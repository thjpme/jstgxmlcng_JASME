# 単位 u4-crop（0.30.0）: Word でトリミングした画像の切り取り

## 要点

- 目的: Word でトリミングした画像が、切り取る前のまま `Graphics/` と ZIP に入り（Word で隠した部分が J-STAGE で公開される）、知らせもない不具合を直す。
  Word のトリミングは画像ファイルを変えず、表示のときに `a:srcRect`（VML は `v:imagedata` の `crop*`）の割合で切り取るだけなので、docx の画像は常に切り取る前のもの。
- 直し方: 読み取り（`docx_reader._graphic`）で切り取りの割合と「反映しない Word の加工」（回転・反転・色の変更など）を `ImageRef.crop`・`ImageRef.edits` に記録し、
  書き出し（`images.export_images`）で Pillow で切り取る（`images.crop_image`）。出力ファイル名・拡張子・XML の `xlink:href` は変えない。
  切り取って出力した画像は要確認 `image_crop`、加工を反映していない画像は要確認 `image_edits`。切り取れない画像（EMF/WMF、Exif の向きのある写真、
  動く GIF、保存できない形式など）は ZIP に入れず、切り取る前の画像を `要変換/` に置いて「用意が必要な画像」（既存の要対応 `images`）にする。
  AI にも Word の表示どおりに切り取った画像を渡し、切り取れない画像は渡さない（AI には依頼文の文字だけ）。文字には触れないので、不変性チェック・ルート2 に影響しない。
- 一緒に直す: 1 つの `w:drawing` に `pic` が複数あるとき、`a:blip` の `a:extLst/a:ext` を拾って画像の大きさが 0 になる不具合（グループの縮尺も掛ける）。
  `images_action` の文の「画像（PNG）」と「docx に画像ファイルがない」を、切り取れなかった JPEG にも合う文に直す。
- 実際の原稿での影響: 切り取りのある画像はテストデータ3 の 3 つの docx（各 1 枚）とテストデータ5（1 枚）。今は 590×438・1636×556 のまま出力しているものが、
  Word の表示どおり 534×401・1308×556 になり、状態が ok → converted、要確認 `image_crop` が 1 件ずつ増える（終了コードは変わらない）。ほかの 30 枚（4 辺とも 0 の空の指定 21 枚を含む）は今と同じバイト列。
  回転・反転・色の効果・負の値・VML の切り取り・Exif の向きは実際の原稿に 0 件。fixture 15 件の XML と画像は変わらない。
- 順: model.py・docx_reader.py・report.py は u3-tables・u3-autonum の後に、ai_assist.py は u1 の後に直す（同じ作業の枝で単位ごとに commit。版は 0.30.0 の最後に 1 回）。
- 担当: 作るのは Sonnet（エフォート medium）。点検は Opus（エフォート medium）。Opus が自分で書く部分はない（文はこの設計書のものをそのまま使う）。
  点検で Opus が見るのは、`image_crop`・`image_edits`・`images_action` の文（top・checklist・box_detail・cli の書き分けと目印 `step()`）、
  切り取れないときに failed へ進む経路（`crop_image` の例外の扱い、`要変換/` の置き方、ZIP に入らないこと）、AI に切り取れない画像を渡さないこと。

## 再現（確かめたこと）

再現と試作のスクリプトは `docs/fix_plan_2026-11/protos/u4-crop/` と `docs/fix_plan_2026-11/protos/review-u4-crop/` にある。
どれも計画のときの作業フォルダ（scratchpad）のパスを前提に書かれていて、そのままでは動かない。手本として読むものである。
出力のフォルダ・生成した docx・切り取った画像（試作の `proto/`）は写していない。

