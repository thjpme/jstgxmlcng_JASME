"""図形の外の図の決め方（structure.Classifier.figure_units。修正計画 W1 の 2.3 の A1〜A5、E、D の飾り）。

図キャプション 1 つに画像の置き場所 1 つ（<graphic> 1 つ）。同じ段落・隣に続く画像だけの段落・近くの段落の画像は、その図に含める。
どの図にも含めなかった、文字のある段落に結び付いた浮動の画像は、その段落の後ろのキャプションなしの図にする。飾りの図形は
画像の位置に数えない。"""
import make_fixtures as mf
import pytest
from lxml import etree

from jasme_jats.pipeline import Options, convert

XLINK = "http://www.w3.org/1999/xlink"


def run(tmp_path, variant, meta, journal):
    path = tmp_path / f"{variant}.docx"
    mf.make_figs(path, variant)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    fid = res.fidelity
    assert fid.ok and fid.final_ok and res.dtd_valid and res.lost_images == [], (fid.missing, fid.conflicts)
    return res, etree.fromstring(res.xml_path.read_bytes().split(b"\n", 2)[2]).find("body")


def body_seq(body):
    """本文の要素の並び: 段落は冒頭 8 字、図は「図1:g」「-:g」（キャプションの番号か -、graphic の数だけ g、中の表は t）。"""
    out = []
    for el in body.iter("p", "fig", "title"):
        if el.tag == "fig":
            cap = el.find("caption")
            out.append(("".join(cap.itertext())[:2] if cap is not None else "-") + ":"
                       + "g" * len(el.findall("graphic")) + "t" * len(el.findall(".//table")))
        elif el.tag == "title" and el.getparent().tag == "sec":
            out.append("見:" + "".join(el.itertext())[:6])
        elif el.tag == "p" and el.getparent().tag in ("sec", "body"):
            out.append("".join(el.itertext())[:8])
    return out


def slots(res):
    return [(s.kind, s.how, [i.image_id for i in s.covers]) for s in res.plan.slots]


def test_run_of_image_paragraphs_and_frame_is_one_figure(journal, meta, tmp_path):
    """画像だけの段落 2 つ（間に枠の図形だけの段落）と図キャプション → 図 1 つ・置き場所 1 つ（C033・C028）。
    キャプションなしの図はできず、枠は画像の位置に数えない（XML にも出ない）。"""
    res, body = run(tmp_path, "run_frame", meta, journal)
    assert body_seq(body)[2:] == ["図1:g", "以上で終わる。"]
    assert slots(res) == [("fig", "run", ["img1", "img3"])]
    deco = [i for i in res.plan.paras.values() if any(a.kind == "image" and a.image.decoration for a in i.atoms)]
    assert [i.images for i in deco] == [[]] and deco[0].is_blank
    assert body.find(".//inline-graphic") is None


@pytest.mark.parametrize("variant", ["same_para_before", "same_para_after"])
def test_image_in_caption_paragraph_belongs_to_figure(journal, meta, tmp_path, variant):
    """図キャプションの段落の中の画像（先頭・末尾）は、その図の画像（置き場所 1 つ）。<caption> に <inline-graphic> を書かず、
    キャプションの文字は docx のまま（不変性チェックが合格）。"""
    res, body = run(tmp_path, variant, meta, journal)
    assert slots(res) == [("fig", "same_para", ["img1"])]
    fig = body.find(".//fig")
    assert fig.find(".//inline-graphic") is None and len(fig.findall("graphic")) == 1
    assert "".join(fig.find("caption").itertext()) == "図1　キャプションの段落の中の画像"
    assert any("段落の中の画像を、その図の画像にした" in d.message for d in res.plan.decisions)


def test_anchored_image_three_elements_before_caption(journal, meta, tmp_path):
    """本文の段落に結び付いた浮動の画像の 3 要素後ろに、画像のない図キャプション → その図に含める（近く。C030）。"""
    res, body = run(tmp_path, "near3", meta, journal)
    assert slots(res) == [("fig", "near", ["img1"])]
    assert body_seq(body)[2:] == ["この段落に浮動の", "これは間にある本", "これは間にある本", "図1:g", "以上で終わる。"]
    assert any("3 要素前の段落「この段落に浮動の画像が結び付いている。」にある画像を、この図の画像にした" in d.message
               for d in res.plan.decisions)


