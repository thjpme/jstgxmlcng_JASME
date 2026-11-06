import sys, json
from pathlib import Path
HERE = Path(__file__).resolve().parent
P = HERE.parent / "u3-tables"
sys.path[:0] = ["/home/user/jstgxmlcng_JASME/tests", str(P)]
from lxml import etree
import make_fixtures as mf
mode = sys.argv[1] if len(sys.argv) > 1 else "proto"
if mode == "proto":
    import proto  # noqa
from jasme_jats.config import ArticleMeta, JournalConfig
from jasme_jats.pipeline import convert, Options
from jasme_jats.docx_reader import read_docx
from jasme_jats.model import Table
journal = JournalConfig.load()
meta = ArticleMeta.from_dict({'volume':'31','issue':'1','fpage':'1','lpage':'12'})
c = mf.cell
def raw(content, tcpr_extra):
    x = c(content)
    return x.replace("</w:tcPr>", tcpr_extra + "</w:tcPr>", 1)
def row(cells, before=0, after=0, header=False):
    trpr = ""
    if before or after or header:
        trpr = "<w:trPr>" + (f'<w:gridBefore w:val="{before}"/>' if before else "") + (f'<w:gridAfter w:val="{after}"/>' if after else "") + ("<w:tblHeader/>" if header else "") + "</w:trPr>"
    return "<w:tr>" + trpr + "".join(cells) + "</w:tr>"

def design_check(tbl, t):
    widths = {getattr(r,'grid_before',0) + sum(x.gridspan for x in r.cells) + getattr(r,'grid_after',0) for r in t.rows if r.cells}
    expect = next(iter(widths)) if len(widths) == 1 else None
    probs = []
    for sec in tbl:
        if sec.tag not in ("thead","tbody","tfoot"): continue
        carry = {}
        for k, tr in enumerate(sec.findall("tr"), 1):
            taken = set(carry); nxt = {a: n-1 for a, n in carry.items() if n > 1}; col = 0
            cells = [x for x in tr if x.tag in ("th","td")]
            for x in cells:
                while col in taken: col += 1
                cs = int(x.get("colspan","1")); rs = int(x.get("rowspan","1"))
                rng = range(col, col+cs)
                if any(q in taken for q in rng): probs.append(f"{sec.tag}{k}重なる")
                else:
                    taken.update(rng)
                    if rs > 1:
                        for q in rng: nxt[q] = rs-1
                col += cs
            if not cells: probs.append(f"{sec.tag}{k}セルなし")
            if taken and max(taken)+1 != len(taken): probs.append(f"{sec.tag}{k}隙間")
            if expect is not None and len(taken) != expect: probs.append(f"{sec.tag}{k}={len(taken)}列(docx {expect})")
            carry = nxt
        if carry: probs.append(f"{sec.tag}はみ出し")
    return probs

CASES = {
 "span0_uniform": [row([raw('A','<w:gridSpan w:val="0"/>'), c('B')]), row([raw('C','<w:gridSpan w:val="0"/>'), c('D')])],
 "span0_merge": [row([raw('A','<w:gridSpan w:val="0"/>'), c('B', vmerge='restart')]), row([c('C'), c('', vmerge='continue')])],
 "head_cross_text": [row([c('H1',vmerge='restart'), c('H2')], header=True), row([c('続き',vmerge='continue'), c('x')]), row([c('',vmerge='continue'), c('y')])],
}
for name, rows in CASES.items():
    d = HERE / "docx"; d.mkdir(exist_ok=True)
    path = d / f"{name}.docx"
    def body(b, rows=rows):
        return [mf.para(mf.S['sec1'], '１．検証'), mf.para(mf.S['body'], '表1に示す。'),
                mf.para(mf.S['tab_cap'], '表1　検証'), mf.table_of_rows(rows, 3), mf.para(mf.S['body'], '以上。')]
    mf.make_article(path, '検証', body)
    try:
        res = convert(path, meta, journal, Options(out_dir=HERE / "out" / mode / name, convert_metafiles=False))
    except Exception as e:
        print(name, "ERROR", type(e).__name__, e); continue
    root = etree.fromstring(res.xml_path.read_bytes().split(b"\n", 2)[2])
    tbl = root.find('.//table-wrap/table')
    doc = read_docx(path)
    ts = [b for b in doc.blocks if isinstance(b, Table)] if hasattr(doc,'blocks') else []
    bl = doc.blocks
    t = next((bl[i+1] for i in range(len(bl)-1) if isinstance(bl[i+1], Table) and not isinstance(bl[i], Table) and bl[i].text_only().startswith('表1')), None)
    x = etree.tostring(tbl, encoding='unicode')
    print(name, json.dumps(dict(fid=res.fidelity.ok, dtd=res.dtd_valid, check=design_check(tbl, t) if t else "no model", warn=[w for w in res.warnings if '表' in w and '結合' in w][:3]), ensure_ascii=False))
    print("   ", x)
