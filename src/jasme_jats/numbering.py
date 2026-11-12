"""Word の自動段落番号（numbering.xml）を、表示される文字列として再現する。

自動番号は docx の文字（w:t）ではなく Word が表示時に生成する。XML ではこれを
「生成文字」として区別して出力し、文字の不変性チェックの対象外であることをレポートに明記する。
"""
from __future__ import annotations

from .ooxml import FONT_DISPLAY, LEGACY_BULLETS, SYMBOL_TABLES, map_symbol_text, w, wval

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


DEFAULT_LEVEL = {"start": 1, "fmt": "decimal", "text": ""}


def _lvl_font(lvl):
    """段の番号・記号の書式（w:lvl/w:rPr/w:rFonts）のフォント名（ascii か hAnsi）。なければ None。"""
    rf = lvl.find(f"{w('rPr')}/{w('rFonts')}")
    if rf is None:
        return None
    return (rf.get(w("ascii")) or rf.get(w("hAnsi")) or "").strip()


def _level(lvl) -> dict:
    """abstractNum の段の定義（w:lvl）。子要素がなければ既定値（DEFAULT_LEVEL と同じ）。番号の書式のフォント（w:rPr/w:rFonts）が
    書かれていれば "font" も入る（箇条書きの記号の表を決める）。"""
    out = {"start": int(wval(lvl.find(w("start")), "1") or 1),
           "fmt": wval(lvl.find(w("numFmt")), "decimal"),
           "text": wval(lvl.find(w("lvlText")), "")}
    font = _lvl_font(lvl)
    if font:
        out["font"] = font
    return out


def _level_present(lvl) -> dict:
    """num の w:lvlOverride/w:lvl の、書かれている子要素（start・numFmt・lvlText・番号の書式のフォント）だけの dict。"""
    out = {}
    el = lvl.find(w("start"))
    if el is not None:
        out["start"] = int(wval(el, "1") or 1)
    el = lvl.find(w("numFmt"))
    if el is not None:
        out["fmt"] = wval(el, "decimal")
    el = lvl.find(w("lvlText"))
    if el is not None:
        out["text"] = wval(el, "")
    font = _lvl_font(lvl)
    if font is not None:
        out["font"] = font
    return out


def bullet_text(font: str, text: str):
    """箇条書きの記号 text（w:lvlText）を、表示される文字にする。戻り値: (文字, [(フォントの名前, 元の文字, 置き換えた文字)])。

    段の書式のフォントが記号フォント（Symbol・Wingdings 系。ooxml.SYMBOL_TABLES）なら、そのフォントの表（ooxml.symbol_char と同じ）で
    私用領域の符号を Unicode にする。フォントが記号フォントでない（指定がない・Arial など）ときは、古い対応（ooxml.LEGACY_BULLETS。
    よく使う 6 つの符号。フォントを見ずに置き換える）にする。表にない符号はそのまま（私用領域の文字が残れば守りが知らせる）。
    """
    if SYMBOL_TABLES.get((font or "").strip().lower()) is not None:
        new, pairs = map_symbol_text(font, text)
        name = FONT_DISPLAY[font.strip().lower()]
        return new, [(name, old, to) for old, to in pairs]
    out, rep = [], []
    for c in text:
        to = LEGACY_BULLETS.get(c)
        out.append(to or c)
        if to:
            rep.append(((font or "").strip(), c, to))
    return "".join(out), rep


