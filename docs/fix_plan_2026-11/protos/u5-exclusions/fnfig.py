"""注の節の図（画像の段落＋図キャプション）と、セルに画像のある注の表。"""
import sys
from pathlib import Path
ROOT=Path("/home/user/jstgxmlcng_JASME")
sys.path[:0]=[str(ROOT/"src"), str(ROOT/"tests")]
import make_fixtures as mf
from lxml import etree
from jasme_jats.config import ArticleMeta, JournalConfig
from jasme_jats.pipeline import Options, convert
from jasme_jats.report import actions
j=JournalConfig.load(); meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12"})
W=Path(__file__).parent/"work"
def body(b):
    rid=b.add_image("fnfig.png", mf.png_bytes("fn fig"))
    rid2=b.add_image("fncell.png", mf.png_bytes("fn cell"))
    return [mf.para(mf.S["sec1"], "１．検証"), mf.para(mf.S["body"], "本文。"),
            mf.para(mf.S["fn_head"], "注"), mf.para(mf.S["fn_body"], "1) 注の本文。"),
            mf.para(mf.S["body"], mf.drawing(rid, 1800000, 1000000, 801)), mf.para(mf.S["fig_cap"], "図1　注の図"),
            mf.table([[mf.cell(mf.para(mf.S["body"], mf.drawing(rid2, 900000, 500000, 802))), mf.cell("x")]])]
p=W/"fnfig.docx"; mf.make_article(p, "注の図の検証", body)
res=convert(p, meta, j, Options(out_dir=W/"fnfig", convert_metafiles=False))
print("ok",res.ok,[(a.level,a.key) for a in actions(res)], "lost",[(l.image_id,l.src) for l in res.lost_images],
      "excl",[(e.src,e.reason[:12]) for e in res.plan.exclusions if not e.blank])
