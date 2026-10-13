"""機械的なリンク付け（生成 AI は使わない）。

  図・表   : 本文中の「図1」「表2」「Figure 1」などを <xref ref-type="fig|table">
  数式     : 「式(1)」「(1)式」を <xref ref-type="disp-formula">
  注       : 上付きの「1)」などを <xref ref-type="fn">
  引用文献 : 著者・年方式の引用の「年」だけを <xref ref-type="bibr">（refparse.py）
  URL・DOI : そのままの文字列を <uri> / <ext-link> / <pub-id>

リンクはアトムの範囲に LinkSpec を付けるだけで、文字列は変えない。
"""
from __future__ import annotations

import re
import unicodedata

from .model import OBJ, Atom, LinkSpec, Para
from .structure import ArticlePlan, FigNode, FormulaNode, ListNode, PNode, QuoteNode, Sec, TableNode

# URL（末尾の句読点・閉じ括弧は含めない）
RE_URL = re.compile(r"(?:https?://|www\.)[^\s<>\"'「」『』、。，（）［］【】〔〕\u3000]+", re.I)
RE_DOI_PREFIXED = re.compile(r"(?:\bdoi\s*[:：]\s*|DOI\s*[:：]?\s*)(10\.\d{4,9}/[^\s<>\"、。，（）「」]+)", re.I)
RE_DOI_BARE = re.compile(r"(?<![\w/.])(10\.\d{4,9}/[^\s<>\"、。，（）「」]+)")
FW = str.maketrans("０１２３４５６７８９", "0123456789")
NUM = r"[0-9０-９]+"
RE_FIGREF = re.compile(rf"(図|Figure|Figs?\.)[\s\u3000]?({NUM})((?:[\s\u3000]*(?:[,，、・]|～|〜|-|－|–|と|及び|および|and)[\s\u3000]*(?:図)?{NUM})*)")
RE_TABREF = re.compile(rf"(表|Tables?)[\s\u3000]?({NUM})((?:[\s\u3000]*(?:[,，、・]|～|〜|-|－|–|と|及び|および|and)[\s\u3000]*(?:表)?{NUM})*)")
RE_EQREF = re.compile(rf"式[\s\u3000]?([(（][\s\u3000]*{NUM}(?:[.．\-－]{NUM})?[\s\u3000]*[)）])|([(（][\s\u3000]*{NUM}(?:[.．\-－]{NUM})?[\s\u3000]*[)）])[\s\u3000]?式")
RE_FN_MARK = re.compile(rf"^[\s\u3000]*(?:注[\s\u3000]*)?[(（]?[\s\u3000]*({NUM})[\s\u3000]*[)）]?[\s\u3000]*$")
# 上付きでない注番号。「注」の字と閉じ括弧があるもの（「（注1）」「［注1］」「注1)」）だけ。「(1)」は箇条の番号などと区別できない
RE_FN_PLAIN = re.compile(rf"[(（\[［〔][\s\u3000]*[注註][\s\u3000]*({NUM})[\s\u3000]*[)）\]］〕]"
                         rf"|(?<![\u3400-\u9fff々])[注註][\s\u3000]*({NUM})[\s\u3000]*[)）]")


def fw_int(s: str) -> int:
    return int(unicodedata.normalize("NFKC", s))


# ---------------------------------------------------------------------------- アトム操作
def atom_offsets(p: Para):
    out = []
    pos = 0
    for a in p.atoms:
        n = len(a.text) if a.kind == "text" else 1
        out.append((pos, pos + n))
        pos += n
    return out


def range_linked(p: Para, s: int, e: int) -> bool:
    """[s, e) にすでにリンク（または docx のハイパーリンク）が付いているか。"""
    for a, (a0, a1) in zip(p.atoms, atom_offsets(p)):
        if a1 <= s or a0 >= e:
            continue
        if a.link is not None or a.href:
            return True
    return False


def apply_span(p: Para, s: int, e: int, spec: LinkSpec, force: bool = False) -> bool:
    """para.plain() 上の [s, e) のアトムに spec を付ける。文字列は変えない。

    範囲が数式・画像をまたぐ場合や、すでにリンクがある場合は付けない（force でも数式はまたがない）。
    """
    if e <= s:
        return False
    plain = p.plain()
    if OBJ in plain[s:e]:
        return False
    if not force and range_linked(p, s, e):
        return False
    new_atoms = []
    for a, (a0, a1) in zip(p.atoms, atom_offsets(p)):
        if a.kind != "text" or a1 <= s or a0 >= e:
            new_atoms.append(a)
            continue
        cut = [a0, max(a0, s), min(a1, e), a1]
        for k in range(3):
            x0, x1 = cut[k], cut[k + 1]
            if x1 <= x0:
                continue
            b = Atom(kind="text", text=a.text[x0 - a0:x1 - a0], fmt=a.fmt, href=a.href, link=a.link)
            if k == 1:
                b.link = spec
                if force:
                    b.href = None
            new_atoms.append(b)
    p.atoms = new_atoms
    return True


