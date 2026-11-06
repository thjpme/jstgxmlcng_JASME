# 単位 u2-app（0.30.0）: 1 画面版で入力を変えた後の結果の混ざり（と従来のノートブックの手順の印）

## 要点

- 目的: 1 画面版（`app.AppState`）で変換した後に入力（docx・PDF・ページ・日付・作り方など）を変えて「反映」「画像を入れる」「結果をダウンロード」を押すと、前回の変換の meta・回答・画像と今の docx・設定が 1 回の変換に混ざる。別の論文の段落が AI の除外として XML から消えても、不変性チェック・DTD は合格し、知らせも出ない。REVIEW の O3（変換の後に AI の方法のラジオを変えると画面が矛盾する）も同じ根で、あわせて直す。従来のノートブックで、途中で止まった手順の後も後ろの手順の「済み」（`DONE`）が残る穴も直す。
- 直し方: 変換したときの入力の写し `RunInputs`（ファイルは中身の sha256 で比べる）を `AppState.run` に持ち、`_run`・`apply_answer`・`add_images`・`download` はこの写しだけを使う。入力が写しと違えば、結果を残したまま理由の文で断る（「このままダウンロード」でも断る）。手動かどうかは写しで決める（O3）。`convert()` は確かめが済むまで前の結果を変えない。別の論文に変えて変換したら回答の欄を空にし、前に別の依頼文へ反映したのと同じ文字の回答は断る（依頼文の digest で結び付ける）。ノートブックは各手順の先頭で自分より後ろの `DONE` を消す（`unmark`）。
- 出力の形は変わらない（XML・レポート・ZIP の中身は同じ）。`report.actions()` に Action は足さない（画面の状態の表示）。
- 実際の原稿での影響: テストデータ1 → テストデータ2 の切り替えでは、本文の段落 ID が 135 件中 132 件重なり、前の論文用の set_role exclude 3 件がすべて採用されてテストデータ2 の段落が 3 つ消えた（fpage も前の値のまま）。テストデータ2 → テストデータ1 では 3 件とも不採用。どちらも混ざったことの知らせはなかった。修正後は、どちらの経路も「入力が前回の変換から変わっています」で断る。
- 担当: 作るのは Sonnet（エフォート medium）、点検は Opus（エフォート medium）。Opus が自分で書く部分はない。点検では `convert()` の手順の順、`on_convert` の 3 つの経路の戻り、crash の後の `view()` が例外を出さないこと、`CRASH_ADVICE` の各案内が新しい状態と合うことを見る。
- 触るファイル: `src/jasme_jats/app.py`、`tools/make_notebook.py`、`tests/test_app.py`、`tests/test_notebook.py`。文書（USAGE・ARCHITECTURE・DEVELOPMENT・REVIEW・GUI_PLAN）は版の最後にまとめて直す。

## 再現（確かめたこと）

再現のスクリプトは `docs/fix_plan_2026-11/protos/u2-app/`（`repro_mix.py`・`repro_more.py`・`repro_answer_kept.py`・`repro_notebook.py`・`real_check.py`）と、点検の試作 `docs/fix_plan_2026-11/protos/review-u2-app/proto.py` にある。どれも作業用フォルダ（scratchpad）のパスを前提に書いてあり、出力のフォルダ・生成した docx は残っていない。手本として読むもので、そのまま実行するものではない。`real_check.py` は tests/private の原稿を読むので、リポジトリのテストにはしない。

| # | 操作 | 0.29.0 で起きたこと | スクリプト |
|---|---|---|---|
| 1 | 手動モードで論文A を変換し、docx を論文B、最初のページを 77 にして「反映」 | 出力は `31_1.xml`。fpage・lpage・DOI は論文A の meta、article-title は論文B。論文A 用の回答（set_role exclude、段落 ID d13）が論文B の d13 に当たって採用され、論文B の段落が消えた。不変性チェック・DTD は合格、要対応 0 件 | `repro_mix.py` |
| 2 | 実際の原稿で同じ操作（route=docx、手動、本文の段落 ID 3 つに set_role exclude） | テストデータ1 → 2: ID は 135 件中 132 件が重なり、3 件とも採用。fpage は 77 と入れたのに 1。テストデータ2 → 1: 重なりは 327 件中 135 件で、3 件とも不採用。どちらも混ざったことの知らせはない | `real_check.py` |
| 3 | テンプレートを変換して画像を 1 枚入れ、docx を別のファイルに変えて「反映」 | `_run` の `add_images(skip_unneeded=True)` が前の画像を新しい結果に入れ、足りない画像が 0 件になる。work/input に 2 つの docx が残る | `repro_more.py`（== 1） |
| 4 | O3: 手動で変換した後に「AI による補完の方法」を api・none に変える | `waiting_for_answer`・`answer_box_open` が False になり手動の欄が隠れる側に判定される。`result_html` に「AI の回答をまだ反映していません」の枠と（none では）「使わない」の注意の枠が出る。`apply_answer` は「手動モードで変換してから」で断る。逆に「使わない」で変換してから手動に変えると、依頼文のない結果に回答を反映する | `repro_more.py`（== 2・2b） |
| 5 | 変換の後に docx の欄を空にして「反映」 | `_run` の `Path(None)` で TypeError。「想定外のエラーで止まりました」（不具合の案内）が出る | `repro_more.py`（== 3） |
| 6 | API キーなしで「変換する」が InputError で止まった後に「反映」 | `convert()` が API キーを確かめる前に `self._meta`・`self._journal` を新しい入力で上書きし、`self.res` は前の結果のまま。手動に戻して「反映」すると、前の依頼文への回答が `31_77.xml` として出る | `repro_more.py`（== 4） |
| 7 | split_labels・route を変えて「反映」 | `_run` が今の入力の split_labels・route を読む。fixture `sample_full` の fig・table-wrap の label は、変換時（False）の 0 から 4 に変わる | `repro_more.py`（== 5）・`repro_answer_kept.py` |
| 8 | 「変換する」で論文B に切り替えた後、欄に残った論文A の回答で「反映」 | `on_convert` の出力に回答の欄（`answer`）がないので、論文A の回答が欄に残る。それで「反映」すると論文A の set_role（d13）が採用され、論文B の段落が消える。入力の写しを持つだけではこの経路は防げない | `repro_answer_kept.py` |
| 9 | 従来のノートブック: 手順 5 まで済ませた後に手順 2・3 をやり直し、途中の SystemExit で止まる | 手順 2（PDF で補う。docx B を選び PDF を選ばなかった）: `docx_path`=B・`pdf_path`=None なのに `DONE` は {1,2,3,4,5} のまま。手順 6 の guard を通り、convert(B, 論文A の meta, route=pdf, pdf=None) が素のトレースバックで止まる。手順 8 は論文A の ZIP を「（B.docx）」と表示し、`CONVERTED`・`PREVIOUS` にも B と記録する。手順 3（受付日が誤り）: `DONE` が戻らず、手順 5 で `ArticleMeta.from_dict` の ValueError が素で出る | `repro_notebook.py` |
| 10 | コマンドライン | 混ざる経路はない（cli.py は 1 回の実行で入力をすべて受けて convert を 1 回呼ぶ）。ただし `--ai-response` に別の論文の回答を渡しても検出しない。この単位では直さない（REVIEW に記録） | コードを読んで確かめた |

