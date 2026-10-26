"""注: テンプレートの規定（本文に上付きの「1)」、注は「注」の節）と違う書き方の原稿。

- Word の脚注機能で書かれた注（tests/fixtures/sample_edge.docx）
- Word の脚注と文末脚注（tests/fixtures/sample_structure.docx の節「Word の脚注と文末脚注」: ID の重なり、削除の変更履歴の
  中の参照、記号を自分で付けた文末脚注、脚注の中からの参照、参照のない脚注）と、その場で作る小さな論文
  （make_fixtures.make_article。空白だけの段落、XML に出力しない段落の中の参照、題目・所属・引用文献など注の番号を
  リンクにしない段落の中の参照と、builder が書いた注へのリンクとの一致）。修正計画の D4・N6
- 本文の大きさの「（注1）」、引用文献の後ろの注の節、番号の書き方が想定外の注（tests/fixtures/sample_notes.docx）
"""
import dataclasses
import json

import pytest
from lxml import etree

import make_fixtures as mf
from conftest import EDGE, NOTES, STRUCTURE
from jasme_jats.builder import build, finalize, serialize
from jasme_jats.config import ArticleMeta
from jasme_jats.docx_reader import read_docx
from jasme_jats.model import note_key, note_label
from jasme_jats.pipeline import Options, _mechanical, convert
from jasme_jats.report import TO_CHECK, actions, note_notes, word_note_refs
from jasme_jats.structure import NO_LINK_KINDS, note_mark
from jasme_jats.validate import validate

S = mf.S
# Word の脚注・文末脚注の段落への set_role を採用しないときの理由（ai_assist.set_role_problem）
WORD_NOTE_ROLE = "Word の脚注・文末脚注の段落の役割は変えられない（注の区切りは Word のとおりにする）"


def load(res):
    return etree.fromstring(res.xml_path.read_bytes().split(b"\n", 2)[2])


def text(el):
    return "".join(el.itertext())


def fn_list(root):
    """注の一覧: {注の ID: [段落の文字]}（XML の順）。"""
    return {fn.get("id"): [text(p) for p in fn.findall("p")] for fn in root.iter("fn")}


def fn_refs(root):
    """注へのリンク: [(rid, 文字, 上付きか)]（XML の順）。"""
    return [(x.get("rid"), text(x), x.find("sup") is not None) for x in root.iter("xref") if x.get("ref-type") == "fn"]


@pytest.fixture(scope="module")
def structure(journal, tmp_path_factory):
    """sample_structure.docx の変換結果（節「Word の脚注と文末脚注」を見る）。"""
    meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12", "pub_date": "2026-03-31",
                                  "received": "2025-06-01", "accepted": "2025-11-20", "peer_review": "あり"})
    return convert(STRUCTURE, meta, journal, Options(out_dir=tmp_path_factory.mktemp("structure"), convert_metafiles=False))


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
    assert [why for _, why in res.ai.rejected] == [WORD_NOTE_ROLE]


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
    # 脚注だけで、リンクのない注・記号を自分で付けた注もなければ、8 章は 0.23.1 と同じ（対応の表は出さない）
    ch8 = report.split("## 8.")[1].split("## 9.")[0]
    assert "（Word の脚注機能で書かれた注の番号だけは、Word の表示「1」ではなく本誌の形式（設定 fn_mark）にしています）" in ch8
    assert "XML の注の対応" not in ch8
    # 注の場所は「Word の脚注 5（注 1）」（0.23.1 は「Word の脚注 1件中」）
    fn = next(fn for fn in res.plan.fns if fn.word_note)
    assert res.plan.locations[fn.paras[0].src] == "Word の脚注 5（注 1）"


def test_word_footnote_mark_and_title_follow_config(journal, meta, tmp_path):
    j = dataclasses.replace(journal, fn_mark="[{n}]", fn_title="")
    res = convert(EDGE, meta, j, Options(out_dir=tmp_path, convert_metafiles=False))
    assert res.fidelity.ok and res.dtd_valid
    root = load(res)
    assert root.find(".//fn-group/title") is None
    assert text(root.find(".//fn-group/fn/p")).startswith("[1] Word")
    assert text(next(x for x in root.iter("xref") if x.get("ref-type") == "fn")) == "[1]"


# ----------------------------------------------------------------------------- Word の脚注と文末脚注（修正計画の D4）
def test_note_key_and_label():
    # 注の鍵は種類と ID の組（脚注と文末脚注は ID が重なりうる）。記号を自分で付けた参照も同じ注を指す
    assert note_key("footnote", "5") == "footnote:5" and note_key("endnote", "5") == "endnote:5"
    assert note_key("footnote-custom", "5") == "footnote:5" and note_key("endnote-custom", "7") == "endnote:7"
    assert note_label("footnote:5") == "Word の脚注 5" and note_label("endnote:5") == "Word の文末脚注 5"
    assert note_label("endnote-custom:5") == "Word の文末脚注 5"


