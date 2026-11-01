"""機械的なリンク付け（生成 AI は使わない）。

  図・表   : 本文中の「図1」「表2」「Figure 1」などを <xref ref-type="fig|table">。直前が漢字（前掲・乃至・及を除く）なら、
             語の一部（地図1・付表1・発表1回目）とみなしてリンクしない
  数式     : 「式(1)」「(1)式」を <xref ref-type="disp-formula">
  注       : 上付きの「1)」「注1」などを <xref ref-type="fn">。数字だけの上付きは、論文の注番号の書き方（Linker.bare_notes）と、
             指数・単位の形（cm²・x²・s⁻¹）かどうかで決める
  引用文献 : 著者・年方式の引用の「年」だけを <xref ref-type="bibr">（refparse.py）
  URL・DOI : そのままの文字列を <uri> / <ext-link> / <pub-id>

リンクはアトムの範囲に LinkSpec を付けるだけで、文字列は変えない。リンクにしなかった上付きの数字・語の中の図表番号は、その番号の
注・図表があれば、判断の一覧（Decision。applied=False）に記録する（レポートの 4 章と AI 依頼文の「推定:」に載る。要対応・要確認には
しない）。
"""
from __future__ import annotations

import re
import unicodedata
from typing import NamedTuple

from .model import OBJ, Atom, LinkSpec, Para
from .structure import ArticlePlan, BoxNode, FigNode, FormulaNode, ListNode, PNode, QuoteNode, Sec, TableNode

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
# 上付きの注番号（上付きの続きの中で finditer する。「1),2)」のように並ぶものも。「註」も認める）
RE_SUP_FN = re.compile(rf"(?:[注註][\s\u3000]*)?[(（]?[\s\u3000]*({NUM})[\s\u3000]*[)）]?")
# 数字と区切りだけの上付きの続き（「1-3」「1, 2」「1,2)」「注1・2」）。続き全体で、注番号か指数・単位かを決める（fullmatch で使う）
RE_SUP_LIST = re.compile(rf"[\s\u3000]*(?:[注註][\s\u3000]*)?[(（]?[\s\u3000]*{NUM}"
                         rf"(?:[\s\u3000]*[,，、・\-－–‐‑−~～〜][\s\u3000]*{NUM})+[\s\u3000]*[)）]?[\s\u3000]*")
