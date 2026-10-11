"""docx を読み取り、中間表現（model.Document）を作る。

文字の扱いは ooxml.py の文字ポリシーに従う。ここで作る「アトム」の文字列を連結したものが、
ooxml.canonical_text() で独立に取り出した文字列と一致することを、最後に fidelity.py で確かめる。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .model import Atom, Cell, Document, ImageRef, Para, Row, Table
from .numbering import Numbering
from .ooxml import (A_NS, BR_TEXT_TYPES, O_NS, PIC_NS, R_NS, V_NS, WP_NS, DocxPackage, m,
                    on_off, paragraph_ids, run_hidden, sym_char, w, wval)



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


class Reader:
    def __init__(self, path):
        self.pkg = DocxPackage(path)
        self.styles = read_styles(self.pkg)
        self.numbering = Numbering(self.pkg.xml("word/numbering.xml"))
        self.default_pstyle = next((s.sid for s in self.styles.values() if s.stype == "paragraph" and s.default), "")
        self.media = {}
        self.images = []
        self.warnings = []
        self.hidden = []
        self.textbox_excluded = []
        self._img_count = 0

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
                       styles=self.styles, warnings=self.warnings, hidden_text=self.hidden,
                       textbox_excluded=self.textbox_excluded, tracked_changes=tracked, comments=comments,
                       images=self.images)
        return doc

    def read_notes(self, part, tag, prefix) -> dict:
        root = self.pkg.xml(part)
        out = {}
        if root is None:
            return out
        saved = (self.part, self.rels, self.pids)
        self.part, self.rels, self.pids = part, self.pkg.rels(part), paragraph_ids(root, prefix)
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
        self.part, self.rels, self.pids = saved
        return out

    def read_block(self, el):
        tag = el.tag
        if tag == w("p"):
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
                  style_name=self.styles[sid].name if sid in self.styles else (sid or ""))
        for tr in tbl.findall(w("tr")):
            trpr = tr.find(w("trPr"))
            row = Row(header=trpr is not None and on_off(trpr.find(w("tblHeader"))))
            for tc in tr:
                if tc.tag == w("sdt"):
                    content = tc.find(w("sdtContent"))
                    tcs = content.findall(w("tc")) if content is not None else []
                elif tc.tag == w("tc"):
                    tcs = [tc]
                else:
                    continue
                for c in tcs:
                    tcpr = c.find(w("tcPr"))
                    cell = Cell()
                    if tcpr is not None:
                        gs = tcpr.find(w("gridSpan"))
                        if gs is not None:
                            cell.gridspan = int(wval(gs, "1") or 1)
                        vm = tcpr.find(w("vMerge"))
                        if vm is not None:
                            cell.vmerge = "restart" if wval(vm) == "restart" else "continue"
                    for ch in c:
                        cell.blocks.extend(self.read_block(ch))
                    row.cells.append(cell)
            t.rows.append(row)
        return t

    # ------------------------------------------------------------ paragraph
    def read_paragraph(self, p, in_textbox=False):
        src = self.pids.get(p, "?")
        ppr = p.find(w("pPr"))
        sid = ""
        numpr = None
        align = ""
        sect = False
        if ppr is not None:
            sid = wval(ppr.find(w("pStyle")), "") or ""
            np = ppr.find(w("numPr"))
            if np is not None:
                numpr = (wval(np.find(w("numId"))), int(wval(np.find(w("ilvl")), "0") or 0))
            align = wval(ppr.find(w("jc")), "") or ""
            sect = ppr.find(w("sectPr")) is not None
        sid = sid or self.default_pstyle
        if numpr is None:
            numpr = self.style_num(sid)
        elif numpr[0] is None:
            sn = self.style_num(sid)
            numpr = (sn[0], numpr[1]) if sn else None
        para = Para(src=src, style_id=sid, style_name=self.styles[sid].name if sid in self.styles else sid,
                    numbering=numpr if numpr and numpr[0] not in (None, "0") else None,
                    align=align, section_break=sect, in_textbox=in_textbox)
        if para.numbering:
            para.autonum = self.numbering.label(*para.numbering)
        self._extra = []
        self._fields = []
        self._walk(p, para, fmt={}, href=None, hidden=False, deleted=False)
        extra = self._extra
        self._extra = []
        return para, extra

    def _field_href(self):
        for f in reversed(self._fields):
            if not f["code_mode"]:
                mm = re.search(r'HYPERLINK\s+"([^"]+)"', f["code"])
                if mm and "\\l" not in f["code"].split(mm.group(0))[-1][:5]:
                    return mm.group(1)
        return None

    def _in_code(self):
        return any(f["code_mode"] for f in self._fields)

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
                self._walk(ch, para, fmt, mm.group(1) if mm else href, hidden, deleted)
                continue
            if tag == w("r"):
                self._run(ch, para, fmt, href, hidden or run_hidden(ch), deleted)
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
                    self._fields.append({"code": "", "code_mode": True})
                elif t == "separate" and self._fields:
                    self._fields[-1]["code_mode"] = False
                elif t == "end" and self._fields:
                    self._fields.pop()
                continue
            if tag == w("instrText"):
                if self._fields and self._fields[-1]["code_mode"]:
                    self._fields[-1]["code"] += ch.text or ""
                continue
            if tag in (w("rPr"), w("delText"), w("lastRenderedPageBreak")):
                continue
            if tag in (w("footnoteReference"), w("endnoteReference")):
                if deleted or self._in_code():
                    continue
                kind = "footnote" if tag == w("footnoteReference") else "endnote"
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
                continue
            if tag == w("t"):
                self._add_text(para, ch.text or "", fmt, h)
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
                self._add_text(para, sym_char(ch), fmt, h)
            elif tag == w("ruby"):
                base = ch.find(w("rubyBase"))
                rt = ch.find(w("rt"))
                if base is not None:
                    self._walk(base, para, fmt, h, hidden, deleted)
                if rt is not None:
                    self.warnings.append(f"{para.src}: ルビ「{_plain(rt)}」は JATS 1.1 で表現できないため、親文字のみ出力")

    # ------------------------------------------------------------ images / text boxes
    def _new_image(self, rid, source, **kw) -> ImageRef:
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
        img = ImageRef(rel_id=rid or "", target=target, source=source, image_id=f"img{self._img_count}", **kw)
        if not target and not kw.get("shape_only"):
            img.shape_only = True
        self.images.append(img)
        return img

    def _textboxes(self, container, para):
        for tx in container.iter(w("txbxContent")):
            # 入れ子のテキストボックスは外側の処理で読む
            if _in_textbox(tx, container):
                continue
            for el in tx:
                if el.tag == w("p"):
                    sub, extra = self._read_nested_paragraph(el)
                    self._extra.append(sub)
                    self._extra.extend(extra)
                elif el.tag == w("tbl"):
                    self._extra.append(self._read_nested_table(el))

    def _read_nested_paragraph(self, p):
        saved = (self._extra, self._fields)
        sub, extra = self.read_paragraph(p, in_textbox=True)
        self._extra, self._fields = saved
        return sub, extra

    def _read_nested_table(self, tbl):
        # セルの段落を読むと read_paragraph が _extra を作り直すため、外側の段落の分を退避しておく
        saved = (self._extra, self._fields)
        t = self.read_table(tbl)
        self._extra, self._fields = saved
        return t

    def _graphic(self, el, para, hidden):
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
            # テキストボックスの中の画像は、テキストボックスの段落として読む（ここで拾うと二重になる）
            pics = [pic for pic in el.iter(f"{{{PIC_NS}}}pic") if not _in_textbox(pic, el)]
            for pic in pics:
                blip = pic.find(f".//{{{A_NS}}}blip")
                rid = blip.get(f"{{{R_NS}}}embed") if blip is not None else None
                ext = pic.find(f".//{{{A_NS}}}ext")
                pcx, pcy = (int(ext.get("cx", "0")), int(ext.get("cy", "0"))) if (ext is not None and len(pics) > 1) else (cx, cy)
                img = self._new_image(rid, "drawing", cx_emu=pcx, cy_emu=pcy, inline=inline, descr=descr)
                if not hidden:
                    para.atoms.append(Atom(kind="image", image=img))
            has_tx = any(True for _ in el.iter(w("txbxContent")))
            if not pics:
                gd = el.find(f".//{{{A_NS}}}graphicData")
                uri = gd.get("uri", "") if gd is not None else ""
                if not has_tx or "wordprocessingGroup" in uri or "wordprocessingCanvas" in uri or "chart" in uri:
                    img = self._new_image(None, "drawing", cx_emu=cx, cy_emu=cy, inline=inline, descr=descr,
                                          shape_only=True)
                    if not hidden:
                        para.atoms.append(Atom(kind="image", image=img))
            if has_tx:
                self._textboxes(el, para)
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
            img = self._new_image(rid, "ole" if el.tag == w("object") else "vml",
                                  cx_emu=cx, cy_emu=cy, ole_progid=progid)
            if not hidden:
                para.atoms.append(Atom(kind="image", image=img))
        has_tx = any(True for _ in el.iter(w("txbxContent")))
        if not imgdata and not has_tx:
            img = self._new_image(None, "vml", cx_emu=cx, cy_emu=cy, shape_only=True, ole_progid=progid)
            if not hidden:
                para.atoms.append(Atom(kind="image", image=img))
        if has_tx:
            self._textboxes(el, para)


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
    if ch.tag == w("t"):
        return ch.text or ""
    if ch.tag in (w("tab"),):
        return "\t"
    return ""


def read_docx(path) -> Document:
    return Reader(path).read()
