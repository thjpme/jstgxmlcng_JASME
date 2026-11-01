# 単位 F（0.25.0）の設計: 文字だけのテキストボックス（囲み）と、本文の外に結び付いた図形（D1・N7）

- 作成: 2026-11-01（設計の担当）。対象: main の 3157349（0.24.1）。コードは変えていない（試作と測定は `scratchpad/f/design/` の下）。
- 正本: `docs/FIX_PLAN.md` の F の節・項目の表の D1・N7・「利用者に決めてもらうこと」9・10・決定事項 9・10・付録の D1。
  文中の FIX_PLAN の行番号（L557 など）は古いので、ここでは名前で書く。
- 利用者の判断（2026-11-01）: 「しきい値はそれでいこう」「N7 もそれで」。しきい値は FIX_PLAN の付録・「計画全体で足した作業」の案
  （文章の 20 字・段の幅の 6 割、注記の 15 字・4 割）を、td1〜3 で確かめて採る（決定事項 9(3)）。N7 は決定事項 10（位置を決められない図表にし、
  AI を使わない設定では止める）。
- 暫定の判断（まとめ役。利用者にはまだ確かめていない。設計書・FIX_PLAN に「暫定」と書く）: 画面（Colab・CLI）の文言と見え方は、
  既存の形（赤い枠・手順 8・標準エラー）に `Action` を足すだけにし、表示の仕組みは変えない。この設計で新たに決めた暫定の判断は 13 章に挙げる。

---

## 0. 要約

1. 読み取りで、`w:txbxContent` ごとに `model.TextBox`（xid は `x1, x2, …`）を記録し、中の段落・表に `textbox_id` を付ける（入れ子は外側の ID を継ぐ）。
   幅は EMU（DrawingML）か pt（VML）から cm で持ち、読めなければ None。使われていない `Document.textbox_excluded` は削除する。
2. 「文字だけのテキストボックス」（画像・表・図表キャプションを含まず、図表の入った浮動配置の図形〈`FloatInfo`〉の一部でもないもの）を、
   `floats.textbox_kind` で **box（囲み）・label（図に重ねた注記）・undecided（決められない）・blank（空白だけ）** に機械的に分ける。
3. box は `BoxNode` → `<boxed-text>`（本文の最上位〈最初の章見出しの前〉では `<p>` で包む。J-STAGE の `<body>` の子は `<p>`・`<sec>` だけ）。
   label と undecided は理由付きで除外する（undecided は要確認の `Action`。AI を使うよう強く勧める）。blank は `exclude_blank` だけ。
4. 置き場所は `place_boxes`（`place_floats` とは別のパス）: 図の左上がアンカー段落の左上にあれば前、行内（wp:inline・位置指定のない VML）なら後ろ、
   それ以外（位置を推定）はアンカー段落の後ろで要確認。本文の外に結び付いたもの（N7）は本文の最後で要確認。AI は placements の `kind` `box`・`label` で指定する。
5. N7: アンカーが本文の外（引用文献・注・付記・謝辞・英文の部分）にある図形は、その領域の段落にしない。図表の入った浮動配置の図形は
   `place_floats` で「位置を決められない図表」（AI なしでは中止。B3 の置き場所の規則で本文の最後に仮に置く）、文字だけのテキストボックスは
   `place_boxes`。資料（app）の中の図形は今のまま。どの図形が本文の外かは、英文の部分では資料が始まったかどうかで決まる（`build_front_en`）ので、
   **構造の組み立てを 2 回行う**（1 回目で本文の外の図形を見つけ、2 回目でそれを本文に回す。4.10）。
6. td1〜3 の実測で分かったこと（1 章）: **td1・td2 に文字だけのテキストボックスはない**。計画で「囲み」と数えた td1・td2 の 2 件ずつは、
   図・表キャプションと表（1 行 1 列の表に問題文〈211・389 字〉、または表そのもの）を入れた浮動配置の図形で、B3 の図表として扱われている（F で変わらない）。
   td3 の 31 件は、行内のグループ図形（Word の図形で描いた図 2 つ）の中の注記 28 件（0〜11 字）と、資料の表のセルに結び付いた囲み 3 件（197〜210 字。
   資料の中なので範囲外。今のまま表のセルの中に出る）。したがって **F で td1・td2 の XML は変わらず、td3 は注記 27 段落の除外の理由と知らせだけが変わる**。

---

## 1. td1〜3 の実測（数値だけ。文字は記録しない）

測定のスクリプト: `scratchpad/f/design/measure.py`・`proto_kind.py`・`floatdump.py`・`groupmeasure.py`（結果 `measure_td{1,2,3}.json`）。
3 本とも 2 段組、1 段の幅 8.68 cm、本文の幅 18.1 cm、1 行 24 字、行送り 0.556 cm。

### 1.1 「囲み」と数えられていたもの（td1・td2）: 文字だけではない

| 原稿 | 図形 | 中身 | 文字数（空白を除く） | 幅 | 今の扱い（0.24.1） |
|---|---|---|---|---|---|
| td1 | s1（アンカー d12） | 図キャプション 3 段落 + 1 行 1 列の表（6 段落） | 271（表 211） | 8.65 cm（1.0 段） | 位置を決められない図表（AI） |
| td1 | s7（d74） | 表キャプション 4 段落 + 表 2 つ（8 行 4 列） | 285 | 8.60 cm | 位置を決められない図表（AI） |
| td2 | s1（d48） | 図キャプション 1 + 1 行 1 列の表（3 段落） | 397（表 389） | 18.0 cm（2.07 段） | 位置を決められない図表（AI） |
| td2 | s3（d246） | 表キャプション 1 + 表（12 行 6 列） | 263 | 18.04 cm | 位置を決められない図表（AI） |

計画の「276・299 文字」「275・402 文字」は空白を含めた同じ 4 件の数。どれもキャプションと表を含むので「文字だけのテキストボックス」ではない
（`place_floats` が図表として扱い、決定事項 22 のとおり表で組んだ図は fig の中の table-wrap）。F の判定の対象にしない（F で変えない）。
ただし、**本当の「囲み」の形（問題文を枠に入れたもの）の実例**としては、表のセルの文字 211・389 字・幅 1.0〜2.07 段を、しきい値の根拠に使う。

### 1.2 td3 の文字だけのテキストボックス 31 件

| 種類 | 件数 | 文字数 | 幅（段の幅に対する割合） | 高さ | 段落 | 画像の近く | 試作の判定 |
|---|---|---|---|---|---|---|---|
| 行内のグループ図形（d67。画像のない Word の図形の図）の中 | 6 | 2〜4 | 1.0〜2.8 cm（0.11〜0.32） | 0.6〜0.7 cm | 1 | グループの中（図そのもの） | label 6 |
| 行内のグループ図形（d167）の中 | 22 | 0〜11 | 0.4〜3.18 cm（0.05〜0.37） | 0.4〜0.94 cm | 1 | 同上 | label 21・blank 1 |
| 資料の表のセルの段落に結び付いた浮動配置（wrapNone、縦 0.08〜0.23 cm） | 3 | 197・199・210 | 12.77〜12.95 cm（1.47〜1.49） | 2.84〜3.12 cm | 3〜6（推定 6〜7 行） | いいえ | box（ただし資料の表の中なので範囲外） |

- 0.24.1 では、グループの中の 27 段落（文字のある 27 件）は「テキストボックス内の文字（図の一部とみなして本文から除外）」で除外され、A の暫定の知らせ（要確認）が出ている。
  グループ図形は画像を持たない Word の図形なので、図は `shape_only` の画像（利用者が用意する。`images_action`）になり、注記はその画像の中に入る。
- 資料の表のセルに結び付いた 3 件の段落は、表のセルの blocks に入り、今も XML の表のセルの中に出ている（除外ではない）。F でも変えない（4.2 の「対象」）。
- 1 本目・2 本目にはない。本文に結び付いた文字だけの囲みの実例は、手元の 3 本にはない（13 章のリスク）。

### 1.3 しきい値が実例を分ける余裕

| 条件 | しきい値 | 実例 |
|---|---|---|
| 囲みの文字数 | 20 字以上 | 197〜210 字（td3 の囲み）、211・389 字（td1・td2 の表で組んだ問題文） |
| 囲みの幅 | 1 段の幅の 0.6 以上（読めなければ使わない） | 1.0〜2.07 段 |
| 注記の文字数 | 15 字以下 | 0〜11 字 |
| 注記の幅 | 1 段の幅の 0.4 以下（読めなければ使わない。グループの中では使わない） | 0.05〜0.37 段 |

---

## 2. 読み取り（`model.py`・`docx_reader.py`）

### 2.1 `model.py`

```python
@dataclass(eq=False)
class TextBox:
    """テキストボックス（w:txbxContent）1 つ。中の段落・表は textbox_id でこのテキストボックスを指す（入れ子の内側は外側の ID）。

    幅・高さは cm。DrawingML は wp:extent（グループの中なら wps:spPr の a:ext に、グループの拡大率〈wp:extent / a:chExt〉を掛ける）、
    VML は v:shape などの style の width・height（pt のときだけ。ほかの単位は読めないとして None）。
    """
    xid: str                         # x1, x2, ...（出現順）
    anchor_src: str                  # 結び付いている段落（アンカー段落。行内なら、その段落）
    source: str = ""                 # "wps"（DrawingML）/ "vml"
    inline: bool = False             # 行内（wp:inline、または position:absolute のない VML）
    absolute: bool = False           # VML の position:absolute（位置を指定した浮動配置）
    group: bool = False              # グループ図形・描画キャンバスの中（wpg:wgp / wpc:wpc / v:group）
    float_id: str = ""               # 浮動配置の図形（Float）の中なら、その ID（wp:anchor のテキストボックス自身の Float も）
    width_cm: Optional[float] = None
    height_cm: Optional[float] = None
```

