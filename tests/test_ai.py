"""AI 補完: 回答の検証と適用（実際の API は呼ばない）。"""
import inspect
import json
import types
from pathlib import Path

import pytest
from lxml import etree

import answers
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


def example_block():
    """依頼文の見本（MANUAL_EXAMPLE）のコードブロックの中身を JSON として読む（parse_response は見本そのものを断るので通さない）。"""
    return json.loads(ai_assist.RE_FENCE.search(ai_assist.MANUAL_EXAMPLE).group(1))


def load(res):
    return etree.fromstring(res.xml_path.read_bytes().split(b"\n", 2)[2])


def test_manual_mode_applies_valid_ops_and_rejects_invalid(journal, meta, tmp_path):
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, ai_mode="manual", ai_response=RESPONSE))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    root = load(res)
    bibr = {(x.text, x.get("rid")) for x in root.iter("xref") if x.get("ref-type") == "bibr"}
    assert {("2001", "B2"), ("2025", "B7"), ("2016", "B4"), ("1977", "B10")} <= bibr
    rejected = {op["text"] for op, _ in res.ai.rejected if op["op"] not in ("formula_image", "set_role")}
    assert rejected == {"Claude", "図9"}           # 年以外へのリンク・存在しない図は不採用
    # 章見出しへの set_role は、Word のスタイルで直す提案にして XML には反映しない（所有者の決定 5。W8 の手順 5）
    assert [why for op, why in res.ai.rejected if op["op"] == "set_role"] == [ai_assist.STYLE_ONLY_WHY]
    assert [(f.src, f.role, f.style, f.how) for f in res.ai.style_fixes] == [
        ("d46", "sec1", "章見出し", "Word で段落のスタイルを「章見出し」にする")]
    assert res.ai.boundaries == []
    # 画像の数式の書き起こし（formula_image）は、docx の画像を AI に渡さなくなったので採用しない（修正計画 W1）
    assert [why for op, why in res.ai.rejected if op["op"] == "formula_image"] == [ai_assist.FORMULA_IMAGE_WHY]
    assert root.find(".//disp-formula/alternatives") is None and not res.fidelity.ai_additions
    names = [n for n in root.iter("name") if n.get("name-style") == "eastern"]
    assert [x.text for x in names[2]] == ["研究", "次郎"]
    assert res.unresolved_after == []
    report = res.report_path.read_text(encoding="utf-8")
    assert "## 2. AI による仕上げ（要確認）" in report and "| 状態 | 済み |" in report and "国宗は" in report


def test_manual_mode_without_response_writes_prompt(journal, meta, tmp_path):
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, ai_mode="manual"))
    prompt = res.prompt_path.read_text(encoding="utf-8")
    assert "[d18]" in prompt and "link_citation" in prompt
    # docx の画像は AI に渡さない（修正計画 W1）: 添付画像のフォルダを作らず、依頼文に添付の案内を書かない
    assert not (tmp_path / "AI添付画像").exists() and "AI添付画像" not in prompt and "添付" not in prompt.split("---")[0]
    assert res.fidelity.ok
    # チャットの AI が JSON を崩さないよう、回答の書き方（コードブロック 1 つ・半角の引用符）と見本を示す
    assert "## 回答の書き方" in prompt and "```json" in prompt
    assert example_block()["operations"]


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
    res = convert(FLOAT, meta, journal, Options(out_dir=tmp_path, ai_mode="manual", ai_response=unclosed))
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
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, ai_mode="api", ai_api_key="test"))
    assert calls["model"] == DEFAULT_MODEL
    assert calls["output_config"]["format"]["type"] == "json_schema"
    assert calls["fallbacks"] == "default"
    assert not res.ai.error
    # 7 件のうち formula_image は採用しない（修正計画 W1）。章見出しへの set_role は提案にする（決定 5）
    assert len(res.ai.accepted) == 5 and res.fidelity.ok and len(res.ai.style_fixes) == 1
    content = calls["messages"][0]["content"]
    assert not any(isinstance(c, dict) and c.get("type") == "image" for c in content)     # docx の画像は渡さない


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
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, ai_mode="api", ai_api_key="t"))
    assert calls == [DEFAULT_MODEL, "claude-opus-6"] and res.ai.model == "claude-opus-6"
    assert "切り替えた" in res.ai.model_note and not res.ai.error
    assert "使用したモデル: claude-opus-6" in res.report_path.read_text(encoding="utf-8")
    # 「自動」→ はじめから最新の Opus
    calls = []
    _fake_anthropic(monkeypatch, calls, available=("claude-opus-6",), listed=listed)
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, ai_mode="api", ai_model="auto", ai_api_key="t"))
    assert calls == ["claude-opus-6"] and "自動" in res.ai.model_note
    # 指定したモデルがなく、一覧からも見つからない → 分かりやすいエラー
    calls = []
    _fake_anthropic(monkeypatch, calls, available=(), listed=[])
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, ai_mode="api", ai_model="claude-typo",
                                               ai_api_key="t"))
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
                                               ai_model="gpt-test", ai_api_key="t"))
    kw = calls[0]
    assert kw["model"] == "gpt-test"
    fmt = kw["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] is True and fmt["schema"] is ai_assist.RESPONSE_SCHEMA
    content = kw["input"][0]["content"]
    assert not any(c["type"] == "input_image" for c in content)        # docx の画像は渡さない（修正計画 W1）
    assert "link_citation" in kw["instructions"]
    assert not res.ai.error and res.ai.provider == "openai"
    assert len(res.ai.accepted) == 5 and res.fidelity.ok and res.fidelity.final_ok   # set_role の sec1 は提案（決定 5）
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
                                               ai_model="gemini-test", ai_api_key="t"))
    kw = calls[0]
    assert kw["model"] == "gemini-test"
    assert kw["config"].response_mime_type == "application/json"
    assert kw["config"].response_json_schema == ai_assist.RESPONSE_SCHEMA
    parts = kw["contents"][0].parts
    assert not any(p.inline_data is not None for p in parts)        # docx の画像は渡さない（修正計画 W1）
    assert not res.ai.error and res.ai.provider == "gemini"
    assert len(res.ai.accepted) == 5 and res.fidelity.ok and res.fidelity.final_ok   # set_role の sec1 は提案（決定 5）
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
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, ai_mode="api", ai_provider="gemini", ai_model=""))
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
                                               ai_model="sakana-namazu", ai_api_key="sk-sakana"))
    client, kw = calls[0]["client"], calls[1]
    assert client["base_url"] == "https://api.sakana.ai/v1" and client["api_key"] == "sk-sakana"
    assert kw["model"] == "sakana-namazu"
    assert kw["response_format"]["type"] == "json_schema"
    assert kw["response_format"]["json_schema"]["schema"] is ai_assist.RESPONSE_SCHEMA
    system, user = kw["messages"]
    assert "## 回答の書き方" in system["content"] and "link_citation" in system["content"]
    assert not any(isinstance(c, dict) and c.get("type") == "image_url" for c in user["content"])   # docx の画像は渡さない
    assert not res.ai.error and res.ai.provider == "sakana"
    assert len(res.ai.accepted) == 5 and res.fidelity.ok and res.fidelity.final_ok   # set_role の sec1 は提案（決定 5）
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
    assert list(example_block()) == ["placements", "operations", "notes"]
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
    """API モードで回答が上限で切れたとき: 最後まで書かれた placements を反映し、誤りは消して、説明（推奨の手順 ai_finish の「一部」）を残す。
    上限で止まっても JSON が最後まで書かれていれば、ふつうに反映する。何も読めなければ、今までどおり誤りにする。"""
    _fake_anthropic(monkeypatch, [], text=_cut_text(), stop="max_tokens")
    res = convert(FLOAT, meta, journal, Options(out_dir=tmp_path / "cut", ai_mode="api", ai_api_key="t"))
    assert res.ai.error == "" and res.ai.cut and "最後まで書かれていた 1 件だけ" in res.ai.partial
    fin = next(a for a in actions(res) if a.key == "ai_finish")      # 出し直しの頼み方は ai_finish の「一部」の文（W8 の手順 3）
    assert fin.progress == "一部・残り 2 個" and "（また途中で切れるときは、手動に切り替えます）" in fin.box_detail   # 同じ上限でまた切れうる
    assert res.plan.floats["s1"].mode == "ai" and res.plan.unplaced_floats == ["s2", "s3"] and res.fidelity.ok
    _fake_anthropic(monkeypatch, [], text=head_first(), stop="max_tokens")
    res = convert(FLOAT, meta, journal, Options(out_dir=tmp_path / "whole", ai_mode="api", ai_api_key="t"))
    assert res.ai.error == "" and res.ai.partial == "" and res.plan.unplaced_floats == []
    _fake_anthropic(monkeypatch, [], text=cut_cases()["e"], stop="max_tokens")
    res = convert(FLOAT, meta, journal, Options(out_dir=tmp_path / "none", ai_mode="api", ai_api_key="t"))
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


