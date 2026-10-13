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

from .floats import at_anchor, why_not_at_anchor
from .model import Decision, Exclusion, Float, Para, Table
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
# テキストボックス内のキャプションの形（NFKC 後）。番号の直後がひらがな・読点・範囲の記号なら「図1は…」のような本文の文
RE_TEXTBOX_CAP = re.compile(r"^(?:(?P<fig>図|Figure|Fig\.?)|(?P<tab>表|Table))\s*[0-9]+(?![0-9ぁ-ゟ,、・~〜\-–—])")
RE_FORMULA_LABEL = re.compile(r"^[\s\u3000]*([(（][\s\u3000]*[0-9０-９]+(?:[.．\-－][0-9０-９]+)?[\s\u3000]*[)）])[\s\u3000]*$")
# 注の一覧の各注の先頭の番号: 「1)」「(1)」「注1)」/「（注1）」「［注1］」/「注1　…」（「註」も）
_WS = r"[\s\u3000]*"
RE_NOTE_MARK = re.compile(
    rf"^{_WS}("
    rf"(?:[注註]{_WS})?[(（]?{_WS}(?P<n1>[0-9０-９]{{1,3}}){_WS}[)）]"
    rf"|[(（\[［〔]{_WS}[注註]{_WS}(?P<n2>[0-9０-９]{{1,3}}){_WS}[)）\]］〕]"
    rf"|[注註]{_WS}(?P<n3>[0-9０-９]{{1,3}})(?=[\s\u3000:：.．,，、]|$)"
    rf")")
RE_REF_HEADING_TEXT = re.compile(r"^\s*(?:引用(?:・|及び|および)?参考文献|参考(?:・|及び|および)?引用文献|引用文献|参考文献|文献"
                                 r"|References?|REFERENCES?|Bibliography)\s*$")
RE_ACK_TEXT = re.compile(r"^\s*(?:謝辞|Acknowledge?ments?)\s*$")
RE_NOTES_TEXT = re.compile(r"^\s*付記\s*$")
RE_FN_TEXT = re.compile(r"^\s*(?:注|註|注釈|Notes?)\s*$")
RE_APPENDIX = re.compile(r"^[\s\u3000]*(?:資料|付録|附録|Appendix)(?:[\s\u3000]*[0-9０-９A-ZＡ-Ｚ]+)?(?=[\s\u3000:：]|$)")


def nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


def num_of(s: str) -> Optional[int]:
    try:
        return int(nfkc(s))
    except ValueError:
        return None


def note_mark(s: str) -> Optional[tuple]:
    """注の先頭の番号（「1)」「（注1）」など）の (開始, 終了, 番号)。番号で始まっていなければ None。"""
    m = RE_NOTE_MARK.match(s or "")
    if not m:
        return None
    return m.start(1), m.end(1), num_of(m.group("n1") or m.group("n2") or m.group("n3"))


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
    tables: list = field(default_factory=list)         # 表で組んだ図の本体（テキストボックスの中の表など）
    extra_images: list = field(default_factory=list)   # 他の段落の中から移した画像（グループ図形の画像）
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


