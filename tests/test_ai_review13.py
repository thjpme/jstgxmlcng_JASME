"""点検 review13 の利用者向けの指摘と、API の形の確かめの直し（W8）。内容は架空。本物の API は呼ばない（偽のクライアント・偽の call_provider）。

- API で出版版 PDF を渡したのに、AI が PDF を見ていない回答は AI回答.json に写さず、もう一度変換すると呼び直す（利用者向け 1）。
  PDF を渡せなかったときは、渡せなかった理由に合わせた直し方を書く。
- Claude の回答が出力の途中で別のモデルに切り替わったとき（fallbacks）、text の部をつないで読み、答えたモデルを記録する（API の形の確かめ (1)(2)）。
- ノートブックの手順 5 の並び（利用者向け 2）、費用の文（3）、手順 4 の勧め方（4）、2 章・14 章の回答待ちの文の PDF（8）、見出しの「推奨」（10）。
"""
import json
import types

from conftest import FULL, PLACE
from jasme_jats import ai_assist, pipeline, report
from jasme_jats.ai_assist import ANSWER_FILE, AIOutcome, DEFAULT_MODEL, cost_note
from jasme_jats.pipeline import Options, _mechanical, convert
from test_ai_pdf import make_pdf
from test_ai_pdf_seen import place_answer


def fake_api(monkeypatch, answer_text):
    """pipeline.call_provider を偽にする（呼ばれた回数を数える）。PDF を渡す呼び出しなら pdf_sent を "pdf" にする（call_api と同じ）。"""
    calls = []

    def fake(provider, system_text, request_text, attachment=None, model=None, api_key=None):
        calls.append(attachment)
        sent = "pdf" if attachment is not None and attachment.mode == "pdf" else ""
        return AIOutcome(mode="api", model=model or "", provider=provider, raw=answer_text, pdf_sent=sent,
                         pdf_note="" if sent else (attachment.note if attachment is not None else ""))
    monkeypatch.setattr(pipeline, "call_provider", fake)
    return calls


def api_opts(out, cache=None, **kw):
    return Options(out_dir=out, ai_mode="api", ai_api_key="t", ai_cache=cache, route="docx", **kw)


def finish(res):
    return {a.key: a for a in report.actions(res)}["ai_finish"]


def test_unseen_answer_with_pdf_sent_is_not_kept_and_called_again(journal, meta, tmp_path, monkeypatch):
    """利用者向け 1: PDF を渡したのに「添付なし」の回答は写さないので、案内どおりもう一度変換すると AI を呼び直す。
    前の写しが出力フォルダに残っていれば消す（コマンドラインが次の変換で読まない）。"""
    _, plan, _ = _mechanical(PLACE, journal)
    pdf = make_pdf(tmp_path / "x.pdf", 3)
    calls = fake_api(monkeypatch, place_answer(plan, status="添付なし"))
    out = tmp_path / "out"
    out.mkdir()
    (out / ANSWER_FILE).write_text("前の写し", encoding="utf-8")
    res = convert(PLACE, meta, journal, api_opts(out, pdf_path=pdf))
    assert res.ai.pdf_sent == "pdf" and report.pdf_unseen(res) and res.ai_answer_path is None
    assert not (out / ANSWER_FILE).exists()
    fin = finish(res)
    assert fin.box_title == report.AI_PDF_TITLE and "（推奨）" not in fin.box_title
    assert "出版版 PDF は AI に渡したのに、PDF を見ていない回答でした" in fin.box_detail
    # 「…してください」に続ける（1 画面版の語は「押」で終わる。点検 review14 利用者向け 1）
    assert report.step("convert_again") + "してください。前の回答を使わずに AI を呼び直します（料金がかかります）" in fin.box_detail
    assert "前の回答を使わずに AI を呼び直す" in fin.cli and "PDF を添付して" not in fin.box_detail
    # もう一度変換する（写しがないので cache は None）: AI を呼び直す
    res2 = convert(PLACE, meta, journal, api_opts(tmp_path / "out2", pdf_path=pdf))
    assert len(calls) == 2 and not res2.ai.reused
    # PDF を見た回答は写し、次の変換では呼ばない
    calls = fake_api(monkeypatch, place_answer(plan, status="見た", total=3))
    res3 = convert(PLACE, meta, journal, api_opts(tmp_path / "out3", pdf_path=pdf))
    assert res3.ai_answer_path is not None and report.ai_done(res3)
    cache = res3.ai_answer_path.read_text(encoding="utf-8")
    res4 = convert(PLACE, meta, journal, api_opts(tmp_path / "out4", cache=cache, pdf_path=pdf))
    assert len(calls) == 1 and res4.ai.reused


