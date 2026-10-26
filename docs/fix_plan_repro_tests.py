"""docs/FIX_PLAN.md の不具合を再現するテスト（0.18.1 の時点の振る舞いを確かめる）。

このファイルは tests/ の外に置いてあり、通常のテスト（python -m pytest）では実行されない。
各テストは「今の誤った振る舞い」を assert で固定している（名前に PROBLEM を付けたもの）。修正すると、その assert が失敗する。
修正の作業では、該当するテストの期待を逆にして tests/ の正式なテストに取り込む（docs/FIX_PLAN.md の「計画全体で足した作業」）。
直した単位のテストは、このファイルから取り除く。単位 A（0.19.0）で取り除いたもの: 表の行がコンテンツコントロールに入っている
（逆は tests/test_reader.py・tests/test_pipeline.py の sample_reader.docx）、出力と除外の重なり（tests/test_fidelity.py）、
N1（tests/test_lost_images.py）、N2（tests/test_structure.py）、N3（tests/test_pipeline.py の
test_blank_paragraphs_in_textbox_and_endnote_are_excluded）。単位 B（0.20.0。U7・N9）に当たるテストは、このファイルには
もともとない（U7・N9 のテストは tests/test_pdfmatch.py に足した）。単位 B2（0.21.0。N10〜N14）も同じで、
再現と直した後の振る舞いのテスト（架空の文字）は、直すときに tests/test_pdfmatch.py に足した。単位 B3（0.22.0。N15〜N19）も同じで、
再現と直した後の振る舞いのテスト（架空の文字）は、直すときに tests/test_floats.py・tests/test_ai.py・tests/test_figure_body.py に足した。
単位 C（0.23.0。M1・M2・N4・U1）は tests/test_pipeline.py・tests/test_notebook.py に取り込んだ。
単位 D（0.23.1。U2・M4・N5）も、このファイルにはもともとない（再現と直した後の振る舞いのテストは、直すときに tests/test_pipeline.py・
tests/test_colab.py・tests/test_notebook.py・tests/test_pdfmatch.py・tests/test_ai.py・tests/test_floats.py・tests/test_figure_body.py・
tests/test_lost_images.py に足した）。
単位 E（0.24.0。N6・D4・D3）で取り除いたもの: 資料の見出しの直後がかっこ（test_PROBLEM_appendix_with_paren_goes_into_abstract。
逆は tests/test_structure.py の test_appendix_with_paren_is_not_in_abstract）とその比較（test_appendix_with_space_is_recognized。
tests/test_structure.py の test_appendix_heading_forms_are_recognized の「資料　授業プリント」）、Word の文末脚注が XML に出ない
（test_PROBLEM_endnotes_are_excluded。逆は tests/test_notes.py の test_endnotes_are_output_as_notes）。

実行のしかた（tests/conftest.py のフィクスチャ journal・meta を使うため、tests/ に一時的に写して実行し、終わったら消す）:

    cp docs/fix_plan_repro_tests.py tests/test_zz_fix_plan_repro.py
    python -m pytest -q tests/test_zz_fix_plan_repro.py
    rm tests/test_zz_fix_plan_repro.py
"""
import json
import sys
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parent))   # tests/ に写して実行する
import make_fixtures as mf  # noqa: E402
from jasme_jats.pipeline import Options, _mechanical, convert  # noqa: E402

S = mf.S


def load(res):
    return etree.fromstring(res.xml_path.read_bytes().split(b"\n", 2)[2])


def text(el):
    return "".join(el.itertext())


def make_doc(path, body_parts, abstract=("Abstract text."), appendix=None, extra_front=()):
    b = mf.Builder()
    body = []
    body += mf.front_ja(b, "検証用の題目", "―副題―", [("架空大学", "試験　太郎")])
    body += list(extra_front)
    body += body_parts(b)
    body += mf.front_en(b, "Title", "Subtitle", [("Taro SHIKEN", "Fictional University")], list(abstract))
    body += mf.tail(b, appendix=appendix)
    b.save(path, body)
    return path


