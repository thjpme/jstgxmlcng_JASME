"""切り取り後の保存で、形式ごとの情報（JPEG の量子化表・サブサンプリング、PNG の透過・dpi）が残るか。"""
import io
from PIL import Image, JpegImagePlugin

def jpg(mode, **kw):
    im = Image.new(mode, (64, 32), (200, 10, 10) if mode == "RGB" else (0, 200, 200, 0) if mode == "CMYK" else 100)
    b = io.BytesIO(); im.save(b, "JPEG", quality=70, dpi=(300, 300), **kw); return b.getvalue()

for mode in ("RGB", "L", "CMYK"):
    src = Image.open(io.BytesIO(jpg(mode)))
    c = src.crop((16, 0, 64, 32))
    try:
        c.save(io.BytesIO(), "JPEG", quality="keep")
        keep = "ok"
    except Exception as e:
        keep = type(e).__name__ + ":" + str(e)
    b = io.BytesIO()
    c.save(b, "JPEG", qtables=src.quantization, subsampling=JpegImagePlugin.get_sampling(src),
           dpi=src.info.get("dpi"), icc_profile=src.info.get("icc_profile"), exif=src.info.get("exif", b""))
    out = Image.open(io.BytesIO(b.getvalue()))
    print(mode, "keep:", keep, "| out", out.mode, out.size, "dpi", out.info.get("dpi"),
          "same qtables", out.quantization == src.quantization, "px", out.getpixel((0, 0)), "src px", src.getpixel((16, 0)))

# PNG: P + transparency, RGBA, LA, I;16, dpi
for mode in ("P", "RGBA", "LA", "I;16", "1"):
    im = Image.new(mode if mode != "P" else "P", (40, 20))
    info = {}
    if mode == "P":
        im.putpalette([255, 0, 0, 0, 0, 255] + [0] * 762); info["transparency"] = 0
    b = io.BytesIO(); im.save(b, "PNG", dpi=(300, 300), **info)
    src = Image.open(io.BytesIO(b.getvalue()))
    c = src.crop((10, 0, 40, 20))
    o = io.BytesIO(); c.save(o, "PNG", dpi=src.info.get("dpi"))
    out = Image.open(io.BytesIO(o.getvalue()))
    print("PNG", mode, out.mode, out.size, "transparency", out.info.get("transparency"), "dpi", out.info.get("dpi"))

# GIF transparency / animation
fr = [Image.new("P", (20, 10), i) for i in range(2)]
b = io.BytesIO(); fr[0].save(b, "GIF", save_all=True, append_images=fr[1:], transparency=0)
src = Image.open(io.BytesIO(b.getvalue()))
print("GIF n_frames", getattr(src, "n_frames", 1), "transparency", src.info.get("transparency"))
c = src.crop((5, 0, 20, 10)); o = io.BytesIO(); c.save(o, "GIF")
out = Image.open(io.BytesIO(o.getvalue())); print("GIF out", out.size, getattr(out, "n_frames", 1), out.info.get("transparency"))

# EXIF orientation
im = Image.new("RGB", (40, 20), "red"); ex = Image.Exif(); ex[0x0112] = 6
b = io.BytesIO(); im.save(b, "JPEG", exif=ex.tobytes()); print("exif orient", Image.open(io.BytesIO(b.getvalue())).getexif().get(0x0112))
