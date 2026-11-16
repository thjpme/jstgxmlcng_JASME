"""冒頭部（題目・著者名・所属）の確かめ（修正計画の単位 C。C009・C015・C016・C035・C036・W6）。

docx は make_fixtures.front_variant で作る（内容は架空）。知らせは要対応 authors_missing と、要対応か要確認 front_check。
どちらも docx の文字も XML の構造も変えない（XML は知らせの有無で変わらない）。
"""
import make_fixtures as mf
import pytest
from conftest import ALL_DOCS, TEMPLATE
from lxml import etree

from jasme_jats import frontcheck, report
from jasme_jats.article import StyleSuspect
from jasme_jats.ai_assist import StyleFix
from jasme_jats.config import ArticleMeta
from jasme_jats.pipeline import Options, convert
from jasme_jats.report import NEEDS_ACTION, TO_CHECK, actions

S = mf.S


def run(tmp_path, journal, meta, name="f", **kw):
    """front_variant の docx を変換し、確かめ（不変性・最終・DTD）が合格することを確かめて返す。"""
    path = mf.front_variant(tmp_path / f"{name}.docx", **kw)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / f"out_{name}", ai_mode="none"))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    return res


def act(res, key):
    return next((a for a in actions(res) if a.key == key), None)


def keys(res):
    return [a.key for a in actions(res)]


def contribs(res):
    root = etree.fromstring(res.xml_base)
    return [[(n.findtext("surname"), n.findtext("given-names")) for n in c.iter("name")] for c in root.iter("contrib")]


# ---------------------------------------------------------------------------- 手順 1: 今の出方（変換の結果は知らせで変わらない）
def test_ok_variant_has_no_front_actions(tmp_path, journal, meta):
    res = run(tmp_path, journal, meta, kind="ok")
    assert [k for k in keys(res) if k in ("authors_missing", "front_check", "excluded_unsure", "name_split")] == []
    assert contribs(res) == [[("試験", "六郎"), ("SHIKEN", "Rokuro")]]


# ---------------------------------------------------------------------------- 手順 2: C009 和文の著者名が 1 人もない
@pytest.mark.parametrize("kind", ["table_normal", "table_body", "one_para", "no_author"])
def test_authors_missing_is_needs_action(tmp_path, journal, meta, kind):
    """著者表のセルにスタイルがない・所属と氏名が 1 つの段落・著者表がない、のどれでも、XML に和文の著者名がないと要対応で知らせる。
    XML は変えない（和文の氏名・所属は今までどおり入らない）。"""
    res = run(tmp_path, journal, meta, kind=kind)
    a = act(res, "authors_missing")
    assert a is not None and a.level == NEEDS_ACTION
    assert res.needs_action
    assert "著者名（日）" in a.top and "所属（日）" in a.top and "2 段落に分けて" in a.top
    # 候補が表の外の段落だけ（著者表がない docx）なら、著者表のセルとは言わない（点検 review19 の 3 回目の利用者向け 3）
    table_words = kind != "one_para"
    assert ("著者表の氏名のセル" in a.top) == table_words and ("著者表を作る必要はありません" in a.top) != table_words
    assert ("著者表に" in report.checklist_line(a)) == table_words and ("著者表に" in a.cli) == table_words
    assert "要対応" in report.checklist_line(a) and a.box_title.endswith("（要対応）")
    assert contribs(res) == [[("SHIKEN", "Rokuro")]]                  # 構造は変えない
    assert report.blocking(actions(res))


def test_authors_missing_lists_candidates_and_dedups(tmp_path, journal, meta):
    """候補（著者名・所属らしい段落）の ID を文に入れ、同じ段落を要確認 excluded_unsure で重ねて挙げない。"""
    res = run(tmp_path, journal, meta, kind="one_para")
    a = act(res, "authors_missing")
    src = next(s for s, p in res.plan.paras.items() if p.text_only() == "架空大学　試験　六郎")
    assert f"{src}「架空大学" in a.top and f"{src}「架空大学" in a.cli
    assert act(res, "excluded_unsure") is None
    assert src not in [s for s, _, _ in report.unplaced_exclusions(res)]
    table = run(tmp_path, journal, meta, name="t", kind="table_normal")
    top = act(table, "authors_missing").top
    assert "「架空大学」" in top and "「試験　六郎」" in top and "本文の表として出力しています" in top


