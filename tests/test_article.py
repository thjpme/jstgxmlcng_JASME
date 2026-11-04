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


# ----------------------------------------------------------------------------- 表の見出し行・後付けの要素（点検の A4・A5・A7）
def _convert_small(tmp_path, journal, meta, parts, **kw):
    import make_fixtures as mf
    from lxml import etree
    from jasme_jats.pipeline import Options, convert
    path = tmp_path / "small.docx"
    mf.make_article(path, "後付けの検証用文書", parts, **kw)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    return res, etree.fromstring(res.xml_path.read_bytes().split(b"\n", 2)[2])


def test_all_header_rows_table_has_no_thead(journal, meta, tmp_path):
    # すべての行が見出し行（Word の「タイトル行の繰り返し」を付けた表）の表は、<thead> だけにせず <tbody> にする
    import make_fixtures as mf
    S = mf.S

    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["tab_cap"], "表1　見出しだけの表"),
                mf.table([[mf.cell("区分"), mf.cell("人数")]], header_rows=1),
                mf.para(S["body"], "以上である。"),
                mf.table([[mf.cell("区分"), mf.cell("人数")], [mf.cell("一組"), mf.cell("三十人")]], header_rows=2),
                mf.para(S["body"], "以上である。")]
    res, root = _convert_small(tmp_path, journal, meta, parts)
    tables = list(root.iter("table"))
    assert len(tables) >= 1
    for t in tables:
        assert t.find("thead") is None and t.find("tbody") is not None


def _back_parts(b):
    import make_fixtures as mf
    S = mf.S
    formula = mf.para(S["body"], mf.omathpara(mf.mr("S=") + mf.mfrac(mf.mr("1"), mf.mr("2")) + mf.mr("ah")), mf.tab(), "(1)",
                      jc="center")
    return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "本文である。"),
            mf.para(S["notes_head"], "付記"), mf.para(S["body"], "付記の文。"), formula,
            mf.list_item(S["body"], "付記の番号付き 1", num_id=7), mf.list_item(S["body"], "付記の番号付き 2", num_id=7),
            mf.para(S["ack_head"], "謝辞"), mf.para(S["body"], "謝辞の文。"), formula,
            mf.table([[mf.cell("区分"), mf.cell("人数")], [mf.cell("一組"), mf.cell("三十人")]], header_rows=1),
            mf.list_item(S["body"], "謝辞の番号付き 1", num_id=7), mf.list_item(S["body"], "謝辞の番号付き 2", num_id=7)]


def test_ack_notes_app_display_elements_and_autonum(journal, meta, tmp_path):
    import make_fixtures as mf
    S = mf.S
    appendix = [mf.para(S["abs"], "資料　ワークシート"), mf.para(S["body"], "資料の文。"),
                mf.list_item(S["body"], "資料の番号付き 1", num_id=7), mf.list_item(S["body"], "資料の番号付き 2", num_id=7),
                mf.list_item(S["body"], "資料の箇条", num_id=6)]
    res, root = _convert_small(tmp_path, journal, meta, _back_parts, appendix=appendix)

    def txt(e):
        return "".join(e.itertext())
    # <ack> の直下は <p> だけ（別行数式・表・リストは <p> の中）
    ack = root.find(".//ack")
    assert {c.tag for c in ack} <= {"title", "p"}
    assert ack.find("p/disp-formula") is not None and ack.find("p/table-wrap") is not None
    assert [txt(x) for x in ack.findall("p/list/list-item/label")] == ["3.", "4."]
    assert [txt(x) for x in ack.findall("p/list/list-item/p")] == ["謝辞の番号付き 1", "謝辞の番号付き 2"]
    # <notes> と <app> も Word の自動番号を <label> に出す
    notes = root.find(".//notes")
    assert [txt(x) for x in notes.findall("list/list-item/label")] == ["1.", "2."]
    app = root.find(".//app")
    lists = app.findall("list")
    assert [x.get("list-type") for x in lists] == ["order", "bullet"]
    assert [txt(x) for x in lists[0].findall("list-item/label")] == ["5.", "6."]
    assert [txt(x) for x in lists[1].findall("list-item/p")] == ["資料の箇条"]
