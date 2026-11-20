"""route pdf（出版版 PDF に合わせる）: 出版版 PDF に表記を合わせた docx（Word の変更履歴つき）を作る。

Word の文字が正で、出版版 PDF（印刷所の組版を経たもの）からは表記の違い（区分 (1)。pdfmatch.grade）だけを補う。docx の段落と
PDF の照合（pdfmatch.py）の結果から、段落ごとの直す箇所を決め（plan_fixes）、書き込まない直しに理由を付け（hold）、元の
docx の XML（前処理しないもの）のランを分けて、削除（w:del）と挿入（w:ins）の変更履歴として書き込む（作成者名は AUTHOR の
1 つ）。書式（太字・斜体・上付きなど）は、直す文字のランの書式をそのまま使う。

  ・直すもの（表記の違い。(1)。Fix の kind width・space・glyph）: 英数字・記号の全角・半角と、その文字のすぐ前後の PDF にない
    空白、句読点（句点どうし・読点どうし）、ダッシュ・ハイフンの字形、引用符の字形・向き、英文の題目・副題・著者名・所属の
    大文字・小文字（pdfmatch.typeset_pair）
  ・書き込まないもの（内容の違い。Fix の kind text）: 語句の追加・削除・置き換えなど、表記の違いに還元できないもの（「ふくろう」
    →「みみずく」など）。plan_fixes は「PDF に合わせるなら何を変えるか」を返す関数のまま、内容の違いの Fix も作る（1 つの違いに
    表記の違いと内容の違いが混ざるときは pdfmatch.diff_parts で分ける）。書き込む直前に hold が理由（CONTENT_REASON）を付け、
    同じ違いを分けた表記の直しも丸ごと止める（FixGroup。spread_reasons）。書き込まない内容の違いと、理由（pdfmatch.TextDiff.why）
    のある決められない違いに、間の docx の文字が 1 文字以下で続く表記の直しも、連鎖でたどって書き込まない（一続きの規則。
    ADJACENT_REASON。「(1)」と PDF の「１）」で「(１）」のような、docx にも PDF にもない形を作らない。止めたかっこの組のもう片方も
    止める）。かっこの全角・半角の直しは、組のもう片方が後の段階で止まったときや、もう片方に直す箇所がないとき（リンクの中の
    文字など）も、組の全角・半角が混ざる形にならないように止める（Fix.pair。spread_reasons）。ただし数式・Word が付ける番号・リンクの文字にかかる違い（UNFIXABLE_REASON）は、一続きの規則の始まりにしない。
    理由のない kind text の Fix を write_fixed_docx に渡すと ValueError（hold を通さずに内容の違いを書き込まないための守り。
    check_held）
  ・直さないもの: 表のセル・数式・図の中の文字（照合しない）、PDF の中に見つからない段落、数式・Word が付ける番号・
    リンクの文字にかかる違い、フィールドの結果・タブ・記号などの文字、空白だけの違い（PDF の空白は信頼できない）、
    段落の文字列を読み取り（docx_reader）と同じに組み立てられない段落（ルビを含む段落など）、PDF のページ番号・誌名の行・
    柱・投稿受付日などや、docx にない図・表の中の文字とみなした文字（docx に足さない。PDF の側にその文字しかない位置の
    docx の文字も消さない）、照合で直し方を決められなかった違い（pdfmatch.TextDiff.why。段落の最初・最後の、どこまでが
    段落の文字か決められない文字、文字として取り出せない数式の位置にかかるものなど）、英文の文と文の間の全角の「，」「．」（docx の
    すぐ後ろが空白でない半角の英数字で、PDF ではすぐ後ろに空白があるもの。半角にすると「night.They」の形になり、空白は足さない
    ので全角のまま残す。NOSPACE_REASON。C111）。1 つの違いを分けた直す箇所の一部が
    ほかの直す箇所と重なるときは、その違いの直す箇所をすべて直さない。
    PDF にない空白の削除（kind space）は、根拠の全角・半角の直し（kind width。PdfCheck.drop_basis）に従わせる（Fix.needs）:
    根拠の直しを直さないことになったら（重なる・内容の違いに続く・構造の確かめ・注の番号を守る・直せない文字にかかるなど、
    どの段階でも。spread_reasons）、空白の削除も直さない（空白だけを消すと、docx にも PDF にもない文字になる）。向きは片方向で、
    空白の削除が直せなくても、根拠の全角・半角の直しは直す（空白が残るだけで、docx のままの文字なので）。根拠が複数の全角・半角の
    直しなら、どれか 1 つでも直さないときは直さない。根拠に Word が付ける番号がある空白の削除は、番号の直し（変換のときに必ず
    PDF に合わせる）が止められることがなく、番号だけで消してよい根拠になるので、全角・半角の直しに従わせない
  ・Word が付ける番号（自動段落番号・脚注番号）は docx の文字ではないので、ここでは直さず、変換のときに全角・半角と字形を
    PDF に合わせる（pipeline の plan.pdf_numbers）

できた docx は Word で開いて、変更を 1 つずつ承諾・却下できる。本ツールの読み取りは、挿入を残し削除を除いた文字
（すべて承諾した状態）を読むので、この docx をPDF のないときと同じ処理で変換すると、表記の直しを当てはめた文字の XML になる。
書き込んだ後に docx を読み直し、段落の文字列が直した結果と一致することを確かめる（一致しない段落は直さずに作り直す）。
段落の役割・領域・リンク・注の区切り・著者と所属の数・氏名の姓と名の分け方が元の docx と同じに決まることも確かめる
（_structure。合わない箇所は直さずに作り直す）。

段落の対応と文字は、読み取り・検証と同じ規則（ooxml の文字ポリシー）で決める。段落記号の削除でつながる段落
（ooxml.joined_paragraphs）は、連鎖の最初の段落の ID の 1 つの段落として照合・直し、直す文字のある w:p の w:t に書き込む
（段落記号の削除をまたぐ直しは、前と後ろの w:p に分かれて入る。段落記号の削除そのものには触らない）。隠し文字の判定は
ooxml.HiddenRule（word/styles.xml から作る）。
"""
from __future__ import annotations

import copy
import datetime as _dt
import difflib
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from .model import OBJ
from .ooxml import (BR_TEXT_TYPES, MC_NS, M_NS, NO_RULE, HiddenRule, choose_alternate, graphic_atoms, joined_paragraphs,
                    paragraph_ids, paragraph_mark_deleted, parse_xml, preprocess, sym_char, w, w_t_text)

XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
# 書き込む変更履歴の作成者名（表記の直しだけを書くので種類で分けない。利用者の判断、2026-11）。route pdf の補完の確かめ（fidelity）も、
# この名前で、このツールが書き込んだ変更履歴を見分ける
AUTHOR = "jasme-jats（出版版 PDF による補完）"
# 直す段落のある XML の部品と、段落 ID の頭文字（docx_reader・fidelity と同じ。Word の脚注・文末脚注の段落も直す）
PARTS = {"word/document.xml": "d", "word/footnotes.xml": "f", "word/endnotes.xml": "e"}
# 直してよいラン（w:r）の親。既存の変更履歴（w:ins / w:del）の中やハイパーリンクの中は直さない
RUN_PARENTS = {w("p"), w("smartTag"), w("customXml"), w("sdtContent")}


