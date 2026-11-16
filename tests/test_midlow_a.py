"""中低の問題 A: 知らせと入力の確かめ（XML は変えない）。

- C067: 手で書いた注の読み取りの問題（番号が読めない・本文から参照されない）の要確認 note_unlinked
- C038: 兄弟の見出しの深さの食い違い（style_check の heading_level）
- C077: 太字だけの 1 項目の順序つきリスト（style_check の heading_guess）
- C095: 責任著者の番号・制御文字の入力の確かめ（config.from_dict・要確認 meta_corresp）
- C057・C105: pypdfium2 の版の範囲と記録
内容はすべて架空。
"""
from types import SimpleNamespace

import pytest

from conftest import NOTES
from jasme_jats import report
from jasme_jats.pipeline import _mechanical
from jasme_jats.report import TO_CHECK


# ----------------------------------------------------------------------------- C067
def test_note_unlinked_uses_same_judgement_as_chapter3(journal):
    _, plan, _ = _mechanical(NOTES, journal)
    r = SimpleNamespace(plan=plan)
    assert report._note_unlinked_action(r) is None       # 正しく読めている原稿では出さない
    plan.fns[2].number = None                            # 番号を読み取れなかった注
    act = report._note_unlinked_action(r)
    assert act.level == TO_CHECK and act.key == "note_unlinked"
    _, _, unnum, unref = report.note_problems(plan)
    assert [f.fid for f in unnum] == ["fn3"]
    assert "を読み取れなかった注: fn3" in "".join(report.note_notes(plan))      # 3 章の文と同じ注
    assert "注 1 件が" in act.box_title and "（番号を読み取れない）" in act.box_title      # 件数は注の数（点検 review20 利用者向け 4）
    assert "fn3" in act.top and "3 段落を 1 件の注にまとめています" in act.top
    assert act.cli.startswith("要確認: ") and "Word" in act.top
    assert "AI による仕上げ（注のリンク・注の区切りの指定）でも直せます" in act.top      # AI の回答がないときだけ言う
    assert f"{report.step('docx')}でアップロードし直し" in act.box_detail              # Colab の枠: どこから入れ直すか（利用者向け 8）
    # 番号を読み取れないだけの注（本文から参照はされている）に「リンクされていない」と言わない（点検 review20 利用者向けの 2 回目）
    for text in (act.top, act.box_detail, act.cli):
        assert "リンクされていない" not in text and "リンクがなく" not in text and "リンクがありません" not in text
    assert "番号を読み取れなかった注には、複数の注が 1 件にまとまっていることがあります" in act.top


def test_note_unlinked_counts_unreferenced_notes_only_once(journal):
    _, plan, _ = _mechanical(NOTES, journal)
    for p, _where in report.body_paragraphs(plan):
        for a in p.atoms:
            if a.link is not None and a.link.attrs.get("ref-type") == "fn" and a.link.attrs.get("rid") == "fn2":
                a.link = None                       # 本文から注 2 へのリンクがない
    plan.fns[1].number = None                       # 参照もされず、番号も読めない注は 1 行
    act = report._note_unlinked_action(SimpleNamespace(plan=plan))
    _, _, unnum, unref = report.note_problems(plan)
    assert [f.fid for f in unnum] == ["fn2"] and "fn2" in [f.fid for f in unref]
    assert act.top.count("fn2（") == 1
    assert "）: 番号を読み取れない・本文から参照されていない" in act.top          # 行に当たる印を全部書く
    n = len({f.fid for f in unnum} | {f.fid for f in unref})
    assert f"注 {n} 件が" in act.box_title and "（番号を読み取れない・本文から参照されていない）" in act.box_title


def test_note_unlinked_with_ai_answer_does_not_say_ai_can_fix(journal):
    """AI の回答が入っているときは「AI でも直せる」と言わず、ai_boundary と同じ Word での直し方にそろえる（点検 review20 利用者向け 4）。"""
    from jasme_jats.ai_assist import AIOutcome, Boundary
    _, plan, _ = _mechanical(NOTES, journal)
    plan.fns[2].number = None
    ai = AIOutcome(mode="manual", raw="{}", boundaries=[Boundary(plan.fns[2].paras[0].src, "注の始まり", "fn", "", "")])
    act = report._note_unlinked_action(SimpleNamespace(plan=plan, ai=ai))
    assert "でも直せます" not in act.top
    assert "AI の回答で注の区切りは直しましたが" in act.top and "AI の回答を入れずに変換し直す" in act.top
    # 区切りを直した後なので、結果の文に「複数の注が 1 件の注になる」を書かない。番号を読み取れないだけなら「リンクされていない」と言わない
    assert "下に挙げた注は番号を読み取れていません" in act.top and "複数の注が 1 件の注" not in act.top
    assert "本文からリンクされていません" not in act.top and "リンクがありません" not in act.top


