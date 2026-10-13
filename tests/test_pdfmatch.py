"""出版版 PDF との照合（pdfmatch.py）と、PDF に合わせて直した docx（pdfdocx.py）。

tests/fixtures/sample_pdfcheck.pdf は、sample_pdfcheck.docx の文字を出版社が組版で直した想定（全角のかっこ・句読点、
「資料」→「付録」など）にして LibreOffice で PDF にしたもの（tests/make_fixtures.py）。

  ルート1（docx から作る）: docx の文字は変えない。照合の結果をレポートに載せるだけ
  ルート2（出版版 PDF に合わせてから作る）: PDF に合わせて直した docx（変更履歴つき）を作り、それを変換する
"""
import zipfile

import pytest
from lxml import etree

from conftest import PDFCHECK, PDFCHECK_PDF
from jasme_jats.ooxml import parse_xml, w
from jasme_jats.pdfdocx import AUTHOR, Fix, _apply_paragraph, _Writer, paragraph_units, plan_fixes, tracked_counts
from jasme_jats.pdfmatch import PdfCheck, TextDiff, compare, is_width_pair
from jasme_jats.pipeline import Options, _mechanical, convert

ORIGINAL = {    # docx の文字（ルート1 の XML はこのまま）
    "d12": "本研究は架空理論 (Fictional Theory, 以下, FT) に基づく (試験, 2020; 見本, 2021)。",
    "d13": "詳しくは資料の学習指導案を参照されたい。授業は2回行った。",
    "d14": "(1) 方法の概要",
    "d17": "試験四郎 (2020). 「架空の研究」. 『架空誌』, 第1巻, pp.1-10.",
}
PUBLISHED = {   # 出版社が直した想定の文字（ルート2 の XML はこうなる）
    "d12": "本研究は架空理論（Fictional Theory, 以下，FT）に基づく（試験，2020；見本，2021）。",
    "d13": "詳しくは付録の学習指導案を参照されたい。授業は２回行った。",
    "d14": "（1）方法の概要",
    "d17": "試験四郎（2020）．「架空の研究」．『架空誌』，第1巻，pp.1-10．",
}


def load(res):
    return etree.fromstring(res.xml_path.read_bytes().split(b"\n", 2)[2])


def texts(root):
    return ["".join(x.itertext()) for x in root.iter("p", "title", "mixed-citation")]


def paragraphs(docx, reject=False):
    """docx の本文の段落の文字。reject=True なら、このツールの変更履歴をすべて却下した文字（挿入を除き、削除を戻す）。"""
    root = parse_xml(zipfile.ZipFile(docx).read("word/document.xml"))
    out = []
    for p in root.iter(w("p")):
        s = []
        for t in p.iter(w("t"), w("delText")):
            mark = next((a for a in t.iterancestors(w("ins"), w("del"))), None)
            ours = mark is not None and mark.get(w("author")) == AUTHOR
            if t.tag == w("t") and not (reject and ours and mark.tag == w("ins")):
                s.append(t.text or "")
            elif t.tag == w("delText") and reject and ours:
                s.append(t.text or "")
        out.append("".join(s))
    return out


def test_width_pairs():
    assert is_width_pair("(", "（") and is_width_pair("２", "2") and is_width_pair("a", "ａ")
    assert not is_width_pair("〜", "~") and not is_width_pair("−", "－") and not is_width_pair("資", "付")
    assert not is_width_pair(" ", "　")


def test_route1_reports_without_changing_text(journal, meta, tmp_path):
    """ルート1: docx の文字は 1 文字も変えず、PDF との違いはレポートに載せるだけ。"""
    pytest.importorskip("pypdfium2")
    res = convert(PDFCHECK, meta, journal, Options(out_dir=tmp_path, pdf_path=PDFCHECK_PDF, convert_metafiles=False))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    assert res.route == "docx" and res.docx_fix is None and not list(tmp_path.glob("*.docx"))
    pc = res.pdf_check
    assert pc.ok and pc.unmatched == []
    assert [(d.src, d.docx, d.pdf) for d in pc.diffs] == [("d13", "資料", "付録")]
    assert pc.width_count == 25 and pc.drop_count == 18
    out = texts(load(res))
    for want in ORIGINAL.values():
        assert want in out
    report = res.report_path.read_text(encoding="utf-8")
    head = report.split("## 2.")[0]
    assert "作り方: docx から作る" in head
    assert "要確認: 出版版 PDF と文字が違う箇所が 1 件、全角・半角の違いが 25 文字あります" in head
    assert "XML は docx の文字のままで、照合の結果を載せているだけです" in report
    assert "| d13 |" in report and "| 資料 | 付録 |" in report
    assert "「(→（」5 件" in report and "「架空理論 (Fict」→「架空理論（Fict」" in report
    assert "出版版 PDF との違い**（文字の違い 1 件・全角・半角の違い 25 文字）" in report.split("## 14.")[1]


