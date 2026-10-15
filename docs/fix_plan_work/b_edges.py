import re, sys
from jasme_jats.pdfmatch import extract_pages, RE_PAGE_NO
for f in sys.argv[1:]:
    pages = extract_pages(f)
    print("=====", f.split("/")[-1], len(pages), "pages")
    for i, p in enumerate(pages):
        ls = [x for x in re.split(r"\r\n|\r|\n", p)]
        nonempty = [x for x in ls if x.strip()]
        mid = [x for x in nonempty[2:-2] if RE_PAGE_NO.match(x)]
        print(f" p{i+1}: head={nonempty[:2]!r} tail={nonempty[-2:]!r} mid_pageno={mid!r}")
