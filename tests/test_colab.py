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


def test_ai_required_and_unplaced_boxes():
    from types import SimpleNamespace
    from jasme_jats.colab import ai_required_box, unplaced_box
    assert "変換を中止しました" in ai_required_box("s1: …") and "#dc2626" in ai_required_box("x")
    assert unplaced_box(SimpleNamespace(unplaced_floats=[])) == ""
    html = unplaced_box(SimpleNamespace(unplaced_floats=["s1", "s3"]))
    assert "s1, s3" in html and "本文の冒頭" in html and "手作業" in html
