"""論文の構造（ArticlePlan）と、その要素（章・段落・箇条書き・図表・数式・囲み・注・文献など）の型。

structure.py（段落の役割の決定と構造の組み立て。Classifier）が作り、linker・refparse・ai_assist・builder・report・pipeline・pdfmatch・pdfdocx が読み書きする。
ここには型と、ArticlePlan のメソッド（判断の記録 decide、出力しない段落の記録 exclude・exclude_blank、図表・囲みを置いた
位置の説明 float_place・box_place など）だけを置き、役割の判定や組み立ての規則は置かない（structure.py）。修正計画の U6 で
structure.py から本体を変えずに移した（structure からも、これまでどおり import できる）。model.py 以外には依存しない。
出力しない段落は、exclude・exclude_blank で必ず理由付きで記録する（文字は変えない）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import NamedTuple, Optional

from .model import Decision, Exclusion, Float, Para, Table


class UnlinkedRef(NamedTuple):
    """番号から図・表を決められず、リンクしなかった図・表の参照 1 か所（ArticlePlan.float_unlinked の要素）。

    word は「図」か「表」、src は段落 ID、text は参照の文字（docx のまま）、start・end は段落の文字（Para.plain()）の中の範囲
    （text == plain()[start:end]）。AI のリンク（link_figure・link_table）が同じ範囲に付いたかを、範囲の重なりで決めるために持つ
    （同じ文字が別の所にあっても取り違えない。ai_assist.apply_ops）。
    """
    word: str
    src: str
    text: str
    start: int
    end: int


# スタイルを確かめる段落の種類（StyleSuspect.kind）: 見出しのスタイルの段落に本文が続く（C037）・見出しの階層と番号の形が合わない（C038）・
# 本文のスタイルの引用らしい段落（C129）・文字から見出しと推定した段落（C014）。検出は修正計画の単位 D が足す（W8 は入れ物と表示だけ）。
# 記号だけの引用文献（ref_symbol。「.」だけの段落など。structure.Classifier.build_back が挙げる。XML の文字は変えず、Word で消してもらう）
STYLE_SUSPECT_KINDS = ("heading_body", "heading_level", "quote_like", "heading_guess", "ref_symbol")


class StyleSuspect(NamedTuple):
    """機械が挙げた、スタイルを確かめる段落 1 つ（ArticlePlan.style_suspects の要素。要確認 style_check の行。修正計画 W8 の 3.3・4.3）。

    kind は STYLE_SUSPECT_KINDS のどれか、src は段落 ID、detail は機械の見立て（「項見出しのスタイルですが、番号の形は節です」など。
    空なら種類ごとの決まった文）。XML は変えない（直すのは Word のスタイル）。
    """
    kind: str
    src: str
    detail: str = ""


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
class ImageSlot:
    """XML の画像の置き場所 1 つ（<graphic>・<inline-graphic> 1 つ。画像は 1 枚）。Classifier.assign_slots が作る。

    docx の画像は、置き場所を決める手がかりとしてだけ使う（covers）。名前は幹 key から決める（builder.Builder.slot_name。
    「{記事識別子}_{幹}.{拡張子}」）。幹は図・表なら番号から（fig03・fig01-2・fig04_2・figx01）、キャプションなしなら covers の
    最初の画像の中身の要約値（ImageRef.digest）の先頭 6 桁（img3fa9c2。同じ中身が 2 か所なら docx の順に _2）。
    kind: fig（図キャプションの図）/ table（画像で貼った表）/ nocap（キャプションなし）/ optional（任意）。
    place: fig（<fig> の中の <graphic>）/ table（<table-wrap> の中の <graphic>）/ inline（段落・表のセルの中の <inline-graphic>）。
    label は「図3」「図1-2」（番号を読めなければ ""）、caption はキャプションの段落（なければ None）、src は場所を示す段落の ID、
    covers はこの 1 枚に写るとみなした ImageRef の一覧（docx の順）、float_id は図形の ID（図形の中身なら）、how は含めた決め方の
    記録、note は備考。
    任意の置き場所（結果のないフィールド〈EQ の囲い文字など〉の位置）は covers が空で、pos・code で位置を示す。画像を入れたときだけ XML に残る。
    """
    key: str
    kind: str
    label: str = ""
    caption: Optional[Para] = None
    src: str = ""
    covers: list = field(default_factory=list)
    float_id: str = ""
    place: str = "fig"
    how: str = ""
    note: str = ""
    # 任意の置き場所（kind が optional）だけ: フィールドの位置（src の段落の文字〈Para.text_only〉の中の文字数）とフィールドコード
    pos: int = -1
    code: str = ""


@dataclass(eq=False)
class FigureRow:
    """図・表・キャプションのない画像の置き場所の一覧の 1 行（structure.figure_rows。XML の順）。レポートの図の画像の一覧と、
    AI の依頼文の「図・表の一覧」（修正計画 W8）が同じものを使う。

    fid は節の ID（F1・T2。キャプションのない図・表のセルの中の置き場所などは ""）、kind は fig（図キャプションの図。表で組んだ図も）/
    table（表）/ nocap（キャプションのない画像の置き場所）、label は「図3」「表1」（番号を読めなければ ""）、caption はキャプションの
    段落（なければ None）、key は画像の置き場所の幹（置き場所がない〈表で組んだ図・表〉なら ""）、float_id は図形の ID（図形の中身から
    組んだものと、本文の図キャプションの図に含めた図形〈FloatInfo.mode が caption〉のもの。図形の外なら ""）、place は位置の決め方
    （structure.PLACE_JA の鍵: word〈Word の並び〉/ mechanical / ai_pdf〈AI が PDF を見て指定〉/ ai_layout〈AI が PDF を見ずに指定〉/ anchor〈結び付いた段落の後ろに仮に置いた〉/ end〈本文の最後〉/
    caption〈図キャプションの位置〉）。node は FigNode・TableNode（段落の中の置き場所なら None）、slot は画像の置き場所（なければ None）。
    """
    fid: str
    kind: str
    label: str = ""
    caption: Optional[Para] = None
    key: str = ""
    float_id: str = ""
    place: str = "word"
    node: object = None
    slot: Optional[ImageSlot] = None


@dataclass(eq=False)
class FigNode:
    image_paras: list
    caption: Optional[Para] = None
    caption_more: list = field(default_factory=list)   # 2 段落目以降のキャプション
    tables: list = field(default_factory=list)         # 表で組んだ図の本体（テキストボックスの中の表など）
    # ほかの段落から含めた画像（グループ図形の画像、図キャプションの段落の中の画像、近くの段落の画像、文字のある段落に結び付いた
    # 浮動の画像。structure.Classifier.figure_units）
    extra_images: list = field(default_factory=list)
    fid: str = ""
    number: Optional[int] = None
    slot: Optional[ImageSlot] = None    # 画像の置き場所（表で組んだ図は None。Classifier.assign_slots）
    # 置き場所の how・note に写すもの（Classifier.figure_units が決める。assign_slots が ImageSlot に入れる）: 画像を含めた決め方
    # （same_para・run・near の「+」つなぎ）と、備考（本体の表にできなかった近くの表の理由など）
    how: str = ""
    note: str = ""


@dataclass(eq=False)
class TableNode:
    """表（<table-wrap>）。table が None で image_paras・extra_images があれば、画像で貼った表（修正計画 W1 の 2.3 の C。
    Classifier.assemble_floats と float_units が組む）で、画像の置き場所 slot を持つ。"""
    table: Optional[Table]
    caption: Optional[Para] = None
    caption_more: list = field(default_factory=list)
    tid: str = ""
    number: Optional[int] = None
    slot: Optional[ImageSlot] = None    # 画像で貼った表の置き場所（Classifier.assign_slots。本体の表がある表は None）
    # 画像で貼った表に含めた、画像だけの段落（図の FigNode.image_paras と同じ。空白の除外の記録に使う）と、ほかの段落から含めた画像
    # （グループ図形の画像など）、含めた決め方（next・run・float）と備考
    image_paras: list = field(default_factory=list)
    extra_images: list = field(default_factory=list)
    how: str = ""
    note: str = ""


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
    # 注の節の中の表 [(k, TableNode)]（docx の順）。k は表の前にある paras の数で、builder.fn が paras[k] の <p> の前に
    # <p><table-wrap> を書く（k == len(paras) なら最後）。最初の注より前にあった表は k=1（注の番号が <fn> の先頭に来るように）
    tables: list = field(default_factory=list)


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
    images: list = field(default_factory=list)     # グループ図形の画像（アンカー段落の中にある ImageRef。飾りの図形を除く）
    # mechanical（機械的に配置）/ ai（AI の指定で配置）/ unplaced（未配置）/ caption（本文の図キャプションの図に含め、その位置に
    # 置いた。キャプションのないグループ図形が、本体のない図キャプションの近くの段落に結び付いているとき。修正計画 W1 の 2.3 の B6。
    # 位置を決められない図形に数えない）
    mode: str = ""
    reason: str = ""                               # 未配置の理由
    caption_src: str = ""                          # mode が caption のとき、含めた図の図キャプションの段落 ID
    # 図形の中身のうち、本文の段落として出した段落（docx の順。Classifier.float_units が決める。図の画像に写らない図形〈表で組んだ
    # 図・Word の表だけの図形・画像を直接持たない図形〉の、キャプションでない文字の段落。plan.body_seq には入れない）
    body_paras: list = field(default_factory=list)
    # 中身の組み方: units（float_units が組んだ）/ raw（組み方を決められず、中身を docx の順にそのまま出した。修正計画 W1 の 2.3 の B5）
    built: str = ""
    where: str = ""                                # 未配置のときに仮に置いた位置: anchor（アンカー段落の後ろ）/ end（本文の最後）
    # 本文の最後に置いた理由: ai（AI が本文より後ろにあると答えた〈after が ""〉か、本文の外の段落の後ろを指定した）/
    # anchor（アンカー段落が本文でない）
    end_why: str = ""
    end_after: str = ""                            # AI が指定した本文の外の段落の ID（end_why が ai のとき。after が "" の答えなら ""）
    end_reason: str = ""                           # end_why が ai のときの AI の答えの根拠（placements の reason。要確認 float_end の行）
    # AI の指定（mode が ai か、end_why が ai）の根拠。basis は pdf（AI が PDF を見て決めた）/ layout（Word の配置からの推定）/
    # keep（仮の位置のまま）/ ""（指定なし・知らない語）、page と column は PDF のページと段（見ていなければ 0 と ""）、confidence は確度。
    # 修正計画 W8 の 3.3・手順 22（3 章の位置の決め方の列〈structure.figure_place〉・ai_assist.pdf_seen が使う）
    basis: str = ""
    page: int = 0
    column: str = ""
    confidence: str = ""
    # 未配置で where が anchor のとき、その後ろに仮に置いた本文の段落の ID（アンカー段落。アンカー段落が箇条書き・引用の途中なら、
    # その箇条書き・引用の最後の段落。Classifier.run_end）
    after_src: str = ""
    # その図形の中身から組んだ図・表の節（FigNode・TableNode。XML の順。表で組んだ図・表のセルの図・中身をそのまま出した図形から
    # 図形の外と同じ規則で組んだもの・mode が caption の図形を含めた本文の図も。Classifier.assign_slots が入れる）
    nodes: list = field(default_factory=list)


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
class StructureConflict:
    """そのまま組み立てると段落の文字が XML にも除外の記録にも入らなくなる構造（docs/REVIEW_2026-11.md の K1・K2）。

    structure.Classifier が組み立ての途中で記録し、pipeline.convert が組み立ての直後に StructureConflictError で中止する。
    """
    kind: str                 # "ref_heading" / "fn_heading" / "notes" / "ack" / "abstract_heading" / "aff"
    lost: list                # 出力も除外もされなくなる段落 ID（空白だけの段落を除く。先頭は前の見出し・所属）
    by: str = ""              # 置き換えた段落 ID（後ろの見出し・次の所属）。著者名が続かないまま残った所属なら ""
    where: str = ""           # aff のとき "loose"（段落）か "table"（著者表）
    by_text: tuple = (False, False)   # 見出しのとき、(前の見出し, 後の見出し) が文字からの推定（back_heading_by_text）か
    between: bool = False     # 前の見出しの節と後ろの見出しの間に、別の種類の後付けの段落があるか（直し方の文を変える）


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
    # 「注」の段落 ID -> その後ろの、「注」を注の節の見出し（Word の「注見出し」スタイル）にすると注の節に入る段落 ID の一覧
    # （次の後付けの見出し・英文の部分・文書の終わりの手前まで。本文に戻した後ろの章見出しとその本文も含む。空白だけの段落・
    # 図形の中の段落は除く）。要確認 fn_guess の助言「注見出しにする」が何を注の節に入れるかを知らせる（report._fn_guess_action）
    fn_guess_span: dict = field(default_factory=dict)
    # 文字から注の見出しと推定される「注」だけの段落 ID（本文・後付けの領域にあるもの。図形の中は除く）の一覧。出現順。
    # 要確認 fn_guess の助言「注見出しにする」が、「注」が 2 つ以上あるときに全部の扱いを決めるよう添えるための記録
    # （「注見出し」の段落は 1 つしか持てず、ほかの「注」が文字から推定されると先の見出しが出力されない。docs/REVIEW_2026-11.md の K1）
    fn_guess_notes: list = field(default_factory=list)
    # 手で書いた注と Word の脚注・文末脚注の両方にある注の番号（Word の注の番号は 1 から付けるので重なる。要確認）
    note_overlap: list = field(default_factory=list)
    # 番号から図・表を決められず、リンクしなかった図・表の参照（UnlinkedRef: 「図」か「表」, 段落 ID, 参照の文字, 段落の中の範囲）。
    # 同じ種類のキャプションの番号が重なる・キャプションに枝番がある（図1-1・図1-2）ときの参照（linker.Linker.float_refs。要確認）
    float_unlinked: list = field(default_factory=list)
    # 文字だけのテキストボックスの ID -> BoxInfo（Classifier.place_boxes が扱ったもの。空白だけのものも。出現順）
    textboxes: dict = field(default_factory=dict)
    # そのまま組み立てると段落の文字が出力にも除外にも入らなくなる構造（StructureConflict。同じ種類の後付けの見出し・英文要旨の見出しが
    # 2 つ、著者名の付かない所属。K1・K2）。あれば pipeline.convert が StructureConflictError で変換を中止する
    structure_conflicts: list = field(default_factory=list)
    # 画像の置き場所（ImageSlot。Classifier.assign_slots が、要素の木を XML とおおむね同じ順にたどって作る）と、画像の ID -> 置き場所
    slots: list = field(default_factory=list)
    slot_of: dict = field(default_factory=dict)
    # 機械が挙げた、スタイルを確かめる段落（StyleSuspect。段落の順。要確認 style_check と推奨の手順 ai_finish の出す条件 3。
    # 検出は修正計画の単位 D が足す。W8 は入れ物と表示だけ）
    style_suspects: list = field(default_factory=list)

    @property
    def unplaced_floats(self) -> list:
        return [fid for fid, info in self.floats.items() if info.mode == "unplaced"]

    @property
    def asked_floats(self) -> list:
        """AI に位置を聞く図形の ID（mode が unplaced か ai。機械的に置いたもの〈mechanical〉と、本文の図キャプションの図に含めたもの
        〈caption〉は入らない。結び付いた段落が本文の外で本文の最後に置いたもの〈end_why anchor〉も入る: PDF で本文の段落を答えれば、
        そこに置ける）。推奨の手順 ai_finish の残りの数は、これと answered_floats で決める（修正計画 W8 の 3.3・4.3）。"""
        return [fid for fid, info in self.floats.items() if info.mode in ("unplaced", "ai")]

    @property
    def answered_floats(self) -> list:
        """asked_floats のうち、AI の答えを採用したもの（mode が ai か、AI が本文の外と答えて end_why が ai のもの）。"""
        return [fid for fid, info in self.floats.items() if info.mode == "ai" or (info.mode == "unplaced" and info.end_why == "ai")]

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

    def fn_table_paras(self) -> set:
        """注の節の中の表（FnNode.tables）のキャプション・キャプションの続き・セルの段落の ID。linker が注番号をリンクしないために使う
        （注の段落と同じ扱い）。"""
        out = set()
        for fn in self.fns:
            for _, t in fn.tables:
                out.update(q.src for q in ([t.caption] if t.caption is not None else []) + list(t.caption_more))
                if t.table is not None:
                    out.update(q.src for q in t.table.paragraphs())
        return out

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

    def exclude_blank(self, para: Para, reason: str = "空白のみの段落"):
        """空白だけの段落を、理由 reason（既定は「空白のみの段落」）で除外に記録する（文字がまったくない段落は記録しない）。

        reason を変えるのは、画像だけの段落を、画像の知らせに添える理由（structure.REF_IMAGE_EXCLUDED など）で除外するときだけ
        （文字は 1 文字もないので、どの理由でも blank の除外）。blank の除外は、ここだけで作る（blank=True を付ける）。不変性チェック（fidelity.verify）は、blank の除外の
        docx の文字が本当に空白だけかを確かめる（空白以外の文字があれば、変換ツールの不具合として不合格）。
        """
        if para.plain():
            self.exclusions.append(Exclusion(src=para.src, reason=reason, text=_para_text(para), blank=True))


def _para_text(para: Para) -> str:
    return "".join(a.text for a in para.atoms if a.kind == "text")