def test_endnotes_are_output_as_notes(journal, meta, tmp_path):
    # Word の文末脚注は、脚注と同じく注の一覧（fn-group）に出し、本文の参照をリンクにする（0.23.1 までは除外していた。
    # docs/fix_plan_repro_tests.py の test_PROBLEM_endnotes_are_excluded の逆）
    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "文末脚注", mf.endnote_ref(3), "が付いた文。")]
    path = tmp_path / "end.docx"
    mf.make_article(path, "文末脚注の検証用文書", parts, endnotes=[mf.endnote(3, " 文末脚注の本文である。")])
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and res.jstage_issues == []
    root = load(res)
    assert root.find(".//fn-group/title").text == "注"
    assert fn_list(root) == {"fn1": ["1) 文末脚注の本文である。"]}
    assert fn_refs(root) == [("fn1", "1)", True)]
    assert not any("文末脚注" in reason for _, reason, _ in res.fidelity.excluded)
    report = res.report_path.read_text(encoding="utf-8")
    assert "注 1（うち Word の脚注・文末脚注 1）" in report
    # 文末脚注だけなら、判断の一覧に「脚注 0 件」とは書かない
    assert "Word の文末脚注機能で書かれた注 1 件を、本文で最初に参照される順の通し番号で注の一覧にした" in report
    assert "脚注 0 件" not in report


def test_endnote_becomes_fn_and_ids_do_not_collide(structure):
    # 脚注 5 と文末脚注 5 は ID が同じでも別の注（0.23.1 は、文末脚注 5 の参照も脚注 5 の fn1 にリンクしていた）
    res = structure
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and res.jstage_issues == []
    root = load(res)
    fns = fn_list(root)
    assert list(fns) == ["fn1", "fn2", "fn3", "fn4", "fn5"]
    assert fns["fn1"] == ["1) 脚注５の架空の説明。"]
    assert fns["fn2"] == ["2) 文末脚注５の一段落目の架空の説明。", "文末脚注５の二段落目の架空の補足。"]
    para = next(p for p in root.iter("p") if text(p).startswith("脚注を付けた文"))
    assert [(x.get("rid"), text(x), x.find("sup") is not None) for x in para.iter("xref")] == [("fn1", "1)", True),
                                                                                                ("fn2", "2)", True)]


def test_note_numbers_follow_first_reference(structure):
    # 脚注・文末脚注をまとめて、本文で最初に参照される順の通し番号（決定事項 7）。続けて、注の中から参照される注
    # （脚注 8 の中の文末脚注 8）。脚注の中から参照された文末脚注は、除外せずに注として出し、脚注の中の参照もリンクにする
    root = load(structure)
    assert fn_refs(root) == [("fn1", "1)", True), ("fn2", "2)", True), ("fn3", "", False), ("fn4", "4)", True),
                             ("fn5", "5)", True)]
    fns = fn_list(root)
    assert fns["fn4"] == ["4) 脚注８の中から文末脚注を参照する5)架空の説明。"]
    assert [x.get("rid") for x in root.find(".//fn[@id='fn4']").iter("xref")] == ["fn5"]
    assert fns["fn5"] == ["5) 脚注の中から参照される文末脚注８の架空の説明。"]
    assert not any("文末脚注８" in t for _, _, t in structure.fidelity.excluded)
    plan = structure.plan
    word = [fn for fn in plan.fns if fn.word_note]
    assert [(fn.word_kind, fn.word_id) for fn in word] == [("footnote", "footnote:5"), ("endnote", "endnote:5"),
                                                           ("endnote", "endnote:7"), ("footnote", "footnote:8"),
                                                           ("endnote", "endnote:8")]
    # 場所の表記は注ごと（0.23.1 は「Word の脚注 1件中」と全件数を書いていた）
    assert [plan.locations[p.src] for p in word[1].paras] == ["Word の文末脚注 5（注 2） 第1段落", "Word の文末脚注 5（注 2） 第2段落"]
    assert plan.locations[word[0].paras[0].src] == "Word の脚注 5（注 1）"


