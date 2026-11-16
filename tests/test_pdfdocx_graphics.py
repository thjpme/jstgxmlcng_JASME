"""図形（画像・テキストボックス）のある段落の、出版版 PDF に合わせる表記の直し（C048）。

pdfdocx.paragraph_units は、図形 1 つにつき読み取り（docx_reader._graphic）と同じ数の画像のアトム（OBJ）を置く
（規則は ooxml.graphic_atoms で共有する）。そのため、図形のある段落でも段落の文字列を読み取りと同じに組み立てられ、
表記の違い (1) を直せる。内容はすべて架空。
"""
import zipfile
from pathlib import Path

import pytest

import make_fixtures as mf
from jasme_jats.ooxml import HiddenRule, parse_xml, preprocess, w
from jasme_jats.pdfdocx import OBJ, PARTS, _chains, _Complex, paragraph_units, raw_paragraph_ids
from test_pdfmatch import N10_TAIL, SMALL_FRONT, TALK, body_lines, convert_with_pages, load, n10_pages, texts

BODY = "森の中では夜に (架空の) 鳥が鳴き，その声を記録した。"
PUB = "森の中では夜に（架空の）鳥が鳴き，その声を記録した。"
FIXED = "森の中では夜に（架空の）鳥が鳴き，その声を記録した。"
GRAPHIC_TAGS = (w("drawing"), w("pict"), w("object"))
AC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}AlternateContent"


def _article(tmp_path, body):
    """「１．はじめに」の後ろに body（Builder -> 段落の XML の並び）がある小さな論文。"""
    def parts(b):
        return [mf.para(mf.S["sec1"], "１．はじめに"), *body(b), mf.para(mf.S["body"], TALK)]
    mf.make_article(tmp_path / "n10.docx", "ページ番号の判定の検証用文書", parts, refs=lambda b: [])
    return tmp_path / "n10.docx"


def _graphics(path) -> int:
    with zipfile.ZipFile(path) as z:
        root = parse_xml(z.read("word/document.xml"))
    return sum(1 for el in root.iter(*GRAPHIC_TAGS))


def _shape(b, shape):
    rid = b.add_image("fig.png", mf.png_bytes("Figure"))
    pic = mf.drawing(rid, 900000, 600000, 502).split("<wp:docPr")[1].split("/>", 1)[1].split("</wp:inline>")[0]
    return {"bare_anchor": lambda: mf.anchored_drawing(rid, 900000, 600000, 501),
            "ac_pic": lambda: mf.anchored(pic, "", 503, 900000, 600000),
            "ac_textbox": lambda: mf.textbox(mf.para(mf.S["body"], "図形の中の文字"), 504),
            "inline_pic": lambda: mf.drawing(rid, 900000, 600000, 505),
            "vml_pic": lambda: mf.vml_image(rid)}[shape]()


@pytest.mark.parametrize("shape", ["bare_anchor", "ac_pic", "ac_textbox", "inline_pic", "vml_pic"])
def test_route2_fixes_paragraph_with_graphic(shape, journal, meta, tmp_path, monkeypatch):
    """ランの直下の浮動の画像・mc:AlternateContent の中の浮動の画像・テキストボックスだけの mc:AlternateContent・行内の画像・
    VML の画像の段落でも、半角のかっこの全角化と、その隣の空白の削除が当たる。補った docx の図形の数は元の docx と同じ
    （図形の欠けは pdfdocx._verify の、OBJ を含む段落の文字列の比べと、補完の確かめの図形の並びの比べで止まる）。補完の確かめは合格。"""
    docx = _article(tmp_path, lambda b: [mf.para(mf.S["body"], BODY, _shape(b, shape))])
    extra = ["図形の中の文字"] if shape == "ac_textbox" else []
    pages = n10_pages([*SMALL_FRONT, *body_lines(PUB), *extra, *body_lines(TALK), *N10_TAIL])
    res = convert_with_pages(tmp_path, monkeypatch, journal, meta, pages, "pdf", docx=docx)
    assert res.fidelity.ok and res.fidelity.final_ok and res.supplement.ok
    fx = res.docx_fix
    assert not [f for f in fx.fixes if not f.applied and "組み立てられない" in (f.reason or "")]
    assert FIXED in texts(load(res))
    assert _graphics(fx.path) == _graphics(docx)


