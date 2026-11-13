"""表の縦結合（vMerge）・飛ばしたグリッド（gridBefore・gridAfter）・gridSpan の不正な値と、出力した表の形の確かめ
（pipeline.table_problems・要対応 table_shape。修正計画 2026-11 の単位 u3-tables）。

docx は make_fixtures の部品で作る（内容は架空）。"""
import json
from pathlib import Path

import make_fixtures as mf
import pytest
from conftest import META_EXAMPLE
from lxml import etree

from jasme_jats import pipeline
from jasme_jats.builder import BuildInfo, Builder
from jasme_jats.cli import main as cli_main
from jasme_jats.docx_reader import read_docx
from jasme_jats.model import Cell, Row, Table
from jasme_jats.pipeline import Options, convert, table_problems
from jasme_jats.report import actions

EMPTY_ANSWER = json.dumps({"placements": [], "operations": [], "notes": []})
HEAD_STOP = "見出し行の終わりで止めました"
SPAN_WARN = "縦に結合したセルの幅"


def load(res):
    return etree.fromstring(res.xml_path.read_bytes().split(b"\n", 2)[2])


def c(text, span=1, v=None):
    return mf.cell(text, span=span, vmerge={"r": "restart", "c": "continue"}.get(v, v))


def _text(el):
    """セルの文字（段落の区切りの break は改行にする）。"""
    out = el.text or ""
    for ch in el:
        out += "\n" if ch.tag == "break" else _text(ch)
        out += ch.tail or ""
    return out


def _cell_str(td):
    s = _text(td)
    if td.get("rowspan"):
        s += "/r" + td.get("rowspan")
    if td.get("colspan"):
        s += "/c" + td.get("colspan")
    return s


def _grid(tbl):
    """出力の <table> を {"thead": [[セル, …], …], "tbody": […]} にする。セルは「文字/r<rowspan>/c<colspan>」。"""
    return {sec.tag: [[_cell_str(td) for td in tr] for tr in sec.findall("tr")] for sec in tbl}


def _convert(tmp_path, journal, meta, rows=None, header_rows=0, raw_rows=None, ncol=None):
    """表キャプション「表1　…」と表 1 つの小さな論文を変換し、4 つの確かめと表の形の確かめを通ることを確かめる。"""
    def parts(b):
        tbl = mf.table_of_rows(raw_rows, ncol) if raw_rows is not None else mf.table(rows, header_rows=header_rows)
        return [mf.para(mf.S["sec1"], "１．表の検証"), mf.para(mf.S["body"], "試験（2024）にならう。"),
                mf.para(mf.S["tab_cap"], "表1　検証用の表"), tbl, mf.para(mf.S["body"], "以上で終わる。")]
    path = tmp_path / "table.docx"
    mf.make_article(path, "表の検証用文書", parts)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid, (res.fidelity.missing, res.dtd_errors[:3])
    assert res.table_problems == [], [p.problems for p in res.table_problems]
    assert res.tables_checked >= 1
    tbl = load(res).find(".//table-wrap/table")
    return res, tbl


def _rows_of(tbl):
    return tbl.findall(".//tr")


# ---------------------------------------------------------------------------- 1. すべて継続の行
BOTH = [[c("A", v="r"), c("B", v="r")], [c("", v="c"), c("", v="c")], [c("C"), c("D")]]
COL1 = [[c("A", v="r"), c("B", v="r")], [c("", v="c"), c("", v="c")], [c("", v="c"), c("D")]]
CONT_TEXT = [[c("A", v="r"), c("B", v="r")], [c("A2", v="c"), c("B2", v="c")], [c("C"), c("D")]]


