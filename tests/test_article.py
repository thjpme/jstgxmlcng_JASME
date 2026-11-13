"""構造の型（article.py）と structure.py の分け方（修正計画の U6 の第 1 段階）。

ノード・ArticlePlan・_para_text は article.py に移し、structure.py からも同じ名前で import できるようにした（tests や
ほかのコードは structure から import している）。循環 import は最初の import で落ちるので、別のプロセスで import して確かめる。
"""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import jasme_jats
from jasme_jats import article, structure

# article.py で定義する名前（structure.py から移したもの。structure からも、同じものを import できること）
MOVED = {"Sec", "PNode", "ListNode", "QuoteNode", "FigNode", "TableNode", "FormulaNode", "BoxNode", "FnNode", "RefNode",
         "BackSec", "AppNode", "Author", "Aff", "FloatInfo", "BoxInfo", "ArticlePlan", "_para_text"}
# 移したのではなく、article.py に新しく足した型（structure からの import は求めない。再エクスポートの対象ではない）
ADDED = {"UnlinkedRef", "StructureConflict", "ImageSlot", "FigureRow"}


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
    assert defined == MOVED | ADDED
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


# ----------------------------------------------------------------------------- Word の自動番号の出力（単位 u3-autonum）
def _numtxt(e):
    return "".join(e.itertext())


def _conv_num(tmp_path, journal, meta, monkeypatch, parts, post=None, opts=None, **kw):
    """自動番号の検証用の小さな論文を変換し、4 つの確かめ・守り（lost_autonums）・jx:gen の出し方を確かめる。
    戻り値: (結果, 最終出力の木, 目印つきの最後の木)。post(path) は docx を作った後に直す関数。"""
    import make_fixtures as mf
    from lxml import etree
    from test_lost_autonums import assert_autonum_gens, convert_tracking
    path = tmp_path / "num.docx"
    mf.make_article(path, "自動番号の検証用文書", parts, **kw)
    if post is not None:
        post(path)
    res, tracked, _ = convert_tracking(monkeypatch, path, journal, meta, tmp_path / "out", **(opts or {}))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    assert res.lost_autonums == []
    assert_autonum_gens(tracked, res.plan)
    return res, etree.fromstring(res.xml_path.read_bytes().split(b"\n", 2)[2]), tracked


def _cells_table():
    import make_fixtures as mf
    S = mf.S
    return mf.table([[mf.cell(mf.list_item(S["body"], "番号付きの質問", num_id=7)), mf.cell("回答")],
                     [mf.cell([mf.list_item(S["body"], "二つ目の質問", num_id=7), mf.list_item(S["body"], "三つ目の質問", num_id=7)]),
                      mf.cell("回答")]])


@pytest.mark.parametrize("where", ["body", "figure", "appendix"])
def test_table_cell_autonum_is_written_as_generated_text(where, journal, meta, tmp_path, monkeypatch):
    """表のセルの自動番号は、段落の先頭に生成した文字で出る（2 段落目以降は <break/> の後ろ）。本文の表・表で組んだ図の表・資料の表。"""
    import make_fixtures as mf
    from jasme_jats.report import actions
    S = mf.S
    kw = {}
    if where == "appendix":
        kw["appendix"] = [mf.para(S["sec1"], "資料　ワークシート"), mf.para(S["tab_cap"], "表2　資料の表"), _cells_table()]

    def parts(b):
        out = [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "本文である。")]
        if where == "body":
            out += [mf.para(S["tab_cap"], "表1　質問の表"), _cells_table()]
        elif where == "figure":
            out += [mf.para(S["fig_cap"], "図1　表で組んだ図"), _cells_table()]
        return out
    res, root, _ = _conv_num(tmp_path, journal, meta, monkeypatch, parts, **kw)
    tds = [td for td in root.iter("td") if _numtxt(td).startswith(("1.", "2."))]
    assert [td.text for td in tds[:1]] == ["1. 番号付きの質問"]
    assert tds[1].text == "2. 二つ目の質問" and tds[1].find("break").tail == "3. 三つ目の質問"
    gens = [t for k, t in res.fidelity.generated if k == "autonum"]
    assert gens[:3] == ["1. ", "2. ", "3. "] or {"1. ", "2. ", "3. "} <= set(gens)
    assert "autonum_lost" not in [a.key for a in actions(res)]
    assert where == "figure" or not res.needs_action        # 画像のない図は、図の本体の要確認になる


