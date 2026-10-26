"""変換全体: 文字の不変性・DTD 妥当性・リンク・出力ファイル。"""
import os
import zipfile
from pathlib import Path

import pytest
from lxml import etree

import make_fixtures as mf
from conftest import ALL_DOCS, FULL, TEMPLATE
from jasme_jats.builder import build
from jasme_jats.pipeline import Options, _mechanical, convert

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
    assert res.lost_images == [] and res.hidden_images == [], res.lost_images   # 画像の出力漏れがない
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
    # 注の番号は注の本文（p）の先頭に入れる（J-STAGE の注には label を書けない・表示されない）
    fn1 = root.find(".//fn[@id='fn1']")
    assert fn1.find("label") is None and "".join(fn1.find("p").itertext()).startswith("1)")
    assert any(x.get("ref-type") == "disp-formula" and x.text == "式(1)" for x in root.iter("xref"))
    uris = [u.get(f"{{{XLINK}}}href") for u in root.iter("uri")]
    assert "https://www.mext.go.jp/" in uris
    # 引用文献中の DOI は既定で pub-id（「https://doi.org/」の部分は文字のまま）。リンク先も xlink:href に入れる
    hrefs = {p.text: p.get(f"{{{XLINK}}}href") for p in root.iter("pub-id")}
    assert hrefs["10.1234/jt.2025.001"] == "https://doi.org/10.1234/jt.2025.001"           # 「doi:10.…」
    assert hrefs["10.1023/A:1012737223465"] == "https://doi.org/10.1023/A:1012737223465"   # https://doi.org/10.…
    assert "10.1017/CBO9781139171472" in hrefs                 # Word のハイパーリンクが付いた DOI も同じ形
    assert not any("CBO9781139171472" in (u.get(f"{{{XLINK}}}href") or "") for u in root.iter("uri"))
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
    assert res.zip_path.name == "jasme_31_1.zip"     # 論文ごとに名前が違う（{資料コード}_{記事識別子}.zip）
    assert res.zip_path.name.isascii()               # 日本語のファイル名は J-STAGE で弾かれる（EMSGM034E）
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
        # 変換した画像もアップロード用の ZIP に入る（修正計画 C）
        assert f"jasme/31/1/31_1/Graphics/{img.name}" in _names(res.zip_path)
        assert res.not_zipped == [] and res.zip_issues == []
    else:
        assert img.status == "failed"


