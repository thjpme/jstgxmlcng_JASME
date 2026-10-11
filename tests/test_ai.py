"""AI 補完: 回答の検証と適用（実際の API は呼ばない）。"""
import json
import types

from lxml import etree

from conftest import DATA, FULL
from jasme_jats import ai_assist
from jasme_jats.ai_assist import parse_response, parse_mathml
from jasme_jats.pipeline import Options, convert

RESPONSE = (DATA / "ai_response_sample_full.json").read_text(encoding="utf-8")


def load(res):
    return etree.fromstring(res.xml_path.read_bytes().split(b"\n", 2)[2])


def test_manual_mode_applies_valid_ops_and_rejects_invalid(journal, meta, tmp_path):
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, ai_mode="manual", ai_response=RESPONSE,
                                               convert_metafiles=False))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    root = load(res)
    bibr = {(x.text, x.get("rid")) for x in root.iter("xref") if x.get("ref-type") == "bibr"}
    assert {("2001", "B2"), ("2025", "B7"), ("2016", "B4"), ("1977", "B10")} <= bibr
    rejected = {op["text"] for op, _ in res.ai.rejected}
    assert rejected == {"Claude", "図9"}           # 年以外へのリンク・存在しない図は不採用
    assert root.find(".//disp-formula/alternatives/graphic") is not None
    assert root.find(".//disp-formula/alternatives/{http://www.w3.org/1998/Math/MathML}math") is not None
    assert res.fidelity.ai_additions                   # AI が併記した数式は別枠で記録される
    names = [n for n in root.iter("name") if n.get("name-style") == "eastern"]
    assert [x.text for x in names[2]] == ["研究", "次郎"]
    assert res.unresolved_after == []
    report = res.report_path.read_text(encoding="utf-8")
    assert "AI による補完（要確認）" in report and "国宗は" in report


def test_manual_mode_without_response_writes_prompt(journal, meta, tmp_path):
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, ai_mode="manual", convert_metafiles=False))
    prompt = res.prompt_path.read_text(encoding="utf-8")
    assert "[d18]" in prompt and "link_citation" in prompt
    assert (tmp_path / "AI添付画像" / "img3.png").exists()
    assert res.fidelity.ok
    # チャットの AI が JSON を崩さないよう、回答の書き方（コードブロック 1 つ・半角の引用符）と見本を示す
    assert "## 回答の書き方" in prompt and "```json" in prompt
    assert parse_response(ai_assist.MANUAL_EXAMPLE)["operations"]


def test_parse_response_does_not_guess_on_curly_quotes():
    # 文字列が飾りの引用符で囲まれた回答は推測で直さず、どこが読めないかと対処を示す
    bad = '{\n  “operations”: [],\n  “notes”: [“注の (n.d.) は引用ではない”]\n}'
    try:
        parse_response(bad)
    except ValueError as e:
        msg = str(e)
    else:
        raise AssertionError("読めてしまった")
    assert "2 行目" in msg and "飾りの引用符" in msg and "コピーボタン" in msg


def test_parse_response_reports_missing_json():
    try:
        parse_response("提案はありません。")
    except ValueError as e:
        assert "コードブロック" in str(e)
    else:
        raise AssertionError("読めてしまった")


def test_parse_response_accepts_code_fence():
    data = parse_response("以下が回答です。\n```json\n" + RESPONSE + "\n```")
    assert len(data["operations"]) == 9


def test_parse_mathml_rejects_foreign_elements():
    ok, _ = parse_mathml('<math><mi>x</mi></math>')
    assert ok is not None
    bad, why = parse_mathml('<math xmlns="http://www.w3.org/1998/Math/MathML"><script/></math>')
    assert bad is None and "script" in why


def test_api_mode_with_fake_client(journal, meta, tmp_path, monkeypatch):
    """API の呼び出し部分を偽のクライアントに置き換えて、回答の受け渡しを確かめる。"""
    calls = {}

    class FakeStream:
        def __init__(self, kwargs):
            calls.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_final_message(self):
            return types.SimpleNamespace(stop_reason="end_turn", content=[types.SimpleNamespace(type="text", text=RESPONSE)],
                                         usage=types.SimpleNamespace(input_tokens=100, output_tokens=50))

    class FakeClient:
        def __init__(self, *a, **k):
            self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(stream=lambda **kw: FakeStream(kw)))
            self.messages = self.beta.messages

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, ai_mode="api", ai_api_key="test",
                                               convert_metafiles=False))
    assert calls["model"] == "claude-opus-5-5"
    assert calls["output_config"]["format"]["type"] == "json_schema"
    assert calls["fallbacks"] == "default"
    assert not res.ai.error
    assert len(res.ai.accepted) == 7 and res.fidelity.ok


def test_response_schema_is_strict():
    op = ai_assist.OP_SCHEMA
    assert op["additionalProperties"] is False
    assert set(op["required"]) == set(op["properties"])
    json.dumps(ai_assist.RESPONSE_SCHEMA)


