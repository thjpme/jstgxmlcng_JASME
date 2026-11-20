"""外部レビュー 2 回目（docs/REVIEW_CODEX_2026-11.md 末尾）の S8 の回帰テスト。

S8: 翻訳の題目が数式だけのとき、空とみなして題目と副題を落とさない（builder.title_group の orphan と frontcheck の _paras を
Para.is_blank で見る）。題目の段落を作り替えた docx を、変換の経路（pipeline.convert）に通して確かめる（内容は架空）。
"""
import re
import zipfile

import make_fixtures as mf
import pytest
from lxml import etree

from jasme_jats import builder, frontcheck
from jasme_jats.config import ArticleMeta
from jasme_jats.pipeline import Options, convert
from jasme_jats.report import NEEDS_ACTION, actions

MARK_T, MARK_S = "題目の目印ＴＴＴ", "副題の目印ＳＳＳ"


def _convert(tmp_path, journal, meta, name, title_runs, sub_runs, *, side="en", **kw):
    """front_variant の題目（英）・副題（英）〈side が ja なら（日）〉の run を title_runs・sub_runs（run の XML。None なら文字のまま）に取り替えて変換する。"""
    src = tmp_path / f"{name}_src.docx"
    if side == "en":
        mf.front_variant(src, en_title=MARK_T, en_subtitle=MARK_S, **kw)
    else:
        mf.front_variant(src, title=MARK_T, subtitle=MARK_S, **kw)
    path = tmp_path / f"{name}.docx"
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zout:
        for it in zin.infolist():
            data = zin.read(it.filename)
            if it.filename == "word/document.xml":
                text = data.decode("utf-8")
                for mark, runs in ((MARK_T, title_runs), (MARK_S, sub_runs)):
                    if runs is None:
                        continue
                    pat = re.compile(r"<w:r(?: [^>/]*)?>(?:(?!</w:r>|</w:p>).)*?<w:t[^>]*>" + mark + r"</w:t></w:r>", re.S)
                    assert len(pat.findall(text)) == 1, mark
                    text = pat.sub(lambda m: runs, text)
                for prefix, uri in EXTRA_NS:       # 図形の名前空間が根にないときは足す
                    if f"xmlns:{prefix}=" not in text[:6000]:
                        text = text.replace("<w:document ", f'<w:document xmlns:{prefix}="{uri}" ', 1)
                data = text.encode("utf-8")
            zout.writestr(it, data)
    return convert(path, meta, journal, Options(out_dir=tmp_path / f"out_{name}", ai_mode="none"))


def _meta(lang):
    d = {"volume": "31", "issue": "1", "fpage": "1", "lpage": "12", "pub_date": "2026-03-31",
         "received": "2025-06-01", "accepted": "2025-11-20"}
    if lang == "en":
        d["lang"] = "en"
    return ArticleMeta.from_dict(d)


def _excl(res, meta, journal):
    return [e for e in builder.build(res.plan, meta, journal)[1].exclusions if e.reason == builder.SUBTITLE_NO_TITLE_EXCLUDED]


def _fc(res):
    return next((a for a in actions(res) if a.key == "front_check"), None)


def _blank_excl(res, meta, journal):
    """空白だけの除外の src の列（構造の段階で除外した分〈plan.exclusions〉と builder で除外した分）。"""
    return [e.src for e in res.plan.exclusions if e.blank] + [e.src for e in _excl(res, meta, journal) if e.blank]


def _ok(res):
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid, (res.fidelity.bad_excluded, res.fidelity.missing)


MATH = mf.omath(mf.mr("x+y"))
DECO = mf.shape("rect")
EXTRA_NS = (("a", "http://schemas.openxmlformats.org/drawingml/2006/main"), ("wps", mf.WPS_URI))                                    # 枠だけの図形（飾り）


def _tg(res):
    return etree.fromstring(res.xml_base).find(".//article-meta/title-group")


