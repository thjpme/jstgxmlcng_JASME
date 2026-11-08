"""docx の読み取り: 中間表現の文字列が、独立に取り出した docx の文字列と一致すること。

読み取りの文字ポリシー（修正計画の G）: 段落記号の削除でつながる段落（ooxml.joined_paragraphs）、スタイル・既定の書式の隠し文字
（ooxml.HiddenRule）、変更履歴で削除された表の行（docx_reader.Reader.read_table）も、ここで確かめる（sample_reader.docx と、
XML の文字列で作る小さな例）。
"""
import pytest
from lxml import etree

import make_fixtures as mf
from conftest import ALL_DOCS, EDGE, FLOAT, FLOAT_TEXT, FULL, PLACE, READER
from jasme_jats.docx_reader import read_docx
from jasme_jats.fidelity import source_texts
from jasme_jats.model import Para, Table
from jasme_jats.omml import math_plain, omml_to_mathml
from jasme_jats.ooxml import (NO_RULE, DocxPackage, HiddenRule, W_NS, canonical_text, canonical_texts, joined_paragraphs,
                              paragraph_ids, paragraph_mark_deleted, unjoined_deleted_marks, w)

PARTS = (("word/document.xml", "d"), ("word/footnotes.xml", "f"), ("word/endnotes.xml", "e"))


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
    # 検証側（不変性チェック）と同じく、本文・脚注・文末脚注のすべての w:p を数える。段落記号の削除でつないだ段落は、連鎖の
    # 最初の段落の ID に連鎖の文字を連結したもの（ooxml.canonical_texts。後ろの段落の ID は欠番）
    pkg = DocxPackage(path)
    rule = HiddenRule(pkg.xml("word/styles.xml"))
    canon, later = {}, set()
    for part, prefix in PARTS:
        root = pkg.xml(part)
        if root is None:
            continue
        canon.update(canonical_texts(root, prefix, rule))
        ids = paragraph_ids(root, prefix)
        later |= {ids[q] for c in joined_paragraphs(root).values() for q in c[1:]}
    assert canon == source_texts(path)          # 不変性チェックの docx 側の文字と同じ
    paras = list(read_paragraphs(doc))
    assert paras
    for p in paras:
        assert atoms_text(p) == canon[p.src], p.src
    # 逆向き: 文字のある段落は、すべて 1 回だけ読まれている（読み落とすと、不変性チェックで「出力漏れ」になる）
    srcs = [p.src for p in paras]
    read = set(srcs)
    assert len(srcs) == len(read), sorted(s for s in read if srcs.count(s) > 1)
    assert [(pid, text) for pid, text in canon.items() if text and pid not in read] == []
    # つないだ段落の後ろの段落の ID は、読み取りの段落にも、検証の文字にもない
    assert not later & read and not later & set(canon)
    if path == READER:
        assert later and {s for _, srcs in doc.joined for s in srcs[1:]} == later


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


# ----------------------------------------------------------------------------- 読み取りの文字ポリシー（修正計画の G）
def wp_ids(path, part="word/document.xml", prefix="d"):
    """docx の w:p ごとの文字（つながずに w:p ごと。ooxml.canonical_text）→ 段落 ID（文字が同じ w:p は最初のもの）。"""
    pkg = DocxPackage(path)
    rule = HiddenRule(pkg.xml("word/styles.xml"))
    out = {}
    for p, pid in paragraph_ids(pkg.xml(part), prefix).items():
        out.setdefault(canonical_text(p, rule), pid)
    return out


@pytest.mark.parametrize("text, parts, style", [
    # 本文＋本文
    ("段落記号を削除した前半の文と，次の段落の後半の文がつながる。", ["段落記号を削除した前半の文と，", "次の段落の後半の文がつながる。"],
     mf.S["body"]),
    # 文字ごと削除した節見出し＋本文: 前の段落が空なので、後ろの段落の書式（本文）。ID は前の段落のもの
    ("見出しを削除した後ろの本文である。", [None, "見出しを削除した後ろの本文である。"], mf.S["body"]),
    # 節見出し＋本文: 前の段落の書式（節見出し）。本文＋節見出し: 前の段落の書式（本文）
    ("（2）見出しの前半と続いた本文の後半", ["（2）見出しの前半と", "続いた本文の後半"], mf.S["sec2"]),
    ("本文の後ろに（3）続いた見出し", ["本文の後ろに", "（3）続いた見出し"], mf.S["body"]),
    # 3 段落の連鎖、段落記号の移動（w:moveFrom）、段落の間のしおり（w:bookmarkStart・End は飛ばす）
    ("連鎖の一つ目，連鎖の二つ目，連鎖の三つ目。", ["連鎖の一つ目，", "連鎖の二つ目，", "連鎖の三つ目。"], mf.S["body"]),
    ("移動の印の前半，移動の印の後半。", ["移動の印の前半，", "移動の印の後半。"], mf.S["body"]),
    ("しおりをはさむ前半，しおりをはさむ後半。", ["しおりをはさむ前半，", "しおりをはさむ後半。"], mf.S["body"]),
    # 表のセルの中、テキストボックスの中（キャプションの 2 段落）
    ("セルの前半とセルの後半。", ["セルの前半と", "セルの後半。"], mf.S["body"]),
    ("図3　テキストボックスの中でつないだ表題", ["図3　テキストボックスの中で", "つないだ表題"], mf.S["fig_cap"]),
], ids=["body-body", "deleted-heading", "heading-body", "body-heading", "chain3", "moveFrom", "bookmark", "cell", "textbox"])
def test_deleted_paragraph_marks_join_paragraphs(text, parts, style):
    """段落記号が変更履歴で削除された段落は、Word で承諾した状態と同じく、次の段落とつないで 1 段落として読む（修正計画の D5）。
    ID は連鎖の最初の段落のもので、後ろの段落の ID は欠番。書式は、前の段落が空なら後ろの段落、そうでなければ前の段落のもの。"""
    doc = read_docx(READER)
    paras = list(read_paragraphs(doc))
    found = [p for p in paras if p.text_only() == text]
    assert len(found) == 1
    p = found[0]
    ids = wp_ids(READER)
    later = [ids[t] for t in parts[1:]]
    first = ids[parts[0]] if parts[0] is not None else f"d{int(later[0][1:]) - 1}"
    assert p.src == first and (first, [first] + later) in doc.joined
    assert not {q.src for q in paras} & set(later)
    assert p.style_id == style
    assert not any(q.text_only() in parts[1:] for q in paras if q is not p)       # 後ろの段落だけの段落はない


