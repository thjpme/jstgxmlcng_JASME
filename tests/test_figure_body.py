"""図の本体の組み方: 表のセルに画像とキャプションが並ぶ図形（AI なしでも図に組む）と、画像のない図キャプションの隣の
キャプションのない表（図の中の表として組む。修正計画の決定事項 22）。"""
import make_fixtures as mf
import pytest
from conftest import CELLS, EDGE, TABLEFIG
from lxml import etree

from jasme_jats.cli import main as cli_main
from jasme_jats.pipeline import AIRequiredError, Options, convert

XLINK = "http://www.w3.org/1999/xlink"


def load(res):
    return etree.fromstring(res.xml_path.read_bytes().split(b"\n", 2)[2])


def sequence(root):
    """本文の要素の並び（段落は文字の冒頭 10 字、図は「図1」などキャプションの番号、図の外の表は「表:」と最初のセルの文字）。"""
    out = []
    for el in root.find("body").iter("p", "fig", "table-wrap"):
        if el.tag == "fig":
            out.append("".join(el.find("caption").itertext())[:2] if el.find("caption") is not None else "図?")
        elif el.tag == "table-wrap":
            if el.getparent().tag != "fig":
                out.append("表:" + "".join(el.find(".//td").itertext())[:4])
        elif el.getparent().tag in ("sec", "body"):
            out.append("".join(el.itertext())[:10])
    return out


def after(seq, head, n=1):
    i = next(k for k, x in enumerate(seq) if x.startswith(head))
    return seq[i + 1:i + 1 + n]


def figures(root):
    """キャプションの番号 → (graphic の数, 中の table-wrap の数)。"""
    return {"".join(f.find("caption").itertext())[:2]: (len(f.findall("graphic")), len(f.findall("table-wrap")))
            for f in root.iter("fig")}


def checks_pass(res):
    fid = res.fidelity
    assert fid.ok and fid.final_ok and res.dtd_valid and res.jstage_issues == [], (fid.missing, fid.conflicts)
    assert res.lost_images == []


# ---------------------------------------------------------------------------- 表のセルに画像とキャプションが並ぶ図形
def test_cell_figures_without_ai(journal, meta, tmp_path):
    """図形の中の表のセルに画像とキャプションが並ぶもの（セルごと・画像の行とキャプションの行・キャプション 1 つの図）は、
    AI なしでも、セルの画像を本体、セルのキャプションをキャプションにした図に組む（表としては出さない）。"""
    res = convert(CELLS, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    checks_pass(res)
    assert res.plan.unplaced_floats == [] and {i.mode for i in res.plan.floats.values()} == {"mechanical"}
    root = load(res)
    assert root.find("body").find(".//table-wrap") is None
    assert figures(root) == {"図1": (1, 0), "図2": (1, 0), "図3": (2, 0), "図4": (1, 0), "図5": (1, 0)}
    seq = sequence(root)
    assert after(seq, "試験（2024）にな", 3) == ["図1", "図2", "この段落に図1と図2"]     # アンカー段落の前（機械的な配置）
    assert after(seq, "図3は，二つの画像", 2) == ["図3", "この段落に図3のテキ"]
    assert after(seq, "図4と図5は，画像", 3) == ["図4", "図5", "この段落に図4と図5"]
    hrefs = [g.get(f"{{{XLINK}}}href") for g in root.iter("graphic")]
    assert sorted(hrefs) == sorted(i.name for i in res.images) and len(hrefs) == 6
    msgs = [d.message for d in res.plan.decisions]
    assert any("セルにある画像とキャプションを、図「図1\u3000左のセルの図」、「図2\u3000右のセルの図」に組んだ（表としては出力しない）"
               in m for m in msgs)
    cells = {q.src for info in res.plan.floats.values() for t in info.tables for q in t.paragraphs()}
    assert all(reason == "空白のみの段落" for src, reason, _ in res.fidelity.excluded if src in cells)   # 文字は落とさない


@pytest.mark.parametrize("variant, fid", [("text", "s1"), ("tabcap", "s1"), ("cross", "s3"), ("extra", "s3")])
def test_cell_figures_not_unique_stay_a_table(journal, meta, tmp_path, variant, fid):
    """組み方が一つに決まらない表（キャプションでない文字・表キャプションがある、画像とキャプションの組を決められない）は、
    図に組まず、今までどおり（0.21.0 と同じ）キャプションのない表として出す。位置が機械的に決まる図形なら、AI を使わない
    設定でも止まらず、アンカー段落の前に置く。位置を決められない図形なら今までどおり AI に任せ（AI なしでは止まる）、
    AI の回答を反映する前は、表のままアンカー段落の後ろに置く。"""
    anchor = {"s1": "この段落に図1と図2", "s3": "この段落に図4と図5"}[fid]
    path = tmp_path / f"cells_{variant}.docx"
    mf.make_b3_cells(path, variant)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "none", convert_metafiles=False))
    checks_pass(res)
    assert res.plan.unplaced_floats == [] and res.plan.floats[fid].mode == "mechanical"
    seq = sequence(load(res))
    k = next(i for i, x in enumerate(seq) if x.startswith(anchor))
    assert seq[k - 1].startswith("表:")                                  # アンカー段落の前に、表のまま
    assert len(figures(load(res))) == 3                                  # ほかの図形は図に組む
    path = tmp_path / f"cells_{variant}_down.docx"
    mf.make_b3_cells(path, variant + ("+down" if fid == "s1" else "+down3"))
    with pytest.raises(AIRequiredError) as e:
        convert(path, meta, journal, Options(out_dir=tmp_path / "down_none", convert_metafiles=False))
    assert [f.float.fid for f in e.value.floats] == [fid]
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "down_manual", ai_mode="manual", convert_metafiles=False))
    checks_pass(res)
    nxt = after(sequence(load(res)), anchor)[0]
    assert nxt.startswith("表:") and res.plan.floats[fid].where == "anchor"


