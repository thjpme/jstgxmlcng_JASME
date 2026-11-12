"""記号フォント（Symbol・Wingdings 系）の私用領域の符号の扱い（C011。要確認 symbol_replaced・要対応 pua_left）のテスト。

箇条書きの記号（Word が付ける生成文字）と、本文の記号（w:sym と、記号フォントのランの w:t の私用領域の文字。docx の文字の読み方の規則）を、
フォントごとの表（ooxml.SYMBOL_TABLES）で普通の Unicode の文字にして出力する。置き換えたことは要確認で知らせ（1 件にまとめる）、
表にない私用領域の文字が最終の XML に残ったら要対応で知らせる（pipeline.pua_chars）。docx は make_fixtures の部品で作る（内容は架空）。
読み取り・検証・ルート2 は同じ規則（ooxml.w_t_text・sym_char）を共有するので、規則そのものの誤りは不変性チェックでは見つからない。
ここ（単体テスト）で表と規則を守る。
"""
import re
import zipfile

import make_fixtures as mf
import pytest
from conftest import META_EXAMPLE
from lxml import etree
from test_pdfmatch import SMALL_FRONT, TALK, N10_TAIL, body_lines, convert_with_pages, n10_pages

from jasme_jats import ooxml
from jasme_jats.cli import main as cli_main
from jasme_jats.docx_reader import read_docx
from jasme_jats.numbering import bullet_text
from jasme_jats.ooxml import SYMBOL_TABLES, canonical_text, is_pua, map_symbol_text, symbol_char, w_t_text
from jasme_jats.pipeline import Options, convert
from jasme_jats.report import NEEDS_ACTION, TO_CHECK, actions

S = mf.S
W = mf.W
PUA_RE = re.compile("[-]")


def set_bullet(path, char, font):
    """箇条書き（numId=6）の 1 段目の記号を char、書式のフォントを font にする（font が None なら rFonts を消す）。"""
    tmp = path.with_suffix(".tmp.docx")
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/numbering.xml":
                nx = data.decode("utf-8")
                a = nx.index('<w:abstractNum w:abstractNumId="7"')
                b = nx.index('<w:lvl w:ilvl="1">', a)
                seg = nx[a:b].replace('<w:lvlText w:val="•"/>', f'<w:lvlText w:val="{char}"/>')
                fonts = f'<w:rFonts w:ascii="{font}" w:hAnsi="{font}"/>' if font else ""
                seg = re.sub(r"<w:rFonts [^>]*/>", fonts, seg)
                data = (nx[:a] + seg + nx[b:]).encode("utf-8")
            zout.writestr(item, data)
    tmp.replace(path)


def bullet_article(path, char, font, n=2):
    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "記号の検証用の本文である。"),
                *[mf.list_item(S["body"], f"箇条の項目{k}") for k in range(n)]]
    mf.make_article(path, "記号の検証用文書", parts)
    set_bullet(path, char, font)


def sym(font, code):
    return f'<w:r><w:sym w:font="{font}" w:char="{code}"/></w:r>'


def font_run(font, text):
    return f'<w:r><w:rPr><w:rFonts w:ascii="{font}" w:hAnsi="{font}"/></w:rPr><w:t>{text}</w:t></w:r>'


def run_convert(path, journal, meta, tmp_path, **kw):
    return convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False, **kw))


def keys(res):
    return [a.key for a in actions(res)]


def xml_of(res):
    return res.xml_path.read_text(encoding="utf-8")


def chapter8(res):
    return res.report_path.read_text(encoding="utf-8").split("## 8.")[1].split("## 9.")[0]


# ---------------------------------------------------------------------------- 表と規則（単体）
def test_tables_are_single_characters_in_the_private_use_area():
    """表のキーは下位 1 バイト、値は 1 文字（1 文字が 1 文字になるので、文字の位置が変わらない）で、私用領域ではない。"""
    for font, table in SYMBOL_TABLES.items():
        assert all(0x20 <= k <= 0xFF for k in table), font
        assert all(len(v) == 1 and not is_pua(v) for v in table.values()), font


