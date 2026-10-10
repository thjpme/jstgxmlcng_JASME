# 開発者向け（引き継ぎ用）

## 環境

```bash
git clone https://github.com/thjpme/jstgxmlcng_JASME.git
cd jstgxmlcng_JASME
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m pytest
```

EMF/WMF 画像の変換を試すには LibreOffice（`soffice`）が必要（なければ該当テストは「変換失敗」を期待して通る）。

## コードの構成（`src/jasme_jats/`）

| ファイル | 役割 |
|---|---|
| `ooxml.py` | docx の低水準処理。**文字ポリシー**（何を docx の文字とみなすか）と、検証用の独立した文字列取り出し `canonical_text()` |
| `docx_reader.py` | docx → 中間表現（`model.py` の `Document` / `Para` / `Atom`） |
| `numbering.py` | Word の自動段落番号を表示どおりの文字列にする |
| `omml.py` | Word の数式（OMML）→ MathML 2.0 |
| `structure.py` | 段落の役割の決定と論文の構造（`ArticlePlan`）の組み立て |
| `linker.py` | 図・表・数式・注・URL・DOI の機械的リンク、アトムにリンクを付ける共通関数 `apply_span()` |
| `refparse.py` | 引用文献の解析と著者・年方式の引用の抽出・照合（先行ツール「文献チェック」refcheck.py から移植） |
| `ai_assist.py` | AI 補完（依頼文の作成、API 呼び出し、回答の検証と適用） |
| `emit.py` / `builder.py` | XML の組み立て（文字は必ず `jx:span` の中に書く） |
| `tracking.py` | 変換途中の目印の定義 |
| `fidelity.py` | 文字の不変性チェック |
| `validate.py` | DTD 検証（`dtd/` に J-STAGE 指定 DTD を同梱） |
| `jstage_rules.py` | J-STAGE のアップロード時チェック（記事アップロードメッセージ一覧）のうち XML だけで判定できるものの再現 |
| `images.py` / `package.py` / `report.py` | 画像の書き出し、ZIP、レポート |
| `pipeline.py` / `cli.py` | 全体の流れとコマンドライン |
| `data/jasme.toml` | 本誌の設定（誌名・ISSN・DOI 形式・スタイル名の対応表など） |

## 守るべき原則

1. **文字列を書き換えるコードを書かない。** 構造はアトムに `LinkSpec` を付けるか、段落の役割を変えることで表す。
2. XML に段落の文字を書くときは必ず `Emitter.span()` を通す（`jx:span` で囲まれない文字は不変性チェックで「追加」とみなされる）。
3. 出力しない段落は `plan.exclude()` か `BuildInfo.exclusions` に理由付きで記録する（記録しないと「出力漏れ」になる）。
4. 構造の区切りとして空白を落とす場合は `Emitter.drop()` を使う（空白以外は落とせない）。
5. 新しい種類の docx の要素に対応するときは、`ooxml.canonical_text()`（検証側）と `docx_reader.py`（変換側）の両方を同じ文字ポリシーで直し、
   その要素を含む docx を `tests/make_fixtures.py` に加えてテストする。

## テスト

- `tests/make_fixtures.py` がテスト用の docx（`tests/fixtures/sample_full.docx`, `sample_edge.docx`）を生成する。内容は架空。
  変更したら `python tests/make_fixtures.py` で作り直してコミットする。
- `tests/test_fidelity.py`: 不変性チェックがわざと壊した XML を確実に検出することのテスト。チェックの処理を変えたら必ず通すこと。
- `tests/test_ai.py`: AI の回答の検証と適用（実際の API は呼ばない。`tests/data/ai_response_sample_full.json` が模擬回答）。
- GitHub Actions（`.github/workflows/test.yml`）で push のたびに実行される。

`tests/fixtures/JASME_template_20261009.docx` は学会のテンプレートから、`tools/sanitize_docx.py` でコメントと作成者情報を
取り除いたもの（本文の文字は同一）。新しい docx をリポジトリに加えるときも、このツールを通すこと。

### 実際の論文でのテスト

実際の論文（未公開原稿や著作権のあるもの）は **公開リポジトリに入れない**。`tests/private/`（`.gitignore` 済み）に置いて手元で試す:

```bash
python -m jasme_jats tests/private/論文.docx --meta examples/meta_example.toml --out output
```

## よくある拡張

- **別の雑誌に使う**: `src/jasme_jats/data/jasme.toml` を複製して書き換え、`--config` で指定する（Colab では `JournalConfig.load(パス)`）。
- **スタイル名の追加**（著者が独自のスタイル名を使った等）: 設定ファイルの `[styles]` に「スタイル名 = 役割」を足す。
- **AI の依頼内容を変える**: `ai_assist.py` の `SYSTEM_PROMPT`。操作の種類を増やすときは `OP_SCHEMA` と `apply_ops()` に検証を加える。
- **モデルを変える**: ノートブックの `MODEL`、コマンドラインの `--ai-model`。

## Colab ノートブック

`notebooks/JASME_docx_to_JSTAGE_XML.ipynb` は `tools/make_notebook.py` で生成している。ノートブックを直すときはこのスクリプトを直して
`python tools/make_notebook.py` を実行する。ノートブックは実行のたびに GitHub の `main` ブランチ（手順 1 の `BRANCH`）からツールを入れる。

- 手順 1 はツール本体を毎回入れ直す（同じ版番号でもコードが新しくなるように）。同じランタイムで前の版を読み込んだ後だと
  入れ直しが反映されないため、その場合はセッションの再起動を求めて止まる。
- Colab ではどのセルも押せてしまうため、各手順の最初で前の手順が済んでいるかを確かめる（変数 `DONE`）。
  ある手順をやり直すと、それより後の手順は未実行に戻る。

## バージョン

`src/jasme_jats/__init__.py` と `pyproject.toml` の version を上げ、`python tools/make_notebook.py` でノートブックを作り直す
（ノートブックの冒頭に版が表示される。作り直し忘れは `tests/test_notebook.py` で検出される）。
レポートにはバージョンとコミット ID が記録される（Colab では pip が記録したコミット ID）。

- 0.x: 試用版。出力の形が変わる修正は 0.x の 2 桁目、それ以外は 3 桁目を上げる。
- 1.0.0: 正式リリース。
