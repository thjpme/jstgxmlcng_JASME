"""論文の構造: 領域（和文の冒頭・本文・後付け・英文の部分）の分け方、英文要旨の後ろの資料（付録）の見出し（修正計画の D3）、
文字だけのテキストボックス（囲み・図に重ねた注記。修正計画の D1）。"""
import dataclasses
import functools
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from lxml import etree

import make_fixtures as mf
from conftest import STRUCTURE, fill_images, image_folder, others
from jasme_jats.docx_reader import read_docx
from jasme_jats.model import Atom, Cell, Para, Row, Table
from jasme_jats.pipeline import Options, StructureConflictError, _mechanical, convert
from jasme_jats.report import NEEDS_ACTION, TO_CHECK, actions, structure_conflict_text
from jasme_jats.structure import BACK_TABLE_EXCLUDED, RE_APPENDIX, Classifier, appendix_heading, appendix_sentence

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
    res = convert(STRUCTURE, meta, journal, Options(out_dir=tmp_path / "with"))
    assert res.fidelity.ok and res.dtd_valid
    plain = tmp_path / "plain.docx"
    mf.make_structure(plain, sections=[
        (h, functools.partial(f, textboxes=False) if f is mf.structure_textbox_regions else f)
        for h, f in mf.STRUCTURE_SECTIONS])
    ref = convert(plain, meta, journal, Options(out_dir=tmp_path / "plain"))
    got = outline(res)
    assert got == outline(ref)
    last = f"{str(len(mf.STRUCTURE_SECTIONS) + 1).translate(mf.ZEN_DIGITS)}．おわりに"      # 最後の章（節を足すと番号が変わる）
    assert last == "４．おわりに" and last in got["sec"] and got["ref"] == 1
    assert got["trans-abstract"] == ["Structure abstract."]
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
                  Options(out_dir=tmp_path / "out"))
    assert res.fidelity.ok and res.dtd_valid and res.lost_images == []
    assert [c.image_id for i in res.images for s in res.plan.slots if s.key == i.key for c in s.covers] == ["img1"]
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
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
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

    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    assert res.fidelity.ok and res.dtd_valid
    root = load(res)
    assert [text(n) for n in root.findall(".//contrib-group/contrib//name[@name-style='eastern']")] == ["試験七郎"]
    assert [text(s.find("title")) for s in root.iter("sec")] == ["１．はじめに"]
    assert root.find(".//body//table-wrap") is None
    reasons = {t: reason for _, reason, t in res.fidelity.excluded}
    assert reasons["特集　図形の中の表"] == "冒頭部の表（著者表以外）の文字"


# ----------------------------------------------------------------------------- 資料（付録）の見出し（修正計画の D3）
APPENDIX_YES = ["資料（授業プリント）", "資料Ⅰ\u3000授業プリント", "資料Ⅱ（ワークシート）", "付録①\u3000調査票", "資料1-2", "Appendix A",
                "資料\u3000授業プリント", "資料", "資料1", "資料１：調査票", "資料2. 授業記録", "資料1．授業記録", "【資料1】授業プリント",
                "［資料２］", "（資料3）ワークシート", "〈付録〉", "<資料1>", "資料－1", "資料‐2", "資料１－２", "資料 3", "\u3000資料3\u3000問題",
                "資料A", "資料Ａ\u3000調査票", "資料A-1", "資料1-2-3\u3000表", "Appendix", "Appendix B: Questionnaire",
                "Appendix Questionnaire", "附録1", "資料ⅰ\u3000授業記録", "資料⑳", "資料1、2", "資料1―授業", "資料―授業プリント―",
                "【資料1】ふりかえりシート", "（資料2）とけいの読み方", "Appendix A: questionnaire items", "Appendix 1. Tasks", "資料1．",
                # 括弧・かぎ括弧の中の「。」と、語・番号の後ろの「空白 + 英小文字」（0.23.1 でも見出し）
                "資料2\u3000架空の児童の記述（下線は筆者。）", "資料1\u3000架空の問い「なぜだろう。」の授業プリント",
                "Appendix 1 questionnaire", "Appendix A worksheet for the fictional lesson", "資料1 worksheet", "資料2 iPad の画面",
                "付録1 t検定の結果", "資料1 x と y の関係表", "資料 1 n=30 の結果", "Appendix questionnaire", "付録 web 調査票",
                "資料2 iPad の画面."]       # 和文の見出しは、「.」で終わっても英文の文とみなさない
APPENDIX_NO = ["資料を配布した。", "資料-1", "資料-1 を見よ", "資料1-", "資料1-授業", "資料12の結果", "資料1を配布した", "資料1は",
               "資料編", "資料提供", "資料の分析", "資料、図表", "資料.", "資料Aと資料B", "資料一", "資料Ⅰの", "付録として示す", "付録は",
               "Appendices", "Appendix-based"]
# RE_APPENDIX の形には合うが、文の形なので資料の見出しとみなさない段落（appendix_sentence）: 語・番号の後ろにかな・漢字があり「。」「．」で
# 終わる和文の文と、語・番号の後ろが「空白 + 英小文字」で「.」などで終わる英文の文。最後の「資料1　…。」は見出しかもしれないが、
# 文とみなす（判断の一覧に記録する。test_sentence_paragraphs_do_not_start_appendix）
APPENDIX_SENTENCES = ["(Appendix 1) lists the fictional tasks.", "(Appendix A) contains the questionnaire.", "Appendix A shows the data.",
                      "（資料1）に示すように、架空の児童は考えた。", "【資料1】に示すように，架空の問いを並べた。",
                      "資料1－2に示したように、架空の結果である。", "資料2（後掲）に示すように、架空の問いを並べた。",
                      "資料1、2は架空の授業の記録である。", "付録1，2に示す架空の問い。", "資料1）に示す架空の問いである。",
                      "資料（後掲）のとおり、架空の問いを並べた。", "資料－1 shows the fictional worksheet.",
                      "資料1，2は架空の授業の記録である．", "（資料1）に示すように，架空の問いを並べた．", "Appendix 1 lists the fictional tasks.",
                      "Appendix shows the data.", "Appendix abstract.", "資料1\u3000架空の授業プリント。"]


@pytest.mark.parametrize("s", APPENDIX_YES)
def test_appendix_heading_forms_are_recognized(s):
    # 先頭の括弧、語の後ろの全角のハイフン・枝番、ローマ数字・丸数字、番号の直後の括弧・ピリオド・読点・ダッシュ。
    # 閉じ括弧のすぐ後ろがひらがなの見出し（「【資料1】ふりかえりシート」）も見出し。括弧・かぎ括弧の中の「。」、語・番号の後ろが
    # 「空白 + 英小文字」の見出し（「Appendix 1 questionnaire」「資料2 iPad の画面」「付録 web 調査票」）も、0.23.1 と同じく見出し
    assert RE_APPENDIX.match(s) and appendix_heading(s) and appendix_sentence(s) == ""


@pytest.mark.parametrize("s", APPENDIX_NO)
def test_appendix_heading_forms_are_not_recognized(s):
    # 本文の文（「資料を配布した。」「資料12の結果」）、語の直後の ASCII のハイフン（「資料-1」）は、資料の見出しとみなさない
    assert not RE_APPENDIX.match(s) and not appendix_heading(s)


@pytest.mark.parametrize("s", APPENDIX_SENTENCES)
def test_sentences_are_not_appendix_headings(s):
    # 先頭の括弧・番号の直後の読点・括弧・番号の前の「－」を許した形（RE_APPENDIX）に合っても、文の形の段落は資料の見出しにしない
    # （英文要旨の文と後ろの段落が資料に移ったり、資料の中の文が新しい資料の見出しになったりするのを防ぐ）
    assert RE_APPENDIX.match(s) and not appendix_heading(s)
    assert appendix_sentence(s) == ("「。」か「．」で終わる和文の文" if s.endswith(("。", "．"))
                                    else "番号などの後ろが英小文字の語で、「.」などで終わる英文の文")


def apps(root):
    """資料（app-group/app）: [(見出し, [中の段落の文字])]。"""
    return [(text(a.find("title")), [text(p) for p in a.findall("p")]) for a in root.iter("app")]


def abstract_paras(root):
    return [text(p) for p in root.findall(".//trans-abstract/p")]


def test_appendix_with_paren_is_not_in_abstract(journal, meta, tmp_path):
    # 「資料」の直後がかっこの見出しも資料の見出しにし、続く段落を英文要旨（trans-abstract）に入れない
    # （docs/fix_plan_repro_tests.py の test_PROBLEM_appendix_with_paren_goes_into_abstract の逆）
    res = convert(STRUCTURE, meta, journal, Options(out_dir=tmp_path))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and res.jstage_issues == []
    root = load(res)
    assert apps(root) == [("資料（授業プリント）", ["問1\u3000架空の問題文である。", "問2\u3000もう一つの架空の問題文である。"])]
    assert abstract_paras(root) == ["Structure abstract."]
    assert res.plan.abstract_ja == [] and res.plan.app_after_refs == []        # 英文だけの英文要旨では知らせない
    assert not {"abstract_ja", "app_after_refs"} & {a.key for a in actions(res)}
    # 小さな論文（英文要旨の段落と、英文要旨のスタイルの資料）でも同じ
    path = tmp_path / "app.docx"
    mf.make_article(path, "資料の見出しの検証用文書", lambda b: [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "本文。")],
                    abstract=["This is the abstract."],
                    appendix=[mf.para(S["abs"], "資料（授業プリント）"), mf.para(S["abs"], "問1\u3000次の式を計算せよ。")])
    root = load(convert(path, meta, journal, Options(out_dir=tmp_path / "small")))
    assert apps(root) == [("資料（授業プリント）", ["問1\u3000次の式を計算せよ。"])]
    assert abstract_paras(root) == ["This is the abstract."]


def test_appendix_heading_variants_become_app_titles(journal, meta, tmp_path):
    # ローマ数字・丸数字の番号、番号の直後のかっこ。本文のスタイルの「付録①　…」も資料の見出しにする
    appendix = [mf.para(S["abs"], "資料Ⅰ\u3000授業プリント"), mf.para(S["abs"], "架空の授業プリントの本文である。"),
                mf.para(S["abs"], "資料Ⅱ（ワークシート）"), mf.para(S["abs"], "架空のワークシートの本文である。"),
                mf.para(S["body"], "付録①\u3000調査票"), mf.para(S["body"], "架空の調査票の本文である。")]
    path = tmp_path / "apps.docx"
    mf.make_article(path, "資料の見出しの検証用文書", lambda b: [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "本文。")],
                    appendix=appendix)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    assert res.fidelity.ok and res.dtd_valid and res.jstage_issues == []
    root = load(res)
    assert apps(root) == [("資料Ⅰ\u3000授業プリント", ["架空の授業プリントの本文である。"]),
                          ("資料Ⅱ（ワークシート）", ["架空のワークシートの本文である。"]),
                          ("付録①\u3000調査票", ["架空の調査票の本文である。"])]
    assert abstract_paras(root) == ["Small article abstract."]


def test_heading_style_after_abstract_starts_appendix(journal, meta, tmp_path):
    # 英文要旨の後ろの、章・節・項見出しのスタイルの段落から資料にする（英文要旨の中に見出しは来ないため。決定事項 8(a)）。
    # 文字が「資料」などで始まらなくてもよい。判断の一覧に記録する。資料の中の見出しのスタイルの段落は、資料の中の段落
    appendix = [mf.para(S["sec1"], "授業の記録"), mf.para(S["body"], "架空の授業の記録である。"),
                mf.para(S["sec2"], "記録の続き"), mf.para(S["body"], "続きの架空の記録である。")]
    path = tmp_path / "style.docx"
    mf.make_article(path, "見出しのスタイルの資料の検証用文書",
                    lambda b: [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "本文。")], appendix=appendix)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    assert res.fidelity.ok and res.dtd_valid and res.jstage_issues == []
    root = load(res)
    assert apps(root) == [("授業の記録", ["架空の授業の記録である。", "記録の続き", "続きの架空の記録である。"])]
    assert abstract_paras(root) == ["Small article abstract."]
    src = next(s for s, p in res.plan.paras.items() if p.plain() == "授業の記録")
    [d] = [d for d in res.plan.decisions if d.src == src]
    assert d.message == ("英文要旨の後ろの、見出しのスタイル「章見出し」の段落「授業の記録」から資料とした（英文要旨の中に見出しは来ないため）。"
                         "資料でなければ、Word でその段落のスタイルを英文要旨のスタイルに直して変換し直す（AI による補完では、"
                         "set_role の abstract で英文要旨に戻せる）")
    assert d.applied and d.location == "資料1（見出し）"


def test_sentence_paragraphs_do_not_start_appendix(journal, meta, tmp_path):
    # 英文要旨の中の「(Appendix 1) lists …」と、資料の中の「資料2（後掲）に示すように、…。」は文なので、資料の見出しにしない
    # （英文要旨の段落は英文要旨のまま、資料の中の文は前の資料の段落のまま）。文字の規則で始めた資料の見出しは判断の一覧
    # （4 章）に記録し、AI 依頼文の推定にも載せる（見出しと誤ったときに気づけるように）
    path = tmp_path / "sentence.docx"
    mf.make_article(path, "資料の見出しと文の検証用文書", lambda b: [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "本文。")],
                    abstract=["Small article abstract.", "(Appendix 1) lists the fictional tasks used in the lesson.",
                              "The last fictional sentence of the abstract."],
                    appendix=[mf.para(S["abs"], "資料1\u3000架空の授業プリント"), mf.para(S["abs"], "問1\u3000架空の問い。"),
                              mf.para(S["abs"], "資料2（後掲）に示すように、架空の問いを並べた。"), mf.para(S["abs"], "最後の架空の文。")])
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", ai_mode="manual"))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and res.jstage_issues == []
    root = load(res)
    assert abstract_paras(root) == ["Small article abstract.", "(Appendix 1) lists the fictional tasks used in the lesson.",
                                    "The last fictional sentence of the abstract."]
    assert apps(root) == [("資料1\u3000架空の授業プリント", ["問1\u3000架空の問い。", "資料2（後掲）に示すように、架空の問いを並べた。",
                                                      "最後の架空の文。"])]
    src = next(s for s, p in res.plan.paras.items() if p.plain() == "資料1\u3000架空の授業プリント")
    [d] = [d for d in res.plan.decisions if d.src == src]
    assert d.message == ("段落「資料1\u3000架空の授業プリント」を資料の見出しとした（「資料」「付録」「附録」「Appendix」で始まる見出しの"
                         "形のため）。資料の見出しでなければ、AI による補完の set_role で英文要旨の段落（abstract）に戻せる")
    assert d.applied and d.location == "資料1（見出し）" and d.category == "style"
    assert f"- [{src}] 推定: 段落「資料1\u3000架空の授業プリント」を資料の見出しとした" in res.prompt_path.read_text(encoding="utf-8")
    report = res.report_path.read_text(encoding="utf-8")
    assert "| 資料1（見出し） | 段落「資料1\u3000架空の授業プリント」を資料の見出しとした" in report.split("## 4.")[1].split("## 5.")[0]
    # 見出しの形に合うが文とみなした段落も、判断の一覧（applied=False）と AI 依頼文の推定に載せる（見出しを文と誤ったときに
    # 気づけるように。英文要旨の段落なら見出しのスタイルで、資料の中の段落なら AI の app_heading で資料にできる）
    sentences = {}
    for t in ("(Appendix 1) lists the fictional tasks used in the lesson.", "資料2（後掲）に示すように、架空の問いを並べた。"):
        src2 = next(s for s, p in res.plan.paras.items() if p.plain() == t)
        [d] = [d for d in res.plan.decisions if d.src == src2]
        assert not d.applied and d.category == "style"
        sentences[t] = d
        assert f"- [{src2}] 推定: 段落「{t[:20]}」は「資料」「付録」「附録」「Appendix」で始まるが、" in res.prompt_path.read_text(encoding="utf-8")
    d = sentences["(Appendix 1) lists the fictional tasks used in the lesson."]
    assert d.location == "英文要旨 第2段落" and d.message == (
        "段落「(Appendix 1) lists t」は「資料」「付録」「附録」「Appendix」で始まるが、番号などの後ろが英小文字の語で、「.」などで"
        "終わる英文の文の形なので、資料の見出しにしなかった（英文要旨の段落のまま）。資料の見出しなら、Word でその段落に章・節・項"
        "見出しのスタイルを付けて変換し直すと、文字はそのままで資料になる（AI による補完では、set_role の app_heading で資料にできる）")
    d = sentences["資料2（後掲）に示すように、架空の問いを並べた。"]
    assert d.location == "資料1 第2要素" and d.message == (
        "段落「資料2（後掲）に示すように、架空の問いを」は「資料」「付録」「附録」「Appendix」で始まるが、「。」か「．」で終わる和文の"
        "文の形なので、資料の見出しにしなかった（前の資料の段落のまま）。資料の見出しなら、AI による補完の set_role の app_heading で"
        "資料にできる")
    assert "| 資料1 第2要素 | 段落「資料2（後掲）に示すように、架空の問いを」は" in report.split("## 4.")[1].split("## 5.")[0]
    # 2 つ目の資料の見出しの判断は、前の資料の段落に戻す案内（p）にする
    path = tmp_path / "second.docx"
    mf.make_article(path, "資料の見出しと文の検証用文書", lambda b: [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "本文。")],
                    appendix=[mf.para(S["abs"], "資料1\u3000架空の授業プリント"), mf.para(S["abs"], "問1\u3000架空の問い。"),
                              mf.para(S["abs"], "資料2：架空の回答の例"), mf.para(S["abs"], "架空の回答の本文。")])
    _, plan, _ = _mechanical(path, journal)
    src = next(s for s, p in plan.paras.items() if p.plain() == "資料2：架空の回答の例")
    [d] = [d for d in plan.decisions if d.src == src]
    assert d.message.endswith("資料の見出しでなければ、AI による補完の set_role で前の資料の段落（p）に戻せる")


