"""補完の確かめ（fidelity.verify_supplement）のテスト。

ルート2 の補った docx が、元の docx から、組版の違い（(A)）と 13.1 に報告した校正の直し（(B)）以外に変わっていないことを、
照合（pdfmatch）・書き込み（pdfdocx）とは別の実装で確かめる。照合・書き込みに不具合があるときに不合格になることを、
直す箇所をすり替える・一覧から消す・変更履歴でなく書き換える形で確かめる（設計 U1 の 5.2 の 11〜18）。
"""
import shutil
import zipfile

import pytest

import make_fixtures as mf
from conftest import META_EXAMPLE, PDFCHECK, PDFCHECK_PDF
from jasme_jats import pdfdocx, pdfmatch, pipeline
from jasme_jats.fidelity import (NUMBER_WHY, UNIT_WHY, UNTRACKED_WHY, UNWRITTEN_WHY, _pair, _unit_ends, source_texts,
                                 supplement_targets, verify_supplement)
from jasme_jats.pipeline import Options, convert
from test_pdfmatch import (FRONT, N10_TAIL, PUB12, REST, SMALL_FRONT, TALK, body_lines, convert_with_pages, load,
                           n10_article, n10_pages)
from test_pdfmatch import texts as xml_texts

SUP_ROW = "出版版 PDF による補完の確かめ（ルート2）"


def route2(tmp_path, meta, journal, name="r2"):
    return convert(PDFCHECK, meta, journal, Options(out_dir=tmp_path / name, pdf_path=PDFCHECK_PDF, route="pdf",
                                                    convert_metafiles=False))


def report(res):
    return res.report_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------- 11. 合格
def test_supplement_passes_on_pdfcheck(journal, meta, tmp_path, capsys):
    """sample_pdfcheck のルート2 で合格。組版の違い 43 文字（全角・半角と、その前後の空白）と、補った校正の直し 1 つ
    （「資料」→「付録」）。1 章の行と、コマンドラインの「補完の確かめ: 合格」。"""
    pytest.importorskip("pypdfium2")
    res = route2(tmp_path, meta, journal)
    sup = res.supplement
    assert sup is not None and sup.ok and sup.problems == []
    assert (sup.typeset, sup.supplied) == (43, 1)
    assert res.ok and not res.needs_action
    head = report(res).split("## 2.")[0]
    row = next(line for line in head.splitlines() if SUP_ROW in line)
    assert "合格" in row and "不合格" not in row and "43" in row
    from jasme_jats.cli import main
    assert main([str(PDFCHECK), "--meta", str(META_EXAMPLE), "--out", str(tmp_path / "cli"), "--pdf",
                 str(PDFCHECK_PDF), "--no-metafile-conversion"]) == 0
    assert "補完の確かめ: 合格" in capsys.readouterr().out


# ---------------------------------------------------------------------------- 12〜14. 不合格にする
def test_supplement_detects_non_typeset_change(journal, meta, tmp_path, monkeypatch, capsys):
    """(A)（全角・半角）の直す箇所の 1 つの PDF の文字を、組版の違いでない文字（「(」→「［」）にすり替えて書き込む。
    不変性チェックは合格のまま（XML は補った docx と同じ）で、補完の確かめだけが不合格にする。要対応・終了コード 1・13.8 の表。"""
    pytest.importorskip("pypdfium2")
    orig = pdfdocx.plan_fixes

    def swapped(plan, check):
        fixes = orig(plan, check)
        f = next(f for f in fixes if f.kind != "text" and f.old == "(")
        f.new = "［"
        return fixes
    monkeypatch.setattr(pdfdocx, "plan_fixes", swapped)
    res = route2(tmp_path, meta, journal)
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    sup = res.supplement
    assert not sup.ok and not res.ok and res.needs_action
    assert [(src, why) for src, _, _, why in sup.problems] == [("d12", UNIT_WHY)]
    _, old, new, _ = sup.problems[0]
    assert "［(］" in old or "［ (］" in old
    assert "［［］" in new
    from jasme_jats.report import actions
    assert "supplement" in [a.key for a in actions(res)]
    section = report(res).split("### 13.8")[1]
    assert "**不合格**" in section and "| d12 |" in section
    from jasme_jats.cli import main
    assert main([str(PDFCHECK), "--meta", str(META_EXAMPLE), "--out", str(tmp_path / "cli"), "--pdf",
                 str(PDFCHECK_PDF), "--no-metafile-conversion"]) == 1
    captured = capsys.readouterr()
    assert "補完の確かめ: 不合格" in captured.out and "補完の確かめが不合格" in captured.err


