"""AI の回答の守り（修正計画 W8 の前半〈手順 0〜9〉の点検 review12 の指摘を直したもの）。実際の API は呼ばない。

- 区切りの指定 1 つで注・英文要旨の構造が崩れないこと（注の見出しへの区切り、英文要旨の最初の段落への資料の見出し、組み直した後の守り）
- 何も変えない区切り・同じ段落への 2 つの区切りを「直した」と知らせないこと
- AI の文の目印の文字・改行が、知らせの枠やコマンドラインの文を壊さないこと
- 別の論文への回答らしいもの（リンクの文字がほとんど段落に見つからない）を使わないこと（依頼の番号での確かめ〈手順 17〉までの最小の守り）
- API の想定外の例外で変換が止まらないこと
- 記号だけの引用文献（「.」だけの段落）を要確認 style_check に挙げること（文字は変えず、除外もしない）
- 推奨の手順 ai_finish が、要対応・必須の手順より後ろに並ぶこと、図形の数と図・表の名前が食い違わないこと
"""
import json

import answers
import make_fixtures as mf
import pytest
from conftest import FLOAT, FULL, NOTES
from lxml import etree

from jasme_jats import ai_assist, colab, pipeline, report
from jasme_jats.ai_assist import (ABSTRACT_FIRST_WHY, BLANK_ROLE_WHY, SAME_ROLE_WHY, STYLE_ONLY_WHY, TWICE_ROLE_WHY,
                                  parse_response)
from jasme_jats.pipeline import Options, _mechanical, convert
from jasme_jats.report import NEEDS_ACTION, STEP, actions, ai_state

S = mf.S


def _manual(path, resp, meta, journal, out):
    return convert(path, meta, journal, Options(out_dir=out, ai_mode="manual", ai_response=resp))


def _base(path, meta, journal, tmp_path):
    """回答なし（手動・回答待ち）の変換（XML を比べる相手）。"""
    return convert(path, meta, journal, Options(out_dir=tmp_path / "base", ai_mode="manual"))


def _keys(res):
    return [a.key for a in actions(res)]


# ---------------------------------------------------------------------------- 点検:原則 1 注の見出しへの区切り
@pytest.mark.parametrize("kind", ["注の始まり", "注の続き"])
def test_note_heading_boundary_is_a_proposal(kind, journal, meta, tmp_path):
    """注の一覧の見出し「注」（どの注の中の段落でもない）への区切りの指定は、注の区切りの直しにしない（反映すると、手で書いた注が
    すべて引用文献になる）。その段落には指定できない区切りとして不採用になり（BOUNDARY_PLACE_WHY）、XML は回答なしと 1 バイトも同じ。"""
    _, plan, _ = _mechanical(NOTES, journal)
    head = next(s for s, p in plan.paras.items() if p.plain() == "注" and plan.region.get(s) == "fn")
    base = _base(NOTES, meta, journal, tmp_path)
    res = _manual(NOTES, answers.answer(boundaries=[(head, kind)]), meta, journal, tmp_path / "a")
    assert [why for _, why in res.ai.rejected] == [ai_assist.BOUNDARY_PLACE_WHY.format(kind=kind)] and res.ai.boundaries == []
    assert res.xml_path.read_bytes() == base.xml_path.read_bytes()
    assert len(res.plan.fns) == len(base.plan.fns) and "ai_boundary" not in _keys(res)


def test_boundary_that_empties_notes_is_undone(journal, meta, tmp_path, monkeypatch):
    """守り（pipeline.boundary_losses）: 区切りの判定（ai_assist.boundary_problem）をすり抜けて、組み直した後に手で書いた注が 1 つも
    なくなったら、その指定を不採用（BOUNDARY_LOST_WHY）にして組み直す。"""
    _, plan, _ = _mechanical(NOTES, journal)
    head = next(s for s, p in plan.paras.items() if p.plain() == "注" and plan.region.get(s) == "fn")
    base = _base(NOTES, meta, journal, tmp_path)
    monkeypatch.setattr(ai_assist, "boundary_problem", lambda p, plan, role: "")
    monkeypatch.setattr(ai_assist, "boundary_kind", lambda p, plan, role: "注の続き")
    res = _manual(NOTES, answers.answer(boundaries=[(head, "注の続き")]), meta, journal, tmp_path / "a")
    assert [why for _, why in res.ai.rejected] == [pipeline.BOUNDARY_LOST_WHY] and res.ai.boundaries == []
    assert res.xml_path.read_bytes() == base.xml_path.read_bytes()
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid


# ---------------------------------------------------------------------------- 点検:原則 2 英文要旨の最初の段落への資料の見出し
def test_app_heading_on_first_abstract_paragraph_is_rejected(journal, meta, tmp_path, monkeypatch):
    """英文要旨の最初の段落を資料の見出しにすると英文要旨が空になるので断る（ABSTRACT_FIRST_WHY。提案にもしない）。2 段落目からは
    今までどおり資料にできる。判定をすり抜けても、組み直した後に英文要旨が空なら戻す（pipeline.boundary_losses）。"""
    _, plan, _ = _mechanical(FULL, journal)
    first, second = plan.abstract[0].src, plan.abstract[1].src
    base = _base(FULL, meta, journal, tmp_path)
    res = _manual(FULL, answers.answer(boundaries=[(first, "資料の見出し")]), meta, journal, tmp_path / "a")
    assert [why for _, why in res.ai.rejected] == [ABSTRACT_FIRST_WHY] and res.ai.style_fixes == []
    assert res.xml_path.read_bytes() == base.xml_path.read_bytes()
    ok = _manual(FULL, answers.answer(boundaries=[(second, "資料の見出し")]), meta, journal, tmp_path / "b")
    assert [(b.src, b.kind) for b in ok.ai.boundaries] == [(second, "資料の見出し")] and len(ok.plan.abstract) == 1
    monkeypatch.setattr(ai_assist, "boundary_problem", lambda p, plan, role: "")
    res = _manual(FULL, answers.answer(boundaries=[(first, "資料の見出し")]), meta, journal, tmp_path / "c")
    assert [why for _, why in res.ai.rejected] == [pipeline.BOUNDARY_LOST_WHY] and res.ai.boundaries == []
    assert res.xml_path.read_bytes() == base.xml_path.read_bytes() and res.plan.abstract


# ---------------------------------------------------------------------------- 点検:原則 5 何も変えない区切り・同じ段落への 2 つの区切り
def test_noop_blank_and_twice_boundaries_are_not_reported(journal, meta, tmp_path):
    """変換ツールの判断と同じ区切り（最初の注への「注の続き」、注の続きの段落への「注の続き」、注の始まりへの「注の始まり」）と、
    空白だけの段落への区切りは、反映も要確認 ai_boundary への記録もしない。同じ段落への 2 つの区切りは、どちらも使わない。"""
    _, plan, _ = _mechanical(NOTES, journal)
    notes = [fn for fn in plan.fns if not fn.word_note]
    first, second, cont = notes[0].paras[0].src, notes[1].paras[0].src, notes[2].paras[1].src
    blank = next(s for s, p in plan.paras.items() if plan.region.get(s) == "fn" and p.is_blank)
    base = _base(NOTES, meta, journal, tmp_path)
    resp = answers.answer(boundaries=[(first, "注の続き"), (cont, "注の続き"), (second, "注の始まり"), (blank, "注の始まり")])
    res = _manual(NOTES, resp, meta, journal, tmp_path / "a")
    assert [why for _, why in res.ai.rejected] == [SAME_ROLE_WHY, SAME_ROLE_WHY, SAME_ROLE_WHY, BLANK_ROLE_WHY]
    assert res.ai.boundaries == [] and res.ai.style_fixes == [] and "ai_boundary" not in _keys(res)
    assert res.xml_path.read_bytes() == base.xml_path.read_bytes()
    res = _manual(NOTES, answers.answer(boundaries=[(cont, "注の始まり"), (cont, "注の続き")]), meta, journal, tmp_path / "b")
    assert [why for _, why in res.ai.rejected] == [TWICE_ROLE_WHY, TWICE_ROLE_WHY] and res.ai.boundaries == []
    assert res.xml_path.read_bytes() == base.xml_path.read_bytes()


