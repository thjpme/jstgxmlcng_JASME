"""機械的なリンク付け（生成 AI は使わない）。

  図・表   : 本文中の「図1」「表2」「Figure 1」などを <xref ref-type="fig|table">。「図」「表」の直前が漢字（前掲・乃至・及を
             除く）なら、語の一部（地図1・付表1・発表1回目）とみなしてリンクしない。同じ種類のキャプションの番号が重なる・キャプションに
             枝番がある（図1-1・図1-2）ときは、その番号の参照と、番号のすぐ後ろに枝番が続く参照（図1-2）をリンクしない（どの図か決め
             られない。plan.float_unlinked に記録し、要確認で知らせる）
  数式     : 「式(1)」「(1)式」を <xref ref-type="disp-formula">
  注       : 上付きの「1)」「注1」などを <xref ref-type="fn">。数字だけの上付きは、論文の注番号の書き方（Linker.bare_notes）と、
             指数・単位の形（cm²・x²・s⁻¹）かどうかで決める
  引用文献 : 著者・年方式の引用の「年」だけを <xref ref-type="bibr">（refparse.py）
  URL・DOI : そのままの文字列を <uri> / <ext-link> / <pub-id>

リンクはアトムの範囲に LinkSpec を付けるだけで、文字列は変えない。リンクにしなかった上付きの数字・語の中の図表番号は、その番号の
注・図表があれば、判断の一覧（Decision。applied=False）に記録する（レポートの 4 章と AI 依頼文の「推定:」に載る。要対応・要確認には
しない。ただし、番号が重なる・枝番のある図・表の参照をリンクしなかったものは、誤ったリンクを出さないための判断なので、要確認で知らせる。
report._float_ref_action）。
"""
from __future__ import annotations

import re
import unicodedata
from typing import NamedTuple

from .article import (ArticlePlan, BoxNode, FigNode, FormulaNode, ListNode, PNode, QuoteNode, Sec, TableNode,
                      UnlinkedRef)
from .model import OBJ, Atom, LinkSpec, Para
from .structure import CAP_BRANCH_NUM, CAP_BRANCH_SEP, RE_FIGCAP, RE_TABCAP, caption_label

