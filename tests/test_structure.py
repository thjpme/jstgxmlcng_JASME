"""論文の構造: 領域（和文の冒頭・本文・後付け・英文の部分）の分け方と、英文要旨の後ろの資料（付録）の見出し（修正計画の D3）。"""
import dataclasses
import functools
from types import SimpleNamespace

import pytest
from lxml import etree

import make_fixtures as mf
from conftest import STRUCTURE
from jasme_jats.docx_reader import read_docx
from jasme_jats.model import Atom, Cell, Para, Row, Table
from jasme_jats.pipeline import Options, _mechanical, convert
from jasme_jats.report import TO_CHECK, actions
from jasme_jats.structure import RE_APPENDIX, Classifier, appendix_heading, appendix_sentence

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
    last = f"{str(len(mf.STRUCTURE_SECTIONS) + 1).translate(mf.ZEN_DIGITS)}．おわりに"      # 最後の章（節を足すと番号が変わる）
    assert last == "３．おわりに" and last in got["sec"] and got["ref"] == 1
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
    res = convert(STRUCTURE, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False))
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
    root = load(convert(path, meta, journal, Options(out_dir=tmp_path / "small", convert_metafiles=False)))
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
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
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
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
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
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", ai_mode="manual", convert_metafiles=False))
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
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
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
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
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
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "ratio", convert_metafiles=False))
    assert [res.plan.paras[s].plain() for s in res.plan.abstract_ja] == ["ABC DEFG 漢字三"]


def test_sentence_shaped_heading_in_abstract_gets_style_guidance(journal, meta, tmp_path):
    # 「資料1　…。」のように「。」で終わる見出しは文とみなすので、最初の資料なら見出しと資料の段落が英文要旨に入る。この段落の
    # 知らせ（10 章の警告）は、見出しを付ける案内ではなく、その段落に見出しのスタイルを付ける案内にする（見出しはもう付いている）。
    # 見出しのスタイルを付ければ、文字はそのままで資料になる
    def make(style):
        path = tmp_path / f"{style}.docx"
        mf.make_article(path, "資料の見出しの検証用文書", lambda b: [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "本文。")],
                        appendix=[mf.para(S[style], "資料1\u3000架空の授業プリント。"), mf.para(S["abs"], "問1\u3000架空の和文の問いである。")])
        return convert(path, meta, journal, Options(out_dir=tmp_path / style, convert_metafiles=False))
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
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
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
