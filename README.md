# jstgxmlcng_JASME — 論文 docx を J-STAGE 全文 XML に変換するツール

『全国数学教育学会誌 数学教育学研究』（J-STAGE 資料コード `jasme`）のテンプレートで作成された論文（Word の .docx）を、
J-STAGE の全文 XML（JATS 1.1、FULL-J）に変換します。

- **本文の文字は 1 文字も変えません**（誤字脱字も含めてそのまま）。変換の最後に、docx と XML の文字を 1 文字ずつ照合して確かめます。
- 受け取った docx が出版版と違うときは、先に出版版 PDF から著者校正の直しと組版の違いを補った docx（Word の変更履歴つき）を作り、
  それを変換することもできます（[docs/USAGE.md](docs/USAGE.md) の「出版版 PDF との照合と、2 通りの作り方」）。
- 見出し・本文・図表・ブロック引用・注・謝辞・付記・引用文献・英文要旨などを、テンプレートのスタイルから機械的に変換します。
- 本文中の「図1」「表2」、注の上付き番号、引用（`Claude (2025)` の **2025 の部分だけ**）、URL・DOI に機械的にリンクを付けます。
- 機械処理で取りこぼした箇所（スタイルの誤り、変則的な引用、画像で貼られた数式など）は、任意で生成 AI（Claude）に補完させられます。
  AI は文字を変更できず、提案はプログラムが検証してから反映します。AI が判断した箇所はレポートに一覧で出ます。
- 出力は J-STAGE のアップロード用フォルダ構成の ZIP と、変換レポートです。

## 使い方（Google Colab。パソコンへのインストールは不要）

ノートブックは 2 つあります。どちらも同じツールで変換し、結果は同じです。

| | ノートブック | 使い方 |
|---|---|---|
| **一般の利用者用（1 画面）** | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/thjpme/jstgxmlcng_JASME/blob/main/notebooks/JASME_docx_to_JSTAGE_XML_GUI.ipynb) | セルを 1 つ実行すると画面が開きます。画面に docx と PDF、書誌情報を入れて「変換する」を押し、「ZIP を保存」で結果を受け取ります |
| 従来版（手順ごとのセル） | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/thjpme/jstgxmlcng_JASME/blob/main/notebooks/JASME_docx_to_JSTAGE_XML.ipynb) | 手順 1〜9 のセルを上から順に実行します。入力欄の値を残したまま続けて変換するときや、1 画面版がうまく開かないときに使います |

1. 上のボタンからノートブックを開きます（Google アカウントが必要）。
2. 論文の docx（と出版版の PDF）をアップロードし、巻・号・ページなどの書誌情報を入力して、変換します。
3. 結果（`変換結果_巻_開始ページ.zip`）をダウンロードし、その中の `jasme_巻_開始ページ.zip` を J-STAGE の編集登載システムにアップロードします。

手順の詳細・結果の見方・できないことは **[docs/USAGE.md](docs/USAGE.md)**、AI の API キーの作り方と手動モードの手順は
[docs/USAGE_AI.md](docs/USAGE_AI.md) にあります。

## しくみ（要点）

```
docx ─読み取り→ 中間表現 ─スタイルで構造化→ ─機械的リンク→ ┬─────────────→ XML 組み立て ─ 文字の不変性チェック ─ 目印を除去 ─ 最終チェック ─ DTD 検証 ─ ZIP・レポート
                                                      └─ AI 補完（任意）: AI は「操作」の JSON を返すだけ → Python が検証して適用 ┘
```

- 段落の文字は「アトム」の列として保持し、リンクや書式は文字を包む要素として付け加えるだけにしています。文字列を書き換える処理はありません。
- 変換途中の XML では、各段落の文字を `<jx:span src="段落ID">` で囲んでおき、docx から別の実装で取り出した文字列と段落ごとに照合します。
  照合が済んでから目印を取り除き、取り除いた後の XML でもう一度文字列を照合します。
- AI に XML や docx を直接編集させることはありません。AI が返すのは「この段落のこの文字列を文献 B3 にリンクする」といった操作の一覧で、
  プログラムが 1 件ずつ検証します（存在しない文字列・リンク先、年以外へのリンクなどは不採用としてレポートに記録）。

