"""AI 補完: 回答の検証と適用（実際の API は呼ばない）。"""
import json
import types

import pytest
from lxml import etree

import make_fixtures as mf
from conftest import DATA, FLOAT, FULL, STRUCTURE
from jasme_jats import ai_assist
from jasme_jats.ai_assist import parse_response, parse_mathml
from jasme_jats.model import Para
from jasme_jats.pipeline import Options, _mechanical, convert
from jasme_jats.report import actions

RESPONSE = (DATA / "ai_response_sample_full.json").read_text(encoding="utf-8")
FLOAT_RESPONSE = json.loads((DATA / "ai_response_sample_float.json").read_text(encoding="utf-8"))


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
    """```json（```JSON も）のコードブロックの中身を読む（閉じの ``` の後ろの説明の { } は使わない）。"""
    data = parse_response("以下が回答です。\n```json\n" + RESPONSE + "\n```")
    assert len(data["operations"]) == 9
    for fence in ("```json", "```JSON"):
        data = parse_response(fence + "\n" + RESPONSE + "\n```\n補足: {placements} は空です。")
        assert len(data["operations"]) == 9


def test_parse_response_reads_json_before_trailing_text(journal, meta, tmp_path):
    """JSON の後ろに文字が続く回答（閉じの ``` のないコードブロックの後ろの説明など）は、最後の } までを読む（0.21.0 と
    同じ。後ろの文字は使わない）。後ろの文字に } があるとき（JSON が 2 つ続くときなど）は読まない。途中で切れた回答とも
    扱わない（parse_cut_response は読まない）。"""
    from jasme_jats.ai_assist import parse_cut_response
    body = json.dumps(FLOAT_RESPONSE, ensure_ascii=False, indent=1)
    unclosed = "```json\n" + body + "\n以上です。"
    for text in (unclosed, body + "\n以上です。", "```json\n" + body + "\n以上です。\n```"):
        assert parse_response(text)["placements"] == FLOAT_RESPONSE["placements"]
        assert parse_cut_response(text) is None
    for text in (body + "\n" + body, unclosed + "注の {d5} を確かめること。"):
        with pytest.raises(ValueError) as e:
            parse_response(text)
        assert "Extra data" in str(e.value) and "途中で切れている" not in str(e.value)
    # 手動モードで貼り戻しても、ふつうの回答と同じく反映する
    res = convert(FLOAT, meta, journal, Options(out_dir=tmp_path, ai_mode="manual", ai_response=unclosed,
                                                convert_metafiles=False))
    assert res.ai.error == "" and res.ai.partial == "" and res.plan.unplaced_floats == [] and res.fidelity.ok


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


def _fake_anthropic(monkeypatch, calls, available=("claude-opus-5-5",), listed=(), text=RESPONSE, stop="end_turn"):
    """偽の Anthropic クライアント。available にないモデルを指定すると NotFoundError、listed は Models API の一覧。
    text・stop は回答の文字列と止まった理由（max_tokens なら、回答が長すぎて途中で切れた）。"""
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
            return types.SimpleNamespace(stop_reason=stop, content=[types.SimpleNamespace(type="text", text=text)],
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
def _fake_openai(monkeypatch, calls, error=None, status="completed", content_type="output_text", text=RESPONSE):
    """偽の OpenAI クライアント（Responses API）。error に例外を渡すと、呼び出し時にそれを送出する。"""
    import openai

    def create(**kw):
        calls.append(kw)
        if error is not None:
            raise error
        item = types.SimpleNamespace(type="message", content=[types.SimpleNamespace(type=content_type, text=text)])
        return types.SimpleNamespace(output=[item], status=status, output_text=text,
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


def _fake_gemini(monkeypatch, calls, error=None, finish="STOP", text=RESPONSE):
    from google import genai
    from google.genai import types as gtypes

    def generate_content(**kw):
        calls.append(kw)
        if error is not None:
            raise error
        return types.SimpleNamespace(prompt_feedback=None, text=text,
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


def _fake_sakana(monkeypatch, calls, reject_schema=False, finish="stop", text=None):
    """偽の OpenAI 互換クライアント（Chat Completions）。reject_schema なら response_format 付きの呼び出しを 400 で断る。"""
    import httpx2
    import openai

    def create(**kw):
        calls.append(kw)
        if reject_schema and "response_format" in kw:
            req = httpx2.Request("POST", "https://api.sakana.ai/v1/chat/completions")
            raise openai.BadRequestError("response_format is not supported", response=httpx2.Response(400, request=req),
                                         body=None)
        msg = types.SimpleNamespace(content=("```json\n" + RESPONSE + "\n```") if text is None else text, refusal=None)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg, finish_reason=finish)],
                                     usage=types.SimpleNamespace(prompt_tokens=90, completion_tokens=45))

    class FakeClient:
        def __init__(self, *a, **k):
            calls.append({"client": k})
            self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=create))

    monkeypatch.setattr(openai, "OpenAI", FakeClient)


