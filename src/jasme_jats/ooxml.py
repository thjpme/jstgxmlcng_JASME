"""docx（Office Open XML）を扱う低水準の共通処理。

ここでは「docx の文字とは何か」の規則（文字ポリシー）を定める。
文字の不変性チェック（fidelity.py）は、この規則で docx から直接文字列を取り出し、
変換結果の XML と突き合わせる。変換本体（docx_reader.py）とは別の実装で取り出すことで、
変換処理の誤りを検出できるようにしている。

文字ポリシー
  含める: w:t, m:t（数式中の文字）, w:tab（タブ文字）, 改行 w:br / w:cr（改行文字）,
          w:noBreakHyphen（U+2011）, w:softHyphen（U+00AD）, w:sym（記号フォントは Unicode に対応付け）
  含めない: 削除された変更履歴（w:del, w:moveFrom）, フィールドコード, 隠し文字（w:vanish）,
          ページ区切り・段区切り, テキストボックス内の段落（別の段落として扱う）, ルビの読み（w:rt）,
          Word が自動生成する文字（脚注番号・自動段落番号。これらは XML では「生成文字」として区別する）
"""
from __future__ import annotations

import re
import zipfile

from lxml import etree

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
PIC_NS = "http://schemas.openxmlformats.org/drawingml/2006/picture"
V_NS = "urn:schemas-microsoft-com:vml"
O_NS = "urn:schemas-microsoft-com:office:office"
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
WPS_NS = "http://schemas.microsoft.com/office/word/2010/wordprocessingShape"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

NS = {"w": W_NS, "m": M_NS, "r": R_NS, "a": A_NS, "wp": WP_NS, "pic": PIC_NS,
      "v": V_NS, "o": O_NS, "mc": MC_NS, "wps": WPS_NS}


def w(tag: str) -> str:
    return f"{{{W_NS}}}{tag}"


def m(tag: str) -> str:
    return f"{{{M_NS}}}{tag}"


def wval(el, default=None):
    """w:val 属性（なければ default）。"""
    if el is None:
        return default
    return el.get(w("val"), default)


def on_off(el) -> bool:
    """w:b や w:i などのオン・オフ要素。要素があり val が false/0/off でなければ真。"""
    if el is None:
        return False
    v = el.get(w("val"))
    return v is None or v.lower() not in ("0", "false", "off", "none")


PARSER = etree.XMLParser(remove_blank_text=False, huge_tree=True, resolve_entities=False, no_network=True)


def parse_xml(data: bytes):
    return etree.fromstring(data, PARSER)


def preprocess(root):
    """mc:AlternateContent を mc:Choice の中身に置き換える（mc:Fallback は捨てる）。

    テキストボックスなどは同じ内容が Choice（DrawingML）と Fallback（VML）の両方に入っているため、
    片方だけを残さないと文字が二重に数えられる。
    """
    for ac in list(root.iter(f"{{{MC_NS}}}AlternateContent")):
        parent = ac.getparent()
        if parent is None:
            continue
        choice = ac.find(f"{{{MC_NS}}}Choice")
        repl = list(choice) if choice is not None else []
        if choice is None:
            fb = ac.find(f"{{{MC_NS}}}Fallback")
            repl = list(fb) if fb is not None else []
        idx = parent.index(ac)
        tail = ac.tail
        parent.remove(ac)
        for i, ch in enumerate(repl):
            parent.insert(idx + i, ch)
        if tail and repl:
            repl[-1].tail = (repl[-1].tail or "") + tail
    return root


