"""機械的に位置を決めた 2 段にまたがる図形は、AI が出版版 PDF を見た回答のときだけ AI の位置を採る（修正計画 W8 の 6.5 の 4。
実験 1 の後の監督の決定）。実際の API は呼ばない。内容はすべて架空。

- 判定は floats.spans_columns（段組みが 2 段以上で、図形の幅が 1 段の幅の 1.3 倍より広い。依頼文の「2 段にまたがる」と同じ）。
- 依頼文では「# PDF を見たときだけ答える図・表」として、位置を聞く図形と分けて挙げる。位置を聞く図形には数えない
  （推奨の手順 ai_finish の残りの数は変えない。2 段の図形があれば ai_finish を出し、PDF を見ていない回答では済みにしない。点検 review14。
  tests/test_ai_review14.py）。
- 採るのは basis が PDF で、AI が PDF を見た回答（pdf_seen が「見た」「見た（確かめられない）」）のときだけ。ほかは機械的な位置のまま
  （2 章の不採用の一覧に理由）。1 段の幅の機械的な図形は、今までどおり変えられない。
"""
import json

import answers
from conftest import CELLS, FLOAT
from lxml import etree

from jasme_jats import ai_assist
from jasme_jats.ai_assist import WIDE_END_WHY, WIDE_HEADING, WIDE_NOT_PDF_WHY, WIDE_UNSEEN_WHY, build_request, request_sections
from jasme_jats.floats import describe, spans_columns
from jasme_jats.model import Float, Layout
from jasme_jats.pipeline import Options, _mechanical, convert
from jasme_jats.report import actions


def _answer(docx, placements, status="見た", basis="PDF", pages=1):
    """docx への回答（依頼の番号と head を埋める）。placements は (図形, after) の組。"""
    req, plan = answers.request_of(docx)
    out = answers.data(placements=placements)
    for pl in out["placements"]:
        pl.update(basis=basis, page=1 if basis == "PDF" else 0, column="両方" if basis == "PDF" else "")
    out["pdf"] = {"status": status, "pages": pages if status == "見た" else 0}
    out["request_id"] = req.stamp
    answers.fill_heads(out, plan)
    return json.dumps(out, ensure_ascii=False)


def _manual(docx, resp, meta, journal, out):
    return convert(docx, meta, journal, Options(out_dir=out, ai_mode="manual", ai_response=resp))


def _fig_after(res, fid):
    """XML の本文で、図 fid の直前の段落の文字。"""
    root = etree.fromstring(res.xml_path.read_bytes())
    prev = ""
    for el in root.find(".//body").iter():
        if el.tag == "p" and el.getparent().tag in ("sec", "body"):
            prev = "".join(el.itertext())
        if el.tag == "fig" and el.get("id") == fid:
            return prev
    return None


def _target(plan, fid):
    """図形 fid のアンカー段落より後ろの、本文の段落（AI の答えに使う。機械的な位置〈アンカー段落の前〉と違う所）。"""
    seq = plan.body_seq
    k = seq.index(plan.floats[fid].float.anchor_src)
    return next(s for s in seq[k + 1:] if plan.paras[s].plain().strip())


def test_spans_columns_rule():
    lay = Layout(columns=2, column_width_cm=8.7, text_width_cm=18.1)
    assert spans_columns(Float(fid="s1", anchor_src="d1", width_cm=16.0), lay)
    assert not spans_columns(Float(fid="s1", anchor_src="d1", width_cm=8.0), lay)
    assert not spans_columns(Float(fid="s1", anchor_src="d1", width_cm=16.0), Layout(columns=1, column_width_cm=18.1))
    # 依頼文の「docx の配置」の「2 段にまたがる」と同じ判定
    assert "（2 段にまたがる）" in describe(Float(fid="s1", anchor_src="d1", width_cm=16.0), lay)
    assert "（1 段の幅）" in describe(Float(fid="s1", anchor_src="d1", width_cm=8.0), lay)


def test_wide_floats_are_listed_apart(journal, meta):
    """2 段にまたがる機械的な図形は、位置を聞く図形に数えず、依頼文の位置の節に「PDF を見たときだけ答える」ものとして分けて挙げる。
    依頼の番号の構造の印には入れる（回答の s1 などが、依頼文と同じ図形を指すかを確かめるため）。"""
    req, plan = answers.request_of(CELLS)
    assert plan.wide_floats == ["s1", "s3"] and plan.asked_floats == [] and plan.floats["s2"].mode == "mechanical"
    assert all(plan.floats[f].mode == "mechanical" and plan.floats[f].wide for f in plan.wide_floats)
    sec = next(s for s in req.sections if s.key == "placements")
    assert sec.parts == {"wide"} and sec.count == ""
    assert ai_assist.PLACEMENTS_WIDE_ONLY in req.instructions and ai_assist.PLACEMENTS_NOPDF not in req.instructions
    assert ai_assist.PLACEMENTS_ASKED not in req.instructions
    assert "\n" + WIDE_HEADING + "\n" in req.data and "# 位置を決める図・表\n" not in req.data
    wide = req.data.split("\n" + WIDE_HEADING + "\n", 1)[1].split("\n\n", 1)[0]
    assert "  今の位置: [" in wide and "（2 段にまたがる）" in wide and "仮の位置" not in wide and "推定" not in wide
    assert req.asked["floats"] == []
    assert [line.split("\t")[1] for line in ai_assist.structure_lines(plan) if line.startswith("s\t")] == ["s1", "s3"]
    # 位置を聞く図形があり、2 段にまたがる機械的な図形がない原稿（FLOAT）の指示は、今までと同じ
    req, plan = answers.request_of(FLOAT)
    assert plan.asked_floats and plan.wide_floats == []
    sec = next(s for s in req.sections if s.key == "placements")
    assert sec.parts == {"asked"} and ai_assist.PLACEMENTS_WIDE_ALSO not in req.instructions
    assert ai_assist.PLACEMENTS_ASKED + ai_assist.PLACEMENTS_TEXT + "\n" + ai_assist.PLACEMENTS_NOPDF in req.instructions