- `Para.textbox_id: str = ""`、`Table.textbox_id: str = ""` を足す（`in_textbox`・`float_id` はそのまま。`in_textbox` は今までどおり
  テキストボックスの直下の段落だけ True。表のセルの段落は False のまま）。
- `Document.textboxes: list`（`TextBox`、出現順）を足し、`Document.textbox_excluded` と `Reader.textbox_excluded` を削除する（どこからも使われていない）。
- 位置（縦・横のずれ・基準）は、浮動配置（wp:anchor）なら同じ `Float` にある（`float_id` で引く）。VML の位置（margin-top など）は読まない
  （位置は推定扱いにするので要らない。AI への説明は「VML の位置指定」とだけ書く）。

### 2.2 `docx_reader.py`

- `Reader.__init__`: `self.textboxes = []`、`self._textbox = None`（読み取り中のテキストボックス）。`textbox_excluded` を削除。
- `read_paragraph`: `Para(..., textbox_id=self._textbox.xid if self._textbox else "")`。`read_table`: `Table(..., textbox_id=…)` も同じ
  （テキストボックスの中の表のセルの段落にも付く）。
- `_graphic` の DrawingML の枝: 今の `holder`（wp:inline / wp:anchor）・`inline`・`uri` を `_textboxes(el, para, holder=holder, inline=inline, group=…)` に渡す。
  `group = "wordprocessingGroup" in uri or "wordprocessingCanvas" in uri`。VML の枝: `_textboxes(el, para, vml=True)`。
- `_textboxes(container, para, ...)`: 各 `txbxContent`（入れ子を除く、今の判定のまま）について、`self._textbox is None and self.part == "word/document.xml"` なら
  `_new_textbox(tx, para, ...)` で `TextBox` を作り `self.textboxes` に足す。中身を読む間だけ `self._textbox` をそれにし、読み終えたら戻す
  （外側を読んでいる間は作らず、入れ子の段落は外側の ID を継ぐ。脚注・文末脚注の中のテキストボックスは記録しない＝今の扱い）。
- `_new_textbox`: 幅・高さ
  - DrawingML・グループでない: `holder` の `wp:extent`（cx, cy）/ 360000。
  - DrawingML・グループの中: `tx` の祖先の `wps:wsp` の `wps:spPr/a:xfrm/a:ext` × 拡大率（一番外側の `wpg:wgp` の `wpg:grpSpPr/a:xfrm/a:chExt` の cx と
    `holder` の `wp:extent` の cx の比。chExt がなければ 1）。読めなければ None。
  - VML: `tx` の祖先の `v:shape`・`v:rect`・`v:roundrect` の `style` の `width:…pt`・`height:…pt`（今の画像の読み取りと同じ正規表現。pt 以外は None）。
    `absolute = "position:absolute" in style（空白を除いて）`、`inline = not absolute`、`group` は祖先に `v:group` があるか。
  - `float_id = self._float.fid if self._float else ""`、`anchor_src = para.src`。
- 文字の読み方は変えない（`ooxml.canonical_text`・`pdfdocx.paragraph_units`・`raw_paragraph_ids` も変えない）。範囲外: ヘッダー・脚注の中、
  グループの入れ子の拡大率（一番外側だけ）。

---

## 3. 判定（`floats.py`）

### 3.1 定数と関数

```python
BOX_CHARS = 20        # 囲みとみなす文字数（空白を除く。数式・脚注記号は 1 字）の下限
BOX_WIDTH = 0.6       # 囲みとみなす幅（1 段の幅に対する割合）の下限
LABEL_CHARS = 15      # 図の注記とみなす文字数の上限
LABEL_WIDTH = 0.4     # 図の注記とみなす幅（1 段の幅に対する割合）の上限（グループ図形の中では使わない）
NEAR_PARAS = 2        # 「画像の近く」: アンカー段落の前後 2 段落以内（図形の外の最上位の段落・表で数える）

def box_lines(paras, width_cm, layout) -> int:
    """囲みの中の行数の推定。幅が分かれば、1 行の字数（幅 / 1 字の幅〈段の幅 / 1 行の字数〉）で文字のある段落ごとに割って足す
    （para_lines と同じく全角 1・半角 0.5）。幅が分からなければ、文字のある段落の数。"""

def textbox_kind(chars, width_cm, lines, near_image, group, layout) -> tuple:
    """文字だけのテキストボックスを、囲み（box）・図に重ねた注記（label）・決められない（undecided）・空白だけ（blank）に分ける。
    戻り値: (種類, 根拠の説明)。根拠は判断の一覧・3 章・AI 依頼文に出す（例:「文字 210 字、幅 12.9 cm〈1 段の幅の 1.5 倍〉、画像から離れている」）。"""
```

規則（上から順に。`col` は `layout.column_width_cm`、なければ 8.68 cm 相当の既定〈`Layout` が空のときは 1 段 = 本文の幅とし、それもなければ幅の条件を使わない〉）:

1. `chars == 0` → **blank**（空白だけ。数式も画像もない）。
2. `group`（グループ図形・描画キャンバスの中）: `chars <= LABEL_CHARS` → **label**（図そのものの中の文字）。それ以外 → **undecided**。
3. `chars <= LABEL_CHARS and near_image and (width_cm is None or width_cm <= LABEL_WIDTH * col)` → **label**。
4. `chars >= BOX_CHARS and (width_cm is None or width_cm >= BOX_WIDTH * col) and (not near_image or lines >= 2)` → **box**。
5. それ以外 → **undecided**。

`near_image`（`structure.Classifier.near_image`。4.3）: グループの中、またはアンカー段落とその前後 `NEAR_PARAS` 段落（図形の外の最上位の段落）に、
画像（行内・浮動配置〈`ImageRef.inline=False`〉・Word の図形〈`shape_only`〉。隠し文字の画像は除く）があるか、図キャプション（キャプションのスタイル、
または「図N」で始まり「。」で終わらない 80 字以下の段落）があるか、図表の入った浮動配置の図形（中に画像のある `Float`）が結び付いているとき。

### 3.2 境界の例（テストにする。`tests/test_floats.py::test_textbox_kind_boundaries`）

| 例 | 文字数 | 幅（段の割合） | 画像の近く | 行数 | グループ | 判定 |
|---|---|---|---|---|---|---|
| td3 のグループの注記 | 1〜11 | 0.05〜0.37 | （グループ） | 1 | はい | label |
| グループの中の長い説明（16 字） | 16 | 0.5 | （グループ） | 1 | はい | undecided |
| (a) 幅の広い囲み（問1…。／ヒント…。） | ≥20 | 1.4 | いいえ | ≥2 | いいえ | box |
| (b) 画像・図キャプションの次の段落の小さな「A 点」 | 2 | 0.12 | はい | 1 | いいえ | label |
| (c) 段落の末尾の行内の囲み | ≥20 | 0.9 | いいえ | ≥1 | いいえ | box |
| (d) 幅が広く短い「（ヒント）」 | 5 | 0.9 | いいえ | 1 | いいえ | undecided |
| 画像の近くの 1 行（20 字以上、幅広） | 25 | 0.9 | はい | 1 | いいえ | undecided |
| 画像の近くの 2 行以上の囲み | 40 | 0.9 | はい | 2 | いいえ | box |
| 画像の近くの、幅広の短い文字（図の題を枠に入れたもの） | 8 | 0.8 | はい | 1 | いいえ | undecided |
| 画像から遠い小さな枠「注」（sample_structure の N2） | 1 | 0.19 | いいえ | 1 | いいえ | undecided |
| 幅を読めない VML の短い文字 | 5 | None | いいえ | 1 | いいえ | undecided（label に倒れない） |
| 幅を読めない VML の短い文字、画像の近く | 5 | None | はい | 1 | いいえ | label |
| 幅を読めない VML の長い文字 | 30 | None | いいえ | 1 | いいえ | box |
| 幅の狭い長い文字（0.5 段） | 30 | 0.5 | いいえ | 3 | いいえ | undecided |
| 16〜19 字の幅広の文字 | 17 | 0.9 | いいえ | 1 | いいえ | undecided |
| 境界: 15 字・0.40 段・画像の近く | 15 | 0.40 | はい | 1 | いいえ | label |
| 境界: 20 字・0.60 段・画像から遠い | 20 | 0.60 | いいえ | 1 | いいえ | box |
| 空 | 0 | – | – | – | – | blank |

「決められない」になるのは、短いが注記らしくない（画像から遠い・幅広）、長いが囲みらしくない（狭い・画像の近くの 1 行）、グループの中の長い文字。
迷ったら除外して知らせる（図の注記を本文に混ぜない。決定事項 9(2)）。

---

## 4. 構造の組み立て（`structure.py`）

### 4.1 新しいデータ

```python
@dataclass(eq=False)
class BoxNode:
    """囲み（文字だけのテキストボックス）。<boxed-text> になる。children は PNode・ListNode・QuoteNode・FormulaNode。"""
    xid: str
    children: list = field(default_factory=list)

@dataclass(eq=False)
class BoxInfo:
    """文字だけのテキストボックスの扱い（レポート・AI 依頼文・知らせに使う）。"""
    box: TextBox
    paras: list                     # テキストボックスの段落（出現順。items にあるもの）
    kind: str = ""                  # box / label / undecided / blank（AI の指定の後は、指定の種類）
    why: str = ""                   # 判定の根拠（floats.textbox_kind）
    mode: str = ""                  # mechanical / ai
    where: str = ""                 # before（アンカー段落の前）/ after（アンカー段落の後ろ）/ end（本文の最後）/ ai（AI の指定の段落の後ろ）/ ""（出力しない）
    estimated: bool = False         # 位置を推定した（要確認）
    after_src: str = ""             # 後ろに置いた本文の段落（before ならアンカー段落の前の段落ではなくアンカー段落を入れる）
    outside: str = ""               # アンカー段落が本文の外なら、その領域（refs / fn / notes / ack / back / front_en。N7）
```

