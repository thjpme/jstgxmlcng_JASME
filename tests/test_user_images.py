"""作業する人が入れる図・表の画像の受け取り（修正計画 W1 の 2.6・2.8。手順 8・9）。

images.check_user_image（中身の確かめ。バイト列は変えない）・images.match_names（ファイル名を置き場所の幹に合わせる）・
package.apply_images（入れた画像を XML に反映する 1 つの関数）・structure.text_before と report.slot_where（置き場所の場所の文）・
structure.caption_body（持ち越しで比べるキャプションの本体）と、変換の後に画像を入れる流れ（pipeline.add_images）。"""
import io
import zipfile
from types import SimpleNamespace

import make_fixtures as mf
import pytest
from lxml import etree

from conftest import fill_images
from jasme_jats.images import SlotImage, check_user_image, match_names
from jasme_jats.model import Atom, Para
from jasme_jats.package import apply_images
from jasme_jats.pipeline import Options, add_images, convert
from jasme_jats.report import _covers_note, actions, image_rows, slot_where
from jasme_jats.structure import caption_body, text_before

XLINK = "{http://www.w3.org/1999/xlink}href"


def image(fmt, mode="RGB", size=(30, 20), **kw) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new(mode, size, (10, 20, 30, 128)[:len(mode)] if mode in ("RGB", "RGBA") else 0).save(buf, fmt, **kw)
    return buf.getvalue()


def exif_jpeg(size=(40, 20)) -> bytes:
    """Exif の向き（6: 右に 90 度）の付いた JPEG。"""
    from PIL import Image
    im = Image.new("RGB", size, (200, 0, 0))
    exif = im.getexif()
    exif[0x0112] = 6
    buf = io.BytesIO()
    im.save(buf, "JPEG", exif=exif.tobytes())
    return buf.getvalue()


# ---------------------------------------------------------------------------- check_user_image
@pytest.mark.parametrize("data,fmt,size", [
    (image("PNG"), "png", (30, 20)),
    (image("PNG", "RGBA"), "png", (30, 20)),
    (image("GIF", "P"), "gif", (30, 20)),
    (image("JPEG"), "jpg", (30, 20)),
    (exif_jpeg(), "jpg", (40, 20)),           # 向きは直さない（読むのは保存されている幅×高さ）
])
def test_accepts_png_jpeg_gif_and_reads_size(data, fmt, size):
    assert check_user_image(data, "a.png") == (fmt, size)


def test_format_is_decided_by_content_not_extension():
    assert check_user_image(image("PNG"), "図1.jpg")[0] == "png"
    assert check_user_image(image("JPEG"), "fig01.gif")[0] == "jpg"


@pytest.mark.parametrize("data,what", [
    (image("PDF"), "PDF"), (image("TIFF"), "TIFF"), (image("BMP"), "BMP"), (image("WEBP"), "WebP"),
    (b"not an image at all", "分からない形式"),
])
def test_refuses_other_formats_with_reason(data, what):
    with pytest.raises(ValueError) as e:
        check_user_image(data, "図2.png")
    assert str(e.value) == (f"「図2.png」は PNG・JPEG・GIF の画像ではありません（中身は {what} です）。"
                            "図の部分を PNG か JPEG の画像にして入れてください。")


def test_refuses_empty_file():
    with pytest.raises(ValueError, match="「空.png」は中身が空（0 バイト）です。"):
        check_user_image(b"", "空.png")


# ---------------------------------------------------------------------------- match_names
def slots(*keys):
    return [SimpleNamespace(key=k, kind="table" if k.startswith("tab") else "fig") for k in keys]


SLOTS = slots("fig01-2", "fig03", "tab01", "img3fa9c2", "fig04", "fig04_2")


