# コードの地図（引き継ぎ用）

このツール（jasme-jats 0.31.0）の「どこが何をしているか」を、別の人や AI が短時間で把握できるようにまとめたもの。
2026-11-03 にコード全体を読み直して書き、2026-11-08 に 0.30.0 の修正（`docs/FIX_PLAN_2026-11.md` の u1〜u4）と 0.31.0 の修正（u5・u6）に合わせて直した。

既存の文書との関係:

| 文書 | 何が書いてあるか |
|---|---|
| `CLAUDE.md` | 最優先の原則の要点（Claude Code が毎回読む） |
| `docs/DESIGN.md` | 設計の判断とその理由（文字ポリシー、PDF との照合、AI 補完、J-STAGE への合わせ方、既知の限界） |
| `docs/DEVELOPMENT.md` | 守るべき原則、テストが何を守っているか、反映の流れ、残っている課題 |
| `docs/FIX_PLAN.md` | 2026-10 のレビュー以降の修正計画と、利用者の決定事項（なぜ今の形になったかの経緯） |
| `docs/GUI_PLAN.md` | 1 画面版（Gradio）の設計と経緯 |
| **この文書** | **コードの構成（モジュールの層・依存・データの流れ・入口）と、「変えたいときはどこを見るか」** |
| `docs/REVIEW_2026-11.md` | 2026-11 の点検で見つけた問題と、その分類（直すべき度合い） |
| `docs/FIX_PLAN_2026-11.md` | 2026-11 の別の AI の点検に基づく修正計画（0.30.0・0.31.0）と、単位ごとの設計書（`docs/fix_plan_2026-11/units/`） |

---

## 1. 全体像

```
入力: 論文の docx（＋ 書誌情報、任意で 出版版 PDF、任意で AI の回答）

  [ルート2 のときだけ] pdfdocx.make_fixed_docx: PDF と照合して、補った docx（変更履歴つき）を作る ── 以降はそれを入力にする
        │
  docx_reader.read_docx ──────────▶ model.Document（段落 = アトムの列。表・画像・図形・脚注も）
        │
  structure.classify ─────────────▶ article.ArticlePlan（題目・著者・本文の章節・図表・注・文献・英文要旨・資料。除外した段落と判断の記録）
        │                                 構造の衝突（同じ種類の後付けの見出し・英文要旨の見出しが 2 つ、著者名の付かない所属。K1・K2）があれば
        │                                 pipeline が StructureConflictError で中止（ルート2 は補う前の元の docx で確かめる）
        │
  linker.link（refparse を使う）──▶ アトムに LinkSpec を付ける（図表・数式・注・引用・URL/DOI）。文字は変えない
        │
  [AI 補完] ai_assist: 依頼文を作る → API を呼ぶ／手動で貼り戻す → JSON を検証 → 役割の指定と図表の配置で classify をやり直し → リンク等を適用
        │
  builder.build（emit を使う）────▶ lxml の木（文字はすべて <jx:span src=段落ID> の中。tracking）
        │
  [PDF があるとき] pdfmatch.check_pdf: docx の段落と PDF の文字を照合（ルート2 では Word が付ける番号を PDF に合わせて build をやり直す）
        │
  fidelity.verify ────────────────▶ docx の文字（ooxml.canonical_texts の別実装）と XML の文字を 1 文字ずつ照合
  builder.finalize / serialize ───▶ 目印を外した最終 XML → fidelity.final_check で再照合 → validate.validate（DTD）
  [ルート2] fidelity.verify_supplement: 補った docx が元の docx から (A)(B) 以外に変わっていないか
  pipeline.lost_images ───────────▶ 画像を入れる場所（置き場所）を作れなかった画像（置き場所をすべて書いた XML〈xml_base〉で調べる）
  pipeline.image_problems ────────▶ XML の画像の名前が置き場所の一覧と合わない所（要対応 image_names）。decorations は飾りの図形の記録（9 章）
  pipeline.table_problems ────────▶ 形の崩れた表（行ごとの列の数・セルの重なり・縦の結合の範囲・セルのない行）
  pipeline.lost_autonums ─────────▶ XML に番号が出なかった Word の自動番号の段落
  pipeline.pua_chars ─────────────▶ 最終の XML に残った私用領域の文字（要対応 pua_left）。symbols_replaced は記号フォントの記号を置き換えた記録（要確認 symbol_replaced）
        │
  package.apply_images（置き場所をすべて書いた XML〈Result.xml_base〉から最終の XML。docx の画像は書き出さない）→ jstage_rules.check
  → package.write_package（ZIP）→ report.render（レポート）。図・表の画像は後から pipeline.add_images で入れ、XML・ZIP・レポートを作り直す
        │
出力: {記事識別子}.xml、jasme_{記事識別子}.zip、{記事識別子}_変換レポート.md、（AI 依頼文.txt、AI判断一覧.md、PDFで補完した原稿.docx）
```

この流れの実体は `pipeline.convert()`（`src/jasme_jats/pipeline.py`）。画面（CLI・Colab・Gradio）はこれを呼ぶ薄い層にすぎない。

### 層で見たモジュール

```
画面      cli.py   colab.py（表示部品）   app.py（Gradio）   tools/make_notebook.py（ノートブック生成）
流れ      pipeline.py（convert / add_images / kept_images / reapply_images / lost_images / image_problems / decorations / table_problems / lost_autonums / pua_chars / symbols_replaced / Result / StructureConflictError）
出力      report.py（レポート・利用者への知らせ actions）  package.py（ZIP）  images.py（画像）  imagelist.py（図の確かめ.html）  jstage_rules.py
検証      fidelity.py（不変性チェック・補完の確かめ）  validate.py（DTD）
組み立て  builder.py → emit.py → omml.py（数式）  tracking.py（目印）
AI        ai_assist.py
PDF       pdfmatch.py（照合）  pdfdocx.py（補った docx を書く）
リンク    linker.py  refparse.py
構造      structure.py（Classifier）  article.py（型）  floats.py（図形の位置の判定）
読み取り  docx_reader.py  numbering.py（自動番号）
基盤      ooxml.py（文字ポリシー・隠し文字・段落のつながり）  model.py（中間表現）  config.py（設定・書誌情報）  data/jasme.toml  dtd/
```

### モジュールの依存（import。上が下を使う）

| モジュール | 使うモジュール |
|---|---|
| `cli` | ai_assist, colab（`step_text`）, config, pipeline, report |
| `app` | ai_assist, colab, config, pipeline, report |
| `colab` | report（`STEP_MARK_PATTERN`・`NEEDS_ACTION` など。`step_text` が目印を読む） |
| `pipeline` | ai_assist, article, builder, config, docx_reader, fidelity, images, jstage_rules, linker, model, package, pdfdocx, pdfmatch, report, structure, tracking, validate |
| `report` | ai_assist, docx_reader, images, linker, model, package, pdfdocx, pdfmatch, structure, validate（`md_tag` が要素名を引く） |
| `fidelity` | omml, ooxml, pdfdocx（定数 AUTHOR・PARTS だけ）, pdfmatch（定数だけ）, tracking |
| `pdfdocx` | builder, docx_reader, linker, model, ooxml, pdfmatch, structure |
| `pdfmatch` | linker, model |
| `ai_assist` | article, builder（`RE_LABEL_SPLIT`）, floats, images, linker, model, omml, structure |
| `builder` | article, config, docx_reader, emit, model, ooxml, structure（`CAP_BRANCH_SEP`）, tracking |
| `emit` | model, omml, tracking |
| `omml` | ooxml, tracking |
| `linker` | article, model, refparse, structure（`CAP_BRANCH_SEP`・`caption_label`・`RE_CAP_BRANCH`） |
| `refparse` | linker, model（linker と相互に import する。関数の中で使うので循環はしない） |
| `structure` | article, floats, model, ooxml |
| `article` | model だけ |
| `floats` | model |
| `docx_reader` | model, numbering, ooxml |
| `numbering` | ooxml |
| `ooxml`, `model`, `config`, `images`, `package`, `jstage_rules`, `validate`, `tracking` | （ほかのモジュールを使わない） |

循環 import がないことは `tests/test_article.py` が別プロセスで確かめている。

---

## 2. 主要なデータ型と、その流れ