def test_sakana_api_mode_with_fake_client(journal, meta, tmp_path, monkeypatch):
    calls = []
    _fake_sakana(monkeypatch, calls)
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, ai_mode="api", ai_provider="sakana",
                                               ai_model="sakana-namazu", ai_api_key="sk-sakana", convert_metafiles=False))
    client, kw = calls[0]["client"], calls[1]
    assert client["base_url"] == "https://api.sakana.ai/v1" and client["api_key"] == "sk-sakana"
    assert kw["model"] == "sakana-namazu"
    assert kw["response_format"]["type"] == "json_schema"
    assert kw["response_format"]["json_schema"]["schema"] is ai_assist.RESPONSE_SCHEMA
    system, user = kw["messages"]
    assert "## 回答の書き方" in system["content"] and "link_citation" in system["content"]
    assert any(c["type"] == "image_url" and c["image_url"]["url"].startswith("data:image/png;base64,")
               for c in user["content"])
    assert not res.ai.error and res.ai.provider == "sakana"
    assert len(res.ai.accepted) == 7 and res.fidelity.ok and res.fidelity.final_ok
    report = res.report_path.read_text(encoding="utf-8")
    assert "API（Sakana AI: sakana-namazu）" in report and "入力 90 トークン" in report


def test_sakana_retries_without_schema_and_never_sends_openai_key(monkeypatch):
    # JSON スキーマの指定を断られたら、指定なしで 1 回だけやり直す（依頼文に回答の形式があるので JSON で返る）
    calls = []
    _fake_sakana(monkeypatch, calls, reject_schema=True)
    out = ai_assist.call_provider("sakana", "x", [], model="fugu", api_key="sk-sakana")
    creates = [c for c in calls if "messages" in c]
    assert len(creates) == 2 and "response_format" not in creates[1]
    assert not out.error and parse_response(out.raw)["operations"] and "指定なしでやり直した" in out.model_note
    _fake_sakana(monkeypatch, [], finish="length")
    assert "途中で切れました" in ai_assist.call_provider("sakana", "x", [], model="fugu", api_key="k").error
    # Sakana のキーがないときに、環境変数の OpenAI のキーを Sakana に送らない
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-should-not-be-sent")
    calls = []
    _fake_sakana(monkeypatch, calls)
    out = ai_assist.call_provider("sakana", "x", [], model="fugu")
    assert "SAKANA_API_KEY" in out.error and calls == []


# ---------------------------------------------------------------------------- 回答の順と、途中で切れた回答
def head_first(indent=1):
    """sample_float の模擬回答を、placements を先頭にして書いたもの（operations を長くして、切る位置を作る）。"""
    d = FLOAT_RESPONSE
    return json.dumps({"placements": d["placements"], "operations": d["operations"] * 3, "notes": ["気づき"]},
                      ensure_ascii=False, indent=indent)


def cut_cases():
    """途中で切れた回答。(a)〜(d) は最後まで書かれた placements の要素を読む。(e)(f) は読まない。"""
    full = head_first()
    ops = full.index('"operations"')
    in_ops = full[:full.index('"reason"', ops) + 15]                     # operations の文字列の途中
    ops_first = json.dumps(FLOAT_RESPONSE, ensure_ascii=False)           # 0.21.0 の見本の順（operations が先頭）
    return {
        "a": in_ops,
        "b": full[:ops + len('"operations":')],                          # "operations": の直後
        "c": full[:full.index('"float": "s2"') + 30],                    # 2 つ目の placements の要素の途中
        "d": "```json\n" + in_ops,                                       # 閉じのないコードブロック
        "e": ops_first[:ops_first.index('"placements"') - 20],           # operations が先頭で、placements の前で切れた
        "f": full.replace('"after": "d17"', '"after": “d17”')[:len(in_ops)],   # 途中に飾りの引用符（書き損じ）
    }