def _manual(path, resp, meta, journal, out):
    """回答 resp（tests/answers.py で作った JSON の文字。省けば何も指定しない回答）を手動モードで貼り戻して変換する。"""
    resp = answers.answer() if resp is None else resp
    return convert(path, meta, journal, Options(out_dir=out, ai_mode="manual", ai_response=resp))


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
    res = _manual(path, answers.answer(boundaries=[(src, "資料の見出し")]), meta, journal, tmp_path / "out")
    assert res.ai.rejected == [] and [op["role"] for op, _ in res.ai.accepted] == ["app_heading"]
    assert [(b.src, b.kind) for b in res.ai.boundaries] == [(src, "資料の見出し")] and res.ai.style_fixes == []
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
    res = _manual(path, answers.answer(boundaries=[(title, "資料の見出し"), (title, "英文要旨の続き")],
                                      style_fixes=[(title, "exclude")]), meta, journal, tmp_path / "out")
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
    res = _manual(path, answers.answer(boundaries=[(src, "英文要旨の続き")]), meta, journal, tmp_path / "out")
    assert res.ai.rejected == [] and res.fidelity.ok and res.dtd_valid
    root = load(res)
    assert _abstract(root) == ["Small article abstract.", "Supplementary note", "The rest of the abstract."]
    assert _apps(root) == [("資料1\u3000架空の授業プリント", ["架空のプリントの本文。"])]
    assert not any(d.src == src and "から資料とした" in d.message for d in res.plan.decisions)
    # 資料の途中の段落（資料の見出しでない段落）への abstract は、英文要旨のスタイルで直す提案にして XML には反映しない
    # （英文要旨の続き〈abstract〉を指定できるのは、今、資料の見出しになっている段落だけ。所有者の決定 5。W8 の手順 5）
    path = tmp_path / "middle.docx"
    mf.make_article(path, "英文要旨に戻す検証用文書", _body,
                    appendix=[mf.para(S["abs"], "資料1\u3000架空の授業プリント"), mf.para(S["abs"], "架空のプリントの本文。"),
                              mf.para(S["abs"], "The rest of the abstract."), mf.para(S["abs"], "And one more sentence."),
                              mf.para(S["abs"], "資料2\u3000架空の調査票"), mf.para(S["abs"], "架空の調査票の本文。")])
    _, plan, _ = _mechanical(path, journal)
    src = next(s for s, p in plan.paras.items() if p.plain() == "The rest of the abstract.")
    assert plan.region[src] == "app"
    res = _manual(path, answers.answer(style_fixes=[(src, "abstract")]), meta, journal, tmp_path / "out2")
    assert [why for _, why in res.ai.rejected] == [ai_assist.STYLE_ONLY_WHY] and res.fidelity.ok and res.dtd_valid
    assert [(f.src, f.style) for f in res.ai.style_fixes] == [(src, "英文要旨")] and res.ai.boundaries == []
    assert load(res) is not None and res.xml_path.read_bytes() == _manual(path, None, meta, journal, tmp_path / "none").xml_path.read_bytes()


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
    res = _manual(path, answers.answer(boundaries=[(appendix_a, "英文要旨の続き"), (answer, "資料の本文")]), meta, journal, tmp_path / "out")
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
    res = _manual(path, answers.answer(boundaries=[(src, "資料の本文")]), meta, journal, tmp_path / "out")
    assert res.ai.rejected == [] and [op["role"] for op, _ in res.ai.accepted] == ["p"]
    assert [(b.src, b.kind) for b in res.ai.boundaries] == [(src, "資料の本文")]
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
    res = _manual(path, answers.answer(boundaries=[(head, "英文要旨の続き")], style_fixes=[(third, "p")]), meta, journal, tmp_path / "out")
    # 資料の見出しでない段落への p は、Word のスタイルで直す提案にして XML には反映しない（所有者の決定 5。W8 の手順 5）
    assert [(op["src"], why) for op, why in res.ai.rejected] == [(third, ai_assist.STYLE_ONLY_WHY)]
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    assert [(b.src, b.kind) for b in res.ai.boundaries] == [(head, "英文要旨の続き")]
    root = load(res)
    assert _abstract(root) == ["Small article abstract.", "Appendix 1: The fictional second abstract paragraph",
                               "The fictional third abstract paragraph."]
    assert _apps(root) == [("資料2\u3000架空の授業プリント", ["架空のプリントの本文。"])]
    res = _manual(path, answers.answer(boundaries=[(head, "英文要旨の続き"), (head2, "資料の本文")], style_fixes=[(third, "p")]),
                  meta, journal, tmp_path / "out2")
    assert [op["src"] for op, _ in res.ai.rejected] == [third] and res.fidelity.ok and res.dtd_valid
    assert [(b.src, b.kind) for b in res.ai.boundaries] == [(head, "英文要旨の続き"), (head2, "資料の本文")]
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
    res = _manual(path, answers.answer(boundaries=[(by_text["授業の記録"], "資料の本文")],
                                      style_fixes=[(by_text["Small article abstract."], "abstract")]), meta, journal, tmp_path / "out3")
    # 英文要旨の段落への abstract は提案（英文要旨の続きは、資料の見出しの段落にだけ指定できる）
    assert [(op["role"], why) for op, why in res.ai.rejected] == [("abstract", ai_assist.STYLE_ONLY_WHY)]
    assert res.fidelity.ok and res.dtd_valid
    root = load(res)
    assert _abstract(root) == ["Small article abstract."]
    assert _apps(root) == [("", ["授業の記録", "架空の記録の本文。"])]


def test_sentence_decision_is_not_recorded_for_ai_roles(journal, meta, tmp_path):
    # 見出しの形に合うが文とみなした段落の判断（「…資料の見出しにしなかった」。applied=False）は、AI が役割を指定した段落には
    # 記録しない（AI が決めたことなので、4 章と依頼文で、資料の見出しにできるという案内を繰り返さない）。資料の見出しでない段落への
    # abstract・p は、Word のスタイルで直す提案にして XML に反映しない（所有者の決定 5）ので、その判断は残る
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
    res = _manual(path, answers.answer(style_fixes=[(s1, "abstract"), (s2, "p")]), meta, journal, tmp_path / "out")
    assert [why for _, why in res.ai.rejected] == [ai_assist.STYLE_ONLY_WHY] * 2 and res.fidelity.ok and res.dtd_valid
    assert sentence_decisions(res.plan) == [s1, s2]
    # 資料の見出しにした段落（app_heading）には記録しない
    res = _manual(path, answers.answer(boundaries=[(s2, "資料の見出し")]), meta, journal, tmp_path / "out_h")
    assert res.ai.rejected == [] and sentence_decisions(res.plan) == [s1]
    res = _manual(path, answers.answer(style_fixes=[(s1, "abstract"), (s2, "p")]), meta, journal, tmp_path / "out2")
    root = load(res)
    assert _abstract(root) == ["Small article abstract.", "(Appendix 1) lists the fictional tasks."]
    assert _apps(root) == [("資料1\u3000架空の授業プリント", ["資料2（後掲）に示すように、架空の問いを並べた。"])]


