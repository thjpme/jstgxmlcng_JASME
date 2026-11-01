"""画像の出力漏れの検出（pipeline.lost_images）と、文字だけのテキストボックスの知らせ（0.24.1 までの暫定の知らせの代わり）。

不変性チェックは文字しか見ないので、画像を出力できない場所（引用文献・題目・著者名・所属の段落など）や、出力しなかった段落の
中の画像は、調べないと XML からも Graphics/ からも黙って消える。docs/fix_plan_repro_tests.py の
test_PROBLEM_N1_image_in_reference_is_lost_silently の逆を確かめる。引用文献の段落に結び付いた図形の中の画像は、0.25.0 から
図に入れる（位置を決められない図表。修正計画の N7）。
"""
import zipfile

import pytest
from lxml import etree

import make_fixtures as mf
from conftest import DATA, FLOAT, FLOAT_TEXT, FULL, PDFCHECK, PDFCHECK_PDF
from jasme_jats.pipeline import AIRequiredError, Options, convert

S = mf.S
CM = 360000


def load(res):
    return etree.fromstring(res.xml_path.read_bytes().split(b"\n", 2)[2])


def chapters(report):
    """レポートの冒頭（1 章まで）・9 章・14 章。"""
    return report.split("## 2.")[0], report.split("## 9.")[1].split("## 10.")[0], report.split("## 14.")[1]


def body_citing(b):
    # 本文の図（XML に出力する画像 img1）と、引用文献の引用
    rid = b.add_image("bodyimg.png", mf.png_bytes("body image"))
    return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "試験（2024）にならい，図1と引用文献の段落に画像を置いた。"),
            mf.para(S["body"], mf.drawing(rid, 1800000, 1000000, 600)), mf.para(S["fig_cap"], "図1\u3000本文の図")]


def image_only_ref(b):
    # 引用文献のスタイルの、画像だけの段落
    rid = b.add_image("refimg.png", mf.png_bytes("ref image"))
    return [mf.para(S["ref"], "試験太郎（2020）．「題」．『架空誌』，第1巻，pp.1-2．"),
            mf.para(S["ref"], mf.drawing(rid, 1800000, 1000000, 601))]


def inline_image_in_ref(b):
    # 文字のある引用文献の段落の中の、行内の画像
    rid = b.add_image("inline.png", mf.png_bytes("inline"))
    return [mf.para(S["ref"], "試験花子（2021）．「題」", mf.drawing(rid, 360000, 360000, 602), "．『架空誌』，第2巻，pp.3-4．")]


def textbox_on_ref(b):
    # 引用文献の段落に結び付いたテキストボックス（図の画像とキャプション）。0.25.0 から、中身は位置を決められない図表（N7）
    rid = b.add_image("bk.png", mf.png_bytes("fig"))
    return [mf.para(S["ref"], "試験太郎（2020）．「題」．『架空誌』，第1巻，pp.1-2．", mf.textbox(
        mf.para(S["body"], mf.drawing(rid, 1800000, 1100000, 801)) + mf.para(S["fig_cap"], "図5\u3000最後のページの図"),
        802, cx=8 * CM, cy=5 * CM))]


def make_ref_image(path, refs):
    mf.make_article(path, "引用文献の画像の検証用文書", body_citing, refs=refs)
    return path


@pytest.mark.parametrize("refs, text", [
    (image_only_ref, ""),
    (inline_image_in_ref, "試験花子（2021）．「題」．『架空誌』")], ids=["image-in-ref", "inline-in-ref"])
def test_image_in_reference_is_reported(refs, text, journal, meta, tmp_path):
    res = convert(make_ref_image(tmp_path / "ref.docx", refs), meta, journal,
                  Options(out_dir=tmp_path / "out", convert_metafiles=False))
    # 文字の検証はすべて合格し、画像は XML にも Graphics/ にも出ない（変換は変えずに、知らせる）
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    # 本文の図の画像だけが XML と Graphics/ に出る
    assert [i.image_id for i in res.images] == ["img1"] and len(list(load(res).iter("graphic", "inline-graphic"))) == 1
    assert len(res.lost_images) == 1 and res.hidden_images == []
    li = res.lost_images[0]
    assert li.image_id == "img2" and li.source.startswith("word/media/")
    assert li.location.startswith("引用文献") and res.plan.region[li.src] == "refs"
    assert li.reason.startswith("引用文献の段落の中にある（引用文献には画像を出力できない）")
    assert li.text == text            # 段落の文字の冒頭（Word で探す手がかり）
    report = res.report_path.read_text(encoding="utf-8")
    top, ch9, ch14 = chapters(report)
    assert "**要対応: XML に入らなかった画像が 1 件あります（9 章）。**" in top
    assert f"> - img2（段落 {li.src}" in top and "Word でその画像" in top and "本文の段落に" in top
    assert "| 画像 | XML に出力 1 件（うち要対応 0 件）。ほかに XML に入らなかった画像が 1 件あり、要対応（9 章） |" in top
    assert "### XML に入らなかった画像（要対応）" in ch9 and "| img2 | word/media/" in ch9 and "| img1 | 31_1_01.png |" in ch9
    assert "- [ ] **XML に入らなかった画像 1 件**（9 章）" in ch14 and "img2（段落" in ch14
    assert "すべて Graphics/ に入っている" not in ch14


