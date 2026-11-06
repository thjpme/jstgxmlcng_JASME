"""fixtures と tests/private の docx をすべて変換し、出力の <table> の形を確かめる（文字は出さない）。"""
import sys, glob, json, os
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path[:0] = ["/home/user/jstgxmlcng_JASME/tests", str(HERE)]
from lxml import etree
from jasme_jats.config import ArticleMeta, JournalConfig
from jasme_jats.pipeline import convert, Options
from jasme_jats.report import actions
from shape import table_shape
journal = JournalConfig.load()
meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12", "pub_date": "2026-03-31",
                              "received": "2025-06-01", "accepted": "2025-11-20", "peer_review": "あり", "keywords": "a; b"})
T = "/home/user/jstgxmlcng_JASME/tests"
files = sorted(glob.glob(T + "/fixtures/*.docx")) + sorted(f for f in glob.glob(T + "/private/**/*.docx", recursive=True)
                                                           if "review-repros" not in f)
total = bad = 0
for i, f in enumerate(files):
    label = (f.split("/private/")[1].split("/")[0] + f"#{i}") if "/private/" in f else os.path.basename(f)
    try:
        res = convert(f, meta, journal, Options(out_dir=HERE / "scan" / str(i), ai_mode="manual", convert_metafiles=False))
    except Exception as e:
        print(label, "ERROR", type(e).__name__); continue
    root = etree.fromstring(res.xml_path.read_bytes().split(b"\n", 2)[2])
    tables = list(root.iter("table"))
    probs = []
    spans = 0
    for k, t in enumerate(tables):
        spans += sum(1 for c in t.iter("td", "th") if c.get("rowspan") or c.get("colspan"))
        w, p = table_shape(t)
        if p:
            probs.append((k, p))
    total += len(tables); bad += bool(probs)
    parents = {}
    for t in tables:
        a = t.getparent().getparent().tag
        parents[a] = parents.get(a, 0) + 1
    print(label, json.dumps(dict(tables=len(tables), span_cells=spans, parents=parents, fid=res.fidelity.ok, dtd=res.dtd_valid,
                                 problems=probs), ensure_ascii=False))
print("total tables", total, "docs with problems", bad)