def test_boundary_problem_allows_only_five_kinds(journal):
    """段落の役割の補正の最小の形（所有者の決定 5。W8 の手順 5）: XML に反映するのは、注の区切り・資料の始まりの直し
    （BOUNDARY_KINDS の 5 つ）だけ。判定は boundary_problem の 1 か所で、set_role_problem を先に通す。"""
    from jasme_jats.ai_assist import BOUNDARY_KINDS, STYLE_ONLY_WHY, boundary_kind, boundary_problem, role_style
    assert BOUNDARY_KINDS == {"注の始まり": "fn_start", "注の続き": "p", "資料の見出し": "app_heading",
                              "英文要旨の続き": "abstract", "資料の本文": "p"}
    _, plan, _ = _mechanical(STRUCTURE, journal)
    by_text = {p.plain(): p for p in plan.paras.values()}
    body = by_text["囲みの後の本文も，本文のまま続く。"]
    abstract = by_text["Structure abstract."]
    app_title = by_text["資料（授業プリント）"]
    app_para = by_text["問1\u3000架空の問題文である。"]
    endnote = next(fn.paras[0] for fn in plan.fns if fn.word_id == "endnote:5")
    # 区切りの直し
    assert boundary_problem(abstract, plan, "app_heading") == "" and boundary_kind(abstract, plan, "app_heading") == "資料の見出し"
    assert boundary_problem(app_para, plan, "app_heading") == ""
    assert boundary_kind(app_title, plan, "abstract") == "英文要旨の続き" and boundary_kind(app_title, plan, "p") == "資料の本文"
    # Word のスタイルで直せる指定は提案
    for p, role in ((body, "sec1"), (body, "quote"), (body, "fig_caption"), (body, "exclude"), (app_para, "abstract"),
                    (app_para, "p"), (abstract, "abstract"), (app_title, "exclude")):
        assert boundary_problem(p, plan, role) == STYLE_ONLY_WHY, (p.plain(), role)
    # set_role_problem の理由が先（提案にもしない）
    assert boundary_problem(endnote, plan, "p").startswith("Word の脚注・文末脚注の段落の役割は変えられない")
    assert boundary_problem(body, plan, "app_heading").startswith("資料の見出し（app_heading）にできるのは")
    # 提案のスタイル名は、設定の最初の日本語のスタイル名
    assert [role_style(journal, r) for r in ("sec1", "quote", "abstract", "p", "fn_heading", "exclude")] == [
        "章見出し", "ブロック引用", "英文要旨", "本文", "注見出し", ""]


@pytest.mark.parametrize("role", ["sec1", "quote", "exclude", "fig_caption", "abstract"])
def test_style_only_set_role_does_not_change_xml(role, journal, meta, tmp_path):
    """区切りの 5 つ以外の set_role（章見出し・引用・除外・図キャプション・資料の見出しでない段落への英文要旨）は、XML を 1 バイトも
    変えず、不採用の理由が STYLE_ONLY_WHY で、AIOutcome.style_fixes にスタイル名つきで入る（所有者の決定 5。W8 の手順 5）。
    AI の除外で本文が落ちない（C042）。"""
    path = tmp_path / "style.docx"
    mf.make_article(path, "提案の検証用文書", lambda b: [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "本文の文である。"),
                                                       mf.para(S["body"], "見出しに見える段落")],
                    appendix=[mf.para(S["abs"], "資料1\u3000架空の授業プリント"), mf.para(S["abs"], "架空のプリントの本文。")])
    _, plan, _ = _mechanical(path, journal)
    by_text = {p.plain(): s for s, p in plan.paras.items()}
    src = by_text["架空のプリントの本文。"] if role == "abstract" else by_text["見出しに見える段落"]
    none = _manual(path, None, meta, journal, tmp_path / "none")
    res = _manual(path, answers.answer(style_fixes=[(src, role)]), meta, journal, tmp_path / "out")
    assert res.xml_path.read_bytes() == none.xml_path.read_bytes()
    assert [why for _, why in res.ai.rejected] == [ai_assist.STYLE_ONLY_WHY] and res.ai.accepted == [] and res.ai.boundaries == []
    [fix] = res.ai.style_fixes
    assert (fix.src, fix.role, fix.verdict, fix.reason, fix.confidence) == (src, role, "直す", "試験", "高")
    assert fix.style == ai_assist.role_style(journal, role) and (fix.style or role == "exclude")
    assert not any(e.reason.startswith("AI") for e in res.plan.exclusions)
    assert ai_assist.STYLE_ONLY_WHY in res.report_path.read_text(encoding="utf-8")       # 2 章の不採用の一覧


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
    # 除外した段落の役割の指定は Word のスタイルで直す提案になる（XML は変えない。所有者の決定 5）ので、案内は 1 通り
    assert lines[journal_line].endswith("（確かめるだけ。本文に必要なら set_role で提案）")
    assert "set_role で指定できる役割:" not in req and "本文の一部なら set_role を提案" not in req
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
    assert "見出しではなく、前の資料の続きにします。前に資料がなければ" in system_prompt()
    # XML に反映するのは注の区切りと資料の始まりの直しだけで、ほかの役割は提案（所有者の決定 5。W8 の手順 5）
    assert "XML に反映するのは、注の区切りと資料の始まりの直しだけです" in system_prompt()
    assert "Word のスタイルで直す\n   提案として作業する人に知らせるだけで、XML は変えません" in system_prompt()


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


def _hint_and_note(plan, hint, note):
    """囲みのテキストボックス hint を「囲みの後の段落」の後ろの囲みに、note を図の注記にする回答。"""
    return answers.answer(boxes=[(hint, "囲み", _src(plan, "囲みの後の段落である。")), (note, "図の注記", "")])


def _manual_pl(path, placements, meta, journal, out):
    """placements を手で書いた回答（items の書き方そのものを試す）を手動モードで貼り戻して変換する。"""
    resp = json.dumps({"placements": placements, "operations": [], "notes": []}, ensure_ascii=False)
    return convert(path, meta, journal, Options(out_dir=out, ai_mode="manual", ai_response=resp))


def test_ai_kind_box_and_label_for_undecided_textboxes(journal, meta, tmp_path):
    # 囲みか図の注記か決められなかったテキストボックスは、AI の placements（kind box・label）で決める。box は指定の段落の直後の
    # boxed-text（ずらさない）、label は AI の判断の理由で除外する。どちらも 2 章の採用の一覧に place_float として載る
    plan, ids = _boxes_by_text(journal)
    hint, note = ids["（ヒント）"], ids["注"]
    assert plan.textboxes[hint].kind == plan.textboxes[note].kind == "undecided"
    res = _manual(STRUCTURE, _hint_and_note(plan, hint, note), meta, journal, tmp_path)
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
    assert "図表の位置、文字だけのテキストボックスの囲み・図の注記の判断と囲みの位置だけで、本文の文字は" in ch2
    assert (res.plan.textboxes[hint].kind, res.plan.textboxes[hint].mode, res.plan.textboxes[hint].where) == ("box", "ai", "ai")
    # 残った 1 件（Area model）だけが、要確認として残る（AI の回答を反映した後の文面）
    act = next(a for a in actions(res) if a.key == "textbox_undecided")
    assert "1 件" in act.box_title and "AI" not in act.box_detail      # Word での直し方だけ（AI の文は ai_finish。W8 の手順 7）
    report = res.report_path.read_text(encoding="utf-8")
    assert "| 囲み・図の注記（テキストボックス） |" in report.split("## 2.")[1].split("## 3.")[0]


def test_textbox_undecided_advice_after_ai_names_operation_of_each_screen(journal, meta, tmp_path):
    """修正計画 W8 の手順 7: 決められなかったテキストボックスの知らせは、AI の状態によらず Word での直し方だけを書く（AI に出し直して
    もらう操作は推奨の手順 ai_finish の「一部」の文が言う）。1 画面版の手動の欄は、知らせの key ではなく状態（report.ai_done が偽）で
    見せたままにする。"""
    from jasme_jats.ai_assist import AIOutcome
    from jasme_jats.app import AppState
    from jasme_jats.colab import step_text
    from jasme_jats.report import ai_state
    plan, ids = _boxes_by_text(journal)
    hint, note = ids["（ヒント）"], ids["注"]
    res = _manual(STRUCTURE, _hint_and_note(plan, hint, note), meta, journal, tmp_path / "manual")
    assert res.ai.mode == "manual" and res.plan.undecided_boxes and ai_state(res) == "一部"
    act = next(a for a in actions(res) if a.key == "textbox_undecided")
    for t in (act.top, act.box_detail, act.cli, act.checklist):
        assert "AI" not in t and "テキストボックスの外" in t, t
    fin = next(a for a in actions(res) if a.key == "ai_finish")
    assert "手順 6 で貼り付け直してください" in step_text(fin.box_detail, "notebook")
    assert "「AI の回答（json のコードブロック）を貼り付ける」の欄に貼り付け直して「反映」を押してください" in step_text(fin.box_detail, "app")
    st = AppState(tmp_path / "work")
    st.set_inputs(ai_mode="manual")
    st.res, st.run = res, types.SimpleNamespace(ai_mode="manual")      # 変換したときの入力の写し（手動の欄は写しで決まる）
    assert st.answer_box_open and st.prompt_text()                     # ai_finish の案内のとおり、貼り付け直す欄が見えている
    # API: ai_finish が「もう一度変換」を言う。textbox_undecided の文は手動と同じ
    api = _manual(STRUCTURE, _hint_and_note(plan, hint, note), meta, journal, tmp_path / "api")
    api.ai = AIOutcome(mode="api")
    api.ai.raw = "{}"
    act2 = next(a for a in actions(api) if a.key == "textbox_undecided")
    assert (act2.top, act2.box_detail, act2.cli, act2.checklist) == (act.top, act.box_detail, act.cli, act.checklist)
    fin = next(a for a in actions(api) if a.key == "ai_finish")
    assert "「変換する」をもう一度押してください" in step_text(fin.box_detail, "app")