| 型（定義場所） | 作る所 | 読む所 | 中身 |
|---|---|---|---|
| `model.Document` | `docx_reader.read_docx` | structure, builder（画像）, pipeline, report | `blocks`（Para と Table の列。本文の順）、`footnotes`/`endnotes`（ID → [Para]）、`media`（画像のバイト列）、`styles`、`images`（ImageRef。Word のトリミングの割合 `crop` と、書き出しで反映しない加工の名前 `edits`〈`model.IMAGE_EDITS` の順〉も。画像の置き場所を決める手がかりとして、同じ `w:drawing`・`w:pict`・`w:object` の画像に共通の `draw_id`、画像の中身の要約値 `digest`、画像のある段落の ID `para_src`、画像の位置に数えない飾りの種類 `decoration` も）、`floats`（浮動配置の図形）、`textboxes`、`layout`（段組み）、`hidden_text`/`style_hidden`、`joined`/`joins`（段落記号の削除でつないだ段落）、`deleted_rows`、`symbols`（`SymbolReplaced`。記号フォントの私用領域の符号を Unicode にしたもの・しなかったもの）、`resultless_fields`（`ResultlessField`。結果を持たないまま終わるフィールドで Word では表示のあるもの。EQ の囲い文字など）、`warnings` |
| `model.Para` | docx_reader | すべて | `src`（段落 ID: 本文 d1, d2…、脚注 f…、文末脚注 e…）、`atoms`、`style_id`、`numbering`/`autonum`、`float_id`/`textbox_id`、`role`（structure が決める） |
| `model.Atom` | docx_reader | linker, emit | `kind` が text / math / image / fnref / gen。`text`、`fmt`（bold など）、`href`、`link`（LinkSpec）。`plain()` は文字でないものを U+FFFC にする |
| `model.Table` / `Row` / `Cell` | docx_reader | structure, builder, pipeline.table_problems | `Table.rows`（Row）、`Row.cells`（Cell）・`header`・`grid_before`/`grid_after`（行の前後で飛ばしたグリッドの列の数）・`number`（docx の表の何行目か。警告の行の番号）、`Cell.gridspan`（0・負・数でない値は 1）・`vmerge`（restart / continue）・`blocks`。縦の結合の `rowspan` は中間表現に持たず、builder が組み立てのときに数える |
| `model.LinkSpec` | linker, refparse, ai_assist | emit | `kind`（xref / uri / ext-link / pub-id / year / article-title / source / label）、`attrs`、`origin`（word / mechanical / ai） |
| `article.ArticlePlan` | `structure.classify` | linker, ai_assist, builder, report, pipeline, pdfmatch, pdfdocx | 論文の構造（`title`、`authors`、`body`〈Sec の木〉、`fns`、`refs`、`abstract`、`apps`…）、`paras`（src → Para）、`region`（src → 領域）、`locations`（src → 人が読む位置）、`exclusions`、`decisions`、`floats`（FloatInfo）、`textboxes`（BoxInfo）、`figures`/`tables`/`formulas`、`body_seq`、`float_unlinked`（リンクしなかった図・表の参照。`UnlinkedRef`〈図か表, 段落 ID, 文字, 段落の中の範囲〉）、`fn_guess_checks`・`fn_guess_numbered`・`fn_guess_span`（文字から推定した「注」の扱い。要確認 `fn_guess`。`fn_guess_span` は「注見出し」にしたとき注の節に入る段落、`fn_guess_notes` は文字から注の見出しと推定した「注」の段落 ID）、`structure_conflicts`（`StructureConflict` の一覧。K1・K2。あれば pipeline が中止）。`fn_table_paras()`（注の節の中の表のキャプション・セルの段落 ID。linker が注番号をリンクしない） |
| `article` のノード | structure | builder, report | `Sec`、`PNode`、`ListNode`、`QuoteNode`、`FigNode`、`TableNode`、`FormulaNode`、`BoxNode`、`FnNode`（`tables`: 注の節の中の表 `[(k, TableNode)]`。builder が k 段落目の後ろに `<p><table-wrap>` で書く）、`RefNode`、`BackSec`、`AppNode`、`Author`、`Aff` |
| `article.StructureConflict` | `structure.Classifier`（`replace_back`・`aff_conflict`） | pipeline（中止・AI の後の組み直し）, report（`structure_conflict_text`）, `structure.conflict_overrides` | そのまま組み立てると段落の文字が出力にも除外にも入らなくなる構造。`kind`（ref_heading / fn_heading / notes / ack / abstract_heading / aff）、`lost`（落ちる段落 ID）、`by`（置き換えた段落 ID）、`where`（aff の loose / table）、`by_text`（見出しが文字からの推定か）、`between`（間に別の種類の後付けの節があるか。直し方の文を変える） |
| `model.Decision` | `plan.decide()`（structure・linker・ai_assist） | report | 機械処理・AI の判断の記録（did は M-001 / A-001） |
| `model.Exclusion` | `plan.exclude()`/`exclude_blank()`、builder | fidelity, report（6 章・要確認 `excluded_unsure`・要対応 `abstract_missing`）, pipeline.lost_images | 出力しない段落の ID・理由・全文。`blank` は空白だけの段落。理由は `structure` の定数で、位置を決められない理由は `structure.UNPLACED_EXCLUSIONS` |
| `linker.Linker` | `linker.link` | pipeline, ai_assist, report | `count`（リンクの数）、`unresolved`（リンク先が見つからなかった参照）・`held`（機械の判断でリンクしなかった参照。AI 依頼文だけに使う）。どちらも `linker.Unresolved`（段落の中の範囲 `start`・`end` と表記 `context` つき。先頭の 6 つは前の組と同じ並び）、`note_style`/`bare_notes`、`float_numbers`（図・表の番号 → ID、リンクしない番号〈重なる・枝番つき〉、枝番の有無）。リンクしなかった参照は `_unlinked` が判断の一覧と `plan.float_unlinked` に記録 |
| `ai_assist.AIOutcome` | pipeline | report, colab, app | `mode`/`provider`/`model`、`raw`（回答）、`accepted`/`rejected`（操作と Decision・理由）、`notes`、`error`、`cut`/`partial`（途中で切れた回答） |
| lxml の木 + `builder.BuildInfo` | `builder.build` | fidelity, pipeline, report | `slots`（出力した画像の置き場所〈`article.ImageSlot`〉。XML の順）・`slot_names`（幹 → 名前）、`exclusions`（builder 側の除外）、`drops`、`notes`、`newlines`、`unsplit_names`、`name_splits`（確かめてもらう和文の著者名の分け方〈`builder.EasternSplit`〉。要確認 `name_split`・AI 依頼文）、`warnings`、`tables`（出力した表〈`<table>` の要素・`model.Table`・Word で探す手がかり〉。`table_problems` が使う）、`unshown_numbers`（番号を出さなかった題目・副題・著者名・所属の段落。10 章の警告） |
| `model.LostImage` / `LostNumber` / `PuaChar` / `TableProblem` | `pipeline.lost_images` / `lost_autonums` / `pua_chars` / `table_problems` | report（9 章・8 章・12 章と要対応） | 画像を入れる場所を作れなかった画像、XML に番号が出なかった自動番号の段落（`src`・`number`・`location`・`where`〈文字を出した要素〉・`text`）、形の崩れた表（`tid`・`where`・`name`・`problems`）、最終の XML に残った私用領域の文字（`PuaChar`: `src`・`code`・`generated`・`font`・`where`・`count`） |
| `fidelity.FidelityResult` | `fidelity.verify` / `final_check` | pipeline（Result.ok）, report（5 章） | `ok`、`mismatches`、`missing`、`duplicates`、`stray`、`conflicts`、`bad_excluded`、`final_ok`、`final_unreadable`（最終出力が XML として読めない・実体の宣言がある）、`final_differs`（最終出力の文字が検証済みの木と違う） |
| `pdfmatch.PdfCheck` | `pdfmatch.check_pdf` | pdfdocx, report（13 章）, pipeline | `diffs`（TextDiff）、`unmatched`、`width`/`drops`/`numbers`（(A) の直し）、`drop_basis`（`drops` の空白の根拠の全角・半角の直しまたは番号）、`ignored_lines`、`case_srcs` |
| `pdfdocx.DocxFix` | `pdfdocx.make_fixed_docx` | pipeline, fidelity.verify_supplement, report | `path`（補った docx。入力が同名なら `_2` などの別名）、`fixes`（Fix の一覧。applied / reason。`Fix.group`＝1 つの違いを分けた組〈双方向〉、`Fix.needs`＝空白の削除が従う根拠の全角・半角の直し〈片方向〉）、`check`（照合の結果） |
| `fidelity.SupplementResult` | `fidelity.verify_supplement` | pipeline, report（13.8） | 補完の確かめの合否と問題 |
| `pipeline.Result` | `pipeline.convert` | report, cli, colab, app | 上のすべてを束ねたもの。`ok`（3 つの検証の合格）、`needs_action`（要対応があるか。`report.actions` から決まる）、出力ファイルのパス。守りの結果は `lost_images`（画像を入れる場所を作れなかった画像）・`image_problems`（XML の画像の名前の不具合）・`decorations`（飾りの図形。`model.Decoration`）・`table_problems`（形の崩れた表）と `tables_checked`（形を確かめた表の数。12 章）・`lost_autonums`（XML に番号が出なかった自動番号の段落）・`unshown_numbers`（番号を出さなかった題目・著者名・所属の段落。10 章）。ほかに `images`（`images.SlotImage`。画像の置き場所ごとの状態〈missing・user・skipped・unused〉と入れた画像の元のファイル名・形式・大きさ）、`xml_base`（置き場所をすべて書いた XML）、`zip_issues`・`not_zipped`、`supplement`（ルート2）など |
| `report.Action` | `report.actions(res)` | report（冒頭・14 章）, colab（枠）, cli（標準エラー）, pipeline（終了コード） | `level`（NEEDS_ACTION / TO_CHECK / STEP）、`key`、`top`、`checklist`、`box_title`/`box_detail`、`cli`、手順だけ `required`/`done`/`failed`/`progress`。止める知らせは `report.blocking(acts)` |

### 段落 ID（`src`）

docx の `w:p` の出現順に `ooxml.paragraph_ids` が振る（本文 `d1, d2, …`、脚注 `f1…`、文末脚注 `e1…`）。読み取りと検証が同じ番号を使うので、
XML の `<jx:span src="d12">` から docx の段落に戻れる。段落記号の削除でつないだ段落は、連鎖の最初の ID だけが残り、後ろは欠番。
図形の ID は `s1, s2…`（浮動配置。`model.Float`）、テキストボックスは `x1, x2…`（`model.TextBox`）、画像は `img1…`、表は `t1…`。
XML の要素の ID は `structure.Classifier.assign_ids` が付ける: 図 `F1`、表 `T1`、数式 `FD1`、注 `fn1`、文献 `B1`、所属 `aff1`。

---

## 3. 各モジュールの役割と入口

行数は W1 の手順 16 の時点（0.31.1 の上の作業中のもの。`wc -l`）。「入口」は、ほかのモジュールから呼ばれる主な関数。

### 基盤

| ファイル | 行 | 役割 | 入口 |
|---|---|---|---|
| `ooxml.py` | 605 | docx の低水準処理と**文字ポリシー**（何が docx の文字か）。`DocxPackage`（zip を開いて `mc:AlternateContent` を前処理。採る側は `choose_alternate`〈Requires を名前空間に解決。読める一覧は `UNDERSTOOD_NS`。記号の挿入 `w16se:symEx` は Fallback の文字〉）、`HiddenRule`（隠し文字の判定。styles.xml から作る）、`joined_paragraphs`/`unjoined_deleted_marks`（段落記号の削除でつなぐ段落）、`canonical_text`/`canonical_texts`（検証用の文字の取り出し。読み取りとは別実装）、`FIELD_DRAWN`・`resultless_field_kind`（結果を持たないまま終わるフィールドのうち、Word では表示のある種類。読み取りが記録して要確認で知らせる）、`sym_char`・`symbol_char`・`w_t_text`・`map_symbol_text`（記号フォント〈Symbol・Wingdings 系〉。フォントごとの表 `SYMBOL_TABLES`。`w:sym` と、記号フォントのランの `w:t` の私用領域の文字を Unicode にする。読み取り・検証・ルート2 が共有）、`in_deleted_run`（削除の変更履歴の中の図形の段落を欠番にする判定。読み取り・検証・ルート2 が共有） | `DocxPackage`, `HiddenRule`, `choose_alternate`, `canonical_texts`, `joined_paragraphs`, `paragraph_ids`, `in_deleted_run`, `SYMBOL_TABLES`, `symbol_char`, `w_t_text` |
| `model.py` | 437 | 中間表現の型（上の表）。`note_key`/`note_label`（Word の脚注・文末脚注の鍵「footnote:5」）。守りの結果の `LostImage`・`LostNumber`・`PuaChar`・`TableProblem`、記号フォントの私用領域の符号の扱い `SymbolReplaced`、反映しない Word の画像の加工の名前 `IMAGE_EDITS` | 型 |
| `config.py` | 245 | `JournalConfig`（`data/jasme.toml`。誌名・ISSN・DOI 形式・スタイル名の対応〈英文要旨は「英文要約見出し」「英文要約」の別名も〉・原稿種別・冒頭の誌名行 `front_lines`〈`structure.front_decoration` が装飾として知らせずに除く〉）と `ArticleMeta`（記事ごとの書誌情報。`from_dict` が巻・号・ページを NFKC にして確かめ、日付を `_date` で読む） | `JournalConfig.load`, `ArticleMeta.from_dict`/`load`, `article_id`, `doi_value` |
| `tracking.py` | 28 | 変換中の目印の名前空間（`jx:span`、`jx:drop`、`jx:gen`〈kind が autonum なら `src` に番号の段落 ID〉、`jx:implicit`、`jx:o`、`jx:ai`） | 定数 |

### 読み取り