def find_in_para(p: Para, text: str, occurrence: int = 1):
    plain = p.plain()
    start = -1
    for _ in range(max(occurrence, 1)):
        start = plain.find(text, start + 1)
        if start < 0:
            return None
    return start, start + len(text)


# ---------------------------------------------------------------------------- 本文の段落を列挙
def body_paragraphs(plan: ArticlePlan):
    """リンク付けの対象となる段落を (para, 文脈) で列挙する。文脈: body / caption / cell / abstract / back / ref"""
    def walk(nodes, where="body"):
        for node in nodes:
            if isinstance(node, Sec):
                if node.heading is not None:
                    yield node.heading, "title"
                yield from walk(node.children, where)
            elif isinstance(node, PNode):
                yield node.para, where
            elif isinstance(node, (QuoteNode,)):
                for p in node.paras:
                    yield p, where
            elif isinstance(node, ListNode):
                for p in node.items:
                    yield p, where
            elif isinstance(node, FigNode):
                if node.caption is not None:
                    yield node.caption, "caption"
                for t in node.tables:
                    for p in t.paragraphs():
                        yield p, "cell"
            elif isinstance(node, TableNode):
                if node.caption is not None:
                    yield node.caption, "caption"
                if node.table is not None:
                    for p in node.table.paragraphs():
                        yield p, "cell"
            elif isinstance(node, FormulaNode):
                yield node.para, "formula"
    yield from walk(plan.body)
    for p in plan.abstract:
        yield p, "abstract"
    for sec in (plan.notes, plan.ack):
        if sec is not None:
            yield from walk(sec.children, "back")
    for fn in plan.fns:
        for p in fn.paras:
            yield p, "fn"
    for app in plan.apps:
        yield from walk(app.children, "back")
    for r in plan.refs:
        yield r.para, "ref"


