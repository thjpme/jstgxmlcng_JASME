"""J-STAGE のアップロード時チェックの再現（jstage_rules）。"""
from lxml import etree

from jasme_jats.jstage_rules import check

XML = """<article xmlns:xlink="http://www.w3.org/1999/xlink" xml:lang="ja" article-type="research-article">
<front><article-meta>
<fpage>1</fpage>
<title-group>
  <article-title xml:lang="ja">題目</article-title>
  <trans-title-group xml:lang="en"><trans-title>Title</trans-title></trans-title-group>
</title-group>
<contrib-group>
  <contrib contrib-type="author"><name-alternatives><name name-style="eastern" xml:lang="ja"><surname>山田</surname>
  <given-names>花子</given-names></name></name-alternatives><xref ref-type="aff" rid="aff1"/></contrib>
  <aff-alternatives id="aff1"><aff xml:lang="ja">大学</aff></aff-alternatives>
</contrib-group>
<history><date date-type="received"><day>1</day><month>4</month><year>2025</year></date>
<date date-type="accepted"><day>1</day><month>8</month><year>2025</year></date></history>
{abstract}
</article-meta></front>
<back><ref-list><ref id="B1" xml:lang="ja"><mixed-citation>山田花子（2020）．題目．</mixed-citation></ref></ref-list></back>
</article>"""


def ids(xml, **kw):
    return [mid for mid, _ in check(etree.fromstring(xml), **kw)]


def test_trans_abstract_with_trans_title_passes():
    assert ids(XML.replace("{abstract}", '<trans-abstract xml:lang="en"><p>Abstract.</p></trans-abstract>')) == []


def test_english_abstract_without_english_title_is_an_error():
    # 実際に J-STAGE で返ってきたエラー（和文の論文で英文要旨を abstract にした場合）
    xml = XML.replace("{abstract}", '<abstract xml:lang="en" specific-use="secondary-disallow"><p>Abstract.</p></abstract>')
    assert ids(xml) == ["EMSGM102E/103E"]


def test_trans_abstract_without_trans_title_is_an_error():
    xml = XML.replace('<trans-title-group xml:lang="en"><trans-title>Title</trans-title></trans-title-group>', "")
    xml = xml.replace("{abstract}", '<trans-abstract xml:lang="en"><p>Abstract.</p></trans-abstract>')
    assert ids(xml) == ["EMSGM104E/105E"]


def test_dates_affiliations_pages_and_images():
    xml = XML.replace("{abstract}", "")
    xml = xml.replace("<month>4</month>", "<month>9</month>")          # 受付日が受理日より後
    xml = xml.replace('rid="aff1"', 'rid="aff2"')                       # 所属がない
    xml = xml.replace("<fpage>1</fpage>", "")                           # 開始ページがない
    got = ids(xml, article_id="31_1", image_names=["31_1.01.png", "図1.png", "31_1_01.png"])
    assert got == ["EMSGM106E", "EMSGM115E", "EMSGM230E", "EMSGM248E", "EMSGM034E"]


def test_reference_language_is_inherited():
    xml = XML.replace("{abstract}", "").replace('<ref id="B1" xml:lang="ja">', '<ref id="B1">')
    assert ids(xml) == []                                               # article の xml:lang="ja" を継ぐ
    xml = xml.replace(' xml:lang="ja" article-type', ' article-type')
    assert ids(xml) == ["EMSGM247E"]
