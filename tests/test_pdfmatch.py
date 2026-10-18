"""出版版 PDF との照合（pdfmatch.py）と、PDF に合わせて直した docx（pdfdocx.py）。

tests/fixtures/sample_pdfcheck.pdf は、sample_pdfcheck.docx の文字を出版社が組版で直した想定（全角のかっこ・句読点、
「資料」→「付録」など）にして LibreOffice で PDF にしたもの（tests/make_fixtures.py）。

  ルート1（docx から作る）: docx の文字は変えない。照合の結果をレポートに載せるだけ
  ルート2（出版版 PDF に合わせてから作る）: PDF に合わせて直した docx（変更履歴つき）を作り、それを変換する

ページ番号・柱・投稿受付日など（組版で入り、docx にない文字）の扱いは、extract_pages の代わりに作った PDF の文字
（d12_pages など。形だけを本誌の出版版 PDF にまねた架空の文字）で確かめる。
"""
import zipfile

import pytest
from lxml import etree

import make_fixtures as mf
from conftest import PDFCHECK, PDFCHECK_PDF
from jasme_jats.ooxml import parse_xml, w
from jasme_jats.pdfdocx import AUTHOR, Fix, _apply_paragraph, _Writer, paragraph_units, plan_fixes, tracked_counts
from jasme_jats.pdfmatch import LINE_MARK, PdfCheck, TextDiff, compare, is_width_pair
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
    # --pdf があれば、既定は「出版版 PDF に合わせてから作る」
    assert main([str(PDFCHECK), "--out", str(tmp_path / "c"), "--pdf", str(PDFCHECK_PDF), "--no-metafile-conversion"]) == 0
    out = capsys.readouterr().out
    assert "出版版 PDF との照合: PDF に合わせて docx を直した 44 箇所" in out
    assert "PDF に合わせて直した docx（変更履歴つき）:" in out and "_PDFに合わせた原稿.docx" in out
    assert main([str(PDFCHECK), "--out", str(tmp_path / "d"), "--pdf", str(PDFCHECK_PDF), "--route", "docx",
                 "--no-metafile-conversion"]) == 0
    out = capsys.readouterr().out
    assert "出版版 PDF との照合: 文字の違い 1 件" in out and "PDF に合わせて直した docx" not in out


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


# ---------------------------------------------------------------------------- ページ番号・柱・投稿受付日（U7・N9）
# 出版版 PDF の文字を、d12 の途中（「基づく」の前）でページが変わる形にして作る（extract_pages の代わり）。
# ページ番号・柱・投稿受付日などは docx にない（組版で入る）文字なので、段落の途中にあっても、docx に足さない
PUB12 = PUBLISHED["d12"]
CUT = PUB12.index("基づく")
FRONT = ["全国数学教育学会誌　数学教育学研究　第31巻　第１号　2026　pp.1～2", "出版版 PDF との照合の検証用文書",
         "―全角と半角の違い―", "架空大学　試験　四郎", "１．はじめに"]
REST = [PUBLISHED["d13"], PUBLISHED["d14"], "引用および参考文献", PUBLISHED["d17"],
        "見本花子（2021）．「見本の研究」．『見本誌』，第2巻，pp.11-20．"]


def d12_pages(end1=(), start2=(), top1="（1）", top2="（2）", first=PUB12[:CUT], second=PUB12[CUT:], rest=REST):
    """1 ページ目の最後が d12 の前半（first）、2 ページ目の最初が後半（second）。end1・start2 はその間に入る行。"""
    page1 = [top1, *FRONT, first, *end1]
    page2 = [top2, *start2, second, *rest]
    return ["\n".join(x for x in page1 if x), "\n".join(x for x in page2 if x)]


def d12_result(journal, pages):
    """照合の結果と、d12 の違い・直す箇所（全角・半角と空白以外）。"""
    plan = _plan(journal)
    pc = compare(plan, pages)
    return (pc, [(d.docx, d.pdf, d.fixable) for d in pc.diffs if d.src == "d12"],
            [(f.old, f.new, f.reason) for f in plan_fixes(plan, pc) if f.src == "d12" and f.kind == "text"])


@pytest.mark.parametrize("pages, ignored", [
    (d12_pages(start2=["試験四郎"]), ["試験四郎"]),                      # 8 文字未満の柱（著者名）がページの最初の行
    (d12_pages(end1=["試験四郎"]), ["試験四郎"]),                        # 柱がページの最後の行
    (d12_pages(top1="（1）\n架空の論文の柱の文字列です", start2=["架空の論文の柱の文字列です"]),
     ["架空の論文の柱の文字列です"]),                                     # 2 ページの記事の柱（2 ページにしか出ない）
    (d12_pages(top1="", end1=["－ 1 －"], top2="", rest=[*REST, "－ 2 －"]), []),     # ページの最後の行のページ番号
    (d12_pages(top1="", end1=["- 1 -"], top2="", rest=[*REST, "- 2 -"]), []),
], ids=["short-head-top", "short-head-bottom", "two-page-head", "page-no-dash-fw", "page-no-dash"])
def test_running_heads_and_page_numbers_are_not_inserted(journal, pages, ignored):
    """段落の途中のページの区切りにある柱・ページ番号は、違いにならず、ルート2 でも docx に足さない。"""
    pc, diffs, fixes = d12_result(journal, pages)
    assert diffs == [] and fixes == []
    assert [(d.src, d.docx, d.pdf) for d in pc.diffs] == [("d13", "資料", "付録")]
    # ページ番号は列から除き（記録しない）、柱とみなした行は、段落の違いの範囲にあったものを記録する
    assert pc.ignored_lines == [("d12", x) for x in ignored]


R1 = "2025年８月31日投稿受付，2025年11月24日採用決定"
R2A, R2B = "2025年２月27日投稿受付，2025年７月30日再投稿受付，", "2025年10月10日採用決定"
R1A, R1B = "2025年８月31日投稿受付，", "2025年11月24日採用決定"         # R1 を 2 つに分けたもの


@pytest.mark.parametrize("pages, ignored, want", [
    # 本文の行の前につながる（ページの最後の行。その行の後ろは d12 の続き）
    (d12_pages(end1=[R1 + " " + PUB12[CUT:CUT + 3]], second=PUB12[CUT + 3:]), R1, []),
    # 同じ形で、すぐ後ろの本文が出版版で直っている（「基づく」→「もとづく」）。違いは本文の直しだけ
    (d12_pages(end1=[R1 + " もとづく"], second=PUB12[CUT + 3:]), R1, [("基", "もと", True)]),
    # 受付日の行だけがページの最後にある
    (d12_pages(end1=[R1]), R1, []),
    # ページの途中で、本文の行の後ろにつながり、次の行にわたる（その後に d12 の続き。ページの端の行ではない）
    (d12_pages(first=PUB12[:CUT] + " " + R2A, end1=[R2B, PUB12[CUT:], *REST[:2]], second="", rest=REST[2:]),
     R2A + R2B, []),
    # ページの最後の 2 行（本文の行の後ろにつながり、次の行にわたる）
    (d12_pages(first=PUB12[:CUT] + " " + R2A, end1=[R2B]), R2A + R2B, []),
    # 古い形（ページの途中の行）
    (d12_pages(end1=["（2025.11.30受理）", PUB12[CUT:], *REST[:2]], second="", rest=REST[2:]), "（2025.11.30受理）", []),
], ids=["after-line", "after-line-fixed", "own-line", "mid-page-2-lines", "last-2-lines", "old-form"])
def test_received_dates_are_not_inserted(journal, pages, ignored, want):
    """投稿受付・採用決定の日付（組版で入る）は、段落の途中のどこにあっても、違いにならず、docx に足さない。"""
    pc, diffs, fixes = d12_result(journal, pages)
    assert diffs == want and fixes == [(old, new, "") for old, new, _ in want]
    assert pc.ignored_lines == [("d12", ignored)]        # 段落の違いの範囲にあったものを 1 回だけ記録する


def test_received_date_pattern():
    """投稿受付日などの形（RE_RECEIVED。本誌の出版版 PDF の形をまねた架空の日付）。行をまたいでもよい。かっこのない
    「受付」「受理」は本文の日付にも当たるので、かっこ付きの古い形でだけ認める。"""
    from jasme_jats.pdfmatch import RE_RECEIVED

    def found(s):
        return [m.group() for m in RE_RECEIVED.finditer(s)]
    assert found("本文の行の後ろ " + R1 + " 本文の続き") == [R1]
    assert found(R2A + "\n" + R2B + "\n図１　架空の図") == [R2A + "\n" + R2B]
    assert found("（2025.11.30受理）") == ["（2025.11.30受理）"]
    assert found("（2025年11月30日受理）") == ["（2025年11月30日受理）"]
    assert found("２０２５年１月５日投稿受付") == ["２０２５年１月５日投稿受付"]
    assert found("2025年８月31日に投稿した。（2025.11.30）") == []
    assert found("申込みは2025年８月30日受付分までとし，論文は2025年3月1日受理された。") == []
    # 日付の並びの最後の区切り（「，」）は、日付のすぐ後ろの 1 文字だけ含める（その後ろの本文の読点は含めない）
    assert found("本文の行 " + R1A + "\n本文の続きの行") == [R1A]
    assert found(R1 + " ，本文の続き") == [R1]
    assert found("2025年８月31日に投稿した，本文") == []


def test_received_dates_joined_to_two_body_lines(journal):
    """2 行の受付日の両方が、それぞれ別の本文の行の後ろにつながる（「本文…2025年８月31日投稿受付，」「本文…2025年11月24日
    採用決定」）。1 つ目の日付の後ろの「，」も受付日の文字として照合に使わず、docx に足さない。"""
    pages = d12_pages(first=PUB12[:CUT] + " " + R1A, end1=[PUB12[CUT:CUT + 3] + " " + R1B, PUB12[CUT + 3:], *REST[:2]],
                      second="", rest=REST[2:])
    pc, diffs, fixes = d12_result(journal, pages)
    assert diffs == [] and fixes == []
    assert pc.ignored_lines == [("d12", R1A), ("d12", R1B)]


def test_page_number_only_at_page_edge():
    """N9: ページ番号として除くのは、ページの最初か最後の行の数字だけの行（1 ページに 1 つ）。ページの途中の数字だけの行
    （引用文献の「pp.11-」の後の「16」、表のセル）は列から除かない（柱の候補の行にする。test_line_marks）。"""
    from jasme_jats.pdfmatch import pdf_stream
    st = pdf_stream(["（25）\n最初の行です。\n2 行目です。\n27\n途中の行です。\n最後から 2 行目です。\n最後の行です。\n"])
    assert "".join(st.chars) == "最初の行です。2行目です。27途中の行です。最後から2行目です。最後の行です。"   # ページ番号を除く
    # 最初の行がページ番号なら、最後の数字だけの行は除かない（引用文献の「16」のことがある）。最初の行がページ番号で
    # なければ、最後の行のページ番号を除く
    st = pdf_stream(["（25）\n本文の行です。\n16", "本文の行です。\n（26）"])
    assert "".join(st.chars) == "本文の行です。16本文の行です。"


REF16 = "架空太郎（2019）．「架空の題目」．『架空学会誌』，第29号，pp.11-16"
BODY16 = "本文の段落の途中に，表の数字だけの行が入る場合を確かめる。"
SMALL_FRONT = ["ページ番号の判定の検証用文書", "―検証用の小さな論文―", "架空大学　試験　六郎", "１．はじめに"]
SMALL_REF = "試験六郎（2024）．「小さな論文」．『架空誌』，第5巻，pp.9-10．"
SMALL_EN = ["A Small Article", "For Checking", "Rokuro SHIKEN", "Fictional University", "Abstract", "Small article abstract."]