def test_authors_missing_does_not_hide_unplaced_when_not_raised(tmp_path, journal, meta):
    """和文の著者がいる記事では、位置を決められない冒頭部の段落は今までどおり excluded_unsure に出る（候補を除くのは authors_missing が出るときだけ）。"""
    path = tmp_path / "c.docx"
    mf.make_conflict(path, loose=[mf.para(None, "冒頭に紛れた段落")])
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "o", ai_mode="none"))
    assert act(res, "authors_missing") is None
    assert [t for _, _, t in report.unplaced_exclusions(res)] == ["冒頭に紛れた段落"] and act(res, "excluded_unsure") is not None


def test_authors_missing_not_for_english_article_or_fixtures(tmp_path, journal):
    """英文の記事（meta.lang が en）では、和文の著者名がなくても出ない。ほかの既存の fixture でも出ない。"""
    meta_en = ArticleMeta.from_dict({"volume": "1", "issue": "1", "fpage": "1", "lpage": "2", "pub_date": "2024-03-31",
                                     "received": "2023-06-01", "accepted": "2023-11-20", "lang": "en"})
    res = run(tmp_path, journal, meta_en, kind="no_author")
    assert act(res, "authors_missing") is None
    for doc in ALL_DOCS:
        if doc == TEMPLATE:
            continue
        r = convert(doc, ArticleMeta.from_dict({"volume": "1", "issue": "1", "fpage": "1", "lpage": "2", "pub_date": "2024-03-31",
                                                "received": "2023-06-01", "accepted": "2023-11-20"}), journal,
                    Options(out_dir=tmp_path / f"o_{doc.stem}", ai_mode="none"))
        assert [k for k in keys(r) if k in ("authors_missing", "front_check")] == [], doc.name


def test_unplaced_guide_mentions_front_styles():
    """位置を決められない冒頭部・英文の部分の段落の直し方に、所属と氏名を分ける・英文の著者名のスタイルを案内する。"""
    assert "Enter で 2 段落に分けて" in report.UNPLACED_GUIDE[report.FRONT_OTHER_EXCLUDED][1]
    assert "著者名（英）" in report.UNPLACED_GUIDE[report.EN_OTHER_EXCLUDED][1]


# ---------------------------------------------------------------------------- 手順 3: 項目（front_check）
def front_items(res):
    return frontcheck.front_findings(res.plan, "ja")


def test_template_placeholder_shape():
    """テンプレートの見本の文字だけに当たる（実名・普通の所属には当たらない）。"""
    for t in ("氏名２(MS明朝，11pt)", "所属２(MS明朝，10pt)", "氏名１", "所属１", "Name2 (Century, 11pt)", "著者名3", "Affiliation 2 (Times, 10pt)"):
        assert frontcheck.template_placeholder(t), t
    for t in ("試験　六郎", "氏名　太郎", "所属　花子", "架空大学", "Rokuro SHIKEN", "", "試験（2024）"):
        assert not frontcheck.template_placeholder(t), t


@pytest.mark.parametrize("white", [True, False])
def test_template_row_is_needs_action_and_not_name_split(tmp_path, journal, meta, white):
    res = run(tmp_path, journal, meta, kind="template" if white else "template_black")
    a = act(res, "front_check")
    assert a is not None and a.level == NEEDS_ACTION
    f = [x for x in front_items(res) if x.kind == frontcheck.TEMPLATE][0]
    assert len(f.srcs) == 2 and "氏名２(MS明朝，11pt)" in a.top and "所属２(MS明朝，10pt)" in a.top
    assert "Word で著者表のその行を消して" in a.top
    assert act(res, "name_split") is None                          # 見本の氏名を「姓と名の分け方」として出さない
    assert contribs(res)[1] == [("氏名２(MS明朝，11pt)", None)]      # 構造は変えない（見本の行も今までどおり出す）


def test_title_multi_asks_to_check_and_text_unchanged(tmp_path, journal, meta):
    res = run(tmp_path, journal, meta, extra_title="―副題を題目のスタイルで―")
    a = act(res, "front_check")
    assert a.level == TO_CHECK and "題目（日）のスタイルの段落が 2 つあり" in a.top and "ダッシュで始まるので副題のよう" in a.top
    assert "「副題（日）」のスタイル" in a.top
    root = etree.fromstring(res.xml_base)
    assert "".join(root.find(".//article-title").itertext()) == "氏名の検証用文書―副題を題目のスタイルで―"      # 文字は今までどおり
    assert not res.needs_action or all(x.key != "front_check" for x in report.blocking(actions(res)))