def _fake_anthropic(monkeypatch, calls, available=("claude-opus-5-5",), listed=()):
    """偽の Anthropic クライアント。available にないモデルを指定すると NotFoundError、listed は Models API の一覧。"""
    import anthropic
    import httpx2

    class FakeStream:
        def __init__(self, kwargs):
            calls.append(kwargs["model"])
            if kwargs["model"] not in available:
                req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
                raise anthropic.NotFoundError("model not found", response=httpx2.Response(404, request=req), body=None)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_final_message(self):
            return types.SimpleNamespace(stop_reason="end_turn", content=[types.SimpleNamespace(type="text", text=RESPONSE)],
                                         usage=types.SimpleNamespace(input_tokens=100, output_tokens=50))

    class FakeClient:
        def __init__(self, *a, **k):
            self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(stream=lambda **kw: FakeStream(kw)))
            self.messages = self.beta.messages
            self.models = types.SimpleNamespace(list=lambda: [types.SimpleNamespace(id=i, created_at=c) for i, c in listed])

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)


def test_api_model_auto_and_retired_fallback(journal, meta, tmp_path, monkeypatch):
    listed = [("claude-opus-5", "2026-01-01"), ("claude-opus-6", "2027-10-01"), ("claude-sonnet-6", "2027-12-01")]
    # 既定のモデルが提供終了（見つからない）→ 使える最新の Opus に切り替えてやり直す
    calls = []
    _fake_anthropic(monkeypatch, calls, available=("claude-opus-6",), listed=listed)
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, ai_mode="api", ai_api_key="t", convert_metafiles=False))
    assert calls == ["claude-opus-5-5", "claude-opus-6"] and res.ai.model == "claude-opus-6"
    assert "切り替えた" in res.ai.model_note and not res.ai.error
    assert "使用したモデル: claude-opus-6" in res.report_path.read_text(encoding="utf-8")
    # 「自動」→ はじめから最新の Opus
    calls = []
    _fake_anthropic(monkeypatch, calls, available=("claude-opus-6",), listed=listed)
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, ai_mode="api", ai_model="auto", ai_api_key="t",
                                               convert_metafiles=False))
    assert calls == ["claude-opus-6"] and "自動" in res.ai.model_note
    # 指定したモデルがなく、一覧からも見つからない → 分かりやすいエラー
    calls = []
    _fake_anthropic(monkeypatch, calls, available=(), listed=[])
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, ai_mode="api", ai_model="claude-typo",
                                               ai_api_key="t", convert_metafiles=False))
    assert "claude-typo が見つかりません" in res.ai.error and res.fidelity.ok


# ---------------------------------------------------------------------------- ChatGPT・Gemini の API モード
def _fake_openai(monkeypatch, calls, error=None, status="completed", content_type="output_text"):
    """偽の OpenAI クライアント（Responses API）。error に例外を渡すと、呼び出し時にそれを送出する。"""
    import openai

    def create(**kw):
        calls.append(kw)
        if error is not None:
            raise error
        item = types.SimpleNamespace(type="message", content=[types.SimpleNamespace(type=content_type, text=RESPONSE)])
        return types.SimpleNamespace(output=[item], status=status, output_text=RESPONSE,
                                     incomplete_details=types.SimpleNamespace(reason="max_output_tokens"),
                                     usage=types.SimpleNamespace(input_tokens=120, output_tokens=60))

    class FakeClient:
        def __init__(self, *a, **k):
            self.responses = types.SimpleNamespace(create=create)

    monkeypatch.setattr(openai, "OpenAI", FakeClient)


