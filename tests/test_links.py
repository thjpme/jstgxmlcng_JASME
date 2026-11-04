"""注・図表へのリンクの規則（修正計画の H。D2・M5）。

- tests/fixtures/sample_links.docx（注番号が「1)」の書き方の論文）と sample_links_bare.docx（注番号が番号だけの上付きの論文）:
  上付きの指数・単位（cm²・x²・s⁻¹・f(x²)）を注にリンクしないこと、論文ごとの注番号の書き方（Linker.bare_notes）、リンクしなかった
  数字の記録（判断の一覧・レポートの 4 章・AI 依頼文の「推定:」）と、記録の text・occurrence の link_note を貼り戻せること
- 語の中の「図1」「表1」（地図1・図表1・発表1回目・付表1 など）を図・表にリンクしないこと（Linker.float_refs）
- その場で作る小さな論文（make_fixtures.make_article）と、段落だけの単体テストで、規則の境界
- ルート2（docx から作り、出版版 PDF で補う）で、番号だけの注の docx を注番号が「1)」の形の出版版 PDF で補うときの今の振る舞い（extract_pages を差し替える。
  docs/DESIGN.md の 4.4・7 章の限界）
docs/fix_plan_repro_tests.py の D2・M5 の再現テスト（test_PROBLEM_superscript_exponent_linked_as_note・
test_PROBLEM_figure_reference_inside_word）の期待を逆にしたものも、ここに置く（test_superscript_exponent_not_linked・
test_float_refs_skip_words）。どのテストも、段落の文字で対象を選ぶ（fixture に段落を足しても壊れないように）。
"""
import json
import re

import make_fixtures as mf
import pytest
from conftest import FULL, LINKS, LINKS_BARE
from lxml import etree

from jasme_jats.linker import RE_FIGREF, RE_TABREF, Linker, find_in_para
from jasme_jats.model import Atom, LinkSpec, Para
from jasme_jats.pipeline import Options, _mechanical, convert
from jasme_jats.report import TO_CHECK, actions, step
from jasme_jats.structure import ArticlePlan