@dataclass
class Fix:
    src: str
    start: int            # docx の段落（plain）の中の範囲 [start, end)。start == end なら、その位置に足す
    end: int
    new: str              # PDF の文字（削除なら空）
    # 表記の違い（(1)）: width（英数字・記号の全角・半角）/ space（PDF にない空白の削除）/ glyph（句読点・ダッシュ・ハイフン・
    # 引用符・大文字・小文字。細かい種類は pdfmatch.typeset_pair(old, new, case=True) で分かる）。内容の違いと、直せない違い
    # （reason に理由）: text（書き込まない。hold が理由を付ける）
    kind: str
    old: str = ""         # docx の文字
    applied: bool = False
    reason: str = ""      # 直さなかった理由
    # 1 つの違い（TextDiff）を分けた直す箇所の組（FixGroup）。None なら単独。組の 1 つでも直さないことになったら、後の段階でも
    # （spread_reasons）、組の全部を直さない（双方向）
    group: object = field(default=None, repr=False, compare=False)
    # kind space の空白の削除が従う、根拠の全角・半角の直し（Fix）。どれか 1 つでも直さないことになったら、この空白の削除も
    # 直さない（片方向。根拠の直しは、空白の削除に関係なく直す）
    needs: list = field(default_factory=list, repr=False, compare=False)
    # かっこの全角・半角の直しの、組のもう片方のかっこ（hold が付ける。_BracketPair）。直すと組の全角・半角が混ざる形
    # （「(1）」）になるなら、どの段階でも直さない（spread_reasons。組のもう片方の直しが止まったときと、もう片方に直す箇所が
    # ないとき〈リンクの中の文字など〉）
    pair: object = field(default=None, repr=False, compare=False)

    @property
    def typeset(self) -> bool:
        """表記の違い（(1)）の直す箇所か。"""
        return self.kind != "text"


@dataclass(eq=False)
class FixGroup:
    """いっしょに直す箇所の組（双方向）。一部だけを当てはめると、docx にも PDF にもない文字になるもの。

    1 つの違い（pdfmatch.TextDiff）を分けた直す箇所（「pp.45－58」を「pp.46-5-58」にしないため）。全角・半角の直しと、その
    すぐ隣の PDF にない空白の削除は、組にせず片方向（Fix.needs）にする。"""
    members: list = field(default_factory=list)


def link_fixes(a: Fix, b: Fix) -> None:
    """a と b をいっしょに直す組にする（どちらかがすでに組なら、組を 1 つにまとめる）。"""
    ga = a.group or FixGroup(members=[a])
    a.group = ga
    if b.group is not ga:
        for m in (b.group.members if b.group is not None else [b]):
            m.group = ga
            ga.members.append(m)


def _fix_desc(f: Fix) -> str:
    return "空白の削除" if f.kind == "space" else f"全角・半角の直し「{f.old}」→「{f.new}」"


def spread_reasons(fixes) -> bool:
    """直さないことにした直す箇所（reason がある）に連動して、まだ直すことにしている直す箇所も直さないことにする。

    ・同じ組（Fix.group。1 つの違いを分けた直す箇所）の直す箇所: 組の一部が直らなければ、組の全部を直さない（双方向）。
      理由は、直さない理由のまま。
    ・空白の削除（Fix.needs の全角・半角の直しがある）: 根拠の直しのどれかが直らなければ、空白の削除も直さない（片方向。
      根拠の直しは、空白の削除が直らなくても直す）。理由は、どの直しに連動して直さないかが分かる文。
    ・かっこの全角・半角の直し（Fix.pair がある）: 直すと、組のもう片方のかっこ（そちらの直しを当てはめた後の文字）と全角・半角が
      混ざるなら直さない（「(1）」のような、docx にも PDF にもない形にしない。どちらの側から見ても同じなので双方向）。理由は、
      組のもう片方のどの直しに連動して直さないかが分かる文。
    fixes に入っている直す箇所の組・根拠が対象で、組・根拠のほかの直す箇所は fixes になくてもよい。直す箇所が変わったか。"""
    changed = False
    while True:
        step = False
        for f in fixes:
            if not f.reason and f.pair is not None:
                why = f.pair.mixed(f)
                if why:
                    f.reason = why
                    step = True
        for g in {id(f.group): f.group for f in fixes if f.group is not None}.values():
            bad = next((m for m in g.members if m.reason), None)
            if bad is None:
                continue
            for m in g.members:
                if not m.reason:
                    m.reason = bad.reason
                    step = True
        for f in fixes:
            if not f.reason:
                bad = next((n for n in f.needs if n.reason), None)
                if bad is not None:
                    f.reason = f"{_fix_desc(bad)}を直さないので、連動して直さない（その理由: {bad.reason}）"
                    step = True
        if not step:
            return changed
        changed = True


@dataclass
class DocxFix:
    path: Path                                       # 出版版 PDF で補った docx
    fixes: list = field(default_factory=list)        # Fix（直したもの・直さなかったもの）
    unmatched: list = field(default_factory=list)    # PDF の中に見つからなかった段落
    check: object = None                             # 元の docx と PDF の照合（pdfmatch.PdfCheck）
    texts: dict = field(default_factory=dict)        # 元の docx の段落の文字列（直した段落・違いのある段落・見つからない段落・
    #                                                  照合に使わなかった PDF の文字のある段落。レポート用）
    locations: dict = field(default_factory=dict)    # 元の docx の段落の場所（レポート用）

    @property
    def applied(self) -> list:
        return [f for f in self.fixes if f.applied]

    @property
    def skipped(self) -> list:
        return [f for f in self.fixes if not f.applied]

    @property
    def applied_typeset(self) -> list:
        """PDF に合わせた表記の違い（(1)）。"""
        return [f for f in self.applied if f.typeset]

    @property
    def skipped_typeset(self) -> list:
        """直せなかった表記の違い（(1)。ほかの直す箇所と重なる、内容の違いに続く、直せない文字にかかる、構造が変わるなど。
        要確認にしない）。内容の違い（kind text）は書き込まないので、直したものの一覧はない（fixes を kind で引く）。"""
        return [f for f in self.skipped if f.typeset]


