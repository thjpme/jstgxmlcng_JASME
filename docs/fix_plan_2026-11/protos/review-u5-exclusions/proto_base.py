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
j = JournalConfig.load()
meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12"})