def test_unjoinable_deleted_marks_are_warned():
    """つなげない段落記号の削除（次が表・コンテンツコントロール・カスタム XML、コンテンツコントロール・セル・テキストボックスの
    最後）は、段落を分けたまま読み、10 章の警告に段落の ID と理由を出す（連鎖の最後の段落なら、ID は連鎖の最初の段落のもの）。
    文字のない段落と、段落記号の隠し文字（スタイル区切り）は警告しない。"""
    doc = read_docx(READER)
    texts = [p.text_only() for p in read_paragraphs(doc)]
    ids = wp_ids(READER)
    warned = {x.split(":", 1)[0]: x for x in doc.warnings if "段落の区切り（段落記号）が削除" in x}
    want = {"次がコンテンツコントロールの段落。": "次がコンテンツコントロールなので",
            "次がカスタムXMLの段落。": "次がカスタム XML なので",
            "コンテンツコントロールの最後の段落。": "コンテンツコントロールの最後の段落なので",
            "表6　段落記号を削除した表題": "次が表なので",
            "セルの最後の段落。": "表のセルの最後の段落なので",
            "図3　テキストボックスの中で": "テキストボックスの最後の段落なので"}
    for t, why in want.items():
        assert why in warned[ids[t]] and "Word で変更をすべて承諾して保存してから変換し直す" in warned[ids[t]], t
    assert len(warned) == len(want)
    for t in ("次がコンテンツコントロールの段落。", "コンテンツコントロールの中の段落。", "次がカスタムXMLの段落。",
              "カスタムXMLの中の段落。", "コンテンツコントロールの最後の段落。", "コンテンツコントロールの後の段落。",
              "表6　段落記号を削除した表題", "セルの一つ目。", "セルの最後の段落。",
              "スタイル区切りの前の段落。", "スタイル区切りの後の段落。"):
        assert t in texts, t
    # 文字のない段落（変更履歴で削除された表の行のセルの段落）の、つなげない段落記号の削除は警告しない
    pkg = DocxPackage(READER)
    rule = HiddenRule(pkg.xml("word/styles.xml"))
    root = pkg.xml("word/document.xml")
    pid = paragraph_ids(root, "d")
    empty = [pid[p] for p, _ in unjoined_deleted_marks(root) if canonical_text(p, rule) == ""]
    assert empty and not set(empty) & set(warned)


def test_joined_numbered_paragraphs_count_once():
    """自動番号の段落の連鎖は、番号を 1 回だけ数える（文字ごと削除した項目が次の項目とつながり、次の項目は「2.」）。"""
    doc = read_docx(READER)
    nums = {p.text_only(): p.autonum for p in read_paragraphs(doc) if p.text_only().startswith("番号の")}
    assert nums == {"番号の一つ目の項目。": "1.", "番号の三つ目の項目。": "2.", "番号の四つ目の項目。": "3."}


def test_joined_paragraph_shapes_and_notes():
    """後ろの段落に結び付いた図形のアンカーは、つないだ段落（最初の段落の ID）。テキストボックスの中の連鎖は 1 つの段落で、
    テキストボックスの段落としても 1 回だけ読む。脚注の 1 段落目の段落記号の削除で、脚注は 1 段落になる。"""
    doc = read_docx(READER)
    paras = {p.text_only(): p for p in read_paragraphs(doc)}
    anchor = paras["図2は段落記号を削除した段落に，続く段落に結び付いた図である。"]
    assert anchor.src == wp_ids(READER)["図2は段落記号を削除した段落に，"]
    cap = paras["図2　つないだ段落に結び付いた図"]
    fl = next(f for f in doc.floats if f.fid == cap.float_id)
    tb = next(t for t in doc.textboxes if t.xid == cap.textbox_id)
    assert fl.anchor_src == tb.anchor_src == anchor.src
    cap3 = paras["図3　テキストボックスの中でつないだ表題"]
    assert cap3.in_textbox and cap3.textbox_id and "つないだ表題" not in paras
    assert [p.text_only() for p in doc.footnotes["31"]] == ["脚注の前半と脚注の後半。"]
    # スタイルの違う段落をつないだ連鎖（structure が判断の一覧に記録する）
    S = mf.S
    assert sorted((tuple(j.style_ids), j.used) for j in doc.joins) == sorted([
        ((S["sec2"], S["body"]), S["body"]), ((S["sec2"], S["body"]), S["sec2"]), ((S["body"], S["sec2"]), S["body"]),
        ((S["body"], "gHidP"), S["body"]), (("gHidP", S["body"]), S["body"])])


