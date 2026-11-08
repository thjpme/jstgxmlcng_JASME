"""docx から読み取った内容を保持する中間表現。

段落の中身は「アトム」の平らな列で表す。リンク付け（xref・uri など）は
アトムの ``link`` 属性を設定するだけで行い、文字列そのものには一切触れない。
文字列を変えずに構造だけを付け加える、という本ツールの原則をこの表現で担保する。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# 本文中のアトムを平文にしたとき、文字でないもの（数式・画像・脚注記号）の位置に置く文字。
# リンク範囲がこの文字をまたがないように使う。
OBJ = "\ufffc"

# Word の脚注・文末脚注の種類（Atom.fn_kind から「-custom」を除いたもの）の日本語
NOTE_KINDS_JA = {"footnote": "脚注", "endnote": "文末脚注"}


def _note_kind(kind: str) -> str:
    return kind.removesuffix("-custom")


def note_key(fn_kind: str, fn_id: str) -> str:
    """Word の脚注・文末脚注の鍵（"footnote:5" / "endnote:5"）。脚注と文末脚注は ID が重なりうるので、種類と ID の組で区別する。

    記号を自分で付けた参照（fn_kind が "footnote-custom" など。customMarkFollows）も、同じ注を指す鍵にする。
    注の番号（builder.word_note_marks）・本文の参照のリンク（emit.Emitter.write_object）・出版版 PDF との照合（pdfmatch）・
    レポートは、どれもこの鍵で注を引く。
    """
    return f"{_note_kind(fn_kind)}:{fn_id}"


def note_label(key: str) -> str:
    """note_key の人が読める表記（「Word の脚注 5」「Word の文末脚注 5」）。鍵に「-custom」が残っていても同じ表記。"""
    kind, _, nid = key.partition(":")
    kind = _note_kind(kind)
    return f"Word の{NOTE_KINDS_JA.get(kind, kind)} {nid}"


@dataclass(eq=False)
class LinkSpec:
    """アトムの範囲に付ける構造（リンクやタグ）。

    kind:
      xref        : 記事内リンク（attrs: ref-type, rid）
      uri         : 外部リンク（本文用、attrs: href）
      ext-link    : 外部リンク（後付け用、attrs: href）
      pub-id      : 引用文献中の DOI（attrs: pub-id-type="doi"）
      year / article-title / source : 引用文献中の書誌要素タグ
      label       : 数式番号などのラベル
    origin: "word"（docx のハイパーリンク）/ "mechanical" / "ai"
    """
    kind: str
    attrs: dict = field(default_factory=dict)
    origin: str = "mechanical"
    note: str = ""
    decision_id: Optional[str] = None


@dataclass(eq=False)
class Atom:
    """段落の中の最小単位。

    kind:
      text   : 文字列（text, fmt）
      math   : 数式（omml 要素, display=True なら別行数式）
      image  : 画像（image: ImageRef）
      fnref  : Word の脚注・文末脚注の参照（fn_kind: footnote / endnote。記号を自分で付けたもの〈customMarkFollows〉は
               末尾に -custom。fn_id。注の鍵は note_key。番号は Word が自動生成）
      gen    : docx の文字ではなく、Word が自動生成して表示する文字（自動番号など）
    """
    kind: str
    text: str = ""
    fmt: frozenset = frozenset()
    href: Optional[str] = None          # docx のハイパーリンク先
    math: object = None                 # lxml element (m:oMath / m:oMathPara)
    display: bool = False
    image: object = None                # ImageRef
    fn_kind: str = ""
    fn_id: str = ""
    link: Optional[LinkSpec] = None

    def plain(self) -> str:
        if self.kind == "text":
            return self.text
        return OBJ


# Word の画像の加工のうち、書き出しで反映しないもの（ImageRef.edits の名前と順）
IMAGE_EDITS = ("切り取り（読めない指定）", "余白", "並べて表示", "塗りつぶしの範囲", "回転", "左右反転", "上下反転",
               "色の変更", "透明度", "図の効果", "アート効果")


@dataclass
class ImageRef:
    rel_id: str
    target: str                 # word/media/xxx.png
    source: str                 # "drawing" | "vml" | "ole"
    cx_emu: int = 0
    cy_emu: int = 0
    inline: bool = True         # wp:inline（行内）か wp:anchor（浮動）か
    descr: str = ""
    ole_progid: str = ""
    shape_only: bool = False    # 画像ファイルを持たない Word 図形
    export_name: str = ""       # 出力ファイル名（Graphics/ 配下）
    image_id: str = ""          # レポート・AI 用の識別子 (img1, img2, ...)
    float_id: str = ""          # 浮動配置の図形（Float）の中の画像なら、その図形の ID
    hidden: bool = False        # 隠し文字（w:vanish）のランの中の画像。段落のアトムにしない（XML に出力しない）
    hidden_style: bool = False  # hidden のうち、スタイル・既定の書式の設定で隠したもの（ランの直接の指定でない。要確認で知らせる）
    crop: tuple | None = None   # Word のトリミング（左・上・右・下）。元の画像の幅・高さに対する割合（0 以上）。4 つとも 0 なら None
    edits: tuple = ()           # 書き出しで反映しない Word の加工の名前（IMAGE_EDITS の順・重複なし）。9 章と要確認 image_edits

    @property
    def height_cm(self) -> float:
        return self.cy_emu / 360000.0

    @property
    def width_cm(self) -> float:
        return self.cx_emu / 360000.0


@dataclass(eq=False)
class Para:
    src: str                    # 段落の識別子（document.xml 内の w:p の出現順。d1, d2, ... / 脚注は f..）
    style_id: str = ""
    style_name: str = ""
    atoms: list = field(default_factory=list)
    numbering: Optional[tuple] = None   # (numId, ilvl)
    autonum: str = ""           # 自動番号のラベル（表示される文字列）
    align: str = ""
    section_break: bool = False  # この段落でセクション（段組みなど）が終わる
    in_textbox: bool = False    # テキストボックス（w:txbxContent）の直下の段落（テキストボックスの中の表のセルの段落は False）
    float_id: str = ""          # 浮動配置の図形（Float）の中の段落なら、その図形の ID
    # テキストボックスの中の段落なら、そのテキストボックス（TextBox）の ID（x1, x2, …。テキストボックスの中の表のセルの段落にも
    # 付く。入れ子の内側のテキストボックスの段落は、外側の ID）
    textbox_id: str = ""
    role: str = ""              # structure.py が決める役割
    role_origin: str = ""       # "style" / "heuristic" / "ai" / "position"
    note: str = ""

    def plain(self) -> str:
        return "".join(a.plain() for a in self.atoms)

    def text_only(self) -> str:
        return "".join(a.text for a in self.atoms if a.kind == "text")

    @property
    def is_blank(self) -> bool:
        return not any(a.kind != "text" or a.text.strip() for a in self.atoms)

    @property
    def images(self) -> list:
        return [a.image for a in self.atoms if a.kind == "image"]

    @property
    def has_display_math(self) -> bool:
        return any(a.kind == "math" and a.display for a in self.atoms)


@dataclass(eq=False)
class Cell:
    blocks: list = field(default_factory=list)   # Para | Table
    gridspan: int = 1
    vmerge: Optional[str] = None                 # "restart" | "continue" | None


@dataclass(eq=False)
class Row:
    cells: list = field(default_factory=list)
    header: bool = False
    grid_before: int = 0    # 行の前で飛ばしたグリッドの列の数（w:trPr/w:gridBefore。セルのない列）
    grid_after: int = 0     # 行の後ろで飛ばしたグリッドの列の数（w:trPr/w:gridAfter）
    number: int = 0         # docx の表の何行目か（1 から。変更履歴で削除して読み飛ばした行も数える。警告の行の番号）


@dataclass(eq=False)
class Table:
    tid: str
    rows: list = field(default_factory=list)
    style_id: str = ""
    style_name: str = ""
    role: str = ""
    float_id: str = ""          # 浮動配置の図形（Float）の中の表なら、その図形の ID
    in_textbox: bool = False    # テキストボックスの中の表（浮動配置でない VML・行内の図形の中の表は、float_id が空でも True）
    textbox_id: str = ""        # テキストボックスの中の表なら、そのテキストボックス（TextBox）の ID
    skipped_rows: int = 0       # 変更履歴で削除された、文字のない行のうち、読み飛ばした行の数（docx_reader。rows に入れていない）

    def paragraphs(self):
        for r in self.rows:
            for c in r.cells:
                for b in c.blocks:
                    if isinstance(b, Para):
                        yield b
                    elif isinstance(b, Table):
                        yield from b.paragraphs()


@dataclass(eq=False)
class Float:
    """浮動配置の図形（テキストボックス・グループ図形）。2 段組をまたぐ図表などに使われる。

    中身（テキストボックスの段落・表、グループの中の画像）は float_id でこの図形を指す。
    位置は Word で表示したときのものではなく、docx に記録された「アンカー段落からの距離」などである。
    """
    fid: str                        # s1, s2, ...
    anchor_src: str                 # 図形が結び付いている段落（アンカー段落）
    h_from: str = ""                # wp:positionH の relativeFrom（column / margin / page / character など）
    h_offset_cm: Optional[float] = None
    h_align: str = ""
    v_from: str = ""                # wp:positionV の relativeFrom（paragraph / line / page / margin など）
    v_offset_cm: Optional[float] = None
    v_align: str = ""
    width_cm: float = 0.0
    height_cm: float = 0.0
    wrap: str = ""                  # wrapTopAndBottom / wrapSquare / wrapTight / wrapNone など
    group: bool = False             # グループ図形


@dataclass(eq=False)
class TextBox:
    """テキストボックス（w:txbxContent）1 つ。中の段落・表は textbox_id でこのテキストボックスを指す（入れ子の内側は外側の ID）。

    幅・高さは cm。DrawingML は wp:extent（グループ図形・描画キャンバスの中なら wps:spPr の a:ext に、グループの拡大率
    〈wp:extent / a:chExt〉を掛ける）、VML は v:shape などの style の width・height（pt のときだけ。ほかの単位は読めないとして
    None）。位置（縦・横のずれと基準）は、浮動配置（wp:anchor）なら同じ図形の Float にある（float_id で引く）。VML の位置
    （margin-top など）は読まない（位置は推定として扱う。structure.Classifier.place_boxes）。
    本文（word/document.xml）のテキストボックスだけを記録する（脚注・文末脚注の中のものは記録しない）。
    """
    xid: str                         # x1, x2, ...（出現順）
    anchor_src: str                  # 結び付いている段落（アンカー段落。行内なら、その段落）
    source: str = ""                 # "wps"（DrawingML）/ "vml"
    inline: bool = False             # 行内（wp:inline、または position:absolute のない VML）
    absolute: bool = False           # VML の position:absolute（位置を指定した浮動配置）
    group: bool = False              # グループ図形・描画キャンバスの中（wpg:wgp / wpc:wpc / v:group）
    float_id: str = ""               # 浮動配置の図形（Float）の中なら、その ID（wp:anchor のテキストボックス自身の Float も）
    width_cm: float | None = None
    height_cm: float | None = None


@dataclass
class Layout:
    """本文の段組みと行の設定（docx の w:sectPr）。図の位置を推定する手がかりにする。"""
    text_width_cm: float = 0.0
    text_height_cm: float = 0.0
    columns: int = 1
    column_width_cm: float = 0.0
    line_pitch_cm: float = 0.0
    chars_per_line: float = 0.0     # 1 段の 1 行に入る全角文字の数


@dataclass
class Exclusion:
    """XML に出力しない docx の文字列。必ずレポートに一覧で出す（6 章）。

    位置を決められない理由（structure.UNPLACED_EXCLUSIONS）の除外は、さらに要確認・要対応で知らせる（report._unplaced_action の
    excluded_unsure・_abstract_missing_action の abstract_missing）。意図した除外（装飾・誌名行、図の注記など）は知らせない。

    blank: 空白だけの段落（の空白）として除外したもの。不変性チェックで、docx の文字が本当に空白だけかを確かめる
    （空白以外の文字があれば不合格）。付けるのは article.ArticlePlan.exclude_blank()（空白だけの段落）と
    builder.Builder.fig（図の画像だけの段落にある空白）だけ。
    """
    src: str
    reason: str
    text: str
    blank: bool = False


@dataclass
class LostImage:
    """docx にあるのに、XML に出力しなかった画像（pipeline が変換の後に調べる。要対応としてレポート・Colab・
    コマンドラインで知らせる）。

    不変性チェックは文字しか見ないので、画像を置けない場所（引用文献・題目・著者・所属の段落など）や、出力しなかった段落の
    中にある画像は、ここで調べないと黙って XML からも Graphics/ からも消える。隠し文字の中の画像は対象にしない。
    """
    image_id: str
    src: str            # 画像のある段落の ID（見つからなければ空）
    location: str       # 段落の場所（plan.locations。なければ領域の名前）
    reason: str         # 出力しなかった理由の推定
    text: str = ""      # 段落の文字の冒頭（Word で探す手がかり。図形の中の画像なら、図形が結び付いている段落を reason に書く）
    source: str = ""    # docx の中のファイル（word/media/...）。Word の図形なら空


@dataclass
class LostNumber:
    """Word の自動番号のある段落で、段落の文字は XML に出したのに番号を出さなかったもの（pipeline.lost_autonums。要対応）。

    番号は docx の文字ではないので、文字の不変性チェックでは見つからない。題目・副題・著者名・所属の段落は、番号を出さないと
    決めているので対象にしない（BuildInfo.unshown_numbers。10 章の警告）。"""
    src: str
    number: str        # Word の番号（ルート2 では PDF に合わせたもの。builder.autonum と同じ）
    location: str      # 段落の場所（plan.locations。なければ領域の名前・Word の脚注など）
    where: str         # 段落の文字を出した XML の要素（td・p など。最初の jx:span の親の要素名）
    text: str = ""     # 段落の文字の冒頭 20 字（Word で探す手がかり）


@dataclass
class TableProblem:
    """出力した XML の表の形の崩れ（pipeline.table_problems が変換の後に調べる。要対応 table_shape）。

    不変性チェックは文字しか、DTD 検証は要素の並びしか見ないので、出力した表の形（行ごとの列の数・セルの重なり・縦の結合が
    見出し行や本文の行の外にはみ出していないか・セルのない行）はここで確かめる。崩れていれば変換ツールの不具合の可能性がある。
    """
    tid: str            # model.Table.tid（組み立ての記録がない表は空）
    where: str          # Word で探す手がかり（builder の where。docx_reader.table_where の形）
    name: str           # 知らせに出す名前（「表 T1」「図 F1 の中の表」。どちらの id もなければ where）
    problems: list      # 問題の文の一覧（同じ文は 1 つ）


@dataclass
class JoinInfo:
    """段落記号が削除された段落の連鎖のうち、段落のスタイルが 1 種類でないもの（docx_reader。structure が判断の一覧に記録する）。"""
    src: str                # 連鎖の最初の段落の ID（読み取った段落の ID）
    srcs: list              # 連鎖の段落の ID（後ろの段落の ID は欠番）
    style_ids: list         # 連鎖の段落ごとのスタイルの ID（pStyle がなければ既定の段落スタイル）
    used: str               # 読み取った段落のスタイルの ID（文字のある最初の段落のもの。すべて空なら最後の段落のもの）


@dataclass
class DeletedRow:
    """変更履歴で削除された表の行（w:trPr/w:del）のうち、どの段落にも Word で表示される文字（画像・数式・注の参照も）がなく、
    図形も読まなかったので読み飛ばしたもの（docx_reader。隠し文字だけが残る行も含む）。"""
    tid: str                # 読み取りの表の ID（t1, t2, …）
    row: int                # docx の表の何行目か（1 から。読み飛ばした行も数える）
    head: str               # 表の最初の文字のあるセルの文字の冒頭（Word で表を探す手がかり）


@dataclass
class Newline:
    """段落の中の改行（w:br・w:cr。文字は "\\n"）を XML に書き出した記録（emit.Emitter.span が書き出すたびに 1 つ）。"""
    src: str                # 段落の ID
    count: int              # 書き出した文字の中の改行の数
    breaks: int             # 改行の前に入れた <break/> の数（表のセル。リンクの中の改行には入れない）
    cell: bool = False      # <break/> を入れる文脈（表のセル。emit.Ctx.breaks）か
    label: str = ""         # 要確認として知らせる文脈の名前（題目・副題、著者名、所属、引用文献。emit.Ctx.newline_label）


@dataclass
class Decision:
    """機械処理または AI が下した判断。レポートの根拠になる。"""
    did: str
    stage: str          # "mechanical" | "ai"
    category: str       # "style" | "citation" | "figure" | "table" | "note" | "url" | "formula" | "name" | ...
    src: str
    message: str
    confidence: str = ""    # 高 / 中 / 低（AI のみ）
    location: str = ""
    applied: bool = True


@dataclass
class Document:
    blocks: list                       # Para | Table（本文の出現順）
    footnotes: dict                    # {id: [Para]}
    endnotes: dict
    media: dict                        # {rel_id: (target, bytes)}
    styles: dict                       # {style_id: StyleInfo}
    warnings: list = field(default_factory=list)
    hidden_text: list = field(default_factory=list)   # [(src, text)]
    # hidden_text のうち、スタイル・既定の書式の設定で隠したもの [(src, text)]（ooxml.HiddenRule.run_hidden_by が "style"。要確認）
    style_hidden: list = field(default_factory=list)
    deleted_note_refs: set = field(default_factory=set)   # 変更履歴で削除された脚注・文末脚注の参照の note_key（docx_reader）
    tracked_changes: int = 0
    comments: int = 0
    images: list = field(default_factory=list)         # ImageRef（出現順）
    floats: list = field(default_factory=list)         # Float（出現順）
    textboxes: list = field(default_factory=list)      # TextBox（出現順。本文のテキストボックス）
    layout: Optional[Layout] = None
    # 段落記号の削除でつないだ段落の連鎖 [(最初の段落の ID, [段落の ID, …])]（本文・Word の脚注・文末脚注。docx_reader）
    joined: list = field(default_factory=list)
    joins: list = field(default_factory=list)          # JoinInfo（つないだ連鎖のうち、段落のスタイルが 1 種類でないもの）
    deleted_rows: list = field(default_factory=list)   # DeletedRow（変更履歴で削除された、文字のない表の行。読み飛ばしたもの）

    def all_paragraphs(self):
        for b in self.blocks:
            if isinstance(b, Para):
                yield b
            elif isinstance(b, Table):
                yield from b.paragraphs()
