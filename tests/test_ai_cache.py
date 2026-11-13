"""AI の回答の使い回し（修正計画 W8 の 4.6・手順 18。出力フォルダの AI回答.json と Options.ai_cache）。

反映した回答の写しを AI回答.json（{"meta": {方法・依頼の番号・提供元・モデル・PDF の渡し方・PDF の sha256}, "answer": 回答}）に書き、
次の変換で中身が Options.ai_cache に渡され、API モードで meta がすべて同じなら、API を呼ばずにその回答を使う。
手動モードでは使い回さない。1 画面版は AppState.ai_cache、ノートブックは変数 AI_CACHE、コマンドラインは出力フォルダの
AI回答.json（--ai-refresh で読まない）で持つ。API は呼ばない（偽の call_provider）。内容は架空。
"""
import json
import zipfile

import pytest

import answers
from conftest import FLOAT, FULL, META_EXAMPLE, fill_images
from jasme_jats import ai_assist, app, pipeline
from jasme_jats.ai_assist import ANSWER_FILE, CACHE_KEYS, REUSED_MSG, AIOutcome, cache_meta, cache_text, cached_answer
from jasme_jats.pipeline import Options, convert


def body_para(docx):
    """docx の本文の、文字のある最初の段落の ID（スタイルの提案の項目に使う）。"""
    _, plan = answers.request_of(docx)
    return next(s for s in plan.body_seq if ai_assist.head_of(plan.paras.get(s)))


def fake_api(monkeypatch, answer_text, cut=False):
    """pipeline.call_provider を偽にする（呼ばれた回数を数える）。回答は answer_text。"""
    calls = []

    def fake(provider, system_text, request_text, images, model=None, api_key=None):
        calls.append((provider, model))
        return AIOutcome(mode="api", model=model or "", provider=provider, raw=answer_text, cut=cut,
                         usage={"input_tokens": 10, "output_tokens": 5})
    monkeypatch.setattr(pipeline, "call_provider", fake)
    return calls


def api_opts(out, cache=None, **kw):
    return Options(out_dir=out, ai_mode="api", ai_api_key="t", ai_cache=cache, **kw)


def test_meta_and_match():
    """meta の項目と、1 つでも違えば使わないこと。手動モードの写しは API の変換で使わない。"""
    meta = cache_meta("api", "R-AAAA-BBBB", "claude", "m1")
    assert tuple(meta) == CACHE_KEYS and meta["pdf_send"] == "" and meta["pdf_sha256"] == ""
    text = cache_text(meta, {"request_id": "R-AAAA-BBBB", "links": []})
    assert json.loads(text)["meta"] == meta
    assert cached_answer(text, meta) == {"request_id": "R-AAAA-BBBB", "links": []}
    for key, value in (("request_id", "R-AAAA-CCCC"), ("model", "m2"), ("provider", "openai"), ("pdf_send", "document"),
                       ("pdf_sha256", "ab")):
        assert cached_answer(text, {**meta, key: value}) is None
    manual = cache_meta("manual", "R-AAAA-BBBB", "claude", "m1")
    assert manual["provider"] == manual["model"] == ""
    assert cached_answer(cache_text(manual, {}), meta) is None          # 手動の写しは API の変換で使わない
    assert cached_answer(text, manual) is None                          # 手動モードでは使い回さない
    for broken in ("", "{", "[]", json.dumps({"meta": meta}), json.dumps({"meta": meta, "answer": []}), None):
        assert cached_answer(broken, meta) is None


