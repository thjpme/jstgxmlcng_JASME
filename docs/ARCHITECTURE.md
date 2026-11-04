# コードの地図（引き継ぎ用）

このツール（jasme-jats 0.29.0）の「どこが何をしているか」を、別の人や AI が短時間で把握できるようにまとめたもの。
2026-11-03 にコード全体を読み直して書いた。

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

---

## 1. 全体像

```
入力: 論文の docx（＋ 書誌情報、任意で 出版版 PDF、任意で AI の回答）

  [ルート2 のときだけ] pdfdocx.make_fixed_docx: PDF と照合して、補った docx（変更履歴つき）を作る ── 以降はそれを入力にする
        │
  docx_reader.read_docx ──────────▶ model.Document（段落 = アトムの列。表・画像・図形・脚注も）
        │
  structure.classify ─────────────▶ article.ArticlePlan（題目・著者・本文の章節・図表・注・文献・英文要旨・資料。除外した段落と判断の記録）
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
  pipeline.lost_images ───────────▶ XML に入らなかった画像
        │
  images.export_images → jstage_rules.check → package.write_package（ZIP）→ report.render（レポート）
        │
出力: {記事識別子}.xml、jasme_{記事識別子}.zip、{記事識別子}_変換レポート.md、（AI 依頼文.txt、AI判断一覧.md、PDFで補完した原稿.docx）
```

この流れの実体は `pipeline.convert()`（`src/jasme_jats/pipeline.py`）。画面（CLI・Colab・Gradio）はこれを呼ぶ薄い層にすぎない。

### 層で見たモジュール

