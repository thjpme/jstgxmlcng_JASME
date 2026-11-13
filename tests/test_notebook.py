"""Colab ノートブック: 生成スクリプトとの一致、各セルの構文、手順の順序の確認。"""
import importlib.util
import json
from pathlib import Path

import pytest

from jasme_jats import __version__

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("make_notebook", ROOT / "tools" / "make_notebook.py")
mk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mk)


def test_notebook_is_up_to_date():
    # ノートブックを直したら python tools/make_notebook.py を実行すること（開発中の版のノートブックは --branch で作る）
    text = mk.OUT.read_text(encoding="utf-8")
    assert text == mk.render(mk.notebook_branch(text))


def test_notebook_branch_and_version_check():
    # main のノートブックは main から入れる。--branch で作ると手順 1 の既定のブランチだけが変わる
    main_nb, dev_nb = mk.render(), mk.render("docs/gui-plan")
    assert mk.notebook_branch(main_nb) == "main" and mk.notebook_branch(dev_nb) == "docs/gui-plan"
    step1_main, step1_dev = ("".join(json.loads(nb)["cells"][1]["source"]) for nb in (main_nb, dev_nb))
    assert 'BRANCH = "main"' in step1_main and 'BRANCH = "docs/gui-plan"' in step1_dev
    assert step1_main.replace('BRANCH = "main"', 'BRANCH = "docs/gui-plan"') == step1_dev
    assert [c for c in json.loads(main_nb)["cells"][2:]] == [c for c in json.loads(dev_nb)["cells"][2:]]
    # 入ったツールの版がノートブックの版と違うとき、main のノートブックは手順 1 で止めて開き直してもらう（後の手順で
    # ツールにない機能を呼んで止まるのを防ぐ）。開発版のノートブックは知らせるだけ
    step1 = cell_source("#@title 1. 準備")
    assert f'ver.startswith("{__version__}")' in step1
    assert "main から開き直して" in step1 and "手順の説明や画面が合わないことがあります" in step1


def test_notebook_shows_version_and_cells_compile():
    nb = json.loads(mk.render())
    assert f"ツールの版: {__version__}" in "".join(nb["cells"][0]["source"])
    for c in nb["cells"]:
        if c["cell_type"] == "code":
            compile("".join(c["source"]), "cell", "exec")


def test_gradio_notebook_is_up_to_date_and_cells_compile():
    """1 画面版（Gradio）のノートブック（準備と画面を 1 つのセルで）も、生成と一致し、セルが構文として正しく、Gradio を入れて share なしで開く。"""
    text = mk.OUT_GRADIO.read_text(encoding="utf-8")
    assert text == mk.render_gradio(mk.notebook_branch(text))      # --branch で作ったものも、同じ置き換えが効く
    assert 'BRANCH = "docs/gui-plan"' in "".join(json.loads(mk.render_gradio("docs/gui-plan"))["cells"][1]["source"])
    nb = json.loads(mk.render_gradio())
    sources = ["".join(c["source"]) for c in nb["cells"]]
    assert f"ツールの版: {__version__}" in sources[0] and "画面が開きます" in sources[0] and "従来版" in sources[0]
    codes = [src for c, src in zip(nb["cells"], sources) if c["cell_type"] == "code"]
    assert len(codes) == 1                          # 準備と画面を 1 つのセルで
    compile(codes[0], "cell", "exec")
    cell = codes[0]
    assert "jasme-jats[ai,images,colab,gui]" in cell and "DONE" not in cell and "手順 2" not in cell and "手順 1" not in cell
    assert cell.index("LO_PROC = subprocess.Popen") < cell.index('"pip", "install"')      # LibreOffice を先に裏で始める
    assert "from jasme_jats.app import launch" in cell and "_app = launch()" in cell
    # 2 回目（ツールが読み込み済み）は入れ直さずに画面を開き直す
    assert "if loaded_before:\n    print(" in cell and "_app.close()" in cell


