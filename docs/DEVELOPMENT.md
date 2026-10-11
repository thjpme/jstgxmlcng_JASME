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
| `ai_assist.py` | AI 補完（依頼文の作成、API 呼び出し（Claude・ChatGPT・Gemini・Sakana AI）、回答の検証と適用） |
| `emit.py` / `builder.py` | XML の組み立て（文字は必ず `jx:span` の中に書く） |
| `tracking.py` | 変換途中の目印の定義 |
| `fidelity.py` | 文字の不変性チェック |
| `validate.py` | DTD 検証（`dtd/` に J-STAGE 指定 DTD を同梱） |
| `floats.py` | 浮動配置の図形（テキストボックス・グループ図形）の位置: 機械的に配置できるかの判定、AI に渡す位置の説明と行数の推定 |
| `jstage_rules.py` | J-STAGE のアップロード時チェック（記事アップロードメッセージ一覧）のうち XML だけで判定できるものの再現 |
| `images.py` / `package.py` / `report.py` | 画像の書き出し、ZIP、レポート |
| `pipeline.py` / `cli.py` | 全体の流れとコマンドライン |
| `colab.py` | Colab ノートブックの表示部品（手動モードの依頼文の枠など）と、続けて変換するときの入力の確認 |
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
- `tests/test_ai.py`: AI の回答の検証と適用（実際の API は呼ばない。`tests/data/ai_response_sample_full.json` が模擬回答。
  Claude・ChatGPT・Gemini・Sakana AI の呼び出しは、それぞれ偽のクライアントに置き換えて確かめる）。
- `tests/test_floats.py`: 浮動配置の図表（`tests/fixtures/sample_float.docx` と模擬回答 `tests/data/ai_response_sample_float.json`）。
  AI を使わない設定での中止、機械的な配置、`placements` の検証と適用。
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
- **モデルを変える**: ノートブックの `MODEL`（Claude）・`OTHER_MODEL`（Claude 以外）、コマンドラインの `--ai-model`。
- **API モードの AI を増やす**: OpenAI 互換の API なら `call_sakana()` と同じく `_openai_client()` に接続先を渡す。それ以外は `ai_assist.call_openai()` などと同じ形（依頼文と画像 → `AIOutcome.raw` に JSON の文字列）の関数を足し、
  `PROVIDERS`・`API_KEY_NAMES`・`call_provider()`、CLI の `--ai-provider`、ノートブックの手順 4 の選択肢に加える。テストは偽のクライアントで書く。

## Colab ノートブック

`notebooks/JASME_docx_to_JSTAGE_XML.ipynb` は `tools/make_notebook.py` で生成している。ノートブックを直すときはこのスクリプトを直して
`python tools/make_notebook.py` を実行する。ノートブックは実行のたびに GitHub の `main` ブランチ（手順 1 の `BRANCH`）からツールを入れる。

- 手順 1 はツール本体を毎回入れ直す（同じ版番号でもコードが新しくなるように）。同じランタイムで前の版を読み込んだ後だと
  入れ直しが反映されないため、その場合はセッションの再起動を求めて止まる。
- LibreOffice は手順 1 で裏でインストールし（`LO_PROC`）、手順 5 で終わるのを待つ。ツール本体の pip は確実さを優先して手順 1 の中で済ませる。
- 開発版は手順 1 の `USE_DEV_VERSION` にチェックを入れると `input()` でブランチ名を尋ねる（通常の利用者が誤って変えないように）。
- 手順 8 は、続けて他の論文を変換するための片付け（`DONE = {1}` に戻し、前の論文を `PREVIOUS` に記録する）。手順 3 は `PREVIOUS` と
  比べて書き換え忘れを知らせ（`colab.same_first_page()` / `carried_over()`）、手順 6 は前の論文の AI の回答が残っていれば止まる。
- 手動モードの依頼文の表示（コピーボタン付きの枠）とエラーの枠は `src/jasme_jats/colab.py`。
- Colab ではどのセルも押せてしまうため、各手順の最初で前の手順が済んでいるかを確かめる（変数 `DONE`）。
  ある手順をやり直すと、それより後の手順は未実行に戻る。

## バージョン

`src/jasme_jats/__init__.py` と `pyproject.toml` の version を上げ、`python tools/make_notebook.py` でノートブックを作り直す
（ノートブックの冒頭に版が表示される。作り直し忘れは `tests/test_notebook.py` で検出される）。
レポートにはバージョンとコミット ID が記録される（Colab では pip が記録したコミット ID）。

