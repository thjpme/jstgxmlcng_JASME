"""テストの AI の回答を作る tests/answers.py の写し方（修正計画 W8 の手順 9・10）。項目ごとに、新しい形の回答
（ai_assist.RESPONSE_SCHEMA の一覧）のどの要素になるかと、その回答を ai_assist.parse_response がそのまま読めること、
前の形の回答を新しい形に写す to_new を確かめる。
"""
import json

import pytest

import answers
from conftest import FIXTURES
from jasme_jats.ai_assist import (BOUNDARY_KINDS, BOUNDARY_SCHEMA, BOX_SCHEMA, LINK_SCHEMA, NAME_SCHEMA, PLACEMENT_SCHEMA,
                                  RESPONSE_SCHEMA, STYLE_FIX_SCHEMA, head_of, parse_response)


def _keys(schema):
    return set(schema["required"])


def test_empty_answer():
    text = answers.answer()
    assert list(json.loads(text)) == RESPONSE_SCHEMA["required"]           # 依頼文の「## 回答の形」と同じ順（placements が一覧の最初）
    data = parse_response(text)
    assert all(data[k] == [] for k in ("placements", "boxes", "boundaries", "links", "names", "style_fixes", "notes"))
    assert data["request_id"] == answers.THIS_REQUEST and data["pdf"] == {"status": "添付なし", "pages": 0}


def test_placements():
    data = answers.data(placements=[("s1", "d20"), ("s2", "d21", "図の直上", "低")])
    assert [(pl["float"], pl["after"], pl["after_head"], pl["reason"], pl["confidence"]) for pl in data["placements"]] == [
        ("s1", "d20", "", answers.DEFAULT_REASON, "中"), ("s2", "d21", "", "図の直上", "低")]
    assert all(set(pl) == _keys(PLACEMENT_SCHEMA) for pl in data["placements"])
    assert data["boxes"] == [] and data["links"] == [] and data["notes"] == []


def test_boxes():
    data = answers.data(boxes=[("x1", "囲み", "d30"), ("x2", "図の注記", "", "矢印の文字", "高")])
    assert [(b["box"], b["kind"], b["after"], b["reason"], b["confidence"]) for b in data["boxes"]] == [
        ("x1", "囲み", "d30", answers.DEFAULT_REASON, "中"), ("x2", "図の注記", "", "矢印の文字", "高")]
    assert all(set(b) == _keys(BOX_SCHEMA) for b in data["boxes"])
    assert data["placements"] == []                                  # 新しい形では、テキストボックスは placements に入れない
    with pytest.raises(ValueError, match="囲み・図の注記"):
        answers.data(boxes=[("x1", "box", "d30")])                  # 中の名前ではなく、回答に書く語で渡す


@pytest.mark.parametrize("kind", list(BOUNDARY_KINDS))
def test_boundaries(kind):
    [b] = parse_response(answers.answer(boundaries=[("d40", kind, "番号で始まる", "中")]))["boundaries"]
    assert (b["src"], b["kind"], b["reason"], b["confidence"], b["head"]) == ("d40", kind, "番号で始まる", "中", "")
    assert set(b) == _keys(BOUNDARY_SCHEMA)
    with pytest.raises(ValueError, match="注の始まり"):
        answers.data(boundaries=[("d40", "fn_start")])


def test_links():
    items = [(kind, "d18", "2001", 2, target) for kind, target in
             (("文献", "B2"), ("図", "F1"), ("表", "T1"), ("注", "fn2"), ("式", "FD1"))]
    links = parse_response(answers.answer(links=items))["links"]
    assert [(x["kind"], x["src"], x["text"], x["occurrence"], x["target"]) for x in links] == items
    assert {(x["reason"], x["confidence"]) for x in links} == {(answers.DEFAULT_REASON, answers.DEFAULT_CONFIDENCE)}
    assert all(set(x) == _keys(LINK_SCHEMA) for x in links)
    with pytest.raises(ValueError, match="文献・図・表・注・式"):
        answers.data(links=[("link_citation", "d18", "2001", 1, "B2")])


def test_names():
    [n] = parse_response(answers.answer(names=[("d2", "試験", "六郎", "英文の著者名と照らした")]))["names"]
    assert n == {"src": "d2", "surname": "試験", "given": "六郎", "reason": "英文の著者名と照らした",
                 "confidence": answers.DEFAULT_CONFIDENCE}
    assert set(n) == _keys(NAME_SCHEMA)


def test_style_fixes():
    """役割の名前から、この誌のスタイル名と Word での直し方に写す（除外はスタイル名なし）。"""
    fixes = parse_response(answers.answer(style_fixes=[("d9", "sec2", "番号の形", "低"), ("d10", "exclude")]))["style_fixes"]
    assert [(f["src"], f["verdict"], f["style"], f["how"], f["confidence"]) for f in fixes] == [
        ("d9", "直す", "節見出し", "Word で段落のスタイルを「節見出し」にする", "低"),
        ("d10", "直す", "", "本文に要らない段落なら、Word で消す", answers.DEFAULT_CONFIDENCE)]
    assert all(set(f) == _keys(STYLE_FIX_SCHEMA) for f in fixes)
    with pytest.raises(ValueError, match="ROLES"):
        answers.data(style_fixes=[("d9", "節見出し")])