def test_custom_mark_endnote_keeps_docx_mark(structure):
    # 記号を自分で付けた文末脚注（customMarkFollows。暫定の判断で脚注と同じ扱い）: 番号を 1 つ使い、本文のリンクは中身のない
    # xref（docx の記号「*」はそのまま。番号は生成しない）、注の一覧の番号は「3)」。判断の一覧で知らせる
    root = load(structure)
    para = next(p for p in root.iter("p") if text(p).startswith("記号を自分で付けた文末脚注"))
    x = next(x for x in para.iter("xref") if x.get("rid") == "fn3")
    assert len(x) == 0 and not x.text
    assert text(para) == "記号を自分で付けた文末脚注*の文と，注の中から文末脚注を参照する脚注4)の文。"
    assert fn_list(root)["fn3"] == ["3) * 記号を自分で付けた文末脚注７の架空の説明。"]
    msgs = [d.message for d in structure.plan.decisions if d.category == "note"]
    assert any(m.startswith("Word の文末脚注 7（注 3）は、本文の記号を自分で付けた注") and "「3)」にした" in m for m in msgs)


def test_unreferenced_and_deleted_notes_are_excluded(structure):
    # 本文から参照されていない注（脚注 9）と、参照が削除の変更履歴の中にだけある注（脚注 6）は、理由付きで除外する
    # （0.23.1 は、どちらも出力も除外もせず、不変性チェックが不合格だった）。空白だけの段落は空白のみの段落として除外する
    fid = structure.fidelity
    assert fid.ok and fid.missing == [] and fid.bad_excluded == [] and fid.conflicts == []
    reasons = {t.strip(): why for _, why, t in fid.excluded}
    assert reasons["参照が削除された脚注６の架空の説明。"] == (
        "Word の脚注 6（本文の参照が変更履歴で削除された注。Word で変更をすべて承諾すると消える）")
    assert reasons["参照されていない脚注９の架空の説明。"] == "Word の脚注 9（本文から参照されていない注）"
    plan = structure.plan
    nine = [s for s, k in plan.note_of.items() if k == "footnote:9"]
    assert [(s, why) for s, why, t in fid.excluded if s in nine and t == "\u3000"] == [(nine[1], "空白のみの段落")]
    assert all(e.blank for e in plan.exclusions if e.reason == "空白のみの段落")
    assert {plan.locations[s] for s in nine} == {"Word の脚注 9"}
    xml = text(load(structure))
    assert "脚注６" not in xml and "脚注９" not in xml
    # 削除の変更履歴の中の参照は、参照として数えない（docx_reader が記録する）
    assert read_docx(STRUCTURE).deleted_note_refs == {"footnote:6"}


def test_blank_paragraphs_in_notes_pass_fidelity(journal, meta, tmp_path):
    # 参照された文末脚注の途中と、参照されていない脚注・文末脚注に、全角・半角の空白だけの段落があっても不変性チェックに
    # 合格する（参照された注の空白だけの段落は注の中に出し、参照されていない注のものは空白のみの段落として除外する）
    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "文末脚注を付けた文", mf.endnote_ref(3), "。")]
    path = tmp_path / "blank.docx"
    mf.make_article(path, "注の空白の検証用文書", parts,
                    endnotes=[mf.endnote(3, " 文末脚注の前半。", mf.para(None, "\u3000"), mf.para(None, " "),
                                         mf.para(None, "文末脚注の後半。")),
                              mf.endnote(5, "\u3000", mf.para(None, " "))],
                    footnotes=[mf.footnote(4, " 参照のない脚注。", mf.para("a8", "\u3000"), mf.para("a8", " "))])
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    fid = res.fidelity
    assert fid.ok and fid.final_ok and res.dtd_valid, (fid.missing, fid.bad_excluded)
    assert fn_list(load(res)) == {"fn1": ["1) 文末脚注の前半。", "\u3000", " ", "文末脚注の後半。"]}
    blank = sorted((s[0], t) for s, why, t in fid.excluded if why == "空白のみの段落")
    assert blank == [("e", " "), ("f", " "), ("f", "\u3000")]
    reasons = {t: why for _, why, t in fid.excluded}
    assert reasons[" 参照のない脚注。"] == "Word の脚注 4（本文から参照されていない注）"
    assert reasons["\u3000"] == "Word の文末脚注 5（本文から参照されていない注）"     # 番号のある 1 段落目（空白だけではない）


def _front_ref_article(path):
    """和文の冒頭の誌名の行（XML に出力しない段落）に Word の文末脚注の参照がある、小さな論文。"""
    b = mf.Builder()
    front = mf.front_ja(b, "リンクのない注の検証用文書", "―副題―", [("架空大学", "試験\u3000八郎")])
    front[0].append(b.frag(mf.para(None, mf.endnote_ref(3)))[0][0])
    b.endnotes_extra.append(mf.endnote(3, " 誌名の行から参照される架空の文末脚注。"))
    body = front + [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "試験（2025）にならう。"),
                    mf.para(S["ref_head"], "引用および参考文献"),
                    mf.para(S["ref"], "試験八郎（2025）．「題」．『架空誌』，第6巻，pp.11-12．")]
    body += mf.front_en(b, "Title", "Subtitle", [("Hachiro SHIKEN", "Fictional University")], ["Abstract text."])
    body += mf.tail(b)
    b.save(path, body)
    return path