def small_article(tmp_path, journal, body, *refs):
    """make_fixtures.make_article の小さな論文（本文 1 段落。引用文献 SMALL_REF の後ろに refs を足す）の構造と、
    段落の文字 -> 段落 ID。PDF の文字は SMALL_FRONT・SMALL_REF・SMALL_EN と組み合わせて作る。"""
    mf.make_article(tmp_path / "small.docx", "ページ番号の判定の検証用文書",
                    lambda b: [mf.para(mf.S["sec1"], "１．はじめに"), mf.para(mf.S["body"], body)],
                    refs=lambda b: [mf.para(mf.S["ref"], r) for r in refs])
    _, plan, _ = _mechanical(tmp_path / "small.docx", journal)
    return plan, {p.plain(): p.src for p in plan.paras.values()}


def test_digit_lines_in_middle_of_page(journal, tmp_path):
    """N9: ページの途中の数字だけの行は、ページ番号として除かない。どの段落にも当たらない行（表のセル）は照合に使わず、
    段落に当たる行（引用文献の「pp.11-」の後の「16」）は照合に使う（ルート2 で docx の「16」を消さない）。"""
    plan, src = small_article(tmp_path, journal, BODY16, REF16)
    pages = ["\n".join(["（1）", *SMALL_FRONT, BODY16[:12], "27", "16", "14", BODY16[12:], "引用および参考文献", SMALL_REF,
                        REF16[:-2], REF16[-2:], *SMALL_EN[:3]]),
             "\n".join(["（2）", *SMALL_EN[3:]])]
    pc = compare(plan, pages)
    assert pc.unmatched == [] and pc.diffs == [] and plan_fixes(plan, pc) == []
    assert pc.ignored_lines == [(src[BODY16], "27"), (src[BODY16], "16"), (src[BODY16], "14")]
    # 「16」がページの最後の行でも、ページの最初の行が「（1）」なら、ページ番号として除かない
    pages = ["\n".join(["（1）", *SMALL_FRONT, BODY16, "引用および参考文献", SMALL_REF, REF16[:-2], REF16[-2:]]),
             "\n".join(["（2）", *SMALL_EN])]
    pc = compare(plan, pages)
    assert pc.unmatched == [] and pc.diffs == [] and plan_fixes(plan, pc) == [] and pc.ignored_lines == []


def test_repeated_line_is_kept_in_stream(journal, tmp_path):
    """3 ページ以上に同じ文字列で出る 8 文字以上の行（柱の形の行）は、ページの端の行でもページの途中の行でも列から除かない。
    ページの途中の同じ文字列の行（引用文献の誌名の行など）は、段落に当たれば照合に使う（ルート2 で docx のその文字を消さない）。
    ページの端の本物の柱は、段落の切れ目にあるので違いにならない。"""
    head = "全国数学教育学会誌　数学教育学研究"
    ref = "架空次郎（2018）．「架空の題目」．全国数学教育学会誌　数学教育学研究，第24巻，pp.1-10．"
    ref2 = "見本三郎（2019）．「見本の題目」．『見本誌』，第3巻，pp.5-8．"
    plan, _ = small_article(tmp_path, journal, BODY16, ref, ref2)
    at = ref.index(head)
    pages = ["\n".join(["（1）", head, *SMALL_FRONT, BODY16]),
             "\n".join(["（2）", head, "引用および参考文献", SMALL_REF, ref[:at], head, ref[at + len(head):], ref2]),
             "\n".join(["（3）", head, *SMALL_EN])]
    pc = compare(plan, pages)
    assert pc.unmatched == [] and pc.diffs == [] and plan_fixes(plan, pc) == [] and pc.ignored_lines == []


REPEAT = "ことが明らかになった。"            # 3 ページの最後の行に出る、本文の段落の最後の行（11 文字）
REPEAT_BODY = ["一つ目の架空の場面では，生徒は表の横の並びに着目し，架空の量が一定の割合で増えることを言葉で述べた。"
               "この発言から，横の見方が対応の見方よりも先に出る" + REPEAT,
               "二つ目の架空の場面では，生徒は二つの量の値の組を順に書き出し，架空の比が変わらないことを確かめた。"
               "このことから，値の組を書く活動で比の一定に気が付く" + REPEAT,
               "三つ目の架空の場面では，生徒はグラフの傾きに着目し，架空の二つの量の関係を式で表そうとした。"
               "全体の分析から，式による表現は対応の見方の後に現れる" + REPEAT,
               "以上の三つの場面を通して，架空の授業における生徒の捉え方の変容を，発話と記述の両方から順に追うことができた。"]


@pytest.mark.parametrize("head", ["", "架空の比例の授業の分析"], ids=["no-head", "head"])
def test_repeated_last_line_of_paragraphs_is_compared(head, journal, tmp_path):
    """本文の 3 つの段落の最後の行がどれも「ことが明らかになった。」で、3 ページの最後の行に出る（柱の形の行になる）。
    段落に行全体が当たるので照合に使い、ルート2 で docx のその文字を消さない。各ページの最初の行に本物の柱（4 ページに
    同じ文字列）があるときも同じで（ページの最後の行の次が、次のページの柱）、段落の途中の柱は docx に足さない。"""
    mf.make_article(tmp_path / "repeat.docx", "ページ番号の判定の検証用文書",
                    lambda b: [mf.para(mf.S["sec1"], "１．はじめに")] + [mf.para(mf.S["body"], x) for x in REPEAT_BODY])
    _, plan, _ = _mechanical(tmp_path / "repeat.docx", journal)
    src = {p.plain(): p.src for p in plan.paras.values()}

    def lines(x):                         # 1 行 24 文字。段落の最後の行は「ことが明らかになった。」だけ
        body = x[:-len(REPEAT)] if x.endswith(REPEAT) else x
        return [body[k:k + 24] for k in range(0, len(body), 24)] + ([REPEAT] if body != x else [])
    heads = [head] if head else []
    last = REPEAT_BODY[3]
    pages = ["\n".join(["（1）", *SMALL_FRONT, *lines(REPEAT_BODY[0])]),
             "\n".join(["（2）", *heads, *lines(REPEAT_BODY[1])]),
             "\n".join(["（3）", *heads, *lines(REPEAT_BODY[2])]),
             "\n".join(["（4）", *heads, *lines(last)[:2]]),
             "\n".join(["（5）", *heads, *lines(last)[2:], "引用および参考文献", SMALL_REF, *SMALL_EN])]
    pc = compare(plan, pages)
    assert pc.unmatched == [] and pc.diffs == [] and plan_fixes(plan, pc) == []
    assert pc.ignored_lines == ([(src[last], head)] if head else [])


def test_line_marks():
    """内部の印（PdfStream の edge・head・line_only）の組。内部の印を確かめるテストはこれだけにし、ほかのテストは照合の結果
    （違い・直す箇所・照合に使わなかった文字）で確かめる。

    ページの端の行（ページ番号を除いた最初の 2 行と最後の 2 行）・ページの途中の数字だけの行・何ページにも出る行・短い行は、
    柱の候補の行（head）。ページの途中の数字だけの行（前の行の続きを除く）と、何ページにも出る行（ページの端の柱を含む。
    0.19.0 では列から除いていた行）は、行全体でしか docx の文字と一致させない行（line_only）。前の行の続きは、前の行が
    数字＋ハイフン・波線で終わる数字だけの行（引用文献の「pp.11-」の改行の後の「16」。ページの最初の柱の次の行なら、前の
    ページの最後の行の続き）だけで、本文の行が「，」で終わった直後（ページの区切りをまたいでも）や、表の「－」のセルの次の
    数字だけの行は、続きとみなさない。短い行（図の中の点の名前など）は柱の候補にするが、line_only にはしない。"""
    from jasme_jats.pdfmatch import pdf_stream
    head = "何ページにも出る架空の行"
    pages = ["\n".join(["（1）", head, "一ページ目の最初の本文の行です。", "27", "pp.11-", "16", "一ページ目の途中の本文の行です，",
                        "31", "－", "21", "A", head, "一ページ目の最後から二行目です。", "pp.12-"]),
             "\n".join(["（2）", "試験四郎", "17", "二ページ目の本文の行です。", "二ページ目の最後の行です，", head]),
             "\n".join(["（3）", head, "10", "三ページ目の本文の行です。"])]
    st = pdf_stream(pages)
    marks = {(st.lines[st.line[k]], st.edge[k], st.head[k], st.line_only[k]) for k in range(len(st.chars))}
    assert {x for x in marks if x[0] in ("27", "16", "31", "－", "21", "A", "試験四郎", "17", "10", head)} == {
        ("27", False, True, True), ("16", False, True, False), ("31", False, True, True), ("－", False, True, False),
        ("21", False, True, True), ("A", False, True, False), ("試験四郎", True, True, False),
        ("17", True, True, False),                                        # ページの最初の柱の次の、前のページの続き
        ("10", True, True, True),                                         # 「，」で終わる前のページの行の後ろ
        (head, False, True, True), (head, True, True, True)}              # ページの端の柱も、行全体でしか一致させない行


def test_page_number_at_page_bottom():
    """ページ番号が各ページの最後の行にある PDF（本誌とは別の形）で、ページの最初の行が引用文献の「pp.11-」の続きの「16」でも、
    ページ番号として除くのは、ページの順に番号が続く最後の行（「16」は除かない）。"""
    from jasme_jats.pdfmatch import pdf_stream
    for fmt in ("{}", "－ {} －", "（{}）"):
        st = pdf_stream(["\n".join(["本文の行です。", REF16[:-2], fmt.format(1)]), "\n".join(["16", "本文の行です。", fmt.format(2)])])
        assert "".join(st.chars) == "本文の行です。" + REF16[:-2].replace(" ", "") + "16本文の行です。", fmt


@pytest.mark.parametrize("fmt", ["{}", "－ {} －", "（{}）"])
def test_page_number_at_page_bottom_keeps_reference_digits(fmt, journal, tmp_path):
    """同じ形の PDF で、引用文献の「16」を消さない（ルート2 で直す箇所がない）。"""
    plan, _ = small_article(tmp_path, journal, BODY16, REF16)
    pages = ["\n".join([*SMALL_FRONT, BODY16, "引用および参考文献", SMALL_REF, REF16[:-2], fmt.format(1)]),
             "\n".join([REF16[-2:], *SMALL_EN, fmt.format(2)])]
    pc = compare(plan, pages)
    assert pc.unmatched == [] and pc.diffs == [] and plan_fixes(plan, pc) == [] and pc.ignored_lines == []


@pytest.mark.parametrize("pages_n", [1, 2])
def test_reference_digits_on_pdf_without_page_numbers(pages_n, journal, tmp_path):
    """ページ番号のない PDF（1 ページだけ、または番号が続く候補がどのページにもない）では、ページの最初か最後の数字だけの行を
    ページ番号として除くが、前の行の続き（引用文献の「pp.11-」の改行の後の「16」）は除かない（ルート2 で docx の「16」を
    消さない）。"""
    plan, src = small_article(tmp_path, journal, BODY16, REF16)
    lines = [*SMALL_FRONT, BODY16, "引用および参考文献", SMALL_REF, REF16[:-2], REF16[-2:]]      # 最後の行が「16」
    pages = ["\n".join(lines)] if pages_n == 1 else ["\n".join(lines), "\n".join(SMALL_EN)]
    pc = compare(plan, pages)
    assert src[REF16] not in pc.unmatched and [d for d in pc.diffs if d.src == src[REF16]] == []
    assert [f for f in plan_fixes(plan, pc) if f.src == src[REF16]] == []


@pytest.mark.parametrize("pages_n", [2, 3])
def test_reference_digits_at_page_top_on_pdf_without_page_numbers(pages_n, journal, tmp_path):
    """ページ番号のない PDF（番号が続く候補がどのページにもない）で、2 ページ目の最初の行が、1 ページ目の最後の行「…pp.11-」の
    続きの「16」。ページの最初の行の候補が前の行の続きかは、前のページの最後の行で見るので、ページ番号として除かない
    （ルート2 で docx の「16」を消さない）。"""
    plan, src = small_article(tmp_path, journal, BODY16, REF16)
    first = [*SMALL_FRONT, BODY16, "引用および参考文献", SMALL_REF, REF16[:-2]]
    rest = [[REF16[-2:], *SMALL_EN]] if pages_n == 2 else [[REF16[-2:], *SMALL_EN[:3]], SMALL_EN[3:]]
    pc = compare(plan, ["\n".join(first)] + ["\n".join(x) for x in rest])
    assert pc.unmatched == [] and pc.diffs == [] and plan_fixes(plan, pc) == [] and pc.ignored_lines == []


