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
from jasme_jats.pdfdocx import (AUTHOR, Fix, _apply_paragraph, _Writer, expected_text, paragraph_units, plan_fixes,
                                 tracked_counts)
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
    """docx の本文の段落の文字。reject=True なら、このツールの変更履歴をすべて却下した文字（挿入を除き、削除を戻す）。
    Word の改行なしハイフン（w:noBreakHyphen）は、読み取りと同じく「‑」。"""
    root = parse_xml(zipfile.ZipFile(docx).read("word/document.xml"))
    out = []
    for p in root.iter(w("p")):
        s = []
        for t in p.iter(w("t"), w("delText"), w("noBreakHyphen")):
            mark = next((a for a in t.iterancestors(w("ins"), w("del"))), None)
            ours = mark is not None and mark.get(w("author")) == AUTHOR
            if t.tag == w("noBreakHyphen"):
                deleted = mark is not None and mark.tag == w("del")
                if (reject and ours) if deleted else not (reject and ours and mark.tag == w("ins")):
                    s.append("‑")
            elif t.tag == w("t") and not (reject and ours and mark.tag == w("ins")):
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


def test_tracked_changes_replace_no_break_hyphen():
    """Word の改行なしハイフン（w:noBreakHyphen。読み取りでは「‑」）は、要素ごと削除の変更履歴にして、PDF の文字（「-」）を挿入
    する（ダッシュ・ハイフンの仲間を PDF に合わせる。ランの書式はそのまま。同じランの w:t の直しも書き込める）。"""
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    p = etree.fromstring(f'<w:p xmlns:w="{ns}"><w:r><w:rPr><w:i/></w:rPr><w:t>pp.63</w:t><w:noBreakHyphen/>'
                         '<w:t>69.</w:t></w:r></w:p>')
    units = paragraph_units(p)
    assert "".join(c for c, _, _ in units) == "pp.63‑69."
    fixes = [Fix("d1", 5, 6, "-", "text", "‑"), Fix("d1", 8, 9, "．", "width", ".")]
    _apply_paragraph(units, fixes, _Writer("2026-01-01T00:00:00Z"))
    assert [f.applied for f in fixes] == [True, True]
    got = []
    for el in p:
        kind = {w("ins"): "ins", w("del"): "del"}.get(el.tag, "keep")
        r = el if kind == "keep" else el.find(w("r"))
        assert r.find(f"{w('rPr')}/{w('i')}") is not None
        t = r.find(w("delText") if kind == "del" else w("t"))
        got.append((kind, "‑" if r.find(w("noBreakHyphen")) is not None else t.text))
    assert got == [("keep", "pp.63"), ("del", "‑"), ("ins", "-"), ("keep", "69"), ("del", "."), ("ins", "．")]


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
    ("", ["本稿では，架空の授業で生徒が self\ufffeexplanation を用いて二つの量を", "比べた場面を分析する。"]),
], ids=["fffe", "shy", "stx", "ascii", "u2010-fffe", "hyphenation"])
def test_real_hyphen_at_line_end_is_kept(docx_hyphen, pdf_lines, journal, tmp_path):
    """英文の本当のハイフン（self-explanation）が PDF で行末に来て、行末のハイフン（pdfium の U+FFFE など、英数字の後の行末の
    「-」）になっても、docx のハイフン（「-」「‐」）を消さない（同じ位置に並ぶので同じ文字とみなす。docx のまま）。docx に
    ハイフンがない（行末のハイフネーション）ときは、今までどおり足さない。docx の「‐」と PDF の行末の「-」のように、PDF の
    行末の文字が docx と違う「-」「‐」なら、PDF に合わせて直す（test_hyphen_variant_at_line_end_follows_pdf）。"""
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
    """校正で足された一文: ページの途中の行でも、ページの端の行でも、段落の途中に行まるごと PDF にだけある文字は足さず、
    照合に使わなかった文字として記録する（13 章の最後の一覧）。

    0.20.0 は、ページの途中の行にまるごと入った一文は足していた。段落の途中の本文の行は両端そろえで行の幅いっぱいになり、
    校正で足された文は前後の行の組み直しになる（行の途中から始まる）ので、段落の途中の、行まるごと PDF にだけある短い文字は、
    docx にない図・表の中の文字（キャプション・軸の名前など）と区別できない（足すと図表の文字が本文に入る）。ページの端の行に
    まるごと入ったものは、柱と区別できないので、0.20.0 から足していない。"""
    added = "校正で足した一文である。"
    pc, diffs, fixes = d12_result(journal, d12_pages(end1=[added, PUB12[CUT:], *REST[:2]], second="", rest=REST[2:]))
    assert diffs == [] and fixes == [] and ("d12", added) in pc.ignored_lines
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


# ---------------------------------------------------------------------------- N10: PDF の中で分断された段落（まとめての照合）
# PDF の中で段落が表・図の中の文字・ほかの段落（2 段組みの読み順のずれ）に分断されると、0.20.0 は段落の後ろ（前）を照合の
# 窓の外に出して窓の中のほかの文字と並べ、ルート2 で docx の本文を消したり置き換えたりしていた。まとめての照合（_joint）では、
# 分断された部分も段落の文字として照合する。PDF の文字は、1 行 24 文字ほどに分けて作る（形だけを本誌の出版版 PDF にまねる）。
def wrap_lines(text, width=24, kinsoku=False):
    """本誌の 1 行の長さで行に分ける（全角の文字を 1、半角の文字を 0.5 と数える）。kinsoku なら、行の最初に来る句読点・閉じ
    かっこを前の行の最後にぶら下げる。"""
    import unicodedata
    lines, cur, n = [], "", 0.0
    for c in text:
        cw = 1.0 if unicodedata.east_asian_width(c) in ("F", "W", "A") else 0.5
        if cur and n + cw > width and not (kinsoku and c in "，。、．）」』！？"):
            lines.append(cur)
            cur, n = "", 0.0
        cur += c
        n += cw
    return lines + ([cur] if cur else [])


def body_lines(text, kinsoku=False):
    """本文の段落の PDF の行（1 行目は全角の空白で字下げ）。"""
    return wrap_lines("　" + text, kinsoku=kinsoku)


def n10_article(tmp_path, journal, blocks, refs=(), title="ページ番号の判定の検証用文書"):
    """「１．はじめに」の後ろに本文の段落の並び blocks（[(スタイル, 文字)]。文字の代わりに部品のリストも書ける〈数式など〉。
    スタイル "table" は文字の代わりにセルの文字の行のリスト、"image" は画像だけの段落〈文字は画像の名前〉）と、引用文献
    SMALL_REF の後ろに refs がある小さな論文の構造と、段落の文字 -> 段落 ID。"""
    def parts(b):
        out = [mf.para(mf.S["sec1"], "１．はじめに")]
        for style, x in blocks:
            if style == "table":
                out.append(mf.table([[mf.cell(c) for c in row] for row in x]))
            elif style == "image":
                img = b.add_image(f"{x or 'fig'}.png", mf.png_bytes(x or "Figure"))
                out.append(mf.para(mf.S["body"], mf.drawing(img, 1440000, 900000, 300 + len(out)), jc="center"))
            else:
                out.append(mf.para(mf.S[style], *([x] if isinstance(x, str) else x)))
        return out
    mf.make_article(tmp_path / "n10.docx", title, parts, refs=lambda b: [mf.para(mf.S["ref"], r) for r in refs])
    _, plan, _ = _mechanical(tmp_path / "n10.docx", journal)
    return plan, {p.plain(): p.src for p in plan.paras.values()}


def n10_pages(*page_lines):
    """ページごとの行のリストから、PDF の各ページの文字（最初の行にページ番号「（n）」）。"""
    return ["\n".join([f"（{n}）", *ls]) for n, ls in enumerate(page_lines, 1)]


def fixed_texts(plan, pc):
    """直す箇所（理由のないもの）をすべて当てはめた段落の文字（ルート2 で直した docx の段落）: 段落 ID -> 文字。"""
    fx = plan_fixes(plan, pc)
    return {s: expected_text(p.plain(), [f for f in fx if f.src == s and not f.reason]) for s, p in plan.paras.items()}


def changed_paragraphs(plan, pc, want):
    """直した後の文字が、want（段落 ID -> 出版版の文字）の段落では want の文字、それ以外の段落では docx の文字と違う段落。"""
    got = fixed_texts(plan, pc)
    return {s: t for s, t in got.items() if t != want.get(s, plan.paras[s].plain())}


def text_fixes(plan, pc, src):
    """段落 src の、文字の違いの直す箇所 (docx, PDF, 直さなかった理由)。"""
    return [(f.old, f.new, f.reason) for f in plan_fixes(plan, pc) if f.src == src and f.kind == "text"]


LESSON_HEAD = ("第三時の授業では，教師はまず前時に作った表を黒板に掲げ，水を入れる時間と水の深さの関係を振り返らせた。"
               "続いて，表の隣り合う値の間に矢印をかき，増え方を書き込む活動を示した。")
LESSON_TAIL = "最後に，教師は時間が３倍になると深さがどうなるかを問い，生徒どうしで説明し合う時間を取った。"
LESSON = LESSON_HEAD + LESSON_TAIL
TALK = "話し合いの中で，ある生徒は時間が３倍になると深さも３倍になると述べ，別の生徒は理由を付け加えた。"
SURVEY = ("授業の前に行った事前の調査では，表を横に見て増え方を答えられた生徒は学級の半数ほどであった。一方で，表を縦に"
          "見て二つの量の対応を答えられた生徒は一割に満たなかった。このことから，多くの生徒は一方の量の変化だけに目を向けて"
          "いたと考えられる。事前の調査の問題は，教科書の練習問題をもとに架空の数値に置き換えて作った。")
N10_TAIL = ["引用および参考文献", SMALL_REF, *SMALL_EN]


@pytest.mark.parametrize("edit", [False, True])
def test_tail_after_other_paragraph_is_kept(edit, journal, tmp_path):
    """PDF の中で、段落の最後の文の前に、docx では 2 つ後ろの段落（2 段組みの読み順のずれ。約 170 文字）が入る。最後の文を
    消したり、ほかの段落の文字に置き換えたりしない。最後の文に校正の直しがあれば直す（0.20.0 は窓の外に出して消していた）。"""
    docx = LESSON.replace("時間を取った", "時間を設けた") if edit else LESSON
    plan, src = n10_article(tmp_path, journal, [("body", docx), ("body", TALK), ("body", SURVEY)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, *body_lines(LESSON_HEAD), *body_lines(SURVEY), *wrap_lines(LESSON_TAIL),
                                  *body_lines(TALK), *N10_TAIL]))
    assert changed_paragraphs(plan, pc, {src[docx]: LESSON}) == {}


@pytest.mark.parametrize("cut", [5, 7])
def test_tail_after_next_paragraph_is_kept(cut, journal, tmp_path):
    """PDF の中で、段落の最後の 5〜7 文字（アンカーにならない長さ）の前に、docx ですぐ後ろの段落が入る（2 段組みの読み順の
    ずれ）。段落の最後を消さない。"""
    plan, src = n10_article(tmp_path, journal, [("body", LESSON), ("body", TALK), ("body", SURVEY)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, *body_lines(LESSON[:-cut]), *body_lines(TALK), LESSON[-cut:],
                                  *body_lines(SURVEY), *N10_TAIL]))
    assert changed_paragraphs(plan, pc, {}) == {}


@pytest.mark.parametrize("rows, split, edit", [(20, "line", False), (100, "line", True), (100, "sentence", True)])
def test_tail_after_long_table_is_kept(rows, split, edit, journal, tmp_path):
    """PDF の中で、段落の最後の行（最後の文）の前に、docx ではその段落の後ろにある表（キャプションと 20〜100 行のセル。
    約 140〜620 文字）が入る。段落の最後の行を消したり、表の文字に置き換えたりせず、表の文字を足さない。最後の文に校正の
    直しがあれば直す（0.20.0 は、最後の行を窓の外に出して消すか、表が長いと最後の文の直しを黙って直さなかった）。"""
    cells = [[f"{chr(0xFF21 + k % 26)}組", str(10 + (k * 7) % 23), str(5 + (k * 11) % 17)] for k in range(rows)]
    docx = LESSON.replace("時間を取った", "時間を設けた") if edit else LESSON
    plan, src = n10_article(tmp_path, journal, [("body", docx), ("tab_cap", "表１　架空の学級ごとの記述の数"),
                                                ("table", cells), ("body", TALK)])
    lines = ["表１　架空の学級ごとの記述の数"] + [" ".join(r) for r in cells]
    first, second = (body_lines(LESSON)[:-1], body_lines(LESSON)[-1:]) if split == "line" else \
        (body_lines(LESSON_HEAD), wrap_lines(LESSON_TAIL))
    pc = compare(plan, n10_pages([*SMALL_FRONT, *first, *lines, *second, *body_lines(TALK), *N10_TAIL]))
    assert changed_paragraphs(plan, pc, {src[docx]: LESSON}) == {}


def test_short_tail_after_table_is_kept(journal, tmp_path):
    """段落の最後の 4 文字（「取った。」の 1 行）が、表の後ろ（次の段落の前）に出る。消さない。"""
    cells = [["Ａ組", "12", "7"], ["Ｂ組", "19", "16"], ["Ｃ組", "26", "8"]]
    plan, src = n10_article(tmp_path, journal, [("body", LESSON), ("tab_cap", "表１　架空の学級ごとの記述の数"),
                                                ("table", cells), ("body", TALK)])
    lines = ["表１　架空の学級ごとの記述の数"] + [" ".join(r) for r in cells]
    pc = compare(plan, n10_pages([*SMALL_FRONT, *body_lines(LESSON[:-4]), *lines, LESSON[-4:], *body_lines(TALK),
                                  *N10_TAIL]))
    assert changed_paragraphs(plan, pc, {}) == {}


SHORT_CELLS = [["Ａ組", "12", "7"], ["Ｂ組", "19", "16"]]
SHORT_CAP = "表１　記述の数"
NOTE20 = "この点は次の節で改めて詳しく述べる。"


TAIL_EDITS = [(4, "持った。"), (3, "てた。"), (6, "間を取る。"), (7, "時間を設けた。")]


def split_tail_blocks(split):
    """段落 LESSON の最後の数文字を分断するもの: (docx の段落の並び, PDF の分断する行, PDF の次の段落の行)。split は
    "table"（docx ではすぐ後ろの表。約 20 文字）か "paragraph"（docx では 2 つ後ろの段落。2 段組みの読み順のずれ）。"""
    if split == "paragraph":
        return [("body", LESSON), ("body", TALK), ("body", NOTE20)], body_lines(NOTE20), body_lines(TALK)
    return ([("body", LESSON), ("tab_cap", SHORT_CAP), ("table", SHORT_CELLS), ("body", TALK)],
            [SHORT_CAP] + [" ".join(r) for r in SHORT_CELLS], body_lines(TALK))


@pytest.mark.parametrize("cut, tail", TAIL_EDITS, ids=["4", "3", "6", "7"])
@pytest.mark.parametrize("split", ["table", "paragraph", "table-next-page"])
def test_edited_short_tail_after_split_is_not_deleted(split, cut, tail, journal, tmp_path):
    """PDF の中で、段落の最後の 3〜7 文字（1 行）が、docx ではすぐ後ろの表（約 20 文字）か 2 つ後ろの段落（2 段組みの読み順の
    ずれ）の後ろに出て、その数文字が校正で直されている（「時間を取った。」→「時間を持った。」など。アンカーにならない長さで、
    docx と同じ文字でもない）。段落の最後の docx の文字を消さずに、出版版の文字に直す（その行まるごとが段落の最後の行で、すぐ
    後ろが次の段落なので、一致した文字だけで置ける。0.20.0 は表のセルの文字を足し、0.21.0 の作業の途中の版は「…時間を」に消して
    いた）。表・ほかの段落の文字を足さない。"""
    pub = LESSON[:-cut] + tail
    blocks, middle, rest = split_tail_blocks("paragraph" if split == "paragraph" else "table")
    plan, src = n10_article(tmp_path, journal, blocks)
    head = [*SMALL_FRONT, *body_lines(LESSON[:-cut])]
    if split == "table-next-page":
        pages = n10_pages(head, [*middle, tail, *rest, *N10_TAIL])
    else:
        pages = n10_pages([*head, *middle, tail, *rest, *N10_TAIL])
    pc = compare(plan, pages)
    assert changed_paragraphs(plan, pc, {src[LESSON]: pub}) == {}


@pytest.mark.parametrize("cut, tail", TAIL_EDITS, ids=["4", "3", "6", "7"])
@pytest.mark.parametrize("after", ["date-page-end", "date2-page-end", "date-column", "head-next-page"])
@pytest.mark.parametrize("split", ["table", "paragraph"])
def test_edited_short_tail_before_date_or_head_line_is_fixed(split, after, cut, tail, journal, tmp_path):
    """test_edited_short_tail_after_split_is_not_deleted の形で、分断の後ろの最後の行と次の段落の間に、照合に使わない行がある:
    1 ページ目の最後の投稿受付日の行（1 行の形と、2 行の受付日の 2 行目だけの形）、段の区切りの受付日の行（次の段落は同じ
    ページで続く）、次のページの最初の柱（8 文字未満の著者名）。その行を飛ばして、段落の最後の docx の文字を消さずに出版版の
    文字に直す（受付日・柱の文字を足さない）。0.21.0 の作業の途中の版（1 回目の点検の直しの後）は「…時間を」に消していた（0.20.0 は
    表のセルの文字を足していた）。"""
    pub = LESSON[:-cut] + tail
    blocks, middle, rest = split_tail_blocks(split)
    plan, src = n10_article(tmp_path, journal, blocks)
    head = [*SMALL_FRONT, *body_lines(LESSON[:-cut]), *middle, tail]
    pages = {"date-page-end": lambda: n10_pages([*head, R1], [*rest, *N10_TAIL]),
             "date2-page-end": lambda: n10_pages([*head, R2B], [*rest, *N10_TAIL]),
             "date-column": lambda: n10_pages([*head, R2B, *rest, *N10_TAIL]),
             "head-next-page": lambda: n10_pages(head, ["試験　六郎", *rest, *N10_TAIL])}[after]()
    pc = compare(plan, pages)
    assert changed_paragraphs(plan, pc, {src[LESSON]: pub}) == {}


FLOW_FIG = {"recall": ["導入", "↓", "前時の表を振り返る"], "task": ["課題の提示", "↓", "個人で考える時間"]}


@pytest.mark.parametrize("cut, tail", [(7, "時間を設けた。"), (8, "う時間をとった。"), (9, "合う場を設けた。")],
                         ids=["7", "8", "9"])
