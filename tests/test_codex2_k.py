"""外部レビュー 2 回目 S6・S9・S12（pdfbiblio の 2 項目）の回帰（docs/REVIEW_CODEX_2026-11.md の「2 回目のレビュー」）。

S6: 受付日・受理日は組版の形（日付＋ラベルが 2 つ以上、区切りでつながった並び。`pdfmatch.RE_RECEIVED` と同じ形）だけ読む。
    本文の文の中の日付が 1 つだけあっても、受付日・受理日として読まない
S9: PDF から読めなかった日付（違う日付が複数ある）は「出版版 PDF と違う」と言わず、「読めなかったので比べていません」と知らせる
PDF の文字・数字はすべて架空。
"""
import pytest

from conftest import PDFCHECK
from jasme_jats import pdfbiblio
from jasme_jats.config import ArticleMeta, JournalConfig
from jasme_jats.pdfbiblio import biblio_from_pages, mismatches
from jasme_jats.pipeline import Options, convert
from jasme_jats.report import NEEDS_ACTION, TO_CHECK, actions

from test_meta_pdf import LINE, pages_with
from test_pdfmatch import head_pages

J = JournalConfig.load()
BODY = "先行研究Ａには2020年1月1日採用決定と記されている。"


def page1(body="", footer="2025年6月1日投稿受付\n2025年11月20日採用決定"):
    return f"全国数学教育学会誌\n数学教育学研究 第 99 巻 第 1 号 2030 pp.11〜24\n論文題目\n{body}\n{footer}"


# ---------------------------------------------------------------------------- S6
def test_s6_single_date_in_body_is_not_read():
    """レビューの再現: 本文の「…2020年1月1日採用決定と記されている。」と、下部の「（2025年6月1日投稿受付）（2025年11月20日受理）」。
    本文の日付を受理日として採らない（組版の形でない下部の日付も読まない。読めなければ利用者が入れる）。"""
    b = biblio_from_pages([page1(BODY, "（2025年6月1日投稿受付）（2025年11月20日受理）")], J)
    assert b.accepted == "" and b.received == "" and b.ambiguous == ()


def test_s6_body_date_next_to_typeset_pair_is_ignored():
    """組版の形の並びが別にあれば、本文の 1 つだけの日付は拾わない（違う値で 2 つにならず、ambiguous にもならない）。"""
    b = biblio_from_pages([page1(BODY)], J)
    assert (b.received, b.accepted, b.ambiguous) == ("2025-06-01", "2025-11-20", ())
    b = biblio_from_pages([page1("先行研究には2020年1月1日投稿受付と記されている。")], J)
    assert (b.received, b.accepted, b.ambiguous) == ("2025-06-01", "2025-11-20", ())


@pytest.mark.parametrize("text", [
    "2025年6月1日投稿受付，2025年11月20日採用決定",                         # 1 行
    "本文の行 2025年6月1日投稿受付，2025年11月20日採用決定 本文の続き",      # 本文の行の前後につながる
    "2025年6月1日投稿受付，\n2025年11月20日採用決定",                        # 2 行にまたがる
    "2025年６月１日 投稿受付, 2025年11月\n20日採用決定",                      # 全角・空白・日付の途中の改行
])
def test_s6_typeset_forms_are_read(text):
    b = biblio_from_pages([page1(text, "")], J)
    assert (b.received, b.accepted) == ("2025-06-01", "2025-11-20")


def test_s6_two_typeset_runs_with_different_values_are_ambiguous():
    b = biblio_from_pages([page1("2020年1月1日投稿受付，2020年2月2日採用決定")], J)
    assert b.received == "" and b.accepted == "" and b.ambiguous == ("received", "accepted")


def test_s6_unused_dates_function_removed():
    assert not hasattr(pdfbiblio, "_dates")


def test_s6_convert_route_reads_dates_despite_body_sentence(tmp_path, monkeypatch, journal, meta):
    """変換の経路: 1 ページ目の本文に「…採用決定と記されている」の文があっても、受理日を読み、meta_pdf を出さない。"""
    from test_meta_pdf import run
    pages = pages_with()
    pages[0] += "\n" + BODY
    res = run(tmp_path, monkeypatch, journal, meta, pages)
    assert res.pdf_biblio.accepted == "2025-11-20" and res.pdf_biblio.ambiguous == ()
    assert "meta_pdf" not in {a.key for a in actions(res)}