def test_response_format_puts_placements_first():
    """依頼文の見本・項目の説明・回答の書き方と、API の構造化出力のスキーマで、placements を回答の最初に書かせる。"""
    assert list(parse_response(ai_assist.MANUAL_EXAMPLE)) == ["placements", "operations", "notes"]
    schema = ai_assist.RESPONSE_SCHEMA
    assert list(schema["properties"]) == schema["required"] == ["placements", "operations", "notes"]
    assert "回答の最初に書く" in schema["properties"]["placements"]["description"]
    assert "回答の JSON は、placements、operations、notes の順に書いてください" in ai_assist.system_prompt()
    guide = ai_assist.FIELD_GUIDE
    assert guide.startswith("回答は placements、operations、notes の順に書く") and guide.index("placements（") < guide.index(
        "operations の各項目")
    prompt = ai_assist.manual_prompt("（依頼）", [])
    assert "JSON は placements、operations、notes の順に書いてください" in prompt
    # 読み取りはキーの順によらない（0.21.0 の順の回答も読める）
    assert parse_response(json.dumps(FLOAT_RESPONSE))["placements"] == parse_response(head_first())["placements"]


@pytest.mark.parametrize("name, floats", [("a", ["s1", "s2", "s3", "s4"]), ("b", ["s1", "s2", "s3", "s4"]),
                                          ("c", ["s1"]), ("d", ["s1", "s2", "s3", "s4"])])
def test_cut_response_keeps_finished_placements(name, floats):
    """途中で切れた回答から、最後まで書かれた placements の要素だけを読む（途中で切れた要素と operations・notes は使わない）。
    JSON の読み取りの誤りが文字列の途中で切れた形（Unterminated string）でも、「途中で切れている」の案内を出す。"""
    from jasme_jats.ai_assist import parse_cut_response
    text = cut_cases()[name]
    with pytest.raises(ValueError) as e:
        parse_response(text)
    assert "回答が途中で切れている可能性があります" in str(e.value)
    if name in ("a", "c"):
        assert "Unterminated string" in str(e.value)
    data = parse_cut_response(text)
    assert [p["float"] for p in data["placements"]] == floats
    assert data["placements"] == FLOAT_RESPONSE["placements"][:len(floats)]
    assert data["operations"] == [] and data["notes"] == []


@pytest.mark.parametrize("name", ["e", "f"])
def test_cut_response_does_not_guess(name):
    """placements に届く前に切れた回答と、途中の書き損じ（切れた回答ではない）からは何も読まない。最後まで読める回答も対象外。"""
    from jasme_jats.ai_assist import parse_cut_response
    assert parse_cut_response(cut_cases()[name]) is None
    assert parse_cut_response(head_first()) is None and parse_cut_response("提案はありません。") is None
    with pytest.raises(ValueError) as e:
        parse_response(cut_cases()["f"])
    assert "飾りの引用符" in str(e.value)


def test_complete_answers_are_not_read_as_cut():
    """最後まで書かれた回答の書き損じは、途中で切れた回答として読まない（読めない回答として、書き損じの案内を出す）:
    最後の文字列の閉じだけが飾りの引用符の回答（飾りの引用符のすぐ後ろが同じ行の ] } なら、途中で切れた回答と同じ
    「Unterminated string」になるので、飾りの引用符で見分ける。後ろが改行なら「Invalid control character」）、閉じの ``` まで
    書かれたコードブロック（```json・```JSON）の中で JSON が途中で終わっている回答。"""
    from jasme_jats.ai_assist import parse_cut_response
    full, one_line = head_first(), head_first(indent=None)
    smart = full[:full.rindex('"気づき"')] + '"気づき”\n ]\n}'
    smart_one = one_line[:one_line.rindex('"気づき"')] + '"気づき”]}'
    with pytest.raises(json.JSONDecodeError) as e:
        json.loads(smart_one)
    assert e.value.msg.startswith("Unterminated string")
    in_ops = cut_cases()["a"]
    for text in (smart, smart_one, "```json\n" + in_ops + "\n```", "```JSON\n" + in_ops + "\n```"):
        assert parse_cut_response(text) is None
        with pytest.raises(ValueError):
            parse_response(text)
    for text in (smart, smart_one):
        with pytest.raises(ValueError) as e:
            parse_response(text)
        assert "飾りの引用符" in str(e.value) and "途中で切れている" not in str(e.value)
    # 閉じのないコードブロックで切れた回答は、今までどおり読む（対照）
    assert parse_cut_response("```json\n" + in_ops) is not None