def test_supplement_detects_unreported_change(journal, meta, tmp_path, monkeypatch):
    """(B) の直す箇所（「資料」→「付録」）を、書き込んだ後に直す箇所の一覧から消す（報告していない変更）→ 不合格。"""
    pytest.importorskip("pypdfium2")
    orig = pipeline.make_fixed_docx

    def drop_text(*args, **kwargs):
        fx = orig(*args, **kwargs)
        fx.fixes = [f for f in fx.fixes if f.kind != "text"]
        return fx
    monkeypatch.setattr(pipeline, "make_fixed_docx", drop_text)
    res = route2(tmp_path, meta, journal)
    assert res.fidelity.ok and not res.supplement.ok and not res.ok
    assert [(src, why) for src, _, _, why in res.supplement.problems] == [("d13", UNIT_WHY)]
    assert "［資料］" in res.supplement.problems[0][1] and "［付録］" in res.supplement.problems[0][2]


def test_supplement_detects_unwritten_fix(journal, tmp_path):
    """対照: 報告した (B) の直す箇所が、補った docx に書き込まれていない → 不合格（報告したのに書き込まれていない）。"""
    pytest.importorskip("pypdfium2")
    fx = pdfdocx.make_fixed_docx(PDFCHECK, PDFCHECK_PDF, tmp_path / "fixed.docx", journal)
    extra = pdfdocx.Fix("d17", 0, 2, "見本", "text", "試験", applied=True)
    sup = verify_supplement(PDFCHECK, fx.path, fx.fixes + [extra], fx.check.case_srcs, fx.check.original, {})
    assert not sup.ok and sup.problems == [("d17", "試験", "見本", UNWRITTEN_WHY)]


