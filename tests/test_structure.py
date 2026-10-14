"""論文の構造: 領域（和文の冒頭・本文・後付け・英文の部分）の分け方。"""
import functools
from types import SimpleNamespace

import pytest
from lxml import etree

import make_fixtures as mf
from conftest import STRUCTURE
from jasme_jats.docx_reader import read_docx
from jasme_jats.model import Atom, Cell, Para, Row, Table
from jasme_jats.pipeline import Options, convert
from jasme_jats.structure import Classifier

S = mf.S


def load(res):
    return etree.fromstring(res.xml_path.read_bytes().split(b"\n", 2)[2])


def text(el):
    return "".join(el.itertext())


def outline(res):
    """領域の分け方で変わるもの: 章節の見出し、引用文献の数、英文要旨の段落、注の一覧の有無。"""
    root = load(res)
    return {"sec": [text(s.find("title")) for s in root.iter("sec")],
            "ref": len(list(root.iter("ref"))),
            "trans-abstract": [text(p) for p in root.findall(".//trans-abstract/p")],
            "fn-group": root.find(".//fn-group") is not None}


def test_textbox_paragraphs_do_not_switch_regions(journal, meta, tmp_path):
    # 本文中のテキストボックスに「英文要旨」スタイルの段落や「注」だけの段落があっても、以降の本文と引用文献は
    # 英文要旨にも注にもならない（章・引用文献・英文要旨・注の一覧は、テキストボックスがない場合と同じ）
    res = convert(STRUCTURE, meta, journal, Options(out_dir=tmp_path / "with", convert_metafiles=False))
    assert res.fidelity.ok and res.dtd_valid
    plain = tmp_path / "plain.docx"
    mf.make_structure(plain, sections=[
        (h, functools.partial(f, textboxes=False) if f is mf.structure_textbox_regions else f)
        for h, f in mf.STRUCTURE_SECTIONS])
    ref = convert(plain, meta, journal, Options(out_dir=tmp_path / "plain", convert_metafiles=False))
    got = outline(res)
    assert got == outline(ref)
    assert "２．おわりに" in got["sec"] and got["ref"] == 1 and got["trans-abstract"] == ["Structure abstract."]
    # テキストボックスの段落は、結び付いている段落と同じ本文の領域に入る
    srcs = {p.plain(): p.src for p in res.plan.paras.values() if p.in_textbox}
    assert {res.plan.region[srcs[t]] for t in ("注", "Area model")} == {"body"}


def _para(src, content, **kw):
    return Para(src=src, atoms=[Atom(kind="text", text=content)], **kw)


def _table(tid, style_id, **kw):
    return Table(tid=tid, rows=[Row(cells=[Cell(blocks=[Para(src=f"{tid}p", style_id=style_id,
                                                             atoms=[Atom(kind="text", text="SHIKEN")])])])], **kw)


def _classifier(journal):
    name = next(n for n, r in journal.styles.items() if r == "author_en")
    return Classifier(SimpleNamespace(styles={"en": SimpleNamespace(name=name, based_on="")}), journal)


@pytest.mark.parametrize("shape", [
    ("abstract", _para("x", "Area model", in_textbox=True)),           # 英文の部分の役割（FRONT_EN_ROLES）
    ("p", _para("x", "注", in_textbox=True)),                           # 後付けの見出しの文字（back_heading_by_text）
    ("ref_heading", _para("x", "参考文献", in_textbox=True)),            # 後付けの見出しのスタイル
    ("author_en", _para("x", "Taro SHIKEN", float_id="s1")),            # 浮動配置の図形の中の段落
    ("table", _table("t9", "en", in_textbox=True)),     # 浮動配置でないテキストボックスの中の表（セルが「著者名（英）」）
    ("table", _table("t9", "en", float_id="s1")),       # 浮動配置の図形の中の表（セルが「著者名（英）」）
], ids=["abstract-style", "fn-text", "ref-heading-style", "float-para", "textbox-table", "float-table"])
def test_split_regions_ignores_shape_contents_in_body(journal, shape):
    # 図形の中の段落・表では領域を変えず、直前にある図形の外のブロック（本文の段落）と同じ領域に入れる
    role, block = shape
    flat = [(_para("d1", "題目"), "title"), (_para("d2", "１．はじめに"), "sec1"), (_para("d3", "本文一。"), "p"),
            (block, role), (_para("d4", "本文二。"), "p"), (_para("d5", "２．おわりに"), "sec1"),
            (_para("d6", "引用文献"), "ref_heading"), (_para("d7", "文献。"), "ref"),
            (_para("d8", "Abstract"), "abstract_heading"), (_para("d9", "Text."), "abstract")]
    regions = _classifier(journal).split_regions(flat)
    got = {name: [b.src if isinstance(b, Para) else b.tid for b, _ in items] for name, items in regions.items()}
    x = block.src if isinstance(block, Para) else block.tid
    assert got == {"front_ja": ["d1"], "body": ["d2", "d3", x, "d4", "d5"], "back": ["d6", "d7"], "front_en": ["d8", "d9"]}