def test_page_number_on_one_page_after_reference_line(journal, tmp_path):
    """ページ番号が 2 ページ目にしかない PDF（番号が続く候補がない）で、1 ページ目の最後の行が「…pp.11-」でも、2 ページ目の
    最初の行のかっこ付きの番号「（2）」は前の行の続きとみなさず、ページ番号として除く（その次の行の「16」は前のページの続き）。"""
    plan, src = small_article(tmp_path, journal, BODY16, REF16)
    pages = ["\n".join([*SMALL_FRONT, BODY16, "引用および参考文献", SMALL_REF, REF16[:-2]]),
             "\n".join(["（2）", REF16[-2:], *SMALL_EN])]
    pc = compare(plan, pages)
    assert pc.diffs == [] and plan_fixes(plan, pc) == [] and pc.ignored_lines == []


def page_top_pages(heads, number, bottom=False):
    """引用文献 REF16 の「pp.11-」で 1 ページ目が終わり、2 ページ目の最初の行が柱 heads（なければ「16」の行）の PDF の文字。
    heads は {ページの番号: 柱の行}。number は「16」の行の文字（出版版で直っていれば「17」）。bottom なら、柱はページの最後の行。"""
    body = [[*SMALL_FRONT, BODY16, "引用および参考文献", SMALL_REF, REF16[:-2]], [number, REF2], SMALL_EN[:3], SMALL_EN[3:]]
    return ["\n".join([f"（{n + 1}）", *([heads[n]] if n in heads and not bottom else []), *x,
                       *([heads[n]] if n in heads and bottom else [])]) for n, x in enumerate(body)]


REF2 = "見本三郎（2019）．「見本の題目」．『見本誌』，第3巻，pp.5-8．"
SHORT_HEAD, TWO_PAGE_HEAD = "試験六郎", "架空の論文の柱の文字列です"


@pytest.mark.parametrize("heads, number, want", [
    ({}, "16", []),                                                # 柱なし（次のページの最初の行）
    ({1: SHORT_HEAD}, "16", []),                                   # 8 文字未満の柱（2 ページ目以降の最初の著者名）
    ({1: SHORT_HEAD}, "17", [("6", "7")]),                         # 同じ形で、出版版で「17」に直っている
    ({0: TWO_PAGE_HEAD, 1: TWO_PAGE_HEAD}, "16", []),              # 2 ページにしか出ない柱
    ({1: TWO_PAGE_HEAD, 2: TWO_PAGE_HEAD, 3: TWO_PAGE_HEAD}, "16", []),           # 3 ページ以上に出る柱
    ({1: TWO_PAGE_HEAD, 2: TWO_PAGE_HEAD, 3: TWO_PAGE_HEAD}, "17", [("6", "7")]),
], ids=["no-head", "short-head", "short-head-fixed", "two-page-head", "repeated-head", "repeated-head-fixed"])
def test_reference_digits_after_page_top_head(heads, number, want, journal, tmp_path):
    """引用文献の「pp.11-」の改行の後の数字が、次のページの最初の柱の次の行にある。柱を飛ばして前のページの最後の行の続きと
    みなし、普通の行として照合する（ルート2 で docx の「16」を消さない。出版版で「17」に直っていれば「6」→「7」と直す）。
    柱は docx に足さない。"""
    plan, src = small_article(tmp_path, journal, BODY16, REF16, REF2)
    pc = compare(plan, page_top_pages(heads, number))
    assert pc.unmatched == [] and [(f.old, f.new) for f in plan_fixes(plan, pc) if f.kind == "text"] == want
    assert pc.ignored_lines == ([(src[REF16], heads[1])] if 1 in heads else [])


@pytest.mark.parametrize("number, want", [("16", []), ("17", [("6", "7")])])
def test_reference_digits_after_page_bottom_head(number, want, journal, tmp_path):
    """3 ページ以上に出る柱が各ページの最後の行にあり、1 ページ目の最後の柱の前の行が「…pp.11-」、2 ページ目の最初の行がその
    続きの数字。何ページにも出る柱は、前の行の続きかを見るときに飛ばすので、普通の行として照合する（ルート2 で docx の「16」を
    消さない）。"""
    plan, src = small_article(tmp_path, journal, BODY16, REF16, REF2)
    heads = {n: TWO_PAGE_HEAD for n in range(4)}
    pc = compare(plan, page_top_pages(heads, number, bottom=True))
    assert pc.unmatched == [] and [(f.old, f.new) for f in plan_fixes(plan, pc) if f.kind == "text"] == want
    assert pc.ignored_lines == [(src[REF16], TWO_PAGE_HEAD)]


def test_continued_digit_line_fixed_in_middle_of_page(journal, tmp_path):
    """ページの途中で、引用文献の「pp.11-」の改行の後の数字が出版版で直っている（docx「16」、PDF「17」）。前の行の続きとして
    普通の行と同じに照合するので、「6」→「7」と直す（数字を消さない）。"""
    plan, _ = small_article(tmp_path, journal, BODY16, REF16, REF2)
    pages = ["\n".join(["（1）", *SMALL_FRONT, BODY16, "引用および参考文献", SMALL_REF, REF16[:-2], "17", REF2, *SMALL_EN])]
    pc = compare(plan, pages)
    assert [(f.old, f.new) for f in plan_fixes(plan, pc) if f.kind == "text"] == [("6", "7")] and pc.ignored_lines == []


def test_repeated_line_in_middle_of_paragraph_is_not_inserted(journal, tmp_path):
    """ページの途中（2 段組の段の最初など）にある柱の形の行（4 ページに出る 13 文字の行）が、本文の段落を分断する。段落に
    当たらないので照合に使わず、docx に足さない（照合に使わなかった文字として記録する）。"""
    plan, src = small_article(tmp_path, journal, BODY16)
    cut = BODY16.index("表の数字")
    pages = ["\n".join(["（1）", *SMALL_FRONT, BODY16[:cut], TWO_PAGE_HEAD, BODY16[cut:], "引用および参考文献"]),
             "\n".join(["（2）", "本文ではない架空の行その一", TWO_PAGE_HEAD, SMALL_REF]),
             "\n".join(["（3）", "本文ではない架空の行その二", TWO_PAGE_HEAD, *SMALL_EN[:3]]),
             "\n".join(["（4）", "本文ではない架空の行その三", TWO_PAGE_HEAD, *SMALL_EN[3:]])]
    pc = compare(plan, pages)
    assert pc.unmatched == [] and pc.diffs == [] and plan_fixes(plan, pc) == []
    assert pc.ignored_lines == [(src[BODY16], TWO_PAGE_HEAD)]


CONT_BODY = "本研究では，架空の調査の結果を整理した。その結果，12点の生徒が最も多く，前回の調査より増えた。"
CONT_PUB = CONT_BODY.replace("12点", "13点")


@pytest.mark.parametrize("cells, page_break", [
    (["31", "27", "14"], False),           # 本文の行が「，」で終わった直後の表のセル（同じページ）
    (["31"], False),
    (["10", "20", "30"], True),            # 次のページの最初の図の目盛り
    (["－", "21", "－", "31"], False),     # 表の「－」（該当なし）のセルの次の数字のセル
], ids=["comma-cells", "comma-cell", "page-top-figure", "dash-cells"])
def test_digit_lines_after_comma_are_not_inserted(cells, page_break, journal, tmp_path):
    """本文の行が「，」で終わった直後（ページの区切りをまたいでも）の表のセル・図の目盛りの数字だけの行や、表の「－」のセルの
    次の数字のセルは、前の行の続き（「pp.11-」の改行の後の「16」）とみなさず、行全体でしか一致させない。近くで docx の数字が
    出版版で直されていても（「12点」→「13点」）、セルの数字が docx の数字と偶然一致して docx に入ることはない（直すのは
    「2」→「3」だけ）。"""
    plan, src = small_article(tmp_path, journal, CONT_BODY)
    cut = CONT_PUB.index("13点")                  # CONT_PUB[:cut] は「，」で終わる
    tail = ["引用および参考文献", SMALL_REF, *SMALL_EN]
    if page_break:
        pages = ["\n".join(["（1）", *SMALL_FRONT, CONT_PUB[:cut]]), "\n".join(["（2）", *cells, CONT_PUB[cut:], *tail])]
    else:
        pages = ["\n".join(["（1）", *SMALL_FRONT, CONT_PUB[:cut], *cells, CONT_PUB[cut:], *tail])]
    pc = compare(plan, pages)
    assert [(f.old, f.new) for f in plan_fixes(plan, pc) if f.kind == "text"] == [("2", "3")]
    assert pc.ignored_lines == [(src[CONT_BODY], c) for c in dict.fromkeys(cells)]


TABLE_CAP = "表１　架空の組ごとの得点"
NEXT_BODY = "次の段落は表の後ろに続く本文の段落であり，照合の確かめに使う。"


def table_article(tmp_path, journal, body, rows):
    """本文の段落 body の後ろに、表のキャプション TABLE_CAP と Word の表 rows、本文の段落 NEXT_BODY がある小さな論文の
    構造と、段落の文字 -> 段落 ID。PDF の中では、表が段落 body の途中に入る形にして確かめる。"""
    mf.make_article(tmp_path / "table.docx", "ページ番号の判定の検証用文書", lambda b: [
        mf.para(mf.S["sec1"], "１．はじめに"), mf.para(mf.S["body"], body), mf.para(mf.S["tab_cap"], TABLE_CAP),
        mf.table([[mf.cell(c) for c in row] for row in rows]), mf.para(mf.S["body"], NEXT_BODY)])
    _, plan, _ = _mechanical(tmp_path / "table.docx", journal)
    return plan, {p.plain(): p.src for p in plan.paras.values()}


def score_rows(n):
    """組の列（「1組」…）と、問ごとの整数の得点のセル（架空の数）の表。見出しの行を含む。"""
    return [["組", "問1", "問2", "問3", "問4", "問5"]] + [[f"{r}組"] + [str(10 + (r * 7 + c * 13) % 89) for c in range(1, 6)]
                                                       for r in range(1, n + 1)]


SHORT_TAIL = ["本研究では，架空の授業における生徒の発言を記", "録し，その特徴を観点ごとに整理したうえで，考",
              "察を加えることにする。授業は全部で五回行い，", "行った。"]


@pytest.mark.parametrize("rows", [5, 6, 8])
def test_numeric_table_before_short_last_line(rows, journal, tmp_path):
    """表（整数のセル 25 個以上）がページの最後にあり、段落の最後の短い行が次のページの最初の行にある（本誌によくある形）。
    数字だけの行を列に残しても、照合の窓を短くしない（段落の最後の行を窓の外に出して、ルート2 で消さない。0.19.0 と同じ）。"""
    body = "".join(SHORT_TAIL)
    grid = score_rows(rows)
    plan, src = table_article(tmp_path, journal, body, grid)
    pages = ["\n".join(["（1）", *SMALL_FRONT, *SHORT_TAIL[:-1], TABLE_CAP, *[c for row in grid for c in row]]),
             "\n".join(["（2）", SHORT_TAIL[-1], NEXT_BODY, "引用および参考文献", SMALL_REF, *SMALL_EN])]
    pc = compare(plan, pages)
    assert pc.unmatched == [] and pc.diffs == [] and plan_fixes(plan, pc) == []
    # 表のセル（短い行と数字だけの行）は、照合に使わなかった文字として記録する（docx の表のセルは照合しない）
    assert pc.ignored_lines == [(src[body], c) for row in grid for c in row]


