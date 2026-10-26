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
    # ノートブックを直したら python tools/make_notebook.py を実行すること
    assert mk.OUT.read_text(encoding="utf-8") == mk.render()


def test_notebook_shows_version_and_cells_compile():
    nb = json.loads(mk.render())
    assert f"ツールの版: {__version__}" in "".join(nb["cells"][0]["source"])
    for c in nb["cells"]:
        if c["cell_type"] == "code":
            compile("".join(c["source"]), "cell", "exec")


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
              USER_IMAGES={"31_1_01.png": ("a.png", b"")})
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
    assert list(ns["USER_IMAGES"]) == ["31_1_01.png"] and ns["DONE"] == {1, 2, 3, 4, 5, 7}
    assert shown[-1]["filename"].endswith("Graphics/31_1_01.png")      # 入れた画像を表示して確かめられる
    assert "jasme/31/1/31_1/Graphics/31_1_01.png" in zipfile.ZipFile(res.zip_path).namelist()
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
    """作り方の初期値は「出版版 PDF に合わせてから作る」。PDF がないときは「docx から作る」を案内する。"""
    src = cell_source("#@title 2.")
    assert 'ROUTE = "出版版 PDF に合わせてから作る"  #@param ["出版版 PDF に合わせてから作る", "docx から作る"]' in src
    ns = {"DONE": {1}, "ROUTE": "出版版 PDF に合わせてから作る", "UPLOAD_PDF": False}
    body = src.split("from google.colab import files\n", 1)[1].split("WORK = ", 1)[0]
    with pytest.raises(SystemExit, match="「docx から作る」"):
        exec(body, ns)


def test_steps5_and_6_show_result_boxes():
    """要対応・要確認の赤い枠（XML に入らなかった画像など）は、手順 5 と手順 6（AI の回答で再変換）で、report.actions から
    まとめて出す（colab.result_boxes。個別の枠の表示を並べない。修正計画 D）。"""
    for prefix in ("#@title 5.", "AI_RESPONSE = r'''"):
        src = cell_source(prefix)
        assert "display(HTML(result_boxes(res" in src
        # 赤い枠は、レポートの表示より前に出す
        assert src.index("result_boxes(res") < src.index("display(Markdown(res.report_path")
        for old in ("missing_images_box", "lost_images_box", "figure_body_box", "pdf_diff_box", "unplaced_box",
                    "error_box("):
            assert old not in src
    assert "result_boxes" in cell_source("#@title 5.").split("api_key = None")[0]   # 手順 5 で import する
    # 手順 5 の手動モードでは、依頼文の枠を出すので「AI の回答をまだ反映していません」の枠は出さない
    assert 'result_boxes(res, skip=("ai_pending",))' in cell_source("#@title 5.")
    # PDF に合わせられなかったときの 1 行（M4）
    assert "elif res.pdf_fallback:" in cell_source("#@title 5.")


def test_step6_shows_ai_error_box_before_report(monkeypatch, tmp_path):
    """手順 6 のセルを実行すると、読めない回答を貼り付けたときは「貼り付けた回答を読み込めませんでした」の赤い枠を、
    レポートの表示より前に出す（result_boxes の呼び出しと、変換の後の流れを、文字列ではなく実行して確かめる）。"""
    from conftest import FULL

    from jasme_jats.colab import result_boxes
    from jasme_jats.config import ArticleMeta, JournalConfig
    from jasme_jats.pipeline import Options, add_images, convert
    from jasme_jats.report import pdf_summary, upload_issues
    shown = fake_display(monkeypatch)
    src = cell_source("AI_RESPONSE = r'''").replace("ここに AI の回答を貼り付ける", "提案はありません（JSON ではない回答）", 1)
    ns = {"DONE": {1, 2, 3, 4, 5}, "AI": "manual", "docx_path": FULL, "pdf_path": None, "ROUTE_KEY": "docx",
          "SPLIT_LABELS": None, "OUT": tmp_path / "output", "journal": JournalConfig.load(),
          "meta": ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "peer_review": "あり"}),
          "convert": convert, "Options": Options, "add_images": add_images, "upload_issues": upload_issues,
          "pdf_summary": pdf_summary, "result_boxes": result_boxes, "HTML": lambda x: x, "display": shown.append,
          "Markdown": lambda x: ("Markdown", x)}
    exec(src, ns)
    assert ns["res"].ai.mode == "manual" and ns["res"].ai.error and ns["LAST_AI_RESPONSE"]
    box = next(i for i, x in enumerate(shown) if isinstance(x, str) and "貼り付けた回答を読み込めませんでした" in x)
    report = next(i for i, x in enumerate(shown) if isinstance(x, tuple) and x[0] == "Markdown")
    assert box < report and "#dc2626" in shown[box]


def test_step8_shows_result_boxes():
    """手順 8（ダウンロード）でも、ダウンロードの後に要対応・要確認の赤い枠を出す（手順 5・6 の枠を読み飛ばしたとき用）。"""
    src = cell_source("#@title 8.")
    assert "from jasme_jats.colab import result_boxes" in src
    assert src.index("files.download(archive)") < src.index("display(HTML(result_boxes(res)))")
    assert "（PDF の文字を読めたとき）PDF に合わせて直した docx" in src


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