def test_note_referenced_only_from_excluded_paragraph(journal, meta, tmp_path):
    # XML に出力しない段落（誌名の行）の中の参照も参照として数え、注は出力する（本文からのリンクのない注）。
    # 判断の一覧（4 章）と 8 章の表で知らせる。1 章のリンクの数には数えない
    res = convert(_front_ref_article(tmp_path / "front.docx"), meta, journal,
                  Options(out_dir=tmp_path / "out", convert_metafiles=False))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    root = load(res)
    assert fn_list(root) == {"fn1": ["1) 誌名の行から参照される架空の文末脚注。"]} and fn_refs(root) == []
    src = next(s for s, why, _ in res.fidelity.excluded if why.startswith("冒頭部のテンプレート装飾"))
    fn = next(fn for fn in res.plan.fns if fn.word_note)
    assert not fn.linked and fn.word_refs == [src]
    msgs = [d.message for d in res.plan.decisions if d.category == "note"]
    assert any(m.startswith(f"Word の文末脚注 3（注 1）は、本文の参照が XML に出力しなかった段落（{src}）の中にだけある")
               for m in msgs)
    report = res.report_path.read_text(encoding="utf-8")
    ch8 = report.split("## 8.")[1].split("## 9.")[0]
    assert (f"| fn1 | Word の文末脚注 3 | 1) | 誌名の行から参照される架空の文… | なし（参照は XML に出力しなかった段落 {src}"
            " の中だけ） |") in ch8
    assert "| 注 0 |" in report or "/ 注 0 /" in report


def _refs_article(path, places, body=(), refs=(), footnotes=(), endnotes=()):
    """和文の冒頭・英文の部分の段落の後ろに、Word の脚注・文末脚注の参照を足した小さな論文（架空の文字）。

    places: {場所: 参照の XML}。場所は journal（誌名の行。XML に出力しない段落）・title・subtitle・aff・name（著者表の所属・
    著者名）・title_en・subtitle_en・name_en・aff_en・abstract（英文要旨の 1 段落目）。body は「１．はじめに」の後ろの段落、
    refs は引用文献 1 件の後ろの段落の XML。
    """
    b = mf.Builder()
    b.footnotes_extra.extend(footnotes)
    b.endnotes_extra.extend(endnotes)
    front = mf.front_ja(b, "注の参照の場所の検証用文書", "―副題―", [("架空大学", "試験\u3000九郎")])
    cells = front[5].findall(f".//{{{mf.W}}}p")
    en = mf.front_en(b, "Title of the Article", "Subtitle", [("Kuro SHIKEN", "Fictional University")], ["Abstract text."])
    en_cells = en[4].findall(f".//{{{mf.W}}}p")
    spots = {"journal": front[0], "title": front[2], "subtitle": front[3], "aff": cells[0], "name": cells[1],
             "title_en": en[2], "subtitle_en": en[3], "name_en": en_cells[0], "aff_en": en_cells[1]}
    for where, ref in places.items():
        if where == "abstract":
            en[6] = mf.para(S["abs"], "Abstract text.", ref)     # 英文要旨の段落は XML の文字列
        else:
            spots[where].extend(b.frag(ref))
    doc = front + [mf.para(S["sec1"], "１．はじめに"), *body, mf.para(S["ref_head"], "引用および参考文献"),
                   mf.para(S["ref"], "試験九郎（2025）．「題」．『架空誌』，第7巻，pp.13-14．"), *refs]
    b.save(path, doc + en + mf.tail(b))
    return path


