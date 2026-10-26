"""生成 AI による補完（推奨は Claude。API モードでは ChatGPT・Gemini・Sakana AI も使える）。

AI には XML も docx も直接編集させない。AI が返すのは「操作」の一覧（JSON）だけで、
Python が 1 件ずつ検証してから、文字列を変えない操作（リンクを付ける・段落の役割を変える・
姓名の区切りを指定する・数式画像に MathML を併記する）として適用する。
適用後は、最後に必ず文字の不変性チェックをやり直す（pipeline.py）。

使い方は 2 通り:
  API モード : AI の API を直接呼ぶ（call_provider）。Claude（ANTHROPIC_API_KEY）、ChatGPT（OPENAI_API_KEY）、
               Gemini（GEMINI_API_KEY または GOOGLE_API_KEY）、Sakana AI（SAKANA_API_KEY）。どれも依頼文と画像を渡し、
               回答の JSON の文字列を受け取るだけで、検証・適用は共通。
  手動モード : 依頼文（プロンプト）を書き出し、利用者が claude.ai などのチャットに貼り付ける。
               返ってきた JSON を貼り戻すと、API モードと同じ検証・適用を行う。
"""
from __future__ import annotations

import base64
import json
import re
import unicodedata
from dataclasses import dataclass, field

from lxml import etree

from .floats import describe, estimate_top_left
from .model import OBJ, LinkSpec, Para
from .omml import MML_NS, OmmlConverter, math_display_text
from .structure import AFTER_BODY_REGIONS, ArticlePlan, _para_text, float_caption

DEFAULT_MODEL = "claude-opus-5-5"

ROLES = {
    "sec1": "章見出し", "sec2": "節見出し", "sec3": "項見出し", "p": "本文段落", "fig_caption": "図キャプション",
    "table_caption": "表キャプション", "quote": "ブロック引用", "ref": "引用文献（参考文献リストの 1 件）",
    "ref_heading": "参考文献見出し", "notes_heading": "付記見出し", "ack_heading": "謝辞見出し",
    "fn_heading": "注見出し", "fn_start": "注の始まり（注の一覧で、新しい注が始まる段落）",
    "abstract": "英文要旨の段落", "title": "題目", "subtitle": "副題",
    "exclude": "論文の本文ではない（テンプレートの装飾など）",
}
_HEADINGS = {"ref_heading", "notes_heading", "ack_heading", "fn_heading"}
REGION_ROLES = {
    "front_ja": {"title", "subtitle", "exclude"},
    "body": {"sec1", "sec2", "sec3", "p", "fig_caption", "table_caption", "quote", "exclude"} | _HEADINGS,
    "notes": {"p", "exclude"} | _HEADINGS, "ack": {"p", "exclude"} | _HEADINGS,
    "fn": {"fn_start", "p", "exclude"} | _HEADINGS, "refs": {"ref", "exclude"} | _HEADINGS, "back": {"p", "exclude"} | _HEADINGS,
    "front_en": {"abstract", "exclude"}, "app": {"p", "exclude"},
    "authors": set(),   # 著者表の中の著者名・所属（確認のために見せるだけで、役割は変えさせない）
}
TARGET_PREFIX = {"link_citation": "B", "link_figure": "F", "link_table": "T", "link_note": "fn", "link_formula": "FD"}
REF_TYPE = {"link_citation": "bibr", "link_figure": "fig", "link_table": "table", "link_note": "fn",
            "link_formula": "disp-formula"}
RE_YEAR = re.compile(r"^(?:(?:1[5-9]|20)\d{2}[a-z]?(?:/(?:1[5-9]|20)\d{2}[a-z]?)?|n\.\s?d\.|印刷中|in press|forthcoming)$", re.I)
MATHML_ELEMENTS = {"math", "mrow", "mi", "mn", "mo", "mtext", "mspace", "ms", "mfrac", "msqrt", "mroot", "msup", "msub",
                   "msubsup", "munder", "mover", "munderover", "mmultiscripts", "mprescripts", "none", "mtable", "mtr",
                   "mtd", "mfenced", "menclose", "mstyle", "mpadded", "mphantom", "merror"}
MATHML_ATTRS = {"mathvariant", "stretchy", "fence", "separator", "accent", "accentunder", "linethickness", "display",
                "columnalign", "notation", "open", "close", "separators", "largeop", "movablelimits", "form",
                "lspace", "rspace", "width", "height", "depth", "bevelled", "displaystyle", "scriptlevel"}

