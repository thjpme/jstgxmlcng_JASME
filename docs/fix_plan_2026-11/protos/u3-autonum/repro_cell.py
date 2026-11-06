"""(6) 表のセルの Word の自動番号が XML に出ないことの再現（make_fixtures.make_article）。
python3 repro_cell.py [--proto]   --proto なら proto.install() を当てた後の出力も見る。"""
import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, "/home/user/jstgxmlcng_JASME/tests")
sys.path.insert(0, str(HERE))
import make_fixtures as mf
if "--proto" in sys.argv:
    import proto; proto.install()
from lxml import etree
from jasme_jats.config import ArticleMeta, JournalConfig
from jasme_jats.pipeline import Options, convert
S = mf.S
def parts(b):
    return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["tab_cap"], "表1　質問紙"),
            mf.table([[mf.cell(mf.list_item(S["body"], "番号付きの質問", num_id=7)), mf.cell("回答")],
                      [mf.cell([mf.list_item(S["body"], "二つ目の質問", num_id=7), mf.list_item(S["body"], "三つ目の質問", num_id=7)]),
                       mf.cell("回答")]]),
            mf.para(S["body"], "以上である。")]
out = HERE / ("cell_out_proto" if "--proto" in sys.argv else "cell_out")
out.mkdir(exist_ok=True)
path = out / "cell.docx"
mf.make_article(path, "セルの番号の検証", parts)
meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12", "pub_date": "2026-03-31",
                              "received": "2025-06-01", "accepted": "2025-11-20", "peer_review": "あり", "keywords": "a; b"})
res = convert(path, meta, JournalConfig.load(), Options(out_dir=out / "o", convert_metafiles=False))
root = etree.fromstring(res.xml_path.read_bytes().split(b"\n", 2)[2])
print("autonum:", [(p.src, p.autonum) for p in res.plan.paras.values() if p.autonum])
print("td:", [etree.tostring(td, encoding="unicode") for td in root.iter("td")])
print("fidelity", res.fidelity.ok, res.fidelity.final_ok, "dtd", res.dtd_valid, "generated", res.fidelity.generated, "needs_action", res.needs_action)
