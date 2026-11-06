"""設計どおりの crop_image の試作を、実際の原稿の切り取りのある画像に当てる（画像は scratchpad の proto/ に）。"""
import glob, io, zipfile
from pathlib import Path
from lxml import etree
from PIL import Image, JpegImagePlugin

A = "http://schemas.openxmlformats.org/drawingml/2006/main"; PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
class CropError(Exception): pass

def crop_box(size, crop):
    w, h = size; l, t, r, b = crop
    box = (round(w * l), round(h * t), w - round(w * r), h - round(h * b))
    if box[2] - box[0] < 1 or box[3] - box[1] < 1:
        raise CropError("empty")
    return box

def crop_image(data, fmt, crop):
    im = Image.open(io.BytesIO(data)); im.load()
    if getattr(im, "n_frames", 1) > 1: raise CropError("frames")
    if im.getexif().get(0x0112, 1) != 1: raise CropError("orientation")
    out = im.crop(crop_box(im.size, crop)); buf = io.BytesIO(); kw = {}
    for k in ("dpi", "icc_profile"):
        if k in im.info: kw[k] = im.info[k]
    if fmt == "JPEG":
        if getattr(im, "quantization", None): kw["qtables"] = im.quantization
        s = JpegImagePlugin.get_sampling(im) if im.format == "JPEG" else -1
        if s != -1: kw["subsampling"] = s
        if "exif" in im.info: kw["exif"] = im.info["exif"]
        if out.mode not in ("RGB", "L", "CMYK"): out = out.convert("RGB")
    out.save(buf, fmt, **kw)
    return buf.getvalue()

dst = Path(__file__).parent / "proto"; dst.mkdir(exist_ok=True)
for p in sorted(glob.glob("/home/user/jstgxmlcng_JASME/tests/private/テストデータ[35]/*.docx")):
    z = zipfile.ZipFile(p); root = etree.fromstring(z.read("word/document.xml"))
    rels = {r.get("Id"): r.get("Target") for r in etree.fromstring(z.read("word/_rels/document.xml.rels"))}
    for k, pic in enumerate(root.iter(f"{{{PIC}}}pic")):
        sr = pic.find(f".//{{{A}}}srcRect")
        if sr is None or all(sr.get(c, "0") == "0" for c in "ltrb"): continue
        crop = tuple(max(0, int(sr.get(c, "0"))) / 100000 for c in "ltrb")
        rid = pic.find(f".//{{{A}}}blip").get(f"{{{R}}}embed"); data = z.read("word/" + rels[rid])
        res = crop_image(data, "PNG", crop); im = Image.open(io.BytesIO(res)); src = Image.open(io.BytesIO(data))
        name = f"{Path(p).parent.name}_{k}.png"; (dst / name).write_bytes(res)
        print(Path(p).parent.name, "src", src.size, src.mode, src.info.get("dpi"), "->", im.size, im.mode, im.info.get("dpi"), len(data), "->", len(res))
