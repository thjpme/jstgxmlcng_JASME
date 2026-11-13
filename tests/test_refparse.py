"""引用の抽出と照合（年の部分だけをリンクにする）。"""
from jasme_jats.model import Atom, Para
from jasme_jats.refparse import Mapped, extract_citations, match_citation, parse_entry, tag_reference
from jasme_jats.structure import RefNode


def make_refs(texts):
    refs = []
    for i, t in enumerate(texts, 1):
        r = RefNode(para=Para(src=f"r{i}", atoms=[Atom(kind="text", text=t)]), rid=f"B{i}")
        r.parsed = parse_entry(t)
        refs.append(r)
    return refs


REFS = make_refs([
    "野村忠夫（1995）．『理科・算数教育における協働的なアプローチの研究』．架空社．",
    "桑原秀雄・川口武史（2007）．「数学的探究の理論」．『数学教育学研究』，第13巻，pp.1-10．",
    "Claude, A. (2025). An unusual reference format example. Journal of Testing, 1, 1-2.",
    "Polya, G. (1945). How to solve it. Princeton University Press.",
    "Polya, G. (1954). Mathematics and plausible reasoning. Princeton University Press.",
    "三浦健・濵田裕介・大野孝志（2016）．「論証活動」．『数学教育学研究』，第22巻，pp.25-36．",
])
KNOWN = {n for r in REFS for n in r.parsed["names"]}


def links(text):
    mp = Mapped(text)
    out = []
    for c in extract_citations(mp.n, KNOWN):
        ref, kind, _ = match_citation(c, REFS)
        s, e = mp.orig(*c["span"])
        out.append((text[s:e], ref.rid if ref else None, kind))
    return out


def test_narrative_fullwidth_paren_links_only_year():
    assert links("Claude（2025）は次のように述べた。") == [("2025", "B3", "exact")]
    assert links("Claude (2025) said") == [("2025", "B3", "exact")]


def test_parenthetical_multiple():
    got = links("数学的探究（野村, 1995；桑原・川口, 2007）における")
    assert got == [("1995", "B1", "exact"), ("2007", "B2", "exact")]


def test_multiple_years_and_page():
    assert links("Polya（1945, 1954）は") == [("1945", "B4", "exact"), ("1954", "B5", "exact")]
    assert links("（野村, 1995, p. 12）") == [("1995", "B1", "exact")]


def test_fullwidth_digits_map_back_to_original():
    text = "野村（１９９５）によれば"
    got = links(text)
    assert got == [("１９９５", "B1", "exact")]


def test_unresolved_cases():
    assert links("Claude（2024）は")[0][1] is None            # 年が違う
    assert links("その後の論考（2001）で")[0][1] is None         # 著者が特定できない


def test_entry_types():
    assert REFS[0].parsed["publication_type"] == "book"
    assert REFS[1].parsed["publication_type"] == "journal"
    assert REFS[2].parsed["year"] == "2025"
    assert REFS[5].parsed["n_authors"] == 3


def _match_one(text, refs):
    """本文 1 文の引用を、文献 refs と照合する（最初の引用の結果）。"""
    known = {n for r in refs for n in r.parsed["names"]}
    c = extract_citations(Mapped(text).n, known)[0]
    return match_citation(c, refs)


def test_same_year_ties_ignore_lower_candidates():
    # 同じ第一著者・同じ年の文献 3 件。B1 は共著（当てはまりが低い）、B2・B3 は単著（同点で最大）。
    # 先頭と末尾だけを比べる今までの判定では B2 の exact になっていた。
    refs = make_refs([
        "Polya, G., & Szego, G. (1945). Problems and theorems. Springer.",
        "Polya, G. (1945). How to solve it. Princeton University Press.",
        "Polya, G. (1945). Mathematical discovery. Wiley.",
    ])
    ref, kind, why = _match_one("Polya（1945）は", refs)
    assert ref is None and kind == "ambiguous"
    assert "B2、B3" in why and "B1" not in why


def test_same_year_low_high_low_is_exact():
    refs = make_refs([
        "Polya, G., & Szego, G. (1945). Problems and theorems. Springer.",
        "Polya, G. (1945). How to solve it. Princeton University Press.",
        "Polya, G., & Szego, G. (1945). Mathematical discovery. Wiley.",
    ])
    ref, kind, _ = _match_one("Polya（1945）は", refs)
    assert kind == "exact" and ref.rid == "B2"


def test_same_year_two_tied_top_candidates_ambiguous():
    refs = make_refs([
        "Polya, G. (1945). How to solve it. Princeton University Press.",
        "Polya, G. (1945). Mathematical discovery. Wiley.",
    ])
    ref, kind, why = _match_one("Polya（1945）は", refs)
    assert ref is None and kind == "ambiguous"
    assert "B1、B2" in why


