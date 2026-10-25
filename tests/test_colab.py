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


def test_pdf_diff_box_shows_context_of_far_replacement():
    """ルート2 の赤い枠の直せなかった箇所のうち、分断された段落の部分の置き換え（FAR_WHY・DISPLACED_WHY）の docx の文字は、
    レポートの 13.2 と同じく、違う部分を「［…］」で囲んで前後の docx の文字とともに出し（表のキャプションの「１」と並べた「12点」の
    「2」→「13」。そのとおりに置き換えると「113点」になる）、一覧の前にその意味を添える。"""
    from pathlib import Path
    from types import SimpleNamespace
    from jasme_jats.colab import pdf_diff_box
    from jasme_jats.pdfdocx import DocxFix, Fix
    from jasme_jats.pdfmatch import FAR_WHY, PdfCheck
    text = "架空の調査の結果を表１に示す。その結果，生徒の平均は12点であり，前回の調査より高かった。"
    at = text.index("2点")
    fx = DocxFix(Path("31_1_PDFに合わせた原稿.docx"), texts={"d12": text},
                 fixes=[Fix("d12", at, at + 1, "13", "text", old="2", reason=FAR_WHY)])
    html = pdf_diff_box(SimpleNamespace(pdf_check=PdfCheck(), docx_fix=fx))
    assert "・d12: 「…，生徒の平均は1［2］点であり，前回の…」→「13」" in html
    assert "docx の側の「［…］」で囲んだ文字は docx の違う部分です" in html


def test_ai_required_and_unplaced_boxes():
    from types import SimpleNamespace
    from jasme_jats.colab import ai_required_box, unplaced_box
    assert "変換を中止しました" in ai_required_box("s1: …") and "#dc2626" in ai_required_box("x")
    assert unplaced_box(SimpleNamespace(unplaced_floats=[])) == ""
    html = unplaced_box(SimpleNamespace(unplaced_floats=["s1", "s3"]))
    assert "s1, s3" in html and "本文の冒頭" in html and "手作業" in html