def test_default_model_comes_from_ai_assist():
    """手順 4 の MODEL の既定と選択肢は、パッケージの ai_assist.DEFAULT_MODEL と同じ（修正計画の U5。make_notebook.py は
    ai_assist.py をファイルとして読むので、その読み方の誤りも、パッケージから import した値と比べて捕まえる）。
    説明書 docs/USAGE_AI.md のモデル名・料金・提供終了の予定も DEFAULT_MODEL_INFO と同じ（説明書は手で書くので、ずれたら直す）。"""
    from jasme_jats.ai_assist import DEFAULT_MODEL, DEFAULT_MODEL_INFO
    assert mk.DEFAULT_MODEL == DEFAULT_MODEL and mk.DEFAULT_MODEL_INFO == DEFAULT_MODEL_INFO
    assert f'MODEL = "{DEFAULT_MODEL}"  #@param ["{DEFAULT_MODEL}", "自動（最新の Opus）"]' in cell_source("#@title 4.")
    usage_ai = (ROOT / "docs" / "USAGE_AI.md").read_text(encoding="utf-8")
    assert f"`{DEFAULT_MODEL}`（{DEFAULT_MODEL_INFO['name']}）" in usage_ai
    assert (f"既定のモデル `{DEFAULT_MODEL}` は、入力 100 万トークンあたり {DEFAULT_MODEL_INFO['input_usd']} ドル、"
            f"出力 100 万トークンあたり {DEFAULT_MODEL_INFO['output_usd']} ドル") in usage_ai
    y, m, d = (int(x) for x in DEFAULT_MODEL_INFO["not_before"].split("-"))
    assert f"提供終了は {y} 年 {m} 月 {d} 日より前にはならない" in usage_ai


def test_module_constants_reports_missing_line(tmp_path):
    """make_notebook.module_constants は、パッケージを import せずに「名前 = リテラル」を読み、行がない（式で書いた）ときは
    分かるエラーで止める（.group の AttributeError などにしない）。"""
    path = tmp_path / "ai_assist.py"
    path.write_text('X = 1\nY: dict = {"a": [1, 2]}\nDEFAULT_MODEL = "claude-" + "opus"\n', encoding="utf-8")
    assert mk.module_constants(path, ("X", "Y")) == {"X": 1, "Y": {"a": [1, 2]}}
    with pytest.raises(SystemExit, match="DEFAULT_MODEL = … の行が見つかりません"):
        mk.module_constants(path, ("X", "DEFAULT_MODEL"))


def test_step_guard_and_mark():
    ns = {}
    with pytest.raises(SystemExit, match="先に手順 1・2 を"):
        exec(mk.guard(1, 2), ns)
    ns = {"DONE": {1, 2}}
    exec(mk.guard(1, 2), ns)
    # 手順 3 をやり直すと、それより後の手順（4, 5）は未実行に戻る
    ns = {"DONE": {1, 2, 3, 4, 5}}
    exec(mk.mark(3), ns)
    assert ns["DONE"] == {1, 2, 3}
    with pytest.raises(SystemExit, match="先に手順 4 を"):
        exec(mk.guard(1, 2, 3, 4), ns)
    # 手順の最初の unmark は、自分とそれより後の手順を（成功するかどうかにかかわらず）未実行に戻す
    ns = {"DONE": {1, 2, 3, 4}}
    exec(mk.unmark(3), ns)
    assert ns["DONE"] == {1, 2}


def fake_display(monkeypatch):
    """Colab の画面表示（IPython.display）の代わり。表示したものを返すリストに貯める。"""
    import sys
    import types
    shown = []
    ipy = types.ModuleType("IPython.display")
    ipy.HTML, ipy.display, ipy.Image = (lambda x: x), shown.append, (lambda **kw: kw)
    monkeypatch.setitem(sys.modules, "IPython", types.ModuleType("IPython"))
    monkeypatch.setitem(sys.modules, "IPython.display", ipy)
    return shown


def cell_source(title_prefix):
    cell = next(c for c in json.loads(mk.render())["cells"] if "".join(c["source"]).startswith(title_prefix))
    return "".join(cell["source"])


