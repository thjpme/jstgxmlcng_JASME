"""注・図表へのリンクの規則（修正計画の H。D2・M5）。

- tests/fixtures/sample_links.docx（注番号が「1)」の書き方の論文）と sample_links_bare.docx（注番号が番号だけの上付きの論文）:
  上付きの指数・単位（cm²・x²・s⁻¹・f(x²)）を注にリンクしないこと、論文ごとの注番号の書き方（Linker.bare_notes）、リンクしなかった
  数字の記録（判断の一覧・レポートの 4 章・AI 依頼文の「推定:」）と、記録の text・occurrence の link_note を貼り戻せること
- 語の中の「図1」「表1」（地図1・図表1・発表1回目・付表1 など）を図・表にリンクしないこと（Linker.float_refs）
- その場で作る小さな論文（make_fixtures.make_article）と、段落だけの単体テストで、規則の境界
docs/fix_plan_repro_tests.py の D2・M5 の再現テスト（test_PROBLEM_superscript_exponent_linked_as_note・
test_PROBLEM_figure_reference_inside_word）の期待を逆にしたものも、ここに置く（test_superscript_exponent_not_linked・
test_float_refs_skip_words）。どのテストも、段落の文字で対象を選ぶ（fixture に段落を足しても壊れないように）。
"""
import json
import re

import make_fixtures as mf
import pytest
from conftest import LINKS, LINKS_BARE
from lxml import etree

from jasme_jats.linker import RE_FIGREF, RE_TABREF, Linker, find_in_para
from jasme_jats.model import Atom, Para
from jasme_jats.pipeline import Options, _mechanical, convert
from jasme_jats.report import actions
from jasme_jats.structure import ArticlePlan

S = mf.S
NOTES3 = ("1) 一つ目の架空の注。", "2) 二つ目の架空の注。", "3) 三つ目の架空の注。")
RE_EXP_ITEM = re.compile(r"「([0-9０-９]+)」（(\d+) 回目）")              # 指数・単位の記録の「2」（1 回目）
RE_BARE_ITEM = re.compile(r"link_note（text「([0-9０-９]+)」、occurrence (\d+)）")   # 番号だけの数字の記録


def load(res):
    return etree.fromstring(res.xml_path.read_bytes().split(b"\n", 2)[2])


def text(el):
    return "".join(el.itertext())


def xref_positions(p, kinds):
    """段落 p（XML の要素）の中の xref: [(段落の中の位置, 文字, rid)]（ref-type が kinds のもの。XML の順）。"""
    out, pos = [], 0

    def walk(el):
        nonlocal pos
        if el.tag == "xref" and el.get("ref-type") in kinds:
            out.append((pos, text(el), el.get("rid")))
        pos += len(el.text or "")
        for ch in el:
            walk(ch)
            pos += len(ch.tail or "")
    walk(p)
    return out


def para_links(root, prefix, kinds=("fn",)):
    """文字が prefix で始まる段落（ちょうど 1 つ）の xref: (段落の文字, [(位置, 文字, rid)])。"""
    found = [p for p in root.iter("p") if text(p).startswith(prefix)
             and not any(a.tag == "p" for a in p.iterancestors())]
    assert len(found) == 1, (prefix, [text(p) for p in found])
    return text(found[0]), xref_positions(found[0], kinds)


def same_links(plain, got, want):
    """xref の一覧 got（[(位置, 文字, rid)]）が want（[(直前の文字, 文字, rid)]）と同じか。直前の文字は、段落の中で xref の直前に
    あるはずの文字（位置を数えずに書くため）。"""
    return len(got) == len(want) and all(t == wt and rid == wr and plain[:pos].endswith(ctx)
                                         for (pos, t, rid), (ctx, wt, wr) in zip(got, want))


def records(res, prefix, category="note"):
    """文字が prefix で始まる段落の、リンクにしなかった記録（判断の一覧の category・applied=False のもの）の文面。"""
    srcs = [src for src, p in res.plan.paras.items() if p.plain().startswith(prefix)]
    assert len(srcs) == 1, (prefix, srcs)
    return [d.message for d in res.plan.decisions if d.src == srcs[0] and d.category == category and not d.applied]


