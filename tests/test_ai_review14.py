"""点検 review14 の指摘の直し（W8）。内容は架空。本物の API は呼ばない（偽の call_provider・偽のクライアント）。

- 2 段にまたがる機械的な図形だけの論文でも、PDF を渡したのに見ていない回答は知らせ、AI回答.json に写さない（原則 1）。
- 2 段の図形への指定は、キャプションのある PDF のページと違えば使わない（原則 2）。途中で切れた回答の理由（原則 5）。
- 応答のモデル名が違うだけでは「安全上の判定で断られた」と書かない（原則 3）。
- 位置を聞いた図形が組み直しで本文に移っても、wide にしない（原則 6）。
- 1 画面版の「押すると」（利用者向け 1）、手動の案内の枠の色と見出し（2）、14 章の行（3）、2 段の図形の数と説明（4・5）、
  style_check の直し方の文（8）。
"""
import json
import types

import answers
from conftest import CELLS, PLACE
from jasme_jats import ai_assist, colab, pipeline, report
from jasme_jats.ai_assist import ANSWER_FILE, WIDE_CUT_WHY, WIDE_PAGE_WHY, WIDE_UNSEEN_WHY, AIOutcome
from jasme_jats.pipeline import Options, _mechanical, convert
from test_ai_pdf import make_pdf
from test_ai_pdf_seen import pages_of
from test_ai_review13 import _fake_claude, api_opts, fake_api, finish
from test_ai_wide import _answer, _manual, _target


def _acts(res):
    return {a.key: a for a in report.actions(res)}


def test_wide_only_unseen_answer_with_pdf_sent_is_told_and_not_kept(journal, meta, tmp_path, monkeypatch):
    """原則 1: 位置を聞く図形がなく、2 段にまたがる機械的な図形だけの論文（CELLS）で、API で PDF を渡したのに「添付なし」の回答は、
    推奨の手順 ai_finish（PDF を見ていない）で知らせ、AI回答.json に写さない。もう一度変換すると AI を呼び直す。"""
    base = convert(CELLS, meta, journal, Options(out_dir=tmp_path / "base", ai_mode="manual"))
    after = _target(base.plan, "s1")
    resp = _answer(CELLS, [("s1", after)], status="添付なし")
    pdf = make_pdf(tmp_path / "x.pdf", 1)
    calls = fake_api(monkeypatch, resp)
    res = convert(CELLS, meta, journal, api_opts(tmp_path / "out", pdf_path=pdf))
    assert res.plan.asked_floats == [] and res.plan.floats["s1"].mode == "mechanical"
    assert [w for _, w in res.ai.rejected] == [WIDE_UNSEEN_WHY.format(fid="s1", seen="添付なし")]
    assert report.ai_state(res) == "済み" and report.pdf_unseen(res) and not report.ai_done(res)
    assert res.ai_answer_path is None and not (tmp_path / "out" / ANSWER_FILE).exists()
    fin = finish(res)
    assert fin.box_title == report.AI_PDF_TITLE and not fin.done
    assert fin.box_detail.startswith("AI の回答を反映しましたが、出版版 PDF は AI に渡したのに、PDF を見ていない回答でした。")
    assert "2 段にまたがる図形 2 個（" in fin.box_detail and "機械的に決めた位置のままです" in fin.box_detail
    assert "図・表 0 個" not in fin.box_detail + fin.checklist + fin.cli
    assert "もう一度変換して、AI を呼び直す" in fin.checklist
    res2 = convert(CELLS, meta, journal, api_opts(tmp_path / "out2", pdf_path=pdf))
    assert len(calls) == 2 and not res2.ai.reused
    # PDF を見た回答は写し、使い回す（2 段の図形も AI の位置に移る。14 章の済みの行に数を添える）
    calls = fake_api(monkeypatch, _answer(CELLS, [("s1", after)], status="見た", pages=1))
    res3 = convert(CELLS, meta, journal, api_opts(tmp_path / "out3", pdf_path=pdf))
    assert res3.plan.floats["s1"].mode == "ai" and report.ai_done(res3) and res3.ai_answer_path is not None
    done = finish(res3)
    assert done.done and "（ほかに、2 段にまたがる図形 1 個（" in done.checklist and "を PDF の位置に移した）" in done.checklist


