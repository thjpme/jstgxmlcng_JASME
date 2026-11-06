import sys, collections
sys.path.insert(0, "/home/user/jstgxmlcng_JASME/src")
from pathlib import Path
from jasme_jats.docx_reader import read_docx
for p in sorted(Path("/home/user/jstgxmlcng_JASME/tests/private").glob("*/*.docx")):
    if "review-repros" in str(p): continue
    doc = read_docx(p)
    c = collections.Counter()
    blanks = collections.Counter()
    for q in doc.all_paragraphs():
        n = q.style_name or ""
        if any(k in n for k in ("英文要", "見出し", "Abstract", "所属", "著者")):
            c[n] += 1
            if q.is_blank: blanks[n] += 1
    print(p.parent.name, p.name[:12], dict(c), "blank:", dict(blanks))
