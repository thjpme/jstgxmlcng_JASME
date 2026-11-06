import sys, zipfile
from pathlib import Path
HERE = Path(__file__).resolve().parent
REPO = Path("/home/user/jstgxmlcng_JASME")
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(HERE.parent / "u3-autonum"))
import make_fixtures as mf
from lxml import etree
import proto
proto.install()
from jasme_jats import builder as B
from jasme_jats.config import ArticleMeta, JournalConfig
from jasme_jats.pipeline import Options, convert
from jasme_jats.tracking import GEN, SPAN
S, W = mf.S, mf.W
def body(b):
    return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "本文の文である。", mf.footnote_ref(5)),
            mf.table([[mf.cell(mf.para(S["body"], " 先頭が空白のセル")), mf.cell("回答")]])]
path = HERE / "fn_first.docx"
mf.make_article(path, "題目", body, footnotes=[mf.footnote(5, "脚注の一段落目。")])
# footnotes.xml の id=5 の 1 段落目に numPr
tmp = path.with_suffix(".t.docx")
with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w") as zout:
    for it in zin.infolist():
        data = zin.read(it.filename)
        if it.filename == "word/footnotes.xml":
            root = etree.fromstring(data)
            for fn in root.iter(f"{{{W}}}footnote"):
                if fn.get(f"{{{W}}}id") == "5":
                    p = fn.find(f"{{{W}}}p"); ppr = p.find(f"{{{W}}}pPr")
                    ppr.append(etree.fromstring(f'<w:numPr xmlns:w="{W}"><w:ilvl w:val="0"/><w:numId w:val="7"/></w:numPr>'))
            data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
        zout.writestr(it, data)
tmp.replace(path)
trees=[]
import jasme_jats.pipeline as P
ob=B.build
def spy(*a,**k):
    r,i=ob(*a,**k); trees.append(r); return r,i
P.build=spy
meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12", "pub_date": "2026-03-31","received": "2025-06-01", "accepted": "2025-11-20", "peer_review": "あり","keywords": "proof; 論証"})
res = convert(path, meta, JournalConfig.load(), Options(out_dir=HERE/"o", convert_metafiles=False))
print(res.fidelity.ok, res.fidelity.final_ok, res.dtd_valid)
from jasme_jats.builder import finalize
f = finalize(trees[-1])
for fn in f.iter("fn"):
    print(repr("".join(fn.itertext())))
print([(g.get("kind"), g.get("src"), g.text) for g in trees[-1].iter(GEN)])
print(proto.lost_autonums(res.plan, trees[-1]))