# URL（末尾の句読点・閉じ括弧は含めない）
RE_URL = re.compile(r"(?:https?://|www\.)[^\s<>\"'「」『』、。，（）［］【】〔〕\u3000]+", re.I)
RE_DOI_PREFIXED = re.compile(r"(?:\bdoi\s*[:：]\s*|DOI\s*[:：]?\s*)(10\.\d{4,9}/[^\s<>\"、。，（）「」]+)", re.I)
RE_DOI_BARE = re.compile(r"(?<![\w/.])(10\.\d{4,9}/[^\s<>\"、。，（）「」]+)")
FW = str.maketrans("０１２３４５６７８９", "0123456789")
NUM = r"[0-9０-９]+"
RE_FIGREF = re.compile(rf"(図|Figure|Figs?\.)[\s\u3000]?({NUM})((?:[\s\u3000]*(?:[,，、・]|～|〜|-|－|–|と|及び|および|and)[\s\u3000]*(?:図)?{NUM})*)")
RE_TABREF = re.compile(rf"(表|Tables?)[\s\u3000]?({NUM})((?:[\s\u3000]*(?:[,，、・]|～|〜|-|－|–|と|及び|および|and)[\s\u3000]*(?:表)?{NUM})*)")
RE_EQREF = re.compile(rf"式[\s\u3000]?([(（][\s\u3000]*{NUM}(?:[.．\-－]{NUM})?[\s\u3000]*[)）])|([(（][\s\u3000]*{NUM}(?:[.．\-－]{NUM})?[\s\u3000]*[)）])[\s\u3000]?式")
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
# 上付きの続きの直前・直後がこれなら指数（10−³ の「−」を本文の大きさで書いたもの・(a+b)²+c）。四則などの演算の記号
OPERATORS = "+-−－＋±×÷^*/／"
# 上付きの続きの直後だけで指数とみなす比較の記号（x²＜4・x²=1）。直前には使わない（比較の記号の直後に指数は来ず、全角の「＜」「＞」は
# 「＜用語＞¹」のように日本語の括弧としても使うため）
COMPARISONS = "=＝<>＜＞≦≧≤≥"
# 直前がこれなら指数・単位（cm²・x²・10³・π²）。英字・数字（全角も）・ギリシャ文字と、単位の記号（µ〈マイクロ記号〉・Å・′〈プライム〉、
# 全角の単位の記号 U+3380〜U+33DF の ㎝・㎜・㎞・㎏ など。12㎝²・x′²）。図・表の参照の番号の数字（「図1¹」）は除く（_exponent_like）
RE_EXP_BEFORE = re.compile(r"[A-Za-zＡ-Ｚａ-ｚ0-9０-９α-ωΑ-Ωµ\u00c5\u212b\u2032\u3380-\u33df]")
# 「図1」「表1」の直前に来てよい漢字（前掲図1・乃至図2・及表1）。ほかの漢字の直後は語の一部（地図1・付表1・発表1回目）
FLOAT_REF_OK_BEFORE = "掲至及"
RE_KANJI = re.compile(r"[\u3400-\u9fff々]")    # RE_FN_PLAIN の「注」の前の漢字と同じ範囲
# 図・表の参照の番号のすぐ後ろの枝番（「図1-2」「図2.1」。キャプションの枝番〈structure.RE_CAP_BRANCH〉と同じ区切り・同じ枝番の数字 CAP_BRANCH_NUM）
RE_BRANCH_REF = re.compile(rf"[{CAP_BRANCH_SEP}]{CAP_BRANCH_NUM}")


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
    """リンク付けの対象となる段落を (para, 文脈) で列挙する。文脈: body / title（見出し）/ caption / cell / formula / abstract / back / fn / ref

    docx の表のセルの段落を表の外に出したもの（表のセルの画像とキャプションで組んだ図のキャプションと、画像と同じ段落の文字。
    plan.cell_paras）は、今までどおり cell とする（出版版 PDF との照合で、表のセルとして照合しない・直さない。pdfmatch）。
    図・表のキャプションの 2 段落目以降（caption_more。出典の行など）も、キャプションと同じ文脈 caption で返す（引用・URL・注番号を
    リンクにし、出版版 PDF との照合にも入れる）。
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
                for p in node.caption_more:
                    yield p, "cell" if p.src in cells else "caption"
                for t in node.tables:
                    for p in t.paragraphs():
                        yield p, "cell"
            elif isinstance(node, TableNode):
                if node.caption is not None:
                    yield node.caption, "caption"
                for p in node.caption_more:
                    yield p, "cell" if p.src in cells else "caption"
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
        # 図・表のキャプションの番号が重なるとき、枝番があるときは、その番号の参照をリンクしない（float_numbers）
        fig_ids, fig_skip, fig_branch = self.float_numbers(plan.figures, RE_FIGCAP, "fid", "図")
        tab_ids, tab_skip, tab_branch = self.float_numbers(plan.tables, RE_TABCAP, "tid", "表")
        eq_ids = {}
        for f in plan.formulas:
            if f.fid and f.label:
                eq_ids[re.sub(r"[\s\u3000()（）]", "", unicodedata.normalize("NFKC", f.label))] = f.fid
        fn_ids = {fn.number: fn.fid for fn in plan.fns if fn.number is not None and not fn.word_note}
        captions = {id(f.caption) for f in plan.figures if f.caption is not None} | \
                   {id(t.caption) for t in plan.tables if t.caption is not None} | \
                   {id(q) for f in plan.figures for q in f.caption_more} | {id(q) for t in plan.tables for q in t.caption_more}
        if fn_ids:
            self.bare_notes = self.note_style(paras)
        for p, where in paras:
            if where == "ref":
                continue
            if id(p) not in captions:
                self.float_refs(p, RE_FIGREF, fig_ids, "fig", "図", fig_skip, fig_branch)
                self.float_refs(p, RE_TABREF, tab_ids, "table", "表", tab_skip, tab_branch)
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

    def float_numbers(self, nodes, regex, id_attr: str, word: str) -> tuple:
        """図または表の参照のリンク先を、キャプションの番号から決める: (番号 -> ID, リンクしない番号 -> (キャプションの冒頭の一覧,
        枝番つきのキャプションがあるか), 枝番つきのキャプションが 1 つでもあるか)。

        同じ種類のキャプションの番号が重なる（図1・図1。図1-1・図1-2 は枝番を読まないと両方「図1」）番号と、枝番つきのキャプション
        〈structure.caption_label〉の番号（整数部分。図2.1 の「2」）は、どのキャプションへの参照か決められないので、リンク先にせず
        リンクしない番号（float_refs が記録して要確認で知らせる）にする。枝番つきのキャプションが 1 つでもあるときは、その種類の
        参照の「図1-2」を範囲とは読まない（float_refs の branch）。"""
        caps = {}
        for node in nodes:
            if node.number is None or not getattr(node, id_attr):
                continue
            n, branch = caption_label(node.caption, regex) if node.caption is not None else (None, False)
            caps.setdefault(node.number if n is None else n, []).append((node, branch))
        ids, skip = {}, {}
        for n, items in caps.items():
            if len(items) > 1 or any(branch for _, branch in items):
                heads = [(_para_head(node.caption) if node.caption is not None else getattr(node, id_attr))
                         for node, _ in items]
                skip[n] = (heads, any(branch for _, branch in items))
            else:
                ids[n] = getattr(items[0][0], id_attr)
        return ids, skip, any(branch for items in caps.values() for _, branch in items)

    def float_refs(self, p: Para, regex, ids, ref_type, word, skip=None, branch=False):
        """「図1」「表1、2」などを図・表へのリンクにする（regex は RE_FIGREF・RE_TABREF）。

        「図」「表」の直前の文字が漢字で FLOAT_REF_OK_BEFORE（前掲・乃至・及）に入らなければ、語の一部（地図1・付表1・発表1回目・
        図表1）とみなしてリンクせず、先頭の番号の直後から探し直す（並びの「、2」なども含めて飛ばすと、「図表1と表1」の後ろの「表1」
        まで落ちるため）。英語の参照（Figure・Fig.・Table）は日本語の語の一部にならないので、直前の文字を見ない（「実験結果Fig. 1」も
        リンクする）。語の一部とみなした参照は、先頭の番号の図・表があるときだけ判断の一覧に記録する（applied=False。並びの番号は記録
        せず、図・表がなくても「見つからない」に出さない）。
        番号の数字が途中から上付きの文字になるとき（「図1」の直後に上付きの注番号「1)」が続くと、plain() では「図11)」になる）は、
        参照を上付きの手前で切る（番号が上付きの文字で始まるときは切らない）。上付きの文字は fn_marks の規則で扱う（図・表の番号の
        直後なので、直前の数字を指数の底とはみなさない〈_exponent_like〉。「1)」などの形なら注番号で、番号だけの数字は論文の注番号の
        書き方による）。先頭の番号の途中で切ったときは、上付きの文字の後ろの並びの番号（「図1¹、2」の「、2」）はリンクしない（「図1¹と
        図2」の「図2」は、上付きの手前から探し直すので、次の参照としてリンクする）。
        skip・branch は float_numbers の結果で、番号が skip にある参照はリンクしない。branch が真（枝番つきのキャプションがある論文）
        のときは、番号のすぐ後ろに枝番の形（RE_BRANCH_REF。「図1-2」「図2.1」）が続く参照を、範囲（図1〜図2）ではなく 1 つの枝番の
        参照とみなして、リンクしない。リンクしなかった参照は _unlinked が判断の一覧と plan.float_unlinked に記録する。
        """
        skip = skip or {}
        plain = p.plain()
        sup = _sup_chars(p)
        pos = 0
        while (m := regex.search(plain, pos)) is not None:
            end = _before_sup(sup, m.start(2), m.end())      # 参照の終わり（上付きの手前で切ったもの）
            s, e = m.start(1), min(m.end(2), end)
            n = fw_int(plain[m.start(2):e])
            prev = plain[s - 1] if s > 0 else ""
            if m.group(1) in ("図", "表") and prev and RE_KANJI.match(prev) and prev not in FLOAT_REF_OK_BEFORE:
                if n in ids:
                    self._word_part(p, plain, s, e, prev, n, ids[n], ref_type, word)
                pos = e
                continue
            # 番号の並び: [(開始, 終了)]。先頭の番号の途中で切ったときは plain[base:end] が空になり、並びの番号はリンクしない
            nums = [(m.start(2), e)]
            if m.group(3):
                base = m.start(3)
                nums += [(base + t.start(), base + t.end()) for t in re.finditer(NUM, plain[base:end])]
            context = plain[s:end]
            last, skip_next = end, False
            for k, (a, b) in enumerate(nums):
                if skip_next:
                    skip_next = False       # 直前の枝番つきの参照の、枝番の数字
                    continue
                n = fw_int(plain[a:b])
                start = s if k == 0 else (a - 1 if plain[a - 1:a] == word else a)
                br = RE_BRANCH_REF.match(plain, b) if branch else None
                if br is not None and any(i in sup for i in range(br.start(), br.end())):
                    br = None
                if br is not None:
                    skip_next = k + 1 < len(nums) and nums[k + 1][0] == br.start() + 1
                    last = max(last, br.end())
                    self._unlinked(p, plain, start, br.end(), n, ref_type, word, skip, branched=True)
                elif n in skip:
                    self._unlinked(p, plain, start, b, n, ref_type, word, skip)
                else:
                    self._link_num(p, s if k == 0 else a, b, n, ids, ref_type, word, context)
            pos = last

    def _unlinked(self, p, plain, s, e, n, ref_type, word, skip, branched=False):
        """番号からどの図・表か決められず、リンクしなかった参照（plain[s:e]。「図1」「図1-2」）を、判断の一覧（applied=False）と
        plan.float_unlinked に記録する（要確認で知らせる。report の _float_ref_action）。n は参照の番号（枝番の前の整数）。"""
        text = plain[s:e]
        heads, has_branch = skip.get(n, ([], False))
        caps = "、".join(f"「{h}」" for h in heads[:3]) + ("ほか" if len(heads) > 3 else "")
        if branched:
            why = (f"番号のすぐ後ろに枝番が続く形なので、枝番つきの{word}の参照とみなし（この論文には枝番つきの{word}のキャプションが"
                   f"ある）、{word}{n} から続く範囲とは読まず、どの{word}か決められないので")
        elif has_branch:
            why = f"{word}{n} のキャプションに枝番がある（{caps}）ので、どの枝番の{word}への参照か決められず"
        else:
            why = f"{word}{n} のキャプションが複数ある（{caps}）ので、どの{word}への参照か決められず"
        op = "link_figure" if ref_type == "fig" else "link_table"
        self.note("figure" if ref_type == "fig" else "table", p.src,
                  f"「{text}」は、{why}、リンクしなかった。手で確かめ、リンクが必要なら、AI による補完の {op}（text「{text}」、"
                  f"occurrence {occurrence_at(p, s, text)}）でリンクできる", applied=False)
        self.plan.float_unlinked.append(UnlinkedRef(word, p.src, text, s, e))

    def _word_part(self, p, plain, s, e, prev, n, rid, ref_type, word):
        """語の一部とみなしてリンクしなかった図・表の参照（plain[s:e]。「図1」）を、判断の一覧に記録する。"""
        text = plain[s:e]
        op = "link_figure" if ref_type == "fig" else "link_table"
        self.note("figure" if ref_type == "fig" else "table", p.src,
                  f"「{text}」は、直前の「{prev}」と続く語の一部（地図1・付表1 など）とみなし、{word} {rid} にリンクしなかった。"
                  f"{word}{n} への参照なら、AI による補完の {op}（text「{text}」、occurrence {occurrence_at(p, s, text)}）で"
                  "リンクできる", applied=False)

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
        上付きの文字だけで番号の形がはっきりした注番号（「注1」「註1」「1)」。_sup_marks の shaped）が 1 つでもあれば偽（「1)」の
        書き方の論文）、なければ真（番号だけの論文）。上付きの「1」＋本文の「)」（strong だが shaped は偽）は数えない（番号だけの
        論文の「（…である³）」のように、本文の閉じ括弧は文の括弧のこともあるため。暫定）。直前が「注」の上付きの数字（after_note）と、
        指数・単位の形のもの（exponent）も数えない。"""
        for p, where in paras:
            if where in ("ref", "fn"):
                continue
            plain = p.plain()
            for s, e, text in _sup_runs(p):
                if any(mk.shaped for mk in _sup_marks(plain, s, e, text)):
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
        exps = []           # 指数・単位の形の数字 (位置, 数字, 回目, 注の ID)。段落ごとに 1 件にまとめて記録する
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
                    exps.append((mk.digit_start, digit, k, rid))
                    continue
                msg = (f"上付きの「{digit}」は、番号だけの形なので注 {rid} にリンクしなかった（この論文の注番号は「1)」「注1」の"
                       f"形）。注番号なら、AI による補完の link_note（text「{digit}」、occurrence {k}）でリンクできる")
                records.append((mk.digit_start, msg))
        if exps:
            # 利用者向けの前半は短くし（同じ数字は 1 回だけ書いて件数を添える。x²+y² は「「2」（2 か所）」）、AI 向けの text と
            # occurrence は数字ごとに書く（occurrence は段落の中の同じ文字の何回目かで、上付きの何番目かではないので、利用者向けの
            # 文には出さない）
            seen = {}
            for _, d, _, _ in exps:
                seen[d] = seen.get(d, 0) + 1
            nums = "".join(f"「{d}」" + (f"（{c} か所）" if c > 1 else "") for d, c in seen.items())
            rids = "・".join(dict.fromkeys(r for _, _, _, r in exps))
            ops = "／".join(f"text「{d}」、occurrence {k}" for _, d, k, _ in exps)
            msg = (f"上付きの{nums}は、指数・単位（cm²・x² などの形）とみなし、注 {rids} にリンクしなかった。注番号なら、"
                   f"AI による補完の link_note（{ops}）でリンクできる")
            records.append((exps[0][0], msg))
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