def test_figure_on_reference_becomes_unplaced(journal, meta, tmp_path):
    """引用文献の段落に結び付いた図形（画像と図キャプション）は、引用文献の段落にせず、位置を決められない図表にする（修正計画の
    N7。0.24.1 までは画像が XML に入らなかった）。AI を使わない設定では止める。AI が位置を答えなければ本文の最後に仮に置き、
    手作業で移す要対応として知らせる。画像は図に入るので、XML に入らなかった画像にはならない。"""
    path = make_ref_image(tmp_path / "ref.docx", textbox_on_ref)
    with pytest.raises(AIRequiredError):
        convert(path, meta, journal, Options(out_dir=tmp_path / "none", convert_metafiles=False))
    resp = '{"placements": [], "operations": [], "notes": []}'
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", ai_mode="manual", ai_response=resp,
                                               convert_metafiles=False))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and res.lost_images == []
    assert sorted(i.image_id for i in res.images) == ["img1", "img2"]
    root = load(res)
    last = root.find("body")[-1]
    assert last[-1].tag == "fig" and "".join(last[-1].find("caption").itertext()) == "図5\u3000最後のページの図"
    assert "図5" not in "".join("".join(m.itertext()) for m in root.iter("mixed-citation"))
    assert res.needs_action and any("本文の最後" in x for x in res.forced_floats)
    top = chapters(res.report_path.read_text(encoding="utf-8"))[0]
    assert "XML に入らなかった画像" not in top and "要対応: 位置を決められなかった図表が 1 件あります" in top


def test_cli_exits_1_and_reports_lost_images(journal, tmp_path, capsys):
    from jasme_jats.cli import main
    path = make_ref_image(tmp_path / "ref.docx", image_only_ref)
    meta = tmp_path / "meta.toml"
    meta.write_text('[article]\nvolume = "31"\nissue = "1"\nfpage = "1"\npeer_review = "あり"\n', encoding="utf-8")
    assert main([str(path), "--meta", str(meta), "--out", str(tmp_path / "out"), "--no-metafile-conversion"]) == 1
    err = capsys.readouterr().err
    assert "要対応: XML に入らなかった画像 1 件" in err and "本文の段落に移して" in err
    assert "img2（段落 d" in err and "引用文献の段落の中にある" in err


def test_lost_images_box(journal, meta, tmp_path):
    from jasme_jats.colab import lost_images_box
    res = convert(make_ref_image(tmp_path / "ref.docx", image_only_ref), meta, journal,
                  Options(out_dir=tmp_path / "out", convert_metafiles=False))
    html = lost_images_box(res)
    assert "#dc2626" in html and "XML に入らなかった画像が 1 件あります（要対応）" in html
    assert "・img2（段落 d" in html and "本文の段落に移して" in html and "手順 2" in html
    assert lost_images_box(convert(FULL, meta, journal, Options(out_dir=tmp_path / "f", convert_metafiles=False))) == ""