def test_numeric_table_inside_paragraph_does_not_cut_tail(journal, tmp_path):
    """PDF の中で、段落の終わり近く（後ろの 9 文字の前）を数字のセルの表（6 行。数字のセルは 1 つずつの行）が分断する。
    数字だけの行を列に残しても、段落の後ろを窓の外に出さない（ルート2 で段落の後ろを消さない。0.19.0 と同じ）。"""
    body = ("本稿では，架空の授業における生徒の発話を記録し，その特徴を三つの観点から整理する。各観点の記録の件数を表１に示す。"
            "以下では表の結果を観点ごとに述べる。")
    labels = [f"第{k + 1}群の記録" for k in range(6)]
    nums = [[str(10 + (r * 11 + c * 7) % 89) for c in range(10)] for r in range(6)]
    plan, src = table_article(tmp_path, journal, body, [[labels[r], *nums[r]] for r in range(6)])
    cut = len(body) - 9
    lines = [TABLE_CAP] + [x for r in range(6) for x in [labels[r], *nums[r]]]
    pages = ["\n".join(["（1）", *SMALL_FRONT, body[:cut], *lines, body[cut:], NEXT_BODY, "引用および参考文献", SMALL_REF,
                        *SMALL_EN])]
    pc = compare(plan, pages)
    assert pc.unmatched == [] and [(f.old, f.new) for f in plan_fixes(plan, pc) if f.kind == "text"] == []


@pytest.mark.parametrize("page_break", [True, False])
def test_table_digits_do_not_match_corrected_number(page_break, journal, tmp_path):
    """段落の数の後ろの語が出版版で直され（docx「12点」→ PDF「12名」）、PDF ではその直前に整数のセルの表がある。表のセルの
    「31」「27」の「1」「2」が docx の「12」と偶然一致して、表の数字が docx に入ることはない（直すのは「点」→「名」だけ）。"""
    body = "架空の調査の結果を表１に示す。その結果，生徒の平均は12点であり，前回の調査より高かった。"
    rows = [["組の名前", "一回目の得点", "二回目の得点"], ["第一の組", "31", "27"], ["第二の組", "14", "23"],
            ["第三の組", "35", "16"], ["第四の組", "19", "21"]]
    plan, src = table_article(tmp_path, journal, body, rows)
    pub = body.replace("12点", "12名")
    cut = pub.index("12名")
    cells = [c for row in rows for c in row]
    if page_break:            # 表がページの最後にあり、段落の続きは次のページの最初の行
        pages = ["\n".join(["（1）", *SMALL_FRONT, pub[:cut], TABLE_CAP, *cells]),
                 "\n".join(["（2）", pub[cut:], NEXT_BODY, "引用および参考文献", SMALL_REF, *SMALL_EN])]
    else:
        pages = ["\n".join(["（1）", *SMALL_FRONT, pub[:cut], TABLE_CAP, *cells, pub[cut:], NEXT_BODY, "引用および参考文献",
                            SMALL_REF, *SMALL_EN])]
    pc = compare(plan, pages)
    assert [(f.old, f.new) for f in plan_fixes(plan, pc) if f.kind == "text"] == [("点", "名")]
    assert pc.ignored_lines == [(src[body], c) for c in ("31", "27", "14", "23", "35", "16", "19", "21")]


@pytest.mark.parametrize("cell", ["16", "1"])
def test_digit_line_at_correction(cell, journal, tmp_path):
    """校正の直し（docx「授業は1回行った」→ PDF「授業は２回行った」）の位置に、ページの途中の数字だけの行（表のセル）がある。
    セルの数字が docx の数字と同じ文字を含んでも（「16」の「1」、「1」）、セルの文字を docx に入れず、「1」→「２」と直す。"""
    body = "本稿は架空の授業を対象とする。授業は1回行った。記録の方法は次の節で述べる。"
    plan, src = small_article(tmp_path, journal, body)
    pub = body.replace("1回", "２回")
    cut = pub.index("２回")
    pages = ["\n".join(["（1）", *SMALL_FRONT, pub[:cut], cell, pub[cut:], "引用および参考文献", SMALL_REF, *SMALL_EN])]
    pc = compare(plan, pages)
    assert [(f.old, f.new) for f in plan_fixes(plan, pc) if f.kind == "text"] == [("1", "２")]
    assert pc.ignored_lines == [(src[body], cell)]


def test_digit_lines_matched_as_whole_lines(journal, tmp_path):
    """前の行の続きの形でない数字だけの行でも、docx の文字がその行の文字とまったく同じに続けば、行全体で一致させて照合する
    （ルート2 で docx の数字を消さず、照合に使わなかった文字にもしない）: 段落の最後（引用文献の「p.」の改行の後の「16」）、
    段落の途中（docx の表を本文に書いた段落の数字）。"""
    ref = "架空太郎（2019）．「架空の題目」．『架空学会誌』，第29号，p.16"
    body = "教職経験は大学卒27年目と院卒16年目である。"
    plan, _ = small_article(tmp_path, journal, body, ref)
    at = ref.index("16")
    pages = ["\n".join(["（1）", *SMALL_FRONT, "教職経験は大学卒", "27", "年目と院卒", "16", "年目である。", "引用および参考文献",
                        SMALL_REF, ref[:at], ref[at:], *SMALL_EN])]
    pc = compare(plan, pages)
    assert pc.unmatched == [] and pc.diffs == [] and plan_fixes(plan, pc) == [] and pc.ignored_lines == []


def test_heading_number_line_matched_as_whole_line(journal):
    """段落の最初（見出しの番号「（1）」が PDF では別の行）でも、docx の段落がその行の文字で始まれば行全体で一致させる
    （番号を消さず、全角・半角は今までどおり直す）。"""
    pages = ["\n".join(["（1）", *FRONT, PUB12, PUBLISHED["d13"], "（1）", "方法の概要", *REST[2:]])]
    plan = _plan(journal)
    pc = compare(plan, pages)
    assert [d for d in pc.diffs if d.src == "d14"] == [] and pc.ignored_lines == []
    assert [(f.old, f.new) for f in plan_fixes(plan, pc) if f.src == "d14"] == [("(", "（"), (")", "）"), (" ", "")]


YEAR_REF = "架空二郎（2021）．「架空の比の研究」．『架空教育研究』，第12巻，2018"      # 年で終わる（終わりの「．」なし）
PAGE_REF = "架空三郎（2017）．「架空の図の研究」．『架空数学研究』，第30号，p.16"
END_CASES = [   # (docx の引用文献, PDF の最後の 2 行, docx の数字, PDF の数字)
    (YEAR_REF, ["架空二郎（2021）．「架空の比の研究」．『架空教育研究』，第12巻，", "2019"], "2018", "2019"),
    (PAGE_REF, ["架空三郎（2017）．「架空の図の研究」．『架空数学研究』，第30号，p.", "17"], "16", "17"),
]


@pytest.mark.parametrize("page_top", [False, True], ids=["same-page", "page-top"])
@pytest.mark.parametrize("ref, lines, old, new", END_CASES, ids=["year", "page"])
def test_corrected_digit_line_at_paragraph_end_is_not_deleted(ref, lines, old, new, page_top, journal, tmp_path):
    """引用文献の最後の行が、前の行の続きの形でない数字だけの行（「，」の後ろの年「2019」、「p.」の改行の後の「17」。行全体で
    しか一致させない行）で、出版版で数字が直されている（同じページの次の行と、次のページの最初の行）。段落の最後の docx の
    数字の位置に同じ行の PDF の文字がなく、次の行は照合に使わない行なので、docx の数字を消さず（0.19.0 は消していた）、
    直さない違い（HEAD_WHY）にする。その行は照合に使わなかった文字として記録する（13 章に出る）。"""
    from jasme_jats.pdfmatch import HEAD_WHY
    plan, src = small_article(tmp_path, journal, BODY16, REF2, ref)
    head = [*SMALL_FRONT, BODY16, "引用および参考文献", SMALL_REF, REF2, lines[0]]
    pages = (["\n".join(["（1）", *head]), "\n".join(["（2）", lines[1], *SMALL_EN])] if page_top
             else ["\n".join(["（1）", *head, lines[1], *SMALL_EN])])
    pc = compare(plan, pages)
    assert pc.unmatched == [] and [(d.src, d.docx, d.pdf, d.fixable, d.why) for d in pc.diffs] == [
        (src[ref], old, new, False, HEAD_WHY)]
    assert [(f.old, f.new, f.reason) for f in plan_fixes(plan, pc) if f.kind == "text"] == [(old, new, HEAD_WHY)]
    assert pc.ignored_lines == [(src[ref], new)]


@pytest.mark.parametrize("number", ["16", "17"])
def test_reference_digits_after_page_bottom_two_page_head(number, journal, tmp_path):
    """引用文献の「pp.11-」で 1 ページ目が終わり、その後ろにページの最後の行の柱（2 ページにしか出ない。前の行の続きかを
    見るときに飛ばさない）があり、2 ページ目の最初の行が数字（「16」、出版版で直っていれば「17」）。数字の行は前の行の続きと
    みなせず、行全体でも一致しないが、docx の「16」を消さず（0.19.0 は消していた）、直さない違い（HEAD_WHY）にする。PDF の
    文字は、続いた照合に使わない行（柱と数字の行）を出す。"""
    from jasme_jats.pdfmatch import HEAD_WHY
    plan, src = small_article(tmp_path, journal, BODY16, REF2, REF16)
    pages = ["\n".join(["（1）", *SMALL_FRONT, BODY16, "引用および参考文献", SMALL_REF, REF2, REF16[:-2], TWO_PAGE_HEAD]),
             "\n".join(["（2）", number, *SMALL_EN, TWO_PAGE_HEAD])]
    pc = compare(plan, pages)
    shown = TWO_PAGE_HEAD + LINE_MARK + number
    assert pc.unmatched == [] and [(d.src, d.docx, d.pdf, d.fixable, d.why) for d in pc.diffs] == [
        (src[REF16], "16", shown, False, HEAD_WHY)]
    assert [(f.old, f.new, f.reason) for f in plan_fixes(plan, pc) if f.kind == "text"] == [("16", shown, HEAD_WHY)]
    assert pc.ignored_lines == [(src[REF16], TWO_PAGE_HEAD), (src[REF16], number)]


def test_deleted_paragraph_end_before_other_paragraph_is_deleted(journal, tmp_path):
    """出版版で段落の最後の文字が消されていて（docx「…考察した。以上」）、PDF のすぐ後ろの行がほかの段落の行なら、今までどおり
    消す（その後ろに照合に使わない行〈図の中の点の名前など〉があっても、段落のすぐ隣の行ではないので、直さない違いにしない）。"""
    body = "本稿では，架空の授業の記録を観点ごとに整理し，その特徴を三つに分けて考察した。以上"
    mf.make_article(tmp_path / "tail.docx", "ページ番号の判定の検証用文書",
                    lambda b: [mf.para(mf.S["sec1"], "１．はじめに"), mf.para(mf.S["body"], body),
                               mf.para(mf.S["body"], NEXT_BODY)])
    _, plan, _ = _mechanical(tmp_path / "tail.docx", journal)
    pages = ["\n".join(["（1）", *SMALL_FRONT, body[:-2], NEXT_BODY, "A", "引用および参考文献", SMALL_REF, *SMALL_EN])]
    pc = compare(plan, pages)
    assert [(f.old, f.new, f.reason) for f in plan_fixes(plan, pc) if f.kind == "text"] == [("以上", "", "")]


