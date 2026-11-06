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

from jasme_jats import article, builder, linker, structure

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


from jasme_jats import report
report.body_paragraphs = body_paragraphs

# ---- 冒頭部の装飾の判定（誌名行・記号だけの行は意図した除外、それ以外は位置づけが不明）
import re, unicodedata
FRONT_OTHER = "冒頭部の、題目・著者以外の段落（テンプレートの装飾・誌名行と違う）"
JOURNAL_LINES = {"全国数学教育学会誌数学教育学研究"}


def front_decoration(text):
    t = re.sub(r"\s", "", unicodedata.normalize("NFKC", text))
    return not t or t in JOURNAL_LINES or not any(unicodedata.category(c)[0] in "LN" for c in t)


patch(structure, structure.Classifier, "build_front_ja", [
    ('                plan.exclude(b, "冒頭部のテンプレート装飾・誌名行など（題目・著者以外の段落）")',
     '                plan.exclude(b, "冒頭部のテンプレート装飾・誌名行など（題目・著者以外の段落）" if FD(_para_text(b)) else FO)'),
])
structure.FD, structure.FO = front_decoration, FRONT_OTHER
# build_front_ja was exec'd with a copy of module namespace; inject names into its globals
structure.Classifier.build_front_ja.__globals__["FD"] = front_decoration
structure.Classifier.build_front_ja.__globals__["FO"] = FRONT_OTHER

UNSURE = {FRONT_OTHER, "冒頭部の表（著者表以外）の文字", "著者表の中の、所属・著者名以外の文字", "後付けの位置づけが不明な表の文字",
          "位置づけが不明な段落（本文と後付けの間）", "英文著者表の中の、所属・著者名以外の文字", "英文部分の表（著者表以外）の文字",
          "英文部分の、題目・著者・要旨以外の段落"}
EN = {"英文部分の表（著者表以外）の文字", "英文部分の、題目・著者・要旨以外の段落"}


def _missing(r):
    if r.plan.abstract:
        return []
    return [(s, t) for s, why, t in r.fidelity.excluded if why in EN and t.strip()]


def _abstract_missing_action(r):
    rows = _missing(r)
    if not rows:
        return None
    return report.Action(report.NEEDS_ACTION, "abstract_missing", top="> **要対応: 英文要旨が見つかりません**",
                         checklist="- [ ] 英文要旨", box_title="英文要旨が見つかりません（要対応）", box_detail="x", cli="要対応: 英文要旨")


def _unsure_action(r):
    miss = {s for s, _ in _missing(r)}
    rows = [(s, why, t) for s, why, t in r.fidelity.excluded if why in UNSURE and t.strip() and s not in miss]
    if not rows:
        return None
    return report.Action(report.TO_CHECK, "excluded_unsure", top="> **要確認: 位置を決められず出力していない段落**",
                         checklist="- [ ] 位置づけ", box_title="位置を決められない段落（要確認）", box_detail="x", cli="要確認: 位置")


_orig_actions = report.actions


def actions(r):
    out = _orig_actions(r)
    extra = [a for a in (_abstract_missing_action(r), _unsure_action(r)) if a is not None]
    return out[:1] + [a for a in extra if a.level == report.NEEDS_ACTION] + out[1:] + [a for a in extra if a.level != report.NEEDS_ACTION]


report.actions = actions
import jasme_jats.pipeline as _pl
_pl.actions = actions
for mod in list(sys.modules.values()):
    if getattr(mod, "__name__", "").startswith(("jasme_jats", "test_")) and getattr(mod, "actions", None) is _orig_actions:
        mod.actions = actions
