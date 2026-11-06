import sys
sys.path.insert(0, "/tmp/claude-0/-home-user-jstgxmlcng-JASME/72d6c468-bb77-50d1-8396-803f4558807a/scratchpad/u5-exclusions")
import proto_patch  # noqa
from pathlib import Path
from jasme_jats.config import ArticleMeta, JournalConfig
from jasme_jats.pipeline import Options, convert
from jasme_jats import report
ROOT = Path("/home/user/jstgxmlcng_JASME")
j = JournalConfig.load(); meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12"})
W = Path(__file__).parent / "count_proto_out"
docs = sorted((ROOT / "tests/fixtures").glob("*.docx")) + sorted(p for p in (ROOT / "tests/private").rglob("*.docx") if "review-repros" not in p.parts)
for i, p in enumerate(docs):
    res = convert(p, meta, j, Options(out_dir=W / f"o{i}", ai_mode="manual", convert_metafiles=False))
    keys = [(a.level, a.key) for a in report.actions(res) if a.key in ("excluded_unsure", "abstract_missing")]
    n = len(proto_patch._missing(res))
    print(p.parent.name, i, keys, "missing_rows", n, "fid_ok", res.fidelity.ok)
