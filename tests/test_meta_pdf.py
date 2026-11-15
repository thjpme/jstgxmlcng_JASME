"""入力した書誌情報が出版版 PDF の 1 ページ目と違うときの知らせ meta_pdf と、コマンドラインの「空の項目を PDF から埋める」（W5 の手順 12）。
PDF の文字・数字はすべて架空（第 31 巻 第 1 号 pp.1〜12。conftest の meta fixture と同じ）。"""
import pytest

from conftest import PDFCHECK
from jasme_jats.cli import main
from jasme_jats.config import ArticleMeta
from jasme_jats.pipeline import Options, convert
from jasme_jats.report import NEEDS_ACTION, TO_CHECK, actions

from test_pdfmatch import head_pages

LINE = "数学教育学研究 第 31 巻 第 1 号 2026 pp.1〜12"
DATES = "2025年6月1日投稿受付\n2025年11月20日採用決定"


def pages_with(line=LINE, dates=DATES, n=13):
    """1 ページ目に誌名の行と日付を足した PDF の文字（ページ数は n。照合には使わない末尾の空ページで合わせる）。"""
    pages = head_pages()
    pages[0] = f"{line}\n{dates}\n" + pages[0]
    return pages + [""] * (n - len(pages))


def run(tmp_path, monkeypatch, journal, meta, pages, route="docx"):
    from jasme_jats import pdfmatch
    monkeypatch.setattr(pdfmatch, "extract_pages", lambda path: pages)
    (tmp_path / "dummy.pdf").write_bytes(b"%PDF-1.4\n")
    return convert(PDFCHECK, meta, journal, Options(out_dir=tmp_path / "out", pdf_path=tmp_path / "dummy.pdf", route=route))


def meta_act(res):
    return {a.key: a for a in actions(res)}.get("meta_pdf")


def test_same_values_give_no_notice(tmp_path, monkeypatch, journal, meta):
    res = run(tmp_path, monkeypatch, journal, meta, pages_with())
    assert res.pdf_biblio.volume == "31" and res.pdf_biblio.lpage == "12" and res.pdf_biblio.pages == 13
    assert meta_act(res) is None


def test_volume_differs_is_needs_action(tmp_path, monkeypatch, journal, meta):
    res = run(tmp_path, monkeypatch, journal, meta, pages_with(line="数学教育学研究 第 32 巻 第 1 号 2026 pp.1〜12"))
    a = meta_act(res)
    assert a.level == NEEDS_ACTION and "巻: 入力 31／PDF 32" in a.top and res.needs_action
    assert "11 章" in a.top and "11 章" in a.checklist and "入力" in a.box_detail
    assert "--meta" in a.cli and a.cli.startswith("要対応")
    # XML に出すのは入力の値のまま（PDF の値で置き換えない）
    xml = res.xml_path.read_text(encoding="utf-8")
    assert "<volume>31</volume>" in xml and "<volume>32</volume>" not in xml
    report = res.report_path.read_text(encoding="utf-8")
    assert "入力した書誌情報が、出版版 PDF と違います" in report.split("## 1.")[1].split("## 2.")[0]
    sec = report.split("## 11.")[1].split("## 12.")[0]
    assert "PDF から読んだ値" in sec and "| 巻 | 31 | 32 |" in sec and "PDF のページ数: 13" in sec


def test_dates_only_is_to_check(tmp_path, monkeypatch, journal, meta):
    res = run(tmp_path, monkeypatch, journal, meta, pages_with(dates="2025年6月3日投稿受付\n2025年11月20日採用決定"))
    a = meta_act(res)
    assert a.level == TO_CHECK and "受付日: 入力 2025-06-01／PDF 2025-06-03" in a.top and not res.needs_action


def test_page_count_text(tmp_path, monkeypatch, journal, meta):
    res = run(tmp_path, monkeypatch, journal, meta, pages_with(n=31))
    a = meta_act(res)
    assert a.level == TO_CHECK
    assert "PDF のページ数（31 ページ）が、ページの範囲 1〜12（12 ページ）と合いません" in a.top
    assert "別の論文の PDF ではないか" in a.box_detail


def test_unreadable_line_compares_nothing(tmp_path, monkeypatch, journal, meta):
    pages = [x.replace("数学教育学研究", "研究誌") for x in pages_with(line="誌名の行がない", dates="", n=13)]   # 誌名の行を読めない PDF
    res = run(tmp_path, monkeypatch, journal, meta, pages)
    assert res.pdf_biblio is not None and not res.pdf_biblio.any() and meta_act(res) is None