def test_textbox_undecided_advice_when_ai_failed_and_checklist_follows_mode(journal, meta, tmp_path):
    """修正計画 W8 の手順 7: AI を使っていない・回答待ち・使った後・失敗（API / 手動）のどれでも、決められなかったテキストボックスの
    知らせの文は同じで、「AI」の語がない（AI を勧める文は推奨の手順 ai_finish の 1 か所。AI だけの原稿では ai_finish の見出しが
    「AI にテキストボックスの種類を判断させる（推奨）」）。"""
    from jasme_jats.ai_assist import AIOutcome
    from jasme_jats.colab import step_text
    plan, ids = _boxes_by_text(journal)
    hint, note = ids["（ヒント）"], ids["注"]
    none = convert(STRUCTURE, meta, journal, Options(out_dir=tmp_path / "none"))
    pend = convert(STRUCTURE, meta, journal, Options(out_dir=tmp_path / "pend", ai_mode="manual"))
    done = _manual(STRUCTURE, _hint_and_note(plan, hint, note), meta, journal, tmp_path / "done")
    errs = []
    for mode in ("api", "manual"):
        res = _manual(STRUCTURE, _hint_and_note(plan, hint, note), meta, journal, tmp_path / ("err_" + mode))
        res.ai = AIOutcome(mode=mode)
        res.ai.raw = "{}"
        res.ai.error = "AI の呼び出しに失敗しました: 試験"
        errs.append(res)
    texts = set()
    for res in [none, pend, done] + errs:
        assert res.plan.undecided_boxes
        act = next(a for a in actions(res) if a.key == "textbox_undecided")
        for t in (act.top, step_text(act.box_detail, "notebook"), act.cli, act.checklist):
            assert "AI" not in t and "\x00" not in t, t
        texts.add((act.checklist, act.box_detail, act.cli))
        assert any(a.key == "ai_finish" for a in actions(res))
    assert len(texts) == 2      # 件数（AI の答えで決めた分が減る）だけが違う
    fin = next(a for a in actions(none) if a.key == "ai_finish")
    assert not none.plan.asked_floats and fin.box_title == "AI にテキストボックスの種類を判断させる（推奨）"
    assert "AI が種類を判断します" in fin.box_detail


@pytest.mark.parametrize("empty", ["", 0, False, None])
def test_g5_falsy_caption_body_are_empty_lists(empty, journal, meta, tmp_path):
    """G5: placements の items の caption・body が falsy な値（""・0・false・null）のときは、以前どおり空の一覧として扱う
    （テキストボックスの box・label の指定は採用される）。真の値で一覧でないもの（"d16"・5）だけが不採用。"""
    plan, ids = _boxes_by_text(journal)
    hint, note = ids["（ヒント）"], ids["注"]
    res = _manual_pl(STRUCTURE, [_box_pl(hint, _src(plan, "囲みの後の段落である。"), caption=empty, body=empty),
                                 _box_pl(note, "", kind="label", caption=empty, body=empty)], meta, journal, tmp_path)
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    assert {op["src"] for op, _ in res.ai.accepted if op["op"] == "place_float"} == {hint, note}
    assert res.ai.rejected == []
    assert (res.plan.textboxes[hint].kind, res.plan.textboxes[note].kind) == ("box", "label")


def test_g5_truthy_non_list_caption_is_still_rejected(journal, meta, tmp_path):
    plan, ids = _boxes_by_text(journal)
    hint = ids["（ヒント）"]
    res = _manual_pl(STRUCTURE, [_box_pl(hint, _src(plan, "囲みの後の段落である。"), caption="d16", body=5)], meta, journal, tmp_path)
    assert res.fidelity.ok and [why for _, why in res.ai.rejected] == ["items の caption は一覧（[ ]）で書く"]
    assert res.plan.textboxes[hint].kind == "undecided"


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
    res = _manual(STRUCTURE, answers.answer(boxes=[(label, "囲み", after)]), meta, journal, tmp_path)
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
    res = _manual(STRUCTURE, answers.answer(boxes=[(label, "図の注記", "")]), meta, journal, tmp_path / "label")
    assert [why for _, why in res.ai.rejected] == [
        f"テキストボックス {label} は図に重ねた注記とみなして除外したので、指定できるのは box（本文の囲みに戻す）だけ（図の注記のままなら書かない）"]
    assert {t: w for _, w, t in res.fidelity.excluded}["A 点"] == "テキストボックス内の文字（図に重ねた注記とみなして本文から除外）"
    [warn] = [w for w in res.warnings if "図に重ねた注記と判断したテキストボックス" in w]
    assert warn.endswith("（6 章）。図の注記でなく本文の文字（問題文など）なら、Word で文字を"
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
    res = _manual(STRUCTURE, answers.answer(boxes=[(est, "囲み", _src(plan, "空の囲みを置いた。"))]), meta, journal, tmp_path)
    assert res.fidelity.ok and res.dtd_valid and res.plan.estimated_boxes == []
    bt = next(bt for bt in load(res).iter("boxed-text") if _text(bt).startswith("問3"))
    assert _text(bt.getprevious()) == "空の囲みを置いた。"
    assert "textbox_place" not in [a.key for a in actions(res)]
    # 浮動配置の図形（位置を決められなかった図表）に kind box を書いたものは、位置（after）だけを使う（items は読まない。
    # 修正計画 W1 の 2.7）。テキストボックスの kind にはしない
    _, fplan, _ = _mechanical(FLOAT, journal)
    out = AIOutcome()
    got = float_placements({"placements": [_box_pl("s1", "d13")]}, fplan, out)
    assert list(got) == ["s1"] and got["s1"]["after"] == "d13" and "kind" not in got["s1"] and out.rejected == []


def test_set_role_on_textbox_paragraphs(journal, meta, tmp_path):
    # 浮動配置でないテキストボックス（VML・行内）の段落に set_role で指定できるのは fig_caption・table_caption・exclude だけ
    # （ほかは placements の kind box・label を案内して採用しない。修正計画の F の (1)）。浮動配置の図形の段落は今までどおり
    # すべて placements で指定させる。指定できる fig_caption・exclude も、Word のスタイルで直す提案にして XML には反映しない
    # （所有者の決定 5。W8 の手順 5。VML のキャプションは、Word でスタイルを図キャプションにすれば図のキャプションになる）
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
    res = _manual(STRUCTURE, answers.answer(style_fixes=[(vml.src, "p"), (vml.src, "exclude")]), meta, journal, tmp_path / "s")
    rej = [(op["role"], w) for op, w in res.ai.rejected if op["src"] == vml.src]
    assert [r for r, _ in rej] == ["p", "exclude"] and "placements" in rej[0][1] and rej[1][1] == ai_assist.STYLE_ONLY_WHY
    assert [(f.role, f.style, f.how) for f in res.ai.style_fixes] == [("exclude", "", ai_assist.EXCLUDE_HOW)]
    assert not {t: w for _, w, t in res.fidelity.excluded}.get(vml.plain(), "").startswith("AI 補完で")   # AI の除外で本文を落とさない（C042）
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
    res = _manual(path, answers.answer(style_fixes=[(cap, "fig_caption"), (cap, "p")]), meta, journal, tmp_path / "v")
    assert res.ai.accepted == [] and [op["role"] for op, w in res.ai.rejected if "placements" in w] == ["p"]
    assert [(f.src, f.role, f.style) for f in res.ai.style_fixes] == [(cap, "fig_caption", "図キャプション")]
    assert res.xml_path.read_bytes() == _manual(path, None, meta, journal, tmp_path / "v0").xml_path.read_bytes()
    assert res.fidelity.ok and res.dtd_valid


def test_textbox_placement_is_used_when_set_role_is_a_proposal(journal, meta, tmp_path):
    # 同じ回答で、決められない（浮動配置でない）テキストボックスの段落を set_role で図キャプションにし、そのテキストボックスに
    # placements の kind label も指定したとき: set_role は Word のスタイルで直す提案にして XML に反映しない（所有者の決定 5。
    # W8 の手順 5）ので、テキストボックスは組み直した後も文字だけのテキストボックスのままで、kind の指定を採用する
    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "試験（2024）の札。", mf.vml_textbox(mf.para(S["body"], "（ヒント）"))),
                mf.para(S["body"], "札の後の段落。")]
    path = tmp_path / "vmlhint.docx"
    mf.make_article(path, "札の検証用文書", parts)
    _, plan, _ = _mechanical(path, journal)
    [xid] = plan.undecided_boxes
    src = plan.textboxes[xid].paras[0].src
    res = _manual(path, answers.answer(boxes=[(xid, "図の注記", "")], style_fixes=[(src, "fig_caption")]), meta, journal, tmp_path / "out")
    assert [op["op"] for op, _ in res.ai.accepted] == ["place_float"] and res.plan.paras[src].role != "fig_caption"
    assert [(op["op"], why) for op, why in res.ai.rejected] == [("set_role", ai_assist.STYLE_ONLY_WHY)]
    assert res.plan.undecided_boxes == [] and res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    # set_role がなければ、kind label を採用する（今までどおり）
    res = _manual(path, answers.answer(boxes=[(xid, "図の注記", "")]), meta, journal, tmp_path / "label")
    assert [op["op"] for op, _ in res.ai.accepted] == ["place_float"] and res.ai.rejected == []