def test_image_in_excluded_front_paragraph_is_reported(journal, meta, tmp_path):
    # 和文の冒頭の誌名の行に結び付いた、画像のテキストボックス（ロゴなど）。中身は冒頭に入り、画像の段落は
    # 「冒頭部のテンプレート装飾」として除外される（出力しなかった段落の中の画像）。
    # 冒頭の最後の段落（セクション区切り）に結び付いた図は本文に入る（test_structure.test_figure_on_section_break_paragraph_goes_to_body）
    b = mf.Builder()
    front = mf.front_ja(b, "冒頭の画像の検証用文書", "―副題―", [("架空大学", "試験\u3000七郎")])
    rid = b.add_image("logo.png", mf.png_bytes("logo", size=(400, 240)))
    tb = mf.textbox(mf.para(S["body"], mf.drawing(rid, 1800000, 1080000, 702)), 701, cx=3000000, cy=1500000)
    front[0].append(b.frag(mf.para(None, tb))[0][0])
    body = front + [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "試験（2025）にならう。"),
                    mf.para(S["ref_head"], "引用および参考文献"),
                    mf.para(S["ref"], "試験七郎（2025）．「題」．『架空誌』，第6巻，pp.11-12．")]
    body += mf.front_en(b, "Title", "Subtitle", [("Shichiro SHIKEN", "Fictional University")], ["Abstract text."])
    body += mf.tail(b)
    b.save(tmp_path / "front.docx", body)
    res = convert(tmp_path / "front.docx", meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    assert res.fidelity.ok and res.dtd_valid and res.images == []
    [li] = res.lost_images
    assert res.plan.region[li.src] == "front_ja" and li.location == "冒頭部"
    assert li.reason.startswith("XML に出力しなかった段落（理由「冒頭部のテンプレート装飾")
    assert "テキストボックス・グループ図形 s1 の中の画像" in li.reason
    assert "**要対応: XML に入らなかった画像が 1 件あります（9 章）。**" in res.report_path.read_text(encoding="utf-8")


def make_endnote_image(path, referenced):
    """Word の文末脚注 4 の 2 段落目が画像だけの段落の、小さな論文。referenced が偽なら、本文から文末脚注を参照しない。"""
    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"),
                mf.para(S["body"], "試験（2024）の文", mf.endnote_ref(4) if referenced else "", "。")]
    note = mf.endnote(4, " 文末脚注の本文。", mf.para(None, mf.drawing("rId77", 1800000, 1000000, 961)))
    mf.make_article(path, "文末脚注の画像の検証用文書", parts,
                    endnotes=[note.replace('<w:endnote w:id="4">', f'<w:endnote w:id="4" {mf.NSDECL}>')])
    with zipfile.ZipFile(path, "a") as z:        # 文末脚注の画像の関係（テンプレートには endnotes.xml.rels がない）
        z.writestr("word/_rels/endnotes.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/relationships"><Relationship Id="rId77" Type="http://schemas.openxmlformats.org/officeDocument/'
                   '2006/relationships/image" Target="media/note.png"/></Relationships>')
        z.writestr("word/media/note.png", mf.png_bytes("note"))
    return path


def test_image_in_referenced_endnote_is_output(journal, meta, tmp_path):
    # 本文から参照された Word の文末脚注は注（fn）として出力するので、その中の画像も XML と Graphics/ に出る（0.24.0）
    res = convert(make_endnote_image(tmp_path / "endnote.docx", True), meta, journal,
                  Options(out_dir=tmp_path / "out", convert_metafiles=False))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and res.jstage_issues == []
    assert res.lost_images == [] and [i.image_id for i in res.images] == ["img1"]
    fn = load(res).find(".//fn-group/fn")
    assert "".join(fn.find("p").itertext()) == "1) 文末脚注の本文。" and fn.find("p/inline-graphic") is not None
    assert "XML に入らなかった画像" not in res.report_path.read_text(encoding="utf-8")


def test_image_in_unreferenced_endnote_is_reported_with_location(journal, meta, tmp_path):
    # 本文から参照されていない Word の文末脚注は出力しない（理由付きで除外）。その中の画像だけの段落は、XML に入らなかった
    # 画像として要対応で知らせ、場所は「Word の文末脚注 4」と書く
    res = convert(make_endnote_image(tmp_path / "endnote.docx", False), meta, journal,
                  Options(out_dir=tmp_path / "out", convert_metafiles=False))
    assert res.fidelity.ok and res.dtd_valid
    [li] = res.lost_images
    assert li.src.startswith("e") and li.location == "Word の文末脚注 4" and li.text == ""
    assert li.reason.startswith("XML に出力しなかった段落（理由「Word の文末脚注 4（本文から参照されていない注）」")
    top, ch9, _ = chapters(res.report_path.read_text(encoding="utf-8"))
    assert f"| {li.image_id} | word/media/note.png | {li.src} | Word の文末脚注 4 |" in ch9
    assert "**要対応: XML に入らなかった画像が 1 件あります（9 章）。**" in top
    assert "要確認: Word の文末脚注" not in top          # 文末脚注の暫定の知らせは出ない（0.24.0）


