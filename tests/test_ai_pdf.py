"""出版版 PDF を Claude の API に渡す（修正計画 W8 の 4.7・手順 20）: pdf_attachment の事前の確かめ、call_api の document の部品、
断られたときの PDF なしのやり直し、Options.ai_send_pdf・--ai-no-pdf、AI回答.json の meta の PDF の欄。
API は呼ばない（偽の anthropic クライアント）。PDF は pypdfium2 で作る空白のページ（内容は架空）。"""
import base64
import copy
import hashlib
import json
import types

import pytest

import answers
from conftest import FULL
from jasme_jats import ai_assist, pipeline
from jasme_jats.ai_assist import ANSWER_FILE, PdfAttachment, pdf_attachment
from jasme_jats.pipeline import Options, convert

pdfium = pytest.importorskip("pypdfium2")
RESPONSE = json.dumps({"placements": [], "links": [], "notes": []})
FULL_ANSWER = answers.answer(docx=FULL)      # 依頼の番号の確かめを通る回答（FULL への回答）


def make_pdf(path, pages=2):
    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(200, 200)
    doc.save(str(path))
    doc.close()
    return path


def fake_claude(monkeypatch, calls, refuse=(), text=RESPONSE):
    """偽の Anthropic クライアント。refuse は、PDF（document の部品）を付けた呼び出しを断る HTTP の状態（400・413）。"""
    import anthropic
    import httpx2

    class FakeStream:
        def __init__(self, kwargs):
            calls.append(copy.deepcopy(kwargs))
            has_pdf = any(b.get("type") == "document" for b in kwargs["messages"][0]["content"])
            if refuse and has_pdf:
                req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
                raise anthropic.APIStatusError("too large", response=httpx2.Response(refuse[0], request=req), body=None)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_final_message(self):
            return types.SimpleNamespace(stop_reason="end_turn", content=[types.SimpleNamespace(type="text", text=text)],
                                         usage=types.SimpleNamespace(input_tokens=1, output_tokens=1))

    class FakeClient:
        def __init__(self, *a, **k):
            self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(stream=lambda **kw: FakeStream(kw)))
            self.messages = self.beta.messages

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)


def test_pdf_attachment_checks(tmp_path):
    good = make_pdf(tmp_path / "a.pdf", 3)
    att = pdf_attachment(good)
    assert (att.mode, att.pages, att.name, att.note) == ("pdf", 3, "a.pdf", "")
    assert att.sha256 == hashlib.sha256(good.read_bytes()).hexdigest() and att.data == good.read_bytes()
    assert pdf_attachment(None).mode == "none" and "指定されていない" in pdf_attachment(None).note
    off = pdf_attachment(good, send=False)
    assert off.mode == "none" and "渡さない設定" in off.note and not off.data
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4 broken")
    assert pdf_attachment(bad).mode == "none" and "開けなかった" in pdf_attachment(bad).note
    assert "読めなかった" in pdf_attachment(tmp_path / "none.pdf").note
    big = pdf_attachment(good, max_bytes=100)
    assert big.mode == "none" and "大きすぎる" in big.note
    many = pdf_attachment(make_pdf(tmp_path / "m.pdf", 101))
    assert many.mode == "none" and "101 ページ" in many.note and "上限 100 ページ" in many.note
    assert pdf_attachment(make_pdf(tmp_path / "h.pdf", 100)).mode == "pdf"


def test_call_api_puts_pdf_before_data(monkeypatch, tmp_path):
    calls = []
    fake_claude(monkeypatch, calls)
    att = pdf_attachment(make_pdf(tmp_path / "a.pdf"))
    out = ai_assist.call_provider("claude", "指示", "データ", att, api_key="t")
    assert not out.error and out.pdf_sent == "pdf" and out.pdf_note == ""
    kw = calls[0]
    content = kw["messages"][0]["content"]
    assert [b["type"] for b in content] == ["document", "text"] and content[1]["text"] == "データ"
    assert content[0]["source"] == {"type": "base64", "media_type": "application/pdf",
                                    "data": base64.standard_b64encode(att.data).decode("ascii")}
    assert "citations" not in content[0] and kw["system"] == "指示"
    assert kw["output_config"]["effort"] == "high" and kw["output_config"]["format"]["type"] == "json_schema"
    # PDF なし: 今までと同じ形（text の部品だけ）
    calls.clear()
    out = ai_assist.call_provider("claude", "指示", "データ", None, api_key="t")
    assert [b["type"] for b in calls[0]["messages"][0]["content"]] == ["text"] and out.pdf_sent == ""
    out = ai_assist.call_provider("claude", "指示", "データ", PdfAttachment(note="理由"), api_key="t")
    assert out.pdf_sent == "" and out.pdf_note == "理由"


