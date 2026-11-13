"""生成 AI による補完（推奨は Claude。API モードでは ChatGPT・Gemini・Sakana AI も使える）。

AI には XML も docx も直接編集させない。AI が返すのは「操作」の一覧（JSON）だけで、
Python が 1 件ずつ検証してから、文字列を変えない操作（リンクを付ける・注の区切りと資料の始まりを直す・
姓名の区切りを指定する）として適用する。ほかの段落の役割の指定（見出し・引用・キャプション・除外など）は、Word のスタイルで
直す提案として記録するだけで、XML は変えない（所有者の決定 5。BOUNDARY_KINDS・boundary_problem）。
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
import os
import re
import unicodedata
from dataclasses import dataclass, field
from typing import NamedTuple

from lxml import etree

from .article import ArticlePlan, _para_text
from .floats import column_cm, describe, estimate_top_left
from .model import OBJ, LinkSpec, Para, note_label
from .omml import MML_NS, OmmlConverter, math_display_text
from .structure import AFTER_BODY_REGIONS, abstract_missing_srcs, figure_rows, float_caption

# 既定の AI モデル（Claude。動作を確かめたもの）。ここ 1 か所で決める（pipeline.Options・cli の既定、ノートブックの手順 4 と説明。
# tools/make_notebook.py はこのファイルを読んで、DEFAULT_MODEL と DEFAULT_MODEL_INFO の値を使う）。
# モデルを変えるときは、2 つを一緒に直し、python tools/make_notebook.py でノートブックを作り直す。どちらもリテラルだけで書く
# （make_notebook.py がパッケージを import せずに ast.literal_eval で読むため）
DEFAULT_MODEL = "claude-opus-5-5"
# 既定のモデルの表示名、料金（100 万トークンあたりの米ドル。入力・出力）、提供終了の予定（この日より前には終わらない。年-月-日）
DEFAULT_MODEL_INFO = {"name": "Claude Opus 5.5", "input_usd": 4, "output_usd": 20, "not_before": "2027-09-22"}

ROLES = {
    "sec1": "章見出し", "sec2": "節見出し", "sec3": "項見出し", "p": "本文段落", "fig_caption": "図キャプション",
    "table_caption": "表キャプション", "quote": "ブロック引用", "ref": "引用文献（参考文献リストの 1 件）",
    "ref_heading": "参考文献見出し", "notes_heading": "付記見出し", "ack_heading": "謝辞見出し",
    "fn_heading": "注見出し", "fn_start": "注の始まり（注の一覧で、新しい注が始まる段落）",
    "abstract": "英文要旨の段落", "app_heading": "資料の見出し（英文要旨の後ろの、資料・付録の始まり）",
    "title": "題目", "subtitle": "副題",
    "exclude": "論文の本文ではない（テンプレートの装飾など）",
}
_HEADINGS = {"ref_heading", "notes_heading", "ack_heading", "fn_heading"}
# AI の回答で XML を直す段落の役割の補正（所有者の決定 5。注の区切りと資料の始まりだけ）: kind の語 → 中の役割。
# 指定できる段落は boundary_kind で決める（注の始まり・注の続きは手で書いた注の一覧〈領域 fn〉の段落、資料の見出しは英文要旨と
# 資料の段落、英文要旨の続き・資料の本文は今、資料の見出し〈AppNode.title〉になっている段落）。ほかの指定は提案（STYLE_ONLY_WHY）
BOUNDARY_KINDS = {"注の始まり": "fn_start", "注の続き": "p", "資料の見出し": "app_heading", "英文要旨の続き": "abstract",
                  "資料の本文": "p"}
# 区切りの 5 つ以外の set_role を XML に反映しない理由（レポートの 2 章の不採用の一覧。同じ内容を AIOutcome.style_fixes に提案として入れる）
STYLE_ONLY_WHY = ("Word のスタイルで直せる指定なので、XML には反映しない（Word で直す提案として、要確認「スタイルを確かめてください」に"
                  "載せる）")
# 除外（exclude）の提案の、Word での直し方（ほかの役割は、その役割のスタイルにする。role_style）
EXCLUDE_HOW = "本文に要らない段落なら、Word で消す"
REGION_ROLES = {
    "front_ja": {"title", "subtitle", "exclude"},
    "body": {"sec1", "sec2", "sec3", "p", "fig_caption", "table_caption", "quote", "exclude"} | _HEADINGS,
    "notes": {"p", "exclude"} | _HEADINGS, "ack": {"p", "exclude"} | _HEADINGS,
    "fn": {"fn_start", "p", "exclude"} | _HEADINGS, "refs": {"ref", "exclude"} | _HEADINGS, "back": {"p", "exclude"} | _HEADINGS,
    # 英文の部分では、資料の始まり（app_heading）を指定でき、資料の見出しに abstract を指定すると英文要旨に戻せる
    "front_en": {"abstract", "app_heading", "exclude"}, "app": {"p", "abstract", "app_heading", "exclude"},
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
                                          "set_role", "split_name"]},
        "src": {"type": "string", "description": "対象の段落 ID（例: d18）"},
        "text": {"type": "string", "description": "リンクにする文字列（段落中にあるとおりに完全一致で）。リンク以外の操作では空文字"},
        "occurrence": {"type": "integer", "description": "段落内で text が何回目に現れる箇所か（1 始まり）"},
        "target": {"type": "string", "description": "リンク先 ID（B3, F1, T2, fn1, FD1 など）。リンク以外では空文字"},
        "role": {"type": "string", "description": "set_role の役割名。それ以外では空文字"},
        # image・mathml は使わない項目（いつも空文字。操作 formula_image をなくした名残で、回答の形を変える修正計画 W8 の手順 10 まで残す）
        "image": {"type": "string", "description": "使わない項目。いつも空文字"},
        "mathml": {"type": "string", "description": "使わない項目。いつも空文字"},
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
        "float": {"type": "string", "description": "図形の ID（s1 など）、またはテキストボックスの ID（x1 など）。「位置を決められ"
                                                   "なかった図表」「囲みか図の注記か決められなかったテキストボックス」「位置を推定した"
                                                   "囲み」「図に重ねた注記とみなして除外したテキストボックス」に挙げたもの"},
        "after": {"type": "string", "description": "図表・囲みを置く位置: Word で表示したときに図の左上の直上にある本文の文章を含む"
                                                   "段落の ID。テキストボックスで kind が label のときは空文字"},
        # items は必須のまま（ChatGPT の strict な構造化出力は、すべての項目を必須にしないと受け付けない）。図形では空の一覧 [] を書かせる
        # （中身の組み合わせは変換ツールが決める。修正計画 W8 の手順 6）
        "items": {"type": "array", "description": "図形（s1 など）では空の一覧 []（中身の組み合わせは変換ツールが決める）。"
                                                  "テキストボックス（x1 など）だけ、kind の組を 1 つ書く", "items": {
            "type": "object",
            "properties": {
                # fig・table は前の形の回答（図形の中身の組）を読むために残す（float_placements は読まない）
                "kind": {"type": "string", "enum": ["fig", "table", "box", "label"],
                         "description": "テキストボックス（x1 など）の種類: box（本文の囲み）か label（図に重ねた注記。本文に"
                                        "出さない）"},
                "caption": {"type": "array", "items": {"type": "string"}, "description": "空の一覧 []"},
                "body": {"type": "array", "items": {"type": "string"}, "description": "空の一覧 []"},
            },
            "required": ["kind", "caption", "body"],
            "additionalProperties": False,
        }},
        "reason": {"type": "string", "description": "位置の根拠（日本語で具体的に）"},
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
                       "description": "位置を決められなかった図表（テキストボックス・グループ図形）の位置と、"
                                      "囲みか図の注記か決められなかったテキストボックスの種類（box・label）。回答の最初に書く"},
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

提案できる操作（5 の placements は operations とは別の一覧に書きます）:
1. link_citation: 本文中の引用を引用文献リストの文献にリンクする。リンクにするのは「年」の部分だけです（例: 「Claude (2025)」なら text は「2025」、「中原（1995, p.3）」なら「1995」）。
   機械処理は「著者名（年）」「（著者名, 年）」の形だけを扱います。著者名と年が離れている、括弧がない、著者名の表記が文献リストと異なる、年が食い違う、などで未リンクのものを探してください。
   年が文献リストと食い違う場合（本文 1977 / 文献 1976 など）は、文脈から同じ文献と判断できるときだけ、確度「低」で提案してください。
2. link_figure / link_table / link_note / link_formula: 「図3」「表2」「注4」「式(2)」などの参照を、対応する図・表・注・数式にリンクする（text は「図3」のように参照の表記全体）。
3. set_role: 段落の役割を指定する。XML に反映するのは、注の区切りと資料の始まりの直しだけです:
   注の一覧（手で書いた注）の段落への fn_start（その段落から新しい注）と p（前の注の続き）、英文要旨と資料の段落への
   app_heading（資料の見出し。その段落から後ろが資料になります）、今、資料の見出しになっている段落への abstract（資料の始まりを
   取り消し、次の資料の見出しまで英文要旨に戻します）と p（見出しではなく、前の資料の続きにします。前に資料がなければ、
   見出しのない資料の最初の段落になります）。
   英文要旨の後ろの資料（付録）が英文要旨に入っているときは、資料の見出しの段落を app_heading にしてください。逆に、英文要旨の
   段落が誤って資料にされているときは、その資料の見出しの段落を abstract にしてください。資料の見出しにされた段落が、見出しでは
   なく資料の中の文のときは p にしてください。
   ほかの役割の指定（見出しの階層、見出しと本文、ブロック引用、図・表のキャプション、引用文献、題目・副題、英文要旨のスタイルの
   ない段落を英文要旨にする、本文に要らない段落の除外など）は、スタイルが正しく設定されていない段落について、Word のスタイルで直す
   提案として作業する人に知らせるだけで、XML は変えません。role には次のいずれかを書く:
   {roles}
   著者表の中の段落（役割 author_ja / aff_ja / author_en / aff_en）は確認のために載せているもので、役割は変えられません。
   Word の脚注・文末脚注の段落と、英文の題目・副題の段落の役割も変えられません。
4. split_name: 姓と名の間に空白がない和文の著者名と、字の間に空白があり姓と名の境目をプログラムが決めた（いちばん長い空白で決めた、または推定した）和文の著者名について、姓と名の境目を指定する（surname + given が氏名の文字列と完全に一致すること。字の間に空白のある氏名は、空白を除いた文字で一致すればよい）。

5. placements（図表の位置）: 依頼文の「# 位置を決められなかった図表」に挙げた図形（s1 など）は、1 つ残らず、
   必ず placements に 1 件ずつ指定してください（省略できません）。これらは Word のテキストボックスやグループ図形に入った図表
   （2 段組をまたぐ図など）で、docx には Word で表示したときの位置が記録されていないため、プログラムでは置き場所を決められませんでした。
   - after: 図表を置く位置です。Word で表示したときに、図の左上の直上にある本文の文章を含む段落の ID を書いてください（その段落の直後に置きます）。
     図の直上が別の図表なら、さらにその上にある本文の文章を含む段落です。図が段やページの先頭にあるときは、読む順で直前にある本文の段落です。
     依頼文に示した配置の情報（アンカー段落、アンカー段落からの距離、行数による推定）から判断してください。行数による推定は文字数から計算した
     目安で、ページや段の区切りは考慮していません。図の番号の順序（図2 は図1 より後）とも矛盾しないようにしてください。
     after に書けるのは「# 論文の段落一覧」の本文の段落（テキストボックス・グループ図形の中の段落と、表のセルの段落を除く）だけです。
   - 答えるのは位置（after）だけです。図形の中の図・表とキャプションの組み合わせはプログラムが決めています（依頼文の「中身」に、
     その順で並べてあります）。図形（s1 など）の items は、空の一覧 [] にしてください。1 つの図形に図・表が 2 つ以上入っていても、
     答えは図形ごとに 1 件です（中の図・表は、その順でまとめて置かれます）。
   - 「# 位置を機械的に決めた図表（変更不可）」に挙げた図形は、位置が確定しています。placements に書かないでください（書いても採用されません）。
   - 「# 囲みか図の注記か決められなかったテキストボックス」に挙げたもの（x1 など）は、1 つ残らず placements に 1 件ずつ指定してください。
     float にテキストボックスの ID、items に {"kind": "box" か "label", "caption": [], "body": []} を 1 つだけ書きます。
     box は本文の囲み（問題文・ヒント・まとめなど、本文として読まれる文章）で、after の段落の直後に枠で囲んだ段落として置きます。
     label は図に重ねた注記（矢印・点・辺の名前など、図の一部の短い文字）で、本文に出しません（after は空文字）。
     「# 位置を推定した囲み」に挙げたものは、置いた位置が違うときだけ、kind box で正しい after を指定してください。
     「# 図に重ねた注記とみなして除外したテキストボックス」に挙げたものは、図の注記ではなく本文として読まれる文章（問題文・ヒントなど）の
     ときだけ、kind box で after を指定してください（本文の囲みに戻ります。図の注記なら書かないでください）。
     「# 囲みとして位置を機械的に決めたテキストボックス（変更不可）」に挙げたものは placements に書かないでください。
   - 浮動配置の図形（s1 など）と、浮動配置のテキストボックス（段落一覧の位置が「テキストボックス x1（浮動配置）の中」の段落）の
     役割は、set_role ではなく placements で指定してください。浮動配置でないテキストボックスの段落に set_role で指定できるのは
     fig_caption・table_caption・exclude だけです（囲みか図の注記かは placements の kind box・label で指定します）。

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
    boundaries: list = field(default_factory=list)   # 反映した注の区切り・資料の始まりの直し（Boundary。role_overrides が記録する）
    style_fixes: list = field(default_factory=list)  # Word のスタイルで直す提案（StyleFix。XML には反映しない。role_overrides が記録する）
    partial: str = ""                 # 途中で切れた回答から、図表の位置の指定（placements）の一部だけを反映したときの説明（推奨の手順 ai_finish の「一部」。report.ai_state）


class Boundary(NamedTuple):
    """AI の回答で反映した、注の区切り・資料の始まりの直し（AIOutcome.boundaries）。kind は BOUNDARY_KINDS の語。"""
    src: str
    kind: str
    role: str
    reason: str
    confidence: str


class StyleFix(NamedTuple):
    """Word のスタイルで直す提案（AIOutcome.style_fixes。XML には反映しない）。style は Word のスタイル名（なければ ""）、how は Word での直し方。"""
    src: str
    role: str
    style: str
    how: str
    reason: str
    confidence: str
    verdict: str = "直す"


# ---------------------------------------------------------------------------- AI に渡す資料
def para_view(p: Para, images: bool = True) -> str:
    """AI に渡す段落の文字列。images が偽なら、docx の画像の印（⟦画像 imgN: …⟧）を書かない（図形の中身。画像は AI に渡さない）。"""
    out = []
    for a in p.atoms:
        if a.kind == "text":
            out.append(a.text)
        elif a.kind == "math":
            mml = OmmlConverter().convert(a.math, a.display)
            out.append(f"⟦数式: {math_display_text(mml)}⟧")
        elif a.kind == "image" and images:
            out.append(f"⟦画像 {a.image.image_id}: {a.image.width_cm:.1f}cm×{a.image.height_cm:.1f}cm⟧")
        elif a.kind == "fnref":
            out.append("⟦Word の文末脚注参照⟧" if a.fn_kind.startswith("endnote") else "⟦Word の脚注参照⟧")
    s = "".join(out)
    return s


def para_view_with_links(p: Para, images: bool = True) -> str:
    """リンク済みの箇所を «文字→リンク先» の形で示した段落の文字列（images は para_view と同じ）。"""
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
            buf += para_view(Para(src="", atoms=[a]), images)
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


# 依頼文の見出しの行（依頼文を回答の欄に貼ったと見分ける目印。build_request・manual_prompt が書き、_misuse が行頭の見出しの行としてだけ照合する）
REQUEST_HEADING = "# 論文の段落一覧"
MANUAL_ANSWER_HEADING = "## 回答の書き方（必ず守ってください）"


def build_request(plan: ArticlePlan, linker, build_exclusions=(), unsplit_names=(), name_splits=()) -> tuple:
    """AI への依頼（本文の文字列）を作る。戻り値: (テキスト, 画像の一覧)。docx の画像は AI に渡さない（図・表の画像は作業する人が
    用意する。修正計画 W1）ので、画像の一覧はいつも空（2 つ目の値は W8 が消す）。

    build_exclusions は書き出しの段階で出力しないと決めた段落（builder.BuildInfo.exclusions）、unsplit_names は姓と名を分けられ
    なかった氏名 [(段落の ID, 氏名, 言語 ja / en)]（builder.BuildInfo.unsplit_names）。英文の氏名も「姓と名の区切りがない氏名」に
    載せる（利用者の決定事項 17 で今までどおり載せる）が、AI の split_name は和文の氏名にしか使えない（apply_ops）ので、英文の行には
    split_name を提案しないことを添える（builder の 10 章の警告の「AI による補完では、英文の著者名は分けられません」と同じ言い分）。
    name_splits は確かめてもらう和文の氏名の分け方 [(段落の ID, builder.EasternSplit)]（BuildInfo.name_splits）。字の間に空白があり、
    いちばん長い空白か推定した境目で分けた氏名（how が longest / context / count）を、どう分けたかとともに載せ、split_name で
    正しい境目を指定してもらう（AI の指定は機械の推定より優先する。apply_ops）。
    氏名の中の改行は「⏎」で示す（1 件を 1 行に書くため。氏名の文字は変えない）。
    """
    lines = []
    lines.append(REQUEST_HEADING)
    lines.append("各行は [段落ID]（現在の役割 / 位置 / Word のスタイル名）本文。«文字→ID» はすでにリンク済みの箇所。")
    lines.append("⟦数式: …⟧ は数式、⟦画像 imgN: …⟧ は画像を表す（これらは文字ではないのでリンクの text に含めない）。\n")
    for src, p in plan.paras.items():
        region = plan.region.get(src, "")
        if not region and not p.in_textbox:
            continue
        role = p.role or region
        loc = plan.locations.get(src, "")
        if p.textbox_id and p.textbox_id in plan.textboxes:
            # 文字だけのテキストボックス（placements では x1 などで指定する）。浮動配置のものの段落は set_role で役割を変えられない
            # （set_role_problem）ので、そう分かるように書く
            loc = f"テキストボックス {p.textbox_id}" + ("（浮動配置）の中" if p.float_id else " の中")
        elif p.float_id:
            loc = f"図形 {p.float_id} の中"
        elif p.textbox_id:
            loc = f"テキストボックス {p.textbox_id} の中"
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
        where = note_label(fn.word_id) if fn.word_note else "段落 " + ", ".join(p.src for p in fn.paras)
        lines.append(f"[{fn.fid}]（{where}）注 {(fn.paras[0].autonum or '')}{para_view(fn.paras[0])[:80]}")
    for fm in plan.formulas:
        if fm.fid:
            lines.append(f"[{fm.fid}] 数式 番号 {fm.label}")
    lines.append("\n# 機械処理で解決できなかった箇所")
    for item in linker.unresolved:
        cat, src, raw, detail = item[:4]
        lines.append(f"- [{src}] {cat}: 「{raw}」 … {detail}")
    for d in plan.decisions:
        if d.category in ("style", "formula", "figure", "table", "note", "box"):
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
            p = plan.paras.get(e.src)
            hint = set_role_hint(p, plan) if p is not None else ""
            lines.append(f"- [{e.src}] 出力から除外: {e.reason}: 「{e.text[:60]}」{hint}")
    miss = abstract_missing_srcs(plan)
    if miss:
        shown = ", ".join(miss[:8]) + (" ほか" if len(miss) > 8 else "")
        lines.append(f"- 英文要旨の段落が見つからない（英文の部分の {shown} を出力から除外した）。"
                     "英文要旨なら、その最初の段落に set_role の abstract を提案（XML には反映せず、作業する人に知らせる）")
    for src, text, lang in unsplit_names:
        note = "（英文の氏名。split_name は和文の氏名にだけ使えるので、提案しない）" if lang == "en" else ""
        # 氏名の中の改行（Word の Shift+Enter。10 章と要確認で別に知らせる）は、行が分かれないよう「⏎」で示す（レポートの表と同じ）
        shown = text.replace("\n", "⏎")
        lines.append(f"- [{src}] 姓と名の区切りがない氏名{note}: 「{shown}」")
    for src, sp in name_splits:
        if sp.how not in ("longest", "context", "count"):
            continue
        why = {"longest": "字の間の空白のうち、いちばん長い空白で分けた",
               "context": f"いちばん長い空白が 2 か所以上あって決められないので、論文の中の表記「{sp.hint}」から推定",
               "count": "いちばん長い空白が 2 か所以上あって決められないので、字数だけから推定"}[sp.how].replace("\n", "⏎")
        shown = sp.name.replace("\n", "⏎")
        kind = ("字の間に空白があり、姓と名の境目を、いちばん長い空白で決めた氏名" if sp.how == "longest"
                else "字の間に空白があり、姓と名の境目を推定した氏名")
        basis = "決め方" if sp.how == "longest" else "推定"
        lines.append(f"- [{src}] {kind}: 「{shown}」（{basis}: 姓「{sp.surname}」・"
                     f"名「{sp.given}」。{why}）。英文の著者名・引用文献の表記などから、正しい境目を split_name で指定")
    lines += float_section(plan)
    return "\n".join(lines), []


def float_section(plan: ArticlePlan) -> list:
    """依頼文の「位置を決められなかった図表」と「位置を機械的に決めた図表（変更不可）」の節と、文字だけのテキストボックスの
    節（textbox_section）。"""
    lines = []
    if not plan.floats:
        return textbox_section(plan)
    unplaced = [info for info in plan.floats.values() if info.mode == "unplaced"]
    fixed = [info for info in plan.floats.values() if info.mode != "unplaced"]
    lay = plan.layout
    if unplaced:
        lines.append("\n# 位置を決められなかった図表（テキストボックス・グループ図形）")
        lines.append("以下のすべてについて、placements に位置（after）を必ず指定してください（中身の図・表の組み合わせは"
                     "決まっているので、items は空の一覧 [] にします）。")
        if lay and lay.columns:
            lines.append(f"本文の体裁: {lay.columns} 段組、1 段の幅 {lay.column_width_cm:.1f} cm（1 行 約 {lay.chars_per_line:.0f} 字）、"
                         f"行送り {lay.line_pitch_cm:.2f} cm（1 段 約 {lay.text_height_cm / lay.line_pitch_cm:.0f} 行）、"
                         f"本文の幅 {lay.text_width_cm:.1f} cm")
        seq = plan.body_seq
        rows = figure_rows(plan)
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
            lines.append("  中身（この順でまとめて置く）:")
            lines += float_contents(plan, info, rows)
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
            if info.mode == "caption":
                # 本文の図キャプションの図に含めた図形（structure.Classifier.take_float。修正計画 W1 の 2.3 の B6）
                how = f"本文の図キャプション [{info.caption_src}] の図に含めて配置済み"
            else:
                how = (f"段落 [{fl.anchor_src}] の前に配置済み" if info.mode == "mechanical" else "AI の指定で配置済み")
            lines.append(f"[{fl.fid}] {what}: {how}")
    return lines + textbox_section(plan)


def _content_line(head: str, q) -> str:
    """図形の中身の段落 1 つの行（段落の ID・スタイル名・リンク済みの印つきの全文。画像の印は書かない）。"""
    return f"{head}[{q.src}]（スタイル: {q.style_name}）{para_view_with_links(q, images=False)}"


def float_contents(plan: ArticlePlan, info, rows) -> list:
    """依頼文の「位置を決められなかった図表」の図形 1 つの「中身」の行（修正計画 W8 の手順 6）。

    図形の中身から変換ツールが組んだ図・表（structure.figure_rows のうち、その図形の行。FloatInfo.nodes と表のセルの図。XML の順）を、
    ID とキャプションの段落で書き、本文として出す段落（FloatInfo.body_paras）を続ける。docx の画像の ID は書かない（画像は AI に
    渡さない。図・表の画像は作業する人が用意する）。図・表に組めたものがなければ、文字のある段落を docx の順に書く。"""
    out = []
    for row in rows:
        if row.float_id != info.float.fid:
            continue
        name = {"fig": "図", "table": "表"}.get(row.kind, "キャプションのない図")
        if row.kind == "table" and row.caption is None:
            name = "キャプションのない表"
        label = f"{name} {row.fid}" if row.fid else name
        if row.caption is None:
            out.append(f"    {label}")
            continue
        out.append(_content_line(f"    {label}: ", row.caption))
        for q in getattr(row.node, "caption_more", None) or []:
            out.append(_content_line("      続き: ", q))
    for q in info.body_paras:
        if not q.is_blank:
            out.append(_content_line("    本文として出す段落: ", q))
    if not out:
        out = [_content_line("    段落: ", q) for q in info.paras if para_view(q, images=False).strip()]
    return out


def _box_size(plan: ArticlePlan, info) -> str:
    """文字だけのテキストボックスの大きさと位置の説明（依頼文）。"""
    tb, lay = info.box, plan.layout
    if info.float is not None:
        return f"docx に記録された大きさと位置: {describe(info.float, lay)}"
    col = column_cm(lay)
    if tb.width_cm is None:
        size = "幅は読めない"
    else:
        size = f"幅 {tb.width_cm:.1f} cm" + (f"（1 段の幅の {tb.width_cm / col:.2f} 倍）" if col else "")
    if tb.height_cm is not None:
        size += f"・高さ {tb.height_cm:.1f} cm"
    if tb.group:
        where = "グループ図形の中"
    elif tb.absolute:
        where = "VML の position:absolute の位置指定（位置の値は読み取っていない）"
    else:
        where = "行内（アンカー段落の行の中）"
    return f"大きさ: {size}。位置: {where}"


def _box_at(info) -> str:
    """囲みを置いた位置（依頼文。段落 ID で示す）。"""
    if info.where == "end":
        return "本文の最後"
    if info.where == "before":
        return f"段落 [{info.after_src}] の前"
    return f"段落 [{info.after_src}] の後ろ" if info.after_src else "本文の最初"


def _box_contents(info) -> list:
    return [f"    段落 [{q.src}]（スタイル: {q.style_name}）{para_view(q)[:80]}" for q in info.paras if not q.is_blank]


def textbox_section(plan: ArticlePlan) -> list:
    """依頼文の、文字だけのテキストボックス（structure.Classifier.place_boxes）の節: 「囲みか図の注記か決められなかった
    テキストボックス」（placements の kind box・label の指定が必要）、「位置を推定した囲み」（位置が違うときだけ指定）、
    「図に重ねた注記とみなして除外したテキストボックス」（本文の文章のときだけ kind box で指定。機械的な注記の判断も、本文の
    問題文などなら AI が囲みに戻せるようにする。暫定の判断）、「囲みとして位置を機械的に決めたテキストボックス（変更不可）」。
    該当がなければ、その節は出さない。"""
    from .structure import OUTSIDE_JA
    boxes = plan.textboxes
    undecided = [x for x, info in boxes.items() if info.kind == "undecided"]
    estimated = [x for x, info in boxes.items() if info.kind == "box" and info.estimated]
    labels = [x for x, info in boxes.items() if info.kind == "label"]
    fixed = [x for x, info in boxes.items() if info.kind == "box" and not info.estimated]
    lines = []

    def anchor(info):
        a = plan.paras.get(info.box.anchor_src)
        where = f"（本文の外〈{OUTSIDE_JA.get(info.outside, info.outside)}〉の段落）" if info.outside else ""
        return f"アンカー段落: [{info.box.anchor_src}]「{_para_text(a)[:30] if a else ''}」{where}"
    if undecided:
        lines.append("\n# 囲みか図の注記か決められなかったテキストボックス")
        lines.append("以下のすべてについて、placements に kind（box か label）を必ず指定してください（box なら after も）。")
        for x in undecided:
            info = boxes[x]
            lines.append(f"\n[{x}] {anchor(info)}")
            lines.append(f"  {_box_size(plan, info)}")
            lines.append(f"  画像の近く: {'はい' if info.near else 'いいえ'}")
            lines.append(f"  判定できなかった理由: {info.why}")
            lines.append("  中身:")
            lines += _box_contents(info)
    if estimated:
        lines.append("\n# 位置を推定した囲み（位置が違うときだけ placements で kind box と after を指定）")
        for x in estimated:
            info = boxes[x]
            lines.append(f"\n[{x}] {_box_at(info)}に置いた（推定の理由: {info.place_why}）。{anchor(info)}")
            lines.append(f"  {_box_size(plan, info)}")
            lines.append("  中身:")
            lines += _box_contents(info)
    if labels:
        lines.append("\n# 図に重ねた注記とみなして除外したテキストボックス（本文の文章のときだけ placements で kind box と after を"
                     "指定）")
        for x in labels:
            info = boxes[x]
            body = " / ".join(f"[{q.src}] {para_view(q)[:40]}" for q in info.paras if not q.is_blank)
            lines.append(f"[{x}] 段落 [{info.box.anchor_src}] の図の注記（{info.why}）: {body}")
    if fixed:
        lines.append("\n# 囲みとして位置を機械的に決めたテキストボックス（変更不可。placements に書かないこと）")
        for x in fixed:
            lines.append(f"[{x}] 囲み: {_box_at(boxes[x])}に配置済み")
    return lines


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
    except TypeError as e:
        # API キーが見つからないと、anthropic のライブラリは送るときに TypeError を投げる（「Could not resolve authentication
        # method」）。それ以外の TypeError（古いライブラリが引数を受け付けないなど）は、API キーの問題として知らせない
        if not (api_key or os.environ.get("ANTHROPIC_API_KEY")) or "authentication" in str(e).lower():
            out.error = ("API キーが見つかりません（Colab では「シークレット」に、コマンドラインでは環境変数に ANTHROPIC_API_KEY を"
                         f"登録してください）: {e}")
        else:
            out.error = f"AI の呼び出しに失敗しました: {e}"
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
    {"float": "s1", "after": "d47", "items": [],
     "reason": "図の上端はアンカー段落 d48 の上端から約 1.8 行下で、推定では直上の本文は d47。図1 の初出（d46）より後", "confidence": "中"},
    {"float": "x2", "after": "d30", "items": [{"kind": "box", "caption": [], "body": []}],
     "reason": "問題文とヒントの囲みで、図の注記ではない。本文で「次の問題」と述べた段落 d30 の直後", "confidence": "中"}
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

placements（「# 位置を決められなかった図表」と「# 囲みか図の注記か決められなかったテキストボックス」に挙げたものごとに 1 件。
どちらもなければ []。「# 位置を推定した囲み」「# 図に重ねた注記とみなして除外したテキストボックス」に挙げたものは、変えるときだけ
kind box で書く）の各項目:
- float: 図形の ID（s1 など）か、テキストボックスの ID（x1 など）
- after: 図表を置く位置（Word で表示したときに図の左上の直上にある本文の文章を含む段落の ID。その段落の直後に置く）。
  テキストボックスを label にするときは ""
- items: 図形（s1 など）では空の一覧 []（中身の図・表の組み合わせはプログラムが決める）。
  テキストボックス（x1 など）では、kind を box（本文の囲み。問題文・ヒントなど）か label（図に重ねた注記。矢印のラベルなど）に
  した組を 1 つだけ書き、caption と body は []
- reason, confidence: 下の operations と同じ

operations の各項目の意味（すべての操作に 12 項目すべてを書き、使わない項目は空文字 "" にする。occurrence は数値）:
- op: 操作の種類（link_citation / link_figure / link_table / link_note / link_formula / set_role / split_name）
- src: 対象の段落 ID（d18 など）
- text: リンクにする文字列（段落中のとおりに完全一致。引用文献なら年の部分だけ）
- occurrence: その段落で text が何回目に現れる箇所か（1 から数える）
- target: リンク先の ID（B3, F1, T2, fn1, FD1 など）
- role: set_role で指定する役割
- image, mathml: 使わない項目（いつも ""）
- surname, given: split_name の姓と名
- reason: 判断の根拠（日本語で具体的に）
- confidence: 高 / 中 / 低"""


