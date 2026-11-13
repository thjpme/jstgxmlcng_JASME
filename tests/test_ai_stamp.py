"""依頼の番号と段落の先頭の文字での回答の確かめ（修正計画 W8 の 4.6・手順 17。ai_assist.request_stamp・check_answer）。

回答の request_id と今の依頼の番号 R-構造の印-本文の印 を比べる:
(a) 2 つとも同じ: 使う（head の合わない項目は、同じ先頭の文字の段落が 1 つだけなら読み替える）
(b) 構造の印だけ同じ（Word で文字を直した後の原稿）: 使う（読み替えは (a) と同じ。head のない項目は不採用。carried に件数）
(c) 構造の印が違う・request_id がない: 回答を 1 件も使わない（ai_finish は「失敗」）
テストの原稿は tests/fixtures の架空の docx を、段落を足して書き換えたもの。
"""
import json
import zipfile
from copy import deepcopy

from lxml import etree

import answers
from conftest import FLOAT, FULL, NOTES, PDFCHECK, PDFCHECK_PDF
from jasme_jats import ai_assist
from jasme_jats.ai_assist import (CARRIED_NO_HEAD_WHY, NO_REQUEST_ID_MSG, OTHER_REQUEST_MSG, RE_STAMP, head_of,
                                  request_stamp)
from jasme_jats.pipeline import Options, _mechanical, convert
from jasme_jats.report import actions, ai_state

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}


def _text(p) -> str:
    return "".join(p.itertext())


def edited_docx(src, dst, before: str, new_text: str = "", where: str = "before"):
    """src の docx の、文字が before で始まる最初の段落の前（where が after なら後ろ）に、同じ書式の段落（文字は new_text）を
    足した docx を dst に書く（段落の ID が 1 つずつずれる原稿。架空の文字）。new_text が空なら、段落を足さずに、その段落の
    最初の文字の要素の頭に「架空の直し」を足す（段落の文字を直した原稿）。"""
    with zipfile.ZipFile(src) as z:
        items = {n: z.read(n) for n in z.namelist()}
    root = etree.fromstring(items["word/document.xml"])
    p = next(p for p in root.iter(f"{{{W}}}p") if _text(p).startswith(before))
    if new_text:
        q = deepcopy(p)
        for r in q.findall("w:r", NS) + q.findall("w:hyperlink", NS):
            q.remove(r)
        r = etree.SubElement(q, f"{{{W}}}r")
        etree.SubElement(r, f"{{{W}}}t").text = new_text
        (p.addprevious if where == "before" else p.addnext)(q)
    else:
        t = next(p.iter(f"{{{W}}}t"))
        t.text = "架空の直し" + t.text
    items["word/document.xml"] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in items.items():
            z.writestr(n, b)
    return dst


def _manual(path, resp, meta, journal, out):
    return convert(path, meta, journal, Options(out_dir=out, ai_mode="manual", ai_response=resp))


def _sec2(res) -> str:
    return res.report_path.read_text(encoding="utf-8").split("\n## 2.")[1].split("\n## 3.")[0]


# ---------------------------------------------------------------------------- 依頼の番号
def test_stamp_is_stable_and_has_two_parts(journal, tmp_path):
    """依頼の番号は R-XXXX-YYYY。同じ docx では同じ。段落の文字を直すと後半だけ、文献を足すと前半が変わる。"""
    req, plan = answers.request_of(FULL, journal)
    assert RE_STAMP.match(req.stamp) and answers.request_of(FULL, journal)[0].stamp == req.stamp
    assert req.instructions.startswith(f"# 依頼（依頼の番号: {req.stamp}）")
    assert request_stamp(plan, req.data) == req.stamp
    text = answers.request_of(edited_docx(FULL, tmp_path / "text.docx", "本研究"), journal)[0].stamp
    assert text[:7] == req.stamp[:7] and text != req.stamp
    ref = plan.refs[-1].para.text_only()
    more = answers.request_of(edited_docx(FULL, tmp_path / "ref.docx", ref[:10], "架空太郎（2099）．架空の文献．架空誌．",
                                          where="after"), journal)
    assert len(more[1].refs) == len(plan.refs) + 1 and more[0].stamp[:7] != req.stamp[:7]


def test_stamp_first_half_survives_width_fixes(journal, meta, tmp_path):
    """ルート2 で全角・半角が補われた docx でも、構造の印（前半）は変わらない（head_of の NFKC）。"""
    one = convert(PDFCHECK, meta, journal, Options(out_dir=tmp_path / "1", ai_mode="manual"))
    two = convert(PDFCHECK, meta, journal, Options(out_dir=tmp_path / "2", ai_mode="manual", route="pdf", pdf_path=PDFCHECK_PDF))
    assert two.docx_fix is not None and two.docx_fix.applied          # 補った docx がある
    assert one.ai.request_id[:7] == two.ai.request_id[:7]