def test_hidden_text_from_styles():
    """文字スタイル・段落スタイル（w:basedOn の派生も）の隠し文字も、Word と同じく隠す（修正計画の U8）。隠した文字は 6 章の
    隠し文字の一覧（Document.hidden_text）に載る。ランの中の改行・記号・改行なしハイフンも一覧に載る。スタイル・既定の書式で
    隠した文字は Document.style_hidden にも載る（要確認。ランの直接の指定で隠した文字は載らない）。段落記号の削除でつないだ
    段落の隠し文字は、段落ごとの段落スタイルで決める（見える段落＋隠す段落、隠す段落＋見える段落）。"""
    doc = read_docx(READER)
    texts = [p.text_only() for p in read_paragraphs(doc)]
    assert not any("〔" in t for t in texts)
    for t in ("文字スタイルで隠した文字。", "派生の文字スタイルで隠した文字。", "直接の指定で隠した文字。",
              "文字スタイルを直接の指定で打ち消して見える文字。", "段落と文字のスタイルの反転で見える文字。",
              "表示を指定した派生の文字スタイルの見える文字。", "直接の指定で見える後半。", "隠した改行と記号の後の文字。",
              "隠す段落に続く見える前半。", "隠す段落に続いた見える後半。"):
        assert t in texts, t
    hidden = [t for _, t in doc.hidden_text]
    style = ["〔文字スタイルで隠す〕", "〔派生の文字スタイルで隠す〕", "〔段落スタイルで隠した段落〕", "〔派生の段落スタイルで隠した段落〕",
             "〔段落スタイルで隠れる文字〕", "〔段落スタイルで隠れる前半〕", "〔表示を指定した派生の文字スタイルでも隠れる文字〕",
             "〔見える段落に続いた隠す段落〕", "〔見える段落に続く隠す段落〕"]
    for t in style + ["〔直接の指定で隠す〕"]:
        assert t in hidden, t
    assert [t for _, t in doc.style_hidden] == style
    src = next(p.src for p in read_paragraphs(doc) if p.text_only() == "隠した改行と記号の後の文字。")
    assert [t for s, t in doc.hidden_text if s == src] == ["〔隠Ａ〕", "\n", "α", chr(0x2011), "〔隠Ｂ〕"]
    # つないだ段落の隠した文字は、連鎖の最初の段落の ID（読み取った段落の ID）で記録する
    paras = {p.text_only(): p.src for p in read_paragraphs(doc)}
    assert ((paras["隠す段落に続く見える前半。"], "〔見える段落に続いた隠す段落〕") in doc.style_hidden
            and (paras["隠す段落に続いた見える後半。"], "〔見える段落に続く隠す段落〕") in doc.style_hidden)


def test_deleted_table_rows():
    """変更履歴で削除された表の行（w:trPr/w:del）のうち、Word で表示される文字・画像などが残らない行は読み飛ばして記録する（修正計画の N8）。
    削除の印だけで文字の残る行と、削除されたセル（w:tcPr/w:cellDel）は出力し、10 章の警告に出す。"""
    doc = read_docx(READER)
    t = table_with(doc, "最後の内容")
    assert cell_texts(t) == [["区分", "内容"], ["印だけの行", "文字は残る"], ["残るセル", ""], ["最後の行", "最後の内容"]]
    assert [(d.tid, d.row, d.head) for d in doc.deleted_rows] == [(t.tid, 2, "区分"), (t.tid, 4, "区分")]
    assert sum("「区分」で始まる表の 3 行目: 変更履歴で削除された行ですが" in x for x in doc.warnings) == 1
    assert sum("「区分」で始まる表の 5 行目に、変更履歴で削除されたセルがあります" in x for x in doc.warnings) == 1


def test_deleted_row_with_shape_is_kept(tmp_path):
    """削除された行でも、図形（隠し文字の中の画像も）を読んだ行は読み飛ばさない（図形のアンカーが出力しない段落を指さないように）。"""
    S = mf.S

    def parts(b):
        img = b.add_image("del_row.png", mf.png_bytes("Row", size=(200, 120)))
        hidden_img = mf.drawing(img, 900000, 540000, 961).replace("<w:r>", "<w:r><w:rPr><w:vanish/></w:rPr>", 1)
        return [mf.para(S["sec1"], "１．はじめに"),
                mf.table_of_rows([mf.tr("区分", "内容"),
                                  "<w:tr><w:trPr><w:del w:id=\"962\" w:author=\"x\"/></w:trPr>"
                                  + mf.cell(mf.para(S["body"], mf.deleted(mf.run("削除した行")), hidden_img))
                                  + mf.cell(mf.para(S["body"], mf.deleted(mf.run("削除した内容")))) + "</w:tr>"], 2)]
    path = tmp_path / "row.docx"
    mf.make_article(path, "削除された行の検証用文書", parts)
    doc = read_docx(path)
    t = table_with(doc, "内容")
    assert len(t.rows) == 2 and doc.deleted_rows == [] and doc.images[0].hidden
    assert any("「区分」で始まる表の 2 行目: 変更履歴で削除された行ですが" in x for x in doc.warnings)


def test_deleted_row_numbering_and_hidden_text(tmp_path):
    """読み飛ばした削除の行の中の自動番号は数えない（Word で承諾すると行ごと消え、後ろの番号が詰まる）。行の中の隠し文字も、隠し文字の
    一覧に載せない（行ごと、読み飛ばした行として記録する）。"""
    S = mf.S

    def parts(b):
        b.styles_extra.append(mf.READER_STYLES)
        row = ("<w:tr><w:trPr><w:del w:id=\"964\" w:author=\"x\"/></w:trPr>"
               + mf.cell(mf.list_item(S["body"], mf.deleted(mf.run("削除した番号の行")), num_id=7))
               + mf.cell(mf.para(S["body"], mf.deleted(mf.run("削除した内容")),
                                 mf.run_styled("〔削除した行の中の隠し文字〕", rstyle="gHid")))
               + "</w:tr>")
        return [mf.para(S["sec1"], "１．はじめに"),
                mf.table_of_rows([mf.tr("区分", "内容"), row, mf.tr("最後", "最後の内容")], 2),
                mf.list_item(S["body"], "表の後の番号の一つ目。", num_id=7),
                mf.list_item(S["body"], "表の後の番号の二つ目。", num_id=7)]
    path = tmp_path / "rownum.docx"
    mf.make_article(path, "削除された行の検証用文書", parts)
    doc = read_docx(path)
    nums = {p.text_only(): p.autonum for p in read_paragraphs(doc) if p.text_only().startswith("表の後の番号")}
    assert nums == {"表の後の番号の一つ目。": "1.", "表の後の番号の二つ目。": "2."}
    assert not any("削除した行の中の隠し文字" in t for _, t in doc.hidden_text) and doc.style_hidden == []
    assert [(d.row, d.head) for d in doc.deleted_rows] == [(2, "区分")]
    t = table_with(doc, "最後の内容")
    assert cell_texts(t) == [["区分", "内容"], ["最後", "最後の内容"]] and t.skipped_rows == 1


