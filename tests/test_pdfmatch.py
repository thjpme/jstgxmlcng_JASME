"""出版版 PDF との照合（pdfmatch.py）。

tests/fixtures/sample_pdfcheck.pdf は、sample_pdfcheck.docx の文字を出版社が組版で直した想定（全角のかっこ・句読点、
「資料」→「付録」など）にして LibreOffice で PDF にしたもの（tests/make_fixtures.py）。
"""
import pytest
from lxml import etree

from conftest import PDFCHECK, PDFCHECK_PDF
from jasme_jats.pdfmatch import compare, is_width_pair
from jasme_jats.pipeline import Options, _mechanical, convert

PUBLISHED = {   # 出版社が直した想定の文字（XML はこうなる）
    "d12": "本研究は架空理論（Fictional Theory, 以下，FT）に基づく（試験，2020；見本，2021）。",
    "d13": "詳しくは資料の学習指導案を参照されたい。授業は２回行った。",      # 「資料」→「付録」は直さない（レポートだけ）
    "d14": "（1）方法の概要",
    "d17": "試験四郎（2020）．「架空の研究」．『架空誌』，第1巻，pp.1-10．",
}


def load(res):
    return etree.fromstring(res.xml_path.read_bytes().split(b"\n", 2)[2])


def texts(root):
    return ["".join(x.itertext()) for x in root.iter("p", "title", "mixed-citation")]


def test_width_pairs():
    assert is_width_pair("(", "（") and is_width_pair("２", "2") and is_width_pair("a", "ａ")
    assert not is_width_pair("〜", "~") and not is_width_pair("−", "－") and not is_width_pair("資", "付")
    assert not is_width_pair(" ", "　")


def test_matches_width_to_published_pdf(journal, meta, tmp_path):
    pytest.importorskip("pypdfium2")
    res = convert(PDFCHECK, meta, journal, Options(out_dir=tmp_path, pdf_path=PDFCHECK_PDF, convert_metafiles=False))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    pc = res.pdf_check
    assert pc.ok and pc.unmatched == []
    assert [(d.src, d.docx, d.pdf) for d in pc.diffs] == [("d13", "資料", "付録")]
    root = load(res)
    out = texts(root)
    for want in PUBLISHED.values():
        assert want in out
    # リンクは保たれる（引用の年、URL）。URL の段落は出版版と同じなので変えない
    assert {x.text for x in root.iter("xref") if x.get("ref-type") == "bibr"} >= {"2020", "2021"}
    assert any("https://example.com/a で公開している" in t for t in out)
    # 不変性チェックは、変えた文字を docx の元の文字として照合している
    assert len(res.fidelity.pdf_width) == pc.width_count > 0 and len(res.fidelity.pdf_drops) == pc.drop_count > 0
    report = res.report_path.read_text(encoding="utf-8")
    assert "要確認: 出版版 PDF と文字が違う箇所が 1 件あります" in report.split("## 2.")[0]
    assert "| d13 |" in report and "| 資料 | 付録 |" in report
    assert "「(→（」" in report and "「架空理論 (Fict」→「架空理論（Fict」" in report
    assert "出版版 PDF と文字が違う箇所（1 件）" in report.split("## 14.")[1]


def test_width_matching_can_be_turned_off(journal, meta, tmp_path):
    pytest.importorskip("pypdfium2")
    res = convert(PDFCHECK, meta, journal, Options(out_dir=tmp_path, pdf_path=PDFCHECK_PDF, pdf_width=False,
                                                   convert_metafiles=False))
    assert res.fidelity.ok and res.fidelity.pdf_width == [] and res.fidelity.pdf_drops == []
    assert "本研究は架空理論 (Fictional Theory, 以下, FT) に基づく (試験, 2020; 見本, 2021)。" in texts(load(res))
    report = res.report_path.read_text(encoding="utf-8")
    assert "設定により PDF に合わせていない" in report and len(res.pdf_check.diffs) == 1


