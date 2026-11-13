"""画像で貼った表・表のセルの図・資料の図（structure.Classifier.assemble_floats・float_units・cell_figures_in・pair_app_figures。
修正計画 W1 の 2.3 の C・D）。

本体の表が見つからない表キャプションで、すぐ後ろが画像だけの段落か、同じ図形に画像があれば、画像で貼った表（<table-wrap> の中の
<caption> と <graphic>。置き場所の名前は tab＋番号）。表のセルの図キャプションは、同じセル・同じ列のすぐ上（上に置く原稿では下）の
セルの画像をその図の画像にする（XML は表のまま。セルの中の <inline-graphic> の名前が図番号になる）。資料の図キャプションは、
本文と同じ規則で隣の画像と組む。"""
import make_fixtures as mf
import pytest
from lxml import etree

from jasme_jats.article import ImageSlot
from jasme_jats.pipeline import NO_DOCX_IMAGE, Options, convert
from jasme_jats.structure import figure_rows, slot_keys

XLINK = "http://www.w3.org/1999/xlink"
HREF = f"{{{XLINK}}}href"


def run(tmp_path, kind, variant, meta, journal):
    path = tmp_path / f"{kind}_{variant}.docx"
    getattr(mf, f"make_{kind}")(path, variant)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    fid = res.fidelity
    assert fid.ok and fid.final_ok and res.dtd_valid and res.lost_images == [], (fid.missing, fid.conflicts)
    return res, etree.fromstring(res.xml_path.read_bytes().split(b"\n", 2)[2])


def stem(name):
    """画像の名前の「{記事識別子}_」の後ろ（幹と拡張子）。"""
    return name.split("_", 2)[2]


def names(root):
    return [stem(g.get(HREF)) for g in root.iter("graphic", "inline-graphic")]


def slots(res):
    return [(s.key, s.kind, s.place, s.how, [i.image_id for i in s.covers]) for s in res.plan.slots]


def test_table_caption_with_next_image_paragraph_is_pasted_table(journal, meta, tmp_path):
    """表キャプションのすぐ後ろが画像だけの段落 → <table-wrap id="T1"> に <caption> と <graphic>（名前 tab01）。<fig> はできず、
    本文の「表1」は T1 にリンクされる。"""
    res, root = run(tmp_path, "table_images", "tab_next", meta, journal)
    tw = root.find(".//table-wrap")
    assert tw.get("id") == "T1" and [c.tag for c in tw] == ["caption", "graphic"]
    assert stem(tw.find("graphic").get(HREF)) == "tab01.png"
    assert "表1" in "".join(tw.find("caption").itertext())
    assert root.find(".//fig") is None and root.find(".//inline-graphic") is None
    assert slots(res) == [("tab01", "table", "table", "next", ["img1"])]
    node = res.plan.tables[0]
    assert node.table is None and node.slot is res.plan.slots[0] and res.plan.slot_of["img1"] is node.slot
    assert node.slot.caption is node.caption and node.slot.src == node.caption.src
    link = [x for x in root.find("body").iter("xref") if x.get("ref-type") == "table"]
    assert [x.get("rid") for x in link] == ["T1"]
    rows = figure_rows(res.plan)
    assert [(r.fid, r.kind, r.label, r.key) for r in rows] == [("T1", "table", "表1", "tab01")]
    assert any("画像で貼った表" in d.message for d in res.plan.decisions)


def test_images_after_blank_paragraph_make_one_pasted_table(journal, meta, tmp_path):
    """表キャプションの後ろの空の段落は飛ばし、続く画像だけの段落 2 つを 1 つの表の画像にする（<graphic> は 1 つ）。"""
    res, root = run(tmp_path, "table_images", "tab_run", meta, journal)
    assert names(root) == ["tab01.png"]
    assert slots(res) == [("tab01", "table", "table", "run", ["img1", "img2"])]
    assert root.find(".//fig") is None


def test_two_pasted_tables_have_own_names(journal, meta, tmp_path):
    res, root = run(tmp_path, "table_images", "tab_two", meta, journal)
    assert [(t.get("id"), stem(t.find("graphic").get(HREF))) for t in root.iter("table-wrap")] == [
        ("T1", "tab01.png"), ("T2", "tab02.png")]
    assert [s[:3] for s in slots(res)] == [("tab01", "table", "table"), ("tab02", "table", "table")]


def test_image_before_figure_caption_is_not_taken_by_table_caption(journal, meta, tmp_path):
    """表キャプション・画像・図キャプションの並び（キャプションは図の下）: 画像は図キャプションの図のもの。表は本体も画像もない。"""
    res, root = run(tmp_path, "table_images", "tab_then_fig", meta, journal)
    tw = root.find(".//table-wrap")
    assert tw.find("graphic") is None and tw.find("table") is None
    assert stem(root.find(".//fig/graphic").get(HREF)) == "fig01.png"
    assert slots(res) == [("fig01", "fig", "fig", "", ["img1"])]