def test_step9_resets_for_next_article(monkeypatch):
    """手順 9: ダウンロード前なら一度止めて確かめ、もう一度押すと、前の論文を記録して手順 2 からやり直せる状態にする。"""
    shown = fake_display(monkeypatch)
    src = cell_source("#@title 9.")
    ns = {"DONE": {1, 2, 3, 4, 5}, "docx_path": Path("first.docx"), "meta_input": {"volume": "31", "fpage": "1"},
          "LAST_AI_RESPONSE": '{"operations": []}', "res": object()}
    with pytest.raises(SystemExit, match="まだダウンロードしていません"):
        exec(src, ns)
    exec(src, ns)                                   # もう一度押すと、ダウンロードせずに進める
    assert ns["DONE"] == {1}
    assert ns["PREVIOUS"] == {"docx": "first.docx", "meta": {"volume": "31", "fpage": "1"},
                              "ai_response": '{"operations": []}'}
    assert "docx_path" not in ns and "res" not in ns and "_DISCARD_OK" not in ns
    # 入力欄に前の論文の値が残ることを、赤い枠で目立つように知らせる（開き直す方法も示す）
    assert "前の論文（first.docx）の値が残っています" in shown[-1] and "開き直して" in shown[-1]
    # ダウンロード済み（手順 8 を実行済み）なら、1 回で進む
    ns.update(DONE={1, 2, 3, 4, 5, 8}, docx_path=Path("second.docx"), meta_input={"volume": "31", "fpage": "13"},
              USER_IMAGES={"31_1_fig01.png": ("a.png", b"")})
    exec(src, ns)
    assert ns["DONE"] == {1} and ns["PREVIOUS"]["docx"] == "second.docx"
    assert "USER_IMAGES" not in ns                  # 前の論文の画像は持ち越さない


def _png(size=(120, 80)):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, "PNG")
    return buf.getvalue()


def _template_result(tmp_path):
    from conftest import TEMPLATE
    from jasme_jats.config import ArticleMeta, JournalConfig
    from jasme_jats.pipeline import Options, convert
    meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "peer_review": "あり"})
    # EMF を変換しない設定では、テンプレートの図 1 の画像を用意できない
    return convert(TEMPLATE, meta, JournalConfig.load(), Options(out_dir=tmp_path / "output", convert_metafiles=False))


def test_step7_uploads_missing_images_one_by_one(monkeypatch, tmp_path):
    """手順 7: 用意できなかった図ごとにアップロードを求め、正しい名前で入れて ZIP とレポートを作り直す。"""
    import types
    import zipfile
    shown = fake_display(monkeypatch)
    res = _template_result(tmp_path)
    uploads = [{}, {"なんでもよい名前.png": _png()}]       # 1 回目はキャンセル（飛ばす）、2 回目は画像を選ぶ
    files = types.SimpleNamespace(upload=lambda: uploads.pop(0))
    ns = {"DONE": {1, 2, 3, 4, 5}, "res": res, "files": files, "USER_IMAGES": {}}
    src = cell_source("#@title 7.")
    exec(src, ns)                                   # キャンセル: 何も入れずに、まだ足りないことを赤い枠で示す
    assert ns["USER_IMAGES"] == {} and "画像ファイルを用意できなかった図が 1 件" in shown[-1]
    exec(src, ns)
    assert list(ns["USER_IMAGES"]) == ["31_1_fig01.png"] and ns["DONE"] == {1, 2, 3, 4, 5, 7}
    assert shown[-1]["filename"].endswith("Graphics/31_1_fig01.png")      # 入れた画像を表示して確かめられる
    assert "jasme/31/1/31_1/Graphics/31_1_fig01.png" in zipfile.ZipFile(res.zip_path).namelist()
    assert "要対応: 画像ファイル" not in res.report_path.read_text(encoding="utf-8")
    exec(src, ns)                                   # 足りない画像がなければ何もしない
    assert uploads == []


def test_step8_stops_once_when_images_are_missing(monkeypatch, tmp_path):
    """手順 8: 用意できなかった画像が残っていれば、ダウンロードの前に一度止めて手順 7 を案内する。"""
    import shutil
    import types
    fake_display(monkeypatch)
    res = _template_result(tmp_path)
    downloaded = []
    ns = {"DONE": {1, 2, 3, 4, 5}, "res": res, "files": types.SimpleNamespace(download=downloaded.append),
          "shutil": shutil, "Path": Path, "WORK": tmp_path, "OUT": tmp_path / "output", "docx_path": Path("a.docx")}
    src = cell_source("#@title 8.")
    with pytest.raises(SystemExit, match="手順 7 で画像をアップロード"):
        exec(src, ns)
    assert downloaded == []
    exec(src, ns)                                   # もう一度押すと、画像なしでダウンロードする
    assert len(downloaded) == 1 and ns["DONE"] == {1, 2, 3, 4, 5, 8}