def cells_doc(tmp_path, name, rows):
    """図の左上がアンカー段落の左上にある（位置が機械的に決まる）図形 1 つの中に、rows の表を入れた原稿。"""
    def parts(b):
        im = [b.add_image(f"{name}_{k}.png", mf.png_bytes(f"{name} {k}", size=(300, 200))) for k in range(3)]

        def pic(k):
            return mf.para(mf.S["body"], mf.drawing(im[k], 1440000, 960000, 861 + k))
        return [mf.para(mf.S["sec1"], "１．表のセルの図"), mf.para(mf.S["body"], "試験（2024）にならう。"),
                mf.para(mf.S["body"], "この段落に図形が結び付いている。", mf.textbox(
                    mf.table(rows(pic)), 860, cx=16 * mf.B3_CM, cy=6 * mf.B3_CM, wrap="wrapTopAndBottom")),
                mf.para(mf.S["body"], "以上で終わる。")]
    path = tmp_path / f"{name}.docx"
    mf.make_article(path, "表のセルの図の検証用文書", parts)
    return path


def cap(text):
    return mf.para(mf.S["fig_cap"], text)


@pytest.mark.parametrize("shape", ["mixed_cell", "vmerge", "sentence"])
def test_cell_figures_guards(journal, meta, tmp_path, shape):
    """組み方が一つに決まらない表は組まない（表のまま。文字は落とさない）: 画像とキャプションが同じセルにあるセルと、画像
    だけ・キャプションだけのセルがまじる表、結合したセルのある表、キャプションでない「図1は…」の文がセルにある表。"""
    rows = {"mixed_cell": lambda pic: [[mf.cell([pic(0), cap("図1\u3000左上の図")]), mf.cell(pic(1))],
                                       [mf.cell(cap("図2\u3000左下のキャプション")), mf.cell(cap("図3\u3000右下のキャプション"))]],
            "vmerge": lambda pic: [[mf.cell(pic(0), vmerge="restart"), mf.cell(pic(1))],
                                   [mf.cell(mf.para(mf.S["body"], ""), vmerge="continue"), mf.cell(cap("図2\u3000右の図"))],
                                   [mf.cell(cap("図1\u3000左の図")), mf.cell("")]],
            "sentence": lambda pic: [[mf.cell([pic(0), mf.para(mf.S["body"], "図1は，左の画像を示す。")]),
                                      mf.cell([pic(1), cap("図2\u3000右のセルの図")])]]}[shape]
    path = cells_doc(tmp_path, shape, rows)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    checks_pass(res)
    root = load(res)
    assert figures(root) == {} and after(sequence(root), "試験（2024）にな", 2)[1] == "この段落に図形が結び"
    assert after(sequence(root), "試験（2024）にな")[0].startswith("表:")     # アンカー段落の前に、表のまま
    cells = "".join("".join(td.itertext()) for td in root.iter("td"))
    assert "図2" in cells and ("図1" in cells)