@pytest.mark.parametrize("name, rows, expect, dropped", [
    ("both_cont", BOTH, [["A", "B"], ["C", "D"]], 1),
    ("col1_all_col2_row2", COL1, [["A/r2", "B"], ["D"]], 1),
    ("cont_text", CONT_TEXT, [["A\nA2", "B\nB2"], ["C", "D"]], 1),
], ids=lambda x: x if isinstance(x, str) else "")
def test_rows_all_continued_are_not_output_and_rowspan_counts_output_rows(journal, meta, tmp_path, name, rows, expect, dropped):
    """すべてのセルが縦結合の継続の行は出力せず、rowspan は出力する行だけで数える（0.29.0 は rowspan が元の行数のまま残った）。
    継続の行の文字は結合元のセルに続けて出す。review-repros の merge の場合（both_cont と同じ入力）もここ。"""
    res, tbl = _convert(tmp_path, journal, meta, rows)
    assert _grid(tbl) == {"tbody": expect}
    assert len(_rows_of(tbl)) == len(rows) - dropped
    assert res.warnings == [] or not any(HEAD_STOP in w or SPAN_WARN in w for w in res.warnings)


# ---------------------------------------------------------------------------- 2. 見出し行と本文の行の境目
def test_vmerge_stops_at_head_body_boundary(journal, meta, tmp_path):
    rows = [[c("H1", v="r"), c("H2")], [c("", v="c"), c("H3")], [c("", v="c"), c("X")], [c("Y"), c("Z")]]
    res, tbl = _convert(tmp_path, journal, meta, rows, header_rows=2)
    assert _grid(tbl) == {"thead": [["H1/r2", "H2"], ["H3"]], "tbody": [["", "X"], ["Y", "Z"]]}
    assert sum(HEAD_STOP in w for w in res.warnings) == 1

    rows = [[c("H1", v="r"), c("H2", v="r")], [c("", v="c"), c("", v="c")], [c("Y"), c("Z")]]
    (tmp_path / "all").mkdir()
    res, tbl = _convert(tmp_path / "all", journal, meta, rows, header_rows=1)
    assert _grid(tbl) == {"thead": [["H1", "H2"]], "tbody": [["", ""], ["Y", "Z"]]}
    assert sum(HEAD_STOP in w for w in res.warnings) == 1

    # 継続側の文字は、本文の 1 行目のセルに出る
    rows = [[c("H1", v="r"), c("H2")], [c("", v="c"), c("H3")], [c("続き", v="c"), c("X")], [c("Y"), c("Z")]]
    (tmp_path / "text").mkdir()
    res, tbl = _convert(tmp_path / "text", journal, meta, rows, header_rows=2)
    assert _grid(tbl)["tbody"] == [["続き", "X"], ["Y", "Z"]]
    assert sum(HEAD_STOP in w for w in res.warnings) == 1

    # 幅の違う継続が境目にあっても、警告なしに結合が切れない
    rows = [[c("H", span=2, v="r"), c("H3")], [c("", v="c"), c("X"), c("Y")], [c("P"), c("Q"), c("R")]]
    (tmp_path / "wide").mkdir()
    res, tbl = _convert(tmp_path / "wide", journal, meta, rows, header_rows=1)
    assert _grid(tbl) == {"thead": [["H/c2", "H3"]], "tbody": [["", "X", "Y"], ["P", "Q", "R"]]}
    assert sum(HEAD_STOP in w for w in res.warnings) == 1
    assert not any(SPAN_WARN in w for w in res.warnings)


# ---------------------------------------------------------------------------- 3. 幅の違う継続
def test_vmerge_with_different_span_is_not_merged(journal, meta, tmp_path):
    rows = [[c("A", span=2, v="r"), c("B")], [c("", v="c"), c("x"), c("y")], [c("C"), c("D"), c("E")]]
    res, tbl = _convert(tmp_path, journal, meta, rows)
    assert _grid(tbl) == {"tbody": [["A/c2", "B"], ["", "x", "y"], ["C", "D", "E"]]}
    assert sum("の 2 行目: " + SPAN_WARN in w for w in res.warnings) == 1

    rows = [[c("A", v="r"), c("B"), c("Bb")], [c("", span=2, v="c"), c("y")], [c("C"), c("D"), c("E")]]
    (tmp_path / "narrow").mkdir()
    res, tbl = _convert(tmp_path / "narrow", journal, meta, rows)
    assert _grid(tbl) == {"tbody": [["A", "B", "Bb"], ["/c2", "y"], ["C", "D", "E"]]}
    assert sum("の 2 行目: " + SPAN_WARN in w for w in res.warnings) == 1

    # 変更履歴で削除されて読み飛ばした行が前にあると、警告の行の番号は docx の表の行の番号（読み飛ばした行も数える）
    raw = [mf.deleted_row("a", "b", "c")] + [mf.tr(*r) for r in rows]
    (tmp_path / "skipped").mkdir()
    res, tbl = _convert(tmp_path / "skipped", journal, meta, raw_rows=raw, ncol=3)
    assert _grid(tbl) == {"tbody": [["A", "B", "Bb"], ["/c2", "y"], ["C", "D", "E"]]}
    assert sum("の 3 行目: " + SPAN_WARN in w for w in res.warnings) == 1