@pytest.mark.parametrize("status", [400, 413])
def test_pdf_refused_retries_once_without_pdf(monkeypatch, tmp_path, status):
    calls = []
    fake_claude(monkeypatch, calls, refuse=(status,))
    att = pdf_attachment(make_pdf(tmp_path / "a.pdf"))
    out = ai_assist.call_api("指示", "データ", att, api_key="t")
    assert not out.error and out.raw == RESPONSE and out.pdf_sent == ""
    assert out.pdf_note.startswith(ai_assist.PDF_REFUSED_MSG) and "too large" in out.pdf_note and str(status) in out.pdf_note
    types_ = [[b["type"] for b in c["messages"][0]["content"]] for c in calls]
    assert types_[-1] == ["text"] and types_.count(["document", "text"]) >= 1
    # PDF なしでも断られたら（2 回目も失敗）、失敗にする。PDF なしのやり直しは 1 回だけ
    import anthropic

    class Always:
        def __init__(self, kw):
            calls.append(copy.deepcopy(kw))
            import httpx2
            req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
            raise anthropic.APIStatusError("nope", response=httpx2.Response(status, request=req), body=None)
    calls.clear()
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: types.SimpleNamespace(
        beta=types.SimpleNamespace(messages=types.SimpleNamespace(stream=lambda **kw: Always(kw))),
        messages=types.SimpleNamespace(stream=lambda **kw: Always(kw))))
    out = ai_assist.call_api("指示", "データ", att, api_key="t")
    assert f"API エラー（{status}）" in out.error and not out.raw
    assert [len(c["messages"][0]["content"]) for c in calls] == [2, 1]        # PDF つき 1 回 → PDF なし 1 回だけ


def _status_error(cls, status, url):
    import httpx2
    req = httpx2.Request("POST", url)
    return cls("refused", response=httpx2.Response(status, request=req), body=None)


def fake_openai(monkeypatch, calls, refuse=None):
    """偽の OpenAI クライアント（Responses API）。refuse は、input_file を付けた呼び出しを断る HTTP の状態。"""
    import openai

    def create(**kw):
        calls.append(copy.deepcopy(kw))
        if refuse and any(c["type"] == "input_file" for c in kw["input"][0]["content"]):
            raise _status_error(openai.APIStatusError, refuse, "https://api.openai.com/v1/responses")
        item = types.SimpleNamespace(type="message", content=[types.SimpleNamespace(type="output_text", text=RESPONSE)])
        return types.SimpleNamespace(output=[item], status="completed", output_text=RESPONSE, usage=None)

    monkeypatch.setattr(openai, "OpenAI", lambda *a, **k: types.SimpleNamespace(responses=types.SimpleNamespace(create=create)))


def fake_gemini(monkeypatch, calls, refuse=None):
    """偽の Gemini クライアント。refuse は、PDF（inline_data）を付けた呼び出しを断る HTTP の状態。"""
    from google import genai
    from google.genai import errors
    from google.genai import types as gtypes

    def generate_content(**kw):
        calls.append(kw)
        if refuse and any(p.inline_data is not None for p in kw["contents"][0].parts):
            raise errors.ClientError(refuse, {"error": {"code": refuse, "message": "too big", "status": "INVALID_ARGUMENT"}})
        return types.SimpleNamespace(prompt_feedback=None, text=RESPONSE, usage_metadata=None,
                                     candidates=[types.SimpleNamespace(finish_reason=gtypes.FinishReason("STOP"))])

    monkeypatch.setattr(genai, "Client", lambda *a, **k: types.SimpleNamespace(models=types.SimpleNamespace(
        generate_content=generate_content)))


