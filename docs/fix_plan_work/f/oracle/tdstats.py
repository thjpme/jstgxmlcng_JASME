"""td1〜3 のテキストボックスの数値だけを出す（文字は出さない）。"""
import sys, zipfile
from lxml import etree
NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
      "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
      "wps": "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
      "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
      "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006"}
W = NS["w"]
for path in sys.argv[1:]:
    root = etree.fromstring(zipfile.ZipFile(path).read("word/document.xml"))
    cm = 360000
    sect = root.findall(".//w:sectPr", NS)
    for s in sect[-1:]:
        cols = s.find("w:cols", NS); pg = s.find("w:pgSz", NS); mar = s.find("w:pgMar", NS)
        print(path, "cols", cols.attrib if cols is not None else None, "pgw", pg.get(f"{{{W}}}w") if pg is not None else None,
              "mar", mar.get(f"{{{W}}}left"), mar.get(f"{{{W}}}right"))
    for txbx in root.iter(f"{{{NS['wps']}}}txbx"):
        if txbx.xpath("ancestor::mc:Fallback", namespaces=NS):
            continue
        holder = txbx.xpath("ancestor::wp:anchor|ancestor::wp:inline", namespaces=NS)[-1]
        ext = holder.find("wp:extent", NS)
        grp = bool(txbx.xpath("ancestor::*[local-name()='wgp']"))
        pv = holder.find("wp:positionV", NS); ph = holder.find("wp:positionH", NS)
        def off(p):
            if p is None: return None
            o = p.find("wp:posOffset", NS)
            return (p.get("relativeFrom"), round(int(o.text) / cm, 2) if o is not None else None)
        content = txbx.find("w:txbxContent", NS)
        text = "".join(t.text or "" for t in content.iter(f"{{{W}}}t"))
        nparas = len(content.findall(".//w:p", NS))
        haspic = bool(holder.xpath(".//pic:pic", namespaces=NS))
        inner_pic = bool(content.xpath(".//pic:pic", namespaces=NS))
        anchor_p = holder.xpath("ancestor::w:p", namespaces=NS)[-1]
        aptext = "".join(t.text or "" for t in anchor_p.iter(f"{{{W}}}t") if not t.xpath("ancestor::w:txbxContent", namespaces=NS))
        anchor_img = bool(anchor_p.xpath(".//pic:pic[not(ancestor::w:txbxContent)]", namespaces=NS))
        # 前後の段落に画像があるか
        sibs = list(anchor_p.itersiblings(preceding=True))[:3] + list(anchor_p.itersiblings())[:3]
        near_img = any(s.xpath(".//pic:pic", namespaces=NS) for s in sibs) or anchor_img
        print(f"{holder.tag.split('}')[1]:6} grp={int(grp)} cx={int(ext.get('cx'))/cm:5.2f} cy={int(ext.get('cy'))/cm:5.2f} "
              f"h={off(ph)} v={off(pv)} chars={len(text.strip())} paras={nparas} pic_in_shape={int(haspic)} pic_in_txt={int(inner_pic)} "
              f"anchor_chars={len(aptext.strip())} anchor_img={int(anchor_img)} near_img={int(near_img)}")
