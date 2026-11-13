"""Colab ノートブックの表示部品（colab.py）。"""
import re

from jasme_jats.colab import error_box, prompt_box


def test_prompt_box_escapes_text_and_has_copy_button():
    html = prompt_box('依頼文 <b>&"')
    assert "依頼文 &lt;b&gt;&amp;&quot;" in html          # 依頼文はエスケープして textarea に入れる
    assert "依頼文をコピー" in html and "jasmeCopy(" in html
    assert "手順 6" in html and "画像" not in html           # docx の画像は AI に渡さない（修正計画 W1）
    assert "（任意）" in html and "出版版 PDF" in html          # 位置を聞く図形のない論文では、PDF の添付は任意（点検 review13 利用者向け 9）


def test_error_box_and_check_box():
    """要対応は赤い枠、要確認は黄色い枠。どちらも文字をエスケープする。"""
    from jasme_jats.colab import check_box
    assert prompt_box("x").count("jasme-prompt-") != 0
    assert "&lt;x&gt;" in error_box("読めません", "<x>") and "#dc2626" in error_box("a", "b")
    assert "&lt;x&gt;" in check_box("確認", "<x>") and "#d97706" in check_box("a", "b") and "#dc2626" not in check_box("a", "b")


def test_summary_box_and_report_details(journal, meta, tmp_path, monkeypatch):
    """結果の要約の灰色の枠（不合格・要対応の行は赤い文字）と、畳んで出すレポート全文（Markdown の表を HTML にする）。"""
    import sys
    from types import SimpleNamespace
    from conftest import FULL
    from jasme_jats.colab import report_details, summary_box
    from jasme_jats.pipeline import Options, convert
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path / "s"))
    html = summary_box(res)
    assert "結果の要約" in html and "文字の不変性チェック: 合格" in html and "DTD 検証: 合格" in html
    assert "J-STAGE のアップロード時チェック: 問題なし" in html and "出版版 PDF との照合: PDF なし" in html
    assert "#b91c1c" not in html and "PDF で補った docx" not in html
    res.dtd_valid = False
    assert "color:#b91c1c !important;font-weight:bold'>DTD 検証: 不合格" in summary_box(res)
    # ルート2 で補った docx の名前。PDF の文字を読めなかったときは、補えなかったことを赤い文字で
    res.docx_fix = SimpleNamespace(path=tmp_path / "31_1_PDFで補完した原稿.docx")
    assert "PDF で補った docx: 31_1_PDFで補完した原稿.docx（変更履歴つき" in summary_box(res)
    # 補完の確かめ（ルート2 で行ったときだけ。不合格は赤字）
    assert "補完の確かめ" not in summary_box(res)
    res.supplement = SimpleNamespace(ok=True)
    assert "<div style='white-space:pre-wrap'>出版版 PDF による補完の確かめ: 合格" in summary_box(res)
    res.supplement = SimpleNamespace(ok=False)
    assert "color:#b91c1c !important;font-weight:bold'>出版版 PDF による補完の確かめ: 不合格" in summary_box(res)
    res.supplement = None
    res.docx_fix = None
    monkeypatch.setattr(type(res), "pdf_fallback", property(lambda self: True))
    assert "font-weight:bold'>PDF で補った docx: 作れませんでした" in summary_box(res)
    md = "# 変換レポート\n\n| 項目 | 結果 |\n|---|---|\n| 不変性 | 合格 |\n\n> **注意** <b>\n"
    html = report_details(md)
    assert html.index("<details") < html.index("<summary") and "変換レポートの全文を見る" in html
    assert "<table>" in html and "<td>合格</td>" in html and "<blockquote>" in html
    # markdown ライブラリがなければ、そのままの文字で出す
    monkeypatch.setitem(sys.modules, "markdown", None)
    html = report_details(md)
    assert "<details" in html and "<table>" not in html and "| 不変性 | 合格 |" in html


