"""ルート2: 出版版 PDF に合わせて直した docx（Word の変更履歴つき）を作る。

docx の段落と PDF の照合（pdfmatch.py）の結果から、段落ごとの直す箇所を決め、元の docx の XML（前処理しないもの）の
ランを分けて、削除（w:del）と挿入（w:ins）の変更履歴として書き込む。書式（太字・斜体・上付きなど）は、直す文字の
ランの書式をそのまま使う。

  ・直すもの: 英数字・記号の全角・半角と、その文字のすぐ前後の PDF にない空白、それ以外の文字の違い
    （大文字・小文字、引用符、「資料」→「付録」など）
  ・直さないもの: 表のセル・数式・図の中の文字（照合しない）、PDF の中に見つからない段落、数式・Word が付ける番号・
    リンクの文字にかかる違い、フィールドの結果・タブ・記号などの文字、空白だけの違い（PDF の空白は信頼できない）、
    段落の文字列を読み取り（docx_reader）と同じに組み立てられない段落（図形を含む段落など）、PDF のページ番号・誌名の行・
    柱・投稿受付日などや、docx にない図・表の中の文字とみなした文字（docx に足さない。PDF の側にその文字しかない位置の
    docx の文字も消さない）、照合で直し方を決められなかった違い（pdfmatch.TextDiff.why。段落の最初・最後の、どこまでが
    段落の文字か決められない文字、文字として取り出せない数式の位置にかかるものなど）。1 つの違いを分けた直す箇所の一部が
    ほかの直す箇所と重なるときは、その違いの直す箇所をすべて直さない

できた docx は Word で開いて、変更を 1 つずつ承諾・却下できる。本ツールの読み取りは、挿入を残し削除を除いた文字
（すべて承諾した状態）を読むので、この docx をルート1 と同じ処理で変換すると、PDF に合わせた文字の XML になる。
書き込んだ後に docx を読み直し、段落の文字列が直した結果と一致することを確かめる（一致しない段落は直さずに作り直す）。
"""
from __future__ import annotations

import copy
import datetime as _dt
import difflib
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from .model import OBJ
from .ooxml import BR_TEXT_TYPES, MC_NS, M_NS, parse_xml, run_hidden, sym_char, w

XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
AUTHOR = "jasme-jats（出版版 PDF に合わせた変更）"
PARTS = {"word/document.xml": "d", "word/footnotes.xml": "f"}
# 直してよいラン（w:r）の親。既存の変更履歴（w:ins / w:del）の中やハイパーリンクの中は直さない
RUN_PARENTS = {w("p"), w("smartTag"), w("customXml"), w("sdtContent")}


@dataclass
class Fix:
    src: str
    start: int            # docx の段落（plain）の中の範囲 [start, end)。start == end なら、その位置に足す
    end: int
    new: str              # PDF の文字（削除なら空）
    kind: str             # width（全角・半角）/ space（空白の削除）/ text（文字の違い）
    old: str = ""         # docx の文字
    applied: bool = False
    reason: str = ""      # 直さなかった理由


@dataclass
class DocxFix:
    path: Path                                       # 直した docx
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


# ---------------------------------------------------------------------------- 直す箇所
def plan_fixes(plan, check) -> list:
    """照合の結果（PdfCheck）から、段落ごとの直す箇所（Fix）の一覧を作る。"""
    fixes = []
    for src, m in check.width.items():
        text = plan.paras[src].plain()
        fixes += [Fix(src, q, q + 1, c, "width", text[q]) for q, c in m.items()]
    for src, ds in check.drops.items():
        text = plan.paras[src].plain()
        fixes += [Fix(src, q, q + 1, "", "space", text[q]) for q in ds]
    group = {}       # id(Fix) -> 違い（TextDiff）の番号。1 つの違いを分けた直す箇所は、まとめて直すか、まとめて直さない
    for gi, d in enumerate(check.diffs):
        text = plan.paras[d.src].plain()
        old = text[d.start:d.end]
        if not d.fixable:
            fixes.append(Fix(d.src, d.start, d.end, d.pdf, "text", old,
                             reason=d.why or "数式・Word が付ける番号・リンクの文字にかかる、または足す位置を決められない"))
            continue
        # 違う部分の中でも、文字ごとに最小限の変更にする（大文字・小文字の違いなど）
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, d.pdf, autojunk=False).get_opcodes():
            if tag == "equal":
                continue
            o, n = old[i1:i2], d.pdf[j1:j2]
            # docx の空白は消さない（PDF の空白は信頼できないので、空白だけの違いは直さない）
            while o and o[0].isspace() and not n[:1].isspace():
                o, i1 = o[1:], i1 + 1
            while o and o[-1].isspace() and not n[-1:].isspace():
                o, i2 = o[:-1], i2 - 1
            if not o.strip() and not n.strip():
                continue
            fixes.append(Fix(d.src, d.start + i1, d.start + i2, n, "text", o))
            group[id(fixes[-1])] = gi
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
        bad = {group[id(f)] for f in fixes if f.reason == overlap and id(f) in group}
        more = [f for f in fixes if not f.reason and group.get(id(f)) in bad]
        if not more:
            break
        for f in more:
            f.reason = overlap
    return fixes


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


