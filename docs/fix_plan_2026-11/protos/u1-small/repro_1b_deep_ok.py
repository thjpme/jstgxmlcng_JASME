import json, sys
sys.path.insert(0, "/home/user/jstgxmlcng_JASME/tests")
from conftest import FULL, FLOAT
from jasme_jats.config import ArticleMeta, JournalConfig
from jasme_jats.pipeline import Options, convert
journal = JournalConfig.load()
meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12", "pub_date": "2026-03-31",
    "received": "2025-06-01", "accepted": "2025-11-20", "peer_review": "あり", "keywords": "proof"})
from pathlib import Path
deep = "[" * 3000 + "]" * 3000
for name, resp in [("ops_deep_elem", '{"placements": [], "operations": [' + deep + '], "notes": [' + deep + ']}'),
                   ("pl_deep", '{"placements": [{"float": "s1", "after": "d1", "items": [' + deep + ']}], "operations": [{"op": "set_role", "src": ' + deep + '}], "notes": []}')]:
    try:
        res = convert(FLOAT, meta, journal, Options(out_dir=Path(__file__).parent / "out" / name, ai_mode="manual", ai_response=resp, convert_metafiles=False))
        print(name, "ok error=", res.ai.error[:50], "rejected", len(res.ai.rejected))
    except BaseException as e:
        print(name, "CRASH", type(e).__name__, e)