@pytest.mark.parametrize("fig", list(FLOW_FIG))
def test_edited_short_tail_after_small_figure_is_fixed(fig, cut, tail, journal, tmp_path):
    """段落の最後の 7〜9 文字（1 行。校正で直されている）が、docx では段落のすぐ後ろの小さな図（画像とキャプション）の後ろに
    出て、図の中の文字の行（「前時の表を振り返る」）に、段落の最後の docx の文字（「時間を取った。」）と同じよく使う文字（「時」
    「を」）がある。その偶然の一致で、図の中の文字（「の表」）を段落に足したり、docx の文字を消したりせず、出版版の文字に直す
    （0.21.0 の作業の途中の版は「…説明し合う時の表を取った。」にしていた。0.20.0 も、図によっては図の中の文字を足していた）。"""
    pub = LESSON[:-cut] + tail
    cap = "図１　架空の授業の流れ"
    plan, src = n10_article(tmp_path, journal, [("body", LESSON), ("image", "fig"), ("fig_cap", cap), ("body", TALK)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, *body_lines(LESSON[:-cut]), *FLOW_FIG[fig], cap, tail, *body_lines(TALK),
                                  *N10_TAIL]))
    assert changed_paragraphs(plan, pc, {src[LESSON]: pub}) == {}


@pytest.mark.parametrize("after", ["none", "date-page-end", "head-next-page"])
@pytest.mark.parametrize("split", ["table", "paragraph"])
def test_heavily_edited_tail_after_split_is_not_deleted(split, after, journal, tmp_path):
    """段落の最後の文の一部（「時間を取った。」）が、PDF では表・ほかの段落の後ろ（次の段落の前）に出て、校正で大きく直されている
    （「場を設けて話し合わせた。」。穴として置けない）。docx の文字を消さない（直すか、直さない違いとして 13 章に出す。表の
    セルの文字を足さない）。その行と次の段落の間に、1 ページ目の最後の投稿受付日の行や次のページの最初の柱があっても同じ。"""
    old, new = "時間を取った。", "場を設けて話し合わせた。"
    pub = LESSON[:-len(old)] + new
    blocks, middle, rest = split_tail_blocks(split)
    plan, src = n10_article(tmp_path, journal, blocks)
    head = [*SMALL_FRONT, *body_lines(LESSON[:-len(old)]), *middle, *wrap_lines(new)]
    pages = {"none": lambda: n10_pages([*head, *rest, *N10_TAIL]),
             "date-page-end": lambda: n10_pages([*head, R1], [*rest, *N10_TAIL]),
             "head-next-page": lambda: n10_pages(head, ["試験　六郎", *rest, *N10_TAIL])}[after]()
    pc = compare(plan, pages)
    got = fixed_texts(plan, pc)[src[LESSON]]
    assert got in (LESSON, pub) and changed_paragraphs(plan, pc, {src[LESSON]: got}) == {}
    if got == LESSON:
        assert any(d.src == src[LESSON] and not d.fixable and d.docx.endswith(old) for d in pc.diffs)


FLOW60 = ["導入", "↓", "前時の表を振り返る", "↓", "課題の提示", "↓", "水を入れる時間と深さ", "↓", "個人で考える", "↓",
          "表に矢印をかき込む", "↓", "学級で話し合う"]


def test_rewritten_first_sentence_after_figure_is_fixed(journal, tmp_path):
    """段落の最初の文が校正で書き換えられ（同じくらいの長さの別の文）、PDF では段落のすぐ前に図（docx では画像とキャプション）が
    ある。図の中の文字は短い行（「導入」「↓」）を含む。段落の最初の docx の文字が、図の中の文字との偶然の一致（「時」など）で、
    PDF の別の位置にあるかもしれないとはみなさない（図の中の短い行を、柱・受付日の行のように飛ばして探さない）。書き換えた文に
    直す。"""
    text = (LESSON_HEAD + "生徒は自分のノートの表にも矢印をかき，増え方がいつも同じであることを確かめた。" + LESSON_TAIL
            + "授業の終わりには，学級全体で増え方の決まりを言葉にまとめ，ノートに書かせて振り返りとした。")
    first = text[:text.index("。") + 1]
    pub = "この授業の初めに，教師は前の時間に使った表をもう一度示し，時間と深さの関係を全員で確かめた。" + text[len(first):]
    cap = "図１　架空の授業の流れ"
    plan, src = n10_article(tmp_path, journal, [("body", TALK), ("image", "fig"), ("fig_cap", cap), ("body", text)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, *body_lines(TALK), *FLOW60, cap, *body_lines(pub), *N10_TAIL]))
    assert changed_paragraphs(plan, pc, {src[text]: pub}) == {}


def test_deleted_last_sentence_before_table_is_deleted(journal, tmp_path):
    """対照: docx の段落の最後の短い文（「以上が第三時の流れである。」）が PDF のどこにもなく（校正で消された）、PDF では段落の
    すぐ後ろに表（docx では段落の後ろの Word の表）とすぐ後ろの段落が続く。その文を消す（表の文字を足さない。0.20.0 は、
    消された文の一部を表のセルの文字で置き換えていた）。"""
    add = "以上が第三時の流れである。"
    plan, src = n10_article(tmp_path, journal, [("body", LESSON + add), ("tab_cap", SHORT_CAP), ("table", SHORT_CELLS),
                                                ("body", TALK)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, *body_lines(LESSON), SHORT_CAP, *[" ".join(r) for r in SHORT_CELLS],
                                  *body_lines(TALK), *N10_TAIL]))
    assert changed_paragraphs(plan, pc, {src[LESSON + add]: LESSON}) == {}


def test_paragraph_split_in_reverse_reading_order(journal, tmp_path):
    """2 段組みの読み順のずれで、段落の後半が PDF の文字の列の前のほう（次の段落の前）に、前半が後ろのほうに出る。どちらも
    段落の文字として照合し、何も変えない（0.20.0 は段落が見つからなかった）。"""
    plan, src = n10_article(tmp_path, journal, [("body", LESSON), ("body", TALK), ("body", SURVEY)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, *wrap_lines(LESSON_TAIL), *body_lines(TALK), *body_lines(SURVEY),
                                  *body_lines(LESSON_HEAD), *N10_TAIL]))
    assert src[LESSON] not in pc.unmatched
    assert changed_paragraphs(plan, pc, {}) == {}


def test_tail_moved_after_references_is_not_replaced(journal):
    """d12 の最後の 8 文字が、ほかの段落と引用文献の後ろに出る。d12 をほかの段落の文字で直さない（0.20.0 は「本,」→「付録」、
    「1)。」→「）」と直していた）。d13 の本当の直しは直す。"""
    plan = _plan(journal)
    pc = compare(plan, ["\n".join(["（1）", *FRONT, PUB12[:-8]]),
                        "\n".join(["（2）", PUBLISHED["d13"], PUBLISHED["d14"], "引用および参考文献", PUBLISHED["d17"],
                                   PUB12[-8:], "見本花子（2021）．「見本の研究」．『見本誌』，第2巻，pp.11-20．"])])
    fx = [(f.src, f.old, f.new) for f in plan_fixes(plan, pc) if f.kind == "text" and not f.reason]
    assert ("d13", "資料", "付録") in fx and not [f for f in fx if f[0] == "d12"]


def test_copy_of_deleted_sentence_in_figure_is_not_used(journal, tmp_path):
    """docx の段落の最後の文が校正で消されていて、段落のすぐ後ろの図の中の文字に、その文の写し（句点が「．」）がある。
    図の中の文字を足さず（「．」に直さない）、消すか決められないので直さずに 13 章に出す。"""
    add = "以上が第三時の流れである。"
    fig = ["導入", "↓", "前時の表を振り返る", "↓", "課題の提示", "↓", "水を入れる時間と深さ", add.replace("。", "．"),
           "個人で考える", "↓", "表に矢印をかき込む", "↓", "学級で話し合う", "図１　架空の授業の流れ"]
    plan, src = n10_article(tmp_path, journal, [("body", LESSON + add), ("image", ""), ("fig_cap", "図１　架空の授業の流れ"),
                                                ("body", TALK)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, *body_lines(LESSON), *fig, *body_lines(TALK), *N10_TAIL]))
    got = fixed_texts(plan, pc)
    assert "．" not in got[src[LESSON + add]] and got[src[LESSON + add]] in (LESSON, LESSON + add)
    assert any(d.src == src[LESSON + add] and not d.fixable for d in pc.diffs)


PROBLEM_CAP = "図２　架空の問題"


@pytest.mark.parametrize("deleted, fig", [
    ("その問題を示す。", ["問題　水を入れる時間と深さの", "関係を表に表し，その決まりを", "問題を解きなさい。"]),
    ("を示した。", ["表に数を書き入れ", "を示せ。"]),
], ids=["solve", "short"])
def test_deleted_last_sentence_like_figure_line_is_not_replaced(deleted, fig, journal, tmp_path):
    """docx の段落の最後の文（「その問題を示す。」）が校正で消されていて、PDF では段落のすぐ後ろに図（docx では画像。キャプション
    は図の上）がある。図の中の文字の最後の行（「問題を解きなさい。」）が、消された文と半分ほど同じで、最後の「。」も同じ。その
    行を段落の最後の行とみなして、図の中の文字（「解きなさい」）で docx の文字を置き換えない（消された文は一文まるごとなので、
    似た行に一致した文字だけで置くことはしない）。消すか、決められなければ docx のまま 13 章に出す（0.21.0 の作業の途中の版は
    「…取った。その問題を解きなさい。」にしていた。0.20.0 は図の中の文字をもっと多く足していた）。"""
    docx = LESSON + deleted
    plan, src = n10_article(tmp_path, journal, [("body", docx), ("fig_cap", PROBLEM_CAP), ("image", "fig"), ("body", TALK)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, *body_lines(LESSON), PROBLEM_CAP, *fig, *body_lines(TALK), *N10_TAIL]))
    got = fixed_texts(plan, pc)[src[docx]]
    assert got in (docx, LESSON) and changed_paragraphs(plan, pc, {src[docx]: got}) == {}
    if got == docx:
        assert any(d.src == src[docx] and not d.fixable and d.docx == deleted for d in pc.diffs)


@pytest.mark.parametrize("deleted, fig", [
    ("そこで，", ["そこで", "表を作る", "↓", "規則を見つける"]),
    ("まず初めに，", ["まず表を作る", "↓", "規則を言葉で書く"]),
], ids=["then", "first"])
def test_deleted_first_words_like_figure_line_are_reported(deleted, fig, journal, tmp_path):
    """docx の段落の最初の語（「そこで，」）が校正で消されていて、PDF では段落のすぐ前に図（docx では画像。キャプションは図の
    下）がある。図の中の文字の最初の行（「そこで」）が、消された語と似ている。その行を段落の最初の行とみなさない（みなすと、
    一致した部分〈「そこで」〉が黙って違いにならない。0.21.0 の作業の途中の版は、13 章に「，」だけを出していた。0.20.0 は
    消していた）。消すか、決められなければ、消された語のすべてを docx のまま、直さない違いとして 13 章に出す。"""
    docx = deleted + TALK
    plan, src = n10_article(tmp_path, journal, [("body", LESSON), ("image", "fig"), ("fig_cap", PROBLEM_CAP), ("body", docx)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, *body_lines(LESSON), *fig, PROBLEM_CAP, *body_lines(TALK), *N10_TAIL]))
    got = fixed_texts(plan, pc)[src[docx]]
    assert got in (docx, TALK) and changed_paragraphs(plan, pc, {src[docx]: got}) == {}
    if got == docx:
        assert any(d.src == src[docx] and not d.fixable and d.docx == deleted for d in pc.diffs)


SMALL_FIG_CAP = "図１　架空の授業の流れ"           # 小さな図のキャプション（docx では画像のすぐ後ろの段落）
SMALL_FIG_STEPS = ["導入", "↓", "課題の提示", "↓"]  # 小さな図の中の文字（docx では画像。どの段落にもない）


@pytest.mark.parametrize("after", ["date-page-end", "head-next-page", "next-paragraph"])
@pytest.mark.parametrize("last", ["時間を見る", "時間の表"], ids=["see", "table"])
def test_figure_line_before_caption_is_not_used_as_last_line(last, after, journal, tmp_path):
    """docx の段落の最後の文（「その結果を表に示す。」）が校正で消されていて、PDF では段落の最後の行（「時間を取った。」）が、docx
    では段落のすぐ後ろの小さな図（画像。キャプションは図の下）の、キャプションの後ろに出る。図の中のキャプションのすぐ前の行が、
    段落の最後の行と最初の 3 文字が同じ（「時間を見る」）か、よく使う文字と消された文の文字が並ぶ（「時間の表」）。その行を段落の
    最後の行と並べて、図の中の文字（「見る」「の」）で docx の文字を置き換えたり、PDF の本文の文字（「取った。」）を消したりしない
    （消すか、決められなければ docx のまま直さない違いとして 13 章に出す）。段落の最後の行と次の段落の間に、1 ページ目の最後の
    投稿受付日の行や次のページの最初の柱があっても同じ（0.21.0 の作業の途中の版は「…説明し合う時間を見る」「…説明し合う時間の
    表に示す。」にしていた。0.20.0 は、消された文の一部を残していた〈「…取った。そのに」など〉）。"""
    docx = LESSON + "その結果を表に示す。"
    plan, src = n10_article(tmp_path, journal, [("body", docx), ("image", "fig"), ("fig_cap", SMALL_FIG_CAP), ("body", TALK)])
    head = [*SMALL_FRONT, *body_lines(LESSON[:-7]), *SMALL_FIG_STEPS, last, SMALL_FIG_CAP, LESSON[-7:]]
    pages = {"date-page-end": lambda: n10_pages([*head, R1], [*body_lines(TALK), *N10_TAIL]),
             "head-next-page": lambda: n10_pages(head, ["試験　六郎", *body_lines(TALK), *N10_TAIL]),
             "next-paragraph": lambda: n10_pages([*head, *body_lines(TALK), *N10_TAIL])}[after]()
    pc = compare(plan, pages)
    got = fixed_texts(plan, pc)[src[docx]]
    assert got in (docx, LESSON) and changed_paragraphs(plan, pc, {src[docx]: got}) == {}
    if got == docx:
        assert any(d.src == src[docx] and not d.fixable for d in pc.diffs)


@pytest.mark.parametrize("before", ["date-page-end", "head-next-page"])
@pytest.mark.parametrize("cut", ["k7", "sentence"])
def test_figure_line_after_first_line_is_not_used_as_first_line(cut, before, journal, tmp_path):
    """段落の最初の語句が校正で書き換えられ（「話し合いの中で」→「議論の中で」）、PDF では段落の最初の行（「議論の中で，あ」）の
    すぐ後ろに小さな図（docx では段落のすぐ前の画像とキャプション。キャプションは図の下）があり、図の中の最初の行（「話し合いの
    場面」）が docx の段落の最初の文字とよく似ている。その行を段落の最初の行と並べて、docx の文字（「中で，あ」）を図の中の文字
    （「場面」）で置き換えない（直すか、決められなければ docx のまま直さない違いとして 13 章に出す。0.21.0 の作業の途中の版は
    「話し合いの場面る生徒は…」にし、0.20.0 は段落の最初の語句を消していた〈「ある生徒は…」〉）。段落の前に 1 ページ目の最後の
    投稿受付日の行か、次のページの最初の柱があっても同じ。"""
    pub = TALK.replace("話し合いの中で", "議論の中で")
    k = 7 if cut == "k7" else pub.index("，") + 1
    plan, src = n10_article(tmp_path, journal, [("body", LESSON), ("image", "fig"), ("fig_cap", SMALL_FIG_CAP), ("body", TALK),
                                                ("body", SURVEY)])
    rest = ["　" + pub[:k], "話し合いの場面", *SMALL_FIG_STEPS[1:], "まとめ", SMALL_FIG_CAP, *wrap_lines(pub[k:]),
            *body_lines(SURVEY), *N10_TAIL]
    first = [*SMALL_FRONT, *body_lines(LESSON)]
    pages = n10_pages([*first, R1], rest) if before == "date-page-end" else n10_pages(first, ["試験　六郎", *rest])
    pc = compare(plan, pages)
    got = fixed_texts(plan, pc)[src[TALK]]
    assert got in (TALK, pub) and changed_paragraphs(plan, pc, {src[TALK]: got}) == {}
    if got == TALK:
        assert any(d.src == src[TALK] and not d.fixable for d in pc.diffs)


@pytest.mark.parametrize("after", ["date-page-end", "head-next-page", "next-paragraph"])
@pytest.mark.parametrize("last, fig", [("時間を２回取った。", "時間を2回見る"), ("時間を3回取った。", "時間を３回見る"),
                                       ("時間をＡ班で取った。", "時間をA班で見る"), ("時間をA班で取った。", "時間をa班で見る")],
                         ids=["digit-zen", "digit-han", "letter", "case"])
def test_figure_line_before_caption_does_not_change_width(last, fig, after, journal, tmp_path):
    """test_figure_line_before_caption_is_not_used_as_last_line の形で、図の中のキャプションのすぐ前の行（「時間を2回見る」）と、
    キャプションの後ろの本文の最後の行（「時間を２回取った。」）の英数字が、全角・半角か大文字・小文字だけ違う。その図の中の行と
    並べた docx の文字の全角・半角・大文字・小文字を、図の中の文字に合わせて変えない（0.21.0 の作業の途中の版は「２」を「2」に
    して、13.1 にふつうの直しとして出していた）。消された最後の文は、消すか、決められなければ docx のまま直さない違いとして
    13 章に出す。"""
    pub = LESSON[:-len("時間を取った。")] + last
    docx = pub + "その結果を表に示す。"
    at = len(pub) - len(last) + len("時間を")         # 全角・半角（大文字・小文字）だけが違う docx の文字の位置
    plan, src = n10_article(tmp_path, journal, [("body", docx), ("image", "fig"), ("fig_cap", SMALL_FIG_CAP), ("body", TALK)])
    head = [*SMALL_FRONT, *body_lines(pub[:-len(last)]), *SMALL_FIG_STEPS, fig, SMALL_FIG_CAP, last]
    pages = {"date-page-end": lambda: n10_pages([*head, R1], [*body_lines(TALK), *N10_TAIL]),
             "head-next-page": lambda: n10_pages(head, ["試験　六郎", *body_lines(TALK), *N10_TAIL]),
             "next-paragraph": lambda: n10_pages([*head, *body_lines(TALK), *N10_TAIL])}[after]()
    pc = compare(plan, pages)
    got = fixed_texts(plan, pc)[src[docx]]
    assert got in (docx, pub) and changed_paragraphs(plan, pc, {src[docx]: got}) == {}
    if got == docx:
        assert any(d.src == src[docx] and not d.fixable and d.start <= at < d.end for d in pc.diffs)