def _para_head(p: Para) -> str:
    """キャプションの冒頭（判断の一覧に書く目印。先頭の 12 文字）。"""
    return p.plain().strip()[:12]


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
    shaped: bool        # 上付きの文字だけで番号の形がはっきりしている（_strong_mark）。論文の書き方の判定（note_style）に使う
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


def _sup_chars(p: Para) -> set:
    """段落の plain() の上で、上付きの文字のアトムにある位置の集まり（リンクの有無は問わない）。"""
    out = set()
    for a, (a0, a1) in zip(p.atoms, atom_offsets(p)):
        if a.kind == "text" and "sup" in a.fmt:
            out.update(range(a0, a1))
    return out


def _before_sup(sup: set, s: int, e: int) -> int:
    """plain[s:e]（図・表の参照の番号から後ろ）が途中から上付きの文字になるなら、その位置。ならない、または s から上付きなら e。"""
    if s in sup:
        return e
    return next((k for k in range(s + 1, e) if k in sup), e)


def _sign_first(text: str) -> bool:
    """上付きの続きが符号で始まるか（前の空白を除く。s⁻¹ の「−1」）。"""
    t = text.lstrip()
    return bool(t) and t[0] in SUP_SIGNS


def _exponent_like(plain: str, s: int, e: int, text: str) -> bool:
    """上付きの続き plain[s:e]（文字は text）が指数・単位の形か。

    続きの先頭が符号（s⁻¹）、直前の 1 文字が英字・数字・ギリシャ文字・単位の記号（cm²・x²・10³・π²・12㎝²。RE_EXP_BEFORE）か
    演算の記号（OPERATORS）、直後の 1 文字が演算の記号か比較の記号（(a+b)²+c・x²＜4。COMPARISONS）なら真。前後の空白は飛ばさない
    （「3 cm」＋² の直前は m）。直前が漢字・かな・句読点・括弧（「＜用語＞¹」の「＞」も）・数式などなら、指数とみなさない
    （「（試験, 2024）²」は注番号の形）。直前の数字が図・表の参照の番号の終わり（「図1¹」「表2³」「Fig. 2¹」「図1、2³」、キャプションの
    「図1²」。_after_float_ref）なら、直前の文字では指数とみなさない（図表の番号は指数の底ではない。番号だけの論文では、0.26.0 と同じく
    注にリンクする）。"""
    if _sign_first(text):
        return True
    before = plain[s - 1] if s > 0 else ""
    after = plain[e] if e < len(plain) else ""
    if before and (RE_EXP_BEFORE.match(before) or before in OPERATORS) and not _after_float_ref(plain, s):
        return True
    return bool(after) and (after in OPERATORS or after in COMPARISONS)