```
画面      cli.py   colab.py（表示部品）   app.py（Gradio）   tools/make_notebook.py（ノートブック生成）
流れ      pipeline.py（convert / add_images / lost_images / Result）
出力      report.py（レポート・利用者への知らせ actions）  package.py（ZIP）  images.py（画像）  jstage_rules.py
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
| `cli` | ai_assist, config, pipeline, report |
| `app` | ai_assist, colab, config, pipeline, report |
| `colab` | report（`STEP_MARK_PATTERN`・`NEEDS_ACTION` など。`step_text` が目印を読む） |
| `pipeline` | ai_assist, article, builder, config, docx_reader, fidelity, images, jstage_rules, linker, model, package, pdfdocx, pdfmatch, report, structure, tracking, validate |
| `report` | ai_assist, docx_reader, linker, model, package, pdfdocx, pdfmatch, structure, validate（`md_tag` が要素名を引く） |
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
| `model.Document` | `docx_reader.read_docx` | structure, builder（画像）, pipeline, report | `blocks`（Para と Table の列。本文の順）、`footnotes`/`endnotes`（ID → [Para]）、`media`（画像のバイト列）、`styles`、`images`（ImageRef）、`floats`（浮動配置の図形）、`textboxes`、`layout`（段組み）、`hidden_text`/`style_hidden`、`joined`/`joins`（段落記号の削除でつないだ段落）、`deleted_rows`、`warnings` |
| `model.Para` | docx_reader | すべて | `src`（段落 ID: 本文 d1, d2…、脚注 f…、文末脚注 e…）、`atoms`、`style_id`、`numbering`/`autonum`、`float_id`/`textbox_id`、`role`（structure が決める） |
| `model.Atom` | docx_reader | linker, emit | `kind` が text / math / image / fnref / gen。`text`、`fmt`（bold など）、`href`、`link`（LinkSpec）。`plain()` は文字でないものを U+FFFC にする |
| `model.LinkSpec` | linker, refparse, ai_assist | emit | `kind`（xref / uri / ext-link / pub-id / year / article-title / source / label）、`attrs`、`origin`（word / mechanical / ai） |
| `article.ArticlePlan` | `structure.classify` | linker, ai_assist, builder, report, pipeline, pdfmatch, pdfdocx | 論文の構造（`title`、`authors`、`body`〈Sec の木〉、`fns`、`refs`、`abstract`、`apps`…）、`paras`（src → Para）、`region`（src → 領域）、`locations`（src → 人が読む位置）、`exclusions`、`decisions`、`floats`（FloatInfo）、`textboxes`（BoxInfo）、`figures`/`tables`/`formulas`、`body_seq`、`float_unlinked`（リンクしなかった図・表の参照。`UnlinkedRef`〈図か表, 段落 ID, 文字, 段落の中の範囲〉）、`fn_guess_checks`・`fn_guess_numbered`・`fn_guess_span`（文字から推定した「注」の扱い。要確認 `fn_guess`。`fn_guess_span` は「注見出し」にしたとき注の節に入る段落） |
| `article` のノード | structure | builder, report | `Sec`、`PNode`、`ListNode`、`QuoteNode`、`FigNode`、`TableNode`、`FormulaNode`、`BoxNode`、`FnNode`、`RefNode`、`BackSec`、`AppNode`、`Author`、`Aff` |
| `model.Decision` | `plan.decide()`（structure・linker・ai_assist） | report, ai_assist（依頼文の「推定:」） | 機械処理・AI の判断の記録（did は M-001 / A-001） |
| `model.Exclusion` | `plan.exclude()`/`exclude_blank()`、builder | fidelity, report（6 章）, pipeline.lost_images | 出力しない段落の ID・理由・全文。`blank` は空白だけの段落 |
| `linker.Linker` | `linker.link` | pipeline, ai_assist, report | `count`（リンクの数）、`unresolved`（リンク先が見つからなかった参照）、`note_style`/`bare_notes`、`float_numbers`（図・表の番号 → ID、リンクしない番号〈重なる・枝番つき〉、枝番の有無）。リンクしなかった参照は `_unlinked` が判断の一覧と `plan.float_unlinked` に記録 |
| `ai_assist.AIOutcome` | pipeline | report, colab, app | `mode`/`provider`/`model`、`raw`（回答）、`accepted`/`rejected`（操作と Decision・理由）、`notes`、`error`、`cut`/`partial`（途中で切れた回答） |
| lxml の木 + `builder.BuildInfo` | `builder.build` | fidelity, pipeline, report | `images`（出力した画像）、`exclusions`（builder 側の除外）、`drops`、`notes`、`newlines`、`unsplit_names`、`warnings` |
| `fidelity.FidelityResult` | `fidelity.verify` / `final_check` | pipeline（Result.ok）, report（5 章） | `ok`、`mismatches`、`missing`、`duplicates`、`stray`、`conflicts`、`bad_excluded`、`final_ok`、`final_unreadable`（最終出力が XML として読めない・実体の宣言がある）、`final_differs`（最終出力の文字が検証済みの木と違う） |
| `pdfmatch.PdfCheck` | `pdfmatch.check_pdf` | pdfdocx, report（13 章）, pipeline | `diffs`（TextDiff）、`unmatched`、`width`/`drops`/`numbers`（(A) の直し）、`drop_basis`（`drops` の空白の根拠の全角・半角の直しまたは番号）、`ignored_lines`、`case_srcs` |
| `pdfdocx.DocxFix` | `pdfdocx.make_fixed_docx` | pipeline, fidelity.verify_supplement, report | `path`（補った docx。入力が同名なら `_2` などの別名）、`fixes`（Fix の一覧。applied / reason。`Fix.group`＝1 つの違いを分けた組〈双方向〉、`Fix.needs`＝空白の削除が従う根拠の全角・半角の直し〈片方向〉）、`check`（照合の結果） |
| `fidelity.SupplementResult` | `fidelity.verify_supplement` | pipeline, report（13.8） | 補完の確かめの合否と問題 |
| `pipeline.Result` | `pipeline.convert` | report, cli, colab, app | 上のすべてを束ねたもの。`ok`（3 つの検証の合格）、`needs_action`（要対応があるか。`report.actions` から決まる）、出力ファイルのパス |
| `report.Action` | `report.actions(res)` | report（冒頭・14 章）, colab（枠）, cli（標準エラー）, pipeline（終了コード） | `level`（NEEDS_ACTION / TO_CHECK）、`key`、`top`、`checklist`、`box_title`/`box_detail`、`cli` |

### 段落 ID（`src`）

docx の `w:p` の出現順に `ooxml.paragraph_ids` が振る（本文 `d1, d2, …`、脚注 `f1…`、文末脚注 `e1…`）。読み取りと検証が同じ番号を使うので、
XML の `<jx:span src="d12">` から docx の段落に戻れる。段落記号の削除でつないだ段落は、連鎖の最初の ID だけが残り、後ろは欠番。
図形の ID は `s1, s2…`（浮動配置。`model.Float`）、テキストボックスは `x1, x2…`（`model.TextBox`）、画像は `img1…`、表は `t1…`。
XML の要素の ID は `structure.Classifier.assign_ids` が付ける: 図 `F1`、表 `T1`、数式 `FD1`、注 `fn1`、文献 `B1`、所属 `aff1`。

---

## 3. 各モジュールの役割と入口

行数は 0.29.0 のもの。「入口」は、ほかのモジュールから呼ばれる主な関数。

### 基盤

| ファイル | 行 | 役割 | 入口 |
|---|---|---|---|
| `ooxml.py` | 453 | docx の低水準処理と**文字ポリシー**（何が docx の文字か）。`DocxPackage`（zip を開いて `mc:AlternateContent` を前処理）、`HiddenRule`（隠し文字の判定。styles.xml から作る）、`joined_paragraphs`/`unjoined_deleted_marks`（段落記号の削除でつなぐ段落）、`canonical_text`/`canonical_texts`（検証用の文字の取り出し。読み取りとは別実装）、`sym_char`（Symbol フォント）、`in_deleted_run`（削除の変更履歴の中の図形の段落を欠番にする判定。読み取り・検証・ルート2 が共有） | `DocxPackage`, `HiddenRule`, `canonical_texts`, `joined_paragraphs`, `paragraph_ids`, `in_deleted_run` |
| `model.py` | 342 | 中間表現の型（上の表）。`note_key`/`note_label`（Word の脚注・文末脚注の鍵「footnote:5」） | 型 |
| `config.py` | 244 | `JournalConfig`（`data/jasme.toml`。誌名・ISSN・DOI 形式・スタイル名の対応・原稿種別）と `ArticleMeta`（記事ごとの書誌情報。`from_dict` が巻・号・ページを NFKC にして確かめ、日付を `_date` で読む） | `JournalConfig.load`, `ArticleMeta.from_dict`/`load`, `article_id`, `doi_value` |
| `tracking.py` | 27 | 変換中の目印の名前空間（`jx:span`、`jx:drop`、`jx:gen`、`jx:implicit`、`jx:o`、`jx:ai`） | 定数 |

### 読み取り

| ファイル | 行 | 役割 | 入口 |
|---|---|---|---|
| `docx_reader.py` | 849 | docx → `Document`。`Reader.read` が document.xml の `w:body` を `read_block` で順にたどる（段落 `read_paragraph`、表 `read_table`、`w:sdt`/`w:customXml` は `_children` で中身をたどる）。`_walk`/`_run` がランをアトムにし、ハイパーリンク・フィールド・変更履歴・隠し文字を扱う。`_graphic` が画像（DrawingML・VML・OLE）と図形（`_new_float`・`_new_textbox`。テキストボックスの中の段落・表は `_read_nested_*`）を記録。`read_notes` が脚注・文末脚注。`read_styles`/`read_layout` | `read_docx(path) -> Document` |
| `numbering.py` | 183 | numbering.xml から自動段落番号の表示文字列（`Numbering.label`）。`w:lvlOverride`・`w:startOverride`、ローマ数字・英字・漢数字。`w:numStyleLink` は styles.xml の番号付けスタイルをたどる（`Numbering(root, styles_root)`・`_follow_style_links`） | `Numbering`, `format_number` |
| `omml.py` | 407 | OMML → MathML 2.0（`OmmlConverter.convert`）。属性で表される記号は `jx:implicit`、順序が入れ替わる文字は `jx:o`。`math_plain`（数式の文字だけ）。根号は `m:deg` に文字があれば `degHide` でも `mroot`（`h_rad`） | `OmmlConverter`, `omml_to_mathml`, `math_plain` |

### 構造

| ファイル | 行 | 役割 | 入口 |
|---|---|---|---|
| `article.py` | 368 | `ArticlePlan` とノードの型、`FloatInfo`/`BoxInfo`、`plan.decide`（段階ごとの件数を持ち O(1) で番号を付ける）/`exclude`/`exclude_blank`/`float_place`/`box_place`/`no_link_paras`、`float_unlinked`・`fn_guess_checks`・`fn_guess_numbered`。規則は置かない | 型 |
| `structure.py` | 2408 | 段落の役割の決定と構造の組み立て。`classify(doc, journal, overrides, placements)` → `Classifier.run`。流れ（冒頭の docstring に目次）: ① `role_of`（AI の指定 → スタイル → 推定）② `split_regions`（和文の冒頭 / 本文 / 後付け / 英文の部分）③ `build_front_ja`（題目・著者・所属）④ `build_body`（`place_floats` 浮動配置の図表、`place_boxes` 文字だけのテキストボックス、`assemble_floats` 図表・箇条書き・引用・別行数式に組む、`nest` 章節項、`compute_locations`）⑤ `build_back`（付記・謝辞・注・引用文献）⑥ `build_front_en`（英文題目・著者・要旨・資料）⑦ `attach_word_notes`（Word の脚注・文末脚注を通し番号の注に）⑧ `assign_ids` ⑨ `joined_styles`。②では、本文スタイルの「注」だけの段落を文字から注の見出しと推定して後付けに切り替えた後、見出しのスタイル（sec1〜sec3）の段落が資料の見出し以外で現れたら本文に戻し、要確認 `fn_guess` の材料（`plan.fn_guess_checks`・`fn_guess_numbered`）を記録する（`check_fn_guess`。ブロックの識別は `block_id`）。「注見出しにすると注の節に入る段落」（`plan.fn_guess_span`）は、推定した「注」ごとに `feed_fn_span` が、その「注」を「注見出し」スタイルにしたときの `build_back` と同じ規則（別の「注」は見出しとして数えない）で数える。⑤の付記・謝辞・資料の自動番号の段落は `add_back_para` で `ListNode` にする。図表のキャプションの番号と枝番は `caption_label`・`RE_CAP_BRANCH`（区切り `CAP_BRANCH_SEP`・数字 `CAP_BRANCH_NUM` は builder・linker が共有）で読む。本文の外の段落に結び付いた図形があれば 2 回組み立てる（`Classifier.outside`）。正規表現（`RE_FIGCAP`、`RE_TABCAP`、`RE_APPENDIX` など）と除外の理由の文言もここ | `classify`, `float_caption`, `float_targets`, `appendix_heading` |
| `floats.py` | 193 | 浮動配置の図形の位置の判定（`at_anchor`: 機械的に置けるか）、AI に渡す説明（`describe`）と行数の推定（`para_lines`, `box_lines`）、文字だけのテキストボックスが囲みか注記か（`textbox_kind`。しきい値 `BOX_CHARS` など） | `at_anchor`, `textbox_kind`, `describe` |

### リンク

| ファイル | 行 | 役割 | 入口 |
|---|---|---|---|
| `linker.py` | 723 | 機械的リンク。`Linker.run`: 数式のラベル → 段落ごとに Word のハイパーリンク・URL/DOI・図表の参照（`float_refs`）・数式の参照（`eq_refs`）・注の参照（`fn_marks`。上付きの種類分け `_sup_marks`、論文の注番号の書き方 `note_style`）→ 引用（refparse）。`apply_span` がアトムに LinkSpec を付ける唯一の共通関数（リンクが重なる・数式をまたぐときは付けない）。`unresolved` にリンク先のない参照を記録。図・表の番号が重なる・枝番つきのキャプションの番号は `float_numbers` でリンク先から外し、その参照と枝番つきの参照（`RE_BRANCH_REF`）はリンクせず `_unlinked` が記録する（K4）。`body_paragraphs` は図・表の `caption_more`（2 段落目以降）も文脈 `caption` で返す | `link(plan, ref_doi) -> Linker`, `apply_span`, `find_in_para`, `occurrence_at`, `cited_refs` |
| `refparse.py` | 423 | 引用文献の解析（`parse_entry`: 著者・年・題名・誌名・DOI）と、本文の著者・年方式の引用の抽出・照合（`extract_citations`, `match_citation`, `link_citations`）、番号方式（`link_numeric`）。NFKC で照合して元の位置に戻す | `link_citations`, `tag_reference`, `link_numeric` |

### AI 補完

| ファイル | 行 | 役割 | 入口 |
|---|---|---|---|
| `ai_assist.py` | 1607 | ① 依頼文 `build_request`（段落一覧 `para_view`、位置を決められない図表 `float_section`、文字だけのテキストボックス `textbox_section`、除外の案内 `set_role_hint`、画像 `image_blocks`）② 呼び出し `call_provider` → `call_api`（Claude。構造化出力・ストリーミング。モデルがなければ `latest_opus`）/ `call_openai` / `call_gemini` / `call_sakana`。手動モードは `manual_prompt` ③ 回答の読み取り `parse_response`（最初の `{` から最後の `}`）、途中で切れた回答 `parse_cut_response` ④ 検証と適用: `split_ops` → `role_overrides`（`set_role_problem` で可否）と `float_placements`（`_placement_problem`/`_box_placement_problem`）→ classify をやり直す（pipeline）→ `retarget_ops`（ID の読み替え）→ `apply_ops`（link_* / split_name / formula_image の検証。題目・著者名・所属・引用文献・別行数式の段落へのリンクと、表・移した画像・キャプションの続きのある図への formula_image は不採用。AI が付けた図表のリンクは、範囲が重なる参照だけ `plan.float_unlinked` から除く）。回答の項目の型は `split_ops`、`notes` は `_notes_list`、MathML は `parse_mathml`（DOCTYPE・実体参照などを不採用）で確かめる。`SYSTEM_PROMPT`、`RESPONSE_SCHEMA`、`DEFAULT_MODEL`/`DEFAULT_MODEL_INFO` | 上のとおり |

### XML の組み立て

| ファイル | 行 | 役割 | 入口 |
|---|---|---|---|
| `builder.py` | 901 | `build(plan, meta, journal, split) -> (root, BuildInfo)`。`Builder` が `<article>` → `<front>`（journal-meta・article-meta: 題目・著者・所属・日付・要旨・キーワード）→ `<body>`（Sec の木。段落・箇条書き・引用・図 `fig`・表 `table-wrap`・数式 `disp-formula`・囲み `boxed-text`）→ `<back>`（付記 `notes`・謝辞 `ack`・注 `fn-group`・文献 `ref-list`・資料 `app-group`）の順に作る。`word_note_marks`（Word の注の番号）、`finalize`（目印を外す）、`serialize`（DOCTYPE 付きで直列化）。全行が見出し行の表は `thead` を作らず、謝辞 `ack` の中の別行数式・表・リストは `p` で包み、付記・謝辞・資料の自動番号の段落は `list_node` で `<list>` に書く | `build`, `finalize`, `serialize`, `word_note_marks` |
| `emit.py` | 297 | 段落のアトムを JATS の要素に書く。`Emitter.span` が **文字を書く唯一の経路**（`<jx:span>` の中に、書式・リンクの要素で包んで書く）。`Ctx` が文脈ごとの制限（TITLE・NAME・AFF・REF・CELL・DISPF…: 使える書式、リンクの書き方、xref の可否、画像の可否、`<break/>` の有無、改行を要確認にする名前）。`drop`（空白だけ落とす）、`gen`（生成文字）、`write_object`（数式・画像・脚注参照） | `Emitter`, `Ctx` と定数 |
| `validate.py` | 49 | 同梱 DTD（`dtd/JATS-journalpublishing1.dtd`）で検証（`resolve_entities=False` なので未定義の実体参照は見つけない。`fidelity.final_check` が補う）。`jats_element_names()` は DTD の要素名（`report.md_tag` が使う） | `validate(xml_bytes) -> (ok, errors)`, `jats_element_names` |
| `jstage_rules.py` | 163 | J-STAGE のアップロード時チェックのうち XML だけで判定できるもの（題目と要旨の言語、日付の前後、所属番号、DOI の文字、画像名など）。`docs/JSTAGE_NOTES.md` | `check(root, aid, image_names) -> [(ID, 内容)]` |

### 検証

| ファイル | 行 | 役割 | 入口 |
|---|---|---|---|
| `fidelity.py` | 688 | ① `verify(docx_path, root, exclusions)`: `source_texts`（ooxml.canonical_texts）と XML の `jx:span` を段落ごとに比べる（欠落・重複・不一致・目印の外の文字 `stray_text`・落とした空白・出力と除外の矛盾・空白のはずの除外に文字）② `final_check(root, xml_bytes, fid)`: 目印を外した最終 XML を読み直して再照合（実体の宣言があれば解決せず不合格。なければ実体を解決するパーサでも読めることを確かめる。`final_unreadable`・`final_differs`） ③ `verify_supplement(original, fixed, fixes, …)`: ルート2 の補完の確かめ（変更履歴の単位 `_mark_runs`/`_unit_ends` を取り出し、(A) は `_pair`、(B) は報告された Fix と照合。pdfmatch とは定数しか共有しない）。`supplement_targets` | 上のとおり |

### PDF との照合（ルート1 の照合、ルート2 の補完）

| ファイル | 行 | 役割 | 入口 |
|---|---|---|---|
| `pdfmatch.py` | 2893 | `check_pdf(plan, pdf_path, fn_marks) -> PdfCheck`。① `extract_pages`（pypdfium2）② `pdf_stream`（空白・ページ番号を除いた文字の列に、柱の候補 `head`・ページの端 `edge`・行全体でしか一致させない行 `line_only`・受付日 `date`・数式の位置 `formula` の印）③ `compare` → `_joint`（全段落をつないで PDF と単調に対応付け、段落ごとの窓を決める）→ `_align`（difflib で段落ごとに照合）→ `_classify`/`_report_regions`（違いを (A) `typeset_pair`/`width`/`drops`/`numbers`、(B) `kind="text"`、(C) `why` に分ける）。`diff_parts`（1 つの違いを直す単位に分ける）。定数表 `QUOTE_CLASSES`・`DASHES`・`HYPHENS`・`NUMBER_PAIRS`・`FW_FIRST/LAST`、理由の文言 `*_WHY` | `check_pdf`, `extract_pages`, `pdf_stream`, `typeset_pair`, `diff_parts` |
| `pdfdocx.py` | 834 | `make_fixed_docx(docx, pdf, out, journal) -> DocxFix`。元の docx を読んで照合し（`_mechanical` → `check_pdf`）、`plan_fixes` で段落ごとの Fix（kind width / space / glyph / text）を決め（空白の削除 `space` は `Fix.needs` で根拠の `width` に片方向で従い、`spread_reasons` が「直さない」を不動点まで広げる。1 つの違いを分けた組は `FixGroup`・`link_fixes` で双方向）、`_Writer` が元の XML（前処理しない木）のランを分けて `w:del`/`w:ins` を書き込む（`paragraph_units`/`raw_paragraph_ids` が読み取りと同じ文字ポリシーで段落を特定）。書いた後に `_verify`（読み直した文字が期待どおりか）と `_structure`（役割・領域・リンク・注の区切り・著者数が元と同じか）で確かめ、合わない段落は直さずに作り直す | `make_fixed_docx`, `paragraph_units`, `tracked_counts`, `same_file` |

### 出力

| ファイル | 行 | 役割 | 入口 |
|---|---|---|---|
| `images.py` | 198 | `export_images`: 画像を `Graphics/` に書く（png/jpg/gif はそのまま、bmp 等は Pillow、EMF/WMF は LibreOffice → PDF → pypdfium2 で PNG。変換できなければ `要変換/` に元を置く）。`user_image`: 利用者が用意した画像（PDF 1 ページも）を出力形式に | `export_images`, `user_image`, `ImageResult` |
| `package.py` | 160 | J-STAGE のフォルダ構成（`jasme/巻/号/記事識別子/`）と ZIP。`upload_entries` が ZIP に入れるものを決める唯一の場所。`zip_problems`（ZIP を読み直して EMSGM034E/053E/059E/073E/074E など）、`unzipped_files`（入れなかったファイル） | `write_package`, `make_zip`, `zip_problems`, `unzipped_files`, `article_dir` |
| `report.py` | 2302 | 変換レポート（Markdown）`render(res)`: 冒頭の要約 → 1 結果の要約 → 2 AI → 3 解決できなかった箇所 → 4 機械的な推定 → 5 不変性チェック → 6 出力しなかった文字 → 7 落とした空白 → 8 生成文字 → 9 画像 → 10 警告 → 11 書誌情報 → 12 DTD と J-STAGE チェック → 13 PDF との照合（`render_route1`/`render_route2`）→ 14 登載前のチェックリスト。`render_ai_only`（AI 判断一覧）。**`actions(res)`** が利用者への知らせ（要対応・要確認）を `Action` の一覧にする唯一の場所（`_fidelity_action`、`_dtd_action`、`_upload_action`、`_ai_*`、`_forced_action`、`images_action`、`lost_action`、`_style_hidden_action`、`_newline_action`、`pdf_actions`…）。`images_to_prepare`（用意が必要な画像）。画面の操作は目印 `step()`（`STEP_NAMES`）で書く（`colab.step_text` が画面ごとの語に置き換える）。レポートの生のタグは `md_tag()` で囲む。0.29.0 で `_float_ref_action`（key `float_ref`。AI の状態で文を分ける `float_ref_manual`・`float_ref_ai`）と `_fn_guess_action`（key `fn_guess`）を足した | `render`, `actions`, `images_to_prepare`, `upload_issues`, `pdf_summary` |

### 流れと画面

| ファイル | 行 | 役割 | 入口 |
|---|---|---|---|
| `pipeline.py` | 600 | `Options`（出力先・AI の方法・PDF・ルート）、`Result`、`convert`（4 章）、`add_images`（利用者の画像を入れて ZIP とレポートを作り直す）、`lost_images`、`fixed_docx_path`（補った docx の書き出し先。入力が同名なら `_2` などの別名）、`AIRequiredError`、`tool_version` | `convert`, `add_images`, `Options`, `Result` |
| `cli.py` | 148 | `python -m jasme_jats` の引数と終了コード（0 要対応なし / 1 要対応あり / 2 中止。`--ai-response` は `--ai manual` のときだけ指定でき、それ以外は引数の誤りで 2）。`user_images_in` | `main` |
| `colab.py` | 338 | Colab の表示部品（HTML）: 依頼文の枠 `prompt_box`、要対応（赤）・要確認（黄）の枠 `result_boxes`（`actions` の順）、要約 `summary_box`、畳んだレポート `report_details`（Markdown → HTML は `markdown_text_only`。生の HTML・実体を無効にして docx の文字の `<`・`&` をそのまま見せる）、続けて変換するときの確認 `same_first_page`/`carried_over`。画面の操作の目印の置き換えは `STEP_WORDS`（`notebook`・`app`・`cli`）と `step_text`（枠を作る関数が `screen` 引数を受ける）。1 画面版の欄・ボタンのラベルは定数 `ANSWER_LABEL`・`APPLY_LABEL`・`CONVERT_LABEL`（`app.py` も使う） | `result_boxes`, `summary_box`, `report_details`, `prompt_box` |
| `app.py` | 641 | 1 画面版（Gradio）。`AppState`（Gradio に依存しない状態: 入力 → `convert` → `waiting_for_answer`/`apply_answer`（手動モード）→ `missing_images`/`add_images` → `needs_action`/`download` → `reset`）と `build_app(state, io)`（画面）、`launch()`（share は必ず False。Colab では `colab_embed` で iframe に埋め込む）。`answer_box_open`（手動の欄を見せるか。手動モードで作った結果のときだけ、`waiting_for_answer` に加え、`REPASTE_KEYS`〈`ai_error`・`partial`・`forced`・`float_ref`・`textbox_undecided`〉の Action が出ているあいだ。`Action` の key を直書きするので、`report.py` で key を変えるときは合わせる）。想定外の例外は `crash(error, operation)` で赤い枠にする（`report.actions()` の知らせではなく例外の表示）。`_run` は最初に前の結果を捨てる | `launch`, `AppState`, `build_app` |
| `tools/make_notebook.py` | 605 | 2 つのノートブック（従来版 9 手順、1 画面版 1 セル）を生成する。`REPO`/`BRANCH`/`DOCS`、手順ごとのセルの文字列、`ai_assist.py` から既定モデルを読む `module_constants` | `python tools/make_notebook.py [--branch]` |
| `tools/sanitize_docx.py` | — | docx からコメント・作成者情報を取り除く（リポジトリに docx を入れる前に通す） | CLI |

---

## 4. `pipeline.convert()` の段階（0.29.0）

`convert(docx_path, meta, journal, opts) -> Result`。以下の番号は `pipeline.py` の処理順。

1. **ルート2 の前処理**（`opts.route == "pdf"`）: `pdfdocx.make_fixed_docx` で補った docx を `pipeline.fixed_docx_path`（`out_dir/{aid}_PDFで補完した原稿.docx`。入力がそのファイルなら `_2` などの別名）に作り、
   `docx_fix.check.ok` なら以降の入力をそれに差し替える。PDF の文字を読めなければ `docx_fix = None` で元の docx を変換する（要対応 `pdf_fallback`）。
2. **機械処理** `_mechanical`: `read_docx` → `classify` → `link`。位置を決められない図表（`plan.unplaced_floats`）があり AI を使わない設定なら `AIRequiredError`（中止。終了コード 2）。
3. **1 回目の組み立て** `build`（AI 依頼文を作るのに BuildInfo の `exclusions`・`unsplit_names` が要る）。
4. **AI 補完**（`opts.ai_mode` が api / manual）: `build_request` → API 呼び出し、または `AI依頼文.txt` の書き出しと `--ai-response` の読み取り。
   回答が読めたら `role_overrides`・`float_placements` を作り、**`_mechanical` をやり直して**（docx を読み直し、役割の指定と配置を渡して組み立て直す）、
   `retarget_ops` で ID を読み替え、`apply_ops` でリンク等を適用し、**2 回目の `build`**。
5. **PDF との照合**（`opts.pdf_path` があれば。ルート1 でも）: `check_pdf`。ルート2 で Word が付ける番号の直し（`number_edits`）があれば `plan.pdf_numbers` に入れて **3 回目の `build`**。
6. **検証**: `verify` → `finalize` → `serialize` → `final_check` → `validate`。DTD が不合格で AI の数式（`FigNode.formula`）があれば、それを取り消してもう一度 build から検証まで。
7. **補完の確かめ**（ルート2 で補った docx があるとき）: `supplement_targets` → `verify_supplement`。
8. **画像の出力漏れ** `lost_images`。
9. **出力**: `export_images` → `jstage_check` → `write_package`（XML・PDF の配置と ZIP）→ `out_dir/{aid}.xml`。
10. **未解決の一覧の整理**: `linker.unresolved` から AI が解決したものを除き、仮に置いた図表・決められないテキストボックス・図の本体が見つからない図を足す（`unresolved_after`。レポート 3 章）。
11. **`Result` を作り**、レポート（`render`）と AI 判断一覧（`render_ai_only`）を書く。`zip_problems`・`unzipped_files` もここで計算する。

`add_images(res, supplied)` は、変換の後に利用者が用意した画像を `Graphics/` に入れ、`make_zip` で ZIP を作り直し、`zip_issues`・`not_zipped` とレポートを更新する。

### 利用者への知らせの経路

```
pipeline.Result ──▶ report.actions(res) ──▶ [Action(level, key, top, checklist, box_title, box_detail, cli), …]
                                              ├─ report.render: 冒頭の文（top）と 14 章（checklist）
                                              ├─ colab.result_boxes: 赤（要対応）・黄（要確認）の枠 ── 従来のノートブックと app.py の両方
                                              ├─ cli.main: 標準エラー（cli）と終了コード（Result.needs_action）
                                              ├─ app.AppState.needs_action / todo_titles: 「ZIP を保存」の前に一度止める
                                              └─ app.AppState.answer_box_open: 手動モードで作った結果（依頼文がある）で、ai_error・partial・forced・float_ref・textbox_undecided があるあいだ手動の欄を見せる