RE_NUM_END = re.compile(rf"{NUM}[\s\u3000]*$")      # 上付きの続きが数字（と空白）で終わる
# 上付きの続きの先頭がこれなら指数（m s⁻¹ を Word で「s」＋上付きの「−1」と書いたもの。注番号は符号で始まらない）
SUP_SIGNS = "-−－‐‑–+＋±⁻⁺"
OPERATORS = "+-−－＋±×÷=＝<>＜＞≦≧≤≥^*/／"   # 上付きの続きの直前・直後がこれなら指数（x+²・(a)²+b）
RE_EXP_BEFORE = re.compile(r"[A-Za-zＡ-Ｚａ-ｚ0-9０-９α-ωΑ-Ω]")   # 直前がこれなら指数・単位（cm²・x²・10³・π²）
# 「図1」「表1」の直前に来てよい漢字（前掲図1・乃至図2・及表1）。ほかの漢字の直後は語の一部（地図1・付表1・発表1回目）
FLOAT_REF_OK_BEFORE = "掲至及"
RE_KANJI = re.compile(r"[\u3400-\u9fff々]")    # RE_FN_PLAIN の「注」の前の漢字と同じ範囲


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
    """リンク付けの対象となる段落を (para, 文脈) で列挙する。文脈: body / caption / cell / abstract / back / ref

    docx の表のセルの段落を表の外に出したもの（表のセルの画像とキャプションで組んだ図のキャプションと、画像と同じ段落の文字。
    plan.cell_paras）は、今までどおり cell とする（出版版 PDF との照合で、表のセルとして照合しない・直さない。pdfmatch）。
    囲み（文字だけのテキストボックス。BoxNode）の段落も cell とする（別行数式は formula。リンクは本文と同じく付ける。出版版 PDF
    との照合では、テキストボックスの段落として照合しない・ルート2 で直さない。0.24.1 と同じ扱い）。
    """
    cells = plan.cell_paras

    def walk(nodes, where="body"):
        for node in nodes:
            if isinstance(node, Sec):
                if node.heading is not None:
                    yield node.heading, "title"
                yield from walk(node.children, where)
            elif isinstance(node, PNode):
                yield node.para, "cell" if node.para.src in cells else where
            elif isinstance(node, (QuoteNode,)):
                for p in node.paras:
                    yield p, "cell" if p.src in cells else where
            elif isinstance(node, ListNode):
                for p in node.items:
                    yield p, "cell" if p.src in cells else where
            elif isinstance(node, FigNode):
                if node.caption is not None:
                    yield node.caption, "cell" if node.caption.src in cells else "caption"
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
            elif isinstance(node, BoxNode):
                yield from walk(node.children, "cell")
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
        # 番号だけの上付きの数字（「主張である¹」の ¹）を注番号とみなすか。論文ごとに run の note_style で決める
        # （run を通らずに fn_marks を呼んだときは、0.26.0 までと同じく注番号とみなす）
        self.bare_notes = True

    def note(self, category, src, msg, applied=True):
        """判断の一覧（レポートの 4 章）に記録する。リンクにしなかった判断は applied=False。"""
        self.plan.decide("mechanical", category, src, msg, applied=applied)

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
        if fn_ids:
            self.bare_notes = self.note_style(paras)
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
        """「図1」「表1、2」などを図・表へのリンクにする（regex は RE_FIGREF・RE_TABREF）。

        直前の文字が漢字で FLOAT_REF_OK_BEFORE（前掲・乃至・及）に入らなければ、語の一部（地図1・付表1・発表1回目・図表1）とみなして
        リンクせず、先頭の番号の直後から探し直す（並びの「、2」なども含めて飛ばすと、「図表1と表1」の後ろの「表1」まで落ちるため）。
        語の一部とみなした参照は、先頭の番号の図・表があるときだけ判断の一覧に記録する（applied=False。並びの番号は記録せず、
        図・表がなくても「見つからない」に出さない）。
        """
        plain = p.plain()
        pos = 0
        while (m := regex.search(plain, pos)) is not None:
            n = fw_int(m.group(2))
            s, e = m.start(1), m.end(2)
            prev = plain[s - 1] if s > 0 else ""
            if prev and RE_KANJI.match(prev) and prev not in FLOAT_REF_OK_BEFORE:
                if n in ids:
                    self._word_part(p, plain, s, e, prev, n, ids[n], ref_type, word)
                pos = e
                continue
            self._link_num(p, s, e, n, ids, ref_type, word, m.group(0))
            tail = m.group(3)
            if tail:
                base = m.start(3)
                for t in re.finditer(NUM, tail):
                    self._link_num(p, base + t.start(), base + t.end(), fw_int(t.group(0)), ids, ref_type, word,
                                   m.group(0))
            pos = m.end()

    def _word_part(self, p, plain, s, e, prev, n, rid, ref_type, word):
        """語の一部とみなしてリンクしなかった図・表の参照（plain[s:e]。「図1」）を、判断の一覧に記録する。"""
        text = plain[s:e]
        op = "link_figure" if ref_type == "fig" else "link_table"
        self.note("figure" if ref_type == "fig" else "table", p.src,
                  f"「{text}」は、直前の「{prev}」と続く語の一部（地図1・付表1 など）とみなし、{word} {rid} にリンクしなかった。"
                  f"{word}{n} への参照なら、AI による補完の {op}（text「{text}」、occurrence {occurrence_at(p, s, text)}）か、"
                  "XML の中で手作業でリンク（xref）を足す", applied=False)

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

    def note_style(self, paras) -> bool:
        """論文の注番号の書き方（bare_notes）: 番号だけの上付きの数字を注番号とみなすか。

        注番号を探す段落（引用文献・注の一覧の段落を除く。囲み・表のセル・キャプション・見出し・要旨・付記なども）の上付きの続きに、
        番号の形がはっきりした注番号（「注1」「1)」、上付きの「1」＋本文の「)」で指数の形でないもの。_sup_marks の strong）が
        1 つでもあれば偽（「1)」の書き方の論文）、なければ真（番号だけの論文）。直前が「注」の上付きの数字（after_note）と、
        指数・単位の形のもの（exponent）は数えない。"""
        for p, where in paras:
            if where in ("ref", "fn"):
                continue
            plain = p.plain()
            for s, e, text in _sup_runs(p):
                if any(mk.kind == "strong" for mk in _sup_marks(plain, s, e, text)):
                    return False
        return True

    def fn_marks(self, p: Para, fn_ids):
        """上付き文字の「1)」「注1」などを注へのリンクにする。

        番号の形がはっきりしたもの（strong）と、直前が「注」のもの（after_note）はリンクする。番号だけの上付きの数字（bare）は、
        論文の注番号の書き方が番号だけ（bare_notes）のときだけリンクする。指数・単位の形のもの（exponent。cm²・x²・s⁻¹）は
        リンクしない（種類は _sup_marks）。リンクしなかった数字は、その番号の注があるときだけ判断の一覧に記録する（applied=False。
        指数・単位は段落ごとに 1 件にまとめる。決定事項 15）。記録には、AI による補完の link_note の text（数字）と occurrence
        （段落の中で何回目か。find_in_para と同じ数え方）を書く（AI 依頼文の段落の一覧は、上付きかどうかを示さないため）。
        注のない番号は、指数・単位の形のものを除き、今までどおり「対応する注が見つからない」に出す。
        """
        if not fn_ids:
            return
        plain = p.plain()
        records = []        # (段落の中の位置, 文面)。段落の中の順に記録する
        exps = []           # 指数・単位の形の数字 (位置, 数字, 回目)。段落ごとに 1 件にまとめて記録する
        for s, e, text in _sup_runs(p):
            for mk in _sup_marks(plain, s, e, text):
                rid = fn_ids.get(mk.num)
                raw = plain[mk.start:mk.end]
                if rid is None:
                    if mk.kind != "exponent":      # 指数・単位の形のものは、注がなくても知らせない
                        self.unresolved.append(("fn", p.src, raw, f"上付きの「{raw}」に対応する注が見つからない"))
                    continue
                if mk.kind in ("strong", "after_note") or (mk.kind == "bare" and self.bare_notes):
                    if apply_span(p, mk.start, mk.end, LinkSpec(kind="xref", attrs={"ref-type": "fn", "rid": rid})):
                        self.count["fn"] += 1
                    continue
                digit = plain[mk.digit_start:mk.digit_end]
                k = occurrence_at(p, mk.digit_start, digit)
                if mk.kind == "exponent":
                    exps.append((mk.digit_start, digit, k))
                    continue
                records.append((mk.digit_start,
                                (f"上付きの数字「{digit}」（段落の中で {k} 回目の「{digit}」）は、番号だけの形なので注 {rid} に"
                                 "リンクしなかった（この論文の注番号は「1)」「注1」のように書かれている）。注番号なら、AI による"
                                 f"補完の link_note（text「{digit}」、occurrence {k}）か、XML の中で手作業でリンク（xref）を足す")))
        if exps:
            _, d0, k0 = exps[0]
            how = (f"text「{d0}」、occurrence {k0}" if len(exps) == 1 else
                   f"数字ごとに、text はその数字、occurrence はその回目。最初のものなら text「{d0}」、occurrence {k0}")
            records.append((exps[0][0],
                            (f"上付きの数字{'・'.join(f'「{d}」（{k} 回目）' for _, d, k in exps)}は、指数・単位（cm²・x² などの形）と"
                             "みなし、注にリンクしなかった（回目は、段落の中でその数字が現れる順）。注番号なら、AI による補完の"
                             f" link_note（{how}）か、XML の中で手作業でリンク（xref）を足す")))
        for _, msg in sorted(records, key=lambda r: r[0]):
            self.note("note", p.src, msg, applied=False)

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