def test_images_to_prepare_are_listed_at_top_and_in_checklist(journal, meta, tmp_path):
    from jasme_jats.images import ImageResult
    from jasme_jats.report import images_to_prepare, render
    # EMF を変換しない設定では、テンプレートの図は「要対応」になる
    res = convert(TEMPLATE, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    assert [(n, c) for n, c, _ in images_to_prepare(res)] == [("31_1_01.png", "図1\u3000三角形ABC")]
    report = res.report_path.read_text(encoding="utf-8")
    top = report.split("## 2.")[0]
    assert "要対応: 画像ファイルを用意できなかった図が 1 件あります" in top
    assert "jasme_31_1.zip の中の `jasme/31/1/31_1/Graphics/`" in top and "`31_1_01.png`: 図1\u3000三角形ABC" in top
    checklist = report.split("## 14.")[1]
    assert "- [ ] **画像ファイルを用意できなかった図 1 件**" in checklist and "`31_1_01.png`（図1\u3000三角形ABC）" in checklist
    # Word の図形で描かれた図（画像ファイルがない）
    res.images[0] = ImageResult(res.images[0].image_id, "31_1_01.png", "", "missing", "")
    assert images_to_prepare(res)[0][2] == "Word の図形・グラフで描かれていて、docx に画像ファイルがない"
    # 画像がすべて出力できたときは、チェックリストに済みとして載る
    res.images[0] = ImageResult(res.images[0].image_id, "31_1_01.png", "word/media/x.emf", "converted")
    assert images_to_prepare(res) == []
    report = render(res)
    assert "要対応: 画像ファイル" not in report and "- [x] 画像 1 件はすべて Graphics/ に入っている" in report


def _image_bytes(fmt="PNG", mode="RGB", size=(120, 80)):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new(mode, size, "white").save(buf, fmt)
    return buf.getvalue()


def test_add_images_puts_user_images_into_zip_and_report(journal, meta, tmp_path):
    from jasme_jats.pipeline import add_images
    from jasme_jats.report import images_to_prepare
    res = convert(TEMPLATE, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    # 用意が必要でない名前・読めない画像・複数ページの PDF は受け付けない（何も入れない）
    with pytest.raises(ValueError, match="用意が必要な画像ではありません"):
        add_images(res, {"31_1_09.png": _image_bytes()})
    with pytest.raises(ValueError, match="「x.png」を画像として読めません"):
        add_images(res, {"31_1_01.png": ("x.png", b"not an image")})
    assert add_images(res, {"31_1_09.png": _image_bytes()}, skip_unneeded=True) == []
    assert images_to_prepare(res)
    # JPEG（CMYK）を渡しても、出力ファイル名の形式（PNG）にして入れる
    assert add_images(res, {"31_1_01.png": ("図1.jpg", _image_bytes("JPEG", "CMYK"))}) == ["31_1_01.png"]
    assert images_to_prepare(res) == []
    with zipfile.ZipFile(res.zip_path) as z:
        assert z.read("jasme/31/1/31_1/Graphics/31_1_01.png")[:4] == b"\x89PNG"
    report = res.report_path.read_text(encoding="utf-8")
    assert "要対応: 画像ファイル" not in report and "- [x] 画像 1 件はすべて Graphics/ に入っている" in report
    assert "| 利用者が用意 | 利用者が用意した画像（図1.jpg）を入れた。変換のときの状態: EMF/WMF の変換を行わない設定" in report


def test_add_images_accepts_one_page_pdf(journal, meta, tmp_path):
    pytest.importorskip("pypdfium2")
    from jasme_jats.images import user_image
    pdf = _image_bytes("PDF", size=(300, 200))
    assert user_image(pdf, "a.png")[:4] == b"\x89PNG"
    with pytest.raises(ValueError, match="2 ページの PDF"):
        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (50, 50), "white").save(buf, "PDF", save_all=True,
                                                  append_images=[Image.new("RGB", (50, 50), "white")])
        user_image(buf.getvalue(), "a.png")


def test_cli_images_option(journal, tmp_path, capsys):
    from jasme_jats.cli import main
    meta = tmp_path / "meta.toml"
    meta.write_text('[article]\nvolume = "31"\nissue = "1"\nfpage = "1"\npeer_review = "あり"\n', encoding="utf-8")
    args = [str(TEMPLATE), "--meta", str(meta), "--no-metafile-conversion"]
    assert main(args + ["--out", str(tmp_path / "a")]) == 1           # 画像が足りないのは要対応（修正計画 D）
    assert "--images で指定するか" in capsys.readouterr().err
    imgs = tmp_path / "imgs"
    imgs.mkdir()
    (imgs / "31_1_01.jpg").write_bytes(_image_bytes("JPEG"))      # 拡張子は問わない
    assert main(args + ["--out", str(tmp_path / "b"), "--images", str(imgs)]) == 0
    out = capsys.readouterr()
    assert "画像を入れて ZIP とレポートを作り直した: 31_1_01.png" in out.out and "要対応" not in out.err
    assert (tmp_path / "b/jasme/31/1/31_1/Graphics/31_1_01.png").exists()


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


def test_ref_doi_as_uri(journal, meta, tmp_path):
    # 設定 ref_doi = "uri": 「https://doi.org/10.…」の文字全体を <uri> にする（文字はそのまま）
    import dataclasses
    j = dataclasses.replace(journal, ref_doi="uri")
    res = convert(FULL, meta, j, Options(out_dir=tmp_path, convert_metafiles=False))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    root = load(res)
    ref_uris = {"".join(u.itertext()): u.get(f"{{{XLINK}}}href") for r in root.iter("ref") for u in r.iter("uri")}
    assert ref_uris["https://doi.org/10.1023/A:1012737223465"] == "https://doi.org/10.1023/A:1012737223465"
    assert ref_uris["10.1234/jt.2025.001"] == "https://doi.org/10.1234/jt.2025.001"
    assert ref_uris["https://doi.org/10.1017/CBO9781139171472"] == "https://doi.org/10.1017/CBO9781139171472"
    assert root.find(".//pub-id") is None


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


def test_categories_and_keywords(journal, meta, tmp_path):
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    root = load(res)
    assert root.get("article-type") == "other"                       # 記事種別: その他
    subjects = [(g.get(XML_LANG), g.findtext("subject")) for g in root.iter("subj-group")]
    assert subjects == [("ja", "論文"), ("en", "Article")]           # 原稿種別（日・英）
    kwds = {g.get(XML_LANG): [k.text for k in g.iter("kwd")] for g in root.iter("kwd-group")}
    assert kwds == {"ja": ["論証", "数学的探究"], "en": ["proof"]}
    assert not any("キーワード" in w for w in res.warnings)


def test_keyword_parsing_and_count():
    from jasme_jats.config import ArticleMeta, keyword_language_mismatch, keyword_problem, split_keywords
    assert split_keywords("equity；ジェンダー; 数学教育 ; ;ICT活用") == (["ジェンダー", "数学教育", "ICT活用"], ["equity"])
    # 言語別の欄（「;」「；」区切り）。キーワードは任意
    m = ArticleMeta.from_dict({"keywords_ja": "数学教育；ジェンダー; ", "keywords_en": "equity; gender, participation"})
    assert m.keywords_ja == ["数学教育", "ジェンダー"] and m.keywords_en == ["equity", "gender, participation"]
    assert keyword_problem(ArticleMeta.from_dict({})) == ""
    assert "上限は 100 個" in keyword_problem(ArticleMeta.from_dict({"keywords_en": ";".join(map(str, range(101)))}))
    # 入力欄の取り違えの確認
    assert keyword_language_mismatch(ArticleMeta.from_dict({"keywords_ja": "equity", "keywords_en": "数学"})) == ["equity", "数学"]

def test_manuscript_type_choices(journal, tmp_path):
    from jasme_jats.config import ArticleMeta
    # 原稿種別（日）だけ指定すれば、英語は設定ファイルの選択肢から決まる
    assert journal.subjects(ArticleMeta.from_dict({"subject_ja": "共同研究"})) == ("共同研究", "Collaborative Research Report")
    assert journal.subjects(ArticleMeta.from_dict({"subject_ja": "講演記事"})) == ("講演記事", "Oration")
    assert journal.subjects(ArticleMeta.from_dict({})) == ("論文", "Article")
    # 「その他」（自由入力）
    meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "peer_review": "なし",
                                  "subject_ja": "資料", "subject_en": "Material"})
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    subjects = [(g.get(XML_LANG), g.findtext("subject")) for g in load(res).iter("subj-group")]
    assert subjects == [("ja", "資料"), ("en", "Material")]
    assert not any("原稿種別" in w for w in res.warnings)