def test_without_pdf_there_is_no_biblio(tmp_path, journal, meta):
    res = convert(PDFCHECK, meta, journal, Options(out_dir=tmp_path / "x"))
    assert res.pdf_biblio is None and meta_act(res) is None
    assert "PDF から読んだ値" not in res.report_path.read_text(encoding="utf-8")


def test_article_meta_load_defaults(tmp_path):
    p = tmp_path / "m.toml"
    p.write_text('[article]\nvolume = "40"\nissue = ""\n', encoding="utf-8")
    m = ArticleMeta.load(p, {"volume": "99", "issue": "2", "fpage": "5", "received": "2029-06-01"})
    assert (m.volume, m.issue, m.fpage, str(m.received)) == ("40", "2", "5", "2029-06-01")
    assert ArticleMeta.load(p).issue == ""


def test_cli_fills_empty_items_from_pdf(tmp_path, monkeypatch, capsys):
    from jasme_jats import pdfmatch
    monkeypatch.setattr(pdfmatch, "extract_pages", lambda path: pages_with())
    pdf = tmp_path / "dummy.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    # --meta なしでも、PDF から巻・号・ページを読めれば記事 ID が決まる
    main([str(PDFCHECK), "--out", str(tmp_path / "a"), "--pdf", str(pdf)])
    cap = capsys.readouterr()
    assert "※ 書誌情報: 巻・号・最初のページ・最後のページ・受付日・受理日を PDF の 1 ページ目から読んで入れた（巻 31・号 1" in cap.out
    assert any(p.name == "31_1.xml" for p in (tmp_path / "a").rglob("*") if p.is_file()), list((tmp_path / "a").rglob("*"))
    # --meta の入力済みの項目は変えず、違いは meta_pdf で知らせる
    m = tmp_path / "m.toml"
    m.write_text('[article]\nvolume = "30"\n', encoding="utf-8")
    code = main([str(PDFCHECK), "--meta", str(m), "--out", str(tmp_path / "b"), "--pdf", str(pdf)])
    cap = capsys.readouterr()
    assert "巻 30" not in cap.out and "※ 書誌情報: 号・" in cap.out         # 入力済みの巻は埋めない
    assert code == 1 and "要対応: 書誌情報が出版版 PDF と違う（巻: 入力 30／PDF 31" in cap.err


@pytest.mark.parametrize("route", ["pdf", "docx"])
def test_wrong_paper_message_shows_issue_line(route, journal, meta, tmp_path, monkeypatch):
    """別の論文で中止する文の最後の行は、PDF の誌名の行を読めたときはその行（読めなければ最初の 2 行。test_pdfmatch）。"""
    from jasme_jats import pdfmatch
    from jasme_jats.pipeline import WrongPaperError
    from test_pdfmatch import swapped_pages
    pages = swapped_pages(journal)
    pages[0] = f"{LINE}\n{DATES}\n" + pages[0]
    monkeypatch.setattr(pdfmatch, "extract_pages", lambda path: pages)
    (tmp_path / "dummy.pdf").write_bytes(b"%PDF-1.4\n")
    with pytest.raises(WrongPaperError) as ei:
        convert(PDFCHECK, meta, journal, Options(out_dir=tmp_path / "out", pdf_path=tmp_path / "dummy.pdf", route=route))
    msg = str(ei.value)
    assert "\nPDF の 1 ページ目の誌名の行: 「数学教育学研究 第 31 巻 第 1 号 2026" in msg and msg.rstrip().endswith("」")
    assert msg.count("PDF の 1 ページ目") == 1
    assert "pp." in msg.splitlines()[-1] and "…" not in msg.splitlines()[-1]       # ページの範囲まで切らずに出す


def test_wrong_paper_text_keeps_page_range_of_long_issue_line():
    """誌名の行は、巻・号・ページの範囲まで切らずに出す（LINE_SHOWN 字まで）。コマンドラインの言い方は空白つき。"""
    from types import SimpleNamespace

    from jasme_jats.colab import step_text
    from jasme_jats.report import LINE_SHOWN, wrong_paper_text
    plan = SimpleNamespace(title=[SimpleNamespace(plain=lambda: "架空の題目の段落です")], title_en=[], paras={})
    pc = SimpleNamespace(verdict_counted=10, verdict_missing=8, first_lines=[])
    line = "数学教育学研究 第 29 巻 第 1 号 2023 pp.131〜146"
    assert len(line) < LINE_SHOWN
    text = wrong_paper_text(plan, pc, "a.docx", "b.pdf", line)
    assert line in text and step_text(text, "cli").count("docx と --pdf に別のファイルを指定してやり直して") == 1
