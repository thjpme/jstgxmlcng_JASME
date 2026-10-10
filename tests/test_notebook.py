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