def test_summary_box_has_ai_finish_row(journal, meta, tmp_path):
    """結果の要約に「AI による仕上げ」の行（方法・モデルと状態〈report.ai_state〉）がある。推奨の手順なので、失敗でも赤くしない
    （修正計画 W8 の手順 4・4.8）。"""
    from types import SimpleNamespace
    from conftest import FLOAT, FULL
    from jasme_jats.colab import summary_box
    from jasme_jats.pipeline import Options, convert
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path / "n"))
    assert "AI による仕上げ: 使わない。状態: 未実行" in summary_box(res)
    res = convert(FLOAT, meta, journal, Options(out_dir=tmp_path / "m", ai_mode="manual"))
    assert "AI による仕上げ: 手動（チャットに貼り付け）。状態: 回答待ち" in summary_box(res)
    res.ai = SimpleNamespace(mode="api", provider="claude", model="claude-x", raw="", error="接続できませんでした", partial=False, pdf_seen="")
    html = summary_box(res)
    assert "AI による仕上げ: API（Claude）（モデル: claude-x）。状態: 失敗" in html and "#b91c1c" not in html


def test_no_ai_is_not_discouraged():
    """「使わない」を推奨しないとは言わない（AI は強く推奨する仕上げで、必須にしない。修正計画 W8 の決定 4・手順 4）。
    src・tools・notebooks に「推奨しません」と、なくした赤い枠（no_ai_box・NO_AI_TITLE・NO_AI_DETAIL）の名前がない。"""
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    files = [f for d in ("src", "tools", "notebooks") for f in (root / d).rglob("*")
             if f.suffix in (".py", ".ipynb") and "__pycache__" not in f.parts]
    assert files
    for f in files:
        text = f.read_text(encoding="utf-8")
        for word in ("推奨しません", "no_ai_box", "NO_AI_TITLE", "NO_AI_DETAIL"):
            assert word not in text, (f, word)
    from jasme_jats import app
    assert ("使わない", "none") in app.AI_MODES


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
    # 全角で入れ直しても、フォルダ名・ファイル名は同じ（31_1）になるので、同じとみなす（修正計画 C の N4）
    assert same_first_page({"volume": "31", "fpage": "1"}, {"volume": "３１", "fpage": "１ "})
    assert not same_first_page({"volume": "31", "fpage": "1"}, {"volume": "31", "fpage": "　"})


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
    from conftest import fill_images
    # 図の画像は作業する人が入れる（修正計画 W1）: 残っていれば手順 images の青い枠、入れれば出さない
    res = convert(TEMPLATE, meta, journal, Options(out_dir=tmp_path / "t"))
    html = missing_images_box(res)
    assert "#2563eb" in html and "#dc2626" not in html and "手順: 図の画像を入れてください（あと 1 枚／全部で 1 枚）" in html
    assert "・fig01: 「図1\u3000三角形ABC」" in html and "手順 7「図の画像を入れる」で入れてください" in html
    fill_images(res)
    assert missing_images_box(res) == ""
    assert missing_images_box(convert(FULL, meta, journal, Options(out_dir=tmp_path / "f"))) != ""


def test_pdf_diff_box_shows_formula_and_insert_marks():
    """ルート2 の赤い枠の直さなかった箇所の docx の文字は、レポートの 13.3 と同じ形にする（docx の数式・画像は「〓」、PDF に
    だけある文字は、足す位置の前後の docx の文字と「［］」）。同じ記号の 2 つの意味（docx の数式と、PDF で読み取れない部分）を
    一覧の前に添える（MATH_WHY の行。docx の数式の位置の行と、PDF にだけある文字の行）。"""
    from pathlib import Path
    from types import SimpleNamespace
    from jasme_jats.colab import pdf_diff_box
    from jasme_jats.pdfdocx import DocxFix, Fix
    from jasme_jats.pdfmatch import MATH_WHY, PdfCheck
    text = "値の組（￼，￼）を順に調べ，その確率を表に記録した。"
    at = text.index("を表")
    fx = DocxFix(Path("31_1_PDFで補完した原稿.docx"), texts={"d12": text},
                 fixes=[Fix("d12", 4, 5, "〓，〓", "text", old="￼", reason=MATH_WHY),
                        Fix("d12", at, at, "（〓，…，〓とおく）", "text", reason=MATH_WHY)])
    html = pdf_diff_box(SimpleNamespace(pdf_check=PdfCheck(), docx_fix=fx))
    assert "￼" not in html and "・d12: 「〓」→「〓，〓」" in html
    assert "・d12: 「…に調べ，その確率［］を表に記録した。」→「（〓，…，〓とおく）」" in html
    assert "docx の側の「〓」は docx の数式・画像、PDF の側の「〓」は PDF で数式など文字として読み取れない部分です。" in html
    assert "docx の側の「［］」は、docx に文字がなく PDF にだけ文字がある位置です" in html


