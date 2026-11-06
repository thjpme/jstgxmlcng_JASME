"""設計の試作: 縦結合の数え方・グリッドの飛ばし・見出し行の区切り（リポジトリは変えず、実行時に差し替える）。"""
import inspect, textwrap
import jasme_jats.docx_reader as dr
import jasme_jats.builder as bd
from jasme_jats.builder import _sub

# --- docx_reader: w:gridBefore・w:gridAfter を Row に読む
src = textwrap.dedent(inspect.getsource(dr.Reader.read_table))
old = 'row = Row(header=trpr is not None and on_off(trpr.find(w("tblHeader"))))'
assert old in src
src = src.replace(old, old + "\n        row.grid_before = _grid_skip(trpr, \"gridBefore\")\n        row.grid_after = _grid_skip(trpr, \"gridAfter\")")
def _grid_skip(trpr, name):
    if trpr is None:
        return 0
    el = trpr.find(dr.w(name))
    try:
        return max(0, int(dr.wval(el, "0") or 0)) if el is not None else 0
    except ValueError:
        return 0
dr._grid_skip = _grid_skip
ns = {}
exec(src, dr.__dict__, ns)
dr.Reader.read_table = ns["read_table"]

WARN_CROSS = "{where}: 見出し行から本文の行へ続く縦の結合を、見出し行の終わりで止めた（本文の行の側は別のセルとして出力した）"
WARN_SPAN = "{where}の {row} 行目: 縦に結合したセルの幅（横に結合した列の数）が上の行のセルと違うので、結合せずに別のセルとして出力した"


def table(self, parent, t):
    rows = t.rows
    n_head = 0
    for row in rows:
        if row.header:
            n_head += 1
        else:
            break
    if n_head == len(rows):
        n_head = 0
    top_of, conts, extra = {}, {}, {}
    owner = {}
    crossed, mismatch = False, []
    for r, row in enumerate(rows):
        col = getattr(row, "grid_before", 0)
        if n_head and r == n_head:
            c0 = col
            for c in row.cells:
                o = owner.get(c0)
                if c.vmerge == "continue" and o is not None and o[1] == c.gridspan:
                    crossed = True
                c0 += c.gridspan
            owner = {}
        new = {}
        for c in row.cells:
            span = c.gridspan
            if c.vmerge == "continue":
                o = owner.get(col)
                if o is not None and o[1] == span:
                    top_of[id(c)] = o[0]
                    conts.setdefault(id(o[0]), []).append(r)
                    extra.setdefault(id(o[0]), []).extend(c.blocks)
                    new[col] = o
                else:
                    if any(s < col + span and col < s + w_ for s, (_, w_) in owner.items()):
                        mismatch.append(r + 1)
                    new[col] = (c, span)
            elif c.vmerge == "restart":
                new[col] = (c, span)
            col += span
        owner = new
    dropped = {r for r, row in enumerate(rows) if all(id(c) in top_of for c in row.cells)}   # セルのない行も
    rowspan = {k: 1 + sum(1 for r in rs if r not in dropped) for k, rs in conts.items()}
    if crossed or mismatch:
        where = dr.table_where(dr.table_head(t))
        if crossed:
            self.info.warnings.append(WARN_CROSS.format(where=where))
        for r in dict.fromkeys(mismatch):
            self.info.warnings.append(WARN_SPAN.format(where=where, row=r))
    tbl = _sub(parent, "table")
    for tag, lo, hi in (("thead", 0, n_head), ("tbody", n_head, len(rows))):
        if lo >= hi:
            continue
        sec = _sub(tbl, tag)
        cell_tag = "th" if tag == "thead" else "td"
        for r in range(lo, hi):
            if r in dropped:
                continue
            row = rows[r]
            tr = _sub(sec, "tr")
            if getattr(row, "grid_before", 0):
                f = _sub(tr, cell_tag)
                if row.grid_before > 1:
                    f.set("colspan", str(row.grid_before))
            for c in row.cells:
                if id(c) in top_of:
                    continue
                td = _sub(tr, cell_tag)
                if c.gridspan > 1:
                    td.set("colspan", str(c.gridspan))
                if rowspan.get(id(c), 1) > 1:
                    td.set("rowspan", str(rowspan[id(c)]))
                self.cell_content(td, c.blocks + extra.get(id(c), []))
            if getattr(row, "grid_after", 0):
                f = _sub(tr, cell_tag)
                if row.grid_after > 1:
                    f.set("colspan", str(row.grid_after))
        if not len(sec):
            tbl.remove(sec)
    if not len(tbl):
        tr = _sub(_sub(tbl, "tbody"), "tr")
        _sub(tr, "td")

bd.Builder.table = table