def test_api_answer_is_reused_without_calling(monkeypatch, tmp_path):
    """API で同じ meta の AI回答.json があれば、偽のクライアントが呼ばれず、同じ回答で同じ XML になる。モデルが違えば呼ぶ。"""
    ans = answers.answer(style_fixes=[(body_para(FULL), "exclude")], docx=FULL)
    calls = fake_api(monkeypatch, ans)
    from jasme_jats.config import ArticleMeta, JournalConfig
    journal = JournalConfig.load()
    meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12", "peer_review": "あり"})
    first = convert(FULL, meta, journal, api_opts(tmp_path / "a"))
    assert len(calls) == 1 and not first.ai.error and not first.ai.reused and first.ai.style_fixes
    path = first.ai_answer_path
    assert path == tmp_path / "a" / ANSWER_FILE and path.is_file()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["meta"] == cache_meta("api", first.ai.request_id, "claude", ai_assist.DEFAULT_MODEL)
    assert saved["answer"]["request_id"] == first.ai.request_id
    # 記事フォルダの外なので ZIP には入らず、10 章の「ZIP に入れなかったファイル」にも出ない
    assert not any(ANSWER_FILE in n for n in zipfile.ZipFile(first.zip_path).namelist()) and not first.not_zipped
    cache = path.read_text(encoding="utf-8")
    # 書誌だけを変えた変換し直し: 呼ばない
    meta2 = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "5", "lpage": "16", "peer_review": "あり"})
    again = convert(FULL, meta2, journal, api_opts(tmp_path / "b", cache))
    assert len(calls) == 1 and again.ai.reused == REUSED_MSG and not again.ai.error
    assert again.ai.style_fixes == first.ai.style_fixes and again.ai.usage == {}
    assert again.ai_answer_path.read_text(encoding="utf-8") == cache           # 写しは同じ中身で書き直す
    report = again.report_path.read_text(encoding="utf-8")
    assert REUSED_MSG in report
    same = convert(FULL, meta, journal, api_opts(tmp_path / "c", cache))
    assert len(calls) == 1 and same.xml_path.read_bytes() == first.xml_path.read_bytes()
    # モデル・提供元が違えば呼ぶ
    convert(FULL, meta, journal, api_opts(tmp_path / "d", cache, ai_model="claude-other"))
    assert len(calls) == 2 and calls[-1] == ("claude", "claude-other")
    convert(FULL, meta, journal, api_opts(tmp_path / "e", cache, ai_provider="openai", ai_model="gpt-test"))
    assert len(calls) == 3 and calls[-1] == ("openai", "gpt-test")
    # 別の論文（依頼の番号が違う）では呼ぶ
    convert(FLOAT, meta, journal, api_opts(tmp_path / "f", cache))
    assert len(calls) == 4
    # 読めない写しでも呼ぶ（止めない）
    convert(FULL, meta, journal, api_opts(tmp_path / "g", "{壊れた"))
    assert len(calls) == 5


def test_not_written_or_used_when_unusable(monkeypatch, tmp_path):
    """使えなかった回答（別の論文への回答・途中で切れた回答・読めない回答）は写さない。手動モードでは ai_cache を使わない。"""
    from jasme_jats.config import ArticleMeta, JournalConfig
    journal = JournalConfig.load()
    meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12", "peer_review": "あり"})
    fake_api(monkeypatch, answers.answer(docx=FLOAT))                    # 別の論文への回答
    res = convert(FULL, meta, journal, api_opts(tmp_path / "a"))
    assert res.ai.error == ai_assist.OTHER_REQUEST_MSG and res.ai_answer_path is None
    assert not (tmp_path / "a" / ANSWER_FILE).exists()
    fake_api(monkeypatch, "{読めない")
    res = convert(FULL, meta, journal, api_opts(tmp_path / "b"))
    assert res.ai.error and res.ai_answer_path is None
    fake_api(monkeypatch, answers.answer(), cut=True)                    # 上限で止まったが最後まで書かれた回答
    res = convert(FULL, meta, journal, api_opts(tmp_path / "c"))
    assert res.ai_answer_path is None
    # 手動モード: 貼った回答の写しは書く（mode が manual）が、ai_cache の回答は使わない（回答は利用者が貼る）
    calls = fake_api(monkeypatch, answers.answer())
    api = convert(FULL, meta, journal, api_opts(tmp_path / "d"))
    cache = api.ai_answer_path.read_text(encoding="utf-8")
    manual = convert(FULL, meta, journal, Options(out_dir=tmp_path / "e", ai_mode="manual", ai_cache=cache))
    assert manual.ai_answer_path is None and not manual.ai.reused
    assert len(calls) == 1
    pasted = convert(FULL, meta, journal, Options(out_dir=tmp_path / "f", ai_mode="manual", ai_response=answers.answer()))
    written = json.loads(pasted.ai_answer_path.read_text(encoding="utf-8"))
    assert written["meta"]["mode"] == "manual" and written["meta"]["model"] == ""
    convert(FULL, meta, journal, api_opts(tmp_path / "g", pasted.ai_answer_path.read_text(encoding="utf-8")))
    assert len(calls) == 2                                               # 手動の写しは API の変換で使わない