| ファイル | 行 | 役割 | 入口 |
|---|---|---|---|
| `docx_reader.py` | 1055 | docx → `Document`。`Reader.read` が document.xml の `w:body` を `read_block` で順にたどる（段落 `read_paragraph`、表 `read_table`、`w:sdt`/`w:customXml` は `_children` で中身をたどる）。`_walk`/`_run` がランをアトムにし、ハイパーリンク・フィールド・変更履歴・隠し文字を扱う。`_graphic` が画像（DrawingML・VML・OLE）と図形（`_new_float`・`_new_textbox`。テキストボックスの中の段落・表は `_read_nested_*`）を記録し、画像の位置を記録する（Word のトリミング・回転などの加工は読まない。画像は書き出さないため。1 つの `w:drawing` に `pic` が複数あるときの大きさは `pic` の `a:xfrm/a:ext` にグループの縮尺を掛ける）。画像ごとに `draw_id`・`para_src`・`digest`〈画像ファイルの SHA-1。ファイルがなければ図形の XML から文字・位置・ID と名前を除いたものの SHA-1。`_xml_digest`〉を記録し、画像を持たない図形のうち、枠・白い四角・線や矢印・文字の図形だけのグループは `ImageRef.decoration` に種類を記録する（`shape_decoration`。画像の位置に数えない図形。まだ構造・出力では使わない）。`draw_id`・`digest` は画像の置き場所の単位と名前の幹に使う（`structure.Classifier.assign_slots`・`slot_keys`）。表は `w:gridSpan`（`_grid_span`。0・負・数でない値は 1）と行の `w:gridBefore`・`w:gridAfter`（`_grid_skip`）・行の番号を読む。`read_notes` が脚注・文末脚注。`read_styles`/`read_layout` | `read_docx(path) -> Document` |
| `numbering.py` | 287 | numbering.xml から自動段落番号の表示文字列（`Numbering.label`）。箇条書きの記号は段の書式のフォント（`w:rPr/w:rFonts`）の表で Unicode にする（`bullet_text`。`Numbering.replaced`）。`w:lvlOverride` の `w:lvl`（段の定義の上書き。書かれた子要素だけを abstractNum の段に重ねる）、ローマ数字・英字・漢数字。数えは abstractNum ごと（同じ abstractNum を使う num は番号を共有する）で、`w:startOverride` はその num の初出で振り直す（`label`。C008）。削除された行を読み飛ばすときの数え方の退避と復元は `snapshot()`・`restore()`。`w:numStyleLink` は styles.xml の番号付けスタイルをたどる（`Numbering(root, styles_root)`・`_follow_style_links`） | `Numbering`, `format_number`, `bullet_text` |
| `omml.py` | 407 | OMML → MathML 2.0（`OmmlConverter.convert`）。属性で表される記号は `jx:implicit`、順序が入れ替わる文字は `jx:o`。`math_plain`（数式の文字だけ）。根号は `m:deg` に文字があれば `degHide` でも `mroot`（`h_rad`） | `OmmlConverter`, `omml_to_mathml`, `math_plain` |

### 構造

| ファイル | 行 | 役割 | 入口 |
|---|---|---|---|
| `article.py` | 513 | `ArticlePlan` とノードの型、スタイルを確かめる段落 `StyleSuspect`（`plan.style_suspects`。検出は修正計画の単位 D。W8 の手順 8 は入れ物だけ）、`FloatInfo`/`BoxInfo`、画像の置き場所 `ImageSlot`（`plan.slots`・`plan.slot_of`・`FigNode.slot`）、`StructureConflict`（K1・K2）、`fn_table_paras`、`plan.decide`（段階ごとの件数を持ち O(1) で番号を付ける）/`exclude`/`exclude_blank`/`float_place`/`box_place`/`no_link_paras`、`float_unlinked`・`fn_guess_checks`・`fn_guess_numbered`・`fn_guess_span`・`fn_guess_notes`。規則は置かない | 型 |
| `structure.py` | 3773 | 段落の役割の決定と構造の組み立て。`classify(doc, journal, overrides, placements)` → `Classifier.run`。流れ（冒頭の docstring に目次）: ① `role_of`（AI の指定 → スタイル → 推定）② `split_regions`（和文の冒頭 / 本文 / 後付け / 英文の部分）③ `build_front_ja`（題目・著者・所属）④ `build_body`（`place_floats` 浮動配置の図表〈中身は AI の指定の有無にかかわらず `float_units` が組む。AI の指定は位置 `after` だけを使う〉、`place_boxes` 文字だけのテキストボックス、`assemble_floats` 図表・箇条書き・引用・別行数式に組む〈図形の外の図キャプションの図は `figure_units`。近くの段落に結び付いたキャプションのないグループ図形は、図形ごとその図に含めて図キャプションの位置に置く `take_float`（`FloatInfo.mode` が caption）。本体の表のない表キャプションの後ろの画像だけの段落は画像で貼った表〈`table_image_paras`。`float_units` も同じ〉〉、`nest` 章節項、`compute_locations`）⑤ `build_back`（付記・謝辞・注・引用文献。注の節の中の表は `FnNode.tables` に入れ、注に入れられない表は位置を決められない除外）⑥ `build_front_en`（英文題目・著者・要旨・資料。後で `pair_app_figures` が資料の図キャプションを隣の画像と組む）⑦ `attach_word_notes`（Word の脚注・文末脚注を通し番号の注に）⑧ `assign_ids`（最後に `assign_slots` が画像の置き場所〈`ImageSlot`。表のセルの図キャプションの置き場所は `cell_figures_in`〉と名前の幹〈`slot_keys`〉を決め、図形ごとの図・表の節 `FloatInfo.nodes` を入れる。要素の木のたどり方は `plan_figures`。図・表の一覧はモジュールの関数 `figure_rows`〈`article.FigureRow`〉）⑨ `joined_styles`。②では、本文スタイルの「注」だけの段落を文字から注の見出しと推定して後付けに切り替えた後、見出しのスタイル（sec1〜sec3）の段落が資料の見出し以外で現れたら本文に戻し、要確認 `fn_guess` の材料（`plan.fn_guess_checks`・`fn_guess_numbered`）を記録する（`check_fn_guess`。ブロックの識別は `block_id`）。「注見出しにすると注の節に入る段落」（`plan.fn_guess_span`）は、推定した「注」ごとに `feed_fn_span` が、その「注」を「注見出し」スタイルにしたときの `build_back` と同じ規則（別の「注」は見出しとして数えない）で数える。⑤の付記・謝辞・資料の自動番号の段落は `add_back_para` で `ListNode` にする。図表のキャプションの番号と枝番は `caption_label`・`RE_CAP_BRANCH`（区切り `CAP_BRANCH_SEP`・数字 `CAP_BRANCH_NUM` は builder・linker が共有）で読む。本文の外の段落に結び付いた図形があれば 2 回組み立てる（`Classifier.outside`）。正規表現（`RE_FIGCAP`、`RE_TABCAP`、`RE_APPENDIX` など）と除外の理由の文言（定数 `FRONT_DECORATION_EXCLUDED`・`FRONT_OTHER_EXCLUDED`・`BACK_TABLE_EXCLUDED`・`EN_OTHER_EXCLUDED` など。位置を決められない理由の集合 `UNPLACED_EXCLUSIONS`、英文の部分の理由 `EN_PART_EXCLUSIONS`）もここ。`front_decoration`（冒頭部の装飾・誌名行か）、`abstract_missing_srcs`（英文要旨が 1 段落もないときの英文の部分の除外。report と ai_assist が共有）。構造の衝突（K1・K2）: `replace_back`（後付けの見出し・英文要旨の見出しの上書き。空白だけの見出しは前でも後ろでも空白の除外）・`_back_between`・`aff_conflict`（著者名の付かない所属。段落と著者表の 2 経路）が `plan.structure_conflicts` に記録し、モジュールの関数 `conflict_overrides`（AI の後の組み直しで使わない set_role の範囲）を pipeline が使う | `classify`, `float_caption`, `float_targets`, `figure_rows`, `appendix_heading`, `conflict_overrides`, `abstract_missing_srcs` |
| `floats.py` | 193 | 浮動配置の図形の位置の判定（`at_anchor`: 機械的に置けるか）、AI に渡す説明（`describe`）と行数の推定（`para_lines`, `box_lines`）、文字だけのテキストボックスが囲みか注記か（`textbox_kind`。しきい値 `BOX_CHARS` など） | `at_anchor`, `textbox_kind`, `describe` |

### リンク

| ファイル | 行 | 役割 | 入口 |
|---|---|---|---|
| `linker.py` | 728 | 機械的リンク。`Linker.run`: 数式のラベル → 段落ごとに Word のハイパーリンク・URL/DOI・図表の参照（`float_refs`）・数式の参照（`eq_refs`）・注の参照（`fn_marks`。上付きの種類分け `_sup_marks`、論文の注番号の書き方 `note_style`）→ 引用（refparse）。`apply_span` がアトムに LinkSpec を付ける唯一の共通関数（リンクが重なる・数式をまたぐときは付けない）。`unresolved` にリンク先のない参照、`held` に判断でリンクしなかった参照を `Unresolved` で記録（段落の中の範囲つき。W8 の手順 15）。図・表の番号が重なる・枝番つきのキャプションの番号は `float_numbers` でリンク先から外し、その参照と枝番つきの参照（`RE_BRANCH_REF`）はリンクせず `_unlinked` が記録する（K4）。`body_paragraphs` は図・表の `caption_more`（2 段落目以降）も文脈 `caption` で返し、注の節の中の表（`FnNode.tables`）も返す（注番号はリンクしない。`Linker.fn_table`） | `link(plan, ref_doi) -> Linker`, `apply_span`, `find_in_para`, `occurrence_at`, `cited_refs`。AI のリンクの text が段落の文字と全角・半角だけ違うときは `find_width_insensitive` が 1 か所に決まるときだけ範囲を返す（C141。W8 の手順 26） |
| `refparse.py` | 427 | 引用文献の解析（`parse_entry`: 著者・年・題名・誌名・DOI）と、本文の著者・年方式の引用の抽出・照合（`extract_citations`, `match_citation`〈同じ第一著者・同じ年の候補は、いちばんよく当てはまる候補が 1 つのときだけ採り、2 つ以上なら「特定できない」〉, `link_citations`）、番号方式（`link_numeric`）。NFKC で照合して元の位置に戻す。文献の `<year>`・論文名・誌名のタグ（`tag_reference`）は、年の位置を `Mapped`（1 文字ずつ NFKC）の上で探し直して戻し、戻した範囲が年の形でなければ付けない | `link_citations`, `tag_reference`, `link_numeric` |

### AI 補完

