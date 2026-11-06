"""u1-small の直し方の試作を当てて既存テストを走らせる（pytest -p allfix）。"""
import sys, json
sys.path.insert(0, "/tmp/scratchpad/u1-small")
import numfix
numfix.install()
from jasme_jats import ai_assist, refparse, pipeline
from jasme_jats.refparse import name_match
_orig_mc = refparse.match_citation
def match_citation(c, refs):
    if c["form"] == "unresolved" or not c["names"]:
        return _orig_mc(c, refs)
    first = c["names"][0]
    by_name = [r for r in refs if r.parsed.get("names") and name_match(first, r.parsed["names"][0], r.parsed["latin"])]
    exact = [r for r in by_name if (r.parsed.get("year") or "").lower() == c["year"].lower()]
    if not exact:
        return _orig_mc(c, refs)
    def fit(r):
        rn = r.parsed["names"]
        co = len(c["names"]) > 1 and len(rn) > 1 and all(name_match(a, b, r.parsed["latin"]) for a, b in zip(c["names"][1:], rn[1:]))
        n_ok = r.parsed["n_authors"] == len(c["names"]) or (c["etal"] and r.parsed["n_authors"] >= 2)
        return (co, n_ok)
    best = max(fit(x) for x in exact)
    top = [x for x in exact if fit(x) == best]
    if len(top) > 1:
        return None, "ambiguous", "同じ著者・同じ年の文献が複数あり、どれか特定できない: " + "、".join(x.rid for x in top)
    return top[0], "exact", ""
refparse.match_citation = match_citation
_orig_pr = ai_assist.parse_response
def parse_response(text):
    t, _ = ai_assist._json_text(text)
    if not t.startswith("{"):
        i = t.find("{")
        if (i >= 0 and t[:i].rstrip().endswith("[")):
            raise ValueError("TOP_ARRAY")
    try:
        d = _orig_pr(text)
    except RecursionError:
        raise ValueError("DEEP")
    if "operations" not in d:
        raise ValueError("NO_OPS")
    return d
ai_assist.parse_response = parse_response
pipeline.parse_response = parse_response
