"""論文の構造（ArticlePlan）と、その要素（章・段落・箇条書き・図表・数式・囲み・注・文献など）の型。

structure.py（段落の役割の決定と構造の組み立て。Classifier）が作り、linker・refparse・ai_assist・builder・report・pipeline・pdfmatch・pdfdocx が読み書きする。
ここには型と、ArticlePlan のメソッド（判断の記録 decide、出力しない段落の記録 exclude・exclude_blank、図表・囲みを置いた
位置の説明 float_place・box_place など）だけを置き、役割の判定や組み立ての規則は置かない（structure.py）。修正計画の U6 で
structure.py から本体を変えずに移した（structure からも、これまでどおり import できる）。model.py 以外には依存しない。
出力しない段落は、exclude・exclude_blank で必ず理由付きで記録する（文字は変えない）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .model import Decision, Exclusion, Float, Para, Table


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
class BoxNode:
    """囲み（文字だけのテキストボックス）。<boxed-text> になる。children は PNode・ListNode・QuoteNode・FormulaNode。"""
    xid: str
    children: list = field(default_factory=list)


@dataclass(eq=False)
class FnNode:
    paras: list
    fid: str = ""
    number: Optional[int] = None
    mark_range: tuple = None      # 先頭の「1)」の位置（para.plain() 上）
    word_note: bool = False       # Word の脚注機能・文末脚注機能による注
    word_kind: str = ""           # footnote（脚注）/ endnote（文末脚注）
    word_id: str = ""             # 注の鍵（model.note_key。"footnote:5" など）
    word_refs: list = field(default_factory=list)   # 参照のある段落の ID（docx の順。重複なし。注の中の参照も）
    # 参照の少なくとも 1 つを、注へのリンクにして出力するか（False なら、参照は XML に出力しなかった段落と、注の番号をリンクに
    # しない段落〈ArticlePlan.no_link_paras〉の中だけ。本文からのリンクのない注）
    linked: bool = True
    custom_mark: bool = False     # 参照のどれかが、記号を自分で付けたもの（customMarkFollows。本文の記号は docx の文字のまま）


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
    where: str = ""                                # 未配置のときに仮に置いた位置: anchor（アンカー段落の後ろ）/ end（本文の最後）
    end_why: str = ""                              # 本文の最後に置いた理由: ai（AI が本文の外の段落の後ろを指定）/ anchor（アンカー段落が本文でない）
    end_after: str = ""                            # AI が指定した本文の外の段落の ID（end_why が ai のとき）
    # 未配置で where が anchor のとき、その後ろに仮に置いた本文の段落の ID（アンカー段落。アンカー段落が箇条書き・引用の途中なら、
    # その箇条書き・引用の最後の段落。Classifier.run_end）
    after_src: str = ""


@dataclass(eq=False)
class BoxInfo:
    """文字だけのテキストボックス（Classifier.place_boxes が扱ったもの）の扱い。レポート・AI 依頼文・知らせに使う。"""
    box: object                     # model.TextBox
    paras: list = field(default_factory=list)      # テキストボックスの段落（出現順。本文の要素の列にあるもの）
    kind: str = ""                  # box（囲み）/ label（図に重ねた注記）/ undecided（決められない）/ blank（空白だけ）。AI の指定の後は、指定の種類
    why: str = ""                   # 判定の根拠（floats.textbox_kind）
    mode: str = ""                  # mechanical / ai
    # 囲みを置いた位置: before（アンカー段落の前）/ after（アンカー段落〈箇条書き・引用の途中なら、その終わり〉の後ろ）/
    # end（本文の最後）/ ai（AI の指定の段落の後ろ）。出力しないものは ""
    where: str = ""
    estimated: bool = False         # 位置を推定した（要確認）
    place_why: str = ""             # 位置を推定した理由
    after_src: str = ""             # 後ろに置いた本文の段落（before ならアンカー段落）
    outside: str = ""               # アンカー段落が本文の外なら、その領域（OUTSIDE_JA のキー。修正計画の N7）
    near: bool = False              # 画像の近く（Classifier.near_image）
    float: object = None            # 浮動配置のテキストボックスなら、その図形（model.Float。AI 依頼文の位置の説明に使う）


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
    # decide が判断の番号に使う、段階ごとの判断の数と、数えた時点の decisions の長さ（decisions を直接足したときは decide が数え直す）
    _stage_counts: dict = field(default_factory=dict, repr=False, compare=False)
    _counted: int = field(default=0, repr=False, compare=False)
    figures: list = field(default_factory=list)
    tables: list = field(default_factory=list)
    formulas: list = field(default_factory=list)
    paras: dict = field(default_factory=dict)        # src -> Para
    locations: dict = field(default_factory=dict)    # src -> 人が読める位置
    region: dict = field(default_factory=dict)       # src -> front_ja / authors / body / back / notes / ack / fn / refs / front_en / app / excluded
    citation_mode: str = ""                          # author-year / numeric（refparse が設定）
    uncited_refs: list = field(default_factory=list) # 本文からリンクされていない文献の ID
    floats: dict = field(default_factory=dict)       # 浮動配置の図形の ID -> FloatInfo
    body_seq: list = field(default_factory=list)     # 本文の段落 ID（出現順。浮動配置の図形の中の段落を除く）
    moved_images: set = field(default_factory=set)   # 図に移したため、元の段落では出力しない画像の ID
    float_decisions: dict = field(default_factory=dict)  # AI の指定で配置した図形の ID -> Decision
    figure_issues: list = field(default_factory=list)    # 画像のない図キャプションの近くの表を図の本体にできなかったもの: (段落 ID, 理由)
    # docx の表のセルの段落のうち、表の外に出したもの（表のセルの画像とキャプションで組んだ図のキャプション・本体。cell_figures）。
    # 出版版 PDF との照合では、今までどおり表のセルとして扱う（照合しない・直さない。linker.body_paragraphs の文脈 "cell"）
    cell_paras: set = field(default_factory=set)
    layout: object = None                            # 本文の段組みと行の設定（model.Layout）
    pdf_numbers: dict = field(default_factory=dict)  # ルート2: Word が付ける番号を PDF に合わせたもの: (種類, ID) -> 文字列（pdfmatch）
    note_of: dict = field(default_factory=dict)      # Word の脚注・文末脚注の段落 ID -> 注の鍵（model.note_key。参照のない注も）
    warnings: list = field(default_factory=list)     # 構造の組み立ての警告（pipeline がレポートの 10 章の警告に加える）
    abstract_ja: list = field(default_factory=list)  # 英文要旨の中の、かな・漢字が 3 割以上の段落 ID（自動では移さない。要確認）
    app_after_refs: list = field(default_factory=list)   # 引用文献などの後ろの、資料の見出しと思われる段落 ID（暫定で警告だけ）
    # 文字から推定した注の見出し（本文スタイルの「注」だけの段落）の扱いの記録: (「注」の段落 ID, "returned"（本文に戻した）か "kept"
    # （注の番号で始まらない段落が続いたまま注の節として扱った）, 説明)。要確認で知らせる（Classifier.split_regions。report._fn_guess_action）
    fn_guess_checks: list = field(default_factory=list)
    # 本文に戻した（"returned"）範囲に、注の番号で始まる段落（本当の注の一覧かもしれない）があったときの、「注」の段落 ID -> その段落 ID の一覧
    fn_guess_numbered: dict = field(default_factory=dict)
    # 手で書いた注と Word の脚注・文末脚注の両方にある注の番号（Word の注の番号は 1 から付けるので重なる。要確認）
    note_overlap: list = field(default_factory=list)
    # 番号から図・表を決められず、リンクしなかった図・表の参照: (「図」か「表」, 段落 ID, 参照の文字)。同じ種類のキャプションの番号が
    # 重なる・キャプションに枝番がある（図1-1・図1-2）ときの参照（linker.Linker.float_refs。要確認）
    float_unlinked: list = field(default_factory=list)
    # 文字だけのテキストボックスの ID -> BoxInfo（Classifier.place_boxes が扱ったもの。空白だけのものも。出現順）
    textboxes: dict = field(default_factory=dict)

    @property
    def unplaced_floats(self) -> list:
        return [fid for fid, info in self.floats.items() if info.mode == "unplaced"]

    @property
    def undecided_boxes(self) -> list:
        """囲みか図の注記か決められず、除外した文字だけのテキストボックスの ID（要確認）。"""
        return [x for x, info in self.textboxes.items() if info.kind == "undecided"]

    @property
    def estimated_boxes(self) -> list:
        """位置を推定して置いた囲みの ID（要確認）。"""
        return [x for x, info in self.textboxes.items() if info.kind == "box" and info.estimated]

    def box_place(self, xid) -> str:
        """囲みを置いた位置の説明（レポート・Colab・コマンドライン・判断の記録で使う）。例: 段落「…」の前 / 段落「…」の後ろ /
        本文の最後。後ろに置いた段落に文字がなければ、その前にある、文字のある本文の段落で示す（float_place と同じ）。"""
        info = self.textboxes[xid]
        if info.where == "end":
            return "本文の最後"
        if info.where == "before":
            p = self.paras.get(info.after_src)
            if p is not None and _para_text(p).strip():
                return f"段落「{_para_text(p).strip()[:20]}」の前"
        seq = self.body_seq
        k = seq.index(info.after_src) if info.after_src in seq else -1
        if info.where == "before":
            k -= 1      # 空のアンカー段落の前に置いた: その前の、文字のある段落の後ろ
        while k >= 0:
            p = self.paras.get(seq[k])
            if p is not None and _para_text(p).strip():
                return f"段落「{_para_text(p).strip()[:20]}」の後ろ"
            k -= 1
        return "本文の最初"

    def float_text_src(self, fid):
        """位置を決められない図表を仮に置いた位置を示す、文字のある本文の段落の ID（本文の最後に置いたもの・見つからないものは
        None）。

        仮に置いた位置のすぐ前の段落（アンカー段落。箇条書き・引用の途中なら、その最後の段落。FloatInfo.after_src）に文字が
        なければ（空の段落など）、その前にある、文字のある本文の段落（XML の中で図表を探す手がかり。レポートの 3 章の場所にも使う）。
        """
        info = self.floats[fid]
        if info.where == "end":
            return None
        seq = self.body_seq
        start = info.after_src or info.float.anchor_src
        k = seq.index(start) if start in seq else -1
        while k >= 0:
            p = self.paras.get(seq[k])
            if p is not None and _para_text(p).strip():
                return seq[k]
            k -= 1
        return None

    def float_place(self, fid) -> str:
        """位置を決められない図表を仮に置いた位置の説明（レポート・Colab・コマンドライン・判断の記録で使う）。

        例: 段落「図1は表で組んだ問題である。この」の後ろ / 本文の最後。段落は float_text_src（アンカー段落、またはアンカー段落を
        含む箇条書き・引用の最後の段落。文字がなければ、その前にある、文字のある本文の段落）。
        """
        if self.floats[fid].where == "end":
            return "本文の最後"
        src = self.float_text_src(fid)
        return f"段落「{_para_text(self.paras[src]).strip()[:20]}」の後ろ" if src else "本文の最初"

    def no_link_paras(self) -> dict:
        """XML に出力するが、Word の脚注・文末脚注の参照（注の番号）をリンクにしない段落: 段落 ID -> 段落の種類（「題目」など）。

        題目・副題（和文・英文）・著者名・所属・引用文献の段落。builder はこれらを emit の xref=False の文脈（TITLE・NAME・AFF・
        REF）で書き出すので、注の番号は上付きの文字だけになる（上付きを置けない NAME では、番号も出さない）。Word の注の
        リンクの有無（FnNode.linked。Classifier.attach_word_notes）と、レポートの 1 章のリンクの数（report.word_note_refs）・
        8 章の表が使う。builder の書き出しの文脈を変えたら、ここも合わせる（tests/test_notes.py が XML の注へのリンクと照らして
        確かめる）。
        """
        out = {}
        for kind, paras in (("題目", self.title), ("副題", self.subtitle), ("英文題目", self.title_en),
                            ("英文副題", self.subtitle_en),
                            ("著者名", [p for a in self.authors for p in (a.name_ja, a.name_en) if p is not None]),
                            ("所属", [p for aff in self.affs for p in (aff.ja, aff.en) if p is not None]),
                            ("引用文献", [r.para for r in self.refs])):
            for p in paras:
                out.setdefault(p.src, kind)
        return out

    def unlinked_places(self, refs) -> tuple:
        """本文からのリンクのない Word の注（FnNode.linked が偽）の、参照のある段落 refs（FnNode.word_refs）を分ける:
        (XML に出力しなかった段落の ID の列, 注の番号をリンクにしない段落〈no_link_paras〉の「題目の段落 d3」の形の列)。
        判断の一覧と、レポートの 8 章の表の説明に使う。"""
        nolink = self.no_link_paras()
        return [s for s in refs if s not in nolink], [f"{nolink[s]}の段落 {s}" for s in refs if s in nolink]

    def decide(self, stage, category, src, message, confidence="", applied=True) -> Decision:
        if self._counted != len(self.decisions):        # decisions を直接足した・減らしたときだけ数え直す（通常は O(1)）
            self._stage_counts = {}
            for x in self.decisions:
                self._stage_counts[x.stage] = self._stage_counts.get(x.stage, 0) + 1
        n = self._stage_counts.get(stage, 0) + 1
        self._stage_counts[stage] = n
        d = Decision(did=f"{'M' if stage == 'mechanical' else 'A'}-{n:03d}", stage=stage,
                     category=category, src=src, message=message, confidence=confidence,
                     location=self.locations.get(src, ""), applied=applied)
        self.decisions.append(d)
        self._counted = len(self.decisions)
        return d

    def exclude(self, para: Para, reason: str):
        text = _para_text(para)
        self.exclusions.append(Exclusion(src=para.src, reason=reason, text=text))

    def exclude_blank(self, para: Para):
        """空白だけの段落を、理由「空白のみの段落」で除外に記録する（文字がまったくない段落は記録しない）。

        理由「空白のみの段落」の除外は、ここだけで作る（blank=True を付ける）。不変性チェック（fidelity.verify）は、blank の除外の
        docx の文字が本当に空白だけかを確かめる（空白以外の文字があれば、変換ツールの不具合として不合格）。
        """
        if para.plain():
            self.exclusions.append(Exclusion(src=para.src, reason="空白のみの段落", text=_para_text(para), blank=True))


def _para_text(para: Para) -> str:
    return "".join(a.text for a in para.atoms if a.kind == "text")