詳しくは [docs/DESIGN.md](docs/DESIGN.md) を参照してください。

## ローカル（パソコン）で使う場合

Python 3.10 以上が必要です。

```bash
pip install "jasme-jats[ai,images] @ git+https://github.com/thjpme/jstgxmlcng_JASME.git@main"
python -m jasme_jats 論文.docx --meta 書誌情報.toml --out output            # AI を使わない
python -m jasme_jats 論文.docx --meta 書誌情報.toml --out output --ai manual  # 手動モード（依頼文を作る）
python -m jasme_jats 論文.docx --meta 書誌情報.toml --out output --ai manual --ai-response 回答.json
ANTHROPIC_API_KEY=... python -m jasme_jats 論文.docx --meta 書誌情報.toml --out output --ai api
OPENAI_API_KEY=... python -m jasme_jats 論文.docx --meta 書誌情報.toml --out output --ai api --ai-provider openai --ai-model モデル名
GEMINI_API_KEY=... python -m jasme_jats 論文.docx --meta 書誌情報.toml --out output --ai api --ai-provider gemini --ai-model モデル名
SAKANA_API_KEY=... python -m jasme_jats 論文.docx --meta 書誌情報.toml --out output --ai api --ai-provider sakana --ai-model モデル名
python -m jasme_jats 論文.docx --meta 書誌情報.toml --out output --images 画像フォルダ   # 用意できなかった図の画像（25_77_01.png など）を入れる
python -m jasme_jats 論文.docx --meta 書誌情報.toml --out output --pdf 記事.pdf               # 出版版 PDF に合わせてから作る
python -m jasme_jats 論文.docx --meta 書誌情報.toml --out output --pdf 記事.pdf --route docx  # docx から作る（PDF とは照合だけ）
```

書誌情報ファイルの例: [examples/meta_example.toml](examples/meta_example.toml)

コマンドラインの終了コードは、**0 が要対応なし、1 が要対応あり、2 が変換の中止**です（要対応・要確認の一覧は標準エラーに出します。
要確認だけなら 0）。次の場合も 1 になります: `--meta` を指定しない（開始ページがないので、J-STAGE のアップロード時チェックの EMSGM230E
で要対応になる）、画像を用意できなかった図がある（`--images` で入れると 0）、`--ai manual` で `--ai-response` を指定しない
（依頼文を作る最初の実行。AI の回答をまだ反映していない）、AI の回答が途中で切れていた（位置を決められない図表が残らなくても）、図の本体が見つからない図がある。手動モードの最初の実行の 1 は、回答を待っている
という知らせで、失敗ではありません（スクリプトから呼ぶときは、依頼文ができていれば次に進んでください。0.23.0 までは 0 でした）。
書誌情報の誤り（巻・号・ページの英数字以外の文字、読めない日付など）、AI による補完が必要な原稿を `--ai none` で変換したとき、
`--ai api` で API キー（環境変数）がないとき、指定したファイル・フォルダ（docx・`--meta`・`--pdf`・`--ai-response`・`--images`）が
ないとき（ファイルの代わりにフォルダを指定したときも）、`--images` の画像を読めないとき（画像は 1 枚も入れません）は 2 で止まります。

## 開発・引き継ぎ

- 利用者向けの説明: [docs/USAGE.md](docs/USAGE.md)、AI の API キーと手動モード: [docs/USAGE_AI.md](docs/USAGE_AI.md)
- 設計: [docs/DESIGN.md](docs/DESIGN.md)
- スタイルと JATS 要素の対応: [docs/STYLE_MAPPING.md](docs/STYLE_MAPPING.md)
- 新しく開発を引き継ぐ人へ（環境の作り方。Claude Code を使う前提）: [docs/HANDOFF.md](docs/HANDOFF.md)
- 開発者向け（テスト・コードの構成・引き継ぎ）: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)
- J-STAGE の仕様の要点と出典: [docs/JSTAGE_NOTES.md](docs/JSTAGE_NOTES.md)

引用文献の抽出規則は、先行ツール「文献チェック」（refcheck）で磨いたものを移植しています。