def occurrence_at(p: Para, pos: int, text: str) -> int:
    """段落の plain() の pos から始まる text が、段落の中で何回目の text か（1 始まり。find_in_para と同じ数え方で、重なる一致も
    数える。AI の回答の occurrence にそのまま使える）。"""
    plain = p.plain()
    k, start = 0, -1
    while True:
        start = plain.find(text, start + 1)
        if start < 0 or start > pos:
            return max(k, 1)
        k += 1
        if start == pos:
            return k


class SupMark(NamedTuple):
    """上付きの続きの中の注番号の候補（位置は段落の plain() の上）。"""
    start: int          # リンクにする範囲（一致の前後の空白を除く）
    end: int
    num: int            # 番号
    kind: str           # strong / after_note / exponent / bare（_sup_marks）
    digit_start: int    # 番号の数字の範囲（記録の text と occurrence に使う）
    digit_end: int


def _sup_runs(p: Para) -> list:
    """上付きの文字のアトム（リンクのないもの）が続く範囲: [(plain の上の開始, 終了, 文字)]。

    リンクのあるアトム・数式・画像・Word の注の参照で切れる（0.26.0 までの fn_marks の区切りと同じ）。リンクを付けても plain は
    変わらないので、段落ごとに最初に 1 回求めればよい。"""
    out, cur = [], None
    for a, (a0, a1) in zip(p.atoms, atom_offsets(p)):
        if a.kind == "text" and "sup" in a.fmt and a.link is None:
            cur = (cur[0], a1, cur[2] + a.text) if cur is not None else (a0, a1, a.text)
        elif cur is not None:
            out.append(cur)
            cur = None
    if cur is not None:
        out.append(cur)
    return out