def test_title_multi_english_and_single_not_flagged(tmp_path, journal, meta):
    res = run(tmp_path, journal, meta)
    assert act(res, "front_check") is None                          # 普通の 1 段落の題目・副題では出ない
    two = run(tmp_path, journal, meta, name="en", en_title="Checking Names", en_title_extra="Second line")
    f = [x for x in front_items(two) if x.kind == frontcheck.TITLE_MULTI]
    assert f and f[0].note == "題目（英）" and len(f[0].srcs) == 2


def test_title_missing_is_needs_action(tmp_path, journal, meta):
    res = run(tmp_path, journal, meta, body_title=True)
    a = act(res, "front_check")
    assert a.level == NEEDS_ACTION and "「題目（日）」のスタイルの段落がありません" in a.top and "題目らしい段落:" in a.top
    up = act(res, "upload")
    assert up is not None                                            # upload（EMSGM097E）はそのまま出す
    assert "EMSGM097E: タイトル(英)とタイトル(日)の両方が未設定" + report.UPLOAD_TITLE_NOTE in up.top      # 同じ原因と添える


def test_authors_missing_with_styled_table_points_to_title_missing(tmp_path, journal, meta):
    """題目が本文のスタイル・著者表のスタイルはある形: authors_missing はスタイルを付ける直し方を書かず、題目の段落を直すと消えると書く
    （一覧の行・枠・コマンドラインとも）。著者表にスタイルがない形は、今までどおりスタイルを付ける直し方。"""
    res = run(tmp_path, journal, meta, body_title=True)
    a = act(res, "authors_missing")
    assert a is not None and a.level == NEEDS_ACTION
    assert report.AUTHORS_TITLE_NOTE in a.top and report.AUTHORS_TITLE_NOTE in a.box_detail
    for text in (a.top, a.checklist, a.cli):
        assert "のスタイルを付けて" not in text and "〈題目の段落がない〉" in text
    plain = run(tmp_path, journal, meta, name="n", kind="table_normal")
    b = act(plain, "authors_missing")
    assert report.AUTHORS_TITLE_NOTE not in b.top and "のスタイルを付けて" in b.checklist


def test_english_article_missing_ja_title_not_flagged(tmp_path, journal):
    meta_en = ArticleMeta.from_dict({"volume": "1", "issue": "1", "fpage": "1", "lpage": "2", "pub_date": "2024-03-31",
                                     "received": "2023-06-01", "accepted": "2023-11-20", "lang": "en"})
    res = run(tmp_path, journal, meta_en, body_title=True)
    assert [x.kind for x in frontcheck.plan_findings(res.plan, "en")] == []


def test_style_check_does_not_repeat_front_paragraphs(tmp_path, journal, meta):
    """AI の style_fixes が、題目・著者名らしい段落（要対応で知らせたもの）を指していても、要確認 style_check に同じ段落を出さない。"""
    res = run(tmp_path, journal, meta, body_title=True)
    title = frontcheck.title_candidates(res.plan)[0]
    res.plan.style_suspects = [StyleSuspect("quote_like", title)]
    res.ai.style_fixes = [StyleFix(title, "title", "題目（日）", "Word で段落のスタイルを「題目（日）」にする", "題目の形", "高")]
    rows, only = report.style_check_rows(res)
    assert title not in [s for s, _ in rows]


def test_front_check_is_one_action_with_heaviest_level(tmp_path, journal, meta):
    """要対応の項目が 1 つでもあれば要対応、なければ要確認（1 つの key）。"""
    res = run(tmp_path, journal, meta, kind="template", extra_title="―副題を題目のスタイルで―")
    assert [k for k in keys(res) if k == "front_check"] == ["front_check"]
    a = act(res, "front_check")
    assert a.level == NEEDS_ACTION and "2 件" in a.top
    assert a.top.index("テンプレートの見本の行") < a.top.index("題目（日）のスタイルの段落")      # 要対応の項目が先


# ---------------------------------------------------------------------------- 手順 4: 著者表の形（swap・ja_missing・aff_missing・en_missing・en_count）
def kinds(res):
    return [x.kind for x in front_items(res)]


