"""構造の型（article.py）と structure.py の分け方（修正計画の U6 の第 1 段階）。

ノード・ArticlePlan・_para_text は article.py に移し、structure.py からも同じ名前で import できるようにした（tests や
ほかのコードは structure から import している）。循環 import は最初の import で落ちるので、別のプロセスで import して確かめる。
"""
import os
import subprocess
import sys
from pathlib import Path

import jasme_jats
from jasme_jats import article, structure

# article.py で定義する名前（structure.py から移したもの。structure からも、同じものを import できること）
MOVED = {"Sec", "PNode", "ListNode", "QuoteNode", "FigNode", "TableNode", "FormulaNode", "BoxNode", "FnNode", "RefNode",
         "BackSec", "AppNode", "Author", "Aff", "FloatInfo", "BoxInfo", "ArticlePlan", "_para_text"}


def run_python(code):
    """新しいプロセスで code を実行する（このテストが import した jasme_jats と同じ場所のものを使う）。"""
    src = str(Path(jasme_jats.__file__).resolve().parent.parent)
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([src, os.environ.get("PYTHONPATH", "")]), PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=120, check=False)


def test_import_in_fresh_process():
    # python -c "import jasme_jats.structure, jasme_jats.pipeline" に当たる（循環 import があれば ImportError で落ちる）
    for code in ("import jasme_jats.structure, jasme_jats.pipeline",
                 "import jasme_jats.pipeline, jasme_jats.structure",
                 "import jasme_jats.article, jasme_jats.linker, jasme_jats.builder, jasme_jats.ai_assist, jasme_jats.report",
                 "import jasme_jats.pdfdocx"):
        r = run_python(code)
        assert r.returncode == 0, (code, r.stderr)


def test_article_does_not_import_structure():
    # article.py は model.py にしか依存しない（structure → article の一方向）
    r = run_python("import sys, jasme_jats.article\n"
                   "bad = sorted(m for m in sys.modules if m.startswith('jasme_jats.')"
                   " and m not in ('jasme_jats.article', 'jasme_jats.model'))\n"
                   "print(','.join(bad))")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == ""


def test_moved_names_are_reexported_from_structure():
    defined = {n for n, v in vars(article).items() if getattr(v, "__module__", None) == "jasme_jats.article"}
    assert defined == MOVED
    for name in MOVED:
        assert getattr(structure, name) is getattr(article, name), name