def _quote(b):
    import make_fixtures as mf
    return [mf.list_item(mf.S["quote"], "引用の文である。", num_id=7)]


def _tab_cap(b):
    import make_fixtures as mf
    return [mf.list_item(mf.S["tab_cap"], "表1　授業の流れ", num_id=7), mf.table([[mf.cell("甲"), mf.cell("乙")]])]


def _fig_more(b):
    import make_fixtures as mf
    rid = b.add_image("a.png", mf.png_bytes("A"))
    return [mf.para(mf.S["body"], mf.drawing(rid, 1800000, 1100000, 50), jc="center"), mf.para(mf.S["fig_cap"], "図1　架空の図"),
            mf.list_item(mf.S["fig_cap"], "図の出典の続き", num_id=7)]


def _formula(b):
    import make_fixtures as mf
    return [mf.list_item(mf.S["body"], mf.omathpara(mf.mr("S=") + mf.mfrac(mf.mr("1"), mf.mr("2"))), mf.tab(), "(1)", num_id=7),
            mf.para(mf.S["body"], "本文である。")]


def _notes_head(b):
    import make_fixtures as mf
    return [mf.list_item(mf.S["notes_head"], "付記", num_id=7), mf.para(mf.S["body"], "付記の文である。")]


def _ack_head(b):
    import make_fixtures as mf
    return [mf.list_item(mf.S["ack_head"], "謝辞", num_id=7), mf.para(mf.S["body"], "謝辞の文である。")]


def _fn_head(b):
    import make_fixtures as mf
    return [mf.list_item(mf.S["fn_head"], "注", num_id=7), mf.para(mf.S["fn_body"], "1) 注の文である。")]


def _fn_second(b):
    import make_fixtures as mf
    return [mf.para(mf.S["fn_head"], "注"), mf.para(mf.S["fn_body"], "1) 注の一段落目である。"),
            mf.list_item(mf.S["fn_body"], "注の二段落目である。", num_id=6)]


def _word_fn_second(b):
    import make_fixtures as mf
    return [mf.para(mf.S["sec1"], "１．はじめに"), mf.para(mf.S["body"], "本文である。", mf.footnote_ref(5))]


def _ref_head(path):
    from test_lost_autonums import add_num
    add_num(path, ["引用および参考文献"])


def _abs_head(path):
    from test_lost_autonums import add_num
    add_num(path, ["Abstract"])


@pytest.mark.parametrize("case", ["quote", "tab_cap", "fig_more", "formula", "notes_head", "ack_head", "fn_head", "ref_head",
                                  "abs_head", "app_head", "fn_second", "abstract_para", "word_fn_second"])
def test_autonum_in_other_contexts_is_written(case, journal, meta, tmp_path, monkeypatch):
    """表のセル以外で番号が落ちていた場所（引用・表のキャプション・図キャプションの続き・別行数式・後付けと英文要旨の見出し・
    注の 2 段落目以降・英文要旨の段落・Word の脚注の 2 段落目）の自動番号が出る。"""
    import make_fixtures as mf
    S = mf.S
    kw, post = {}, None
    builders = {"quote": _quote, "tab_cap": _tab_cap, "fig_more": _fig_more, "formula": _formula, "notes_head": _notes_head,
                "ack_head": _ack_head, "fn_head": _fn_head, "fn_second": _fn_second, "word_fn_second": _word_fn_second}
    inner = builders.get(case, lambda b: [mf.para(S["body"], "本文である。")])
    if case == "ref_head":
        post = _ref_head
    elif case == "abs_head":
        post = _abs_head
    elif case == "app_head":
        kw["appendix"] = [mf.list_item(S["sec1"], "資料　ワークシート", num_id=7), mf.para(S["body"], "資料の文である。")]
    elif case == "abstract_para":
        kw["appendix"] = [mf.list_item(S["abs"], "A numbered abstract paragraph.", num_id=7)]
    elif case == "word_fn_second":
        kw["footnotes"] = [mf.footnote(5, "脚注の一段落目。", mf.list_item("a8", "脚注の二段落目。", num_id=7))]

    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに")] + inner(b) if case != "word_fn_second" else inner(b)
    res, root, _ = _conv_num(tmp_path, journal, meta, monkeypatch, parts, post=post, **kw)
    if case == "quote":
        assert _numtxt(root.find(".//disp-quote/p")) == "1. 引用の文である。"
    elif case == "tab_cap":
        tw = root.find(".//table-wrap")
        assert _numtxt(tw.find("label")) == "1." and _numtxt(tw.find("caption/p")) == "表1　授業の流れ"
    elif case == "fig_more":
        assert [_numtxt(p) for p in root.findall(".//fig/caption/p")] == ["図1　架空の図", "1. 図の出典の続き"]
    elif case == "formula":
        assert _numtxt(root.find(".//disp-formula")).startswith("1. ")
    elif case == "notes_head":
        assert _numtxt(root.find(".//notes/title")) == "1. 付記"
    elif case == "ack_head":
        assert _numtxt(root.find(".//ack/title")) == "1. 謝辞"
    elif case == "fn_head":
        assert _numtxt(root.find(".//fn-group/title")) == "1. 注"
    elif case == "ref_head":
        assert _numtxt(root.find(".//ref-list/title")).startswith("1. 引用および参考文献")
    elif case == "abs_head":
        assert _numtxt(root.find(".//trans-abstract/title")) == "1. Abstract"
    elif case == "app_head":
        assert _numtxt(root.find(".//app/title")) == "1. 資料　ワークシート"
    elif case == "fn_second":
        assert [_numtxt(p) for p in root.find(".//fn-group/fn").findall("p")][1] == "• 注の二段落目である。"
    elif case == "abstract_para":
        assert _numtxt(root.findall(".//trans-abstract/p")[-1]) == "1. A numbered abstract paragraph."
    else:
        assert [_numtxt(p) for p in root.find(".//fn-group/fn").findall("p")][1].startswith("1. 脚注の二段落目")


