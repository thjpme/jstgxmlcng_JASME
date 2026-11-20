"""外部レビュー（Codex）の 2 回目の指摘 S7・S10 の回帰テスト（0.39.0 に向けた修正）。

- S7: 引用文献の Word のリンク先（DOI）が、表示文字の別の DOI に置き換わらない。`_same_as_text` の DOI の分岐は、
  表示文字から機械的に作るリンクの DOI と href の DOI が完全に一致するときだけ同じとみなす（大文字・小文字と末尾の「/」は除く）。
- S10: 責任著者の欄は、前回の変換との比べでも `config._corresp` で解析した結果で比べる（U+FE50 などの区切りの違いを拾う）。
内容はすべて架空。
"""
from lxml import etree

import make_fixtures as mf
from conftest import FULL
from jasme_jats.app import AppState, type_choices
from jasme_jats.linker import _same_as_text
from jasme_jats.pipeline import Options, convert

S = mf.S
XLINK = "{http://www.w3.org/1999/xlink}href"


# ----------------------------------------------------------------------------- S7: 引用文献の DOI のリンク先
def _ref_link_article(tmp_path, name, shown, target):
    """引用文献の 1 件の中に、表示文字 shown・リンク先 target の Word のハイパーリンクがある架空の論文。"""
    def refs(b):
        rid = b.add_hyperlink(target)
        return [mf.para(S["ref"], "架空太郎（2024）．架空の資料．", f'<w:hyperlink r:id="{rid}">{mf.run(shown, u=True)}</w:hyperlink>')]

    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "架空の本文である。")]
    path = tmp_path / f"{name}.docx"
    mf.make_article(path, "リンクの検証用文書", parts, refs=refs)
    return path


def _links(res):
    root = etree.parse(str(res.xml_path))
    return [(e.tag, e.get(XLINK), "".join(e.itertext())) for e in root.iter("uri", "ext-link", "pub-id")]


def _convert_ref(meta, journal, tmp_path, name, shown, target):
    path = _ref_link_article(tmp_path, name, shown, target)
    return convert(path, meta, journal, Options(out_dir=tmp_path / name))


def test_doi_with_trailing_slash_in_word_link_is_kept(meta, journal, tmp_path):
    """表示 https://doi.org/10.1000/ABCD、リンク先 https://doi.org/10.1000/ABC/ → Word のリンク先を残す（S7 の再現）。
    0.38.0 は部分一致で「同じ」とみなし、表示文字の DOI（ABCD）にリンクしていた。"""
    res = _convert_ref(meta, journal, tmp_path, "s7slash", "https://doi.org/10.1000/ABCD", "https://doi.org/10.1000/ABC/")
    assert ("uri", "https://doi.org/10.1000/ABC/", "https://doi.org/10.1000/ABCD") in _links(res)
    assert not any(t == "pub-id" for t, _, _ in _links(res))                       # 表示文字からは作らない
    assert res.fidelity.ok and res.dtd_valid


def test_doi_partial_match_without_slash_is_kept(meta, journal, tmp_path):
    """表示 https://doi.org/10.1000/ABCD、リンク先 https://doi.org/10.1000/ABC（末尾の / なし）も、同じく残す（部分一致の穴）。"""
    res = _convert_ref(meta, journal, tmp_path, "s7noslash", "https://doi.org/10.1000/ABCD", "https://doi.org/10.1000/ABC")
    assert ("uri", "https://doi.org/10.1000/ABC", "https://doi.org/10.1000/ABCD") in _links(res)
    assert res.fidelity.ok and res.dtd_valid


def test_doi_really_same_still_uses_the_display_text(meta, journal, tmp_path):
    """DOI が本当に同じ（大文字・小文字だけ違う・dx.doi.org と doi.org・末尾の / だけ違う）なら、今までどおり表示文字から作るリンク。"""
    cases = [
        ("https://doi.org/10.1000/ABC", "https://doi.org/10.1000/abc", "https://doi.org/10.1000/ABC"),
        ("https://dx.doi.org/10.1000/abc", "https://doi.org/10.1000/abc", "https://dx.doi.org/10.1000/abc"),
        ("https://doi.org/10.1000/abc/", "https://doi.org/10.1000/abc", "https://doi.org/10.1000/abc/"),
    ]
    for i, (shown, target, want) in enumerate(cases):
        res = _convert_ref(meta, journal, tmp_path, f"s7same{i}", shown, target)
        assert any(t == "pub-id" and h == want for t, h, _ in _links(res)), (shown, target)     # 表示文字から作ったリンク
        assert res.fidelity.ok and res.dtd_valid


