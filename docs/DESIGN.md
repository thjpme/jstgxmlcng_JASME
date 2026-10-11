# 設計

## 1. 目的と最優先の要件

- 入力: 『全国数学教育学会誌 数学教育学研究』のテンプレート（`tests/fixtures/JASME_template_20261009.docx`）で作成された論文の docx
- 出力: J-STAGE 全文 XML（JATS 1.1 Journal Publishing、FULL-J）と、J-STAGE のアップロード用フォルダ構成の ZIP、変換レポート
- **最優先: docx の本文の文字を 1 文字も変えない**（誤字脱字も直さない）。リンクの誤りは許容されるが、少ないほどよい。

## 2. 実行環境の選択（Google Colab）

| 案 | 利点 | 欠点 |
|---|---|---|
| **Google Colab のノートブック（採用）** | ブラウザと Google アカウントだけで動く。ノートブックが毎回 GitHub から最新のコードを入れるので、コードの写しが散らばらない。ファイルは利用者自身の一時的な実行環境で処理される | 実行のたびに準備（1〜3 分）が要る |
| Web アプリ（Streamlit 等を常時公開） | 最も簡単に使える | サーバーの維持・費用・管理者が必要。未公開原稿を外部サーバーに上げることになる |
| GitHub Actions で変換 | 記録が自動で残る | 原稿をリポジトリに置く必要がある（公開リポジトリでは不可） |
| 配布用の実行ファイル | オフラインで動く | OS ごとの作成・更新が必要。EMF 変換の LibreOffice を同梱できない |

変換の本体は Python のパッケージ（`src/jasme_jats/`）で、Colab のノートブックはその薄い操作画面にすぎない。
同じパッケージがパソコンのコマンドラインでも、GitHub Actions のテストでも動く。

## 3. 処理の流れ（`pipeline.py`）

1. **読み取り**（`docx_reader.py`）: docx の XML を直接読み、段落を「アトム」（文字・数式・画像・脚注参照・生成文字）の列にする。
2. **構造化**（`structure.py`）: スタイル名から段落の役割を決め、題目・著者・本文（章節項）・図表・注・文献・英文要旨・資料の構造（`ArticlePlan`）を組み立てる。
   スタイルが想定外の段落は、番号の形式などから機械的に推定し、`Decision` として記録する。
3. **機械的リンク**（`linker.py`, `refparse.py`）: 図・表・数式・注・引用文献・URL・DOI。
4. **AI 補完（任意）**（`ai_assist.py`）: AI が返した操作を検証し、構造の組み直しとリンクの追加として適用する。
5. **XML の組み立て**（`builder.py`, `emit.py`）
6. **文字の不変性チェック**（`fidelity.py`）… AI 補完を行った場合も必ずここで行う
7. **最終出力の再チェック**: 目印を取り除いた XML を直列化して読み直し、文字列が検証済みの木と一致することを確かめる
8. **DTD 検証**（`validate.py`）: 同梱の J-STAGE 指定 DTD
9. **画像・ZIP・レポート**（`images.py`, `package.py`, `report.py`）

## 4. 文字を変えないしくみ

### 4.1 文字ポリシー（`ooxml.py` の冒頭）

「docx の文字」を次のように定義する。

- 含める: `w:t`、数式中の `m:t`、タブ（`w:tab` → タブ文字）、改行（`w:br`, `w:cr` → 改行文字）、`w:noBreakHyphen`、`w:softHyphen`、`w:sym`（Symbol フォントは Unicode に対応付け）
- 含めない: 削除された変更履歴、フィールドコード、隠し文字、ページ区切り、ルビの読み、テキストボックス内の段落（別の段落として扱う）
- Word が自動生成する文字（自動段落番号・脚注番号）は docx の文字ではない。XML では「生成文字」として区別し、レポートに記録する。

### 4.2 変換中の目印と照合