OP_SCHEMA = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["link_citation", "link_figure", "link_table", "link_note", "link_formula",
                                          "set_role", "formula_image", "split_name"]},
        "src": {"type": "string", "description": "対象の段落 ID（例: d18）。formula_image では空文字"},
        "text": {"type": "string", "description": "リンクにする文字列（段落中にあるとおりに完全一致で）。リンク以外の操作では空文字"},
        "occurrence": {"type": "integer", "description": "段落内で text が何回目に現れる箇所か（1 始まり）"},
        "target": {"type": "string", "description": "リンク先 ID（B3, F1, T2, fn1, FD1 など）。リンク以外では空文字"},
        "role": {"type": "string", "description": "set_role の役割名。それ以外では空文字"},
        "image": {"type": "string", "description": "formula_image の画像 ID（img3 など）。それ以外では空文字"},
        "mathml": {"type": "string", "description": "formula_image の MathML（<math> 要素）。それ以外では空文字"},
        "surname": {"type": "string", "description": "split_name の姓。それ以外では空文字"},
        "given": {"type": "string", "description": "split_name の名。それ以外では空文字"},
        "reason": {"type": "string", "description": "判断の根拠（日本語。前後の文脈など、人が確認できるように具体的に）"},
        "confidence": {"type": "string", "enum": ["高", "中", "低"]},
    },
    "required": ["op", "src", "text", "occurrence", "target", "role", "image", "mathml", "surname", "given", "reason",
                 "confidence"],
    "additionalProperties": False,
}
PLACEMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "float": {"type": "string", "description": "図形の ID（s1 など。「位置を決められなかった図表」に挙げたもの）"},
        "after": {"type": "string", "description": "図表を置く位置: Word で表示したときに図の左上の直上にある本文の文章を含む段落の ID"},
        "items": {"type": "array", "description": "図形の中身を、図・表ごとに組にしたもの", "items": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["fig", "table"]},
                "caption": {"type": "array", "items": {"type": "string"},
                            "description": "キャプションの段落 ID（出典などの続きの段落も順に）"},
                "body": {"type": "array", "items": {"type": "string"},
                         "description": "本体: 表 ID（t3 など）、画像 ID（img2 など）、または画像だけの段落 ID"},
            },
            "required": ["kind", "caption", "body"],
            "additionalProperties": False,
        }},
        "reason": {"type": "string", "description": "位置と組み合わせの根拠（日本語で具体的に）"},
        "confidence": {"type": "string", "enum": ["高", "中", "低"]},
    },
    "required": ["float", "after", "items", "reason", "confidence"],
    "additionalProperties": False,
}
# placements を最初に書かせる（回答が長すぎて途中で切れても、図表の位置の指定が残るように。parse_cut_response）。
# JSON スキーマはキーの順を決めないが、構造化出力はスキーマの順に書くことが多いので、properties と required もこの順にする
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "placements": {"type": "array", "items": PLACEMENT_SCHEMA,
                       "description": "位置を決められなかった図表（テキストボックス・グループ図形）の位置と組み合わせ。"
                                      "回答の最初に書く"},
        "operations": {"type": "array", "items": OP_SCHEMA},
        "notes": {"type": "array", "items": {"type": "string"},
                  "description": "操作にはできないが、人が確認すべきと考えたこと（日本語）"},
    },
    "required": ["placements", "operations", "notes"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """あなたは、学術誌『全国数学教育学会誌 数学教育学研究』の論文（Word の docx）を J-STAGE 全文 XML（JATS 1.1）に変換する作業の補助者です。
Python のプログラムがすでに機械的な変換を済ませています。あなたの仕事は、機械処理で取りこぼした箇所を見つけ、「操作」の一覧として提案することです。

絶対の規則:
- 論文の文字は 1 文字も変えてはいけません（誤字脱字に見えても直さない）。あなたが提案できるのは、既存の文字列に対する次の操作だけです。
- 操作の text には、段落中にある文字列を一字一句そのまま書いてください。プログラムが完全一致で探し、見つからなければその操作は捨てられます。

提案できる操作（6 の placements は operations とは別の一覧に書きます）:
1. link_citation: 本文中の引用を引用文献リストの文献にリンクする。リンクにするのは「年」の部分だけです（例: 「Claude (2025)」なら text は「2025」、「中原（1995, p.3）」なら「1995」）。
   機械処理は「著者名（年）」「（著者名, 年）」の形だけを扱います。著者名と年が離れている、括弧がない、著者名の表記が文献リストと異なる、年が食い違う、などで未リンクのものを探してください。
   年が文献リストと食い違う場合（本文 1977 / 文献 1976 など）は、文脈から同じ文献と判断できるときだけ、確度「低」で提案してください。
2. link_figure / link_table / link_note / link_formula: 「図3」「表2」「注4」「式(2)」などの参照を、対応する図・表・注・数式にリンクする（text は「図3」のように参照の表記全体）。
3. set_role: スタイルが正しく設定されておらず、役割を機械的に決められなかった段落の役割を指定する。role には次のいずれかを書く:
   {roles}
   著者表の中の段落（役割 author_ja / aff_ja / author_en / aff_en）は確認のために載せているもので、役割は変えられません。
4. formula_image: 画像として貼り付けられた数式を MathML（MathML 2.0、<math xmlns="http://www.w3.org/1998/Math/MathML"> を根要素とする）に書き起こす。元の画像は残したまま、読み取った数式を併記します。数式でない画像には提案しないでください。
5. split_name: 姓と名の間に空白がない和文の著者名について、姓と名の境目を指定する（surname + given が氏名の文字列と完全に一致すること）。

6. placements（図表の位置と組み合わせ）: 依頼文の「# 位置を決められなかった図表」に挙げた図形（s1 など）は、1 つ残らず、
   必ず placements に 1 件ずつ指定してください（省略できません）。これらは Word のテキストボックスやグループ図形に入った図表
   （2 段組をまたぐ図など）で、docx には Word で表示したときの位置が記録されていないため、プログラムでは置き場所を決められませんでした。
   - after: 図表を置く位置です。Word で表示したときに、図の左上の直上にある本文の文章を含む段落の ID を書いてください（その段落の直後に置きます）。
     図の直上が別の図表なら、さらにその上にある本文の文章を含む段落です。図が段やページの先頭にあるときは、読む順で直前にある本文の段落です。
     依頼文に示した配置の情報（アンカー段落、アンカー段落からの距離、行数による推定）から判断してください。行数による推定は文字数から計算した
     目安で、ページや段の区切りは考慮していません。図の番号の順序（図2 は図1 より後）とも矛盾しないようにしてください。
     after に書けるのは「# 論文の段落一覧」の本文の段落（テキストボックス・グループ図形の中の段落と、表のセルの段落を除く）だけです。
   - items: 図形の中身を、図・表ごとに組にしたものです。kind は fig（図）か table（表）。caption はキャプションの段落 ID
     （「図1　…」の段落と、それに続く出典などの段落を順に）。body は本体で、表 ID（t3 など）、画像 ID（img2 など）、または画像だけの段落 ID。
     問題文などを表で組んだ図は、kind を fig、body をその表にします。1 つの図形に図が 2 つ並んでいる（表の中に画像とキャプションが並んでいる）
     場合は、画像とキャプションのセルの段落を図ごとに組にして、items を 2 つにします。表は kind を table、body をその表 1 つにします。
   - 「# 位置を機械的に決めた図表（変更不可）」に挙げた図形は、位置も組み合わせも確定しています。placements に書かないでください（書いても採用されません）。
   - テキストボックス・グループ図形の中の段落の役割は、set_role ではなく placements で指定してください。

回答の JSON は、placements、operations、notes の順に書いてください（placements を最初に。回答が長すぎて途中で切れても、
図表の位置の指定が残るようにするためです）。

reason には、人が後で確認できるように、判断の根拠を日本語で具体的に書いてください（例: 「第3章第2段落の『その後の論考（2001）』は、直前の主語『国宗は』から国宗（2001）と判断」）。
confidence は 高・中・低 のいずれか。自信がないものは提案しないか、「低」としてください。
操作にできない気づき（文献リストに見当たらない文献の引用、図番号の欠番など）は notes に書いてください。

注についても必ず確認してください: 本文中の注番号（上付きの「1)」など）と、注の一覧（[fn1] など）の対応を確かめ、
上付きになっていないなどの理由で未リンクの注番号は link_note でリンクしてください。番号の飛び・重複、本文から参照されていない注、
本文の注番号の位置の文脈と注の内容が合わない（番号の付け違いと思われる）ものは、操作にせず notes に書いてください。
注の一覧は、番号（「1)」「（注1）」など）で始まる段落から新しい注、番号のない段落は前の注の続きとして機械的に区切っています。
番号の書き方が想定外で複数の注が 1 件にまとめられている場合は、新しい注が始まる段落を set_role の fn_start に、
誤って分けられた続きの段落を set_role の p（前の注の続き）にしてください（注の一覧の段落でだけ指定できます）。
fn_start で新しく分けた注へリンクするときは、link_note の target に、その注の最初の段落の ID（d42 など）を書いてください。"""


@dataclass
class AIOutcome:
    mode: str = "none"                # none / api / manual
    model: str = ""
    provider: str = "claude"          # API モードで使った AI（PROVIDERS のキー）
    accepted: list = field(default_factory=list)    # (op, Decision)
    rejected: list = field(default_factory=list)    # (op, 理由)
    notes: list = field(default_factory=list)
    error: str = ""
    usage: dict = field(default_factory=dict)
    raw: str = ""
    model_note: str = ""              # 指定と違うモデルを使った場合の説明
    cut: bool = False                 # API の回答が長すぎて途中で切れた（raw は切れたところまで）
    partial: str = ""                 # 途中で切れた回答から、図表の位置の指定（placements）の一部だけを反映したときの説明（要対応）


# ---------------------------------------------------------------------------- AI に渡す資料
def para_view(p: Para) -> str:
    out = []
    for a in p.atoms:
        if a.kind == "text":
            out.append(a.text)
        elif a.kind == "math":
            mml = OmmlConverter().convert(a.math, a.display)
            out.append(f"⟦数式: {math_display_text(mml)}⟧")
        elif a.kind == "image":
            out.append(f"⟦画像 {a.image.image_id}: {a.image.width_cm:.1f}cm×{a.image.height_cm:.1f}cm⟧")
        elif a.kind == "fnref":
            out.append("⟦Word の脚注参照⟧")
    s = "".join(out)
    return s


def para_view_with_links(p: Para) -> str:
    """リンク済みの箇所を «文字→リンク先» の形で示した段落の文字列。"""
    out = []
    cur = None
    buf = ""
    for a in p.atoms:
        spec = a.link
        if spec is not cur:
            if cur is not None and buf:
                out.append(f"«{buf}→{_spec_label(cur)}»")
            elif buf:
                out.append(buf)
            buf = ""
            cur = spec
        if a.kind == "text":
            buf += a.text
        else:
            buf += para_view(Para(src="", atoms=[a]))
    if cur is not None and buf:
        out.append(f"«{buf}→{_spec_label(cur)}»")
    elif buf:
        out.append(buf)
    return "".join(out)


def _spec_label(spec: LinkSpec) -> str:
    if spec.kind == "xref":
        return spec.attrs.get("rid", "")
    if spec.kind in ("uri", "ext-link", "pub-id"):
        return "URL"
    return spec.kind


def build_request(plan: ArticlePlan, linker, build_exclusions=(), unsplit_names=()) -> tuple:
    """AI への依頼（本文の文字列と画像）を作る。戻り値: (テキスト, [画像: (image_id, media_type, bytes)])"""
    lines = []
    lines.append("# 論文の段落一覧")
    lines.append("各行は [段落ID]（現在の役割 / 位置 / Word のスタイル名）本文。«文字→ID» はすでにリンク済みの箇所。")
    lines.append("⟦数式: …⟧ は数式、⟦画像 imgN: …⟧ は画像を表す（これらは文字ではないのでリンクの text に含めない）。\n")
    for src, p in plan.paras.items():
        region = plan.region.get(src, "")
        if not region and not p.in_textbox:
            continue
        role = p.role or region
        loc = plan.locations.get(src, "")
        if p.float_id:
            loc = f"図形 {p.float_id} の中"
        text = para_view_with_links(p)
        if not text.strip():
            continue
        lines.append(f"[{src}]（{role} / {loc} / {p.style_name}）{text}")
    lines.append("\n# 引用文献リスト")
    for r in plan.refs:
        lines.append(f"[{r.rid}] {para_view(r.para)}")
    lines.append("\n# 図・表・注・数式")
    for f in plan.figures:
        cap = _para_text(f.caption) if f.caption is not None else "（キャプションなし）"
        imgs = ", ".join(i.image_id for ip in f.image_paras for i in ip.images)
        lines.append(f"[{f.fid or '-'}] 図 {cap}（画像: {imgs or 'なし'}）")
    for t in plan.tables:
        cap = _para_text(t.caption) if t.caption is not None else "（キャプションなし）"
        lines.append(f"[{t.tid}] 表 {cap}")
    for fn in plan.fns:
        where = "Word の脚注" if fn.word_note else "段落 " + ", ".join(p.src for p in fn.paras)
        lines.append(f"[{fn.fid}]（{where}）注 {(fn.paras[0].autonum or '')}{para_view(fn.paras[0])[:80]}")
    for fm in plan.formulas:
        if fm.fid:
            lines.append(f"[{fm.fid}] 数式 番号 {fm.label}")
    lines.append("\n# 機械処理で解決できなかった箇所")
    for item in linker.unresolved:
        cat, src, raw, detail = item[:4]
        lines.append(f"- [{src}] {cat}: 「{raw}」 … {detail}")
    for d in plan.decisions:
        if d.category in ("style", "formula", "figure", "table", "note"):
            lines.append(f"- [{d.src}] 推定: {d.message}")
    for fn in plan.fns:
        if not fn.word_note and fn.number is None:
            lines.append(f"- [{fn.fid}] 注の先頭に番号を読み取れなかった（段落 {', '.join(p.src for p in fn.paras)} を 1 件の注とした）")
    for p in plan.paras.values():
        if p.note == "style_unknown":
            lines.append(f"- [{p.src}] スタイル「{p.style_name}」は想定外のため本文段落として扱った: 「{_para_text(p)[:40]}」")
    unc = plan.uncited_refs
    if unc:
        lines.append(f"- 本文でリンクされていない文献: {', '.join(unc)}（本文中に引用があれば link_citation を提案）")
    for e in list(plan.exclusions) + list(build_exclusions):
        if e.text.strip():
            lines.append(f"- [{e.src}] 出力から除外: {e.reason}: 「{e.text[:60]}」（本文の一部なら set_role を提案）")
    for src, text in unsplit_names:
        lines.append(f"- [{src}] 姓と名の区切りがない氏名: 「{text}」")
    images = []
    for f in plan.figures:
        for ip in f.image_paras:
            for img in ip.images:
                if f.caption is None and img.target:
                    images.append(img)
    lines += float_section(plan, images)
    seen = set()
    images = [i for i in images if not (i.image_id in seen or seen.add(i.image_id))]
    return "\n".join(lines), images


def float_section(plan: ArticlePlan, images: list) -> list:
    """依頼文の「位置を決められなかった図表」と「位置を機械的に決めた図表（変更不可）」の節。images に添付する画像を足す。"""
    if not plan.floats:
        return []
    lines = []
    unplaced = [info for info in plan.floats.values() if info.mode == "unplaced"]
    fixed = [info for info in plan.floats.values() if info.mode != "unplaced"]
    lay = plan.layout
    if unplaced:
        lines.append("\n# 位置を決められなかった図表（テキストボックス・グループ図形）")
        lines.append("以下のすべてについて、placements に位置（after）と組み合わせ（items）を必ず指定してください。")
        if lay and lay.columns:
            lines.append(f"本文の体裁: {lay.columns} 段組、1 段の幅 {lay.column_width_cm:.1f} cm（1 行 約 {lay.chars_per_line:.0f} 字）、"
                         f"行送り {lay.line_pitch_cm:.2f} cm（1 段 約 {lay.text_height_cm / lay.line_pitch_cm:.0f} 行）、"
                         f"本文の幅 {lay.text_width_cm:.1f} cm")
        seq = plan.body_seq
        for info in unplaced:
            fl = info.float
            anchor = plan.paras.get(fl.anchor_src)
            lines.append(f"\n[{fl.fid}] アンカー段落: [{fl.anchor_src}]「{_para_text(anchor)[:30] if anchor else ''}」")
            lines.append(f"  docx に記録された位置: {describe(fl, lay)}")
            k = seq.index(fl.anchor_src) if fl.anchor_src in seq else -1
            est = estimate_top_left(fl, lay, [plan.paras[x] for x in seq[k:k + 40]], seq[k - 1] if k > 0 else "") \
                if k >= 0 else None
            if est and est[0]:
                lines.append(f"  行数による推定: 図の左上の直上の本文は段落 [{est[0]}]（{est[1]}）")
            else:
                lines.append("  行数による推定: できない（縦の位置がアンカー段落を基準にしていない、または別の段にあるため）。"
                             "アンカー段落の前後と本文中の参照から判断してください")
            lines.append("  中身:")
            for q in info.paras:
                if q.is_blank and not q.images:
                    continue
                lines.append(f"    段落 [{q.src}]（スタイル: {q.style_name}）{para_view(q)[:80]}")
                images.extend(i for i in q.images if i.target)
            for t in info.tables:
                cells = [c for c in t.paragraphs() if not c.is_blank or c.images]
                lines.append(f"    表 {t.tid}（{len(t.rows)} 行。セルの段落: "
                             + "、".join(f"[{c.src}]{para_view(c)[:30]}" for c in cells[:12])
                             + ("…" if len(cells) > 12 else "") + "）")
                images.extend(i for c in cells for i in c.images if i.target)
            for img in info.images:
                lines.append(f"    画像 {img.image_id}（グループ図形の画像。{img.width_cm:.1f}cm×{img.height_cm:.1f}cm）")
                if img.target:
                    images.append(img)
            if info.reason:
                lines.append(f"  機械的に決められなかった理由: {info.reason}")
    if fixed:
        lines.append("\n# 位置を機械的に決めた図表（変更不可。placements に書かないこと）")
        for info in fixed:
            fl = info.float
            caps = [q for q in info.paras if q.role in ("fig_caption", "table_caption")]
            in_cells = any(c.role in ("fig_caption", "table_caption") for t in info.tables for c in t.paragraphs())
            if caps:
                what = "「" + _para_text(caps[0])[:30] + "」"
            elif in_cells:
                what = float_caption(info)      # 表のセルの画像とキャプションで組んだ図（structure.Classifier.cell_figures）
            else:
                what = "（キャプションなし）"
            how = (f"段落 [{fl.anchor_src}] の前に配置済み" if info.mode == "mechanical" else "AI の指定で配置済み")
            lines.append(f"[{fl.fid}] {what}: {how}")
    return lines


def image_blocks(doc, images):
    """AI に見せる画像（png / jpg / gif のみ。EMF などは変換できれば変換する）。"""
    blocks = []
    for img in images:
        data = doc.media.get(img.target)
        if data is None:
            continue
        ext = img.target.rsplit(".", 1)[-1].lower()
        mt = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif"}.get(ext)
        if mt is None and ext in ("emf", "wmf"):
            from .images import convert_metafile
            png, _ = convert_metafile(data, ext, min_width_px=800)
            if png:
                data, mt = png, "image/png"
        if mt is None:
            continue
        blocks.append((img.image_id, mt, data))
    return blocks


# ---------------------------------------------------------------------------- API / 手動
AUTO_MODEL = "auto"     # 「自動」: 使える最新の Opus を Models API で調べて使う
MODELS_PAGE = "https://platform.claude.com/docs/en/models/overview"
PROVIDERS = {"claude": "Claude", "openai": "ChatGPT", "gemini": "Gemini", "sakana": "Sakana AI"}
API_KEY_NAMES = {"claude": ("ANTHROPIC_API_KEY",), "openai": ("OPENAI_API_KEY",),
                 "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"), "sakana": ("SAKANA_API_KEY",)}
