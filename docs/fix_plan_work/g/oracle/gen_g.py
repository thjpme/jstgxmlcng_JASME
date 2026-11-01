"""単位 G（D5・U8・U3・N8）の反例の docx と期待（cases.json）を作る。実装（ooxml・docx_reader・fidelity・pdfdocx・emit）は読まずに、
docs/FIX_PLAN.md の G の節と付録の D5・U3・U8 だけから期待を決めた。文字はすべて架空。

  python gen_g.py        # cases/*.docx と cases.json を作る

tests/make_fixtures.py の部品（Builder・para・run・cell・table・textbox・drawing・sdt・custom_xml・deleted・front_ja・front_en・
tail・make_pdfcheck）を import して使う（make_fixtures.py は変えない）。足りない部品（段落記号の w:del・w:moveFrom・w:vanish、
スタイルの w:vanish・specVanish、docDefaults の vanish、ランの中の w:br、w:trPr/w:del・w:tcPr/w:cellDel、bookmark の境界）は
この中に書く。
"""
from __future__ import annotations

import copy
import json
import re
import sys
import zipfile
from pathlib import Path

from lxml import etree

HERE = Path(__file__).resolve().parent
REPO = Path("/home/user/jstgxmlcng_JASME")
sys.path.insert(0, str(REPO / "tests"))
import make_fixtures as mf  # noqa: E402

S = mf.S
W = mf.W
CASES = HERE / "cases"
BR = "⏎"          # w:t の中のこの記号は、生成の最後に w:br（同じランの中の改行）に置き換える
DATE = 'w:author="試験" w:date="2026-01-01T00:00:00Z"'
_ids = iter(range(70000, 79999))


def nid():
    return next(_ids)


# ============================================================================= 足りない部品
def mark(kind):
    """段落記号のラン書式（w:pPr/w:rPr）の中身。del・moveFrom は変更履歴、vanish・spec はスタイル区切り（隠した段落記号）。"""
    if kind == "del":
        return f'<w:del w:id="{nid()}" {DATE}/>'
    if kind == "moveFrom":
        return f'<w:moveFrom w:id="{nid()}" {DATE}/>'
    if kind == "vanish":
        return "<w:vanish/>"
    if kind == "spec":
        return "<w:vanish/><w:specVanish/>"
    raise ValueError(kind)


def pm(style, *parts, m="del", num_id=None):
    """段落記号に印（m）のある段落。num_id があれば自動番号の段落。"""
    ppr = f'<w:pStyle w:val="{style}"/>' if style else ""
    if num_id:
        ppr += f'<w:numPr><w:ilvl w:val="0"/><w:numId w:val="{num_id}"/></w:numPr>'
    ppr += f"<w:rPr>{mark(m)}</w:rPr>"
    body = "".join(p if p.startswith("<") else mf.run(p) for p in parts if p)
    return f"<w:p><w:pPr>{ppr}</w:pPr>{body}</w:p>"


def item(style, *parts, num_id=7):
    return mf.list_item(style, *parts, num_id=num_id)


def hrun(text, rstyle=None, vanish=None, spec=False, b=False):
    """隠し文字の部品。vanish は None（指定なし）・True（w:vanish）・False（w:vanish w:val="0"）。"""
    rpr = ""
    if rstyle:
        rpr += f'<w:rStyle w:val="{rstyle}"/>'
    if b:
        rpr += "<w:b/>"
    if vanish is True:
        rpr += "<w:vanish/>"
    elif vanish is False:
        rpr += '<w:vanish w:val="0"/>'
    if spec:
        rpr += "<w:specVanish/>"
    rpr = f"<w:rPr>{rpr}</w:rPr>" if rpr else ""
    return f'<w:r>{rpr}<w:t xml:space="preserve">{mf.escape(text)}</w:t></w:r>'


def deleted_text(text):
    return mf.deleted(mf.run(text))


def cstyle(sid, name, based=None, vanish=None, b=False):
    """文字スタイル（styles.xml に足す）。"""
    rpr = ("<w:b/>" if b else "") + ({True: "<w:vanish/>", False: '<w:vanish w:val="0"/>'}.get(vanish, ""))
    bo = f'<w:basedOn w:val="{based}"/>' if based else '<w:basedOn w:val="a0"/>'
    return (f'<w:style w:type="character" w:customStyle="1" w:styleId="{sid}"><w:name w:val="{name}"/>{bo}'
            f'<w:rPr>{rpr}</w:rPr></w:style>')


def pstyle(sid, name, based="af5", vanish=None):
    """段落スタイル（styles.xml に足す）。"""
    rpr = {True: "<w:vanish/>", False: '<w:vanish w:val="0"/>'}.get(vanish, "")
    return (f'<w:style w:type="paragraph" w:customStyle="1" w:styleId="{sid}"><w:name w:val="{name}"/>'
            f'<w:basedOn w:val="{based}"/><w:qFormat/><w:rPr>{rpr}</w:rPr></w:style>')