- 中間表現は、段落の文字をアトムの列として持つ。リンク付けはアトムに `LinkSpec` を付けるだけで、文字列は変えない。
- XML の組み立てでは、段落の文字を必ず `<jx:span src="段落ID" seq="n">` の中に書く（`tracking.py`）。
- `fidelity.verify()` は、docx から **別の実装**（`ooxml.canonical_text()`）で段落ごとの文字列を取り出し、XML の `jx:span` の文字列と比較する。
  - すべての段落が、XML に出力されているか、出力しない理由（`Exclusion`）が記録されているか
  - 目印の外に文字がないか（docx にない文字の追加の検出）
  - 構造の区切りとして落とした文字（`jx:drop`）が空白だけか
  - 同じ段落を二重に出力していないか
- 照合後に目印を取り除き（タグを外すだけ）、直列化した最終出力を読み直して、文字列が一致することを `final_check()` で確かめる。
- `tests/test_fidelity.py` で、わざと文字を変える・段落を消す・文字を足す・段落を二重にする、などの改変がすべて検出されることを確かめている。

### 4.3 出力しない文字・落とす空白・生成文字

- 出力しない段落（`Exclusion`）: テンプレートの誌名行・装飾行（❚❚❚）、空白だけの段落、重複する所属、図の一部とみなしたテキストボックスの文字など。レポートに全文を載せる。
- 落とす空白（`jx:drop`）: 姓と名の間（JATS では `<surname>` と `<given-names>` に分けるため）。`split_labels = true` のときは図表番号・章番号・注番号とタイトルの間も。空白以外は落とさない。
- 数式: OMML では属性で表される括弧などの記号は MathML の `<mo>` になるため、`jx:implicit` を付けて照合から除く。根号の指数のように MathML で順序が入れ替わる文字は、`jx:o`（docx 上の順序）で並べ直して照合する。

## 5. AI 補完の設計

- AI には XML も docx も直接編集させない。AI が返すのは操作の一覧（JSON。`ai_assist.RESPONSE_SCHEMA`）だけ。
- 操作の種類: `link_citation`（年の部分のみ）/ `link_figure` / `link_table` / `link_note` / `link_formula` / `set_role` / `formula_image` / `split_name`
- プログラムによる検証（`apply_ops`）:
  - 対象の段落・文字列（完全一致）・リンク先が存在するか
  - 引用文献へのリンクの文字列が「年」か（利用者の指定した規則を機械的に強制する）
  - 数式・画像をまたがないか、既存のリンクと重ならないか
  - 役割の指定がその位置で可能か
  - MathML が MathML の要素だけでできているか（それ以外の要素は不採用、未知の属性は除去）
  - 姓 + 名 が氏名の文字列と一致するか
- `set_role` を含む場合は、docx を読み直して構造を最初から組み立て直してから、他の操作を適用する。
- 数式画像は、元の画像を残したまま AI が読み取った MathML を `<alternatives>` で併記する。これは docx の文字ではないため `<jx:ai>` で囲み、
  不変性チェックでは「追加」と扱わず、レポートに別枠で一覧を出す。DTD に合わない場合は自動で取り消す。
- API モードと手動モードは、依頼文の作り方と回答の受け取り方が違うだけで、検証・適用・最終チェックは同じ。
- API の呼び出し（Claude）: 既定モデル `claude-opus-5-5`、構造化出力（JSON スキーマ）、`effort: high`、ストリーミング、拒否時のサーバー側フォールバック（`fallbacks: "default"`）。
- モデル: 既定は動作確認済みの `claude-opus-5-5`（提供終了は 2027-09-22 以降の予定）。指定したモデルが見つからない（提供終了など）ときは、Models API の一覧から最新の Opus を選んで 1 回だけやり直し、レポートに記録する。`auto`（Colab の「自動（最新の Opus）」）では、はじめから最新の Opus を使う。
- API モードの入口は `ai_assist.call_provider()`。Claude（推奨・`call_api()`）のほか、ChatGPT（`call_openai()`。OpenAI の Responses API）、
  Gemini（`call_gemini()`。Google の Gemini API）、Sakana AI（`call_sakana()`。Sakana Namazu・Fugu の OpenAI 互換 Chat Completions API、
  接続先 `https://api.sakana.ai/v1`）に対応する。どれも依頼文と画像を渡して JSON の文字列（`AIOutcome.raw`）を受け取るだけで、
  検証・適用・最終チェックは共通。回答は同じ JSON スキーマ（`RESPONSE_SCHEMA`）で受け取る（OpenAI は strict の json_schema、
  Gemini は `response_json_schema`、Sakana AI は `response_format` の json_schema。Sakana AI では受け付けられなければ指定なしで
  1 回だけやり直し、依頼文に入れた回答の形式（見本と項目の説明）で JSON を返させる）。
