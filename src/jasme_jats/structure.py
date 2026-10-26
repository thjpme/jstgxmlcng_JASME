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
from .model import Decision, Exclusion, Float, Para, Table, note_key, note_label
from .ooxml import is_ws

BODY_ROLES = {"sec1", "sec2", "sec3", "p", "fig_caption", "table_caption", "quote", "fn"}
FRONT_JA_ROLES = {"title", "subtitle", "aff_ja", "author_ja"}
FRONT_EN_ROLES = {"title_en", "subtitle_en", "author_en", "aff_en", "abstract_heading", "abstract"}
BACK_HEADINGS = {"notes_heading": "notes", "ack_heading": "ack", "fn_heading": "fn", "ref_heading": "refs"}
HEADING_LEVEL = {"sec1": 1, "sec2": 2, "sec3": 3}

# 文字だけのテキストボックスの段落を除外したときの理由。レポートは、この理由の除外の件数を、冒頭と 14 章に「要確認」として
# 出す（文字だけのテキストボックスを XML に出力できるようになるまでの暫定の知らせ。report.provisional_exclusions）
TEXTBOX_TEXT_EXCLUDED = "テキストボックス内の文字（図の一部とみなして本文から除外）"
# 位置を決められない図表を仮に置く位置のうち「本文の最後」（本文の領域の最後の要素の後ろ）。place_floats の差し込み位置
BODY_END = float("inf")
# 本文より後ろにある領域（ArticlePlan.region の値）。AI がこれらの段落の後ろを指定した図表は、本文の最後に仮に置く
# （ai_assist.float_placements。本誌のテンプレートでは、英文の部分・資料も本文より後ろ）
AFTER_BODY_REGIONS = {"notes", "ack", "fn", "refs", "back", "front_en", "app"}

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
# 資料（付録）の見出し: 「資料」「付録」「附録」「Appendix」で始まる段落（英文要旨の後ろで、資料の始まりとみなす。build_front_en）。
# 先頭の開き括弧を 1 つ許す（「【資料1】」「（資料3）」。閉じ括弧はそろえなくてよい）。語の後ろの番号は、数字・英字・
# Ⅰ-Ⅻ・ⅰ-ⅻ・①-⑳で、前に空白と全角のハイフン「－」・ハイフン「‐」、後ろに枝番（「資料1-2」）を許す。番号の直後には、
# 空白・コロン・ピリオド・読点・括弧・ダッシュ・行末だけを許す（「資料1を配布した」「資料12の結果」は本文の文）。ASCII の
# ハイフン「-」は語の直後に許さない（「資料-1」は本文の文とみなす。枝番の区切りにだけ使う）。番号がないときは、語の直後に
# 空白・コロン・括弧・ダッシュ・行末だけを許す（「資料、図表」「資料.」は本文の文）。この形に合う文（「資料1、2は…である。」
# 「Appendix shows ….」）は appendix_sentence で見分ける
_APP_OPEN = "【［\\[〔〈《＜<(（"
_APP_CLOSE = "】］\\]〕〉》＞>)）"
_APP_DASH = "－‐‒–—―"          # ASCII のハイフン「-」は入れない（枝番の区切りにだけ使う）
_APP_NUM = "[0-9０-９A-ZＡ-Ｚ]+|[Ⅰ-Ⅻ]|[ⅰ-ⅻ]|[①-⑳]"
RE_APPENDIX = re.compile(
    rf"^{_WS}[{_APP_OPEN}]?{_WS}(?:資料|付録|附録|Appendix)"
    rf"(?:{_WS}[－‐]?{_WS}(?:{_APP_NUM})(?:[-{_APP_DASH}](?:{_APP_NUM}))*"                 # 番号（前に全角のハイフン、後ろに枝番）
    rf"(?=[\s\u3000:：.．、,，{_APP_OPEN}{_APP_CLOSE}{_APP_DASH}]|$)"                      # 番号の直後
    rf"|(?=[\s\u3000:：{_APP_OPEN}{_APP_CLOSE}{_APP_DASH}]|$))")                           # 番号のないとき、語の直後
# RE_APPENDIX に合う段落のうち、文の形のもの（appendix_sentence。資料の見出しとみなさない）を見分ける規則。和文の文は、語・番号の
# 後ろにかな・漢字があり、段落が「。」か「．」で終わるもの（「資料1、2は…である。」。括弧・かぎ括弧の中の「。」〈「資料2　…
# （下線は筆者。）」〉は段落の終わりでないので数えない）。英文の文は、語・番号（と閉じ括弧）の後ろが「空白 + 英小文字」で、
# かな・漢字がなく、段落が「.」「?」「!」で終わるもの（「(Appendix 1) lists ….」。「Appendix 1 questionnaire」「資料2 iPad の画面」は見出し）
RE_APPENDIX_SENTENCE = re.compile(rf"[{_APP_CLOSE}]*[\s\u3000]+[a-z]")
RE_JA_SENTENCE_END = re.compile(r"[。．][\s\u3000]*$")
RE_EN_SENTENCE_END = re.compile(r"[.?!][\s\u3000]*$")
# かな・漢字（英文要旨の中の和文の段落の判定。config.RE_JA_CHARS は全角英数字も含むので使わない）
RE_KANA_KANJI = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff々]")
ABSTRACT_JA_RATIO = 0.3        # 英文要旨の段落のうち、かな・漢字がこの割合以上なら和文の段落とみなして知らせる
# 引用文献などの後ろの資料の見出しと思われる段落を知らせるときの、後付けの節の名前（build_back。決定事項 8(b) は暫定で警告だけ）
APP_PLACE = {"refs": "引用文献", "fn": "注", "notes": "付記", "ack": "謝辞"}
# 注の番号をリンクにしない段落の種類（ArticlePlan.no_link_paras。判断の一覧と、レポートの 8 章の表で知らせる）
NO_LINK_KINDS = "題目・副題・著者名・所属・引用文献"


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


def appendix_sentence(text: str) -> str:
    """資料の見出しの形（RE_APPENDIX）に合う段落が文の形なら、その形の名前（判断の一覧の文言に使う）。合わない・文の形でなければ ''。

    和文の文: 語・番号の後ろにかな・漢字があり、段落が「。」か「．」で終わる（「資料1、2は授業の記録である。」「（資料1）に
    示すように、…。」）。括弧・かぎ括弧の中の「。」（「資料2　児童の記述（下線は筆者。）」「資料1　問い「なぜだろう。」の…」）は
    段落の終わりでないので、見出しのまま。英文の文: 語・番号（と閉じ括弧）の後ろが「空白 + 英小文字」で、かな・漢字がなく、
    段落が「.」「?」「!」で終わる（「(Appendix 1) lists ….」）。英文の終わりがない「Appendix 1 questionnaire」と、和文の
    「資料2 iPad の画面」は見出しのまま（0.23.1 と同じ）。
    """
    m = RE_APPENDIX.match(text)
    if not m:
        return ""
    rest = text[m.end():]
    if RE_KANA_KANJI.search(rest):
        return "「。」か「．」で終わる和文の文" if RE_JA_SENTENCE_END.search(rest) else ""
    if RE_APPENDIX_SENTENCE.match(rest) and RE_EN_SENTENCE_END.search(rest):
        return "番号などの後ろが英小文字の語で、「.」などで終わる英文の文"
    return ""


def appendix_heading(text: str) -> bool:
    """段落の文字が資料（付録）の見出しの形か（英文要旨の後ろの資料の始まり〈build_front_en〉と、引用文献などの後ろの資料の
    知らせ〈build_back〉で使う）。RE_APPENDIX に合い、文の形（appendix_sentence）でないもの。
    """
    return bool(RE_APPENDIX.match(text)) and not appendix_sentence(text)


def unreferenced_note_reason(key: str, deleted: bool) -> str:
    """本文から参照されていない Word の脚注・文末脚注を除外したときの理由（レポートの 6 章）。

    deleted: 参照が削除の変更履歴の中にだけある（Word で変更をすべて承諾すると、注も消える）。
    """
    if deleted:
        return f"{note_label(key)}（本文の参照が変更履歴で削除された注。Word で変更をすべて承諾すると消える）"
    return f"{note_label(key)}（本文から参照されていない注）"