def test_step8_stops_once_when_action_is_needed(monkeypatch, tmp_path):
    """手順 8: 画像のほかの要対応（J-STAGE のアップロード時チェックの問題など）が残っていても、ダウンロードの前に一度止めて
    赤い枠で示す。もう一度押すとダウンロードする（修正計画 D）。"""
    import shutil
    import types

    from conftest import FULL

    from jasme_jats.config import ArticleMeta, JournalConfig
    from jasme_jats.pipeline import Options, convert
    shown = fake_display(monkeypatch)
    meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "peer_review": "あり",
                                  "received": "2026-01-10", "accepted": "2025-11-20"})
    res = convert(FULL, meta, JournalConfig.load(), Options(out_dir=tmp_path / "output", convert_metafiles=False))
    assert res.jstage_issues
    downloaded = []
    ns = {"DONE": {1, 2, 3, 4, 5}, "res": res, "files": types.SimpleNamespace(download=downloaded.append),
          "shutil": shutil, "Path": Path, "WORK": tmp_path, "OUT": tmp_path / "output", "docx_path": Path("a.docx")}
    src = cell_source("#@title 8.")
    with pytest.raises(SystemExit, match="要対応が 1 件あります"):
        exec(src, ns)
    assert downloaded == [] and "J-STAGE のアップロード時チェックで問題が 1 件あります" in shown[-1]
    exec(src, ns)                                   # もう一度押すと、そのままダウンロードする
    assert len(downloaded) == 1 and ns["DONE"] == {1, 2, 3, 4, 5, 8}
    assert "EMSGM106E" in shown[-1]                 # ダウンロードの後にも、残っている要対応の枠を出す
    # 同じ docx を書誌情報を直して変換し直し、別の要対応（開始ページがない EMSGM230E）が残ったときは、もう一度止める
    meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "peer_review": "あり"})
    ns["res"] = res = convert(FULL, meta, JournalConfig.load(), Options(out_dir=tmp_path / "output", convert_metafiles=False))
    assert "EMSGM230E" in [mid for mid, _ in res.jstage_issues] and "EMSGM106E" not in [mid for mid, _ in res.jstage_issues]
    ns["DONE"] = {1, 2, 3, 4, 5}
    with pytest.raises(SystemExit, match="要対応が 1 件あります"):
        exec(src, ns)
    assert len(downloaded) == 1 and "EMSGM230E" in shown[-1]
    exec(src, ns)
    assert len(downloaded) == 2


def test_step8_does_not_stop_without_action(monkeypatch, tmp_path):
    """手順 8: 要対応がなければ止めずにダウンロードする（要確認だけなら止めない）。"""
    import shutil
    import types

    from conftest import FULL

    from jasme_jats.config import ArticleMeta, JournalConfig
    from jasme_jats.pipeline import Options, convert
    fake_display(monkeypatch)
    meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "peer_review": "あり"})
    res = convert(FULL, meta, JournalConfig.load(), Options(out_dir=tmp_path / "output", convert_metafiles=False))
    assert not res.needs_action
    downloaded = []
    ns = {"DONE": {1, 2, 3, 4, 5}, "res": res, "files": types.SimpleNamespace(download=downloaded.append),
          "shutil": shutil, "Path": Path, "WORK": tmp_path, "OUT": tmp_path / "output", "docx_path": Path("a.docx")}
    exec(cell_source("#@title 8."), ns)
    assert len(downloaded) == 1


def test_step8_does_not_stop_with_only_checks(monkeypatch, tmp_path):
    """手順 8: 要確認（ルート1 の出版版 PDF との違い）だけなら止めずにダウンロードし、ダウンロードの後に赤い枠を出す
    （止めるのは level が要対応のものだけ）。"""
    import shutil
    import types

    from conftest import PDFCHECK, PDFCHECK_PDF

    from jasme_jats.config import ArticleMeta, JournalConfig
    from jasme_jats.pipeline import Options, convert
    from jasme_jats.report import TO_CHECK, actions
    pytest.importorskip("pypdfium2")
    shown = fake_display(monkeypatch)
    meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "peer_review": "あり"})
    res = convert(PDFCHECK, meta, JournalConfig.load(), Options(out_dir=tmp_path / "output", pdf_path=PDFCHECK_PDF,
                                                                route="docx", convert_metafiles=False))
    assert [a.key for a in actions(res)] == ["pdf_diff"] and {a.level for a in actions(res)} == {TO_CHECK}
    assert not res.needs_action
    downloaded = []
    ns = {"DONE": {1, 2, 3, 4, 5}, "res": res, "files": types.SimpleNamespace(download=downloaded.append),
          "shutil": shutil, "Path": Path, "WORK": tmp_path, "OUT": tmp_path / "output", "docx_path": Path("a.docx")}
    exec(cell_source("#@title 8."), ns)
    assert len(downloaded) == 1 and ns["DONE"] == {1, 2, 3, 4, 5, 8}
    assert "出版版 PDF と文字が違う箇所" in shown[-1]


