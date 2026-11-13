"""docx を読み取り、中間表現（model.Document）を作る。

文字の扱いは ooxml.py の文字ポリシーに従う。ここで作る「アトム」の文字列を連結したものが、
ooxml.canonical_texts() で独立に取り出した文字列と一致することを、最後に fidelity.py で確かめる。
段落記号の削除でつながる段落（ooxml.joined_paragraphs）と隠し文字の判定（ooxml.HiddenRule）は、検証・ルート2 と同じ規則を使う:
つながる段落は連鎖の最初の段落の ID の 1 つの段落として読み（後ろの段落の ID は欠番）、つなげない段落記号の削除は
レポートの 10 章の警告で知らせる。変更履歴で削除された表の行のうち、Word で表示される文字・画像などが残らない行は読み飛ばして
記録する。スタイル・既定の書式の設定で隠した文字・画像は、隠し文字の判定が暫定なので別にも記録する（要確認で知らせる）。
"""
from __future__ import annotations

import copy
import hashlib
import re
from dataclasses import dataclass, field

from lxml import etree

from .model import (Atom, Cell, DeletedRow, Document, Float, ImageRef, JoinInfo, Layout, Para, ResultlessField, Row, SymbolReplaced,
                    Table, TextBox, note_key)
from .numbering import Numbering
from .ooxml import (A_NS, BR_TEXT_TYPES, FONT_DISPLAY, LEGACY_BULLETS, O_NS, PIC_NS, R_NS, SYMBOL_ADDED, V_NS, WP_NS, WPS_NS, DocxPackage, HiddenRule,
                    canonical_text, is_pua, joined_paragraphs, m, on_off, paragraph_ids, resultless_field_kind, run_font, sym_char, sym_code,
                    symbol_char,
                    unjoined_deleted_marks, w, w_t_text, wval)

WPG_NS = "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup"
WPC_NS = "http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas"
# テキストボックスを入れる VML の図形（style に大きさ・位置がある）
VML_BOX_SHAPES = {f"{{{V_NS}}}shape", f"{{{V_NS}}}rect", f"{{{V_NS}}}roundrect"}

# レポートの 10 章の警告（読み取りで見つけた、変更履歴の承諾の状態をまねきれないもの。Action にはしない）
UNJOINED_MSG = ("{src}: 段落「{head}」は、変更履歴で段落の区切り（段落記号）が削除されていますが、{why}なので、次の段落と"
                "つながずに出力しました。Word で変更をすべて承諾して保存してから変換し直すと、Word の表示と同じ段落になります。")
DELETED_ROW_KEPT_MSG = ("{where}の {row} 行目: 変更履歴で削除された行ですが、削除されていない文字・画像などがあるので、行のまま出力しました"
                        "（Word で変更をすべて承諾すると、この行は消えます）。Word で確かめ、変更をすべて承諾して保存してから"
                        "変換し直してください。")
CELL_DELETED_MSG = ("{where}の {row} 行目に、変更履歴で削除されたセルがあります。セルはそのまま出力しました（削除された文字は"
                    "出力していません）。Word で変更をすべて承諾すると、セルが消えて表の形が変わることがあるので、Word で"
                    "承諾して保存してから変換し直してください。")


def table_where(head: str, caption: str = "") -> str:
    """読み取りの表を利用者が Word で探す手がかり（キャプション「表1　…」の表 / 「区分」で始まる表 / 文字のない表）。head は
    table_head（DeletedRow.head と同じ形）、caption は表のキャプションの文字（あれば、キャプションの冒頭 20 字で示す）。"""
    cap = caption.strip()
    if cap:
        return f"キャプション「{cap[:20]}{'…' if len(cap) > 20 else ''}」の表"
    return f"「{head}」で始まる表" if head else "文字のない表"


@dataclass
class StyleInfo:
    sid: str
    stype: str
    name: str
    based_on: str = ""
    fmt: dict = field(default_factory=dict)   # bold/italic/... -> bool
    num: tuple = None                          # (numId, ilvl)
    default: bool = False


def _rpr_fmt(rpr) -> dict:
    """w:rPr から書式の指定（明示されたものだけ）を取り出す。"""
    out = {}
    if rpr is None:
        return out
    for tag, key in (("b", "bold"), ("i", "italic"), ("strike", "strike"), ("dstrike", "strike"),
                     ("smallCaps", "sc")):
        el = rpr.find(w(tag))
        if el is not None:
            out[key] = on_off(el)
    u = rpr.find(w("u"))
    if u is not None:
        out["underline"] = (wval(u, "single") or "single") != "none"
    va = rpr.find(w("vertAlign"))
    if va is not None:
        v = wval(va, "baseline")
        out["sup"] = v == "superscript"
        out["sub"] = v == "subscript"
    return out


def read_styles(pkg: DocxPackage) -> dict:
    root = pkg.xml("word/styles.xml")
    styles = {}
    if root is None:
        return styles
    for s in root.findall(w("style")):
        sid = s.get(w("styleId"))
        name_el = s.find(w("name"))
        info = StyleInfo(
            sid=sid,
            stype=s.get(w("type"), ""),
            name=wval(name_el, sid) if name_el is not None else sid,
            based_on=wval(s.find(w("basedOn")), "") or "",
            fmt=_rpr_fmt(s.find(w("rPr"))),
            default=s.get(w("default")) in ("1", "true"),
        )
        ppr = s.find(w("pPr"))
        if ppr is not None:
            np = ppr.find(w("numPr"))
            if np is not None:
                info.num = (wval(np.find(w("numId"))), int(wval(np.find(w("ilvl")), "0") or 0))
        styles[sid] = info
    return styles


def _grid_span(gs) -> int:
    """w:gridSpan の値（横に結合した列の数）。0・負・数でない値は 1（Word などは 1 として表示する）。"""
    try:
        return max(1, int(wval(gs, "1") or 1))
    except ValueError:
        return 1


def _grid_skip(trpr, name) -> int:
    """w:trPr の w:gridBefore / w:gridAfter（行の前後で飛ばしたグリッドの列の数）。なければ 0。負・数でない値も 0。"""
    el = trpr.find(w(name)) if trpr is not None else None
    if el is None:
        return 0
    try:
        return max(0, int(wval(el, "0") or 0))
    except ValueError:
        return 0


