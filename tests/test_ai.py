"""AI 補完: 回答の検証と適用（実際の API は呼ばない）。"""
import inspect
import json
import types
from pathlib import Path

import pytest
from lxml import etree

import make_fixtures as mf
from conftest import DATA, FLOAT, FULL, STRUCTURE
from jasme_jats import ai_assist
from jasme_jats import pipeline
from jasme_jats.ai_assist import DEFAULT_MODEL, parse_response, parse_mathml
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
    assert calls["model"] == DEFAULT_MODEL
    assert calls["output_config"]["format"]["type"] == "json_schema"
    assert calls["fallbacks"] == "default"
    assert not res.ai.error
    assert len(res.ai.accepted) == 7 and res.fidelity.ok


def test_default_model_is_written_once(tmp_path):
    """既定の AI モデル名は ai_assist.DEFAULT_MODEL の 1 か所にだけ書き、表示名・料金・提供終了の予定は DEFAULT_MODEL_INFO の
    1 か所にだけ書く（修正計画の U5）。pipeline.Options の既定もこれで、ノートブックの生成スクリプト（tools/make_notebook.py）は
    ai_assist.py から読む（tests/test_notebook.py）。ほかの src のファイルと make_notebook.py に、同じ値の直書きがないことを数える。"""
    from jasme_jats.ai_assist import DEFAULT_MODEL_INFO
    assert Options(out_dir=tmp_path).ai_model == DEFAULT_MODEL
    info = DEFAULT_MODEL_INFO
    y, m, d = (int(x) for x in info["not_before"].split("-"))
    literals = [f'"{DEFAULT_MODEL}"', info["name"], info["not_before"], f"{y} 年 {m} 月 {d} 日",
                f"あたり {info['input_usd']} ドル", f"あたり {info['output_usd']} ドル"]
    root = Path(pipeline.__file__).resolve().parent
    for path in sorted(root.glob("*.py")) + [root.parent.parent / "tools" / "make_notebook.py"]:
        body = path.read_text(encoding="utf-8")
        for lit in literals:
            want = 1 if path.name == "ai_assist.py" and lit in (f'"{DEFAULT_MODEL}"', info["name"], info["not_before"]) else 0
            assert body.count(lit) == want, (path, lit)


def test_response_schema_is_strict():
    op = ai_assist.OP_SCHEMA
    assert op["additionalProperties"] is False
    assert set(op["required"]) == set(op["properties"])
    json.dumps(ai_assist.RESPONSE_SCHEMA)


def _fake_anthropic(monkeypatch, calls, available=(DEFAULT_MODEL,), listed=(), text=RESPONSE, stop="end_turn"):
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
    assert calls == [DEFAULT_MODEL, "claude-opus-6"] and res.ai.model == "claude-opus-6"
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
    for model in ("", "auto", DEFAULT_MODEL):
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


def test_set_role_p_after_abstract_keeps_abstract(journal, meta, tmp_path):
    # AI が資料の見出しを abstract で英文要旨に戻し、その後ろの段落（資料の中の段落）に p も指定したとき、p の段落から見出しのない
    # 資料を始めない（英文要旨のまま。次の資料の見出しまで英文要旨に戻すという abstract の意味のとおり）。後ろの資料の見出しへの p は、
    # 前に資料がないので、今までどおり見出しのない資料の最初の段落になる
    path = tmp_path / "back.docx"
    mf.make_article(path, "英文要旨に戻す検証用文書", _body,
                    appendix=[mf.para(S["abs"], "Appendix 1: The fictional second abstract paragraph"),
                              mf.para(S["abs"], "The fictional third abstract paragraph."),
                              mf.para(S["abs"], "資料2\u3000架空の授業プリント"), mf.para(S["abs"], "架空のプリントの本文。")])
    _, plan, _ = _mechanical(path, journal)
    by_text = {p.plain(): s for s, p in plan.paras.items()}
    head, third, head2 = (by_text[t] for t in ("Appendix 1: The fictional second abstract paragraph",
                                               "The fictional third abstract paragraph.", "資料2\u3000架空の授業プリント"))
    assert plan.region[third] == "app" and [a.title.src for a in plan.apps] == [head, head2]
    res = _manual(path, [_set_role(head, "abstract"), _set_role(third, "p")], meta, journal, tmp_path / "out")
    assert res.ai.rejected == [] and res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    root = load(res)
    assert _abstract(root) == ["Small article abstract.", "Appendix 1: The fictional second abstract paragraph",
                               "The fictional third abstract paragraph."]
    assert _apps(root) == [("資料2\u3000架空の授業プリント", ["架空のプリントの本文。"])]
    [d] = [d for op, d in res.ai.accepted if op["src"] == third]       # 役割が変わらなかったことを、そのとおりに記録する
    assert d.message == ("段落を資料の中の段落（p）にする指定だが、AI の abstract で英文要旨に戻した後ろの段落なので、英文要旨の段落の"
                         "ままにした。試験") and d.location == "英文要旨 第3段落"
    res = _manual(path, [_set_role(head, "abstract"), _set_role(third, "p"), _set_role(head2, "p")], meta, journal, tmp_path / "out2")
    assert res.ai.rejected == [] and res.fidelity.ok and res.dtd_valid
    root = load(res)
    assert _abstract(root) == ["Small article abstract.", "Appendix 1: The fictional second abstract paragraph",
                               "The fictional third abstract paragraph."]
    assert _apps(root) == [("", ["資料2\u3000架空の授業プリント", "架空のプリントの本文。"])]
    assert [d.message for op, d in res.ai.accepted if op["src"] == head2] == ["段落の役割を「本文段落」とした。試験"]
    # 英文要旨の段落への abstract（指定しても変わらない）の後ろでも、最初の資料の見出し（見出しのスタイルの段落）への p は、見出しの
    # ない資料の最初の段落になる（見出しと資料の段落を英文要旨に入れない）
    path = tmp_path / "style.docx"
    mf.make_article(path, "英文要旨に戻す検証用文書", _body,
                    appendix=[mf.para(S["sec1"], "授業の記録"), mf.para(S["body"], "架空の記録の本文。")])
    _, plan, _ = _mechanical(path, journal)
    by_text = {p.plain(): s for s, p in plan.paras.items()}
    res = _manual(path, [_set_role(by_text["Small article abstract."], "abstract"), _set_role(by_text["授業の記録"], "p")],
                  meta, journal, tmp_path / "out3")
    assert res.ai.rejected == [] and res.fidelity.ok and res.dtd_valid
    root = load(res)
    assert _abstract(root) == ["Small article abstract."]
    assert _apps(root) == [("", ["授業の記録", "架空の記録の本文。"])]