# ---------------------------------------------------------------------------- 個別のリンク
class Linker:
    def __init__(self, plan: ArticlePlan, ref_doi: str = "pub-id"):
        self.plan = plan
        self.ref_doi = ref_doi      # 引用文献中の DOI: "uri"（リンクとして表示）/ "pub-id"（DOI として登録）
        self.count = {"fig": 0, "table": 0, "disp-formula": 0, "fn": 0, "bibr": 0, "url": 0, "doi": 0, "word": 0}
        self.unresolved = []    # (category, src, text, detail)

    def note(self, category, src, msg):
        self.plan.decide("mechanical", category, src, msg)

    def run(self):
        from .refparse import link_citations
        plan = self.plan
        self.label_formulas()
        paras = list(body_paragraphs(plan))
        for p, where in paras:
            self.word_hyperlinks(p, where)
        for p, where in paras:
            self.urls(p, where)
        fig_ids = {f.number: f.fid for f in plan.figures if f.number is not None and f.fid}
        tab_ids = {t.number: t.tid for t in plan.tables if t.number is not None and t.tid}
        eq_ids = {}
        for f in plan.formulas:
            if f.fid and f.label:
                eq_ids[re.sub(r"[\s\u3000()（）]", "", unicodedata.normalize("NFKC", f.label))] = f.fid
        fn_ids = {fn.number: fn.fid for fn in plan.fns if fn.number is not None and not fn.word_note}
        captions = {id(f.caption) for f in plan.figures if f.caption is not None} | \
                   {id(t.caption) for t in plan.tables if t.caption is not None}
        for p, where in paras:
            if where == "ref":
                continue
            if id(p) not in captions:
                self.float_refs(p, RE_FIGREF, fig_ids, "fig", "図")
                self.float_refs(p, RE_TABREF, tab_ids, "table", "表")
            if where != "formula":
                self.eq_refs(p, eq_ids)
            if where not in ("fn",):
                self.fn_marks(p, fn_ids)
                self.fn_marks_plain(p, fn_ids)
        link_citations(plan, self, paras)
        return self

    # 数式番号を <label> に
    def label_formulas(self):
        for f in self.plan.formulas:
            if f.label_range and not range_linked(f.para, *f.label_range):
                apply_span(f.para, f.label_range[0], f.label_range[1], LinkSpec(kind="label"))

    def word_hyperlinks(self, p: Para, where: str = "body"):
        """docx のハイパーリンク（href 付きの文字）を uri リンクにする。

        引用文献の中で、表示されている文字が URL そのもの（または DOI を含む doi.org のリンク）であるものは、
        Word のリンクとしては扱わず、後の urls() に任せる。ハイパーリンクの有無で文献ごとに形が変わらないよう、
        DOI は一律に「https://doi.org/ の文字 + <pub-id>」にするため（リンク先は同じ）。
        """
        i = 0
        atoms = p.atoms
        while i < len(atoms):
            a = atoms[i]
            if a.kind == "text" and a.href and a.link is None:
                j = i
                while j + 1 < len(atoms) and atoms[j + 1].kind == "text" and atoms[j + 1].href == a.href \
                        and atoms[j + 1].link is None:
                    j += 1
                if where == "ref" and _same_as_text(a.href, "".join(atoms[k].text for k in range(i, j + 1))):
                    for k in range(i, j + 1):
                        atoms[k].href = None
                    i = j + 1
                    continue
                spec = LinkSpec(kind="uri", attrs={"href": a.href}, origin="word")
                for k in range(i, j + 1):
                    atoms[k].link = spec
                self.count["word"] += 1
                i = j + 1
            else:
                i += 1

    def doi_spec(self, doi: str, kind: str, where: str) -> LinkSpec:
        href = "https://doi.org/" + doi
        if where == "ref" and self.ref_doi == "pub-id":
            return LinkSpec(kind="pub-id", attrs={"pub-id-type": "doi", "href": href})
        return LinkSpec(kind=kind, attrs={"href": href})

    def urls(self, p: Para, where: str):
        plain = p.plain()
        kind = "ext-link" if where in ("fn", "back") else "uri"
        # DOI（doi: 付き・裸）
        for m in RE_DOI_PREFIXED.finditer(plain):
            s, e = m.start(1), m.end(1)
            doi = _trim(plain[s:e])
            e = s + len(doi)
            spec = self.doi_spec(doi, kind, where)
            if apply_span(p, s, e, spec):
                self.count["doi"] += 1
        for m in RE_URL.finditer(plain):
            s = m.start()
            url = _trim(m.group(0))
            e = s + len(url)
            href = url if re.match(r"https?://", url, re.I) else "http://" + url
            dm = re.match(r"https?://(?:dx\.)?doi\.org/(10\.\d{4,9}/\S+)", url, re.I)
            if dm and where == "ref" and self.ref_doi == "pub-id":
                ds = s + dm.start(1)
                spec = LinkSpec(kind="pub-id", attrs={"pub-id-type": "doi", "href": url})
                if apply_span(p, ds, e, spec):
                    self.count["doi"] += 1
                continue
            if apply_span(p, s, e, LinkSpec(kind=kind, attrs={"href": href})):
                self.count["doi" if dm else "url"] += 1
                if not url.lower().startswith("http"):
                    self.note("url", p.src, f"「{url}」に http:// を補ってリンク先とした")
        if where == "ref":
            for m in RE_DOI_BARE.finditer(plain):
                s = m.start(1)
                doi = _trim(m.group(1))
                e = s + len(doi)
                spec = self.doi_spec(doi, "uri", where)
                if apply_span(p, s, e, spec):
                    self.count["doi"] += 1

    def float_refs(self, p: Para, regex, ids, ref_type, word):
        plain = p.plain()
        for m in regex.finditer(plain):
            n = fw_int(m.group(2))
            s, e = m.start(1), m.end(2)
            self._link_num(p, s, e, n, ids, ref_type, word, m.group(0))
            tail = m.group(3)
            if tail:
                base = m.start(3)
                for t in re.finditer(NUM, tail):
                    self._link_num(p, base + t.start(), base + t.end(), fw_int(t.group(0)), ids, ref_type, word,
                                   m.group(0))

    def _link_num(self, p, s, e, n, ids, ref_type, word, context):
        rid = ids.get(n)
        if rid is None:
            self.unresolved.append((ref_type, p.src, context, f"{word}{n} に対応する{word}が見つからない"))
            return
        if apply_span(p, s, e, LinkSpec(kind="xref", attrs={"ref-type": ref_type, "rid": rid})):
            self.count[ref_type] += 1

    def eq_refs(self, p: Para, eq_ids):
        if not eq_ids:
            return
        plain = p.plain()
        for m in RE_EQREF.finditer(plain):
            lab = m.group(1) or m.group(2)
            key = re.sub(r"[\s\u3000()（）]", "", unicodedata.normalize("NFKC", lab))
            rid = eq_ids.get(key)
            if rid and apply_span(p, m.start(), m.end(), LinkSpec(kind="xref", attrs={"ref-type": "disp-formula", "rid": rid})):
                self.count["disp-formula"] += 1

    def fn_marks(self, p: Para, fn_ids):
        """上付き文字の「1)」「注1」などを注へのリンクにする。"""
        if not fn_ids:
            return
        offs = atom_offsets(p)
        i = 0
        atoms = list(p.atoms)
        while i < len(atoms):
            a = atoms[i]
            if a.kind == "text" and "sup" in a.fmt and a.link is None:
                j = i
                text = a.text
                while j + 1 < len(atoms) and atoms[j + 1].kind == "text" and "sup" in atoms[j + 1].fmt \
                        and atoms[j + 1].link is None:
                    j += 1
                    text += atoms[j].text
                s0 = offs[i][0]
                # 「1),2)」のように複数並ぶ場合も考慮
                for m in re.finditer(rf"(?:注[\s\u3000]*)?[(（]?[\s\u3000]*({NUM})[\s\u3000]*[)）]?", text):
                    if not m.group(0).strip():
                        continue
                    n = fw_int(m.group(1))
                    rid = fn_ids.get(n)
                    if rid is None:
                        self.unresolved.append(("fn", p.src, m.group(0), f"上付きの「{m.group(0)}」に対応する注が見つからない"))
                        continue
                    ms, me = s0 + m.start(), s0 + m.end()
                    if apply_span(p, ms, me, LinkSpec(kind="xref", attrs={"ref-type": "fn", "rid": rid})):
                        self.count["fn"] += 1
                atoms = list(p.atoms)
                offs = atom_offsets(p)
                # 次のアトムへ（分割でアトム数が変わるため位置で進める）
                end_pos = s0 + len(text)
                i = next((k for k, (a0, a1) in enumerate(offs) if a0 >= end_pos), len(atoms))
            else:
                i += 1

    def fn_marks_plain(self, p: Para, fn_ids):
        """上付きでない「（注1）」などを注へのリンクにする（テンプレートの規定は上付きの「1)」だが、本文の大きさで書かれた場合）。"""
        if not fn_ids:
            return
        text = p.plain()
        for m in RE_FN_PLAIN.finditer(text):
            s, e = m.span()
            if range_linked(p, s, e) or _has_sup(p, s, e):
                continue    # 上付きのものは fn_marks() で扱う
            n = fw_int(m.group(1) or m.group(2))
            rid = fn_ids.get(n)
            if rid is None:
                self.unresolved.append(("fn", p.src, m.group(0), f"「{m.group(0)}」に対応する注が見つからない"))
                continue
            if apply_span(p, s, e, LinkSpec(kind="xref", attrs={"ref-type": "fn", "rid": rid})):
                self.count["fn"] += 1
                self.note("note", p.src, f"上付きでない注番号「{m.group(0)}」を注 {rid} にリンクした")


