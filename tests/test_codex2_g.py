"""外部レビュー 2 回目 S1: 閉じていない開きかっこがあると、組のかっこの片方だけが直る問題（pdfdocx._bracket_partners）。
文字はすべて架空。"""
import make_fixtures as mf
from jasme_jats.fidelity import source_texts
from jasme_jats.pdfdocx import _bracket_partners
from test_codex_d import _convert, _ins
from test_pdfmatch import load, para_text, texts


def test_unclosed_open_is_discarded():
    """閉じていない開きかっこは組にならず、ほかの種類の組の邪魔もしない（組は種類ごと）。"""
    assert _bracket_partners("(整数 { の組)") == {0: 8, 8: 0}                       # S1 の再現（波かっこ）
    assert _bracket_partners("(整数 [ の組)") == {0: 8, 8: 0}                       # 旧版からの穴（角かっこ）
    assert _bracket_partners("（整数 ｛ の組）") == {0: 8, 8: 0}                     # 全角
    assert _bracket_partners("( { [ )") == {0: 6, 6: 0}                            # 閉じていない開きが重なる
    assert _bracket_partners("((a)") == {1: 3, 3: 1}                               # 同じ種類の入れ子で外側が閉じていない
    assert _bracket_partners("(a))") == {0: 2, 2: 0}


def test_unclosed_with_other_pair_later():
    """(a) 閉じていない「{」の後ろに別の「{…}」の組があっても、外側の「( )」は組になる。"""
    assert _bracket_partners("(例 { 1, 2 ) と { 3 }") == {0: 10, 10: 0, 14: 18, 18: 14}
    assert _bracket_partners("(例 [ 1, 2 ) と [ 3 ]") == {0: 10, 10: 0, 14: 18, 18: 14}


def test_crossing_pairs_per_kind():
    """(b) 波かっこは、丸・角かっことは別に組にする（丸・角かっこの組を 0.37.0 から変えない）。波かっこと交差しても、それぞれ組になる。
    丸かっこと角かっこは 1 つのスタック（0.37.0 と同じ）: 後ろで閉じられる角かっこの中の「)」は組にしない。"""
    assert _bracket_partners("(a{b)c}") == {0: 4, 4: 0, 2: 6, 6: 2}
    assert _bracket_partners("{a(b}c)") == {0: 4, 4: 0, 2: 6, 6: 2}
    assert _bracket_partners("(a［b)c］") == {2: 6, 6: 2}                         # 0.37.0 と同じ（「(」は組にならない）
    assert _bracket_partners("a(b［c)d］e)") == {1: 9, 9: 1, 3: 7, 7: 3}          # 0.37.0 と同じ（5 の「)」を飛ばす）


def test_list_marks_inside_square_brackets_do_not_take_the_outer_paren():
    """再点検で見つかった回帰: 角かっこの中の「1)」「2)」（開く側のない閉じるかっこ）は、外側の「(」と組にしない
    （種類ごとに別々に組を作ると、「(」が「1)」と組になり、最後の「)」が組にならず片方だけ直る。0.37.0 は外側どうしが組）。"""
    t = "集合(例 [1) a, 2) b])を考える。"
    assert _bracket_partners(t) == {2: 17, 17: 2, 5: 16, 16: 5}
    t = "集合(例 ［a) b］)を考える。"
    assert _bracket_partners(t) == {2: 11, 11: 2, 5: 10, 10: 5}
    # 閉じていない「[」（後ろの「]」は 2 つ目の「[」のもの）は捨てて、外側の「(」「)」を組にする
    assert _bracket_partners("(例 [ 1, 2 ) と [ 3 ]") == {0: 10, 10: 0, 14: 18, 18: 14}
    # 同じ種類の中の開く側のない閉じるかっこは見分けられない（0.37.0 から同じ。「(」は最初の「)」と組）
    assert _bracket_partners("集合(例 1) a, 2) b)を考える。") == {2: 6, 6: 2}


def test_closers_without_opener_do_not_pair():
    """開きのない閉じかっこ（「1) 本文（注）」の「1)」）は組にならず、ほかの組の邪魔もしない。"""
    assert _bracket_partners("1) 本文（注）") == {5: 7, 7: 5}
    assert _bracket_partners("1) 本文") == {}
    assert _bracket_partners("a) b (c) d) e") == {5: 7, 7: 5}
    assert _bracket_partners("1) (整数 { の組) 2)") == {3: 11, 11: 3}
    assert _bracket_partners("}a)") == {}
    assert _bracket_partners("（a 1) b") == {0: 4, 4: 0}                           # 本当に閉じていない開きがあれば組になる


