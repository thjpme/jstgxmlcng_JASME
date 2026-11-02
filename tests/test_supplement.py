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
from jasme_jats.fidelity import (NUMBER_WHY, UNIT_WHY, UNTRACKED_WHY, UNWRITTEN_WHY, _pair, source_texts,
                                 verify_supplement)
from jasme_jats.pipeline import Options, convert
from test_pdfmatch import (FRONT, N10_TAIL, PUB12, REST, SMALL_FRONT, TALK, body_lines, convert_with_pages,
                           n10_article, n10_pages)

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
    assert SUP_ROW in head and "合格（元の docx から変わった文字 44 箇所" in head
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
    typeset_pair = getattr(pdfmatch, "typeset_pair", None)
    if typeset_pair is None:            # 照合の側の述語がまだない（ほかの作業の途中）ときは、比べる相手がない
        return
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
