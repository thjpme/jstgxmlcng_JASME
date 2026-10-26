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
                                   〈w:sdt〉や w:customXml に包まれた表の行・セル、テキストボックスの段落と表）
tests/fixtures/sample_float_text.docx : テキストボックスの中で、画像と文字が同じ段落にある図形（キャプションのある図と、
                                   キャプションのない図形）。位置は機械的に決まる
tests/fixtures/sample_structure.docx : 論文の構造（領域の分け方など）の境界ケース（本文中のテキストボックスにある
                                   「英文要旨」スタイルの段落や「注」だけの段落）
tests/fixtures/sample_b3_cells.docx : 表のセルに画像とキャプションが並ぶ図形（AI なしで図に組める形）。位置は機械的に決まる
tests/fixtures/sample_b3_tablefig.docx : 画像のない図キャプションと、その隣のキャプションのない表（表で組んだ図）
tests/fixtures/sample_b3_place.docx : 位置を決められない図表の仮の置き場所（同じ段落に結び付いた 2 つの図形、空の段落に
                                   結び付いた図形、引用文献の後ろの注）。AI 補完が必要（ALL_DOCS には入れない）

make_article() は小さな論文を作る。テストの中で、境界ケースの docx をその場で作るのにも使う。

内容は架空のもので、実在の論文ではない。
"""
from __future__ import annotations

import copy
import io
import re
import sys
import zipfile
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
     "fn_head": "aff6", "ref_head": "aff8", "ref": "aff9", "fig_cap": "affa", "tab_cap": "affb",
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


def drawing(rid, cx, cy, pid, name="図", anchor=False):
    graphic = (f'<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
               f'<pic:pic><pic:nvPicPr><pic:cNvPr id="{pid}" name="{name}"/><pic:cNvPicPr/></pic:nvPicPr>'
               f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
               f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
               f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic>')
    return (f'<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/>'
            f'<wp:docPr id="{pid}" name="{name}"/>{graphic}</wp:inline></w:drawing></w:r>')


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
def make_pdfcheck(path, published=False):
    """出版版 PDF との照合の検証用。published=True なら、出版社が組版で直した想定の文字にする（PDF を作るため）。"""
    def t(docx_text, pub_text=None):
        return (pub_text if pub_text is not None else docx_text) if published else docx_text

    b = Builder()
    link = b.add_hyperlink("https://example.com/a")
    body = []
    body += front_ja(b, "出版版 PDF との照合の検証用文書", "―全角と半角の違い―", [("架空大学", "試験\u3000四郎")])
    body.append(para(S["sec1"], "１．はじめに"))
    body.append(para(S["body"], t("本研究は架空理論 (Fictional Theory, 以下, FT) に基づく (試験, 2020; 見本, 2021)。",
                                  "本研究は架空理論（Fictional Theory, 以下，FT）に基づく（試験，2020；見本，2021）。")))
    body.append(para(S["body"], t("詳しくは資料の学習指導案を参照されたい。授業は2回行った。",
                                  "詳しくは付録の学習指導案を参照されたい。授業は２回行った。")))
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


ZEN_DIGITS = str.maketrans("0123456789", "０１２３４５６７８９")

# sample_reader の節（見出し, 部品を作る関数）。ケースを足すときは、部品を作る関数を足してここに加える。
# 節の見出しの番号は make_reader が付ける。テストは段落の文字で対象を選ぶ（件数や段落の ID に頼らない）
READER_SECTIONS = [
    ("包まれた表の行とセル", reader_wrapped_rows),
    ("テキストボックスの中の包まれた段落と表", reader_textbox_sdt),
]


def make_reader(path):
    """読み取りの境界ケース。sample_edge は件数で確かめるテストがあるので、新しいケースはこちらに足す。"""
    b = Builder()
    body = []
    body += front_ja(b, "読み取りの検証用文書", "―包まれた要素を読み落とさない―", [("架空大学", "試験\u3000五郎")])
    for k, (heading, section) in enumerate(READER_SECTIONS, 1):
        body.append(para(S["sec1"], f"{str(k).translate(ZEN_DIGITS)}．{heading}"))
        body += section(b)
    body.append(para(S["ref_head"], "引用および参考文献"))
    body.append(para(S["ref"], "試験五郎（2023）．「読み取りの検証」．『架空誌』，第4巻，pp.7-8．"))
    body += front_en(b, "Reading Wrapped Elements", "Checking the Reader", [("Goro SHIKEN", "Fictional University")],
                     ["Reader abstract."])
    body += tail(b)
    b.save(path, body)


# ----------------------------------------------------------------------------- 小さな論文
def endnote_ref(nid):
    """本文の中の、Word の文末脚注の参照。"""
    return f'<w:r><w:rPr><w:rStyle w:val="a9"/></w:rPr><w:endnoteReference w:id="{nid}"/></w:r>'


def endnote(nid, text, *more):
    """Word の文末脚注（Builder.endnotes_extra に足す）。1 段落目は文末脚注の番号と text、more は 2 段落目以降の段落の XML。"""
    first = f'<w:p><w:r><w:rPr><w:rStyle w:val="a9"/></w:rPr><w:endnoteRef/></w:r>{run(text)}</w:p>'
    return f'<w:endnote w:id="{nid}">{first}{"".join(more)}</w:endnote>'


def make_article(path, title, body_parts, endnotes=(), refs=None):
    """題目・著者・本文・引用文献 1 件・英文要旨だけの小さな論文。

    body_parts(b) は本文の段落（章見出しから）の XML の一覧を返す。本文で「試験（2024）」を引用すると、引用文献にリンクされる。
    endnotes は Word の文末脚注の XML（endnote()）の一覧。
    refs(b) は、引用文献 1 件の後ろに足す段落（引用文献の段落など）の XML の一覧を返す（省略すると足さない）。
    """
    b = Builder()
    b.endnotes_extra.extend(endnotes)
    body = []
    body += front_ja(b, title, "―検証用の小さな論文―", [("架空大学", "試験\u3000六郎")])
    body += body_parts(b)
    body.append(para(S["ref_head"], "引用および参考文献"))
    body.append(para(S["ref"], "試験六郎（2024）．「小さな論文」．『架空誌』，第5巻，pp.9-10．"))
    if refs is not None:
        body += refs(b)
    body += front_en(b, "A Small Article", "For Checking", [("Rokuro SHIKEN", "Fictional University")],
                     ["Small article abstract."])
    body += tail(b)
    b.save(path, body)


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


# sample_structure の節（見出し, 部品を作る関数）。ケースを足すときは、部品を作る関数を足してここに加える。
# 節の見出しの番号は make_structure が付ける。テストは段落の文字で対象を選ぶ（件数や段落の ID に頼らない）
STRUCTURE_SECTIONS = [
    ("テキストボックスの中の別の領域のスタイル", structure_textbox_regions),
]


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
    body += tail(b)
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
    （2 つ目の項目、同じ番号の定義の段落を入れた、浮動配置でないテキストボックス）。"other_list" は、2 項目の箇条書きの最後の
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
    elif variant in ("two_lists", "list_heading", "list_image", "list_math", "list_textbox"):
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
    pdf_done = make_pdfcheck_pdf(out / "sample_pdfcheck.pdf")
    print("written:", out / "sample_full.docx", out / "sample_edge.docx", out / "sample_float.docx",
          out / "sample_notes.docx", out / "sample_pdfcheck.docx", out / "sample_reader.docx",
          out / "sample_float_text.docx", out / "sample_structure.docx", out / "sample_b3_cells.docx",
          out / "sample_b3_tablefig.docx", out / "sample_b3_place.docx",
          out / "sample_pdfcheck.pdf" if pdf_done else "（LibreOffice がないので sample_pdfcheck.pdf は作り直していない）")
    sys.exit(0)
