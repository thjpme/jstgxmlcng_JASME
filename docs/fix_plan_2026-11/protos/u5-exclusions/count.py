"""除外の理由ごとの件数（本文の抜粋は出さない。件数・理由・段落 ID・文字数だけ）。"""
import json
import re
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path("/home/user/jstgxmlcng_JASME")
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
from jasme_jats.config import ArticleMeta, JournalConfig
from jasme_jats.pipeline import Options, convert
from jasme_jats.report import actions

journal = JournalConfig.load()
meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12"})
WORK = Path(__file__).resolve().parent / "count_out"
WORK.mkdir(exist_ok=True)

docs = sorted((ROOT / "tests/fixtures").glob("*.docx"))
priv = sorted(p for p in (ROOT / "tests/private").rglob("*.docx") if "review-repros" not in p.parts)
docs += priv


def norm(reason):
    return re.sub(r"（d\w+ と同一", "（dN と同一", re.sub(r"（[a-z]\d+ と同一.*", "（…と同一）", reason))


total = Counter()
per = {}
for i, p in enumerate(docs):
    label = p.parent.name + "/" + (p.name if "private" not in p.parts else f"doc{i}")
    try:
        res = convert(p, meta, journal, Options(out_dir=WORK / f"o{i}", ai_mode="manual", convert_metafiles=False))
    except Exception as e:  # noqa
        per[label] = {"error": type(e).__name__ + ": " + str(e)[:80]}
        continue
    c = Counter()
    ids = defaultdict(list)
    lens = defaultdict(list)
    for s, reason, text in res.fidelity.excluded:
        if reason in ("空白のみの段落", "図の画像だけの段落にある空白"):
            continue
        r = norm(reason)
        c[r] += 1
        ids[r].append(s)
        lens[r].append(len(re.sub(r"\s", "", text)))
    total.update(c)
    en = [x for x in ("title_en", "abstract") if getattr(res.plan, x)]
    per[label] = {"lang": res.plan.lang, "abstract_en_paras": len(res.plan.abstract),
                  "has_title_en": bool(res.plan.title_en), "abstract_heading": res.plan.abstract_heading is not None,
                  "ok": res.ok, "actions": [(a.level, a.key) for a in actions(res)],
                  "excl": {r: {"n": n, "ids": ids[r][:8], "chars": lens[r][:8]} for r, n in c.items()}}
print(json.dumps(per, ensure_ascii=False, indent=1))
print(json.dumps(total, ensure_ascii=False, indent=1))