def test_sentence_decision_is_not_recorded_for_ai_roles(journal, meta, tmp_path):
    # 見出しの形に合うが文とみなした段落の判断（「…資料の見出しにしなかった」。applied=False）は、AI が役割を指定した段落には
    # 記録しない（AI が決めたことなので、4 章と依頼文で、資料の見出しにできるという案内を繰り返さない）
    path = tmp_path / "sentence.docx"
    mf.make_article(path, "文の形の段落の検証用文書", _body, abstract=["Small article abstract.", "(Appendix 1) lists the fictional tasks."],
                    appendix=[mf.para(S["abs"], "資料1\u3000架空の授業プリント"),
                              mf.para(S["abs"], "資料2（後掲）に示すように、架空の問いを並べた。")])
    _, plan, _ = _mechanical(path, journal)
    by_text = {p.plain(): s for s, p in plan.paras.items()}
    s1, s2 = by_text["(Appendix 1) lists the fictional tasks."], by_text["資料2（後掲）に示すように、架空の問いを並べた。"]

    def sentence_decisions(plan):
        return [d.src for d in plan.decisions if "資料の見出しにしなかった" in d.message]
    assert sentence_decisions(plan) == [s1, s2]               # 機械処理では記録する
    res = _manual(path, [_set_role(s1, "abstract"), _set_role(s2, "p")], meta, journal, tmp_path / "out")
    assert res.ai.rejected == [] and res.fidelity.ok and res.dtd_valid
    assert sentence_decisions(res.plan) == []
    root = load(res)
    assert _abstract(root) == ["Small article abstract.", "(Appendix 1) lists the fictional tasks."]
    assert _apps(root) == [("資料1\u3000架空の授業プリント", ["資料2（後掲）に示すように、架空の問いを並べた。"])]


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
    # 囲みか図の注記か決められなかったテキストボックス（浮動配置でない VML）の段落には、placements の kind box・label を勧める
    # （set_role p は採用されないので勧めない。修正計画の F）
    assert lines[box].endswith("（囲みなら placements の kind box、図の注記なら label で指定）")
    # 依頼文の役割の一覧と説明に、資料の見出し（app_heading）がある
    assert "app_heading（資料の見出し（英文要旨の後ろの、資料・付録の始まり））" in system_prompt()
    assert "資料の見出しの段落を app_heading にしてください" in system_prompt() and "app_heading" in ROLES
    assert "見出しではなく資料の中の文のときは p にしてください（前の資料の続きになります。前に資料がなければ" in system_prompt()


# ----------------------------------------------------------------------------- 文字だけのテキストボックス（修正計画の D1）
def _boxes_by_text(journal):
    """sample_structure の、1 回目の組み立ての plan と、文字だけのテキストボックスの最初の段落の文字 -> ID。"""
    _, plan, _ = _mechanical(STRUCTURE, journal)
    return plan, {next((q.plain() for q in bi.paras if not q.is_blank), ""): x for x, bi in plan.textboxes.items()}


def _src(plan, head):
    return next(s for s, p in plan.paras.items() if p.plain().startswith(head))


def _box_pl(xid, after, kind="box", **kw):
    item = {"kind": kind, "caption": [], "body": []}
    item.update(kw)
    return {"float": xid, "after": after, "items": [item], "reason": "試験の回答", "confidence": "中"}


def _manual_pl(path, placements, meta, journal, out, ops=()):
    resp = json.dumps({"placements": placements, "operations": list(ops), "notes": []}, ensure_ascii=False)
    return convert(path, meta, journal, Options(out_dir=out, ai_mode="manual", ai_response=resp, convert_metafiles=False))


def test_ai_kind_box_and_label_for_undecided_textboxes(journal, meta, tmp_path):
    # 囲みか図の注記か決められなかったテキストボックスは、AI の placements（kind box・label）で決める。box は指定の段落の直後の
    # boxed-text（ずらさない）、label は AI の判断の理由で除外する。どちらも 2 章の採用の一覧に place_float として載る
    plan, ids = _boxes_by_text(journal)
    hint, note = ids["（ヒント）"], ids["注"]
    assert plan.textboxes[hint].kind == plan.textboxes[note].kind == "undecided"
    res = _manual_pl(STRUCTURE, [_box_pl(hint, _src(plan, "囲みの後の段落である。")), _box_pl(note, "", kind="label")],
                     meta, journal, tmp_path)
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and res.jstage_issues == []
    root = load(res)
    bt = next(bt for bt in root.iter("boxed-text") if _text(bt) == "（ヒント）")
    assert _text(bt.getprevious()) == "囲みの後の段落である。" and _text(bt.getnext()) == "ヒントを付けた。"
    accepted = {op["src"]: d for op, d in res.ai.accepted if op["op"] == "place_float"}
    assert set(accepted) == {hint, note} and accepted[hint] is res.plan.float_decisions[hint]
    assert accepted[hint].category == "box" and "囲み（boxed-text）として段落「囲みの後の段落である。」の後に置いた" in accepted[hint].message
    reasons = {t: why for _, why, t in res.fidelity.excluded}
    assert reasons["注"] == "テキストボックス内の文字（AI による補完で図に重ねた注記と判断し、本文から除外）"
    # 10 章の警告は、AI の判断だと分かるように書き、AI に出し直してもらうことを勧める（機械的な判断の警告とは別の文面）
    [warn] = [w for w in res.warnings if f"テキストボックス {note} の文字を" in w]
    assert f"AI が図に重ねた注記と判断したテキストボックス {note} の文字を、本文から除外しました（2 章・6 章）。" in warn
    assert warn.endswith("AI に出し直してもらうか、Word で文字をテキストボックスの外に出して変換し直してください")
    # 2 章の説明: 文字だけのテキストボックスがある論文では、囲み・図の注記の判断も AI が変えられることを書く
    ch2 = res.report_path.read_text(encoding="utf-8").split("## 2.")[1].split("## 3.")[0]
    assert "図表の位置と組み合わせ、文字だけのテキストボックスの囲み・図の注記の判断と囲みの位置だけで、本文の文字は" in ch2
    assert (res.plan.textboxes[hint].kind, res.plan.textboxes[hint].mode, res.plan.textboxes[hint].where) == ("box", "ai", "ai")
    # 残った 1 件（Area model）だけが、要確認として残る（AI の回答を反映した後の文面）
    act = next(a for a in actions(res) if a.key == "textbox_undecided")
    assert "1 件" in act.box_title and "採用されませんでした" in act.box_detail
    report = res.report_path.read_text(encoding="utf-8")
    assert "| 囲み・図の注記（テキストボックス） |" in report.split("## 2.")[1].split("## 3.")[0]