def test_textbox_figures_and_captions(journal, meta, tmp_path):
    # テキストボックスの中の表・画像を読み、本文スタイルの「図N」「表N」の段落をキャプションと推定する
    from conftest import EDGE
    res = convert(EDGE, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    assert res.fidelity.ok and res.dtd_valid
    root = load(res)
    caps = {el.get("id"): ("".join(el.find("caption").itertext()) if el.find("caption") is not None else None,
                           len(list(el.iter("graphic"))), el.find("table") is not None)
            for el in root.iter("fig", "table-wrap") if el.get("id")}
    # 図の左上がアンカー段落の左上にあるテキストボックス: 中身を組にして、アンカー段落の前に機械的に置く
    assert caps["F2"] == ("図2　テキストボックス内の表で組んだ問題", 0, False)
    assert root.find(".//fig[@id='F2']/table-wrap/table") is not None      # 表で組んだ図は図の中に表を入れる
    assert {i.mode for i in res.plan.floats.values()} == {"mechanical"}
    assert caps["F3"] == ("図3　テキストボックス内の画像", 1, False)        # 前の図のキャプションに画像を取られない
    assert ("表1　テキストボックス内の表", 0, True) in caps.values()
    assert "問1　架空の問題文である。" in "".join(root.itertext())
    mech = [d.message for d in res.plan.decisions if d.stage == "mechanical"]
    assert any("「図3　テキストボックス内の画像」を図キャプションと推定" in m for m in mech)
    assert any("「表1　テキストボックス内の表」を表キャプションと推定" in m for m in mech)


def test_wrapped_rows_cells_and_textbox_paragraphs(journal, meta, tmp_path):
    # コンテンツコントロール（w:sdt）・w:customXml に包まれた表の行・セルとテキストボックスの段落も、
    # XML の表・図の中に、文書の順に入る（不変性チェックの合格だけでは、入った場所までは分からない）
    from conftest import READER
    res = convert(READER, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    assert res.fidelity.ok and res.dtd_valid
    root = load(res)

    def rows(caption):
        tw = next(t for t in root.iter("table-wrap") if "".join(t.find("caption").itertext()) == caption)
        return [["".join(c.itertext()) for c in r] for r in tw.iter("tr")]
    assert rows("表1　コンテンツコントロールに包んだ行")[1:] == [["前", "SDTの行の前"], ["包んだ行", "SDTで包んだ行"],
                                                         ["後", "SDTの行の後"]]
    assert rows("表2　カスタムXMLに包んだ行")[2] == ["包んだ行", "XMLで包んだ行"]
    assert rows("表3　カスタムXMLとコンテンツコントロールに包んだセル")[1] == ["セルの左", "XMLで包んだセル", "SDTで包んだセル",
                                                                "セルの右"]
    assert [r[1] for r in rows("表4　入れ子のコンテンツコントロールに包んだ行")[1:]] == [
        "入れ子のSDTの1行目", "入れ子のSDTの2行目", "XMLを包んだSDTの行", "入れ子の行の後"]
    assert rows("表5　テキストボックスの中の包まれた表") == [["観点", "内容"], ["包んだ表", "テキストボックスのSDTの表"]]
    # テキストボックスの中で w:sdt に包んだキャプションも、同じテキストボックスの画像と組になり、機械的に置かれる
    fig = root.find(".//fig[@id='F1']")
    assert "".join(fig.find("caption").itertext()) == "図1　コンテンツコントロールに包んだキャプション"
    assert len(list(fig.iter("graphic"))) == 1
    assert {i.mode for i in res.plan.floats.values()} == {"mechanical"}


def test_blank_paragraphs_in_textbox_and_endnote_are_excluded(journal, meta, tmp_path):
    # 文字だけのテキストボックスと、本文から参照されていない Word の文末脚注の中の、空白だけの段落（全角空白・半角空白）も、
    # 除外として記録する（記録しないと、出力にも除外にもならず、不変性チェックが「出力漏れ」で不合格になる）。
    # 本文から参照された文末脚注の空白だけの段落は、脚注と同じく注の中に出力する（0.24.0）
    S = mf.S

    def parts(b):
        img = b.add_image("blank.png", mf.png_bytes("Blank", size=(400, 240)))
        return [mf.para(S["sec1"], "１．はじめに"),
                mf.para(S["body"], "試験（2024）の問題を枠で囲んだ。", mf.textbox(
                    mf.para(S["body"], "問1\u3000枠の中の問題文である。") + mf.para(S["body"], "\u3000")
                    + mf.para(S["body"], " "), 903, cx=5000000)),
                mf.para(S["body"], "文末脚注を付けた文", mf.endnote_ref(4), "。"),
                # 図の画像の段落にある空白（書き出しの段階で、空白だけの除外として記録する）
                mf.para(S["body"], mf.drawing(img, 1800000, 1080000, 904), "\u3000"),
                mf.para(S["fig_cap"], "図1\u3000画像の後ろに空白がある図")]
    path = tmp_path / "blank.docx"
    mf.make_article(path, "空白だけの段落の検証用文書", parts,
                    endnotes=[mf.endnote(4, " 文末脚注の本文。", mf.para(None, "\u3000"), mf.para(None, " ")),
                              mf.endnote(5, " 参照されていない文末脚注の本文。", mf.para(None, "\u3000"), mf.para(None, " "))])
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    fid = res.fidelity
    assert fid.ok and fid.final_ok and res.dtd_valid, (fid.missing, fid.bad_excluded)
    # 本文（テキストボックス）の段落 d… と、参照されていない文末脚注の段落 e… の、全角空白・半角空白だけの段落
    blank = sorted((s[0], t) for s, reason, t in fid.excluded if reason == "空白のみの段落")
    assert blank == [("d", " "), ("d", "\u3000"), ("e", " "), ("e", "\u3000")]
    assert all(e.blank for e in res.plan.exclusions if e.reason == "空白のみの段落") and fid.bad_excluded == []
    _, plan, _ = _mechanical(path, journal)
    assert [(e.reason, e.text, e.blank) for e in build(plan, meta, journal)[1].exclusions] == [
        ("図の画像だけの段落にある空白", "\u3000", True)]
    reasons = {t: reason for _, reason, t in fid.excluded}
    assert reasons["問1\u3000枠の中の問題文である。"].startswith("テキストボックス内の文字")
    assert reasons[" 参照されていない文末脚注の本文。"] == "Word の文末脚注 5（本文から参照されていない注）"
    # 参照された文末脚注は注 fn1 になり、空白だけの段落も注の中に出力する（除外にしない）
    fn = etree.fromstring(res.xml_path.read_bytes().split(b"\n", 2)[2]).find(".//fn-group/fn")
    assert ["".join(p.itertext()) for p in fn.findall("p")] == ["1) 文末脚注の本文。", "\u3000", " "]
    assert " 文末脚注の本文。" not in reasons


def test_blank_paragraphs_in_front_and_back_tables_are_excluded(journal, meta, tmp_path):
    # 著者名スタイルの段落・冒頭のテキストボックスの表・引用文献の節の表・注の節の表・英文の部分の表（著者表以外）の、
    # 全角空白だけの段落も、空白だけの除外として記録する（記録しないと、不変性チェックが「出力漏れ」で不合格になる）
    S = mf.S

    def tbl(text):
        return mf.table([[mf.cell(text), mf.cell("\u3000")]])
    b = mf.Builder()
    front = mf.front_ja(b, "表の空白の検証用文書", "―副題―", [("架空大学", "試験\u3000六郎")])
    front.insert(len(front) - 3, mf.para(S["author_ja"], "\u3000"))                 # 著者名スタイルの全角空白
    front[3].append(b.frag(mf.para(None, mf.textbox(tbl("冒頭の囲みの表"), 905, cx=5000000)))[0][0])
    body = front + [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "試験（2024）の本文である。"),
                    mf.para(S["ref_head"], "引用および参考文献"),
                    mf.para(S["ref"], "試験六郎（2024）．「小さな論文」．『架空誌』，第5巻，pp.9-10．"), tbl("文献の表"),
                    mf.para(S["fn_head"], "注"), mf.para(S["body"], "1）注の本文。"), tbl("注の表")]
    english = mf.front_en(b, "A Small Article", "For Checking", [("Rokuro SHIKEN", "Fictional University")],
                          ["Small article abstract."])
    english.insert(4, tbl("English table"))                                          # 英文の著者表の前の表
    path = tmp_path / "blank_tables.docx"
    b.save(path, body + english + mf.tail(b))
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    fid = res.fidelity
    assert fid.ok and fid.final_ok and res.dtd_valid, (fid.missing, fid.bad_excluded)
    assert fid.bad_excluded == [] and fid.conflicts == []
    blank = [e for e in res.plan.exclusions if e.reason == "空白のみの段落"]
    assert [e.text for e in blank] == ["\u3000"] * 5 and all(e.blank for e in blank)
    reasons = {t: reason for _, reason, t in fid.excluded}
    assert reasons["冒頭の囲みの表"] == "冒頭部の表（著者表以外）の文字"
    assert reasons["注の表"] == "後付けの位置づけが不明な表の文字"
    assert reasons["English table"] == "英文部分の表（著者表以外）の文字"
    assert "文献の表" in [r.para.plain() for r in res.plan.refs]                    # 引用文献の表の文字は引用文献のまま


def test_textbox_caption_pattern():
    from jasme_jats.model import Atom, Para
    from jasme_jats.structure import Classifier

    def cap(text):
        return Classifier.textbox_caption(Para(src="d1", atoms=[Atom(kind="text", text=text)]))
    assert cap("図１　開発した問題") == "fig_caption"
    assert cap("Figure 2. A model") == "fig_caption"
    assert cap("表3「解答類型」") == "table_caption"
    # 本文の文はキャプションにしない
    assert cap("図1は，教科書の見開きページである") is None
    assert cap("図1，図2を参照") is None
    assert cap("図1〜3に示す") is None
    assert cap("図1に示すとおりである。") is None


def _img_para(src):
    from jasme_jats.model import Atom, ImageRef, Para
    return Para(src=src, atoms=[Atom(kind="image", image=ImageRef(rel_id="r", target=f"word/media/{src}.png", source="drawing"))])


def _text_para(src, text):
    from jasme_jats.model import Atom, Para
    return Para(src=src, atoms=[Atom(kind="text", text=text)])


def test_figure_pairing_caption_above_and_below(journal):
    from jasme_jats.structure import Classifier, FigNode
    cl = Classifier(None, journal)
    # キャプションが画像の上にある原稿（図が続く）
    c1, i1, c2, i2 = _text_para("c1", "図1 上"), _img_para("i1"), _text_para("c2", "図2 上"), _img_para("i2")
    figs = [n for n in cl.assemble_floats([("fig_caption", c1), ("p", i1), ("fig_caption", c2), ("p", i2)])
            if isinstance(n, FigNode)]
    assert [(f.caption.src, [p.src for p in f.image_paras]) for f in figs] == [("c1", ["i1"]), ("c2", ["i2"])]
    # キャプションが画像の下にある原稿: 画像のない図（表で組んだ図など）のキャプションが、次の図の画像を取らない
    ca, t, i, cb = _text_para("ca", "図1 表の図"), _text_para("t", "本文。"), _img_para("i"), _text_para("cb", "図2 下")
    figs = [n for n in cl.assemble_floats([("fig_caption", ca), ("p", t), ("p", i), ("fig_caption", cb)])
            if isinstance(n, FigNode)]
    assert [(f.caption.src, [p.src for p in f.image_paras]) for f in figs] == [("ca", []), ("cb", ["i"])]


def test_report_lists_paragraphs_with_unknown_style():
    from jasme_jats.report import style_unknown_rows
    from jasme_jats.structure import ArticlePlan
    plan = ArticlePlan(lang="ja")
    for k in range(7):
        p = _text_para(f"d{k}", f"標準スタイルの本文{k}")
        p.style_name, p.note = "Normal", "style_unknown"
        plan.paras[p.src] = p
    plan.locations["d0"] = "１．はじめに / 第1要素"
    rows = style_unknown_rows(plan)
    assert len(rows) == 1
    assert rows[0][2] == "１．はじめに / 第1要素ほか"
    assert "スタイル「Normal」）7 件を本文の段落として扱った" in rows[0][3] and rows[0][3].endswith("ほか")


# ---------------------------------------------------------------------------- アップロード用 ZIP の中身（修正計画 C: M1・M2）
def _names(zpath):
    with zipfile.ZipFile(zpath) as z:
        return z.namelist()


def _handmade_zip(path, entries):
    """zipfile で ZIP を手作りする。entries: ZIP の中のパス -> 中身（bytes）。"""
    with zipfile.ZipFile(path, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return path


def test_upload_zip_has_only_this_article(journal, meta, tmp_path):
    from jasme_jats.pipeline import add_images
    # EMF を変換できなかったとき: 元の画像は出力フォルダの直下の 要変換/ に置き、ZIP には入れない（EMSGM034E・074E）
    res = convert(TEMPLATE, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    names = _names(res.zip_path)
    assert names == ["jasme/31/1/31_1/31_1.xml"]
    assert all(n.isascii() for n in names)
    assert (tmp_path / "要変換" / "31_1_01.emf").exists()
    assert not (tmp_path / "jasme/31/1/31_1/要変換").exists()
    assert "要変換/31_1_01.emf" in res.images[0].message
    assert res.images[0].message.startswith("EMF/WMF の変換を行わない設定")      # メッセージの先頭の理由は変えない
    assert res.jstage_issues == [] and res.zip_issues == [] and res.not_zipped == []
    # 利用者が用意した画像を入れると、その画像だけが ZIP に加わる
    add_images(res, {"31_1_01.png": _image_bytes()})
    assert _names(res.zip_path) == ["jasme/31/1/31_1/31_1.xml", "jasme/31/1/31_1/Graphics/31_1_01.png"]
    assert res.zip_issues == [] and res.not_zipped == []
    # 手作りした ZIP: 記事フォルダの中の 要変換/ は、日本語のフォルダ名（EMSGM034E）と想定外の項目（EMSGM074E）
    from jasme_jats.package import zip_problems
    bad = _handmade_zip(tmp_path / "bad.zip", {"jasme/31/1/31_1/31_1.xml": b"<article/>",
                                              "jasme/31/1/31_1/要変換/x.emf": b"emf"})
    ids = [mid for mid, _ in zip_problems(bad, journal, meta)]
    assert "EMSGM034E" in ids and "EMSGM074E" in ids


def test_zip_problems_on_handmade_zips(journal, meta, tmp_path):
    from jasme_jats.package import zip_problems
    xml = {"jasme/31/1/31_1/31_1.xml": b"<article/>"}
    # ZIP の名前が日本語（全角の巻）: EMSGM034E が 1 件
    got = zip_problems(_handmade_zip(tmp_path / "jasme_３１_１.zip", xml), journal, meta)
    assert [mid for mid, _ in got] == ["EMSGM034E"] and "jasme_３１_１.zip" in got[0][1]
    # 0 バイトのファイル: XML は EMSGM053E、PDF は EMSGM059E、画像は EMSGM073E
    got = zip_problems(_handmade_zip(tmp_path / "a.zip", {"jasme/31/1/31_1/31_1.xml": b"",
                                                          "jasme/31/1/31_1/31_1.pdf": b"",
                                                          "jasme/31/1/31_1/Graphics/31_1_01.png": b""}), journal, meta)
    assert [mid for mid, _ in got] == ["EMSGM053E", "EMSGM059E", "EMSGM073E"]
    # 記事フォルダの外（同じ出力フォルダで変換したほかの記事）: 記事フォルダごとに 1 件（'-'。EMSGM219E のおそれ）
    got = zip_problems(_handmade_zip(tmp_path / "b.zip", {**xml, "jasme/31/1/31_13/31_13.xml": b"<article/>",
                                                          "jasme/31/1/31_13/Graphics/31_13_01.png": b"png"}), journal, meta)
    assert [mid for mid, _ in got] == ["-"] and "jasme/31/1/31_13/" in got[0][1]
    # 想定どおりの ZIP（フォルダの項目があってもよい）は問題なし
    ok = _handmade_zip(tmp_path / "c.zip", {"jasme/": b"", "jasme/31/": b"", "jasme/31/1/": b"", "jasme/31/1/31_1/": b"",
                                            **xml, "jasme/31/1/31_1/31_1.pdf": b"%PDF", "jasme/31/1/31_1/Graphics/": b"",
                                            "jasme/31/1/31_1/Graphics/31_1_01.png": b"png"})
    assert zip_problems(ok, journal, meta) == []
    # 記事の XML がない ZIP（make_zip は必ず入れる。手で作り直したときなど）: '-' が 1 件
    got = zip_problems(_handmade_zip(tmp_path / "d.zip", {"jasme/31/1/31_1/31_1.pdf": b"%PDF"}), journal, meta)
    assert [mid for mid, _ in got] == ["-"] and "jasme/31/1/31_1/31_1.xml" in got[0][1]
    assert [mid for mid, _ in zip_problems(_handmade_zip(tmp_path / "e.zip", {}), journal, meta)] == ["-"]


def test_zip_image_names_by_status():
    from jasme_jats.images import ImageResult
    from jasme_jats.package import zip_image_names
    # ZIP に入れるのは、そのまま出力（ok）・変換して出力（converted）・利用者が用意（user）の画像だけ
    images = [ImageResult(f"rId{k}", f"31_1_0{k}.png", "", st) for k, st in
              enumerate(["ok", "converted", "user", "failed", "missing"], 1)]
    assert zip_image_names(images) == ["31_1_01.png", "31_1_02.png", "31_1_03.png"]
    assert zip_image_names([ImageResult("rId9", "", "", "ok")]) == []         # 名前のない画像は入れない


def test_missing_image_note_points_to_step7_and_images_option(tmp_path):
    from types import SimpleNamespace

    from jasme_jats.images import export_images
    # Word の図形（画像ファイルがない）: 9 章の備考は、記事フォルダに手で置く案内ではなく、手順 7・--images を案内する
    img = SimpleNamespace(image_id="rId1", export_name="31_1_01.png", shape_only=True, target="")
    got = export_images(SimpleNamespace(media={}), [img], tmp_path / "Graphics", keep_dir=tmp_path / "要変換")
    assert [(i.status, i.name) for i in got] == [("missing", "31_1_01.png")]
    assert got[0].message.startswith("Word の図形・グラフなどで画像ファイルがない。")      # 先頭の理由は変えない
    assert "手順 7" in got[0].message and "--images" in got[0].message and "ZIP には入らない" in got[0].message


def test_pdf_stays_in_zip_after_add_images(journal, meta, tmp_path):
    from jasme_jats.pipeline import add_images
    pdf = tmp_path / "dummy.pdf"
    pdf.write_bytes(b"%PDF-1.4 dummy\n")                    # 写すだけ（ルート1。照合では読めず、変換は続ける）
    res = convert(TEMPLATE, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False, pdf_path=pdf))
    assert res.has_pdf and "jasme/31/1/31_1/31_1.pdf" in _names(res.zip_path)
    res.zip_issues = [("-", "変換のときの値")]               # add_images が計算し直すことを確かめる
    add_images(res, {"31_1_01.png": _image_bytes()})
    assert _names(res.zip_path) == ["jasme/31/1/31_1/31_1.xml", "jasme/31/1/31_1/31_1.pdf",
                                    "jasme/31/1/31_1/Graphics/31_1_01.png"]
    assert res.not_zipped == [] and res.zip_issues == []
    assert "- [x] PDF（31_1.pdf）がアップロード用の ZIP に入っている" in res.report_path.read_text(encoding="utf-8")


def test_pdf_left_in_article_folder_can_be_given_again(journal, meta, tmp_path):
    from conftest import PDFCHECK
    pdf = tmp_path / "dummy.pdf"
    pdf.write_bytes(b"%PDF-1.4 dummy\n")
    out = tmp_path / "out"
    convert(PDFCHECK, meta, journal, Options(out_dir=out, convert_metafiles=False, pdf_path=pdf))
    # 記事フォルダに残っている PDF をそのまま指定しても（--pdf out/jasme/31/1/31_1/31_1.pdf）、同じファイルなので写さずに使う
    left = out / "jasme/31/1/31_1/31_1.pdf"
    res = convert(PDFCHECK, meta, journal, Options(out_dir=out, convert_metafiles=False, pdf_path=left))
    assert res.has_pdf and left.read_bytes() == pdf.read_bytes()
    assert "jasme/31/1/31_1/31_1.pdf" in _names(res.zip_path) and res.not_zipped == [] and res.zip_issues == []


def test_rerun_with_user_images_keeps_report_consistent(journal, meta, tmp_path):
    from jasme_jats.pipeline import add_images
    opts = Options(out_dir=tmp_path, convert_metafiles=False)
    png = _image_bytes()
    res = convert(TEMPLATE, meta, journal, opts)
    add_images(res, {"31_1_01.png": png})
    res = convert(TEMPLATE, meta, journal, opts)            # 同じ出力フォルダで変換し直す（Colab の手順 5・6）
    assert res.not_zipped == ["Graphics/31_1_01.png"]       # 前に入れた画像は、入れ直すまで ZIP に入れない
    add_images(res, {"31_1_01.png": png}, skip_unneeded=True)
    assert res.not_zipped == []                              # 入れ直した後は計算し直す
    tenth = res.report_path.read_text(encoding="utf-8").split("## 10.")[1].split("## 11.")[0]
    assert "ZIP に入れなかった" not in tenth
    assert "jasme/31/1/31_1/Graphics/31_1_01.png" in _names(res.zip_path)


def test_files_put_by_hand_are_not_zipped(journal, meta, tmp_path):
    opts = Options(out_dir=tmp_path, convert_metafiles=False)
    convert(FULL, meta, journal, opts)
    (tmp_path / "jasme/31/1/31_1/memo.txt").write_text("手で置いたメモ", encoding="utf-8")
    res = convert(FULL, meta, journal, opts)
    assert res.not_zipped == ["memo.txt"]
    assert "jasme/31/1/31_1/memo.txt" not in _names(res.zip_path)
    report = res.report_path.read_text(encoding="utf-8")
    tenth = report.split("## 10.")[1].split("## 11.")[0]
    assert "ZIP に入れなかった" in tenth and "`memo.txt`" in tenth and "対応は要りません" in tenth
    assert "ZIP に入れなかったファイル 1 件（10 章）" in report.split("## 2.")[0]


def test_empty_pdf_is_reported_by_zip_check(journal, meta, tmp_path):
    from conftest import PDFCHECK
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    res = convert(PDFCHECK, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False, pdf_path=empty))
    assert res.has_pdf and "EMSGM059E" in [mid for mid, _ in res.zip_issues]
    assert res.jstage_issues == []                          # XML のチェックとは分けて持つ
    report = res.report_path.read_text(encoding="utf-8")
    assert "要対応 1 件（12 章）" in report.split("## 2.")[0]
    assert "| EMSGM059E |" in report.split("## 12.")[1].split("## 13.")[0]


def test_zip_of_second_article_in_same_out_dir(journal, tmp_path):
    from jasme_jats.config import ArticleMeta

    def meta_of(fpage):
        return ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": fpage, "peer_review": "あり"})
    opts = Options(out_dir=tmp_path, convert_metafiles=False)
    r1 = convert(FULL, meta_of("1"), journal, opts)
    before = r1.zip_path.read_bytes()
    r2 = convert(FULL, meta_of("13"), journal, opts)        # 同じ出力フォルダで 2 本目
    assert r2.zip_path != r1.zip_path
    names = _names(r2.zip_path)
    assert names and all(n.startswith("jasme/31/1/31_13/") for n in names)
    assert r1.zip_path.read_bytes() == before                # 1 本目の ZIP は変わらない
    assert r2.zip_issues == [] and r2.not_zipped == []
    # 開始ページを打ち間違えて変換し直した（1 → 15）: 前の記事フォルダは ZIP に入らない
    r3 = convert(FULL, meta_of("15"), journal, opts)
    assert all(n.startswith("jasme/31/1/31_15/") for n in _names(r3.zip_path)) and r3.zip_issues == []


def test_pdf_of_previous_run_is_not_zipped(journal, meta, tmp_path):
    from conftest import PDFCHECK
    pdf = tmp_path / "dummy.pdf"
    pdf.write_bytes(b"%PDF-1.4 dummy\n")                    # 写すだけ（照合では読めず、変換は続ける）
    out = tmp_path / "out"
    r1 = convert(PDFCHECK, meta, journal, Options(out_dir=out, convert_metafiles=False, pdf_path=pdf))
    assert r1.has_pdf and "jasme/31/1/31_1/31_1.pdf" in _names(r1.zip_path)
    assert "- [x] PDF（31_1.pdf）がアップロード用の ZIP に入っている" in r1.report_path.read_text(encoding="utf-8")
    r2 = convert(PDFCHECK, meta, journal, Options(out_dir=out, convert_metafiles=False))     # 同じ記事を PDF なしで
    assert not r2.has_pdf and r2.not_zipped == ["31_1.pdf"]
    assert "jasme/31/1/31_1/31_1.pdf" not in _names(r2.zip_path)
    assert not any("31_1.pdf" in w for w in r2.warnings)     # 警告（10 章の箇条）ではなく not_zipped に持つ
    report = r2.report_path.read_text(encoding="utf-8")
    pdf_line = next(line for line in report.split("## 14.")[1].splitlines() if "PDF（31_1.pdf）" in line)
    assert pdf_line.startswith("- [ ]") and "--pdf" in pdf_line and "手順 2" in pdf_line
    tenth = report.split("## 10.")[1].split("## 11.")[0]
    assert "`31_1.pdf`" in tenth and "--pdf" in tenth and "手順 2" in tenth


def test_cli_prints_files_not_zipped(journal, tmp_path, capsys):
    from jasme_jats.cli import main
    meta = tmp_path / "meta.toml"
    meta.write_text('[article]\nvolume = "31"\nissue = "1"\nfpage = "1"\npeer_review = "あり"\n', encoding="utf-8")
    args = [str(FULL), "--meta", str(meta), "--no-metafile-conversion", "--out", str(tmp_path / "o")]
    assert main(args) == 0
    (tmp_path / "o/jasme/31/1/31_1/31_1.pdf").write_bytes(b"%PDF-1.4 dummy\n")     # 記事フォルダに手で置いた PDF
    capsys.readouterr()
    assert main(args) == 0
    out = capsys.readouterr().out
    assert "ZIP に入れなかったファイル 1 件" in out and "31_1.pdf" in out and "--pdf" in out


# ---------------------------------------------------------------------------- 書誌情報の入力値（修正計画 C: N4・U1）
def test_volume_issue_pages_are_normalized(journal):
    from jasme_jats.config import ArticleMeta
    m = ArticleMeta.from_dict({"volume": "３１", "issue": "1", "fpage": "１", "lpage": "１２"})
    assert m.article_id(journal) == "31_1" and (m.volume, m.fpage, m.lpage) == ("31", "1", "12")
    assert m.input_notes == ["巻「３１」を「31」として読みました（全角の文字を半角にしました）",
                             "最初のページ「１」を「1」として読みました（全角の文字を半角にしました）",
                             "最後のページ「１２」を「12」として読みました（全角の文字を半角にしました）"]
    assert ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1"}).input_notes == []
    assert ArticleMeta.from_dict({"input_notes": ["x"]}).input_notes == []      # 入力の同名の鍵は使わない
    with pytest.raises(ValueError, match="巻「31巻」に、使えない文字「巻」があります.*全角の文字"):
        ArticleMeta.from_dict({"volume": "31巻"})
    with pytest.raises(ValueError, match="号「1-2」に、使えない文字「-」"):
        ArticleMeta.from_dict({"issue": "1-2"})
    with pytest.raises(ValueError, match="最初のページ「p.１」に、使えない文字「.」"):
        ArticleMeta.from_dict({"fpage": "p.１"})
    with pytest.raises(ValueError, match="使えない文字「空白」"):
        ArticleMeta.from_dict({"volume": "3 1"})
    # 幅のない空白（U+200B）などの見えない文字は「見えない文字」と書き、全角の文字とは言わない
    with pytest.raises(ValueError, match="号「１\u200b」に、使えない文字「見えない文字」があります") as ei:
        ArticleMeta.from_dict({"volume": "31", "issue": "１\u200b"})
    assert "全角の文字" not in str(ei.value) and "打ち直してください" in str(ei.value)
    with pytest.raises(ValueError, match="使えない文字「巻」「見えない文字」.*全角の文字"):
        ArticleMeta.from_dict({"volume": "31巻\u2060"})
    # 終了ページはフォルダ名に使わないので、正規化だけ
    assert ArticleMeta.from_dict({"lpage": "12頁"}).lpage == "12頁"
    assert ArticleMeta.from_dict({"volume": 31, "fpage": 1}).article_id(journal) == "31_1"    # TOML の数


def test_full_width_volume_gives_ascii_zip(journal, tmp_path):
    from jasme_jats.config import ArticleMeta
    meta = ArticleMeta.from_dict({"volume": "３１", "issue": "１", "fpage": "１", "peer_review": "あり"})
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    assert res.zip_path.name == "jasme_31_1.zip" and res.zip_issues == []
    assert all(n.startswith("jasme/31/1/31_1/") for n in _names(res.zip_path))
    eleventh = res.report_path.read_text(encoding="utf-8").split("## 11.")[1].split("## 12.")[0]
    assert "- 巻「３１」を「31」として読みました（全角の文字を半角にしました）" in eleventh


def test_cli_meta_input_errors_and_notes(tmp_path, capsys):
    from jasme_jats.cli import main
    meta = tmp_path / "meta.toml"
    meta.write_text('[article]\nvolume = "31巻"\nissue = "1"\nfpage = "1"\n', encoding="utf-8")
    args = [str(FULL), "--meta", str(meta), "--no-metafile-conversion", "--out", str(tmp_path / "o")]
    assert main(args) == 2                                     # 変換しない（トレースバックで落ちない）
    err = capsys.readouterr().err
    assert "書誌情報" in err and "巻「31巻」" in err and not (tmp_path / "o").exists()
    meta.write_text('[article]\nvolume = "３１"\nissue = "1"\nfpage = "1"\npeer_review = "あり"\n', encoding="utf-8")
    assert main(args) == 0
    assert "※ 書誌情報: 巻「３１」を「31」として読みました" in capsys.readouterr().out
    meta.write_text('[article]\nreceived = "2026/13/1"\n', encoding="utf-8")
    assert main(args) == 2 and "受付日「2026/13/1」を読めません" in capsys.readouterr().err


def test_dates_accept_common_forms():
    import datetime as dt

    from jasme_jats.config import ArticleMeta, _date
    for v in ["2026-03-31", "2026/3/31", "2026.3.31", "2026-3-31", "2026年3月31日", "２０２６／３／３１", "20260331",
              " 2026/3/31 ", "2026 / 3 / 31", "２０２６年 ３月 ３１日"]:
        assert _date(v) == dt.date(2026, 3, 31), v
    # アラビア・インド数字（NFKC でも半角にならない）は [0-9] でないので読まない
    for v in ["2026/13/1", "2026-02-30", "26/3/31", "2026-W13-2", "2026-03", "2026-03-31 10:00", "令和8年3月31日",
              "\u0662\u0660\u0662\u0666/\u0663/\u0663\u0661"]:
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            _date(v)
    with pytest.raises(ValueError, match="^日付「2026-03」"):     # 欄の名前の既定は「日付」
        _date("2026-03")
    assert _date(dt.datetime(2026, 3, 31, 10, 0)) == dt.date(2026, 3, 31)     # TOML の引用符なしの日時
    assert type(_date(dt.datetime(2026, 3, 31, 10, 0))) is dt.date
    assert _date(dt.date(2026, 3, 31)) == dt.date(2026, 3, 31)
    assert _date("　") is None and _date("") is None and _date(None) is None
    with pytest.raises(ValueError, match="受付日「2026/13/1」"):
        ArticleMeta.from_dict({"received": "2026/13/1"})
    m = ArticleMeta.from_dict({"pub_date": "2026/3/31", "received": "2025年6月1日", "approved": "２０２５．１１．１０"})
    assert (m.pub_date, m.received, m.approved) == (dt.date(2026, 3, 31), dt.date(2025, 6, 1), dt.date(2025, 11, 10))


# ---------------------------------------------------------------------------- 要対応・要確認の知らせ（修正計画 D の U2）
def test_upload_issues_are_needs_action(journal, tmp_path):
    """J-STAGE のアップロード時チェックの問題（受付日が受理日より後など）は要対応: レポートの冒頭と 14 章に出し、
    コマンドラインは 1 を返して、標準エラーにメッセージ ID を出す。"""
    from jasme_jats.config import ArticleMeta
    from jasme_jats.report import NEEDS_ACTION, actions
    meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12", "pub_date": "2026-03-31",
                                  "received": "2026-01-10", "accepted": "2025-11-20", "peer_review": "あり"})
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    assert res.ok and res.needs_action                     # ok（不変性・DTD）の意味は変えない
    act = next(a for a in actions(res) if a.key == "upload")
    assert act.level == NEEDS_ACTION and "EMSGM106E" in act.box_detail and "EMSGM106E" in act.cli
    report = res.report_path.read_text(encoding="utf-8")
    assert "要対応: J-STAGE のアップロード時チェック" in report.split("## 2.")[0]
    assert "EMSGM106E" in report.split("## 2.")[0]
    ch14 = report.split("## 14.")[1]
    assert any("J-STAGE のアップロード時チェック" in line and "12 章" in line for line in ch14.splitlines())