# ---------------------------------------------------------------------------- 点検:原則 3・6 AI の文の目印の文字・改行
@pytest.mark.parametrize("reason", ["a\x00step:bogus\x00b", "a\x00step:images\x00b", "a\n## 14. 偽の章\n- [ ] 偽の手順"])
def test_ai_reason_cannot_break_boxes(reason, journal, meta, tmp_path):
    """AI の根拠の文に画面の操作の目印の文字（U+0000）や改行があっても、知らせの枠・コマンドラインの文を出すときに落ちず、画面の
    案内にも偽の行にも化けない（回答を読むときに制御文字を除き〈ai_assist.strip_controls〉、知らせでは改行を「⏎」にする〈report.ai_text〉）。"""
    _, plan, _ = _mechanical(NOTES, journal)
    cont = [fn for fn in plan.fns if not fn.word_note][2].paras[1].src
    body = next(s for s, p in plan.paras.items() if plan.region.get(s) == "body" and len(p.plain()) > 10)
    resp = answers.answer(boundaries=[(cont, "注の始まり", reason)], style_fixes=[(body, "sec1", reason)])
    res = _manual(NOTES, resp, meta, journal, tmp_path / "a")
    acts = {a.key: a for a in actions(res)}
    assert {"style_check", "ai_boundary"} <= set(acts)
    for key in ("style_check", "ai_boundary"):
        a = acts[key]
        for screen in ("notebook", "app", "cli"):
            for text in (a.box_title, a.box_detail, a.cli):
                out = colab.step_text(text, screen)
                assert "\x00" not in out and "偽の章\n" not in out and colab.STEP_WORDS[screen]["images"] not in out
        assert "\n## 14." not in a.box_detail and "\n## 14." not in a.cli
    colab.result_boxes(res)
    if "\n" in reason:
        assert "⏎## 14. 偽の章⏎" in acts["style_check"].box_detail


def test_parse_response_strips_controls():
    """回答の中の制御文字（タブ・改行・復帰を除く）は、読むときに取り除く（目印の U+0000 も）。"""
    data = parse_response(json.dumps({"placements": [{"float": "s1", "after": "d3", "reason": "x\x00step:y\x00z\x07"}],
                                      "notes": ["a\x00b\tc\nd"]}))
    assert data["placements"][0]["reason"] == "xstep:yz" and data["notes"] == ["ab\tc\nd"]


# ---------------------------------------------------------------------------- 点検:原則 7 API の想定外の例外
def test_unexpected_api_exception_does_not_stop(journal, meta, tmp_path, monkeypatch):
    """call_provider が想定外の例外（SDK の誤りの型でないもの）を出しても、変換は AI を使わないときと同じ形で終わり、状態は「失敗」。
    例外の文は書かず、型の名前だけにする（API キーなどが例外の文に入っていても、2 章・AI判断一覧に出さない。点検 review13 原則 5）。"""
    def boom(*a, **k):
        raise RuntimeError("試験の誤り dummy-secret-value")
    monkeypatch.setattr(pipeline, "call_provider", boom)
    res = convert(NOTES, meta, journal, Options(out_dir=tmp_path / "a", ai_mode="api", ai_api_key="dummy-secret-value"))
    assert ai_state(res) == "失敗" and res.ai.error == "AI の呼び出しで想定外の誤りが起きました（RuntimeError）"
    for path in (res.report_path, res.ai_report_path):
        assert "dummy-secret-value" not in path.read_text(encoding="utf-8")
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    assert "ai_finish" not in [a.key for a in report.blocking(actions(res))]


# ---------------------------------------------------------------------------- 点検:原則 8 style_check の抜粋
def test_style_check_excerpt_has_no_object_mark(journal, meta, tmp_path):
    """要確認 style_check の行の抜粋は、2 章の表と同じく画像・数式の位置の文字（U+FFFC）を含めない。"""
    _, plan, _ = _mechanical(FULL, journal)
    src = next(s for s, p in plan.paras.items() if "￼" in p.plain() and plan.region.get(s) == "body")
    res = _manual(FULL, answers.answer(style_fixes=[(src, "sec1")]), meta, journal, tmp_path / "a")
    a = next(a for a in actions(res) if a.key == "style_check")
    assert "￼" not in a.box_detail and "￼" not in a.cli and "￼" not in a.top
    assert f"{src}（" in a.box_detail