class Reader:
    def __init__(self, path):
        self.pkg = DocxPackage(path)
        self.styles = read_styles(self.pkg)
        self.numbering = Numbering(self.pkg.xml("word/numbering.xml"), self.pkg.xml("word/styles.xml"))
        self.default_pstyle = next((s.sid for s in self.styles.values() if s.stype == "paragraph" and s.default), "")
        self.media = {}
        self.images = []
        self.warnings = []
        self.hidden = []
        # 隠し文字のうち、スタイル・既定の書式の設定で隠したもの（ooxml.HiddenRule.run_hidden_by が "style"。規則が暫定なので
        # 要確認で知らせる。report._style_hidden_action）。self.hidden の一部
        self.style_hidden = []
        # 記号フォントの私用領域の符号を、普通の Unicode の文字に置き換えたもの（model.SymbolReplaced。箇条書きの記号・w:sym・
        # 記号フォントのランの w:t。要確認で知らせる。report._symbol_action）
        self.symbols = []
        # 結果を持たないまま終わるフィールドのうち、Word では表示のあるもの（model.ResultlessField。EQ の囲い文字など。表示は docx の
        # 文字ではないので XML には出さず、要確認で知らせる。report._resultless_field_action）
        self.resultless = []
        # 削除の変更履歴の中の脚注・文末脚注の参照の注の鍵（参照として数えない。structure.Classifier.attach_word_notes が除外の理由に使う）
        self.deleted_note_refs = set()
        self._img_count = 0
        self._draw_count = 0    # w:drawing・w:pict・w:object の通し番号（ImageRef.draw_id）
        self.floats = []
        self._float = None      # 読み取り中の浮動配置の図形（Float）
        self.textboxes = []
        self._textbox = None    # 読み取り中のテキストボックス（TextBox）。入れ子の内側を読む間も外側のまま
        # 隠し文字の判定（検証・ルート2 と同じ規則）と、読み取り中の w:p の段落の状態（HiddenRule.para_state）
        self.hidden_rule = HiddenRule(self.pkg.xml("word/styles.xml"))
        self._pstate = False
        # 段落記号の削除でつなぐ段落（部品ごと。_set_joins）: 連鎖の最初の w:p -> 連鎖、連鎖の後ろの w:p の集合
        self.chains, self.later = {}, set()
        self.joined = []        # (最初の段落の ID, [段落の ID, …])（すべての連鎖）
        self.joins = []         # JoinInfo（スタイルの違う段落をつないだ連鎖。structure が判断の一覧に記録する）
        self.deleted_rows = []  # DeletedRow（変更履歴で削除された、文字のない表の行。読み飛ばしたもの）

    # ------------------------------------------------------------ styles
    def style_chain(self, sid):
        seen = []
        while sid and sid in self.styles and sid not in seen:
            seen.append(sid)
            sid = self.styles[sid].based_on
        return seen

    def char_style_fmt(self, sid) -> dict:
        out = {}
        for s in reversed(self.style_chain(sid)):
            out.update(self.styles[s].fmt)
        return out

    def style_num(self, sid):
        for s in self.style_chain(sid):
            if self.styles[s].num:
                return self.styles[s].num
        return None

    # ------------------------------------------------------------ document
    def read(self) -> Document:
        root = self.pkg.xml("word/document.xml")
        self.part = "word/document.xml"
        self.rels = self.pkg.rels(self.part)
        self.pids = paragraph_ids(root, "d")
        self._set_joins(root)
        body = root.find(w("body"))
        blocks = []
        self._tcount = 0
        for el in body:
            blocks.extend(self.read_block(el))
        footnotes = self.read_notes("word/footnotes.xml", "footnote", "f")
        endnotes = self.read_notes("word/endnotes.xml", "endnote", "e")
        tracked = sum(1 for _ in root.iter(w("ins"), w("del"), w("moveFrom"), w("moveTo")))
        comments = sum(1 for _ in root.iter(w("commentRangeStart")))
        doc = Document(blocks=blocks, footnotes=footnotes, endnotes=endnotes, media=self.media,
                       styles=self.styles, warnings=self.warnings, hidden_text=self.hidden, style_hidden=self.style_hidden,
                       symbols=self.symbols, resultless_fields=self.resultless,
                       tracked_changes=tracked, comments=comments,
                       images=self.images, floats=self.floats, textboxes=self.textboxes, layout=read_layout(root, self.pkg),
                       deleted_note_refs=self.deleted_note_refs, joined=self.joined, joins=self.joins,
                       deleted_rows=self.deleted_rows)
        return doc

    def read_notes(self, part, tag, prefix) -> dict:
        root = self.pkg.xml(part)
        out = {}
        if root is None:
            return out
        saved = (self.part, self.rels, self.pids, self.chains, self.later)
        self.part, self.rels, self.pids = part, self.pkg.rels(part), paragraph_ids(root, prefix)
        self._set_joins(root)
        for note in root.findall(w(tag)):
            if note.get(w("type")) in ("separator", "continuationSeparator", "continuationNotice"):
                continue
            nid = note.get(w("id"))
            paras = []
            for el in note:
                for b in self.read_block(el):
                    if isinstance(b, Para):
                        paras.append(b)
                    else:
                        paras.extend(b.paragraphs())
            out[nid] = paras
        self.part, self.rels, self.pids, self.chains, self.later = saved
        return out

    def _set_joins(self, root):
        """部品 root の段落記号の削除でつなぐ段落（ooxml.joined_paragraphs）を決め、つなげないもの（unjoined_deleted_marks）を
        10 章の警告にする。つなげない段落が連鎖の最後の段落なら、警告の ID は連鎖の最初の段落のもの（読み取った段落の ID）。
        警告は、その段落（連鎖なら連鎖全体）の docx の文字が空でないときだけ（空の段落は、つながなくても見える違いがない。
        変更履歴で削除された表の行のセルの最後の段落などで、警告が並ぶのを避ける）。"""
        self.chains = joined_paragraphs(root)
        self.later = {q for c in self.chains.values() for q in c[1:]}
        chain_of = {q: c for c in self.chains.values() for q in c}
        for p, why in unjoined_deleted_marks(root):
            chain = chain_of.get(p, [p])
            text = "".join(canonical_text(q, self.hidden_rule) for q in chain)
            if text:
                # 理由が英字で終わるとき（「次がカスタム XML」）は「なので」の前に空白を入れる
                why = why + (" " if why[-1:].isascii() else "")
                self.warnings.append(UNJOINED_MSG.format(src=self.pids.get(chain[0], "?"), head=text.strip()[:20], why=why))

    def read_block(self, el):
        tag = el.tag
        if tag == w("p"):
            if el in self.later:        # 段落記号の削除で前の段落につながる（前の段落といっしょに読んだ）
                return []
            para, extra = self.read_paragraph(el)
            return [para] + extra
        if tag == w("tbl"):
            return [self.read_table(el)]
        if tag in (w("sdt"),):
            content = el.find(w("sdtContent"))
            out = []
            if content is not None:
                for ch in content:
                    out.extend(self.read_block(ch))
            return out
        if tag in (w("customXml"), w("ins"), w("moveTo")):
            out = []
            for ch in el:
                out.extend(self.read_block(ch))
            return out
        return []

    def read_table(self, tbl) -> Table:
        self._tcount += 1
        tpr = tbl.find(w("tblPr"))
        sid = wval(tpr.find(w("tblStyle"))) if tpr is not None else ""
        t = Table(tid=f"t{self._tcount}", style_id=sid or "",
                  style_name=self.styles[sid].name if sid in self.styles else (sid or ""),
                  float_id=self._float.fid if self._float else "", textbox_id=self._textbox.xid if self._textbox else "")
        # 変更履歴で削除された行（w:trPr/w:del）のうち読み飛ばしたもの、文字が残るので出力したもの、変更履歴で削除されたセル
        # （w:tcPr/w:cellDel）のある行（どれも docx の表の何行目か。1 から、読み飛ばした行も数える）
        skipped, kept, cell_del = [], [], []
        # 行と、行の中のセルは、コンテンツコントロール（w:sdt）や w:customXml に包まれていることがある
        for k, tr in enumerate(_children(tbl, (w("tr"),)), 1):
            trpr = tr.find(w("trPr"))
            row = Row(header=trpr is not None and on_off(trpr.find(w("tblHeader"))))
            row.grid_before = _grid_skip(trpr, "gridBefore")
            row.grid_after = _grid_skip(trpr, "gridAfter")
            row.number = k
            row_deleted = trpr is not None and trpr.find(w("del")) is not None
            shapes = (len(self.images), len(self.floats), len(self.textboxes))
            records = (len(self.joined), len(self.joins), len(self.deleted_rows), len(self.hidden), len(self.warnings),
                       len(self.style_hidden), len(self.symbols), len(self.resultless))
            # 削除された行を読み飛ばすときに戻す、自動番号の数え方の写し（Numbering.snapshot）
            numbering_state = self.numbering.snapshot() if row_deleted else None
            has_cell_del = False
            for c in _children(tr, (w("tc"),)):
                tcpr = c.find(w("tcPr"))
                cell = Cell()
                if tcpr is not None:
                    gs = tcpr.find(w("gridSpan"))
                    if gs is not None:
                        cell.gridspan = _grid_span(gs)
                    vm = tcpr.find(w("vMerge"))
                    if vm is not None:
                        cell.vmerge = "restart" if wval(vm) == "restart" else "continue"
                    has_cell_del = has_cell_del or tcpr.find(w("cellDel")) is not None
                for ch in c:
                    cell.blocks.extend(self.read_block(ch))
                row.cells.append(cell)
            if row_deleted:
                # Word で変更を承諾すると行ごと消える。文字・画像・数式・注の参照（アトム）がひとつもなく、図形（画像・浮動配置の
                # 図形・テキストボックス）も読まなかった行だけを読み飛ばす（行の段落の docx の文字はすべて空なので、検証は
                # 何もしなくても同じ結果になる。図形を読み飛ばすと、図形のアンカーが出力しない段落を指してしまう）
                if _row_empty(row) and shapes == (len(self.images), len(self.floats), len(self.textboxes)):
                    skipped.append(k)
                    # 読み飛ばした行の中でつないだ段落・読み飛ばした入れ子の表の行・隠し文字・警告は、出力した段落の記録から外し
                    # （行ごと記録する）、行の中で数えた自動番号は戻す（Word で承諾すると行ごと消え、後ろの番号が詰まる）
                    del (self.joined[records[0]:], self.joins[records[1]:], self.deleted_rows[records[2]:],
                         self.hidden[records[3]:], self.warnings[records[4]:], self.style_hidden[records[5]:], self.symbols[records[6]:],
                         self.resultless[records[7]:])
                    self.numbering.restore(numbering_state)
                    continue
                kept.append(k)
            if has_cell_del:
                cell_del.append(k)
            t.rows.append(row)
        head = table_head(t)
        t.skipped_rows = len(skipped)
        self.deleted_rows += [DeletedRow(tid=t.tid, row=k, head=head) for k in skipped]
        self.warnings += [DELETED_ROW_KEPT_MSG.format(where=table_where(head), row=k) for k in kept]
        self.warnings += [CELL_DELETED_MSG.format(where=table_where(head), row=k) for k in cell_del]
        return t

    # ------------------------------------------------------------ paragraph
    def read_paragraph(self, p, in_textbox=False):
        """段落 p を読む。p が段落記号の削除でつながる連鎖の最初の段落なら、連鎖の段落を順に読んで 1 つの段落にする。

        つないだ段落の ID は最初の段落のもの。書式（スタイル・番号・揃え）は、連鎖の中で docx の文字（canonical_text）が空でない
        最初の段落のもの（すべて空なら最後の段落のもの。「前の段落が空なら後ろの段落のもの、そうでなければ前の段落のもの」を
        先頭からたたみ込んだものと同じ）。セクションの区切りは最後の段落のもの。自動番号は連鎖ごとに 1 回だけ数える。
        """
        src = self.pids.get(p, "?")
        chain = self.chains.get(p, [p])
        first_resultless = len(self.resultless)
        fp = p if len(chain) == 1 else next((q for q in chain if canonical_text(q, self.hidden_rule) != ""), chain[-1])
        ppr = fp.find(w("pPr"))
        sid = ""
        numpr = None
        align = ""
        if ppr is not None:
            sid = wval(ppr.find(w("pStyle")), "") or ""
            np = ppr.find(w("numPr"))
            if np is not None:
                numpr = (wval(np.find(w("numId"))), int(wval(np.find(w("ilvl")), "0") or 0))
            align = wval(ppr.find(w("jc")), "") or ""
        last = chain[-1].find(w("pPr"))
        sect = last is not None and last.find(w("sectPr")) is not None
        sid = sid or self.default_pstyle
        if numpr is None:
            numpr = self.style_num(sid)
        elif numpr[0] is None:
            sn = self.style_num(sid)
            numpr = (sn[0], numpr[1]) if sn else None
        para = Para(src=src, style_id=sid, style_name=self.styles[sid].name if sid in self.styles else sid,
                    numbering=numpr if numpr and numpr[0] not in (None, "0") else None,
                    align=align, section_break=sect, in_textbox=in_textbox,
                    float_id=self._float.fid if self._float else "", textbox_id=self._textbox.xid if self._textbox else "")
        if para.numbering:
            para.autonum = self.numbering.label(*para.numbering)
            self._note_symbols(src, "bullet", self.numbering.font, [(f, o, n) for f, o, n in self.numbering.replaced],
                               para.autonum)
        if len(chain) > 1:
            self._record_join(chain, para)
        self._extra = []
        for q in chain:
            # フィールドと隠し文字の段落の状態は w:p ごと（段落をまたぐフィールドは扱わない）
            self._fields = []
            self._pstate = self.hidden_rule.para_state(q)
            self._walk(q, para, fmt={}, href=None, hidden="", deleted=False)
        extra = self._extra
        self._extra = []
        # 結果を持たないフィールドの記録に、段落の文字（位置の前後の抜粋に使う）を添える（入れ子の段落の記録は、その段落の読み取りで添えた）
        text = para.text_only()
        for rec in self.resultless[first_resultless:]:
            if rec.src == para.src:
                rec.text = text
        return para, extra

    def _record_join(self, chain, para):
        """つないだ連鎖を記録する。段落のスタイル（pStyle がなければ既定の段落スタイル）が 1 種類でなければ JoinInfo も。"""
        srcs = [self.pids.get(q, "?") for q in chain]
        self.joined.append((para.src, srcs))
        sids = [wval(q.find(f"{w('pPr')}/{w('pStyle')}"), "") or self.default_pstyle for q in chain]
        if len(set(sids)) > 1:
            self.joins.append(JoinInfo(src=para.src, srcs=srcs, style_ids=sids, used=para.style_id))

    def _field_href(self):
        for f in reversed(self._fields):
            if not f["code_mode"]:
                mm = re.search(r'HYPERLINK\s+"([^"]+)"', f["code"])
                if mm and "\\l" not in f["code"].split(mm.group(0))[-1][:5]:
                    return mm.group(1)
        return None

    def _in_code(self):
        return any(f["code_mode"] for f in self._fields)

    @staticmethod
    def _shown(para):
        """段落にこれまでに入れたアトムの量（アトムの数と文字数）。フィールドの結果が空かの判定に使う。"""
        return len(para.atoms), sum(len(a.text) for a in para.atoms)

    def _note_resultless(self, para, code, pos):
        """結果を持たないまま終わったフィールドが、Word では表示のある種類（ooxml.resultless_field_kind）なら記録する（self.resultless）。"""
        kind = resultless_field_kind(code)
        if kind:
            self.resultless.append(ResultlessField(para.src, kind, " ".join(code.split()), pos))

    def _note_symbols(self, src, kind, font, replaced, shown):
        """記号フォントの私用領域の符号の扱いを記録する（self.symbols）。replaced: 置き換えたもの [(フォントの名前, 元の文字,
        置き換えた文字)]。shown: 段落に入れる文字。そこに私用領域の文字が残っていれば（表にない符号・記号フォントでないフォント）、
        置き換えていないもの（SymbolReplaced.to が空）として記録する（font は書かれたフォント名）。"""
        self.symbols += [SymbolReplaced(src, kind, f, ord(old), new,
                                        known=(kind == "bullet" and LEGACY_BULLETS.get(old) == new)
                                        or (kind == "sym" and f == "Symbol" and (ord(old) & 0xFF) not in SYMBOL_ADDED))
                         for f, old, new in replaced]
        self.symbols += [SymbolReplaced(src, kind, font, ord(c), "") for c in shown if is_pua(c)]

    def _add_text(self, para, text, fmt, href):
        if not text:
            return
        f = frozenset(k for k, v in fmt.items() if v)
        a = para.atoms[-1] if para.atoms else None
        if a is not None and a.kind == "text" and a.fmt == f and a.href == href and a.link is None:
            a.text += text
        else:
            para.atoms.append(Atom(kind="text", text=text, fmt=f, href=href))

    def _walk(self, el, para, fmt, href, hidden, deleted):
        """el の子を読む。hidden は隠し文字か（隠したときの指定。ooxml.HiddenRule.run_hidden_by の "direct"・"style"。隠さないなら ""）。"""
        for ch in el:
            tag = ch.tag
            if not isinstance(tag, str):
                continue
            if tag in (w("pPr"), w("rPr"), w("bookmarkStart"), w("bookmarkEnd"), w("proofErr"),
                       w("commentRangeStart"), w("commentRangeEnd"), w("permStart"), w("permEnd")):
                continue
            if tag in (w("del"), w("moveFrom")):
                self._walk(ch, para, fmt, href, hidden, True)
                continue
            if tag == w("hyperlink"):
                rid = ch.get(f"{{{R_NS}}}id")
                h = href
                if rid and rid in self.rels:
                    h = self.rels[rid][1]
                self._walk(ch, para, fmt, h, hidden, deleted)
                continue
            if tag == w("fldSimple"):
                instr = ch.get(w("instr"), "")
                mm = re.search(r'HYPERLINK\s+"([^"]+)"', instr)
                shown, pos = self._shown(para), len(para.text_only())
                self._walk(ch, para, fmt, mm.group(1) if mm else href, hidden, deleted)
                if not (deleted or hidden or self._in_code()) and self._shown(para) == shown:
                    self._note_resultless(para, instr, pos)     # 結果の子がない（または空の）フィールド
                continue
            if tag == w("r"):
                self._run(ch, para, fmt, href, hidden or self.hidden_rule.run_hidden_by(ch, self._pstate), deleted)
                continue
            if tag == m("oMathPara") or tag == m("oMath"):
                if deleted or hidden or self._in_code():
                    continue
                para.atoms.append(Atom(kind="math", math=ch, display=(tag == m("oMathPara"))))
                continue
            if tag in (w("sdt"),):
                content = ch.find(w("sdtContent"))
                if content is not None:
                    self._walk(content, para, fmt, href, hidden, deleted)
                continue
            if tag in (w("ins"), w("moveTo"), w("smartTag"), w("customXml"), w("sdtContent"), w("dir"), w("bdo")):
                self._walk(ch, para, fmt, href, hidden, deleted)
                continue
            if len(ch):
                self._walk(ch, para, fmt, href, hidden, deleted)

    def _run(self, r, para, base_fmt, href, hidden, deleted):
        rpr = r.find(w("rPr"))
        fmt = dict(base_fmt)
        if rpr is not None:
            rs = wval(rpr.find(w("rStyle")))
            if rs:
                fmt.update(self.char_style_fmt(rs))
            fmt.update(_rpr_fmt(rpr))
        for ch in r:
            tag = ch.tag
            if not isinstance(tag, str):
                continue
            if tag == w("fldChar"):
                t = ch.get(w("fldCharType"))
                if t == "begin":
                    # skip: 削除・隠し文字の中、または別のフィールドのコードの中のフィールドは、表示されないので数えない
                    self._fields.append({"code": "", "code_mode": True, "shown": None, "pos": len(para.text_only()),
                                         "skip": bool(deleted or hidden or self._in_code())})
                elif t == "separate" and self._fields:
                    self._fields[-1]["code_mode"] = False
                    self._fields[-1]["shown"] = self._shown(para)
                elif t == "end" and self._fields:
                    f = self._fields.pop()
                    # separate がない、または結果が空のまま終わったフィールド
                    if not f["skip"] and (f["shown"] is None or f["shown"] == self._shown(para)):
                        self._note_resultless(para, f["code"], f["pos"])
                continue
            if tag == w("instrText"):
                if self._fields and self._fields[-1]["code_mode"]:
                    self._fields[-1]["code"] += ch.text or ""
                continue
            if tag in (w("rPr"), w("delText"), w("lastRenderedPageBreak")):
                continue
            if tag in (w("footnoteReference"), w("endnoteReference")):
                kind = "footnote" if tag == w("footnoteReference") else "endnote"
                if deleted and not self._in_code():
                    # 削除の変更履歴の中の参照は、参照として数えない（Word で変更をすべて承諾した状態）。参照先の注を
                    # 理由付きで除外するために記録する（文字の読み方は変えない）
                    self.deleted_note_refs.add(note_key(kind, ch.get(w("id")) or ""))
                if deleted or self._in_code():
                    continue
                if ch.get(w("customMarkFollows")) in ("1", "true"):
                    kind += "-custom"   # 記号は直後の w:t に本文の文字として入っている
                para.atoms.append(Atom(kind="fnref", fn_kind=kind, fn_id=ch.get(w("id")), fmt=frozenset({"sup"})))
                continue
            if tag in (w("footnoteRef"), w("endnoteRef")):
                # 脚注本文の先頭に Word が自動表示する番号
                para.atoms.append(Atom(kind="gen", text="", fn_kind="mark"))
                continue
            if tag in (w("drawing"), w("pict"), w("object")):
                if deleted or self._in_code():
                    continue
                self._graphic(ch, para, hidden)
                continue
            if deleted or self._in_code():
                continue
            h = href or self._field_href()
            if hidden:
                txt = _plain_of_run_child(ch)
                if txt:
                    self.hidden.append((para.src, txt))
                    if hidden == "style":
                        self.style_hidden.append((para.src, txt))
                continue
            if tag == w("t"):
                text, replaced = w_t_text(ch)
                if replaced or any(is_pua(c) for c in text):
                    font = run_font(ch.getparent(), keep_case=True)
                    self._note_symbols(para.src, "text", font, [(FONT_DISPLAY.get(font.lower(), font), o, n) for o, n in replaced],
                                       text)
                self._add_text(para, text, fmt, h)
            elif tag in (w("tab"), w("ptab")):
                self._add_text(para, "\t", fmt, h)
            elif tag == w("br"):
                if ch.get(w("type")) in BR_TEXT_TYPES:
                    self._add_text(para, "\n", fmt, h)
            elif tag == w("cr"):
                self._add_text(para, "\n", fmt, h)
            elif tag == w("noBreakHyphen"):
                self._add_text(para, "\u2011", fmt, h)
            elif tag == w("softHyphen"):
                self._add_text(para, "\u00ad", fmt, h)
            elif tag == w("sym"):
                text = sym_char(ch)
                font = (ch.get(w("font")) or "").strip()
                n = sym_code(ch)
                if n is not None and (symbol_char(font, n) or is_pua(text)):
                    code = chr(0xF000 + (n & 0xFF)) if n < 0x100 else chr(n)
                    new = symbol_char(font, n)
                    self._note_symbols(para.src, "sym", font, [(FONT_DISPLAY.get(font.lower(), font), code, new)] if new else [],
                                       text)
                self._add_text(para, text, fmt, h)
            elif tag == w("ruby"):
                base = ch.find(w("rubyBase"))
                rt = ch.find(w("rt"))
                if base is not None:
                    self._walk(base, para, fmt, h, hidden, deleted)
                if rt is not None:
                    self.warnings.append(f"{para.src}: ルビ「{_plain(rt)}」は JATS 1.1 で表現できないため、親文字のみ出力")

    # ------------------------------------------------------------ images / text boxes
    def _new_image(self, rid, source, el=None, **kw) -> ImageRef:
        """画像 1 つの ImageRef。el は画像の XML（pic:pic・v:imagedata・図形全体）で、画像ファイルがないときの digest に使う。"""
        self._img_count += 1
        target = ""
        if rid and rid in self.rels:
            typ, target, mode = self.rels[rid]
            if mode == "External":
                self.warnings.append(f"外部リンク画像（{target}）は取り込めません")
                target = ""
            elif target not in self.media:
                data = self.pkg.read(target)
                if data is not None:
                    self.media[target] = data
        img = ImageRef(rel_id=rid or "", target=target, source=source, image_id=f"img{self._img_count}",
                       float_id=self._float.fid if self._float else "", **kw)
        if not target and not kw.get("shape_only"):
            img.shape_only = True
        if target in self.media:
            img.digest = hashlib.sha1(self.media[target]).hexdigest()
        elif el is not None:
            img.digest = self._xml_digest(el)
        self.images.append(img)
        return img

    def _xml_digest(self, el) -> str:
        """図形の XML の SHA-1。文字（w:txbxContent）・位置（wp:positionH・positionV・simplePos・a:off）・ID と名前の属性は除く
        （文字を直したり、図形を動かしたりしても変わらない）。リレーションシップの ID（r:id など）は、参照先の部品の中身にする
        （部品の番号が振り直されても変わらない）。"""
        c = copy.deepcopy(el)
        drop = {w("txbxContent"), f"{{{WP_NS}}}positionH", f"{{{WP_NS}}}positionV", f"{{{WP_NS}}}simplePos", f"{{{A_NS}}}off"}
        for x in [x for x in c.iter() if x is not c and x.tag in drop]:
            if x.getparent() is not None:
                x.getparent().remove(x)
        for x in c.iter():
            if not isinstance(x.tag, str):
                continue
            for k in list(x.attrib):
                local = k.rsplit("}", 1)[-1]
                if k.startswith(f"{{{R_NS}}}"):
                    ref = self.rels.get(x.get(k))
                    data = self.pkg.read(ref[1]) if ref and ref[2] != "External" else None
                    x.set(k, hashlib.sha1(data).hexdigest() if data is not None else (ref[1] if ref else x.get(k)))
                elif local in DIGEST_DROP_ATTRS:
                    del x.attrib[k]
        return hashlib.sha1(etree.tostring(c, method="c14n", exclusive=True)).hexdigest()

    def _textboxes(self, container, para, holder=None, inline=False, group=False, vml=False):
        """container（w:drawing / w:pict / w:object）の中のテキストボックスの段落・表を読み、段落 para の後ろに並べる。

        本文（word/document.xml）のテキストボックスごとに TextBox を記録し（_new_textbox）、中身を読む間だけ self._textbox に
        する（中の段落・表の textbox_id）。入れ子の内側のテキストボックスは、外側を読んでいる間に読むので、TextBox を作らず、
        外側の ID を継ぐ。holder・inline・group は DrawingML の wp:inline / wp:anchor と、グループ図形・描画キャンバスの中か。
        """
        for tx in container.iter(w("txbxContent")):
            # 入れ子のテキストボックスは外側の処理で読む
            if _in_textbox(tx, container):
                continue
            outer = self._textbox
            if outer is None and self.part == "word/document.xml":
                self._textbox = self._new_textbox(tx, para, holder, inline, group, vml)
            # 段落と表も、コンテンツコントロール（w:sdt）や w:customXml に包まれていることがある
            for el in _children(tx, (w("p"), w("tbl"))):
                if el.tag == w("p"):
                    if el in self.later:        # 段落記号の削除で前の段落につながる（前の段落といっしょに読んだ）
                        continue
                    sub, extra = self._read_nested_paragraph(el)
                    self._extra.append(sub)
                    self._extra.extend(extra)
                elif el.tag == w("tbl"):
                    self._extra.append(self._read_nested_table(el))
            self._textbox = outer

    def _new_textbox(self, tx, para, holder, inline, group, vml) -> TextBox:
        """テキストボックス tx（w:txbxContent）の TextBox（種類・大きさ）。文字の読み方には関わらない。

        大きさ: DrawingML は wp:extent（グループ図形・描画キャンバスの中なら、テキストボックスの wps:spPr の a:ext に、一番外側の
        グループの拡大率〈wp:extent / wpg:grpSpPr の a:chExt。chExt がなければ 1〉を掛ける）。VML は図形の style の width・height
        （pt のときだけ。ほかの単位〈cm・in・%・グループの座標〉は読めないとして None）。
        """
        tb = TextBox(xid=f"x{len(self.textboxes) + 1}", anchor_src=para.src, source="vml" if vml else "wps",
                     float_id=self._float.fid if self._float else "")
        if vml:
            shape = next((a for a in tx.iterancestors() if a.tag in VML_BOX_SHAPES), None)
            style = re.sub(r"\s", "", shape.get("style", "") if shape is not None else "").lower()
            tb.width_cm, tb.height_cm = _vml_cm(style, "width"), _vml_cm(style, "height")
            tb.absolute = "position:absolute" in style
            tb.inline = not tb.absolute
            tb.group = any(a.tag == f"{{{V_NS}}}group" for a in tx.iterancestors())
        else:
            tb.inline, tb.group = inline, group
            ext = holder.find(f"{{{WP_NS}}}extent") if holder is not None else None
            if not group:
                if ext is not None:
                    tb.width_cm, tb.height_cm = _emu_cm(ext.get("cx")), _emu_cm(ext.get("cy"))
            else:
                wsp = next((a for a in tx.iterancestors() if a.tag == f"{{{WPS_NS}}}wsp"), None)
                a_ext = wsp.find(f"{{{WPS_NS}}}spPr/{{{A_NS}}}xfrm/{{{A_NS}}}ext") if wsp is not None else None
                if a_ext is not None:
                    groups = [a for a in tx.iterancestors() if a.tag in (f"{{{WPG_NS}}}wgp", f"{{{WPC_NS}}}wpc")]
                    ch = groups[-1].find(f"{{{WPG_NS}}}grpSpPr/{{{A_NS}}}xfrm/{{{A_NS}}}chExt") if groups else None
                    sx = sy = 1.0
                    if ch is not None and ext is not None:
                        sx = _ratio(ext.get("cx"), ch.get("cx"))
                        sy = _ratio(ext.get("cy"), ch.get("cy"))
                    w_cm, h_cm = _emu_cm(a_ext.get("cx")), _emu_cm(a_ext.get("cy"))
                    tb.width_cm = w_cm * sx if w_cm is not None else None
                    tb.height_cm = h_cm * sy if h_cm is not None else None
        self.textboxes.append(tb)
        return tb

    def _read_nested_paragraph(self, p):
        # 外側の段落の読み取りの途中なので、外側の段落の分（中の段落・フィールド・隠し文字の段落の状態）を退避しておく
        saved = (self._extra, self._fields, self._pstate)
        sub, extra = self.read_paragraph(p, in_textbox=True)
        self._extra, self._fields, self._pstate = saved
        return sub, extra

    def _read_nested_table(self, tbl):
        # セルの段落を読むと read_paragraph が _extra・_fields・_pstate を作り直すため、外側の段落の分を退避しておく
        saved = (self._extra, self._fields, self._pstate)
        t = self.read_table(tbl)
        t.in_textbox = True
        self._extra, self._fields, self._pstate = saved
        return t

    def _graphic(self, el, para, hidden):
        """画像・図形。隠し文字のランの中の画像も doc.images に入れる（ImageRef.hidden。スタイル・既定の書式で隠したものは
        hidden_style も）が、段落のアトムにはしない。テキストボックスの中の段落は、隠し文字のランの中でも隠さずに読む
        （画像と違う。0.25.0 と同じ。docs/DESIGN.md の 4.1）。"""
        self._draw_count += 1
        hid = {"hidden": bool(hidden), "hidden_style": hidden == "style",
               "draw_id": f"g{self._draw_count}", "para_src": para.src}
        if el.tag == w("drawing"):
            holder = el.find(f"{{{WP_NS}}}inline")
            inline = holder is not None
            if holder is None:
                holder = el.find(f"{{{WP_NS}}}anchor")
            cx = cy = 0
            descr = ""
            if holder is not None:
                ext = holder.find(f"{{{WP_NS}}}extent")
                if ext is not None:
                    cx, cy = int(ext.get("cx", "0")), int(ext.get("cy", "0"))
                dp = holder.find(f"{{{WP_NS}}}docPr")
                if dp is not None:
                    descr = dp.get("descr", "") or dp.get("title", "")
            has_tx = any(True for _ in el.iter(w("txbxContent")))
            gd = el.find(f".//{{{A_NS}}}graphicData")
            uri = gd.get("uri", "") if gd is not None else ""
            outer = self._float
            if (not inline and holder is not None and outer is None and self.part == "word/document.xml"
                    and (has_tx or "wordprocessingGroup" in uri or "wordprocessingCanvas" in uri)):
                self._float = self._new_float(holder, para, "wordprocessingGroup" in uri)
            # テキストボックスの中の画像は、テキストボックスの段落として読む（ここで拾うと二重になる）
            pics = [pic for pic in el.iter(f"{{{PIC_NS}}}pic") if not _in_textbox(pic, el)]
            for pic in pics:
                blip = pic.find(f".//{{{A_NS}}}blip")
                rid = blip.get(f"{{{R_NS}}}embed") if blip is not None else None
                ext = pic.find(f"{{{PIC_NS}}}spPr/{{{A_NS}}}xfrm/{{{A_NS}}}ext")
                pcx, pcy = cx, cy
                if ext is not None and len(pics) > 1:
                    sx = sy = 1.0
                    groups = [a for a in pic.iterancestors() if a.tag in (f"{{{WPG_NS}}}wgp", f"{{{WPC_NS}}}wpc")]
                    ch = (groups[-1].find(f"{{{WPG_NS}}}grpSpPr/{{{A_NS}}}xfrm/{{{A_NS}}}chExt") if groups else None)
                    wext = holder.find(f"{{{WP_NS}}}extent") if holder is not None else None
                    if ch is not None and wext is not None:
                        sx = _ratio(wext.get("cx"), ch.get("cx"))
                        sy = _ratio(wext.get("cy"), ch.get("cy"))
                    pcx, pcy = round(int(ext.get("cx", "0")) * sx), round(int(ext.get("cy", "0")) * sy)
                img = self._new_image(rid, "drawing", el=pic, cx_emu=pcx, cy_emu=pcy, inline=inline, descr=descr,
                                      **hid)
                if not hidden:
                    para.atoms.append(Atom(kind="image", image=img))
            if not pics:
                if not has_tx or "wordprocessingGroup" in uri or "wordprocessingCanvas" in uri or "chart" in uri:
                    img = self._new_image(None, "drawing", el=el, cx_emu=cx, cy_emu=cy, inline=inline, descr=descr,
                                          shape_only=True, decoration=shape_decoration(el), **hid)
                    if not hidden:
                        para.atoms.append(Atom(kind="image", image=img))
            if has_tx:
                self._textboxes(el, para, holder=holder, inline=inline,
                                group="wordprocessingGroup" in uri or "wordprocessingCanvas" in uri)
            self._float = outer
            return
        # VML（w:pict / w:object）
        progid = ""
        ole = el.find(f".//{{{O_NS}}}OLEObject")
        if ole is not None:
            progid = ole.get("ProgID", "")
        imgdata = [d for d in el.iter(f"{{{V_NS}}}imagedata") if not _in_textbox(d, el)]
        shape = el.find(f".//{{{V_NS}}}shape")
        cx = cy = 0
        if shape is not None:
            style = shape.get("style", "")
            mw = re.search(r"width:([\d.]+)pt", style)
            mh = re.search(r"height:([\d.]+)pt", style)
            if mw and mh:
                cx, cy = int(float(mw.group(1)) * 12700), int(float(mh.group(1)) * 12700)
        for d in imgdata:
            rid = d.get(f"{{{R_NS}}}id")
            img = self._new_image(rid, "ole" if el.tag == w("object") else "vml", el=d,
                                  cx_emu=cx, cy_emu=cy, ole_progid=progid, **hid)
            if not hidden:
                para.atoms.append(Atom(kind="image", image=img))
        has_tx = any(True for _ in el.iter(w("txbxContent")))
        if not imgdata and not has_tx:
            img = self._new_image(None, "vml", el=el, cx_emu=cx, cy_emu=cy, shape_only=True, ole_progid=progid, **hid)
            if not hidden:
                para.atoms.append(Atom(kind="image", image=img))
        if has_tx:
            self._textboxes(el, para, vml=True)

    def _new_float(self, holder, para, group) -> Float:
        fl = Float(fid=f"s{len(self.floats) + 1}", anchor_src=para.src, group=group)
        for tag, pre in (("positionH", "h"), ("positionV", "v")):
            pos = holder.find(f"{{{WP_NS}}}{tag}")
            if pos is None:
                continue
            setattr(fl, f"{pre}_from", pos.get("relativeFrom", ""))
            off, al = pos.find(f"{{{WP_NS}}}posOffset"), pos.find(f"{{{WP_NS}}}align")
            if off is not None and (off.text or "").strip().lstrip("-").isdigit():
                setattr(fl, f"{pre}_offset_cm", int(off.text) / 360000.0)
            elif al is not None:
                setattr(fl, f"{pre}_align", (al.text or "").strip())
        ext = holder.find(f"{{{WP_NS}}}extent")
        if ext is not None:
            fl.width_cm, fl.height_cm = int(ext.get("cx", "0")) / 360000.0, int(ext.get("cy", "0")) / 360000.0
        fl.wrap = next((etree_local(c) for c in holder if etree_local(c).startswith("wrap")), "")
        self.floats.append(fl)
        return fl


