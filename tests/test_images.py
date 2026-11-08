"""Word でトリミングした画像の切り取り（images.crop_image・export_images）と、反映しない加工の知らせ（image_crop・image_edits）。

Word のトリミングは画像ファイルを変えず、表示のときに a:srcRect（VML は v:imagedata の crop*）の割合で切り取るだけなので、
docx の画像は切り取る前のもの。切り取って出力し（要確認）、切り取れない画像は ZIP に入れず用意が必要な画像（要対応）にする。
"""
import io
import struct
import zipfile

import pytest
from PIL import Image

import make_fixtures as mf
from jasme_jats import images
from jasme_jats.images import CropError, crop_box, crop_image, crop_text
from jasme_jats.package import zip_image_names
from jasme_jats.pipeline import Options, add_images, convert
from jasme_jats.report import STEP_NAMES, actions, images_action, images_to_prepare

S = mf.S


def keys(res):
    return [a.key for a in actions(res)]


def simple(b):
    return [mf.para(S["sec1"], "１．検証"), mf.para(S["body"], "これは検証用の本文です。")]


def one_image(name, data, **kw):
    """図のキャプションのある画像 1 枚の論文（media 名は name）。"""
    def body(b):
        rid = b.add_image(name, data)
        return simple(b) + [mf.para(S["body"], mf.drawing(rid, 1800000, 1000000, 600, **kw)),
                            mf.para(S["fig_cap"], "図1　検証の図")]
    return body


def make(tmp_path, body, name="a.docx"):
    path = tmp_path / name
    mf.make_article(path, "切り取りの検証", body)
    return path


def run(tmp_path, body, journal, meta, **opts):
    out = tmp_path / "out"
    return convert(make(tmp_path, body), meta, journal, Options(out_dir=out, convert_metafiles=False, **opts))


def zip_member(res, tail):
    with zipfile.ZipFile(res.zip_path) as z:
        names = [n for n in z.namelist() if n.endswith(tail)]
        return z.read(names[0]) if names else None


def exif_jpeg(orientation=1, size=(200, 100), thumb=None):
    """Exif の向きと、IFD1 に縮小画像（thumb）のある JPEG（review-u4-crop/exp3.py の組み方）。"""
    tb = thumb or b""
    ifd0_off = 8
    ifd0 = struct.pack("<H", 1) + struct.pack("<HHII", 0x0112, 3, 1, orientation)
    tiff = b"II*\x00" + struct.pack("<I", ifd0_off) + ifd0
    if tb:
        ifd1_off = ifd0_off + len(ifd0) + 4
        thumb_off = ifd1_off + 2 + 12 * 2 + 4
        ifd1 = (struct.pack("<H", 2) + struct.pack("<HHII", 0x0201, 4, 1, thumb_off)
                + struct.pack("<HHII", 0x0202, 4, 1, len(tb)) + struct.pack("<I", 0))
        tiff += struct.pack("<I", ifd1_off) + ifd1 + tb
    else:
        tiff += struct.pack("<I", 0)
    img = Image.new("RGB", size, "red")
    img.paste("blue", (size[0] // 2, 0, size[0], size[1]))
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=b"Exif\x00\x00" + tiff)
    return buf.getvalue()


# ----------------------------------------------------------------------------- 部品
def test_crop_box_rounds_and_rejects_empty():
    assert crop_box((200, 100), (0.5, 0, 0, 0)) == (100, 0, 200, 100)
    x0, y0, x1, y1 = crop_box((590, 438), (0.04329, 0.03646, 0.05032, 0.04839))
    assert (x1 - x0, y1 - y0) == (534, 401)
    with pytest.raises(CropError):
        crop_box((200, 100), (0.6, 0, 0.5, 0))


def test_crop_text():
    assert crop_text((0.5, 0, 0.1, 0)) == "左 50.0%・右 10.0%"


def test_crop_image_png_keeps_transparency_and_dpi():
    im = Image.new("P", (40, 20), 1)
    im.putpalette([0, 0, 0, 255, 0, 0] + [0] * 250 * 3)
    buf = io.BytesIO()
    im.save(buf, "PNG", transparency=0, dpi=(300, 300))
    out, _, size = crop_image(buf.getvalue(), "PNG", (0.25, 0, 0, 0))
    got = Image.open(io.BytesIO(out))
    assert size == (30, 20) and got.size == (30, 20) and got.mode == "P" and got.info["transparency"] == 0
    assert abs(got.info["dpi"][0] - 300) < 1
    buf = io.BytesIO()
    Image.new("RGBA", (40, 20), (1, 2, 3, 4)).save(buf, "PNG")
    assert Image.open(io.BytesIO(crop_image(buf.getvalue(), "PNG", (0.25, 0, 0, 0))[0])).mode == "RGBA"


def test_crop_image_png_16bit_and_alpha_modes():
    def png(mode, **kw):
        buf = io.BytesIO()
        Image.new(mode, (40, 20)).save(buf, "PNG", **kw)
        return buf.getvalue()

    for mode in ("I;16", "LA"):
        out = crop_image(png(mode), "PNG", (0.25, 0, 0, 0))[0]
        assert Image.open(io.BytesIO(out)).mode == mode
    # PA は PNG に書けない形式なので、メモリ上で作って PNG にできる RGBA を通して確かめる
    pa = Image.new("PA", (40, 20), (5, 128))
    buf = io.BytesIO()
    pa.convert("RGBA").save(buf, "PNG")
    out = crop_image(buf.getvalue(), "PNG", (0.25, 0, 0, 0))[0]
    assert Image.open(io.BytesIO(out)).mode == "RGBA"
    # PA で開いた画像を直接切り取る経路（out.mode が PNG の形式でない → RGBA）
    cropped = pa.crop((10, 0, 40, 20))
    assert "A" in cropped.mode and cropped.mode not in images._PNG_MODES


def test_crop_image_jpeg_reuses_quantization():
    data = mf.two_tone("JPEG", quality=70)
    out, _, size = crop_image(data, "JPEG", (0.5, 0, 0, 0))
    got, src = Image.open(io.BytesIO(out)), Image.open(io.BytesIO(data))
    assert got.format == "JPEG" and size == (100, 100)
    assert all(abs(a - b) <= 10 for a, b in zip(got.convert("RGB").getpixel((50, 50)), (0, 0, 255)))
    assert got.quantization == src.quantization


def test_crop_image_drops_exif_thumbnail():
    tb = io.BytesIO()
    Image.new("RGB", (16, 8), (200, 10, 10)).save(tb, "JPEG")
    data = exif_jpeg(1, thumb=tb.getvalue())
    assert tb.getvalue() in data
    out, _, _ = crop_image(data, "JPEG", (0.5, 0, 0, 0))
    assert tb.getvalue() not in out


def test_crop_image_rejects_exif_orientation_and_frames():
    with pytest.raises(CropError):
        crop_image(exif_jpeg(6), "JPEG", (0.5, 0, 0, 0))
    frames = [Image.new("RGB", (20, 10), "red"), Image.new("RGB", (20, 10), "blue")]
    buf = io.BytesIO()
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:])
    with pytest.raises(CropError):
        crop_image(buf.getvalue(), "GIF", (0.5, 0, 0, 0))


