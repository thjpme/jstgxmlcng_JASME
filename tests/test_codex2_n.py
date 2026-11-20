"""外部レビュー（Codex）の 2 回目の点検で見つかった、引用文献の Word のリンクの判定（`linker._same_as_text`）の穴の回帰テスト（0.39.0 に向けた修正）。

Word のリンクを捨てて表示文字から機械的にリンクを作り直してよいのは、機械的に作るリンクが 1 つだけ Word のリンクに重なり、
(A) 同じ範囲の内側に収まって同じ先を指すか、(B) 後ろへ伸びるが Word のリンクの文字そのものが href と同じ先（URL・DOI の途中までの文字に
そのままリンクが付いただけ）のときだけ。範囲を段落全体の文字で実際に求めて比べる（表示文字の中の別の URL、機械的なリンクが 2 つ以上、
DOI の末尾の「/」の取り違えは偽で、Word のリンク先が残る）。(B) は、以前の決定（点検 review20 の 2 回目、0.36.0。リンクのない文字だけの
URL でも urls() は後ろの ASCII まで伸ばすので、Word のリンクがあるときだけ短くしない）による。内容はすべて架空。
"""
import re

import pytest
from lxml import etree

import make_fixtures as mf
from jasme_jats.linker import _same_as_text, _url_key
from jasme_jats.pipeline import Options, convert

S = mf.S
XLINK = "{http://www.w3.org/1999/xlink}href"
DOI_HREF = re.compile(r"https?://(?:dx\.)?doi\.org/(10\.\d{4,9}/\S+)$", re.I)
EDGE = " 　.,;:!?。、，．)]）」』>([（「『［〔〕"


def _article(tmp_path, name, shown, href, suffix=""):
    def refs(b):
        rid = b.add_hyperlink(href)
        return [mf.para(S["ref"], "架空太郎（2024）．架空の資料．",
                        f'<w:hyperlink r:id="{rid}">{mf.run(shown, u=True)}</w:hyperlink>', *([mf.run(suffix)] if suffix else []))]

    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "架空の本文である。")]
    path = tmp_path / f"{name}.docx"
    mf.make_article(path, "リンクの検証用文書", parts, refs=refs)
    return path


def _links(res):
    root = etree.parse(str(res.xml_path))
    return [(e.tag, e.get(XLINK), "".join(e.itertext())) for e in root.iter("uri", "ext-link", "pub-id")]


def _run(meta, journal, tmp_path, name, shown, href, suffix=""):
    res = convert(_article(tmp_path, name, shown, href, suffix), meta, journal, Options(out_dir=tmp_path / name))
    assert res.fidelity.ok and res.dtd_valid
    return _links(res)


def _target_key(h):
    h = h.strip()
    m = DOI_HREF.match(h)
    return ("doi", m.group(1).lower()) if m else _url_key(h.rstrip("/"))


def _word_text_key(shown):
    """Word のリンクの文字そのものから作る先（「doi:」付き・裸の DOI は DOI の部分から）。"""
    t = shown.strip()
    if "10." in t and not re.match(r"https?://", t, re.I):
        return ("doi", t[t.index("10."):].strip().lower())
    return _target_key(t)


# ----------------------------------------------------------------------------- 点検の再現（変換の経路）
@pytest.mark.parametrize("shown,href,suffix", [
    ("https://example.com/a", "https://example.com/other", "b/c"),                      # 後ろに ASCII が続き、href が文字と違う先 → (B) にしない
    ("10.1000/abc", "https://doi.org/10.1000/xyz", "d"),
    ("https://example.com/?doi=10.1000/abc", "https://doi.org/10.1000/abc", ""),       # 2: 表示文字の URL が優先される
    ("https://example.com/a 10.1000/abc", "https://doi.org/10.1000/abc", ""),          # 3: 表示文字に機械的なリンクが 2 つ
    ("https://doi.org/10.1000/ABC/", "https://doi.org/10.1000/abc", ""),               # 4: 末尾の「/」は別の DOI
])
def test_word_link_target_is_kept_when_text_cannot_replace_it(meta, journal, tmp_path, shown, href, suffix):
    links = _run(meta, journal, tmp_path, "keep", shown, href, suffix)
    assert ("uri", href, shown) in links, links


