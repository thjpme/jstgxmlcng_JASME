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


# ---- C164: 文献リストにあるのに「該当なし」になっていた引用の形（内容は架空）
def _all(text, refs):
    """本文 1 文のすべての引用を、文献 refs と照合する（[(年の文字, 文献の ID か None, 種別)]）。"""
    known = {n for r in refs for n in r.parsed["names"]}
    mp = Mapped(text)
    out = []
    for c in extract_citations(mp.n, known):
        ref, kind, _ = match_citation(c, refs)
        s, e = mp.orig(*c["span"])
        out.append((text[s:e], ref.rid if ref else None, kind))
    return out


def test_c164_narrative_after_japanese_text_and_et_al_with_comma():
    """和文に続けた欧文の著者（「…についてはGoos (2019)」）と、「Cai, Morris, et al. (2019b)」の et al. の前のコンマ。"""
    refs = make_refs([
        "Goos, M. (2019). A chapter title. In G. Kaiser (Ed.), A book. Springer.",
        "Barwell, R., & Reid, D. A. (2019). Another chapter. In G. Kaiser (Ed.), A book. Springer.",
        "Cai, J., Morris, A., Hohensee, C., Hwang, S., & Hiebert, J. (2019a). Title one. Journal of Testing, 50, 1-2.",
        "Cai, J., Morris, A., Hohensee, C., Hwang, S., & Hiebert, J. (2019b). Title two. Journal of Testing, 50, 3-4.",
    ])
    assert _all("雑誌Aについては，Goos (2019) が述べた．", refs) == [("2019", "B1", "exact")]
    assert _all("ESMについてはGoos (2019)．FLMについてはBarwell & Reid (2019)．", refs) == [("2019", "B1", "exact"), ("2019", "B2", "exact")]
    assert _all("シリーズの最初であるCai, Morris, et al. (2019b) は，", refs) == [("2019b", "B4", "exact")]


def test_c164_et_al_prefers_three_or_more_authors_over_single_or_pair():
    """「Bakker et al.」は著者 1 人の文献ではなく、「Lavie et al.」は 2 人の文献より 3 人以上の文献に結ぶ。
    候補が 1 件だけのときは今までどおり（2 人の文献に et al. でも結ぶ）。"""
    refs = make_refs([
        "Bakker, A. (2019). A response. Journal of Testing, 3, 1-2.",
        "Bakker, A., Cai, J., English, L., & Kaiser, G. (2019). Effect sizes. Journal of Testing, 4, 1-2.",
        "Lavie, I. & Sfard, A. (2019). Two authors. Journal of Testing, 5, 1-2.",
        "Lavie, I., Steiner, A., & Sfard, A. (2019). Three authors. Journal of Testing, 6, 1-2.",
        "Gamma, C., & Delta, D. (2020). Only pair. Journal of Testing, 7, 1-2.",
    ])
    assert _all("Bakker et al. (2019) は", refs) == [("2019", "B2", "exact")]
    assert _all("(e.g., Lavie et al.,2019)", refs) == [("2019", "B4", "exact")]
    assert _all("Gamma et al. (2020) は", refs) == [("2020", "B5", "exact")]
    # et al. でなければ、人数が合う文献を選ぶ（今までどおり）
    assert _all("Bakker (2019) は", refs) == [("2019", "B1", "exact")]
    assert _all("Lavie & Sfard (2019) は", refs) == [("2019", "B3", "exact")]


def test_c164_reference_authors_without_separator_and_two_word_surname():
    """文献リストの著者が区切りなしに続く形（「Alpha,T. Beta-Gamma,A.(2021)」）と、2 語の姓（Esparza Puga・Van Dooren）を本文の「Puga」「Dooren」で引く形。"""
    refs = make_refs([
        "Alpha,T. Beta-Gamma,A.(2021).Teaching practices: The case of numbers, Journal of Testing, 62, pp.1-13.",
        "Esparza Puga, D. S., & Aguilar, M. S. (2021). Students' views. Journal of Testing, 8, 1-2.",
    ])
    assert refs[0].parsed["names"] == ["alpha", "beta-gamma"] and refs[0].parsed["n_authors"] == 2
    assert _all("Alpha and Beta-Gamma(2021) は，(Alpha and Beta-Gamma,2021)", refs) == [("2021", "B1", "exact"), ("2021", "B1", "exact")]
    assert _all("Esparza Puga & Aguilar(2021) は，(Esparza Puga & Aguilar ,2021)", refs) == [("2021", "B2", "exact"), ("2021", "B2", "exact")]
    # 綴りが違う・年が違う引用は、結ばない（誤ったリンクより未解決）
    assert _all("Alpah and Beta-Gamma(2021) は", refs)[0][1] is None
    assert _all("Alpha and Beta-Gamma(2022) は", refs)[0][1] is None


def test_c164_japanese_editor_suffix_and_organization_with_hiragana():
    """「（新村編, 2018）」の編は著者名に入れない。ひらがなをはさむ団体名は、全体が文献の著者名と合うときだけ結ぶ。"""
    refs = make_refs([
        "新村出編(2018)．架空辞典第七版，架空書店．",
        "架空学会数理分野のひな形検討委員会(2013).「報告　分野別のひな形」．",
    ])
    assert _all("（新村編, 2018）", refs) == [("2018", "B1", "exact")]
    assert _all("（架空学会数理分野のひな形検討委員会，2013，p.7）", refs) == [("2013", "B2", "exact")]
    # 別の団体名（後ろ側だけが同じ）は結ばない
    assert _all("（別の学会数理分野のひな形検討委員会，2013）", refs)[0][1] is None
