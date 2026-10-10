"""Word の数式（OMML）を MathML 2.0（JATS 1.1 の DTD が採用する版）に変換する。

docx の数式中の文字（m:t）は、MathML のトークン要素（mi / mn / mo / mtext）にそのまま入れる。
括弧の種類や積分記号のように OMML では属性で表される記号は、MathML では mo 要素として現れるため
jx:implicit="1" を付けて区別する（文字の不変性チェックではこれを除いて比較する）。
"""
from __future__ import annotations

from lxml import etree

from .ooxml import BR_TEXT_TYPES, M_NS, W_NS, m, sym_char, w
from .tracking import IMPLICIT, ORDER

MML_NS = "http://www.w3.org/1998/Math/MathML"


def mm(tag: str) -> str:
    return f"{{{MML_NS}}}{tag}"


OPERATORS = set("+-−±∓×÷=≠<>≤≥≦≧≈≒≡≢∼≃≅∝∞∂∇∑∏∐∫∬∭∮√∛∜…⋯⋮⋱()[]{}|‖,;:!/\\^_·∙∘∠⊥∥∴∵∈∉∋⊂⊃⊆⊇⊊⊋∪∩∧∨¬→←↑↓↔⇒⇐⇔↦⟶⟹°′″‴%＋－＝＜＞（）［］｛｝｜，：；！／・～〜'*∗⊕⊗⊙⌒△▽□■◯○●∀∃∄∅")
ACCENT_DISPLAY = {"\u0302": "^", "\u0303": "~", "\u0304": "¯", "\u0305": "¯", "\u0307": "˙", "\u0308": "¨",
                  "\u20d7": "→", "\u20d6": "←", "\u20e1": "↔", "\u0301": "´", "\u0300": "`", "\u030c": "ˇ",
                  "\u0306": "˘", "\u030a": "˚", "\u20db": "\u20db"}
INTEGRALS = set("∫∬∭∮∯∰∱∲∳")
SCR = {"double-struck": "double-struck", "script": "script", "fraktur": "fraktur",
       "sans-serif": "sans-serif", "monospace": "monospace", "roman": None}


def _val(el, tag, default=None):
    if el is None:
        return default
    c = el.find(m(tag))
    if c is None:
        return default
    v = c.get(m("val"))
    return default if v is None else v


def _onoff(el, tag) -> bool:
    if el is None:
        return False
    c = el.find(m(tag))
    if c is None:
        return False
    v = c.get(m("val"))
    return v is None or v.lower() in ("1", "on", "true")


