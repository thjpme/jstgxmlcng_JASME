"""中低の問題 B: リンクと PDF 照合。

- C089: URL の直後に空白なしで続く「(…参照)」「参照」をリンクの範囲に入れない（文字は変えない）。それでも href に非 ASCII が残る
  ときは推定で切らず、要確認 link_iri で知らせる。DOI は非 ASCII で止める
- C090: http・https・mailto・ftp 以外のリンク先（file:・javascript: など）を要確認 link_iri で知らせる（値は書き換えない）
- C111: route pdf で、英文の文の間の全角の「，」「．」（docx のすぐ後ろが空白でない半角の英数字、PDF ではすぐ後ろに空白がある）を
  半角に直さない（全角のまま。空白は足さない。一続きの規則の始まりにしない。それを根拠にした空白の削除も直さない）
内容はすべて架空。
"""
import pytest
from lxml import etree

import make_fixtures as mf
from jasme_jats import report
from jasme_jats.linker import RE_DOI_BARE, RE_DOI_PREFIXED, RE_URL, Linker, _trim, href_problems
from jasme_jats.model import Atom, Para
from jasme_jats.pdfdocx import ADJACENT_REASON, NOSPACE_REASON, Fix, hold
from jasme_jats.pipeline import Options, convert
from jasme_jats.report import TO_CHECK, actions
from jasme_jats.structure import ArticlePlan

S = mf.S
XLINK = "{http://www.w3.org/1999/xlink}href"


# ----------------------------------------------------------------------------- C089: URL の範囲
@pytest.mark.parametrize("text, url", [
    ("https://example.org/a/b.pdf(2024.1.9参照)", "https://example.org/a/b.pdf"),          # 実際の原稿の形（架空の URL）
    ("https://example.org/a/b.pdf(2024年1月9日閲覧)。", "https://example.org/a/b.pdf"),
    ("https://example.org/a/b.html参照", "https://example.org/a/b.html"),
    ("https://example.org/a/b.html（2024年1月9日参照）", "https://example.org/a/b.html"),    # 全角のかっこは今までどおり止まる
    ("https://example.org/a/b.html 参照", "https://example.org/a/b.html"),                  # 空白が続く形も今までどおり
    ("https://example.org/a〈架空〉", "https://example.org/a"),                              # 和文のかっこで止める
    ("https://example.org/a：架空", "https://example.org/a"),
    ("https://example.org/a(accessed", "https://example.org/a"),                             # 閉じかっこのない「(」から後ろ
    ("https://example.org/wiki/A_(b)", "https://example.org/wiki/A_(b)"),                   # 組になるかっこは URL の一部
    ("https://ja.example.org/wiki/架空の項目", "https://ja.example.org/wiki/架空の項目"),     # IRI は推定で切らない（link_iri で知らせる）
    # 「参照」などで終わる日本語のページ名は切らない（外した後の最後の文字が「/」・非 ASCII など。点検 review20 原則 1）
    ("https://ja.example.org/wiki/参照", "https://ja.example.org/wiki/参照"),
    ("https://ja.example.org/wiki/アクセス", "https://ja.example.org/wiki/アクセス"),
    ("https://ja.example.org/wiki/文献参照", "https://ja.example.org/wiki/文献参照"),
    ("https://ja.example.org/wiki/情報取得", "https://ja.example.org/wiki/情報取得"),
    ("https://ja.example.org/wiki/A_(参照)", "https://ja.example.org/wiki/A_(参照)"),
    ("https://example.org/a/b.pdf参照した", "https://example.org/a/b.pdf"),
    ("https://example.org/a/b.pdf(2024年1月9日アクセス)", "https://example.org/a/b.pdf"),
    # 閉じていない「(」は、後ろが日付・和文・英語の閲覧の語のときだけ切る（URL の一部の「(」は切らない。原則 4）
    ("https://example.org/a/b.pdf(2024.1.9", "https://example.org/a/b.pdf"),
    ("https://example.org/search?q=(a", "https://example.org/search?q=(a"),
    # 後ろが数字なら、日付の形（2〜4 桁の数字と「年」「.」「/」「-」）のときだけ切る（点検 review20 の 2 回目）
    ("https://example.org/search?q=(1", "https://example.org/search?q=(1"),
    ("https://example.org/f(1", "https://example.org/f(1"),
    ("https://example.org/f(12x", "https://example.org/f(12x"),
    ("https://example.org/f(12", "https://example.org/f(12"),
    ("https://example.org/a/b.pdf(2024/1/9", "https://example.org/a/b.pdf"),
    ("https://example.org/a/b.pdf(24-1-9", "https://example.org/a/b.pdf"),
    ("https://example.org/a/b.pdf(2024年1月9日", "https://example.org/a/b.pdf"),
])
def test_url_range(text, url):
    m = RE_URL.search(text)
    assert _trim(m.group(0)) == url