def test_openai_api_mode_with_fake_client(journal, meta, tmp_path, monkeypatch):
    calls = []
    _fake_openai(monkeypatch, calls)
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, ai_mode="api", ai_provider="openai",
                                               ai_model="gpt-test", ai_api_key="t", convert_metafiles=False))
    kw = calls[0]
    assert kw["model"] == "gpt-test"
    fmt = kw["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] is True and fmt["schema"] is ai_assist.RESPONSE_SCHEMA
    content = kw["input"][0]["content"]
    assert any(c["type"] == "input_image" and c["image_url"].startswith("data:image/png;base64,") for c in content)
    assert "link_citation" in kw["instructions"]
    assert not res.ai.error and res.ai.provider == "openai"
    assert len(res.ai.accepted) == 7 and res.fidelity.ok and res.fidelity.final_ok
    report = res.report_path.read_text(encoding="utf-8")
    assert "API（ChatGPT: gpt-test）" in report and "入力 120 トークン" in report


def test_openai_errors_are_reported(journal, meta, tmp_path, monkeypatch):
    import httpx2
    import openai
    req = httpx2.Request("POST", "https://api.openai.com/v1/responses")
    err = openai.AuthenticationError("bad key", response=httpx2.Response(401, request=req), body=None)
    _fake_openai(monkeypatch, [], error=err)
    out = ai_assist.call_provider("openai", "x", [], model="gpt-test", api_key="t")
    assert "OPENAI_API_KEY" in out.error
    _fake_openai(monkeypatch, [], content_type="refusal")
    assert "断りました" in ai_assist.call_provider("openai", "x", [], model="gpt-test", api_key="t").error
    _fake_openai(monkeypatch, [], status="incomplete")
    assert "途中で切れました" in ai_assist.call_provider("openai", "x", [], model="gpt-test", api_key="t").error
    # API キーが見つからない（クライアントを作れない）ときも、止まらずにエラーとして記録する
    def no_key(*a, **k):
        raise openai.OpenAIError("The api_key client option must be set")
    monkeypatch.setattr(openai, "OpenAI", no_key)
    assert "OPENAI_API_KEY を確認" in ai_assist.call_provider("openai", "x", [], model="gpt-test").error


def _fake_gemini(monkeypatch, calls, error=None, finish="STOP"):
    from google import genai
    from google.genai import types as gtypes

    def generate_content(**kw):
        calls.append(kw)
        if error is not None:
            raise error
        return types.SimpleNamespace(prompt_feedback=None, text=RESPONSE,
                                     candidates=[types.SimpleNamespace(finish_reason=gtypes.FinishReason(finish))],
                                     usage_metadata=types.SimpleNamespace(prompt_token_count=130, candidates_token_count=40,
                                                                          thoughts_token_count=30))

    class FakeClient:
        def __init__(self, *a, **k):
            self.models = types.SimpleNamespace(generate_content=generate_content)

    monkeypatch.setattr(genai, "Client", FakeClient)


def test_gemini_api_mode_with_fake_client(journal, meta, tmp_path, monkeypatch):
    calls = []
    _fake_gemini(monkeypatch, calls)
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, ai_mode="api", ai_provider="gemini",
                                               ai_model="gemini-test", ai_api_key="t", convert_metafiles=False))
    kw = calls[0]
    assert kw["model"] == "gemini-test"
    assert kw["config"].response_mime_type == "application/json"
    assert kw["config"].response_json_schema == ai_assist.RESPONSE_SCHEMA
    parts = kw["contents"][0].parts
    assert any(p.inline_data is not None and p.inline_data.mime_type == "image/png" for p in parts)
    assert not res.ai.error and res.ai.provider == "gemini"
    assert len(res.ai.accepted) == 7 and res.fidelity.ok and res.fidelity.final_ok
    report = res.report_path.read_text(encoding="utf-8")
    assert "API（Gemini: gemini-test）" in report and "出力 70 トークン" in report   # 思考のトークンも出力に数える


def test_gemini_errors_are_reported(monkeypatch):
    from google.genai import errors
    bad_key = errors.ClientError(400, {"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.",
                                                 "status": "INVALID_ARGUMENT"}})
    _fake_gemini(monkeypatch, [], error=bad_key)
    out = ai_assist.call_provider("gemini", "x", [], model="gemini-test", api_key="t")
    assert "GEMINI_API_KEY" in out.error
    not_found = errors.ClientError(404, {"error": {"code": 404, "message": "not found", "status": "NOT_FOUND"}})
    _fake_gemini(monkeypatch, [], error=not_found)
    assert "gemini-test が見つかりません" in ai_assist.call_provider("gemini", "x", [], model="gemini-test").error
    _fake_gemini(monkeypatch, [], finish="MAX_TOKENS")
    assert "途中で切れました" in ai_assist.call_provider("gemini", "x", [], model="gemini-test").error
    _fake_gemini(monkeypatch, [], finish="SAFETY")
    assert "SAFETY" in ai_assist.call_provider("gemini", "x", [], model="gemini-test").error
    from google import genai

    def no_key(*a, **k):
        raise ValueError("Missing key inputs argument!")
    monkeypatch.setattr(genai, "Client", no_key)
    assert "GEMINI_API_KEY または GOOGLE_API_KEY を確認" in ai_assist.call_provider("gemini", "x", [], model="g").error


def test_other_providers_require_a_model_name(journal, meta, tmp_path):
    # ChatGPT・Gemini ではモデル名を利用者が指定する（Claude のモデル名・「自動」・空欄は受け付けない）
    for model in ("", "auto", "claude-opus-5-5"):
        out = ai_assist.call_provider("openai", "x", [], model=model)
        assert "モデルの名前を指定" in out.error and "Opus と同等以上" in out.error
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, ai_mode="api", ai_provider="gemini", ai_model="",
                                               convert_metafiles=False))
    assert "Gemini の API を使うときは" in res.ai.error and res.fidelity.ok


def test_cli_requires_model_for_other_providers(capsys):
    import pytest
    from jasme_jats.cli import main
    with pytest.raises(SystemExit):
        main([str(FULL), "--ai", "api", "--ai-provider", "openai"])
    assert "--ai-model" in capsys.readouterr().err