点検の試作（`proto.py`）で、さらに次を確かめた。

- (a) 設計の初めの形では `paper_changed` を `convert()` の途中でしか書き換えないので、論文A → 論文B を変換した後に受付日を誤って「変換する」を押すと、入力の誤りで止まったのに回答の欄が空になる（B 用に貼った回答が消える）。
- (b) `file_digest` の OSError を外に出す形では、`on_apply` の crash の後の `view()` → `result_html()` → `changed_inputs()` からも同じ OSError が出て、Gradio の外枠（「Error」だけ）に抜ける。

根: `AppState` に「変換したときの入力」が残っていない。残るのは結果（`self.res`）と変換に使った値の一部（`self._meta`・`self._journal`・`self._api_key`・`self.user_images`）だけで、`_run` は docx・pdf・route・split_labels・model を毎回今の画面の入力（`self.inputs`）から読む。`waiting_for_answer`・`answer_box_open`・`result_html`（`no_ai_box`）・`apply_answer` の「手動か」も入力（`self.inputs["ai_mode"]`）を見る（O3）。AI の回答は段落 ID で指すので、同じテンプレートで書いた論文どうしでは ID がほぼ重なり、別の論文の段落に当たっても検証を通る。ノートブックでは `DONE` を各手順の最後（`mark`）でしか書き換えない。

## 直し方

行番号は 0.29.0 の `src/jasme_jats/app.py`（641 行）と `tools/make_notebook.py` のもの。

### 1. 新しい定数・関数（app.py のモジュールの最上位。`InputError` の後）

- `import hashlib`・`import unicodedata` を足し、`from dataclasses import dataclass, field`・`from typing import Optional` を足す。
- `COMPARED_INPUTS = tuple(n for n in INPUT_NAMES if n not in ("ai_mode", "model"))`
  - コメント: 「変換の結果を左右する入力（前回の変換と比べる）。AI の方法・モデルは次に変換するときに使う設定なので比べない（O3）」。
- `LABELS`（49〜53 行目）に `"route": "作り方"` と `"split_labels": "SPLIT_LABELS"` を足す。LABELS は `ready`（gr.Markdown）に出るので、`<label>` のような生のタグは書かない。
- `DOCXISH = (LABELS["docx"], LABELS["pdf"], LABELS["route"], LABELS["split_labels"])`: 変わると依頼文も変わり得る入力の名前（`stale_text` の文の分岐に使う）。
- `_DIGESTS: dict = {}` と `file_digest(path) -> str`:
  - ファイルの中身の sha256（16 進）を返す。`(str(path), st.st_size, st.st_mtime_ns)` をキーにして `_DIGESTS` に覚える（`on_change` はキーを押すたびに呼ばれるため。覚えは関数の中に置き、AppState の側に置かない。テストはこの関数を monkeypatch する）。
  - 例外はここでは捕まえない（捕まえるのは `fingerprint()`）。
- `_model_value(v) -> str`: 今の `_run`（191 行目）の `"auto" if str(v).startswith("自動") else str(v).strip()` を切り出したもの。`convert()` と `settings_note()` が使う。
- `@dataclass(frozen=True) class RunInputs`: docstring「変換したときの入力の写し。AppState.convert が作り、_run・apply_answer・add_images・download が使う。」
  - `compared: dict`（`fingerprint()` の戻り値）
  - `docx: Path`（work/input の写し）、`pdf: Optional[Path]`（同じく写し。なければ None）
  - `route: str`、`split_labels: bool`、`ai_mode: str`
  - `model: str`（`Options.ai_model` に渡す値。`_model_value` の結果）
  - `meta: ArticleMeta`、`journal: JournalConfig`
  - `docx_name: str`（元のファイル名。前の回答を断る文に使う）
  - `api_key: Optional[str] = field(default=None, repr=False)`（repr に出さない。既定値つきなので最後に置く）

### 2. AppState の状態（`__init__`・114〜123 行目）

- `self._meta`・`self._journal`・`self._api_key` を消し、`self.run: Optional[RunInputs] = None` に置き換える。
- `self.paper_changed = False`: 直前の `convert()` で docx の中身が前回と違った。`on_convert` が回答の欄を空にするかを決める。
- `self._last_docx = None`: 最後に `convert()` が手順 3 まで進んだときの docx の digest。変換が後で失敗しても残す。
- `self._last_answer = None`: `(依頼文の sha256, docx_name, 回答を strip した文字)`。最後に反映に成功した回答。`reset()` では消さない（ノートブックの `PREVIOUS["ai_response"]` に当たる役。ただし鍵は依頼文）。

### 3. 比べる関数（AppState のメソッド）

- `fingerprint(self) -> dict`: `COMPARED_INPUTS` の名前ごとに比べる値を返す。
  - docx・pdf: 値が空なら None。空でなければ `file_digest(Path(v))`。**OSError（FileNotFoundError を含む）はすべて捕まえて** `("読めない", str(v))` を返す（前回の値と一致しないので「変わった」扱いになる）。画面の判定（`view`・`ready_text`）から例外が出ない形にする。
  - split_labels: `bool(v)`。route: `str(v)`。
  - subject_other・subject_other_en: `manuscript_type` が `OTHER_TYPE` でないときは `""`（出力に使わないので比べない）。
  - そのほか: `unicodedata.normalize("NFKC", str(v or "")).strip()`。ArticleMeta・`colab.same_first_page` と同じく、「１」と「1」、前後の空白は同じとみなす。日付の書き方の違い（2026/3/31 と 2026-03-31）は同じとみなさない（断る側に倒れるだけ。直さない）。
  - 同じファイルを選び直しただけなら（パスが違っても中身が同じなら）変わっていない扱いになる。
- `changed_inputs(self) -> list`: `self.res is None` か `self.run is None` なら `[]`。そうでなければ、今の `fingerprint()` と `self.run.compared` で値の違う名前の `LABELS` を、`COMPARED_INPUTS` の順に返す（例: `["docx", "最初のページ"]`）。結果がないとき（変換が途中で止まった後）に「今の結果は…」の文を出さないため。
- `stale_text(self, changed) -> str`: 次の文を組み立てて `_app_text()` に通す（`changed` は LABELS の名前のリスト）。f 文字列の式の中で `"、".join` を書かず、先に変数にする（Python 3.10）。

  ```python
  names = "、".join(changed)
  if any(n in DOCXISH for n in changed):
      inner = ("入れた画像は消えるので、変換の後にもう一度入れてください。手動モードでは新しい依頼文が出るので、"
               "AI に渡して回答を貼り替えます")
  else:
      inner = ("入れた画像は消えるので、変換の後にもう一度入れてください。貼り付けた回答は欄に残るので、変換の後にもう一度"
               + rp.step("apply_button") + "を押します")
  text = ("入力が前回の変換から変わっています（変わった項目: " + names + "）。今の結果は、変える前の入力で作ったものです。"
          "変えた入力で作るには、" + rp.step("convert_again") + "してください（" + inner + "）。"
          "今の結果のまま続けるときは、入力を前回の変換のときの値に戻してください（同じファイルを選び直せば、変わっていない扱いになります）。")
  return _app_text(text)
  ```

  1 画面版では「「変換する」をもう一度押してください（…もう一度「反映」を押します）」になる。分岐の条件を docx だけでなく PDF・作り方・SPLIT_LABELS にも広げるのは、これらでも依頼文が変わり得て、変わると 6 節の確かめで同じ回答が断られるため（「欄に残る回答でもう一度反映」と案内して断る食い違いを避ける）。