def test_symbol_char_is_per_font():
    """同じ符号でもフォントごとに違う記号。記号フォントでないフォント・表にない符号は None（そのまま）。"""
    assert symbol_char("Wingdings", 0xF09F) == "•" and symbol_char("wingdings", 0xF0FC) == "✓"
    assert symbol_char("Wingdings 2", 0xF098) == "●" and symbol_char("Wingdings 3", 0xF075) == "▶"
    assert symbol_char("Symbol", 0xF0AE) == "→" and symbol_char("Symbol", 0xF031) == "1"
    assert symbol_char("Wingdings", 0xF0AE) is None            # Wingdings の F0AE は表にない（Symbol の「→」にしない）
    assert symbol_char("Wingdings 2", 0xF09F) is None           # Wingdings の「•」を Wingdings 2 に使わない
    assert symbol_char("Arial", 0xF09F) is None and symbol_char("", 0xF09F) is None
    assert symbol_char("Wingdings", 0xF0B1) is None
    assert symbol_char("Wingdings", 0x9F) == "•"                # w:char="009F" も下位 1 バイトで読む（Symbol と同じ）


def test_map_symbol_text_only_private_use():
    assert map_symbol_text("Wingdings", "ab") == ("a✓b", [("", "✓")])
    assert map_symbol_text("Arial", "") == ("", [])
    assert map_symbol_text("Symbol", "abc") == ("abc", [])      # Symbol フォントの ASCII は私用領域ではないので、そのまま（別の問題）


def test_bullet_text_uses_the_level_font_and_keeps_legacy_for_other_fonts():
    """箇条書きの記号: 記号フォントはそのフォントの表。記号フォントでない・指定がないときは、古い 6 つの対応（回帰）。"""
    assert bullet_text("Wingdings", "") == ("•", [("Wingdings", "", "•")])
    assert bullet_text("Wingdings", "")[0] == "\u2219"          # 公式は U+2219 BULLET OPERATOR（中黒 U+00B7 ではない）
    assert bullet_text("Wingdings", "")[0] == ""          # 公式は U+2BCE（✧ U+2727 とは別の文字）。表から外した
    assert bullet_text("Wingdings", "")[0] == "■"
    assert bullet_text("Symbol", "")[0] == "•" and bullet_text("Wingdings", "")[0] == "➢"
    # 古い対応は、フォントが記号フォントでないときだけ（Symbol の F0A7 は ♣、Wingdings の F0A7 は ▪）
    assert bullet_text("", "")[0] == "•" and bullet_text("Arial", "")[0] == "▪"
    assert bullet_text("Symbol", "")[0] == "♣" and bullet_text("Wingdings", "")[0] == "▪"
    assert bullet_text("Arial", "•") == ("•", []) and bullet_text("Arial", "o") == ("o", [])
    # 表にない符号は私用領域のまま（守りが知らせる）
    assert bullet_text("Wingdings", "")[0] == ""


def test_w_t_text_reads_the_run_font():
    """記号フォントのランの w:t の私用領域の文字だけを Unicode にする。読み取り・検証・ルート2 が同じ（w_t_text）。"""
    def p(xml):
        return etree.fromstring(f'<w:p xmlns:w="{W}">{xml}</w:p>')
    wing = p(font_run("Wingdings", "あい"))
    assert canonical_text(wing) == "あ✓い"
    assert w_t_text(next(wing.iter(f"{{{W}}}t"))) == ("あ✓い", [("", "✓")])
    # フォントの指定がない・記号フォントでないランは、そのまま（守りが知らせる）
    assert canonical_text(p("<w:r><w:t></w:t></w:r>")) == ""
    assert canonical_text(p(font_run("Arial", ""))) == ""
    assert canonical_text(p(sym("Wingdings", "F0FC") + sym("Wingdings", "F0B1"))) == "✓"
    assert canonical_text(p(sym("Symbol", "F0DE") + sym("Symbol", "F031"))) == "⇒1"