def test_note_unlinked_with_ai_answer_and_unreferenced_note_says_only_the_link(journal):
    from jasme_jats.ai_assist import AIOutcome, Boundary
    _, plan, _ = _mechanical(NOTES, journal)
    for p, _where in report.body_paragraphs(plan):
        for a in p.atoms:
            if a.link is not None and a.link.attrs.get("rid") == "fn2":
                a.link = None
    ai = AIOutcome(mode="manual", raw="{}", boundaries=[Boundary(plan.fns[2].paras[0].src, "注の始まり", "fn", "", "")])
    act = report._note_unlinked_action(SimpleNamespace(plan=plan, ai=ai))
    assert "下に挙げた注は本文からリンクされていません" in act.top
    assert "このまま登載すると、本文から注へのリンクがありません（3 章" in act.top and "複数の注が 1 件の注" not in act.top


def test_note_unlinked_points_to_superscript_note_marks(journal):
    """本文の注番号が Unicode の上付き文字の形なら、その段落 ID を手がかりに添える（読むだけ。点検 review20 利用者向け 9）。"""
    from jasme_jats.model import Atom
    _, plan, _ = _mechanical(NOTES, journal)
    for p, _where in report.body_paragraphs(plan):
        for a in p.atoms:
            if a.link is not None and a.link.attrs.get("rid") == "fn2":
                a.link = None
    body = next(p for p, where in report.body_paragraphs(plan) if where not in ("ref", "fn") and p.text_only().strip())
    body.atoms.append(Atom(kind="text", text="架空の主張である²⁾"))
    act = report._note_unlinked_action(SimpleNamespace(plan=plan))
    assert f"Unicode の上付き文字の「¹⁾」の形の文字が本文の {body.src} にあります" in act.top and "［検索］" in act.top
    assert "［検索］で「⁾」を探すと" in act.top and "「[」" not in act.top          # 見つかった形の文字だけを書く（点検 review20 の 2 回目）


def test_note_mark_hint_spacing_with_more_paragraphs(journal):
    """「ほか N 段落」の後ろに余分な空白を入れない（点検 review20 の 2 回目）。"""
    from jasme_jats.model import Atom
    _, plan, _ = _mechanical(NOTES, journal)
    bodies = [p for p, where in report.body_paragraphs(plan) if where not in ("ref", "fn") and p.text_only().strip()]
    assert len(bodies) > report.NOTE_MARK_SHOWN
    for p in bodies[:report.NOTE_MARK_SHOWN + 1]:
        p.atoms.append(Atom(kind="text", text="架空の主張である[1]"))
    hint = report._note_mark_hint(plan)
    assert "ほか 1 段落にあります" in hint and "段落 にあります" not in hint
    assert "［検索］で「[」を探すと" in hint and "「⁾」" not in hint


# ----------------------------------------------------------------------------- C038・C077（本文の構造の確かめ。XML は変えない）
import make_fixtures as mf
from test_body_back_suspects import _act, _convert, _kinds, _refs, _src, _xml

S = mf.S
para, run = mf.para, mf.run


def _sections(tmp_path, meta, journal, name, heads):
    """章見出し（sec1）「２．方法」の下に、(スタイル, 見出しの文字) の見出しを並べた小さな論文を変換する。"""
    def parts(b):
        out = [para(S["sec1"], "１．はじめに"), para(S["body"], "試験（2024）による。架空の本文である。"), para(S["sec1"], "２．方法")]
        for style, text in heads:
            out += [para(S[style], text), para(S["body"], f"{text}の架空の本文である。")]
        return out
    return _convert(tmp_path, name, parts, _refs(), meta, journal)