def test_cli_reads_answer_file_and_refresh(monkeypatch, tmp_path, capsys):
    """コマンドライン: 出力フォルダの AI回答.json を読んで呼ばない。--ai-refresh で呼び直す。--ai api でないと引数の誤り。"""
    from jasme_jats.cli import main
    monkeypatch.setenv("ANTHROPIC_API_KEY", "t")
    calls = fake_api(monkeypatch, answers.answer())
    args = [str(FULL), "--meta", str(META_EXAMPLE), "--out", str(tmp_path / "out"), "--ai", "api"]
    main(args)
    assert len(calls) == 1 and (tmp_path / "out" / ANSWER_FILE).is_file()
    main(args)
    out = capsys.readouterr().out
    assert len(calls) == 1 and "AI は呼んでいません" in out
    main(args + ["--ai-refresh"])
    assert len(calls) == 2
    with pytest.raises(SystemExit) as ei:
        main(args[:-2] + ["--ai-refresh"])
    assert ei.value.code == 2 and "--ai-refresh は --ai api のときだけ" in capsys.readouterr().err


def test_app_keeps_cache_and_images(monkeypatch, tmp_path):
    """1 画面版: 出力フォルダを消しても AppState.ai_cache で回答を使い回し、入れた画像も同じ図に入れ直す。"""
    from test_app import filled
    monkeypatch.setenv("ANTHROPIC_API_KEY", "t")
    calls = fake_api(monkeypatch, answers.answer())
    st = filled(tmp_path)
    st.set_inputs(ai_mode="api")
    res = st.convert(app.IO())
    assert len(calls) == 1 and st.ai_cache == res.ai_answer_path.read_text(encoding="utf-8")
    keys = fill_images(st.res)
    assert keys
    st.set_inputs(received="2025-07-01")                # 書誌だけを直した変換し直し
    res = st.convert(app.IO())
    assert len(calls) == 1 and res.ai.reused
    assert keys and all(im.status != "missing" for im in res.images if im.key in keys), [(i.key, i.status) for i in res.images]     # 画像は使い回しの後も同じ図に入る
    st.set_inputs(model="claude-other")
    st.convert(app.IO())
    assert len(calls) == 2
    # 手動モードの変換は、API の写しを上書きしない
    cache = st.ai_cache
    st.set_inputs(ai_mode="manual")
    st.convert(app.IO())
    st.apply_answer(answers.answer())
    assert st.ai_cache == cache


def test_notebook_holds_ai_cache():
    """ノートブック: 手順 5 で AI_CACHE を Options.ai_cache に渡し、API の写しを覚える。手順 6・9 の「前の論文の回答」の確かめはない。"""
    from test_notebook import mk
    src = "".join("".join(c["source"]) for c in json.loads(mk.render())["cells"])
    assert 'ai_cache=globals().get("AI_CACHE")' in src and "AI_CACHE = res.ai_answer_path.read_text" in src
    assert "LAST_AI_RESPONSE" not in src and '"ai_response"' not in src
