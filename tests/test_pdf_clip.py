"""出版版 PDF の描かれない文字（クリップの外の文字）を照合に使わない（pdfmatch.extract_pages。C022）。

PDF は手で組む（英字だけ・Helvetica・外部のライブラリなし）。文字はすべて架空。
"""
import pytest

pdfium = pytest.importorskip("pypdfium2")

from jasme_jats.pdfmatch import PdfPages, extract_pages  # noqa: E402


def _pdf(content: bytes, forms=()) -> bytes:
    """1 ページの PDF。forms は [(名前, 行列, 中身, 中で使う Form の名前の並び)]（Form XObject。ページの資源にすべて入れる）。"""
    names = {n: 6 + k for k, (n, _, _, _) in enumerate(forms)}
    xo = b" ".join(b"/%s %d 0 R" % (n.encode(), names[n]) for n in names)
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> /XObject << " + xo + b" >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    for _, matrix, body, kids in forms:
        kx = b" ".join(b"/%s %d 0 R" % (n.encode(), names[n]) for n in kids)
        objs.append(b"<< /Type /XObject /Subtype /Form /BBox [-1000 -1000 1000 1000] /Matrix [" + matrix.encode() +
                    b"] /Resources << /Font << /F1 5 0 R >> /XObject << " + kx + b" >> >> /Length %d >>\nstream\n" % len(body)
                    + body + b"\nendstream")
    out = b"%PDF-1.4\n"
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return out


def _text(s, x, y, mode=0):
    return b"BT /F1 12 Tf %d Tr %d %d Td (%s) Tj ET\n" % (mode, x, y, s.encode())


def _full(path):
    doc = pdfium.PdfDocument(str(path))
    try:
        return [doc[i].get_textpage().get_text_range() for i in range(len(doc))]
    finally:
        doc.close()


VISIBLE = _text("VISIBLE", 10, 250)
CASES = {
    # ページの直下の re W n の外の文字
    "page_clip": (_pdf(VISIBLE + b"q 0 0 300 100 re W n " + _text("INCLIP", 10, 50) + _text("HIDDEN", 10, 200) + b"Q\n"),
                  ["VISIBLE", "INCLIP"], ["HIDDEN"]),
    # Form XObject の外（ページ）のクリップで切り抜いた、Form の中の文字
    "form_clip": (_pdf(VISIBLE + b"q 0 0 300 100 re W n /X1 Do Q\n",
                       [("X1", "1 0 0 1 0 0", _text("INFORM", 10, 50) + _text("HIDDEN", 10, 200), ())]),
                  ["VISIBLE", "INFORM"], ["HIDDEN"]),
    # 行列（拡大・平行移動）付きの Form の中の、ページのクリップの外の文字
    "form_matrix": (_pdf(VISIBLE + b"q 0 0 300 100 re W n /X1 Do Q\n",
                         [("X1", "2 0 0 2 0 20", _text("INFORM", 10, 10) + _text("HIDDEN", 10, 100), ())]),
                    ["VISIBLE", "INFORM"], ["HIDDEN"]),
    # (a) Form の中の re W n、Form に拡大＋平行移動の行列（Form の中のクリップは Form の座標）
    "inner_clip_matrix": (_pdf(VISIBLE + b"/X1 Do\n",
                               [("X1", "2 0 0 2 0 20", b"q 0 0 150 40 re W n " + _text("INSIDE", 10, 10) + _text("OUTSIDE", 10, 60)
                                 + b"Q", ())]),
                          ["VISIBLE", "INSIDE"], ["OUTSIDE"]),
    # (b) 2 段の入れ子の Form（平行移動の中に拡大）。掛ける順を取り違えると、残す文字・除く文字が入れ替わる
    "nested": (_pdf(VISIBLE + b"/X1 Do\n",
                    [("X1", "1 0 0 1 0 50", b"/X2 Do", ("X2",)),
                     ("X2", "2 0 0 2 0 0", b"q 0 0 100 30 re W n " + _text("INSIDE", 5, 5) + _text("OUTSIDE", 5, 60) + b"Q", ())]),
               ["VISIBLE", "INSIDE"], ["OUTSIDE"]),
    # (b) 拡大の中に平行移動
    "nested2": (_pdf(VISIBLE + b"/X1 Do\n",
                     [("X1", "2 0 0 2 0 0", b"/X2 Do", ("X2",)),
                      ("X2", "1 0 0 1 0 50", b"q 0 0 100 30 re W n " + _text("INSIDE", 5, 5) + _text("OUTSIDE", 5, 60) + b"Q", ())]),
                ["VISIBLE", "INSIDE"], ["OUTSIDE"]),
    # (c) 90 度の回転
    "rotate": (_pdf(VISIBLE + b"/X1 Do\n",
                    [("X1", "0 1 -1 0 200 0", b"q 0 0 100 30 re W n " + _text("INSIDE", 5, 5) + _text("OUTSIDE", 5, 60) + b"Q", ())]),
               ["VISIBLE", "INSIDE"], ["OUTSIDE"]),
    # 字の一部（下側）がクリップの中に入る大きな字は、描かれているので残す（文字枠の中心はクリップの外。点検 review19 の 2 回目）
    "partly_inside": (_pdf(VISIBLE + b"q 0 0 300 108 re W n BT /F1 30 Tf 10 100 Td (BIGFONT) Tj ET " + _text("HIDDEN", 10, 200)
                           + b"Q\n"),
                      ["VISIBLE", "BIGFONT"], ["HIDDEN"]),
    # 外のクリップの中に、それより広い内のクリップを重ねた形（pdfium では共通部分。外接矩形の近似では残す向きになる）は、ここでは見ない
    # 描画モード 3（透明な文字。スキャンの上の文字の層など）は除かない
    "mode3": (_pdf(VISIBLE + _text("OCRTEXT", 10, 200, mode=3)), ["VISIBLE", "OCRTEXT"], []),
}


