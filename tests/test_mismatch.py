"""要確認 pdf_mismatch（PDF と文字が違う箇所）。手で作った照合の結果（PdfCheck）で、件数・行の形・並び・文の 2 通りを確かめる（W3 の手順 6）。
文字はすべて架空。通しの変換は tests/test_pdfmatch.py。"""
from types import SimpleNamespace

from jasme_jats.pdfmatch import CONTENT, FIX, SILENT, UNSURE, PdfCheck, TextDiff, level_of
from jasme_jats.report import MISMATCH_MANY, MISMATCH_SHOWN, TO_CHECK, mismatch_diffs, mismatch_lines, pdf_actions

TEXT = "この活動ではふくろうの絵を使い，参加者は2468名で，柿の木の観察を行った。3. 次に"


def diff(label, docx, pdf, start, src="d71", **kw):
    """手で作った違い（区分は level_of に任せず、label を付けて CONTENT にする）。"""
    return TextDiff(src, docx, pdf, "", start, start + len(docx), level=kw.pop("level", CONTENT), label=label, **kw)


def result(diffs, fx=None, checked=50, text=TEXT):
    para = SimpleNamespace(plain=lambda: text)
    plan = SimpleNamespace(paras={"d71": para, "d72": para}, locations={"d71": "本文 2 章 5 段落目", "d72": "引用文献 9 件目"},
                           pdf_numbers={})
    return SimpleNamespace(pdf_check=PdfCheck(diffs=diffs, checked=checked), docx_fix=fx, plan=plan, route="docx",
                           supplement=None)


def keys(r):
    return [a.key for a in pdf_actions(r)]


def test_only_content_diffs_make_the_action():
    """(a) 内容の違い（区分 CONTENT）がなければ出ない: 表記の違い（FIX・SILENT）と照合できなかった所（UNSURE）は数えない。"""
    ds = [TextDiff("d71", "1", "１", "", 0, 1, kind="typeset", level=FIX, label="pair"),
          TextDiff("d71", "x", "y", "", 3, 4, kind="typeset", fixable=False, level=SILENT, label="unfixable"),
          TextDiff("d71", "ふくろう", "みみずく", "", 6, 10, why="head", level=UNSURE, label="head")]
    assert keys(result(ds)) == [] and mismatch_diffs(result(ds)) == []
    assert keys(result([diff("word", "ふくろう", "みみずく", 6)])) == ["pdf_mismatch"]


def test_line_forms_and_four_places():
    """(b) 件数・行の形（3.1。置き換え・docx にだけある・PDF にだけある・Word の番号・約物だけ）。冒頭・枠・コマンドラインに出る。"""
    ds = [diff("word", "ふくろう", "みみずく", 6),
          diff("word", "の観察", "", TEXT.index("の観察")),
          diff("word", "", "毎朝の", TEXT.index("観察")),
          diff("number", "", "4.", 0, number="3.", src="d72"),
          diff("punct", "2468", "2,468", TEXT.index("2468"))]
    r = result(ds)
    (a,) = [x for x in pdf_actions(r) if x.key == "pdf_mismatch"]
    assert a.level == TO_CHECK
    assert mismatch_lines(r) == [
        "本文 2 章 5 段落目（d71）: docx「この活動では［ふくろう］の絵を使い，参加者は…」→ PDF「みみずく」",
        "本文 2 章 5 段落目（d71）: docx「…2468名で，柿の木［の観察］を行った。3. 次に」→ PDF にはない",
        "本文 2 章 5 段落目（d71）: docx「…468名で，柿の木の［］観察を行った。3. …」→ PDF「毎朝の」（docx にはない）",
        "引用文献 9 件目（d72）: docx の番号「3.」→ PDF「4.」",
        "本文 2 章 5 段落目（d71）: docx「…の絵を使い，参加者は［2468］名で，柿の木の観察を…」→ PDF「2,468」"]
    assert a.top.startswith("> **要確認: 出版版 PDF と文字が違う箇所が 5 件あります（13.1）。**")
    assert a.top.count("\n> - ") == 5
    assert "出版版 PDF と文字が違う箇所**（5 件。13.1）" in a.checklist and a.checklist.startswith("- [ ] ")
    assert a.box_title == "出版版 PDF と文字が違う箇所が 5 件あります（要確認）"
    assert a.cli.startswith("要確認: 出版版 PDF と文字が違う箇所 5 件（レポートの冒頭と 13.1）")
    assert "\x00" in a.box_detail                      # 画面の操作は目印（step）で書く


