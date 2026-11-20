"""外部レビュー（docs/REVIEW_CODEX_2026-11.md）の R6・R9 の回帰テスト。

R6: 翻訳の題目がなく副題だけがあるとき、副題の段落を理由付きで除外に記録し（不変性チェックが合格する）、要対応 front_check で知らせる。
R9: 縦結合の継続のセルと飛ばしたグリッド（gridBefore・gridAfter）が同じ行にあっても、行は消えず rowspan に数える。
docx は make_fixtures の部品で作る（内容は架空）。
"""
import make_fixtures as mf
import pytest
from lxml import etree

from jasme_jats import builder, frontcheck
from jasme_jats.config import ArticleMeta
from jasme_jats.pipeline import Options, convert
from jasme_jats.report import NEEDS_ACTION, actions
from test_tables import _convert, _grid, c


# ---------------------------------------------------------------------------- R6
def _front(tmp_path, journal, meta, name, **kw):
    path = mf.front_variant(tmp_path / f"{name}.docx", **kw)
    return convert(path, meta, journal, Options(out_dir=tmp_path / f"out_{name}", ai_mode="none"))


def _exclusions(res, meta, journal):
    """res.plan をもう一度組み立てたときの builder の除外の記録（BuildInfo.exclusions。Result には持ち越さない）。"""
    return [e for e in builder.build(res.plan, meta, journal)[1].exclusions if e.reason == builder.SUBTITLE_NO_TITLE_EXCLUDED]


def _orphan(res):
    return next((a for a in actions(res) if a.key == "front_check"), None)


def test_subtitle_en_without_title_en_is_excluded_and_needs_action(tmp_path, journal, meta):
    """題目（英）がなく副題（英）だけ: 不変性チェックが合格し、除外の記録に理由があり、要対応 front_check が出る。"""
    res = _front(tmp_path, journal, meta, "ja", en_title="", en_subtitle="Untranslated subtitle")
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid, res.fidelity.missing
    ex = _exclusions(res, meta, journal)
    assert [e.text for e in ex] == ["Untranslated subtitle"] and not ex[0].blank
    a = _orphan(res)
    assert a is not None and a.level == NEEDS_ACTION and res.needs_action
    assert "副題（英）の段落がありますが、題目（英）がありません" in a.top and "題目（英）の段落（「" in a.top
    assert "要対応" in a.cli
    # 構造は補わない: XML に副題（英）の文字も trans-title-group も出ない
    xml = res.xml_base.decode("utf-8")
    assert "Untranslated subtitle" not in xml
    assert etree.fromstring(res.xml_base).find(".//article-meta/title-group/trans-title-group") is None
    # 「変換ツールの不具合の可能性」（要対応 fidelity）は出ない
    assert not any(x.key == "fidelity" for x in actions(res))


def test_subtitle_with_title_is_not_orphan(tmp_path, journal, meta):
    """題目（英）があれば、今までどおり trans-subtitle に出す（除外にも知らせにもしない）。"""
    res = _front(tmp_path, journal, meta, "ok")
    assert not _exclusions(res, meta, journal)
    assert _orphan(res) is None and "<trans-subtitle" in res.xml_base.decode("utf-8")


def test_subtitle_ja_without_title_ja_in_english_article(tmp_path, journal):
    """英文の論文（主が英文、翻訳が和文）でも対称に扱う: 題目（日）がなく副題（日）だけなら、副題（日）を除外して要対応で知らせる。"""
    meta_en = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12", "pub_date": "2026-03-31",
                                     "received": "2025-06-01", "accepted": "2025-11-20", "lang": "en"})
    res = _front(tmp_path, journal, meta_en, "en", title="", subtitle="―和文の副題だけ―")
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid, res.fidelity.missing
    ex = _exclusions(res, meta_en, journal)
    assert [e.text for e in ex if e.text.strip()] == ["―和文の副題だけ―"]       # 空白だけの題目（日）の段落も blank の除外に記録する
    assert all(e.blank for e in ex if not e.text.strip())
    a = _orphan(res)
    assert a is not None and a.level == NEEDS_ACTION and "副題（日）の段落がありますが、題目（日）がありません" in a.top
    assert "和文の副題だけ" not in res.xml_base.decode("utf-8")