def test_deleted_row_with_joined_cell_paragraphs(tmp_path):
    """読み飛ばした削除の行の中でつないだ段落（Word で行を削除したときの、段落記号も削除されたセルの段落）は、出力した段落として
    記録しない（6 章の「つないで 1 段落として出力しました」に載せない。行は読み飛ばした行として記録する）。"""
    S = mf.S
    two = [mf.para_mark_deleted(S["body"], mf.deleted(mf.run("セルの一つ目"))),
           mf.para_mark_deleted(S["body"], mf.deleted(mf.run("セルの二つ目")))]

    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"),
                mf.table_of_rows([mf.tr("区分", "内容"),
                                  "<w:tr><w:trPr><w:del w:id=\"963\" w:author=\"x\"/></w:trPr>" + mf.cell(two)
                                  + mf.cell(mf.para(S["body"], mf.deleted(mf.run("削除した内容")))) + "</w:tr>",
                                  mf.tr("最後", "最後の内容")], 2)]
    path = tmp_path / "rowjoin.docx"
    mf.make_article(path, "削除された行の検証用文書", parts)
    doc = read_docx(path)
    assert cell_texts(table_with(doc, "最後の内容")) == [["区分", "内容"], ["最後", "最後の内容"]]
    assert [(d.row, d.head) for d in doc.deleted_rows] == [(2, "区分")] and doc.joined == [] and doc.joins == []
    assert not any("段落の区切り（段落記号）" in x for x in doc.warnings)


# ooxml の規則の単体テスト（XML の文字列で作る）
STYLES_U8 = (   # 文字スタイル・派生・段落スタイル・派生（LibreOffice と比べた 21 通りの実験と同じ形。styleId は架空）
    '<w:style w:type="character" w:styleId="H"><w:name w:val="H"/><w:rPr><w:vanish/></w:rPr></w:style>'
    '<w:style w:type="character" w:styleId="HD"><w:name w:val="HD"/><w:basedOn w:val="H"/><w:rPr><w:b/></w:rPr></w:style>'
    '<w:style w:type="character" w:styleId="HD0"><w:name w:val="HD0"/><w:basedOn w:val="H"/><w:rPr><w:vanish w:val="0"/></w:rPr>'
    '</w:style>'
    '<w:style w:type="character" w:styleId="HD1"><w:name w:val="HD1"/><w:basedOn w:val="H"/><w:rPr><w:vanish/></w:rPr></w:style>'
    '<w:style w:type="character" w:styleId="HDD"><w:name w:val="HDD"/><w:basedOn w:val="HD"/><w:rPr><w:i/></w:rPr></w:style>'
    '<w:style w:type="paragraph" w:styleId="P"><w:name w:val="P"/><w:basedOn w:val="body"/><w:rPr><w:vanish/></w:rPr></w:style>'
    '<w:style w:type="paragraph" w:styleId="PD"><w:name w:val="PD"/><w:basedOn w:val="P"/><w:rPr><w:b/></w:rPr></w:style>'
    '<w:style w:type="paragraph" w:styleId="PD0"><w:name w:val="PD0"/><w:basedOn w:val="P"/><w:rPr><w:vanish w:val="0"/></w:rPr>'
    '</w:style>'
    '<w:style w:type="paragraph" w:styleId="PD1"><w:name w:val="PD1"/><w:basedOn w:val="P"/><w:rPr><w:vanish/></w:rPr></w:style>')


def styles_root(extra=STYLES_U8, doc_defaults=False, default_vanish=False):
    dd = '<w:docDefaults><w:rPrDefault><w:rPr><w:vanish/></w:rPr></w:rPrDefault></w:docDefaults>' if doc_defaults else ""
    normal = "<w:rPr><w:vanish/></w:rPr>" if default_vanish else ""
    return etree.fromstring(f'<w:styles xmlns:w="{W_NS}">{dd}<w:style w:type="paragraph" w:default="1" w:styleId="a">'
                            f'<w:name w:val="Normal"/>{normal}</w:style><w:style w:type="paragraph" w:styleId="body">'
                            f'<w:name w:val="Body Text"/><w:basedOn w:val="a"/></w:style>{extra}</w:styles>')


def hidden_para(pstyle, rstyle=None, vanish=None, spec=False):
    """段落 pstyle（None なら pStyle なし）の中の「TEST」のラン。"""
    ppr = f'<w:pPr><w:pStyle w:val="{pstyle}"/></w:pPr>' if pstyle else ""
    run = mf.run_styled("TEST", rstyle=rstyle, vanish=vanish, spec=spec)
    return etree.fromstring(f'<w:p xmlns:w="{W_NS}">{ppr}{run}</w:p>')


