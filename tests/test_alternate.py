"""mc:AlternateContent（Choice と Fallback のどちらを採るか）。

MCE の規則どおり、Choice の Requires の接頭辞を名前空間に解決し、本ツールが読める名前空間だけの Choice を採る。そうでなければ
Fallback を採る（ooxml.choose_alternate）。Word 2016 以降が記号の挿入で入れる文字（w16se:symEx。C012）は Fallback の w:t を読む。
読み取り・検証・ルート2 が同じ前処理を共有するので、ルート1 の XML・ルート2 の直し・補完の確かめのどれでも文字が 1 回だけ出ること
を確かめる。
"""
import zipfile

import pytest
from lxml import etree

import make_fixtures as mf
from jasme_jats import pdfdocx
from jasme_jats.docx_reader import read_docx
from jasme_jats.fidelity import source_texts
from jasme_jats.ooxml import MC_NS, choose_alternate, paragraph_ids, preprocess, w
from jasme_jats.pipeline import Options, convert
from test_pdfmatch import N10_TAIL, SMALL_FRONT, TALK, body_lines, convert_with_pages, load, n10_pages, texts

SYMEX_NS = "http://schemas.microsoft.com/office/word/2015/wordml/symex"
W16SE = f'xmlns:w16se="{SYMEX_NS}"'


def symex(char, fallback, requires="w16se", ns=W16SE):
    """記号の挿入（Word 2016 以降）が書く形。w:r の中に置く。"""
    choice = f'<w16se:symEx w16se:font="ＭＳ 明朝" w16se:char="{char}"/>' if char else ""
    fb = f"<w:t>{fallback}</w:t>" if fallback else ""
    return (f'<w:r><mc:AlternateContent><mc:Choice Requires="{requires}" {ns}>{choice}</mc:Choice>'
            f"<mc:Fallback>{fb}</mc:Fallback></mc:AlternateContent></w:r>")


def tree(inner):
    return etree.fromstring(f"<w:body {mf.NSDECL}>{inner}</w:body>")


def after(inner):
    """前処理した後の w:body の中身を、文字（w:t と図形の印）で表す。"""
    root = preprocess(tree(inner))
    return ["".join(t.text for t in p.iter(w("t"))) for p in root.iter(w("p"))]


@pytest.mark.parametrize("ac, expect", [
    # 記号の挿入: w16se は読めないので Fallback の w:t を採る
    (symex("2460", "①"), "視点①から"),
    # Choice が空で Fallback にだけ文字がある形（REVIEW の R13）
    (symex("", "②"), "視点②から"),
    # 読めない名前空間の Choice に未知の Requires が混ざる（読めるものだけが揃っていなければ採らない）
    (symex("2460", "③", requires="wps w16se"), "視点③から"),
    # 接頭辞が宣言されていない Requires は、読めない名前空間として Fallback を採る
    (symex("", "④", requires="w16zz", ns=""), "視点④から"),
])
def test_choose_fallback_when_choice_is_not_understood(ac, expect):
    got = after(f"<w:p><w:r><w:t>視点</w:t></w:r>{ac}<w:r><w:t>から</w:t></w:r></w:p>")
    assert got == [expect]


URIS = {"wps": "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
        "wpg": "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup",
        "wpc": "http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas",
        "wpi": "http://schemas.microsoft.com/office/word/2010/wordprocessingInk",
        "w14": "http://schemas.microsoft.com/office/word/2010/wordml",
        "wp14": "http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing",
        "a14": "http://schemas.microsoft.com/office/drawing/2010/main"}


@pytest.mark.parametrize("requires", [*URIS, "wps wpg"])
def test_choose_choice_when_understood(requires):
    """読める名前空間（実際の原稿の図形・テキストボックスの wps・wpg・wpc を含む）の Choice は Choice を採り、Fallback は捨てる。"""
    decl = " ".join(f'xmlns:{p}="{URIS[p]}"' for p in requires.split())
    ac = (f'<w:r><mc:AlternateContent><mc:Choice Requires="{requires}" {decl}><w:t>選ぶ</w:t></mc:Choice>'
          "<mc:Fallback><w:t>捨てる</w:t></mc:Fallback></mc:AlternateContent></w:r>")
    assert after(f"<w:p>{ac}</w:p>") == ["選ぶ"]