def _sign_first(text: str) -> bool:
    """上付きの続きが符号で始まるか（前の空白を除く。s⁻¹ の「−1」）。"""
    t = text.lstrip()
    return bool(t) and t[0] in SUP_SIGNS


def _exponent_like(plain: str, s: int, e: int, text: str) -> bool:
    """上付きの続き plain[s:e]（文字は text）が指数・単位の形か。

    続きの先頭が符号（s⁻¹）、直前の 1 文字が英字・数字・ギリシャ文字（cm²・x²・10³・π²）か演算の記号、直後の 1 文字が演算の記号
    （(a)²+b）なら真。前後の空白は飛ばさない（「3 cm」＋² の直前は m）。直前が漢字・かな・句読点・閉じ括弧・数式などなら、
    指数とみなさない（「（試験, 2024）²」は注番号の形）。"""
    if _sign_first(text):
        return True
    before = plain[s - 1] if s > 0 else ""
    after = plain[e] if e < len(plain) else ""
    if before and (RE_EXP_BEFORE.match(before) or before in OPERATORS):
        return True
    return bool(after) and after in OPERATORS


def _strong_mark(g: str) -> bool:
    """番号の形がはっきりした注番号か: 「注」「註」で始まる、または閉じ括弧で終わる（前後の空白を除く）。"""
    g = g.strip()
    return g.startswith(("注", "註")) or g.endswith((")", "）"))


def _sup_marks(plain: str, s: int, e: int, text: str) -> list:
    """上付きの続き plain[s:e]（文字は text）の中の注番号の候補（RE_SUP_FN の一致。空白だけのものを除く）: [SupMark]。

    種類（kind）:
      strong     : 番号の形がはっきりした注番号（_strong_mark）。続きが数字で終わり、直後の本文の文字が閉じ括弧で、指数・単位の形で
                   ないときの、最後の数字だけの一致も（上付きの「1」＋本文の「)」。上付きの外の文字で補う）
      after_note : 続きの直前が「注」「註」（本文の「注」＋上付きの「1」）。リンクするが、論文の書き方の判定（note_style）には使わない
      exponent   : 指数・単位の形（_exponent_like）。符号で始まる続きは、「−1)」のように閉じ括弧で終わっても、すべてこれ
      bare       : 番号だけ（論文の書き方が番号だけのときだけリンクする）
    優先は、符号で始まる続きの exponent ＞ strong ＞ after_note ＞ exponent ＞ bare。数字と区切りだけの続き（RE_SUP_LIST。「1-3」
    「1, 2」「1,2)」）は、続き全体の文字と前後で、すべての一致に同じ種類を付ける。"""
    ms = [m for m in RE_SUP_FN.finditer(text) if m.group(0).strip()]
    if not ms:
        return []
    sign = _sign_first(text)
    exp = _exponent_like(plain, s, e, text)
    after = plain[e] if e < len(plain) else ""
    tail_close = after in (")", "）") and not exp and RE_NUM_END.search(text) is not None
    note_before = plain[:s].rstrip().endswith(("注", "註"))

    def kind(g, last):
        if sign:
            return "exponent"
        if _strong_mark(g) or (last and tail_close):
            return "strong"
        if note_before:
            return "after_note"
        return "exponent" if exp else "bare"

    if RE_SUP_LIST.fullmatch(text):
        kinds = [kind(text, True)] * len(ms)
    else:
        kinds = [kind(m.group(0), i == len(ms) - 1) for i, m in enumerate(ms)]
    out = []
    for m, k in zip(ms, kinds):
        g = m.group(0)
        out.append(SupMark(s + m.start() + len(g) - len(g.lstrip()), s + m.end() - (len(g) - len(g.rstrip())),
                           fw_int(m.group(1)), k, s + m.start(1), s + m.end(1)))
    return out


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
