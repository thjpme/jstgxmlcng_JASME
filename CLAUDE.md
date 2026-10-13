# CLAUDE.md

論文の docx を J-STAGE 全文 XML（JATS 1.1）に変換するツール（『全国数学教育学会誌 数学教育学研究』用）。
作業の前に `docs/DEVELOPMENT.md`（コードの構成・守るべき原則・反映の流れ）と `docs/DESIGN.md`（設計）を読むこと。
新しく引き継いだ人向けの環境の作り方は `docs/HANDOFF.md`。

## 最優先の原則

- **docx の本文の文字を 1 文字も変えない**（誤字脱字も直さない）。文字列を書き換えるコードを書かない。
  構造はアトムに `LinkSpec` を付けるか段落の役割を変えることで表し、XML の段落の文字は必ず `Emitter.span()` を通して書く。
- 出力しない段落は理由付きで記録し（`plan.exclude()` / `BuildInfo.exclusions`）、落とせるのは空白だけ（`Emitter.drop()`）。
- 唯一の例外: 記事の PDF（出版版）があるとき、英数字・記号の全角・半角だけの違いを PDF に合わせ、その前後の PDF にない空白を落とす
  （`pdfmatch.py`。利用者の判断で既定はオン、設定で切れる）。変えた文字は `jx:w`・`jx:d` に元の文字を残し、不変性チェックで
  全角・半角の違いと空白だけであることを確かめる。かな・漢字や、文字そのものが違う箇所は変えずにレポートに載せる。
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