# ---------------------------------------------------------------------------- 直す箇所
def plan_fixes(plan, check) -> list:
    """照合の結果（PdfCheck）から、段落ごとの直す箇所（Fix）の一覧を作る。

    全角・半角（check.width）と PDF にない空白（check.drops）は 1 文字ずつの組版の違い（kind width・space）。違い（check.diffs）は
    pdfmatch.diff_parts で直す単位に分け、組版の違いの文字は kind width・glyph、内容の違いは kind text にする。直せない違い
    （fixable が偽）は分けずに理由付きの 1 つの Fix にし、kind は組版の違いだけのもの（TextDiff.kind typeset）なら width か
    glyph、それ以外は text（決められない違いと、番号・数式・リンクにかかる内容の違い）。

    「PDF に合わせるなら何を変えるか」を返す関数で、内容の違い（kind text）の Fix も理由なしで返す。書き込む前に必ず hold を
    通す（make_fixed_docx。照合のテストは、この戻り値で PDF の形を組み立てられるかを確かめる）。"""
    from .pdfmatch import diff_parts
    fixes = []
    widths = {}      # (段落 ID, 位置) -> 全角・半角の直し
    for src, m in check.width.items():
        text = plan.paras[src].plain()
        for q, c in m.items():
            widths[src, q] = Fix(src, q, q + 1, c, "width", text[q])
            fixes.append(widths[src, q])
    for src, ds in check.drops.items():
        text = plan.paras[src].plain()
        for q in sorted(ds):
            space = Fix(src, q, q + 1, "", "space", text[q])
            fixes.append(space)
            # 空白の削除は、根拠の全角・半角の直しに従わせる（根拠の直しを直さないのに空白だけ消すと、docx にも PDF にもない
            # 文字になる）。根拠の直しは空白の削除に従わせない（空白が残るだけ）。根拠に Word が付ける番号があるときは、番号は
            # docx の文字ではなく、変換のときに必ず PDF に合わせる（pdfdocx は止めない）ので、番号だけで消してよい根拠になり、
            # 全角・半角の直しに従わせない
            basis = check.drop_basis.get(src, {}).get(q, ())
            if any(b[0] == "number" for b in basis):
                continue
            for kind, *at in sorted(b for b in basis if b[0] == "width"):
                if (src, at[0]) in widths:
                    space.needs.append(widths[src, at[0]])
                else:
                    space.reason = space.reason or "根拠の全角・半角の直しがない"
    case_srcs = check.case_srcs
    for d in check.diffs:
        text = plan.paras[d.src].plain()
        old = text[d.start:d.end]
        if not d.fixable:
            kind = _typeset_kind(d.docx, d.pdf) if d.kind == "typeset" else "text"
            fixes.append(Fix(d.src, d.start, d.end, d.pdf, kind, old, reason=d.why or UNFIXABLE_REASON))
            continue
        # 違う部分の中でも、文字ごとに最小限の変更にし、組版の違いと内容の違いを分ける（「58」→「５８９」は「5」「8」の
        # 全角・半角と、「９」の追加）
        first = len(fixes)
        for a, b, new, kind in diff_parts(text, d, d.src in case_srcs):
            fixes.append(Fix(d.src, a, b, new, kind if kind in ("text", "width") else "glyph", text[a:b]))
            if len(fixes) > first + 1:
                link_fixes(fixes[first], fixes[-1])
    order = {src: i for i, src in enumerate(plan.paras)}
    fixes.sort(key=lambda f: (order.get(f.src, len(order)), f.start, f.end))
    # 重なるものは後のものを直さない。1 つの違い（TextDiff）を分けた直す箇所の一部が重なるときは、その違いの直す箇所をすべて
    # 直さない（一部だけを当てはめると、docx にも PDF にもない文字になる。「pp.45－58」を「pp.46-5-58」にするなど）。直さないことに
    # した箇所が増えなくなるまで繰り返す
    overlap = "ほかの直す箇所と重なる"
    while True:
        last = {}
        for f in fixes:
            if f.reason:
                continue
            prev = last.get(f.src)
            if prev is not None and (f.start < prev.end or (f.start == f.end == prev.end and prev.start == prev.end)):
                f.reason = overlap
                continue
            last[f.src] = f
        if not spread_reasons(fixes):
            break
    return fixes


# 直さない理由（hold が付ける）
UNFIXABLE_REASON = "数式・Word が付ける番号・リンクの文字にかかる、または足す位置を決められない"
CONTENT_REASON = "内容の違い（PDF から docx に、内容を足さない・消さない・置き換えない）"
ADJACENT_REASON = "直さない違いに続く表記の違い（一部だけ直すと、docx にも PDF にもない形になる）"
NOSPACE_REASON = ("英文の文と文の間の全角の「，」「．」（PDF ではすぐ後ろに空白があり、docx にはない。半角にすると文の間が空かない形"
                  "〈「night.They」〉になり、空白は docx にない文字なので足さない。全角のまま残す）")
# NOSPACE_REASON で直さない全角・半角の直し: docx の文字 -> PDF の文字。docx のすぐ後ろが空白でない半角の英数字（RE_NOSPACE_NEXT）で、
# PDF ではすぐ後ろに英文の単語の間の空白がある（pdfmatch.PdfCheck.spaced_after）ものだけ（C111）
NOSPACE_PUNCT = {"，": ",", "．": "."}
RE_NOSPACE_NEXT = re.compile(r"[A-Za-z0-9]")
# 一続きの規則: 直さない違いとの間の docx の文字がこれ以下なら、続く表記の直しも直さない
ADJACENT_GAP = 1
# 一続きの規則の、かっこの組: 片方を直さないなら、組のもう片方も直さない（「（2020)」のような、docx にも PDF にもない形にしない）。
# 値は組の種類（全角・半角を問わない。開くかっこの半角で表す: 閉じるかっこは BRACKET_CLOSE の値）。丸かっこ・角かっこ・波かっこ。
# 「＜＞」「<>」は不等号にも使うので組にしない
BRACKETS = {"(": "(", "（": "(", ")": ")", "）": ")", "[": "[", "［": "[", "]": "]", "］": "]",
            "{": "{", "｛": "{", "}": "}", "｝": "}"}
# 組の種類 → 閉じるかっこ（種類で表した）。開くかっこの種類はこの表の鍵
BRACKET_CLOSE = {"(": ")", "[": "]", "{": "}"}
# 閉じるかっこ（種類で表した）→ 開くかっこの種類
CLOSE_KIND = {v: k for k, v in BRACKET_CLOSE.items()}


def hold(fixes, texts=None, spaced=None) -> None:
    """書き込まない直す箇所に理由を付ける（plan_fixes の後、write_fixed_docx の前。make_fixed_docx）。

    (a) 内容の違い（kind text）で理由のないもの → CONTENT_REASON。
    (b) spread_reasons（同じ違いを分けた表記の直しも止まる。FixGroup）。
    (b2) 英文の文の間の全角の「，」「．」（C111）: 段落の文字 texts と spaced（pdfmatch.PdfCheck.spaced_after）があれば、全角の「，」「．」を
        半角に直す kind width の直しで、docx のすぐ後ろが空白でない半角の英数字、PDF ではすぐ後ろに空白があるもの → NOSPACE_REASON
        （全角のまま残す。空白は足さない）。一続きの規則の始まりにはしない。それを根拠にした空白の削除（Fix.needs）は (b2) の後の
        spread_reasons で直さない（片方向）。
    (c) 一続きの規則: 書き込まない kind text の直す箇所（内容の違いと、理由 why のある決められない違い。UNFIXABLE_REASON の
        ものは始まりにしない）と、その組の直す箇所、またはこの規則で止めた直す箇所から、間の docx の文字が ADJACENT_GAP 以下で
        続く表記の直し（kind width・space・glyph）を、連鎖でたどって書き込まない → ADJACENT_REASON。段落の中だけ。
        段落の文字 texts（段落 ID → plain）があれば、止めた直す箇所の範囲にあるかっこ（BRACKETS）の、組のもう片方のかっこの
        表記の直しも止め（ADJACENT_REASON）、そこからも続けてたどる。
    (d) もう一度 spread_reasons（空白の削除の連動と、止めた表記の直しの組）。
    texts があれば、(d) の前に、かっこの全角・半角の直しに組のもう片方のかっこを付ける（Fix.pair。_pair_brackets）。これで、(d) と後の段階
    （書き込みの段階で直せない文字にかかる・構造が変わる、など）で止まったかっこの組のもう片方も、spread_reasons で止まる。"""
    by_src = {}
    for f in fixes:
        by_src.setdefault(f.src, []).append(f)
    for f in fixes:
        if f.kind == "text" and not f.reason:
            f.reason = CONTENT_REASON
    spread_reasons(fixes)
    if texts and spaced:
        for f in fixes:
            if not f.reason and _nospace(f, texts.get(f.src), spaced.get(f.src, ())):
                f.reason = NOSPACE_REASON
        spread_reasons(fixes)

    def start(f):
        if f.kind == "text":
            return bool(f.reason) and f.reason not in (UNFIXABLE_REASON, NOSPACE_REASON)
        return f.reason in (CONTENT_REASON, ADJACENT_REASON)
    for src, fs in by_src.items():
        partner = _bracket_partners(texts[src]) if texts and src in texts else {}
        stops = [f for f in fs if start(f)]
        rest = [f for f in fs if not f.reason and f.typeset]
        while stops and rest:
            pair = {partner[q] for s in stops for q in range(s.start, s.end) if q in partner}
            hit = [g for g in rest if any(_gap(g, s) <= ADJACENT_GAP for s in stops)
                   or any(g.start <= q < g.end for q in pair)]
            for g in hit:
                g.reason = ADJACENT_REASON
            rest = [g for g in rest if not g.reason]
            stops = hit
        if src in (texts or {}):
            _pair_brackets(fs, texts[src])
    spread_reasons(fixes)


