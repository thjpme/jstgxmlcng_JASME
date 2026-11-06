"""直し方の試作（リポジトリは変えず、実行時に builder・emit を差し替える）。

- Emitter.gen に src を足す（kind autonum のとき段落 ID を属性 src に）
- Builder.autonum_mark(parent, p): paragraph_or_formula と同じ区切りで番号を先頭に補う
- 表のセル・引用・英文要旨・注の 2 段落目以降・別行数式・キャプション（label）・後付けの見出し（title の先頭）で番号を出す
- 題目・著者名・所属は出さない（意図して出さない経路。守りの対象外）
- 守り: lost_autonums(plan, root) を計算する

import して install() を呼ぶ。python3 proto.py で audit.docx と全 docx を変換して確かめる。
"""
import sys
import unicodedata
from pathlib import Path

from lxml import etree

from jasme_jats import builder as B
from jasme_jats import emit as E
from jasme_jats.builder import RE_HEAD_SPLIT, RE_LABEL_SPLIT, _starts_with_space, _sub
from jasme_jats.tracking import GEN, SPAN

NO_NUMBER_PLACES = ("title-group", "contrib", "aff")    # 題目・著者名・所属（意図して番号を出さない）


def gen(parent, text, kind, src=None):
    el = etree.SubElement(parent, GEN)
    el.set("kind", kind)
    if src:
        el.set("src", src)
    el.text = text
    return el


def autonum_mark(self, parent, p):
    if not p.autonum:
        return
    mark = self.autonum(p).strip()
    if mark:
        sep = "" if _starts_with_space(p) or unicodedata.east_asian_width(mark[-1]) in ("F", "W") else " "
        self.em.gen(parent, mark + sep, "autonum", p.src)


def autonum_label(self, parent, p):
    if p.autonum and self.autonum(p).strip():
        self.em.gen(_sub(parent, "label"), self.autonum(p), "autonum", p.src)
        return True
    return False