def table_rows(rows_xml, ncol, header=False):
    """行の XML をそのまま並べた表（header なら 1 行目を見出し行にする）。"""
    if header and rows_xml:
        rows_xml = [rows_xml[0].replace("<w:tr>", "<w:tr><w:trPr><w:tblHeader/></w:trPr>", 1)] + list(rows_xml[1:])
    return mf.table_of_rows(rows_xml, ncol)


def del_row(*texts, pmark=False, keep=False):
    """変更履歴で削除された表の行（w:trPr/w:del）。keep なら中身の文字は削除にしない（印だけの行）。
    pmark ならセルの段落記号も削除にする（Word が行を削除したときの形）。"""
    cells = []
    for t in texts:
        content = mf.run(t) if keep else deleted_text(t)
        ppr = f'<w:pStyle w:val="{S["body"]}"/>' + (f"<w:rPr>{mark('del')}</w:rPr>" if pmark else "")
        cells.append(f'<w:tc><w:tcPr><w:tcW w:w="2000" w:type="dxa"/></w:tcPr><w:p><w:pPr>{ppr}</w:pPr>{content}</w:p></w:tc>')
    return f'<w:tr><w:trPr><w:del w:id="{nid()}" {DATE}/></w:trPr>{"".join(cells)}</w:tr>'


def del_cell(text):
    """変更履歴で削除されたセル（w:tcPr/w:cellDel）。中身の文字も削除。"""
    return (f'<w:tc><w:tcPr><w:tcW w:w="2000" w:type="dxa"/><w:cellDel w:id="{nid()}" {DATE}/></w:tcPr>'
            f'<w:p><w:pPr><w:pStyle w:val="{S["body"]}"/></w:pPr>{deleted_text(text)}</w:p></w:tc>')


def bookmark(name):
    i = nid()
    return f'<w:bookmarkStart w:id="{i}" w:name="{name}"/><w:bookmarkEnd w:id="{i}"/>'


def fn_two(fid, first, second, first_mark=None, second_mark=None):
    """2 段落（second が None なら 1 段落）の Word の脚注。段落記号に印を付けられる。"""
    def ppr(m):
        return f'<w:pPr><w:pStyle w:val="a8"/>{f"<w:rPr>{mark(m)}</w:rPr>" if m else ""}</w:pPr>'
    out = f'<w:footnote w:id="{fid}"><w:p>{ppr(first_mark)}{mf._note_first("footnoteRef", first, "")}</w:p>'
    if second is not None:
        out += f"<w:p>{ppr(second_mark)}{mf.run(second)}</w:p>"
    return out + "</w:footnote>"


class GBuilder(mf.Builder):
    """スタイルの追加・docDefaults と標準スタイルの vanish・w:t の中の改行を、保存の後で書き込む。"""

    def __init__(self, styles_extra=(), doc_vanish=False, normal_vanish=False):
        super().__init__()
        self.styles_extra = list(styles_extra)
        self.doc_vanish = doc_vanish
        self.normal_vanish = normal_vanish

    def save(self, out, body_xml_parts):
        tmp = Path(str(out) + ".tmp")
        super().save(tmp, body_xml_parts)
        with zipfile.ZipFile(tmp) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
            for it in zin.infolist():
                data = zin.read(it.filename)
                if it.filename in ("word/document.xml", "word/footnotes.xml"):
                    s = data.decode("utf-8")
                    s = s.replace(BR, '</w:t><w:br/><w:t xml:space="preserve">')
                    data = s.encode("utf-8")
                elif it.filename == "word/styles.xml":
                    s = data.decode("utf-8")
                    if self.doc_vanish:
                        s = s.replace("<w:rPrDefault><w:rPr>", "<w:rPrDefault><w:rPr><w:vanish/>", 1)
                    if self.normal_vanish:
                        s, n = re.subn(r'(<w:style w:type="paragraph" w:default="1" w:styleId="a">.*?<w:rPr>)',
                                       r"\1<w:vanish/>", s, count=1, flags=re.S)
                        assert n == 1
                    s = s.replace("</w:styles>", "".join(self.styles_extra) + "</w:styles>")
                    data = s.encode("utf-8")
                zout.writestr(it, data)
        tmp.unlink()


def article(path, body_fn, *, title="段落と文字の検証用文書", footnotes=(), refs=(), abstract=("Oracle abstract.",),
            last_abstract=None, builder=None):
    """題目・著者・本文・引用文献・英文要旨の小さな論文。last_abstract は英文要旨の最後の段落の XML（本文の最後の w:p）。"""
    b = builder or GBuilder()
    b.footnotes_extra.extend(footnotes)
    body = []
    body += mf.front_ja(b, title, "―架空の検証―", [("架空大学", "検証　七海")])
    body += body_fn(b)
    body.append(mf.para(S["ref_head"], "引用および参考文献"))
    body.append(mf.para(S["ref"], "検証七海（2025）．「架空の検証の方法」．『架空誌』，第8巻，pp.3-4．"))
    body += [r if r.startswith("<") else mf.para(S["ref"], r) for r in refs]
    body += mf.front_en(b, "An Oracle Article", "For Checking G", [("Nanami KENSHO", "Fictional University")],
                        list(abstract))
    if last_abstract:
        body.append(last_abstract)
    body += mf.tail(b)
    b.save(path, body)


