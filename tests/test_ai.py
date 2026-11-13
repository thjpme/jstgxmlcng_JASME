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
from jasme_jats.ai_assist import DEFAULT_MODEL, parse_response
from jasme_jats.model import Para
from jasme_jats.pipeline import Options, _mechanical, convert
from jasme_jats.report import actions

RESPONSE = (DATA / "ai_response_sample_full.json").read_text(encoding="utf-8")
FLOAT_RESPONSE = json.loads((DATA / "ai_response_sample_float.json").read_text(encoding="utf-8"))
# 出版版 PDF を見たと答える回答（pdf.status が「見た」。ツールに PDF がなければ「見た（確かめられない）」で、手順 ai_finish が済む）
FLOAT_SEEN = {**FLOAT_RESPONSE, "pdf": {"status": "見た", "pages": 0}}
# 前の形の回答（operations を持つ。W8 の手順 10 で断るようになった形）
FLOAT_OLD = json.dumps({"placements": [{"float": "s1", "after": "d17", "items": [], "reason": "x", "confidence": "中"}],
                        "operations": [], "notes": []})


ALL_SECTIONS = [ai_assist.RequestSection(k, i, k, "", frozenset()) for i, k in enumerate(ai_assist.ANSWER_LISTS + ("notes",), 1)]


def example_block(sections=ALL_SECTIONS):
    """依頼文の「## 回答の形」の見本（既定は、頼むことの節をすべて出したとき）のコードブロックの中身を JSON として読む
    （parse_response は見本そのものを断るので通さない）。"""
    return json.loads(ai_assist.RE_FENCE.search(ai_assist.request_instructions(sections)).group(1))


def _info(exclusions=(), unsplit_names=(), name_splits=()):
    """build_request に渡す builder.BuildInfo の代わり（依頼文が読む 3 つだけ）。"""
    return types.SimpleNamespace(exclusions=list(exclusions), unsplit_names=list(unsplit_names), name_splits=list(name_splits))


def load(res):
    return etree.fromstring(res.xml_path.read_bytes().split(b"\n", 2)[2])


def test_manual_mode_applies_valid_ops_and_rejects_invalid(journal, meta, tmp_path):
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, ai_mode="manual", ai_response=RESPONSE))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    root = load(res)
    bibr = {(x.text, x.get("rid")) for x in root.iter("xref") if x.get("ref-type") == "bibr"}
    assert {("2001", "B2"), ("2025", "B7"), ("2016", "B4"), ("1977", "B10")} <= bibr
    rejected = {op["text"] for op, _ in res.ai.rejected}
    assert rejected == {"Claude", "図9"}           # 年以外へのリンク・存在しない図は不採用
    # 章見出しのスタイルの提案（style_fixes）は、記録するだけで XML には反映しない（所有者の決定 5。W8 の手順 5・10）
    assert [(f.src, f.role, f.style, f.how) for f in res.ai.style_fixes] == [
        ("d46", "sec1", "章見出し", "Word で段落のスタイルを「章見出し」にする")]
    assert res.ai.boundaries == []
    # 画像の数式の書き起こしは、回答の形にない（docx の画像を AI に渡さない。修正計画 W1・W8）
    assert root.find(".//disp-formula/alternatives") is None and not res.fidelity.ai_additions
    names = [n for n in root.iter("name") if n.get("name-style") == "eastern"]
    assert [x.text for x in names[2]] == ["研究", "次郎"]
    assert res.unresolved_after == []
    report = res.report_path.read_text(encoding="utf-8")
    assert "## 2. AI による仕上げ" in report and "| 状態 | 済み |" in report and "久保は" in report


def test_manual_mode_without_response_writes_prompt(journal, meta, tmp_path):
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, ai_mode="manual"))
    prompt = res.prompt_path.read_text(encoding="utf-8")
    assert "[d18]" in prompt and "… links" in prompt
    # docx の画像は AI に渡さない（修正計画 W1）: 添付画像のフォルダを作らない。添付を勧めるのは出版版 PDF だけ（【作業する方へ】。W8 の 4.1）
    assert not (tmp_path / "AI添付画像").exists() and "AI添付画像" not in prompt
    assert prompt.startswith(ai_assist.HUMAN_HEADING) and "画像を添付" not in prompt
    assert res.fidelity.ok
    # チャットの AI が JSON を崩さないよう、回答の形（コードブロック 1 つ・半角の引用符）と見本を示す
    assert "## 回答の形" in prompt and "```json" in prompt and ai_assist.ANSWER_FIRST_MANUAL in prompt
    assert example_block()["links"]


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
    assert (len(data["links"]), len(data["names"]), len(data["style_fixes"])) == (6, 1, 1)
    for fence in ("```json", "```JSON"):
        data = parse_response(fence + "\n" + RESPONSE + "\n```\n補足: {placements} は空です。")
        assert len(data["links"]) == 6


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
    # 章見出しへの指定は提案（style_fixes）にする（決定 5）
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
    """回答のスキーマは、どの object もすべての項目を必須にし、ほかの項目を許さない（ChatGPT の strict な構造化出力）。"""
    def objects(sch):
        if isinstance(sch, dict):
            if sch.get("type") == "object":
                yield sch
            for v in sch.values():
                yield from objects(v)
    found = list(objects(ai_assist.RESPONSE_SCHEMA))
    assert len(found) == 8                         # 回答・pdf・6 つの一覧の要素
    for o in found:
        assert o["additionalProperties"] is False and o["required"] == list(o["properties"])
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
    # system（instructions）に指示の部分、利用者の内容にデータの部分（修正計画 W8 の手順 13）
    assert kw["instructions"].startswith(ai_assist.REQUEST_TITLE) and ai_assist.ANSWER_FIRST_API in kw["instructions"]
    assert ai_assist.DATA_HEADING not in kw["instructions"].splitlines() and content[-1]["text"].startswith(ai_assist.DATA_HEADING)
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
    out = ai_assist.call_provider("openai", "指示", "x", None, model="gpt-test", api_key="t")
    assert "OPENAI_API_KEY" in out.error
    _fake_openai(monkeypatch, [], content_type="refusal")
    assert "断りました" in ai_assist.call_provider("openai", "指示", "x", None, model="gpt-test", api_key="t").error
    _fake_openai(monkeypatch, [], status="incomplete")
    assert "途中で切れました" in ai_assist.call_provider("openai", "指示", "x", None, model="gpt-test", api_key="t").error
    # API キーが見つからない（クライアントを作れない）ときも、止まらずにエラーとして記録する
    def no_key(*a, **k):
        raise openai.OpenAIError("The api_key client option must be set")
    monkeypatch.setattr(openai, "OpenAI", no_key)
    assert "OPENAI_API_KEY を確認" in ai_assist.call_provider("openai", "指示", "x", None, model="gpt-test").error


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
    out = ai_assist.call_provider("gemini", "指示", "x", None, model="gemini-test", api_key="t")
    assert "GEMINI_API_KEY" in out.error
    not_found = errors.ClientError(404, {"error": {"code": 404, "message": "not found", "status": "NOT_FOUND"}})
    _fake_gemini(monkeypatch, [], error=not_found)
    assert "gemini-test が見つかりません" in ai_assist.call_provider("gemini", "指示", "x", None, model="gemini-test").error
    _fake_gemini(monkeypatch, [], finish="MAX_TOKENS")
    assert "途中で切れました" in ai_assist.call_provider("gemini", "指示", "x", None, model="gemini-test").error
    _fake_gemini(monkeypatch, [], finish="SAFETY")
    assert "SAFETY" in ai_assist.call_provider("gemini", "指示", "x", None, model="gemini-test").error
    from google import genai

    def no_key(*a, **k):
        raise ValueError("Missing key inputs argument!")
    monkeypatch.setattr(genai, "Client", no_key)
    assert "GEMINI_API_KEY または GOOGLE_API_KEY を確認" in ai_assist.call_provider("gemini", "指示", "x", None, model="g").error


def test_other_providers_require_a_model_name(journal, meta, tmp_path):
    # ChatGPT・Gemini ではモデル名を利用者が指定する（Claude のモデル名・「自動」・空欄は受け付けない）
    for model in ("", "auto", DEFAULT_MODEL):
        out = ai_assist.call_provider("openai", "指示", "x", None, model=model)
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
    # system に指示の部分（「## 回答の形」に見本がある。見本を足さない）、利用者の内容にデータの部分（修正計画 W8 の手順 13）
    assert system["content"].startswith(ai_assist.REQUEST_TITLE) and system["content"].count("```json") == 1
    assert ai_assist.ANSWER_FIRST_API in system["content"] and ai_assist.HUMAN_HEADING not in system["content"]
    assert user["content"][-1]["text"].startswith(ai_assist.DATA_HEADING)
    assert not any(isinstance(c, dict) and c.get("type") == "image_url" for c in user["content"])   # docx の画像は渡さない
    assert not res.ai.error and res.ai.provider == "sakana"
    assert len(res.ai.accepted) == 5 and res.fidelity.ok and res.fidelity.final_ok   # set_role の sec1 は提案（決定 5）
    report = res.report_path.read_text(encoding="utf-8")
    assert "API（Sakana AI: sakana-namazu）" in report and "入力 90 トークン" in report


def test_sakana_retries_without_schema_and_never_sends_openai_key(monkeypatch):
    # JSON スキーマの指定を断られたら、指定なしで 1 回だけやり直す（依頼文に回答の形式があるので JSON で返る）
    calls = []
    _fake_sakana(monkeypatch, calls, reject_schema=True)
    out = ai_assist.call_provider("sakana", "指示", "x", None, model="fugu", api_key="sk-sakana")
    creates = [c for c in calls if "messages" in c]
    assert len(creates) == 2 and "response_format" not in creates[1]
    assert not out.error and parse_response(out.raw)["links"] and "指定なしでやり直した" in out.model_note
    _fake_sakana(monkeypatch, [], finish="length")
    assert "途中で切れました" in ai_assist.call_provider("sakana", "指示", "x", None, model="fugu", api_key="k").error
    # Sakana のキーがないときに、環境変数の OpenAI のキーを Sakana に送らない
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-should-not-be-sent")
    calls = []
    _fake_sakana(monkeypatch, calls)
    out = ai_assist.call_provider("sakana", "指示", "x", None, model="fugu")
    assert "SAKANA_API_KEY" in out.error and calls == []