- `ArticlePlan.textboxes: dict = {}`（xid → BoxInfo。文字だけのテキストボックスで、place_boxes が扱ったもの。blank も入れる）。
- `ArticlePlan` に `undecided_boxes`（kind が undecided の xid）と `estimated_boxes`（kind が box で estimated の xid）の property を足す。
- 定数: `TEXTBOX_LABEL_EXCLUDED = "テキストボックス内の文字（図に重ねた注記とみなして本文から除外）"`、
  `TEXTBOX_UNDECIDED_EXCLUDED = "テキストボックス内の文字（囲みか図の注記か決められないため本文から除外。要確認）"`、
  `TEXTBOX_AI_LABEL_EXCLUDED = "テキストボックス内の文字（AI による補完で図に重ねた注記と判断し、本文から除外）"`。
  どれも「テキストボックス内の文字」で始める（既存のテスト・利用者の見慣れた表記と揃える）。`TEXTBOX_TEXT_EXCLUDED` は、図形の中の図表の
  一部の文字（キャプションのあるテキストボックスのほかの段落など。下の「対象外」）に今までどおり使う。コメントの「暫定の知らせ」は消す。
- `OUTSIDE_JA = {"refs": "引用文献", "fn": "注", "notes": "付記", "ack": "謝辞", "back": "後付け", "front_en": "英文の部分"}`。

### 4.2 対象（文字だけのテキストボックス）

`Classifier.text_only(xid) -> bool`（1 か所で決める。`place_floats` の「図表ではない」判定と `place_boxes` の対象の両方で使う）:
- そのテキストボックスの最上位の要素（`self.box_members[xid]`: `run()` で、AI の exclude を除いた後の flat から textbox_id ごとに集めた段落・表）に、
  表がない、画像のある段落がない、図表キャプションの段落（items の役割が fig_caption / table_caption、または `textbox_caption` の形）がない。
- かつ、`float_id` があるなら、その Float が図表の入った図形（`plan.floats` に入るもの）でない（グループの Float の中の注記は範囲外。FIX_PLAN (9)）。

対象外（今の扱いのまま）: 表のセルの段落に結び付いたテキストボックス（中身は表のセルの blocks にあり、items に出てこない。td3 の資料の 3 件）、
和文の冒頭（front_ja）に結び付いたもの、資料（app）の中のもの、脚注・文末脚注の中のもの、図表の入った浮動配置の図形（`FloatInfo`）の中のもの、
キャプション・画像・表を含むテキストボックス（キャプションは今までどおりキャプションに、ほかの段落は `TEXTBOX_TEXT_EXCLUDED`）。

`place_floats` の `if not (info.images or info.tables or groups or any(q.images for q in info.paras)): continue` は残す（意味は text_only と同じ。
コメントに「place_boxes で扱う」と書く）。

### 4.3 `near_image(tb) -> bool`

`self._top`（`run()` で作る、図形の外の最上位の段落・表の列〈doc.blocks のうち `in_shape` でないもの〉）と `self._top_index`（段落 ID → 位置）を使う。
3.1 の定義のとおり。図表の入った浮動配置の図形の判定は `{img.float_id for img in doc.images if img.float_id}` に入る Float の `anchor_src`。

### 4.4 `place_boxes(items, src_index) -> (inserts, taken)`

`build_body` で `place_floats` の直後に、**元の items**（place_floats に渡したものと同じ列。差し込み位置はこの列の位置で数える）で呼ぶ。
`doc.textboxes` を出現順に回す（別のパス。FIX_PLAN (6)）。各 `tb` について:

1. `members = [b for b, _ in items if b.textbox_id == tb.xid]`。空なら飛ばす（表のセル・冒頭・本文の外で 2 回目に回されなかったもの・AI の exclude）。
2. `text_only(tb.xid)` でなければ飛ばす（今の扱い。build_body の in_textbox の枝が処理する）。
3. 種類: AI の指定（`self.placements.get(tb.xid)`。4.9）があればそれ、なければ `textbox_kind(...)`。文字数は `plain()` の空白以外の数（数式は 1 字）。
4. 空白だけの段落は、どの種類でも `plan.exclude_blank(p)`（文字のまったくない段落は記録されない。今と同じ）。`plan.region[p.src] = "body"`。
5. 種類ごと:
   - **blank**: 4 だけ。判断・知らせは出さない（FIX_PLAN (5)）。
   - **label**: 文字のある段落を `plan.exclude(p, TEXTBOX_LABEL_EXCLUDED)`（AI の指定なら `TEXTBOX_AI_LABEL_EXCLUDED`）。判断の一覧に記録し、
     アンカー段落ごとに 1 行の警告を `plan.warnings` に足す（「d67: 図に重ねた注記と判断したテキストボックス 6 件（x3〜x8）の文字を本文から除外しました（6 章）」）。
   - **undecided**: 文字のある段落を `plan.exclude(p, TEXTBOX_UNDECIDED_EXCLUDED)`。判断の一覧に `applied=False` で記録（AI 依頼文の「推定:」に載る）。知らせは 7 章。
   - **box**: `BoxNode(xid, children=self.box_children(文字のある段落, roles))` を作り、`(target, (BODY_END, k), [("node", node)])` を inserts に足す
     （同じ位置の浮動配置の図表の後ろ。同じ位置の囲みどうしは docx の順）。置き場所（4.5）を `BoxInfo` に記録し、判断の一覧に記録する。
6. `taken` に members の id を入れる（build_body の役割の決め方の枝に流さない）。`plan.textboxes[tb.xid] = BoxInfo(...)`。

`build_body` は `items, inserts, raw, prov = self.place_floats(items)` の後に `box_inserts, taken = self.place_boxes(orig_items, src_index)` を呼び、
`inserts += box_inserts`、`items = [x for x in items if id(x[0]) not in taken]` にする（src_index は place_floats と同じものを返させるか、build_body で作って渡す）。
in_textbox の除外の枝（`if b.in_textbox and role not in (...) and not b.images:`）は、文字だけでないテキストボックスの段落にだけ当たる（今までどおり）。

`box_children(paras, roles)`: 段落ごとに、items の役割が quote なら QuoteNode（続けば 1 つに）、`formula_node(p)` があれば FormulaNode、
自動番号の段落（`numbering` と `autonum`）は同じ番号の定義が続く間 ListNode（`doc_numbering_is_bullet` で順序の有無）、それ以外は PNode。
見出しのスタイルの段落も PNode（boxed-text の中に sec を作らない。J-STAGE の boxed-text の子に sec はない）。各段落に `_take(p, "p" か "quote")`。

### 4.5 置き場所の規則

| テキストボックス | 置く位置（items での差し込み位置） | where | estimated（要確認） |
|---|---|---|---|
| 浮動配置（wp:anchor）で `floats.at_anchor(fl, layout)` | アンカー段落の前（`src_index[anchor]`） | before | いいえ |
| 浮動配置でそれ以外 | アンカー段落の後ろ（`run_end` で箇条書き・引用の終わりにずらす） | after | はい |
| 行内（wp:inline）・位置指定のない VML | アンカー段落の後ろ（`run_end` でずらす） | after | いいえ |
| VML の position:absolute | アンカー段落の後ろ（`run_end` でずらす） | after | はい |
| アンカー段落が本文の外（N7） | 本文の最後（`BODY_END`） | end | はい |
| アンカー段落が items にない（和文の冒頭の最後のセクション区切りに結び付いた、本文に入った図形） | テキストボックスの最初の段落の位置（本文の最初） | after | はい |
| AI の指定（kind box・after） | 指定の段落の後ろ（`src_index[after] + 1`。ずらさない） | ai | いいえ |

- 付録 D1 の (a) は前、(c) の inline は後ろ（FIX_PLAN）。図の左上がアンカー段落の左上にあるときに前に置くのは、浮動配置の図表（6.1 の `at_anchor`）と同じ考え。
- 位置を推定したものに `estimate_top_left` は使わない（浮動配置の図表と同じく、行数の推定は AI に渡す目安にとどめる）。
- アンカー段落が箇条書き・引用の途中なら終わりにずらすのは、位置を決められない図表（B3、`run_end`）と同じ（箇条書きを 2 つに分けない）。

### 4.6 `plan.body_seq`・`run_end`

- `place_floats` の `plan.body_seq = [b.src for b, _ in items if isinstance(b, Para) and not b.float_id]` に `and not b.textbox_id` を足す（FIX_PLAN (4)）。
  浮動配置でないテキストボックスの段落が、AI の after・行数の推定・仮の位置の段落に入らないようにする。
- `run_end` の `skip(b)` に `or bool(b.textbox_id)` を足す（テキストボックスの段落はその位置に出さないので飛ばす）。`list_or_quote` は今のまま
  （図形の中の段落は箇条書きにしない）。

### 4.7 `compute_locations`・`node_paras`・`assign_ids`・`nest`

- `node_paras(BoxNode)` = `[p for c in node.children for p in node_paras(c)]`。`compute_locations` は BoxNode を 1 つの要素として数える（変更は node_paras だけ）。
- `assign_ids` の `walk`: `elif isinstance(node, BoxNode): walk(node.children)`（囲みの中の別行数式に FD の ID。図・表は入らない）。
- `nest`: 変更なし（BoxNode は Sec でない要素）。`float_targets` の walk: 変更なし（BoxNode の中の段落は図形の中身から出した段落として数えない。囲みは手作業で移す対象ではない）。

### 4.8 N7（本文の外に結び付いた図形）: 構造の組み立てを 2 回行う