@pytest.mark.parametrize("before", ["date-page-end", "head-next-page"])
@pytest.mark.parametrize("docx_head, pub_head, fig_first", [
    ("第1の話し合いの中で，", "第1の議論の中で，", "第１の話し合いの場面"),
    ("第１の話し合いの中で，", "第１の議論の中で，", "第1の話し合いの場面"),
    ("第２時の話し合いの中で", "第２時の議論の中で", "第2時の話し合い"),
], ids=["fig-zen", "fig-han", "split-figure"])
def test_figure_line_after_first_line_does_not_change_width(docx_head, pub_head, fig_first, before, journal, tmp_path):
    """test_figure_line_after_first_line_is_not_used_as_first_line の形で、本当の最初の行（「第1の議論の中で，」）のすぐ後ろの
    図の中の最初の行（「第１の話し合いの場面」）と、docx の段落の最初の文字（「第1の話し合いの中で，」）の英数字が、全角・半角
    だけ違う。その図の中の行と並べた docx の文字の全角・半角を、図の中の文字に合わせて変えない（段落ごとの照合が、分断する図の
    中の文字とみなした位置〈「第2時の話し合い」〉で並べたものも。0.21.0 の作業の途中の版は「1」を「１」、「２」を「2」にして
    いた）。段落の最初の語句の書き換えは、直すか、決められなければ docx のまま直さない違いとして 13 章に出す。直さなかった
    全角・半角の違いも、黙って捨てずに直さない違いとして出す。"""
    docx = docx_head + TALK[len("話し合いの中で，"):] if docx_head.endswith("，") else docx_head + TALK[len("話し合いの中で"):]
    pub = pub_head + docx[len(docx_head):]
    plan, src = n10_article(tmp_path, journal, [("body", LESSON), ("image", "fig"), ("fig_cap", SMALL_FIG_CAP), ("body", docx),
                                                ("body", SURVEY)])
    rest = ["　" + pub_head, fig_first, *SMALL_FIG_STEPS[1:], "まとめ", SMALL_FIG_CAP, *wrap_lines(pub[len(pub_head):]),
            *body_lines(SURVEY), *N10_TAIL]
    first = [*SMALL_FRONT, *body_lines(LESSON)]
    pages = n10_pages([*first, R1], rest) if before == "date-page-end" else n10_pages(first, ["試験　六郎", *rest])
    pc = compare(plan, pages)
    got = fixed_texts(plan, pc)[src[docx]]
    assert got in (docx, pub) and changed_paragraphs(plan, pc, {src[docx]: got}) == {}
    if got == docx:      # docx の 2 文字目（「1」「２」）は、全角・半角だけが図の中の文字と違う
        assert any(d.src == src[docx] and not d.fixable and d.start <= 1 < d.end for d in pc.diffs)


@pytest.mark.parametrize("between", ["date-page-end", "head-next-page", "date-and-head"])
def test_figure_line_after_page_break_is_not_used_as_first_line(between, journal, tmp_path):
    """test_figure_line_after_first_line_is_not_used_as_first_line の形で、本当の最初の行（「議論の中で，あ」）が 1 ページ目の
    最後にあり、小さな図が次のページの最初にある（間に、1 ページ目の最後の投稿受付日の行か、次のページの最初の柱がある）。
    受付日の行・柱を飛ばして、図の中の最初の行（「話し合いの場面」）の前の行が本当の最初の行かを見て、docx の文字（「中で，あ」）を
    図の中の文字（「場面」）で置き換えない（0.21.0 の作業の途中の版は「話し合いの場面る生徒は…」にしていた）。直すか、決められ
    なければ docx のまま直さない違いとして 13 章に出す。"""
    pub = TALK.replace("話し合いの中で", "議論の中で")
    plan, src = n10_article(tmp_path, journal, [("body", LESSON), ("image", "fig"), ("fig_cap", SMALL_FIG_CAP), ("body", TALK),
                                                ("body", SURVEY)])
    first = [*SMALL_FRONT, *body_lines(LESSON), "　" + pub[:7]]
    rest = ["話し合いの場面", *SMALL_FIG_STEPS[1:], "まとめ", SMALL_FIG_CAP, *wrap_lines(pub[7:]), *body_lines(SURVEY),
            *N10_TAIL]
    pages = {"date-page-end": lambda: n10_pages([*first, R1], rest),
             "head-next-page": lambda: n10_pages(first, ["試験　六郎", *rest]),
             "date-and-head": lambda: n10_pages([*first, R1], ["試験　六郎", *rest])}[between]()
    pc = compare(plan, pages)
    got = fixed_texts(plan, pc)[src[TALK]]
    assert got in (TALK, pub) and changed_paragraphs(plan, pc, {src[TALK]: got}) == {}
    if got == TALK:
        assert any(d.src == src[TALK] and not d.fixable for d in pc.diffs)


@pytest.mark.parametrize("after", ["date-page-end", "date-column", "date-head-next-page"])
@pytest.mark.parametrize("material", ["table", "figure-above"])
@pytest.mark.parametrize("edit", ["word", "deleted-sentence"])
def test_last_line_after_date_line_before_caption_is_fixed(edit, material, after, journal, tmp_path):
    """対照: 段落の最後の 1 行（本当の段落の行。校正で「取った」→「持った」と直されているか、その後ろの最後の文が消されている）が、
    1 ページ目の最後の投稿受付日の行の後ろ（次のページの最初、同じページの次の段の最初、次のページの最初の柱の後ろ）に出て、
    そのすぐ後ろに表のキャプション（表は docx でも段落のすぐ後ろ）か、図の上のキャプションがある。前の行との間は受付日の行・柱
    だけで、図の中の文字の行はないので、その行を図の中の行とみなさず、出版版の文字に直す（0.21.0 の作業の途中の版は、直さない
    違い〈DISPLACED_WHY〉にしていた）。"""
    docx, pub = ((LESSON, LESSON.replace("時間を取った", "時間を持った")) if edit == "word" else
                 (LESSON + "その結果を表に示す。", LESSON))
    if material == "table":
        mat, mid = [("tab_cap", SHORT_CAP), ("table", SHORT_CELLS)], [SHORT_CAP] + [" ".join(r) for r in SHORT_CELLS]
    else:
        mat, mid = [("fig_cap", SMALL_FIG_CAP), ("image", "fig")], [SMALL_FIG_CAP, *SMALL_FIG_STEPS, "まとめ"]
    plan, src = n10_article(tmp_path, journal, [("body", docx), *mat, ("body", TALK), ("body", SURVEY)])
    lines = body_lines(pub)
    first = [*SMALL_FRONT, *lines[:-1], R1]
    rest = [lines[-1], *mid, *body_lines(TALK), *body_lines(SURVEY), *N10_TAIL]
    pages = {"date-page-end": lambda: n10_pages(first, rest),
             "date-column": lambda: n10_pages([*first, *rest]),
             "date-head-next-page": lambda: n10_pages(first, ["試験　六郎", *rest])}[after]()
    pc = compare(plan, pages)
    assert changed_paragraphs(plan, pc, {src[docx]: pub}) == {}


@pytest.mark.parametrize("steps, head", [([], False), ([], True), (["↓"], False), (["↓"], True), (["導入", "↓"], False)],
                         ids=["1-line", "1-line-head", "2-lines", "2-lines-head", "3-lines"])
def test_figure_at_page_top_is_not_used_as_last_line(steps, head, journal, tmp_path):
    """段落の最後の文（「その結果を表に示す。」）が校正で消されていて、PDF では小さな図（キャプションは図の下）が次のページの最初に
    あり、段落の最後の行（「時間を取った。」）がキャプションの後ろに出る。図の中の文字の行はページの最初の端の行で、柱（次のページの
    最初の「試験　六郎」）と見分けられないが、キャプションの後ろに、段落の最後の docx の文字とよりよく並ぶ行（本当の最後の行）がある
    ので、キャプションのすぐ前の図の中の行（「時間を見る」）を段落の最後の行と並べない（図の中の文字「見る」を足して「取った。」を
    消さない。受付日の行・柱だけの間なら本当の段落の行とみなす形〈上の
    test_last_line_after_date_line_before_caption_is_fixed〉の例外）。図の中の行が 1 行だけで、前のページの最後の行のすぐ後ろに
    ある（間の行がない）形も同じ（点検した版は「…時間を見る」にしていた。0.20.0 は docx のまま 13 章にも出さなかった）。消すか、
    決められなければ docx のまま直さない違いとして 13 章に出す。"""
    docx = LESSON + "その結果を表に示す。"
    plan, src = n10_article(tmp_path, journal, [("body", docx), ("image", "fig"), ("fig_cap", SMALL_FIG_CAP), ("body", TALK),
                                                ("body", SURVEY)])
    second = [*steps, "時間を見る", SMALL_FIG_CAP, LESSON[-7:], *body_lines(TALK), *body_lines(SURVEY), *N10_TAIL]
    pc = compare(plan, n10_pages([*SMALL_FRONT, *body_lines(LESSON[:-7])], ["試験　六郎", *second] if head else second))
    got = fixed_texts(plan, pc)[src[docx]]
    assert got in (docx, LESSON) and changed_paragraphs(plan, pc, {src[docx]: got}) == {}
    if got == docx:
        assert any(d.src == src[docx] and not d.fixable for d in pc.diffs)


@pytest.mark.parametrize("head", [False, True])
def test_figure_at_page_bottom_is_not_used_as_first_line(head, journal, tmp_path):
    """段落の最初の語句が校正で書き換えられ（「話し合いの中で」→「議論の中で」）、PDF では、ページの最後に、小さな図（キャプションは
    図の上）と、段落の本当の最初の行がある（段落の残りは次のページ）。図の中の最初の行（「話し合いの場面」）が docx の最初の文字と
    よく似ている。図の中の文字の行（「↓」）はページの最後の端の行だが、柱が出る位置（ページの最初の端の行）ではないので、図の中の
    文字とみなし、図の中の行を段落の最初の行と並べない（「話し合いの場面議論の中で…」にしない）。直すか、決められなければ docx の
    まま直さない違いとして 13 章に出す。"""
    pub = TALK.replace("話し合いの中で", "議論の中で")
    plan, src = n10_article(tmp_path, journal, [("body", LESSON), ("fig_cap", SMALL_FIG_CAP), ("image", "fig"), ("body", TALK),
                                                ("body", SURVEY)])
    lines = body_lines(pub)
    first = [*SMALL_FRONT, *body_lines(LESSON), SMALL_FIG_CAP, "話し合いの場面", "↓", lines[0]]
    rest = [*lines[1:], *body_lines(SURVEY), *N10_TAIL]
    pc = compare(plan, n10_pages(first, ["試験　六郎", *rest] if head else rest))
    got = fixed_texts(plan, pc)[src[TALK]]
    assert got in (TALK, pub) and changed_paragraphs(plan, pc, {src[TALK]: got}) == {}
    if got == TALK:
        assert any(d.src == src[TALK] and not d.fixable for d in pc.diffs)


@pytest.mark.parametrize("after", ["date-page-end", "date-column"])
def test_first_line_after_caption_before_date_line_is_fixed(after, journal, tmp_path):
    """対照（頭の側）: 段落の最初の 1 行（本当の段落の行。校正で「話し合いの中で」→「議論の中で」）が、図のキャプション（図の
    下）のすぐ後ろ、1 ページ目の最後の投稿受付日の行の前にあり、段落の残りは次のページ（同じページの次の段）に続く。その行を
    図の中の行とみなさず、出版版の文字に直す（0.21.0 の作業の途中の版は、直さない違いにしていた）。"""
    pub = TALK.replace("話し合いの中で", "議論の中で")
    plan, src = n10_article(tmp_path, journal, [("body", LESSON), ("image", "fig"), ("fig_cap", SMALL_FIG_CAP), ("body", TALK),
                                                ("body", SURVEY)])
    lines = body_lines(pub)
    first = [*SMALL_FRONT, *body_lines(LESSON), *SMALL_FIG_STEPS, "まとめ", SMALL_FIG_CAP, lines[0], R1]
    rest = [*lines[1:], *body_lines(SURVEY), *N10_TAIL]
    pc = compare(plan, n10_pages(first, rest) if after == "date-page-end" else n10_pages([*first, *rest]))
    assert changed_paragraphs(plan, pc, {src[TALK]: pub}) == {}


@pytest.mark.parametrize("deleted", [False, True])
def test_last_line_taken_by_next_paragraph_with_same_sentence_is_not_fixed(deleted, journal, tmp_path):
    """段落 A の最後の行（「…で説明し合う時間を取った。」）が小さな図（キャプションは図の下）の後ろに出て、そのすぐ後ろに
    1 ページ目の最後の投稿受付日の行があり、次のページの最初の段落 B が、A の最後の文と同じ文（「説明し合う時間を取った。」）で
    始まり、B のその文が校正で直されている（「取った」→「設けた」）。A の最後の文が消されていることもある。まとめての照合は、
    A の最後の行を B の最初の行と並べることがあり、そのとき B の窓の最初の行は、キャプションと受付日の行に挟まれた A の行になる。
    間に図の中の文字の行がなくても、A の最後の docx の文字がどの塊にも入っていない（B が A の行を取ったかもしれない）ので、その
    行の違いで B を直さない（A の行の文字「で」を B に足さない。0.21.0 の作業の途中の版は「で説明し合う時間を設けた。…」にしていた）。"""
    b_docx = "説明し合う時間を取った。その後，教師は二つの説明を並べて板書し，違いを問うた。"
    b_pub = b_docx.replace("取った", "設けた")
    docx, pub = (LESSON + "その結果を表に示す。", LESSON) if deleted else (LESSON, LESSON)
    plan, src = n10_article(tmp_path, journal, [("body", docx), ("image", "fig"), ("fig_cap", SMALL_FIG_CAP), ("body", b_docx),
                                                ("body", SURVEY)])
    lines = body_lines(pub)
    first = [*SMALL_FRONT, *lines[:-1], *SMALL_FIG_STEPS, "まとめ", SMALL_FIG_CAP, lines[-1], R1]
    pc = compare(plan, n10_pages(first, [*body_lines(b_pub), *body_lines(SURVEY), *N10_TAIL]))
    got = fixed_texts(plan, pc)
    assert got[src[docx]] in (docx, pub) and got[src[b_docx]] in (b_docx, b_pub)
    assert changed_paragraphs(plan, pc, {src[docx]: got[src[docx]], src[b_docx]: got[src[b_docx]]}) == {}


@pytest.mark.parametrize("before", ["date-page-end", "head-next-page"])
def test_edited_first_line_before_figure_is_fixed(before, journal, tmp_path):
    """対照: 段落の最初の行（校正で「話し合いの中で」→「話し合いの場面で」）のすぐ後ろに小さな図とキャプションがあり、最初の行の
    前に 1 ページ目の最後の投稿受付日の行か、次のページの最初の柱がある。最初の行は本当の段落の行なので、図の中の行とみなさず
    （すぐ前の受付日・柱の行に、docx の段落の文字はない）、出版版の文字に直す。"""
    pub = TALK.replace("話し合いの中で", "話し合いの場面で")
    plan, src = n10_article(tmp_path, journal, [("body", LESSON), ("image", "fig"), ("fig_cap", SMALL_FIG_CAP), ("body", TALK),
                                                ("body", SURVEY)])
    lines = body_lines(pub)
    rest = [lines[0], *SMALL_FIG_STEPS, "まとめ", SMALL_FIG_CAP, *lines[1:], *body_lines(SURVEY), *N10_TAIL]
    first = [*SMALL_FRONT, *body_lines(LESSON)]
    pages = n10_pages([*first, R1], rest) if before == "date-page-end" else n10_pages(first, ["試験　六郎", *rest])
    pc = compare(plan, pages)
    assert changed_paragraphs(plan, pc, {src[TALK]: pub}) == {}


SCORE_BODY ="架空の調査の結果を表１に示す。その結果，生徒の平均は12点であり，前回の調査より高かった。"
SCORE_CUT = SCORE_BODY.index("12点")
SCORE_CAP = "表１　架空の得点"
SCORE_ROWS = [["組", "男子", "女子"], ["1組", "31", "27"], ["2組", "14", "23"]]


@pytest.mark.parametrize("docx_table", [False, True])
@pytest.mark.parametrize("pub", ["13点", "１３点"])
def test_digit_in_table_line_is_not_matched_by_chance(docx_table, pub, journal, tmp_path):
    """PDF では、段落の「12点」（出版版で「13点」）の前に表（キャプション「表１　架空の得点」とセル）が入る。キャプションの
    「１」やセル「1組」の「1」を docx の「1」と偶然一致させず、「2」→「3」だけを直し、表の文字を足さない（0.20.0 は
    キャプションを足すか、「組13」を足すか、重なって直さない）。docx に表があれば、キャプションの段落も PDF の中に見つかる。"""
    blocks = [("body", SCORE_BODY)] + ([("tab_cap", SCORE_CAP), ("table", SCORE_ROWS)] if docx_table else []) + \
        [("body", TALK)]
    plan, src = n10_article(tmp_path, journal, blocks)
    pub_body = SCORE_BODY.replace("12点", pub)
    cells = [c for row in SCORE_ROWS for c in row]
    pc = compare(plan, n10_pages([*SMALL_FRONT, *body_lines(pub_body[:SCORE_CUT]), SCORE_CAP, *cells,
                                  *wrap_lines(pub_body[SCORE_CUT:]), *body_lines(TALK), *N10_TAIL]))
    assert changed_paragraphs(plan, pc, {src[SCORE_BODY]: pub_body}) == {}
    if docx_table:
        assert src[SCORE_CAP] not in pc.unmatched
    else:
        assert (src[SCORE_BODY], SCORE_CAP) in pc.ignored_lines


@pytest.mark.parametrize("head, old, new", [("架空六郎", "六つの", "三つの"), ("数学の研究", "数学の授業", "算数の授業")])
def test_running_head_sharing_chars_with_correction(head, old, new, journal, tmp_path):
    """段落がページをまたぎ、次のページの最初の行の柱（「架空六郎」など）が、出版版で直された docx の文字と 1〜2 文字同じ。
    柱の文字を足さず、直しだけを直す（0.20.0 は柱の残りの文字を足していた）。"""
    text = f"本稿では，架空の学校における{old}記録を観点ごとに整理し，その特徴を述べる。観点ごとに発話の例を示す。"
    pub = text.replace(old, new)
    cut = pub.index(new)
    plan, src = n10_article(tmp_path, journal, [("body", text), ("body", TALK)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, *body_lines(pub[:cut])],
                                 [head, *wrap_lines(pub[cut:]), *body_lines(TALK), *N10_TAIL]))
    assert changed_paragraphs(plan, pc, {src[text]: pub}) == {}


def test_short_head_hole_is_not_searched_beyond_previous_paragraph(journal, tmp_path):
    """引用文献の最初の 2 文字（「架空」）が出版版で直され（「仮想」）、前の文献のさらに前の、ページの最初の柱に同じ 2 文字が
    ある。段落の最初の短い部分を、docx ですぐ前の段落を越えた先（柱）と並べず、柱の文字を足さない。"""
    r1 = "見本一郎（2019）．「架空の数の研究」．『見本数学研究』，第29号，pp.11-16．"
    r2 = "架空花子（2024）．「小さな論文の続き」．『見本誌』，第6巻，pp.1-8．"
    plan, src = n10_article(tmp_path, journal, [("body", TALK)], refs=[r1, r2])
    pub2 = r2.replace("架空", "仮想", 1)
    pc = compare(plan, n10_pages([*SMALL_FRONT, *body_lines(TALK), "引用および参考文献", SMALL_REF],
                                 ["架空の論文の柱", *wrap_lines(r1), *wrap_lines(pub2), *SMALL_EN]))
    assert changed_paragraphs(plan, pc, {src[r2]: pub2}) == {}


EDGE_BODY = "本稿では，架空の授業の記録を観点ごとに整理し，その特徴を三つに分けて考察した"
EDGE_NEXT = "次の節では，それぞれの特徴について，具体的な発話の例を挙げて詳しく述べる。"