def test_abort_display_for_ai_is_gone():
    """AI を使わない設定でも変換は中止しない（修正計画 W8 の決定 4）ので、中止の表示（AIRequiredError・ai_required_box）と、位置を
    決められなかった図表の赤い枠（unplaced_box）、目印 ai_modes は、製品のコード・作業用のスクリプト・ノートブックにない（W8 の手順 2）。
    図表を置いた位置は推奨の手順 ai_finish・要確認 float_end とレポートの 3 章で知らせる（test_steps・test_floats）。"""
    from pathlib import Path

    from jasme_jats import report
    root = Path(__file__).resolve().parent.parent
    files = [*(root / "src").rglob("*.py"), *(root / "tools").glob("*.py"), *(root / "notebooks").glob("*.ipynb")]
    assert len(files) > 10
    for f in files:
        text = f.read_text(encoding="utf-8")
        for word in ("AIRequiredError", "ai_required_box", "unplaced_box", "unplaced_text", '"ai_modes"'):
            assert word not in text, (f.name, word)
    assert "ai_modes" not in report.STEP_NAMES


def test_result_boxes_follow_actions(journal, tmp_path, monkeypatch):
    """手順 5・6・8 の枠は report.actions からまとめて作る（colab.result_boxes）: J-STAGE のアップロード時チェック、
    DTD 検証の不合格、AI のエラー（推奨の手順 ai_finish の「失敗」。手動モードと API モードで直し方を書き分ける）。"""
    from conftest import FULL

    from jasme_jats.report import actions, blocking

    from jasme_jats import pipeline
    from jasme_jats.ai_assist import AIOutcome
    from jasme_jats.colab import result_boxes
    from jasme_jats.config import ArticleMeta
    from jasme_jats.pipeline import Options, convert
    meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12", "pub_date": "2026-03-31",
                                  "received": "2026-01-10", "accepted": "2025-11-20", "peer_review": "あり"})
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path / "j"))
    html = result_boxes(res)
    assert "#dc2626" in html and "J-STAGE のアップロード時チェックで問題が 1 件あります（要対応）" in html
    assert "EMSGM106E" in html and "手順 3" in html
    # 要確認は、空白のない和文の著者名（d11「研究次郎」）の name_split だけ（C064）
    assert result_boxes(res, level="要確認", skip=("name_split",)) == ""
    assert "著者名の姓と名の分け方を確かめてください（要確認）" in result_boxes(res, level="要確認")
    res.dtd_valid, res.dtd_errors = False, ["31_1.xml:3: Element body content does not follow the DTD"]
    html = result_boxes(res)
    assert "J-STAGE 指定の DTD による検証が不合格です（1 件。要対応）" in html and "Element body content" in html
    good = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "peer_review": "あり"})
    res = convert(FULL, good, journal, Options(out_dir=tmp_path / "m", ai_mode="manual", ai_response="読めない回答"))
    html = result_boxes(res)
    # 読めない回答・API の失敗は、推奨の手順 ai_finish の「失敗」（見出しが赤字の青い枠。要対応ではない。修正計画 W8 の 4.3）
    assert "手順（推奨）: AI の回答を反映できませんでした" in html and "#b91c1c" in html
    assert "回答のコードブロックの中身だけを手順 6 で貼り付け直してください。" in html
    assert "AI の回答をまだ反映していません" not in html            # 回答を貼り付けた後は「回答待ち」ではない
    # API モード: 偽の呼び出しがエラーを返す
    monkeypatch.setattr(pipeline, "call_provider",
                        lambda *a, **k: AIOutcome(mode="api", model="claude-test", error="API の利用制限に達しました"))
    res = convert(FULL, good, journal, Options(out_dir=tmp_path / "a", ai_mode="api", ai_api_key="k"))
    html = result_boxes(res)
    assert "手順（推奨）: AI の回答を反映できませんでした" in html and "API の利用制限に達しました" in html
    assert "変換の結果は、AI を使わないときと同じです。" in html
    report = res.report_path.read_text(encoding="utf-8")
    assert not res.needs_action or [a.key for a in blocking(actions(res))] == ["images"]
    assert "AI による仕上げは行えませんでした: API の利用制限に達しました" in report.split("## 2.")[1].split("## 3.")[0]