def png(b, name, label):
    return b.add_image(name, mf.png_bytes(label, size=(400, 240)))


# ============================================================================= ケース
CASE_LIST = []


def case(cid, title, checks, route="docx", twin=None):
    def deco(fn):
        CASE_LIST.append({"id": cid, "title": title, "checks": checks, "route": route, "make": fn, "twin": twin})
        return fn
    return deco


def ex(check, level="exact", **kw):
    return dict(check=check, level=level, **kw)


H1 = lambda t: mf.para(S["sec1"], t)  # noqa: E731
P = lambda *t: mf.para(S["body"], *t)  # noqa: E731
APPROVE = ["承諾", "反映"]                        # 10 章の「承諾できず 2 段落のまま」の警告の言葉（どちらか）
BREAK = ["改行"]


# ---------------------------------------------------------------- D5
@case("d5_two", "本文の 2 段落の段落記号の削除（つながる。ID は前の段落、後は欠番）", [
    ex("p_exact", text="甲の段落の前半であり，甲の段落の後半である。"),
    ex("p_absent", text="甲の段落の前半であり，"),
    ex("p_absent", text="甲の段落の後半である。"),
    ex("id_gap", text="甲の段落の前半であり，甲の段落の後半である。", next="乙の段落はそのまま残る。", gap=2),
    ex("no_ch10", keys=["承諾"]),
])
def d5_two(path):
    article(path, lambda b: [H1("１．段落記号の削除"), pm(S["body"], "甲の段落の前半であり，"),
                             P("甲の段落の後半である。"), P("乙の段落はそのまま残る。")])


@case("d5_chain3", "3 段落の連鎖（1 段落になる。ID は最初の段落、後の 2 つは欠番）", [
    ex("p_exact", text="丙の一つ目，丙の二つ目，丙の三つ目。"),
    ex("p_absent", text="丙の三つ目。"),
    ex("id_gap", text="丙の一つ目，丙の二つ目，丙の三つ目。", next="丁の段落。", gap=3),
])
def d5_chain3(path):
    article(path, lambda b: [H1("１．連鎖"), pm(S["body"], "丙の一つ目，"), pm(S["body"], "丙の二つ目，"),
                             P("丙の三つ目。"), P("丁の段落。")])


@case("d5_prev_empty", "前の段落が空（文字ごと削除した節見出し）: 後の段落の書式（本文）になる。ID は前の段落", [
    ex("p_exact", text="戊の段落の本文である。"),
    ex("not_title", text="戊の段落の本文である。"),
    ex("id_gap", text="戊の段落の本文である。", next="己の段落。", gap=2),
    ex("decision", level="either", keys=["段落記号", "つな", "結合", "続"], text="戊の段落の本文である。", alts=[True, False]),
])
def d5_prev_empty(path):
    article(path, lambda b: [H1("１．はじめに"), pm(S["sec2"], deleted_text("（1）消した見出し")),
                             P("戊の段落の本文である。"), P("己の段落。")])


@case("d5_heading_first", "節見出し + 本文: 前の段落（見出し）の書式のまま。pStyle が違うので 4 章の判断に記録", [
    ex("title_exact", text="（1）見出しの前半と見出しの後半"),
    ex("p_absent", text="見出しの後半"),
    ex("decision", keys=["段落記号", "つな", "結合", "続"], text="（1）見出しの前半と"),
])
def d5_heading_first(path):
    article(path, lambda b: [H1("１．はじめに"), pm(S["sec2"], "（1）見出しの前半と"), P("見出しの後半"),
                             P("庚の本文。")])


@case("d5_body_first", "本文 + 節見出し（fix_plan_repro_tests の逆向き）: 本文の <p> になり、見出しは消える。4 章の判断", [
    ex("p_exact", text="辛の前半の文と（2）辛の後半の見出し"),
    ex("no_title", text="（2）辛の後半の見出し"),
    ex("decision", keys=["段落記号", "つな", "結合", "続"], text="辛の前半の文と"),
])
def d5_body_first(path):
    article(path, lambda b: [H1("１．はじめに"), pm(S["body"], "辛の前半の文と"),
                             mf.para(S["sec2"], "（2）辛の後半の見出し"), P("壬の本文。")])