def test_doi_stops_at_non_ascii():
    assert RE_DOI_PREFIXED.search("doi:10.0000/fict.2024.1参照").group(1) == "10.0000/fict.2024.1"
    # 大文字・小文字の仲間（U+0130・U+0131・U+017F・U+212A）も ASCII でないので止める（re.I を使わない。点検 review20 原則 2）
    for c in "\u0130\u0131\u017f\u212a":
        assert RE_DOI_PREFIXED.search(f"doi:10.0000/ab{c}参照").group(1) == "10.0000/ab"
        assert RE_DOI_BARE.search(f"10.0000/ab{c}").group(1) == "10.0000/ab"
    assert [RE_DOI_PREFIXED.search(t).group(1) for t in ("DOI 10.0000/a", "Doi：10.0000/b", "DOI\u300010.0000/c")] == \
        ["10.0000/a", "10.0000/b", "10.0000/c"]
    assert RE_DOI_BARE.search("10.0000/fict.2024.1(2024年参照)").group(1) == "10.0000/fict.2024.1(2024"
    assert _trim(RE_DOI_BARE.search("10.0000/fict.2024.1(2024年参照)").group(1)) == "10.0000/fict.2024.1"


def test_urls_change_only_the_link_range():
    """文字は変えず、リンクの範囲（LinkSpec）だけが URL の部分になる。"""
    text = "架空の資料，https://example.org/a/b.pdf(2024.1.9参照)"
    p = Para(src="d1", atoms=[Atom(kind="text", text=text)])
    Linker(ArticlePlan()).urls(p, "ref")
    assert p.plain() == text
    linked = [(a.text, a.link.attrs["href"]) for a in p.atoms if a.link is not None]
    assert linked == [("https://example.org/a/b.pdf", "https://example.org/a/b.pdf")]


def _article(tmp_path, name, body=(), refs=(), links=()):
    """本文の段落 body・引用文献の後ろの段落 refs の小さな論文。links は Word のハイパーリンク [(リンク先, 文字)]（本文の段落に 1 つずつ）。"""
    def parts(b):
        out = [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "試験（2024）による。架空の本文である。")]
        out += [mf.para(S["body"], t) for t in body]
        for href, shown in links:
            rid = b.add_hyperlink(href)
            out.append(mf.para(S["body"], "架空の資料は", f'<w:hyperlink r:id="{rid}">{mf.run(shown, u=True)}</w:hyperlink>',
                               "にある。"))
        return out
    path = tmp_path / f"{name}.docx"
    mf.make_article(path, "リンクの検証用文書", parts, refs=lambda b: [mf.para(S["ref"], t) for t in refs])
    return path


def _convert(tmp_path, name, meta, journal, **kw):
    return convert(_article(tmp_path, name, **kw), meta, journal, Options(out_dir=tmp_path / name))


def _hrefs(res):
    root = etree.parse(str(res.xml_path))
    return [(e.tag, e.get(XLINK), "".join(e.itertext())) for e in root.iter("uri", "ext-link", "pub-id")]


def _act(res, key):
    return next((a for a in actions(res) if a.key == key), None)


def test_url_with_access_date_converts(meta, journal, tmp_path):
    ref = "架空太郎（2024）．架空の資料．https://example.org/a/b.pdf(2024.1.9参照)"
    res = _convert(tmp_path, "c089", meta, journal, refs=[ref])
    assert ("uri", "https://example.org/a/b.pdf", "https://example.org/a/b.pdf") in _hrefs(res)
    assert all(h.isascii() for _, h, _ in _hrefs(res))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid       # 文字は 1 文字も変えない
    assert _act(res, "link_iri") is None