# (段落スタイル, ランの指定, 隠れるか, docDefaults にも vanish があるとき隠れるか)。修正計画の G の規則（ECMA-376 の切り替え: スタイルと
# 既定の書式の vanish は、真ならそれまでの状態を反転し、偽なら変えない。ランの直接の指定はその値）の期待。LibreOffice（24.2）で承諾・
# 表示した結果と違うのは、u15（偽を指定した派生の文字スタイル）・u19（specVanish だけのラン）で LibreOffice は表示するところと、
# docDefaults の版の u03・u05〜u08・u10・u16・u18・u21（LibreOffice は、段落スタイルに vanish の指定があればその値をそのまま使う）。
# どれも暫定（Word では未確認。docs/DESIGN.md の 4.1）
U8_CASES = [
    ("u01", "body", {"rstyle": "H"}, True, False),
    ("u02", "body", {"rstyle": "HD"}, True, False),
    ("u03", "body", {"rstyle": "HD0"}, False, True),
    ("u04", "body", {"rstyle": "HD1"}, True, False),
    ("u05", "P", {}, True, False),
    ("u06", "PD", {}, True, False),
    ("u07", "PD0", {}, False, True),
    ("u08", "PD1", {}, True, False),
    ("u09", "body", {"rstyle": "H", "vanish": False}, False, False),
    ("u10", "P", {"rstyle": "H"}, False, True),
    ("u11", "P", {"rstyle": "H", "vanish": False}, False, False),
    ("u12", "P", {"vanish": False}, False, False),
    ("u13", "body", {"vanish": True}, True, True),
    ("u14", "P", {"vanish": True}, True, True),
    ("u15", "P", {"rstyle": "HD0"}, True, False),
    ("u16", "P", {"rstyle": "HD"}, False, True),
    ("u17", "body", {"rstyle": "HDD"}, True, False),
    ("u18", "PD", {"rstyle": "HD"}, False, True),
    ("u19", "body", {"spec": True}, True, True),
    ("u20", "body", {"vanish": False, "spec": True}, False, False),
    ("u21", "PD1", {"rstyle": "HD1"}, False, True),
    ("plain", "body", {}, False, True),
]


@pytest.mark.parametrize("pstyle, run_kw, hidden, hidden_dd", [c[1:] for c in U8_CASES], ids=[c[0] for c in U8_CASES])
def test_hidden_rule(pstyle, run_kw, hidden, hidden_dd):
    """隠し文字の判定（ooxml.HiddenRule）: 直接の指定・文字スタイル・段落スタイル（派生も）・既定の書式（docDefaults）。"""
    p = hidden_para(pstyle, **run_kw)
    assert canonical_text(p, HiddenRule(styles_root())) == ("" if hidden else "TEST")
    assert canonical_text(p, HiddenRule(styles_root(doc_defaults=True))) == ("" if hidden_dd else "TEST")


def test_hidden_rule_details():
    """派生のスタイルの値（いちばん派生した側。連鎖の中で反転しない）、既定の段落スタイル、既定の書式との打ち消し、basedOn の循環、
    styles.xml がないとき。"""
    rule = HiddenRule(styles_root())
    assert (rule.style_value("H"), rule.style_value("HD"), rule.style_value("HD0"), rule.style_value("HD1")) == (True, True, False, True)
    assert rule.style_value("body") is None and rule.style_value("ない") is None
    # pStyle のない段落は既定の段落スタイル（Normal）の値
    assert canonical_text(hidden_para(None), HiddenRule(styles_root(default_vanish=True))) == ""
    assert canonical_text(hidden_para(None), rule) == "TEST"
    # 既定の書式と既定の段落スタイルの両方に vanish があると、打ち消し合って見える（XOR。どちらか一方なら隠れる）
    both = HiddenRule(styles_root(doc_defaults=True, default_vanish=True))
    assert canonical_text(hidden_para(None), both) == "TEST" and both.para_state(hidden_para(None)) is False
    assert canonical_text(hidden_para("body", rstyle="H"), both) == ""
    # basedOn の循環は打ち切る
    loop = HiddenRule(styles_root('<w:style w:type="character" w:styleId="X"><w:basedOn w:val="Y"/></w:style>'
                                  '<w:style w:type="character" w:styleId="Y"><w:basedOn w:val="X"/></w:style>'))
    assert loop.style_value("X") is None and canonical_text(hidden_para("body", rstyle="X"), loop) == "TEST"
    # styles.xml がなければ直接の指定だけ（文字スタイルの指定は見ない）
    assert canonical_text(hidden_para("body", rstyle="H"), NO_RULE) == "TEST"
    assert canonical_text(hidden_para("body", vanish=True), None) == ""


def test_hidden_rule_cause():
    """隠したときの指定（ooxml.HiddenRule.run_hidden_by）: ランの直接の指定（w:vanish・w:specVanish）なら "direct"、文字スタイル・
    段落スタイル・既定の書式なら "style"（読み取りが要確認として記録する）、隠れなければ ""。隠れるかは run_hidden と同じ。"""
    rules = (HiddenRule(styles_root()), HiddenRule(styles_root(doc_defaults=True)))
    for name, pstyle, kw, hidden, hidden_dd in U8_CASES:
        p = hidden_para(pstyle, **kw)
        r = p.find(w("r"))
        for rule, want in zip(rules, (hidden, hidden_dd)):
            ps = rule.para_state(p)
            by = rule.run_hidden_by(r, ps)
            assert (by != "") is want is rule.run_hidden(r, ps), name
            if want:
                assert by == ("direct" if kw.get("vanish") or kw.get("spec") else "style"), name
    assert NO_RULE.run_hidden_by(hidden_para("body", rstyle="H").find(w("r")), False) == ""


def test_joined_paragraph_section_break(tmp_path):
    """段落記号の削除でつないだ段落のセクションの区切り（Para.section_break）は、連鎖の最後の段落のもの（Word で承諾すると、
    削除した段落記号といっしょに、その段落のセクションの区切りも消える）。"""
    S = mf.S

    def with_sect(xml):
        return xml.replace("</w:pPr>", '<w:sectPr><w:type w:val="continuous"/></w:sectPr></w:pPr>', 1)

    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"),
                mf.para_mark_deleted(S["body"], "区切りのない前半，"), with_sect(mf.para(S["body"], "区切りのある後半。")),
                with_sect(mf.para_mark_deleted(S["body"], "区切りを削除した前半，")), mf.para(S["body"], "区切りのない後半。")]
    path = tmp_path / "sect.docx"
    mf.make_article(path, "セクションの区切りの検証用文書", parts)
    doc = read_docx(path)
    paras = {p.text_only(): p for p in read_paragraphs(doc)}
    assert paras["区切りのない前半，区切りのある後半。"].section_break
    assert not paras["区切りを削除した前半，区切りのない後半。"].section_break