class OmmlConverter:
    def __init__(self):
        self.warnings = []
        self.seq = 0

    # ---------------------------------------------------------------- tokens
    def tok(self, tag, text, **attrs):
        el = etree.Element(mm(tag))
        el.text = text
        el.set(ORDER, str(self.seq))
        self.seq += 1
        for k, v in attrs.items():
            if v is not None:
                el.set(k, v)
        return el

    def implicit(self, text, **attrs):
        el = etree.Element(mm("mo"))
        el.text = text
        el.set(IMPLICIT, "1")
        for k, v in attrs.items():
            if v is not None:
                el.set(k, v)
        return el

    def row(self, items):
        if len(items) == 1:
            return items[0]
        r = etree.Element(mm("mrow"))
        for it in items:
            r.append(it)
        return r

    def node(self, tag, *children, **attrs):
        el = etree.Element(mm(tag))
        for k, v in attrs.items():
            if v is not None:
                el.set(k, v)
        for c in children:
            el.append(c)
        return el

    # ---------------------------------------------------------------- entry
    def convert(self, el, display=False):
        """m:oMath または m:oMathPara を mml:math 要素に変換する。"""
        self.seq = 0
        math = etree.Element(mm("math"))
        if display:
            math.set("display", "block")
        if el.tag == m("oMathPara"):
            parts = []
            for ch in el:
                if ch.tag == m("oMath"):
                    parts.append(self.children(ch))
                elif ch.tag in (w("r"),):
                    parts.append(self.text_run(ch))
            if len(parts) == 1:
                content = parts[0]
            else:
                table = etree.Element(mm("mtable"))
                for p in parts:
                    table.append(self.node("mtr", self.node("mtd", self.row(p) if p else self.node("mrow"))))
                content = [table]
        else:
            content = self.children(el)
        if len(content) == 1:
            math.append(content[0])
        else:
            math.append(self.row(content) if content else self.node("mrow"))
        return math

    # ---------------------------------------------------------------- traversal
    def children(self, el):
        out = []
        for ch in el:
            tag = ch.tag
            if not isinstance(tag, str):
                continue
            if tag.endswith("Pr") or tag == m("ctrlPr"):
                continue
            if tag in (w("del"), w("moveFrom")):
                continue
            if tag in (w("ins"), w("moveTo"), w("sdt"), w("sdtContent"), w("customXml"), w("smartTag")):
                out.extend(self.children(ch))
                continue
            h = getattr(self, "h_" + etree.QName(tag).localname, None) if tag.startswith(f"{{{M_NS}}}") else None
            if tag == w("r"):
                out.extend(self.text_run(ch))
            elif h is not None:
                res = h(ch)
                if isinstance(res, list):
                    out.extend(res)
                elif res is not None:
                    out.append(res)
            elif tag.startswith(f"{{{W_NS}}}") and tag in (w("bookmarkStart"), w("bookmarkEnd"), w("proofErr")):
                continue
            else:
                self.warnings.append(f"未対応の数式要素 {etree.QName(tag).localname} は中身だけを出力")
                inner = self.children(ch)
                if inner:
                    out.append(self.row(inner))
        return out

    def arg(self, el, tag):
        c = el.find(m(tag))
        items = self.children(c) if c is not None else []
        return self.row(items) if items else self.node("mrow")

    # ---------------------------------------------------------------- runs
    @staticmethod
    def run_text(r) -> str:
        out = []
        for ch in r:
            t = ch.tag
            if t in (m("t"), w("t")):
                out.append(ch.text or "")
            elif t in (w("tab"),):
                out.append("\t")
            elif t == w("br") and ch.get(w("type")) in BR_TEXT_TYPES:
                out.append("\n")
            elif t == w("cr"):
                out.append("\n")
            elif t == w("sym"):
                out.append(sym_char(ch))
            elif t == w("noBreakHyphen"):
                out.append("\u2011")
            elif t == w("softHyphen"):
                out.append("\u00ad")
        return "".join(out)

    def text_run(self, r):
        """数式中に置かれた通常の文字（w:r）。"""
        text = self.run_text(r)
        return [self.tok("mtext", text)] if text else []

    def h_r(self, r):
        text = self.run_text(r)
        if not text:
            return []
        rpr = r.find(m("rPr"))
        if _onoff(rpr, "nor"):
            return [self.tok("mtext", text)]
        sty = _val(rpr, "sty", None)
        scr = SCR.get(_val(rpr, "scr", ""), None)
        return self.tokenize(text, sty, scr)

    def tokenize(self, text, sty, scr):
        out = []
        i = 0
        n = len(text)
        variant_single = {None: None, "i": None, "p": "normal", "b": "bold", "bi": "bold-italic"}.get(sty)
        if scr:
            variant_single = scr
        while i < n:
            c = text[i]
            if c.isdigit():
                j = i + 1
                while j < n and (text[j].isdigit() or (text[j] in ".．" and j + 1 < n and text[j + 1].isdigit())):
                    j += 1
                out.append(self.tok("mn", text[i:j], mathvariant="bold" if sty in ("b", "bi") else None))
                i = j
            elif c.isalpha() and (c.isascii() or 0x370 <= ord(c) <= 0x3FF or ord(c) >= 0x1D400):
                if sty == "p":
                    j = i + 1
                    while j < n and text[j].isalpha() and (text[j].isascii() or 0x370 <= ord(text[j]) <= 0x3FF):
                        j += 1
                    word = text[i:j]
                    out.append(self.tok("mi", word, mathvariant="normal" if len(word) == 1 else None))
                    i = j
                else:
                    out.append(self.tok("mi", c, mathvariant=variant_single))
                    i += 1
            elif c in OPERATORS:
                out.append(self.tok("mo", c))
                i += 1
            elif c.isspace():
                j = i + 1
                while j < n and text[j].isspace():
                    j += 1
                out.append(self.tok("mtext", text[i:j]))
                i = j
            else:
                j = i + 1
                while j < n and not (text[j].isdigit() or text[j] in OPERATORS or text[j].isspace()
                                     or (text[j].isalpha() and text[j].isascii())):
                    j += 1
                out.append(self.tok("mi" if j - i == 1 and c.isalpha() else "mtext", text[i:j]))
                i = j
        return out

    # ---------------------------------------------------------------- structures
    def h_f(self, el):
        pr = el.find(m("fPr"))
        typ = _val(pr, "type", "bar")
        num = self.arg(el, "num")
        den = self.arg(el, "den")
        if typ == "lin":
            return self.node("mrow", num, self.implicit("/"), den)
        attrs = {}
        if typ == "noBar":
            attrs["linethickness"] = "0"
        elif typ == "skw":
            attrs["bevelled"] = "true"
        return self.node("mfrac", num, den, **attrs)

    def h_sSup(self, el):
        return self.node("msup", self.arg(el, "e"), self.arg(el, "sup"))

    def h_sSub(self, el):
        return self.node("msub", self.arg(el, "e"), self.arg(el, "sub"))

    def h_sSubSup(self, el):
        e = self.arg(el, "e")
        sub = self.arg(el, "sub")
        sup = self.arg(el, "sup")
        return self.node("msubsup", e, sub, sup)

    def h_sPre(self, el):
        sub = self.arg(el, "sub")
        sup = self.arg(el, "sup")
        e = self.arg(el, "e")
        return self.node("mmultiscripts", e, self.node("mprescripts"), sub, sup)

    def h_rad(self, el):
        pr = el.find(m("radPr"))
        hide = _onoff(pr, "degHide")
        deg_el = el.find(m("deg"))
        deg_items = self.children(deg_el) if deg_el is not None else []
        e = self.arg(el, "e")
        if hide or not deg_items:
            return self.node("msqrt", e)
        return self.node("mroot", e, self.row(deg_items))

    def h_d(self, el):
        pr = el.find(m("dPr"))
        beg = _val(pr, "begChr", "(")
        end = _val(pr, "endChr", ")")
        sep = _val(pr, "sepChr", "|")
        items = []
        if beg:
            items.append(self.implicit(beg, fence="true"))
        es = el.findall(m("e"))
        for k, e in enumerate(es):
            if k and sep:
                items.append(self.implicit(sep, separator="true"))
            inner = self.children(e)
            items.append(self.row(inner) if inner else self.node("mrow"))
        if end:
            items.append(self.implicit(end, fence="true"))
        return self.node("mrow", *items)

    def h_nary(self, el):
        pr = el.find(m("naryPr"))
        chr_ = _val(pr, "chr", "∫")
        loc = _val(pr, "limLoc", None) or ("subSup" if chr_ in INTEGRALS else "undOvr")
        op = self.implicit(chr_, largeop="true")
        sub_el, sup_el = el.find(m("sub")), el.find(m("sup"))
        sub_items = self.children(sub_el) if sub_el is not None else []
        sup_items = self.children(sup_el) if sup_el is not None else []
        # 非表示指定でも中身の文字があれば出力する（文字を落とさないため）
        has_sub = bool(sub_items)
        has_sup = bool(sup_items)
        sub = self.row(sub_items) if sub_items else None
        sup = self.row(sup_items) if sup_items else None
        if has_sub and has_sup:
            head = self.node("munderover" if loc == "undOvr" else "msubsup", op, sub, sup)
        elif has_sub:
            head = self.node("munder" if loc == "undOvr" else "msub", op, sub)
        elif has_sup:
            head = self.node("mover" if loc == "undOvr" else "msup", op, sup)
        else:
            head = op
        return self.node("mrow", head, self.arg(el, "e"))

    def h_func(self, el):
        return self.node("mrow", self.arg(el, "fName"), self.arg(el, "e"))

    def h_acc(self, el):
        pr = el.find(m("accPr"))
        ch = _val(pr, "chr", "\u0302")
        return self.node("mover", self.arg(el, "e"), self.implicit(ACCENT_DISPLAY.get(ch, ch)), accent="true")

    def h_bar(self, el):
        pr = el.find(m("barPr"))
        pos = _val(pr, "pos", "bot")
        e = self.arg(el, "e")
        if pos == "top":
            return self.node("mover", e, self.implicit("¯"), accent="true")
        return self.node("munder", e, self.implicit("_"), accentunder="true")

    def h_box(self, el):
        return self.arg(el, "e")

    def h_borderBox(self, el):
        return self.node("menclose", self.arg(el, "e"), notation="box")

    def h_groupChr(self, el):
        pr = el.find(m("groupChrPr"))
        ch = _val(pr, "chr", "⏟")
        pos = _val(pr, "pos", "bot")
        e = self.arg(el, "e")
        if pos == "top":
            return self.node("mover", e, self.implicit(ch))
        return self.node("munder", e, self.implicit(ch))

    def h_limLow(self, el):
        return self.node("munder", self.arg(el, "e"), self.arg(el, "lim"))

    def h_limUpp(self, el):
        return self.node("mover", self.arg(el, "e"), self.arg(el, "lim"))

    def h_eqArr(self, el):
        table = etree.Element(mm("mtable"))
        for e in el.findall(m("e")):
            inner = self.children(e)
            table.append(self.node("mtr", self.node("mtd", self.row(inner) if inner else self.node("mrow"))))
        return table

    def h_m(self, el):
        table = etree.Element(mm("mtable"))
        for mr in el.findall(m("mr")):
            tr = etree.SubElement(table, mm("mtr"))
            for e in mr.findall(m("e")):
                inner = self.children(e)
                tr.append(self.node("mtd", self.row(inner) if inner else self.node("mrow")))
        return table

    def h_phant(self, el):
        pr = el.find(m("phantPr"))
        e = self.arg(el, "e")
        if _onoff(pr, "show"):
            return e
        return self.node("mphantom", e)

    def h_oMath(self, el):
        return self.children(el)

    def h_e(self, el):
        return self.children(el)


def omml_to_mathml(el, display=False):
    conv = OmmlConverter()
    return conv.convert(el, display), conv.warnings


def math_plain(math_el) -> str:
    """MathML から、docx の数式文字（暗黙の記号を除く）を docx 上の順序で取り出す。"""
    toks = [t for t in math_el.iter() if t.get(ORDER) is not None]
    toks.sort(key=lambda t: int(t.get(ORDER)))
    return "".join(t.text or "" for t in toks)


def math_display_text(math_el) -> str:
    """AI やレポート向けの読みやすい平文（暗黙の記号も含む、MathML の順序）。"""
    return "".join((t.text or "") for t in math_el.iter() if isinstance(t.tag, str) and t.text and t.tag.startswith(f"{{{MML_NS}}}"))