def test_swap_asks_to_check_and_not_name_split(tmp_path, journal, meta):
    """所属と氏名のセルが入れ替わった著者表は、要確認で知らせ、「姓と名の分け方」には出さない。XML は変えない。"""
    res = run(tmp_path, journal, meta, authors=(("試験　六郎", "架空大学人間科学研究科"),))
    a = act(res, "front_check")
    assert a.level == TO_CHECK and kinds(res) == [frontcheck.SWAP]
    assert "所属の語（「大学」）" in a.top and "Enter で 2 段落に分けて" in a.top
    # 例は、所属の語がある著者名（著者名のスタイル）と、氏名らしい所属（所属のスタイル）に分けて書く
    import re
    assert re.search(r"所属の語がある著者名: d\d+「架空大学人間科学研究科」。氏名らしい所属: d\d+「試験　六郎」）", a.top)
    assert act(res, "name_split") is None and contribs(res)[0][0] == ("架空大学人間科学研究科", None)


def test_chapter2_note_follows_front_check_level(tmp_path, journal, meta):
    """2 章のスタイルの表の注記は、front_check の重さのとおり（要確認なら「要確認」と書き、「要対応」と書かない）。"""
    res = run(tmp_path, journal, meta, authors=(("試験　六郎", "架空大学人間科学研究科"),))
    src = [x for x in front_items(res) if x.kind == frontcheck.SWAP][0].srcs[0]
    res.plan.style_suspects = [StyleSuspect("quote_like", src)]
    text = "\n".join(report.ai_style_section(res))
    assert "（冒頭部の確かめ〈要確認「題目・著者名・所属」〉に載せた）" in text and "要対応「" not in text


def test_swap_not_flagged_for_plain_names(tmp_path, journal, meta):
    """空白のない氏名・所属の語のない所属では、入れ替わりと言わない（name_split は今までどおり）。"""
    res = run(tmp_path, journal, meta, authors=(("架空大学", "試験六郎"),))
    assert kinds(res) == [] and act(res, "name_split") is not None
    res = run(tmp_path, journal, meta, name="b", authors=(("架空研究会", "試験　六郎"),))
    assert kinds(res) == []


def test_swap_in_one_paragraph_with_author_style(tmp_path, journal, meta):
    """「所属　氏名」の 1 段落に「著者名（日）」を付けた形: 和文の所属がなく（要対応 aff_missing）、入れ替わり（要確認 swap）も挙がる。"""
    res = run(tmp_path, journal, meta, kind="one_para_author")
    assert kinds(res) == [frontcheck.AFF_MISSING, frontcheck.SWAP]
    assert act(res, "front_check").level == NEEDS_ACTION and act(res, "name_split") is None
    assert act(res, "authors_missing") is None


def test_ja_missing_and_en_count(tmp_path, journal, meta):
    two_en = (("Rokuro SHIKEN", "Fictional University"), ("Nanao KENSHO", "Fictional Institute"))
    res = run(tmp_path, journal, meta, en=two_en)                               # 英文の著者が 2 人、和文が 1 人
    f = [x for x in front_items(res) if x.kind == frontcheck.JA_MISSING]
    assert f and f[0].level == frontcheck.MUST and act(res, "front_check").level == NEEDS_ACTION
    two_ja = (("架空大学", "試験　六郎"), ("架空研究所", "検証　七郎"))
    res = run(tmp_path, journal, meta, name="b", authors=two_ja)                 # 和文が 2 人、英文が 1 人
    assert kinds(res) == [frontcheck.EN_COUNT] and act(res, "front_check").level == TO_CHECK
    res = run(tmp_path, journal, meta, name="c", authors=two_ja, en=two_en)      # 2 人・2 人は出ない
    assert kinds(res) == []


def test_aff_missing_and_en_missing(tmp_path, journal, meta):
    res = run(tmp_path, journal, meta, authors=(("", "試験　六郎"),))
    assert kinds(res) == [frontcheck.AFF_MISSING] and act(res, "front_check").level == NEEDS_ACTION
    res = run(tmp_path, journal, meta, name="b", en_para=True)
    a = act(res, "front_check")
    assert kinds(res) == [frontcheck.EN_MISSING] and a.level == TO_CHECK
    assert "「著者名（英）」「所属（英）」" in a.top and "Rokuro SHIKEN" in a.top
    assert act(res, "excluded_unsure") is None                                  # 同じ段落を 2 回挙げない