# 図形の XML の digest（_xml_digest）から除く属性（名前空間によらず、ローカル名で）
DIGEST_DROP_ATTRS = frozenset({"id", "name", "anchorId", "editId", "paraId", "textId"})
_BOX_PRST = ("rect", "roundRect")
_WHITE_SCHEME = ("bg1", "lt1")


def _fill_kind(wsp) -> str:
    """図形 wps:wsp の塗り。none（塗りなし）/ white（白）/ other（それ以外。グラデーション・画像・色つき・テーマの塗り）。"""
    sp = wsp.find(f"{{{WPS_NS}}}spPr")
    if sp is not None:
        for ch in sp:
            tag = etree_local(ch)
            if tag == "noFill":
                return "none"
            if tag == "solidFill":
                col = next(iter(ch), None)
                if col is None:
                    return "other"
                # 色の加工（明るさ・色合いなど）があれば純白ではない。透明度（alpha）は塗りの色を変えない
                if any(etree_local(x) != "alpha" for x in col):
                    return "other"
                name, val = etree_local(col), (col.get("val") or "").lower()
                if (name == "srgbClr" and val == "ffffff") or (name == "schemeClr" and val in _WHITE_SCHEME) \
                        or (name == "sysClr" and val == "window"):
                    return "white"
                return "other"
            if tag in ("gradFill", "blipFill", "pattFill", "grpFill"):
                return "other"
    # spPr に塗りの指定がなければ、図形のスタイル（wps:style の fillRef）に従う。idx 0 は塗りなし
    st = wsp.find(f"{{{WPS_NS}}}style/{{{A_NS}}}fillRef")
    if st is not None and (st.get("idx") or "0") != "0":
        return "other"
    return "none"


