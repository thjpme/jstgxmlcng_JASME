"""テスト用の docx を、JASME テンプレートのスタイル定義を使って生成する。

  python tests/make_fixtures.py

tests/fixtures/sample_full.docx : 本番に近い論文（数式・図表・注・文献・URL・意図的なスタイル違反を含む）
tests/fixtures/sample_edge.docx : 読み取りの境界ケース（Word の脚注、自動番号、隠し文字、変更履歴、
                                   テキストボックス、記号フォント、フィールドのハイパーリンクなど）
tests/fixtures/sample_float.docx : 位置を機械的に決められない浮動配置の図表（テキストボックス・グループ図形）。
                                   AI 補完（tests/data/ai_response_sample_float.json）が必要
tests/fixtures/sample_notes.docx : テンプレートの規定と違う書き方の注（本文の大きさの「（注1）」、引用文献の後ろの注の節、
                                   番号の書き方が想定外の注）
tests/fixtures/sample_pdfcheck.docx / .pdf : 出版版 PDF との照合。PDF は、出版社が組版で直した想定の文字（全角のかっこ・
                                   句読点、「資料」→「付録」など）の docx を LibreOffice で PDF にしたもの（LibreOffice が
                                   なければ PDF は作り直さない）
tests/fixtures/sample_reader.docx : 読み取りの境界ケースのうち sample_edge に入れていないもの（コンテンツコントロール
                                   〈w:sdt〉や w:customXml に包まれた表の行・セル、テキストボックスの段落と表、段落記号の削除
                                   〈つながる段落・つなげない場所〉、スタイルの隠し文字、段落の中の改行〈セル・本文・題目・
                                   引用文献〉、変更履歴で削除された表の行・セル）
tests/fixtures/sample_float_text.docx : テキストボックスの中で、画像と文字が同じ段落にある図形（キャプションのある図と、
                                   キャプションのない図形）。位置は機械的に決まる
tests/fixtures/sample_structure.docx : 論文の構造（領域の分け方など）の境界ケース（本文中のテキストボックスにある
                                   「英文要旨」スタイルの段落や「注」だけの段落、Word の脚注と文末脚注〈ID の重なり・削除された
                                   参照・記号を自分で付けた文末脚注・脚注の中からの参照・参照のない脚注〉、文字だけのテキストボックス
                                   〈囲み・図に重ねた注記・決められないもの・VML・行内・空のもの〉、英文要旨の後ろの
                                   「資料（授業プリント）」）
tests/fixtures/sample_b3_cells.docx : 表のセルに画像とキャプションが並ぶ図形（AI なしで図に組める形）。位置は機械的に決まる
tests/fixtures/sample_b3_tablefig.docx : 画像のない図キャプションと、その隣のキャプションのない表（表で組んだ図）
tests/fixtures/sample_b3_place.docx : 位置を決められない図表の仮の置き場所（同じ段落に結び付いた 2 つの図形、空の段落に
                                   結び付いた図形、引用文献の後ろの注）。AI 補完が必要（ALL_DOCS には入れない）
tests/fixtures/sample_outside.docx : 本文の外（引用文献・注・英文要旨）の段落に結び付いた図形と囲み、資料の中の囲み、
                                   引用文献の段落の中の画像。AI 補完が必要（ALL_DOCS には入れない）
tests/fixtures/sample_links.docx : 注・図表へのリンクの規則の境界ケース（注番号が「1)」の書き方の論文）。指数・単位の上付き
                                   （cm²・x²・s⁻¹・f(x²)）、番号の形がはっきりした注番号（「1,2)」「1-3)」「註1」、上付きの「1」＋本文の
                                   「)」）、本文の「注」＋上付きの「1」、番号だけの上付きの数字、語の中の「図1」「表1」（地図1・図表1・
                                   発表1回目・付表1 など）とリンクする参照（前掲表1・乃至・並び・「図表1と表1」の後ろの表1）
tests/fixtures/sample_links_bare.docx : sample_links と同じ規則の、注番号が番号だけの上付きの論文（「主張である¹」「（試験, 2024）²」と
                                   「4 m²」、上付きの「1-3」「1, 2」、文の括弧を閉じる直前の上付きの「3」＋本文の「）」。注の一覧の番号も上付き）

make_fixtures の部品（テストの中で docx をその場で作るもの）: cell()（セル）・table()（表）・tr()/table_row()/table_of_rows()
（行を並べた表。table_row は gridBefore・gridAfter・見出し行を書ける）・make_article()（下）など。

make_article() は小さな論文を作る。テストの中で、境界ケースの docx をその場で作るのにも使う。

内容は架空のもので、実在の論文ではない。
"""
from __future__ import annotations

import copy
import io
import re
import sys
import zipfile
import zlib
from pathlib import Path
from xml.sax.saxutils import escape

from lxml import etree
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "fixtures" / "JASME_template_20261009.docx"

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NSDECL = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
          'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
          'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
          'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
          'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture" '
          'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
          'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
          'xmlns:wpg="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup" '
          'xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office"')

# テンプレートのスタイル ID
S = {"title": "af7", "subtitle": "af8", "aff_ja": "af9", "author_ja": "afa", "title_en": "afb",
     "subtitle_en": "afc", "author_en": "afd", "aff_en": "afe", "abs_head": "aff", "abs": "aff0",
     "sec1": "aff1", "sec2": "aff2", "sec3": "aff3", "notes_head": "aff4", "ack_head": "aff5",
     "fn_head": "aff6", "fn_body": "aff7", "ref_head": "aff8", "ref": "aff9", "fig_cap": "affa", "tab_cap": "affb",
     "quote": "affc", "body": "af5", "normal": None}


# ----------------------------------------------------------------------------- 部品
def run(text, b=False, i=False, sup=False, sub=False, u=False):
    rpr = ""
    if b:
        rpr += "<w:b/>"
    if i:
        rpr += "<w:i/>"
    if u:
        rpr += '<w:u w:val="single"/>'
    if sup:
        rpr += '<w:vertAlign w:val="superscript"/>'
    if sub:
        rpr += '<w:vertAlign w:val="subscript"/>'
    rpr = f"<w:rPr>{rpr}</w:rPr>" if rpr else ""
    sp = ' xml:space="preserve"' if text != text.strip() or "  " in text else ""
    return f"<w:r>{rpr}<w:t{sp}>{escape(text)}</w:t></w:r>"


def tab():
    return "<w:r><w:tab/></w:r>"


def para(style, *parts, jc=None):
    ppr = ""
    if style:
        ppr += f'<w:pStyle w:val="{style}"/>'
    if jc:
        ppr += f'<w:jc w:val="{jc}"/>'
    ppr = f"<w:pPr>{ppr}</w:pPr>" if ppr else ""
    body = "".join(p if p.startswith("<") else run(p) for p in parts if p)
    return f"<w:p>{ppr}{body}</w:p>"


def list_item(style, *parts, num_id=6):
    """自動番号の段落（箇条書きの項目）。テンプレートの numbering.xml の numId=6 は「•」の箇条書き、numId=7 は「1.」の番号。"""
    ppr = (f'<w:pStyle w:val="{style}"/>' if style else "") + f'<w:numPr><w:ilvl w:val="0"/><w:numId w:val="{num_id}"/></w:numPr>'
    body = "".join(p if p.startswith("<") else run(p) for p in parts if p)
    return f"<w:p><w:pPr>{ppr}</w:pPr>{body}</w:p>"


def mr(text, sty=None):
    rpr = f'<m:rPr><m:sty m:val="{sty}"/></m:rPr>' if sty else ""
    return f"<m:r>{rpr}<m:t>{escape(text)}</m:t></m:r>"


def msup(base, sup):
    return f"<m:sSup><m:e>{base}</m:e><m:sup>{sup}</m:sup></m:sSup>"


def mfrac(num, den):
    return f"<m:f><m:num>{num}</m:num><m:den>{den}</m:den></m:f>"


def omath(inner):
    return f"<m:oMath>{inner}</m:oMath>"


def omathpara(inner):
    return f"<m:oMathPara><m:oMath>{inner}</m:oMath></m:oMathPara>"


