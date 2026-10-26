"""単位 E（注〈Word の文末脚注〉と資料の見出し）の、実装を見ない反例の docx を作る（文字はすべて架空）。

tests/make_fixtures.py の部品（Builder・para・run・front_ja・front_en・tail・textbox・drawing・endnote）を import して使う。
make_fixtures.py 自体は変えない。Word の脚注・文末脚注は Builder.footnotes_extra / endnotes_extra に足す。

使い方: python gen_e.py <出力フォルダ>   （run_e.py からも build(name, path) で呼ぶ）
"""
import sys
from pathlib import Path

REPO = Path("/home/user/jstgxmlcng_JASME")
sys.path.insert(0, str(REPO / "tests"))
import make_fixtures as mf  # noqa: E402

S = mf.S
TRK = 'w:author="試験" w:date="2026-01-01T00:00:00Z"'


# ----------------------------------------------------------------------------- 部品
def fn_ref(nid, custom=None):
    """本文の中の、Word の脚注の参照。custom があれば customMarkFollows の記号（docx の文字）。"""
    if custom:
        return (f'<w:r><w:rPr><w:rStyle w:val="a9"/></w:rPr><w:footnoteReference w:customMarkFollows="1" w:id="{nid}"/>'
                f'<w:t>{custom}</w:t></w:r>')
    return f'<w:r><w:rPr><w:rStyle w:val="a9"/></w:rPr><w:footnoteReference w:id="{nid}"/></w:r>'


def en_ref(nid, custom=None):
    """本文の中の、Word の文末脚注の参照。"""
    if custom:
        return (f'<w:r><w:rPr><w:rStyle w:val="a9"/></w:rPr><w:endnoteReference w:customMarkFollows="1" w:id="{nid}"/>'
                f'<w:t>{custom}</w:t></w:r>')
    return mf.endnote_ref(nid)


def deleted(xml_run, rid=801):
    return f'<w:del w:id="{rid}" {TRK}>{xml_run}</w:del>'


def inserted(xml_run, rid=802):
    return f'<w:ins w:id="{rid}" {TRK}>{xml_run}</w:ins>'


def note_p(mark_tag, text, style=None, extra=""):
    """注の 1 段落目（Word の番号 + 文字）。mark_tag は footnoteRef / endnoteRef。"""
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return (f'<w:p>{ppr}<w:r><w:rPr><w:rStyle w:val="a9"/></w:rPr><w:{mark_tag}/></w:r>'
            f'<w:r><w:t xml:space="preserve"> {mf.escape(text)}</w:t></w:r>{extra}</w:p>')


def plain_p(text):
    sp = ' xml:space="preserve"'
    return f'<w:p><w:r><w:t{sp}>{mf.escape(text)}</w:t></w:r></w:p>'


def footnote(nid, text, *more, extra=""):
    return f'<w:footnote w:id="{nid}">{note_p("footnoteRef", text, "a8", extra)}{"".join(more)}</w:footnote>'


def endnote(nid, text, *more, extra=""):
    return f'<w:endnote w:id="{nid}">{note_p("endnoteRef", text, None, extra)}{"".join(more)}</w:endnote>'


def custom_endnote(nid, mark, text):
    """customMarkFollows の文末脚注の中身（Word の番号の代わりに記号を文字で書く）。"""
    return (f'<w:endnote w:id="{nid}"><w:p><w:r><w:rPr><w:rStyle w:val="a9"/></w:rPr><w:t>{mark}</w:t></w:r>'
            f'<w:r><w:t xml:space="preserve"> {mf.escape(text)}</w:t></w:r></w:p></w:endnote>')


def blank_footnote(nid, spaces):
    return (f'<w:footnote w:id="{nid}"><w:p><w:pPr><w:pStyle w:val="a8"/></w:pPr>'
            f'<w:r><w:t xml:space="preserve">{spaces}</w:t></w:r></w:p></w:footnote>')


def blank_endnote(nid, spaces):
    return f'<w:endnote w:id="{nid}"><w:p><w:r><w:t xml:space="preserve">{spaces}</w:t></w:r></w:p></w:endnote>'