- `settings_note(self) -> str`: `self.res is None` か `self.run is None` なら `""`。今の `self.inputs["ai_mode"]` が `run.ai_mode` と違うか、`_model_value(self.inputs["model"])` が `run.model` と違うとき、次の文を `_app_text` に通して返す。それ以外は `""`。
  - 「「AI による補完の方法」の欄・MODEL の変更は、次に変換するときに使われます（今の結果は前の設定のままです。変えた設定で作るには、" + rp.step("convert_again") + "してください）。」
  - 「AI による補完の方法」は画面の実際のラベル（`test_app_words_match_the_real_labels` が確かめるラベルの集合にある）。
- `ready_text(self) -> str`: `on_change` の `ready` の文を AppState に移す。次を空でないものだけ `"\n\n"` で続ける。
  1. `missing()` があれば「足りない項目: " + "、".join(miss)」（今の 534 行目と同じ文）。
  2. `changed_inputs()` があれば `stale_text(changed)`、なければ `settings_note()`。
  - どれもなければ `""`。

### 4. `convert()`（211〜231 行目を書き直す。順番が大事）

1. 最初の行で `self.paper_changed = False`（入力の誤りで止まったときに前回の値で回答の欄を消さないため）。
2. ローカル変数で確かめる: `meta = self._article_meta()`、`journal = JournalConfig.load()`、`api_key = None`。`ai_mode == "api"` なら `io.read_secret(API_KEY_NAMES["claude"])`、読めなければ今と同じ InputError。**ここまでは `self.res`・`self.run`・`self.user_images` を変えない**（再現 6 の修正）。
3. `compared = self.fingerprint()`。
4. `compared["docx"]` か `compared["pdf"]` が「読めない」の印（タプルで先頭が "読めない"）なら InputError: `_app_text(rp.step(該当の "docx" か "pdf") + "のファイルを読めませんでした。選び直してから、" + rp.step("convert_again") + "してください。")`。1 画面版では「「docx（論文の Word ファイル）」の欄のファイルを読めませんでした。選び直してから、「変換する」をもう一度押してください。」。ここまでは `self.res`・`self.run`・`self._last_docx` を変えない（前の結果は残る）。
5. `self.paper_changed = self._last_docx is not None and compared["docx"] != self._last_docx`。続けて `self._last_docx = compared["docx"]`。
6. 前の結果と画像と写しを捨てる: `self.res = None; self.user_images = {}; self.run = None`。224 行目のコメント「同じ論文のやり直しは apply_answer」は「前の変換で受け取った画像は持ち越さない（入力を変えずに回答を反映し直すときは apply_answer が入れ直す）」に直す。
7. ファイルを写す: 今の `_run` の 184〜194 行目を `_copy_inputs(self) -> tuple`（戻り値 `(local_docx, local_pdf)`）として切り出して呼ぶ。work/input に元の名前で写し、写し先と同じパスなら写さない（今と同じ）。work/input の前の論文の写しは消さない（入力が work/input の中を指すとき、元のファイルまで消すため。今と同じ）。
8. `self.run = RunInputs(compared=compared, docx=local_docx, pdf=local_pdf, route=str(f["route"]), split_labels=bool(f["split_labels"]), ai_mode=f["ai_mode"], model=_model_value(f["model"]), meta=meta, journal=journal, docx_name=Path(f["docx"]).name, api_key=api_key)`。
9. 今と同じく `step(0.05, …)`・`io.libreoffice_ready()`・`step(0.2, …)` の後、`res = self._run(self.run.ai_mode, None, progress)`、`step(1.0, "完了")`。
- docstring に「確かめ（足りない項目・入力の誤り・API キー・ファイルを読めない）で止まったときは、前の結果と入力の写しをそのまま残す」を足す。

### 5. `_run(ai_mode, ai_response, progress)`（181〜209 行目）

- `self.inputs` を読まない。`run = self.run` から作る。
- 順番: `run` を読む → `opts = Options(out_dir=self.out_dir, ai_mode=ai_mode, ai_provider="claude", ai_model=run.model, ai_api_key=run.api_key, ai_response=ai_response, pdf_path=run.pdf, route=run.route, split_labels=run.split_labels)` を作る → `self.res = None` → `shutil.rmtree(self.out_dir, ignore_errors=True)` → `convert(run.docx, run.meta, run.journal, opts)`。失敗し得る準備（Options）を、前の結果を捨てる前に済ませる。
- ファイルの写しは呼ばない（`convert()` へ移した）。
- `except AIRequiredError` → InputError（`ai_required_box`）、`step(0.9, …)`、`user_images` の入れ直し、`self.res = res` は今のまま。
- 0.31.0 の u6 が `except StructureConflictError` をこの except の隣に足す（`raise InputError(step_text(str(e), "app"), structure_conflict_box(str(e), "app"))`）。この単位では足さない。

### 6. `apply_answer(text, io, progress)`（269〜276 行目）

1. `self.res is None or self.run is None or self.run.ai_mode != "manual"` なら今と同じ「手動モードで変換してから、回答を貼り付けてください。」。入力のラジオではなく写しで決める（O3）。
2. `changed = self.changed_inputs()` が空でなければ `raise InputError(self.stale_text(changed))`。結果・欄は残す。
3. 回答が空なら今の「AI の回答が貼り付けられていません。」。
4. `prompt_digest = hashlib.sha256(self.prompt_text().encode("utf-8")).hexdigest()`（`_run` の前に取る。`_run` は出力フォルダを消すため）。
5. `self._last_answer` があり、`self._last_answer[2] == text.strip()` で、`self._last_answer[0] != prompt_digest` なら InputError。文（`_app_text` を通す）:
   - 「貼り付けられているのは、前に別の依頼文（" + 名前 + " のとき）に対して反映した AI の回答です。今の" + rp.step("prompt") + "を AI に渡し、返ってきた回答に貼り替えてから" + rp.step("apply_button") + "を押してください。」
   - 名前は `self._last_answer[1]`。依頼文が同じなら（同じ docx の変換し直し、ページだけ直した、同名で直した版でも依頼文が同じ）通す。依頼文が違うときだけ断る。
6. 進みの表示（今の 275 行目）→ `res = self._run("manual", text)`。成功したら `self._last_answer = (prompt_digest, self.run.docx_name, text.strip())`。`res` を返す。

