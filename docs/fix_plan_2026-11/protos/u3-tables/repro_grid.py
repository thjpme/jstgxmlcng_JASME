import sys, json
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path[:0] = ["/home/user/jstgxmlcng_JASME/tests", str(HERE)]
from lxml import etree
import make_fixtures as mf
from jasme_jats.config import ArticleMeta, JournalConfig
from jasme_jats.pipeline import convert, Options
from jasme_jats.report import actions
from shape import table_shape
journal = JournalConfig.load()
meta = ArticleMeta.from_dict({'volume':'31','issue':'1','fpage':'1','lpage':'12'})
c = mf.cell
def row(cells, before=0, after=0):
    trpr = ""
    if before or after:
        trpr = "<w:trPr>" + (f'<w:gridBefore w:val="{before}"/>' if before else "") + (f'<w:gridAfter w:val="{after}"/>' if after else "") \
               + (f'<w:wBefore w:w="{2000*before}" w:type="dxa"/>' if before else "") + (f'<w:wAfter w:w="{2000*after}" w:type="dxa"/>' if after else "") + "</w:trPr>"
    return "<w:tr>" + trpr + "".join(cells) + "</w:tr>"
CASES = {
 "before_plain": [row([c('A'),c('B'),c('C')]), row([c('D'),c('E')], before=1), row([c('F'),c('G'),c('H')])],
 "after_plain": [row([c('A'),c('B'),c('C')]), row([c('D'),c('E')], after=1), row([c('F'),c('G'),c('H')])],
 # 2 列目（グリッド列 1）が結合。2 行目は gridBefore=1 で、最初のセルが列 1 の継続
 "before_vmerge_lost": [row([c('A'),c('B',vmerge='restart'),c('C')]), row([c('',vmerge='continue'),c('E')], before=1), row([c('F'),c('G'),c('H')])],
 # 1 列目が結合元。2 行目は gridBefore=1 で、最初のセル（本当は列 1 の継続）が列 0 と数えられて 1 列目に結合される
 "before_vmerge_wrong": [row([c('A',vmerge='restart'),c('B',vmerge='restart'),c('C')]), row([c('',vmerge='continue'),c('E')], before=1), row([c('F'),c('G'),c('H')])],
}
for name, rows in CASES.items():
    d = HERE / "docx"; d.mkdir(exist_ok=True)
    path = d / f"{name}.docx"
    def body(b, rows=rows):
        return [mf.para(mf.S['sec1'], '１．検証'), mf.para(mf.S['body'], '表1に示す。'),
                mf.para(mf.S['tab_cap'], '表1　グリッドの検証'), mf.table_of_rows(rows, 3), mf.para(mf.S['body'], '以上。')]
    mf.make_article(path, 'グリッドの検証', body)
    res = convert(path, meta, journal, Options(out_dir=HERE / "out" / name, convert_metafiles=False))
    root = etree.fromstring(res.xml_path.read_bytes().split(b"\n", 2)[2])
    tbl = root.find('.//table-wrap/table')
    widths, problems = table_shape(tbl)
    x = etree.tostring(tbl, encoding='unicode'); x = x[x.index('<tbody'):]
    print(name, json.dumps(dict(fid_ok=res.fidelity.ok, dtd=res.dtd_valid, actions=[a.key for a in actions(res)],
               widths=widths, problems=problems, xml=x), ensure_ascii=False))