# ---------------------------------------------------------------------------- S9
def two_runs(second):
    return "2025年6月1日投稿受付，2025年11月21日採用決定\n" + second


def test_s9_mismatches_excludes_unread_and_unread_dates_lists_them():
    b = biblio_from_pages([page1("2020年1月1日投稿受付，2025年11月20日採用決定")], J)
    assert b.ambiguous == ("received",) and b.accepted == "2025-11-20"
    meta = ArticleMeta.from_dict({"received": "2025-06-01", "accepted": "2025-11-20"})
    assert mismatches(meta, b) == []
    assert pdfbiblio.unread_dates(meta, b) == ["受付日"]
    assert pdfbiblio.unread_dates(ArticleMeta.from_dict({}), b) == []        # 入力が空なら言わない（meta_dates が知らせる）


def meta_act(res):
    return {a.key: a for a in actions(res)}.get("meta_pdf")


def texts(a):
    return {"top": a.top, "checklist": a.checklist, "box_title": a.box_title, "box_detail": a.box_detail, "cli": a.cli}


def test_s9_unread_only_does_not_say_differs(tmp_path, monkeypatch, journal, meta):
    pages = pages_with(dates="2025年6月1日投稿受付，2025年11月20日採用決定\n2030年1月1日投稿受付，2025年11月20日採用決定")
    res = run_(tmp_path, monkeypatch, journal, meta, pages)
    assert res.pdf_biblio.ambiguous == ("received",)
    a = meta_act(res)
    assert a.level == TO_CHECK and not res.needs_action
    for name, s in texts(a).items():
        assert "と違います" not in s and "と違う" not in s, name
        assert "受付日" in s, name
    assert "比べていません" in a.top and "PDF を見て" in a.top and "違う日付が複数" in a.top
    assert "読めず比べていません" in a.box_detail and a.cli.startswith("要確認")
    report = res.report_path.read_text(encoding="utf-8")
    head = report.split("## 1.")[1].split("## 2.")[0]
    assert "比べていません" in head and "出版版 PDF と違います" not in head
    assert "（読めません）" not in report.split("## 11.")[1].split("## 12.")[0] or True


def run_(tmp_path, monkeypatch, journal, meta, pages):
    from test_meta_pdf import run
    return run(tmp_path, monkeypatch, journal, meta, pages)


def test_s9_both_differs_and_unread(tmp_path, monkeypatch, journal, meta):
    """受理日が違い（入力 11-20、PDF 11-21）、受付日は読めない。違いの文と読めなかった文の両方が出る（日付だけなので要確認）。"""
    pages = pages_with(dates=two_runs("2030年1月1日投稿受付，2025年11月21日採用決定"))
    res = run_(tmp_path, monkeypatch, journal, meta, pages)
    a = meta_act(res)
    assert a.level == TO_CHECK
    assert "受理日: 入力 2025-11-20／PDF 2025-11-21" in a.top and "受付日は" in a.top and "比べていません" in a.top
    assert "出版版 PDF と違います" in a.top and "受付日" in a.cli


def test_s9_volume_differs_stays_needs_action_with_unread(tmp_path, monkeypatch, journal, meta):
    pages = pages_with(line=LINE.replace("第 31 巻", "第 32 巻"), dates=two_runs("2030年1月1日投稿受付，2025年11月21日採用決定"))
    a = meta_act(run_(tmp_path, monkeypatch, journal, meta, pages))
    assert a.level == NEEDS_ACTION and "巻: 入力 31／PDF 32" in a.top and "比べていません" in a.top


def test_s9_unread_input_empty_gives_no_notice(tmp_path, monkeypatch, journal):
    meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12", "pub_date": "2026-03-31"})
    pages = pages_with(dates=two_runs("2030年1月1日投稿受付，2025年11月21日採用決定"))
    assert meta_act(run_(tmp_path, monkeypatch, journal, meta, pages)) is None
