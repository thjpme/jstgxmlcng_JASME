# 単位 C（0.23.0）の設計メモ（impl）

正本は docs/FIX_PLAN.md の C の節。ここは関数ごとの変更点と、実装で決めたこと。

## M1+M2: アップロード用 ZIP の中身

- `images.export_images(doc, images, out_dir, convert_metafiles=True, keep_dir=None)`
  - 変換できなかった EMF/WMF の元のファイルを `keep_dir` に置く。None なら今までどおり `out_dir.parent / "要変換"`（呼び出し側は pipeline だけ）。
  - pipeline は `out_dir / "要変換"`（出力フォルダの直下。記事フォルダの外）を渡す。メッセージ「…。元の画像を 要変換/{名前} に保存した」は変えない。
- `package.ZIP_STATUSES = ("ok", "converted", "user")`、`package.zip_image_names(images)`: ZIP に入れる画像の名前（状態が ok・converted・user）。
- `package.upload_entries(out_dir, journal, meta, image_names, has_pdf)`: ZIP に入れる項目（ZIP の中のパス。out_dir からの相対）の一覧。
  `{aid}.xml`、has_pdf なら `{aid}.pdf`、`Graphics/{画像}`（image_names の順）。これだけで ZIP の中身を決める。
- `package.make_zip(out_dir, journal, meta, image_names=(), has_pdf=False)`: upload_entries の項目だけを詰める（記事フォルダを rglob しない）。
- `package.write_package(out_dir, journal, meta, xml_bytes, pdf_path=None, image_names=())`: 今までどおり XML と PDF を置き、make_zip に渡す。戻り値は同じ (zpath, adir, has_pdf)。
- `package.zip_problems(zpath, journal, meta)`: ZIP を読み直して [(メッセージ ID, 内容)] を返す。
  (a) ZIP の名前が `[A-Za-z0-9._-]+` でない → EMSGM034E。
  (b) パスの各部分（フォルダ名・ファイル名）が `[A-Za-z0-9._-]+` でない → EMSGM034E（同じ部分は 1 件。記事フォルダの Graphics/ の画像名は jstage_rules が見るので除く）。
  (c) 記事フォルダの外の項目 → '-'（EMSGM219E のおそれ）。記事フォルダごと（資料コード/巻/号/記事識別子 の 4 階層）にまとめて 1 件。
      記事フォルダの中の想定外の項目（{aid}.xml・{aid}.pdf・Graphics/ の直下のファイル以外）→ EMSGM074E（項目ごと）。
  (d) 0 バイト: {aid}.xml → EMSGM053E、{aid}.pdf → EMSGM059E、Graphics/ の画像 → EMSGM073E。
  ZIP として読めないときは EMSGM034E 1 件（"ZIP として読めない"）。
- `package.unzipped_files(out_dir, journal, meta, zpath)`: 記事フォルダにあるのに ZIP に入っていないファイル（記事フォルダからの相対パス、並べたもの）。
- `Result.zip_issues`・`Result.not_zipped`（既定は空）。convert でも add_images でも計算し直す（res.warnings には入れない）。
- pipeline.add_images: make_zip に、今の res.images から zip_image_names と res.has_pdf を渡し、zip_issues・not_zipped を計算し直してからレポートを書く。
- report:
  - 1 章の「J-STAGE のアップロード時チェック」の行と 12 章の表は jstage_issues + zip_issues（12 章の説明に ZIP の中身も確かめることを足す）。
  - 1 章の「警告」の行: not_zipped があれば「、ZIP に入れなかったファイル n 件」を足す。
  - 10 章: not_zipped があれば、警告の後に 1 項目（「ZIP に入れなかった」）。PDF があれば手順 2 / --pdf、Graphics/ があれば手順 7 / --images を案内し、
    それ以外は前の変換の残り・手で置いたファイルで、対応は要らないと書く。
  - 14 章の PDF の行: has_pdf なら「- [x] PDF（{aid}.pdf）が ZIP に入っている」、なければ「- [ ] **PDF（{aid}.pdf）が ZIP に入っていない**: Colab では手順 2 で記事の PDF を選び、コマンドラインでは --pdf で指定して変換し直す」。
- cli・ノートブック（手順 5・6）: 「J-STAGE のアップロード時チェック」の件数と一覧に zip_issues も含める（表示に両方を使う）。
- README: 要変換/ の行（出力フォルダの直下、ZIP には入らない）と ZIP の行（今回の XML・画像・指定した PDF だけ）。

## N4: 巻・号・ページ

- `ArticleMeta.from_dict`: volume・issue・fpage・lpage を `str().strip()` → NFKC → strip。変わったら `input_notes` に「巻「３１」を「31」として読みました（全角の文字を半角にしました）」を足す。
  volume・issue・fpage が空でなく `[A-Za-z0-9]+` でなければ ValueError（欄の名前・入力・使えない文字。非 ASCII があれば「全角の文字」が原因と書く）。
  欄の名前は Colab の手順 3 に合わせる（巻・号・最初のページ・最後のページ）。
- `ArticleMeta.input_notes: list`（入力値を直した知らせ。XML には出さない）。入力の辞書の同名の鍵は使わない。
- 表示の場所:
  - Colab の手順 3: ValueError は今までどおり `SystemExit(f"入力を確認してください: {e}")`。input_notes は「入力しました」の後に「※ …」で 1 行ずつ print（既存の「※ 原稿種別は…」と同じ書き方）。
  - CLI: `ArticleMeta.load` の ValueError を捕まえて標準エラーに「書誌情報（ファイル）を確認してください: …」、終了コード 2（中止。AIRequiredError と同じ）。
    input_notes は標準出力に「※ …」。
  - レポートの 11 章: input_notes があれば表の後に 1 行ずつ（golden は、入力を直さないので変わらない）。

## U1: 日付

- `config._date(v, label="日付")`: None・"" → None。datetime → .date()（datetime を先に判定）。date → そのまま。
  それ以外は NFKC にして空白をすべて除き、空なら None。`[0-9]{4}[0-9]{2}[0-9]{2}` か `[0-9]{4}[-/.年][0-9]{1,2}[-/.月][0-9]{1,2}日?` に fullmatch したら
  date(年, 月, 日)（存在しない日は ValueError）。それ以外は ValueError「{label}「{v}」を読めません（YYYY-MM-DD の形で入力してください。2026/3/31 のようにも書けます）」。fromisoformat は使わない。
- from_dict の日付の繰り返しで欄の名前を渡す（発行日・J-STAGE 公開日・受付日・再受付日〈revised。Colab にはない欄〉・受理日・最終査読日）。
- make_notebook.py の手順 3 の説明「日付は 2026-03-31 の形で（2026/3/31 でもかまいません）、分からなければ空欄にします。」

## FIX_PLAN と違えること

- 付録 M2 の最初の版の「warnings に「31_1.pdf」があること」は、C の節の方針（res.warnings に入れない。反証の方針）に従い、not_zipped で確かめる。
- zip_problems の (c) 記事フォルダの外の項目は、記事フォルダ（4 階層）ごとにまとめて 1 件にする（項目ごとだと画像の数だけ並ぶため）。