def test_notes_referenced_only_from_title_and_references_have_no_link(journal, meta, tmp_path):
    # 題目・副題・所属・引用文献などの中の参照は、注の番号を上付きの文字で出すだけで、リンクにしない（emit の xref=False の
    # 文脈）。参照がそこにだけある注は、本文からのリンクのない注として判断の一覧と 8 章の表で知らせ、1 章のリンクの数に
    # 数えない（修正前は、8 章の表に「あり」と出し、1 章のリンクの数にも数えていた）
    fr, er = mf.footnote_ref, mf.endnote_ref
    path = _refs_article(
        tmp_path / "title.docx",
        {"journal": fr(6), "title": er(1) + er(5), "subtitle": fr(2), "aff": fr(6), "title_en": er(3), "aff_en": fr(7)},
        body=[mf.para(S["body"], "本文から題目と同じ文末脚注", er(5), "を参照する。")],
        refs=[mf.para(S["ref"], "試験十郎（2024）．「別の題」．『架空誌』", fr(4), "．")],
        footnotes=[mf.footnote(n, f" 架空の脚注{n}。") for n in (2, 4, 6, 7)],
        endnotes=[mf.endnote(n, f" 架空の文末脚注{n}。") for n in (1, 3, 5)])
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and res.jstage_issues == []
    plan, root = res.plan, load(res)
    word = {fn.word_id: fn for fn in plan.fns if fn.word_note}
    # 番号は、誌名の行の脚注 6 が 1)、題目の文末脚注 1・5 が 2)・3)（本文で最初に参照される順）
    assert [(fn.fid, k) for k, fn in word.items()] == [
        ("fn1", "footnote:6"), ("fn2", "endnote:1"), ("fn3", "endnote:5"), ("fn4", "footnote:2"), ("fn5", "footnote:4"),
        ("fn6", "endnote:3"), ("fn7", "footnote:7")]
    # XML の注へのリンクは、本文から参照した文末脚注 5 の 1 つだけ（題目の中の同じ注の参照はリンクにならない）
    assert fn_refs(root) == [("fn3", "3)", True)]
    assert [k for k, fn in word.items() if fn.linked] == ["endnote:5"]
    assert text(root.find(".//article-title")) == "注の参照の場所の検証用文書2)3)"
    assert word_note_refs(plan) == 1
    report = res.report_path.read_text(encoding="utf-8")
    assert "注 1（うち Word の脚注・文末脚注 1）" in report
    t, st, ref, t_en = plan.title[0].src, plan.subtitle[0].src, plan.refs[1].para.src, plan.title_en[0].src
    aff, aff_en = plan.affs[0].ja.src, plan.affs[0].en.src
    journal_line = word["footnote:6"].word_refs[0]
    assert word["footnote:6"].word_refs == [journal_line, aff] and journal_line in {e.src for e in plan.exclusions}
    ch8 = report.split("## 8.")[1].split("## 9.")[0]
    tail = f"の中だけ。{NO_LINK_KINDS}の中の注の番号はリンクにしない） |"
    for row in (f"| fn1 | Word の脚注 6 | 1) | 架空の脚注6。 | なし（参照は XML に出力しなかった段落 {journal_line} と、所属の段落 {aff} {tail}",
                f"| fn2 | Word の文末脚注 1 | 2) | 架空の文末脚注1。 | なし（参照は題目の段落 {t} {tail}",
                "| fn3 | Word の文末脚注 5 | 3) | 架空の文末脚注5。 | あり |",
                f"| fn4 | Word の脚注 2 | 4) | 架空の脚注2。 | なし（参照は副題の段落 {st} {tail}",
                f"| fn5 | Word の脚注 4 | 5) | 架空の脚注4。 | なし（参照は引用文献の段落 {ref} {tail}",
                f"| fn6 | Word の文末脚注 3 | 6) | 架空の文末脚注3。 | なし（参照は英文題目の段落 {t_en} {tail}",
                f"| fn7 | Word の脚注 7 | 7) | 架空の脚注7。 | なし（参照は所属の段落 {aff_en} {tail}"):
        assert row in ch8
    msgs = [d.message for d in plan.decisions if d.category == "note"]

    def why(kind):
        return f"本文からのリンクのない注として出力した（{kind}の中の注の番号は、リンクにせず上付きの番号だけにする。8 章）"
    assert f"Word の文末脚注 1（注 2）は、参照が題目の段落 {t} の中にだけあるので、{why('題目')}" in msgs
    assert f"Word の脚注 4（注 5）は、参照が引用文献の段落 {ref} の中にだけあるので、{why('引用文献')}" in msgs
    # 出力しなかった段落の中の参照もある注には、本文の段落に移す案内を付ける
    assert (f"Word の脚注 6（注 1）は、参照が XML に出力しなかった段落 {journal_line} と、所属の段落 {aff} の中にだけあるので、"
            f"{why('所属')}。本文からリンクする注なら、Word で参照を本文の段落に移して変換し直す") in msgs
    assert not any(m.startswith("Word の文末脚注 5（注 3）は") for m in msgs)


