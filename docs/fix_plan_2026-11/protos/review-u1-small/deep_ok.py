import json, sys
from pathlib import Path
sys.path.insert(0, "/home/user/jstgxmlcng_JASME/tests")
from conftest import FULL
from jasme_jats.config import ArticleMeta, JournalConfig
from jasme_jats.pipeline import Options, convert
from jasme_jats.report import actions
journal = JournalConfig.load()
meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12", "pub_date": "2026-03-31",
    "received": "2025-06-01", "accepted": "2025-11-20", "peer_review": "あり", "keywords": "proof"})
# find max parseable depth
lo=1;hi=200000
while lo<hi:
    m=(lo+hi+1)//2
    try: json.loads("["*m+"]"*m); lo=m
    except RecursionError: hi=m-1
print("max depth", lo)
d=lo-5
def nest(n): return "["*n+"]"*n
op = '{"op": "set_role", "src": "d5", "text": %s, "occurrence": 1, "target": "", "role": "sec1", "image": "", "mathml": "", "surname": "", "given": "", "reason": %s, "confidence": %s}'
cases = {
 "op_text": '{"placements": [], "operations": [' + op % (nest(d-3), '"r"', '"高"') + '], "notes": []}',
 "op_reason": '{"placements": [], "operations": [' + op % ('""', nest(d-3), '"高"') + '], "notes": []}',
 "op_conf": '{"placements": [], "operations": [' + op % ('""', '"r"', nest(d-3)) + '], "notes": []}',
 "pl_items": '{"placements": [{"float":"s1","after":"d5","items":' + nest(d-3) + ',"reason":"r","confidence":"中"}], "operations": [], "notes": []}',
 "pl_reason": '{"placements": [{"float":"s1","after":"d5","items":[],"reason":' + nest(d-3) + ',"confidence":"中"}], "operations": [], "notes": []}',
 "notes": '{"placements": [], "operations": [], "notes": [' + nest(d-2) + ']}',
 "extra": '{"placements": [], "operations": [], "notes": [], "x": ' + nest(d-1) + '}',
}
base = Path(__file__).parent / "out"
for name, resp in cases.items():
    try:
        res = convert(FULL, meta, journal, Options(out_dir=base/name, ai_mode="manual", ai_response=resp, convert_metafiles=False))
        print(name, "ok error=", repr(res.ai.error[:60]), "keys", [a.key for a in actions(res)][:6])
    except BaseException as e:
        print(name, "CRASH", type(e).__name__, str(e)[:100])