def test_corrected_digit_line_at_paragraph_end_in_report(journal, meta, tmp_path, monkeypatch):
    """同じ形（「，」の後ろの年が出版版で直されている）をルート2 で変換すると、XML の文献は docx の年のまま（消さない）。
    13.2 に直さなかった理由を出し、13.4（直した docx と PDF の照合）でも「PDF と同じ文字になりました」とは言わず、残っている
    違いとして出す。13.6 には年の行が載る。"""
    from jasme_jats.pdfmatch import HEAD_WHY
    small_article(tmp_path, journal, BODY16, REF2, YEAR_REF)
    ref, lines, old, new = END_CASES[0]
    pages = ["\n".join(["（1）", *SMALL_FRONT, BODY16, "引用および参考文献", SMALL_REF, REF2, *lines, *SMALL_EN])]
    res = convert_with_pages(tmp_path, monkeypatch, journal, meta, pages, "pdf", docx=tmp_path / "small.docx")
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    assert [(f.old, f.new, f.reason) for f in res.docx_fix.skipped] == [(old, new, HEAD_WHY)]
    assert not any(f.kind == "text" for f in res.docx_fix.applied) and YEAR_REF in texts(load(res))
    ch13 = chapters(res)[1]
    assert f"| {old} | {new} | {HEAD_WHY} |" in ch13.split("### 13.2")[1].split("### 13.3")[0]
    remaining = ch13.split("### 13.4")[1].split("### 13.5")[0]
    assert "PDF と同じ文字になりました" not in remaining and f"| {old} | {new}" in remaining
    assert f"数字だけの行 1 件: {new}" in ch13.split("### 13.6")[1]


def test_corrected_heading_number_line_is_not_deleted(journal, tmp_path):
    """段落の最初（別の行の見出しの番号）が出版版で直されている（docx「（1）」、PDF の行「（2）」。行全体でしか一致させない行）。
    段落の最初の docx の文字の位置に同じ行の PDF の文字がなく、前の行は照合に使わない行なので、番号を消さず（0.19.0 は
    消していた）、直さない違い（HEAD_WHY）にする（番号が同じなら行全体で一致させる。test_heading_number_line_matched_as_whole_line）。"""
    from jasme_jats.pdfmatch import HEAD_WHY
    heading, body2 = "（1）架空の授業の分析の方法と記録の観点", "次に，記録した発言を三つの観点から分類し，それぞれの件数を述べる。"
    mf.make_article(tmp_path / "heading.docx", "ページ番号の判定の検証用文書",
                    lambda b: [mf.para(mf.S["sec1"], "１．はじめに"), mf.para(mf.S["body"], BODY16),
                               mf.para(mf.S["sec2"], heading), mf.para(mf.S["body"], body2)])
    _, plan, _ = _mechanical(tmp_path / "heading.docx", journal)
    src = {p.plain(): p.src for p in plan.paras.values()}
    pages = ["\n".join(["（1）", *SMALL_FRONT, BODY16, "（2）", heading[3:], body2, "引用および参考文献", SMALL_REF, *SMALL_EN])]
    pc = compare(plan, pages)
    assert [(d.src, d.docx, d.pdf, d.fixable, d.why) for d in pc.diffs] == [(src[heading], "（1）", "（2）", False, HEAD_WHY)]
    assert [(f.old, f.new, f.reason) for f in plan_fixes(plan, pc) if f.kind == "text"] == [("（1）", "（2）", HEAD_WHY)]
    assert pc.ignored_lines == [(src[heading], "（2）")]


def test_no_space_from_skipped_table_digits(journal, tmp_path):
    """足す文字（「約」と「2」）の間に照合に使わなかった表の数字の行があっても、その数字の後ろの改行を英文の単語の間の空白と
    取り違えない（足す文字に空白を入れない。空白を戻すかは、足す文字の前後の文字で決める）。"""
    body = "本稿は架空の授業を対象とする。授業は回行った。記録の方法は次の節で述べる。"
    plan, src = small_article(tmp_path, journal, body)
    cut = body.index("回行った")
    pages = ["\n".join(["（1）", *SMALL_FRONT, body[:cut] + "約", "16", "2" + body[cut:], "引用および参考文献", SMALL_REF,
                        *SMALL_EN])]
    pc = compare(plan, pages)
    assert [(f.old, f.new) for f in plan_fixes(plan, pc) if f.kind == "text"] == [("", "約2")]
    assert pc.ignored_lines == [(src[body], "16")]


@pytest.mark.parametrize("labels", [["A", "B", "C", "O"], ["y", "O", "x", "1", "2"], ["図中Ａ", "図中Ｂ"]],
                         ids=["points", "axes", "labels"])
def test_short_lines_in_middle_of_page_are_not_inserted(labels, journal):
    """図の中の短い文字（点の名前・軸のラベルなど。docx では図は画像）がページの途中で段落を分断しても、docx に足さない。"""
    pc, diffs, fixes = d12_result(journal, d12_pages(end1=[*labels, PUB12[CUT:], *REST[:2]], second="", rest=REST[2:]))
    assert diffs == [] and fixes == []
    assert pc.ignored_lines == [("d12", x) for x in labels]


def test_length_rule_counts_ignored_chars(journal):
    """段落の途中の PDF にだけある文字が、段落に当たる行の後ろの 3 文字と、ページの端の照合に使わない行（18 文字）で、
    合わせて 20 文字以上なら、残りの 3 文字も足さない（PDF にだけある 20 文字以上の文字を足さない規則の長さは、照合に
    使わない文字を除く前で数える。0.19.0 と同じく、足す文字が増えない）。段落の文字のある行にかかるので、黙って捨てずに、
    直さない違い（LONG_WHY）として 13 章に出す。"""
    from jasme_jats.pdfmatch import LONG_WHY
    line = "架空の柱の文字列で十八文字ある行です"
    pages = d12_pages(first=PUB12[:CUT] + "ＡＢＣ", start2=[line])
    pc, diffs, fixes = d12_result(journal, pages)
    assert diffs == [("", "ＡＢＣ" + LINE_MARK + line, False)] and fixes == [("", "ＡＢＣ" + LINE_MARK + line, LONG_WHY)]
    assert pc.ignored_lines == [("d12", line)]


ADD_BODY = "本稿は架空の授業を対象とする。授業は五回行い，記録の方法は次の節で述べる。"
ADD_PUB = ADD_BODY.replace("授業は五回", "授業は全部で五回")       # 校正で足された短い文字
REPEATED_HEAD = "架空の比例の授業における生徒の発話の分析"              # 20 文字。2〜4 ページの最初の行に出る柱


@pytest.mark.parametrize("kind", ["table-digits", "running-head"])
def test_short_addition_next_to_line_only_lines_is_inserted(kind, journal, tmp_path):
    """校正で足された短い文字（「全部で」）のすぐ隣に、表の整数のセル 10 個（20 文字）か、3 ページ以上に出る 20 文字の柱が
    ある。行全体でしか一致させない行（0.19.0 では列から除いていた行）の文字は、PDF にだけある 20 文字以上の文字を足さない
    規則の長さに数えないので（0.19.0 と同じ）、「全部で」を今までどおり足す（表の数字・柱は足さない）。"""
    plan, src = small_article(tmp_path, journal, ADD_BODY)
    cut = ADD_PUB.index("全部で")
    if kind == "table-digits":
        cells = [str(10 + (k * 7) % 89) for k in range(10)]
        pages = ["\n".join(["（1）", *SMALL_FRONT, ADD_PUB[:cut], *cells, ADD_PUB[cut:], "引用および参考文献", SMALL_REF, *SMALL_EN])]
        ignored = cells
    else:
        pages = ["\n".join(["（1）", *SMALL_FRONT, ADD_PUB[:cut]]), "\n".join(["（2）", REPEATED_HEAD, ADD_PUB[cut:]]),
                 "\n".join(["（3）", REPEATED_HEAD, "引用および参考文献", SMALL_REF]), "\n".join(["（4）", REPEATED_HEAD, *SMALL_EN])]
        ignored = [REPEATED_HEAD]
    pc = compare(plan, pages)
    assert [(f.old, f.new, f.reason) for f in plan_fixes(plan, pc) if f.kind == "text"] == [("", "全部で", "")]
    assert pc.ignored_lines == [(src[ADD_BODY], x) for x in ignored]


LONG_BODY = "本稿は架空の授業を対象とする。授業は五回行った。記録の方法は次の節で述べる。"
LONG_ADDED = "なお，授業の記録は二人の観察者が別々に取り，後で照らし合わせた。"       # 校正で足された一文（20 文字以上）


def test_long_pdf_only_text_on_paragraph_line_is_reported(journal, tmp_path):
    """段落の途中の、PDF にだけある 20 文字以上の文字は、図の中の文字などの可能性が高いので足さない。段落の文字のある行に
    かかるとき（校正で足された一文かもしれない）は、黙って捨てずに、直さない違い（LONG_WHY）にして 13 章に出す。段落の
    文字のない行だけのとき（図の中の文字の行）は、今までどおり違いにしないが、照合に使わなかった文字として記録する
    （13 章の最後の一覧に載る）。"""
    from jasme_jats.pdfmatch import LONG_WHY
    plan, src = small_article(tmp_path, journal, LONG_BODY)
    lines = ["本稿は架空の授業を対象とする。授業は", "五回行った。" + LONG_ADDED[:15], LONG_ADDED[15:] + "記録の方",
             "法は次の節で述べる。"]
    pages = ["\n".join(["（1）", *SMALL_FRONT, *lines, "引用および参考文献", SMALL_REF, *SMALL_EN])]
    pc = compare(plan, pages)
    shown = LONG_ADDED[:15] + LINE_MARK + LONG_ADDED[15:]
    assert [(d.docx, d.pdf, d.fixable, d.why) for d in pc.diffs] == [("", shown, False, LONG_WHY)]
    assert [(f.old, f.new, f.reason) for f in plan_fixes(plan, pc) if f.kind == "text"] == [("", shown, LONG_WHY)]
    # 図の中の文字の行（段落の文字のない行）だけなら、違いにしない（照合に使わなかった文字として記録する）
    figure = ["図の中の架空の文字その一", "図の中の架空の文字その二"]
    cut = LONG_BODY.index("記録の")
    pages = ["\n".join(["（1）", *SMALL_FRONT, LONG_BODY[:cut], *figure, LONG_BODY[cut:], "引用および参考文献", SMALL_REF,
                        *SMALL_EN])]
    pc = compare(plan, pages)
    assert pc.diffs == [] and plan_fixes(plan, pc) == [] and pc.ignored_lines == [(src[LONG_BODY], x) for x in figure]


def test_long_pdf_only_text_on_other_paragraph_line_is_not_reported(journal, tmp_path):
    """段落の途中の、PDF にだけある 20 文字以上の文字が、ほかの段落（表のキャプション）の文字のある行にかかる（この段落の文字の
    ある行にはかからない）。図・表の中の文字とみなして、直さない違い（LONG_WHY）にはせず、照合に使わなかった文字として記録する
    （13 章の最後の一覧に載る）。"""
    extra = "に示した点の位置と名前と記号の一覧を表します"          # キャプションの行の後ろの、PDF にだけある 22 文字
    plan, src = table_article(tmp_path, journal, LONG_BODY, [["1組", "26"]])
    cut = LONG_BODY.index("記録の")
    pages = ["\n".join(["（1）", *SMALL_FRONT, LONG_BODY[:cut], TABLE_CAP + extra, LONG_BODY[cut:], NEXT_BODY, "引用および参考文献",
                        SMALL_REF, *SMALL_EN])]
    pc = compare(plan, pages)
    assert pc.unmatched == [] and pc.diffs == [] and plan_fixes(plan, pc) == []
    assert pc.ignored_lines == [(src[LONG_BODY], TABLE_CAP + extra)]