def test_hidden_image_is_not_lost(journal, meta, tmp_path):
    # 隠し文字のランの中の画像は、Word で表示されないので出力しない（隠し文字と同じ扱い。要対応にはしない）
    def parts(b):
        rid = b.add_image("hidden.png", mf.png_bytes("hidden"))
        hidden = mf.drawing(rid, 1800000, 1000000, 611).replace("<w:r>", "<w:r><w:rPr><w:vanish/></w:rPr>", 1)
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "試験（2024）の本文。", hidden)]
    mf.make_article(tmp_path / "hidden.docx", "隠し文字の画像の検証用文書", parts)
    res = convert(tmp_path / "hidden.docx", meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    assert res.fidelity.ok and res.lost_images == [] and res.hidden_images == ["img1"] and res.images == []
    report = res.report_path.read_text(encoding="utf-8")
    assert "XML に入らなかった画像" not in report
    assert "隠し文字の中の画像 1 件（img1）: Word で表示されないので、出力していません。" in report.split("## 7.")[0]
    ch9 = chapters(report)[1]
    assert "XML に出力した画像はありません。" in ch9 and "隠し文字（Word で非表示に設定された文字）の中の画像 1 件（img1）" in ch9


@pytest.mark.parametrize("by", ["direct", "style"])
def test_style_hidden_image_is_noticed(by, journal, meta, tmp_path):
    # 文字スタイルで隠し文字になっているランの中の画像も、ランに直接付けた隠し文字と同じく出力しない（要対応にはしない）。隠し文字の
    # 判定（スタイルの w:vanish）は暫定なので、スタイルで隠した画像は要確認で知らせる（ランに直接付けた隠し文字の画像は知らせない）
    from jasme_jats.report import TO_CHECK, actions

    def parts(b):
        b.styles_extra.append(mf.READER_STYLES)
        rid = b.add_image("hidden.png", mf.png_bytes("hidden"))
        rpr = "<w:vanish/>" if by == "direct" else '<w:rStyle w:val="gHid"/>'
        hidden = mf.drawing(rid, 1800000, 1000000, 612).replace("<w:r>", f"<w:r><w:rPr>{rpr}</w:rPr>", 1)
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "試験（2024）の本文。", hidden)]
    mf.make_article(tmp_path / "hidden.docx", "隠し文字の画像の検証用文書", parts)
    res = convert(tmp_path / "hidden.docx", meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    assert res.fidelity.ok and res.lost_images == [] and res.hidden_images == ["img1"] and res.images == []
    acts = {a.key: a for a in actions(res)}
    if by == "direct":
        assert res.style_hidden_images == [] and "style_hidden" not in acts
        return
    act = acts["style_hidden"]
    assert res.style_hidden_images == ["img1"] and res.style_hidden == [] and act.level == TO_CHECK
    assert "既定の書式の設定で隠し文字になっている画像が 1 件あり、XML に出力していません（6 章）" in act.top
    assert act.top.endswith("対象: 画像 img1")
    assert "上の隠し文字のうち" in res.report_path.read_text(encoding="utf-8").split("## 6.")[1].split("## 7.")[0]


@pytest.mark.parametrize("case", ["full-ai", "float-ai", "float-text", "pdfcheck-route1", "pdfcheck-route2"])
def test_no_lost_images_in_fixtures(case, journal, meta, tmp_path):
    # 既存の fixture（ALL_DOCS は test_pipeline.test_fidelity_and_dtd で確かめる）では、画像の出力漏れはない
    kw = {"full-ai": dict(path=FULL, ai_mode="manual",
                          ai_response=(DATA / "ai_response_sample_full.json").read_text(encoding="utf-8")),
          "float-ai": dict(path=FLOAT, ai_mode="manual",
                           ai_response=(DATA / "ai_response_sample_float.json").read_text(encoding="utf-8")),
          "float-text": dict(path=FLOAT_TEXT),
          "pdfcheck-route1": dict(path=PDFCHECK, pdf_path=PDFCHECK_PDF, route="docx"),
          "pdfcheck-route2": dict(path=PDFCHECK, pdf_path=PDFCHECK_PDF, route="pdf")}[case]
    path = kw.pop("path")
    res = convert(path, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False, **kw))
    assert res.lost_images == [] and res.hidden_images == []
    assert "XML に入らなかった画像" not in res.report_path.read_text(encoding="utf-8")