def _shape_kind(wsp) -> str:
    """図形 wps:wsp の種類。text（文字のある長方形・角丸）/ frame（文字のない長方形・角丸で塗りなし）/ mask（同じく白い塗り）/
    line（文字のない線・コネクタ・矢印）/ ""（それ以外。楕円・三角形・フリーフォーム・色つきなど）。"""
    sp = wsp.find(f"{{{WPS_NS}}}spPr")
    geom = sp.find(f"{{{A_NS}}}prstGeom") if sp is not None else None
    prst = geom.get("prst", "") if geom is not None else ""
    box = wsp.find(f"{{{WPS_NS}}}txbx")
    has_text = box is not None and any((t.text or "").strip() for t in box.iter(w("t")))
    if prst in _BOX_PRST:
        if has_text:
            return "text"
        fill = _fill_kind(wsp)
        return "frame" if fill == "none" else "mask" if fill == "white" else ""
    low = prst.lower()
    if prst and not has_text and not low.startswith("flowchart") and ("line" in low or "connector" in low or "arrow" in low):
        return "line"
    return ""


def shape_decoration(el) -> str:
    """画像を持たない図形 el（w:drawing）が、画像の位置に数えない飾りなら、その種類。そうでなければ ""。

    飾り（修正計画 W1 の 2.3 の D）: 単独の図形の、文字のない枠（frame。長方形・角丸で塗りなし）・白い四角（mask）・線やコネクタや矢印（line）。
    グループ（描画キャンバスも）で、中の図形がすべて枠か白い四角（frame。白い四角だけなら mask）、またはすべて文字のある長方形・角丸
    （textgroup）のもの。グラフ・VML・それ以外の形（楕円・三角形・フリーフォームなど）・線だけを集めたグループ・枠と文字の図形が混ざった
    グループは、画像の位置に数える（迷うものは数える側に倒す）。"""
    gd = el.find(f".//{{{A_NS}}}graphicData")
    uri = gd.get("uri", "") if gd is not None else ""
    shapes = [x for x in el.iter(f"{{{WPS_NS}}}wsp") if not _in_textbox(x, el)]
    if "wordprocessingShape" in uri:
        kind = _shape_kind(shapes[0]) if len(shapes) == 1 else ""
        return kind if kind in ("frame", "mask", "line") else ""
    if "wordprocessingGroup" in uri or "wordprocessingCanvas" in uri:
        # グループの中に画像・表・グラフがあれば、図形だけの集まりではない
        if not shapes or any(True for x in el.iter(f"{{{PIC_NS}}}pic", f"{{{WPG_NS}}}graphicFrame") if not _in_textbox(x, el)):
            return ""
        kinds = {_shape_kind(x) for x in shapes}
        if kinds <= {"frame", "mask"}:
            return "mask" if kinds == {"mask"} else "frame"
        if kinds == {"text"}:
            return "textgroup"
    return ""


