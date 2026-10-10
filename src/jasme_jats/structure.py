"""段落の役割（見出し・本文・図表・文献など）を決め、論文の構造（ArticlePlan）を組み立てる。

役割は原則として Word のスタイル名で決める（config の [styles]）。
スタイルが想定外の段落には、番号の形式などから機械的に推定した役割を与え、
推定したことを Decision として記録する（レポートと AI 補完の対象になる）。
構造の組み立ては文字列を一切変更しない。出力しない段落は Exclusion として必ず記録する。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

from .model import Decision, Exclusion, Para, Table
from .ooxml import is_ws

BODY_ROLES = {"sec1", "sec2", "sec3", "p", "fig_caption", "table_caption", "quote", "fn"}
FRONT_JA_ROLES = {"title", "subtitle", "aff_ja", "author_ja"}
FRONT_EN_ROLES = {"title_en", "subtitle_en", "author_en", "aff_en", "abstract_heading", "abstract"}
BACK_HEADINGS = {"notes_heading": "notes", "ack_heading": "ack", "fn_heading": "fn", "ref_heading": "refs"}
HEADING_LEVEL = {"sec1": 1, "sec2": 2, "sec3": 3}

# 想定外スタイルの段落から役割を推定する規則
RE_HEAD1 = re.compile(r"^[0-9０-９]{1,2}[．.](?![0-9０-９])\s*\S.{0,40}$")
RE_HEAD2 = re.compile(r"^[(（][0-9０-９]{1,2}[)）]\s*\S.{0,40}$")
RE_HEAD3 = re.compile(r"^[①-⑳]\s*\S.{0,40}$")
RE_FIGCAP = re.compile(r"^(?:図|Figure|Fig\.?)\s*([0-9０-９]+)")
RE_TABCAP = re.compile(r"^(?:表|Table)\s*([0-9０-９]+)")
RE_FORMULA_LABEL = re.compile(r"^[\s\u3000]*([(（][\s\u3000]*[0-9０-９]+(?:[.．\-－][0-9０-９]+)?[\s\u3000]*[)）])[\s\u3000]*$")
RE_NOTE_MARK = re.compile(r"^[\s\u3000]*((?:注[\s\u3000]*)?[(（]?[\s\u3000]*([0-9０-９]{1,3})[\s\u3000]*[)）])")
RE_REF_HEADING_TEXT = re.compile(r"^\s*(?:引用(?:・|及び|および)?参考文献|参考(?:・|及び|および)?引用文献|引用文献|参考文献|文献"
                                 r"|References?|REFERENCES?|Bibliography)\s*$")
RE_ACK_TEXT = re.compile(r"^\s*(?:謝辞|Acknowledge?ments?)\s*$")
RE_NOTES_TEXT = re.compile(r"^\s*付記\s*$")
RE_FN_TEXT = re.compile(r"^\s*(?:注|注釈|Notes?)\s*$")
RE_APPENDIX = re.compile(r"^[\s\u3000]*(?:資料|付録|附録|Appendix)(?:[\s\u3000]*[0-9０-９A-ZＡ-Ｚ]+)?(?=[\s\u3000:：]|$)")


def nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


def num_of(s: str) -> Optional[int]:
    try:
        return int(nfkc(s))
    except ValueError:
        return None


# ----------------------------------------------------------------------------- nodes
@dataclass(eq=False)
class Sec:
    level: int
    heading: Optional[Para]
    children: list = field(default_factory=list)
    sid: str = ""


@dataclass(eq=False)
class PNode:
    para: Para


@dataclass(eq=False)
class ListNode:
    items: list
    ordered: bool = True


@dataclass(eq=False)
class QuoteNode:
    paras: list


@dataclass(eq=False)
class FigNode:
    image_paras: list
    caption: Optional[Para] = None
    caption_more: list = field(default_factory=list)   # 2 段落目以降のキャプション
    fid: str = ""
    number: Optional[int] = None
    formula: object = None        # AI が数式画像と判断した場合に読み取った MathML（mml:math 要素）
    formula_decision: str = ""


@dataclass(eq=False)
class TableNode:
    table: Optional[Table]
    caption: Optional[Para] = None
    caption_more: list = field(default_factory=list)
    tid: str = ""
    number: Optional[int] = None


@dataclass(eq=False)
class FormulaNode:
    para: Para
    fid: str = ""
    label: str = ""               # "(1)" など（本文中の文字列）
    label_range: tuple = None     # para.plain() 上の位置


@dataclass(eq=False)
class FnNode:
    paras: list
    fid: str = ""
    number: Optional[int] = None
    mark_range: tuple = None      # 先頭の「1)」の位置（para.plain() 上）
    word_note: bool = False       # Word の脚注機能による注
    word_id: str = ""


@dataclass(eq=False)
class RefNode:
    para: Para
    rid: str = ""
    parsed: dict = field(default_factory=dict)


@dataclass(eq=False)
class BackSec:
    heading: Optional[Para]
    children: list = field(default_factory=list)


@dataclass(eq=False)
class AppNode:
    title: Optional[Para]
    children: list = field(default_factory=list)


@dataclass(eq=False)
class Author:
    name_ja: Optional[Para] = None
    name_en: Optional[Para] = None
    affs: list = field(default_factory=list)      # Aff
    split_ja: Optional[int] = None                 # 姓と名の境目（AI 補完で指定された場合）
    split_en: Optional[int] = None


@dataclass(eq=False)
class Aff:
    ja: Optional[Para] = None
    en: Optional[Para] = None
    aid: str = ""


@dataclass
class ArticlePlan:
    lang: str = "ja"
    title: list = field(default_factory=list)
    subtitle: list = field(default_factory=list)
    title_en: list = field(default_factory=list)
    subtitle_en: list = field(default_factory=list)
    authors: list = field(default_factory=list)
    affs: list = field(default_factory=list)
    abstract_heading: Optional[Para] = None
    abstract: list = field(default_factory=list)
    body: list = field(default_factory=list)
    notes: Optional[BackSec] = None
    ack: Optional[BackSec] = None
    fn_heading: Optional[Para] = None
    fns: list = field(default_factory=list)
    ref_heading: Optional[Para] = None
    refs: list = field(default_factory=list)
    apps: list = field(default_factory=list)
    exclusions: list = field(default_factory=list)
    decisions: list = field(default_factory=list)
    figures: list = field(default_factory=list)
    tables: list = field(default_factory=list)
    formulas: list = field(default_factory=list)
    paras: dict = field(default_factory=dict)        # src -> Para
    locations: dict = field(default_factory=dict)    # src -> 人が読める位置
    region: dict = field(default_factory=dict)       # src -> front_ja / body / notes / ack / fn / refs / front_en / app
    citation_mode: str = ""                          # author-year / numeric（refparse が設定）
    uncited_refs: list = field(default_factory=list) # 本文からリンクされていない文献の ID

    def decide(self, stage, category, src, message, confidence="", applied=True) -> Decision:
        n = sum(1 for x in self.decisions if x.stage == stage) + 1
        d = Decision(did=f"{'M' if stage == 'mechanical' else 'A'}-{n:03d}", stage=stage,
                     category=category, src=src, message=message, confidence=confidence,
                     location=self.locations.get(src, ""), applied=applied)
        self.decisions.append(d)
        return d

    def exclude(self, para: Para, reason: str):
        text = _para_text(para)
        self.exclusions.append(Exclusion(src=para.src, reason=reason, text=text))


def _para_text(para: Para) -> str:
    return "".join(a.text for a in para.atoms if a.kind == "text")


# ----------------------------------------------------------------------------- roles
class Classifier:
    def __init__(self, doc, journal, overrides=None):
        self.doc = doc
        self.journal = journal
        self.mapping = journal.styles
        self.overrides = overrides or {}      # src -> role（AI 補完）
        self.plan = ArticlePlan(lang=journal.lang)

    def style_role(self, para: Para) -> Optional[str]:
        sid = para.style_id
        seen = set()
        while sid and sid not in seen:
            seen.add(sid)
            st = self.doc.styles.get(sid)
            if st is None:
                break
            if st.name in self.mapping:
                return self.mapping[st.name]
            sid = st.based_on
        return None

    def role_of(self, para: Para) -> str:
        if para.src in self.overrides:
            para.role_origin = "ai"
            return self.overrides[para.src]
        r = self.style_role(para)
        para.role_origin = "style" if r and r != "normal" else ""
        return r or "normal"

    # 推定の補助
    @staticmethod
    def all_bold(para: Para) -> bool:
        texts = [a for a in para.atoms if a.kind == "text" and a.text.strip()]
        return bool(texts) and all("bold" in a.fmt for a in texts)

    def guess_heading(self, para: Para, strict: bool) -> Optional[str]:
        t = _para_text(para).strip()
        if not t or "。" in t or any(a.kind != "text" for a in para.atoms):
            return None
        if strict and not self.all_bold(para):
            return None
        if RE_HEAD1.match(t):
            return "sec1"
        if RE_HEAD2.match(t):
            return "sec2"
        if RE_HEAD3.match(t):
            return "sec3"
        return None

    # ----------------------------------------------------------------- main
    def run(self) -> ArticlePlan:
        plan = self.plan
        flat = []   # (block, role)
        for b in self.doc.blocks:
            if isinstance(b, Table):
                flat.append((b, "table"))
                for p in b.paragraphs():
                    plan.paras[p.src] = p
            else:
                plan.paras[b.src] = b
                flat.append((b, self.role_of(b)))
        for notes in (self.doc.footnotes, self.doc.endnotes):
            for paras in notes.values():
                for p in paras:
                    plan.paras[p.src] = p

        kept = []
        for b, role in flat:
            if role == "exclude":
                plan.exclude(b, "AI 補完で、論文の本文ではない（テンプレートの装飾など）と判断")
                plan.region[b.src] = "excluded"
                continue
            kept.append((b, role))
        flat = kept
        regions = self.split_regions(flat)
        self.build_front_ja(regions["front_ja"])
        self.build_body(regions["body"])
        self.build_back(regions["back"])
        self.build_front_en(regions["front_en"])
        self.attach_word_notes()
        self.assign_ids()
        return plan

    def table_roles(self, t: Table) -> set:
        return {self.role_of(p) for p in t.paragraphs()}

    def split_regions(self, flat):
        regions = {"front_ja": [], "body": [], "back": [], "front_en": []}
        state = "front_ja"
        seen_title = False
        for b, role in flat:
            troles = self.table_roles(b) if isinstance(b, Table) else set()
            if role in FRONT_EN_ROLES or troles & {"author_en", "aff_en"}:
                state = "front_en"
            elif state == "front_ja":
                if role in FRONT_JA_ROLES or troles & FRONT_JA_ROLES:
                    seen_title = seen_title or role == "title"
                elif role in BODY_ROLES and not (role == "p" and b.is_blank):
                    state = "body"
                elif role in BACK_HEADINGS:
                    state = "back"
                elif role == "normal" and isinstance(b, Para) and self.guess_heading(b, strict=False):
                    state = "body"
                elif isinstance(b, Table) and seen_title and not troles & FRONT_JA_ROLES:
                    state = "body"
            elif state == "body":
                if role in BACK_HEADINGS or (isinstance(b, Para) and self.back_heading_by_text(b, role)):
                    state = "back"
            regions[state].append((b, role))
            if state == "front_ja" and isinstance(b, Para) and b.section_break and seen_title:
                state = "body"
        return regions

    def back_heading_by_text(self, para: Para, role: str) -> Optional[str]:
        """スタイル違反の後付け見出し（「引用文献」を章見出しスタイルで書いた等）をテキストから推定。"""
        if role not in ("sec1", "normal", "p"):
            return None
        t = nfkc(_para_text(para)).strip()
        if RE_REF_HEADING_TEXT.match(t):
            return "ref_heading"
        if RE_ACK_TEXT.match(t):
            return "ack_heading"
        if RE_NOTES_TEXT.match(t):
            return "notes_heading"
        if RE_FN_TEXT.match(t):
            return "fn_heading"
        return None

    # ----------------------------------------------------------------- front (ja)
    def build_front_ja(self, items):
        plan = self.plan
        for b, role in items:
            if isinstance(b, Table):
                if self.table_roles(b) & {"aff_ja", "author_ja"}:
                    self.read_author_table_ja(b)
                else:
                    for p in b.paragraphs():
                        if not p.is_blank:
                            plan.exclude(p, "冒頭部の表（著者表以外）の文字")
                continue
            plan.region[b.src] = "front_ja"
            if role == "title":
                plan.title.append(b)
                plan.locations[b.src] = "題目"
            elif role == "subtitle":
                plan.subtitle.append(b)
                plan.locations[b.src] = "副題"
            elif role in ("aff_ja", "author_ja"):
                self.author_paragraph_ja(b, role)
            elif b.is_blank:
                if b.plain():
                    plan.exclude(b, "空白のみの段落")
            else:
                plan.locations[b.src] = "冒頭部"
                plan.exclude(b, "冒頭部のテンプレート装飾・誌名行など（題目・著者以外の段落）")

    def read_author_table_ja(self, t: Table):
        current_affs = []
        for row in t.rows:
            row_affs, row_names = [], []
            for c in row.cells:
                for blk in c.blocks:
                    paras = [blk] if isinstance(blk, Para) else list(blk.paragraphs())
                    for p in paras:
                        r = self.role_of(p)
                        if p.is_blank:
                            if p.plain():
                                self.plan.exclude(p, "空白のみの段落")
                            continue
                        if r == "aff_ja":
                            row_affs.append(p)
                        elif r == "author_ja":
                            row_names.append(p)
                        else:
                            self.plan.exclude(p, "著者表の中の、所属・著者名以外の文字")
            if row_affs:
                current_affs = row_affs
            for n in row_names:
                self.add_author_ja(n, current_affs)

    def author_paragraph_ja(self, p, role):
        if not hasattr(self, "_loose_affs"):
            self._loose_affs = []
        if p.is_blank:
            return
        if role == "aff_ja":
            self._loose_affs = [p]
        else:
            self.add_author_ja(p, self._loose_affs)

    def add_author_ja(self, name_para, aff_paras):
        plan = self.plan
        a = Author(name_ja=name_para)
        plan.locations[name_para.src] = f"著者{len(plan.authors) + 1}（和文）"
        for ap in aff_paras:
            a.affs.append(self.aff_for(ja=ap))
        plan.authors.append(a)

    def aff_for(self, ja=None, en=None) -> Aff:
        plan = self.plan
        key_ja = _para_text(ja).strip() if ja else None
        for aff in plan.affs:
            if ja is not None and aff.ja is not None and _para_text(aff.ja).strip() == key_ja:
                if aff.ja is not ja:
                    plan.exclude(ja, f"重複する所属（{aff.ja.src} と同一の文字列のため 1 つにまとめた）")
                return aff
        aff = Aff(ja=ja, en=en)
        plan.affs.append(aff)
        if ja is not None:
            plan.locations[ja.src] = f"所属{len(plan.affs)}（和文）"
        return aff

    # ----------------------------------------------------------------- body
    def build_body(self, items):
        plan = self.plan
        flat = []
        for b, role in items:
            if isinstance(b, Table):
                flat.append(("table", b))
                for tp in b.paragraphs():
                    plan.region[tp.src] = "body"
                    tp.role = tp.role or "cell"
                continue
            plan.region[b.src] = "body"
            if b.in_textbox and role not in ("fig_caption", "table_caption") and not b.images:
                if not b.is_blank:
                    plan.exclude(b, "テキストボックス内の文字（図の一部とみなして本文から除外）")
                continue
            if b.is_blank:
                if b.plain():
                    plan.exclude(b, "空白のみの段落")
                continue
            if role in ("normal", None) or role not in BODY_ROLES | {"table"}:
                guessed = self.guess_heading(b, strict=False)
                if guessed:
                    role = guessed
                    b.role_origin = "heuristic"
                    plan.decide("mechanical", "style", b.src,
                                f"スタイル「{b.style_name}」の段落「{_para_text(b)[:30]}」を"
                                f"{ {'sec1': '章', 'sec2': '節', 'sec3': '項'}[role]}見出しと推定（番号の形式から）")
                else:
                    role = "p"
                    b.role_origin = "heuristic"
                    b.note = "style_unknown"
            elif role == "p":
                guessed = self.guess_heading(b, strict=True)
                if guessed:
                    role = guessed
                    b.role_origin = "heuristic"
                    plan.decide("mechanical", "style", b.src,
                                f"本文スタイルの段落「{_para_text(b)[:30]}」を"
                                f"{ {'sec1': '章', 'sec2': '節', 'sec3': '項'}[role]}見出しと推定（全体が太字で番号の形式）")
            b.role = role
            flat.append((role, b))

        # 本文スタイルのまま書かれた図表キャプションの推定
        for k, (role, b) in enumerate(flat):
            if role != "p" or not isinstance(b, Para):
                continue
            t = nfkc(_para_text(b)).strip()
            if len(t) > 80 or t.endswith("。"):
                continue
            nxt = flat[k + 1] if k + 1 < len(flat) else (None, None)
            prv = flat[k - 1] if k > 0 else (None, None)
            if RE_TABCAP.match(t) and (nxt[0] == "table" or prv[0] == "table"):
                flat[k] = ("table_caption", b)
                b.role, b.role_origin = "table_caption", "heuristic"
                plan.decide("mechanical", "style", b.src, f"本文スタイルの段落「{t[:30]}」を表キャプションと推定（隣が表）")
            elif RE_FIGCAP.match(t) and (self.is_image_para(nxt[1]) or self.is_image_para(prv[1])):
                flat[k] = ("fig_caption", b)
                b.role, b.role_origin = "fig_caption", "heuristic"
                plan.decide("mechanical", "style", b.src, f"本文スタイルの段落「{t[:30]}」を図キャプションと推定（隣が画像）")

        nodes = self.assemble_floats(flat)
        plan.body = self.nest(nodes)
        self.compute_locations(plan.body, [])

    @staticmethod
    def is_image_para(b) -> bool:
        if not isinstance(b, Para):
            return False
        return bool(b.images) and all(a.kind == "image" or (a.kind == "text" and is_ws(a.text)) for a in b.atoms)

    def assemble_floats(self, flat):
        """図（画像段落＋図キャプション）と表（表キャプション＋表）を組み立て、本文の要素列にする。"""
        plan = self.plan
        out = []
        used = set()
        n = len(flat)
        for k, (role, b) in enumerate(flat):
            if id(b) in used:
                continue
            if role in ("fig_caption", "table_caption") and out and k > 0 and flat[k - 1][1] is not None \
                    and isinstance(out[-1], FigNode if role == "fig_caption" else TableNode) \
                    and out[-1].caption is not None and flat[k - 1][0] == role \
                    and not (RE_FIGCAP if role == "fig_caption" else RE_TABCAP).match(nfkc(_para_text(b)).strip()):
                # 番号で始まらないキャプション段落が続く → 直前のキャプションの続き
                out[-1].caption_more.append(b)
                plan.decide("mechanical", "figure" if role == "fig_caption" else "table", b.src,
                            f"キャプションの続きの段落「{_para_text(b)[:20]}」を直前の{'図' if role == 'fig_caption' else '表'}のキャプションに含めた")
                continue
            if role == "fig_caption":
                img = None
                for j in range(len(out) - 1, max(-1, len(out) - 3), -1):
                    if isinstance(out[j], PNode) and self.is_image_para(out[j].para):
                        img = out.pop(j).para
                        break
                if img is None:
                    for j in range(k + 1, min(n, k + 3)):
                        if self.is_image_para(flat[j][1]) and id(flat[j][1]) not in used:
                            img = flat[j][1]
                            used.add(id(img))
                            break
                fig = FigNode(image_paras=[img] if img else [], caption=b)
                if img is None:
                    plan.decide("mechanical", "figure", b.src, "図キャプションに対応する画像が見つからない（図形・グループ化等の可能性）")
                out.append(fig)
                continue
            if role == "table_caption":
                tbl = None
                for j in range(k + 1, min(n, k + 3)):
                    if flat[j][0] == "table" and id(flat[j][1]) not in used:
                        tbl = flat[j][1]
                        used.add(id(tbl))
                        break
                if tbl is None and out and isinstance(out[-1], TableNode) and out[-1].caption is None:
                    out[-1].caption = b
                    continue
                if tbl is None:
                    plan.decide("mechanical", "table", b.src, "表キャプションに対応する表が見つからない")
                out.append(TableNode(table=tbl, caption=b))
                continue
            if role == "table":
                out.append(TableNode(table=b))
                continue
            if role in HEADING_LEVEL:
                out.append(Sec(level=HEADING_LEVEL[role], heading=b))
                continue
            if role == "quote":
                if out and isinstance(out[-1], QuoteNode):
                    out[-1].paras.append(b)
                else:
                    out.append(QuoteNode(paras=[b]))
                continue
            # 本文段落
            if self.is_image_para(b):
                out.append(PNode(b))   # 図キャプションが後に来れば図になる。最後まで残れば下で処理
                continue
            fnode = self.formula_node(b)
            if fnode:
                out.append(fnode)
                continue
            if b.numbering and b.autonum:
                ordered = not self.doc_numbering_is_bullet(b)
                if out and isinstance(out[-1], ListNode) and out[-1].items[-1].numbering[0] == b.numbering[0]:
                    out[-1].items.append(b)
                else:
                    out.append(ListNode(items=[b], ordered=ordered))
                continue
            out.append(PNode(b))
        # キャプションのない画像段落 → キャプションなしの図
        final = []
        for node in out:
            if isinstance(node, PNode) and self.is_image_para(node.para):
                fig = FigNode(image_paras=[node.para])
                imgs = node.para.images
                small = all(0 < i.height_cm < 2.2 and i.width_cm / max(i.height_cm, 0.01) > 2.5 for i in imgs)
                if small:
                    plan.decide("mechanical", "formula", node.para.src,
                                "キャプションのない横長の小さな画像（数式画像の可能性）。キャプションなしの図として出力")
                else:
                    plan.decide("mechanical", "figure", node.para.src, "キャプションのない画像。キャプションなしの図として出力")
                final.append(fig)
            else:
                final.append(node)
        return final

    @staticmethod
    def doc_numbering_is_bullet(b):
        return b.autonum and not re.search(r"[0-9０-９A-Za-zⅠ-Ⅻ①-⑳ア-ンイ一-十]", b.autonum)

    def formula_node(self, b: Para) -> Optional[FormulaNode]:
        if not b.has_display_math:
            return None
        plain = b.plain()
        if any(a.kind not in ("math", "text") for a in b.atoms):
            return None
        # 数式以外の文字が空白と式番号だけなら別行数式
        outside = "".join(a.text if a.kind == "text" else "" for a in b.atoms)
        if outside.strip() and not RE_FORMULA_LABEL.match(outside):
            return None
        node = FormulaNode(para=b)
        if outside.strip():
            m = re.search(r"[(（][\s\u3000]*[0-9０-９]+(?:[.．\-－][0-9０-９]+)?[\s\u3000]*[)）]", plain)
            if m:
                node.label = m.group(0)
                node.label_range = (m.start(), m.end())
        return node

    def nest(self, nodes):
        root = []
        stack = []   # Sec
        for node in nodes:
            if isinstance(node, Sec):
                while stack and stack[-1].level >= node.level:
                    stack.pop()
                (stack[-1].children if stack else root).append(node)
                stack.append(node)
            else:
                (stack[-1].children if stack else root).append(node)
        return root

    def compute_locations(self, nodes, path):
        plan = self.plan
        count = 0
        for node in nodes:
            if isinstance(node, Sec):
                title = _para_text(node.heading).strip()[:24] if node.heading else ""
                if node.heading:
                    plan.locations[node.heading.src] = " > ".join(path + [title]) + "（見出し）"
                self.compute_locations(node.children, path + [title])
                continue
            count += 1
            where = " > ".join(path) if path else "本文冒頭"
            for p in self.node_paras(node):
                plan.locations.setdefault(p.src, f"{where} / 第{count}要素")

    @staticmethod
    def node_paras(node):
        if isinstance(node, PNode):
            return [node.para]
        if isinstance(node, QuoteNode):
            return node.paras
        if isinstance(node, ListNode):
            return node.items
        if isinstance(node, FigNode):
            return node.image_paras + ([node.caption] if node.caption else []) + node.caption_more
        if isinstance(node, TableNode):
            out = ([node.caption] if node.caption else []) + node.caption_more
            if node.table:
                out += list(node.table.paragraphs())
            return out
        if isinstance(node, FormulaNode):
            return [node.para]
        return []

    # ----------------------------------------------------------------- back
    def build_back(self, items):
        plan = self.plan
        state = None
        current_fn = None
        for b, role in items:
            if isinstance(b, Table):
                if state == "refs":
                    for p in b.paragraphs():
                        if not p.is_blank:
                            plan.refs.append(RefNode(para=p))
                    continue
                target = {"notes": plan.notes, "ack": plan.ack}.get(state)
                if target is not None:
                    target.children.append(TableNode(table=b))
                else:
                    for p in b.paragraphs():
                        if not p.is_blank:
                            plan.exclude(p, "後付けの位置づけが不明な表の文字")
                continue
            heading = role if role in BACK_HEADINGS else self.back_heading_by_text(b, role)
            if heading:
                if role not in BACK_HEADINGS:
                    plan.decide("mechanical", "style", b.src,
                                f"スタイル「{b.style_name}」の段落「{_para_text(b)[:20]}」を後付けの見出しと推定（文字列から）")
                state = BACK_HEADINGS[heading]
                plan.region[b.src] = state
                if state == "notes":
                    plan.notes = BackSec(heading=b)
                    plan.locations[b.src] = "付記（見出し）"
                elif state == "ack":
                    plan.ack = BackSec(heading=b)
                    plan.locations[b.src] = "謝辞（見出し）"
                elif state == "fn":
                    plan.fn_heading = b
                    plan.locations[b.src] = "注（見出し）"
                elif state == "refs":
                    plan.ref_heading = b
                    plan.locations[b.src] = "引用文献（見出し）"
                current_fn = None
                continue
            plan.region[b.src] = state or "back"
            if b.is_blank:
                if b.plain():
                    plan.exclude(b, "空白のみの段落")
                continue
            if state == "refs":
                plan.refs.append(RefNode(para=b))
                plan.locations[b.src] = f"引用文献 {len(plan.refs)}件目"
            elif state == "fn":
                if b.autonum and RE_NOTE_MARK.match(b.autonum):
                    # Word の自動番号で「1)」などを付けた注
                    current_fn = FnNode(paras=[b], number=num_of(RE_NOTE_MARK.match(b.autonum).group(2)))
                    plan.fns.append(current_fn)
                    plan.locations[b.src] = f"注 {len(plan.fns)}件目"
                    continue
                m = RE_NOTE_MARK.match(b.plain())
                sup_lead = b.atoms and b.atoms[0].kind == "text" and "sup" in b.atoms[0].fmt and \
                    re.match(r"^[\s\u3000]*[0-9０-９]+", b.atoms[0].text)
                if m or sup_lead or current_fn is None:
                    current_fn = FnNode(paras=[b])
                    if m:
                        current_fn.number = num_of(m.group(2))
                        current_fn.mark_range = (m.start(1), m.end(1))
                    elif sup_lead:
                        mm = re.match(r"^[\s\u3000]*([0-9０-９]+)", b.atoms[0].text)
                        current_fn.number = num_of(mm.group(1))
                        current_fn.mark_range = (mm.start(1), mm.end(1))
                    plan.fns.append(current_fn)
                else:
                    current_fn.paras.append(b)
                plan.locations[b.src] = f"注 {len(plan.fns)}件目"
            elif state in ("notes", "ack"):
                target = plan.notes if state == "notes" else plan.ack
                fnode = self.formula_node(b)
                target.children.append(fnode or PNode(b))
                plan.locations[b.src] = ("付記" if state == "notes" else "謝辞") + f" 第{len(target.children)}段落"
            else:
                plan.exclude(b, "位置づけが不明な段落（本文と後付けの間）")

    # ----------------------------------------------------------------- front (en) + appendix
    def build_front_en(self, items):
        plan = self.plan
        in_abstract = False
        app = None
        pending_name = None
        for b, role in items:
            if isinstance(b, Table):
                troles = self.table_roles(b)
                if troles & {"author_en", "aff_en"} and app is None:
                    for p in b.paragraphs():
                        r = self.role_of(p)
                        plan.region[p.src] = "front_en"
                        if p.is_blank:
                            if p.plain():
                                plan.exclude(p, "空白のみの段落")
                            continue
                        if r == "author_en":
                            pending_name = self.add_author_en(p)
                        elif r == "aff_en":
                            self.add_aff_en(p, pending_name)
                        else:
                            plan.exclude(p, "英文著者表の中の、所属・著者名以外の文字")
                    continue
                if in_abstract or app is not None:
                    if app is None:
                        app = AppNode(title=None)
                        plan.apps.append(app)
                    app.children.append(TableNode(table=b))
                else:
                    for p in b.paragraphs():
                        if not p.is_blank:
                            plan.exclude(p, "英文部分の表（著者表以外）の文字")
                continue
            plan.region[b.src] = "front_en"
            if b.is_blank:
                if b.plain():
                    plan.exclude(b, "空白のみの段落")
                continue
            text = _para_text(b)
            if (in_abstract or app is not None) and RE_APPENDIX.match(text):
                app = AppNode(title=b)
                plan.apps.append(app)
                plan.region[b.src] = "app"
                plan.locations[b.src] = f"資料{len(plan.apps)}（見出し）"
                in_abstract = False
                continue
            if app is not None:
                plan.region[b.src] = "app"
                plan.locations[b.src] = f"資料{len(plan.apps)} 第{len(app.children) + 1}要素"
                if role in HEADING_LEVEL or self.guess_heading(b, strict=False):
                    app.children.append(PNode(b))   # 資料内の見出しは段落として出力
                else:
                    fnode = self.formula_node(b)
                    app.children.append(fnode or (FigNode(image_paras=[b]) if self.is_image_para(b) else PNode(b)))
                continue
            if role == "title_en":
                plan.title_en.append(b)
                plan.locations[b.src] = "英文題目"
            elif role == "subtitle_en":
                plan.subtitle_en.append(b)
                plan.locations[b.src] = "英文副題"
            elif role == "author_en":
                pending_name = self.add_author_en(b)
            elif role == "aff_en":
                self.add_aff_en(b, pending_name)
            elif role == "abstract_heading":
                plan.abstract_heading = b
                plan.locations[b.src] = "英文要旨（見出し）"
                in_abstract = True
            elif role == "abstract" or in_abstract:
                plan.abstract.append(b)
                plan.locations[b.src] = f"英文要旨 第{len(plan.abstract)}段落"
                in_abstract = True
            else:
                plan.locations[b.src] = "英文部分"
                plan.exclude(b, "英文部分の、題目・著者・要旨以外の段落")

    def add_author_en(self, p) -> Author:
        plan = self.plan
        idx = getattr(self, "_en_count", 0)
        self._en_count = idx + 1
        plan.locations[p.src] = f"著者{idx + 1}（英文）"
        if idx < len(plan.authors):
            plan.authors[idx].name_en = p
            return plan.authors[idx]
        a = Author(name_en=p)
        plan.authors.append(a)
        return a

    def add_aff_en(self, p, author: Optional[Author]):
        plan = self.plan
        plan.locations[p.src] = "所属（英文）"
        text = _para_text(p).strip()
        if author is not None:
            # 和文所属と対応付ける（同じ著者の和文所属のうち、英文が未設定のもの）
            for aff in author.affs:
                if aff.en is None:
                    aff.en = p
                    return
                if _para_text(aff.en).strip() == text:
                    if aff.en is not p:
                        plan.exclude(p, f"重複する所属（{aff.en.src} と同一の文字列のため 1 つにまとめた）")
                    return
        for aff in plan.affs:
            if aff.en is not None and _para_text(aff.en).strip() == text:
                if author is not None and aff not in author.affs:
                    author.affs.append(aff)
                plan.exclude(p, f"重複する所属（{aff.en.src} と同一の文字列のため 1 つにまとめた）")
                return
        aff = Aff(en=p)
        plan.affs.append(aff)
        if author is not None:
            author.affs.append(aff)

    def attach_word_notes(self):
        """Word の脚注機能で付けた注を、注のリストの後ろに加える。"""
        plan = self.plan
        order = []
        for p in self.doc.all_paragraphs():
            for a in p.atoms:
                if a.kind == "fnref" and a.fn_kind.startswith("footnote") and a.fn_id not in order:
                    order.append(a.fn_id)
        for nid in order:
            paras = self.doc.footnotes.get(nid, [])
            if not paras:
                continue
            node = FnNode(paras=paras, word_note=True)
            for p in paras:
                plan.region[p.src] = "fn"
                plan.locations[p.src] = f"Word の脚注 {len(order)}件中"
            node.word_id = nid
            plan.fns.append(node)
        for p in self.doc.endnotes.values():
            for q in p:
                if not q.is_blank:
                    plan.exclude(q, "Word の文末脚注（未対応。内容を確認して本文の注に移してください）")

    def assign_ids(self):
        plan = self.plan
        figs, tabs, forms = [], [], []

        def walk(nodes):
            for node in nodes:
                if isinstance(node, Sec):
                    walk(node.children)
                elif isinstance(node, FigNode):
                    figs.append(node)
                elif isinstance(node, TableNode):
                    tabs.append(node)
                elif isinstance(node, FormulaNode):
                    forms.append(node)
                elif isinstance(node, (BackSec, AppNode)):
                    walk(node.children)
        walk(plan.body)
        for extra in (plan.notes, plan.ack):
            if extra:
                walk(extra.children)
        for app in plan.apps:
            walk(app.children)
        seen = set()
        k = 0
        for f in figs:
            if f.caption is not None:
                k += 1
                f.fid = f"F{k}"
                m = RE_FIGCAP.match(nfkc(_para_text(f.caption)).strip())
                if m:
                    f.number = int(m.group(1))
                    if f.number in seen:
                        plan.decide("mechanical", "figure", f.caption.src, f"図番号 {f.number} が重複している")
                    seen.add(f.number)
        seen = set()
        for i, t in enumerate(tabs, 1):
            t.tid = f"T{i}"
            if t.caption is not None:
                m = RE_TABCAP.match(nfkc(_para_text(t.caption)).strip())
                if m:
                    t.number = int(m.group(1))
                    if t.number in seen:
                        plan.decide("mechanical", "table", t.caption.src, f"表番号 {t.number} が重複している")
                    seen.add(t.number)
        for i, fm in enumerate([f for f in forms if f.label], 1):
            fm.fid = f"FD{i}"
        for i, fn in enumerate(plan.fns, 1):
            fn.fid = f"fn{i}"
        for i, r in enumerate(plan.refs, 1):
            r.rid = f"B{i}"
        for i, a in enumerate(plan.affs, 1):
            a.aid = f"aff{i}"
        plan.figures, plan.tables, plan.formulas = figs, tabs, forms


def classify(doc, journal, overrides=None) -> ArticlePlan:
    return Classifier(doc, journal, overrides).run()