# ---------------------------------------------------------------------------- 点検:回帰 1 記号だけの引用文献
def test_symbol_only_reference_is_listed_in_style_check(journal, meta, tmp_path):
    """引用文献の節の「.」だけの段落は、文字を変えず除外もせず引用文献の 1 件として出し（所有者の決定 5: 除外は Word で直す）、
    要確認 style_check に挙げて Word で消してもらう。AI がなくても出し、推奨の手順 ai_finish を出す条件には数えない。"""
    path = tmp_path / "dot.docx"
    mf.make_article(path, "記号の文献の検証用文書", lambda b: [mf.para(S["sec1"], "１．はじめに"),
                                                           mf.para(S["body"], "架空の主張である（試験，2024）。")],
                    refs=lambda b: [mf.para(S["ref"], ".")])
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "a"))
    dot = next(s for s, p in res.plan.paras.items() if p.plain() == ".")
    assert [(x.kind, x.src) for x in res.plan.style_suspects] == [("ref_symbol", dot)]
    root = etree.parse(str(res.xml_path)).getroot()
    assert [("".join(r.itertext())) for r in root.iter("mixed-citation")][-1] == "."       # 文字は変えない
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    a = next(a for a in actions(res) if a.key == "style_check")
    assert a.level == report.TO_CHECK and "記号だけの段落が、引用文献の 1 件として XML に出ます" in a.box_detail
    assert "Word でこの段落を消す" in a.box_detail and "ai_finish" not in _keys(res)
    # AI の除外の提案は同じ行に添う
    resp = answers.answer(style_fixes=[(dot, "exclude")])
    res = _manual(path, resp, meta, journal, tmp_path / "b")
    [row] = [x for x in report.style_check_rows(res)[0] if x[0] == dot]
    assert "AI の提案: 本文に要らない段落なら、Word で消す" in row[1]


# ---------------------------------------------------------------------------- 点検:利用者向け 3・6 ai_finish の並びと図形の名前
def test_ai_finish_comes_after_blocking_actions(journal, meta, tmp_path):
    """推奨の手順 ai_finish は、要対応と必須の手順（図の画像を入れる）の後ろに並ぶ（画面・コマンドラインの順。14 章と同じ考え方）。"""
    res = convert(FLOAT, meta, journal, Options(out_dir=tmp_path / "a"))
    acts = actions(res)
    keys = [a.key for a in acts]
    i = keys.index("ai_finish")
    assert all(not (a.level == NEEDS_ACTION or (a.level == STEP and a.required)) for a in acts[i + 1:])
    assert "images" in keys and keys.index("images") < i


def test_float_names_count_and_order(journal, meta, tmp_path):
    """図形の数と中の図・表の名前を分けて書く（「図形 3 個（図1・図2・図3・図4）」。名前は番号順）。名前が多ければ「ほか N 個」、
    キャプションのないものは数でまとめる。"""
    res = convert(FLOAT, meta, journal, Options(out_dir=tmp_path / "a"))
    left = res.plan.asked_floats
    assert report.float_phrase(res.plan, left) == "図形 3 個（図1・図2・図3・図4）"
    fin = next(a for a in actions(res) if a.key == "ai_finish")
    assert "図形 3 個（図1・図2・図3・図4）を、結び付いている段落のすぐ後ろに置いている" in fin.checklist


def test_blank_after_paragraph_is_named_by_previous_text(journal, meta, tmp_path):
    """AI が空の段落の後ろを指定したとき、2 章の採用の記録に「段落「」」と書かず、前の文字のある段落の先頭で書く（点検:利用者向け 7）。"""
    path = tmp_path / "blank.docx"
    def parts(b):
        out = mf.float_text_parts(b, down_cm=3)
        return out[:4] + [mf.para(S["body"], "")] + out[4:]
    mf.make_article(path, "空の段落の検証用文書", parts)
    _, plan, _ = _mechanical(path, journal)
    [fid] = plan.asked_floats
    blank = next(s for s, p in plan.paras.items() if plan.region.get(s) == "body" and p.is_blank and not p.textbox_id)
    res = _manual(path, answers.answer(placements=[(fid, blank)]), meta, journal, tmp_path / "a")
    d = res.plan.float_decisions[fid]
    assert "段落「」" not in d.message and f"段落{blank}（空の段落。「以上が図1である。」の次）の後に置いた" in d.message