@pytest.mark.parametrize("appendix, expected", [
    # 括弧の中に「。」がある、最初の資料の見出し（点検の 1 回目の修正の後は、見出しと資料の段落が英文要旨に入っていた）
    ([("abs", "資料1\u3000架空の授業プリント（一部抜粋。）"), ("abs", "問1\u3000架空の問い。"), ("abs", "問2\u3000もう一つの架空の問い。")],
     [("資料1\u3000架空の授業プリント（一部抜粋。）", ["問1\u3000架空の問い。", "問2\u3000もう一つの架空の問い。"])]),
    # 2 つ目からの資料の見出し（括弧の中の「。」、語・番号の後ろが「空白 + 英小文字」の和文の見出し。修正の後は前の資料につながり、
    # どこにも知らせが出なかった）
    ([("abs", "資料1\u3000架空の授業プリント"), ("abs", "問1\u3000架空の問い。"), ("abs", "資料2\u3000架空の児童の記述（下線は筆者。）"),
      ("abs", "架空の児童の記述の文。"), ("body", "資料3 iPad の画面"), ("body", "架空の画面の説明。"),
      ("abs", "資料4\u3000架空の問い「なぜだろう。」の授業プリント"), ("abs", "架空のプリントの本文。")],
     [("資料1\u3000架空の授業プリント", ["問1\u3000架空の問い。"]), ("資料2\u3000架空の児童の記述（下線は筆者。）", ["架空の児童の記述の文。"]),
      ("資料3 iPad の画面", ["架空の画面の説明。"]), ("資料4\u3000架空の問い「なぜだろう。」の授業プリント", ["架空のプリントの本文。"])]),
    # 番号の後ろが英小文字の英文の見出し（英文の終わりの「.」がないので、文とみなさない）
    ([("abs", "Appendix 1 questionnaire"), ("abs", "Q1. How did you solve the fictional task?"),
      ("abs", "Appendix 2 lesson plan of the fictional class"), ("abs", "The fictional plan.")],
     [("Appendix 1 questionnaire", ["Q1. How did you solve the fictional task?"]),
      ("Appendix 2 lesson plan of the fictional class", ["The fictional plan."])]),
])
def test_appendix_headings_with_period_inside_or_lower_case_word(journal, meta, tmp_path, appendix, expected):
    # 括弧・かぎ括弧の中に「。」がある見出しと、語・番号の後ろが「空白 + 英小文字」の見出しは、0.23.1 と同じく資料の見出しにする
    # （文とみなすのは、「。」か「．」で終わる和文と、「.」などで終わる英文だけ。appendix_sentence）
    path = tmp_path / "heads.docx"
    mf.make_article(path, "資料の見出しの検証用文書", lambda b: [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "本文。")],
                    appendix=[mf.para(S[style], t) for style, t in appendix])
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and res.jstage_issues == []
    root = load(res)
    assert apps(root) == expected
    assert abstract_paras(root) == ["Small article abstract."]
    assert res.plan.abstract_ja == [] and not any(not d.applied for d in res.plan.decisions if d.category == "style")


def test_japanese_paragraph_in_abstract_is_reported(journal, meta, tmp_path):
    # 和文の論文で、英文要旨の中に、かな・漢字が 3 割以上の段落があれば知らせる（資料などの和文が英文要旨に入っているかも
    # しれない）。自動では移さない。判断の一覧（applied=False）、10 章の警告、レポートの冒頭と 14 章の要確認
    path = tmp_path / "ja.docx"
    mf.make_article(path, "英文要旨の中の和文の検証用文書",
                    lambda b: [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "本文。")],
                    abstract=["Small article abstract.", "問2\u3000架空の和文の問題文である。", "A few 漢字 in English."])
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    assert res.fidelity.ok and res.dtd_valid and res.jstage_issues == []
    assert abstract_paras(load(res)) == ["Small article abstract.", "問2\u3000架空の和文の問題文である。", "A few 漢字 in English."]
    src = next(s for s, p in res.plan.paras.items() if p.plain().startswith("問2"))
    assert res.plan.abstract_ja == [src]                 # 漢字が 3 割未満の段落は知らせない
    [d] = [d for d in res.plan.decisions if d.src == src]
    assert not d.applied and d.message.startswith("英文要旨の段落「問2\u3000架空の和文の問題文である。」は、かな・漢字が 3 割以上ある")
    assert [w for w in res.warnings if w.startswith(f"{src}:")] == [
        (f"{src}: 英文要旨の段落「問2\u3000架空の和文の問題文である。」に、かな・漢字が 3 割以上あります。資料などの和文なら、Word で"
         "資料の見出しの段落に章・節・項見出しのスタイルを付けて（見出しがなければ、資料の前に「資料1」などの見出しを付けて）変換し直して"
         "ください")]
    assert {a.level for a in actions(res) if a.key == "abstract_ja"} == {TO_CHECK} and not res.needs_action
    report = res.report_path.read_text(encoding="utf-8")
    top, ch14 = report.split("## 2.")[0], report.split("## 14.")[1]
    assert "> **要確認: 英文要旨に、和文と思われる段落が 1 件あります（10 章）。**" in top
    assert f"対象の段落: {src}「問2\u3000架空の和文の問題文である…」" in top        # 段落の例は 15 文字まで
    assert "- [ ] **英文要旨の中の和文の段落**（1 件。10 章）" in ch14
    assert ("資料なら、Word で資料の見出しの段落に章・節・項見出しのスタイルを付けて（見出しがなければ、資料の前に「資料1」"
            "「資料（授業プリント）」などの見出しを付けて）、変換し直してください。") in top
    # 境目: かな・漢字がちょうど 3 割の段落は知らせ、2 割の段落は知らせない（空白は数えない）
    path = tmp_path / "ratio.docx"
    mf.make_article(path, "英文要旨の中の和文の境目の検証用文書",
                    lambda b: [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "本文。")],
                    abstract=["Small article abstract.", "ABC DEFG 漢字三", "ABCDEFGH 漢字"])
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "ratio"))
    assert [res.plan.paras[s].plain() for s in res.plan.abstract_ja] == ["ABC DEFG 漢字三"]


def test_sentence_shaped_heading_in_abstract_gets_style_guidance(journal, meta, tmp_path):
    # 「資料1　…。」のように「。」で終わる見出しは文とみなすので、最初の資料なら見出しと資料の段落が英文要旨に入る。この段落の
    # 知らせ（10 章の警告）は、見出しを付ける案内ではなく、その段落に見出しのスタイルを付ける案内にする（見出しはもう付いている）。
    # 見出しのスタイルを付ければ、文字はそのままで資料になる
    def make(style):
        path = tmp_path / f"{style}.docx"
        mf.make_article(path, "資料の見出しの検証用文書", lambda b: [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "本文。")],
                        appendix=[mf.para(S[style], "資料1\u3000架空の授業プリント。"), mf.para(S["abs"], "問1\u3000架空の和文の問いである。")])
        return convert(path, meta, journal, Options(out_dir=tmp_path / style))
    res = make("abs")
    assert res.fidelity.ok and res.dtd_valid
    root = load(res)
    assert root.find(".//app-group") is None
    assert abstract_paras(root) == ["Small article abstract.", "資料1\u3000架空の授業プリント。", "問1\u3000架空の和文の問いである。"]
    head, q = (next(s for s, p in res.plan.paras.items() if p.plain() == t)
               for t in ("資料1\u3000架空の授業プリント。", "問1\u3000架空の和文の問いである。"))
    assert res.plan.abstract_ja == [head, q]
    assert [w for w in res.warnings if w.startswith(f"{head}:")] == [
        (f"{head}: 英文要旨の段落「資料1\u3000架空の授業プリント。」に、かな・漢字が 3 割以上あります。この段落は「資料」などで"
         "始まりますが、「。」か「．」で終わる和文の文の形なので、資料の見出しにしていません。資料の見出しなら、Word でこの段落に"
         "章・節・項見出しのスタイルを付けて変換し直してください（文字はそのままで資料になります）")]
    [warning] = [w for w in res.warnings if w.startswith(f"{q}:")]
    assert warning.endswith("資料などの和文なら、Word で資料の見出しの段落に章・節・項見出しのスタイルを付けて（見出しがなければ、資料の前に"
                            "「資料1」などの見出しを付けて）変換し直してください")
    assert [d.applied for d in res.plan.decisions if d.src == head] == [False, False]   # 文とみなした判断と、和文の判断
    res = make("sec1")                                                                  # 案内のとおり見出しのスタイルを付けると資料
    root = load(res)
    assert apps(root) == [("資料1\u3000架空の授業プリント。", ["問1\u3000架空の和文の問いである。"])]
    assert abstract_paras(root) == ["Small article abstract."] and res.plan.abstract_ja == []


def test_japanese_paragraph_in_abstract_of_english_article_is_not_reported(journal, tmp_path):
    # 英文の論文（設定 lang が en）では、英文要旨にかな・漢字の多い段落があっても知らせない（和文の論文だけで知らせる）
    path = tmp_path / "en.docx"
    mf.make_article(path, "英文の論文の検証用文書", lambda b: [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "本文。")],
                    abstract=["Small article abstract.", "問2\u3000架空の和文の問題文である。"])
    _, plan, _ = _mechanical(path, dataclasses.replace(journal, lang="en"))
    assert plan.lang == "en" and plan.abstract_ja == [] and plan.warnings == []
    assert not any(d.message.startswith("英文要旨の段落") for d in plan.decisions)
    _, plan, _ = _mechanical(path, journal)                       # 和文の論文なら知らせる
    assert [plan.paras[s].plain() for s in plan.abstract_ja] == ["問2\u3000架空の和文の問題文である。"]


def test_appendix_after_references_is_warned(journal, meta, tmp_path):
    # 引用文献の後ろの、章見出しのスタイルの「資料　…」と本文のスタイルの「資料2　…」。暫定の判断で資料（app-group）にはせず、
    # 引用文献の段落のまま出力して（文字は落とさない）、10 章の警告とレポートの冒頭・14 章の要確認で知らせる（決定事項 8(b) は
    # 利用者に未確認）。参考文献のスタイルの段落は、「資料」で始まっても引用文献の 1 件として知らせない。空白だけの見出しのスタイルの
    # 段落と、引用文献を分ける見出しのスタイルの小見出し（「＜英文献＞」。資料の見出しの形でない）も知らせない
    refs = [mf.para(S["ref"], "資料\u3000架空統計（2023）．『架空の統計』．架空出版．"), mf.para(S["sec1"], "\u3000"),
            mf.para(S["sec3"], "＜英文献＞"), mf.para(S["ref"], "Shiken, R. (2023). A fictional paper. Fictional Journal, 1, 1-2."),
            mf.para(S["sec1"], "資料\u3000架空の授業プリント"), mf.para(S["body"], "架空の授業プリントの本文である。"),
            mf.para(S["body"], "資料2\u3000架空のワークシート"), mf.para(S["body"], "架空のワークシートの本文である。"),
            mf.para(S["body"], "資料3\u3000架空の調査問題（一部抜粋。）"),      # 括弧の中の「。」は文の終わりでない（知らせる）
            mf.para(S["body"], "資料1、2は架空の授業の記録である。")]          # 文の形の段落は知らせない（appendix_heading）
    path = tmp_path / "after.docx"
    mf.make_article(path, "引用文献の後ろの資料の検証用文書", lambda b: [mf.para(S["sec1"], "１．はじめに"),
                                                                     mf.para(S["body"], "試験（2024）にならう。")],
                    refs=lambda b: refs)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    assert res.fidelity.ok and res.dtd_valid
    root = load(res)
    assert root.find(".//app-group") is None and abstract_paras(root) == ["Small article abstract."]
    xml = text(root)
    assert "資料\u3000架空の授業プリント" in xml and "架空の授業プリントの本文である。" in xml
    src = next(s for s, p in res.plan.paras.items() if p.plain() == "資料\u3000架空の授業プリント")
    src2 = next(s for s, p in res.plan.paras.items() if p.plain() == "資料2\u3000架空のワークシート")
    src3 = next(s for s, p in res.plan.paras.items() if p.plain() == "資料3\u3000架空の調査問題（一部抜粋。）")
    assert res.plan.app_after_refs == [src, src2, src3] and res.plan.region[src] == res.plan.region[src2] == "refs"
    entry = next(s for s, p in res.plan.paras.items() if p.plain().startswith("資料\u3000架空統計"))
    assert entry in [r.para.src for r in res.plan.refs]          # 参考文献のスタイルの段落は引用文献の 1 件のまま（知らせない）
    assert f"{src}: 引用文献の中に、資料の見出しと思われる段落「資料\u3000架空の授業プリント」があります。今の版では、" in "".join(res.warnings)
    assert {a.level for a in actions(res) if a.key == "app_after_refs"} == {TO_CHECK}
    report = res.report_path.read_text(encoding="utf-8")
    assert "> **要確認: 引用文献などの後ろに、資料の見出しと思われる段落があります（10 章）。**" in report.split("## 2.")[0]
    assert "- [ ] **引用文献などの後ろの資料の見出し**（3 件。10 章）" in report.split("## 14.")[1]


# ----------------------------------------------------------------------------- 文字だけのテキストボックス（修正計画の D1）
def boxes(root):
    """boxed-text ごとの (親の要素名, 直前の要素の文字, 直後の要素の文字, 中の要素の名前の並び)。"""
    out = []
    for bt in root.iter("boxed-text"):
        prev, nxt = bt.getprevious(), bt.getnext()
        out.append((bt.getparent().tag, text(prev) if prev is not None else None, text(nxt) if nxt is not None else None,
                    [c.tag for c in bt]))
    return out


def excluded(res):
    return {t: reason for _, reason, t in res.fidelity.excluded}


def _convert_structure(journal, meta, tmp_path, **kw):
    res = convert(STRUCTURE, meta, journal, Options(out_dir=tmp_path, **kw))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and res.jstage_issues == []
    return res


def test_box_at_anchor_becomes_boxed_text(journal, meta, tmp_path):
    # (a) 図の左上がアンカー段落の左上にある幅の広い囲みは、アンカー段落の前の <boxed-text>。中の自動番号の段落は <list>、
    # 「(1)」の付いた別行数式は FD1（本文の「式(1)」からリンク）、全角空白だけの段落は空白の除外
    res = _convert_structure(journal, meta, tmp_path)
    root = load(res)
    [a] = [b for b in boxes(root) if b[2] == "試験（2025）の問題を次に示す。"]
    assert a == ("sec", "３．囲みと図の注記", "試験（2025）の問題を次に示す。", ["p", "list", "p", "disp-formula"])
    bt = next(bt for bt in root.iter("boxed-text") if text(bt).startswith("問1"))
    assert bt.get("id") is None and bt.find("disp-formula").get("id") == "FD1"
    assert text(bt.find("disp-formula/label")) == "(1)"
    assert [text(li) for li in bt.findall("list/list-item/p")] == ["底辺と高さを測る。", "面積の式に当てはめる。"]
    assert [(x.text, x.get("rid")) for x in root.iter("xref") if x.get("ref-type") == "disp-formula"] == [("式(1)", "FD1")]
    assert excluded(res)["　"] == "空白のみの段落"
    assert not any(t.startswith("問1") for t in excluded(res))
    # (c) 段落の末尾の行内の囲みは、アンカー段落の後ろ。どちらも知らせない（位置は docx から決まる）
    [c] = [b for b in boxes(root) if b[1] == "次の囲みを読む。"]
    assert c == ("sec", "次の囲みを読む。", "囲みの後の段落である。", ["p", "p"])
    info = {x: bi for x, bi in res.plan.textboxes.items()}
    assert sorted((bi.kind, bi.where, bi.estimated) for bi in info.values() if bi.kind == "box") == [
        ("box", "after", False), ("box", "after", True), ("box", "before", False)]
    assert "| 囲み・図の注記（テキストボックス） |" in res.report_path.read_text(encoding="utf-8").split("## 4.")[1]


def test_label_and_undecided_textboxes_are_excluded(journal, meta, tmp_path, capsys):
    # (b) 画像・図キャプションの次の段落の小さな「A 点」は、図に重ねた注記として除外し、10 章に警告を出す（要確認にはしない）。
    # (d) 幅が広く短い「（ヒント）」と、N2 の「注」「Area model」は、囲みか注記か決められないので除外し、要確認で知らせる
    # （AI による補完を勧める。止めない。終了コードは 0）。空のテキストボックスと全角空白だけのテキストボックスは何も知らせない
    from jasme_jats.structure import TEXTBOX_LABEL_EXCLUDED, TEXTBOX_UNDECIDED_EXCLUDED
    res = _convert_structure(journal, meta, tmp_path)
    keys = fill_images(res)         # 図の画像の手順（必須）を済ませる
    ex = excluded(res)
    assert ex["A 点"] == TEXTBOX_LABEL_EXCLUDED
    assert ex["（ヒント）"] == ex["注"] == ex["Area model"] == TEXTBOX_UNDECIDED_EXCLUDED
    assert any("図に重ねた注記と判断したテキストボックス" in w for w in res.warnings)
    root = load(res)
    assert "A 点" not in text(root) and "（ヒント）" not in text(root)
    kinds = sorted(bi.kind for bi in res.plan.textboxes.values())
    assert kinds.count("blank") == 2 and kinds.count("undecided") == 3 and kinds.count("label") == 1
    acts = {a.key: a for a in actions(res)}
    assert acts["textbox_undecided"].level == TO_CHECK and "label" not in acts
    assert not any(a.level == NEEDS_ACTION for a in actions(res)) and not res.needs_action
    report = res.report_path.read_text(encoding="utf-8")
    top, ch14 = report.split("## 2.")[0], report.split("## 14.")[1]
    ch3 = report.split("## 3.")[1].split("## 4.")[0]
    assert ("**要確認: 囲み（問題文・ヒントなど）か図の注記か決められなかったテキストボックスが 3 件あり、その文字を XML に"
            "出力していません（3 章・6 章）。**") in top and "AI による補完を使うと" in top
    assert "| テキストボックスの文字（3 章・4 章・6 章・10 章） | 囲み 3 件（boxed-text。うち位置を推定 1 件・要確認）、図の注記として除外 1 件、" \
           "決められずに除外 3 件（要確認） |" in top
    assert "- [ ] **囲みか図の注記か決められなかったテキストボックス 3 件**" in ch14
    assert "| 囲み・図の注記 |" in ch3 and "テキストボックス" in ch3 and "「（ヒント）」" in ch3
    # 暫定の知らせ（0.19.0〜0.24.1）は出さない
    assert "テキストボックスの中の文字" not in report
    # コマンドライン: 要確認なので終了コード 0、標準エラーに出す
    from jasme_jats.cli import main
    m = tmp_path / "meta.toml"
    m.write_text('[article]\nvolume = "31"\nissue = "1"\nfpage = "1"\npeer_review = "あり"\n', encoding="utf-8")
    assert main([str(STRUCTURE), "--meta", str(m), "--out", str(tmp_path / "cli"),
                 "--images", str(image_folder(tmp_path / "pics", keys))]) == 0
    err = capsys.readouterr().err
    assert "要確認: 囲みか図の注記か決められなかったテキストボックス 3 件の文字を XML に出力していません" in err
    assert "要確認: 位置を推定して置いた囲み 1 件" in err


