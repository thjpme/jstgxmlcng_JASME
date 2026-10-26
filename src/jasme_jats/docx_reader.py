"""docx を読み取り、中間表現（model.Document）を作る。

文字の扱いは ooxml.py の文字ポリシーに従う。ここで作る「アトム」の文字列を連結したものが、
ooxml.canonical_text() で独立に取り出した文字列と一致することを、最後に fidelity.py で確かめる。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .model import Atom, Cell, Document, Float, ImageRef, Layout, Para, Row, Table, note_key
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
        # 削除の変更履歴の中の脚注・文末脚注の参照の注の鍵（参照として数えない。structure.Classifier.attach_word_notes が除外の理由に使う）
        self.deleted_note_refs = set()
        self._img_count = 0
        self.floats = []
        self._float = None      # 読み取り中の浮動配置の図形（Float）

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
                       images=self.images, floats=self.floats, layout=read_layout(root, self.pkg),
                       deleted_note_refs=self.deleted_note_refs)
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
                  style_name=self.styles[sid].name if sid in self.styles else (sid or ""),
                  float_id=self._float.fid if self._float else "")
        # 行と、行の中のセルは、コンテンツコントロール（w:sdt）や w:customXml に包まれていることがある
        for tr in _children(tbl, (w("tr"),)):
            trpr = tr.find(w("trPr"))
            row = Row(header=trpr is not None and on_off(trpr.find(w("tblHeader"))))
            for c in _children(tr, (w("tc"),)):
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
                    align=align, section_break=sect, in_textbox=in_textbox,
                    float_id=self._float.fid if self._float else "")
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
        img = ImageRef(rel_id=rid or "", target=target, source=source, image_id=f"img{self._img_count}",
                       float_id=self._float.fid if self._float else "", **kw)
        if not target and not kw.get("shape_only"):
            img.shape_only = True
        self.images.append(img)
        return img

    def _textboxes(self, container, para):
        for tx in container.iter(w("txbxContent")):
            # 入れ子のテキストボックスは外側の処理で読む
            if _in_textbox(tx, container):
                continue
            # 段落と表も、コンテンツコントロール（w:sdt）や w:customXml に包まれていることがある
            for el in _children(tx, (w("p"), w("tbl"))):
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
        t.in_textbox = True
        self._extra, self._fields = saved
        return t

    def _graphic(self, el, para, hidden):
        """画像・図形。隠し文字のランの中の画像も doc.images に入れる（ImageRef.hidden）が、段落のアトムにはしない。"""
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
                ext = pic.find(f".//{{{A_NS}}}ext")
                pcx, pcy = (int(ext.get("cx", "0")), int(ext.get("cy", "0"))) if (ext is not None and len(pics) > 1) else (cx, cy)
                img = self._new_image(rid, "drawing", cx_emu=pcx, cy_emu=pcy, inline=inline, descr=descr,
                                      hidden=hidden)
                if not hidden:
                    para.atoms.append(Atom(kind="image", image=img))
            if not pics:
                if not has_tx or "wordprocessingGroup" in uri or "wordprocessingCanvas" in uri or "chart" in uri:
                    img = self._new_image(None, "drawing", cx_emu=cx, cy_emu=cy, inline=inline, descr=descr,
                                          shape_only=True, hidden=hidden)
                    if not hidden:
                        para.atoms.append(Atom(kind="image", image=img))
            if has_tx:
                self._textboxes(el, para)
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
            img = self._new_image(rid, "ole" if el.tag == w("object") else "vml",
                                  cx_emu=cx, cy_emu=cy, ole_progid=progid, hidden=hidden)
            if not hidden:
                para.atoms.append(Atom(kind="image", image=img))
        has_tx = any(True for _ in el.iter(w("txbxContent")))
        if not imgdata and not has_tx:
            img = self._new_image(None, "vml", cx_emu=cx, cy_emu=cy, shape_only=True, ole_progid=progid,
                                  hidden=hidden)
            if not hidden:
                para.atoms.append(Atom(kind="image", image=img))
        if has_tx:
            self._textboxes(el, para)


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