```

知らせを足すときは `report.py` に `_xxx_action(res) -> Action | None` を作り、`actions()` の並びに加えるだけ（DEVELOPMENT.md の原則 8）。
`box_detail` の画面の操作は目印 `report.step()` で書き、枠を作るとき（`colab._box`・`result_boxes` の `screen` 引数）に `colab.STEP_WORDS` の語
（`notebook`・`app`・`cli`）へ置き換える。1 画面版の想定外の例外の枠（`app.AppState.crash`）は、この経路を通らない。

---

## 5. ルート2（docx から作り、出版版 PDF で補う）の流れ

```
元の docx ──▶ pdfdocx.make_fixed_docx
               ├─ _mechanical（read_docx + classify + link。照合に段落の役割・リンク・注の鍵が要る）
               ├─ pdfmatch.check_pdf（PDF の文字を取り出し、段落ごとに照合して (A)(B)(C) に分ける）
               ├─ plan_fixes（段落ごとの Fix。直さない理由 reason も記録）
               ├─ _Writer.run（元の XML のランを分けて w:del / w:ins を書く。脚注・文末脚注の XML にも）
               ├─ _verify（読み直した段落の文字が、期待どおりか）・_structure（役割・領域・リンク・注の区切りが元と同じか）
               │    └─ 合わない段落は Fix を外して書き直す
               └─ DocxFix（path, fixes, check）
