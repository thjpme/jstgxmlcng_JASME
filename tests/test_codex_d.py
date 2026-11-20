"""外部レビュー R3: PDF に合わせる処理で、波かっこ「{ }」の組の片方だけが直る問題（pdfdocx の BRACKETS・FULL_BRACKETS・
_bracket_partners）。文字はすべて架空。"""
import pytest

import make_fixtures as mf
from jasme_jats.fidelity import source_texts
from jasme_jats.pdfdocx import Fix, _bracket_partners, hold, spread_reasons
from test_pdfmatch import (N10_TAIL, SMALL_FRONT, TALK, body_lines, convert_with_pages, load, n10_pages, para_text,
                           texts)


def _ins(ch):
    """ほかの作成者の変更履歴（w:ins）の中の 1 文字（書き込みの段階で直せない文字）。"""
    return ('<w:ins w:id="5002" w:author="試験" w:date="2026-01-01T00:00:00Z"><w:r><w:t xml:space="preserve">'
            f'{ch}</w:t></w:r></w:ins>')


def _convert(tmp_path, monkeypatch, journal, meta, runs, pdf_text):
    """runs（docx の段落の run の並び）の小さな論文を、その段落が pdf_text の PDF で補う（ルート2）。"""
    def body(b):
        return [mf.para(mf.S["sec1"], "１．はじめに"), mf.para(mf.S["body"], *runs), mf.para(mf.S["body"], TALK)]
    src = tmp_path / "ins.docx"
    mf.make_article(src, "ページ番号の判定の検証用文書", body)
    pages = n10_pages([*SMALL_FRONT, *body_lines(pdf_text), *body_lines(TALK), *N10_TAIL])
    return convert_with_pages(tmp_path, monkeypatch, journal, meta, pages, "pdf", docx=src)


def test_bracket_partners_braces():
    """波かっこも組になる。種類の違うかっこは組にしない。入れ子は内側から。"""
    assert _bracket_partners("a{b}c") == {1: 3, 3: 1}
    assert _bracket_partners("a｛b}c") == {1: 3, 3: 1}                        # 全角・半角の混在でも組
    assert _bracket_partners("{(1)}") == {0: 4, 4: 0, 1: 3, 3: 1}
    assert _bracket_partners("{[(x)]}") == {0: 6, 6: 0, 1: 5, 5: 1, 2: 4, 4: 2}
    assert _bracket_partners("{a)") == {}                                      # 種類の違うかっこは組にしない
    assert _bracket_partners("(a}") == {}
    assert _bracket_partners("[a}") == {}
    # 交差する形は、種類ごとに別々に組になる（S1 の直しで変更。片方を直さなければ、もう片方も直さない側に倒れる）
    assert _bracket_partners("{a(b})") == {0: 4, 4: 0, 2: 5, 5: 2}
    assert _bracket_partners("a{b") == {} and _bracket_partners("a}b") == {}


def test_brace_pair_unit_hold():
    """hold: 波かっこの片方を直さない（内容の違いに続く）と、組のもう片方も直さない。両方直せるときは両方直す。"""
    from jasme_jats.pdfdocx import ADJACENT_REASON, CONTENT_REASON
    text = "集合{整数の組}を考える。"
    o, c = text.index("{"), text.index("}")
    fixes = [Fix("d1", o, o + 1, "｛", "width", "{"), Fix("d1", c, c + 1, "｝", "width", "}")]
    hold(fixes, {"d1": text})
    assert [f.reason for f in fixes] == ["", ""]
    # 片方が書き込みの段階で止まれば、もう片方も止まる（どちらの向きでも）
    a, b = fixes
    a.reason = "直せない文字にかかる"
    assert spread_reasons(fixes)
    assert b.reason.startswith("かっこの組のもう片方の全角・半角の直し「{」→「｛」を直さないので")
    b.reason, a.reason = "直せない文字にかかる", ""
    spread_reasons(fixes)
    assert a.reason.startswith("かっこの組のもう片方の全角・半角の直し「}」→「｝」を直さないので")
    # 一続きの規則: 内容の違いに続いて止めた「}」の組の「{」も止める（離れていても）
    text = "前に {ふくろう} と書いた。"
    o, c = text.index("{"), text.index("}")
    fixes = [Fix("d1", o, o + 1, "｛", "width", "{"), Fix("d1", o + 1, c, "みみずく", "text", "ふくろう"),
             Fix("d1", c, c + 1, "｝", "width", "}")]
    hold(fixes, {"d1": text})
    assert [f.reason for f in fixes] == [ADJACENT_REASON, CONTENT_REASON, ADJACENT_REASON]
    # もともと混ざっている組「{1｝」は片方を直して混ざらなくなるので止めない
    mixed = "集合{1｝を示す。"
    one = [Fix("d1", 2, 3, "｛", "width", "{")]
    hold(one, {"d1": mixed})
    assert one[0].reason == ""
    # 種類の違うかっこ「{…)」は組にならないので、連動しない
    text = "集合{整数の組)を考える。"
    o, c = text.index("{"), text.index(")")
    fixes = [Fix("d1", o, o + 1, "｛", "width", "{"), Fix("d1", c, c + 1, "）", "width", ")")]
    hold(fixes, {"d1": text})
    fixes[0].reason = "直せない文字にかかる"
    spread_reasons(fixes)
    assert fixes[1].reason == ""


