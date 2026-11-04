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


# ----------------------------------------------------------------------------- 後付けの自動番号の段落（点検の F8・F9）
def _tags(p):
    """段落 p の中の要素（label を除く）の並び: ((タグ, 属性の名前)...)。リンクの種類（uri か ext-link か）まで見る。"""
    return [(c.tag, tuple(sorted(k.split("}")[-1] for k in c.attrib))) for c in p.iter() if c is not p and c.tag != "label"]


def test_autonum_items_in_back_sections_are_written_like_plain_paragraphs(journal, meta, tmp_path):
    """F8: 付記・謝辞・資料の自動番号の段落（箇条）の中のリンク（URL・引用文献）は、その節の番号のない段落と同じ書き方になる
    （付記・資料は <ext-link>、謝辞は本文と同じ <uri>。箇条だけ本文の書き方になっていた）。"""
    import make_fixtures as mf
    S = mf.S
    cite = "試験（2024）に https://example.org/%s を見よ。"

    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "本文。"),
                mf.para(S["notes_head"], "付記"), mf.list_item(S["body"], "箇条 " + cite % "n1", num_id=7),
                mf.para(S["body"], "段落 " + cite % "n2"),
                mf.para(S["ack_head"], "謝辞"), mf.list_item(S["body"], "箇条 " + cite % "a1", num_id=7),
                mf.para(S["body"], "段落 " + cite % "a2")]
    appendix = [mf.para(S["abs"], "資料　ワークシート"), mf.list_item(S["body"], "箇条 " + cite % "p1", num_id=7),
                mf.para(S["body"], "段落 " + cite % "p2")]
    res, root = _convert_small(tmp_path, journal, meta, parts, appendix=appendix)
    for sec in ("notes", "ack", "app"):
        el = root.find(f".//{sec}")
        [item] = el.findall(".//list-item/p")
        [plain] = [p for p in el.findall("p") if "".join(p.itertext()).startswith("段落")]
        assert _tags(item), sec
        assert _tags(item) == _tags(plain), sec
    # 付記・資料は ext-link、謝辞は uri（番号のない段落と同じ）
    assert [len(root.find(f".//{s}").findall(".//list-item//ext-link")) for s in ("notes", "ack", "app")] == [1, 0, 1]
    assert [len(root.find(f".//{s}").findall(".//list-item//uri")) for s in ("notes", "ack", "app")] == [0, 1, 0]


def test_heading_with_autonum_in_back_sections_is_not_joined_to_lists(journal, meta, tmp_path):
    """F9: 付記・謝辞・資料の中の、自動番号つきの見出しのスタイル（sec1・sec2）の段落は、前後の同じ番号の箇条の <list> にまとめない
    （本文で見出しは節の見出しで、箇条にならない）。前後の箇条は別の <list> になり、見出しは番号を先頭に補った <p> になる
    （番号は生成した文字。docx の文字は変えない）。"""
    import make_fixtures as mf
    S = mf.S

    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "本文。"),
                mf.para(S["notes_head"], "付記"), mf.list_item(S["body"], "付記の項目一", num_id=7),
                mf.list_item(S["sec2"], "付記の中の見出し", num_id=7), mf.list_item(S["body"], "付記の項目二", num_id=7),
                mf.para(S["ack_head"], "謝辞"), mf.list_item(S["body"], "謝辞の項目一", num_id=7),
                mf.list_item(S["sec1"], "謝辞の中の見出し", num_id=7), mf.list_item(S["body"], "謝辞の項目二", num_id=7)]
    appendix = [mf.para(S["sec1"], "資料　ワークシート"), mf.list_item(S["body"], "資料の項目一", num_id=7),
                mf.list_item(S["sec1"], "資料の中の見出し", num_id=7), mf.list_item(S["body"], "資料の項目二", num_id=7),
                mf.list_item(S["body"], "資料の項目三", num_id=7)]
    res, root = _convert_small(tmp_path, journal, meta, parts, appendix=appendix)

    def txt(e):
        return "".join(e.itertext())
    for sec, head, wrap in (("notes", "付記の中の見出し", False), ("ack", "謝辞の中の見出し", True), ("app", "資料の中の見出し", False)):
        el = root.find(f".//{sec}")
        lists = el.findall("p/list") if wrap else el.findall("list")
        assert len(lists) == 2, sec                                      # 見出しの前と後ろで別の <list>
        assert all(head not in txt(x) for x in lists), sec               # 見出しは箇条の中に入らない
        [h] = [p for p in el.findall("p") if head in txt(p)]
        assert txt(h).endswith(head) and txt(h)[:-len(head)].strip().rstrip(".").isdigit(), (sec, txt(h))
    # 見出しの後ろの箇条は、見出しで切れた新しい <list> から始まる（資料は 2 つの項目が同じ <list>）
    assert [len(x.findall("list-item")) for x in root.find(".//app").findall("list")] == [1, 2]
    assert [len(x.findall("list-item")) for x in root.find(".//notes").findall("list")] == [1, 1]
    # 見出しの数字は生成した文字（jx:gen）で、docx の文字ではない（不変性チェックは合格している）
    assert res.fidelity.ok and res.fidelity.final_ok


# ----------------------------------------------------------------------------- 判断の記録の数え方（点検の F11）
def test_decide_cost_does_not_grow_with_decisions(journal, tmp_path, monkeypatch):
    """F11: 判断の番号を数えるために、判断のたびに判断の一覧を頭から数え直さない（枝番のある大きな論文で 2 乗の時間になった）。
    枝番つきのキャプションの論文に、リンクしない参照の判断を 600 件作らせ、判断の一覧を読んだ回数（要素数）を数える。"""
    import make_fixtures as mf
    from jasme_jats.pipeline import _mechanical
    S = mf.S
    n_paras = 600
    count = [0]

    class Counting(list):
        def __iter__(self):
            for x in super().__iter__():
                count[0] += 1
                yield x

    orig = article.ArticlePlan.__init__

    def init(self, *a, **kw):
        orig(self, *a, **kw)
        self.decisions = Counting(self.decisions)
    monkeypatch.setattr(article.ArticlePlan, "__init__", init)

    def parts(b):
        out = [mf.para(S["sec1"], "１．はじめに")]
        for k in (1, 2):
            rid = b.add_image(f"f11_{k}.png", mf.png_bytes(f"F11 {k}"))
            out += [mf.para(S["body"], mf.drawing(rid, 2880000, 1800000, 970 + k), jc="center"), mf.para(S["fig_cap"], f"図1-{k}　架空の図")]
        out += [mf.para(S["body"], f"段落{i}の本文。図1-2を見る。") for i in range(n_paras)]
        return out
    path = tmp_path / "f11.docx"
    mf.make_article(path, "判断の数え方の検証用文書", parts)
    _, plan, _ = _mechanical(path, journal)
    n = len(plan.decisions)
    assert n >= n_paras
    # 判断の一覧を 1 回ずつ読む程度（件数の定数倍）。判断のたびに数え直すと n*n/2 以上になる
    assert count[0] < 10 * n, (count[0], n)
    # 番号は段階ごとに 1 から連番で、重ならない
    for stage in {d.stage for d in plan.decisions}:
        nums = [int(d.did[2:]) for d in plan.decisions if d.stage == stage]
        assert nums == list(range(1, len(nums) + 1)), stage