# ---------------------------------------------------------------------------- 4. 横に広いセルが結合元の列を覆う
def test_vmerge_is_cut_by_a_wide_cell(journal, meta, tmp_path):
    rows = [[c("X"), c("A", v="r")], [c("C", span=2)], [c("Y"), c("", v="c")]]
    res, tbl = _convert(tmp_path, journal, meta, rows)
    assert _grid(tbl) == {"tbody": [["X", "A"], ["C/c2"], ["Y", ""]]}
    assert not any(SPAN_WARN in w or HEAD_STOP in w for w in res.warnings)


# ---------------------------------------------------------------------------- 5. gridBefore・gridAfter
def test_grid_before_and_after_are_filled(journal, meta, tmp_path):
    R = mf.table_row
    raw = [R(["A", "B", "C"]), R(["D", "E"], grid_before=1), R(["D", "E"], grid_after=1), R(["F"], grid_before=2)]
    res, tbl = _convert(tmp_path, journal, meta, raw_rows=raw, ncol=3)
    assert _grid(tbl) == {"tbody": [["A", "B", "C"], ["", "D", "E"], ["D", "E", ""], ["/c2", "F"]]}

    raw = [R(["H1", "H2"], header=True, grid_before=1), R(["A", "B", "C"])]
    (tmp_path / "head").mkdir()
    res, tbl = _convert(tmp_path / "head", journal, meta, raw_rows=raw, ncol=3)
    assert _grid(tbl) == {"thead": [["", "H1", "H2"]], "tbody": [["A", "B", "C"]]}
    assert tbl.find("thead/tr")[0].tag == "th"

    # 列 1 の継続が gridBefore=1 の行にある: 列 1 の結合元に結び付く
    raw = [R(["A", c("B", v="r"), "C"]), R([c("", v="c"), "Z"], grid_before=1)]
    (tmp_path / "col1").mkdir()
    res, tbl = _convert(tmp_path / "col1", journal, meta, raw_rows=raw, ncol=3)
    assert _grid(tbl) == {"tbody": [["A", "B/r2", "C"], ["", "Z"]]}

    # 列 0・1 がどちらも結合元で、継続が gridBefore=1 の行にある: 列 1 の B に結び付く（列 0 の A ではない）
    raw = [R([c("A", v="r"), c("B", v="r"), "C"]), R([c("", v="c"), "Z"], grid_before=1)]
    (tmp_path / "both").mkdir()
    res, tbl = _convert(tmp_path / "both", journal, meta, raw_rows=raw, ncol=3)
    assert _grid(tbl) == {"tbody": [["A", "B/r2", "C"], ["", "Z"]]}


# ---------------------------------------------------------------------------- 6. 削除された結合元の行
def test_deleted_top_row_continuations_get_a_new_owner(journal, meta, tmp_path):
    top = mf.deleted_row("a", "b").replace("</w:tcPr>", '<w:vMerge w:val="restart"/></w:tcPr>', 1)
    raw = [top, mf.tr(c("Q", v="c"), "X"), mf.tr(c("", v="c"), "Y")]
    res, tbl = _convert(tmp_path, journal, meta, raw_rows=raw, ncol=2)
    assert _grid(tbl) == {"tbody": [["Q/r2", "X"], ["Y"]]}
    assert "Q" in "".join(tbl.itertext())