def test_cut_inside_string_with_smart_quotes_is_cut():
    """切れた文字列の中に、JSON の文字としての飾りの引用符（「“主張”について」。文字列を閉じていない）があっても、途中で
    切れた回答として、最後まで書かれた placements の要素を読む。読み取りの誤りの案内も「途中で切れている」にする。"""
    from jasme_jats.ai_assist import parse_cut_response
    full = head_first()
    ops = full.index('"reason"', full.index('"operations"'))
    for tail in ("第1章の“主張”についての途中", "第1章の“主張”"):
        text = full[:ops] + '"reason": "' + tail
        data = parse_cut_response(text)
        assert data is not None and data["placements"] == FLOAT_RESPONSE["placements"]
        with pytest.raises(ValueError) as e:
            parse_response(text)
        assert "途中で切れている" in str(e.value) and "飾りの引用符（“ ” など）で囲まれています" not in str(e.value)


def test_code_fence_marks_inside_strings_are_not_blocks():
    """JSON の文字列の中の ``` は、コードブロックの始まり・閉じとみなさない（コードブロックなしの回答・コードブロックの中の
    回答・前置きの説明のある回答）。前置きの説明と同じ行から始まるコードブロックも読む。"""
    body = json.dumps({"placements": FLOAT_RESPONSE["placements"], "operations": [], "notes": ["```の記号の説明"]},
                      ensure_ascii=False, indent=1)
    for text in (body, "```json\n" + body + "\n```", "以下が回答です。\n" + body, "以下が回答です：```json\n" + body + "\n```",
                 "```text\n補足\n```\n```json\n" + body + "\n```"):
        data = parse_response(text)
        assert data["placements"] == FLOAT_RESPONSE["placements"] and data["notes"] == ["```の記号の説明"]
    # { で始まる回答（コードブロックの中身だけをコピーしたもの）は、文字列の中に「```{」があってもコードブロックを探さない
    body = json.dumps({"placements": FLOAT_RESPONSE["placements"], "operations": [], "notes": ["```{ で始まる記号"]},
                      ensure_ascii=False)
    assert parse_response(body)["notes"] == ["```{ で始まる記号"]


def _cut_text():
    return cut_cases()["c"]


def test_api_cut_answers_are_kept(monkeypatch):
    """API の回答が上限で切れたとき、4 社とも、切れたところまでの回答（raw）を残し、切れたこと（cut）を返す。"""
    text = _cut_text()
    calls = []
    _fake_anthropic(monkeypatch, calls, text=text, stop="max_tokens")
    out = ai_assist.call_provider("claude", "x", [], api_key="t")
    assert (out.raw, out.cut) == (text, True) and "途中で切れました" in out.error and out.usage["output_tokens"] == 50
    _fake_openai(monkeypatch, [], status="incomplete", text=text)
    out = ai_assist.call_provider("openai", "x", [], model="gpt-test", api_key="t")
    assert (out.raw, out.cut) == (text, True) and "途中で切れました" in out.error
    _fake_gemini(monkeypatch, [], finish="MAX_TOKENS", text=text)
    out = ai_assist.call_provider("gemini", "x", [], model="gemini-test")
    assert (out.raw, out.cut) == (text, True) and "途中で切れました" in out.error
    _fake_sakana(monkeypatch, [], finish="length", text=text)
    out = ai_assist.call_provider("sakana", "x", [], model="fugu", api_key="k")
    assert (out.raw, out.cut) == (text, True) and "途中で切れました" in out.error
    # 切れていない回答は cut にならない
    _fake_anthropic(monkeypatch, [], text=RESPONSE)
    out = ai_assist.call_provider("claude", "x", [], api_key="t")
    assert not out.cut and out.raw == RESPONSE and not out.error


