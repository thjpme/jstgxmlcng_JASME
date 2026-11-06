from types import SimpleNamespace as NS
from jasme_jats.refparse import match_citation
def ref(rid, names, year="2001"):
    return NS(rid=rid, parsed={"names": names, "latin": True, "year": year, "n_authors": len(names), "authors_str": " ".join(names)})
c = {"form": "narrative", "names": ["Smith", "Jones"], "etal": False, "year": "2001"}
case1 = [ref("B1", ["Smith", "Jones"]), ref("B2", ["Smith", "Jones"]), ref("B3", ["Smith"])]
case2 = [ref("B1", ["Smith"]), ref("B2", ["Smith", "Jones"]), ref("B3", ["Smith"])]
case3 = [ref("B1", ["Smith"]), ref("B2", ["Smith"]), ref("B3", ["Smith", "Jones"])]   # 末尾が唯一の最大（今も正しい）
for name, refs in (("case1 B1=B2>B3", case1), ("case2 B1<B2>B3", case2), ("case3 B1=B2<B3", case3)):
    r, kind, why = match_citation(c, refs)
    print(name, "->", r.rid if r else None, kind, why)
# 和文
cj = {"form": "narrative", "names": ["山田"], "etal": False, "year": "2001"}
def jref(rid, names): return NS(rid=rid, parsed={"names": names, "latin": False, "year": "2001", "n_authors": len(names), "authors_str": "・".join(names)})
case4 = [jref("B1", ["山田"]), jref("B2", ["山田"]), jref("B3", ["山田", "佐藤"])]
r, kind, why = match_citation(cj, case4); print("case4 ja B1=B2(1名)>B3", "->", r.rid if r else None, kind, why)