def test_route2_fixes_docx_with_tracked_changes(journal, meta, tmp_path):
    """ルート2: PDF に合わせて直した docx（変更履歴つき）を作り、それを変換する。"""
    pytest.importorskip("pypdfium2")
    before = PDFCHECK.read_bytes()
    res = convert(PDFCHECK, meta, journal, Options(out_dir=tmp_path, pdf_path=PDFCHECK_PDF, route="pdf",
                                                   convert_metafiles=False))
    assert PDFCHECK.read_bytes() == before                  # 元の docx は変えない
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    fx = res.docx_fix
    assert res.route == "pdf" and fx.path.exists() and fx.path.parent == tmp_path
    assert res.docx_name == PDFCHECK.name
    # 全角・半角、その前後の空白、「資料」→「付録」をすべて直す（URL の段落・英文要旨は出版版と同じなので直さない）
    assert len(fx.applied) == 44 and fx.skipped == [] and fx.unmatched == []
    assert {f.kind for f in fx.applied} == {"width", "space", "text"}
    assert [(f.src, f.old, f.new) for f in fx.applied if f.kind == "text"] == [("d13", "資料", "付録")]
    out = texts(load(res))
    for want in PUBLISHED.values():
        assert want in out
    assert any("https://example.com/a で公開している" in t for t in out)
    root = load(res)
    assert {x.text for x in root.iter("xref") if x.get("ref-type") == "bibr"} >= {"2020", "2021"}
    # 直した docx をもう一度照合すると、違いは残っていない
    assert res.pdf_check.diffs == [] and res.pdf_check.width_count == 0
    # 変更履歴: 承諾した文字が PDF の文字、却下すると元の docx の文字に戻る
    assert tracked_counts(fx.path) == (26, 40)
    assert paragraphs(fx.path, reject=True) == paragraphs(PDFCHECK)
    assert PUBLISHED["d12"] in paragraphs(fx.path)
    report = res.report_path.read_text(encoding="utf-8")
    head = report.split("## 2.")[0]
    assert "作り方: 出版版 PDF に合わせてから作る" in head
    assert "PDF に合わせて docx を直した 44 箇所（変更履歴: 挿入 26・削除 40）" in head
    assert f"照合の相手は、出版版 PDF に合わせて直した docx（{fx.path.name}）" in head
    assert "「詳しくは資料の学習指」→「詳しくは付録の学習指」" in report
    assert "### 13.2 PDF と違うが直さなかった箇所（要確認）\n\nありません。" in report
    assert "Word で開き、変更履歴を確認する" in report.split("## 14.")[1]


def test_route2_needs_pdf(journal, meta, tmp_path):
    with pytest.raises(ValueError, match="PDF が必要"):
        convert(PDFCHECK, meta, journal, Options(out_dir=tmp_path, route="pdf", convert_metafiles=False))