- 0.x: 試用版。出力の形が変わる修正は 0.x の 2 桁目、それ以外は 3 桁目を上げる。
- 1.0.0: 正式リリース。

## 開発を再開するとき

正本は GitHub の `main` ブランチ。Colab のノートブックも、実行のたびに `main` からツールを入れる。
これまでの開発に関わっていない人が引き継ぐときは、先に [HANDOFF.md](HANDOFF.md)（権限の引き継ぎ、所有者に連絡が取れなくなったときの手順、
Claude Code の環境の作り方）を読む。
リポジトリ直下の `CLAUDE.md` は Claude Code が自動で読む要点（原則・テスト・反映）なので、原則や手順を変えたらそちらも直す。

### Claude Code で再開する場合

1. Claude Code（claude.ai/code）で、このリポジトリ（`thjpme/jstgxmlcng_JASME`）を選んで新しいセッションを始める。
2. 最初に、例えば次のように頼む。

   > `docs/DEVELOPMENT.md` と `docs/DESIGN.md` を読んで、このツールの仕組みと守るべき原則（docx の本文は 1 文字も変えない）を
   > 把握してから、〇〇を直して。修正後はテストを通し、`main` に反映して。

3. 実際の論文で確かめる必要がある作業なら、その docx を渡す（下記）。

### 実際の論文（未公開原稿など）を使うとき

- 公開リポジトリには入れない。原本は手元か Google Drive の開発用資料フォルダに置き、作業のたびに渡す。
- 作業環境では `tests/private/`（`.gitignore` 済み）に置いて試す（上の「実際の論文でのテスト」）。

### 変更から反映までの流れ

1. コードを直す（「守るべき原則」を守る）。
2. `python -m pytest` がすべて通ることを確かめる（GitHub Actions でも Python 3.10 / 3.12 で実行される）。
3. ノートブックを直したら `python tools/make_notebook.py` で作り直す。
4. 版を上げる（「バージョン」）。
5. コミットして `main` に反映する。
6. Colab でノートブックを開き直し、「ランタイム」→「セッションを再起動」してから手順 1 を実行し、版の表示を確かめる。
   反映前の版を Colab で試したいときは、手順 1 の「開発版を使う（USE_DEV_VERSION）」にチェックを入れてブランチ名を入力する。

### J-STAGE の試験登載で分かったこと（2026-10）

詳細は `docs/JSTAGE_NOTES.md`。要点:

- 和文の論文の英文要旨は `<trans-abstract>` にする（`<abstract xml:lang="en">` だと EMSGM102E「タイトル(英)がない」）。
- アップロードの前に、編集登載システムで巻・号・セクションを作っておく（ないと EMSGM181E / EMSGM182E）。
- 注（`<fn>`）の `<label>` は表示されない。番号は `<p>` の先頭に書く。
- 引用文献の DOI を `<pub-id>` に書くと、プレビューではリンクにならなかった（設定 `ref_doi` で `<uri>` に切り替えられる）。
- アップロードする ZIP の名前は `jasme.zip` でなくてもよい（`jasme_巻_開始ページ.zip` で受け付けられた）。確かめられるのは中のフォルダ構成。

### 残っている課題

| 課題 | 状況 |
|---|---|
| ChatGPT・Gemini・Sakana AI の API モード | 0.12.0（ChatGPT・Gemini）・0.13.0（Sakana AI）で対応（推奨は Claude）。偽のクライアントでのテストのみで、実際の API ではまだ試していない（Sakana Fugu のチャットでは、手動モードの依頼文に正しい JSON が返ることを利用者が確認）。試験運用で一度ずつ確かめる |
| 注の番号から本文へ戻るリンク | J-STAGE の仕様上できない（`<xref>` に付けられるのは ref-type と rid だけで、戻り先の目印を付けられない。注の中は `<p>` だけ）。ブラウザの「戻る」で戻れる |
| 引用文献の DOI のリンク | 今は J-STAGE に DOI として登録する `<pub-id>`。公開後に J-STAGE の引用文献リンクが付くかを確認し、画面上のリンクを優先するなら `ref_doi = "uri"` にする |
| テキストボックス・グループ図形の中の図 | 位置を機械的に決められない図表は AI に位置と組み合わせを指定させる（`docs/DESIGN.md` の 6.1。0.14.0）。`placements` は模擬回答でのみ確かめていて、実際の AI（どの会社のものも）ではまだ試していない。表で組んだ図（`fig` の中の `table-wrap`）が J-STAGE の画面でどう表示されるかも、試験登載で確認が必要 |
| 正式リリース | 試験運用で問題がなければ、版を 1.0.0 にする |