def test_unseen_answer_without_pdf_tells_how_to_send_it(journal, meta, tmp_path, monkeypatch):
    """利用者向け 1: PDF を渡せなかった回答は写してよい（PDF の渡し方が meta に入る）。直し方は理由ごと（PDF を指定する・渡す設定にする・
    手動に切り替える）。どれも「もう一度実行」だけを言わない。"""
    _, plan, _ = _mechanical(PLACE, journal)
    fake_api(monkeypatch, place_answer(plan, status="添付なし"))
    res = convert(PLACE, meta, journal, api_opts(tmp_path / "a"))
    fin = finish(res)
    assert res.ai.pdf_sent == "" and res.ai_answer_path is not None
    assert f"{ai_assist.PDF_NONE_MSG}" in fin.box_detail and report.step("pdf") + "で出版版 PDF を指定して" in fin.box_detail
    assert "--pdf で出版版 PDF を指定して" in fin.cli
    pdf = make_pdf(tmp_path / "x.pdf", 3)
    res = convert(PLACE, meta, journal, api_opts(tmp_path / "b", pdf_path=pdf, ai_send_pdf=False))
    fin = finish(res)
    assert ai_assist.PDF_OFF_MSG in fin.box_detail and "--ai-no-pdf を外して" in fin.cli
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf")
    res = convert(PLACE, meta, journal, api_opts(tmp_path / "c", pdf_path=broken))
    fin = finish(res)
    assert "手動（チャットに貼り付け）に切り替えて" in fin.box_detail and "--ai manual に切り替えて" in fin.cli


def _fake_claude(monkeypatch, content, served):
    import anthropic

    class FakeStream:
        def __init__(self, kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_final_message(self):
            return types.SimpleNamespace(stop_reason="end_turn", model=served, content=content,
                                         usage=types.SimpleNamespace(input_tokens=10, output_tokens=5))

    class FakeClient:
        def __init__(self, *a, **k):
            self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(stream=lambda **kw: FakeStream(kw)))
            self.messages = self.beta.messages

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)


def test_mid_output_fallback_joins_text_parts_and_records_the_model(journal, meta, tmp_path, monkeypatch):
    """API の形の確かめ (1)(2): stream で出力の途中に断られると、content は「途中までの text → fallback の部 → 続きの text」になる。
    text の部をつないで 1 つの回答として読み、答えたモデル（msg.model）を AIOutcome.model と model_note に記録する。"""
    from test_ai import RESPONSE
    body = RESPONSE
    cut = len(body) // 2
    content = [types.SimpleNamespace(type="text", text=body[:cut]),
               types.SimpleNamespace(type="fallback"),
               types.SimpleNamespace(type="text", text=body[cut:])]
    _fake_claude(monkeypatch, content, "claude-opus-5")
    out = ai_assist.call_api("指示", "データ", None, api_key="t")
    assert out.raw == body and not out.error
    assert out.model == "claude-opus-5" and "安全上の判定で断られたため、claude-opus-5 が回答した" in out.model_note
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, ai_mode="api", ai_api_key="t"))
    assert not res.ai.error and res.ai.accepted and res.ai.model == "claude-opus-5"
    assert "使用したモデル: claude-opus-5。安全上の判定で断られたため" in res.report_path.read_text(encoding="utf-8")
    # 切り替わらなければ、text の部は 1 つで、モデルの記録もそのまま
    _fake_claude(monkeypatch, [types.SimpleNamespace(type="text", text=body)], DEFAULT_MODEL)
    out = ai_assist.call_api("指示", "データ", None, api_key="t")
    assert out.raw == body and out.model == DEFAULT_MODEL and out.model_note == ""