def test_split_regions_ignores_shape_contents_in_front(journal):
    # 冒頭の図形の中の表・段落でも本文に切り替えない（図形の中のセクション区切りでも切り替えない）。
    # 冒頭の最後の段落（セクション区切り）に結び付いた図形の中身は、切り替えた後の本文に入る（0.18.1 と同じ）
    tb_table = _table("t9", "", in_textbox=True)
    sect = _para("d3", "", section_break=True)
    flat = [(_para("d1", "題目"), "title"), (tb_table, "table"),
            (_para("x0", "区切り", in_textbox=True, section_break=True), "normal"), (_para("d2", "試験　太郎"), "author_ja"),
            (sect, "normal"), (_para("x1", "本文スタイルの囲み。", in_textbox=True), "p"),
            (_para("x2", "図1　冒頭の最後の段落に結び付いた図", in_textbox=True), "fig_caption"),
            (_para("d4", "１．はじめに"), "sec1")]
    regions = _classifier(journal).split_regions(flat)
    got = {name: [b.src if isinstance(b, Para) else b.tid for b, _ in items] for name, items in regions.items()}
    assert got == {"front_ja": ["d1", "t9", "x0", "d2", "d3"], "body": ["x1", "x2", "d4"], "back": [], "front_en": []}


def test_split_regions_title_in_textbox(journal):
    # 題目がテキストボックスの中にあっても（誌名の行に結び付けた図形）、題目を見たことにして、冒頭の最後のセクション区切りで
    # 本文に切り替える（章見出しの前の、標準スタイルの段落を冒頭に残さない）
    flat = [(_para("d1", "誌名"), "normal"), (_para("x1", "題目", in_textbox=True), "title"),
            (_para("d2", "試験　太郎"), "author_ja"), (_para("d3", "", section_break=True), "normal"),
            (_para("d4", "章見出しの前の本文。"), "normal"), (_para("d5", "１．はじめに"), "sec1")]
    regions = _classifier(journal).split_regions(flat)
    got = {name: [b.src for b, _ in items] for name, items in regions.items()}
    assert got == {"front_ja": ["d1", "x1", "d2", "d3"], "body": ["d4", "d5"], "back": [], "front_en": []}


def _front_article(path, front_hook, body_head):
    """冒頭（mf.front_ja）を front_hook(b, front) で変えた小さな論文。body_head は章見出しの前に置く段落の XML の一覧。"""
    b = mf.Builder()
    front = mf.front_ja(b, "冒頭の図形の検証用文書", "―副題―", [("架空大学", "試験\u3000七郎")])
    front_hook(b, front)
    body = front + body_head + [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "図1を示す。試験（2025）にならう。"),
                                mf.para(S["ref_head"], "引用および参考文献"),
                                mf.para(S["ref"], "試験七郎（2025）．「題」．『架空誌』，第6巻，pp.11-12．")]
    body += mf.front_en(b, "Title", "Subtitle", [("Shichiro SHIKEN", "Fictional University")], ["Abstract text."])
    body += mf.tail(b)
    b.save(path, body)
    return path