def test_vml_absolute_box_and_caption_textbox(journal, meta, tmp_path):
    # (e) VML だけの、位置を指定した（position:absolute）囲みは、位置を推定してアンカー段落の後ろに置き、要確認（3 章の
    # 「囲み・図の注記」）。(f) 図キャプションだけのテキストボックスは、今までどおり隣の画像と組んだ図のキャプション
    res = _convert_structure(journal, meta, tmp_path)
    root = load(res)
    [e] = [b for b in boxes(root) if b[1] == "枠の中の問題を考える。"]
    assert e[0] == "sec" and e[3] == ["p", "p"]
    [bi] = [bi for bi in res.plan.textboxes.values() if bi.estimated]
    assert bi.box.source == "vml" and bi.box.absolute and "position:absolute" in bi.place_why
    assert res.plan.box_place(bi.box.xid) == "段落「枠の中の問題を考える。」の後ろ"
    acts = {a.key: a for a in actions(res)}
    assert acts["textbox_place"].level == TO_CHECK and "段落「枠の中の問題を考える。」の後ろ" in acts["textbox_place"].top
    [row] = [u for u in res.unresolved_after if u[0] == "box" and "問3" in u[2]]
    assert "位置は推定" in row[3] and "boxed-text を正しい位置に移す" in row[3]
    fig = next(f for f in root.iter("fig") if text(f.find("caption")) == "図2　テキストボックスのキャプション")
    assert fig.find("graphic") is not None


def test_vml_width_in_cm_near_image_is_undecided(journal, meta, tmp_path):
    # VML の幅が pt 以外（cm・%）で読めないときは、画像の近くの短い文字でも図の注記（黙って除外）に倒さず、決められないもの
    # （要確認）にする（修正計画の付録の D1「VML の width が pt 以外のとき、label に倒れない」）。幅を pt で書けば注記になる
    def parts(width):
        def make(b):
            rid = b.add_image("vmlcm.png", mf.png_bytes("Figure"))
            return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "試験（2024）の図を示す。"),
                    mf.para(S["body"], mf.drawing(rid, 1800000, 1080000, 3201)),
                    mf.para(S["body"], "画像の後ろの段落に札が付く。",
                            mf.vml_textbox(mf.para(S["body"], "（ヒント）"), width=width, height="1cm")),
                    mf.para(S["body"], "札の後ろの本文である。")]
        return make
    kinds = {}
    for width in ("14cm", "40%", "20pt"):
        path = tmp_path / f"vml_{width.replace('%', 'pct')}.docx"
        mf.make_article(path, "VML の札の検証用文書", parts(width))
        res = convert(path, meta, journal, Options(out_dir=tmp_path / path.stem))
        assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and res.jstage_issues == []
        [bi] = res.plan.textboxes.values()
        kinds[width] = (bi.kind, bi.box.width_cm is None, bi.near)
        if bi.kind == "undecided":
            assert "textbox_undecided" in [a.key for a in actions(res)] and "幅は読めない" in bi.why
    assert kinds == {"14cm": ("undecided", True, True), "40%": ("undecided", True, True), "20pt": ("label", False, True)}


def test_box_at_body_top_is_wrapped_in_p(journal, meta, tmp_path):
    # 本文の最上位（最初の章見出しの前）の囲みは <p> で包む（J-STAGE の <body> の子は <p> と <sec> だけ。DTD にも合う）
    tb = mf.textbox(mf.para(S["body"], "問1　架空の冒頭の問題である。答えを一つ書け。") + mf.para(S["body"], "ヒント　図をかく。"),
                    901, cx=12 * 360000, cy=2 * 360000)
    path = tmp_path / "top.docx"
    mf.make_article(path, "冒頭の囲みの検証用文書", lambda b: [mf.para(S["body"], "冒頭の段落に囲みを結び付けた。", tb),
                                                         mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "試験（2024）の本文。")])
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    assert res.fidelity.ok and res.dtd_valid and res.jstage_issues == []
    root = load(res)
    assert root.find("body/boxed-text") is None
    bt = root.find("body/p/boxed-text")
    assert [text(p) for p in bt.findall("p")] == ["問1　架空の冒頭の問題である。答えを一つ書け。", "ヒント　図をかく。"]
    assert text(bt.getparent().getnext()) == "冒頭の段落に囲みを結び付けた。"


def test_text_only_textbox_becomes_boxed_text(journal, meta, tmp_path):
    """囲み（テキストボックス）に入れた問題文の文字を XML の <boxed-text> に出す（docs/fix_plan_repro_tests.py の
    test_PROBLEM_text_only_textbox_is_dropped_from_xml の逆。0.24.1 までは除外して 6 章に載るだけだった）。囲みとして位置を
    機械的に決めた浮動配置のテキストボックスの段落への set_role p は、機械的に決めたので変更できないとして採用しない
    （placements でも変えられないので、placements は案内しない）。"""
    import json
    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"),
                mf.para(S["body"], "次の問題を扱う。", mf.textbox(
                    mf.para(S["body"], "問1　次の二次方程式を解きなさい。")
                    + mf.para(S["body"], "ヒント: 因数分解を使う。"), 401, cx=5000000, cy=800000)),
                mf.para(S["body"], "以上が問題である。")]
    path = tmp_path / "box.docx"
    mf.make_article(path, "囲みの検証用文書", parts)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    assert res.fidelity.ok and res.dtd_valid
    bt = load(res).find(".//boxed-text")
    assert [text(p) for p in bt.findall("p")] == ["問1　次の二次方程式を解きなさい。", "ヒント: 因数分解を使う。"]
    assert not any("二次方程式" in t for t in excluded(res))
    _, plan, _ = _mechanical(path, journal)
    src = next(s for s, p in plan.paras.items() if "二次方程式" in p.plain())
    resp = {"operations": [{"op": "set_role", "src": src, "text": "", "occurrence": 1, "target": "", "role": "p",
                            "image": "", "mathml": "", "surname": "", "given": "", "reason": "x", "confidence": "高"}],
            "placements": [], "notes": []}
    res2 = convert(path, meta, journal, Options(out_dir=tmp_path / "ai", ai_mode="manual",
                                                ai_response=json.dumps(resp, ensure_ascii=False)))
    assert res2.ai.rejected and res2.ai.rejected[0][1].endswith("は囲み（boxed-text）として扱いと位置を機械的に決めたので、変更できない")
    assert text(load(res2).find(".//boxed-text")).startswith("問1　次の二次方程式を解きなさい。")


BOX_Q = "問Ａ　架空の町の二つの公園の間の道のりを，地図の縮尺を使って求めなさい。"
BOX_H = "考え方　縮尺の分母をかけると実際の長さになることを使い，単位をそろえてから比べること。"
BOX_Q2 = "問Ｂ　架空の電車が一定の速さで進むとき，進んだ時間と道のりの関係を式に表しなさい。"


def _box_between(variant):
    """画像と図キャプション（または表キャプションと表）の間に囲みがある本文（test_boxes_do_not_split_figures）。"""
    cm = 360000
    box1 = mf.para(S["body"], BOX_Q) + mf.para(S["body"], BOX_H)
    box2 = mf.para(S["body"], BOX_Q2) + mf.para(S["body"], "答えは一つの式にまとめ，理由を表で説明すること。")

    def parts(b):
        out = [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "試験（2024）の地図を次に示す。")]
        if variant == "table":
            # 本文スタイルの表キャプションの段落に行内の囲み、続いて表
            tbl = mf.table([[mf.cell("区分"), mf.cell("人数")], [mf.cell("一組"), mf.cell("三十人")]])
            return out + [mf.para(S["body"], "表1　架空の集計", mf.textbox_inline(box1, 3301, cx=8 * cm, cy=3 * cm)), tbl,
                          mf.para(S["body"], "表1のとおりである。")]
        rid = b.add_image("between.png", mf.png_bytes("Fictional map", size=(300, 200)))
        if variant == "inline":
            # 画像の段落の中の行内の囲み 1 つと、本文スタイルの図キャプション（キャプションの推定が隣の画像を見る）
            out += [mf.para(S["body"], mf.drawing(rid, 1800000, 1200000, 3302),
                            mf.textbox_inline(box1, 3303, cx=8 * cm, cy=3 * cm)),
                    mf.para(S["body"], "図1　架空の地図")]
        else:
            # キャプションのスタイルの図キャプションの段落に、左上がそろった囲みが 2 つ（画像とキャプションの間に囲みが 2 つ）
            out += [mf.para(S["body"], mf.drawing(rid, 1800000, 1200000, 3304)),
                    mf.para(S["fig_cap"], "図1　架空の地図",
                            mf.textbox(box1, 3305, cx=8 * cm, cy=3 * cm, wrap="wrapTopAndBottom"),
                            mf.textbox(box2, 3306, cx=8 * cm, cy=3 * cm, wrap="wrapTopAndBottom"))]
        return out + [mf.para(S["body"], "図1から道のりが分かる。")]
    return parts


@pytest.mark.parametrize("variant", ["inline", "two_boxes", "table"])
def test_boxes_do_not_split_figures(variant, journal, meta, tmp_path):
    """囲み（boxed-text）は、図表の組み立てで隣の要素として数えない（点検の指摘。0.24.1 までは囲みの文字を除外していたので、
    画像と図キャプション、表キャプションと表の間に囲みがあっても組めていた）。画像の段落の行内の囲みと本文スタイルの図キャプション
    （inline）、図キャプションの段落の左上の囲み 2 つ（two_boxes）、本文スタイルの表キャプションの段落の行内の囲みと表（table）の
    どれでも、図・表に ID とキャプションが付き、本文の「図1」「表1」がリンクになる。囲みは組み立てた図表の隣に出る。"""
    path = tmp_path / f"{variant}.docx"
    mf.make_article(path, "囲みと図の検証用文書", _box_between(variant))
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    fill_images(res)                # 図の画像の手順（必須）を済ませ、ほかの知らせを今までどおり確かめる
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and res.jstage_issues == []
    assert res.lost_images == [] and others(res) == []
    root = load(res)
    sec = root.find("body/sec")
    tags = [el.tag for el in sec if el.tag != "title"]
    bts = list(root.iter("boxed-text"))
    assert [text(bt.find("p")) for bt in bts] == ([BOX_Q] if variant != "two_boxes" else [BOX_Q, BOX_Q2])
    assert all(bt.getparent() is sec for bt in bts)
    if variant == "table":
        assert tags == ["p", "table-wrap", "boxed-text", "p"]
        tw = root.find(".//table-wrap")
        assert tw.get("id") == "T1" and text(tw.find("caption")) == "表1　架空の集計" and tw.find("table") is not None
        assert [(x.text, x.get("rid")) for x in root.iter("xref") if x.get("ref-type") == "table"] == [("表1", "T1")]
        return
    assert tags == ["p"] + ["boxed-text"] * len(bts) + ["fig", "p"]
    [fig] = root.iter("fig")
    assert fig.get("id") == "F1" and text(fig.find("caption")) == "図1　架空の地図" and fig.find("graphic") is not None
    assert [(x.text, x.get("rid")) for x in root.iter("xref") if x.get("ref-type") == "fig"] == [("図1", "F1")]


SOURCE_NOTE = "出典：架空の町の資料（2020）をもとに作成した。"


def _figure_textbox(floating):
    """図の画像・図キャプション・出典の文を入れたテキストボックス（行内。floating なら、位置を決められない浮動配置）。"""
    def parts(b):
        rid = b.add_image("figtb.png", mf.png_bytes("Fictional town", size=(300, 200)))
        inner = (mf.para(S["body"], mf.drawing(rid, 1800000, 1200000, 3402)) + mf.para(S["fig_cap"], "図1　架空の町の地図")
                 + mf.para(S["body"], SOURCE_NOTE))
        tb = (mf.textbox(inner, 3401, cx=8 * 360000, cy=5 * 360000, v=("paragraph", 2 * 360000), wrap="wrapTopAndBottom")
              if floating else mf.textbox_inline(inner, 3401, cx=8 * 360000, cy=5 * 360000))
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "試験（2024）の地図を図1に示す。", tb),
                mf.para(S["body"], "図1から町の様子が分かる。")]
    return parts


def test_text_in_figure_textbox_is_notified(journal, meta, tmp_path):
    """図表の入ったテキストボックスの中の、キャプションでも図の本体でもない文字（出典など）は、今までどおり図の一部とみなして
    出力しないが、要確認で知らせる（点検の指摘。0.24.1 では暫定の知らせが数えていたが、0.25.0 の最初の実装では 6 章に載るだけ
    だった）。AI の placements では戻せず、set_role も fig_caption・table_caption・exclude 以外は採用しない（理由で placements を案内しない）。"""
    from jasme_jats.structure import TEXTBOX_TEXT_EXCLUDED
    path = tmp_path / "figtb.docx"
    mf.make_article(path, "図のテキストボックスの検証用文書", _figure_textbox(False))
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "none"))
    fill_images(res)                # 図の画像の手順（必須）を済ませ、ほかの知らせを今までどおり確かめる
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and res.lost_images == []
    assert excluded(res)[SOURCE_NOTE] == TEXTBOX_TEXT_EXCLUDED
    fig = load(res).find(".//fig")
    assert fig.get("id") == "F1" and fig.find("graphic") is not None and res.plan.textboxes == {}
    [act] = others(res)
    assert (act.level, act.key) == (TO_CHECK, "textbox_figure_text") and not res.needs_action
    src = next(s for s, p in res.plan.paras.items() if p.plain() == SOURCE_NOTE)
    report = res.report_path.read_text(encoding="utf-8")
    top, ch14 = report.split("## 2.")[0], report.split("## 14.")[1]
    assert ("> **要確認: 図の画像に写るものとして、XML の本文に出していない文字があります（図形 1 つ。6 章）。**"
            in top) and "> - 図1（fig01）の図形: 25 字「出典：架空の町の資料（2020）をもとに…」" in top
    assert "本文として読ませたい文字なら、Word でその文字を図形の外（本文の段落）に出して、変換し直してください" in top
    assert "- [ ] **図の画像に写るものとして XML の本文に出していない文字（図形 1 つ）**（6 章）" in ch14
    assert "図の画像に写るものとして、XML の本文に出していない文字があります（図形 1 つ。要確認）" == act.box_title
    assert "docx で図形の外（本文の段落）に出して変換し直すこと" in act.cli and "図1（fig01）の図形: 25 字" in act.cli
    # AI の set_role p は採用しない。placements の kind box・label の対象でもないので、理由で placements を案内しない
    _, plan, _ = _mechanical(path, journal)
    xid = plan.paras[src].textbox_id
    import json
    resp = {"placements": [{"float": xid, "after": next(s for s, p in plan.paras.items() if p.plain().startswith("図1から")),
                            "items": [{"kind": "box", "caption": [], "body": []}], "reason": "x", "confidence": "中"}],
            "operations": [{"op": "set_role", "src": src, "text": "", "occurrence": 1, "target": "", "role": "p", "image": "",
                            "mathml": "", "surname": "", "given": "", "reason": "x", "confidence": "高"}], "notes": []}
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "ai", ai_mode="manual",
                                               ai_response=json.dumps(resp, ensure_ascii=False)))
    why = {op["op"]: w for op, w in res.ai.rejected}
    assert why["set_role"] == (f"テキストボックス {xid} は囲み・図の注記の判断の対象でない（図表の入ったテキストボックス・本文の外の"
                               "テキストボックスなど）ので、段落に指定できる役割は fig_caption・table_caption・exclude だけ")
    assert "placements" not in why["set_role"] and why["place_float"].startswith(f"{xid} は「位置を決められなかった図表」")
    assert "textbox_figure_text" in [a.key for a in actions(res)] and excluded(res)[SOURCE_NOTE] == TEXTBOX_TEXT_EXCLUDED


def test_text_in_unplaced_figure_textbox_is_notified_before_answer(journal, meta, tmp_path):
    """位置を決められない図表（浮動配置）の中の出典の文は、図の画像に写るとみなして除外し、手動モードで AI の回答を貼り戻す
    前から要確認で知らせる（図形の中身の組み方は AI の指定の有無で変わらない。修正計画 W1 の 2.4）。AI が位置を答えなくても
    同じく知らせる。"""
    import json
    path = tmp_path / "figfloat.docx"
    mf.make_article(path, "浮動配置の図の検証用文書", _figure_textbox(True))
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "pending", ai_mode="manual"))
    assert res.plan.unplaced_floats and res.fidelity.ok and res.dtd_valid
    assert excluded(res)[SOURCE_NOTE] == "テキストボックス内の文字（図の一部とみなして本文から除外）"
    assert "textbox_figure_text" in [a.key for a in actions(res)]
    empty = json.dumps({"placements": [], "operations": [], "notes": []})
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "ans", ai_mode="manual", ai_response=empty))
    keys = [a.key for a in actions(res)]
    assert "forced" in keys and "textbox_figure_text" in keys and res.fidelity.ok and res.dtd_valid


def test_caption_shaped_paragraph_in_inline_textbox_stays_caption(journal, meta, tmp_path):
    """浮動配置でないテキストボックスの、本文スタイルの「図1　…」（キャプションの形。「。」で終わらない）は、文字だけの
    テキストボックスとして囲み・注記の判定に回さず、今までどおり隣の画像の図のキャプションにする（Classifier.text_only）。"""
    def parts(b):
        rid = b.add_image("vmlcap2.png", mf.png_bytes("Figure"))
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "試験（2024）の図を示す。"),
                mf.para(S["body"], mf.drawing(rid, 1800000, 1080000, 3501)),
                mf.para(S["body"], mf.vml_textbox(mf.para(S["body"], "図1　架空の図形"), width="200pt", height="20pt")),
                mf.para(S["body"], "以上が図1である。")]
    path = tmp_path / "vmlcap.docx"
    mf.make_article(path, "VML のキャプションの検証用文書", parts)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    fill_images(res)                # 図の画像の手順（必須）を済ませ、ほかの知らせを今までどおり確かめる
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and res.jstage_issues == []
    assert res.plan.textboxes == {} and others(res) == []
    fig = load(res).find(".//fig")
    assert fig.get("id") == "F1" and text(fig.find("caption")) == "図1　架空の図形" and fig.find("graphic") is not None