def test_step2_route_defaults_to_published_pdf():
    """作り方の初期値は「docx から作り、出版版 PDF で補う」。PDF がないときは「docx から作る」を案内する。"""
    src = cell_source("#@title 2.")
    assert 'ROUTE = "docx から作り、出版版 PDF で補う"  #@param ["docx から作り、出版版 PDF で補う", "docx から作る"]' in src
    ns = {"DONE": {1}, "ROUTE": "docx から作り、出版版 PDF で補う", "UPLOAD_PDF": False}
    body = src.split("from google.colab import files\n", 1)[1].split("WORK = ", 1)[0]
    with pytest.raises(SystemExit, match="「docx から作る」"):
        exec(body, ns)


def test_steps5_and_6_show_result_boxes():
    """要対応・要確認の枠（XML に入らなかった画像など）は、手順 5 と手順 6（AI の回答で再変換）で、report.actions から
    まとめて出す（colab.result_boxes。個別の枠の表示を並べない。修正計画 D）。その後に結果の要約（summary_box）、
    レポート全文（report_details。畳んで出す）の順。要約の行を print で並べない。"""
    for prefix in ("#@title 5.", "AI_RESPONSE = r'''"):
        src = cell_source(prefix)
        assert "display(HTML(result_boxes(res" in src
        assert (src.index("result_boxes(res") < src.index("display(HTML(summary_box(res)))")
                < src.index("display(HTML(report_details(res.report_path"))
        assert "Markdown(" not in src and 'print("文字の不変性チェック' not in src
        for old in ("missing_images_box", "lost_images_box", "figure_body_box", "pdf_diff_box", "unplaced_box",
                    "error_box("):
            assert old not in src
    assert "result_boxes" in cell_source("#@title 5.").split("api_key = None")[0]   # 手順 5 で import する
    # 手順 5 の手動モードでは、依頼文の枠を出すので「AI の回答をまだ反映していません」の枠は出さない
    assert 'result_boxes(res, skip=("ai_pending",))' in cell_source("#@title 5.")


def test_step6_shows_ai_error_box_before_report(monkeypatch, tmp_path):
    """手順 6 のセルを実行すると、読めない回答を貼り付けたときは「貼り付けた回答を読み込めませんでした」の赤い枠を、
    レポートの表示より前に出す（result_boxes の呼び出しと、変換の後の流れを、文字列ではなく実行して確かめる）。"""
    from conftest import FULL

    from jasme_jats.colab import report_details, result_boxes, summary_box
    from jasme_jats.config import ArticleMeta, JournalConfig
    from jasme_jats.pipeline import Options, add_images, convert
    shown = fake_display(monkeypatch)
    src = cell_source("AI_RESPONSE = r'''").replace("ここに AI の回答を貼り付ける", "提案はありません（JSON ではない回答）", 1)
    ns = {"DONE": {1, 2, 3, 4, 5}, "AI": "manual", "docx_path": FULL, "pdf_path": None, "ROUTE_KEY": "docx",
          "SPLIT_LABELS": None, "OUT": tmp_path / "output", "journal": JournalConfig.load(),
          "meta": ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "peer_review": "あり"}),
          "convert": convert, "Options": Options, "add_images": add_images, "result_boxes": result_boxes,
          "summary_box": summary_box, "report_details": report_details, "HTML": lambda x: x, "display": shown.append}
    exec(src, ns)
    assert ns["res"].ai.mode == "manual" and ns["res"].ai.error and ns["LAST_AI_RESPONSE"]
    box = next(i for i, x in enumerate(shown) if "貼り付けた回答を読み込めませんでした" in x)
    summary = next(i for i, x in enumerate(shown) if "結果の要約" in x)
    report = next(i for i, x in enumerate(shown) if "<details" in x and "変換レポート" in x)
    assert box < summary < report and "#dc2626" in shown[box]