def test_textbox_placement_after_excluded_paragraph_is_kept(journal, meta, tmp_path):
    # 同じ回答で、本文の段落を set_role exclude にし、その段落を after にした kind box も指定したとき: exclude は Word で消す
    # 提案にして XML に反映しない（AI の除外で本文を落とさない。所有者の決定 5・C042。W8 の手順 5）ので、after は本文の段落の
    # ままで、kind box を採用する
    plan, ids = _boxes_by_text(journal)
    hint, after = ids["（ヒント）"], _src(plan, "囲みの後の段落である。")
    res = _manual(STRUCTURE, answers.answer(boxes=[(hint, "囲み", after)], style_fixes=[(after, "exclude")]), meta, journal, tmp_path)
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and res.jstage_issues == []
    assert [(op["op"], why) for op, why in res.ai.rejected] == [("set_role", ai_assist.STYLE_ONLY_WHY)]
    assert [op["op"] for op, _ in res.ai.accepted] == ["place_float"]
    assert res.plan.textboxes[hint].kind == "box" and hint not in res.plan.undecided_boxes
    assert "囲みの後の段落である。" not in {t for _, _, t in res.fidelity.excluded}


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
    example = example_block()
    assert example["placements"][1]["float"] == "x2" and example["placements"][1]["items"][0]["kind"] == "box"
    assert "（kind は box か label）" in a.manual_prompt("依頼文", [])
    assert ("「# 図に重ねた注記とみなして除外したテキストボックス」に挙げたものは、本文の文章（問題文・ヒントなど）のときだけ、"
            "placements に kind box で書いてください。") in a.manual_prompt("依頼文", [])
    assert "「図に重ねた注記とみなして除外したテキストボックス」に挙げたもの" in a.PLACEMENT_SCHEMA["properties"]["float"]["description"]


def test_prompts_ask_only_positions_of_floats(journal):
    """依頼文・項目の説明・スキーマ・見本は、図形には位置（after）だけを聞く（修正計画 W8 の手順 6）。中身の組み合わせ（items）の
    組み方・数式の画像の書き起こし（formula_image）・画像の添付の説明はない。items は必須のまま（ChatGPT の strict な構造化出力
    のため）で、図形では空の一覧 []、テキストボックスだけ kind の組 1 つ。"""
    a = ai_assist
    _, plan, linker = _mechanical(FLOAT, journal)
    texts = {"system": a.system_prompt(), "guide": a.FIELD_GUIDE,
             "manual": a.manual_prompt(a.build_request(plan, linker)[0]), "schema": json.dumps(a.RESPONSE_SCHEMA, ensure_ascii=False)}
    for name, t in texts.items():
        assert "formula_image" not in t and "MathML" not in t, name
        assert "組み合わせ（items）" not in t and "位置と組み合わせ" not in t and "画像 ID" not in t, name
        assert "添付" not in t and "画像だけの段落 ID" not in t, name
    assert "答えるのは位置（after）だけです" in texts["system"] and "items は、空の一覧 [] にしてください" in texts["system"]
    assert "- items: 図形（s1 など）では空の一覧 []" in texts["guide"]
    assert "formula_image" not in a.OP_SCHEMA["properties"]["op"]["enum"]
    sch = a.PLACEMENT_SCHEMA
    assert "items" in sch["required"] and sch["properties"]["items"]["description"].startswith("図形（s1 など）では空の一覧 []")
    example = example_block()
    assert example["placements"][0]["float"] == "s1" and example["placements"][0]["items"] == []
    assert example["placements"][1]["items"][0]["kind"] == "box"


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
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", ai_mode="manual"))
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
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, ai_mode="manual"))
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
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", ai_mode="manual"))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    [warn] = [w for w in res.warnings if "英文の著者名" in w]
    assert "「KENKYU」" in warn and "全体を姓として" in warn and "Word で" in warn
    assert any(d.category == "name" and "「KENKYU」" in d.message for d in res.build_notes)
    names = [ln for ln in res.prompt_path.read_text(encoding="utf-8").splitlines() if "姓と名の区切りがない氏名" in ln]
    assert len(names) == 1 and names[0].endswith("「KENKYU」") and "split_name は和文の氏名にだけ使える" in names[0]
    assert [a.key for a in actions(res)] == []      # 手動の回答待ちは、位置を聞く図形がないので 2 章の 1 行だけ
    root = load(res)
    [en] = [n for n in root.iter("name") if n.get("name-style") == "western"]
    assert [(x.tag, x.text) for x in en] == [("surname", "KENKYU")]
    # AI が英文の氏名に split_name を提案しても採用しない（依頼文の添え書きと 10 章の警告のとおり。XML も変わらない）
    src = names[0].split("]", 1)[0].removeprefix("- [")
    resp = answers.answer(names=[(src, "KEN", "KYU", "試しの分割", "低")])
    res2 = convert(path, meta, journal, Options(out_dir=tmp_path / "out2", ai_mode="manual", ai_response=resp))
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
    return convert(FULL, meta, journal, Options(out_dir=out, ai_mode="manual", ai_response=resp))


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
    """A1: placements の各欄の型が違っても変換は止まらず、理由付きで不採用（float・after の型）。浮動配置の図形の items は
    読まないので（修正計画 W1 の 2.7）、items の型の違いは理由にならず、図形の ID で不採用になる（この原稿に図形 s1 はない）。"""
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
    assert sum("float と after は文字列で書く" in w for w in whys) == 4
    assert sum("s1 は「位置を決められなかった図表」" in w for w in whys) == 6 and not any("一覧（[ ]）" in w for w in whys)


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


def test_a8_formula_image_is_always_rejected(journal):
    """docx の画像を AI に渡さなくなった（修正計画 W1 の 2.7）ので、formula_image は中身にかかわらず不採用に記録し、図に数式を
    付けない（操作そのものは W8 が消す）。"""
    _, plan, _ = _mechanical(FULL, journal, {}, {})
    fig = next(f for f in plan.figures if any(i.image_id == "img3" for ip in f.image_paras for i in ip.images))
    mml = '<math xmlns="http://www.w3.org/1998/Math/MathML"><mi>a</mi></math>'
    out = ai_assist.AIOutcome()
    ai_assist.apply_ops([_op(op="formula_image", image="img3", mathml=mml)], plan, None, out)
    assert out.accepted == [] and out.rejected[0][1] == ai_assist.FORMULA_IMAGE_WHY and fig.formula is None


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
        resp = answers.answer(links=[("図", cap, text, 1, "F2")])
        return convert(p, meta, journal, Options(out_dir=tmp_path / sub, ai_mode="manual",
                                                 ai_response=resp, split_labels=split))
    res = run(True, "図1", "a")
    assert res.fidelity.ok and res.ai.accepted == [] and "<label>" in res.ai.rejected[0][1]
    assert not [x for x in load(res).iter("xref") if x.get("ref-type") == "fig"]
    res = run(False, "図1", "b")
    assert len(res.ai.accepted) == 1 and [x for x in load(res).iter("xref") if x.get("ref-type") == "fig"]
    res = run(True, "a", "c")                       # 番号の後ろ（タイトル）は <label> の外
    assert len(res.ai.accepted) == 1 and [x for x in load(res).iter("xref") if x.get("ref-type") == "fig"]