def op(kind, src, text_, occurrence, target):
    return {"op": kind, "src": src, "text": text_, "occurrence": occurrence, "target": target, "role": "", "image": "",
            "mathml": "", "surname": "", "given": "", "reason": "記録の text と occurrence による", "confidence": "中"}


def src_of(res, prefix):
    [src] = [src for src, p in res.plan.paras.items() if p.plain().startswith(prefix)]
    return src


@pytest.fixture(scope="module")
def links(journal, tmp_path_factory):
    """sample_links.docx の手動モードの変換結果（回答を貼り戻す前）。"""
    from jasme_jats.config import ArticleMeta
    meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12", "pub_date": "2026-03-31",
                                  "received": "2025-06-01", "accepted": "2025-11-20", "peer_review": "あり"})
    return convert(LINKS, meta, journal, Options(out_dir=tmp_path_factory.mktemp("links"), ai_mode="manual",
                                                 convert_metafiles=False))


def article(tmp_path, body, notes=NOTES3):
    """本文の段落（XML の一覧）と、注の一覧（「1) …」の段落）の小さな論文。"""
    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"), *body, mf.para(S["fn_head"], "注"), *(mf.para(S["body"], n) for n in notes)]
    path = tmp_path / "case.docx"
    mf.make_article(path, "リンクの境界の検証用文書", parts)
    return path


# ============================================================================= D2: 上付きの指数・単位と注番号
def test_superscript_notes_with_marks(links, journal):
    """「1)」の書き方の論文: 番号の形がはっきりした注番号だけをリンクし、指数・単位（cm²・x²・s⁻¹・f(x²)）と番号だけの ² は
    リンクしない。「1,2)」「1-3)」の 1 もリンクし、「註1」は「註」ごと、上付きの「1」＋本文の「)」と本文の「注」＋上付きの「1」も
    リンクする。リンクは上付きの文字だけにかかる（位置で確かめる）。"""
    root = load(links)
    expect = {
        "面積は 3 cm": [("2 である", "1)", "fn1")],
        "式 x": [("を考える", "1", "fn1"), ("1,", "2)", "fn2")],
        "速さの単位は": [("−1 である", "1", "fn1"), ("1-", "3)", "fn3")],
        "架空の補足がある": [("補足がある", "註1", "fn1"), ("。また", "注3", "fn3")],
        "番号の後ろが本文の括弧である": [("括弧である", "1", "fn1"), ("本文の注", "1", "fn1")],
        "関数 f(x": [],
    }
    for prefix, want in expect.items():
        plain, got = para_links(root, prefix)
        assert same_links(plain, got, want), (plain, got)
        assert all(plain[pos:pos + len(t)] == t and " " not in t for pos, t, _ in got)
    # 上付きの外の「)」で補った注番号も、リンクは上付きの「1」だけ（本文の「)」は xref の外）
    [x] = [x for x in root.iter("xref") if x.get("ref-type") == "fn" and (x.tail or "").startswith(")")]
    assert text(x) == "1" and x.find("sup") is not None
    assert _mechanical(LINKS, journal)[2].bare_notes is False