# ---------------------------------------------------------------------------- (a)
def test_a_same_request_is_used_and_off_by_one_is_reread(journal, meta, tmp_path):
    """(a) 今の依頼の番号の回答はそのまま使う。ID を 1 つ書き違えた指定（head は正しい段落のもの）は、同じ先頭の文字の段落が
    1 つだけなら読み替える（reread。2 章に書く）。head のない指定は確かめずに使う。"""
    _, plan, _ = _mechanical(FULL, journal)
    good = answers.answer(links=[("文献", "d18", "2001", 1, "B2")], docx=FULL)
    assert json.loads(good)["links"][0]["head"] == head_of(plan.paras["d18"])
    res = _manual(FULL, good, meta, journal, tmp_path / "a")
    assert [(op["src"], op["target"]) for op, _ in res.ai.accepted] == [("d18", "B2")] and not res.ai.carried
    assert res.ai.answered_id == res.ai.request_id
    wrong = json.loads(good)
    wrong["links"][0]["src"] = "d17"            # head は d18 のまま
    res = _manual(FULL, json.dumps(wrong, ensure_ascii=False), meta, journal, tmp_path / "b")
    assert [op["src"] for op, _ in res.ai.accepted] == ["d18"] and res.ai.reread == [("links", "d17", "d18")]
    assert "d17 → d18" in _sec2(res)
    nohead = json.loads(good)
    nohead["links"][0]["head"] = ""
    res = _manual(FULL, json.dumps(nohead, ensure_ascii=False), meta, journal, tmp_path / "c")
    assert [op["src"] for op, _ in res.ai.accepted] == ["d18"]


def test_a_short_or_unknown_head_is_not_reread(journal, meta, tmp_path):
    """(a) head が 4 字に満たない・どの段落とも合わない指定は、読み替えずに不採用（理由は 2 章）。"""
    good = json.loads(answers.answer(links=[("文献", "d18", "2001", 1, "B2")], docx=FULL))
    for head, why in (("研究", "head が短くて"), ("架空の別の段落の文字", "同じ先頭の文字の段落が依頼文の段落にない")):
        d = json.loads(json.dumps(good))
        d["links"][0].update(src="d17", head=head)
        res = _manual(FULL, json.dumps(d, ensure_ascii=False), meta, journal, tmp_path / head)
        assert res.ai.accepted == [] and len(res.ai.rejected) == 1 and why in res.ai.rejected[0][1]


# ---------------------------------------------------------------------------- (b)
def test_b_answer_to_previous_draft_is_reread(journal, meta, tmp_path):
    """(b) 段落を 1 つ足した docx（構造は同じ）に、足す前の依頼文への回答を入れると、placements と links が先頭の文字で
    読み替わって使われ、carried に件数が書かれる。head のない項目は不採用。"""
    resp = json.loads(answers.answer(placements=[("s1", "d17"), ("s2", "d26"), ("s3", "d23")], docx=FLOAT))
    resp["style_fixes"] = [answers.style_fix("d23", "quote")]               # head なし（(b) では確かめられない）
    new = edited_docx(FLOAT, tmp_path / "new.docx", "図1は表で組んだ問題", "架空の段落を足した。")
    _, plan, _ = _mechanical(new, journal)
    assert head_of(plan.paras["d18"]) == resp["placements"][0]["after_head"]          # ID が 1 つずれた
    res = _manual(new, json.dumps(resp, ensure_ascii=False), meta, journal, tmp_path / "b")
    assert res.ai.request_id[:7] == resp["request_id"][:7] and res.ai.request_id != resp["request_id"]
    assert {(op["src"], op["target"]) for op, _ in res.ai.accepted} == {("s1", "d18"), ("s2", "d27"), ("s3", "d24")}
    assert [why for _, why in res.ai.rejected] == [CARRIED_NO_HEAD_WHY]
    assert res.ai.carried == ai_assist.CARRIED_MSG.format(n=4, m=3) and ai_state(res) != "失敗"
    assert "原稿を直す前の回答です。" in _sec2(res)
    # links も読み替わる（FULL の d18 の前に段落を足す）
    resp = answers.answer(links=[("文献", "d18", "2001", 1, "B2")], docx=FULL)
    _, plan0, _ = _mechanical(FULL, journal)
    new = edited_docx(FULL, tmp_path / "full.docx", plan0.paras["d18"].text_only()[:12], "架空の段落を足した。")
    res = _manual(new, resp, meta, journal, tmp_path / "c")
    assert [(op["src"], op["target"]) for op, _ in res.ai.accepted] == [("d19", "B2")] and res.ai.carried