# ---------------------------------------------------------------------------- (a) 箇条書きの記号を置き換える
@pytest.mark.parametrize("code,expect", [("", "•"), ("", "○"), ("", "■")])
def test_wingdings_bullets_become_unicode(code, expect, journal, meta, tmp_path):
    path = tmp_path / "b.docx"
    bullet_article(path, code, "Wingdings")
    res = run_convert(path, journal, meta, tmp_path)
    xml = xml_of(res)
    assert not PUA_RE.search(xml) and xml.count(f"<label>{expect}</label>") == 2
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and not res.needs_action
    assert res.pua_chars == []
    assert [(s.kind, s.font, s.code, s.to) for s in res.symbols_replaced] == [("bullet", "Wingdings", ord(code), expect)] * 2
    acts = [a for a in actions(res) if a.key == "symbol_replaced"]
    assert len(acts) == 1 and acts[0].level == TO_CHECK                # 件数でまとめた 1 件
    assert f"箇条書きの記号（Wingdings）を「{expect}」に置き換えました（2 か所）" in acts[0].top
    assert "Word の表示と同じか" in acts[0].top and "PDF" not in acts[0].top            # PDF を指定していない変換では、PDF と比べようがない
    assert "新しい行頭文字の定義" in acts[0].top and "打ち直して" not in acts[0].top and "step:" in acts[0].box_detail   # 箇条書きの記号は打ち直せない
    assert "U+" not in acts[0].top and "symbol_replaced" not in acts[0].top           # 利用者向けの文にコードの名前を書かない
    ch8 = chapter8(res)
    assert "対応する普通の文字に置き換えた記号（全件" in ch8 and f"U+{ord(code):04X}" in ch8 and expect in ch8


def test_unknown_bullets_are_grouped_with_a_few_paragraphs(journal, meta, tmp_path):
    """表にない箇条書きの記号が多くても、要対応は 1 行（フォント・符号・種類ごとの件数）で、段落は先頭の数件だけ。全件は 8 章の表。"""
    from jasme_jats.report import PUA_SAMPLES
    n = PUA_SAMPLES + 4
    path = tmp_path / "many.docx"
    bullet_article(path, "\uf0b1", "Wingdings", n=n)
    res = run_convert(path, journal, meta, tmp_path)
    assert len(res.pua_chars) == n
    a, = [a for a in actions(res) if a.key == "pua_left"]
    for text in (a.top, a.box_detail, a.cli):
        assert text.count("U+F0B1") == 1 and f"{n} か所残っています" in text and "ほか 4 段落" in text
        assert "箇条の項目0" in text and f"箇条の項目{PUA_SAMPLES}" not in text
    assert chapter8(res).count("U+F0B1") == n                 # 8 章は全件


def test_symbol_check_mentions_pdf_only_when_given(journal, meta, tmp_path):
    """記号の確かめの相手は、PDF を指定した変換では出版版 PDF の記号、指定していない変換では Word の表示。"""
    import types
    from jasme_jats.model import SymbolReplaced
    from jasme_jats.report import _symbol_action
    syms = [SymbolReplaced("d1", "text", "Wingdings", 0xF0FC, "\u2713")]
    for has_pdf, want, not_want in ((True, "出版版 PDF の記号と同じか", "Word の表示と同じか"),
                                    (False, "Word の表示と同じか", "出版版 PDF")):
        act = _symbol_action(types.SimpleNamespace(has_pdf=has_pdf, symbols_replaced=syms, plan=None))
        assert want in act.top and want in act.cli and not_want not in act.top


def test_symbol_added_to_the_table_is_not_reported_as_unchanged(journal, meta, tmp_path):
    """Symbol の w:sym のうち、0.31.1 までも同じ文字にしていたもの（矢印など）は「従来どおり」、後から表に足したもの（数字・€・®©™）は
    要確認で知らせる。"""
    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "矢印", sym("Symbol", "F0AE"), "と数字", sym("Symbol", "F031"), "。")]
    path = tmp_path / "added.docx"
    mf.make_article(path, "記号の検証用文書", parts)
    res = run_convert(path, journal, meta, tmp_path)
    assert [(s.to, s.known) for s in res.symbols_replaced] == [("\u2192", True), ("1", False)]
    top = next(a for a in actions(res) if a.key == "symbol_replaced").top
    assert "「1」" in top and "「\u2192」" not in top
    assert chapter8(res).count("従来どおり") >= 2 and "要確認" in chapter8(res)