@case("d5_autonum", "自動番号の段落の連鎖: 連鎖の最後で 1 回だけ番号を数える（文字ごと消した項目の次も同じ番号）", [
    ex("p_exact_in", text="甲項目の前半，甲項目の後半。"),
    ex("label", text="甲項目の前半，甲項目の後半。", label="1."),
    ex("label", text="乙項目。", label="2."),
    ex("label", text="丙項目。", label="3."),
])
def d5_autonum(path):
    article(path, lambda b: [H1("１．番号"), P("次の項目を挙げる。"),
                             pm(S["body"], "甲項目の前半，", num_id=7), item(S["body"], "甲項目の後半。"),
                             item(S["body"], "乙項目。"),
                             pm(S["body"], deleted_text("消した項目。"), num_id=7), item(S["body"], "丙項目。"),
                             P("以上の項目である。")])


@case("d5_bookmark", "段落の間にブックマーク（飛ばしてつなぐ）", [
    ex("p_exact", text="癸の前半，癸の後半。"),
    ex("id_gap", text="癸の前半，癸の後半。", next="癸の次の段落。", gap=2),
])
def d5_bookmark(path):
    article(path, lambda b: [H1("１．ブックマーク"), pm(S["body"], "癸の前半，"), bookmark("_gOracle1"),
                             P("癸の後半。"), P("癸の次の段落。")])


@case("d5_movefrom", "段落記号の w:moveFrom（削除と同じくつなぐ）", [
    ex("p_exact", text="子の前半，子の後半。"),
    ex("p_absent", text="子の後半。"),
])
def d5_movefrom(path):
    article(path, lambda b: [H1("１．移動"), pm(S["body"], "子の前半，", m="moveFrom"), P("子の後半。"),
                             P("子の次の段落。")])


@case("d5_vanish_mark", "段落記号の w:vanish（スタイル区切り）はつながない。警告もない", [
    ex("p_exact", text="丑の前半の見出し風"),
    ex("p_exact", text="丑の後半の本文。"),
    ex("p_exact", text="寅の前半の見出し風"),
    ex("p_exact", text="寅の後半の本文。"),
    ex("no_ch10", keys=["承諾"]),
])
def d5_vanish_mark(path):
    article(path, lambda b: [H1("１．スタイル区切り"), pm(S["body"], "丑の前半の見出し風", m="vanish"),
                             P("丑の後半の本文。"), pm(S["body"], "寅の前半の見出し風", m="spec"), P("寅の後半の本文。")])


@case("d5_sdt_boundary", "sdt・customXml の境界ではつながず、10 章に「承諾できず」の警告", [
    ex("p_exact", text="卯のSDTの中の最後，"), ex("p_exact", text="卯のSDTの後。"),
    ex("p_exact", text="辰のSDTの前，"), ex("p_exact", text="辰のSDTの中。"),
    ex("p_exact", text="巳のXMLの中の最後，"), ex("p_exact", text="巳のXMLの後。"),
    ex("p_exact", text="午のXMLの前，"), ex("p_exact", text="午のXMLの中。"),
    ex("ch10", keys=APPROVE, text="卯のSDTの中の最後，"), ex("ch10", keys=APPROVE, text="辰のSDTの前，"),
    ex("ch10", keys=APPROVE, text="巳のXMLの中の最後，"), ex("ch10", keys=APPROVE, text="午のXMLの前，"),
])
def d5_sdt_boundary(path):
    article(path, lambda b: [H1("１．境界"), mf.sdt(pm(S["body"], "卯のSDTの中の最後，")), P("卯のSDTの後。"),
                             pm(S["body"], "辰のSDTの前，"), mf.sdt(P("辰のSDTの中。")),
                             mf.custom_xml(pm(S["body"], "巳のXMLの中の最後，"), "part"), P("巳のXMLの後。"),
                             pm(S["body"], "午のXMLの前，"), mf.custom_xml(P("午のXMLの中。"), "part"),
                             P("境界の後の段落。")])


@case("d5_before_table", "表の直前の段落（表題）の段落記号の削除: つながず、表題のまま。10 章に警告", [
    ex("table_caption", caption="表1　未の表の表題"),
    ex("ch10", keys=APPROVE, text="表1　未の表の表題"),
])
def d5_before_table(path):
    article(path, lambda b: [H1("１．表"), P("表1に未の表を示す。"), pm(S["tab_cap"], "表1　未の表の表題"),
                             mf.table([[mf.cell("項目"), mf.cell("値")], [mf.cell("未の一"), mf.cell("未の二")]]),
                             P("表の後の段落。")])


@case("d5_cell", "セルの中: 途中の段落はつながる（<break/> なし）、最後の段落はつながず警告", [
    ex("cell_exact", text="申のセルの前半，申のセルの後半。", breaks=0),
    ex("cell_exact", text="酉のセルの一つ目。酉のセルの最後。", breaks=1),
    ex("ch10", keys=APPROVE, text="酉のセルの最後。"),
])
def d5_cell(path):
    return article(path, lambda b: [
        H1("１．セル"), P("表1にセルの例を示す。"), mf.para(S["tab_cap"], "表1　セルの段落の表"),
        mf.table([[mf.cell("左"), mf.cell("右")],
                  [mf.cell([pm(S["body"], "申のセルの前半，"), P("申のセルの後半。")]),
                   mf.cell([P("酉のセルの一つ目。"), pm(S["body"], "酉のセルの最後。")])]]),
        P("表の後の段落。")])