def test_cli_exits_1_on_upload_issues(tmp_path, capsys):
    from jasme_jats.cli import main
    meta = tmp_path / "meta.toml"
    meta.write_text('[article]\nvolume = "31"\nissue = "1"\nfpage = "1"\npeer_review = "あり"\n'
                    'received = "2026-01-10"\naccepted = "2025-11-20"\n', encoding="utf-8")
    assert main([str(FULL), "--meta", str(meta), "--out", str(tmp_path / "out"), "--no-metafile-conversion"]) == 1
    err = capsys.readouterr().err
    assert "要対応: J-STAGE のアップロード時チェック" in err and "EMSGM106E" in err
    # --meta がないと開始ページがなく（EMSGM230E）、要対応で 1（README に明記）
    assert main([str(FULL), "--out", str(tmp_path / "nometa"), "--no-metafile-conversion"]) == 1
    assert "EMSGM230E" in capsys.readouterr().err


def test_cli_template_needs_image_until_given(tmp_path, capsys):
    """テンプレート（EMF を変換しない設定では図 1 の画像を用意できない）は 1、--images で画像を渡すと 0。"""
    from conftest import META_EXAMPLE

    from jasme_jats.cli import main
    args = [str(TEMPLATE), "--meta", str(META_EXAMPLE), "--no-metafile-conversion"]
    assert main(args + ["--out", str(tmp_path / "a")]) == 1
    assert "--images で指定するか" in capsys.readouterr().err
    imgs = tmp_path / "imgs"
    imgs.mkdir()
    (imgs / "31_1_01.png").write_bytes(_image_bytes())
    assert main(args + ["--out", str(tmp_path / "b"), "--images", str(imgs)]) == 0
    assert "要対応" not in capsys.readouterr().err