S = mf.S
NOTES3 = ("1) 一つ目の架空の注。", "2) 二つ目の架空の注。", "3) 三つ目の架空の注。")
# 記録の link_note の text と occurrence（指数・単位の記録は数字ごとに「／」で並ぶ。番号だけの数字の記録は 1 つ）
RE_ITEM = re.compile(r"text「([0-9０-９]+)」、occurrence (\d+)")


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
    「1, 2」は 1 と 2（xref に空白を入れない）。文の括弧を閉じる直前の上付きの「3」＋本文の「）」（「（…述べる³）」）はリンクするが、
    論文の書き方を「1)」の書き方にしない（ほかの番号だけの注番号もリンクしたまま。0.26.0 と同じ）。"""
    res = convert(LINKS_BARE, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    root = load(res)
    expect = {
        "これは架空の主張である": [("主張である", "1", "fn1")],
        "架空の報告がある": [("2024）", "2", "fn2")],
        "教室の広さは 4 m": [],
        "架空の議論がある": [("議論がある", "1", "fn1"), ("1-", "3", "fn3"), ("議論もある", "1", "fn1"), ("1, ", "2", "fn2")],
        "（詳しい架空の説明は後で述べる": [("述べる", "3", "fn3")],
    }
    for prefix, want in expect.items():
        plain, got = para_links(root, prefix)
        assert same_links(plain, got, want), (plain, got)
    assert _mechanical(LINKS_BARE, journal)[2].bare_notes is True
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and res.jstage_issues == []
    assert records(res, "教室の広さは 4 m") and not records(res, "これは架空の主張である")
    assert not records(res, "（詳しい架空の説明は後で述べる")


def test_unlinked_superscripts_are_recorded(links):
    """リンクしなかった上付きの数字は、その番号の注があるときだけ記録する（applied=False）。指数・単位の形は段落ごとに 1 件
    （決定事項 15）、「1)」の書き方の論文の番号だけの数字は 1 件ずつ。文面に link_note の text と occurrence を書き、text に
    空白を入れない。レポートの 4 章と AI 依頼文の「推定:」に載り、要対応・要確認（actions）には入らない。"""
    rec = {prefix: records(links, prefix) for prefix in ("面積は 3 cm", "式 x", "速さの単位は", "関数 f(x", "架空の補足がある")}
    assert [RE_ITEM.findall(m) for m in rec["面積は 3 cm"]] == [[("2", "1")]]
    assert [RE_ITEM.findall(m) for m in rec["式 x"]] == [[("2", "1"), ("2", "2")]]     # x²+y² は 1 件にまとめる
    assert [RE_ITEM.findall(m) for m in rec["速さの単位は"]] == [[("1", "1")]]         # 符号で始まる上付き（s⁻¹）
    assert all("指数・単位" in m and "番号だけ" not in m for k in ("面積は 3 cm", "式 x", "速さの単位は") for m in rec[k])
    assert rec["面積は 3 cm"][0].startswith("上付きの「2」は、指数・単位") and "注 fn2 に" in rec["面積は 3 cm"][0]
    # 同じ数字は利用者向けの前半に 1 回だけ書いて件数を添え、AI 向けの text と occurrence は数字ごとに書く
    assert rec["式 x"][0].startswith("上付きの「2」（2 か所）は、") and "occurrence 1／text「2」" in rec["式 x"][0]
    # f(x²) の ² は指数・単位、「番号だけの」＋² は番号だけの数字（段落の中の順に記録する）
    exp, bare = rec["関数 f(x"]
    assert RE_ITEM.findall(exp) == [("2", "1")] and RE_ITEM.findall(bare) == [("2", "2")]
    assert "指数・単位" in exp and "番号だけの形" in bare and "fn2" in bare
    assert all(len(m) <= 140 for msgs in rec.values() for m in msgs)     # 利用者が読む記録は短く（1 件 140 字まで）
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
    for prefix in ("面積は 3 cm", "関数 f(x"):
        msg = records(links, prefix)[-1]
        [(t, k)] = RE_ITEM.findall(msg)
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
    # 上付きの「1」＋本文の「)」はリンクするが、論文の書き方の判定には数えない（本文の閉じ括弧は文の括弧のこともあるため。暫定）。
    # 上付きの文字だけで番号の形がはっきりした注番号がなければ番号だけの論文とみなし、番号だけの ² もリンクする（0.26.0 と同じ）
    ("番号だけの上付き", [mf.para(S["body"], "架空の主張である", mf.run("1", sup=True), ")。"),
                         mf.para(S["body"], "番号だけの上付き", mf.run("2", sup=True), "もある。")],
     [("番号だけの上付き", "2", "fn2")], True, False),
    # 直前が「注」の上付きだけでは、論文の書き方を「1)」の書き方にしない（番号だけの ² もリンクする）
    ("架空の補足は注", [mf.para(S["body"], "架空の補足は注", mf.run("1", sup=True), "にあり、別の主張もある", mf.run("2", sup=True),
                                "。")], [("補足は注", "1", "fn1"), ("主張もある", "2", "fn2")], True, False),
    # 全角の上付きの注番号
    ("全角の注番号", [mf.para(S["body"], "全角の注番号である", mf.run("２）", sup=True), "。")], [("番号である", "２）", "fn2")],
     False, False),
    # 番号だけの論文: 括弧として使う「＞」「〉」の後ろの番号だけの上付きは注番号（比較の記号は、直前にあっても指数とみなさない）
    ("＜架空の用語＞", [mf.para(S["body"], "＜架空の用語＞", mf.run("1", sup=True), "と〈架空の語〉", mf.run("2", sup=True), "を使う。")],
     [("用語＞", "1", "fn1"), ("語〉", "2", "fn2")], True, False),
    # 番号だけの論文: 全角の単位の記号（㎝）の後ろの上付きは指数・単位（リンクせず記録する）
    ("面積は 12㎝", [mf.para(S["body"], "面積は 12㎝", mf.run("2", sup=True), " である。")], [], True, True),
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
    assert [RE_ITEM.findall(m) for m in records(res, "問1")] == [[("2", "1")]]


@pytest.mark.parametrize("where", ["box", "cell"])
def test_note_style_counts_box_and_cell(where, journal, meta, tmp_path):
    """論文の書き方の判定には、囲み（boxed-text）と表のセルの中の上付きも数える（本文と同じ規則）: 本文には番号だけの上付きしか
    なく、上付きの「1)」が囲み・表のセルの中にだけある論文は「1)」の書き方とみなし、本文の番号だけの ² はリンクせずに記録する。"""
    shaped = mf.para(S["body"], "問2　架空の長方形の面積を求める式を考える", mf.run("1)", sup=True), "。これを確かめよ。")
    if where == "box":
        holder = [mf.para(S["body"], "次の囲みを見る。", mf.textbox_inline(shaped, 4102, cx=12 * 360000, cy=2 * 360000))]
    else:
        holder = [mf.para(S["tab_cap"], "表1\u3000架空の表"), mf.table([[mf.cell("観点"), mf.cell(shaped)]])]
    path = article(tmp_path, [mf.para(S["body"], "番号だけの主張である", mf.run("2", sup=True), "。"), *holder])
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    assert _mechanical(path, journal)[2].bare_notes is False
    assert same_links(*para_links(load(res), "番号だけの主張である"), [])
    assert [RE_ITEM.findall(m) for m in records(res, "番号だけの主張である")] == [[("2", "1")]]
    xs = [(text(x), x.get("rid")) for x in load(res).iter("xref") if x.get("ref-type") == "fn"]
    assert xs == [("1)", "fn1")]                # 囲み・セルの中の「1)」はリンクする


@pytest.mark.parametrize("before, sup, after, kinds", [
    ("面積は 3 cm", "2", " である", ["exponent"]), ("である", "1)", "。", ["strong"]), ("式 x", "2", "+y", ["exponent"]),
    ("を考える", "1,2)", "。", ["strong", "strong"]), ("m s", "−1", "", ["exponent"]),
    ("補足がある", "註1", "。", ["strong"]), ("括弧である", "1", ")。", ["strong"]), ("本文の注", "1", "も", ["after_note"]),
    ("f(x", "2", ")", ["exponent"]), ("番号だけの", "2", "は", ["bare"]), ("議論もある", "1, 2", "。", ["bare", "bare"]),
    ("（試験, 2024）", "2", "。", ["bare"]), ("10", "2,3", "", ["exponent", "exponent"]), ("x", "1-3", "", ["exponent"] * 2),
    ("", "−1)", "", ["exponent"]), ("(a+b)", "2", "+c", ["exponent"]), ("(a+b)", "2", "", ["bare"]),
    ("である", "1", "）", ["strong"]), ("10", "3", ")", ["exponent"]), ("ある", "1)2", "", ["strong", "bare"]),
    # 直前の文字: ギリシャ文字・全角の英字・単位の記号（㎝・µ・Å・′）・四則などの演算の記号は指数、比較の記号・括弧は指数としない
    ("π", "2", "", ["exponent"]), ("ｘ", "2", "", ["exponent"]), ("面積は 12㎝", "2", " である", ["exponent"]),
    ("µ", "2", "", ["exponent"]), ("10 \u00c5", "3", "", ["exponent"]), ("10 \u212b", "3", "", ["exponent"]),
    ("x\u2032", "2", "", ["exponent"]), ("10−", "3", "", ["exponent"]), ("＜架空の用語＞", "1", "と", ["bare"]),
    ("<term>", "2", "", ["bare"]), ("x=", "2", "", ["bare"]),
    # 直後の文字: 比較の記号は、直前で決まらないときも指数（(a+b)²＜c）
    ("(a+b)", "2", "＜c", ["exponent"]), ("(a+b)", "2", "=c", ["exponent"]),
    # ASCII のハイフンで始まる上付き（m s⁻² を「s」＋上付きの「-2」で書いたもの）も、直前の文字によらず指数。本文の「註」＋上付きも
    # 直前が「注」と同じ
    ("m s", "-2", "", ["exponent"]), ("", "-1", "", ["exponent"]), ("本文の註", "1", "も", ["after_note"]),
    # 本文の閉じ括弧で補うのは、上付きの続きが数字で終わるときだけ（上付きの「3a」＋本文の「）」は番号だけ）
    ("述べる", "3a", "）", ["bare"]),
    # 図・表の参照の番号の直後の上付きは、直前の数字を指数の底とみなさない（番号だけ。本文の閉じ括弧があれば番号の形）。英語の参照・
    # 並びの番号・語の一部の「地図1」も。番号で終わらない直前（「図1-」の「-」・「図1.5」の小数）と、符号で始まる上付き・直後の
    # 演算の記号は今までどおり指数
    ("結果は図1", "1", "に示す", ["bare"]), ("表2", "3", "を見る", ["bare"]), ("see Fig. 2", "1", " and", ["bare"]),
    ("Table 2", "2", "", ["bare"]), ("図１", "１", "", ["bare"]), ("図12", "3", "", ["bare"]), ("図1、2", "3", "", ["bare"]),
    ("図1～3", "2", "", ["bare"]), ("図1と表2", "3", "", ["bare"]), ("地図1", "2", "", ["bare"]), ("図1", "1", ")", ["strong"]),
    ("図1", "1, 2", "", ["bare", "bare"]), ("図1-", "2", "", ["exponent"]), ("図1.5", "2", "", ["exponent"]),
    ("図1", "\u22121", "", ["exponent"]), ("図1", "2", "+c", ["exponent"]),
])
def test_sup_mark_kinds(before, sup, after, kinds):
    """上付きの続きの候補の種類（_sup_marks）: 符号 > 番号の形 > 直前の「注」 > 指数・単位 > 番号だけ。数字と区切りだけの続きは
    続き全体で 1 つの種類。リンクの範囲は前後の空白を含めない。"""
    from jasme_jats.linker import _sup_marks
    plain = before + sup + after
    marks = _sup_marks(plain, len(before), len(before) + len(sup), sup)
    assert [m.kind for m in marks] == kinds
    assert all(plain[m.start:m.end] == plain[m.start:m.end].strip() for m in marks)


@pytest.mark.parametrize("before, sup, after, shaped", [
    ("である", "1)", "。", [True]), ("補足がある", "註1", "。", [True]), ("を考える", "1,2)", "。", [True, True]),
    ("変数 x", "2)", "", [True]), ("ある", "1)2", "", [True, False]), ("括弧である", "1", ")。", [False]),
    ("述べる", "3", "）。", [False]), ("議論もある", "1, 2", ")", [False, False]), ("", "−1)", "", [False]),
    ("本文の注", "1", "も", [False]), ("番号だけの", "2", "は", [False]),
])
def test_sup_mark_shaped(before, sup, after, shaped):
    """論文の注番号の書き方の判定（note_style）に数える shaped は、上付きの文字だけで番号の形がはっきりした注番号（「注」「註」で
    始まる・閉じ括弧で終わる）だけ。上付きの「1」＋本文の「)」（strong。リンクはする）、符号で始まるもの、直前が「注」のものは偽。"""
    from jasme_jats.linker import _sup_marks
    plain = before + sup + after
    marks = _sup_marks(plain, len(before), len(before) + len(sup), sup)
    assert [m.shaped for m in marks] == shaped
    assert all(m.kind == "strong" for m in marks if m.shaped)


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
    assert all(len(m) <= 140 for m in figs + tabs)        # 利用者が読む記録は短く（1 件 140 字まで）
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
    ("同々図1を見る", "fig", {1: "F1"}, [], 1),     # 「々」も漢字（RE_KANJI）
    # 英語の参照は、直前が漢字でも語の一部とみなさない
    ("実験結果Fig. 1を見る", "fig", {1: "F1"}, [("Fig. 1", "F1")], 0),
    ("実験結果Table 1を見る", "table", {1: "T1"}, [("Table 1", "T1")], 0),
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


def sup_atom(text_):
    return Atom(kind="text", text=text_, fmt=frozenset({"sup"}))


def plain_atom(text_):
    return Atom(kind="text", text=text_)


def test_float_refs_stop_before_superscript():
    """「図1」の直後に上付きの注番号「1)」が続くと、plain() では「図11)」になる。参照は上付きの手前で切り、図1 にリンクする
    （「図11 に対応する図が見つからない」にしない）。並びの番号（「図1、2」＋上付きの「3)」）も同じ。上付きの「1)」「3)」は、その後の
    fn_marks で注番号になる（番号だけの上付きの数字の扱いは test_fn_marks_after_float_number）。番号が上付きの文字で始まるもの
    （「図」＋上付きの「12」）は切らない（今までどおり）。"""
    lk = Linker(ArticlePlan())
    p = Para(src="d1", atoms=[plain_atom("結果を図1"), sup_atom("1)"), plain_atom("に示す。図1、2"), sup_atom("3)"),
                              plain_atom("と図"), sup_atom("12"), plain_atom("も見る。")])
    lk.float_refs(p, RE_FIGREF, {1: "F1", 2: "F2", 12: "F12"}, "fig", "図")
    assert [(a.text, a.link.attrs["rid"]) for a in p.atoms if a.link is not None] == [
        ("図1", "F1"), ("図1", "F1"), ("2", "F2"), ("図", "F12"), ("12", "F12")]
    assert lk.unresolved == []
    lk.fn_marks(p, {1: "fn1", 3: "fn3"})
    assert [(a.text, a.link.attrs["rid"]) for a in p.atoms if a.link is not None and a.link.attrs["ref-type"] == "fn"] == [
        ("1)", "fn1"), ("3)", "fn3")]
    # 語の中の参照の判定も、切った番号で記録する（「地図1」＋上付きの「1)」）
    plan = ArticlePlan()
    lk = Linker(plan)
    q = Para(src="d2", atoms=[plain_atom("地図1"), sup_atom("1)"), plain_atom("を見る。")])
    lk.float_refs(q, RE_FIGREF, {1: "F1"}, "fig", "図")
    assert [d.message.split("」", 1)[0] for d in plan.decisions] == ["「図1"] and lk.unresolved == []
    # 番号の図がない「見つからない」（3 章）の文脈も、切った参照（「図51)」ではなく「図5」）
    lk = Linker(ArticlePlan())
    r = Para(src="d3", atoms=[plain_atom("図5"), sup_atom("1)"), plain_atom("を見る。")])
    lk.float_refs(r, RE_FIGREF, {1: "F1"}, "fig", "図")
    assert lk.unresolved == [("fig", "d3", "図5", "図5 に対応する図が見つからない")]
    # 先頭の番号の途中で切ったときは、上付きの後ろの並びの番号（「、2」）はリンクしない（今の限界。docs/DESIGN.md の 6 章）。「と図2」
    # のように「図」の付いたものは、上付きの手前から探し直すので、次の参照としてリンクする。上付きの文字にリンク（Word のハイパー
    # リンクなど）があっても、上付きの手前で切る（「図23」にしない）
    lk = Linker(ArticlePlan())
    href = LinkSpec(kind="uri", attrs={"href": "https://example.org/"}, origin="word")
    q = Para(src="d4", atoms=[plain_atom("図1"), sup_atom("1"), plain_atom("、2と図2を見る。図2"),
                              Atom(kind="text", text="3", fmt=frozenset({"sup"}), link=href), plain_atom("も見る。")])
    lk.float_refs(q, RE_FIGREF, {1: "F1", 2: "F2"}, "fig", "図")
    assert [(a.text, a.link.attrs["rid"]) for a in q.atoms if a.link is not None and a.link.kind == "xref"] == [
        ("図1", "F1"), ("図2", "F2"), ("図2", "F2")]
    assert lk.unresolved == []


def test_figure_ref_before_superscript_note_converts(journal, meta, tmp_path):
    """変換の全体でも、「図1」＋上付きの「1)」は図1 と注 1 の両方にリンクし（3 章に「図11」を出さない）、直前が漢字の英語の参照
    （「実験結果Fig. 1」）も図1 にリンクする。不変性チェック・DTD・J-STAGE のチェックは合格。"""
    def parts(b):
        rid = b.add_image("links_case_fig1.png", mf.png_bytes("Case figure 1"))
        return [mf.para(S["sec1"], "１．はじめに"),
                mf.para(S["body"], "結果を図1", mf.run("1)", sup=True), "に示す。実験結果Fig. 1も見る。"),
                mf.para(S["body"], mf.drawing(rid, 2880000, 1800000, 961), jc="center"),
                mf.para(S["fig_cap"], "図1\u3000架空の図"),
                mf.para(S["fn_head"], "注"), mf.para(S["body"], "1) 一つ目の架空の注。")]
    path = tmp_path / "figsup.docx"
    mf.make_article(path, "リンクの境界の検証用文書", parts)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and res.jstage_issues == []
    assert same_links(*para_links(load(res), "結果を図1", ("fig", "fn")),
                      [("結果を", "図1", "F1"), ("図1", "1)", "fn1"), ("実験結果", "Fig. 1", "F1")])
    assert [u for u in res.unresolved_after if u[0] == "fig"] == []


@pytest.mark.parametrize("bare_notes", [True, False])
def test_fn_marks_after_float_number(bare_notes):
    """図・表の参照の番号の直後の番号だけの上付き（キャプションの「図1²　…」・本文の「表2³」）は、直前の数字を指数の底とみなさない
    （点検 2 回目に直した。それまでは直前が数字なので指数・単位とみなした）: 番号だけの論文では注にリンクし（0.26.0 と同じ）、
    「1)」の書き方の論文では番号だけの数字として 1 件ずつ記録する（指数・単位の記録にしない）。キャプションの番号は、上付きの数字も
    含めて読むので、この形の図の番号は「図12」になる（structure.py の限界。修正計画の H の「残る限界」）。"""
    plan = ArticlePlan()
    lk = Linker(plan)
    lk.bare_notes = bare_notes
    p = Para(src="d1", atoms=[plain_atom("図1"), sup_atom("2"), plain_atom("\u3000架空の図（表2"), sup_atom("3"),
                              plain_atom("も参照）")])
    lk.fn_marks(p, {2: "fn2", 3: "fn3"})
    got = [(a.text, a.link.attrs["rid"]) for a in p.atoms if a.link is not None]
    msgs = [d.message for d in plan.decisions]
    if bare_notes:
        assert got == [("2", "fn2"), ("3", "fn3")] and msgs == []
    else:
        assert got == [] and [RE_ITEM.findall(m) for m in msgs] == [[("2", "1")], [("3", "1")]]
        assert all("番号だけの形" in m and "指数" not in m for m in msgs)
    assert lk.unresolved == []


@pytest.mark.parametrize("marked", [False, True])
def test_figure_number_then_superscript_note_converts(marked, journal, meta, tmp_path):
    """変換の全体で、図・表の参照の番号の直後の上付きの注番号（本文の「図1¹」「表1²」、表のセルの「図1³」）は、図・表と注の両方に
    リンクする（点検 2 回目）。番号だけの論文（marked が偽）では、番号だけの上付きも注にリンクする（0.26.0 と同じ）。「1)」の書き方の
    論文（marked）では、上付きの「1」＋本文の「)」（「図1¹)」）を注にリンクし、番号だけの「表1²」「図1³」は番号だけの数字として
    記録する。不変性チェック・DTD・J-STAGE のチェックは合格。"""
    def parts(b):
        rid = b.add_image("links_case_fig1.png", mf.png_bytes("Case figure 1"))
        body = [mf.para(S["body"], "結果は図1", mf.run("1", sup=True), ")に示す。" if marked else "に示す。", "表1",
                        mf.run("2", sup=True), "も見る。")]
        if marked:
            body.append(mf.para(S["body"], "番号の形の注である", mf.run("3)", sup=True), "。"))
        return [mf.para(S["sec1"], "１．はじめに"), *body,
                mf.para(S["body"], mf.drawing(rid, 2880000, 1800000, 962), jc="center"),
                mf.para(S["fig_cap"], "図1\u3000架空の図"), mf.para(S["tab_cap"], "表1\u3000架空の表"),
                mf.table([[mf.cell("観点"), mf.cell("内容")],
                          [mf.cell("架空"), mf.cell(mf.para(S["body"], "セルの図1", mf.run("3", sup=True), "を参照"))]]),
                mf.para(S["fn_head"], "注"), *(mf.para(S["body"], n) for n in NOTES3)]
    path = tmp_path / "fignum.docx"
    mf.make_article(path, "リンクの境界の検証用文書", parts)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and res.jstage_issues == []
    assert _mechanical(path, journal)[2].bare_notes is not marked
    root = load(res)
    kinds = ("fig", "table", "fn")
    [cell] = [td for td in root.iter("td") if text(td).startswith("セルの図1")]
    got_cell = xref_positions(cell, kinds)
    if marked:
        assert same_links(*para_links(root, "結果は図1", kinds),
                          [("結果は", "図1", "F1"), ("図1", "1", "fn1"), (")に示す。", "表1", "T1")])
        assert same_links(text(cell), got_cell, [("セルの", "図1", "F1")])
        assert [RE_ITEM.findall(m) for m in records(res, "結果は図1")] == [[("2", "1")]]
        assert [RE_ITEM.findall(m) for m in records(res, "セルの図1")] == [[("3", "1")]]
        assert all("指数" not in m for m in records(res, "結果は図1") + records(res, "セルの図1"))
    else:
        assert same_links(*para_links(root, "結果は図1", kinds),
                          [("結果は", "図1", "F1"), ("図1", "1", "fn1"), ("に示す。", "表1", "T1"), ("表1", "2", "fn2")])
        assert same_links(text(cell), got_cell, [("セルの", "図1", "F1"), ("セルの図1", "3", "fn3")])
        assert records(res, "結果は図1") == [] and records(res, "セルの図1") == []
    assert [u for u in res.unresolved_after if u[0] in ("fig", "table", "fn")] == []


def test_fn_marks_without_run_link_bare_numbers():
    """run（論文の書き方の判定）を通らずに fn_marks を呼んだときは、番号だけの上付きの数字も注番号とみなす（0.26.0 までと同じ。
    Linker.__init__ の bare_notes）。"""
    lk = Linker(ArticlePlan())
    assert lk.bare_notes is True
    p = Para(src="d1", atoms=[plain_atom("番号だけの"), sup_atom("2"), plain_atom("は注である。")])
    lk.fn_marks(p, {2: "fn2"})
    assert [(a.text, a.link.attrs["rid"]) for a in p.atoms if a.link is not None] == [("2", "fn2")]


def test_note_style_ignores_note_list_and_references(journal, meta, tmp_path):
    """論文の書き方の判定には、注の一覧（番号を上付きの「1)」で書いたもの）と引用文献の段落の上付きは数えない: 本文の番号だけの ¹ は
    リンクする（番号だけの論文のまま）。"""
    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "番号だけの主張である", mf.run("1", sup=True), "。"),
                mf.para(S["fn_head"], "注"), mf.para(S["body"], mf.run("1)", sup=True), " 一つ目の架空の注。")]
    path = tmp_path / "style.docx"
    mf.make_article(path, "リンクの境界の検証用文書", parts, refs=lambda b: [
        mf.para(S["ref"], "試験七郎（2023）．「架空の論文", mf.run("1)", sup=True), "」．『架空誌』，第3巻，pp.1-2．")])
    assert _mechanical(path, journal)[2].bare_notes is True
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    assert same_links(*para_links(load(res), "番号だけの主張である"), [("主張である", "1", "fn1")])


R2_TITLE = "ルート2の注番号の検証用文書"
R2_P1 = "これは一つ目の架空の主張であり、学習の過程を考える手がかりになる"
R2_P2 = "二つ目の架空の主張であり、授業の工夫を考える手がかりになる"
R2_P3 = "三つ目の架空の主張であり、評価の方法を考える手がかりになる"


def route2_case(tmp_path, variant):
    """ルート2 の注番号の書き方の検証: 番号だけの上付きの注（3 つ）の docx と、注番号を「1)」の形で組んだ出版版 PDF の文字
    （extract_pages の代わり）。3 つ目の段落には、注と関係のない誤字（docx「正し」→ PDF「正しい」）を置く。variant: all は 3 つの
    段落とも PDF にある。partial は 2 つ目の段落が PDF では別の文（PDF に見つからない）。cell は 2 つ目の注番号が表のセルの中
    （ルート2 はセルを直さない）。"""
    def parts(b):
        out = [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], R2_P1, mf.run("1", sup=True), "。")]
        if variant == "cell":
            out += [mf.para(S["tab_cap"], "表1\u3000架空の表"),
                    mf.table([[mf.cell("観点"), mf.cell("内容")],
                              [mf.cell("架空"), mf.cell(mf.para(S["body"], "授業の工夫", mf.run("2", sup=True)))]]),
                    mf.para(S["body"], "表1のとおり、架空の観点を整理した。")]
        else:
            out.append(mf.para(S["body"], R2_P2, mf.run("2", sup=True), "。"))
        out += [mf.para(S["body"], R2_P3, mf.run("3", sup=True), "。ここは正し表記である。"),
                mf.para(S["sec1"], "２．おわりに"), mf.para(S["body"], "架空のまとめであり、今後の課題を考える手がかりになる。"),
                mf.para(S["fn_head"], "注")]
        return out + [mf.para(S["body"], mf.run(str(k), sup=True), f" {t}の架空の注である。")
                      for k, t in ((1, "一つ目"), (2, "二つ目"), (3, "三つ目"))]
    path = tmp_path / f"{variant}.docx"
    mf.make_article(path, R2_TITLE, parts)
    second = {"all": f"{R2_P2}2)。", "partial": "まったく別の架空の文章が出版版ではここに入っており、内容も語句も大きく異なっている2)。",
              "cell": "表1　架空の表\n観点 内容\n架空 授業の工夫2)\n表1のとおり、架空の観点を整理した。"}[variant]
    page = (f"{R2_TITLE}\n―検証用の小さな論文―\n１．はじめに\n{R2_P1}1)。\n{second}\n{R2_P3}3)。ここは正しい表記である。\n"
            "２．おわりに\n架空のまとめであり、今後の課題を考える手がかりになる。\n注\n1 一つ目の架空の注である。\n"
            "2 二つ目の架空の注である。\n3 三つ目の架空の注である。\n引用および参考文献\n"
            "試験六郎（2024）．「小さな論文」．『架空誌』，第5巻，pp.9-10．\n")
    return path, [page]


@pytest.mark.parametrize("variant", ["all", "partial", "cell"])
def test_route2_note_style_change(variant, journal, meta, tmp_path, monkeypatch):
    """ルート2 で、番号だけの注の docx を「1)」の形の出版版 PDF で補うときの今の振る舞い（修正計画の H の「残る限界」・
    docs/DESIGN.md の 4.4 と 7 章）。直した docx では注番号が上付きの「1)」の形になり、論文の書き方の判定（note_style）が「1)」の
    書き方に変わる。注番号のある段落をすべて直せるとき（all）は、すべて直して注のリンクも残る。1 つでも直さない段落（PDF に見つから
    ない段落・表のセル）があると、その段落の番号だけの注番号のリンクが直した docx で消えるので、pdfdocx の守り（_lost）が
    すべての直しを止める（注と関係のない誤字の直しも。0.26.0 は直していた）。XML は元の docx のまま（注のリンクも元のまま）で、
    要確認（pdf_unfixed）が出る。直すなら、pdfdocx が直した docx を読み直すときと最後の変換で、元の docx の書き方の判定を使う
    （B2.1 の後。修正計画の H）。そのときは、このテストの partial・cell の期待を逆にする。"""
    from jasme_jats import pdfmatch
    from jasme_jats.pdfdocx import STRUCTURE_REASON
    path, pages = route2_case(tmp_path, variant)
    assert _mechanical(path, journal)[2].bare_notes is True
    monkeypatch.setattr(pdfmatch, "extract_pages", lambda p: pages)
    (tmp_path / "dummy.pdf").write_bytes(b"%PDF-1.4\n")
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", pdf_path=tmp_path / "dummy.pdf", route="pdf",
                                               convert_metafiles=False))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    fixes = [(f.old, f.new, f.applied, f.reason) for f in res.docx_fix.fixes]
    xrefs = [(text(x), x.get("rid")) for x in load(res).iter("xref") if x.get("ref-type") == "fn"]
    keys = [a.key for a in actions(res)]
    if variant == "all":
        assert fixes == [("", ")", True, "")] * 3 + [("", "い", True, "")]
        assert xrefs == [("1)", "fn1"), ("2)", "fn2"), ("3)", "fn3")] and "pdf_unfixed" not in keys
        assert res.supplement.ok            # 補完の確かめ（fidelity.verify_supplement）
    else:
        assert fixes == [("", ")", False, STRUCTURE_REASON)] * 2 + [("", "い", False, STRUCTURE_REASON)]
        assert xrefs == [("1", "fn1"), ("2", "fn2"), ("3", "fn3")] and "pdf_unfixed" in keys
        assert any(R2_P3 + "3。ここは正し表記である。" == text(q) for q in load(res).iter("p"))


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


# ============================================================================= K3: キャプションの 2 段落目以降
def test_caption_more_is_linked(journal, meta, tmp_path):
    """図・表のキャプションの 2 段落目以降（出典の行など）の引用（試験（2024））・URL・上付きの注番号も、1 段落目と同じくリンクする
    （linker.body_paragraphs が caption_more も文脈 "caption" で返す）。キャプションの中の「図1」「表1」は、1 段落目と同じく
    図・表の参照にしない。不変性チェック・DTD・J-STAGE のチェックは合格。"""
    def parts(b):
        rid = b.add_image("links_k3_fig1.png", mf.png_bytes("K3 figure 1"))
        return [mf.para(S["sec1"], "１．はじめに"),
                mf.para(S["body"], mf.drawing(rid, 2880000, 1800000, 963), jc="center"),
                mf.para(S["fig_cap"], "図1　架空の図"),
                mf.para(S["fig_cap"], "出典：試験（2024）．http://example.com/fig1 を見る", mf.run("1)", sup=True), "（表1と同じ）"),
                mf.para(S["tab_cap"], "表1　架空の表"),
                mf.para(S["tab_cap"], "出典：試験（2024）．http://example.com/tab1"),
                mf.table([[mf.cell("観点"), mf.cell("内容")], [mf.cell("架空"), mf.cell("架空の内容")]]),
                mf.para(S["fn_head"], "注"), mf.para(S["body"], NOTES3[0])]
    path = tmp_path / "k3.docx"
    mf.make_article(path, "リンクの境界の検証用文書", parts)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and res.jstage_issues == []
    root = load(res)
    [fig] = list(root.iter("fig"))
    [tab] = list(root.iter("table-wrap"))
    fig_p = fig.findall("caption/p")
    tab_p = tab.findall("caption/p")
    assert [text(p) for p in fig_p] == ["図1　架空の図", "出典：試験（2024）．http://example.com/fig1 を見る1)（表1と同じ）"]
    assert [(x.tag, text(x)) for x in fig_p[1].iter() if x.tag in ("xref", "uri")] == [
        ("xref", "2024"), ("uri", "http://example.com/fig1"), ("xref", "1)")]
    assert [(x.tag, text(x)) for x in tab_p[1].iter() if x.tag in ("xref", "uri")] == [
        ("xref", "2024"), ("uri", "http://example.com/tab1")]
    assert fig_p[1].find("xref[@ref-type='table']") is None



# ============================================================================= K4: 枝番つき・番号が重なる図表のキャプション
def floats_article(tmp_path, body, fig_caps=(), tab_caps=(), name="k4"):
    """本文の段落（XML の一覧）の後ろに、図（画像と図キャプション）と表（表キャプションと表）を並べた小さな論文。"""
    def parts(b):
        out = [mf.para(S["sec1"], "１．はじめに"), *body]
        for k, cap in enumerate(fig_caps, 1):
            rid = b.add_image(f"links_k4_fig{k}.png", mf.png_bytes(f"K4 figure {k}"))
            out += [mf.para(S["body"], mf.drawing(rid, 2880000, 1800000, 970 + k), jc="center"), mf.para(S["fig_cap"], cap)]
        for cap in tab_caps:
            out += [mf.para(S["tab_cap"], cap), mf.table([[mf.cell("観点"), mf.cell("内容")], [mf.cell("架空"), mf.cell("内容")]])]
        return out
    path = tmp_path / f"{name}.docx"
    mf.make_article(path, "リンクの境界の検証用文書", parts)
    return path


def float_links(root, prefix):
    """文字が prefix で始まる段落の、図・表への参照: [(文字, ref-type, rid)]。"""
    [q] = [q for q in root.iter("p") if text(q).startswith(prefix)]
    return [(text(x), x.get("ref-type"), x.get("rid")) for x in q.iter("xref") if x.get("ref-type") in ("fig", "table")]


def test_branch_figure_numbers_are_not_linked(journal, meta, tmp_path):
    """図1-1・図1-2・図2.1 のように枝番のあるキャプションがあるとき、「図1-1」「図1-2」「図1」「図2」「図2.1」の参照はどれもリンクしない
    （どの枝番の図か決められない。今までは図1-1・図1-2 が両方「図1」になり、後の図にリンクしていた）。枝番のない図3 の参照はリンクする。
    判断の一覧（4 章）に 1 件ずつ記録し、要確認の知らせを 1 つ出す（終了コードは 0）。不変性チェック・DTD・J-STAGE のチェックは合格。"""
    body = [mf.para(S["body"], "図1-1と図1-2を比べる。図1も見る。図2.1を参照する。図2と図3も見る。"),
            mf.para(S["body"], "図1-2、図3は架空である。")]
    path = floats_article(tmp_path, body, ["図1-1　架空の図", "図1-2　もう一つの図", "図2.1　枝番の図",
                                                     "図3　ふつうの図"])
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and res.jstage_issues == []
    root = load(res)
    assert float_links(root, "図1-1と図1-2を比べる") == [("3", "fig", "F4")]
    assert float_links(root, "図1-2、図3は") == [("3", "fig", "F4")]
    plan = res.plan
    assert [(u.word, u.text) for u in plan.float_unlinked] == [
        ("図", "図1-1"), ("図", "図1-2"), ("図", "図1"), ("図", "図2.1"), ("図", "図2"), ("図", "図1-2")]
    recs = [d for d in plan.decisions if d.category == "figure" and not d.applied and "リンクしなかった" in d.message]
    assert len(recs) == 6 and all("link_figure" in d.message for d in recs)
    [act] = [a for a in actions(res) if a.key == "float_ref"]
    assert act.level == TO_CHECK and "図1-1" in act.top and "図2.1" in act.top and not res.needs_action
    assert "図1-1" in act.box_detail and "図1-1" in act.cli
    assert "手順" not in act.top + act.box_detail + act.cli + act.checklist
    # 内部の操作名を出さず、そのままでもよいこと・付けるなら XML のどこをどうするかを言う（F13）
    assert "link_figure" not in act.checklist
    for text in (act.top, act.box_detail, act.cli):
        assert "link_" not in text and "登載できる" in text and 'ref-type="fig"' in text and "xref" in text, text
    # 利用者が取れる手段の文: 手で足す・AI による補完を使う設定で変換し直す（回答を編集するようには読めない）。図の id の場所も言う
    assert "AI による補完を使う設定" in act.top and "変換し直すと" in act.top and "AI による補完の回答" not in act.top
    assert step("ai_choose") + "変換し直すと" in act.box_detail and "AI による補完の回答" not in act.box_detail     # 画面ごとの語は colab が置き換える
    assert "--ai manual か --ai api を指定して変換し直すと" in act.cli
    for text in (act.top, act.box_detail):
        assert '<fig id="…">' in text and "<table-wrap id=" in text, text
        assert "> （" not in text and "`（表への" in text or ">（表への" in text, text    # タグの後ろに余分な空白がない
    assert " （表への参照は" not in act.top + act.box_detail
    # レポート（Markdown）では、生のタグは Markdown を HTML にすると消えるので、バッククォートで囲む。画面の枠と標準エラーは囲まない
    assert '`<xref ref-type="fig" rid="図の id">`' in act.top and '`<fig id="…">`' in act.top and "`<xref>`" in act.checklist
    assert "`" not in act.box_detail and "`" not in act.cli
    from jasme_jats.colab import report_details
    shown = report_details(act.top + "\n" + act.checklist)
    assert "xref" in shown and "&lt;xref" in shown and "<xref" not in shown.replace("&lt;xref", "")
    # 変換レポートの全文でも、冒頭・14 章の文のタグは HTML にしても残る
    page = report_details(res.report_path.read_text(encoding="utf-8"))
    assert "&lt;xref" in page and "&lt;fig id" in page
    assert "float_ref" in [a.key for a in actions(res)]
    assert any("リンクしなかった図・表の参照" in line for line in act.checklist.splitlines())


def test_duplicate_figure_numbers_are_not_linked(journal, meta, tmp_path):
    """同じ番号の図のキャプションが 2 つ（図1 と図1）あるとき、「図1」の参照はリンクしない（今までは後のキャプションに黙ってリンクした）。
    表も同じ（表2 が 2 つ）。重ならない番号の図2・表1 の参照はリンクする。"""
    body = [mf.para(S["body"], "図1と図2を見る。表1と表2を見る。")]
    path = floats_article(tmp_path, body, ["図1　一つ目の図", "図1　二つ目の図", "図2　三つ目の図"],
                          ["表1　一つ目の表", "表2　二つ目の表", "表2　三つ目の表"])
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and res.jstage_issues == []
    assert float_links(load(res), "図1と図2を見る") == [("2", "fig", "F3"), ("表1", "table", "T1")]
    assert [(u.word, u.text) for u in res.plan.float_unlinked] == [("図", "図1"), ("表", "表2")]
    msgs = [d.message for d in res.plan.decisions if not d.applied and "リンクしなかった" in d.message]
    assert len(msgs) == 2 and "キャプションが複数ある" in msgs[0] and "図1" in msgs[0]
    assert [a.key for a in actions(res) if a.key == "float_ref"] == ["float_ref"]


def test_branch_ref_not_range_only_with_branch_captions(journal, meta, tmp_path):
    """枝番のキャプションがない論文では、「図1-2」は今までどおり範囲（図1〜図2）として読み、図1 と図2 にリンクする（知らせも出ない）。"""
    body = [mf.para(S["body"], "図1-2を見る。表1、2も見る。")]
    path = floats_article(tmp_path, body, ["図1　一つ目の図", "図2　二つ目の図"], ["表1　一つ目の表", "表2　二つ目の表"])
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    assert float_links(load(res), "図1-2を見る") == [("図1", "fig", "F1"), ("2", "fig", "F2"), ("表1", "table", "T1"),
                                                  ("2", "table", "T2")]
    assert res.plan.float_unlinked == [] and [a for a in actions(res) if a.key == "float_ref"] == []


def test_branch_table_numbers_only_affect_tables(journal, meta, tmp_path):
    """枝番があるのは表だけ（表1-1・表1-2）のときは、表の参照だけリンクしない。図の「図1-2」は範囲のままリンクする。"""
    body = [mf.para(S["body"], "図1-2と表1-2と表3を見る。")]
    path = floats_article(tmp_path, body, ["図1　一つ目の図", "図2　二つ目の図"],
                          ["表1-1　一つ目の表", "表1-2　二つ目の表", "表3　三つ目の表"])
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    assert float_links(load(res), "図1-2と表1-2") == [("図1", "fig", "F1"), ("2", "fig", "F2"), ("3", "table", "T3")]
    assert [(u.word, u.text) for u in res.plan.float_unlinked] == [("表", "表1-2")]


def test_caption_label_branch():
    """キャプションの番号と枝番（structure.caption_label）: 区切りは「-」「‐」「－」「.」「．」など、後ろに数字が続くときだけ。"""
    from jasme_jats.structure import RE_FIGCAP, RE_TABCAP, caption_label
    def cap(t):
        return Para(src="d1", atoms=[Atom(kind="text", text=t)])
    for t, want in [("図1-2　架空", (1, True)), ("図２．１　架空", (2, True)), ("図３－４　架空", (3, True)),
                    ("図1‐2　架空", (1, True)), ("Figure 1-2 caption", (1, True)), ("図1　架空", (1, False)),
                    ("図1.　架空", (1, False)), ("図1-　架空", (1, False)), ("図 12：架空", (12, False)),
                    ("架空の図", (None, False))]:
        assert caption_label(cap(t), RE_FIGCAP) == want, t
    assert caption_label(cap("表2-3　架空"), RE_TABCAP) == (2, True)


@pytest.mark.parametrize("plain, skip, want_links, want_unlinked", [
    # 枝番つきのキャプションがある論文（branch）: 番号のすぐ後ろの枝番は 1 つの参照。リンクしない
    ("図1-2を見る", {1: (["図1-1", "図1-2"], True)}, [], ["図1-2"]),
    ("図1、図1-2と図3を見る", {1: (["図1-1", "図1-2"], True)}, [("3", "F3")], ["図1", "図1-2"]),
    ("図3-4と図4.2を見る", {4: (["図4.1"], True)}, [], ["図3-4", "図4.2"]),
    # 枝番の形でない並びは範囲のまま（空白を挟む・全角の「〜」）。並びの番号は番号だけにリンクする
    ("図3 - 5を見る。図3〜4も見る", {}, [("図3", "F3"), ("5", "F5"), ("図3", "F3"), ("4", "F4")], []),
])
def test_float_refs_branch_rules(plain, skip, want_links, want_unlinked):
    """float_refs の skip・branch: 枝番の形（番号のすぐ後ろの「-2」「.1」）は、枝番つきのキャプションがある論文では 1 つの参照として
    リンクしない。skip の番号の参照もリンクしない。リンクした参照の文字と rid、リンクしなかった参照の文字を確かめる。"""
    plan = ArticlePlan()
    lk = Linker(plan)
    q = Para(src="d1", atoms=[Atom(kind="text", text=plain)])
    ids = {n: f"F{n}" for n in (1, 2, 3, 4, 5) if n not in skip}
    lk.float_refs(q, RE_FIGREF, ids, "fig", "図", skip, True)
    got = [(a.text, a.link.attrs["rid"]) for a in q.atoms if a.link is not None]
    assert got == want_links
    assert [u.text for u in plan.float_unlinked] == want_unlinked
    assert q.plain() == plain


# ---- F12: 枝番の区切りは 1 か所の定義（structure.CAP_BRANCH_SEP）。キャプションの枝番・<label> の切り方・参照の枝番が一致する
BRANCH_SEPS = ["-", "‐", "‑", "‒", "–", "—", "―", "−", ".", "－", "．"]


@pytest.mark.parametrize("sep", BRANCH_SEPS)
def test_branch_separator_is_one_definition(sep):
    """枝番とみなすキャプションの番号（structure.caption_label）・<label> に切り分ける番号（builder.RE_LABEL_SPLIT）・参照の枝番
    （linker.RE_BRANCH_REF）が、同じ区切りで枝番を読む（en ダッシュなどでキャプションは枝番とみなすのに <label> は「図1」で切っていた）。"""
    from jasme_jats.builder import RE_LABEL_SPLIT
    from jasme_jats.linker import RE_BRANCH_REF
    from jasme_jats.structure import RE_FIGCAP, caption_label
    cap = f"図1{sep}2　架空の図"
    assert caption_label(Para(src="d1", atoms=[Atom(kind="text", text=cap)]), RE_FIGCAP) == (1, True)
    assert RE_LABEL_SPLIT.match(cap).group(2) == f"図1{sep}2"
    assert RE_BRANCH_REF.match(f"{sep}2") is not None


@pytest.mark.parametrize("split", [True, False])
def test_en_dash_branch_caption_label_and_links(split, journal, meta, tmp_path):
    """キャプション「図1–2」（en ダッシュ）は枝番なので、<label> も「図1–2」で切り（split_labels のとき）、参照「図1–2」「図1」は
    リンクせず要確認で知らせる。split_labels=False では <label> を作らず、キャプションの文字は変わらない。"""
    body = [mf.para(S["body"], "図1–2を見る。図1も見る。図3を見る。")]
    path = floats_article(tmp_path, body, ["図1–1　最初の図", "図1–2　次の図", "図3　別の図"])
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False, split_labels=split))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    root = load(res)
    caps = ["".join(c.itertext()) for c in root.iter("caption")]
    if split:
        assert [text(x) for x in root.iter("label") if text(x).startswith("図")] == ["図1–1", "図1–2", "図3"]
        assert caps == ["最初の図", "次の図", "別の図"]
    else:
        assert not [x for x in root.iter("label") if text(x).startswith("図")]
        assert caps == ["図1–1　最初の図", "図1–2　次の図", "図3　別の図"]
    assert float_links(root, "図1–2を見る") == [("図3", "fig", "F3")]
    assert sorted(u.text for u in res.plan.float_unlinked) == ["図1", "図1–2"]
    assert "float_ref" in [a.key for a in actions(res)]


# ---- G4: 枝番とみなす数字は 1〜2 桁（直後に数字が続かない）。「図1―2019年度の推移」の年は枝番にしない
@pytest.mark.parametrize("sep", BRANCH_SEPS)
def test_branch_number_is_short_in_all_three_definitions(sep):
    """枝番の数字は 1〜2 桁で、直後に数字が続かないもの（CAP_BRANCH_NUM）。年のような長い数字は、キャプションの枝番・<label> に
    切り分ける番号・参照の枝番のどれでも枝番にしない（今までは <label> が「図1―2019」になった）。短い数字は今までどおり枝番。"""
    from jasme_jats.builder import RE_LABEL_SPLIT
    from jasme_jats.linker import RE_BRANCH_REF
    from jasme_jats.structure import RE_FIGCAP, caption_label
    for digits, branch in (("2019", False), ("123", False), ("2", True), ("12", True), ("１２", True)):
        cap = f"図1{sep}{digits}年度の推移"
        assert caption_label(Para(src="d1", atoms=[Atom(kind="text", text=cap)]), RE_FIGCAP) == (1, branch), cap
        assert RE_LABEL_SPLIT.match(cap).group(2) == (f"図1{sep}{digits}" if branch else "図1"), cap
        assert (RE_BRANCH_REF.match(f"{sep}{digits}") is not None) == branch, cap


@pytest.mark.parametrize("split", [True, False])
def test_year_after_dash_is_not_a_branch(split, journal, meta, tmp_path):
    """G4: キャプション「図1―2019年度の推移」の <label> は「図1」になり（split_labels のとき）、枝番のない図として本文の「図1」を
    リンクする。split_labels=False ではキャプションの文字は変わらない。"""
    body = [mf.para(S["body"], "図1を見る。")]
    path = floats_article(tmp_path, body, ["図1―2019年度の推移", "図2　別の図"], name="g4")
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False, split_labels=split))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    root = load(res)
    if split:
        assert [text(x) for x in root.iter("label") if text(x).startswith("図")] == ["図1", "図2"]
        assert [text(c) for c in root.iter("caption")] == ["―2019年度の推移", "別の図"]
    else:
        assert [text(c) for c in root.iter("caption")] == ["図1―2019年度の推移", "図2　別の図"]
    assert float_links(root, "図1を見る") == [("図1", "fig", "F1")]
    assert not res.plan.float_unlinked


def _float_ref_states(tmp_path, journal, meta):
    """図1 が 2 つあるため、「図1」の参照が 2 か所、リンクされない小さな論文。(docx, 参照の段落 ID) を返す。"""
    body = [mf.para(S["body"], "図1を見る。図1も見る。")]
    path = floats_article(tmp_path, body, ["図1　一つ目の図", "図1　二つ目の図"], [], name="h3")
    _, plan, _ = _mechanical(path, journal)
    src = next(s for s, p in plan.paras.items() if p.plain().startswith("図1を見る"))
    return path, src


def _manual(path, ops, meta, journal, out):
    resp = json.dumps({"operations": ops, "placements": [], "notes": []}, ensure_ascii=False)
    return convert(path, meta, journal, Options(out_dir=out, ai_mode="manual", ai_response=resp, convert_metafiles=False))


def _link_op(src, target, occurrence=1, text="図1"):
    return {"op": "link_figure", "src": src, "text": text, "occurrence": occurrence, "target": target, "role": "", "image": "",
            "mathml": "", "surname": "", "given": "", "reason": "試験", "confidence": "高"}


def _float_ref(res):
    [act] = [a for a in actions(res) if a.key == "float_ref"]
    return act


def test_h3_float_ref_advice_follows_the_ai_state(journal, meta, tmp_path):
    """H3: 図・表の参照のリンクを付けていない箇所の案内は、AI による補完の状態（使っていない・回答待ち・AI を使った後）で文を分ける
    （以前は、回答待ちや AI を使った後にも「AI による補完を使う設定で変換し直すと…」と勧めた）。AI がリンクを付けた参照は残りから除く。"""
    path, src = _float_ref_states(tmp_path, journal, meta)
    # (1) AI を使っていない: AI による補完を使う設定にして変換し直すことを勧める（画面ごとの語は目印）
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "none", convert_metafiles=False))
    assert len(res.plan.float_unlinked) == 2
    act = _float_ref(res)
    assert "AI による補完を使う設定（API か手動）で変換し直すと" in act.top and step("ai_choose") + "変換し直すと" in act.box_detail
    assert "--ai manual か --ai api を指定して変換し直すと" in act.cli
    # (2) 手動で回答待ち: 回答を反映すると AI がリンクを付けること、反映した後に残る分をこの知らせで確かめることを言う。設定の変更は勧めない
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "pending", ai_mode="manual", convert_metafiles=False))
    act = _float_ref(res)
    assert "AI の回答を反映すると" in act.top and "もう一度出る" in act.top and "設定（API か手動）" not in act.top
    assert step("answer_apply") + "と" in act.box_detail and step("ai_choose") not in act.box_detail
    assert "--ai manual --ai-response 回答のファイル を指定して変換し直すと" in act.cli and "--ai manual か --ai api を指定して" not in act.cli
    # (3) AI を使った後、一部だけリンクが付いた: 付いた分は除き、残りは「AI もリンクを付けなかった参照」。設定の変更は勧めない
    res = _manual(path, [_link_op(src, "F1", 1)], meta, journal, tmp_path / "part")
    assert res.fidelity.ok and res.ai.rejected == [] and len(res.plan.float_unlinked) == 1
    assert float_links(load(res), "図1を見る") == [("図1", "fig", "F1")]
    act = _float_ref(res)
    assert "（1 か所）" not in act.top and "対象の参照（1 か所）" in act.box_detail
    for t in (act.top, act.box_detail, act.cli):
        assert "AI もリンクを付けませんでした" in t and "設定（API か手動）" not in t and "ai_choose" not in t, t
        assert "--ai manual か --ai api" not in t
    # (4) 全部にリンクが付いた: 知らせは出ない
    res = _manual(path, [_link_op(src, "F1", 1), _link_op(src, "F2", 2)], meta, journal, tmp_path / "all")
    assert res.plan.float_unlinked == [] and [a for a in actions(res) if a.key == "float_ref"] == []
    # (5) AI の回答が採用されなかった（リンク先がない）: 残りは全部
    res = _manual(path, [_link_op(src, "F99", 1)], meta, journal, tmp_path / "none_ok")
    assert len(res.plan.float_unlinked) == 2 and "AI もリンクを付けませんでした" in _float_ref(res).top
    # (6) 回答を読み込めなかった: AI は反映されていない。設定の変更ではなく回答を反映できたらと言う
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "bad", ai_mode="manual", ai_response="これは JSON ではない",
                                               convert_metafiles=False))
    assert res.ai.error
    act = _float_ref(res)
    assert "AI による補完が反映できていません" in act.top and "AI の回答を反映できたら" in act.top
    assert "設定（API か手動）" not in act.top and "--ai manual か --ai api" not in act.cli


def test_manual_fields_hidden_when_result_was_not_made_in_manual_mode(journal, meta, tmp_path):
    """0.29.0 の 4 回目の点検: AI を使っていない（または API の）結果のまま、変換し直さずに「AI による補完の方法」の欄だけを手動に切り替えても、
    手動の欄（依頼文・「反映」）は出さない（図・表の参照の知らせ float_ref が出ていても。空の依頼文と回答を反映できない「反映」になるため）。
    手動モードで作った結果（依頼文がある）では出る。"""
    from jasme_jats.app import AppState
    path, src = _float_ref_states(tmp_path, journal, meta)
    none = convert(path, meta, journal, Options(out_dir=tmp_path / "none", convert_metafiles=False))
    assert none.ai.mode == "none" and [a for a in actions(none) if a.key == "float_ref"]
    st = AppState(tmp_path / "w")
    st.set_inputs(ai_mode="none")
    st.res = none
    assert not st.answer_box_open
    st.set_inputs(ai_mode="manual")
    assert not st.answer_box_open and st.prompt_text() == ""
    # API の結果も同じ
    done = _manual(path, [_link_op(src, "F1", 1)], meta, journal, tmp_path / "api_like")
    done.ai.mode, done.prompt_path = "api", None
    st.res = done
    assert not st.answer_box_open
    # 手動モードで作った結果（AI を使った後）は、貼り直せるように見える
    done = _manual(path, [_link_op(src, "F1", 1)], meta, journal, tmp_path / "manual_done")
    st.res = done
    assert st.answer_box_open and st.prompt_text()


def test_ai_link_on_lookalike_text_keeps_the_unlinked_reference(journal, meta, tmp_path):
    """0.29.0 の最後の点検: AI がリンクを付けた参照を plan.float_unlinked から除く一致は、段落の中の位置（範囲）を見る。
    リンクの対象でない同じ文字（「地図1」の「図1」）に AI がリンクを付けても、本当にリンクされていない「図1」の要確認 float_ref は消えない。
    AI がその参照そのものにリンクを付ければ消える。"""
    body = [mf.para(S["body"], "地図1を見る。図1も見る。")]
    path = floats_article(tmp_path, body, ["図1　一つ目の図", "図1　二つ目の図"], [], name="fu")
    _, plan, _ = _mechanical(path, journal)
    src = next(s for s, p in plan.paras.items() if p.plain().startswith("地図1"))
    plain = plan.paras[src].plain()
    [ref] = plan.float_unlinked
    assert (ref.word, ref.src, ref.text) == ("図", src, "図1") and plain[ref.start:ref.end] == "図1"
    assert ref.start == plain.index("。図1") + 1                      # 「地図1」の「図1」ではなく、2 つ目の「図1」
    # (1) 1 回目の「図1」（地図1 の中）にリンクを付けた: 本当にリンクされていない 2 つ目の参照は残り、知らせも出る
    res = _manual(path, [_link_op(src, "F1", 1)], meta, journal, tmp_path / "lookalike")
    assert res.fidelity.ok and res.ai.rejected == []
    assert [(u.src, u.text, u.start) for u in res.plan.float_unlinked] == [(src, "図1", ref.start)]
    act = _float_ref(res)
    assert "AI もリンクを付けませんでした" in act.top and "対象の参照（1 か所）" in act.box_detail
    # (2) 2 回目の「図1」（本当にリンクされていない参照）にリンクを付けた: 除かれ、知らせも出ない
    res = _manual(path, [_link_op(src, "F1", 2)], meta, journal, tmp_path / "real")
    assert res.fidelity.ok and res.ai.rejected == [] and res.plan.float_unlinked == []
    assert [a for a in actions(res) if a.key == "float_ref"] == []


def test_float_ref_advice_names_operations_each_screen_can_take(journal, meta, tmp_path):
    """0.29.0 の最後の点検の小さいもの (a)〜(d): 図・表の参照の知らせの案内が、画面ごとに取れる操作を言う。
    (a) API の呼び出しが失敗したときは、回答を反映する言い方（手動の言い方）にしない。(b) 回答待ちは、1 画面版では「反映」を押すだけ
    （押した後にさらに「変換する」を押す操作に読ませない）、ノートブックでは ▶ を押す。(c) AI を使った後の「AI に出し直してもらう」は、
    手動なら貼り直し、API ならもう一度変換する。(d) コマンドラインは --ai manual と --ai-response を一緒に言う。"""
    from jasme_jats import pipeline
    from jasme_jats.ai_assist import AIOutcome
    from jasme_jats.colab import step_text
    path, src = _float_ref_states(tmp_path, journal, meta)

    def texts(res):
        act = _float_ref(res)
        return {"report": act.top, "notebook": step_text(act.box_detail, "notebook"), "app": step_text(act.box_detail, "app"),
                "cli": act.cli}
    # (b) 回答待ち（手動）
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "pending", ai_mode="manual", convert_metafiles=False))
    t = texts(res)
    assert "手順 6 で AI の回答を貼り付けて ▶ を押すと" in t["notebook"]
    assert "「反映」を押すと、AI が指定した参照にリンクが付く" in t["app"] and "「反映」を押して変換し直すと" not in t["app"]
    assert "「変換する」" not in t["app"]                            # 回答なしで作り直す操作を勧めない
    assert "--ai manual --ai-response 回答のファイル を指定して変換し直すと" in t["cli"]
    # (c) AI を使った後（手動）: 貼り直す。1 画面版は手動の欄が見えたまま（AppState.answer_box_open）
    res = _manual(path, [_link_op(src, "F1", 1)], meta, journal, tmp_path / "manual_done")
    t = texts(res)
    assert "手順 6 で貼り付け直してください" in t["notebook"]
    assert "「AI の回答（json のコードブロック）を貼り付ける」の欄に貼り付け直して「反映」を押してください" in t["app"]
    assert "--ai manual --ai-response 回答のファイル を指定し直して実行してください" in t["cli"]
    assert "貼り付け直して反映" in t["report"] and "手順" not in t["app"] and "\x00" not in "".join(t.values())
    from jasme_jats.app import AppState
    st = AppState(tmp_path / "work")
    st.set_inputs(ai_mode="manual")
    st.res = res
    assert st.answer_box_open                                   # 案内のとおり、貼り付け直す欄が見えている
    # (c) AI を使った後（API）: もう一度変換する
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "api_done", convert_metafiles=False))
    res.ai = AIOutcome(mode="api")
    res.ai.raw = "{}"
    t = texts(res)
    assert "手順 5 をもう一度実行してください" in t["notebook"] and "「変換する」をもう一度押してください" in t["app"]
    assert "--ai api でもう一度実行してください" in t["cli"] and "もう一度変換すると" in t["report"]
    # (a) API の呼び出しが失敗した: 回答を反映する言い方ではなく、もう一度変換して補完ができれば、と言う
    real = pipeline.call_provider
    pipeline.call_provider = lambda *a, **k: _api_failed()
    try:
        res = convert(path, meta, journal, Options(out_dir=tmp_path / "api_err", ai_mode="api", ai_api_key="x", convert_metafiles=False))
    finally:
        pipeline.call_provider = real
    assert res.ai.error and res.ai.mode == "api"
    t = texts(res)
    for screen, text in t.items():
        assert "AI の回答を反映できたら" not in text and "AI による補完ができていません" in text, screen
    assert "手順 5 をもう一度実行して AI による補完ができれば" in t["notebook"]
    assert "「変換する」をもう一度押して AI による補完ができれば" in t["app"]
    assert "--ai api でもう一度実行して AI による補完ができれば" in t["cli"]
    # 回答を読めなかった手動モードは、今までどおり「AI の回答を反映できたら」
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "bad", ai_mode="manual", ai_response="これは JSON ではない",
                                               convert_metafiles=False))
    assert "AI の回答を反映できたら" in texts(res)["report"]


def _api_failed():
    from jasme_jats.ai_assist import AIOutcome
    o = AIOutcome(mode="api")
    o.error = "接続できません"
    return o


def test_cli_ai_response_needs_ai_manual(journal, meta, tmp_path, capsys):
    """0.29.0 の最後の点検の (d): --ai の既定は none なので、--ai-response だけでは回答が読まれない。黙って無視せず、引数の誤り
    （標準エラー・終了コード 2。変換の前に止める）にする。--ai api でも同じ。--ai manual と一緒なら読む。"""
    from conftest import META_EXAMPLE

    from jasme_jats.cli import main
    resp = tmp_path / "回答.json"
    resp.write_text('{"operations": [], "placements": [], "notes": []}', encoding="utf-8")
    base = [str(FULL), "--meta", str(META_EXAMPLE), "--no-metafile-conversion", "--ai-response", str(resp)]
    for extra in ([], ["--ai", "none"], ["--ai", "api"]):
        with pytest.raises(SystemExit) as e:
            main(base + extra + ["--out", str(tmp_path / "out")])
        err = capsys.readouterr().err
        assert e.value.code == 2 and "--ai-response" in err and "--ai manual" in err, extra
    assert not (tmp_path / "out").exists()
    assert main(base + ["--ai", "manual", "--out", str(tmp_path / "ok")]) in (0, 1)
    assert (tmp_path / "ok").exists()