def test_cell_figures_one_caption_in_a_row(journal, meta, tmp_path):
    """横 1 行に画像 2 つとキャプション 1 つが並ぶ表は、2 つの画像を本体にした図 1 つに組む（図キャプションが表全体で 1 つ）。"""
    path = cells_doc(tmp_path, "row3", lambda pic: [[mf.cell(pic(0)), mf.cell(pic(1)), mf.cell(cap("図1\u3000二つの画像の図"))]])
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    checks_pass(res)
    root = load(res)
    assert figures(root) == {"図1": (2, 0)} and root.find("body").find(".//table-wrap") is None


def test_table_with_caption_but_no_image_stays_a_table(journal, meta, tmp_path):
    """セルに図キャプションと問題文だけがある（画像のない）図形の中の表は、この形ではないので、今までどおり表のまま出す
    （AI を使わない設定でも止まらない）。"""
    def parts(b):
        return [mf.para(mf.S["sec1"], "１．表の中の図キャプション"),
                mf.para(mf.S["body"], "この段落に表のテキストボックスが結び付いている。", mf.textbox(
                    mf.table([[mf.cell("問1\u3000架空の問題")], [mf.cell(mf.para(mf.S["fig_cap"], "図1\u3000表の中のキャプション"))]]),
                    840, cx=10 * 360000, cy=4 * 360000, wrap="wrapTopAndBottom")),
                mf.para(mf.S["body"], "以上で終わる。")]
    path = tmp_path / "caption_in_table.docx"
    mf.make_article(path, "表の中の図キャプションの検証用文書", parts)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    checks_pass(res)
    assert res.plan.unplaced_floats == [] and res.plan.floats["s1"].mode == "mechanical"
    assert sequence(load(res))[:2] == ["表:問1\u3000架", "この段落に表のテキス"]       # アンカー段落の前に、表のまま


def test_cell_figures_of_unplaced_float_and_mixed_paragraph(journal, meta, tmp_path):
    """位置を決められない図形でも、組み方が決まれば組んでアンカー段落の後ろに仮に置く。セルの中で画像と文字が同じ段落は、
    画像を図に入れ、段落の文字は図の直後の段落に出す（修正計画の決定事項 1 と同じ）。"""
    path = tmp_path / "cells_down.docx"
    mf.make_b3_cells(path, "down")
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "down", ai_mode="manual", convert_metafiles=False))
    checks_pass(res)
    assert res.plan.unplaced_floats == ["s1"]
    assert after(sequence(load(res)), "この段落に図1と図2", 2) == ["図1", "図2"]
    path = tmp_path / "cells_mixed.docx"
    mf.make_b3_cells(path, "mixed")
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "mixed", convert_metafiles=False))
    checks_pass(res)
    root = load(res)
    fig = next(f for f in root.iter("fig") if "".join(f.find("caption").itertext()).startswith("図1"))
    assert len(fig.findall("graphic")) == 1 and "説明文" not in "".join(fig.itertext())
    nxt = fig.getnext()
    assert nxt.tag == "p" and "".join(nxt.itertext()) == "説明文：左のセルの画像と同じ段落にある文字。"
    assert nxt.find("inline-graphic") is None
    assert any("画像と文字が同じ段落にある" in d.message for d in res.plan.decisions)


