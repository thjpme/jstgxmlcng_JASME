"""u4-crop の再現: Word のトリミング（a:srcRect / v:imagedata の crop*）が出力に反映されない。"""
import io
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path("/home/user/jstgxmlcng_JASME")
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
from lxml import etree
from PIL import Image
import make_fixtures as mf
from jasme_jats.config import ArticleMeta, JournalConfig
from jasme_jats.pipeline import convert, Options
from jasme_jats.report import actions
from jasme_jats.docx_reader import read_docx

WORK = Path(__file__).parent
journal = JournalConfig.load()
meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12"})


def out(label, **v):
    print(label, json.dumps(v, ensure_ascii=False, default=str))


def two_tone(fmt="PNG", size=(200, 100)):
    im = Image.new("RGB", size, "red")
    im.paste("blue", (size[0] // 2, 0, size[0], size[1]))
    buf = io.BytesIO()
    im.save(buf, fmt)
    return buf.getvalue()


def simple():
    return [mf.para(mf.S["sec1"], "１．検証"), mf.para(mf.S["body"], "これは検証用の本文です。")]


def run(label, pic_xml_fn, media_name="cropped.png", fmt="PNG"):
    def body(b):
        rid = b.add_image(media_name, two_tone(fmt))
        return simple() + [mf.para(mf.S["body"], pic_xml_fn(rid)), mf.para(mf.S["fig_cap"], "図1　検証の画像")]
    path = WORK / f"{label}.docx"
    mf.make_article(path, "トリミングの検証", body)
    res = convert(path, meta, journal, Options(out_dir=WORK / f"{label}-out", convert_metafiles=False))
    img = res.images[0]
    with zipfile.ZipFile(res.zip_path) as z:
        name = next(n for n in z.namelist() if n.endswith("/" + img.name))
        im = Image.open(io.BytesIO(z.read(name)))
        im.load()
    doc = read_docx(path)
    out(label, ok=res.ok, needs_action=res.needs_action, actions=[a.key for a in actions(res)],
        status=img.status, name=img.name, size=im.size, px00=im.getpixel((0, 0)),
        imageref_fields=sorted(vars(doc.images[0]).keys()))


def drawing_crop(rid):
    return mf.drawing(rid, 1800000, 1800000, 6501).replace(
        "<a:stretch>", '<a:srcRect l="50000" t="0" r="0" b="0"/><a:stretch>')


def drawing_crop_jpeg(rid):
    return drawing_crop(rid)


def vml_crop(rid):
    return (f'<w:r><w:pict><v:shape style="width:100pt;height:100pt"><v:imagedata r:id="{rid}" o:title="" '
            f'cropleft="32768f"/></v:shape></w:pict></w:r>')


run("drawing-png", drawing_crop)
run("drawing-jpg", drawing_crop_jpeg, media_name="cropped.jpeg", fmt="JPEG")
run("vml-png", vml_crop)
