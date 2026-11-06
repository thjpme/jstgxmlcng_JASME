import sys
from pathlib import Path
ROOT = Path("/home/user/jstgxmlcng_JASME")
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
from jasme_jats.config import ArticleMeta, JournalConfig
from jasme_jats.pipeline import Options, convert
from jasme_jats.report import actions
j = JournalConfig.load()
meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12"})
p = Path(sys.argv[1])
res = convert(p, meta, j, Options(out_dir=p.parent / ("b_" + p.stem), convert_metafiles=False))
f = res.fidelity
print(res.ok, f.missing, [(a.level,a.key) for a in actions(res)], len(res.plan.refs), res.plan.ref_heading)
