"""外部レビュー 2 回目 S1: 閉じていない開きかっこがあると、組のかっこの片方だけが直る問題（pdfdocx._bracket_partners）。
文字はすべて架空。"""
import make_fixtures as mf
from jasme_jats.fidelity import source_texts
from jasme_jats.pdfdocx import _bracket_partners
from test_codex_d import _convert, _ins
from test_pdfmatch import load, para_text, texts


def test_unclosed_open_is_discarded():
    """閉じていない開きかっこ（後ろに同じ種類の閉じかっこがない）は組にせず、一つ下の開きかっこで続ける。"""
    assert _bracket_partners("(整数 { の組)") == {0: 8, 8: 0}                       # S1 の再現（波かっこ）
    assert _bracket_partners("(整数 [ の組)") == {0: 8, 8: 0}                       # 旧版からの穴（角かっこ）
    assert _bracket_partners("（整数 ｛ の組）") == {0: 8, 8: 0}                     # 全角
    assert _bracket_partners("( { [ )") == {0: 6, 6: 0}                            # 閉じていない開きが重なる
    assert _bracket_partners("( { [ x )") == {0: 8, 8: 0}
    assert _bracket_partners("( { )") == {0: 4, 4: 0}


def test_closers_without_opener_do_not_pair():
    """開きのない閉じかっこ（「1) 本文（注）」の「1)」）は組にならず、ほかの組の邪魔もしない。"""
    assert _bracket_partners("1) 本文（注）") == {5: 7, 7: 5}
    assert _bracket_partners("1) 本文") == {}
    assert _bracket_partners("a) b (c) d) e") == {5: 7, 7: 5}
    assert _bracket_partners("1) (整数 { の組) 2)") == {3: 11, 11: 3}
    assert _bracket_partners("}a)") == {}


def test_nested_and_crossing_unchanged():
    """入れ子は内側から組になり、交差する閉じかっこは組にならない（今までどおり）。"""
    assert _bracket_partners("{[(x)]}") == {0: 6, 6: 0, 1: 5, 5: 1, 2: 4, 4: 2}
    assert _bracket_partners("{a(b})") == {2: 5, 5: 2}                              # 後ろに「)」がある: 交差
    assert _bracket_partners("{a)") == {} and _bracket_partners("(a}") == {}
    assert _bracket_partners("a{b") == {} and _bracket_partners("a}b") == {}


def test_crossing_exact():
    # 「[」の後ろに「]」があるので、「)」は「[」を捨てずに組にならない。「(」も「]」と組にならない
    assert _bracket_partners("(a[b)c]") == {2: 6, 6: 2}


def test_route2_unclosed_brace_pair_held(journal, meta, tmp_path, monkeypatch):
    """S1: 変更履歴の中の「(」は直せない。閉じていない「{」があっても組の「)」も直さず、補った docx と XML は
    「集合(整数 { の組)を考える。」のまま（「(整数 { の組）」にしない）。"""
    res = _convert(tmp_path, monkeypatch, journal, meta, ["集合", _ins("("), "整数 { の組)を考える。"],
                   "集合（整数 { の組）を考える。")
    assert res.fidelity.ok and res.fidelity.final_ok and res.supplement.ok
    held = {(f.old, f.new): f.reason for f in res.docx_fix.skipped}
    assert held[("(", "（")].startswith("直せない文字")
    assert held[(")", "）")].startswith("かっこの組のもう片方の全角・半角の直し「(」→「（」を直さないので")
    assert para_text(source_texts(res.docx_fix.path), "集合") == "集合(整数 { の組)を考える。"
    assert "集合(整数 { の組)を考える。" in texts(load(res))


def test_route2_unclosed_square_pair_held(journal, meta, tmp_path, monkeypatch):
    """旧版からの穴: 閉じていない「[」でも同じ。"""
    res = _convert(tmp_path, monkeypatch, journal, meta, ["集合", _ins("("), "整数 [ の組)を考える。"],
                   "集合（整数 [ の組）を考える。")
    assert res.fidelity.ok and res.fidelity.final_ok and res.supplement.ok
    assert para_text(source_texts(res.docx_fix.path), "集合") == "集合(整数 [ の組)を考える。"


def test_route2_unclosed_brace_pair_both_fixed(journal, meta, tmp_path, monkeypatch):
    """両方直せるときは、閉じていない「{」があっても「（」「）」に直る。"""
    res = _convert(tmp_path, monkeypatch, journal, meta, ["集合(整数 { の組)を考える。"],
                   "集合（整数 { の組）を考える。")
    assert res.fidelity.ok and res.fidelity.final_ok and res.supplement.ok
    assert para_text(source_texts(res.docx_fix.path), "集合") == "集合（整数 { の組）を考える。"