def test_bullets_regression_symbol_and_other_fonts(journal, meta, tmp_path):
    """既存の箇条書き（Symbol の F0B7・Wingdings の F0D8・フォントなしの F0B7）は、これまでと同じ文字になる。"""
    for k, (char, font, expect) in enumerate([("", "Symbol", "•"), ("", "Wingdings", "➢"), ("", None, "•"),
                                              ("", "Arial", "●")]):
        path = tmp_path / f"r{k}.docx"
        bullet_article(path, char, font, n=1)
        res = run_convert(path, journal, meta, tmp_path / str(k))
        assert f"<label>{expect}</label>" in xml_of(res) and not PUA_RE.search(xml_of(res)) and res.pua_chars == []
        # 0.31.1 までも同じ文字にしていた置き換え（known）は、要確認で知らせず、8 章の全件の表にだけ載せる
        assert all(s.known for s in res.symbols_replaced)
        assert "symbol_replaced" not in keys(res) and not res.needs_action
        assert ("従来どおり" in chapter8(res)) == bool(res.symbols_replaced)


def test_plain_bullets_are_not_reported(journal, meta, tmp_path):
    """私用領域でない記号（テンプレートの「•」）は、置き換えも知らせもない。"""
    path = tmp_path / "plain.docx"
    bullet_article(path, "•", "Arial")
    res = run_convert(path, journal, meta, tmp_path)
    assert res.symbols_replaced == [] and res.pua_chars == []
    assert not {"symbol_replaced", "pua_left"} & set(keys(res))


# ---------------------------------------------------------------------------- (b) 表にない記号は要対応
def test_unknown_private_use_bullet_is_needs_action(journal, meta, tmp_path, capsys):
    path = tmp_path / "unk.docx"
    bullet_article(path, "", "Wingdings")
    res = run_convert(path, journal, meta, tmp_path)
    assert res.fidelity.ok and res.fidelity.final_ok            # 不変性チェックは通る（番号は docx の文字ではない）
    assert PUA_RE.search(xml_of(res)) and res.needs_action
    src = next(s for s, p in res.plan.paras.items() if p.plain() == "箇条の項目0")
    assert [(pc.src, pc.code, pc.generated, pc.font, pc.where, pc.count) for pc in res.pua_chars] == [
        (src, 0xF0B1, True, "Wingdings", "label", 1), (next(s for s, p in res.plan.paras.items() if p.plain() == "箇条の項目1"),
                                                      0xF0B1, True, "Wingdings", "label", 1)]
    acts = [a for a in actions(res) if a.key == "pua_left"]
    assert len(acts) == 1 and acts[0].level == NEEDS_ACTION
    for text in (acts[0].top, acts[0].box_detail, acts[0].cli):
        assert src in text and "U+F0B1" in text and "Wingdings" in text and "箇条書きの記号" in text and "2 か所" in text
        assert "生成文字" not in text and "XML の label" not in text
    assert "新しい行頭文字の定義" in acts[0].top and "打ち直して" not in acts[0].top and "symbol_replaced" not in keys(res)
    assert "U+F0B1" in chapter8(res) and "XML に残った私用領域" in chapter8(res)
    assert cli_main([str(path), "--meta", str(META_EXAMPLE), "--out", str(tmp_path / "cli"), "--no-metafile-conversion"]) == 1
    assert "U+F0B1" in capsys.readouterr().err


