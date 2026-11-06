"""検出の試作（monkeypatch。リポジトリは変えない）。

上書きが起きる箇所で「その段落が出力も除外もされなくなる」ときだけ記録する:
- build_back: plan.notes / plan.ack / plan.fn_heading / plan.ref_heading（と、一覧の外の plan.abstract_heading）を、前の値があるのに置き換える。
  前の節の段落（見出し＋付記・謝辞なら中身）のうち空白だけでないものが落ちる。すべて空白だけなら exclude_blank して記録しない。
- author_paragraph_ja: 著者に付いていない所属を新しい所属で置き換える／最後に著者に付かない所属が残る。
- read_author_table_ja: 著者に付いていない行の所属を次の行の所属で置き換える／表の最後に残る。
"""
from dataclasses import dataclass, field

from jasme_jats import structure
from jasme_jats.article import ArticlePlan
from jasme_jats.model import Para

WATCH = {"notes": "notes", "ack": "ack", "fn_heading": "fn", "ref_heading": "refs", "abstract_heading": "abstract"}


@dataclass
class Conflict:
    kind: str           # notes / ack / fn / refs / abstract / aff
    lost: list          # 落ちる段落 ID
    by: str             # 置き換えた段落 ID（最後に残った所属なら ""）
    first: str = ""


def _lost_paras(old):
    if isinstance(old, Para):
        return [old]
    out = [old.heading]
    for c in old.children:
        out += structure.Classifier.node_paras(c)
    return out


class TrackingPlan(ArticlePlan):
    def __setattr__(self, name, value):
        if name in WATCH and value is not None and self.__dict__.get(name) is not None:
            old = self.__dict__[name]
            paras = _lost_paras(old)
            lost = [p for p in paras if not p.is_blank]
            new = value if isinstance(value, Para) else value.heading
            if lost:
                self.__dict__.setdefault("_conflicts", []).append(Conflict(WATCH[name], [p.src for p in lost], new.src))
            else:
                for p in paras:
                    self.exclude_blank(p)
        object.__setattr__(self, name, value)


structure.ArticlePlan = TrackingPlan


def author_paragraph_ja(self, p, role):
    if not hasattr(self, "_loose_affs"):
        self._loose_affs, self._loose_used = [], True
    if p.is_blank:
        self.plan.exclude_blank(p)
        return
    if role == "aff_ja":
        if self._loose_affs and not self._loose_used:
            self.plan.__dict__.setdefault("_conflicts", []).append(Conflict("aff", [x.src for x in self._loose_affs], p.src))
        self._loose_affs, self._loose_used = [p], False
    else:
        self.add_author_ja(p, self._loose_affs)
        self._loose_used = True


def read_author_table_ja(self, t):
    current_affs, used = [], True
    for row in t.rows:
        row_affs, row_names = [], []
        for c in row.cells:
            for blk in c.blocks:
                paras = [blk] if isinstance(blk, Para) else list(blk.paragraphs())
                for p in paras:
                    r = self.role_of(p)
                    self.plan.region[p.src] = "authors"
                    p.role = p.role or r
                    if p.is_blank:
                        self.plan.exclude_blank(p)
                        continue
                    if r == "aff_ja":
                        row_affs.append(p)
                    elif r == "author_ja":
                        row_names.append(p)
                    else:
                        self.plan.exclude(p, "著者表の中の、所属・著者名以外の文字")
        if row_affs:
            if current_affs and not used:
                self.plan.__dict__.setdefault("_conflicts", []).append(
                    Conflict("aff", [x.src for x in current_affs], row_affs[0].src))
            current_affs, used = row_affs, False
        for n in row_names:
            self.add_author_ja(n, current_affs)
            used = True
    if current_affs and not used:
        self.plan.__dict__.setdefault("_conflicts", []).append(Conflict("aff", [x.src for x in current_affs], ""))


_orig_front = structure.Classifier.build_front_ja


def build_front_ja(self, items):
    _orig_front(self, items)
    if getattr(self, "_loose_affs", None) and not self._loose_used:
        self.plan.__dict__.setdefault("_conflicts", []).append(Conflict("aff", [x.src for x in self._loose_affs], ""))


structure.Classifier.author_paragraph_ja = author_paragraph_ja
structure.Classifier.read_author_table_ja = read_author_table_ja
structure.Classifier.build_front_ja = build_front_ja


def conflicts(plan):
    return plan.__dict__.get("_conflicts", [])