def test_result_boxes_before_answer_in_manual_mode(journal, meta, tmp_path):
    """手動モードで回答を貼り戻す前: 手順 5 では依頼文の枠があるので回答待ちの枠を出さず（skip）、手順 8 の止める枠
    （blocking）にも出さない（推奨の手順は止めない）。全部の枠には青い枠（手順）で出す。"""
    from conftest import FLOAT

    from jasme_jats.colab import result_boxes
    from jasme_jats.pipeline import Options, convert
    from conftest import fill_images
    res = convert(FLOAT, meta, journal, Options(out_dir=tmp_path, ai_mode="manual"))
    fill_images(res)                                         # 図の画像の手順（必須）を済ませる
    assert result_boxes(res, skip=("ai_finish", "images")) == ""
    assert result_boxes(res, level="要対応") == ""
    assert result_boxes(res, blocking=True) == ""           # 手順 8 は、回答待ちでは止めない
    html = result_boxes(res)
    assert "手順（推奨）: AI で図・表の位置を合わせる（残り 3 個）" in html and "手順 6" in html
    assert "#2563eb" in html and "#eff6ff" in html


def test_result_boxes_show_textbox_notices(journal, meta, tmp_path):
    """文字だけのテキストボックスの知らせ（囲みか図の注記か決められなかったもの・位置を推定した囲み。どちらも要確認）も、
    report.actions に足しただけで手順 5・6・8 の枠に出る（表示の仕組みは変えない。修正計画の F）。手動モードで回答を
    貼り戻す前は、決められないテキストボックスを AI の回答で判断することを、回答待ちの枠にも書く。"""
    from conftest import STRUCTURE

    from jasme_jats.colab import result_boxes
    from jasme_jats.pipeline import Options, convert
    res = convert(STRUCTURE, meta, journal, Options(out_dir=tmp_path / "n"))
    html = result_boxes(res, level="要確認")
    assert "囲みか図の注記か決められなかったテキストボックスが 3 件あります（要確認）" in html
    assert "#d97706" in html and "#dc2626" not in html             # 要確認は黄色い枠
    assert "テキストボックスの外（本文の段落）に出してから変換し直してください" in html and "位置を推定して置いた囲みが 1 件あります（要確認）" in html
    assert "AI による補完" not in html and "AI による仕上げ" not in html         # AI を勧める文は推奨の手順 ai_finish の枠だけ（修正計画 W8 の手順 7）
    assert result_boxes(res, level="要対応") == ""
    res = convert(STRUCTURE, meta, journal, Options(out_dir=tmp_path / "m", ai_mode="manual"))
    html = result_boxes(res)
    # 回答待ちの推奨の手順 ai_finish にも、決められないテキストボックスを AI が判断することを書く（冒頭の手動モードの説明はなくした）
    assert "囲みか図の注記か決められないテキストボックス 3 個の文字は、XML に出していません。AI が種類を判断します。" in html


# ---------------------------------------------------------------------------- 画面の操作の目印（O2）
def test_step_words_cover_every_mark_in_report():
    """report.py が使う目印の名前と、colab.STEP_WORDS の両方の画面の語がそろっている。知らない目印・画面は例外。"""
    import re
    from pathlib import Path

    import pytest

    from jasme_jats import app, pipeline, report
    from jasme_jats.colab import STEP_WORDS, step_text
    assert set(STEP_WORDS) == {"notebook", "app", "cli"}
    for screen, words in STEP_WORDS.items():
        assert set(words) == set(report.STEP_NAMES), screen
        assert all("\x00" not in w and ("手順" not in w or screen == "notebook") for w in words.values())
    used = set()
    for module in (report, pipeline, app):    # 目印は report.py・pipeline.py（StructureConflictError の文）・app.py（CRASH_ADVICE）で使う
        used |= set(re.findall(r"step\((?:'|\")(\w+)(?:'|\")\)", Path(module.__file__).read_text(encoding="utf-8")))
    assert used == set(report.STEP_NAMES)                 # 使っていない目印・表にない目印がない
    assert step_text(report.step("docx") + "から", "notebook") == "手順 2 から"     # 1ffed92 までの文と同じ（助詞の前の空白）
    assert step_text(report.step("pdf") + "で選んだ", "notebook") == "手順 2 で選んだ"
    assert step_text(report.step("images") + "で、", "notebook") == "手順 7「図の画像を入れる」で、"
    assert step_text(report.step("docx") + "、", "notebook") == "手順 2、"
    assert step_text(report.step("docx") + "から", "app") == "「docx（論文の Word ファイル）」の欄から"
    assert step_text(report.step("docx") + "から", "cli") == "docx の指定から"
    assert step_text("目印なし", "app") == "目印なし"
    with pytest.raises(ValueError, match="知らない目印"):
        step_text("\x00step:nothing\x00")
    with pytest.raises(ValueError, match="知らない目印"):
        report.step("nothing")
    with pytest.raises(ValueError, match="知らない画面"):
        step_text("x", "other")