# ---------------------------------------------------------------------------- (c) 本文の記号（w:sym・w:t）
def test_body_symbols(journal, meta, tmp_path):
    """w:sym と記号フォントのランの w:t は表で置き換えて（要確認 1 件）、表にないもの・記号フォントでないランの私用領域の文字は
    要対応（docx の文字として）。不変性チェックは合格のまま。"""
    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"),
                mf.para(S["body"], "チェック", sym("Wingdings", "F0FC"), "と矢印", sym("Symbol", "F0AE"), "と記号の文字",
                        font_run("Wingdings", ""), "と未知の記号", sym("Symbol", "F0C1"), "と", font_run("Arial", ""),
                        "と", sym("Wingdings", "F0B1"), "。")]
    path = tmp_path / "body.docx"
    mf.make_article(path, "記号の検証用文書", parts)
    res = run_convert(path, journal, meta, tmp_path)
    src = next(s for s, p in res.plan.paras.items() if p.plain().startswith("チェック"))
    assert "チェック✓と矢印→と記号の文字☑と未知の記号とと。" in xml_of(res)
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    assert [(s.kind, s.font, s.to, s.known) for s in res.symbols_replaced] == [
        ("sym", "Wingdings", "✓", False), ("sym", "Symbol", "→", True), ("text", "Wingdings", "☑", False)]
    assert {(pc.code, pc.generated, pc.font) for pc in res.pua_chars} == {(0xF0C1, False, "Symbol"), (0xF0FC, False, "Arial"),
                                                                          (0xF0B1, False, "Wingdings")}
    assert all(pc.src == src and pc.where == "p" for pc in res.pua_chars)
    k = keys(res)
    assert k.count("symbol_replaced") == 1 and k.count("pua_left") == 1 and res.needs_action
    top = next(a for a in actions(res) if a.key == "symbol_replaced").top
    assert "本文の記号（Wingdings）を「✓」に置き換えました（1 か所。段落 " + src + "（" in top and "「チェック✓と矢印→と記号" in top
    assert "打ち直してください" in top and "新しい行頭文字の定義" not in top           # 本文の記号だけなら、打ち直しの案内だけ
    assert "「→」" not in top and "従来どおり" in chapter8(res)         # w:sym の Symbol は 0.31.1 からの置き換え。冒頭では知らせない
    pua = next(a for a in actions(res) if a.key == "pua_left")
    assert "本文の文字" in pua.top and "Arial" in pua.top and "打ち直してください" in pua.top and "新しい行頭文字の定義" not in pua.top
    assert "docx の文字" not in pua.top and "生成文字" not in pua.top


def test_replaced_symbols_are_counted_only_when_output(journal, meta, tmp_path):
    """箇条書きの記号の置き換えは、生成文字の中に置き換えた文字があるときだけ数える（ルート2 で番号を PDF の字形に合わせたら除く）。"""
    from jasme_jats.pipeline import symbols_replaced
    from jasme_jats.model import SymbolReplaced
    from jasme_jats.tracking import GEN, SPAN
    import types
    root = etree.Element("article")
    g = etree.SubElement(root, GEN, kind="autonum", src="d1")
    g.text = "・ "
    etree.SubElement(root, SPAN, src="d1", seq="0").text = "本文"
    doc = types.SimpleNamespace(symbols=[SymbolReplaced("d1", "bullet", "Wingdings", 0xF09F, "•"),
                                         SymbolReplaced("d1", "text", "Symbol", 0xF0AE, "→"),
                                         SymbolReplaced("d2", "text", "Symbol", 0xF0AE, "→"),
                                         SymbolReplaced("d1", "text", "Symbol", 0xF0B1, "")])
    got = symbols_replaced(None, root, doc)
    assert [(s.src, s.kind) for s in got] == [("d1", "text")]       # 番号は「・」（「•」ではない）、d2 は出力していない、to のないものは除く