| 項目 | 結果 | スクリプト | 見たこと |
|---|---|---|---|
| DrawingML の `a:srcRect`（l=50000。右半分だけ表示）の PNG | 再現 | `u4-crop/repro.py`（drawing-png） | ZIP の `Graphics/31_1_01.png` は 200×100（切り取る前）、左上の画素は赤（期待は 100×100・青）。status=ok、actions は空、`needs_action` は偽。`ImageRef` に切り取りを持つ欄がない |
| 同じ `a:srcRect` の JPEG | 再現 | `u4-crop/repro.py`（drawing-jpg） | `31_1_01.jpg` が 200×100 のまま（元のバイト列）。知らせなし |
| VML の `v:imagedata cropleft="32768f"`（50%） | 再現 | `u4-crop/repro.py`（vml-png） | 200×100 のまま。VML の `crop*` も読んでいない |
| 実際の原稿の切り取り・加工の数 | 確かめた | `u4-crop/scan_private.py`・`private_convert.py`・`proto_crop.py` | tests/private の docx 10 件（テストデータ1〜5 とテンプレート）の `pic:pic` は 34 枚。非 0 の `a:srcRect` はテストデータ3 の 3 件（各 1 枚、img4、`wp:anchor`、PNG RGB 590×438、上下左右とも約 4〜5%）とテストデータ5 の 1 件（img1、PNG RGBA 1636×556、左 約 20%）。ほかの 21 枚の `a:srcRect` は 4 辺とも 0（Word が付ける空の指定）。負の値・`a:fillRect` の指定・`a:tile`・回転・反転・`a:blip` の色の効果・`a14:imgProps`・VML の切り取りと回転は 0 件（`a:blip` の `a:extLst` はすべて useLocalDpi）。Exif の向きのある画像は 0 件。`v:imagedata` はテストデータ4 に 1 件（`mc:Fallback` の側で読まれない。切り取りなし）。試作で切り取ると 534×401・1308×556 になり、mode（RGB・RGBA）と dpi が残った |
| EMF/WMF の変換後の画像に `srcRect` を当てはめられるか | 当てはめられない | `u4-crop/` の EMF の試し（テンプレートの EMF。切り取りはない） | LibreOffice は EMF を A4 の紙面に置く（PDF は 595×842 pt、`--convert-to png` も 794×1123 px。EMF の rclFrame は約 79×70 pt）。紙面の中の位置が分からず、`_crop_white` の前でも後でも正しく当てはめられない |
| 1 つの `w:drawing` に `pic` が複数あるときの大きさ | 再現（別の問題） | `u4-crop/multi_pic_ext.py` | グループ図形に `pic` を 2 つ入れ、`a:blip` に Word が付ける `a:extLst`（useLocalDpi）を付けると、img1・img2 とも `cx_emu=cy_emu=0`（期待は 1000000×800000 と 500000×400000）。`pic.find('.//a:ext')` が `a:blip/a:extLst/a:ext` を先に拾う。AI の依頼文が「グループ図形の画像。0.0cm×0.0cm」になる |
| Pillow の保存で形式ごとの情報が残るか | 確かめた | `u4-crop/pillow_modes.py`・`review-u4-crop/exp1.py` | `quality="keep"` は切り取った画像では ValueError（Pillow 12.3・13.0）。`qtables=im.quantization` と `subsampling=JpegImagePlugin.get_sampling(im)` で元と同じ量子化表になる。P の透過（int・bytes）は切り取りの後も残る。PNG の dpi は `save(..., dpi=...)` で渡さないと落ちる。Pillow が作った CMYK の JPEG（adobe）は往復しても値が変わらない |
| JPEG の Exif の縮小画像 | 問題あり（点検） | `review-u4-crop/exp3.py`（`exp2.py` は piexif を使う試しで、使わなかった） | 生の `im.info["exif"]` を渡して保存すると、IFD1 の縮小画像（切り取る前の全体）が出力に残る。`exif=im.getexif()` を渡すか、渡さなければ残らない |
| Pillow 13 の保存 | 問題あり（点検） | （Pillow 13.0.0 の venv で試した） | mode I の PNG は `OSError: cannot write mode I as PNG`（12.3 は非推奨の警告だけ）。I;16 は書ける。PA はどの版でも PNG に書けない。pyproject は `Pillow>=9` なので新しい環境には 13 が入る |
| 既存の fixture | 確かめた | （点検で正規表現で調べた） | tests/fixtures/*.docx の `word/*.xml` に切り取り・回転・効果はなく、テンプレートの空の `<a:srcRect/>` 1 件だけ（4 辺とも 0 なので `crop` は None） |

原因: `docx_reader._graphic`（docx_reader.py 595 行目〜。DrawingML の `pics` のループは 623〜630 行目、VML のループは 656〜661 行目）が
`a:srcRect`・`v:imagedata` の `crop*`（と回転・反転・色の効果）を読まず、`model.ImageRef`（model.py 91〜113 行目）にも持つ欄がない。
`images.export_images`（images.py 140〜198 行目。DIRECT は 162〜166 行目）は拡張子が png/jpg/gif なら `doc.media` のバイト列をそのまま書くので、
Word で隠した部分も `Graphics/` に入り、`package.upload_entries` がそのまま ZIP に入れる。手動モードの `AI添付画像/`（pipeline.py 370〜373 行目）と
API に渡す画像（`ai_assist.image_blocks`、ai_assist.py 502〜519 行目）も切り取る前のもの。

## 直し方

文字は 1 文字も変えない（画像の属性だけ。`ooxml.canonical_text`・`pdfdocx`・`fidelity` は直さない）。出力の形式・拡張子（`builder.name_image`、builder.py 96〜108 行目）・
`package.ZIP_STATUSES`・`pipeline.add_images`・colab・app・cli・make_notebook は変えない（知らせは `Action` を足すだけで出る）。

### 1. model.py（ImageRef）

`ImageRef` の末尾（`hidden_style` の後ろ）に、既定値つきで 2 つ足す（位置引数で作っている既存の呼び出しはそのまま動く）。

```python
    crop: tuple | None = None   # Word のトリミング（左・上・右・下）。元の画像の幅・高さに対する割合（0 以上）。4 つとも 0 なら None
    edits: tuple = ()           # 書き出しで反映しない Word の加工の名前（IMAGE_EDITS の順・重複なし）。9 章と要確認 image_edits
```

モジュールに、加工の名前と並びの順を定数で置く（読み取りはこの順に並べ直す。テストはこの順を前提にする）。

```python
# Word の画像の加工のうち、書き出しで反映しないもの（ImageRef.edits の名前と順）
IMAGE_EDITS = ("切り取り（読めない指定）", "余白", "並べて表示", "塗りつぶしの範囲", "回転", "左右反転", "上下反転",
               "色の変更", "透明度", "図の効果", "アート効果")
```

### 2. docx_reader.py

#### 2-1. モジュールの関数（`_in_textbox`〈790 行目〉の近くに足す）

- `_pct(v) -> float | None`: OOXML の ST_Percentage。`"50000"` → 0.5（1/1000 %）、Strict の `"50%"` → 0.5、None・空 → 0.0、読めない → None。
- `_vml_frac(v) -> float | None`: VML の割合。`"16384f"` → 0.25（f は 1/65536）、`"25%"` → 0.25、`"0.25"` → 0.25、None・空 → 0.0、読めない → None。
- `_crop_tuple(vals) -> tuple[tuple | None, list]`: 4 つの割合（左・上・右・下）から `(crop, edits)`。
  - None（読めない値）は 0 とみなし、edits に「切り取り（読めない指定）」を足す（隠した部分が知らせなしで ZIP に入らないように）。
  - 負の値（外側に余白を足す指定）は 0 にする。-0.001（ST_Percentage で -100）より小さいときだけ edits に「余白」を足す（ごく小さな負の値で要確認を出さない）。
  - 4 つとも 0 なら crop は None。
- `_xfrm_edits(xfrm, edits)`: `a:xfrm` の `rot` が 0 以外なら「回転」、`flipH` が `"1"`/`"true"` なら「左右反転」、`flipV` なら「上下反転」を edits に足す（xfrm が None なら何もしない）。
- `_pic_edits(pic, container) -> tuple[tuple | None, tuple]`（DrawingML）:
  - `sr = pic.find(f"{{{PIC_NS}}}blipFill/{{{A_NS}}}srcRect")` の `l`・`t`・`r`・`b` を `_pct` で読み、`_crop_tuple`（sr がなければ crop は None）。
  - `pic:blipFill/a:tile` があれば「並べて表示」。`pic:blipFill/a:stretch/a:fillRect` の `l`・`t`・`r`・`b` のどれかが 0 以外なら「塗りつぶしの範囲」（切り取りは srcRect だけを当てる）。
  - `_xfrm_edits(pic.find(f"{{{PIC_NS}}}spPr/{{{A_NS}}}xfrm"), edits)`。
  - グループ全体の回転・反転: `pic.iterancestors()` を `container`（`w:drawing`）に着くまでたどり、各祖先の子のうち局所名が `grpSpPr` のもの（`wpg:grpSpPr`・`a:grpSpPr`）の子 `a:xfrm` に `_xfrm_edits` を当てる（`grpSpPr` は `pic` の祖先ではなく、祖先の子であることに注意）。
  - `a:blip` の子孫の局所名: `grayscl`・`duotone`・`biLevel`・`clrChange`・`clrRepl`・`hsl`・`tint`・`lum` → 「色の変更」、
    `alphaBiLevel`・`alphaCeiling`・`alphaFloor`・`alphaInv`・`alphaMod`・`alphaModFix`・`alphaRepl` → 「透明度」、`blur`・`fillOverlay` → 「図の効果」、
    `a:extLst/a:ext` の下の局所名 `imgProps`（`a14:imgProps`。アート効果・修整・背景の削除）→ 「アート効果」。
  - 戻り値の edits は `IMAGE_EDITS` の順に並べ、重複を除いた tuple。
- `_vml_edits(imagedata) -> tuple[tuple | None, tuple]`（VML）:
  - `cropleft`・`croptop`・`cropright`・`cropbottom` を `_vml_frac` で読み `_crop_tuple`。
  - `gain`・`blacklevel`・`gamma`・`chromakey` のどれかが空でない、または `grayscale`・`bilevel` が `"t"`/`"true"` なら「色の変更」。
  - 親の要素（`imagedata.getparent()`。`v:shape`・`v:rect`・`v:image` など）の `style` を空白を除いて小文字にし、`rotation:` の値が 0 以外なら「回転」、`flip:` の値に `x` があれば「左右反転」、`y` があれば「上下反転」。
  - 戻り値の edits は `IMAGE_EDITS` の順・重複なし。

#### 2-2. `_graphic` の変更

- DrawingML の `pics` のループ（623〜630 行目）:
  - 大きさ: `ext = pic.find(f".//{{{A_NS}}}ext")`（626 行目）を `ext = pic.find(f"{{{PIC_NS}}}spPr/{{{A_NS}}}xfrm/{{{A_NS}}}ext")` に変える。
    `len(pics) > 1` で ext があるときは、`_new_textbox` のグループの分（564〜576 行目）と同じ縮尺を掛ける:
    `groups = [a for a in pic.iterancestors() if a.tag in (f"{{{WPG_NS}}}wgp", f"{{{WPC_NS}}}wpc")]`、
    `ch = groups[-1].find(f"{{{WPG_NS}}}grpSpPr/{{{A_NS}}}xfrm/{{{A_NS}}}chExt") if groups else None`、
    ch と holder の `wp:extent` があれば `sx = _ratio(extent.cx, ch.cx)`・`sy = _ratio(extent.cy, ch.cy)`（なければ 1）、
    `pcx, pcy = round(int(ext.cx) * sx), round(int(ext.cy) * sy)`。ext がないときと `len(pics) == 1` のときは今のとおり holder の大きさ。
  - `crop, edits = _pic_edits(pic, el)` を `self._new_image(..., crop=crop, edits=edits, **hid)` に渡す。グループ図形・描画キャンバスの中の pic、1 つの drawing の複数の pic も、
    pic ごとに自分の `blipFill` を読む（グループ全体の回転・反転だけ祖先を見る）。
  - `pics` がないとき（`shape_only`）は変えない。
- VML のループ（656〜661 行目）: `crop, edits = _vml_edits(d)` を `_new_image` に渡す（`source` が `"ole"` でも同じ。OLE のプレビュー画像の切り取り）。
- 隠し文字の画像（hidden）にも記録してよい（出力しないので影響なし）。

### 3. images.py

#### 3-1. 足すもの

```python
class CropError(Exception):
    """Word で切り取った（トリミングした）画像を切り取れない理由（利用者向けの日本語の文。「…ため」の前に入る形）。"""


def crop_text(crop) -> str:
    """切り取りの割合の表示（0 でない辺だけ。順は左・上・右・下）: 「左 50.0%・右 10.0%」。レポートと知らせで共用。"""


def crop_box(size, crop) -> tuple:
    """(x0, y0, x1, y1) = (round(w*l), round(h*t), w - round(w*r), h - round(h*b))。幅か高さが 1 px 未満なら
    CropError("切り取ると画像が残らない")。"""


def _check_croppable(im) -> None:
    """切り取れない画像なら CropError。"""
    # getattr(im, "n_frames", 1) > 1 → CropError("複数のコマのある画像（動く GIF など）の")
    # im.getexif().get(0x0112, 1) not in (0, 1) → CropError("画像に向きの情報（Exif）があり、Word が表示する向きでの切り取りの位置を決められない")
    #   （向き 0 は規格外で、表示ソフトは 1 と同じに扱うので切り取る）


def crop_image(data: bytes, fmt: str, crop) -> tuple:
    """Word のトリミング crop に合わせて切り取った画像。fmt は "PNG" / "JPEG" / "GIF"（出力ファイル名の拡張子から決める）。
    戻り値: (切り取った画像のバイト列, (元の幅, 高さ), (切り取った後の幅, 高さ))。切り取りが 1 px 未満で
    crop_box が画像の全体になるときは (None, 元の大きさ, 元の大きさ)（呼び出し側は元のバイト列をそのまま使う）。
    切り取れなければ CropError（開く・切り取る・保存するのどこで失敗しても CropError にする）。"""
```

`crop_text` の各辺は `f"{v * 100:.1f}%"` で作り、`"・".join(...)` は f 文字列の式の外で変数にする（Python 3.10。`tests/test_syntax.py`）。

`crop_image` の中の順:

1. 全体を `try:` で囲む。`except CropError: raise`、`except Exception as e: raise CropError(f"画像を切り取って保存できない（{e}）") from e`。
2. `im = Image.open(io.BytesIO(data)); im.load()`（読めなければ上の except で CropError。文は「画像を読めない（…）」にするため、開くところだけ別に `try` して `CropError(f"画像を読めない（{e}）")` にする）。
3. `box = crop_box(im.size, crop)`。`box == (0, 0, w, h)` なら `(None, im.size, im.size)` を返す（Exif・コマ数は見ない。切り取らないので止める理由がない）。
4. `_check_croppable(im)` → `out = im.crop(box)`。
5. 保存の引数: `dpi = im.info.get("dpi")`、`icc = im.info.get("icc_profile")` があれば渡す（PNG の dpi は引数で渡さないと落ちる）。
   - JPEG: `out.mode` が RGB・L・CMYK 以外なら RGB にする。`im.format == "JPEG"` のときだけ `qtables=im.quantization` と、
     `JpegImagePlugin.get_sampling(im)` が -1 でなければ `subsampling=` を渡す（元と同じ量子化で再圧縮。`quality="keep"` は切り取った画像では ValueError になるので使わない）。
     `im.info` に `progressive`（または `progression`）があれば `progressive=True`。**Exif は渡さない**（生の `im.info["exif"]` は IFD1 の縮小画像〈切り取る前の全体〉を含む）。
     PNG にはしない（拡張子と href が変わり、写真が大きくなる）。
   - PNG: 残す mode は `1`・`L`・`LA`・`I;16`・`P`・`RGB`・`RGBA`（`I` は Pillow 13 で PNG に書けないので外す）。それ以外は、mode に `A` がある（PA など）か `out.info` に `transparency` があれば RGBA、なければ RGB に変換する。
     P の透過（`info["transparency"]`）は crop で残る。
   - GIF: そのまま `save(buf, "GIF")`（透過は残る）。
6. `(buf.getvalue(), im.size, out.size)` を返す。

#### 3-2. ImageResult（images.py 21〜27 行目）

末尾に既定値つきで足す（tests/test_pipeline.py 127・130・548 行目の位置引数の呼び出しはそのまま動く）。

```python
    crop: tuple | None = None   # Word のトリミングに合わせて切り取って出力したときの割合（ImageRef.crop）。切り取らなければ None
    edits: tuple = ()           # 書き出しで反映しなかった Word の加工（ImageRef.edits の写し）
```

#### 3-3. export_images の変更（`img`〈ImageRef〉ごと）

共通: `edits = img.edits`。edits があれば `edit_note = "Word の加工（" + "・".join(edits) + "）は反映していない"` を作り、
message の末尾に足し（message が空でなければ「。」でつなぐ）、`ImageResult.edits` に入れる。`shape_only`・`missing` の分岐は変えない。
`FMT = {"png": "PNG", "jpg": "JPEG", "gif": "GIF"}`（出力ファイル名の拡張子 → Pillow の形式）をモジュールに置く。

- DIRECT（162〜166 行目）:
  - `img.crop` が None なら今のまま（元のバイト列・status ok）。
  - あれば `out, (w0, h0), (w1, h1) = crop_image(data, FMT[want_ext], img.crop)`。
    - `out` が None（1 px 未満）: 元のバイト列のまま status ok・`crop=None`（image_crop に出さない）。
    - そうでなければ `out` を書き、`ImageResult(..., "converted", f"Word のトリミングに合わせて切り取った（{ct}。{w0}×{h0} px → {w1}×{h1} px）", crop=img.crop, edits=edits)`（`ct = crop_text(img.crop)`）。
    - CropError なら 3-4。
- PILLOW（167〜177 行目。bmp・tif など → PNG）: 開いた後、`img.crop` があれば `box = crop_box(im.size, img.crop)` を計算し、全体でなければ `_check_croppable(im)` → `im = im.crop(box)`。
  message は切り取ったとき「{SRC} を PNG に変換し、Word のトリミングに合わせて切り取った（{ct}。{w0}×{h0} px → {w1}×{h1} px）」、ImageResult の crop に割合を入れる。
  CropError なら 3-4（切り取る前の画像を PNG にしたものを置く。PNG にできなければ元のバイト列を `{名前の幹}.{src_ext}` で置く）。それ以外の例外は今のとおり「変換に失敗: …」の failed。
- METAFILE（178〜196 行目）: `img.crop` があるときは、変換に成功しても切り取らず、`Graphics/` に書かない。
  - 変換できた PNG を `keep_dir / name` に置き、status `failed`、message
    「Word で切り取った（トリミングした）EMF/WMF の図で、切り取りの位置（{ct}）を変換した画像に当てはめられないため、切り取る前の画像を 要変換/{name} に保存した。Word の表示の範囲に切り取った画像を用意すること」。
  - 変換できなかったときは、今の failed の message の後ろに「（Word で切り取った図。切り取りの位置: {ct}）」を足す。

#### 3-4. 切り取れないとき（CropError）

隠した部分を ZIP に入れないため `failed` にする（`ZIP_STATUSES` に入らない → ZIP に入らず、`report.images_to_prepare` に出て要対応 `images` になり、
`pipeline.add_images` で利用者の画像を受け付ける）。`Graphics/` には書かない。切り取る前の画像を `keep_dir / name`（DIRECT は元のバイト列、PILLOW は PNG にしたもの）に置き、message は

「Word で切り取った（トリミングした）画像だが、{理由}ため切り取れなかった。切り取る前の画像を 要変換/{name} に保存した。Word の表示の範囲に切り取った画像を用意すること」

（理由は CropError の文。「要変換/」は記事フォルダの外なので ZIP に入らない。既存の EMF と同じ）。文に手順番号・欄の名前を書かない（この文は `images_action` の box_detail の行に入る）。

#### 3-5. 変えないもの

`user_image`（利用者が入れた画像）は切り取らない。`add_images` が status `"user"` の ImageResult に置き換えるので、crop・edits は既定値に戻り、下の知らせから外れる。

モジュールの docstring の「docx の画像はそのまま使えるものが多いが」の後ろに「（Word でトリミングした画像は、表示される範囲に切り取る。`crop_image`）」を足し、
`export_images` の docstring に、切り取れない画像は `keep_dir` に切り取る前の画像を置いて failed にすることを書く。

### 4. ai_assist.image_blocks（502〜519 行目）

```python
def image_blocks(doc, images):
    """AI に見せる画像（png / jpg / gif のみ。EMF などは変換できれば変換する）。

    Word でトリミングした画像（ImageRef.crop）は、Word の表示どおりに切り取ったものを渡す。切り取れない画像（EMF/WMF の
    トリミング、Exif の向きのある画像など。images.CropError）は渡さない（Word で見せていない部分を外に出さない。AI には
    依頼文の文字だけ）。"""
```

- `mt is None and ext in ("emf", "wmf")` のとき、`img.crop` があれば変換せずに飛ばす（`continue`）。
- png/jpg/gif で `img.crop` があれば、`from .images import CropError, crop_image`（既存の `convert_metafile` と同じく関数の中で import）して
  `out, _, _ = crop_image(data, {"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "gif": "GIF"}[ext], img.crop)`。CropError なら飛ばす。`out` が None でなければ `data = out`。
- 手動モードの `AI添付画像/`（pipeline.py 370〜373 行目）はファイル名が image_id と mt で決まるので変わらない。依頼文（`build_request`）は変えない。
- この関数は `export_images` より前に呼ばれる（pipeline.py 355 行目）ので、切り取りは書き出しと別に行う（同じ画像を 2 回切り取るが、結果は同じ）。

### 5. report.py

#### 5-1. キャプションの共用

`images_to_prepare`（146〜165 行目）の中のキャプションの表を `_image_captions(r) -> dict`（image_id → 図のキャプション）に切り出し、
`images_to_prepare` と下の 2 つの Action で使う（`images_to_prepare` の結果は変えない）。

#### 5-2. `_image_crop_action(r)`（TO_CHECK、key `"image_crop"`）

対象は `[i for i in r.images if i.crop and i.status == "converted"]`。なければ None。`zname = r.zip_path.name if r.zip_path else "アップロード用の ZIP"`、`gdir = graphics_dir(r)`。
各行の文字は、キャプション `cap = caps.get(i.image_id, "")`、`ct = crop_text(i.crop)` を先に変数にする。文は「利用者向けの文」の節のとおり。

#### 5-3. `_image_edits_action(r)`（TO_CHECK、key `"image_edits"`）

対象は `[i for i in r.images if i.edits and i.status in ("ok", "converted")]`（「余白」「塗りつぶしの範囲」だけでも出す）。なければ None。
行は `{name}（{image_id}）: {"・".join(edits)}` で、edits に「アート効果」があれば、その行の末尾に「（docx の画像は効果を付けた後のものの場合がある）」を添える。

#### 5-4. `images_action`（1056〜1079 行目）の文

- top の「次の名前の画像（PNG）を作り」を「次の名前の画像（名前の拡張子の形式。.png は PNG、.jpg は JPEG）を作り」に直す。
- box_detail の最初の文「Word の図形で描かれた図などは、docx に画像ファイルがないので、変換で画像を作れません。」を
  「Word の図形で描かれた図や、変換・切り取りができなかった画像は、そのままでは Graphics/ に入れられません。」に直す。
- box_title・top の太字の部分・checklist の書き出し・cli は変えない（tests/test_pipeline.py 122・125 行目、test_colab.py 92 行目、test_notebook.py 171 行目が見ている）。

#### 5-5. actions() の並び（1649〜1658 行目）

単位どうしの点検で決めた並びにする。u3-autonum が `lost_action` の後ろに `lost_autonum_action` を入れた後なので、その後ろに足す
（0.31.0 で u5 が `_abstract_missing_action` を `lost_autonum_action` と `_image_crop_action` の間に入れる）。

```
..., images_action, lost_action, lost_autonum_action, _image_crop_action, _image_edits_action, _style_hidden_action, ...
```

テストは、`image_crop` が `lost` のすぐ後ろにあることを前提にしない（key が含まれることと、`image_edits` より前にあることだけを見る）。

#### 5-6. 9 章・1 章

9 章（1951〜1962 行目）の表の列は変えない（備考の欄に `export_images` の message が出る）。1 章の画像の要約も変えない。
新しい目印（`STEP_NAMES`）は足さず、box_detail だけ `step("docx")` を使う。top・checklist・cli には目印を書かない。`app.REPASTE_KEYS` には足さない。

## テスト

新しいテストの docx はすべて `tmp_path` に作る。既存の `tests/fixtures/*.docx` は作り直さない（`make_fixtures.drawing` などの既定の出力は今と同じにする）。
Pillow はテスト環境にある（12.3.0）。`JpegImagePlugin.get_sampling`・`Image.quantization` は Pillow 9 にもある。

### tests/make_fixtures.py の部品（既定値のとき今と同じ XML）

- `drawing(rid, cx, cy, pid, name="図", anchor=False, src_rect=None, xfrm="", blip="")`: `src_rect` は `'l="50000"'` のような属性の文字列で、
  `<a:srcRect {src_rect}/>` を `<a:stretch>` の前に入れる。`xfrm` は `a:xfrm` の属性（`' rot="5400000" flipH="1"'`）、`blip` は `a:blip` の中身
  （`'<a:grayscl/>'` や `a:extLst`）。`blip == ""` のときは今と同じく `<a:blip r:embed="…"/>`（自己終了）。
- `vml_image(rid, width="100pt", height="100pt", attrs="", style="")`: `<w:r><w:pict><v:shape style="width:…;height:…{;style}"><v:imagedata r:id="…" {attrs}/></v:shape></w:pict></w:r>`。
- `pic_group(rids_exts, pid, extent=(cx, cy), ch_ext=None, blip_ext=False, grp_xfrm="")`: 1 つのグループ図形（`wpg:wgp`）に pic を複数入れる。
  `rids_exts` は `[(rid, cx, cy), …]`、`ch_ext` があれば `wpg:grpSpPr/a:xfrm` に `<a:ext …/><a:chExt cx=… cy=…/>` を入れ、`blip_ext` なら `a:blip` に useLocalDpi の `a:extLst` を入れる。`grp_xfrm` は `a:xfrm` の属性（`' flipH="1"'`）。
- `two_tone(fmt="PNG", size=(200, 100), **save_kw) -> bytes`: 左半分が赤・右半分が青の画像。

### tests/test_images.py（新規）

| テスト | 入力 | 確かめること |
|---|---|---|
| `test_crop_box_rounds_and_rejects_empty` | — | `crop_box((200,100),(0.5,0,0,0)) == (100,0,200,100)`、`crop_box((590,438),(0.04329,0.03646,0.05032,0.04839))` の幅・高さが 534×401、`(0.6,0,0.5,0)` は CropError |
| `test_crop_text` | — | `(0.5,0,0.1,0)` → 「左 50.0%・右 10.0%」 |
| `test_crop_image_png_keeps_transparency_and_dpi` | P モード（透過 0）・dpi 300 の 40×20 PNG を `(0.25,0,0,0)` | 30×20、mode P、`info["transparency"] == 0`、dpi ≈ 300。RGBA も mode が残る |
| `test_crop_image_png_16bit_and_alpha_modes` | I;16・LA・PA の PNG | I;16 は I;16 のまま（Pillow 13 でも通る）、LA は LA のまま、PA は RGBA になり透過が残る |
| `test_crop_image_jpeg_reuses_quantization` | quality=70・200×100 の `two_tone("JPEG")` を `(0.5,0,0,0)` | format JPEG、100×100、(0,0) が青（各成分の差 10 以内）、`quantization` が元と同じ |
| `test_crop_image_drops_exif_thumbnail` | IFD1（0x0201・0x0202）に縮小画像のある Exif（向き 1）の JPEG（`review-u4-crop/exp3.py` の組み方）を `(0.5,0,0,0)` | 出力のバイト列に縮小画像のバイト列が含まれない |
| `test_crop_image_rejects_exif_orientation_and_frames` | Exif 0x0112=6 の JPEG、2 コマ（違う色）の GIF | CropError |
| `test_exif_orientation_zero_is_cropped` | Exif 0x0112=0 の JPEG + `src_rect` で変換 | status converted |
| `test_convert_crops_word_trimmed_png` | `make_article` に `two_tone()` + `src_rect='l="50000"'` の段落と図のキャプション | ZIP の `Graphics/31_1_01.png` が 100×100 で (0,0) が青、`res.images[0].status == "converted"`、`crop == (0.5,0,0,0)`、XML の graphic の `xlink:href == "31_1_01.png"`、actions の key に `image_crop`、`needs_action` は偽、9 章に「切り取った」 |
| `test_convert_crops_jpeg_keeps_jpg_name` | media 名 `.jpeg` の `two_tone("JPEG")` + `src_rect` | 名前 `31_1_01.jpg`、`Image.open` が JPEG・100×100 |
| `test_convert_uncroppable_goes_to_prepare` | Exif 向き 6 の JPEG + `src_rect` | status failed、`zip_image_names` に入らず ZIP に `Graphics/31_1_01.jpg` がない、記事フォルダの `Graphics/` にもない、`out_dir/要変換/31_1_01.jpg` がある（200×100）、`images_to_prepare` に名前があり理由に「切り取れなかった」、要対応 `images` で `needs_action` が真。`add_images(res, {"31_1_01.jpg": 用意した PNG のバイト列})` が通って status user、その後の actions に `image_crop` がない |
| `test_crop_save_error_becomes_failed` | PNG + `src_rect`、`monkeypatch` で `PIL.Image.Image.save` に OSError を投げさせる | `export_images` が落ちず status failed、`要変換/` に元の画像がある |
| `test_subpixel_crop_is_noop` | 100×100 の PNG に `src_rect='l="100"'`（0.1%） | status ok・元のバイト列のまま・`crop` None・`image_crop` なし |
| `test_convert_metafile_with_crop_is_not_cropped` | EMF のバイト列（中身はダミーでよい）+ `src_rect`、`convert_metafiles=False` | failed、message に「切り取った図」。変換に成功する場合は `pytest.mark.skipif(soffice_path() is None)` で別に: `Graphics/` に書かず、`要変換/31_1_01.png` があり、message に「当てはめられない」 |
| `test_convert_rotated_image_is_reported` | `xfrm=' rot="5400000"'`（切り取りなし） | status ok・元のバイト列のまま、`edits == ("回転",)`、要確認 `image_edits`、box_detail の目印が `STEP_NAMES` のものだけ |
| `test_image_crop_comes_before_image_edits` | 切り取りと回転のある画像 1 つ | actions の key に `image_crop` と `image_edits` があり、`image_crop` が前（`lost` の隣であることは見ない） |
| `test_ai_images_are_cropped` | キャプションのない画像の段落（AI に渡る）+ `src_rect`、`ai_mode="manual"` | `out_dir/AI添付画像/img1.png` が 100×100 |
| `test_ai_skips_uncroppable_image` | キャプションのない画像の段落に Exif 向き 6 の JPEG + `src_rect`、`ai_mode="manual"` | `AI添付画像/` に img1 がない（`image_blocks` の戻り値にも入らない） |

### tests/test_reader.py

u3-tables のテストと名前が重ならないよう、どれも `test_reader_` か `test_group_` で始める。

| テスト | 入力 | 確かめること |
|---|---|---|
| `test_reader_reads_src_rect` | `src_rect='l="50000" r="10000"'`、`'l="50%"'`（Strict）、`l=t=r=b="0"`、`'t="-5000" l="20000"'` | `crop == (0.5,0,0.1,0)`・`edits == ()`／0.5／`crop` None／`crop == (0.2,0,0,0)` で「余白」が edits にある |
| `test_reader_unreadable_src_rect` | `src_rect='l="abc"'` | edits に「切り取り（読めない指定）」 |
| `test_tiny_negative_src_rect_not_padding` | `src_rect='t="-50"'` | edits に「余白」がない、`crop` None |
| `test_reader_reads_vml_crop` | `vml_image(attrs='cropleft="16384f" cropright="0.1"')`、`style='rotation:90;flip:x'` | `crop == (0.25,0,0.1,0)`、edits に「回転」「左右反転」 |
| `test_reader_records_rotation_flip_effects` | `xfrm=' rot="5400000" flipV="1"'`、`blip='<a:grayscl/><a:alphaModFix amt="50000"/>'` | `edits == ("回転", "上下反転", "色の変更", "透明度")`、`crop` None。`pic_group(..., grp_xfrm=' flipH="1"')` の中の pic の edits に「左右反転」 |
| `test_reader_records_art_effects` | `blip` に `<a:extLst><a:ext uri="{BEBA8EAE-BF5A-486C-A8C5-ECC9F3942E4B}"><a14:imgProps/></a:ext></a:extLst>`（a14 の名前空間を宣言する） | edits に「アート効果」 |
| `test_group_pic_size_ignores_blip_extlst` | `pic_group([(r1,1000000,800000),(r2,500000,400000)], blip_ext=True)`（`u4-crop/multi_pic_ext.py` の形） | `cx_emu` が 1000000 と 500000 |
| `test_group_pic_size_scaled_by_chext` | `pic_group([(r1,1000000,…),(r2,500000,…)], extent=(1000000,…), ch_ext=(2000000,…))` | `cx_emu` が 500000 と 250000 |

### tests/test_pipeline.py

- `test_uncroppable_jpeg_images_action_text`: 切り取れない JPEG（Exif 向き 6 + `src_rect`）の変換で、`images_action` の top に「.jpg は JPEG」があり、「画像（PNG）を作り」がない。box_detail が「変換・切り取りができなかった画像は」で始まる。

## 回帰の確かめ（基準との比較で想定する違い）

0.29.0 のコードで取った基準（u1 の (1a) の直後。fixture 15 件・tests/private 10 件のルート1、PDF のある 6 件のルート2。AI は manual・回答なし、`convert_metafiles=False`）と、
u3-autonum を入れた 1 つ前の commit とを比べる。

- ZIP の一覧と画像のハッシュ: テストデータ3 の 3 つの docx の img4 と、テストデータ5 の img1 だけが変わる（大きさが 534×401・1308×556 になり、mode RGB・RGBA と dpi が残る）。
  ルート2 の回も同じ。ほかの画像（4 辺とも 0 の空の指定 21 枚を含む）は元のバイト列のまま（ハッシュが同じ）。ZIP に入る名前の一覧は変わらない。
- actions の key と level: テストデータ3 の 3 件とテストデータ5 に要確認 `image_crop` が 1 件増える。`image_edits` はどれでも鳴らない。終了コードは変わらない。
- XML: 変わらない（`xlink:href` も同じ）。`pic` が複数の drawing の大きさの直しは、テストデータ2 の該当がテキストボックスの中の表の画像でこの経路を通らず、テストデータ4 のグループの中の pic は 1 枚なので、変わらない見込み。
  fixture の `mf.group` も pic 1 枚・`a:extLst` なしで変わらない。
- レポート: 9 章の状態（「そのまま出力」→「変換して出力」）と備考（テストデータ3・5）。要対応 `images` が鳴る原稿（テンプレートなど、EMF を変換しない設定の回）は、`images_action` の top と box_detail の文が 5-4 のとおり変わる。
- 除外の理由ごとの件数・warnings の件数・不変性チェック・DTD・補完の確かめ: 変わらない。
- 既存のテスト: 並びを確かめるテスト（test_floats 731 行・test_pipeline 867 行・test_links 180 行・test_ai 1396 行・test_notebook 271 行）が落ちないことで、
  fixture で `image_crop`・`image_edits` が鳴らないことも確かめる。tests/test_ai.py の依頼文の比較（画像の大きさの cm）が変わらないことを実装のときに確かめる。

## ほかの単位・ルート2・AI 補完・画面との関係

- ルート2: `pdfdocx` は画像の XML に触れないので、補った docx でも `srcRect` は残り、同じく切り取られる。文字・不変性チェック・`verify_supplement` に影響しない。
- `pipeline.lost_images`: XML に入らなかった画像は書き出さないので、切り取りと無関係。
- `pipeline.convert` の順: 単位どうしの点検で決めた (9) の `export_images` で切り取る。AI の `image_blocks`（(4) の前の依頼）はそれより前なので、自分で切り取る。
- AI 補完: API と手動モードの `AI添付画像/` が Word の表示に合う。切り取れない画像は渡さない。`formula_image` にした図の画像も `export_images` を通るので同じく切り取られる。
- u1（同じ 0.30.0）: `ai_assist.py` は u1 の `parse_response`・`split_ops` の直しの後に直す（関数は重ならない）。0.31.0 の u5 は `build_request` を直す。
- u3-tables・u3-autonum（同じ 0.30.0）: model.py は u3-tables → u3-autonum → u4、docx_reader.py は u3-tables → u4、report.py は u3-tables → u3-autonum → u4 の順に同じ作業の枝で直す。
  並行して作るなら model.py・docx_reader.py・report.actions の head の行・make_fixtures.py を手で合わせる。`Result` には欄を足さない（`ImageResult` の中だけ）。
- make_fixtures.py: u1 の (1a) で fixture を作り直した後に部品を足すが、既定の出力を変えず、fixture は作り直さない。
- 画面: colab・app・cli は `Action` を表示するだけなので変えない。切り取れない画像は既存の要対応 `images` の経路に乗り、1 画面版の「画像を入れる」の欄（`app.missing_images` が `images_to_prepare` を使う。点検で確かめた）・ノートブックの手順 7・`--images` で受け付ける。
- 利用者が後から入れた画像（`add_images`、status user）は切り取らず、知らせない。

## 利用者向けの文

どれも f 文字列の式の中にバックスラッシュ・外側と同じ引用符を書かない（`"・".join(...)` や `esc(...)` の結果は先に変数にする）。レポートに生のタグは書かないので `md_tag` は要らない。

### image_crop（要確認）

`items` は各画像の `{name}`・`{image_id}`・キャプション（20 字。なければ「キャプションなし」）・`{crop_text}`。

- top:
  「> **要確認: Word で切り取った（トリミングした）画像 {n} 件を、Word で表示される範囲に切り取って出力しました（9 章）。** 切り取った画像は {esc(zname)} の中の `{gdir}` にあります。出版版 PDF や Word の表示と比べて、切り取りの位置が合っているか確かめてください。違っていれば、Word で切り取りを直して変換し直してください。」
  の後に「>」と、画像ごとに「> - `{name}`（{image_id}。{esc(cap, 20) or 'キャプションなし'}）: {ct}」。
- checklist: 「- [ ] **Word で切り取った画像 {n} 件**（9 章）の切り取りの位置が Word の表示と合っているか確かめる: `{name}`（{キャプション}）、…」
- box_title: 「Word で切り取った画像 {n} 件を切り取って出力しました（要確認）」
- box_detail: 「Word で切り取った（トリミングした）画像は、docx の中では切り取る前のまま入っているので、Word で表示される範囲に切り取って {zname} の中の {gdir} に入れました。出版版 PDF や Word の表示と比べて、位置が合っているか確かめてください。違っていれば、Word で切り取りを直した docx を{step('docx')}でアップロードし直し、そこから順にやり直してください（レポートの冒頭と 9 章）。」の後に改行と、画像ごとに「・{name}（{キャプション}）: {ct}」。
- cli: 「要確認: Word で切り取った画像 {n} 件を、表示される範囲に切り取って出力した（ZIP の中の {gdir}。レポートの冒頭と 9 章）。位置を確かめること: {name}（{ct}）, …」

### image_edits（要確認）

- top:
  「> **要確認: Word で回転・反転・色の変更などをした画像 {n} 件は、その加工を反映していないことがあります（9 章）。** J-STAGE の画面では、Word の表示と見た目（向き・色・余白など）が違うことがあります。出力した画像は {esc(zname)} の中の `{gdir}` にあります。違っていれば、加工した後の見た目の画像を画像編集ソフトなどで作り、Word で差し替えて変換し直してください。」
  の後に「>」と、画像ごとに「> - `{name}`（{image_id}）: {加工の名前を「・」でつないだもの}{アート効果の添え書き}」。
  アート効果の添え書きは「（docx の画像は効果を付けた後のものの場合がある）」。Word の「図として保存」は勧めない（切り取り・回転を反映するか確かめていない）。
- checklist: 「- [ ] **Word で加工した画像 {n} 件**（9 章）の見た目が Word の表示と合っているか確かめる: `{name}`（{加工}）、…」
- box_title: 「Word の加工（回転・反転・色の変更など）を反映していない画像が {n} 件あります（要確認）」
- box_detail: top の 2 文目以降と同じ内容で、最後を「…Word で差し替えた docx を{step('docx')}でアップロードし直し、そこから順にやり直してください（レポートの冒頭と 9 章）。」にし、改行と画像ごとに「・{name}（{image_id}）: {加工}」。
- cli: 「要確認: Word の加工（回転・反転・色の変更など）を反映していないことがある画像 {n} 件（レポートの冒頭と 9 章）: {name}（{加工}）, …」

### 切り取れなかった画像（要対応。既存の key `images`）

`ImageResult.message`（`images_to_prepare` の理由の欄）は 3-3・3-4 の文。`images_action` は 5-4 の 2 か所だけ直す。

### 9 章の備考

「Word のトリミングに合わせて切り取った（左 50.0%。200×100 px → 100×100 px）」「Word の加工（回転）は反映していない」。表の列は変えない。

### 中止

しない（中止は K1・K2 だけ）。

## 文書の更新（CLAUDE.md は案だけ）

この単位の実装者が直すもの:

- docs/ARCHITECTURE.md:
  - images.py の行: 「png/jpg/gif はそのまま」→「png/jpg/gif はそのまま。Word のトリミング（`ImageRef.crop`）があれば Pillow で切り取る（`crop_image`）。切り取れなければ切り取る前の画像を `要変換/` に置き、用意が必要な画像（failed）にする」。主な名前に `crop_image`・`CropError` を足す。行数。
  - docx_reader.py の行: `_graphic` が `a:srcRect`・`v:imagedata` の `crop*` と回転・反転・色の加工を `ImageRef.crop`・`edits` に記録すること。行数。
  - ai_assist.py の行: `image_blocks` が切り取った画像を渡し、切り取れない画像は渡さないこと。
  - report.py の行: `_image_crop_action`（key `image_crop`）・`_image_edits_action`（key `image_edits`）。actions の並びは単位どうしの点検で決めた順で書く（版の最後にまとめて直す分と合わせる）。
- docs/DESIGN.md:
  - 処理の流れの画像の書き出しに切り取りを足す。
  - 「アップロード用 ZIP の中身」の行（807 行目）に「Word のトリミングは切り取って出力する（要確認）。切り取れないもの（EMF/WMF、Exif の向きのある画像、複数のコマの画像など）は ZIP に入れず、切り取る前の画像を `要変換/` に置いて要対応」を足す。
  - 「画像ファイル名」の行（806 行目）をコードに合わせる（下の食い違い 1）。
  - 7 章（既知の限界）に「回転・反転・色の変更・図の効果は反映しない（要確認）」「EMF/WMF のトリミングは、LibreOffice が A4 の紙面に置くので位置を当てはめられない（要対応）」「JPEG を切り取ると、元と同じ量子化表で再圧縮する。Exif・PNG の gAMA などの chunk は落とす。16 bit の RGB の PNG は 8 bit になる」を足す。
- src/jasme_jats/images.py の docstring（3-5）。

版の最後に Opus がまとめて直すもの（単位どうしの点検の決定。文の案を渡す）:

- docs/REVIEW_2026-11.md: 直したものとして「Word でトリミングした画像（計画の u4。0.30.0）」と「1 つの drawing に pic が複数あるときの大きさ 0（u4。0.30.0）」。新しい未修正の項目は下の「直さず REVIEW に記録するもの」。
- docs/USAGE.md の「たとえば次のものです」の一覧に 2 行:
  - 「**要確認「Word で切り取った画像を切り取って出力しました」（`image_crop`）** — Word でトリミングした画像は、docx の中では切り取る前のまま入っているので、Word で表示される範囲に切り取って出力しました。出版版 PDF や Word の表示と比べて位置を確かめてください。切り取れない画像（Word の図〈EMF/WMF〉など）は ZIP に入れず、要対応「画像ファイルを用意できなかった図」になります。」
  - 「**要確認「Word の加工を反映していない画像があります」（`image_edits`）** — Word で回転・反転・色の変更などをした画像は、その加工をせずに出力しています。J-STAGE で見た目が違えば、加工した後の見た目の画像を作って Word で差し替えてください。」
- docs/DEVELOPMENT.md の守るべき原則 7（ZIP に入れるもの）に一言（任意）: 「Word で切り取った画像は切り取って入れ、切り取れなければ failed にして入れない（`images.crop_image`）」。

CLAUDE.md（実装者は直さない。利用者の承認を待つ案）: 「アップロード用 ZIP に入れるものは…」の項の後ろに次の 1 文を足す。

> Word でトリミングした画像は、Word で表示される範囲に切り取って入れ（要確認）、切り取れないもの（EMF/WMF など）は入れずに「用意が必要な画像」（要対応）にする（`images.crop_image`）。Word で隠した部分は ZIP にも AI にも渡さない。

## 文書とコードの食い違い

1. docs/DESIGN.md の「画像ファイル名」の行（806 行目）は `{巻}_{開始ページ}_{連番2桁}.png` と書くが、コードは `image_name_pattern`（jasme.toml の `"{article_id}_{n:02d}"`）に、
   元の画像の拡張子から png/jpg/gif を付ける（`builder.name_image` 102〜106 行目。JPEG は `.jpg`）。**この単位で文書の側を直す**（「`{記事識別子}_{連番2桁}` に、元の画像の形式の拡張子〈.png・.jpg・.gif。ほかの形式は変換して .png〉」）。
2. `images.export_images` の `shape_only` の message（153〜155 行目）は「ノートブックは手順 7、1 画面版は「画像を入れる」の欄」と画面の操作を直接書き、`images_action` の box_detail の行にそのまま出る。
   CLAUDE.md の「手順番号や欄の名前を直接書かず、目印 `report.step()` で書く」と食い違う（REVIEW の O2 の記録では、images.py の理由の文は両方の言い方にしたとしている）。**直さない**（REVIEW に新しい項目として記録）。この単位で足す文には手順番号・欄の名前を書かない。
3. `images.convert_metafile` の LibreOffice がないときの文（54 行目）が、ない欄名「EMF/WMF 画像を変換する」を指す（REVIEW の O11。既知）。**直さない**。
4. docs/ARCHITECTURE.md の images.py の行「png/jpg/gif はそのまま」は今のコードと合っているが、この単位の修正の後は食い違うので合わせる（文書の更新）。

## 新しく見つけた問題（この単位で直すもの／直さず REVIEW に記録するもの）

この単位で直すもの:

- 1 つの `w:drawing` に `pic` が複数あるとき、画像の大きさが 0 になる（`pic.find('.//a:ext')` が `a:blip/a:extLst/a:ext` を拾う）。グループの縮尺も掛けていなかった（直し方 2-2）。
  行内（`wp:inline`）のグループでは `floats.para_lines` が最初の画像の `height_cm` で行数を推定するので、0 から実際の値になると図表の位置の推定が変わりうる（実際の原稿で該当なし）。
- `images_action` の文の「画像（PNG）」と「docx に画像ファイルがない」（直し方 5-4）。
- JPEG の Exif の縮小画像・Pillow 13 の mode I（直し方 3-1。点検で見つけたもの）。

直さず REVIEW に記録するもの:

- 前の版の変換で `Graphics/` に置いた切り取る前の画像は、今回 failed になっても記事フォルダに残る（ZIP には入らず、10 章の「ZIP に入れなかったファイル」に出る）。
- 依頼文（`build_request`）は、AI に渡さなかった画像（切り取れない画像、変換できない EMF）を ⟦画像 imgN⟧ のまま書き、添付がないことを AI に伝えない（今までの EMF と同じ）。
- `convert_metafile` は LibreOffice が A4 の紙面に置いた画像の白の余白を切るので、EMF の枠の中の白の余白も切り、Word の表示より狭くなりうる（以前からの動き）。
- `export_images` の `shape_only` の文が手順番号を直接書く（上の食い違い 2。O2 の一部）。
- Word が JPEG の Exif の向きを表示に使うか、`srcRect` がどちらの向きの座標かは未確認（切り取りをやめて要対応にするので、出力が誤ることはない）。
- `a14:imgProps` の `a:blip` の画像が効果を付けた後のものかは、手元に例がなく未確認（要確認で知らせるだけ）。
- CMYK の JPEG（Photoshop の Adobe 反転・YCCK）の色の往復は、Pillow で作った画像でしか確かめていない。PNG の gAMA・cHRM・テキストの chunk は落ちる。16 bit の RGB の PNG は 8 bit になる。
- 回転・反転は反映しない（90 度単位の回転と反転は Pillow で反映できるが、実際の原稿に例がないので今回は入れない）。負の `srcRect` は余白を足さずに 0 にする。

## 未決のこと（利用者の返事待ち／実装のときに確かめること）

利用者の返事待ち: なし（2026-11-06 の決定で、切り取って出力し要確認で知らせる。切り取れないもの・回転などの扱いは計画者が決めた）。CLAUDE.md の案（文書の更新）は承認待ち。

実装のときに確かめること:

- tests/test_ai.py の依頼文の比較（画像の cm の表示）が、`a:ext` の探し方の変更で変わらないこと。
- Pillow 13 の環境で `test_crop_image_png_16bit_and_alpha_modes` が通ること（新しい venv で一度回す。点検では I;16 が書けること、PA が書けないことを確かめた）。
- 出力ファイル名が .jpg なのに中身が PNG の画像など、`im.format` と `fmt` が違うとき、`qtables` を渡さずに保存できること。
- `drawing` の既定の出力が今とバイト単位で同じこと（既存の fixture を作り直さないので、新しいテストで `drawing(...)` の文字列を比べてもよい）。
- テストデータ3・5 で、切り取った画像の大きさが 534×401・1308×556 になり、mode・dpi が残ること（基準との比較）。

## 点検の指摘の反映表

| 重さ | 題 | 反映した節 |
|---|---|---|
| major | JPEG の Exif をそのまま渡すと、切り取る前の全体の縮小画像（IFD1）が ZIP に入る | 直し方 3-1（Exif は渡さない）、テスト（`test_crop_image_drops_exif_thumbnail`） |
| major | `crop_image` の保存の失敗（Pillow 13 の mode I など）が捕まらず、変換全体が落ちる | 直し方 3-1（全体を try で CropError に、I を外す、PA などは RGBA）、テスト（`test_crop_image_png_16bit_and_alpha_modes`・`test_crop_save_error_becomes_failed`） |
| major | 切り取れなかった画像が入る `images_action` の文が合わない（「（PNG）」と「docx に画像ファイルがない」） | 直し方 5-4、テスト（`test_uncroppable_jpeg_images_action_text`）、回帰の確かめ（レポートの文） |
| minor | グループ図形の中の pic の大きさを子の座標のまま使う | 直し方 2-2（chExt と wp:extent の比を掛ける）、テスト（`test_group_pic_size_scaled_by_chext`）、新しく見つけた問題（`floats.para_lines`） |
| minor | 切り取りが 1 px 未満でも再圧縮・要確認になる。小さな負の値で「余白」が出る | 直し方 3-1（`crop_image` が None を返す）・3-3（DIRECT は ok のまま）・2-1（-0.001 より小さいときだけ「余白」）、テスト（`test_subpixel_crop_is_noop`・`test_tiny_negative_src_rect_not_padding`） |
| minor | Exif の向き 0 で切り取りをやめて要対応になる | 直し方 3-1（`not in (0, 1)`）、テスト（`test_exif_orientation_zero_is_cropped`） |
| minor | 読めない srcRect・VML の crop の値を黙って 0 にする | 直し方 2-1（「切り取り（読めない指定）」）、テスト（`test_reader_unreadable_src_rect`） |
| minor | `image_edits` の文が `a14:imgProps`・余白・塗りつぶしの範囲に合わない。「図として保存」の案内は確かでない | 直し方 2-1（`a14:imgProps` は「図の効果」と分けて「アート効果」の名前にし、その行だけに添え書き）、利用者向けの文（image_edits。「反映していないことがあります」「見た目（向き・色・余白など）」、「図として保存」は書かない） |
| minor | `image_crop` の要確認で、切り取った画像がどこにあるかを示していない | 利用者向けの文（image_crop の top・box_detail・cli に `graphics_dir(r)` の置き場所） |