def test_notes():
    assert parse_response(answers.answer(notes=["番号が飛んでいる", "注 3 は参照されていない"]))["notes"] == [
        "番号が飛んでいる", "注 3 は参照されていない"]


def test_base_answer_is_extended():
    """base（回答の文字か dict）の一覧の後ろに足す。base は変えない。"""
    base = answers.answer(placements=[("s1", "d20")], notes=["前の気づき"])
    text = answers.answer(base=base, links=[("図", "d23", "見開き", 1, "F2")], notes=["気づき"])
    data = json.loads(text)
    assert [pl["float"] for pl in data["placements"]] == ["s1"]
    assert [x["kind"] for x in data["links"]] == ["図"] and data["notes"] == ["前の気づき", "気づき"]
    assert json.loads(base)["links"] == []


def test_wrong_item_length_is_refused():
    with pytest.raises(ValueError, match="項目の数"):
        answers.data(placements=[("s1",)])
    with pytest.raises(ValueError, match="項目の数"):
        answers.data(names=[("d2", "試験", "六郎", "理由", "高", "余分")])


# ---------------------------------------------------------------------------- to_new（前の形の回答を新しい形に写す）
def _op(op, src, **kw):
    out = {"op": op, "src": src, "text": "", "occurrence": 1, "target": "", "role": "", "image": "", "mathml": "",
           "surname": "", "given": "", "reason": "前の形", "confidence": "中"}
    out.update(kw)
    return out


def _plan(name):
    from jasme_jats.config import JournalConfig
    from jasme_jats.pipeline import _mechanical
    return _mechanical(FIXTURES / name, JournalConfig.load(None))[1]


def test_to_new_operations():
    """link_* は links、split_name は names、区切りでない set_role は style_fixes、formula_image は捨てる。head は段落の先頭の文字。"""
    plan = _plan("sample_full.docx")
    old = {"placements": [], "notes": ["気づき"], "operations": [
        _op("link_citation", "d18", text="2001", target="B2"), _op("link_figure", "d20", text="図1", occurrence=2, target="F1"),
        _op("split_name", "d11", surname="研究", given="次郎"), _op("set_role", "d46", role="sec1"),
        _op("formula_image", "", image="img3", mathml="<math/>"), _op("unknown", "d18")]}
    new = answers.to_new(old, plan)
    assert [(x["kind"], x["src"], x["text"], x["occurrence"], x["target"], x["head"]) for x in new["links"]] == [
        ("文献", "d18", "2001", 1, "B2", head_of(plan.paras["d18"])), ("図", "d20", "図1", 2, "F1", head_of(plan.paras["d20"]))]
    assert [(n["src"], n["surname"], n["given"]) for n in new["names"]] == [("d11", "研究", "次郎")]
    assert [(f["src"], f["style"], f["head"]) for f in new["style_fixes"]] == [("d46", "章見出し", head_of(plan.paras["d46"]))]
    assert new["boundaries"] == [] and new["notes"] == ["気づき"]
    assert head_of(plan.paras["d18"])                                   # 文字のある段落の head は空でない
    assert parse_response(json.dumps(new, ensure_ascii=False))["links"] == new["links"]


def test_to_new_boundaries_and_boxes():
    """区切りの直しに当たる set_role は boundaries（kind はその段落の区切りの語）、テキストボックスの placements は boxes。"""
    from jasme_jats.ai_assist import _written_notes
    plan = _plan("sample_notes.docx")
    notes = _written_notes(plan)
    later = next(q for fn in notes for q in fn.paras[1:]) if any(len(fn.paras) > 1 for fn in notes) else notes[1].paras[0]
    old = {"operations": [_op("set_role", later.src, role="fn_start"), _op("set_role", notes[0].paras[0].src, role="quote")],
           "placements": []}
    new = answers.to_new(old, plan)
    assert [(b["src"], b["kind"]) for b in new["boundaries"]] == [(later.src, "注の始まり")]
    assert [f["src"] for f in new["style_fixes"]] == [notes[0].paras[0].src]
    plan = _plan("sample_structure.docx")
    xid = next(iter(plan.textboxes))
    old = {"operations": [], "placements": [
        {"float": xid, "after": plan.body_seq[0], "items": [{"kind": "box", "caption": [], "body": []}], "reason": "r",
         "confidence": "高"}]}
    new = answers.to_new(old, plan)
    assert new["placements"] == [] and [(b["box"], b["kind"], b["after"]) for b in new["boxes"]] == [
        (xid, "囲み", plan.body_seq[0])]


def test_to_new_reads_fenced_text():
    plan = _plan("sample_full.docx")
    text = "```json\n" + json.dumps({"placements": [], "operations": [_op("link_citation", "d18", text="2001", target="B2")],
                                     "notes": []}, ensure_ascii=False) + "\n```"
    assert [x["text"] for x in answers.to_new(text, plan)["links"]] == ["2001"]
