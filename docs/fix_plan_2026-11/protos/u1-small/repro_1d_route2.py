import sys, zipfile
from pathlib import Path
sys.path.insert(0, "/home/user/jstgxmlcng_JASME/tests")
sys.path.insert(0, str(Path(__file__).parent))
import make_fixtures as mf
import test_pdfmatch as tp
from jasme_jats.config import ArticleMeta, JournalConfig
from jasme_jats.pipeline import _mechanical, convert, Options
from jasme_jats.pdfmatch import compare
from jasme_jats.pdfdocx import plan_fixes
from jasme_jats.report import actions
import jasme_jats.pdfmatch as pdfmatch
HERE = Path(__file__).parent / "r2"
HERE.mkdir(exist_ok=True)
journal = JournalConfig.load()
meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12", "pub_date": "2026-03-31",
    "received": "2025-06-01", "accepted": "2025-11-20", "peer_review": "あり", "keywords": "proof"})
ITEMS = ["一つ目の項目として，架空の授業の記録を集めた。", "二つ目の項目として，記録を観点ごとに整理した。"]
def parts(b):
    return [mf.para(mf.S["sec1"], "１．はじめに"), mf.para(mf.S["body"], tp.TALK),
            *[mf.list_item(mf.S["body"], t, num_id=92) for t in ITEMS]]
base = HERE / "base.docx"; dst = HERE / "ov.docx"
mf.make_article(base, "ページ番号の判定の検証用文書", parts)
NUMS = ('<w:num w:numId="92"><w:abstractNumId w:val="0"/><w:lvlOverride w:ilvl="0">'
        '<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="upperLetter"/><w:lvlText w:val="(%1)"/></w:lvl></w:lvlOverride></w:num>')
with zipfile.ZipFile(base) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
    for it in zin.infolist():
        d = zin.read(it.filename)
        if it.filename == "word/numbering.xml":
            d = d.decode().replace("</w:numbering>", NUMS + "</w:numbering>").encode()
        zout.writestr(it, d)
if "--fixed" in sys.argv:
    import numfix; numfix.install()
_, plan, _ = _mechanical(dst, journal)
src = {p.plain(): p.src for p in plan.paras.values()}
print("autonum", [plan.paras[src[t]].autonum for t in ITEMS])
for label, marks in (("PDF=(A)(B)", ["(A)", "(B)"]), ("PDF=（Ａ）（Ｂ）", ["（Ａ）", "（Ｂ）"])):
    pages = tp.n10_pages([*tp.SMALL_FRONT, *tp.body_lines(tp.TALK), *[f"{m}{t}" for m, t in zip(marks, ITEMS)], *tp.N10_TAIL])
    pc = compare(plan, pages)
    print(label, "number_edits", {k[1]: v for k, v in pc.number_edits.items()}, "diffs", len(pc.diffs),
          [(d.src, d.kind, d.fixable, bool(d.why)) for d in pc.diffs][:4], "fixes", len(plan_fixes(plan, pc)))
    pdfmatch.extract_pages = lambda path, pages=pages: pages
    (HERE / "dummy.pdf").write_bytes(b"%PDF-1.4\n")
    res = convert(dst, meta, journal, Options(out_dir=HERE / ("out" + label[-2:]), pdf_path=HERE / "dummy.pdf", route="pdf", convert_metafiles=False))
    print("   route2: supplement ok", res.supplement.ok if res.supplement else None, "actions", [a.key for a in actions(res)], "fid", res.fidelity.ok and res.fidelity.final_ok)
