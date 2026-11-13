"""AI が出版版 PDF を見て答えたかのツールの確かめ（ai_assist.pdf_seen。修正計画 W8 の 4.4・手順 22）と、それによる推奨の手順
ai_finish の済み・未済み、位置の決め方の列（PLACE_JA の ai_pdf・ai_layout）、2 章の概要の表。PDF の文字は pdfmatch.extract_pages を差し
替える（内容は架空）。"""
import json

import pytest

import answers
from conftest import FLOAT, FULL, PLACE
from jasme_jats import report
from jasme_jats.ai_assist import PDF_SEEN_OK, AIOutcome, pdf_seen
from jasme_jats.pipeline import Options, _mechanical, convert
from jasme_jats.report import actions
from jasme_jats.structure import PLACE_JA, figure_place
from test_floats import src_of


def pages_of(plan, fids_pages, total, monkeypatch):
    """図形 fid のキャプションの文字を指定のページ（1 から）に書いた PDF のページの文字を、pdfmatch.extract_pages に差し替える。
    fids_pages は {fid: ページ, ...}（ページが複数の list ならそのすべてに書く）。"""
    from jasme_jats import ai_assist, pdfmatch
    texts = [["" for _ in range(total)]][0]
    for fid, pg in fids_pages.items():
        for q in [pg] if isinstance(pg, int) else pg:
            texts[q - 1] += " ".join(ai_assist.float_caption_texts(plan.floats[fid])[:1]) + " 本文の続き "
    monkeypatch.setattr(pdfmatch, "extract_pages", lambda path: list(texts))


def place_answer(plan, pages=None, basis="PDF", status="見た", total=0):
    """PLACE の 4 つの図形を結び付いた段落の後ろと答える回答。pages は {fid: ページ}（placements の page）。"""
    d = answers.data(placements=[(fid, plan.floats[fid].float.anchor_src) for fid in ("s1", "s2", "s3")]
                     + [("s4", src_of(plan, "この段落に図3と図2"))])
    for pl in d["placements"]:
        pl["basis"] = basis
        pl["page"] = (pages or {}).get(pl["float"], 0)
    d["pdf"] = {"status": status, "pages": total}
    return json.dumps(d, ensure_ascii=False)


def run(journal, meta, tmp_path, resp, pdf=None):
    return convert(PLACE, meta, journal, Options(out_dir=tmp_path, ai_mode="manual", ai_response=resp,
                                                  pdf_path=pdf))


def finish(res):
    return {a.key: a for a in actions(res)}["ai_finish"]


def test_pdf_seen_of_each_answer(journal, meta, tmp_path, monkeypatch):
    """4.4 の表の 1 行ごと。"""
    _, plan, _ = _mechanical(PLACE, journal)
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    fids = ["s1", "s2", "s3", "s4"]
    where = dict(zip(fids, (1, 2, 3, 3)))

    def seen(pages=None, pdf_path=pdf, mode="manual", sent="pdf", status="見た", total=3):
        res = run(journal, meta, tmp_path / "r", place_answer(plan, pages=where, total=total, status=status))
        out = AIOutcome(mode=mode, pdf_status=status, pdf_pages=total, pdf_sent=sent)
        return pdf_seen(out, res.plan, pdf_path)

    # 回答に pdf がなければ ""。添付なし・別の論文は確かめずにそのまま
    assert pdf_seen(AIOutcome(), plan, pdf) == ("", "")
    assert seen(status="添付なし") == ("添付なし", "") and seen(status="別の論文") == ("別の論文", "")
    # API で PDF を渡していない
    state, note = seen(mode="api", sent="")
    assert state == "合わない（PDF を渡していない）" and "渡していない" in note
    # ツールに PDF がない・ページを数えられない
    assert seen(pdf_path=None)[0] == "見た（確かめられない）"
    monkeypatch.setattr("jasme_jats.pdfmatch.extract_pages", lambda p: (_ for _ in ()).throw(RuntimeError("x")))
    assert seen()[0] == "見た（確かめられない）"
    # ページ数
    pages_of(plan, {}, 4, monkeypatch)
    state, note = seen(total=3)
    assert state == "合わない（ページ数）" and "AI の答えは 3 ページ、この PDF は 4 ページ" in note
    # 図のページ: ページ数が合い、キャプションが 1 ページだけに見つかる図形の page が合う
    pages_of(plan, where, 3, monkeypatch)
    assert seen() == ("見た", "")
    # AI の答えのページが半分に満たない
    assert seen(pages=None)[0] == "見た"
    res = run(journal, meta, tmp_path / "r2", place_answer(plan, pages={f: 1 for f in fids}, total=3))
    state, note = pdf_seen(AIOutcome(mode="manual", pdf_status="見た", pdf_pages=3), res.plan, pdf)
    assert state == "合わない（図のページ）" and "合ったのは" in note
    # キャプションが 2 ページに見つかる図形は比べない（比べられる図形がなければ、ページ数だけで決める）
    pages_of(plan, {f: [1, 2] for f in fids}, 3, monkeypatch)
    assert pdf_seen(AIOutcome(mode="manual", pdf_status="見た", pdf_pages=3), res.plan, pdf) == ("見た", "")


