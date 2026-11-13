"""AI への依頼文の指示の部分と AIRequest（修正計画 W8 の手順 13。実際の API は呼ばない）。

依頼文は【作業する方へ】（手動だけ）・指示の部分（「# 依頼」から「## 回答の形」まで）・データの部分（「# 論文（ここから下はデータ）」
から下）の 3 つ。指示は 1 回だけ書き、この論文で頼むことの節だけを、出す節だけで 1 から番号を振って出す（ai_assist.request_sections）。
API では system に指示、利用者の内容にデータを渡す。
"""
import json
import types

import pytest

from conftest import EDGE, FLOAT, FULL, NOTES, OUTSIDE, PDFCHECK, PLACE, STRUCTURE
from jasme_jats import ai_assist
from jasme_jats.ai_assist import (ANSWER_FIRST_API, ANSWER_FIRST_MANUAL, DATA_HEADING, HUMAN_HEADING, REQUEST_TITLE,
                                  build_request, parse_response, request_sections)
from jasme_jats.article import StyleSuspect
from jasme_jats.builder import build
from jasme_jats.pipeline import Options, _mechanical, convert

DOCS = [FULL, EDGE, FLOAT, NOTES, PDFCHECK, STRUCTURE, PLACE, OUTSIDE]
TITLES = {"placements": "図・表の位置", "boxes": "テキストボックスの種類", "links": "リンクの取りこぼし",
          "names": "著者名の姓と名の区切り", "style_fixes": "スタイルの見立て", "notes": "そのほかの気づき"}
# 今の形の前の依頼文の指示の部分（SYSTEM_PROMPT と、手動の回答の書き方・見本・項目の説明。W8 の 4.1 の「今の 7.4 千字」）の長さ
OLD_INSTRUCTIONS_LEN = 7400


def _request(path, journal, meta, **kw):
    _, plan, linker = _mechanical(path, journal)
    info = build(plan, meta, journal, None)[1]
    return plan, info, build_request(plan, linker, info, **kw)


@pytest.mark.parametrize("path", DOCS, ids=lambda p: p.stem)
def test_sections_follow_the_paper(path, journal, meta):
    """節を出す条件（W8 の 4.1 の表）: 図・表の位置は位置を聞く図形があるとき、テキストボックスの種類は決められない・推定した・
    図の注記とみなしたテキストボックスがあるとき、注の区切りは手で書いた注があるとき、氏名は確かめる和文の氏名があるとき。
    リンク・スタイル・気づきはいつも。番号は出す節だけで 1 から振り、頼むことの一覧・節の見出しと合う。"""
    plan, info, req = _request(path, journal, meta)
    keys = [s.key for s in req.sections]
    assert ("placements" in keys) == bool(plan.asked_floats)
    assert ("boxes" in keys) == bool(plan.textboxes and any(b.kind in ("undecided", "label") or b.estimated
                                                            for b in plan.textboxes.values()))
    bound = next((s for s in req.sections if s.key == "boundaries"), None)
    assert (bound is not None and "notes" in bound.parts) == any(not fn.word_note for fn in plan.fns)
    assert ("names" in keys) == bool(ai_assist.asked_names(info))
    assert [k for k in keys if k in ("links", "style_fixes", "notes")] == ["links", "style_fixes", "notes"]
    assert [s.n for s in req.sections] == list(range(1, len(keys) + 1))
    ins = req.instructions
    for s in req.sections:
        assert f"\n{s.n}. {s.title}" in ins and f"\n## {s.n}. {s.title}（{s.key}）\n" in ins
    for key, title in TITLES.items():
        if key not in keys:
            assert f"{title}（{key}）" not in ins and f"… {key}" not in ins
    assert "## 0. 最初に: PDF を確かめる（pdf）" in ins and ins.rstrip().endswith("```")
    # 頼まない一覧は、見本でも [] と書く
    example = json.loads(ai_assist.RE_FENCE.search(ins).group(1))
    assert list(example) == list(ai_assist.RESPONSE_SCHEMA["properties"])
    assert all((example[k] != []) == (k in keys) for k in ai_assist.ANSWER_LISTS)