def test_ai_kind_box_restores_mechanical_label(journal, meta, tmp_path):
    # 図に重ねた注記と機械的に判断したテキストボックスも、本文の文字（問題文など）なら、AI が placements の kind box で本文の
    # 囲みに戻せる（F の確かめで足した暫定の判断。それまでは「扱いを機械的に決めたので変更できない」で採用せず、図の近くの
    # 短い問題文が XML から消えたまま AI でも戻せなかった）。依頼文では、変更不可の節ではなく、戻せる節に中身と一緒に載せる
    from jasme_jats.ai_assist import build_request
    plan, ids = _boxes_by_text(journal)
    label, a_src, after = ids["A 点"], _src(plan, "A 点"), _src(plan, "図1の点に名前を付けた。")
    assert plan.textboxes[label].kind == "label"
    _, plan1, linker = _mechanical(STRUCTURE, journal)
    req, _ = build_request(plan1, linker)
    assert (f"- [{a_src}] 出力から除外: テキストボックス内の文字（図に重ねた注記とみなして本文から除外）: 「A 点」"
            "（図の注記でなく本文の文章なら、placements の kind box で囲みに指定）") in req
    res = _manual_pl(STRUCTURE, [_box_pl(label, after)], meta, journal, tmp_path)
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and res.jstage_issues == []
    bt = next(bt for bt in load(res).iter("boxed-text") if _text(bt) == "A 点")
    assert _text(bt.getprevious()) == "図1の点に名前を付けた。" and bt.getparent().tag == "sec"
    [(op, d)] = [(op, d) for op, d in res.ai.accepted if op["op"] == "place_float"]
    assert op["src"] == label and d is res.plan.float_decisions[label] and d.category == "box"
    assert "を囲み（boxed-text）として段落「図1の点に名前を付けた。」の後に置いた（機械的には図に重ねた注記と判断していた）。" in d.message
    assert "A 点" not in {t for _, _, t in res.fidelity.excluded} and res.ai.rejected == []
    assert not any("図に重ねた注記と判断したテキストボックス" in w for w in res.warnings)
    info = res.plan.textboxes[label]
    assert (info.kind, info.mode, info.where, info.estimated) == ("box", "ai", "ai", False)
    # 1 章の「テキストボックスの文字」の行は、AI の判断（2 章）と機械的な判断（4 章）の両方があるときに両方の章を示す
    assert "| テキストボックスの文字（2 章・3 章・4 章・6 章） |" in res.report_path.read_text(encoding="utf-8").split("## 2.")[0]
    # kind label（注記のまま）は採用しない。注記のまま除外し、10 章の警告に、本文の文字なら囲みに指定できることを書く
    res = _manual_pl(STRUCTURE, [_box_pl(label, "", kind="label")], meta, journal, tmp_path / "label")
    assert [why for _, why in res.ai.rejected] == [
        f"テキストボックス {label} は図に重ねた注記とみなして除外したので、指定できるのは box（本文の囲みに戻す）だけ（図の注記のままなら書かない）"]
    assert {t: w for _, w, t in res.fidelity.excluded}["A 点"] == "テキストボックス内の文字（図に重ねた注記とみなして本文から除外）"
    [warn] = [w for w in res.warnings if "図に重ねた注記と判断したテキストボックス" in w]
    assert warn.endswith("（6 章）。図の注記でなく本文の文字（問題文など）なら、AI による補完で囲みに指定するか、Word で文字を"
                         "テキストボックスの外に出して変換し直してください")


@pytest.mark.parametrize("make, why", [
    (lambda p, ids: _box_pl(ids["（ヒント）"], _src(p, "問1　架空の三角形")), "本文の段落ではない"),     # 囲みの中の段落
    # 浮動配置でない（行内の）囲みの中の段落（textbox_id だけで plan.body_seq から除く。修正計画の F の (4)）
    (lambda p, ids: _box_pl(ids["（ヒント）"], _src(p, "問2　架空の問い")), "本文の段落ではない"),
    (lambda p, ids: _box_pl(ids["（ヒント）"], _src(p, "試験七郎（2025）")), "本文の段落ではない"),        # 引用文献の段落
    (lambda p, ids: _box_pl(ids["（ヒント）"], _src(p, "試験　七郎")), "本文の段落ではない"),             # 著者表のセル
    (lambda p, ids: _box_pl(ids["問1　架空の三角形の面積を求めよ。底辺と高さは図に示す。"], _src(p, "囲みの後の段落")),
     "は囲み（boxed-text）として扱いと位置を機械的に決めたので、変更できない"),
    (lambda p, ids: _box_pl(ids["問2　架空の問いを二つの式で考えよ。"], "", kind="label"),     # 行内の囲み
     "は囲み（boxed-text）として扱いと位置を機械的に決めたので、変更できない"),
    (lambda p, ids: _box_pl(ids[""], _src(p, "囲みの後の段落")), "は扱いを機械的に決めたので、変更できない"),   # 空白だけ
    # 図に重ねた注記とみなしたもの: 本文の囲みに戻す box だけを受け付ける（注記のままなら書かない）
    (lambda p, ids: _box_pl(ids["A 点"], "", kind="label"), "指定できるのは box（本文の囲みに戻す）だけ（図の注記のままなら書かない）"),
    (lambda p, ids: _box_pl(ids["A 点"], _src(p, "問1　架空の三角形")), "本文の段落ではない"),
    (lambda p, ids: _box_pl(ids["問3　架空の数の列の規則を説明せよ。"], "", kind="label"), "box だけを指定できる"),
    (lambda p, ids: _box_pl(ids["（ヒント）"], _src(p, "囲みの後の段落"), caption=[_src(p, "（ヒント）")]), "空の一覧 [] にする"),
    (lambda p, ids: {**_box_pl(ids["（ヒント）"], _src(p, "囲みの後の段落")),
                     "items": [{"kind": "box", "caption": [], "body": []}] * 2}, "1 つだけ書く"),
    (lambda p, ids: _box_pl(ids["（ヒント）"], _src(p, "囲みの後の段落"), kind="fig"), "1 つだけ書く"),
    (lambda p, ids: _box_pl("x99", _src(p, "囲みの後の段落")), "にない"),
])
def test_ai_textbox_placements_are_validated(journal, make, why):
    from jasme_jats.ai_assist import AIOutcome, float_placements
    plan, ids = _boxes_by_text(journal)
    out = AIOutcome()
    got = float_placements({"placements": [make(plan, ids)]}, plan, out)
    assert got == {} and len(out.rejected) == 1 and why in out.rejected[0][1]


def test_ai_textbox_placement_twice_and_estimated_box(journal, meta, tmp_path):
    # 同じテキストボックスの 2 回目の指定は採用しない。位置を推定した囲みは、kind box で位置だけを指定し直せる（要確認は消える）
    from jasme_jats.ai_assist import AIOutcome, float_placements
    plan, ids = _boxes_by_text(journal)
    hint, est = ids["（ヒント）"], ids["問3　架空の数の列の規則を説明せよ。"]
    out = AIOutcome()
    got = float_placements({"placements": [_box_pl(hint, "", kind="label"), _box_pl(hint, _src(plan, "囲みの後の段落"))]},
                           plan, out)
    assert got[hint]["kind"] == "label" and "2 回ある" in out.rejected[0][1]
    assert plan.estimated_boxes == [est]
    res = _manual_pl(STRUCTURE, [_box_pl(est, _src(plan, "空の囲みを置いた。"))], meta, journal, tmp_path)
    assert res.fidelity.ok and res.dtd_valid and res.plan.estimated_boxes == []
    bt = next(bt for bt in load(res).iter("boxed-text") if _text(bt).startswith("問3"))
    assert _text(bt.getprevious()) == "空の囲みを置いた。"
    assert "textbox_place" not in [a.key for a in actions(res)]
    # 浮動配置の図形（位置を決められなかった図表）に kind box を書いたものは採用しない
    _, fplan, _ = _mechanical(FLOAT, journal)
    out = AIOutcome()
    assert float_placements({"placements": [_box_pl("s1", "d13")]}, fplan, out) == {}
    assert "items の kind は fig か table" in out.rejected[0][1]