class DocxPackage:
    """docx の zip を開き、必要なパートを前処理済みで返す。"""

    def __init__(self, path):
        self.path = path
        self.zip = zipfile.ZipFile(path)
        self.names = set(self.zip.namelist())
        self._cache = {}

    def read(self, name: str):
        return self.zip.read(name) if name in self.names else None

    def xml(self, name: str):
        if name not in self._cache:
            data = self.read(name)
            self._cache[name] = preprocess(parse_xml(data)) if data is not None else None
        return self._cache[name]

    def rels(self, part: str) -> dict:
        """パートのリレーションシップ {rId: (type, target, mode)}。"""
        d, base = part.rsplit("/", 1) if "/" in part else ("", part)
        rels_name = f"{d}/_rels/{base}.rels" if d else f"_rels/{base}.rels"
        data = self.read(rels_name)
        out = {}
        if data is None:
            return out
        root = parse_xml(data)
        for rel in root.iter(f"{{{REL_NS}}}Relationship"):
            target = rel.get("Target", "")
            mode = rel.get("TargetMode", "")
            if mode != "External" and not target.startswith("/"):
                target = (d + "/" + target) if d else target
                # 相対パスの ../ を解決
                parts = []
                for seg in target.split("/"):
                    if seg == "..":
                        if parts:
                            parts.pop()
                    elif seg and seg != ".":
                        parts.append(seg)
                target = "/".join(parts)
            elif target.startswith("/"):
                target = target[1:]
            out[rel.get("Id")] = (rel.get("Type", ""), target, mode)
        return out


def paragraph_ids(root, prefix: str) -> dict:
    """w:p 要素 → 識別子（prefix + 出現順）。読み取り側と検証側で同じ番号を使う。"""
    return {p: f"{prefix}{i}" for i, p in enumerate(root.iter(w("p")), 1)}


# Symbol フォントの私用領域コード（F020–F0FF）→ Unicode（よく使われる記号のみ）
_SYMBOL = {
    0x20: " ", 0x21: "!", 0x22: "∀", 0x23: "#", 0x24: "∃", 0x25: "%", 0x26: "&", 0x27: "∋",
    0x28: "(", 0x29: ")", 0x2A: "∗", 0x2B: "+", 0x2C: ",", 0x2D: "−", 0x2E: ".", 0x2F: "/",
    0x3A: ":", 0x3B: ";", 0x3C: "<", 0x3D: "=", 0x3E: ">", 0x3F: "?", 0x40: "≅",
    0x41: "Α", 0x42: "Β", 0x43: "Χ", 0x44: "Δ", 0x45: "Ε", 0x46: "Φ", 0x47: "Γ", 0x48: "Η",
    0x49: "Ι", 0x4A: "ϑ", 0x4B: "Κ", 0x4C: "Λ", 0x4D: "Μ", 0x4E: "Ν", 0x4F: "Ο", 0x50: "Π",
    0x51: "Θ", 0x52: "Ρ", 0x53: "Σ", 0x54: "Τ", 0x55: "Υ", 0x56: "ς", 0x57: "Ω", 0x58: "Ξ",
    0x59: "Ψ", 0x5A: "Ζ", 0x5B: "[", 0x5C: "∴", 0x5D: "]", 0x5E: "⊥", 0x5F: "_",
    0x61: "α", 0x62: "β", 0x63: "χ", 0x64: "δ", 0x65: "ε", 0x66: "φ", 0x67: "γ", 0x68: "η",
    0x69: "ι", 0x6A: "ϕ", 0x6B: "κ", 0x6C: "λ", 0x6D: "μ", 0x6E: "ν", 0x6F: "ο", 0x70: "π",
    0x71: "θ", 0x72: "ρ", 0x73: "σ", 0x74: "τ", 0x75: "υ", 0x76: "ϖ", 0x77: "ω", 0x78: "ξ",
    0x79: "ψ", 0x7A: "ζ", 0x7B: "{", 0x7C: "|", 0x7D: "}", 0x7E: "∼",
    0xA2: "′", 0xA3: "≤", 0xA5: "∞", 0xA7: "♣", 0xA8: "♦", 0xA9: "♥", 0xAA: "♠", 0xAB: "↔",
    0xAC: "←", 0xAD: "↑", 0xAE: "→", 0xAF: "↓", 0xB0: "°", 0xB1: "±", 0xB2: "″", 0xB3: "≥",
    0xB4: "×", 0xB5: "∝", 0xB6: "∂", 0xB7: "•", 0xB8: "÷", 0xB9: "≠", 0xBA: "≡", 0xBB: "≈",
    0xBC: "…", 0xC0: "ℵ", 0xC4: "⊗", 0xC5: "⊕", 0xC6: "∅", 0xC7: "∩", 0xC8: "∪", 0xC9: "⊃",
    0xCA: "⊇", 0xCB: "⊄", 0xCC: "⊂", 0xCD: "⊆", 0xCE: "∈", 0xCF: "∉", 0xD0: "∠", 0xD1: "∇",
    0xD5: "∏", 0xD6: "√", 0xD7: "⋅", 0xD8: "¬", 0xD9: "∧", 0xDA: "∨", 0xDB: "⇔", 0xDC: "⇐",
    0xDD: "⇑", 0xDE: "⇒", 0xDF: "⇓", 0xE5: "∑", 0xF2: "∫",
}