def test_textbox_keeps_outer_hidden_state(tmp_path):
    """隠す段落スタイルの段落の中のテキストボックスを読んだ後も、外側の段落の隠し文字の状態のまま読む（テキストボックスの後ろの
    ランも隠す）。テキストボックスの中の段落は、その段落自身の段落スタイルで決める（本文なら見える）。"""
    S = mf.S

    def parts(b):
        b.styles_extra.append(mf.READER_STYLES)
        box = mf.textbox_inline(mf.para(S["body"], "隠す段落の中の囲みの見える文字。"), 741)
        return [mf.para(S["sec1"], "１．はじめに"),
                mf.para("gHidP", "〔囲みの前の隠れる文字〕", box, "〔囲みの後ろの隠れる文字〕")]
    path = tmp_path / "tbhidden.docx"
    mf.make_article(path, "隠し文字の検証用文書", parts)
    doc = read_docx(path)
    canon = source_texts(path)
    for p in read_paragraphs(doc):
        assert atoms_text(p) == canon[p.src], p.src
    assert "隠す段落の中の囲みの見える文字。" in [p.text_only() for p in read_paragraphs(doc)]
    assert [t for _, t in doc.style_hidden] == ["〔囲みの前の隠れる文字〕", "〔囲みの後ろの隠れる文字〕"]


def _body(xml):
    return etree.fromstring(f'<w:document xmlns:w="{W_NS}"><w:body>{xml}<w:sectPr/></w:body></w:document>')


def _p(text, mark="del"):
    """段落。mark が del・moveFrom なら段落記号の削除、vanish なら段落記号の隠し文字（スタイル区切り）、ins なら段落記号の挿入。"""
    rpr = {"del": '<w:del w:id="1" w:author="x"/>', "moveFrom": '<w:moveFrom w:id="2" w:author="x"/>',
           "vanish": "<w:vanish/><w:specVanish/>", "ins": '<w:ins w:id="3" w:author="x"/>'}.get(mark, "")
    ppr = f"<w:pPr><w:rPr>{rpr}</w:rPr></w:pPr>" if rpr else ""
    return f"<w:p>{ppr}<w:r><w:t>{text}</w:t></w:r></w:p>"


def test_joined_paragraphs_rules():
    """段落記号の削除でつなぐ規則（ooxml.joined_paragraphs・unjoined_deleted_marks・canonical_texts）: 同じ親の中で、次の兄弟が
    w:p のときだけ（中身のない目印は飛ばす）。次が表・ブロックの w:ins、本文の最後（w:sectPr の前）ではつながない。段落記号の
    隠し文字・挿入はつながない。"""
    root = _body(_p("a") + '<w:commentRangeStart w:id="5"/><w:proofErr w:type="spellStart"/>' + _p("b", None)
                 + _p("c") + _p("d") + "<w:tbl/>" + _p("e", "moveFrom") + '<w:ins w:id="6" w:author="x">' + _p("f", None)
                 + "</w:ins>" + _p("g", "vanish") + _p("h", "ins") + _p("i", None) + _p("j"))
    chains = joined_paragraphs(root)
    assert [[canonical_text(q) for q in c] for c in chains.values()] == [["a", "b"], ["c", "d"]]
    assert [(canonical_text(q), why) for q, why in unjoined_deleted_marks(root)] == [
        ("d", "次が表"), ("e", "次が段落でない"), ("j", "本文の最後の段落")]
    assert [paragraph_mark_deleted(q) for q in root.iter(w("p"))] == [True, False, True, True, True, False, False, False, False,
                                                                       True]
    assert canonical_texts(root, "d") == {"d1": "ab", "d3": "cd", "d5": "e", "d6": "f", "d7": "g", "d8": "h", "d9": "i",
                                          "d10": "j"}
    # 親の最後の段落（表のセル・テキストボックス・注・コンテンツコントロール）はつながない
    cell = etree.fromstring(f'<w:tc xmlns:w="{W_NS}">{_p("k")}</w:tc>')
    assert [why for _, why in unjoined_deleted_marks(cell)] == ["表のセルの最後の段落"]
    sdt = etree.fromstring(f'<w:body xmlns:w="{W_NS}"><w:sdt><w:sdtContent>{_p("l")}</w:sdtContent></w:sdt>{_p("m", None)}'
                           '</w:body>')
    assert joined_paragraphs(sdt) == {} and [why for _, why in unjoined_deleted_marks(sdt)] == [
        "コンテンツコントロールの最後の段落"]


def _with_style_linked_numbering(src, dst, circular=False):
    """numbering.xml に、番号付けスタイル経由の定義を足した docx を作る（Word の形: numId 91 → abstractNum 91〈w:numStyleLink〉→
    スタイル LinkedList の numId 90 → abstractNum 90〈w:styleLink で LinkedList を名乗る。段の定義はここ〉）。circular なら、
    スタイルが numId 91 自身を指す（たどれない）。"""
    import zipfile
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/numbering.xml":
                x = data.decode("utf-8")
                a = ('<w:abstractNum w:abstractNumId="90"><w:multiLevelType w:val="multilevel"/><w:styleLink w:val="LinkedList"/>'
                     '<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="(%1)"/></w:lvl>'
                     '</w:abstractNum><w:abstractNum w:abstractNumId="91"><w:multiLevelType w:val="multilevel"/>'
                     '<w:numStyleLink w:val="LinkedList"/></w:abstractNum>')
                n = ('<w:num w:numId="90"><w:abstractNumId w:val="90"/></w:num>'
                     '<w:num w:numId="91"><w:abstractNumId w:val="91"/></w:num>')
                i = x.index("<w:num ")
                x = x[:i].replace("</w:abstractNum><w:num", "</w:abstractNum><w:num") + a + x[i:]
                x = x.replace("</w:numbering>", n + "</w:numbering>")
                data = x.encode("utf-8")
            elif item.filename == "word/styles.xml":
                target = "91" if circular else "90"
                st = ('<w:style w:type="numbering" w:styleId="LinkedList"><w:name w:val="LinkedList"/>'
                      f'<w:pPr><w:numPr><w:numId w:val="{target}"/></w:numPr></w:pPr></w:style>')
                data = data.decode("utf-8").replace("</w:styles>", st + "</w:styles>").encode("utf-8")
            zout.writestr(item, data)