# ---------------------------------------------------------------------------- 回答の順と、途中で切れた回答
CUT_LINKS = [answers.link("文献", "d18", "2001", 1, "B2", "第1章の段落の引用と判断した例")] * 2


def head_first(indent=1):
    """sample_float の模擬回答を、依頼文の回答の形の順（placements が一覧の最初）で書いたもの（links を長くして、切る位置を作る）。"""
    d = dict(FLOAT_RESPONSE, links=CUT_LINKS, notes=["気づき"])
    return json.dumps({k: d[k] for k in ai_assist.RESPONSE_SCHEMA["required"]}, ensure_ascii=False, indent=indent)


def cut_cases():
    """途中で切れた回答。(a)〜(d) は最後まで書かれた placements の要素を読む。(e)(f) は読まない。"""
    full = head_first()
    ops = full.index('"links"')
    in_ops = full[:full.index('"reason"', ops) + 15]                     # links の文字列の途中
    ops_first = json.dumps(dict({"links": CUT_LINKS}, **FLOAT_RESPONSE), ensure_ascii=False)   # links が先頭の回答
    return {
        "a": in_ops,
        "b": full[:ops + len('"links":')],                               # "links": の直後
        "c": full[:full.index('"float": "s2"') + 30],                    # 2 つ目の placements の要素の途中
        "d": "```json\n" + in_ops,                                       # 閉じのないコードブロック
        "e": ops_first[:ops_first.index('"placements"') - 20],           # links が先頭で、placements の前で切れた
        "f": full.replace('"after": "d17"', '"after": “d17”')[:len(in_ops)],   # 途中に飾りの引用符（書き損じ）
    }


def test_response_format_puts_placements_first():
    """依頼文の見本・項目の説明・回答の書き方と、API の構造化出力のスキーマで、placements を回答の最初に書かせる。"""
    schema = ai_assist.RESPONSE_SCHEMA
    assert list(schema["properties"]) == schema["required"] == list(example_block()) == [
        "request_id", "pdf", "placements", "boxes", "boundaries", "links", "names", "style_fixes", "notes"]
    assert "回答の最初の一覧として書く" in schema["properties"]["placements"]["description"]
    ins = ai_assist.request_instructions(ALL_SECTIONS)
    assert "項目はこの順に書きます（placements を先に書くのは、回答が途中で切れても図・表の位置が残るようにするためです）" in ins
    # 読み取りはキーの順によらない（0.21.0 の順の回答も読める）
    assert parse_response(json.dumps(FLOAT_RESPONSE))["placements"] == parse_response(head_first())["placements"]


@pytest.mark.parametrize("name, floats", [("a", ["s1", "s2", "s3", "s4"]), ("b", ["s1", "s2", "s3", "s4"]),
                                          ("c", ["s1"]), ("d", ["s1", "s2", "s3", "s4"])])