### 7. `add_images`・`download`

- `add_images(mapping)`（303 行目）: `self.res is None` の確かめの直後に、`changed = self.changed_inputs()` があれば `raise InputError(self.stale_text(changed))`。
- `download(accept_todo)`（395 行目）: `self.res is None` の確かめの直後に、`changed` があれば `return None, self.stale_text(changed)`。`accept_todo` でも断る（計画者の決定）。`on_download` の「ダウンロードの前に」の赤い枠に出る。

### 8. 画面の判定（O3）

- `waiting_for_answer`（234 行目）: `self.res is not None and self.run is not None and self.run.ai_mode == "manual" and ai_pending(self.res)`。
- `answer_box_open`（245 行目）: 最初の条件を `self.res is None or self.run is None or self.run.ai_mode != "manual" or self.res.ai.mode != "manual" or not self.res.prompt_path` にする。`run.ai_mode` を `res.ai.mode` より先に見る（`test_image_slots_in_view` の模擬の res には `ai` がないため。`self.run is None` で先に False になる）。
  - docstring の「（waiting_for_answer と同じく、「AI による補完の方法」の欄が手動のとき）」と、続く「さらに…欄だけを手動に切り替えても…」の 2 文を、「手動モードで変換した結果のときだけ見せる（変換したときの入力の写し `run.ai_mode` で決める。変換の後に「AI による補完の方法」の欄を変えても変わらない。O3）。」に直す。
- `result_html`（384 行目）: `no_ai_box` を出す条件を `self.run is not None and self.run.ai_mode == "none"` にする。**「入力が前回の変換から変わっています」の枠は足さない**（`ready` と、断ったときの赤い枠で知らせる。黄色い枠は要確認の色で、原則 8 の例外を広げるため）。`check_box` の import も足さない。
- `reset()`（406 行目）: `self._meta = self._journal = self._api_key = None` の行を `self.run = None; self.paper_changed = False; self._last_docx = None` に替える。`_last_answer` は残す。

### 9. `build_app`

- `on_change`（531〜534 行目）: `sync(values)` の後、`return gr.update(interactive=not state.missing()), state.ready_text()`。
- `on_convert`（536〜544 行目）: 出力を `views + [answer, ready]` にする（`go.click(on_convert, inputs, views + [answer, ready])`。`answer` の部品は on_convert より前に作られている）。戻りは、どの経路（成功・InputError・想定外の例外）でも `view(...) + [gr.update(value="") if state.paper_changed else gr.update(), state.ready_text()]`。共通の小さな関数 `tail()` にして 3 か所で使う。
  - 同じ docx の変換し直しでは回答の欄を残す。`CRASH_ADVICE["apply"]` の「「変換する」をもう一度押すと…貼り付けた回答も…欄に残っています」はこれで成り立つ。
  - 入力を変えて `ready` に文が出た後、変換に成功すると `ready` は空になる（変換し直した後も古い文が残る問題を防ぐ）。
- `on_apply`・`on_images`・`on_download`・`on_next` の出力は変えない（入力を変えないため）。`on_next` は今のまま回答の欄を空にし、入力の値の変化で `on_change` が `ready` を作り直す。
- 手動の欄・画像の欄は、入力が変わっても隠さない。押せば理由の赤い枠が出て、入力を戻せば続けられる。

### 10. 前の結果を捨てず、残して断る理由（設計の決定。コードのコメントに要約を書く）

- `on_change` はキーを押すたびと「次の論文」で呼ばれる。触っただけで結果・貼り付けた回答・入れた画像を消すと取り返せない。
- 断る文で、変わった項目と、戻す・変換し直すの 2 つの道を示せる。
- 比べるのはファイルの中身（sha256）。Gradio 6.31.0 は中身の sha256（seed つき）でアップロード先を決めるので、同じファイルの選び直しはパスも同じになることが多いが、Gradio の内部には頼らない。既にある写しを再び渡すときに Gradio が mtime を変えるので、`_DIGESTS` の覚えが外れて計算し直すことがある（正しさには影響しない）。

### 11. 従来のノートブック（tools/make_notebook.py）

- `mark`（84 行目）の後に `unmark(step)` を足す:

  ```python
  def unmark(step):
      return f'DONE = {{n for n in globals().get("DONE", set()) if n < {step}}}\n'
  ```

- 手順 2・3・4・5・7・8 のセルで、`guard(...)` の直後に `unmark(N)` を入れる（2: 178 行目の後、3: 252 行目の後、4: 303 行目の後、5: 329 行目の後、7: 419 行目の後、8: 457 行目の後）。最後の `mark(N)` は残す。状態を書き換える最初の行（手順 2 の ROUTE_KEY、手順 4 の AI など）より前に置く。成功した手順の `DONE` は今の `mark` と同じ値になるので、流れは変わらない。手順 2 の `unmark` は `from google.colab import files` より前なので、`test_step2_route_defaults_to_published_pdf` の切り出しに当たらない。
- 手順 6（398 行目からのセル）: 回答の確かめ 3 つ（`AI != "manual"`・空・`PREVIOUS` と同じ）の直後、`res = convert(...)` の前に `unmark(5)` を入れ、セルの最後に `mark(5)` を足す。確かめで止まったときは `DONE` を変えない。変換が途中で止まったら手順 7・8 は guard で止まり、混ざった出力フォルダ（手順 6 は OUT を消さずに convert する）を使わない。成功したら `mark(5)` が 7・8 を消すので、反映し直した結果は手順 8 でダウンロードし直す（手順 9 の「まだダウンロードしていません」の確かめが働く）。
- 手順 9（488 行目）は `DONE = {1}` にするので変えない。
- GUARD の前のコメント（71〜72 行目）を「済んだ手順は変数 DONE に記録する。各手順の最初（guard の直後）で、自分とそれより後の手順を「未実行」に戻し（unmark）、最後まで済んだら自分を記録する（mark）。途中で止まった手順の後では、後ろの手順の guard が止める。」に直す。
- 新しい文は足さない。途中で止まった後は、今の GUARD の文「先に手順 N を実行してください（…前の手順をやり直したときは、その後の手順もやり直してください）」がそのまま出る。
- ipynb は直接直さない。この単位の commit では ipynb を入れない（版の最後に `python tools/make_notebook.py` で 1 回だけ作り直す。単位どうしの点検の順）。単位の確かめで全テストを回すときは、一時的に `python tools/make_notebook.py` を実行して `test_notebook_is_up_to_date` を通し、ipynb の差分は `git checkout notebooks/` で戻してから commit する。
- 1 画面版のノートブック（`launch()` だけ）は対象外。

### 12. 版

0.30.0（u1・u3-tables・u3-autonum・u4 と同じ版）。この単位では版を上げない（版の最後に 1 回だけ `__init__.py` と `pyproject.toml` を上げる）。出力の形は変わらない。

## テスト

