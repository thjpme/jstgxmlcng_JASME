"""引用の抽出と照合（年の部分だけをリンクにする）。"""
from jasme_jats.model import Atom, Para
from jasme_jats.refparse import Mapped, extract_citations, match_citation, parse_entry
from jasme_jats.structure import RefNode


def make_refs(texts):
    refs = []
    for i, t in enumerate(texts, 1):
        r = RefNode(para=Para(src=f"r{i}", atoms=[Atom(kind="text", text=t)]), rid=f"B{i}")
        r.parsed = parse_entry(t)
        refs.append(r)
    return refs


REFS = make_refs([
    "中原忠男（1995）．『算数・数学教育における構成的アプローチの研究』．聖文社．",
    "岩崎秀樹・山口武志（2007）．「数学的探究の理論」．『数学教育学研究』，第13巻，pp.1-10．",
    "Claude, A. (2025). An unusual reference format example. Journal of Testing, 1, 1-2.",
    "Polya, G. (1945). How to solve it. Princeton University Press.",
    "Polya, G. (1954). Mathematics and plausible reasoning. Princeton University Press.",
    "宮川健・濵中裕明・大滝孝治（2016）．「論証活動」．『数学教育学研究』，第22巻，pp.25-36．",
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
    got = links("数学的探究（中原, 1995；岩崎・山口, 2007）における")
    assert got == [("1995", "B1", "exact"), ("2007", "B2", "exact")]


def test_multiple_years_and_page():
    assert links("Polya（1945, 1954）は") == [("1945", "B4", "exact"), ("1954", "B5", "exact")]
    assert links("（中原, 1995, p. 12）") == [("1995", "B1", "exact")]


def test_fullwidth_digits_map_back_to_original():
    text = "中原（１９９５）によれば"
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