def test_cut_response_keeps_finished_placements(name, floats):
    """途中で切れた回答から、最後まで書かれた placements の要素だけを読む（途中で切れた要素と links・notes などは使わない）。
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
    assert data["links"] == [] and data["notes"] == [] and data["style_fixes"] == []


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
    ops = full.index('"reason"', full.index('"links"'))
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
    body = json.dumps({"placements": FLOAT_RESPONSE["placements"], "links": [], "notes": ["```の記号の説明"]},
                      ensure_ascii=False, indent=1)
    for text in (body, "```json\n" + body + "\n```", "以下が回答です。\n" + body, "以下が回答です：```json\n" + body + "\n```",
                 "```text\n補足\n```\n```json\n" + body + "\n```"):
        data = parse_response(text)
        assert data["placements"] == FLOAT_RESPONSE["placements"] and data["notes"] == ["```の記号の説明"]
    # { で始まる回答（コードブロックの中身だけをコピーしたもの）は、文字列の中に「```{」があってもコードブロックを探さない
    body = json.dumps({"placements": FLOAT_RESPONSE["placements"], "links": [], "notes": ["```{ で始まる記号"]},
                      ensure_ascii=False)
    assert parse_response(body)["notes"] == ["```{ で始まる記号"]


def _cut_text():
    return cut_cases()["c"]


def test_api_cut_answers_are_kept(monkeypatch):
    """API の回答が上限で切れたとき、4 社とも、切れたところまでの回答（raw）を残し、切れたこと（cut）を返す。"""
    text = _cut_text()
    calls = []
    _fake_anthropic(monkeypatch, calls, text=text, stop="max_tokens")
    out = ai_assist.call_provider("claude", "指示", "x", None, api_key="t")
    assert (out.raw, out.cut) == (text, True) and "途中で切れました" in out.error and out.usage["output_tokens"] == 50
    _fake_openai(monkeypatch, [], status="incomplete", text=text)
    out = ai_assist.call_provider("openai", "指示", "x", None, model="gpt-test", api_key="t")
    assert (out.raw, out.cut) == (text, True) and "途中で切れました" in out.error
    _fake_gemini(monkeypatch, [], finish="MAX_TOKENS", text=text)
    out = ai_assist.call_provider("gemini", "指示", "x", None, model="gemini-test")
    assert (out.raw, out.cut) == (text, True) and "途中で切れました" in out.error
    _fake_sakana(monkeypatch, [], finish="length", text=text)
    out = ai_assist.call_provider("sakana", "指示", "x", None, model="fugu", api_key="k")
    assert (out.raw, out.cut) == (text, True) and "途中で切れました" in out.error
    # 切れていない回答は cut にならない
    _fake_anthropic(monkeypatch, [], text=RESPONSE)
    out = ai_assist.call_provider("claude", "指示", "x", None, api_key="t")
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
    out = ai_assist.call_api("指示", "x", None, model="claude-test")
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
    out = ai_assist.call_api("指示", "x", None, model="claude-test", api_key="sk-test")
    assert out.error == "AI の呼び出しに失敗しました: stream() got an unexpected keyword argument 'fallbacks'"
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = ai_assist.call_api("指示", "x", None, model="claude-test")       # API キーがどこにもなければ、API キーの知らせ
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
    # 英文の題目への区切りの指定は、どれも採用しない（暫定の判断。0.23.1 は英文題目を exclude・abstract にすると、英文副題が
    # XML から落ちていた）。スタイルの提案は記録だけ。英文題目・副題はそのまま
    path = tmp_path / "title.docx"
    mf.make_article(path, "英文題目の検証用文書", _body)
    _, plan, _ = _mechanical(path, journal)
    title = plan.title_en[0].src
    res = _manual(path, answers.answer(boundaries=[(title, "資料の見出し"), (title, "英文要旨の続き")],
                                      style_fixes=[(title, "exclude")]), meta, journal, tmp_path / "out")
    assert [why for _, why in res.ai.rejected] == ["英文の題目・副題の段落の役割は変えられない（変えると英文の題目・副題が XML から落ちる）"] * 2
    assert [f.src for f in res.ai.style_fixes] == [title]
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
    # 資料の途中の段落（資料の見出しでない段落）を英文要旨にする提案（style_fixes）は、XML には反映しない
    # （英文要旨の続きを指定できるのは、今、資料の見出しになっている段落だけ。所有者の決定 5。W8 の手順 5・10）
    path = tmp_path / "middle.docx"
    mf.make_article(path, "英文要旨に戻す検証用文書", _body,
                    appendix=[mf.para(S["abs"], "資料1\u3000架空の授業プリント"), mf.para(S["abs"], "架空のプリントの本文。"),
                              mf.para(S["abs"], "The rest of the abstract."), mf.para(S["abs"], "And one more sentence."),
                              mf.para(S["abs"], "資料2\u3000架空の調査票"), mf.para(S["abs"], "架空の調査票の本文。")])
    _, plan, _ = _mechanical(path, journal)
    src = next(s for s, p in plan.paras.items() if p.plain() == "The rest of the abstract.")
    assert plan.region[src] == "app"
    res = _manual(path, answers.answer(style_fixes=[(src, "abstract")]), meta, journal, tmp_path / "out2")
    assert res.ai.rejected == [] and res.fidelity.ok and res.dtd_valid
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
    from jasme_jats.report import actions
    act = next(x for x in actions(res) if x.key == "ai_boundary")
    assert "前の資料の続きにしました" in act.box_detail and "見出しのない資料" not in act.box_detail


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
    # 要確認 ai_boundary の行で、見出しのない資料になったことを知らせる（点検 review13 原則 3）
    from jasme_jats.report import APP_NO_TITLE_LINE, actions
    act = next(x for x in actions(res) if x.key == "ai_boundary")
    assert APP_NO_TITLE_LINE.format(head="「資料1\u3000架空の授業プリント」") in act.box_detail and "前の資料の続き" not in act.box_detail


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
    # 資料の見出しでない段落を本文にする提案（style_fixes）は、XML には反映しない（所有者の決定 5。W8 の手順 5・10）
    assert res.ai.rejected == [] and [f.src for f in res.ai.style_fixes] == [third]
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    assert [(b.src, b.kind) for b in res.ai.boundaries] == [(head, "英文要旨の続き")]
    root = load(res)
    assert _abstract(root) == ["Small article abstract.", "Appendix 1: The fictional second abstract paragraph",
                               "The fictional third abstract paragraph."]
    assert _apps(root) == [("資料2\u3000架空の授業プリント", ["架空のプリントの本文。"])]
    res = _manual(path, answers.answer(boundaries=[(head, "英文要旨の続き"), (head2, "資料の本文")], style_fixes=[(third, "p")]),
                  meta, journal, tmp_path / "out2")
    assert res.ai.rejected == [] and [f.src for f in res.ai.style_fixes] == [third] and res.fidelity.ok and res.dtd_valid
    assert [(b.src, b.kind) for b in res.ai.boundaries] == [(head, "英文要旨の続き"), (head2, "資料の本文")]
    root = load(res)
    assert _abstract(root) == ["Small article abstract.", "Appendix 1: The fictional second abstract paragraph",
                               "The fictional third abstract paragraph."]
    assert _apps(root) == [("", ["資料2\u3000架空の授業プリント", "架空のプリントの本文。"])]
    assert [d.message for op, d in res.ai.accepted if op["src"] == head2] == ["段落を「資料の本文」（本文段落）とした。試験"]
    # 英文要旨の段落への abstract（指定しても変わらない）の後ろでも、最初の資料の見出し（見出しのスタイルの段落）への p は、見出しの
    # ない資料の最初の段落になる（見出しと資料の段落を英文要旨に入れない）
    path = tmp_path / "style.docx"
    mf.make_article(path, "英文要旨に戻す検証用文書", _body,
                    appendix=[mf.para(S["sec1"], "授業の記録"), mf.para(S["body"], "架空の記録の本文。")])
    _, plan, _ = _mechanical(path, journal)
    by_text = {p.plain(): s for s, p in plan.paras.items()}
    res = _manual(path, answers.answer(boundaries=[(by_text["授業の記録"], "資料の本文")],
                                      style_fixes=[(by_text["Small article abstract."], "abstract")]), meta, journal, tmp_path / "out3")
    # 英文要旨の段落を英文要旨にする提案は、記録だけ（英文要旨の続きは、資料の見出しの段落にだけ指定できる）
    assert res.ai.rejected == [] and [f.role for f in res.ai.style_fixes] == ["abstract"]
    assert res.fidelity.ok and res.dtd_valid
    root = load(res)
    assert _abstract(root) == ["Small article abstract."]
    assert _apps(root) == [("", ["授業の記録", "架空の記録の本文。"])]


def test_sentence_decision_is_not_recorded_for_ai_roles(journal, meta, tmp_path):
    # 見出しの形に合うが文とみなした段落の判断（「…資料の見出しにしなかった」。applied=False）は、AI が役割を指定した段落には
    # 記録しない（AI が決めたことなので、4 章と依頼文で、資料の見出しにできるという案内を繰り返さない）。資料の見出しでない段落を
    # 英文要旨・本文にする提案（style_fixes）は XML に反映しない（所有者の決定 5）ので、その判断は残る
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
    assert res.ai.rejected == [] and len(res.ai.style_fixes) == 2 and res.fidelity.ok and res.dtd_valid
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
    from jasme_jats.ai_assist import (ABSTRACT_FIRST_WHY, BOUNDARY_KINDS, STYLE_ONLY_WHY, boundary_kind, boundary_problem,
                                      role_style)
    assert BOUNDARY_KINDS == {"注の始まり": "fn_start", "注の続き": "p", "資料の見出し": "app_heading",
                              "英文要旨の続き": "abstract", "資料の本文": "p"}
    _, plan, _ = _mechanical(STRUCTURE, journal)
    by_text = {p.plain(): p for p in plan.paras.values()}
    body = by_text["囲みの後の本文も，本文のまま続く。"]
    abstract = by_text["Structure abstract."]
    app_title = by_text["資料（授業プリント）"]
    app_para = by_text["問1\u3000架空の問題文である。"]
    endnote = next(fn.paras[0] for fn in plan.fns if fn.word_id == "endnote:5")
    # 区切りの直し（英文要旨の最初の段落を資料の見出しにすると英文要旨が空になるので、それだけは断る）
    assert plan.abstract[0] is abstract and boundary_kind(abstract, plan, "app_heading") == "資料の見出し"
    assert boundary_problem(abstract, plan, "app_heading") == ABSTRACT_FIRST_WHY
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
    """スタイルの提案（style_fixes。章見出し・引用・除外・図キャプション・資料の見出しでない段落への英文要旨）は、XML を 1 バイトも
    変えず、AIOutcome.style_fixes にスタイル名つきで入る（所有者の決定 5。W8 の手順 5・10）。AI の除外で本文が落ちない（C042）。"""
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
    assert res.ai.rejected == [] and res.ai.accepted == [] and res.ai.boundaries == []
    [fix] = res.ai.style_fixes
    assert (fix.src, fix.role, fix.verdict, fix.reason, fix.confidence) == (
        src, "" if role == "exclude" else role, "直す", "試験", "高")
    assert fix.style == ai_assist.role_style(journal, role) and (fix.style or role == "exclude")
    assert not any(e.reason.startswith("AI") for e in res.plan.exclusions)
    assert "### スタイルの提案（XML には反映していない）" in res.report_path.read_text(encoding="utf-8")       # 2 章


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
    # 依頼文の「# 出力から除いた段落（確かめるだけ）」は、除いた理由と文字だけを書き、操作の案内を添えない（0.23.1 は、冒頭・
    # 著者表・Word の注の段落にも「本文の一部なら set_role を提案」と書き、必ず捨てられる set_role を勧めていた〈N6〉。W8 の手順 15 で
    # 案内〈set_role_hint〉をなくした。直すのは style_fixes の提案で、指示の部分に書く）
    from jasme_jats.ai_assist import BOUNDARY_KINDS, EXCLUDED_HEADING, build_request

    def hints(path):
        _, plan, linker = _mechanical(path, journal)
        req = build_request(plan, linker).data
        sec = req.split(EXCLUDED_HEADING + "\n", 1)[1].split("\n\n", 1)[0] if EXCLUDED_HEADING in req else ""
        return {ln.split("]")[0][3:]: ln for ln in sec.splitlines() if ln.startswith("- [")}, plan
    lines, plan = hints(STRUCTURE)
    _, plan2, linker = _mechanical(STRUCTURE, journal)
    request = build_request(plan2, linker)
    req = request.data
    # 文末脚注の参照は「⟦文末脚注⟧」、「## 注」の Word の注は、行頭の注の ID に「（Word の文末脚注 5）」を添え、段落の行を続ける
    # （修正計画 W8 の 4.1。続きの段落は字下げ）
    assert "脚注を付けた文⟦脚注⟧と文末脚注を付けた文⟦文末脚注⟧。" in req
    notes = req.split("\n## 注（", 1)[1].split("\n\n", 1)[0].splitlines()[1:]
    first = {fn.word_id: fn.paras[0].src for fn in plan2.fns if fn.word_note}
    assert notes[0].startswith(f"[fn1]（Word の脚注 5）[{first['footnote:5']}]")
    assert notes[1].startswith(f"[fn2]（Word の文末脚注 5）[{first['endnote:5']}]")
    assert notes[2].startswith("      [") and all(ln.lstrip().startswith("[") for ln in notes)
    journal_line = next(e for e in plan.exclusions if e.reason.startswith("冒頭部のテンプレート装飾"))
    assert lines[journal_line.src] == f"- [{journal_line.src}] {journal_line.reason}:「{journal_line.text.strip()[:60]}" + (
        "…」" if len(journal_line.text.strip()) > 60 else "」")
    # 手順 15 の節（未解決の一覧・除外）に、操作の名前を書かない（図形の節は手順 16 で作り直す）
    mine = "\n".join(req.split(h, 1)[1].split("\n\n", 1)[0] for h in ("# 機械がリンクできなかった箇所", EXCLUDED_HEADING))
    assert all(w not in mine for w in ("set_role", "placements", "split_name", "link_", "推定: "))
    unref = next(s for s, k in plan.note_of.items() if k == "footnote:9")
    assert unref in lines                                   # どの役割にもできない段落も、除いたことは載せる
    lines, plan = hints(FULL)
    dup = next(e.src for e in plan.exclusions if e.reason.startswith("重複する所属"))
    assert dup in lines                                     # 著者表の中の段落
    # 囲みか図の注記か決められなかったテキストボックス（浮動配置でない VML）の段落は、テキストボックスの節に載せ、除外の一覧には
    # 載せない（二重に載せない）
    vml = ('<w:r><w:pict><v:shape style="width:200pt;height:40pt"><v:textbox><w:txbxContent>'
           + mf.para(S["body"], "囲みの中の架空の問題文。") + "</w:txbxContent></v:textbox></v:shape></w:pict></w:r>")
    path = tmp_path / "vml.docx"
    mf.make_article(path, "依頼文の案内の検証用文書", lambda b: [mf.para(S["sec1"], "１．はじめに"),
                                                               mf.para(S["body"], "囲みを付けた本文。", vml)])
    lines, plan = hints(path)
    box = next(s for s, p in plan.paras.items() if p.plain() == "囲みの中の架空の問題文。")
    assert box in {e.src for e in plan.exclusions} and box not in lines
    _, plan3, linker3 = _mechanical(path, journal)
    assert f"[{box}]" in build_request(plan3, linker3).data.split("# 囲みか図の注記か決められなかった", 1)[1]
    # 回答で直すのは注の区切りと資料の始まりだけで、ほかの役割はスタイルの提案（所有者の決定 5。W8 の手順 5・13）。依頼文の区切りの
    # 語は BOUNDARY_KINDS と同じ
    ins = request.instructions
    assert "Word のスタイルでは直しにくい" in ins and "スタイルの付け間違いは、あなたの回答では直りません" in ins
    bound = next((s for s in request.sections if s.key == "boundaries"), None)
    kinds = (("注の始まり", "注の続き") if bound and "notes" in bound.parts else ()) + (
        ("資料の見出し", "英文要旨の続き", "資料の本文") if bound and "apps" in bound.parts else ())
    assert all(f'"{k}"' in ins for k in kinds) and set(kinds) <= set(BOUNDARY_KINDS)
    assert "app_heading" not in ins and "set_role" not in ins


# ----------------------------------------------------------------------------- 文字だけのテキストボックス（修正計画の D1）
def _boxes_by_text(journal):
    """sample_structure の、1 回目の組み立ての plan と、文字だけのテキストボックスの最初の段落の文字 -> ID。"""
    _, plan, _ = _mechanical(STRUCTURE, journal)
    return plan, {next((q.plain() for q in bi.paras if not q.is_blank), ""): x for x, bi in plan.textboxes.items()}


def _src(plan, head):
    return next(s for s, p in plan.paras.items() if p.plain().startswith(head))


def _hint_and_note(plan, hint, note):
    """囲みのテキストボックス hint を「囲みの後の段落」の後ろの囲みに、note を図の注記にする回答。"""
    return answers.answer(boxes=[(hint, "囲み", _src(plan, "囲みの後の段落である。")), (note, "図の注記", "")])


def _manual_boxes(path, boxes, meta, journal, out):
    """boxes を手で書いた回答（項目の書き方そのものを試す）を手動モードで貼り戻して変換する。"""
    resp = json.dumps(dict(answers.empty(), boxes=list(boxes)), ensure_ascii=False)
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
    assert reasons["注"] == "テキストボックス内の文字（AI による仕上げで図に重ねた注記と判断し、本文から除外）"
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
    assert not none.plan.asked_floats and fin.box_title == "AI にテキストボックスの種類を判断させる"
    assert "AI が種類を判断します" in fin.box_detail


def test_ai_kind_box_restores_mechanical_label(journal, meta, tmp_path):
    # 図に重ねた注記と機械的に判断したテキストボックスも、本文の文字（問題文など）なら、AI が placements の kind box で本文の
    # 囲みに戻せる（F の確かめで足した暫定の判断。それまでは「扱いを機械的に決めたので変更できない」で採用せず、図の近くの
    # 短い問題文が XML から消えたまま AI でも戻せなかった）。依頼文では、変更不可の節ではなく、戻せる節に中身と一緒に載せる
    from jasme_jats.ai_assist import build_request
    plan, ids = _boxes_by_text(journal)
    label, a_src, after = ids["A 点"], _src(plan, "A 点"), _src(plan, "図1の点に名前を付けた。")
    assert plan.textboxes[label].kind == "label"
    _, plan1, linker = _mechanical(STRUCTURE, journal)
    req = build_request(plan1, linker).data
    # 図の注記とみなしたテキストボックスの段落は、その節に載せ、「# 出力から除いた段落」には載せない（二重に載せない。W8 の手順 15）
    assert f"[{a_src}]A 点" in req.split("# 図の注記とみなして除いたテキストボックス", 1)[1]
    assert f"- [{a_src}]" not in req.split("# 出力から除いた段落", 1)[-1].split("\n\n", 1)[0]
    res = _manual(STRUCTURE, answers.answer(boxes=[(label, "囲み", after)]), meta, journal, tmp_path)
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and res.jstage_issues == []
    bt = next(bt for bt in load(res).iter("boxed-text") if _text(bt) == "A 点")
    assert _text(bt.getprevious()) == "図1の点に名前を付けた。" and bt.getparent().tag == "sec"
    [(op, d)] = [(op, d) for op, d in res.ai.accepted if op["op"] == "place_float"]
    assert op["src"] == label and d is res.plan.float_decisions[label] and d.category == "box"
    assert "を囲み（boxed-text）として段落「図1の点に名前を付けた。」の後に置いた（機械的には図に重ねた注記と判断していた）。" in d.message
    assert "A 点" not in {t for _, _, t in res.fidelity.excluded}
    assert [why for _, why in res.ai.rejected] == [ai_assist.NO_BOX_WHY] * len(plan.undecided_boxes)   # 聞いたのに答えのないもの
    assert not any("図に重ねた注記と判断したテキストボックス" in w for w in res.warnings)
    info = res.plan.textboxes[label]
    assert (info.kind, info.mode, info.where, info.estimated) == ("box", "ai", "ai", False)
    # 1 章の「テキストボックスの文字」の行は、AI の判断（2 章）と機械的な判断（4 章）の両方があるときに両方の章を示す
    assert "| テキストボックスの文字（2 章・3 章・4 章・6 章） |" in res.report_path.read_text(encoding="utf-8").split("## 2.")[0]
    # kind label（注記のまま）は採用しない。注記のまま除外し、10 章の警告に、本文の文字なら囲みに指定できることを書く
    res = _manual(STRUCTURE, answers.answer(boxes=[(label, "図の注記", "")]), meta, journal, tmp_path / "label")
    assert [why for op, why in res.ai.rejected if op["src"] == label] == [
        f"テキストボックス {label} は図の注記とみなして除いたので、指定できるのは「囲み」（本文の囲みに戻す）だけ（図の注記のままなら書かない）"]
    assert {t: w for _, w, t in res.fidelity.excluded}["A 点"] == "テキストボックス内の文字（図に重ねた注記とみなして本文から除外）"
    [warn] = [w for w in res.warnings if "図に重ねた注記と判断したテキストボックス" in w]
    assert warn.endswith("（6 章）。図の注記でなく本文の文字（問題文など）なら、Word で文字を"
                         "テキストボックスの外に出して変換し直してください")


@pytest.mark.parametrize("make, why", [
    (lambda p, ids: answers.box(ids["（ヒント）"], "囲み", _src(p, "問1　架空の三角形")), "本文の段落ではない"),     # 囲みの中の段落
    # 浮動配置でない（行内の）囲みの中の段落（textbox_id だけで plan.body_seq から除く。修正計画の F の (4)）
    (lambda p, ids: answers.box(ids["（ヒント）"], "囲み", _src(p, "問2　架空の問い")), "本文の段落ではない"),
    (lambda p, ids: answers.box(ids["（ヒント）"], "囲み", _src(p, "試験七郎（2025）")), "本文の段落ではない"),   # 引用文献の段落
    (lambda p, ids: answers.box(ids["（ヒント）"], "囲み", _src(p, "試験　七郎")), "本文の段落ではない"),        # 著者表のセル
    (lambda p, ids: answers.box(ids["問1　架空の三角形の面積を求めよ。底辺と高さは図に示す。"], "囲み", _src(p, "囲みの後の段落")),
     "は囲み（boxed-text）として扱いと位置を機械的に決めたので、変更できない"),
    (lambda p, ids: answers.box(ids["問2　架空の問いを二つの式で考えよ。"], "図の注記", ""),     # 行内の囲み
     "は囲み（boxed-text）として扱いと位置を機械的に決めたので、変更できない"),
    (lambda p, ids: answers.box(ids[""], "囲み", _src(p, "囲みの後の段落")), "は扱いを機械的に決めたので、変更できない"),   # 空白だけ
    # 図の注記とみなしたもの: 本文の囲みに戻す「囲み」だけを受け付ける（注記のままなら書かない）
    (lambda p, ids: answers.box(ids["A 点"], "図の注記", ""), "指定できるのは「囲み」（本文の囲みに戻す）だけ（図の注記のままなら書かない）"),
    (lambda p, ids: answers.box(ids["A 点"], "囲み", _src(p, "問1　架空の三角形")), "本文の段落ではない"),
    (lambda p, ids: answers.box(ids["問3　架空の数の列の規則を説明せよ。"], "図の注記", ""), "「囲み」だけを指定できる"),
    (lambda p, ids: dict(answers.box(ids["（ヒント）"], "囲み", _src(p, "囲みの後の段落")), kind="box"), "「囲み」か「図の注記」でない"),
    (lambda p, ids: dict(answers.box(ids["（ヒント）"], "囲み", _src(p, "囲みの後の段落")), kind="fig"), "「囲み」か「図の注記」でない"),
    (lambda p, ids: answers.box("x99", "囲み", _src(p, "囲みの後の段落")), "にない"),
    (lambda p, ids: answers.box("s1", "囲み", _src(p, "囲みの後の段落")), "にない"),
    # after_head が段落の先頭の文字と合わない（段落の ID の書き違いの疑い）
    (lambda p, ids: answers.box(ids["（ヒント）"], "囲み", _src(p, "囲みの後の段落"), after_head="違う段落の先頭"), "と合わない"),
])
def test_ai_textbox_placements_are_validated(journal, make, why):
    from jasme_jats.ai_assist import AIOutcome, box_kinds
    plan, ids = _boxes_by_text(journal)
    out = AIOutcome()
    got = box_kinds({"boxes": [make(plan, ids)]}, plan, out)
    assert got == {} and len(out.rejected) == 1 and why in out.rejected[0][1]


def test_ai_textbox_placement_twice_and_estimated_box(journal, meta, tmp_path):
    # 同じテキストボックスの 2 回目の指定は採用しない。位置を推定した囲みは、kind 囲みで位置だけを指定し直せる（要確認は消える）
    from jasme_jats.ai_assist import AIOutcome, box_kinds, float_placements
    plan, ids = _boxes_by_text(journal)
    hint, est = ids["（ヒント）"], ids["問3　架空の数の列の規則を説明せよ。"]
    out = AIOutcome()
    after = _src(plan, "囲みの後の段落")
    got = box_kinds({"boxes": [answers.box(hint, "図の注記", ""),
                               answers.box(hint, "囲み", after, after_head=ai_assist.head_of(plan.paras[after]))]}, plan, out)
    assert got[hint]["kind"] == "label" and got[hint]["after"] == "" and "2 回ある" in out.rejected[0][1]
    assert plan.estimated_boxes == [est]
    res = _manual(STRUCTURE, answers.answer(boxes=[(est, "囲み", _src(plan, "空の囲みを置いた。"))]), meta, journal, tmp_path)
    assert res.fidelity.ok and res.dtd_valid and res.plan.estimated_boxes == []
    bt = next(bt for bt in load(res).iter("boxed-text") if _text(bt).startswith("問3"))
    assert _text(bt.getprevious()) == "空の囲みを置いた。"
    assert "textbox_place" not in [a.key for a in actions(res)]
    # 図形（位置を決められなかった図表）の位置は placements に書き、テキストボックスの ID を placements に書いた指定は採用しない
    _, fplan, _ = _mechanical(FLOAT, journal)
    out = AIOutcome()
    got = float_placements({"placements": [answers.placement("s1", "d13")]}, fplan, out)
    assert list(got) == ["s1"] and got["s1"]["after"] == "d13" and "kind" not in got["s1"] and out.rejected == []
    out = AIOutcome()
    assert float_placements({"placements": [answers.placement(hint, after)]}, plan, out) == {}
    assert [why for _, why in out.rejected] == [f"{hint} はテキストボックスなので、種類と位置は boxes に書く"]


def test_set_role_on_textbox_paragraphs(journal, meta, tmp_path):
    # 浮動配置でないテキストボックス（VML・行内）の段落に set_role で指定できるのは fig_caption・table_caption・exclude だけ
    # （回答の boundaries の役割はどれも当たり、boxes の kind「囲み」「図の注記」を案内して採用しない。修正計画の F の (1)）。
    # スタイルの提案（style_fixes）は、どの段落でも記録するだけで XML には反映しない（所有者の決定 5。W8 の手順 5・10。VML の
    # キャプションは、Word でスタイルを図キャプションにすれば図のキャプションになる）。同じ段落の 2 件目の提案は不採用
    from jasme_jats.ai_assist import set_role_problem
    _, plan, _ = _mechanical(STRUCTURE, journal)
    vml = next(p for p in plan.paras.values() if p.plain().startswith("問3　架空の数の列"))
    floating = next(p for p in plan.paras.values() if p.plain() == "（ヒント）")
    assert vml.textbox_id and not vml.float_id and floating.float_id
    for role in ("p", "quote", "sec2"):
        assert set_role_problem(vml, plan, role) == ("テキストボックスの段落には区切りを指定できない（囲みか図の注記かは boxes の"
                                                     " kind「囲み」「図の注記」で答える）")
    assert set_role_problem(vml, plan, "exclude") == "" and set_role_problem(vml, plan, "fig_caption") == ""
    assert "図・表の位置は placements、テキストボックスの種類は boxes で答える" in set_role_problem(floating, plan, "exclude")
    for why in (set_role_problem(vml, plan, "p"), set_role_problem(floating, plan, "p")):     # 前の形の名前を書かない（点検 review13 原則 4）
        assert "kind box" not in why and "fig_caption" not in why
    # 囲みとして位置を機械的に決めたもの（placements でも変えられない）の段落には、placements を案内せず「機械的に決めたので
    # 変更できない」と返す（0.25.0 の最初の実装は placements を案内し、placements も採用しないので行き止まりになっていた）
    at_anchor = next(p for p in plan.paras.values() if p.plain().startswith("問1　架空の三角形"))
    inline = next(p for p in plan.paras.values() if p.plain().startswith("問2　架空の問い"))
    fixed = "は囲み（boxed-text）として扱いと位置を機械的に決めたので、変更できない"
    for role in ("p", "exclude", "fig_caption"):
        assert set_role_problem(at_anchor, plan, role) == f"テキストボックス {at_anchor.textbox_id} {fixed}"
    assert set_role_problem(inline, plan, "p") == (
        f"テキストボックス {inline.textbox_id} {fixed}（テキストボックスの段落には区切りを指定できない）")
    assert set_role_problem(inline, plan, "exclude") == ""      # 浮動配置でない段落の exclude は今までどおり受け付ける
    res = _manual(STRUCTURE, answers.answer(style_fixes=[(vml.src, "exclude"), (vml.src, "p")]), meta, journal, tmp_path / "s")
    assert [w for op, w in res.ai.rejected if op["src"] == vml.src] == [ai_assist.STYLE_TWICE_WHY]
    assert [(f.role, f.style, f.how) for f in res.ai.style_fixes] == [("", "", ai_assist.EXCLUDE_HOW)]
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
    assert res.ai.accepted == [] and [w for op, w in res.ai.rejected if op["src"] == cap] == [ai_assist.STYLE_TWICE_WHY]
    assert [(f.src, f.role, f.style) for f in res.ai.style_fixes] == [(cap, "fig_caption", "図キャプション")]
    assert res.xml_path.read_bytes() == _manual(path, None, meta, journal, tmp_path / "v0").xml_path.read_bytes()
    assert res.fidelity.ok and res.dtd_valid


def test_textbox_placement_is_used_when_set_role_is_a_proposal(journal, meta, tmp_path):
    # 同じ回答で、決められない（浮動配置でない）テキストボックスの段落を図キャプションにする提案と、そのテキストボックスの種類
    # 「図の注記」を指定したとき: 提案は XML に反映しない（所有者の決定 5。W8 の手順 5・10）ので、テキストボックスは組み直した後も
    # 文字だけのテキストボックスのままで、種類の指定を採用する
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
    assert res.ai.rejected == [] and [f.src for f in res.ai.style_fixes] == [src]
    assert res.plan.undecided_boxes == [] and res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    # 提案がなくても、種類の指定を採用する（今までどおり）
    res = _manual(path, answers.answer(boxes=[(xid, "図の注記", "")]), meta, journal, tmp_path / "label")
    assert [op["op"] for op, _ in res.ai.accepted] == ["place_float"] and res.ai.rejected == []


def test_textbox_placement_after_excluded_paragraph_is_kept(journal, meta, tmp_path):
    # 同じ回答で、本文の段落を除く提案（style_fixes の除外）と、その段落を after にした種類「囲み」も指定したとき: 除外は Word で
    # 消す提案で XML に反映しない（AI の除外で本文を落とさない。所有者の決定 5・C042。W8 の手順 5・10）ので、after は本文の段落の
    # ままで、種類の指定を採用する
    plan, ids = _boxes_by_text(journal)
    hint, after = ids["（ヒント）"], _src(plan, "囲みの後の段落である。")
    res = _manual(STRUCTURE, answers.answer(boxes=[(hint, "囲み", after)], style_fixes=[(after, "exclude")]), meta, journal, tmp_path)
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and res.jstage_issues == []
    assert [why for op, why in res.ai.rejected] == [ai_assist.NO_BOX_WHY] * (len(plan.undecided_boxes) - 1)
    assert [op["op"] for op, _ in res.ai.accepted] == ["place_float"] and [f.src for f in res.ai.style_fixes] == [after]
    assert res.plan.textboxes[hint].kind == "box" and hint not in res.plan.undecided_boxes
    assert "囲みの後の段落である。" not in {t for _, _, t in res.fidelity.excluded}


def test_request_lists_textboxes(journal):
    # 依頼文（修正計画 W8 の手順 16）: 囲みか図の注記か決められなかったもの（中身・仮の位置・大きさ・決められなかった理由）、位置を
    # 推定した囲み（違うときだけ答える）、図の注記とみなしたもの（本文の文章のときだけ答える）の節。位置を機械的に決めた囲みは、
    # 答えない「中身」の節に中身だけを載せる（中の参照にリンクできるように）
    from jasme_jats.ai_assist import build_request
    _, plan, linker = _mechanical(STRUCTURE, journal)
    _, ids = _boxes_by_text(journal)
    req = build_request(plan, linker).data
    undecided = req.split("\n# 囲みか図の注記か決められなかったテキストボックス\n", 1)[1].split("\n\n", 1)[0]
    assert all(f"[{ids[t]}] 中身: " in undecided for t in ("（ヒント）", "注", "Area model"))
    assert "  決められなかった理由: 文字 5 字" in undecided and "画像の近く: いいえ" in undecided
    assert "（結び付いた段落の位置）" in undecided and "判定できなかった" not in undecided
    est = req.split("\n# 位置を推定した囲み（位置が違うときだけ答える）\n", 1)[1].split("\n\n", 1)[0]
    x = ids['問3　架空の数の列の規則を説明せよ。']
    assert est.startswith(f"[{x}] 置いた位置: [") and "ページの上の位置の指定" in est
    assert f"  中身: [{_src(plan, '問3　架空の数の列の規則を説明せよ。')}]問3" in est
    fixed = req.split("\n# 位置が決まっている図・表と囲みの中身（", 1)[1].split("\n\n", 1)[0]
    a, c, b = ids["問1　架空の三角形の面積を求めよ。底辺と高さは図に示す。"], ids["問2　架空の問いを二つの式で考えよ。"], ids["A 点"]
    assert f"[{a}] 囲み（[" in fixed and "」の前）。中身: [" in fixed and f"[{c}] 囲み（" in fixed
    # 図に重ねた注記とみなしたものは、答えない節ではなく、本文の文章なら kind 囲みで戻せる節に載せる（中身の段落も示す）
    assert f"[{b}]" not in fixed
    labels = req.split("\n# 図の注記とみなして除いたテキストボックス（本文の文章のときだけ答える）\n", 1)[1].split("\n\n", 1)[0]
    a_src = _src(plan, "A 点")
    assert labels == (f"[{b}] [{_src(plan, '図1の点に名前を付けた。')}] の図の注記（{plan.textboxes[b].why}）: "
                      f"[{a_src}]A 点")
    # テキストボックスの中の段落は「## 本文」に載せず（after に書けない）、テキストボックスの節に中身として載せる（修正計画 W8 の 4.1。
    # 位置を機械的に決めた囲みの中身も、中の参照にリンクできるように載せる）
    body = req.split("\n## 本文（", 1)[1].split("\n\n", 1)[0]
    hint_src = next(s for s, p in plan.paras.items() if p.plain() == "（ヒント）")
    inline_src = _src(plan, "問2　架空の問い")
    assert f"[{hint_src}]" not in body and f"[{inline_src}]" not in body
    assert f"中身: [{hint_src}]（ヒント）" in undecided and f"中身: [{inline_src}]問2" in fixed
    # テキストボックスのない原稿の依頼文には、これらの節を出さない
    _, fplan, flinker = _mechanical(FULL, journal)
    assert "テキストボックス" not in build_request(fplan, flinker).data


def test_prompts_explain_box_and_label(journal):
    a = ai_assist
    # 回答の形（W8 の手順 10）: テキストボックスの種類は boxes の kind（囲み・図の注記）
    assert a.BOX_SCHEMA["properties"]["kind"]["enum"] == ["囲み", "図の注記"]
    assert "テキストボックスの ID（x1 など）" in a.BOX_SCHEMA["properties"]["box"]["description"]
    assert a.RESPONSE_SCHEMA["properties"]["boxes"]["items"] is a.BOX_SCHEMA
    # 依頼文の指示（W8 の手順 13）: 決められないもの・位置を推定した囲み・図の注記とみなしたものがある原稿では、3 つの答え方を書く
    _, plan, linker = _mechanical(STRUCTURE, journal)
    req = a.build_request(plan, linker)
    box = next(s for s in req.sections if s.key == "boxes")
    assert box.parts == {"undecided", "estimated", "labels"} and box.count == f"{len(plan.undecided_boxes)} 個"
    ins = req.instructions
    assert f"{box.n}. テキストボックスの種類（{box.count}）… boxes" in ins
    assert "「# 囲みか図の注記か決められなかったテキストボックス」に挙げたもの（x1 など）は、1 つ残らず答えます。" in ins
    assert 'kind は、"囲み"（問題文・ヒント・まとめなど' in ins and '"図の注記"（矢印・点・辺の名前など' in ins
    assert "「# 位置を推定した囲み」に挙げたものは、置いた位置が違うときだけ" in ins
    assert "「# 図の注記とみなして除いたテキストボックス」に挙げたものは、図の注記ではなく本文として読まれる文章のときだけ" in ins
    assert "どちらも、変えないなら書きません。" in ins
    # 位置を聞く図形のない原稿では、囲みの after の決め方を、図・表の位置の節を指さずに書く
    if "placements" not in {s.key for s in req.sections}:
        assert a.BOX_AFTER_TEXT in ins and "「1. 図・表の位置」" not in ins
    example = example_block(req.sections)
    assert example["boxes"][0]["kind"] == "＜囲み｜図の注記＞" and "float" not in example["boxes"][0]
    # テキストボックスのない原稿では、節も見本の要素も出さない
    _, fplan, flinker = _mechanical(FULL, journal)
    freq = a.build_request(fplan, flinker)
    assert "boxes" not in {s.key for s in freq.sections} and "テキストボックスの種類" not in freq.instructions
    assert example_block(freq.sections)["boxes"] == []


def test_prompts_ask_only_positions_of_floats(journal):
    """依頼文・スキーマ・見本は、図形には位置（after）だけを聞く（修正計画 W8 の手順 6・13）。中身の組み合わせ（items）の組み方・
    数式の画像の書き起こし（formula_image）・画像の添付の説明はない。"""
    a = ai_assist
    _, plan, linker = _mechanical(FLOAT, journal)
    req = a.build_request(plan, linker, manual=False)
    texts = {"system": req.system_text(), "manual": a.build_request(plan, linker).manual_text(),
             "schema": json.dumps(a.RESPONSE_SCHEMA, ensure_ascii=False)}
    for name, t in texts.items():
        assert "formula_image" not in t and "MathML" not in t and "operations" not in t, name
        assert "組み合わせ（items）" not in t and "位置と組み合わせ" not in t and "画像 ID" not in t, name
        assert "画像を添付" not in t and "画像だけの段落 ID" not in t, name
    assert "答えるのは位置だけです" in texts["system"] and "items" not in texts["system"]
    assert "items" not in a.PLACEMENT_SCHEMA["properties"] and "operations" not in a.RESPONSE_SCHEMA["properties"]
    example = example_block(req.sections)
    assert list(example["placements"][0]) == list(a.PLACEMENT_SCHEMA["properties"])


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
    assert "- [d11]「研究次郎」: 姓と名の間に空白がない" in res.prompt_path.read_text(encoding="utf-8")
    assert 'split("「"' not in inspect.getsource(pipeline.convert)
    # 氏名の前後の空白（全角も）は AI の split_name の検証と同じく除き、間に空白のある氏名は載せない
    path = names_article(tmp_path / "names.docx", ["研究次郎", "架空四郎\u3000", "\u3000架空五郎", "試験\u3000太郎", "試験 三郎"],
                         ["Jiro KENKYU", "Shiro KAKU", "Goro KAKU", "Taro SHIKEN", "Saburo SHIKEN"])
    _, plan, _ = _mechanical(path, journal)
    info = build(plan, meta, journal, None)[1]
    assert [(text, lang) for _, text, lang in info.unsplit_names] == [("研究次郎", "ja"), ("架空四郎", "ja"), ("架空五郎", "ja")]


def test_build_request_lists_unsplit_names_with_language(journal):
    """build_request は (段落の ID, 氏名, 言語) の組を受け取り、「# 姓と名の区切りを確かめる氏名」には和文の氏名だけを載せる
    （AI の回答の names は和文の氏名にしか使えない。修正計画 W8 の 4.1・C043。W8 の手順 15 までは、決定事項 17 で英文の氏名も
    載せ、split_name を提案しないことを添えていた。英文 1 語の氏名は、今までどおり 10 章の警告で知らせる）。"""
    from jasme_jats.ai_assist import NAMES_HEADING, build_request
    _, plan, linker = _mechanical(FULL, journal)
    req = build_request(plan, linker, _info(unsplit_names=[("d11", "研究次郎", "ja"), ("d12", "KENKYU", "en")])).data
    sec = req.split(NAMES_HEADING + "\n", 1)[1].split("\n\n", 1)[0].splitlines()
    assert sec == ["- [d11]「研究次郎」: 姓と名の間に空白がない"]
    req = build_request(plan, linker, _info(unsplit_names=[("d12", "KENKYU", "en")])).data
    assert NAMES_HEADING not in req


def test_build_request_shows_newline_in_unsplit_name(journal):
    """氏名の中の改行（著者名の後ろの Shift+Enter など）は、依頼文では「⏎」で示し、1 件を 1 行に書く（氏名の文字は変えない。
    BuildInfo.unsplit_names には改行の文字のまま入る）。"""
    from jasme_jats.ai_assist import build_request
    _, plan, linker = _mechanical(FULL, journal)
    req = build_request(plan, linker, _info(unsplit_names=[("d11", "研究次郎\n", "ja")])).data
    [line] = [ln for ln in req.splitlines() if "姓と名の間に空白がない" in ln]
    assert line == "- [d11]「研究次郎⏎」: 姓と名の間に空白がない"


def test_english_one_word_name_is_listed_and_warned(journal, meta, tmp_path):
    """英文 1 語の著者名は、全体を姓として出力し、4 章の記録（今までどおり）・10 章の警告（決定事項 17 の後半）に出す。AI 依頼文には
    載せない（AI の names は和文の氏名だけ。C043。W8 の手順 15 までは決定事項 17 で載せていた）。要対応・要確認は増えない。和文の
    「研究　次郎」は分けられるので載せない。"""
    path = names_article(tmp_path / "en.docx", ["研究\u3000次郎"], ["KENKYU"])
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", ai_mode="manual"))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    [warn] = [w for w in res.warnings if "英文の著者名" in w]
    assert "「KENKYU」" in warn and "全体を姓として" in warn and "Word で" in warn
    assert any(d.category == "name" and "「KENKYU」" in d.message for d in res.build_notes)
    # AI 依頼文の「# 姓と名の区切りを確かめる氏名」には、英文の氏名を載せない（C043。W8 の手順 15。決定事項 17 で載せていた）
    assert "# 姓と名の区切りを確かめる氏名" not in res.prompt_path.read_text(encoding="utf-8")
    assert [a.key for a in actions(res)] == []      # 手動の回答待ちは、位置を聞く図形がないので 2 章の 1 行だけ
    root = load(res)
    [en] = [n for n in root.iter("name") if n.get("name-style") == "western"]
    assert [(x.tag, x.text) for x in en] == [("surname", "KENKYU")]
    # AI が英文の氏名の姓と名を答えても採用しない（確かめてもらう氏名は和文だけ。C043。XML も変わらない）
    src = res.plan.authors[0].name_en.src
    resp = answers.answer(names=[(src, "KEN", "KYU", "試しの分割", "低")])
    res2 = convert(path, meta, journal, Options(out_dir=tmp_path / "out2", ai_mode="manual", ai_response=resp))
    assert [why for _, why in res2.ai.rejected] == [ai_assist.NAME_UNLISTED_WHY]
    assert res2.ai.accepted == [] and res2.xml_path.read_bytes() == res.xml_path.read_bytes()


# ----------------------------------------------------------------------------- 点検 2026-11（A1・A2・A3・A6・A8）
def _op(**kw):
    base = {"op": "", "src": "", "text": "", "occurrence": 1, "target": "", "role": "", "image": "", "mathml": "",
            "surname": "", "given": "", "reason": "試験", "confidence": "高"}
    base.update(kw)
    return base


def _manual_raw(items, meta, journal, out, notes=(), placements=(), key="links"):
    """回答の一覧 key（既定は links）と placements・notes を手で書いた回答（項目の型の誤りそのものを試す）で変換する。"""
    resp = json.dumps({"request_id": answers.THIS_REQUEST, key: list(items), "placements": list(placements), "notes": notes},
                      ensure_ascii=False)
    return convert(FULL, meta, journal, Options(out_dir=out, ai_mode="manual", ai_response=resp))


def test_a1_op_field_types(journal, meta, tmp_path):
    """A1: 回答の項目が一覧・辞書・bool だと理由付きで不採用、数値は文字列にして照合に使う（変換は止まらない）。"""
    links = [answers.link("文献", ["d18"], "2001", 1, "B2"), answers.link("文献", "d18", {"a": 1}, 1, "B2"),
             answers.link("文献", "d18", 2001, 1, "B2")]
    res = _manual_raw(links, meta, journal, tmp_path)
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    whys = [why for _, why in res.ai.rejected]
    assert sum("文字列でない" in w for w in whys) == 2 and len(whys) == 2
    assert [op["text"] for op, _ in res.ai.accepted] == ["2001"]
    res = _manual_raw([dict(answers.boundary("d46", "資料の見出し"), kind=True), dict(answers.name("d11", "研究", "次郎"), given=[1]),
                       "d46"], meta, journal, tmp_path / "b", key="boundaries")
    assert [why for _, why in res.ai.rejected] == [
        "項目 kind が文字列でない（bool）ので使わなかった", "boundaries の要素が { } のまとまりでない（str）ので使わなかった",
        ai_assist.BOUNDARY_KIND_WHY.format(kind="")]            # 区切りの一覧に書かれた氏名の指定（kind がない）


def test_a1_placements_types(journal, meta, tmp_path):
    """A1: placements の各欄の型が違っても変換は止まらず、理由付きで不採用（文字列でない項目）。数値は文字列にして照合し、図形の
    ID で不採用になる（この原稿に図形 s1 はない）。"""
    pl = answers.placement("s1", "d18")
    pls = [dict(pl, float=["s1"]), dict(pl, float=1.5), dict(pl, after={"x": 1}), dict(pl, after=7), dict(pl, reason=5),
           dict(pl, page="三")]
    res = _manual_raw([], meta, journal, tmp_path, placements=pls)
    assert res.fidelity.ok and len(res.ai.rejected) == len(pls)
    whys = [why for _, why in res.ai.rejected]
    assert sum("が文字列でない" in w for w in whys) == 2
    assert sum("は「位置を決める図・表」にない" in w for w in whys) == 4


def test_a1_a2_parse_paths_do_not_raise():
    data = parse_response(json.dumps({"links": [answers.link("図", "d18", 1.5, 1, "F1")], "placements": [], "notes": 3}))
    out = ai_assist.AIOutcome()
    plan_like = types.SimpleNamespace(body_seq=[], floats={}, textboxes={}, region={}, paras={})
    ops = ai_assist.link_ops(data, plan_like, out)
    assert ops[0]["text"] == "1.5" and out.rejected == []
    cut = ai_assist.parse_cut_response('{"placements": [{"float": ["s1"], "after": 3}, {"fl')
    out2 = ai_assist.AIOutcome()
    assert ai_assist.float_placements(cut, plan_like, out2) == {} and len(out2.rejected) == 1


def test_a2_notes_types():
    def notes(v):
        return parse_response(json.dumps({"links": [], "placements": [], "notes": v}))["notes"]
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


def test_c141_link_text_width_variant_links_single_place(journal):
    """C141（W8 の手順 26）: リンクの text が段落の文字と全角・半角だけ違い、1 か所に決まるときは、段落の文字の範囲でリンクする（文字は変えない）。
    2 か所に当たるとき・全角・半角以外も違うときは不採用。"""
    from jasme_jats.model import Atom, Para
    from jasme_jats.linker import find_width_insensitive
    p = Para(src="dx", atoms=[Atom(kind="text", text="Aは（2019）と（2020）を見る")])
    assert find_width_insensitive(p, "(2019)") == (2, 8)
    assert find_width_insensitive(p, "(2019") == (2, 7)
    assert find_width_insensitive(p, "(2021)") is None
    q = Para(src="dy", atoms=[Atom(kind="text", text="（2019）と(2019)")])
    assert find_width_insensitive(q, "(2019)") is None          # 2 か所に当たる
    assert find_width_insensitive(q, "") is None
    _, plan, _ = _mechanical(FULL, journal, {}, {})
    target = next(pp for pp in plan.paras.values() if pp.plain().strip() and pp.src not in {x.src for x in plan.title})
    before = target.plain()
    plan_text = "（2019）"
    target.atoms = [Atom(kind="text", text=before + plan_text)]
    fid = plan.figures[0].fid
    out = ai_assist.AIOutcome()
    ai_assist.apply_ops([_op(op="link_figure", src=target.src, text="(2019)", target=fid)], plan, None, out)
    assert len(out.accepted) == 1, out.rejected
    assert target.plain() == before + plan_text                     # 文字は変わらない
    # 2 回目以降の指定は救わない（同じ文字が 1 か所だけの段落で、回数の違う指定を黙って 1 回目に読み替えない。点検 review13 原則 2）
    for occ, text in ((2, "(2019)"), (999, "(2019)"), (2, plan_text)):
        out = ai_assist.AIOutcome()
        ai_assist.apply_ops([_op(op="link_figure", src=target.src, text=text, target=fid, occurrence=occ)], plan, None, out)
        assert out.accepted == [] and [w for _, w in out.rejected] == [f"段落 {target.src} に「{text}」（{occ} 回目）が見つからない"]


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


def test_formula_image_is_gone():
    """数式の画像の書き起こし（操作 formula_image・MathML の読み取り parse_mathml・DTD 不合格のときの取り消し・FigNode.formula）は
    なくした（修正計画 W8 の手順 12。docx の画像を AI に渡さないので、AI は読めない）。"""
    from pathlib import Path
    import jasme_jats
    from jasme_jats.article import FigNode
    src = Path(jasme_jats.__file__).resolve().parent
    for path in src.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "formula_image" not in text and "parse_mathml" not in text and "MATHML_ELEMENTS" not in text, path.name
    assert "formula" not in FigNode.__dataclass_fields__ and not hasattr(ai_assist, "FORMULA_IMAGE_WHY")


def test_a8_float_with_image_and_table_keeps_the_table(journal, meta, tmp_path):
    """A8: 画像と表の入った図形の位置を AI が指定しても、表が残り、不変性チェックも通る。W1 からは、キャプションのない
    図形（画像を直接持たないテキストボックス）の画像と表は別々の要素として出る（float_units の B4）ので、画像はキャプションなしの図、
    表は表のまま（前は数式の画像の書き起こし〈formula_image〉も試していたが、W8 の手順 12 で操作ごとなくした）。"""
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
    anchor = next(x for x in plan.body_seq if plan.paras[x].plain().startswith("本文である"))
    resp = answers.answer(placements=[(fid, anchor)])
    res = convert(p, meta, journal, Options(out_dir=tmp_path / "o", ai_mode="manual", ai_response=resp))
    assert res.fidelity.ok and res.fidelity.final_ok and res.ai.error == ""
    assert res.plan.floats[fid].mode == "ai" and res.ai.rejected == []
    root = load(res)
    assert "表の文字甲" in res.xml_path.read_text(encoding="utf-8")
    assert not any(f.find("table-wrap") is not None for f in root.iter("fig"))      # 表は図の中に入らない


# ---------------------------------------------------------------------------- 回答の形（A9・A10・{ } でない操作）
_OP1 = answers.link("文献", "d5", "2001", 1, "B1")          # 回答の一覧の要素 1 件（回答全体ではない）
_EMPTY_ANS = answers.empty()


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


def test_parse_response_requires_answer_items():
    """回答は種類ごとの一覧を持つ { }（W8 の手順 10）。指定 1 件だけの回答・回答の項目のない回答・一覧でない項目は断る。前の形の
    回答（operations を持つもの）は、古い形式だと断る（古い形を読む経路は持たない）。ない一覧は [] とみなす。"""
    with pytest.raises(ValueError, match="指定 1 件だけ"):
        parse_response(json.dumps(_OP1))
    for d in ({}, {"request_id": "R-AAAA-BBBB"}, {"pdf": {"status": "見た", "pages": 3}}):
        with pytest.raises(ValueError, match="回答の項目（placements・boxes・boundaries・links・names・style_fixes・notes）がありません"):
            parse_response(json.dumps(d))
    for key in ("placements", "boxes", "boundaries", "links", "names", "style_fixes"):
        with pytest.raises(ValueError, match=f"JSON の {key} が一覧"):
            parse_response(json.dumps({key: {}}))
    for old in ({"operations": []}, {"placements": [], "operations": [], "notes": []}, json.loads(FLOAT_OLD)):
        with pytest.raises(ValueError, match="古い形式です（operations があります）"):
            parse_response(json.dumps(old, ensure_ascii=False))
    assert parse_response(RESPONSE)["links"]
    data = parse_response(json.dumps({"notes": ["気づきだけ"]}, ensure_ascii=False))
    assert data["links"] == data["placements"] == [] and data["notes"] == ["気づきだけ"] and data["pdf"] == {}
    assert parse_response(json.dumps(_EMPTY_ANS))["links"] == []
    # 依頼文の見本（値が「＜…＞」の説明）は、そのまま貼ると見本の写しとして断る（C019。W8 の手順 13）
    with pytest.raises(ValueError, match="見本と同じ内容の項目"):
        parse_response(json.dumps(example_block(), ensure_ascii=False))


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


def test_non_dict_items_are_recorded(journal, meta, tmp_path):
    """一覧の要素が { } のまとまりでないもの（文字列・一覧）は、理由付きで不採用に記録する（黙って落とさない）。"""
    outcome = ai_assist.AIOutcome()
    plan_like = types.SimpleNamespace(paras={})
    assert ai_assist.link_ops({"links": ["文献 d18", [1]]}, plan_like, outcome) == []
    assert len(outcome.rejected) == 2
    assert "str" in outcome.rejected[0][1] and "list" in outcome.rejected[1][1]
    assert outcome.rejected[0][0]["text"] == "文献 d18"
    res = _manual_raw(["文献 d18", [1]], meta, journal, tmp_path)
    assert len(res.ai.rejected) == 2 and res.fidelity.ok
    report = res.report_path.read_text(encoding="utf-8")
    sec2 = report.split("\n## 2.")[1].split("\n## 3.")[0]                              # 2 章の不採用の表
    assert "文献 d18" in sec2
    assert sum("links の要素が { } のまとまりでない（str）" in ln for ln in sec2.splitlines()) == 1
    assert sum("links の要素が { } のまとまりでない（list）" in ln for ln in sec2.splitlines()) == 1


# ----------------------------------------------------------------------------- 英文要旨が見つからないとき（u5-exclusions）
def test_set_role_abstract_for_missing_abstract_is_a_proposal(journal, meta, tmp_path):
    """英文要旨のスタイルも見出しもない原稿では、依頼文が「英文要旨の段落が見つからない」と書く（AI は style_fixes で提案する）。
    英文要旨のスタイルのない段落を英文要旨にする指定は、Word のスタイルで直す提案にして XML には反映しない（所有者の決定 5。
    W8 の手順 5）。abstract_missing は残り、XML は回答なしと同じ。"""
    from test_structure import _no_abstract_style_docx
    from jasme_jats.structure import EN_OTHER_EXCLUDED
    path = _no_abstract_style_docx(tmp_path)
    before = convert(path, meta, journal, Options(out_dir=tmp_path / "before", ai_mode="manual"))
    assert "abstract_missing" in [a.key for a in actions(before)] and before.plan.abstract == []
    prompt = before.prompt_path.read_text(encoding="utf-8")
    assert "英文要旨の段落が見つからない" in prompt
    # 操作の案内（前の形の set_role）は書かず、事実だけを「# 出力から除いた段落」の最初に書く（W8 の手順 15）
    sec = prompt.split("# 出力から除いた段落（確かめるだけ）\n", 1)[1]
    assert sec.startswith("英文要旨の段落が見つからないため、英文の部分の段落（") and "set_role" not in prompt
    first = next(s for s, why, _ in before.fidelity.excluded if why == EN_OTHER_EXCLUDED)
    assert first in prompt
    res = _manual(path, answers.answer(style_fixes=[(first, "abstract")]), meta, journal, tmp_path / "after")
    assert res.plan.abstract == [] and res.fidelity.ok and res.dtd_valid
    assert res.ai.rejected == []
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


@pytest.mark.parametrize("name", list(CONFLICT_ROLE_CASES))
def test_set_role_that_makes_conflict_is_rejected(name, journal, meta, tmp_path, monkeypatch):
    """AI の区切りの指定で組み直すと構造の衝突（同じ種類の後付けの見出しが 2 つ・著者名に付かない所属。K1・K2）ができるときは、
    中止せず、その指定を不採用（2 章。CONFLICT_ROLE_WHY）にして組み直す。不変性チェックは合格し、衝突は残らない。
    今の判定（決定 5）では、これらの役割はスタイルの提案（style_fixes）で、XML には反映しない（組み直さない）。構造の衝突の守り
    （pipeline._reject_roles・structure.conflict_overrides）は、区切りの検証を差し替えて（answers.force_boundaries）確かめる。"""
    kw, text, role = CONFLICT_ROLE_CASES[name]
    path = mf.make_conflict(tmp_path / f"{name}.docx", **kw)
    _, plan, _ = _mechanical(path, journal)
    src = _src_of(plan, text)
    assert plan.structure_conflicts == [] and _mechanical(path, journal, {src: role})[1].structure_conflicts
    res = _manual(path, answers.answer(style_fixes=[(src, role)]), meta, journal, tmp_path / "proposal")
    assert res.ai.rejected == [], name
    assert [f.src for f in res.ai.style_fixes] == [src] and res.plan.structure_conflicts == [], name
    answers.force_boundaries(monkeypatch, {src: role})
    res = _manual(path, answers.answer(), meta, journal, tmp_path / "out")
    assert [(op["src"], op["role"], why) for op, why in res.ai.rejected] == [(src, role, pipeline.CONFLICT_ROLE_WHY)], name
    assert not [op for op, _ in res.ai.accepted if op["op"] == "boundary"] and res.ai.boundaries == [], name
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
    """AI の区切りの指定で衝突ができたとき、1 段目は衝突の範囲（落ちる所属から次の所属まで。前付けの中）の段落への指定だけを
    不採用にして組み直す: 本文の見出しへの指定は採用されたまま、著者 1 への指定だけが不採用（組み立ては 3 回: 機械的な
    組み立て・回答を反映・1 段目）。区切りの検証を差し替えて（answers.force_boundaries）、衝突を作る役割で確かめる。"""
    path = mf.make_conflict(tmp_path / "k2.docx", **_K2_AUTHORS)
    _, plan, _ = _mechanical(path, journal)
    author, head = _src_of(plan, "試験　六郎"), _src_of(plan, "１．はじめに")
    answers.force_boundaries(monkeypatch, {author: role, head: "sec2"})   # 区切り以外の役割も反映する形で、衝突の守りを確かめる
    calls = _count_mechanical(monkeypatch)
    res = _manual(path, answers.answer(), meta, journal, tmp_path / "a")
    assert [(op["src"], why) for op, why in res.ai.rejected] == [(author, pipeline.CONFLICT_ROLE_WHY)]
    assert [op["src"] for op, _ in res.ai.accepted if op["op"] == "boundary"] == [head]
    assert [b.src for b in res.ai.boundaries] == [head]          # 使わなかった指定は、反映した直しの一覧から除く
    assert calls == [{}, {author: role, head: "sec2"}, {head: "sec2"}]
    assert res.plan.structure_conflicts == [] and res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    assert [x for x in res.plan.decisions if x.stage == "ai" and x.src == head]           # 本文の見出しの指定は判断の一覧に残る
    assert [[x.ja.plain() for x in a.affs] for a in res.plan.authors] == [["第一大学"], ["第二大学"]]   # 著者 1 は元のまま


def test_conflict_outside_range_rejects_all_set_roles(journal, meta, tmp_path, monkeypatch):
    """衝突の範囲の中に AI の指定がない衝突（範囲の外の set_role だけでできた衝突）では、1 段目を飛ばし、2 段目で set_role をすべて
    不採用にして組み直す。形: 本文スタイルの「注」が 2 つ続いた後ろに章見出しがあるので、機械的には先の「注」から章見出しの前までを
    本文に戻す（K5）。AI がその章見出しを本文の段落（p）にすると、本文に戻さなくなり、注の見出しが 2 つになる（衝突の範囲は 2 つの
    「注」の間で、章見出しは範囲の外）。本文の見出しへの別の指定も不採用になる。"""
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
    answers.force_boundaries(monkeypatch, {chapter: "p", head: "sec1"})   # 区切り以外の役割も反映する形で、衝突の守りを確かめる
    calls = _count_mechanical(monkeypatch)
    res = _manual(path, answers.answer(), meta, journal, tmp_path / "out")
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
    d = answers.data(links=[("文献", "d5", "2001", 1, "B1", "本物の回答の理由")])
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
    ok["notes"] = [ai_assist.REQUEST_TITLE + " の見出しは" + ai_assist.DATA_HEADING + "と同じ"]
    assert parse_response(json.dumps(ok, ensure_ascii=False))["links"]


def test_several_code_blocks_are_refused():
    # 見本のあとに本物の回答が続く回答も、どれを読むか推測せず断る
    with pytest.raises(ValueError, match="2 つ"):
        parse_response(f"見本はこうです。\n{ai_assist.request_instructions(ALL_SECTIONS).split('## 回答の形', 1)[1]}\n\n"
                       f"回答です。\n{_real_answer_block()}\n")
    # コードブロックが 1 つなら、前後の説明があっても今までどおり読む。{ で始まる回答（中身だけのコピー）も同じ
    assert parse_response("回答です。\n" + _real_answer_block() + "\n以上")["links"]
    assert parse_response(_real_answer_block().split("\n", 1)[1].rsplit("\n", 1)[0])["links"]


def _sample_answer():
    """依頼文の「## 回答の形」の見本と同じ形（値が「＜…＞」の説明）の回答（修正計画 W8 の 4.1。依頼文の見本は手順 13 で入る）。"""
    return {"request_id": "R-AAAA-BBBB", "pdf": {"status": "＜見た｜添付なし｜別の論文＞", "pages": 0},
            "placements": [{"float": "＜s1 など＞", "after": "＜段落 ID か 空＞", "after_head": "＜その段落の先頭 8 字か 空＞",
                            "page": 0, "column": "＜左｜右｜両方｜空＞", "basis": "＜PDF｜配置の情報｜仮の位置＞",
                            "reason": "＜根拠＞", "confidence": "＜高｜中｜低＞"}],
            "links": [{"kind": "＜文献｜図｜表｜注｜式＞", "src": "＜段落 ID＞", "head": "＜先頭 8 字＞", "text": "＜リンクにする文字＞",
                       "occurrence": 1, "target": "＜B3・F1・T2・fn1・FD1 など＞", "reason": "＜根拠＞", "confidence": "＜高｜中｜低＞"}],
            "notes": ["＜気づき＞"]}