`tests/test_app.py` に足す（架空の docx だけで作る。論文A・論文B は `tmp_path` に `tests/make_fixtures.py` の `make_article` で作り、題目と本文の段落を変える。本文の形は `docs/fix_plan_2026-11/protos/u2-app/repro_mix.py` の parts を手本にする）。文の確かめでは、どの文にも `"\x00"` と「手順」がないことも見る。

1. `test_inputs_changed_after_convert_are_refused`: `filled(tmp_path, docx=A)` を `ai_mode="manual"` で convert し、`set_inputs(docx=str(B), fpage="77")`。期待: `changed_inputs() == ["docx", "最初のページ"]`。`apply_answer('{"operations": []}')` は InputError で、文に「入力が前回の変換から変わっています」「「変換する」をもう一度押してください」「新しい依頼文が出る」がある。`st.res` は前と同じオブジェクトで、XML の fpage は 1。`download()` と `download(accept_todo=True)` は `(None, 同じ文)`。`ready_text()` に「入力が前回の変換から変わっています」があり、`result_html()` にはない。`set_inputs(docx=str(A), fpage=" １ ")` に戻すと `changed_inputs() == []` になり、`apply_answer` が通って XML の題目は論文A。fpage だけを変えたときの文は「貼り付けた回答は欄に残る」と「もう一度「反映」を押します」の側になる。
2. `test_same_file_reselected_is_not_a_change`: A を `tmp_path/"gradio"/"A.docx"` に写して docx に入れる（パスは違い中身は同じ）→ `changed_inputs() == []`。1 バイト違う同名ファイルにすると `["docx"]`。`docx=None` にすると `["docx"]` で、`on_apply` の `out[0]` に「入力が前回の変換から変わっています」があり「想定外のエラー」はない（再現 5 の TypeError がなくなる）。さらに `monkeypatch.setattr(app, "file_digest", 例外 OSError を出す関数)` にすると、`on_change` と `on_apply` が例外を外に出さず、`on_apply` は「入力が前回の変換から変わっています」の枠、`st.convert()` は「のファイルを読めませんでした」の InputError で、`st.res` と `st.run` は前のまま。
3. `test_images_not_carried_to_changed_input`: `monkeypatch` で `convert_metafiles=False` にし（既存の `test_missing_images_are_filled_per_figure` と同じ方法）、TEMPLATE を変換して `add_images` で 1 枚入れる。`set_inputs(docx=論文B)`。期待: `add_images` と `apply_answer` は「入力が前回の変換から変わっています」の InputError。`user_images` は残るが、論文B を `convert()` すると `{}` になり、論文B の結果に前の画像は入らない。
4. `test_ai_mode_change_after_convert_keeps_screen`（O3）: FULL を手動で convert し、`ai_mode="api"`、続けて `"none"` にして、それぞれで確かめる。期待: `waiting_for_answer` と `answer_box_open` は True のまま。`result_html()` に「AI の回答をまだ反映していません」も「AI による補完を「使わない」」も出ない。`changed_inputs() == []`。`ready_text()` に「次に変換するときに使われます」がある。`apply_answer('{"operations": []}')` が通る。逆に `ai_mode="none"` で convert してから `"manual"` にすると、`apply_answer` は「手動モードで変換してから」で断り、`answer_box_open` は False。
5. `test_failed_convert_keeps_previous_run`: FULL を none で convert し、`fpage="77"`・`ai_mode="api"` にして、環境変数のキーなしで `st.convert(app.IO())`（`monkeypatch.delenv` で `API_KEY_NAMES["claude"]` を消す）。期待: InputError。`st.run.meta.fpage` は前の値、`st.res` は同じオブジェクト。`changed_inputs() == ["最初のページ"]`。`download()` は `(None, 文)`。
6. `test_new_paper_clears_answer_field`: `build_app` の `fns` を使う。`on_convert(論文A の値)` の後、論文B の値で `on_convert`。期待: `len(out) == len(views) + 2`（views の数は `9 + app.MAX_IMAGE_SLOTS`）。`out[-2]` が `gr.update(value="")`（dict の `"value"` が `""`）。同じ docx で `on_convert` し直すと `out[-2]` に `"value"` がない。論文B を変換した後に受付日を「あした」にして `on_convert` すると、`out[0]` が入力の誤りの枠で、`out[-2]` に `"value"` がない（貼った回答を残す。点検の (a)）。入力（fpage）を変えて `on_change` の `ready` に「入力が前回の変換から変わっています」が出た後、`on_convert` に成功すると `out[-1] == ""`。
7. `test_previous_paper_answer_refused`: 論文A を手動で convert し、`ans_A`（論文A の本文の段落 ID に set_role exclude の 1 件）を `apply_answer`。docx=論文B にして convert し、`apply_answer(ans_A)`。期待: InputError「前に別の依頼文（A.docx のとき）に対して反映した AI の回答です」。論文B の XML に論文B の段落が残る（変換していない）。`reset()` の後に論文B を入れて変換し直しても同じく断る。違う回答（`'{"operations": []}'`）は通る。A と同じ中身の docx（別のパス）と、同名で中身は違うが依頼文の変わらない docx（A の `docProps/core.xml` の更新日だけを書き換えたもの。本文を変えると依頼文も変わるので使わない）では、`ans_A` が通る。依頼文が変わったこと（本文の 1 段落を足した A）では断る。
8. `test_stopped_convert_leaves_no_stale_text`: FULL を none で convert した後、図の位置を AI が決める必要のある fixture（`conftest.FLOAT`）を none で convert して AIRequiredError（InputError）で止める。期待: `st.res is None` で `st.run` は残る。fpage を変えても `changed_inputs() == []`、`ready_text()` に「今の結果は」がない、`answer_box_open` は False。0.31.0 の u6 が、同じ形を K1 の docx（StructureConflictError）でも足す。
9. `test_subject_other_ignored_unless_other_type`: 原稿種別が「その他」でないとき、`subject_other` を変えても `changed_inputs() == []`。「その他」にして変換した後に変えると `["原稿種別（日本語）"]`。
10. `test_app_words_match_the_real_labels` に足す: `stale_text(["docx"])`・`stale_text(["最初のページ"])`・`settings_note` の文（ai_mode を変えた状態で作る）と、「読めませんでした」の文に `"\x00"`・「手順」がなく、「…」で囲んだ名前が画面のラベルにある。

`tests/test_notebook.py` に足す:

11. `test_failed_step_drops_later_steps`: `repro_notebook.py` と同じく `google.colab` の `files.upload` を偽物にする（`monkeypatch.setitem(sys.modules, ...)`）。セルの `Path("/content/jasme_work")` を `Path(str(tmp_path))` に置き換えてから exec する。手順 2 のセルを `DONE={1,2,3,4,5}`、uploads=`[{"B.docx": b"PK"}, {}]`（PDF なし）で exec → SystemExit の後 `DONE == {1}`、`mk.guard(1, 2, 3, 4, 5)` の exec が SystemExit。手順 3 のセルに受付日「あした」と査読ありを入れて `DONE={1,2,3,4,5}` で exec → SystemExit の後 `DONE == {1, 2}`。手順 6 のセル（`"AI_RESPONSE = r'''"` で探す）で `convert` を例外を出す関数にして exec → `5 not in DONE`。成功した手順 6（`test_step6_shows_ai_error_box_before_report` と同じ ns で `DONE={1,2,3,4,5,7,8}`）の後は `DONE == {1,2,3,4,5}`。
12. `test_step_guard_and_mark` に足す: `exec(mk.unmark(3), ns)` で `{1,2,3,4}` が `{1,2}` になる。