def test_superscript_notes_bare(journal, meta, tmp_path):
    """番号だけの上付きの論文: かな・閉じ括弧の後ろの ¹ ² はリンクし、「4 m」＋² はリンクしない。上付きの「1-3」は 1 と 3、
    「1, 2」は 1 と 2（xref に空白を入れない）。"""
    res = convert(LINKS_BARE, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    root = load(res)
    expect = {
        "これは架空の主張である": [("主張である", "1", "fn1")],
        "架空の報告がある": [("2024）", "2", "fn2")],
        "教室の広さは 4 m": [],
        "架空の議論がある": [("議論がある", "1", "fn1"), ("1-", "3", "fn3"), ("議論もある", "1", "fn1"), ("1, ", "2", "fn2")],
    }
    for prefix, want in expect.items():
        plain, got = para_links(root, prefix)
        assert same_links(plain, got, want), (plain, got)
    assert _mechanical(LINKS_BARE, journal)[2].bare_notes is True
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and res.jstage_issues == []
    assert records(res, "教室の広さは 4 m") and not records(res, "これは架空の主張である")


def test_unlinked_superscripts_are_recorded(links):
    """リンクしなかった上付きの数字は、その番号の注があるときだけ記録する（applied=False）。指数・単位の形は段落ごとに 1 件
    （決定事項 15）、「1)」の書き方の論文の番号だけの数字は 1 件ずつ。文面に link_note の text と occurrence を書き、text に
    空白を入れない。レポートの 4 章と AI 依頼文の「推定:」に載り、要対応・要確認（actions）には入らない。"""
    rec = {prefix: records(links, prefix) for prefix in ("面積は 3 cm", "式 x", "速さの単位は", "関数 f(x", "架空の補足がある")}
    assert [RE_EXP_ITEM.findall(m) for m in rec["面積は 3 cm"]] == [[("2", "1")]]
    assert [RE_EXP_ITEM.findall(m) for m in rec["式 x"]] == [[("2", "1"), ("2", "2")]]     # x²+y² は 1 件にまとめる
    assert [RE_EXP_ITEM.findall(m) for m in rec["速さの単位は"]] == [[("1", "1")]]         # 符号で始まる上付き（s⁻¹）
    assert all("指数・単位" in m for k in ("面積は 3 cm", "式 x", "速さの単位は") for m in rec[k])
    # f(x²) の ² は指数・単位、「番号だけの」＋² は番号だけの数字（段落の中の順に記録する）
    exp, bare = rec["関数 f(x"]
    assert RE_EXP_ITEM.findall(exp) == [("2", "1")] and RE_BARE_ITEM.findall(bare) == [("2", "2")]
    assert "番号だけの形" in bare and "fn2" in bare
    assert rec["架空の補足がある"] == []
    report = links.report_path.read_text(encoding="utf-8")
    prompt = links.prompt_path.read_text(encoding="utf-8")
    for prefix, msgs in rec.items():
        src = src_of(links, prefix)
        for m in msgs:
            assert m in report
            assert f"- [{src}] 推定: {m}" in prompt
    assert [a.key for a in actions(links)] == ["ai_pending"]      # 記録だけ（手動モードの回答待ちのほかに知らせはない）


def test_link_note_from_record_is_accepted(links, journal, meta, tmp_path):
    """記録の text と occurrence で link_note を貼り戻すと採用され、その上付きの数字（本文の同じ数字ではなく）にリンクが付く。"""
    ops = []
    for prefix, pattern in (("面積は 3 cm", RE_EXP_ITEM), ("関数 f(x", RE_BARE_ITEM)):
        msg = records(links, prefix)[-1]
        [(t, k)] = pattern.findall(msg)
        ops.append(op("link_note", src_of(links, prefix), t, int(k), "fn2"))
    res = convert(LINKS, meta, journal, Options(out_dir=tmp_path, ai_mode="manual", convert_metafiles=False,
                                                ai_response=json.dumps({"operations": ops}, ensure_ascii=False)))
    assert len(res.ai.accepted) == 2 and res.ai.rejected == []
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    root = load(res)
    assert same_links(*para_links(root, "面積は 3 cm"), [("3 cm", "2", "fn2"), ("2 である", "1)", "fn1")])
    assert same_links(*para_links(root, "関数 f(x"), [("番号だけの", "2", "fn2")])


def test_exponent_without_note_is_not_unresolved(journal, meta, tmp_path):
    """指数・単位の形の上付きは、その番号の注がなくても「対応する注が見つからない」（3 章）に出さず、記録もしない。番号の形が
    はっきりした上付きの「5)」で注 5 がないものは、今までどおり 3 章に出る。"""
    path = article(tmp_path, [mf.para(S["body"], "面積は 3 cm", mf.run("2", sup=True), " である", mf.run("1)", sup=True), "。"),
                              mf.para(S["body"], "一覧にない注である", mf.run("5)", sup=True), "。")], notes=NOTES3[:1])
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    fn = [(u[2], u[3]) for u in res.unresolved_after if u[0] == "fn"]
    assert fn == [("5)", "上付きの「5)」に対応する注が見つからない")]
    assert records(res, "面積は 3 cm") == []
    assert same_links(*para_links(load(res), "面積は 3 cm"), [("2 である", "1)", "fn1")])


@pytest.mark.parametrize("prefix, body, links_, bare_notes, recorded", [
    # 符号で始まる上付きは、閉じ括弧で終わっても指数とみなす（注番号は符号で始まらない）
    ("速さは毎時", [mf.para(S["body"], "速さは毎時 3 km", mf.run("\u22121)", sup=True), "。"),
                    mf.para(S["body"], "注である", mf.run("2)", sup=True))], [], False, True),
    # 英字の後ろでも、閉じ括弧で終わる上付きは番号の形がはっきりした注番号（指数の判定より先）
    ("変数 x", [mf.para(S["body"], "変数 x", mf.run("2)", sup=True), " を使う。")], [("変数 x", "2)", "fn2")], False, False),
    # 「1)」の書き方の論文では、閉じ括弧の後ろの番号だけの上付きもリンクしない（記録する）
    ("架空の報告", [mf.para(S["body"], "架空の報告がある（試験, 2024）", mf.run("2", sup=True), "。"),
                    mf.para(S["body"], "注である", mf.run("1)", sup=True), "。")], [], False, True),
    # 本文の「注」（と空白）＋上付きの数字はリンクする
    ("架空の補足は注 ", [mf.para(S["body"], "架空の補足は注 ", mf.run("1", sup=True), " にある", mf.run("2)", sup=True), "。")],
     [("補足は注 ", "1", "fn1"), ("1 にある", "2)", "fn2")], False, False),
    # 直前が「注」の上付きだけでは、論文の書き方を「1)」の書き方にしない（番号だけの ² もリンクする）
    ("架空の補足は注", [mf.para(S["body"], "架空の補足は注", mf.run("1", sup=True), "にあり、別の主張もある", mf.run("2", sup=True),
                                "。")], [("補足は注", "1", "fn1"), ("主張もある", "2", "fn2")], True, False),
    # 全角の上付きの注番号
    ("全角の注番号", [mf.para(S["body"], "全角の注番号である", mf.run("２）", sup=True), "。")], [("番号である", "２）", "fn2")],
     False, False),
])
def test_superscript_boundaries(prefix, body, links_, bare_notes, recorded, journal, meta, tmp_path):
    """上付きの注番号の規則の境界（prefix で始まる段落のリンク・論文の書き方・その段落の記録の有無）。"""
    path = article(tmp_path, body)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    assert same_links(*para_links(load(res), prefix), links_)
    assert _mechanical(path, journal)[2].bare_notes is bare_notes
    assert bool(records(res, prefix)) is recorded
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid


def test_note_marks_inside_box(journal, meta, tmp_path):
    """囲み（文字だけのテキストボックス。boxed-text）の中の上付きも本文と同じ規則: 「9 cm」＋² はリンクせずに記録し、「1)」は fn1。"""
    box = mf.para(S["body"], "問1　架空の正方形の面積は 9 cm", mf.run("2", sup=True), " である", mf.run("1)", sup=True),
                  "。これを確かめよ。")
    path = article(tmp_path, [mf.para(S["body"], "本文の段落である", mf.run("2)", sup=True), "。",
                                      mf.textbox_inline(box, 4101, cx=12 * 360000, cy=2 * 360000))])
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and res.jstage_issues == []
    [bt] = load(res).iter("boxed-text")
    [bp] = bt.iter("p")
    assert same_links(text(bp), xref_positions(bp, ("fn",)), [("2 である", "1)", "fn1")])
    assert [RE_EXP_ITEM.findall(m) for m in records(res, "問1")] == [[("2", "1")]]


@pytest.mark.parametrize("before, sup, after, kinds", [
    ("面積は 3 cm", "2", " である", ["exponent"]), ("である", "1)", "。", ["strong"]), ("式 x", "2", "+y", ["exponent"]),
    ("を考える", "1,2)", "。", ["strong", "strong"]), ("m s", "−1", "", ["exponent"]),
    ("補足がある", "註1", "。", ["strong"]), ("括弧である", "1", ")。", ["strong"]), ("本文の注", "1", "も", ["after_note"]),
    ("f(x", "2", ")", ["exponent"]), ("番号だけの", "2", "は", ["bare"]), ("議論もある", "1, 2", "。", ["bare", "bare"]),
    ("（試験, 2024）", "2", "。", ["bare"]), ("10", "2,3", "", ["exponent", "exponent"]), ("x", "1-3", "", ["exponent"] * 2),
    ("", "−1)", "", ["exponent"]), ("(a+b)", "2", "+c", ["exponent"]), ("(a+b)", "2", "", ["bare"]),
    ("である", "1", "）", ["strong"]), ("10", "3", ")", ["exponent"]), ("ある", "1)2", "", ["strong", "bare"]),
])
def test_sup_mark_kinds(before, sup, after, kinds):
    """上付きの続きの候補の種類（_sup_marks）: 符号 > 番号の形 > 直前の「注」 > 指数・単位 > 番号だけ。数字と区切りだけの続きは
    続き全体で 1 つの種類。リンクの範囲は前後の空白を含めない。"""
    from jasme_jats.linker import _sup_marks
    plain = before + sup + after
    marks = _sup_marks(plain, len(before), len(before) + len(sup), sup)
    assert [m.kind for m in marks] == kinds
    assert all(plain[m.start:m.end] == plain[m.start:m.end].strip() for m in marks)


@pytest.mark.parametrize("plain, pos, text_", [("2022 年の 2 m2", 11, "2"), ("1111", 2, "11"), ("図1と図1", 3, "図1"),
                                              ("x2+y2", 4, "2")])
def test_occurrence_at_matches_find_in_para(plain, pos, text_):
    """記録の occurrence（occurrence_at）は、AI の回答の検証（find_in_para）でその位置を指す（重なる一致も数える）。"""
    from jasme_jats.linker import occurrence_at
    p = Para(src="d1", atoms=[Atom(kind="text", text=plain)])
    assert find_in_para(p, text_, occurrence_at(p, pos, text_)) == (pos, pos + len(text_))


# ============================================================================= M5: 語の中の「図1」「表1」
def test_figure_refs_inside_words(links):
    """語の中の「図1」「表1」はリンクしない（直前が漢字で、前掲・乃至・及でないもの）。先頭の番号の直後から探し直すので、
    「図表1と表1」の後ろの表1、「地図1、図2」の図2 はリンクする。記録は先頭の番号の図・表があるものだけ（並びの番号は記録しない）。"""
    root = load(links)
    kinds = ("fig", "table")
    assert para_links(root, "地図1と図表1", kinds)[1] == []
    assert [(t, rid) for _, t, rid in para_links(root, "前掲表1", kinds)[1]] == [
        ("表1", "T1"), ("図1", "F1"), ("図2", "F2"), ("図1", "F1"), ("図1", "F1"), ("2", "F2")]
    assert same_links(*para_links(root, "図表1と表1", kinds), [("図表1と", "表1", "T1"), ("地図1、", "図2", "F2")])
    figs = records(links, "地図1と図表1", "figure")
    tabs = records(links, "地図1と図表1", "table")
    assert [re.search("直前の「(.)」", m).group(1) for m in figs] == ["地", "念"]
    assert [re.search("直前の「(.)」", m).group(1) for m in tabs] == ["図", "発", "代", "付"]
    assert "link_figure（text「図1」、occurrence 2）" in figs[1] and "link_table（text「表1」、occurrence 4）" in tabs[3]
    # 「地図1、図2」と「地図1、2」は 1 件ずつ（「、2」は記録しない）、「図表1と表1」の図表1 は 1 件
    assert len(records(links, "図表1と表1", "figure")) == 2 and len(records(links, "図表1と表1", "table")) == 1
    prompt = links.prompt_path.read_text(encoding="utf-8")
    assert all(f"推定: {m}" in prompt for m in figs + tabs)


def test_link_figure_from_record_is_accepted(links, journal, meta, tmp_path):
    """語の一部とみなした「図1」の記録の text・occurrence の link_figure を貼り戻すと、その「図1」にリンクが付く。"""
    msg = records(links, "地図1と図表1", "figure")[1]          # 概念図1
    t, k = re.search(r"link_figure（text「(.+?)」、occurrence (\d+)）", msg).groups()
    response = json.dumps({"operations": [op("link_figure", src_of(links, "地図1と図表1"), t, int(k), "F1")]}, ensure_ascii=False)
    res = convert(LINKS, meta, journal, Options(out_dir=tmp_path, ai_mode="manual", ai_response=response, convert_metafiles=False))
    assert len(res.ai.accepted) == 1 and res.fidelity.ok
    assert same_links(*para_links(load(res), "地図1と図表1", ("fig",)), [("概念", "図1", "F1")])


@pytest.mark.parametrize("plain, ref_type, ids, linked, recorded", [
    ("地図1に示す", "fig", {1: "F1"}, [], 1),
    ("図表1に示す", "table", {1: "T1"}, [], 1),
    ("発表1回目の", "table", {1: "T1"}, [], 1),
    ("図表1と表1を比べる。", "table", {1: "T1"}, [("表1", "T1")], 1),
    ("地図1、2と地図1、図2", "fig", {1: "F1", 2: "F2"}, [("図2", "F2")], 2),
    ("前掲表1と、図1乃至図2、及表1", "table", {1: "T1"}, [("表1", "T1"), ("表1", "T1")], 0),
    ("地図3と図3", "fig", {1: "F1"}, [], 0),      # 図3 はない: 語の一部は記録も「見つからない」もない
])
def test_float_refs_skip_words(plain, ref_type, ids, linked, recorded):
    """docs/fix_plan_repro_tests.py の test_PROBLEM_figure_reference_inside_word の逆（正規表現ではなく float_refs の結果で確かめる）。"""
    plan = ArticlePlan()
    lk = Linker(plan)
    p = Para(src="d1", atoms=[Atom(kind="text", text=plain)])
    regex, word = (RE_FIGREF, "図") if ref_type == "fig" else (RE_TABREF, "表")
    lk.float_refs(p, regex, ids, ref_type, word)
    assert [(a.text, a.link.attrs["rid"]) for a in p.atoms if a.link is not None] == linked
    assert len(plan.decisions) == recorded and all(not d.applied for d in plan.decisions)
    assert [u for u in lk.unresolved if "図3" not in u[2]] == []
    assert len(lk.unresolved) == (1 if plain == "地図3と図3" else 0)     # リンクの形の「図3」は今までどおり「見つからない」


def test_eq_refs_unchanged():
    """式の参照（eq_refs）は H で変えない: 「数式(1)」の「式(1)」は今までどおりリンクする。"""
    lk = Linker(ArticlePlan())
    p = Para(src="d1", atoms=[Atom(kind="text", text="数式(1)より明らか。")])
    lk.eq_refs(p, {"1": "FD1"})
    assert [(a.text, a.link.attrs["rid"]) for a in p.atoms if a.link is not None] == [("式(1)", "FD1")]


def test_superscript_exponent_not_linked(journal, meta, tmp_path):
    """docs/fix_plan_repro_tests.py の test_PROBLEM_superscript_exponent_linked_as_note の逆: 上付きの「2」（cm² の指数）は、
    注 2 があっても注へのリンクにしない。"""
    path = article(tmp_path, [mf.para(S["body"], "面積は 3 cm", mf.run("2", sup=True), " である", mf.run("1)", sup=True), "。")],
                   notes=NOTES3[:2])
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    links_ = [(text(x), x.get("rid")) for x in load(res).iter("xref") if x.get("ref-type") == "fn"]
    assert ("1)", "fn1") in links_
    assert ("2", "fn2") not in links_
