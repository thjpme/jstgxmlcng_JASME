"""手動モードの画面（修正計画 W8 の手順 23。4.5）: 依頼文の枠の案内（出版版 PDF の添付・任意であること）、画面の操作の目印 pdf_attach、
コマンドラインの既定の --ai manual、API の費用の文。AI は呼ばない。"""
import re
from pathlib import Path

import pytest

from conftest import FLOAT, FULL, META_EXAMPLE
from jasme_jats import app, colab, report
from jasme_jats.cli import main
from jasme_jats.colab import STEP_WORDS, ai_finish_of, manual_guide, prompt_box
from jasme_jats.pipeline import Options, convert


def waiting(journal, meta, tmp_path, docx=FLOAT, pdf=None):
    return convert(docx, meta, journal, Options(out_dir=tmp_path / "w", ai_mode="manual", pdf_path=pdf))


def test_prompt_box_guides_with_pdf_attach(journal, meta, tmp_path):
    """位置を聞く図形がある論文: 枠の見出しと最初の説明は ai_finish の Action のもの、2 の手順に出版版 PDF を添付する案内がある。"""
    res = waiting(journal, meta, tmp_path)
    act = ai_finish_of(res)
    assert act is not None and act.box_intro and act.box_intro in act.box_detail
    html = prompt_box("依頼文 <b>", act, "notebook", "29_55.pdf")
    assert colab.step_text(act.box_title) in html and colab.step_text(act.box_intro) in html          # 同じ文を 2 か所に書かない
    assert "出版版 PDF を同じメッセージに添付して" in html and "29_55.pdf" in html
    assert "手順 6 に貼り付けて ▶ を押します。" in html and "依頼文をコピー" in html and "依頼文 &lt;b&gt;" in html
    assert "\x00" not in html
    # PDF がツールに渡されていないときは名前を出さない
    nameless = prompt_box("x", act, "notebook", "")
    assert "この論文の出版版 PDF" in nameless and "29_55.pdf" not in nameless and "同じメッセージに添付して" in nameless
    # 回答待ちの ai_finish の本文にも、PDF の添付の案内
    assert "出版版 PDF を同じメッセージに添付して送信し" in colab.step_text(act.box_detail)


def test_prompt_box_without_floats_is_optional(journal, meta, tmp_path):
    """位置を聞く図形がない論文（ai_finish の Action がないか、PDF の添付を求めない）: 見出しは「AI の回答を入れる（任意）」、PDF の添付は求めない。"""
    res = waiting(journal, meta, tmp_path, FULL)
    assert not res.plan.asked_floats
    html = prompt_box("x", None, "notebook")
    assert "AI の回答を入れる（任意）" in html and "位置を決められない図・表はありません" in html
    assert "同じメッセージに添付して" not in html
    act = ai_finish_of(res)           # ある場合（スタイルを確かめる段落だけのとき）も PDF の添付は求めない
    if act is not None:
        assert "同じメッセージに添付して" not in prompt_box("x", act, "notebook")


@pytest.mark.parametrize("screen", ["notebook", "app", "cli"])
def test_guide_uses_marks_not_step_numbers(journal, meta, tmp_path, screen):
    """案内の文に「手順 6」などの番号を直接書かず、画面ごとの語（STEP_WORDS）に置き換える。"""
    res = waiting(journal, meta, tmp_path)
    html = manual_guide(ai_finish_of(res), screen, "29_55.pdf")
    assert STEP_WORDS[screen]["pdf_attach"] in html and "\x00" not in html
    if screen != "notebook":
        assert "手順 6" not in html and "手順 5" not in html
    if screen == "app":
        assert "「AI の回答（json のコードブロック）を貼り付ける」の欄に貼り付けて「反映」を押します。" in html
    if screen == "cli":
        assert "--ai-response" in html
    source = Path(colab.__file__).read_text(encoding="utf-8")
    start, end = source.index("COPY_STEP = "), source.index("def _notice(")
    assert not re.search(r"手順 \d", source[start:end])            # 案内を組む部品に番号が直接書かれていない


def test_app_waiting_shows_guide_instead_of_ai_finish(tmp_path):
    """1 画面版の手動の回答待ち: ai_finish の枠の代わりに案内（なぜ・任意か・PDF の添付）を出す。位置を聞く図形がなくても、任意の案内を出す。"""
    st = app.AppState(tmp_path / "work")
    st.set_inputs(route="docx", docx=str(FLOAT), volume="31", issue="1", fpage="1", lpage="12", peer_review="査読あり",
                  manuscript_type=app.type_choices()[0], ai_mode="manual")
    st.convert()
    assert st.waiting_for_answer
    boxes = st.result_html().split("<details")[0]
    assert "強く推奨" in boxes and "このまま登載することもできます" in boxes
    assert "出版版 PDF を同じメッセージに添付して" in boxes and boxes.count("AI で図・表の位置を合わせる") == 1
    assert "手順 6" not in boxes
    st2 = app.AppState(tmp_path / "work2")
    st2.set_inputs(route="docx", docx=str(FULL), volume="31", issue="1", fpage="1", lpage="12", peer_review="査読あり",
                   manuscript_type=app.type_choices()[0], ai_mode="manual")
    st2.convert()
    assert "AI の回答を入れる（任意）" in st2.result_html().split("<details")[0]


