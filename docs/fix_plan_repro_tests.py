"""docs/FIX_PLAN.md の不具合を再現するテスト（0.18.1 の時点の振る舞いを確かめる）。

このファイルは tests/ の外に置いてあり、通常のテスト（python -m pytest）では実行されない。
各テストは「今の誤った振る舞い」を assert で固定している（名前に PROBLEM を付けたもの）。修正すると、その assert が失敗する。
修正の作業では、該当するテストの期待を逆にして tests/ の正式なテストに取り込む（docs/FIX_PLAN.md の「計画全体で足した作業」）。

実行のしかた（tests/conftest.py のフィクスチャ journal・meta を使うため、tests/ に一時的に写して実行し、終わったら消す）:

    cp docs/fix_plan_repro_tests.py tests/test_zz_fix_plan_repro.py
    python -m pytest -q tests/test_zz_fix_plan_repro.py
    rm tests/test_zz_fix_plan_repro.py
"""
import json
import sys
import zipfile
from pathlib import Path

import pytest
from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parent))   # tests/ に写して実行する
import make_fixtures as mf  # noqa: E402
from conftest import FULL, TEMPLATE  # noqa: E402
from jasme_jats.config import ArticleMeta  # noqa: E402
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


# --------------------------------------------------------------------------- 1. アップロード用 ZIP の中身
def test_PROBLEM_zip_contains_youhenkan_folder(journal, meta, tmp_path):
    """EMF を変換できなかったとき、元の EMF を入れた「要変換/」フォルダが記事フォルダの中に作られ、
    J-STAGE にアップロードする ZIP にそのまま入る（日本語のフォルダ名・EMF ファイル）。"""
    res = convert(TEMPLATE, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    names = zipfile.ZipFile(res.zip_path).namelist()
    assert any("要変換" in n and n.endswith(".emf") for n in names), names
    # jstage_rules は画像の名前しか見ないので、このフォルダは検出されない
    assert res.jstage_issues == []


def test_PROBLEM_zip_accumulates_articles_in_shared_out_dir(journal, tmp_path):
    """同じ出力フォルダで 2 本目を変換すると、2 本目の ZIP に 1 本目の記事フォルダも入る（コマンドラインの既定 --out output）。"""
    m1 = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "peer_review": "あり"})
    m2 = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "13", "peer_review": "あり"})
    convert(FULL, m1, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    r2 = convert(FULL, m2, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    names = zipfile.ZipFile(r2.zip_path).namelist()
    assert any(n.startswith("jasme/31/1/31_1/") for n in names), names
    assert any(n.startswith("jasme/31/1/31_13/") for n in names)


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


# --------------------------------------------------------------------------- 4. 英文要旨の後ろの段落
def test_PROBLEM_appendix_with_paren_goes_into_abstract(journal, meta, tmp_path):
    """「資料（…）」のように、「資料」の直後がかっこの見出しは資料と認識されず、その後の段落ごと英文要旨（trans-abstract）に入る。"""
    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "本文。")]
    path = make_doc(tmp_path / "app.docx", parts, abstract=["This is the abstract."],
                    appendix=[mf.para(S["abs"], "資料（授業プリント）"), mf.para(S["abs"], "問1　次の式を計算せよ。")])
    res = convert(path, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    root = load(res)
    abstract = text(root.find(".//trans-abstract"))
    assert "資料（授業プリント）" in abstract and "次の式を計算せよ" in abstract
    assert root.find(".//app-group") is None
    assert res.jstage_issues == []       # J-STAGE のチェックでも気づけない


def test_appendix_with_space_is_recognized(journal, meta, tmp_path):
    """比較: 「資料　…」（空白）なら資料として認識される。"""
    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "本文。")]
    path = make_doc(tmp_path / "app2.docx", parts, abstract=["This is the abstract."],
                    appendix=[mf.para(S["abs"], "資料　授業プリント"), mf.para(S["abs"], "問1　次の式を計算せよ。")])
    res = convert(path, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    assert load(res).find(".//app-group/app") is not None


# --------------------------------------------------------------------------- 6. 表の行がコンテンツコントロールに入っていると読まれない
def test_PROBLEM_table_row_inside_sdt_is_not_read(journal, meta, tmp_path):
    """w:sdt（コンテンツコントロール）で包まれた表の行（w:tr）は read_table が見ないので、その文字が XML に出ず、
    不変性チェックが不合格になる（docx が正しくても変換結果を使えない）。"""
    def parts(b):
        tbl = ('<w:tbl><w:tblPr><w:tblStyle w:val="a5"/><w:tblW w:w="0" w:type="auto"/></w:tblPr>'
               '<w:tblGrid><w:gridCol w:w="2000"/></w:tblGrid>'
               + "<w:tr>" + mf.cell("見える行") + "</w:tr>"
               + "<w:sdt><w:sdtPr/><w:sdtContent><w:tr>" + mf.cell("コンテンツコントロールの行") + "</w:tr></w:sdtContent></w:sdt>"
               + "</w:tbl>")
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["tab_cap"], "表1　検証"), tbl, mf.para(S["body"], "")]
    path = make_doc(tmp_path / "sdt.docx", parts)
    res = convert(path, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    assert not res.fidelity.ok
    assert any("コンテンツコントロールの行" in t for _, t in res.fidelity.missing)


# --------------------------------------------------------------------------- 7. 文末脚注は XML に出ない
def test_PROBLEM_endnotes_are_excluded(journal, meta, tmp_path):
    """Word の文末脚注（注を末尾にまとめる機能。脚注より「注」の書き方に近い）は、本文の参照も注の本文も XML に出ない。"""
    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"),
                mf.para(S["body"], "文末脚注", '<w:r><w:rPr><w:rStyle w:val="a9"/></w:rPr><w:endnoteReference w:id="3"/></w:r>',
                        "が付いた文。")]
    path = make_doc(tmp_path / "end.docx", parts)
    # endnotes.xml に注を足す
    tmp = tmp_path / "end2.docx"
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/endnotes.xml":
                data = data.decode("utf-8").replace(
                    "</w:endnotes>",
                    '<w:endnote w:id="3"><w:p><w:r><w:endnoteRef/></w:r><w:r><w:t xml:space="preserve"> 文末脚注の本文である。'
                    '</w:t></w:r></w:p></w:endnote></w:endnotes>').encode("utf-8")
            zout.writestr(item, data)
    res = convert(tmp, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    assert res.fidelity.ok and res.dtd_valid      # 検査は通る（除外として記録されるため）
    root = load(res)
    assert "文末脚注の本文である" not in text(root)
    assert root.find(".//fn-group") is None
    assert any("文末脚注" in reason for _, reason, _ in res.fidelity.excluded)


# --------------------------------------------------------------------------- 8. 不変性チェックの穴
def test_PROBLEM_fidelity_does_not_flag_paragraph_both_output_and_excluded(journal, meta):
    """出力した段落が除外にも登録されていても、不変性チェックは何も言わない（verify の pass 分岐）。"""
    from jasme_jats.builder import build
    from jasme_jats.fidelity import verify
    from jasme_jats.model import Exclusion
    doc, plan, _ = _mechanical(FULL, journal)
    root, info = build(plan, meta, journal)
    src = next(p.src for p in plan.paras.values() if p.role == "p" and len(p.plain()) > 10)
    res = verify(FULL, root, plan.exclusions + info.exclusions + [Exclusion(src, "試験", "x")])
    assert res.ok


# --------------------------------------------------------------------------- 9. 図表参照の誤検出
def test_PROBLEM_figure_reference_inside_word(journal):
    """「地図1」「図表1」のような語の中の「図1」「表1」が図・表へのリンクになる。"""
    from jasme_jats.linker import RE_FIGREF, RE_TABREF
    assert RE_FIGREF.search("地図1に示す").group(0) == "図1"
    assert RE_TABREF.search("図表1に示す").group(0) == "表1"
    assert RE_TABREF.search("発表1回目の").group(0) == "表1"


# --------------------------------------------------------------------------- 10. 日付の入力
def test_PROBLEM_date_with_slash_not_zero_padded():
    """「2026/3/31」「2026.3.31」は、区切りを置き換える処理があるのに読めない（ゼロ埋めが必要）。"""
    from jasme_jats.config import _date
    with pytest.raises(ValueError):
        _date("2026/3/31")
    assert _date("2026/03/31") is not None


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


# --------------------------------------------------------------------------- N1・N2・N3（計画づくりで見つけたもの）
def test_PROBLEM_N3_blank_paragraph_in_textbox_fails_fidelity(journal, meta, tmp_path):
    """文字だけのテキストボックスに全角空白だけの段落があると、除外にも出力にもならず、不変性チェックが不合格になる。"""
    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"),
                mf.para(S["body"], "本文。", mf.textbox(mf.para(S["body"], "問1\u3000計算せよ。")
                                                       + mf.para(S["body"], "\u3000"), 501))]
    path = make_doc(tmp_path / "n3.docx", parts)
    res = convert(path, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    assert not res.fidelity.ok
    assert [t for _, t in res.fidelity.missing] == ["\u3000"]


def test_PROBLEM_N2_textbox_style_switches_region(journal, meta, tmp_path):
    """本文中のテキストボックスに「英文要旨」スタイルの段落が 1 つあると、以降の本文と引用文献がすべて英文要旨に入る。
    不変性チェック・DTD・J-STAGE のチェックはすべて合格する。"""
    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"),
                mf.para(S["body"], "本文一。", mf.textbox(mf.para(S["abs"], "Label in English"), 502)),
                mf.para(S["sec1"], "２．方法"), mf.para(S["body"], "本文二。"),
                mf.para(S["ref_head"], "引用および参考文献"), mf.para(S["ref"], "試験太郎（2020）．「題」．『誌』，1，1-2．")]
    path = make_doc(tmp_path / "n2.docx", parts)
    res = convert(path, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    assert res.fidelity.ok and res.dtd_valid
    root = load(res)
    assert len(root.findall(".//body/sec")) == 1          # 「２．方法」の章がない
    assert root.find(".//ref") is None                     # 引用文献がない
    abstract = [text(p) for p in root.findall(".//trans-abstract/p")]
    assert "２．方法" in abstract and "本文二。" in abstract


def test_PROBLEM_N1_image_in_reference_is_lost_silently(journal, meta, tmp_path):
    """引用文献の段落にある画像は、XML にも Graphics にも出ず、警告もない（不変性チェックは文字しか見ない）。"""
    def parts(b):
        rid = b.add_image("refimg.png", mf.png_bytes("ref image"))
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "本文。"),
                mf.para(S["ref_head"], "引用および参考文献"),
                mf.para(S["ref"], "試験太郎（2020）．「題」．『誌』，1，1-2．"),
                mf.para(S["ref"], mf.drawing(rid, 1800000, 1000000, 601))]
    path = make_doc(tmp_path / "n1.docx", parts)
    res = convert(path, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    assert res.fidelity.ok and res.images == []
    root = load(res)
    assert not list(root.iter("graphic")) and not list(root.iter("inline-graphic"))
    assert not any("img" in w for w in res.warnings)