@pytest.mark.parametrize("name", list(CASES))
def test_extract_pages_drops_clipped_text(name, tmp_path):
    """クリップの外の文字を除き、中の文字は残す。行列付きの Form・入れ子・回転でも、残す文字と除く文字を取り違えない。
    hidden は除いた空白でない文字の数。"""
    data, kept, dropped = CASES[name]
    path = tmp_path / f"{name}.pdf"
    path.write_bytes(data)
    full = _full(path)[0]
    assert all(s in full for s in kept + dropped)       # 今までの抽出は、描かれない文字も返していた
    pages = extract_pages(path)
    assert isinstance(pages, PdfPages) and len(pages) == 1
    assert all(s in pages[0] for s in kept)
    assert not any(s in pages[0] for s in dropped)
    assert pages.hidden == sum(len(s) for s in dropped)


def test_extract_pages_unchanged_without_clip(tmp_path):
    """クリップのない PDF では、今までの get_text_range() と 1 バイトも違わない。hidden は 0。"""
    path = tmp_path / "noclip.pdf"
    path.write_bytes(_pdf(VISIBLE + _text("ALSOSEEN", 10, 200) + b"q 0 0 300 300 re W n " + _text("CLIPPED", 10, 100) + b"Q\n"))
    pages = extract_pages(path)
    assert list(pages) == _full(path) and pages.hidden == 0


def test_extract_pages_space_only_outside_clip(tmp_path):
    """クリップの外に空白の文字だけがあるページ: 空白は除く（ページの文字は変わる）が、hidden は空白でない文字だけを数えるので 0。"""
    path = tmp_path / "space.pdf"
    path.write_bytes(_pdf(VISIBLE + b"q 0 0 300 100 re W n " + _text("INCLIP", 10, 50) + _text(" ", 10, 200) + b"Q\n"))
    pages = extract_pages(path)
    assert "VISIBLE" in pages[0] and "INCLIP" in pages[0] and pages.hidden == 0


def test_compare_uses_visible_layer(tmp_path, journal):
    """照合: 描かれない層が docx と同じ英文で、見える層が違う語の PDF では、内容の違いが 1 つ出る（今までの抽出では、描かれない層と
    一致して違いが出なかった）。"""
    from jasme_jats.pdfmatch import compare
    from test_pdfmatch import guard_article, guard_pages
    text = "Owls call at night near the quiet river and we recorded their voices."
    pub = text.replace("quiet", "still")
    plan, src = guard_article(tmp_path, journal, [text])
    body = (b"q 0 0 300 240 re W n " + _text(pub[:36], 5, 200) + _text(pub[36:], 5, 185)
            + _text(text[:36], 5, 270) + _text(text[36:], 5, 255) + b"Q\n")
    path = tmp_path / "layers.pdf"
    path.write_bytes(_pdf(body))
    pages = extract_pages(path)
    assert pages.hidden == len(text.replace(" ", ""))

    def diffs(page):
        pc = compare(plan, guard_pages(*[x for x in page.splitlines() if x.strip()]))
        return [d for d in pc.diffs if d.src == src[text]]
    assert diffs(_full(path)[0]) == []
    got = diffs(pages[0])
    assert [(d.docx, d.pdf, d.level) for d in got] == [("quiet", "still", "content")]


@pytest.mark.parametrize("hidden", [0, 4261], ids=["none", "hidden"])
def test_report_hidden_chars(hidden, journal, meta, tmp_path, monkeypatch):
    """check_pdf は、描かれない文字の数（PdfPages.hidden）を PdfCheck.hidden_chars に入れ、レポートの 13.3 に 1 行出す（知らせには
    しない）。0 のときは出さない。"""
    from jasme_jats.report import actions
    from test_pdfmatch import (N10_TAIL, SMALL_FRONT, TALK, body_lines, chapters, convert_with_pages, n10_article,
                               n10_pages)
    text = "森の中ではふくろうが夜に鳴き，その声を記録した。"
    n10_article(tmp_path, journal, [("body", text), ("body", TALK)])
    pages = PdfPages(n10_pages([*SMALL_FRONT, *body_lines(text), *body_lines(TALK), *N10_TAIL]))
    pages.hidden = hidden
    res = convert_with_pages(tmp_path, monkeypatch, journal, meta, pages, "pdf", docx=tmp_path / "n10.docx")
    assert res.docx_fix.check.hidden_chars == hidden
    sec = chapters(res)[1].split("### 13.3")[1].split("### 13.4")[0]
    line = "- 出版版 PDF の、描かれない文字（図の枠の外に隠れた文字など）4,261 字は、照合に使っていません。"
    assert (line in sec) == bool(hidden)
    assert "描かれない" not in " ".join(a.text for a in actions(res))