def install():
    E.Emitter.gen = staticmethod(gen)
    Bd = B.Builder
    Bd.autonum_mark = autonum_mark
    Bd.autonum_label = autonum_label

    def sec(self, parent, node):
        s = _sub(parent, "sec")
        if node.sid:
            s.set("id", node.sid)
        h = node.heading
        if h is None:
            _sub(s, "title")
        else:
            if h.autonum:
                lab = _sub(s, "label")
                self.em.gen(lab, self.autonum(h), "autonum", h.src)
            self.labelled(s, h, RE_HEAD_SPLIT, B.E.SECTITLE, title_tag="title", allow_label=not h.autonum)
        self.nodes(s, node.children)
    Bd.sec = sec

    def paragraph_or_formula(self, parent, p, ctx, autonum_mark=False):
        pe = _sub(parent, "p")
        if autonum_mark:
            self.autonum_mark(pe, p)
        self.em.span(pe, p, ctx)
    Bd.paragraph_or_formula = paragraph_or_formula

    def list_node(self, parent, node, ctx=B.E.BODY):
        lst = _sub(parent, "list", list_type="order" if node.ordered else "bullet")
        for p in node.items:
            li = _sub(lst, "list-item")
            if p.autonum:
                lab = _sub(li, "label")
                self.em.gen(lab, self.autonum(p), "autonum", p.src)
            pe = _sub(li, "p")
            self.em.span(pe, p, ctx)
    Bd.list_node = list_node

    orig_nodes = Bd.nodes

    def nodes(self, parent, nodes, top=False):
        from jasme_jats.article import QuoteNode
        for node in nodes:
            if isinstance(node, QuoteNode):
                dq = _sub(parent, "disp-quote")
                for p in node.paras:
                    pe = _sub(dq, "p")
                    self.autonum_mark(pe, p)
                    self.em.span(pe, p, B.E.BODY)
            else:
                orig_nodes(self, parent, [node], top=top)
    Bd.nodes = nodes

    def cell_content(self, td, blocks):
        from jasme_jats.model import Para
        paras = []
        for b in blocks:
            if isinstance(b, Para):
                paras.append(b)
            else:
                paras.extend(b.paragraphs())
                self.info.warnings.append("表の中の表（入れ子）は、内側の表の文字を順に並べて出力した")
        first = True
        aligns = set()
        for p in paras:
            if p.is_blank and not p.plain():
                continue
            if not first:
                _sub(td, "break")
            self.autonum_mark(td, p)
            self.em.span(td, p, B.E.CELL)
            first = False
            if p.align:
                aligns.add(p.align)
        if len(aligns) == 1:
            a = aligns.pop()
            a = {"center": "center", "left": "left", "start": "left", "right": "right", "end": "right"}.get(a)
            if a:
                td.set("align", a)
    Bd.cell_content = cell_content

    def formula(self, parent, node):
        df = _sub(parent, "disp-formula")
        if node.fid:
            df.set("id", node.fid)
        self.autonum_mark(df, node.para)
        self.em.span(df, node.para, B.E.DISPF)
    Bd.formula = formula

    def caption(self, holder, cap):
        if self.autonum_label(holder, cap):
            self.labelled(holder, cap, RE_LABEL_SPLIT, B.E.CAPTION, title_tag="caption", allow_label=False, wrap_p=True)
            return
        m = RE_LABEL_SPLIT.match(cap.plain()) if self.split else None
        if m and m.group(2):
            self.labelled(holder, cap, RE_LABEL_SPLIT, B.E.CAPTION, title_tag="caption", wrap_p=True)
        else:
            c = _sub(holder, "caption")
            pe = _sub(c, "p")
            self.em.span(pe, cap, B.E.CAPTION)

    def caption_more(self, holder, paras):
        if not paras:
            return
        cap = holder.find("caption")
        if cap is None:
            cap = _sub(holder, "caption")
        for p in paras:
            pe = _sub(cap, "p")
            self.autonum_mark(pe, p)
            self.em.span(pe, p, B.E.CAPTION)
    Bd.caption_more = caption_more

    orig_fig, orig_tw = Bd.fig, Bd.table_wrap

    def fig(self, parent, node):
        if node.caption is not None and node.caption.autonum:
            cap = node.caption
            node.caption = None
            try:
                orig_fig(self, parent, node)
            finally:
                node.caption = cap
            f = parent[-1] if len(parent) and parent[-1].tag == "fig" else None
            if f is None:       # formula_image
                return
            tmp = etree.Element("tmp")
            caption(self, tmp, cap)
            self.caption_more(tmp, node.caption_more)
            for k, ch in enumerate(list(tmp)):
                f.insert(k, ch)
            return
        orig_fig(self, parent, node)
    Bd.fig = fig

    def table_wrap(self, parent, node):
        if node.caption is not None and node.caption.autonum:
            cap = node.caption
            node.caption = None
            try:
                orig_tw(self, parent, node)
            finally:
                node.caption = cap
            tw = parent[-1]
            tmp = etree.Element("tmp")
            caption(self, tmp, cap)
            self.caption_more(tmp, node.caption_more)
            for k, ch in enumerate(list(tmp)):
                tw.insert(k, ch)
            return
        orig_tw(self, parent, node)
    Bd.table_wrap = table_wrap

    orig_span = E.Emitter.span

    # 後付けの見出し・英文要旨の見出し: <title> の中なら番号を先頭に（見出しのスタイルで sec になるものは sec が出す）
    def span(self, parent, para, ctx, start=0, end=None, seq=0, skip_gen=True):
        if (ctx is B.E.SECTITLE and parent.tag == "title" and start == 0 and getattr(para, "autonum", "")
                and parent.getparent() is not None and parent.getparent().tag != "sec"):
            b = self._builder
            b.autonum_mark(parent, para)
        return orig_span(self, parent, para, ctx, start, end, seq, skip_gen)
    E.Emitter.span = span

    orig_init = Bd.__init__

    def __init__(self, *a, **k):
        orig_init(self, *a, **k)
        self.em._builder = self
    Bd.__init__ = __init__

    def fn(self, fg, fnode):
        el = _sub(fg, "fn", id=fnode.fid)
        mark = ""
        if fnode.word_note:
            mark = self.plan.pdf_numbers.get(("fnlist", fnode.word_id), self.marks[fnode.word_id][1])
        elif fnode.paras and fnode.paras[0].autonum:
            mark = self.autonum(fnode.paras[0]).strip()
        for i, p in enumerate(fnode.paras):
            pe = _sub(el, "p")
            if i == 0 and mark:
                sep = "" if _starts_with_space(p) or unicodedata.east_asian_width(mark[-1]) in ("F", "W") else " "
                self.em.gen(pe, mark + sep, "footnote-mark" if fnode.word_note else "autonum",
                            None if fnode.word_note else p.src)
                if fnode.word_note:
                    self.autonum_mark(pe, p)
            else:
                self.autonum_mark(pe, p)
            self.em.span(pe, p, B.E.BACKP)
    Bd.fn = fn

    orig_meta = Bd.article_meta

    def article_meta(self, front):
        # 英文要旨の段落は autonum_mark=True で
        pf = Bd.paragraph_or_formula

        def pf2(self2, parent, p, ctx, autonum_mark=False):
            return pf(self2, parent, p, ctx, autonum_mark=autonum_mark or ctx is B.E.ABSTRACT)
        Bd.paragraph_or_formula = pf2
        try:
            orig_meta(self, front)
        finally:
            Bd.paragraph_or_formula = pf
    Bd.article_meta = article_meta