def test_links_inside_box(journal, meta, tmp_path):
    """囲み（boxed-text）の中の引用文献の引用と図の参照も、本文と同じくリンクにする（linker.body_paragraphs の囲みの枝）。"""
    def parts(b):
        rid = b.add_image("boxlink.png", mf.png_bytes("Figure"))
        box = (mf.para(S["body"], "問1　試験（2024）にならい，図1の二つの点の間の道のりを求めなさい。")
               + mf.para(S["body"], "答えは一つに決まる。"))
        return [mf.para(S["sec1"], "１．はじめに"),
                mf.para(S["body"], "次の問題を読む。", mf.textbox_inline(box, 3602, cx=12 * 360000, cy=2 * 360000)),
                mf.para(S["body"], "囲みの後の一つ目の段落である。"), mf.para(S["body"], "囲みの後の二つ目の段落である。"),
                mf.para(S["body"], "図1を次に示す。"), mf.para(S["body"], mf.drawing(rid, 1800000, 1080000, 3601)),
                mf.para(S["fig_cap"], "図1　架空の地図")]
    path = tmp_path / "boxlink.docx"
    mf.make_article(path, "囲みの中のリンクの検証用文書", parts)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and res.jstage_issues == []
    [bt] = load(res).iter("boxed-text")
    assert [(x.get("ref-type"), x.get("rid"), x.text) for x in bt.iter("xref")] == [("bibr", "B1", "2024"),
                                                                                  ("fig", "F1", "図1")]


@pytest.mark.parametrize("between, kind", [([], "label"), (["p"], "label"), (["p", "p"], "undecided"),
                                           (["table", "p"], "undecided")])
def test_near_image_counts_two_elements(between, kind, journal, meta, tmp_path):
    """「画像の近く」（Classifier.near_image）は、アンカー段落の前後 2 つ（図形の外の段落と表で数える。floats.NEAR_PARAS）まで。
    画像の段落から 3 つ離れた（間に段落 2 つ、または表と段落）小さな札は、図の注記にせず、決められないもの（要確認）にする。"""
    def parts(b):
        rid = b.add_image("near.png", mf.png_bytes("Figure"))
        mid = [mf.table([[mf.cell("区分"), mf.cell("人数")], [mf.cell("一組"), mf.cell("三十人")]]) if x == "table"
               else mf.para(S["body"], f"間の段落{k + 1}である。") for k, x in enumerate(between)]
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], mf.drawing(rid, 1800000, 1080000, 3701)), *mid,
                mf.para(S["body"], "図に名前を付けた。", mf.textbox(mf.para(S["body"], "点Ｔ"), 3702, cx=360000, cy=216000,
                                                            h=("column", 720000), v=("paragraph", -720000))),
                mf.para(S["body"], "以上である。")]
    path = tmp_path / "near.docx"
    mf.make_article(path, "画像の近さの検証用文書", parts)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    [bi] = res.plan.textboxes.values()
    assert (bi.kind, bi.near) == (kind, kind == "label")
    # 1 章の「テキストボックスの文字」の行は、中身のある章だけを示す（図の注記だけなら 3 章を示さない）
    row = ("| テキストボックスの文字（4 章・6 章・10 章） | 図の注記として除外 1 件 |" if kind == "label"
           else "| テキストボックスの文字（3 章・4 章・6 章） | 決められずに除外 1 件（要確認） |")
    assert row in res.report_path.read_text(encoding="utf-8").split("## 2.")[0]


# ---- K5: 本文スタイルの「注」だけの段落（表の注の見出しなど）で、後付けに切り替えたまま本文に戻らない
def table_note_article(tmp_path, tail, note_style=None):
    """表の後ろに本文スタイル（既定。note_style で変える）の「注」だけの段落と注の説明があり、その後ろに tail（XML の一覧）が続く小さな論文。"""
    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "表1に結果を示す。"),
                mf.para(S["tab_cap"], "表1　架空の表"),
                mf.table([[mf.cell("観点"), mf.cell("内容")], [mf.cell("架空"), mf.cell("内容")]]),
                mf.para(note_style or S["body"], "注"), mf.para(S["body"], "表の下の説明である。"),
                mf.para(S["body"], "もう一つの説明である。"), *tail]
    path = tmp_path / "k5.docx"
    mf.make_article(path, "表の注の検証用文書", parts)
    return path


def test_table_note_heading_returns_to_body(journal, meta, tmp_path):
    """本文スタイルの「注」だけの段落（表の注の見出し）の後ろに章見出しのスタイルの段落が現れたら、文字から推定した注の節ではなく
    本文の続きとして、「注」の段落から章見出しの前までを本文に戻す（今までは以降の章見出し・本文がすべて 1 件の注の段落になった）。
    判断の一覧に記録する。文字は 1 文字も変わらない（不変性チェック合格）。"""
    tail = [mf.para(S["sec1"], "２．おわりに"), mf.para(S["body"], "終わりの本文である。"),
            mf.para(S["sec2"], "（１）まとめ"), mf.para(S["body"], "まとめの本文である。")]
    path = table_note_article(tmp_path, tail)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and res.jstage_issues == []
    root = load(res)
    assert root.find(".//fn-group") is None and res.plan.fns == []
    secs = list(root.find("body"))
    assert [text(s.find("title")) for s in secs] == ["１．はじめに", "２．おわりに"]
    assert [text(q) for q in secs[0].findall("p")] == ["表1に結果を示す。", "注", "表の下の説明である。", "もう一つの説明である。"]
    assert [text(q) for q in root.iter("title") if text(q) == "（１）まとめ"] == ["（１）まとめ"]
    [d] = [d for d in res.plan.decisions if "本文に戻した" in d.message]
    assert d.category == "style" and d.applied and res.plan.paras[d.src].plain() == "注" and "3 ブロック" in d.message
    assert {res.plan.region[s] for s, q in res.plan.paras.items() if q.plain() in ("注", "表の下の説明である。")} == {"body"}
    # 本文に戻したことを要確認で知らせる（F10）
    [act] = [x for x in actions(res) if x.key == "fn_guess"]
    assert act.level == TO_CHECK and "本文に戻" in act.top and d.src in act.top


@pytest.mark.parametrize("note_style", [None, S["sec1"]], ids=["body-style", "sec1-style"])
def test_real_notes_section_stays(note_style, journal, meta, tmp_path):
    """対照: 「注」の後ろに注が並び、引用文献の見出し（スタイル）が続く原稿は、今までどおり注の節（fn-group）になる。「注」が本文
    スタイルでも章見出しのスタイルでも同じ。"""
    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "架空の主張である。"),
                mf.para(note_style or S["body"], "注"), mf.para(S["body"], "1) 一つ目の注である。"),
                mf.para(S["body"], "2) 二つ目の注である。")]
    path = tmp_path / "k5_real.docx"
    mf.make_article(path, "注の節の検証用文書", parts)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    root = load(res)
    assert [text(q) for q in root.find(".//fn-group").findall("fn/p")] == ["1) 一つ目の注である。", "2) 二つ目の注である。"]
    assert not [d for d in res.plan.decisions if "本文に戻した" in d.message]
    assert [text(s.find("title")) for s in root.find("body")] == ["１．はじめに"]
    assert "fn_guess" not in [x.key for x in actions(res)]      # 注の番号で始まる段落が続く注の節は、知らせも出ない


def test_real_notes_section_followed_by_text_ref_heading(journal, meta, tmp_path):
    """対照: 「注」（本文スタイル）の後ろの注の一覧のあとに、章見出しのスタイルで書いた「謝辞」（文字から推定する後付けの見出し）が
    続く原稿は、注の節のまま（後付けの見出しが先に現れるので本文に戻さない）。謝辞は make_article の引用文献の見出しとは種類が違う
    ので、見出しの重複にならない（章見出しのスタイルの「引用文献」だと引用文献の見出しが 2 つになる。その形は
    test_structure_conflict_kinds の K1_notes_then_text_ref_heading）。"""
    tail = [mf.para(S["sec1"], "謝辞"), mf.para(S["body"], "お世話になった方々に感謝します。")]
    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "架空の主張である。"),
                mf.para(S["body"], "注"), mf.para(S["body"], "1) 一つ目の注である。"), *tail]
    path = tmp_path / "k5_ref.docx"
    mf.make_article(path, "注の節の検証用文書", parts)
    _, plan, _ = _mechanical(path, journal)
    assert [fn.number for fn in plan.fns] == [1] and plan.fn_heading is not None
    assert plan.structure_conflicts == [] and plan.ack is not None and plan.ack.heading.plain() == "謝辞"
    assert not [d for d in plan.decisions if "本文に戻した" in d.message]
    assert [s.heading.plain() for s in plan.body if getattr(s, "heading", None) is not None] == ["１．はじめに"]


# ---- F10: K5 の戻しの条件（見出しのスタイルの段落が、資料の見出しでない。G2 で「注」の直後が注の番号で始まらないことは外した）と、文字から推定した注の節の知らせ
def fn_guess_article(tmp_path, middle, name):
    """章見出しの後ろに、本文スタイルの「注」だけの段落と middle（XML の一覧）が続く小さな論文（引用文献は make_article が足す）。"""
    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "架空の主張である（注1）。"),
                mf.para(S["body"], "注"), *middle]
    path = tmp_path / f"{name}.docx"
    mf.make_article(path, "注の扱いの検証用文書", parts)
    return path


def fn_guess_action(res):
    return [a for a in actions(res) if a.key == "fn_guess"]


@pytest.mark.parametrize("style, kind", [("sec2", "節"), ("sec3", "項")])
def test_table_note_heading_before_sub_heading_returns_to_body(style, kind, journal, meta, tmp_path):
    """F10 (1): 「注」の後ろが節・項の見出し（sec2・sec3）でも、資料の見出しでなければ本文に戻す
    （今までは章見出し〈sec1〉だけが戻し、節・項の見出し以降の本文がすべて 1 件の注になった）。要確認で知らせる。"""
    middle = [mf.para(S["body"], "表の下の説明である。"), mf.para(S[style], "（１）小節" if style == "sec2" else "① 小項"),
              mf.para(S["body"], "小節の本文である。")]
    path = fn_guess_article(tmp_path, middle, "f10_sub")
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    root = load(res)
    assert root.find(".//fn-group") is None and res.plan.fns == []
    body_text = text(root.find("body"))
    for s in ("注", "表の下の説明である。", "小節の本文である。"):
        assert s in body_text
    [d] = [d for d in res.plan.decisions if "本文に戻した" in d.message]
    assert d.applied and kind + "見出し" in d.message and res.plan.paras[d.src].plain() == "注"
    [act] = fn_guess_action(res)
    assert act.level == TO_CHECK and d.src in act.top and "本文に戻" in act.top
    assert "Word" in act.top and act.cli.startswith("要確認")
    assert not res.needs_action


def test_real_notes_section_followed_by_chapter_style_paragraph_stays(journal, meta, tmp_path):
    """F10 (2): 注の番号で始まる段落が続く本当の注の節の後ろに、引用文献の見出しなしで章見出しのスタイルの段落（資料など）が
    続いても、注の節を本文に戻さない（今までは注が 0 件になり、知らせもなかった）。注の一覧に見えない段落が続いたことを
    要確認で知らせ、判断の一覧に記録する。"""
    middle = [mf.para(S["body"], "（注1）一つ目の注である。"), mf.para(S["sec1"], "資料"), mf.para(S["body"], "資料の本文である。")]
    path = fn_guess_article(tmp_path, middle, "f10_real")
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    assert len(res.plan.fns) == 1 and res.plan.fn_heading is not None
    assert not [d for d in res.plan.decisions if "本文に戻した" in d.message]
    root = load(res)
    assert len(list(root.iter("fn"))) == 1
    [act] = fn_guess_action(res)
    assert act.level == TO_CHECK and "注の節として扱" in act.top and "見出しのスタイルの段落" in act.top
    [d] = [d for d in res.plan.decisions if "注の節として扱った" in d.message]
    assert d.applied and "見出しのスタイルの段落" in d.message
    assert not res.needs_action


def test_table_note_without_chapter_heading_reaches_refs_is_reported(journal, meta, tmp_path):
    """F10 (3): 表の注の「注」の後ろに章見出しが出ないまま引用文献の見出しに着くと、章の残りの本文が注の節に入る（扱いは今までと
    同じ）。そのとき、注の番号で始まらない段落が続いたまま注の節として扱ったことを要確認で知らせ、判断の一覧に記録する。"""
    middle = [mf.para(S["body"], "表の注の文である。"), mf.para(S["body"], "最後の章のつづきの本文である。以上である。")]
    path = fn_guess_article(tmp_path, middle, "f10_refs")
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    assert len(res.plan.fns) == 1
    [act] = fn_guess_action(res)
    assert act.level == TO_CHECK and "注の節として扱" in act.top and "注の番号で始まらない" in act.top
    [d] = [d for d in res.plan.decisions if "注の節として扱った" in d.message]
    assert d.applied and "注の番号で始まらない" in d.message and res.plan.paras[d.src].plain() == "注"
    assert res.plan.fn_guess_checks and res.plan.fn_guess_checks[0][1] == "kept"
    report = res.report_path.read_text(encoding="utf-8")
    assert "注」だけの段落" in report.split("## 2.")[0]
    assert not res.needs_action


def test_real_notes_with_continuation_paragraphs_are_not_reported(journal, meta, tmp_path):
    """対照: 「注」の直後が注の番号で始まる注の一覧は、番号のない続きの段落が混じっていても、知らせない（今までどおり）。"""
    middle = [mf.para(S["body"], "（注1）一つ目の注である。"), mf.para(S["body"], "一つ目の注の続きである。"),
              mf.para(S["body"], "（注2）二つ目の注である。")]
    path = fn_guess_article(tmp_path, middle, "f10_cont")
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    assert [len(fn) for fn in [list(x.findall("p")) for x in load(res).iter("fn")]] == [2, 1]
    assert fn_guess_action(res) == [] and res.plan.fn_guess_checks == []
    assert not [d for d in res.plan.decisions if "注の節として扱った" in d.message or "本文に戻した" in d.message]


# ---- G1・G2・G3: 英文の部分に切り替わるブロックが表のとき・注の番号で始まる表の注・知らせの助言
def test_fn_guess_check_when_english_part_starts_with_a_table(journal, meta, tmp_path):
    """G1: 文字から推定した注の節（表の注の「注」）が、英文の部分に切り替わるブロックが表（Table。src がなく tid）で終わっても、
    変換が止まらず（今までは b.src を読んで AttributeError）、注の節として扱ったことを要確認で知らせる。段落のときと同じ。"""
    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "架空の主張である。"), mf.para(S["body"], "注"),
                mf.para(S["body"], "表の注の文である。"),
                mf.table([[mf.cell([mf.para(S["author_en"], "Rokuro SHIKEN")]), mf.cell([mf.para(S["aff_en"], "Fictional University")])]]),
                mf.para(S["title_en"], "A Small Article")]
    path = tmp_path / "g1.docx"
    mf.make_article(path, "表で英文の部分が始まる検証用文書", parts)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    [act] = fn_guess_action(res)
    assert act.level == TO_CHECK and "注の節として扱" in act.top
    [(_, kind, how)] = res.plan.fn_guess_checks
    assert kind == "kept" and "後ろの英文の部分 t" in how             # 表の識別子（t1 など）で示す
    [d] = [d for d in res.plan.decisions if "注の節として扱った" in d.message]
    assert "後ろの英文の部分 t" in d.message


NUMBERED_TABLE_NOTES = ["1) 数値は平均である。", "2) 欠損は除いた。"]


@pytest.mark.parametrize("head_style, head_text, kind", [("sec1", "２．方法", "章"), ("sec2", "（１）小節", "節"),
                                                          ("sec3", "① 小項", "項")])
def test_numbered_table_notes_followed_by_heading_return_to_body(head_style, head_text, kind, journal, meta, tmp_path):
    """G2: 注の番号で始まる表の注（「注」「1) 数値は平均である。」「2) 欠損は除いた。」）の後ろに章見出し・節見出し・項見出しが
    続くときも、資料の見出しでなければ本文に戻す（「注」の直後が注の番号で始まるかは、戻すかどうかの条件にしない。今までは以降の
    章がすべて 1 件の注に入った）。要確認で知らせ、判断の一覧に記録する。文字は 1 文字も変わらない。"""
    middle = [mf.para(S["body"], t) for t in NUMBERED_TABLE_NOTES] + [mf.para(S[head_style], head_text), mf.para(S["body"], "続きの本文である。")]
    path = fn_guess_article(tmp_path, middle, "g2_" + head_style)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    root = load(res)
    assert root.find(".//fn-group") is None and res.plan.fns == []
    body_text = text(root.find("body"))
    for s in ("注", "1) 数値は平均である。", "2) 欠損は除いた。", head_text, "続きの本文である。"):
        assert s in body_text
    [d] = [d for d in res.plan.decisions if "本文に戻した" in d.message]
    assert d.applied and kind + "見出し" in d.message and "注の番号で始まる表の注の可能性" in d.message
    assert res.plan.paras[d.src].plain() == "注" and "3 ブロック" in d.message
    [act] = fn_guess_action(res)
    assert act.level == TO_CHECK and d.src in act.top and "本文に戻" in act.top
    assert not res.needs_action


@pytest.mark.parametrize("app", ["資料", "資料1　授業の記録", "Appendix 2"])
def test_real_notes_followed_by_appendix_heading_stays(app, journal, meta, tmp_path):
    """G2: 後ろの見出しのスタイルの段落が資料の見出し（appendix_heading）なら、今までどおり注の節として扱う（戻さない）。
    注の一覧に見えない段落が続いたことは要確認で知らせる。"""
    middle = [mf.para(S["body"], "（注1）一つ目の注である。"), mf.para(S["sec1"], app), mf.para(S["body"], "資料の本文である。")]
    path = fn_guess_article(tmp_path, middle, "g2_app")
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    assert len(res.plan.fns) == 1 and not [d for d in res.plan.decisions if "本文に戻した" in d.message]
    [act] = fn_guess_action(res)
    assert act.level == TO_CHECK and "注の節として扱" in act.top


def test_heading_that_is_an_appendix_sentence_returns_to_body(journal, meta, tmp_path):
    """G2: 「資料1、2は授業の記録である。」のような文の形の章見出しは資料の見出しではない（appendix_sentence）ので、本文に戻す。"""
    middle = [mf.para(S["body"], "1) 数値は平均である。"), mf.para(S["sec1"], "資料1、2は授業の記録である。"), mf.para(S["body"], "続き。")]
    path = fn_guess_article(tmp_path, middle, "g2_sentence")
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    assert res.plan.fns == [] and [d for d in res.plan.decisions if "本文に戻した" in d.message]