def test_step8_shows_result_boxes():
    """手順 8（ダウンロード）でも、ダウンロードの後に要対応・要確認の枠を出す（手順 5・6 の枠を読み飛ばしたとき用）。"""
    src = cell_source("#@title 8.")
    assert "from jasme_jats.colab import result_boxes" in src
    assert src.index("files.download(archive)") < src.index("display(HTML(result_boxes(res)))")
    assert "（PDF の文字を読めたとき）PDF で補った docx" in src


def test_step3_reads_full_width_numbers_and_common_dates(capsys):
    """手順 3: 全角の数字は半角にして、その旨を表示する。英数字以外の巻・読めない日付は、欄の名前を示して止める。"""
    from jasme_jats.config import JournalConfig
    src = cell_source("#@title 3.")
    assert "2026-03-31 の形で（2026/3/31 でもかまいません）" in src

    def run(**values):
        s = src.replace('peer_review = "（選んでください）"  #@param', 'peer_review = "査読あり"  #@param')
        for name, v in values.items():
            s = s.replace(f'{name} = ""  #@param', f'{name} = "{v}"  #@param', 1)
        ns = {"DONE": {1, 2}, "docx_path": Path("a.docx")}
        exec(s, ns)
        return ns
    ns = run(volume="３１", first_page="１", pub_date="2026/3/31")
    out = capsys.readouterr().out
    assert "※ 巻「３１」を「31」として読みました（全角の文字を半角にしました）" in out
    assert ns["_meta"].article_id(JournalConfig.load()) == "31_1" and str(ns["_meta"].pub_date) == "2026-03-31"
    with pytest.raises(SystemExit, match="入力を確認してください: 巻「31巻」に、使えない文字「巻」"):
        run(volume="31巻")
    with pytest.raises(SystemExit, match="入力を確認してください: 受付日「2026/13/1」を読めません"):
        run(received="2026/13/1")


def test_failed_step_drops_later_steps(monkeypatch, tmp_path):
    """途中で止まった手順の後では、後ろの手順の「済み」が残らない（unmark）。手順 2（PDF を選ばずに止まる）・手順 3（受付日の誤り）・
    手順 6（変換が例外で止まる）で確かめる。"""
    import sys
    import types

    from conftest import FULL

    from jasme_jats.colab import report_details, result_boxes, structure_conflict_box, summary_box
    from jasme_jats.config import ArticleMeta, JournalConfig
    from jasme_jats.pipeline import Options, StructureConflictError, add_images, convert
    uploads = []
    files = types.SimpleNamespace(upload=lambda: uploads.pop(0), download=lambda p: None)
    colab = types.ModuleType("google.colab")
    colab.files = files
    google = types.ModuleType("google")
    google.colab = colab
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.colab", colab)
    work = f"Path({str(tmp_path)!r})"
    # 手順 2: docx は選んだが、PDF を選ばずに止まる
    src2 = cell_source("#@title 2.").replace('Path("/content/jasme_work")', work)
    ns = {"DONE": {1, 2, 3, 4, 5}}
    uploads[:] = [{"B.docx": b"PK"}, {}]
    with pytest.raises(SystemExit):
        exec(src2, ns)
    assert ns["DONE"] == {1}
    with pytest.raises(SystemExit, match="先に手順"):
        exec(mk.guard(1, 2, 3, 4, 5), dict(ns))
    # 手順 3: 受付日が誤り
    src3 = cell_source("#@title 3.").replace('peer_review = "（選んでください）"  #@param', 'peer_review = "査読あり"  #@param')
    src3 = src3.replace('received = ""  #@param', 'received = "あした"  #@param', 1)
    ns3 = {"DONE": {1, 2, 3, 4, 5}, "docx_path": Path("a.docx")}
    with pytest.raises(SystemExit):
        exec(src3, ns3)
    assert ns3["DONE"] == {1, 2}
    # 手順 6: 変換が例外で止まる / 成功する
    shown = fake_display(monkeypatch)
    src6 = cell_source("AI_RESPONSE = r'''").replace("ここに AI の回答を貼り付ける", "提案はありません（JSON ではない回答）", 1)

    def boom(*args, **kwargs):
        raise RuntimeError("途中で止まる")
    base = {"AI": "manual", "docx_path": FULL, "pdf_path": None, "ROUTE_KEY": "docx", "SPLIT_LABELS": None,
            "OUT": tmp_path / "output", "journal": JournalConfig.load(),
            "meta": ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "peer_review": "あり"}),
            "convert": convert, "Options": Options, "add_images": add_images, "result_boxes": result_boxes,
            "summary_box": summary_box, "report_details": report_details, "HTML": lambda x: x, "display": shown.append,
            "StructureConflictError": StructureConflictError, "structure_conflict_box": structure_conflict_box}
    ns6 = dict(base, DONE={1, 2, 3, 4, 5, 7, 8}, convert=boom)
    with pytest.raises(RuntimeError):
        exec(src6, ns6)
    assert 5 not in ns6["DONE"] and ns6["DONE"] == {1, 2, 3, 4}
    ns6 = dict(base, DONE={1, 2, 3, 4, 5, 7, 8})
    exec(src6, ns6)
    assert ns6["DONE"] == {1, 2, 3, 4, 5}