def test_authors_missing_suppresses_dependent_items(tmp_path, journal, meta):
    """和文の著者名が 1 人もないときは、和文の所属・英文の著者数の食い違いを要対応・要確認にして重ねない（authors_missing だけ）。"""
    for kind in ("table_normal", "one_para", "no_author"):
        res = run(tmp_path, journal, meta, name=kind, kind=kind)
        assert [x.kind for x in front_items(res) if x.kind in (frontcheck.AFF_MISSING, frontcheck.EN_COUNT, frontcheck.JA_MISSING)] == []
        assert act(res, "authors_missing") is not None and act(res, "front_check") is None


# ---------------------------------------------------------------------------- 手順 5: 出版版 PDF との確かめ（pdf_findings）
class FakeCheck:
    """pdfmatch.compare の結果のうち、pdf_findings が読む部分。"""
    def __init__(self, unmatched=(), found_elsewhere=(), ok=True, verdict=""):
        self.ok, self.verdict = ok, verdict
        self.unmatched, self.found_elsewhere = list(unmatched), list(found_elsewhere)


def front_page(extra=""):
    """架空の PDF の 1 ページ目の文字（題目・副題・所属・氏名。docx の文字に、組版で入る行を足したもの）。"""
    return "数学教育学研究 第 1 巻 第 1 号 2024 pp.1〜2\n氏名の検証用文書\n―姓と名―\n架空大学\n試験 六郎\n" + extra


def paras_of(res):
    p = res.plan
    return dict(title=p.title[0].src, aff=p.affs[0].ja.src, name=p.authors[0].name_ja.src, aff_en=p.affs[0].en.src,
                name_en=p.authors[0].name_en.src, title_en=p.title_en[0].src)


def test_pdf_findings_nothing_when_everything_is_on_the_first_page(tmp_path, journal, meta):
    res = run(tmp_path, journal, meta)
    out, on_page = frontcheck.pdf_findings(res.plan, [front_page(), "本文のページ"], FakeCheck())
    assert out == [] and on_page == set()


def test_pdf_findings_missing_near_and_title_page(tmp_path, journal, meta):
    res = run(tmp_path, journal, meta, authors=(("架空髙校", "試験　六郎"),))
    ids = paras_of(res)
    page = front_page().replace("架空大学", "架空高校")                  # 異体字だけ違う（少し違う）
    out, _ = frontcheck.pdf_findings(res.plan, [page], FakeCheck())
    assert [(f.kind, f.level, f.srcs) for f in out] == [(frontcheck.PDF_NEAR, frontcheck.CHECK, [ids["aff"]])]
    gone = page.replace("試験 六郎", "ほか 氏")                              # 著者名が PDF にない
    out, _ = frontcheck.pdf_findings(res.plan, [gone], FakeCheck())
    kinds_ = {f.kind: f.srcs for f in out}
    assert kinds_[frontcheck.PDF_MISSING] == [ids["name"]] and frontcheck.PDF_NEAR in kinds_
    assert all(f.level == frontcheck.CHECK for f in out)                 # PDF の項目は要確認にとどめる
    # 号全体の PDF（題目が 3 ページ目）でも、題目のページから探して誤って知らせない
    out, on_page = frontcheck.pdf_findings(res.plan, ["別の論文", "別の論文の続き", page.replace("架空高校", "架空髙校"), "本文"],
                                           FakeCheck())
    assert out == []
    # 題目が PDF にない: 題目の段落は pdf_missing（pdf_near は出さない）
    out, _ = frontcheck.pdf_findings(res.plan, ["まったく違う文字だけのページ。" * 5], FakeCheck())
    assert ids["title"] in {s for f in out if f.kind == frontcheck.PDF_MISSING for s in f.srcs}


def test_pdf_findings_english_items_use_the_match_result(tmp_path, journal, meta):
    res = run(tmp_path, journal, meta)
    ids = paras_of(res)
    pages = [front_page()]
    out, _ = frontcheck.pdf_findings(res.plan, pages, FakeCheck(unmatched=[ids["aff_en"]]))
    assert [(f.kind, f.srcs) for f in out] == [(frontcheck.PDF_EN_MISSING, [ids["aff_en"]])]
    out, _ = frontcheck.pdf_findings(res.plan, pages, FakeCheck(unmatched=[ids["aff_en"]], found_elsewhere=[ids["aff_en"]]))
    assert out == []                                                      # PDF の別の位置にそのままある段落は挙げない
    for bad in (FakeCheck(ok=False), FakeCheck(verdict="wrong"), FakeCheck(verdict="garbled")):
        assert frontcheck.pdf_findings(res.plan, pages, bad) == ([], set())      # 照合できなかったときは何も言わない