# ---------------------------------------------------------------------------- 点検 review13 原則 1 対になっていない代理の符号
@pytest.mark.parametrize("where", ["reason", "text", "notes"])
def test_lone_surrogate_in_answer_does_not_stop(where, journal, meta, tmp_path):
    """回答の JSON のエスケープ "\\ud800" は json.loads で読めてしまうが、UTF-8 にできないので、読んだ直後（strip_controls）に除く。
    AI回答.json・レポートを書くときに変換が止まらない（手動・API とも）。"""
    resp = json.loads(answers.answer(links=[("文献", "d18", "2001", 1, "B2")], docx=FULL))
    if where == "notes":
        resp["notes"] = ["\udfff"]
    else:
        resp["links"][0][where] = "x\ud800y" if where == "reason" else "\ud800"
    text = json.dumps(resp)                     # ensure_ascii（"\ud800" のエスケープのまま）
    res = _manual(FULL, text, meta, journal, tmp_path / "m")
    assert res.report_path.exists() and res.fidelity.ok and res.dtd_valid
    for path in (res.report_path, res.ai_report_path):
        path.read_text(encoding="utf-8")
    assert data_has_no_surrogate(parse_response(text))
    if where == "reason":
        assert [op["reason"] for op, _ in res.ai.accepted] == ["xy"]


def data_has_no_surrogate(v) -> bool:
    if isinstance(v, str):
        return not any("\ud800" <= c <= "\udfff" for c in v)
    if isinstance(v, list):
        return all(data_has_no_surrogate(x) for x in v)
    if isinstance(v, dict):
        return all(data_has_no_surrogate(k) and data_has_no_surrogate(x) for k, x in v.items())
    return True


def test_lone_surrogate_in_api_answer_does_not_stop(journal, meta, tmp_path, monkeypatch):
    resp = json.loads(answers.answer(docx=FULL))
    resp["notes"] = ["\ud800"]
    monkeypatch.setattr(pipeline, "call_provider", lambda *a, **k: ai_assist.AIOutcome(
        mode="api", model="m", raw=json.dumps(resp)))
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path / "a", ai_mode="api", ai_api_key="dummy"))
    assert not res.ai.error and res.ai.notes == [] and res.ai_answer_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------- 点検 review13 原則 5 Claude の回答に文字の部分がない
def test_claude_answer_without_text_has_a_reason(monkeypatch):
    """Claude の回答に文字の部分（type が text）がないときは、理由のない「失敗」にしない（call_openai などと同じ文）。"""
    import types
    import anthropic

    class FakeStream:
        def __init__(self, kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_final_message(self):
            return types.SimpleNamespace(stop_reason="end_turn", content=[types.SimpleNamespace(type="thinking")], usage=None)

    class FakeClient:
        def __init__(self, *a, **k):
            self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(stream=lambda **kw: FakeStream(kw)))
            self.messages = self.beta.messages

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    out = ai_assist.call_api("指示", "データ", None, api_key="dummy")
    assert out.raw == "" and out.error == "AI から回答が返ってきませんでした"


# ---------------------------------------------------------------------------- 点検 review13 原則 6 使い回しの説明
def test_reused_answer_is_told_in_ai_finish():
    """前の変換の回答を使って AI を呼ばなかったこと（AIOutcome.reused）は、残っている推奨の手順 ai_finish の枠とコマンドラインの文に
    添える（済んだ手順は枠を出さないので添えない）。"""
    import types
    r = types.SimpleNamespace(ai=types.SimpleNamespace(reused=ai_assist.REUSED_MSG))
    left = report.Action(STEP, "ai_finish", required=False, box_detail="本文。", cli="文。")
    assert report._with_reused(left, r).box_detail == "本文。" + ai_assist.REUSED_MSG
    assert left.cli == "文。" + ai_assist.REUSED_MSG
    done = report.Action(STEP, "ai_finish", required=False, done=True)
    assert report._with_reused(done, r).box_detail == "" and report._with_reused(None, r) is None
    r.ai.reused = ""
    again = report.Action(STEP, "ai_finish", required=False, box_detail="本文。")
    assert report._with_reused(again, r).box_detail == "本文。"