@pytest.mark.parametrize("side,lang", [("en", "ja"), ("ja", "en")])
def test_math_only_title_keeps_title_and_subtitle(tmp_path, journal, side, lang):
    """(1)(5) 翻訳の題目が数式だけ・副題が文字: trans-title（inline-formula）と trans-subtitle を出し、除外も知らせもない。"""
    meta = _meta(lang)
    res = _convert(tmp_path, journal, meta, f"m1{side}", MATH, None, side=side)
    _ok(res)
    tg = _tg(res)
    assert tg.find("trans-title-group/trans-title/inline-formula") is not None
    assert tg.find("trans-title-group/trans-subtitle") is not None
    assert not _excl(res, meta, journal) and _fc(res) is None
    assert not res.fidelity.bad_excluded


@pytest.mark.parametrize("side,lang,label", [("en", "ja", "副題（英）"), ("ja", "en", "副題（日）")])
def test_math_only_subtitle_without_title_is_nonblank_exclusion(tmp_path, journal, side, lang, label):
    """(2)(5) 翻訳の題目がなく副題が数式だけ: 副題は空白でない除外に記録し、要対応 front_check が出て、fidelity は合格する。"""
    meta = _meta(lang)
    res = _convert(tmp_path, journal, meta, f"m2{side}", "", MATH, side=side)
    _ok(res)
    ex = _excl(res, meta, journal)
    assert len(ex) == 1 and not ex[0].blank
    a = _fc(res)
    assert a is not None and a.level == NEEDS_ACTION and f"{label}の段落がありますが" in a.top
    assert _tg(res).find("trans-title-group") is None


@pytest.mark.parametrize("side,lang", [("en", "ja"), ("ja", "en")])
def test_blank_title_with_subtitle_is_unchanged(tmp_path, journal, side, lang):
    """(3)(5) 翻訳の題目が全角空白だけ・副題が文字: 副題は除外（空白でない）、題目は空白だけの除外（1 件）、要対応（今までどおり）。
    翻訳が英文のとき〈side が en〉は構造の段階で、翻訳が和文のとき〈side が ja〉は builder で、題目を空白だけの除外に記録する。"""
    meta = _meta(lang)
    res = _convert(tmp_path, journal, meta, f"m3{side}", mf.run("　"), None, side=side)
    _ok(res)
    assert [e.blank for e in _excl(res, meta, journal) if e.text.strip()] == [False]
    assert len(_blank_excl(res, meta, journal)) == 1        # 空白だけの題目の除外はちょうど 1 件（重複も漏れもない）
    assert _fc(res) is not None and _fc(res).level == NEEDS_ACTION


@pytest.mark.parametrize("side,lang", [("en", "ja"), ("ja", "en")])
def test_decoration_only_title_is_blank(tmp_path, journal, side, lang):
    """(4)(5) 翻訳の題目が飾りの図形だけ（is_blank は飾りを数えない）: 空白だけの題目と同じく空白の除外 1 件、副題は孤立として知らせる。
    fidelity は合格し、trans-title-group は出ない。"""
    meta = _meta(lang)
    res = _convert(tmp_path, journal, meta, f"m4{side}", DECO, None, side=side)
    _ok(res)
    assert [e.blank for e in _excl(res, meta, journal) if e.text.strip()] == [False]
    assert len(_blank_excl(res, meta, journal)) == 1
    assert _fc(res) is not None and _fc(res).level == NEEDS_ACTION
    assert _tg(res).find("trans-title-group") is None


def test_math_only_main_title_is_not_missing(tmp_path, journal):
    """和文の記事で題目（日）が数式だけ: 題目がない（title_missing）とは知らせない（_paras が is_blank で見るため。S8 の副産物）。"""
    meta = _meta("ja")
    res = _convert(tmp_path, journal, meta, "m6", MATH, None, side="ja")
    _ok(res)
    assert not any(f.kind == frontcheck.TITLE_MISSING for f in frontcheck.plan_findings(res.plan, "ja"))
    assert _tg(res).find("article-title/inline-formula") is not None