def test_no_pdf_means_no_check(journal, meta, tmp_path):
    res = convert(PDFCHECK, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    assert res.pdf_check is None
    assert "| 出版版 PDF との照合 | PDF なし（照合していない） |" in res.report_path.read_text(encoding="utf-8")


def _plan(journal):
    return _mechanical(PDFCHECK, journal)[1]


def test_compare_keeps_links_spaces_and_reports_missing(journal):
    plan = _plan(journal)
    pages = ["本研究は架空理論（Fictional Theory, 以下，FT）に基づく（試験，2020；見本，2021）。\n"
             # URL の文字は、PDF で全角になっていても直さない（表示とリンク先がずれないように）
             "この段落は出版版と同じで，架空の資料を ｈｔｔｐｓ://example.com/a で公開している。\n"
             "（1）方法の概要\n"
             "This abstract is the same in the published version.\n"]
    pc = compare(plan, pages)
    assert "d15" not in pc.width                          # URL の段落
    assert pc.width["d12"] and pc.width["d14"]
    # 英文の単語の間の空白は落とさない（英文要旨は出版版と同じなので違いなし）
    abstract = next(p.src for p in plan.abstract)
    assert abstract not in pc.width and abstract not in pc.drops
    # PDF にない段落は「見つからない」に（直さない）
    assert "d13" in pc.unmatched and "d17" in pc.unmatched and "d13" not in pc.width


def test_compare_without_text(journal):
    pc = compare(_plan(journal), ["", "\n"])
    assert not pc.ok and "文字を取り出せなかった" in pc.message


def test_wrong_pdf_changes_nothing(journal, meta, tmp_path):
    """別の記事の PDF なら、段落が見つからないだけで、ルート2 でも docx の文字は直さない。"""
    pytest.importorskip("pypdfium2")
    from conftest import NOTES
    res = convert(NOTES, meta, journal, Options(out_dir=tmp_path, pdf_path=PDFCHECK_PDF, route="pdf",
                                                convert_metafiles=False))
    fx, pc = res.docx_fix, res.pdf_check
    assert fx.applied == [] and fx.unmatched and tracked_counts(fx.path) == (0, 0)
    assert pc.diffs == [] and pc.unmatched and res.fidelity.ok
    assert paragraphs(fx.path) == paragraphs(NOTES)
    assert "別の記事の PDF ではないか確認" in res.report_path.read_text(encoding="utf-8")


def test_word_footnote_numbers_follow_pdf(journal, meta, tmp_path, monkeypatch):
    """Word の脚注番号（docx の文字ではなくツールが作る文字）は、ルート2 では変換のときに全角・半角を PDF に合わせる。"""
    from conftest import EDGE
    from jasme_jats import pdfmatch
    pages = ["Word の脚注1）が付いた文。\n１）Word の脚注機能で付けた注です。\n"]
    monkeypatch.setattr(pdfmatch, "extract_pages", lambda path: pages)
    (tmp_path / "dummy.pdf").write_bytes(b"%PDF-1.4\n")    # ZIP に入れるだけ（文字は extract_pages の代わりから）
    res = convert(EDGE, meta, journal, Options(out_dir=tmp_path / "pdf", pdf_path=tmp_path / "dummy.pdf", route="pdf",
                                               convert_metafiles=False))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    root = load(res)
    x = next(x for x in root.iter("xref") if x.get("ref-type") == "fn")
    assert "".join(x.itertext()) == "1）"
    # 注の一覧: 番号を PDF に合わせ、docx の記号の後の空白も PDF にないので直した docx で消す（番号の後に空白を補わない）
    assert "".join(root.find(".//fn/p").itertext()) == "１）Word の脚注機能で付けた注です。"
    assert res.pdf_check.number_edits == {("fnref", "5"): "1）", ("fnlist", "5"): "１）"}
    assert [(f.src, f.kind) for f in res.docx_fix.applied] == [("f3", "space")]   # 脚注 5 の段落
    report = res.report_path.read_text(encoding="utf-8")
    assert "| 注の一覧の脚注番号 | Word の脚注 5 | 「1)」→「１）」 |" in report
    # ルート1 では、Word の番号も設定 fn_mark のまま（違いはレポートに載せるだけ）
    res = convert(EDGE, meta, journal, Options(out_dir=tmp_path / "docx", pdf_path=tmp_path / "dummy.pdf",
                                               convert_metafiles=False))
    assert "".join(load(res).find(".//fn/p").itertext()) == "1) Word の脚注機能で付けた注です。"
    report = res.report_path.read_text(encoding="utf-8")
    assert "| 注の一覧の脚注番号 | Word の脚注 5 | 「1)」→「１）」 |" in report


def test_autonum_follows_pdf(journal):
    """段落の自動番号（Word の自動段落番号）も、PDF と全角・半角を照合する。"""
    plan = _plan(journal)
    plan.paras["d14"].autonum = "1. "              # 自動番号の付いた見出しとみなす
    pages = ["本研究は架空理論（Fictional Theory, 以下，FT）に基づく（試験，2020；見本，2021）。\n"
             "１．（1）方法の概要\n"]
    pc = compare(plan, pages)
    assert pc.number_edits == {("auto", "d14"): "１． "}   # 番号の後ろの空白はそのまま


def test_plan_fixes_keeps_docx_spaces(journal):
    """文字の違いを直すとき、docx の空白は消さない（PDF の空白は信頼できない）。数式などにかかる違いは直さない。"""
    plan = _plan(journal)
    text = plan.paras["d13"].plain()
    a = text.index("資料")
    check = PdfCheck(diffs=[TextDiff("d13", "資料の", "付録の", "", a, a + 3),
                            TextDiff("d12", "x", "y", "", 0, 1, fixable=False)])
    fixes = plan_fixes(plan, check)
    assert [(f.src, f.start, f.end, f.old, f.new, f.reason) for f in fixes if f.src == "d13"] == [
        ("d13", a, a + 2, "資料", "付録", "")]
    assert [f.reason for f in fixes if f.src == "d12"] == ["数式・Word が付ける番号・リンクの文字にかかる、または足す位置を決められない"]
    space = PdfCheck(diffs=[TextDiff("d12", " (", "（", "", 8, 10)])
    assert [(f.start, f.end, f.old, f.new) for f in plan_fixes(plan, space)] == [(9, 10, "(", "（")]


def test_tracked_changes_keep_run_format():
    """直すランの書式（太字など）は、そのままの文字・削除・挿入のどのランにも残す。"""
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    p = etree.fromstring(f'<w:p xmlns:w="{ns}"><w:r w:rsidR="00A1"><w:rPr><w:b/></w:rPr><w:t>ab(c)</w:t></w:r>'
                         '<w:r><w:tab/><w:t>d</w:t></w:r></w:p>')
    units = paragraph_units(p)
    assert "".join(c for c, _, _ in units) == "ab(c)\td"
    fixes = [Fix("d1", 2, 3, "（", "width", "("), Fix("d1", 4, 5, "）", "width", ")"),
             Fix("d1", 5, 6, "", "space", "\t")]
    _apply_paragraph(units, fixes, _Writer("2026-01-01T00:00:00Z"))
    assert [f.applied for f in fixes] == [True, True, False]       # タブは直せない
    assert "タブ" in fixes[2].reason
    runs = []
    for el in p[:-1]:
        kind = {w("ins"): "ins", w("del"): "del"}.get(el.tag, "keep")
        r = el if kind == "keep" else el.find(w("r"))
        if kind != "keep":
            assert el.get(w("author")) == AUTHOR and el.get(w("id")) and el.get(w("date")) == "2026-01-01T00:00:00Z"
        assert r.get(w("rsidR")) == "00A1"
        bold = r.find(f"{w('rPr')}/{w('b')}") is not None
        runs.append((kind, r.find(w("delText") if kind == "del" else w("t")).text, bold))
    assert runs == [("keep", "ab", True), ("del", "(", True), ("ins", "（", True), ("keep", "c", True),
                    ("del", ")", True), ("ins", "）", True)]
    assert p[-1].find(w("tab")) is not None and p[-1].find(w("t")).text == "d"     # 直さないランはそのまま


def test_colab_box_and_cli_route(journal, meta, tmp_path, capsys):
    """Colab の赤い枠と、コマンドラインの --route。"""
    pytest.importorskip("pypdfium2")
    from jasme_jats.cli import main
    from jasme_jats.colab import pdf_diff_box
    res = convert(PDFCHECK, meta, journal, Options(out_dir=tmp_path / "1", pdf_path=PDFCHECK_PDF, convert_metafiles=False))
    html = pdf_diff_box(res)
    assert "#dc2626" in html and "出版版 PDF と文字が違う箇所が 1 件、全角・半角の違いが 25 文字あります" in html
    assert "XML は docx の文字のまま" in html and "出版版 PDF に合わせてから作る" in html
    res = convert(PDFCHECK, meta, journal, Options(out_dir=tmp_path / "2", pdf_path=PDFCHECK_PDF, route="pdf",
                                                   convert_metafiles=False))
    assert pdf_diff_box(res) == ""                 # すべて直せて、残っている違いもない
    f = res.docx_fix.applied[0]
    f.applied, f.reason = False, "ほかの直す箇所と重なる"
    html = pdf_diff_box(res)
    assert "直せなかった箇所 1 件" in html and "ほかの直す箇所と重なる" in html and res.docx_fix.path.name in html

    with pytest.raises(SystemExit):
        main([str(PDFCHECK), "--out", str(tmp_path / "c"), "--route", "pdf"])
    assert "--pdf で記事の PDF を指定してください" in capsys.readouterr().err
    assert main([str(PDFCHECK), "--out", str(tmp_path / "c"), "--route", "pdf", "--pdf", str(PDFCHECK_PDF),
                 "--no-metafile-conversion"]) == 0
    out = capsys.readouterr().out
    assert "出版版 PDF との照合: PDF に合わせて docx を直した 44 箇所" in out
    assert "PDF に合わせて直した docx（変更履歴つき）:" in out and "_PDFに合わせた原稿.docx" in out


def test_route2_keeps_note_marks_when_fixing_breaks_notes(journal, meta, tmp_path, monkeypatch):
    """直すと注を認識できなくなる（本文の「（注1）」が PDF では上付きの「1）」）ときは、すべての注の番号を docx のままにする。"""
    from conftest import NOTES
    from jasme_jats import pdfmatch
    from jasme_jats.pdfdocx import NOTE_REASON
    pages = ["本文の大きさで書いた注番号1）と，角括弧の注番号［注2］がある文。\n"
             "箇条の番号（1）と（2）は注へのリンクにしない。2 段落からなる注3）もある。\n"
             "注\n１）本文の大きさで書かれた注番号の注である。\n［注2］角括弧で書かれた注番号の注である。\n"
             "３）2 段落からなる注の 1 段落目である。\n"]
    monkeypatch.setattr(pdfmatch, "extract_pages", lambda path: pages)
    (tmp_path / "dummy.pdf").write_bytes(b"%PDF-1.4\n")
    res = convert(NOTES, meta, journal, Options(out_dir=tmp_path, pdf_path=tmp_path / "dummy.pdf", route="pdf",
                                                convert_metafiles=False))
    assert res.fidelity.ok and res.dtd_valid
    fx = res.docx_fix
    kept = [f for f in fx.skipped if f.reason == NOTE_REASON]
    assert {f.src for f in kept} == {"d12", "d13", "d18", "d20"} and len(fx.skipped) == len(kept)
    assert {(f.src, f.old) for f in kept} >= {("d12", "（注"), ("d13", "（注"), ("d18", "1"), ("d20", "3")}
    # 注の番号以外（箇条の番号の全角・半角など）は直す
    assert ("d13", "(", "（") in {(f.src, f.old, f.new) for f in fx.applied}
    root = load(res)
    assert ["".join(x.itertext()) for x in root.iter("xref") if x.get("ref-type") == "fn"] == ["（注1）", "［注2］", "（注3）"]
    assert len(root.findall(".//fn")) == 3
    assert "注の番号（直すと注を認識できなくなるので" in res.report_path.read_text(encoding="utf-8")


def test_route2_with_unreadable_pdf_converts_original(journal, meta, tmp_path, monkeypatch):
    """PDF の文字を読めなければ、docx を直さずに変換する（直した docx は作らない）。"""
    from jasme_jats import pdfmatch
    monkeypatch.setattr(pdfmatch, "extract_pages", lambda path: ["", "\n"])
    (tmp_path / "dummy.pdf").write_bytes(b"%PDF-1.4\n")
    res = convert(PDFCHECK, meta, journal, Options(out_dir=tmp_path, pdf_path=tmp_path / "dummy.pdf", route="pdf",
                                                   convert_metafiles=False))
    assert res.fidelity.ok and res.docx_fix is None and not list(tmp_path.glob("*.docx"))
    assert ORIGINAL["d12"] in texts(load(res))
    report = res.report_path.read_text(encoding="utf-8")
    assert "（PDF の文字を読めなかったので、docx を直さずに変換した）" in report
    assert "照合できなかった" in report.split("## 2.")[0]


def test_route2_keeps_reference_when_fixing_breaks_citation(journal, meta, tmp_path, monkeypatch):
    """引用文献の著者名を PDF に合わせると本文の引用（「試験, 2020」）と照合できなくなるときは、その文献の段落を直さない。"""
    from jasme_jats import pdfmatch
    from jasme_jats.pdfdocx import STRUCTURE_REASON
    pages = [PUBLISHED["d12"] + "\n" + PUBLISHED["d13"] + "\n" + PUBLISHED["d14"] + "\n引用および参考文献\n"
             + PUBLISHED["d17"].replace("試験四郎", "試行四郎") + "\n"
             + "見本花子（2021）．「見本の研究」．『見本誌』，第2巻，pp.11-20．\n"]
    monkeypatch.setattr(pdfmatch, "extract_pages", lambda path: pages)
    (tmp_path / "dummy.pdf").write_bytes(b"%PDF-1.4\n")
    res = convert(PDFCHECK, meta, journal, Options(out_dir=tmp_path, pdf_path=tmp_path / "dummy.pdf", route="pdf",
                                                   convert_metafiles=False))
    fx = res.docx_fix
    assert {f.src for f in fx.skipped} == {"d17"} and {f.reason for f in fx.skipped} == {STRUCTURE_REASON}
    assert ("d17", "験", "行") in {(f.src, f.old, f.new) for f in fx.skipped}
    out = texts(load(res))
    assert PUBLISHED["d12"] in out and ORIGINAL["d17"] in out     # 引用のある段落は直し、文献の段落は docx のまま
    assert {x.text for x in load(res).iter("xref") if x.get("ref-type") == "bibr"} == {"2020", "2021"}