@case("d5_textbox", "テキストボックス: アンカーが後の段落でも 1 段落、中での連鎖、中の最後の段落はつながず警告", [
    ex("p_exact", text="図1は戌の図である。前半，後半の説明。"),
    ex("fig_caption", caption="図1　戌の図の表題の前半と後半"),
    ex("fig_caption", caption="図2　亥の図の表題"),
    ex("ch10", keys=APPROVE, text="図2　亥の図の表題"),
])
def d5_textbox(path):
    def body(b):
        i1, i2 = png(b, "g_tb1.png", "Oracle figure 1"), png(b, "g_tb2.png", "Oracle figure 2")
        tb1 = mf.textbox(P(mf.drawing(i1, 1800000, 1100000, 812, name="図"))
                         + pm(S["fig_cap"], "図1　戌の図の表題の前半") + mf.para(S["fig_cap"], "と後半"),
                         811, cy=1500000)
        tb2 = mf.textbox(P(mf.drawing(i2, 1800000, 1100000, 814, name="図"))
                         + pm(S["fig_cap"], "図2　亥の図の表題"), 813, cy=1500000)
        return [H1("１．図"), pm(S["body"], "図1は戌の図である。前半，"), P("後半の説明。", tb1),
                P("図2は亥の図である。", tb2), P("図の後の段落。")]
    article(path, body)


@case("d5_note", "脚注: 1 段落目の段落記号の削除はつながる。注の最後の段落はつながず警告", [
    ex("fn_paras", text="乾の注の前半と乾の注の後半。", n=1),
    ex("fn_paras", text="坤の注の最後。", n=1),
    ex("ch10", keys=APPROVE, text="坤の注の最後。"),
])
def d5_note(path):
    fns = [fn_two(41, "乾の注の前半と", "乾の注の後半。", first_mark="del"),
           fn_two(42, "坤の注の最後。", None, first_mark="del")]
    article(path, lambda b: [H1("１．注"), P("注の付いた文", mf.footnote_ref(41), "と別の注", mf.footnote_ref(42), "。")],
            footnotes=fns)


@case("d5_body_last", "本文の最後の段落（英文要旨の最後）の段落記号の削除: つながず警告", [
    ex("p_exact_in", text="The last oracle paragraph."),
    ex("ch10", keys=APPROVE, text="The last oracle paragraph."),
])
def d5_body_last(path):
    article(path, lambda b: [H1("１．最後"), P("本文の段落。")],
            last_abstract=pm(S["abs"], "The last oracle paragraph."))


# ---------------------------------------------------------------- U8
U8_STYLES = [
    mf_c for mf_c in (
        cstyle("gHid", "検証隠し", vanish=True),
        cstyle("gPlainC", "検証太字", b=True),
        pstyle("gHidP", "検証隠し段落", vanish=True),
        cstyle("gHidB", "検証隠し基", vanish=True),
        cstyle("gDerOff", "検証派生戻す", based="gHidB", vanish=False),
        cstyle("gDerInh", "検証派生継ぐ", based="gHidB", b=True),
        cstyle("gDerOn", "検証派生隠す", based="gHidB", vanish=True),
        pstyle("gPHidB", "検証段落隠し基", vanish=True),
        pstyle("gPDerOff", "検証段落派生戻す", based="gPHidB", vanish=False),
        pstyle("gPDerOn", "検証段落派生隠す", based="gPHidB", vanish=True),
        pstyle("gPDerInh", "検証段落派生継ぐ", based="gPHidB"),
        pstyle("gNoVan", "検証既定戻し", vanish=False),
    )]


@case("u8_char", "直接の w:vanish と文字スタイルの vanish（どちらも隠す。6 章に載る）", [
    ex("p_exact", text="見える文字の甲との後。"),
    ex("text_absent", text="〔直接に隠した甲〕"), ex("text_absent", text="〔文字スタイルで隠した乙〕"),
    ex("hidden_listed", text="〔直接に隠した甲〕"), ex("hidden_listed", text="〔文字スタイルで隠した乙〕"),
])
def u8_char(path):
    article(path, lambda b: [H1("１．隠し文字"), P("見える文字の甲", hrun("〔直接に隠した甲〕", vanish=True), "と",
                                                   hrun("〔文字スタイルで隠した乙〕", rstyle="gHid"), "の後。")],
            builder=GBuilder(U8_STYLES))