def manual_prompt(request_text, images=()) -> str:
    """手動モード: チャットに貼り付ける依頼文。

    チャットの AI は、回答を地の文で書くと引用符を飾り文字（“ ”）に変えることがあり、JSON として読めなくなる。
    そのため、回答をコードブロック 1 つにまとめるよう求め、形式の見本を示す。docx の画像は AI に渡さない（修正計画 W1）ので、
    画像を添付する案内は書かない（images は使わない。引数は W8 が消す）。
    """
    system = system_prompt()
    return (f"{system}\n\n"
            f"{MANUAL_ANSWER_HEADING}\n"
            "- 回答は、```json で始まり ``` で終わるコードブロック 1 つだけにしてください。コードブロックの前後には何も書かないでください。\n"
            "- アーティファクトやファイルにはせず、この会話の中にコードブロックとして書いてください。\n"
            "- 文字列はすべて半角の二重引用符（\"）で囲んでください。飾りの引用符（“ ” ‘ ’）は使わないでください。\n"
            "- JSON は placements、operations、notes の順に書いてください（placements を最初に。回答が途中で切れても、"
            "図表の位置の指定が残るようにするためです）。\n"
            "- 「# 位置を決められなかった図表」に挙げた図形は、すべて placements に書いてください（省略できません）。"
            "なければ \"placements\": [] としてください。\n"
            "- 「# 囲みか図の注記か決められなかったテキストボックス」に挙げたもの（x1 など）も、すべて placements に書いてください"
            "（kind は box か label）。\n"
            "- 「# 図に重ねた注記とみなして除外したテキストボックス」に挙げたものは、本文の文章（問題文・ヒントなど）のときだけ、"
            "placements に kind box で書いてください。\n"
            "- 提案する操作がなければ \"operations\": [] とし、気づいたことだけを notes に書いてください。\n\n"
            "回答の見本（形式の見本です。内容はこの論文とは関係ありません）:\n"
            f"{MANUAL_EXAMPLE}\n\n"
            f"{FIELD_GUIDE}\n\n"
            "---\n"
            f"{request_text}\n")