# ---------------------------------------------------------------------------- 7. 読み取り
def test_reader_reads_grid_skips(journal, meta, tmp_path):
    R = mf.table_row
    bad_before = R(["B1", "B2"]).replace("<w:tr>", '<w:tr><w:trPr><w:gridBefore w:val="x"/></w:trPr>', 1)

    def span(text, val):
        return mf.cell(text).replace("</w:tcPr>", f'<w:gridSpan w:val="{val}"/></w:tcPr>', 1)
    raw = [mf.deleted_row("a", "b", "c"), R(["D", "E"], grid_before=1), R(["F"], grid_after=2), bad_before,
           R([span("S0", "0"), span("S1", "-1"), span("S2", "x")])]

    def parts(b):
        return [mf.para(mf.S["sec1"], "１．表"), mf.para(mf.S["body"], "試験（2024）にならう。"),
                mf.para(mf.S["tab_cap"], "表1　読み取り"), mf.table_of_rows(raw, 3)]
    path = tmp_path / "reader.docx"
    mf.make_article(path, "読み取りの検証用文書", parts)
    doc = read_docx(path)
    t = next(b for b in doc.blocks if isinstance(b, Table) and any(p.plain() == "S0" for p in b.paragraphs()))
    assert [(r.grid_before, r.grid_after, r.number) for r in t.rows] == [(1, 0, 2), (0, 2, 3), (0, 0, 4), (0, 0, 5)]
    assert [x.gridspan for x in t.rows[3].cells] == [1, 1, 1]
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    assert res.fidelity.ok and res.table_problems == []


# ---------------------------------------------------------------------------- 8. table_problems の単体
def _unit(xml, docx_rows, record=True, root_remove=False):
    """xml: <table> の XML。docx_rows: docx の行ごとの [gridspan, …]（None なら t.rows は空）。"""
    root = etree.fromstring(f'<article><body><table-wrap id="T9">{xml}</table-wrap></body></article>')
    tbl = root.find(".//table")
    info = BuildInfo()
    if record:
        rows = [Row(cells=[Cell(gridspan=s) for s in spans]) for spans in docx_rows or []]
        info.tables.append((tbl, Table(tid="t1", rows=rows), "where"))
    if root_remove:
        tbl.getparent().getparent().remove(tbl.getparent())
    return root, info


T = "<table><tbody>{}</tbody></table>"


@pytest.mark.parametrize("name, xml, docx_rows, expect", [
    ("overflow", T.format("<tr><td rowspan='2'/><td/></tr>"), [[1, 1]], "縦の結合（rowspan）が XML の本文の行（tbody）の外にはみ出している"),
    ("overlap", T.format("<tr><td/><td rowspan='2'/></tr><tr><td colspan='2'/></tr>"), [[1, 1], [2]],
     "XML の本文の行（tbody）の 2 行目でセルが重なっている"),
    ("short", T.format("<tr><td/><td/></tr>"), [[1, 1, 1]], "XML の本文の行（tbody）の 1 行目が 2 列ぶん（docx の表は 3 列）"),
    ("cellless", T.format("<tr><td/></tr><tr/>"), [[1], [1]], "XML の本文の行（tbody）の 2 行目にセルがない"),
    ("overflow_second_row", T.format("<tr><td/><td/></tr><tr><td rowspan='2' colspan='1'/><td/></tr>"), [[1, 1], [1, 1]],
     "縦の結合（rowspan）が XML の本文の行（tbody）の外にはみ出している"),
])
def test_table_problems_unit(name, xml, docx_rows, expect):
    root, info = _unit(xml, docx_rows)
    found, checked = table_problems(root, info)
    assert checked == 1
    assert len(found) == 1 and expect in found[0].problems, found
    assert found[0].name == "表 T9" and found[0].tid == "t1" and found[0].where == "where"
    assert len(found[0].problems) == len(set(found[0].problems))