| ファイル | 行 | 役割 | 入口 |
|---|---|---|---|
| `ai_assist.py` | 1788 | ① 依頼文 `build_request` → `AIRequest`（【作業する方へ】`human_text`〈手動だけ〉・指示の部分 `request_instructions`〈出す節と番号は `request_sections` の 1 か所で決める。API の system は `system_text`〉・データの部分。手動は `manual_text`。データの部分 `_data_lines`: 論文の段落の節 `paper_sections`〈行の書き方 `DATA_RULES`・「## スタイルの一覧」`style_names`・冒頭・本文・後付け・注・引用文献・英文の部分。段落の行 `para_line`〈`[段落 ID]〔スタイル名〕文字`。本文のスタイル `body_style` は〔 〕を書かない。⟦番号: …⟧・⟦脚注⟧・⏎。画像の印は書かない。`para_view`〉、表 `table_lines`〈参照らしい文字のあるセル `cell_has_ref` だけ〉。W8 の手順 14〉、図表式の一覧 `figure_list`。「# 機械がリンクできなかった箇所」`unresolved_section`〈`unresolved_line`: 段落の表記と何回目か〉・「# スタイルを確かめる段落」`suspect_section`・「# 出力から除いた段落」`exclusion_section`・「# 姓と名の区切りを確かめる氏名」`names_section`〈和文だけ〉。W8 の手順 15。「# 位置を決める図・表」`float_section`〈図形ごとに「中身」`float_contents`〈変換ツールが組んだ図・表を ID とキャプションの段落で書き、画像の ID は書かない〉・仮の位置・docx の配置〈`floats.describe`。日本語〉・推定〈`floats.estimate_top_left`。「## 本文」にない段落は `listed_before` で前の段落に読み替える〉。位置が決まっている図形は ID だけ〉、テキストボックスの 3 つの節 `textbox_section`、答えない中身の節 `fixed_section`。after に書ける段落は `after_ids`〈`AIRequest.asked` の after〉。W8 の手順 16。docx の画像は AI に渡さない〈W1〉）② 呼び出し `call_provider(provider, system_text, data_text, attachment, …)`〈attachment は出版版 PDF `PdfAttachment`。`pdf_attachment` が事前に確かめる〈30 MB・100 ページ・開けるか〉。4 社とも依頼のデータの前に渡す〈Claude は document、ChatGPT は `input_file`＋`store=False`、Gemini は `Part.from_bytes`、Sakana AI は Namazu の 4 MB 以下なら PDF・ほかは先頭 40 ページの画像。`pdf_will_be_sent`〉。断られたら〈400・413〉PDF なしで 1 回だけやり直す〈Sakana AI は PDF → ページの画像 → なし の順で、JSON スキーマを外すやり直しより先〉。渡した方法は `AIOutcome.pdf_sent`、理由は `pdf_note`。W8 の手順 20・21〉 → `call_api`（Claude。構造化出力・ストリーミング。モデルがなければ `latest_opus`）/ `call_openai` / `call_gemini` / `call_sakana`（どれも system に指示、利用者の内容にデータ） ③ 回答の読み取り `parse_response`（回答の形は `RESPONSE_SCHEMA`: `request_id`・`pdf`・種類ごとの一覧 `ANSWER_LISTS`〈placements・boxes・boundaries・links・names・style_fixes〉・`notes`。修正計画 W8 の手順 10。最初の `{` から最後の `}`。最上位が一覧〈`[ ]`。`_top_level_array`〉の回答、回答の項目のない回答、一覧でない項目、入れ子が深すぎる回答〈`RecursionError`〉は読めない回答にし、それぞれの文〈`TOP_ARRAY_MSG`・`SINGLE_OP_MSG`・`NO_OPS_MSG`・`OPS_NOT_LIST_MSG`・`DEEP_MSG`〉を出す。`operations` を持つ前の形の回答〈`OLD_FORM_MSG`〉・依頼文そのもの〈行頭の「# 依頼」「# 論文（ここから下はデータ）」。`RE_REQUEST_HEADING`〉・`{` で始まるコードブロックが 2 つ以上・見本の写し〈値がまるごと「＜…＞」。`RE_SAMPLE_VALUE`・`_copied_sample`〉の回答は回答全体を断る。戻り値はどの一覧もそろえた dict〈`_answer_data`〉）、途中で切れた回答 `parse_cut_response`（最後まで書かれた placements の要素だけ。最上位が一覧のもの・深すぎるもの・前の形のものは読まない） ④ どの依頼文への回答か `check_answer`（依頼の番号 `request_stamp`〈R-構造の印-本文の印。`structure_lines`〉と比べ、構造の印が違う・番号のない回答は使わない。段落を指す項目の head が合わなければ、同じ先頭の文字の段落が 1 つだけなら読み替える〈`AIOutcome.reread`〉。本文の印だけ違えば `AIOutcome.carried`。W8 の手順 17）⑤ 検証と適用（種類ごと。要素は `_items` が型を確かめ、`{ }` でない要素・文字列にできない項目は理由付きで不採用に記録する。段落を指す項目は先頭の文字〈`head_key`・`head_of`・`same_head`。合わなければ `HEAD_WHY`〉で確かめる）: `read_answer_meta`（request_id・pdf を `AIOutcome` に写す）、`pdf_seen`（AI が出版版 PDF を見て答えたかをツールが確かめる。位置を反映した後に pipeline が呼び、`AIOutcome.pdf_seen`・`pdf_seen_note` に入れる。ページ数と、キャプションが PDF の 1 ページだけに見つかる図形の `FloatInfo.page` を比べる。合わなくても位置は使う。W8 の手順 22）、`link_ops`・`name_ops`（今の操作の形に写す。氏名は依頼文に挙げた和文の氏名 `asked_names` だけ）、`style_fixes`（提案 `AIOutcome.style_fixes`。XML には反映しない。決定 5）、`boundary_overrides`（`boundary_problem` で可否。注の区切り・資料の始まりの 5 つを上書き表と `AIOutcome.boundaries` に入れる）、`float_placements`（`_placement_problem`。after が "" か本文の外の段落の答えは `after_body` で、採用して指定に where end。W8 の手順 11）・`box_kinds`（`_box_placement_problem`）、`missing_answers`（聞いたのに答えのない図形・テキストボックスを「指定なし」で記録。C079）→ classify をやり直す（pipeline）→ `record_boundaries`（反映した区切りを採用に記録）→ `retarget_ops`（ID の読み替え）→ `apply_ops`（link_* / split_name の検証。題目・著者名・所属・引用文献・別行数式の段落へのリンクは不採用。AI が付けた図表のリンクは、範囲が重なる参照だけ `plan.float_unlinked` から除く）。`notes` は `_notes_list`。数式の画像の書き起こし〈formula_image〉は W8 の手順 12 でなくした。依頼文の指示の文の定数（`RULES_TEXT`・`PLACEMENTS_TEXT` など）、`RESPONSE_SCHEMA`、`DEFAULT_MODEL`/`DEFAULT_MODEL_INFO` | 上のとおり |

### XML の組み立て

| ファイル | 行 | 役割 | 入口 |
|---|---|---|---|
| `builder.py` | 1259 | `build(plan, meta, journal, split) -> (root, BuildInfo)`。`Builder` が `<article>` → `<front>`（journal-meta・article-meta: 題目・著者・所属・日付・要旨・キーワード）→ `<body>`（Sec の木。段落・箇条書き・引用・図 `fig`・表 `table-wrap`・数式 `disp-formula`・囲み `boxed-text`）→ `<back>`（付記 `notes`・謝辞 `ack`・注 `fn-group`・文献 `ref-list`・資料 `app-group`）の順に作る。`word_note_marks`（Word の注の番号）、`finalize`（目印を外す）、`serialize`（DOCTYPE 付きで直列化）。全行が見出し行の表は `thead` を作らず、謝辞 `ack` の中の別行数式・表・リストと注 `fn` の中の表（`FnNode.tables`）は `p` で包み、付記・謝辞・資料の自動番号の段落は `list_node` で `<list>` に書く。Word の自動番号は、段落の先頭の生成文字 `autonum_mark`（表のセル・引用・別行数式・英文要旨・注の 2 段落目以降など）、キャプションの `<label>`（`caption`。`split_labels` にかかわらず）、後付けと英文要旨の見出しの `<title>` の先頭（`heading_title`）に書き、題目・副題・著者名・所属の番号は出さずに `unshown_number` が `BuildInfo.unshown_numbers` に記録する（10 章の警告 `UNSHOWN_NUMBERS_MSG`）。表（`table`）は、縦の結合の結合元を「開始列 → (セル, 幅)」で覚えて行ごとに作り直し、幅の同じ継続だけを結合し（違えば別のセル。10 章の警告 `TABLE_SPAN_MISMATCH_MSG`）、見出し行から本文の行へは結合を延ばさず（`TABLE_HEAD_SPAN_MSG`）、すべてのセルが継続の行は出力せず `rowspan` は出力する行だけで数え、行の前後で飛ばしたグリッドは空のセルで埋める（`_grid_cell`）。出力した表は `BuildInfo.tables` に記録する | `build`, `finalize`, `serialize`, `word_note_marks` |
| `emit.py` | 352 | 段落のアトムを JATS の要素に書く。`Emitter.span` が **文字を書く唯一の経路**（`<jx:span>` の中に、書式・リンクの要素で包んで書く）。`Ctx` が文脈ごとの制限（TITLE・NAME・AFF・REF・CELL・DISPF…: 使える書式、リンクの書き方、xref の可否、画像の可否、`<break/>` の有無、改行を要確認にする名前）。`drop`（空白だけ落とす）、`gen`（生成文字。自動番号には段落 ID の `src` を付ける）、`write_object`（数式・画像・脚注参照）、`with_optionals`・`plain_pos`（任意の置き場所〈結果のないフィールドの位置〉に `<inline-graphic>` を差し込む。文字は変えない） | `Emitter`, `Ctx` と定数 |
| `validate.py` | 49 | 同梱 DTD（`dtd/JATS-journalpublishing1.dtd`）で検証（`resolve_entities=False` なので未定義の実体参照は見つけない。`fidelity.final_check` が補う）。`jats_element_names()` は DTD の要素名（`report.md_tag` が使う） | `validate(xml_bytes, where=None) -> (ok, errors)`〈errors は場所つきの文字列 `DtdError`〉, `group_errors`, `jats_element_names` |
| `jstage_rules.py` | 163 | J-STAGE のアップロード時チェックのうち XML だけで判定できるもの（題目と要旨の言語、日付の前後、所属番号、DOI の文字、画像名など）。`docs/JSTAGE_NOTES.md` | `check(root, aid, image_names) -> [(ID, 内容)]` |

### 検証

| ファイル | 行 | 役割 | 入口 |
|---|---|---|---|
| `fidelity.py` | 688 | ① `verify(docx_path, root, exclusions)`: `source_texts`（ooxml.canonical_texts）と XML の `jx:span` を段落ごとに比べる（欠落・重複・不一致・目印の外の文字 `stray_text`・落とした空白・出力と除外の矛盾・空白のはずの除外に文字）② `final_check(root, xml_bytes, fid)`: 目印を外した最終 XML を読み直して再照合（実体の宣言があれば解決せず不合格。なければ実体を解決するパーサでも読めることを確かめる。`final_unreadable`・`final_differs`） ③ `verify_supplement(original, fixed, fixes, …)`: ルート2 の補完の確かめ（変更履歴の単位 `_mark_runs`/`_unit_ends` を取り出し、(A) は `_pair`、(B) は報告された Fix と照合。pdfmatch とは定数しか共有しない）。`supplement_targets` | 上のとおり |

### PDF との照合（ルート1 の照合、ルート2 の補完）