def test_report_text_names_no_step_number_outside_marks():
    """report.py の文（コメント以外の文字列）に、手順の番号を直接書かない（box_detail は目印で書く）。レポートの文（top・checklist）に
    書くときは、ノートブックと 1 画面版の両方の利用者に通じるよう「ノートブックは手順 N、1 画面版は…」の形にする。"""
    import io
    import re
    import tokenize
    from pathlib import Path

    from jasme_jats import report
    text = Path(report.__file__).read_text(encoding="utf-8")
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type == tokenize.STRING and tok.string.lstrip("rbf")[:3] not in ('"""', "'''"):      # docstring は対象外
            for m in re.finditer(r"手順 \d", tok.string):
                assert tok.string[:m.start()].endswith("ノートブックは"), f"report.py:{tok.start[0]}: {tok.string}"


def test_no_mark_left_in_any_screen(journal, meta, tmp_path):
    """いろいろな結果の actions() のすべての Action で、両方の画面の枠に目印が残らない。1 画面版の枠には手順の番号も出ない。
    レポート（.md）と top・checklist・cli の文にも目印は出ない。make_notebook.py が使う box_detail も、置き換えれば目印は残らない。"""
    from conftest import EDGE, FLOAT, FULL, OUTSIDE, PDFCHECK, PDFCHECK_PDF, PLACE, STRUCTURE, TABLEFIG

    from jasme_jats.colab import lost_images_box, missing_images_box, pdf_diff_box, result_boxes, step_text
    from jasme_jats.pipeline import Options, convert
    from jasme_jats.report import actions
    cases = [(docx, Options(out_dir=tmp_path / f"c{k}{mode}", ai_mode=mode))
             for k, docx in enumerate([FULL, EDGE, FLOAT, PLACE, OUTSIDE, STRUCTURE, TABLEFIG]) for mode in ("none", "manual")]
    cases += [(PDFCHECK, Options(out_dir=tmp_path / f"p{route}", ai_mode="none",
                                 pdf_path=PDFCHECK_PDF, route=route)) for route in ("docx", "pdf")]
    seen = set()
    for docx, opts in cases:
        res = convert(docx, meta, journal, opts)            # AI を使わない設定でも中止しない
        assert "\x00" not in res.report_path.read_text(encoding="utf-8")
        for a in actions(res):
            seen.add(a.key)
            assert not any("\x00" in t for t in (a.top, a.checklist, a.cli)), a.key
            for screen in ("notebook", "app", "cli"):
                assert "\x00" not in step_text(a.box_title, screen) + step_text(a.box_detail, screen), a.key
            for screen in ("app", "cli"):
                assert not re.search(r"手順 ?\d", step_text(a.box_detail, screen) + step_text(a.box_title, screen)), a.key
        for screen in ("notebook", "app"):
            html = result_boxes(res, screen=screen) + missing_images_box(res, screen) + lost_images_box(res, screen) \
                + pdf_diff_box(res, screen)
            assert "\x00" not in html, screen
            assert screen == "notebook" or not re.search(r"手順 ?\d", html)      # 青い枠の見出し「手順:」は区分の名前
    assert {"ai_finish", "textbox_undecided"} <= seen      # 目印を使う知らせを実際に通した


def test_app_screen_words_in_boxes(journal, meta, tmp_path):
    """同じ Action の文を、ノートブックでは手順の番号で、1 画面版では欄の名前で読む。"""
    from conftest import FLOAT

    from jasme_jats.colab import result_boxes
    from jasme_jats.pipeline import Options, convert
    res = convert(FLOAT, meta, journal, Options(out_dir=tmp_path, ai_mode="manual"))
    note = result_boxes(res, level="手順")
    page = result_boxes(res, level="手順", screen="app")
    assert "手順 5 の依頼文を AI" in note and "手順 6 に貼り付けて ▶ を押してください" in note
    assert "依頼文を AI" in page and "「AI の回答（json のコードブロック）を貼り付ける」の欄に貼り付けて「反映」を押してください" in page \
        and not re.search(r"手順 ?\d", page)


