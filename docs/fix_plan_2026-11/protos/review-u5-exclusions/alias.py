import sys, dataclasses
from collections import Counter
from pathlib import Path
ROOT = Path("/home/user/jstgxmlcng_JASME")
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
from jasme_jats.config import ArticleMeta, JournalConfig
from jasme_jats.pipeline import Options, convert
from jasme_jats.report import actions
j0 = JournalConfig.load()
st = dict(j0.styles); st["英文要約見出し"] = "abstract_heading"; st["英文要約"] = "abstract"
j1 = dataclasses.replace(j0, styles=st)
meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12"})
docs = sorted(p for p in (ROOT / "tests/private").rglob("*.docx") if "review-repros" not in p.parts) + sorted((ROOT/"tests/fixtures").glob("*.docx"))
W = Path(__file__).resolve().parent / "out"
for i, p in enumerate(docs):
    rows = []
    for tag, j in (("base", j0), ("alias", j1)):
        res = convert(p, meta, j, Options(out_dir=W / f"{tag}{i}", ai_mode="manual", convert_metafiles=False))
        c = Counter(r for s, r, t in res.fidelity.excluded if t.strip())
        pl = res.plan
        xml = (W / f"{tag}{i}")
        rows.append((tag, res.ok, len(pl.abstract), pl.abstract_heading.src if pl.abstract_heading else None,
                     len(pl.apps), [len(a.children) for a in pl.apps], len(pl.tables), dict(c), [(a.level, a.key) for a in actions(res)],
                     [p.src for p in pl.abstract][:6]))
    if rows[0][1:] != rows[1][1:]:
        print(i, p.parent.name if 'private' in p.parts else p.name)
        for r in rows: print("  ", r)
    else:
        print(i, "same")
