"""テスト用の docx を、JASME テンプレートのスタイル定義を使って生成する。

  python tests/make_fixtures.py

tests/fixtures/sample_full.docx : 本番に近い論文（数式・図表・注・文献・URL・意図的なスタイル違反を含む）
tests/fixtures/sample_edge.docx : 読み取りの境界ケース（Word の脚注、自動番号、隠し文字、変更履歴、
                                   テキストボックス、記号フォント、フィールドのハイパーリンクなど）

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


def textbox(inner, pid, cx=2000000, cy=500000):
    """浮動配置のテキストボックス（Word と同じく、DrawingML と VML の代替の両方に同じ中身を入れる）。"""
    return ('<w:r><mc:AlternateContent><mc:Choice Requires="wps"><w:drawing><wp:anchor distT="0" distB="0" distL="0" '
            'distR="0" simplePos="0" relativeHeight="1" behindDoc="0" locked="0" layoutInCell="1" allowOverlap="1">'
            '<wp:simplePos x="0" y="0"/><wp:positionH relativeFrom="column"><wp:posOffset>0</wp:posOffset></wp:positionH>'
            '<wp:positionV relativeFrom="paragraph"><wp:posOffset>0</wp:posOffset></wp:positionV>'
            f'<wp:extent cx="{cx}" cy="{cy}"/><wp:wrapNone/><wp:docPr id="{pid}" name="テキスト ボックス"/>'
            '<a:graphic><a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">'
            f'<wps:wsp><wps:txbx><w:txbxContent>{inner}</w:txbxContent></wps:txbx><wps:bodyPr/></wps:wsp>'
            '</a:graphicData></a:graphic></wp:anchor></w:drawing></mc:Choice><mc:Fallback><w:pict><v:shape><v:textbox>'
            f'<w:txbxContent>{inner}</w:txbxContent></v:textbox></v:shape></w:pict></mc:Fallback></mc:AlternateContent></w:r>')


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


if __name__ == "__main__":
    out = HERE / "fixtures"
    make_full(out / "sample_full.docx")
    make_edge(out / "sample_edge.docx")
    print("written:", out / "sample_full.docx", out / "sample_edge.docx")
    sys.exit(0)