def test_steps5_and_6_stop_on_structure_conflict(monkeypatch, tmp_path):
    """原稿の構造の衝突（K1・K2）で変換が中止されたとき、手順 5 は赤い枠（structure_conflict_box）を出して SystemExit で止まり、
    手順 6（守り）も同じ。どちらも `DONE` から 5 を消すので、手順 7〜8 は先に進めない。セル 5・6 に error_box( は書かない。"""
    from test_structure import conflict_doc

    from jasme_jats.colab import (ai_required_box, no_ai_box, prompt_box, report_details, result_boxes, structure_conflict_box,
                                  summary_box)
    from jasme_jats.config import ArticleMeta, JournalConfig
    from jasme_jats.pipeline import AIRequiredError, Options, StructureConflictError, add_images, convert
    for prefix in ("#@title 5.", "AI_RESPONSE = r'''"):
        src = cell_source(prefix)
        assert "except StructureConflictError as e:" in src and "display(HTML(structure_conflict_box(str(e))))" in src
        assert "上の赤い枠のとおり Word で原稿を直して保存し、手順 2 から選び直してやり直してください。" in src
        assert "error_box(" not in src
    shown = fake_display(monkeypatch)
    path = conflict_doc(tmp_path, "K1_ref_ref")
    base = {"AI": "manual", "PROVIDER": "claude", "API_MODEL": "x", "CONVERT_EMF": False, "WORK": tmp_path, "OUT": tmp_path / "output",
            "meta_input": {"volume": "31", "issue": "1", "fpage": "1", "peer_review": "あり"}, "docx_path": path, "pdf_path": None,
            "ROUTE_KEY": "docx", "SPLIT_LABELS": None, "journal": JournalConfig.load(),
            "meta": ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "peer_review": "あり"}),
            "convert": convert, "Options": Options, "add_images": add_images, "result_boxes": result_boxes,
            "summary_box": summary_box, "report_details": report_details, "prompt_box": prompt_box, "no_ai_box": no_ai_box,
            "ai_required_box": ai_required_box, "AIRequiredError": AIRequiredError,
            "StructureConflictError": StructureConflictError, "structure_conflict_box": structure_conflict_box,
            "HTML": lambda x: x, "display": shown.append}
    ns5 = dict(base, DONE={1, 2, 3, 4})
    with pytest.raises(SystemExit, match="上の赤い枠のとおり Word で原稿を直して保存し"):
        exec(cell_source("#@title 5."), ns5)
    assert 5 not in ns5["DONE"] and ns5["DONE"] == {1, 2, 3, 4}
    box = next(x for x in shown if "原稿の構造を直す必要があります（変換を中止しました）" in x)
    assert "#dc2626" in box and "手順 2 から" in box and "\x00" not in box
    ns6 = dict(base, DONE={1, 2, 3, 4, 5, 7, 8})
    with pytest.raises(SystemExit, match="手順 2 から選び直して"):
        exec(cell_source("AI_RESPONSE = r'''").replace("ここに AI の回答を貼り付ける", "{}", 1), ns6)
    assert 5 not in ns6["DONE"] and ns6["DONE"] == {1, 2, 3, 4}