def fake_sakana(monkeypatch, calls, refuse=(), reject_schema=False):
    """偽の Sakana AI クライアント（Chat Completions）。refuse は、断る部品の種類（"file"・"image_url"）。"""
    import openai

    def create(**kw):
        kinds = [c["type"] for c in kw["messages"][1]["content"]]
        calls.append({"kinds": kinds, "schema": "response_format" in kw, "content": kw["messages"][1]["content"]})
        if any(k in refuse for k in kinds) or (reject_schema and "response_format" in kw):
            raise _status_error(openai.BadRequestError, 400, "https://api.sakana.ai/v1/chat/completions")
        msg = types.SimpleNamespace(content=RESPONSE, refusal=None)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg, finish_reason="stop")], usage=None)

    monkeypatch.setattr(openai, "OpenAI", lambda *a, **k: types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create))))


def test_pdf_will_be_sent_by_provider(tmp_path):
    att = pdf_attachment(make_pdf(tmp_path / "a.pdf"))
    for p in ("claude", "openai", "gemini"):
        assert ai_assist.pdf_will_be_sent(p, att, "m") == "pdf"
    assert ai_assist.pdf_will_be_sent("sakana", att, "sakana-namazu-1") == "pdf"
    assert ai_assist.pdf_will_be_sent("sakana", att, "sakana-fugu") == "pages"
    big = PdfAttachment(mode="pdf", name="b.pdf", data=att.data + b"0" * ai_assist.PDF_SAKANA_BYTES, pages=2)
    assert ai_assist.pdf_will_be_sent("sakana", big, "sakana-namazu-1") == "pages"       # 4 MB 超はページの画像
    assert ai_assist.pdf_will_be_sent("openai", pdf_attachment(None), "m") == ""
    assert ai_assist.pdf_will_be_sent("unknown", att, "m") == ""


def test_openai_gets_pdf_before_data_and_store_false(monkeypatch, tmp_path):
    calls = []
    fake_openai(monkeypatch, calls)
    att = pdf_attachment(make_pdf(tmp_path / "a.pdf"))
    out = ai_assist.call_provider("openai", "指示", "データ", att, model="gpt-test", api_key="t")
    assert not out.error and out.pdf_sent == "pdf" and out.pdf_note == ""
    content = calls[0]["input"][0]["content"]
    assert [c["type"] for c in content] == ["input_file", "input_text"] and calls[0]["store"] is False
    assert content[0]["filename"] == "a.pdf"
    assert content[0]["file_data"] == "data:application/pdf;base64," + base64.standard_b64encode(att.data).decode("ascii")
    # 断られたら PDF なしで 1 回だけやり直す
    calls.clear()
    fake_openai(monkeypatch, calls, refuse=413)
    out = ai_assist.call_provider("openai", "指示", "データ", att, model="gpt-test", api_key="t")
    assert not out.error and out.pdf_sent == "" and out.pdf_note.startswith(ai_assist.PDF_REFUSED_MSG) and "413" in out.pdf_note
    assert [len(c["input"][0]["content"]) for c in calls] == [2, 1]
    # PDF がなければ渡さず、理由を書く
    out = ai_assist.call_provider("openai", "指示", "データ", pdf_attachment(None), model="gpt-test", api_key="t")
    assert out.pdf_sent == "" and out.pdf_note == ai_assist.PDF_NONE_MSG


def test_gemini_gets_pdf_before_data(monkeypatch, tmp_path):
    calls = []
    fake_gemini(monkeypatch, calls)
    att = pdf_attachment(make_pdf(tmp_path / "a.pdf"))
    out = ai_assist.call_provider("gemini", "指示", "データ", att, model="gemini-test", api_key="t")
    parts = calls[0]["contents"][0].parts
    assert not out.error and out.pdf_sent == "pdf" and len(parts) == 2
    assert parts[0].inline_data.mime_type == "application/pdf" and parts[0].inline_data.data == att.data
    assert parts[1].text == "データ"
    calls.clear()
    fake_gemini(monkeypatch, calls, refuse=400)
    out = ai_assist.call_provider("gemini", "指示", "データ", att, model="gemini-test", api_key="t")
    assert not out.error and out.pdf_sent == "" and ai_assist.PDF_REFUSED_MSG in out.pdf_note
    assert [len(c["contents"][0].parts) for c in calls] == [2, 1]