def test_front_check_reads_pdf_findings_and_dedups_with_template(tmp_path, journal, meta):
    """PDF の項目は front_check（要確認）に 1 つにまとまり、テンプレートの見本の行（要対応）と同じ段落は重ねない。"""
    from jasme_jats.pdfmatch import PdfCheck
    res = run(tmp_path, journal, meta, kind="template")
    ids = paras_of(res)
    tmpl = [f for f in front_items(res) if f.kind == frontcheck.TEMPLATE][0].srcs
    out, on_page = frontcheck.pdf_findings(res.plan, [front_page()], FakeCheck(unmatched=[ids["name_en"]]))
    assert {s for f in out if f.kind == frontcheck.PDF_MISSING for s in f.srcs} == set(tmpl)        # 見本の行は PDF にない
    res.pdf_check = PdfCheck(front=out, front_on_page=on_page)
    got = [f for f in report.front_findings(res)]
    assert [f.kind for f in got] == [frontcheck.TEMPLATE, frontcheck.PDF_EN_MISSING]               # PDF の項目から見本の段落を除く
    a = act(res, "front_check")
    top = a.top
    assert top.count("氏名２(MS明朝，11pt)") == 1 and "出版版 PDF に見つからない英文の項目" in top
    # 要対応と要確認の項目が混ざるときは、要確認の項目に印を付ける（囲み・一覧の行・コマンドライン）
    assert a.level == NEEDS_ACTION and "（要確認）出版版 PDF に見つからない英文の項目" in top
    assert "（要確認）著者表に、テンプレートの見本の行" not in top
    assert "PDF に見つからない英文の項目（要確認）" in a.checklist and "テンプレートの見本の行（要確認）" not in a.checklist
    assert "（要確認）出版版 PDF に見つからない英文の項目" in a.box_detail and "（要確認）出版版 PDF" in a.cli


def test_pdf_en_name_in_other_order_is_found(tmp_path, journal, meta):
    """英文の著者名の語が PDF の 1 つの行にすべてあれば（姓と名の順だけが違う）、PDF に見つからないとは言わない。"""
    res = run(tmp_path, journal, meta)
    ids = paras_of(res)
    name_en = res.plan.paras[ids["name_en"]].plain()
    swapped = " ".join(reversed(name_en.split()))
    assert swapped != name_en
    last = f"A Fictional Title\n{swapped}*1\nFictional University"
    out, _ = frontcheck.pdf_findings(res.plan, [front_page(), last], FakeCheck(unmatched=[ids["name_en"]]))
    assert out == []
    out, _ = frontcheck.pdf_findings(res.plan, [front_page(), "A Fictional Title\nOther Name"], FakeCheck(unmatched=[ids["name_en"]]))
    assert [(f.kind, f.srcs) for f in out] == [(frontcheck.PDF_EN_MISSING, [ids["name_en"]])]


def test_pdf_check_fills_front_from_a_real_pdf(journal, meta, tmp_path):
    """実際の PDF（sample_pdfcheck）で、冒頭部の項目が出ない。check_pdf が front・front_on_page を入れる（読めないときも例外にしない）。"""
    from conftest import PDFCHECK, PDFCHECK_PDF
    if not PDFCHECK_PDF.exists():
        pytest.skip("sample_pdfcheck.pdf がない")
    for route in ("docx", "pdf"):
        res = convert(PDFCHECK, meta, journal, Options(out_dir=tmp_path / route, ai_mode="none", route=route, pdf_path=PDFCHECK_PDF))
        assert res.pdf_check.ok and res.pdf_check.front == [], route
        assert act(res, "front_check") is None and act(res, "authors_missing") is None


def test_authors_missing_notes_candidates_on_the_title_page(tmp_path, journal, meta):
    from jasme_jats.pdfmatch import PdfCheck
    res = run(tmp_path, journal, meta, kind="table_normal")
    out, on_page = frontcheck.pdf_findings(res.plan, [front_page()], FakeCheck())
    assert len(on_page) == 2                                               # 本文の表になった著者表のセル（所属・氏名）
    res.pdf_check = PdfCheck(front=out, front_on_page=on_page)
    assert act(res, "authors_missing").top.count("PDF の題目のページにあります") == 2
    res.pdf_check = PdfCheck(ok=False)                                     # 照合できなかったときは添えない
    assert "PDF の題目のページ" not in act(res, "authors_missing").top


