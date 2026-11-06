import glob, os, collections
from jasme_jats import refparse
from jasme_jats.config import JournalConfig
from jasme_jats.pipeline import _mechanical
from jasme_jats.refparse import name_match
orig = refparse.match_citation
def fixed(c, refs):
    if c["form"] == "unresolved" or not c["names"]:
        return orig(c, refs)
    first = c["names"][0]
    by_name = [r for r in refs if r.parsed.get("names") and name_match(first, r.parsed["names"][0], r.parsed["latin"])]
    exact = [r for r in by_name if (r.parsed.get("year") or "").lower() == c["year"].lower()]
    if not exact:
        return orig(c, refs)
    def fit(r):
        rn = r.parsed["names"]
        co = len(c["names"]) > 1 and len(rn) > 1 and all(name_match(a, b, r.parsed["latin"]) for a, b in zip(c["names"][1:], rn[1:]))
        n_ok = r.parsed["n_authors"] == len(c["names"]) or (c["etal"] and r.parsed["n_authors"] >= 2)
        return (co, n_ok)
    best = max(fit(x) for x in exact)
    top = [x for x in exact if fit(x) == best]
    if len(top) > 1:
        return None, "ambiguous", "x"
    return top[0], "exact", ""
stats = collections.Counter()
journal = JournalConfig.load()
for f in sorted(glob.glob("/home/user/jstgxmlcng_JASME/tests/private/**/*.docx", recursive=True)):
    res = {}
    for name, fn in (("orig", orig), ("fixed", fixed)):
        calls = []
        def wrap(c, refs, fn=fn):
            out = fn(c, refs); calls.append((c["span"], out[0].rid if out[0] else None, out[1], len([r for r in refs if (r.parsed.get("year") or "").lower() == c["year"].lower()])))
            return out
        refparse.match_citation = wrap
        try:
            _mechanical(f, journal)
        except Exception as e:
            calls.append(("ERR", type(e).__name__))
        res[name] = calls
    refparse.match_citation = orig
    folder = os.path.basename(os.path.dirname(f))
    kinds = collections.Counter(k[2] for k in res["orig"] if len(k) > 2)
    diff = sum(1 for a, b in zip(res["orig"], res["fixed"]) if a != b) + abs(len(res["orig"]) - len(res["fixed"]))
    print(folder, "citations", len(res["orig"]), dict(kinds), "diff", diff)