@dataclass(eq=False)
class FloatInfo:
    """本文の浮動配置の図形のうち、図表の中身（画像・表・キャプション）を持つもの。"""
    float: Float
    paras: list = field(default_factory=list)      # テキストボックスの段落（出現順）
    tables: list = field(default_factory=list)     # テキストボックスの表
    images: list = field(default_factory=list)     # グループ図形の画像（アンカー段落の中にある ImageRef）
    mode: str = ""                                 # mechanical（機械的に配置）/ ai（AI の指定で配置）/ unplaced（未配置）
    reason: str = ""                               # 未配置の理由


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
    floats: dict = field(default_factory=dict)       # 浮動配置の図形の ID -> FloatInfo
    body_seq: list = field(default_factory=list)     # 本文の段落 ID（出現順。浮動配置の図形の中の段落を除く）
    moved_images: set = field(default_factory=set)   # 図に移したため、元の段落では出力しない画像の ID
    float_decisions: dict = field(default_factory=dict)  # AI の指定で配置した図形の ID -> Decision
    layout: object = None                            # 本文の段組みと行の設定（model.Layout）
    pdf_edits: dict = field(default_factory=dict)    # 出版版 PDF に合わせる変更: src -> ({位置: 文字}, {落とす空白の位置})

    @property
    def unplaced_floats(self) -> list:
        return [fid for fid, info in self.floats.items() if info.mode == "unplaced"]

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
    def __init__(self, doc, journal, overrides=None, placements=None):
        self.doc = doc
        self.journal = journal
        self.mapping = journal.styles
        self.overrides = overrides or {}      # src -> role（AI 補完）
        self.placements = placements or {}    # 浮動配置の図形の ID -> 配置の指定（AI 補完。ai_assist.float_placements）
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
                        # AI への依頼文にも載せる（確認のため。役割の変更は受け付けない）
                        self.plan.region[p.src] = "authors"
                        p.role = p.role or r
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
        order = {id(b): k for k, (b, _) in enumerate(items)}
        items, inserts, front = self.place_floats(items)
        for k in front:
            order[k] = -1           # 位置を決められない図表の中身（本文の冒頭に置く）
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
                cap = self.textbox_caption(b)
                if cap is None:
                    if not b.is_blank:
                        plan.exclude(b, "テキストボックス内の文字（図の一部とみなして本文から除外）")
                    continue
                role = cap
                b.role_origin = "heuristic"
                kind = "図" if cap == "fig_caption" else "表"
                plan.decide("mechanical", "style", b.src,
                            f"テキストボックス内のスタイル「{b.style_name}」の段落「{_para_text(b)[:30]}」を"
                            f"{kind}キャプションと推定（「{kind}N」で始まる）")
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

        # 配置を決めた浮動配置の図表を、決めた位置（items での位置）に差し込む
        merged, pending = [], sorted(inserts, key=lambda x: (x[0], x[1]))
        for entry in flat:
            while pending and pending[0][0] <= order[id(entry[1])]:
                merged.extend(pending.pop(0)[2])
            merged.append(entry)
        for _, _, entries in pending:
            merged.extend(entries)
        flat = merged

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

    # ----------------------------------------------------------------- 浮動配置の図表
    def place_floats(self, items):
        """浮動配置の図形（テキストボックス・グループ図形）に入った図表を、本文のどこに置くかを決める。

        図を置く位置の規則は「Word で表示したときに、図の左上の直上にある本文の文章を含む段落の直後」。
        - AI の指定（placements）があれば、その組み合わせで、指定された段落の直後に置く。
        - なければ、図の左上がアンカー段落の左上の位置にあり（floats.at_anchor）、中身が単純（キャプション 1 つと本体 1 つ）な
          場合だけ、機械的にアンカー段落の前に置く。
        - どちらでもなければ「位置を決められない図表」として記録し、本文の冒頭に仮に置く（利用者が手作業で移す）。
          中身が単純なら図の本体とキャプションを組にし、そうでなければ中身をそのまま（これまでの扱いで）出す。
        戻り値: (並べ直した items, [(items での位置, 同じ位置での順番, [(役割, 要素)])], 本文の冒頭に移した中身の id の集合)。
        同じ位置に置くものはキャプションの番号順
        """
        plan = self.plan
        src_index = {b.src: k for k, (b, _) in enumerate(items) if isinstance(b, Para)}
        plan.layout = getattr(self.doc, "layout", None)
        plan.body_seq = [b.src for b, _ in items if isinstance(b, Para) and not b.float_id]
        members, group_imgs, roles = {}, {}, {}
        for b, role in items:
            if b.float_id:
                members.setdefault(b.float_id, []).append(b)
                roles[id(b)] = role
            elif isinstance(b, Para):
                for img in b.images:
                    if img.float_id:
                        group_imgs.setdefault(img.float_id, []).append(img)
        placed, inserts, front = set(), [], []
        layout = plan.layout
        for fl in getattr(self.doc, "floats", []):
            if fl.anchor_src not in src_index:
                continue
            blocks = members.get(fl.fid, [])
            info = FloatInfo(float=fl, paras=[b for b in blocks if isinstance(b, Para)],
                             tables=[b for b in blocks if isinstance(b, Table)], images=group_imgs.get(fl.fid, []))
            groups, others = self.float_captions(info.paras, roles)
            if not (info.images or info.tables or groups or any(q.images for q in info.paras)):
                continue        # 文字だけのテキストボックスは図表ではない（これまでどおり）
            plan.floats[fl.fid] = info
            spec = self.placements.get(fl.fid)
            if spec and spec["after"] not in src_index:
                spec = None     # AI の役割の指定で、指定された段落が本文でなくなった
            if spec:
                entries = self.float_from_spec(info, spec)
                target = src_index[spec["after"]] + 1
                info.mode = "ai"
            else:
                entries = self.float_mechanical(info, groups, others) if at_anchor(fl, layout) else None
                if entries is None:
                    info.mode = "unplaced"
                    info.reason = (why_not_at_anchor(fl, layout) if not at_anchor(fl, layout)
                                   else "中身の組み合わせ（図表の本体とキャプション）を機械的に決められない")
                    plan.decide("mechanical", "figure", fl.anchor_src,
                                f"テキストボックス・グループ図形 {fl.fid}（{self.float_summary(info)}）は、位置を機械的に"
                                f"決められない（{info.reason}）。AI による補完で位置を指定する必要がある"
                                "（指定がなければ本文の冒頭に仮に置く）", applied=False)
                    # 位置は決められないので本文の冒頭に置く。組み合わせは、中身が単純なら機械的に組む
                    entries = self.float_mechanical(info, groups, others)
                    placed.update(id(b) for b in blocks)
                    if entries is None:
                        front.extend((b, roles[id(b)]) for b in blocks)
                        continue
                    inserts.append((-1, (self.float_number(info), len(inserts)), entries))
                    continue
                target = src_index[fl.anchor_src]
                info.mode = "mechanical"
                plan.decide("mechanical", "figure", fl.anchor_src,
                            f"テキストボックス・グループ図形 {fl.fid}（{self.float_summary(info)}）を、アンカー段落"
                            f"「{_para_text(plan.paras[fl.anchor_src])[:20]}」の前に置いた（図の左上がアンカー段落の左上の位置にあるため）")
            placed.update(id(b) for b in blocks)
            inserts.append((target, (self.float_number(info), len(inserts)), entries))
        rest = [(b, r) for b, r in items if id(b) not in placed]
        return front + rest, inserts, {id(b) for b, _ in front}

    @staticmethod
    def float_number(info) -> float:
        """浮動配置の図形の中の最初の図表番号（なければ無限大）。"""
        for q in info.paras + [c for t in info.tables for c in t.paragraphs()]:
            m = RE_FIGCAP.match(nfkc(_para_text(q)).strip()) or RE_TABCAP.match(nfkc(_para_text(q)).strip())
            if m:
                return int(nfkc(m.group(1)))
        return float("inf")

    def float_captions(self, paras, roles):
        """テキストボックスの段落からキャプションを探す。戻り値: ([(役割, [段落…])], キャプションでも画像でもない段落)"""
        groups, others = [], []
        prev_cap = False
        for p in paras:
            if p.is_blank or p.images:
                prev_cap = prev_cap and p.is_blank
                continue
            role = roles.get(id(p), "")
            cap = role if role in ("fig_caption", "table_caption") else self.textbox_caption(p)
            t = nfkc(_para_text(p)).strip()
            if cap and (RE_FIGCAP.match(t) or RE_TABCAP.match(t) or not groups):
                groups.append((cap, [p]))
                prev_cap = True
            elif role in ("fig_caption", "table_caption") and prev_cap:
                groups[-1][1].append(p)       # 番号で始まらないキャプションの続き（出典など）
            else:
                others.append(p)
                prev_cap = False
        return groups, others

    @staticmethod
    def float_summary(info) -> str:
        """浮動配置の図形の中身の要約（レポート用）: キャプションの冒頭と、本体の種類。"""
        texts = [nfkc(_para_text(q)).strip() for q in info.paras if not q.is_blank]
        caps = [t[:20] for t in texts if RE_FIGCAP.match(t) or RE_TABCAP.match(t)]
        body = (["画像"] if info.images or any(q.images for q in info.paras) else []) + (["表"] if info.tables else [])
        head = "、".join(f"「{c}」" for c in caps) if caps else "キャプションなし"
        return f"{head}／中身: {'・'.join(body) or '文字'}"

    def _take(self, p: Para, role: str, origin=""):
        p.role = role
        if origin:
            p.role_origin = origin
        self.plan.region[p.src] = "body"

    def _take_table(self, t: Table):
        for tp in t.paragraphs():
            self.plan.region[tp.src] = "body"
            tp.role = tp.role or "cell"

    def _caption_decision(self, p: Para, role: str):
        if p.role_origin != "style" or self.style_role(p) not in ("fig_caption", "table_caption"):
            kind = "図" if role == "fig_caption" else "表"
            self.plan.decide("mechanical", "style", p.src,
                             f"テキストボックス内のスタイル「{p.style_name}」の段落「{_para_text(p)[:30]}」を"
                             f"{kind}キャプションと推定（「{kind}N」で始まる）")
            return "heuristic"
        return ""

    def _drop_blank(self, p: Para):
        self.plan.region[p.src] = "body"
        if p.plain():
            self.plan.exclude(p, "空白のみの段落")

    def float_mechanical(self, info, groups, others):
        """位置が機械的に決まる浮動配置の図形の中身を組む。中身が単純でなければ None（AI に任せる）。"""
        image_paras = [q for q in info.paras if q.images]
        if len(groups) > 1 or others or len(info.tables) > 1 or (info.tables and (image_paras or info.images)):
            return None
        if groups and groups[0][0] == "table_caption" and (image_paras or info.images):
            return None
        # ここから先は必ず組む（状態を変えるのは、組めると決まってから）
        for q in info.paras:
            if q.is_blank and not q.images:
                self._drop_blank(q)
        for t in info.tables:
            self._take_table(t)
        for q in image_paras:
            self._take(q, "p")
        if not groups:
            # キャプションのない画像・表（これまでの扱い: キャプションなしの図・表）
            return [("p", q) for q in image_paras] + [("table", t) for t in info.tables]
        role, caps = groups[0]
        for q in caps:
            self._take(q, role, self._caption_decision(q, role))
        if role == "table_caption":
            if not info.tables:
                return [(role, q) for q in caps]
            return [("node", TableNode(table=info.tables[0], caption=caps[0], caption_more=caps[1:]))]
        if not (image_paras or info.images or info.tables):
            return [(role, q) for q in caps]     # キャプションだけ（隣の画像と組にする。これまでの扱い）
        self.plan.moved_images.update(i.image_id for i in info.images)
        return [("node", FigNode(image_paras=image_paras, caption=caps[0], caption_more=caps[1:],
                                 tables=list(info.tables), extra_images=list(info.images)))]

    def float_from_spec(self, info, spec):
        """AI が指定した組み合わせ（ai_assist.float_placements で検証済み）で、浮動配置の図形の中身を組む。"""
        plan = self.plan
        paras = {q.src: q for q in info.paras}
        cells = {q.src: t for t in info.tables for q in t.paragraphs()}
        cell_paras = {q.src: q for t in info.tables for q in t.paragraphs()}
        tables = {t.tid: t for t in info.tables}
        group_imgs = {i.image_id: i for i in info.images}
        img_para = {i.image_id: q for q in list(info.paras) + list(cell_paras.values()) for i in q.images}
        used, used_tables, dissolved, entries, descs = set(), set(), set(), [], []
        for item in spec["items"]:
            caps = []
            for src in item["caption"]:
                q = paras.get(src) or cell_paras[src]
                if src in cells:
                    dissolved.add(cells[src].tid)
                role = "fig_caption" if item["kind"] == "fig" else "table_caption"
                self._take(q, role, "ai")
                caps.append(q)
                used.add(q.src)
            image_paras, extra, tbls = [], [], []
            for x in item["body"]:
                if x in tables:
                    tbls.append(tables[x])
                    used_tables.add(x)
                    self._take_table(tables[x])
                elif x in group_imgs:
                    extra.append(group_imgs[x])
                else:
                    q = paras.get(x) or cell_paras.get(x) or img_para[x]
                    if q.src in cells:
                        dissolved.add(cells[q.src].tid)
                    if q not in image_paras:
                        image_paras.append(q)
                        self._take(q, "p")
                        used.add(q.src)
            plan.moved_images.update(i.image_id for i in extra)
            cap, more = (caps[0], caps[1:]) if caps else (None, [])
            if item["kind"] == "table":
                entries.append(("node", TableNode(table=tbls[0], caption=cap, caption_more=more)))
            else:
                entries.append(("node", FigNode(image_paras=image_paras, caption=cap, caption_more=more,
                                                tables=tbls, extra_images=extra)))
            what = "表" if item["kind"] == "table" else "図"
            body = "表" if tbls else "画像"
            descs.append(f"{what}「{_para_text(cap)[:20] if cap else 'キャプションなし'}」（本体: {body}）")
        # 指定に含まれなかった中身は、図表の後にそのまま出す（文字を落とさないため）
        for q in info.paras:
            if q.src in used:
                continue
            if q.is_blank and not q.images:
                self._drop_blank(q)
            else:
                self._take(q, "p")
                entries.append(("p", q))
        for t in info.tables:
            if t.tid in dissolved:
                for q in t.paragraphs():
                    if q.src in used:
                        continue
                    if q.is_blank and not q.images:
                        self._drop_blank(q)
                    else:
                        self._take(q, "p")
                        entries.append(("p", q))
            elif t.tid not in used_tables:
                self._take_table(t)
                entries.append(("table", t))
        after = plan.paras.get(spec["after"])
        d = plan.decide("ai", "figure", spec["after"],
                        f"テキストボックス・グループ図形 {info.float.fid} の中身を{'、'.join(descs)}として組み、段落"
                        f"「{_para_text(after)[:20] if after else spec['after']}」の後に置いた。{spec.get('reason', '')}",
                        spec.get("confidence", ""))
        plan.float_decisions[info.float.fid] = d
        return entries

    @staticmethod
    def textbox_caption(b: Para) -> Optional[str]:
        """図表キャプションのスタイルでないテキストボックス内の段落が、キャプションの形をしていれば役割を返す。"""
        t = nfkc(_para_text(b)).strip()
        if len(t) > 80 or t.endswith("。"):
            return None
        m = RE_TEXTBOX_CAP.match(t)
        if not m:
            return None
        return "fig_caption" if m.group("fig") else "table_caption"

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
        below = sum(1 for k in range(1, n) if flat[k][0] == "fig_caption" and self.is_image_para(flat[k - 1][1]))
        above = sum(1 for k in range(n - 1) if flat[k][0] == "fig_caption" and self.is_image_para(flat[k + 1][1]))
        captions_below = below >= above
        for k, (role, b) in enumerate(flat):
            if role == "node":          # 組み立て済みの図表（浮動配置の図形）
                out.append(b)
                continue
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
                        # キャプションを画像の下に置く原稿では、直後に図キャプションがある画像はそのキャプションの図のもの
                        if captions_below and j + 1 < n and flat[j + 1][0] == "fig_caption":
                            continue
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
            return (node.image_paras + ([node.caption] if node.caption else []) + node.caption_more
                    + [p for t in node.tables for p in t.paragraphs()])
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
                    if plan.ref_heading is not None:
                        plan.decide("mechanical", "note", b.src,
                                    "注の節が引用文献の後ろにある（テンプレートでは引用文献の前）。XML では位置に関係なく注の一覧として出力した")
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
                # 番号（Word の自動番号の「1)」、手で打った「1)」「（注1）」、上付きの数字）で始まる段落から新しい注。
                # 番号のない段落は前の注の続き。AI の指定（fn_start: 新しい注の始まり / p: 前の注の続き）があればそれに従う
                auto = note_mark(b.autonum) if b.autonum else None
                mark = None if auto else note_mark(b.plain())
                sup_lead = None
                if not (auto or mark) and b.atoms and b.atoms[0].kind == "text" and "sup" in b.atoms[0].fmt:
                    sup_lead = re.match(r"^[\s\u3000]*([0-9０-９]+)", b.atoms[0].text)
                starts = bool(auto or mark or sup_lead)
                ai_role = self.overrides.get(b.src)
                if ai_role == "fn_start":
                    starts = True
                elif ai_role == "p" and current_fn is not None:
                    starts = False
                if starts or current_fn is None:
                    current_fn = FnNode(paras=[b])
                    if auto:
                        current_fn.number = auto[2]
                    elif mark:
                        current_fn.number = mark[2]
                        current_fn.mark_range = mark[:2]
                    elif sup_lead:
                        current_fn.number = num_of(sup_lead.group(1))
                        current_fn.mark_range = (sup_lead.start(1), sup_lead.end(1))
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
                        plan.region[p.src] = "authors"
                        p.role = p.role or r
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
        word = [fn for fn in plan.fns if fn.word_note]
        if word:
            plan.decide("mechanical", "note", word[0].paras[0].src,
                        f"Word の脚注機能で書かれた注 {len(word)} 件を、注の一覧にした（テンプレートの規定は、本文に上付きの「1)」を書き、"
                        f"注は「注」の節にまとめる）。本文と注の一覧の番号、注の見出しは補った（8 章）")
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


def classify(doc, journal, overrides=None, placements=None) -> ArticlePlan:
    return Classifier(doc, journal, overrides, placements).run()
