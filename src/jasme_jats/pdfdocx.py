"""ルート2（docx から作り、出版版 PDF で補う）: 出版版 PDF で補った docx（Word の変更履歴つき）を作る。

Word の文字が正で、出版版 PDF（印刷所の校正を経たもの）からは著者校正の直しを補う。docx の段落と PDF の照合（pdfmatch.py）の
結果から、段落ごとの直す箇所を決め、元の docx の XML（前処理しないもの）のランを分けて、削除（w:del）と挿入（w:ins）の変更履歴
として書き込む（作成者名は AUTHOR の 1 つ）。書式（太字・斜体・上付きなど）は、直す文字のランの書式をそのまま使う。

  ・直すもの（組版の違い。(A)。Fix の kind width・space・glyph）: 英数字・記号の全角・半角と、その文字のすぐ前後の PDF にない
    空白、ダッシュ・ハイフンの字形、引用符の字形・向き、英文の題目・副題・著者名・所属の大文字・小文字（pdfmatch.typeset_pair）
  ・直すもの（校正の直し。(B)。Fix の kind text）: 語句の追加・削除・置き換えで、組版の違いに還元できないもの（「資料」→
    「付録」など）。1 つの違いに (A) と (B) が混ざるときは pdfmatch.diff_parts で分ける。足す文字は PDF の文字のまま
  ・直さないもの: 表のセル・数式・図の中の文字（照合しない）、PDF の中に見つからない段落、数式・Word が付ける番号・
    リンクの文字にかかる違い、フィールドの結果・タブ・記号などの文字、空白だけの違い（PDF の空白は信頼できない）、
    段落の文字列を読み取り（docx_reader）と同じに組み立てられない段落（図形を含む段落など）、PDF のページ番号・誌名の行・
    柱・投稿受付日などや、docx にない図・表の中の文字とみなした文字（docx に足さない。PDF の側にその文字しかない位置の
    docx の文字も消さない）、照合で直し方を決められなかった違い（(C)。pdfmatch.TextDiff.why。段落の最初・最後の、どこまでが
    段落の文字か決められない文字、文字として取り出せない数式の位置にかかるものなど）。1 つの違いを分けた直す箇所の一部が
    ほかの直す箇所と重なるときは、その違いの直す箇所をすべて直さない（(A) と (B) に分けたものも、まとめて直さない）。
    PDF にない空白の削除（kind space）は、根拠の全角・半角の直し（kind width。PdfCheck.drop_basis）と同じ組（FixGroup）にし、
    どちらかを直さないことになったら（重なる・構造の確かめ・注の番号を守る・直せない文字にかかるなど、どの段階でも。
    spread_reasons）、両方を直さない（空白だけを消すと、docx にも PDF にもない文字になる）。根拠が Word が付ける番号だけの
    空白の削除は、番号の直し（変換のときに必ず PDF に合わせる）が止められることがないので、組にしない
  ・Word が付ける番号（自動段落番号・脚注番号）は docx の文字ではないので、ここでは直さず、変換のときに全角・半角と字形を
    PDF に合わせる（pipeline の plan.pdf_numbers）

できた docx は Word で開いて、変更を 1 つずつ承諾・却下できる。本ツールの読み取りは、挿入を残し削除を除いた文字
（すべて承諾した状態）を読むので、この docx をルート1 と同じ処理で変換すると、(A) と (B) を当てはめた文字の XML になる。
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
from .ooxml import (BR_TEXT_TYPES, MC_NS, M_NS, NO_RULE, HiddenRule, joined_paragraphs, paragraph_ids,
                    paragraph_mark_deleted, parse_xml, preprocess, sym_char, w)

XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
# 書き込む変更履歴の作成者名（組版の違いと校正の直しで分けない。利用者の判断、2026-11）。ルート2 の補完の確かめ（fidelity）も、
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
    # 組版の違い（(A)）: width（英数字・記号の全角・半角）/ space（PDF にない空白の削除）/ glyph（ダッシュ・ハイフン・引用符・
    # 大文字・小文字。細かい種類は pdfmatch.typeset_pair(old, new, case=True) で分かる）。校正の直し（(B)）と、直せない違い
    # （(C)。reason に理由）: text
    kind: str
    old: str = ""         # docx の文字
    applied: bool = False
    reason: str = ""      # 直さなかった理由
    # いっしょに直す直す箇所の組（FixGroup）。None なら単独。組の 1 つでも直さないことになったら、後の段階でも（_spread）、
    # 組の全部を直さない
    group: object = field(default=None, repr=False, compare=False)

    @property
    def typeset(self) -> bool:
        """組版の違い（(A)）の直す箇所か。"""
        return self.kind != "text"


@dataclass(eq=False)
class FixGroup:
    """いっしょに直す直す箇所の組。一部だけを当てはめると、docx にも PDF にもない文字になるもの。

    paired が偽: 1 つの違い（pdfmatch.TextDiff）を分けた直す箇所（「pp.45－58」を「pp.46-5-58」にしないため）。
    paired が真: 全角・半角の直し（kind width）と、そのすぐ隣の PDF にない空白の削除（kind space。check.drops）。
    空白だけを消すと「本文 (挿入の文字) の後ろ」が「本文(挿入の文字)の後ろ」になる。"""
    paired: bool = False
    members: list = field(default_factory=list)


def link_fixes(a: Fix, b: Fix, paired: bool = False) -> None:
    """a と b をいっしょに直す組にする（どちらかがすでに組なら、組を 1 つにまとめる）。"""
    ga = a.group or FixGroup(members=[a])
    a.group = ga
    if b.group is not ga:
        for m in (b.group.members if b.group is not None else [b]):
            m.group = ga
            ga.members.append(m)
    ga.paired = ga.paired or paired


def _fix_desc(f: Fix) -> str:
    return "空白の削除" if f.kind == "space" else f"全角・半角の直し「{f.old}」→「{f.new}」"


def spread_reasons(fixes) -> bool:
    """直さないことにした直す箇所（reason がある）と同じ組（Fix.group）の、まだ直すことにしている直す箇所も直さないことにする
    （組の一部が直らなければ、組の全部を直さない）。理由は、1 つの違いを分けた組なら直さない理由のまま、全角・半角と空白の削除の
    組なら、どの直しに連動して直さないかが分かる文。fixes の組のどれかが変わったか。"""
    changed = False
    for g in {id(f.group): f.group for f in fixes if f.group is not None}.values():
        bad = next((m for m in g.members if m.reason), None)
        if bad is None:
            continue
        for m in g.members:
            if not m.reason:
                m.reason = f"{_fix_desc(bad)}を直さないので、連動して直さない（その理由: {bad.reason}）" if g.paired else bad.reason
                changed = True
    return changed


@dataclass
class DocxFix:
    path: Path                                       # 出版版 PDF で補った docx
    fixes: list = field(default_factory=list)        # Fix（直したもの・直さなかったもの）
    unmatched: list = field(default_factory=list)    # PDF の中に見つからなかった段落
    check: object = None                             # 元の docx と PDF の照合（pdfmatch.PdfCheck）
    texts: dict = field(default_factory=dict)        # 元の docx の段落の文字列（直した段落・見つからない段落・照合に
    #                                                  使わなかった PDF の文字のある段落。レポート用）
    locations: dict = field(default_factory=dict)    # 元の docx の段落の場所（レポート用）

    @property
    def applied(self) -> list:
        return [f for f in self.fixes if f.applied]

    @property
    def skipped(self) -> list:
        return [f for f in self.fixes if not f.applied]

    @property
    def applied_text(self) -> list:
        """補った校正の直し（(B)。kind text の直したもの）。"""
        return [f for f in self.applied if not f.typeset]

    @property
    def applied_typeset(self) -> list:
        """PDF に合わせた組版の違い（(A)）。"""
        return [f for f in self.applied if f.typeset]

    @property
    def skipped_text(self) -> list:
        """直さなかった校正の直しと、決められない違い（(B)・(C)。要確認）。"""
        return [f for f in self.skipped if not f.typeset]

    @property
    def skipped_typeset(self) -> list:
        """直せなかった組版の違い（(A)。ほかの直す箇所と重なる、直せない文字にかかる、構造が変わるなど。要確認にしない）。"""
        return [f for f in self.skipped if f.typeset]


# ---------------------------------------------------------------------------- 直す箇所
def plan_fixes(plan, check) -> list:
    """照合の結果（PdfCheck）から、段落ごとの直す箇所（Fix）の一覧を作る。

    全角・半角（check.width）と PDF にない空白（check.drops）は 1 文字ずつの組版の違い（kind width・space）。違い（check.diffs）は
    pdfmatch.diff_parts で直す単位に分け、組版の違いの文字は kind width・glyph、校正の直しは kind text にする。直せない違い
    （fixable が偽）は分けずに理由付きの 1 つの Fix にし、kind は組版の違いだけのもの（TextDiff.kind typeset）なら width か
    glyph、それ以外は text（(C) と、番号・数式・リンクにかかる校正の直し）。"""
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
            # 空白の削除は、根拠の全角・半角の直しといっしょに直す（根拠の直しを直さないのに空白だけ消すと、docx にも PDF にも
            # ない文字になる）。根拠が Word が付ける番号だけのときは、番号は docx の文字ではなく、変換のときに必ず PDF に合わせる
            # （pdfdocx は止めない）ので、連動させる直し箇所がない
            basis = check.drop_basis.get(src, {}).get(q, ())
            for kind, *at in sorted(b for b in basis if b[0] == "width"):
                if (src, at[0]) in widths:
                    link_fixes(space, widths[src, at[0]], paired=True)
                else:
                    space.reason = space.reason or "根拠の全角・半角の直しがない"
    case_srcs = check.case_srcs
    for d in check.diffs:
        text = plan.paras[d.src].plain()
        old = text[d.start:d.end]
        if not d.fixable:
            kind = _typeset_kind(d.docx, d.pdf) if d.kind == "typeset" else "text"
            fixes.append(Fix(d.src, d.start, d.end, d.pdf, kind, old,
                             reason=d.why or "数式・Word が付ける番号・リンクの文字にかかる、または足す位置を決められない"))
            continue
        # 違う部分の中でも、文字ごとに最小限の変更にし、組版の違いと校正の直しを分ける（「58」→「５８９」は「5」「8」の
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
    """段落の文字列を読み取りと同じに組み立てられない（図形を含むなど）。"""


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
    for a in el.iterancestors():
        if a.tag == f"{{{MC_NS}}}Fallback":
            ac = a.getparent()
            if ac is not None and ac.find(f"{{{MC_NS}}}Choice") is not None:
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
    図形・ルビを含む段落は _Complex。hidden は隠し文字の判定（ooxml.HiddenRule。None なら NO_RULE）。段落記号の削除による
    つながりは見ない（write_fixed_docx が、連鎖の段落ごとの単位を連結する）。
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

    def run(r, deleted, hidden):
        for ch in r:
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
            if tag in (w("drawing"), w("pict"), w("object")) and deleted:
                continue        # 削除の変更履歴の中の図形は、承諾すると消える（読み取りも読まない）
            if tag in (w("drawing"), w("pict"), w("object"), w("ruby")):
                raise _Complex
            if deleted or in_code() or hidden:
                continue
            editable = not fields       # フィールドの結果の文字は直さない（フィールドを更新すると戻るため）
            if tag == w("t"):
                out.extend((c, ch if editable else None, k) for k, c in enumerate(ch.text or ""))
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

    先に、直せない直す箇所をすべて決め、いっしょに直す組（Fix.group）の一部が直せなければ組の全部を直さないことにしてから、
    直せるものを書き込む（一部だけ書き込んだ後では取り消せない）。"""
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

    段落記号の削除でつながる段落（_chains）は、連鎖の最初の段落の ID で、連鎖の w:p ごとの単位（paragraph_units）を連結して
    直す。連鎖の後ろの段落の ID には直す箇所がない（読み取りの段落がない）。
    """
    if same_file(src_path, dst_path):
        # 入力を読みながら同じファイルを書き出すと、入力が壊れる（書き込む前に止める。呼び出し側が別の名前にする）
        raise ValueError(f"入力の docx と、補った docx の書き出し先が同じファイルです: {dst_path}")
    date = date or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    writer = _Writer(date)
    spread_reasons(fixes)       # 直さないことにした直す箇所と組の直す箇所も直さない
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
                        f.reason = "段落の文字列を読み取りと同じに組み立てられない（図形を含む段落など）"
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
    """ルート2 の最初の段階: docx と PDF を照合し、組版の違いと校正の直しを出版版 PDF で補った docx（変更履歴つき）を out_path に
    作る。

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
    fix.fixes = plan_fixes(plan, check)
    for s in {f.src for f in fix.fixes} | set(fix.unmatched) | {src for src, _ in check.ignored_lines}:
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
        spread_reasons(fix.fixes)       # 守る範囲に入った直す箇所と組の直す箇所も直さない（空白の削除だけが残らないように）
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
    """段落ごとの（役割, 領域）とリンクの並び {src: ((役割, 領域), [(リンク, 開始, 終了)])}、注 {fid: (番号, 段落)}、注の番号の範囲、
    著者と所属（_people）。

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
    fns = {fn.fid: (fn.number, tuple(q.src for q in fn.paras)) for fn in plan.fns}
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
    分けるなら ("split",)、和文の氏名は ("eastern", 語の数)、英文の氏名は ("western", 語の数, 姓の語の番号)。直した文字で
    分け方が変わったか（大文字の語の位置・空白の数）を比べるため。"""
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
        return ("eastern", len(toks))
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