def test_prefix_is_resolved_by_namespace_not_by_name():
    """接頭辞の名前ではなく名前空間で判断する: wps を別の名前空間に結び付けた Choice は読めない。"""
    ac = ('<w:r><mc:AlternateContent><mc:Choice Requires="wps" xmlns:wps="urn:other"><w:t>採らない</w:t></mc:Choice>'
          "<mc:Fallback><w:t>採る</w:t></mc:Fallback></mc:AlternateContent></w:r>")
    assert after(f"<w:p>{ac}</w:p>") == ["採る"]
    # 接頭辞が違っても、読める名前空間なら Choice を採る
    ac = ('<w:r><mc:AlternateContent><mc:Choice Requires="sh" xmlns:sh="http://schemas.microsoft.com/office/word/2010/'
          'wordprocessingShape"><w:t>採る</w:t></mc:Choice><mc:Fallback><w:t>採らない</w:t></mc:Fallback>'
          "</mc:AlternateContent></w:r>")
    assert after(f"<w:p>{ac}</w:p>") == ["採る"]


def test_alternate_without_fallback_or_choice():
    """Fallback がなければ（Word が読める名前空間を本ツールが知らないだけかもしれないので）Choice を採る。Choice がなければ
    Fallback、どちらもなければ何も出さない。"""
    only_choice = ('<w:r><mc:AlternateContent><mc:Choice Requires="w16se" ' + W16SE + "><w:t>残す</w:t></mc:Choice>"
                   "</mc:AlternateContent></w:r>")
    assert after(f"<w:p>{only_choice}</w:p>") == ["残す"]
    only_fb = "<w:r><mc:AlternateContent><mc:Fallback><w:t>代替</w:t></mc:Fallback></mc:AlternateContent></w:r>"
    assert after(f"<w:p>{only_fb}</w:p>") == ["代替"]
    assert after("<w:p><w:r><mc:AlternateContent/></w:r></w:p>") == [""]
    ac = tree("<w:p><w:r><mc:AlternateContent><mc:Fallback/></mc:AlternateContent></w:r></w:p>").find(f".//{{{MC_NS}}}Fallback")
    assert choose_alternate(ac.getparent()) is ac


def test_textbox_is_read_once_in_all_forms(tmp_path):
    """既存の wps のテキストボックス（Choice に DrawingML、Fallback に VML）は今までどおり 1 回だけ読む。"""
    def parts(b):
        return [mf.para(mf.S["sec1"], "１．はじめに"),
                mf.para(mf.S["body"], "枠の中の文を示す。", mf.textbox(mf.para(mf.S["body"], "枠の中の文"), 611))]
    path = tmp_path / "tb.docx"
    mf.make_article(path, "代替内容の検証用文書", parts)
    doc = read_docx(path)
    assert [p.text_only() for p in doc.all_paragraphs() if p.in_textbox] == ["枠の中の文"]


def para_text(src_texts, head):
    """不変性チェックの docx 側の文字（段落 ID -> 文字）のうち、head で始まる段落の文字（1 つだけ）。"""
    found = [t for t in src_texts.values() if t.startswith(head)]
    assert len(found) == 1
    return found[0]


def symex_article(tmp_path, parts_after=("から始める。",), mid=None):
    """本文に記号の挿入（①）が 1 つある小さな論文（ルート2 の PDF 照合に使う n10.docx）。"""
    mid = mid or symex("2460", "①")
    return [("body", ["視点", mid, *parts_after]), ("body", TALK)]


def test_symex_is_read_by_route1(tmp_path, journal, meta):
    """ルート1: 記号の挿入で入れた ① が XML にちょうど 1 回入り、不変性チェックは合格する。レポートに要対応・要確認は出ない。"""
    from test_pdfmatch import n10_article
    n10_article(tmp_path, journal, symex_article(tmp_path))
    docx = tmp_path / "n10.docx"
    assert para_text(source_texts(docx), "視点") == "視点①から始める。"
    res = convert(docx, meta, journal, Options(out_dir=tmp_path / "r1"))
    out = texts(load(res))
    assert out.count("視点①から始める。") == 1 and sum(t.count("①") for t in out) == 1
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    assert not res.needs_action


def test_symex_is_not_inserted_again_by_route2(tmp_path, journal, meta, monkeypatch):
    """ルート2: PDF にも ① がある。docx の ① は記号の挿入の文字として読むので、PDF の ① を足す (B) の挿入は作らない
    （Word で「①①」と二重に見えない）。補った docx を読み直しても ① は 1 つ、補完の確かめも合格する。"""
    from test_pdfmatch import n10_article
    n10_article(tmp_path, journal, symex_article(tmp_path))
    pages = n10_pages([*SMALL_FRONT, *body_lines("視点①から始める。"), *body_lines(TALK), *N10_TAIL])
    res = convert_with_pages(tmp_path, monkeypatch, journal, meta, pages, "pdf", docx=tmp_path / "n10.docx")
    fx = res.docx_fix
    assert [(f.old, f.new) for f in fx.fixes if f.applied] == []
    assert not any("①" in f.new for f in fx.fixes)
    out = texts(load(res))
    assert out.count("視点①から始める。") == 1
    assert res.fidelity.ok and res.supplement is not None and res.supplement.ok and res.supplement.supplied == 0
    assert para_text(source_texts(res.docx_fix.path), "視点") == "視点①から始める。"
    assert "<w:ins " not in pdfdocx_xml(res.docx_fix.path)