def sym_char(sym_el) -> str:
    """w:sym を Unicode 文字に変換する。Symbol フォント以外はコードをそのまま文字にする。"""
    code = sym_el.get(w("char"), "0")
    font = (sym_el.get(w("font")) or "").lower()
    try:
        n = int(code, 16)
    except ValueError:
        return "�"
    if font == "symbol":
        low = n - 0xF000 if n >= 0xF000 else n
        if low in _SYMBOL:
            return _SYMBOL[low]
    return chr(n)


def run_hidden(r) -> bool:
    rpr = r.find(w("rPr"))
    if rpr is None:
        return False
    return on_off(rpr.find(w("vanish"))) or on_off(rpr.find(w("specVanish")))


BR_TEXT_TYPES = (None, "textWrapping")


def canonical_text(p) -> str:
    """段落（w:p）の文字列を文字ポリシーに従って取り出す（検証用の独立実装）。

    数式（m:t）も含む。テキストボックス内の段落は含めない（別段落として数える）。
    """
    out = []
    field_stack = []   # True = コード部（結果ではない）

    def in_code():
        return any(field_stack)

    def walk(el, hidden=False, deleted=False):
        for ch in el:
            tag = ch.tag
            if not isinstance(tag, str):
                continue
            if tag == w("p") or tag == w("txbxContent") or tag == w("rt"):
                continue
            if tag in (w("del"), w("moveFrom")):
                walk(ch, hidden, True)
                continue
            if tag == w("r"):
                walk(ch, hidden or run_hidden(ch), deleted)
                continue
            if tag == w("fldChar"):
                t = ch.get(w("fldCharType"))
                if t == "begin":
                    field_stack.append(True)
                elif t == "separate" and field_stack:
                    field_stack[-1] = False
                elif t == "end" and field_stack:
                    field_stack.pop()
                continue
            if tag in (w("rPr"), w("pPr"), m("rPr"), w("instrText"), w("delText"),
                       w("footnoteReference"), w("endnoteReference"), m("ctrlPr")):
                continue
            if deleted or hidden or in_code():
                if tag == m("r"):
                    walk(ch, hidden, deleted)
                elif len(ch):
                    walk(ch, hidden, deleted)
                continue
            if tag == w("t") or tag == m("t"):
                out.append(ch.text or "")
            elif tag in (w("tab"), w("ptab")):
                out.append("\t")
            elif tag == w("br"):
                if ch.get(w("type")) in BR_TEXT_TYPES:
                    out.append("\n")
            elif tag == w("cr"):
                out.append("\n")
            elif tag == w("noBreakHyphen"):
                out.append("\u2011")
            elif tag == w("softHyphen"):
                out.append("\u00ad")
            elif tag == w("sym"):
                out.append(sym_char(ch))
            elif len(ch):
                walk(ch, hidden, deleted)

    walk(p)
    return "".join(out)


def text_of_element(el) -> str:
    """要素以下の w:t / m:t を連結（テキストボックスの判定などの簡易用途）。"""
    return "".join(t.text or "" for t in el.iter(w("t"), m("t")))


WS_RE = re.compile(r"^[\s\u3000\u00a0]*$")


def is_ws(s: str) -> bool:
    return bool(WS_RE.match(s))
