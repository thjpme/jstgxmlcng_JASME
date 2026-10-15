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


def test_page_number_only_at_page_edge():
    """N9: ページ番号として除くのは、ページの最初か最後の行の数字だけの行（1 ページに 1 つ）。ページの途中の数字だけの行
    （引用文献の「pp.11-」の後の「16」、表のセル）は除かず、柱の候補の行にする。"""
    from jasme_jats.pdfmatch import pdf_stream
    st = pdf_stream(["（25）\n最初の行です。\n2 行目です。\n27\n途中の行です。\n最後から 2 行目です。\n最後の行です。\n"])
    assert "".join(st.chars) == "最初の行です。2行目です。27途中の行です。最後から2行目です。最後の行です。"   # ページ番号を除く
    lines = [(st.lines[st.line[k]], st.edge[k], st.head[k]) for k in range(len(st.chars))]
    assert list(dict.fromkeys(lines)) == [
        ("最初の行です。", True, True), ("2 行目です。", True, True), ("27", False, True),    # 数字だけの行は柱の候補
        ("途中の行です。", False, False), ("最後から 2 行目です。", True, True), ("最後の行です。", True, True)]
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


def test_repeated_line_only_removed_at_page_edge(journal, tmp_path):
    """3 ページ以上に同じ文字列で出る 8 文字以上の行（柱）を列から除くのは、ページの端の行だけ。ページの途中の同じ文字列の
    行（引用文献の誌名の行など）は除かず、段落に当たれば照合に使う。"""
    from jasme_jats.pdfmatch import pdf_stream
    head = "全国数学教育学会誌　数学教育学研究"
    ref = "架空次郎（2018）．「架空の題目」．全国数学教育学会誌　数学教育学研究，第24巻，pp.1-10．"
    ref2 = "見本三郎（2019）．「見本の題目」．『見本誌』，第3巻，pp.5-8．"
    plan, _ = small_article(tmp_path, journal, BODY16, ref, ref2)
    at = ref.index(head)
    pages = ["\n".join(["（1）", head, *SMALL_FRONT, BODY16]),
             "\n".join(["（2）", head, "引用および参考文献", SMALL_REF, ref[:at], head, ref[at + len(head):], ref2]),
             "\n".join(["（3）", head, *SMALL_EN])]
    st = pdf_stream(pages)
    kept = {(st.lines[st.line[k]], st.edge[k], st.head[k]) for k in range(len(st.chars))}
    assert {x for x in kept if x[0] == head} == {(head, False, True)}       # ページの途中の 1 行だけが残る
    pc = compare(plan, pages)
    assert pc.unmatched == [] and pc.diffs == [] and plan_fixes(plan, pc) == [] and pc.ignored_lines == []


def test_line_only_marks():
    """ページの途中の数字だけの行（前の行の続きを除く）と、何ページにも出る行（0.19.0 では列から除いていた行）は、行全体で
    しか docx の文字と一致させない行（line_only）。引用文献の「pp.11-」の改行の後の「16」は、前の行の続きなので普通の行。
    短い行（図の中の点の名前など）は柱の候補にするが、行全体でしか一致させない行にはしない。"""
    from jasme_jats.pdfmatch import pdf_stream
    head = "何ページにも出る架空の行"
    pages = ["\n".join(["（1）", head, "本文の行です。", "27", "pp.11-", "16", "A", head, "本文の最後の行です。", "最後の行です。"]),
             "\n".join(["（2）", head, "本文の行です。"]), "\n".join(["（3）", head, "本文の行です。"])]
    st = pdf_stream(pages)
    marks = {(st.lines[st.line[k]], st.edge[k], st.head[k], st.line_only[k]) for k in range(len(st.chars))}
    assert {x for x in marks if x[0] in ("27", "16", "A", head)} == {
        ("27", False, True, True), ("16", False, True, False), ("A", False, True, False), (head, False, True, True)}


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
    使わない文字を除く前で数える。0.19.0 と同じく、足す文字が増えない）。"""
    pages = d12_pages(first=PUB12[:CUT] + "ＡＢＣ", start2=["架空の柱の文字列で十八文字ある行です"])
    pc, diffs, fixes = d12_result(journal, pages)
    assert diffs == [] and fixes == []
    assert pc.ignored_lines == [("d12", "架空の柱の文字列で十八文字ある行です")]


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
    assert pc.ignored_lines == [("d13", figure[1]), ("d13", figure[2])]


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
    PDF の文字は、行の変わり目に「／」を入れて示す（レポートで、照合に使わなかった行と本文の行を見分けられるように）。"""
    from jasme_jats.pdfmatch import HEAD_WHY
    plan = _plan(journal)
    pc = compare(plan, d12_pages(start2=["試験四郎", "ＸＸＸＸＸＸ"], second=PUB12[CUT + 3:]))   # 「基づく」が PDF にない
    d = next(d for d in pc.diffs if d.src == "d12")
    assert (d.docx, d.pdf, d.fixable, d.why) == ("基づく", "試験四郎／ＸＸＸＸＸＸ", False, HEAD_WHY)
    assert pc.ignored_lines == [("d12", "試験四郎"), ("d12", "ＸＸＸＸＸＸ")]
    fix = next(f for f in plan_fixes(plan, pc) if f.src == "d12" and f.kind == "text")
    assert (fix.old, fix.new, fix.reason) == ("基づく", "試験四郎／ＸＸＸＸＸＸ", HEAD_WHY)