# ---------------------------------------------------------------------------- 画像のない図キャプションと、隣の表
def test_caption_less_table_becomes_figure_body(journal, meta, tmp_path, capsys):
    """画像のない図キャプションの直前の、キャプションのない表は、その図の本体にする（fig の中の table-wrap）。
    表とキャプションの間に段落がある、表に表キャプションが付いている、などで組めないときは、要対応として知らせる。"""
    res = convert(TABLEFIG, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    checks_pass(res)
    root = load(res)
    assert figures(root) == {"図1": (0, 1), "図2": (0, 0), "図3": (0, 0)}
    fig1 = next(f for f in root.iter("fig") if f.get("id") == "F1")
    assert "".join(fig1.find("table-wrap").itertext()).startswith("問1")
    seq = sequence(root)
    assert after(seq, "試験（2024）にな", 2) == ["図1", "図2は，表と図キャプ"]                  # 表は図の中だけ
    assert after(seq, "図2は，表と図キャプ", 3) == ["表:問2\u3000も", "この段落は表と図キャ", "図2"]
    assert [t.tid for t in res.plan.tables] == ["T1", "T2"]                            # 図の中の表には表の ID を付けない
    plan = res.plan
    why = {plan.paras[src].plain()[:2]: w for src, w in plan.figure_issues}
    assert why == {"図2": "図キャプションの前にキャプションのない表があるが、間にほかの段落がある",
                   "図3": "直前の表に表キャプション「表1\u3000表キャプションの付いた表」が付いている"}
    assert any("画像のない図キャプション「図1\u3000表で組んだ問題」の直前にある、キャプションのない表" in d.message
               for d in plan.decisions)
    rows = [u for u in res.unresolved_after if u[0] == "figbody"]
    assert [u[2][:2] for u in rows] == ["図2", "図3"] and all("表を図キャプションのすぐ上" in u[3] for u in rows)
    report = res.report_path.read_text(encoding="utf-8")
    head = report.split("## 2.")[0]
    assert "要対応: 図の本体（画像・表）が見つからない図が 2 件あります（3 章）" in head
    assert "| 図の本体 |" in report.split("## 3.")[1].split("## 4.")[0]
    assert "図の本体が見つからない図 2 件（3 章の「図の本体」）" in report.split("## 14.")[1]
    warned = [w.split(":")[0] for w in res.warnings if "画像が見つからないため <graphic> なしで出力" in w]
    assert warned == ["F2", "F3"]                         # 表を本体にした F1 は、画像のない図の警告を出さない
    # コマンドラインでも知らせる（表の文字は XML に入っているので、終了コードは変えない）
    assert cli_main([str(TABLEFIG), "--out", str(tmp_path / "cli")]) == 0
    err = capsys.readouterr().err
    assert "要対応: 図の本体（画像・表）が見つからない図 2 件" in err and "「図2\u3000間に段落がある問題」" in err


def test_caption_above_figure_takes_following_table(journal, meta, tmp_path):
    """図キャプションを図の上に置く原稿では、画像のない図キャプションの直後の、キャプションのない表を図の本体にする。"""
    path = tmp_path / "tablefig_above.docx"
    mf.make_b3_tablefig(path, "above")
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    checks_pass(res)
    root = load(res)
    assert figures(root) == {"図5": (1, 0), "図4": (0, 1)} and res.plan.figure_issues == []
    assert after(sequence(root), "図4は，図キャプショ", 2) == ["図4", "以上が図4である。"]


def bare_table(text):
    return mf.table([[mf.cell(text)]])


def above_marker(b):
    """図キャプションを図の上に置く原稿にするための、画像の図（キャプションが上）と、その後ろの本文の段落。"""
    img = b.add_image("above_marker.png", mf.png_bytes("Above", size=(300, 200)))
    return [mf.para(mf.S["fig_cap"], "図9\u3000上のキャプションの図"), mf.para(mf.S["body"], mf.drawing(img, 1440000, 960000, 901)),
            mf.para(mf.S["body"], "図9は，キャプションを図の上に置いた。")]


@pytest.mark.parametrize("shape, why", [
    ("below_next", "直後にキャプションのない表があるが、この原稿は図キャプションを図の下に置いているため、図の本体にしなかった"),
    ("below_gap2", "図キャプションの前にキャプションのない表があるが、間にほかの段落がある"),
    ("above_gap2", "図キャプションの後ろにキャプションのない表があるが、間にほかの段落がある"),
    ("below_tabcap_gap", "直前の表に表キャプション「表1\u3000架空の表」が付いている"),
    ("above_prev", "直前にキャプションのない表があるが、この原稿は図キャプションを図の上に置いているため、図の本体にしなかった"),
    ("above_tabcap", "直後の表の次に表キャプションがあり、どちらの表か決められない"),
    ("above_gap", "図キャプションの後ろにキャプションのない表があるが、間にほかの段落がある"),
])
def test_table_near_caption_that_cannot_be_the_body(journal, meta, tmp_path, shape, why):
    """近くに表があるのに図の本体にできない形は、理由を付けて要対応にする（表はそのまま表として出す）。"""
    cap = mf.para(mf.S["fig_cap"], "図1\u3000本体の見つからない図")
    text = mf.para(mf.S["body"], "この段落は図キャプションと表の間にある。")

    def parts(b):
        text2 = mf.para(mf.S["body"], "この段落も図キャプションと表の間にある。")
        body = {"below_next": [cap, bare_table("問1\u3000架空の問題")],
                "below_gap2": [bare_table("問1\u3000架空の問題"), text, text2, cap],
                "above_gap2": above_marker(b) + [cap, text, text2, bare_table("問1\u3000架空の問題")],
                "below_tabcap_gap": [mf.para(mf.S["tab_cap"], "表1\u3000架空の表"), text, bare_table("問1\u3000架空の問題"),
                                     cap],
                "above_prev": above_marker(b) + [bare_table("問1\u3000架空の問題"), cap, text],
                "above_tabcap": above_marker(b) + [cap, bare_table("問1\u3000架空の問題"),
                                                   mf.para(mf.S["tab_cap"], "表1\u3000架空の表")],
                "above_gap": above_marker(b) + [cap, text, bare_table("問1\u3000架空の問題")]}[shape]
        return [mf.para(mf.S["sec1"], "１．表と図キャプション"), mf.para(mf.S["body"], "試験（2024）にならう。"), *body,
                mf.para(mf.S["body"], "以上で終わる。")]
    path = tmp_path / f"{shape}.docx"
    mf.make_article(path, "表と図キャプションの検証用文書", parts)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    checks_pass(res)
    assert [w for _, w in res.plan.figure_issues] == [why]
    assert figures(load(res))["図1"] == (0, 0) and any(t.table is not None for t in res.plan.tables)


@pytest.mark.parametrize("shape", ["below_tabcap_after", "above_tabcap_gap", "above_tabcap_first"])
def test_table_with_its_own_caption_is_not_a_candidate(journal, meta, tmp_path, shape):
    """表キャプションの付いた表（表の下に表キャプションを置く書き方、上に置く書き方）は、画像のない図キャプションの近くに
    あっても図の本体の候補にしない（要対応にもしない）。表は表キャプションの表として出す。"""
    cap = mf.para(mf.S["fig_cap"], "図1\u3000本体の見つからない図")
    tab, tabcap = bare_table("問1\u3000架空の問題"), mf.para(mf.S["tab_cap"], "表1\u3000架空の表")

    def parts(b):
        body = {"below_tabcap_after": [cap, tab, tabcap],
                "above_tabcap_gap": above_marker(b) + [cap, mf.para(mf.S["body"], "この段落は図キャプションと表の間にある。"),
                                                       tab, tabcap],
                "above_tabcap_first": above_marker(b) + [cap, tabcap, tab]}[shape]
        return [mf.para(mf.S["sec1"], "１．表キャプションの付いた表"), mf.para(mf.S["body"], "試験（2024）にならう。"), *body,
                mf.para(mf.S["body"], "以上で終わる。")]
    path = tmp_path / f"{shape}.docx"
    mf.make_article(path, "表キャプションの付いた表の検証用文書", parts)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    checks_pass(res)
    assert res.plan.figure_issues == []
    root = load(res)
    assert figures(root)["図1"] == (0, 0)
    wraps = {"".join(t.find("caption").itertext())[:2]: "".join(t.find(".//td").itertext())[:2]
             for t in root.iter("table-wrap") if t.find("caption") is not None}
    assert wraps == {"表1": "問1"}


def place_parts(b, shape):
    """位置を決められない図形（アンカー段落から 3 cm 下）と、本文の画像のない図キャプション・キャプションのない表。

    float_table: 表 2 つだけの図形（中身をそのまま出す）を、図キャプションの直前の段落に結び付ける（図キャプションは図の下）。
    float_between: 図キャプションを図の上に置く原稿で、図キャプションの段落に画像の図形を結び付け、その下に本文の表を置く。
    float_caption: 図キャプションを図の上に置く原稿で、キャプションだけの図形を結び付けた段落の直後に、本文の表を置く。
    """
    def shape_box(inner, pid):
        return mf.textbox(inner, pid, cx=8 * mf.B3_CM, cy=4 * mf.B3_CM, v=("paragraph", 3 * mf.B3_CM),
                          wrap="wrapTopAndBottom")
    head = [mf.para(mf.S["sec1"], "１．仮に置いた図形"), mf.para(mf.S["body"], "試験（2024）にならう。")]
    if shape == "float_table":
        inner = bare_table("図形の中の表その一") + bare_table("図形の中の表その二")
        return head + [mf.para(mf.S["body"], "この段落に表だけの図形が結び付いている。", shape_box(inner, 820)),
                       mf.para(mf.S["fig_cap"], "図1\u3000画像のない図"), mf.para(mf.S["body"], "以上で終わる。")]
    if shape == "float_between":
        img = b.add_image("place_between.png", mf.png_bytes("Between", size=(300, 200)))
        inner = mf.para(mf.S["body"], mf.drawing(img, 1440000, 960000, 831)) + mf.para(mf.S["fig_cap"], "図2\u3000仮に置く図")
        return head + above_marker(b) + [mf.para(mf.S["fig_cap"], "図1\u3000表の上のキャプション", shape_box(inner, 830)),
                                         bare_table("問1\u3000架空の問題"), mf.para(mf.S["body"], "以上で終わる。")]
    if shape == "prov_tabcap":
        img = b.add_image("place_tabcap.png", mf.png_bytes("Tabcap", size=(300, 200)))
        inner = mf.para(mf.S["tab_cap"], "表1\u3000図形の中の表の見出し") + mf.para(mf.S["body"], mf.drawing(img, 1440000, 960000, 851))
        return head + [mf.para(mf.S["body"], "この段落に図形が結び付いている。", shape_box(inner, 850)),
                       bare_table("問A\u3000本文のキャプションのない表"), mf.para(mf.S["body"], "以上で終わる。")]
    if shape == "prov_tables":
        img = b.add_image("place_tables.png", mf.png_bytes("Tables", size=(300, 200)))
        inner = (mf.para(mf.S["body"], mf.drawing(img, 1440000, 960000, 871)) + bare_table("図形の中の表その一")
                 + bare_table("図形の中の表その二"))
        return head + [mf.para(mf.S["body"], "この段落に図形が結び付いている。", shape_box(inner, 870)),
                       mf.para(mf.S["tab_cap"], "表1\u3000本文の表キャプション"), mf.para(mf.S["body"], "以上で終わる。")]
    if shape == "prov_image":
        body_img = b.add_image("place_body.png", mf.png_bytes("Body", size=(300, 200)))
        img = b.add_image("place_float.png", mf.png_bytes("Float", size=(300, 200)))
        inner = mf.para(mf.S["body"], mf.drawing(img, 1440000, 960000, 881)) + mf.para(mf.S["body"], "\u3000")
        return head + [mf.para(mf.S["body"], mf.drawing(body_img, 1440000, 960000, 882), shape_box(inner, 880)),
                       mf.para(mf.S["fig_cap"], "図1\u3000本文の画像の図"), mf.para(mf.S["body"], "以上で終わる。")]
    inner = mf.para(mf.S["fig_cap"], "図2\u3000キャプションだけの図形")
    return head + above_marker(b) + [mf.para(mf.S["body"], "この段落にキャプションだけの図形が結び付いている。",
                                             shape_box(inner, 840)),
                                     bare_table("問1\u3000架空の問題"), mf.para(mf.S["body"], "以上で終わる。")]


@pytest.mark.parametrize("shape", ["float_table", "float_between", "float_caption"])
def test_provisional_float_is_not_paired_with_outside(journal, meta, tmp_path, shape):
    """位置を決められない図形（アンカー段落の後ろに仮に置いたもの）の中身は、本当はそこにないので、図の本体を探すときに、
    その外の図キャプション・表と組にしない（図形の中の表を本文の図に入れない。図形のキャプションに本文の表を入れない）。
    本文の図キャプションと表は、間に図形の中身を仮に置いていても、docx で隣り合っていれば組にする。"""
    path = tmp_path / f"{shape}.docx"
    mf.make_article(path, "仮に置いた図形の検証用文書", lambda b: place_parts(b, shape))
    # AI が位置を答えなかった（図形は仮の位置のまま。手作業で移す図表の ID が知らせに出る）
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", ai_mode="manual", convert_metafiles=False,
                                               ai_response='{"placements": [], "operations": [], "notes": []}'))
    checks_pass(res)
    assert res.plan.unplaced_floats == ["s1"] and res.plan.figure_issues == []
    root = load(res)
    seq = sequence(root)
    detail = next(u[3] for u in res.unresolved_after if u[0] == "float")
    if shape == "float_table":
        assert figures(root) == {"図1": (0, 0)}
        assert after(seq, "この段落に表だけの図", 3) == ["表:図形の中", "表:図形の中", "図1"]
        assert "にある T1・T2 を正しい位置" in detail             # 本文の図 F1 は、図形の中身ではない
    elif shape == "float_between":
        assert figures(root) == {"図9": (1, 0), "図1": (0, 1), "図2": (1, 0)}
        assert after(seq, "図9は，キャプショ", 3) == ["図1", "図2", "以上で終わる。"]
        assert "にある F3 を正しい位置" in detail
    else:
        assert figures(root) == {"図9": (1, 0), "図2": (0, 0)}
        assert after(seq, "この段落にキャプショ", 3) == ["図2", "表:問1\u3000架", "以上で終わる。"]
        assert "にある F2 を正しい位置" in detail