def test_supplement_detects_untracked_edit(journal, tmp_path):
    """補った docx の w:t を変更履歴なしで書き換える → 不合格（このツールの変更履歴を却下した文字が元の docx と違う）。"""
    pytest.importorskip("pypdfium2")
    fx = pdfdocx.make_fixed_docx(PDFCHECK, PDFCHECK_PDF, tmp_path / "fixed.docx", journal)
    sup = verify_supplement(PDFCHECK, fx.path, fx.fixes, fx.check.case_srcs, fx.check.original, {})
    assert sup.ok
    edited = tmp_path / "edited.docx"
    with zipfile.ZipFile(fx.path) as zin, zipfile.ZipFile(edited, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                text = data.decode("utf-8")
                assert text.count(">に基づく<") == 1
                data = text.replace(">に基づく<", ">に基く<").encode("utf-8")
            zout.writestr(item, data)
    sup = verify_supplement(PDFCHECK, edited, fx.fixes, fx.check.case_srcs, fx.check.original, {})
    assert not sup.ok and [(src, why) for src, _, _, why in sup.problems] == [("d12", UNTRACKED_WHY)]


def test_supplement_detects_space_deletion_between_words(journal, meta, tmp_path, monkeypatch):
    """照合の drops でない空白の削除（英文要旨の語の間の空白）を (A) の直す箇所として書き込む → 不合格（空白の削除を (A) と
    みなすのは、全角・半角の対のすぐ隣の半角の空白と、段落の先頭の空白だけ）。"""
    pytest.importorskip("pypdfium2")
    orig = pdfdocx.plan_fixes

    def extra(plan, check):
        fixes = orig(plan, check)
        t = plan.paras["d26"].plain()
        q = t.index(" ")
        fixes.append(pdfdocx.Fix("d26", q, q + 1, "", "space", " "))
        return fixes
    monkeypatch.setattr(pdfdocx, "plan_fixes", extra)
    res = route2(tmp_path, meta, journal)
    assert any(f.src == "d26" and f.applied for f in res.docx_fix.fixes)
    assert res.fidelity.ok and not res.supplement.ok and not res.ok
    assert [(src, why) for src, _, _, why in res.supplement.problems] == [("d26", UNIT_WHY)]


@pytest.mark.parametrize("d, i, at_start, ok", [
    (" (", "（", False, True),          # 全角・半角の対のすぐ前の空白
    (")  ", "）", False, True),         # 対のすぐ後ろの、続いた空白
    (" ", "", True, True),              # 番号のすぐ後ろ（自動番号のある段落の先頭・注の番号の後ろ）の空白
    (" ", "", False, False),            # 隣に対も番号もない空白
    ("\u3000(", "（", False, False),    # 全角の空白
    ("\t(", "（", False, False),        # タブ
    ("\n(", "（", False, False),        # 改行
    (" (", "［", False, False),          # 隣が対でない
])
def test_supplement_space_deletion_rule(d, i, at_start, ok):
    """空白の削除の規則（_unit_ends）: 半角の空白で、d の中のすぐ隣を全角・半角の対として並べたときか、段落の先頭のときだけ (A)。"""
    assert (_unit_ends(d, i, [], 0, False, at_start) != {}) == ok
    # 単位の後ろが番号（注の参照のすぐ前）なら、後ろの空白も (A)
    assert _unit_ends(" ", "", [], 0, False, False, True) != {} and _unit_ends("\t", "", [], 0, False, False, True) == {}


NOTE_BODY = ["脚注の付いた文 ", mf.footnote_ref(5), " と後ろの 文のつづきである。"]
NOTE_PAGES = [("ルート2の脚注\n―検証用の小さな論文―\n１．はじめに\n脚注の付いた文１）と後ろの 文のつづきである。\n"
               "引用および参考文献\n試験六郎（2024）．「小さな論文」．『架空誌』，第5巻，pp.9-10．\n"
               "注\n１）脚注の本文であり十分に長い文である。\n")]


def note_article(tmp_path):
    path = tmp_path / "note.docx"
    mf.make_article(path, "ルート2の脚注", lambda b: [mf.para(mf.S["sec1"], "１．はじめに"), mf.para(mf.S["body"], *NOTE_BODY)],
                    footnotes=[mf.footnote(5, " 脚注の本文であり十分に長い文である。")])
    return path


def test_supplement_space_next_to_note_reference(journal, meta, tmp_path, monkeypatch):
    """Word の脚注の参照（本文の番号。canonical_text には出ない）のすぐ前・すぐ後ろの半角の空白を消す直し（照合の drops）は、
    参照の位置の境目の目印で (A) と認めて合格する。注の段落の番号の後ろの空白も同じ。参照の隣でない空白（「後ろの 文」）を消す
    直しを足すと不合格。"""
    path = note_article(tmp_path)
    res = convert_with_pages(tmp_path, monkeypatch, journal, meta, NOTE_PAGES, "pdf", docx=path)
    spaces = [f for f in res.docx_fix.fixes if f.kind == "space" and f.applied]
    assert len(spaces) >= 2
    assert res.fidelity.ok and res.supplement.ok and res.supplement.problems == []
    orig = pdfdocx.plan_fixes

    def extra(plan, check):
        fixes = orig(plan, check)
        src = next(s for s, p in plan.paras.items() if "後ろの 文" in p.plain())
        q = plan.paras[src].plain().index("の 文") + 1
        fixes.append(pdfdocx.Fix(src, q, q + 1, "", "space", " "))
        return fixes
    monkeypatch.setattr(pdfdocx, "plan_fixes", extra)
    (tmp_path / "x").mkdir()
    res = convert_with_pages(tmp_path / "x", monkeypatch, journal, meta, NOTE_PAGES, "pdf", docx=path)
    assert res.fidelity.ok and not res.supplement.ok
    assert [why for _, _, _, why in res.supplement.problems] == [UNIT_WHY]
    assert "後ろの［ ］文" in res.supplement.problems[0][1]


@pytest.mark.parametrize("bullet", [True, False], ids=["autonum", "plain"])
def test_supplement_space_at_paragraph_start(bullet, journal, meta, tmp_path, monkeypatch):
    """段落の先頭の半角の空白の削除を (A) と認めるのは、自動番号のある段落だけ（番号のすぐ後ろ）。自動番号の箇条の項目の先頭の
    空白（PDF「・一つ目…」）は合格し、自動番号のない段落の先頭の空白を消す直しは不合格。"""
    item = " 一つ目の項目として，架空の授業の記録を集めた。"

    def parts(b):
        para = mf.list_item(mf.S["body"], item) if bullet else mf.para(mf.S["body"], item)
        return [mf.para(mf.S["sec1"], "１．はじめに"), mf.para(mf.S["body"], TALK), para]
    mf.make_article(tmp_path / "b.docx", "ページ番号の判定の検証用文書", parts, bullet="●")
    pages = n10_pages([*SMALL_FRONT, *body_lines(TALK), f"・{item.strip()}" if bullet else f"　{item.strip()}", *N10_TAIL])
    orig = pdfdocx.plan_fixes

    def extra(plan, check):
        fixes = orig(plan, check)
        src = next(s for s, p in plan.paras.items() if p.plain() == item)
        if not any(f.src == src and f.start == 0 for f in fixes):
            fixes.append(pdfdocx.Fix(src, 0, 1, "", "space", " "))
        return fixes
    monkeypatch.setattr(pdfdocx, "plan_fixes", extra)
    res = convert_with_pages(tmp_path, monkeypatch, journal, meta, pages, "pdf", docx=tmp_path / "b.docx")
    assert any(f.kind == "space" and f.start == 0 and f.applied for f in res.docx_fix.fixes)
    assert res.fidelity.ok and res.supplement.ok == bullet
    if not bullet:
        assert [why for _, _, _, why in res.supplement.problems] == [UNIT_WHY]


def test_supplement_case_sources_are_independent(journal, meta, tmp_path, monkeypatch):
    """大文字・小文字を (A) とする段落は、照合（pdfmatch.case_paragraphs）を通さず plan から作る。照合の側が英文要旨も
    含めてしまう不具合で、英文要旨の大文字・小文字を組版の違いとして書き込んでも、補完の確かめは不合格にする。"""
    pytest.importorskip("pypdfium2")
    orig = pdfmatch.case_paragraphs
    monkeypatch.setattr(pdfmatch, "case_paragraphs", lambda plan: orig(plan) | {"d26"})
    orig_pf = pdfdocx.plan_fixes

    def extra(plan, check):
        fixes = orig_pf(plan, check)
        fixes.append(pdfdocx.Fix("d26", 0, 1, "t", "glyph", "T"))
        return fixes
    monkeypatch.setattr(pdfdocx, "plan_fixes", extra)
    res = route2(tmp_path, meta, journal)
    assert [(f.old, f.new, f.applied) for f in res.docx_fix.fixes if f.src == "d26"] == [("T", "t", True)]
    assert not res.supplement.ok and [(src, why) for src, _, _, why in res.supplement.problems] == [("d26", UNIT_WHY)]
    # 英文の題目・著者名などは plan から作った集合に入る（英文要旨は入らない）
    case_srcs, numbers = supplement_targets(res.plan, {})
    assert {p.src for p in res.plan.title_en} <= case_srcs and "d26" not in case_srcs


# ---------------------------------------------------------------------------- 15. 数式の後ろと、段落記号の削除をまたぐ直し
def test_supplement_with_formula_and_joined_paragraphs(journal, meta, tmp_path, monkeypatch):
    """数式の後ろの直し（読み取りの段落の文字では数式は 1 文字、検証の文字では数式の文字なので、位置がずれる）と、段落記号の
    削除をまたぐ直し（前の w:p の最後と後ろの w:p の最初にかかる直し）でも合格する（位置ではなく、変更履歴の単位で当てる）。"""
    prob = ["各回の結果から相対度数を求め，これを試行の確率とよび，", mf.omath(mf.mr("p") + mf.mr("q")),
            "の値の変化を表に記録した。"]
    n10_article(tmp_path, journal, [("body", prob), ("body", TALK)])
    pub = "各回の結果から相対度数を求め，これを試行の確率とよび，pqの値の変化を表に順に記録した。"
    pages = n10_pages([*SMALL_FRONT, *body_lines(pub), *body_lines(TALK), *N10_TAIL])
    res = convert_with_pages(tmp_path, monkeypatch, journal, meta, pages, "pdf", docx=tmp_path / "n10.docx")
    fx = res.docx_fix
    assert [(f.old, f.new) for f in fx.fixes if f.applied and f.kind == "text"] == [("", "順に")]
    assert res.supplement is not None and res.supplement.ok and res.supplement.supplied == 1
    # 段落記号の削除をまたぐ直し（「。授」→「，本」。前の w:p の最後の文字と後ろの w:p の最初の文字にかかる）
    split = tmp_path / "split.docx"
    mf.make_pdfcheck(split, split=True)
    d13 = "詳しくは付録の学習指導案を参照されたい，本業は２回行った。"
    pages = ["\n".join(["（1）", *FRONT, PUB12, d13, *REST[1:]])]
    (tmp_path / "s").mkdir()
    res = convert_with_pages(tmp_path / "s", monkeypatch, journal, meta, pages, "pdf", docx=split)
    texts = [(f.old, f.new) for f in res.docx_fix.fixes if f.applied and f.kind == "text"]
    assert texts == [("資料", "付録"), ("。授", "，本")]
    assert res.fidelity.ok and res.supplement.ok and res.supplement.supplied == len(texts)


# ---------------------------------------------------------------------------- 16. Word が付ける番号
@pytest.mark.parametrize("new, ok", [("・", True), ("◆", False), ("●", True)])
def test_supplement_number_edits(new, ok, tmp_path):
    """Word が付ける番号（plan.pdf_numbers）が、表にない字形（「●」→「◆」）になっていれば不合格。「●」→「・」
    （NUMBER_PAIRS）と全角・半角（「(1)」→「（1）」）は合格。"""
    shutil.copyfile(PDFCHECK, tmp_path / "a.docx")
    original = {("auto", "d20"): "●", ("fnlist", "1"): "(1)"}
    numbers = {("auto", "d20"): new, ("fnlist", "1"): "（1）"}
    sup = verify_supplement(tmp_path / "a.docx", PDFCHECK, [], set(), original, numbers)
    assert sup.ok == ok
    if not ok:
        assert sup.problems == [("auto:d20", "●", "◆", NUMBER_WHY)]
    # 番号でない文字の「●」→「・」は (A) でない
    assert not _pair("●", "・") and _pair("●", "・", number=True)


# ---------------------------------------------------------------------------- 17. 照合の述語と同じ答え
PAIR_CHARS = ([chr(c) for c in range(0x20, 0x7F)] + [chr(c) for c in range(0xFF01, 0xFF5F)]
              + list(pdfmatch.HYPHENS + pdfmatch.DASHES) + list("\"“”'’‘＂＇") + list("●・〜～…"))


def test_supplement_pairs_agree_with_pdfmatch():
    """補完の確かめの対の判定（fidelity._pair。定数だけを共有した別の実装）と、照合の pdfmatch.typeset_pair が、文字の集合の
    すべての対で同じ答えになる（片方だけを直すと落ちる）。"""
    typeset_pair = pdfmatch.typeset_pair
    chars = sorted(set(PAIR_CHARS))
    bad = [(a, b, case, number) for a in chars for b in chars for case in (False, True) for number in (False, True)
           if _pair(a, b, case, number) != bool(typeset_pair(a, b, case=case, number=number))]
    assert bad == []


# ---------------------------------------------------------------------------- 18. 行わないとき
def test_supplement_none_on_route1_and_fallback(journal, meta, tmp_path):
    """ルート1 と、PDF を読めなかったルート2 では補完の確かめを行わず（None）、1 章に行が出ない。"""
    res = convert(PDFCHECK, meta, journal, Options(out_dir=tmp_path / "r1", pdf_path=PDFCHECK_PDF,
                                                   convert_metafiles=False))
    assert res.supplement is None and SUP_ROW not in report(res).split("## 2.")[0]
    (tmp_path / "broken.pdf").write_bytes(b"")
    res = convert(PDFCHECK, meta, journal, Options(out_dir=tmp_path / "fb", pdf_path=tmp_path / "broken.pdf", route="pdf",
                                                   convert_metafiles=False))
    assert res.pdf_fallback and res.supplement is None and SUP_ROW not in report(res).split("## 2.")[0]


def test_source_texts_unchanged_by_check(journal, tmp_path):
    """補完の確かめは補った docx を読むだけで、ファイルを変えない（変更履歴を外すのは写しの木の上）。"""
    pytest.importorskip("pypdfium2")
    fx = pdfdocx.make_fixed_docx(PDFCHECK, PDFCHECK_PDF, tmp_path / "fixed.docx", journal)
    before = fx.path.read_bytes()
    texts = source_texts(fx.path)
    verify_supplement(PDFCHECK, fx.path, fx.fixes, fx.check.case_srcs, fx.check.original, {})
    assert fx.path.read_bytes() == before and source_texts(fx.path) == texts


# ---------------------------------------------------------------------------- 19. 全角・半角の直しと隣の空白の削除は連動する
P1_DOCX = "授業の最初に確認した値 (３) の後ろで，生徒は話し合いを続け，その様子を記録した。"
P1_PUB = "授業の最初に確認した値（３）の後ろで，生徒は話し合いを続け，その様子を記録した。"


def p1_convert(tmp_path, monkeypatch, journal, meta, parts):
    """本文の段落 parts（plain は P1_DOCX）を、P1_PUB（全角の括弧で、括弧の外に空白がない）の PDF で補う。"""
    n10_article(tmp_path, journal, [("body", parts), ("body", TALK)])
    pages = n10_pages([*SMALL_FRONT, *body_lines(P1_PUB), *body_lines(TALK), *N10_TAIL])
    return convert_with_pages(tmp_path, monkeypatch, journal, meta, pages, "pdf", docx=tmp_path / "n10.docx")


def p1_summary(res):
    return [(f.kind, f.old, f.new, f.applied) for f in res.docx_fix.fixes if f.src == "d12"]


def test_supplement_space_goes_with_width_when_fixed(journal, meta, tmp_path, monkeypatch):
    """対照: 全角・半角の直しが通るときは、隣の空白の削除も今までどおり通る（「値 (３) の後ろ」→「値（３）の後ろ」）。
    空白の削除は根拠の全角・半角の直しと同じ組（Fix.group）で、PdfCheck.drop_basis が根拠を示す。"""
    pytest.importorskip("pypdfium2")
    res = p1_convert(tmp_path, monkeypatch, journal, meta, P1_DOCX)
    assert p1_summary(res) == [("space", " ", "", True), ("width", "(", "（", True), ("width", ")", "）", True),
                               ("space", " ", "", True)]
    assert res.docx_fix.check.drop_basis == {"d12": {11: {("width", 12)}, 15: {("width", 14)}}}
    f = [f for f in res.docx_fix.fixes if f.src == "d12"]
    assert f[0].group is f[1].group is not None and f[3].group is f[2].group is not None and f[0].group is not f[3].group
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and res.supplement.ok and res.ok
    assert P1_PUB in xml_texts(load(res))


def test_supplement_space_not_left_alone_inside_other_authors_insertion(journal, meta, tmp_path, monkeypatch):
    """(b) 全角・半角にする括弧が、ほかの作成者の挿入（w:ins）の中にあって直せないとき、その外の隣の空白の削除だけが残らない
    （「値 (３) の後ろ」が「値(３) の後ろ」になって、docx にも PDF にもない文字になり、補完の確かめが不合格になっていた）。
    理由には、どの直しに連動して直さなかったかが出る。"""
    pytest.importorskip("pypdfium2")
    parts = ["授業の最初に確認した値 ", '<w:ins w:id="2" w:author="x"><w:r><w:t>(３)</w:t></w:r></w:ins>',
             " の後ろで，生徒は話し合いを続け，その様子を記録した。"]
    res = p1_convert(tmp_path, monkeypatch, journal, meta, parts)
    fixes = [f for f in res.docx_fix.fixes if f.src == "d12"]
    assert [(f.kind, f.old, f.applied) for f in fixes] == [("space", " ", False), ("width", "(", False),
                                                           ("width", ")", False), ("space", " ", False)]
    assert fixes[1].reason.startswith("直せない文字")
    assert fixes[0].reason == f"全角・半角の直し「(」→「（」を直さないので、連動して直さない（その理由: {fixes[1].reason}）"
    assert fixes[3].reason.startswith("全角・半角の直し「)」→「）」を直さないので")
    assert not res.docx_fix.applied
    assert res.fidelity.ok and res.fidelity.final_ok and res.supplement.ok and res.supplement.problems == []
    assert P1_DOCX in xml_texts(load(res))


def test_supplement_space_not_left_alone_when_structure_check_stops_width(journal, meta, tmp_path, monkeypatch):
    """(a) 構造の確かめ（_lost → _protect → _kept）が「(」の全角・半角の直しを止めるとき（「(」の範囲にかかるリンクが崩れる
    ものとして）、その前の空白の削除だけが残らない。「)」と後ろの空白は止められた範囲にかからないので、今までどおり直す。"""
    pytest.importorskip("pypdfium2")
    calls = []
    orig = pdfdocx._lost

    def lost(original, fixed):
        calls.append(1)
        found = orig(original, fixed)
        if len(calls) == 1:
            q = P1_DOCX.index("(")
            found.append(("d12", (q, q + 1), pdfdocx.STRUCTURE_REASON, ""))
        return found
    monkeypatch.setattr(pdfdocx, "_lost", lost)
    res = p1_convert(tmp_path, monkeypatch, journal, meta, P1_DOCX)
    assert len(calls) >= 2
    assert p1_summary(res) == [("space", " ", "", False), ("width", "(", "（", False), ("width", ")", "）", True),
                               ("space", " ", "", True)]
    space, width = [f for f in res.docx_fix.fixes if f.src == "d12"][:2]
    assert width.reason == pdfdocx.STRUCTURE_REASON
    assert space.reason == f"全角・半角の直し「(」→「（」を直さないので、連動して直さない（その理由: {pdfdocx.STRUCTURE_REASON}）"
    assert res.fidelity.ok and res.supplement.ok and res.supplement.problems == []
    assert "授業の最初に確認した値 (３）の後ろで，生徒は話し合いを続け，その様子を記録した。" in xml_texts(load(res))


def test_supplement_space_not_left_alone_when_note_number_is_kept(journal, meta, tmp_path, monkeypatch):
    """(c) ある注の番号を直すと注を認識できなくなるとき、すべての注の番号を docx のままにする（NOTE_REASON）。別の注の番号の
    括弧を半角にする直し（PDF「注(注3)もある」）と、その前の空白の削除（docx「注 （注3）もある」）は、いっしょに直さない。
    注の番号でない文字の全角・半角（箇条の番号）は今までどおり直す。"""
    from conftest import NOTES
    pytest.importorskip("pypdfium2")
    src = tmp_path / "notes.docx"
    with zipfile.ZipFile(NOTES) as zin, zipfile.ZipFile(src, "w") as zout:
        for item in zin.infolist():
            blob = zin.read(item.filename)
            if item.filename == "word/document.xml":
                text = blob.decode("utf-8")
                assert text.count("注（注3）") == 1
                blob = text.replace("注（注3）", "注 （注3）").encode("utf-8")
            zout.writestr(item, blob)
    pages = ["本文の大きさで書いた注番号1）と，角括弧の注番号［注2］がある文。\n"
             "箇条の番号（1）と（2）は注へのリンクにしない。2 段落からなる注(注3)もある。\n"
             "引用および参考文献\n試験三郎（2022）．「注の書き方」．『架空誌』，第3巻，pp.5-6．\n"
             "注\n１）本文の大きさで書かれた注番号の注である。\n［注2］角括弧で書かれた注番号の注である。\n"
             "３）2 段落からなる注の 1 段落目である。\n"]
    monkeypatch.setattr(pdfmatch, "extract_pages", lambda path: pages)
    (tmp_path / "dummy.pdf").write_bytes(b"%PDF-1.4\n")
    res = convert(src, meta, journal, Options(out_dir=tmp_path / "o", pdf_path=tmp_path / "dummy.pdf", route="pdf",
                                              convert_metafiles=False))
    note = [f for f in res.docx_fix.fixes if f.src == "d13" and f.reason]
    assert [(f.kind, f.old, f.new) for f in note] == [("space", " ", ""), ("width", "（", "("), ("width", "）", ")")]
    assert note[1].reason == pdfdocx.NOTE_REASON
    assert note[0].reason == f"全角・半角の直し「（」→「(」を直さないので、連動して直さない（その理由: {pdfdocx.NOTE_REASON}）"
    assert ("d13", "(", "（") in {(f.src, f.old, f.new) for f in res.docx_fix.applied}
    assert res.fidelity.ok and res.fidelity.final_ok and res.supplement.ok and res.supplement.problems == []
    assert any("2 段落からなる注 （注3）もある。" in t for t in xml_texts(load(res)))


def test_write_fixed_docx_spreads_reasons_in_group(journal, tmp_path):
    """write_fixed_docx と _apply_paragraph は、組（Fix.group）の一部が直せない（既存の変更履歴の中など）と分かったとき、組の全部を
    直さない。書き込みの前に決めるので、直せる側は書き込まれない。入力と書き出し先が同じファイルなら、書き込む前に ValueError。"""
    src = tmp_path / "in.docx"
    mf.make_article(src, "ページ番号の判定の検証用文書", lambda b: [
        mf.para(mf.S["sec1"], "１．はじめに"),
        mf.para(mf.S["body"], "値 ", '<w:ins w:id="2" w:author="x"><w:r><w:t>(</w:t></w:r></w:ins>', "３) の後ろ。")])
    _, plan = pdfdocx._mechanical(src, journal)
    s = next(k for k, p in plan.paras.items() if p.plain().startswith("値 "))
    space, width = pdfdocx.Fix(s, 1, 2, "", "space", " "), pdfdocx.Fix(s, 2, 3, "（", "width", "(")
    other = pdfdocx.Fix(s, 4, 5, "）", "width", ")")
    pdfdocx.link_fixes(space, width, paired=True)
    pdfdocx.write_fixed_docx(src, tmp_path / "out.docx", plan, [space, width, other])
    assert [(f.applied, bool(f.reason)) for f in (space, width, other)] == [(False, True), (False, True), (True, False)]
    assert "連動して直さない" in space.reason
    before = src.read_bytes()
    with pytest.raises(ValueError):
        pdfdocx.write_fixed_docx(src, src, plan, [])
    assert src.read_bytes() == before