def test_b_duplicate_head_is_not_reread(journal, meta, tmp_path):
    """(b) 同じ先頭の文字の段落が 2 つある原稿では読み替えず、不採用にする。"""
    resp = answers.answer(placements=[("s1", "d17")], docx=FLOAT)
    head = json.loads(resp)["placements"][0]["after_head"]
    new = edited_docx(FLOAT, tmp_path / "dup.docx", "図1は表で組んだ問題", "図3と図4は，1つのテキストボックスの中の架空の段落。")
    _, plan, _ = _mechanical(new, journal)
    assert sum(head_of(p) == head for p in plan.paras.values()) == 2
    res = _manual(new, resp, meta, journal, tmp_path / "b")
    assert res.ai.carried and [op["src"] for op, _ in res.ai.accepted] == []
    assert [why for op, why in res.ai.rejected if op["src"] == "s1"][0].endswith("2 つあって決められないので使わなかった（段落の ID の書き違いの疑い）")


# ---------------------------------------------------------------------------- (c)
def test_c_other_structure_or_no_id_is_refused(journal, meta, tmp_path):
    """(c) 文献を 1 つ足した docx・別の論文への回答・request_id のない回答は、1 件も使わない。文は 4.6 のとおりで、
    推奨の手順 ai_finish は「失敗」（必須ではない）。XML は回答なしと同じ。"""
    _, plan, _ = _mechanical(FLOAT, journal)
    resp = answers.answer(placements=[("s1", "d17")], docx=FLOAT)
    base = convert(FLOAT, meta, journal, Options(out_dir=tmp_path / "base", ai_mode="manual"))
    ref = plan.refs[-1].para.text_only()
    more = edited_docx(FLOAT, tmp_path / "ref.docx", ref[:10], "架空太郎（2099）．架空の文献．架空誌．", where="after")
    res = _manual(more, resp, meta, journal, tmp_path / "ref")
    assert res.ai.error == OTHER_REQUEST_MSG and res.ai.accepted == [] and res.ai.rejected == []
    other = answers.answer(placements=[("s1", "d17")], docx=NOTES)          # 別の論文の依頼文への回答
    noid = dict(json.loads(resp), request_id="")
    for out, text, msg in (("other", other, OTHER_REQUEST_MSG), ("noid", json.dumps(noid, ensure_ascii=False), NO_REQUEST_ID_MSG),
                           ("bad", json.dumps(dict(noid, request_id="R-1234"), ensure_ascii=False), OTHER_REQUEST_MSG)):
        res = _manual(FLOAT, text, meta, journal, tmp_path / out)
        assert res.ai.error == msg and res.ai.accepted == [] and res.ai.rejected == [] and ai_state(res) == "失敗"
        assert res.xml_path.read_bytes() == base.xml_path.read_bytes()
        fin = next(a for a in actions(res) if a.key == "ai_finish")
        assert fin.failed and not fin.required and msg in fin.box_detail


def test_request_id_written_in_full_width_is_accepted(journal, meta, tmp_path):
    """全角で写した依頼の番号も受ける（NFKC で比べる）。"""
    import unicodedata
    resp = json.loads(answers.answer(links=[("文献", "d18", "2001", 1, "B2")], docx=FULL))
    wide = "".join(chr(ord(c) + 0xFEE0) if "!" <= c <= "~" else c for c in resp["request_id"])
    assert unicodedata.normalize("NFKC", wide) == resp["request_id"] and wide != resp["request_id"]
    res = _manual(FULL, json.dumps(dict(resp, request_id=wide), ensure_ascii=False), meta, journal, tmp_path)
    assert not res.ai.error and len(res.ai.accepted) == 1


def test_cut_answer_keeps_request_id(journal, meta, tmp_path):
    """途中で切れた回答も、placements より前に書かれた request_id で確かめる（なければ断る）。"""
    resp = answers.answer(placements=[("s1", "d17"), ("s2", "d26")], docx=FLOAT)
    cut = resp[:resp.index('{"float": "s2"')]
    data = ai_assist.parse_cut_response(cut)
    assert data["request_id"] == json.loads(resp)["request_id"] and len(data["placements"]) == 1
    res = _manual(FLOAT, cut, meta, journal, tmp_path / "a")
    assert res.ai.partial and [op["src"] for op, _ in res.ai.accepted] == ["s1"]
    res = _manual(FLOAT, cut.replace(json.loads(resp)["request_id"], "", 1), meta, journal, tmp_path / "b")
    assert res.ai.error == NO_REQUEST_ID_MSG and not res.ai.partial and ai_state(res) == "失敗"