def test_wide_float_takes_pdf_answer(journal, meta, tmp_path):
    """PDF を見た回答（basis PDF。ツールに PDF がないので「見た（確かめられない）」）なら、2 段にまたがる機械的な図形も AI の位置に
    置く。位置を聞く図形には数えないので、推奨の手順 ai_finish の出方は回答なしと同じ。文字・DTD は変わらない。"""
    base = convert(CELLS, meta, journal, Options(out_dir=tmp_path / "base", ai_mode="manual"))
    plan = base.plan
    after = _target(plan, "s1")
    res = _manual(CELLS, _answer(CELLS, [("s1", after)]), meta, journal, tmp_path / "a")
    assert res.ai.pdf_seen == "見た（確かめられない）" and res.ai.rejected == []
    info = res.plan.floats["s1"]
    assert info.mode == "ai" and info.wide and info.basis == "pdf"
    assert res.plan.asked_floats == [] and res.plan.answered_floats == [] and res.plan.wide_floats == ["s1", "s3"]
    assert _fig_after(res, "F1") == res.plan.paras[after].plain() != _fig_after(base, "F1")
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    fin = [a for a in actions(res) if a.key == "ai_finish"]
    assert [a.key for a in actions(base) if a.key == "ai_finish"] == [a.key for a in fin]
    assert all(a.done for a in fin)


def test_wide_float_keeps_mechanical_place_without_pdf(journal, meta, tmp_path):
    """PDF を見ていない回答・basis が PDF でない答え・本文より後ろという答えは使わず、機械的な位置のまま（2 章の不採用に理由）。
    1 段の幅の機械的な図形（s2）は、PDF を見た回答でも今までどおり変えられない。"""
    base = convert(CELLS, meta, journal, Options(out_dir=tmp_path / "base", ai_mode="manual"))
    plan = base.plan
    after = _target(plan, "s1")
    cases = [(dict(status="添付なし"), [("s1", after)], WIDE_UNSEEN_WHY.format(fid="s1", seen="添付なし")),
             (dict(basis="配置の情報"), [("s1", after)], WIDE_NOT_PDF_WHY.format(fid="s1")),
             (dict(), [("s1", "")], WIDE_END_WHY.format(fid="s1")),
             (dict(), [("s2", _target(plan, "s2"))], "図形 s2 は位置を機械的に決めた図表なので、位置を変更できない")]
    for i, (kw, pls, why) in enumerate(cases):
        res = _manual(CELLS, _answer(CELLS, pls, **kw), meta, journal, tmp_path / f"c{i}")
        assert [w for _, w in res.ai.rejected] == [why], (kw, res.ai.rejected)
        assert all(res.plan.floats[f].mode == "mechanical" for f in ("s1", "s2", "s3"))
        assert res.xml_path.read_bytes() == base.xml_path.read_bytes()


def test_wide_floats_do_not_count_in_pdf_page_check(journal, meta):
    """pdf_seen の図のページの確かめは、位置を聞いた図形の指定だけで行う（2 段にまたがる機械的な図形への指定〈wide〉は、PDF を
    見たかで使うかを決めるので数えない）。"""
    _, plan, _ = _mechanical(CELLS, journal)
    out = ai_assist.AIOutcome(mode="manual", pdf_status="見た", pdf_pages=1)
    specs = {"s1": {"after": "", "basis": "pdf", "page": 9, "wide": True, "op": {}}}
    assert ai_assist.pdf_seen(out, plan, None, specs)[0] == "見た（確かめられない）"
    assert ai_assist.wide_rejects(dict(specs), ai_assist.AIOutcome(pdf_seen="見た")) == []
    rest = dict(specs)
    out = ai_assist.AIOutcome(pdf_seen="合わない（ページ数）")
    assert ai_assist.wide_rejects(rest, out) == ["s1"] and rest == {}
    assert out.rejected[0][1] == WIDE_UNSEEN_WHY.format(fid="s1", seen="合わない（ページ数）")


def test_sections_count_wide(journal, meta):
    _, plan, linker = _mechanical(CELLS, journal)
    keys = {s.key: s for s in request_sections(plan)}
    assert "placements" in keys and keys["placements"].parts == {"wide"}
    assert build_request(plan, linker, journal=journal).asked["floats"] == []