def test_set_role_on_textbox_paragraphs(journal, meta, tmp_path):
    # 浮動配置でないテキストボックス（VML・行内）の段落に set_role で指定できるのは fig_caption・table_caption・exclude だけ
    # （ほかは placements の kind box・label を案内して採用しない。修正計画の F の (1)）。浮動配置の図形の段落は今までどおり
    # すべて placements で指定させる。VML のキャプションへの fig_caption は今までどおり採用し、図のキャプションになる
    from jasme_jats.ai_assist import set_role_problem
    _, plan, _ = _mechanical(STRUCTURE, journal)
    vml = next(p for p in plan.paras.values() if p.plain().startswith("問3　架空の数の列"))
    floating = next(p for p in plan.paras.values() if p.plain() == "（ヒント）")
    assert vml.textbox_id and not vml.float_id and floating.float_id
    for role in ("p", "quote", "sec2"):
        assert "placements の kind box・label で指定する" in set_role_problem(vml, plan, role)
    assert set_role_problem(vml, plan, "exclude") == "" and set_role_problem(vml, plan, "fig_caption") == ""
    assert "placements で指定する" in set_role_problem(floating, plan, "exclude")
    # 囲みとして位置を機械的に決めたもの（placements でも変えられない）の段落には、placements を案内せず「機械的に決めたので
    # 変更できない」と返す（0.25.0 の最初の実装は placements を案内し、placements も採用しないので行き止まりになっていた）
    at_anchor = next(p for p in plan.paras.values() if p.plain().startswith("問1　架空の三角形"))
    inline = next(p for p in plan.paras.values() if p.plain().startswith("問2　架空の問い"))
    fixed = "は囲み（boxed-text）として扱いと位置を機械的に決めたので、変更できない"
    for role in ("p", "exclude", "fig_caption"):
        assert set_role_problem(at_anchor, plan, role) == f"テキストボックス {at_anchor.textbox_id} {fixed}"
    assert set_role_problem(inline, plan, "p") == (
        f"テキストボックス {inline.textbox_id} {fixed}（浮動配置でないテキストボックスの段落に指定できる役割は fig_caption・"
        "table_caption・exclude だけ）")
    assert set_role_problem(inline, plan, "exclude") == ""      # 浮動配置でない段落の exclude は今までどおり受け付ける
    res = _manual(STRUCTURE, [_set_role(vml.src, "p"), _set_role(vml.src, "exclude")], meta, journal, tmp_path / "s")
    [(op, why)] = [(op, w) for op, w in res.ai.rejected if op["src"] == vml.src]
    assert op["role"] == "p" and "placements" in why
    assert {t: w for _, w, t in res.fidelity.excluded}[vml.plain()].startswith("AI 補完で、論文の本文ではない")
    assert res.fidelity.ok and res.dtd_valid

    def parts(b):
        rid = b.add_image("vmlcap.png", mf.png_bytes("Figure"))
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "試験（2024）の図を示す。"),
                mf.para(S["body"], mf.drawing(rid, 1800000, 1080000, 3101)),
                mf.para(S["body"], mf.vml_textbox(mf.para(S["body"], "図1　架空の図形の説明である。"), width="200pt", height="20pt")),
                mf.para(S["body"], "以上が図1である。")]
    path = tmp_path / "vmlcap.docx"
    mf.make_article(path, "VML のキャプションの検証用文書", parts)
    _, p2, _ = _mechanical(path, journal)
    cap = next(s for s, p in p2.paras.items() if p.plain().startswith("図1　架空の図形"))
    assert cap in {e.src for e in p2.exclusions}            # 「。」で終わるのでキャプションの形でなく、文字だけのテキストボックス
    res = _manual(path, [_set_role(cap, "fig_caption"), _set_role(cap, "p")], meta, journal, tmp_path / "v")
    assert [op["role"] for op, _ in res.ai.accepted] == ["fig_caption"]
    assert [op["role"] for op, w in res.ai.rejected if "placements" in w] == ["p"]
    fig = load(res).find(".//fig")
    assert fig.get("id") == "F1" and _text(fig.find("caption")) == "図1　架空の図形の説明である。"
    assert fig.find("graphic") is not None and res.fidelity.ok and res.dtd_valid


def test_textbox_placement_unused_after_set_role_is_rejected(journal, meta, tmp_path):
    # 同じ回答で、決められない（浮動配置でない）テキストボックスの段落を set_role で図キャプションにし、そのテキストボックスに
    # placements の kind label も指定したとき: 組み直した後は文字だけのテキストボックスでないので、kind の指定は使えない。
    # 黙って捨てずに不採用（2 章）として示す（set_role は採用）
    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "試験（2024）の札。", mf.vml_textbox(mf.para(S["body"], "（ヒント）"))),
                mf.para(S["body"], "札の後の段落。")]
    path = tmp_path / "vmlhint.docx"
    mf.make_article(path, "札の検証用文書", parts)
    _, plan, _ = _mechanical(path, journal)
    [xid] = plan.undecided_boxes
    src = plan.textboxes[xid].paras[0].src
    res = _manual_pl(path, [_box_pl(xid, "", kind="label")], meta, journal, tmp_path / "out", ops=[_set_role(src, "fig_caption")])
    assert [op["role"] for op, _ in res.ai.accepted] == ["fig_caption"] and res.plan.paras[src].role == "fig_caption"
    [(op, why)] = [(op, w) for op, w in res.ai.rejected if op["op"] == "place_float"]
    assert op["src"] == xid and why.startswith(f"テキストボックス {xid} は、AI の役割の指定（set_role）を反映して組み直した後に")
    assert res.plan.undecided_boxes == [] and res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    # set_role がなければ、kind label を採用する（今までどおり）
    res = _manual_pl(path, [_box_pl(xid, "", kind="label")], meta, journal, tmp_path / "label")
    assert [op["op"] for op, _ in res.ai.accepted] == ["place_float"] and res.ai.rejected == []


def test_textbox_placement_after_excluded_paragraph_is_rejected(journal, meta, tmp_path):
    # 同じ回答で、本文の段落を set_role exclude にし、その段落を after にした kind box も指定したとき: 組み直した後は after が
    # 本文の段落でないので、kind の指定は使わず（place_boxes が指定なしに戻す。修正計画の F の (3)）、2 章の不採用として示す。
    # 変換は止まらず、そのテキストボックスは決められないもの（要確認）のまま（set_role は採用）
    plan, ids = _boxes_by_text(journal)
    hint, after = ids["（ヒント）"], _src(plan, "囲みの後の段落である。")
    res = _manual_pl(STRUCTURE, [_box_pl(hint, after)], meta, journal, tmp_path, ops=[_set_role(after, "exclude")])
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and res.jstage_issues == []
    assert [(op["op"], op["role"]) for op, _ in res.ai.accepted if op["op"] == "set_role"] == [("set_role", "exclude")]
    [(op, why)] = [(op, w) for op, w in res.ai.rejected if op["op"] == "place_float"]
    assert op["src"] == hint and why.startswith(f"テキストボックス {hint} は、AI の役割の指定（set_role）を反映して組み直した後に")
    assert res.plan.textboxes[hint].kind == "undecided" and hint in res.plan.undecided_boxes
    assert "textbox_undecided" in [a.key for a in actions(res)]
    assert {t: w for _, w, t in res.fidelity.excluded}["（ヒント）"].startswith("テキストボックス内の文字（囲みか図の注記か決められない")


