"""外部レビュー R5・R7・R10 の回帰（docs/REVIEW_CODEX_2026-11.md）。

R5: 依頼の番号が (b)（構造の印だけ同じ）のとき、head がない・null の項目も、head が "" と同じに扱われて不採用になる
R7: PDF の 1 ページ目に同じラベルの違う日付が複数あるとき、受付日・受理日を採らない（入力欄に入れない・比べない）
R10: 同じ番号の文献が 2 つ以上あるとき、本文の「[n]」を結ばずに未解決（ambiguous）に記録し、要確認 bibr_dup で知らせる
"""
import json
from types import SimpleNamespace

import pytest

import answers
from conftest import FLOAT, FULL
from jasme_jats import ai_assist
from jasme_jats.ai_assist import CARRIED_NO_HEAD_WHY
from jasme_jats.config import ArticleMeta, JournalConfig
from jasme_jats.model import Atom, Para
from jasme_jats.pdfbiblio import biblio_from_pages, biblio_inputs, fill_missing, mismatches
from jasme_jats.pipeline import _mechanical
from jasme_jats.refparse import DUP_NUMBER_DETAIL, link_numeric
from jasme_jats.report import _bibr_dup_action
from test_ai_stamp import _manual, edited_docx

J = JournalConfig.load()


# ---------------------------------------------------------------------------- R5
@pytest.mark.parametrize("how", ["missing", "null", "empty"])
def test_r5_b_answer_without_head_is_rejected(how, journal, meta, tmp_path):
    """(b) 完全な見本の d18 の前に段落を足し、足す前の依頼文への links の回答を入れる。head が "" でも、キーがなくても、
    null でも、段落の ID がずれていないか確かめられないので CARRIED_NO_HEAD_WHY で不採用になる（新しい d18 にリンクを付けない）。"""
    resp = json.loads(answers.answer(links=[("文献", "d18", "2001", 1, "B2")], docx=FULL))
    link = resp["links"][0]
    if how == "missing":
        link.pop("head", None)
    elif how == "null":
        link["head"] = None
    else:
        link["head"] = ""
    _, plan0, _ = _mechanical(FULL, journal)
    new = edited_docx(FULL, tmp_path / "full.docx", plan0.paras["d18"].text_only()[:12], "別の箇所の2001について述べる。")
    res = _manual(new, json.dumps(resp, ensure_ascii=False), meta, journal, tmp_path / "o")
    assert res.ai.accepted == []
    assert [why for _, why in res.ai.rejected] == [CARRIED_NO_HEAD_WHY]
    assert res.ai.carried == ai_assist.CARRIED_MSG.format(n=1, m=0)        # 確かめていない項目を「確かめられた」に数えない


# ---------------------------------------------------------------------------- R7
def page1(body="", footer="2025年6月1日投稿受付\n2025年11月20日採用決定"):
    return f"全国数学教育学会誌\n数学教育学研究 第 99 巻 第 1 号 2030 pp.11〜24\n論文題目\n{body}\n{footer}"


def test_r7_two_different_received_dates_are_not_taken():
    b = biblio_from_pages([page1("先行研究Ａには2020年1月1日投稿受付と記されている。")], J)
    assert b.received == "" and b.accepted == "2025-11-20" and b.ambiguous == ("received",)
    assert "received" not in biblio_inputs(b)
    # 入力欄の空きも埋めない
    out, filled = fill_missing({}, b)
    assert "received" not in out and "受付日" not in filled
    # 入力があれば、比べられなかったことを meta_pdf の経路（mismatches）で知らせる。受理日は今までどおり比べる
    meta = ArticleMeta.from_dict({"received": "2025-06-01", "accepted": "2025-11-20"})
    ms = mismatches(meta, b)
    assert [m[0] for m in ms] == ["受付日"] and ms[0][1] == "2025-06-01" and "複数" in ms[0][2]
    # 入力が空なら何も言わない（日付の未入力は meta_dates が知らせる）
    assert mismatches(ArticleMeta.from_dict({}), b) == []


def test_r7_same_value_repeated_or_single_is_taken():
    b = biblio_from_pages([page1("2025年6月1日投稿受付（再掲）")], J)           # 同じ値が複数回
    assert (b.received, b.ambiguous) == ("2025-06-01", ())
    b = biblio_from_pages([page1()], J)                                        # 1 つだけ
    assert (b.received, b.accepted, b.ambiguous) == ("2025-06-01", "2025-11-20", ())


def test_r7_revised_and_received_labels_stay_distinct():
    b = biblio_from_pages([page1(footer="2025年6月1日投稿受付\n2025年9月3日再投稿受付\n2025年11月20日採用決定")], J)
    assert (b.received, b.revised, b.accepted, b.ambiguous) == ("2025-06-01", "2025-09-03", "2025-11-20", ())
    # 再投稿受付が 2 つ違っても、投稿受付には影響しない
    b = biblio_from_pages([page1("2020年1月1日再投稿受付", "2025年6月1日投稿受付\n2025年9月3日再投稿受付")], J)
    assert (b.received, b.revised, b.ambiguous) == ("2025-06-01", "", ("revised",))


# ---------------------------------------------------------------------------- R10
def _para(src, text):
    return Para(src=src, atoms=[Atom("text", text)])


def _ref(rid, number):
    return SimpleNamespace(rid=rid, parsed={"number": number}, para=_para("r" + rid, f"[{number}] 文献"))


def _run(refs):
    body = _para("d1", "[1]を参照。[2]も参照。")
    plan = SimpleNamespace(refs=refs)
    linker = SimpleNamespace(unresolved=[], count={"bibr": 0})
    link_numeric(plan, linker, [(body, "body")])
    return body, linker


def test_r10_duplicate_number_is_not_linked_but_recorded():
    body, linker = _run([_ref("B2", 1), _ref("B3", 1), _ref("B4", 2)])
    rids = [a.link.attrs["rid"] for a in body.atoms if a.link and a.link.kind == "xref"]
    assert rids == ["B4"]                                           # [2] は結ばれ、[1] は結ばれない
    assert linker.count["bibr"] == 1
    [u] = linker.unresolved
    assert (u.kind, u.src, u.text, u.ref_kind, u.year) == ("bibr", "d1", "[1]", "ambiguous", "1")
    assert u.detail.startswith(DUP_NUMBER_DETAIL) and "B2" in u.detail and "B3" in u.detail
    # 要確認 bibr_dup で知らせる
    act = _bibr_dup_action(SimpleNamespace(unresolved_after=linker.unresolved))
    assert act.key == "bibr_dup" and act.level == "要確認" and "[1]" in act.top and act.checklist and act.cli
    # 重複がなければ知らせない
    body, linker = _run([_ref("B2", 1), _ref("B4", 2)])
    assert linker.unresolved == [] and linker.count["bibr"] == 2
    assert _bibr_dup_action(SimpleNamespace(unresolved_after=linker.unresolved)) is None
    # 著者・年の曖昧さ（同じ ref_kind "ambiguous"）は、この知らせに入らない
    assert _bibr_dup_action(SimpleNamespace(unresolved_after=[("bibr", "d1", "山田（2020）", "同じ著者・同じ年の文献が複数あり")])) is None
