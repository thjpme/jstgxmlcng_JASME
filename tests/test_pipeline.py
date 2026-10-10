"""変換全体: 文字の不変性・DTD 妥当性・リンク・出力ファイル。"""
import zipfile

import pytest
from lxml import etree

from conftest import ALL_DOCS, FULL, TEMPLATE
from jasme_jats.pipeline import Options, convert

XLINK = "http://www.w3.org/1999/xlink"


@pytest.mark.parametrize("split", [False, True], ids=["strict", "split"])
@pytest.mark.parametrize("path", ALL_DOCS, ids=lambda p: p.name)
def test_fidelity_and_dtd(path, split, journal, meta, tmp_path):
    res = convert(path, meta, journal, Options(out_dir=tmp_path, split_labels=split, convert_metafiles=False))
    fid = res.fidelity
    assert fid.ok, (fid.mismatches, fid.missing, fid.stray[:3])
    assert fid.final_ok, fid.final_detail
    assert res.dtd_valid, res.dtd_errors[:5]
    if not split:
        assert all(reason == "姓と名の間の空白" for _, _, reason in fid.drops)


def load(res):
    return etree.fromstring(res.xml_path.read_bytes().split(b"\n", 2)[2])


def test_links_in_full_sample(journal, meta, tmp_path):
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    root = load(res)
    bibr = [(x.text, x.get("rid")) for x in root.iter("xref") if x.get("ref-type") == "bibr"]
    # 引用は年の部分だけがリンクになる
    assert ("1995", "B3") in bibr and ("2007", "B1") in bibr and ("2019a", "B5") in bibr
    assert all(t and t[:4].isdigit() for t, _ in bibr)
    figs = [(x.text, x.get("rid")) for x in root.iter("xref") if x.get("ref-type") == "fig"]
    assert ("図1", "F1") in figs and ("2", "F2") in figs
    assert ("Figure 1", "F1") in figs
    assert any(x.get("ref-type") == "table" and x.get("rid") == "T1" for x in root.iter("xref"))
    assert any(x.get("ref-type") == "fn" and x.get("rid") == "fn1" for x in root.iter("xref"))
    assert any(x.get("ref-type") == "disp-formula" and x.text == "式(1)" for x in root.iter("xref"))
    uris = [u.get(f"{{{XLINK}}}href") for u in root.iter("uri")]
    assert "https://www.mext.go.jp/" in uris
    dois = [p.text for p in root.iter("pub-id")]
    assert "10.1023/A:1012737223465" in dois and "10.1234/jt.2025.001" in dois
    ext = [e.get(f"{{{XLINK}}}href") for e in root.iter("ext-link")]
    assert "https://example.org/srp-notes" in ext
    # スタイル違反の見出しは機械的に章として推定される
    titles = ["".join(t.itertext()) for t in root.iter("title")]
    assert "２．考察" in titles
    # 書誌情報
    assert root.find(".//article-id").text == "10.24529/jasme.31.1_1"
    assert root.find(".//abstract").get("{http://www.w3.org/XML/1998/namespace}lang") == "en"


def test_package_layout(journal, meta, tmp_path):
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    with zipfile.ZipFile(res.zip_path) as z:
        names = set(z.namelist())
    assert "jasme/31/1/31_1/31_1.xml" in names
    assert {"jasme/31/1/31_1/Graphics/31_1_01.png", "jasme/31/1/31_1/Graphics/31_1_02.png"} <= names
    assert res.report_path.exists()
    text = res.report_path.read_text(encoding="utf-8")
    assert "文字の不変性チェック" in text and "合格" in text


def test_split_labels_moves_numbers_to_label(journal, meta, tmp_path):
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, split_labels=True, convert_metafiles=False))
    root = load(res)
    fig = root.find(".//fig[@id='F1']")
    assert fig.find("label").text == "図1"
    assert "".join(fig.find("caption").itertext()) == "三角形ABCと三角形DEFの合同"
    assert any(r == "番号と本文の間の空白" for _, _, r in res.fidelity.drops)


def test_template_emf_conversion(journal, meta, tmp_path):
    from jasme_jats.images import soffice_path
    res = convert(TEMPLATE, meta, journal, Options(out_dir=tmp_path))
    img = res.images[0]
    if soffice_path():
        assert img.status == "converted"
        assert (tmp_path / "jasme/31/1/31_1/Graphics" / img.name).exists()
    else:
        assert img.status == "failed"