@pytest.mark.parametrize("shown,href,suffix,want", [
    ("https://doi.org/10.1000/abc", "https://doi.org/10.1000/abc", ",2020.", ("pub-id", "https://doi.org/10.1000/abc,2020")),
    ("https://doi.org/10.1000/abc", "https://doi.org/10.1000/abc", "(2020)", ("pub-id", "https://doi.org/10.1000/abc(2020)")),
    ("10.1000/abc", "https://doi.org/10.1000/abc", "d", ("pub-id", "https://doi.org/10.1000/abcd")),
    ("doi:10.1000/abc", "https://doi.org/10.1000/abc", "x", ("pub-id", "https://doi.org/10.1000/abcx")),
    ("https://example.com/a", "https://example.com/a", "b/c", ("uri", "https://example.com/ab/c")),
])
def test_word_link_on_part_of_url_is_extended_like_0_37_0(meta, journal, tmp_path, shown, href, suffix, want):
    """Word のリンクの文字が URL・DOI の途中までで、リンク先がその文字と同じ先のとき(B)は、0.37.0 と同じく後ろまで伸びた
    機械的なリンクにする（以前の決定。点検 review20 の 2 回目。tests/test_midlow_b.py の Foo_(bar) と同じ形）。"""
    links = _run(meta, journal, tmp_path, "ext", shown, href, suffix)
    assert [(t, h) for t, h, _ in links] == [want], links


# ----------------------------------------------------------------------------- 今までどおり表示文字から作るもの
@pytest.mark.parametrize("shown,href,suffix,want", [
    ("https://doi.org/10.1000/abc", "https://doi.org/10.1000/abc", "", ("pub-id", "https://doi.org/10.1000/abc")),
    ("https://doi.org/10.1000/ABC", "https://doi.org/10.1000/abc", "", ("pub-id", "https://doi.org/10.1000/ABC")),
    ("https://dx.doi.org/10.1000/abc", "https://doi.org/10.1000/abc", "", ("pub-id", "https://dx.doi.org/10.1000/abc")),
    ("https://doi.org/10.1000/abc", "https://doi.org/10.1000/abc", "．", ("pub-id", "https://doi.org/10.1000/abc")),
    ("https://doi.org/10.1000/abc", "https://doi.org/10.1000/abc", "。", ("pub-id", "https://doi.org/10.1000/abc")),
    ("10.1000/abc", "https://doi.org/10.1000/ABC", "。", ("pub-id", "https://doi.org/10.1000/abc")),
    ("https://example.com/a", "https://example.com/a", "", ("uri", "https://example.com/a")),
    ("https://EXAMPLE.com/a", "https://example.com/a", "", ("uri", "https://EXAMPLE.com/a")),
    ("https://example.com/a", "https://example.com/a", "。", ("uri", "https://example.com/a")),
])
def test_same_target_is_still_built_from_the_text(meta, journal, tmp_path, shown, href, suffix, want):
    links = _run(meta, journal, tmp_path, "same", shown, href, suffix)
    assert [(t, h) for t, h, _ in links] == [want], links
    assert not any(h == href and (t, h) != want for t, h, _ in links)


# ----------------------------------------------------------------------------- 判定の基準（まとめて）
SHOWN = [
    "https://doi.org/10.1000/abc", "https://doi.org/10.1000/ABC/", "https://doi.org/10.1000/abc。", "https://doi.org/10.1000/abc)",
    "(https://doi.org/10.1000/abc)", "https://dx.doi.org/10.1000/abc", "doi.org/10.1000/abc", "doi:10.1000/abc", "DOI: 10.1000/abc",
    "10.1000/abc", "10.1000/abc/", "10.1000/abc?x=1", "10.1000/abc#f",
    "https://example.com/a", "http://example.com/a", "www.example.com/a", "example.com/a", "https://example.com/a/",
    "https://example.com/a.", "https://example.com/a、", "https://example.com/a)", "https://example.com/a?q=1", "https://example.com/a#f",
    "https://EXAMPLE.com/a", "https://example.com/A",
    "https://example.com/?doi=10.1000/abc", "https://example.com/a 10.1000/abc", "https://example.com/a https://example.com/b",
    "https://example.com/a https://example.com/a", "架空太郎（2024）．架空の資料．https://example.com/a",
    "mailto:a@example.com",
]
SUFFIX = ["", ",2020.", "(2020)", "d", "x", "b/c", "．", "。", "、", ")", "/", "?q=1", "#f", "（全角）", "参照", " 2020"]
HREF = ["https://doi.org/10.1000/abc", "https://example.com/a", "https://example.com/a/", "http://www.example.com/a",
        "https://example.com/?doi=10.1000/abc", "mailto:a@example.com"]