def test_sections_cover_each_condition(journal, meta):
    """上の原稿の中に、どの節も、出る原稿と出ない原稿がある（条件の確かめが空回りしない）。"""
    seen = {}
    for path in DOCS:
        _, _, req = _request(path, journal, meta)
        for key in ("placements", "boxes", "boundaries", "names"):
            seen.setdefault(key, set()).add(key in {s.key for s in req.sections})
    assert all(v == {True, False} for v in seen.values()), seen


def test_numbers_restart_and_cross_references_follow(journal, meta):
    """図形のない原稿では、注の区切りが 1 番になり、ほかの節を指す文（スタイルの見立て・新しく分けた注へのリンク）もその番号で書く。"""
    _, _, req = _request(NOTES, journal, meta)
    num = {s.key: s.n for s in req.sections}
    assert num["boundaries"] == 1 and num["links"] == 2
    ins = req.instructions
    assert f"（ほかは「{num['style_fixes']}. スタイルの見立て」で提案します）" in ins
    assert "「1. 注の区切り」で新しく分けた注へのリンクは、target にその注の最初の段落の ID" in ins
    assert "次のことだけです" in ins and "資料の始まり:" not in ins and "注の区切り:" in ins
    # 注の区切りの節のない原稿（手で書いた注がない）では、新しく分けた注へのリンクの文を書かない
    _, _, req = _request(EDGE, journal, meta)
    assert "boundaries" not in {s.key for s in req.sections} and "新しく分けた注へのリンク" not in req.instructions
    # 注の区切りと資料の始まりの両方がある原稿
    _, _, req = _request(FULL, journal, meta)
    bound = next(s for s in req.sections if s.key == "boundaries")
    assert bound.title == "注の区切り・資料の始まり" and "次の 2 つだけです" in req.instructions
    assert '"資料の見出し"' in req.instructions and '"注の始まり"' in req.instructions


def test_placements_rules_are_written(journal, meta):
    """図・表の位置の節に、PDF を見たときの規則（ページと段・同じ after の並び・本文より後ろなら after を空に）と、PDF を見て
    いないときの答え方を書く（点検 review12 の利用者向け minor: 同じ after の並び方、PDF と Word のどちらで決めるか）。"""
    _, _, req = _request(FLOAT, journal, meta)
    ins = req.instructions
    assert "1. 図・表の位置（3 個）… placements" in ins
    assert "PDF を見たとき（basis は \"PDF\"）:" in ins and "PDF を見ていないとき（page は 0、column は \"\"）:" in ins
    assert "同じ after に 2 つ以上置くときは、PDF で先に読むものから順に placements に書きます（書いた順に並びます）。" in ins
    assert "8. 図の番号の順や、本文で最初に参照される位置には合わせません（PDF の位置が正です）。" in ins
    assert "after と after_head を \"\" にして" in ins
    # 前の形の操作・項目の名前は書かない
    for word in ("set_role", "split_name", "operations", "items", "link_citation", "formula_image"):
        assert word not in ins, word


def test_style_section_lists_suspects_only_when_there_are(journal, meta):
    """スタイルを確かめる段落（plan.style_suspects）があるときだけ、「1 つ残らず答える」の項を出し、AIRequest.asked に段落を入れる。"""
    _, plan, linker = _mechanical(FULL, journal)
    assert "「# スタイルを確かめる段落」" not in build_request(plan, linker).instructions
    plan.style_suspects = [StyleSuspect("heading_body", "d18", "架空の説明")]
    req = build_request(plan, linker)
    style = next(s for s in req.sections if s.key == "style_fixes")
    assert "suspects" in style.parts and req.asked["styles"] == ["d18"]
    assert "「# スタイルを確かめる段落」に挙げた段落（機械が疑わしいと見た所）には、1 つ残らず答えます。" in req.instructions
    assert "ほかにスタイルが違うと判断した段落があれば足します" in req.instructions


