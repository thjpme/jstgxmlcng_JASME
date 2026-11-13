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
    return convert(path, meta, journal, Options(out_dir=tmp_path / "out"))


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


# ---- 任意の置き場所（修正計画 W1 の手順 15。画像で補えるようにする）

def optional(res):
    return [i for i in res.images if i.kind == "optional"]


def test_optional_slot_is_not_a_step_and_xml_is_unchanged(journal, meta, tmp_path):
    """入れないと、XML は今と同じ（<inline-graphic> なし）で、手順 images に数えない。置き場所は状態 unused で一覧にだけ出る。"""
    path = tmp_path / "opt.docx"
    article(path, lambda b: [mf.para(S["body"], "矢印を書き，", fld(r"eq \o\ac(○,3)"), "と記した。")])
    res = run_convert(path, journal, meta, tmp_path)
    xml = res.xml_path.read_text(encoding="utf-8")
    assert "inline-graphic" not in xml and "矢印を書き，と記した。" in xml
    im, = optional(res)
    assert im.status == "unused" and im.key.startswith("opt") and len(im.key) == 9
    assert "images" not in [a.key for a in actions(res)]
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and not res.lost_images
    from jasme_jats.report import images_progress
    assert images_progress(res) == (0, 0)
    a, = found(res)
    assert im.key in a.top and "画像で補うこともできます" in a.top and "入れなくてもかまいません" in a.top


def test_optional_image_is_placed_at_the_field_position(journal, meta, tmp_path):
    """入れると、その位置に <inline-graphic> が入る。文字は不変、DTD 合格、ZIP にも入る。"""
    from conftest import key_png
    from jasme_jats.pipeline import add_images
    path = tmp_path / "opt2.docx"
    article(path, lambda b: [mf.para(S["body"], "矢印を書き，", fld(r"eq \o\ac(○,3)"), "と記した。")])
    res = run_convert(path, journal, meta, tmp_path)
    key = optional(res)[0].key
    assert add_images(res, {key: ("a.png", key_png(1))}) == [key]
    xml = res.xml_path.read_text(encoding="utf-8")
    aid = meta.article_id(journal)
    assert f'矢印を書き，<inline-graphic xlink:href="{aid}_{key}.png"/>と記した。' in xml
    assert optional(res)[0].status == "user"
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and not res.image_problems and not res.zip_issues
    assert not res.lost_images
    import zipfile
    assert f"Graphics/{aid}_{key}.png" in "".join(zipfile.ZipFile(res.zip_path).namelist())


def test_optional_at_start_end_and_same_code(journal, meta, tmp_path):
    """段落の先頭・終わりの位置も書ける。同じコードが 2 か所なら 2 つ目の幹に _2 が付く。"""
    from conftest import key_png
    from jasme_jats.pipeline import add_images
    path = tmp_path / "opt3.docx"
    article(path, lambda b: [mf.para(S["body"], fld(r"EQ \o\ac(○,1)"), "中", fld(r"EQ \o\ac(○,1)"), "身", fld(r"EQ \o\ac(○,2)"))])
    res = run_convert(path, journal, meta, tmp_path)
    keys = [i.key for i in optional(res)]
    assert len(keys) == 3 and keys[1] == keys[0] + "_2" and keys[2] != keys[0]
    add_images(res, {k: ("x.png", key_png(n)) for n, k in enumerate(keys)})
    xml = res.xml_path.read_text(encoding="utf-8")
    aid = meta.article_id(journal)
    h = [f'<inline-graphic xlink:href="{aid}_{k}.png"/>' for k in keys]
    assert h[0] + "中" + h[1] + "身" + h[2] in xml
    assert res.fidelity.final_ok and res.dtd_valid and not res.image_problems


def test_optional_inside_bold_and_cell(journal, meta, tmp_path):
    """太字の途中・表のセルの中のフィールドも、その位置に書ける（文字は不変）。"""
    from conftest import key_png
    from jasme_jats.pipeline import add_images
    path = tmp_path / "opt4.docx"
    cell_para = mf.para(S["body"], "セルの", fld(r"EQ \o\ac(○,7)"), "文字")
    article(path, lambda b: [mf.para(S["body"], mf.run("太字の", b=True), fld(r"EQ \o\ac(○,5)"), mf.run("部分", b=True), "である。"),
                             mf.table([[mf.cell([cell_para]), mf.cell("隣")]])])
    res = run_convert(path, journal, meta, tmp_path)
    keys = [i.key for i in optional(res)]
    assert len(keys) == 2
    add_images(res, {k: ("x.png", key_png(n)) for n, k in enumerate(keys)})
    xml = res.xml_path.read_text(encoding="utf-8")
    aid = meta.article_id(journal)
    assert f'<bold>太字の</bold><inline-graphic xlink:href="{aid}_{keys[0]}.png"/><bold>部分</bold>である。' in xml
    assert f'セルの<inline-graphic xlink:href="{aid}_{keys[1]}.png"/>文字' in xml
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and not res.image_problems


