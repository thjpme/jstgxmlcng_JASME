"""AI の回答の新しい形（修正計画 W8 の 3.4・4.2・手順 10）: 種類ごとの一覧を 1 件ずつ検証し、採用か不採用に記録する。
実際の API は呼ばない。

- 段落の先頭の文字（head・after_head）の確かめ（head_key・head_of・same_head）
- boundaries・links・names・style_fixes の採用と不採用（4.2 の表の 1 行ごと）
- 聞いたのに回答にない図形・テキストボックスの「指定なし」の記録（C079）
- request_id・pdf の写し（確かめは手順 17・22）
- スタイルの提案があってもなくても XML が 1 バイトも違わないこと、AI の位置の指定で画像の置き場所の名前と除外が変わらないこと
"""
import json

import answers
import pytest
from conftest import FLOAT, FULL, NOTES, STRUCTURE

from jasme_jats import ai_assist
from jasme_jats.ai_assist import (AIOutcome, boundary_overrides, head_key, head_of, link_ops, name_ops, parse_response,
                                  read_answer_meta, same_head, style_fixes)
from jasme_jats.model import Atom, Para
from jasme_jats.pipeline import Options, _mechanical, convert


def _manual(path, resp, meta, journal, out):
    return convert(path, meta, journal, Options(out_dir=out, ai_mode="manual", ai_response=resp))


def _data(**kw):
    return parse_response(answers.answer(**kw))


# ---------------------------------------------------------------------------- 先頭の文字
def test_head_of_skips_non_text_and_spaces():
    """head_of: 文字のアトムだけ（数式・画像・脚注の参照を除く。Word の番号は段落の文字でない）をつなぎ、NFKC にして空白
    （全角の空白・改行）を除いた先頭 8 字。文字のない段落は ""。"""
    from jasme_jats.model import ImageRef
    img = ImageRef(rel_id="rId1", target="word/media/a.png", source="drawing", image_id="img1")
    p = Para(src="d1", atoms=[Atom(kind="text", text="　１．"), Atom(kind="math", text=""), Atom(kind="image", text="", image=img),
                               Atom(kind="text", text="はじめ\nに "), Atom(kind="fnref", text="", fn_kind="footnote"),
                               Atom(kind="text", text="本稿は，")], autonum="(1)")
    assert head_of(p) == "1.はじめに本稿"
    assert head_of(Para(src="d2", atoms=[Atom(kind="math", text="")])) == "" and head_of(None) == ""
    assert head_key(" Ａ　b⏎c\t") == "Abc"


def test_same_head_rules():
    """same_head: 同じ正規化で先頭 8 字までを比べ、同じか、4 字以上でツールの head の先頭部分なら合う。空は確かめない。"""
    p = Para(src="d1", atoms=[Atom(kind="text", text="分数の除法の導入では，面積図が")])
    real = head_of(p)
    assert real == "分数の除法の導入"
    for ok in (real, real + "では", "分数の除", "分 数 の 除 法", "", "分数の除法の導入では，面積図"):
        assert same_head(ok, p), ok
    for ng in ("分数の", "分数の割", "数の除法の導入", "面積図が"):
        assert not same_head(ng, p), ng
    assert same_head("何でも", Para(src="d2", atoms=[]))           # 文字のない段落は確かめない


# ---------------------------------------------------------------------------- boundaries
def test_boundaries_kinds_and_heads(journal):
    """boundaries: kind が区切りの語で、その段落に指定できる区切り（boundary_kind）と同じで、head が合うものだけを上書き表に入れる。"""
    _, plan, _ = _mechanical(NOTES, journal)
    notes = [fn for fn in plan.fns if not fn.word_note]
    cont = notes[2].paras[1]
    out = AIOutcome()
    over, ops = boundary_overrides(_data(boundaries=[(cont.src, "注の始まり")]), plan, out)
    assert over == {cont.src: "fn_start"} and [op["src"] for op in ops] == [cont.src] and out.rejected == []
    for kind, head, why in (("資料の本文", "", ai_assist.BOUNDARY_PLACE_WHY.format(kind="資料の本文")),   # 注の段落に資料の語
                            ("fn_start", "", ai_assist.BOUNDARY_KIND_WHY.format(kind="fn_start")),      # 中の名前は使えない
                            ("注の始まり", "違う段落の先頭", "と合わない")):
        out = AIOutcome()
        item = dict(answers.boundary(cont.src, "注の始まり", head=head), kind=kind)
        over, ops = boundary_overrides(parse_response(json.dumps({"boundaries": [item]}, ensure_ascii=False)), plan, out)
        assert over == {} and ops == [] and out.boundaries == [] and why in out.rejected[0][1], kind
    out = AIOutcome()
    assert boundary_overrides(_data(boundaries=[("d999", "注の始まり")]), plan, out)[0] == {}
    assert out.rejected[0][1] == "段落 d999 が存在しない"
    # head が合えば使う（AI が短く書いた head も）
    out = AIOutcome()
    over, _ = boundary_overrides(parse_response(json.dumps({"boundaries": [answers.boundary(
        cont.src, "注の始まり", head=head_of(cont)[:5])]}, ensure_ascii=False)), plan, out)
    assert over == {cont.src: "fn_start"}