def test_same_sentence_at_end_and_in_next_paragraph(journal, tmp_path):
    """段落 A の最後の行（「的な活動を考察した。」）と同じ文字が次の段落 B の最初の文にもあり、B の 2 文目は B の書き出しと
    同じ「比例の考えは，」で始まる（docx の B の「考察した。比例の考」が、PDF では A の最後の行と B の最初の行にまたがり、
    アンカーになる）。A の最後の行を B のものにして A の最後の文字を消さず、A・B の校正の直し（「また，」「また，さらに，」）は
    直す（1 行だけで境目を決めると、A と B のどちらでも説明できて B に取られていた）。"""
    a = ("図の読み方は，design-based research の授業の流れを比べた。本稿の分析は，見方の変容を資料に考察した。生徒の記述は，"
         "説明の仕方を見いだした（試験，2021）。生徒の記述は，proof の考察の手がかりを確かめた。式の意味は，授業の流れを17名"
         "見いだした。表現の工夫は，design-based research の数学的な活動を考察した。")
    b = "比例の考えは，数学的な活動を考察した。比例の考えは，授業の流れを資料に考察した。生徒の記述は，図の形を20回見いだした。"
    a_pub = a.replace("比べた。本稿", "比べた。また，本稿")
    b_pub = b.replace("考察した。比例", "考察した。また，さらに，比例")
    lines = ["図の読み方は，design-based research の授業の流れ", "を比べた。また，本稿の分析は，見方の変容を資料に",
             "考察した。生徒の記述は，説明の仕方を見いだした（", "試験，2021）。生徒の記述は，proof の考察の手がか",
             "りを確かめた。式の意味は，授業の流れを17名見いだ", "した。表現の工夫は，design-based research の数学",
             "的な活動を考察した。", "比例の考えは，数学的な活動を考察した。また，さら",
             "に，比例の考えは，授業の流れを資料に考察した。生", "徒の記述は，図の形を20回見いだした。"]
    plan, src = n10_article(tmp_path, journal, [("body", a), ("body", b), ("body", EDGE_NEXT)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, *lines, *body_lines(EDGE_NEXT), *N10_TAIL]))
    assert changed_paragraphs(plan, pc, {src[a]: a_pub, src[b]: b_pub}) == {}


def test_changed_last_word_after_table(journal, tmp_path):
    """段落の最後の行（「付録に見いだした。」）が docx の表の後ろに出て、その行の最初の語が出版版で直されている（docx
    「資料に見いだした。」）。最後の行を探して「資料」→「付録」だけを直し、最後の文字を消さない。"""
    text = LESSON_HEAD + "その記録は資料に見いだした。"
    pub = text.replace("資料", "付録")
    cells = [["学級", "一回目", "二回目"]] + [[f"{chr(0xFF21 + k)}組", str(10 + k), str(5 + k)] for k in range(8)]
    cap = "表１　架空の学級ごとの記述の数"
    plan, src = n10_article(tmp_path, journal, [("body", text), ("tab_cap", cap), ("table", cells), ("body", TALK)])
    pc = compare(plan, n10_pages([*body_lines(LESSON_HEAD + "その記録は"), cap, *[" ".join(r) for r in cells],
                                  "付録に見いだした。", *body_lines(TALK), *N10_TAIL]))
    assert changed_paragraphs(plan, pc, {src[text]: pub}) == {}


def test_last_char_after_unknown_table_is_not_deleted(journal, tmp_path):
    """段落の最後の「。」だけの行が、docx にない表（キャプションと短いセルの行）の後ろ、docx にない図のキャプションの前に
    出る。「。」を消さない（見つけられなければ、直さない違い〈UNSURE_WHY〉として 13 章に出す）。表・図の文字を足さない。"""
    text = EDGE_BODY + "。"
    plan, src = n10_article(tmp_path, journal, [("body", text), ("body", EDGE_NEXT)])
    table = ["表３　架空の件数", "1組", "85", "61", "－", "2組", "79", "12", "－", "3組", "56", "4組", "－"]
    pc = compare(plan, n10_pages([*SMALL_FRONT, *body_lines(EDGE_BODY), *table, "。", "図２　架空の関係",
                                  *body_lines(EDGE_NEXT), *N10_TAIL]))
    assert changed_paragraphs(plan, pc, {}) == {}


def test_insert_after_space_before_merged_change(journal, tmp_path):
    """英語の後ろの空白の後に、校正で足された文字（「約」）と、その近くの直し（「を」→「に」）がある。まとめた違いの
    足す位置は空白の後ろ（0.20.0 と同じ）。"""
    text = "対応の見方は，problem-solving の記録の件数を見いだした。"
    pub = "対応の見方は，problem-solving 約の記録の件数に見いだした。"
    plan, src = n10_article(tmp_path, journal, [("body", text), ("body", TALK)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, *body_lines(pub), *body_lines(TALK), *N10_TAIL]))
    assert changed_paragraphs(plan, pc, {src[text]: pub}) == {}


def test_two_fixes_around_line_end_hyphen(journal, tmp_path):
    """docx「pp.45-58」、PDF「pp.46-」（改行）「59」（行末は「-」か U+FFFE）。ハイフンを消さず、空白を入れず、数字だけを直す
    （0.20.0 は、まとめた違いの PDF の文字から行末のハイフンを落とし、行の変わり目を空白とみなして「pp.46 59」にしていた）。"""
    ref = "架空太郎（2019）．「架空の題目」．『架空学会誌』，第29号，pp.45-58．"
    plan, src = n10_article(tmp_path, journal, [("body", TALK)], refs=[ref])
    for end in ("-", "￾"):
        pc = compare(plan, n10_pages([*SMALL_FRONT, *body_lines(TALK), "引用および参考文献", SMALL_REF,
                                      f"架空太郎（2019）．「架空の題目」．『架空学会誌』，第29号，pp.46{end}", "59．",
                                      *SMALL_EN]))
        assert fixed_texts(plan, pc)[src[ref]] == ref.replace("45-58", "46-59")


def test_period_added_at_paragraph_end(journal, tmp_path):
    """段落の最後に「。」がなく、PDF の段落の最後の行にはある（校正で足された）。「。」を足す（0.20.0 は黙って足さなかった）。"""
    plan, src = n10_article(tmp_path, journal, [("body", EDGE_BODY), ("body", EDGE_NEXT)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, *body_lines(EDGE_BODY + "。"), *body_lines(EDGE_NEXT), *N10_TAIL]))
    assert changed_paragraphs(plan, pc, {src[EDGE_BODY]: EDGE_BODY + "。"}) == {}


def test_period_added_after_short_last_line(journal, tmp_path):
    """段落の最後の行が「た。」だけで、「。」が校正で足された（docx は「…考察した」）。前の行から続いて一致しているので足す。"""
    text = "本稿では，架空の授業の記録を観点ごとに整理し，その特徴を三つに分けて考察した"
    lines = ["　本稿では，架空の授業の記録を観点ごとに整理し", "，その特徴を三つに分けて考察し", "た。"]
    plan, src = n10_article(tmp_path, journal, [("body", text), ("body", EDGE_NEXT)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, *lines, *body_lines(EDGE_NEXT), *N10_TAIL]))
    assert changed_paragraphs(plan, pc, {src[text]: text + "。"}) == {}


def test_words_before_coincidental_first_match_are_not_added(journal, tmp_path):
    """短い段落「架空の学級は，…」のすぐ前に docx にない表（キャプション「表３　架空の件数」と短いセル）があり、段落の最初の
    「架空」がキャプションの「架空」と偶然一致する。キャプションの「表３」を段落の最初に足さない（直さない違いとして 13 章に
    出す）。"""
    text = "架空の学級は，式による表現を考察した。"
    pub = "架空それぞれの学級は，式による表現を考察した。"
    plan, src = n10_article(tmp_path, journal, [("body", EDGE_BODY + "。"), ("body", text), ("body", EDGE_NEXT)])
    table = ["表３　架空の件数", "1組", "－", "－", "2組", "－", "3組", "69", "－", "34", "4組", "－", "5組", "69"]
    pc = compare(plan, n10_pages([*SMALL_FRONT, *body_lines(EDGE_BODY + "。"), *table, *wrap_lines(pub),
                                  *body_lines(EDGE_NEXT), *N10_TAIL]))
    got = fixed_texts(plan, pc)[src[text]]
    assert got in (text, pub) and changed_paragraphs(plan, pc, {src[text]: got}) == {}


REF_2018 = "架空二郎（2021）．「架空の比の研究」．『架空教育研究』，第12巻，2018"      # 年で終わる（終わりの「．」なし）
REF_NEXT = "見本四郎（2015）．「見本の題目」．『見本誌』，第3巻，pp.5-8．"


def test_reference_end_is_not_replaced_by_table_cell(journal, tmp_path):
    """引用文献の最後の「2018」が出版版で消されていて、すぐ後ろに docx にない表（キャプションとセル「1組」「26」「2組」
    「73」）がある。最後の「2」をセル「2組」の「2」と並べて、「2018」を「2組」に直さない（消すか、直さずに 13 章に出す）。"""
    plan, src = n10_article(tmp_path, journal, [("body", TALK)], refs=[REF_2018, REF_NEXT])
    pc = compare(plan, n10_pages([*SMALL_FRONT, *body_lines(TALK), "引用および参考文献", SMALL_REF,
                                  "架空二郎（2021）．「架空の比の研究」．『架空教育", "研究』，第12巻，", "表１　架空の組ごとの得点",
                                  "1組", "26", "2組", "73", *wrap_lines(REF_NEXT), *SMALL_EN]))
    got = fixed_texts(plan, pc)[src[REF_2018]]
    assert got in (REF_2018, REF_2018[:-4]) and changed_paragraphs(plan, pc, {src[REF_2018]: got}) == {}


def test_reference_end_digit_is_not_widened_by_caption(journal, tmp_path):
    """引用文献の最後の「2018」が出版版で「2019」に直り、すぐ後ろの行に docx にない図のキャプション「図１　架空の図」がある。
    「2018」の「1」をキャプションの「１」と並べて全角にしたり、キャプションの文字を足したりしない。"""
    plan, src = n10_article(tmp_path, journal, [("body", TALK)], refs=[REF_2018, REF_NEXT])
    pc = compare(plan, n10_pages([*SMALL_FRONT, *body_lines(TALK), "引用および参考文献", SMALL_REF,
                                  "架空二郎（2021）．「架空の比の研究」．『架空教育", "研究』，第12巻，", "2019", "図１　架空の図",
                                  *wrap_lines(REF_NEXT), *SMALL_EN]))
    got = fixed_texts(plan, pc)[src[REF_2018]]
    assert got in (REF_2018, REF_2018.replace("2018", "2019")) and changed_paragraphs(plan, pc, {src[REF_2018]: got}) == {}


def test_width_on_short_last_line_is_applied(journal, tmp_path):
    """段落の最後の行が「で５８」だけで、その前に校正で「全部」が足され（docx「合計で58」）、数字は全角になっている。最後の行の
    2 文字の一致は段落の最後までなので、全角・半角も PDF に合わせる（偶然の一致とみなさない）。"""
    text = "架空の調査では，学級ごとの回答の数を集計し，その合計で58"
    pub = "架空の調査では，学級ごとの回答の数を集計し，その合計で全部で５８"
    plan, src = n10_article(tmp_path, journal, [("body", text), ("body", EDGE_NEXT)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, "　架空の調査では，学級ごとの回答の数を集計し，", "その合計で全部", "で５８",
                                  *body_lines(EDGE_NEXT), *N10_TAIL]))
    assert changed_paragraphs(plan, pc, {src[text]: pub}) == {}


REF_BOOK = "架空五郎（2009）．『架空の算数の授業』．架空書房．"


def test_edge_fix_is_not_cut_at_line_end(journal, tmp_path):
    """引用文献の最後の「房．」が出版版で「さらに」に直り、PDF では「さ」で行が終わって「らに」が次の短い行に出る（その後ろに
    短い行が続く）。同じ行の「さ」だけで直して PDF と違う文字にせず、直さない違い（EDGE_WHY）として 13 章に出す。"""
    plan, src = n10_article(tmp_path, journal, [("body", TALK)], refs=[REF_BOOK, REF_NEXT])
    pc = compare(plan, n10_pages([*SMALL_FRONT, *body_lines(TALK), "引用および参考文献", SMALL_REF,
                                  "架空五郎（2009）．『架空の算数の授業』．架空書さ", "らに", "A", "B", "O",
                                  *wrap_lines(REF_NEXT), *SMALL_EN]))
    got = fixed_texts(plan, pc)[src[REF_BOOK]]
    assert got in (REF_BOOK, REF_BOOK.replace("房．", "さらに")) and changed_paragraphs(plan, pc, {src[REF_BOOK]: got}) == {}


def test_edge_fix_on_short_last_line_is_applied(journal, tmp_path):
    """test_edge_fix_is_not_cut_at_line_end と同じ直し（「房．」→「さらに」）で、PDF では「架空」で行が終わり、段落の最後の行が
    「書さらに」だけ（前の行から続いて一致し、段落のほかの行より目に見えて短い）。段落はその行で終わっているので、すぐ後ろの
    短い行（「A」など）に続いているとはみなさず、「さらに」に直す。"""
    plan, src = n10_article(tmp_path, journal, [("body", TALK)], refs=[REF_BOOK, REF_NEXT])
    pc = compare(plan, n10_pages([*SMALL_FRONT, *body_lines(TALK), "引用および参考文献", SMALL_REF,
                                  "架空五郎（2009）．『架空の算数の授業』．架空", "書さらに", "A", "B", "O",
                                  *wrap_lines(REF_NEXT), *SMALL_EN]))
    assert changed_paragraphs(plan, pc, {src[REF_BOOK]: REF_BOOK.replace("房．", "さらに")}) == {}


def test_words_added_at_paragraph_start(journal, tmp_path):
    """PDF の段落の最初の行の書き出しに、校正で足された「まず，」がある。足す（0.20.0 は黙って足さなかった）。"""
    plan, src = n10_article(tmp_path, journal, [("body", EDGE_BODY + "。"), ("body", EDGE_NEXT)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, *body_lines(EDGE_BODY + "。"), *body_lines("まず，" + EDGE_NEXT),
                                  *N10_TAIL]))
    assert changed_paragraphs(plan, pc, {src[EDGE_NEXT]: "まず，" + EDGE_NEXT}) == {}


@pytest.mark.parametrize("deleted", ["以上", "以上の"])
def test_deleted_end_same_as_next_start(deleted, journal, tmp_path):
    """docx の段落の最後の「以上」が出版版で消されていて、次の段落が「以上のことから」で始まる。段落の最後の「以上」を消し、
    次の段落は変えない（0.20.0 は次の段落の書き出しと並べて、違いにしなかった）。"""
    nxt = "以上のことから，" + EDGE_NEXT
    plan, src = n10_article(tmp_path, journal, [("body", EDGE_BODY + "。" + deleted), ("body", nxt)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, *body_lines(EDGE_BODY + "。"), *body_lines(nxt), *N10_TAIL]))
    assert changed_paragraphs(plan, pc, {src[EDGE_BODY + "。" + deleted]: EDGE_BODY + "。"}) == {}


JOIN_BASE = "続いて，表の隣り合う値の間に矢印をかき，増え方を書き込む活動を確かめ"


@pytest.mark.parametrize("a, a_pub, b_pub", [
    (JOIN_BASE + "る", JOIN_BASE + "た。", TALK),                      # A の最後の「る」→「た。」
    (JOIN_BASE + "る", JOIN_BASE + "る。", TALK),                      # A の最後に「。」
    (JOIN_BASE + "た。", JOIN_BASE + "た。", "そこで，" + TALK),         # B の最初に「そこで，」（A は文の終わりで終わる）
    (JOIN_BASE + "る", JOIN_BASE + "た。", TALK.replace("話し合いの中で", "議論の中で")),  # A の最後と B の書き出しの両方
], ids=["a-fix", "a-period", "b-add", "both"])
def test_joined_paragraphs_boundary_is_fixed(a, a_pub, b_pub, journal, tmp_path):
    """docx の 2 つの段落 A・B が、PDF では 1 つの段落につながる（A の最後と B の最初が同じ行。間に空白もない）。A の最後・B の
    最初の校正の直しは、それぞれの段落に直す。A の直された最後を B の頭に足して、A を途中まで直したり（「…確かめ」と
    「た。話し合いの中で…」）、B の最初の文字を消したりしない（文の終わりの直後で、境目を決める）。"""
    plan, src = n10_article(tmp_path, journal, [("body", a), ("body", TALK), ("body", EDGE_NEXT)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, *body_lines(a_pub + b_pub), *body_lines(EDGE_NEXT), *N10_TAIL]))
    assert changed_paragraphs(plan, pc, {src[a]: a_pub, src[TALK]: b_pub}) == {}


@pytest.mark.parametrize("a_pub, b_pub", [
    (JOIN_BASE + "て", TALK),            # A の最後の「る」→「て」
    (JOIN_BASE, "そこで" + TALK),          # A の最後の「る」を消し、B の書き出しに「そこで」を足す
], ids=["a-te", "a-del-b-add"])
def test_joined_paragraphs_boundary_without_stop_is_not_guessed(a_pub, b_pub, journal, tmp_path):
    """docx の 2 つの段落 A（最後が「…確かめる」）・B が、PDF では 1 つの段落につながり、間の PDF の文字（「て」「そこで」）に
    文の終わりも全角の空白もない。A の最後の直し（「る」→「て」）と、A の最後の削除と B の書き出しの挿入（「る」を消して
    「そこで」を足す）は PDF から区別できない。どちらかに決めて、B に足された語を A に足したり（「…確かめそこで」。B の語は
    落ちる）しない。正しく直すか、決められなければ両方の段落を docx のまま、直さない違い（EDGE_WHY）として 13 章に出す。"""
    from jasme_jats.pdfmatch import EDGE_WHY
    a = JOIN_BASE + "る"
    plan, src = n10_article(tmp_path, journal, [("body", a), ("body", TALK), ("body", EDGE_NEXT)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, *body_lines(a_pub + b_pub), *body_lines(EDGE_NEXT), *N10_TAIL]))
    if changed_paragraphs(plan, pc, {src[a]: a_pub, src[TALK]: b_pub}) == {}:
        return
    assert changed_paragraphs(plan, pc, {}) == {}
    for s in (src[a], src[TALK]):
        assert [(d.fixable, d.why) for d in pc.diffs if d.src == s] == [(False, EDGE_WHY)]