@pytest.mark.parametrize("split", [True, False])
def test_caption_autonum_label(split, journal, meta, tmp_path, monkeypatch):
    """キャプションに自動番号があれば、split_labels にかかわらず番号を <label> に出し、キャプションの文字は分けない。"""
    import make_fixtures as mf
    res, root, _ = _conv_num(tmp_path, journal, meta, monkeypatch,
                             lambda b: [mf.para(mf.S["body"], "本文である。")] + _tab_cap(b),
                             opts={"split_labels": split})
    tw = root.find(".//table-wrap")
    assert [c.tag for c in tw][:2] == ["label", "caption"]
    assert _numtxt(tw.find("label")) == "1." and _numtxt(tw.find("caption/p")) == "表1　授業の流れ"
    assert tw.find("caption/label") is None


@pytest.mark.parametrize("split", [True, False], ids=["split-name", "unsplit-name"])
def test_title_author_aff_autonum_is_not_written_and_warned(split, journal, meta, tmp_path, monkeypatch):
    """題目・副題・著者名・所属の自動番号は XML に出さず、10 章の警告にする。守りは報告しない（要対応にしない）。
    著者名は、姓と名に分けられるものと、空白がなく分けられないもの。所属は和英両方がある（aff-alternatives）。"""
    import make_fixtures as mf
    from lxml import etree
    from test_lost_autonums import add_num, convert_tracking
    S = mf.S
    ja, en = ("試験\u3000六郎", "Rokuro SHIKEN") if split else ("試験六郎", "SHIKEN")
    b = mf.Builder()
    body = mf.front_ja(b, "番号付き題目", "―番号付き副題―", [("番号付き大学", ja)])
    body += [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "本文である。"), mf.para(S["ref_head"], "引用および参考文献"),
             mf.para(S["ref"], "検査七郎（2024）．「小さな論文」．『架空誌』，第5巻，pp.9-10．")]
    body += mf.front_en(b, "Numbered Title", "Numbered Subtitle", [(en, "Numbered University")], ["Abstract text."])
    body += mf.tail(b)
    path = tmp_path / "unshown.docx"
    b.save(path, body)
    add_num(path, ["番号付き題目", "番号付き副題", ja, "番号付き大学", "Numbered Title", "Numbered Subtitle", en, "Numbered University"])
    res, tracked, info = convert_tracking(monkeypatch, path, journal, meta, tmp_path / "out")
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and res.lost_autonums == []
    root = etree.fromstring(res.xml_path.read_bytes().split(b"\n", 2)[2])
    assert _numtxt(root.find(".//article-title")) == "番号付き題目"
    assert _numtxt(root.find(".//subtitle")) == "―番号付き副題―"
    assert _numtxt(root.find(".//title-group/trans-title-group/trans-title")) == "Numbered Title" \
        and _numtxt(root.find(".//title-group/trans-title-group/trans-subtitle")) == "Numbered Subtitle"
    assert root.find(".//aff-alternatives") is not None
    assert [_numtxt(x) for x in root.iter("institution")] == ["番号付き大学", "Numbered University"]
    ja_name = root.find(".//name[@name-style='eastern']")
    assert _numtxt(ja_name) == ja.replace("\u3000", "") and (ja_name.find("given-names") is not None) == split
    assert not re.search(r"\d\.", "".join(_numtxt(x) for x in (root.find(".//title-group"), root.find(".//contrib-group"))))
    unshown = res.unshown_numbers
    assert sorted(u[2] for u in unshown) == sorted(["題目", "副題", "翻訳題目", "翻訳副題", "著者名", "著者名", "所属", "所属"])
    assert sorted(u[0] for u in unshown) == sorted(s for s, p in res.plan.paras.items() if p.autonum)
    warn = [w for w in res.warnings if "Word の自動番号があります" in w]
    assert len(warn) == 1 and all(u[0] in warn[0] for u in unshown)
    assert not res.needs_action
    report = res.report_path.read_text(encoding="utf-8")
    assert "（題目・副題・著者名・所属の段落の番号は出していません。10 章）" in report.split("## 8.")[1].split("## 9.")[0]