def test_note_in_author_name_has_no_number(journal, meta, tmp_path):
    # 著者名（和文・英文）の中の Word の注の参照は、番号も出さない（著者名の要素には上付きの文字を置けない。0.23.1 は上付きの番号を
    # surname・given-names の中に入れ、DTD 検証が不合格だった）。注は本文からのリンクのない注として出し、判断の一覧と 8 章で知らせる
    path = _refs_article(tmp_path / "name.docx", {"name": mf.endnote_ref(5), "name_en": mf.footnote_ref(5)},
                         body=[mf.para(S["body"], "本文の段落。")],
                         footnotes=[mf.footnote(5, " 英文の著者名の架空の脚注。")], endnotes=[mf.endnote(5, " 著者名の架空の文末脚注。")])
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and res.jstage_issues == []
    assert "dtd" not in {a.key for a in actions(res)}
    root = load(res)
    assert [text(n) for n in root.iter("name")] == ["試験九郎", "SHIKENKuro"]       # 番号は出さない（姓・名の文字は docx のまま）
    assert fn_list(root) == {"fn1": ["1) 著者名の架空の文末脚注。"], "fn2": ["2) 英文の著者名の架空の脚注。"]} and fn_refs(root) == []
    name_ja, name_en = res.plan.authors[0].name_ja.src, res.plan.authors[0].name_en.src
    msgs = [d.message for d in res.plan.decisions if d.category == "note"]
    assert (f"Word の文末脚注 5（注 1）は、参照が著者名の段落 {name_ja} の中にだけあるので、本文からのリンクのない注として出力した"
            "（著者名の中の注の番号は、著者名に上付きの文字を置けないので出力しない。8 章）") in msgs
    ch8 = res.report_path.read_text(encoding="utf-8").split("## 8.")[1].split("## 9.")[0]
    assert (f"| fn2 | Word の脚注 5 | 2) | 英文の著者名の架空の脚注。 | なし（参照は著者名の段落 {name_en} の中だけ。{NO_LINK_KINDS}の中の"
            "注の番号はリンクにしない。著者名の中では番号も出力しない） |") in ch8


def test_title_footnote_is_listed_in_chapter8(journal, meta, tmp_path):
    # 脚注だけの論文でも、題目に付けた脚注（助成の謝辞など）は本文からのリンクのない注なので、8 章に対応の表を出す
    # （表の前置きは「Word の脚注と、XML の注の対応:」。8 章の説明の文は脚注だけのときのまま）。1 章のリンクの数には、
    # 本文の脚注の参照だけを数える
    fr = mf.footnote_ref
    path = _refs_article(tmp_path / "fnonly.docx", {"title": fr(1)},
                         body=[mf.para(S["body"], "本文の脚注", fr(2), "の文。")],
                         footnotes=[mf.footnote(1, " 本研究は架空の助成を受けた。"), mf.footnote(2, " 本文の架空の脚注。")])
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    assert fn_refs(load(res)) == [("fn2", "2)", True)]
    t = res.plan.title[0].src
    report = res.report_path.read_text(encoding="utf-8")
    assert "注 1（うち Word の脚注 1）" in report
    ch8 = report.split("## 8.")[1].split("## 9.")[0]
    assert "（Word の脚注機能で書かれた注の番号だけは、Word の表示「1」ではなく本誌の形式（設定 fn_mark）にしています）" in ch8
    assert "Word の脚注と、XML の注の対応（「Word の注」の番号は docx の中の番号で、" in ch8
    assert (f"| fn1 | Word の脚注 1 | 1) | 本研究は架空の助成を受けた。 | なし（参照は題目の段落 {t} の中だけ。{NO_LINK_KINDS}の中の"
            "注の番号はリンクにしない） |") in ch8
    assert "| fn2 | Word の脚注 2 | 2) | 本文の架空の脚注。 | あり |" in ch8


def test_chapter8_excerpt_uses_first_paragraph_with_text(journal, meta, tmp_path):
    # 8 章の表の「注の書き出し」は、文字のある最初の段落の docx の文字（1 段落目が番号と空白だけの注も、Word で探せるように）
    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "文末脚注を付けた文", mf.endnote_ref(3), "。")]
    path = tmp_path / "head.docx"
    mf.make_article(path, "注の書き出しの検証用文書", parts,
                    endnotes=[mf.endnote(3, "\u3000", mf.para(None, "二段落目から始まる架空の文末脚注の説明。"))])
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    ch8 = res.report_path.read_text(encoding="utf-8").split("## 8.")[1].split("## 9.")[0]
    assert "| fn1 | Word の文末脚注 3 | 1) | 二段落目から始まる架空の文末脚… | あり |" in ch8