| ファイル | 行 | 役割 | 入口 |
|---|---|---|---|
| `pdfmatch.py` | 2901 | `check_pdf(plan, pdf_path, fn_marks) -> PdfCheck`。① `extract_pages`（pypdfium2）② `pdf_stream`（空白・ページ番号を除いた文字の列に、柱の候補 `head`・ページの端 `edge`・行全体でしか一致させない行 `line_only`・受付日 `date`・数式の位置 `formula` の印）③ `compare` → `_joint`（全段落をつないで PDF と単調に対応付け、段落ごとの窓を決める）→ `_align`（difflib で段落ごとに照合）→ `_classify`/`_report_regions`（違いを (A) `typeset_pair`/`width`/`drops`/`numbers`、(B) `kind="text"`、(C) `why` に分ける）。`diff_parts`（1 つの違いを直す単位に分ける）。定数表 `QUOTE_CLASSES`・`DASHES`・`HYPHENS`・`NUMBER_PAIRS`・`FW_FIRST/LAST`、理由の文言 `*_WHY` | `check_pdf`, `extract_pages`, `pdf_stream`, `typeset_pair`, `diff_parts` |
| `pdfdocx.py` | 860 | `make_fixed_docx(docx, pdf, out, journal) -> DocxFix`。元の docx を読んで照合し（`_mechanical` → `check_pdf`）、`plan_fixes` で段落ごとの Fix（kind width / space / glyph / text）を決め（空白の削除 `space` は `Fix.needs` で根拠の `width` に片方向で従い、`spread_reasons` が「直さない」を不動点まで広げる。1 つの違いを分けた組は `FixGroup`・`link_fixes` で双方向）、`_Writer` が元の XML（前処理しない木）のランを分けて `w:del`/`w:ins` を書き込む（`paragraph_units`/`raw_paragraph_ids` が読み取りと同じ文字ポリシーで段落を特定）。書いた後に `_verify`（読み直した文字が期待どおりか）と `_structure`（役割・領域・リンク・注の区切り〈注の節の表の形も〉・著者数が元と同じか）で確かめ、合わない段落は直さずに作り直す | `make_fixed_docx`, `paragraph_units`, `tracked_counts`, `same_file` |

### 出力

| ファイル | 行 | 役割 | 入口 |
|---|---|---|---|
| `images.py` | 170 | 作業する人が入れる図・表の画像の受け取り（docx の画像は書き出さない。W1）。`check_user_image`: 入れられた画像の中身を確かめる（PNG・JPEG・GIF だけ。向き・圧縮・透過を変えず、そのままのバイト列を使う。幅と高さは Pillow で読むだけ）。`SlotImage`（置き場所 1 つと入れた画像の状態）・`KeptImage`・`DroppedImage`・`ChangedImage`（変換し直しの持ち越しの記録）。`match_names`: アップロードされたファイル名を、幹・図番号・記事識別子つきの名前で置き場所に合わせる | `check_user_image`, `SlotImage`, `match_names`, `KeptImage`, `DroppedImage`, `ChangedImage` |
| `imagelist.py` | 175 | 取り違えの確かめの一覧（`{記事識別子}_図の確かめ.html`。出力フォルダの記事フォルダの外に書き、ZIP に入れない）。行のデータは `report.image_rows` で、ここは見せ方だけ。`check_html(res, embed=False)`（`embed` で縮小した画像を埋め込む）・`write_check(res)`（変換・`rebuild_outputs` のたびに書き、`Result.check_path` に持つ） | `check_html`, `write_check`, `check_name` |
| `package.py` | 224 | J-STAGE のフォルダ構成（`jasme/巻/号/記事識別子/`）と ZIP。`upload_entries` が ZIP に入れるものを決める唯一の場所。`zip_problems`（ZIP を読み直して EMSGM034E/053E/059E/073E/074E など。画像の置き場所を渡すと、置き場所にない名前の画像と、入れたのに ZIP にない画像も）、`unzipped_files`（入れなかったファイル） | `write_package`, `make_zip`, `zip_problems`, `unzipped_files`, `article_dir` |
| `report.py` | 3804 | 変換レポート（Markdown）`render(res)`: 冒頭の要約 → 1 結果の要約 → 2 AI → 3 解決できなかった箇所 → 4 機械的な推定 → 5 不変性チェック → 6 出力しなかった文字 → 7 落とした空白 → 8 生成文字 → 9 画像 → 10 警告 → 11 書誌情報 → 12 DTD と J-STAGE チェック → 13 PDF との照合（`render_route1`/`render_route2`）→ 14 登載前のチェックリスト。`render_ai_only`（AI 判断一覧）。**`actions(res)`** が利用者への知らせ（要対応・要確認）を `Action` の一覧にする唯一の場所（`_fidelity_action`、`_dtd_action`、`_table_shape_action`〈key `table_shape`〉、`_upload_action`、`_ai_finish_action`〈推奨の手順 `ai_finish`。状態は `ai_state`・`ai_done`〈位置を聞く図形があれば、AI が PDF を見たこと `pdf_unseen` が偽であることも要る〉・PDF の表示 `ai_pdf`、見ていないときの文 `_ai_pdf_unseen_action`、方法の表示は `ai_method`・`ai_summary`。W8〉、`_float_end_action`〈要確認 `float_end`。W8〉、`_style_check_action`〈要確認 `style_check`。機械が挙げた段落 `plan.style_suspects` と AI の提案 `AIOutcome.style_fixes` を 1 つに。行は `style_check_rows`。W8〉、`_ai_boundary_action`〈要確認 `ai_boundary`。AI の回答で直した注の区切り・資料の始まり `AIOutcome.boundaries`。W8〉、`images_action`、`lost_action`、`lost_autonum_action`〈key `autonum_lost`〉、`_unplaced_action`〈key `excluded_unsure`。理由ごとの直し方 `UNPLACED_GUIDE`〉、`_abstract_missing_action`〈key `abstract_missing`〉、`_style_hidden_action`、`_newline_action`、`pdf_actions`…。並びは 4 章の「利用者への知らせの経路」）。8 章に XML に番号を出せなかった段落の表、12 章に「表の形の確かめ」の節を出す。6 章の理由の列には、位置を決められない除外に「（要確認）」、英文要旨が見つからないときの除外に「（要対応）」を添える。構造の衝突で中止するときの文 `structure_conflict_text`（衝突ごとに段落 ID・抜粋・Word での直し方。`actions` の知らせではなく `StructureConflictError` の文）。`image_rows`, `images_progress`（用意が必要な画像）。画面の操作は目印 `step()`（`STEP_NAMES`）で書く（`colab.step_text` が画面ごとの語に置き換える）。レポートの生のタグは `md_tag()` で囲む。0.29.0 で `_float_ref_action`（key `float_ref`。手で足す方法 `float_ref_manual`。AI の状態で文を分けた `float_ref_ai` は W8 の手順 7 でなくした）と `_fn_guess_action`（key `fn_guess`）を、0.30.0 で `table_shape`・`autonum_lost` を（`image_crop`・`image_edits` は W1 でなくした）、0.31.0 で `excluded_unsure`・`abstract_missing` を足した | `render`, `actions`, `image_rows`, `images_progress`, `upload_issues`, `pdf_summary`, `structure_conflict_text` |

### 流れと画面

| ファイル | 行 | 役割 | 入口 |
|---|---|---|---|
| `pipeline.py` | 1292 | `Options`（出力先・AI の方法・PDF・ルート）、`Result`、`convert`（4 章）、`add_images`（利用者の画像を入れて ZIP とレポートを作り直す）、守り `lost_images`（置き場所をすべて書いた `xml_base` の木で、画像の置き場所を作れなかった画像）・`image_problems`（最終の XML の画像の名前）・`decorations`（飾りの図形の記録）・`table_problems`（出力した `<table>` の形を、builder の結合の判断に頼らず、docx の行ごとの列の数と HTML の表の割り当てだけで確かめる）・`lost_autonums`（文字を出したのに番号の `jx:gen` がない自動番号の段落）、`fixed_docx_path`（補った docx の書き出し先。入力が同名なら `_2` などの別名）と `_drop_fixed`（中止のとき、この変換が書いた補った docx を消す）、中止の例外 `StructureConflictError`（K1・K2。`plan`・`conflicts` を持つ。変換を中止する例外はこれだけ。AI を使わない設定でも中止しない〈W8〉）、AI の区切りの指定を構造の衝突などで使わないときの `_reject_roles`・理由 `CONFLICT_ROLE_WHY`・`BOUNDARY_LOST_WHY`、`tool_version` | `convert`, `add_images`, `Options`, `Result`, `lost_images`, `table_problems`, `lost_autonums`, `StructureConflictError` |
| `cli.py` | 179 | `python -m jasme_jats` の引数と終了コード（0 要対応なし / 1 要対応あり / 2 中止〈`StructureConflictError` は文を標準エラーに出す〉。`--ai-response` は `--ai manual` のときだけ指定でき、それ以外は引数の誤りで 2）。`--ai api` では出力フォルダの `AI回答.json` を `Options.ai_cache` に読む（`--ai-refresh` で読まない。`--ai api` 以外で指定すると 2）。`images_in`（`--images` のフォルダを `images.match_names` で置き場所に合わせる。合わないファイルは標準エラー）・`image_table`（図の画像の表。見出しは手順 `images` の `progress`）。`--no-image`、`--no-metafile-conversion` はなくした | `main` |
| `colab.py` | 341 | Colab の表示部品（HTML）: 手動モードの案内の枠 `manual_guide`（見出し・説明は `ai_finish` の `Action` の `box_title`・`box_intro`、手順の番号つきの案内、出版版 PDF を添付する案内）と、それにコピーボタンと依頼文を足した依頼文の枠 `prompt_box`（`ai_finish_of(res)` で `Action` を取る。1 画面版は `manual_guide` を結果の枠の並びに出す）、中止の枠 `structure_conflict_box`（赤）、要対応（赤）・要確認（黄）の枠 `result_boxes`（`actions` の順）、要約 `summary_box`（AI による仕上げの行は `report.ai_summary`）、畳んだレポート `report_details`（Markdown → HTML は `markdown_text_only`。生の HTML・実体を無効にして docx の文字の `<`・`&` をそのまま見せる）、続けて変換するときの確認 `same_first_page`/`carried_over`。画面の操作の目印の置き換えは `STEP_WORDS`（`notebook`・`app`・`cli`）と `step_text`（枠を作る関数が `screen` 引数を受ける）。1 画面版の欄・ボタンのラベルは定数 `ANSWER_LABEL`・`APPLY_LABEL`・`CONVERT_LABEL`（`app.py` も使う）。枠は白地に黒の文字に固定し（`LIGHT_STYLE`）、ダークモードでも読める | `result_boxes`, `summary_box`, `report_details`, `prompt_box`, `manual_guide` |
| `app.py` | 852 | 1 画面版（Gradio）。`AppState`（Gradio に依存しない状態: 入力 → `convert` → `waiting_for_answer`/`apply_answer`（手動モード）→ `image_rows`/`match_images`（「まとめて入れる」の名前合わせ）/`add_images`（`skip` は「入れない」）→ `needs_action`/`download` → `reset`）と `build_app(state, io)`（画面）、`launch()`（share は必ず False。Colab では `colab_embed` で iframe に埋め込む）。`answer_box_open`（手動の欄を見せるか。手動モードで作った結果のときだけ、`waiting_for_answer` に加え、AI による仕上げが済んでいない〈`report.ai_done` が偽。回答待ち・失敗・一部〉あいだ。知らせの key では決めない〈以前の `REPASTE_KEYS` は W8 の手順 7 でなくした〉）。中止（`StructureConflictError`）は `_run` が `InputError` にして `structure_conflict_box` の枠で出し（`res` は None のまま、入力の写し `run` は残る）、想定外の例外は `crash(error, operation)` で赤い枠にする（どちらも `report.actions()` の知らせではなく例外の表示）。変換したときの入力の写し `AppState.run`（`RunInputs`。docx・PDF は作業用の場所に写したもの、比べる値 `compared`〈ファイルは中身の sha256。`fingerprint`・`file_digest`〉、作り方・SPLIT_LABELS・AI の方法・モデル・書誌情報・API キー）を `convert` が作り、`_run`・`apply_answer`・`add_images`・`download` はこの写しだけを使う。入力が写しと違えば、前の結果を残したまま理由の文で断る（`changed_inputs`・`stale_text`。「このままダウンロード」でも断る。AI の方法・モデルは比べず、変えたら `settings_note` で次の変換から使うと言う）。手動かどうか（`waiting_for_answer`・`answer_box_open`）も写しで決める（O3）。`convert` は確かめ（足りない項目・入力の誤り・API キー・ファイルを読めない）が済むまで前の結果と写しを変えず、`_run` は Options を作ってから前の結果を捨てる。別の論文（docx の中身が違う）で変換すると回答の欄を空にし（`paper_changed`）、前の論文の回答は、変換の中の依頼の番号の確かめ（`ai_assist.check_answer`）が使わない（W8 の手順 18 で、前の「前に反映したのと同じ文字の回答を断る」`_last_answer` から置き換えた）。API モードの回答の写し（`AI回答.json` の中身）は `AppState.ai_cache` に持ち、`Options.ai_cache` で渡す（出力フォルダは毎回消す）。変換ボタンの横の文は `ready_text` | `launch`, `AppState`, `build_app` |
| `tools/make_notebook.py` | 618 | 2 つのノートブック（従来版 9 手順、1 画面版 1 セル）を生成する。手順 5 は中止の例外（`StructureConflictError`）を、手順 6 は `StructureConflictError`（守り）を枠で出して `SystemExit` で止める（「済み」に 5 が残らないので手順 6〜8 は `guard` で止まる）。従来版の各手順は、最初に前の手順の「済み」を確かめ（`guard`）、自分と後ろの手順の「済み」を消し（`unmark`）、最後まで済んだら自分を記録する（`mark`）。`REPO`/`BRANCH`/`DOCS`、手順ごとのセルの文字列、`ai_assist.py` から既定モデルを読む `module_constants` | `python tools/make_notebook.py [--branch]` |
| `tools/sanitize_docx.py` | 234 | リポジトリに入れる docx から個人情報を取り除く（lxml で部品を書き直す）。取り除くもの: コメント（comments*.xml・people.xml と本文・脚注・文末脚注のコメントの範囲と参照）、`customXml/`・`docProps/custom.xml`・`docProps/thumbnail.*`、`w:attachedTemplate`（テンプレートのパス）とその関係、ヘッダー/フッターの文字（ページ番号のフィールドは残す）。空にするもの: 文書のプロパティの作成者・最終更新者・題目・主題・説明・キーワード・分類、app.xml の Company・Manager・HyperlinkBase・TitlesOfParts、`w:initials`。変更履歴の作成者は「作成者」（`pdfdocx.AUTHOR` は残す）。入力と同じ出力先は断り（`SAME_FILE_MSG`）、一時ファイルに書いて本文の文字（`fidelity.source_texts`）と画像の名前が同じことを確かめてから置き換える（`CHANGED_MSG`）。残った外部のローカルのパスは警告だけ | `sanitize`, `main`（終了コード 0 成功・1 断った・読めない・2 使い方の誤り） |

