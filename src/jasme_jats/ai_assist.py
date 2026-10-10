"""生成 AI（Claude）による補完。

AI には XML も docx も直接編集させない。AI が返すのは「操作」の一覧（JSON）だけで、
Python が 1 件ずつ検証してから、文字列を変えない操作（リンクを付ける・段落の役割を変える・
姓名の区切りを指定する・数式画像に MathML を併記する）として適用する。
適用後は、最後に必ず文字の不変性チェックをやり直す（pipeline.py）。

使い方は 2 通り:
  API モード : Claude API を直接呼ぶ（環境変数 ANTHROPIC_API_KEY などの認証情報が必要）
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

from .model import OBJ, LinkSpec, Para
from .omml import MML_NS, OmmlConverter, math_display_text
from .structure import ArticlePlan, _para_text

DEFAULT_MODEL = "claude-opus-5-5"

ROLES = {
    "sec1": "章見出し", "sec2": "節見出し", "sec3": "項見出し", "p": "本文段落", "fig_caption": "図キャプション",
    "table_caption": "表キャプション", "quote": "ブロック引用", "ref": "引用文献（参考文献リストの 1 件）",
    "ref_heading": "参考文献見出し", "notes_heading": "付記見出し", "ack_heading": "謝辞見出し",
    "fn_heading": "注見出し", "abstract": "英文要旨の段落", "title": "題目", "subtitle": "副題",
    "exclude": "論文の本文ではない（テンプレートの装飾など）",
}
_HEADINGS = {"ref_heading", "notes_heading", "ack_heading", "fn_heading"}
REGION_ROLES = {
    "front_ja": {"title", "subtitle", "exclude"},
    "body": {"sec1", "sec2", "sec3", "p", "fig_caption", "table_caption", "quote", "exclude"} | _HEADINGS,
    "notes": {"p", "exclude"} | _HEADINGS, "ack": {"p", "exclude"} | _HEADINGS,
    "fn": {"p", "exclude"} | _HEADINGS, "refs": {"ref", "exclude"} | _HEADINGS, "back": {"p", "exclude"} | _HEADINGS,
    "front_en": {"abstract", "exclude"}, "app": {"p", "exclude"},
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
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "operations": {"type": "array", "items": OP_SCHEMA},
        "notes": {"type": "array", "items": {"type": "string"},
                  "description": "操作にはできないが、人が確認すべきと考えたこと（日本語）"},
    },
    "required": ["operations", "notes"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """あなたは、学術誌『全国数学教育学会誌 数学教育学研究』の論文（Word の docx）を J-STAGE 全文 XML（JATS 1.1）に変換する作業の補助者です。
Python のプログラムがすでに機械的な変換を済ませています。あなたの仕事は、機械処理で取りこぼした箇所を見つけ、「操作」の一覧として提案することです。

絶対の規則:
- 論文の文字は 1 文字も変えてはいけません（誤字脱字に見えても直さない）。あなたが提案できるのは、既存の文字列に対する次の操作だけです。
- 操作の text には、段落中にある文字列を一字一句そのまま書いてください。プログラムが完全一致で探し、見つからなければその操作は捨てられます。

提案できる操作:
1. link_citation: 本文中の引用を引用文献リストの文献にリンクする。リンクにするのは「年」の部分だけです（例: 「Claude (2025)」なら text は「2025」、「中原（1995, p.3）」なら「1995」）。
   機械処理は「著者名（年）」「（著者名, 年）」の形だけを扱います。著者名と年が離れている、括弧がない、著者名の表記が文献リストと異なる、年が食い違う、などで未リンクのものを探してください。
   年が文献リストと食い違う場合（本文 1977 / 文献 1976 など）は、文脈から同じ文献と判断できるときだけ、確度「低」で提案してください。
2. link_figure / link_table / link_note / link_formula: 「図3」「表2」「注4」「式(2)」などの参照を、対応する図・表・注・数式にリンクする（text は「図3」のように参照の表記全体）。
3. set_role: スタイルが正しく設定されておらず、役割を機械的に決められなかった段落の役割を指定する。role には次のいずれかを書く:
   {roles}
4. formula_image: 画像として貼り付けられた数式を MathML（MathML 2.0、<math xmlns="http://www.w3.org/1998/Math/MathML"> を根要素とする）に書き起こす。元の画像は残したまま、読み取った数式を併記します。数式でない画像には提案しないでください。
5. split_name: 姓と名の間に空白がない和文の著者名について、姓と名の境目を指定する（surname + given が氏名の文字列と完全に一致すること）。