- OpenAI 互換の接続先（Sakana AI）には、API キーを必ず明示して渡す（環境変数 `OPENAI_API_KEY` の OpenAI のキーを別の会社に送らないため）。
- Sakana AI は既定で送信内容を学習に使う設定なので、ノートブックで選んだときに、学習への利用を止める（オプトアウトする）よう赤い枠で注意する。
- Claude 以外では、モデルを利用者が指定する（既定値を持たない。モデルの入れ替わりが速く、動作確認もしていないため）。
  Claude Opus と同等以上の性能のモデルを推奨する。API キーの作り方などは利用者が各社の案内で調べる（ノートブックでは説明しない）。
- 推奨を Claude とする理由: 依頼文（`SYSTEM_PROMPT`）と回答の検証を Claude で試して調整しているため。他社のモデルでも、誤った提案は
  検証で捨てられるので本文の文字は変わらないが、補完の効果は下がりうる。

## 6. J-STAGE に合わせた主な判断

| 項目 | 判断 | 理由 |
|---|---|---|
| DOCTYPE・ルート要素 | J-STAGE マニュアルの固定値 | マニュアル 3.3.3 |
| 題目 | 本文の言語の題目を `<article-title xml:lang>`、もう一方を `<trans-title-group xml:lang><trans-title>` | J-STAGE は article-title を「タイトル」、trans-title を「翻訳タイトル」として、xml:lang で日・英を判定する |
| 英文要旨 | 和文の論文では `<trans-abstract xml:lang="en">`、英文の論文では `<abstract xml:lang="en">` | J-STAGE では「抄録(英)」（abstract）には「タイトル(英)」（article-title）、「翻訳抄録(英)」（trans-abstract）には「翻訳タイトル(英)」（trans-title）が必要（アップロードメッセージ EMSGM102E/104E）。和文の論文で英文要旨を abstract にすると「英語タイトルがない」エラーになる。ガイドライン 3.1.23 の例も和文論文の英文抄録は trans-abstract。本誌には和文要旨がない |
| 抄録の `specific-use` | 設定ファイルの値（既定 `secondary-disallow`） | 抄録ライセンスフラグ。DTD・ガイドライン上 `<abstract>` にだけ付けられ、`<trans-abstract>` には付けられない（和文の論文では出力されない）。学会の方針で決める |
| 引用文献の `xml:lang` | かな・漢字を含む文献は `ja`、それ以外は `en` | J-STAGE の「引用文献（記述言語）」（未設定だと EMSGM247E） |
| 記事種別・原稿種別 | `<article article-type="other">`（その他）。原稿種別は `<subj-group subj-group-type="article" xml:lang="ja|en">`。Colab の手順 3 で「論文 / Article」「共同研究 / Collaborative Research Report」「講演記事 / oration」「その他（自由入力）」から選ぶ | 学会の指定。選択肢は設定ファイルの `[manuscript_types]`（変えたらノートブックを作り直す） |
| キーワード | 任意。Colab の手順 3 で日本語・英語を別々の欄に入力（「;」「；」区切り）。`kwd-group xml:lang="ja"` と `xml:lang="en"` | docx にキーワードの欄がないため。J-STAGE の上限は日・英あわせて 100 個（EMSGM149E。超えたら手順 3 で止める）。日本語の欄に英語だけのもの、英語の欄にかな・漢字を含むものがあれば、取り違えの確認を促す |
| 査読の有無 | 利用者が必ず入力（Colab の手順 3 で選ばないと先に進めない）。査読ありは `<history><date date-type="approved">`（最終査読日。分からなければ年月日を空に）、査読なしは `<date date-type="accepted as received">`（年月日を空に） | ガイドライン 3.1.30。どちらも書かないと資料の査読あり/なしの設定が引き継がれるため、記事ごとに明示する |
| 登載時チェックの再現 | `jstage_rules.py` で、アップロードメッセージ一覧のうち XML だけで判定できるもの（題目と抄録の言語の対応、日付の前後、所属番号の連番、DOI の文字、画像ファイル名など）を確かめ、レポート 12 章に出す | DTD に合っていても J-STAGE で弾かれる条件があるため |
| 図表番号 | 既定は caption の中に番号ごと入れる | 文字を落とさないため（`split_labels` で切替） |
| 引用文献 | `<mixed-citation>` に原文をそのまま入れ、年・論文名・誌名・DOI・URL にだけタグを付ける | J-STAGE は mixed-citation の文字をそのまま表示する。タグは文字を変えない |
| 文献中の DOI | 既定（設定 `ref_doi = "pub-id"`）は `https://doi.org/` の部分を文字のまま、`10.…` の部分を `<pub-id pub-id-type="doi" xlink:href>` にする。`ref_doi = "uri"` では「https://doi.org/10.…」の文字全体を `<uri xlink:href>` にする。Word のハイパーリンクが付いていても、表示文字が URL そのもの（または同じ DOI）なら同じ形にする | J-STAGE の mixed-citation の子要素は uri・pub-id などで ext-link は使えず、同じ文字をリンクと DOI の両方にはできない。ガイドラインは pub-id を推奨（引用文献リンクの反映率が上がる）。2026-10 の試験登載では pub-id は画面上リンクにならなかったが、DOI としての登録を優先する（uri にした場合も、編集登載システムで DOI 欄に手入力すれば登録できる） |
| 本文中の URL | `<uri xlink:href>`（注・付記・資料では `<ext-link>`） | J-STAGE マニュアルの子要素構成 |
| 注 | `<fn-group>`。本文の上付き「1)」を `<xref ref-type="fn">`。注の番号は `<fn>` の `<p>` の先頭に入れる（Word の自動番号・脚注番号は生成した文字として。手で打たれた番号は docx の文字のまま） | テンプレートの注の書き方。J-STAGE の注は子要素が `<p>` だけで、`<label>` は表示されない（2026-10 の試験登載で確認） |
| 付記 | `<notes>` | J-STAGE の「注釈」 |
| 資料 | `<app-group>` | J-STAGE の「付録」 |
| 画像ファイル名 | `{巻}_{開始ページ}_{連番2桁}.png` | J-STAGE フォルダ構成（連番を 0 埋めすると表示順が揃う） |
| アップロード用 ZIP の名前 | `{資料コード}_{記事識別子}.zip`（例: `jasme_31_1.zip`） | 複数の論文を続けて変換しても名前が重ならないように。フォルダ構成の資料（別紙 2）の `{資料コード}.zip` に記事識別子を足した。J-STAGE が確かめるのは中のフォルダ構成で、名前のエラーは日本語のファイル名（EMSGM034E）だけ。2026-10 の試験登載で、この名前で受け付けられることを確認（`docs/JSTAGE_NOTES.md`） |
| 著作権表記・ライセンス | 出力しない | J-STAGE の資料の設定が使われる |

## 7. 既知の限界

- Word の図形・グループ図形・グラフは画像化できない（PDF などから画像を用意する）。
- ルビは親文字のみ。
- 引用の抽出は著者・年方式と `[1]` 形式の番号方式。上付き番号の引用方式には未対応（AI 補完で補える）。
- 段落の役割の推定は、番号の形式（「１．」「(1)」「①」）と隣接する画像・表からの規則による。