SMART_QUOTES = "“”„‟‘’‚‛＂"

ASK_AGAIN = ("チャットで使っているときは、AI に「回答の書き方の見本の形で、```json のコードブロック 1 つで"
             "出し直してください」と頼んでください")
TOP_ARRAY_MSG = ("回答の JSON が一覧（[ ] で囲んだもの）になっています。回答は見本のとおり、{ で始まり placements・"
                 "operations・notes を持つ 1 つのまとまりにします。" + ASK_AGAIN)
SINGLE_OP_MSG = ("回答の JSON が操作 1 件だけ（op を持つ { }）になっています。操作は operations の一覧の中に書きます。"
                 + ASK_AGAIN)
NO_OPS_MSG = ("JSON に operations の一覧がありません（提案する操作がないときも \"operations\": [] と書く決まりです）。"
              + ASK_AGAIN)
OPS_NOT_LIST_MSG = "JSON の operations が一覧（[ ]）になっていません"
DEEP_MSG = "JSON の入れ子（[ ] や { } の中の [ ] や { }）が深すぎて読めません。" + ASK_AGAIN


# 断る文は、画面（ノートブック・1 画面版・コマンドライン）に共通の言い方で書く（ai_error の案内と同じ。error の文は、レポートの冒頭と
# コマンドラインの標準エラーにもそのまま出るので、手順番号・欄の名前・ファイル名は書かない）
PASTED_REQUEST_MSG = ("AI の回答ではなく、AI に送る依頼文が貼られています。依頼文をチャットの AI に送り、"
                      "返ってきた回答のコードブロックをコピーして貼り付けてください")