def _after_float_ref(plain: str, s: int) -> bool:
    """上付きの続きの手前の文字 plain[:s] が、図・表の参照の番号で終わるか（float_refs と同じ RE_FIGREF・RE_TABREF の形。「図1」
    「表2」「Fig. 2」「図1、2」。語の一部とみなす「地図1」、キャプションの先頭の「図1」も）。"""
    if s == 0 or not re.match(NUM, plain[s - 1]):
        return False
    head = plain[:s]
    return any(m.end() == s for rx in (RE_FIGREF, RE_TABREF) for m in rx.finditer(head))


def _strong_mark(g: str) -> bool:
    """番号の形がはっきりした注番号か: 「注」「註」で始まる、または閉じ括弧で終わる（前後の空白を除く）。"""
    g = g.strip()
    return g.startswith(("注", "註")) or g.endswith((")", "）"))


def _sup_marks(plain: str, s: int, e: int, text: str) -> list:
    """上付きの続き plain[s:e]（文字は text）の中の注番号の候補（RE_SUP_FN の一致。空白だけのものを除く）: [SupMark]。

    種類（kind）:
      strong     : 番号の形がはっきりした注番号（_strong_mark。shaped が真）。続きが数字で終わり、直後の本文の文字が閉じ括弧で、
                   指数・単位の形でないときの、最後の数字だけの一致も（上付きの「1」＋本文の「)」。上付きの外の文字で補う。リンクは
                   するが、本文の閉じ括弧は文の括弧〈「（…である³）」〉のこともあるので shaped は偽で、論文の書き方の判定には使わない）
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
        """(種類, shaped)"""
        if sign:
            return "exponent", False
        if _strong_mark(g):
            return "strong", True
        if last and tail_close:
            return "strong", False
        if note_before:
            return "after_note", False
        return ("exponent" if exp else "bare"), False

    if RE_SUP_LIST.fullmatch(text):
        kinds = [kind(text, True)] * len(ms)
    else:
        kinds = [kind(m.group(0), i == len(ms) - 1) for i, m in enumerate(ms)]
    out = []
    for m, (k, shaped) in zip(ms, kinds):
        g = m.group(0)
        out.append(SupMark(s + m.start() + len(g) - len(g.lstrip()), s + m.end() - (len(g) - len(g.rstrip())),
                           fw_int(m.group(1)), k, shaped, s + m.start(1), s + m.end(1)))
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
