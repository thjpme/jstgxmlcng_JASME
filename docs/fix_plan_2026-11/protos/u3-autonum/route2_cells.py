import sys
from pathlib import Path
from collections import Counter
REPO = Path("/home/user/jstgxmlcng_JASME")
from jasme_jats.config import ArticleMeta, JournalConfig
from jasme_jats.pipeline import Options, convert
from jasme_jats.linker import body_paragraphs
from jasme_jats.pdfmatch import target_paragraphs
journal = JournalConfig.load()
meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12", "pub_date": "2026-03-31",
                              "received": "2025-06-01", "accepted": "2025-11-20", "peer_review": "あり", "keywords": "a; b"})
HERE = Path(__file__).resolve().parent
for folder in ("テストデータ1", "テストデータ2"):
    f = REPO / "tests" / "private" / folder
    pdf = next(f.glob("*.pdf"))
    d = sorted(f.glob("*.docx"))[-1]
    for route in ("docx", "pdf"):
        res = convert(d, meta, journal, Options(out_dir=HERE / "r2" / folder / route, convert_metafiles=False, ai_mode="manual",
                                               pdf_path=pdf, route=route))
        plan = res.plan
        cells = {p.src for p, w in body_paragraphs(plan) if w == "cell"}
        auto_cells = sorted((p.src for p in plan.paras.values() if p.src in cells and (p.autonum or "").strip()), key=lambda s: int(s[1:]))
        shapes = Counter(plan.paras[s].autonum for s in auto_cells)
        targets = {p.src for p in target_paragraphs(plan)}
        pc = res.pdf_check
        diffs = [d_ for d_ in pc.diffs if d_.src in auto_cells]
        nums = [k for k in pc.numbers if k[1] in auto_cells]
        ign = [k for k in getattr(pc, "ignored_lines", {}) ] if hasattr(pc, "ignored_lines") else []
        fixes = [fx for fx in (res.docx_fix.fixes if res.docx_fix else []) if fx.src in auto_cells]
        print(folder, route, "cell autonum paras", len(auto_cells), "shapes", dict(shapes), "in targets", len(set(auto_cells) & targets),
              "diffs", len(diffs), "numbers", len(nums), "fixes", len(fixes),
              "pdf_numbers", len([k for k in plan.pdf_numbers if k[1] in auto_cells]),
              "supplement", None if res.supplement is None else res.supplement.ok, "number_count", pc.number_count)
        # どの区分の違いがあったか（全体）
        print("   diffs kinds", Counter(x.kind for x in pc.diffs))