def test_human_part_is_manual_only_and_names_the_pdf(journal, meta):
    """【作業する方へ】は手動の依頼文だけに入れる。ツールに PDF が渡されていればファイル名を出し、渡されていなければ名前を出さない。
    位置を聞く図形がない論文では、2 行目を PDF の体裁の文にする。どちらも、添付しなくても回答は得られることを書く。"""
    _, _, req = _request(FLOAT, journal, meta, pdf_name="架空論文.pdf")
    lines = req.human.splitlines()
    assert lines[0] == HUMAN_HEADING and "出版版 PDF「架空論文.pdf」を同じメッセージに添付してください（強く推奨）。" in lines[1]
    assert "図・表を出版版と同じ位置に置けます" in lines[2] and "添付しなくても回答は得られます" in lines[2]
    assert req.manual_text().startswith(HUMAN_HEADING) and "架空論文.pdf" not in req.instructions + req.data
    _, _, req = _request(FLOAT, journal, meta)
    assert "この論文の出版版 PDF を同じメッセージに" in req.human and "「" not in req.human.splitlines()[1]
    _, _, req = _request(FULL, journal, meta, pdf_name="架空論文.pdf")
    assert req.human.splitlines()[2] == ("PDF があると、AI が PDF の体裁（見出し・引用の字下げ・著者名）を見て答えられます。"
                                         "添付しなくても回答は得られます。")
    _, _, req = _request(FLOAT, journal, meta, pdf_name="架空論文.pdf", manual=False)
    assert req.human == "" and not req.manual_text().startswith(HUMAN_HEADING)


def test_parts_and_texts(journal, meta):
    """手動の依頼文は 3 つをつないだもの。API の system は、指示の「## 回答の形」の最初の 1 文を「回答は JSON だけを書きます。」に
    替えたもの（ほかは同じ）。データの部分は「# 論文（ここから下はデータ）」から始まる。依頼の番号（request_stamp）は、指示の見出しと
    見本の request_id に出る。"""
    plan, _, req = _request(FLOAT, journal, meta)
    text = req.manual_text()
    assert text == f"{req.human}\n\n{req.instructions}\n\n{req.data}\n"
    assert req.instructions.startswith(f"{REQUEST_TITLE}（依頼の番号: {req.stamp}）\n") and req.data.startswith(DATA_HEADING + "\n")
    form = req.system_text().split("## 回答の形\n", 1)[1]
    assert form.startswith(ANSWER_FIRST_API) and ANSWER_FIRST_MANUAL not in req.system_text()
    assert req.system_text().replace(ANSWER_FIRST_API, ANSWER_FIRST_MANUAL, 1) == req.instructions
    assert ai_assist.RE_STAMP.match(req.stamp) and f'"request_id": "{req.stamp}"' in req.instructions
    assert req.asked["floats"] == plan.asked_floats and req.asked["boxes"] == plan.undecided_boxes


def test_instructions_are_shorter_than_before():
    """指示の部分は、すべての節・項目を出したときでも、今の形の前（7.4 千字）より短い（W8 の 4.1）。"""
    every = {"boxes": {"undecided", "estimated", "labels"}, "boundaries": {"notes", "apps"}, "links": {"notes"},
             "style_fixes": {"suspects", "excluded"}}
    sections = [ai_assist.RequestSection(k, i, TITLES.get(k, "注の区切り・資料の始まり"), "3 個", frozenset(every.get(k, ())))
                for i, k in enumerate(ai_assist.ANSWER_LISTS + ("notes",), 1)]
    ins = ai_assist.request_instructions(sections, "R-AAAA-BBBB")
    assert ins.startswith("# 依頼（依頼の番号: R-AAAA-BBBB）\n") and '"request_id": "R-AAAA-BBBB"' in ins
    assert len(ins) < OLD_INSTRUCTIONS_LEN


