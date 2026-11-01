"""docx の読み取り: 中間表現の文字列が、独立に取り出した docx の文字列と一致すること。"""
import pytest

from conftest import ALL_DOCS, EDGE, FLOAT, FLOAT_TEXT, FULL, PLACE, READER
from jasme_jats.docx_reader import read_docx
from jasme_jats.fidelity import source_texts
from jasme_jats.model import Para, Table
from jasme_jats.omml import math_plain, omml_to_mathml


def atoms_text(p):
    out = []
    for a in p.atoms:
        if a.kind == "text":
            out.append(a.text)
        elif a.kind == "math":
            out.append(math_plain(omml_to_mathml(a.math, a.display)[0]))
    return "".join(out)


def read_paragraphs(doc):
    """読み取った段落すべて（本文・表・テキストボックスと、Word の脚注・文末脚注）。"""
    yield from doc.all_paragraphs()
    for notes in (doc.footnotes, doc.endnotes):
        for paras in notes.values():
            yield from paras


@pytest.mark.parametrize("path", ALL_DOCS + [FLOAT, FLOAT_TEXT, PLACE], ids=lambda p: p.name)
def test_reader_matches_canonical(path):
    doc = read_docx(path)
    # 検証側（不変性チェック）と同じく、本文・脚注・文末脚注のすべての w:p を数える
    canon = source_texts(path)
    paras = list(read_paragraphs(doc))
    assert paras
    for p in paras:
        assert atoms_text(p) == canon[p.src], p.src
    # 逆向き: 文字のある段落は、すべて 1 回だけ読まれている（読み落とすと、不変性チェックで「出力漏れ」になる）
    srcs = [p.src for p in paras]
    read = set(srcs)
    assert len(srcs) == len(read), sorted(s for s in read if srcs.count(s) > 1)
    assert [(pid, text) for pid, text in canon.items() if text and pid not in read] == []


def table_with(doc, text):
    """セルに text の段落がある表（テキストボックスの中の表を含む）。"""
    def tables(blocks):
        for b in blocks:
            if isinstance(b, Table):
                yield b
                for r in b.rows:
                    for c in r.cells:
                        yield from tables(c.blocks)
    found = [t for t in tables(doc.blocks) if any(p.text_only() == text for p in t.paragraphs())]
    assert len(found) == 1, text
    return found[0]


def cell_texts(t):
    return [["".join(p.text_only() for p in c.blocks if isinstance(p, Para)) for c in r.cells] for r in t.rows]


@pytest.mark.parametrize("wrapped, rows", [
    # 行をコンテンツコントロール（w:sdt）に包む
    ("SDTで包んだ行", [["区分", "内容"], ["前", "SDTの行の前"], ["包んだ行", "SDTで包んだ行"], ["後", "SDTの行の後"]]),
    # 行を w:customXml に包む
    ("XMLで包んだ行", [["区分", "内容"], ["前", "XMLの行の前"], ["包んだ行", "XMLで包んだ行"], ["後", "XMLの行の後"]]),
    # 行の中のセルを w:customXml・w:sdt に包む
    ("XMLで包んだセル", [["左", "中1", "中2", "右"], ["セルの左", "XMLで包んだセル", "SDTで包んだセル", "セルの右"]]),
    # 入れ子の w:sdt（Word の繰り返しセクション）と、w:sdt の中の w:customXml に包んだ行
    ("入れ子のSDTの1行目", [["区分", "内容"], ["入れ子1", "入れ子のSDTの1行目"], ["入れ子2", "入れ子のSDTの2行目"],
                      ["入れ子3", "XMLを包んだSDTの行"], ["後", "入れ子の行の後"]]),
    # テキストボックスの中で w:sdt に包んだ表
    ("テキストボックスのSDTの表", [["観点", "内容"], ["包んだ表", "テキストボックスのSDTの表"]]),
], ids=["sdt-row", "customXml-row", "wrapped-cells", "nested-sdt-rows", "textbox-sdt-table"])
def test_wrapped_table_rows_and_cells(wrapped, rows):
    """w:sdt・w:customXml に包まれた行・セルも、前後の行・セルと文書の順に読む。"""
    t = table_with(read_docx(READER), wrapped)
    assert len(t.rows) == len(rows)
    assert cell_texts(t) == rows