@pytest.mark.parametrize("name,key", [
    ("29_55_fig03.png", "fig03"), ("fig03.png", "fig03"), ("fig3.png", "fig03"), ("図3.png", "fig03"),
    ("Figure3.png", "fig03"), ("FIG3.JPG", "fig03"), ("ｆｉｇ３.png", "fig03"), ("図　３.png", "fig03"),
    ("fig1-2.png", "fig01-2"), ("表1.jpg", "tab01"), ("tab01.jpg", "tab01"), ("table1.jpg", "tab01"),
    ("img3fa9c2.png", "img3fa9c2"), ("fig04_2.png", "fig04_2"), ("fig04.png", "fig04"),
])
def test_match_names_aliases(name, key):
    assert match_names([name], SLOTS, "29_55") == ({key: name}, [], [])


def test_number_alias_needs_a_single_slot_with_that_number():
    """図4 が 2 つ（fig04・fig04_2）あるときは、番号からの別名（fig4・図4）を受け付けない（幹で指定してもらう）。"""
    assert match_names(["fig4.png", "図4.png"], SLOTS, "29_55") == ({}, ["fig4.png", "図4.png"], [])


def test_other_article_id_is_not_accepted():
    """記事識別子の付いた名前で、識別子がこの記事と違うものは合わない名前にする（別の論文のフォルダの使い回し）。"""
    found, unmatched, clashes = match_names(["29_44_fig03.png", "29_55_tab01.png", "fig9.png"], SLOTS, "29_55")
    assert found == {"tab01": "29_55_tab01.png"} and unmatched == ["29_44_fig03.png", "fig9.png"] and clashes == []


@pytest.mark.parametrize("aid", ["31_e5", "31_s1", "a1_2"])
def test_article_id_with_letters(aid):
    """英字を含む記事識別子（最初のページが e5・S1 など）でも、記事識別子つきの名前が合う。ほかの識別子の名前は合わない（点検 9）。"""
    upper = aid.upper()
    found, unmatched, clashes = match_names([f"{aid}_fig03.png", f"{upper}_tab01.png", "31_e6_img3fa9c2.png", "29_55_fig04.png"], SLOTS, aid)
    assert found == {"fig03": f"{aid}_fig03.png", "tab01": f"{upper}_tab01.png"}
    assert unmatched == ["31_e6_img3fa9c2.png", "29_55_fig04.png"] and clashes == []


def test_two_files_for_one_slot_are_returned_as_a_clash():
    found, unmatched, clashes = match_names(["fig3.png", "図3.jpg", "表1.png"], SLOTS, "29_55")
    assert found == {"tab01": "表1.png"} and unmatched == [] and clashes == [("fig03", ["fig3.png", "図3.jpg"])]


# ---------------------------------------------------------------------------- caption_body
def para(text):
    return Para(src="d1", atoms=[Atom(kind="text", text=text)])


@pytest.mark.parametrize("text,body", [
    ("図4　児童Aの記述", "児童Aの記述"), ("図４　児童Ａの記述", "児童Aの記述"), ("表1 架空の表", "架空の表"),
    ("図1-2　枝番の図", "枝番の図"), ("図1．2　点の枝番", "点の枝番"), ("Figure 3: An Example", "An Example"),
    ("（出典：架空の資料）", "(出典:架空の資料)"),
])
def test_caption_body_removes_the_number(text, body):
    assert caption_body(para(text)) == body


# ---------------------------------------------------------------------------- text_before・slot_where
@pytest.fixture(scope="module")
def where(tmp_path_factory, journal_module, meta_module):
    tmp = tmp_path_factory.mktemp("where")
    path = tmp / "where.docx"
    mf.make_where(path)
    res = convert(path, meta_module, journal_module, Options(out_dir=tmp / "out"))
    fid = res.fidelity
    assert fid.ok and fid.final_ok and res.dtd_valid and res.lost_images == [], (fid.missing, fid.conflicts)
    return res


@pytest.fixture(scope="module")
def journal_module():
    from jasme_jats.config import JournalConfig
    return JournalConfig.load()


@pytest.fixture(scope="module")
def meta_module():
    from jasme_jats.config import ArticleMeta
    return ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12", "pub_date": "2026-03-31",
                                  "received": "2025-06-01", "accepted": "2025-11-20", "peer_review": "あり"})