MANY_BLOCKS_MSG = ("回答の中に {{ で始まるコードブロックが {n} つあり、どれが回答か決められません。チャットで使っているときは、"
                   "AI に「回答の書き方の見本の形で、```json のコードブロック 1 つだけで出し直してください」と頼み、"
                   "返ってきたコードブロック 1 つをコピーして貼ってください")
SAMPLE_COPIED_MSG = ("回答の中に、依頼文の見本と同じ内容の項目が {n} 件あります。見本ではなく、この論文についての回答を"
                     "貼り付けてください")
RE_REQUEST_HEADING = re.compile(rf"^[ \t]*(?:{re.escape(REQUEST_HEADING)}|{re.escape(MANUAL_ANSWER_HEADING)})[ \t]*$", re.MULTILINE)


def _sample_keys() -> tuple:
    """依頼文の見本（MANUAL_EXAMPLE）の項目の印。戻り値: (operations の (op, src, reason) の集合, placements の (float, reason) の集合)。"""
    m = RE_FENCE.search(MANUAL_EXAMPLE)
    data = json.loads(m.group(1))
    return ({(o["op"], o["src"], o["reason"]) for o in data["operations"]},
            {(p["float"], p["reason"]) for p in data["placements"]})


def _copied_sample(data) -> int:
    """回答 data にある、見本と同じ項目（operations は op・src・reason、placements は float・reason が一致）の件数。"""
    if not isinstance(data, dict):
        return 0
    ops, pls = _sample_keys()
    n = 0
    for key, keys, fields in (("operations", ops, ("op", "src", "reason")), ("placements", pls, ("float", "reason"))):
        items = data.get(key)
        for it in items if isinstance(items, list) else []:
            vals = tuple(it.get(f) for f in fields) if isinstance(it, dict) else ()
            if vals and all(isinstance(v, str) for v in vals) and vals in keys:     # 文字列でない値（一覧など）は見本と同じではない
                n += 1
    return n