既存のテストの直し:

- `test_apply_crash_before_result_dropped_keeps_manual_fields`: `monkeypatch.setattr(app.shutil, "copyfile", boom)` を `monkeypatch.setattr(app, "Options", boom)`（`OSError("写せません")`）に替える。写しは `convert()` に移り、`_run` は Options を作ってから結果を捨てるので、期待（res が残る・手動の欄が見える・「そのまま残っています」）は同じ。docstring の「入力ファイルを作業用の場所に写せないなど」を「変換の設定を作れないなど」に直す。
- `test_manual_fields_stay_for_repaste` の最後の 2 行: 期待は同じ。コメントを「変換の後に「AI による補完の方法」の欄を変えても判定は変わらない（O3）。この時点では貼り直す枠がないので欄は出ない」に直す。
- `test_image_slots_in_view`: 変えない（`answer_box_open` が `self.run is None` で先に False を返す）。通ることを確かめる。
- `test_unexpected_error_is_shown_and_old_result_dropped`・`test_unexpected_error_in_apply_answer`・`test_apply_crash_hides_manual_fields_as_advised`: `convert()` が run を作ってから `_run` で止まるので、そのまま通るはず。`out[0]`〜`out[8]` の添字は変わらない（on_convert は末尾に 2 つ足すだけ）。確かめる。
- `tests/test_notebook.py` の `test_step_guard_and_mark`・`test_step9_resets_for_next_article`・`test_step7_uploads_missing_images_one_by_one`・`test_step8_*`・`test_step6_shows_ai_error_box_before_report`: `unmark`・`mark(5)` を足した後の `DONE` の値で期待が変わらないかを確かめる。手順 8 の「一度止める」の 2 回目の ▶ は、8 が DONE にない状態で進むので変わらない。
- `test_notebook_is_up_to_date`: 11 節のとおり、確かめのときだけ作り直す。

## 回帰の確かめ（基準との比較で想定する違い）

- 基準（u1 の fixture の作り直しの直後に 0.29.0 のコードで取ったもの。fixture 15 件と tests/private 10 件、ルート1 と PDF のある 6 件のルート2）と比べ、XML のハッシュ・actions の key と level・除外の理由ごとの件数・warnings の件数・ZIP の一覧と画像のハッシュ・終了コードは**すべて同じ**（違いは 0）。この単位は pipeline・report を変えない。
- `python -m pytest -q` を全部回す（1298 件＋追加分）。`tests/test_syntax.py`（Python 3.10）も通す。
- 画面の確かめ（実装者が手で 1 回。Colab でなくてもよい。`python -c "from jasme_jats.app import launch; launch(inline=False)"` などで開く）: 変換 → ページを変える → 「反映」「画像を入れる」「結果をダウンロード」が断られ、`ready` に文が出る → 戻すと通る → 別の docx で「変換する」を押すと回答の欄が空になり `ready` が空になる。
- 動きが変わるところ（意図したもの）: 入力を変えた後の 3 つの操作が断られる。AI の方法を変えても手動の欄は残る。別の論文で変換すると回答の欄が空になる。ノートブックの手順 6 の後は手順 8 をやり直す必要がある（`mark(5)` が 7・8 を消す）。手順 6 が想定外の例外で止まると手順 5 からやり直しになり、手順 5 は添付画像をもう一度ダウンロードさせる（害は小さい）。
- 速さ: `fingerprint()` は `on_change` のたびに docx・PDF の digest を求めるが、2 回目からは覚えを使う。最初の 1 回は数 MB の sha256（数十 ms）。

## ほかの単位・ルート2・AI 補完・画面との関係

- 同じファイルを触る順: `app.py` は u2 → u5 → u6、`tools/make_notebook.py` は u2 → u6。0.30.0 ではこの単位は u1 の (1b)(1c)(1d) と並行してよい（触るファイルが重ならない）。
- u5（0.31.0）: `REPASTE_KEYS` に `abstract_missing` を足す。この単位の `answer_box_open` の最初の条件の変更と同じ場所なので、u5 は u2 の形の上に足す。
- u6（0.31.0）: `_run` の `except AIRequiredError` の隣に `except StructureConflictError` を足す（5 節）。中止のときは `self.run` が残り `self.res` が None になるので、`changed_inputs()` は `[]`、`settings_note()` は `""` で、`ready` に紛らわしい文は出ない。`on_convert` の戻りは中止の経路でも `views + [answer, ready]`（9 節の `tail()` を通る）。u6 は、テスト 8 と同じ形を K1 の docx で足す。ノートブックの手順 5 は u6 で `guard → unmark(5) → … → try: convert / except AIRequiredError / except StructureConflictError（structure_conflict_box と SystemExit）→ … → mark(5)` になり、手順 6 は `unmark(5) → convert → mark(5)` のまま、u6 が守りの except を 1 行足す。`test_steps5_and_6_show_result_boxes`（セル 5・6 に `error_box(` を書かない）とテスト 11 の両方を満たす。
- `pipeline.convert` の順（単位どうしの点検の決定）には触れない。
- O1（0.29.0）: `_run` は今も最初の段階で `self.res` を捨て（Options を作った後）、`crash()` と `CRASH_ADVICE` の文は変えない。新しい状態での確かめ:
  - `apply`: `_run` が結果を捨てた後に止まる → 手動の欄は隠れ、「変換する」を押すと同じ docx なので回答の欄が残る（案内どおり）。
  - `apply_kept`: Options を作れない・依頼文を読めないなど、捨てる前に止まる → 結果と欄が残る（案内どおり）。
  - `images`・`download`: 変わらない。入力が変わっていれば先に断るので、crash の経路には入らない。
- ルート2: PDF も中身の digest で比べ、route・PDF を変えても「変わった」として断る（どちらも出力の形を変える）。補った docx は out_dir に作られ、`_run` の rmtree で毎回作り直されるので写しの対象にしない。
- AI 補完: pipeline は回答がどの docx 用かを知らない。画面の側で、入力が変われば断る・別の論文で変換したら回答の欄を空にする・前に別の依頼文へ反映したのと同じ文字の回答は断る、の 3 つで、別の論文の回答が当たる経路を塞ぐ。文字の違う別の論文の回答（段落 ID が重なるもの）は、依頼文に印を入れて回答に返させないと防げない。今回は入れず REVIEW に記録する（計画者の決定）。
- `report.actions()`: 何も足さない。入力の変化は画面の状態の扱いで、O1 と同じく Action ではない。文の中の操作は `rp.step("convert_again" / "prompt" / "apply_button" / "docx" / "pdf")` で書き、`_app_text` で置き換える。新しい目印（STEP_NAMES）は足さない。
- コマンドライン: 変えない。終了コード（0・1・2）にも関係しない。
- 再現スクリプトの移し替え: tests/private/review-repros/reproduce.py の 'app-input-change' の部分は、この単位のテスト 1〜7 で正式なテストになる。reproduce.py は利用者のフォルダなので実装者は直さず、移した項目として最後の報告の一覧に入れる。