def lost_autonums(plan, root):
    """守り: XML に文字を出した段落のうち、自動番号があるのに番号（jx:gen kind autonum src=段落 ID）を出していないもの。"""
    shown = {g.get("src") for g in root.iter(GEN) if g.get("kind") == "autonum"}
    out, seen = [], set()
    for sp in root.iter(SPAN):
        src = sp.get("src")
        if src in seen:
            continue
        seen.add(src)
        p = plan.paras.get(src)
        if p is None or not (p.autonum or "").strip() or src in shown:
            continue
        if any(a.tag in NO_NUMBER_PLACES for a in sp.iterancestors()):
            continue
        out.append((src, p.autonum.strip(), "/".join(reversed([a.tag for a in sp.iterancestors() if isinstance(a.tag, str)
                                                               and not a.tag.startswith("{")][:3]))))
    return out


if __name__ == "__main__":
    install()
    HERE = Path(__file__).resolve().parent
    sys.path.insert(0, str(HERE))
    import jasme_jats.pipeline as P
    trees = []
    ob = B.build

    def build_spy(*a, **k):
        root, info = ob(*a, **k)
        trees.append(root)
        return root, info
    P.build = build_spy
    from jasme_jats.config import ArticleMeta, JournalConfig
    from jasme_jats.pipeline import AIRequiredError, Options, convert
    journal = JournalConfig.load()
    meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12", "pub_date": "2026-03-31",
                                  "received": "2025-06-01", "accepted": "2025-11-20", "peer_review": "あり",
                                  "keywords": "proof; 論証"})
    REPO = Path("/home/user/jstgxmlcng_JASME")
    docs = [HERE / "audit_out" / "audit.docx"] + sorted((REPO / "tests" / "fixtures").glob("*.docx")) \
        + sorted((REPO / "tests" / "private").glob("テスト*/*.docx")) + sorted((REPO / "tests" / "private" / "テンプレート").glob("*.docx"))
    runs = [(d, None) for d in docs]
    for folder in ("テストデータ1", "テストデータ2", "テストデータ3"):
        f = REPO / "tests" / "private" / folder
        for d in sorted(f.glob("*.docx")):
            runs.append((d, next(f.glob("*.pdf"))))
    for k, (d, pdf) in enumerate(runs):
        trees.clear()
        opts = dict(out_dir=HERE / "proto_out" / str(k), convert_metafiles=False, pdf_path=pdf, route="pdf" if pdf else "docx")
        try:
            res = convert(d, meta, journal, Options(**opts))
        except AIRequiredError:
            trees.clear()
            res = convert(d, meta, journal, Options(ai_mode="manual", **opts))
        root = trees[-1]
        lost = lost_autonums(res.plan, root)
        label = (d.parent.name if "private" in str(d) else d.stem) + ("/route2" if pdf else "")
        gens = sum(1 for g in root.iter(GEN) if g.get("kind") == "autonum")
        print(label, k, "fid", res.fidelity.ok, res.fidelity.final_ok, "dtd", res.dtd_valid, res.dtd_errors[:2],
              "sup", None if res.supplement is None else res.supplement.ok, "autonum gens", gens, "lost", lost)
