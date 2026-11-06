"""tools/sanitize_docx.py の直し方の試作（scratchpad だけ）。"""
import os, re, sys, tempfile, zipfile
from pathlib import Path
from lxml import etree
from jasme_jats.ooxml import w
from jasme_jats.pdfdocx import AUTHOR

AUTHOR_PLACEHOLDER = "作成者"
COMMENT_PARTS = re.compile(r"word/(?:comments|commentsExtended|commentsExtensible|commentsIds|people)\.xml$")
CUSTOM_PARTS = re.compile(r"(?:customXml/.*|docProps/custom\.xml)$")
HF_PART = re.compile(r"word/(header|footer)\d*\.xml$")
COMMENT_TAGS = {w("commentRangeStart"), w("commentRangeEnd"), w("commentReference")}
CORE_BLANK = ("{http://purl.org/dc/elements/1.1/}creator", "{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}lastModifiedBy",
              "{http://purl.org/dc/elements/1.1/}title", "{http://purl.org/dc/elements/1.1/}subject",
              "{http://purl.org/dc/elements/1.1/}description", "{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}keywords",
              "{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}category")
APP_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}"
REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
CT_NS = "{http://schemas.openxmlformats.org/package/2006/content-types}"

def _dropped(name):
    return bool(COMMENT_PARTS.match(name) or CUSTOM_PARTS.match(name))

def _rel_target(base_part, target):
    if target.startswith("/"):
        return target[1:]
    base = os.path.dirname(os.path.dirname(base_part)) if base_part.startswith("_rels") else os.path.dirname(os.path.dirname(base_part))
    return os.path.normpath(os.path.join(base, target)).replace("\\", "/")

def _xml(data):
    return etree.fromstring(data)

def _bytes(root):
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)

def clean_part(name, data):
    if name.startswith("word/") and name.endswith(".xml") and not _dropped(name):
        root = _xml(data)
        changed = False
        if HF_PART.match(name):
            new = etree.Element(root.tag, nsmap=root.nsmap)
            etree.SubElement(new, w("p"))
            return _bytes(new)
        for el in list(root.iter(*COMMENT_TAGS)):
            parent = el.getparent()
            parent.remove(el); changed = True
            if parent.tag == w("r") and all(ch.tag == w("rPr") for ch in parent):
                parent.getparent().remove(parent)
        for el in root.iter():
            a = el.get(w("author"))
            if a is not None and a != AUTHOR:
                el.set(w("author"), AUTHOR_PLACEHOLDER); changed = True
            if el.get(w("initials")) is not None:
                el.set(w("initials"), ""); changed = True
        if name == "word/settings.xml":
            for el in list(root.iter(w("attachedTemplate"))):
                el.getparent().remove(el); changed = True
        return _bytes(root) if changed else data
    if name.endswith(".rels"):
        root = _xml(data)
        part = name.replace("_rels/", "").removesuffix(".rels")
        changed = False
        for rel in list(root):
            t, typ = rel.get("Target", ""), rel.get("Type", "")
            if typ.endswith("/attachedTemplate") or (rel.get("TargetMode") != "External" and _dropped(_rel_target(name, t))):
                root.remove(rel); changed = True
        return _bytes(root) if changed else data
    if name == "[Content_Types].xml":
        root = _xml(data)
        for o in list(root.iter(CT_NS + "Override")):
            if _dropped(o.get("PartName", "").lstrip("/")):
                root.remove(o)
        return _bytes(root)
    if name == "docProps/core.xml":
        root = _xml(data)
        for t in CORE_BLANK:
            for el in root.iter(t):
                el.text = None
        return _bytes(root)
    if name == "docProps/app.xml":
        root = _xml(data)
        for t in ("Company", "Manager", "HyperlinkBase"):
            for el in root.iter(APP_NS + t):
                el.text = None
        return _bytes(root)
    return data

def sanitize(src, dst):
    src, dst = Path(src), Path(dst)
    if dst.exists() and os.path.samefile(src, dst):
        raise SystemExit("入力と出力に同じファイルが指定されています。出力には別のファイル名を指定してください（元の docx を残すため）")
    fd, tmp = tempfile.mkstemp(suffix=".docx", dir=dst.parent); os.close(fd)
    try:
        with zipfile.ZipFile(src) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if _dropped(item.filename):
                    continue
                zout.writestr(item, clean_part(item.filename, zin.read(item.filename)))
        from jasme_jats.fidelity import source_texts
        if source_texts(src) != source_texts(tmp):
            raise SystemExit("本文の文字が変わったので書き出さなかった")
        os.replace(tmp, dst)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
