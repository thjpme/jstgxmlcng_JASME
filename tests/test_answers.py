"""テストの AI の回答を作る tests/answers.py の写し方（修正計画 W8 の手順 9）。項目ごとに、今の形の回答
（placements・operations・notes）のどの要素になるかと、その回答を ai_assist.parse_response・split_ops がそのまま読めることを確かめる。
"""
import json

import pytest

import answers
from jasme_jats.ai_assist import BOUNDARY_KINDS, OP_SCHEMA, PLACEMENT_SCHEMA, RESPONSE_SCHEMA, parse_response, split_ops


def _ops(text):
    """回答の文字を読み、変換ツールが使う操作の一覧にする（読めない操作は落ちる）。"""
    return split_ops(parse_response(text))


def test_empty_answer():
    text = answers.answer()
    assert json.loads(text) == {"placements": [], "operations": [], "notes": []}
    assert list(json.loads(text)) == RESPONSE_SCHEMA["required"]           # placements を最初に書く（回答の書き方と同じ順）
    assert parse_response(text) == json.loads(text)


def test_placements():
    data = answers.data(placements=[("s1", "d20"), ("s2", "d21", "図の直上", "低")])
    assert data["placements"] == [
        {"float": "s1", "after": "d20", "items": [], "reason": answers.DEFAULT_REASON, "confidence": "中"},
        {"float": "s2", "after": "d21", "items": [], "reason": "図の直上", "confidence": "低"}]
    assert all(set(pl) == set(PLACEMENT_SCHEMA["required"]) for pl in data["placements"])
    assert data["operations"] == [] and data["notes"] == []


def test_boxes():
    data = answers.data(boxes=[("x1", "囲み", "d30"), ("x2", "図の注記", "", "矢印の文字", "高")])
    assert [(pl["float"], pl["after"], pl["items"], pl["reason"], pl["confidence"]) for pl in data["placements"]] == [
        ("x1", "d30", [{"kind": "box", "caption": [], "body": []}], answers.DEFAULT_REASON, "中"),
        ("x2", "", [{"kind": "label", "caption": [], "body": []}], "矢印の文字", "高")]
    with pytest.raises(ValueError, match="囲み・図の注記"):
        answers.data(boxes=[("x1", "box", "d30")])                  # 中の名前ではなく、回答に書く語で渡す


def test_placements_and_boxes_share_placements():
    """今の形では、図形の位置とテキストボックスの種類は同じ placements の一覧（図形が先）。"""
    data = answers.data(boxes=[("x1", "囲み", "d30")], placements=[("s1", "d20")])
    assert [pl["float"] for pl in data["placements"]] == ["s1", "x1"]


@pytest.mark.parametrize("kind", list(BOUNDARY_KINDS))
def test_boundaries(kind):
    [op] = _ops(answers.answer(boundaries=[("d40", kind, "番号で始まる", "中")]))
    assert (op["op"], op["src"], op["role"], op["reason"], op["confidence"]) == (
        "set_role", "d40", BOUNDARY_KINDS[kind], "番号で始まる", "中")
    with pytest.raises(ValueError, match="注の始まり"):
        answers.data(boundaries=[("d40", "fn_start")])


def test_links():
    want = {"文献": ("link_citation", "B2"), "図": ("link_figure", "F1"), "表": ("link_table", "T1"), "注": ("link_note", "fn2"),
            "式": ("link_formula", "FD1")}
    items = [(kind, "d18", "2001", 2, target) for kind, (_, target) in want.items()]
    ops = _ops(answers.answer(links=items))
    assert [(op["op"], op["src"], op["text"], op["occurrence"], op["target"]) for op in ops] == [
        (name, "d18", "2001", 2, target) for name, target in want.values()]
    assert {(op["reason"], op["confidence"]) for op in ops} == {(answers.DEFAULT_REASON, answers.DEFAULT_CONFIDENCE)}
    assert all(op["role"] == op["surname"] == op["given"] == "" for op in ops)
    with pytest.raises(ValueError, match="文献・図・表・注・式"):
        answers.data(links=[("link_citation", "d18", "2001", 1, "B2")])


def test_names():
    [op] = _ops(answers.answer(names=[("d2", "試験", "六郎", "英文の著者名と照らした")]))
    assert (op["op"], op["src"], op["surname"], op["given"], op["reason"], op["confidence"]) == (
        "split_name", "d2", "試験", "六郎", "英文の著者名と照らした", answers.DEFAULT_CONFIDENCE)
    assert op["text"] == op["target"] == op["role"] == ""


def test_style_fixes():
    [op] = _ops(answers.answer(style_fixes=[("d9", "sec2", "番号の形", "低")]))
    assert (op["op"], op["src"], op["role"], op["reason"], op["confidence"]) == ("set_role", "d9", "sec2", "番号の形", "低")


def test_notes():
    assert parse_response(answers.answer(notes=["番号が飛んでいる", "注 3 は参照されていない"]))["notes"] == [
        "番号が飛んでいる", "注 3 は参照されていない"]


def test_operation_order_and_all_fields():
    """operations は links・names・boundaries・style_fixes の順（それぞれの中は渡した順）。どの操作も、今の操作の項目をすべて持つ。"""
    data = answers.data(style_fixes=[("d9", "quote")], boundaries=[("d40", "注の始まり"), ("d41", "注の続き")],
                        names=[("d2", "試験", "六郎")], links=[("文献", "d18", "2001", 1, "B2")])
    assert [(op["op"], op["src"]) for op in data["operations"]] == [
        ("link_citation", "d18"), ("split_name", "d2"), ("set_role", "d40"), ("set_role", "d41"), ("set_role", "d9")]
    assert all(set(op) == set(OP_SCHEMA["required"]) for op in data["operations"])
    assert _ops(json.dumps(data, ensure_ascii=False)) == data["operations"]


def test_base_answer_is_extended():
    """base（回答の文字か dict）の一覧の後ろに足す。base は変えない。"""
    base = answers.answer(placements=[("s1", "d20")], notes=["前の気づき"])
    text = answers.answer(base=base, links=[("図", "d23", "見開き", 1, "F2")], notes=["気づき"])
    data = json.loads(text)
    assert [pl["float"] for pl in data["placements"]] == ["s1"]
    assert [op["op"] for op in data["operations"]] == ["link_figure"] and data["notes"] == ["前の気づき", "気づき"]
    assert json.loads(base)["operations"] == []


def test_wrong_item_length_is_refused():
    with pytest.raises(ValueError, match="項目の数"):
        answers.data(placements=[("s1",)])
    with pytest.raises(ValueError, match="項目の数"):
        answers.data(names=[("d2", "試験", "六郎", "理由", "高", "余分")])
