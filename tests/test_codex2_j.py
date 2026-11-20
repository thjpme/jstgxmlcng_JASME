"""外部レビュー 2 回目 S4 の回帰（docs/REVIEW_CODEX_2026-11.md の「2 回目のレビュー」）。

S4: AI のリンクが「その未解決の箇所そのもの」を解決したときだけ、未解決（unresolved_after）から除く。
段落 ID と文字の部分一致だけで除いていたため、同じ段落の別の位置の「1」への注のリンクでも、同じ番号の文献が複数あって結ばなかった
本文の「[1]」の未解決と要確認 bibr_dup が消えた。今は、AI のリンクが付いた文字の範囲と未解決の範囲が重なり、リンクの種類が合うものだけを除く。
"""
import json

import answers
import make_fixtures as mf
from jasme_jats.pipeline import Options, convert
from jasme_jats.report import actions
from make_fixtures import S


def _article(path, n="1"):
    """同じ番号 n の文献が 2 つ。本文の d12 は「[n]を参照。補足するとおりnについて確認した。」（2 回目の n は注の参照のつもり）。"""
    mf.make_article(
        path, "同じ番号の文献の検証用文書",
        lambda b: [mf.para(S["sec1"], "１．はじめに"),
                   mf.para(S["body"], f"[{n}]を参照。補足するとおり{n}について確認した。"),
                   mf.para(S["body"], "別の文", mf.footnote_ref(1), "のある文。")],
        footnotes=[mf.footnote(1, " 架空の注。")],
        refs=lambda b: [mf.para(S["ref"], f"[{n}] 山田一郎（2020）．「甲」．『架空誌』，第1巻，pp.1-2．"),
                        mf.para(S["ref"], f"[{n}] 鈴木二郎（2021）．「乙」．『架空誌』，第2巻，pp.3-4．")])


def _convert(path, meta, journal, out, links):
    from jasme_jats.pipeline import _mechanical
    _, plan, _ = _mechanical(path, journal)
    resp = json.loads(answers.answer(links=links, docx=path))
    return convert(path, meta, journal, Options(out_dir=out, ai_mode="manual", ai_response=json.dumps(resp, ensure_ascii=False)))


def _body_src(res):
    return next(s for s, p in res.plan.paras.items() if p.plain().startswith("[") and "を参照" in p.plain())


def _dup(res):
    return [u for u in res.unresolved_after if u[0] == "bibr" and getattr(u, "ref_kind", "") == "ambiguous"]


def test_s4_ai_link_elsewhere_in_paragraph_keeps_ambiguous_citation(journal, meta, tmp_path):
    path = tmp_path / "dup.docx"
    _article(path)
    base = convert(path, meta, journal, Options(out_dir=tmp_path / "o0"))
    assert len(_dup(base)) == 1
    src = _body_src(base)
    fn = base.plan.fns[0].fid
    plain = base.plan.paras[src].plain()
    assert plain.count("1") == 2, plain
    res = _convert(path, meta, journal, tmp_path / "o1", [("注", src, "1", 2, fn)])
    assert res.ai.rejected == [] and len(res.ai.accepted) == 1
    # 2 回目の「1」（注の参照）に付いたリンクは、1 回目の「[1]」の未解決とは別の箇所
    assert len(_dup(res)) == 1
    assert "bibr_dup" in {a.key for a in actions(res)}


def _art2(path, body):
    mf.make_article(path, "未解決の検証用文書",
                    lambda b: [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], body),
                               mf.para(S["body"], "別の文", mf.footnote_ref(1), "のある文。"),
                               mf.para(S["fig_cap"], "図1　架空の図")],
                    footnotes=[mf.footnote(1, " 架空の注。")],
                    refs=lambda b: [mf.para(S["ref"], "山田一郎（2020）．「甲」．『架空誌』，第1巻，pp.1-2．")])


def _target(base, kind):
    return {"文献": "B1", "図": base.plan.figures[0].fid, "注": base.plan.fns[0].fid}[kind]


def _run2(tmp_path, meta, journal, body, kind, text, occ, name):
    """変換 → 未解決が 1 件あることを確かめ → AI のリンクを入れて変換し直した結果と、元の未解決の種類を返す。"""
    path = tmp_path / f"{name}.docx"
    _art2(path, body)
    base = convert(path, meta, journal, Options(out_dir=tmp_path / f"{name}0"))
    src = next(s for s, p in base.plan.paras.items() if p.plain().startswith(body[:3]))
    before = [u for u in base.unresolved_after if u[1] == src]
    assert len(before) == 1, before
    resp = json.loads(answers.answer(links=[(kind, src, text, occ, _target(base, kind))], docx=path))
    res = convert(path, meta, journal, Options(out_dir=tmp_path / f"{name}1", ai_mode="manual",
                                               ai_response=json.dumps(resp, ensure_ascii=False)))
    assert res.ai.rejected == [] and len(res.ai.accepted) == 1, res.ai.rejected
    return before[0], [u for u in res.unresolved_after if u[1] == src]


def test_s4_bibr_resolved_by_ai_link_on_that_year(journal, meta, tmp_path):
    # 山田（2021）は年が合わず結べない。AI が 2021 を山田の文献にリンクすれば、未解決から消える
    u, after = _run2(tmp_path, meta, journal, "山田（2021）によれば。", "文献", "2021", 1, "bib_same")
    assert u.kind == "bibr" and after == []


def test_s4_bibr_stays_when_ai_links_other_occurrence(journal, meta, tmp_path):
    # 同じ年が同じ段落にもう 1 回ある。AI が別の出現（2 回目）にリンクしても、1 回目の未解決は残る
    u, after = _run2(tmp_path, meta, journal, "山田（2021）によれば2021年に。", "文献", "2021", 2, "bib_other")
    assert u.kind == "bibr" and [x.start for x in after] == [u.start]


def test_s4_bibr_stays_when_ai_links_note_on_same_text(journal, meta, tmp_path):
    # 種類が違うリンク（注）では、文献の未解決は消えない
    u, after = _run2(tmp_path, meta, journal, "山田（2021）によれば。", "注", "2021", 1, "bib_note")
    assert [x.start for x in after] == [u.start]


def test_s4_figure_resolved_by_ai_link_on_that_reference(journal, meta, tmp_path):
    u, after = _run2(tmp_path, meta, journal, "図5に示す。", "図", "図5", 1, "fig_same")
    assert u.kind == "fig" and after == []


def test_s4_figure_stays_when_ai_links_other_occurrence(journal, meta, tmp_path):
    # 図5（未解決）の後ろの別の「5」への図のリンクでは、図5 の未解決は残る
    u, after = _run2(tmp_path, meta, journal, "図5に示す。また5を見る。", "図", "5", 2, "fig_other")
    assert u.kind == "fig" and [x.start for x in after] == [u.start]