def test_same_year_coauthored_citation_picks_coauthored_among_three():
    """共著・共著・単著の 3 件: 共著の引用（A・B（2001））は共著の 2 件が同点で最大なので ambiguous（B1・B2 だけ）。"""
    refs = make_refs([
        "Alpha, A., & Beta, B. (2001). First work. Press.",
        "Alpha, A., & Beta, B. (2001). Second work. Press.",
        "Alpha, A. (2001). Third work. Press.",
    ])
    ref, kind, why = _match_one("Alpha and Beta（2001）は", refs)
    assert ref is None and kind == "ambiguous"
    assert "B1、B2" in why and "B3" not in why


def test_same_year_two_candidates_unchanged():
    """候補が 2 件（共著・単著）で当てはまりが違うときは今までどおり exact（単著は単著、共著は共著）。"""
    refs = make_refs([
        "Alpha, A., & Beta, B. (2001). First work. Press.",
        "Alpha, A. (2001). Second work. Press.",
    ])
    ref, kind, _ = _match_one("Alpha（2001）は", refs)
    assert kind == "exact" and ref.rid == "B2"
    ref, kind, _ = _match_one("Alpha and Beta（2001）は", refs)
    assert kind == "exact" and ref.rid == "B1"


# ---------------------------------------------------------------- 文献の <year> などのタグ位置（C017）
def tagged(text, numeric=False, parsed=None):
    """文献の段落に tag_reference を呼び、タグが付いた範囲の文字を {種類: 文字列} で返す。"""
    r = RefNode(para=Para(src="r1", atoms=[Atom(kind="text", text=text)]), rid="B1")
    r.parsed = parsed if parsed is not None else parse_entry(text, numeric)
    tag_reference(r)
    assert "".join(a.plain() for a in r.para.atoms) == text   # 文字は変えない
    return {a.link.kind: a.text for a in r.para.atoms if a.link}


def test_year_tag_after_combining_characters():
    # o + 結合アクセント（NFKC で合成されるが、1 文字ずつの正規化では合成されない）が年より前にある
    text = "Gasco\u0301n, J., & Nicola\u0301s, P. (2019). What is a tag? Journal of Tests, 1, 1-2."
    assert tagged(text) == {"year": "2019"}


def test_year_tag_after_halfwidth_katakana_voiced_mark():
    text = "\uff8c\uff9e\uff99\uff70\uff85\uff70, J. S.\uff081963\uff09\u300e\u30c6\u30b9\u30c8\u306e\u672c\u300f\uff0e"
    assert tagged(text) == {"year": "1963", "source": "\u30c6\u30b9\u30c8\u306e\u672c"}


def test_year_tag_with_manual_number_prefix():
    assert tagged("[2] Smith, J. (2020). A title. Journal of Tests, 1, 1-2.", numeric=True) == {"year": "2020"}
    assert tagged("1) \u8a66\u9a13\u516d\u90ce\uff082024\uff09\u300c\u8a66\u9a13\u306e\u8ad6\u6587\u300d\u300e\u8a66\u9a13\u8a8c\u300f\u7b2c1\u5dfb\uff0e", numeric=True) == {
        "year": "2024", "article-title": "\u8a66\u9a13\u306e\u8ad6\u6587", "source": "\u8a66\u9a13\u8a8c"}


def test_year_tag_unchanged_for_plain_references():
    assert tagged("Polya, G. (1945). How to solve it. Princeton University Press.") == {"year": "1945"}
    assert tagged("\u4e2d\u539f\u5fe0\u7537\uff081995\uff09\uff0e\u300e\u7b97\u6570\u306e\u7814\u7a76\u300f\uff0e\u8056\u6587\u793e\uff0e") == {
        "year": "1995", "source": "\u7b97\u6570\u306e\u7814\u7a76"}
    assert tagged("Smith, J. (2020a). A title. Journal of Tests, 1, 1-2.") == {"year": "2020a"}


def test_year_tag_guard_skips_when_range_is_not_a_year(monkeypatch):
    # 位置の戻しが別の理由でずれても、年でない文字を囲まず、論文名・誌名のタグも付けない
    text = "\u8a66\u9a13\u516d\u90ce\uff082024\uff09\u300c\u8a66\u9a13\u306e\u8ad6\u6587\u300d\u300e\u8a66\u9a13\u8a8c\u300f\u7b2c1\u5dfb\uff0e"
    assert set(tagged(text)) == {"year", "article-title", "source"}
    real = Mapped.orig
    monkeypatch.setattr(Mapped, "orig", lambda self, ns, ne: (lambda o: (o[0] - 1, o[1] - 1) if o else o)(real(self, ns, ne)))
    assert tagged(text) == {}