def test_crop_image_unreadable_is_crop_error():
    with pytest.raises(CropError):
        crop_image(b"not an image", "PNG", (0.5, 0, 0, 0))


# ----------------------------------------------------------------------------- 変換
def test_convert_crops_word_trimmed_png(journal, meta, tmp_path):
    res = run(tmp_path, one_image("a.png", mf.two_tone(), src_rect='l="50000"'), journal, meta)
    im = Image.open(io.BytesIO(zip_member(res, "Graphics/31_1_01.png")))
    assert im.size == (100, 100) and im.convert("RGB").getpixel((0, 0)) == (0, 0, 255)
    r = res.images[0]
    assert r.status == "converted" and r.crop == (0.5, 0, 0, 0)
    xml = res.xml_path.read_text(encoding="utf-8")
    assert 'xlink:href="31_1_01.png"' in xml
    assert "image_crop" in keys(res) and not res.needs_action
    report = res.report_path.read_text(encoding="utf-8")
    assert "切り取った" in report.split("## 9.")[1].split("## 10.")[0]


def test_convert_crops_jpeg_keeps_jpg_name(journal, meta, tmp_path):
    res = run(tmp_path, one_image("a.jpeg", mf.two_tone("JPEG"), src_rect='l="50000"'), journal, meta)
    assert res.images[0].name == "31_1_01.jpg"
    im = Image.open(io.BytesIO(zip_member(res, "Graphics/31_1_01.jpg")))
    assert im.format == "JPEG" and im.size == (100, 100)


def test_exif_orientation_zero_is_cropped(journal, meta, tmp_path):
    res = run(tmp_path, one_image("a.jpg", exif_jpeg(0), src_rect='l="50000"'), journal, meta)
    assert res.images[0].status == "converted"


def test_convert_uncroppable_goes_to_prepare(journal, meta, tmp_path):
    res = run(tmp_path, one_image("a.jpg", exif_jpeg(6), src_rect='l="50000"'), journal, meta)
    r = res.images[0]
    assert r.status == "failed" and r.name == "31_1_01.jpg"
    assert r.name not in zip_image_names(res.images)
    assert zip_member(res, "Graphics/31_1_01.jpg") is None
    assert not list((tmp_path / "out").glob("jasme/**/Graphics/31_1_01.jpg"))
    keep = tmp_path / "out" / "要変換" / "31_1_01.jpg"
    assert keep.exists() and Image.open(keep).size == (200, 100)
    need = images_to_prepare(res)
    assert [n for n, _, _ in need] == ["31_1_01.jpg"] and "切り取れなかった" in need[0][2]
    assert "images" in keys(res) and res.needs_action
    buf = io.BytesIO()
    Image.new("RGB", (50, 50), "green").save(buf, "PNG")
    add_images(res, {"31_1_01.jpg": buf.getvalue()})
    assert res.images[0].status == "user"
    assert "image_crop" not in keys(res)