def test_nested_mixed_kinds_and_widths():
    """入れ子（内側から）・種類の混在・全角と半角の混在。"""
    assert _bracket_partners("{[(x)]}") == {0: 6, 6: 0, 1: 5, 5: 1, 2: 4, 4: 2}
    assert _bracket_partners("(（1）)") == {0: 4, 4: 0, 1: 3, 3: 1}
    assert _bracket_partners("{a)") == {} and _bracket_partners("(a}") == {}
    assert _bracket_partners("a{b") == {} and _bracket_partners("a}b") == {}


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


def _held_ok(res, head, want):
    assert res.fidelity.ok and res.fidelity.final_ok and res.supplement.ok
    assert para_text(source_texts(res.docx_fix.path), head) == want
    assert want in texts(load(res))


def test_route2_unclosed_brace_then_pair_open_held(journal, meta, tmp_path, monkeypatch):
    """(a) 「(」が直せないとき、後ろに別の「{…}」の組があっても「)」は直さない。"""
    res = _convert(tmp_path, monkeypatch, journal, meta, ["集合", _ins("("), "例 { 1, 2 ) と { 3 } を考える。"],
                   "集合（例 { 1, 2 ）と { 3 } を考える。")
    _held_ok(res, "集合", "集合(例 { 1, 2 ) と { 3 } を考える。")


def test_route2_unclosed_brace_then_pair_close_held(journal, meta, tmp_path, monkeypatch):
    """(a) 「)」が直せないとき、「(」も直さない。"""
    res = _convert(tmp_path, monkeypatch, journal, meta, ["集合(例 { 1, 2 ", _ins(")"), " と { 3 } を考える。"],
                   "集合（例 { 1, 2 ） と { 3 } を考える。")
    _held_ok(res, "集合", "集合(例 { 1, 2 ) と { 3 } を考える。")


def test_route2_unclosed_square_then_pair_held(journal, meta, tmp_path, monkeypatch):
    """角かっこの (a)。"""
    res = _convert(tmp_path, monkeypatch, journal, meta, ["集合", _ins("("), "例 [ 1, 2 ) と [ 3 ] を考える。"],
                   "集合（例 [ 1, 2 ）と [ 3 ] を考える。")
    _held_ok(res, "集合", "集合(例 [ 1, 2 ) と [ 3 ] を考える。")


def test_route2_crossing_held(journal, meta, tmp_path, monkeypatch):
    """(b) 交差「(a{b)c}」で「(」が直せないとき、「)」も直さない（「{」「}」は組どうしで直る）。"""
    res = _convert(tmp_path, monkeypatch, journal, meta, ["集合", _ins("("), "a { b ) c } を考える。"],
                   "集合（a ｛ b ） c ｝を考える。")
    out = para_text(source_texts(res.docx_fix.path), "集合")
    assert res.fidelity.ok and res.fidelity.final_ok and res.supplement.ok
    assert "(" in out and ")" in out and "（" not in out and "）" not in out


def test_route2_crossing_old_hole_held(journal, meta, tmp_path, monkeypatch):
    """旧版からの穴「{a(b}c)」: 「{」が直せないとき「}」も直さない。"""
    res = _convert(tmp_path, monkeypatch, journal, meta, ["集合", _ins("{"), "a ( b } c ) を考える。"],
                   "集合｛a （ b ｝ c ）を考える。")
    out = para_text(source_texts(res.docx_fix.path), "集合")
    assert res.fidelity.ok and res.fidelity.final_ok and res.supplement.ok
    assert "{" in out and "}" in out and "｛" not in out and "｝" not in out


def test_route2_list_marks_in_square_brackets_both_fixed(journal, meta, tmp_path, monkeypatch):
    """再点検の回帰: 「(例 [1) a, 2) b])」→ PDF「（例 [1) a, 2) b]）」は、外側の「(」「)」が両方直る（0.37.0 と同じ。
    「(例 [1) a, 2) b]）」のような、docx にも PDF にもない形にしない）。"""
    for i, (docx, pdf) in enumerate((("集合(例 [1) a, 2) b])を考える。", "集合（例 [1) a, 2) b]）を考える。"),
                                     ("集合(例 ［a) b］)を考える。", "集合（例 ［a) b］）を考える。"))):
        sub = tmp_path / f"m{i}"
        sub.mkdir()
        res = _convert(sub, monkeypatch, journal, meta, [docx], pdf)
        assert res.fidelity.ok and res.fidelity.final_ok and res.supplement.ok
        assert para_text(source_texts(res.docx_fix.path), "集合") == pdf
        assert pdf in texts(load(res))


def test_route2_list_marks_in_square_brackets_held_together(journal, meta, tmp_path, monkeypatch):
    """同じ形で外側の「(」が直せないときは、最後の「)」も直さない（列挙の「1)」「2)」は PDF と同じ半角なので直す所がない）。"""
    res = _convert(tmp_path, monkeypatch, journal, meta, ["集合", _ins("("), "例 [1) a, 2) b])を考える。"],
                   "集合（例 [1) a, 2) b]）を考える。")
    _held_ok(res, "集合", "集合(例 [1) a, 2) b])を考える。")