def test_request_heading_marks_pasted_request(journal, meta, tmp_path):
    """依頼文（手動の全体・API の指示だけ・データだけ・依頼の番号つきの見出し）を回答の欄に貼ると断る（C019。新しい見出し）。
    見出しの文字を notes に引用しただけ（行頭でない）なら断らない。"""
    _, _, req = _request(FULL, journal, meta)
    for text in (req.manual_text(), req.system_text(), req.data, "# 依頼（依頼の番号: R-AAAA-BBBB）\n{}"):
        with pytest.raises(ValueError, match="依頼文が貼られています"):
            parse_response(text)
    ok = {"links": [], "notes": [f"見出しの「{REQUEST_TITLE}」と「{DATA_HEADING}」"]}
    assert parse_response(json.dumps(ok, ensure_ascii=False))["notes"]
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, ai_mode="manual", ai_response=req.system_text()))
    assert "依頼文" in res.ai.error and not res.ai.accepted and res.fidelity.ok


# ---------------------------------------------------------------------------- 4 社の API に渡すもの
def _anthropic(monkeypatch, calls):
    import anthropic

    class FakeStream:
        def __init__(self, kw):
            calls.append(kw)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_final_message(self):
            return types.SimpleNamespace(stop_reason="end_turn", content=[types.SimpleNamespace(type="text", text="{}")],
                                         usage=None)

    class FakeClient:
        def __init__(self, *a, **k):
            self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(stream=lambda **kw: FakeStream(kw)))
            self.messages = self.beta.messages

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)


def test_four_providers_get_instructions_as_system(journal, meta, tmp_path, monkeypatch):
    """Claude・ChatGPT・Gemini・Sakana AI のどれでも、system に指示の部分（AIRequest.system_text）、利用者の内容にデータの部分
    （AIRequest.data）を渡す（修正計画 W8 の手順 13。点検 2 の指摘 12）。Sakana にも見本を足さない。"""
    from test_ai import _fake_gemini, _fake_openai, _fake_sakana
    _, _, req = _request(FLOAT, journal, meta, manual=False)
    system, data = req.system_text(), req.data
    calls = []
    _anthropic(monkeypatch, calls)
    assert not ai_assist.call_provider("claude", system, data, None, api_key="t").error
    assert calls[0]["system"] == system and calls[0]["messages"][0]["content"][-1]["text"] == data
    calls = []
    _fake_openai(monkeypatch, calls)
    ai_assist.call_provider("openai", system, data, None, model="gpt-test", api_key="t")
    assert calls[0]["instructions"] == system and calls[0]["input"][0]["content"][-1]["text"] == data
    calls = []
    _fake_gemini(monkeypatch, calls)
    ai_assist.call_provider("gemini", system, data, None, model="gemini-test", api_key="t")
    assert calls[0]["config"].system_instruction == system and calls[0]["contents"][0].parts[-1].text == data
    calls = []
    _fake_sakana(monkeypatch, calls)
    ai_assist.call_provider("sakana", system, data, None, model="fugu", api_key="k")
    msgs = next(c for c in calls if "messages" in c)["messages"]
    assert msgs[0] == {"role": "system", "content": system} and msgs[1]["content"][-1]["text"] == data
    # 変換でも同じ（pipeline が AIRequest の 2 つを渡す。【作業する方へ】は API には渡さない）
    seen = []
    real = ai_assist.call_provider

    def spy(provider, system_text, request_text, images, **kw):
        seen.append((system_text, request_text))
        return real(provider, system_text, request_text, images, **kw)
    monkeypatch.setattr("jasme_jats.pipeline.call_provider", spy)
    calls = []
    _anthropic(monkeypatch, calls)
    convert(FLOAT, meta, journal, Options(out_dir=tmp_path, ai_mode="api", ai_api_key="t"))
    (s, d), = seen
    assert s.startswith(REQUEST_TITLE) and HUMAN_HEADING not in s + d and d.startswith(DATA_HEADING)