def _nospace(f: Fix, text, spaced) -> bool:
    """f が、英文の文の間の全角の「，」「．」を半角にする直し（hold の (b2)。NOSPACE_REASON）か。text は段落の文字（plain）、
    spaced は PDF ではすぐ後ろに空白がある全角・半角の文字の位置（pdfmatch.PdfCheck.spaced_after の段落の分）。"""
    return (text is not None and f.kind == "width" and f.end - f.start == 1 and NOSPACE_PUNCT.get(f.old) == f.new
            and f.start in spaced and bool(RE_NOSPACE_NEXT.fullmatch(text[f.end:f.end + 1])))


def _bracket_partners(text: str) -> dict:
    """段落の文字のかっこの組（全角・半角を問わない。入れ子は内側から）: 位置 → 組のもう片方の位置。組にならないかっこは入れない。

    丸かっこと角かっこは 1 つのスタックで組にする（0.37.0 と同じ）: 閉じるかっこが来て、一番上の開くかっこと種類が違うときは、
    その閉じるかっこを組にしない（「(例 [1) a, 2) b])」の「1)」「2)」のような、開く側のない閉じるかっこ。外側の「(」は最後の「)」と
    組になる）。ただし、一番上の開くかっこが後ろで閉じられないもの（_closes_later が偽。「(例 [ 1, 2 ) と [ 3 ]」の最初の「[」）なら、
    閉じていない開くかっことして捨てて、一つ下で続ける（外側の「(」「)」が組になる。外部レビュー 2 回目の S1）。
    波かっこは、波かっこだけの別のスタックで組にする（丸・角かっこの組には関わらない。0.37.0 は波かっこを組にしなかったので、
    丸・角かっこの組を 0.37.0 から変えない。「(整数 { の組)」「(a{b)c}」の「(」「)」は組のまま）。
    同じ種類のかっこの中の、開く側のない閉じるかっこ（「(例 1) a, 2) b)」）は見分けられない（「(」は最初の「)」と組になる。0.37.0 から同じ）。"""
    kinds = [BRACKETS.get(c) for c in text]
    out = {}
    for group in (("(", "["), ("{",)):
        stack = []
        for i, k in enumerate(kinds):
            if k in group:
                stack.append((i, k))
            elif CLOSE_KIND.get(k) in group:
                while stack and BRACKET_CLOSE[stack[-1][1]] != k and not _closes_later(kinds, i + 1, stack[-1][1]):
                    stack.pop()
                if stack and BRACKET_CLOSE[stack[-1][1]] == k:
                    o, _ = stack.pop()
                    out[o], out[i] = i, o
    return out


def _closes_later(kinds, start: int, kind: str) -> bool:
    """種類 kind の開くかっこが 1 つ開いているとして、位置 start から後ろに、それを閉じる閉じるかっこがあるか（後ろで開く同じ種類の
    開くかっこは、それ自身の閉じるかっこを先に使う。「{ 1, 2 ) と { 3 }」の最初の「{」は、後ろの「}」が 2 つ目の「{」のものなので偽）。"""
    depth = 1
    for k in kinds[start:]:
        if k == kind:
            depth += 1
        elif k == BRACKET_CLOSE[kind]:
            depth -= 1
            if depth == 0:
                return True
    return False


FULL_BRACKETS = frozenset("（）［］｛｝")


def _bracket_swap(f: Fix) -> bool:
    """1 文字のかっこを、同じ種類のかっこ（全角・半角の違いだけ）に直す直す箇所か。"""
    return (f.end - f.start == 1 and len(f.old) == 1 and len(f.new) == 1 and f.old in BRACKETS
            and BRACKETS.get(f.new) == BRACKETS[f.old])


@dataclass(eq=False)
class _BracketPair:
    """かっこの全角・半角の直し（Fix.pair）の、組のもう片方のかっこ: 位置 at、docx の文字 char、その位置にかかる直す箇所 cover。"""
    at: int
    char: str
    cover: list = field(default_factory=list)

    def mixed(self, f: Fix) -> str:
        """f を直すと組の全角・半角が混ざるなら、直さない理由（混ざらない・決められないなら空）。"""
        live = [g for g in self.cover if not g.reason]
        if not live:
            other = self.char
        elif len(live) == 1 and _bracket_swap(live[0]):
            other = live[0].new
        else:                   # もう片方をかっこ以外に直す: 組の形を決められないので、この規則では止めない
            return ""
        if (f.new in FULL_BRACKETS) == (other in FULL_BRACKETS):
            return ""
        held = next((g for g in self.cover if g.reason), None)
        if held is not None:
            desc = _fix_desc(held) if held.kind in ("width", "space") else f"直し「{held.old}」→「{held.new}」"
            return (f"かっこの組のもう片方の{desc}を直さないので、連動して直さない（片方だけ直すと、docx にも PDF にも"
                    f"ない形になる。その理由: {held.reason}）")
        return (f"かっこの組のもう片方「{self.char}」に直す箇所がない（リンクの中の文字など）ので、直さない（片方だけ直すと、"
                "docx にも PDF にもない形になる）")


def _pair_brackets(fs, text: str) -> None:
    """1 つの段落の直す箇所のうち、かっこの全角・半角の直しに、組のもう片方のかっこ（_BracketPair）を付ける。docx で組の全角・半角が
    もともと混ざっているもの（「(1）」）には付けない（直せば混ざらなくなることがある）。"""
    partner = _bracket_partners(text)
    for f in fs:
        if not _bracket_swap(f) or f.start not in partner:
            continue
        p = partner[f.start]
        if (text[f.start] in FULL_BRACKETS) != (text[p] in FULL_BRACKETS):
            continue
        f.pair = _BracketPair(p, text[p], [g for g in fs if g is not f and g.start <= p < g.end])


def check_held(fixes) -> None:
    """内容の違いを書き込まない守り（write_fixed_docx の入口）: 理由（reason）のない kind text の直す箇所があれば ValueError。
    plan_fixes は内容の違いの Fix も理由なしで返すので、hold を通さずに write_fixed_docx を呼ぶ新しいコードが内容の違いを
    書き込まないようにする。"""
    bad = [f for f in fixes if f.kind == "text" and not f.reason]
    if bad:
        raise ValueError(f"理由のない内容の違いの直す箇所があります（hold を通してください）: {bad[0].src} "
                         f"「{bad[0].old}」→「{bad[0].new}」")


def _gap(a: Fix, b: Fix) -> int:
    """2 つの直す箇所の間の docx の文字の数（重なれば 0 以下）。"""
    return b.start - a.end if (a.start, a.end) <= (b.start, b.end) else a.start - b.end


def _typeset_kind(docx: str, pdf: str) -> str:
    """組版の違いだけの文字列の対（pdfmatch.typeset_same が真のもの）の Fix の kind: 違う文字がすべて全角・半角なら width、
    それ以外（ダッシュ・引用符・大文字・小文字を含む）は glyph。"""
    from .pdfmatch import is_width_pair
    d = [c for c in docx if not c.isspace()]
    q = [c for c in pdf if not c.isspace()]
    return "width" if all(x == y or is_width_pair(x, y) for x, y in zip(d, q)) else "glyph"


