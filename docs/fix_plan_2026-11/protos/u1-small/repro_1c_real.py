import sys
sys.path.insert(0, "/home/user/jstgxmlcng_JASME/tests")
from test_refparse import make_refs
from jasme_jats.refparse import Mapped, extract_citations, match_citation
def links(text, refs):
    known = {n for r in refs for n in r.parsed["names"]}
    mp = Mapped(text); out = []
    for c in extract_citations(mp.n, known):
        ref, kind, why = match_citation(c, refs)
        s, e = mp.orig(*c["span"]); out.append((text[s:e], ref.rid if ref else None, kind, why))
    return out
A = make_refs(["試験太郎・架空花子（2001）．「一つ目の論文」．『架空誌』，第1巻，pp.1-2．",
               "試験太郎・架空花子（2001）．「二つ目の論文」．『架空誌』，第2巻，pp.3-4．",
               "試験太郎（2001）．『三つ目の本』．架空書房．"])
print("case1", links("試験・架空（2001）は", A))
B = make_refs(["試験太郎（2001）．『一つ目の本』．架空書房．",
               "試験太郎・架空花子（2001）．「二つ目の論文」．『架空誌』，第2巻，pp.3-4．",
               "試験太郎（2001）．『三つ目の本』．架空書房．"])
print("case2", links("試験・架空（2001）は", B))
print("case2b 単著", links("試験（2001）は", B))
