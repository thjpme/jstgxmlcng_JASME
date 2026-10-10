"""Word の自動段落番号（numbering.xml）を、表示される文字列として再現する。

自動番号は docx の文字（w:t）ではなく Word が表示時に生成する。XML ではこれを
「生成文字」として区別して出力し、文字の不変性チェックの対象外であることをレポートに明記する。
"""
from __future__ import annotations

from .ooxml import w, wval

_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
_PAREN = "⑴⑵⑶⑷⑸⑹⑺⑻⑼⑽⑾⑿⒀⒁⒂⒃⒄⒅⒆⒇"
_AIUEO = "アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン"
_IROHA = "イロハニホヘトチリヌルヲワカヨタレソツネナラムウヰノオクヤマケフコエテアサキユメミシヱヒモセスン"
_KANJI = "〇一二三四五六七八九"
_KOU = "甲乙丙丁戊己庚辛壬癸"


def _roman(n: int) -> str:
    vals = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
            (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    out = ""
    for v, s in vals:
        while n >= v:
            out += s
            n -= v
    return out


def _letter(n: int) -> str:
    # a..z, aa..zz（Word の方式）
    if n <= 0:
        return ""
    k = (n - 1) % 26
    rep = (n - 1) // 26 + 1
    return chr(ord("a") + k) * rep


def _kanji(n: int) -> str:
    if n < 10:
        return _KANJI[n]
    if n < 100:
        t, o = divmod(n, 10)
        return ("" if t == 1 else _KANJI[t]) + "十" + (_KANJI[o] if o else "")
    return str(n)


def format_number(n: int, fmt: str) -> str:
    fw = str.maketrans("0123456789", "０１２３４５６７８９")
    if fmt in ("decimal", "", None):
        return str(n)
    if fmt == "decimalZero":
        return f"{n:02d}"
    if fmt in ("decimalFullWidth", "decimalFullWidth2"):
        return str(n).translate(fw)
    if fmt == "decimalHalfWidth":
        return str(n)
    if fmt == "upperRoman":
        return _roman(n)
    if fmt == "lowerRoman":
        return _roman(n).lower()
    if fmt == "upperLetter":
        return _letter(n).upper()
    if fmt == "lowerLetter":
        return _letter(n)
    if fmt == "decimalEnclosedCircle" and 1 <= n <= 20:
        return _CIRCLED[n - 1]
    if fmt == "decimalEnclosedParen" and 1 <= n <= 20:
        return _PAREN[n - 1]
    if fmt in ("aiueo", "aiueoFullWidth") and 1 <= n <= len(_AIUEO):
        return _AIUEO[n - 1]
    if fmt in ("iroha", "irohaFullWidth") and 1 <= n <= len(_IROHA):
        return _IROHA[n - 1]
    if fmt in ("japaneseCounting", "ideographDigital", "japaneseDigitalTenThousand"):
        return _kanji(n)
    if fmt in ("ideographTraditional",) and 1 <= n <= 10:
        return _KOU[n - 1]
    if fmt == "none":
        return ""
    return str(n)


_BULLET_MAP = {"\uf0b7": "•", "\uf0a7": "▪", "\uf076": "❖", "\uf0d8": "➢", "\uf0fc": "✓", "\uf06c": "●", "o": "o"}


class Numbering:
    def __init__(self, root):
        self.abstract = {}   # abstractNumId -> {ilvl: dict}
        self.nums = {}       # numId -> (abstractNumId, {ilvl: startOverride})
        self.counters = {}   # numId -> {ilvl: n}
        if root is None:
            return
        for an in root.findall(w("abstractNum")):
            aid = an.get(w("abstractNumId"))
            levels = {}
            for lvl in an.findall(w("lvl")):
                il = int(lvl.get(w("ilvl"), "0"))
                levels[il] = {
                    "start": int(wval(lvl.find(w("start")), "1") or 1),
                    "fmt": wval(lvl.find(w("numFmt")), "decimal"),
                    "text": wval(lvl.find(w("lvlText")), ""),
                }
            self.abstract[aid] = levels
        for num in root.findall(w("num")):
            nid = num.get(w("numId"))
            aid = wval(num.find(w("abstractNumId")))
            overrides = {}
            for ov in num.findall(w("lvlOverride")):
                il = int(ov.get(w("ilvl"), "0"))
                so = ov.find(w("startOverride"))
                if so is not None:
                    overrides[il] = int(wval(so, "1"))
            self.nums[nid] = (aid, overrides)

    def label(self, num_id: str, ilvl: int) -> str:
        """番号付き段落が1つ現れるたびに呼ぶ。表示される番号文字列を返す。"""
        if num_id in (None, "0") or num_id not in self.nums:
            return ""
        aid, overrides = self.nums[num_id]
        levels = self.abstract.get(aid, {})
        if ilvl not in levels:
            return ""
        cnt = self.counters.setdefault(num_id, {})
        start = overrides.get(ilvl, levels[ilvl]["start"])
        cnt[ilvl] = cnt.get(ilvl, start - 1) + 1
        for deeper in [k for k in cnt if k > ilvl]:
            del cnt[deeper]
        lv = levels[ilvl]
        if lv["fmt"] == "bullet":
            t = lv["text"]
            return "".join(_BULLET_MAP.get(c, c) for c in t)
        text = lv["text"]
        for k in range(9):
            token = f"%{k + 1}"
            if token in text:
                if k in levels:
                    st = overrides.get(k, levels[k]["start"])
                    n = cnt.get(k, st)
                    text = text.replace(token, format_number(n, levels[k]["fmt"]))
                else:
                    text = text.replace(token, "")
        return text

    def is_bullet(self, num_id: str, ilvl: int) -> bool:
        if num_id not in self.nums:
            return False
        aid, _ = self.nums[num_id]
        lv = self.abstract.get(aid, {}).get(ilvl)
        return bool(lv and lv["fmt"] == "bullet")