def expected_text(text: str, fixes) -> str:
    """段落の文字列に直す箇所を当てはめた結果（書き込んだ docx を読み直して確かめるため）。"""
    out, pos = [], 0
    for f in sorted(fixes, key=lambda f: (f.start, f.end)):
        out.append(text[pos:f.start])
        out.append(f.new)
        pos = f.end
    out.append(text[pos:])
    return "".join(out)


# ---------------------------------------------------------------------------- 元の docx の段落の文字
class _Complex(Exception):
    """段落の文字列を読み取りと同じに組み立てられない（ルビを含むなど）。"""


def raw_paragraph_ids(root, prefix: str) -> dict:
    """前処理していない XML の段落 ID → w:p。読み取り（mc:AlternateContent を mc:Choice に置き換えてから数える）と同じ番号。"""
    out = {}
    i = 0
    for p in root.iter(w("p")):
        if _dropped_by_preprocess(p):
            continue
        i += 1
        out[f"{prefix}{i}"] = p
    return out


def _dropped_by_preprocess(el) -> bool:
    """前処理（ooxml.preprocess）が捨てる側（mc:AlternateContent の採らない Choice・Fallback）の中にあるか。"""
    for a in el.iterancestors():
        if a.tag in (f"{{{MC_NS}}}Choice", f"{{{MC_NS}}}Fallback"):
            ac = a.getparent()
            if ac is not None and ac.tag == f"{{{MC_NS}}}AlternateContent" and choose_alternate(ac) is not a:
                return True
    return False


def _chains(root, prefix: str) -> dict:
    """段落記号の削除でつなぐ段落の連鎖 {最初の段落 ID: [段落 ID, …]}（読み取り・検証と同じ規則 ooxml.joined_paragraphs）。

    root は前処理していない XML。どの段落をつなぐかは前処理した木で決める（mc:Fallback の中の写しをつながない）ので、写しを
    前処理して段落 ID で引く（ID の番号は raw_paragraph_ids と同じ）。部品に段落記号の削除がひとつもなければ写しを作らない。
    """
    if not any(paragraph_mark_deleted(p) for p in root.iter(w("p"))):
        return {}
    pre = preprocess(copy.deepcopy(root))
    ids = paragraph_ids(pre, prefix)
    return {ids[c[0]]: [ids[q] for q in c] for c in joined_paragraphs(pre).values()}


def paragraph_units(p, hidden=None) -> list:
    """段落の文字を [(文字, w:t 要素または None, w:t の中の位置)] で返す。読み取り（docx_reader）の文字ポリシーと同じ。

    直せるのは w:t の文字と、Word の改行なしハイフン（w:noBreakHyphen。要素そのものと位置 0。要素ごと変更履歴の削除にして、
    PDF の「-」を足せる）だけ（タブ・改行・記号・フィールドの結果・数式・脚注番号などは None）。
    図形（w:drawing・w:pict・w:object）は、読み取りと同じ数の画像のアトム（OBJ。直せない単位）を置き、中は読まない（テキストボックスの
    文字は別の段落。数の規則は ooxml.graphic_atoms で読み取りと共有する。C048）。ランの中の mc:AlternateContent は、前処理と同じく
    採る側の中身を読む（w:t の文字は直せない単位、図形は同じく OBJ）。ルビを含む段落と、段落の直下の mc:AlternateContent は _Complex。
    hidden は隠し文字の判定（ooxml.HiddenRule。None なら NO_RULE）。段落記号の削除によるつながりは見ない（write_fixed_docx が、連鎖の段落ごとの単位を連結する）。
    """
    out = []
    fields = []          # [code_mode]
    rule = hidden or NO_RULE
    ps = rule.para_state(p)

    def in_code():
        return any(fields)

    def walk(el, deleted, hidden):
        for ch in el:
            tag = ch.tag
            if not isinstance(tag, str):
                continue
            if tag in (w("pPr"), w("rPr"), w("bookmarkStart"), w("bookmarkEnd"), w("proofErr"), w("commentRangeStart"),
                       w("commentRangeEnd"), w("permStart"), w("permEnd")):
                continue
            if tag in (w("del"), w("moveFrom")):
                walk(ch, True, hidden)
            elif tag in (w("hyperlink"), w("fldSimple")):
                walk(ch, deleted, hidden)
            elif tag == w("r"):
                run(ch, deleted, hidden or rule.run_hidden(ch, ps))
            elif tag in (f"{{{M_NS}}}oMathPara", f"{{{M_NS}}}oMath"):
                if not (deleted or hidden or in_code()):
                    out.append((OBJ, None, 0))
            elif tag == f"{{{MC_NS}}}AlternateContent":
                raise _Complex
            elif tag == w("sdt"):
                content = ch.find(w("sdtContent"))
                if content is not None:
                    walk(content, deleted, hidden)
            elif tag in (w("ins"), w("moveTo"), w("smartTag"), w("customXml"), w("sdtContent"), w("dir"), w("bdo")):
                walk(ch, deleted, hidden)
            elif len(ch):
                walk(ch, deleted, hidden)

    def run_children(r):
        """ランの子。mc:AlternateContent は、前処理（ooxml.preprocess）が採る側の子に置き換える（採らない側は読まない）。
        採る側の子は (子, True) で返す（Fallback の w:t だけを直しても、Word は採らない Choice〈記号の挿入の w16se:symEx など〉
        を表示するので、直さない）。"""
        for ch in r:
            if ch.tag == f"{{{MC_NS}}}AlternateContent":
                chosen = choose_alternate(ch)
                for c in (chosen if chosen is not None else ()):
                    yield c, True
            else:
                yield ch, False

    def run(r, deleted, hidden):
        for ch, alt in run_children(r):
            tag = ch.tag
            if not isinstance(tag, str):
                continue
            if tag == w("fldChar"):
                t = ch.get(w("fldCharType"))
                if t == "begin":
                    fields.append(True)
                elif t == "separate" and fields:
                    fields[-1] = False
                elif t == "end" and fields:
                    fields.pop()
                continue
            if tag in (w("instrText"), w("rPr"), w("delText"), w("lastRenderedPageBreak")):
                continue
            if tag in (w("footnoteReference"), w("endnoteReference")):
                if not (deleted or in_code()):
                    out.append((OBJ, None, 0))
                continue
            if tag in (w("footnoteRef"), w("endnoteRef")):
                out.append((OBJ, None, 0))
                continue
            if tag in (w("drawing"), w("pict"), w("object")):
                # 図形は、読み取り（docx_reader._graphic）と同じ数の画像のアトムを置く（規則は ooxml.graphic_atoms で共有する。
                # C048）。削除の変更履歴の中・フィールドのコードの中・隠し文字の図形は、読み取りもアトムにしない。中には入らない
                # （テキストボックスの段落は別の w:p。ランの中の mc:AlternateContent の採る側の図形も同じ）
                if not (deleted or in_code() or hidden):
                    out.extend((OBJ, None, 0) for _ in graphic_atoms(ch))
                continue
            if alt and tag == w("ruby"):
                continue        # 代替内容の中のルビ（今までどおり読まない）
            if tag == w("ruby"):
                raise _Complex
            if deleted or in_code() or hidden:
                continue
            # フィールドの結果の文字と、mc:AlternateContent の中の文字は直さない
            # （フィールドを更新すると戻る。代替内容は、採る側を直しても Word が別の側を表示するかもしれない）
            editable = not fields and not alt
            if tag == w("t"):
                # 記号フォントのランの w:t の私用領域の文字は、Unicode にした文字を読む（ooxml.w_t_text。1 文字が 1 文字なので、
                # 文字の位置 k は元の w:t のまま）。この文字を直す直しは、直した文字で置き換える
                out.extend((c, ch if editable else None, k) for k, c in enumerate(w_t_text(ch, r)[0]))
            elif tag in (w("tab"), w("ptab")):
                out.append(("\t", None, 0))
            elif tag == w("br"):
                if ch.get(w("type")) in BR_TEXT_TYPES:
                    out.append(("\n", None, 0))
            elif tag == w("cr"):
                out.append(("\n", None, 0))
            elif tag == w("noBreakHyphen"):
                # Word の改行なしハイフン（U+2011 として読む）。PDF の「-」に合わせて直せるように、要素ごと消せるようにする
                # （ダッシュ・ハイフンの仲間を PDF に合わせる。pdfmatch.HYPHENS）
                out.append(("‑", ch if editable else None, 0))
            elif tag == w("softHyphen"):
                out.append(("­", None, 0))
            elif tag == w("sym"):
                out.append((sym_char(ch), None, 0))

    walk(p, False, False)
    return out