def test_anchored_image_four_elements_before_caption(journal, meta, tmp_path):
    """4 要素後ろの図キャプションには含めない: 図 1 つ（画像なし）と、段落の後ろのキャプションなしの図 1 つ。"""
    res, body = run(tmp_path, "near4", meta, journal)
    assert slots(res) == [("nocap", "", ["img1"]), ("fig", "", [])]
    assert body_seq(body)[2:4] == ["この段落に浮動の", "-:g"]
    nocap = res.plan.slots[0]
    assert nocap.src == res.plan.slots[0].covers[0].para_src and res.plan.paras[nocap.src].plain().startswith("この段落に")
    p = next(p for p in body.iter("p") if "".join(p.itertext()).startswith("この段落に"))
    assert p.find(".//inline-graphic") is None


def test_other_caption_between_is_not_crossed(journal, meta, tmp_path):
    """間に別の図キャプションがあれば、近くの画像として含めない。"""
    res, body = run(tmp_path, "near_other_caption", meta, journal)
    assert slots(res) == [("nocap", "", ["img1"]), ("fig", "", ["img2"]), ("fig", "", [])]
    assert body_seq(body)[2:6] == ["この段落に浮動の", "-:g", "図1:g", "図2:g"]


def test_caption_above_looks_after_and_skips_its_continuation(journal, meta, tmp_path):
    """図キャプションを図の上に置く原稿では、後ろの要素を見る（キャプションの続きの段落は数えない）。"""
    res, _ = run(tmp_path, "near_above", meta, journal)
    assert slots(res) == [("fig", "", ["img1"]), ("fig", "near", ["img2"])]
    f1 = next(f for f in res.plan.figures if f.number == 1)
    assert [q.plain() for q in f1.caption_more] == ["（出典：架空の資料）"]
    assert any("2 要素後ろの段落「この段落に浮動の画像が結び付いている。」" in d.message for d in res.plan.decisions)


def test_image_anchored_to_heading_goes_after_heading(journal, meta, tmp_path):
    """見出しに結び付いた浮動の画像（近くに図キャプションがない）は、見出しの後ろのキャプションなしの図。<title> に画像を
    書かない。"""
    res, body = run(tmp_path, "heading", meta, journal)
    assert slots(res) == [("nocap", "", ["img1"])]
    seq = body_seq(body)
    assert seq[seq.index("見:（１）浮動の") + 1] == "-:g"
    assert all(t.find(".//inline-graphic") is None for t in body.iter("title"))
    assert any("結び付いた画像を、その段落の後ろのキャプションなしの図にした" in d.message for d in res.plan.decisions)


def test_table_figure_is_kept_and_far_image_stays_nocap(journal, meta, tmp_path):
    """画像だけの段落 → 本文の段落 → キャプションのない表 → 図キャプション: 今と同じく表で組んだ図（置き場所なし）で、
    画像はキャプションなしの図。"""
    res, body = run(tmp_path, "table_first", meta, journal)
    assert body_seq(body)[2:] == ["-:g", "これは間にある本", "図1:t", "以上で終わる。"]
    assert slots(res) == [("nocap", "", ["img1"])]


def test_decoration_only_paragraphs_make_nothing(journal, meta, tmp_path):
    """枠・白い四角の図形だけの段落は、置き場所を作らず、空の <p> も出さない（空白だけの段落と同じ扱い）。"""
    res, body = run(tmp_path, "deco", meta, journal)
    assert res.plan.slots == []
    assert body_seq(body)[2:] == ["これは間にある本", "以上で終わる。"]
    assert all("".join(p.itertext()).strip() for p in body.iter("p"))
    assert sorted(a.image.decoration for p in res.plan.paras.values() for a in p.atoms if a.kind == "image") == ["frame", "mask"]
    # 飾りだけの段落は、空白だけの段落と同じく除外（blank）に記録する（文字は 1 文字もない）
    srcs = [p.src for p in res.plan.paras.values() if any(a.kind == "image" for a in p.atoms)]
    assert {e.src for e in res.plan.exclusions if e.blank} >= set(srcs)


def test_ellipse_and_chart_are_counted(journal, meta, tmp_path):
    """楕円とグラフは飾りでないので、キャプションなしの置き場所になる。"""
    res, _ = run(tmp_path, "ellipse_chart", meta, journal)
    assert [(k, h) for k, h, _ in slots(res)] == [("nocap", ""), ("nocap", "")]
