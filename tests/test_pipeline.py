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
    assert main(args + ["--out", str(tmp_path / "a")]) == 0
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
