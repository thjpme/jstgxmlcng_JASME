# CLAUDE.md

論文の docx を J-STAGE 全文 XML（JATS 1.1）に変換するツール（『全国数学教育学会誌 数学教育学研究』用）。
作業の前に `docs/DEVELOPMENT.md`（コードの構成・守るべき原則・反映の流れ）と `docs/DESIGN.md`（設計）を読むこと。
新しく引き継いだ人向けの環境の作り方は `docs/HANDOFF.md`。

## 最優先の原則

- **docx の本文の文字を 1 文字も変えない**（誤字脱字も直さない）。文字列を書き換えるコードを書かない。
  構造はアトムに `LinkSpec` を付けるか段落の役割を変えることで表し、XML の段落の文字は必ず `Emitter.span()` を通して書く。
- 出力しない段落は理由付きで記録し（`plan.exclude()` / `BuildInfo.exclusions`。空白だけの段落は `plan.exclude_blank()`）、
  落とせるのは空白だけ（`Emitter.drop()`）。出力した段落を除外にも記録すると、不変性チェックは不合格になる。
- 不変性チェックは文字しか見ない。XML に入らなかった画像は `pipeline.lost_images()` が検出し、要対応として知らせる。
- 作り方は 2 通り（`Options.route`。最初に利用者が選ぶ。Colab の初期値とコマンドラインの `--pdf` があるときの既定はルート2）。
  どちらも docx → XML の処理は同じで、上の原則はそのまま守る。
  - ルート1「docx から作る」: docx の文字のまま XML にする。記事の PDF があれば照合して、違いをレポートに載せるだけ（`pdfmatch.py`）。
  - ルート2「出版版 PDF に合わせてから作る」: 先に、docx の文字を PDF に合わせて直した docx（Word の変更履歴つき）を作り（`pdfdocx.py`）、
    それをルート1 と同じ処理で変換する。docx を直すのは `pdfdocx.py` だけで、XML は直した docx と 1 文字も違わない。
    Word が付ける番号（自動番号・脚注番号）は docx の文字ではないので、変換のときに全角・半角を PDF に合わせる。
    PDF のページ番号・誌名の行・柱・投稿受付日など（組版で入る文字）と、docx にない図・表の中の文字は docx に足さない（`pdfmatch.pdf_stream`。足さなかった文字はレポートの 13 章）。
    足すか・消すかを PDF から決められない違いは直さず、理由（`TextDiff.why`）を付けて 13 章に出す。
- 詳しくは `docs/DEVELOPMENT.md` の「守るべき原則」。

## 環境とテスト

```bash
pip install -e ".[dev]"     # セッションの最初に 1 回
python -m pytest -q         # 変更のたびに。すべて通ってから反映する
```

- ノートブック（`notebooks/*.ipynb`）は `tools/make_notebook.py` で生成する。ipynb を直接編集せず、スクリプトを直して
  `python tools/make_notebook.py` を実行する。
- テスト用の docx は `tests/make_fixtures.py` で生成する（内容は架空）。

## 反映

- 正本は `main`。利用者の Colab ノートブックは実行のたびに `main` からツールを入れるので、`main` への反映はすぐ利用者に届く。
- 反映の前に版を上げる（`src/jasme_jats/__init__.py` と `pyproject.toml`。出力の形が変わる修正は 0.x の 2 桁目、それ以外は 3 桁目）
  → ノートブックを作り直す → テストを通す。
- 実際の論文（未公開原稿）は `tests/private/`（`.gitignore` 済み）にだけ置き、コミットしない。新しい docx をリポジトリに加えるときは
  `tools/sanitize_docx.py` を通す。
- 文書・コメント・コミットメッセージは日本語で、既存の書き方に合わせる。