@pytest.mark.parametrize("a, a_pub", [
    (JOIN_BASE + "た。", JOIN_BASE + "た。"),        # 直しなし
    (JOIN_BASE + "る", JOIN_BASE + "た。"),          # A の最後の「る」→「た。」
    (JOIN_BASE + "る", JOIN_BASE + "る"),            # 直しなし（A は文の終わりで終わらない）
], ids=["same", "a-fix", "no-stop"])
def test_first_char_of_joined_paragraph_at_line_end_is_kept(a, a_pub, journal, tmp_path):
    """docx の 2 つの段落 A・B が PDF では 1 つにつながり、B の書き出しの 1 文字（「話」）が、A の最後と同じ行の最後に来る
    （「…確かめた。話」の改行の後に「し合いの中で…」）。行の境目で段落を分けて（B の最初の文字を A の側にして）、B の最初の
    文字を消さない（_contests の行の境目の点は 1 文字の一致より小さい）。A の最後の直しは直す。"""
    b = "話し合いの中で，ある生徒は時間が３倍になると述べた。"
    plan, src = n10_article(tmp_path, journal, [("body", a), ("body", b), ("body", EDGE_NEXT)])
    text = "　" + a_pub + b
    cut = len("　" + a_pub) + 1
    lines = [text[:cut][i:i + 24] for i in range(0, cut, 24)] + [text[cut:][i:i + 24] for i in range(0, len(text) - cut, 24)]
    assert lines[(cut - 1) // 24].endswith("。話" if a_pub.endswith("。") else "る話")
    pc = compare(plan, n10_pages([*SMALL_FRONT, *lines, *body_lines(EDGE_NEXT), *N10_TAIL]))
    assert changed_paragraphs(plan, pc, {src[a]: a_pub}) == {}


@pytest.mark.parametrize("pdf_head, sep, fixed", [
    ("（１）架空の目標", "　", True),                 # 追い込みの見出しの最後の直し（見出しと本文の間は全角の空白）
    ("（１）架空の目的と方法", "　", True),           # 見出しの最後に足された語
    ("（１）架空の目的と方法", "", False),            # 間に空白がなく、足された語がどちらの段落の文字か決められない
], ids=["head-fix", "head-add", "no-space"])
def test_run_in_heading_boundary(pdf_head, sep, fixed, journal, tmp_path):
    """docx では見出しの段落（「（１）架空の目的」。4 文字以上なので照合する）と本文の段落に分かれ、PDF では見出しが本文の最初の
    行の頭に入る（追い込みの見出し）。見出しの最後の直し・足された語は、見出しの段落に直す（見出しを途中まで直し、本文の頭に
    見出しの文字を足さない）。どちらの段落の文字か決められないときは、両方とも docx のまま、直さない違い（EDGE_WHY）として
    両方の段落の 13 章に出す。"""
    from jasme_jats.pdfmatch import EDGE_WHY
    head = "（１）架空の目的"
    plan, src = n10_article(tmp_path, journal, [("body", LESSON), ("sec2", head), ("body", TALK)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, *body_lines(LESSON), *wrap_lines(pdf_head + sep + TALK), *N10_TAIL]))
    assert changed_paragraphs(plan, pc, {src[head]: pdf_head} if fixed else {}) == {}
    if not fixed:
        for s in (src[head], src[TALK]):
            assert [(d.pdf, d.fixable, d.why) for d in pc.diffs if d.src == s] == [("と方法", False, EDGE_WHY)]


def test_joined_paragraphs_with_both_edits_are_reported(journal, tmp_path):
    """docx の 2 つの段落 A・B が PDF では 1 つにつながり、A の最後（「る」→「て」）と B の書き出し（「話し合い」→「議論」）の
    両方が直されて、間の「て議論」に文の終わりも空白もない（どこまでが A の文字か決められない）。どちらも docx のまま、直さない
    違い（EDGE_WHY）として 13 章に出す（A の「る」を消して B の頭に「て」を足すことをしない）。"""
    from jasme_jats.pdfmatch import EDGE_WHY
    a = JOIN_BASE + "る"
    b_pub = TALK.replace("話し合いの中で", "議論の中で")
    plan, src = n10_article(tmp_path, journal, [("body", a), ("body", TALK), ("body", EDGE_NEXT)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, *body_lines(JOIN_BASE + "て" + b_pub), *body_lines(EDGE_NEXT), *N10_TAIL]))
    assert changed_paragraphs(plan, pc, {}) == {}
    for s in (src[a], src[TALK]):
        assert [(d.fixable, d.why) for d in pc.diffs if d.src == s] == [(False, EDGE_WHY)]


def test_added_sentence_continuing_to_next_line_is_reported(journal, tmp_path):
    """PDF の段落の最後に、校正で足された一文（2 行にわたる）が続く。同じ行の部分だけを足して文の途中で切ることはせず、
    直さない違い（EDGE_WHY）として 13 章に出し、次の行は照合に使わなかった文字として記録する。"""
    from jasme_jats.pdfmatch import EDGE_WHY
    add = "。なお，授業の記録は二人の観察者が別々に取り，授業の後で照らし合わせた。"
    plan, src = n10_article(tmp_path, journal, [("body", EDGE_BODY), ("body", EDGE_NEXT)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, *body_lines(EDGE_BODY + add), *body_lines(EDGE_NEXT), *N10_TAIL]))
    assert changed_paragraphs(plan, pc, {}) == {}
    assert any(d.src == src[EDGE_BODY] and d.why == EDGE_WHY for d in pc.diffs)
    assert any(s == src[EDGE_BODY] for s, _ in pc.ignored_lines)


@pytest.mark.parametrize("added", ["。", "（試験，2020）。"], ids=["period", "citation"])
def test_addition_only_on_next_line_is_reported(added, journal, tmp_path):
    """docx の段落が文の終わりで終わらず、PDF では段落の最後の行が行の幅いっぱいで、校正で段落の最後に足された文字（「。」・
    「（試験，2020）。」）が次の行にだけ出る（その次の行は次の段落）。次の行は、短い行・どの段落にも当たらない行で、図の中の
    文字のこともあるので足さないが、黙って捨てずに、直さない違い（EDGE_WHY）と照合に使わなかった文字として 13 章に出す
    （0.20.0 は、どちらも 13 章にも出さなかった）。次の段落の違いにはしない。"""
    from jasme_jats.pdfmatch import EDGE_WHY
    text = EDGE_BODY + "後に，課題を述べる"            # 字下げを含めてちょうど 2 行
    plan, src = n10_article(tmp_path, journal, [("body", text), ("body", EDGE_NEXT)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, *body_lines(text), added, *body_lines(EDGE_NEXT), *N10_TAIL]))
    assert changed_paragraphs(plan, pc, {}) == {}
    assert [(d.src, d.docx, d.pdf, d.fixable, d.why) for d in pc.diffs if d.src in (src[text], src[EDGE_NEXT])] == [
        (src[text], "", added, False, EDGE_WHY)]
    assert (src[text], added) in pc.ignored_lines


@pytest.mark.parametrize("case", ["heading", "not-next-line"])
def test_figure_sentence_after_paragraph_end_is_not_reported_as_edge(case, journal, tmp_path):
    """対照: 段落のすぐ後ろの、どの段落にも当たらない文の終わりで終わる行（docx にない図の中の説明の文）でも、段落が見出し
    （文の終わりで終わらないのがふつう）のときや、段落の最後の行のすぐ後ろの行でない（間に図の中の短い行「A」がある）ときは、
    校正で足された文の続きとみなさない（直さない違いにせず、照合に使わなかった文字としてだけ 13 章に出す）。"""
    figure = "これは架空の図の中の説明の文である。"
    text = EDGE_BODY + "後に，課題を述べる"
    if case == "heading":
        plan, src = n10_article(tmp_path, journal, [("body", EDGE_NEXT), ("sec2", "研究の方法"), ("body", text)])
        lines = [*body_lines(EDGE_NEXT), "研究の方法", figure, *body_lines(text)]
        first = "研究の方法"
    else:
        plan, src = n10_article(tmp_path, journal, [("body", text), ("body", EDGE_NEXT)])
        lines = [*body_lines(text), "A", figure, *body_lines(EDGE_NEXT)]
        first = text
    pc = compare(plan, n10_pages([*SMALL_FRONT, *lines, *N10_TAIL]))
    assert changed_paragraphs(plan, pc, {}) == {}
    assert not [d for d in pc.diffs if not d.fixable]
    assert (src[first], figure) in pc.ignored_lines


def test_english_word_only_on_next_page_line_is_reported(journal, tmp_path):
    """英文の段落の最後に校正で足された語「design.」が、PDF ではページの最後の行に 1 語だけで出る（次のページから次の段落）。
    ページの端の行は柱のこともあるので足さないが、黙って捨てずに、直さない違い（EDGE_WHY）として 13 章に出す（0.20.0 は
    13 章にも出さなかった）。"""
    from jasme_jats.pdfmatch import EDGE_WHY
    text = "This fictional study examines how pupils explained ratios in the lesson"
    plan, src = n10_article(tmp_path, journal, [("body", text), ("body", EDGE_NEXT)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, "This fictional study examines how pupils", "explained ratios in the lesson",
                                  "design."], [*body_lines(EDGE_NEXT), *N10_TAIL]))
    assert changed_paragraphs(plan, pc, {}) == {}
    assert [(d.docx, d.pdf, d.fixable, d.why) for d in pc.diffs if d.src == src[text]] == [("", "design.", False, EDGE_WHY)]


@pytest.mark.parametrize("docx, added, fixed", [
    # docx の段落が「。」で終わり、その後ろに空白をはさまずに図の中の文字が同じ行につながる
    (EDGE_BODY + "。", "図３", False),
    # docx の「。」の後ろに足す PDF の文字が「。」で終わり、図の中の文字が続く
    (EDGE_BODY, "。図３", False),
    # 対照: 段落の最後の「。」の後ろに、校正で足された文（文の終わりで終わる）
    (EDGE_BODY + "。", "以上である。", True),
    # 対照: 段落の最後の引用の「）」の後ろに、校正で足された「。」
    (EDGE_BODY + "（試験，2020）", "。", True),
], ids=["figure-after-period", "period-and-figure", "sentence-after-period", "period-after-citation"])
def test_text_joined_after_sentence_end_on_last_line(docx, added, fixed, journal, tmp_path):
    """段落の最後の行の後ろに、空白をはさまずに PDF にだけある文字がつながる。docx の段落の最後か、足す文字の中の文の終わりの
    後ろに、文の終わりで終わらない文字（「図３」）が続くなら、図の中の文字かもしれないので足さず、直さない違い（EDGE_WHY）に
    する（段落の最後の、同じ行の PDF にだけある文字は、空白をはさまなければ足すので、「…考察した。図３」にしないように）。
    文の終わりで終わる文字（校正で足された文、引用の後ろの「。」）は足す（0.20.0 は、どれも黙って足さなかった）。"""
    from jasme_jats.pdfmatch import EDGE_WHY
    plan, src = n10_article(tmp_path, journal, [("body", docx), ("body", EDGE_NEXT)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, *body_lines(docx + added, kinsoku=True), *body_lines(EDGE_NEXT),
                                  *N10_TAIL]))
    if fixed:
        assert changed_paragraphs(plan, pc, {src[docx]: docx + added}) == {}
    else:
        assert changed_paragraphs(plan, pc, {}) == {}
        assert [(d.fixable, d.why) for d in pc.diffs if d.src == src[docx]] == [(False, EDGE_WHY)]


@pytest.mark.parametrize("added, fixed", [(" Figure 3", False), (" All were coded.", True)], ids=["figure", "sentence"])
def test_english_text_after_sentence_end_on_last_line(added, fixed, journal, tmp_path):
    """英文の段落の最後の「.」の後ろに、同じ行で単語の間の空白をはさんで PDF にだけある文字が続く。文の終わりで終わらない文字
    （図の中の文字「Figure 3」）は足さず、直さない違い（EDGE_WHY）にする。文の終わりで終わる文（校正で足された「All were
    coded.」）は、単語の間の空白とともに足す（対照）。"""
    from jasme_jats.pdfmatch import EDGE_WHY
    text = "This fictional study examines how pupils explained ratios."
    plan, src = n10_article(tmp_path, journal, [("body", text), ("body", EDGE_NEXT)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, "This fictional study examines how pupils", "explained ratios." + added,
                                  *body_lines(EDGE_NEXT), *N10_TAIL]))
    if fixed:
        assert changed_paragraphs(plan, pc, {src[text]: text + added}) == {}
    else:
        assert changed_paragraphs(plan, pc, {}) == {}
        assert [(d.fixable, d.why) for d in pc.diffs if d.src == src[text]] == [(False, EDGE_WHY)]


def test_end_change_before_short_label_line_is_fixed(journal, tmp_path):
    """段落の最後の「。」が出版版で「とした」に直り、段落の最後の行（「かりになるとした」。段落のほかの行より目に見えて短い）の
    すぐ後ろに、どの段落とも一致しない短い行（図の中の点の名前「A」）がある。段落はその短い最後の行で終わっているので、「A」に
    続いているとはみなさず、「。」→「とした」と直す（直さない違いにしない）。"""
    text = "比例の理解を深めるうえで，表と式の関係が手がかりになる。"
    pub = text[:-1] + "とした"
    plan, src = n10_article(tmp_path, journal, [("body", EDGE_BODY + "。"), ("body", text), ("body", EDGE_NEXT)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, *body_lines(EDGE_BODY + "。"), "　比例の理解を深めるうえで，表と式の関係が手が",
                                  "かりになるとした", "A", *body_lines(EDGE_NEXT), *N10_TAIL]))
    assert changed_paragraphs(plan, pc, {src[text]: pub}) == {}


@pytest.mark.parametrize("before", [["表１　架空の組ごとの得点", "1組", "26", "2組", "73"], ["27", "16", "14"]],
                         ids=["unknown-table", "digit-lines"])
def test_start_change_after_short_lines_is_fixed(before, journal, tmp_path):
    """段落の最初の「なお」が出版版で「また」に直り、段落のすぐ前に、どの段落とも一致しない短い行（docx にない表の
    キャプションと短いセル、数字だけの行）がある。すぐ前の行が目に見えて短いので、段落はその次の行から始まっているとみなし、
    「なお」→「また」と直す（表の文字は足さない）。"""
    text = "なお，以上の結果から，対応の見方と変化の見方を行き来する活動が，比例の理解を深めるうえで重要であると考えられる。"
    pub = "また" + text[2:]
    plan, src = n10_article(tmp_path, journal, [("body", EDGE_BODY + "。"), ("body", text)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, *body_lines(EDGE_BODY + "。"), *before, *wrap_lines(pub), *N10_TAIL]))
    assert changed_paragraphs(plan, pc, {src[text]: pub}) == {}


def test_end_change_on_full_last_line_before_free_line_is_reported(journal, tmp_path):
    """1 行の引用文献の最後の「7．」が出版版で「生徒」に直り、その行（行の幅いっぱい）のすぐ後ろに、どの段落とも一致しない
    短い行（「A」）がある。段落がその行で終わっているか決められない（「A」に続いているかもしれない）ので、同じ行の部分だけで
    直さず、直さない違い（EDGE_WHY）として 13 章に出す。"""
    from jasme_jats.pdfmatch import EDGE_WHY
    ref = "架空二郎（2021）．「架空の比の研究」．『架空教育研究』，第12巻，pp.33-47．"
    plan, src = n10_article(tmp_path, journal, [("body", TALK)], refs=[ref, REF_NEXT])
    pc = compare(plan, n10_pages([*SMALL_FRONT, *body_lines(TALK), "引用および参考文献", SMALL_REF, ref[:-2] + "生徒", "A",
                                  *wrap_lines(REF_NEXT), *SMALL_EN]))
    assert changed_paragraphs(plan, pc, {}) == {}
    assert [(d.docx, d.pdf, d.why) for d in pc.diffs if d.src == src[ref]] == [("7．", "生徒", EDGE_WHY)]


@pytest.mark.parametrize("nxt", [REF_NEXT, "Smith, J. (2015). A fictional study of ratio. Fictional Journal, 3, 5-8."],
                         ids=["ja", "en"])
def test_corrected_year_line_at_page_top_before_next_reference(nxt, journal, tmp_path):
    """引用文献の最後の行の年（「，」の後ろの数字だけの行。行全体でしか一致させない行）が出版版で「2018」→「2019」と直り、
    次のページの最初の行（ページ番号の行の次）に出て、その後ろに次の文献が続く。前のページの最後に空の行がある（PDF から
    取り出した文字によくある形）。docx の「2018」を消さず、直さない違い（HEAD_WHY）にする（窓を広げるときに、列に文字のない
    行〈空の行・ページ番号の行〉で止まると、年の行が窓から外れて消していた）。"""
    from jasme_jats.pdfmatch import HEAD_WHY
    pub = REF_2018.replace("2018", "2019")
    k = pub.index("巻，") + 2
    plan, src = n10_article(tmp_path, journal, [("body", TALK)], refs=[REF_2018, nxt])
    pc = compare(plan, n10_pages([*SMALL_FRONT, *body_lines(TALK), "引用および参考文献", SMALL_REF, *wrap_lines(pub[:k]), ""],
                                 [pub[k:], *wrap_lines(nxt), *SMALL_EN]))
    assert changed_paragraphs(plan, pc, {}) == {}
    assert [(d.docx, d.pdf, d.fixable, d.why) for d in pc.diffs if d.src == src[REF_2018]] == [
        ("2018", "2019", False, HEAD_WHY)]


def test_paragraph_starting_with_line_on_many_pages_is_found(journal, tmp_path):
    """同じ文字の段落（くり返し示す問題文など）が docx に 2 つあり、PDF ではその最初の行が、図の中の同じ文字の行とあわせて
    3 ページに出る（何ページにも出る行。行全体でしか一致させない行なので、まとめての照合の列に入らない）。段落の文字が、docx で
    前後の段落の PDF の位置の間にそのまま続いていれば、その段落の位置とする（PDF の中に見つからない段落〈13.5〉にしない）。"""
    item = "比の値を求める問題を，三つの場面に分けて架空の数値で示し，各場面で比の値の意味を問うた。"
    first = body_lines(item)[0]       # 2 行目は 21 文字（段落の文字の半分に足りない）
    plan, src = n10_article(tmp_path, journal, [("body", RATIO), ("body", item), ("body", TALK), ("body", SURVEY),
                                                ("image", "fig"), ("body", LESSON_TAIL), ("body", RATIO_TALK),
                                                ("body", item), ("body", LESSON_HEAD)])
    pages = n10_pages([*SMALL_FRONT, *body_lines(RATIO), *body_lines(item), *body_lines(TALK), "（続く）", "（続く）"],
                      [*body_lines(SURVEY), first.strip(), "図１　架空の問題文", *body_lines(LESSON_TAIL), "（続く）", "（続く）"],
                      [*body_lines(RATIO_TALK), *body_lines(item), *body_lines(LESSON_HEAD), *N10_TAIL])
    pc = compare(plan, pages)
    assert pc.unmatched == [] and changed_paragraphs(plan, pc, {}) == {}
    assert not [d for d in pc.diffs if plan.paras[d.src].plain() == item]


# ---------------------------------------------------------------------------- 分断された部分の照合（表・図・ほかの段落）
INTRO = ("本研究の目的は，架空の中学校で行った比例の授業において，生徒が二つの量の関係をどのように捉えたかを，"
         "ノートの記述と授業中の発話から明らかにすることである。")