def test_api_mode_applies_finished_placements_of_cut_answer(journal, meta, tmp_path, monkeypatch):
    """API モードで回答が上限で切れたとき: 最後まで書かれた placements を反映し、誤りは消して、要対応の説明を残す。
    上限で止まっても JSON が最後まで書かれていれば、ふつうに反映する。何も読めなければ、今までどおり誤りにする。"""
    _fake_anthropic(monkeypatch, [], text=_cut_text(), stop="max_tokens")
    res = convert(FLOAT, meta, journal, Options(out_dir=tmp_path / "cut", ai_mode="api", ai_api_key="t",
                                                convert_metafiles=False))
    assert res.ai.error == "" and res.ai.cut and "最後まで書かれていた 1 件だけ" in res.ai.partial
    assert "また途中で切れるときは、「手動（チャットに貼り付け）」に切り替えて" in res.ai.partial   # 同じ上限でまた切れうる
    assert res.plan.floats["s1"].mode == "ai" and res.plan.unplaced_floats == ["s2", "s3"] and res.fidelity.ok
    _fake_anthropic(monkeypatch, [], text=head_first(), stop="max_tokens")
    res = convert(FLOAT, meta, journal, Options(out_dir=tmp_path / "whole", ai_mode="api", ai_api_key="t",
                                                convert_metafiles=False))
    assert res.ai.error == "" and res.ai.partial == "" and res.plan.unplaced_floats == []
    _fake_anthropic(monkeypatch, [], text=cut_cases()["e"], stop="max_tokens")
    res = convert(FLOAT, meta, journal, Options(out_dir=tmp_path / "none", ai_mode="api", ai_api_key="t",
                                                convert_metafiles=False))
    assert res.ai.error == "AI の回答が長すぎて途中で切れました"            # API の誤り（JSON の読み取りの誤りにしない）
    assert res.ai.partial == "" and res.plan.unplaced_floats == ["s1", "s2", "s3"]


def test_cli_stops_without_api_key(monkeypatch, capsys):
    """コマンドラインで --ai api を指定し API キーがなければ、トレースバックではなく引数の誤りとして止める（N5）。"""
    import pytest

    from jasme_jats.cli import main
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(SystemExit) as e:
        main([str(FULL), "--ai", "api"])
    assert e.value.code == 2 and "ANTHROPIC_API_KEY" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main([str(FULL), "--ai", "api", "--ai-provider", "openai", "--ai-model", "gpt-test"])
    assert "OPENAI_API_KEY" in capsys.readouterr().err


def test_call_api_reports_missing_key(monkeypatch):
    """anthropic のライブラリは API キーがないと、送るときに TypeError を投げる。止まらずにエラーとして記録する（N5）。"""
    import anthropic

    def no_key(**kw):
        raise TypeError('"Could not resolve authentication method. Expected one of api_key, auth_token, or credentials"')

    class FakeClient:
        def __init__(self, *a, **k):
            self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(stream=no_key))
            self.messages = self.beta.messages
    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    out = ai_assist.call_api("x", [], model="claude-test")
    assert "API キーが見つかりません" in out.error and "ANTHROPIC_API_KEY" in out.error and not out.raw


def test_call_api_other_type_error_is_not_api_key(monkeypatch):
    """API キーがあるのに出た TypeError（古いライブラリが引数を受け付けないなど）は、「API キーが見つかりません」にしない。"""
    import anthropic

    def old_sdk(**kw):
        raise TypeError("stream() got an unexpected keyword argument 'fallbacks'")

    class FakeClient:
        def __init__(self, *a, **k):
            self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(stream=old_sdk))
            self.messages = self.beta.messages
    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    out = ai_assist.call_api("x", [], model="claude-test", api_key="sk-test")
    assert out.error == "AI の呼び出しに失敗しました: stream() got an unexpected keyword argument 'fallbacks'"
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = ai_assist.call_api("x", [], model="claude-test")       # API キーがどこにもなければ、API キーの知らせ
    assert "API キーが見つかりません" in out.error


# ----------------------------------------------------------------------------- set_role の可否（修正計画の N6・D3）
S = mf.S


def _set_role(src, role):
    return {"op": "set_role", "src": src, "text": "", "occurrence": 1, "target": "", "role": role, "image": "",
            "confidence": "高", "reason": "試験"}


def _manual(path, ops, meta, journal, out):
    resp = json.dumps({"operations": ops, "placements": [], "notes": []}, ensure_ascii=False)
    return convert(path, meta, journal, Options(out_dir=out, ai_mode="manual", ai_response=resp, convert_metafiles=False))


def _text(el):
    return "".join(el.itertext())


def _apps(root):
    return [(_text(a.find("title")), [_text(p) for p in a.findall("p")]) for a in root.iter("app")]


def _abstract(root):
    return [_text(p) for p in root.findall(".//trans-abstract/p")]


def _body(b):
    return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "本文。")]