def etree_local(el) -> str:
    tag = el.tag if isinstance(el.tag, str) else ""
    return tag.rsplit("}", 1)[-1]


TWIP_CM = 2.54 / 1440


def read_layout(root, pkg) -> Layout:
    """本文の段組みと行の設定。段組みのあるセクション（なければ最後のセクション）の w:sectPr から求める。"""
    sects = list(root.iter(w("sectPr")))
    if not sects:
        return Layout()

    def num(el, attr, default=0):
        try:
            return int(el.get(w(attr))) if el is not None and el.get(w(attr)) is not None else default
        except ValueError:
            return default
    sp = next((x for x in sects if num(x.find(w("cols")), "num", 1) > 1), sects[-1])
    pg, mar, cols, grid = (sp.find(w(t)) for t in ("pgSz", "pgMar", "cols", "docGrid"))
    width = num(pg, "w", 11906) - num(mar, "left", 1440) - num(mar, "right", 1440)
    height = num(pg, "h", 16838) - num(mar, "top", 1440) - num(mar, "bottom", 1440)
    n = max(1, num(cols, "num", 1))
    col = (width - num(cols, "space", 425) * (n - 1)) / n
    font_pt = _body_font_pt(pkg)
    # 文字数と行数の指定（w:docGrid）があれば、その行送りと字送り（charSpace は 1/4096 pt 単位の追加分）
    gtype = grid.get(w("type")) if grid is not None else ""
    pitch = num(grid, "linePitch", 0) if gtype in ("lines", "linesAndChars", "snapToChars") else 0
    char_pt = font_pt + (num(grid, "charSpace", 0) / 4096.0 if gtype in ("linesAndChars", "snapToChars") else 0)
    return Layout(text_width_cm=width * TWIP_CM, text_height_cm=height * TWIP_CM, columns=n,
                  column_width_cm=col * TWIP_CM, line_pitch_cm=(pitch or font_pt * 20 * 1.5) * TWIP_CM,
                  chars_per_line=(col / 20.0) / char_pt if char_pt else 0.0)


