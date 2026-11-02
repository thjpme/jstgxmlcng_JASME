# GUI を直している担当への連絡（2026-11-01。main 0.26.1 のノートブックの手順 1 の直し）

## 起きていたこと（原因）

- ブランチ `docs/gui-plan` のノートブック（G1 で作り直したもの、版 0.26.1 と表示）は、手順 1 で **main のツール（0.26.0）** を入れる
  （`BRANCH = "main"`。開発版のチェックを入れない限り、どのブランチのノートブックでも main から入る）。
- main の 0.26.0 には、ブランチで足した `colab.summary_box`・`colab.report_details`・`check_box`、pyproject の `colab`・`gui` の extras、`app.py` がない。
  - 手順 1: pip は `jasme-jats[ai,images,colab]` の `colab` を「ない extra」として警告するだけで成功し、「※ このノートブックの説明は版 0.26.1 のものです。
    ノートブックを開き直してください」と出て、そのまま先に進める形だった（止まっているように見える）。
  - 手順 5: `from jasme_jats.colab import … report_details, summary_box` で ImportError になる（ツールが main のものだから）。
- ブランチ自体のコードは問題ない（`docs/gui-plan` を入れた venv で pytest 901 件合格。Gradio 6.31.0 は PyPI にあり、依存の解決も通る〈75 パッケージ〉。
  Colab の既存パッケージとの衝突は未確認）。

## main に入れた直し（コミット 56d5b59、版 0.26.1。`tools/make_notebook.py`・`tests/test_notebook.py`・`docs/DEVELOPMENT.md`）

1. `python tools/make_notebook.py --branch <ブランチ名>` で作ると、手順 1 の既定の `BRANCH` がそのブランチになる（`render(branch)`。
   `BRANCH = "main"` の行だけを置き換える。`notebook_branch(text)` でノートブックからブランチ名を読める）。main に反映するときは `--branch` なしで作り直す。
2. 手順 1 は、入ったツールの版がノートブックの版と違うとき、
   - main のノートブック（`BRANCH == "main"`）なら **止める**（「入ったツールの版（…）が、このノートブックの版（…）と違います。GitHub の main から開き直すか、
     開発中の版なら USE_DEV_VERSION にチェックを入れてブランチ名を入力」）。後の手順でツールにない機能を呼んで止まるのを防ぐ。
   - 開発版のノートブック（`--branch` で作ったもの、または USE_DEV_VERSION）なら知らせるだけ。
   - 版を読めなかったとき（`ver` が空）も止める。
3. `tests/test_notebook.py` の一致の確認は、ノートブックに書かれたブランチで作り直して比べる（`--branch` で作ったノートブックでも通る）。
   `test_notebook_branch_and_version_check` を足した。

## ブランチ側でやってほしいこと

1. main（56d5b59。G の 0.26.0 と、この 0.26.1）を `docs/gui-plan` にマージする。衝突しそうな場所: `tools/make_notebook.py`（手順 1 の雛形の末尾〈版の確認〉と
   末尾の `render`・`__main__`。main 側を採り、G1 の `[ai,images,colab]` と G2 の `_PREP_GRADIO` はそのまま）、`tests/test_notebook.py`、`__init__.py`・`pyproject.toml` の版、
   `README.md`（G の説明が 0.26.0 で足した「できないこと・注意点」の項目と、G1 で USAGE.md に移した部分）、`notebooks/*.ipynb`（作り直すので中身は気にしなくてよい）。
2. 版の番号: main は 0.26.1 になった。ブランチの「G1（0.26.0）」「G2（0.26.1）」の表示は main と衝突するので、マージのときに次の番号（0.26.2 以降。
   単位 H が近く 0.27.0 を取る予定なので、H の後にマージするなら 0.27.1 以降）にする。
3. ノートブックは `python tools/make_notebook.py --branch docs/gui-plan` で作り直す。試作の Gradio ノートブック（`_PREP_GRADIO`）も、同じ `BRANCH = "main"` の置き換えが
   効く形にする（`render(branch)` と同じ置換を試作側にも通す。今の `render` は `cells`〈本体のノートブック〉だけを置き換える）。
4. Colab で試すときは、GitHub からノートブックを開くときにブランチを `docs/gui-plan` にする（main のノートブックを開くと 0.26.1 のツールが入り、手順 1 の版の確認は通るが、
   ブランチの画面は出ない）。`--branch` で作ったノートブックなら、USE_DEV_VERSION のチェックは要らない。
5. main に反映するときは `--branch` なしで作り直し、`BRANCH = "main"` に戻す（`test_notebook_is_up_to_date` は、どちらの形でも通る）。

## 手順 5 について

- ブランチのコードと手順 5 のセルは合っている（`summary_box`・`report_details` はブランチの `colab.py` にある）。main のツールが入っていたことが原因なので、
  上の 1・3・4 で直る。
- main から入れたときの `colab` の extra は警告だけで、`markdown` は入らない。`report_details` は `markdown` がないと `<pre>` に退避する（この挙動は残してよい）。
