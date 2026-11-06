"""pytest のプラグイン: 試作の検出（proto）で、構造の衝突が起きたテストを記録する（テストの結果は変えない）。"""
import os, json
from pathlib import Path
import proto
from jasme_jats import structure, pipeline
LOG = Path(__file__).parent / "out" / "pytest_conflicts.jsonl"
_orig = structure.classify
def classify(*a, **k):
    plan = _orig(*a, **k)
    cs = proto.conflicts(plan)
    if cs:
        with LOG.open("a") as f:
            f.write(json.dumps({"test": os.environ.get("PYTEST_CURRENT_TEST", ""), "kinds": [c.kind for c in cs],
                                "lost": [c.lost for c in cs], "by": [c.by for c in cs]}, ensure_ascii=False) + "\n")
    return plan
structure.classify = classify
pipeline.classify = classify
