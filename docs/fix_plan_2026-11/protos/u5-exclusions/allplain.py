"""英文の部分のスタイルをすべて外した原稿（K12 の「本文がすべて標準スタイル」）。"""
import sys, zipfile
from pathlib import Path
ROOT=Path("/home/user/jstgxmlcng_JASME")
sys.path[:0]=[str(ROOT/"src"), str(ROOT/"tests")]
from lxml import etree
import make_fixtures as mf
from jasme_jats.config import ArticleMeta, JournalConfig
from jasme_jats.pipeline import Options, convert
from jasme_jats.report import actions
j=JournalConfig.load(); meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12"})
W=Path(__file__).parent/"work"; Wn="{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
orig=W/"b_orig.docx"
def change(data):
    root=etree.fromstring(data)
    body=root.find(Wn+"body")
    seen=False
    for el in body.iter(Wn+"p"):
        t="".join(el.itertext())
        if t=="A Small Article": seen=True
        if seen:
            ps=el.find(Wn+"pStyle", ) if False else el.find(Wn+"pPr")
            if ps is not None:
                st=ps.find(Wn+"pStyle")
                if st is not None: ps.remove(st)
    return etree.tostring(root)
dst=W/"b4_all_plain.docx"
with zipfile.ZipFile(orig) as zi, zipfile.ZipFile(dst,"w") as zo:
    for e in zi.infolist():
        d=zi.read(e.filename)
        if e.filename=="word/document.xml": d=change(d)
        zo.writestr(e,d)
res=convert(dst, meta, j, Options(out_dir=W/"b4", convert_metafiles=False))
print("ok",res.ok,[(a.level,a.key) for a in actions(res)], "refs",len(res.plan.refs), "abstract",len(res.plan.abstract),"title_en",len(res.plan.title_en),
      "excl",[(e.src,e.reason[:15]) for e in res.plan.exclusions if not e.blank])