def test_pinned_shapes_after_g2(journal, meta, tmp_path):
    """G2: 点検で使った形が、新しい条件でどうなるかを固定する。
    k5b: 「注」+「（注1）…」で文書が終わる → 注の節（知らせなし）。k5b2: その後ろに節見出し → 本文に戻す（要確認）。
    k5c: その後ろに資料の章見出し → 注の節のまま（要確認）。e3: 表の注の後ろに見出しがないまま引用文献 → 注の節のまま（要確認）。"""
    def article(name, middle):
        def parts(b):
            return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "最初の本文である。（注1）"), mf.para(S["body"], "注"), *middle]
        path = tmp_path / f"{name}.docx"
        mf.make_article(path, "注の形の検証用文書", parts)
        res = convert(path, meta, journal, Options(out_dir=tmp_path / name))
        assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
        return res
    note = mf.para(S["body"], "（注1）末尾の注である。")
    res = article("k5b", [note])
    assert len(res.plan.fns) == 1 and fn_guess_action(res) == []
    res = article("k5b2", [note, mf.para(S["sec2"], "1.1 小節"), mf.para(S["body"], "小節本文")])
    assert res.plan.fns == [] and res.plan.fn_guess_checks[0][1] == "returned"
    assert "小節本文" in text(load(res).find("body")) and len(fn_guess_action(res)) == 1
    res = article("k5c", [note, mf.para(S["sec1"], "資料"), mf.para(S["body"], "資料の本文。")])
    assert len(res.plan.fns) == 1 and res.plan.fn_guess_checks[0][1] == "kept"
    res = article("e3", [mf.para(S["body"], "表の注の文である。"), mf.para(S["body"], "最後の章のつづきの本文である。以上である。")])
    assert len(res.plan.fns) == 1 and res.plan.fn_guess_checks[0][1] == "kept"


def _manual_roles(path, ops, meta, journal, out):
    resp = json.dumps({"operations": [{"op": "set_role", "src": s, "text": "", "occurrence": 1, "target": "", "role": r, "image": "",
                                       "confidence": "高", "reason": "試験"} for s, r in ops], "placements": [], "notes": []},
                      ensure_ascii=False)
    return convert(path, meta, journal, Options(out_dir=out, ai_mode="manual", ai_response=resp))


def fn_guess_texts(act):
    """利用者向けの文（レポートの冒頭・14 章・Colab の枠・コマンドライン）をまとめて返す。"""
    return [act.top, act.checklist, act.box_title, act.box_detail, act.cli]


def test_fn_guess_advice_is_executable(journal, meta, tmp_path):
    """G3・H2: 要確認の助言（注の節なら Word の「注見出し」スタイル、本文の続きなら Word の「注本文」スタイル）に従うと、実際に
    推定が変わる。助言に内部の操作名（set_role・fn_heading・p を指定）を出さない（利用者が指定できない書き方になるため）。
    「注」が本文スタイルのままでは、本文のスタイルに直しても同じ推定になる（助言にしない）。"""
    middle = [mf.para(S["body"], "表の注の文である。"), mf.para(S["body"], "最後の章のつづきの本文である。以上である。")]
    path = fn_guess_article(tmp_path, middle, "g3")
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    [act] = fn_guess_action(res)
    for s in ("注見出し", "注本文"):
        assert s in act.top and s in act.box_detail and s in act.checklist and s in act.cli
    for t in fn_guess_texts(act):
        assert not any(w in t for w in ("set_role", "fn_heading", "p を指定", "AI による補完"))
    assert "本文・標準・章見出しのスタイルのままでは" in act.top and "本文のスタイルに直" not in act.top
    # 一覧に段落の ID と文字の抜粋を付ける
    [(src, kind, _)] = res.plan.fn_guess_checks
    assert f"{src}「注」" in act.top and f"{src}「注」" in act.box_detail
    # (1) 本文のスタイルのまま: 推定は変わらない（Word で本文のスタイルにしても同じ）
    assert kind == "kept"
    # (2) 注の節: 「注」のスタイルを「注見出し」にすると、推定ではなくスタイルで注の節になり、要確認は出ない
    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "架空の主張である（注1）。"), mf.para(S["fn_head"], "注"),
                mf.para(S["body"], "1) 一つ目の注である。")]
    path2 = tmp_path / "g3_style.docx"
    mf.make_article(path2, "注見出しの検証用文書", parts)
    res2 = convert(path2, meta, journal, Options(out_dir=tmp_path / "out2"))
    assert res2.fidelity.ok and len(res2.plan.fns) == 1 and fn_guess_action(res2) == []
    # (3) 本文の続き: 「注」のスタイルを「注本文」にすると、推定されず、本文の段落として出て、要確認も出ない（H2。Word で取れる手段）
    def parts3(b):
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "架空の主張である（注1）。"), mf.para(S["fn_body"], "注"), *middle]
    path3 = tmp_path / "g3_fnbody.docx"
    mf.make_article(path3, "注本文の検証用文書", parts3)
    res3 = convert(path3, meta, journal, Options(out_dir=tmp_path / "out3"))
    assert res3.fidelity.ok and res3.fidelity.final_ok and res3.dtd_valid and res3.jstage_issues == []
    assert res3.plan.fn_guess_checks == [] and fn_guess_action(res3) == [] and res3.plan.fns == []
    assert [text(q) for q in load(res3).find("body").iter("p")][1:] == ["注", "表の注の文である。", "最後の章のつづきの本文である。以上である。"]
    assert res3.plan.region[next(s for s, q in res3.plan.paras.items() if q.plain() == "注")] == "body"
    # (4) 本文のスタイルのまま、章見出しの前までを戻す場合（returned）も、「注」を「注本文」にすれば推定されない
    tail = [mf.para(S["sec2"], "（１）小節"), mf.para(S["body"], "小節の本文である。")]
    for name, style, want in (("g3_ret_body", "body", 1), ("g3_ret_fnbody", "fn_body", 0)):
        def parts4(b, style=style):
            return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "架空の主張である。"), mf.para(S[style], "注"),
                    mf.para(S["body"], "表の下の説明である。"), *tail]
        path4 = tmp_path / f"{name}.docx"
        mf.make_article(path4, "戻しの検証用文書", parts4)
        res4 = convert(path4, meta, journal, Options(out_dir=tmp_path / name))
        assert res4.fidelity.ok and res4.fidelity.final_ok and res4.dtd_valid and len(fn_guess_action(res4)) == want
        assert "表の下の説明である。" in text(load(res4).find("body")) and res4.plan.fns == []
    # (5) AI の補完が役割を指定した段落も推定しない（利用者への案内にはしないが、仕組みとして働く）
    res5 = _manual_roles(path, [(src, "p")], meta, journal, tmp_path / "out5")
    assert res5.ai.rejected == [] and res5.fidelity.ok and res5.fidelity.final_ok and res5.dtd_valid
    assert res5.plan.fns == [] and res5.plan.fn_guess_checks == [] and fn_guess_action(res5) == []
    assert "注" in [text(q) for q in load(res5).find("body").iter("p")]
    res6 = _manual_roles(path, [(src, "fn_heading")], meta, journal, tmp_path / "out6")
    assert res6.ai.rejected == [] and res6.fidelity.ok and len(res6.plan.fns) == 1 and fn_guess_action(res6) == []


def test_fn_guess_style_note_body_in_template():
    """H2: 助言の「注見出し」「注本文」は、テンプレートのスタイルの名前で、設定のとおりの役割になる（役割 fn_heading と fn）。
    「注本文」は本文の領域に現れても本文の段落（structure.BODY_ROLES）。ほかのスタイル（キャプション・ブロック引用）を勧めない根拠は
    上のテストの (3)・docs/STYLE_MAPPING.md（別の要素になる）。"""
    from jasme_jats.structure import BODY_ROLES, BACK_HEADINGS
    from jasme_jats.config import JournalConfig
    styles = JournalConfig.load().styles
    assert styles["注見出し"] == "fn_heading" and styles["注本文"] == "fn"
    # テストの docx が使うスタイル ID（S["fn_head"]・S["fn_body"]）は、テンプレートの「注見出し」「注本文」
    import re
    import zipfile
    xml = zipfile.ZipFile(Path(__file__).parent / "fixtures" / "JASME_template_20261009.docx").read("word/styles.xml").decode("utf-8")
    names = dict(re.findall(r'<w:style [^>]*w:styleId="([^"]+)"[^>]*>\s*<w:name w:val="([^"]+)"', xml))
    assert (names[S["fn_head"]], names[S["fn_body"]]) == ("注見出し", "注本文")
    assert "fn" in BODY_ROLES and "fn_heading" in BACK_HEADINGS


def test_fn_guess_numbered_paragraphs_in_returned_range_are_reported(journal, meta, tmp_path):
    """H7: 本文に戻した範囲に注の番号で始まる段落（「1) …」）が含まれるとき、件数と抜粋を要確認の文に出し、注の節にする手段
    （「注見出し」スタイル）を添える。含まれないときは、その文は出ない。"""
    middle = [mf.para(S["body"], "1) 一つ目の注である。"), mf.para(S["body"], "2) 二つ目の注である。"),
              mf.para(S["sec1"], "補足"), mf.para(S["body"], "補足の本文である。")]
    path = fn_guess_article(tmp_path, middle, "h7")
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    [(head, kind, how)] = res.plan.fn_guess_checks
    assert kind == "returned" and len(res.plan.fn_guess_numbered[head]) == 2 and "注の番号で始まる段落が 2 件ある" in how
    [act] = fn_guess_action(res)
    for t in (act.top, act.box_detail):
        assert "注の番号で始まる段落が 2 件ありました" in t and "「1) 一つ目の注である。」" in t and "「2) 二つ目の注である。」" in t
        assert "注見出し" in t and "後ろの章見出しとその本文も含めてすべて注の節に入ります" in t
    assert "注の番号で始まる段落が 2 件" in act.cli and "注見出し" in act.cli
    # 注の番号で始まる段落がなければ、触れない
    path2 = fn_guess_article(tmp_path, [mf.para(S["body"], "表の下の説明である。"), *middle[2:]], "h7_none")
    res2 = convert(path2, meta, journal, Options(out_dir=tmp_path / "out2"))
    [act2] = fn_guess_action(res2)
    assert res2.plan.fn_guess_numbered == {} and "注の番号で始まる段落が" not in act2.top + act2.box_detail + act2.cli


def test_fn_guess_advice_says_which_paragraphs_join_the_notes(journal, meta, tmp_path):
    """0.29.0 の最後の点検: 「注見出し」にすると、後付けの見出しまでの段落（後ろの章も）が注の節に入る注意を、「注見出し」を勧めるすべての
    場合（戻した・戻した範囲に注の番号がある・注の節として扱った）と、すべての出口（レポートの冒頭・14 章・Colab の枠・コマンドライン）に、
    どの段落か分かる形（最初と最後の段落の ID と抜粋、件数）で添える。その範囲は、実際に「注見出し」にしたときに注の節に入る段落と一致する。"""
    clause = "後ろの章見出しとその本文も含めてすべて注の節に入ります"
    cases = {
        "returned": [mf.para(S["body"], "表の下の説明である。"), mf.para(S["sec1"], "補足"), mf.para(S["body"], "補足の本文である。")],
        "numbered": [mf.para(S["body"], "1) 一つ目の注である。"), mf.para(S["body"], "2) 二つ目の注である。"),
                     mf.para(S["sec1"], "補足"), mf.para(S["body"], "補足の本文である。")],
        "kept": [mf.para(S["body"], "表の注の文である。"), mf.para(S["body"], "最後の章のつづきの本文である。以上である。")],
    }
    for name, middle in cases.items():
        res = convert(fn_guess_article(tmp_path, middle, "span_" + name), meta, journal,
                      Options(out_dir=tmp_path / ("o_" + name)))
        [act] = fn_guess_action(res)
        [(head, kind, _)] = res.plan.fn_guess_checks
        assert kind == ("kept" if name == "kept" else "returned"), name
        span = res.plan.fn_guess_span[head]
        last = res.plan.paras[span[-1]].plain()
        assert len(span) == len(middle) and last == middle_text(middle[-1]), name
        for t in fn_guess_texts(act):
            if t in (act.box_title,):
                continue
            assert "注見出し" in t and clause in t, (name, t)
            assert f"{span[0]}「" in t and f"{span[-1]}「{last[:15]}" in t and f"までの {len(span)} 段落" in t, (name, t)
        assert "\x00" not in "".join(fn_guess_texts(act))
        # その範囲は、「注」を「注見出し」にしたとき、実際に注の節に入る段落と一致する
        def parts(b, middle=middle):
            return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "架空の主張である（注1）。"), mf.para(S["fn_head"], "注"), *middle]
        path2 = tmp_path / f"span_{name}_style.docx"
        mf.make_article(path2, "注の扱いの検証用文書", parts)
        res2 = convert(path2, meta, journal, Options(out_dir=tmp_path / ("s_" + name)))
        assert res2.fidelity.ok and res2.fidelity.final_ok and res2.dtd_valid
        assert [s for s, r in res2.plan.region.items() if r == "fn" and s != head] == span, name


FN_SPAN_PIECES = {
    "注": lambda: mf.para(S["body"], "注"),
    "body": lambda: mf.para(S["body"], "表の下の説明である。"),
    "blank": lambda: mf.para(S["body"], ""),
    "sec1": lambda: mf.para(S["sec1"], "補足"),
    "sec2": lambda: mf.para(S["sec2"], "（１）小節"),
    "sec3": lambda: mf.para(S["sec3"], "① 小項"),
    "app": lambda: mf.para(S["sec1"], "資料1　調査票"),
    "table": lambda: mf.table([[mf.cell("観点"), mf.cell("内容")]]),
    "num": lambda: mf.para(S["body"], "1) 数値は平均である。"),
}
FN_SPAN_CASES = {
    "one_returned": ["注", "body", "sec1", "body"],
    "one_kept": ["注", "body"],
    "one_numbered": ["注", "num", "sec2", "body"],
    "two_returned": ["body", "注", "body", "sec1", "body", "注", "body", "sec1", "body"],
    "two_kept_last": ["注", "body", "sec1", "body", "注", "body"],
    "three_mixed": ["注", "body", "table", "blank", "sec2", "body", "注", "blank", "body", "app", "body", "注", "table", "body", "sec3", "body"],
    "two_adjacent": ["注", "注", "body", "sec1", "body"],
    "with_app_between": ["注", "body", "app", "body", "注", "body", "sec2", "body"],
}


def fn_span_article(tmp_path, tokens, name, style_index=None):
    """tokens の並び（FN_SPAN_PIECES の名前）が章見出しと本文の後ろに続く小さな論文。style_index 番目の「注」だけ「注見出し」スタイルにする。"""
    def parts(b):
        out = [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "架空の主張である（注1）。")]
        k = 0
        for t in tokens:
            if t == "注" and k == style_index:
                out.append(mf.para(S["fn_head"], "注"))
            else:
                out.append(FN_SPAN_PIECES[t]())
            k += t == "注"
        return out
    path = tmp_path / f"{name}.docx"
    mf.make_article(path, "注の扱いの検証用文書", parts)
    return path


@pytest.mark.parametrize("case", list(FN_SPAN_CASES))
def test_fn_guess_span_matches_notes_when_each_note_is_made_heading(case, journal, meta, tmp_path):
    """0.29.0 の 4 回目の点検: 要確認 fn_guess が言う「注見出しにすると注の節に入る段落」（plan.fn_guess_span）は、「注」が 1 つ・2 つ・3 つ、
    間に表・空白段落・節/項の見出し・資料の見出しがあっても、「注」ごとに、その「注」を実際に「注見出し」スタイルにして変換し直したときの
    注の一覧の段落（plan.fns）と一致する。別の「注」の段落は見出しとして注の節に戻るだけで、注の一覧の段落には入らない。"""
    tokens = FN_SPAN_CASES[case]
    res = convert(fn_span_article(tmp_path, tokens, case), meta, journal,
                  Options(out_dir=tmp_path / "o"))
    assert res.fidelity.ok and res.fidelity.final_ok
    plan = res.plan
    notes = [s for s, p in plan.paras.items() if p.plain() == "注"]
    assert notes
    checked = 0
    for k, head in enumerate(notes):
        if head not in plan.fn_guess_span:          # 先の「注」が注の節として扱われ、その中の「注」は推定の対象ではない
            continue
        # 注見出しが後ろにもう 1 つあると、見出しは 1 つしか持てず、先の見出しの段落が出力されないので、変換を中止する（K1。
        # StructureConflictError。その形では助言に、すべての「注」の扱いを決めてから変換し直すよう添える。
        # test_fn_guess_advice_for_several_notes...）。k より後ろに別の「注」があるときだけ中止になり、k が最後の「注」なら合格する
        opts2 = Options(out_dir=tmp_path / f"s_{case}_{k}")
        if k < len(notes) - 1:
            with pytest.raises(StructureConflictError) as e:
                convert(fn_span_article(tmp_path, tokens, f"{case}_{k}", k), meta, journal, opts2)
            plan2 = e.value.plan
            assert e.value.conflicts and all(c.kind == "fn_heading" for c in e.value.conflicts), (case, k)
            lost = {s for c in e.value.conflicts for s in c.lost}
            assert lost and lost <= set(notes), (case, k)           # 落ちるのは「注」の見出しの段落だけ
        else:
            res2 = convert(fn_span_article(tmp_path, tokens, f"{case}_{k}", k), meta, journal, opts2)
            assert res2.fidelity.final_ok and res2.dtd_valid, (case, k)
            assert res2.fidelity.ok and not res2.fidelity.missing, (case, k)
            plan2 = res2.plan
        actual = [p.src for fn in plan2.fns for p in fn.paras]
        assert plan.fn_guess_span[head] == actual, (case, head)
        assert not set(plan.fn_guess_span[head]) & set(notes), (case, head)       # 別の「注」の段落は数えない
        checked += 1
    assert checked >= 1


def fn_styled_article(tmp_path, tokens, name, styles):
    """fn_span_article と同じ並びで、k 番目の「注」のスタイルを styles[k]（S のキー。足りない分は body）にする。"""
    def parts(b):
        out = [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "架空の主張である（注1）。")]
        k = 0
        for t in tokens:
            if t == "注":
                out.append(mf.para(S[styles[k] if k < len(styles) else "body"], "注"))
                k += 1
            else:
                out.append(FN_SPAN_PIECES[t]())
        return out
    path = tmp_path / f"{name}.docx"
    mf.make_article(path, "注の扱いの検証用文書", parts)
    return path


