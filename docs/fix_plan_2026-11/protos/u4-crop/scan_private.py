"""tests/private の docx の画像の切り取り・回転・反転・効果を数える（本文の文字は出さない）。"""
import io
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path("/home/user/jstgxmlcng_JASME")
sys.path[:0] = [str(ROOT / "src")]
from lxml import etree
from PIL import Image

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"
V = "urn:schemas-microsoft-com:vml"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
EFFECTS = ("duotone", "grayscl", "biLevel", "alphaModFix", "clrChange", "lum", "hsl", "tint", "alphaBiLevel",
           "alphaCeiling", "alphaFloor", "alphaInv", "alphaMod", "alphaRepl", "blur", "clrRepl", "fillOverlay")

PARTS = ("word/document.xml", "word/footnotes.xml", "word/endnotes.xml")
out_dir = Path(__file__).parent / "private-crops"
out_dir.mkdir(exist_ok=True)

for path in sorted(p for p in (ROOT / "tests/private").rglob("*.docx") if "review-repros" not in p.parts):
    folder = path.parent.name
    z = zipfile.ZipFile(path)
    c = Counter()
    media = Counter(Path(n).suffix.lower() for n in z.namelist() if n.startswith("word/media/"))
    for part in PARTS:
        if part not in z.namelist():
            continue
        root = etree.fromstring(z.read(part))
        rels_name = part.replace("word/", "word/_rels/") + ".rels"
        rels = {}
        if rels_name in z.namelist():
            for rel in etree.fromstring(z.read(rels_name)):
                rels[rel.get("Id")] = rel.get("Target")
        for pic in root.iter(f"{{{PIC}}}pic"):
            c["pic"] += 1
            sr = pic.find(f".//{{{A}}}srcRect")
            if sr is not None and any(sr.get(k) not in (None, "0") for k in "ltrb"):
                c["srcRect(nonzero)"] += 1
                vals = {k: int(sr.get(k, "0")) for k in "ltrb"}
                if any(v < 0 for v in vals.values()):
                    c["srcRect(negative)"] += 1
                blip = pic.find(f".//{{{A}}}blip")
                rid = blip.get(f"{{{R}}}embed")
                target = "word/" + rels.get(rid, "")
                try:
                    im = Image.open(io.BytesIO(z.read(target)))
                    w, h = im.size
                    box = (round(w * vals["l"] / 100000), round(h * vals["t"] / 100000),
                           w - round(w * vals["r"] / 100000), h - round(h * vals["b"] / 100000))
                    print(folder, path.name[:6], "crop", Path(target).suffix, im.mode, (w, h), vals, "->",
                          (box[2] - box[0], box[3] - box[1]), "exif-orient", im.getexif().get(0x0112))
                    if all(v >= 0 for v in vals.values()):
                        im.crop(box).save(out_dir / f"{folder}_{c['srcRect(nonzero)']}.png")
                except Exception as e:  # noqa: BLE001
                    print(folder, "crop-read-failed", target, type(e).__name__)
            elif sr is not None:
                c["srcRect(all-zero)"] += 1
            if pic.find(f".//{{{A}}}fillRect") is not None and any(pic.find(f".//{{{A}}}fillRect").get(k) for k in "ltrb"):
                c["fillRect(nonzero)"] += 1
            if pic.find(f".//{{{A}}}tile") is not None:
                c["tile"] += 1
            xfrm = pic.find(f"{{{PIC}}}spPr/{{{A}}}xfrm")
            if xfrm is not None:
                if xfrm.get("rot") not in (None, "0"):
                    c["rot"] += 1
                if xfrm.get("flipH") in ("1", "true"):
                    c["flipH"] += 1
                if xfrm.get("flipV") in ("1", "true"):
                    c["flipV"] += 1
            blip = pic.find(f".//{{{A}}}blip")
            if blip is not None:
                for ch in blip.iter():
                    ln = etree.QName(ch).localname if isinstance(ch.tag, str) else ""
                    if ln in EFFECTS:
                        c[f"effect:{ln}"] += 1
                    if ln == "imgProps" or ln == "imgEffect":
                        c[f"a14:{ln}"] += 1
                for ext in blip.iter(f"{{{A}}}ext"):
                    c[f"blip-ext:{ext.get('uri')}"] += 1
            # pic:pic の外側（グループ）
            anc = [etree.QName(a).localname for a in pic.iterancestors()]
            if "wgp" in anc or "grpSp" in anc:
                c["pic-in-group"] += 1
            if "wpc" in anc:
                c["pic-in-canvas"] += 1
        for d in root.iter(f"{{{V}}}imagedata"):
            c["v:imagedata"] += 1
            if any(d.get(k) for k in ("cropleft", "croptop", "cropright", "cropbottom")):
                c["vml-crop"] += 1
        for sh in root.iter(f"{{{V}}}shape"):
            if "rotation" in (sh.get("style") or "") or "flip" in (sh.get("style") or ""):
                c["vml-rot/flip"] += 1
        # 1 つの w:drawing に pic が複数
        for d in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}drawing"):
            n = sum(1 for _ in d.iter(f"{{{PIC}}}pic"))
            if n > 1:
                c["drawing-with-multi-pic"] += 1
    print(folder, path.name[:6], dict(c), "media", dict(media))