@case("u8_para", "段落スタイルの vanish: 段落全体が消える。文字スタイルの vanish とのトグル・直接の val=0 は見える", [
    ex("text_absent", text="段落スタイルで隠した段落の文字。"),
    ex("hidden_listed", text="段落スタイルで隠した段落の文字。"),
    ex("p_exact", text="トグルで見える丙直接の指定で見える丁重ねて見える戊"),
    ex("text_absent", text="〔隠れる部分〕"), ex("text_absent", text="〔文字スタイルが無指定で隠れる〕"),
    ex("p_exact", text="前後の見える段落。"),
])
def u8_para(path):
    article(path, lambda b: [
        H1("１．段落スタイル"), P("前後の見える段落。"),
        mf.para("gHidP", "段落スタイルで隠した段落の文字。"),
        mf.para("gHidP", "〔隠れる部分〕", hrun("トグルで見える丙", rstyle="gHid"), hrun("直接の指定で見える丁", vanish=False),
                hrun("〔文字スタイルが無指定で隠れる〕", rstyle="gPlainC"),
                hrun("重ねて見える戊", rstyle="gHid", vanish=False)),
        P("後ろの段落。")], builder=GBuilder(U8_STYLES))


@case("u8_basedon", "basedOn の派生: vanish を最初に指定しているスタイル（いちばん派生した側）の値（連鎖の中で反転しない）", [
    ex("p_exact", text="己一派生で戻して見える。"),
    ex("text_absent", text="〔基で隠す〕"), ex("text_absent", text="〔継いで隠す〕"), ex("text_absent", text="〔派生も隠す〕"),
    ex("p_exact", text="段落の派生で戻して見える文。"),
    ex("text_absent", text="〔段落の派生も隠す文〕"),
    ex("text_absent", text="〔段落の派生が継いで隠す文〕"),
    ex("p_exact", text="派生段落と文字のトグルで見える"),
    ex("text_absent", text="〔派生段落で隠れる〕"),
])
def u8_basedon(path):
    article(path, lambda b: [
        H1("１．派生"),
        P("己一", hrun("〔基で隠す〕", rstyle="gHidB"), hrun("派生で戻して見える", rstyle="gDerOff"),
          hrun("〔継いで隠す〕", rstyle="gDerInh"), hrun("〔派生も隠す〕", rstyle="gDerOn"), "。"),
        mf.para("gPDerOff", "段落の派生で戻して見える文。"),
        mf.para("gPDerOn", "〔段落の派生も隠す文〕"),
        mf.para("gPDerInh", "〔段落の派生が継いで隠す文〕"),
        mf.para("gPDerOn", "〔派生段落で隠れる〕", hrun("派生段落と文字のトグルで見える", rstyle="gHidB")),
        P("派生の後の段落。")], builder=GBuilder(U8_STYLES))


U8_DOCDEF_BODY = lambda b: [  # noqa: E731
    H1("１．既定の書式"), P("既定の書式でも見える本文。"), mf.para("gNoVan", "〔既定で隠れる段落〕"),
    P("既定の後の本文", hrun("と直接に隠す文字", vanish=True), "。"),
    mf.table([[mf.cell("表の左"), mf.cell("表の右")]]), P("表の後の本文。")]


@case("u8_docdef_twin", "（比べる相手）docDefaults・標準スタイルに vanish のない同じ文書", [
    ex("p_exact", text="〔既定で隠れる段落〕"),
])
def u8_docdef_twin(path):
    article(path, U8_DOCDEF_BODY, builder=GBuilder(U8_STYLES))


@case("u8_docdef", "docDefaults の vanish を標準スタイル（段落スタイル）の vanish で打ち消す: 本文は見える。val=0 の段落スタイルは隠れる", [
    ex("text_absent", text="〔既定で隠れる段落〕"),
    ex("same_as_twin", ignore=["既定で隠れる段落"]),
    ex("p_exact", text="既定の後の本文。"),
], twin="u8_docdef_twin")
def u8_docdef(path):
    article(path, U8_DOCDEF_BODY, builder=GBuilder(U8_STYLES, doc_vanish=True, normal_vanish=True))


@case("u8_spec", "ランの specVanish（隠す）", [
    ex("p_exact", text="庚の文字の後。"),
    ex("text_absent", text="〔特別に隠す〕"),
])
def u8_spec(path):
    article(path, lambda b: [H1("１．特別"), P("庚の文字", hrun("〔特別に隠す〕", spec=True), "の後。")],
            builder=GBuilder(U8_STYLES))


@case("u8_br_sym", "隠し文字の中の w:br・w:sym・w:noBreakHyphen（どれも出力しない。6 章の書き方はどちらか）", [
    ex("p_exact", text="辛の文字の後。"),
    ex("p_exact", text="壬の文字の後。"),
    ex("text_absent", text="〔隠Ａ〕"), ex("text_absent", text="〔隠Ｃ〕"),
    ex("hidden_has_br", level="either", text="〔隠Ａ〕", alts=[True, False]),
])
def u8_br_sym(path):
    hid = ('<w:r><w:rPr><w:vanish/></w:rPr><w:t>〔隠Ａ〕</w:t><w:br/><w:sym w:font="Symbol" w:char="F062"/>'
           '<w:noBreakHyphen/><w:t>〔隠Ｂ〕</w:t></w:r>')
    hid2 = '<w:r><w:rPr><w:rStyle w:val="gHid"/></w:rPr><w:t>〔隠Ｃ〕</w:t><w:br/><w:sym w:font="Symbol" w:char="F067"/></w:r>'
    article(path, lambda b: [H1("１．隠した改行"), P("辛の文字", hid, "の後。"), P("壬の文字", hid2, "の後。")],
            builder=GBuilder(U8_STYLES))