SAKANA_BASE_URL = "https://api.sakana.ai/v1"   # Sakana AI（Namazu・Fugu）の OpenAI 互換 API


def system_prompt() -> str:
    return SYSTEM_PROMPT.replace("{roles}", " / ".join(f"{k}（{v}）" for k, v in ROLES.items()))


def latest_opus(client) -> str:
    """Models API（使えるモデルの一覧）から、いちばん新しい Opus のモデル ID を返す。調べられなければ空文字。"""
    try:
        models = [m for m in client.models.list() if str(m.id).startswith("claude-opus-")]
    except Exception:  # noqa: BLE001
        return ""
    models.sort(key=lambda m: str(getattr(m, "created_at", "")), reverse=True)
    return models[0].id if models else ""


def call_api(request_text, images, model=DEFAULT_MODEL, api_key=None, effort="high") -> AIOutcome:
    """Claude API を呼ぶ。

    モデルは既定で動作確認済みの DEFAULT_MODEL。"auto" なら使える最新の Opus を調べて使う。
    指定したモデルが見つからない（提供終了など）ときは、最新の Opus に切り替えて 1 回だけやり直し、その旨を残す。
    """
    import anthropic
    out = AIOutcome(mode="api", model=model)
    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    content = []
    for image_id, mt, data in images:
        content.append({"type": "text", "text": f"画像 {image_id}:"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": mt,
                                                   "data": base64.standard_b64encode(data).decode("ascii")}})
    content.append({"type": "text", "text": request_text})
    system = system_prompt()

    def send(model_id):
        kwargs = dict(model=model_id, max_tokens=64000, system=system, messages=[{"role": "user", "content": content}],
                      output_config={"effort": effort, "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}})
        try:
            # 安全上の判定で断られた場合に、サーバー側で別のモデルに切り替えて続ける（fallbacks）
            with client.beta.messages.stream(betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                                             **kwargs) as stream:
                return stream.get_final_message()
        except anthropic.BadRequestError:
            # ベータ機能が使えない環境・モデルでは通常の呼び出しでやり直す
            with client.messages.stream(**kwargs) as stream:
                return stream.get_final_message()

    try:
        if model == AUTO_MODEL:
            model = latest_opus(client) or DEFAULT_MODEL
            out.model = model
            out.model_note = f"「自動」を選んだため、使える最新の Opus（{model}）を使った"
        try:
            msg = send(model)
        except anthropic.NotFoundError:
            alt = latest_opus(client)
            if not alt or alt == model:
                raise
            out.model_note = (f"指定したモデル {model} が使えなかった（提供終了など）ため、使える最新の Opus（{alt}）に"
                              "切り替えた")
            out.model = model = alt
            msg = send(model)
    except anthropic.AuthenticationError:
        out.error = "API キーが無効です（Colab では「シークレット」に ANTHROPIC_API_KEY を登録してください）"
        return out
    except anthropic.NotFoundError:
        out.error = f"モデル {model} が見つかりません。モデル名を確認してください（一覧: {MODELS_PAGE}）"
        return out
    except anthropic.RateLimitError:
        out.error = "API の利用制限に達しました。しばらく待ってから再実行してください"
        return out
    except anthropic.APIStatusError as e:
        out.error = f"API エラー（{e.status_code}）: {e.message}"
        return out
    except anthropic.APIConnectionError:
        out.error = "API に接続できませんでした（ネットワークを確認してください）"
        return out
    if msg.stop_reason == "refusal":
        out.error = "AI が回答を断りました（安全上の判定）。手動モードで再試行してください"
        return out
    text = next((b.text for b in msg.content if b.type == "text"), "")
    out.raw = text
    u = getattr(msg, "usage", None)
    if u is not None:
        out.usage = {"input_tokens": getattr(u, "input_tokens", None), "output_tokens": getattr(u, "output_tokens", None)}
    if msg.stop_reason == "max_tokens":
        # 切れたところまでの回答（raw）は残す。最後まで書かれた図表の位置の指定だけを読む（pipeline・parse_cut_response）
        out.error = "AI の回答が長すぎて途中で切れました"
        out.cut = True
    return out


def call_provider(provider, request_text, images, model=None, api_key=None) -> AIOutcome:
    """API モードの入口。どの AI でも、依頼文と画像を渡して回答の JSON の文字列（AIOutcome.raw）を受け取るだけ。

    推奨は Claude（依頼文と動作確認は Claude で行っている）。Claude 以外ではモデルを利用者が指定する
    （Claude Opus と同等以上のモデルを推奨）。
    """
    if provider == "claude":
        return call_api(request_text, images, model=model or DEFAULT_MODEL, api_key=api_key)
    if provider not in PROVIDERS:
        return AIOutcome(mode="api", model=model or "", provider=provider, error=f"API の種類 {provider} には対応していません")
    out = AIOutcome(mode="api", model=(model or "").strip(), provider=provider)
    if not out.model or out.model == AUTO_MODEL or out.model.startswith("claude-"):
        out.error = (f"{PROVIDERS[provider]} の API を使うときは、使うモデルの名前を指定してください"
                     "（Claude Opus と同等以上の性能のモデルを推奨します）")
        return out
    call = {"openai": call_openai, "gemini": call_gemini, "sakana": call_sakana}[provider]
    return call(request_text, images, out, api_key)


def _key_error(provider) -> str:
    return (f"API キーが無効です（Colab では「シークレット」に {' または '.join(API_KEY_NAMES[provider])} として"
            f"{PROVIDERS[provider]} の API キーを登録してください）")


def _openai_client(provider, out: AIOutcome, api_key=None, base_url=None):
    """openai ライブラリのクライアントを作る（ChatGPT と、OpenAI 互換の API）。作れなければ out.error に理由を入れて None。"""
    try:
        import openai
    except ImportError:
        out.error = f"{PROVIDERS[provider]} の API を使うためのライブラリ openai がインストールされていません（pip install openai）"
        return None, None
    names = " または ".join(API_KEY_NAMES[provider])
    if base_url and not api_key:
        # 接続先が OpenAI でないときは、環境変数 OPENAI_API_KEY（別の会社のキー）を送らないように、キーを必ず明示する
        out.error = f"{PROVIDERS[provider]} の API キーが指定されていません（{names} を確認してください）"
        return openai, None
    kwargs = {"timeout": 1800, "base_url": base_url} if base_url else {"timeout": 1800}
    try:
        return openai, (openai.OpenAI(api_key=api_key, **kwargs) if api_key else openai.OpenAI(**kwargs))
    except openai.OpenAIError as e:   # API キーが見つからないときなど
        out.error = f"{PROVIDERS[provider]} の API を使う準備ができませんでした（{names} を確認してください）: {e}"
        return openai, None


def _openai_error(openai, e, provider, model) -> str:
    """openai ライブラリの例外を、利用者向けの説明にする。"""
    if isinstance(e, openai.AuthenticationError):
        return _key_error(provider)
    if isinstance(e, openai.NotFoundError):
        return f"モデル {model} が見つかりません（または使う権限がありません）。モデル名を確認してください"
    if isinstance(e, openai.RateLimitError):
        return "API の利用制限に達しました（または利用料の残高が足りません）。確認してから再実行してください"
    if isinstance(e, openai.APIStatusError):
        return f"API エラー（{e.status_code}）: {e.message}"
    if isinstance(e, openai.APIConnectionError):
        return "API に接続できませんでした（ネットワークを確認してください）"
    return f"API エラー: {e}"


def call_openai(request_text, images, out: AIOutcome, api_key=None) -> AIOutcome:
    """ChatGPT（OpenAI の Responses API）を呼ぶ。回答は Claude と同じ JSON スキーマで受け取る（構造化出力）。"""
    openai, client = _openai_client("openai", out, api_key)
    if client is None:
        return out
    content = []
    for image_id, mt, data in images:
        content.append({"type": "input_text", "text": f"画像 {image_id}:"})
        content.append({"type": "input_image", "detail": "high",
                        "image_url": f"data:{mt};base64,{base64.standard_b64encode(data).decode('ascii')}"})
    content.append({"type": "input_text", "text": request_text})
    try:
        resp = client.responses.create(
            model=out.model, instructions=system_prompt(), input=[{"role": "user", "content": content}],
            text={"format": {"type": "json_schema", "name": "jasme_operations", "schema": RESPONSE_SCHEMA,
                             "strict": True}})
    except openai.OpenAIError as e:
        out.error = _openai_error(openai, e, "openai", out.model)
        return out
    for item in getattr(resp, "output", None) or []:
        for c in getattr(item, "content", None) or []:
            if getattr(c, "type", "") == "refusal":
                out.error = "AI が回答を断りました（安全上の判定）。手動モードで再試行してください"
                return out
    if getattr(resp, "status", "") == "incomplete":
        reason = getattr(getattr(resp, "incomplete_details", None), "reason", "")
        out.error = ("AI の回答が長すぎて途中で切れました" if reason == "max_output_tokens"
                     else f"AI の回答が途中で止まりました（{reason}）")
        if reason == "max_output_tokens":
            out.raw, out.cut = getattr(resp, "output_text", None) or "", True     # 切れたところまで（call_api と同じ）
        return out
    out.raw = resp.output_text or ""
    if not out.raw:
        out.error = "AI から回答が返ってきませんでした"
    u = getattr(resp, "usage", None)
    if u is not None:
        out.usage = {"input_tokens": getattr(u, "input_tokens", None), "output_tokens": getattr(u, "output_tokens", None)}
    return out


def call_sakana(request_text, images, out: AIOutcome, api_key=None) -> AIOutcome:
    """Sakana AI（Sakana Namazu・Sakana Fugu）を呼ぶ。OpenAI 互換の Chat Completions API で、接続先だけが違う。

    JSON スキーマの指定（構造化出力）は、受け付けられなければ指定なしで 1 回だけやり直す。
    どちらでも答えられるように、依頼文に回答の形式（見本と項目の説明）を入れておく。
    """
    openai, client = _openai_client("sakana", out, api_key, base_url=SAKANA_BASE_URL)
    if client is None:
        return out
    content = []
    for image_id, mt, data in images:
        content.append({"type": "text", "text": f"画像 {image_id}:"})
        content.append({"type": "image_url",
                        "image_url": {"url": f"data:{mt};base64,{base64.standard_b64encode(data).decode('ascii')}"}})
    content.append({"type": "text", "text": request_text})
    system = (f"{system_prompt()}\n\n## 回答の書き方\n"
              "- 回答は次の見本の形の JSON だけにしてください（前後に説明を書かない）。文字列は半角の二重引用符（\"）で囲んでください。\n"
              f"- 提案する操作がなければ \"operations\": [] とし、気づいたことだけを notes に書いてください。\n\n"
              f"{MANUAL_EXAMPLE}\n\n{FIELD_GUIDE}")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": content}]
    schema = {"type": "json_schema", "json_schema": {"name": "jasme_operations", "schema": RESPONSE_SCHEMA, "strict": True}}
    try:
        try:
            resp = client.chat.completions.create(model=out.model, messages=messages, response_format=schema)
        except openai.BadRequestError:
            resp = client.chat.completions.create(model=out.model, messages=messages)
            out.model_note = "JSON スキーマの指定（構造化出力）を受け付けなかったため、指定なしでやり直した"
    except openai.OpenAIError as e:
        out.error = _openai_error(openai, e, "sakana", out.model)
        return out
    choice = (getattr(resp, "choices", None) or [None])[0]
    msg = getattr(choice, "message", None)
    if getattr(msg, "refusal", None) or getattr(choice, "finish_reason", "") == "content_filter":
        out.error = "AI が回答を断りました（安全上の判定）。手動モードで再試行してください"
        return out
    if getattr(choice, "finish_reason", "") == "length":
        out.error = "AI の回答が長すぎて途中で切れました"
        out.raw, out.cut = getattr(msg, "content", None) or "", True             # 切れたところまで（call_api と同じ）
        return out
    out.raw = getattr(msg, "content", None) or ""
    if not out.raw:
        out.error = "AI から回答が返ってきませんでした"
    u = getattr(resp, "usage", None)
    if u is not None:
        out.usage = {"input_tokens": getattr(u, "prompt_tokens", None), "output_tokens": getattr(u, "completion_tokens", None)}
    return out


def call_gemini(request_text, images, out: AIOutcome, api_key=None) -> AIOutcome:
    """Gemini（Google の Gemini API）を呼ぶ。回答は Claude と同じ JSON スキーマで受け取る（構造化出力）。"""
    try:
        from google import genai
        from google.genai import errors, types
    except ImportError:
        out.error = "Gemini の API を使うためのライブラリ google-genai がインストールされていません（pip install google-genai）"
        return out
    try:
        client = genai.Client(api_key=api_key) if api_key else genai.Client()
    except Exception as e:  # noqa: BLE001  API キーが見つからないときなど
        out.error = f"Gemini の API を使う準備ができませんでした（{' または '.join(API_KEY_NAMES['gemini'])} を確認してください）: {e}"
        return out
    parts = []
    for image_id, mt, data in images:
        parts.append(types.Part.from_text(text=f"画像 {image_id}:"))
        parts.append(types.Part.from_bytes(data=data, mime_type=mt))
    parts.append(types.Part.from_text(text=request_text))
    config = types.GenerateContentConfig(system_instruction=system_prompt(), response_mime_type="application/json",
                                         response_json_schema=RESPONSE_SCHEMA)
    try:
        resp = client.models.generate_content(model=out.model, contents=[types.Content(role="user", parts=parts)],
                                              config=config)
    except errors.APIError as e:
        msg = str(getattr(e, "message", "") or e)
        if e.code in (401, 403) or "API key" in msg or "API_KEY" in msg:
            out.error = _key_error("gemini")
        elif e.code == 404:
            out.error = f"モデル {out.model} が見つかりません。モデル名を確認してください"
        elif e.code == 429:
            out.error = "API の利用制限に達しました。しばらく待ってから再実行してください"
        else:
            out.error = f"API エラー（{e.code}）: {msg}"
        return out
    except Exception as e:  # noqa: BLE001  通信の失敗など
        out.error = f"API に接続できませんでした（{type(e).__name__}）。ネットワークを確認してください"
        return out
    block = getattr(getattr(resp, "prompt_feedback", None), "block_reason", None)
    if block:
        out.error = f"AI が回答を断りました（安全上の判定: {block}）。手動モードで再試行してください"
        return out
    cand = (getattr(resp, "candidates", None) or [None])[0]
    reason = str(getattr(getattr(cand, "finish_reason", None), "value", getattr(cand, "finish_reason", "")) or "")
    if reason == "MAX_TOKENS":
        out.error = "AI の回答が長すぎて途中で切れました"
        try:
            out.raw = getattr(resp, "text", None) or ""                           # 切れたところまで（call_api と同じ）
        except Exception:  # noqa: BLE001  文字以外の部分しかないときなど
            out.raw = ""
        out.cut = True
        return out
    if reason and reason not in ("STOP", "FINISH_REASON_UNSPECIFIED"):
        out.error = f"AI の回答が途中で止まりました（{reason}）。手動モードで再試行してください"
        return out
    out.raw = getattr(resp, "text", None) or ""
    if not out.raw:
        out.error = "AI から回答が返ってきませんでした"
    u = getattr(resp, "usage_metadata", None)
    if u is not None:
        output = (getattr(u, "candidates_token_count", None) or 0) + (getattr(u, "thoughts_token_count", None) or 0)
        out.usage = {"input_tokens": getattr(u, "prompt_token_count", None), "output_tokens": output}
    return out


MANUAL_EXAMPLE = """```json
{
  "placements": [
    {"float": "s1", "after": "d47", "items": [{"kind": "fig", "caption": ["d52", "d53"], "body": ["t3"]}],
     "reason": "図の上端はアンカー段落 d48 の上端から約 1.8 行下で、推定では直上の本文は d47。図1 の初出（d46）より後", "confidence": "中"}
  ],
  "operations": [
    {"op": "link_citation", "src": "d18", "text": "2001", "occurrence": 1, "target": "B2", "role": "", "image": "",
     "mathml": "", "surname": "", "given": "", "reason": "第1章第3段落の「その後の論考（2001）」は、主語「国宗は」から国宗（2001）と判断", "confidence": "高"},
    {"op": "set_role", "src": "d46", "text": "", "occurrence": 1, "target": "", "role": "sec1", "image": "",
     "mathml": "", "surname": "", "given": "", "reason": "「２．考察」は章番号の形式で、前後の章見出しと同じ書き方", "confidence": "中"}
  ],
  "notes": ["本文の「Lakatos（1977）」は文献リストでは 1976 年になっている"]
}
```"""

FIELD_GUIDE = """回答は placements、operations、notes の順に書く（placements を最初に）。

placements（位置を決められなかった図表ごとに 1 件。依頼文に「# 位置を決められなかった図表」がなければ []）の各項目:
- float: 図形の ID（s1 など）
- after: 図表を置く位置（Word で表示したときに図の左上の直上にある本文の文章を含む段落の ID。その段落の直後に置く）
- items: 図・表ごとの組。kind（fig / table）、caption（キャプションの段落 ID の一覧）、body（表 ID・画像 ID・画像だけの段落 ID の一覧）
- reason, confidence: 下の operations と同じ

operations の各項目の意味（すべての操作に 12 項目すべてを書き、使わない項目は空文字 "" にする。occurrence は数値）:
- op: 操作の種類（link_citation / link_figure / link_table / link_note / link_formula / set_role / formula_image / split_name）
- src: 対象の段落 ID（d18 など。formula_image では ""）
- text: リンクにする文字列（段落中のとおりに完全一致。引用文献なら年の部分だけ）
- occurrence: その段落で text が何回目に現れる箇所か（1 から数える）
- target: リンク先の ID（B3, F1, T2, fn1, FD1 など）
- role: set_role で指定する役割
- image: formula_image の画像 ID（img3 など）
- mathml: formula_image で読み取った数式（<math xmlns="http://www.w3.org/1998/Math/MathML"> から </math> まで）
- surname, given: split_name の姓と名
- reason: 判断の根拠（日本語で具体的に）
- confidence: 高 / 中 / 低"""


def manual_prompt(request_text, images) -> str:
    """手動モード: チャットに貼り付ける依頼文。

    チャットの AI は、回答を地の文で書くと引用符を飾り文字（“ ”）に変えることがあり、JSON として読めなくなる。
    そのため、回答をコードブロック 1 つにまとめるよう求め、形式の見本を示す。
    """
    system = system_prompt()
    img_note = ""
    if images:
        names = "、".join(f"{i}.{mt.split('/')[-1].replace('jpeg', 'jpg')}" for i, mt, _ in images)
        img_note = (f"\n\n（この依頼には画像が {len(images)} 枚あります。出力フォルダの「AI添付画像」にある {names} を"
                    "このメッセージに添付してください。ファイル名が画像 ID です。）")
    return (f"{system}{img_note}\n\n"
            "## 回答の書き方（必ず守ってください）\n"
            "- 回答は、```json で始まり ``` で終わるコードブロック 1 つだけにしてください。コードブロックの前後には何も書かないでください。\n"
            "- アーティファクトやファイルにはせず、この会話の中にコードブロックとして書いてください。\n"
            "- 文字列はすべて半角の二重引用符（\"）で囲んでください。飾りの引用符（“ ” ‘ ’）は使わないでください。\n"
            "- JSON は placements、operations、notes の順に書いてください（placements を最初に。回答が途中で切れても、"
            "図表の位置の指定が残るようにするためです）。\n"
            "- 「# 位置を決められなかった図表」に挙げた図形は、すべて placements に書いてください（省略できません）。"
            "なければ \"placements\": [] としてください。\n"
            "- 提案する操作がなければ \"operations\": [] とし、気づいたことだけを notes に書いてください。\n\n"
            "回答の見本（形式の見本です。内容はこの論文とは関係ありません）:\n"
            f"{MANUAL_EXAMPLE}\n\n"
            f"{FIELD_GUIDE}\n\n"
            "---\n"
            f"{request_text}\n")


SMART_QUOTES = "“”„‟‘’‚‛＂"


def parse_response(text: str) -> dict:
    """AI の回答（JSON）を読む。```json のコードブロックがあればその中身を使う。

    書式の崩れた回答を推測で直すことはしない。読めないときは、どこが・なぜ読めないかを示す。JSON の前後の文字（前置きの説明や、
    閉じの ``` のないコードブロックの後ろの説明など）は使わず、最初の { から最後の } までを読む（_before_trailing_text）。
    途中で切れた回答は読めない（ValueError）。最後まで書かれた図表の位置の指定だけは parse_cut_response で読める。
    """
    t, _ = _json_text(text)
    if not t.startswith("{"):
        i, j = t.find("{"), t.rfind("}")
        if i < 0 or j <= i:
            raise ValueError("回答の中に JSON（{ で始まり } で終わる部分）が見つかりません。"
                             "AI に「回答の書き方」に従ってコードブロックで出し直すよう頼んでください")
        t = t[i:j + 1]
    try:
        data = json.loads(t)
    except json.JSONDecodeError as e:
        data = _before_trailing_text(t, e)
        if data is None:
            line = t.splitlines()[e.lineno - 1] if 0 < e.lineno <= len(t.splitlines()) else ""
            hint = ""
            if any(q in line for q in SMART_QUOTES):
                hint = ("回答の中で、文字列が半角の \" ではなく飾りの引用符（“ ” など）で囲まれています。"
                        "AI に「文字列は半角の二重引用符で、```json のコードブロックで出し直してください」と頼み、"
                        "コードブロック右上のコピーボタンでコピーしてください。")
            elif cut_at_end(e, t):
                hint = CUT_HINT
            raise ValueError(f"{e.lineno} 行目 {e.colno} 文字目で JSON として読めません（{e.msg}）。"
                             f"該当行: {line[:80]!r}。{hint}") from None
    if not isinstance(data, dict) or not isinstance(data.get("operations", []), list):
        raise ValueError("JSON に operations の一覧がありません")
    if not isinstance(data.get("placements", []), list):
        raise ValueError("JSON の placements が一覧（[ ]）になっていません")
    return data


def _before_trailing_text(t: str, e: json.JSONDecodeError):
    """JSON の後ろに文字が続く回答（e が「Extra data」）を、最後の } までで読み直す。読めなければ None。

    閉じの ``` のないコードブロックの後ろに説明が続く回答など。0.21.0 は、コードブロックの閉じがないと回答全体の最初の {
    から最後の } までを読んでいたので、その読み方に合わせる（後ろの文字は使わない。前置きの文字を読み飛ばすのと同じ）。
    後ろの文字に } があるとき（JSON が 2 つ続くときなど）は読めない。途中で切れた回答（parse_cut_response）には使わない。
    """
    j = t.rfind("}")
    if e.msg != "Extra data" or not 0 < j < len(t) - 1:
        return None
    try:
        return json.loads(t[:j + 1])
    except json.JSONDecodeError:
        return None


# 回答のコードブロック。始まりの ```（json）のすぐ後ろは {、閉じの ``` は行の頭にあるものだけ（JSON の文字列の中の ``` を
# コードブロックの始まり・閉じとみなさない。文字列は改行を含められないので、中の ``` は行の頭に来ない）。閉じの ``` がなければ
# 最後まで（回答が途中で切れると閉じがない）
RE_FENCE = re.compile(r"```[ \t]*(?:json|JSON)?[ \t]*\n?(?=\s*\{)(.*?)(^[ \t]*```|\Z)", re.S | re.M)
# 途中で切れた回答の案内（parse_response の読み取りの誤り）
CUT_HINT = ("回答が途中で切れている可能性があります。チャットで「回答が途中で切れました。同じ形式で最初から出し直して"
            "ください」と頼み、新しい回答を最初から最後まで貼り付けてください（続きだけを貼り付けても読めません）。")


def _json_text(text: str) -> tuple:
    """回答から JSON の部分を取り出す。戻り値: (JSON の部分, コードブロックが閉じの ``` で閉じているか)。

    回答が { で始まるとき（コードブロックの中身だけをコピーした回答など）は、回答全体（文字列の中の ``` をコードブロックと
    みなさない）。そうでなければ、```json から始まるコードブロック（RE_FENCE）の中身（閉じの ``` がなければ最後まで）。
    コードブロックがなければ回答全体。
    """
    t = text.strip()
    if t.startswith("{"):
        return t, False
    m = RE_FENCE.search(t)
    return (m.group(1).strip(), bool(m.group(2))) if m else (t, False)


# 値の書きかけ（数・true・false・null の途中）
RE_PARTIAL_LITERAL = re.compile(r"^(?:-?[0-9.eE+-]*|t(?:r(?:ue?)?)?|f(?:a(?:l(?:se?)?)?)?|n(?:u(?:ll?)?)?)$")


def cut_at_end(e: json.JSONDecodeError, t: str) -> bool:
    """JSON の読み取りの誤り e が、回答が途中で切れたときの形か（それより前は JSON として正しい）。

    文字列の途中で入力が終わった（Unterminated string。閉じの " が見つからないまま終わったときだけ出る）か、
    「Expecting …」の誤りで、その位置から後ろが空か、値の書きかけ（数・true・false・null の途中）だけのとき。
    途中の書き損じ（飾りの引用符など）は、切れた回答ではない。最後まで書かれた回答で、最後の文字列の閉じだけが飾りの引用符
    のときも「Unterminated string」になるので、その文字列（e.pos から後ろ）に飾りの引用符があれば、切れた形とみなさない。
    """
    if e.msg.startswith("Unterminated string"):
        return not any(q in t[e.pos:] for q in SMART_QUOTES)
    return e.msg.startswith("Expecting") and bool(RE_PARTIAL_LITERAL.match(t[e.pos:].strip()))


def parse_cut_response(text: str):
    """途中で切れた回答から、最後まで書かれている図表の位置の指定（placements の要素）だけを読む。読めなければ None。

    JSON の読み取りの誤りが、回答の最後で切れた形（cut_at_end）のときだけ読む（途中の書き損じは読まない。閉じの ``` まで
    書かれたコードブロックの回答は、最後まで書かれているので読まない）。最上位のオブジェクトのキーと値を 1 組ずつ JSON として
    読み、placements の値は要素を 1 つずつ読む。途中で切れている要素と、それより後ろは読まない（推測で補わない。閉じ括弧も
    補わない）。operations と notes は、最後まで書かれた要素があっても使わない（リンクは件数が多く、途中までのリンクだけが
    付くと確かめにくい）。読めた要素も、ふつうの回答と同じく float_placements で検証する。
    戻り値: {"placements": [...], "operations": [], "notes": []}
    """
    t, closed = _json_text(text)
    i = t.find("{")
    if i < 0 or closed:
        return None
    t = t[i:]
    try:
        json.loads(t)
        return None                    # 切れていない（読める回答は parse_response で読む）
    except json.JSONDecodeError as e:
        if not cut_at_end(e, t):
            return None
    dec, n = json.JSONDecoder(), len(t)

    def ws(k):
        while k < n and t[k] in " \t\r\n":
            k += 1
        return k

    found, k = [], ws(1)
    try:
        while k < n and t[k] != "}":
            if t[k] == ",":
                k = ws(k + 1)
            if k >= n or t[k] != '"':
                break
            key, k = dec.raw_decode(t, k)
            k = ws(k)
            if k >= n or t[k] != ":":
                break
            k = ws(k + 1)
            if key != "placements":
                _, k = dec.raw_decode(t, k)       # 値の途中で切れていれば、ここで読めずに終わる
                k = ws(k)
                continue
            if k >= n or t[k] != "[":
                break
            found, k = [], ws(k + 1)
            while k < n and t[k] != "]":
                if t[k] == ",":
                    k = ws(k + 1)
                el, k = dec.raw_decode(t, k)      # 最後まで書かれた要素だけ（途中で切れた要素は読めずに終わる）
                found.append(el)
                k = ws(k)
            k = ws(k + 1)
    except json.JSONDecodeError:
        pass
    if not found:
        return None
    return {"placements": found, "operations": [], "notes": []}


# ---------------------------------------------------------------------------- 検証と適用
def split_ops(data):
    ops = []
    for raw in data.get("operations", []):
        if not isinstance(raw, dict):
            continue
        op = {k: raw.get(k, "" if k != "occurrence" else 1) for k in OP_SCHEMA["properties"]}
        try:
            op["occurrence"] = int(op.get("occurrence") or 1)
        except (TypeError, ValueError):
            op["occurrence"] = 1
        ops.append(op)
    return ops


def role_overrides(ops, plan: ArticlePlan, outcome: AIOutcome) -> dict:
    """set_role 操作を検証し、段落の役割の上書き表にする（構造の組み立てをやり直すため）。"""
    out = {}
    for op in ops:
        if op["op"] != "set_role":
            continue
        src, role = op["src"], op["role"]
        if src not in plan.paras:
            outcome.rejected.append((op, f"段落 {src} が存在しない"))
            continue
        if role not in ROLES:
            outcome.rejected.append((op, f"役割「{role}」は指定できない"))
            continue
        if plan.paras[src].float_id:
            outcome.rejected.append((op, "テキストボックス・グループ図形の中の段落の役割は placements で指定する"))
            continue
        if role == "fn_start" and any(q is plan.paras[src] for fn in plan.fns if fn.word_note for q in fn.paras):
            outcome.rejected.append((op, "Word の脚注機能で書かれた注は、Word の区切りのとおりにする"))
            continue
        region = plan.region.get(src, "")
        if region and role not in REGION_ROLES.get(region, set()):
            outcome.rejected.append((op, f"この位置（{region}）では役割「{role}」を指定できない"))
            continue
        out[src] = role
    return out


def placement_op(pl) -> dict:
    """配置の指定を、レポートの「操作」の一覧に載せる形にする。"""
    pl = pl if isinstance(pl, dict) else {}
    items = pl.get("items") if isinstance(pl.get("items"), list) else []
    what = "；".join(f"{it.get('kind')}: キャプション {','.join(map(str, it.get('caption') or []))} / 本体 "
                     f"{','.join(map(str, it.get('body') or []))}" for it in items if isinstance(it, dict))
    return {"op": "place_float", "src": str(pl.get("float", "")), "text": what, "target": str(pl.get("after", "")),
            "role": "", "image": "", "reason": str(pl.get("reason", "")), "confidence": str(pl.get("confidence", ""))}


def float_placements(data, plan: ArticlePlan, outcome: AIOutcome) -> dict:
    """placements（図表の位置と組み合わせ）を検証し、図形の ID → 指定 の表にする（構造の組み立てをやり直すため）。

    採用するのは、位置を決められなかった図形について、中身をすべて正しく指定したものだけ。機械的に配置した図形は変更させない。
    本文の外（注・引用文献など。structure.AFTER_BODY_REGIONS）の段落の後ろを指定したものは、本文の外には図表を置けないので
    今までどおり採用しないが、その図形には「本文の最後に仮に置く」印（{"where": "end"}）を付ける（決定事項 21。
    structure.Classifier.place_floats）。印を付けた後に、同じ図形の正しい指定があれば、そちらを採用する。
    """
    out, ends = {}, {}
    body = set(plan.body_seq)
    for pl in data.get("placements", []) or []:
        op = placement_op(pl)
        why = _placement_problem(pl, plan, body, out)
        if why:
            fid = pl.get("float") if isinstance(pl, dict) else None
            after = pl.get("after") if isinstance(pl, dict) else None
            info = plan.floats.get(fid) if isinstance(fid, str) else None
            if (info is not None and info.mode == "unplaced" and fid not in out and fid not in ends
                    and isinstance(after, str) and after not in body and plan.region.get(after) in AFTER_BODY_REGIONS):
                ends[fid] = ({"where": "end", "after": after, "op": op}, len(outcome.rejected))
            outcome.rejected.append((op, why))
            continue
        out[pl["float"]] = {"after": pl["after"], "items": pl["items"], "reason": op["reason"],
                            "confidence": op["confidence"] if op["confidence"] in ("高", "中", "低") else "低", "op": op}
    for fid, (spec, k) in ends.items():
        if fid in out:
            continue                    # 同じ図形の、後ろの正しい指定を採用した
        out[fid] = spec
        op, why = outcome.rejected[k]
        outcome.rejected[k] = (op, why + "。図表は本文の最後に仮に置いた（手作業で正しい位置に移すこと）")
    return out


def _placement_problem(pl, plan: ArticlePlan, body: set, done: dict) -> str:
    if not isinstance(pl, dict):
        return "指定の形式が正しくない"
    fid, after, items = pl.get("float"), pl.get("after"), pl.get("items")
    info = plan.floats.get(fid)
    if info is None:
        return f"図形 {fid} は「位置を決められなかった図表」にない"
    if info.mode != "unplaced":
        return f"図形 {fid} は位置を機械的に決めた図表なので、位置も組み合わせも変更できない"
    if fid in done:
        return f"図形 {fid} の指定が 2 回ある（最初の指定を採用）"
    if after not in body:
        return f"置く位置の段落 {after} は本文の段落ではない（図形の中の段落・表のセル・本文以外は指定できない）"
    if not isinstance(items, list) or not items:
        return "items（図表の組）がない"
    paras = {q.src: q for q in info.paras}
    cells = {q.src: q for t in info.tables for q in t.paragraphs()}
    tables = {t.tid for t in info.tables}
    group_imgs = {i.image_id for i in info.images}
    img_paras = {i.image_id: q for q in list(paras.values()) + list(cells.values()) for i in q.images}
    used, whole, split = set(), set(), set()
    cell_table = {q.src: t.tid for t in info.tables for q in t.paragraphs()}
    for it in items:
        if not isinstance(it, dict) or it.get("kind") not in ("fig", "table"):
            return "items の kind は fig か table"
        caps, bodies = it.get("caption") or [], it.get("body") or []
        if not isinstance(caps, list) or not isinstance(bodies, list):
            return "caption と body は一覧（[ ]）で書く"
        for c in caps:
            q = paras.get(c) or cells.get(c)
            if q is None:
                return f"キャプションの段落 {c} は図形 {fid} の中にない"
            if not _para_text(q).strip():
                return f"キャプションの段落 {c} に文字がない"
            if c in cell_table:
                split.add(cell_table[c])
        if it["kind"] == "table" and (len(bodies) != 1 or bodies[0] not in tables):
            return "表（table）の body は、図形の中の表 1 つ"
        if it["kind"] == "fig" and not bodies:
            return "図（fig）の body（画像か表）がない"
        for x in bodies:
            if x in tables:
                whole.add(x)
                continue
            if x in group_imgs:
                continue
            q = paras.get(x) or cells.get(x) or img_paras.get(x)
            if q is None:
                return f"本体 {x} は図形 {fid} の中の表・画像・画像の段落ではない"
            if not q.images:
                return (f"本体 {x} の段落 {q.src} には画像がない（画像以外の文字だけの段落は、キャプションか、"
                        "指定しない段落として残す）")
            # 画像と文字が同じ段落（画像だけの段落でないもの）も本体にできる。画像は図に入り、段落は文字ごと図の直後に
            # 本文の段落として出る（structure.Classifier.float_from_spec）
            if q.src in cell_table:
                split.add(cell_table[q.src])
        for x in list(caps) + [img_paras[b].src if b in img_paras and b not in group_imgs else b for b in bodies]:
            if x in used:
                return f"{x} が 2 回使われている"
            used.add(x)
    if whole & split:
        return f"表 {', '.join(sorted(whole & split))} を、表全体と、セルの段落の両方で使っている"
    return ""


def target_keys(plan: ArticlePlan) -> dict:
    """リンク先の ID（F1, T2, FD1, fn1, B3）→ 構造を組み直しても変わらない目印（キャプションなどの段落 ID）。

    AI は依頼文（1 回目の組み立て）の ID でリンク先を指定するが、役割や図表の配置の指定を反映して組み直すと、
    図表の並びが変わって ID がずれることがある（retarget_ops で読み替える）。
    """
    keys = {}
    for f in plan.figures:
        p = f.caption if f.caption is not None else (f.image_paras[0] if f.image_paras else None)
        if f.fid and p is not None:
            keys[f.fid] = ("fig", p.src)
    for t in plan.tables:
        if t.tid:
            keys[t.tid] = ("table", t.caption.src if t.caption is not None else (t.table.tid if t.table else ""))
    for fm in plan.formulas:
        if fm.fid:
            keys[fm.fid] = ("formula", fm.para.src)
    for fn in plan.fns:
        if fn.fid and fn.paras:
            keys[fn.fid] = ("fn", fn.paras[0].src)
    for r in plan.refs:
        keys[r.rid] = ("ref", r.para.src)
    return keys


def retarget_ops(ops, before: dict, plan: ArticlePlan):
    """リンクの操作の target（1 回目の組み立ての ID）を、組み直した後の plan の ID に読み替える。"""
    after = {key: rid for rid, key in target_keys(plan).items()}
    for op in ops:
        if op["op"] == "link_note" and op["target"] not in before and ("fn", op["target"]) in after:
            # fn_start で新しく分けた注は、依頼文に ID がないので、その注の最初の段落の ID で指定される
            op["target"] = after[("fn", op["target"])]
            continue
        if op["op"] in TARGET_PREFIX and op["target"] in before:
            new = after.get(before[op["target"]])
            # 組み直した後に見つからなければ、別の図表に誤ってリンクしないよう存在しない ID にする（不採用になる）
            op["target"] = new or f"{op['target']}（組み直した後に見当たらない）"


def apply_ops(ops, plan: ArticlePlan, doc, outcome: AIOutcome):
    """set_role 以外の操作を検証して適用する（構造を組み直した後の plan に対して）。"""
    from .linker import apply_span, range_linked
    ids = {"B": {r.rid for r in plan.refs}, "F": {f.fid for f in plan.figures if f.fid},
           "T": {t.tid for t in plan.tables}, "fn": {f.fid for f in plan.fns}, "FD": {f.fid for f in plan.formulas if f.fid}}
    images = {}
    for f in plan.figures:
        for ip in f.image_paras:
            for img in ip.images:
                images[img.image_id] = f
    author_paras = {}
    for a in plan.authors:
        if a.name_ja is not None:
            author_paras[a.name_ja.src] = (a, "ja")
        if a.name_en is not None:
            author_paras[a.name_en.src] = (a, "en")
    for op in ops:
        kind = op["op"]
        if kind == "set_role":
            if any(r[0] is op for r in outcome.rejected):
                continue
            d = plan.decide("ai", "style", op["src"], f"段落の役割を「{ROLES[op['role']]}」とした。{op['reason']}",
                            op["confidence"])
            outcome.accepted.append((op, d))
            continue
        if kind in TARGET_PREFIX:
            src, text, target = op["src"], op["text"], op["target"]
            p = plan.paras.get(src)
            if p is None:
                outcome.rejected.append((op, f"段落 {src} が存在しない"))
                continue
            prefix = TARGET_PREFIX[kind]
            if target not in ids.get(prefix, set()):
                outcome.rejected.append((op, f"リンク先 {target} が存在しない（{kind} の対象は {prefix}…）"))
                continue
            if not text:
                outcome.rejected.append((op, "リンクにする文字列が空"))
                continue
            if kind == "link_citation" and not RE_YEAR.match(unicodedata.normalize("NFKC", text).strip()):
                outcome.rejected.append((op, f"引用文献のリンクは年の部分だけに付ける規則だが、「{text}」は年ではない"))
                continue
            from .linker import find_in_para
            rng = find_in_para(p, text, op["occurrence"])
            if rng is None:
                outcome.rejected.append((op, f"段落 {src} に「{text}」（{op['occurrence']} 回目）が見つからない"))
                continue
            if OBJ in p.plain()[rng[0]:rng[1]]:
                outcome.rejected.append((op, "数式や画像をまたぐ範囲にはリンクを付けられない"))
                continue
            if range_linked(p, *rng):
                outcome.rejected.append((op, "すでにリンクが付いている箇所"))
                continue
            spec = LinkSpec(kind="xref", attrs={"ref-type": REF_TYPE[kind], "rid": target}, origin="ai")
            apply_span(p, rng[0], rng[1], spec)
            what = {"link_citation": "引用", "link_figure": "図の参照", "link_table": "表の参照", "link_note": "注の参照",
                    "link_formula": "数式の参照"}[kind]
            d = plan.decide("ai", "citation" if kind == "link_citation" else "xref", src,
                            f"「{text}」を{what}として {target} にリンクした。{op['reason']}", op["confidence"])
            spec.decision_id = d.did
            outcome.accepted.append((op, d))
            continue
        if kind == "formula_image":
            fig = images.get(op["image"])
            if fig is None:
                outcome.rejected.append((op, f"画像 {op['image']} が見つからない"))
                continue
            if fig.caption is not None:
                outcome.rejected.append((op, "キャプションのある図は数式画像として扱わない"))
                continue
            mml, err = parse_mathml(op["mathml"])
            if mml is None:
                outcome.rejected.append((op, f"MathML として読めない: {err}"))
                continue
            fig.formula = mml
            src = fig.image_paras[0].src if fig.image_paras else ""
            d = plan.decide("ai", "formula", src, f"画像 {op['image']} を数式と判断し、読み取った MathML を併記した"
                            f"（元の画像も残している）。読み取り結果: {math_display_text(mml)}。{op['reason']}",
                            op["confidence"])
            fig.formula_decision = d.did
            outcome.accepted.append((op, d))
            continue
        if kind == "split_name":
            src = op["src"]
            if src not in author_paras:
                outcome.rejected.append((op, f"段落 {src} は著者名ではない"))
                continue
            a, lang = author_paras[src]
            if lang != "ja":
                outcome.rejected.append((op, "英文氏名は空白の位置で姓と名を分けるため、分割の指定は和文氏名だけに使える"))
                continue
            p = plan.paras[src]
            text = p.plain()
            sur, giv = op["surname"], op["given"]
            core = text.strip(" \u3000\t")
            lead = len(text) - len(text.lstrip(" \u3000\t"))
            if not sur or not giv or core != sur + giv:
                outcome.rejected.append((op, f"姓「{sur}」と名「{giv}」をつなげても氏名「{core}」にならない"))
                continue
            a.split_ja = lead + len(sur)
            d = plan.decide("ai", "name", src, f"氏名「{core}」を姓「{sur}」・名「{giv}」に分けた。{op['reason']}",
                            op["confidence"])
            outcome.accepted.append((op, d))
            continue
        outcome.rejected.append((op, f"未知の操作「{kind}」"))


def parse_mathml(s: str):
    if not s or "<" not in s:
        return None, "空"
    t = s.strip()
    if "xmlns" not in t.split(">", 1)[0]:
        t = re.sub(r"^<(?:mml:)?math", f'<math xmlns="{MML_NS}"', t, count=1)
    t = t.replace("<mml:", "<").replace("</mml:", "</")
    try:
        el = etree.fromstring(t.encode("utf-8"), etree.XMLParser(resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError as e:
        return None, str(e)
    if etree.QName(el).localname != "math":
        return None, "根要素が math ではない"
    for x in el.iter():
        if not isinstance(x.tag, str):
            continue
        q = etree.QName(x)
        if q.namespace != MML_NS or q.localname not in MATHML_ELEMENTS:
            return None, f"使えない要素 {q.localname}"
        for a in list(x.attrib):
            if etree.QName(a).localname not in MATHML_ATTRS:
                del x.attrib[a]
    el.attrib.pop("display", None)
    return el, ""