def test_sibling_heading_depth_mismatch_is_reported(meta, journal, tmp_path):
    res = _sections(tmp_path, meta, journal, "c038", [("sec2", "２．１　甲の方法"), ("sec3", "２．２　乙の方法"), ("sec2", "２．３　丙の方法")])
    src = _src(res, "２．２　乙の方法")
    assert _kinds(res, "heading_level") == [("heading_level", src)]
    assert "項見出しのスタイル" in res.plan.style_suspects[-1].detail and "節見出しのスタイル" in res.plan.style_suspects[-1].detail
    act = _act(res, "style_check")
    assert act.level == TO_CHECK and src in act.box_detail
    # 例は多数の階層の兄弟の番号、直し方は多数の階層のスタイルの名前 1 つ（点検 review20 利用者向け 7）
    row = next(x for x in act.box_detail.split("\n") if src in x)
    assert "「２．１」「２．３」など）は節見出しのスタイル" in row and "直し方: この見出しのスタイルを「節見出し」にする。" in row
    assert "「項見出し」" not in row
    assert _act(res, "ai_finish") is not None                  # 直す向きは PDF を見て決められる（AI の提案を待つ種類）
    # XML は変えない（入れ子は今のまま。節の下の項として出る）
    assert len(_xml(res).findall(".//body/sec/sec")) == 2 and len(_xml(res).findall(".//body/sec/sec/sec")) == 1
    assert res.fidelity.ok and res.dtd_valid and not res.needs_action


def test_sibling_depth_is_not_reported_when_aligned(meta, journal, tmp_path):
    res = _sections(tmp_path, meta, journal, "c038ok", [("sec2", "２．１　甲の方法"), ("sec2", "２．２　乙の方法")])
    assert _kinds(res, "heading_level") == []
    # 誌の慣習（章の下の「（1）」が節）や、系列の違う見出し（節の下の項に「（1）」）は、食い違いとしない
    res = _sections(tmp_path, meta, journal, "c038ok2", [("sec2", "（１）甲の方法"), ("sec2", "（２）乙の方法"),
                                                       ("sec2", "２．１　丙の方法"), ("sec3", "（１）丁の方法")])
    assert _kinds(res, "heading_level") == []


def test_sibling_depth_mismatch_when_space_after_number_is_gone(meta, journal, tmp_path):
    """PDF に合わせた docx で番号の後ろの空白が消え、題名が全角の数字で始まる形（「2.2．２倍…」）も 2 段の番号と読む（3 段の「2.2.2」と
    読まない。点検 review20 利用者向け 1）。"""
    res = _sections(tmp_path, meta, journal, "c038w", [("sec2", "2.1．甲の方法"), ("sec3", "2.2．２倍の方法"), ("sec2", "2.3．丙の方法")])
    assert _kinds(res, "heading_level") == [("heading_level", _src(res, "2.2．２倍の方法"))]


@pytest.mark.parametrize("text, parts", [
    ("3.2．２倍の方法", [3, 2]), ("３．２．１　題名", [3, 2, 1]), ("3.2.1題名", [3, 2, 1]), ("3．２倍の方法", [3]),
    ("3.1 題名", [3, 1]), ("3.1.2.1 題名", [3, 1, 2]), ("3.2024年の題名", None), ("3 題名", None), ("3.1", None),
])
def test_heading_number_reads_text_before_nfkc(text, parts):
    from jasme_jats.structure import _heading_number
    got = _heading_number(text)
    assert (got[0] if got else None) == parts


def test_sibling_depth_mismatch_in_paren_series(meta, journal, tmp_path):
    res = _sections(tmp_path, meta, journal, "c038p", [("sec2", "（１）甲の方法"), ("sec2", "（２）乙の方法"), ("sec3", "（３）丙の方法")])
    assert _kinds(res, "heading_level") == [("heading_level", _src(res, "（３）丙の方法"))]


def test_bold_single_item_ordered_list_is_reported(meta, journal, tmp_path):
    def parts(b):
        return [para(S["sec1"], "１．はじめに"), para(S["body"], "試験（2024）による。"),
                mf.list_item(S["body"], run("架空の太字の小見出し", b=True), num_id=7),
                para(S["body"], "その本文である。"),
                mf.list_item(S["body"], run("太字でない 1 項目"), num_id=7),
                para(S["body"], "続きの本文である。"),
                mf.list_item(S["body"], run("太字の項目 1", b=True), num_id=7), mf.list_item(S["body"], run("太字の項目 2", b=True), num_id=7),
                para(S["body"], "終わりの本文である。")]
    res = _convert(tmp_path, "c077", parts, _refs(), meta, journal)
    src = _src(res, "架空の太字の小見出し")
    assert _kinds(res, "heading_guess") == [("heading_guess", src)]        # 太字でない 1 項目・2 項目のリストは挙げない
    act = _act(res, "style_check")
    assert act.level == TO_CHECK and src in act.box_detail and "1 項目だけの番号つきリスト" in act.box_detail
    # 直し方はこの行だけで言い切る（見出しの一般の直し方を重ねない。章の下なので節見出し。点検 review20 利用者向け 5）
    row = next(x for x in act.box_detail.split("\n") if src in x)
    assert "スタイルを「節見出し」にする" in row and "見出しの番号として出ます" in row and "番号つきの箇条なら、そのままでよい" in row
    assert "PDF に合わせたいときだけ、［ホーム］の［段落番号］を外して" in row       # AI の提案の行と同じ直し方を先に書く（点検 review20 の 2 回目）
    assert "「本文」のスタイル" not in row and "「章見出し」" not in row
    xml = _xml(res)
    assert [len(x.findall("list-item")) for x in xml.iter("list")] == [1, 1, 2]      # リストは変えない
    assert res.fidelity.ok and res.dtd_valid and not res.needs_action