# ---------------------------------------------------------------------------- 書き込み
class _Writer:
    def __init__(self, date: str):
        self.date = date
        self.next_id = 90000

    def mark(self, tag):
        el = etree.Element(w(tag))
        el.set(w("id"), str(self.next_id))
        el.set(w("author"), AUTHOR)
        el.set(w("date"), self.date)
        self.next_id += 1
        return el

    @staticmethod
    def run(r, rpr, child=None):
        nr = etree.Element(w("r"), dict(r.attrib))
        if rpr is not None:
            nr.append(copy.deepcopy(rpr))
        if child is not None:
            nr.append(child)
        return nr

    def text_node(self, r, rpr, kind, text):
        t = etree.Element(w("delText") if kind == "del" else w("t"))
        t.set(XML_SPACE, "preserve")
        t.text = text
        nr = self.run(r, rpr, t)
        if kind == "keep":
            return nr
        m = self.mark("del" if kind == "del" else "ins")
        m.append(nr)
        return m

    def rebuild(self, r, plans):
        """ラン r を、直す w:t ごとに、そのままの文字・削除・挿入のランに分けて置き換える。直す Word の改行なしハイフン
        （w:noBreakHyphen。paragraph_units）は、要素ごと、そのまま残すか削除のランにし、その前後に挿入のランを置く。"""
        rpr = r.find(w("rPr"))
        parent = r.getparent()
        idx = parent.index(r)
        new = []
        for ch in list(r):
            if ch is rpr:
                continue
            if ch in plans and ch.tag != w("t"):
                dels, ins_after = plans[ch]
                new += [self.text_node(r, rpr, "ins", s) for s in ins_after.get(-1, [])]
                if 0 in dels:
                    m = self.mark("del")
                    m.append(self.run(r, rpr, ch))
                    new.append(m)
                else:
                    new.append(self.run(r, rpr, ch))
                new += [self.text_node(r, rpr, "ins", s) for s in ins_after.get(0, [])]
            elif ch in plans:
                dels, ins_after = plans[ch]
                segs = []

                def add(kind, s):
                    if not s:
                        return
                    if segs and segs[-1][0] == kind:
                        segs[-1][1] += s
                    else:
                        segs.append([kind, s])
                for s in ins_after.get(-1, []):
                    add("ins", s)
                for k, c in enumerate(ch.text or ""):
                    add("del" if k in dels else "keep", c)
                    for s in ins_after.get(k, []):
                        add("ins", s)
                new += [self.text_node(r, rpr, kind, s) for kind, s in segs]
            else:
                new.append(self.run(r, rpr, ch))
        parent.remove(r)
        for k, n in enumerate(new):
            parent.insert(idx + k, n)


def _apply_paragraph(units, fixes, writer: _Writer):
    """段落に直す箇所を書き込む。直せないものは Fix.reason に理由を書く。

    先に、直せない直す箇所をすべて決め、組（Fix.group）の一部が直せなければ組の全部を、根拠の全角・半角の直し（Fix.needs）が
    直せなければ空白の削除を、直さないことにしてから、直せるものを書き込む（一部だけ書き込んだ後では取り消せない）。
    組と根拠は 1 つの段落の中だけなので、make_fixed_docx が回ごとに広げ直す必要はない（write_fixed_docx が先に広げ、ここでも
    直せない理由を足してから広げる）。"""
    plans = {}           # w:t -> (削除する位置, {この位置の後に足す: [文字列]})

    def plan_of(t):
        return plans.setdefault(t, (set(), {}))

    def ok_run(t):
        r = t.getparent()
        return r is not None and r.tag == w("r") and r.getparent() is not None and r.getparent().tag in RUN_PARENTS

    sites = {}           # id(Fix) -> 足す位置の (w:t, 位置)
    for f in fixes:
        if f.reason:
            continue
        rng = units[f.start:f.end]
        if any(t is None or not ok_run(t) for _, t, _ in rng):
            f.reason = "直せない文字（タブ・記号・フィールドの結果、既存の変更履歴やリンクの中の文字など）にかかる"
        elif f.start == f.end:          # 足す: 直前の文字の後（なければ直後の文字の前）
            if f.start > 0 and units[f.start - 1][1] is not None and ok_run(units[f.start - 1][1]):
                _, t, k = units[f.start - 1]
            elif f.start < len(units) and units[f.start][1] is not None and ok_run(units[f.start][1]):
                _, t, k = units[f.start]
                k -= 1
            else:
                f.reason = "文字を足す位置の前後が直せない文字"
                continue
            sites[id(f)] = (t, k)
    spread_reasons(fixes)
    for f in fixes:
        if f.reason:
            continue
        if f.start == f.end:
            t, k = sites[id(f)]
            plan_of(t)[1].setdefault(k, []).append(f.new)
        else:
            rng = units[f.start:f.end]
            for _, t, k in rng:
                plan_of(t)[0].add(k)
            if f.new:
                _, t, k = rng[-1]
                plan_of(t)[1].setdefault(k, []).append(f.new)
        f.applied = True
    runs = {}
    for t, pl in plans.items():
        runs.setdefault(t.getparent(), {})[t] = pl
    for r, pl in runs.items():
        writer.rebuild(r, pl)


def same_file(a, b) -> bool:
    """2 つのパスが同じファイルか（パスの解決後の一致か、どちらも存在して同じファイルか）。"""
    a, b = Path(a), Path(b)
    if a.resolve() == b.resolve():
        return True
    try:
        return a.exists() and b.exists() and a.samefile(b)
    except OSError:
        return False