def drawing(rid, cx, cy, pid, name="図", anchor=False, src_rect=None, xfrm="", blip=""):
    """行内の画像。src_rect は a:srcRect の属性（'l="50000"'）、xfrm は a:xfrm の属性（' rot="5400000"'）、blip は a:blip の中身。"""
    sr = f"<a:srcRect {src_rect}/>" if src_rect else ""
    blip_xml = f'<a:blip r:embed="{rid}">{blip}</a:blip>' if blip else f'<a:blip r:embed="{rid}"/>'
    graphic = (f'<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
               f'<pic:pic><pic:nvPicPr><pic:cNvPr id="{pid}" name="{name}"/><pic:cNvPicPr/></pic:nvPicPr>'
               f'<pic:blipFill>{blip_xml}{sr}<a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
               f'<pic:spPr><a:xfrm{xfrm}><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
               f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic>')
    return (f'<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/>'
            f'<wp:docPr id="{pid}" name="{name}"/>{graphic}</wp:inline></w:drawing></w:r>')


def vml_image(rid, width="100pt", height="100pt", attrs="", style=""):
    """VML の画像（w:pict）。attrs は v:imagedata の属性（'cropleft="16384f"'）、style は v:shape の style の後ろに足す文字。"""
    extra = f";{style}" if style else ""
    return (f'<w:r><w:pict><v:shape style="width:{width};height:{height}{extra}">'
            f'<v:imagedata r:id="{rid}" {attrs}/></v:shape></w:pict></w:r>')


def pic_group(rids_exts, pid, extent=None, ch_ext=None, blip_ext=False, grp_xfrm=""):
    """1 つのグループ図形（wpg:wgp）に pic を複数入れた行内の図形。rids_exts は [(rid, cx, cy), ...]。"""
    if extent is None:
        extent = (max(c for _, c, _ in rids_exts), max(c for _, _, c in rids_exts))
    ext_lst = ('<a:extLst><a:ext uri="{28A0092B-C50C-407E-A947-70E740481C1C}">'
               '<a14:useLocalDpi xmlns:a14="http://schemas.microsoft.com/office/drawing/2010/main" val="0"/></a:ext></a:extLst>'
               if blip_ext else "")
    pics = ""
    for k, (rid, cx, cy) in enumerate(rids_exts):
        blip = f'<a:blip r:embed="{rid}">{ext_lst}</a:blip>' if ext_lst else f'<a:blip r:embed="{rid}"/>'
        pics += (f'<pic:pic><pic:nvPicPr><pic:cNvPr id="{pid + k + 1}" name="図"/><pic:cNvPicPr/></pic:nvPicPr>'
                 f'<pic:blipFill>{blip}<a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
                 f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
                 '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>')
    chext = f'<a:chExt cx="{ch_ext[0]}" cy="{ch_ext[1]}"/>' if ch_ext else ""
    grp = (f'<wpg:grpSpPr><a:xfrm{grp_xfrm}><a:off x="0" y="0"/><a:ext cx="{extent[0]}" cy="{extent[1]}"/>{chext}</a:xfrm>'
           '</wpg:grpSpPr>')
    graphic = ('<a:graphic><a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup">'
               f'<wpg:wgp><wpg:cNvGrpSpPr/>{grp}{pics}</wpg:wgp></a:graphicData></a:graphic>')
    return (f'<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{extent[0]}" cy="{extent[1]}"/>'
            f'<wp:docPr id="{pid}" name="図"/>{graphic}</wp:inline></w:drawing></w:r>')


def two_tone(fmt="PNG", size=(200, 100), **save_kw) -> bytes:
    """左半分が赤・右半分が青の画像。"""
    img = Image.new("RGB", size, "red")
    img.paste("blue", (size[0] // 2, 0, size[0], size[1]))
    buf = io.BytesIO()
    img.save(buf, fmt, **save_kw)
    return buf.getvalue()


def anchored(graphic, fallback, pid, cx, cy, h=("column", 0), v=("paragraph", 0), wrap="wrapNone"):
    """浮動配置の図形（wp:anchor）。h, v は (relativeFrom, EMU 単位のずれ)。"""
    return ('<w:r><mc:AlternateContent><mc:Choice Requires="wps"><w:drawing><wp:anchor distT="0" distB="0" distL="0" '
            'distR="0" simplePos="0" relativeHeight="1" behindDoc="0" locked="0" layoutInCell="1" allowOverlap="1">'
            f'<wp:simplePos x="0" y="0"/><wp:positionH relativeFrom="{h[0]}"><wp:posOffset>{h[1]}</wp:posOffset></wp:positionH>'
            f'<wp:positionV relativeFrom="{v[0]}"><wp:posOffset>{v[1]}</wp:posOffset></wp:positionV>'
            f'<wp:extent cx="{cx}" cy="{cy}"/><wp:{wrap}/><wp:docPr id="{pid}" name="図形 {pid}"/>'
            f'{graphic}</wp:anchor></w:drawing></mc:Choice><mc:Fallback>{fallback}</mc:Fallback></mc:AlternateContent></w:r>')


def textbox(inner, pid, cx=2000000, cy=500000, **pos):
    """浮動配置のテキストボックス（Word と同じく、DrawingML と VML の代替の両方に同じ中身を入れる）。"""
    graphic = ('<a:graphic><a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">'
               f'<wps:wsp><wps:txbx><w:txbxContent>{inner}</w:txbxContent></wps:txbx><wps:bodyPr/></wps:wsp>'
               '</a:graphicData></a:graphic>')
    fallback = f'<w:pict><v:shape><v:textbox><w:txbxContent>{inner}</w:txbxContent></v:textbox></v:shape></w:pict>'
    return anchored(graphic, fallback, pid, cx, cy, **pos)


def textbox_inline(inner, pid, cx=3600000, cy=1080000):
    """行内（wp:inline）のテキストボックス（段落の中に文字と同じように並ぶ図形。DrawingML の代替の VML は付けない）。"""
    graphic = ('<a:graphic><a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">'
               f'<wps:wsp><wps:txbx><w:txbxContent>{inner}</w:txbxContent></wps:txbx><wps:bodyPr/></wps:wsp>'
               '</a:graphicData></a:graphic>')
    return (f'<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/>'
            f'<wp:docPr id="{pid}" name="テキスト ボックス {pid}"/>{graphic}</wp:inline></w:drawing></w:r>')


def vml_textbox(inner, width="300pt", height="60pt", absolute=False):
    """VML だけのテキストボックス（DrawingML のない古い形式）。absolute なら position:absolute（位置を指定した浮動配置）。"""
    style = ("position:absolute;margin-left:0;margin-top:0;" if absolute else "") + f"width:{width};height:{height}"
    return (f'<w:r><w:pict><v:shape style="{style}"><v:textbox><w:txbxContent>{inner}</w:txbxContent></v:textbox>'
            '</v:shape></w:pict></w:r>')


def group(rid, pic_cx, pic_cy, inner, pid, cx, cy, **pos):
    """画像とテキストボックス（キャプション）をまとめたグループ図形。"""
    pic = (f'<pic:pic><pic:nvPicPr><pic:cNvPr id="{pid + 1}" name="図"/><pic:cNvPicPr/></pic:nvPicPr>'
           f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
           f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{pic_cx}" cy="{pic_cy}"/></a:xfrm>'
           '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>')
    graphic = ('<a:graphic><a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup">'
               f'<wpg:wgp><wpg:cNvGrpSpPr/><wpg:grpSpPr/>{pic}<wps:wsp><wps:txbx><w:txbxContent>{inner}</w:txbxContent>'
               '</wps:txbx><wps:bodyPr/></wps:wsp></wpg:wgp></a:graphicData></a:graphic>')
    fallback = f'<w:pict><v:group><v:shape><v:textbox><w:txbxContent>{inner}</w:txbxContent></v:textbox></v:shape></v:group></w:pict>'
    return anchored(graphic, fallback, pid, cx, cy, **pos)


# 画像を持たない図形（飾りの判定・画像の位置の数え方の検証用）
WSP_FILL = {"none": "<a:noFill/>",
            "white": '<a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill>',
            "bg1": '<a:solidFill><a:schemeClr val="bg1"/></a:solidFill>',
            "window": '<a:solidFill><a:sysClr val="window" lastClr="FFFFFF"/></a:solidFill>',
            "gray": '<a:solidFill><a:schemeClr val="bg1"><a:lumMod val="95000"/></a:schemeClr></a:solidFill>',
            "red": '<a:solidFill><a:srgbClr val="FF0000"/></a:solidFill>',
            "gradient": "<a:gradFill><a:gsLst/></a:gradFill>",
            "": ""}
WPS_URI = "http://schemas.microsoft.com/office/word/2010/wordprocessingShape"
WPG_URI = "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup"


def wsp(prst="rect", fill="none", text="", x=0):
    """図形 1 つ（wps:wsp）。prst は図形の形、fill は WSP_FILL の鍵、text があればテキストボックス（文字のある図形）にする。"""
    txbx = f'<wps:txbx><w:txbxContent>{para(S["body"], text)}</w:txbxContent></wps:txbx>' if text else ""
    return (f'<wps:wsp><wps:cNvSpPr/><wps:spPr><a:xfrm><a:off x="{x}" y="0"/><a:ext cx="720000" cy="360000"/></a:xfrm>'
            f'<a:prstGeom prst="{prst}"><a:avLst/></a:prstGeom>{WSP_FILL[fill]}</wps:spPr>{txbx}<wps:bodyPr/></wps:wsp>')


def _shape_run(graphic, pid, anchor, h, v):
    if anchor:
        return anchored(graphic, "", pid, 720000, 360000, h=h, v=v)
    return (f'<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="720000" cy="360000"/>'
            f'<wp:docPr id="{pid}" name="図形 {pid}"/>{graphic}</wp:inline></w:drawing></w:r>')


def shape(prst="rect", fill="none", pid=801, anchor=False, h=("column", 0), v=("paragraph", 0)):
    """画像も文字も持たない単独の図形（枠・白い四角・線・矢印など）。anchor なら浮動配置（h, v は位置のずれ）。"""
    graphic = f'<a:graphic><a:graphicData uri="{WPS_URI}">{wsp(prst, fill)}</a:graphicData></a:graphic>'
    return _shape_run(graphic, pid, anchor, h, v)


def shape_group(shapes, pid=811, anchor=False, h=("column", 0), v=("paragraph", 0)):
    """図形のグループ（wpg:wgp）。shapes は [(prst, fill, text), ...]。画像は持たない。"""
    inner = "".join(wsp(p, f, t, x=k * 800000) for k, (p, f, t) in enumerate(shapes))
    graphic = (f'<a:graphic><a:graphicData uri="{WPG_URI}"><wpg:wgp><wpg:cNvGrpSpPr/><wpg:grpSpPr/>{inner}</wpg:wgp>'
               '</a:graphicData></a:graphic>')
    return _shape_run(graphic, pid, anchor, h, v)


def chart_drawing(pid=821, rid="rId999"):
    """グラフ（c:chart）の図形。"""
    graphic = ('<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart">'
               f'<c:chart xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" r:id="{rid}"/>'
               '</a:graphicData></a:graphic>')
    return _shape_run(graphic, pid, False, ("column", 0), ("paragraph", 0))


def cell(content, span=1, vmerge=None, width=2000):
    tcpr = f'<w:tcW w:w="{width}" w:type="dxa"/>'
    if span > 1:
        tcpr += f'<w:gridSpan w:val="{span}"/>'
    if vmerge == "restart":
        tcpr += '<w:vMerge w:val="restart"/>'
    elif vmerge == "continue":
        tcpr += "<w:vMerge/>"
    paras = content if isinstance(content, list) else [content]
    inner = "".join(p if p.startswith("<w:p") else para(S["body"], p) for p in paras)
    return f"<w:tc><w:tcPr>{tcpr}</w:tcPr>{inner}</w:tc>"


def table(rows, style="a5", header_rows=0):
    out = f'<w:tbl><w:tblPr><w:tblStyle w:val="{style}"/><w:tblW w:w="0" w:type="auto"/></w:tblPr><w:tblGrid>'
    ncol = max(sum(int(re.search(r'gridSpan w:val="(\d+)"', c).group(1)) if "gridSpan" in c else 1 for c in r)
               for r in rows)
    out += '<w:gridCol w:w="2000"/>' * ncol + "</w:tblGrid>"
    for k, r in enumerate(rows):
        trpr = "<w:trPr><w:tblHeader/></w:trPr>" if k < header_rows else ""
        out += f"<w:tr>{trpr}{''.join(r)}</w:tr>"
    return out + "</w:tbl>"


def png_bytes(text, size=(480, 300), font_size=28, bg="white"):
    img = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", font_size)
    except OSError:
        font = ImageFont.load_default()
    d.rectangle([4, 4, size[0] - 5, size[1] - 5], outline="black", width=2)
    d.text((20, size[1] // 2 - font_size), text, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


# ----------------------------------------------------------------------------- 組み立て
class Builder:
    def __init__(self):
        self.zin = zipfile.ZipFile(TEMPLATE)
        self.doc = etree.fromstring(self.zin.read("word/document.xml"))
        self.body = self.doc.find(f"{{{W}}}body")
        self.kids = list(self.body)
        self.media = {}
        self.rels_extra = []
        self.footnotes_extra = []
        self.endnotes_extra = []        # Word の文末脚注（endnote() の XML）
        self.styles_extra = []          # word/styles.xml に足すスタイルの定義（w:style の XML。READER_STYLES など）
        # 箇条書き（numbering.xml の numId=6〈abstractNum 7〉の 1 段目）の記号を変えるとき、その記号（None なら「•」のまま）
        self.bullet = None
        self._rid = 900

    def add_image(self, name, data):
        self._rid += 1
        rid = f"rId{self._rid}"
        self.media[f"word/media/{name}"] = data
        self.rels_extra.append(f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                               f'relationships/image" Target="media/{name}"/>')
        return rid

    def add_hyperlink(self, url):
        self._rid += 1
        rid = f"rId{self._rid}"
        self.rels_extra.append(f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                               f'relationships/hyperlink" Target="{escape(url)}" TargetMode="External"/>')
        return rid

    def frag(self, xml):
        wrapper = etree.fromstring(f"<w:body {NSDECL}>{xml}</w:body>")
        return list(wrapper)

    @staticmethod
    def set_text(p, text):
        ts = list(p.iter(f"{{{W}}}t"))
        if not ts:
            return
        ts[0].text = text
        for t in ts[1:]:
            t.getparent().remove(t)

    def save(self, out, body_xml_parts):
        # body を作り直す
        for ch in list(self.body):
            self.body.remove(ch)
        for part in body_xml_parts:
            if isinstance(part, str):
                for el in self.frag(part):
                    self.body.append(el)
            else:
                self.body.append(part)
        data = etree.tostring(self.doc, xml_declaration=True, encoding="UTF-8", standalone=True)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in self.zin.infolist():
                if item.filename == "word/document.xml":
                    zout.writestr(item, data)
                elif item.filename == "word/_rels/document.xml.rels":
                    rels = self.zin.read(item.filename).decode("utf-8")
                    rels = rels.replace("</Relationships>", "".join(self.rels_extra) + "</Relationships>")
                    zout.writestr(item, rels)
                elif item.filename == "word/footnotes.xml" and self.footnotes_extra:
                    fx = self.zin.read(item.filename).decode("utf-8")
                    fx = fx.replace("</w:footnotes>", "".join(self.footnotes_extra) + "</w:footnotes>")
                    zout.writestr(item, fx)
                elif item.filename == "word/endnotes.xml" and self.endnotes_extra:
                    ex = self.zin.read(item.filename).decode("utf-8")
                    ex = ex.replace("</w:endnotes>", "".join(self.endnotes_extra) + "</w:endnotes>")
                    zout.writestr(item, ex)
                elif item.filename == "word/styles.xml" and self.styles_extra:
                    sx = self.zin.read(item.filename).decode("utf-8")
                    sx = sx.replace("</w:styles>", "".join(self.styles_extra) + "</w:styles>")
                    zout.writestr(item, sx)
                elif item.filename == "word/numbering.xml" and self.bullet:
                    nx = self.zin.read(item.filename).decode("utf-8")
                    head = '<w:abstractNum w:abstractNumId="7"'
                    a = nx.index(head)
                    b = nx.index('<w:lvl w:ilvl="1">', a)
                    nx = nx[:a] + nx[a:b].replace('<w:lvlText w:val="•"/>', f'<w:lvlText w:val="{self.bullet}"/>') + nx[b:]
                    zout.writestr(item, nx)
                elif item.filename == "[Content_Types].xml":
                    ct = self.zin.read(item.filename).decode("utf-8")
                    if 'Extension="png"' not in ct:
                        ct = ct.replace("<Default ", '<Default Extension="png" ContentType="image/png"/><Default ', 1)
                    zout.writestr(item, ct)
                else:
                    zout.writestr(item, self.zin.read(item.filename))
            for name, blob in self.media.items():
                zout.writestr(name, blob)


def front_ja(b: Builder, title, subtitle, authors):
    """テンプレートの冒頭（誌名・装飾行・題目・著者表・区切り）を流用して差し替える。"""
    k = b.kids
    out = [copy.deepcopy(k[0]), copy.deepcopy(k[1])]
    t = copy.deepcopy(k[2])
    b.set_text(t, title)
    out.append(t)
    st = copy.deepcopy(k[3])
    b.set_text(st, subtitle)
    out.append(st)
    out.append(copy.deepcopy(k[4]))
    tbl = copy.deepcopy(k[5])
    rows = tbl.findall(f"{{{W}}}tr")
    proto = rows[0]
    for r in rows:
        tbl.remove(r)
    for aff, name in authors:
        r = copy.deepcopy(proto)
        cells = r.findall(f"{{{W}}}tc")
        b.set_text(cells[0].find(f".//{{{W}}}p"), aff)
        b.set_text(cells[1].find(f".//{{{W}}}p"), name)
        tbl.append(r)
    out.append(tbl)
    out.extend(copy.deepcopy(x) for x in k[6:9])   # 装飾行・空行・セクション区切り
    return out


def front_en(b: Builder, title, subtitle, authors, abstract_paras):
    k = b.kids
    # テンプレート末尾: [sect区切り段落] [空] [題目（英）] [副題（英）] [著者表（英）] [Abstract] [要旨]...
    idx_sect2 = [i for i, el in enumerate(k) if el.find(f".//{{{W}}}sectPr") is not None][1]
    out = [copy.deepcopy(k[idx_sect2]), copy.deepcopy(k[idx_sect2 + 1])]
    t = copy.deepcopy(k[idx_sect2 + 2])
    b.set_text(t, title)
    out.append(t)
    st = copy.deepcopy(k[idx_sect2 + 3])
    b.set_text(st, subtitle)
    out.append(st)
    tbl = copy.deepcopy(k[idx_sect2 + 4])
    rows = tbl.findall(f"{{{W}}}tr")
    proto_name, proto_aff = rows[0], rows[1]
    for r in rows:
        tbl.remove(r)
    for name, aff in authors:
        rn = copy.deepcopy(proto_name)
        b.set_text(rn.find(f".//{{{W}}}p"), name)
        ra = copy.deepcopy(proto_aff)
        b.set_text(ra.find(f".//{{{W}}}p"), aff)
        tbl.append(rn)
        tbl.append(ra)
    out.append(tbl)
    out.append(copy.deepcopy(k[idx_sect2 + 5]))   # Abstract 見出し
    for text in abstract_paras:
        out.append(para(S["abs"], text))
    return out


def tail(b: Builder, appendix=None):
    k = b.kids
    out = []
    if appendix:
        out.extend(appendix)
    out.append(copy.deepcopy(k[-1]))   # body 末尾の sectPr
    return out


# ----------------------------------------------------------------------------- sample_full
def make_full(path):
    b = Builder()
    fig1 = b.add_image("fig1.png", png_bytes("Triangle ABC = DEF"))
    fig2 = b.add_image("fig2.png", png_bytes("Student work", size=(480, 260)))
    eqimg = b.add_image("eq1.png", png_bytes("a^2 + b^2 = c^2", size=(360, 70), font_size=30))
    mext = b.add_hyperlink("https://www.mext.go.jp/")

    body = []
    body += front_ja(b, "数学的探究における証明の構成過程に関する研究",
                     "―中学校第２学年「三角形の合同」を事例として―",
                     [("広島大学大学院人間社会科学研究科", "数学\u3000太郎"),
                      ("東京学芸大学", "教育\u3000花子"),
                      ("広島大学大学院人間社会科学研究科", "研究次郎")])

    body.append(para(S["sec1"], "１．はじめに"))
    body.append(para(S["body"],
                     "本研究では，数学的探究（中原, 1995；岩崎・山口, 2007）における証明の構成過程を検討する。",
                     "Lakatos（1976）は証明と反駁の論理を示し，Polya（1945, 1954）は発見的方法を論じた。",
                     "また，宮川ほか（2016）は世界探究パラダイムに基づく論証活動を分析している",
                     run("1)", sup=True), "。"))
    body.append(para(S["body"],
                     "証明の機能については多くの議論がある（Hanna, 2000, p. 5; de Villiers, 1990）。",
                     "学習指導要領（文部科学省, 2019a）では，",
                     run("論理的に考察し表現する力", b=True),
                     "の育成が求められている。詳しくは文部科学省のWebサイト（",
                     f'<w:hyperlink r:id="{mext}">{run("https://www.mext.go.jp/", u=True)}</w:hyperlink>',
                     "）を参照されたい。"))
    body.append(para(S["body"],
                     "国宗は，その後の論考（2001）において証明の意義を整理した。",
                     "なお，この点についてはClaudeの2025年の報告も参考になる。",
                     "濱中（2016）も同様の指摘をしているが，Lakatos（1977）の議論とは立場が異なる。"))

    body.append(para(S["sec2"], "(1) 証明の構成と三角形の合同"))
    body.append(para(S["body"],
                     "三平方の定理",
                     omath(msup(mr("x"), mr("2")) + mr("+") + msup(mr("y"), mr("2")) + mr("=") + msup(mr("r"), mr("2"))),
                     "を例に，図1に示すような図形を考える。三角形の面積は次の式で表される。"))
    body.append(para(S["body"],
                     omathpara(mr("S=") + mfrac(mr("1"), mr("2")) + mr("ah")), tab(), "(1)", jc="center"))
    body.append(para(S["body"],
                     "式(1)より，底辺",
                     omath(mr("a")),
                     "と高さ",
                     omath(mr("h")),
                     "が等しければ面積も等しい。また，",
                     omath("<m:rad><m:radPr><m:degHide m:val=\"1\"/></m:radPr><m:deg/><m:e>" + mr("2") + "</m:e></m:rad>"
                           + mr("≒1.41")),
                     "や",
                     omath("<m:rad><m:deg>" + mr("3") + "</m:deg><m:e>" + mr("x") + "</m:e></m:rad>"),
                     "，",
                     omath("<m:nary><m:naryPr><m:chr m:val=\"∑\"/></m:naryPr><m:sub>" + mr("k=1") + "</m:sub><m:sup>"
                           + mr("n") + "</m:sup><m:e>" + mr("k") + "</m:e></m:nary>"
                           + mr("=") + "<m:d><m:e>" + mr("n+1") + "</m:e></m:d>" + mr("n/2")),
                     "も用いた。化学式H",
                     run("2", sub=True),
                     "Oのような下付き文字も含む。"))
    body.append(para(S["body"], drawing(fig1, 2880000, 1800000, 101), jc="center"))
    body.append(para(S["fig_cap"], "図1\u3000三角形ABCと三角形DEFの合同"))
    body.append(para(S["sec3"], "① 生徒の記述"))
    body.append(para(S["body"],
                     "生徒の記述を図2に示す（図1，2を参照）。授業の流れは表1のとおりである。"))
    body.append(para(S["body"], drawing(fig2, 2880000, 1560000, 102), jc="center"))
    body.append(para(S["fig_cap"], "図2\u3000生徒Aの記述"))
    body.append(para(S["tab_cap"], "表1\u3000授業の流れ"))
    body.append(table([
        [cell(run("段階", b=True)), cell(run("時間", b=True)), cell(run("主な活動", b=True))],
        [cell("導入", vmerge="restart"), cell("10分"), cell("課題の把握")],
        [cell("", vmerge="continue"), cell("5分"), cell(["予想の共有", "（全体）"])],
        [cell("展開"), cell("30分", span=2)],
    ], header_rows=1))
    body.append(para(S["body"], ""))
    body.append(para(S["quote"], "証明とは，ある命題が真であることを，公理と既に証明された命題から導くことである。"))
    body.append(para(S["quote"], "（中原, 1995, p. 12）"))
    body.append(para(S["body"], ""))

    # --- スタイル違反（AI 補完の対象）
    body.append(para(None, run("２．考察", b=True)))
    body.append(para(S["body"], "表2に分析の観点を示す。下の式は画像で挿入されている。"))
    body.append(para(S["body"], drawing(eqimg, 1800000, 350000, 103, name="数式"), jc="center"))
    body.append(para(S["body"], "表2\u3000分析の観点"))
    body.append(table([
        [cell("観点"), cell("内容")],
        [cell("論証"), cell("根拠を示して説明する")],
    ]))
    body.append(para(S["body"], ""))

    body.append(para(S["notes_head"], "付記"))
    body.append(para(S["body"], "本研究は，第50回秋期研究発表会での発表内容を加筆・修正したものである。"))
    body.append(para(S["body"], ""))
    body.append(para(S["ack_head"], "謝辞"))
    body.append(para(S["body"], "調査にご協力いただいた先生方に感謝申し上げます。"))
    body.append(para(S["body"], ""))
    body.append(para(S["fn_head"], "注"))
    body.append(para(S["body"], "1) SRP は Study and Research Path の略である。"))
    body.append(para(S["body"], "2) 詳細は https://example.org/srp-notes を参照。"))
    body.append(para(S["body"], ""))
    body.append(para(S["ref_head"], "引用および参考文献"))
    refs = [
        "岩崎秀樹・山口武志（2007）．「数学的探究の理論」．『数学教育学研究』，第13巻，pp.1-10．",
        "国宗進（2001）．「証明の意義」．『数学教育論究』，第77巻，pp.3-20．",
        "中原忠男（1995）．『算数・数学教育における構成的アプローチの研究』．聖文社．",
        "宮川健・濵中裕明・大滝孝治（2016）．「世界探究パラダイムに基づくSRPにおける論証活動（1）」．"
        "全国数学教育学会誌『数学教育学研究』，第22巻，第２号，pp.25-36．",
        "文部科学省（2019a）．『中学校学習指導要領解説 数学編』．日本文教出版．",
        "文部科学省（2019b）．『高等学校学習指導要領解説 数学編』．学校図書．",
        "Claude, A. (2025). An unusual reference format example. Journal of Testing, 1, 1-2. doi:10.1234/jt.2025.001",
        "de Villiers, M. (1990). The role and function of proof in mathematics. Pythagoras, 24, 17-24.",
        "Hanna, G. (2000). Proof, explanation and exploration: An overview. Educational Studies in Mathematics, "
        "44(1), 5-23. https://doi.org/10.1023/A:1012737223465",
        "Lakatos, I. (1976). Proofs and refutations. Cambridge University Press. ",
        "Polya, G. (1945). How to solve it. Princeton University Press.",
        "Polya, G. (1954). Mathematics and plausible reasoning. Princeton University Press.",
    ]
    # Word のハイパーリンクが付いた DOI（他の文献と同じく https://doi.org/ の文字 + pub-id になること）
    lakatos = b.add_hyperlink("https://doi.org/10.1017/CBO9781139171472")
    for r in refs:
        if r.startswith("Lakatos"):
            body.append(para(S["ref"], r, f'<w:hyperlink r:id="{lakatos}">'
                                          f'{run("https://doi.org/10.1017/CBO9781139171472", u=True)}</w:hyperlink>'))
        else:
            body.append(para(S["ref"], r))

    body += front_en(b, "A Study on the Process of Constructing Proofs in Mathematical Inquiry",
                     "Focusing on Congruence of Triangles in the Second Grade of Lower Secondary School",
                     [("Taro SUGAKU", "Graduate School of Humanities and Social Sciences, Hiroshima University"),
                      ("Hanako KYOIKU", "Tokyo Gakugei University"),
                      ("Jiro KENKYU", "Graduate School of Humanities and Social Sciences, Hiroshima University")],
                     ["This study examines the process of constructing proofs in mathematical inquiry. "
                      "Figure 1 shows the congruent triangles discussed in the lesson.",
                      "The results suggest that students' proofs develop through refutations (Lakatos, 1976)."])
    body += tail(b, appendix=[para(S["abs"], "資料\u3000授業で用いたワークシート"),
                              para(S["abs"], "ワークシートの設問は次の通りである。")])
    b.save(path, body)


# ----------------------------------------------------------------------------- sample_edge
def make_edge(path):
    b = Builder()
    link = b.add_hyperlink("https://example.com/a?b=1&c=2")
    tbimg = b.add_image("tbfig.png", png_bytes("Figure in a text box", size=(400, 240)))
    body = []
    body += front_ja(b, "境界ケースの検証用文書", "―読み取りの網羅性を確かめる―",
                     [("架空大学", "試験\u3000一郎")])
    body.append(para(S["sec1"], "１．読み取りの境界ケース"))
    # Word の脚注
    b.footnotes_extra.append(
        '<w:footnote w:id="5"><w:p><w:pPr><w:pStyle w:val="a8"/></w:pPr><w:r><w:rPr><w:rStyle w:val="a9"/></w:rPr>'
        '<w:footnoteRef/></w:r><w:r><w:t xml:space="preserve"> Word の脚注機能で付けた注です。</w:t></w:r></w:p></w:footnote>')
    body.append(para(S["body"], "Word の脚注", '<w:r><w:rPr><w:rStyle w:val="a9"/></w:rPr><w:footnoteReference w:id="5"/></w:r>',
                     "が付いた文。"))
    # 隠し文字・変更履歴
    body.append(para(S["body"], "表示される文字",
                     '<w:r><w:rPr><w:vanish/></w:rPr><w:t>（隠し文字）</w:t></w:r>',
                     '<w:del w:id="1" w:author="x"><w:r><w:delText>削除済み</w:delText></w:r></w:del>',
                     '<w:ins w:id="2" w:author="x"><w:r><w:t>挿入済み</w:t></w:r></w:ins>', "。"))
    # フィールドのハイパーリンクと記号フォント
    body.append(para(S["body"],
                     '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
                     '<w:r><w:instrText xml:space="preserve"> HYPERLINK "https://example.net/field" </w:instrText></w:r>'
                     '<w:r><w:fldChar w:fldCharType="separate"/></w:r>',
                     run("フィールドのリンク"),
                     '<w:r><w:fldChar w:fldCharType="end"/></w:r>',
                     "と記号",
                     '<w:r><w:sym w:font="Symbol" w:char="F061"/></w:r>',
                     "と",
                     f'<w:hyperlink r:id="{link}">{run("通常のリンク")}</w:hyperlink>',
                     "。改行", "<w:r><w:br/></w:r>", "の後。"))
    # テキストボックスに入った図キャプション
    body.append(para(S["body"], "図1はテキストボックスの例。",
                     textbox(para(S["fig_cap"], "図1　テキストボックス内のキャプション"), 201)))
    # テキストボックスに入った表（表で組んだ問題）と、本文スタイルのキャプション（スタイル違反）
    body.append(para(S["body"], "図2は表で組んだ問題の例。", textbox(
        table([[cell("問1　架空の問題文である。")], [cell("問2　もう一つの問題文である。")]])
        + para(S["body"], "図2　テキストボックス内の表で組んだ問題"), 202, cy=1200000)))
    # テキストボックスに入った画像と、本文スタイルのキャプション（画像を外側の図形の画像として二重に読まない）
    body.append(para(S["body"], "図3はテキストボックス内の画像の例。", textbox(
        para(S["body"], drawing(tbimg, 1800000, 1100000, 204, name="図"))
        + para(S["body"], "図3　テキストボックス内の画像"), 203, cy=1500000)))
    # テキストボックスに入った表キャプション（本文スタイル）と表
    body.append(para(S["body"], "表1はテキストボックス内の表の例。", textbox(
        para(S["body"], "表1　テキストボックス内の表")
        + table([[cell("観点"), cell("内容")], [cell("論証"), cell("根拠を示す")]]), 205, cy=1000000)))
    # 自動番号付きの段落（numbering.xml の numId=1 が無ければ無視される）
    body.append(para(S["body"], "全角スペースで始まる段落と\tタブ。"))
    body.append(para(S["body"], "\u3000全角スペースで始まる段落。"))
    body.append(para(S["ref_head"], "引用および参考文献"))
    body.append(para(S["ref"], "試験一郎（2020）．「境界ケース」．『架空誌』，第1巻，pp.1-2．"))
    body += front_en(b, "Edge Cases", "Checking Coverage", [("Ichiro SHIKEN", "Fictional University")],
                     ["Edge case abstract."])
    body += tail(b)
    b.save(path, body)


# ----------------------------------------------------------------------------- sample_float
def make_float(path):
    """2 段組をまたぐ図などを、テキストボックス・グループ図形で配置した原稿（位置の多くは機械的に決められない）。"""
    b = Builder()
    img_a = b.add_image("float_a.png", png_bytes("Area model", size=(300, 240)))
    img_b = b.add_image("float_b.png", png_bytes("Tree diagram", size=(300, 240)))
    img_g = b.add_image("float_g.png", png_bytes("Textbook page", size=(480, 300)))
    img_m = b.add_image("float_m.png", png_bytes("Fixed figure", size=(400, 240)))
    cm = 360000
    body = []
    body += front_ja(b, "浮動配置の図表の検証用文書", "―テキストボックスとグループ図形―", [("架空大学", "試験\u3000花子")])
    body.append(para(S["sec1"], "１．テキストボックスの図表"))
    body.append(para(S["body"], "図1は表で組んだ問題である。この段落は図の前に置かれる本文である。"))
    # s1: 表で組んだ問題と、本文スタイルのキャプション。アンカー段落から 2 cm 下（2 段にまたがる）
    body.append(para(S["body"], "この段落に図1のテキストボックスが結び付いている。図の上端はこの段落の上端から離れている。", textbox(
        table([[cell("問1\u3000架空の問題文である。")], [cell("問2\u3000もう一つの問題文である。")]])
        + para(S["body"], "図1\u3000表で組んだ問題"), 301, cx=18 * cm, cy=5 * cm, v=("paragraph", 2 * cm),
        wrap="wrapTopAndBottom")))
    body.append(para(S["body"], "図3と図4は，1つのテキストボックスの中の表に並べた図である。"))
    # s2: 表の中に画像 2 つとキャプション 2 つ（図3・図4）
    body.append(para(S["body"], "この段落には図3と図4のテキストボックスが結び付いている。", textbox(
        table([[cell(para(S["body"], drawing(img_a, 1800000, 1440000, 311))),
                cell(para(S["body"], drawing(img_b, 1800000, 1440000, 312)))],
               [cell(para(S["fig_cap"], "図3\u3000面積図")), cell(para(S["fig_cap"], "図4\u3000樹形図"))]]),
        302, cx=18 * cm, cy=6 * cm, v=("paragraph", 3 * cm), wrap="wrapTopAndBottom")))
    # s3: 画像とキャプションのテキストボックスをまとめたグループ図形。縦はページ基準
    body.append(para(S["body"], "図2は教科書の見開きページであり，グループ図形で配置されている。", group(
        img_g, 6 * cm, 3 * cm, para(S["fig_cap"], "図2\u3000グループ図形の図") + para(S["fig_cap"], "（出典：架空の教科書）"),
        320, cx=18 * cm, cy=5 * cm, v=("page", 10 * cm), wrap="wrapTopAndBottom")))
    body.append(para(S["body"], "以上のように，図の位置は docx だけでは決められない。"))
    # s4: 図の左上がアンカー段落の左上にある（機械的に位置を決められる）
    body.append(para(S["body"], "図5は位置が機械的に決まる図である。", textbox(
        para(S["body"], drawing(img_m, 1800000, 1080000, 331)) + para(S["body"], "図5\u3000位置が決まる図"), 330,
        cx=8 * cm, cy=4 * cm, wrap="wrapTopAndBottom")))
    body.append(para(S["sec1"], "２．おわりに"))
    body.append(para(S["body"], "図1から図5を本文の適切な位置に置く。"))
    body.append(para(S["body"], "位置が決まる図（前掲）は，ここでは扱わない。"))   # 番号のない参照（AI がリンクする例）
    body.append(para(S["ref_head"], "引用および参考文献"))
    body.append(para(S["ref"], "試験花子（2021）．「浮動配置」．『架空誌』，第2巻，pp.3-4．"))
    body += front_en(b, "Floating Figures", "Text Boxes and Groups", [("Hanako SHIKEN", "Fictional University")],
                     ["Floating figure abstract."])
    body += tail(b)
    b.save(path, body)


# ----------------------------------------------------------------------------- sample_notes
def make_notes(path):
    """テンプレートの規定（本文に上付きの「1)」、注の節は引用文献の前）と違う書き方の注。"""
    b = Builder()
    body = []
    body += front_ja(b, "注の書き方の検証用文書", "―規定と違う注の番号―", [("架空大学", "試験\u3000三郎")])
    body.append(para(S["sec1"], "１．はじめに"))
    body.append(para(S["body"], "本文の大きさで書いた注番号（注1）と，角括弧の注番号［注2］がある文。"))
    body.append(para(S["body"], "箇条の番号 (1) と (2) は注へのリンクにしない。2 段落からなる注（注3）もある。"))
    body.append(para(S["body"], "番号の書き方が想定外の注※4は，機械的には区切れない。"))
    # 注の節を引用文献の後ろに置く
    body.append(para(S["ref_head"], "引用および参考文献"))
    body.append(para(S["ref"], "試験三郎（2022）．「注の書き方」．『架空誌』，第3巻，pp.5-6．"))
    body.append(para(S["fn_head"], "注"))
    body.append(para(S["body"], "（注1）本文の大きさで書かれた注番号の注である。"))
    body.append(para(S["body"], "［注2］角括弧で書かれた注番号の注である。"))
    body.append(para(S["body"], "（注3）2 段落からなる注の 1 段落目である。"))
    body.append(para(S["body"], "これは注3の 2 段落目である。"))
    body.append(para(S["body"], "※4 番号の書き方が想定外の注である。"))
    body += front_en(b, "Notes in Various Forms", "Checking Note Numbers", [("Saburo SHIKEN", "Fictional University")],
                     ["Note abstract."])
    body += tail(b)
    b.save(path, body)


# ----------------------------------------------------------------------------- sample_pdfcheck
def make_pdfcheck(path, published=False, split=False, hidden=False):
    """出版版 PDF との照合の検証用。published=True なら、出版社が組版で直した想定の文字にする（PDF を作るため）。

    split=True なら、本文の段落「詳しくは資料の…。授業は2回行った。」を、段落記号を変更履歴で削除した 2 つの w:p に分ける
    （Word で承諾すると 1 段落。PDF は今の sample_pdfcheck.pdf のまま使う。修正計画の D5 のルート2。リポジトリには入れず、
    テストの中で作る）。
    hidden=True なら、ルート2 で直す本文の段落（「本研究は…」「詳しくは…」。split なら「授業は…」も）の途中、直す文字のすぐ前に、
    文字スタイル（READER_STYLES の gHid）で隠した文字「〔隠した注記〕」を入れる（Word では表示されないので、docx の文字は変わらない。
    PDF は今の sample_pdfcheck.pdf のまま使う。修正計画の G のルート2。テストの中で作る）。
    """
    def t(docx_text, pub_text=None):
        return (pub_text if pub_text is not None else docx_text) if published else docx_text

    def h(text, at):
        """段落の文字 text のラン。hidden なら、文字 at の前で分け、間に隠した文字のランを入れる。"""
        if not hid:
            return (text,)
        k = text.index(at)
        return (text[:k], hid, text[k:])

    b = Builder()
    hid = run_styled("〔隠した注記〕", rstyle="gHid") if hidden and not published else ""
    if hid:
        b.styles_extra.append(READER_STYLES)
    link = b.add_hyperlink("https://example.com/a")
    body = []
    body += front_ja(b, "出版版 PDF との照合の検証用文書", "―全角と半角の違い―", [("架空大学", "試験\u3000四郎")])
    body.append(para(S["sec1"], "１．はじめに"))
    body.append(para(S["body"], *h(t("本研究は架空理論 (Fictional Theory, 以下, FT) に基づく (試験, 2020; 見本, 2021)。",
                                     "本研究は架空理論（Fictional Theory, 以下，FT）に基づく（試験，2020；見本，2021）。"), "(")))
    if split and not published:
        body.append(para_mark_deleted(S["body"], *h("詳しくは資料の学習指導案を参照されたい。", "資料")))
        body.append(para(S["body"], *h("授業は2回行った。", "2")))
    else:
        body.append(para(S["body"], *h(t("詳しくは資料の学習指導案を参照されたい。授業は2回行った。",
                                         "詳しくは付録の学習指導案を参照されたい。授業は２回行った。"), "資料")))
    body.append(para(S["sec2"], t("(1) 方法の概要", "（1）方法の概要")))
    body.append(para(S["body"], "この段落は出版版と同じで，架空の資料を ",
                     f'<w:hyperlink r:id="{link}">{run("https://example.com/a")}</w:hyperlink>', " で公開している。"))
    body.append(para(S["ref_head"], "引用および参考文献"))
    body.append(para(S["ref"], t("試験四郎 (2020). 「架空の研究」. 『架空誌』, 第1巻, pp.1-10.",
                                 "試験四郎（2020）．「架空の研究」．『架空誌』，第1巻，pp.1-10．")))
    body.append(para(S["ref"], t("見本花子 (2021). 「見本の研究」. 『見本誌』, 第2巻, pp.11-20.",
                                 "見本花子（2021）．「見本の研究」．『見本誌』，第2巻，pp.11-20．")))
    body += front_en(b, "Checking against the published PDF", "Width of characters",
                     [("Shiro SHIKEN", "Fictional University")], ["This abstract is the same in the published version."])
    body += tail(b)
    b.save(path, body)


def make_pdfcheck_pdf(pdf_path):
    """出版社が直した想定の docx を LibreOffice で PDF にする。LibreOffice がなければ何もしない（False）。"""
    import shutil
    import subprocess
    import tempfile
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return False
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "published.docx"
        make_pdfcheck(src, published=True)
        subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", td, str(src)],
                       check=True, capture_output=True, timeout=180)
        shutil.copyfile(Path(td) / "published.pdf", pdf_path)
    return True


# ----------------------------------------------------------------------------- sample_reader
def sdt(inner):
    """コンテンツコントロール（w:sdt）で包む。"""
    return f"<w:sdt><w:sdtPr/><w:sdtContent>{inner}</w:sdtContent></w:sdt>"


def custom_xml(inner, element="item"):
    """カスタム XML（w:customXml）で包む。"""
    return f'<w:customXml w:element="{element}">{inner}</w:customXml>'


def tr(*cells):
    """表の行。cells は cell() の XML か文字列（文字列は本文の段落 1 つのセルにする）。"""
    return "<w:tr>" + "".join(c if c.startswith("<") else cell(c) for c in cells) + "</w:tr>"


def table_row(cells, header=False, grid_before=0, grid_after=0):
    """表の行（table_of_rows と組み合わせる）。cells は cell() の XML か文字列。trPr に gridBefore・gridAfter
    （と幅の wBefore・wAfter）・tblHeader を書く（OOXML の順: gridBefore, gridAfter, wBefore, wAfter, …, tblHeader）。"""
    trpr = ""
    if grid_before:
        trpr += f'<w:gridBefore w:val="{grid_before}"/>'
    if grid_after:
        trpr += f'<w:gridAfter w:val="{grid_after}"/>'
    if grid_before:
        trpr += f'<w:wBefore w:w="{2000 * grid_before}" w:type="dxa"/>'
    if grid_after:
        trpr += f'<w:wAfter w:w="{2000 * grid_after}" w:type="dxa"/>'
    if header:
        trpr += "<w:tblHeader/>"
    pr = f"<w:trPr>{trpr}</w:trPr>" if trpr else ""
    body = "".join(c if c.startswith("<") else cell(c) for c in cells)
    return f"<w:tr>{pr}{body}</w:tr>"


def table_of_rows(rows, ncol, style="a5"):
    """行の XML（w:sdt などで包んだ行を含む）を、そのまま並べた表。"""
    return (f'<w:tbl><w:tblPr><w:tblStyle w:val="{style}"/><w:tblW w:w="0" w:type="auto"/></w:tblPr><w:tblGrid>'
            + '<w:gridCol w:w="2000"/>' * ncol + "</w:tblGrid>" + "".join(rows) + "</w:tbl>")


def reader_wrapped_rows(b: Builder):
    """表の行・セルが、コンテンツコントロールや w:customXml に包まれている。包まれた行・セルは前後の行・セルの間にある。"""
    return [
        para(S["body"], "試験（2023）にならい，行やセルがコンテンツコントロールなどに包まれた表を表1，表2，表3，表4に示す。"),
        para(S["tab_cap"], "表1\u3000コンテンツコントロールに包んだ行"),
        table_of_rows([tr("区分", "内容"), tr("前", "SDTの行の前"), sdt(tr("包んだ行", "SDTで包んだ行")),
                       tr("後", "SDTの行の後")], 2),
        para(S["tab_cap"], "表2\u3000カスタムXMLに包んだ行"),
        table_of_rows([tr("区分", "内容"), tr("前", "XMLの行の前"), custom_xml(tr("包んだ行", "XMLで包んだ行"), "row"),
                       tr("後", "XMLの行の後")], 2),
        para(S["tab_cap"], "表3\u3000カスタムXMLとコンテンツコントロールに包んだセル"),
        table_of_rows([tr("左", "中1", "中2", "右"),
                       tr("セルの左", custom_xml(cell("XMLで包んだセル"), "cell"), sdt(cell("SDTで包んだセル")),
                          "セルの右")], 4),
        # Word の「繰り返しセクション」と同じく、外側のコンテンツコントロールの中に、行ごとのコンテンツコントロールがある
        para(S["tab_cap"], "表4\u3000入れ子のコンテンツコントロールに包んだ行"),
        table_of_rows([tr("区分", "内容"),
                       sdt(sdt(tr("入れ子1", "入れ子のSDTの1行目")) + sdt(tr("入れ子2", "入れ子のSDTの2行目"))),
                       sdt(custom_xml(tr("入れ子3", "XMLを包んだSDTの行"), "row")),
                       tr("後", "入れ子の行の後")], 2),
        para(S["body"], "以上の表では，包まれた行やセルも前後の行やセルと同じ順に並ぶ。"),
    ]


def reader_textbox_sdt(b: Builder):
    """テキストボックスの中の段落と表が、コンテンツコントロールや w:customXml に包まれている。

    図は、画像の段落とキャプションが組になる単純な形で、図の位置は機械的に決まる。
    """
    img = b.add_image("reader_tb.png", png_bytes("Caption in a content control", size=(400, 240)))
    return [
        para(S["body"], "図1はテキストボックスの中のキャプションがコンテンツコントロールに包まれた例。", textbox(
            para(S["body"], drawing(img, 1800000, 1100000, 412, name="図"))
            + sdt(para(S["fig_cap"], "図1\u3000コンテンツコントロールに包んだキャプション")), 411, cy=1500000)),
        para(S["body"], "表5はテキストボックスの中のキャプションと表が包まれた例。", textbox(
            custom_xml(para(S["tab_cap"], "表5\u3000テキストボックスの中の包まれた表"), "caption")
            + sdt(table_of_rows([tr("観点", "内容"), tr("包んだ表", "テキストボックスのSDTの表")], 2)),
            413, cy=1000000)),
        para(S["body"], "以上が読み取りの確かめである。"),
    ]


# ----------------------------------------------------------------------------- 読み取りの文字ポリシー（修正計画の G）の部品
def _mark_id(kind, xml):
    """変更履歴の印の w:id（中身から決める。何度作っても同じ docx になるように。deleted() と同じ考え）。"""
    return zlib.crc32((kind + xml).encode("utf-8")) % 90000 + 10000


def _change_mark(tag, kind, xml):
    """中身のない変更履歴の印（w:del・w:moveFrom・w:cellDel）。"""
    return f'<w:{tag} w:id="{_mark_id(kind, xml)}" w:author="試験" w:date="2026-01-01T00:00:00Z"/>'


def para_mark_deleted(style, *parts, kind="del", num_id=None):
    """段落記号を変更履歴で削除した段落（w:pPr/w:rPr の w:del。kind="move" なら w:moveFrom）。Word で変更を承諾すると、
    次の段落とつながって 1 段落になる。num_id があれば自動番号の段落（list_item と同じ）。"""
    body = "".join(p if p.startswith("<") else run(p) for p in parts if p)
    ppr = (f'<w:pStyle w:val="{style}"/>' if style else "")
    if num_id is not None:
        ppr += f'<w:numPr><w:ilvl w:val="0"/><w:numId w:val="{num_id}"/></w:numPr>'
    tag = "moveFrom" if kind == "move" else "del"
    return f"<w:p><w:pPr>{ppr}<w:rPr>{_change_mark(tag, tag, body)}</w:rPr></w:pPr>{body}</w:p>"


def para_mark_hidden(style, *parts):
    """段落記号を隠し文字にした段落（スタイル区切り。w:pPr/w:rPr の w:vanish と w:specVanish）。削除ではないので、つながない。"""
    body = "".join(p if p.startswith("<") else run(p) for p in parts if p)
    return (f'<w:p><w:pPr><w:pStyle w:val="{style}"/><w:rPr><w:vanish/><w:specVanish/></w:rPr></w:pPr>{body}</w:p>')


def run_styled(text, rstyle=None, vanish=None, spec=False):
    """文字スタイル（rstyle）・直接の隠し文字（vanish が True なら w:vanish、False なら w:vanish w:val="0"）・w:specVanish のラン。"""
    rpr = f'<w:rStyle w:val="{rstyle}"/>' if rstyle else ""
    if vanish is True:
        rpr += "<w:vanish/>"
    elif vanish is False:
        rpr += '<w:vanish w:val="0"/>'
    if spec:
        rpr += "<w:specVanish/>"
    rpr = f"<w:rPr>{rpr}</w:rPr>" if rpr else ""
    sp = ' xml:space="preserve"' if text != text.strip() else ""
    return f"<w:r>{rpr}<w:t{sp}>{escape(text)}</w:t></w:r>"


def br():
    """段落の中の改行（Word の Shift+Enter。w:br）だけのラン。"""
    return "<w:r><w:br/></w:r>"


def run_with_break(before, after, b=True):
    """1 つのランの中に、文字・改行（w:br）・文字が並ぶ（太字のランの中の改行など）。"""
    rpr = "<w:rPr><w:b/></w:rPr>" if b else ""
    return f"<w:r>{rpr}<w:t>{escape(before)}</w:t><w:br/><w:t>{escape(after)}</w:t></w:r>"


def deleted_row(*cells, text_deleted=True, marks=False):
    """変更履歴で削除された表の行（w:trPr/w:del）。text_deleted なら、セルの文字も削除の変更履歴（deleted()）で包む（Word で行を
    削除したときの形。文字の残る行は False）。marks なら、セルの段落記号も削除にする。"""
    tcs = []
    for text in cells:
        inner = deleted(run(text)) if text_deleted else run(text)
        tcs.append(cell(para_mark_deleted(S["body"], inner) if marks else para(S["body"], inner)))
    return f"<w:tr><w:trPr>{_change_mark('del', 'row', ''.join(cells))}</w:trPr>{''.join(tcs)}</w:tr>"


def cell_deleted(content):
    """変更履歴で削除されたセル（w:tcPr/w:cellDel）。content は cell() と同じ。"""
    c = cell(content)
    return c.replace("</w:tcPr>", _change_mark("cellDel", "cell", c) + "</w:tcPr>", 1)


def add_break(b: Builder, p_el, after):
    """front_ja などが作った lxml の段落 p_el の最後に、改行（w:br）のランと、文字 after のランを足す（Builder.set_text では改行を
    入れられないため）。"""
    for r in list(b.frag(f"<w:p>{br()}{run(after)}</w:p>")[0]):
        p_el.append(r)


# 隠し文字（w:vanish）を指定した文字スタイル・段落スタイル（w:basedOn の派生も。Builder.styles_extra に足す）。段落スタイルは
# 本文のスタイル（af5）から派生させる（段落の役割は本文のまま）
READER_STYLES = (
    '<w:style w:type="character" w:customStyle="1" w:styleId="gHid"><w:name w:val="G隠し文字"/><w:rPr><w:vanish/></w:rPr>'
    '</w:style>'
    '<w:style w:type="character" w:customStyle="1" w:styleId="gHidDer"><w:name w:val="G隠し文字の派生"/>'
    '<w:basedOn w:val="gHid"/></w:style>'
    '<w:style w:type="character" w:customStyle="1" w:styleId="gHidOff"><w:name w:val="G隠し文字の派生（表示）"/>'
    '<w:basedOn w:val="gHid"/><w:rPr><w:vanish w:val="0"/></w:rPr></w:style>'
    '<w:style w:type="paragraph" w:customStyle="1" w:styleId="gHidP"><w:name w:val="G隠し段落"/><w:basedOn w:val="af5"/>'
    '<w:rPr><w:vanish/></w:rPr></w:style>'
    '<w:style w:type="paragraph" w:customStyle="1" w:styleId="gHidPDer"><w:name w:val="G隠し段落の派生"/>'
    '<w:basedOn w:val="gHidP"/></w:style>')


def reader_deleted_marks(b: Builder):
    """段落記号を変更履歴で削除した段落（Word で変更を承諾すると次の段落とつながる。修正計画の D5）と、つなげない場所。

    図は、画像の段落とキャプションが組になる単純な形で、図の位置は機械的に決まる（reader_textbox_sdt と同じ形）。
    """
    img2 = b.add_image("reader_join.png", png_bytes("Joined paragraphs", size=(400, 240)))
    img3 = b.add_image("reader_join_tb.png", png_bytes("Joined caption", size=(400, 240)))
    mark = para_mark_deleted
    b.footnotes_extra.append(f'<w:footnote w:id="31">{mark("a8", _note_first("footnoteRef", "脚注の前半と", ""))}'
                             f'{para("a8", "脚注の後半。")}</w:footnote>')
    return [
        # 本文＋本文
        mark(S["body"], "段落記号を削除した前半の文と，"),
        para(S["body"], "次の段落の後半の文がつながる。"),
        # 文字ごと削除した節見出し＋本文（前の段落が空なので、後ろの段落の書式になる）
        mark(S["sec2"], deleted(run("（1）削除した見出し"))),
        para(S["body"], "見出しを削除した後ろの本文である。"),
        # 節見出し＋本文（前の段落の書式。見出しのまま）
        mark(S["sec2"], "（2）見出しの前半と"),
        para(S["body"], "続いた本文の後半"),
        # 本文＋節見出し（前の段落の書式。本文のまま）
        mark(S["body"], "本文の後ろに"),
        para(S["sec2"], "（3）続いた見出し"),
        # 3 段落の連鎖
        mark(S["body"], "連鎖の一つ目，"), mark(S["body"], "連鎖の二つ目，"), para(S["body"], "連鎖の三つ目。"),
        # 自動番号の段落の連鎖（numId=7 は「1.」の番号。文字ごと削除した 2 つ目の項目は、次の項目とつながり、番号を 1 つだけ使う）
        list_item(S["body"], "番号の一つ目の項目。", num_id=7),
        mark(S["body"], deleted(run("削除した番号の項目。")), num_id=7),
        list_item(S["body"], "番号の三つ目の項目。", num_id=7),
        list_item(S["body"], "番号の四つ目の項目。", num_id=7),
        # 段落記号の移動（w:moveFrom）と、段落の間のしおり
        mark(S["body"], "移動の印の前半，", kind="move"), para(S["body"], "移動の印の後半。"),
        mark(S["body"], "しおりをはさむ前半，"), '<w:bookmarkStart w:id="71" w:name="g_join"/><w:bookmarkEnd w:id="71"/>',
        para(S["body"], "しおりをはさむ後半。"),
        # 段落記号の隠し文字（スタイル区切り）はつながない（警告もしない）
        para_mark_hidden(S["body"], "スタイル区切りの前の段落。"), para(S["body"], "スタイル区切りの後の段落。"),
        # つなげない: 次がコンテンツコントロール・カスタム XML、コンテンツコントロールの最後
        mark(S["body"], "次がコンテンツコントロールの段落。"), sdt(para(S["body"], "コンテンツコントロールの中の段落。")),
        mark(S["body"], "次がカスタムXMLの段落。"), custom_xml(para(S["body"], "カスタムXMLの中の段落。"), "para"),
        sdt(para(S["body"], "包まれた段落の一つ目。") + mark(S["body"], "コンテンツコントロールの最後の段落。")),
        para(S["body"], "コンテンツコントロールの後の段落。"),
        # 表の直前（つなげない）と、セルの中（1 段落目はつなぎ、セルの最後の段落はつながない）
        para(S["body"], "表6は段落記号を削除したセルの段落の例である。"),
        mark(S["tab_cap"], "表6　段落記号を削除した表題"),
        table([[cell("観点"), cell("内容")],
               [cell([mark(S["body"], "セルの前半と"), para(S["body"], "セルの後半。")]),
                cell([para(S["body"], "セルの一つ目。"), mark(S["body"], "セルの最後の段落。")])]]),
        # 後ろの段落に結び付いたテキストボックス（図の位置は、つないだ段落の後ろに機械的に決まる）
        mark(S["body"], "図2は段落記号を削除した段落に，"),
        para(S["body"], "続く段落に結び付いた図である。", textbox(
            para(S["body"], drawing(img2, 1800000, 1100000, 432, name="図"))
            + para(S["fig_cap"], "図2　つないだ段落に結び付いた図"), 431, cy=1500000)),
        # テキストボックスの中の連鎖（キャプションを 2 段落に分けたもの）と、テキストボックスの最後の段落（つながない）
        para(S["body"], "図3はテキストボックスの中の表題をつないだ例である。", textbox(
            para(S["body"], drawing(img3, 1800000, 1100000, 434, name="図"))
            + mark(S["fig_cap"], "図3　テキストボックスの中で") + mark(S["fig_cap"], "つないだ表題"), 433, cy=1500000)),
        # 脚注の 1 段落目の段落記号の削除（脚注は 1 段落になる）
        para(S["body"], "段落記号を削除した脚注", footnote_ref(31), "のある文。"),
    ]


def reader_hidden_styles(b: Builder):
    """文字スタイル・段落スタイル（派生も）・直接の指定の隠し文字（w:vanish。修正計画の U8）。スタイルは READER_STYLES。

    隠す文字は「〔〕」で囲む（テストは「〔」が XML にないことを確かめる）。隠し文字のランの中に画像は入れない。
    段落記号の削除でつないだ段落（D5）の隠し文字は、段落ごとの段落スタイルで決める（つないだ後の段落のスタイルにはしない）。
    """
    return [
        para(S["body"], "文字スタイルで", run_styled("〔文字スタイルで隠す〕", rstyle="gHid"), "隠した文字。"),
        para(S["body"], "派生の文字スタイルで", run_styled("〔派生の文字スタイルで隠す〕", rstyle="gHidDer"), "隠した文字。"),
        para(S["body"], "直接の指定で", run_styled("〔直接の指定で隠す〕", vanish=True), "隠した文字。"),
        para(S["body"], run_styled("文字スタイルを直接の指定で打ち消して見える文字。", rstyle="gHid", vanish=False)),
        para("gHidP", "〔段落スタイルで隠した段落〕"),
        para("gHidPDer", "〔派生の段落スタイルで隠した段落〕"),
        para("gHidP", "〔段落スタイルで隠れる文字〕", run_styled("段落と文字のスタイルの反転で見える文字。", rstyle="gHid")),
        # 偽（w:val="0"）を指定した派生の文字スタイルは、反転させないだけで、段落の状態は変えない（隠す段落の中では隠れる。
        # 修正計画の規則。LibreOffice は表示する）
        para(S["body"], "表示を指定した派生の文字スタイルの", run_styled("見える文字。", rstyle="gHidOff")),
        para("gHidP", "〔段落スタイルで隠れる前半〕", run_styled("〔表示を指定した派生の文字スタイルでも隠れる文字〕", rstyle="gHidOff"),
             run_styled("直接の指定で見える後半。", vanish=False)),
        # 段落記号を削除した段落と、隠す段落スタイルの段落の連鎖（見える段落＋隠す段落、隠す段落＋見える段落）。隠し文字は
        # 段落ごとの段落スタイルで決め、書式は文字のある最初の段落（どちらも本文）のもの
        para_mark_deleted(S["body"], "隠す段落に続く見える前半。"), para("gHidP", "〔見える段落に続いた隠す段落〕"),
        para_mark_deleted("gHidP", "〔見える段落に続く隠す段落〕"), para(S["body"], "隠す段落に続いた見える後半。"),
        # 隠し文字のランの中の改行・記号・改行なしハイフン（レポートの 6 章の隠し文字の一覧に載る）
        para(S["body"], "隠した改行と記号", '<w:r><w:rPr><w:vanish/></w:rPr><w:t>〔隠Ａ〕</w:t><w:br/>'
             '<w:sym w:font="Symbol" w:char="F061"/><w:noBreakHyphen/><w:t>〔隠Ｂ〕</w:t></w:r>', "の後の文字。"),
    ]


def reader_line_breaks(b: Builder):
    """段落の中の改行（Word の Shift+Enter。w:br。修正計画の U3）: 表のセル（<break/> を補う）と本文（文字のまま）。題目と
    引用文献の改行は make_reader が足す。"""
    link = b.add_hyperlink("https://example.com/reader-break")
    return [
        para(S["body"], "表7は改行のあるセルの例である（見本，2022）。本文の段落の", br(), "改行の後。"),
        para(S["tab_cap"], "表7　改行のあるセル"),
        table([[cell(para(S["body"], "見出しの", br(), "一行目")), cell("内容")],
               [cell(para(S["body"], "普通の文字の", br(), "改行")),
                cell(para(S["body"], run_with_break("太字の前", "太字の後")))],
               [cell(para(S["body"], run("太字の一つ目", b=True), br(), run("太字の二つ目", b=True))),
                cell(para(S["body"], f'<w:hyperlink r:id="{link}">{run("リンクの")}{br()}{run("中の改行")}</w:hyperlink>'))],
               [cell([para(S["body"], "段落の最後で改行", br()), para(S["body"], "次の段落")]), cell("最後のセル")]],
              header_rows=1),
    ]


def reader_deleted_rows(b: Builder):
    """変更履歴で削除された表の行（w:trPr/w:del）とセル（w:tcPr/w:cellDel）（修正計画の N8）。"""
    return [
        para(S["body"], "表8は変更履歴で行を削除した表の例である。"),
        para(S["tab_cap"], "表8　行を削除した表"),
        table_of_rows([tr("区分", "内容"),
                       deleted_row("削除した行", "削除した内容"),
                       deleted_row("印だけの行", "文字は残る", text_deleted=False),
                       deleted_row("段落記号も削除した行", "段落記号も削除した内容", marks=True),
                       "<w:tr>" + cell("残るセル") + cell_deleted(para(S["body"], deleted(run("削除したセルの文字"))))
                       + "</w:tr>",
                       tr("最後の行", "最後の内容")], 2),
    ]


ZEN_DIGITS = str.maketrans("0123456789", "０１２３４５６７８９")

# sample_reader の節（見出し, 部品を作る関数）。ケースを足すときは、部品を作る関数を足してここに加える。
# 節の見出しの番号は make_reader が付ける。テストは段落の文字で対象を選ぶ（件数や段落の ID に頼らない）
READER_SECTIONS = [
    ("包まれた表の行とセル", reader_wrapped_rows),
    ("テキストボックスの中の包まれた段落と表", reader_textbox_sdt),
    ("段落記号の削除", reader_deleted_marks),
    ("スタイルの隠し文字", reader_hidden_styles),
    ("セルの改行", reader_line_breaks),
    ("削除された表の行", reader_deleted_rows),
]


def make_reader(path):
    """読み取りの境界ケース。sample_edge は件数で確かめるテストがあるので、新しいケースはこちらに足す。

    題目と 2 つ目の引用文献の段落には、段落の中の改行（w:br。修正計画の U3）を入れる。
    """
    b = Builder()
    b.styles_extra.append(READER_STYLES)
    body = []
    body += front_ja(b, "読み取りの検証用文書", "―包まれた要素を読み落とさない―", [("架空大学", "試験\u3000五郎")])
    add_break(b, body[2], "（改行の後の題目）")
    for k, (heading, section) in enumerate(READER_SECTIONS, 1):
        body.append(para(S["sec1"], f"{str(k).translate(ZEN_DIGITS)}．{heading}"))
        body += section(b)
    body.append(para(S["ref_head"], "引用および参考文献"))
    body.append(para(S["ref"], "試験五郎（2023）．「読み取りの検証」．『架空誌』，第4巻，pp.7-8．"))
    body.append(para(S["ref"], "見本六郎（2022）．「改行のある文献」．", br(), "『架空誌』，第3巻，pp.5-6．"))
    body += front_en(b, "Reading Wrapped Elements", "Checking the Reader", [("Goro SHIKEN", "Fictional University")],
                     ["Reader abstract."])
    body += tail(b)
    b.save(path, body)


# ----------------------------------------------------------------------------- 小さな論文
def _note_ref(tag, nid, mark):
    """本文の中の、Word の脚注・文末脚注の参照。mark があれば、記号を自分で付けた参照（customMarkFollows。記号は参照の直後の
    w:t に本文の文字として入る。Word と同じ形）。"""
    if mark:
        return (f'<w:r><w:rPr><w:rStyle w:val="a9"/></w:rPr><w:{tag} w:customMarkFollows="1" w:id="{nid}"/>'
                f'<w:t>{escape(mark)}</w:t></w:r>')
    return f'<w:r><w:rPr><w:rStyle w:val="a9"/></w:rPr><w:{tag} w:id="{nid}"/></w:r>'


def _note_first(ref_tag, text, mark):
    """脚注・文末脚注の 1 段落目の、番号（Word が付ける。mark があれば記号の文字）と text（XML の部品でもよい）。"""
    inner = f"<w:t>{escape(mark)}</w:t>" if mark else f"<w:{ref_tag}/>"
    return f'<w:r><w:rPr><w:rStyle w:val="a9"/></w:rPr>{inner}</w:r>' + (text if text.startswith("<") else run(text))


def footnote_ref(nid, mark=""):
    """本文の中の、Word の脚注の参照（mark は記号を自分で付けた参照の記号）。"""
    return _note_ref("footnoteReference", nid, mark)


def footnote(nid, text, *more, mark=""):
    """Word の脚注（Builder.footnotes_extra に足す）。sample_edge と同じ書き方（スタイル「脚注文字列」）。1 段落目は脚注の番号と
    text（XML の部品でもよい）、more は 2 段落目以降の段落の XML。mark があれば、番号の代わりに記号の文字で始める。"""
    first = f'<w:p><w:pPr><w:pStyle w:val="a8"/></w:pPr>{_note_first("footnoteRef", text, mark)}</w:p>'
    return f'<w:footnote w:id="{nid}">{first}{"".join(more)}</w:footnote>'


def endnote_ref(nid, mark=""):
    """本文の中の、Word の文末脚注の参照（mark は記号を自分で付けた参照の記号）。"""
    return _note_ref("endnoteReference", nid, mark)


def endnote(nid, text, *more, mark=""):
    """Word の文末脚注（Builder.endnotes_extra に足す）。1 段落目は文末脚注の番号と text（XML の部品でもよい）、more は 2 段落目
    以降の段落の XML。mark があれば、番号の代わりに記号の文字で始める（記号を自分で付けた文末脚注の、Word の形）。"""
    first = f'<w:p>{_note_first("endnoteRef", text, mark)}</w:p>'
    return f'<w:endnote w:id="{nid}">{first}{"".join(more)}</w:endnote>'


def deleted(xml):
    """ラン（の XML）を、削除の変更履歴（w:del）で包む。w:t は w:delText にする（Word と同じ形）。
    w:id は中身から決める（何度作っても同じ docx になるように）。"""
    xml = xml.replace("<w:t>", "<w:delText>").replace("<w:t ", "<w:delText ").replace("</w:t>", "</w:delText>")
    return f'<w:del w:id="{zlib.crc32(xml.encode("utf-8")) % 90000 + 10000}" w:author="試験" w:date="2026-01-01T00:00:00Z">{xml}</w:del>'


def make_article(path, title, body_parts, endnotes=(), refs=None, footnotes=(), abstract=("Small article abstract.",),
                 appendix=None, bullet=None):
    """題目・著者・本文・引用文献 1 件・英文要旨だけの小さな論文。

    body_parts(b) は本文の段落（章見出しから）の XML の一覧を返す。本文で「試験（2024）」を引用すると、引用文献にリンクされる。
    endnotes・footnotes は Word の文末脚注・脚注の XML（endnote()・footnote()）の一覧。
    refs(b) は、引用文献 1 件の後ろに足す段落（引用文献の段落など）の XML の一覧を返す（省略すると足さない）。
    abstract は英文要旨の段落の文字の一覧、appendix は英文要旨の後ろ（資料）の段落の XML の一覧（省略すると足さない。
    画像を使うときは appendix(b) の形の関数）。
    bullet: 箇条書き（list_item の numId=6）の記号を「•」から変えるときの記号（出版版 PDF との照合の「●」など）。
    """
    b = Builder()
    b.bullet = bullet
    b.endnotes_extra.extend(endnotes)
    b.footnotes_extra.extend(footnotes)
    body = []
    body += front_ja(b, title, "―検証用の小さな論文―", [("架空大学", "試験\u3000六郎")])
    body += body_parts(b)
    body.append(para(S["ref_head"], "引用および参考文献"))
    body.append(para(S["ref"], "試験六郎（2024）．「小さな論文」．『架空誌』，第5巻，pp.9-10．"))
    if refs is not None:
        body += refs(b)
    body += front_en(b, "A Small Article", "For Checking", [("Rokuro SHIKEN", "Fictional University")], list(abstract))
    body += tail(b, appendix=appendix(b) if callable(appendix) else appendix)
    b.save(path, body)


# ----------------------------------------------------------------------------- 構造の衝突（K1・K2）の検証用
def front_ja_rows(b: Builder, title, rows, loose=()):
    """front_ja と同じだが、著者表の行を [(所属, 著者名)] で自由に与える（空文字は空のセル。所属に改行があれば、所属の欄に段落を
    分けて並べる。行がなければ表を置かない）。loose は、表の後ろに足す段落の XML の一覧（表の外の所属・著者名の段落）。"""
    k = b.kids
    out = [copy.deepcopy(k[0]), copy.deepcopy(k[1])]
    t = copy.deepcopy(k[2])
    b.set_text(t, title)
    out.append(t)
    st = copy.deepcopy(k[3])
    b.set_text(st, "―検証用―")
    out.append(st)
    out.append(copy.deepcopy(k[4]))
    tbl = copy.deepcopy(k[5])
    trs = tbl.findall(f"{{{W}}}tr")
    proto = trs[0]
    for r in trs:
        tbl.remove(r)
    for aff, name in rows:
        r = copy.deepcopy(proto)
        cells = r.findall(f"{{{W}}}tc")
        first, *more = aff.split("\n")         # 所属の欄に段落を分けて並べるときは、改行で区切る
        ap = cells[0].find(f".//{{{W}}}p")
        b.set_text(ap, first)
        for text in more:
            extra = copy.deepcopy(ap)
            b.set_text(extra, text)
            ap.addnext(extra)
            ap = extra
        b.set_text(cells[1].find(f".//{{{W}}}p"), name)
        tbl.append(r)
    if rows:
        out.append(tbl)
    out.extend(b.frag("".join(loose)) if loose else [])
    out.extend(copy.deepcopy(x) for x in k[6:9])
    return out


def front_en_rows(b: Builder, rows, abstract=("Small article abstract.",), heading=True):
    """front_en と同じだが、英文の著者表の行を [("name" か "aff", 文字)] で自由に並べる。heading が偽なら英文要旨の見出し（Abstract）を
    置かない。"""
    k = b.kids
    i2 = [i for i, el in enumerate(k) if el.find(f".//{{{W}}}sectPr") is not None][1]
    out = [copy.deepcopy(k[i2]), copy.deepcopy(k[i2 + 1])]
    t = copy.deepcopy(k[i2 + 2])
    b.set_text(t, "A Small Article")
    out.append(t)
    st = copy.deepcopy(k[i2 + 3])
    b.set_text(st, "For Checking")
    out.append(st)
    tbl = copy.deepcopy(k[i2 + 4])
    trs = tbl.findall(f"{{{W}}}tr")
    pn, pa = trs[0], trs[1]
    for r in trs:
        tbl.remove(r)
    for kind, text in rows:
        r = copy.deepcopy(pn if kind == "name" else pa)
        b.set_text(r.find(f".//{{{W}}}p"), text)
        tbl.append(r)
    out.append(tbl)
    if heading:
        out.append(copy.deepcopy(k[i2 + 5]))    # Abstract 見出し
    for text in abstract:
        out.append(para(S["abs"], text))
    return out


def make_conflict(path, body=None, back=None, ja_rows=(("架空大学", "試験\u3000六郎"),), loose=(),
                  en_rows=(("name", "Rokuro SHIKEN"), ("aff", "Fictional University")), en_after=None, en_heading=True):
    """後付けの見出しの重複・所属の連続（docs/REVIEW_2026-11.md の K1・K2）の検証用の小さな論文。

    body: 本文（章見出しの後ろ）に足す段落の XML の一覧。back: 後付け（引用文献の見出し・1 件の代わりに置く段落の XML の一覧。
    省略すると引用文献の見出しと 1 件）。ja_rows・loose: 和文の著者表の行と、表の後ろの段落（front_ja_rows）。en_rows: 英文の著者表の
    行（front_en_rows）。en_after: 英文要旨の後ろに足す段落の XML の一覧。en_heading が偽なら、英文の著者表の後ろの英文要旨の見出しを
    置かない。
    """
    b = Builder()
    parts = front_ja_rows(b, "検証用の論文", list(ja_rows), loose)
    parts += [para(S["sec1"], "１．はじめに"), para(S["body"], "架空の主張である（試験，2024）。")]
    parts += list(body or [])
    if back is None:
        parts.append(para(S["ref_head"], "引用文献"))
        parts.append(para(S["ref"], "試験六郎（2024）．「小さな論文」．『架空誌』，第5巻，pp.9-10．"))
    else:
        parts += list(back)
    parts += front_en_rows(b, list(en_rows), heading=en_heading)
    parts += list(en_after or [])
    parts.append(copy.deepcopy(b.kids[-1]))
    b.save(path, parts)
    return path


# ----------------------------------------------------------------------------- sample_float_text
def float_text_parts(b: Builder, down_cm=0):
    """テキストボックスの中で、画像と文字（説明文）が同じ段落にある図形。図1 はキャプションあり、もう 1 つはキャプションなし。

    down_cm: 図1 のテキストボックスを、アンカー段落から下にずらす量（cm）。0 なら位置は機械的に決まる。
    0 より大きければ位置を決められない図表になる（AI による配置の指定を試すため）。
    """
    img1 = b.add_image("float_text_1.png", png_bytes("Picture with text", size=(400, 240)))
    img2 = b.add_image("float_text_2.png", png_bytes("No caption", size=(400, 240)))
    cm = 360000
    return [
        para(S["sec1"], "１．画像と文字が同じ段落の図"),
        para(S["body"], "試験（2024）にならい，図1では画像と説明文を同じ段落に置いた。"),
        para(S["body"], "この段落に図1のテキストボックスが結び付いている。", textbox(
            para(S["body"], drawing(img1, 1800000, 1080000, 512), "説明文：図1の画像と同じ段落にある文字。")
            + para(S["fig_cap"], "図1\u3000画像と文字が同じ段落の図"), 511, cx=8 * cm, cy=4 * cm,
            v=("paragraph", int(down_cm * cm)), wrap="wrapTopAndBottom")),
        para(S["body"], "以上が図1である。"),
        para(S["sec1"], "２．キャプションのない図形"),
        para(S["body"], "この段落にキャプションのないテキストボックスが結び付いている。", textbox(
            para(S["body"], drawing(img2, 1800000, 1080000, 522), "説明文：キャプションのない図形の文字。"),
            521, cx=8 * cm, cy=4 * cm, wrap="wrapTopAndBottom")),
        para(S["body"], "以上のように，図形の中の文字も落とさない。"),
    ]


def make_float_text(path, down_cm=0):
    """テキストボックスの中で、画像と文字が同じ段落にある図形の原稿（ALL_DOCS には入れない）。"""
    make_article(path, "図形の中の画像と文字の検証用文書", lambda b: float_text_parts(b, down_cm))


# ----------------------------------------------------------------------------- sample_structure
def structure_textbox_regions(b: Builder, textboxes=True):
    """本文中のテキストボックスに、本文の外で使うスタイル・文字の段落がある。

    「注」だけのテキストボックスの後ろに番号で始まる本文の段落が、「英文要旨」スタイルの英語の段落のテキストボックスの
    後ろに本文・章見出し・引用文献が続く。図形の中の段落では領域が変わらないので、どちらのテキストボックスの段落も
    本文の領域に入り、以降の本文は注にも英文要旨にもならない。
    textboxes=False なら、テキストボックスを除いた同じ原稿（テキストボックスがない場合と比べるため）。
    """
    def tb(inner, pid, cx):
        return textbox(inner, pid, cx=cx, cy=300000) if textboxes else ""
    return [
        para(S["body"], "試験（2025）にならい，図形の中の文字で論文の構造が変わらないことを確かめる。",
             tb(para(S["body"], "注"), 611, 600000)),
        para(S["body"], "1) 番号で始まる本文の段落も，注にはならない。"),
        para(S["body"], "英語の語を囲みに入れた。", tb(para(S["abs"], "Area model"), 612, 900000)),
        para(S["body"], "囲みの後の本文も，本文のまま続く。"),
    ]


def structure_word_notes(b: Builder):
    """Word の脚注と文末脚注（tests/test_notes.py）。

    脚注 5 と文末脚注 5（ID が重なる。文末脚注 5 は 2 段落）、削除の変更履歴の中の脚注 6 の参照、記号を自分で付けた
    文末脚注 7（本文の記号「*」）、脚注 8 の中から文末脚注 8 を参照、参照のない脚注 9（2 段落目は全角空白だけ）。
    期待: 本文で最初に参照される順の通し番号で、脚注 5 が fn1「1)」、文末脚注 5 が fn2「2)」、文末脚注 7 が fn3（本文の記号は
    docx の文字のまま、注の一覧は「3)」）、脚注 8 が fn4、文末脚注 8 が fn5（脚注 8 の中からリンク）。脚注 6・9 は理由付きで除外。
    """
    b.footnotes_extra += [
        footnote(5, " 脚注５の架空の説明。"),
        footnote(6, " 参照が削除された脚注６の架空の説明。"),
        footnote(8, run(" 脚注８の中から文末脚注を参照する") + endnote_ref(8) + run("架空の説明。")),
        footnote(9, " 参照されていない脚注９の架空の説明。", para("a8", "\u3000")),
    ]
    b.endnotes_extra += [
        endnote(5, " 文末脚注５の一段落目の架空の説明。", para(None, "文末脚注５の二段落目の架空の補足。")),
        endnote(7, " 記号を自分で付けた文末脚注７の架空の説明。", mark="*"),
        endnote(8, " 脚注の中から参照される文末脚注８の架空の説明。"),
    ]
    return [
        para(S["body"], "脚注を付けた文", footnote_ref(5), "と文末脚注を付けた文", endnote_ref(5), "。"),
        para(S["body"], "削除した参照", deleted(footnote_ref(6)), "のある文。"),
        para(S["body"], "記号を自分で付けた文末脚注", endnote_ref(7, mark="*"), "の文と，注の中から文末脚注を参照する脚注",
             footnote_ref(8), "の文。"),
    ]


def structure_textboxes(b: Builder):
    """文字だけのテキストボックス（tests/test_structure.py・tests/test_ai.py。修正計画の D1）。

    (a) 図の左上がアンカー段落の左上にある、幅の広い囲み（問題文・自動番号の 2 項目・ヒント・全角空白だけの段落・「(1)」の付いた
    別行数式。後ろの本文に「式(1)」）。(c) 段落の末尾にある行内の囲み。(d) 幅が広く短い「（ヒント）」（囲みか注記か決められない）。
    (e) VML だけの、位置を指定した（position:absolute）囲み。空のテキストボックスと、全角空白だけのテキストボックス。
    (b) 画像・図キャプションの次の段落に結び付いた、上にずらした小さな注記「A 点」（図に重ねた注記）。(f) 画像の段落の後ろの段落に
    結び付いた、図キャプションだけのテキストボックス（今までどおり図のキャプション）。(a)〜(e) は画像から 3 段落以上離す。
    """
    cm = 360000
    tri = b.add_image("structure_tri.png", png_bytes("Fictional triangle", size=(400, 240)))
    tri2 = b.add_image("structure_tri2.png", png_bytes("Second triangle", size=(400, 240)))
    formula = para(S["body"], omathpara(mr("S=") + mfrac(mr("1"), mr("2")) + mr("ah")), tab(), "(1)", jc="center")
    box_a = (para(S["body"], "問1　架空の三角形の面積を求めよ。底辺と高さは図に示す。")
             + list_item(S["body"], "底辺と高さを測る。") + list_item(S["body"], "面積の式に当てはめる。")
             + para(S["body"], "ヒント　架空の補助線をひく。") + para(S["body"], "　") + formula)
    box_c = para(S["body"], "問2　架空の問いを二つの式で考えよ。") + para(S["body"], "答えは一つに決まる。")
    box_e = para(S["body"], "問3　架空の数の列の規則を説明せよ。") + para(S["body"], "一つ目の数は二である。")
    return [
        para(S["body"], "試験（2025）の問題を次に示す。", textbox(box_a, 621, cx=12 * cm, cy=3 * cm, wrap="wrapTopAndBottom")),
        para(S["body"], "式(1)より面積が分かる。"),
        para(S["body"], "次の囲みを読む。", textbox_inline(box_c, 622, cx=10 * cm, cy=2 * cm)),
        para(S["body"], "囲みの後の段落である。"),
        para(S["body"], "ヒントを付けた。", textbox(para(S["body"], "（ヒント）"), 623, cx=10 * cm, cy=int(0.8 * cm),
                                             v=("paragraph", int(1.5 * cm)), wrap="wrapTopAndBottom")),
        para(S["body"], "枠の中の問題を考える。", vml_textbox(box_e, width="300pt", height="60pt", absolute=True)),
        para(S["body"], "空の囲みを置いた。", textbox(para(S["body"], ""), 624, cx=10 * cm, cy=cm),
             textbox(para(S["body"], "　"), 625, cx=10 * cm, cy=cm)),
        para(S["body"], "図の前の段落である。"),
        para(S["body"], drawing(tri, 1800000, 1080000, 626)),
        para(S["fig_cap"], "図1　架空の三角形"),
        para(S["body"], "図1の点に名前を付けた。", textbox(para(S["body"], "A 点"), 627, cx=cm, cy=int(0.6 * cm),
                                                 h=("column", 2 * cm), v=("paragraph", -2 * cm))),
        para(S["body"], drawing(tri2, 1800000, 1080000, 628)),
        para(S["body"], "この段落に図2のキャプションのテキストボックスが結び付いている。",
             textbox(para(S["fig_cap"], "図2　テキストボックスのキャプション"), 629, cx=8 * cm, cy=int(0.7 * cm),
                     wrap="wrapTopAndBottom")),
        para(S["body"], "以上で囲みと注記の例を終える。"),
    ]


# sample_structure の節（見出し, 部品を作る関数）。ケースを足すときは、部品を作る関数を足してここに加える。
# 節の見出しの番号は make_structure が付ける。テストは段落の文字で対象を選ぶ（件数や段落の ID に頼らない）
STRUCTURE_SECTIONS = [
    ("テキストボックスの中の別の領域のスタイル", structure_textbox_regions),
    ("Word の脚注と文末脚注", structure_word_notes),
    ("囲みと図の注記", structure_textboxes),
]
# sample_structure の英文要旨の後ろの資料（「資料」の直後がかっこの見出し。tests/test_structure.py）
STRUCTURE_APPENDIX = [("abs", "資料（授業プリント）"), ("abs", "問1\u3000架空の問題文である。"),
                      ("abs", "問2\u3000もう一つの架空の問題文である。")]


def make_structure(path, sections=None):
    """論文の構造（領域の分け方など）の境界ケース。

    sections は（見出し, 部品を作る関数）の一覧で、省略すると STRUCTURE_SECTIONS。最後の節「おわりに」と引用文献は
    make_structure が付ける（ケースの後ろにも章見出し・本文・引用文献があるようにするため）。
    """
    b = Builder()
    body = []
    body += front_ja(b, "構造の検証用文書", "―図形の中の文字で領域を変えない―", [("架空大学", "試験　七郎")])
    k = 0
    for k, (heading, section) in enumerate(STRUCTURE_SECTIONS if sections is None else sections, 1):
        body.append(para(S["sec1"], f"{str(k).translate(ZEN_DIGITS)}．{heading}"))
        body += section(b)
    body.append(para(S["sec1"], f"{str(k + 1).translate(ZEN_DIGITS)}．おわりに"))
    body.append(para(S["body"], "以上のように，章と引用文献は図形の中の文字に左右されない。"))
    body.append(para(S["ref_head"], "引用および参考文献"))
    body.append(para(S["ref"], "試験七郎（2025）．「構造の検証」．『架空誌』，第6巻，pp.11-12．"))
    body += front_en(b, "Checking the Structure", "Regions and Shapes", [("Shichiro SHIKEN", "Fictional University")],
                     ["Structure abstract."])
    body += tail(b, appendix=[para(S[style], text) for style, text in STRUCTURE_APPENDIX])
    b.save(path, body)


# ----------------------------------------------------------------------------- sample_b3_*（位置を決められない図表・表で組んだ図）
B3_CM = 360000


def b3_cells_parts(b: Builder, variant=""):
    """表のセルに画像とキャプションが並ぶ図形。どれも図の左上がアンカー段落の左上にある（位置は機械的に決まる）。

    s1: 1 行 2 列。セルごとに画像とキャプション（図1・図2）。s2: 2 行 1 列。1 行目に画像 2 つ、2 行目にキャプション 1 つ（図3）。
    s3: 2 行 2 列。1 行目に画像、2 行目にキャプション（図4・図5。同じ列の画像とキャプションが組になる）。
    variant（テストの中で作る。「+」でつなぐと組み合わせる）: "text"（s1 の右のセルにキャプションでない文字「（a）」）、
    "tabcap"（s1 の右のセルのキャプションを表キャプションに）、"cross"（s3 の画像とキャプションを互い違いに置く: 組を一つに
    決められない）、"extra"（s3 の 1 行目に、キャプションのない 3 つ目の画像）、"down"・"down3"（s1・s3 をアンカー段落から
    2 cm 下にずらす: 位置を決められない）、"mixed"（s1 の左のセルの画像の段落に、説明の文字も書く）
    """
    vs = set(variant.split("+"))
    im = [b.add_image(f"b3_cell_{k}.png", png_bytes(f"Cell picture {k}", size=(300, 200))) for k in range(1, 8)]

    def pic(k, pid, text=""):
        return para(S["body"], drawing(im[k], 1440000, 960000, pid), text)

    c1 = [pic(0, 711, "説明文：左のセルの画像と同じ段落にある文字。" if "mixed" in vs else ""),
          para(S["fig_cap"], "図1\u3000左のセルの図")]
    c2 = [pic(1, 712), para(S["fig_cap"], "図2\u3000右のセルの図")]
    if "text" in vs:
        c2.insert(1, para(S["body"], "（a）"))
    if "tabcap" in vs:
        c2[1] = para(S["tab_cap"], "表1\u3000セルの中の表キャプション")
    v1 = ("paragraph", 2 * B3_CM) if "down" in vs else ("paragraph", 0)
    v3 = ("paragraph", 2 * B3_CM) if "down3" in vs else ("paragraph", 0)
    rows3 = [[cell(pic(4, 731)), cell(pic(5, 732))],
             [cell(para(S["fig_cap"], "図4\u3000左の列の図")), cell(para(S["fig_cap"], "図5\u3000右の列の図"))]]
    if "cross" in vs:
        rows3 = [[cell(pic(4, 731)), cell(para(S["fig_cap"], "図4\u3000左の列の図"))],
                 [cell(para(S["fig_cap"], "図5\u3000右の列の図")), cell(pic(5, 732))]]
    if "extra" in vs:
        rows3[0].append(cell(pic(6, 733)))
        rows3[1].append(cell(""))
    return [
        para(S["sec1"], "１．表のセルに並べた図"),
        para(S["body"], "試験（2024）にならい，図1と図2を表のセルに並べた。"),
        para(S["body"], "この段落に図1と図2のテキストボックスが結び付いている。", textbox(
            table([[cell(c1), cell(c2)]]), 710, cx=16 * B3_CM, cy=5 * B3_CM, v=v1, wrap="wrapTopAndBottom")),
        para(S["body"], "図3は，二つの画像からなる図である。"),
        para(S["body"], "この段落に図3のテキストボックスが結び付いている。", textbox(
            table([[cell([pic(2, 721), pic(3, 722)])], [cell(para(S["fig_cap"], "図3\u3000二つの画像からなる図"))]]),
            720, cx=8 * B3_CM, cy=6 * B3_CM, wrap="wrapTopAndBottom")),
        para(S["body"], "図4と図5は，画像の行とキャプションの行に分けた表に並べた。"),
        para(S["body"], "この段落に図4と図5のテキストボックスが結び付いている。", textbox(
            table(rows3), 730, cx=16 * B3_CM, cy=6 * B3_CM, v=v3, wrap="wrapTopAndBottom")),
        para(S["body"], "以上のように，表のセルに並べた図も図として出力する。"),
    ]


def make_b3_cells(path, variant=""):
    """表のセルに画像とキャプションが並ぶ図形の原稿（AI なしで図に組める。variant は b3_cells_parts）。"""
    make_article(path, "表のセルに並べた図の検証用文書", lambda b: b3_cells_parts(b, variant))


def b3_tablefig_parts(b: Builder, variant=""):
    """画像のない図キャプションと、その隣のキャプションのない表（図形ではない本文の表）。

    図1: 表の直後に図キャプション（表を図の本体にする）。図2: 表と図キャプションの間に本文の段落（組まない・要対応）。
    図3: 表キャプションの付いた表の直後に図キャプション（組まない・要対応）。
    variant="above": 図キャプションを図の上に置く原稿（画像の図 1 つで判定させる）。図4 の直後の表を図の本体にする。
    """
    out = [para(S["sec1"], "１．表で組んだ図"),
           para(S["body"], "試験（2024）にならい，図1は問題文を表で組んだ。")]
    if variant == "above":
        img = b.add_image("b3_above.png", png_bytes("Caption above", size=(300, 200)))
        return out + [
            para(S["fig_cap"], "図5\u3000キャプションを上に置いた図"), para(S["body"], drawing(img, 1440000, 960000, 741)),
            para(S["body"], "図4は，図キャプションの下に表を置いた。"),
            para(S["fig_cap"], "図4\u3000表の上のキャプション"),
            table([[cell("問4\u3000キャプションの下の表で組んだ架空の問題である。")]]),
            para(S["body"], "以上が図4である。")]
    return out + [
        table([[cell("問1\u3000表で組んだ架空の問題である。")]]),
        para(S["fig_cap"], "図1\u3000表で組んだ問題"),
        para(S["body"], "図2は，表と図キャプションの間に段落がある例である。"),
        table([[cell("問2\u3000もう一つの架空の問題である。")]]),
        para(S["body"], "この段落は表と図キャプションの間にある。"),
        para(S["fig_cap"], "図2\u3000間に段落がある問題"),
        para(S["tab_cap"], "表1\u3000表キャプションの付いた表"),
        table([[cell("観点"), cell("内容")], [cell("論証"), cell("根拠を示す")]]),
        para(S["fig_cap"], "図3\u3000表の直後の図キャプション"),
        para(S["body"], "以上のように，表で組んだ図を確かめる。")]


def make_b3_tablefig(path, variant=""):
    """画像のない図キャプションと、その隣のキャプションのない表の原稿（図形はない。variant は b3_tablefig_parts）。"""
    make_article(path, "表で組んだ図の検証用文書", lambda b: b3_tablefig_parts(b, variant))


def b3_place_parts(b: Builder, variant=""):
    """位置を決められない図表（どれも図の上端がアンカー段落から離れている）の仮の置き場所。

    s1: アンカー段落から 3 cm 下の図1。s2・s3: 同じアンカー段落に、docx の順で図3・図2。s4: 文字のない段落に結び付いた図4。
    variant（テストの中で作る）: s1 のアンカー段落を、"list" は 3 項目の箇条書きの 2 つ目の項目、"quote" は 3 段落の引用の
    2 つ目の段落にする。"blank_list" は、2 項目の箇条書きの項目の間の空の段落に s1 を結び付ける。s1 を箇条書きの最初の項目に
    結び付け、その後ろを次の形にするもの: "two_lists"（2 つ目の項目、本文の段落、同じ番号の定義の 2 項目の箇条書き）、
    "list_heading"（2 つ目の項目、同じ番号の定義で、見出しと推定する太字の「２．…」の段落）、"list_image"（画像と文字が同じ
    段落の項目、3 つ目の項目、画像だけの項目）、"list_math"（2 つ目の項目、別行数式だけの項目、4 つ目の項目）、"list_textbox"
    （2 つ目の項目、同じ番号の定義の段落を入れた、浮動配置でないテキストボックス）、"list_box"（2 つ目の項目、文字だけの浮動配置で
    ないテキストボックスの段落、3 つ目の項目）。"other_list" は、2 項目の箇条書きの最後の
    項目に s1 を結び付け、すぐ後ろに別の番号の定義の 2 項目の箇条書きを置く。"quote_blank" は、引用の 2 つ目の段落に s1 を
    結び付け、3 つ目の段落との間に空の段落を置く。
    """
    img = [b.add_image(f"b3_place_{k}.png", png_bytes(f"Place {k}", size=(300, 200))) for k in range(1, 5)]

    def tb(k, cap, pid, down):
        return textbox(para(S["body"], drawing(img[k], 1440000, 960000, pid + 1)) + para(S["fig_cap"], cap), pid,
                       cx=8 * B3_CM, cy=4 * B3_CM, v=("paragraph", int(down * B3_CM)), wrap="wrapTopAndBottom")
    s1 = tb(0, "図1\u3000一つ目の図", 750, 3)
    first = [para(S["body"], "この段落に図1のテキストボックスが結び付いている。", s1)]
    if variant == "list":
        first = [list_item(S["body"], "箇条書きの一つ目の項目である。"),
                 list_item(S["body"], "この項目に図1のテキストボックスが結び付いている。", s1),
                 list_item(S["body"], "箇条書きの三つ目の項目である。")]
    elif variant == "quote":
        first = [para(S["quote"], "引用の一つ目の段落である。"),
                 para(S["quote"], "この引用の段落に図1のテキストボックスが結び付いている。", s1),
                 para(S["quote"], "引用の三つ目の段落である。")]
    elif variant == "blank_list":
        first = [list_item(S["body"], "箇条書きの一つ目の項目である。"), para(S["body"], s1),
                 list_item(S["body"], "箇条書きの二つ目の項目である。")]
    elif variant == "other_list":
        first = [list_item(S["body"], "箇条書きの一つ目の項目である。"),
                 list_item(S["body"], "この項目に図1のテキストボックスが結び付いている。", s1),
                 list_item(S["body"], "別の番号の箇条書きの一つ目である。", num_id=7),
                 list_item(S["body"], "別の番号の箇条書きの二つ目である。", num_id=7)]
    elif variant == "quote_blank":
        first = [para(S["quote"], "引用の一つ目の段落である。"),
                 para(S["quote"], "この引用の段落に図1のテキストボックスが結び付いている。", s1),
                 para(S["body"], ""), para(S["quote"], "引用の三つ目の段落である。")]
    elif variant in ("two_lists", "list_heading", "list_image", "list_math", "list_textbox", "list_box"):
        first = [list_item(S["body"], "この項目に図1のテキストボックスが結び付いている。", s1)]
        if variant == "two_lists":
            first += [list_item(S["body"], "一つ目の箇条書きの二つ目の項目である。"),
                      para(S["body"], "二つの箇条書きの間にある本文の段落である。"),
                      list_item(S["body"], "二つ目の箇条書きの項目である。"),
                      list_item(S["body"], "二つ目の箇条書きの最後の項目である。")]
        elif variant == "list_heading":
            first += [list_item(S["body"], "箇条書きの二つ目の項目である。"),
                      list_item(S["body"], run("２．見出しと推定する段落", b=True))]
        elif variant == "list_image":
            item = [b.add_image(f"b3_place_item_{k}.png", png_bytes(f"Item {k}", size=(300, 200))) for k in (1, 2)]
            first += [list_item(S["body"], drawing(item[0], 720000, 480000, 756), "二つ目の項目には画像と文字がある。"),
                      list_item(S["body"], "箇条書きの三つ目の項目である。"),
                      list_item(S["body"], drawing(item[1], 1440000, 960000, 757))]
        elif variant == "list_math":
            first += [list_item(S["body"], "箇条書きの二つ目の項目である。"),
                      list_item(S["body"], omathpara(mr("y=") + mfrac(mr("1"), mr("2")) + mr("x"))),
                      list_item(S["body"], "数式の後ろの項目である。")]
        elif variant == "list_box":
            first += [list_item(S["body"], "箇条書きの二つ目の項目である。"),
                      para(S["body"], vml_textbox(para(S["body"], "囲みの中の架空の文である。"))),
                      list_item(S["body"], "箇条書きの三つ目の項目である。")]
        else:
            vml = ('<w:r><w:pict><v:shape><v:textbox><w:txbxContent>'
                   + list_item(S["body"], "浮動配置でないテキストボックスの中の項目である。")
                   + '</w:txbxContent></v:textbox></v:shape></w:pict></w:r>')
            first += [list_item(S["body"], "箇条書きの二つ目の項目である。"), para(S["body"], vml)]
    return [para(S["sec1"], "１．仮の置き場所"),
            para(S["body"], "試験（2024）にならい，図1を置く。"),
            *first,
            para(S["body"], "図2と図3は同じ段落に結び付いている。"),
            para(S["body"], "この段落に図3と図2のテキストボックスが結び付いている。", tb(1, "図3\u3000三つ目の図", 760, 2),
                 tb(2, "図2\u3000二つ目の図", 770, 5)),
            para(S["body"], tb(3, "図4\u3000空の段落に結び付いた図", 780, 2)),
            para(S["sec1"], "２．おわりに"),
            para(S["body"], "以上のように，図の位置は docx だけでは決められない。")]


def b3_place_refs(b: Builder, outside=False):
    """引用文献の後ろの注（AI が注の段落の後ろを答える例のため）。outside なら、注の段落に図形を結び付ける（本文の外の図形）。"""
    note = "1) 架空の注である。"
    if not outside:
        return [para(S["fn_head"], "注"), para(S["body"], note)]
    img = b.add_image("b3_outside.png", png_bytes("Outside", size=(300, 200)))
    return [para(S["fn_head"], "注"), para(S["body"], note, textbox(
        para(S["body"], drawing(img, 1440000, 960000, 791)) + para(S["fig_cap"], "図5\u3000注に結び付いた図"), 790,
        cx=8 * B3_CM, cy=4 * B3_CM, v=("paragraph", 2 * B3_CM), wrap="wrapTopAndBottom"))]


def make_b3_place(path, outside=False, variant=""):
    """位置を決められない図表の仮の置き場所の原稿（AI 補完が必要。ALL_DOCS には入れない。variant は b3_place_parts）。"""
    make_article(path, "仮の置き場所の検証用文書", lambda b: b3_place_parts(b, variant),
                 refs=lambda b: b3_place_refs(b, outside))


# ----------------------------------------------------------------------------- 図形の外の図の決め方（修正計画 W1 の手順 4）
def anchored_drawing(rid, cx, cy, pid, h=("column", 0), v=("paragraph", 0)):
    """浮動配置（wp:anchor）の画像 1 つ（図形〈グループ・テキストボックス〉ではない。段落に結び付いた浮動の画像）。"""
    graphic = (f'<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
               f'<pic:pic><pic:nvPicPr><pic:cNvPr id="{pid}" name="図"/><pic:cNvPicPr/></pic:nvPicPr>'
               f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
               f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
               f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic>')
    return ('<w:r><w:drawing><wp:anchor distT="0" distB="0" distL="0" distR="0" simplePos="0" relativeHeight="1" '
            'behindDoc="0" locked="0" layoutInCell="1" allowOverlap="1"><wp:simplePos x="0" y="0"/>'
            f'<wp:positionH relativeFrom="{h[0]}"><wp:posOffset>{h[1]}</wp:posOffset></wp:positionH>'
            f'<wp:positionV relativeFrom="{v[0]}"><wp:posOffset>{v[1]}</wp:posOffset></wp:positionV>'
            f'<wp:extent cx="{cx}" cy="{cy}"/><wp:wrapTopAndBottom/><wp:docPr id="{pid}" name="図 {pid}"/>'
            f'{graphic}</wp:anchor></w:drawing></w:r>')


def figs_parts(b: Builder, variant):
    """図形の外の図キャプションと画像の並び（修正計画 W1 の 2.3 の A1〜A5・E・D。図キャプションは図の下）。variant:

    run_frame: 画像だけの段落・枠の図形だけの段落・画像だけの段落・図キャプション（C033・C028）。
    same_para_before / same_para_after: 図キャプションの段落の先頭・末尾に画像（C006）。
    near3 / near4: 画像の結び付いた本文の段落の 3 / 4 要素後ろに、画像のない図キャプション（C030）。
    near_other_caption: 画像の結び付いた本文の段落と、画像のない図キャプションの間に、別の図（画像と図キャプション）。
    near_above: 図キャプションを図の上に置く原稿（図9 とその後ろの画像）で、画像のない図キャプションと、その続きの段落の後ろ
    2 要素目に、画像の結び付いた本文の段落。
    heading: 浮動の画像の結び付いた章見出し（近くに図キャプションがない）。
    table_first: 画像だけの段落・本文の段落・キャプションのない表・図キャプション（表で組んだ図。画像はキャプションなし）。
    deco: 枠の図形だけの段落（行内）と、白い四角の図形だけの段落（浮動）。
    ellipse_chart: 楕円の図形だけの段落と、グラフだけの段落。
    """
    im = [b.add_image(f"figs_{variant}_{k}.png", png_bytes(f"Figs {k}", size=(300, 200))) for k in range(1, 4)]
    pic = [drawing(im[k], 1440000, 960000, 941 + k) for k in range(3)]
    float_pic = anchored_drawing(im[2], 1440000, 960000, 951)
    cap = para(S["fig_cap"], "図1\u3000架空の図")
    text = [para(S["body"], f"これは間にある本文の段落{k}である。") for k in range(1, 4)]
    head = [para(S["sec1"], "１．図の並び"), para(S["body"], "試験（2024）にならう。")]
    body = {
        "run_frame": [para(S["body"], pic[0]), para(S["body"], shape("rect", "none", pid=961)), para(S["body"], pic[1]), cap],
        "same_para_before": [para(S["fig_cap"], pic[0], "図1\u3000キャプションの段落の中の画像")],
        "same_para_after": [para(S["fig_cap"], "図1\u3000キャプションの段落の中の画像", pic[0])],
        "near3": [para(S["body"], "この段落に浮動の画像が結び付いている。", float_pic), text[0], text[1], cap],
        "near4": [para(S["body"], "この段落に浮動の画像が結び付いている。", float_pic), text[0], text[1], text[2], cap],
        "near_other_caption": [para(S["body"], "この段落に浮動の画像が結び付いている。", float_pic), para(S["body"], pic[0]),
                               para(S["fig_cap"], "図1\u3000画像のある図"), para(S["fig_cap"], "図2\u3000画像のない図")],
        "near_above": [para(S["fig_cap"], "図9\u3000上のキャプションの図"), para(S["body"], pic[0]), text[0],
                       para(S["fig_cap"], "図1\u3000画像のない図"), para(S["fig_cap"], "（出典：架空の資料）"), text[1],
                       para(S["body"], "この段落に浮動の画像が結び付いている。", float_pic)],
        "heading": [para(S["sec2"], "（１）浮動の画像の結び付いた見出し", float_pic), text[0], text[1]],
        "table_first": [para(S["body"], pic[0]), text[0], table([[cell("問1\u3000架空の問題")]]), cap],
        "deco": [para(S["body"], shape("rect", "none", pid=961)), para(S["body"], shape("rect", "white", pid=962, anchor=True)),
                 text[0]],
        "ellipse_chart": [para(S["body"], shape("ellipse", "none", pid=961)), para(S["body"], chart_drawing(pid=962)), text[0]],
    }[variant]
    return head + body + [para(S["body"], "以上で終わる。")]


def make_figs(path, variant):
    """図形の外の図の決め方の原稿（variant は figs_parts。ALL_DOCS には入れない。tests/test_figure_units.py）。"""
    make_article(path, "図の並びの検証用文書", lambda b: figs_parts(b, variant))


# ----------------------------------------------------------------------------- 浮動配置の図形の中身（修正計画 W1 の手順 5）
def float_group(pics, shapes, boxes, pid, cx, cy, **pos):
    """浮動配置のグループ図形（wpg:wgp）。pics は [(rid, cx, cy)]（グループが直接持つ画像）、shapes は [(prst, fill)]（文字のない
    図形）、boxes は中身の XML の一覧（テキストボックス 1 つずつ。キャプション・文字）。"""
    inner = ""
    for k, (rid, w, h) in enumerate(pics):
        inner += (f'<pic:pic><pic:nvPicPr><pic:cNvPr id="{pid + k + 1}" name="図"/><pic:cNvPicPr/></pic:nvPicPr>'
                  f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
                  f'<pic:spPr><a:xfrm><a:off x="{k * 1500000}" y="0"/><a:ext cx="{w}" cy="{h}"/></a:xfrm>'
                  '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>')
    inner += "".join(wsp(p, f, x=k * 800000) for k, (p, f) in enumerate(shapes))
    inner += "".join(f'<wps:wsp><wps:cNvSpPr/><wps:spPr><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></wps:spPr>'
                     f'<wps:txbx><w:txbxContent>{x}</w:txbxContent></wps:txbx><wps:bodyPr/></wps:wsp>' for x in boxes)
    graphic = (f'<a:graphic><a:graphicData uri="{WPG_URI}"><wpg:wgp><wpg:cNvGrpSpPr/><wpg:grpSpPr/>{inner}</wpg:wgp>'
               '</a:graphicData></a:graphic>')
    fallback = ("<w:pict><v:group>" + "".join(f"<v:shape><v:textbox><w:txbxContent>{x}</w:txbxContent></v:textbox></v:shape>"
                                             for x in boxes) + "</v:group></w:pict>")
    return anchored(graphic, fallback, pid, cx, cy, **pos)


def float_figs_parts(b: Builder, variant):
    """浮動配置の図形の中身の組み方（修正計画 W1 の 2.3 の B・2.4）。図形はどれも図の左上がアンカー段落の左上にある（位置は
    機械的に決まる）。variant に「_down」を付けると、図形をアンカー段落から 2 cm 下にずらす（位置を決められない）。

    group: 画像 2 枚・線・白い四角・文字のテキストボックス・図キャプションのテキストボックスをまとめたグループ図形（C002・C004）。
    two_figs: テキストボックスに、画像だけの段落・図1・画像だけの段落・図2。
    two_tables: テキストボックスに、表1（表の上のキャプション）・表・表・表2（表の下のキャプション）。
    table_fig_note: テキストボックスに、キャプションのない表・図1・注の文字（表で組んだ図。注は本文の段落）。
    ambiguous: テキストボックスに、表・表1・表・表2（どの表がどの表キャプションのものか決められない）。
    nocap_group: キャプションのないグループ図形（画像 1 枚と文字のテキストボックス）。
    nocap_textbox: キャプションのないテキストボックスに、文字の段落・表・画像だけの段落。
    anchor_tabcap / anchor_figcap / anchor_image: 図キャプションと画像のテキストボックスを、本文の表キャプション（後ろに表）・
    本文の図キャプション（前に画像）・本文の画像だけの段落（後ろに図キャプション）に結び付ける。
    near_group3 / near_group4: キャプションのないグループ図形（画像 1 枚と文字のテキストボックス）を結び付けた本文の段落の
    3 / 4 要素後ろに、画像のない本文の図キャプション（修正計画 W1 の 2.3 の B6。C029）。
    near_group_empty: near_group3 と同じで、グループ図形を結び付けた段落が空の段落。
    two_figs_above: テキストボックスに、図1・画像だけの段落・図2・画像だけの段落（図キャプションを画像の上に置く図形）。
    nocap_source: キャプションのないグループ図形（画像 1 枚と、文字「点Ｐ」・「資料：…」・引用のある出典の注記のテキストボックス。
    data24 の形）。nocap_label: 同じ形で、「資料：…」が図形の先頭にあり、後ろに別のテキストボックスのラベルの文字が続く。
    two_figs_text: two_figs の後ろに、図の画像に写る文字「線分ＡＢの長さ」（修正計画 W1 の 4.2。図形ごとの行）。
    drawn: 文字の図形（長方形のテキストボックス）だけのグループ図形で、中に文字「ア」「イ」と図キャプション「図1」（Word の図形で
    描いた図。data10・data25 の形。グループは飾りの textgroup）。drawn_free: 同じ形で図キャプションのないもの（飾りの一覧に入る）。
    """
    kind, down = variant.replace("_down", ""), variant.endswith("_down")
    cm = B3_CM
    pos = dict(v=("paragraph", 2 * cm if down else 0), wrap="wrapTopAndBottom")
    im = [b.add_image(f"float_figs_{variant}_{k}.png", png_bytes(f"Float {k}", size=(300, 200))) for k in range(1, 4)]

    def pic(k, pid):
        return para(S["body"], drawing(im[k], 1440000, 960000, pid))

    def bare(text):
        return table([[cell(text)]])

    def tb(inner, pid=1001):
        return textbox(inner, pid, cx=12 * cm, cy=6 * cm, **pos)

    head = [para(S["sec1"], "１．図形の中身"), para(S["body"], "試験（2024）にならい，図形の中身の組み方を確かめる。")]
    anchor = "この段落に図形が結び付いている。本文の段落としての長さを持たせる。"
    fig_box = tb(pic(0, 1002) + para(S["fig_cap"], "図5　図形の中の図"))
    shapes = {
        "group": float_group([(im[0], 1440000, 960000), (im[1], 1440000, 960000)], [("line", "none"), ("rect", "white")],
                             [para(S["body"], "点Ａと点Ｂを結ぶ。"), para(S["fig_cap"], "図1　グループ図形の図")],
                             1001, 12 * cm, 6 * cm, **pos),
        "two_figs": tb(pic(0, 1002) + para(S["fig_cap"], "図1　一つ目の図") + pic(1, 1003)
                       + para(S["fig_cap"], "図2　二つ目の図")),
        "two_tables": tb(para(S["tab_cap"], "表1　上のキャプションの表") + bare("上の表の中身") + bare("下の表の中身")
                         + para(S["tab_cap"], "表2　下のキャプションの表")),
        "table_fig_note": tb(bare("問1　架空の問題") + para(S["fig_cap"], "図1　表で組んだ図")
                             + para(S["body"], "注：架空の注である。")),
        "ambiguous": tb(bare("前の表の中身") + para(S["tab_cap"], "表1　一つ目の表") + bare("間の表の中身")
                        + para(S["tab_cap"], "表2　二つ目の表")),
        "nocap_group": float_group([(im[0], 1440000, 960000)], [], [para(S["body"], "点Ｐ")], 1001, 8 * cm, 4 * cm, **pos),
        "nocap_textbox": tb(para(S["body"], "図形の中の説明の文である。") + bare("図形の中の表")
                            + pic(0, 1002)),
        "two_figs_text": tb(pic(0, 1002) + para(S["fig_cap"], "図1　一つ目の図") + pic(1, 1003)
                            + para(S["fig_cap"], "図2　二つ目の図") + para(S["body"], "線分ＡＢの長さ")),
        "drawn": float_group([], [], [para(S["body"], "ア"), para(S["body"], "イ"), para(S["fig_cap"], "図1　図形で描いた図")],
                             1001, 12 * cm, 6 * cm, **pos),
        "drawn_free": float_group([], [], [para(S["body"], "ア"), para(S["body"], "イ")], 1001, 12 * cm, 6 * cm, **pos),
        "two_figs_above": tb(para(S["fig_cap"], "図1　上のキャプションの図") + pic(0, 1002)
                             + para(S["fig_cap"], "図2　二つ目の上のキャプションの図") + pic(1, 1003)),
        "nocap_source": float_group([(im[0], 1440000, 960000)], [],
                                    [para(S["body"], "点Ｐ"),
                                     para(S["body"], "資料：　架空の授業プリントの問い") + para(S["body"], "※試験（2024）を基に筆者作成")],
                                    1001, 8 * cm, 4 * cm, **pos),
        "nocap_label": float_group([(im[0], 1440000, 960000)], [],
                                   [para(S["body"], "資料：　架空の授業プリントの問い"), para(S["body"], "点Ａ"),
                                    para(S["body"], "ラベルの文字：" + "あ" * 40) + para(S["body"], "いろいろ" * 30)],
                                   1001, 8 * cm, 4 * cm, **pos),
    }
    if kind in shapes:
        return head + [para(S["body"], anchor, shapes[kind]), para(S["body"], "以上で終わる。")]
    if kind.startswith("near_group"):
        text = [para(S["body"], f"これは間にある本文の段落{k}である。") for k in range(1, 4)]
        lead = para(S["body"], shapes["nocap_group"]) if kind == "near_group_empty" else para(S["body"], anchor, shapes["nocap_group"])
        return head + [lead] + text[:3 if kind == "near_group4" else 2] + [
            para(S["fig_cap"], "図1　近くの段落の図形の図"), para(S["body"], "以上で終わる。")]
    body_pic = para(S["body"], drawing(im[2], 1440000, 960000, 1011))
    if kind == "anchor_tabcap":
        return head + [para(S["tab_cap"], "表1　本文の表", fig_box), bare("本文の表の中身"),
                       para(S["body"], "以上で終わる。")]
    if kind == "anchor_figcap":
        return head + [body_pic, para(S["fig_cap"], "図1　本文の図", fig_box), para(S["body"], "以上で終わる。")]
    assert kind == "anchor_image", variant
    return head + [para(S["body"], drawing(im[2], 1440000, 960000, 1011), fig_box), para(S["fig_cap"], "図1　本文の図"),
                   para(S["body"], "以上で終わる。")]


def make_float_figs(path, variant):
    """浮動配置の図形の中身の組み方の原稿（variant は float_figs_parts。ALL_DOCS には入れない。tests/test_float_units.py）。"""
    make_article(path, "図形の中身の検証用文書", lambda b: float_figs_parts(b, variant))


# ----------------------------------------------------------------------------- 画像で貼った表・表のセルの図・資料の図（修正計画 W1 の手順 7）
def table_images_parts(b: Builder, variant):
    """画像で貼った表・表のセルの図・資料の図（修正計画 W1 の 2.3 の C・D）の並び。図キャプションは図の下（既定）。variant:

    tab_next: 表キャプション・画像だけの段落（C の (2)）。tab_run: 表キャプション・空の段落・画像だけの段落 2 つ。
    tab_two: 表キャプション・画像・表キャプション・画像。tab_then_fig: 表キャプション・画像・図キャプション（画像は図のもの）。
    tab_not_next: 表キャプション・本文の段落・画像（画像は表のものにしない）。
    tab_group: 本文の段落に、画像 1 枚のグループ図形と、表キャプションだけのテキストボックスが結び付く（C の (1)。図の左上が
    アンカー段落の左上にある）。tab_textbox: テキストボックスに、表キャプション・画像だけの段落・注の文字。
    cell_up: 表のセルに、画像（1 行目）とその下のキャプション（2 行目。キャプションのスタイル）の図1、同じ形でスタイルのない
    キャプションの図2。cell_same: 同じセルに、キャプションと画像。cell_none: キャプションの上のセルに画像がない
    （画像は別の列のセル）。cell_two: 同じセルに図キャプションが 2 つ。cell_above: 図キャプションを図の上に置く原稿
    （本文の図9 の後ろに画像）で、表のセルの 1 行目にキャプション・2 行目に画像。cell_float: 1 列の表の行ごとに、浮動の
    グループ図形（画像 1 枚）を結び付けたキャプションのない段落・同じ形のグループ図形を結び付けた図1 のキャプション・空の段落・
    画像のない図2 のキャプション・グループ図形の段落・図3 のキャプション（data17 の形。図1 は上のセルの画像、キャプションに
    結び付いた画像はキャプションなしのまま、図2 は画像の見つからない図）。
    """
    im = [b.add_image(f"tabimg_{variant}_{k}.png", png_bytes(f"Tab {k}", size=(300, 200))) for k in range(1, 5)]

    def group(k, pid):
        return float_group([(im[k], 1440000, 960000)], [], [], pid, 4 * B3_CM, 3 * B3_CM, v=("paragraph", 0),
                           wrap="wrapTopAndBottom")

    def pic(k, pid):
        return para(S["body"], drawing(im[k], 1440000, 960000, pid))

    cm = B3_CM
    head = [para(S["sec1"], "１．画像の表"), para(S["body"], "試験（2024）にならい，表1に結果を示す。")]
    cap1 = para(S["tab_cap"], "表1\u3000画像で貼った表")
    text = para(S["body"], "これは間にある本文の段落である。")
    pos = dict(v=("paragraph", 0), wrap="wrapTopAndBottom")
    anchor = "この段落に図形が結び付いている。本文の段落としての長さを持たせる。"
    body = {
        "tab_next": [cap1, pic(0, 1001)],
        "tab_run": [cap1, para(S["body"], ""), pic(0, 1001), pic(1, 1002)],
        "tab_two": [cap1, pic(0, 1001), para(S["tab_cap"], "表2\u3000二つ目の画像の表"), pic(1, 1002)],
        "tab_then_fig": [cap1, pic(0, 1001), para(S["fig_cap"], "図1\u3000表ではなく図")],
        "tab_not_next": [cap1, text, pic(0, 1001)],
        "tab_group": [para(S["body"], anchor, float_group([(im[0], 1440000, 960000)], [], [para(S["tab_cap"], "表1\u3000グループの表")],
                                                          1001, 12 * cm, 6 * cm, **pos))],
        "tab_textbox": [para(S["body"], anchor, textbox(para(S["tab_cap"], "表1\u3000図形の中の表") + pic(0, 1002)
                                                        + para(S["body"], "注：画像に写る文字である。"), 1001,
                                                        cx=12 * cm, cy=6 * cm, **pos))],
        "cell_up": [table([[cell([pic(0, 1001)])], [cell(para(S["fig_cap"], "図1\u3000上の画像の図"))]]), text,
                    table([[cell([pic(1, 1002)])], [cell(para(S["body"], "図2：スタイルのないキャプション"))]])],
        "cell_same": [table([[cell([pic(0, 1001), para(S["fig_cap"], "図1\u3000同じセルの図")])]])],
        "cell_none": [table([[cell(para(S["body"], "見出し")), cell([pic(0, 1001)])],
                             [cell(para(S["fig_cap"], "図1\u3000画像のない列の図")), cell("説明")]])],
        "cell_two": [table([[cell([pic(0, 1001), para(S["fig_cap"], "図1\u3000一つ目"), pic(1, 1002),
                                   para(S["fig_cap"], "図2\u3000二つ目")])]])],
        "cell_above": [para(S["fig_cap"], "図9\u3000上のキャプションの図"), pic(2, 1003), text,
                       table([[cell(para(S["fig_cap"], "図1\u3000下の画像の図"))], [cell([pic(0, 1001)])]])],
        "cell_float": [table([[cell(para(S["body"], group(0, 1101)))],
                              [cell(para(S["fig_cap"], group(1, 1201), "図1\u3000上のセルの図"))],
                              [cell(para(S["body"], ""))],
                              [cell(para(S["fig_cap"], "図2\u3000画像の見つからない図"))],
                              [cell(para(S["body"], group(2, 1301)))],
                              [cell(para(S["fig_cap"], "図3\u3000三つ目の図"))]])],
    }[variant]
    return head + body + [para(S["body"], "以上で終わる。")]


def make_table_images(path, variant):
    """画像で貼った表・表のセルの図の原稿（variant は table_images_parts。ALL_DOCS には入れない。tests/test_table_images.py）。"""
    make_article(path, "画像の表の検証用文書", lambda b: table_images_parts(b, variant))


def app_figures_parts(b: Builder, variant):
    """資料の図キャプション（修正計画 W1 の 2.3 の D の「資料」）。英文要旨の後ろに「資料1」の見出しと、variant の並び:

    below: 画像だけの段落・図キャプション（スタイルあり）。after: 図キャプション・画像だけの段落。own: 画像を含む図キャプション。
    run: 画像だけの段落 2 つ・図キャプション。plain: スタイルのない「図1　…」・画像（隣が画像なので図キャプションと推定）。
    none: 画像のない図キャプション。two: 画像・図キャプション・画像・図キャプション。
    """
    im = [b.add_image(f"appfig_{variant}_{k}.png", png_bytes(f"App {k}", size=(300, 200))) for k in range(1, 3)]

    def pic(k, pid):
        return para(S["abs"], drawing(im[k], 1440000, 960000, pid))

    head = [para(S["abs"], "資料1\u3000架空の授業プリント"), para(S["abs"], "資料の本文である。")]
    cap = para(S["fig_cap"], "図1\u3000資料の図")
    return head + {
        "below": [pic(0, 1001), cap],
        "after": [cap, pic(0, 1001)],
        "own": [para(S["fig_cap"], drawing(im[0], 1440000, 960000, 1001), "図1\u3000資料の図")],
        "run": [pic(0, 1001), pic(1, 1002), cap],
        "plain": [pic(0, 1001), para(S["abs"], "図1\u3000スタイルのない資料の図")],
        "none": [cap],
        "two": [pic(0, 1001), cap, pic(1, 1002), para(S["fig_cap"], "図2\u3000二つ目の資料の図")],
    }[variant]


def make_app_figures(path, variant):
    """資料の図キャプションの原稿（variant は app_figures_parts。ALL_DOCS には入れない。tests/test_table_images.py）。"""
    make_article(path, "資料の図の検証用文書", lambda b: [para(S["sec1"], "１．本文"), para(S["body"], "本文の段落である。")],
                 appendix=lambda b: app_figures_parts(b, variant))


# ----------------------------------------------------------------------------- 画像の置き場所の場所の文（修正計画 W1 の 2.8）
def where_parts(b: Builder):
    """画像の置き場所の場所を示す文（structure.text_before・report.slot_where）の原稿の本文。

    章「１．場所の確かめ」の最初に画像だけの段落、本文の段落・空白だけの段落・画像だけの段落、文の中に行内の画像のある段落、
    浮動の画像の結び付いた段落、図キャプションの図（図1）、キャプションのないグループ図形を結び付けた段落（図形の位置は
    アンカー段落の前。図形の中の「点Ｐ」は飛ばす）、付記の見出しの直後の画像だけの段落。
    """
    im = [b.add_image(f"where_{k}.png", png_bytes(f"Where {k}", size=(300, 200))) for k in range(1, 8)]

    def pic(k, pid):
        return drawing(im[k], 1440000, 960000, pid)
    group = float_group([(im[5], 1440000, 960000)], [], [para(S["body"], "点Ｐ")], 1101, 8 * B3_CM, 4 * B3_CM,
                        v=("paragraph", 0), wrap="wrapTopAndBottom")
    return [para(S["sec1"], "１．場所の確かめ"), para(S["body"], pic(0, 1001)),
            para(S["body"], "試験（2024）にならい，画像の場所を確かめる。"), para(S["body"], ""), para(S["body"], pic(1, 1002)),
            para(S["body"], "文の中に", pic(2, 1003), "行内の画像がある段落である。"),
            para(S["body"], "この段落に浮動の画像が結び付いている。", anchored_drawing(im[3], 1440000, 960000, 1004)),
            para(S["body"], pic(4, 1005)), para(S["fig_cap"], "図1　児童Aの記述"),
            para(S["sec1"], "２．図形の場所"), para(S["body"], "図形の前にある本文の段落である。"),
            para(S["body"], "この段落に図形が結び付いている。", group),
            para(S["notes_head"], "付記"), para(S["body"], pic(6, 1007)), para(S["body"], "付記の本文である。")]


def make_where(path):
    """画像の置き場所の場所の文の原稿（where_parts。ALL_DOCS には入れない。tests/test_user_images.py）。"""
    make_article(path, "画像の場所の検証用文書", where_parts)


# ----------------------------------------------------------------------------- sample_outside（本文の外の図形。修正計画の N7）
def make_outside(path):
    """本文の外の段落に結び付いた図形（AI 補完が必要。ALL_DOCS には入れない。tests/test_floats.py）。

    引用文献の 1 件目に図3 の図形（画像と図キャプション。2 cm 下）、2 件目に文字だけの囲み、3 件目の段落の中に行内の画像
    （テキストボックスの外。XML に入らない画像として要対応のまま）。注の段落に表1 の図形（表キャプションと表）。英文要旨の段落に
    文字だけの囲み。英文要旨の後ろの資料の段落に、文字だけの囲み（今までどおり資料の中に出す）。
    """
    b = Builder()
    cm = 360000
    img = b.add_image("outside_fig.png", png_bytes("Outside figure", size=(300, 200)))
    logo = b.add_image("outside_ref.png", png_bytes("Ref", size=(120, 60)))
    fig = textbox(para(S["body"], drawing(img, 1440000, 960000, 831)) + para(S["fig_cap"], "図3　架空の最後のページの図"),
                  830, cx=8 * cm, cy=4 * cm, v=("paragraph", 2 * cm), wrap="wrapTopAndBottom")
    box = textbox(para(S["body"], "問4　架空の補足の問題である。三つの数の和を求めよ。")
                  + para(S["body"], "答えは本文の表で確かめる。"), 832, cx=12 * cm, cy=3 * cm, v=("paragraph", cm),
                  wrap="wrapTopAndBottom")
    tbl = textbox(para(S["tab_cap"], "表1　架空の集計") + table([[cell("区分"), cell("人数")], [cell("一組"), cell("30")]]),
                  833, cx=8 * cm, cy=3 * cm, v=("paragraph", cm), wrap="wrapTopAndBottom")
    abs_box = textbox(para(S["abs"], "Box: a fictional supplementary task for the abstract."), 834, cx=12 * cm, cy=2 * cm,
                      v=("paragraph", cm), wrap="wrapTopAndBottom")
    app_box = textbox(para(S["body"], "資料の囲み：架空のワークシートの問いである。答えを書く。"), 835, cx=12 * cm, cy=2 * cm,
                      wrap="wrapTopAndBottom")
    body = front_ja(b, "本文の外の図形の検証用文書", "―引用文献に結び付いた図―", [("架空大学", "試験　八郎")])
    body += [para(S["sec1"], "１．はじめに"), para(S["body"], "試験（2024）にならい，図3と表1を引用文献の後ろに置いた。"),
             para(S["sec1"], "２．おわりに"), para(S["body"], "以上のように，本文の外に結び付いた図形も本文に出す。"),
             para(S["ref_head"], "引用および参考文献"),
             para(S["ref"], "試験六郎（2024）．「小さな論文」．『架空誌』，第5巻，pp.9-10．", fig),
             para(S["ref"], "試験七郎（2025）．「補足の問題」．『架空誌』，第6巻，pp.11-12．", box),
             para(S["ref"], "試験八郎（2026）．「画像のある文献」", drawing(logo, 600000, 300000, 836), "．『架空誌』，第7巻，pp.13-14．"),
             para(S["fn_head"], "注"), para(S["body"], "1) 架空の注である。", tbl)]
    body += front_en(b, "Shapes Outside the Body", "For Checking", [("Hachiro SHIKEN", "Fictional University")], [])
    body.append(para(S["abs"], "Outside abstract text.", abs_box))
    body += tail(b, appendix=[para(S["abs"], "資料1　架空の授業プリント"), para(S["abs"], "資料の本文である。", app_box)])
    b.save(path, body)


# ----------------------------------------------------------------------------- sample_links*（注・図表へのリンクの規則。修正計画の D2・M5）
def links_parts(b: Builder, bare=False):
    """注・図表へのリンクの規則の境界ケースの本文（章見出しから注の一覧まで）。

    bare が偽なら、注番号が「1)」の書き方の論文（sample_links）: 指数・単位の上付き（「3 cm」＋²、「x²+y²」、「m s」＋上付きの
    「−1」、「f(x²)」）、番号の形がはっきりした注番号（「1)」「1,2)」「1-3)」「註1」「注3」、上付きの「1」＋本文の「)」）、
    本文の「注」＋上付きの「1」、番号だけの上付きの「2」。注の一覧は「1) …」〜「3) …」。
    真なら、注番号が番号だけの上付きの論文（sample_links_bare）: かな・閉じ括弧の後ろの ¹ ²、「4 m」＋²、上付きの「1-3」「1, 2」
    （上付きの直前に「注」の字を置かない）、文の括弧を閉じる直前の上付きの「3」＋本文の「）」（リンクするが、論文の書き方を「1)」の
    書き方にしない）。注の一覧の番号も上付き。
    どちらにも、語の中の「図1」「表1」（地図1・図表1・発表1回目・概念図1・代表1名・付表1）と、リンクする参照（前掲表1・乃至・
    括弧・並び・「図表1と表1」の後ろの表1・「地図1、図2」の図2）、図1・図2（画像あり）、表1（本体あり）を入れる。
    """
    fig1 = b.add_image("links_fig1.png", png_bytes("Links figure 1"))
    fig2 = b.add_image("links_fig2.png", png_bytes("Links figure 2", size=(480, 260)))
    out = [para(S["sec1"], "１．はじめに"), para(S["body"], "試験（2024）にならい，注と図表へのリンクの規則を確かめる。")]
    if not bare:
        out += [
            para(S["body"], "面積は 3 cm", run("2", sup=True), " である", run("1)", sup=True), "。"),
            para(S["body"], "式 x", run("2", sup=True), "+y", run("2", sup=True), " を考える", run("1,2)", sup=True), "。"),
            para(S["body"], "速さの単位は m s", run("\u22121", sup=True), " である", run("1-3)", sup=True), "。"),
            para(S["body"], "架空の補足がある", run("註1", sup=True), "。また", run("注3", sup=True), "も参照。"),
            para(S["body"], "番号の後ろが本文の括弧である", run("1", sup=True), ")。本文の注", run("1", sup=True), "も同じ。"),
            para(S["body"], "関数 f(x", run("2", sup=True), ") は架空の例である。番号だけの", run("2", sup=True), "は注にしない。"),
        ]
    else:
        out += [
            para(S["body"], "これは架空の主張である", run("1", sup=True), "。"),
            para(S["body"], "架空の報告がある（試験, 2024）", run("2", sup=True), "。"),
            para(S["body"], "教室の広さは 4 m", run("2", sup=True), " である。"),
            para(S["body"], "架空の議論がある", run("1-3", sup=True), "。別の議論もある", run("1, 2", sup=True), "。"),
            para(S["body"], "（詳しい架空の説明は後で述べる", run("3", sup=True), "）。"),
        ]
    out += [
        para(S["body"], "地図1と図表1を見る。発表1回目は概念図1で、代表1名が付表1を示した。"),
        para(S["body"], "前掲表1、図1乃至図2、（図1）、図1、2を参照する。"),
        para(S["body"], "図表1と表1を比べる。地図1、図2も見る。地図1、2は架空である。"),
        para(S["body"], drawing(fig1, 2880000, 1800000, 951), jc="center"),
        para(S["fig_cap"], "図1\u3000架空の図"),
        para(S["body"], drawing(fig2, 2880000, 1560000, 952), jc="center"),
        para(S["fig_cap"], "図2\u3000もう一つの架空の図"),
        para(S["tab_cap"], "表1\u3000架空の表"),
        table([[cell("観点"), cell("内容")], [cell("架空"), cell("架空の内容")]]),
        para(S["sec1"], "２．おわりに"),
        para(S["body"], "以上のように，指数や語の中の番号はリンクにしない。"),
        para(S["fn_head"], "注"),
    ]
    notes = ("一つ目の架空の注。", "二つ目の架空の注。", "三つ目の架空の注。")
    if not bare:
        out += [para(S["body"], f"{k}) {text}") for k, text in enumerate(notes, 1)]
    else:
        out += [para(S["body"], run(str(k), sup=True), f" {text}") for k, text in enumerate(notes, 1)]
    return out


def make_links(path, bare=False):
    """注・図表へのリンクの規則の境界ケースの原稿（links_parts。bare なら注番号が番号だけの上付きの論文）。"""
    make_article(path, "リンクの規則の検証用文書" + ("（番号だけの注）" if bare else ""), lambda b: links_parts(b, bare))


def make_links_bare(path):
    """注番号が番号だけの上付きの論文の原稿（make_links の bare=True）。"""
    make_links(path, bare=True)


if __name__ == "__main__":
    out = HERE / "fixtures"
    make_full(out / "sample_full.docx")
    make_edge(out / "sample_edge.docx")
    make_float(out / "sample_float.docx")
    make_notes(out / "sample_notes.docx")
    make_pdfcheck(out / "sample_pdfcheck.docx")
    make_reader(out / "sample_reader.docx")
    make_float_text(out / "sample_float_text.docx")
    make_structure(out / "sample_structure.docx")
    make_b3_cells(out / "sample_b3_cells.docx")
    make_b3_tablefig(out / "sample_b3_tablefig.docx")
    make_b3_place(out / "sample_b3_place.docx")
    make_outside(out / "sample_outside.docx")
    make_links(out / "sample_links.docx")
    make_links_bare(out / "sample_links_bare.docx")
    pdf_done = make_pdfcheck_pdf(out / "sample_pdfcheck.pdf")
    print("written:", out / "sample_full.docx", out / "sample_edge.docx", out / "sample_float.docx",
          out / "sample_notes.docx", out / "sample_pdfcheck.docx", out / "sample_reader.docx",
          out / "sample_float_text.docx", out / "sample_structure.docx", out / "sample_b3_cells.docx",
          out / "sample_b3_tablefig.docx", out / "sample_b3_place.docx", out / "sample_outside.docx",
          out / "sample_links.docx", out / "sample_links_bare.docx",
          out / "sample_pdfcheck.pdf" if pdf_done else "（LibreOffice がないので sample_pdfcheck.pdf は作り直していない）")
    sys.exit(0)