def test_mark_lookalike_in_docx_text_is_shown_as_is(tmp_path, journal, meta, monkeypatch):
    """docx の文字（段落の抜粋）に {{step:docx}}・{{step:x}} の形があっても、目印とは読まれない（F2）。書き換わらず、例外にならない。
    PDF の文字の U+0000 は、枠に入らない（目印の区切りと紛れない）。"""
    from test_pdfmatch import N10_TAIL, SMALL_FRONT, TALK, body_lines, convert_with_pages, n10_article, n10_pages

    from jasme_jats.colab import result_boxes
    from jasme_jats.report import actions
    for word in ("{{step:docx}}", "{{step:x}}"):
        docx = f"授業の最初に確認した値の{word}あ後ろで，生徒は話し合いを続け，その様子を記録した。"
        pub = f"授業の最初に確認した値の{word}\x00後ろで，生徒は話し合いを続け，その様子を記録した。"
        out = tmp_path / word[7:-2]
        out.mkdir()
        n10_article(out, journal, [("body", docx), ("body", TALK)])
        pages = n10_pages([*SMALL_FRONT, *body_lines(pub), *body_lines(TALK), *N10_TAIL])
        res = convert_with_pages(out, monkeypatch, journal, meta, pages, "docx", docx=out / "n10.docx")
        assert any("step:" in a.box_detail for a in actions(res))        # 抜粋が枠に出る（抜粋は途中で切れることがあるので、中ほどで見る）
        tail = word[3:]                                                   # "step:docx}}" / "step:x}}"
        for screen in ("notebook", "app", "cli"):
            html = result_boxes(res, screen=screen)         # 例外にならない
            assert tail in html and "\x00" not in html, screen
            assert "手順 2}}" not in html and "欄}}" not in html and "指定}}" not in html     # 抜粋の中の並びは語に書き換わらない


def test_ai_required_message_names_the_modes_of_each_screen(journal, meta, tmp_path, capsys):
    """AI を使わない設定で図表の位置を決められないとき、変換は中止せず（修正計画 W8 の決定 4）、推奨の手順 ai_finish の文に、画面ごとの
    選択肢の名前が出る（F5。ノートブックは手順 4 の名前、1 画面版は app.AI_MODES の名前、コマンドラインは --ai の指定）。目印が残らない。"""
    from conftest import FLOAT, META_EXAMPLE, image_folder

    from jasme_jats import app
    from jasme_jats.cli import main
    from jasme_jats.colab import step_text
    from jasme_jats.pipeline import Options, convert
    from jasme_jats.report import actions
    res = convert(FLOAT, meta, journal, Options(out_dir=tmp_path / "a"))
    fin = next(a for a in actions(res) if a.key == "ai_finish")
    note = step_text(fin.box_detail)                                # ノートブック（既定）
    assert ("手順 4 で AI による仕上げの方法を「API で自動実行」か「手動（チャットに貼り付け）」にして ▶ を押し、手順 5 から"
            "変換し直してください。") in note and "\x00" not in note
    page = step_text(fin.box_detail, "app")
    labels = [label for label, _ in app.AI_MODES]
    assert "「AI による仕上げの方法」の欄を「手動（チャットに貼り付け）」か「API（Claude）」にして「" in page
    assert "手動（チャットに貼り付け）" in labels and "API（Claude）" in labels             # 画面の選択肢の名前と同じ
    assert "API で自動実行" not in page and "\x00" not in page
    st = app.AppState(tmp_path / "work")
    st.set_inputs(route="docx", docx=str(FLOAT), volume="31", issue="1", fpage="1", lpage="12", peer_review="査読あり",
                  manuscript_type=app.type_choices()[0], ai_mode="none")
    st.convert()                                                    # 1 画面版も中止しない
    assert st.res is not None and "ai_finish" in [a.key for a in actions(st.res)]
    assert "#dc2626" not in st.result_html()                        # 「使わない」を選んでも赤い枠は出ない（W8 の手順 4）
    pics = image_folder(tmp_path / "pics", [i.key for i in res.images if i.status == "missing"])
    capsys.readouterr()
    assert main([str(FLOAT), "--meta", str(META_EXAMPLE), "--out", str(tmp_path / "cli"), "--ai", "none", "--images", str(pics)]) == 0
    err = capsys.readouterr().err
    assert "--ai manual か --ai api を指定して変換し直すと" in err and "\x00" not in err and "API で自動実行" not in err


