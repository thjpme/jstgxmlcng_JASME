"""外部レビュー 2 回目の S2・S12（CARRIED_MSG）の回帰（docs/REVIEW_CODEX_2026-11.md 末尾）。

S2: 型の誤った AI の回答（kind が配列・項目が辞書でない など）で、変換が TypeError で止まる。AI を条件に変換を止めない。
S12: 段落を指さない項目・先頭の文字の確かめの対象でない一覧は、確かめずに使うので「確かめられた m 件」に数えず、別に数える。
"""
import json
import zipfile

import pytest

import answers
from conftest import FULL
from jasme_jats import ai_assist
from jasme_jats.ai_assist import ANSWER_LISTS, CARRIED_NO_HEAD_WHY
from jasme_jats.pipeline import _mechanical
from test_ai_stamp import _manual, edited_docx

BAD_VALUES = [[], ["x"], {"a": 1}, 3, None, True, 1.5]
FIELDS = {"placements": ("float", "after", "after_head", "basis", "column", "reason", "confidence"),
          "boxes": ("box", "kind", "after", "after_head", "reason", "confidence"),
          "boundaries": ("src", "head", "kind", "reason", "confidence"),
          "links": ("kind", "src", "head", "text", "occurrence", "target", "reason", "confidence"),
          "names": ("src", "head", "family", "given", "reason", "confidence"),
          "style_fixes": ("src", "head", "style", "how", "verdict", "reason", "confidence")}


def _convert_with(resp, docx, journal, meta, tmp_path):
    res = _manual(docx, json.dumps(resp, ensure_ascii=False), meta, journal, tmp_path)
    assert res.zip_path and zipfile.is_zipfile(res.zip_path)
    return res


def _good_link():
    return json.loads(answers.answer(links=[("文献", "d18", "2001", 1, "B2")], docx=FULL))


@pytest.mark.parametrize("kind", ["missing", "null", "mismatch"])
def test_s2_review_repro_array_kind_on_old_request(kind, journal, meta, tmp_path):
    """レビューの再現: 完全な見本の d18 の前に段落を足し、前の依頼番号への links（kind が []）。変換は止まらず、不採用になる。"""
    resp = _good_link()
    link = resp["links"][0]
    link.update(kind=[], text="2001", target="B2")
    if kind == "missing":
        link.pop("head", None)
    elif kind == "null":
        link["head"] = None
    else:
        link["head"] = "合わない先頭の文字の段落"
    _, plan0, _ = _mechanical(FULL, journal)
    new = edited_docx(FULL, tmp_path / "full.docx", plan0.paras["d18"].text_only()[:12], "別の箇所の2001について述べる。")
    res = _convert_with(resp, new, journal, meta, tmp_path / "o")
    assert res.ai.accepted == [] and len(res.ai.rejected) == 1


def _bad_items(key):
    """一覧 key の、型の誤った項目の一覧（辞書でない項目と、各項目に誤った型の値を入れた辞書）。"""
    out = [[], "文字", 3, None, [1, 2]]
    for f in FIELDS[key]:
        for bad in BAD_VALUES:
            it = {g: "x" for g in FIELDS[key]}
            it[f] = bad
            if f in ("src", "after", "float", "box"):
                pass
            out.append(it)
    return out


@pytest.mark.parametrize("key", ANSWER_LISTS)
@pytest.mark.parametrize("carried", [False, True])
def test_s2_wrong_types_never_stop_conversion(key, carried, journal, meta, tmp_path):
    """6 種類の一覧それぞれで、型の誤った項目を入れても、(a)・(b) とも変換が止まらず ZIP ができる。"""
    base = _good_link()
    docx = FULL
    if carried:
        _, plan0, _ = _mechanical(FULL, journal)
        docx = edited_docx(FULL, tmp_path / "full.docx", plan0.paras["d18"].text_only()[:12], "別の箇所の2001について述べる。")
    items = _bad_items(key)
    # 項目を 1 つずつ入れる（1 つの例外が全体を隠さないように、まとめて 1 回と個別の両方）
    for i, it in enumerate(items):
        resp = dict(base, **{k: [] for k in ANSWER_LISTS})
        resp[key] = [it]
        res = _convert_with(resp, docx, journal, meta, tmp_path / f"o{i}")
        assert res.ai.accepted == [] or key in ("names",) or isinstance(it, dict)
    resp = dict(base, **{k: [] for k in ANSWER_LISTS})
    resp[key] = items
    res = _convert_with(resp, docx, journal, meta, tmp_path / "all")
    assert res.ai.accepted == []
    assert res.ai.rejected                       # 型の誤った項目は不採用として記録される


def test_s2_rec_functions_accept_any_types():
    """記録用の関数は、どんな型の値でも例外を出さない。"""
    for key in ANSWER_LISTS[:2] + ("boundaries", "links", "style_fixes"):
        if key == "names":
            continue
        for f in FIELDS[key]:
            for bad in BAD_VALUES:
                ai_assist._check_rec(key, {f: bad})


# ---------------------------------------------------------------------------- S12
def test_s12_carried_counts_unchecked_items_separately(journal, meta, tmp_path):
    """(b) で、段落を指さない placements（after が ""）は確かめずに使うので、「確かめられた 0 件」とは言わない。"""
    resp = json.loads(answers.answer(links=[("文献", "d18", "2001", 1, "B2")], docx=FULL))
    resp["links"] = []
    resp["placements"] = [{"float": "s1", "after": "", "after_head": "", "basis": "", "column": "", "reason": "x", "confidence": "高"}]
    _, plan0, _ = _mechanical(FULL, journal)
    new = edited_docx(FULL, tmp_path / "full.docx", plan0.paras["d18"].text_only()[:12], "別の箇所の2001について述べる。")
    res = _manual(new, json.dumps(resp, ensure_ascii=False), meta, journal, tmp_path / "o")
    assert res.ai.carried == ai_assist.CARRIED_MSG.format(n=1, m=0, k=1)
    assert "確かめられた 0 件と、先頭の文字の確かめの要らない指定（段落を指さない指定など）1 件" in res.ai.carried


def test_s2_valid_head_with_wrong_typed_fields(journal, meta, tmp_path):
    """段落と head は正しく、ほかの項目の型が誤った項目も、(a)・(b) とも止まらない。"""
    _, plan0, _ = _mechanical(FULL, journal)
    head = ai_assist.head_of(plan0.paras["d18"])
    new = edited_docx(FULL, tmp_path / "full.docx", plan0.paras["d18"].text_only()[:12], "別の箇所の2001について述べる。")
    for key, ptr in (("boundaries", "src"), ("links", "src"), ("style_fixes", "src")):
        for f in FIELDS[key]:
            if f in ("src", "head"):
                continue
            for bad in BAD_VALUES:
                it = {g: "x" for g in FIELDS[key]}
                it.update({ptr: "d18", "head": head, f: bad})
                for docx in (FULL, new):
                    resp = dict(_good_link(), **{k: [] for k in ANSWER_LISTS})
                    resp[key] = [it]
                    _convert_with(resp, docx, journal, meta, tmp_path / "v")