def _cases():
    # 全部の組は多すぎるので、表示文字ごとに、その表示文字に関係のある href と全部の後ろの文字を組にする
    for shown in SHOWN:
        for href in HREF:
            for suffix in SUFFIX:
                yield shown, suffix, href


def _unit_ok(shown, suffix, href):
    """_same_as_text を、リンクの文字 shown と後ろの文字 suffix を含む段落の文字で直接呼ぶ。"""
    prefix = "架空太郎（2024）．架空の資料．"
    plain = prefix + shown + suffix
    return _same_as_text(href, shown, plain=plain, span=(len(prefix), len(prefix) + len(shown)))


def test_same_as_text_true_means_same_range_and_same_target():
    """真になった組は、機械的に作るリンクが Word のリンクと同じ範囲・同じ先になる（偽は常に安全なので確かめない）。"""
    from jasme_jats.linker import _machine_links
    n_true = 0
    for shown, suffix, href in _cases():
        if not _unit_ok(shown, suffix, href):
            continue
        n_true += 1
        prefix = "架空太郎（2024）．架空の資料．"
        plain = prefix + shown + suffix
        ws, we = len(prefix), len(prefix) + len(shown)
        hits, taken = [], []
        for c in _machine_links(plain, "ref", "pub-id", [(ws, we)]):
            if any(c.s < y and x < c.e for x, y in taken):
                continue                                    # 重なる候補は付かない（apply_span）
            taken.append((c.s, c.e))
            if c.e > ws and c.s < we:
                hits.append(c)
        assert len(hits) == 1 and hits[0].outer >= ws, (shown, suffix, href)
        c = hits[0]
        assert all(ch in EDGE for ch in plain[ws:c.outer]), (shown, suffix, href)
        if c.e <= we:                                       # (A) 同じ範囲の内側・同じ先
            assert all(ch in EDGE for ch in plain[c.e:we]), (shown, suffix, href)
            assert _target_key(c.spec.attrs["href"]) == _target_key(href), (shown, suffix, href)
        else:                                               # (B) 後ろへ伸びる: Word のリンクの文字そのものが href と同じ先
            assert _word_text_key(shown) == _target_key(href), (shown, suffix, href)
    assert n_true > 20


@pytest.mark.parametrize("shown", SHOWN)
def test_dropped_word_link_is_rebuilt_over_the_same_text_with_the_same_target(meta, journal, tmp_path_factory, shown):
    """変換の経路: Word のリンクが捨てられた（リンク先 href のリンクが XML にない）なら、リンクの先は href と同じで、
    リンクの文字は Word のリンクの文字と同じ（DOI の pub-id は、DOI の部分だけがリンクの文字になる）。"""
    for href, suffix in [(h, s) for h in HREF for s in SUFFIX if (len(shown) + len(h) + len(s)) % 5 == 0 or s in ("", ",2020.", "d", "。")]:
        tmp = tmp_path_factory.mktemp("c")
        links = _run(meta, journal, tmp, "c", shown, href, suffix)
        if any(h == href and "".join(t.split()) == "".join(shown.split()) for _, h, t in links if h == href):
            continue                                        # Word のリンク先がそのまま残った（安全）
        core = shown.strip(EDGE)
        hit = [(t, h, x) for t, h, x in links if _target_key(h) == _target_key(href)]
        if not hit:                                         # (B) 後ろへ伸びた: Word のリンクの文字そのものが href と同じ先
            assert suffix and _word_text_key(shown) == _target_key(href) and len(links) == 1, (shown, suffix, href, links)
            continue
        for t, h, x in hit:
            if t == "pub-id":
                assert core.endswith(x) or shown.strip().endswith(x) or x in shown, (shown, suffix, href, links)
            else:
                assert x.strip(EDGE) == core or (suffix and x.startswith(shown.strip())), (shown, suffix, href, links)   # (B) は後ろまで伸びる
        assert all(x in shown + suffix for _, _, x in links), links      # リンクの文字が Word のリンクの外へ広がらない
