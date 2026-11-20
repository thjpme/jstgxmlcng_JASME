"""外部レビュー（docs/REVIEW_CODEX_2026-11.md）の R8・R11 の回帰テスト。

- R8: 引用文献の Word のリンク先は、表示文字の大文字・小文字が違っても、スキームとホストだけを大文字・小文字を区別せずに比べ、
  パス・クエリ・フラグメントは完全一致で比べる（リンク先が /study のまま残る）。
- R11: 変換の後にキーワードの全角・半角だけを直したら、変わった入力として断る（入力のまま XML に出る欄は strip だけで比べる）。
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


# ----------------------------------------------------------------------------- R8: 引用文献のリンク先
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


def _hrefs(res):
    root = etree.parse(str(res.xml_path))
    return [(e.tag, e.get(XLINK), "".join(e.itertext())) for e in root.iter("uri", "ext-link", "pub-id")]


def test_ref_link_keeps_word_target_when_only_path_case_differs(meta, journal, tmp_path):
    """表示文字 https://example.org/Study、リンク先 https://example.org/study。リンク先（/study）を残す（R8 の再現）。"""
    path = _ref_link_article(tmp_path, "r8", "https://example.org/Study", "https://example.org/study")
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "r8"))
    assert ("uri", "https://example.org/study", "https://example.org/Study") in _hrefs(res)
    assert res.fidelity.ok and res.dtd_valid                                       # 文字は 1 文字も変えない


def test_ref_link_host_case_only_difference_is_still_same(meta, journal, tmp_path):
    """ホストの大文字・小文字だけの違いは、今までどおり同じリンクとみなす（href は表示文字から作る）。"""
    path = _ref_link_article(tmp_path, "r8host", "https://Example.org/x", "https://example.org/x")
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "r8host"))
    assert ("uri", "https://Example.org/x", "https://Example.org/x") in _hrefs(res)


def test_same_as_text_compares_scheme_and_host_only_case_insensitively():
    cases = [
        ("https://example.org/Study", "https://example.org/Study", True),
        ("https://example.org/Study", "https://example.org/study", False),     # パスは完全一致
        ("https://Example.org/x", "https://example.org/x", True),              # ホストは区別しない
        ("HTTPS://example.org/x", "https://example.org/x", True),              # スキームは区別しない
        ("https://example.org/x/", "https://example.org/x", True),             # 末尾の / は今までどおり除く
        ("https://example.org/a?Q=1", "https://example.org/a?q=1", False),    # クエリは完全一致
        ("https://example.org/a#Top", "https://example.org/a#top", False),    # フラグメントは完全一致
        ("https://user:Pw@Example.org/x", "https://user:pw@example.org/x", False),   # 利用者名は完全一致（ホストだけ区別しない）
        ("https://doi.org/10.1000/ABC", "doi.org/10.1000/abc", False),        # スキームのない doi.org は機械的にリンクしないので、Word のリンク先を残す
        ("https://doi.org/10.1000/ABC", "doi:10.1000/abc", True),             # DOI が同じなら同じ（大文字・小文字は区別しない）
    ]
    for href, text, want in cases:
        assert _same_as_text(href, text) is want, (href, text)


# ----------------------------------------------------------------------------- R11: 入力の写しとの比べ
def _filled(tmp_path, **extra):
    """app の test_app.filled と同じ必須項目の状態（架空の入力）。"""
    st = AppState(tmp_path / "work")
    kw = {"pub_date": "2026-03-31", "received": "2025-06-01", "accepted": "2025-11-20"}
    kw.update(extra)
    st.set_inputs(docx=str(FULL), volume="31", issue="1", fpage="1", lpage="12", peer_review="査読あり",
                  manuscript_type=type_choices()[0], ai_mode="none", **kw)
    return st


def _kwds(res):
    return [e.text for e in etree.parse(str(res.xml_path)).iter("kwd")]


def test_keyword_nfkc_only_change_is_reported(tmp_path):
    """キーワードの全角を半角に直しただけでも、変わった入力として断る（直す前の XML を渡さない。R11 の再現）。"""
    st = _filled(tmp_path, keywords_ja="研究Ａ", keywords_en="ＡＢＣ")
    st.convert()
    assert _kwds(st.res) == ["研究Ａ", "ＡＢＣ"]                                  # 入力のまま XML に出る
    st.set_inputs(keywords_ja="研究A")
    assert st.changed_inputs() == ["キーワード（日本語）"]
    st.set_inputs(keywords_ja="研究Ａ", keywords_en="ABC")
    assert st.changed_inputs() == ["キーワード（英語）"]


def test_nfkc_normalized_fields_are_not_reported(tmp_path):
    """from_dict が NFKC にする欄（巻・最初のページ）は、全角・半角だけの違いでは変わったとしない（今までどおり）。"""
    st = _filled(tmp_path)
    st.convert()
    st.set_inputs(volume="３１", fpage=" １ ")
    assert st.changed_inputs() == []
