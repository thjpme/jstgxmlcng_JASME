# J-STAGE の仕様の要点（本ツールに関係する部分）

確認日: 2026-10-10

## 出典

- J-STAGE 全文 XML 利用者向けマニュアル（JATS 1.1）
  https://www.jstage.jst.go.jp/static/pages/GuidelineAndManuals/zenbun-xml-jats1_1-manual/-char/ja
- J-STAGE XML データフォーマットガイドライン（JATS1.1 版）第 2.4 版（2026/07/30）
  https://www.jstage.jst.go.jp/static/files/ja/jstage_xml_jats1_1_format_guideline.pdf
- （別紙 1）修飾タグ処理仕様
  https://www.jstage.jst.go.jp/static/files/ja/jstage-xml_jats1_1_attachment1.pdf
- 別紙 2（記事アップロードフォルダ構成）
  https://www.jstage.jst.go.jp/static/files/ja/UM-01-004_sousa(henshu)_append2.pdf
- 別紙 3（記事アップロードメッセージ一覧）… `jstage_rules.py` のチェックの出典
  https://www.jstage.jst.go.jp/static/files/ja/UM-01-004_sousa(henshu)_append3.pdf
- J-STAGE 操作マニュアル 編集登載編（巻号・セクションの作成、記事アップロード）
  https://www.jstage.jst.go.jp/static/files/ja/UM-01-004_sousa(henshu).pdf
- XML 項目一覧（メタデータ項目と文字数の上限）
  https://www.jstage.jst.go.jp/static/files/ja/jstage-xml_jats1_1-metadata_item_list.pdf
- FULL-J XML サンプル
  https://www.jstage.jst.go.jp/html/files/GuidelineAndManuals/TAB2/20190529/ja/full-j_johokanri.zip
- J-STAGE 指定 DTD: https://www.jstage.jst.go.jp/dtds/1.1/JATS-journalpublishing1.dtd
  （`src/jasme_jats/dtd/` に同梱。NLM の JATS 1.1 Journal Publishing DTD と同一であることを確認済み。DTD はパブリックドメイン）
- 本誌の J-STAGE 資料トップ: https://www.jstage.jst.go.jp/browse/jasme/-char/ja

## 要点

- XML 宣言・DOCTYPE は固定値。ルート `<article>` の名前空間（xsi, mml, xlink, ali）、`dtd-version="1.1"`、`article-type`、`xml:lang` は必須。
- XML は JATS 1.1 の DTD で妥当である必要がある（ガイドライン 1 章）。
- `<journal-id journal-id-type="j-stage">` と `<issn>` は必須。雑誌名などは J-STAGE 側で上書きされる。
- 著者は `<name-alternatives>` に和英の `<name>`。所属は `<aff-alternatives id="aff1">` に和英の `<aff>`、著者からは `<xref ref-type="aff" rid="aff1">`。
- 題目: `<article-title>` が「タイトル」、`<trans-title>` が「翻訳タイトル」。日・英は xml:lang で判定される。
- 抄録: `<abstract>` が「抄録」、`<trans-abstract>` が「翻訳抄録」。それぞれ 1 つまで（ガイドライン 3.1.23）。
  **「抄録(英)」には「タイトル(英)」、「翻訳抄録(英)」には「翻訳タイトル(英)」が必要**（アップロードメッセージ EMSGM102E〜105E）。
  和文の論文では英語の題目が翻訳タイトルなので、英文要旨は `<trans-abstract xml:lang="en">` にする
  （`<abstract xml:lang="en">` にすると「抄録(英)が設定されていますが、タイトル(英)が設定されていません」で弾かれる）。
- `<abstract>` の `specific-use` は抄録ライセンスフラグ（secondary-allow / secondary-disallow）。`<trans-abstract>` には付けられない。
- 引用文献 `<ref>` の `xml:lang`（記述言語）がないと EMSGM247E。
- 文字数の上限: 抄録・翻訳抄録 4000（p の合計）、記事表題 2000、引用文献（mixed-citation）4000。
- `<label>` の自動付番は行われない。番号を表示したい場合は label か本文に書く。
- `<mixed-citation>` の中の文字・空白・句読点はそのまま表示される。引用文献原文は「label + 半角空白 + mixed-citation の文字」で登録される。
  → 本ツールは mixed-citation の中で改行や字下げを入れない（入れると文字が変わる）。
- 引用文献の DOI は `https://doi.org/` 形式ではなく `10.` から始まる形式で `<pub-id pub-id-type="doi">` に書くと、引用文献リンクの反映率が上がる（ガイドライン）。ただし 2026-10 の試験登載では、pub-id の DOI は画面上リンクにならなかった。
  本ツールの既定は `<uri>`（設定 `ref_doi`）。`<mixed-citation>` の子要素に `<ext-link>` は使えない（マニュアルの子要素構成）。
- 画像は jpg / gif / png（mp4 も可）。`Graphics/` に置き、XML ではファイル名だけを書く。ファイル名を「記事識別子.」で始めてはいけない。
- アップロードの前に、編集登載システムで巻・号と、その号のセクション（目次の見出し。例: 論文）を作成しておく
  （操作マニュアル 編集登載編のフロー A-2・A-3）。ないと EMSGM181E「巻号が学会誌別巻号の設定に存在しません」、
  EMSGM182E「学会誌別セクションが存在しません」。アップロード後、記事をセクションに振り分ける（A-6 記事移動）。
  これは J-STAGE 側の設定で、XML では指定できない。
- フォルダ構成: `{資料コード}/{巻}/{号}/{記事識別子}/`。記事識別子は `{巻}_{開始ページ}`（論文番号がない場合）。ZIP 名は `{資料コード}.zip`。PDF は必須。

## 本誌の値（設定ファイル `src/jasme_jats/data/jasme.toml`）

- 資料コード `jasme`、Print ISSN 1341-2620、Online ISSN 2433-3034
- 誌名 「数学教育学研究 : 全国数学教育学会誌」/ "Journal of JASME : research in mathematics education"
- 発行機関 全国数学教育学会 / Japan Academic Society of Mathematics Education
- DOI の形式 `10.24529/jasme.{巻}.{号}_{開始ページ}`（例: 10.24529/jasme.30.2_59）
- 本誌には和文要旨がない（英文要旨のみ）