# ---------------------------------------------------------------- U3
def bold_br_run(a, c):
    return f'<w:r><w:rPr><w:b/></w:rPr><w:t>{a}</w:t><w:br/><w:t>{c}</w:t></w:r>'


@case("u3_cell", "セルの中の w:br は <break/> を補う（\\n は残す）。見出し行・太字の中・太字の間・セルの末尾も。リンクの中は今のまま", [
    ex("cell_break", text="見出しの一行目\n見出しの二行目", tag="th_or_td"),
    ex("cell_break", text="セルの一行目\nセルの二行目"),
    ex("cell_break", text="太字の前\n太字の後"),
    ex("cell_break", text="太字の甲\n太字の乙"),
    ex("cell_break_prefix", text="末尾で改行\n"),
    ex("link_no_break", text="リンクの前\nリンクの後"),
    ex("ch10", level="either", keys=BREAK, text="セルの一行目", alts=[True, False]),
])
def u3_cell(path):
    def body(b):
        link = b.add_hyperlink("https://example.org/oracle-g")
        rows = [
            mf.tr(mf.cell(f"見出しの一行目{BR}見出しの二行目"), mf.cell("見出しの右")),
            mf.tr(mf.cell(f"セルの一行目{BR}セルの二行目"),
                  mf.cell(f'<w:p><w:pPr><w:pStyle w:val="{S["body"]}"/></w:pPr>{bold_br_run("太字の前", "太字の後")}</w:p>')),
            mf.tr(mf.cell(f'<w:p><w:pPr><w:pStyle w:val="{S["body"]}"/></w:pPr>{mf.run("太字の甲", b=True)}<w:r><w:br/></w:r>'
                          f'{mf.run("太字の乙", b=True)}</w:p>'),
                  mf.cell(f'<w:p><w:pPr><w:pStyle w:val="{S["body"]}"/></w:pPr><w:hyperlink r:id="{link}">'
                          f'{mf.run(f"リンクの前{BR}リンクの後")}</w:hyperlink></w:p>')),
            mf.tr(mf.cell([f'<w:p><w:pPr><w:pStyle w:val="{S["body"]}"/></w:pPr><w:r><w:t>末尾で改行</w:t><w:br/></w:r></w:p>',
                           P("次の段落")]), mf.cell("普通のセル")),
        ]
        return [H1("１．セルの改行"), P("表1にセルの改行を示す。"), mf.para(S["tab_cap"], "表1　改行のあるセル"),
                table_rows(rows, 2, header=True), P("表の後の段落。")]
    article(path, body)


@case("u3_body", "本文・見出しの w:br は文字のまま（<break/> なし）。10 章に一覧。本文は要対応・要確認の知らせにしない", [
    ex("no_break_in", text="２．見出しの\n改行", tag="title"),
    ex("no_break_in", text="本文の一行目\n本文の二行目。", tag="p"),
    ex("ch10", keys=BREAK, text="本文の一行目"),
    ex("ch10", keys=BREAK, text="２．見出しの"),
    ex("no_action", keys=["改行"]),
])
def u3_body(path):
    article(path, lambda b: [H1("１．はじめに"), P("改行のない段落。"), H1(f"２．見出しの{BR}改行"),
                             P(f"本文の一行目{BR}本文の二行目。")])


@case("u3_title_ref", "題目・引用文献の w:br は文字のまま。10 章に一覧し、知らせ（Action）にする", [
    ex("no_break_in", text="改行を含む\n題目の検証", tag="article-title"),
    ex("no_break_in", text="改行のある\n文献", tag="mixed-citation", contains=True),
    ex("ch10", keys=BREAK, text="改行を含む"),
    ex("ch10", keys=BREAK, text="改行のある"),
    ex("action", keys=["改行"]),
])
def u3_title_ref(path):
    article(path, lambda b: [H1("１．はじめに"), P("題目と文献に改行がある。")],
            title=f"改行を含む{BR}題目の検証",
            refs=[f"検証八雲（2024）．「改行のある{BR}文献」．『架空誌』，第6巻，pp.1-2．"])


