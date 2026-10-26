"""注: テンプレートの規定（本文に上付きの「1)」、注は「注」の節）と違う書き方の原稿。

- Word の脚注機能で書かれた注（tests/fixtures/sample_edge.docx）
- Word の脚注と文末脚注（tests/fixtures/sample_structure.docx の節「Word の脚注と文末脚注」: ID の重なり、削除の変更履歴の
  中の参照、記号を自分で付けた文末脚注、脚注の中からの参照、参照のない脚注）と、その場で作る小さな論文
  （make_fixtures.make_article。空白だけの段落、XML に出力しない段落の中の参照）。修正計画の D4・N6
- 本文の大きさの「（注1）」、引用文献の後ろの注の節、番号の書き方が想定外の注（tests/fixtures/sample_notes.docx）
"""
import dataclasses
import json

import pytest
from lxml import etree

import make_fixtures as mf
from conftest import EDGE, NOTES, STRUCTURE
from jasme_jats.config import ArticleMeta
from jasme_jats.docx_reader import read_docx
from jasme_jats.model import note_key, note_label
from jasme_jats.pipeline import Options, _mechanical, convert
from jasme_jats.report import note_notes
from jasme_jats.structure import note_mark

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
    assert "Word の脚注・文末脚注機能で書かれた注 1 件（脚注 0 件・文末脚注 1 件）を、本文で最初に参照される順の通し番号で" in report


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
    assert f"| fn1 | Word の文末脚注 3 | 1) | なし（参照は XML に出力しなかった段落 {src} の中だけ） |" in ch8
    assert "| 注 0 |" in report or "/ 注 0 /" in report


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
    assert "| fn1 | Word の脚注 5 | 1) | あり |" in ch8 and "| fn2 | Word の文末脚注 5 | 2) | あり |" in ch8
    assert "| fn3 | Word の文末脚注 7 | 3) | あり（本文の記号は docx の文字のまま） |" in ch8
    assert "Word の脚注・文末脚注機能で書かれた注 5 件（脚注 2 件・文末脚注 3 件）を、本文で最初に参照される順の通し番号で" in report
