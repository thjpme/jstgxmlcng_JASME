import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, "/home/user/jstgxmlcng_JASME/tests")
from conftest import FULL
from jasme_jats.config import ArticleMeta, JournalConfig
from jasme_jats.pipeline import Options, convert
from jasme_jats.report import actions
journal = JournalConfig.load()
meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12", "pub_date": "2026-03-31",
    "received": "2025-06-01", "accepted": "2025-11-20", "peer_review": "あり", "keywords": "proof"})
op = {"op": "set_role", "src": "d5", "text": "", "occurrence": 1, "target": "", "role": "sec1", "image": "", "mathml": "",
      "surname": "", "given": "", "reason": "r", "confidence": "高"}
base = Path(__file__).parent / "out"
for name, resp in [("array", json.dumps([op])), ("deep", '{"placements": [], "operations": [' + "[" * 20000 + "]" * 20000 + "]}")]:
    out = base / name
    try:
        res = convert(FULL, meta, journal, Options(out_dir=out, ai_mode="manual", ai_response=resp, convert_metafiles=False))
        print(name, "error=", repr(res.ai.error[:60]), "applied", len(res.ai.applied) if hasattr(res.ai, "applied") else "?",
              "keys", [a.key for a in actions(res)][:8], "needs_action", res.needs_action)
    except BaseException as e:
        print(name, "CRASH", type(e).__name__)