def write_fixed_docx(src_path, dst_path, plan, fixes, skip=frozenset(), date=None):
    """直す箇所を変更履歴として書き込んだ docx を dst_path に作る。skip の段落は直さない。

    理由（reason）のない内容の違い（kind text）の直す箇所があれば ValueError（hold を通してから呼ぶ）。

    段落記号の削除でつながる段落（_chains）は、連鎖の最初の段落の ID で、連鎖の w:p ごとの単位（paragraph_units）を連結して
    直す。連鎖の後ろの段落の ID には直す箇所がない（読み取りの段落がない）。
    """
    if same_file(src_path, dst_path):
        # 入力を読みながら同じファイルを書き出すと、入力が壊れる（書き込む前に止める。呼び出し側が別の名前にする）
        raise ValueError(f"入力の docx と、補った docx の書き出し先が同じファイルです: {dst_path}")
    check_held(fixes)
    date = date or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    writer = _Writer(date)
    # 呼び出し側が先に直さないことにした直す箇所に連動するものも、先に直さないことにする。_apply_paragraph も広げるが、skip の段落と
    # 段落の文字列を組み立てられない段落は、_apply_paragraph の前に「書き込んだ後に読み直した…」などの理由を付けて飛ばすので、
    # その前に広げないと、連動の理由（どの直しに連動して直さないか）が出ない
    spread_reasons(fixes)
    by_src = {}
    for f in fixes:
        by_src.setdefault(f.src, []).append(f)
    with zipfile.ZipFile(src_path) as zin:
        roots = {part: parse_xml(zin.read(part)) for part in PARTS if part in zin.namelist()}
        ids_used = [int(v) for root in roots.values() for el in root.iter() if isinstance(el.tag, str)
                    for v in [el.get(w("id"))] if v and v.lstrip("-").isdigit()]
        writer.next_id = max(ids_used + [0]) + 1000
        # 隠し文字の判定は読み取りと同じ規則（styles.xml は読み取りと同じく前処理してから使う）
        rule = (HiddenRule(preprocess(parse_xml(zin.read("word/styles.xml"))))
                if "word/styles.xml" in zin.namelist() else NO_RULE)
        for part, root in roots.items():
            raw = raw_paragraph_ids(root, PARTS[part])
            chains = _chains(root, PARTS[part])
            later = {s for c in chains.values() for s in c[1:]}
            for src in raw:
                if src in later:        # 連鎖の後ろの段落は、最初の段落といっしょに直す
                    continue
                pf = [f for f in by_src.get(src, []) if not f.reason]
                if not pf:
                    continue
                if src in skip:
                    for f in pf:
                        f.reason = "書き込んだ後に読み直した文字列が合わなかった"
                    continue
                try:
                    units = [u for s in chains.get(src, [src]) for u in paragraph_units(raw[s], rule)]
                except _Complex:
                    units = None
                if units is None or "".join(c for c, _, _ in units) != plan.paras[src].plain():
                    for f in pf:
                        f.reason = "段落の文字列を読み取りと同じに組み立てられない（ルビを含む段落など）"
                    continue
                _apply_paragraph(units, pf, writer)
        with zipfile.ZipFile(dst_path, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename in roots:
                    zout.writestr(item, etree.tostring(roots[item.filename], xml_declaration=True, encoding="UTF-8",
                                                       standalone=True))
                else:
                    zout.writestr(item, zin.read(item.filename))


def _mechanical(path, journal):
    """docx を読み取り、構造を決め、リンクを付ける（変換の機械処理と同じ）。(読み取った文書, 構造)。"""
    from .docx_reader import read_docx
    from .linker import link
    from .structure import classify
    doc = read_docx(path)
    texts = {p.src: p.plain() for p in _all_paragraphs(doc)}       # 構造を決める前の段落の文字列
    plan = classify(doc, journal)
    link(plan, journal.ref_doi)
    return texts, plan


def _all_paragraphs(doc):
    """本文（表のセル・テキストボックスを含む）と、Word の脚注・文末脚注のすべての段落（直した docx の読み直しの確かめに使う）。"""
    yield from doc.all_paragraphs()
    for notes in (doc.footnotes, doc.endnotes):
        for paras in notes.values():
            yield from paras


def make_fixed_docx(docx_path, pdf_path, out_path, journal) -> DocxFix:
    """route pdf の最初の段階: docx と PDF を照合し、表記の違い（(1)）を出版版 PDF に合わせた docx（変更履歴つき）を out_path に
    作る。内容の違いは書き込まない（hold）。

    書き込んだ後に読み直して、(1) 直した段落の文字列が直した結果と一致するか、(2) 段落の役割・領域（英文要旨・資料など）・
    リンク（注・引用文献・図表など）・注の区切り・著者と所属の数・氏名の姓と名の分け方が元の docx と同じに決まるかを確かめる。
    合わない箇所は直さずに作り直す。
    """
    from .builder import word_note_marks
    from .pdfmatch import check_pdf
    _, plan = _mechanical(docx_path, journal)
    # Word の脚注番号も照合に入れる（番号の後の docx の空白で PDF にないものを消すため。番号そのものは変換のときに合わせる）
    marks = {wid: m for wid, (_, m) in word_note_marks(plan, journal).items()}
    check = check_pdf(plan, pdf_path, marks)
    out_path = Path(out_path)
    fix = DocxFix(path=out_path, check=check, unmatched=list(check.unmatched))
    if not check.ok:            # PDF の文字を読めない: docx は作らない（呼び出し側が元の docx を変換する）
        return fix
    if check.verdict == "wrong":    # 別の論文の PDF（pdfmatch.paper_verdict）: docx は作らない（呼び出し側が WrongPaperError で中止する）
        return fix
    fix.fixes = plan_fixes(plan, check)
    # 内容の違いと、それに続く表記の直しは書き込まない（理由は 8 回の作り直しでも保つ）
    hold(fix.fixes, {s: plan.paras[s].plain() for s in {f.src for f in fix.fixes}}, check.spaced_after)
    for s in {f.src for f in fix.fixes} | {d.src for d in check.diffs} | set(fix.unmatched) | {src for src, _ in check.ignored_lines}:
        fix.texts[s] = plan.paras[s].plain()
        fix.locations[s] = plan.locations.get(s, "")
    reasons = {id(f): f.reason for f in fix.fixes}      # 照合の段階で直さないと決めたもの
    original = _structure(plan)
    targets = {r.rid: [r.para.src] for r in plan.refs} | {fn.fid: [q.src for q in fn.paras] for fn in plan.fns}
    skip = set()                                         # 読み直した文字列が合わなかった段落
    keep = {}                                            # 構造が変わるので直さない範囲: src -> {(開始, 終了) または None（段落全体）: 理由}
    final = False
    for attempt in range(8):
        final = final or attempt == 7
        for f in fix.fixes:
            f.applied, f.reason = False, reasons[id(f)]
            if not f.reason:
                f.reason = _kept(f, keep) or (STRUCTURE_REASON if final else "")   # 確かめきれなかった: 何も直さない
        write_fixed_docx(docx_path, out_path, plan, fix.fixes, skip)
        if final:
            break
        texts, fixed = _mechanical(out_path, journal)
        bad = _verify(texts, plan, fix.fixes)
        if bad:
            skip |= bad          # 読み直した文字列が合わない段落は直さずに作り直す
            continue
        lost = _lost(original, _structure(fixed))
        if not lost:
            break
        final = not _protect(keep, lost, targets)
    return fix


STRUCTURE_REASON = "直すと、段落の役割やリンク（引用文献・図表など）が元の docx と同じに決まらなくなる"
NOTE_REASON = "注の番号（直すと注を認識できなくなるので、すべての注で docx のままにする）"


def _protect(keep, lost, targets) -> bool:
    """崩れたものにかかる変更を直さないことにする。守る範囲が広がったか（広がらなければ、これ以上は確かめられない）。

    崩れたリンクごとに、1 回目はリンクの文字の範囲、それでも崩れればリンク先の段落（引用文献・注。リンク先の文字が変わって
    照合できなくなった場合）、それでも崩れればリンクのある段落全体を直さない。
    """
    before = {src: dict(v) for src, v in keep.items()}
    for src, rng, why, rid in lost:
        got = keep.setdefault(src, {})
        if None in got:
            continue
        if rng is not None and rng not in got:
            got[rng] = why
        elif any(None not in keep.get(t, {}) for t in targets.get(rid, ())):
            for t in targets[rid]:
                keep[t] = {None: STRUCTURE_REASON}
        else:
            keep[src] = {None: STRUCTURE_REASON}
    return keep != before


def _kept(f, keep) -> str:
    """直さない範囲にかかっていれば、その理由。"""
    for rng, why in keep.get(f.src, {}).items():
        if rng is None or (f.start < rng[1] and rng[0] < max(f.end, f.start + 1)):
            return why
    return ""


def _structure(plan) -> tuple:
    """段落ごとの（役割, 領域）とリンクの並び {src: ((役割, 領域), [(リンク, 開始, 終了)])}、注 {fid: (番号, 段落, 注の節の表の
    形〈(k, キャプションの段落 ID)。FnNode.tables〉)}、注の番号の範囲、著者と所属（_people）。

    領域（plan.region）も比べるのは、英文要旨・資料の段落は役割が空のままなので、役割だけでは、直すと英文要旨と資料の境が
    動くこと（英文要旨の「資料-1 …」を PDF の「資料－1 …」に直すと、資料の見出しになるなど）を見つけられないため。
    著者と所属を比べるのは、英文の著者名・所属も照合して直す（大文字・小文字・全角・半角・空白）ので、直すと著者の数や
    氏名の姓と名の分け方が変わること（「SHIKEN Shiro」を「Shiken Shiro」にすると、姓が後ろの語になる、姓と名の間の空白を
    消すなど）を見つけるため。
    """
    paras = {}
    for src, p in plan.paras.items():
        links, pos = [], 0
        for a in p.atoms:
            n = len(a.text) if a.kind == "text" else 1
            if a.link is not None:
                links.append(((a.link.kind, tuple(sorted(a.link.attrs.items()))), pos, pos + n))
            pos += n
        paras[src] = ((p.role, plan.region.get(src, "")), links)
    fns = {fn.fid: (fn.number, tuple(q.src for q in fn.paras),
                    tuple((k, t.caption.src if t.caption is not None else "") for k, t in fn.tables)) for fn in plan.fns}
    marks = [(fn.paras[0].src, tuple(fn.mark_range), fn.fid) for fn in plan.fns if fn.paras and fn.mark_range]
    return paras, fns, marks, _people(plan)


def _people(plan) -> tuple:
    """著者と所属の形: (著者ごとの (和文の氏名の段落, 英文の氏名の段落, 所属の ID の並び), 所属ごとの (和文の段落, 英文の段落,
    ID), 氏名の段落 -> 姓と名の分け方〈_name_shape〉)。"""
    def src(p):
        return p.src if p is not None else ""
    authors = tuple((src(a.name_ja), src(a.name_en), tuple(f.aid for f in a.affs)) for a in plan.authors)
    affs = tuple((src(f.ja), src(f.en), f.aid) for f in plan.affs)
    shapes = {}
    for a in plan.authors:
        for style, p, split in (("eastern", a.name_ja, a.split_ja), ("western", a.name_en, a.split_en)):
            if p is not None:
                shapes[p.src] = _name_shape(p.plain(), style, split)
    return authors, affs, shapes


def _name_shape(text: str, style: str, split) -> tuple:
    """氏名の姓と名の分け方（builder.person_name と同じ規則で、位置ではなく形で表す）: 分けないなら ()、AI の指定の位置で
    分けるなら ("split",)、和文の氏名は ("eastern", 分け方, 姓の字数, 語の数)（分け方は builder.split_eastern の how）、英文の
    氏名は ("western", 語の数, 姓の語の番号)。直した文字で分け方が変わったか（大文字の語の位置・空白の数と長さ）を比べるため。

    和文の氏名の境目の推定のうち、論文の中の表記からの推定（how が context）は氏名の段落の外の文字で決まり、氏名の段落を
    直さないことでは守れないので、論文の文字を渡さずに比べる（字数からの推定と同じ形になる。変換では論文の文字も使う）。"""
    n = len(text)
    core_s = n - len(text.lstrip(" \u3000\t"))
    core_e = len(text.rstrip(" \u3000\t"))
    if split is not None and core_s < split < core_e:
        return ("split",)
    core = text[core_s:core_e]
    toks = re.findall(r"[^ \u3000\t]+", core)
    if len(toks) < 2:
        return ()
    if style == "eastern":
        from .builder import split_eastern
        sp = split_eastern(text)
        return ("eastern", sp.how, len(sp.surname), len(toks))
    caps = [k for k, t in enumerate(toks) if re.fullmatch(r"[A-ZÀ-Ý][A-ZÀ-Ý'’\-]+", t)]
    k = caps[0] if len(caps) == 1 and caps[0] in (0, len(toks) - 1) else len(toks) - 1
    return ("western", len(toks), k)


def _lost(original, fixed) -> list:
    """直した docx で、元の docx と同じに決まらなくなったもの [(src, (開始, 終了) または None, 理由, リンク先)]（範囲は元の段落の上）。

    注の番号（本文の注へのリンクと、注の一覧の先頭の番号）は、どれか 1 つでも守るときは、すべての注で守る（そろえるため）。
    """
    (paras0, fns0, marks0, people0), (paras1, fns1, _, people1) = original, fixed
    out, notes = [], False
    if people0 != people1:
        # 著者・所属の数か、氏名の姓と名の分け方が変わった: 著者名・所属の段落のうち、形が変わったものを直さない（数や
        # 対応が変わったときは、著者名・所属の段落をすべて直さない）
        if people0[:2] != people1[:2]:
            srcs = {x for a in people0[0] for x in a[:2]} | {x for f in people0[1] for x in f[:2]}
        else:
            srcs = {x for x, v in people0[2].items() if people1[2].get(x) != v}
        out += [(x, None, STRUCTURE_REASON, "") for x in sorted(srcs) if x]
    for src, (role, links) in paras0.items():
        got = paras1.get(src)
        if got is None or got[0] != role:
            out.append((src, None, STRUCTURE_REASON, ""))
            continue
        keys0, keys1 = [k for k, _, _ in links], [k for k, _, _ in got[1]]
        if keys0 == keys1:
            continue
        for tag, i1, i2, _, _ in difflib.SequenceMatcher(None, keys0, keys1, autojunk=False).get_opcodes():
            if tag in ("delete", "replace"):
                for k, a, b in links[i1:i2]:
                    fn = dict(k[1]).get("ref-type") == "fn"
                    out.append((src, (a, b), NOTE_REASON if fn else STRUCTURE_REASON, dict(k[1]).get("rid", "")))
                    notes |= fn
    if any(fns1.get(fid) != v for fid, v in fns0.items()):
        notes = True
    if notes:
        for src, (_, links) in paras0.items():
            out += [(src, (a, b), NOTE_REASON, dict(k[1])["rid"]) for k, a, b in links if dict(k[1]).get("ref-type") == "fn"]
        out += [(src, rng, NOTE_REASON, fid) for src, rng, fid in marks0]
    return list(dict.fromkeys(out))


def _verify(texts, plan, fixes) -> set:
    """直した docx を読み直した段落の文字列が、直した結果と同じかを確かめる。合わない段落の ID を返す。"""
    bad = set()
    by_src = {}
    for f in fixes:
        if f.applied:
            by_src.setdefault(f.src, []).append(f)
    for src, fs in by_src.items():
        if texts.get(src) != expected_text(plan.paras[src].plain(), fs):
            bad.add(src)
    return bad


def tracked_counts(path) -> tuple:
    """docx の中の、このツールが書き込んだ変更履歴（挿入, 削除）の数（元の docx にあった変更履歴は数えない）。"""
    ins = dels = 0
    with zipfile.ZipFile(path) as z:
        for part in PARTS:
            if part in z.namelist():
                for el in parse_xml(z.read(part)).iter(w("ins"), w("del")):
                    if el.get(w("author")) == AUTHOR:
                        if el.tag == w("ins"):
                            ins += 1
                        else:
                            dels += 1
    return ins, dels