def _misuse(text: str) -> str:
    """回答として貼られたものが、依頼文そのもの・コードブロックの複数並びなら、断る理由の文。そうでなければ ""。

    依頼文の見出しの行（行頭だけ。JSON の文字列は改行を含められないので、回答の中身には現れない）があれば依頼文。
    回答が { で始まる（コードブロックの中身だけをコピーした）ときは、コードブロックを数えない。{ で始まるコードブロックが
    2 つ以上あるときは、どれを読むか推測しない（見本を引用してから答えた回答など）。
    """
    if RE_REQUEST_HEADING.search(text):
        return PASTED_REQUEST_MSG
    t = text.strip()
    if not t.startswith("{"):
        n = len(RE_FENCE.findall(t))
        if n >= 2:
            return MANY_BLOCKS_MSG.format(n=n)
    return ""


def _top_level_array(t: str) -> bool:
    """回答の JSON の最上位が一覧（[ ]）か。最初の { の直前（空白を除く）が [ なら、一覧の最初の要素とみなす。"""
    if t.startswith("{"):
        return False
    i = t.find("{")
    return i > 0 and t[:i].rstrip().endswith("[")


def parse_response(text: str) -> dict:
    """AI の回答（JSON）を読む。```json のコードブロックがあればその中身を使う。

    書式の崩れた回答を推測で直すことはしない。読めないときは、どこが・なぜ読めないかを示す。JSON の前後の文字（前置きの説明や、
    閉じの ``` のないコードブロックの後ろの説明など）は使わず、最初の { から最後の } までを読む（_before_trailing_text）。
    途中で切れた回答は読めない（ValueError）。最後まで書かれた図表の位置の指定だけは parse_cut_response で読める。
    最上位が一覧（[ ]）の回答は読まない（回答全体を一覧で囲んだ [{placements, operations, notes}] も読まない）。
    operations は必須（操作がなくても []）。入れ子が深すぎて読めない回答は、読めない回答（ValueError）とする。
    """
    why = _misuse(text)
    if why:
        raise ValueError(why)
    t, _ = _json_text(text)
    if _top_level_array(t):
        raise ValueError(TOP_ARRAY_MSG)
    if not t.startswith("{"):
        i, j = t.find("{"), t.rfind("}")
        if i < 0 or j <= i:
            raise ValueError("回答の中に JSON（{ で始まり } で終わる部分）が見つかりません。"
                             "AI に「回答の書き方」に従ってコードブロックで出し直すよう頼んでください")
        t = t[i:j + 1]
    try:
        data = json.loads(t)
    except RecursionError:
        raise ValueError(DEEP_MSG) from None
    except json.JSONDecodeError as e:
        data = _before_trailing_text(t, e)
        if data is None:
            line = t.splitlines()[e.lineno - 1] if 0 < e.lineno <= len(t.splitlines()) else ""
            hint = ""
            if cut_at_end(e, t):
                hint = CUT_HINT         # 途中で切れた回答（切れた文字列の中に、JSON の文字としての飾りの引用符があっても）
            elif any(q in line for q in SMART_QUOTES):
                hint = ("回答の中で、文字列が半角の \" ではなく飾りの引用符（“ ” など）で囲まれています。"
                        "AI に「文字列は半角の二重引用符で、```json のコードブロックで出し直してください」と頼み、"
                        "コードブロック右上のコピーボタンでコピーしてください。")
            raise ValueError(f"{e.lineno} 行目 {e.colno} 文字目で JSON として読めません（{e.msg}）。"
                             f"該当行: {line[:80]!r}。{hint}") from None
    if not isinstance(data, dict):
        raise ValueError(NO_OPS_MSG)
    if "operations" not in data:
        raise ValueError(SINGLE_OP_MSG if "op" in data else NO_OPS_MSG)
    if not isinstance(data["operations"], list):
        raise ValueError(OPS_NOT_LIST_MSG)
    if not isinstance(data.get("placements", []), list):
        raise ValueError("JSON の placements が一覧（[ ]）になっていません")
    copied = _copied_sample(data)
    if copied:
        raise ValueError(SAMPLE_COPIED_MSG.format(n=copied))
    data["notes"] = _notes_list(data.get("notes", []))
    return data


def _notes_list(notes) -> list:
    """回答の notes（人が確認すべきこと）を、文字列の一覧にする。

    一覧ならその要素の文字列（数値は str()、一覧・辞書・None などは捨てる）、文字列なら 1 件、それ以外は捨てる。
    捨てたものがあれば、その旨の注意を 1 件足す（黙って落とさない。1 文字ずつの「気づき」にもしない）。
    """
    if notes is None or notes == []:
        return []
    if isinstance(notes, str):
        return [notes]
    if not isinstance(notes, list):
        return [f"AI の回答の notes が一覧でも文字列でもなかった（{type(notes).__name__}）ので、使わなかった"]
    out, dropped = [], 0
    for n in notes:
        if isinstance(n, str):
            out.append(n)
        elif isinstance(n, (int, float)) and not isinstance(n, bool):
            out.append(str(n))
        else:
            dropped += 1
    if dropped:
        out.append(f"AI の回答の notes に文字列でない要素が {dropped} 件あったので、使わなかった")
    return out


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
    except (json.JSONDecodeError, RecursionError):
        return None


# 回答のコードブロック。始まりの ```（json）のすぐ後ろは {、閉じの ``` は行の頭にあるものだけ（JSON の文字列の中の ``` を
# コードブロックの始まり・閉じとみなさない。文字列は改行を含められないので、中の ``` は行の頭に来ない）。閉じの ``` がなければ
# 最後まで（回答が途中で切れると閉じがない）
RE_FENCE = re.compile(r"```[ \t]*(?:json|JSON)?[ \t]*\n?(?=\s*\{)(.*?)(^[ \t]*```|\Z)", re.DOTALL | re.MULTILINE)
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
# 文字列を閉じているように見える飾りの引用符（すぐ後ろが , ] } :。最後まで書かれた回答の書き損じ。cut_at_end）
RE_SMART_CLOSE = re.compile("[" + re.escape(SMART_QUOTES) + r"](?=\s*[,\]}:])")


def cut_at_end(e: json.JSONDecodeError, t: str) -> bool:
    """JSON の読み取りの誤り e が、回答が途中で切れたときの形か（それより前は JSON として正しい）。

    文字列の途中で入力が終わった（Unterminated string。閉じの " が見つからないまま終わったときだけ出る）か、
    「Expecting …」の誤りで、その位置から後ろが空か、値の書きかけ（数・true・false・null の途中）だけのとき。
    途中の書き損じ（飾りの引用符など）は、切れた回答ではない。最後まで書かれた回答で、最後の文字列の閉じだけが飾りの引用符
    のときも「Unterminated string」になるので、その文字列（e.pos から後ろ）に、文字列を閉じているように見える飾りの引用符
    （すぐ後ろが , ] } :。RE_SMART_CLOSE）があれば、切れた形とみなさない（文字列の中の「“主張”について」のような
    飾りの引用符は、JSON の文字として正しいので、切れた形とみなす）。
    """
    if e.msg.startswith("Unterminated string"):
        return not RE_SMART_CLOSE.search(t[e.pos:])
    return e.msg.startswith("Expecting") and bool(RE_PARTIAL_LITERAL.match(t[e.pos:].strip()))