def _has_sup(p: Para, s: int, e: int) -> bool:
    return any(a.kind == "text" and "sup" in a.fmt for a, (a0, a1) in zip(p.atoms, atom_offsets(p)) if a0 < e and a1 > s)


def _same_as_text(href: str, text: str) -> bool:
    """ハイパーリンクの href が、表示されている文字から機械的に作るリンクと同じ先を指すか。"""
    h, t = href.strip(), text.strip()
    if h.rstrip("/").lower() == t.rstrip("/").lower():
        return True
    m = re.match(r"https?://(?:dx\.)?doi\.org/(10\.\d{4,9}/\S+)$", h, re.I)
    return bool(m) and m.group(1).lower() in t.lower()


def _trim(url: str) -> str:
    """URL の末尾から、文の句読点や対応しない閉じ括弧を除く。"""
    while url and url[-1] in ".,;:!?。、，．)]）」』>":
        if url[-1] in ")）" and url.count("(") + url.count("（") >= url.count(")") + url.count("）"):
            break
        url = url[:-1]
    return url


def link(plan: ArticlePlan, ref_doi: str = "pub-id") -> Linker:
    return Linker(plan, ref_doi).run()


def linked_ids(plan: ArticlePlan, ref_type: str) -> set:
    """本文（引用文献リスト以外）からリンクされている、指定した種類（bibr / fig / table など）の ID。"""
    out = set()
    for p, where in body_paragraphs(plan):
        if where == "ref":
            continue
        for a in p.atoms:
            if a.link is not None and a.link.kind == "xref" and a.link.attrs.get("ref-type") == ref_type:
                out.add(a.link.attrs.get("rid"))
    return out


def cited_refs(plan: ArticlePlan) -> set:
    """本文からリンクされている文献の ID。"""
    return linked_ids(plan, "bibr")