@pytest.mark.parametrize("case", list(FN_SPAN_CASES))
def test_fn_guess_advice_for_several_notes_decides_all_notes_before_reconverting(case, journal, meta, tmp_path):
    """0.29.0 の 5 回目の点検: 文字から注の見出しと推定される「注」が 2 つ以上ある結果では、要確認 fn_guess の助言（冒頭・14 章・枠・
    コマンドライン）に、「注見出し」にするのは注の節の「注」1 つだけにし、ほかの「注」は「注本文」スタイルにするなど、すべての「注」の
    扱いを決めてから変換し直す注意と、対象の「注」の段落 ID と抜粋を添える（先の「注」だけを「注見出し」にして変換し直すと、後ろの
    「注」も注の見出しと推定されて先の見出しが出力されないので、変換が中止される。StructureConflictError）。1 つのときは添えない。
    その助言どおり（先の「注」を注見出し、後ろの「注」を注本文）にした docx は不変性チェックに合格する。"""
    tokens = FN_SPAN_CASES[case]
    n = tokens.count("注")
    res = convert(fn_span_article(tmp_path, tokens, case), meta, journal, Options(out_dir=tmp_path / "o"))
    assert res.fidelity.ok and res.fidelity.final_ok
    [act] = fn_guess_action(res)
    notes = [s for s, p in res.plan.paras.items() if p.plain() == "注"]
    assert res.plan.fn_guess_notes == notes and len(notes) == n
    marker = "すべての「注」の扱いを決めてから"
    for t in fn_guess_texts(act):
        if t == act.box_title:
            continue
        assert "set_role" not in t and "fn_heading" not in t and "\x00" not in t
        if n < 2:
            assert marker not in t, (case, t)
            continue
        assert marker in t and "ほかの「注」（表の注の見出しなど）は「注本文」スタイル" in t and f"{n} 件あります" in t, (case, t)
        assert all(f"{s}「注」" in t for s in notes), (case, t)
        assert "4 章の件数のほか、その範囲の中の「注」も数えています" in t and "変換が中止されることがあります" in t, (case, t)
        assert "要対応で止まる" not in t
    if n < 2:
        return
    # 助言どおり: 先の「注」を「注見出し」、ほかの「注」を「注本文」にして変換し直すと、不変性チェックに合格する
    res2 = convert(fn_styled_article(tmp_path, tokens, case + "_advice", ["fn_head"] + ["fn_body"] * (n - 1)), meta, journal,
                   Options(out_dir=tmp_path / "o2"))
    assert res2.fidelity.ok and res2.fidelity.final_ok and res2.dtd_valid and not res2.fidelity.missing, case
    assert res2.plan.fn_heading is not None and res2.plan.fn_heading.src == notes[0] and not res2.needs_action
    # 先の「注」だけを直して、後ろの「注」を本文スタイルのままにすると、後ろの「注」も注の見出しと推定されて先の見出しが出力されない
    # ので、変換が中止される（助言が止める形。K1）。先の「注」が落ちる段落に入る
    with pytest.raises(StructureConflictError) as e:
        convert(fn_styled_article(tmp_path, tokens, case + "_first", ["fn_head"]), meta, journal,
                Options(out_dir=tmp_path / "o3"))
    lost = {s for c in e.value.conflicts for s in c.lost}
    assert notes[0] in lost and lost <= set(notes) and all(c.kind == "fn_heading" for c in e.value.conflicts), case


def test_fn_guess_advice_counts_each_note_range(journal, meta, tmp_path):
    """0.29.0 の 4 回目の点検: 「注」の段落が 2 つ以上ある原稿（表ごとに「注」の行がある論文）でも、要確認 fn_guess の助言は「注」ごとの範囲
    （最初と最後の段落と件数）を言い、先の「注」の範囲が次の「注」で打ち切られない。範囲の書き方は「d14「…」から d17「…」までの 4 段落」
    （「から」の後ろに空白を置き、1 段落のときは「…」の 1 段落）。"""
    tokens = FN_SPAN_CASES["two_returned"]
    res = convert(fn_span_article(tmp_path, tokens, "adv"), meta, journal, Options(out_dir=tmp_path / "o"))
    [act] = fn_guess_action(res)
    plan = res.plan
    heads = [h for h, _, _ in plan.fn_guess_checks]
    assert len(heads) == 2
    second = plan.paras[heads[1]]
    lead = plan.fn_guess_span[heads[0]]
    assert heads[1] not in lead
    for t in fn_guess_texts(act):
        if t == act.box_title:
            continue
        # 先の「注」の範囲は 2 つ目の「注」を越えて、最後の本文まで（2 つ目の「注」の段落は数えない）
        first, last = lead[0], lead[-1]
        assert f"{heads[0]} の後ろの {first}「" in t and f"から {last}「" in t and f"までの {len(lead)} 段落" in t, t
        assert "」から" not in t.replace("」から ", "") and "」 の" not in t
    assert second.plain() == "注" and len(lead) == 6
    # 1 段落のときは「」の 1 段落」（余分な空白を置かない）
    res1 = convert(fn_span_article(tmp_path, FN_SPAN_CASES["one_kept"], "adv1"), meta, journal,
                   Options(out_dir=tmp_path / "o1"))
    [act1] = fn_guess_action(res1)
    [(h, _, _)] = res1.plan.fn_guess_checks
    [only] = res1.plan.fn_guess_span[h]
    assert f"{h} の後ろの {only}「表の下の説明である。」の 1 段落" in act1.top
    assert "」 の 1 段落" not in act1.top + act1.box_detail + act1.cli


def middle_text(p):
    """mf.para の XML の一覧（文字列）から、段落の文字を取り出す。"""
    from lxml import etree
    root = etree.fromstring(f'<root xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">{p}</root>')
    return "".join(root.itertext())


# ----------------------------------------------------------------------------- 位置を決められない除外の知らせ（u5-exclusions）
def _no_abstract_style_docx(tmp_path, name="noabs.docx", extra=(), plain_heading=False, front_extra=(), heading_last=False):
    """英文要旨のスタイルがない論文。英文の部分（題目・著者表）はあるが、Abstract の見出しがなく（plain_heading なら見出しは残す）、
    要旨の 2 段落は標準スタイル（heading_last なら見出しを要旨の 2 段落の後ろに置く。見出しの後ろに段落がない形）。extra は要旨の後ろに足す XML の一覧、front_extra は和文の冒頭（題目の前）に足す XML の一覧。"""
    b = mf.Builder()
    body = list(mf.front_ja(b, "英文要旨のない検証用の論文", "―検証―", [("架空大学", "試験　六郎")]))
    body[2:2] = list(front_extra)
    body += [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "試験（2024）にならう。"),
             mf.para(S["ref_head"], "引用および参考文献"),
             mf.para(S["ref"], "試験六郎（2024）．「小さな論文」．『架空誌』，第5巻，pp.9-10．")]
    english = mf.front_en(b, "A Small Article", "For Checking", [("Rokuro SHIKEN", "Fictional University")],
                          ["First abstract.", "Second abstract."])
    heading = english[5]
    del english[5:]
    if plain_heading:
        english.append(heading)
    english += [mf.para(None, "First abstract."), mf.para(None, "Second abstract.")]
    if heading_last:
        english.append(heading)
    body += english + list(extra) + mf.tail(b)
    path = tmp_path / name
    b.save(path, body)
    return path


def _convert_no_abstract(journal, meta, tmp_path, **kw):
    out = kw.pop("out", "out")
    opts = kw.pop("opts", {})
    path = kw.pop("path", None) or _no_abstract_style_docx(tmp_path, **kw)
    return convert(path, meta, journal, Options(out_dir=tmp_path / out, **opts))


def test_abstract_without_style_or_heading_needs_action(journal, meta, tmp_path):
    from jasme_jats.structure import EN_OTHER_EXCLUDED
    res = _convert_no_abstract(journal, meta, tmp_path)
    assert res.plan.abstract == [] and res.fidelity.ok and res.dtd_valid
    keys = [(a.level, a.key) for a in actions(res)]
    assert (NEEDS_ACTION, "abstract_missing") in keys and "excluded_unsure" not in [k for _, k in keys]
    assert res.needs_action
    srcs = [s for s, why, _ in res.fidelity.excluded if why == EN_OTHER_EXCLUDED]
    assert len(srcs) == 2
    act = next(a for a in actions(res) if a.key == "abstract_missing")
    for s in srcs:
        assert s in act.top and s in act.cli and s in act.box_detail
    assert "「英文要旨」スタイル" in act.top and "「英文要旨見出し」" in act.top and "段落 2 件" in act.top
    assert "（スタイルなし）" in act.top or "Normal" in act.top
    report = res.report_path.read_text(encoding="utf-8")
    ch6 = report.split("## 6.")[1].split("## 7.")[0]
    assert ch6.count(EN_OTHER_EXCLUDED + "（要対応）") == 2 and "（要確認）" not in ch6
    assert "AI による補完を使うときは" in act.box_detail      # AI を使わないとき（目印 ai_choose の文）


def test_abstract_missing_reason_follows_heading(journal, meta, tmp_path):
    """見出しがないときは「見出しにもスタイルがない」、英文要旨見出しのスタイルの見出しがあるときは「その後ろに段落がない」と書く。"""
    no_head = next(a for a in actions(_convert_no_abstract(journal, meta, tmp_path, out="nh")) if a.key == "abstract_missing")
    assert "見出し（Abstract）にも" in no_head.top and "その後ろに英文要旨の段落がない" not in no_head.top
    res = _convert_no_abstract(journal, meta, tmp_path, out="wh", heading_last=True)
    assert res.plan.abstract == [] and res.plan.abstract_heading is not None
    act = next(a for a in actions(res) if a.key == "abstract_missing")
    assert "その後ろに英文要旨の段落がないため" in act.top and "見出し（Abstract）にも" not in act.top
    assert "その後ろに英文要旨の段落がないため" in act.box_detail


def test_abstract_missing_with_english_article(journal, meta, tmp_path):
    path = _no_abstract_style_docx(tmp_path)
    en = dataclasses.replace(journal, lang="en")
    res_en = convert(path, meta, en, Options(out_dir=tmp_path / "en"))
    assert "abstract_missing" in [a.key for a in actions(res_en)]


def test_abstract_missing_mentions_appendix(journal, meta, tmp_path):
    from jasme_jats.report import ABSTRACT_MISSING_APP
    extra = [mf.para(None, "Appendix 1　Questionnaire"), mf.table([[mf.cell("Item A"), mf.cell("Item B")]])]
    res = _convert_no_abstract(journal, meta, tmp_path, extra=extra)
    act = next(a for a in actions(res) if a.key == "abstract_missing")
    assert ABSTRACT_MISSING_APP in act.top and ABSTRACT_MISSING_APP in act.box_detail and ABSTRACT_MISSING_APP in act.cli
    assert "段落 3 件と表のセルの段落 2 件" in act.top
    plain = next(a for a in actions(_convert_no_abstract(journal, meta, tmp_path, out="plain")) if a.key == "abstract_missing")
    assert ABSTRACT_MISSING_APP not in plain.top and "段落 2 件を" in plain.top


def test_no_english_part_does_not_report_missing_abstract(journal, meta, tmp_path):
    b = mf.Builder()
    body = list(mf.front_ja(b, "英文の部分のない検証用の論文", "―検証―", [("架空大学", "試験　六郎")]))
    body += [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "試験（2024）にならう。"),
             mf.para(S["ref_head"], "引用および参考文献"),
             mf.para(S["ref"], "試験六郎（2024）．「小さな論文」．『架空誌』，第5巻，pp.9-10．")]
    body += mf.tail(b)
    path = tmp_path / "noen.docx"
    b.save(path, body)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    keys = [a.key for a in actions(res)]
    assert "abstract_missing" not in keys and "excluded_unsure" not in keys


def test_abstract_heading_with_plain_paragraphs_is_ok(journal, meta, tmp_path):
    res = _convert_no_abstract(journal, meta, tmp_path, plain_heading=True)
    assert len(res.plan.abstract) == 2 and res.fidelity.ok and res.dtd_valid
    assert actions(res) == []


def test_extra_english_paragraph_is_unplaced(journal, meta, tmp_path):
    from jasme_jats.structure import EN_OTHER_EXCLUDED
    b = mf.Builder()
    body = list(mf.front_ja(b, "英文の余分な段落の検証用の論文", "―検証―", [("架空大学", "試験　六郎")]))
    body += [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "試験（2024）にならう。"),
             mf.para(S["ref_head"], "引用および参考文献"),
             mf.para(S["ref"], "試験六郎（2024）．「小さな論文」．『架空誌』，第5巻，pp.9-10．")]
    english = mf.front_en(b, "A Small Article", "For Checking", [("Rokuro SHIKEN", "Fictional University")], ["Abstract text."])
    english.insert(5, mf.para(None, "Received June 2025."))
    body += english + mf.tail(b)
    path = tmp_path / "extra.docx"
    b.save(path, body)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    assert [t for _, why, t in res.fidelity.excluded if why == EN_OTHER_EXCLUDED] == ["Received June 2025."]
    assert [(a.level, a.key) for a in actions(res)] == [(TO_CHECK, "excluded_unsure")] and not res.needs_action
    assert len(res.plan.abstract) == 1


def _atoms(*items):
    return Para(src="d1", style_id="x", style_name="標準", atoms=list(items))


def test_front_decoration():
    from jasme_jats.structure import front_decoration
    lines = ["全国数学教育学会誌　数学教育学研究"]
    t = lambda s: _atoms(Atom(kind="text", text=s))
    assert front_decoration(t("❚" * 40), lines)
    for s in ("全国数学教育学会誌　数学教育学研究", "全国数学教育学会誌 数学教育学研究", "全国数学教育学会誌数学教育学研究"):
        assert front_decoration(t(s), lines), s
    assert front_decoration(t(""), lines) and front_decoration(_atoms(), lines)
    assert not front_decoration(t("受付日　2025年"), lines)
    assert not front_decoration(t("全国数学教育学会誌　数学教育学研究"), ())
    assert not front_decoration(_atoms(Atom(kind="math")), lines)
    assert front_decoration(_atoms(Atom(kind="image")), lines)
    assert not front_decoration(_atoms(Atom(kind="text", text="❚❚"), Atom(kind="math")), lines)


def test_front_paragraph_other_than_decoration_is_unplaced(journal, meta, tmp_path):
    from jasme_jats.structure import FRONT_DECORATION_EXCLUDED, FRONT_OTHER_EXCLUDED
    res = _convert_no_abstract(journal, meta, tmp_path, plain_heading=True,
                               front_extra=[mf.para(None, "受付日　2025年6月1日")])
    by = {}
    for s, why, t in res.fidelity.excluded:
        by.setdefault(why, []).append(t)
    assert by[FRONT_OTHER_EXCLUDED] == ["受付日　2025年6月1日"]
    assert len(by[FRONT_DECORATION_EXCLUDED]) == 3        # テンプレートの誌名行と装飾行
    assert [(a.level, a.key) for a in actions(res)] == [(TO_CHECK, "excluded_unsure")]
    plain = _convert_no_abstract(journal, meta, tmp_path, plain_heading=True, out="plain")
    assert FRONT_OTHER_EXCLUDED not in [why for _, why, _ in plain.fidelity.excluded] and actions(plain) == []


def test_abstract_style_aliases(journal):
    from jasme_jats.config import JournalConfig
    j = JournalConfig.load()
    assert j.styles["英文要約"] == "abstract" and j.styles["英文要約見出し"] == "abstract_heading"
    assert next(n for n, v in j.styles.items() if v == "abstract") == "英文要旨"
    assert next(n for n, v in j.styles.items() if v == "abstract_heading") == "英文要旨見出し"
    assert j.front_lines == ["全国数学教育学会誌　数学教育学研究"]


def test_unplaced_action_texts(journal, meta, tmp_path):
    from jasme_jats.colab import step_text
    from jasme_jats.structure import EN_OTHER_EXCLUDED, FRONT_OTHER_EXCLUDED
    b = mf.Builder()
    front = ["受付日　2025年6月1日", "査読中の原稿", "掲載予定", "特集号"]
    body = list(mf.front_ja(b, "位置を決められない段落の検証用の論文", "―検証―", [("架空大学", "試験　六郎")]))
    body[2:2] = [mf.para(None, x) for x in front]
    body += [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "試験（2024）にならう。"),
             mf.para(S["ref_head"], "引用および参考文献"),
             mf.para(S["ref"], "試験六郎（2024）．「小さな論文」．『架空誌』，第5巻，pp.9-10．")]
    english = mf.front_en(b, "A Small Article", "For Checking", [("Rokuro SHIKEN", "Fictional University")], ["Abstract text."])
    english[5:5] = [mf.para(None, f"Note number {i}.") for i in (1, 2, 3)]
    body += english + mf.tail(b)
    path = tmp_path / "unplaced.docx"
    b.save(path, body)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    act = next(a for a in actions(res) if a.key == "excluded_unsure")
    assert (act.level, act.key) == (TO_CHECK, "excluded_unsure") and not res.needs_action
    assert "7 件" in act.top and "冒頭部の段落 4 件（" in act.top and "英文の部分の段落 3 件（" in act.top
    assert "ほか" in act.top.split("冒頭部の段落 4 件")[1].split("\n")[0]        # 抜粋は 3 件まで
    assert "ほか" not in act.top.split("英文の部分の段落 3 件")[1].split("\n")[0]
    assert "7 件" in act.checklist and "7 件" in act.box_title
    for screen in ("notebook", "app", "cli"):
        shown = step_text(act.box_detail, screen)
        assert "\x00" not in shown and "step:" not in shown
    srcs = [s for s, why, _ in res.fidelity.excluded if why in (FRONT_OTHER_EXCLUDED, EN_OTHER_EXCLUDED)]
    assert len(srcs) == 7 and srcs[0] in act.cli
    ch6 = res.report_path.read_text(encoding="utf-8").split("## 6.")[1].split("## 7.")[0]
    assert ch6.count("（要確認）") == 7


def test_no_unplaced_notices_for_fixtures(journal, meta, tmp_path):
    """どの fixture でも、位置を決められない除外の知らせ・英文要旨が見つからない知らせは鳴らない（回帰の守り）。"""
    docs = sorted((Path(__file__).parent / "fixtures").glob("*.docx"))
    assert len(docs) >= 15
    for i, doc in enumerate(docs):
        res = convert(doc, meta, journal, Options(out_dir=tmp_path / str(i), ai_mode="manual"))
        keys = [a.key for a in actions(res)]
        assert "excluded_unsure" not in keys and "abstract_missing" not in keys, doc.name