# --------------------------------------------------------------------------- 2. 文字だけのテキストボックスが XML から消える
def test_PROBLEM_text_only_textbox_is_dropped_from_xml(journal, meta, tmp_path):
    """囲み（テキストボックス）に入れた問題文など、画像・表・キャプションを含まないテキストボックスの文字は
    XML に出力されない（レポート 6 章に載るだけ）。AI の set_role でも復活できない。"""
    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"),
                mf.para(S["body"], "次の問題を扱う。", mf.textbox(
                    mf.para(S["body"], "問1　次の二次方程式を解きなさい。")
                    + mf.para(S["body"], "ヒント: 因数分解を使う。"), 401, cx=5000000, cy=800000)),
                mf.para(S["body"], "以上が問題である。")]
    path = make_doc(tmp_path / "box.docx", parts)
    res = convert(path, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    assert res.fidelity.ok and res.dtd_valid
    xml_text = text(load(res))
    assert "次の二次方程式を解きなさい" not in xml_text
    assert any("テキストボックス内の文字" in reason for _, reason, _ in res.fidelity.excluded)
    # AI で役割を指定しても採用されない
    _, plan, _ = _mechanical(path, journal)
    src = next(s for s, p in plan.paras.items() if "二次方程式" in p.plain())
    resp = {"operations": [{"op": "set_role", "src": src, "text": "", "occurrence": 1, "target": "", "role": "p",
                            "image": "", "mathml": "", "surname": "", "given": "", "reason": "x", "confidence": "高"}],
            "placements": [], "notes": []}
    res2 = convert(path, meta, journal, Options(out_dir=tmp_path / "ai", ai_mode="manual", convert_metafiles=False,
                                                ai_response=json.dumps(resp, ensure_ascii=False)))
    assert res2.ai.rejected and "placements" in res2.ai.rejected[0][1]
    assert "次の二次方程式を解きなさい" not in text(load(res2))


# --------------------------------------------------------------------------- 3. 上付きの数字が注にリンクされる
def test_PROBLEM_superscript_exponent_linked_as_note(journal, meta, tmp_path):
    """上付きの「2」（cm²・x² の指数）が、注 2 があると注へのリンクにされる。"""
    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"),
                mf.para(S["body"], "面積は 3 cm", mf.run("2", sup=True), " である", mf.run("1)", sup=True), "。"),
                mf.para(S["fn_head"], "注"),
                mf.para(S["body"], "1) 一つ目の注。"),
                mf.para(S["body"], "2) 二つ目の注。")]
    path = make_doc(tmp_path / "sup.docx", parts)
    res = convert(path, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    links = [(text(x), x.get("rid")) for x in load(res).iter("xref") if x.get("ref-type") == "fn"]
    assert ("1)", "fn1") in links
    assert ("2", "fn2") in links          # ← 指数の 2 が注 2 へのリンクになる（誤り）


# --------------------------------------------------------------------------- 9. 図表参照の誤検出
def test_PROBLEM_figure_reference_inside_word(journal):
    """「地図1」「図表1」のような語の中の「図1」「表1」が図・表へのリンクになる。"""
    from jasme_jats.linker import RE_FIGREF, RE_TABREF
    assert RE_FIGREF.search("地図1に示す").group(0) == "図1"
    assert RE_TABREF.search("図表1に示す").group(0) == "表1"
    assert RE_TABREF.search("発表1回目の").group(0) == "表1"


# --------------------------------------------------------------------------- 11. 自動番号の番号付けが本文と脚注・テキストボックスで共有される
def test_numbering_counter_is_global_across_parts():
    """numbering.Numbering の計数は読み取り順（本文→脚注）で共有される（Word も同じ numId なら共有するので、これは仕様の確認）。"""
    from jasme_jats.numbering import Numbering
    from jasme_jats.ooxml import parse_xml
    xml = b'''<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
    <w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1)"/></w:lvl></w:abstractNum>
    <w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>'''
    n = Numbering(parse_xml(xml))
    assert [n.label("1", 0) for _ in range(3)] == ["1)", "2)", "3)"]


# --------------------------------------------------------------------------- 12. 削除された段落記号
def test_PROBLEM_deleted_paragraph_mark_keeps_two_paragraphs(journal, meta, tmp_path):
    """段落記号が削除された変更履歴（2 段落を 1 つにつなぐ変更）は、承諾すると 1 段落になるが、ツールは 2 段落のまま出力する
    （削除された文字は除くのに、段落の結合は反映されない）。"""
    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"),
                '<w:p><w:pPr><w:pStyle w:val="af5"/><w:rPr><w:del w:id="9" w:author="x"/></w:rPr></w:pPr>'
                '<w:r><w:t>前半の文と</w:t></w:r></w:p>',
                mf.para(S["body"], "後半の文。")]
    path = make_doc(tmp_path / "pmark.docx", parts)
    res = convert(path, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    assert res.fidelity.ok
    ps = [text(p) for p in load(res).iter("p")]
    assert "前半の文と" in ps and "後半の文。" in ps and "前半の文と後半の文。" not in ps