def test_textbox_paragraphs_inside_sdt():
    """テキストボックスの中で w:sdt・w:customXml に包まれた段落も、テキストボックスの段落として読む。"""
    doc = read_docx(READER)
    paras = {p.text_only(): p for p in doc.all_paragraphs()}
    image_para = next(p for p in doc.all_paragraphs() for a in p.atoms
                      if a.kind == "image" and a.image.target == "word/media/reader_tb.png")
    cap = paras["図1\u3000コンテンツコントロールに包んだキャプション"]
    assert image_para.in_textbox and cap.in_textbox
    assert cap.float_id and cap.float_id == image_para.float_id
    # w:customXml に包んだ表キャプションと、w:sdt に包んだ表は、同じ図形の中身になる
    tcap = paras["表5\u3000テキストボックスの中の包まれた表"]
    t = table_with(doc, "テキストボックスのSDTの表")
    assert tcap.in_textbox and tcap.float_id and tcap.float_id == t.float_id != cap.float_id


def test_edge_cases():
    doc = read_docx(EDGE)
    texts = {p.src: p.text_only() for p in doc.all_paragraphs()}
    joined = "\n".join(texts.values())
    # 隠し文字と削除された変更履歴は出力しない。挿入は出力する
    assert "（隠し文字）" not in joined
    assert "削除済み" not in joined
    assert "挿入済み" in joined
    assert doc.hidden_text and doc.hidden_text[0][1] == "（隠し文字）"
    assert doc.tracked_changes == 2
    # 記号フォントの α、改行
    assert "記号α" in joined
    assert "改行\nの後" in joined
    # テキストボックスの中身は 1 回だけ読む（mc:Fallback を二重に数えない）
    tb = [p.text_only() for p in doc.all_paragraphs() if p.in_textbox]
    assert tb.count("図1　テキストボックス内のキャプション") == 1
    # テキストボックスの中の表も読む
    assert "問1　架空の問題文である。" in joined and "根拠を示す" in joined
    # テキストボックスの中の画像は、テキストボックスの段落の画像として 1 回だけ読む（外側の図形の画像にしない）
    tbimg = [p.in_textbox for p in doc.all_paragraphs() for a in p.atoms
             if a.kind == "image" and a.image.target == "word/media/tbfig.png"]
    assert tbimg == [True]
    assert [i.target for i in doc.images].count("word/media/tbfig.png") == 1
    # フィールドのハイパーリンク
    hrefs = {a.href for p in doc.all_paragraphs() for a in p.atoms if a.kind == "text" and a.href}
    assert "https://example.net/field" in hrefs
    assert "https://example.com/a?b=1&c=2" in hrefs
    # Word の脚注
    assert "5" in doc.footnotes


def test_images_and_math_detected():
    doc = read_docx(FULL)
    assert [i.target for i in doc.images] == ["word/media/fig1.png", "word/media/fig2.png", "word/media/eq1.png"]
    displays = [a for p in doc.all_paragraphs() for a in p.atoms if a.kind == "math" and a.display]
    assert len(displays) == 1