def test_iri_is_kept_and_reported(meta, journal, tmp_path):
    """非 ASCII が残るリンク先は、推定で切らずに要確認 link_iri で知らせる（XML の href は docx の文字のまま）。"""
    ref = "架空太郎（2024）．架空の項目．https://ja.example.org/wiki/架空の項目"
    res = _convert(tmp_path, "iri", meta, journal, refs=[ref])
    assert ("uri", "https://ja.example.org/wiki/架空の項目", "https://ja.example.org/wiki/架空の項目") in _hrefs(res)
    act = _act(res, "link_iri")
    assert act.level == TO_CHECK and "1 件" in act.box_title
    assert "https://ja.example.org/wiki/架空の項目" in act.top and "日本語などの文字" in act.top
    assert "リンク先が XML のリンクになります" in act.top                    # 文字列の継ぎ目の空白（点検 review20 の 2 回目）
    assert act.cli.startswith("要確認: ") and "file:" not in act.box_detail
    assert "xlink:href" not in act.top + act.checklist + act.cli and "［挿入］の［リンク］" in act.top   # 直し方は Word だけ（利用者向け 3）
    assert not res.needs_action and res.fidelity.ok


def test_word_hyperlink_on_url_limits_the_link_in_references(meta, journal, tmp_path):
    """引用文献の中で URL の文字だけに Word のハイパーリンク（リンク先は URL の文字と同じ）を付ければ、すぐ後ろの文字はリンク先に
    入らない（link_iri の直し方。文字は変わらない。点検 review20 利用者向け 3）。"""
    url = "https://example.org/a/b.html"
    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "試験（2024）による。架空の本文である。")]

    def refs(b):
        rid = b.add_hyperlink(url)
        return [mf.para(S["ref"], "試験太郎（2024）．架空の資料．", f'<w:hyperlink r:id="{rid}">{mf.run(url, u=True)}</w:hyperlink>',
                        mf.run("架空の注記"))]
    path = tmp_path / "wl.docx"
    mf.make_article(path, "リンクの検証用文書", parts, refs=refs)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "wl"))
    assert ("uri", url, url) in _hrefs(res)
    assert _act(res, "link_iri") is None and res.fidelity.ok and res.dtd_valid


def test_word_hyperlink_on_part_of_url_does_not_shorten_the_link(meta, journal, tmp_path):
    """URL の途中までにだけ付いた Word のハイパーリンク（自動書式で「…/wiki/Foo_」だけがリンク）では、すぐ後ろが ASCII の文字なので
    縮めず、URL 全体をリンクにする（0.35.0 までと同じ。点検 review20 の 2 回目）。"""
    part = "https://example.org/wiki/Foo_"
    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "試験（2024）による。架空の本文である。")]

    def refs(b):
        rid = b.add_hyperlink(part)
        return [mf.para(S["ref"], "試験太郎（2024）．架空の資料．", f'<w:hyperlink r:id="{rid}">{mf.run(part, u=True)}</w:hyperlink>',
                        mf.run("(bar)"))]
    path = tmp_path / "wp.docx"
    mf.make_article(path, "リンクの検証用文書", parts, refs=refs)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "wp"))
    assert ("uri", part + "(bar)", part + "(bar)") in _hrefs(res)
    assert res.fidelity.ok and res.dtd_valid


# ----------------------------------------------------------------------------- C090: リンク先のスキーム
@pytest.mark.parametrize("href", ["file:///C:/Users/x/draft.docx", "javascript:void(0)", "draft.docx"])
def test_unusual_scheme_is_reported_not_rewritten(href, meta, journal, tmp_path):
    res = _convert(tmp_path, "c090", meta, journal, links=[(href, "架空の資料")])
    assert ("uri", href, "架空の資料") in _hrefs(res)          # 値は書き換えない・リンクも外さない
    act = _act(res, "link_iri")
    assert act.level == TO_CHECK and "http・https・mailto・ftp 以外" in act.top and "［リンクの編集］" in act.box_detail
    assert report.step("docx") in act.box_detail
    assert not res.needs_action and res.fidelity.ok and res.dtd_valid


def test_usual_links_are_not_reported(meta, journal, tmp_path):
    res = _convert(tmp_path, "ok", meta, journal, links=[("https://example.org/x", "架空の資料"), ("mailto:a@example.org", "連絡先")],
                   body=["架空の資料は https://example.org/y にある。"], refs=["架空太郎（2024）．架空の論文．doi:10.0000/fict.1"])
    assert _act(res, "link_iri") is None
    assert href_problems(res.plan) == []