def pdfdocx_xml(path):
    with zipfile.ZipFile(path) as z:
        return z.read("word/document.xml").decode("utf-8")


def test_symex_with_other_fix_in_same_paragraph(tmp_path, journal, meta, monkeypatch):
    """記号の挿入のある段落の別の箇所は、今までどおり PDF に合わせて直せる（記号の挿入の単位は直せない単位として数える
    ので、直す位置はずれない）。"""
    from test_pdfmatch import n10_article
    n10_article(tmp_path, journal, symex_article(tmp_path, ("から始める。",)))
    pages = n10_pages([*SMALL_FRONT, *body_lines("視点①から順に始める。"), *body_lines(TALK), *N10_TAIL])
    res = convert_with_pages(tmp_path, monkeypatch, journal, meta, pages, "pdf", docx=tmp_path / "n10.docx")
    fx = res.docx_fix
    assert [(f.old, f.new) for f in fx.fixes if f.applied and f.kind == "text"] == [("", "順に")]
    assert res.supplement.ok and res.supplement.supplied == 1
    assert texts(load(res)).count("視点①から順に始める。") == 1
    assert para_text(source_texts(res.docx_fix.path), "視点") == "視点①から順に始める。"


def test_paragraph_ids_skip_only_unchosen_branch():
    """ルート2 が数える段落番号は、前処理した木（読み取り）と同じ: 採らなかった側（Fallback、または読めない Choice の中が
    Fallback より後のとき）の段落は数えない。"""
    inner = "<w:p><w:r><w:t>枠</w:t></w:r></w:p>"
    box = (f'<w:r><mc:AlternateContent><mc:Choice Requires="wps"><w:txbxContent>{inner}</w:txbxContent></mc:Choice>'
           f"<mc:Fallback><w:txbxContent>{inner}</w:txbxContent></mc:Fallback></mc:AlternateContent></w:r>")
    # Choice が読めない Requires のときは、Choice の中の段落を数えず、Fallback の中を数える
    odd = ('<w:r><mc:AlternateContent><mc:Choice Requires="w16se" ' + W16SE + f"><w:txbxContent>{inner}</w:txbxContent>"
           f"</mc:Choice><mc:Fallback><w:txbxContent>{inner}</w:txbxContent></mc:Fallback></mc:AlternateContent></w:r>")
    for ac, side in ((box, "Choice"), (odd, "Fallback")):
        root = tree(f"<w:p><w:r><w:t>前</w:t></w:r>{ac}</w:p><w:p><w:r><w:t>後</w:t></w:r></w:p>")
        raw = pdfdocx.raw_paragraph_ids(root, "d")
        pre = preprocess(etree.fromstring(etree.tostring(root)))
        want = {v: k for k, v in paragraph_ids(pre, "d").items()}
        assert set(raw) == set(want) == {"d1", "d2", "d3"}
        assert [a.tag for a in raw["d2"].iterancestors()][1] == f"{{{MC_NS}}}{side}"
        assert "".join(raw["d3"].itertext()) == "後"


def test_route2_fixes_paragraph_holding_a_textbox(tmp_path, journal, meta, monkeypatch):
    """図形（テキストボックス）のあるランを含む段落も、今までどおり ルート2 で直せる（図形の文字は別の段落で、この段落の
    文字には入らない。ランの中の mc:AlternateContent の図形は _Complex にしない）。"""
    from test_pdfmatch import n10_article
    box = mf.textbox(mf.para(mf.S["body"], "枠の中の文"), 611)
    n10_article(tmp_path, journal, [("body", ["枠を示す", box, "ので説明する。"]), ("body", TALK)])
    pages = n10_pages([*SMALL_FRONT, *body_lines("枠を示すので順に説明する。"), *body_lines(TALK), *N10_TAIL])
    res = convert_with_pages(tmp_path, monkeypatch, journal, meta, pages, "pdf", docx=tmp_path / "n10.docx")
    assert [(f.old, f.new) for f in res.docx_fix.fixes if f.applied and f.kind == "text"] == [("", "順に")]
    assert res.supplement.ok and res.supplement.supplied == 1
    doc = read_docx(res.docx_fix.path)
    assert [p.text_only() for p in doc.all_paragraphs() if p.in_textbox] == ["枠の中の文"]
