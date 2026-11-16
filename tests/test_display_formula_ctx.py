"""別行数式（m:oMathPara）を DTD が認めない文脈のうち、章や節の見出し・後付けの見出し・題目に置いたとき、
<disp-formula> ではなく <inline-formula> で書き、DTD に合わせる。<p> の中（本文・キャプション・注）は今までどおり <disp-formula>。
引用文献の中は <disp-formula> のまま（DTD 不合格で止める。引用文献の後ろの資料が文献になった形〈C001〉の守り。C044）。"""
import zipfile

import make_fixtures as mf
from jasme_jats.config import ArticleMeta, JournalConfig
from jasme_jats.pipeline import Options, convert

S = mf.S
META = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12", "pub_date": "2026-03-31",
                              "received": "2025-06-01", "accepted": "2025-11-20", "peer_review": "あり",
                              "keywords": "proof; 論証"})
NOTE = "別行数式を置けない場所"


def DISP():
    return mf.omathpara(mf.mr("x") + mf.msup(mf.mr("y"), mf.mr("2")))


def _after_title(path):
    with zipfile.ZipFile(path) as z:
        items = {n: z.read(n) for n in z.namelist()}
    doc = items["word/document.xml"].decode("utf-8")
    i = doc.index("題目MARK")
    j = doc.index("</w:r>", i) + len("</w:r>")
    items["word/document.xml"] = (doc[:j] + mf.omathpara(mf.mr("t")) + doc[j:]).encode("utf-8")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for n, d in items.items():
            z.writestr(n, d)


def _run(tmp_path, title="題目", **kw):
    path = tmp_path / "a.docx"
    mf.make_article(str(path), title, **kw)
    if title == "題目MARK":
        _after_title(path)
    return convert(str(path), META, JournalConfig.load(), Options(out_dir=str(tmp_path / "out")))


def _xml(res):
    return res.xml_path.read_text(encoding="utf-8")


def _check_inline(res):
    xml = _xml(res)
    assert res.dtd_valid
    assert res.fidelity.ok and res.fidelity.final_ok
    assert "<inline-formula>" in xml
    assert "<disp-formula" not in xml and 'display="block"' not in xml
    assert any(NOTE in w for w in res.warnings)


def test_display_formula_in_reference_stays_display_and_fails_dtd(tmp_path):
    # 引用文献の中は行内にしない（資料が文献になった形を DTD 検証で止める）
    res = _run(tmp_path, body_parts=lambda b: [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "本文である。")],
               refs=lambda b: [mf.para(S["ref"], "試験七郎（2023）．「別の論文」．", DISP(), "『架空誌』，第6巻，pp.1-2．")])
    assert not res.dtd_valid and "<disp-formula" in _xml(res)
    assert res.fidelity.ok and res.fidelity.final_ok
    assert not any(NOTE in w for w in res.warnings)


def test_display_formula_in_section_heading_is_inline(tmp_path):
    res = _run(tmp_path, body_parts=lambda b: [mf.para(S["sec1"], "１．はじめに", DISP()), mf.para(S["body"], "本文である。")])
    _check_inline(res)


def test_display_formula_in_ack_heading_is_inline(tmp_path):
    res = _run(tmp_path, body_parts=lambda b: [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "本文である。"),
                                               mf.para(S["ack_head"], "謝辞", DISP()), mf.para(S["body"], "謝辞の文。")])
    _check_inline(res)


def test_display_formula_in_title_is_inline(tmp_path):
    res = _run(tmp_path, title="題目MARK",
               body_parts=lambda b: [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "本文である。")])
    _check_inline(res)


def test_display_formula_in_p_stays_disp_formula(tmp_path):
    res = _run(tmp_path, body_parts=lambda b: [
        mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "本文である。", DISP()),
        mf.para(S["fig_cap"], "図1　架空の図", DISP()), mf.para(S["tab_cap"], "表1　架空の表", DISP()),
        mf.para(S["fn_head"], "注"), mf.para(S["body"], "1) 注の文。", DISP())])
    assert _xml(res).count("<disp-formula") >= 3
    assert not any(NOTE in w for w in res.warnings)