def test_set_role_app_heading_starts_appendix(journal, meta, tmp_path):
    # 英文要旨に入った資料の和文の段落に app_heading を指定すると、その段落から資料になる（D3）
    path = tmp_path / "app.docx"
    mf.make_article(path, "資料の見出しの検証用文書", _body,
                    abstract=["Small article abstract.", "架空の授業の記録", "架空の記録の本文である。"])
    _, plan, _ = _mechanical(path, journal)
    src = next(s for s, p in plan.paras.items() if p.plain() == "架空の授業の記録")
    assert src in plan.abstract_ja                       # AI に渡す前は、英文要旨の中の和文として知らせている
    res = _manual(path, [_set_role(src, "app_heading")], meta, journal, tmp_path / "out")
    assert res.ai.rejected == [] and [op["role"] for op, _ in res.ai.accepted] == ["app_heading"]
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and res.jstage_issues == []
    root = load(res)
    assert _apps(root) == [("架空の授業の記録", ["架空の記録の本文である。"])]
    assert _abstract(root) == ["Small article abstract."]
    assert res.plan.abstract_ja == [] and "abstract_ja" not in {a.key for a in actions(res)}


def test_set_role_on_english_title_is_rejected(journal, meta, tmp_path):
    # 英文の題目への set_role は、どの役割も採用しない（暫定の判断。0.23.1 は英文題目を exclude・abstract にすると、英文副題が
    # XML から落ちていた）。英文題目・副題はそのまま
    path = tmp_path / "title.docx"
    mf.make_article(path, "英文題目の検証用文書", _body)
    _, plan, _ = _mechanical(path, journal)
    title = plan.title_en[0].src
    res = _manual(path, [_set_role(title, "app_heading"), _set_role(title, "exclude"), _set_role(title, "abstract")],
                  meta, journal, tmp_path / "out")
    assert [why for _, why in res.ai.rejected] == ["英文の題目・副題の段落の役割は変えられない（変えると英文の題目・副題が XML から落ちる）"] * 3
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    root = load(res)
    assert _text(root.find(".//article-meta/title-group/trans-title-group/trans-title")) == "A Small Article"
    assert _text(root.find(".//article-meta/title-group/trans-title-group/trans-subtitle")) == "For Checking"
    assert root.find(".//app-group") is None


def test_set_role_abstract_returns_heading_style_appendix(journal, meta, tmp_path):
    # 見出しのスタイルで始めた資料（英文要旨の後ろの章見出しのスタイル）の見出しに abstract を指定すると、その段落と、
    # 次の資料の見出しまでの段落が英文要旨に戻る（D3。資料の領域に abstract を指定できる）
    path = tmp_path / "back.docx"
    mf.make_article(path, "英文要旨に戻す検証用文書", _body,
                    appendix=[mf.para(S["sec1"], "Supplementary note"), mf.para(S["body"], "The rest of the abstract."),
                              mf.para(S["abs"], "資料1\u3000架空の授業プリント"), mf.para(S["abs"], "架空のプリントの本文。")])
    _, plan, _ = _mechanical(path, journal)
    src = next(s for s, p in plan.paras.items() if p.plain() == "Supplementary note")
    assert plan.region[src] == "app"
    res = _manual(path, [_set_role(src, "abstract")], meta, journal, tmp_path / "out")
    assert res.ai.rejected == [] and res.fidelity.ok and res.dtd_valid
    root = load(res)
    assert _abstract(root) == ["Small article abstract.", "Supplementary note", "The rest of the abstract."]
    assert _apps(root) == [("資料1\u3000架空の授業プリント", ["架空のプリントの本文。"])]
    assert not any(d.src == src and "から資料とした" in d.message for d in res.plan.decisions)
    # 資料の途中の段落に abstract を指定すると、その段落から次の資料の見出しまでが英文要旨に戻る
    path = tmp_path / "middle.docx"
    mf.make_article(path, "英文要旨に戻す検証用文書", _body,
                    appendix=[mf.para(S["abs"], "資料1\u3000架空の授業プリント"), mf.para(S["abs"], "架空のプリントの本文。"),
                              mf.para(S["abs"], "The rest of the abstract."), mf.para(S["abs"], "And one more sentence."),
                              mf.para(S["abs"], "資料2\u3000架空の調査票"), mf.para(S["abs"], "架空の調査票の本文。")])
    _, plan, _ = _mechanical(path, journal)
    src = next(s for s, p in plan.paras.items() if p.plain() == "The rest of the abstract.")
    assert plan.region[src] == "app"
    res = _manual(path, [_set_role(src, "abstract")], meta, journal, tmp_path / "out2")
    assert res.ai.rejected == [] and res.fidelity.ok and res.dtd_valid
    root = load(res)
    assert _abstract(root) == ["Small article abstract.", "The rest of the abstract.", "And one more sentence."]
    assert _apps(root) == [("資料1\u3000架空の授業プリント", ["架空のプリントの本文。"]),
                           ("資料2\u3000架空の調査票", ["架空の調査票の本文。"])]