def test_figure_on_section_break_paragraph_goes_to_body(journal, meta, tmp_path):
    # 和文の冒頭の最後の段落（セクション区切り）に結び付いた図のテキストボックスは、本文の図 F1 になる（0.18.1 と同じ）。
    # 冒頭に入れると、画像の段落とキャプションが「冒頭部のテンプレート装飾」として除外され、図が XML から消える
    def hook(b, front):
        rid = b.add_image("sect.png", mf.png_bytes("sect fig", size=(400, 240)))
        tb = mf.textbox(mf.para(S["body"], mf.drawing(rid, 1800000, 1080000, 702))
                        + mf.para(S["fig_cap"], "図1\u3000冒頭の最後の段落の図"), 701, cx=3000000, cy=1500000)
        front[8].append(b.frag(mf.para(None, tb))[0][0])
    res = convert(_front_article(tmp_path / "sectfig.docx", hook, []), meta, journal,
                  Options(out_dir=tmp_path / "out", convert_metafiles=False))
    assert res.fidelity.ok and res.dtd_valid and res.lost_images == []
    assert [i.image_id for i in res.images] == ["img1"]
    root = load(res)
    fig = root.find("body/fig[@id='F1']")
    assert text(fig.find("caption")) == "図1\u3000冒頭の最後の段落の図" and len(fig.findall("graphic")) == 1
    assert not any("図1" in t for _, _, t in res.fidelity.excluded)


def test_title_in_textbox_switches_to_body_at_section_break(journal, meta, tmp_path):
    # 題目の段落をテキストボックスに入れ、誌名の行に結び付けた原稿。題目は題目として出し、冒頭の最後のセクション区切りの後の、
    # 章見出しの前にある標準スタイルの段落は、本文に入れる（冒頭に残すと「冒頭部のテンプレート装飾」として除外される）
    def hook(b, front):
        title = front.pop(2)
        tb = mf.textbox(etree.tostring(title, encoding="unicode"), 951, cx=6000000, cy=500000)
        front[0].append(b.frag(mf.para(None, tb))[0][0])
    path = _front_article(tmp_path / "title_tb.docx", hook, [mf.para(None, "章見出しの前に、標準スタイルで書いた本文の段落がある。")])
    assert [p.plain() for p in read_docx(path).blocks if isinstance(p, Para) and p.in_textbox] == ["冒頭の図形の検証用文書"]
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    assert res.fidelity.ok and res.dtd_valid
    root = load(res)
    assert text(root.find(".//title-group/article-title")) == "冒頭の図形の検証用文書"
    assert text(root.find("body/p")) == "章見出しの前に、標準スタイルで書いた本文の段落がある。"
    assert not any(t.startswith("章見出しの前") for _, _, t in res.fidelity.excluded)


def test_textbox_table_without_float_stays_in_front(journal, meta, tmp_path):
    # 浮動配置でない VML のテキストボックスの中の表（float_id がない）も、図形の中の表として扱い、本文に切り替えない
    # （切り替えると、後ろの著者表が本文の表になり、著者が XML から消える）
    b = mf.Builder()
    front = mf.front_ja(b, "冒頭の図形の検証用文書", "―副題―", [("架空大学", "試験　七郎")])
    vml = ('<w:r><w:pict><v:shape style="width:200pt;height:40pt"><v:textbox><w:txbxContent>'
           + mf.table([[mf.cell("特集　図形の中の表")]]) + mf.para(S["body"])
           + "</w:txbxContent></v:textbox></v:shape></w:pict></w:r>")
    front[3].append(b.frag(mf.para(None, vml))[0][0])      # 副題の段落に結び付ける
    body = front + [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "試験（2025）にならう。"),
                    mf.para(S["ref_head"], "引用および参考文献"),
                    mf.para(S["ref"], "試験七郎（2025）．「構造の検証」．『架空誌』，第6巻，pp.11-12．")]
    body += mf.front_en(b, "Title", "Subtitle", [("Shichiro SHIKEN", "Fictional University")], ["Abstract text."])
    body += mf.tail(b)
    path = tmp_path / "front_textbox_table.docx"
    b.save(path, body)
    tables = [t for t in read_docx(path).blocks if isinstance(t, Table) and t.in_textbox]
    assert [(t.float_id, [p.plain() for p in t.paragraphs()]) for t in tables] == [("", ["特集　図形の中の表"])]

    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    assert res.fidelity.ok and res.dtd_valid
    root = load(res)
    assert [text(n) for n in root.findall(".//contrib-group/contrib//name[@name-style='eastern']")] == ["試験七郎"]
    assert [text(s.find("title")) for s in root.iter("sec")] == ["１．はじめに"]
    assert root.find(".//body//table-wrap") is None
    reasons = {t: reason for _, reason, t in res.fidelity.excluded}
    assert reasons["特集　図形の中の表"] == "冒頭部の表（著者表以外）の文字"
