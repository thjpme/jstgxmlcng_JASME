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


def test_s4_ai_link_on_the_citation_itself_resolves_it(journal, meta, tmp_path):
    # AI の文献のリンクは年の形の文字にしか付けられないので、番号が年の形（2001）の文献で、番号の位置に付ける
    path = tmp_path / "dup2.docx"
    _article(path, "2001")
    base = convert(path, meta, journal, Options(out_dir=tmp_path / "o0"))
    src = _body_src(base)
    res = _convert(path, meta, journal, tmp_path / "o1", [("文献", src, "2001", 1, "B2")])
    assert res.ai.rejected == [] and len(res.ai.accepted) == 1
    assert _dup(res) == []
    assert "bibr_dup" not in {a.key for a in actions(res)}