def paragraph_units(p) -> list:
    """段落の文字を [(文字, w:t 要素または None, w:t の中の位置)] で返す。読み取り（docx_reader）の文字ポリシーと同じ。

    直せるのは w:t の文字と、Word の改行なしハイフン（w:noBreakHyphen。要素そのものと位置 0。要素ごと変更履歴の削除にして、
    PDF の「-」を足せる）だけ（タブ・改行・記号・フィールドの結果・数式・脚注番号などは None）。
    図形・ルビを含む段落は _Complex。
    """
    out = []
    fields = []          # [code_mode]

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
                run(ch, deleted, hidden or run_hidden(ch))
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
    """段落に直す箇所を書き込む。直せないものは Fix.reason に理由を書く。"""
    plans = {}           # w:t -> (削除する位置, {この位置の後に足す: [文字列]})

    def plan_of(t):
        return plans.setdefault(t, (set(), {}))

    def ok_run(t):
        r = t.getparent()
        return r is not None and r.tag == w("r") and r.getparent() is not None and r.getparent().tag in RUN_PARENTS

    for f in fixes:
        if f.reason:
            continue
        rng = units[f.start:f.end]
        if any(t is None or not ok_run(t) for _, t, _ in rng):
            f.reason = "直せない文字（タブ・記号・フィールドの結果、既存の変更履歴やリンクの中の文字など）にかかる"
            continue
        if f.start == f.end:          # 足す: 直前の文字の後（なければ直後の文字の前）
            if f.start > 0 and units[f.start - 1][1] is not None and ok_run(units[f.start - 1][1]):
                _, t, k = units[f.start - 1]
            elif f.start < len(units) and units[f.start][1] is not None and ok_run(units[f.start][1]):
                _, t, k = units[f.start]
                k -= 1
            else:
                f.reason = "文字を足す位置の前後が直せない文字"
                continue
            plan_of(t)[1].setdefault(k, []).append(f.new)
        else:
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


def write_fixed_docx(src_path, dst_path, plan, fixes, skip=frozenset(), date=None):
    """直す箇所を変更履歴として書き込んだ docx を dst_path に作る。skip の段落は直さない。"""
    date = date or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    writer = _Writer(date)
    by_src = {}
    for f in fixes:
        by_src.setdefault(f.src, []).append(f)
    with zipfile.ZipFile(src_path) as zin:
        roots = {part: parse_xml(zin.read(part)) for part in PARTS if part in zin.namelist()}
        ids_used = [int(v) for root in roots.values() for el in root.iter() if isinstance(el.tag, str)
                    for v in [el.get(w("id"))] if v and v.lstrip("-").isdigit()]
        writer.next_id = max(ids_used + [0]) + 1000
        for part, root in roots.items():
            for src, p_el in raw_paragraph_ids(root, PARTS[part]).items():
                pf = [f for f in by_src.get(src, []) if not f.reason]
                if not pf:
                    continue
                if src in skip:
                    for f in pf:
                        f.reason = "書き込んだ後に読み直した文字列が合わなかった"
                    continue
                try:
                    units = paragraph_units(p_el)
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
    yield from doc.all_paragraphs()
    for notes in doc.footnotes.values():
        yield from notes


def make_fixed_docx(docx_path, pdf_path, out_path, journal) -> DocxFix:
    """ルート2 の最初の段階: docx と PDF を照合し、PDF に合わせて直した docx（変更履歴つき）を out_path に作る。

    書き込んだ後に読み直して、(1) 直した段落の文字列が直した結果と一致するか、(2) 段落の役割・リンク（注・引用文献・図表
    など）・注の区切りが元の docx と同じに決まるかを確かめる。合わない箇所は直さずに作り直す。
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
    """段落ごとの役割とリンクの並び {src: (役割, [(リンク, 開始, 終了)])}、注 {fid: (番号, 段落)}、注の番号の範囲。"""
    paras = {}
    for src, p in plan.paras.items():
        links, pos = [], 0
        for a in p.atoms:
            n = len(a.text) if a.kind == "text" else 1
            if a.link is not None:
                links.append(((a.link.kind, tuple(sorted(a.link.attrs.items()))), pos, pos + n))
            pos += n
        paras[src] = (p.role, links)
    fns = {fn.fid: (fn.number, tuple(q.src for q in fn.paras)) for fn in plan.fns}
    marks = [(fn.paras[0].src, tuple(fn.mark_range), fn.fid) for fn in plan.fns if fn.paras and fn.mark_range]
    return paras, fns, marks


def _lost(original, fixed) -> list:
    """直した docx で、元の docx と同じに決まらなくなったもの [(src, (開始, 終了) または None, 理由, リンク先)]（範囲は元の段落の上）。

    注の番号（本文の注へのリンクと、注の一覧の先頭の番号）は、どれか 1 つでも守るときは、すべての注で守る（そろえるため）。
    """
    (paras0, fns0, marks0), (paras1, fns1, _) = original, fixed
    out, notes = [], False
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
