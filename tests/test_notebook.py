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


def test_step2_route_defaults_to_published_pdf():
    """作り方の初期値は「出版版 PDF に合わせてから作る」。PDF がないときは「docx から作る」を案内する。"""
    src = cell_source("#@title 2.")
    assert 'ROUTE = "出版版 PDF に合わせてから作る"  #@param ["出版版 PDF に合わせてから作る", "docx から作る"]' in src
    ns = {"DONE": {1}, "ROUTE": "出版版 PDF に合わせてから作る", "UPLOAD_PDF": False}
    body = src.split("from google.colab import files\n", 1)[1].split("WORK = ", 1)[0]
    with pytest.raises(SystemExit, match="「docx から作る」"):
        exec(body, ns)


def test_steps5_and_6_show_lost_images_box():
    """XML に入らなかった画像（引用文献の段落の中の画像など）の赤い枠を、手順 5 と手順 6（AI の回答で再変換）で出す。"""
    for prefix in ("#@title 5.", "AI_RESPONSE = r'''"):
        src = cell_source(prefix)
        assert "display(HTML(lost_images_box(res)))" in src
        # 画像の枠は、レポートの表示より前に出す
        assert src.index("lost_images_box(res)") < src.index("display(Markdown(res.report_path")
    assert "lost_images_box" in cell_source("#@title 5.").split("api_key = None")[0]   # 手順 5 で import する


def test_step8_shows_lost_images_box():
    """手順 8（ダウンロード）でも、ダウンロードの後に XML に入らなかった画像の赤い枠を出す（手順 5・6 の枠を読み飛ばしたとき用）。"""
    src = cell_source("#@title 8.")
    assert "from jasme_jats.colab import lost_images_box, missing_images_box" in src
    assert src.index("files.download(archive)") < src.index("display(HTML(lost_images_box(res)))")