@pytest.mark.parametrize("route", ["docx", "pdf"])
def test_long_pdf_only_text_is_listed_in_report(route, journal, meta, tmp_path, monkeypatch):
    """PDF にだけある 20 文字以上の文字で、段落の文字のある行にかかるもの（LONG_WHY）は、ルート2 では直さずに 13.2 に、
    ルート1 では 13.1 に、その旨を添えて載せる（行の変わり目は LINE_MARK）。"""
    from jasme_jats.pdfmatch import LONG_WHY
    from jasme_jats.report import WHY_MARKS
    line = "架空の柱の文字列で十八文字ある行です"
    res = convert_with_pages(tmp_path, monkeypatch, journal, meta,
                             d12_pages(first=PUB12[:CUT] + "ＡＢＣ", start2=[line]), route)
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    shown = "ＡＢＣ" + LINE_MARK + line
    assert not any(line in t or "ＡＢＣ" in t for t in texts(load(res)))         # 足さない
    ch13 = chapters(res)[1]
    if route == "docx":
        section = ch13.split("### 13.1")[1].split("### 13.2")[0]
        assert f"| {shown}{WHY_MARKS[LONG_WHY]} |" in section
        # 添える文と列の見出しの文言（定数が空になっても気づけるように、文字列で確かめる）
        assert "PDF にだけある 20 文字以上の文字" in WHY_MARKS[LONG_WHY] and "| PDF（⏎ は行の変わり目） |" in section
    else:
        assert [(f.src, f.old, f.new, f.reason) for f in res.docx_fix.skipped] == [("d12", "", shown, LONG_WHY)]
        assert f"| {shown} | {LONG_WHY} |" in ch13.split("### 13.2")[1].split("### 13.3")[0]


SIMILAR_A = "架空省（2018a）．『架空学校学習指導要領（令和元年告示）解説　架空算数編』．架空文教出版．"
SIMILAR_B = "架空省（2018b）．『架空学校学習指導要領（令和元年告示）解説　架空総則編』．架空館出版社．"


@pytest.mark.parametrize("between", [["0", "10", "20", "30", "40", "50"], ["架空の比例の授業の分析"]],
                         ids=["figure-digits", "running-head"])
def test_similar_references_split_by_line_only_lines(between, journal, tmp_path):
    """同じ著者・同じ年で書名の始まりが同じ文献（2018a・2018b）の前の方が、ページの区切りで 2 行に分かれ、その間に図の目盛りの
    数字の行か 3 ページ以上に出る柱（行全体でしか一致させない行）がある。その行を除いた文字の上で照合するので（0.19.0 と
    同じ一致の塊）、後ろのよく似た文献と並べられず、ルート2 で文献の文字を消さない。"""
    plan, src = small_article(tmp_path, journal, BODY16, SIMILAR_A, SIMILAR_B)
    pages = ["\n".join(["（1）", *SMALL_FRONT, BODY16, "引用および参考文献", SMALL_REF, SIMILAR_A[:24]]),
             "\n".join(["（2）", *between, SIMILAR_A[24:], SIMILAR_B[:24], SIMILAR_B[24:], *SMALL_EN[:3]]),
             "\n".join(["（3）", *between[-1:], *SMALL_EN[3:]]), "\n".join(["（4）", *between[-1:], "End"])]
    pc = compare(plan, pages)
    assert pc.unmatched == [] and pc.diffs == [] and plan_fixes(plan, pc) == []
    assert pc.ignored_lines == [(src[SIMILAR_A], x) for x in between]


@pytest.mark.parametrize("between", [["0", "10", "20", "30", "40", "50"], ["架空の比例の授業の分析"]],
                         ids=["figure-digits", "running-head"])
def test_similar_references_after_whole_line_match(between, journal, tmp_path):
    """同じ形（よく似た文献 A・B の A の後ろの方が、ページの区切りと、図の目盛りの数字の行か 3 ページ以上に出る柱で分かれる）で、
    A の前の方に、行全体で一致させる「p.」の改行の後の「16」の行がある。行全体で一致させた行の後ろを照合し直すときも、
    行全体でしか一致させない行を除いて照合するので、A が B と並べられず、ルート2 で A の文字を消さない。"""
    ref_a = SIMILAR_A.replace("）．『", "）．p.16．『")
    ref_b = SIMILAR_B.replace("）．『", "）．p.16．『")
    plan, src = small_article(tmp_path, journal, BODY16, ref_a, ref_b)
    at, cut = ref_a.index("16"), ref_a.index("解説")
    pages = ["\n".join(["（1）", *SMALL_FRONT, BODY16, "引用および参考文献", SMALL_REF, ref_a[:at], ref_a[at:at + 2],
                        ref_a[at + 2:cut]]),
             "\n".join(["（2）", *between, ref_a[cut:], ref_b[:24], ref_b[24:], *SMALL_EN[:3]]),
             "\n".join(["（3）", *between[-1:], *SMALL_EN[3:]]), "\n".join(["（4）", *between[-1:], "End"])]
    pc = compare(plan, pages)
    assert pc.unmatched == [] and pc.diffs == [] and plan_fixes(plan, pc) == []
    assert pc.ignored_lines == [(src[ref_a], x) for x in between]


def test_heading_number_after_table_digits_is_matched(journal, tmp_path):
    """表のキャプションと数字のセル（docx にない表）のすぐ後ろに、見出しの番号「（1）」だけの行がある（柱のない本誌の形）。
    続いた数字だけの行の最後の行だけで docx の見出しが始まるので、その行だけを行全体で一致させる（ルート2 で見出しの番号を
    消さず、表の文字を見出しに入れない）。"""
    heading, body2 = "（1）架空の授業の分析の方法と記録の観点", "次に，記録した発言を三つの観点から分類し，それぞれの件数を述べる。"
    mf.make_article(tmp_path / "heading.docx", "ページ番号の判定の検証用文書",
                    lambda b: [mf.para(mf.S["sec1"], "１．はじめに"), mf.para(mf.S["body"], BODY16),
                               mf.para(mf.S["sec2"], heading), mf.para(mf.S["body"], body2)])
    _, plan, _ = _mechanical(tmp_path / "heading.docx", journal)
    pages = ["\n".join(["（1）", *SMALL_FRONT, BODY16, "表１　架空の得点", "1組", "27", "16", "2組", "14", "9", "（1）", heading[3:],
                        body2, "引用および参考文献", SMALL_REF, *SMALL_EN])]
    pc = compare(plan, pages)
    assert pc.unmatched == [] and pc.diffs == [] and plan_fixes(plan, pc) == []


def test_fullwidth_hyphen_and_line_end_hyphen_are_width_difference(journal, tmp_path):
    """docx の全角の「－」と、PDF の英数字の後の行末の半角の「-」（引用文献の「pp.11-」の改行の後の「16」）は、今までどおり
    全角・半角の違いとして直す（docx のハイフンと行末のハイフンを同じ文字とみなすのは、全角・半角が同じときだけ）。"""
    ref = REF16.replace("pp.11-16", "pp.11－16")
    plan, src = small_article(tmp_path, journal, BODY16, ref)
    pages = ["\n".join(["（1）", *SMALL_FRONT, BODY16, "引用および参考文献", SMALL_REF, REF16[:-2], REF16[-2:], *SMALL_EN])]
    pc = compare(plan, pages)
    assert pc.diffs == [] and pc.width == {src[ref]: {ref.index("－"): "-"}}
    assert [(f.old, f.new, f.kind) for f in plan_fixes(plan, pc) if f.src == src[ref]] == [("－", "-", "width")]


HYPHEN_BODY ="本稿では，架空の授業で生徒が self-explanation を用いて二つの量を比べた場面を分析する。"


@pytest.mark.parametrize("docx_hyphen, pdf_lines", [
    ("-", ["本稿では，架空の授業で生徒が self\ufffeexplanation を用いて二つの量を", "比べた場面を分析する。"]),
    ("-", ["本稿では，架空の授業で生徒が self\u00adexplanation を用いて二つの量を", "比べた場面を分析する。"]),
    ("-", ["本稿では，架空の授業で生徒が self\x02explanation を用いて二つの量を", "比べた場面を分析する。"]),
    ("-", ["本稿では，架空の授業で生徒が self-", "explanation を用いて二つの量を比べた場面を分析する。"]),
    ("‐", ["本稿では，架空の授業で生徒が self\ufffeexplanation を用いて二つの量を", "比べた場面を分析する。"]),
    ("‐", ["本稿では，架空の授業で生徒が self-", "explanation を用いて二つの量を比べた場面を分析する。"]),
    ("", ["本稿では，架空の授業で生徒が self\ufffeexplanation を用いて二つの量を", "比べた場面を分析する。"]),
], ids=["fffe", "shy", "stx", "ascii", "u2010-fffe", "u2010-ascii", "hyphenation"])
def test_real_hyphen_at_line_end_is_kept(docx_hyphen, pdf_lines, journal, tmp_path):
    """英文の本当のハイフン（self-explanation）が PDF で行末に来て、行末のハイフン（pdfium の U+FFFE など、英数字の後の行末の
    「-」）になっても、docx のハイフン（「-」「‐」）を消さない（同じ位置に並ぶので同じ文字とみなす。docx のまま）。docx に
    ハイフンがない（行末のハイフネーション）ときは、今までどおり足さない。"""
    body = HYPHEN_BODY.replace("-", docx_hyphen)
    plan, _ = small_article(tmp_path, journal, body)
    pages = ["\n".join(["（1）", *SMALL_FRONT, *pdf_lines, "引用および参考文献", SMALL_REF, *SMALL_EN])]
    pc = compare(plan, pages)
    assert pc.unmatched == [] and pc.diffs == [] and plan_fixes(plan, pc) == [] and pc.ignored_lines == []


def test_body_date_correction_is_fixed(journal, tmp_path):
    """本文の中の日付（「…日受付分」。投稿受付日の形ではない）が出版版で直されていれば、今までどおり直す。"""
    body = "架空の調査では，申込みは2020年８月30日受付分までを対象とし，回答は二回に分けて集めた。"
    plan, _ = small_article(tmp_path, journal, body)
    pages = ["\n".join(["（1）", *SMALL_FRONT, body.replace("30日", "31日"), "引用および参考文献", SMALL_REF, *SMALL_EN])]
    pc = compare(plan, pages)
    assert [(f.old, f.new, f.reason) for f in plan_fixes(plan, pc) if f.kind == "text"] == [("0", "1", "")]
    assert pc.ignored_lines == []


def test_received_date_in_docx_is_compared(journal, tmp_path):
    """docx に投稿受付日などと同じ文字の段落があれば、その段落に当たるので照合に使う（照合に使わなかった文字にしない）。"""
    body = "本稿は，" + R1 + "の原稿を改めたものである。"
    plan, _ = small_article(tmp_path, journal, body, REF16)
    cut = body.index("2025年11月")
    pages = ["\n".join(["（1）", *SMALL_FRONT, body[:cut], body[cut:], "引用および参考文献", SMALL_REF, REF16, *SMALL_EN])]
    pc = compare(plan, pages)
    assert pc.unmatched == [] and pc.diffs == [] and plan_fixes(plan, pc) == [] and pc.ignored_lines == []


def test_real_fix_next_to_running_head(journal):
    """柱の隣の本当の直し（出版版で「基づく」→「もとづく」）は、柱を除いて今までどおり直す。ページの端の行でも、その行に
    段落に当たる文字があれば、校正で足された文字は今までどおり足す。"""
    pages = d12_pages(start2=["試験四郎"], second=PUB12[CUT:].replace("基づく", "もとづく", 1))
    pc, diffs, fixes = d12_result(journal, pages)
    assert diffs == [("基", "もと", True)] and fixes == [("基", "もと", "")] and pc.ignored_lines == [("d12", "試験四郎")]
    pc, diffs, fixes = d12_result(journal, d12_pages(second="さらに" + PUB12[CUT:]))     # 2 ページ目の最初の行
    assert diffs == [("", "さらに", True)] and fixes == [("", "さらに", "")] and pc.ignored_lines == []


def test_long_pdf_only_text_over_page_edge_is_not_inserted(journal):
    """段落の途中の、PDF にだけある 20 文字以上の文字（図の中の文字など）は、今までどおり足さない。その一部がページの端の行に
    かかって照合に使わない文字になっても、残りの文字を足さない（柱の候補などを除いたことで、足す文字が増えない）。"""
    d13 = PUBLISHED["d13"]
    cut = d13.index("授業は")
    figure = ["図中ラベルＡＢＣＤＥＦＧ", "図の中の文字その２", "図の中の文字その３"]      # 後ろの 2 行がページの最後の 2 行
    pages = ["\n".join(["（1）", *FRONT, PUB12, d13[:cut], *figure]),
             "\n".join(["（2）", d13[cut:], *REST[1:]])]
    plan = _plan(journal)
    pc = compare(plan, pages)
    assert [(d.src, d.docx, d.pdf) for d in pc.diffs] == [("d13", "資料", "付録")]
    assert [(f.old, f.new) for f in plan_fixes(plan, pc) if f.kind == "text"] == [("資料", "付録")]
    # どの段落にも当たらない残りの行（ページの途中の図の中の文字）も、照合に使わなかった文字として記録する
    assert pc.ignored_lines == [("d13", x) for x in figure]


