"""Colab ノートブックの表示部品（colab.py）。"""
from jasme_jats.colab import error_box, prompt_box


def test_prompt_box_escapes_text_and_has_copy_button():
    html = prompt_box('依頼文 <b>&"', ["img3.png"])
    assert "依頼文 &lt;b&gt;&amp;&quot;" in html          # 依頼文はエスケープして textarea に入れる
    assert "依頼文をコピー" in html and "jasmeCopy(" in html
    assert "img3.png" in html and "手順 6" in html


def test_compact_box_and_error_box():
    html = prompt_box("x", compact=True)
    assert "依頼文をコピー" in html and "手順 6" not in html
    assert prompt_box("x").count("jasme-prompt-") != 0
    assert "&lt;x&gt;" in error_box("読めません", "<x>")


def test_no_ai_box_is_red_warning():
    from jasme_jats.colab import no_ai_box
    html = no_ai_box()
    assert "推奨しません" in html and "#dc2626" in html and "手動（チャットに貼り付け）" in html


def test_detects_values_left_from_previous_article():
    from jasme_jats.colab import carried_over, same_first_page
    prev = {"volume": "31", "issue": "1", "fpage": "1", "lpage": "12", "keywords_ja": "数学教育", "keywords_en": "",
            "received": "2026-04-01", "pub_date": "2026-12-01"}
    cur = dict(prev, lpage="20")
    assert same_first_page(prev, cur)                      # 巻と最初のページが同じ → 書き換え忘れの疑い
    assert carried_over(prev, cur) == ["最初のページ", "キーワード（日本語）", "受付日"]   # 空欄・号・発行日は対象外
    nxt = dict(prev, fpage="13", lpage="24", keywords_ja="証明", received="2026-05-01")
    assert not same_first_page(prev, nxt) and carried_over(prev, nxt) == []
    assert not same_first_page({"volume": "31", "fpage": ""}, {"volume": "31", "fpage": ""})


def test_next_article_box_is_red_warning():
    from jasme_jats.colab import next_article_box
    html = next_article_box("a.docx")
    assert "#dc2626" in html and "前の論文（a.docx）の値が残っています" in html
    assert "手順 3" in html and "開き直して" in html and "手順 1 から" in html
    assert "前の論文の値が残っています" in next_article_box()


def test_missing_images_box(journal, meta, tmp_path):
    from conftest import FULL, TEMPLATE
    from jasme_jats.colab import missing_images_box
    from jasme_jats.pipeline import Options, convert
    res = convert(TEMPLATE, meta, journal, Options(out_dir=tmp_path / "t", convert_metafiles=False))
    html = missing_images_box(res)
    assert "#dc2626" in html and "画像ファイルを用意できなかった図が 1 件あります" in html
    assert "31_1_01.png: 図1\u3000三角形ABC" in html and "jasme_31_1.zip の中の jasme/31/1/31_1/Graphics/" in html
    assert missing_images_box(convert(FULL, meta, journal, Options(out_dir=tmp_path / "f", convert_metafiles=False))) == ""


def test_pdf_diff_box_shows_formula_and_insert_marks():
    """ルート2 の赤い枠の直せなかった箇所の docx の文字は、レポートの 13.2 と同じ形にする（docx の数式・画像は「〓」、PDF に
    だけある文字は、足す位置の前後の docx の文字と「［］」）。同じ記号の 2 つの意味（docx の数式と、PDF で読み取れない部分）を
    一覧の前に添える（MATH_WHY の行。docx の数式の位置の行と、PDF にだけある文字の行）。"""
    from pathlib import Path
    from types import SimpleNamespace
    from jasme_jats.colab import pdf_diff_box
    from jasme_jats.pdfdocx import DocxFix, Fix
    from jasme_jats.pdfmatch import MATH_WHY, PdfCheck
    text = "値の組（￼，￼）を順に調べ，その確率を表に記録した。"
    at = text.index("を表")
    fx = DocxFix(Path("31_1_PDFに合わせた原稿.docx"), texts={"d12": text},
                 fixes=[Fix("d12", 4, 5, "〓，〓", "text", old="￼", reason=MATH_WHY),
                        Fix("d12", at, at, "（〓，…，〓とおく）", "text", reason=MATH_WHY)])
    html = pdf_diff_box(SimpleNamespace(pdf_check=PdfCheck(), docx_fix=fx))
    assert "￼" not in html and "・d12: 「〓」→「〓，〓」" in html
    assert "・d12: 「…に調べ，その確率［］を表に記録した。」→「（〓，…，〓とおく）」" in html
    assert "docx の側の「〓」は docx の数式・画像、PDF の側の「〓」は PDF で数式など文字として読み取れない部分です。" in html
    assert "docx の側の「［］」は、docx に文字がなく PDF にだけ文字がある位置です" in html


def test_ai_required_and_unplaced_boxes(journal):
    """位置を決められなかった図表の枠は、図表ごとに仮に置いた位置（アンカー段落の後ろ・本文の最後）を示す。"""
    from types import SimpleNamespace

    from conftest import FLOAT, PLACE

    from jasme_jats.colab import ai_required_box, unplaced_box
    from jasme_jats.pipeline import _mechanical
    assert "変換を中止しました" in ai_required_box("s1: …") and "#dc2626" in ai_required_box("x")
    assert unplaced_box(SimpleNamespace(unplaced_floats=[])) == ""
    _, plan, _ = _mechanical(FLOAT, journal)
    html = unplaced_box(plan)
    assert "#dc2626" in html and "仮の位置に置いています" in html and "手作業" in html and "本文の冒頭" not in html
    assert "・s1（「図1\u3000表で組んだ問題」）: 段落「この段落に図1のテキストボックスが結び付」の後ろ\n" in html
    assert "・s3（「図2\u3000グループ図形の図」）: 段落「図2は教科書の見開きページであり，グルー」の後ろ\n" in html
    # AI が注の段落の後ろを指定した図表は、本文の最後（理由を添える）
    _, first, _ = _mechanical(PLACE, journal)
    note = next(src for src, p in first.paras.items() if p.plain().startswith("1) 架空の注"))
    _, plan, _ = _mechanical(PLACE, journal, placements={"s1": {"where": "end", "after": note}})
    html = unplaced_box(plan)
    assert "・s1（「図1\u3000一つ目の図」）: 本文の最後（AI が注などの本文の外の段落の後ろを指定したため）\n" in html
    assert "・s2（「図3\u3000三つ目の図」）: 段落「この段落に図3と図2のテキストボックスが」の後ろ\n" in html


def test_figure_body_box(journal, meta, tmp_path):
    """図の本体（画像・表）が見つからない図（近くの表を図の本体にできなかったもの）の赤い枠。"""
    from conftest import FULL, TABLEFIG

    from jasme_jats.colab import figure_body_box
    from jasme_jats.pipeline import Options, convert
    html = figure_body_box(convert(TABLEFIG, meta, journal, Options(out_dir=tmp_path / "t", convert_metafiles=False)))
    assert "#dc2626" in html and "図の本体（画像・表）が見つからない図が 2 件あります（要対応）" in html
    assert "・「図2\u3000間に段落がある問題」（図キャプションの前にキャプションのない表があるが、間にほかの段落がある）" in html
    assert "・「図3\u3000表の直後の図キャプション」（直前の表に表キャプション「表1\u3000表キャプションの付いた表」が付いている）" in html
    assert "表を図キャプションのすぐ上" in html and "変換し直してください" in html
    assert figure_body_box(convert(FULL, meta, journal, Options(out_dir=tmp_path / "f", convert_metafiles=False))) == ""
