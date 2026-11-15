"""出版版 PDF の 1 ページ目から書誌情報を読む（pdfbiblio。W5 の手順 11）。文字・数字はすべて架空。"""
import datetime as dt

import pytest

from jasme_jats.config import ArticleMeta, JournalConfig
from jasme_jats.pdfbiblio import (PdfBiblio, biblio_from_pages, biblio_inputs, fill_missing, mismatches, page_count_ok,
                                  read_biblio)

J = JournalConfig.load()


def page1(line="数学教育学研究 第 99 巻 第 1 号 2030 pp.11〜24", dates="2029年6月1日投稿受付\n2029年11月20日採用決定"):
    return f"全国数学教育学会誌\n{line}\n論文題目\n{dates}\n本文"


def test_config_has_pdf_biblio():
    assert "(?P<volume>" in J.pdf_issue_line
    assert J.pdf_date_labels == {"received": "投稿受付", "revised": "再投稿受付", "accepted": "採用決定"}


@pytest.mark.parametrize("line", [
    "数学教育学研究 第 99 巻 第 1 号 2030 pp.11〜24",          # 半角
    "数学教育学研究　第９９巻　第１号　２０３０　ｐｐ．１１～２４",      # 全角（NFKC で半角になる）
    "数学教育学研究  第99巻第1号  2030   pp. 11-24",               # 空白の揺れ・「-」
    "数学教育学研究 第 99 巻\n第 1 号 2030 pp.11–24",              # 改行・「–」
])
def test_issue_line_variants(line):
    b = biblio_from_pages([page1(line)], J)
    assert (b.volume, b.issue, b.year, b.fpage, b.lpage) == ("99", "1", "2030", "11", "24")
    assert b.line.startswith("数学教育学研究")


def test_dates():
    b = biblio_from_pages([page1(dates="2029年６月１日 投稿受付\n2029年9月3日再投稿受付\n2029年11月\n20日採用決定")], J)
    assert (b.received, b.revised, b.accepted) == ("2029-06-01", "2029-09-03", "2029-11-20")
    # 再投稿受付のない号では revised は空。投稿受付が再投稿受付に取られない
    b = biblio_from_pages([page1()], J)
    assert (b.received, b.revised, b.accepted) == ("2029-06-01", "", "2029-11-20")
    # 存在しない日付は読まない
    b = biblio_from_pages([page1(dates="2029年2月30日投稿受付")], J)
    assert b.received == ""


def test_unreadable_gives_empty_without_error(tmp_path):
    assert not biblio_from_pages([], J).any()
    assert not biblio_from_pages(["ただの本文です"], J).any()
    assert biblio_from_pages(["ただの本文です"], J).pages == 1
    j2 = JournalConfig.load()
    j2.pdf_issue_line = "(("          # 壊れた正規表現でも例外にしない
    assert not biblio_from_pages([page1()], j2).volume
    j2.pdf_issue_line, j2.pdf_date_labels = "", {}
    assert not biblio_from_pages([page1()], j2).any()
    bad = tmp_path / "x.pdf"
    bad.write_bytes(b"not a pdf")
    assert read_biblio(bad, J) == PdfBiblio()
    assert read_biblio(tmp_path / "none.pdf", J) == PdfBiblio()


def test_inputs_and_fill_missing():
    b = biblio_from_pages([page1(dates="2029年9月3日再投稿受付\n2029年6月1日投稿受付")], J)
    assert biblio_inputs(b) == {"volume": "99", "issue": "1", "fpage": "11", "lpage": "24", "received": "2029-06-01"}   # 再投稿受付は入れない
    given = {"volume": "98", "issue": "", "fpage": None, "peer_review": "yes"}
    out, filled = fill_missing(given, b)
    assert out["volume"] == "98"                    # 入力済みは変えない
    assert (out["issue"], out["fpage"], out["lpage"], out["received"]) == ("1", "11", "24", "2029-06-01")
    assert out["peer_review"] == "yes" and "accepted" not in out
    assert filled == ["号", "最初のページ", "最後のページ", "受付日"]
    assert given["issue"] == ""                      # 元の辞書は変えない
    assert fill_missing({}, PdfBiblio())[1] == []


def meta(**kw):
    return ArticleMeta.from_dict(kw)


def test_mismatches():
    b = biblio_from_pages([page1()] + ["x"] * 13, J)           # 14 ページ
    ok = meta(volume="99", issue="1", fpage="11", lpage="24", received="2029-06-01", accepted="2029-11-20", pub_date="2030-03-31")
    assert mismatches(ok, b) == []
    ms = mismatches(meta(volume="98", issue="01", fpage="11", lpage="24", received="2029-06-10"), b)
    assert ms == [("巻", "98", "99"), ("受付日", "2029-06-10", "2029-06-01")]   # 「01」と「1」は同じ号
    assert mismatches(meta(pub_date="2031-03-31"), b) == [("発行日の年", "2031", "2030")]
    # 読めなかった項目と入力が空の項目は比べない
    assert mismatches(meta(volume="98"), PdfBiblio()) == []
    assert mismatches(meta(), b) == []
    # 再受付日は比べない
    assert mismatches(meta(revised="2020-01-01"), biblio_from_pages([page1(dates="2029年9月3日再投稿受付")], J)) == []


def test_page_count():
    assert page_count_ok("11", "24", 14) and page_count_ok("11", "24", 15)
    assert not page_count_ok("11", "24", 31)
    assert page_count_ok("", "24", 31) and page_count_ok("11", "24", 0)    # 比べられなければ違いにしない
    b = biblio_from_pages([page1()] + ["x"] * 30, J)
    assert mismatches(meta(fpage="11", lpage="24"), b) == [("ページ数", "11〜24（14 ページ）", "31 ページ")]
