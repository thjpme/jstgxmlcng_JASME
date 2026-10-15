"""段落の後ろの部分が、照合の窓の外（ほかの段落の文字の後ろ）に出る場合の再現（scratchpad だけで使う。単位 B の外の不具合）。

  python -I exp_tail.py [src のフォルダ]      # 省略すると作業ツリーの src

d12 の最後の 8 文字を、ほかの段落（d13・d14・引用文献）の文字の後ろに置いた PDF の文字と照合する。d12 の後ろの部分は
照合の窓（段落の長さ + 60 文字ほど）の外に出るので、窓の中のほかの段落の文字と並べられ、d12 の「本,」が「付録」（d13 の
直す前の文字で、d13 に当たらなかった文字）に、「1)。」が「）」に直される（ルート2 で docx にその直しが入る）。
"""
import sys
sys.path.insert(0, "/home/user/jstgxmlcng_JASME/tests")
sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else "/home/user/jstgxmlcng_JASME/src")
from test_pdfmatch import PUBLISHED, FRONT, REST, _plan
from jasme_jats.config import JournalConfig
from jasme_jats.pdfmatch import compare
from jasme_jats.pdfdocx import plan_fixes
j = JournalConfig.load()
plan = _plan(j)
pub12 = PUBLISHED["d12"]
tail = pub12[-8:]
pages = ["\n".join(["（1）", *FRONT, pub12[:-8]]),
         "\n".join(["（2）", PUBLISHED["d13"], PUBLISHED["d14"], "引用および参考文献", PUBLISHED["d17"], tail,
                    "見本花子（2021）．「見本の研究」．『見本誌』，第2巻，pp.11-20．"])]
pc = compare(plan, pages)
print("tail", tail, "unmatched", pc.unmatched)
for d in pc.diffs:
    print(" diff", d.src, repr(d.docx), repr(d.pdf), d.fixable, getattr(d, "why", "")[:20])
for f in plan_fixes(plan, pc):
    if f.kind == "text":
        print(" fix", f.src, repr(f.old), repr(f.new), f.reason[:20])