def test_sakana_pdf_or_page_images(monkeypatch, tmp_path):
    att = pdf_attachment(make_pdf(tmp_path / "a.pdf", 3))
    calls = []
    fake_sakana(monkeypatch, calls)
    out = ai_assist.call_provider("sakana", "指示", "データ", att, model="sakana-namazu-x", api_key="t")
    assert not out.error and out.pdf_sent == "pdf" and calls[0]["kinds"] == ["file", "text"]
    f = calls[0]["content"][0]["file"]
    assert f["filename"] == "a.pdf" and f["file_data"].startswith("data:application/pdf;base64,")
    # Fugu は PDF ではなくページの画像（ページ数だけ。データの前）
    calls.clear()
    out = ai_assist.call_provider("sakana", "指示", "データ", att, model="sakana-fugu", api_key="t")
    assert out.pdf_sent == "pages" and calls[0]["kinds"] == ["image_url"] * 3 + ["text"] and out.pdf_note == ""
    assert calls[0]["content"][0]["image_url"]["url"].startswith("data:image/png;base64,")
    # 4 MB 超の Namazu もページの画像
    calls.clear()
    big = PdfAttachment(mode="pdf", name="b.pdf", data=att.data + b"0" * ai_assist.PDF_SAKANA_BYTES, pages=3, sha256="x")
    out = ai_assist.call_provider("sakana", "指示", "データ", big, model="sakana-namazu-x", api_key="t")
    assert out.pdf_sent == "pages" and calls[0]["kinds"][0] == "image_url"


def test_sakana_page_images_are_limited_to_40_pages(monkeypatch, tmp_path):
    att = pdf_attachment(make_pdf(tmp_path / "a.pdf", 42))
    calls = []
    fake_sakana(monkeypatch, calls)
    out = ai_assist.call_provider("sakana", "指示", "データ", att, model="sakana-fugu", api_key="t")
    assert out.pdf_sent == "pages" and calls[0]["kinds"].count("image_url") == 40 and "先頭 40 ページ" in out.pdf_note


def test_sakana_retry_order_pdf_pages_none_then_schema(monkeypatch, tmp_path):
    att = pdf_attachment(make_pdf(tmp_path / "a.pdf", 2))
    calls = []
    fake_sakana(monkeypatch, calls, refuse=("file",))
    out = ai_assist.call_provider("sakana", "指示", "データ", att, model="sakana-namazu-x", api_key="t")
    assert [c["kinds"][0] for c in calls] == ["file", "image_url"] and out.pdf_sent == "pages"
    assert ai_assist.PDF_TO_PAGES_MSG in out.pdf_note and all(c["schema"] for c in calls)
    calls.clear()
    fake_sakana(monkeypatch, calls, refuse=("file", "image_url"))
    out = ai_assist.call_provider("sakana", "指示", "データ", att, model="sakana-namazu-x", api_key="t")
    assert [c["kinds"][0] for c in calls] == ["file", "image_url", "text"] and out.pdf_sent == "" and not out.error
    assert ai_assist.PDF_REFUSED_MSG in out.pdf_note and calls[-1]["schema"] and not out.model_note
    # PDF の有無を決めてから、JSON スキーマを外す（PDF つきの呼び出しでは外さない）
    calls.clear()
    fake_sakana(monkeypatch, calls, refuse=("file",), reject_schema=True)
    out = ai_assist.call_provider("sakana", "指示", "データ", att, model="sakana-namazu-x", api_key="t")
    assert [(c["kinds"][0], c["schema"]) for c in calls] == [("file", True), ("image_url", True), ("text", True), ("text", False)]
    assert out.pdf_sent == "" and "JSON スキーマ" in out.model_note and not out.error


def run(meta, journal, out, docx=FULL, **kw):
    return convert(docx, meta, journal, Options(out_dir=out, ai_mode="api", ai_api_key="t", **kw))