# ---------------------------------------------------------------- N8
@case("n8_rows", "削除された空の行は消えて記録される。削除の印があっても文字の残る行は残る", [
    ex("table_rows", caption="表1　削除された行の表",
       rows=[["区分", "内容"], ["残る行", "残る内容"], ["印だけの行", "文字は残る"], ["最後の行", "最後の内容"]]),
    ex("report_line", any_of=[["削除", "表の行"], ["削除された行"], ["行を読み飛ば"], ["削除", "行を"]]),
])
def n8_rows(path):
    rows = [mf.tr("区分", "内容"), mf.tr("残る行", "残る内容"), del_row("消える行", "消える内容"),
            del_row("印だけの行", "文字は残る", keep=True), del_row("段落記号も消える行", "その内容", pmark=True),
            mf.tr("最後の行", "最後の内容")]
    article(path, lambda b: [H1("１．削除された行"), P("表1に削除された行のある表を示す。"),
                             mf.para(S["tab_cap"], "表1　削除された行の表"), table_rows(rows, 2),
                             P("表の後の段落。")])


@case("n8_celldel", "削除されたセル（w:cellDel）: セルを消すか空のセルのままか（どちらか）。ほかのセルの文字は残る", [
    ex("table_has", caption="表1　削除されたセルの表", texts=["左", "右", "残るセル", "下の右"]),
    ex("celldel", level="either", caption="表1　削除されたセルの表", alts=["removed", "empty"]),
])
def n8_celldel(path):
    rows = [mf.tr("左", "右"), f'<w:tr>{mf.cell("残るセル")}{del_cell("消えるセル")}</w:tr>', mf.tr("下の左", "下の右")]
    article(path, lambda b: [H1("１．削除されたセル"), P("表1に削除されたセルのある表を示す。"),
                             mf.para(S["tab_cap"], "表1　削除されたセルの表"), table_rows(rows, 2),
                             P("表の後の段落。")])


# ---------------------------------------------------------------- ルート2（sample_pdfcheck.pdf と組み合わせる）
PUB = "詳しくは付録の学習指導案を参照されたい。授業は２回行った。"
ORIG = "詳しくは資料の学習指導案を参照されたい。授業は2回行った。"


def pdfcheck_split(path, first, second):
    """make_pdfcheck の docx の、ORIG の段落を、段落記号を削除した 2 段落（first + second）に分ける。"""
    tmp = Path(str(path) + ".base.docx")
    mf.make_pdfcheck(tmp)
    with zipfile.ZipFile(tmp) as zin, zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zout:
        for it in zin.infolist():
            data = zin.read(it.filename)
            if it.filename == "word/document.xml":
                root = etree.fromstring(data)
                ps = [p for p in root.iter(f"{{{W}}}p") if "".join(t.text or "" for t in p.iter(f"{{{W}}}t")) == ORIG]
                assert len(ps) == 1
                p = ps[0]
                p2 = copy.deepcopy(p)
                for q, text in ((p, first), (p2, second)):
                    ts = list(q.iter(f"{{{W}}}t"))
                    ts[0].text = text
                    for t in ts[1:]:
                        t.getparent().remove(t)
                ppr = p.find(f"{{{W}}}pPr")
                rpr = etree.SubElement(ppr, f"{{{W}}}rPr")
                d = etree.SubElement(rpr, f"{{{W}}}del")
                d.set(f"{{{W}}}id", str(nid()))
                d.set(f"{{{W}}}author", "試験")
                d.set(f"{{{W}}}date", "2026-01-01T00:00:00Z")
                p.addnext(p2)
                data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
            zout.writestr(it, data)
    tmp.unlink()


@case("r2_join", "ルート2: 段落記号の削除でつないだ段落を PDF に合わせて直す。直した docx も 2 つの w:p と印のまま", [
    ex("p_exact", text=PUB),
    ex("p_absent", text="授業は２回行った。"),
    ex("fixed_docx", first_head="詳しくは", joined=[PUB]),
], route="pdf")
def r2_join(path):
    pdfcheck_split(path, "詳しくは資料の学習指導案を参照されたい。", "授業は2回行った。")


@case("r2_boundary", "ルート2: つないだ境目に PDF の文字（。）がある。足すか直さずに 13 章に出すか（どちらか）。段落は 1 つ", [
    ex("p_one_of", texts=[PUB, "詳しくは付録の学習指導案を参照されたい授業は２回行った。"]),
    ex("p_absent", text="授業は２回行った。"),
    ex("fixed_docx", first_head="詳しくは", joined=[PUB, "詳しくは付録の学習指導案を参照されたい授業は２回行った。"]),
], route="pdf")
def r2_boundary(path):
    pdfcheck_split(path, "詳しくは資料の学習指導案を参照されたい", "授業は2回行った。")


def main():
    CASES.mkdir(exist_ok=True)
    out = []
    for c in CASE_LIST:
        path = CASES / f"{c['id']}.docx"
        c["make"](path)
        d = {k: v for k, v in c.items() if k != "make"}
        d["docx"] = str(path)
        out.append(d)
    (HERE / "cases.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(out)} 件")


if __name__ == "__main__":
    main()
