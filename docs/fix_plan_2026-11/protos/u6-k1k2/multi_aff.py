"""1 人の著者に所属が 2 つ: 著者表の同じ行の所属の欄に段落を 2 つ並べると、両方が付くか（Word での直し方の案内の確かめ）。"""
import copy
from common import OUT, S, W, article, para, run, summary
import common, make_fixtures as mf
orig = common.front_ja_rows
def rows2(b, title, rows, loose=()):
    out = orig(b, title, rows, loose)
    tbl = next(el for el in out if el.tag == f"{{{W}}}tbl")
    tc = tbl.find(f".//{{{W}}}tc")
    p = tc.find(f"{{{W}}}p")
    p2 = copy.deepcopy(p); b.set_text(p2, "第二大学"); p.addnext(p2)
    return out
common.front_ja_rows = rows2
path = article(OUT / "multi_aff.docx", ja_rows=(("第一大学", "試験　六郎"),))
res = run("multi_aff", path)
print(summary(res), [(a.name_ja.src, [x.ja.src for x in a.affs]) for a in res.plan.authors])