- 図形の中身は `split_regions` でアンカー段落と同じ領域に入る（今のまま）。英文の部分（front_en）では、資料（app）が始まったかどうかは
  `build_front_en` の中でしか決まらず、`build_body` はその前に動く。順序を入れ替えると、すべての原稿の判断の番号（M-001 …）が変わるので、
  次の 2 回にする（`classify()`）:
  1. 1 回目: 今の順で組み立てる。`build_back` と `build_front_en`（資料が始まる前）は、本文の外の図形の要素
     （`b.float_id` のある段落・表、または `b.textbox_id` があり `text_only` のテキストボックスの段落）を、**状態を変えずに飛ばし**、
     `self.outside[key] = 領域`（key は float_id か textbox_id。領域は build_back の state〈なければ "back"〉、build_front_en では "front_en"）に記録する。
     資料が始まった後（`app is not None`）の図形は今のまま資料の中に出す。
  2. `self.outside` が空なら 1 回目の plan を返す（**本文の外の図形がない原稿は 0.24.1 と同じ処理・同じ判断の番号**）。
  3. 空でなければ、1 回目が段落に書き込んだもの（`Para.role`・`role_origin`・`note`。`classify` の最初に doc のすべての段落〈本文・表のセル・脚注・文末脚注〉で
     控える）を戻し、`Classifier(..., outside=self.outside)` で組み立て直す。2 回目の `split_regions` は、`in_shape(b)` で key が `outside` にある要素を、
     その時点の状態にかかわらず `regions["body"]` の最後に足す（docx の順。領域の状態は変えない）。
  - 2 回目の `build_back`・`build_front_en` で新しく本文の外の図形を見つけたら（起きないはず）、同じく飛ばす。出力にも除外にもならないので
    不変性チェックが「出力漏れ」で不合格になり、黙って消えることはない。
- `place_floats`: `fl.anchor_src not in src_index` で `continue` していたところを、`key = fl.fid in self.outside` なら続ける（それ以外は今までどおり continue。
  表のセル・冒頭に結び付いた図形）。本文の外の図形は:
  - 図表の入った図形（images・tables・キャプション）なら FloatInfo にし、AI の指定（after が本文の段落）があれば `float_from_spec` で mode ai、
    なければ **mode unplaced**（`at_anchor` は見ない）。`info.reason = f"図形が本文の外（{OUTSIDE_JA[領域]}）の段落に結び付いている"`。
    仮の位置は `provisional_target`（アンカー段落が body_seq にないので end・end_why "anchor" ＝ 本文の最後。決定事項 21 の後半、B3 で用意済み）。
    AI を使わない設定では `pipeline.AIRequiredError` で止まる（決定事項 10。今の仕組みのまま）。
  - グループ図形の画像（`ImageRef.float_id` がその図形）は、アンカー段落が items にないので、`plan.paras[fl.anchor_src].images` から集める
    （本文に結び付いた図形は今までどおり items から集める）。`moved_images` に入れ、図に入れる（引用文献の段落では画像はもともと出せない）。
  - 文字だけのテキストボックスは `place_boxes`（4.5 の end）。
- 引用文献・注などの段落そのものにある画像（テキストボックスの外の、行内・浮動配置の画像。Float にならないもの）は、今までどおり段落のまま
  （A の N1 の `lost_images` で要対応）。浮動配置でない（行内・VML の）テキストボックスで、キャプション・画像・表を含むものも、今のまま
  その領域の段落（範囲外。7 章の限界に書く）。

### 4.9 AI の指定の反映（structure 側）

`place_boxes` で `spec = self.placements.get(tb.xid)`（ai_assist で検証済み。kind は box か label）:
- label: 除外（`TEXTBOX_AI_LABEL_EXCLUDED`）。`d = plan.decide("ai", "box", tb.anchor_src, f"テキストボックス {xid}（「…」）を図に重ねた注記と判断し、本文から除外した。{reason}", confidence)`。
- box: `spec["after"]` が `src_index` になければ（組み直した後に本文の段落でなくなった）指定なしに戻す（FIX_PLAN (3)）。あれば `src_index[after] + 1` に置き、
  `d = plan.decide("ai", "box", after, f"テキストボックス {xid}（「…」）を囲み（boxed-text）として段落「…」の後に置いた。{reason}", confidence)`。
- どちらも `plan.float_decisions[tb.xid] = d`（pipeline が `outcome.accepted` に載せる。既存のループのまま）。

### 4.10 判断の一覧の文（機械処理。category "box"）

- box・前: 「テキストボックス x1（「問1　…」ほか、文字 32 字）を囲み（boxed-text）とし、アンカー段落「…」の前に置いた（{why}。図の左上がアンカー段落の左上の位置にあるため）」
- box・後ろ（行内）: 「…行内のテキストボックスなので、アンカー段落「…」の後に置いた」
- box・推定: 「…位置は docx から決められない（{why_not_at_anchor か「VML の位置指定」}）ので、アンカー段落「…」の後に置いた（要確認）」
- box・本文の外: 「…アンカー段落が本文の外（引用文献）にあるので、本文の最後に置いた（要確認）」
- label: 「テキストボックス x3（「A 点」）を図に重ねた注記と判断し、本文から除外した（{why}）」
- undecided（applied=False）: 「テキストボックス x4（「（ヒント）」）は、囲みか図の注記か決められない（{why}）。本文から除外した（AI による補完の placements で kind box・label を指定できる）」
- `report.CAT_JA["box"] = "囲み（テキストボックス）"`、`ai_assist.build_request` の「推定:」の対象の category に "box" を足す。

---

## 5. XML（`builder.py`・`emit.py`・`linker.py`）

- `builder.Builder.nodes(parent, nodes, top=False)`: `elif isinstance(node, BoxNode): self.boxed_text(_sub(parent, "p") if top else parent, node)`。
  `boxed_text(parent, node)`: `bt = _sub(parent, "boxed-text")`、`self.nodes(bt, node.children)`（PNode は `<p>`、ListNode は `<list>`、QuoteNode は
  `<disp-quote>`、FormulaNode は `<disp-formula id="FD1">`）。段落の文字は今までどおり `Emitter.span()`（文脈 `E.BODY`）。id は付けない。
  `top` は今は使われていない引数で、`build` が本文の最上位だけ True で呼んでいる（変えない）。
- DTD（同梱の JATS 1.1）で確かめたこと（`scratchpad/f/design/dtdtest.py`）: body の最初の章の前に直接置く・sec の中・p の中・app の中、中に p・
  disp-formula・list・table-wrap・disp-quote・fig を入れても、どれも合格。sec の中で子の sec の後ろに置くと不合格（nest はつねに最も深い節の children に
  足すので、この形は作られない）。
- J-STAGE の全文 XML 作成マニュアル（3.5.4 (1)）: `<body>` の子は `<p>` と `<sec>` だけ。`<boxed-text>` は `<sec>` と `<p>` の子に置ける。中の `<p>` は
  「タグによっては表示が崩れる恐れがあります」。したがって、本文の最上位（最初の章見出しの前）では `<p><boxed-text>…</boxed-text></p>` にする
  （FIX_PLAN の「本文の冒頭では <p> で包む」はこの意味。docs/JSTAGE_NOTES.md に根拠を書く）。
- `emit.py`: 変更なし。
- `linker.body_paragraphs`: `elif isinstance(node, BoxNode): yield from walk(node.children, "cell")`（囲みの段落は文脈 cell、別行数式は formula）。
  リンク（図・表・式・注・引用文献・URL）は本文と同じく付く。文脈を cell にするのは、出版版 PDF との照合（`pdfmatch.target_paragraphs` は cell と formula を除く、
  `_flow_paragraphs` はテキストボックスの段落を流れから除く）で、囲みの段落を照合しない・ルート2 で直さない（0.24.1 と同じ扱い。B3 の `cell_paras` と
  同じ方法）ため。照合の規則（pdfmatch.py）には触らない。docstring に「囲みの段落（BoxNode）も cell」と書く。

---

## 6. AI（`ai_assist.py`）

### 6.1 回答の形

- `PLACEMENT_SCHEMA`:
  - `float` の description: 「図形の ID（s1 など）、またはテキストボックスの ID（x1 など）。「位置を決められなかった図表」「囲みか図の注記か決められなかったテキストボックス」
    「位置を推定した囲み」に挙げたもの」。
  - `after` の description に「テキストボックスで kind が label のときは空文字」。
  - `items.kind` の enum を `["fig", "table", "box", "label"]` にし、description「fig（図）・table（表）は図形（s1 など）の中身の組。box（本文の囲み）・label（図に重ねた注記。
    本文に出さない）はテキストボックス（x1 など）に 1 つだけ書き、caption と body は空の一覧 []」。
- `FIELD_GUIDE`（placements の各項目）:
  - 「- float: 図形の ID（s1 など）か、テキストボックスの ID（x1 など）」
  - 「- after: …。テキストボックスを label にするときは ""」
  - 「- items: 図・表ごとの組。kind（fig / table）、caption（…）、body（…）。テキストボックス（x1 など）では、kind を box（本文の囲み。問題文・ヒントなど）か
    label（図に重ねた注記。矢印のラベルなど）にした組を 1 つだけ書き、caption と body は []」
  - 先頭の文「placements（…依頼文に「# 位置を決められなかった図表」がなければ []）」を「placements（「# 位置を決められなかった図表」と
    「# 囲みか図の注記か決められなかったテキストボックス」に挙げたものごとに 1 件。どちらもなければ []）」にする。
- `MANUAL_EXAMPLE`: placements に 2 件目 `{"float": "x2", "after": "d30", "items": [{"kind": "box", "caption": [], "body": []}], "reason": "問題文と
  ヒントの囲みで、図の注記ではない。本文で「次の問題」と述べた段落 d30 の直後", "confidence": "中"}` を足す。
- `manual_prompt` の「回答の書き方」: 「- 「# 位置を決められなかった図表」に挙げた図形は…」の後ろに
  「- 「# 囲みか図の注記か決められなかったテキストボックス」に挙げたもの（x1 など）も、すべて placements に書いてください（kind は box か label）。」を足す。