def test_orphan_subtitle_helper_mirrors_builder(tmp_path, journal, meta):
    res = _front(tmp_path, journal, meta, "h", en_title="", en_subtitle="Untranslated subtitle")
    assert frontcheck.orphan_subtitle(res.plan, "ja")[0] == "副題（英）"
    assert frontcheck.orphan_subtitle(res.plan, "en")[0] == "副題（英）"      # 題目（英）がなければ、英文の記事でも翻訳は英文のまま（builder と同じ）


# ---------------------------------------------------------------------------- R9
R = mf.table_row


def test_grid_after_with_continuation_keeps_the_row_and_rowspan(journal, meta, tmp_path):
    """[A(縦結合の始まり), B] / [継続, gridAfter=1] / [C, D]: A は rowspan=2、2 行目は空の td の行として出る。
    gridAfter の代わりに空のセルを置いた docx と同じ出力になる。"""
    raw = [R([c("A", v="r"), "B"]), R([c("", v="c")], grid_after=1), R(["C", "D"])]
    res, tbl = _convert(tmp_path, journal, meta, raw_rows=raw, ncol=2)
    assert _grid(tbl) == {"tbody": [["A/r2", "B"], [""], ["C", "D"]]}
    (tmp_path / "ref").mkdir()
    raw = [R([c("A", v="r"), "B"]), R([c("", v="c"), ""]), R(["C", "D"])]
    _, ref = _convert(tmp_path / "ref", journal, meta, raw_rows=raw, ncol=2)
    assert _grid(ref) == _grid(tbl)


def test_grid_before_with_continuation_keeps_the_row_and_rowspan(journal, meta, tmp_path):
    raw = [R(["A", c("B", v="r")]), R([c("", v="c")], grid_before=1), R(["C", "D"])]
    res, tbl = _convert(tmp_path, journal, meta, raw_rows=raw, ncol=2)
    assert _grid(tbl) == {"tbody": [["A", "B/r2"], [""], ["C", "D"]]}
    (tmp_path / "ref").mkdir()
    raw = [R(["A", c("B", v="r")]), R(["", c("", v="c")]), R(["C", "D"])]
    _, ref = _convert(tmp_path / "ref", journal, meta, raw_rows=raw, ncol=2)
    assert _grid(ref) == _grid(tbl)


def test_all_continued_rows_without_grid_skips_are_still_dropped(journal, meta, tmp_path):
    """空き列のない、すべて継続の行は今までどおり出さない（rowspan は出す行だけで数える）。"""
    raw = [R([c("A", v="r"), c("B", v="r")]), R([c("", v="c"), c("", v="c")]), R(["C", "D"])]
    _, tbl = _convert(tmp_path, journal, meta, raw_rows=raw, ncol=2)
    assert _grid(tbl) == {"tbody": [["A", "B"], ["C", "D"]]}


def test_blank_title_ja_in_english_article_is_excluded_as_blank(tmp_path, journal):
    """S11: 英文の論文で題目（日）が全角空白だけ・副題（日）が文字。題目（日）の段落は builder が空白だけの除外に記録する
    （builder.title_group の `for p in other_sub + other:` から other を外すと、不変性チェックが不合格になる）。空白だけの除外はちょうど 1 件。"""
    meta_en = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12", "pub_date": "2026-03-31",
                                     "received": "2025-06-01", "accepted": "2025-11-20", "lang": "en"})
    res = _front(tmp_path, journal, meta_en, "enblank", title="\u3000", subtitle="―和文の副題だけ―")
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid, (res.fidelity.missing, res.fidelity.bad_excluded)
    ex = _exclusions(res, meta_en, journal)
    assert sorted((e.blank, e.text) for e in ex) == [(False, "―和文の副題だけ―"), (True, "\u3000")]
    assert len([e for e in ex if e.blank]) == 1