@pytest.mark.parametrize("spaced", [False, True], ids=["plain", "leading-space"])
def test_word_footnote_first_paragraph_autonum(spaced, journal, meta, tmp_path, monkeypatch):
    """Word の脚注の 1 段落目に自動番号があるときは「1) 1. …」（脚注番号が先。本文が空白で始まっても「1)1. …」にしない）。"""
    import zipfile
    import make_fixtures as mf
    from lxml import etree
    S = mf.S
    W = mf.W
    text = " 先頭が空白の脚注である。" if spaced else "脚注の一段落目である。"

    def post(path):
        tmp = path.with_suffix(".t.docx")
        with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w") as zout:
            for it in zin.infolist():
                data = zin.read(it.filename)
                if it.filename == "word/footnotes.xml":
                    fr = etree.fromstring(data)
                    for fn in fr.iter(f"{{{W}}}footnote"):
                        if fn.get(f"{{{W}}}id") == "5":
                            ppr = fn.find(f"{{{W}}}p").find(f"{{{W}}}pPr")
                            ppr.append(etree.fromstring(f'<w:numPr xmlns:w="{W}"><w:ilvl w:val="0"/><w:numId w:val="7"/></w:numPr>'))
                    data = etree.tostring(fr, xml_declaration=True, encoding="UTF-8", standalone=True)
                zout.writestr(it, data)
        tmp.replace(path)
    res, root, tracked = _conv_num(
        tmp_path, journal, meta, monkeypatch,
        lambda b: [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "本文である。", mf.footnote_ref(5))],
        post=post, footnotes=[mf.footnote(5, text)])
    fn = root.find(".//fn-group/fn")
    assert _numtxt(fn.find("p")) == f"1) 1. {text.strip()}"
    from jasme_jats.tracking import GEN
    pe = tracked.find(".//fn-group/fn/p")
    gens = [(g.get("kind"), g.get("src")) for g in pe.iter(GEN)]
    assert [k for k, _ in gens] == ["footnote-mark", "autonum"] and gens[0][1] is None
    assert gens[1][1].startswith("f") and res.plan.paras[gens[1][1]].autonum.strip() == "1."     # f は Word の脚注の段落


def test_hand_note_first_paragraph_autonum_once(journal, meta, tmp_path, monkeypatch):
    """手で書いた注の 1 段落目の自動番号は、注の番号として 1 回だけ出る（二重に出さない）。"""
    import make_fixtures as mf
    from jasme_jats.tracking import GEN
    S = mf.S
    res, root, tracked = _conv_num(
        tmp_path, journal, meta, monkeypatch,
        lambda b: [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "本文である。"), mf.para(S["fn_head"], "注"),
                   mf.list_item(S["fn_body"], "注の一段落目である。", num_id=7)])
    assert _numtxt(root.find(".//fn-group/fn/p")) == "1. 注の一段落目である。"
    assert [g.get("kind") for g in tracked.find(".//fn-group/fn").iter(GEN)] == ["autonum"]