def test_sample_items_in_answer_are_refused():
    """見本の写し（値がまるごと「＜…＞」の項目）は、回答ごと断る。断る文は件数だけを言い、内部の項目名・ID は出さない。"""
    with pytest.raises(ValueError, match="見本") as ei:
        parse_response(json.dumps(_sample_answer(), ensure_ascii=False))
    msg = str(ei.value)
    assert "3 件" in msg and "placements" not in msg and "links" not in msg and "＜" not in msg
    # 画面ごとの操作（手順番号・欄の名前・ファイル名）は書かない（レポート・コマンドラインにもそのまま出る文）
    for m in (ai_assist.PASTED_REQUEST_MSG, msg):
        assert "手順" not in m and "欄" not in m and ".txt" not in m
    # 見本の項目が 1 件だけ入った回答（ほかは本物）
    d = answers.data(links=[("文献", "d5", "2001", 1, "B1", "本物の回答の理由")])
    d["links"].append(_sample_answer()["links"][0])
    with pytest.raises(ValueError, match="見本"):
        parse_response(json.dumps(d, ensure_ascii=False))
    # 文字の一部に「＜」「＞」がある本物の回答は読む
    d = answers.data(links=[("文献", "d5", "2001", 1, "B1", "本文の「＜注意＞」の後ろの引用")])
    assert parse_response(json.dumps(d, ensure_ascii=False))["links"]
    # 途中で切れた回答から読む位置の指定でも、見本の写しは使わない
    cut = json.dumps(_sample_answer()["placements"], ensure_ascii=False)
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