def floats_in_body(root):
    """本文の図・表の並び: 「ID:キャプションの番号（なければ -）:中身（g は画像、t は表）」。"""
    out = []
    for el in root.find("body").iter("fig", "table-wrap"):
        if el.getparent().tag == "fig":
            continue
        cap = el.find("caption")
        inner = "g" * len(el.findall("graphic")) + "t" * len(el.findall(".//table"))
        out.append(f"{el.get('id')}:{''.join(cap.itertext())[:2] if cap is not None else '-'}:{inner}")
    return out


@pytest.mark.parametrize("shape", ["prov_tabcap", "prov_tables", "prov_image"])
def test_provisional_float_is_not_paired_with_outside_captions(journal, meta, tmp_path, shape):
    """位置を決められない図形（アンカー段落の後ろに仮に置いたもの）の中身は、その外の表・表キャプション・画像・図キャプション
    とも組にしない（図形の表キャプションに本文の表を入れない。本文の表キャプションを図形の表に付けない。本文の図キャプションを
    図形の画像と組にしない）。本文の画像と図キャプションは、間に図形の中身を仮に置いていても、docx で隣り合っていれば組にする。
    手作業で移す図表の知らせには、図形の中身だけを出す。"""
    path = tmp_path / f"{shape}.docx"
    mf.make_article(path, "仮に置いた図形の検証用文書", lambda b: place_parts(b, shape))
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", ai_mode="manual", convert_metafiles=False,
                                               ai_response='{"placements": [], "operations": [], "notes": []}'))
    checks_pass(res)
    assert res.plan.unplaced_floats == ["s1"] and res.plan.floats["s1"].where == "anchor"
    detail = next(u[3] for u in res.unresolved_after if u[0] == "float")
    got = floats_in_body(load(res))
    if shape == "prov_tabcap":
        assert got == ["T1:表1:", "None:-:g", "T2:-:t"]      # 図形の表キャプションだけ・図形の画像・本文の表
        assert "にある T1 を正しい位置" in detail                # 本文の表 T2 は、図形の中身ではない
    elif shape == "prov_tables":
        assert got == ["None:-:g", "T1:-:t", "T2:-:t", "T3:表1:"]  # 本文の表キャプションは図形の表に付けない
        assert "にある T1・T2 を正しい位置" in detail
    else:
        assert got == ["None:-:g", "F1:図1:g"]                  # 図形の画像・本文の画像と本文の図キャプション
        f1 = next(f for f in res.plan.figures if f.fid == "F1")
        assert [q.float_id for q in f1.image_paras] == [""]
        assert "にある図表の中身を正しい位置" in detail and "F1" not in detail


def test_figure_without_image_or_table_nearby_is_unchanged(journal, meta, tmp_path):
    """近くに表の候補がない、画像のない図キャプション（キャプションだけのテキストボックスなど）は、今までどおり判断の一覧に
    記録するだけ（要対応にしない）。"""
    res = convert(EDGE, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    assert res.plan.figure_issues == []
    assert any(d.message == "図キャプションに対応する画像が見つからない（図形・グループ化等の可能性）" for d in res.plan.decisions)
