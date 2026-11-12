"""結果を持たないフィールド（EQ の囲い文字など）の表示される文字が XML に出せないことの知らせ（C013。要確認 resultless_field）のテスト。

fldChar の begin → end の間に separate がない（Word の「囲い文字」機能の正規の形）EQ・SYMBOL・フォームのフィールドは、Word では
コードから文字を描いて表示するが、docx の文字（w:t）ではないので XML には出さない（読み取りと検証が同じ読み方をするので、不変性チェックは
合格する）。XML は変えず、要確認として 1 件にまとめて知らせる。表示のない種類（XE・TC など）や、結果のあるフィールド（PAGE・HYPERLINK）では
知らせない。docx は make_fixtures の部品で作る（内容は架空）。
"""
import make_fixtures as mf

from jasme_jats.docx_reader import read_docx
from jasme_jats.ooxml import resultless_field_kind
from jasme_jats.pipeline import Options, convert
from jasme_jats.report import NEEDS_ACTION, TO_CHECK, actions

S = mf.S


def fld(code, result=None):
    """フィールドのラン列。result が None なら separate も結果もない（結果のないフィールド）。"""
    instr = f'<w:r><w:instrText xml:space="preserve"> {code} </w:instrText></w:r>'
    if result is None:
        return '<w:r><w:fldChar w:fldCharType="begin"/></w:r>' + instr + '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    res = mf.run(result) if result else ""
    return ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>' + instr + '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            + res + '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


def article(path, parts, **kw):
    mf.make_article(path, "フィールドの検証用文書", lambda b: [mf.para(S["sec1"], "１．はじめに"), *parts(b)], **kw)


def run_convert(path, journal, meta, tmp_path):
    return convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))


def found(res):
    return [a for a in actions(res) if a.key == "resultless_field"]


def test_eq_without_result_is_reported(journal, meta, tmp_path):
    """EQ（separate なし）は要確認で 1 件、段落の ID・種類・段落の文字の抜粋（印つき）を知らせる。XML の文字は変わらず、不変性チェックは合格。"""
    path = tmp_path / "eq.docx"
    article(path, lambda b: [mf.para(S["body"], "矢印を書き，", fld(r"eq \o\ac(○,3)"), "と記した。"),
                             mf.para(S["body"], "普通の段落である。")])
    res = run_convert(path, journal, meta, tmp_path)
    src = next(s for s, p in res.plan.paras.items() if p.text_only().startswith("矢印を書き"))
    assert "矢印を書き，と記した。" in res.xml_path.read_text(encoding="utf-8")
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    a, = found(res)
    assert a.level == TO_CHECK
    assert [(f.src, f.kind) for f in res.resultless_fields] == [(src, "EQ")]
    assert src in a.top and "囲い文字" in a.top and "矢印を書き，［ここ］と記した" in a.top
    assert "打ち直" in a.top and "抜けたまま" in a.top
    assert not res.needs_action or all(x.level != NEEDS_ACTION for x in actions(res) if x.key == "resultless_field")


def test_several_in_one_paragraph_are_one_line(journal, meta, tmp_path):
    """同じ段落に複数あれば 1 行にまとめる（件数は全体で数える）。別の段落は別の行。"""
    path = tmp_path / "many.docx"
    article(path, lambda b: [mf.para(S["body"], "最初の", fld(r"EQ \o\ac(○,1)"), "と次の", fld(r"EQ \o\ac(○,2)"), "が並ぶ。"),
                             mf.para(S["body"], "別の段落の", fld("FORMCHECKBOX"), "である。")])
    res = run_convert(path, journal, meta, tmp_path)
    a, = found(res)
    assert len(res.resultless_fields) == 3 and "3 か所" in a.top
    lines = [x for x in a.top.splitlines() if x.startswith("> - ")]
    assert len(lines) == 2 and "2 か所" in lines[0] and "チェックボックス" in lines[1]
    assert "最初の［ここ］と次の" in lines[0] and "と次の［ここ］が並ぶ" in lines[0]


def test_display_less_and_resulted_fields_are_not_reported(journal, meta, tmp_path):
    """表示のない種類（XE・TC・SET など）と、結果のあるフィールド（PAGE・HYPERLINK・REF。結果が空でも）は知らせない。"""
    path = tmp_path / "quiet.docx"
    article(path, lambda b: [mf.para(S["body"], "索引", fld('XE "架空の語"'), "と", fld('TC "目次の項目"'), "と",
                                     fld("SET x 1"), "と", fld("ADDIN EN.CITE"), "と", fld("PRIVATE"), "と", fld("ASK a b"),
                                     "の文。"),
                             mf.para(S["body"], "ページ", fld("PAGE", "3"), "とリンク", fld('HYPERLINK "https://example.net/"', "先"),
                                     "と空の参照", fld("REF missing", ""), "と空の ", fld(" ", None), "の文。")])
    res = run_convert(path, journal, meta, tmp_path)
    assert res.resultless_fields == [] and found(res) == []
    assert res.fidelity.ok


def test_eq_with_empty_result_is_reported_but_eq_with_result_is_not(journal, meta, tmp_path):
    """separate があっても結果が空の EQ は知らせる。結果の文字があれば知らせない（結果は w:t として出力される）。"""
    path = tmp_path / "result.docx"
    article(path, lambda b: [mf.para(S["body"], "空の結果", fld(r"EQ \o\ac(○,4)", ""), "と、結果あり", fld(r"EQ \o\ac(○,5)", "⑤"),
                                     "の文。")])
    res = run_convert(path, journal, meta, tmp_path)
    assert [f.kind for f in res.resultless_fields] == ["EQ"]
    assert "空の結果［ここ］と、結果あり" in found(res)[0].top and "⑤" in res.xml_path.read_text(encoding="utf-8")