# ---------------------------------------------------------------------------- links・names
def test_links_head_and_kind(journal, meta, tmp_path):
    """links: head が段落の先頭の文字と合わない指定・知らない kind は不採用（段落の文字との照合は apply_ops）。合えば反映する。"""
    _, plan, _ = _mechanical(FULL, journal)
    p = plan.paras["d18"]
    out = AIOutcome()
    data = parse_response(json.dumps({"links": [
        answers.link("文献", "d18", "2001", 1, "B2", head="別の段落の先頭"), dict(answers.link("文献", "d18", "2001", 1, "B2"), kind="引用"),
        answers.link("文献", "d18", "2001", 1, "B2", head=head_of(p))], "request_id": answers.THIS_REQUEST}, ensure_ascii=False))
    ops = link_ops(data, plan, out)
    assert [op["op"] for op in ops] == ["link_citation"] and len(out.rejected) == 2
    assert out.rejected[0][1].startswith("head「別の段落の先頭」が段落 d18 の先頭の文字") and out.rejected[1][1].startswith("kind「引用」は")
    res = _manual(FULL, json.dumps(data, ensure_ascii=False), meta, journal, tmp_path)
    assert [(op["text"], op["target"]) for op, _ in res.ai.accepted] == [("2001", "B2")] and len(res.ai.rejected) == 2


def test_names_only_listed(journal, meta, tmp_path):
    """names: 依頼文に挙げた和文の氏名（姓と名を分けられなかった・境目を推定した）だけを使う（C043）。挙げていない氏名は不採用。"""
    _, plan, _ = _mechanical(FULL, journal)
    resp = answers.answer(names=[("d11", "研究", "次郎"), ("d7", "数学", "太郎")])
    res = _manual(FULL, resp, meta, journal, tmp_path / "a")
    assert [(op["src"], why) for op, why in res.ai.rejected] == [("d7", ai_assist.NAME_UNLISTED_WHY)]
    assert [op["src"] for op, _ in res.ai.accepted] == ["d11"]
    out = AIOutcome()
    info = type("Info", (), {"unsplit_names": [("d11", "研究次郎", "ja"), ("d30", "KENKYU", "en")], "name_splits": []})()
    assert ai_assist.asked_names(info) == {"d11"}
    assert [op["src"] for op in name_ops(_data(names=[("d11", "研究", "次郎"), ("d30", "KEN", "KYU")]), plan, out, info)] == ["d11"]


# ---------------------------------------------------------------------------- style_fixes
def test_style_fixes_rules(journal):
    """style_fixes: 段落があり head が合い、verdict が「直す」か「このまま」。知らないスタイル名は捨てて how だけを使い（how も空なら
    不採用）、同じ段落の 2 件目は不採用。「このまま」は how がなくてよい。"""
    _, plan, _ = _mechanical(FULL, journal)
    base = dict(answers.style_fix("d46", "sec1"))
    items = [base,                                                               # 採用（スタイル名つき）
             dict(base, src="d18", style="架空のスタイル", how="Word で段落を分ける"),   # 知らないスタイル名は捨てる
             dict(base, src="d20", style="架空のスタイル", how=""),                 # how も空: 不採用
             dict(base, src="d46", how="2 件目"),                                   # 同じ段落の 2 件目: 不採用
             dict(base, src="d21", verdict="このまま", style="", how=""),          # 「このまま」
             dict(base, src="d22", verdict="直したい"),                             # verdict の語でない
             dict(base, src="d999")]
    out = AIOutcome()
    style_fixes(parse_response(json.dumps({"style_fixes": items}, ensure_ascii=False)), plan, out, journal)
    assert [(f.src, f.role, f.style, f.how, f.verdict) for f in out.style_fixes] == [
        ("d46", "sec1", "章見出し", "Word で段落のスタイルを「章見出し」にする", "直す"),
        ("d18", "", "", "Word で段落を分ける", "直す"), ("d21", "", "", "", "このまま")]
    assert [op["src"] for op, _ in out.rejected] == ["d20", "d46", "d22", "d999"]
    assert [why for _, why in out.rejected][:2] == [ai_assist.STYLE_EMPTY_WHY, ai_assist.STYLE_TWICE_WHY]
    # head が合わない提案は不採用
    out = AIOutcome()
    style_fixes(parse_response(json.dumps({"style_fixes": [dict(base, src="d18", head="違う段落の先頭")]}, ensure_ascii=False)),
                plan, out, journal)
    assert out.style_fixes == [] and "と合わない" in out.rejected[0][1]
    # style だけで how が空なら、スタイル名から直し方を作る
    out = AIOutcome()
    style_fixes(parse_response(json.dumps({"style_fixes": [dict(base, how="")]}, ensure_ascii=False)), plan, out, journal)
    assert out.style_fixes[0].how == "Word で段落のスタイルを「章見出し」にする"