- `SYSTEM_PROMPT`:
  - 「6. placements」の箇条に足す: 「- 「# 囲みか図の注記か決められなかったテキストボックス」に挙げたもの（x1 など）は、1 つ残らず placements に 1 件ずつ指定して
    ください。float にテキストボックスの ID、items に {"kind": "box" か "label", "caption": [], "body": []} を 1 つだけ書きます。box は本文の囲み（問題文・
    ヒント・まとめなど。本文として読まれる文章）で、after の段落の直後に枠で囲んだ段落として置きます。label は図に重ねた注記（矢印・点・辺の名前など、
    図の一部の短い文字）で、本文に出しません（after は空文字）。「# 位置を推定した囲み」に挙げたものは、置いた位置が違うときだけ、kind box で正しい
    after を指定してください。」
  - 最後の箇条「- テキストボックス・グループ図形の中の段落の役割は、set_role ではなく placements で指定してください。」を
    「- 浮動配置の図形（s1 など）の中の段落の役割は、set_role ではなく placements で指定してください。浮動配置でないテキストボックスの段落に
    set_role で指定できるのは fig_caption・table_caption・exclude だけです（囲みか図の注記かは placements の kind box・label で指定します）。」にする。
- `RESPONSE_SCHEMA.placements` の description に「囲みか図の注記か決められなかったテキストボックス」を足す。

### 6.2 依頼文（`build_request`・`float_section`）

- 段落一覧の場所: `elif p.textbox_id: loc = f"テキストボックス {p.textbox_id} の中"`（float_id の後）。除外した段落も今までどおり載る。
- `float_section` に節を足す（`plan.textboxes` から）:
  - 「# 囲みか図の注記か決められなかったテキストボックス」: 「以下のすべてについて、placements に kind（box か label）を必ず指定してください（box なら after も）。」
    各件: `[x4] アンカー段落: [d20]「…」（本文の外〈引用文献〉の段落なら、その旨）` / `大きさ: 幅 … cm（1 段の幅の … 倍）・高さ … cm（読めなければ「読めない」）。
    位置: {浮動配置なら floats.describe、行内なら「行内（アンカー段落の行の中）」、VML なら「VML の位置指定」}` / `画像の近く: はい・いいえ` / `判定できなかった理由: {why}` /
    `中身:` 段落ごとに `[src] para_view(q)[:80]`。
  - 「# 位置を推定した囲み（位置が違うときだけ placements で kind box と after を指定）」: `[x5] 段落 [d31] の後ろに置いた（理由: …）。中身: …`。
  - 「# 扱いを機械的に決めたテキストボックス（変更不可。placements に書かないこと）」: 囲み（位置が決まっているもの）は `[x1] 囲み: 段落 [d12] の前に配置済み`、
    注記はアンカー段落ごとにまとめて `[x3]〜[x8] 図の注記（段落 [d67] の図）として除外済み`。
  - 節の順は、浮動配置の図表の節の後ろ。どの節も、該当がなければ出さない（今の依頼文は、テキストボックスのない原稿では変わらない。ただし SYSTEM_PROMPT・
    FIELD_GUIDE・MANUAL_EXAMPLE はどの原稿でも変わる）。
- `set_role_hint`: `p.textbox_id` があり `p.float_id` がない段落で、`set_role_problem(p, plan, "p")` が拒否するときは、
  「（囲みなら placements の kind box、図の注記なら label で指定）」を返す（「本文の一部なら set_role を提案」とは書かない）。
- 添付画像: 増やさない（決められないテキストボックスの近くの画像は、キャプションのない図なら今までどおり添付される）。

### 6.3 検証（`set_role_problem`・`float_placements`・`_placement_problem`）

- `set_role_problem`（E で作った 1 か所の規則）に、`p.float_id` の判定の直後に足す:
  ```python
  if p.textbox_id and role not in ("fig_caption", "table_caption", "exclude"):
      return ("浮動配置でないテキストボックスの段落に指定できる役割は fig_caption・table_caption・exclude だけ"
              "（囲みか図の注記かは placements の kind box・label で指定する）")
  ```
  浮動配置の図形（float_id）の段落は今までどおり「placements で指定する」で拒否（wp:anchor のテキストボックスは Float を持つので、こちらに当たる）。
  docstring の「文字だけのテキストボックスの段落（float_id のないもの）の規則は、修正計画の F で足す」を消し、規則を書く。
  VML のキャプションへの `set_role fig_caption` は今までどおり採用される（回帰しない。FIX_PLAN (1)）。
- `float_placements`: そのまま（`_placement_problem` の結果で採用する）。採用した box・label の指定は `out[xid] = {"kind": kind, "after": after, "items": items,
  "reason": …, "confidence": …, "op": op}`。テキストボックスの指定の after が本文の外の段落でも、「本文の最後」の印（where end）は付けない（不採用にするだけ）。
- `_placement_problem`: 最初に `box = plan.textboxes.get(fid)` を見る:
  ```
  if box is not None:
      if box.kind == "undecided" or (box.kind == "box" and box.estimated) は指定できる。ほかは
          「テキストボックス {fid} は扱いを機械的に決めたので、変更できない」
      2 回目 → 「テキストボックス {fid} の指定が 2 回ある（最初の指定を採用）」
      items が 1 つの dict でない → 「テキストボックスの items は、kind が box か label の組を 1 つだけ書く」
      kind が box・label でない → 同上
      caption・body が空の一覧でない → 「テキストボックスの指定では caption と body は空の一覧 [] にする」
      位置を推定した囲みに label → 「位置を推定した囲みには box だけを指定できる」
      kind が box で after が body にない → 「置く位置の段落 {after} は本文の段落ではない（図形の中の段落・表のセル・本文以外は指定できない）」
      → ""
  ```
  浮動配置の図形（plan.floats）に kind box・label → 「図形 {fid} の items の kind は fig か table」（今の「items の kind は fig か table」の文で足りる）。
  ID がどちらにもない → 「図形 {fid} は「位置を決められなかった図表」にない」を「{fid} は「位置を決められなかった図表」「囲みか図の注記か決められなかった
  テキストボックス」「位置を推定した囲み」にない」にする。
- `placement_op`: 変更なし（text に「box: キャプション  / 本体 」が入る。レポートの 2 章でそのまま読める）。
- `target_keys`・`retarget_ops`: 変更なし（囲みの中の数式は FormulaNode として keys に入る）。

---

## 7. パイプラインと知らせ（`pipeline.py`・`report.py`）

### 7.1 `pipeline.py`

- `classify` が 2 回組み立てても、`_mechanical` は変えない。
- AI の採用の一覧: 既存の `for sid, spec in placements.items(): if sid in plan.float_decisions: outcome.accepted.append(...)` で、xid の指定も載る（変更なし）。
- 3 章（`unresolved_after`）: 浮動配置の図表の行の後ろに、`plan.textboxes` から足す:
  - undecided: `("box", _located(plan, anchor), f"テキストボックス {xid}「{head}」", detail)`。detail は、手動モードで回答前なら
    「囲みか図の注記か決められない（{why}）。AI の回答を反映すると判断される（今は XML に出力していない）」、それ以外は
    「囲みか図の注記か決められない（{why}）。XML に出力していない。AI による補完を使って変換し直すか、Word で確かめ、本文に必要な囲みなら文字をテキストボックスの外
    （本文の段落）に出して変換し直す」。
  - 位置を推定した囲み（estimated）: detail「囲み（boxed-text）を{段落「…」の後ろ / 本文の最後}に置いた（位置は推定: {理由}）。PDF と見比べ、違えば XML の中で
    boxed-text を正しい位置に移す」。
  - 場所の欄はアンカー段落の場所（本文の外なら「引用文献 3件目」など）。
- `AIRequiredError`: 変更なし（本文の外の図表は `info.reason` で「図形が本文の外（注）の段落に結び付いている」と出る）。
- `lost_images`: 変更なし。

### 7.2 `report.py`

- 削除: `provisional_exclusions`、`PROVISIONAL`、`_provisional_actions`、`actions()` の `+ _provisional_actions(r)`、`from .structure import TEXTBOX_TEXT_EXCLUDED`、
  冒頭の `late = [... or a.key in PROVISIONAL]` の `or a.key in PROVISIONAL`、14 章の `a.key in PROVISIONAL`（画像がすべて Graphics/ にある行を、
  XML に入らなかった画像〈lost〉の前に出す規則だけ残す）。
- `UNRES_JA["box"] = "囲み・図の注記"`、`CAT_JA["box"] = "囲み（テキストボックス）"`。
- 1 章の表: `plan.textboxes` に blank 以外があれば、行「テキストボックスの文字（3 章・6 章）」を「位置を決められなかった図表」の行の後ろに足す:
  「囲み {a} 件（boxed-text。うち位置を推定 {e} 件）、図の注記として除外 {l} 件、決められずに除外 {u} 件（要確認）」（0 件の項目は書かない）。
- `actions()` の head の並びに、`figure_body_action` の後ろに `_textbox_undecided_action`・`_textbox_place_action` を足す（どちらも要確認 TO_CHECK。
  要対応にしない: 文字は 6 章に全文があり、図の注記を本文に混ぜるほうが害が大きい。決定事項 9(2)）。

`_textbox_undecided_action(r)`（key `textbox_undecided`。`plan.undecided_boxes` がなければ None。対象の例は `_para_samples` と同じく 5 件まで）:
- top: 「> **要確認: 囲み（問題文・ヒントなど）か図の注記か決められなかったテキストボックスが {n} 件あり、その文字を XML に出力していません（3 章・6 章）。**
  AI による補完を使うと、AI が囲みか注記かを判断し、囲みは本文に出します（強く勧めます）。AI を使わないときは、Word でそのテキストボックスを確かめ、
  本文に必要な囲みなら、文字をテキストボックスの外（本文の段落）に出してから変換し直してください。対象: x4（段落 d20「…」に結び付いた「（ヒント）」）…」
