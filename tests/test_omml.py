"""OMML → MathML 変換。"""
from lxml import etree

from jasme_jats.omml import MML_NS, math_plain, omml_to_mathml
from jasme_jats.tracking import IMPLICIT

M = "http://schemas.openxmlformats.org/officeDocument/2006/math"


def om(inner, para=False):
    xml = f'<m:oMath xmlns:m="{M}">{inner}</m:oMath>'
    if para:
        xml = f'<m:oMathPara xmlns:m="{M}">{xml}</m:oMathPara>'
    return etree.fromstring(xml)


def r(t):
    return f"<m:r><m:t>{t}</m:t></m:r>"


def tags(el):
    return [etree.QName(x).localname for x in el.iter() if isinstance(x.tag, str)]


def test_fraction_and_tokens():
    mml, w = omml_to_mathml(om(r("S=") + f"<m:f><m:num>{r('1')}</m:num><m:den>{r('2')}</m:den></m:f>" + r("ah")))
    assert not w
    assert "mfrac" in tags(mml)
    assert math_plain(mml) == "S=12ah"
    mis = [x.text for x in mml.iter(f"{{{MML_NS}}}mi")]
    assert mis == ["S", "a", "h"]


def test_root_keeps_docx_order():
    # m:rad は 指数 → 底 の順、MathML の mroot は 底 → 指数 の順。検証用の文字列は docx の順に戻る
    mml, _ = omml_to_mathml(om(f"<m:rad><m:deg>{r('3')}</m:deg><m:e>{r('x')}</m:e></m:rad>"))
    root = next(mml.iter(f"{{{MML_NS}}}mroot"))
    assert [c.text for c in root] == ["x", "3"]
    assert math_plain(mml) == "3x"


def test_implicit_symbols_are_marked():
    mml, _ = omml_to_mathml(om(f"<m:d><m:e>{r('a+b')}</m:e></m:d>"
                               f'<m:nary><m:naryPr><m:chr m:val="∑"/></m:naryPr><m:sub>{r("k")}</m:sub><m:sup/><m:e>{r("k")}</m:e></m:nary>'))
    implicit = [x.text for x in mml.iter() if x.get(IMPLICIT)]
    assert implicit == ["(", ")", "∑"]
    assert math_plain(mml) == "a+bkk"


def test_display_and_normal_text():
    mml, _ = omml_to_mathml(om('<m:r><m:rPr><m:nor/></m:rPr><m:t>面積 S</m:t></m:r>', para=True), display=True)
    assert mml.get("display") == "block"
    assert next(mml.iter(f"{{{MML_NS}}}mtext")).text == "面積 S"


def test_unknown_element_keeps_text():
    mml, w = omml_to_mathml(om(f"<m:foo><m:e>{r('z')}</m:e></m:foo>"))
    assert math_plain(mml) == "z"
    assert w