def test_wide_only_waiting_box_asks_for_pdf(journal, meta, tmp_path):
    """利用者向け 4・5: 2 段の図形だけの論文の手動の回答待ちでも、推奨の手順 ai_finish を出し、枠・【作業する方へ】・コマンドラインで
    出版版 PDF の添付を求める（NO_FLOATS_INTRO の「任意」にしない）。"""
    res = convert(CELLS, meta, journal, Options(out_dir=tmp_path, ai_mode="manual"))
    fin = finish(res)
    assert fin.box_title == report.AI_FINISH_TITLE and not fin.done
    assert "2 段にまたがる図形 2 個（" in fin.box_intro and "出版版と同じ位置に移せます" in fin.box_intro
    assert report.step("pdf_attach") in fin.box_detail and "出版版 PDF と一緒に" in fin.cli
    assert "出版版 PDF を同じメッセージに添付して" in fin.checklist
    html = colab.manual_guide(fin, "notebook")
    assert colab.NO_FLOATS_INTRO not in html and "強く推奨" in html
    assert "（強く推奨）" in res.prompt_path.read_text(encoding="utf-8")


def test_wide_page_must_match_caption_page(journal, meta, tmp_path, monkeypatch):
    """原則 2: PDF を見た回答でも、2 段の図形への指定の page が、キャプションがちょうど 1 ページだけに見つかる PDF のページと違えば
    使わない（pdf_seen には数えない。総ページ数だけ当てた回答で 2 段の図形を動かさない）。ページが合えば使う。"""
    _, plan, _ = _mechanical(CELLS, journal)
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    pages_of(plan, {"s1": 1}, 2, monkeypatch)
    base = convert(CELLS, meta, journal, Options(out_dir=tmp_path / "base", ai_mode="manual"))
    after = _target(base.plan, "s1")
    resp = json.loads(_answer(CELLS, [("s1", after)], pages=2))
    resp["placements"][0]["page"] = 2
    res = convert(CELLS, meta, journal, Options(out_dir=tmp_path / "bad", ai_mode="manual",
                                                ai_response=json.dumps(resp, ensure_ascii=False), pdf_path=pdf))
    assert res.ai.pdf_seen == "見た" and res.plan.floats["s1"].mode == "mechanical"
    assert [w for _, w in res.ai.rejected] == [WIDE_PAGE_WHY.format(fid="s1", page=2, found=1)]
    assert res.xml_path.read_bytes() == base.xml_path.read_bytes() and report.ai_done(res)
    resp["placements"][0]["page"] = 1
    ok = convert(CELLS, meta, journal, Options(out_dir=tmp_path / "ok", ai_mode="manual",
                                               ai_response=json.dumps(resp, ensure_ascii=False), pdf_path=pdf))
    assert ok.ai.rejected == [] and ok.plan.floats["s1"].mode == "ai"


def test_wide_rejects_of_cut_answer_says_cut():
    """原則 5: 途中で切れた回答の 2 段の図形への指定は、「添付なし」ではなく、確かめられない理由で不採用にする。"""
    out = AIOutcome(partial="途中まで")
    specs = {"s1": {"after": "d1", "basis": "pdf", "page": 1, "wide": True, "op": {}}}
    assert ai_assist.wide_rejects(specs, out) == ["s1"] and specs == {}
    assert out.rejected[0][1] == WIDE_CUT_WHY.format(fid="s1") and "添付なし" not in out.rejected[0][1]
    # PDF を見たと確かめられても、途中で切れた回答なら使わない
    out = AIOutcome(partial="途中まで", pdf_seen="見た")
    specs = {"s1": {"after": "d1", "basis": "pdf", "page": 1, "wide": True, "op": {}}}
    assert ai_assist.wide_rejects(specs, out) == ["s1"]


def test_model_name_alone_is_not_called_a_refusal(journal, meta, tmp_path, monkeypatch):
    """原則 3: 応答の model が頼んだ名前と違っても、fallback の部がなければ「安全上の判定で断られた」と書かない（別名のモデル名で
    頼むと、解決後の ID が返ることがある）。答えたモデルの名前は記録する。"""
    _, plan, _ = _mechanical(PLACE, journal)
    text = json.dumps(answers.data(), ensure_ascii=False)
    _fake_claude(monkeypatch, [types.SimpleNamespace(type="text", text=text)], "claude-opus-5-20261101")
    out = ai_assist.call_api("system", "data", None, model="claude-opus-5", api_key="t")
    assert out.model == "claude-opus-5-20261101" and "安全上の判定" not in out.model_note
    assert out.model_note == "API の応答のモデル名は claude-opus-5-20261101（指定は claude-opus-5）"