def test_table_problems_unit_no_false_alarm():
    # (e) docx がもともと行ごとに列の数が違う表で、出力も同じ形なら 0 件
    root, info = _unit(T.format("<tr><td/><td/></tr><tr><td/><td/><td/></tr>"), [[1, 1], [1, 1, 1]])
    assert table_problems(root, info) == ([], 1)
    # 縦の結合が行をまたいで覆っていれば、列の数がそろう
    root, info = _unit(T.format("<tr><td rowspan='2'/><td/></tr><tr><td/></tr>"), [[1, 1], [1, 1]])
    assert table_problems(root, info) == ([], 1)
    # (f) t.rows が空の表（変更履歴ですべての行が削除された表）は数えない
    root, info = _unit(T.format("<tr><td/></tr>"), None)
    assert table_problems(root, info) == ([], 0)
    # (h) root から外した <table>（数式の画像にした図の中の表など）は数えない
    root, info = _unit(T.format("<tr><td/></tr>"), [[1]], root_remove=True)
    assert table_problems(root, info) == ([], 0)


def test_table_problems_unit_unrecorded_table():
    """(i) 組み立ての記録がない <table> は、割り当てだけ確かめて「組み立ての記録がない表」として知らせる。"""
    root, info = _unit(T.format("<tr><td/></tr>"), [[1]], record=False)
    found, checked = table_problems(root, info)
    assert checked == 1 and len(found) == 1
    assert found[0].tid == "" and found[0].name == "表 T9" and found[0].problems == ["組み立ての記録がない表"]
    # 図の中の表は「図 F1 の中の表」
    root = etree.fromstring('<article><body><fig id="F1"><table-wrap><table><tbody><tr><td/></tr></tbody></table>'
                            "</table-wrap></fig></body></article>")
    found, _ = table_problems(root, BuildInfo())
    assert found[0].name == "図 F1 の中の表"


def test_table_problems_gridspan_zero_through_convert(journal, meta, tmp_path):
    """(g) 各行の先頭が gridSpan=0 の docx は、読み取りで 1 にそろえるので、形の確かめが誤って鳴らない。"""
    def span0(text):
        return mf.cell(text).replace("</w:tcPr>", '<w:gridSpan w:val="0"/></w:tcPr>', 1)
    raw = [mf.tr(span0("A"), "B"), mf.tr(span0("C"), "D")]
    res, tbl = _convert(tmp_path, journal, meta, raw_rows=raw, ncol=2)
    assert _grid(tbl) == {"tbody": [["A", "B"], ["C", "D"]]}
    # 0 の先頭のセルの右に restart: 結合元の列を取り違えない
    raw = [mf.tr(span0("A"), c("B", v="r")), mf.tr("C", c("", v="c"))]
    (tmp_path / "merge").mkdir()
    res, tbl = _convert(tmp_path / "merge", journal, meta, raw_rows=raw, ncol=2)
    assert _grid(tbl) == {"tbody": [["A", "B/r2"], ["C"]]}


# ---------------------------------------------------------------------------- 9. 要対応 table_shape
@pytest.fixture
def broken_table(monkeypatch):
    """Builder.table が、最初の td に rowspan="9" を付けて表を崩す（変換ツールの不具合の代わり）。"""
    orig = Builder.table

    def table(self, parent, t, caption=None):
        orig(self, parent, t, caption)
        tbl = parent[-1]
        td = tbl.find(".//td")
        td.set("rowspan", "9")
    monkeypatch.setattr(Builder, "table", table)


