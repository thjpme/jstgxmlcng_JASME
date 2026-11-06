import sys
sys.path.insert(0, "/tmp/claude-0/-home-user-jstgxmlcng-JASME/72d6c468-bb77-50d1-8396-803f4558807a/scratchpad/u6-k1k2")
import proto
from common import S, article, para, run, summary
from pathlib import Path
OUT = Path(__file__).resolve().parent / "out"; OUT.mkdir(exist_ok=True)
P = lambda st, t: para(S[st], t)
REF = P("ref", "試験六郎（2024）．「小さな論文」．『架空誌』，第5巻，pp.9-10．")
FN1 = P("body", "1) 注の本文である。")
CASES = {
 # 設計の助言どおり「後ろの見出しを消す」
 "fn_after_refs_delete_later_ref_head": dict(back=[P("ref_head", "引用文献"), REF, P("fn_head", "注"), FN1, P("ref", "架空花子（2020）．『本』．架空社．")]),
 "notes_notes_delete_later_head": dict(back=[P("notes_head", "付記"), P("body", "先の付記。"), P("ref_head", "引用文献"), REF, P("body", "後の付記。")]),
}
for name, kw in CASES.items():
    path = article(OUT / f"{name}.docx", **kw)
    res = run("a_" + name, path)
    s = summary(res); pl = res.plan
    print(name, s, "refs", len(pl.refs), "fns", [[p.src for p in f.paras] for f in pl.fns], "conf", [(c.kind,c.lost) for c in proto.conflicts(pl)])