def test_no_pdf_means_no_check(journal, meta, tmp_path):
    res = convert(PDFCHECK, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    assert res.pdf_check is None
    assert "| 出版版 PDF との照合 | PDF なし（照合していない） |" in res.report_path.read_text(encoding="utf-8")


def _plan(journal):
    return _mechanical(PDFCHECK, journal)[1]


def test_compare_keeps_links_spaces_and_reports_missing(journal):
    plan = _plan(journal)
    pages = ["本研究は架空理論（Fictional Theory, 以下，FT）に基づく（試験，2020；見本，2021）。\n"
             # URL の文字は、PDF で全角になっていても変えない（表示とリンク先がずれないように）
             "この段落は出版版と同じで，架空の資料を ｈｔｔｐｓ://example.com/a で公開している。\n"
             "（1）方法の概要\n"
             "This abstract is the same in the published version.\n"]
    pc = compare(plan, pages)
    assert "d15" not in pc.width                          # URL の段落
    assert pc.width["d12"] and pc.width["d14"]
    # 英文の単語の間の空白は落とさない（英文要旨は出版版と同じなので変更なし）
    abstract = next(p.src for p in plan.abstract)
    assert abstract not in pc.width and abstract not in pc.drops
    # PDF にない段落は「見つからない」に（変更もしない）
    assert "d13" in pc.unmatched and "d17" in pc.unmatched and "d13" not in pc.width
    assert pc.edits.keys() == pc.width.keys() | pc.drops.keys()
    assert compare(plan, pages, apply=False).edits == {}


def test_compare_without_text(journal):
    pc = compare(_plan(journal), ["", "\n"])
    assert not pc.ok and "文字を取り出せなかった" in pc.message


def test_wrong_pdf_changes_nothing(journal, meta, tmp_path):
    """別の記事の PDF なら、段落が見つからないだけで、文字は変えない。"""
    pytest.importorskip("pypdfium2")
    from conftest import NOTES
    res = convert(NOTES, meta, journal, Options(out_dir=tmp_path, pdf_path=PDFCHECK_PDF, convert_metafiles=False))
    pc = res.pdf_check
    assert pc.edits == {} and pc.diffs == [] and pc.unmatched and res.fidelity.pdf_width == []
    assert "別の記事の PDF ではないか確認" in res.report_path.read_text(encoding="utf-8")


def test_word_footnote_numbers_follow_pdf(journal, meta, tmp_path, monkeypatch):
    """Word の脚注番号（docx の文字ではなくツールが作る文字）も、全角・半角を PDF に合わせる。"""
    from conftest import EDGE
    from jasme_jats import pdfmatch
    pages = ["Word の脚注1）が付いた文。\n１）Word の脚注機能で付けた注です。\n"]
    monkeypatch.setattr(pdfmatch, "extract_pages", lambda path: pages)
    (tmp_path / "dummy.pdf").write_bytes(b"%PDF-1.4\n")    # ZIP に入れるだけ（文字は extract_pages の代わりから）
    res = convert(EDGE, meta, journal, Options(out_dir=tmp_path, pdf_path=tmp_path / "dummy.pdf", convert_metafiles=False))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    root = load(res)
    x = next(x for x in root.iter("xref") if x.get("ref-type") == "fn")
    assert "".join(x.itertext()) == "1）"
    # 注の一覧: 番号を PDF に合わせ、docx の記号の後の空白も PDF にないので落とす（番号の後に空白を補わない）
    assert "".join(root.find(".//fn/p").itertext()) == "１）Word の脚注機能で付けた注です。"
    assert res.pdf_check.number_edits == {("fnref", "5"): "1）", ("fnlist", "5"): "１）"}
    report = res.report_path.read_text(encoding="utf-8")
    assert "| 注の一覧の脚注番号 | Word の脚注 5 | 「1)」→「１）」 |" in report
    # 設定で切ると、Word の番号も設定 fn_mark のまま
    res = convert(EDGE, meta, journal, Options(out_dir=tmp_path / "off", pdf_path=tmp_path / "dummy.pdf", pdf_width=False,
                                               convert_metafiles=False))
    assert "".join(load(res).find(".//fn/p").itertext()) == "1) Word の脚注機能で付けた注です。"


def test_autonum_follows_pdf(journal):
    """段落の自動番号（Word の自動段落番号）も、全角・半角を PDF に合わせる。"""
    plan = _plan(journal)
    plan.paras["d14"].autonum = "1. "              # 自動番号の付いた見出しとみなす
    pages = ["本研究は架空理論（Fictional Theory, 以下，FT）に基づく（試験，2020；見本，2021）。\n"
             "１．（1）方法の概要\n"]
    pc = compare(plan, pages)
    assert pc.number_edits == {("auto", "d14"): "１． "}   # 番号の後ろの空白はそのまま
    assert compare(plan, pages, apply=False).number_edits == {}