def test_two_abstract_heading_styles(journal, meta, tmp_path):
    """「英文要旨見出し」の見出しと、別名のスタイル名「英文要約見出し」の見出しが両方ある原稿は、英文要旨の見出しが 2 つになるので
    変換を中止する（K1 と同じ仕組み。StructureConflictError）。"""
    import re
    import zipfile
    sid, new_id = S["abs_head"], "AliasAbsHead"
    src = _no_abstract_style_docx(tmp_path, plain_heading=True, extra=[mf.para(new_id, "Abstract"), mf.para(None, "Third.")])
    alias = tmp_path / "alias.docx"
    with zipfile.ZipFile(src) as zi, zipfile.ZipFile(alias, "w") as zo:
        for e in zi.infolist():
            data = zi.read(e.filename)
            if e.filename == "word/styles.xml":
                styles = data.decode("utf-8")
                m = re.search(rf'<w:style [^>]*w:styleId="{sid}".*?</w:style>', styles, re.S)
                copy = m.group(0).replace(f'w:styleId="{sid}"', f'w:styleId="{new_id}"')
                copy = re.sub(r'(<w:name w:val=")[^"]*(")', r"\g<1>英文要約見出し\g<2>", copy, count=1)
                data = styles.replace(m.group(0), m.group(0) + copy).encode("utf-8")
            zo.writestr(e, data)
    with pytest.raises(StructureConflictError) as e:
        convert(alias, meta, journal, Options(out_dir=tmp_path / "out"))
    [c] = e.value.conflicts
    assert c.kind == "abstract_heading" and "英文要旨の見出しが 2 つ" in str(e.value)
    assert [e.value.plan.paras[s].plain() for s in c.lost] == ["Abstract"] and e.value.plan.paras[c.by].plain() == "Abstract"


# ----------------------------------------------------------------------------- 後付けの見出しの重複・連続する所属（u6-k1k2。K1・K2）
def _p(style, t):
    return mf.para(S[style], t)


_REF_TEXT, _REF2_TEXT = "試験六郎（2024）．「小さな論文」．『架空誌』，第5巻，pp.9-10．", "架空花子（2020）．『本』．架空社．"
_REF = _p("ref", _REF_TEXT)
_REF2 = _p("ref", _REF2_TEXT)
_FN1 = _p("body", "1) 注の本文である。")

# 名前 -> make_fixtures.make_conflict の引数
CONFLICT_DOCS = {
    # --- K1
    "K1_ref_ref": dict(back=[_p("ref_head", "引用文献"), _REF, _p("ref_head", "参考文献"), _REF2]),
    "K1_ref_reftext": dict(back=[_p("ref_head", "引用文献"), _REF, _p("body", "参考文献"), _REF2]),
    "K1_ack_ack_style": dict(back=[_p("ack_head", "謝辞"), _p("body", "先の謝辞の本文。"), _p("ack_head", "謝辞"),
                                   _p("body", "後の謝辞の本文。"), _p("ref_head", "引用文献"), _REF]),
    # 前の謝辞の見出しが空白だけ（中身あり）: 見出しは空白の除外に記録され、lost は中身だけ
    # （後付けの始まりは引用文献の見出し。本文の途中の空白だけの見出しは領域を切り替えない〈C041〉ので、その見出しは使わない）
    "K1_ack_blankhead_ack": dict(back=[_p("ref_head", "引用文献"), _REF, _p("ack_head", "　"), _p("body", "先の謝辞の本文。"),
                                       _p("ack_head", "謝辞"), _p("body", "後の謝辞の本文。")]),
    "K1_ack_ack_text": dict(body=[_p("body", "謝辞"), _p("body", "先の謝辞の本文。"), _p("body", "謝辞"), _p("body", "後の謝辞の本文。")]),
    "K1_notes_notes": dict(back=[_p("notes_head", "付記"), _p("body", "先の付記。"), _p("ref_head", "引用文献"), _REF,
                                 _p("notes_head", "付記"), _p("body", "後の付記。")]),
    "K1_fn_style2": dict(body=[_p("fn_head", "注"), _FN1, _p("fn_head", "注"), _p("body", "2) 二つ目の注。")]),
    "K1_fn_style_text": dict(body=[_p("fn_head", "注"), _FN1, _p("body", "注"), _p("body", "2) 二つ目の注。")]),
    "K1_fn_text2_kept": dict(body=[_p("body", "注"), _FN1, _p("body", "注"), _p("body", "2) 二つ目の注。")]),
    "K1_fn_after_refs_then_ref_again": dict(back=[_p("ref_head", "引用文献"), _REF, _p("fn_head", "注"), _FN1,
                                                  _p("ref_head", "参考文献"), _REF2]),
    # 章見出しのスタイルで書いた「引用文献」（文字から推定した見出し）の後ろに、make_article と同じ引用文献の見出し
    "K1_notes_then_text_ref_heading": dict(body=[_p("body", "注"), _FN1, _p("sec1", "引用文献"), _REF],
                                           back=[_p("ref_head", "引用および参考文献"), _REF2]),
    "X_abstract_heading2": dict(en_after=[_p("abs_head", "Abstract"), _p("abs", "Second abstract.")]),
    # --- K2
    "K2_loose_aff_aff_author": dict(ja_rows=(), loose=(_p("aff_ja", "第一大学"), _p("aff_ja", "第二大学"), _p("author_ja", "試験　六郎"))),
    "K2_loose_trailing_aff": dict(ja_rows=(), loose=(_p("aff_ja", "第一大学"), _p("author_ja", "試験　六郎"), _p("aff_ja", "第二大学"))),
    "K2_loose_dup_aff": dict(ja_rows=(), loose=(_p("aff_ja", "第一大学"), _p("author_ja", "試験　六郎"), _p("aff_ja", "第一大学"),
                                                _p("aff_ja", "第一大学"), _p("author_ja", "架空　花子"))),
    "K2_table_affonly_row_first": dict(ja_rows=(("第一大学", ""), ("第二大学", "試験　六郎"))),
    "K2_table_affonly_row_last": dict(ja_rows=(("第一大学", "試験　六郎"), ("第二大学", ""))),
    "K2_table_then_loose_author": dict(ja_rows=(("第一大学", ""),), loose=(_p("author_ja", "試験　六郎"),)),
}

# 中止しない対照（structure_conflicts も missing も空）
NO_CONFLICT_DOCS = {
    # 先の「注」が本文に戻る（K5。戻った「注」は build_back に届かない）
    "K1_fn_text2_K5_returned": dict(body=[_p("body", "注"), _p("body", "表の下の説明。"), _p("sec1", "２．続き"),
                                          _p("body", "本文。"), _p("body", "注"), _FN1]),
    "K1_fn_text2_first_returned_second_kept_body": dict(body=[_p("body", "注"), _p("body", "表の下の説明。"), _p("sec1", "２．続き"),
                                                              _p("body", "注"), _p("body", "表の下の説明2。")]),
    "K2_loose_aff_author_author": dict(ja_rows=(), loose=(_p("aff_ja", "第一大学"), _p("author_ja", "試験　六郎"),
                                                          _p("author_ja", "架空　花子"))),
    "K2_loose_aff_blank_aff_author": dict(ja_rows=(), loose=(_p("aff_ja", "第一大学"), _p("aff_ja", ""), _p("author_ja", "試験　六郎"))),
    "K2_table_nameonly_row": dict(ja_rows=(("第一大学", "試験　六郎"), ("", "架空　花子"))),
    "K2_table_two_affs_in_cell": dict(ja_rows=(("第一大学\n第二大学", "試験　六郎"),)),
    # 英文の側は文字が落ちないので検出しない（著者のない <aff> は K13 で別に残る）
    "EN_aff_before_name": dict(en_rows=(("aff", "Fictional University"), ("name", "Rokuro SHIKEN"))),
    "EN_aff_aff_name": dict(en_rows=(("aff", "First University"), ("aff", "Second University"), ("name", "Rokuro SHIKEN"))),
    "EN_name_aff_aff": dict(en_rows=(("name", "Rokuro SHIKEN"), ("aff", "First University"), ("aff", "Second University"))),
    "EN_trailing_aff": dict(en_rows=(("name", "Rokuro SHIKEN"), ("aff", "Fictional University"), ("aff", "Other University"))),
}


def conflict_doc(tmp_path, name):
    kw = CONFLICT_DOCS.get(name) or NO_CONFLICT_DOCS[name]
    return mf.make_conflict(tmp_path / f"{name}.docx", **kw)


def build_missing(path, journal, meta):
    """convert を通さず（中止されるので）組み立てて不変性チェックにかけ、出力も除外もされなかった段落 ID の集合を返す。"""
    from jasme_jats.builder import build
    from jasme_jats.fidelity import verify
    _, plan, _ = _mechanical(path, journal)
    root, info = build(plan, meta, journal, journal.split_labels)
    fid = verify(path, root, plan.exclusions + info.exclusions)
    return plan, {s for s, _ in fid.missing}


@pytest.mark.parametrize("name", list(CONFLICT_DOCS))
def test_structure_conflict_matches_lost_paragraphs(name, journal, meta, tmp_path):
    """検出した衝突の lost の段落 ID の集合は、検出を外してそのまま組み立てたときに不変性チェックが不合格にする段落 ID の集合と一致する
    （落ちる段落だけを、落ちるときだけ検出する）。"""
    plan, missing = build_missing(conflict_doc(tmp_path, name), journal, meta)
    lost = {s for c in plan.structure_conflicts for s in c.lost}
    assert lost and lost == missing, name


@pytest.mark.parametrize("name", list(NO_CONFLICT_DOCS))
def test_no_structure_conflict_for_contrast_forms(name, journal, meta, tmp_path):
    """対照: 本文に戻った「注」・著者名に付く所属・空の所属・同じ行の所属の欄に 2 段落・英文の側は、中止しない（missing も空）。"""
    plan, missing = build_missing(conflict_doc(tmp_path, name), journal, meta)
    assert plan.structure_conflicts == [] and not missing, name
    res = convert(tmp_path / f"{name}.docx", meta, journal, Options(out_dir=tmp_path / "out"))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid, name


def test_two_affiliations_in_one_cell_attach_to_the_author(journal, meta, tmp_path):
    """Word での直し方の案内の確かめ: 著者表の同じ行の所属の欄に段落を分けて並べると、その著者に所属が 2 つ付く。"""
    _, plan, _ = _mechanical(conflict_doc(tmp_path, "K2_table_two_affs_in_cell"), journal)
    [a] = plan.authors
    assert [x.ja.plain() for x in a.affs] == ["第一大学", "第二大学"]


# 名前 -> (kind, lost の文字, by の文字, where, by_text, between)
CONFLICT_KINDS = {
    "K1_ref_ref": ("ref_heading", ["引用文献"], "参考文献", "", (False, False), False),
    "K1_ref_reftext": ("ref_heading", ["引用文献"], "参考文献", "", (False, True), False),
    "K1_ack_ack_style": ("ack", ["謝辞", "先の謝辞の本文。"], "謝辞", "", (False, False), False),
    "K1_ack_blankhead_ack": ("ack", ["先の謝辞の本文。"], "謝辞", "", (False, False), False),
    "K1_ack_ack_text": ("ack", ["謝辞", "先の謝辞の本文。"], "謝辞", "", (True, True), False),
    "K1_notes_notes": ("notes", ["付記", "先の付記。"], "付記", "", (False, False), True),
    "K1_fn_style2": ("fn_heading", ["注"], "注", "", (False, False), False),
    "K1_fn_style_text": ("fn_heading", ["注"], "注", "", (False, True), False),
    "K1_fn_text2_kept": ("fn_heading", ["注"], "注", "", (True, True), False),
    "K1_fn_after_refs_then_ref_again": ("ref_heading", ["引用文献"], "参考文献", "", (False, False), True),
    "K1_notes_then_text_ref_heading": ("ref_heading", ["引用文献"], "引用および参考文献", "", (True, False), False),
    "X_abstract_heading2": ("abstract_heading", ["Abstract"], "Abstract", "", (False, False), False),
    "K2_loose_aff_aff_author": ("aff", ["第一大学"], "第二大学", "loose", (False, False), False),
    "K2_loose_trailing_aff": ("aff", ["第二大学"], "", "loose", (False, False), False),
    "K2_loose_dup_aff": ("aff", ["第一大学"], "第一大学", "loose", (False, False), False),
    "K2_table_affonly_row_first": ("aff", ["第一大学"], "第二大学", "table", (False, False), False),
    "K2_table_affonly_row_last": ("aff", ["第二大学"], "", "table", (False, False), False),
    "K2_table_then_loose_author": ("aff", ["第一大学"], "", "table", (False, False), False),
}


@pytest.mark.parametrize("name", list(CONFLICT_KINDS))
def test_structure_conflict_kinds(name, journal, meta, tmp_path):
    """各形の衝突が 1 件ずつ、期待どおりの (種類, 落ちる段落, 置き換えた段落, 段落か表か, 文字からの推定, 間に別の節があるか) で記録される。"""
    kind, lost, by, where, by_text, between = CONFLICT_KINDS[name]
    _, plan, _ = _mechanical(conflict_doc(tmp_path, name), journal)
    [c] = plan.structure_conflicts
    assert (c.kind, c.where, c.by_text, c.between) == (kind, where, by_text, between), name
    assert [plan.paras[s].plain() for s in c.lost] == lost, name
    assert (plan.paras[c.by].plain() if c.by else "") == by, name
    order = list(plan.paras)
    assert not c.by or order.index(c.lost[-1]) < order.index(c.by)        # 落ちる段落は置き換えた段落より前


def test_structure_conflicts_are_all_collected(journal, meta, tmp_path):
    """組み立ては最初の衝突で止めず、すべての箇所を集める（K1 の見出しと K2 の所属が同じ原稿にあるとき、両方を文に挙げる）。"""
    path = mf.make_conflict(tmp_path / "all.docx", ja_rows=(), loose=(_p("aff_ja", "第一大学"), _p("aff_ja", "第二大学"),
                                                                   _p("author_ja", "試験　六郎")),
                            back=[_p("ref_head", "引用文献"), _REF, _p("ref_head", "参考文献"), _REF2],
                            en_after=[_p("abs_head", "Abstract"), _p("abs", "Second abstract.")])
    with pytest.raises(StructureConflictError) as e:
        convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    assert [c.kind for c in e.value.conflicts] == ["aff", "ref_heading", "abstract_heading"]
    assert "3 か所" in str(e.value)
    assert not list((tmp_path / "out").glob("*.xml"))


BLANK_DOCS = {
    # 前の見出しが空（文字なし）: 本物の見出しで置き換える（空の段落は記録しない）
    "blank_first_empty": dict(back=[_p("ref_head", ""), _p("ref_head", "引用文献"), _REF]),
    # 前の見出しが全角空白だけ: 除外（空白のみの段落）にして、本物の見出しで置き換える
    "blank_first_space": dict(back=[_p("ref_head", "　"), _p("ref_head", "引用文献"), _REF]),
    # 本物の見出しの後ろに空・全角空白だけの見出し: 前の本物の見出しを残す
    "blank_last_empty": dict(back=[_p("ref_head", "引用文献"), _REF, _p("ref_head", "")]),
    "blank_last_space": dict(back=[_p("ref_head", "引用文献"), _REF, _p("ref_head", "　")]),
    "blank_fn_after_fn": dict(body=[_p("fn_head", "注"), _p("fn_head", ""), _FN1]),
    # 注の見出しの後ろの表のあとの空の注見出し: 表は空の見出しに左右されず、注 1 の 1 段落目の後ろに入る（知らせは出ない）
    "blank_fn_after_table": dict(body=[_p("fn_head", "注"), mf.table([[mf.cell("区分"), mf.cell("人数")]]),
                                       _p("fn_head", ""), _FN1]),
    # 謝辞の節の途中の空の謝辞見出し: 後ろの本文は前の謝辞の節に入る
    "blank_ack_in_section": dict(back=[_p("ack_head", "謝辞"), _p("body", "先の謝辞の本文。"), _p("ack_head", ""),
                                       _p("body", "後の謝辞の本文。"), _p("ref_head", "引用文献"), _REF]),
}


@pytest.mark.parametrize("name", list(BLANK_DOCS))
def test_blank_heading_is_excluded_not_conflict(name, journal, meta, tmp_path):
    """空白だけの見出しは、前でも後ろでも、中止せずに空白の除外にする。前の本物の見出しは残り（後ろが空白のとき）、
    不変性チェックは合格する（0.31.0 より前は、前の空白は missing、後ろの空白は前の本物の見出しが落ちて不合格だった）。"""
    path = mf.make_conflict(tmp_path / f"{name}.docx", **BLANK_DOCS[name])
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    plan = res.plan
    assert plan.structure_conflicts == [] and res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid, name
    heads = {"ref": plan.ref_heading, "fn": plan.fn_heading}
    real = {"blank_fn_after_table": "fn", "blank_first_empty": "ref", "blank_first_space": "ref", "blank_last_empty": "ref", "blank_last_space": "ref",
            "blank_fn_after_fn": "fn"}
    if name in real:
        assert heads[real[name]] is not None and heads[real[name]].plain() == ("引用文献" if real[name] == "ref" else "注")
    blank_texts = {"blank_first_space": "　", "blank_last_space": "　"}
    if name in blank_texts:
        [ex] = [x for x in res.fidelity.excluded if x[1] == "空白のみの段落"]
        assert plan.paras[ex[0]].plain() == blank_texts[name]
    if name == "blank_fn_after_table":
        assert "excluded_unsure" not in {a.key for a in actions(res)}
        assert [(fn.number, len(fn.tables)) for fn in plan.fns] == [(1, 1)]
        assert not any(e.reason == BACK_TABLE_EXCLUDED for e in plan.exclusions)
    if name == "blank_fn_after_fn":
        assert [p.plain() for fn in plan.fns for p in fn.paras] == ["1) 注の本文である。"]
    if name == "blank_ack_in_section":
        assert plan.ack.heading.plain() == "謝辞"
        assert [c.para.plain() for c in plan.ack.children] == ["先の謝辞の本文。", "後の謝辞の本文。"]


def test_blank_back_heading_does_not_change_other_outputs(journal, meta, tmp_path):
    """空白だけの後付けの見出しの扱いは、その段落を除外に記録するだけ: 空の見出しがない原稿と、XML の本文は同じ。"""
    with_blank = mf.make_conflict(tmp_path / "with.docx", back=BLANK_DOCS["blank_last_space"]["back"])
    without = mf.make_conflict(tmp_path / "without.docx")
    texts = []
    for i, path in enumerate((with_blank, without)):
        res = convert(path, meta, journal, Options(out_dir=tmp_path / f"o{i}"))
        texts.append(text(load(res)))
    assert texts[0] == texts[1]