def test_image_two_elements_after_table_caption_is_not_taken(journal, meta, tmp_path):
    """表キャプションのすぐ後ろでない画像（間に本文の段落）は、表のものにしない（キャプションなしの図のまま）。"""
    res, root = run(tmp_path, "table_images", "tab_not_next", meta, journal)
    assert root.find(".//table-wrap/graphic") is None
    assert [s[1] for s in slots(res)] == ["nocap"]


@pytest.mark.parametrize("variant", ["tab_group", "tab_textbox"])
def test_float_with_table_caption_and_image_is_pasted_table(journal, meta, tmp_path, variant):
    """図形（グループ図形の画像・テキストボックスの画像だけの段落）に、本体の表のない表キャプションと画像 → 表の画像。
    図形の図は位置を決められないものにならず（アンカー段落の前に置く）、キャプションなしの図はできない。"""
    res, root = run(tmp_path, "table_images", variant, meta, journal)
    tw = root.find(".//table-wrap")
    assert stem(tw.find("graphic").get(HREF)) == "tab01.png" and root.find(".//fig") is None
    assert slots(res) == [("tab01", "table", "table", "float", ["img1"])]
    info = res.plan.floats["s1"]
    assert info.mode == "mechanical" and info.nodes == [res.plan.tables[0]] and res.plan.unplaced_floats == []
    assert [r.place for r in figure_rows(res.plan)] == ["mechanical"]
    if variant == "tab_textbox":
        # 図の画像に写るとみなして、キャプションでない文字は除外する
        assert "画像に写る文字" not in "".join(root.itertext())
        assert any("画像に写る文字" in "".join(e.text) for e in res.plan.exclusions)


@pytest.mark.parametrize("variant,expect", [
    ("cell_up", [("fig01", "fig", "inline", "cell", ["img1"]), ("fig02", "fig", "inline", "cell", ["img2"])]),
    ("cell_same", [("fig01", "fig", "inline", "cell", ["img1"])]),
])
def test_figure_caption_in_table_cell_takes_the_cell_image(journal, meta, tmp_path, variant, expect):
    """表のセルの図キャプションは、同じセル・同じ列のすぐ上のセルの画像を、その図の画像にする（キャプションのスタイルでも、
    スタイルのない「図2：…」の形でも）。XML は表のまま（<fig> はできない）で、セルの中の <inline-graphic> の名前が図番号になる。"""
    res, root = run(tmp_path, "table_images", variant, meta, journal)
    assert slots(res) == expect
    assert root.find(".//fig") is None and root.find(".//table-wrap/graphic") is None
    assert names(root) == [f"{s[0]}.png" for s in expect]
    assert all(g.getparent().tag == "td" for g in root.iter("inline-graphic"))
    rows = figure_rows(res.plan)
    assert [(r.kind, r.label, r.key) for r in rows if r.kind == "fig"] == [("fig", f"図{k}", s[0]) for k, s in enumerate(expect, 1)]
    assert all(r.fid == "" and r.node is None for r in rows if r.kind == "fig")


def test_figure_caption_in_cell_without_image_above_keeps_other_image_nocap(journal, meta, tmp_path):
    """キャプションの上のセルに画像がなければ、別の列の画像を取らない（画像はキャプションなしの置き場所のまま）。図キャプションには
    画像の見つからない図の置き場所（covers が空）を作り、キャプションの段落の先頭に <inline-graphic>（名前は図番号）を書く。"""
    res, root = run(tmp_path, "table_images", "cell_none", meta, journal)
    assert [s[1:] for s in slots(res)] == [("nocap", "inline", "", ["img1"]), ("fig", "inline", "cell", [])]
    assert names(root)[0].startswith("img") and names(root)[1] == "fig01.png"
    g = list(root.iter("inline-graphic"))[1]
    assert g.getparent().tag == "td" and (g.tail or "").startswith("図1")
    [slot] = [s for s in res.plan.slots if s.kind == "fig"]
    assert slot.label == "図1" and slot.note == "同じセルにも、同じ列の上のセルにも、この図のものと決められる画像がない"
    assert any("画像を docx で見つけられなかった" in d.message for d in res.plan.decisions)


def test_two_captions_in_one_cell_are_left_alone(journal, meta, tmp_path):
    """1 つのセルに図キャプションが 2 つ以上あるときは、組み合わせを決められないので画像はキャプションなしのまま。図キャプションには
    それぞれ画像の見つからない図の置き場所を作る。"""
    res, root = run(tmp_path, "table_images", "cell_two", meta, journal)
    assert [(s[0], s[1], s[4]) for s in slots(res)] == [
        (slots(res)[0][0], "nocap", ["img1"]), ("fig01", "fig", []), (slots(res)[2][0], "nocap", ["img2"]), ("fig02", "fig", [])]