補った docx ──▶ convert の 2〜6（ルート1 と同じ）── 5 で Word の番号を PDF に合わせる（plan.pdf_numbers）
              ──▶ fidelity.verify_supplement（元の docx と補った docx を比べ、変更履歴の単位が (A) か報告した (B) だけか）
レポート 13 章: 13.1 補った校正の直し / 13.2 組版の違い / 13.3 直さなかった箇所と理由 / 13.4 Word の番号 / 13.5 残る違い / 13.6 見つからない段落 / 13.7 照合に使わなかった PDF の文字 / 13.8 補完の確かめ
```

---

## 6. 画面と pipeline の関係

| 画面 | ファイル | 呼ぶもの |
|---|---|---|
| コマンドライン | `cli.py` | `convert` → 結果の表示 → `add_images`（`--images`）→ `actions` を標準エラーへ → 終了コード |
| 従来のノートブック（手順 1〜9） | `notebooks/JASME_docx_to_JSTAGE_XML.ipynb`（`tools/make_notebook.py` が生成） | 手順 1 pip と LibreOffice / 2 アップロード / 3 書誌情報 `ArticleMeta.from_dict` / 4 AI の選択 / 5 `convert` と `colab.result_boxes` など / 6 手動モードの回答を貼って `convert` / 7 `add_images` / 8 ダウンロード（要対応なら一度止める）/ 9 次の論文 |
| 1 画面版（Gradio） | `notebooks/JASME_docx_to_JSTAGE_XML_GUI.ipynb`（同上）→ `app.launch()` | `AppState` が同じ `convert`/`add_images` を呼ぶ。表示は `colab.py` の部品 |

ノートブックは実行のたびに GitHub の `main` から pip で入れる（`BRANCH`）。`main` に入れた変更はすぐ利用者に届く。

---

## 7. テストの地図

`python -m pytest -q`（0.29.0 で 1272 件）。各ファイルが何を守っているかの詳細は `docs/DEVELOPMENT.md` の「テスト」。

| テスト | 守っている動き |
|---|---|
| `test_reader.py` | 読み取りの文字が検証側（canonical_texts）と一致、文字ポリシー（段落記号の削除・隠し文字・削除された行）、テキストボックスの記録 |
| `test_fidelity.py` | わざと壊した XML を不変性チェックが必ず検出する |
| `test_structure.py` / `test_article.py` | 領域の分け方、資料の見出し、囲み・注記、循環 import がない |
| `test_floats.py` / `test_figure_body.py` | 浮動配置の図表の配置と組み方、仮の位置、表のセルの図 |
| `test_links.py` / `test_refparse.py` / `test_notes.py` | リンクの規則（注・図表・引用）、注の書き方、Word の脚注・文末脚注 |
| `test_ai.py` | AI の回答の検証と適用、途中で切れた回答、4 社の呼び出し（偽のクライアント） |
| `test_pdfmatch.py` / `test_supplement.py` | PDF との照合、ルート2 の直し、組版で入る文字、補完の確かめ |
| `test_pipeline.py` / `test_lost_images.py` / `test_jstage_rules.py` | 全体の流れ、ZIP の中身、終了コード、画像の出力漏れ、J-STAGE チェック |
| `test_colab.py` / `test_app.py` / `test_notebook.py` | 表示部品、1 画面版の状態、ノートブックが最新か（版・既定モデル） |
| `test_omml.py` | 数式の変換 |
| `test_syntax.py` | Python 3.10 でも読める書き方か（f 文字列の式の中のバックスラッシュ・同じ引用符。全 `.py` のコンパイル）、レポートに生のタグがないか |

fixture の docx は `tests/make_fixtures.py` が作る（架空の内容。`make_article()` でテストの中でも小さな論文を作れる）。
実際の論文は `tests/private/`（`.gitignore` 済み）にだけ置く。CI は `.github/workflows/test.yml`（Python 3.10 / 3.12）。

---

## 8. 逆引き: 変えたいときはどこを見るか

| やりたいこと | 見る所 |
|---|---|
| 新しいスタイル名を役割に対応させる | `data/jasme.toml` の `[styles]`（コードは変えない） |
| 役割の推定の規則（番号の形・見出しの推定）を変える | `structure.py` の `RE_*`、`guess_heading`、`role_of`。判断は `plan.decide` に記録 |
| 領域（本文 / 後付け / 英文の部分）の切り替えを変える | `structure.Classifier.split_regions`（文字から推定した「注」の本文への戻しは `fn_guess`・`check_fn_guess`）、`back_heading_by_text`、`outside_key` |
| 図表の配置（浮動配置）の規則を変える | `floats.at_anchor`（機械的に置ける条件）、`structure.place_floats`、`provisional_target` |
| 囲み / 図の注記のしきい値を変える | `floats.textbox_kind` の定数（`BOX_CHARS` など）、`structure.place_boxes` |
| リンクの規則（図表・注・引用）を変える | `linker.py`（`float_refs`、`float_numbers`〈重なる番号・枝番〉、`_sup_marks`、`note_style`）、`refparse.py`（引用）。枝番の定義は `structure.CAP_BRANCH_SEP`・`CAP_BRANCH_NUM`（builder の `RE_LABEL_SPLIT` と共有） |
| XML の要素・属性の出し方を変える | `builder.py`（要素の並び）、`emit.py`（文字・書式・リンク。`Ctx`） |
| 文字を書く文脈の制限（例: 所属で使える書式）を変える | `emit.py` の `Ctx` 定数（TITLE・NAME・AFF・REF…）。`article.no_link_paras` も合わせる |
| docx の新しい要素（例: 新しい種類のフィールド）に対応する | `ooxml.canonical_text`（検証）と `docx_reader._walk`/`_run`（読み取り）、`pdfdocx.paragraph_units`（ルート2）の 3 か所を同じ規則で。fixture を足す |
| 隠し文字・段落のつながりの規則を変える | `ooxml.HiddenRule`、`ooxml.joined_paragraphs`（3 か所が共有。単体テストで確かめる） |
| 利用者への知らせ（要対応・要確認）を足す | `report.py` に `_xxx_action` を作り `actions()` に加える。画面側は触らない。画面の操作は目印 `step()`、レポートの生のタグは `md_tag()` |
| 画面ごとの操作の語（手順番号・欄の名前）を変える | `colab.STEP_WORDS`（1 か所の表）。目印の名前を足すなら `report.STEP_NAMES` と全画面の語 |
| レポートの章を変える | `report.render`（章ごとに `L.append`）。13 章は `render_route1`/`render_route2` |
| ZIP に入れるものを変える | `package.upload_entries`（1 か所）と `zip_problems`（確かめ） |
| 画像の形式の対応を増やす | `images.export_images`（`DIRECT`・`PILLOW`・`METAFILE`） |
| J-STAGE のチェックを足す | `jstage_rules.check`（XML で判定できるもの）、`package.zip_problems`（ZIP の形） |
| AI の依頼内容・操作の種類を変える | `ai_assist.SYSTEM_PROMPT`、`RESPONSE_SCHEMA`/`OP_SCHEMA`、`apply_ops`、`set_role_problem` |
| 既定の AI モデルを変える | `ai_assist.DEFAULT_MODEL`・`DEFAULT_MODEL_INFO` → `python tools/make_notebook.py` |
| API モードの AI を増やす | `ai_assist.call_xxx` を足し `PROVIDERS`・`API_KEY_NAMES`・`call_provider`、`cli.py` の `--ai-provider`、ノートブック手順 4 |
| PDF との照合の分類（(A)(B)(C)）を変える | `pdfmatch._classify`/`_report_regions`、`typeset_pair` と定数表。`fidelity._pair` も同じ答えになるように（`test_supplement.py`） |
| 組版で入る文字（柱・受付日）の扱いを変える | `pdfmatch.pdf_stream`、`RE_RECEIVED`、`MIN_CHARS` |
| ルート2 の docx への書き込みを変える | `pdfdocx._Writer`。書いた後の `_verify`・`_structure` を外さない |
| 書誌情報の入力の確かめを変える | `config.ArticleMeta.from_dict`、`_id_value`、`_date` |
| ノートブックの文言・セルを変える | `tools/make_notebook.py` → `python tools/make_notebook.py`（ipynb は直接編集しない） |
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
| 除外 / Exclusion | XML に出力しない段落。必ず理由付きで記録し、レポート 6 章に全文を載せる |
| 生成文字 | docx の文字ではなく Word が表示時に作る文字（自動番号・脚注番号・補った注の見出し）。`jx:gen` |
| 不変性チェック | docx の文字と XML の文字を 1 文字ずつ照合すること（`fidelity.verify`） |
| 浮動配置の図形 / Float | テキストボックス・グループ図形で、本文の段落（アンカー段落）に結び付いて浮いているもの（`s1…`） |
| 文字だけのテキストボックス | 画像・表・キャプションを含まないテキストボックス。囲み（`<boxed-text>`）/ 図の注記（除外）/ 決められない（除外して要確認） |
| 位置を決められない図表 | 機械的に置けず AI に位置を指定させる図表。回答がなければ仮の位置（アンカー段落の後ろ・本文の最後） |
| 判断 / Decision | 機械処理・AI の判断の記録（レポート 2・4 章、AI 依頼文の「推定:」） |
| 要対応 / 要確認 | 利用者への知らせの 2 段階（`report.Action.level`）。要対応は終了コード 1 とダウンロード前の一時停止、要確認は黄色い枠だけ |
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
- `grep -n "暫定" src/jasme_jats/*.py` で、コードの中の暫定の判断の場所が出る（0.29.0 で 20 か所）。
