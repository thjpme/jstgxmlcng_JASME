# 単位「中低 A」: 知らせと入力の確かめ（C067 の (1)・C038・C077・C095・C057・C105）

- 対象の版: 0.35.0 の上（版上げ・反映は監督が行う）。XML は変えない。論文は data14 のように呼び、中身は書かない。例とテストは架空。
- 確かめの結果: `triage_all.json` の items と check（C067・C038・C077・C095・C057・C105 は「案のまま」。C057 は C105 と一緒に閉じる）。

## 設計と実装

### C067 の (1): 要確認 `note_unlinked`
- `report.note_problems(plan)`（新設）が、手で書いた注の (注の一覧, 本文での初出の順, 番号を読めない注 unnum, 本文から参照されない注 unref) を返す。
  3 章の `note_notes` も同じ関数を使うので、件数がずれない（新しい判定は作っていない）。AI の仕上げ（link_note）でリンクされた注は、plan の本文の参照に
  入っているので数えない。注の読み取り（Unicode の上付き・「[N]」）は変えない（(2) は later）。
- `report._note_unlinked_action`: 件数・場所（段落 ID・見出しの場所・先頭の文字）・Word での直し方つき。先頭 5 件（`NOTE_UNLINKED_SHOWN`）、残りは「ほか N 件（3 章）」。
  番号が読めず参照もされない注は 1 行にまとめる。`actions()` では `_note_overlap_action` の次。
  点検 review20 の 2 回目の後: 文を印で分ける（unref があるときだけ「本文からリンクされていない・リンクがない」、unnum だけなら「番号を読み取れず、複数の注が 1 件にまとまっていることがある」。AI の回答があるときは結果の文に区切りの点を書かない）。手がかりの［検索］の文字は見つかった形のものだけ、「ほか N 段落」の後ろの余分な空白は消した。
  点検 review20 の後: 件数は注の数（「注 2 件が…（番号を読み取れない・本文から参照されていない）」）で、行に当たる印を全部書く。参照されない注があれば、本文の
  Unicode の上付きの「¹⁾」・「[1]」の形の文字のある段落 ID（先頭 3 段落。`_note_mark_hint`。読むだけ）を添える。AI の回答が入っているとき（`ai_state` が済み・一部）は
  「AI でも直せます」を言わず、ai_boundary と同じ Word での直し方（「1)」の形に直して AI の回答を入れずに変換し直す）にする。Colab の枠に `step('docx')` からやり直すことを書く。
- 実際の 28 論文: data6（AI あり: 番号を読めない注 1・参照されない注 1）、data21（AI なし: 参照されない注 4。AI の link_note でリンクされると 0）。

### C038: 兄弟の見出しの深さの食い違い（`heading_level`）
- `structure.sibling_level_mismatches(body)`（`Classifier.build_body` が `nest` の後で呼ぶ）。見出しを番号の形で系列に分ける:「3.1」「3.2」は章 3 の下、「3.1.1」は 3.1 の下、
  「(1)」は直前の「3.」「3.1」の形の見出しの下、「①」は直前の（①でない）見出しの下、「1.」「2.」は章の系列。系列の中の `Sec.level`（見出しのスタイルの階層）が 2 種類以上なら、
  多数の階層（同数なら最初）と違うものだけを挙げる。誌の慣習（章の下の「(1)」が節など）は決め打たない。番号が文字にない見出し（自動番号）は見ない。構造は変えない。
- 番号は NFKC の前の文字で読む（`structure._heading_number`）。「.」「．」の後ろの数字が前の数字と全角・半角が違えば題名の始まりとみなす（PDF に合わせた docx で
  「3.2． ２倍…」の空白が消えた「3.2．２倍…」を 3 段の「3.2.2」と読まない。点検 review20 利用者向け 1）。行には多数の階層の兄弟の番号（2 つまで）と、
  そのスタイルの名前 1 つの直し方（`StyleSuspect.how`。`Classifier.heading_style`）を書く。
- 実際の 28 論文: data22 の 1 件。AI なし・AI ありの両方の style_check に出る（AI ありでは AI の提案つき）。style_check の key はもともとあったので、key の差には出ない。
  XML の階層は変えない。review20 の修正の前は、pdf ルートでは上の空白の削除のために出なかった。誤検出 0。

### C077: 太字だけの 1 項目の番号つきリスト（`heading_guess`）
- `Classifier.bold_single_lists(body)`: 本文の 1 項目だけの順序つきリストで、段落が全部太字・40 字以下・「。」を含まないもの。既存の種類 `heading_guess` に、
  「1 項目だけの番号つきリスト」の見立てで載せる（リストは変えない）。直し方は行の `StyleSuspect.how` で言い切る（中の節の 1 つ下の見出しのスタイルにする。Word の段落番号は見出しの番号として出る。番号の形を PDF に合わせたいときだけ段落番号を外して打つ〈点検 review20 利用者向けの 2 回目〉。番号つきの箇条ならそのまま。heading_guess の一般の直し方は重ねない。点検 review20 利用者向け 5）。