WATER_HEAD = ("第三時の授業では，教師はまず前時に作った表を黒板に掲げ，水を入れる時間と水の深さの関係を振り返らせた。"
              "続いて，表の隣り合う値の間に矢印をかき，深さがどれだけ増えたかを矢印の上に書き込む活動を示した。"
              "生徒は自分のノートの表にも矢印をかき，増え方がいつも同じであることを確かめた。")
WATER_TAIL = "最後に，教師は時間が３倍になると深さがどうなるかを問い，生徒どうしで説明し合う時間を取った。"
WATER = WATER_HEAD + WATER_TAIL
WATER_AFTER = ("話し合いの中で，ある生徒は時間が３倍になると深さも３倍になると述べ，別の生徒は１分ごとに同じだけ増えるから"
               "だと理由を付け加えた。教師はこの二つの説明を並べて板書した。")
RECORD = "なお，授業の記録は二人の観察者が別々に取り，授業の後に照らし合わせて食い違いを確かめた。記録の方法は前時と同じである。"
COUNT_CAP = "表１　架空の学級ごとの記述の数"
# 表（およそ 200 文字。0.20.0 の照合の窓〈段落の長さ + 60 文字ほど〉より長く、段落の後ろを窓の外に出す）
COUNT_ROWS = [["学級", "一回目", "二回目"]] + [["ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸ"[k] + "組", str(10 + (k * 7) % 23),
                                         str(5 + (k * 11) % 17)] for k in range(24)]
FLOW_CAP = "図１　架空の授業の流れ"
# 図の中の文字（およそ 200 文字。docx では画像なので、どの段落にもない）と図のキャプション
FLOW_LINES = [x for w in ["導入", "前時の表を振り返る", "課題の提示", "水を入れる時間と深さ", "個人で考える", "表に矢印をかき込む",
                          "増え方を書く", "学級で話し合う", "増え方に注目する説明", "何倍かに注目する説明", "二つの説明を比べる",
                          "まとめ", "分かったことを書く", "振り返りを書く", "教師の発問", "生徒の説明", "板書の記録",
                          "ノートの記述", "記述の分類"] for x in (w, "↓")][:-1] + [FLOW_CAP]


def water_lines(text):
    """WATER などの段落の PDF の行（行の最初に来る句読点を前の行にぶら下げる）。"""
    return body_lines(text, kinsoku=True)


def test_tail_after_table_is_matched_as_part(journal, tmp_path):
    """段落の最後の文が、PDF では表の後ろにある（docx では表は段落の後ろの Word の表）。最後の文の校正の直し（docx「設けた」
    → PDF「取った」）を、分断された部分として照合して直す。表の文字は足さない。"""
    docx = WATER_HEAD + WATER_TAIL.replace("取った", "設けた")
    plan, src = n10_article(tmp_path, journal, [("body", INTRO), ("body", docx), ("tab_cap", COUNT_CAP),
                                                ("table", COUNT_ROWS), ("body", WATER_AFTER)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, *water_lines(INTRO), *water_lines(WATER_HEAD), COUNT_CAP,
                                  *[" ".join(r) for r in COUNT_ROWS], *wrap_lines(WATER_TAIL, kinsoku=True),
                                  *water_lines(WATER_AFTER), *N10_TAIL]))
    assert pc.unmatched == []
    assert changed_paragraphs(plan, pc, {src[docx]: WATER}) == {}


def test_head_before_figure_is_matched_as_part(journal, tmp_path):
    """段落の最初の行が、PDF では図（docx では段落の前の画像。図の中の文字は docx にない）の前にある。最初の行の校正の直し
    （docx「まず」→ PDF「最初に」）を直す。図の中の文字は足さない。"""
    pub = WATER.replace("教師はまず", "教師は最初に")
    lines = water_lines(pub)
    plan, src = n10_article(tmp_path, journal, [("body", INTRO), ("image", "fig1"), ("fig_cap", FLOW_CAP), ("body", WATER),
                                                ("body", WATER_AFTER)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, *water_lines(INTRO), lines[0], *FLOW_LINES, *lines[1:],
                                  *water_lines(WATER_AFTER), *N10_TAIL]))
    assert pc.unmatched == []
    assert changed_paragraphs(plan, pc, {src[WATER]: pub}) == {}


def test_middle_split_by_other_paragraph(journal, tmp_path):
    """PDF の読み順で、段落の途中（4 行目の後）にほかの段落（docx では 2 つ後ろ）が入る。どちらの段落も変えない（ほかの
    段落の文字を足さない・段落の文字を消さない）。"""
    lines = water_lines(WATER)
    plan, src = n10_article(tmp_path, journal, [("body", INTRO), ("body", WATER), ("body", WATER_AFTER), ("body", RECORD)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, *water_lines(INTRO), *lines[:4], *water_lines(RECORD), *lines[4:],
                                  *water_lines(WATER_AFTER), *N10_TAIL]))
    assert pc.unmatched == []
    assert changed_paragraphs(plan, pc, {}) == {}


def test_short_tail_after_table_is_not_deleted(journal, tmp_path):
    """分断された段落の最後の部分が 4 文字（「取った。」）だけで、表の後ろにある。消さない（docx のまま）。"""
    plan, src = n10_article(tmp_path, journal, [("body", INTRO), ("body", WATER), ("tab_cap", COUNT_CAP),
                                                ("table", COUNT_ROWS), ("body", WATER_AFTER)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, *water_lines(INTRO), *water_lines(WATER[:-4]), COUNT_CAP,
                                  *[" ".join(r) for r in COUNT_ROWS], WATER[-4:], *water_lines(WATER_AFTER), *N10_TAIL]))
    assert pc.unmatched == []
    assert changed_paragraphs(plan, pc, {}) == {}


PAGES_REF = "架空太郎（2015）．「架空の題目その1」．『架空学会誌』，第20号，pp.6-13．"


def test_received_date_between_digits_is_not_matched(journal, tmp_path):
    """引用文献の「pp.6-」の改行の後に、組版で投稿受付日の行が入り、その後ろにページの終わりの数（出版版で「13」→「14」）が
    ある。docx の「1」を投稿受付日の「10月」の「1」と並べない（「114」にしない）。投稿受付日は足さない。"""
    date = "2026年３月２日投稿受付，2026年６月25日再投稿受付，2026年10月７日採用決定"
    plan, src = n10_article(tmp_path, journal, [("body", INTRO)], refs=[PAGES_REF])
    head = PAGES_REF[:PAGES_REF.rindex("-") + 1]
    pc = compare(plan, n10_pages([*SMALL_FRONT, *water_lines(INTRO), "引用および参考文献", SMALL_REF, head[:24], head[24:],
                                  date, "14．", *SMALL_EN]))
    assert changed_paragraphs(plan, pc, {src[PAGES_REF]: PAGES_REF.replace("13．", "14．")}) == {}


def test_unowned_line_inside_paragraph_is_not_inserted(journal, tmp_path):
    """段落の行に挟まれた、どの段落にも当たらない行（図の中の文字）は足さない。その後ろの行の「。」は段落の文字として照合し、
    年の直し（「2020」→「2021」）だけをする。"""
    text = "式の意味は，式による表現を整理した（試験，2020）。"
    plan, src = n10_article(tmp_path, journal, [("body", INTRO), ("body", text)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, *water_lines(INTRO), "式の意味は，式による表現を整理した（試験，2021）",
                                  "図の中の架空の文字その一です", "。", *N10_TAIL]))
    assert changed_paragraphs(plan, pc, {src[text]: text.replace("2020", "2021")}) == {}


FIVE_BODY = ("授業は全部で五回行い，各回の記録を第２節で述べる枠組みで分類した。分類の結果は表１に示すとおりであり，"
             "回を追うごとに対応の見方が増えていったことがうかがえる。")
FIVE_LAST = "がうかがえる。"                      # FIVE_BODY の最後の行（PDF では図の後ろに出る）
FIVE_NEXT = "次に，生徒の記述を観点ごとに整理し，その特徴を三つの段階に分けて述べる。"
FIVE_NEXT2 = "第二の段階は一方の量の変化に着目する段階であり，第三の段階は二つの量の変化を対応させる段階である。"
AXIS_LINES = ["架空の点Ａの位置", "横の軸は時間の長さ", "縦の軸は量の大きさ", "生徒の発話の数", "第一の段階の発話",
              "第二の段階の発話", "第三の段階の発話", "授業の前半の記録"]          # 図の中の文字（docx では画像。66 文字）


def test_tail_after_other_paragraphs_is_not_deleted(journal, tmp_path):
    """段落の最後の行が、PDF では次の 2 つの段落（2 段組みの読み順のずれ。80 文字ほど）の後ろに出る。0.20.0 は次の段落の文字と
    並べて「がうかがえ」を消していた。消さない（次の段落も変えない）。"""
    plan, src = n10_article(tmp_path, journal, [("body", FIVE_BODY), ("body", FIVE_NEXT), ("body", FIVE_NEXT2)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, FIVE_BODY[:-len(FIVE_LAST)], FIVE_NEXT, FIVE_NEXT2, FIVE_LAST, *N10_TAIL]))
    for text in (FIVE_BODY, FIVE_NEXT, FIVE_NEXT2):
        assert [(o, n) for o, n, r in text_fixes(plan, pc, src[text]) if not r] == []


@pytest.mark.parametrize("line1, line2", [("pp.46-", "59．"), ("pp.46￾", "59．")], ids=["hyphen", "fffe"])
def test_hyphen_between_two_fixes_is_kept(line1, line2, journal, tmp_path):
    """引用文献のページの範囲の「-」が PDF では行末にあり、その前後の数字が出版版で直っている（docx「pp.45-58」、PDF「pp.46-」
    の改行の後の「59」）。数字だけを直す（「5」→「6」、「8」→「9」。0.20.0 は「pp.46 59」にしていた）。"""
    head = "架空太郎（2019）．「架空の題目」．『架空学会誌』，第29号，"
    ref = head + "pp.45-58．"
    plan, src = small_article(tmp_path, journal, FIVE_NEXT, ref)
    pc = compare(plan, ["\n".join(["（1）", *SMALL_FRONT, FIVE_NEXT, "引用および参考文献", SMALL_REF, head + line1, line2,
                                   *SMALL_EN])])
    assert [(o, n) for o, n, r in text_fixes(plan, pc, src[ref]) if not r] == [("5", "6"), ("8", "9")]


def test_hyphenation_between_two_fixes_has_no_space(journal, tmp_path):
    """英文の行末のハイフネーション（docx にハイフンがない）の前後に 2 つの直しがあるとき、行の変わり目に空白を足さない。"""
    ref = "Shiken, T. (2019). Fictional explanation of ratio. Fictional Journal of Mathematics, 12, 45-58."
    pub = ref.replace("Fictional explanation", "Fictitious explanations")
    plan, src = small_article(tmp_path, journal, FIVE_NEXT, ref)
    pc = compare(plan, ["\n".join(["（1）", *SMALL_FRONT, FIVE_NEXT, "引用および参考文献", SMALL_REF,
                                   "Shiken, T. (2019). Fictitious expla-", "nations of ratio. Fictional Journal of",
                                   "Mathematics, 12, 45-58.", *SMALL_EN])])
    assert fixed_texts(plan, pc)[src[ref]] == pub


def test_short_match_moved_next_to_previous_block(journal, tmp_path):
    """段落の最初の行の最後の「る」の後ろに、PDF では表のキャプションとセル（「量を別々に見る」。docx のほかの段落にも同じ文字が
    ある）が入る。0.20.0 は docx の「る」をセルの最後の「る」と並べて、行の最後の「る」とセルの文字を段落に足していた
    （「る量を別々に見」）。「る」を前の行の最後の「る」と並べ、セルの文字を足さない。"""
    text = "授業は全部で五回行い，各回の記録を第２節で述べる枠組みで分類した。分類の結果は表１に示すとおりである。"
    other = "第一の段階は量を別々に見る段階である。"
    rows = [["観点", "第１回"], ["量を別々に見る", "3"]]
    plan, src = n10_article(tmp_path, journal, [("body", text), ("tab_cap", TABLE_CAP), ("table", rows), ("body", other)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, text[:24], TABLE_CAP, "観点", "第１回", "量を別々に見る", "3", text[24:], other,
                                  *N10_TAIL]))
    assert [(o, n) for o, n, r in text_fixes(plan, pc, src[text]) if not r] == []


def test_real_corrections_next_to_split_are_fixed(journal, tmp_path):
    """分断の手前の直し（「五回」→「５回」の全角・半角と、「全部で」→「合わせて」）は、段落の最後の行が図の中の文字の後ろに
    出ても直す（分断された部分の守りで、直せる違いを直さなくならない）。"""
    pub = FIVE_BODY.replace("全部で五回", "合わせて５回")
    plan, src = n10_article(tmp_path, journal, [("body", FIVE_BODY), ("body", FIVE_NEXT)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, pub[:-len(FIVE_LAST)], *AXIS_LINES * 4, FIVE_LAST, FIVE_NEXT, *N10_TAIL]))
    assert fixed_texts(plan, pc)[src[FIVE_BODY]] == pub


# ---------------------------------------------------------------------------- 照合の守り（足さない・消さない側に倒す）
# まとめての照合で段落の最初・最後・途中の PDF にだけある文字を扱えるようになったので、図・表の中の文字や受付日の文字を
# docx に足さないための守り（段落の端の空白の後ろの文字、段落の途中の行まるごと、長い置き換え、受付日との偶然の一致、
# まとめた直しと全角・半角の直しの重なり）を確かめる。守りがあっても、ふつうの直しは直す（対照）
RATIO = ("第二時の授業では，教師はまず前時に使った帯図を黒板に示し，基準にする量と比べる量の関係を確かめさせた。"
         "続いて，帯図の下に数直線をかき，二つの量の割合を数直線の上に書き入れる活動を示した。")
RATIO_TALK = "話し合いでは，ある児童は基準にする量が二倍になると割合は半分になると述べた。"
GUARD_DATE = "2026年７月14日投稿受付，2026年11月９日採用決定"


def cut_lines(text, width=24):
    """width 文字ずつの行に分ける（文字の幅は数えない）。"""
    return [text[i:i + width] for i in range(0, len(text), width)]


def guard_article(tmp_path, journal, bodies, refs=()):
    """本文の段落 bodies（と引用文献 SMALL_REF の後ろの refs）の小さな論文の構造と、段落の文字 -> 段落 ID。"""
    return n10_article(tmp_path, journal, [("body", t) for t in bodies], refs, title="照合の守りの検証用文書")


def guard_pages(*lines, refs=()):
    return ["\n".join(["（1）", "照合の守りの検証用文書", *SMALL_FRONT[1:], *lines, "引用および参考文献", SMALL_REF, *refs,
                       *SMALL_EN])]


@pytest.mark.parametrize("where", ["end", "start"])
def test_figure_label_joined_to_paragraph_edge_line_is_not_added(where, journal, tmp_path):
    """本文の横に置かれた図の中の文字（「時間（分）」）が、段落の最後（最初）の行に同じ行としてつながる。和文の本文の行の中に
    空白は入らないので、空白をはさんだ PDF にだけある文字は足さない。黙って捨てずに、直さない違いにする。"""
    plan, src = guard_article(tmp_path, journal, [RATIO, RATIO_TALK])
    lines = cut_lines("　" + RATIO)
    lines = lines[:-1] + [lines[-1] + "　時間（分）"] if where == "end" else ["時間（分）　" + lines[0]] + lines[1:]
    pc = compare(plan, guard_pages(*lines, *cut_lines("　" + RATIO_TALK)))
    got = fixed_texts(plan, pc)
    assert got[src[RATIO]] == RATIO and got[src[RATIO_TALK]] == RATIO_TALK
    assert [d.fixable for d in pc.diffs if d.src == src[RATIO]] == [False]


def test_period_added_on_last_line_is_added(journal, tmp_path):
    """対照: 校正で段落の最後に足された「。」（同じ行で、空白をはさまない）は今までどおり足す。"""
    plan, src = guard_article(tmp_path, journal, [RATIO[:-1], RATIO_TALK])
    pc = compare(plan, guard_pages(*cut_lines("　" + RATIO), *cut_lines("　" + RATIO_TALK)))
    assert fixed_texts(plan, pc)[src[RATIO[:-1]]] == RATIO


def test_period_and_figure_label_after_last_line_are_not_added(journal, tmp_path):
    """docx の段落の最後に「。」がなく、PDF の最後の行は「。」の後ろに空白をはさんで図の中の文字が続く。図の中の文字は足さない
    （「。」も、どこまでが段落の文字か決められないので、足さずに直さない違いにする）。"""
    plan, src = guard_article(tmp_path, journal, [RATIO[:-1], RATIO_TALK])
    lines = cut_lines("　" + RATIO)
    pc = compare(plan, guard_pages(*lines[:-1], lines[-1] + "　時間（分）", *cut_lines("　" + RATIO_TALK)))
    assert fixed_texts(plan, pc)[src[RATIO[:-1]]] in (RATIO[:-1], RATIO)


def test_heading_number_only_in_pdf_is_not_added(journal, tmp_path):
    """docx の見出しにない番号「（２）」が、PDF では見出しの前に空白をはさんである。足さない。"""
    plan, src = n10_article(tmp_path, journal, [("body", RATIO), ("sec2", "研究の方法"), ("body", RATIO_TALK)],
                            title="照合の守りの検証用文書")
    pc = compare(plan, guard_pages(*cut_lines("　" + RATIO), "（２）　研究の方法", *cut_lines("　" + RATIO_TALK)))
    assert fixed_texts(plan, pc)[src["研究の方法"]] == "研究の方法"


@pytest.mark.parametrize("where", ["end", "start"])
def test_english_words_added_at_paragraph_edge_keep_space(where, journal, tmp_path):
    """英文の段落の最後（最初）に校正で足された語は、単語の間の空白の後ろ（前）でも足し、空白も足す（「Briefly,This」に
    しない）。"""
    text = "This fictional study examines how pupils explained ratios. The lessons were recorded."
    pub = text + " All were coded." if where == "end" else "Briefly, " + text
    plan, src = guard_article(tmp_path, journal, [text, RATIO_TALK])
    pc = compare(plan, guard_pages(pub[:48], pub[48:], *cut_lines("　" + RATIO_TALK)))
    assert fixed_texts(plan, pc)[src[text]] == pub


@pytest.mark.parametrize("line", ["図２　架空の配置", "表２　架空の得点の一覧"])
def test_caption_line_inside_paragraph_is_not_added(line, journal, tmp_path):
    """段落の途中に、docx にない図・表のキャプションの行がまるごと入る（近くに照合に使わない文字がない）。段落の途中の本文の
    行は行の幅いっぱいになるので、短い行がまるごと PDF にだけあるのは図・表の中の文字と考え、足さずに照合に使わなかった文字
    （13 章の最後の一覧）に出す（0.20.0 は 20 文字未満なら足していた）。"""
    plan, src = guard_article(tmp_path, journal, [RATIO, RATIO_TALK])
    lines = cut_lines("　" + RATIO)
    pc = compare(plan, guard_pages(*lines[:2], line, *lines[2:], *cut_lines("　" + RATIO_TALK)))
    assert fixed_texts(plan, pc)[src[RATIO]] == RATIO
    assert (src[RATIO], line) in pc.ignored_lines