def test_cli_input_errors_exit_2(tmp_path, capsys):
    """指定したファイル・フォルダがないとき（トレースバックにしない）と、--images の画像を読めないときは、中止の 2（要対応の 1 ではない）。"""
    from conftest import META_EXAMPLE

    from jasme_jats.cli import main
    for args, word in (([str(tmp_path / "ない.docx")], "変換する docx"),
                       ([str(FULL), "--meta", str(tmp_path / "ない.toml")], "--meta"),
                       ([str(FULL), "--pdf", str(tmp_path / "ない.pdf")], "--pdf"),
                       ([str(FULL), "--ai", "manual", "--ai-response", str(tmp_path / "ない.json")], "--ai-response"),
                       ([str(FULL), "--images", str(tmp_path / "ない")], "--images"),
                       ([str(FULL), "--meta", str(tmp_path)], "--meta")):            # ファイルの代わりにフォルダ
        with pytest.raises(SystemExit) as e:
            main(args + ["--out", str(tmp_path / "out")])
        assert e.value.code == 2 and f"{word} の" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()                  # 変換する前に止める
    # 通常のファイルでなくても読めるもの（シェルのプロセス置換 <(...) の /dev/fd/NN など）は、0.23.0 と同じく変換する
    if Path("/dev/fd").is_dir():
        r, wfd = os.pipe()
        os.write(wfd, META_EXAMPLE.read_bytes())
        os.close(wfd)
        try:
            assert main([str(FULL), "--meta", f"/dev/fd/{r}", "--no-metafile-conversion", "--out", str(tmp_path / "fd")]) == 0
        finally:
            os.close(r)
    imgs = tmp_path / "imgs"
    imgs.mkdir()
    (imgs / "31_1_01.png").write_bytes(b"not an image")     # 読めない画像
    args = [str(TEMPLATE), "--meta", str(META_EXAMPLE), "--no-metafile-conversion", "--out", str(tmp_path / "a")]
    assert main(args + ["--images", str(imgs)]) == 2
    assert "画像: " in capsys.readouterr().err
    assert not (tmp_path / "a/jasme/31/1/31_1/Graphics/31_1_01.png").exists()