class Numbering:
    def __init__(self, root, styles_root=None):
        """root は numbering.xml、styles_root は styles.xml（番号付けスタイル経由の定義 w:numStyleLink をたどるときに使う。なくてもよい）。"""
        self.abstract = {}   # abstractNumId -> {ilvl: dict}
        self.nums = {}       # numId -> (abstractNumId, {ilvl: startOverride})
        self.counters = {}   # abstractNumId -> {ilvl: n}（Word は abstractNum ごとに数え、同じ abstractNum を使う num は番号を共有する）
        self.restarts = {}   # abstractNumId -> {ilvl: n}（w:startOverride で振り直した段の、次に数え始めるときの開始番号。
        # 数えの初期値と、上位の段が未出現のときの %n の値に使う。次の振り直しまで残る）
        self._started = set()  # 最初の段落を数えた（w:startOverride を適用した）numId
        self.lvl_overrides = {}  # numId -> {ilvl: 書かれた子要素だけの段の定義}
        # 直前の label が、箇条書きの記号を置き換えたもの [(フォントの名前, 元の文字, 置き換えた文字)]（docx_reader が記録する）
        self.replaced = []
        self.font = ""      # 直前の label の段の書式のフォント名（箇条書きのとき。書かれたまま）
        if root is None:
            return
        for an in root.findall(w("abstractNum")):
            aid = an.get(w("abstractNumId"))
            levels = {}
            for lvl in an.findall(w("lvl")):
                il = int(lvl.get(w("ilvl"), "0"))
                levels[il] = _level(lvl)
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
                lv = ov.find(w("lvl"))
                if lv is not None:
                    self.lvl_overrides.setdefault(nid, {})[il] = _level_present(lv)
            self.nums[nid] = (aid, overrides)
        self._follow_style_links(root, styles_root)

    def _follow_style_links(self, root, styles_root):
        """番号付けスタイル経由の定義（abstractNum の w:numStyleLink）の段の定義を、リンク先から得る。

        ECMA-376: w:numStyleLink の abstractNum は自分では段を定義せず、styles.xml の番号付けスタイル（w:type="numbering"）の
        w:pPr/w:numPr/w:numId が指す num の abstractNum（w:styleLink でそのスタイルを名乗る定義）の段を使う。リンク先がまた
        w:numStyleLink なら、さらにたどる。循環・見つからない・段の定義がないときは、何もしない（自分の段の定義のまま。例外にしない）。
        """
        links = {an.get(w("abstractNumId")): wval(an.find(w("numStyleLink"))) for an in root.findall(w("abstractNum"))}
        links = {a: s for a, s in links.items() if s}
        if not links or styles_root is None:
            return
        style_num = {}
        for st in styles_root.findall(w("style")):
            if st.get(w("type")) == "numbering":
                nid = wval(st.find(f"{w('pPr')}/{w('numPr')}/{w('numId')}"))
                if nid:
                    style_num[st.get(w("styleId"))] = nid

        def resolve(aid, seen):
            if aid in seen:
                return None
            seen = seen | {aid}
            if aid not in links:
                return self.abstract.get(aid) or None
            nid = style_num.get(links[aid])
            target = self.nums.get(nid, (None,))[0] if nid else None
            return resolve(target, seen) if target is not None else None

        resolved = {aid: resolve(aid, frozenset()) for aid in links}
        for aid, levels in resolved.items():
            if levels:
                self.abstract[aid] = levels

    def _levels(self, num_id) -> dict:
        """num の段の定義: abstractNum の段に、w:lvlOverride/w:lvl に書かれた子要素を重ねる。

        w:startOverride は含めない（その num を最初に使った段落で、数えを振り直すだけ。`label`）。
        """
        aid = self.nums[num_id][0]
        base = self.abstract.get(aid, {})
        levels = dict(base)   # self.abstract の dict は共有されているので書き換えない
        for il, ov in self.lvl_overrides.get(num_id, {}).items():
            levels[il] = {**base.get(il, DEFAULT_LEVEL), **ov}
        return levels

    def snapshot(self):
        """数え方（counters・restarts と、w:startOverride を適用済みの num）の写し。`restore` で戻す。"""
        return ({a: dict(c) for a, c in self.counters.items()}, {a: dict(c) for a, c in self.restarts.items()},
                set(self._started))

    def restore(self, snap) -> None:
        """`snapshot` の写しの状態に戻す（写しは書き換えない。何度戻してもよい）。"""
        counters, restarts, started = snap
        self.counters = {a: dict(c) for a, c in counters.items()}
        self.restarts = {a: dict(c) for a, c in restarts.items()}
        self._started = set(started)

    def label(self, num_id: str, ilvl: int) -> str:
        """番号付き段落が1つ現れるたびに呼ぶ。表示される番号文字列を返す。

        Word と同じく、abstractNum ごとに数える（同じ abstractNum を使う num は番号を共有する）。w:startOverride は、その num を
        最初に使った段落で、その段（と深い段）を振り直す（数えを消し、開始番号を `restarts` に置く。浅い段から処理する）だけで、後で元の num に戻った段落は、
        振り直した後の続きになる。上位の段が未出現のときの %n は、`restarts` の開始番号（なければ段の start）。
        """
        self.replaced = []
        self.font = ""
        if num_id in (None, "0") or num_id not in self.nums:
            return ""
        levels = self._levels(num_id)
        if ilvl not in levels:
            return ""
        aid, starts = self.nums[num_id]
        key = aid if aid is not None else ("num", num_id)
        cnt = self.counters.setdefault(key, {})
        rst = self.restarts.setdefault(key, {})
        if num_id not in self._started:
            self._started.add(num_id)
            # 浅い段から振り直す（書かれた順で結果を変えない）。その段と深い段の数えを消し、開始番号は次に数え始めるときの値にする
            for il in sorted(starts):
                for k in [k for k in list(cnt) + list(rst) if k >= il]:
                    cnt.pop(k, None)
                    rst.pop(k, None)
                rst[il] = starts[il]
        start = rst.get(ilvl, levels[ilvl]["start"])
        cnt[ilvl] = cnt.get(ilvl, start - 1) + 1
        for deeper in [k for k in cnt if k > ilvl]:
            del cnt[deeper]
        lv = levels[ilvl]
        if lv["fmt"] == "bullet":
            self.font = lv.get("font", "")
            shown, self.replaced = bullet_text(self.font, lv["text"])
            return shown
        text = lv["text"]
        for k in range(9):
            token = f"%{k + 1}"
            if token in text:
                if k in levels:
                    n = cnt.get(k, rst.get(k, levels[k]["start"]))
                    text = text.replace(token, format_number(n, levels[k]["fmt"]))
                else:
                    text = text.replace(token, "")
        return text

    def is_bullet(self, num_id: str, ilvl: int) -> bool:
        if num_id not in self.nums:
            return False
        lv = self._levels(num_id).get(ilvl)
        return bool(lv and lv["fmt"] == "bullet")
