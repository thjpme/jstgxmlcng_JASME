"""変換全体: 文字の不変性・DTD 妥当性・リンク・出力ファイル。"""
import zipfile

import pytest
from lxml import etree

from conftest import ALL_DOCS, FULL, TEMPLATE
from jasme_jats.pipeline import Options, convert

XLINK = "http://www.w3.org/1999/xlink"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


@pytest.mark.parametrize("split", [False, True], ids=["strict", "split"])
@pytest.mark.parametrize("path", ALL_DOCS, ids=lambda p: p.name)
def test_fidelity_and_dtd(path, split, journal, meta, tmp_path):
    res = convert(path, meta, journal, Options(out_dir=tmp_path, split_labels=split, convert_metafiles=False))
    fid = res.fidelity
    assert fid.ok, (fid.mismatches, fid.missing, fid.stray[:3])
    assert fid.final_ok, fid.final_detail
    assert res.dtd_valid, res.dtd_errors[:5]
    assert res.jstage_issues == [], res.jstage_issues
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
    # 引用文献中の DOI は既定で <uri>（J-STAGE の画面でリンクとして表示される）。文字はそのまま
    ref_uris = {"".join(u.itertext()): u.get(f"{{{XLINK}}}href") for r in root.iter("ref") for u in r.iter("uri")}
    assert ref_uris["https://doi.org/10.1023/A:1012737223465"] == "https://doi.org/10.1023/A:1012737223465"
    assert ref_uris["10.1234/jt.2025.001"] == "https://doi.org/10.1234/jt.2025.001"          # 「doi:10.…」の DOI 部分
    # Word のハイパーリンクが付いた DOI も同じ形
    assert ref_uris["https://doi.org/10.1017/CBO9781139171472"] == "https://doi.org/10.1017/CBO9781139171472"
    assert root.find(".//pub-id") is None
    ext = [e.get(f"{{{XLINK}}}href") for e in root.iter("ext-link")]
    assert "https://example.org/srp-notes" in ext
    # スタイル違反の見出しは機械的に章として推定される
    titles = ["".join(t.itertext()) for t in root.iter("title")]
    assert "２．考察" in titles
    # 書誌情報
    assert root.find(".//article-id").text == "10.24529/jasme.31.1_1"
    # 和文の論文: 題目（日）が article-title、英語の題目が trans-title、英文要旨は trans-abstract
    # （abstract[@xml:lang="en"] にすると J-STAGE で「タイトル(英)がない」エラー EMSGM102E になる）
    assert root.find(".//title-group/article-title").get(XML_LANG) == "ja"
    assert root.find(".//title-group/trans-title-group").get(XML_LANG) == "en"
    assert root.find(".//article-meta/abstract") is None
    assert root.find(".//article-meta/trans-abstract").get(XML_LANG) == "en"
    langs = {r.get("id"): r.get(XML_LANG) for r in root.iter("ref")}
    assert set(langs.values()) == {"ja", "en"}
    assert res.jstage_issues == []


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


def test_float_notes_list_unreferenced_and_uncaptioned(journal):
    from jasme_jats.linker import body_paragraphs
    from jasme_jats.pipeline import _mechanical
    from jasme_jats.report import float_notes
    doc, plan, linker = _mechanical(FULL, journal)
    assert float_notes(plan) == []
    for p, _ in body_paragraphs(plan):          # 図2 への参照を外す
        for a in p.atoms:
            if a.link is not None and a.link.attrs.get("rid") == "F2":
                a.link = None
    plan.tables[0].caption = None
    notes = float_notes(plan)
    assert any(n.startswith("本文中のどこからも参照（リンク）されていない図: F2") for n in notes)
    assert any(n.startswith("キャプションのない表") and "T1" in n for n in notes)


def test_ref_doi_as_pub_id(journal, meta, tmp_path):
    # 設定 ref_doi = "pub-id": 「10.…」の部分を pub-id（リンク先も xlink:href に入れる）
    import dataclasses
    j = dataclasses.replace(journal, ref_doi="pub-id")
    res = convert(FULL, meta, j, Options(out_dir=tmp_path, convert_metafiles=False))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    root = load(res)
    hrefs = {p.text: p.get(f"{{{XLINK}}}href") for p in root.iter("pub-id")}
    assert hrefs["10.1234/jt.2025.001"] == "https://doi.org/10.1234/jt.2025.001"
    assert hrefs["10.1023/A:1012737223465"] == "https://doi.org/10.1023/A:1012737223465"
    assert "10.1017/CBO9781139171472" in hrefs                 # Word のハイパーリンクが付いた DOI
    assert not any("CBO9781139171472" in (u.get(f"{{{XLINK}}}href") or "") for u in root.iter("uri"))


def test_note_notes_detect_unreferenced_and_out_of_order(journal):
    from jasme_jats.linker import apply_span, body_paragraphs
    from jasme_jats.model import LinkSpec
    from jasme_jats.pipeline import _mechanical
    from jasme_jats.report import note_notes
    doc, plan, linker = _mechanical(FULL, journal)
    # 見本の論文では注2 が本文から参照されていない
    assert note_notes(plan) == ["本文中のどこからも参照（リンク）されていない注: fn2（2) 詳細は https://examp）"]
    # 注1 の参照より前に注2 への参照を作る → 本文での初出の順が 注2 → 注1
    p = next(p for p, w in body_paragraphs(plan) if w == "body" and p.plain().strip())
    assert apply_span(p, 0, 1, LinkSpec(kind="xref", attrs={"ref-type": "fn", "rid": "fn2"}))
    assert note_notes(plan) == ["本文で注が番号順に参照されていない（本文での初出の順: 注2 → 注1）"]


@pytest.mark.parametrize("peer_review, approved, expect", [
    ("あり", "", ("approved", "", "")),
    ("査読あり", "2025-11-10", ("approved", "10", "2025")),
    ("なし", "", ("accepted as received", "", "")),
])
def test_peer_review_in_history(journal, tmp_path, peer_review, approved, expect):
    from jasme_jats.config import ArticleMeta
    meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "pub_date": "2026-03-31",
                                  "peer_review": peer_review, "approved": approved})
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    assert res.dtd_valid and res.jstage_issues == []
    root = load(res)
    dates = root.findall(".//article-meta/history/date")
    assert [(d.get("date-type"), d.findtext("day"), d.findtext("year")) for d in dates] == [expect]
    assert not any("査読の有無" in w for w in res.warnings)


def test_peer_review_missing_or_invalid(journal, tmp_path):
    from jasme_jats.config import ArticleMeta
    meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1"})
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    assert any("査読の有無が未入力" in w for w in res.warnings)
    assert load(res).find(".//history") is None
    with pytest.raises(ValueError, match="査読の有無"):
        ArticleMeta.from_dict({"peer_review": "たぶん"})
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        ArticleMeta.from_dict({"approved": "2025/13/40"})
