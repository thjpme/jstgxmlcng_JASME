import sys, time
sys.path.insert(0, "/home/user/jstgxmlcng_JASME/tests")
import make_fixtures as mf
from pathlib import Path
from lxml import etree
from jasme_jats.config import ArticleMeta, JournalConfig
from jasme_jats.pipeline import Options, convert
S = mf.S
def doc(path, bare_list):
    b = mf.Builder()
    body = mf.front_ja(b, "架空の検証論文", "―副題―", [("架空大学", "試験　太郎")])
    body.append(mf.para(S["sec1"], "１．はじめに"))
    body.append(mf.para(S["body"], "架空の主張である", mf.run("1", sup=True), "。面積は 4 m", mf.run("2", sup=True), "である。"))
    body.append(mf.para(S["fn_head"], "注"))
    if bare_list:
        body.append(mf.para(S["body"], mf.run("1", sup=True), "　一つ目の架空の注。"))
        body.append(mf.para(S["body"], mf.run("2", sup=True), "　二つ目の架空の注。"))
    else:
        body.append(mf.para(S["body"], "1) 一つ目の架空の注。"))
        body.append(mf.para(S["body"], "2) 二つ目の架空の注。"))
    body.append(mf.para(S["ref_head"], "引用および参考文献"))
    body.append(mf.para(S["ref"], "試験太郎（2020）．「架空の論考」．『架空誌』，第1巻，pp.1-2．"))
    body += mf.front_en(b, "A Fictional Paper", "Sub", [("Taro SHIKEN", "Fictional University")], ["Fictional abstract."])
    body += mf.tail(b)
    b.save(path, body)
j = JournalConfig.load(); meta = ArticleMeta.load(Path("/home/user/jstgxmlcng_JASME/examples/meta_example.toml"))
for bl in (True, False):
    p = Path(f"p_{bl}.docx"); doc(p, bl)
    t=time.time()
    res = convert(p, meta, j, Options(out_dir=Path(f"o_{bl}"), ai_mode="manual", convert_metafiles=False))
    print(bl, time.time()-t, res.fidelity.ok, res.dtd_valid, res.jstage_issues, [ (d.category, d.src, d.message[:80]) for d in res.plan.decisions])
    root = etree.fromstring(res.xml_path.read_bytes())
    for x in root.iter("xref"): print("  ", x.get("ref-type"), x.get("rid"), "".join(x.itertext()))
    for fn in root.iter("fn"): print("  fn", fn.get("id"), "".join(fn.itertext()))
    print([str(w)[:100] for w in res.warnings])