def test_app_texts_for_api(tmp_path):
    """API のときの費用の文は ai_assist.cost_note（DEFAULT_MODEL_INFO の per_run_usd）から作り、ノートブックと同じ。変換中の文は PDF も送ることを言う。"""
    from jasme_jats.ai_assist import cost_note
    assert "ドル" in cost_note() and "前の回答を使うので料金はかかりません" in cost_note()
    st = app.AppState(tmp_path / "work")
    st.set_inputs(ai_mode="api", pdf=str(FULL))
    assert "AI に依頼文と出版版 PDF を送って" in st.convert_note()
    st.set_inputs(ai_mode="api", pdf=None)
    note = st.convert_note()
    assert "AI に依頼文を送って" in note and "PDF" not in note
    st.set_inputs(ai_mode="manual")
    assert st.convert_note() == "変換中…（数分かかることがあります）"


def test_cli_defaults_to_manual(tmp_path, capsys):
    """--ai の指定がなくても依頼文 AI依頼文.txt を書き出し、終了コードは AI を使わないときと同じ（回答待ちは推奨の手順）。"""
    out = tmp_path / "o"
    code = main([str(FLOAT), "--meta", str(META_EXAMPLE), "--out", str(out)])
    cap = capsys.readouterr()
    assert (out / "AI依頼文.txt").exists()
    assert "出版版 PDF を一緒に渡して送信し、返ってきた回答を保存して --ai manual --ai-response で指定する" in cap.out
    assert "AI 依頼文:" in cap.out and code in (0, 1)
    code_none = main([str(FLOAT), "--meta", str(META_EXAMPLE), "--out", str(tmp_path / "n"), "--ai", "none"])
    assert code == code_none and not (tmp_path / "n" / "AI依頼文.txt").exists()
    assert "出版版 PDF と一緒に" in cap.err or "AI依頼文.txt" in cap.err        # 標準エラーの手順（推奨）にも依頼文の渡し方
    # 位置を聞く図形がない論文: PDF の案内は出さない
    main([str(FULL), "--meta", str(META_EXAMPLE), "--out", str(tmp_path / "f")])
    assert "一緒に渡して" not in capsys.readouterr().out


def test_report_waiting_text_has_pdf_only_with_floats(journal, meta, tmp_path):
    """回答待ちの ai_finish の本文: 位置を聞く図形があるときだけ PDF の添付（目印 pdf_attach）を書く。"""
    mark = report.STEP_MARK + "step:pdf_attach" + report.STEP_MARK
    assert mark in ai_finish_of(waiting(journal, meta, tmp_path)).box_detail
    res = waiting(journal, meta, tmp_path / "x", FULL)
    act = ai_finish_of(res)
    assert act is None or mark not in act.box_detail


def test_notebook_step5_shows_guide_box_once(monkeypatch, tmp_path):
    """ノートブックの手順 5（手動）: 依頼文の枠に、ai_finish の見出し・説明と PDF の添付の案内を出し、ai_finish の枠を重ねて出さない。"""
    from test_notebook import cell_source, fake_display

    from jasme_jats.config import ArticleMeta, JournalConfig
    shown = fake_display(monkeypatch)
    meta_input = {"volume": "31", "issue": "1", "fpage": "1", "lpage": "12", "peer_review": "あり"}
    ns = {"DONE": {1, 2, 3, 4}, "AI": "manual", "PROVIDER": "claude", "API_MODEL": "x", "WORK": tmp_path, "meta_input": meta_input,
          "docx_path": FLOAT, "pdf_path": None, "ROUTE_KEY": "docx", "SPLIT_LABELS": None}
    exec(cell_source("#@title 5."), ns)
    page = "".join(x for x in shown if isinstance(x, str))
    assert page.count("AI で図・表の位置を合わせる（残り 3 個）") == 1       # 依頼文の枠の見出しだけ（ai_finish の枠は出さない）
    assert "出版版 PDF を同じメッセージに添付して" in page and "手順 6 に貼り付けて ▶ を押します。" in page
    assert 5 in ns["DONE"] and ArticleMeta and JournalConfig
