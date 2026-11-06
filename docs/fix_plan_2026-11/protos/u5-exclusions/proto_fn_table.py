"""設計の試作（リポジトリは変えない。実行中のモジュールの関数を差し替えるだけ）: 注の節の表を注の中に出す。

確かめること: 不変性チェック・DTD・リンク（表のセルの中の注番号をリンクにしない）・表の ID。
"""
import inspect
import sys
import textwrap
from pathlib import Path

ROOT = Path("/home/user/jstgxmlcng_JASME")
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
from lxml import etree

import make_fixtures as mf
from jasme_jats import article, builder, linker, structure
from jasme_jats.config import ArticleMeta, JournalConfig
from jasme_jats.pipeline import Options, convert
from jasme_jats.report import actions

# FnNode.tables（[(k, TableNode)]）。dataclass に後から足す代わりに、既定値の属性で代用
article.FnNode.tables = ()


def patch(mod, cls, name, pairs):
    src = inspect.getsource(getattr(cls, name))
    for old, new in pairs:
        assert src.count(old) == 1, (name, old)
        src = src.replace(old, new)
    ns = dict(vars(mod))
    exec("class _X:\n" + src, ns)
    setattr(cls, name, ns["_X"].__dict__[name])


patch(structure, structure.Classifier, "build_back", [
    ("        current_fn = None\n        for b, role in items:",
     "        current_fn = None\n        pending = []\n"
     "        def flush():\n"
     "            for t in pending:\n"
     "                for p in t.paragraphs():\n"
     "                    plan.exclude_blank(p) if p.is_blank else plan.exclude(p, '後付けの位置づけが不明な表の文字')\n"
     "            pending.clear()\n"
     "        for b, role in items:"),
    ("                target = {\"notes\": plan.notes, \"ack\": plan.ack}.get(state)",
     "                if state == 'fn':\n"
     "                    if current_fn is None:\n"
     "                        pending.append(b)\n"
     "                    else:\n"
     "                        cap = None\n"
     "                        if len(current_fn.paras) >= 2 and self.role_of(current_fn.paras[-1]) == 'table_caption':\n"
     "                            cap = current_fn.paras.pop()\n"
     "                        current_fn.tables = list(current_fn.tables) + [(len(current_fn.paras), TableNode(table=b, caption=cap))]\n"
     "                    continue\n"
     "                target = {\"notes\": plan.notes, \"ack\": plan.ack}.get(state)"),
    ("                current_fn = None\n                continue",
     "                flush()\n                current_fn = None\n                continue"),
    ("                    plan.fns.append(current_fn)\n",
     "                    plan.fns.append(current_fn)\n"
     "                    if pending:\n"
     "                        current_fn.tables = [(0, TableNode(table=t)) for t in pending]\n"
     "                        pending.clear()\n"),
    ("            else:\n                plan.exclude(b, \"位置づけが不明な段落（本文と後付けの間）\")",
     "            else:\n                plan.exclude(b, \"位置づけが不明な段落（本文と後付けの間）\")\n        flush()"),
])

patch(structure, structure.Classifier, "assign_ids", [
    ("        for app in plan.apps:\n            walk(app.children)",
     "        for fn in plan.fns:\n            tabs.extend(t for _, t in fn.tables)\n"
     "        for app in plan.apps:\n            walk(app.children)"),
])

patch(builder, builder.Builder, "fn", [
    ("        for i, p in enumerate(fn.paras):\n            pe = _sub(el, \"p\")",
     "        tables = list(fn.tables)\n"
     "        for i, p in enumerate(fn.paras):\n"
     "            while tables and tables[0][0] == i:\n"
     "                self.table_wrap(_sub(el, 'p'), tables.pop(0)[1])\n"
     "            pe = _sub(el, \"p\")"),
    ("            self.em.span(pe, p, E.BACKP)",
     "            self.em.span(pe, p, E.BACKP)\n"
     "        for _, node in tables:\n"
     "            self.table_wrap(_sub(el, 'p'), node)"),
])

_orig_bp = linker.body_paragraphs


def body_paragraphs(plan):
    for p, w in _orig_bp(plan):
        yield p, w
        if w == "fn":
            pass
    for fn in plan.fns:
        for _, t in fn.tables:
            if t.caption is not None:
                yield t.caption, "caption"
            for p in t.table.paragraphs():
                yield p, "cell"


linker.body_paragraphs = body_paragraphs

j = JournalConfig.load()
meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12"})
W = Path(__file__).resolve().parent / "work"


def simple(b):
    return [mf.para(mf.S["sec1"], "１．検証"), mf.para(mf.S["body"], "本文の表1と表2を見よ。"),
            mf.para(mf.S["tab_cap"], "表1　本文の表"), mf.table([[mf.cell("本文の表"), mf.cell("1")]])]


cases = {
    "p_after_item": lambda b: simple(b) + [mf.para(mf.S["fn_head"], "注"), mf.para(mf.S["fn_body"], "1) 注の本文。"),
                                           mf.table([[mf.cell("注の表A"), mf.cell("2)")]]),
                                           mf.para(mf.S["fn_body"], "続きの段落。"),
                                           mf.para(mf.S["fn_body"], "2) 次の注。")],
    "p_first": lambda b: simple(b) + [mf.para(mf.S["fn_head"], "注"), mf.table([[mf.cell("注の表B"), mf.cell("4")]]),
                                      mf.para(mf.S["fn_body"], "1) 注の本文。")],
    "p_caption": lambda b: simple(b) + [mf.para(mf.S["fn_head"], "注"), mf.para(mf.S["fn_body"], "1) 注の本文。"),
                                        mf.para(mf.S["tab_cap"], "表2　注の表"),
                                        mf.table([[mf.cell("注の表C"), mf.cell("\u3000")]])],
    "p_alone": lambda b: simple(b) + [mf.para(mf.S["fn_head"], "注"), mf.table([[mf.cell("注の表D"), mf.cell("5")]])],
}
for name, body in cases.items():
    p = W / f"proto_{name}.docx"
    mf.make_article(p, "注の表の試作", body)
    res = convert(p, meta, j, Options(out_dir=W / f"proto_{name}", convert_metafiles=False))
    root = etree.fromstring(res.xml_path.read_bytes())
    fns = [etree.tostring(fn, encoding="unicode", with_tail=False) for fn in root.iter("fn")]
    xrefs = [(x.get("ref-type"), x.get("rid"), x.text) for x in root.iter("xref") if x.get("ref-type") in ("table", "fn")]
    print(name, dict(ok=res.ok, fid_ok=res.fidelity.ok, dtd=res.dtd_valid, dtd_err=res.dtd_errors[:2],
                     actions=[(a.level, a.key) for a in actions(res)],
                     excl=[(e.src, e.reason[:14]) for e in res.plan.exclusions if not e.blank and not e.reason.startswith("冒頭部")],
                     tables=[t.tid for t in res.plan.tables], xrefs=xrefs))
    for f in fns:
        print("   ", f.replace('xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:mml="http://www.w3.org/1998/Math/MathML" xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:ali="http://www.niso.org/schemas/ali/1.0/"', "")[:400])