def test_set_role_overrides_appendix_heading_text(journal, meta, tmp_path):
    # 「資料」「Appendix」などで始まる見出しの形の段落でも、AI が abstract・p を指定すれば資料の見出しにしない（AI の指定を文字の
    # 規則より優先する。D3）。英文要旨の「Appendix A: …」は英文要旨に戻り、資料の中の「資料2：…」は前の資料の段落になる
    path = tmp_path / "text.docx"
    mf.make_article(path, "資料の見出しの文字の検証用文書", _body,
                    abstract=["Small article abstract.", "Appendix A: questionnaire items"],
                    appendix=[mf.para(S["abs"], "資料1\u3000架空の授業プリント"), mf.para(S["abs"], "架空のプリントの本文。"),
                              mf.para(S["abs"], "資料2：架空の回答の例"), mf.para(S["abs"], "架空の回答の本文。")])
    _, plan, _ = _mechanical(path, journal)
    by_text = {p.plain(): s for s, p in plan.paras.items()}
    appendix_a, answer = by_text["Appendix A: questionnaire items"], by_text["資料2：架空の回答の例"]
    assert [a.title.src for a in plan.apps] == [appendix_a, by_text["資料1\u3000架空の授業プリント"], answer]   # 機械的には 3 つの資料
    res = _manual(path, [_set_role(appendix_a, "abstract"), _set_role(answer, "p")], meta, journal, tmp_path / "out")
    assert res.ai.rejected == [] and res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    root = load(res)
    assert _abstract(root) == ["Small article abstract.", "Appendix A: questionnaire items"]
    assert _apps(root) == [("資料1\u3000架空の授業プリント", ["架空のプリントの本文。", "資料2：架空の回答の例", "架空の回答の本文。"])]


def test_set_role_p_on_first_appendix_heading(journal, meta, tmp_path):
    # 前に資料のない資料の見出し（最初の資料の見出し）に p を指定すると、見出しのない資料の最初の段落になる（資料の中の段落。
    # 後ろの段落も資料のまま）。資料の文字を英文要旨に入れない（英文要旨に戻すのは abstract だけ。修正前は、見出しと後ろの段落が
    # 英文要旨に入っていた）
    path = tmp_path / "first.docx"
    mf.make_article(path, "資料の最初の見出しの検証用文書", _body,
                    appendix=[mf.para(S["abs"], "資料1\u3000架空の授業プリント"), mf.para(S["abs"], "問1\u3000架空の問い。"),
                              mf.para(S["abs"], "問2\u3000もう一つの架空の問い。")])
    _, plan, _ = _mechanical(path, journal)
    src = next(s for s, p in plan.paras.items() if p.plain() == "資料1\u3000架空の授業プリント")
    assert [a.title.src for a in plan.apps] == [src]
    res = _manual(path, [_set_role(src, "p")], meta, journal, tmp_path / "out")
    assert res.ai.rejected == [] and [op["role"] for op, _ in res.ai.accepted] == ["p"]
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and res.jstage_issues == []
    root = load(res)
    assert _abstract(root) == ["Small article abstract."]
    assert _apps(root) == [("", ["資料1\u3000架空の授業プリント", "問1\u3000架空の問い。", "問2\u3000もう一つの架空の問い。"])]
    assert res.plan.region[src] == "app" and res.plan.apps[0].title is None