def test_notebook_sentences_equal_those_before_marks(journal, meta, tmp_path):
    """ノートブックの枠の文は、目印にする前（1ffed92）の文と一字一句同じ（助詞の前の空白、「アップロードし直し」など）。
    1ffed92 と今の両方で fixtures の変換結果の全 Action の box_detail を作って比べた確かめの代表（F3）。"""
    from conftest import OUTSIDE, PDFCHECK, PDFCHECK_PDF, STRUCTURE

    from jasme_jats.colab import result_boxes
    from jasme_jats.pipeline import Options, convert
    res = convert(PDFCHECK, meta, journal, Options(out_dir=tmp_path / "p", pdf_path=PDFCHECK_PDF,
                                                   route="docx"))
    assert ("校正の直しを補うときは、手順 2 で「docx から作り、出版版 PDF で補う」を選んで変換し直すか、docx を直して"
            "手順 2 からやり直してください。") in result_boxes(res)
    res = convert(OUTSIDE, meta, journal, Options(out_dir=tmp_path / "o", ai_mode="manual"))
    assert "Word で直した docx を手順 2 でアップロードし直し、そこから順にやり直してください" in result_boxes(res)
    res = convert(STRUCTURE, meta, journal, Options(out_dir=tmp_path / "s", ai_mode="manual"))
    assert "手順 6 に貼り付けて ▶ を押してください" in result_boxes(res)      # 回答待ちの ai_finish（目印 paste）


def _html_text_and_tags(html):
    from html.parser import HTMLParser

    class P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.text, self.tags = [], []

        def handle_starttag(self, tag, attrs):
            self.tags.append(tag)

        def handle_data(self, data):
            self.text.append(data)
    p = P()
    p.feed(html)
    return "".join(p.text), p.tags


def test_report_details_shows_angle_brackets(journal, meta, tmp_path):
    """0.29.0 の最後の点検: レポートに引用した docx の文字に「x<y>z」「<y かつ z>」「<b>」のような、タグに見える並びがあっても、
    「変換レポートの全文を見る」（Markdown → HTML）で文字が消えない。.md の文字は docx のまま。ツールのタグ（md_tag でコードにしたもの）は
    今までどおりコードで出る。"""
    import make_fixtures as mf
    from conftest import ALL_DOCS, FLOAT, FLOAT_TEXT, OUTSIDE, PLACE

    from jasme_jats.colab import markdown_text_only, report_details
    from jasme_jats.pipeline import Options, convert
    S = mf.S
    md = ("# 変換レポート\n\n> **要確認**: 「x<y>z」「<y かつ z>」「<b>」「a&amp;b」「<http://example.org>」 と `<xref>` と "
          "`<fig id=\"…\">`\n\n- 引用: 「<i>強調」\n\n```\n<pre>の中の <b> は文字のまま\n```\n\n| 項目 | 結果 |\n|---|---|\n| x<y | <z> |\n")
    text, tags = _html_text_and_tags(report_details(md))
    for s in ("x<y>z", "<y かつ z>", "<b>", "a&amp;b", "<http://example.org>", "<xref>", '<fig id="…">', "<i>強調", "<pre>の中の <b> は文字のまま",
              "x<y", "<z>"):
        assert s in text, s
    assert set(tags) <= {"style", "details", "summary", "div", "h1", "blockquote", "p", "strong", "code", "ul", "li", "pre", "table",
                         "thead", "tbody", "tr", "th", "td"}, tags
    assert "<code>&lt;xref&gt;</code>" in report_details(md)           # ツールのタグはコードのまま
    # 実際の docx の経路: 引用文献の段落の文字がレポートの 10 章の警告などに載り、Colab の全文表示で消えない
    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "架空の主張である。"),
                mf.table([[mf.cell(mf.para(S["body"], "表の", mf.br(), "セル"))]])]
    path = tmp_path / "x.docx"
    mf.make_article(path, "t", parts, refs=lambda b: [mf.para(S["ref"], "x<y>z", mf.br(), "続き")])
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    rep = res.report_path.read_text(encoding="utf-8")
    assert "x<y>z" in rep                                               # .md の文字は docx のまま
    text, _ = _html_text_and_tags(report_details(rep))
    assert "x<y>z" in text and "xz" not in text.replace("x<y>z", "")
    # レポートは生の HTML を使わない: すべての fixture のレポートで、生の HTML を無効にして HTML にしても、無効にしない場合と同じ
    # （違うのは docx の文字にタグ・実体参照に見える並びがあるときだけ）。許す要素を限る必要がない
    import markdown
    checked = 0
    for docx in ALL_DOCS + [FLOAT, FLOAT_TEXT, PLACE, OUTSIDE]:
        for mode in ("none", "manual"):
            r = convert(docx, meta, journal, Options(out_dir=tmp_path / f"r{checked}", ai_mode=mode))
            checked += 1
            rep = r.report_path.read_text(encoding="utf-8")
            assert markdown_text_only(rep) == markdown.markdown(rep, extensions=["tables", "fenced_code"]), (docx.name, mode)
    assert checked >= 15