def _body_font_pt(pkg) -> float:
    """既定の段落スタイル（標準）の文字の大きさ（pt）。"""
    st = pkg.xml("word/styles.xml")
    size = None
    if st is not None:
        dd = st.find(f"{w('docDefaults')}/{w('rPrDefault')}/{w('rPr')}/{w('sz')}")
        if dd is not None:
            size = dd.get(w("val"))
        for s in st.findall(w("style")):
            if s.get(w("type")) == "paragraph" and s.get(w("default")) in ("1", "true"):
                sz = s.find(f"{w('rPr')}/{w('sz')}")
                if sz is not None:
                    size = sz.get(w("val"))
    try:
        return int(size) / 2.0 if size else 10.5
    except ValueError:
        return 10.5


def _children(el, tags):
    """el の子のうち、タグが tags のものを文書の順に返す。

    コンテンツコントロール（w:sdt）なら w:sdtContent の中を、w:customXml ならその中を、入れ子も再帰でたどる。
    表の行、行の中のセル、テキストボックスの段落と表は、これらに包まれていることがある。直下の子だけを見ると
    包まれたものを読み落とす（検証側の ooxml.paragraph_ids はすべての w:p を数えるので、不変性チェックで「出力漏れ」になる）。
    """
    for ch in el:
        if ch.tag in tags:
            yield ch
        elif ch.tag == w("sdt"):
            content = ch.find(w("sdtContent"))
            if content is not None:
                yield from _children(content, tags)
        elif ch.tag == w("customXml"):
            yield from _children(ch, tags)