def no_link_rule(kinds) -> str:
    """注の番号をリンクにしない段落の中の、Word の注の参照の書き出し方（判断の一覧の説明）。

    kinds: 参照のある段落の種類（ArticlePlan.no_link_paras の値。「題目」「著者名」など）。題目・所属・引用文献などでは
    上付きの番号だけを出し、著者名では番号も出さない（著者名の要素には上付きの文字を置けない。emit.Emitter.write_object）。
    """
    kinds = list(dict.fromkeys(kinds))
    out = []
    shown = [k for k in kinds if k != "著者名"]
    if shown:
        out.append(f"{'・'.join(shown)}の中の注の番号は、リンクにせず上付きの番号だけにする")
    if "著者名" in kinds:
        out.append("著者名の中の注の番号は、著者名に上付きの文字を置けないので出力しない")
    return "。".join(out)


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
    # 手で書いた注と Word の脚注・文末脚注の両方にある注の番号（Word の注の番号は 1 から付けるので重なる。要確認）
    note_overlap: list = field(default_factory=list)

    @property
    def unplaced_floats(self) -> list:
        return [fid for fid, info in self.floats.items() if info.mode == "unplaced"]

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
        n = sum(1 for x in self.decisions if x.stage == stage) + 1
        d = Decision(did=f"{'M' if stage == 'mechanical' else 'A'}-{n:03d}", stage=stage,
                     category=category, src=src, message=message, confidence=confidence,
                     location=self.locations.get(src, ""), applied=applied)
        self.decisions.append(d)
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


def in_shape(b) -> bool:
    """図形（テキストボックス・グループ図形）の中の段落・表か（Para・Table の in_textbox または float_id）。"""
    return b.in_textbox or bool(b.float_id)


def float_caption(info) -> str:
    """浮動配置の図形の中のキャプション（表のセルの中のものも）の冒頭。レポート・Colab・コマンドラインで図表を示すのに使う。"""
    caps = []
    for q in info.paras + [c for t in info.tables for c in t.paragraphs()]:
        t = nfkc(q.plain()).strip()
        if RE_FIGCAP.match(t) or RE_TABCAP.match(t):
            caps.append(f"「{q.plain().strip()[:20]}」")
    return "".join(caps) or "キャプションなし"


def float_ids(plan, info) -> str:
    """浮動配置の図形の中身を出力した図・表の ID（F1、T2 など。「・」でつなぐ）。表のセルの画像とキャプションで組んだ図、
    表のない表キャプションも（キャプションのない図には ID がないので出ない）。レポート・Colab・コマンドラインで、XML の中の
    図表を示すのに使う。"""
    paras = {id(q) for q in info.paras} | {id(q) for t in info.tables for q in t.paragraphs()}
    tables = {id(t) for t in info.tables}
    ids = [f.fid for f in plan.figures if f.fid and (
        any(id(q) in paras for q in f.image_paras + ([f.caption] if f.caption is not None else []))
        or any(id(t) in tables for t in f.tables))]
    ids += [t.tid for t in plan.tables if (t.table is not None and id(t.table) in tables)
            or (t.caption is not None and id(t.caption) in paras)]
    return "・".join(ids)


def float_targets(plan, info) -> str:
    """浮動配置の図形の中身を出力した XML の要素の説明（手作業で移す図表の知らせ。レポート・Colab・コマンドラインで使う）。

    図・表の ID（float_ids）と、図形の中身から本文の段落として出した段落（画像と文字が同じ段落の文字など。図の直後に出す）。
    ID のある図表か段落があれば、キャプションのない図（ID がない）も数える（知らせどおりに移したときに、図形の中身が仮の位置に
    残らないように）。例: 「F1・F2 と段落「説明文：左のセルの画像と同じ段」」「F1 とキャプションのない図」「段落「…」」。
    どれもなければ（キャプションのない図だけのときなど）空文字で、呼び出し側は「図表の中身」と示す。
    """
    mine = {id(q) for q in info.paras} | {id(q) for t in info.tables for q in t.paragraphs()}

    def walk(nodes):
        for node in nodes:
            if isinstance(node, Sec):
                yield from walk(node.children)
            else:
                yield node

    nodes = list(walk(plan.body))
    nocap = sum(1 for n in nodes if isinstance(n, FigNode) and not n.fid and any(id(q) in mine for q in n.image_paras))
    paras = [q for n in nodes if not isinstance(n, (FigNode, TableNode)) for q in Classifier.node_paras(n) if id(q) in mine]
    ids = float_ids(plan, info)
    items = [ids] if ids else []
    if ids or paras:
        if nocap:
            items.append("キャプションのない図" + (f" {nocap} つ" if nocap > 1 else ""))
        if paras:
            items.append("段落" + "".join(f"「{_para_text(q).strip()[:20]}」" for q in paras))
    out = ""
    for item in items:
        out += ((" と" if out[-1].isascii() else "と") + item) if out else item
    return out


def same_place(flat, provisional) -> tuple:
    """本文の要素の列 flat の要素ごとに、同じ置き場所の、すぐ前・すぐ後ろの要素の位置（なければ None）。戻り値: (前, 後ろ)。

    置き場所は、位置を決められない図表（仮の位置に置いた図形）の中身なら仮に置いた位置（provisional: 要素の id -> 置き場所。
    同じ位置に仮に置いた図形の中身は同じ値）、それ以外（図形の外の要素と、位置の決まった図形の中身）は ""。仮に置いた図形の
    中身は本当はそこにないので、図表の組み立てで前後を見るときは、同じ置き場所の要素だけを見る（Classifier.assemble_floats・
    build_body）。同じ位置に仮に置いた図形の中身どうし（同じ段落に結び付いた、画像だけの図形とキャプションだけの図形など）は
    隣り合う要素として見る。
    """
    n = len(flat)
    here = [provisional.get(id(b), "") for _, b in flat]
    prev, nxt, last = [None] * n, [None] * n, {}
    for k in range(n):
        prev[k] = last.get(here[k])
        last[here[k]] = k
    last = {}
    for k in range(n - 1, -1, -1):
        nxt[k] = last.get(here[k])
        last[here[k]] = k
    return prev, nxt