@pytest.mark.parametrize("name", ["edge", "structure", "everywhere"])
def test_word_note_links_match_xml(journal, meta, tmp_path, name):
    # FnNode.linked と 1 章のリンクの数（report.word_note_refs）は、builder が実際に書いた注へのリンクと一致する
    # （ArticlePlan.no_link_paras は builder の書き出しの文脈をなぞったもの。文脈を変えたら合わせる）。everywhere は、
    # 参照を冒頭・英文の部分の各段落・見出し・本文・表のセル・引用文献・英文要旨・注の中に置いた論文。著者名の中の参照は、
    # 番号も出さずに DTD に合う XML にする（0.23.1 は上付きの番号を surname・given-names の中に入れ、DTD 検証が不合格だった）
    if name == "everywhere":
        fr, er = mf.footnote_ref, mf.endnote_ref
        places = {"journal": fr(1), "title": fr(2), "subtitle": er(3), "aff": fr(4), "name": er(5), "title_en": fr(6),
                  "subtitle_en": er(7), "name_en": fr(8), "aff_en": er(9), "abstract": fr(15)}
        path = _refs_article(
            tmp_path / "all.docx", places,
            body=[mf.para(S["sec2"], "（１）見出しの文末脚注", er(10)), mf.para(S["body"], "本文の脚注", fr(11), "。"),
                  mf.table([[mf.cell(mf.para(S["body"], "セルの脚注", fr(12)))]]), mf.para(S["body"], "表の後の文。")],
            refs=[mf.para(S["ref"], "試験十郎（2024）．「別の題」．『架空誌』", er(13), "．")],
            footnotes=[mf.footnote(n, f" 架空の脚注{n}。") for n in (1, 2, 4, 6, 8, 12, 15)]
            + [mf.footnote(11, mf.run(" 中から文末脚注を参照する脚注") + er(14) + mf.run("。"))],
            endnotes=[mf.endnote(n, f" 架空の文末脚注{n}。") for n in (3, 5, 7, 9, 10, 13, 14)])
    else:
        path = {"edge": EDGE, "structure": STRUCTURE}[name]
    _, plan, _ = _mechanical(path, journal)
    root, _ = build(plan, meta, journal)
    word = {fn.fid: fn for fn in plan.fns if fn.word_note}
    xrefs = [x.get("rid") for x in root.iter("xref") if x.get("ref-type") == "fn" and x.get("rid") in word]
    assert word and set(xrefs) == {fid for fid, fn in word.items() if fn.linked}
    assert len(xrefs) == word_note_refs(plan)
    ok, errors = validate(serialize(finalize(root)))
    assert ok, errors
    if name == "everywhere":
        assert len(word) == 15
        assert sorted(fn.word_id for fn in word.values() if fn.linked) == [
            "endnote:10", "endnote:14", "footnote:11", "footnote:12", "footnote:15"]
        # 著者名（和文・英文）の中の参照は、番号を出さない。注は本文からのリンクのない注として出し、判断の一覧で知らせる
        names = [text(n) for n in root.iter("name")]
        assert names and not any(n.endswith(")") for n in names)
        name_ja = plan.authors[0].name_ja.src
        msgs = [d.message for d in plan.decisions if d.category == "note"]
        assert any(m.startswith("Word の文末脚注 5（注 ") and f"参照が著者名の段落 {name_ja} の中にだけあるので" in m
                   and "（著者名の中の注の番号は、著者名に上付きの文字を置けないので出力しない。8 章）" in m for m in msgs)


@pytest.mark.parametrize("kind", ["endnote", "footnote"])
def test_manual_and_word_notes_with_same_numbers_are_reported(journal, meta, tmp_path, kind):
    # 「注」の節に手で書いた注（「1)」）と Word の脚注・文末脚注が両方あると、Word の注の番号も 1 から付くので、注の一覧に同じ番号の
    # 別の注が並ぶ。番号は変えずに（手で書いた注の後ろから続けるかは利用者に未確認）、10 章の警告と要確認で知らせる
    # （0.23.1 では、文末脚注は除外して要確認で知らせ、脚注は何も知らせていなかった）
    ref = mf.endnote_ref(3) if kind == "endnote" else mf.footnote_ref(3)
    note = (mf.endnote if kind == "endnote" else mf.footnote)(3, " Word の注の架空の文。")

    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "手で書いた注の番号", mf.run("1)", sup=True), "と Word の注", ref, "の文。"),
                mf.para(S["fn_head"], "注"), mf.para(S["body"], "1) 手で書いた架空の注。")]
    path = tmp_path / f"{kind}.docx"
    mf.make_article(path, "手で書いた注と Word の注の検証用文書", parts,
                    **({"endnotes": [note]} if kind == "endnote" else {"footnotes": [note]}))
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    root = load(res)
    assert fn_list(root) == {"fn1": ["1) 手で書いた架空の注。"], "fn2": ["1) Word の注の架空の文。"]}
    assert fn_refs(root) == [("fn1", "1)", True), ("fn2", "1)", True)]       # リンク先は正しい（番号だけが重なる）
    assert res.plan.note_overlap == [1]
    assert ("手で書いた注と Word の脚注・文末脚注が両方あり、注の番号 1) が重なっています（Word の注の番号は本誌の形式で 1 から"
            "付けるため）。") in "".join(res.warnings)
    [act] = [a for a in actions(res) if a.key == "note_overlap"]
    assert act.level == TO_CHECK and not res.needs_action
    report = res.report_path.read_text(encoding="utf-8")
    assert ("> **要確認: 手で書いた注と Word の脚注・文末脚注が両方あり、注の番号 1) が重なっています（10 章）。**"
            in report.split("## 2.")[0])
    assert "- [ ] **注の番号の重なり**（1)。10 章）" in report.split("## 14.")[1]
    assert "手で書いた注と Word の脚注・文末脚注が両方あり" in report.split("## 10.")[1].split("## 11.")[0]


