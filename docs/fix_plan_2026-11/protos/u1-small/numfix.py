"""R6 の直し方の試作（scratchpad だけ。リポジトリは変えない）。"""
from jasme_jats import numbering as N
from jasme_jats.ooxml import w, wval

def _level(lvl):
    return {"start": int(wval(lvl.find(w("start")), "1") or 1),
            "fmt": wval(lvl.find(w("numFmt")), "decimal"),
            "text": wval(lvl.find(w("lvlText")), "")}

class FixedNumbering(N.Numbering):
    def __init__(self, root, styles_root=None):
        super().__init__(root, styles_root)
        self.lvl_over = {}
        if root is None:
            return
        for num in root.findall(w("num")):
            nid = num.get(w("numId"))
            for ov in num.findall(w("lvlOverride")):
                lv = ov.find(w("lvl"))
                if lv is not None:
                    self.lvl_over.setdefault(nid, {})[int(ov.get(w("ilvl"), "0"))] = _level(lv)

    def _effective(self, num_id):
        aid, starts = self.nums[num_id]
        levels = dict(self.abstract.get(aid, {}))
        levels.update(self.lvl_over.get(num_id, {}))
        return {il: (dict(lv, start=starts[il]) if il in starts else lv) for il, lv in levels.items()}

    def label(self, num_id, ilvl):
        if num_id in (None, "0") or num_id not in self.nums:
            return ""
        levels = self._effective(num_id)
        if ilvl not in levels:
            return ""
        cnt = self.counters.setdefault(num_id, {})
        cnt[ilvl] = cnt.get(ilvl, levels[ilvl]["start"] - 1) + 1
        for deeper in [k for k in cnt if k > ilvl]:
            del cnt[deeper]
        lv = levels[ilvl]
        if lv["fmt"] == "bullet":
            return "".join(N._BULLET_MAP.get(c, c) for c in lv["text"])
        text = lv["text"]
        for k in range(9):
            token = f"%{k + 1}"
            if token in text:
                if k in levels:
                    text = text.replace(token, N.format_number(cnt.get(k, levels[k]["start"]), levels[k]["fmt"]))
                else:
                    text = text.replace(token, "")
        return text

def install():
    from jasme_jats import docx_reader
    docx_reader.Numbering = FixedNumbering