# ----------------------------------------------------------------------------- roles
class Classifier:
    def __init__(self, doc, journal, overrides=None, placements=None):
        self.doc = doc
        self.journal = journal
        self.mapping = journal.styles
        self.overrides = overrides or {}      # src -> role（AI 補完）
        self.placements = placements or {}    # 浮動配置の図形の ID -> 配置の指定（AI 補完。ai_assist.float_placements）
        # 仮の位置に置いた図形の中身: 本文の要素（flat）の id -> 置き場所（仮に置いた位置。同じ位置に仮に置いた図形の中身は同じ値。
        # build_body）
        self.provisional = {}
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
        for kind, notes in (("footnote", self.doc.footnotes), ("endnote", self.doc.endnotes)):
            for nid, paras in notes.items():
                for p in paras:
                    plan.paras[p.src] = p
                    plan.note_of[p.src] = note_key(kind, nid)

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
        """ブロックを領域（和文の冒頭・本文・後付け・英文の部分）に分ける。

        領域は、段落の役割（スタイル）と文字から、図形の外のブロックだけで決める。図形（テキストボックス・グループ図形）の
        中の段落・表では状態を変えず（図形の中のセクション区切りでも切り替えず）、その時点の領域に入れる。テキストボックスの
        中の「英文要旨」スタイルの段落や「注」だけの段落で、以降の本文と引用文献が英文要旨や注に入るのを防ぐため。
        図形の中身は結び付いている段落（アンカー段落）の後ろに並ぶので、アンカー段落と同じ領域に入る。ただし、アンカー段落が
        和文の冒頭の最後の段落（セクション区切り）なら、切り替えた後の本文に入る（テンプレートの冒頭に図形はないので、本文の
        中身とみなす）。図形の中の題目の段落は「題目を見た」ことにする（題目をテキストボックスに入れた原稿でも、冒頭の最後の
        セクション区切りで本文に切り替えるため）。
        """
        regions = {"front_ja": [], "body": [], "back": [], "front_en": []}
        state = "front_ja"
        seen_title = False
        for b, role in flat:
            if in_shape(b):
                seen_title = seen_title or (state == "front_ja" and role == "title")
                regions[state].append((b, role))
                continue
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
                        if p.is_blank:
                            plan.exclude_blank(p)
                        else:
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
                plan.exclude_blank(b)
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
                            self.plan.exclude_blank(p)
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
            self.plan.exclude_blank(p)
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
        items, inserts, raw, prov = self.place_floats(items)
        flat = []
        for b, role in items:
            # 位置を決められない図表のうち、中身をそのまま出すものの要素は、役割をここで決めてから、その図表の差し込みに入れる
            # （仮に置く位置。place_floats）
            out = raw.get(id(b), flat)
            if isinstance(b, Table):
                out.append(("table", b))
                for tp in b.paragraphs():
                    plan.region[tp.src] = "body"
                    tp.role = tp.role or "cell"
                continue
            plan.region[b.src] = "body"
            if b.in_textbox and role not in ("fig_caption", "table_caption") and not b.images:
                cap = self.textbox_caption(b)
                if cap is None:
                    if b.is_blank:
                        plan.exclude_blank(b)      # 全角空白だけの段落も記録する（記録しないと出力漏れになる）
                    else:
                        plan.exclude(b, TEXTBOX_TEXT_EXCLUDED)
                    continue
                role = cap
                b.role_origin = "heuristic"
                kind = "図" if cap == "fig_caption" else "表"
                plan.decide("mechanical", "style", b.src,
                            f"テキストボックス内のスタイル「{b.style_name}」の段落「{_para_text(b)[:30]}」を"
                            f"{kind}キャプションと推定（「{kind}N」で始まる）")
            if b.is_blank:
                plan.exclude_blank(b)
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
            out.append((role, b))

        # 配置を決めた浮動配置の図表を、決めた位置（items での位置）に差し込む。本文の最後（BODY_END）は最後に足す
        merged, pending = [], sorted(inserts, key=lambda x: (x[0], x[1]))
        for entry in flat:
            while pending and pending[0][0] <= order[id(entry[1])]:
                merged.extend(pending.pop(0)[2])
            merged.append(entry)
        for _, _, entries in pending:
            merged.extend(entries)
        flat = merged
        # 位置を決められない図表（仮の位置に置いた図形）の中身。本当はそこにないので、図表を組み立てるときに、その外の要素と
        # 組にしない（assemble_floats・table_for_figure）。置き場所は仮に置いた位置で、同じ位置に仮に置いた図形の中身どうし
        # （同じ段落に結び付いた、画像だけの図形とキャプションだけの図形など）は組にする
        self.provisional = {id(obj): f"@{target}" for target, entries in prov for _, obj in entries}

        # 本文スタイルのまま書かれた図表キャプションの推定（隣は同じ置き場所の要素。仮に置いた図形の中身とその外は隣にしない）
        before, ahead = same_place(flat, self.provisional)
        for k, (role, b) in enumerate(flat):
            if role != "p" or not isinstance(b, Para):
                continue
            t = nfkc(_para_text(b)).strip()
            if len(t) > 80 or t.endswith("。"):
                continue
            nxt = flat[ahead[k]] if ahead[k] is not None else (None, None)
            prv = flat[before[k]] if before[k] is not None else (None, None)
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
        - なければ、図の左上がアンカー段落の左上の位置にあり（floats.at_anchor）、中身が単純（キャプション 1 つと本体 1 つ、
          表のセルに画像とキャプションが並ぶ図など。float_mechanical）な場合だけ、機械的にアンカー段落の前に置く。
        - どちらでもなければ「位置を決められない図表」として記録し、仮の位置に置く（利用者が手作業で移す。決定事項 21）。
          仮の位置は、アンカー段落のすぐ後ろ。AI が本文の外（注・引用文献など）の段落の後ろを指定したとき（ai_assist.float_placements
          の印 where="end"）と、アンカー段落が本文の段落でないとき（今は起きない。修正計画の F）は、本文の最後（provisional_target）。
          中身が単純なら図の本体とキャプションを組にし、そうでなければ中身をそのまま（これまでの扱いで。役割は build_body で
          決める）出す。
        戻り値: (並べ直した items, [(items での位置, 同じ位置での順番, [(役割, 要素)])], 中身をそのまま出す図形の要素の id →
        その図形の差し込みの一覧, [(仮の位置に置いた図形の items での位置, その差し込みの一覧)])。items での位置は「その位置の要素の前」で、
        アンカー段落の後ろは アンカー段落の位置 + 1、本文の最後は BODY_END。同じ位置に置くものはキャプションの番号順（番号が
        なければ後ろ）、同じ番号なら docx の順
        """
        plan = self.plan
        src_index = {b.src: k for k, (b, _) in enumerate(items) if isinstance(b, Para)}
        plan.layout = getattr(self.doc, "layout", None)
        plan.body_seq = [b.src for b, _ in items if isinstance(b, Para) and not b.float_id]
        body = set(plan.body_seq)
        members, group_imgs, roles = {}, {}, {}
        for b, role in items:
            if b.float_id:
                members.setdefault(b.float_id, []).append(b)
                roles[id(b)] = role
            elif isinstance(b, Para):
                for img in b.images:
                    if img.float_id:
                        group_imgs.setdefault(img.float_id, []).append(img)
        placed, inserts, raw, prov = set(), [], {}, []
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
            end = bool(spec) and spec.get("where") == "end"     # AI が本文の外の段落の後ろを指定した（本文の最後に仮に置く）
            if spec and not end and spec["after"] not in src_index:
                spec = None     # AI の役割の指定で、指定された段落が本文でなくなった
            if spec and not end:
                entries = self.float_from_spec(info, spec)
                target = src_index[spec["after"]] + 1
                info.mode = "ai"
            else:
                entries = self.float_mechanical(info, groups, others) if at_anchor(fl, layout) and not end else None
                if entries is None:
                    info.mode = "unplaced"
                    info.reason = (why_not_at_anchor(fl, layout) if not at_anchor(fl, layout)
                                   else "中身の組み合わせ（図表の本体とキャプション）を機械的に決められない")
                    info.where, info.end_why, info.end_after, target = self.provisional_target(
                        fl, spec if end else None, src_index, body)
                    if info.where == "anchor":
                        # アンカー段落が箇条書き・引用の途中なら、その最後の段落の後ろにずらす（箇条書き・引用を 2 つに分けない）
                        last = self.run_end(items, target - 1)
                        info.after_src, target = items[last][0].src, last + 1
                    place = ("AI が本文の外の段落の後ろを指定したので、本文の最後に仮に置く" if info.end_why == "ai"
                             else f"指定がなければ{plan.float_place(fl.fid)}に仮に置く")
                    plan.decide("mechanical", "figure", fl.anchor_src,
                                f"テキストボックス・グループ図形 {fl.fid}（{self.float_summary(info)}）は、位置を機械的に"
                                f"決められない（{info.reason}）。AI による補完で位置を指定する必要がある（{place}）",
                                applied=False)
                    # 組み合わせは、中身が単純なら機械的に組む。単純でなければ中身をそのまま出す（build_body で役割を決めてから、
                    # この図形の差し込みに入れる）
                    entries = self.float_mechanical(info, groups, others)
                    if entries is None:
                        entries = []
                        for b in blocks:
                            raw[id(b)] = entries
                    else:
                        placed.update(id(b) for b in blocks)
                    inserts.append((target, (self.float_number(info), len(inserts)), entries))
                    prov.append((target, entries))
                    continue
                target = src_index[fl.anchor_src]
                info.mode = "mechanical"
                plan.decide("mechanical", "figure", fl.anchor_src,
                            f"テキストボックス・グループ図形 {fl.fid}（{self.float_summary(info)}）を、アンカー段落"
                            f"「{_para_text(plan.paras[fl.anchor_src])[:20]}」の前に置いた（図の左上がアンカー段落の左上の位置にあるため）")
            placed.update(id(b) for b in blocks)
            inserts.append((target, (self.float_number(info), len(inserts)), entries))
        rest = [(b, r) for b, r in items if id(b) not in placed]
        return rest, inserts, raw, prov

    @staticmethod
    def provisional_target(fl, end_spec, src_index, body) -> tuple:
        """位置を決められない図表を仮に置く位置（決定事項 21）。戻り値: (where, end_why, end_after, items での差し込み位置)。

        - AI が本文の外（注・引用文献など）の段落の後ろを指定した（end_spec。ai_assist.float_placements の印）: 本文の最後
        - アンカー段落が本文の段落（body。plan.body_seq）でない: 本文の最後。今の place_floats は本文にアンカーのある図形だけを
          扱うので起きないが、本文の外に結び付いた図形を扱うとき（修正計画の F の N7）にそのまま使えるように分けておく
        - それ以外: アンカー段落のすぐ後ろ（AI の指定の after と同じ形）。アンカー段落が箇条書き・引用の途中なら、place_floats が
          その箇条書き・引用の最後の段落の後ろにずらす（run_end）
        """
        if end_spec:
            return "end", "ai", end_spec.get("after", ""), BODY_END
        if fl.anchor_src not in body:
            return "end", "anchor", "", BODY_END
        return "anchor", "", "", src_index[fl.anchor_src] + 1

    def list_or_quote(self, b, role):
        """本文の要素 b（items の役割 role）が、assemble_floats で前後の段落と 1 つにまとめる箇条書きの項目か引用の段落なら、
        その種類（引用は "quote"、箇条書きは ("list", 番号の定義の ID)）。そうでなければ None。

        役割は build_body と同じ考えで見る（役割の決まっていない段落・本文の段落のうち、見出しと推定するものは箇条書きにしない）。
        画像だけの段落（図になる）と別行数式の段落（数式になる）は、assemble_floats と同じく箇条書きの項目にしない（箇条書きは
        その前で終わる）。画像と文字が同じ段落の項目は、箇条書きの項目のまま。図形の中の段落（XML に出さないものもある）は、
        箇条書きにしない（迷うものは None。仮の位置をずらさないだけ）。
        """
        if not isinstance(b, Para) or in_shape(b):
            return None
        if role == "quote":
            return "quote"
        if not (b.numbering and b.autonum) or self.is_image_para(b) or self.formula_node(b) is not None:
            return None
        if role in ("normal", None, "") or role not in BODY_ROLES | {"table"}:
            heading = self.guess_heading(b, strict=False)
        elif role == "p":
            heading = self.guess_heading(b, strict=True)
        else:
            return None
        return None if heading else ("list", b.numbering[0])

    def run_end(self, items, k) -> int:
        """仮に置く位置のすぐ前の要素 items[k]（アンカー段落）が、続いた箇条書きの項目（同じ番号の定義）か引用の段落の途中に
        あれば、その並びの最後の段落の位置。そうでなければ k。

        位置を決められない図表をアンカー段落のすぐ後ろに仮に置くと、箇条書き・引用が 2 つに分かれ、図表を手作業で移しても
        分かれたまま残るため（assemble_floats は、続いた箇条書きの項目と引用の段落を 1 つの list・disp-quote にまとめる）。
        AI が指定した位置はずらさない。間の図形の中身と空白だけの段落は飛ばす（その位置には出力しない）。アンカー段落が空の
        段落なら、その前の要素で見る。
        """
        def skip(b):
            return bool(b.float_id) or (isinstance(b, Para) and b.is_blank)

        prev = next((j for j in range(k, -1, -1) if not skip(items[j][0])), None)
        want = self.list_or_quote(*items[prev]) if prev is not None else None
        if want is None:
            return k
        last = k
        for j in range(k + 1, len(items)):
            b, role = items[j]
            if skip(b):
                continue
            if self.list_or_quote(b, role) != want:
                break
            last = j
        return last

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
        """浮動配置の図形の中身の要約（レポート用）: キャプションの冒頭と、本体の種類（表のセルの中のキャプション・画像も）。"""
        paras = info.paras + [c for t in info.tables for c in t.paragraphs()]
        texts = [nfkc(_para_text(q)).strip() for q in paras if not q.is_blank]
        caps = [t[:20] for t in texts if RE_FIGCAP.match(t) or RE_TABCAP.match(t)]
        body = (["画像"] if info.images or any(q.images for q in paras) else []) + (["表"] if info.tables else [])
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
        self.plan.exclude_blank(p)

    def float_mechanical(self, info, groups, others):
        """位置が機械的に決まる浮動配置の図形の中身を組む。中身が単純でなければ None（AI に任せる）。

        単純な中身: キャプション 1 つと本体 1 つ（画像・表）、または表 1 つだけで、そのセルに画像とキャプションが並ぶ図
        （cell_figures）。画像と文字が同じ段落は、図に組むときは画像を図に移し、段落は文字ごと図の直後に本文の段落として出す。
        キャプションのない図形は図にしないので、これまでどおり画像も文字も段落のまま出す。表 1 つだけの図形で、セルの画像と
        キャプションの組み方が一つに決まらないものも、これまでどおり（0.21.0 と同じ）キャプションのない表として出す。
        """
        image_paras = [q for q in info.paras if q.images]
        if len(info.tables) == 1 and not (groups or others or image_paras or info.images):
            cells = self.cell_figures(info)
            if cells is not None:
                return cells        # 表のセルに画像とキャプションが並ぶ図
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
        # 画像と文字が同じ段落（画像だけの段落でないもの）は、画像を図に移し（段落の中では出さない）、
        # 段落は文字ごと図の直後に本文の段落として出す
        mixed = [q for q in image_paras if not self.is_image_para(q)]
        extra = list(info.images) + [i for q in mixed for i in q.images]
        for q in mixed:
            self.plan.decide("mechanical", "figure", q.src,
                             f"テキストボックス・グループ図形 {info.float.fid} の段落「{_para_text(q).strip()[:20]}」は、"
                             "画像と文字が同じ段落にある。画像は図に入れ、段落の文字は図の直後に本文の段落として出した")
        self.plan.moved_images.update(i.image_id for i in extra)
        return ([("node", FigNode(image_paras=[q for q in image_paras if q not in mixed], caption=caps[0],
                                  caption_more=caps[1:], tables=list(info.tables), extra_images=extra))]
                + [("p", q) for q in mixed])

    def cell_caption(self, q: Para) -> str | None:
        """表のセルの段落がキャプションか（キャプションのスタイル、またはキャプションの形。float_captions と同じ考え）。

        表のセルの段落には items の役割がないので、スタイルから求める（role_of）。
        """
        role = self.role_of(q)
        return role if role in ("fig_caption", "table_caption") else self.textbox_caption(q)

    def cell_figures(self, info):
        """浮動配置の図形の中の表 1 つのセルに、画像と図キャプションが並ぶ図（N18）を、表を出さずに図に組む。

        戻り値: 組んだ要素の一覧。組まないときは None で、呼び出し側（float_mechanical）がこれまで（0.21.0）の扱いにする
        （キャプションのない表として出す。位置が機械的に決まる図形はアンカー段落の前に置き、位置を決められない図形は今までどおり
        AI に任せる）。
        - 図キャプションが表全体で 1 つ: すべてのセルの画像（行・列の順）を本体にした図 1 つ
        - 2 つ以上: どのセルも「画像とキャプション 1 つ」か「空白だけ」なら、セルごとの図。画像だけのセルとキャプション 1 つだけの
          セルが並ぶ表（画像の行とキャプションの行など）は、隣り合う画像とキャプションの組が一つに決まるときだけ（cell_pairs）
        組まない（None）とき: セルに画像と番号で始まる図キャプションの両方がない（この形ではない。セルに図キャプションと問題文
        だけがある表で組んだ図も、表のまま出す）、表キャプションがある、キャプションでも画像でもない文字の段落（「（a）」などの
        小見出しも。表の構造を捨てると読めなくなるおそれがある）や入れ子の表がある、画像とキャプションの組を一つに決められない。
        組むときのセルの段落は、画像の段落・キャプション（とその続きの出典など）・空白だけなので、表を出さなくても文字は落ちない。
        画像と文字が同じ段落は、float_mechanical と同じく、画像を図に移し、段落は文字ごと図の直後に本文の段落として出す。
        状態を変えるのは、組めると決まってから（float_mechanical と同じ約束）。
        """
        t = info.tables[0]
        grid, blanks = [], []          # grid: 行ごとの [(画像の段落の一覧, [キャプションの組（段落の一覧）…])]
        n_img = n_cap = 0
        stop = False                   # 表キャプション・キャプションでない文字の段落・入れ子の表がある
        for row in t.rows:
            line = []
            for c in row.cells:
                imgs, caps, prev_cap = [], [], False
                for q in c.blocks:
                    if isinstance(q, Table):
                        stop, prev_cap = True, False
                        continue
                    if q.images:
                        imgs.append(q)
                        prev_cap = False
                        continue
                    if q.is_blank:
                        blanks.append(q)
                        continue
                    text = nfkc(_para_text(q)).strip()
                    if self.cell_caption(q) == "fig_caption" and RE_FIGCAP.match(text):
                        caps.append([q])
                        prev_cap = True
                    elif prev_cap and self.role_of(q) == "fig_caption" and not RE_TABCAP.match(text):
                        caps[-1].append(q)          # 番号で始まらないキャプションの続き（出典など。float_captions と同じ）
                    else:
                        stop, prev_cap = True, False    # 表キャプション、キャプションでない文字の段落
                line.append((imgs, caps))
                n_img += len(imgs)
                n_cap += len(caps)
            grid.append(line)
        if not (n_cap and n_img) or stop:
            return None
        cells = [x for line in grid for x in line]
        if n_cap == 1:
            figs = [([q for imgs, _ in cells for q in imgs], next(caps[0] for _, caps in cells if caps))]
        elif all((imgs and len(caps) == 1) or not (imgs or caps) for imgs, caps in cells):
            figs = [(imgs, caps[0]) for imgs, caps in cells if caps]
        else:
            figs = self.cell_pairs(t, grid)
            if figs is None:
                return None
        # ここから先は必ず組む
        plan = self.plan
        plan.decide("mechanical", "figure", info.float.anchor_src,
                    f"テキストボックス・グループ図形 {info.float.fid} の表 {t.tid} のセルにある画像とキャプションを、図"
                    + "、".join(f"「{_para_text(caps[0]).strip()[:20]}」" for _, caps in figs) + "に組んだ（表としては出力しない）")
        for q in blanks + [q for q in info.paras if q.is_blank and not q.images]:
            self._drop_blank(q)
        entries = []
        for imgs, caps in figs:
            plan.cell_paras.update(q.src for q in imgs + caps)
            for q in imgs:
                self._take(q, "p")
            for q in caps:
                self._take(q, "fig_caption", self._caption_decision(q, "fig_caption"))
            mixed = [q for q in imgs if not self.is_image_para(q)]
            for q in mixed:
                plan.decide("mechanical", "figure", q.src,
                            f"テキストボックス・グループ図形 {info.float.fid} の段落「{_para_text(q).strip()[:20]}」は、"
                            "画像と文字が同じ段落にある。画像は図に入れ、段落の文字は図の直後に本文の段落として出した")
            extra = [i for q in mixed for i in q.images]
            plan.moved_images.update(i.image_id for i in extra)
            entries.append(("node", FigNode(image_paras=[q for q in imgs if q not in mixed], caption=caps[0],
                                            caption_more=caps[1:], extra_images=extra)))
            entries.extend(("p", q) for q in mixed)
        return entries

    @staticmethod
    def cell_pairs(t, grid):
        """画像だけのセルとキャプション 1 つだけのセルが並ぶ表で、画像とキャプションの組を決める（cell_figures）。

        同じ列で上下に隣り合う組（画像の行とキャプションの行など）か、同じ行で左右に隣り合う組で、表全体で向き
        （列ごとか行ごとか、画像が先かキャプションが先か）が一つに決まるときだけ組む（空白だけのセルは飛ばす）。
        結合したセルがある、行ごとのセルの数が違う、どの向きでも組めない・二つ以上の向きで組めるときは None。
        戻り値: [(画像の段落の一覧, キャプションの組)]（組の最初のセルの行・列の順）
        """
        if any(c.gridspan != 1 or c.vmerge for row in t.rows for c in row.cells) or len({len(line) for line in grid}) != 1:
            return None
        kind = {}
        for r, line in enumerate(grid):
            for c, (imgs, caps) in enumerate(line):
                if (imgs and caps) or len(caps) > 1:
                    return None
                if imgs or caps:
                    kind[(r, c)] = "img" if imgs else "cap"
        nrow, ncol = len(grid), len(grid[0])
        found = []
        for lines in ([[(r, c) for r in range(nrow)] for c in range(ncol)],      # 列ごと（上下に隣り合う）
                      [[(r, c) for c in range(ncol)] for r in range(nrow)]):     # 行ごと（左右に隣り合う）
            for first, second in (("img", "cap"), ("cap", "img")):
                pairs = []
                for line in lines:
                    seq = [pos for pos in line if pos in kind]
                    if len(seq) % 2 or any(kind[pos] != (first, second)[k % 2] for k, pos in enumerate(seq)):
                        pairs = None
                        break
                    pairs += [(seq[k], seq[k + 1]) for k in range(0, len(seq), 2)]
                if pairs:
                    found.append(pairs)
        if len(found) != 1:
            return None
        out = []
        for a, b in sorted(found[0]):
            img, cap = (a, b) if kind[a] == "img" else (b, a)
            out.append((grid[img[0]][img[1]][0], grid[cap[0]][cap[1]][1][0]))
        return out

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
            image_paras, extra, tbls, mixed = [], [], [], []
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
                    if not self.is_image_para(q):
                        # 画像と文字が同じ段落: 画像は図に移し、段落は文字ごと図の直後に本文の段落として出す
                        if q not in mixed:
                            mixed.append(q)
                            extra.extend(q.images)
                            self._take(q, "p")
                            used.add(q.src)
                    elif q not in image_paras:
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
                entries.extend(("p", q) for q in mixed)
            what = "表" if item["kind"] == "table" else "図"
            body = "表" if tbls else "画像"
            if mixed:
                body += (f"。画像と文字が同じ段落 {', '.join(q.src for q in mixed)} は、画像を図に入れ、"
                         "文字は図の直後に本文の段落として出した")
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
        """図（画像段落＋図キャプション）と表（表キャプション＋表）を組み立て、本文の要素列にする。

        位置を決められない図表（仮の位置に置いた図形。self.provisional）の中身は、本当はそこにないので、その外の要素とは組に
        しない（図キャプションと画像、表キャプションと表、キャプションの続き、図の本体の表〈table_for_figure〉）。前後の要素は、
        同じ置き場所の要素（図形の外の要素なら図形の外の要素、仮に置いた図形の中身なら同じ位置に仮に置いた図形の中身）だけで
        数える（間に図形の中身を仮に置いていても、docx で隣り合う画像と図キャプションは組にする。同じ段落に結び付いた、画像だけの
        図形とキャプションだけの図形は、同じ位置に仮に置くので組にする）。
        """
        plan = self.plan
        out = []
        used = set()
        n = len(flat)
        prev, nxt = same_place(flat, self.provisional)
        where = {}                  # out の要素の id -> 置き場所（provisional の値。図形の外は ""）

        def put(node, k):
            out.append(node)
            where[id(node)] = self.provisional.get(id(flat[k][1]), "")

        def last_out(k, m=1):       # out の最後から、flat[k] と同じ置き場所の要素の位置（m 個まで。後ろから）
            here, got = self.provisional.get(id(flat[k][1]), ""), []
            for j in range(len(out) - 1, -1, -1):
                if len(got) == m:
                    break
                if where[id(out[j])] == here:
                    got.append(j)
            return got

        def ahead(k, m):            # flat[k] の後ろの、同じ置き場所の要素の位置（m 個まで）
            got, j = [], nxt[k]
            while j is not None and len(got) < m:
                got.append(j)
                j = nxt[j]
            return got

        below = sum(1 for k in range(n) if flat[k][0] == "fig_caption" and prev[k] is not None
                    and self.is_image_para(flat[prev[k]][1]))
        above = sum(1 for k in range(n) if flat[k][0] == "fig_caption" and nxt[k] is not None
                    and self.is_image_para(flat[nxt[k]][1]))
        captions_below = below >= above
        for k, (role, b) in enumerate(flat):
            if role == "node":          # 組み立て済みの図表（浮動配置の図形）
                put(b, k)
                continue
            if id(b) in used:
                continue
            last = last_out(k)
            if role in ("fig_caption", "table_caption") and last and prev[k] is not None \
                    and flat[prev[k]][1] is not None \
                    and isinstance(out[last[0]], FigNode if role == "fig_caption" else TableNode) \
                    and out[last[0]].caption is not None and flat[prev[k]][0] == role \
                    and not (RE_FIGCAP if role == "fig_caption" else RE_TABCAP).match(nfkc(_para_text(b)).strip()):
                # 番号で始まらないキャプション段落が続く → 直前のキャプションの続き
                out[last[0]].caption_more.append(b)
                plan.decide("mechanical", "figure" if role == "fig_caption" else "table", b.src,
                            f"キャプションの続きの段落「{_para_text(b)[:20]}」を直前の{'図' if role == 'fig_caption' else '表'}のキャプションに含めた")
                continue
            if role == "fig_caption":
                img = None
                for j in last_out(k, 2):
                    if isinstance(out[j], PNode) and self.is_image_para(out[j].para):
                        img = out.pop(j).para
                        break
                if img is None:
                    for j in ahead(k, 2):
                        # キャプションを画像の下に置く原稿では、直後に図キャプションがある画像はそのキャプションの図のもの
                        if captions_below and nxt[j] is not None and flat[nxt[j]][0] == "fig_caption":
                            continue
                        if self.is_image_para(flat[j][1]) and id(flat[j][1]) not in used:
                            img = flat[j][1]
                            used.add(id(img))
                            break
                fig = FigNode(image_paras=[img] if img else [], caption=b)
                if img is None:
                    # 画像がなければ、隣のキャプションのない表を図の本体にする（表で組んだ図。決定事項 22）
                    tbl, why = self.table_for_figure(flat, out, k, used, captions_below, self.provisional)
                    if tbl is not None:
                        fig.tables.append(tbl)
                        plan.decide("mechanical", "figure", b.src,
                                    f"画像のない図キャプション「{_para_text(b).strip()[:20]}」の"
                                    f"{'直前' if captions_below else '直後'}にある、キャプションのない表 {tbl.tid} を、"
                                    "図の本体として組んだ（図の中に表を入れる）")
                    elif why:
                        plan.figure_issues.append((b.src, why))
                        plan.decide("mechanical", "figure", b.src, f"図キャプションに対応する画像が見つからない（{why}）",
                                    applied=False)
                    else:
                        plan.decide("mechanical", "figure", b.src, "図キャプションに対応する画像が見つからない（図形・グループ化等の可能性）")
                put(fig, k)
                continue
            if role == "table_caption":
                tbl = None
                for j in ahead(k, 2):
                    if flat[j][0] == "table" and id(flat[j][1]) not in used:
                        tbl = flat[j][1]
                        used.add(id(tbl))
                        break
                if tbl is None and last and isinstance(out[last[0]], TableNode) and out[last[0]].caption is None:
                    out[last[0]].caption = b
                    continue
                if tbl is None:
                    plan.decide("mechanical", "table", b.src, "表キャプションに対応する表が見つからない")
                put(TableNode(table=tbl, caption=b), k)
                continue
            if role == "table":
                put(TableNode(table=b), k)
                continue
            if role in HEADING_LEVEL:
                put(Sec(level=HEADING_LEVEL[role], heading=b), k)
                continue
            if role == "quote":
                if out and isinstance(out[-1], QuoteNode):
                    out[-1].paras.append(b)
                else:
                    put(QuoteNode(paras=[b]), k)
                continue
            # 本文段落
            if self.is_image_para(b):
                put(PNode(b), k)   # 図キャプションが後に来れば図になる。最後まで残れば下で処理
                continue
            fnode = self.formula_node(b)
            if fnode:
                put(fnode, k)
                continue
            if b.numbering and b.autonum:
                ordered = not self.doc_numbering_is_bullet(b)
                if out and isinstance(out[-1], ListNode) and out[-1].items[-1].numbering[0] == b.numbering[0]:
                    out[-1].items.append(b)
                else:
                    put(ListNode(items=[b], ordered=ordered), k)
                continue
            put(PNode(b), k)
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
    def table_for_figure(flat, out, k, used, captions_below, provisional=None):
        """画像のない図キャプション flat[k] の本体にする、キャプションのない表（N19。決定事項 22: fig の中の table-wrap）。

        図キャプションを図の下に置く原稿（captions_below。画像の図がなければ下とみなす）では直前、上に置く原稿では直後の、
        キャプションのない表を本体にする。間にほかの段落があれば組まない（空白だけの段落は flat にない）。直後の表の次が
        表キャプションなら、その表は表キャプションのもの（表の下に表キャプションを置く書き方）かもしれないので組まない。
        位置を決められない図表（仮の位置に置いた図形。provisional: flat の要素の id → 置き場所〈仮に置いた位置〉）の中身は、
        本当はそこにないので、その外の要素とは組にしない。図キャプションの前後は、同じ置き場所の要素（図形の外の図キャプション
        なら図形の外の要素、仮に置いた図形の中の図キャプションなら同じ位置に仮に置いた図形の中身）だけで数える（間にほかの図形の
        中身を仮に置いていても、docx で隣り合う表と図キャプションは組にする）。
        直前の表は out（組み立て済み）から取り出す（後ろの表の ID が詰まる）。直後の表は used に入れる。
        戻り値: (表, "") / (None, 組めなかった理由。近くに表の候補があるとき) / (None, "")（近くにキャプションのない表がない）
        """
        provisional = provisional or {}
        here = provisional.get(id(flat[k][1]), "")
        near = [j for j in range(len(flat)) if provisional.get(id(flat[j][1]), "") == here]
        p = near.index(k)

        def at(d):          # 図キャプションから d 個先（負なら前）の、同じ置き場所の要素の flat での位置（なければ None）
            return near[p + d] if 0 <= p + d < len(near) else None

        def role(d):
            j = at(d)
            return flat[j][0] if j is not None else None

        def node(d):        # d 個前の要素が表なら、その TableNode（out の中。組み立て済み）
            j = at(d)
            if j is None or flat[j][0] != "table":
                return None
            return next((x for x in reversed(out) if isinstance(x, TableNode) and x.table is flat[j][1]), None)

        def before(d):      # d 個前の要素が、キャプションのない表か
            x = node(d)
            return x if x is not None and x.caption is None else None

        def after(d):       # d 個先の要素が、キャプションのない表か
            j = at(d)
            if j is None or flat[j][0] != "table" or id(flat[j][1]) in used:
                return False
            return role(d + 1) != "table_caption" and role(d - 1) != "table_caption"

        if captions_below:
            x = node(-1)
            if x is not None:
                if x.caption is None:
                    del out[next(i for i in range(len(out) - 1, -1, -1) if out[i] is x)]
                    return x.table, ""
                return None, f"直前の表に表キャプション「{_para_text(x.caption).strip()[:20]}」が付いている"
            if after(1):
                return None, ("直後にキャプションのない表があるが、この原稿は図キャプションを図の下に置いているため、"
                              "図の本体にしなかった")
            if before(-2) or before(-3):
                return None, "図キャプションの前にキャプションのない表があるが、間にほかの段落がある"
            return None, ""
        j = at(1)
        if j is not None and flat[j][0] == "table" and id(flat[j][1]) not in used:
            if role(2) == "table_caption":
                return None, "直後の表の次に表キャプションがあり、どちらの表か決められない"
            used.add(id(flat[j][1]))
            return flat[j][1], ""
        if before(-1):
            return None, ("直前にキャプションのない表があるが、この原稿は図キャプションを図の上に置いているため、"
                          "図の本体にしなかった")
        if after(2) or after(3):
            return None, "図キャプションの後ろにキャプションのない表があるが、間にほかの段落がある"
        return None, ""

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
                        if p.is_blank:
                            plan.exclude_blank(p)
                        else:
                            plan.refs.append(RefNode(para=p))
                    continue
                target = {"notes": plan.notes, "ack": plan.ack}.get(state)
                if target is not None:
                    target.children.append(TableNode(table=b))
                else:
                    for p in b.paragraphs():
                        if p.is_blank:
                            plan.exclude_blank(p)
                        else:
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
            if state in APP_PLACE and not b.is_blank and role != "ref" and appendix_heading(_para_text(b)):
                # 引用文献などの後ろの、資料の見出しと思われる段落（参考文献のスタイル以外で、「資料1　…」などの見出しの形の
                # 段落。見出しのスタイルでも文字で決める〈引用文献を分ける「＜英文献＞」などの小見出しを知らせない〉）。暫定の判断で、
                # 資料にはせず知らせるだけにする（決定事項 8(b) は利用者に未確認）。段落の扱い（引用文献の 1 件など）は変えない
                plan.app_after_refs.append(b.src)
                plan.warnings.append(f"{b.src}: {APP_PLACE[state]}の中に、資料の見出しと思われる段落「{_para_text(b).strip()[:20]}」"
                                     f"があります。今の版では、引用文献などの後ろの資料は資料として扱わず、{APP_PLACE[state]}の"
                                     "段落として出力しました")
            if b.is_blank:
                plan.exclude_blank(b)
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
        ai_abstract = False         # AI が abstract を指定した段落があった（後ろで資料が始まっていなければ、そこから英文要旨が続く）
        for b, role in items:
            if isinstance(b, Table):
                troles = self.table_roles(b)
                if troles & {"author_en", "aff_en"} and app is None:
                    for p in b.paragraphs():
                        r = self.role_of(p)
                        plan.region[p.src] = "authors"
                        p.role = p.role or r
                        if p.is_blank:
                            plan.exclude_blank(p)
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
                        if p.is_blank:
                            plan.exclude_blank(p)
                        else:
                            plan.exclude(p, "英文部分の表（著者表以外）の文字")
                continue
            plan.region[b.src] = "front_en"
            if b.is_blank:
                plan.exclude_blank(b)
                continue
            text = _para_text(b)
            ai = b.src in self.overrides
            by_style = by_text = False
            sentence = ""
            # 「資料1　…」などの見出しの形の段落（文の形の段落は除く。appendix_heading）と、英文要旨の後ろの、章・節・項見出しの
            # スタイルの段落（英文要旨の中に見出しは来ないので、資料の始まりとみなす。決定事項 8(a)。資料の中の見出しのスタイルの
            # 段落は、今までどおり資料の中の段落）。AI の指定がなければ、ここから資料を始める
            head_text = (in_abstract or app is not None) and appendix_heading(text)
            head_style = in_abstract and app is None and (self.style_role(b) if ai else role) in HEADING_LEVEL
            if ai and role in ("abstract", "p"):
                starts = False              # AI が資料の見出しではないと指定した（文字・見出しのスタイルより優先）
            elif role == "app_heading":
                starts = True               # AI が資料の見出しと指定した
            elif head_text:
                starts = by_text = True
            else:
                starts = by_style = head_style and b.role_origin == "style"
                if not starts and (in_abstract or app is not None):
                    # 見出しの形に合うが、文とみなした段落（判断の一覧に記録する。下。AI が役割を指定した段落は、上で決まる）
                    sentence = appendix_sentence(text)
            if ai and role == "abstract":
                app = None                  # AI の指定で英文要旨に戻す（後ろの段落も、次の資料の見出しまで英文要旨）
                ai_abstract = True
            elif ai and role == "p" and app is None and not (in_abstract and ai_abstract and not (head_text or head_style)):
                # AI が資料の中の段落と指定した段落の前に資料がない（最初の資料の見出しへの p など）: 見出しのない資料を始め、
                # その最初の段落にする（資料の文字を英文要旨に入れない。英文要旨に戻すのは abstract だけ）。ただし、AI が
                # abstract で英文要旨に戻した後ろの、見出しでない段落への p は、英文要旨のまま（資料を始めない）
                app = AppNode(title=None)
                plan.apps.append(app)
                in_abstract = False
            if starts:
                first = app is None
                app = AppNode(title=b)
                plan.apps.append(app)
                plan.region[b.src] = "app"
                plan.locations[b.src] = f"資料{len(plan.apps)}（見出し）"
                in_abstract = False
                head = text.strip()[:20]
                if by_style:
                    plan.decide("mechanical", "style", b.src,
                                f"英文要旨の後ろの、見出しのスタイル「{b.style_name}」の段落「{head}」から資料とした"
                                "（英文要旨の中に見出しは来ないため）。資料でなければ、Word でその段落のスタイルを英文要旨の"
                                "スタイルに直して変換し直す（AI による補完では、set_role の abstract で英文要旨に戻せる）")
                elif by_text:
                    # 文字の規則で始めた資料も記録する（文の形の段落を見出しと誤ったときに、レポートの 4 章と AI 依頼文の推定で
                    # 気づけるように）
                    back = "英文要旨の段落（abstract）" if first else "前の資料の段落（p）"
                    plan.decide("mechanical", "style", b.src,
                                f"段落「{head}」を資料の見出しとした（「資料」「付録」「附録」「Appendix」で始まる見出しの形のため）。"
                                f"資料の見出しでなければ、AI による補完の set_role で{back}に戻せる")
                continue
            if app is not None:
                plan.region[b.src] = "app"
                plan.locations[b.src] = f"資料{len(plan.apps)} 第{len(app.children) + 1}要素"
                if sentence:
                    self.note_appendix_sentence(b, text, sentence, first=False)
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
                if sentence:
                    self.note_appendix_sentence(b, text, sentence, first=True)
                if plan.lang == "ja":
                    self.check_abstract_ja(b, text, sentence)
            else:
                plan.locations[b.src] = "英文部分"
                plan.exclude(b, "英文部分の、題目・著者・要旨以外の段落")

    def note_appendix_sentence(self, b, text, sentence, first):
        """「資料」などで始まり資料の見出しの形（RE_APPENDIX）に合うが、文の形（appendix_sentence）なので資料の見出しにしなかった
        段落を、判断の一覧に記録する（applied=False。レポートの 4 章と、AI 依頼文の「推定:」に載る）。

        文の形の判定で見出しを文と誤ったときに、気づいて直せるように（最初の資料なら見出しと資料の段落が英文要旨に入り、2 つ目
        からの資料なら前の資料につながる）。first: 英文要旨の段落（最初の資料の見出しの位置）か。
        """
        where = "英文要旨の段落のまま" if first else "前の資料の段落のまま"
        how = ("Word でその段落に章・節・項見出しのスタイルを付けて変換し直すと、文字はそのままで資料になる（AI による補完では、"
               "set_role の app_heading で資料にできる）") if first else "AI による補完の set_role の app_heading で資料にできる"
        self.plan.decide("mechanical", "style", b.src,
                         f"段落「{text.strip()[:20]}」は「資料」「付録」「附録」「Appendix」で始まるが、{sentence}の形なので、"
                         f"資料の見出しにしなかった（{where}）。資料の見出しなら、{how}", applied=False)

    def check_abstract_ja(self, b, text, sentence=""):
        """英文要旨の段落に、かな・漢字が 3 割以上あれば知らせる（資料などの和文が英文要旨に入っているかもしれない）。

        自動では移さない。判断の記録（applied=False。AI 依頼文の「推定:」に載り、AI が app_heading を提案できる）と、
        10 章の警告と、要確認の知らせ（report.actions の abstract_ja）にする。sentence: 段落が「資料1　…。」のように資料の見出しの
        形で始まるが、文の形なので資料の見出しにしなかった（appendix_sentence）。このときは、見出しを付ける案内ではなく、その段落に
        見出しのスタイルを付ける案内にする（文字を変えずに資料にできる）。
        """
        plan = self.plan
        t = "".join(text.split())
        if not t or len(RE_KANA_KANJI.findall(t)) < ABSTRACT_JA_RATIO * len(t):
            return
        head = text.strip()[:20]
        plan.abstract_ja.append(b.src)
        plan.decide("mechanical", "style", b.src,
                    f"英文要旨の段落「{head}」は、かな・漢字が 3 割以上ある（資料などの和文が英文要旨に入っているかもしれない）。"
                    "自動では移していない", applied=False)
        if sentence:
            how = (f"この段落は「資料」などで始まりますが、{sentence}の形なので、資料の見出しにしていません。資料の見出しなら、Word で"
                   "この段落に章・節・項見出しのスタイルを付けて変換し直してください（文字はそのままで資料になります）")
        else:
            how = ("資料などの和文なら、Word で資料の見出しの段落に章・節・項見出しのスタイルを付けて（見出しがなければ、資料の前に"
                   "「資料1」などの見出しを付けて）変換し直してください")
        plan.warnings.append(f"{b.src}: 英文要旨の段落「{head}」に、かな・漢字が 3 割以上あります。{how}")

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
        """Word の脚注・文末脚注を、本文で最初に参照される順の通し番号で、注のリストの後ろに加える（決定事項 7）。

        参照の順は doc.all_paragraphs() の順（document.xml の段落の順。XML に出力しなかった段落の参照も、その位置で数える。
        Word が脚注に番号を付ける順と同じ）。続けて、集めた注の中の参照を順に足す（脚注の中から参照した文末脚注も出力する）。
        番号は、builder.word_note_marks が plan.fns の中の Word の注の順に付ける（設定 fn_mark。本誌は「1)」）。
        削除の変更履歴の中の参照は、参照として数えない（docx_reader が Document.deleted_note_refs に記録する）。
        参照されていない注の段落は、理由を付けて除外する（空白だけの段落は exclude_blank）。
        参照がどれも、XML に出力しなかった段落か、注の番号をリンクにしない段落（題目・著者名・所属・引用文献など。
        ArticlePlan.no_link_paras）の中にある注は、本文からのリンクのない注（FnNode.linked が偽）として出力し、判断の一覧と
        レポートの 8 章で知らせる。手で書いた注と番号が重なるときは、番号は変えずに plan.note_overlap に記録し、10 章の警告に
        する（要確認の知らせは report の note_overlap）。
        """
        plan = self.plan
        notes = {note_key(kind, nid): paras
                 for kind, d in (("footnote", self.doc.footnotes), ("endnote", self.doc.endnotes)) for nid, paras in d.items()}
        order, where, custom = [], {}, set()

        def collect(paras):
            for p in paras:
                for a in p.atoms:
                    if a.kind != "fnref":
                        continue
                    k = note_key(a.fn_kind, a.fn_id)
                    if not notes.get(k):
                        continue            # 参照先の注が docx にない（今までどおり注にしない。本文の参照は何も出力されない）
                    refs = where.setdefault(k, [])
                    if p.src not in refs:
                        refs.append(p.src)
                    if a.fn_kind.endswith("-custom"):
                        custom.add(k)
                    if k not in order:
                        order.append(k)

        collect(self.doc.all_paragraphs())
        i = 0
        while i < len(order):               # 集めた注の中の参照（足した注の中も続けて見る）
            collect(notes[order[i]])
            i += 1
        # リンクにならない参照: XML に出力しなかった段落と、注の番号をリンクにしない段落（題目・著者名・所属・引用文献など）の中のもの
        nolink = plan.no_link_paras()
        unlinked = {e.src for e in plan.exclusions} | set(nolink)
        nodes = []
        for n, k in enumerate(order, 1):
            paras = notes[k]
            node = FnNode(paras=paras, word_note=True, word_kind=k.partition(":")[0], word_id=k, word_refs=where[k],
                          linked=any(s not in unlinked for s in where[k]), custom_mark=k in custom)
            for j, p in enumerate(paras, 1):
                plan.region[p.src] = "fn"
                plan.locations[p.src] = f"{note_label(k)}（注 {n}）" + (f" 第{j}段落" if len(paras) > 1 else "")
            plan.fns.append(node)
            nodes.append((n, node))
        for k, paras in notes.items():      # 参照されていない注
            if k in where:
                continue
            why = unreferenced_note_reason(k, k in self.doc.deleted_note_refs)
            for p in paras:
                plan.locations[p.src] = note_label(k)
                if p.is_blank:
                    plan.exclude_blank(p)   # 空白だけの段落（文字がまったくない段落は記録しない）
                elif p.plain():
                    plan.exclude(p, why)
        if not nodes:
            return
        ends = sum(1 for _, fn in nodes if fn.word_kind == "endnote")
        if ends == len(nodes):
            what = f"Word の文末脚注機能で書かれた注 {ends} 件を、本文で最初に参照される順の通し番号で注の一覧にした"
        elif ends:
            what = (f"Word の脚注・文末脚注機能で書かれた注 {len(nodes)} 件（脚注 {len(nodes) - ends} 件・文末脚注 {ends} 件）を、"
                    "本文で最初に参照される順の通し番号で注の一覧にした")
        else:
            what = f"Word の脚注機能で書かれた注 {len(nodes)} 件を、注の一覧にした"
        plan.decide("mechanical", "note", nodes[0][1].paras[0].src,
                    f"{what}（テンプレートの規定は、本文に上付きの「1)」を書き、注は「注」の節にまとめる）。"
                    "本文と注の一覧の番号、注の見出しは補った（8 章）")
        # 手で書いた注（「注」の節の「1)」など）と番号が重なる Word の注（Word の注は 1 から番号を付ける〈builder.word_note_marks〉）。
        # 手で書いた注の後ろから番号を続けるかは利用者に確かめていないので、番号は変えずに知らせる（10 章の警告と要確認）
        manual = {fn.number for fn in plan.fns if not fn.word_note and fn.number is not None}
        plan.note_overlap = sorted(manual & set(range(1, len(nodes) + 1)))
        if plan.note_overlap:
            marks = "、".join(self.journal.fn_mark.format(n=k) for k in plan.note_overlap)
            plan.warnings.append(f"手で書いた注と Word の脚注・文末脚注が両方あり、注の番号 {marks} が重なっています（Word の注の番号は"
                                 "本誌の形式で 1 から付けるため）。注の一覧に、同じ番号の別の注が並びます（本文からリンクしている"
                                 "注は、それぞれ正しい注を指します）。Word でどちらかの書き方にそろえて、変換し直してください")
        for n, fn in nodes:
            label = f"{note_label(fn.word_id)}（注 {n}）"
            if not fn.linked:
                out, shown = plan.unlinked_places(fn.word_refs)
                move = "本文からリンクする注なら、Word で参照を本文の段落に移して変換し直す"
                if not shown:
                    msg = (f"{label}は、本文の参照が XML に出力しなかった段落（{'、'.join(out)}）の中にだけあるので、"
                           f"本文からのリンクのない注として出力した（8 章）。{move}")
                else:
                    # 題目・引用文献などの中の参照（注の番号は上付きの文字だけで、リンクにしない。著者名の中では番号も出さない）
                    before = f" XML に出力しなかった段落 {'、'.join(out)} と、" if out else ""
                    msg = (f"{label}は、参照が{before}{'、'.join(shown)} の中にだけあるので、本文からのリンクのない注として"
                           f"出力した（{no_link_rule(nolink[s] for s in fn.word_refs if s in nolink)}。8 章）"
                           + (f"。{move}" if out else ""))
                plan.decide("mechanical", "note", fn.paras[0].src, msg)
            if fn.custom_mark:
                # 暫定の判断: 記号を自分で付けた注も、脚注と同じく番号を 1 つ使う（本文の記号は docx の文字のまま）。本文の参照は
                # 中身のない <xref> で、記号はその後ろに出るので、記号はリンクにならない（emit.Emitter.write_object）
                plan.decide("mechanical", "note", fn.paras[0].src,
                            f"{label}は、本文の記号を自分で付けた注（Word の「記号」）。本文の記号は docx の文字のまま、"
                            f"注の一覧の番号は「{self.journal.fn_mark.format(n=n)}」にした（本文と注の一覧で記号が違う。"
                            "本文の注へのリンクは記号の前の中身のない参照で、記号はリンクにならない。PDF と照らし、J-STAGE の"
                            "プレビューで確認すること）")

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