def test_href_problems_counts_one_link_once():
    from jasme_jats.model import LinkSpec
    plan = ArticlePlan()
    spec = LinkSpec(kind="uri", attrs={"href": "file:///架空.docx"}, origin="word")
    p = Para(src="d1", atoms=[Atom(kind="text", text="架空", link=spec), Atom(kind="text", text="の資料", fmt=frozenset({"b"}), link=spec)])
    from jasme_jats.article import PNode
    plan.body = [PNode(p)]
    probs = href_problems(plan)
    assert [(x.src, x.text, x.kinds) for x in probs] == [("d1", "架空の資料", ("scheme", "iri"))]


# ----------------------------------------------------------------------------- C111: 英文の文の間の全角の「，」「．」
def test_hold_keeps_fullwidth_stop_before_word():
    """hold の (b2): 直さない。一続きの規則の始まりにしない（間 1 文字の「１」の直しは直す）。それを根拠にした空白の削除は直さない
    （片方向: 空白の削除を直さなくても、ほかの全角・半角の直しは直す）。"""
    text = "at night ．They ate １ fish．"
    q = text.index("．")
    stop = Fix("d1", q, q + 1, ".", "width", "．")
    space = Fix("d1", q - 1, q, "", "space", " ")
    space.needs.append(stop)
    one = Fix("d1", text.index("１"), text.index("１") + 1, "1", "width", "１")
    end = Fix("d1", len(text) - 1, len(text), ".", "width", "．")            # 文の最後（すぐ後ろに文字がない）は直す
    fixes = [space, stop, one, end]
    hold(fixes, {"d1": text}, {"d1": {q, len(text) - 1}})
    assert stop.reason == NOSPACE_REASON
    assert space.reason and "連動して直さない" in space.reason and NOSPACE_REASON in space.reason
    assert one.reason == "" and end.reason == ""
    assert ADJACENT_REASON not in {f.reason for f in fixes}


@pytest.mark.parametrize("text, spaced, held", [
    ("ab．Cd", True, True),
    ("ab．5d", True, True),          # 半角の数字も同じ
    ("ab．Cd", False, False),        # PDF のすぐ後ろに空白がない（「pp.45」の形）: 今までどおり直す
    ("ab． Cd", True, False),        # docx のすぐ後ろが空白: 直す
    ("ab．Ｃd", True, False),        # すぐ後ろが全角の英字
    ("ab，Cd", True, True),
])
def test_hold_nospace_conditions(text, spaced, held):
    q = text.index("．") if "．" in text else text.index("，")
    f = Fix("d1", q, q + 1, "." if text[q] == "．" else ",", "width", text[q])
    hold([f], {"d1": text}, {"d1": {q} if spaced else set()})
    assert (f.reason == NOSPACE_REASON) == held


def test_hold_without_spaced_is_unchanged():
    text = "ab．Cd"
    f = Fix("d1", 2, 3, ".", "width", "．")
    hold([f], {"d1": text})
    assert f.reason == ""


def test_route2_keeps_fullwidth_stop_between_sentences(journal, meta, tmp_path, monkeypatch):
    """ルート2: PDF は「night. They」（空白あり）、docx は「night．They」（空白なし）。「．」は全角のまま（空白も足さない）。「day，and」の「，」も同じ。
    「pp．45」（PDF も空白なし）と文の最後の「．」は今までどおり半角に直す。13.2 に件数を載せる。補完の確かめは合格。"""
    from test_pdfmatch import owl_convert, para_text
    from jasme_jats.fidelity import source_texts
    body = "架空の観察の記録である。Owls hunt at night．They rest by day，and see pp．45 in the note．"
    pub = "架空の観察の記録である。Owls hunt at night. They rest by day, and see pp.45 in the note."
    res = owl_convert(tmp_path, monkeypatch, journal, meta, body, pub)
    assert res.fidelity.ok and res.fidelity.final_ok and res.supplement.ok and res.dtd_valid
    held = [(f.old, f.new) for f in res.docx_fix.skipped if f.reason == NOSPACE_REASON]
    assert held == [("．", "."), ("，", ",")]
    got = para_text(source_texts(res.docx_fix.path), "架空の観察")
    assert got == "架空の観察の記録である。Owls hunt at night．They rest by day，and see pp.45 in the note."
    text = res.report_path.read_text(encoding="utf-8").split("### 13.2")[1].split("### 13.3")[0]
    assert report.SILENT_NOSPACE + " 2" in text
