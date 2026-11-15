"""W8 の残りの小さな指摘 6 件の直し（点検 review14 の最後の確かめの minor）。内容は架空。本物の API は呼ばない。

- 1: PDF を見た回答で 2 段の図形が機械的な位置のまま残っても、済みの行がそれを言う。
- 2: page のない指定を不採用にするとき、理由に「ページ（0）」と書かない。
- 3: fallback の部があれば、応答のモデル名が指定と同じでも記録する。
- 4: 位置を聞く図形と 2 段の図形の両方があるとき、PDF を見せる文を重ねない。
- 5: 見出しの「（残り n 個）」は数え方を変えず、2 段の図形の数を文で添える。
- 6: することの一覧の行の括弧を 2 つ続けない。
"""
import json
import types

from conftest import CELLS, FLOAT
from jasme_jats import ai_assist, report
from jasme_jats.ai_assist import WIDE_NOPAGE_WHY, WIDE_PAGE_WHY
from jasme_jats.pipeline import Options, _mechanical, convert
from test_ai_pdf import make_pdf
from test_ai_pdf_seen import pages_of
from test_ai_review13 import _fake_claude, api_opts, fake_api, finish
from test_ai_wide import _answer, _target


def test_done_row_tells_wide_float_left_mechanical(journal, meta, tmp_path, monkeypatch):
    """1・2: PDF を見た回答でも、2 段の図形への指定のページが違う（またはない）と機械的な位置のままで、済みの行がそれを言う。
    ページがないときの理由は「ページ（0）」と書かない。"""
    _, plan, _ = _mechanical(CELLS, journal)
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    pages_of(plan, {"s1": 1}, 2, monkeypatch)
    base = convert(CELLS, meta, journal, Options(out_dir=tmp_path / "base", ai_mode="manual"))
    resp = json.loads(_answer(CELLS, [("s1", _target(base.plan, "s1"))], pages=2))
    resp["placements"][0]["page"] = 2
    res = convert(CELLS, meta, journal, Options(out_dir=tmp_path / "bad", ai_mode="manual",
                                                ai_response=json.dumps(resp, ensure_ascii=False), pdf_path=pdf))
    assert [w for _, w in res.ai.rejected] == [WIDE_PAGE_WHY.format(fid="s1", page=2, found=1)]
    fin = finish(res)
    assert fin.done and "機械的な位置のまま" in fin.checklist and "）（" not in fin.checklist
    assert fin.checklist == "- [x] AI の回答を反映した（2 章。ほかに、2 段にまたがる図形 2 個（" + fin.checklist.split("（", 2)[2]
    # ページがない指定
    resp["placements"][0]["page"] = 0
    res = convert(CELLS, meta, journal, Options(out_dir=tmp_path / "nopage", ai_mode="manual",
                                                ai_response=json.dumps(resp, ensure_ascii=False), pdf_path=pdf))
    [(_, why)] = res.ai.rejected
    assert why == WIDE_NOPAGE_WHY.format(fid="s1", found=1) and "ページ（0）" not in why


def test_fallback_part_is_recorded_even_when_the_model_name_is_the_same(monkeypatch):
    """3: content に fallback の部があれば、応答のモデル名が指定と同じでも、切り替わったことを記録する（名前だけ同じで切り替わらないときは記録しない）。"""
    text = types.SimpleNamespace(type="text", text="{}")
    _fake_claude(monkeypatch, [text, types.SimpleNamespace(type="fallback"), text], "claude-opus-5")
    out = ai_assist.call_api("s", "d", None, model="claude-opus-5", api_key="t")
    assert "安全上の判定で断られ、別のモデルに切り替わった" in out.model_note and "claude-opus-5" in out.model_note
    _fake_claude(monkeypatch, [text], "claude-opus-5")
    out = ai_assist.call_api("s", "d", None, model="claude-opus-5", api_key="t")
    assert out.model_note == ""


def _asked_and_wide(journal, meta, tmp_path, **kw):
    res = convert(FLOAT, meta, journal, Options(out_dir=tmp_path, ai_mode="manual", **kw))
    res.plan.floats["s4"].wide = True        # 機械的に置いた図形 s4 を 2 段にまたがる図形にする（位置を聞く図形は s1〜s3 のまま）
    return res


def test_asked_and_wide_do_not_repeat_the_pdf_sentence_and_count_wide_in_words(journal, meta, tmp_path):
    """4・5: 位置を聞く図形と 2 段の図形の両方があるとき、「PDF を見せると…」の文は 1 回。見出しの残りの数は位置を聞いた図形だけで、
    2 段の図形の数は見出しの文で添える。"""
    res = _asked_and_wide(journal, meta, tmp_path)
    assert res.plan.asked_floats == ["s1", "s2", "s3"] and res.plan.wide_floats == ["s4"]
    fin = finish(res)
    assert fin.box_title == "AI で図・表の位置を合わせる（残り 3 個。ほかに 2 段にまたがる図形 1 個）" and fin.progress == "回答待ち・残り 3 個"
    assert fin.box_detail.count("AI に出版版 PDF を見せると") == 1 and fin.box_intro.count("AI に出版版 PDF を見せると") == 1
    assert "2 段にまたがる図形 1 個（" in fin.box_intro and "機械的に決めた位置に置いています" in fin.box_intro
    # 2 段の図形だけなら、今までどおり PDF を見せる文を添える
    only = convert(CELLS, meta, journal, Options(out_dir=tmp_path / "w", ai_mode="manual"))
    assert finish(only).box_intro.count("出版版と同じ位置に移せます") == 1 and "（残り" not in finish(only).box_title


def test_pdf_unseen_row_has_one_parenthesis(journal, meta, tmp_path, monkeypatch):
    """6: することの一覧の「PDF を見ていない」行の括弧は 1 つ（機械的な位置のままの 2 段の図形は、同じ括弧の中に書く）。"""
    base = convert(CELLS, meta, journal, Options(out_dir=tmp_path / "base", ai_mode="manual"))
    resp = _answer(CELLS, [("s1", _target(base.plan, "s1"))], status="添付なし")
    fake_api(monkeypatch, resp)
    res = convert(CELLS, meta, journal, api_opts(tmp_path / "out", pdf_path=make_pdf(tmp_path / "x.pdf", 1)))
    fin = finish(res)
    assert fin.box_title == report.AI_PDF_TITLE and "）（" not in fin.checklist
    assert "（添付なし。2 章。2 段にまたがる図形 2 個（" in fin.checklist