def test_a8_formula_image_on_real_docx_with_table_and_moved_image(journal, meta, tmp_path):
    """A8: 図形の中の画像と表を formula_image にしようとしても、表が残り、不変性チェックも通る。W1 からは、キャプションのない
    図形（画像を直接持たないテキストボックス）の画像と表は別々の要素として出る（float_units の B4。AI の items は読まない）ので、
    画像はキャプションなしの図、表は表のまま。"""
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
    res = convert(p, meta, journal, Options(out_dir=tmp_path / "o", ai_mode="manual", ai_response=resp))
    assert res.fidelity.ok and res.fidelity.final_ok
    assert not any(op["op"] == "place_float" for op, _ in res.ai.rejected)
    root = load(res)
    assert "表の文字甲" in res.xml_path.read_text(encoding="utf-8")
    assert not any(f.find("table-wrap") is not None for f in root.iter("fig"))      # 表は図の中に入らない


# ---------------------------------------------------------------------------- 回答の形（A9・A10・{ } でない操作）
_OP1 = {"op": "set_role", "src": "d5", "text": "", "occurrence": 1, "target": "", "role": "sec1", "image": "",
        "mathml": "", "surname": "", "given": "", "reason": "試験", "confidence": "高"}
_EMPTY_ANS = {"placements": [], "operations": [], "notes": []}


@pytest.mark.parametrize("text", [
    json.dumps([_OP1]),
    "```json\n" + json.dumps([_OP1]) + "\n```",
    "```json\n" + json.dumps([_OP1, dict(_OP1, src="d6")], indent=2) + "\n```",
    json.dumps([_OP1]) + "\n以上です。",
    json.dumps([_EMPTY_ANS]),
])
def test_parse_response_rejects_top_level_array(text):
    with pytest.raises(ValueError, match="一覧（\\[ \\] で囲んだもの）"):
        parse_response(text)


def test_parse_response_empty_array_is_not_found():
    with pytest.raises(ValueError, match="JSON（{ で始まり } で終わる部分）が見つかりません"):
        parse_response("[]")


def test_parse_response_requires_operations():
    with pytest.raises(ValueError, match="操作 1 件だけ"):
        parse_response(json.dumps(_OP1))
    for d in ({"placements": []}, {"notes": []}):
        with pytest.raises(ValueError, match="operations の一覧がありません"):
            parse_response(json.dumps(d))
    with pytest.raises(ValueError, match="operations が一覧"):
        parse_response(json.dumps({"operations": {}}))
    assert parse_response(RESPONSE)["operations"]
    assert parse_response(json.dumps(_EMPTY_ANS))["operations"] == []
    assert example_block()["operations"]


def test_manual_array_answer_is_ai_error(journal, meta, tmp_path):
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, ai_mode="manual", ai_response=json.dumps([_OP1])))
    assert "一覧" in res.ai.error
    assert next(a for a in actions(res) if a.key == "ai_finish").failed and "ai_error" not in {a.key for a in actions(res)}
    assert res.fidelity.ok


def test_deeply_nested_answer_does_not_abort(journal, meta, tmp_path):
    n = 100000
    resp = '{"placements": [], "operations": [' + "[" * n + "]" * n + "]}"
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, ai_mode="manual", ai_response=resp))
    assert "入れ子" in res.ai.error and next(a for a in actions(res) if a.key == "ai_finish").failed
    with pytest.raises(ValueError, match="入れ子"):
        parse_response(resp)
    assert ai_assist.parse_cut_response('{"placements": [{"float": "s1"}, ' + "[" * n) is None
    assert ai_assist.parse_cut_response('{"placements": [' + "[" * n) is None


def test_cut_top_level_array_is_not_partial(journal, meta, tmp_path):
    cut = '[{"placements": [{"float": "s1", "kind": "box"}], "operations": [{"op": "link_'
    for text in ("```json\n" + cut, cut):
        assert ai_assist.parse_cut_response(text) is None
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, ai_mode="manual", ai_response="```json\n" + cut))
    assert "一覧" in res.ai.error and not res.ai.partial


def test_split_ops_records_non_dict_ops(journal, meta, tmp_path):
    outcome = types.SimpleNamespace(rejected=[])
    assert ai_assist.split_ops({"operations": ["link_citation d18", [1]]}, outcome) == []
    assert len(outcome.rejected) == 2
    assert "str" in outcome.rejected[0][1] and "list" in outcome.rejected[1][1]
    assert outcome.rejected[0][0]["text"] == "link_citation d18"
    res = _manual_raw(["link_citation d18", [1]], meta, journal, tmp_path)
    assert len(res.ai.rejected) == 2 and res.fidelity.ok
    report = res.report_path.read_text(encoding="utf-8")
    sec2 = report.split("\n## 2.")[1].split("\n## 3.")[0]                              # 2 章の不採用の表
    assert "link_citation d18" in sec2
    assert sum("操作が { } のまとまりでない（str）" in ln for ln in sec2.splitlines()) == 1
    assert sum("操作が { } のまとまりでない（list）" in ln for ln in sec2.splitlines()) == 1


# ----------------------------------------------------------------------------- 英文要旨が見つからないとき（u5-exclusions）
def test_set_role_abstract_for_missing_abstract_is_a_proposal(journal, meta, tmp_path):
    """英文要旨のスタイルも見出しもない原稿では、依頼文が「英文要旨の段落が見つからない」と書き、AI の set_role の abstract を案内する。
    英文要旨のスタイルのない段落を英文要旨にする指定は、Word のスタイルで直す提案にして XML には反映しない（所有者の決定 5。
    W8 の手順 5）。abstract_missing は残り、XML は回答なしと同じ。"""
    from test_structure import _no_abstract_style_docx
    from jasme_jats.structure import EN_OTHER_EXCLUDED
    path = _no_abstract_style_docx(tmp_path)
    before = convert(path, meta, journal, Options(out_dir=tmp_path / "before", ai_mode="manual"))
    assert "abstract_missing" in [a.key for a in actions(before)] and before.plan.abstract == []
    prompt = before.prompt_path.read_text(encoding="utf-8")
    assert "英文要旨の段落が見つからない" in prompt
    assert "set_role の abstract を提案（XML には反映せず、作業する人に知らせる）" in prompt
    first = next(s for s, why, _ in before.fidelity.excluded if why == EN_OTHER_EXCLUDED)
    assert first in prompt
    res = _manual(path, answers.answer(style_fixes=[(first, "abstract")]), meta, journal, tmp_path / "after")
    assert res.plan.abstract == [] and res.fidelity.ok and res.dtd_valid
    assert [why for _, why in res.ai.rejected] == [ai_assist.STYLE_ONLY_WHY]
    assert [(f.src, f.role, f.style) for f in res.ai.style_fixes] == [(first, "abstract", "英文要旨")]
    assert "abstract_missing" in [a.key for a in actions(res)]
    assert res.xml_path.read_bytes() == _manual(path, None, meta, journal, tmp_path / "none").xml_path.read_bytes()


# ----------------------------------------------------------------------------- 構造の衝突と AI（u6-k1k2）
def test_conflict_in_original_docx_stops_before_ai(journal, meta, tmp_path):
    """元の docx に K1 の形（本文スタイルの「注」が 2 つで、注の見出しが 2 つになる）があるときは、AI の回答を反映する前に
    StructureConflictError で中止する。2 つ目の「注」に p を指定する回答（AI が直せる形）でも、元の docx で止めて Word で直してもらう
    （手動モードでも AI依頼文.txt を書かない。API の費用もかけない）。"""
    from test_structure import conflict_doc

    from jasme_jats.pipeline import StructureConflictError, _mechanical
    path = conflict_doc(tmp_path, "K1_fn_text2_kept")
    _, plan, _ = _mechanical(path, journal)
    second = [s for s, p in plan.paras.items() if p.plain() == "注"][1]
    out = tmp_path / "out"
    with pytest.raises(StructureConflictError) as e:
        _manual(path, answers.answer(style_fixes=[(second, "p")]), meta, journal, out)
    assert e.value.conflicts and not (out / "AI依頼文.txt").exists() and list(out.iterdir()) == []