def test_request_lists_textboxes(journal):
    # 依頼文: 囲みか図の注記か決められなかったもの（placements の指定が必要）、位置を推定した囲み（違うときだけ指定）、扱いを
    # 機械的に決めたもの（変更不可）の節。テキストボックスの段落の場所は「テキストボックス x… の中」
    from jasme_jats.ai_assist import build_request
    _, plan, linker = _mechanical(STRUCTURE, journal)
    _, ids = _boxes_by_text(journal)
    req, _ = build_request(plan, linker)
    undecided = req.split("# 囲みか図の注記か決められなかったテキストボックス\n", 1)[1].split("\n# ", 1)[0]
    assert all(f"[{ids[t]}]" in undecided for t in ("（ヒント）", "注", "Area model"))
    assert "判定できなかった理由: 文字 5 字" in undecided and "画像の近く: いいえ" in undecided
    est = req.split("# 位置を推定した囲み", 1)[1].split("\n# ", 1)[0]
    assert f"[{ids['問3　架空の数の列の規則を説明せよ。']}]" in est and "position:absolute" in est
    fixed = req.split("# 囲みとして位置を機械的に決めたテキストボックス（変更不可。placements に書かないこと）", 1)[1]
    a, c, b = ids["問1　架空の三角形の面積を求めよ。底辺と高さは図に示す。"], ids["問2　架空の問いを二つの式で考えよ。"], ids["A 点"]
    assert f"[{a}] 囲み: 段落 [" in fixed and "] の前に配置済み" in fixed and f"[{c}] 囲み:" in fixed
    # 図に重ねた注記とみなしたものは、変更不可の節ではなく、本文の文章なら kind box で戻せる節に載せる（中身の段落も示す）
    assert f"[{b}]" not in fixed
    labels = req.split("# 図に重ねた注記とみなして除外したテキストボックス（本文の文章のときだけ placements で kind box と after を"
                       "指定）\n", 1)[1].split("\n# ", 1)[0].rstrip("\n")
    a_src = _src(plan, "A 点")
    assert labels == (f"[{b}] 段落 [{_src(plan, '図1の点に名前を付けた。')}] の図の注記（{plan.textboxes[b].why}）: "
                      f"[{a_src}] A 点")
    # 段落の場所: 浮動配置のテキストボックスは「（浮動配置）」を付ける（set_role で役割を変えられないことが分かるように）
    hint_src = next(s for s, p in plan.paras.items() if p.plain() == "（ヒント）")
    assert f"[{hint_src}]（body / テキストボックス {ids['（ヒント）']}（浮動配置）の中 /" in req
    inline_src = _src(plan, "問2　架空の問い")
    assert f"[{inline_src}]（p / テキストボックス {c} の中 /" in req
    # テキストボックスのない原稿の依頼文には、これらの節を出さない
    _, fplan, flinker = _mechanical(FULL, journal)
    assert "テキストボックス" not in build_request(fplan, flinker)[0].split("---", 1)[-1].split("# 論文の段落一覧")[-1]


def test_prompts_explain_box_and_label():
    a = ai_assist
    assert a.PLACEMENT_SCHEMA["properties"]["items"]["items"]["properties"]["kind"]["enum"] == ["fig", "table", "box", "label"]
    assert "テキストボックスの ID（x1 など）" in a.PLACEMENT_SCHEMA["properties"]["float"]["description"]
    assert "囲みか図の注記か決められなかったテキストボックス" in a.RESPONSE_SCHEMA["properties"]["placements"]["description"]
    sp = a.system_prompt()
    assert "「# 囲みか図の注記か決められなかったテキストボックス」に挙げたもの（x1 など）は、1 つ残らず" in sp
    assert '{"kind": "box" か "label", "caption": [], "body": []}' in sp
    assert "浮動配置でないテキストボックスの段落に set_role で指定できるのは\n     fig_caption・table_caption・exclude だけ" in sp
    assert "浮動配置のテキストボックス（段落一覧の位置が「テキストボックス x1（浮動配置）の中」の段落）の" in sp
    assert ("「# 図に重ねた注記とみなして除外したテキストボックス」に挙げたものは、図の注記ではなく本文として読まれる文章"
            "（問題文・ヒントなど）の\n     ときだけ、kind box で after を指定してください") in sp
    assert "「# 囲みとして位置を機械的に決めたテキストボックス（変更不可）」に挙げたものは placements に書かないでください。" in sp
    assert "「# 図に重ねた注記とみなして除外したテキストボックス」に挙げたものは、変えるときだけ\nkind box で書く" in a.FIELD_GUIDE
    assert "kind を box（本文の囲み。問題文・ヒントなど）か label（図に重ねた注記。矢印のラベルなど）" in a.FIELD_GUIDE
    assert "- float: 図形の ID（s1 など）か、テキストボックスの ID（x1 など）" in a.FIELD_GUIDE
    example = parse_response(a.MANUAL_EXAMPLE)
    assert example["placements"][1]["float"] == "x2" and example["placements"][1]["items"][0]["kind"] == "box"
    assert "（kind は box か label）" in a.manual_prompt("依頼文", [])
    assert ("「# 図に重ねた注記とみなして除外したテキストボックス」に挙げたものは、本文の文章（問題文・ヒントなど）のときだけ、"
            "placements に kind box で書いてください。") in a.manual_prompt("依頼文", [])
    assert "「図に重ねた注記とみなして除外したテキストボックス」に挙げたもの" in a.PLACEMENT_SCHEMA["properties"]["float"]["description"]