def test_fidelity_failure_is_needs_action(journal, meta, tmp_path):
    """不変性チェックが不合格なら、冒頭に今と同じ文で知らせ、要対応にする（決定事項 5(d)）。"""
    from jasme_jats.report import actions, render
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    assert actions(res) == [] and not res.needs_action
    res.fidelity.ok = False
    assert res.needs_action and not res.ok
    head = render(res).split("## 2.")[0]
    assert ("> **注意: 文字の不変性チェックが不合格です。** 出力された XML の本文が docx と一致していません。"
            "下の 5 章の差分を確認し、この XML は登載に使わないでください（変換ツールの不具合の可能性があります）。") in head
    assert "文字の不変性チェックが不合格" in render(res).split("## 14.")[1]
    res.fidelity.ok = True
    res.dtd_valid, res.dtd_errors = False, ["31_1.xml:3: Element body content does not follow the DTD"]
    assert res.needs_action
    report = render(res)
    assert "要対応: J-STAGE 指定の DTD による検証が不合格です（1 件、12 章）" in report.split("## 2.")[0]
    assert "DTD 検証が不合格" in report.split("## 14.")[1]


def test_manual_mode_before_answer_is_needs_action(journal, meta, tmp_path, capsys):
    """手動モードで AI の回答を貼り戻す前の出力は要対応（決定事項 5(c)）。冒頭は手動モードの説明のまま、14 章とコマンドラインで
    回答を貼り戻すよう知らせる。"""
    from jasme_jats.cli import main
    from jasme_jats.report import actions
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path / "a", ai_mode="manual", convert_metafiles=False))
    assert [a.key for a in actions(res)] == ["ai_pending"] and res.needs_action
    report = res.report_path.read_text(encoding="utf-8")
    assert "手動モード: 「AI依頼文.txt」をチャット" in report.split("## 2.")[0]
    assert "AI の回答をまだ反映していない" in report.split("## 14.")[1]
    from conftest import META_EXAMPLE
    assert main([str(FULL), "--meta", str(META_EXAMPLE), "--out", str(tmp_path / "b"), "--ai", "manual",
                 "--no-metafile-conversion"]) == 1
    assert "--ai-response で指定し" in capsys.readouterr().err