def test_floating_image_on_cell_caption_yields_to_image_above(journal, meta, tmp_path):
    """data17 の形: 表のセルの図キャプションの段落に結び付いた浮動の画像だけがあり、同じ列の上のセルにキャプションのない画像が
    あるときは、上のセルの画像をその図の画像にする（図1）。キャプションに結び付いた画像は、どの図のものか決められないので
    キャプションなしの置き場所のまま（次の図2 に取らせない）。上のセルが空の図2 は、画像の見つからない図の置き場所。図3 は
    上のセルの画像。どの図も置き場所を持ち、同じ画像を 2 つの図に組まない。"""
    res, root = run(tmp_path, "table_images", "cell_float", meta, journal)
    got = slots(res)
    assert [(s[0], s[1], s[3], s[4]) for s in got] == [
        ("fig01", "fig", "cell", ["img1"]), (got[1][0], "nocap", "", ["img2"]), ("fig02", "fig", "cell", []),
        ("fig03", "fig", "cell", ["img3"])]
    assert names(root) == ["fig01.png", f"{got[1][0]}.png", "fig02.png", "fig03.png"]
    assert all(g.getparent().tag == "td" for g in root.iter("inline-graphic")) and root.find(".//fig") is None
    fig1 = res.plan.slots[0]
    assert "どの図のものか決められない" in fig1.note
    from jasme_jats.report import images_to_prepare
    why = {name.split("_", 2)[2]: w for name, _, w in images_to_prepare(res)}
    fig2 = res.plan.slots[2]
    assert fig2.note == ("同じセルにも、同じ列の上のセルにも、この図のものと決められる画像がない。図1 のキャプションの段落に結び付いた、"
                         "キャプションのない画像がこの図の画像かもしれない。そうなら、その画像をこの図の名前で入れ、キャプションなしの置き場所は外す")
    assert why["fig02.png"] == f"{NO_DOCX_IMAGE}（{fig2.note}）" and why["fig02.png"].count("（") == 2   # 理由の中のかっこは 1 段だけ
    rows = figure_rows(res.plan)
    assert [(r.kind, r.label, r.key) for r in rows if r.kind == "fig"] == [
        ("fig", "図1", "fig01"), ("fig", "図2", "fig02"), ("fig", "図3", "fig03")]


def test_cell_figure_looks_down_when_captions_are_above_figures(journal, meta, tmp_path):
    """図キャプションを図の上に置く原稿（本文の図9 の後ろに画像）では、表のセルの図キャプションは同じ列のすぐ下のセルの画像を取る。"""
    res, root = run(tmp_path, "table_images", "cell_above", meta, journal)
    assert slots(res) == [("fig09", "fig", "fig", "", ["img1"]), ("fig01", "fig", "inline", "cell", ["img2"])]
    assert names(root) == ["fig09.png", "fig01.png"]


def test_table_slot_keys():
    """画像で貼った表の幹: tab＋番号 2 桁、読めない番号は tabx＋順、同じ番号は _2。図の幹とは別に数える。"""
    from jasme_jats.structure import classify  # noqa: F401  (幹の規則だけを確かめる: ImageSlot を直接作る)
    from jasme_jats.model import Para

    def cap(src, text):
        from jasme_jats.model import Atom
        return Para(src=src, atoms=[Atom(kind="text", text=text)])

    mk = [ImageSlot(key="", kind="table", caption=cap("d1", "表1　a")), ImageSlot(key="", kind="table", caption=cap("d2", "表1　b")),
          ImageSlot(key="", kind="table", caption=cap("d3", "表2-3　c")), ImageSlot(key="", kind="table", caption=cap("d4", "あ")),
          ImageSlot(key="", kind="fig", caption=cap("d5", "図1　d")), ImageSlot(key="", kind="fig", caption=cap("d6", "え"))]
    order = {f"d{k}": k for k in range(1, 7)}
    assert slot_keys(mk, order, {}) == ["tab01", "tab01_2", "tab02-3", "tabx01", "fig01", "figx01"]


@pytest.mark.parametrize("variant,figs", [
    ("below", ["図1"]), ("after", ["図1"]), ("own", ["図1"]), ("run", ["図1"]), ("plain", ["図1"]), ("two", ["図1", "図2"])])
def test_figure_caption_in_appendix_is_paired_with_adjacent_image(journal, meta, tmp_path, variant, figs):
    """資料の図キャプションは、隣の画像だけの段落（前・後ろ・続く複数）か段落の中の画像と組んで <fig>（<caption> と <graphic>）にする。
    スタイルのない「図1　…」も、隣が画像なら図キャプションと推定する。"""
    res, root = run(tmp_path, "app_figures", variant, meta, journal)
    app = root.find(".//app")
    got = [(f.get("id"), "".join(f.find("caption").itertext())[:2], stem(f.find("graphic").get(HREF))) for f in app.iter("fig")]
    assert got == [(f"F{k}", figs[k - 1], f"fig0{k}.png") for k in range(1, len(figs) + 1)]
    assert app.find("graphic") is None and root.find(".//inline-graphic") is None
    assert all(s[1:3] == ("fig", "fig") for s in slots(res))
    assert len(slots(res)) == len(figs)


def test_figure_caption_in_appendix_without_image_stays_paragraph(journal, meta, tmp_path):
    """画像が隣にない資料の図キャプションは、これまでどおり段落のまま（図にしない・置き場所を作らない）。"""
    res, root = run(tmp_path, "app_figures", "none", meta, journal)
    assert root.find(".//app//fig") is None and slots(res) == []
    assert "図1　資料の図" in [("".join(p.itertext())) for p in root.find(".//app").iter("p")]