def test_set_role_problem_rules(journal):
    # set_role の可否は set_role_problem の 1 か所で決める（回答の検証と、依頼文の除外の一覧の案内で使う。N6）
    from jasme_jats.ai_assist import set_role_problem
    _, plan, _ = _mechanical(STRUCTURE, journal)
    by_text = {p.plain(): p for p in plan.paras.values()}
    body = by_text["囲みの後の本文も，本文のまま続く。"]
    endnote = next(fn.paras[0] for fn in plan.fns if fn.word_id == "endnote:5")
    unref = next(plan.paras[s] for s, k in plan.note_of.items() if k == "footnote:9")
    shape = by_text["Area model"]
    abstract = by_text["Structure abstract."]
    app_title = by_text["資料（授業プリント）"]
    app_para = by_text["問1\u3000架空の問題文である。"]
    front = next(p for p in plan.paras.values() if plan.region.get(p.src) == "front_ja")
    assert set_role_problem(body, plan, "heading") == "役割「heading」は指定できない"                        # 1
    assert "placements" in set_role_problem(shape, plan, "p")                                                  # 2
    for p, role in ((endnote, "p"), (endnote, "exclude"), (unref, "p")):                                        # 3
        assert set_role_problem(p, plan, role) == "Word の脚注・文末脚注の段落の役割は変えられない（注の区切りは Word のとおりにする）"
    cell = Para(src="zz1")
    plan.paras[cell.src] = cell                                                                                 # 4（領域のない段落）
    assert set_role_problem(cell, plan, "p") == "表のセルなど、論文の中の位置が決まっていない段落の役割は変えられない"
    assert set_role_problem(plan.title_en[0], plan, "abstract").startswith("英文の題目・副題の段落の役割は変えられない")   # 5
    assert set_role_problem(body, plan, "app_heading") == "資料の見出し（app_heading）にできるのは、英文要旨と資料の段落だけ"  # 6
    assert set_role_problem(plan.abstract_heading, plan, "app_heading") == (       # 英文要旨の見出しから資料にはしない
        "資料の見出し（app_heading）にできるのは、英文要旨と資料の段落だけ")
    assert set_role_problem(front, plan, "p") == "この位置（front_ja）では役割「p」を指定できない"                # 7
    # 指定できるもの
    assert set_role_problem(body, plan, "p") == "" and set_role_problem(abstract, plan, "app_heading") == ""
    assert set_role_problem(app_title, plan, "abstract") == "" and set_role_problem(app_para, plan, "app_heading") == ""


def test_request_hints_follow_set_role_problem(journal, tmp_path):
    # 依頼文の除外の一覧の案内は、set_role_problem で指定できる役割だけを勧める（0.23.1 は、冒頭・著者表・Word の注の段落にも
    # 「本文の一部なら set_role を提案」と書き、必ず捨てられる set_role を勧めていた。N6）
    from jasme_jats.ai_assist import ROLES, build_request, system_prompt

    def hints(path):
        _, plan, linker = _mechanical(path, journal)
        req, _ = build_request(plan, linker)
        return {ln.split("]")[0][3:]: ln for ln in req.splitlines() if ln.startswith("- [") and "出力から除外" in ln}, plan
    lines, plan = hints(STRUCTURE)
    _, plan2, linker = _mechanical(STRUCTURE, journal)
    req = build_request(plan2, linker)[0]
    # 文末脚注の参照は「⟦Word の文末脚注参照⟧」、注の一覧の Word の注は「（Word の文末脚注 5）」と書く
    assert "脚注を付けた文⟦Word の脚注参照⟧と文末脚注を付けた文⟦Word の文末脚注参照⟧。" in req
    assert "[fn2]（Word の文末脚注 5）注" in req and "[fn1]（Word の脚注 5）注" in req
    journal_line = next(e.src for e in plan.exclusions if e.reason.startswith("冒頭部のテンプレート装飾"))
    assert lines[journal_line].endswith("（set_role で指定できる役割: title, subtitle）")
    unref = next(s for s, k in plan.note_of.items() if k == "footnote:9")
    assert lines[unref].endswith("（この段落の役割は set_role では変えられない）")
    lines, plan = hints(FULL)
    dup = next(e.src for e in plan.exclusions if e.reason.startswith("重複する所属"))
    assert lines[dup].endswith("（この段落の役割は set_role では変えられない）")      # 著者表の中の段落
    # 本文の段落（浮動配置でないテキストボックスの中の文字）は、今までどおり p を勧める
    vml = ('<w:r><w:pict><v:shape style="width:200pt;height:40pt"><v:textbox><w:txbxContent>'
           + mf.para(S["body"], "囲みの中の架空の問題文。") + "</w:txbxContent></v:textbox></v:shape></w:pict></w:r>")
    path = tmp_path / "vml.docx"
    mf.make_article(path, "依頼文の案内の検証用文書", lambda b: [mf.para(S["sec1"], "１．はじめに"),
                                                               mf.para(S["body"], "囲みを付けた本文。", vml)])
    lines, plan = hints(path)
    box = next(s for s, p in plan.paras.items() if p.plain() == "囲みの中の架空の問題文。")
    assert lines[box].endswith("（本文の一部なら set_role を提案）")
    # 依頼文の役割の一覧と説明に、資料の見出し（app_heading）がある
    assert "app_heading（資料の見出し（英文要旨の後ろの、資料・付録の始まり））" in system_prompt()
    assert "資料の見出しの段落を app_heading にしてください" in system_prompt() and "app_heading" in ROLES
    assert "見出しではなく資料の中の文のときは p にしてください（前の資料の続きになります。前に資料がなければ" in system_prompt()