def _emu_cm(v):
    """EMU の文字列を cm にする（読めなければ None）。"""
    try:
        return int(v) / 360000.0
    except (TypeError, ValueError):
        return None


def _ratio(a, b) -> float:
    """グループ図形の拡大率 a / b（読めない・0 なら 1）。"""
    try:
        a, b = int(a), int(b)
    except (TypeError, ValueError):
        return 1.0
    return a / b if a > 0 and b > 0 else 1.0


def _vml_cm(style, prop):
    """VML の style（空白を除いて小文字にしたもの）の width・height を cm にする。pt のときだけ（ほかの単位は None）。"""
    mm = re.search(rf"(?:^|;){prop}:([0-9.]+)pt(?:;|$)", style)
    if not mm:
        return None
    try:
        return float(mm.group(1)) / 72.0 * 2.54
    except ValueError:
        return None


def _in_textbox(el, container) -> bool:
    """el が container の中のテキストボックス（w:txbxContent）の中にあるか。"""
    anc = el.getparent()
    while anc is not None and anc is not container:
        if anc.tag == w("txbxContent"):
            return True
        anc = anc.getparent()
    return False


def _plain(el) -> str:
    return "".join(t.text or "" for t in el.iter(w("t")))


def _plain_of_run_child(ch) -> str:
    """隠し文字のランの子の文字（レポートの 6 章の隠し文字の一覧に載せる。文字ポリシーの「含める」もの）。"""
    tag = ch.tag
    if tag == w("t"):
        return w_t_text(ch)[0]
    if tag in (w("tab"), w("ptab")):
        return "\t"
    if tag == w("br"):
        return "\n" if ch.get(w("type")) in BR_TEXT_TYPES else ""
    if tag == w("cr"):
        return "\n"
    if tag == w("noBreakHyphen"):
        return "\u2011"
    if tag == w("softHyphen"):
        return "\u00ad"
    if tag == w("sym"):
        return sym_char(ch)
    return ""


def _cell_paragraphs(cell):
    """セルの段落（入れ子の表のセル・セルの中のテキストボックスの段落を含む）。"""
    for b in cell.blocks:
        if isinstance(b, Para):
            yield b
        else:
            yield from b.paragraphs()


def _row_empty(row) -> bool:
    """行のどのセルの段落にも、アトム（文字・画像・数式・注の参照）がない。"""
    return not any(q.atoms for c in row.cells for q in _cell_paragraphs(c))


def table_head(t) -> str:
    """表の最初の文字のあるセルの文字の冒頭 20 字（長ければ「…」を付ける。Word で表を探す手がかり）。"""
    for row in t.rows:
        for c in row.cells:
            text = "".join(q.text_only() for q in _cell_paragraphs(c)).strip()
            if text:
                return text[:20] + ("…" if len(text) > 20 else "")
    return ""


def read_docx(path) -> Document:
    return Reader(path).read()