def test_route2_fix_touching_graphic_keeps_graphic(journal, meta, tmp_path, monkeypatch):
    """画像のすぐ隣のかっこの直しは当たり、画像は消えない（補った docx の図形の数は元の docx と同じ）。画像の単位（OBJ）には
    w:t がないので、画像の前の空白は「(」のすぐ隣とみなさず、消さない（docx の文字のまま）。不変性・最終・補完の確かめは合格。"""
    def body(b):
        rid = b.add_image("fig.png", mf.png_bytes("Figure"))
        return [mf.para(mf.S["body"], "森の中では夜に ", mf.drawing(rid, 900000, 600000, 701), "(架空の) 鳥が鳴き，その声を記録した。")]
    docx = _article(tmp_path, body)
    pages = n10_pages([*SMALL_FRONT, *body_lines(PUB), *body_lines(TALK), *N10_TAIL])
    res = convert_with_pages(tmp_path, monkeypatch, journal, meta, pages, "pdf", docx=docx)
    assert res.fidelity.ok and res.fidelity.final_ok and res.supplement.ok
    assert _graphics(res.docx_fix.path) == _graphics(docx) == 1
    assert "森の中では夜に （架空の）鳥が鳴き，その声を記録した。" in texts(load(res))


def _raw(tmp_path, *parts):
    """本文の段落（parts は段落の中身の XML）の、読み取りの前と同じ前処理をした w:p の並びと、隠し文字の規則。"""
    path = _article(tmp_path, lambda b: [mf.para(mf.S["body"], *p(b)) for p in parts])
    with zipfile.ZipFile(path) as z:
        root = parse_xml(z.read("word/document.xml"))
        rule = HiddenRule(preprocess(parse_xml(z.read("word/styles.xml"))))
    ps = [p for p in root.iter(w("p")) if "".join(t.text or "" for t in p.iter(w("t"))).startswith("鳥の")]
    return ps, rule


def _objs(p, rule):
    return sum(1 for c, _, _ in paragraph_units(p, rule) if c == OBJ)


def test_paragraph_units_graphic_atoms(tmp_path):
    """グループの中の画像 2 つは OBJ 2 つ。削除の変更履歴の中の図形・隠し文字のランの図形は OBJ 0（読み取りと同じ）。"""
    def group(b):
        r1 = b.add_image("a.png", mf.png_bytes("A"))
        r2 = b.add_image("b.png", mf.png_bytes("B"))
        return ["鳥の群れ", mf.pic_group([(r1, 600000, 400000), (r2, 600000, 400000)], 601)]

    def dele(b):
        return ["鳥の削除", mf.deleted(mf.drawing(b.add_image("c.png", mf.png_bytes("C")), 600000, 400000, 611))]

    def hidden(b):
        return ["鳥の隠し", mf.drawing(b.add_image("d.png", mf.png_bytes("D")), 600000, 400000, 621)
                .replace("<w:r>", "<w:r><w:rPr><w:vanish/></w:rPr>", 1)]
    ps, rule = _raw(tmp_path, group, dele, hidden)
    assert [_objs(p, rule) for p in ps] == [2, 0, 0]


def test_paragraph_units_ruby_is_complex(tmp_path):
    """ルビのある段落は今までどおり組み立てない（_Complex。write_fixed_docx が理由を付けて直さない）。"""
    ruby = ('<w:r><w:ruby><w:rubyPr><w:rubyAlign w:val="distributeSpace"/></w:rubyPr><w:rt><w:r><w:t>とり</w:t></w:r></w:rt>'
            '<w:rubyBase><w:r><w:t>鳥</w:t></w:r></w:rubyBase></w:ruby></w:r>')
    ps, rule = _raw(tmp_path, lambda b: ["鳥のルビ", ruby])
    with pytest.raises(_Complex):
        paragraph_units(ps[0], rule)


FIXTURES = sorted((Path(__file__).parent / "fixtures").glob("*.docx"))


@pytest.mark.parametrize("path", FIXTURES, ids=[p.stem for p in FIXTURES])
def test_paragraph_units_match_reader(path):
    """性質: テスト用の docx のすべての段落（ルビ・段落の直下の mc:AlternateContent のあるものを除く）で、paragraph_units の
    文字列が読み取りの段落の文字列（plain()）と同じ（図形のある段落も。C048）。"""
    from jasme_jats.docx_reader import read_docx
    from jasme_jats.pdfdocx import _all_paragraphs
    doc = read_docx(path)
    want = {p.src: p.plain() for p in _all_paragraphs(doc)}
    checked = graphic = 0
    with zipfile.ZipFile(path) as z:
        rule = (HiddenRule(preprocess(parse_xml(z.read("word/styles.xml")))) if "word/styles.xml" in z.namelist() else None)
        for part, prefix in PARTS.items():
            if part not in z.namelist():
                continue
            root = parse_xml(z.read(part))
            raw = raw_paragraph_ids(root, prefix)
            chains = _chains(root, prefix)
            later = {s for c in chains.values() for s in c[1:]}
            for src, p in raw.items():
                if src in later or src not in want:
                    continue
                try:
                    units = [u for s in chains.get(src, [src]) for u in paragraph_units(raw[s], rule)]
                except _Complex:
                    assert any(True for _ in p.iter(w("ruby"))) or any(ch.tag == AC for ch in p), src
                    continue
                assert "".join(c for c, _, _ in units) == want[src], src
                checked += 1
                graphic += any(True for _ in p.iter(*GRAPHIC_TAGS))
    assert checked
    if path.stem in ("sample_float", "sample_full"):
        assert graphic          # 図形のある段落も比べている