# ---------------------------------------------------------------------------- 手順 6: 空白だけの段落（本文の役割のスタイル）で、和文の冒頭を本文に切り替えない
def test_blank_body_role_paragraph_does_not_switch_front_region(tmp_path, journal, meta):
    """副題と著者表の間の空の段落が章見出しのスタイルでも、著者表は著者として読む（本文の表にならない）。切り替えなかったことは判断に記録する。"""
    res = run(tmp_path, journal, meta, kind="blank_sec1")
    assert contribs(res) == [[("試験", "六郎"), ("SHIKEN", "Rokuro")]]
    assert [k for k in keys(res) if k in ("authors_missing", "front_check", "excluded_unsure")] == []
    root = etree.fromstring(res.xml_base)
    assert root.findall(".//body//table-wrap") == []
    assert any("空白だけの段落のスタイル" in d.message and "和文の冒頭のまま" in d.message for d in res.plan.decisions)
    assert [p.text_only() for p in res.plan.title] == ["氏名の検証用文書"]


def test_blank_heading_inside_body_is_unchanged(tmp_path, journal, meta):
    """本文の途中の空の章見出しは、今までどおり（領域は本文のまま。本文の段落は落ちない）。空の段落の直後に標準スタイルの本文が続く形でも本文は出る。"""
    path = tmp_path / "mid.docx"
    mf.make_article(path, "空の見出しの検証用文書",
                    lambda b: [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "最初の段落である。"), mf.para(S["sec1"], ""),
                               mf.para(None, "標準スタイルの段落である。")])
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "o", ai_mode="none"))
    out = etree.fromstring(res.xml_base)
    assert ["".join(p.itertext()) for p in out.findall(".//body//p")] == ["最初の段落である。", "標準スタイルの段落である。"]
    assert res.fidelity.ok and res.fidelity.final_ok


def test_pdf_findings_failure_is_recorded_in_chapter_13(journal, meta, tmp_path, monkeypatch):
    """冒頭部の PDF との確かめ（frontcheck.pdf_findings）が想定外の例外で失敗しても、照合の結果は損なわず、13 章の記録に 1 行残す
    （例外の型の名前。PdfCheck.front_error）。知らせ（Action）は足さない（点検 review19 の 3 回目の原則 3）。"""
    from test_pdfmatch import N10_TAIL, SMALL_FRONT, TALK, body_lines, convert_with_pages, n10_pages
    from test_pdfdocx_graphics import BODY, PUB, _article

    def boom(plan, pages, res):
        raise KeyError("架空の失敗")
    monkeypatch.setattr(frontcheck, "pdf_findings", boom)
    docx = _article(tmp_path, lambda b: [mf.para(mf.S["body"], BODY)])
    pages = n10_pages([*SMALL_FRONT, *body_lines(PUB), *body_lines(TALK), *N10_TAIL])
    res = convert_with_pages(tmp_path, monkeypatch, journal, meta, pages, "pdf", docx=docx)
    assert res.pdf_check.ok and res.pdf_check.front_error == "KeyError" and res.supplement.ok
    ch13 = res.report_path.read_text(encoding="utf-8").split("\n## 13. ")[1]
    assert "冒頭部（題目・著者名・所属）の、出版版 PDF との確かめはできませんでした（KeyError）" in ch13
    assert not [a for a in actions(res) if "KeyError" in (a.top + a.cli + a.checklist)]


def test_pdf_items_show_the_whole_paragraph(tmp_path, journal, meta):
    """PDF と比べる項目（pdf_en_missing など）は、段落の文字を先頭 15 文字で切らず、まるごと出す（違う所が後ろにあっても PDF と
    見比べられるように。点検 review19 の 3 回目の利用者向け 1）。"""
    from jasme_jats.pdfmatch import PdfCheck
    res = run(tmp_path, journal, meta)
    ids = paras_of(res)
    aff_en = res.plan.paras[ids["aff_en"]].text_only().strip()
    assert len(aff_en) > 15
    res.pdf_check = PdfCheck(front=[frontcheck.finding(frontcheck.PDF_EN_MISSING, [ids["aff_en"]])])
    a = act(res, "front_check")
    assert f"「{aff_en}」" in a.top and f"「{aff_en}」" in a.box_detail