def parse_cut_response(text: str):
    """途中で切れた回答から、最後まで書かれている図表の位置の指定（placements の要素）だけを読む。読めなければ None。

    JSON の読み取りの誤りが、回答の最後で切れた形（cut_at_end）のときだけ読む（途中の書き損じは読まない。閉じの ``` まで
    書かれたコードブロックの回答は、最後まで書かれているので読まない）。最上位のオブジェクトのキーと値を 1 組ずつ JSON として
    読み、placements の値は要素を 1 つずつ読む。途中で切れている要素と、それより後ろは読まない（推測で補わない。閉じ括弧も
    補わない）。operations と notes は、最後まで書かれた要素があっても使わない（リンクは件数が多く、途中までのリンクだけが
    付くと確かめにくい）。読めた要素も、ふつうの回答と同じく float_placements で検証する。
    入れ子が深すぎる回答と、最上位が一覧の回答は、読まない（None）。
    戻り値: {"placements": [...], "operations": [], "notes": []}
    """
    if _misuse(text):
        return None                    # 依頼文・複数のコードブロック（parse_response が断る。読めた一部を使わない）
    t, closed = _json_text(text)
    i = t.find("{")
    if i < 0 or closed or _top_level_array(t):
        return None
    t = t[i:]
    try:
        json.loads(t)
        return None                    # 切れていない（読める回答は parse_response で読む）
    except RecursionError:
        return None                    # 入れ子が深すぎる（切れたかどうかを決められない）
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
    except (json.JSONDecodeError, RecursionError):
        pass
    if not found or _copied_sample({"placements": found}):
        return None                    # 見本と同じ項目（parse_response と同じく、見本の写しは使わない）
    return {"placements": found, "operations": [], "notes": []}


# ---------------------------------------------------------------------------- 検証と適用
def _op_field(v, key):
    """操作の項目 v を文字列にする。戻り値: (値, 使えない理由 '')。

    文字列はそのまま、None は空文字、数値（int・float。bool は除く）は str()（"text": 2001 など。照合に使うだけの項目に限る。
    mathml は XML に書く項目なので数値は認めない）。一覧・辞書・bool などは使えない。
    """
    if v is None:
        return "", ""
    if isinstance(v, str):
        return v, ""
    if isinstance(v, (int, float)) and not isinstance(v, bool) and key != "mathml":
        return str(v), ""
    return "", f"項目 {key} が文字列でない（{type(v).__name__}）"


def split_ops(data, outcome=None):
    """回答の operations を、項目をすべて文字列にした操作の一覧にする（occurrence は整数）。

    項目の型が文字列にできない操作（_op_field）は、理由付きで outcome.rejected に記録して除く（outcome が None なら黙って除く）。
    操作が { } のまとまりでないもの（文字列・一覧など）も同じく記録して除く。
    """
    ops = []
    for raw in data.get("operations", []):
        if not isinstance(raw, dict):
            if outcome is not None:
                op = {k: "" for k in OP_SCHEMA["properties"]}
                op["occurrence"] = 1
                if isinstance(raw, str):
                    op["text"] = raw[:80]
                outcome.rejected.append((op, "操作が { } のまとまりでない（" + type(raw).__name__
                                         + "）ので、この操作は使わなかった"))
            continue
        op, bad = {}, ""
        for k in OP_SCHEMA["properties"]:
            if k == "occurrence":
                try:
                    op[k] = int(raw.get(k) or 1)
                except (TypeError, ValueError, OverflowError):
                    op[k] = 1
                continue
            op[k], why = _op_field(raw.get(k, ""), k)
            bad = bad or why
        if bad:
            if outcome is not None:
                outcome.rejected.append((op, bad + "ので、この操作は使わなかった"))
            continue
        ops.append(op)
    return ops


def set_role_problem(p, plan: ArticlePlan, role: str) -> str:
    """段落 p に set_role で役割 role を指定できない理由（指定できれば ''）。

    回答の検証（role_overrides）と、依頼文の除外の一覧の案内（set_role_hint）の両方で使う（指定しても必ず捨てられる操作を
    AI に勧めないように、判定を 1 か所にまとめる。修正計画の N6）。上から順に見て、最初に当たった理由を返す。
    浮動配置の図形（float_id）の段落は、すべて placements で指定させる。浮動配置でないテキストボックス（行内・VML）の段落には
    fig_caption・table_caption・exclude だけを受け付け（VML のキャプションへの fig_caption は今までどおり効く）、ほかの役割は
    囲みか図の注記かを placements の kind box・label で指定させる（修正計画の F の (1)）。囲みとして位置を機械的に決めた
    文字だけのテキストボックス（placements でも変えられないもの。_box_placement_problem）の段落と、囲み・図の注記の判断の
    対象でないテキストボックス（plan.textboxes にないもの: 図表の入ったテキストボックス、本文の外・表のセルのものなど）の段落には、
    placements を案内しない（案内が行き止まりにならないように）。
    """
    if role not in ROLES:
        return f"役割「{role}」は指定できない"
    box = plan.textboxes.get(p.textbox_id) if p.textbox_id else None
    fixed = (f"テキストボックス {p.textbox_id} は囲み（boxed-text）として扱いと位置を機械的に決めたので、変更できない"
             if box is not None and box.kind == "box" and not box.estimated else "")
    if p.float_id:
        return fixed or "テキストボックス・グループ図形の中の段落の役割は placements で指定する"
    if p.textbox_id and role not in ("fig_caption", "table_caption", "exclude"):
        if fixed:
            return fixed + "（浮動配置でないテキストボックスの段落に指定できる役割は fig_caption・table_caption・exclude だけ）"
        if box is None:
            return (f"テキストボックス {p.textbox_id} は囲み・図の注記の判断の対象でない（図表の入ったテキストボックス・本文の外の"
                    "テキストボックスなど）ので、段落に指定できる役割は fig_caption・table_caption・exclude だけ")
        return ("浮動配置でないテキストボックスの段落に指定できる役割は fig_caption・table_caption・exclude だけ"
                "（囲みか図の注記かは placements の kind box・label で指定する）")
    if p.src in plan.note_of:
        # 参照のない注も含めて、Word の脚注・文末脚注の段落すべて（構造の組み立てで役割を見ないので、指定しても何も変わらない）
        return "Word の脚注・文末脚注の段落の役割は変えられない（注の区切りは Word のとおりにする）"
    region = plan.region.get(p.src, "")
    if not region:
        return "表のセルなど、論文の中の位置が決まっていない段落の役割は変えられない"
    if any(q is p for q in plan.title_en + plan.subtitle_en):
        # 暫定の判断（修正計画にない）: 英文題目を abstract・exclude などにすると、英文副題が XML から落ちる
        return "英文の題目・副題の段落の役割は変えられない（変えると英文の題目・副題が XML から落ちる）"
    if role == "app_heading" and region != "app" and not any(q is p for q in plan.abstract):
        return "資料の見出し（app_heading）にできるのは、英文要旨と資料の段落だけ"
    if role not in REGION_ROLES.get(region, set()):
        return f"この位置（{region}）では役割「{role}」を指定できない"
    return ""


def set_role_hint(p, plan: ArticlePlan) -> str:
    """依頼文の除外の一覧で、段落 p に添える set_role の案内。

    除外した段落の役割の指定は、Word のスタイルで直す提案になる（XML は変えない。決定 5）ので、案内は「確かめるだけ」の 1 通りにする。
    ただし、set_role_problem でどの役割も指定できない段落（Word の注・著者表の中の段落など）には、必ず捨てられる set_role を
    勧めない（N6）。囲みか図の注記か決められなかったテキストボックスの段落には、placements の kind box・label を案内し、図に
    重ねた注記とみなしたテキストボックスの段落には、本文の文章なら kind box で囲みにできることを案内する（set_role では囲みにできない）。
    """
    box = plan.textboxes.get(p.textbox_id) if p.textbox_id else None
    if box is not None and box.kind == "undecided":
        return "（囲みなら placements の kind box、図の注記なら label で指定）"
    if box is not None and box.kind == "label":
        return "（図の注記でなく本文の文章なら、placements の kind box で囲みに指定）"
    if any(not set_role_problem(p, plan, r) for r in ROLES if r != "exclude"):
        return "（確かめるだけ。本文に必要なら set_role で提案）"
    return "（この段落の役割は set_role では変えられない）"


