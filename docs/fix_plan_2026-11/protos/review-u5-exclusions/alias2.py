import sys, dataclasses
from pathlib import Path
ROOT = Path("/home/user/jstgxmlcng_JASME")
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
from jasme_jats.config import ArticleMeta, JournalConfig
from jasme_jats.pipeline import Options, convert
j0 = JournalConfig.load()
st = dict(j0.styles); st["英文要約見出し"] = "abstract_heading"; st["英文要約"] = "abstract"
j1 = dataclasses.replace(j0, styles=st)
meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12"})
p = next((ROOT / "tests/private/テンプレート").glob("*.docx"))
res = convert(p, meta, j1, Options(out_dir=Path("out/t"), ai_mode="manual", convert_metafiles=False))
pl = res.plan
for s in ("d86","d87","d88","d89","d90","d91","d185","d186","d187"):
    q = pl.paras.get(s)
    print(s, q.style_name if q else None, q.role if q else None, pl.region.get(s), pl.locations.get(s), len(q.plain()) if q else None)
for a in pl.apps:
    print("app", a.title.src if a.title else None, [type(c).__name__ for c in a.children], [c.tid for c in a.children if hasattr(c,'tid')])
print([d.message[:60] for d in pl.decisions if d.src in ("d90","d186")])
print("lang", pl.lang, "title_en", [q.src for q in pl.title_en])