def make_provisional(path, hint=False):
    """文字だけのテキストボックス（2 段落と全角空白の段落）と、Word の文末脚注 1 件（2 段落目は空白だけ）がある小さな論文。

    0.24.1 までは、文字だけのテキストボックスを除外し、暫定の知らせ（要確認）を出していた。0.25.0 からは囲み（boxed-text）に
    出す（修正計画の F）。hint なら、囲みか図の注記か決められない「（ヒント）」のテキストボックスも足す（要確認の対象）。
    Word の文末脚注は 0.24.0 から注として出力する。"""
    def parts(b):
        out = [mf.para(S["sec1"], "１．はじめに"),
               mf.para(S["body"], "試験（2024）の問題を枠で囲んだ。", mf.textbox(
                   mf.para(S["body"], "問1\u3000枠の中の問題文である。") + mf.para(S["body"], "ヒント: 図をかく。")
                   + mf.para(S["body"], "\u3000"), 903, cx=5000000)),
               mf.para(S["body"], "文末脚注を付けた文", mf.endnote_ref(4), "。")]
        if hint:
            out.append(mf.para(S["body"], "ヒントの札を付けた。", mf.textbox(mf.para(S["body"], "（ヒント）"), 904, cx=3600000,
                                                                      cy=300000, v=("paragraph", 500000))))
        return out
    mf.make_article(path, "囲みの知らせの検証用文書", parts, endnotes=[mf.endnote(4, " 文末脚注の本文。", mf.para(None, " "))])
    return path


def test_textbox_notices_replace_provisional_ones(journal, meta, tmp_path):
    # 0.24.1 の暫定の知らせ（「テキストボックスの中の文字 N 段落を、XML に出力していません」）は出さない。囲みは boxed-text に
    # 出し、囲みか図の注記か決められないものだけを要確認で知らせる（レポートの冒頭・14 章。要対応の後ろ）
    res = convert(make_provisional(tmp_path / "prov.docx"), meta, journal,
                  Options(out_dir=tmp_path / "out", convert_metafiles=False))
    assert res.fidelity.ok and res.lost_images == [] and res.dtd_valid
    bt = load(res).find(".//boxed-text")
    assert ["".join(p.itertext()) for p in bt.findall("p")] == ["問1\u3000枠の中の問題文である。", "ヒント: 図をかく。"]
    report = res.report_path.read_text(encoding="utf-8")
    assert "テキストボックスの中の文字" not in report and "要確認: 囲み" not in report and "要確認: 位置を推定" not in report
    assert "".join(load(res).find(".//fn-group/fn/p").itertext()) == "1) 文末脚注の本文。"
    assert not any("未対応" in reason for _, reason, _ in res.fidelity.excluded)
    res = convert(make_provisional(tmp_path / "hint.docx", hint=True), meta, journal,
                  Options(out_dir=tmp_path / "hint", convert_metafiles=False))
    top, _, ch14 = chapters(res.report_path.read_text(encoding="utf-8"))
    assert ("**要確認: 囲み（問題文・ヒントなど）か図の注記か決められなかったテキストボックスが 1 件あり、その文字を XML に"
            "出力していません（3 章・6 章）。**") in top and "「（ヒント）」" in top
    assert "- [ ] **囲みか図の注記か決められなかったテキストボックス 1 件**" in ch14 and not res.needs_action
    # 要確認は、要対応の後ろ（0.23.0 からの並び）
    from jasme_jats.report import render
    res.fidelity.ok = False
    top = render(res).split("## 2.")[0]
    assert top.index("> **注意: 文字の不変性チェックが不合格です。**") < top.index("> **要確認: 囲み（問題文")
    res.fidelity.ok = True
    full = convert(FULL, meta, journal, Options(out_dir=tmp_path / "full", convert_metafiles=False)).report_path
    assert "テキストボックス" not in full.read_text(encoding="utf-8").split("## 2.")[0]


def test_cli_shows_textbox_notices(journal, tmp_path, capsys):
    # コマンドラインでも、囲みか図の注記か決められなかったテキストボックス（要確認）を標準エラーに出す。終了コードは 0
    from jasme_jats.cli import main
    path = make_provisional(tmp_path / "hint.docx", hint=True)
    meta = tmp_path / "meta.toml"
    meta.write_text('[article]\nvolume = "31"\nissue = "1"\nfpage = "1"\npeer_review = "あり"\n', encoding="utf-8")
    assert main([str(path), "--meta", str(meta), "--out", str(tmp_path / "out"), "--no-metafile-conversion"]) == 0
    err = capsys.readouterr().err
    assert "要確認: 囲みか図の注記か決められなかったテキストボックス 1 件の文字を XML に出力していません" in err
    assert "--ai manual か --ai api で AI による補完を使うか" in err and "テキストボックスの中の文字" not in err