# ---------------------------------------------------------------------------- 読み取り・検証・ルート2 が同じ読み方をする
def test_reader_validator_and_supplement_share_the_rule(journal, meta, tmp_path, monkeypatch):
    """読み取りの段落の文字と、検証の文字（canonical_text）と、ルート2 の直す単位の文字が同じ（記号の置き換えを含む）。"""
    from jasme_jats import pdfdocx
    from jasme_jats.fidelity import source_texts
    path = tmp_path / "share.docx"
    mf.make_article(path, "記号の検証用文書",
                    lambda b: [mf.para(S["sec1"], "１．はじめに"),
                               mf.para(S["body"], "矢印", sym("Wingdings", "F0E0"), "と", font_run("Wingdings", ""), "の文字。")])
    doc = read_docx(path)
    para = next(p for p in doc.all_paragraphs() if p.plain().startswith("矢印"))
    assert para.plain() == "矢印→と✓の文字。"
    assert source_texts(path)[para.src] == para.plain()
    with zipfile.ZipFile(path) as z:
        pkg_root = ooxml.preprocess(ooxml.parse_xml(z.read("word/document.xml")))
    p = next(q for q in pkg_root.iter(f"{{{W}}}p") if "矢印" in "".join(t.text or "" for t in q.iter(f"{{{W}}}t")))
    units = pdfdocx.paragraph_units(p, ooxml.NO_RULE)
    assert "".join(u[0] for u in units) == para.plain()


def test_symbol_font_run_with_alternate_content_is_read_the_same(tmp_path):
    """記号フォントのランの中の mc:AlternateContent（記号の挿入が書く形）の Fallback の w:t も、読み取り・検証・ルート2 が
    同じに置き換える（ルート2 の pdfdocx.paragraph_units は、前処理をしていない木も読むので、ランのフォントを渡している）。"""
    from jasme_jats import pdfdocx
    from jasme_jats.fidelity import source_texts
    ac = ('<w:r><w:rPr><w:rFonts w:ascii="Wingdings" w:hAnsi="Wingdings"/></w:rPr><mc:AlternateContent>'
          '<mc:Choice Requires="w16se" xmlns:w16se="http://schemas.microsoft.com/office/word/2015/wordml/symex">'
          '<w16se:symEx w16se:font="Wingdings" w16se:char="F0FC"/></mc:Choice><mc:Fallback><w:t>\uf0fc</w:t></mc:Fallback>'
          '</mc:AlternateContent></w:r>')
    path = tmp_path / "ac.docx"
    mf.make_article(path, "記号の検証用文書",
                    lambda b: [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "確認", ac, "の記号。")])
    doc = read_docx(path)
    para = next(p for p in doc.all_paragraphs() if p.plain().startswith("確認"))
    assert para.plain() == "確認\u2713の記号。"
    assert source_texts(path)[para.src] == para.plain()
    with zipfile.ZipFile(path) as z:
        raw = ooxml.parse_xml(z.read("word/document.xml"))
    p = next(q for q in raw.iter(f"{{{W}}}p") if "確認" in "".join(t.text or "" for t in q.iter(f"{{{W}}}t")))
    assert "".join(u[0] for u in pdfdocx.paragraph_units(p, ooxml.NO_RULE)) == para.plain()       # 前処理をしていない木でも同じ


# ---------------------------------------------------------------------------- (e) ルート2
def test_route2_bullet_wingdings_f09f_with_pdf_dot(journal, meta, tmp_path, monkeypatch):
    """ルート2 で、Wingdings の F09F（「•」にする）の箇条書きと PDF の「・」は、要対応にならない（Unicode にした後の照合）。
    XML に私用領域の文字は残らない。"""
    pytest.importorskip("pypdfium2")
    items = ["一つ目の項目として，架空の授業の記録を集めた。", "二つ目の項目として，記録を観点ごとに整理した。"]

    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], TALK), *[mf.list_item(S["body"], t) for t in items]]
    path = tmp_path / "n10.docx"
    mf.make_article(path, "ページ番号の判定の検証用文書", parts)
    set_bullet(path, "", "Wingdings")
    pages = n10_pages([*SMALL_FRONT, *body_lines(TALK), *[f"・{t}" for t in items], *N10_TAIL])
    res = convert_with_pages(tmp_path, monkeypatch, journal, meta, pages, "pdf", docx=path)
    assert not PUA_RE.search(xml_of(res)) and res.pua_chars == []
    assert not res.needs_action and res.fidelity.ok and (res.supplement is None or res.supplement.ok)
    assert "pua_left" not in keys(res)
