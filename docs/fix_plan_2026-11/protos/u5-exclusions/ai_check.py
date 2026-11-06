import sys, json
from pathlib import Path
ROOT=Path("/home/user/jstgxmlcng_JASME")
sys.path[:0]=[str(ROOT/"src"), str(ROOT/"tests")]
from jasme_jats.config import ArticleMeta, JournalConfig
from jasme_jats.pipeline import Options, convert, _mechanical
from jasme_jats.ai_assist import build_request
from jasme_jats.report import actions
j=JournalConfig.load()
meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12"})
W=Path(__file__).parent/"work"
p=W/"b1_noheading_plain.docx"
_, plan, linker = _mechanical(p, j)
req,_=build_request(plan, linker)
print([ln for ln in req.splitlines() if "出力から除外" in ln and ("d21" in ln or "d22" in ln)])
resp=json.dumps({"operations":[{"op":"set_role","src":"d21","role":"abstract"}]})
res=convert(p, meta, j, Options(out_dir=W/"b1_ai", ai_mode="manual", ai_response=resp, convert_metafiles=False))
print("abstract", len(res.plan.abstract), "ok", res.ok, [(a.level,a.key) for a in actions(res)], [e.src for e in res.plan.exclusions if not e.blank])
# K7 in AI
p=W/"a1_after_item.docx"
_, plan, linker = _mechanical(p, j)
req,_=build_request(plan, linker)
print([ln[:60] for ln in req.splitlines() if "出力から除外" in ln and ("d15" in ln or "d16" in ln)])