def test_convert_sends_pdf_and_records_meta(journal, meta, tmp_path, monkeypatch):
    calls = []
    fake_claude(monkeypatch, calls, text=FULL_ANSWER)
    pdf = make_pdf(tmp_path / "a.pdf", 2)
    res = run(meta, journal, tmp_path / "o1", pdf_path=pdf)
    assert res.ai.pdf_sent == "pdf" and [b["type"] for b in calls[0]["messages"][0]["content"]] == ["document", "text"]
    got = json.loads(res.ai_answer_path.read_text(encoding="utf-8"))["meta"]
    assert got["pdf_send"] == "pdf" and got["pdf_sha256"] == hashlib.sha256(pdf.read_bytes()).hexdigest()
    assert "渡した" in res.report_path.read_text(encoding="utf-8").split("## 2.")[1].split("## 3.")[0]
    # 同じ PDF なら使い回す（呼ばない）。PDF を渡さない設定、別の PDF では使い回さない
    cache = res.ai_answer_path.read_text(encoding="utf-8")
    calls.clear()
    res2 = run(meta, journal, tmp_path / "o2", pdf_path=pdf, ai_cache=cache)
    assert calls == [] and res2.ai.reused and res2.ai.pdf_sent == "pdf"
    assert "呼び出していない" in res2.report_path.read_text(encoding="utf-8").split("## 2.")[1].split("## 3.")[0]
    res3 = run(meta, journal, tmp_path / "o3", pdf_path=pdf, ai_cache=cache, ai_send_pdf=False)
    assert len(calls) == 1 and res3.ai.pdf_sent == "" and "渡さない設定" in res3.ai.pdf_note
    assert [b["type"] for b in calls[0]["messages"][0]["content"]] == ["text"]
    calls.clear()
    run(meta, journal, tmp_path / "o4", pdf_path=make_pdf(tmp_path / "b.pdf", 3), ai_cache=cache)
    assert len(calls) == 1


def test_pdf_less_answer_is_not_reused_with_pdf(journal, meta, tmp_path, monkeypatch):
    """PDF なしで得た回答（渡さない設定・断られてやり直した）を、PDF を付けた変換で使い回さない。"""
    calls = []
    fake_claude(monkeypatch, calls, text=FULL_ANSWER)
    pdf = make_pdf(tmp_path / "a.pdf")
    res = run(meta, journal, tmp_path / "o1", pdf_path=pdf, ai_send_pdf=False)
    cache = res.ai_answer_path.read_text(encoding="utf-8")
    assert json.loads(cache)["meta"]["pdf_send"] == "" and json.loads(cache)["meta"]["pdf_sha256"] == ""
    calls.clear()
    run(meta, journal, tmp_path / "o2", pdf_path=pdf, ai_cache=cache)
    assert len(calls) == 1
    # 断られて外してやり直した回答の写しも、PDF なしの meta
    calls.clear()
    fake_claude(monkeypatch, calls, refuse=(413,), text=FULL_ANSWER)
    res = run(meta, journal, tmp_path / "o3", pdf_path=pdf)
    assert res.ai.pdf_sent == "" and ai_assist.PDF_REFUSED_MSG in res.ai.pdf_note
    assert json.loads(res.ai_answer_path.read_text(encoding="utf-8"))["meta"]["pdf_send"] == ""
    assert ai_assist.PDF_REFUSED_MSG in res.report_path.read_text(encoding="utf-8")


def test_cli_ai_no_pdf(tmp_path, monkeypatch, capsys):
    from jasme_jats.cli import main
    seen = []
    monkeypatch.setattr(pipeline, "call_provider", lambda p, s, r, att, **k: seen.append(att) or ai_assist.AIOutcome(
        mode="api", raw=RESPONSE))
    pdf = make_pdf(tmp_path / "a.pdf")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "t")
    main([str(FULL), "--ai", "api", "--pdf", str(pdf), "--out", str(tmp_path / "o1")])
    main([str(FULL), "--ai", "api", "--pdf", str(pdf), "--ai-no-pdf", "--out", str(tmp_path / "o2")])
    assert [a.mode for a in seen] == ["pdf", "none"]
    with pytest.raises(SystemExit) as e:
        main([str(FULL), "--ai-no-pdf", "--out", str(tmp_path / "o3")])
    assert e.value.code == 2 and "--ai-no-pdf" in capsys.readouterr().err
