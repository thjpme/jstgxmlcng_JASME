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


def test_step8_resets_for_next_article(monkeypatch):
    """手順 8: ダウンロード前なら一度止めて確かめ、もう一度押すと、前の論文を記録して手順 2 からやり直せる状態にする。"""
    import sys
    import types
    shown = []
    ipy = types.ModuleType("IPython.display")       # Colab の画面表示の代わり
    ipy.HTML, ipy.display = (lambda x: x), shown.append
    monkeypatch.setitem(sys.modules, "IPython", types.ModuleType("IPython"))
    monkeypatch.setitem(sys.modules, "IPython.display", ipy)
    cell = next(c for c in json.loads(mk.render())["cells"] if "".join(c["source"]).startswith("#@title 8."))
    src = "".join(cell["source"])
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
    # ダウンロード済み（手順 7 を実行済み）なら、1 回で進む
    ns.update(DONE={1, 2, 3, 4, 5, 7}, docx_path=Path("second.docx"), meta_input={"volume": "31", "fpage": "13"})
    exec(src, ns)
    assert ns["DONE"] == {1} and ns["PREVIOUS"]["docx"] == "second.docx"