def test_unseen_answer_leaves_ai_finish(journal, meta, tmp_path):
    """位置を聞く図形があるとき、PDF を見ていない回答（添付なし・別の論文・合わない）は、位置を反映しても手順が残る。
    回答の位置はそのまま使う（図形の mode は ai）。"""
    _, plan, _ = _mechanical(PLACE, journal)
    for status, word in (("添付なし", "見ていない回答でした"), ("別の論文", "別の論文だと答えました")):
        res = run(journal, meta, tmp_path / status, place_answer(plan, status=status))
        assert res.plan.answered_floats and not res.plan.unplaced_floats
        assert report.ai_state(res) == "済み" and res.ai.pdf_seen == status
        assert report.pdf_unseen(res) and not report.ai_done(res)
        fin = finish(res)
        assert (fin.done, fin.failed, fin.required) == (False, False, False)
        assert fin.box_title == report.AI_PDF_TITLE and word in fin.box_detail
        assert "AI の回答で図・表 4 個の位置を決めましたが" in fin.box_detail and report.step("repaste") in fin.box_detail
        assert fin.progress == f"済み・PDF {status}" and "手順（推奨）" in fin.cli
        assert res.ai.pdf_seen in report.ai_summary(res)
        assert "PDF を見たか" in res.report_path.read_text(encoding="utf-8")
    # ページ数が合わない: 理由を添える
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    import jasme_jats.pdfmatch as pm
    old, pm.extract_pages = pm.extract_pages, lambda p: ["a", "b"]
    try:
        res = run(journal, meta, tmp_path / "bad", place_answer(plan, total=5), pdf=pdf)
    finally:
        pm.extract_pages = old
    assert res.ai.pdf_seen == "合わない（ページ数）" and not report.ai_done(res)
    assert "AI の答えは 5 ページ、この PDF は 2 ページ" in finish(res).box_detail
    assert "別の論文の PDF を添付していないか" in finish(res).box_detail


def test_seen_answer_finishes(journal, meta, tmp_path):
    """見た回答（ツールに PDF がないときは「見た（確かめられない）」）なら手順が済み、14 章の行は PDF を見たと書く。"""
    _, plan, _ = _mechanical(PLACE, journal)
    res = run(journal, meta, tmp_path, place_answer(plan))
    assert res.ai.pdf_seen in PDF_SEEN_OK == ("見た", "見た（確かめられない）") and res.ai.pdf_seen == "見た（確かめられない）"
    assert report.ai_done(res) and finish(res).done
    assert finish(res).checklist.startswith("- [x] AI が出版版 PDF を見て、図・表 4 個の位置を決めた")


def test_no_asked_floats_needs_no_pdf(journal, meta, tmp_path):
    """位置を聞く図形のない原稿では、PDF を見ていない回答でも済み（リンクなどは PDF がなくても決められる）。"""
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, ai_mode="manual", ai_response=answers.answer(docx=FULL)))
    assert res.ai.pdf_seen == "添付なし" and not res.plan.asked_floats and not report.pdf_unseen(res)
    assert report.ai_state(res) == "済み" and report.ai_done(res)


def test_place_column_splits_by_pdf(journal, meta, tmp_path):
    """3 章の「位置の決め方」と図の画像の一覧の列: AI の指定が「AI の指定（PDF を見て）」「AI の指定（PDF なし）」に分かれる。"""
    assert "ai" not in PLACE_JA and PLACE_JA["ai_pdf"] == "AI の指定（PDF を見て）" and PLACE_JA["ai_layout"] == "AI の指定（PDF なし）"
    _, plan, _ = _mechanical(PLACE, journal)
    for basis, key in (("PDF", "ai_pdf"), ("配置の情報", "ai_layout"), ("仮の位置", "ai_layout")):
        res = run(journal, meta, tmp_path / basis, place_answer(plan, basis=basis, pages={"s1": 2}))
        info = res.plan.floats["s1"]
        assert info.mode == "ai" and figure_place(res.plan, "s1") == key
        assert (info.basis, info.page, info.column) == ({"PDF": "pdf", "配置の情報": "layout", "仮の位置": "keep"}[basis], 2, "")
        assert info.confidence == "中"
    text = res.report_path.read_text(encoding="utf-8")
    assert "AI の指定（PDF なし）" in text