ABSTRACT = ["This fictional abstract describes a classroom study on shapes."]


def article(path, body, footnotes=(), endnotes=(), after_refs=(), abstract=ABSTRACT, appendix=None,
            title_en="A Fictional Study"):
    """和文の小さな論文。body は章見出しからの段落の XML の一覧。after_refs は引用文献 1 件の後ろの段落。"""
    b = mf.Builder()
    b.footnotes_extra.extend(footnotes)
    b.endnotes_extra.extend(endnotes)
    out = []
    out += mf.front_ja(b, "架空の検証用の題目", "―注と資料の確かめ―", [("架空大学", "試験　八郎")])
    out += list(body)
    out.append(mf.para(S["ref_head"], "引用および参考文献"))
    out.append(mf.para(S["ref"], "試験八郎（2023）．「架空の研究」．『架空誌』，第7巻，pp.13-14．"))
    out += list(after_refs)
    out += mf.front_en(b, title_en, "Notes and Appendices", [("Hachiro SHIKEN", "Fictional University")], list(abstract))
    out += mf.tail(b, appendix=appendix)
    b.save(path, out)
    return path


def H1(t):
    return mf.para(S["sec1"], t)


def P(*parts, style="body"):
    return mf.para(S[style], *parts)


# ----------------------------------------------------------------------------- 注（D4）
def n01_endnote_only(path):
    body = [H1("１．はじめに"),
            P("架空の授業で三角形を扱った", en_ref(3), "。"),
            P("以上で本文を終える。")]
    return article(path, body, endnotes=[endnote(3, "文末脚注の一段落目の架空の説明。",
                                                  plain_p("文末脚注の二段落目の架空の補足。"))])


def n02_footnote_only(path):
    body = [H1("１．はじめに"), P("架空の授業で四角形を扱った", fn_ref(5), "。")]
    return article(path, body, footnotes=[footnote(5, "脚注だけの原稿の架空の注。")])


def n03_interleaved(path):
    body = [H1("１．はじめに"),
            P("最初の参照は文末脚注である", en_ref(3), "。"),
            P("次の参照は脚注である", fn_ref(5), "。"),
            P("最後の参照は二つ目の文末脚注である", en_ref(4), "。")]
    return article(path, body, footnotes=[footnote(5, "脚注Ａの架空の文。")],
                   endnotes=[endnote(3, "文末脚注Ｂの架空の文。"), endnote(4, "文末脚注Ｃの架空の文。")])


def n04_collision(path):
    body = [H1("１．はじめに"),
            P("脚注を先に参照する", fn_ref(5), "。"),
            P("同じ番号の文末脚注を後に参照する", en_ref(5), "。")]
    return article(path, body, footnotes=[footnote(5, "番号が重なる脚注の架空の文。")],
                   endnotes=[endnote(5, "番号が重なる文末脚注の架空の文。")])


def n05_collision_rev(path):
    body = [H1("１．はじめに"),
            P("文末脚注を先に参照する", en_ref(5), "。"),
            P("同じ番号の脚注を後に参照する", fn_ref(5), "。")]
    return article(path, body, footnotes=[footnote(5, "後に参照される脚注の架空の文。")],
                   endnotes=[endnote(5, "先に参照される文末脚注の架空の文。")])


def n06_nested(path):
    body = [H1("１．はじめに"), P("脚注だけを本文で参照する", fn_ref(5), "。")]
    return article(path, body,
                   footnotes=[footnote(5, "この脚注の中から文末脚注を参照する", extra=en_ref(7) + mf.run("。"))],
                   endnotes=[endnote(7, "脚注の中から参照される架空の文末脚注。")])


def n07_ref_in_del(path):
    body = [H1("１．はじめに"),
            P("残る参照の付いた文", fn_ref(5), "。"),
            P("削除された参照の付いた文", deleted(fn_ref(6)), "。")]
    return article(path, body, footnotes=[footnote(5, "残る脚注の架空の文。"),
                                          footnote(6, "参照が削除された脚注の架空の文。")])