def test_many_and_shown_limit():
    """(c) 語句が 12 件のとき、先頭 10 件と「ほか 2 件」、語句が多いので校正後の docx でない可能性の文が入る。"""
    ds = [diff("word", "ふくろう", f"鳥{i}", 6) for i in range(12)]
    (a,) = pdf_actions(result(ds))
    assert MISMATCH_SHOWN == 10 and a.top.count("\n> - ") == 11 and "…ほか 2 件（13.1）" in a.top
    assert "校正後の docx でない可能性" not in a.top and "受け取った docx が校正後の版でない可能性があります" in a.top
    assert a.box_detail.count("\n・") == 10 and "…ほか 2 件" in a.box_detail
    assert "校正後の版でない可能性があります。1 か所ずつ直す前に" in a.box_detail and "**" not in a.box_detail


def test_many_counts_words_and_numbers_only():
    """(d) 約物だけ・大文字・小文字が多くても、語句の違いが 5 件未満なら「校正後の docx でない可能性」の文は入らない（5 件で入る）。"""
    ds = [diff("punct", "2468", "2,468", 2) for _ in range(6)] + [diff("case", "Ab", "AB", 2) for _ in range(3)]
    (a,) = pdf_actions(result(ds))
    assert "9 件あります" in a.top and "可能性があります" not in a.top
    ds += [diff("word", "ふくろう", "鳥", 6) for _ in range(MISMATCH_MANY - 1)]
    (a,) = pdf_actions(result(ds))
    assert "可能性があります" not in a.top
    ds += [diff("number", "", "4.", 0, number="3.")]
    (a,) = pdf_actions(result(ds))
    assert "可能性があります" in a.top


def test_order():
    """(e) 並び: 語句・番号 → 大文字・小文字 → 約物だけ。同じ種類の中は docx の順。"""
    ds = [diff("punct", "2468", "2,468", 20), diff("case", "Ab", "AB", 11), diff("word", "ふくろう", "鳥", 6),
          diff("number", "", "4.", 0, number="3."), diff("word", "絵", "図", 14)]
    assert [d.label for d in mismatch_diffs(result(ds))] == ["word", "number", "word", "case", "punct"]


def test_two_sentences_for_typeset_fixed_or_not():
    """(f) 表記を PDF に合わせたか（補った docx を作ったか）で文が 2 通り。"""
    ds = [diff("word", "ふくろう", "鳥", 6)]
    (a,) = pdf_actions(result(ds))
    assert "表記も PDF に合わせていません" in a.top and "表記も PDF に合わせていません" in a.box_detail
    fx = SimpleNamespace(check=PdfCheck(diffs=ds, checked=50), texts={"d71": TEXT}, locations={"d71": "本文 2 章 5 段落目"},
                         unmatched=[])
    r = result([], fx=fx)
    r.pdf_check = PdfCheck(checked=50)                 # 補った docx の照合は違いなし。知らせは元の docx の照合（fx.check）から
    (a,) = pdf_actions(r)
    assert "PDF に合わせて直したのは、全角・半角や句読点などの表記だけです" in a.top
    assert "表記も PDF に合わせていません" not in a.top
    assert "本文 2 章 5 段落目（d71）: docx「この活動では［ふくろう］の絵を使い" in a.top


def test_level_empty_diff_counts_as_content():
    """(h) 手で作った違い（level が空）でも level_of で内容の違いとして出る。"""
    d = TextDiff("d71", "ふくろう", "鳥", "", 6, 10)
    assert d.level == "" and level_of(d) == CONTENT
    assert keys(result([d])) == ["pdf_mismatch"]


def test_number_with_text_uses_excerpt_form():
    """Word の番号と、続く本文の文字にかかる違いは、番号を断って前に置き、本文の違う部分を［ ］で示す（番号だけの違いは「docx の番号」の形）。"""
    d = diff("word", "ふくろう", "鳥", 6, number="●")
    (line,) = mismatch_lines(result([d]))
    assert line == "本文 2 章 5 段落目（d71）: docx「（Word の番号「●」）この活動では［ふくろう］の絵を使い，参加者は…」→ PDF「鳥」"