# ---------------------------------------------------------------------------- 補完の確かめの図形の比べ（点検 review19 の 3 回目の原則 1）
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"


def _edited(src, dst, edit):
    """補った docx src の本文（word/document.xml。前処理していない木）を edit(root) で変えた docx を dst に書く。"""
    from lxml import etree
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                root = parse_xml(data)
                edit(root)
                data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
            zout.writestr(item, data)
    return dst


def _top_graphics(root):
    """いちばん外側の図形（mc:AlternateContent はまるごと）。"""
    tags = (*GRAPHIC_TAGS, AC)
    return [el for el in root.iter(*tags) if not any(a.tag in tags for a in el.iterancestors())]


def _drop(root):
    g = _top_graphics(root)[0]
    g.getparent().remove(g)


def _dup(root):
    import copy
    g = _top_graphics(root)[0]
    g.addnext(copy.deepcopy(g))


def _supplement(original, fixed):
    from jasme_jats.fidelity import verify_supplement
    return verify_supplement(original, fixed, set(), {}, {})


@pytest.mark.parametrize("shape", ["bare_anchor", "ac_pic", "ac_textbox", "inline_pic", "vml_pic"])
def test_supplement_detects_lost_or_doubled_graphic(shape, journal, meta, tmp_path, monkeypatch):
    """補完の確かめ（fidelity.verify_supplement）は図形の並びも比べる: 図形のある段落を直した正しい補った docx は合格のまま、そこから
    図形を 1 つ消した形・2 つにした形は不合格（理由 GRAPHIC_WHY）。mc:AlternateContent の採らない側（Fallback）だけを消した形も
    不合格（前処理の前の木の比べ）。照合・直しの結果は渡さない。"""
    from jasme_jats.fidelity import GRAPHIC_WHY
    docx = _article(tmp_path, lambda b: [mf.para(mf.S["body"], BODY, _shape(b, shape))])
    extra = ["図形の中の文字"] if shape == "ac_textbox" else []
    pages = n10_pages([*SMALL_FRONT, *body_lines(PUB), *extra, *body_lines(TALK), *N10_TAIL])
    res = convert_with_pages(tmp_path, monkeypatch, journal, meta, pages, "pdf", docx=docx)
    fixed = res.docx_fix.path
    assert res.supplement.ok and _supplement(docx, fixed).ok
    for name, edit in (("drop", _drop), ("dup", _dup)):
        sup = _supplement(docx, _edited(fixed, tmp_path / f"{name}.docx", edit))
        assert not sup.ok and [p for p in sup.problems if p[3] == GRAPHIC_WHY], name
    if shape.startswith("ac_"):
        def drop_fallback(root):
            fb = next(root.iter(f"{MC}Fallback"))
            fb.getparent().remove(fb)
        sup = _supplement(docx, _edited(fixed, tmp_path / "fallback.docx", drop_fallback))
        assert not sup.ok and [p for p in sup.problems if p[3] == GRAPHIC_WHY]


def test_supplement_detects_swapped_or_moved_graphic(journal, meta, tmp_path, monkeypatch):
    """同じ段落の画像 2 つの順を入れ替えた形と、画像を隣の段落に移した形（部品全体の並びは同じ）は、補完の確かめで不合格。"""
    from jasme_jats.fidelity import GRAPHIC_WHY

    def body(b):
        r1 = b.add_image("a.png", mf.png_bytes("A"))
        r2 = b.add_image("b.png", mf.png_bytes("B"))
        return [mf.para(mf.S["body"], BODY, mf.drawing(r1, 900000, 600000, 801), mf.drawing(r2, 700000, 500000, 802)),
                mf.para(mf.S["body"], "鳥の声は短く，すぐに止んだ。")]
    docx = _article(tmp_path, body)
    pages = n10_pages([*SMALL_FRONT, *body_lines(PUB), *body_lines("鳥の声は短く，すぐに止んだ。"), *body_lines(TALK), *N10_TAIL])
    res = convert_with_pages(tmp_path, monkeypatch, journal, meta, pages, "pdf", docx=docx)
    fixed = res.docx_fix.path
    assert res.supplement.ok and _supplement(docx, fixed).ok

    def swap(root):
        a, b = [g.getparent() for g in _top_graphics(root)]       # 画像のラン
        a.addprevious(b)

    def move(root):
        run = _top_graphics(root)[1].getparent()
        p = run.getparent()
        nxt = p.getnext()
        nxt.append(run)
    for name, edit in (("swap", swap), ("move", move)):
        sup = _supplement(docx, _edited(fixed, tmp_path / f"{name}.docx", edit))
        assert not sup.ok and [p for p in sup.problems if p[3] == GRAPHIC_WHY], name