## 利用者向けの文

どれも Action ではない。`_app_text` で 1 画面版の語にした形で書く。

- 変換ボタンの横（`ready`）: 「足りない項目: …」の後に、入力が変わったときは次の文、AI の方法・モデルだけを変えたときは settings_note を出す。
  - docx・PDF・作り方・SPLIT_LABELS が変わったとき: 「入力が前回の変換から変わっています（変わった項目: docx、最初のページ）。今の結果は、変える前の入力で作ったものです。変えた入力で作るには、「変換する」をもう一度押してください（入れた画像は消えるので、変換の後にもう一度入れてください。手動モードでは新しい依頼文が出るので、AI に渡して回答を貼り替えます）。今の結果のまま続けるときは、入力を前回の変換のときの値に戻してください（同じファイルを選び直せば、変わっていない扱いになります）。」
  - それ以外（ページ・日付など）だけが変わったとき: 括弧の中が「入れた画像は消えるので、変換の後にもう一度入れてください。貼り付けた回答は欄に残るので、変換の後にもう一度「反映」を押します」になる。
  - settings_note: 「「AI による補完の方法」の欄・MODEL の変更は、次に変換するときに使われます（今の結果は前の設定のままです。変えた設定で作るには、「変換する」をもう一度押してください）。」
- 「反映」「画像を入れる」: 上の stale_text を、赤い枠「入力を確認してください」に出す。結果・手動の欄・画像の欄・貼り付けた回答は消さない。
- 「結果をダウンロード」: 赤い枠「ダウンロードの前に」に stale_text。「このままダウンロード」にチェックを入れても断る。
- 「変換する」でファイルを読めないとき: 「「docx（論文の Word ファイル）」の欄のファイルを読めませんでした。選び直してから、「変換する」をもう一度押してください。」（PDF なら PDF の欄）。前の結果は残る。
- 前の論文の回答: 「貼り付けられているのは、前に別の依頼文（A.docx のとき）に対して反映した AI の回答です。今の依頼文を AI に渡し、返ってきた回答に貼り替えてから「反映」を押してください。」
- 結果の欄（`result_html`）には新しい枠を出さない。
- ノートブック: 新しい文はない（GUARD の今の文が出る）。

## 文書の更新（CLAUDE.md は案だけ）

版の最後に 1 人（Opus）がまとめて直す（単位どうしの点検の決定）。この単位の実装者は、コードの中のコメント・docstring（app.py の `convert`・`answer_box_open`・224 行目のコメント、make_notebook.py の GUARD のコメント）だけを直す。

- `docs/USAGE.md` の「一般の利用者用（1 画面）の使い方」の 4.・5.（13〜21 行目のあたり）: 変換の後に入力（ファイル・ページ・日付・作り方など）を変えたら「変換する」を押し直すこと、押すまでは「反映」「画像を入れる」「結果をダウンロード」が断られること（入力を戻せば続けられる。同じファイルの選び直しは変わっていない扱い）、AI による補完の方法・MODEL の変更は次の変換から使われること、別の論文に変えて変換すると回答の欄が空になることを足す。
- `docs/ARCHITECTURE.md` の app.py の行（206 行目）: 「`_run` は最初に前の結果を捨てる」を「変換したときの入力の写し `AppState.run`（`RunInputs`。ファイルは中身の sha256）を `_run`・`apply_answer`・`add_images`・`download` が使い、入力が写しと違えば断る（`changed_inputs`・`stale_text`）。手動かどうかは写しで決める（O3）。`_run` は Options を作ってから前の結果を捨てる」に直す。データの流れの app.AppState の行も合わせる。行数の表は wc -l に合わせる。
- `docs/DEVELOPMENT.md` の 42 行目（app.py の説明）: 上と同じ形に直す（「`_run` は最初に前の結果 `self.res` を捨てる」を、写しが `convert` に移り、Options を作ってから捨てる形に）。原則 8 の注は直さない（結果の欄に黄色い枠を足さないため）。
- `docs/REVIEW_2026-11.md`:
  - O3 を 0.30.0 で直したと記録し、場所の行番号「app.py 225〜228」を直す（0.29.0 では `waiting_for_answer` が 233〜236 行目、`answer_box_open` が 244〜257 行目）。
  - 新しい項目（O 系の続きの番号。今の最後は O14）として、直したものを足す: 1 画面版で変換の後に入力を変えると前の変換と混ざる（入力の写し）、「変換する」で別の論文に変えても前の回答が欄に残る、従来のノートブックで途中で止まった手順の後も後ろの手順の「済み」が残る。
  - 未修正の新しい項目として足す: 「AI の回答がどの依頼文への回答かを確かめない（コマンドラインの `--ai-response`・ノートブック・1 画面版。1 画面版とノートブックは同じ文字の回答だけを断る）。依頼文に docx の短い印を入れて回答に返させる案（依頼文・RESPONSE_SCHEMA・回答の確かめに触れる）」。
- `docs/GUI_PLAN.md` の 8 章（「試作で割り切った点」の近く、346 行目のあたり）: 変換の後に入力を変えたときの扱い（結果を残して断る。ファイルは中身で比べる。別の論文で変換すると回答の欄を空にする）を 1 行足す。
- `tools/make_notebook.py` の GUARD のコメント: 11 節（実装者が直す）。
- CLAUDE.md: この単位では直す案はない。

## 文書とコードの食い違い

1. app.py 224 行目のコメント「前の変換で受け取った画像は持ち越さない（同じ論文のやり直しは apply_answer）」: `apply_answer` が同じ論文だと決まっているように書くが、0.29.0 のコードは今の入力の docx を読むので、別の論文にも画像を入れる（再現 3）。この単位でコードを直し、コメントも 4 節 6 のとおりに直す。
2. `docs/ARCHITECTURE.md` の app.py の行と `docs/DEVELOPMENT.md` 42 行目の「`_run` は最初に前の結果（self.res）を捨てる」: 0.29.0 の `_run` は、入力を work/input に写してから `self.res = None` にする（184〜195 行目。`test_apply_crash_before_result_dropped_keeps_manual_fields` も写しが先なことを前提にしている）。この単位で写しを `convert()` へ移し、`_run` は Options を作ってから捨てる形になるので、文書を新しい形に合わせる（版の最後）。
3. `docs/REVIEW_2026-11.md` の O3 の場所「app.py 225〜228」: 0.29.0 では `waiting_for_answer` が 233〜236 行目、`answer_box_open` が 244〜257 行目で、ずれている（版の最後に直す）。
4. `AppState.convert` の docstring「足りない項目・入力の誤り・API キーの読み出し失敗は InputError」: API キーを読めずに止まるときも `self._meta`・`self._journal` を上書きした後で、前の結果と新しい meta が混ざる副作用が書かれていない（再現 6）。コードを直し、docstring に「確かめで止まったときは前の結果と写しを残す」を足す。
5. make_notebook.py の GUARD の前のコメント「ある手順をやり直したら、それより後の手順は「未実行」に戻す」: 0.29.0 で戻すのは手順の最後（`mark`）だけで、途中で止まった手順では戻らない（再現 9）。この単位でコードを合わせ、コメントも直す。
6. `answer_box_open` の docstring「回答の反映（apply_answer）ができるときだけ見せる（waiting_for_answer と同じく、「AI による補完の方法」の欄が手動のとき）」: 欄（入力）で決めること自体が O3 の原因。写しで決める形にし、docstring を直す（8 節）。