def test_textboxes_are_recorded(tmp_path):
    """テキストボックス（w:txbxContent）ごとの TextBox（修正計画の D1）: 浮動配置（wp:anchor）・行内（wp:inline）・VML（pt の大きさ、
    position:absolute の有無、pt 以外の単位は読めない）・グループ図形の中（拡大率を掛けた幅）。中の段落・表・表のセルの段落に
    textbox_id が付き、入れ子の内側の段落は外側の ID を継ぐ。"""
    import make_fixtures as mf
    S, cm = mf.S, 360000
    group = ('<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="7200000" cy="1800000"/>'
             '<wp:docPr id="951" name="グループ"/><a:graphic><a:graphicData '
             'uri="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup"><wpg:wgp><wpg:cNvGrpSpPr/>'
             '<wpg:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="7200000" cy="1800000"/><a:chOff x="0" y="0"/>'
             '<a:chExt cx="3600000" cy="900000"/></a:xfrm></wpg:grpSpPr>'
             '<wps:wsp><wps:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="360000" cy="180000"/></a:xfrm></wps:spPr>'
             f'<wps:txbx><w:txbxContent>{mf.para(S["body"], "P")}</w:txbxContent></wps:txbx><wps:bodyPr/></wps:wsp>'
             '</wpg:wgp></a:graphicData></a:graphic></wp:inline></w:drawing></w:r>')
    inner = mf.textbox(mf.para(S["body"], "内側の札"), 953, cx=2 * cm, cy=cm)
    nested = mf.para(S["body"], "外側の一つ目。") + mf.para(S["body"], "外側の二つ目。", inner)
    tbl = mf.table([[mf.cell("セルの文字")]])

    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"),
                mf.para(S["body"], "浮動配置。", mf.textbox(mf.para(S["body"], "浮動配置の囲み"), 941, cx=12 * cm, cy=2 * cm)),
                mf.para(S["body"], "行内。", mf.textbox_inline(mf.para(S["body"], "行内の囲み"), 942, cx=10 * cm, cy=cm)),
                mf.para(S["body"], "VML。", mf.vml_textbox(mf.para(S["body"], "VML の囲み"), width="300pt", height="72pt")),
                mf.para(S["body"], "位置指定。", mf.vml_textbox(mf.para(S["body"], "位置を指定した囲み"), absolute=True)),
                mf.para(S["body"], "単位。", mf.vml_textbox(mf.para(S["body"], "インチの囲み"), width="3in", height="1in")),
                mf.para(S["body"], "グループ。", group),
                mf.para(S["body"], "入れ子。", mf.textbox(nested, 952, cx=12 * cm, cy=3 * cm)),
                mf.para(S["body"], "表。", mf.vml_textbox(tbl + mf.para(S["body"], "表の後ろ")))]
    path = tmp_path / "boxes.docx"
    mf.make_article(path, "テキストボックスの読み取りの検証用文書", parts)
    doc = read_docx(path)
    assert not hasattr(doc, "textbox_excluded")
    paras = {p.text_only(): p for p in doc.all_paragraphs()}
    boxes = {tb.xid: tb for tb in doc.textboxes}

    def box(text):
        return boxes[paras[text].textbox_id]
    fl = box("浮動配置の囲み")
    assert (fl.source, fl.inline, fl.absolute, fl.group) == ("wps", False, False, False)
    assert fl.float_id == paras["浮動配置の囲み"].float_id != "" and fl.anchor_src == paras["浮動配置。"].src
    assert round(fl.width_cm, 2) == 12.0 and round(fl.height_cm, 2) == 2.0
    il = box("行内の囲み")
    assert (il.inline, il.float_id, round(il.width_cm, 2)) == (True, "", 10.0)
    vml = box("VML の囲み")
    assert (vml.source, vml.inline, vml.absolute) == ("vml", True, False)
    assert round(vml.width_cm, 2) == round(300 / 72 * 2.54, 2) and round(vml.height_cm, 2) == 2.54
    ab = box("位置を指定した囲み")
    assert (ab.inline, ab.absolute) == (False, True)
    assert box("インチの囲み").width_cm is None and box("インチの囲み").height_cm is None   # pt 以外の単位は読めない
    gr = box("P")
    assert gr.group and gr.inline and round(gr.width_cm, 2) == 2.0 and round(gr.height_cm, 2) == 1.0   # 拡大率 2 倍
    # 入れ子の内側の段落は、外側のテキストボックスの ID を継ぐ（内側の TextBox は作らない）
    outer = paras["外側の一つ目。"].textbox_id
    assert paras["内側の札"].textbox_id == paras["外側の二つ目。"].textbox_id == outer
    assert len(doc.textboxes) == 8 and outer in boxes
    # テキストボックスの中の表と、そのセルの段落にも付く。テキストボックスの外の段落には付かない
    t = table_with(doc, "セルの文字")
    assert t.textbox_id == paras["セルの文字"].textbox_id == paras["表の後ろ"].textbox_id != ""
    assert paras["表。"].textbox_id == "" and paras["浮動配置。"].textbox_id == ""
    assert [tb.xid for tb in doc.textboxes] == [f"x{k}" for k in range(1, 9)]