def test_style_fixes_do_not_change_xml(journal, meta, tmp_path):
    """スタイルの提案（style_fixes）があってもなくても、XML は 1 バイトも違わない（所有者の決定 5）。"""
    none = _manual(STRUCTURE, answers.answer(), meta, journal, tmp_path / "none")
    _, plan, _ = _mechanical(STRUCTURE, journal)
    body = [s for s in plan.body_seq if plan.paras[s].plain().strip()]
    res = _manual(STRUCTURE, answers.answer(style_fixes=[(body[0], "quote"), (body[1], "exclude"), (body[2], "sec2")]),
                  meta, journal, tmp_path / "fix")
    assert len(res.ai.style_fixes) == 3 and res.xml_path.read_bytes() == none.xml_path.read_bytes()


# ---------------------------------------------------------------------------- 指定なし・request_id・pdf
def test_missing_placements_are_recorded(journal, meta, tmp_path):
    """聞いたのに回答にない図形は「指定なし」（NO_PLACEMENT_WHY）として不採用の一覧に載り、3 章の理由は「指定がなかった」のまま。
    AIOutcome.asked に聞いた図形の ID が入る。途中で切れた回答には記録しない。"""
    res = _manual(FLOAT, answers.answer(placements=[("s1", "d17")]), meta, journal, tmp_path / "a")
    assert res.ai.asked == ["s1", "s2", "s3"]
    assert [(op["src"], why) for op, why in res.ai.rejected] == [("s2", ai_assist.NO_PLACEMENT_WHY),
                                                                 ("s3", ai_assist.NO_PLACEMENT_WHY)]
    rows = [u[3] for u in res.unresolved_after if u[0] == "float"]
    assert len(rows) == 2 and all(r.endswith("。AI の回答に、この図表の位置の指定がなかった") for r in rows)
    text = answers.answer(placements=[("s1", "d17"), ("s2", "d26")])
    res = _manual(FLOAT, text[:text.index('"float": "s2"') + 20], meta, journal, tmp_path / "cut")
    assert res.ai.partial and not any(why == ai_assist.NO_PLACEMENT_WHY for _, why in res.ai.rejected)


def test_request_id_and_pdf_are_copied():
    out = AIOutcome()
    read_answer_meta(parse_response(json.dumps(dict(answers.empty(), request_id="R-AAAA-BBBB",
                                                    pdf={"status": "見た", "pages": 12}))), out)
    assert (out.answered_id, out.pdf_status, out.pdf_pages) == ("R-AAAA-BBBB", "見た", 12)
    out = AIOutcome()
    read_answer_meta(parse_response(json.dumps(dict(answers.empty(), request_id=5, pdf={"status": "たぶん", "pages": "12"}),
                                               ensure_ascii=False)), out)
    assert (out.answered_id, out.pdf_status, out.pdf_pages) == ("", "添付なし", 0)
    out = AIOutcome()
    read_answer_meta(parse_response(json.dumps({"links": []})), out)
    assert (out.answered_id, out.pdf_status, out.pdf_pages) == ("", "", 0)


def test_ai_placement_keeps_slot_names_and_exclusions(journal, meta, tmp_path):
    """AI の位置の指定の前後で、画像の置き場所の名前と除外の記録が変わらない（位置だけが変わる。修正計画 W8 の 2 章の 7）。"""
    none = _manual(FLOAT, None, meta, journal, tmp_path / "none")
    res = _manual(FLOAT, answers.answer(placements=[("s1", "d17"), ("s2", "d26"), ("s3", "d23")]), meta, journal, tmp_path / "ai")
    assert res.plan.unplaced_floats == [] and none.plan.unplaced_floats == ["s1", "s2", "s3"]
    assert sorted(s.key for s in res.plan.slots) == sorted(s.key for s in none.plan.slots)
    assert sorted((e.src, e.reason) for e in res.plan.exclusions) == sorted((e.src, e.reason) for e in none.plan.exclusions)


@pytest.mark.parametrize("text, why", [
    ('{"operations": [], "placements": [], "notes": []}', "古い形式です"),
    ('{"placements": [{"float": "＜s1 など＞", "after": "d3"}]}', "見本と同じ内容の項目が 1 件"),
])
def test_old_and_sample_answers_fail_conversion(text, why, journal, meta, tmp_path):
    """前の形の回答・見本の写しは回答ごと断り、AI の仕上げは「失敗」（変換は AI を使わないときと同じに終わる）。"""
    from jasme_jats.report import actions, ai_state
    res = _manual(FLOAT, text, meta, journal, tmp_path)
    assert why in res.ai.error and ai_state(res) == "失敗" and res.fidelity.ok and res.plan.unplaced_floats == ["s1", "s2", "s3"]
    assert next(a for a in actions(res) if a.key == "ai_finish").failed