def test_structure_conflict_text_adds_other_fn_guess_notes_once(journal, tmp_path):
    """注の見出しの衝突の文には、衝突にかかわらない文字から推定される「注」（本文に戻った「注」）があれば、文全体で 1 回だけ、
    すべての「注」の扱いを一緒に決める注意を添える。衝突にかかわる「注」は挙げない。"""
    from jasme_jats.report import structure_conflict_text
    _, plan, _ = _mechanical(fn_span_article(tmp_path, FN_SPAN_CASES["three_mixed"], "other", 1), journal)
    text_ = structure_conflict_text(plan)
    returned = plan.fn_guess_notes[0]
    assert text_.count("ほかに、文字から注の見出しと推定される「注」だけの段落") == 1
    assert f"だけの段落 {returned}「注」があります" in text_ and "一緒に決めてから変換し直してください" in text_
    lost = [s for c in plan.structure_conflicts for s in c.lost]
    assert returned not in lost
    _, plan2, _ = _mechanical(conflict_doc(tmp_path, "K1_fn_style2"), journal)
    assert "ほかに" not in structure_conflict_text(plan2)


_NAME1, _NAME2 = _p("author_ja", "試験　六郎"), _p("author_ja", "架空　花子")
# 名前 -> (元の形〈CONFLICT_DOCS の名前か make_conflict の引数〉, 中止の文にある直し方の言葉, 直し方どおりに Word で直した形の
# make_conflict の引数)。直した形は、元の段落の文字を変えずに、段落を消す・移す・スタイルを変える・著者表の欄に並べることだけで作る
ADVICE_FIXES = {
    # 引用文献 → 注 → 参考文献: 後ろの文献を前の引用文献の節の最後に移してから「参考文献」を消す
    "ref_between": ("K1_fn_after_refs_then_ref_again", "の節の最後に移してから",
                    dict(back=[_p("ref_head", "引用文献"), _REF, _REF2, _p("fn_head", "注"), _FN1])),
    # 付記 → 引用文献 → 付記: 後の付記の本文を前の付記の後ろに移してから、後ろの「付記」を消す
    "notes_between": ("K1_notes_notes", "）の最後に移してから",
                      dict(back=[_p("notes_head", "付記"), _p("body", "先の付記。"), _p("body", "後の付記。"), _p("ref_head", "引用文献"),
                                 _REF])),
    # 注 → 引用文献 → 注、謝辞 → 引用文献 → 謝辞: 同じく、後ろの節の段落を前の節の最後に移してから、後ろの見出しを消す
    "fn_between": (dict(back=[_p("fn_head", "注"), _FN1, _p("ref_head", "引用文献"), _REF, _p("fn_head", "注"),
                              _p("body", "2) 二つ目の注。")]), "の節の最後に移してから",
                   dict(back=[_p("fn_head", "注"), _FN1, _p("body", "2) 二つ目の注。"), _p("ref_head", "引用文献"), _REF])),
    "ack_between": (dict(back=[_p("ack_head", "謝辞"), _p("body", "先の謝辞の本文。"), _p("ref_head", "引用文献"), _REF,
                               _p("ack_head", "謝辞"), _p("body", "後の謝辞の本文。")]), "）の最後に移してから",
                    dict(back=[_p("ack_head", "謝辞"), _p("body", "先の謝辞の本文。"), _p("body", "後の謝辞の本文。"),
                               _p("ref_head", "引用文献"), _REF])),
    # 間に節がない: 後ろの見出しを消すだけ
    "ref_ref": ("K1_ref_ref", "の段落を消してください（その後ろの段落は、前の見出し",
                dict(back=[_p("ref_head", "引用文献"), _REF, _REF2])),
    "ack_ack": ("K1_ack_ack_style", "の段落を消してください（その後ろの段落は、前の節",
                dict(back=[_p("ack_head", "謝辞"), _p("body", "先の謝辞の本文。"), _p("body", "後の謝辞の本文。"), _p("ref_head", "引用文献"),
                           _REF])),
    # 注の見出しが 2 つ: 注の一覧が 2 つに分かれているなら後ろの「注」を消す。そうでなければ 1 つだけを「注見出し」、ほかを「注本文」に
    "fn_two_lists": ("K1_fn_style2", "注の一覧が 2 つに分かれているなら、後ろの見出し",
                     dict(body=[_p("fn_head", "注"), _FN1, _p("body", "2) 二つ目の注。")])),
    "fn_one_heading": ("K1_fn_text2_kept", "ほかの「注」（表の注の見出しなど）は「注本文」スタイル",
                       dict(body=[_p("fn_head", "注"), _FN1, _p("fn_body", "注"), _p("body", "2) 二つ目の注。")])),
    # 英文要旨の見出しが 2 つ: 要らない方の見出しを消す（後ろでも前でも）
    "abstract_later": ("X_abstract_heading2", "要らない方の見出しの段落を消して",
                       dict(en_after=[_p("abs", "Second abstract.")])),
    "abstract_earlier": ("X_abstract_heading2", "要らない方の見出しの段落を消して",
                         dict(en_heading=False, en_after=[_p("abs_head", "Abstract"), _p("abs", "Second abstract.")])),
    # 所属・所属・著者（1 人の著者に所属が 2 つ）: テンプレートの著者表の、その著者の行の所属の欄に段落を分けて並べる
    "aff_two_loose": ("K2_loose_aff_aff_author", "テンプレートの著者表を使い、その著者の行の所属の欄に段落を分けて並べて",
                      dict(ja_rows=(("第一大学\n第二大学", "試験　六郎"),))),
    "aff_trailing": ("K2_loose_trailing_aff", "テンプレートの著者表を使い、その著者の行の所属の欄に段落を分けて並べて",
                     dict(ja_rows=(("第一大学\n第二大学", "試験　六郎"),))),
    # 同じ所属を重ねて書いた: どちらかを消す
    "aff_dup": ("K2_loose_dup_aff", "同じ所属を重ねて書いたのなら、どちらかの段落を消して",
                dict(ja_rows=(), loose=(_p("aff_ja", "第一大学"), _NAME1, _p("aff_ja", "第一大学"), _NAME2))),
    # 著者名の後ろに書いたほかの著者の所属（著者名・所属・所属・著者名）: その著者名の段落のすぐ前に移す
    "aff_other_author": (dict(ja_rows=(), loose=(_NAME1, _p("aff_ja", "第一大学"), _p("aff_ja", "第二大学"), _NAME2)),
                         "その著者名の段落のすぐ前に移して",
                         dict(ja_rows=(), loose=(_p("aff_ja", "第一大学"), _NAME1, _p("aff_ja", "第二大学"), _NAME2))),
    # 著者表: 著者名のない所属の行の所属を、その所属が付く著者の行の所属の欄に移す
    "aff_table_row": ("K2_table_affonly_row_first", "その所属が付く著者の行の所属の欄に移し、段落を分けて並べて",
                      dict(ja_rows=(("第一大学\n第二大学", "試験　六郎"),))),
    "aff_table_last": ("K2_table_affonly_row_last", "ほかの著者の所属なら、その著者の行の所属の欄に移し",
                       dict(ja_rows=(("第一大学\n第二大学", "試験　六郎"),))),
    # 著者表の所属の行の著者名が表の外: 著者名をその行の著者名の欄に移す
    "aff_table_name_outside": ("K2_table_then_loose_author", "その著者名をこの行の著者名の欄に移して",
                               dict(ja_rows=(("第一大学", "試験　六郎"),))),
}


@pytest.mark.parametrize("name", list(ADVICE_FIXES))
def test_advice_fixed_docx_passes(name, journal, meta, tmp_path):
    """中止の文（report.structure_conflict_text）の Word での直し方どおりに直した docx は、中止せず、不変性チェックに合格し、要対応が
    ない。間に別の後付けの節がある形（引用文献 → 注 → 参考文献、付記 → 引用文献 → 付記など）の文だけが「移して」と案内し、直した形
    では後ろの文献・付記の本文などが前の節に入る（間の節に入らない）。"""
    orig, phrase, fixed = ADVICE_FIXES[name]
    path = conflict_doc(tmp_path, orig) if isinstance(orig, str) else mf.make_conflict(tmp_path / f"{name}_orig.docx", **orig)
    _, plan, _ = _mechanical(path, journal)
    assert plan.structure_conflicts, name
    msg = structure_conflict_text(plan)
    assert phrase in msg, (name, msg)
    between = [c.between for c in plan.structure_conflicts if c.kind != "aff"]
    assert ("移してから" in msg) == any(between), name
    res = convert(mf.make_conflict(tmp_path / f"{name}_fixed.docx", **fixed), meta, journal,
                  Options(out_dir=tmp_path / "out"))
    p = res.plan
    assert p.structure_conflicts == [] and res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid, name
    assert not [a.key for a in actions(res) if a.level == NEEDS_ACTION], name
    fn_paras = [[x.plain() for x in fn.paras] for fn in p.fns]
    refs = [r.para.plain() for r in p.refs]
    if name == "ref_between":
        assert refs == [_REF_TEXT, _REF2_TEXT] and fn_paras == [["1) 注の本文である。"]]
    if name == "notes_between":
        assert [c.para.plain() for c in p.notes.children] == ["先の付記。", "後の付記。"] and refs == [_REF_TEXT]
    if name == "ref_ref":
        assert refs == [_REF_TEXT, _REF2_TEXT] and p.ref_heading.plain() == "引用文献"
    if name == "fn_between":
        assert fn_paras == [["1) 注の本文である。"], ["2) 二つ目の注。"]] and refs == [_REF_TEXT]
    if name in ("ack_ack", "ack_between"):
        assert [c.para.plain() for c in p.ack.children] == ["先の謝辞の本文。", "後の謝辞の本文。"]
    if name in ("fn_two_lists", "fn_one_heading"):
        assert [fn.number for fn in p.fns] == [1, 2] and p.fn_heading.plain() == "注"
    if name in ("abstract_later", "abstract_earlier"):
        assert [x.plain() for x in p.abstract] == ["Small article abstract.", "Second abstract."]
    if name.startswith("aff_"):
        affs = [[x.ja.plain() for x in a.affs] for a in p.authors]
        assert affs == {"aff_dup": [["第一大学"], ["第一大学"]], "aff_other_author": [["第一大学"], ["第二大学"]],
                        "aff_table_name_outside": [["第一大学"]]}.get(name, [["第一大学", "第二大学"]]), name


def test_advice_delete_only_misplaces_paragraphs_between_sections(journal, meta, tmp_path):
    """間に別の後付けの節がある形で、案内の「移して」をせずに後ろの見出しを消すだけだと、後ろの文献・付記の本文が間の節に入る
    （不変性チェックは合格し、知らせもない。だから中止の文は、先に後ろの節の段落を前の節の最後に移すよう案内する）。"""
    res = convert(mf.make_conflict(tmp_path / "ref.docx", back=[_p("ref_head", "引用文献"), _REF, _p("fn_head", "注"), _FN1, _REF2]),
                  meta, journal, Options(out_dir=tmp_path / "a"))
    assert res.fidelity.ok and [r.para.plain() for r in res.plan.refs] == [_REF_TEXT]
    assert [[x.plain() for x in fn.paras] for fn in res.plan.fns] == [["1) 注の本文である。", _REF2_TEXT]]     # 文献が注の続きになる
    res = convert(mf.make_conflict(tmp_path / "notes.docx", back=[_p("notes_head", "付記"), _p("body", "先の付記。"),
                                                                 _p("ref_head", "引用文献"), _REF, _p("body", "後の付記。")]),
                  meta, journal, Options(out_dir=tmp_path / "b"))
    assert res.fidelity.ok and [c.para.plain() for c in res.plan.notes.children] == ["先の付記。"]
    assert [r.para.plain() for r in res.plan.refs] == [_REF_TEXT, "後の付記。"]          # 付記の本文が引用文献の 2 件目になる


# ----------------------------------------------------------------------------- 空白だけの段落は領域を切り替えない（C041）
def _midbody(style, tail_text="原稿の続きである。"):
    """本文の途中に、スタイルが後付け・英文要旨の見出しの、空白だけの段落を置き、後ろに章見出しと本文を続ける。"""
    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "本文の前半である（試験，2024）。"),
                mf.para(S[style]),
                mf.para(S["sec1"], "２．方法"), mf.para(S["body"], tail_text)]
    return parts


@pytest.mark.parametrize("style", ["ref_head", "fn_head", "notes_head", "ack_head", "abs"])
def test_blank_paragraph_with_back_heading_style_does_not_switch_region(style, journal, meta, tmp_path):
    """本文の途中の、空白だけで後付け・英文要旨の見出しのスタイルが付いた段落では、領域を切り替えない。後ろの章見出しと本文は
    本文のまま残り、本物の引用文献だけが <ref>、本物の英文要旨だけが英文要旨になる。"""
    path = tmp_path / "blank.docx"
    mf.make_article(path, "空白の見出しスタイルの検証用文書", _midbody(style))
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    got = outline(res)
    assert got["sec"] == ["１．はじめに", "２．方法"] and got["ref"] == 1
    assert got["trans-abstract"] == ["Small article abstract."] and not got["fn-group"]
    root = load(res)
    assert "原稿の続きである。" in text(root.find("body")) and root.find(".//back//notes") is None
    assert "原稿の続きである。" not in "".join(text(r) for r in root.iter("ref"))
    blank = next(p for p in res.plan.paras.values() if p.style_id == S[style] and not p.plain())
    assert res.plan.region[blank.src] == "body"
    assert not [a.key for a in actions(res) if a.level == NEEDS_ACTION]
    assert not [a.key for a in actions(res) if a.key == "excluded_unsure"]


def test_blank_sec1_after_guessed_note_does_not_return_notes_to_body(journal, meta, tmp_path):
    """文字から注の見出しと推定した「注」と注の一覧の後ろの、空白だけの章見出しスタイルの段落は、注を本文に戻す合図にしない。"""
    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "本文である（試験，2024）。"),
                mf.para(S["body"], "注"), mf.para(S["body"], "1) 注の内容である。"), mf.para(S["sec1"])]
    path = tmp_path / "note_blank.docx"
    mf.make_article(path, "注の後ろの空白の検証用文書", parts)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    assert [fn.number for fn in res.plan.fns] == [1] and res.plan.fn_heading is not None
    assert not any("本文に戻した" in d.message for d in res.plan.decisions)


def test_blank_paragraph_switch_is_recorded_when_ignored(journal, meta, tmp_path):
    """空白だけの見出しスタイルの段落を領域の切り替えに使わなかったことは、判断の一覧に記録する。"""
    path = tmp_path / "blank.docx"
    mf.make_article(path, "空白の見出しスタイルの検証用文書", _midbody("ref_head"))
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    assert any("空白だけ" in d.message and "領域" in d.message for d in res.plan.decisions)


# ----------------------------------------------------------------------------- 空白だけの見出しの後ろに中身が続くときは切り替える（C041 の例外）
def test_blank_ref_heading_followed_by_references_still_switches(journal, meta, tmp_path):
    """後付けの見出しのスタイルが空の段落の直後に、参考文献スタイルの文献が続くときは、今までどおり引用文献の節に切り替える
    （本物の中身が本文の段落 <p> にならない）。"""
    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "本文である（試験，2024）。"),
                mf.para(S["ref_head"]), mf.para(S["ref"], _REF2_TEXT)]
    path = tmp_path / "blank_ref.docx"
    mf.make_article(path, "空の引用文献見出しの検証用文書", parts)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    assert [r.para.plain() for r in res.plan.refs] == [_REF2_TEXT, _REF_TEXT]
    assert _REF2_TEXT not in text(load(res).find("body"))


def test_blank_fn_heading_followed_by_notes_still_switches(journal, meta, tmp_path):
    """空の注の見出しのスタイルの段落の直後に、注本文スタイルの注が続くときは、注の節に切り替える。"""
    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "本文である（試験，2024）。"),
                mf.para(S["fn_head"]), mf.para(S["fn_body"], "1) 注の内容である。")]
    path = tmp_path / "blank_fn.docx"
    mf.make_article(path, "空の注の見出しの検証用文書", parts)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    assert [[x.plain() for x in fn.paras] for fn in res.plan.fns] == [["1) 注の内容である。"]]
    assert "注の内容である。" not in text(load(res).find("body"))


def test_blank_heading_followed_by_body_text_does_not_switch(journal, meta, tmp_path):
    """もとの C041 の形: 空の見出しスタイル（引用文献・注）の段落の後ろに本文が続くときは、切り替えない。"""
    for style in ("ref_head", "fn_head"):
        def parts(b, style=style):
            return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "本文である（試験，2024）。"),
                    mf.para(S[style]), mf.para(S["body"], "原稿の続きである。")]
        path = tmp_path / f"blank_{style}.docx"
        mf.make_article(path, "空の見出しの後ろの本文の検証用文書", parts)
        res = convert(path, meta, journal, Options(out_dir=tmp_path / style))
        assert res.fidelity.ok and res.dtd_valid
        assert len(res.plan.refs) == 1 and not res.plan.fns
        assert "原稿の続きである。" in text(load(res).find("body"))


def test_blank_back_heading_inside_back_does_not_steal_following_references(journal, meta, tmp_path):
    """後付けの中の、空白だけの謝辞の見出しのスタイルの段落は、後ろに参考文献スタイルの文献が続くなら節を切り替えない（文献が
    謝辞にならない）。本物の謝辞の本文が続くときは、今までどおり謝辞の節に切り替える。"""
    def refs(b):
        return [mf.para(S["ack_head"]), mf.para(S["ref"], _REF2_TEXT)]
    path = tmp_path / "back_ref.docx"
    mf.make_article(path, "後付けの中の空白の見出しの検証用文書", lambda b: [mf.para(S["sec1"], "１．はじめに")], refs=refs)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "a"))
    assert res.fidelity.ok and res.dtd_valid
    assert [r.para.plain() for r in res.plan.refs] == [_REF_TEXT, _REF2_TEXT] and res.plan.ack is None

    def refs2(b):
        return [mf.para(S["ack_head"]), mf.para(S["body"], "謝辞の本文である。")]
    path = tmp_path / "back_ack.docx"
    mf.make_article(path, "後付けの中の空白の見出しの検証用文書", lambda b: [mf.para(S["sec1"], "１．はじめに")], refs=refs2)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "b"))
    assert res.fidelity.ok and res.dtd_valid
    assert [c.para.plain() for c in res.plan.ack.children] == ["謝辞の本文である。"] and len(res.plan.refs) == 1