# ---------------------------------------------------------------------------- 13 章（W2 の手順 7。render_pdf）
def chapter13(r, fx=None, pc=None):
    """手で作った結果から 13 章（render_pdf）の行を作って 1 つの文字列にする。"""
    from jasme_jats.report import render_pdf
    L = []
    render_pdf(L, r, pc or r.pdf_check, fx)
    return "\n".join(L)


def make_fx(check, applied=(), skipped=()):
    from pathlib import Path
    return SimpleNamespace(check=check, texts={"d71": TEXT, "d72": TEXT}, locations={"d71": "本文 2 章 5 段落目", "d72": "引用文献 9 件目"},
                           unmatched=list(check.unmatched), path=Path("99_11_PDFで補完した原稿.docx"),
                           applied_typeset=list(applied), skipped_typeset=list(skipped))


def fix(kind, old="1", new="１"):
    return SimpleNamespace(kind=kind, old=old, new=new, typeset=True, applied=True, reason="")


def test_section_13_1_has_the_same_count_as_the_action():
    """(a) 13.1 の表の行数が pdf_mismatch の件数と同じ。ないときは「ありません。」。"""
    ds = [diff("word", "ふくろう", "みみずく", 6), diff("punct", "2468", "2,468", TEXT.index("2468")),
          diff("number", "", "4.", 0, number="3.", src="d72")]
    r = result(ds)
    sec = chapter13(r).split("### 13.1")[1].split("### 13.2")[0]
    rows = [x for x in sec.splitlines() if x.startswith("| d7")]
    assert len(rows) == len(mismatch_diffs(r)) == 3
    assert "| d71 | 本文 2 章 5 段落目 | この活動では［ふくろう］の絵を使い，参加者は… | みみずく | 語句 |" in sec
    assert "ありません。" in chapter13(result([])).split("### 13.1")[1].split("### 13.2")[0]


def test_section_13_2_counts_only():
    """(b) 13.2 は件数だけ（表がない）。「合わせた」は applied_typeset の数と Word の番号の数、「合わせなかった」は silent_diffs の
    label ごとと skipped_typeset（直せない位置にあるもの）。"""
    silent = [TextDiff("d71", "x", "y", "", 3, 4, kind="typeset", fixable=False, level=SILENT, label="unfixable"),
              TextDiff("d71", "a", "b", "", 3, 4, level=SILENT, label="script"),
              TextDiff("d71", "a", "b", "", 5, 6, level=SILENT, label="script+mixed"),
              TextDiff("d71", "a", "b", "", 7, 8, level=SILENT, label="noteform"),
              TextDiff("d71", "a", "b", "", 9, 10, level=SILENT, label="glyph")]
    r = result([])
    fx = make_fx(PdfCheck(diffs=silent, checked=50), applied=[fix("width"), fix("width"), fix("space", " ", "")],
                 skipped=[fix("width")])
    r.plan.pdf_numbers = {("auto", "d71"): "・", ("fnref", "footnote:1"): "1）"}
    r.docx_fix = fx
    sec = chapter13(r, fx).split("### 13.2")[1].split("### 13.3")[0]
    assert "合わせた表記: 英数字・記号の全角・半角 2 箇所、PDF にない空白 1 箇所、Word が付ける番号 2 件。" in sec
    assert "合わせなかった表記の違い（docx のまま。確認は要りません）: 上付き・下付きの文字 2、注番号の形 1、字形だけの違い 1、" \
           "直せない位置にあるもの（リンクの中・図形のある段落・直さない違いの隣など） 1。" in sec
    assert "|" not in sec


def test_section_13_3_table_is_cut_at_30_rows():
    """(c) 13.3 の見出しの文と、照合できなかった違いの表は 30 行で切れる（わけは短い名前）。"""
    ds = [TextDiff("d71", "", f"文{i}", "［］前後", 3, 3, why="edge", level=UNSURE, label="edge") for i in range(35)]
    sec = chapter13(result(ds)).split("### 13.3")[1]
    assert sec.startswith(" 照合できなかった箇所（記録。PDF と見比べたいときに使う）")
    assert "- 決められなかった違い 35 件（段落の端 35）" in sec
    rows = [x for x in sec.splitlines() if x.startswith("| d71 |")]
    assert len(rows) == 30 and "…ほか 5 件（表は 30 行まで）。" in sec


