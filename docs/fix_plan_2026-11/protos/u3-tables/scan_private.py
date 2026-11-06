"""tests/private と tests/fixtures の docx の表の形を数える（本文の文字は出さない）。"""
import sys, zipfile, glob, os
from lxml import etree
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
def w(t): return f"{{{W}}}{t}"
def val(el, d=None):
    return el.get(w("val"), d) if el is not None else d
ROOT = "/home/user/jstgxmlcng_JASME/tests"
files = sorted(glob.glob(ROOT + "/private/**/*.docx", recursive=True)) + sorted(glob.glob(ROOT + "/fixtures/*.docx"))
for f in files:
    if "review-repros" in f and not f.endswith(("merge.docx","note-table.docx")):
        continue
    with zipfile.ZipFile(f) as z:
        parts = [n for n in z.namelist() if n.startswith("word/") and n.endswith(".xml")]
        stats = dict(tbl=0, vMerge=0, gridSpan=0, gridBefore=0, gridAfter=0, wBefore=0, tblHeader=0, ragged=0, grid_mismatch=0, nested=0)
        for n in parts:
            root = etree.fromstring(z.read(n))
            for t in root.iter(w("tbl")):
                stats["tbl"] += 1
                if any(a.tag == w("tbl") for a in t.iterancestors()): stats["nested"] += 1
                ngrid = len(t.findall(w("tblGrid") + "/" + w("gridCol")))
                widths = set()
                for tr in t.iter(w("tr")):
                    if next((a for a in tr.iterancestors(w("tbl"))), None) is not t: continue
                    trpr = tr.find(w("trPr"))
                    gb = int(val(trpr.find(w("gridBefore")) if trpr is not None else None, 0) or 0)
                    ga = int(val(trpr.find(w("gridAfter")) if trpr is not None else None, 0) or 0)
                    tot = gb + ga
                    for tc in tr.iter(w("tc")):
                        if next((a for a in tc.iterancestors(w("tr"))), None) is not tr: continue
                        gs = tc.find(w("tcPr") + "/" + w("gridSpan"))
                        tot += int(val(gs, 1) or 1)
                    widths.add(tot)
                if len(widths) > 1: stats["ragged"] += 1
                if widths and max(widths) != ngrid: stats["grid_mismatch"] += 1
            for k in ("vMerge","gridSpan","gridBefore","gridAfter","wBefore","tblHeader"):
                stats[k] += len(list(root.iter(w(k))))
    print(os.path.relpath(f, ROOT).split("/")[1] if "private" in f else os.path.basename(f), stats)