def test_table_shape_is_needs_action(journal, meta, tmp_path, broken_table, capsys):
    def parts(b):
        return [mf.para(mf.S["sec1"], "１．表"), mf.para(mf.S["body"], "試験（2024）にならう。"),
                mf.para(mf.S["tab_cap"], "表1　検証用の表"), mf.table([[c("A"), c("B")], [c("C"), c("D")]])]
    path = tmp_path / "broken.docx"
    mf.make_article(path, "表の検証用文書", parts)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and res.ok
    keys = [a.key for a in actions(res)]
    assert "table_shape" in keys and res.needs_action
    assert keys[0] == "table_shape"      # 不変性・DTD・補完は合格なので、いちばん前に出る
    assert len(res.table_problems) == 1 and res.table_problems[0].name == "表 T1"
    report = res.report_path.read_text(encoding="utf-8")
    assert "出力した XML の表 1 件の形が崩れています" in report.split("## 2.")[0]
    ch12 = report.split("## 12.")[1].split("## 13.")[0]
    assert "### 表の形の確かめ" in ch12 and "見つかった問題" in ch12 and "縦の結合（rowspan）" in ch12
    assert "表の形が崩れている 1 件" in report.split("## 14.")[1]
    assert cli_main([str(path), "--meta", str(META_EXAMPLE), "--out", str(tmp_path / "cli"),
                     ]) == 1
    err = capsys.readouterr().err
    assert "表" in err and "変換ツールの不具合の可能性" in err and "表 T1" in err


def test_table_shape_not_raised_for_normal_tables(journal, meta, tmp_path):
    res, tbl = _convert(tmp_path, journal, meta, BOTH)
    assert "table_shape" not in [a.key for a in actions(res)]
    report = res.report_path.read_text(encoding="utf-8")
    assert "### 表の形の確かめ" in report and "問題はありませんでした" in report.split("### 表の形の確かめ")[1]
    assert res.tables_checked == 1


# ---------------------------------------------------------------------------- 10. 守りは最後の木を見る
def test_table_problems_use_last_build(journal, meta, tmp_path, monkeypatch):
    def parts(b):
        return [mf.para(mf.S["sec1"], "１．表"), mf.para(mf.S["body"], "試験（2024）にならう。"),
                mf.para(mf.S["tab_cap"], "表1　検証用の表"), mf.table([[c("A"), c("B")], [c("C"), c("D")]])]
    path = tmp_path / "twice.docx"
    mf.make_article(path, "表の検証用文書", parts)
    orig = pipeline.build

    def run(which):
        calls = []

        def wrapped(*a, **k):
            root, info = orig(*a, **k)
            calls.append((root, info))
            return root, info
        monkeypatch.setattr(pipeline, "build", wrapped)
        res = convert(path, meta, journal, Options(out_dir=tmp_path / f"out-{which}", ai_mode="manual",
                                                   ai_response=EMPTY_ANSWER))
        return res, calls
    res, calls = run("plain")
    assert len(calls) == 2 and res.table_problems == []
    last_info = calls[-1][1]
    assert res.tables_checked == sum(1 for _, t, _ in last_info.tables if t.rows) == 1

    for which in ("first", "last"):
        def wrapped(*a, _which=which, **k):
            root, info = orig(*a, **k)
            n = wrapped.n = getattr(wrapped, "n", 0) + 1
            if (_which == "first" and n == 1) or (_which == "last" and n == 2):
                root.find(".//td").set("rowspan", "9")
            return root, info
        monkeypatch.setattr(pipeline, "build", wrapped)
        res = convert(path, meta, journal, Options(out_dir=tmp_path / f"out-{which}", ai_mode="manual",
                                                   ai_response=EMPTY_ANSWER))
        assert len(res.table_problems) == (0 if which == "first" else 1)


# ---------------------------------------------------------------------------- 12. 実際の原稿（tests/private がある環境だけ）
PRIVATE = sorted(p for p in (Path(__file__).resolve().parent / "private").glob("*/*.docx") if p.parent.name != "review-repros")


@pytest.mark.skipif(not PRIVATE, reason="tests/private がない")
def test_private_manuscripts_have_no_table_shape_problems(journal, meta, tmp_path):
    """実際の原稿の表の形が崩れていない（原稿の文字・ファイル名は出さない）。"""
    bad = []
    for k, path in enumerate(PRIVATE):
        res = convert(path, meta, journal, Options(out_dir=tmp_path / str(k), ai_mode="manual"))
        if res.table_problems:
            bad.append(k)
    assert bad == [], f"表の形が崩れた原稿の番号: {bad}"