def test_inserted_words_in_reflowed_lines_are_added(journal, tmp_path):
    """対照: 校正で段落の途中に足された語（PDF では行が組み直されて、行の途中から始まる）は今までどおり足す。"""
    pub = RATIO.replace("続いて，", "続いて，教師は")
    plan, src = guard_article(tmp_path, journal, [RATIO, RATIO_TALK])
    pc = compare(plan, guard_pages(*cut_lines("　" + pub), *cut_lines("　" + RATIO_TALK)))
    assert fixed_texts(plan, pc)[src[RATIO]] == pub


SPAN_OLD = "各自"
SPAN_NEW = "単元の最初に配った架空の学習カードに印刷した二つ"


@pytest.mark.parametrize("page_break", [False, True], ids=["same-page", "next-page-top"])
def test_long_replacement_across_whole_line_is_not_partly_applied(page_break, journal, tmp_path):
    """校正で docx の短い語句（「各自」）が長い語句（24 文字）に置き換えられ、PDF ではその語句の途中の 1 行が、語句の文字だけで
    できている（行まるごと。次のページの最初の行のことも）。その行を外した残りの文字だけで置き換えない（「各自」→「単元つ」の
    ように、docx にも PDF にもない文字にしない）。直すか、直さない違いとして 13 章に出す。"""
    pre = ("第二時の授業では，教師はまず前時に使った帯図を黒板に示し，基準にする量と比べる量の関係を確かめさせた。その後，"
           "全体で確認した後，班の児童は")
    post = "の帯図にも数直線をかき，割合がいつも同じであることを確かめた。"
    text, pub = pre + SPAN_OLD + post, pre + SPAN_NEW + post
    lines = cut_lines("　" + pre + SPAN_NEW[:2])
    assert len(lines[-1]) == 24
    whole, rest = SPAN_NEW[2:26], SPAN_NEW[26:] + post
    plan, src = guard_article(tmp_path, journal, [text, RATIO_TALK])
    if page_break:
        pages = guard_pages(*lines)
        pages = [pages[0].split("引用および参考文献")[0].rstrip("\n"),
                 "\n".join(["（2）", whole, *cut_lines(rest), *cut_lines("　" + RATIO_TALK), "引用および参考文献",
                            SMALL_REF, *SMALL_EN])]
    else:
        pages = guard_pages(*lines, whole, *cut_lines(rest), *cut_lines("　" + RATIO_TALK))
    pc = compare(plan, pages)
    got = fixed_texts(plan, pc)[src[text]]
    assert got in (text, pub) and changed_paragraphs(plan, pc, {src[text]: got}) == {}
    if got == text:
        assert any(d.src == src[text] and not d.fixable for d in pc.diffs)


SPAN_PRE2 = ("第二時の授業では，教師はまず前時に使った帯図を黒板に示し，基準にする量と比べる量の関係を確かめさせた。その後，"
             "全体で確認した後，班の児童は")
SPAN_POST2 = "の帯図にも数直線をかき，割合がいつも同じであることを確かめた。"


@pytest.mark.parametrize("where", ["start", "end", "start-next-page-top"])
def test_replacement_aligned_to_whole_line_is_not_partly_applied(where, journal, tmp_path):
    """校正で docx の語句（「自分自身が書いて」。8 文字）が長い語句（26〜27 文字）に置き換えられ、PDF ではその語句の最初（最後）の
    24 文字が行まるごと（前の行は行の幅いっぱいで終わり、次の行は docx の文字から始まる。行まるごとの文字は、docx の語句と
    1 文字も同じでない。その行が次のページの最初の行〈照合に使わないページの端の行〉のことも）。その行を外した残りの文字だけで
    置き換えない（「…班の児童は大判の帯図…」「…班の児童たちは大きなの帯図…」のように、docx にも PDF にもない文字にしない。置き換えの
    PDF の側が 20 文字長くないので、20 文字の規則〈LONG_WHY〉では止まらない）。直すか、直さない違いとして 13 章に出す。"""
    old = "自分自身が書いて"
    if where.startswith("start"):
        pre, new = SPAN_PRE2.replace("班の児童は", "班の児童たちは"), SPAN_NEW + "大きな"
        lines = cut_lines("　" + pre)
        assert len(lines[-1]) == 24
        lines += [new[:24], *cut_lines(new[24:] + SPAN_POST2)]
    else:
        pre, new = SPAN_PRE2, "大判" + SPAN_NEW
        lines = cut_lines("　" + pre + new[:2])
        assert len(lines[-1]) == 24
        lines += [new[2:], *cut_lines(SPAN_POST2)]
    text, pub = pre + old + SPAN_POST2, pre + new + SPAN_POST2
    plan, src = guard_article(tmp_path, journal, [text, RATIO_TALK])
    rest = cut_lines("　" + RATIO_TALK)
    if where == "start-next-page-top":
        k = len(cut_lines("　" + pre))          # 行まるごとの行の位置
        pages = guard_pages(*lines[:k])
        pages = [pages[0].split("引用および参考文献")[0].rstrip("\n"),
                 "\n".join(["（2）", *lines[k:], *rest, "引用および参考文献", SMALL_REF, *SMALL_EN])]
    else:
        pages = guard_pages(*lines, *rest)
    pc = compare(plan, pages)
    got = fixed_texts(plan, pc)[src[text]]
    assert got in (text, pub) and changed_paragraphs(plan, pc, {src[text]: got}) == {}
    if got == text:
        assert any(d.src == src[text] and not d.fixable for d in pc.diffs)


def test_long_addition_with_coincidental_char_is_not_partly_applied(journal, tmp_path):
    """校正で docx の「各自」が長い語句（「単元の最初に配った…書いた自分たち」）に置き換えられ、その語句の中の「自」が docx の
    「自」と偶然一致する（違いが「各」→「単元の…書いた」〈長い。直さない〉と「分たち」の挿入に分かれる）。長い違いの隣の挿入だけを
    直して、docx にも PDF にもない文字（「各自分たち」）にしない（まとめて直さない。_join_long）。"""
    text = SPAN_PRE2 + "各自" + SPAN_POST2
    pub = SPAN_PRE2 + "単元の最初に配った架空の学習カードに書いた自分たち" + SPAN_POST2
    plan, src = guard_article(tmp_path, journal, [text, RATIO_TALK])
    pc = compare(plan, guard_pages(*cut_lines("　" + pub), *cut_lines("　" + RATIO_TALK)))
    got = fixed_texts(plan, pc)[src[text]]
    assert got in (text, pub) and changed_paragraphs(plan, pc, {src[text]: got}) == {}
    if got == text:
        assert any(d.src == src[text] and not d.fixable for d in pc.diffs)


def test_added_sentence_with_whole_line_is_not_partly_applied(journal, tmp_path):
    """校正で、段落の途中に一文（「なお，授業の記録は二人の観察者が…合わせた。」）が足され、次の文にも語が足された（「授業の記録は」
    →「授業者の記録は」）。PDF では、足された文の 2 行目が行まるごと、足された文の文字だけでできている。足された文の最初の
    「授業」が docx の次の文の「授業」と偶然一致して、違いが「なお，」の挿入と、行まるごとを含む長い挿入に分かれる。行まるごとを
    含む違いを直さないとき、そのすぐ前の「なお，」だけを足して、docx にも PDF にもない文（「なお，授業の記録は，観点…」）にしない
    （まとめて直さない。行まるごとの違いの範囲は、外した行も含める）。"""
    a = "表現の工夫は，数学的な活動を順に整理した。グラフの傾きは，授業の流れを明らかにした。"
    b = "授業の記録は，観点ごとの特徴を取り上げた。第二の場面は，二つの方法を述べた。"
    added = "なお，授業の記録は二人の観察者が別々に取り，後で照らし合わせた。"
    text, pub = a + b, a + added + b.replace("授業の", "授業者の", 1)
    head = "　" + a + "なお，授業"
    whole = added[len("なお，授業"):len("なお，授業") + 24]
    assert len(whole) == 24 and len(cut_lines(head)[-1]) == 24
    lines = [*cut_lines(head), whole, *cut_lines(pub[len(head) - 1 + 24:])]
    assert "".join(lines).lstrip("　") == pub
    plan, src = guard_article(tmp_path, journal, [text, RATIO_TALK])
    pc = compare(plan, guard_pages(*lines, *cut_lines("　" + RATIO_TALK)))
    got = fixed_texts(plan, pc)[src[text]]
    assert got in (text, pub) and changed_paragraphs(plan, pc, {src[text]: got}) == {}
    if got == text:
        assert any(d.src == src[text] and not d.fixable for d in pc.diffs)


WIDE_CAP = "図１　架空の授業で用いた水そうと目盛りの配置の様子"


@pytest.mark.parametrize("where", ["page-end", "page-top", "inside"])
def test_correction_next_to_wide_caption_line_does_not_add_caption(where, journal, tmp_path):
    """段落の途中の行の変わり目（ページの最後・次のページの最初、段落の途中）に、docx にない、段落の行ほどの幅のキャプションの
    行がまるごと入り、そのすぐ前の行の最後の 1 文字が校正で直されている。キャプションの行を docx に足さない。キャプションの行は、
    校正で足された長い語句の行と区別できないので、直すか、決められなければ docx のまま直さない違いとして 13 章に出す（DESIGN.md
    4.4 の限界）。"""
    lines = body_lines(LESSON)
    pub_lines = list(lines)
    pub_lines[2] = pub_lines[2][:-1] + "★"
    pub = "".join(pub_lines)[1:]
    plan, src = n10_article(tmp_path, journal, [("body", LESSON), ("body", TALK)])
    first, second = [*SMALL_FRONT, *pub_lines[:3]], [*pub_lines[3:], *body_lines(TALK), *N10_TAIL]
    pages = {"page-end": lambda: n10_pages([*first, WIDE_CAP], second),
             "page-top": lambda: n10_pages(first, [WIDE_CAP, *second]),
             "inside": lambda: n10_pages([*first, WIDE_CAP, *second])}[where]()
    pc = compare(plan, pages)
    got = fixed_texts(plan, pc)[src[LESSON]]
    assert got in (LESSON, pub) and changed_paragraphs(plan, pc, {src[LESSON]: got}) == {}
    if got == LESSON:
        assert any(d.src == src[LESSON] and not d.fixable for d in pc.diffs)


@pytest.mark.parametrize("pub, at, width, caps", [
    (RATIO.replace("使った帯図", "使った大きな二枚の帯図"), "大きな", 24, ["図３　架空の帯図の配置"]),
    (RATIO.replace("二つの量", "三つの量"), "三", 23, ["図３　架空の帯図の配置", "表２　架空の得点の一覧"])],
    ids=["insert", "replace"])
def test_short_caption_lines_inside_correction_are_skipped(pub, at, width, caps, journal, tmp_path):
    """対照: 校正で足された語（「大きな二枚の」）の途中や、直された文字（「二」→「三」）のすぐ後ろの行の変わり目に、PDF では
    docx にない図のキャプションの短い行（段落のいちばん長い行の SHORT_LINE 未満の幅）がまるごと入る。段落の途中の本文の行は
    行の幅いっぱいになるので、短い行は長い語句の途中の行ではなく、図の中の文字と考える。その行を外した残りの文字で直す
    （置き換えの PDF の側の長さ〈20 文字の規則〉にも、キャプションの行の文字を数えない）。"""
    body = "　" + pub
    n = body.index(at) + len(at)
    assert n % width == 0
    lines = cut_lines(body, width)
    plan, src = guard_article(tmp_path, journal, [RATIO, RATIO_TALK])
    pc = compare(plan, guard_pages(*lines[:n // width], *caps, *lines[n // width:], *cut_lines("　" + RATIO_TALK)))
    assert fixed_texts(plan, pc)[src[RATIO]] == pub
    assert all((src[RATIO], c) in pc.ignored_lines for c in caps)


def test_replacement_with_long_copy_in_figure_is_not_used(journal, tmp_path):
    """docx の「重視」の位置の PDF に、図の中の原稿の写し（30 文字ほど）が入る。写しの文字で置き換えない（直すなら「中心」
    だけ）。"""
    text = "そこで本研究では，架空の村の学校での体験重視の単元構成を，架空の観点から検討していくことにした。"
    copy = "中心の単元構成を，架空の観点から検討していくことにした．次に，"
    pub = text.replace("体験重視", "体験中心")
    k = pub.index("中心")
    plan, src = guard_article(tmp_path, journal, [text, RATIO_TALK])
    pc = compare(plan, guard_pages(pub[:k], copy, pub[k:], *cut_lines("　" + RATIO_TALK)))
    assert fixed_texts(plan, pc)[src[text]] in (text, pub)


def test_year_split_by_received_date_is_fixed(journal, tmp_path):
    """本文の「（試験，2021）」の年が、PDF では行の途中で受付日につながって分かれ（「（試験，20」受付日、次の行「23）」）、
    出版版で「2023」に直されている。受付日の「2026」の「2」と docx の年を並べず、「2023」に直す（「20223」にしない）。"""
    text = "架空の課題は，記録の件数を整理した（試験，2021）。比例の考えは，式による表現を確かめた。"
    pub = text.replace("2021", "2023")
    cut = pub.index("23）")
    plan, src = guard_article(tmp_path, journal, [text, RATIO_TALK])
    pc = compare(plan, guard_pages(pub[:cut] + " " + GUARD_DATE, pub[cut:], *cut_lines("　" + RATIO_TALK)))
    assert fixed_texts(plan, pc)[src[text]] == pub


def test_page_number_after_received_date_line_is_fixed(journal, tmp_path):
    """引用文献の「pp.6-」の改行の後に受付日の行が入り、その後ろに出版版で直された「14．」がある。受付日の「10月」の「1」と
    docx の数字を並べない（0.20.0 は「114」にしていた）。"""
    plan, src = guard_article(tmp_path, journal, [RATIO], refs=(PAGES_REF,))
    pc = compare(plan, guard_pages(*cut_lines("　" + RATIO), refs=(PAGES_REF[:24], PAGES_REF[24:-3],
                                                                  GUARD_DATE.replace("７月14", "10月10"), "14．")))
    assert fixed_texts(plan, pc)[src[PAGES_REF]] in (PAGES_REF, PAGES_REF.replace("13．", "14．"))


def test_width_fix_inside_merged_fix(journal, tmp_path):
    """docx「pp.45－58」（全角のハイフン）、PDF「pp.46-」の改行の後の「59」。まとめた直しの一部だけを当てはめて「pp.46-5-58」
    にしない（全角・半角の直しはまとめた直しに含める）。"""
    ref = "架空三子（2020）．「架空の比の研究」．『架空学会誌』，第9巻，pp.45－58．"
    plan, src = guard_article(tmp_path, journal, [RATIO], refs=(ref,))
    pc = compare(plan, guard_pages(*cut_lines("　" + RATIO),
                                   refs=("架空三子（2020）．「架空の比の研究」．『架空学会誌』，第9巻，pp.46-", "59．")))
    assert fixed_texts(plan, pc)[src[ref]] == ref.replace("45－58", "46-59")


def test_sub_edits_of_one_diff_are_applied_together(journal, tmp_path):
    """plan_fixes は、1 つの違いを分けた直す箇所の一部がほかの直す箇所と重なるとき、その違いの直す箇所をすべて直さない
    （一部だけを当てはめると、docx にも PDF にもない文字になる）。"""
    text = "架空の研究は pp.45－58 を参照した。"
    plan, src = guard_article(tmp_path, journal, [text])
    s = src[text]
    a = text.index("5－58")
    pc = PdfCheck(diffs=[TextDiff(s, "5－58", "6-59", "", a, a + 4, True)], width={s: {a + 1: "-"}})
    assert fixed_texts(plan, pc)[s] in (text.replace("－", "-"), text.replace("45－58", "46-59"))


NOTE = "本研究は架空の研究会の助成を受けて行った架空の調査の一部である。調査に協力した架空の学級の生徒に感謝する。"


@pytest.mark.parametrize("head, style", [("付記", "notes_head"), ("謝辞", "ack_head")], ids=["notes", "ack"])
def test_run_in_short_heading_is_not_reported(head, style, journal, tmp_path):
    """docx では短い見出しの段落（「付記」など。MIN_CHARS 文字未満なので照合しない）と次の段落に分かれ、PDF では見出しが
    次の段落の最初の行の頭に、全角の空白をはさんで入る（追い込みの見出し）。PDF の行の頭の「付記」は docx の短い段落の
    文字なので、次の段落の違い（EDGE_WHY）にしない。次の段落の校正の直しは直す（対照）。"""
    plan, src = n10_article(tmp_path, journal, [("body", RATIO), (style, head), ("body", NOTE)])
    pub = NOTE.replace("架空の調査", "架空の調査研究")
    pc = compare(plan, n10_pages([*SMALL_FRONT, *body_lines(RATIO), *wrap_lines(f"{head}　{pub}"), *N10_TAIL]))
    assert changed_paragraphs(plan, pc, {src[NOTE]: pub}) == {}
    assert not [d for d in pc.diffs if d.src == src[NOTE] and not d.fixable]
    assert not [t for s, t in pc.ignored_lines if s == src[NOTE]]


# ---------------------------------------------------------------------------- 段落を分断する、表で組んだ図（問題文）
# 表で組んだ図（Word の表に問題文を書いた図。docx では段落の前に結び付いている）が、PDF では段落の途中に出る。図の中の文字は
# 表のセルの段落に当たるが、セルと PDF で句読点の形が違う（docx「．」「･･･」、PDF「。」「…」）と、その文字はどの段落にも
# 当たらない（0.20.0 は、それを分断された段落に足していた）
SPAN_INTRO = "前節を受けて，本稿では確率の課題を単元の最初の授業で用いる。その課題では，同じ袋の玉について異なる手がかりをもつ二人を登場させる。"
SPAN_PRE = ("課題①では，赤い玉が出たという知らせを聞く前の確率を考え，課題②では，赤い玉が出たという知らせを聞いた後の確率を"
            "考える。どちらの課題でも，知らせによって確率の捉え方が変わることに気づかせたい。この捉え方を「確率は知らせによって"
            "変わるもの」")
SPAN_POST = "という考えに結びつけると，課題①と課題②の違いを説明できる。"
SPAN_CAP = "図１　架空の課題"
SPAN_CELLS = ["白い玉が３個，赤い玉が７個入った袋がある．この袋から，はじめにＢさんが玉を１個取り出し，続いてあなたが１個取り出す．",
              "課題①ここで，Ｂさんが玉を取り出したあと，その色を見せないまま手の中に握っているとしよう･･･そのうえで，あなたが"
              "赤い玉を取り出したとすると，Ｂさんの玉が赤い確率は，大きくなるか，小さくなるか，同じままか．"]


def span_pages(pub, page_break=False):
    """SPAN_PRE（の後ろの出版版の文字 pub）の段落が、表で組んだ図に分断される PDF の文字（図の後ろでページが変わることも）。"""
    cells = [c.replace("．", "。").replace("･･･", "…") for c in SPAN_CELLS]
    figure = [SPAN_CAP] + [x for c in cells for x in (c[:48], c[48:])]
    first = [*SMALL_FRONT, *body_lines(SPAN_INTRO), *body_lines(SPAN_PRE), *figure]
    rest = [*wrap_lines(pub[len(SPAN_PRE):]), *body_lines(TALK), *N10_TAIL]
    return n10_pages(first, rest) if page_break else n10_pages(first + rest)


def span_article(tmp_path, journal, text):
    return n10_article(tmp_path, journal, [("body", SPAN_INTRO), ("table", [[c] for c in SPAN_CELLS]), ("fig_cap", SPAN_CAP),
                                           ("body", text), ("body", TALK)])


@pytest.mark.parametrize("page_break", [False, True])
@pytest.mark.parametrize("edit", [False, True])
def test_figure_text_splitting_paragraph_is_not_added(edit, page_break, journal, tmp_path):
    """段落が、表で組んだ図（docx では段落の前の表とキャプション）に分断される（図の後ろで段落が続く。図の後ろでページが
    変わることも）。セルと PDF で形の違う図の中の「。」「…」を段落に足さない。分断の後ろの校正の直し（「結びつける」→
    「結び付ける」）は直す。"""
    text = SPAN_PRE + SPAN_POST
    pub = text.replace("結びつける", "結び付ける") if edit else text
    plan, src = span_article(tmp_path, journal, text)
    pc = compare(plan, span_pages(pub, page_break))
    assert changed_paragraphs(plan, pc, {src[text]: pub}) == {}


def test_paragraph_end_moved_to_free_line_is_not_deleted(journal, tmp_path):
    """分断された段落の最後の「できる。」が出版版で「しやすい。」に直り、PDF ではその行が前の行から折り返した短い行で、
    どの段落にも当たらない（docx の「できる。」と 1 文字しか一致しないので、段落の文字として置けない）。段落の最後の、同じ
    行に PDF の文字がない docx の文字でも、すぐ後ろの行がほかの段落の行でなければ消さない（直すか、直さない違いとして
    13 章に出す）。"""
    text = SPAN_PRE + SPAN_POST
    pub = text.replace("説明できる", "説明しやすい")
    plan, src = span_article(tmp_path, journal, text)
    pc = compare(plan, span_pages(pub))
    got = fixed_texts(plan, pc)[src[text]]
    assert got in (text, pub) and changed_paragraphs(plan, pc, {src[text]: got}) == {}
    if got == text:
        assert any(d.src == src[text] and not d.fixable for d in pc.diffs)


# ---------------------------------------------------------------------------- ダッシュ（行末の「-」）
DASH_BODY = "架空の研究では pp.11–16 の範囲を参照した。"
DASH_KINDS = ["–", "—", "―", "−", "‒"]      # en dash・em dash・水平線・マイナス・数字幅のダッシュ（pdfmatch.DASHES）


@pytest.mark.parametrize("dash", DASH_KINDS, ids=["en", "em", "bar", "minus", "figure"])
def test_dash_at_line_end_follows_pdf(dash, journal, tmp_path):
    """docx のダッシュ（en dash「–」・em dash「—」・水平線「―」・マイナス「−」・数字幅のダッシュ「‒」）と同じ位置に、PDF では
    英数字の後の行末の「-」がある。PDF に合わせて「-」に直す（決定事項 20・23。0.20.0 は docx のダッシュを消していた）。PDF の
    文字が行末のハイフンの印（U+FFFE。何の字形か分からない）なら、docx のまま（違いにしない）。"""
    text = DASH_BODY.replace("–", dash)
    plan, src = n10_article(tmp_path, journal, [("body", text)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, "　架空の研究では pp.11-", "16 の範囲を参照した。", *N10_TAIL]))
    assert changed_paragraphs(plan, pc, {src[text]: DASH_BODY.replace("–", "-")}) == {}
    assert [(d.docx, d.pdf, d.fixable, d.why) for d in pc.diffs if d.src == src[text]] == [(dash, "-", True, "")]
    pc = compare(plan, n10_pages([*SMALL_FRONT, "　架空の研究では pp.11￾", "16 の範囲を参照した。", *N10_TAIL]))
    assert changed_paragraphs(plan, pc, {}) == {} and not [d for d in pc.diffs if d.src == src[text]]


@pytest.mark.parametrize("docx_hyphen, pdf_hyphen", [("‐", "-"), ("‑", "-"), ("-", "‐"), ("－", "‐")],
                         ids=["hyphen", "nobreak", "minus-to-hyphen", "fullwidth-to-hyphen"])
def test_hyphen_variant_at_line_end_follows_pdf(docx_hyphen, pdf_hyphen, journal, tmp_path):
    """docx のハイフンの仲間（「‐」、Word の改行なしハイフン〈w:noBreakHyphen〉の「‑」、「-」「－」）と同じ位置に、PDF では
    英数字の後の行末の、docx と違う「-」「‐」がある。行の途中と同じく、PDF の文字に合わせて直す（0.20.0 から、行末でだけ
    黙って docx のまま残していた）。PDF の文字が行末のハイフンの印（U+FFFE）なら、docx のまま（違いにしない）。"""
    text = DASH_BODY.replace("–", docx_hyphen)
    plan, src = n10_article(tmp_path, journal, [("body", text)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, f"　架空の研究では pp.11{pdf_hyphen}", "16 の範囲を参照した。", *N10_TAIL]))
    assert changed_paragraphs(plan, pc, {src[text]: DASH_BODY.replace("–", pdf_hyphen)}) == {}
    assert [(d.docx, d.pdf, d.fixable, d.why) for d in pc.diffs if d.src == src[text]] == [(docx_hyphen, pdf_hyphen, True, "")]
    pc = compare(plan, n10_pages([*SMALL_FRONT, "　架空の研究では pp.11￾", "16 の範囲を参照した。", *N10_TAIL]))
    assert changed_paragraphs(plan, pc, {}) == {} and not [d for d in pc.diffs if d.src == src[text]]


def test_hyphenation_without_docx_dash_is_not_added(journal, tmp_path):
    """対照: docx にダッシュ・ハイフンのない位置の、PDF の英数字の後の行末の「-」（行末のハイフネーション）は、今までどおり
    docx に足さない（英単語の途中の改行のハイフン）。"""
    text = "架空の研究では selfexplanation の効果を調べた。"
    plan, src = n10_article(tmp_path, journal, [("body", text)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, "　架空の研究では self-", "explanation の効果を調べた。", *N10_TAIL]))
    assert changed_paragraphs(plan, pc, {}) == {} and not [d for d in pc.diffs if d.src == src[text]]


