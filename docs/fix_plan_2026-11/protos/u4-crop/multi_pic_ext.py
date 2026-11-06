"""1 つの drawing に pic が 2 つ（グループ図形）で、a:blip に a:extLst（Word が付ける useLocalDpi）があるときの大きさ。"""
import io, sys
from pathlib import Path
ROOT = Path("/home/user/jstgxmlcng_JASME")
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
from PIL import Image
import make_fixtures as mf
from jasme_jats.docx_reader import read_docx
EXT = ('<a:extLst><a:ext uri="{28A0092B-C50C-407E-A947-70E740481C1C}"><a14:useLocalDpi '
       'xmlns:a14="http://schemas.microsoft.com/office/drawing/2010/main" val="0"/></a:ext></a:extLst>')
def body(b):
    buf = io.BytesIO(); Image.new("RGB", (10, 10), "red").save(buf, "PNG")
    r1 = b.add_image("a.png", buf.getvalue()); r2 = b.add_image("b.png", buf.getvalue())
    g = mf.group(r1, 1000000, 800000, mf.para(mf.S["fig_cap"], "図1　検証"), 7001, 2000000, 2000000)
    pic2 = (f'<pic:pic><pic:nvPicPr><pic:cNvPr id="7100" name="図"/><pic:cNvPicPr/></pic:nvPicPr>'
            f'<pic:blipFill><a:blip r:embed="{r2}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="500000" cy="400000"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>')
    g = g.replace("<wps:wsp>", pic2 + "<wps:wsp>", 1)
    g = g.replace(f'<a:blip r:embed="{r1}"/>', f'<a:blip r:embed="{r1}">{EXT}</a:blip>')
    g = g.replace(f'<a:blip r:embed="{r2}"/>', f'<a:blip r:embed="{r2}">{EXT}</a:blip>')
    return [mf.para(mf.S["sec1"], "１．検証"), mf.para(mf.S["body"], "本文。", g)]
p = Path(__file__).parent / "multi-pic.docx"
mf.make_article(p, "検証", body)
print([(i.image_id, i.cx_emu, i.cy_emu) for i in read_docx(p).images])