def test_cost_note_says_when_the_answer_is_reused():
    """利用者向け 3: 費用の文は、前の回答を使う条件（図の画像・書誌だけを直したとき）と、呼び直す場合、目安であることを言う。
    ノートブックの文（tools/make_notebook.py の COST_NOTE）も同じ。"""
    from test_notebook import mk
    text = cost_note()
    assert "図の画像や書誌だけを直して変換し直すときは、前の回答を使うので料金はかかりません" in text
    assert "Word で原稿を直したときや、AI・モデル・PDF を変えたときは、AI を呼び直します" in text and "目安" in text
    assert "同じ原稿をもう一度変換するときは" not in text
    assert mk.COST_NOTE == text


def test_notebook_step4_and_step5_order():
    """利用者向け 2・4: 手順 5 は、要対応・要確認・必須の手順の枠（result_boxes）を先に出し、その後に依頼文の枠（prompt_box）を出す。
    手順 4 は、手動と API（Claude）のどちらも使えることと、それぞれが向く場合を 1 か所で言い、「推奨」を選択肢の名前に重ねない。"""
    from test_notebook import mk
    cells = ["".join(c["source"]) for c in json.loads(mk.render())["cells"]]
    step5 = next(c for c in cells if "#@title 5. 変換を実行" in c)
    assert step5.index("display(HTML(result_boxes(res") < step5.index("display(HTML(prompt_box(")
    step4 = next(c for c in cells if "#@title 4. AI による仕上げの方法を選ぶ" in c)
    assert "Claude・推奨" not in step4 and '"API で自動実行（Claude）"' in step4
    assert "はじめて使うときや、論文が少ないときに向きます" in step4 and "何本も続けて変換するときに向きます" in step4
    assert "API で使う AI は Claude を推奨します（ChatGPT・Gemini・Sakana AI は動作を確かめていません）" in step4


def test_waiting_answer_texts_ask_for_the_pdf(journal, meta, tmp_path):
    """利用者向け 7・8: 回答待ちの 2 章と 14 章の行は、位置を聞く図形があれば出版版 PDF の添付を言う。2 章の見出しに「要確認」を付けない。"""
    res = convert(PLACE, meta, journal, Options(out_dir=tmp_path / "p", ai_mode="manual"))
    text = res.report_path.read_text(encoding="utf-8")
    ch2 = text.split("## 2. AI による仕上げ\n")[1].split("## 3.")[0]
    assert "出版版 PDF を同じメッセージに添付してチャット" in ch2 and "AI による仕上げの前の状態です" in ch2
    assert "## 2. AI による仕上げ（要確認）" not in text and "- AI による仕上げ: 手動" in text
    assert "を、出版版 PDF を同じメッセージに添付して AI に渡し" in finish(res).checklist
    # 位置を聞く図形のない論文では、PDF は任意
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path / "f", ai_mode="manual"))
    if not res.plan.asked_floats:
        ch2 = res.report_path.read_text(encoding="utf-8").split("## 2. AI による仕上げ\n")[1].split("## 3.")[0]
        assert "出版版 PDF を添付すると" in ch2


def test_titles_do_not_repeat_recommended(journal, meta, tmp_path):
    """利用者向け 10: 青い枠は「手順（推奨）: 」を付けるので、見出し（box_title）に「推奨」を書かない。"""
    from jasme_jats.colab import result_boxes
    res = convert(PLACE, meta, journal, Options(out_dir=tmp_path))
    fin = finish(res)
    assert "推奨" not in fin.box_title and fin.box_title.endswith("個）")
    html = result_boxes(res)
    assert "手順（推奨）: " + fin.box_title in html and html.count("推奨") >= 1