def heads(res, slot):
    h, p = text_before(res.plan, slot.src, slot)
    return (h.text_only() if h is not None else None, p.text_only()[:10] if p is not None else None)


def test_text_before_and_slot_where(where):
    """置き場所の場所の文（修正計画 W1 の 2.8）: 章の最初の画像だけの段落、空白だけの段落を飛ばした前の段落、行内の画像の段落の中、
    浮動の画像の結び付いた段落の後ろ、キャプションのある図は章だけ、図形から組んだ図（アンカー段落の前に置く）は前の段落の後ろ、
    付記の見出しの直後。"""
    res = where
    got = [(s.kind, s.place, heads(res, s), slot_where(res, s)) for s in res.plan.slots]
    sec1, sec2 = "章「１．場所の確かめ」", "章「２．図形の場所」"
    assert got == [
        ("nocap", "fig", ("１．場所の確かめ", None), f"{sec1}の最初"),
        ("nocap", "fig", ("１．場所の確かめ", "試験（2024）にな"), f"「試験（2024）にならい，画像の場所を確…」の段落の後ろ（{sec1}）"),
        ("nocap", "inline", ("１．場所の確かめ", "文の中に行内の画像が"), f"「文の中に行内の画像がある段落である。」の段落の中（{sec1}）"),
        ("nocap", "fig", ("１．場所の確かめ", "この段落に浮動の画像"), f"「この段落に浮動の画像が結び付いている。」の段落の後ろ（{sec1}）"),
        ("fig", "fig", ("１．場所の確かめ", "図1　児童Aの記述"), sec1),
        ("nocap", "fig", ("２．図形の場所", "図形の前にある本文の"), f"「図形の前にある本文の段落である。」の段落の後ろ（{sec2}）"),
        ("nocap", "inline", ("付記", None), "章「付記」の最初"),
    ]
    # 図形の中の段落（「点Ｐ」）は、場所の段落にしない。図形の置き場所は、図形の中身から組んだ図（plan_figures に段落として出ない）
    float_slot = res.plan.slots[5]
    assert float_slot.float_id and res.plan.floats[float_slot.float_id].mode == "mechanical"
    # 画像の置き場所の一覧の「場所」も同じ文（SlotImage.location）
    assert [i.location for i in res.images] == [g[3] for g in got]


def test_text_before_of_a_text_paragraph_is_itself(where):
    p = next(q for q in where.plan.paras.values() if q.text_only().startswith("試験（2024）にならい"))
    h, q = text_before(where.plan, p.src)
    assert q is p and h.text_only() == "１．場所の確かめ"


# ---------------------------------------------------------------------------- apply_images
def test_apply_images_sets_extension_removes_skipped_and_keeps_text(where, journal_module):
    """JPEG を入れると xlink:href が .jpg になる。「入れない」のキャプションなしの <fig> と <inline-graphic> は消え、後ろの文字は残り、
    XML の文字は変わらない。結果は DTD に合う。まだ入れていない置き場所はそのまま。"""
    from jasme_jats.pipeline import dtd_places
    from jasme_jats.validate import validate
    res = where
    imgs = [SlotImage(key=i.key, name=i.name, kind=i.kind) for i in res.images]
    by = {i.key: i for i in imgs}
    keys = [s.key for s in res.plan.slots]
    by["fig01"].status, by["fig01"].format = "user", "jpg"
    by[keys[0]].status = "skipped"                  # 章の最初の画像だけの段落（<fig><graphic/></fig>）
    by[keys[2]].status = "skipped"                  # 行内の画像（<inline-graphic>）
    out = apply_images(res.xml_base, imgs)
    root, base = etree.fromstring(out), etree.fromstring(res.xml_base)
    assert "".join(root.itertext()) == "".join(base.itertext())
    hrefs = [g.get(XLINK) for g in root.iter("graphic", "inline-graphic")]
    assert "31_1_fig01.jpg" in hrefs and "31_1_fig01.png" not in hrefs
    assert not any(keys[0] in h or keys[2] in h for h in hrefs)
    assert len(hrefs) == len(list(base.iter("graphic", "inline-graphic"))) - 2
    p = next(p for p in root.iter("p") if "".join(p.itertext()).startswith("文の中に"))
    assert "".join(p.itertext()) == "文の中に行内の画像がある段落である。"
    assert validate(out, dtd_places(res.plan))[0]
    # 変えるところがなければ、そのまま返す
    assert apply_images(res.xml_base, [SlotImage(key=i.key, name=i.name) for i in res.images]) == res.xml_base