def test_crop_save_error_becomes_failed(journal, meta, tmp_path, monkeypatch):
    real = Image.Image.save

    def boom(self, fp, format=None, **params):
        if format == "PNG" and self.size == (100, 100):
            raise OSError("disk full")
        return real(self, fp, format, **params)

    monkeypatch.setattr(Image.Image, "save", boom)
    res = run(tmp_path, one_image("a.png", mf.two_tone(), src_rect='l="50000"'), journal, meta)
    assert res.images[0].status == "failed"
    assert (tmp_path / "out" / "要変換" / "31_1_01.png").exists()


def test_subpixel_crop_is_noop(journal, meta, tmp_path):
    data = mf.two_tone(size=(100, 100))
    res = run(tmp_path, one_image("a.png", data, src_rect='l="100"'), journal, meta)
    r = res.images[0]
    assert r.status == "ok" and r.crop is None and zip_member(res, "Graphics/31_1_01.png") == data
    assert "image_crop" not in keys(res)


def test_convert_metafile_with_crop_is_not_cropped(journal, meta, tmp_path):
    res = run(tmp_path, one_image("a.emf", b"\x01\x00\x00\x00dummy-emf", src_rect='l="50000"'), journal, meta)
    r = res.images[0]
    assert r.status == "failed" and "切り取った図" in r.message
    assert zip_member(res, "Graphics/31_1_01.png") is None


@pytest.mark.skipif(images.soffice_path() is None, reason="LibreOffice がない")
def test_convert_converted_metafile_with_crop_goes_to_prepare(journal, meta, tmp_path):
    from conftest import TEMPLATE
    emf = zipfile.ZipFile(TEMPLATE).read("word/media/" + next(
        n.rsplit("/", 1)[-1] for n in zipfile.ZipFile(TEMPLATE).namelist() if n.endswith(".emf")))
    out = tmp_path / "out"
    res = convert(make(tmp_path, one_image("a.emf", emf, src_rect='l="50000"')), meta, journal, Options(out_dir=out))
    r = res.images[0]
    assert r.status == "failed" and "当てはめられない" in r.message
    assert zip_member(res, "Graphics/31_1_01.png") is None
    assert (out / "要変換" / "31_1_01.png").exists()


def test_convert_rotated_image_is_reported(journal, meta, tmp_path):
    data = mf.two_tone()
    res = run(tmp_path, one_image("a.png", data, xfrm=' rot="5400000"'), journal, meta)
    r = res.images[0]
    assert r.status == "ok" and r.edits == ("回転",) and zip_member(res, "Graphics/31_1_01.png") == data
    acts = {a.key: a for a in actions(res)}
    assert "image_edits" in acts
    import re
    from jasme_jats.report import STEP_MARK_PATTERN
    used = re.findall(STEP_MARK_PATTERN, acts["image_edits"].box_detail)
    assert used and all(n in STEP_NAMES for n in used)
    assert not re.findall(STEP_MARK_PATTERN, acts["image_edits"].top)


def test_image_crop_comes_before_image_edits(journal, meta, tmp_path):
    res = run(tmp_path, one_image("a.png", mf.two_tone(), src_rect='l="50000"', xfrm=' rot="5400000"'), journal, meta)
    k = keys(res)
    assert "image_crop" in k and "image_edits" in k and k.index("image_crop") < k.index("image_edits")


def test_uncroppable_jpeg_images_action_text(journal, meta, tmp_path):
    res = run(tmp_path, one_image("a.jpg", exif_jpeg(6), src_rect='l="50000"'), journal, meta)
    a = images_action(res)
    assert ".jpg は JPEG" in a.top and "画像（PNG）を作り" not in a.top
    assert a.box_detail.startswith("Word の図形で描かれた図や、変換・切り取りができなかった画像は")


# ----------------------------------------------------------------------------- AI
def ai_body(name, data, **kw):
    def body(b):
        rid = b.add_image(name, data)
        return simple(b) + [mf.para(S["body"], mf.drawing(rid, 1800000, 1000000, 600, **kw))]
    return body


def test_ai_images_are_cropped(journal, meta, tmp_path):
    res = run(tmp_path, ai_body("a.png", mf.two_tone(), src_rect='l="50000"'), journal, meta, ai_mode="manual")
    p = tmp_path / "out" / "AI添付画像" / "img1.png"
    assert Image.open(p).size == (100, 100)


def test_ai_skips_uncroppable_image(journal, meta, tmp_path):
    res = run(tmp_path, ai_body("a.jpg", exif_jpeg(6), src_rect='l="50000"'), journal, meta, ai_mode="manual")
    assert not (tmp_path / "out" / "AI添付画像" / "img1.jpg").exists()
    from jasme_jats.ai_assist import image_blocks
    from jasme_jats.docx_reader import read_docx
    doc = read_docx(tmp_path / "a.docx")
    assert image_blocks(doc, doc.images) == []
