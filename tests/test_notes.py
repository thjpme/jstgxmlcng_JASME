"""注: テンプレートの規定（本文に上付きの「1)」、注は「注」の節）と違う書き方の原稿。

- Word の脚注機能で書かれた注（tests/fixtures/sample_edge.docx）
- 本文の大きさの「（注1）」、引用文献の後ろの注の節、番号の書き方が想定外の注（tests/fixtures/sample_notes.docx）
"""
import dataclasses
import json

import pytest
from lxml import etree

from conftest import EDGE, NOTES
from jasme_jats.pipeline import Options, _mechanical, convert
from jasme_jats.report import note_notes
from jasme_jats.structure import note_mark


def load(res):
    return etree.fromstring(res.xml_path.read_bytes().split(b"\n", 2)[2])


def text(el):
    return "".join(el.itertext())


@pytest.mark.parametrize("s, expect", [
    ("1) 本文", 1), ("(2) 本文", 2), ("注3) 本文", 3), ("（注4）本文", 4), ("(注 5) 本文", 5), ("［注6］本文", 6),
    ("〔注7〕本文", 7), ("注8　本文", 8), ("註9 本文", 9), ("１）本文", 1),
    ("注意1 本文", None), ("注10の説明", None), ("2018年", None), ("※4 本文", None),
])
def test_note_mark_forms(s, expect):
    m = note_mark(s)
    assert (m[2] if m else None) == expect


def test_plain_note_marks_and_notes_after_refs(journal, meta, tmp_path):
    res = convert(NOTES, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    root = load(res)
    fg = root.find(".//fn-group")
    assert fg.findtext("title") == "注"
    fns = fg.findall("fn")
    # 「（注1）」「［注2］」で始まる段落から新しい注。番号のない段落は前の注の続き（AI なしでは「※4」も注3 の続き）
    assert [len(fn.findall("p")) for fn in fns] == [1, 1, 3]
    assert [text(fn.find("p"))[:4] for fn in fns] == ["（注1）", "［注2］", "（注3）"]
    # 上付きでない「（注1）」などもリンクする（文字はそのまま）。「注」のない「(1)」はリンクしない
    links = {(text(x), x.get("rid")) for x in root.iter("xref") if x.get("ref-type") == "fn"}
    assert links == {("（注1）", "fn1"), ("［注2］", "fn2"), ("（注3）", "fn3")}
    report = res.report_path.read_text(encoding="utf-8")
    assert "注の節が引用文献の後ろにある" in report
    assert "上付きでない注番号「（注1）」を注 fn1 にリンクした" in report
    assert "| 注 3 |" in report or "/ 注 3 /" in report


def test_report_explains_notes_without_numbers(journal):
    _, plan, _ = _mechanical(NOTES, journal)
    plan.fns[2].number = None     # 番号を読み取れなかった場合
    assert note_notes(plan)[0].startswith(
        "先頭に番号（「1)」「（注1）」など）を読み取れなかった注: fn3（「（注3）2 段落からなる注の 1 段落目」。3 段落を 1 件の注にまとめた）")


def _op(**kw):
    return dict({"text": "", "occurrence": 1, "target": "", "role": "", "image": "", "confidence": "高", "reason": "試験"}, **kw)


def test_ai_can_split_notes_and_link_to_the_new_note(journal, meta, tmp_path):
    _, plan, _ = _mechanical(NOTES, journal)
    start = next(s for s, p in plan.paras.items() if p.plain().startswith("※4"))
    ref = next(s for s, p in plan.paras.items() if "注※4は" in p.plain())
    resp = {"operations": [_op(op="set_role", src=start, role="fn_start"),
                           # 新しく分けた注は依頼文に ID がないので、その注の最初の段落の ID で指定する
                           _op(op="link_note", src=ref, text="※4", target=start)],
            "placements": [], "notes": []}
    res = convert(NOTES, meta, journal, Options(out_dir=tmp_path, ai_mode="manual", convert_metafiles=False,
                                                ai_response=json.dumps(resp, ensure_ascii=False)))
    assert res.ai.rejected == []
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    root = load(res)
    fns = root.findall(".//fn-group/fn")
    assert [len(fn.findall("p")) for fn in fns] == [1, 1, 2, 1]
    assert text(fns[3]).startswith("※4")
    assert ("※4", "fn4") in {(text(x), x.get("rid")) for x in root.iter("xref") if x.get("ref-type") == "fn"}


def test_ai_cannot_split_word_footnotes(journal, meta, tmp_path):
    _, plan, _ = _mechanical(EDGE, journal)
    src = next(fn.paras[0].src for fn in plan.fns if fn.word_note)
    resp = {"operations": [_op(op="set_role", src=src, role="fn_start")], "placements": [], "notes": []}
    res = convert(EDGE, meta, journal, Options(out_dir=tmp_path, ai_mode="manual", convert_metafiles=False,
                                               ai_response=json.dumps(resp, ensure_ascii=False)))
    assert [why for _, why in res.ai.rejected] == ["Word の脚注機能で書かれた注は、Word の区切りのとおりにする"]


def test_word_footnotes_use_journal_mark_and_get_a_title(journal, meta, tmp_path):
    res = convert(EDGE, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    root = load(res)
    fg = root.find(".//fn-group")
    # docx に注の見出しがないので「注」を補う。番号は Word の表示「1」ではなく本誌の形式「1)」
    assert fg.findtext("title") == "注"
    assert text(fg.find("fn/p")) == "1) Word の脚注機能で付けた注です。"   # docx の文字の先頭の空白と重ねない
    x = next(x for x in root.iter("xref") if x.get("ref-type") == "fn")
    assert x.find("sup") is not None and text(x) == "1)"
    assert ("fn-title", "注") in res.fidelity.generated
    report = res.report_path.read_text(encoding="utf-8")
    assert "注 1（うち Word の脚注 1）" in report
    assert "補った注の見出し 1 件" in report
    assert "Word の脚注機能で書かれた注 1 件を、注の一覧にした" in report


def test_word_footnote_mark_and_title_follow_config(journal, meta, tmp_path):
    j = dataclasses.replace(journal, fn_mark="[{n}]", fn_title="")
    res = convert(EDGE, meta, j, Options(out_dir=tmp_path, convert_metafiles=False))
    assert res.fidelity.ok and res.dtd_valid
    root = load(res)
    assert root.find(".//fn-group/title") is None
    assert text(root.find(".//fn-group/fn/p")).startswith("[1] Word")
    assert text(next(x for x in root.iter("xref") if x.get("ref-type") == "fn")) == "[1]"
