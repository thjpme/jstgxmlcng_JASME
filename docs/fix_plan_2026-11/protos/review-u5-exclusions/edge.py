import sys
sys.argv = ["x"]
exec(open("proto_base.py").read())
from jasme_jats.report import actions
W = Path("/tmp/claude-0/-home-user-jstgxmlcng-JASME/72d6c468-bb77-50d1-8396-803f4558807a/scratchpad/review-u5-exclusions/work")
W.mkdir(exist_ok=True)
def simple(b):
    return [mf.para(mf.S["sec1"], "１．検証"), mf.para(mf.S["body"], "本文の表1と表2を見よ。注1)。"),
            mf.para(mf.S["tab_cap"], "表1　本文の表"), mf.table([[mf.cell("本文の表"), mf.cell("1")]])]
cases = {
  # 注の見出しの直後にキャプション、表、その後に 1)
  "cap_first": lambda b: simple(b) + [mf.para(mf.S["fn_head"], "注"), mf.para(mf.S["tab_cap"], "表2　注の表"),
                                      mf.table([[mf.cell("注の表C"), mf.cell("x")]]), mf.para(mf.S["fn_body"], "1) 注の本文。")],
  # 表キャプションの番号が本文と重なる
  "cap_dup": lambda b: simple(b) + [mf.para(mf.S["fn_head"], "注"), mf.para(mf.S["fn_body"], "1) 注の本文。"),
                                    mf.para(mf.S["tab_cap"], "表1　注の表"), mf.table([[mf.cell("注の表C"), mf.cell("x")]])],
  # 注の表の後ろに引用文献の見出し（pending のまま）
  "alone_then_refs": lambda b: simple(b) + [mf.para(mf.S["fn_head"], "注"), mf.table([[mf.cell("注の表D"), mf.cell("5")]]),
                                            mf.para(mf.S["ref_head"], "引用文献"), mf.para(mf.S["ref"], "山田太郎（2020）．本．出版社．")],
}
for name, body in cases.items():
    p = W / f"e_{name}.docx"
    mf.make_article(p, "注の表の試作", body)
    res = convert(p, meta, j, Options(out_dir=W / f"e_{name}", convert_metafiles=False))
    root = etree.fromstring(res.xml_path.read_bytes())
    xrefs = [(x.get("ref-type"), x.get("rid"), x.text) for x in root.iter("xref") if x.get("ref-type") in ("table", "fn")]
    print(name, dict(ok=res.ok, dtd=res.dtd_valid, actions=[(a.level, a.key) for a in actions(res)],
                     excl=[(e.src, e.reason[:14]) for e in res.plan.exclusions + res.info.exclusions if not e.blank and not e.reason.startswith("冒頭部")] if hasattr(res,'info') else [(e.src, e.reason[:14]) for e in res.plan.exclusions if not e.blank and not e.reason.startswith("冒頭部")],
                     fns=[(f.fid, f.number, [q.src for q in f.paras], [(k, t.tid, t.caption.src if t.caption else None) for k, t in f.tables]) for f in res.plan.fns],
                     tables=[(t.tid, t.number) for t in res.plan.tables], xrefs=xrefs))
    print("   decisions:", [d.message[:50] for d in res.plan.decisions if d.category in ("table","note")])