def boundary_kind(p, plan: ArticlePlan, role: str) -> str:
    """段落 p への役割 role の指定が、注の区切り・資料の始まりの直し（BOUNDARY_KINDS）なら、その kind の語（でなければ ''）。

    set_role_problem を通った指定だけに使う（領域の確かめは set_role_problem が済ませている）。
    """
    region = plan.region.get(p.src, "")
    app_title = any(a.title is p for a in plan.apps)
    if region == "fn" and role in ("fn_start", "p"):
        return "注の始まり" if role == "fn_start" else "注の続き"
    if role == "app_heading":
        return "資料の見出し"
    if app_title and role in ("abstract", "p"):
        return "英文要旨の続き" if role == "abstract" else "資料の本文"
    return ""


def boundary_problem(p, plan: ArticlePlan, role: str) -> str:
    """段落 p に役割 role を指定して XML に反映できない理由（反映できれば ''）。

    判定の 1 か所（今の形の回答の set_role の検証〈role_overrides〉と、W8 の新しい形の回答の boundaries が使う）。
    set_role_problem を先に通し、通った指定のうち注の区切り・資料の始まりの直し（boundary_kind）でないものは STYLE_ONLY_WHY を返す
    （Word のスタイルで直す提案にする。所有者の決定 5）。
    """
    why = set_role_problem(p, plan, role)
    if why:
        return why
    return "" if boundary_kind(p, plan, role) else STYLE_ONLY_WHY


def role_style(journal, role: str) -> str:
    """役割 role の Word のスタイル名（journal.styles で、その役割の最初の日本語のスタイル名。なければ ''）。"""
    styles = getattr(journal, "styles", None) or {}
    return next((name for name, r in styles.items() if r == role and not name.isascii()), "")


def style_fix(op: dict, journal) -> StyleFix:
    """区切りの 5 つ以外の set_role を、Word のスタイルで直す提案にする（XML には反映しない）。"""
    role = op["role"]
    style = "" if role == "exclude" else role_style(journal, role)
    if role == "exclude":
        how = EXCLUDE_HOW
    elif style:
        how = f"Word で段落のスタイルを「{style}」にする"
    else:
        how = f"Word で段落を{ROLES.get(role, role)}のスタイルにする"
    return StyleFix(op["src"], role, style, how, op.get("reason", ""), op.get("confidence", ""))


def role_overrides(ops, plan: ArticlePlan, outcome: AIOutcome, journal=None) -> dict:
    """set_role 操作を検証し、段落の役割の上書き表にする（構造の組み立てをやり直すため）。可否は boundary_problem で決める。

    上書き表に入れるのは、注の区切り・資料の始まりの直し（BOUNDARY_KINDS）だけ。ほかの役割の指定は STYLE_ONLY_WHY で不採用にし、
    同じ内容を Word のスタイルで直す提案（AIOutcome.style_fixes。スタイル名は journal から）に入れる（所有者の決定 5）。
    反映した直しは AIOutcome.boundaries に記録する（構造の衝突で使わなかったものは pipeline._reject_roles が除く）。
    """
    out = {}
    for op in ops:
        if op["op"] != "set_role":
            continue
        src, role = op["src"], op["role"]
        if src not in plan.paras:
            outcome.rejected.append((op, f"段落 {src} が存在しない"))
            continue
        p = plan.paras[src]
        why = boundary_problem(p, plan, role)
        if why:
            outcome.rejected.append((op, why))
            if why == STYLE_ONLY_WHY:
                outcome.style_fixes.append(style_fix(op, journal))
            continue
        outcome.boundaries.append(Boundary(src, boundary_kind(p, plan, role), role, op.get("reason", ""),
                                           op.get("confidence", "")))
        out[src] = role
    return out


def placement_op(pl) -> dict:
    """配置の指定を、レポートの「操作」の一覧に載せる形にする。"""
    pl = pl if isinstance(pl, dict) else {}
    items = pl.get("items") if isinstance(pl.get("items"), list) else []
    def ids(v):                         # 一覧でない値（数値など）はここで落とさない。不採用の理由は _placement_problem が示す
        return ",".join(map(str, v)) if isinstance(v, list) else ("" if v in (None, 0, "") else str(v))
    what = "；".join(f"{it.get('kind')}: キャプション {ids(it.get('caption'))} / 本体 {ids(it.get('body'))}"
                     for it in items if isinstance(it, dict))
    return {"op": "place_float", "src": str(pl.get("float", "")), "text": what, "target": str(pl.get("after", "")),
            "role": "", "image": "", "reason": str(pl.get("reason", "")), "confidence": str(pl.get("confidence", ""))}