---

## 4. `pipeline.convert()` の段階（0.31.0）

`convert(docx_path, meta, journal, opts) -> Result`。以下の番号は `pipeline.py` の処理順。中止（終了コード 2。構造の衝突だけ）は 1 と 2 の 2 か所で、どちらも AI を呼ぶ前。
位置を決められない図表があっても、AI を使わない設定で中止しない（修正計画 W8 の決定 4。結び付いた段落の後ろか本文の最後に置き、推奨の手順 `ai_finish` で知らせる）。

1. **ルート2 の前処理**（`opts.route == "pdf"`）: まず**補う前の元の docx** で `_mechanical` を行い、構造の衝突（`plan.structure_conflicts`。K1・K2）があれば
   `StructureConflictError` で中止する（補った docx を作らない。O7）。
   続けて `pdfdocx.make_fixed_docx` で補った docx を `pipeline.fixed_docx_path`（`out_dir/{aid}_PDFで補完した原稿.docx`。入力がそのファイルなら `_2` などの別名）に作り、
   `docx_fix.check.ok` なら以降の入力をそれに差し替える。PDF の文字を読めなければ `docx_fix = None` で元の docx を変換する（要対応 `pdf_fallback`）。
2. **機械処理** `_mechanical`: `read_docx` → `classify` → `link`。構造の衝突があれば `StructureConflictError`（中止。終了コード 2。AI の方法にかかわらず
   AI を呼ぶ前に止め、手動モードでも `AI依頼文.txt` を書かない）。
   ルート2 でこの変換が補った docx を書いていれば、中止の前に消す（`_drop_fixed`。1 をすり抜けたときだけ）。
3. **1 回目の組み立て** `build`（AI 依頼文を作るのに BuildInfo の `exclusions`・`unsplit_names`・`name_splits` が要る）。
4. **AI 補完**（`opts.ai_mode` が api / manual）: `build_request`（`AIRequest`）→ API 呼び出し（system に `system_text()`、利用者の内容に `data`）、または `AI依頼文.txt`（`manual_text()`）の書き出しと `--ai-response` の読み取り。
   回答が読めたら種類ごとに検証し（`link_ops`・`name_ops`・`style_fixes`・`boundary_overrides`・`float_placements`・`box_kinds`）、**`_mechanical` をやり直して**（docx を読み直し、区切りの指定と配置を渡して組み立て直す）、
   AI の区切りの指定で構造の衝突ができたら、**2 段で組み直す**: 1 段目は衝突の範囲（`structure.conflict_overrides`）の指定だけを、なお残れば 2 段目は区切りの指定をすべて
   不採用（`_reject_roles`。理由 `CONFLICT_ROLE_WHY`。レポート 2 章）にして `_mechanical` をやり直す（中止しない。その後ろの `StructureConflictError` は届かない守り）。
   続けて `retarget_ops` で ID を読み替え、`apply_ops` でリンク等を適用し、**2 回目の `build`**。
5. **PDF との照合**（`opts.pdf_path` があれば。ルート1 でも）: `check_pdf`。ルート2 で Word が付ける番号の直し（`number_edits`）があれば `plan.pdf_numbers` に入れて **3 回目の `build`**。
6. **検証**: `verify` → `finalize` → `serialize` → `final_check` → `validate`。`validate` には `pipeline.dtd_places`（引用文献・表・注の id → 段落）を渡し、エラーに原因の場所を付ける（AI の数式の取り消しのやり直しは、W8 の手順 12 で数式の書き起こしごとなくした）。
7. **補完の確かめ**（ルート2 で補った docx があるとき）: `supplement_targets` → `verify_supplement`。
8. **守り**（どれも最後の組み立ての木と `BuildInfo` を使い、変換の結果は変えずに要対応として知らせる）: 画像の置き場所を作れなかった画像 `lost_images`（置き場所をすべて書いた `xml_base` の木で調べる）→
   表の形 `table_problems`（`Result.table_problems`・`tables_checked`。要対応 `table_shape`）→ 自動番号の出力漏れ `lost_autonums`（`Result.lost_autonums`。要対応 `autonum_lost`）→ 私用領域の文字 `pua_chars`（`Result.pua_chars`。要対応 `pua_left`）と記号の置き換え `symbols_replaced`（`Result.symbols_replaced`。要確認 `symbol_replaced`）。
9. **出力**: `slot_images`（置き場所ごとの `images.SlotImage`。変換の直後はすべて missing〈任意は unused〉。docx の画像は書き出さない）→ `jstage_check` → `write_package`（XML・PDF の配置と ZIP。画像はまだない）→ `out_dir/{aid}.xml`。最終の XML は、検証の段階で `package.apply_images(xml_base, images)` が作る（`final_check`・`validate` はその XML で行う）。画像を入れたとき（`add_images`）は `rebuild_outputs` が同じ確かめをやり直す。
10. **未解決の一覧の整理**: `linker.unresolved` から AI が解決したものを除き、仮に置いた図表・決められないテキストボックスを足す（`unresolved_after`。レポート 3 章）。
11. **`Result` を作り**、レポート（`render`）と AI 判断一覧（`render_ai_only`）を書く。`zip_problems`（画像の置き場所を渡す）・`unzipped_files`・`image_problems`（最終の XML の画像の名前）・`decorations`（飾りの図形）もここで計算する。

`add_images(res, supplied, skip=None)` は、変換の後に利用者が用意した画像を `Graphics/` に入れ（`skip` はキャプションのない画像の「入れない」）、`rebuild_outputs` で XML・ZIP を作り直し、`zip_issues`・`not_zipped` とレポートを更新する。
変換し直すときは、前に `kept_images(res)` で入れた画像を覚え、変換の後に `reapply_images(res, kept)` で同じ図（幹・種類・キャプションの本体・キャプションのない画像は場所）だけ入れ直す。入れなかった画像は `Result.images_dropped`、キャプションが少し変わった図に入れた画像は `Result.images_changed` に記録する。

### 利用者への知らせの経路

```
pipeline.Result ──▶ report.actions(res) ──▶ [Action(level, key, top, checklist, box_title, box_detail, cli), …]
                                              ├─ report.render: 冒頭の文（top）と 14 章（checklist）
                                              ├─ colab.result_boxes: 赤（要対応）・黄（要確認）の枠 ── 従来のノートブックと app.py の両方
                                              ├─ cli.main: 標準エラー（cli）と終了コード（Result.needs_action = report.blocking）
                                              ├─ app.AppState.needs_action / todo_titles: 「ZIP を保存」の前に一度止める
                                              └─ app.AppState.answer_box_open: 手動モードで作った結果（依頼文がある）で、report.ai_done が偽のあいだ手動の欄を見せる
```

`actions()` の並び（修正計画 W8 の手順 8 の後。レポートの冒頭の順）: fidelity, supplement, dtd, table_shape, image_names, upload,
textbox_undecided, textbox_place, textbox_figure_text, excluded_unsure, images, lost, image_same, image_changed, autonum_lost, pua_left, abstract_missing, style_hidden, resultless_field, symbol_replaced, abstract_ja,
app_after_refs, float_end, style_check, ai_boundary, note_overlap, float_ref, fn_guess, name_split, newline、その後ろに `pdf_actions`（PDF との照合の知らせ）。
推奨の手順 ai_finish は、この並びの中の最後の要対応・必須の手順のすぐ後ろに入れる（W8 の前半の点検 review12 で、先頭から移した）。
AI の失敗・途中で切れた回答・手動の回答待ちは、推奨の手順 ai_finish の状態（`report.ai_state`。未実行・回答待ち・済み・一部・失敗）で知らせる（W8 の前の要対応 `ai_error`・`partial`、手順 `ai_pending` はなくした）。

