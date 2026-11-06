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
CASES = {
 # 1: 2 列の両方が 2 行目で継続（既存の再現と同じ）
 "both_cont": dict(rows=[[c('A',vmerge='restart'),c('B',vmerge='restart')],[c('',vmerge='continue'),c('',vmerge='continue')],[c('C'),c('D')]]),
 # 2: 1 列目が 3 行とも結合、2 列目は 2 行目だけ継続
 "col1_all_col2_row2": dict(rows=[[c('A',vmerge='restart'),c('B',vmerge='restart')],[c('',vmerge='continue'),c('',vmerge='continue')],[c('',vmerge='continue'),c('D')]]),
 # 3: 継続側のセルに文字がある
 "cont_text": dict(rows=[[c('A',vmerge='restart'),c('B',vmerge='restart')],[c('A2',vmerge='continue'),c('B2',vmerge='continue')],[c('C'),c('D')]]),
 # 4: 見出し行から本文の行へ続く結合
 "head_to_body": dict(rows=[[c('H1',vmerge='restart'),c('H2')],[c('',vmerge='continue'),c('H3')],[c('',vmerge='continue'),c('X')],[c('Y'),c('Z')]], header_rows=2),
 # 5: 見出し行 1 行が本文へ結合、見出し行のすべてが restart → 本文の 1 行目がすべて継続
 "head_all_to_body": dict(rows=[[c('H1',vmerge='restart'),c('H2',vmerge='restart')],[c('',vmerge='continue'),c('',vmerge='continue')],[c('Y'),c('Z')]], header_rows=1),
 # 6: 正常（比較用。sample_full と同じ形）
 "normal": dict(rows=[[c('h1'),c('h2'),c('h3')],[c('a',vmerge='restart'),c('b'),c('c')],[c('',vmerge='continue'),c('d'),c('e')],[c('f'),c('g',span=2)]], header_rows=1),
 # 7: gridSpan と vMerge の幅が違う（結合元 2 列、継続 1 列 + 1 セル）
 "span_mismatch_wide_top": dict(rows=[[c('A',span=2,vmerge='restart'),c('B')],[c('',vmerge='continue'),c('x'),c('y')],[c('C'),c('D'),c('E')]]),
 # 8: 結合元 1 列、継続 2 列
 "span_mismatch_narrow_top": dict(rows=[[c('A',vmerge='restart'),c('B'),c('Bb')],[c('',span=2,vmerge='continue'),c('y')],[c('C'),c('D'),c('E')]]),
 # 9: 横に広いセルが、結合元の列を覆った後で継続が出る（owner が開始列だけで消える）
 "owner_not_cleared": dict(rows=[[c('X'),c('A',vmerge='restart')],[c('C',span=2)],[c('Y'),c('',vmerge='continue')]]),
}
out = {}
for name, spec in CASES.items():
    d = HERE / "docx"; d.mkdir(exist_ok=True)
    path = d / f"{name}.docx"
    def body(b, spec=spec):
        return [mf.para(mf.S['sec1'], '１．検証'), mf.para(mf.S['body'], '表1に示す。'),
                mf.para(mf.S['tab_cap'], '表1　結合の検証'), mf.table(spec["rows"], header_rows=spec.get("header_rows", 0)),
                mf.para(mf.S['body'], '以上。')]
    mf.make_article(path, '結合の検証', body)
    res = convert(path, meta, journal, Options(out_dir=HERE / "out" / name, convert_metafiles=False))
    root = etree.fromstring(res.xml_path.read_bytes().split(b"\n", 2)[2])
    tbl = root.find('.//table-wrap/table')
    widths, problems = table_shape(tbl)
    out[name] = dict(fid_ok=res.fidelity.ok, dtd=res.dtd_valid, actions=[a.key for a in actions(res)],
                     docx_rows=len(spec["rows"]), out_rows=len(tbl.findall('.//tr')), widths=widths, problems=problems,
                     xml=etree.tostring(tbl, encoding='unicode'))
for k, v in out.items():
    print(k, json.dumps(v, ensure_ascii=False))