## 新しく見つけた問題（この単位で直すもの／直さず REVIEW に記録するもの）

この単位で直すもの:

- 「変換する」で別の論文に変えても回答の欄に前の論文の回答が残り、そのまま「反映」できる（再現 8。9 節・6 節）。
- `ready` が `on_change` でしか書き換わらず、変換し直した後も古い文が残る（点検で見つけた。9 節）。
- 変換の後に docx の欄を空にして「反映」すると、入力の問題なのに「想定外のエラー」（不具合の案内）になる（再現 5。写しで動き、入力の違いとして断る）。
- ノートブックの手順 8 が、手順 2 が途中で止まった後に、論文A の ZIP を「（B.docx）」と表示し、`CONVERTED`・`PREVIOUS` にも B と記録する（変数の値をたどって確かめた。`unmark(2)` で手順 8 は guard で止まる）。
- ノートブックの手順 3 が入力の誤りで止まった後に手順 5 を押すと、`ArticleMeta.from_dict` の ValueError が素のトレースバックで出る（`unmark(3)` で guard が止める）。
- ノートブックの手順 6 は OUT を消さずに convert するので、途中で止まると OUT が一部だけ書き換わり、手順 7・8 がその出力を使うおそれがある（確かめていない。`unmark(5)` で手順 7・8 は止まる）。
- `stale_text` の分岐を docx だけでなく PDF・作り方・SPLIT_LABELS に広げる（計画の書き手の判断。依頼文は docx の構造・除外・分けなかった名前から作るので、これらを変えると依頼文が変わり得て、6 節の確かめで前の回答が断られる。「欄の回答でもう一度反映」と案内して断る食い違いを避ける）。

直さず REVIEW に記録するもの:

- AI の回答がどの依頼文への回答かを pipeline が確かめない（コマンドライン・ノートブック・1 画面版）。実際の原稿では本文の段落 ID の 98％（135 件中 132 件）が別の論文と重なった。依頼文に docx の digest の短い印を入れて回答に返させる案（未修正の新しい項目）。
- 日付の書き方の違い（2026/3/31 と 2026-03-31）など、ArticleMeta では同じになる入力も「変わった」と判定する（断る側に倒れるだけ。戻すか変換し直せば続けられる）。REVIEW には書かず、この設計書に残すだけでよい。
- 従来のノートブックのフォームの値は ▶ を押すまで変数にならない（手順 3 の欄を書き換えて ▶ を押さずに手順 5 を押すと、前の値で変換する）。Colab の仕様でセルの中からは読めないので直せない。USAGE.md に書くかは版の最後に決める（確かめていない）。

## 未決のこと（利用者の返事待ち／実装のときに確かめること）

利用者の返事待ち:

- なし（入力が変わったときのダウンロードは「このままダウンロード」でも断る、前の論文の回答は依頼文の digest で結び付ける、依頼文に印を入れる案は今回入れない、を計画者が決めた）。
- 再現スクリプトの移し替え（tests/private/review-repros/reproduce.py の 'app-input-change' を利用者が消すか）は、計画の「利用者に聞くこと」の 4 で聞く。

実装のときに確かめること:

- Gradio のアップロードの写し（キャッシュ）が、同じ画面を開いている間に消えないこと（`gr.Blocks` に `delete_cache` を渡していないので消えないはず）。消えると `fingerprint()` が「読めない」になり、入力が変わった扱いで断る（害は「選び直してください」で済む）。
- 依頼文がない手動の結果（`prompt_path` が None。`prompt_text()` が `""`）でも `apply_answer` の確かめが落ちないこと（`""` の digest を使う。画面では手動の欄が隠れるので、通常は押せない）。
- `on_convert` の出力に `ready` を足しても、Gradio が同じ部品を `on_change` と `on_convert` の両方の出力に持つことを許すこと（許すはず。`build_app` のテストで組めることを確かめる）。
- 既存の `test_unexpected_error_*`・`test_image_slots_in_view`・ノートブックのテストが、直した後もそのまま通ること（テストの節）。

## 点検の指摘の反映表

| 重さ | 題 | 反映した節 |
|---|---|---|
| major | paper_changed が convert の最初で戻らず、入力の誤りで止まった変換でも回答の欄を空にする | 直し方 4 の 1（最初の行で False）、テスト 6 |
| major | 変換ボタンの横の文（ready）が on_convert で書き換わらず、変換し直した後も残る | 直し方 9（出力を views + [answer, ready]）、テスト 6 |
| major | file_digest の OSError が crash の後の view() からも出て on_apply の外へ抜ける。既存テストの書き換え案が通らない | 直し方 3（fingerprint が OSError をすべて捕まえる）・4 の 4（読めない印の InputError）・5（Options を先に作る）、テスト 2、既存テストの直し（monkeypatch 先を app.Options に） |
| major | 前の論文の回答の確かめを docx の中身で結び付けると、直した版の docx への正しい再利用を断り、文も紛らわしい | 直し方 6（依頼文の digest で結び付け、文を「前に別の依頼文（…のとき）」に）、テスト 7 |
| minor | 結果の欄の黄色い枠は原則 8 との関係が書かれておらず、同じ長い文が 3 か所に出る | 直し方 8（result_html に枠を足さない）、文書の更新（原則 8 は直さない） |
| minor | 結果がないとき（変換が止まった後）にも「今の結果は…」の文が出る | 直し方 3（changed_inputs・settings_note は res が None なら空）、テスト 8 |
| minor | stale_text が docx を変えていないときにも新しい回答を求めているように読める | 直し方 3 の stale_text（2 通りの文。分岐を PDF・作り方・SPLIT_LABELS にも広げた）、利用者向けの文 |
| minor | 結果を左右しない入力の違いでも「変わった」と判定する | 直し方 3 の fingerprint（その他でないときの subject_other）、テスト 9。日付の書き方の違いは直さない（新しく見つけた問題） |
| minor | ノートブックのテストの形に、作業フォルダの差し替えが書かれていない | テスト 11（`/content/jasme_work` を tmp_path に置き換えてから exec） |
| minor | 文書の更新の一覧に、原則 8 と REVIEW の新しい未修正の項目が足りない | 文書の更新（REVIEW に未修正の項目を足す。原則 8 は枠を足さないので直さない） |