# ----------------------------------------------------------------------------- C095
from jasme_jats.config import ArticleMeta
from jasme_jats.pipeline import Options, convert


@pytest.mark.parametrize("v, expect", [(1, [1]), ("1", [1]), ("1,2", [1, 2]), ("１，２", [1, 2]), ([1, 2], [1, 2]), ("", []), (None, [])])
def test_corresp_is_read_as_positive_integers(v, expect):
    assert ArticleMeta.from_dict({"corresp": v}).corresp == expect


@pytest.mark.parametrize("v", ["0", "-1", "a", "1.5", [0], [1, -2], [1.5], [True], "1,x"])
def test_corresp_bad_value_is_a_value_error_with_a_sentence(v):
    with pytest.raises(ValueError, match="責任著者の番号「.*」を読めません"):
        ArticleMeta.from_dict({"corresp": v})


@pytest.mark.parametrize("key, v", [("keywords", "数学;\x01教育"), ("keywords_ja", ["数学\x08"]), ("keywords_en", "math​;edu"),
                                    ("doi", "10.1/\x00x"), ("subject_ja", "論文\x1f"), ("lpage", "12\x7f")])
def test_control_characters_in_text_fields_are_a_value_error(key, v):
    with pytest.raises(ValueError, match="見えない文字（制御文字など。U\\+[0-9A-F]{4}）が入っています"):
        ArticleMeta.from_dict({key: v})


def test_control_character_message_names_the_field_like_the_screen():
    """欄の名前は 1 画面版（app.LABELS）に合わせ、キーを括弧で添える。英字の名前の後ろは空白（点検 review20 利用者向け 6）。"""
    with pytest.raises(ValueError, match="^DOI の欄（doi）に、見えない文字.*DOI の欄を空にして"):
        ArticleMeta.from_dict({"doi": "10.1/\u200bx"})
    with pytest.raises(ValueError, match="^キーワード（英語）の欄（keywords_en）に"):
        ArticleMeta.from_dict({"keywords_en": ["a\ufeff"]})


@pytest.mark.parametrize("key, v, shown", [("lpage", "9\x0b", "最後のページの欄（last_page）"),
                                           ("subject_ja", "論文\u200b", "原稿種別（日本語）の欄（subject_other）"),
                                           ("subject_en", "Paper\u200b", "原稿種別（英語）の欄（subject_other_en）"),
                                           ("keywords_ja", "数学\x01", "キーワード（日本語）の欄（keywords_ja）")])
def test_control_character_message_names_notebook_variable(key, v, shown):
    """括弧に添える名前は、ノートブックの欄の変数名にそろえる（点検 review20 利用者向けの 2 回目）。"""
    import re
    with pytest.raises(ValueError, match="^" + re.escape(shown)):
        ArticleMeta.from_dict({key: v})


def test_newline_and_tab_in_text_fields_are_kept():
    assert ArticleMeta.from_dict({"keywords_ja": ["数学\t教育"], "doi": "10.1/x\n"}).keywords_ja == ["数学\t教育"]


def test_cli_reports_control_characters_without_traceback(tmp_path, capsys):
    from jasme_jats import cli
    toml = tmp_path / "m.toml"
    toml.write_text('[article]\nvolume = "31"\nkeywords_ja = ["数学\\u0001"]\n', encoding="utf-8")
    from conftest import NOTES as docx
    code = cli.main([str(docx), "--meta", str(toml), "--out", str(tmp_path / "o"), "--ai", "none"])
    err = capsys.readouterr().err
    assert code == 2 and "見えない文字" in err and "Traceback" not in err