- checklist: 「- [ ] **囲みか図の注記か決められなかったテキストボックス {n} 件**（3 章。XML に出力していない）: AI による補完を使って変換し直すか、
  Word で確かめ、本文に必要な囲みならテキストボックスの外に出して変換し直す」
- box_title: 「囲みか図の注記か決められなかったテキストボックスが {n} 件あります（要確認）」
- box_detail: 「その文字は XML に出力していません。手順 5 で AI による補完（「API で自動実行」か「手動」）を選んで変換し直すと、AI が囲みか注記かを判断します。
  AI を使わないときは、Word で確かめ、本文に必要な囲みなら文字をテキストボックスの外に出してから変換し直してください（レポートの冒頭・3 章・6 章）。\n対象: …」
  （手動モードで回答前・AI の回答を反映した後は、「手順 5 で…選んで」の文を「AI の回答に kind の指定がないか、採用されませんでした（2 章）」に替える）
- cli: 「要確認: 囲みか図の注記か決められなかったテキストボックス {n} 件の文字を XML に出力していません（レポートの冒頭と 3 章）。--ai manual か --ai api で
  AI による補完を使うか、docx でその文字をテキストボックスの外に出して変換し直すこと」

`_textbox_place_action(r)`（key `textbox_place`。`plan.estimated_boxes` がなければ None）:
- top: 「> **要確認: 位置を推定して置いた囲み（boxed-text）が {n} 件あります（3 章）。** docx には Word で表示したときの位置が記録されていないため、
  アンカー段落のすぐ後ろ（本文の外に結び付いたものは本文の最後）に置きました。PDF と見比べ、違えば XML の中で囲みを正しい位置に移してください: x5（段落「…」の後ろ）…」
- checklist: 「- [ ] 位置を推定して置いた囲み {n} 件（3 章の「囲み・図の注記」）を PDF と見比べ、違えば XML の中で移す」
- box_title: 「位置を推定して置いた囲みが {n} 件あります（要確認）」、box_detail・cli も同じ内容（cli は「レポートの冒頭と 3 章」）。

- 6 章: 除外の理由（4.1 の 3 つ）がそのまま載る（変更なし）。10 章: label の警告（plan.warnings。pipeline が足す）。4 章: 判断の一覧（category box）。
- 冒頭の手動モードの説明（`pipeline.output_note`）: 決められないテキストボックスがあれば「囲みか図の注記か決められなかったテキストボックス（3 章）は、
  AI の回答を反映するまで XML に出力していません。」を足す（pipeline の既存の文の組み立てに 1 文足すだけ。`_ai_pending_action` の box_detail にも同じ 1 文）。
- colab.py・cli.py・tools/make_notebook.py は変えない（Action を足すだけで、赤い枠・手順 8・標準エラーに出る）。

---

## 8. 関数ごとの変更点（一覧）

| ファイル | 変更 |
|---|---|
| model.py | `TextBox` を足す。`Para.textbox_id`・`Table.textbox_id`・`Document.textboxes` を足し、`Document.textbox_excluded` を削除 |
| docx_reader.py | `Reader.__init__`（textboxes・_textbox。textbox_excluded 削除）、`read`（Document に textboxes）、`read_paragraph`・`read_table`（textbox_id）、`_graphic`（holder・inline・group を渡す）、`_textboxes`（TextBox を作り、読む間 _textbox を立てる）、`_new_textbox`（大きさ・種類） |
| floats.py | 定数 5 つ、`box_lines`、`textbox_kind`。モジュールの docstring に「文字だけのテキストボックスの判定」を足す |
| structure.py | `BoxNode`・`BoxInfo`・`OUTSIDE_JA`・除外の理由 3 つ、`ArticlePlan.textboxes`・`undecided_boxes`・`estimated_boxes`、`Classifier.__init__(…, outside=None)`（`self.outside`）、`run`（box_members・_top）、`split_regions`（outside の要素を body へ）、`build_body`（place_boxes を呼ぶ）、`place_floats`（body_seq、本文の外の Float、グループ画像の集め方）、`place_boxes`・`box_children`・`text_only`・`near_image`（新規）、`run_end`（skip）、`node_paras`・`assign_ids`（BoxNode）、`build_back`・`build_front_en`（本文の外の図形を飛ばして記録）、`classify`（2 回の組み立てと段落の書き込みの戻し） |
| builder.py | `nodes`（BoxNode）、`boxed_text`（新規） |
| linker.py | `body_paragraphs`（BoxNode を cell で） |
| ai_assist.py | `PLACEMENT_SCHEMA`・`RESPONSE_SCHEMA`・`SYSTEM_PROMPT`・`MANUAL_EXAMPLE`・`FIELD_GUIDE`・`manual_prompt`、`build_request`（場所、推定の category）、`float_section`（3 つの節）、`set_role_problem`・`set_role_hint`、`_placement_problem`、`float_placements`（box・label の spec の形） |
| pipeline.py | 3 章の行（box）、手動モードの説明の 1 文、plan.warnings（label の警告は structure が足す） |
| report.py | 暫定の知らせの削除、`CAT_JA`・`UNRES_JA`、1 章の行、`_textbox_undecided_action`・`_textbox_place_action`、`actions` の並び、`_ai_pending_action` の 1 文 |
| __init__.py・pyproject.toml | 0.25.0 |
| notebooks | `python tools/make_notebook.py` で作り直す（版だけ変わる） |

変えないもの: pdfmatch.py、pdfdocx.py、ooxml.py、fidelity.py、emit.py、colab.py、cli.py、tools/make_notebook.py、images.py、package.py。

---

## 9. テストの計画

### 9.1 fixture（`tests/make_fixtures.py`）

- 部品: `textbox_inline(inner, pid, cx, cy)`（wp:inline の wps。Fallback なし）、`vml_textbox(inner, width="300pt", height="60pt", absolute=False)`
  （`<w:r><w:pict><v:shape style="…"><v:textbox><w:txbxContent>…`。absolute なら style に `position:absolute;margin-left:0;margin-top:0`）、
  `textbox` は今のまま（anchored・Fallback 付き）。
- `make_structure` に節を足す: `STRUCTURE_SECTIONS` に `("囲みと図の注記", structure_textboxes)`（最後の「おわりに」の前。既存の節の後ろなので、既存の段落 ID は変わらず、
  後ろの段落の ID だけがずれる。テストは段落の文字で対象を選ぶ）。`structure_textboxes(b)` の中身（すべて架空の文字）:
  - (a) アンカー段落「試験（2025）の問題を次に示す。」に、`textbox(cx=12 cm, cy=3 cm, h=column 0, v=paragraph 0)` の囲み:
    「問1　架空の三角形の面積を求めよ。」「（1）　底辺と高さを測る。」（自動番号の段落なら ListNode）「ヒント　架空の補助線をひく。」・全角空白だけの段落・
    別行数式「S=½ah　(1)」の段落。続く本文に「式(1)より面積が分かる。」。
  - (b) 画像の段落（drawing）・図キャプション「図1　架空の三角形」・その次の段落「図1の点に名前を付けた。」に、`textbox(cx=1 cm, cy=0.6 cm, v=paragraph -2 cm)`「A 点」。
  - (c) 段落「次の囲みを読む。」の末尾に `textbox_inline(cx=10 cm)`「問2　架空の問いを二つの式で考えよ。」「答えは一つに決まる。」。
  - (d) 段落「ヒントを付けた。」（画像から 3 段落以上離す）に、`textbox(cx=10 cm, cy=0.8 cm)`「（ヒント）」。
  - (e) 段落「枠の中の問題を考える。」に、`vml_textbox(width="300pt", absolute=True)`「問3　架空の数の列の規則を説明せよ。」。
  - (f) 画像の段落の後ろの段落に `textbox` の図キャプション（fig_cap スタイル「図2　テキストボックスのキャプション」）。
  - 空のテキストボックス（`textbox(para(S["body"], ""))`）と、全角空白だけのテキストボックス。
  - 既存の N2 のテキストボックス（「注」「Area model」）はそのまま（undecided になる）。
  ALL_DOCS のまま（AI がなくても止まらない）。作り直しは `python -c "import sys; sys.path.insert(0,'tests'); import make_fixtures as m; m.make_structure('tests/fixtures/sample_structure.docx')"`、
  `git diff --stat tests/fixtures` で sample_structure.docx だけが変わることを確かめる。
- N7 の fixture `tests/fixtures/sample_outside.docx`（新規。`make_outside(path)`。AI 補完が必要なので ALL_DOCS に入れない。conftest に `OUTSIDE`、
  `__main__` の一覧にも足す）: 小さな論文（make_article）で、
  - 引用文献の 1 件目の段落に結び付いた浮動配置の図形（画像の段落 + 図キャプション「図3　架空の最後のページの図」、縦 2 cm 下）、
  - 引用文献の 2 件目の段落に結び付いた文字だけの囲み（幅 12 cm、「問4　架空の補足の問題である。」ほか 20 字以上）、
  - 注の段落に結び付いた浮動配置の表（表キャプション「表1　架空の集計」+ 表）、
  - 英文要旨の段落に結び付いた文字だけの囲み（20 字以上）、
  - 英文要旨の後ろの資料（「資料1　架空の授業プリント」）の段落に結び付いた文字だけの囲み（今のまま資料の中に出る）、
  - 引用文献の 3 件目の段落の中の行内の画像（テキストボックスの外。N1 で要対応のまま）。
  既存の `make_b3_place(outside=True)`（注に結び付いた図 s5）も、そのまま N7 の例として使う（テストは書き直す）。

