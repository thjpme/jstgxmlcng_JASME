"""実際の原稿と fixtures の表で、結合元のない継続・幅の違う継続・見出し行をまたぐ結合・すべて継続の行を数える（文字は出さない）。"""
import glob, os
from jasme_jats.docx_reader import read_docx
from jasme_jats.model import Table, Para
T = "/home/user/jstgxmlcng_JASME/tests"
files = sorted(glob.glob(T + "/fixtures/*.docx")) + sorted(f for f in glob.glob(T + "/private/**/*.docx", recursive=True) if "review-repros" not in f)
def tables(blocks):
    for b in blocks:
        if isinstance(b, Table):
            yield b
            for r in b.rows:
                for c in r.cells:
                    yield from tables(c.blocks)
for f in files:
    doc = read_docx(f)
    allt = list(tables(doc.blocks))
    for tb in doc.textboxes:
        pass
    st = dict(tables=len(allt), orphan_cont=0, span_mismatch=0, cross_head=0, all_cont_rows=0, head_rows=0)
    for t in allt:
        n_head = 0
        for r in t.rows:
            if r.header: n_head += 1
            else: break
        if n_head == len(t.rows): n_head = 0
        st["head_rows"] += n_head
        owner = {}
        for i, row in enumerate(t.rows):
            col, new, allc = 0, {}, bool(row.cells)
            for c in row.cells:
                if c.vmerge == "continue":
                    o = owner.get(col)
                    if o and o == c.gridspan:
                        new[col] = o
                        if n_head and i == n_head: st["cross_head"] += 1
                    else:
                        allc = False
                        if any(s < col + c.gridspan and col < s + w for s, w in owner.items()): st["span_mismatch"] += 1
                        else: st["orphan_cont"] += 1
                        new[col] = c.gridspan
                elif c.vmerge == "restart":
                    new[col] = c.gridspan; allc = False
                else:
                    allc = False
                col += c.gridspan
            owner = new
            st["all_cont_rows"] += allc
    label = f.split("/private/")[1].split("/")[0] if "/private/" in f else os.path.basename(f)
    print(label, st)