知らせを足すときは `report.py` に `_xxx_action(res) -> Action | None` を作り、`actions()` の並びに加えるだけ（DEVELOPMENT.md の原則 8）。
`box_detail` の画面の操作は目印 `report.step()` で書き、枠を作るとき（`colab._box`・`result_boxes` の `screen` 引数）に `colab.STEP_WORDS` の語
（`notebook`・`app`・`cli`）へ置き換える。変換の中止（`StructureConflictError`。終了コード 2）と 1 画面版の想定外の例外の枠
（`app.AppState.crash`）は、この経路を通らない（例外の表示。中止の文も目印で書き、`colab.structure_conflict_box`〈ノートブック・1 画面版〉と
`cli.py`〈標準エラー〉が `step_text` で語に置き換える）。

---

## 5. ルート2（docx から作り、出版版 PDF で補う）の流れ

```
元の docx ──▶ _mechanical で構造の衝突・位置を決められない図表を確かめる（あれば補った docx を作らずに中止）
          ──▶ pdfdocx.make_fixed_docx
               ├─ _mechanical（read_docx + classify + link。照合に段落の役割・リンク・注の鍵が要る）
               ├─ pdfmatch.check_pdf（PDF の文字を取り出し、段落ごとに照合して (A)(B)(C) に分ける）
               ├─ plan_fixes（段落ごとの Fix。直さない理由 reason も記録）
               ├─ _Writer.run（元の XML のランを分けて w:del / w:ins を書く。脚注・文末脚注の XML にも）
               ├─ _verify（読み直した段落の文字が、期待どおりか）・_structure（役割・領域・リンク・注の区切りが元と同じか）
               │    └─ 合わない段落は Fix を外して書き直す
               └─ DocxFix（path, fixes, check）
補った docx ──▶ convert の 2〜6（ルート1 と同じ）── 5 で Word の番号を PDF に合わせる（plan.pdf_numbers。PDF と照合する段落だけ）
              ──▶ fidelity.verify_supplement（元の docx と補った docx を比べ、変更履歴の単位が (A) か報告した (B) だけか）
レポート 13 章: 13.1 補った校正の直し / 13.2 組版の違い / 13.3 直さなかった箇所と理由 / 13.4 Word の番号 / 13.5 残る違い / 13.6 見つからない段落 / 13.7 照合に使わなかった PDF の文字 / 13.8 補完の確かめ
```

---

## 6. 画面と pipeline の関係

| 画面 | ファイル | 呼ぶもの |
|---|---|---|
| コマンドライン | `cli.py` | `convert` → 結果の表示 → `add_images`（`--images`）→ `actions` を標準エラーへ → 終了コード |
| 従来のノートブック（手順 1〜9） | `notebooks/JASME_docx_to_JSTAGE_XML.ipynb`（`tools/make_notebook.py` が生成） | 手順 1 pip / 2 アップロード / 3 書誌情報 `ArticleMeta.from_dict` / 4 AI の選択 / 5 `convert` と `colab.result_boxes` など / 6 手動モードの回答を貼って `convert` / 7 `match_names`・`add_images`・`imagelist.check_frame` / 8 ダウンロード（要対応なら一度止める）/ 9 次の論文 |
| 1 画面版（Gradio） | `notebooks/JASME_docx_to_JSTAGE_XML_GUI.ipynb`（同上）→ `app.launch()` | `AppState` が同じ `convert`/`add_images` を呼ぶ。表示は `colab.py` の部品 |

ノートブックは実行のたびに GitHub の `main` から pip で入れる（`BRANCH`）。`main` に入れた変更はすぐ利用者に届く。

---

## 7. テストの地図

`python -m pytest -q`（0.31.0 で 1554 件）。各ファイルが何を守っているかの詳細は `docs/DEVELOPMENT.md` の「テスト」。

| テスト | 守っている動き |
|---|---|
| `test_reader.py` | 読み取りの文字が検証側（canonical_texts）と一致、文字ポリシー（段落記号の削除・隠し文字・削除された行）、テキストボックスの記録、自動番号の上書き（`w:lvlOverride/w:lvl`）、画像のトリミングと加工の記録 |
| `test_fidelity.py` | わざと壊した XML を不変性チェックが必ず検出する |
| `test_structure.py` / `test_article.py` | 領域の分け方、資料の見出し、囲み・注記、位置を決められない除外の知らせ（`excluded_unsure`・`abstract_missing`・冒頭部の装飾）、構造の衝突（K1・K2）の検出が不変性チェックの欠落と一致すること・空白だけの見出し・中止の文の直し方どおりに直した docx が合格すること、循環 import がない |
| `test_floats.py` / `test_figure_body.py` | 浮動配置の図表の配置と組み方、仮の位置、表のセルの図 |
| `test_float_units.py` | 浮動配置の図形の中身の組み方（float_units）、AI の位置の指定を after だけ読むこと、組み立て済みの節を前後に数えないこと |
| `test_figure_units.py` | 図形の外の図の決め方（同じ段落・続く画像だけの段落・近くの段落の画像、段落に結び付いた浮動の画像、飾り） |
| `test_table_images.py` | 画像で貼った表（表キャプションの後ろの画像・図形の中の画像）、表のセルの図キャプションの画像、資料の図キャプション |
| `test_links.py` / `test_refparse.py` / `test_notes.py` | リンクの規則（注・図表・引用）、注の書き方、Word の脚注・文末脚注、注の節の中の表（`<fn><p><table-wrap>`） |
| `test_names.py` | 著者名の姓と名の分け方（`builder.split_eastern` の規則、字の間・前後の空白を落とすこと、要確認 `name_split`、AI の `split_name` との関係、ルート2 の `_name_shape`） |
| `test_ai.py` | AI の回答の検証と適用、途中で切れた回答、4 社の呼び出し（偽のクライアント）、構造の衝突を作る区切りの指定の不採用（2 段の組み直し） |
| `test_ai_request.py` | 依頼文（W8 の手順 13）: 節を出す条件と番号、【作業する方へ】、`system_text`、4 社に渡す system とデータ、依頼文を貼った回答の見分け |
| `test_ai_data.py` | 依頼文のデータの部分（W8 の手順 14）: 「## 本文」の段落と `body_seq`、図形の中の段落・画像の印を載せない、文献と注を 1 回ずつ、⟦番号: …⟧、表のセルの省略、図・表・式の一覧、スタイルの一覧 |
| `test_ai_unresolved.py` | 依頼文のデータの部分 2（W8 の手順 15）: 未解決の一覧の表記と何回目か（`linker.Unresolved`）、レポートの 3 章が変わらない、スタイルを確かめる段落・除外・和文の氏名の節 |
| `test_ai_float_data.py` | 依頼文のデータの部分 3（W8 の手順 16）: 位置を決める図・表の中身・仮の位置・docx の配置（日本語）・推定（段が違えばなし・「## 本文」にない段落の読み替え）、位置が決まっている図形は ID だけ、テキストボックスの 3 つの節、`AIRequest.asked` の after |
| `test_ai_cache.py` | 回答の使い回し（W8 の手順 18）: `AI回答.json` の meta と、1 つでも違えば使わないこと、同じ meta なら偽の API が呼ばれず同じ XML、モデル・提供元・論文が違えば呼ぶ、使えなかった回答は写さない、手動モードでは使わない、コマンドラインの `--ai-refresh`、1 画面版の `ai_cache` と画像の入れ直し、ノートブックの `AI_CACHE` |
| `test_ai_stamp.py` | 依頼の番号と先頭の文字での回答の確かめ（W8 の手順 17）: 番号の前半・後半の変わり方、(a) 読み替え、(b) 直す前の回答と carried・同じ先頭の段落、(c) 別の構造・別の論文・番号のない回答を使わない |
| `test_ai_answer.py` | 回答の新しい形（W8 の手順 10）: 先頭の文字の確かめ、boundaries・links・names・style_fixes の採用と不採用、「指定なし」の記録、request_id・pdf の写し |
| `test_pdfmatch.py` / `test_supplement.py` | PDF との照合、ルート2 の直し、組版で入る文字、補完の確かめ |
| `test_pipeline.py` / `test_lost_images.py` / `test_jstage_rules.py` | 全体の流れ、ZIP の中身、終了コード（構造の衝突の中止は 2）、中止のとき補った docx を残さない（O7）、画像を入れる場所を作れなかった画像、J-STAGE チェック |
| `test_cli_images.py` | `--images` の名前合わせ・`--no-image`・図の画像の表・終了コード |
| `test_imagelist.py` | 図の確かめ.html（行が `image_rows` と同じ・エスケープ・相対リンクと埋め込み・作り直し・ZIP に入らない・図形で描いた図と飾り） |
| `test_image_guards.py` | 画像の守りと知らせ（`lost_images` を `xml_base` で調べる・`image_problems`・ZIP の画像の 2 つの確かめ・`textbox_figure_text` の図形ごとの行・`image_same`・飾りと図形で描いた図） |
| `test_tables.py` | 表の縦の結合・飛ばしたグリッドの組み立てと、表の形の確かめ（`table_problems`・要対応 `table_shape`・12 章） |
| `test_lost_autonums.py` / `test_article.py` | 自動番号の出力（場所ごと）と、自動番号の出力漏れの守り（`lost_autonums`・要対応 `autonum_lost`）、題目・著者名・所属の番号の 10 章の警告 |
| `test_resultless_fields.py` | 結果を持たないフィールド（C013）: EQ などの表示される文字が XML に出ないことの要確認 `resultless_field`（`ooxml.resultless_field_kind`・`Document.resultless_fields`）、表示のない種類・結果のあるフィールドで出ないこと |
| `test_symbols.py` | 記号フォントの私用領域の符号（C011）: `ooxml.SYMBOL_TABLES` の表、箇条書きの記号（`numbering.bullet_text`）、`w:sym`・ランの `w:t` の読み方（`ooxml.w_t_text`。読み取り・検証・ルート2 で同じ）、要確認 `symbol_replaced`・要対応 `pua_left`（`pipeline.pua_chars`） |
| `test_user_images.py` | 作業する人が入れる画像の受け取り（`check_user_image`・`match_names`・`apply_images`・ZIP）。docx の画像の書き出し・切り取り・変換のテストは W1 の手順 16 でなくした |
| `test_sanitize.py` | `tools/sanitize_docx.py`（同じファイルを断る、取り除くもの・残すもの、本文の文字が変わらないこと） |
| `test_colab.py` / `test_app.py` / `test_notebook.py` | 表示部品（中止の枠）、1 画面版の状態、ノートブックが最新か（版・既定モデル）・手順 5 の中止 |
| `test_omml.py` | 数式の変換 |
| `test_syntax.py` | Python 3.10 でも読める書き方か（f 文字列の式の中のバックスラッシュ・同じ引用符。全 `.py` のコンパイル）、レポートに生のタグがないか |

fixture の docx は `tests/make_fixtures.py` が作る（架空の内容。`make_article()` でテストの中でも小さな論文を作れる）。
手動モードで貼り戻す AI の回答は `tests/answers.py` の `answer()` が意味で書いた項目から作る（写し方のテストは `test_answers.py`）。
実際の論文は `tests/private/`（`.gitignore` 済み）にだけ置く。CI は `.github/workflows/test.yml`（Python 3.10 / 3.12）。

---

## 8. 逆引き: 変えたいときはどこを見るか