def test_table_cell_and_footnote_are_recorded(journal, meta, tmp_path):
    """表のセル・脚注の中の EQ も記録する（段落の読み取りの途中で外側の段落のフィールドの状態を退避する経路）。"""
    path = tmp_path / "nested.docx"
    cell_para = mf.para(S["body"], "セルの", fld(r"EQ \o\ac(○,7)"), "文字")
    eq8 = fld(r"EQ \o\ac(○,8)")
    fn = mf.footnote(5, mf.run(" 脚注の") + eq8 + mf.run("文字。"))
    article(path, lambda b: [mf.para(S["body"], "表の前の", fld(r"EQ \o\ac(○,9)"), "文", mf.footnote_ref(5), "。"),
                             mf.table([[mf.cell([cell_para]), mf.cell("隣")]])],
            footnotes=[fn])
    doc = read_docx(path)
    kinds = [(f.src[0], f.kind) for f in doc.resultless_fields]
    assert sorted(kinds) == [("d", "EQ"), ("d", "EQ"), ("f", "EQ")]
    res = run_convert(path, journal, meta, tmp_path)
    assert len(res.resultless_fields) == 3 and len(found(res)) == 1 and res.fidelity.ok


def test_fldsimple_is_the_same(journal, meta, tmp_path):
    """w:fldSimple の形も同じ扱い（結果の子がない EQ は記録、結果のある PAGE は記録しない）。"""
    path = tmp_path / "simple.docx"
    article(path, lambda b: [mf.para(S["body"], "単純な", '<w:fldSimple w:instr=" EQ \\o\\ac(○,1) "/>', "と",
                                     f'<w:fldSimple w:instr=" PAGE ">{mf.run("2")}</w:fldSimple>', "の文。")])
    res = run_convert(path, journal, meta, tmp_path)
    assert [f.kind for f in res.resultless_fields] == ["EQ"]
    assert "単純な［ここ］と2の文" in found(res)[0].top


def test_deleted_and_hidden_fields_are_not_reported(journal, meta, tmp_path):
    """変更履歴で削除された・隠し文字のフィールドは、Word で表示されないので知らせない。"""
    path = tmp_path / "gone.docx"
    gone = fld(r"EQ \o\ac(○,1)").replace("<w:r>", "<w:r><w:rPr><w:vanish/></w:rPr>")
    eq2 = fld(r"EQ \o\ac(○,2)")
    deleted = f'<w:del w:id="1" w:author="x">{eq2}</w:del>'
    article(path, lambda b: [mf.para(S["body"], "隠し", gone, "と削除", deleted, "の文。")])
    res = run_convert(path, journal, meta, tmp_path)
    assert res.resultless_fields == [] and found(res) == []


def test_chapter6_lists_all(journal, meta, tmp_path):
    """レポートの 6 章に全件（種類・フィールドコードの抜粋つき）を載せる。"""
    path = tmp_path / "chapter.docx"
    article(path, lambda b: [mf.para(S["body"], "前", fld(r"eq \o\ac(○,3+i)"), "後。")])
    res = run_convert(path, journal, meta, tmp_path)
    ch6 = res.report_path.read_text(encoding="utf-8").split("## 6.")[1].split("## 7.")[0]
    assert "Word では表示されるが、XML に出せない文字" in ch6 and "Word のフィールドの中身" in ch6
    assert r"eq \o\ac(○,3+i)" in ch6 and "前［ここ］後" in ch6
    assert "結果を持たないまま" not in ch6                # 利用者向けの言い方にする


def test_mark_is_explained_before_the_lines_and_lines_are_capped(journal, meta, tmp_path):
    """位置の印（［ここ］）は、それを使う行より前に説明する。段落ごとの行は先頭の数件だけ並べ、ほかは「ほか N 段落」にする
    （全件は 6 章）。文が、ルート1・ルート2 のどちらでも誤りにならない（XML にその文字があるかを確かめてもらう）。"""
    from jasme_jats.report import RESULTLESS_LINES, RESULTLESS_MARK
    n = RESULTLESS_LINES + 3
    path = tmp_path / "cap.docx"
    article(path, lambda b: [mf.para(S["body"], f"段落{k}の", fld(rf"EQ \o\ac(○,{k})"), "の文。") for k in range(n)])
    res = run_convert(path, journal, meta, tmp_path)
    a, = found(res)
    for text in (a.top, a.box_detail, a.cli):
        assert text.index("は、文字のある位置の印です") < text.index(RESULTLESS_MARK + "の文")
        assert text.count("段落0の" + RESULTLESS_MARK) == 1 and f"段落{RESULTLESS_LINES - 1}の" in text
        assert f"段落{RESULTLESS_LINES}の" not in text and "ほか 3 段落" in text
        assert "確かめ" in text and "XML のその位置" in text
    ch6 = res.report_path.read_text(encoding="utf-8").split("## 6.")[1].split("## 7.")[0]
    assert f"段落{n - 1}の" in ch6                                # 6 章は全件


def test_kind_rule():
    """フィールドの種類の規則（ooxml.resultless_field_kind。読み取りの記録の根拠）。"""
    assert resultless_field_kind(r" eq \o\ac(○,3) ") == "EQ"
    assert resultless_field_kind("SYMBOL 65 \\f Wingdings") == "SYMBOL"
    assert resultless_field_kind(" FORMCHECKBOX ") == "FORMCHECKBOX"
    for code in ('XE "a"', 'TC "a"', 'TA \\l "a"', "RD x.docx", "SET a b", "ASK a b", "ADDIN X", "PRIVATE", "", "  ", "PAGE", "REF a"):
        assert resultless_field_kind(code) is None, code