@pytest.mark.parametrize("docx_dash, pdf_dash", [("—", "-"), ("−", "-"), ("-", "–"), ("–", "—"), ("‑", "-")])
def test_dash_in_middle_of_line_follows_pdf(docx_dash, pdf_dash, journal, tmp_path):
    """行の途中のダッシュ・ハイフンの違い（docx と PDF で別の文字）は、今までどおり PDF の文字に合わせて直す。"""
    text = DASH_BODY.replace("–", docx_dash)
    plan, src = n10_article(tmp_path, journal, [("body", text)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, f"　架空の研究では pp.11{pdf_dash}16 の範囲を参照", "した。", *N10_TAIL]))
    assert changed_paragraphs(plan, pc, {src[text]: DASH_BODY.replace("–", pdf_dash)}) == {}


NBH = "<w:r><w:noBreakHyphen/></w:r>"      # Word の改行なしハイフン（読み取りでは「‑」）


@pytest.mark.parametrize("pdf_lines", [["　架空の研究では pp.11-16 の範囲を参照", "した。"],
                                       ["　架空の研究では pp.11-", "16 の範囲を参照した。"]], ids=["middle", "line-end"])
def test_no_break_hyphen_follows_pdf_in_route2(pdf_lines, journal, meta, tmp_path, monkeypatch):
    """docx の Word の改行なしハイフン（w:noBreakHyphen。読み取りでは「‑」）と同じ位置に、PDF では「-」がある（行の途中と、英数字の
    後の行末）。ルート2 は PDF に合わせて「-」に直す（改行なしハイフンを削除し、「-」を挿入する変更履歴。却下すると元に戻る）。
    XML は「-」で、不変性チェックは合格する（0.21.0 の作業の途中の版は、直せない文字として 13 章に出し、XML は「‑」のままだった）。
    ルート1 は、直せる違いとして 13 章に出すだけ（XML は「‑」）。"""
    plan, src = n10_article(tmp_path, journal, [("body", ["架空の研究では pp.11", NBH, "16 の範囲を参照した。"])])
    pages = n10_pages([*SMALL_FRONT, *pdf_lines, *N10_TAIL])
    res = convert_with_pages(tmp_path, monkeypatch, journal, meta, pages, "pdf", docx=tmp_path / "n10.docx")
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    assert [(f.old, f.new, f.applied) for f in res.docx_fix.fixes] == [("‑", "-", True)]
    assert "架空の研究では pp.11-16 の範囲を参照した。" in texts(load(res))
    assert "架空の研究では pp.11-16 の範囲を参照した。" in paragraphs(res.docx_fix.path)
    assert "架空の研究では pp.11‑16 の範囲を参照した。" in paragraphs(res.docx_fix.path, reject=True)
    res1 = convert_with_pages(tmp_path, monkeypatch, journal, meta, pages, "docx", docx=tmp_path / "n10.docx")
    assert "架空の研究では pp.11‑16 の範囲を参照した。" in texts(load(res1))
    assert [(d.docx, d.pdf, d.fixable) for d in res1.pdf_check.diffs] == [("‑", "-", True)]


def test_en_dash_in_reference_at_line_end_is_not_deleted(journal, tmp_path):
    """引用文献のページの範囲の en dash（docx「pp. 63–69.」）が、PDF では「pp.63-」の改行の後の「69．」。「–」を消さずに「-」に
    直す（0.20.0 は「6369」にしていた）。"""
    ref = "架空花子（2016）．「架空の授業の研究」．『架空大学教育学部紀要』, 第18巻, pp. 63–69."
    plan, src = n10_article(tmp_path, journal, [("body", TALK)], refs=[ref])
    pc = compare(plan, n10_pages([*SMALL_FRONT, *body_lines(TALK), "引用および参考文献", SMALL_REF,
                                  "架空花子（2016）．「架空の授業の研究」．『架空大学", "教育学部紀要』，第18巻，pp.63-", "69．",
                                  *SMALL_EN]))
    assert "63-69" in fixed_texts(plan, pc)[src[ref]]


# ---------------------------------------------------------------------------- 数式（PDF の文字に入らない数式の位置）
# pdfium は、文字として取り出せない数式の字形の位置を、全角の空白を含む空白の並び（「　 　」など）にする。校正で足された
# 数式を含む語句（「（p1，…，p4 とおく）」など）は、PDF の文字では数式の欠けた語句（「（，…，とおく）」）になるので、足すと
# docx も XML も PDF と違う文になる。直さずに 13 章に出す（MATH_WHY）
FORMULA = "　 　"        # PDF の数式 1 つの位置の空白の並び（形だけをまねる）
PROB = ["各回の結果から相対度数を求め，これを試行の確率とよび，", mf.omath(mf.mr("p")), "の値の変化を表に記録した。"]
PROB_TEXT = "".join(x if not x.startswith("<") else "￼" for x in PROB)       # docx の段落の文字（数式は OBJ）


@pytest.mark.parametrize("split", [False, True], ids=["same-line", "line-break"])
def test_insertion_with_unreadable_formula_is_not_fixed(split, journal, tmp_path):
    """校正で「（p1，…，p4 とおく）」が足され、PDF の文字では数式の位置が空白の並び（「（　 　， …， 　 　とおく）」）。
    数式の欠けた「（，…，とおく）」を足さず、直さない違い（MATH_WHY）として 13 章に出す（PDF の文字は、数式の位置を「〓」で
    示す）。同じ段落の、数式から離れた位置の校正の直し（「表に」→「表に順に」）は直す。数式の位置で行が変わっても同じ。"""
    from jasme_jats.pdfmatch import MATH_WHY
    plan, src = n10_article(tmp_path, journal, [("body", PROB), ("body", TALK)])
    s = src[PROB_TEXT]
    head = f"　各回の結果から相対度数を求め，これを試行の確率 （{FORMULA}， …， {FORMULA}"
    tail = f"とおく） とよび， {FORMULA}の値の変化を表に順に記録した。"
    lines = [head, tail] if split else [head + tail[:10], tail[10:]]
    pc = compare(plan, n10_pages([*SMALL_FRONT, *lines, *body_lines(TALK), *N10_TAIL]))
    assert fixed_texts(plan, pc)[s] == PROB_TEXT.replace("表に記録", "表に順に記録")
    assert [(d.docx, d.pdf.replace(LINE_MARK, ""), d.fixable, d.why) for d in pc.diffs if d.src == s and d.why] == [
        ("", "（〓，…，〓とおく）", False, MATH_WHY)]


def test_docx_text_at_unreadable_formula_is_not_deleted(journal, tmp_path):
    """docx は文字の「p」、PDF では数式になっていて、文字に入らず空白の並び。docx の「p」を消さず、直さない違い（MATH_WHY）に
    する。"""
    from jasme_jats.pdfmatch import MATH_WHY
    text = "この試行で赤が出る確率をpとし，その値を予想させた。"
    plan, src = n10_article(tmp_path, journal, [("body", text), ("body", TALK)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, f"　この試行で赤が出る確率を{FORMULA}とし， その値を予想させた。",
                                  *body_lines(TALK), *N10_TAIL]))
    assert changed_paragraphs(plan, pc, {}) == {}
    assert [(d.docx, d.fixable, d.why) for d in pc.diffs if d.src == src[text]] == [("p", False, MATH_WHY)]


def test_addition_between_unreadable_formulas_is_not_fixed(journal, tmp_path):
    """docx には数式が 2 つ（「（p，p）」）、PDF では校正で数式が 3 つになり、どれも文字に入らず空白の並び（「（　 　， 　 　，
    　 　）」）。違う文字は数式の間の「，」1 つだが、足すと数式の欠けた式になる（docx に数式は足せない）。docx のまま、直さない
    違い（MATH_WHY）として 13 章に出す（0.20.0 は、docx の数式の位置に PDF の「，」を並べて、黙って違いにしなかった）。"""
    from jasme_jats.pdfmatch import MATH_WHY
    pair = ["値の組（", mf.omath(mf.mr("p")), "，", mf.omath(mf.mr("p")), "）を順に調べ，その結果を表にまとめた。"]
    text = "".join(x if not x.startswith("<") else "￼" for x in pair)
    plan, src = n10_article(tmp_path, journal, [("body", pair), ("body", TALK)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, f"　値の組（{FORMULA}， {FORMULA}， {FORMULA}）を順に調べ， その",
                                  "結果を表にまとめた。", *body_lines(TALK), *N10_TAIL]))
    assert changed_paragraphs(plan, pc, {}) == {}
    assert [(d.pdf, d.fixable, d.why) for d in pc.diffs if d.src == src[text]] == [("〓，〓", False, MATH_WHY)]


@pytest.mark.parametrize("route", ["docx", "pdf"])
def test_formula_and_insert_position_shown_in_report(route, journal, meta, tmp_path, monkeypatch):
    """直さない違いの docx の文字と前後の文字では、docx の数式も「〓」で示す（ルート1 の 13.1・ルート2 の 13.4 の前後の欄で、
    数式が消えて見えないように）。ルート2 の 13.2 では、docx の側に文字がない（PDF にだけある文字の）行の docx の欄に、足す位置の
    前後の docx の文字（「…［］…」）を出す（同じ段落に同じ PDF の文字の行が並んでも見分けられるように）。表に「〓」があるときは、
    docx の欄と PDF の欄で意味が違う（docx の数式・画像と、PDF で読み取れない部分）ことを、表の前に添える。"""
    pair = ["値の組（", mf.omath(mf.mr("p")), "，", mf.omath(mf.mr("p")), "）を順に調べ，その結果を表にまとめた。"]
    text = EDGE_BODY + "後に，課題を述べる"
    n10_article(tmp_path, journal, [("body", pair), ("body", text), ("body", EDGE_NEXT)])
    pages = n10_pages([*SMALL_FRONT, f"　値の組（{FORMULA}， {FORMULA}， {FORMULA}）を順に調べ， その", "結果を表にまとめた。",
                       *body_lines(text), "。", *body_lines(EDGE_NEXT), *N10_TAIL])
    res = convert_with_pages(tmp_path, monkeypatch, journal, meta, pages, route, docx=tmp_path / "n10.docx")
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    ch13 = chapters(res)[1]
    from jasme_jats.report import FORMULA_NOTE
    if route == "docx":
        section = ch13.split("### 13.1")[1].split("### 13.2")[0]
        assert "| 〓 | 〓，〓" in ch13 and "値の組（〓，［〓］）を順に調べ" in section and FORMULA_NOTE in section
    else:
        from jasme_jats.pdfmatch import EDGE_WHY, MATH_WHY
        from jasme_jats.report import INSERT_AT
        section = ch13.split("### 13.2")[1].split("### 13.3")[0]
        assert f"| 〓 | 〓，〓 | {MATH_WHY} |" in section and FORMULA_NOTE in section
        assert f"| …に，課題を述べる{INSERT_AT} | 。 | {EDGE_WHY} |" in section and INSERT_AT == "［］"
        section = ch13.split("### 13.4")[1].split("### 13.5")[0]
        assert "値の組（〓，［〓］）を順に調べ" in section and FORMULA_NOTE in section


@pytest.mark.parametrize("docx, pdf_lines, pub", [
    # 行の両端そろえで句読点の後に入る半角の空白
    ("授業では，最初に予想を書かせた。次に，班ごとに実験を行わせた。",
     ["　授業では， 最初に予想を書かせた。 次に， 三人の", "班ごとに実験を行わせた。"],
     "授業では，最初に予想を書かせた。次に，三人の班ごとに実験を行わせた。"),
    # 全角の空白を含まない、半角の空白 2 つ
    ("結果を集計した。その後，表を用いて全体で検討した。", ["　結果を集計した。 その後，  二つの表を用いて全体", "で検討した。"],
     "結果を集計した。その後，二つの表を用いて全体で検討した。"),
    # 英文の段落の 1 行目の字下げ（全角の空白 2 つと半角の空白）の直後
    ("This fictional study examines how pupils explained ratios.",
     ["　　 Briefly, This fictional study examines how", "pupils explained ratios."],
     "Briefly, This fictional study examines how pupils explained ratios."),
], ids=["justified", "two-spaces", "english-indent"])
def test_corrections_next_to_ordinary_spaces_are_fixed(docx, pdf_lines, pub, journal, tmp_path):
    """対照: 数式の位置とみなすのは、全角の空白を含む 2 文字以上の空白の並び（行の最初の字下げを除く）だけ。両端そろえの空白・
    半角の空白の並び・英文の段落の字下げのすぐ隣の校正の直しは、今までどおり直す（PDF の空白は信頼できない）。"""
    plan, src = n10_article(tmp_path, journal, [("body", docx), ("body", TALK)])
    pc = compare(plan, n10_pages([*SMALL_FRONT, *pdf_lines, *body_lines(TALK), *N10_TAIL]))
    assert changed_paragraphs(plan, pc, {src[docx]: pub}) == {}