### 9.2 新しいテスト

`tests/test_reader.py`:
- TextBox の記録: wp:anchor（float_id あり、幅は extent）、wp:inline（inline、幅）、VML pt（幅・高さ、absolute の有無）、VML の幅が pt 以外（`width:3in`）は None、
  グループの中（group、拡大率を掛けた幅）、入れ子の内側の段落が外側の xid を継ぐ、テキストボックスの中の表とセルの段落の textbox_id、`Document` に
  `textbox_excluded` がない。

`tests/test_floats.py`:
- `test_textbox_kind_boundaries`: 3.2 の表をすべて（`textbox_kind` の単体テスト。幅 None・グループ・15/20 字・0.4/0.6 の境界の上下）。
- `test_box_lines`（幅あり・なし）。
- N7: `test_float_anchored_outside_body_is_kept_as_before` を書き直して `test_float_anchored_outside_body_becomes_unplaced`:
  make_b3_place(outside=True) を AI なしで変換すると `AIRequiredError`（理由に「本文の外（注）」）、手動モードで回答前は s5 が unplaced・where end・
  本文の最後に図5（fn-group に図5 の文字がない）、要対応（forced）に「本文の最後」、AI が after に本文の段落を指定すれば その後ろ、注の段落を指定すれば
  不採用で本文の最後。
- sample_outside: 手動モードで回答前、図3・表1 は本文の最後（unplaced、end_why anchor）、引用文献の件数は 3（図形の段落が引用文献にならない。`plan.refs` に
  キャプションの文字がない）、`lost_images` は行内の画像 1 件だけ（図3 の画像は XML の図に入る）、文字だけの囲み 2 件は本文の最後の boxed-text（estimated、
  `textbox_place` の要確認）、資料の囲みは app の中（今の扱い）、不変性・最終・DTD 合格。
- 2 回の組み立て: sample_outside で `classify` の結果の判断（`plan.decisions` の did と message）に重複がない。同じ doc で `classify` を 2 回呼んでも同じ結果
  （段落の書き込みを戻している）。本文の外の図形のない原稿（sample_full）では 1 回だけ組み立てる（`Classifier` を差し替えて数える）。

`tests/test_structure.py`（sample_structure の (a)〜(f)）:
- (a) は `<boxed-text>` になり、アンカー段落「試験（2025）の問題を次に示す。」の前（同じ sec の中の直前の要素）。中の段落・list・disp-formula（id FD1、label「(1)」）、
  本文の「式(1)」が FD1 へのリンク、全角空白の段落は「空白のみの段落」の除外。
- (c) はアンカー段落の後ろの boxed-text。
- (b) は除外され、理由が「図に重ねた注記」を含み、10 章の警告がある。要確認の Action はない。
- (d) は AI なしでは除外され（理由「囲みか図の注記か決められない」）、`textbox_undecided` の要確認がレポートの冒頭・14 章・3 章に出る（終了コード 0、`needs_action` は偽）。
- (e) はアンカー段落の後ろの boxed-text で、`textbox_place` の要確認（3 章の「囲み・図の注記」）。
- (f) は今までどおり図のキャプション。
- 空・全角空白だけのテキストボックスは、boxed-text にも要確認にもならない（全角空白は「空白のみの段落」）。
- 本文の最上位（最初の章の前）に置いた囲みは `<p><boxed-text>` になる（in-test の docx。make_article で章見出しの前の段落に (a) の形を結び付ける）。
- 既存の `test_textbox_paragraphs_do_not_switch_regions` が通る（N2 のテキストボックスは undecided で除外のまま）。
- docs/fix_plan_repro_tests.py の `test_PROBLEM_text_only_textbox_is_dropped_from_xml` を逆にして取り込む（`test_text_only_textbox_becomes_boxed_text`）:
  同じ docx で「次の二次方程式を解きなさい」が boxed-text の中にあり、6 章の除外にない。AI の set_role p は「placements」を含む理由で不採用のまま
  （浮動配置の図形）。docs/fix_plan_repro_tests.py から取り除き、冒頭の説明に「単位 F で取り除いたもの」を書く。

`tests/test_ai.py`:
- 手動モードの回答で (d) に `kind box, after=(d) のアンカー段落` → その段落の後ろの boxed-text、`ai.accepted` に place_float として載る（`float_decisions["x…"]`）。
- (d) に `kind label` → 理由「AI による補完で図に重ねた注記と判断」の除外、要確認の Action は消える。
- after がテキストボックスの中の段落・表のセル・引用文献の段落 → 不採用（「本文の段落ではない」）、(d) は除外のまま。
- (a)（機械的に決めた囲み）への指定 → 「変更できない」で不採用。(e)（位置を推定した囲み）に kind box と別の after → 採用、label → 不採用。
- テキストボックスの指定で caption・body が空でない、items が 2 つ、kind が fig → 不採用。浮動配置の図形（s1）に kind box → 不採用。
- (e) の段落への set_role p → 「placements の kind box・label で指定」を含む理由で不採用。VML のテキストボックスの「図1　…」への set_role fig_caption → 採用され F1 の
  キャプションになる（回帰しない）。
- 依頼文: 「# 囲みか図の注記か決められなかったテキストボックス」に (d) と N2 の 2 件、「# 位置を推定した囲み」に (e)、「変更不可」に (a)(c)(b)。テキストボックスの段落の
  場所が「テキストボックス x… の中」。SYSTEM_PROMPT・FIELD_GUIDE・MANUAL_EXAMPLE に box・label。
- `test_request_hints_follow_set_role_problem` の最後（VML の囲みの段落）を、「（囲みなら placements の kind box、図の注記なら label で指定）」に書き直す。
- 点検で足したテスト（FIX_PLAN 付録）: 囲み・label・undecided・未配置の図形（手動モードで回答前）に全角空白だけの段落を入れても不変性チェックに合格、
  本文のテキストボックスに「英文要旨」スタイル・「注」だけの段落があっても sec の数・trans-abstract・fn-group が変わらない（既存）、VML の width が pt 以外で label に倒れない（単体テスト）。

`tests/test_lost_images.py`:
- `test_image_in_reference_is_reported` の `textbox-on-ref` の場合を外し、`test_figure_on_reference_becomes_unplaced`（手動モード: lost_images が空、図5 が本文の最後の図、
  要対応 forced。AI なし: AIRequiredError）にする。ほかの 2 つの場合（引用文献の段落の画像）は今のまま（N1 は続く）。
- `test_provisional_notices_for_textbox`・`test_cli_shows_provisional_notices` を書き直す: make_provisional の囲み（21 字・幅 13.9 cm・画像から遠い）は boxed-text になり、
  「要確認: テキストボックスの中の文字」は出ない（暫定の知らせの削除）。決められない形（in-test で「（ヒント）」）では `textbox_undecided` の要確認が
  レポートの冒頭・14 章・CLI の標準エラーに出て、終了コード 0。並びは要対応の後ろ。

`tests/test_pipeline.py`:
- `test_blank_paragraphs_in_textbox_and_endnote_are_excluded`: 囲み「問1　枠の中の問題文である。」（13 字・幅広・画像の近く）は undecided の除外になり、理由は
  「テキストボックス内の文字」で始まる（今の assert のまま通る）。
- ALL_DOCS の不変性・最終・DTD・jstage_issues == [] の既存テストが sample_structure で通る。

`tests/test_colab.py`: `result_boxes` に `textbox_undecided` の box_title が出る（Action を足しただけで出ることの確かめ。表示の仕組みは変えない）。

### 9.3 既存テストの書き換え（まとめ）

1. tests/test_floats.py の `test_float_anchored_outside_body_is_kept_as_before`（逆にする）。
2. tests/test_lost_images.py の `test_image_in_reference_is_reported[textbox-on-ref]`（N7 に移す）、`test_provisional_notices_for_textbox`、`test_cli_shows_provisional_notices`（暫定の知らせの削除）。
3. tests/test_ai.py の `test_request_hints_follow_set_role_problem` の VML の囲みの案内。
4. 文言・件数で確かめるテストのうち、sample_structure の段落の数・除外の数・判断の番号に頼るもの（調べた範囲ではない。テストは段落の文字で選んでいる）。
5. tests/test_floats.py の list_textbox の docstring（「XML に出さない」は今もそのとおり。変えない）。

---

## 10. 合格の条件（物差し）

- pytest: `python -m pytest -q -p no:cacheprovider` がすべて合格（3.13 と 3.10）。新しいテストが 0.24.1 の src（`scratchpad/f/base0241_src`）では失敗することを確かめる
  （`pytest_src.sh <base0241_src> <python> tests/test_…::…`）。
- ruff: `ruff check src tests tools` の件数が HEAD を超えない。
- golden（23 件。`scratchpad/f/golden_base/manifest.json` と比べる）。違ってよいもの:
  - 手動・AI のすべての `prompt`（SYSTEM_PROMPT・FIELD_GUIDE・MANUAL_EXAMPLE・manual_prompt の書式。依頼文の書式の変化）。
  - `sample_structure_manual`・`sample_structure_split` の xml・report・prompt（(a)〜(f) の追加、N2 の 2 件が undecided の除外になること、知らせ、判断の一覧）。
  - ほかの原稿の xml と report は同じ（文字だけのテキストボックスがない。試作で確かめた: sample_full・edge・template・notes・pdfcheck・reader・b3_cells・b3_tablefig・
    float に文字だけのテキストボックスはない）。pdfcheck のルート1・2 も同じ。違いはすべて本体を diff して理由を書く。