def test_fullwidth_space_paragraphs_in_textboxes_keep_fidelity(journal, meta, tmp_path):
    # 囲み・図の注記・決められないもの・位置を決められない図形（手動モードで回答前）の中の全角空白だけの段落も、空白の除外として
    # 記録し、不変性チェックに合格する
    def parts(b):
        rid = b.add_image("fw.png", mf.png_bytes("Figure"))
        rid2 = b.add_image("fw2.png", mf.png_bytes("Float"))
        cm = 360000
        return [mf.para(S["sec1"], "１．はじめに"),
                mf.para(S["body"], "試験（2024）の囲みである。", mf.textbox(
                    mf.para(S["body"], "問1　架空の囲みの問題文である。答えを書け。") + mf.para(S["body"], "　"), 911,
                    cx=12 * cm, cy=2 * cm)),
                mf.para(S["body"], "囲みの後の段落。"),
                mf.para(S["body"], "ヒントの札。", mf.textbox(mf.para(S["body"], "（ヒント）") + mf.para(S["body"], "　"), 912,
                                                         cx=10 * cm, cy=cm)),
                mf.para(S["body"], "札の後の段落。"), mf.para(S["body"], "図の前の段落。"),
                mf.para(S["body"], mf.drawing(rid, 1800000, 1080000, 913)), mf.para(S["fig_cap"], "図1　架空の図"),
                mf.para(S["body"], "図1の注記。", mf.textbox(mf.para(S["body"], "A点") + mf.para(S["body"], "　"), 914,
                                                      cx=cm, cy=cm, v=("paragraph", -cm))),
                mf.para(S["body"], "図2の段落。", mf.textbox(
                    mf.para(S["body"], mf.drawing(rid2, 1440000, 960000, 916)) + mf.para(S["body"], "　")
                    + mf.para(S["fig_cap"], "図2　位置を決められない図"), 915, cx=8 * cm, cy=4 * cm, v=("paragraph", 2 * cm)))]
    path = tmp_path / "fw.docx"
    mf.make_article(path, "全角空白の検証用文書", parts)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", ai_mode="manual", convert_metafiles=False))
    fid = res.fidelity
    assert fid.ok and fid.final_ok and res.dtd_valid and fid.bad_excluded == [], (fid.missing, fid.bad_excluded)
    kinds = sorted(bi.kind for bi in res.plan.textboxes.values())
    assert kinds == ["box", "label", "undecided"] and res.plan.unplaced_floats == ["s4"]
    assert sum(1 for _, why, t in fid.excluded if why == "空白のみの段落" and t == "　") == 4


# ============================================================================= 姓と名の区切りがない氏名（修正計画の U4）
def names_article(path, ja_names, en_names):
    """和文・英文の著者名だけを変えた小さな論文（著者名は ja_names・en_names の順。所属はどれも架空大学）。"""
    b = mf.Builder()
    body = mf.front_ja(b, "氏名の検証用文書", "―姓と名―", [("架空大学", n) for n in ja_names])
    body += [mf.para(mf.S["sec1"], "１．はじめに"), mf.para(mf.S["body"], "試験（2024）にならい，著者名を確かめる。"),
             mf.para(mf.S["ref_head"], "引用および参考文献"),
             mf.para(mf.S["ref"], "試験六郎（2024）．「小さな論文」．『架空誌』，第5巻，pp.9-10．")]
    body += mf.front_en(b, "Checking Names", "Surnames", [(n, "Fictional University") for n in en_names], ["Name abstract."])
    body += mf.tail(b)
    b.save(path, body)
    return path


def test_unsplit_names_come_from_build_info(journal, meta, tmp_path):
    """姓と名の区切りがない氏名は、builder.BuildInfo.unsplit_names（段落の ID・前後の空白を除いた氏名・言語）から AI 依頼文に
    載せる（4 章の記録の文言から切り出さない）。sample_full の d11 は、模擬回答の split_name の対象。"""
    from jasme_jats.builder import build
    _, plan, _ = _mechanical(FULL, journal)
    assert build(plan, meta, journal, None)[1].unsplit_names == [("d11", "研究次郎", "ja")]
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, ai_mode="manual", convert_metafiles=False))
    assert "- [d11] 姓と名の区切りがない氏名: 「研究次郎」" in res.prompt_path.read_text(encoding="utf-8")
    assert 'split("「"' not in inspect.getsource(pipeline.convert)
    # 氏名の前後の空白（全角も）は AI の split_name の検証と同じく除き、間に空白のある氏名は載せない
    path = names_article(tmp_path / "names.docx", ["研究次郎", "架空四郎\u3000", "\u3000架空五郎", "試験\u3000太郎", "試験 三郎"],
                         ["Jiro KENKYU", "Shiro KAKU", "Goro KAKU", "Taro SHIKEN", "Saburo SHIKEN"])
    _, plan, _ = _mechanical(path, journal)
    info = build(plan, meta, journal, None)[1]
    assert [(text, lang) for _, text, lang in info.unsplit_names] == [("研究次郎", "ja"), ("架空四郎", "ja"), ("架空五郎", "ja")]


def test_build_request_lists_unsplit_names_with_language(journal):
    """build_request は (段落の ID, 氏名, 言語) の組を受け取り、英文の氏名も載せる（利用者の決定事項 17: 英文 1 語の氏名も、
    今までどおり AI 依頼文に載せる）。split_name は和文の氏名にしか使えない（apply_ops）ので、英文の行には提案しないことを添える
    （10 章の警告の「AI による補完では、英文の著者名は分けられません」と同じ言い分）。"""
    from jasme_jats.ai_assist import build_request
    _, plan, linker = _mechanical(FULL, journal)
    req, _ = build_request(plan, linker, (), [("d11", "研究次郎", "ja"), ("d12", "KENKYU", "en")])
    assert "- [d11] 姓と名の区切りがない氏名: 「研究次郎」" in req
    assert ("- [d12] 姓と名の区切りがない氏名（英文の氏名。split_name は和文の氏名にだけ使えるので、提案しない）: 「KENKYU」"
            in req)


def test_build_request_shows_newline_in_unsplit_name(journal):
    """氏名の中の改行（著者名の後ろの Shift+Enter など）は、依頼文では「⏎」で示し、1 件を 1 行に書く（氏名の文字は変えない。
    BuildInfo.unsplit_names には改行の文字のまま入る）。"""
    from jasme_jats.ai_assist import build_request
    _, plan, linker = _mechanical(FULL, journal)
    req, _ = build_request(plan, linker, (), [("d11", "研究次郎\n", "ja")])
    [line] = [ln for ln in req.splitlines() if "姓と名の区切りがない氏名" in ln]
    assert line == "- [d11] 姓と名の区切りがない氏名: 「研究次郎⏎」"


def test_english_one_word_name_is_listed_and_warned(journal, meta, tmp_path):
    """英文 1 語の著者名は、全体を姓として出力し、4 章の記録（今までどおり）・AI 依頼文（決定事項 17。split_name を提案しないことを
    添える）・10 章の警告（決定事項 17 の後半）に出す。要対応・要確認は増えない。和文の「研究　次郎」は分けられるので載せない。"""
    path = names_article(tmp_path / "en.docx", ["研究\u3000次郎"], ["KENKYU"])
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", ai_mode="manual", convert_metafiles=False))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    [warn] = [w for w in res.warnings if "英文の著者名" in w]
    assert "「KENKYU」" in warn and "姓（surname）" in warn and "Word で" in warn
    assert any(d.category == "name" and "「KENKYU」" in d.message for d in res.build_notes)
    names = [ln for ln in res.prompt_path.read_text(encoding="utf-8").splitlines() if "姓と名の区切りがない氏名" in ln]
    assert len(names) == 1 and names[0].endswith("「KENKYU」") and "split_name は和文の氏名にだけ使える" in names[0]
    assert [a.key for a in actions(res)] == ["ai_pending"]
    root = load(res)
    [en] = [n for n in root.iter("name") if n.get("name-style") == "western"]
    assert [(x.tag, x.text) for x in en] == [("surname", "KENKYU")]
    # AI が英文の氏名に split_name を提案しても採用しない（依頼文の添え書きと 10 章の警告のとおり。XML も変わらない）
    src = names[0].split("]", 1)[0].removeprefix("- [")
    op = {"op": "split_name", "src": src, "text": "", "occurrence": 1, "target": "", "role": "", "image": "", "mathml": "",
          "surname": "KEN", "given": "KYU", "reason": "試しの分割", "confidence": "低"}
    res2 = convert(path, meta, journal, Options(out_dir=tmp_path / "out2", ai_mode="manual", convert_metafiles=False,
                                                ai_response=json.dumps({"operations": [op]}, ensure_ascii=False)))
    assert [why for _, why in res2.ai.rejected] == ["英文氏名は空白の位置で姓と名を分けるため、分割の指定は和文氏名だけに使える"]
    assert res2.ai.accepted == [] and res2.xml_path.read_bytes() == res.xml_path.read_bytes()