def test_structure_conflict_box_and_text(journal, tmp_path):
    """原稿の構造の衝突（K1・K2）で変換を中止するときの枠（赤）と文: 3 つの画面（ノートブック・1 画面版・コマンドライン）で画面の操作の
    目印が語に置き換わって残らない。すべての衝突の段落 ID と抜粋が文にあり、種類ごとの直し方（注見出し・注本文、所属の欄、
    間に別の節があるときだけ「移して」）が書かれる。"""
    from test_structure import CONFLICT_DOCS, CONFLICT_KINDS, conflict_doc

    from jasme_jats.colab import structure_conflict_box
    from jasme_jats.pipeline import _mechanical
    from jasme_jats.report import structure_conflict_text
    for name in CONFLICT_DOCS:
        _, plan, _ = _mechanical(conflict_doc(tmp_path, name), journal)
        msg = structure_conflict_text(plan)
        assert "変換を中止しました" in msg and f"箇所が {len(plan.structure_conflicts)} か所ある" in msg
        for c in plan.structure_conflicts:
            for src in [c.lost[0]] + ([c.by] if c.by else []):          # 節は最初の段落と置き換えた見出しの抜粋、最後の段落の ID
                text = plan.paras[src].text_only().strip()
                assert f"{src}「{text}」" in msg, (name, src)
            assert c.lost[-1] in msg
        for screen, word in (("notebook", "手順 2 から"), ("app", "「docx（論文の Word ファイル）」の欄から"),
                             ("cli", "docx の指定から")):
            box = structure_conflict_box(msg, screen)
            assert "#dc2626" in box and "原稿の構造を直す必要があります（変換を中止しました）" in box, (name, screen)
            assert word in box and "\x00" not in box and "step:" not in box, (name, screen)
        kind = CONFLICT_KINDS[name]
        body = msg.split("\n", 1)[1]
        if kind[0] == "fn_heading":
            assert "「注見出し」スタイルにし" in body and "「注本文」スタイル" in body
        if kind[0] == "aff":
            if kind[3] == "table":
                assert "所属の欄" in body
            elif kind[2]:
                assert "所属の欄" in body and "テンプレートの著者表" in body
            else:
                assert "最後の所属の段落" in body and "著者名の段落のすぐ前に移して" in body and "テンプレートの著者表" in body
        if kind[0] in ("ref_heading", "fn_heading", "notes", "ack"):
            assert ("移して" in body) == kind[5], name        # 間に別の節があるときだけ「移して」
        assert "set_role" not in msg and "不具合" not in msg


def test_every_box_is_light_with_important_colors(journal, meta, tmp_path):
    """白地の枠はすべて jasme-light のクラスと <style> を持ち、色の指定は !important（ダークモードでも白地に暗い文字）。"""
    import re
    from jasme_jats.colab import (LIGHT_STYLE, check_box, next_article_box, report_details, structure_conflict_box,
                                  summary_box)
    from jasme_jats.pipeline import Options, convert
    from conftest import FULL
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path / "s"))
    boxes = [error_box("見出し", "詳細"), check_box("見出し", "詳細"), prompt_box("依頼文"),
             structure_conflict_box("x"), next_article_box("a.docx"), summary_box(res),
             report_details("# 見出し\n\n本文")]
    for h in boxes:
        assert "class='jasme-light'" in h and LIGHT_STYLE in h
        assert re.search(r"\.jasme-light div[^{]*\{color:#1f2937 !important\}", h)
        outside = h.replace(LIGHT_STYLE, "")
        # インラインの color（border-color・background-color 以外）は、すべて !important つき
        for m in re.finditer(r"(?<![-\w])(color|background):[^;'\"]*", outside):
            assert "!important" in m.group(0), m.group(0)