reason には、人が後で確認できるように、判断の根拠を日本語で具体的に書いてください（例: 「第3章第2段落の『その後の論考（2001）』は、直前の主語『国宗は』から国宗（2001）と判断」）。
confidence は 高・中・低 のいずれか。自信がないものは提案しないか、「低」としてください。
操作にできない気づき（文献リストに見当たらない文献の引用、図番号の欠番など）は notes に書いてください。"""


@dataclass
class AIOutcome:
    mode: str = "none"                # none / api / manual
    model: str = ""
    accepted: list = field(default_factory=list)    # (op, Decision)
    rejected: list = field(default_factory=list)    # (op, 理由)
    notes: list = field(default_factory=list)
    error: str = ""
    usage: dict = field(default_factory=dict)
    raw: str = ""


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
        lines.append(f"[{fn.fid}] 注 {(fn.paras[0].autonum or '')}{para_view(fn.paras[0])[:80]}")
    for fm in plan.formulas:
        if fm.fid:
            lines.append(f"[{fm.fid}] 数式 番号 {fm.label}")
    lines.append("\n# 機械処理で解決できなかった箇所")
    for item in linker.unresolved:
        cat, src, raw, detail = item[:4]
        lines.append(f"- [{src}] {cat}: 「{raw}」 … {detail}")
    for d in plan.decisions:
        if d.category in ("style", "formula", "figure", "table"):
            lines.append(f"- [{d.src}] 推定: {d.message}")
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
    return "\n".join(lines), images


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
def call_api(request_text, images, model=DEFAULT_MODEL, api_key=None, effort="high") -> AIOutcome:
    import anthropic
    out = AIOutcome(mode="api", model=model)
    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    content = []
    for image_id, mt, data in images:
        content.append({"type": "text", "text": f"画像 {image_id}:"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": mt,
                                                   "data": base64.standard_b64encode(data).decode("ascii")}})
    content.append({"type": "text", "text": request_text})
    system = SYSTEM_PROMPT.replace("{roles}", " / ".join(f"{k}（{v}）" for k, v in ROLES.items()))
    kwargs = dict(model=model, max_tokens=64000, system=system, messages=[{"role": "user", "content": content}],
                  output_config={"effort": effort, "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}})
    try:
        try:
            # 安全上の判定で断られた場合に、サーバー側で別のモデルに切り替えて続ける（fallbacks）
            with client.beta.messages.stream(betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                                             **kwargs) as stream:
                msg = stream.get_final_message()
        except anthropic.BadRequestError:
            # ベータ機能が使えない環境では通常の呼び出しでやり直す
            with client.messages.stream(**kwargs) as stream:
                msg = stream.get_final_message()
    except anthropic.AuthenticationError:
        out.error = "API キーが無効です（Colab では「シークレット」に ANTHROPIC_API_KEY を登録してください）"
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
    if msg.stop_reason == "max_tokens":
        out.error = "AI の回答が長すぎて途中で切れました"
        return out
    text = next((b.text for b in msg.content if b.type == "text"), "")
    out.raw = text
    u = getattr(msg, "usage", None)
    if u is not None:
        out.usage = {"input_tokens": getattr(u, "input_tokens", None), "output_tokens": getattr(u, "output_tokens", None)}
    return out


def manual_prompt(request_text, images) -> str:
    """手動モード: チャットに貼り付ける依頼文。"""
    system = SYSTEM_PROMPT.replace("{roles}", " / ".join(f"{k}（{v}）" for k, v in ROLES.items()))
    img_note = ""
    if images:
        names = "、".join(f"{i}.{mt.split('/')[-1].replace('jpeg', 'jpg')}" for i, mt, _ in images)
        img_note = (f"\n\n（この依頼には画像が {len(images)} 枚あります。出力フォルダの「AI添付画像」にある {names} を"
                    "このメッセージに添付してください。ファイル名が画像 ID です。）")
    schema = json.dumps(RESPONSE_SCHEMA, ensure_ascii=False, indent=1)
    return (f"{system}{img_note}\n\n"
            "回答は、次の JSON スキーマに従う JSON だけを書いてください（説明文や ``` は不要）。\n"
            f"{schema}\n\n"
            "---\n"
            f"{request_text}\n")


def parse_response(text: str) -> dict:
    """AI の回答（JSON）を取り出す。コードブロックで囲まれていても受け付ける。"""
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    if not t.startswith("{"):
        i, j = t.find("{"), t.rfind("}")
        if i >= 0 and j > i:
            t = t[i:j + 1]
    data = json.loads(t)
    if not isinstance(data, dict) or not isinstance(data.get("operations", []), list):
        raise ValueError("JSON に operations の一覧がありません")
    return data


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
        region = plan.region.get(src, "")
        if region and role not in REGION_ROLES.get(region, set()):
            outcome.rejected.append((op, f"この位置（{region}）では役割「{role}」を指定できない"))
            continue
        out[src] = role
    return out


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