- 実際の 28 論文: data17 の 1 件、data27 の 3 件。

### C095: 責任著者の番号と制御文字
- 点検 review20 の後: 制御文字の文の欄の名前を 1 画面版（`app.LABELS`）に合わせ（「キーワード（日本語）」など）、キーを括弧で添える（「DOI の欄（doi）に、…」）。
- `config._corresp`: 整数・「1,2」の文字列・整数の一覧を 1 以上の整数にし、読めなければ分かる文の ValueError（0・負の数・小数・真偽値・数字でない文字）。
  `config._check_text_fields`: 文字列の欄（TEXT_FIELDS。最後のページ・DOI・原稿種別・言語・キーワードなど）の Cc・Cf（改行・タブ・復帰は除く）を、欄の名前と文字の番号つきで断る。
  どちらも `ArticleMeta.from_dict` の 1 か所なので、1 画面版（`AppState` の InputError）・ノートブック（SystemExit）・コマンドライン（終了コード 2）が同じ所を通る。
- `report._meta_corresp_action`: 著者の人数の範囲外の番号が 1 つでもあれば要確認 `meta_corresp`。範囲外の番号には印を付けず、最後の著者に付けるなどの推定はしない。点検 review20 の 2 回目の後: 文に著者の順（`report.author_names`。「1: 氏名」）を挙げ、著者が 1 人なら「1〜1」と書かない。11 章の表に「責任著者」の行（`report.corresp_cell`。入力の番号と印を付けた著者の氏名。範囲外はそうと書く）を足した。
  著者が 1 人もいない原稿は要対応 `authors_missing` で知らせるので出さない。

### C057・C105: pypdfium2
- `pyproject.toml` の `images`・`dev` を `pypdfium2>=5,<6`。`report.pdfium_version()`（importlib.metadata。入っていなければ ""）の版を、レポートの冒頭の「ツール」の行の隣に
  「PDF を読むライブラリ: pypdfium2 X」と書く（Action にしない）。Pillow の下限は触れていない（C105 の残り）。
- CI（`.github/workflows/test.yml`）: `pip install -e ".[dev]"` が 5.x を入れる（Python 3.10 でも py3-none の wheel で入ることを確かめた）。変更不要。
  ノートブックは `jasme-jats[ai,images,colab]` を入れるので範囲は pyproject から入る。`tools/make_notebook.py` に版は書いていないので、作り直しても差分は出ない。
  `pdfmatch._clip_api` の古い版向けの退避は残す（5 未満を入れない範囲にしたので、通常は働かない）。

## `STYLE_SUSPECT_KINDS`・`STYLE_NO_AI_KINDS` の区分（rest_D.md の決め方に合わせた）
- `heading_level`・`heading_guess`（C077 を含む）は **AI の提案を待つ種類**（`STYLE_NO_AI_KINDS` に入れない）。直し方が機械的に決まらず、どちらの階層が正しいか・
  本当に見出しのつもりかは出版版 PDF を見れば AI が答えられるため（heading_body・既存の heading_guess と同じ）。直し方が決まっている ref_symbol・back_heading・ref_cont だけが待たない。
- 理由と影響: 推奨の手順 `ai_finish`（要対応・終了コードには数えない）が、この種類だけの原稿でも出る。実際の 28 論文で増えたのは data17 の 1 件（ほかは既に出ていた）。

## 足したテスト
- `tests/test_midlow_a.py`（33 件）: note_unlinked（3 章と同じ判定・参照されず番号も読めない注は 1 行）、heading_level（食い違い・揃っている・誌の慣習の混在・「(1)」の系列）、
  太字の 1 項目リスト（1 項目だけ挙げ、2 項目・太字でないものは挙げない。リストは 1・1・2 のまま）、corresp（読める形・読めない形・範囲外は印を付けず知らせる）、制御文字（欄ごと・改行とタブは通す・CLI に traceback が出ない）、
  pypdfium2 の範囲と版の記録（入っていなければ書かない・Action にしない）。
- `tests/test_app.py`: 1 画面版の入力の確かめ（責任著者・制御文字）。`tests/test_style_check.py`・`test_pipeline.py`・`test_colab.py` の期待を、新しい文・新しい知らせに合わせた。

## 回帰（タグ mA、基準 runs_fx3。46 docx × 2 ルート）
- 同じ 88 件、違う 4 件。XML の差 0。状態・不変性チェック・最終チェック・補完の確かめ・DTD・例外の差 0。
- 知らせの key の差: data6（docx_ai・pdf_ai）に要確認 `note_unlinked`、data17（docx・pdf）に推奨の手順 `ai_finish`（C077 の 1 件で style_check の行が増えた）。
- key が変わらず行が増えたもの: data27 の style_check に 3 行（C077）。data22 の 1 件（C038）は、AI なし・AI ありの両方の style_check に出る（AI ありでは AI の提案つき）。
  style_check の key はもともとあったので、key の差には出ない。XML の階層は変えない（AI の回答は見出しの階層を XML に反映しない。所有者の決定 5）。