def test_no_optional_slot_in_title_and_references(journal, meta, tmp_path):
    """題目・引用文献の中のフィールド（画像を書けない文脈）には置き場所を作らない。XML は今と同じで、要確認 resultless_field は残る。"""
    import zipfile
    path = tmp_path / "opt5.docx"
    article(path, lambda b: [mf.para(S["body"], "本文である。")],
            refs=lambda b: [mf.para(S["ref"], "文献の", fld(r"EQ \o\ac(○,1)"), "文字列．")])
    patched = tmp_path / "opt5p.docx"
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(patched, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                text = data.decode("utf-8")
                end = "フィールドの検証用文書</w:t></w:r>"
                assert text.count(end) == 1
                data = text.replace(end, end + fld(r"EQ \o\ac(○,2)")).encode("utf-8")
            zout.writestr(item, data)
    res = run_convert(patched, journal, meta, tmp_path)
    assert len(res.resultless_fields) == 2 and optional(res) == []
    assert "inline-graphic" not in res.xml_path.read_text(encoding="utf-8")
    assert res.fidelity.ok and res.dtd_valid and not res.lost_images
    a, = found(res)
    assert "画像で補うこともできます" not in a.top and "画像の幹" not in a.top


def test_unused_optional_does_not_make_lost(journal, meta, tmp_path):
    """入れていない任意の置き場所は lost（画像の置き場所がない）にならない。"""
    path = tmp_path / "opt6.docx"
    article(path, lambda b: [mf.para(S["body"], "矢印", fld(r"EQ \o\ac(○,3)"), "。")])
    res = run_convert(path, journal, meta, tmp_path)
    assert res.lost_images == [] and all(a.key != "lost" for a in actions(res))
    assert optional(res)[0].status == "unused"


def test_optional_image_is_carried_over_and_matched_by_name(journal, meta, tmp_path):
    """持ち越し: 変換し直しても、同じ幹の任意の画像は入れ直される。まとめて入れるときの名前（幹）でも合う。"""
    from conftest import key_png
    from jasme_jats.images import match_names
    from jasme_jats.pipeline import add_images, kept_images, reapply_images
    path = tmp_path / "opt7.docx"
    article(path, lambda b: [mf.para(S["body"], "矢印", fld(r"EQ \o\ac(○,3)"), "。")])
    res = run_convert(path, journal, meta, tmp_path)
    key = optional(res)[0].key
    aid = meta.article_id(journal)
    matched, unmatched, clashes = match_names([f"{aid}_{key}.png", "other.png"], res.images, aid)
    assert matched == {key: f"{aid}_{key}.png"} and unmatched == ["other.png"] and not clashes
    add_images(res, {key: ("a.png", key_png(2))})
    kept = kept_images(res)
    res2 = run_convert(path, journal, meta, tmp_path)
    assert optional(res2)[0].status == "unused"
    assert reapply_images(res2, kept) == [key]
    assert optional(res2)[0].status == "user" and "<inline-graphic" in res2.xml_path.read_text(encoding="utf-8")
    assert not res2.images_dropped and res2.fidelity.final_ok


def test_optional_image_can_be_given_from_cli_and_app(journal, meta, tmp_path):
    """要確認 resultless_field が案内するとおり、任意の置き場所の画像も、コマンドラインの --images と 1 画面版の「まとめて入れる」で
    名前（幹・記事識別子つきの幹）から入れられる。図の画像の表と手順の数には出さない。"""
    from conftest import META_EXAMPLE, key_png
    from jasme_jats.cli import main, image_table
    from test_app import filled
    path = tmp_path / "opt8.docx"
    article(path, lambda b: [mf.para(S["body"], "矢印", fld(r"EQ \o\ac(○,3)"), "。")])
    key = optional(run_convert(path, journal, meta, tmp_path))[0].key
    folder = tmp_path / "pics"
    folder.mkdir()
    (folder / f"{key}.png").write_bytes(key_png(3))
    out = tmp_path / "cli"
    assert main([str(path), "--meta", str(META_EXAMPLE), "--out", str(out), "--images", str(folder)]) == 0
    xml = next(out.rglob("*.xml")).read_text(encoding="utf-8")
    assert f"_{key}.png" in xml and "<inline-graphic" in xml
    st = filled(tmp_path, docx=path)
    res = st.convert()
    aid = res.meta.article_id(res.journal)
    pic = tmp_path / f"{aid}_{key}.png"
    pic.write_bytes(key_png(4))
    matched, unmatched, clashes = st.match_images([str(pic)])
    assert list(matched) == [key] and not unmatched and not clashes
    assert st.add_images(matched) == [key] and optional(st.res)[0].status == "user"
    assert st.image_rows() == [] and image_table(st.res) == []          # 行と表には出さない