def test_schemeless_doi_org_text_keeps_the_word_link(meta, journal, tmp_path):
    """表示「doi.org/10.1000/abc」（スキームなし）は、機械的には URL にも DOI にもリンクしない。Word のリンク先を捨てると
    リンクが 1 つも付かなくなるので、同じとみなさず、Word のリンク先を残す。"""
    for i, shown in enumerate(("doi.org/10.1000/abc", "dx.doi.org/10.1000/abc")):
        res = _convert_ref(meta, journal, tmp_path, f"s7bare{i}", shown, "https://doi.org/10.1000/ABC")
        assert ("uri", "https://doi.org/10.1000/ABC", shown) in _links(res)
        assert res.fidelity.ok and not res.needs_action


def test_same_as_text_doi_branch_needs_the_whole_doi():
    cases = [
        ("https://doi.org/10.1000/ABC/", "https://doi.org/10.1000/ABCD", False),     # S7 の再現（末尾の / あり）
        ("https://doi.org/10.1000/ABC", "https://doi.org/10.1000/ABCD", False),      # 末尾の / なし（部分一致）
        ("https://doi.org/10.1000/ABC", "10.1000/ABCD", False),
        ("https://doi.org/10.1000/ABC", "10.1000/ABC", True),                         # 裸の DOI
        ("https://doi.org/10.1000/ABC", "doi:10.1000/abc", True),                     # doi: の形
        ("https://doi.org/10.1000/ABC", "https://doi.org/10.1000/abc/", True),        # 大文字・小文字・末尾の / は除く
        ("https://dx.doi.org/10.1000/abc", "https://doi.org/10.1000/abc", True),      # dx.doi.org と doi.org
        ("https://doi.org/10.1000/abc/", "https://doi.org/10.1000/abc", True),        # 末尾の / だけ
        ("https://doi.org/10.1000/ABC", "https://doi.org/10.1000/ABC。", True),       # 後ろの句点は範囲に入れない（_trim）
        ("https://doi.org/10.1000/ABC", "(https://doi.org/10.1000/ABC)", True),       # 閉じかっこも範囲に入れない
        ("https://doi.org/10.1000/ABC", "10.1000/ABC と 10.1000/ABD", False),        # DOI が 2 つ（1 つでも違えば同じでない）
        ("https://doi.org/10.1000/ABC", "10.1000/ABC と 10.1000/ABC", True),          # 同じ DOI が 2 つ
        ("https://doi.org/10.1000/ABC", "10.1000/ABC?x=1", False),                    # クエリ付きは別の DOI の文字
        ("https://doi.org/10.1000/ABC", "Click here", False),                         # DOI のない表示文字
    ]
    for href, text, want in cases:
        assert _same_as_text(href, text) is want, (href, text)


# ----------------------------------------------------------------------------- S10: 責任著者の欄の比べ
def _filled(tmp_path, **extra):
    st = AppState(tmp_path / "work")
    kw = {"pub_date": "2026-03-31", "received": "2025-06-01", "accepted": "2025-11-20"}
    kw.update(extra)
    st.set_inputs(docx=str(FULL), volume="31", issue="1", fpage="1", lpage="12", peer_review="査読あり",
                  manuscript_type=type_choices()[0], ai_mode="none", **kw)
    return st


def test_corresp_separator_nfkc_only_change_is_reported(tmp_path):
    """「1，2」で変換したあと、区切りを U+FE50（﹐）に変えたら変わった入力として断る（S10 の再現。0.38.0 は比べず通していた）。"""
    st = _filled(tmp_path, corresp="1，2")
    st.convert()
    st.set_inputs(corresp="1﹐2")
    assert st.changed_inputs() == ["責任著者"]


def test_corresp_same_numbers_are_not_reported(tmp_path):
    """区切り・全角半角・空白だけが違い、解析すると同じ整数の組になるものは、変わったとしない。"""
    st = _filled(tmp_path, corresp="1，2")
    st.convert()
    for v in ("1,2", "１，２", " 1 , 2 ", "1、2", "1,2 "):
        st.set_inputs(corresp=v)
        assert st.changed_inputs() == [], v


def test_corresp_empty_and_none_are_the_same(tmp_path):
    st = _filled(tmp_path)
    st.convert()
    st.set_inputs(corresp=None)
    assert st.changed_inputs() == []
    st.set_inputs(corresp="  ")
    assert st.changed_inputs() == []
    st.set_inputs(corresp="1")
    assert st.changed_inputs() == ["責任著者"]