def _src_of(plan, text):
    [src] = [s for s, p in plan.paras.items() if p.plain() == text]
    return src


def _p(style, t):
    return mf.para(mf.S[style], t)


_K2_AUTHORS = dict(ja_rows=(), loose=(_p("aff_ja", "第一大学"), _p("author_ja", "試験　六郎"), _p("aff_ja", "第二大学"),
                                      _p("author_ja", "架空　花子")))
# 名前 -> (make_fixtures.make_conflict の引数, set_role する段落の文字, 役割)。元の docx には構造の衝突がなく、この set_role で組み直すと
# 衝突ができる（引用文献の 2 件目の段落を引用文献の見出しに、本文の段落を謝辞の見出しに、所属・著者・所属・著者の著者 1 を除外・題目・副題に）
CONFLICT_ROLE_CASES = {
    "ref_heading_on_ref": (dict(back=[_p("ref_head", "引用文献"), _p("ref", "試験六郎（2024）．『本』．架空社．"), _p("ref", "参考文献"),
                                      _p("ref", "架空花子（2020）．『本』．架空社．")]), "参考文献", "ref_heading"),
    "ack_heading_on_body": (dict(body=[_p("body", "謝辞"), _p("body", "先の謝辞の本文。"), _p("body", "お礼"),
                                       _p("body", "後の謝辞の本文。")]), "お礼", "ack_heading"),
    "author_exclude": (_K2_AUTHORS, "試験　六郎", "exclude"),
    "author_title": (_K2_AUTHORS, "試験　六郎", "title"),
    "author_subtitle": (_K2_AUTHORS, "試験　六郎", "subtitle"),
}


def _reflect_all_roles(monkeypatch):
    """区切りの 5 つ（ai_assist.BOUNDARY_KINDS）以外の set_role も XML に反映する形に差し替える。

    所有者の決定 5（W8 の手順 5）で、見出し・除外・題目などの set_role は Word のスタイルで直す提案になり、構造の衝突（K1・K2）を
    作る指定は区切りの直しにほとんど残らない。構造の衝突の守り（pipeline._reject_roles・structure.conflict_overrides。変えない）を
    確かめ続けるため、衝突を作りやすい役割の指定で試す。"""
    monkeypatch.setattr(ai_assist, "boundary_kind", lambda p, plan, role: "試験の区切り")


@pytest.mark.parametrize("name", list(CONFLICT_ROLE_CASES))
def test_set_role_that_makes_conflict_is_rejected(name, journal, meta, tmp_path, monkeypatch):
    """AI の set_role で組み直すと構造の衝突（同じ種類の後付けの見出しが 2 つ・著者名に付かない所属。K1・K2）ができるときは、中止せず、
    その set_role を不採用（2 章。CONFLICT_ROLE_WHY）にして組み直す。不変性チェックは合格し、衝突は残らない。
    今の判定（決定 5）では、これらの指定は Word のスタイルで直す提案で、XML には反映しない（組み直さない）。"""
    kw, text, role = CONFLICT_ROLE_CASES[name]
    path = mf.make_conflict(tmp_path / f"{name}.docx", **kw)
    _, plan, _ = _mechanical(path, journal)
    src = _src_of(plan, text)
    assert plan.structure_conflicts == [] and _mechanical(path, journal, {src: role})[1].structure_conflicts
    res = _manual(path, answers.answer(style_fixes=[(src, role)]), meta, journal, tmp_path / "proposal")
    assert [(op["src"], why) for op, why in res.ai.rejected] == [(src, ai_assist.STYLE_ONLY_WHY)], name
    assert [f.src for f in res.ai.style_fixes] == [src] and res.plan.structure_conflicts == [], name
    _reflect_all_roles(monkeypatch)
    res = _manual(path, answers.answer(style_fixes=[(src, role)]), meta, journal, tmp_path / "out")
    assert [(op["src"], op["role"], why) for op, why in res.ai.rejected] == [(src, role, pipeline.CONFLICT_ROLE_WHY)], name
    assert not [op for op, _ in res.ai.accepted if op["op"] == "set_role"] and res.ai.boundaries == [], name
    assert res.plan.structure_conflicts == [] and res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid, name
    assert pipeline.CONFLICT_ROLE_WHY in res.report_path.read_text(encoding="utf-8")       # 2 章の不採用の一覧
    assert "set_role" not in pipeline.CONFLICT_ROLE_WHY


def _count_mechanical(monkeypatch):
    """pipeline._mechanical の呼び出しごとの AI の役割の指定（overrides）を記録する（組み直しの回数と、使った指定を確かめる）。"""
    calls, orig = [], pipeline._mechanical

    def wrapped(docx_path, journal, overrides=None, placements=None):
        calls.append(dict(overrides or {}))
        return orig(docx_path, journal, overrides, placements)
    monkeypatch.setattr(pipeline, "_mechanical", wrapped)
    return calls


@pytest.mark.parametrize("role", ["exclude", "title", "subtitle"])
def test_conflict_range_keeps_other_set_roles(role, journal, meta, tmp_path, monkeypatch):
    """AI の set_role で衝突ができたとき、1 段目は衝突の範囲（落ちる所属から次の所属まで。前付けの中）の段落への set_role だけを
    不採用にして組み直す: 本文の見出しへの set_role は採用されたまま、著者 1 への set_role だけが不採用（組み立ては 3 回: 機械的な
    組み立て・回答を反映・1 段目）。同じ段落への set_role を 2 つ書いた回答では、両方とも不採用になる。"""
    path = mf.make_conflict(tmp_path / "k2.docx", **_K2_AUTHORS)
    _, plan, _ = _mechanical(path, journal)
    author, head = _src_of(plan, "試験　六郎"), _src_of(plan, "１．はじめに")
    _reflect_all_roles(monkeypatch)                  # 区切り以外の役割も反映する形で、衝突の守りを確かめる
    calls = _count_mechanical(monkeypatch)
    res = _manual(path, answers.answer(style_fixes=[(author, role), (head, "sec2")]), meta, journal, tmp_path / "a")
    assert [(op["src"], why) for op, why in res.ai.rejected] == [(author, pipeline.CONFLICT_ROLE_WHY)]
    assert [op["src"] for op, _ in res.ai.accepted if op["op"] == "set_role"] == [head]
    assert [b.src for b in res.ai.boundaries] == [head]          # 使わなかった指定は、反映した直しの一覧から除く
    assert calls == [{}, {author: role, head: "sec2"}, {head: "sec2"}]
    assert res.plan.structure_conflicts == [] and res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    assert [x for x in res.plan.decisions if x.stage == "ai" and x.src == head]           # 本文の見出しの指定は判断の一覧に残る
    assert [[x.ja.plain() for x in a.affs] for a in res.plan.authors] == [["第一大学"], ["第二大学"]]   # 著者 1 は元のまま
    # 同じ段落への set_role が 2 つ（後ろの指定が使われる）: 両方とも不採用（2 章に 2 件）
    calls.clear()
    res = _manual(path, answers.answer(style_fixes=[(author, role), (author, "exclude")]), meta, journal, tmp_path / "b")
    assert [(op["src"], op["role"], why) for op, why in res.ai.rejected] == [
        (author, role, pipeline.CONFLICT_ROLE_WHY), (author, "exclude", pipeline.CONFLICT_ROLE_WHY)]
    assert not res.ai.accepted and calls == [{}, {author: "exclude"}, {}]
    assert res.plan.structure_conflicts == [] and res.fidelity.ok