# ----------------------------------------------------------------------------- 点検 2026-11（A1・A2・A3・A6・A8）
def _op(**kw):
    base = {"op": "", "src": "", "text": "", "occurrence": 1, "target": "", "role": "", "image": "", "mathml": "",
            "surname": "", "given": "", "reason": "試験", "confidence": "高"}
    base.update(kw)
    return base


def _manual_raw(ops, meta, journal, out, notes=(), placements=()):
    resp = json.dumps({"operations": ops, "placements": list(placements), "notes": notes}, ensure_ascii=False)
    return convert(FULL, meta, journal, Options(out_dir=out, ai_mode="manual", ai_response=resp, convert_metafiles=False))


def test_a1_op_field_types(journal, meta, tmp_path):
    """A1: 操作の項目が一覧・辞書・bool だと理由付きで不採用、数値は文字列にして照合に使う（変換は止まらない）。"""
    ops = [_op(op="link_citation", src=["d18"], text="2001", target="B2"),
           _op(op="link_citation", src="d18", text={"a": 1}, target="B2"),
           _op(op="set_role", src="d46", role=True),
           _op(op="formula_image", image="img3", mathml=2001),
           _op(op="link_citation", src="d18", text=2001, target="B2")]
    res = _manual_raw(ops, meta, journal, tmp_path)
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    whys = [why for _, why in res.ai.rejected]
    assert sum("文字列でない" in w for w in whys) == 4
    assert any("項目 mathml" in w for w in whys)


def test_a1_placements_types(journal, meta, tmp_path):
    """A1: placements の各欄の型が違っても変換は止まらず、理由付きで不採用（float・after・items の caption・body の数値など）。"""
    it = {"kind": "fig", "caption": ["d16"], "body": ["t2"]}
    pls = [{"float": ["s1"], "after": "d18", "items": [], "reason": "x", "confidence": "高"},
           {"float": 1.5, "after": "d18", "items": [it], "reason": "x", "confidence": "高"},
           {"float": "s1", "after": {"x": 1}, "items": [], "reason": 5, "confidence": "高"},
           {"float": "s1", "after": 7, "items": [it], "reason": "x", "confidence": "高"},
           {"float": "s1", "after": "d18", "items": [{"kind": "fig", "caption": [["a"]], "body": [{}]}],
            "reason": "x", "confidence": "高"},
           {"float": "s1", "after": "d18", "items": [dict(it, caption=5)], "reason": "x", "confidence": "高"},
           {"float": "s1", "after": "d18", "items": [dict(it, body=5)], "reason": "x", "confidence": "高"},
           {"float": "s1", "after": "d18", "items": [dict(it, body=2.5)], "reason": "x", "confidence": "高"},
           {"float": "s1", "after": "d18", "items": [dict(it, caption="d16")], "reason": "x", "confidence": "高"},
           {"float": "s1", "after": "d18", "items": [dict(it, body={"a": 1})], "reason": "x", "confidence": "高"}]
    res = _manual_raw([], meta, journal, tmp_path, placements=pls)
    assert res.fidelity.ok and len(res.ai.rejected) == len(pls)
    whys = [why for _, why in res.ai.rejected]
    assert sum("は一覧（[ ]）で書く" in w for w in whys) == 5          # caption=5・body=5・2.5・文字列・辞書
    assert sum("文字列" in w for w in whys) >= 4


def test_a1_a2_parse_paths_do_not_raise():
    data = parse_response(json.dumps({"operations": [_op(op="link_figure", text=1.5)], "placements": [], "notes": 3}))
    out = ai_assist.AIOutcome()
    ops = ai_assist.split_ops(data, out)
    assert ops[0]["text"] == "1.5" and out.rejected == []
    cut = ai_assist.parse_cut_response('{"placements": [{"float": ["s1"], "after": 3, "items": 1}, {"fl')
    out2 = ai_assist.AIOutcome()
    plan_like = types.SimpleNamespace(body_seq=[], floats={}, textboxes={}, region={})
    assert ai_assist.float_placements(cut, plan_like, out2) == {} and len(out2.rejected) == 1


def test_a2_notes_types():
    def notes(v):
        return parse_response(json.dumps({"operations": [], "placements": [], "notes": v}))["notes"]
    assert notes("気づき") == ["気づき"]
    assert notes(["a", 2, ["b"]])[:2] == ["a", "2"] and "使わなかった" in notes(["a", 2, ["b"]])[2]
    [n] = notes(5)
    assert "使わなかった" in n
    [n] = notes({"a": 1})
    assert "使わなかった" in n


def test_a2_notes_in_convert(journal, meta, tmp_path):
    res = _manual_raw([], meta, journal, tmp_path, notes="気づき")
    assert res.ai.notes == ["気づき"]
    res = _manual_raw([], meta, journal, tmp_path / "b", notes=7)
    assert len(res.ai.notes) == 1 and "使わなかった" in res.ai.notes[0]


def test_a3_mathml_entities_comments_pi():
    m = '<math xmlns="http://www.w3.org/1998/Math/MathML">{}</math>'
    for inner in ("<mi>&foo;</mi>", "<!-- c --><mi>a</mi>", "<?pi x?><mi>a</mi>"):
        s = '<!DOCTYPE math [<!ENTITY foo "abc">]>' + m.format(inner)
        assert parse_mathml(s)[0] is None
    assert parse_mathml(m.format("<mi>&foo;</mi>"))[0] is None
    assert parse_mathml(m.format("<!-- c --><mi>a</mi>"))[0] is None
    assert parse_mathml(m.format("<?pi x?><mi>a</mi>"))[0] is None
    assert parse_mathml(m.format("<mi>a</mi>"))[0] is not None


def test_a3_final_check_unreadable_entity():
    from jasme_jats.fidelity import FidelityResult, final_check
    root = etree.fromstring(b"<a>x</a>")
    res = FidelityResult()
    assert final_check(root, b"<a>x<b>&foo;</b></a>", res) is False        # 未定義の実体参照
    assert res.final_ok is False and "XML として読めない" in res.final_detail
    res = FidelityResult()
    assert final_check(root, b'<!DOCTYPE a [<!ENTITY foo "abc">]><a>x</a>', res) is False      # 実体の宣言は解決せずに不合格（F6）
    res = FidelityResult()
    assert final_check(root, b"<a>x</a>", res) is True