def test_added_sentence_in_page_edge_line_is_only_reported(journal):
    """校正で足された一文: ページの途中の行なら今までどおり足す。ページの端の行にまるごと入ったものは、柱と区別できないので
    足さず、照合に使わなかった文字として記録する。"""
    added = "校正で足した一文である。"
    _, diffs, fixes = d12_result(journal, d12_pages(end1=[added, PUB12[CUT:], *REST[:2]], second="", rest=REST[2:]))
    assert diffs == [("", added, True)] and fixes == [("", added, "")]
    pc, diffs, fixes = d12_result(journal, d12_pages(start2=[added]))
    assert diffs == [] and fixes == [] and pc.ignored_lines == [("d12", added)]


def test_docx_text_only_against_running_head_is_not_fixed(journal):
    """PDF の側に柱とみなした行しかない位置で docx に文字がある（置き換え）: 直さず（fixable=False）、理由を付ける。
    PDF の文字は、行の変わり目に LINE_MARK（本文に出ない記号）を入れて示す（レポートで、照合に使わなかった行と本文の行を
    見分けられるように）。"""
    from jasme_jats.pdfmatch import HEAD_WHY
    plan = _plan(journal)
    pc = compare(plan, d12_pages(start2=["試験四郎", "ＸＸＸＸＸＸ"], second=PUB12[CUT + 3:]))   # 「基づく」が PDF にない
    d = next(d for d in pc.diffs if d.src == "d12")
    assert (d.docx, d.pdf, d.fixable, d.why) == ("基づく", "試験四郎" + LINE_MARK + "ＸＸＸＸＸＸ", False, HEAD_WHY)
    assert pc.ignored_lines == [("d12", "試験四郎"), ("d12", "ＸＸＸＸＸＸ")]
    fix = next(f for f in plan_fixes(plan, pc) if f.src == "d12" and f.kind == "text")
    assert (fix.old, fix.new, fix.reason) == ("基づく", "試験四郎" + LINE_MARK + "ＸＸＸＸＸＸ", HEAD_WHY)


def test_table_text_next_to_running_head_is_not_used(journal):
    """柱の候補などを除いた残りが、どの段落の文字とも一致しない行の文字（docx にない図・表の中の文字や、照合に使わない短い
    セルの文字）だけなら、その文字で docx を直さない。本誌の出版版 PDF では、ページの最後の表の文字の後に、次のページの
    最初の行がまるごと docx と違う段落があると、ページの端の行を除いた残りの表の文字で docx の文字を置き換えていた。
    残りの行（ページの途中の表の文字）も、照合に使わなかった文字として記録する（13 章の最後の一覧に載る）。"""
    from jasme_jats.pdfmatch import HEAD_WHY
    table = ["表見出しの行", "セルＡ１", "セルＢ２", "セルＣ３"]       # 後ろの 2 行が 1 ページ目の最後の 2 行
    plan = _plan(journal)
    pc = compare(plan, d12_pages(end1=table, start2=["ＸＸＸＸＸＸ"], second=PUB12[CUT + 3:]))   # 「基づく」が PDF にない
    d = next(d for d in pc.diffs if d.src == "d12")
    assert (d.docx, d.pdf, d.fixable, d.why) == ("基づく", LINE_MARK.join([*table, "ＸＸＸＸＸＸ"]), False, HEAD_WHY)
    fix = next(f for f in plan_fixes(plan, pc) if f.src == "d12" and f.kind == "text")
    assert (fix.old, fix.reason) == ("基づく", HEAD_WHY)
    assert pc.ignored_lines == [("d12", x) for x in [*table, "ＸＸＸＸＸＸ"]]
    # docx の側に文字がない位置でも、20 文字未満の表の文字を足さない
    pc, diffs, fixes = d12_result(journal, d12_pages(end1=table))
    assert diffs == [] and fixes == [] and pc.ignored_lines == [("d12", x) for x in table]


@pytest.mark.parametrize("head, both_pages", [("基づく架空の論文の柱です", True), ("基づく", False)],
                         ids=["two-page-head", "short-head"])
def test_head_starting_like_next_line_is_not_inserted(head, both_pages, journal):
    """ページの最初の柱（2 ページの記事の柱・8 文字未満の柱）の最初の文字が、その次の本文の行の最初の文字と同じ（「基づく」）。
    difflib は先にある柱の「基づく」と docx を一致させるが、PDF にだけある文字を行の境目にそろえるので、柱の行は段落に当たらず、
    柱の文字も本文の文字も docx に足さない（照合に使わなかった文字として記録する）。"""
    pc, diffs, fixes = d12_result(journal, d12_pages(top1="（1）\n" + head if both_pages else "（1）", start2=[head]))
    assert diffs == [] and fixes == [] and pc.ignored_lines == [("d12", head)]


SPLIT_BODY = "変化の割合は，観点ごとの特徴を明らかにした。本稿の分析は，説明の仕方を比べた。"
SPLIT_PUB = SPLIT_BODY.replace("本稿", "さらに，本稿")       # 校正で足された「さらに，」が、表とページの区切りで 2 つに分かれる
TABLE_LINES = ["表１　架空の得点", "1組", "26", "9", "2組", "66", "73"]      # docx にない表（キャプション・セル）


def test_caption_between_split_addition_is_not_inserted(journal, tmp_path):
    """校正で足された短い文字（「さらに，」）が、docx にない表（キャプションとセル）とページの区切りで「さら」と「に，」に分かれる。
    照合に使わない文字（表のセル・ページの端の行）のある範囲の、どの段落の文字とも一致しない行（キャプション）は、docx に
    足さない（足すのは段落に当たる行の「さら」と「に，」だけ）。キャプションも照合に使わなかった文字として記録する。"""
    plan, src = small_article(tmp_path, journal, SPLIT_BODY)
    cut = SPLIT_PUB.index("に，本稿")
    pages = ["\n".join(["（1）", *SMALL_FRONT, SPLIT_PUB[:cut], *TABLE_LINES]),
             "\n".join(["（2）", SPLIT_PUB[cut:], "引用および参考文献", SMALL_REF, *SMALL_EN])]
    pc = compare(plan, pages)
    assert [(f.old, f.new) for f in plan_fixes(plan, pc) if f.kind == "text"] == [("", "さらに，")]
    assert pc.ignored_lines == [(src[SPLIT_BODY], x) for x in TABLE_LINES]


def test_caption_starting_like_next_line_is_not_inserted(journal, tmp_path):
    """docx にない表のキャプション「表１…」が、段落の途中の「…式による」と「表現を…」の間にある（キャプションの最初の文字が、
    その次の本文の行の最初の文字と同じ）。PDF にだけある文字を行の境目にそろえるので、キャプションも表のセルも docx に足さない。"""
    body = "生徒の記述は，式による表現を見いだした。対応の見方は，問題の解決を述べた。"
    plan, src = small_article(tmp_path, journal, body)
    cut = body.index("表現")
    pages = ["\n".join(["（1）", *SMALL_FRONT, body[:cut], *TABLE_LINES, body[cut:], "引用および参考文献", SMALL_REF, *SMALL_EN])]
    pc = compare(plan, pages)
    assert pc.diffs == [] and plan_fixes(plan, pc) == []
    assert pc.ignored_lines == [(src[body], x) for x in TABLE_LINES]


def test_addition_slid_to_short_line_is_only_listed(journal, tmp_path):
    """限界（docs/DESIGN.md 4.4）: 校正で足された文字（「生徒の発言」→「生徒の記述の発言」の「記述の」）が、その前の docx の文字と
    同じ文字（「の」）で終わり、行の境目にそろえると短い行（PDF の行「の記述」）1 行だけになる。その行は段落に当たらないので、
    docx に足さない（0.19.0 は足していた）。13 章の最後の一覧に、そろえた後の行の文字が載る（本文なら手で直す）。直すときは、
    このテストを書き換える。"""
    body = "本稿では，架空の授業の記録を観点ごとに整理し，その特徴を三つに分けて考察したうえで，生徒の発言を述べる。"
    pub = body.replace("生徒の発言", "生徒の記述の発言")
    plan, src = small_article(tmp_path, journal, body)
    k = pub.index("の記述の発言")
    pages = ["\n".join(["（1）", *SMALL_FRONT, pub[:k], pub[k:k + 3], pub[k + 3:], "引用および参考文献", SMALL_REF, *SMALL_EN])]
    pc = compare(plan, pages)
    assert pc.unmatched == [] and pc.diffs == [] and plan_fixes(plan, pc) == []
    assert pc.ignored_lines == [(src[body], "の記述")]


FORWARD_BODY = "その結果を表１に示す。どちらの学級でも，対応の見方が後半に現れ，比の一定に気付く生徒が多かった。"
HEAD_BODY = "本稿では，生徒の記述は，式による表現を見いだした。対応の見方は，問題の解決を述べた。"


@pytest.mark.parametrize("body, cut, line, page_top", [
    (FORWARD_BODY, "に示す", "表１", False),          # docx にない表のキャプション（ページの途中の短い行）
    (FORWARD_BODY, "に示す", "表１", True),           # 同じ行が、次のページの最初の行
    (HEAD_BODY, "表現", "架空の式による", True),       # 次のページの最初の柱（8 文字未満）
], ids=["caption-mid-page", "caption-page-top", "head-page-top"])
def test_line_ending_like_previous_line_is_not_inserted(body, cut, line, page_top, journal, tmp_path):
    """段落を分断する行（docx にない表のキャプション・ページの最初の柱）の最後の文字が、その前の本文の行の最後の文字と同じ
    （「…その結果を表１」＋キャプション「表１」、「…式による」＋柱「架空の式による」）。difflib は docx の後ろの文字を、分断する
    行から続けて一致させるが、PDF にだけある文字を後ろへずらして行の境目にそろえるので、分断する行は段落に当たらず、docx に
    足さない（照合に使わなかった文字として記録する）。"""
    plan, src = small_article(tmp_path, journal, body)
    k = body.index(cut)
    tail = ["引用および参考文献", SMALL_REF, *SMALL_EN]
    pages = (["\n".join(["（1）", *SMALL_FRONT, body[:k]]), "\n".join(["（2）", line, body[k:], *tail])] if page_top
             else ["\n".join(["（1）", *SMALL_FRONT, body[:k], line, body[k:], *tail])])
    pc = compare(plan, pages)
    assert pc.unmatched == [] and pc.diffs == [] and plan_fixes(plan, pc) == []
    assert pc.ignored_lines == [(src[body], line)]


def test_ignored_line_is_recorded_without_invisible_chars(journal):
    """照合に使わなかった行は、PDF の目に見えない文字（行末のハイフンの印の U+FFFE など）を除いて記録する（レポートに出す）。"""
    pc, diffs, fixes = d12_result(journal, d12_pages(start2=["試験￾四郎\x02"]))
    assert diffs == [] and fixes == [] and pc.ignored_lines == [("d12", "試験四郎")]


def test_fix_next_to_head_only_position_is_applied(journal):
    """柱しかない位置（直さない）のすぐ近くにある本当の直し（「行った。」→「行ったのだ。」）は、まとめずに今までどおり直す。"""
    from jasme_jats.pdfmatch import HEAD_WHY
    d13 = PUBLISHED["d13"]
    cut = d13.index("２回")
    pages = ["\n".join(["（1）", *FRONT, PUB12, d13[:cut]]),
             "\n".join(["（2）", "試験四郎", d13[cut + 2:].replace("行った。", "行ったのだ。"), *REST[1:]])]
    plan = _plan(journal)
    pc = compare(plan, pages)
    assert [(d.docx, d.pdf, d.fixable, d.why) for d in pc.diffs if d.src == "d13"] == [
        ("資料", "付録", True, ""), ("2回", "試験四郎", False, HEAD_WHY), ("", "のだ", True, "")]
    assert [(f.old, f.new, f.reason) for f in plan_fixes(plan, pc) if f.src == "d13" and f.kind == "text"] == [
        ("資料", "付録", ""), ("2回", "試験四郎", HEAD_WHY), ("", "のだ", "")]
    assert pc.ignored_lines == [("d13", "試験四郎")]