| やりたいこと | 見る所 |
|---|---|
| 新しいスタイル名を役割に対応させる | `data/jasme.toml` の `[styles]`（コードは変えない） |
| 役割の推定の規則（番号の形・見出しの推定）を変える | `structure.py` の `RE_*`、`guess_heading`、`role_of`。判断は `plan.decide` に記録 |
| 領域（本文 / 後付け / 英文の部分）の切り替えを変える | `structure.Classifier.split_regions`（空白だけの段落〈図形の外〉では切り替えない。文字から推定した「注」の本文への戻しは `fn_guess`・`check_fn_guess`）、`back_heading_by_text`、`outside_key` |
| 図表の配置（浮動配置）の規則を変える | `floats.at_anchor`（機械的に置ける条件）、`structure.place_floats`、`provisional_target`。中身の組み方は `structure.float_units`（B1〜B5）、組み立て済みの節を前後に数えない置き場所は `NODE_PLACE`（`same_place`） |
| 囲み / 図の注記のしきい値を変える | `floats.textbox_kind` の定数（`BOX_CHARS` など）、`structure.place_boxes` |
| リンクの規則（図表・注・引用）を変える | `linker.py`（`float_refs`、`float_numbers`〈重なる番号・枝番〉、`_sup_marks`、`note_style`）、`refparse.py`（引用）。枝番の定義は `structure.CAP_BRANCH_SEP`・`CAP_BRANCH_NUM`（builder の `RE_LABEL_SPLIT` と共有） |
| 著者名の姓と名の分け方を変える | `builder.split_eastern`（和文。境目の推定の手がかりは `name_context`・`surname_hint`〈引用の形は `RE_CITE_AFTER`〉。AI の指定は `EasternSplit.how` が `ai`）と `Builder.person_name`（英文・落とす空白）。`pdfdocx._name_shape`（ルート2 の形の比べ）と `ai_assist.apply_ops` の `split_name`（`spaced_split`）も合わせる。知らせは `report._name_split_action` |
| XML の要素・属性の出し方を変える | `builder.py`（要素の並び）、`emit.py`（文字・書式・リンク。`Ctx`） |
| 文字を書く文脈の制限（例: 所属で使える書式）を変える | `emit.py` の `Ctx` 定数（TITLE・NAME・AFF・REF…）。`article.no_link_paras` も合わせる |
| docx の新しい要素（例: 新しい種類のフィールド）に対応する（結果を持たないフィールドで Word では表示のある種類を増やすなら `ooxml.FIELD_DRAWN`） | `ooxml.canonical_text`（検証）と `docx_reader._walk`/`_run`（読み取り）、`pdfdocx.paragraph_units`（ルート2）の 3 か所を同じ規則で。fixture を足す |
| 隠し文字・段落のつながりの規則を変える | `ooxml.HiddenRule`、`ooxml.joined_paragraphs`（3 か所が共有。単体テストで確かめる） |
| 除外の理由を足す・変える | `structure.py` の除外の理由の定数。位置を決められずに除くなら `UNPLACED_EXCLUSIONS` に入れ、`report.UNPLACED_GUIDE` に名前と直し方を足す |
| 利用者への知らせ（要対応・要確認）を足す | `report.py` に `_xxx_action` を作り `actions()` に加える。画面側は触らない。画面の操作は目印 `step()`、レポートの生のタグは `md_tag()` |
| 画面ごとの操作の語（手順番号・欄の名前）を変える | `colab.STEP_WORDS`（1 か所の表）。目印の名前を足すなら `report.STEP_NAMES` と全画面の語 |
| レポートの章を変える | `report.render`（章ごとに `L.append`）。13 章は `render_route1`/`render_route2` |
| ZIP に入れるものを変える | `package.upload_entries`（1 か所）と `zip_problems`（確かめ） |
| 受け付ける画像の形式を変える | `images.check_user_image`（`_ACCEPTED`・`_REFUSED`）。J-STAGE が受け付けるのは jpg・gif・png |
| 画像の守り（置き場所を作れなかった画像・名前の不具合・飾り）を変える | `pipeline.lost_images`（`xml_base` の木で調べる）・`image_problems`・`decorations`（図形で描いた図の幹は `_decoration_figure`）、ZIP の画像は `package.zip_problems`、知らせは `report.lost_action`（直し方は `APP_MOVE_HOW` の 1 か所）・`_image_names_action`・`_image_same_action`・`_textbox_figure_text_action`（図形ごとの行は `figure_text_groups`） |
| Word の画像の加工（トリミング・回転など）の扱いを変える | 変える所はない。docx の画像は書き出さず、読み取りも加工を読まない（W1。`ImageRef.crop`・`edits`・`IMAGE_EDITS` は手順 16 でなくした）。作業する人が入れる画像は中身を変えない（`images.check_user_image`） |
| 表の組み立て（縦の結合・飛ばしたグリッド）を変える | `builder.Builder.table`。変えた後も `pipeline.table_problems`（builder の判断に頼らない確かめ）が通ること（`tests/test_tables.py`） |
| Word の自動番号の出し方を変える | `builder.Builder.autonum_mark`・`caption`・`heading_title`・`unshown_number`。出した番号の `jx:gen` には段落 ID の `src` を付ける（`pipeline.lost_autonums` が使う） |
| J-STAGE のチェックを足す | `jstage_rules.check`（XML で判定できるもの）、`package.zip_problems`（ZIP の形） |
| AI の依頼内容・回答の項目を変える | `ai_assist.request_sections`（出す節）・`request_instructions` と指示の文の定数、`RESPONSE_SCHEMA`（種類ごとのスキーマ `PLACEMENT_SCHEMA` など）と種類ごとの検証（`link_ops` など）、`apply_ops`、`set_role_problem`、テストの回答 `tests/answers.py`、XML に反映する役割の補正 `BOUNDARY_KINDS`・`boundary_problem`（ほかは提案 `style_fixes`） |
| 既定の AI モデルを変える | `ai_assist.DEFAULT_MODEL`・`DEFAULT_MODEL_INFO` → `python tools/make_notebook.py` |
| API モードの AI を増やす | `ai_assist.call_xxx` を足し `PROVIDERS`・`API_KEY_NAMES`・`call_provider`、`cli.py` の `--ai-provider`、ノートブック手順 4 |
| PDF との照合の分類（(A)(B)(C)）を変える | `pdfmatch._classify`/`_report_regions`、`typeset_pair` と定数表。`fidelity._pair` も同じ答えになるように（`test_supplement.py`） |
| 組版で入る文字（柱・受付日）の扱いを変える | `pdfmatch.pdf_stream`、`RE_RECEIVED`、`MIN_CHARS` |
| ルート2 の docx への書き込みを変える | `pdfdocx._Writer`。書いた後の `_verify`・`_structure` を外さない |
| 書誌情報の入力の確かめを変える | `config.ArticleMeta.from_dict`、`_id_value`、`_date` |
| ノートブックの文言・セルを変える | `tools/make_notebook.py` → `python tools/make_notebook.py`（ipynb は直接編集しない） |
| 構造の衝突（K1・K2）の検出・中止の文を変える | 検出は `structure.Classifier.replace_back`・`aff_conflict`、範囲は `conflict_overrides`、中止は `pipeline.convert`、文は `report.structure_conflict_text`。検出は不変性チェックの欠落と一致させる（`tests/test_structure.py`） |
| 1 画面版の画面を変える | `app.build_app`（画面）、`AppState`（状態。Gradio なしでテストできる） |
| 版を上げる | `src/jasme_jats/__init__.py` と `pyproject.toml` → ノートブックを作り直す |

---

## 9. 用語

| 用語 | 意味 |
|---|---|
| アトム | 段落の中の最小単位（文字・数式・画像・脚注参照・生成文字）。`model.Atom` |
| 段落 ID / src | docx の段落の識別子（`d12`、脚注 `f3`、文末脚注 `e3`）。XML の `jx:span` と docx を結ぶ |
| 領域 | 段落がある区画: 和文の冒頭 `front_ja` / 著者表 `authors` / 本文 `body` / 付記 `notes` / 謝辞 `ack` / 注 `fn` / 引用文献 `refs` / 後付け `back` / 英文の部分 `front_en` / 資料 `app` |
| 役割 | 段落の種類（見出し・本文・図キャプション・引用文献…）。スタイル名から決め、想定外は推定（`Para.role`、`role_origin`） |
| 除外 / Exclusion | XML に出力しない段落。必ず理由付きで記録し、レポート 6 章に全文を載せる。位置を決められない除外（`UNPLACED_EXCLUSIONS`）は要確認・要対応でも知らせる |
| 構造の衝突 | そのまま組み立てると段落の文字が XML にも除外にも入らなくなる形（同じ種類の後付けの見出し・英文要旨の見出しが 2 つ、著者名の付かない所属。K1・K2）。変換を中止する（`StructureConflictError`） |
| 生成文字 | docx の文字ではなく Word が表示時に作る文字（自動番号・脚注番号・補った注の見出し）。`jx:gen`（自動番号は `src` に段落 ID） |
| 不変性チェック | docx の文字と XML の文字を 1 文字ずつ照合すること（`fidelity.verify`） |
| 浮動配置の図形 / Float | テキストボックス・グループ図形で、本文の段落（アンカー段落）に結び付いて浮いているもの（`s1…`） |
| 文字だけのテキストボックス | 画像・表・キャプションを含まないテキストボックス。囲み（`<boxed-text>`）/ 図の注記（除外）/ 決められない（除外して要確認） |
| 位置を決められない図表 | 機械的に置けず AI に位置を指定させる図表。回答がなければ仮の位置（アンカー段落の後ろ・本文の最後） |
| 判断 / Decision | 機械処理・AI の判断の記録（レポート 2・4 章） |
| 要対応 / 要確認 / 手順 | 利用者への知らせの 3 区分（`report.Action.level`）。要対応は終了コード 1 とダウンロード前の一時停止、要確認は黄色い枠だけ、手順は青い枠と 14 章の行（必須で残っていれば要対応と同じく止める。推奨は止めない） |
| ルート1 / ルート2 | docx から作る / docx から作り、出版版 PDF で補う（`Options.route` の docx / pdf） |
| (A)(B)(C) | ルート2 の違いの分類: 組版の違い（PDF に合わせる）/ 校正の直し（変更履歴で補う）/ 決められない違い（直さず 13.3 に理由を出す） |
| 補完の確かめ | 補った docx が元の docx から (A)(B) 以外に変わっていないことの確認（`fidelity.verify_supplement`） |
| 注の鍵 | Word の脚注・文末脚注の識別子「footnote:5」「endnote:5」（`model.note_key`） |
| 柱 | PDF の各ページの端にある誌名などの行（照合に使わない） |

---

## 10. 暫定の判断・課題の所在

- Word で未確認の規則（隠し文字・段落のつながり・削除されたセル）と、架空の docx でしか確かめていない機能の一覧は
  `docs/DEVELOPMENT.md` の「残っている課題」と `docs/DESIGN.md` の 7 章。
- 2026-11 の点検で見つけた問題と、直すべき度合いの分類は `docs/REVIEW_2026-11.md`。
- `grep -n "暫定" src/jasme_jats/*.py` で、コードの中の暫定の判断の場所が出る（0.31.0 で 20 か所）。