def test_apply_images_removes_unused_optional_and_keeps_tail():
    xml = (b'<article xmlns:xlink="http://www.w3.org/1999/xlink"><body><p>\xe5\x89\x8d'
           b'<inline-graphic xlink:href="31_1_opt81b0d4.png"/>\xe5\xbe\x8c</p></body></article>')
    out = apply_images(xml, [SlotImage(key="opt81b0d4", name="31_1_opt81b0d4.png", kind="optional", status="unused")])
    root = etree.fromstring(out)
    assert root.find(".//inline-graphic") is None and root.find(".//p").text == "前後"


# ---------------------------------------------------------------------------- 変換の後に画像を入れる（手順 9）
def zip_bytes(res, name):
    with zipfile.ZipFile(res.zip_path) as z:
        return z.read(f"jasme/31/1/31_1/Graphics/{name}")


def test_user_images_go_into_zip_unchanged(where):
    """入れた画像は、Exif の向きつき JPEG・透過 PNG も、バイト列をそのまま ZIP に入れる（C085）。入れた後の XML で最終出力の
    再チェック・DTD・J-STAGE のチェックが合格し、図 1 つは 1 枚で済む。"""
    res = where
    keys = [i.key for i in res.images]
    jpeg, rgba = exif_jpeg(), image("PNG", "RGBA")
    add_images(res, {"fig01": ("図1.jpg", jpeg), keys[0]: ("透過.png", rgba)})
    assert zip_bytes(res, "31_1_fig01.jpg") == jpeg and zip_bytes(res, f"31_1_{keys[0]}.png") == rgba
    assert res.fidelity.final_ok and res.dtd_valid and res.jstage_issues == [] and res.zip_issues == []
    [step] = [a for a in actions(res) if a.key == "images"]
    assert not step.done and step.progress == f"あと {len(keys) - 2} 枚／全部で {len(keys)} 枚"
    fill_images(res)
    [step] = [a for a in actions(res) if a.key == "images"]
    assert step.done and not res.needs_action


def test_figure_with_two_images_needs_one_image(journal, meta, tmp_path):
    """docx で画像 2 枚（と枠の図形）の図は、置き場所 1 つ・要る画像 1 枚で、備考に「1 枚にまとめた画像を入れてください」。
    1 枚入れると手順は済む。"""
    path = tmp_path / "run_frame.docx"
    mf.make_figs(path, "run_frame")
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    [row] = image_rows(res)
    assert row.key == "fig01" and row.note == "docx ではこの図に画像 2 枚（1 枚にまとめた画像を入れてください）"
    [step] = [a for a in actions(res) if a.key == "images"]
    assert step.progress == "あと 1 枚／全部で 1 枚" and "（1 枚にまとめた" not in step.box_detail
    add_images(res, {"fig01": ("fig1.png", image("PNG"))})
    assert [a for a in actions(res) if a.key == "images"][0].done and not res.needs_action


def test_covers_note_counts_images_and_shapes():
    pic, shape = SimpleNamespace(shape_only=False), SimpleNamespace(shape_only=True)
    assert _covers_note(SimpleNamespace(covers=[pic])) == ""
    assert (_covers_note(SimpleNamespace(covers=[pic, pic, shape]))
            == "docx ではこの図に画像 2 枚と図形 1 個（1 枚にまとめた画像を入れてください）")