- td1〜3（`--route docx --ai manual`。0.24.1 と比べる）:
  - td1・td2: XML は 0.24.1 と同じ（文字だけのテキストボックスがない）。レポートも版の行のほかは同じ（1 章の行は増えない）。
  - td3: XML は 0.24.1 と同じ（注記は今も除外。資料の表の中の囲みは今も表のセルの中）。レポートは、注記 27 段落の除外の理由が「図に重ねた注記とみなして」になり、
    10 章に警告 2 行（d67・d167）、1 章に「テキストボックスの文字」の行（図の注記として除外 27 件、空白 1 件は数えない）、A の暫定の知らせ（要確認）がなくなる。
    要確認・要対応のほかの項目は同じ。
  - 3 本とも本文の文字はすべて 0.24.1 と同じ、不変性・最終・DTD・J-STAGE のチェックは合格、XML に入らなかった画像は増えない（0 件のまま）。
- sample_structure・sample_outside の XML が DTD に合格し、boxed-text が本文の最上位に直接出ない（`body/boxed-text` がない）。

---

## 11. 残る限界と、利用者に確かめてもらうこと

- J-STAGE の画面での `<boxed-text>` の表示（枠で囲まれるか、中の list・disp-formula が崩れないか）を、試験登載で確かめる（DEVELOPMENT の「残っている課題」に足す。
  JSTAGE_NOTES.md にマニュアルの根拠〈body の子は p と sec、boxed-text は sec と p の子、中の p は表示が崩れる恐れ〉と、確かめた結果を書く）。
- 本文に結び付いた文字だけの囲みの実例が手元の 3 本にない（td1・td2 の「囲み」は表で組んだ図）。しきい値は、td3 の注記（グループの中）と資料の囲み、
  td1・td2 の表で組んだ問題文の文字数・幅で確かめただけ。本文の囲みが 20 字未満（「問1　次の式を計算せよ。」など）だと undecided になり、要確認が増える。
  試験運用で、要確認の件数と、AI の判断が妥当かを見る。
- ルート2 で、囲みの文字は PDF に合わせて直さず、ルート1 でも PDF との違いを 13 章に出さない（0.24.1 と同じ。照合の規則を変えないため）。
- 位置を推定した囲み（浮動配置で図の左上がアンカー段落の左上にないもの、VML の位置指定、本文の外に結び付いたもの）は、アンカー段落の後ろ（本文の外なら
  本文の最後）に置き、要確認にする。AI に位置を指定させられるが、必須ではない。
- グループ図形の中の文字は、16 字以上なら undecided（AI か人が判断）。浮動配置のグループ図形（図表の入った Float）の中の注記は今の扱いのまま
  （AI の指定がなければ除外、指定があれば図の後に p）。
- 本文の外の、浮動配置でない（行内・VML の）テキストボックスで、キャプション・画像・表を含むものは、今までどおりその領域の段落（画像は N1 の要対応）。
  和文の冒頭・表のセル・脚注の中のテキストボックスも今のまま。
- 既存の不整合（F では直さない。報告）: J-STAGE のマニュアルでは `<body>` の子は `<p>` と `<sec>` だけだが、今の builder は最初の章見出しの前の図・表・
  箇条書き・別行数式・引用を `<body>` の直下に出している（DTD には合う。test_structure の `body/fig[@id='F1']` もこの形を確かめている）。J-STAGE で弾かれるかは未確認。
- 実際の AI（Claude）で box・label の回答の形を一度確かめる（FIX_PLAN の「計画全体で足した作業」）。

---

## 12. 文書の更新

- docs/DESIGN.md: 4.3 の暫定の知らせの箇条を、囲み・注記・決められないものの扱いに書き換える。5 章（placements の kind box・label、set_role の
  テキストボックスの規則、依頼文の節）。6.1 の最後の「本文にアンカーのある図形だけの扱い…F（N7）で」を N7 の扱いに書き換え、6.2「文字だけのテキストボックス
  （囲み）」を足す（判定の規則と表、置き場所の表、boxed-text の出し方、2 回の組み立て）。7 章の「図・表を含まないテキストボックス…F で直す」を 11 章の限界に置き換える。
  E で書いた「文字だけのテキストボックスの段落（float_id のないもの）の規則は、修正計画の F で足す」を消す。
- docs/JSTAGE_NOTES.md: boxed-text の置き場所（マニュアル 3.5.4 (1)）と試験登載で確かめること。
- docs/DEVELOPMENT.md: テストの節に sample_outside、sample_structure の (a)〜(f)。「残っている課題」に boxed-text の表示・本文の囲みの実例・body の直下の図表。
  コードの構成の表の floats.py（文字だけのテキストボックスの判定）・structure.py（place_boxes・2 回の組み立て）。
- docs/FIX_PLAN.md の F の節: 「実装したこと」、1 章の実測（td1・td2 の「囲み」は表で組んだ図だったこと）、決定事項 9(3) の数の注記、暫定の判断（13 章）。
- docs/fix_plan_repro_tests.py: test 2 を取り除き、冒頭の説明に F を足す。
- README.md: 出力（囲みは boxed-text）、レポートの 3 章「囲み・図の注記」、要確認の 2 つ。
- モジュールの docstring（floats・structure.place_boxes・ai_assist.set_role_problem・report.actions）。CLAUDE.md は変えない（原則は同じ）。

---

## 13. 決めたこと・暫定の判断・却下した案・食い違い

### 13.1 この設計で決めた暫定の判断（利用者に未確認。設計書と FIX_PLAN に「暫定」と書く）

1. 位置を推定した囲みは、AI なしでもアンカー段落の後ろ（本文の外なら本文の最後）に置いて要確認にする（止めない・除外しない）。
2. 決められないもの・位置を推定した囲みは、どちらも要確認（終了コード 0）。図の注記（label）は知らせない（10 章の警告と 6 章だけ）。
3. グループ図形・描画キャンバスの中の文字だけのテキストボックスは、15 字以下なら注記（label）、それより長ければ undecided（FIX_PLAN (9) の「範囲外」は、
   図表の入った浮動配置の図形〈FloatInfo〉の中のものに当てはめ、td3 のような行内のグループ図形〈Float にならない〉の中の注記は判定の対象にした）。
4. 囲みの段落は、出版版 PDF との照合で表のセルと同じく照合しない（文脈 cell）。
5. 本文の外に結び付いた図形の判定のために、構造の組み立てを 2 回行う（本文の外の図形がある原稿だけ）。
6. 囲み（boxed-text）に id を付けない。囲みの中の見出しのスタイルの段落は p にする。
7. 知らせの文言（7.2）。画面の見え方はまとめ役の暫定の判断のとおり既存の形に Action を足すだけ。

### 13.2 却下した案

- 組み立ての順を front_en → body に変える: すべての原稿の判断の番号が変わる（golden がすべて変わる）。
- `build_front_en` を空の plan で試しに実行して資料の範囲を知る: 著者（`plan.authors`）や `_en_count` を書き換える副作用があり、壊れやすい。
- `build_front_en` の状態の判定を別の関数に切り出す: E で 3 回点検した規則を大きく組み替えることになる（I の分割の時に検討）。
- 本文の外の図形の中身を、本文を組み立てた後に plan.body に差し込む: AI の after の位置の扱いが place_floats と 2 通りになる。
- 位置を推定した囲みに `estimate_top_left` を機械的に使う: 浮動配置の図表で採らなかった（ページ・段の区切りを考えない）のと同じ理由。
- 20 字未満でも「。」で終わる幅広の文字を囲みにする: 実例がなく、「（ヒント）」などの境界が増える。迷ったら AI か人に任せる。
- 囲みを ルート2 で PDF に合わせて直す: 照合の規則（pdfmatch.py）を変えることになり、B2.1 が保留中。
- 本文の最上位の図・表なども `<p>` で包む: F の範囲外（既存の不整合として報告）。

### 13.3 文書とコードの食い違い（見つけたもの）

1. FIX_PLAN 決定事項 9(3)・まとめ役の作業指示の「td1・td2 の 276〜402 文字の 2 件ずつは囲み」: 実際は、図・表キャプションと表を入れた浮動配置の図形（B3 の図表）で、
   文字だけのテキストボックスではない。td3 の 31 件は、行内のグループ図形の中の 28 件（0〜11 字）と、資料の表のセルに結び付いた 3 件（197〜210 字）。
   → FIX_PLAN の F の節に実測を書く（直す）。
2. FIX_PLAN F (9)「グループ図形の中の注記は、今の扱い（図の後に p）」: 「図の後に p」は浮動配置のグループ図形で AI が中身を指定したときだけで、行内のグループ図形
   （td3）の今の扱いは除外（TEXTBOX_TEXT_EXCLUDED）。→ 13.1 の 3 のとおりに解釈し、FIX_PLAN に書く。
3. FIX_PLAN「本文の冒頭では <p> で包む」: DTD は body の直下の boxed-text を認める。理由は J-STAGE のマニュアル（body の子は p と sec）。→ JSTAGE_NOTES に書く。
4. 今の builder は、最初の章見出しの前の fig・table-wrap・list・disp-formula・disp-quote を body の直下に出す（J-STAGE のマニュアルと違う。DTD は合格）。→ 直さない（11 章）。
5. DESIGN.md 4.3・7 章・6.1 の「F で直す」「本文にアンカーのある図形だけの扱い」、5 章と ai_assist.set_role_problem の docstring の「F で足す」、
   structure.py の TEXTBOX_TEXT_EXCLUDED の前のコメント（暫定の知らせ）、report.provisional_exclusions の docstring。→ F で直す。
6. FIX_PLAN の行番号（structure.py:570・L557・L1207〜1259、SYSTEM_PROMPT:148、pipeline.py:243、ai_assist.py:702〜706）は古い。→ F の節を書くときに名前に直す。
7. `Builder.nodes` の引数 `top` は今は使われていない（呼び出しでは渡している）。→ F で使う（boxed-text を p で包む）。
8. model.py の `Para.in_textbox` にコメントがない（`Table.in_textbox` にはある）。テキストボックスの中の表のセルの段落は in_textbox が False。→ textbox_id のコメントで説明する。
