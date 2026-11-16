"""本文の途中の英文の部分のスタイルの段落（C083。要確認 style_check の en_in_body）。

本文の途中の段落に英文の部分の役割のスタイル（英文要旨・英文題目など）が付いていても、その後ろに引用文献の節のしるし
（引用文献の見出し・文献のスタイルの段落）があれば、本物の英文の部分は引用文献より後ろにあるので、領域を切り替えず本文の段落として出し、
Word でスタイルを直す知らせを出す。後ろに引用文献のしるしがなければ今までどおり切り替える（推定しない）。
"""
import make_fixtures as mf
import pytest
from lxml import etree

from jasme_jats import report
from jasme_jats.pipeline import Options, convert
from jasme_jats.report import actions

S = mf.S


def _mid(style, text):
    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "試験（2024）による。前半の本文である。"),
                mf.para(S[style], text),
                mf.para(S["body"], "後半の本文その 1。"), mf.para(S["sec1"], "２．方法"), mf.para(S["body"], "後半の本文その 2。")]
    return parts


def _convert(tmp_path, journal, meta, parts, name="e", **kw):
    path = tmp_path / f"{name}.docx"
    mf.make_article(path, "架空の題目", parts, **kw)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / f"out_{name}", ai_mode="none"))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid, (res.fidelity.missing, res.dtd_errors[:3])
    return res


def _keys(res):
    return [a.key for a in actions(res)]


def _src(res, text):
    return next(s for s, p in res.plan.paras.items() if p.plain() == text)


CASES = [("abs", "A stray English paragraph."), ("title_en", "A Stray English Title"), ("abs_head", "Abstract"),
         ("aff_en", "Fictional University"), ("abs", "架空の和文の 1 段落（スタイルだけ英文要旨）。")]


@pytest.mark.parametrize("style,text", CASES)
def test_english_style_in_body_stays_body(tmp_path, journal, meta, style, text):
    """後ろに引用文献があるなら、後ろの本文・「２．方法」は本文のまま、引用文献は引用文献のまま。段落は本文の段落（p）で出し、文字は変えない。"""
    res = _convert(tmp_path, journal, meta, _mid(style, text))
    for t in ("後半の本文その 1。", "後半の本文その 2。", "２．方法", text):
        assert res.plan.region[_src(res, t)] == "body", t
    assert res.plan.paras[_src(res, text)].role == "p"
    root = etree.fromstring(res.xml_base)
    titles = ["".join(t.itertext()) for t in root.findall(".//body/sec/title")]
    assert titles == ["１．はじめに", "２．方法"]
    body_p = ["".join(p.itertext()) for p in root.findall(".//body/sec/p")]
    assert text in body_p and "後半の本文その 1。" in body_p
    assert len(root.findall(".//ref")) == 1
    keys = _keys(res)
    assert "refs_missing" not in keys and "upload" not in keys
    sus = [x for x in res.plan.style_suspects if x.kind == "en_in_body"]
    assert [x.src for x in sus] == [_src(res, text)]
    act = next(a for a in actions(res) if a.key == "style_check")
    assert "本文の途中に、英文の部分のスタイル" in act.box_detail and "引用文献より後ろに移して" in act.box_detail
    assert "en_in_body" in report.STYLE_NO_AI_KINDS
    assert "ai_finish" not in keys


def test_consecutive_english_styles_each_stay_body(tmp_path, journal, meta):
    """連続する英文の役割の段落も、それぞれ同じ規則（どちらも本文の段落）。"""
    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "試験（2024）による。前半の本文である。"),
                mf.para(S["abs_head"], "Abstract"), mf.para(S["abs"], "A stray English paragraph."),
                mf.para(S["body"], "後半の本文。")]
    res = _convert(tmp_path, journal, meta, parts)
    assert [x.src for x in res.plan.style_suspects if x.kind == "en_in_body"] == [_src(res, "Abstract"), _src(res, "A stray English paragraph.")]
    assert res.plan.region[_src(res, "後半の本文。")] == "body"


def test_correct_manuscript_has_no_notice(tmp_path, journal, meta):
    """正しい原稿（英文の部分が引用文献の後ろ）では出ない。"""
    res = _convert(tmp_path, journal, meta, lambda b: [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "試験（2024）による。")])
    assert [x for x in res.plan.style_suspects if x.kind == "en_in_body"] == []


def test_appendix_after_english_abstract_has_no_notice(tmp_path, journal, meta):
    """英文要旨の後ろに資料（番号つきの見出しと本文）がある原稿でも、出ない（資料は本文の途中ではない）。"""
    res = _convert(tmp_path, journal, meta, lambda b: [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "試験（2024）による。")],
                   appendix=[mf.para(S["sec1"], "資料１　架空の資料"), mf.para(S["body"], "資料の本文。")])
    assert [x for x in res.plan.style_suspects if x.kind == "en_in_body"] == []
    assert res.plan.region[_src(res, "資料の本文。")] == "app"


def test_english_style_without_refs_after_still_switches(tmp_path, journal, meta):
    """後ろに引用文献のしるしがなければ、今までどおり英文の部分に切り替える（推定しない）。"""
    path = tmp_path / "n.docx"
    b = mf.Builder()
    b.bullet = None
    body = mf.front_ja(b, "架空の題目", "―検証用の小さな論文―", [("架空大学", "試験　六郎")])
    body += [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "試験（2024）による。前半の本文である。"),
             mf.para(S["abs"], "A stray English paragraph."), mf.para(S["body"], "後半の本文。")]
    b.save(path, body)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out_n", ai_mode="none"))
    assert [x for x in res.plan.style_suspects if x.kind == "en_in_body"] == []
    assert res.plan.region[_src(res, "A stray English paragraph.")] == "front_en"