def test_note_overlap_is_not_reported_without_both_kinds(structure, journal):
    # Word の注だけ（sample_structure.docx）、手で書いた注だけ（sample_notes.docx）の原稿では知らせない
    assert structure.plan.note_overlap == [] and "note_overlap" not in {a.key for a in actions(structure)}
    _, plan, _ = _mechanical(NOTES, journal)
    assert plan.fns and not any(fn.word_note for fn in plan.fns) and plan.note_overlap == []


def test_ai_cannot_set_role_on_word_notes(journal, meta, tmp_path):
    # Word の脚注・文末脚注の段落（参照のない注も）への set_role は、どの役割も採用しない（修正計画の N6。0.23.1 は p・exclude を
    # 「採用」と記録しながら何も変えていなかった）
    _, plan, _ = _mechanical(STRUCTURE, journal)
    endnote = next(fn.paras[0].src for fn in plan.fns if fn.word_id == "endnote:5")
    footnote = next(fn.paras[0].src for fn in plan.fns if fn.word_id == "footnote:5")
    unref = next(s for s, k in plan.note_of.items() if k == "footnote:9")
    ops = [_op(op="set_role", src=endnote, role="p"), _op(op="set_role", src=endnote, role="exclude"),
           _op(op="set_role", src=footnote, role="fn_start"), _op(op="set_role", src=unref, role="p")]
    res = convert(STRUCTURE, meta, journal, Options(out_dir=tmp_path, ai_mode="manual", convert_metafiles=False,
                                                    ai_response=json.dumps({"operations": ops, "placements": [], "notes": []},
                                                                           ensure_ascii=False)))
    assert [why for _, why in res.ai.rejected] == [WORD_NOTE_ROLE] * 4
    assert not any(op["op"] == "set_role" for op, _ in res.ai.accepted)
    assert res.fidelity.ok and list(fn_list(load(res))) == ["fn1", "fn2", "fn3", "fn4", "fn5"]


def test_report_lists_word_notes_with_endnotes(structure):
    # 文末脚注があるときは、1 章の表記を「Word の脚注・文末脚注」にし、8 章に Word の注と XML の注の対応の表を出す
    report = structure.report_path.read_text(encoding="utf-8")
    assert "注 5（うち Word の脚注・文末脚注 5）" in report
    ch8 = report.split("## 8.")[1].split("## 9.")[0]
    assert "本文で最初に参照される順の通し番号を本誌の形式〈設定 fn_mark〉で付けています。対応は下の表" in ch8
    # 「Word の注」の番号は docx の中の ID（Word の画面の番号とは違うことがある）なので、注の書き出しも載せる（15 文字まで）
    assert "Word の脚注・文末脚注と、XML の注の対応（「Word の注」の番号は docx の中の番号で、" in ch8
    assert "| fn1 | Word の脚注 5 | 1) | 脚注５の架空の説明。 | あり |" in ch8
    assert "| fn2 | Word の文末脚注 5 | 2) | 文末脚注５の一段落目の架空の説… | あり |" in ch8
    assert ("| fn3 | Word の文末脚注 7 | 3) | * 記号を自分で付けた文末脚注… | あり（中身のない参照。本文の記号はリンクの外で docx の"
            "文字のまま。J-STAGE のプレビューで確かめる） |") in ch8
    assert "Word の脚注・文末脚注機能で書かれた注 5 件（脚注 2 件・文末脚注 3 件）を、本文で最初に参照される順の通し番号で" in report