def test_same_head_on_pages_is_recorded_once(journal):
    """同じ柱が段落の途中の複数のページにあっても 1 回だけ記録する。段落の切れ目にある柱は記録しない。"""
    cut2 = PUB12.index("（試験")
    pages = ["\n".join(["（1）", *FRONT, PUB12[:CUT]]),
             "\n".join(["（2）", "試験四郎", PUB12[CUT:cut2]]),
             "\n".join(["（3）", "試験四郎", PUB12[cut2:], *REST[:2]]),
             "\n".join(["（4）", "試験四郎", *REST[2:]])]                 # d14 と「引用および参考文献」の間
    pc, diffs, fixes = d12_result(journal, pages)
    assert diffs == [] and fixes == []
    assert pc.ignored_lines == [("d12", "試験四郎")]


def head_pages():
    """d12 の途中（2 ページ目の最初の行）と d13 の途中（3 ページ目の最初の行）に柱「試験四郎」がある PDF の文字。
    d13 の「２回」は PDF になく、その位置には柱しかない。"""
    d13 = PUBLISHED["d13"]
    cut13 = d13.index("２回")
    return ["\n".join(["（1）", *FRONT, PUB12[:CUT]]),
            "\n".join(["（2）", "試験四郎", PUB12[CUT:], d13[:cut13]]),
            "\n".join(["（3）", "試験四郎", d13[cut13 + 2:], *REST[1:]])]


def convert_with_pages(tmp_path, monkeypatch, journal, meta, pages, route, docx=PDFCHECK):
    """extract_pages の代わりに pages を PDF の文字として、docx を変換する（ZIP に入れる PDF は中身のないもの）。"""
    from jasme_jats import pdfmatch
    monkeypatch.setattr(pdfmatch, "extract_pages", lambda path: pages)
    (tmp_path / "dummy.pdf").write_bytes(b"%PDF-1.4\n")
    return convert(docx, meta, journal, Options(out_dir=tmp_path / route, pdf_path=tmp_path / "dummy.pdf", route=route,
                                                convert_metafiles=False))


def chapters(res):
    """レポートの冒頭（1 章まで）・13 章・14 章。"""
    report = res.report_path.read_text(encoding="utf-8")
    return report.split("## 2.")[0], report.split("\n## 13. ")[1].split("\n## 14. ")[0], report.split("\n## 14. ")[1]


@pytest.mark.parametrize("route", ["docx", "pdf"])
def test_running_heads_are_listed_in_report(route, journal, meta, tmp_path, monkeypatch):
    """柱は XML の本文に入らず、照合に使わなかった文字としてレポートの 13 章の最後に段落ごとに載る（冒頭の要約に件数、14 章に
    確かめる項目）。柱しかない位置の docx の文字（d13 の「2回」）は、ルート2 でも直さず、直さなかった理由を載せる
    （ルート1 では、PDF の側が照合に使わなかった文字だけであることを添える）。"""
    from jasme_jats.pdfmatch import HEAD_WHY
    from jasme_jats.report import IGNORED_NOTE, IGNORED_NOTE_ROUTE2, IGNORED_TITLE, WHY_MARK
    res = convert_with_pages(tmp_path, monkeypatch, journal, meta, head_pages(), route)
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    ignored = [("d12", "試験四郎"), ("d13", "試験四郎")]
    assert res.pdf_check.ignored_lines == ignored
    out = texts(load(res))
    head, ch13, ch14 = chapters(res)
    loc = res.plan.locations
    if route == "docx":
        assert ORIGINAL["d12"] in out
        assert [(d.src, d.docx, d.pdf, d.fixable, d.why) for d in res.pdf_check.diffs] == [
            ("d13", "資料", "付録", True, ""), ("d13", "2回", "試験四郎", False, HEAD_WHY)]
        assert f"| 2回 | 試験四郎{WHY_MARK} |" in ch13.split("### 13.1")[1].split("### 13.2")[0]
        assert "PDF の側は照合に使わなかった文字だけ" in WHY_MARK         # 添える文が空になっていない
        section = ch13.split(f"### 13.4 {IGNORED_TITLE}")[1]
    else:
        fx = res.docx_fix
        assert fx.check.ignored_lines == ignored
        assert [(f.src, f.old, f.new, f.reason) for f in fx.skipped] == [("d13", "2回", "試験四郎", HEAD_WHY)]
        assert PUBLISHED["d12"] in out and "詳しくは付録の学習指導案を参照されたい。授業は2回行った。" in out
        assert f"| 2回 | 試験四郎 | {HEAD_WHY} |" in ch13.split("### 13.2")[1].split("### 13.3")[0]
        section = ch13.split(f"### 13.6 {IGNORED_TITLE}")[1]
        # ルート2 では、ほかの段落にある文字でも、13.1 で元の段落から消していないかを確かめてもらう
        assert IGNORED_NOTE_ROUTE2 in section and "PDF に合わせて直した docx にも入れていません" in section
    assert "照合に使わなかった PDF の文字 2 件（2 段落。誌名の行・投稿受付日・表や図の中の文字などとみなしたもの。" in head
    assert "13 章で確認" not in head            # 要約の行の 13 章の案内は、行の最後の「（13 章）」だけ
    assert "13 章の最後の「照合に使わなかった PDF の文字」（2 件）に、docx にない本文" in ch14
    assert not any("試験四郎" in t for t in out if "架空理論" in t or "学習指導案" in t)
    assert IGNORED_NOTE in section
    assert f"| d12 | {loc['d12']} | 1 | 試験四郎 |" in section and f"| d13 | {loc['d13']} | 1 | 試験四郎 |" in section


def test_no_running_heads_in_report(journal, meta, tmp_path):
    """照合に使わなかった文字がなければ「ありません。」（冒頭の要約と 14 章にも出さない）。"""
    pytest.importorskip("pypdfium2")
    from jasme_jats.report import IGNORED_TITLE
    res = convert(PDFCHECK, meta, journal, Options(out_dir=tmp_path, pdf_path=PDFCHECK_PDF, route="pdf",
                                                   convert_metafiles=False))
    assert res.docx_fix.check.ignored_lines == [] and res.pdf_check.ignored_lines == []
    head, ch13, ch14 = chapters(res)
    assert f"### 13.6 {IGNORED_TITLE}\n\nありません。" in ch13
    assert "照合に使わなかった PDF の文字" not in head and "照合に使わなかった PDF の文字" not in ch14


def test_table_cells_are_listed_per_paragraph(journal, meta, tmp_path, monkeypatch):
    """段落の途中に入った表のセル（短い行・数字だけの行）は、13 章の一覧で段落ごとに 1 行にまとめる（数字だけの行は件数と
    最初のいくつか）。ルート2 でも段落の最後の行を消さない。"""
    body = "".join(SHORT_TAIL)
    grid = score_rows(6)
    mf.make_article(tmp_path / "table.docx", "ページ番号の判定の検証用文書", lambda b: [
        mf.para(mf.S["sec1"], "１．はじめに"), mf.para(mf.S["body"], body), mf.para(mf.S["tab_cap"], TABLE_CAP),
        mf.table([[mf.cell(c) for c in row] for row in grid]), mf.para(mf.S["body"], NEXT_BODY)])
    pages = ["\n".join(["（1）", *SMALL_FRONT, *SHORT_TAIL[:-1], TABLE_CAP, *[c for row in grid for c in row]]),
             "\n".join(["（2）", SHORT_TAIL[-1], NEXT_BODY, "引用および参考文献", SMALL_REF, *SMALL_EN])]
    res = convert_with_pages(tmp_path, monkeypatch, journal, meta, pages, "pdf", docx=tmp_path / "table.docx")
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    assert res.docx_fix.applied == [] and body in texts(load(res))
    src = next(s for s, p in res.plan.paras.items() if p.plain() == body)
    head, ch13, ch14 = chapters(res)
    assert "照合に使わなかった PDF の文字 42 件（1 段落。" in head
    labels = grid[0] + [row[0] for row in grid[1:]]                     # 見出しの行と組の列（短い行）
    numbers = [c for row in grid[1:] for c in row[1:]]                   # 得点のセル（数字だけの行）
    assert f"| 段落 | 場所 | 行数 | PDF の文字（{LINE_MARK} は行の変わり目） |" in ch13.split("### 13.6")[1]
    rows = [x for x in ch13.split("### 13.6")[1].splitlines() if x.startswith(f"| {src} |")]
    assert rows == [f"| {src} | {res.docx_fix.locations[src]} | 42 | " + LINE_MARK.join(labels) + LINE_MARK
                    + "数字だけの行 30 件: " + "、".join(numbers[:8]) + "… |"]


def test_location_of_paragraph_with_only_ignored_lines(journal, meta, tmp_path, monkeypatch):
    """ほかに直す箇所のない段落（d15）の途中の柱も、ルート2 の 13.6 に、元の docx の段落の場所付きで載る。"""
    d15 = "この段落は出版版と同じで，架空の資料を https://example.com/a で公開している。"
    cut = d15.index("架空の資料")
    pages = ["\n".join(["（1）", *FRONT, PUBLISHED["d12"], PUBLISHED["d13"], PUBLISHED["d14"], d15[:cut]]),
             "\n".join(["（2）", "試験四郎", d15[cut:], *REST[2:]])]
    res = convert_with_pages(tmp_path, monkeypatch, journal, meta, pages, "pdf")
    assert ("d15", "試験四郎") in res.docx_fix.check.ignored_lines
    assert not any(f.src == "d15" for f in res.docx_fix.fixes)
    loc = _mechanical(PDFCHECK, journal)[1].locations["d15"]          # 元の docx の段落の場所
    assert f"| d15 | {loc} | 1 | 試験四郎 |" in chapters(res)[1].split("### 13.6")[1]


def test_head_only_position_shows_pdf_lines_in_report(journal, meta, tmp_path, monkeypatch):
    """PDF の側に照合に使わなかった文字（投稿受付日と、どの段落にも当たらないページの端の行）しかない位置の docx の文字は
    直さず、13.2 に、PDF の文字を行の変わり目に LINE_MARK を入れて長めに出す（受付日の後ろの行まで見えるように。本文の
    「／」と見分けられるように、本文に出ない記号にし、列の見出しにも書く）。"""
    from jasme_jats.pdfmatch import HEAD_WHY
    from jasme_jats.report import PDF_COLUMN
    assert LINE_MARK == "⏎"           # 本文に出る「／」などと見分けられる記号（本文に出ない記号）
    pages = d12_pages(end1=[R1], start2=["ＸＸＸＸＸＸ"], second=PUB12[CUT + 3:])      # 「基づく」が PDF にない
    res = convert_with_pages(tmp_path, monkeypatch, journal, meta, pages, "pdf")
    shown = R1 + LINE_MARK + "ＸＸＸＸＸＸ"
    assert [(f.src, f.old, f.new, f.reason) for f in res.docx_fix.skipped] == [("d12", "基づく", shown, HEAD_WHY)]
    section = chapters(res)[1].split("### 13.2")[1].split("### 13.3")[0]
    assert f"| 基づく | {shown} | {HEAD_WHY} |" in section and f"| docx | {PDF_COLUMN} | 直さなかった理由 |" in section
    from jasme_jats.colab import pdf_diff_box                  # Colab の枠でも、行の変わり目の記号を説明する
    assert f"「{shown}」（{HEAD_WHY}。{LINE_MARK} は PDF の行の変わり目）" in pdf_diff_box(res)