def test_table_text_next_to_running_head_is_not_used(journal):
    """柱の候補などを除いた残りが、どの段落の文字とも一致しない行の文字（docx にない図・表の中の文字や、照合に使わない短い
    セルの文字）だけなら、その文字で docx を直さない。本誌の出版版 PDF では、ページの最後の表の文字の後に、次のページの
    最初の行がまるごと docx と違う段落があると、ページの端の行を除いた残りの表の文字で docx の文字を置き換えていた。"""
    from jasme_jats.pdfmatch import HEAD_WHY
    table = ["表見出しの行", "セルＡ１", "セルＢ２", "セルＣ３"]       # 後ろの 2 行が 1 ページ目の最後の 2 行
    plan = _plan(journal)
    pc = compare(plan, d12_pages(end1=table, start2=["ＸＸＸＸＸＸ"], second=PUB12[CUT + 3:]))   # 「基づく」が PDF にない
    d = next(d for d in pc.diffs if d.src == "d12")
    assert (d.docx, d.pdf, d.fixable, d.why) == ("基づく", "／".join(table) + "／ＸＸＸＸＸＸ", False, HEAD_WHY)
    fix = next(f for f in plan_fixes(plan, pc) if f.src == "d12" and f.kind == "text")
    assert (fix.old, fix.reason) == ("基づく", HEAD_WHY)
    assert pc.ignored_lines == [("d12", table[2]), ("d12", table[3]), ("d12", "ＸＸＸＸＸＸ")]
    # docx の側に文字がない位置でも、20 文字未満の表の文字を足さない
    pc, diffs, fixes = d12_result(journal, d12_pages(end1=table))
    assert diffs == [] and fixes == [] and pc.ignored_lines == [("d12", table[2]), ("d12", table[3])]


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
    from jasme_jats.report import IGNORED_NOTE, IGNORED_TITLE, WHY_MARK
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
        section = ch13.split(f"### 13.4 {IGNORED_TITLE}")[1]
    else:
        fx = res.docx_fix
        assert fx.check.ignored_lines == ignored
        assert [(f.src, f.old, f.new, f.reason) for f in fx.skipped] == [("d13", "2回", "試験四郎", HEAD_WHY)]
        assert PUBLISHED["d12"] in out and "詳しくは付録の学習指導案を参照されたい。授業は2回行った。" in out
        assert f"| 2回 | 試験四郎 | {HEAD_WHY} |" in ch13.split("### 13.2")[1].split("### 13.3")[0]
        section = ch13.split(f"### 13.6 {IGNORED_TITLE}")[1]
        assert "PDF に合わせて直した docx にも入れていません" in section
    assert "照合に使わなかった PDF の文字 2 件（2 段落。誌名の行・投稿受付日・表や図の中の文字などとみなしたもの。" in head
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
    rows = [x for x in ch13.split("### 13.6")[1].splitlines() if x.startswith(f"| {src} |")]
    assert rows == [f"| {src} | {res.docx_fix.locations[src]} | 42 | " + "／".join(labels) + "／数字だけの行 30 件: "
                    + "、".join(numbers[:8]) + "… |"]


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
    直さず、13.2 に、PDF の文字を行の変わり目に「／」を入れて長めに出す（受付日の後ろの行まで見えるように）。"""
    from jasme_jats.pdfmatch import HEAD_WHY
    pages = d12_pages(end1=[R1], start2=["ＸＸＸＸＸＸ"], second=PUB12[CUT + 3:])      # 「基づく」が PDF にない
    res = convert_with_pages(tmp_path, monkeypatch, journal, meta, pages, "pdf")
    assert [(f.src, f.old, f.new, f.reason) for f in res.docx_fix.skipped] == [("d12", "基づく", R1 + "／ＸＸＸＸＸＸ", HEAD_WHY)]
    assert f"| 基づく | {R1}／ＸＸＸＸＸＸ | {HEAD_WHY} |" in chapters(res)[1].split("### 13.2")[1].split("### 13.3")[0]