def test_asked_float_does_not_become_wide(journal, meta, tmp_path):
    """原則 6: Classifier.place_floats は、指定があれば float_placements が wide の印を付けた指定のときだけ FloatInfo.wide を真にする
    （位置を聞いた図形の指定〈wide の印なし〉で、機械的な位置に戻っても wide にしない）。"""
    _, plan, _ = _mechanical(CELLS, journal)
    anchor = plan.floats["s1"].float.anchor_src
    # wide の印のない指定（位置を聞いた図形への指定の形）: 指定の段落が本文でなくなったときは機械的な位置に戻るが、wide にしない
    spec = {"after": "x-none", "reason": "", "confidence": "", "basis": "pdf", "page": 1, "column": "", "order": 0, "op": {}}
    _, plan2, _ = _mechanical(CELLS, journal, {}, {"s1": dict(spec)})
    assert plan2.floats["s1"].mode == "mechanical" and not plan2.floats["s1"].wide
    # wide の印のある指定は、同じ形で wide のまま
    _, plan3, _ = _mechanical(CELLS, journal, {}, {"s1": dict(spec, wide=True)})
    assert plan3.floats["s1"].mode == "mechanical" and plan3.floats["s1"].wide and anchor


def test_convert_again_reads_naturally_on_every_screen(journal, meta, tmp_path, monkeypatch):
    """利用者向け 1: PDF を渡したのに見ていない回答の案内は、どの画面の語でも「…してください」に続く（1 画面版で「押すると」にならない）。
    14 章の行も、もう一度変換して呼び直すと書く（利用者向け 3）。"""
    _, plan, _ = _mechanical(PLACE, journal)
    from test_ai_pdf_seen import place_answer
    fake_api(monkeypatch, place_answer(plan, status="添付なし"))
    res = convert(PLACE, meta, journal, api_opts(tmp_path, pdf_path=make_pdf(tmp_path / "x.pdf", 3)))
    fin = finish(res)
    for screen in ("notebook", "app", "cli"):
        text = colab.step_text(fin.box_detail, screen)
        assert "押すると" not in text and "前の回答を使わずに AI を呼び直します" in text
    assert "「変換する」をもう一度押してください。前の回答を使わずに" in colab.step_text(fin.box_detail, "app")
    assert "もう一度変換して、AI を呼び直す（前の回答は使わない。料金がかかる）" in fin.checklist
    assert "PDF を添付して AI に依頼し直す" not in fin.checklist


def test_pdf_not_sent_checklist_says_how(journal, meta, tmp_path, monkeypatch):
    """利用者向け 3: PDF を渡せなかった回答の 14 章の行は、渡せなかった理由ごとの直し方（枠・コマンドラインと同じ分け方）。"""
    _, plan, _ = _mechanical(PLACE, journal)
    from test_ai_pdf_seen import place_answer
    fake_api(monkeypatch, place_answer(plan, status="添付なし"))
    res = convert(PLACE, meta, journal, api_opts(tmp_path))
    assert res.ai.pdf_note == ai_assist.PDF_NONE_MSG
    assert "出版版 PDF を指定して、もう一度変換する" in finish(res).checklist


def test_manual_guide_is_a_blue_step_box(journal, meta, tmp_path):
    """利用者向け 2: 手動の案内の枠（ノートブックの prompt_box・1 画面版の manual_guide）は、手順の青い枠で、見出しの前に
    「手順（推奨）: 」を付ける（要確認の黄色と分ける）。推奨の手順がないとき（NO_FLOATS_TITLE）は「（任意）」の見出しのまま。"""
    res = convert(PLACE, meta, journal, Options(out_dir=tmp_path, ai_mode="manual"))
    fin = finish(res)
    for html in (colab.manual_guide(fin, "app"), colab.prompt_box("依頼文", fin)):
        assert "#2563eb" in html and "#d97706" not in html and "#fffbeb" not in html
        assert "手順（推奨）: " + fin.box_title in html
    none = colab.manual_guide(None)
    assert colab.NO_FLOATS_TITLE in none and "手順（推奨）" not in none and "#2563eb" in none


def test_style_check_how_covers_joining():
    """利用者向け 8: 要確認 style_check の直し方は、段落記号を消して段落をつなぐ提案にも当てはまる文にする。"""
    assert "段落記号を消して次の段落とつなぐ" in report.STYLE_CHECK_HOW and "段落をつないで保存" in report.STYLE_CHECK_HOW
