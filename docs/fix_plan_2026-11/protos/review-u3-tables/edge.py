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
 # gridSpan=0（壊れた値）
 "span0": [row([raw('A','<w:gridSpan w:val="0"/>'), c('B')]), row([c('C'), c('D')])],
 # 表の 1 行目の継続（結合元なし）とその下の継続
 "orphan_first": [row([c('',vmerge='continue'), c('B')]), row([c('X',vmerge='continue'), c('D')]), row([c('E'), c('F')])],
 # 見出し行と本文の境目で幅の違う継続
 "head_mismatch": [row([c('H1',span=2,vmerge='restart'), c('H2')], header=True), row([c('',vmerge='continue'), c('x'), c('y')]), row([c('a'), c('b'), c('c')])],
 # 本文の 1 行目にセルがない（見出し 1 行 + セルのない行 + 本文）
 "cellless_row": [row([c('H1'), c('H2')], header=True), "<w:tr/>", row([c('a'), c('b')])],
 # 見出し + 本文がセルのない行だけ
 "cellless_only_body": [row([c('H1'), c('H2')], header=True), "<w:tr/>"],
 # gridBefore だけの継続行（すべて継続 + gridBefore）
 "dropped_with_before": [row([c('A'), c('B',vmerge='restart'), c('C',vmerge='restart')]), row([c('',vmerge='continue'), c('',vmerge='continue')], before=1), row([c('D'), c('E'), c('F')])],
 # docx がもともと不ぞろい（2 列と 3 列）
 "irregular": [row([c('A'), c('B')]), row([c('C'), c('D'), c('E')])],
 # 不ぞろい + 結合
 "irregular_merge": [row([c('A',vmerge='restart'), c('B'), c('B2')]), row([c('',vmerge='continue'), c('D')])],
 # 削除された結合元の行（変更履歴）: 1 行目が削除（空）で restart、2 行目が継続
 "deleted_top": [row([c('A'), c('B')]), "<w:tr><w:trPr><w:del w:id=\"91\" w:author=\"x\" w:date=\"2024-01-01T00:00:00Z\"/></w:trPr>" + c('',vmerge='restart') + c('') + "</w:tr>", row([c('Q',vmerge='continue'), c('R')]), row([c('',vmerge='continue'), c('S')])],
 # gridspan 負
 "span_neg": [row([raw('A','<w:gridSpan w:val="-1"/>'), c('B')]), row([c('C'), c('D')])],
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