def test_num_style_link_numbering_is_followed(tmp_path, journal, meta):
    """abstractNum の w:numStyleLink（番号付けスタイル経由の定義）は、スタイルの numId が指す定義の段を使う（修正計画の R3）。
    番号が出て <list> になる。たどれない（循環）ときは今までどおり番号なしで、例外にしない。"""
    from jasme_jats.pipeline import Options, convert
    S = mf.S

    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"),
                mf.list_item(S["body"], "一つ目の項目", num_id=91), mf.list_item(S["body"], "二つ目の項目", num_id=91),
                mf.para(S["body"], "最後の文。")]
    base = tmp_path / "base.docx"
    mf.make_article(base, "番号付けスタイルの検証用文書", parts)
    path = tmp_path / "linked.docx"
    _with_style_linked_numbering(base, path)
    doc = read_docx(path)
    items = [p for p in doc.all_paragraphs() if p.numbering]
    assert [p.autonum for p in items] == ["(1)", "(2)"]
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    assert res.fidelity.ok and res.fidelity.final_ok
    xml = (tmp_path / "out" / next(p.name for p in (tmp_path / "out").iterdir() if p.suffix == ".xml")).read_text("utf-8")
    assert "<list" in xml and "(1)" in xml
    bad = tmp_path / "circular.docx"
    _with_style_linked_numbering(base, bad, circular=True)
    assert [p.autonum for p in read_docx(bad).all_paragraphs() if p.numbering] == ["", ""]


def _with_lvl_override(src, dst):
    """numbering.xml に、abstractNum 0（段 0 は decimal・「%1.」）を指す、w:lvlOverride/w:lvl つきの num を足した docx を作る。
    92: lvl（upperLetter・「(%1)」）、93: startOverride 5 と lvl（lowerRoman・「%1)」）、94: startOverride 3 だけ、
    95: ilvl 0 が upperLetter・「%1.」、ilvl 1 が decimal・「%1-%2」。"""
    import zipfile
    n = ('<w:num w:numId="92"><w:abstractNumId w:val="0"/><w:lvlOverride w:ilvl="0"><w:lvl w:ilvl="0">'
         '<w:start w:val="1"/><w:numFmt w:val="upperLetter"/><w:lvlText w:val="(%1)"/></w:lvl></w:lvlOverride></w:num>'
         '<w:num w:numId="93"><w:abstractNumId w:val="0"/><w:lvlOverride w:ilvl="0"><w:startOverride w:val="5"/><w:lvl w:ilvl="0">'
         '<w:numFmt w:val="lowerRoman"/><w:lvlText w:val="%1)"/></w:lvl></w:lvlOverride></w:num>'
         '<w:num w:numId="94"><w:abstractNumId w:val="0"/><w:lvlOverride w:ilvl="0"><w:startOverride w:val="3"/></w:lvlOverride></w:num>'
         '<w:num w:numId="95"><w:abstractNumId w:val="0"/>'
         '<w:lvlOverride w:ilvl="0"><w:lvl w:ilvl="0"><w:numFmt w:val="upperLetter"/><w:lvlText w:val="%1."/></w:lvl></w:lvlOverride>'
         '<w:lvlOverride w:ilvl="1"><w:lvl w:ilvl="1"><w:numFmt w:val="decimal"/><w:lvlText w:val="%1-%2"/></w:lvl></w:lvlOverride></w:num>')
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/numbering.xml":
                data = data.decode("utf-8").replace("</w:numbering>", n + "</w:numbering>").encode("utf-8")
            zout.writestr(item, data)


def test_lvl_override_numbering_is_used(tmp_path, journal, meta):
    """w:lvlOverride/w:lvl は、その num だけ段の定義を置き換える（修正計画の R6）。"""
    from jasme_jats.pipeline import Options, convert
    S = mf.S

    def parts(b):
        sub = mf.list_item(S["body"], "下の項目", num_id=95).replace('<w:ilvl w:val="0"/>', '<w:ilvl w:val="1"/>')
        return [mf.para(S["sec1"], "１．はじめに"),
                mf.list_item(S["body"], "項目一", num_id=92), mf.list_item(S["body"], "項目二", num_id=92),
                mf.list_item(S["body"], "項目三", num_id=93), mf.list_item(S["body"], "項目四", num_id=94),
                mf.list_item(S["body"], "項目五", num_id=95), sub,
                mf.para(S["body"], "最後の文。")]
    base = tmp_path / "base.docx"
    mf.make_article(base, "段の上書きの検証用文書", parts)
    path = tmp_path / "override.docx"
    _with_lvl_override(base, path)
    doc = read_docx(path)
    assert [p.autonum for p in doc.all_paragraphs() if p.numbering] == ["(A)", "(B)", "v)", "3.", "A.", "A-1"]
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    assert res.fidelity.ok and res.fidelity.final_ok
    xml = (tmp_path / "out" / next(p.name for p in (tmp_path / "out").iterdir() if p.suffix == ".xml")).read_text("utf-8")
    assert "<list" in xml and "(A)" in xml