def test_section_13_3_found_elsewhere_line():
    """(d) PDF に見つからなかった段落は、同じ文字が PDF のどこかにある段落を除いて数え、その段落は件数の 1 行にする。"""
    pc = PdfCheck(checked=50, unmatched=["d71", "d72"], found_elsewhere=["d72"])
    sec = chapter13(result([])).split("### 13.3")[1]
    assert "PDF に見つからなかった段落はありません。" in sec
    r = result([])
    r.pdf_check = pc
    sec = chapter13(r).split("### 13.3")[1]
    assert "- PDF に見つからなかった段落 1 件" in sec and "| d71 | 本文 2 章 5 段落目 |" in sec and "| d72 |" not in sec
    assert "同じ文字が PDF のどこかにある段落 1 件" in sec


def test_route_docx_wording():
    """(e) --route docx（補った docx がない）の 13 章: 最初の文が「表記も PDF に合わせていません」、13.2 の見出しが「PDF と表記が
    違う箇所（docx のまま）」、13.4 がない。ルート2 は 13.4（補完の確かめ）まである。"""
    r = result([diff("word", "ふくろう", "鳥", 6)])
    text = chapter13(r)
    assert "**XML は docx の文字のままで、表記も PDF に合わせていません**（コマンドラインの `--route docx`）" in text
    assert "### 13.2 PDF と表記が違う箇所（docx のまま）" in text and "13.4" not in text
    fx = make_fx(PdfCheck(diffs=[], checked=50))
    r2 = result([], fx=fx)
    r2.supplement = SimpleNamespace(ok=True, typeset=3, problems=[])
    r2.docx_fix = fx
    text = chapter13(r2, fx)
    assert "補った docx「99_11_PDFで補完した原稿.docx」。Word の変更履歴つき" in text
    assert "### 13.2 PDF に合わせた表記（確認は要りません）" in text and "### 13.4 補完の確かめ\n\n合格（表記を合わせた箇所 3 文字）" in text


def test_summary_line_form(monkeypatch):
    """(f) 1 章の行: PDF と違う箇所 N 件（要確認。13.1）／表記を PDF に合わせた M 箇所／照合できなかった箇所と PDF に見つからない段落（13.3）。"""
    from jasme_jats.report import pdf_summary
    import jasme_jats.pdfdocx as pdfdocx
    ds = [diff("word", "ふくろう", "鳥", 6),
          TextDiff("d71", "", "文", "", 3, 3, why="edge", level=UNSURE, label="edge")]
    r = result(ds)
    r.pdf_check.unmatched = ["d71", "d72"]
    r.pdf_check.found_elsewhere = ["d72"]
    r.supplement = None
    r.plan.pdf_numbers = {}
    assert pdf_summary(r) == ("PDF と違う箇所 1 件（要確認。13.1） / PDF と表記が違う箇所 0 箇所（docx のまま） / "
                              "照合できなかった箇所 1 件・PDF に見つからない段落 1 件（13.3）（13 章）")
    fx = make_fx(PdfCheck(diffs=[], checked=50), applied=[fix("width")] * 3)
    r2 = result([], fx=fx)
    r2.supplement = SimpleNamespace(ok=False, typeset=0, problems=[])
    r2.plan.pdf_numbers = {("auto", "d71"): "・"}
    monkeypatch.setattr(pdfdocx, "tracked_counts", lambda path: (4, 5))
    assert pdf_summary(r2) == ("PDF と違う箇所 なし / 表記を PDF に合わせた 4 箇所（変更履歴: 挿入 4・削除 5） / "
                               "補完の確かめ: 不合格（要対応）（13 章）")