def n08_ref_in_ins(path):
    body = [H1("１．はじめに"),
            P("残る参照の付いた文", fn_ref(5), "。"),
            P("挿入された参照の付いた文", inserted(fn_ref(6)), "。")]
    return article(path, body, footnotes=[footnote(5, "残る脚注の架空の文。"),
                                          footnote(6, "参照が挿入された脚注の架空の文。")])


def n09_unreferenced(path):
    body = [H1("１．はじめに"), P("参照される文末脚注だけがある", en_ref(3), "。")]
    return article(path, body, footnotes=[footnote(8, "どこからも参照されない脚注の架空の文。")],
                   endnotes=[endnote(3, "参照される文末脚注の架空の文。"),
                             endnote(9, "どこからも参照されない文末脚注の架空の文。")])


def n10_unreferenced_blank(path):
    body = [H1("１．はじめに"), P("参照される脚注だけがある", fn_ref(5), "。")]
    return article(path, body, footnotes=[footnote(5, "参照される脚注の架空の文。"), blank_footnote(8, "　 ")],
                   endnotes=[blank_endnote(9, " 　")])


def n11_blank_in_endnote(path):
    body = [H1("１．はじめに"), P("空白の段落を含む文末脚注を参照する", en_ref(3), "。")]
    return article(path, body, endnotes=[endnote(3, "空白の段落の前の架空の文。", plain_p("　"),
                                                  plain_p("空白の段落の後の架空の文。"))])


def n12_custom_mark(path):
    body = [H1("１．はじめに"),
            P("一つ目の文末脚注", en_ref(3), "。"),
            P("記号で示す文末脚注", en_ref(4, custom="*"), "。"),
            P("三つ目の文末脚注", en_ref(5), "。")]
    return article(path, body, endnotes=[endnote(3, "一つ目の架空の注。"), custom_endnote(4, "*", "記号の架空の注。"),
                                         endnote(5, "三つ目の架空の注。")])


def n13_ref_only_paragraph(path):
    body = [H1("１．はじめに"),
            P("この次の段落には参照だけがある。"),
            P(fn_ref(5)),
            P("参照だけの段落の後の本文。")]
    return article(path, body, footnotes=[footnote(5, "参照だけの段落から参照される架空の脚注。")])


# ----------------------------------------------------------------------------- 資料の見出し（D3）
def _app(heading, style="abs", next_text="問1　架空の式を計算せよ。", next_style=None):
    def build(path):
        body = [H1("１．はじめに"), P("架空の本文。")]
        return article(path, body, appendix=[mf.para(S[style], heading),
                                             mf.para(S[next_style or style], next_text)])
    return build


def a16_two_appendices(path):
    body = [H1("１．はじめに"), P("架空の本文。")]
    return article(path, body, appendix=[mf.para(S["abs"], "資料1　架空の授業プリント"),
                                         mf.para(S["abs"], "一つ目の資料の架空の中身。"),
                                         mf.para(S["abs"], "資料2　架空のワークシート"),
                                         mf.para(S["abs"], "二つ目の資料の架空の中身。")])


JP_IN_ABS = "この段落は英文要旨の中に置かれた架空の和文の説明である。"


def a12_japanese_in_abstract(path, control=False):
    abstract = ["This fictional abstract describes a classroom study on shapes."]
    if not control:
        abstract.append(JP_IN_ABS)
    abstract.append("The fictional results suggest further study.")
    body = [H1("１．はじめに"), P("架空の本文。")]
    return article(path, body, abstract=abstract)


SMALL_JP = "The fictional term kyozai kenkyu (教材研究) is used in this abstract."


def a13_small_japanese(path, control=False):
    abstract = ["This fictional abstract describes a classroom study on shapes."]
    abstract.append("The fictional term kyozai kenkyu is used in this abstract." if control else SMALL_JP)
    body = [H1("１．はじめに"), P("架空の本文。")]
    return article(path, body, abstract=abstract)


def a14_app_after_refs(path, control=False):
    body = [H1("１．はじめに"), P("架空の本文。")]
    after = [] if control else [H1("資料　架空の授業プリント"), P("引用文献の後ろに置いた資料の架空の中身。")]
    return article(path, body, after_refs=after)


