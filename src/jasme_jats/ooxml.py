"""docx（Office Open XML）を扱う低水準の共通処理。

ここでは「docx の文字とは何か」の規則（文字ポリシー）を定める。
文字の不変性チェック（fidelity.py）は、この規則で docx から直接文字列を取り出し、
変換結果の XML と突き合わせる。変換本体（docx_reader.py）とは別の実装で取り出すことで、
変換処理の誤りを検出できるようにしている。

文字ポリシー
  「docx の文字」は、Word で表示される文字（変更履歴をすべて承諾し、隠し文字を隠した状態）とする。読み取り（docx_reader）・
  検証（canonical_text・canonical_texts。fidelity.source_texts）・ルート2（pdfdocx.paragraph_units・write_fixed_docx）の 3 か所は、
  ここに置く規則（段落のつながり joined_paragraphs と、隠し文字の判定 HiddenRule）を共有し、文字の取り出しはそれぞれ別の実装で行う。
  含める: w:t, m:t（数式中の文字）, w:tab / w:ptab（タブ文字）, 改行 w:br / w:cr（改行文字）,
          w:noBreakHyphen（U+2011）, w:softHyphen（U+00AD）, w:sym（記号フォントは Unicode に対応付け）
  含めない: 削除された変更履歴（w:del, w:moveFrom）, フィールドコード, 隠し文字（HiddenRule。ランの直接の w:vanish・w:specVanish、
          文字スタイル・段落スタイル〈w:basedOn をたどる〉と既定の書式〈w:docDefaults〉の w:vanish）,
          ページ区切り・段区切り, テキストボックス内の段落（別の段落として扱う。削除の変更履歴の中の図形の段落は欠番）, ルビの読み（w:rt）,
          Word が自動生成する文字（脚注番号・自動段落番号。これらは XML では「生成文字」として区別する）
  段落の区切り: 段落記号が削除された段落（w:pPr/w:rPr の w:del・w:moveFrom）は、Word で承諾した状態と同じく、同じ親の中の次の
          段落とつないで 1 段落にする（joined_paragraphs。段落の ID は連鎖の最初の段落のもので、後ろの段落の ID は欠番）。
          次が段落でない（表・コンテンツコントロール・カスタム XML など）か、親の最後の段落（本文・表のセル・テキストボックス・
          注の最後など）なら、つながない（unjoined_deleted_marks。読み取りがレポートの 10 章で知らせる）。段落記号の w:vanish
          （スタイル区切り）は削除ではないので、つながない。
  隠し文字で扱わないもの: 数式の中のラン（m:r）の w:vanish（数式は全体を出す）、表スタイル（w:tblStylePr など）・番号の書式
          （w:lvl/w:rPr）の w:vanish、段落記号の w:vanish、リンクスタイル（w:link）の特別な扱い、テーマ・互換性の設定。
          つないだ段落の後ろの段落の隠し文字は、その段落自身の段落スタイルで決める。隠し文字のランの中のテキストボックス
          （行内・浮動配置）の段落は、ランの隠し文字を継がない（別の段落として、その段落自身の規則で決める。読み取りも同じ。
          隠し文字のランの中の画像は、読み取りが隠す）。
  変更履歴で削除された表の行（w:trPr/w:del）のうち、どの段落にも Word で表示される文字（画像・数式・注の参照も）がなく、図形も
  ない行は、読み取りが行ごと読み飛ばす（docx_reader.Reader.read_table。隠し文字だけが残る行も）。行の段落の文字は空なので、
  検証は何もしなくても同じ結果になる。
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


class HiddenRule:
    """隠し文字（w:vanish）の判定。読み取り・検証・ルート2 の 3 か所が同じ規則を使う（どれも word/styles.xml から作る）。

    修正計画（docs/FIX_PLAN.md の G）の規則。スタイルと既定の書式の w:vanish は、ECMA-376 の切り替えの性質（toggle property。
    スタイルで真なら、それまでの状態を反転させ、偽なら変えない）として扱い、ランの直接の指定はその値そのものにする。
    style_value(sid): スタイル sid から w:basedOn をたどり、w:rPr/w:vanish を最初に指定しているスタイル（いちばん派生した側）の
      値（どれも指定していなければ None。循環は打ち切る）。派生の連鎖の中では反転させない。
    para_state(p): 段落 p の状態。既定の書式（w:docDefaults/w:rPrDefault）の値を、段落スタイル（w:pPr/w:pStyle。なければ既定の
      段落スタイル）の値が真なら反転したもの（XOR）。styles.xml にないスタイルの ID は、値の指定がないものとして扱う。
    run_hidden(r, ps): ラン r が隠れているか（ps は段落の状態）。上から順に、最初に当たったもの:
      1. ランの直接の w:vanish があれば、その値（w:val="0" なら表示）
      2. 直接の w:specVanish があれば隠す（ECMA-376 では、常に隠れているようにふるまう）
      3. w:rStyle の文字スタイルの値が真なら、段落の状態を反転（偽か指定がなければ段落の状態のまま。XOR）
      4. どれもなければ段落の状態
    run_hidden_by(r, ps): 同じ規則で、隠れるときに何で決まったか（1・2 のランの直接の指定なら "direct"、3・4 のスタイル・既定の
      書式なら "style"。隠れなければ ""）。スタイル・既定の書式で隠した文字は、規則が暫定なので、読み取りが記録して要確認で
      知らせる（Document.style_hidden。report._style_hidden_action）。
    styles_root が None なら（NO_RULE）、ランの直接の指定だけを見る。
    LibreOffice（24.2）で承諾・表示した結果とは、次の形で違う（暫定。Word では未確認。docs/DESIGN.md の 4.1・7 章）: 偽を指定した派生の
    文字スタイルを、隠す段落スタイルの段落で使ったラン（LibreOffice は表示）、既定の書式に w:vanish があり、段落スタイルにも
    w:vanish の指定があるとき（LibreOffice は段落スタイルの値をそのまま使う）、w:specVanish だけのラン（LibreOffice は表示）。
    """

    def __init__(self, styles_root=None):
        self.styles = {}            # スタイルの ID -> w:style
        self.default_p = ""         # 既定の段落スタイルの ID
        self.dd = False             # 既定の書式の w:vanish
        self._cache = {}
        if styles_root is None:
            return
        for st in styles_root.findall(w("style")):
            sid = st.get(w("styleId"))
            if sid is None:
                continue
            self.styles[sid] = st
            if not self.default_p and st.get(w("type")) == "paragraph" and st.get(w("default")) in ("1", "true"):
                self.default_p = sid
        dd = styles_root.find(f"{w('docDefaults')}/{w('rPrDefault')}/{w('rPr')}/{w('vanish')}")
        self.dd = on_off(dd)

    def style_value(self, sid):
        if sid in self._cache:
            return self._cache[sid]
        seen, cur, val = set(), sid, None
        while cur and cur in self.styles and cur not in seen:
            seen.add(cur)
            st = self.styles[cur]
            v = st.find(f"{w('rPr')}/{w('vanish')}")
            if v is not None:
                val = on_off(v)
                break
            cur = wval(st.find(w("basedOn")))
        self._cache[sid] = val
        return val

    def para_state(self, p) -> bool:
        ppr = p.find(w("pPr"))
        sid = wval(ppr.find(w("pStyle"))) if ppr is not None else None
        return self.dd ^ (self.style_value(sid or self.default_p) is True)

    def run_hidden(self, r, ps: bool) -> bool:
        return self.run_hidden_by(r, ps) != ""

    def run_hidden_by(self, r, ps: bool) -> str:
        rpr = r.find(w("rPr"))
        direct = rpr.find(w("vanish")) if rpr is not None else None
        if direct is not None:
            return "direct" if on_off(direct) else ""
        if rpr is not None and on_off(rpr.find(w("specVanish"))):
            return "direct"
        rs = wval(rpr.find(w("rStyle"))) if rpr is not None else None
        hidden = (not ps) if rs and self.style_value(rs) is True else ps
        return "style" if hidden else ""


NO_RULE = HiddenRule(None)      # styles.xml がないとき（ランの直接の指定だけを見る）

# 段落記号が削除された段落を次の段落とつなぐとき、間にあっても飛ばす要素（中身のない目印）
JOIN_SKIP = {w(t) for t in ("bookmarkStart", "bookmarkEnd", "proofErr", "permStart", "permEnd", "commentRangeStart",
                            "commentRangeEnd", "moveFromRangeStart", "moveFromRangeEnd", "moveToRangeStart",
                            "moveToRangeEnd", "customXmlInsRangeStart", "customXmlInsRangeEnd", "customXmlDelRangeStart",
                            "customXmlDelRangeEnd", "customXmlMoveFromRangeStart", "customXmlMoveFromRangeEnd",
                            "customXmlMoveToRangeStart", "customXmlMoveToRangeEnd")}
# つなげない理由（unjoined_deleted_marks）: 親の最後の段落のとき（親の要素ごと）と、次の要素が段落でないとき（次の要素ごと）
END_REASONS = {w("body"): "本文の最後の段落", w("tc"): "表のセルの最後の段落", w("txbxContent"): "テキストボックスの最後の段落",
               w("footnote"): "注の最後の段落", w("endnote"): "注の最後の段落",
               w("sdtContent"): "コンテンツコントロールの最後の段落", w("customXml"): "カスタム XML の最後の段落"}
NEXT_REASONS = {w("tbl"): "次が表", w("sdt"): "次がコンテンツコントロール", w("customXml"): "次がカスタム XML"}


def paragraph_mark_deleted(p) -> bool:
    """段落記号が変更履歴で削除（w:pPr/w:rPr の w:del か w:moveFrom）されているか。段落記号の w:vanish（スタイル区切り）・
    w:ins は見ない（つながない）。"""
    rpr = p.find(f"{w('pPr')}/{w('rPr')}")
    return rpr is not None and (rpr.find(w("del")) is not None or rpr.find(w("moveFrom")) is not None)


def _join_target(p) -> tuple:
    """段落記号が削除された段落 p をつなぐ先: (次の w:p, "") か、つなげなければ (None, 理由)。

    同じ親の中だけを見る（親を越えて、コンテンツコントロールの中から外へ、セルの最後から次のセルへ、などはつながない）。
    間の中身のない目印（JOIN_SKIP）・コメント・処理命令は飛ばす。
    """
    nxt = p.getnext()
    while nxt is not None and (not isinstance(nxt.tag, str) or nxt.tag in JOIN_SKIP):
        nxt = nxt.getnext()
    if nxt is not None and nxt.tag == w("p"):
        return nxt, ""
    if nxt is None or nxt.tag == w("sectPr"):
        parent = p.getparent()
        return None, END_REASONS.get(parent.tag if parent is not None else "", "段落の並びの最後の段落")
    return None, NEXT_REASONS.get(nxt.tag, "次が段落でない")


def joined_paragraphs(root) -> dict:
    """段落記号が削除された段落の連鎖 {連鎖の最初の w:p: [w:p, w:p, ...]}（2 段落以上のものだけ。文書の順）。

    読み取り・検証・ルート2 が同じ規則でつなぐ。前処理した木（mc:AlternateContent を mc:Choice に置き換えたもの。
    DocxPackage.xml）に対して呼ぶ（前処理しない木では mc:Fallback の中の写しもつないでしまう）。
    """
    link = {}
    for p in root.iter(w("p")):
        if paragraph_mark_deleted(p):
            nxt, _ = _join_target(p)
            if nxt is not None:
                link[p] = nxt
    later = set(link.values())
    chains = {}
    for p in link:
        if p in later:
            continue
        chain = [p]
        while chain[-1] in link:
            chain.append(link[chain[-1]])
        chains[p] = chain
    return chains


def unjoined_deleted_marks(root) -> list:
    """段落記号が削除されているのに、つなぐ先のない段落 [(w:p, 理由)]（文書の順）。"""
    out = []
    for p in root.iter(w("p")):
        if paragraph_mark_deleted(p):
            nxt, why = _join_target(p)
            if nxt is None:
                out.append((p, why))
    return out


def in_deleted_run(p) -> bool:
    """段落 p が、変更履歴で削除された要素（w:del・w:moveFrom）の中にあるか。

    段落が削除の中に入るのは、削除されたランの図形（テキストボックス）の中の段落だけ。Word で承諾すると図形ごと消えるので、
    読み取りは図形を読まない（その段落の ID は欠番になる）。検証・ルート2 も同じ規則で、その段落を数えない。
    """
    return any(a.tag in (w("del"), w("moveFrom")) for a in p.iterancestors())


def canonical_texts(root, prefix: str, hidden=None) -> dict:
    """部品（root）のすべての段落の文字 {段落 ID: 文字}（検証用。fidelity.source_texts）。

    段落 ID は paragraph_ids と同じ番号。段落記号の削除でつないだ連鎖（joined_paragraphs）は、最初の段落の ID に、連鎖の段落
    ごとの canonical_text を順に連結した文字を入れ、後ろの段落の ID は入れない（欠番）。削除の変更履歴の中の図形の段落
    （in_deleted_run）も入れない（欠番）。hidden は隠し文字の判定（HiddenRule）。
    """
    chains = joined_paragraphs(root)
    later = {q for c in chains.values() for q in c[1:]}
    out = {}
    for p, pid in paragraph_ids(root, prefix).items():
        if p not in later and not in_deleted_run(p):
            out[pid] = "".join(canonical_text(q, hidden) for q in chains.get(p, [p]))
    return out


BR_TEXT_TYPES = (None, "textWrapping")


def canonical_text(p, hidden=None) -> str:
    """段落（w:p）の文字列を文字ポリシーに従って取り出す（検証用の独立実装）。

    数式（m:t）も含む。テキストボックス内の段落は含めない（別段落として数える）。hidden は隠し文字の判定（HiddenRule。
    None なら NO_RULE）。段落記号の削除によるつながりは見ない（canonical_texts がつなぐ）。
    """
    out = []
    field_stack = []   # True = コード部（結果ではない）
    rule = hidden or NO_RULE
    ps = rule.para_state(p)

    def in_code():
        return any(field_stack)

    def walk(el, hid=False, deleted=False):
        for ch in el:
            tag = ch.tag
            if not isinstance(tag, str):
                continue
            if tag == w("p") or tag == w("txbxContent") or tag == w("rt"):
                continue
            if tag in (w("del"), w("moveFrom")):
                walk(ch, hid, True)
                continue
            if tag == w("r"):
                walk(ch, hid or rule.run_hidden(ch, ps), deleted)
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
            if deleted or hid or in_code():
                if tag == m("r"):
                    walk(ch, hid, deleted)
                elif len(ch):
                    walk(ch, hid, deleted)
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
                walk(ch, hid, deleted)

    walk(p)
    return "".join(out)


def text_of_element(el) -> str:
    """要素以下の w:t / m:t を連結（テキストボックスの判定などの簡易用途）。"""
    return "".join(t.text or "" for t in el.iter(w("t"), m("t")))


WS_RE = re.compile(r"^[\s\u3000\u00a0]*$")


def is_ws(s: str) -> bool:
    return bool(WS_RE.match(s))