def test_a6_links_in_nolink_paragraphs_rejected(journal):
    _, plan, _ = _mechanical(FULL, journal, {}, {})
    title = plan.title[0]
    ref = plan.refs[0].para
    ops = [_op(op="link_figure", src=title.src, text=title.plain()[:1], target=plan.figures[0].fid),
           _op(op="link_citation", src=ref.src, text="2001", target="B2")]
    out = ai_assist.AIOutcome()
    ai_assist.apply_ops(ops, plan, None, out)
    assert out.accepted == [] and len(out.rejected) == 2
    assert "題目" in out.rejected[0][1] and "引用文献" in out.rejected[1][1]


def test_a8_formula_image_with_extra_content_rejected(journal):
    _, plan, _ = _mechanical(FULL, journal, {}, {})
    fig = next(f for f in plan.figures if any(i.image_id == "img3" for ip in f.image_paras for i in ip.images))
    mml = '<math xmlns="http://www.w3.org/1998/Math/MathML"><mi>a</mi></math>'
    for attr in ("tables", "extra_images", "caption_more"):
        setattr(fig, attr, [object()])
        out = ai_assist.AIOutcome()
        ai_assist.apply_ops([_op(op="formula_image", image="img3", mathml=mml)], plan, None, out)
        assert out.accepted == [] and "数式画像" in out.rejected[0][1] and fig.formula is None
        setattr(fig, attr, [])
    out = ai_assist.AIOutcome()
    ai_assist.apply_ops([_op(op="formula_image", image="img3", mathml=mml)], plan, None, out)
    assert len(out.accepted) == 1


def test_f6_final_check_rejects_entity_declaration_without_reading(tmp_path):
    """F6: 実体の宣言（<!ENTITY）を含む最終出力は、実体を解決せずに（外部実体のファイルを読まずに）不合格にする。"""
    from jasme_jats.fidelity import FidelityResult, final_check
    secret = tmp_path / "secret.txt"
    secret.write_text("SECRET", encoding="utf-8")
    for decl in (f'<!ENTITY x SYSTEM "{secret.as_uri()}">', '<!ENTITY x "SECRET">'):
        xml = f'<?xml version="1.0"?><!DOCTYPE a [{decl}]><a>SECRET</a>'.encode()
        res = FidelityResult()
        assert final_check(etree.fromstring(b"<a>SECRET</a>"), xml, res) is False
        assert res.final_ok is False and "<!ENTITY" in res.final_detail
    # 外部実体を参照する本文でも、読み込んだ文字が合格の根拠にならない
    xml = f'<?xml version="1.0"?><!DOCTYPE a [<!ENTITY x SYSTEM "{secret.as_uri()}">]><a>&x;</a>'.encode()
    res = FidelityResult()
    assert final_check(etree.fromstring(b"<a>SECRET</a>"), xml, res) is False


def _caption_docx(path):
    def parts(b):
        out = [mf.para(mf.S["sec1"], "１．はじめに"), mf.para(mf.S["body"], "本文である。")]
        for k, cap in enumerate(["図1　a", "図2　b"], 1):
            rid = b.add_image(f"f{k}.png", mf.png_bytes(f"F{k}"))
            out += [mf.para(mf.S["body"], mf.drawing(rid, 2880000, 1800000, 970 + k), jc="center"),
                    mf.para(mf.S["fig_cap"], cap)]
        return out
    mf.make_article(path, "検証用文書", parts)


def test_f7_link_on_label_range_rejected_when_split(journal, meta, tmp_path):
    """F7: split_labels のとき、図キャプションの先頭の番号（<label>）にかかるリンクは不採用。分けないときと、番号以外の範囲は採用。"""
    p = tmp_path / "in.docx"
    _caption_docx(p)
    _, plan, _ = _mechanical(p, journal)
    cap = plan.figures[0].caption.src

    def run(split, text, sub):
        resp = json.dumps({"operations": [_op(op="link_figure", src=cap, text=text, target="F2")], "placements": [], "notes": []})
        return convert(p, meta, journal, Options(out_dir=tmp_path / sub, convert_metafiles=False, ai_mode="manual",
                                                 ai_response=resp, split_labels=split))
    res = run(True, "図1", "a")
    assert res.fidelity.ok and res.ai.accepted == [] and "<label>" in res.ai.rejected[0][1]
    assert not [x for x in load(res).iter("xref") if x.get("ref-type") == "fig"]
    res = run(False, "図1", "b")
    assert len(res.ai.accepted) == 1 and [x for x in load(res).iter("xref") if x.get("ref-type") == "fig"]
    res = run(True, "a", "c")                       # 番号の後ろ（タイトル）は <label> の外
    assert len(res.ai.accepted) == 1 and [x for x in load(res).iter("xref") if x.get("ref-type") == "fig"]


def test_a8_formula_image_on_real_docx_with_table_and_moved_image(journal, meta, tmp_path):
    """A8: 表を含む図・他の段落から移した画像のある図を formula_image にしようとしても、不採用で表が残り、不変性チェックも通る。"""
    cm = 360000

    def parts(b):
        i1 = b.add_image("a.png", mf.png_bytes("Inner", size=(300, 200)))
        tbl = mf.table([[mf.cell("表の文字甲"), mf.cell("乙")]])
        inner = mf.para(mf.S["body"], mf.drawing(i1, 1800000, 1080000, 512)) + tbl + mf.para(mf.S["body"], "")
        return [mf.para(mf.S["sec1"], "１．はじめに"),
                mf.para(mf.S["body"], "本文である。", mf.textbox(inner, 511, cx=8 * cm, cy=4 * cm, v=("paragraph", 30 * cm),
                                                               wrap="wrapTopAndBottom")),
                mf.para(mf.S["body"], "以上。")]
    p = tmp_path / "in.docx"
    mf.make_article(p, "検証用文書", parts)
    _, plan, _ = _mechanical(p, journal)
    fid, info = next((k, v) for k, v in plan.floats.items() if v.tables)
    img = next(i.image_id for q in info.paras for i in q.images)
    anchor = next(x for x in plan.body_seq if plan.paras[x].plain().startswith("本文である"))
    tid = info.tables[0].tid
    mml = '<math xmlns="http://www.w3.org/1998/Math/MathML"><mi>a</mi></math>'
    pl = {"float": fid, "after": anchor, "items": [{"kind": "fig", "caption": [], "body": [img, tid]}], "reason": "x",
          "confidence": "中"}
    resp = json.dumps({"operations": [_op(op="formula_image", image=img, mathml=mml)], "placements": [pl], "notes": []})
    res = convert(p, meta, journal, Options(out_dir=tmp_path / "o", convert_metafiles=False, ai_mode="manual", ai_response=resp))
    assert res.fidelity.ok and res.fidelity.final_ok
    assert any("数式画像" in w for _, w in res.ai.rejected)
    assert "表の文字甲" in res.xml_path.read_text(encoding="utf-8")