# ----------------------------------------------------------------------------- AI の set_role（N6・D3）
def r01_abs_paras(path):
    body = [H1("１．はじめに"), P("架空の本文。")]
    return article(path, body, abstract=["This fictional abstract describes a classroom study on shapes.",
                                         "Worksheet used in the fictional lesson",
                                         "Question one asks pupils to compare two fictional figures."])


def r05_figure(path):
    def build_body(b):
        img = b.add_image("oracle_e_fig.png", mf.png_bytes("Fictional figure", size=(400, 240)))
        cm = 360000
        return [H1("１．はじめに"),
                P("次の図に架空の図形を示す。", mf.textbox(
                    mf.para(S["body"], mf.drawing(img, 1800000, 1080000, 712))
                    + mf.para(S["fig_cap"], "図1　架空の図形"), 711, cx=8 * cm, cy=4 * cm, wrap="wrapTopAndBottom")),
                P("図の後の架空の本文。")]
    b = mf.Builder()
    out = []
    out += mf.front_ja(b, "架空の検証用の題目", "―注と資料の確かめ―", [("架空大学", "試験　八郎")])
    out += build_body(b)
    out.append(mf.para(S["ref_head"], "引用および参考文献"))
    out.append(mf.para(S["ref"], "試験八郎（2023）．「架空の研究」．『架空誌』，第7巻，pp.13-14．"))
    out += mf.front_en(b, "A Fictional Study", "Notes and Appendices", [("Hachiro SHIKEN", "Fictional University")],
                       list(ABSTRACT))
    out += mf.tail(b)
    b.save(path, out)
    return path


def r08_excluded_ref(path):
    body = [H1("１．はじめに"),
            P("残る参照の付いた文", fn_ref(5), "。"),
            P("除外を指定する段落の文", fn_ref(6), "。"),
            P("後に続く架空の本文。")]
    return article(path, body, footnotes=[footnote(5, "残る参照の架空の脚注。"),
                                          footnote(6, "除外された段落から参照される架空の脚注。")])


BUILDERS = {
    "N01": n01_endnote_only, "N02": n02_footnote_only, "N03": n03_interleaved, "N04": n04_collision,
    "N05": n05_collision_rev, "N06": n06_nested, "N07": n07_ref_in_del, "N08": n08_ref_in_ins,
    "N09": n09_unreferenced, "N10": n10_unreferenced_blank, "N11": n11_blank_in_endnote, "N12": n12_custom_mark,
    "N13": n13_ref_only_paragraph,
    "A01": _app("資料（授業プリント）"),
    "A02": _app("資料Ⅰ　授業プリント"),
    "A03": _app("資料Ⅱ（ワークシート）"),
    "A04": _app("付録①　調査票", style="body"),
    "A05": _app("資料1-2　授業の記録"),
    "A06": _app("【資料1】", next_style="body"),
    "A07": _app("Appendix A", next_text="Question 1. Compute the fictional expression."),
    "A08": _app("資料"),
    "A09": _app("資料を配布した。", next_text="架空の配布物の説明である。"),
    "A10": _app("資料-1　授業プリント"),
    "A11": _app("授業で用いたワークシート", style="sec1", next_text="ワークシートの架空の問いを示す。", next_style="body"),
    "A11b": _app("架空の調査の記録", style="sec2", next_text="調査の架空の手順を示す。", next_style="body"),
    "A12": a12_japanese_in_abstract,
    "A12c": lambda p: a12_japanese_in_abstract(p, control=True),
    "A13": a13_small_japanese,
    "A13c": lambda p: a13_small_japanese(p, control=True),
    "A14": a14_app_after_refs,
    "A14c": lambda p: a14_app_after_refs(p, control=True),
    "A15": _app("資料　授業プリント"),
    "A17": _app("資料1　調査票", style="body"),
    "A16": a16_two_appendices,
    "R01": r01_abs_paras,
    "R05": r05_figure,
    "R08": r08_excluded_ref,
}


def build(name, path):
    return BUILDERS[name](Path(path))


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out.mkdir(parents=True, exist_ok=True)
    for name in BUILDERS:
        build(name, out / f"{name}.docx")
    print(f"{len(BUILDERS)} 件を {out} に作った")