def test_conflict_outside_range_rejects_all_set_roles(journal, meta, tmp_path, monkeypatch):
    """衝突の範囲の中に AI の指定がない衝突（範囲の外の set_role だけでできた衝突）では、1 段目を飛ばし、2 段目で set_role をすべて
    不採用にして組み直す。形: 本文スタイルの「注」が 2 つ続いた後ろに章見出しがあるので、機械的には先の「注」から章見出しの前までを
    本文に戻す（K5）。AI がその章見出しを本文の段落（p）にすると、本文に戻さなくなり、注の見出しが 2 つになる（衝突の範囲は 2 つの
    「注」の間で、章見出しは範囲の外）。本文の見出しへの別の set_role も不採用になる。"""
    from jasme_jats.structure import conflict_overrides
    path = mf.make_conflict(tmp_path / "k5.docx", body=[_p("body", "注"), _p("body", "1) 注の本文である。"), _p("body", "注"),
                                                       _p("body", "2) 二つ目の注。"), _p("sec1", "２．続き"),
                                                       _p("body", "本文の続きである。")])
    _, plan, _ = _mechanical(path, journal)
    chapter, head = _src_of(plan, "２．続き"), _src_of(plan, "１．はじめに")
    assert plan.structure_conflicts == [] and [k for _, k, _ in plan.fn_guess_checks] == ["returned"]
    _, plan_p, _ = _mechanical(path, journal, {chapter: "p", head: "sec1"})
    [c] = plan_p.structure_conflicts
    assert c.kind == "fn_heading" and conflict_overrides(plan_p, {chapter: "p", head: "sec1"}) == set()
    _reflect_all_roles(monkeypatch)                  # 区切り以外の役割も反映する形で、衝突の守りを確かめる
    calls = _count_mechanical(monkeypatch)
    res = _manual(path, answers.answer(style_fixes=[(chapter, "p"), (head, "sec1")]), meta, journal, tmp_path / "out")
    assert [(op["src"], why) for op, why in res.ai.rejected] == [(chapter, pipeline.CONFLICT_ROLE_WHY),
                                                                 (head, pipeline.CONFLICT_ROLE_WHY)]
    assert calls == [{}, {chapter: "p", head: "sec1"}, {}]       # 1 段目の組み直しはない
    assert not res.ai.accepted and res.plan.structure_conflicts == [] and res.fidelity.ok and res.fidelity.final_ok


def test_conflict_overrides_range(journal, tmp_path):
    """conflict_overrides: 範囲は落ちる段落と置き換えた段落の間（docx の順）。著者名の続かない最後の所属は、和文の冒頭（所属・著者表・
    AI が除外した段落を含む）が続くところまでで、本文・後付けへの指定は範囲に入れない。範囲の中に指定がなければ空。"""
    from test_structure import conflict_doc

    from jasme_jats.structure import conflict_overrides
    for name, inside, outside in (
            ("K1_ref_ref", ["引用文献", "試験六郎（2024）．「小さな論文」．『架空誌』，第5巻，pp.9-10．", "参考文献"],
             ["１．はじめに", "架空花子（2020）．『本』．架空社．"]),
            ("K2_loose_aff_aff_author", ["第一大学", "第二大学"], ["試験　六郎", "１．はじめに"]),
            ("K2_loose_trailing_aff", ["第二大学"], ["第一大学", "試験　六郎", "１．はじめに", "引用文献"]),
            ("K2_table_then_loose_author", ["第一大学", "試験　六郎"], ["検証用の論文", "１．はじめに"])):
        _, plan, _ = _mechanical(conflict_doc(tmp_path, name), journal)
        every = {s: "p" for s in plan.paras}
        got = conflict_overrides(plan, every)
        assert {_src_of(plan, t) for t in inside} <= got, name
        assert not {_src_of(plan, t) for t in outside} & got, name
        assert all(plan.region.get(s) in ("front_ja", "authors", "excluded") for s in got) or not name.startswith("K2"), name
        assert conflict_overrides(plan, {s: r for s, r in every.items() if s not in got}) == set(), name


# ---- C019: 依頼文・見本を回答の欄に貼ったときは、回答全体を断る
def _real_answer_block():
    d = {"placements": [], "operations": [dict(_OP1, reason="本物の回答の理由")], "notes": []}
    return "```json\n" + json.dumps(d, ensure_ascii=False, indent=1) + "\n```"


def test_pasted_request_is_refused(journal, meta, tmp_path):
    first = convert(FULL, meta, journal, Options(out_dir=tmp_path / "a", ai_mode="manual"))
    prompt = first.prompt_path.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="依頼文"):
        parse_response(prompt)
    assert ai_assist.parse_cut_response(prompt) is None
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path / "b", ai_mode="manual", ai_response=prompt))
    assert "依頼文" in res.ai.error and not res.ai.accepted
    assert next(a for a in actions(res) if a.key == "ai_finish").failed and "ai_error" not in {a.key for a in actions(res)}
    assert res.fidelity.ok
    # 依頼文の見出しの行と同じ文字でも、行頭の見出しの行でなければ（notes や reason に引用しても）断らない
    ok = json.loads(RESPONSE)
    ok["notes"] = [ai_assist.REQUEST_HEADING + " の見出しは" + ai_assist.MANUAL_ANSWER_HEADING + "と同じ"]
    assert parse_response(json.dumps(ok, ensure_ascii=False))["operations"]


def test_several_code_blocks_are_refused():
    # 見本のあとに本物の回答が続く回答も、どれを読むか推測せず断る
    with pytest.raises(ValueError, match="2 つ"):
        parse_response(f"見本はこうです。\n{ai_assist.MANUAL_EXAMPLE}\n\n回答です。\n{_real_answer_block()}\n")
    # コードブロックが 1 つなら、前後の説明があっても今までどおり読む。{ で始まる回答（中身だけのコピー）も同じ
    assert parse_response("回答です。\n" + _real_answer_block() + "\n以上")["operations"]
    assert parse_response(_real_answer_block().split("\n", 1)[1].rsplit("\n", 1)[0])["operations"]


def test_sample_items_in_answer_are_refused():
    # 見本のコードブロックそのもの。断る文は件数だけを言い、内部の項目名・ID は出さない
    ex = example_block()
    n = len(ex["operations"]) + len(ex["placements"])
    with pytest.raises(ValueError, match="見本") as ei:
        parse_response(ai_assist.MANUAL_EXAMPLE)
    msg = str(ei.value)
    assert f"{n} 件" in msg and "operations" not in msg and "placements" not in msg and "link_" not in msg
    assert not any(x["src"] in msg for x in ex["operations"]) and not any(x["float"] in msg for x in ex["placements"])
    # 画面ごとの操作（手順番号・欄の名前・ファイル名）は書かない（レポート・コマンドラインにもそのまま出る文）
    for m in (ai_assist.PASTED_REQUEST_MSG, msg):
        assert "手順" not in m and "欄" not in m and ".txt" not in m
    # 見本の操作が 1 件だけ入った回答（ほかは本物）
    d = {"placements": [], "operations": [example_block()["operations"][1], dict(_OP1, reason="本物の回答の理由")], "notes": []}
    with pytest.raises(ValueError, match="見本"):
        parse_response(json.dumps(d, ensure_ascii=False))
    # 見本の図表の位置が 1 件
    d = {"placements": [example_block()["placements"][0]], "operations": [], "notes": []}
    with pytest.raises(ValueError, match="見本"):
        parse_response(json.dumps(d, ensure_ascii=False))
    # 見本と ID だけが同じで理由の違うもの（本物の回答）は読む
    d = {"placements": [], "operations": [dict(example_block()["operations"][1], reason="本物の理由")], "notes": []}
    assert parse_response(json.dumps(d, ensure_ascii=False))["operations"]
    # 途中で切れた回答から読む位置の指定でも、見本の写しは使わない
    cut = json.dumps(example_block()["placements"][:1], ensure_ascii=False)
    assert ai_assist.parse_cut_response('{"placements": ' + cut[:-1] + ', {"float": "s9"') is None


def test_ai_advice_is_only_in_ai_finish_sources():
    """修正計画 W8 の手順 7: ほかの知らせの AI の文をなくしたので、状態を分ける関数 ai_pending・float_ref_ai、目印 answer_apply、
    1 画面版の知らせの key の一覧 REPASTE_KEYS は、製品のコードにない（手動の欄は report.ai_done で決める）。"""
    from pathlib import Path

    import jasme_jats
    root = Path(jasme_jats.__file__).parent
    for f in sorted(root.glob("*.py")):
        text = f.read_text(encoding="utf-8")
        for word in ("ai_pending", "REPASTE_KEYS", "float_ref_ai", '"answer_apply"'):
            assert word not in text, (f.name, word)