def _numbering_from(abstract_lvl, num_body):
    from jasme_jats.numbering import Numbering
    x = (f'<w:numbering xmlns:w="{W_NS}"><w:abstractNum w:abstractNumId="0">{abstract_lvl}</w:abstractNum>'
         f'<w:num w:numId="1"><w:abstractNumId w:val="0"/>{num_body}</w:num></w:numbering>')
    return Numbering(etree.fromstring(x))


def test_lvl_override_partial_children_inherit_abstract():
    """上書きの lvl に書かれていない子要素は abstractNum の段の値を使う（番号が黙って消えない）。共有の dict は書き換えない。"""
    lvl = '<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="(%1)"/></w:lvl>'
    n = _numbering_from(lvl, '<w:lvlOverride w:ilvl="0"><w:lvl w:ilvl="0"><w:start w:val="4"/></w:lvl></w:lvlOverride>')
    assert [n.label("1", 0), n.label("1", 0)] == ["(4)", "(5)"]
    n = _numbering_from(lvl, '<w:lvlOverride w:ilvl="0"><w:lvl w:ilvl="0"><w:numFmt w:val="upperLetter"/></w:lvl></w:lvlOverride>')
    assert n.label("1", 0) == "(A)"
    assert n.abstract["0"][0] == {"start": 1, "fmt": "decimal", "text": "(%1)"}


def test_lvl_override_bullet_and_start_priority():
    lvl = '<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl>'
    n = _numbering_from(lvl, '<w:lvlOverride w:ilvl="0"><w:lvl w:ilvl="0"><w:numFmt w:val="bullet"/></w:lvl></w:lvlOverride>')
    assert n.is_bullet("1", 0)
    n = _numbering_from(lvl, '<w:lvlOverride w:ilvl="0"><w:startOverride w:val="7"/>'
                             '<w:lvl w:ilvl="0"><w:start w:val="2"/></w:lvl></w:lvlOverride>')
    assert [n.label("1", 0), n.label("1", 0)] == ["7.", "8."]


# ----------------------------------------------------------------------------- 画像の切り取り・加工の記録（u4-crop）
def _images_of(tmp_path, *parts, name="img.docx"):
    def body(b):
        out = [mf.para(mf.S["sec1"], "１．検証")]
        for part in parts:
            out.append(mf.para(mf.S["body"], part(b)))
        return out

    path = tmp_path / name
    mf.make_article(path, "画像の読み取り", body)
    return read_docx(path).images


def _draw(**kw):
    return lambda b: mf.drawing(b.add_image("p.png", mf.two_tone()), 1000000, 800000, 700, **kw)


def test_reader_reads_src_rect(tmp_path):
    imgs = _images_of(tmp_path, _draw(src_rect='l="50000" r="10000"'), _draw(src_rect='l="50%"'),
                      _draw(src_rect='l="0" t="0" r="0" b="0"'), _draw(src_rect='t="-5000" l="20000"'))
    assert imgs[0].crop == (0.5, 0, 0.1, 0) and imgs[0].edits == ()
    assert imgs[1].crop == (0.5, 0, 0, 0)
    assert imgs[2].crop is None
    assert imgs[3].crop == (0.2, 0, 0, 0) and "余白" in imgs[3].edits


def test_reader_unreadable_src_rect(tmp_path):
    (img,) = _images_of(tmp_path, _draw(src_rect='l="abc"'))
    assert "切り取り（読めない指定）" in img.edits


def test_tiny_negative_src_rect_not_padding(tmp_path):
    (img,) = _images_of(tmp_path, _draw(src_rect='t="-50"'))
    assert "余白" not in img.edits and img.crop is None


def test_reader_reads_vml_crop(tmp_path):
    (img,) = _images_of(tmp_path, lambda b: mf.vml_image(b.add_image("v.png", mf.two_tone()),
                                                        attrs='cropleft="16384f" cropright="0.1"',
                                                        style="rotation:90;flip:x"))
    assert img.crop == (0.25, 0, 0.1, 0) and "回転" in img.edits and "左右反転" in img.edits


def test_reader_records_rotation_flip_effects(tmp_path):
    (img,) = _images_of(tmp_path, _draw(xfrm=' rot="5400000" flipV="1"', blip='<a:grayscl/><a:alphaModFix amt="50000"/>'))
    assert img.edits == ("回転", "上下反転", "色の変更", "透明度") and img.crop is None

    def grp(b):
        r1 = b.add_image("g1.png", mf.two_tone())
        return mf.pic_group([(r1, 1000000, 800000)], 710, grp_xfrm=' flipH="1"')

    (g,) = _images_of(tmp_path, grp, name="grp.docx")
    assert "左右反転" in g.edits


def test_reader_records_art_effects(tmp_path):
    art = ('<a:extLst><a:ext uri="{BEBA8EAE-BF5A-486C-A8C5-ECC9F3942E4B}">'
           '<a14:imgProps xmlns:a14="http://schemas.microsoft.com/office/drawing/2010/main"/></a:ext></a:extLst>')
    (img,) = _images_of(tmp_path, _draw(blip=art))
    assert "アート効果" in img.edits


def _group_images(tmp_path, **kw):
    def grp(b):
        r1, r2 = b.add_image("g1.png", mf.two_tone()), b.add_image("g2.png", mf.two_tone())
        return mf.pic_group([(r1, 1000000, 800000), (r2, 500000, 400000)], 720, **kw)

    return _images_of(tmp_path, grp)


def test_group_pic_size_ignores_blip_extlst(tmp_path):
    imgs = _group_images(tmp_path, blip_ext=True)
    assert [i.cx_emu for i in imgs] == [1000000, 500000]


def test_group_pic_size_scaled_by_chext(tmp_path):
    imgs = _group_images(tmp_path, extent=(1000000, 800000), ch_ext=(2000000, 1600000))
    assert [i.cx_emu for i in imgs] == [500000, 250000]