# ---------------------------------------------------------------- 表のセルの確かめ（W2 の手順 8。文字はすべて架空）
def _cell_plan(journal, tmp_path, rows):
    import make_fixtures as mf
    from jasme_jats.pipeline import _mechanical
    mf.make_article(tmp_path / "cells.docx", "セルの確かめの検証用文書", lambda b: [
        mf.para(mf.S["sec1"], "１．はじめに"), mf.para(mf.S["body"], "本文の段落は、表の前に置く架空の文である。"),
        mf.para(mf.S["tab_cap"], "表１　架空の表"), mf.table([[mf.cell(c) for c in row] for row in rows])])
    return _mechanical(tmp_path / "cells.docx", journal)[1]


def _cell_pages(*lines):
    return ["本文の段落は表の前に置く架空の文である。\n" + "\n".join(lines)]


def test_cell_misses_found_and_not_found(journal, tmp_path):
    """(a)(b)(c) 8 文字以上の行が PDF に見つからなければ 1 件。「：」・全角半角・行の折り返しだけの違いと、7 文字以下の行は 0 件。"""
    from jasme_jats.pdfmatch import cell_misses
    rows = [["水色の札を配った後の残りの枚数", "A組：ABC123 の結果"], ["七文字の短い行", "12345"]]
    plan = _cell_plan(journal, tmp_path, rows)
    src = {p.plain(): p.src for p in plan.paras.values()}
    assert cell_misses(plan, _cell_pages("水色の札を配った後の", "残りの枚数", "Ａ組 ABC１２３ の結果", "七文字の短い行別")) == []
    got = cell_misses(plan, _cell_pages("水色の札を配った後の", "A組 ABC123 の結果"))
    assert got == [(src["水色の札を配った後の残りの枚数"], "水色の札を配った後の残りの枚数")]
    assert [t for _, t in cell_misses(plan, _cell_pages("水色の札を配った後の残りの枚数", "A組 ABC123 の結果", "七文字"))] == []


def test_cell_misses_split_by_objects_and_boxes(monkeypatch):
    """(d)(e) 改行と数式・画像の位置で行に分けて、行ごとに見る。囲み（文脈 cell）の段落も同じ。cell 以外の文脈は見ない。"""
    from jasme_jats import linker
    from jasme_jats.model import OBJ
    from jasme_jats.pdfmatch import cell_misses
    para = lambda src, t: SimpleNamespace(src=src, plain=lambda: t)
    ps = [(para("d1", f"前半の文字が長い行です{OBJ}後半は別の行になります\n三行目は短い"), "cell"),
          (para("d2", "囲みの中にある長い一文の行"), "cell"), (para("d3", "本文の段落なので見ない長い行です"), "body")]
    monkeypatch.setattr(linker, "body_paragraphs", lambda plan: ps)
    got = cell_misses(None, ["前半の文字が長い行です 後半は別の行になります"])
    assert got == [("d2", "囲みの中にある長い一文の行")]
    got = cell_misses(None, ["前半の文字が長い行です"])
    assert [s for s, _ in got] == ["d1", "d2"] and got[0][1] == "後半は別の行になります"


def test_cell_misses_in_action_and_13_1():
    """(f)(g) 件数に入り（文字の違いの後ろに並ぶ）、行の形は 3.1 のとおり。13.1 の表の「表のセル」の行にもなる。語句の違いが多い文の数には入らない。"""
    from jasme_jats.report import mismatch_cells, mismatch_count
    r = result([diff("word", "ふくろう", "みみずく", 6)])
    r.pdf_check.cell_misses = [("d72", "水色の札を配った後の残りの枚数")]
    assert mismatch_cells(r) == [("d72", "水色の札を配った後の残りの枚数")] and mismatch_count(r) == 2
    assert mismatch_lines(r)[-1] == "引用文献 9 件目（d72）: 「水色の札を配った後の残りの枚数」と同じ文字が PDF に見つからない"
    (a,) = pdf_actions(r)
    assert "が 2 件あります" in a.top and a.top.count("\n> - ") == 2
    assert "表のセル" in chapter13(r) and "水色の札を配った後の残りの枚数" in chapter13(r)
    r2 = result([])
    r2.pdf_check.cell_misses = [("d72", f"表の中の長い行{i}です") for i in range(MISMATCH_MANY + 1)]
    (a,) = pdf_actions(r2)
    assert "可能性があります" not in a.top and f"{MISMATCH_MANY + 1} 件" in a.top