def test_corresp_out_of_range_is_reported_not_fixed(journal, tmp_path):
    from conftest import NOTES as docx
    meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "9", "corresp": "1,9"})
    res = convert(docx, meta, journal, Options(out_dir=tmp_path))
    n = len(res.plan.authors)
    assert n < 9
    act = next(a for a in report.actions(res) if a.key == "meta_corresp")
    assert act.level == TO_CHECK and "9" in act.box_title and f"{n} 人" in act.box_title
    xml = res.xml_path.read_text(encoding="utf-8")
    assert xml.count('corresp="yes"') == 1                      # 範囲内の 1 番だけ。最後の著者などには付けない
    ok = convert(docx, ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "9", "corresp": "1"}), journal,
                 Options(out_dir=tmp_path / "ok"))
    assert not any(a.key == "meta_corresp" for a in report.actions(ok))


def test_corresp_report_shows_authors_and_chapter11_row(journal, tmp_path):
    """meta_corresp が指す 11 章に責任著者の行があり、文に著者の順を挙げる。著者が 1 人なら「1〜1」と書かない（点検 review20 の 2 回目）。"""
    from conftest import NOTES as docx
    meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "9", "corresp": "1,9"})
    res = convert(docx, meta, journal, Options(out_dir=tmp_path))
    names = report.author_names(res.plan)
    n = len(names)
    act = next(a for a in report.actions(res) if a.key == "meta_corresp")
    order = f"1: {names[0]}"
    for text in (act.top, act.box_detail, act.cli):
        assert order in text
    assert "著者の順は 1 章" not in act.top and "docx の和文の著者名の順" in act.top
    md = res.report_path.read_text(encoding="utf-8")
    ch11 = md.split("## 11. 書誌情報（入力値）", 1)[1].split("\n## ", 1)[0]
    row = next(x for x in ch11.splitlines() if x.startswith("| 責任著者 |"))
    assert f"1（{names[0]}）" in row and f"9（範囲外。著者は {n} 人。印を付けていません）" in row
    if n == 1:
        assert "1〜1" not in act.top + act.box_detail + act.cli
    # 番号が範囲内なら印を付けた著者の氏名だけ。入力がなければ「（未入力）」
    plan1 = SimpleNamespace(authors=res.plan.authors[:1])
    assert report.corresp_cell(SimpleNamespace(corresp=[1]), plan1) == f"1（{names[0]}）"
    assert report.corresp_cell(SimpleNamespace(corresp=[]), plan1) == "（未入力）"


def test_corresp_single_author_range_is_written_as_1(journal, tmp_path):
    from conftest import NOTES as docx
    meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "9", "corresp": "2"})
    res = convert(docx, meta, journal, Options(out_dir=tmp_path))
    res.plan.authors = res.plan.authors[:1]
    act = report._meta_corresp_action(res)
    assert "1〜1" not in act.top + act.box_detail + act.cli
    assert "責任著者の番号を、1 に直して" in act.top and "corresp を、1 の番号に直して" in act.cli


# ----------------------------------------------------------------------------- C057・C105
def test_pypdfium2_range_is_pinned_in_pyproject():
    import re
    from pathlib import Path
    text = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text(encoding="utf-8")
    found = re.findall(r'"(pypdfium2[^"]*)"', text)
    assert found == ["pypdfium2>=5,<6", "pypdfium2>=5,<6"]          # images と dev
    # Colab のノートブックは images を入れるので、範囲は pyproject から入る（ノートブックに版を直接書かない）
    assert "pypdfium2" not in (Path(__file__).resolve().parent.parent / "tools" / "make_notebook.py").read_text(encoding="utf-8")


def test_report_records_pypdfium2_version_only_when_installed(journal, meta, tmp_path, monkeypatch):
    from conftest import NOTES as docx
    res = convert(docx, meta, journal, Options(out_dir=tmp_path))
    head = res.report_path.read_text(encoding="utf-8").split("## 1.")[0]
    v = report.pdfium_version()
    if v:
        assert f"- PDF を読むライブラリ: pypdfium2 {v}\n" in head
        assert head.index("- ツール: jasme-jats") < head.index("- PDF を読むライブラリ")
    monkeypatch.setattr(report, "pdfium_version", lambda: "")
    assert "PDF を読むライブラリ" not in report.render(res)
    assert not any("pypdfium2" in a.key for a in report.actions(res))           # 知らせ（Action）にはしない