def test_route2_brace_pair_held_at_write_stage(journal, meta, tmp_path, monkeypatch):
    """R3: 変更履歴（w:ins）の中の「{」は書き込みの段階で直せない。組の「}」も直さず、補った docx と XML は
    「集合{整数の組}を考える。」のまま（「{整数の組｝」にしない）。"""
    res = _convert(tmp_path, monkeypatch, journal, meta, ["集合", _ins("{"), "整数の組}を考える。"],
                   "集合｛整数の組｝を考える。")
    assert res.fidelity.ok and res.fidelity.final_ok and res.supplement.ok
    held = {(f.old, f.new): f.reason for f in res.docx_fix.skipped}
    assert held[("{", "｛")].startswith("直せない文字")
    assert held[("}", "｝")].startswith("かっこの組のもう片方の全角・半角の直し「{」→「｛」を直さないので")
    assert para_text(source_texts(res.docx_fix.path), "集合") == "集合{整数の組}を考える。"
    assert "集合{整数の組}を考える。" in texts(load(res))


def test_route2_brace_pair_both_fixed(journal, meta, tmp_path, monkeypatch):
    """両方直せるときは、両方「｛｝」に直る。"""
    res = _convert(tmp_path, monkeypatch, journal, meta, ["集合{整数の組}を考える。"], "集合｛整数の組｝を考える。")
    assert res.fidelity.ok and res.fidelity.final_ok and res.supplement.ok
    assert not res.docx_fix.skipped or all(f.old not in "{}" for f in res.docx_fix.skipped)
    assert para_text(source_texts(res.docx_fix.path), "集合") == "集合｛整数の組｝を考える。"
    assert "集合｛整数の組｝を考える。" in texts(load(res))


def test_route2_nested_brace_paren_held(journal, meta, tmp_path, monkeypatch):
    """入れ子「{(…)}」: 内側の「(」が止まれば「)」も止まり、外側の「{」「}」は組どうしで直る。"""
    res = _convert(tmp_path, monkeypatch, journal, meta, ["集合{", _ins("("), "整数)の組}を考える。"],
                   "集合｛（整数）の組｝を考える。")
    assert res.fidelity.ok and res.fidelity.final_ok and res.supplement.ok
    out = para_text(source_texts(res.docx_fix.path), "集合")
    assert out == "集合｛(整数)の組｝を考える。"


def test_route2_mismatched_kinds_not_paired(journal, meta, tmp_path, monkeypatch):
    """種類の違うかっこ「{…)」は組にならない: 「{」が止まっても「)」は直る。"""
    res = _convert(tmp_path, monkeypatch, journal, meta, ["集合", _ins("{"), "整数の組)を考える。"],
                   "集合｛整数の組）を考える。")
    assert res.fidelity.ok and res.fidelity.final_ok and res.supplement.ok
    assert para_text(source_texts(res.docx_fix.path), "集合") == "集合{整数の組）を考える。"