def float_placements(data, plan: ArticlePlan, outcome: AIOutcome) -> dict:
    """placements（図表の位置）を検証し、図形の ID → 指定 の表にする（構造の組み立てをやり直すため）。

    採用するのは、位置を決められなかった図形について、本文の段落の後ろを指定したもの。中身の組み合わせ（items）は読まない
    （組み合わせは変換ツールが決める。修正計画 W1 の 2.7）。機械的に配置した図形は変更させない。
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
        # 浮動配置の図形の items（中身の組み合わせ）は使わない（組み合わせは変換ツールが決める）。採用の記録（2 章）の操作の欄には
        # 書かれたまま載せる（placement_op。黙って捨てない）。label は after を使わない（書かなくてよい）
        spec = {"after": pl.get("after"), "reason": op["reason"],
                "confidence": op["confidence"] if op["confidence"] in ("高", "中", "低") else "低", "op": op}
        if pl["float"] in plan.textboxes:
            spec["kind"] = pl["items"][0]["kind"]       # 文字だけのテキストボックス: box（囲み）か label（図の注記）
        out[pl["float"]] = spec
    for fid, (spec, k) in ends.items():
        if fid in out:
            continue                    # 同じ図形の、後ろの正しい指定を採用した
        out[fid] = spec
        op, why = outcome.rejected[k]
        outcome.rejected[k] = (op, why + "。図表は本文の最後に仮に置いた（手作業で正しい位置に移すこと）")
    return out


def _placement_problem(pl, plan: ArticlePlan, body: set, done: dict) -> str:
    """配置の指定 pl を採用しない理由（採用できれば ''）。

    浮動配置の図形では、図形の ID と置く位置（after。本文の段落か）だけを検証する。中身の組み合わせ（items）は、あっても
    なくてもよく、読まない（組み合わせは変換ツールが決める。structure.Classifier.float_units。修正計画 W1 の 2.7）。
    文字だけのテキストボックスは、今までどおり items[0].kind（box か label）を読む（_box_placement_problem）。
    """
    if not isinstance(pl, dict):
        return "指定の形式が正しくない"
    fid, after, items = pl.get("float"), pl.get("after"), pl.get("items")
    if not isinstance(fid, str) or not (after is None or isinstance(after, str)):
        return "float と after は文字列で書く"
    box = plan.textboxes.get(fid)
    if box is not None:
        for it in items if isinstance(items, list) else []:
            if not isinstance(it, dict):
                continue                # 形式の不備は、以降の検証が理由を示す
            for key in ("caption", "body"):
                v = it.get(key)
                if not v:
                    continue            # None・""・0・false は、以前どおり空の一覧として扱う
                if not isinstance(v, list):
                    return f"items の {key} は一覧（[ ]）で書く"
                if not all(isinstance(x, str) for x in v):
                    return f"items の {key} の要素は文字列（段落・表・画像の ID）で書く"
        return _box_placement_problem(fid, box, after, items, body, done)
    info = plan.floats.get(fid)
    if info is None:
        return (f"{fid} は「位置を決められなかった図表」「囲みか図の注記か決められなかったテキストボックス」"
                "「位置を推定した囲み」「図に重ねた注記とみなして除外したテキストボックス」にない")
    if info.mode == "caption":
        # 本文の図キャプションの図に含めた図形（structure.Classifier.take_float。修正計画 W1 の 2.3 の B6）
        return f"図形 {fid} は本文の図キャプション [{info.caption_src}] の図に含めて配置した図形なので、位置を変更できない"
    if info.mode != "unplaced":
        return f"図形 {fid} は位置を機械的に決めた図表なので、位置を変更できない"
    if fid in done:
        return f"図形 {fid} の指定が 2 回ある（最初の指定を採用）"
    if after not in body:
        return f"置く位置の段落 {after} は本文の段落ではない（図形の中の段落・表のセル・本文以外は指定できない）"
    return ""


def _box_placement_problem(xid, box, after, items, body: set, done: dict) -> str:
    """文字だけのテキストボックスの指定（placements の kind box・label）を採用しない理由（採用できれば ''）。

    指定できるのは、囲みか図の注記か決められなかったもの（box か label）、位置を推定した囲み（box で位置だけ）と、図に重ねた
    注記とみなしたもの（box で本文の囲みに戻すだけ。機械的な注記の判断でも、本文の問題文などなら AI が戻せるようにする。
    暫定の判断）。box の after は本文の段落だけ。label の after は使わない。囲みとして位置を機械的に決めたもの（図の左上が
    アンカー段落の左上にある浮動配置・行内）と空白だけのものは変更させない。
    """
    if box.kind not in ("undecided", "label") and not (box.kind == "box" and box.estimated):
        what = "囲み（boxed-text）として扱いと位置" if box.kind == "box" else "扱い"
        return f"テキストボックス {xid} は{what}を機械的に決めたので、変更できない"
    if xid in done:
        return f"テキストボックス {xid} の指定が 2 回ある（最初の指定を採用）"
    if (not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict)
            or items[0].get("kind") not in ("box", "label")):
        return "テキストボックスの items は、kind が box か label の組を 1 つだけ書く"
    if items[0].get("caption") or items[0].get("body"):
        return "テキストボックスの指定では caption と body は空の一覧 [] にする"
    if items[0]["kind"] == "label" and box.kind == "box":
        return "位置を推定した囲みには box だけを指定できる"
    if items[0]["kind"] == "label" and box.kind == "label":
        return (f"テキストボックス {xid} は図に重ねた注記とみなして除外したので、指定できるのは box（本文の囲みに戻す）だけ"
                "（図の注記のままなら書かない）")
    if items[0]["kind"] == "box" and (not isinstance(after, str) or after not in body):
        return f"置く位置の段落 {after} は本文の段落ではない（図形の中の段落・表のセル・本文以外は指定できない）"
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


def label_ranges(plan: ArticlePlan, split: bool) -> dict:
    """split_labels のとき <label> に分ける図表キャプションの先頭の範囲（段落の ID → 範囲の終わり）。

    分け方は builder の規則（RE_LABEL_SPLIT。先頭の空白と番号）をそのまま使う。<label> の中は emit.LABEL が xref=False なので、
    この範囲にかかるリンクは XML に出ない。
    """
    from .builder import RE_LABEL_SPLIT
    out = {}
    if not split:
        return out
    caps = [f.caption for f in plan.figures] + [t.caption for t in plan.tables]
    for c in caps:
        m = RE_LABEL_SPLIT.match(c.plain()) if c is not None else None
        if m and m.group(2):
            out[c.src] = m.end(2)
    return out


# formula_image（画像の数式の書き起こし）を採用しない理由（2 章の不採用の一覧）
FORMULA_IMAGE_WHY = "docx の画像を AI に渡していないので採用しない（画像の数式の書き起こしは使わない）"


def apply_ops(ops, plan: ArticlePlan, doc, outcome: AIOutcome, split: bool = False):
    """set_role 以外の操作を検証して適用する（構造を組み直した後の plan に対して）。

    split は split_labels（図表キャプションの先頭の番号を <label> に分けるか）。分けるとき、その番号の範囲にかかるリンクは採用しない。
    """
    from .linker import apply_span, range_linked
    labels = label_ranges(plan, split)
    ids = {"B": {r.rid for r in plan.refs}, "F": {f.fid for f in plan.figures if f.fid},
           "T": {t.tid for t in plan.tables}, "fn": {f.fid for f in plan.fns}, "FD": {f.fid for f in plan.formulas if f.fid}}
    # リンクを出せない段落（emit の xref が偽の文脈で書く段落）: 題目・著者名・所属・引用文献（no_link_paras）と別行数式
    nolink = dict(plan.no_link_paras())
    for fm in plan.formulas:
        nolink.setdefault(fm.para.src, "別行数式")
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
            what = f"段落の役割を「{ROLES[op['role']]}」とした。"
            para = plan.paras.get(op["src"])
            if op["role"] == "p" and any(q is para for q in plan.abstract):
                # abstract で英文要旨に戻した後ろの、資料の見出しでない段落への p（structure.Classifier.build_front_en）。
                # 採用しても役割は変わらないので、そのとおりに記録する
                what = "段落を資料の中の段落（p）にする指定だが、AI の abstract で英文要旨に戻した後ろの段落なので、英文要旨の段落のままにした。"
            d = plan.decide("ai", "style", op["src"], f"{what}{op['reason']}", op["confidence"])
            outcome.accepted.append((op, d))
            continue
        if kind in TARGET_PREFIX:
            src, text, target = op["src"], op["text"], op["target"]
            p = plan.paras.get(src)
            if p is None:
                outcome.rejected.append((op, f"段落 {src} が存在しない"))
                continue
            if src in nolink:
                outcome.rejected.append((op, f"{nolink[src]}の段落には、XML でリンクを出せないので付けない"))
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
            if src in labels and rng[0] < labels[src]:
                outcome.rejected.append((op, "図表キャプションの先頭の番号（<label> に分ける部分）にはリンクを出せないので付けない"))
                continue
            spec = LinkSpec(kind="xref", attrs={"ref-type": REF_TYPE[kind], "rid": target}, origin="ai")
            apply_span(p, rng[0], rng[1], spec)
            what = {"link_citation": "引用", "link_figure": "図の参照", "link_table": "表の参照", "link_note": "注の参照",
                    "link_formula": "数式の参照"}[kind]
            d = plan.decide("ai", "citation" if kind == "link_citation" else "xref", src,
                            f"「{text}」を{what}として {target} にリンクした。{op['reason']}", op["confidence"])
            spec.decision_id = d.did
            outcome.accepted.append((op, d))
            if kind in ("link_figure", "link_table"):
                # 機械的にはリンクしなかった図・表の参照（plan.float_unlinked）に AI がリンクを付けたら、その分は残りから除く
                # （要確認の知らせ〈report._float_ref_action〉は、AI もリンクを付けなかった参照だけを挙げる）。同じ種類・同じ段落で、
                # 参照の範囲が AI のリンクの範囲と重なるものだけを除く（リンクの対象でない同じ文字〈「地図1」の「図1」〉に AI がリンクを
                # 付けても、本当にリンクされていない参照は残る）
                word = "図" if kind == "link_figure" else "表"
                plan.float_unlinked[:] = [u for u in plan.float_unlinked
                                          if not (u.word == word and u.src == src and u.start < rng[1] and rng[0] < u.end)]
            continue
        if kind == "formula_image":
            # docx の画像を AI に渡さなくなった（修正計画 W1）ので、画像を読み取った数式は使わない（操作そのものは W8 が消す）
            outcome.rejected.append((op, FORMULA_IMAGE_WHY))
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
            if sur and giv and core == sur + giv:
                a.split_ja = lead + len(sur)
            else:
                at = spaced_split(text, sur, giv)
                if at is None:
                    outcome.rejected.append((op, f"姓「{sur}」と名「{giv}」をつなげても氏名「{core}」にならない"))
                    continue
                a.split_ja = at
            d = plan.decide("ai", "name", src, f"氏名「{core}」を姓「{sur}」・名「{giv}」に分けた。{op['reason']}",
                            op["confidence"])
            outcome.accepted.append((op, d))
            continue
        outcome.rejected.append((op, f"未知の操作「{kind}」"))


def spaced_split(text: str, sur: str, giv: str):
    """字の間に空白のある和文の氏名（前後を除いた中に空白の連なりが 2 つ以上。「試　験　六　郎」）への split_name の位置: 空白を除いた
    姓・名をつなげたものが、空白を除いた氏名と一致すれば、姓の最後の字の次の位置（text の上）。一致しなければ None。

    空白が 1 か所以下の氏名には使わない（これまでどおり、空白も含めて完全に一致したときだけ受け付ける。C043）。"""
    ws = " \u3000\t"
    core_s, core_e = len(text) - len(text.lstrip(ws)), len(text.rstrip(ws))
    if len(re.findall(r"[ \u3000\t]+", text[core_s:core_e])) < 2:
        return None
    s_n, g_n = re.sub(r"[ \u3000\t]+", "", sur or ""), re.sub(r"[ \u3000\t]+", "", giv or "")
    if not s_n or not g_n or re.sub(r"[ \u3000\t]+", "", text[core_s:core_e]) != s_n + g_n:
        return None
    k = 0
    for i in range(core_s, core_e):
        if text[i] not in ws:
            k += 1
            if k == len(s_n):
                return i + 1
    return None


def parse_mathml(s: str):
    if not s or "<" not in s:
        return None, "空"
    t = s.strip()
    if "xmlns" not in t.split(">", 1)[0]:
        t = re.sub(r"^<(?:mml:)?math", f'<math xmlns="{MML_NS}"', t, count=1)
    t = t.replace("<mml:", "<").replace("</mml:", "</")
    if "<!doctype" in t.lower():
        return None, "DOCTYPE（実体の定義）は使えない"
    try:
        el = etree.fromstring(t.encode("utf-8"), etree.XMLParser(resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError as e:
        return None, str(e)
    if etree.QName(el).localname != "math":
        return None, "根要素が math ではない"
    for x in el.iter():
        if not isinstance(x.tag, str):
            # 実体参照・コメント・処理命令は、そのまま出力に入ると XML として読めない・数式でない文字が入るので使わない
            return None, "実体参照・コメント・処理命令は使えない"
        q = etree.QName(x)
        if q.namespace != MML_NS or q.localname not in MATHML_ELEMENTS:
            return None, f"使えない要素 {q.localname}"
        for a in list(x.attrib):
            if etree.QName(a).localname not in MATHML_ATTRS:
                del x.attrib[a]
    el.attrib.pop("display", None)
    return el, ""
