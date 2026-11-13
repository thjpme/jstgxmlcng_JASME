"""和文の著者名の姓と名の分け方（C010・C064・C072）。

字の間に空白を入れて揃えた和文の氏名（「試\u3000験\u3000六\u3000郎」）は、空白の連なりの数と長さで分ける（builder.split_eastern）:
1 つならそこで分け、2 つ以上でいちばん長い連なりが 1 つならそこで分け、いちばん長い連なりが 2 つ以上なら境目を推定する（論文の中の
引用の形の「姓だけ」の表記、なければ字数）。姓・名の中の字間の空白と、氏名の前後の空白は落とす（Emitter.drop。7 章）。いちばん長い空白で分けたもの・
推定で分けたもの・AI が分けたもの・分けられなかったもの（空白のない氏名）は、要確認 name_split で知らせる。氏名はすべて架空。
"""
import pytest
from lxml import etree

import answers
import make_fixtures as mf
from jasme_jats import pdfmatch
from jasme_jats.builder import (NAME_EDGE_REASON, NAME_GAP_REASONS, NAME_INNER_REASON, build, name_context,
                                split_eastern, surname_hint)
from jasme_jats.pipeline import Options, _mechanical, convert
from jasme_jats.report import TO_CHECK, actions

REF = "試験六郎（2024）．「小さな論文」．『架空誌』，第5巻，pp.9-10．"


def names_doc(path, ja_name, body_text, en_name="Rokuro SHIKEN", ref=REF):
    """和文の著者名 1 人・本文 1 段落・引用文献 1 件の小さな論文。"""
    b = mf.Builder()
    body = mf.front_ja(b, "氏名の検証用文書", "―姓と名―", [("架空大学", ja_name)])
    body += [mf.para(mf.S["sec1"], "１．はじめに"), mf.para(mf.S["body"], body_text),
             mf.para(mf.S["ref_head"], "引用および参考文献"), mf.para(mf.S["ref"], ref)]
    body += mf.front_en(b, "Checking Names", "Surnames", [(en_name, "Fictional University")], ["Name abstract."])
    body += mf.tail(b)
    b.save(path, body)
    return path


def load(res):
    return etree.fromstring(res.xml_path.read_bytes().split(b"\n", 2)[2])


def eastern(res):
    [nm] = [n for n in load(res).iter("name") if n.get("name-style") == "eastern"]
    return [(x.tag, x.text) for x in nm]


# ----------------------------------------------------------------------------- 規則（単体）
@pytest.mark.parametrize("text, context, how, sur, giv", [
    ("試験\u3000六郎", "", "single", "試験", "六郎"),
    ("試\u3000験\u3000\u3000洋", "", "longest", "試験", "洋"),
    ("試\u3000験\u3000六\u3000郎", "", "count", "試験", "六郎"),
    ("試\u3000験\u3000六\u3000郎", "また，試験（2020）は", "context", "試験", "六郎"),
    ("試\u3000験\u3000六\u3000郎", "試験・研究（2021）", "context", "試験", "六郎"),
    ("試\u3000験\u3000六\u3000郎", "試験ら (2019)", "context", "試験", "六郎"),
    ("林\u3000太\u3000郎", "", "count", "林太", "郎"),
    ("林\u3000太\u3000郎", "これは林（2019）による", "context", "林", "太郎"),
    ("林\u3000太\u3000郎", "小林（2019）による", "count", "林太", "郎"),           # 前が漢字: 別の語の一部
    ("試\u3000験\u3000六\u3000郎", "試験六郎（2024）", "count", "試験", "六郎"),    # 氏名の全体の一部は数えない
    ("試\u3000験\u3000六\u3000郎", "試験を行った", "count", "試験", "六郎"),        # 引用の形でない: 手がかりにしない
    ("試\u3000験\u3000六\u3000郎", "試（2019），試験（2020）", "count", "試験", "六郎"),   # 2 つの境目に現れる: 決めない
    ("試\u3000験\u3000六\u3000郎", "試験六（2019）", "context", "試験六", "郎"),
    ("\u3000試験六郎\u3000", "", "none", "試験六郎", ""),
    ("試 験 六 郎", "", "count", "試験", "六郎"),
    ("試\u3000験\u3000\ufffc", "", "single", "試", "験\ufffc"),     # 注の参照とその前の空白は、氏名の空白に数えない
    ("試験\u3000六郎\u3000\ufffc", "", "single", "試験", "六郎\ufffc"),
    ("試\u3000験 六 郎", "", "longest", "試", "験六郎"),               # 全角の空白は半角 2 つ分: いちばん長いのは最初の空白
    ("試\u3000験  六郎", "", "count", "試験", "六郎"),                  # 全角 1 つ = 半角 2 つ: 長さが同じ
    ("Taro\u3000Q\u3000SHIKEN", "", "latin", "Taro", "QSHIKEN"),     # ローマ字の氏名: 最初の空白で分ける（語の間の空白は残す）
    # 引用の形（論文の中の表記からの推定）
    ("林\u3000太\u3000郎", "林ら（2019）の研究", "context", "林", "太郎"),
    ("林\u3000太\u3000郎", "林・試験（2019）の研究", "context", "林", "太郎"),
    ("林\u3000太\u3000郎", "（林，2019）", "context", "林", "太郎"),
    ("林\u3000太\u3000郎", "（林, 2019; 試験, 2020）", "context", "林", "太郎"),
    ("林\u3000太\u3000郎", "（林,2015)", "context", "林", "太郎"),
    ("林\u3000太\u3000郎", "林他（2019）・林ほか（2020）", "context", "林", "太郎"),
    ("林\u3000太\u3000郎", "林 (2020a)", "context", "林", "太郎"),
    ("林\u3000太\u3000郎", "林（印刷中）", "context", "林", "太郎"),
    ("林\u3000太\u3000郎", "林（in press）", "context", "林", "太郎"),
    # 引用の形でないものは手がかりにしない（1 字の姓にしない）
    ("中\u3000川\u3000郎", "中1と高2の生徒。小・中の差。", "count", "中川", "郎"),
    ("上\u3000田\u3000郎", "その上，条件を変えた。", "count", "上田", "郎"),
    ("高\u3000橋\u3000郎", "高1の生徒を対象とした。", "count", "高橋", "郎"),
    ("林\u3000太\u3000郎", "林，2015年に行った。林（12）と林・試験，と林ら．", "count", "林太", "郎"),
    ("林\u3000太\u3000郎", "林（2019年", "count", "林太", "郎"),             # 括弧の形でも、年の直後が「年」なら日付
    ("林\u3000太\u3000郎", "林（2019年に、中（2015年度）", "count", "林太", "郎"),
    ("林\u3000太\u3000郎", "林・試験・架空（2019）", "context", "林", "太郎"),
    ("林\u3000太\u3000郎", "林・Smith（2019）", "context", "林", "太郎"),
    ("林\u3000太\u3000郎", "林・これは長すぎる語（2019）", "count", "林太", "郎"),   # 「・共著者」は氏名らしい 1〜4 字だけ
    ("林\u3000太\u3000郎", "林・試験を行った（2019）", "count", "林太", "郎"),
])
def test_split_eastern_rule(text, context, how, sur, giv):
    sp = split_eastern(text, context)
    assert (sp.how, sp.surname, sp.given) == (how, sur, giv)
    assert sp.guessed == (how in ("context", "count"))
    assert split_eastern(text, context) == sp           # 同じ入力なら同じ結果
    if how == "context":
        assert sp.hint and sur in sp.hint


GENERAL_DOTS = "小・中学校（2019）と中・高等学校（2020）。高・大接続（2019）。小・中学校学習指導要領（2017）。中・高（2019）。"
ALL_NEGATIVES = GENERAL_DOTS + "中1の生徒と小・中の差。その上，高1の生徒を対象とした。上位と中位，小学生"


@pytest.mark.parametrize("name, sur, giv", [("中\u3000川\u3000郎", "中川", "郎"), ("小\u3000林\u3000郎", "小林", "郎"),
                                            ("上\u3000田\u3000郎", "上田", "郎"), ("高\u3000橋\u3000郎", "高橋", "郎")])
def test_general_words_are_not_surname_cues(name, sur, giv):
    """「中1」「小・中」「その上，」「高1の生徒を対象」のような一般の語は、1 字の姓の手がかりにならない（字数から推定する）。"""
    sp = split_eastern(name, ALL_NEGATIVES)
    assert (sp.how, sp.surname, sp.given) == ("count", sur, giv)


@pytest.mark.parametrize("name, sur, giv", [("小\u3000野\u3000太\u3000郎", "小野", "太郎"), ("中\u3000村\u3000太\u3000郎", "中村", "太郎"),
                                            ("高\u3000橋\u3000一\u3000郎", "高橋", "一郎"), ("大\u3000野\u3000一\u3000郎", "大野", "一郎")])
@pytest.mark.parametrize("general", ["小・中学校（2019）", "中・高等学校（2020）", "高・大接続（2019）", "小・中学校学習指導要領（2017）",
                                     "中・高（2019）", "幼・小・中（2019）", "小・中・高等学校（2018）"])
def test_school_word_lists_are_not_surname_cues(name, sur, giv, general):
    """「小・中学校（2019）」のような学校種・学年の並びは、「姓・共著者（年）」の形でも手がかりにしない（1 字の姓にしない）。"""
    sp = split_eastern(name, general)
    assert (sp.how, sp.surname, sp.given) == ("count", sur, giv)


@pytest.mark.parametrize("cite, hint", [("林（2019）", "林（2019）"), ("林（2019, p.3）", "林（2019, p.3）"),
                                        ("（林，2019, p.3）", "（林，2019, p.3）"), ("林（2019 年末に", "林（2019"),
                                        ("林・試験（2019）", "林・試験（2019）"), ("（林, 2019; 試験, 2020）", "（林, 2019; 試験, 2020）")])
def test_hint_shows_up_to_closing_bracket(cite, hint):
    sp = split_eastern("林\u3000太\u3000郎", cite)
    assert sp.how == "context" and sp.hint == hint


@pytest.mark.parametrize("cite", ["林（2019）", "林ら（2019）", "林・試験（2019）", "（林，2019）"])
def test_citation_forms_are_surname_cues(cite):
    ctx = ALL_NEGATIVES + "\n" + cite
    sp = split_eastern("林\u3000太\u3000郎", ctx)
    assert (sp.how, sp.surname, sp.given) == ("context", "林", "太郎") and sp.hint in ctx


def test_split_eastern_ai_position():
    """AI の指定（split）があれば、機械の推定より優先する。指定の位置に接する空白が姓と名の間の空白。"""
    text = "試\u3000験\u3000六\u3000郎"
    sp = split_eastern(text, "試（2019）", split=3)
    assert (sp.how, sp.surname, sp.given, sp.gap) == ("ai", "試験", "六郎", (3, 4))
    sp = split_eastern("試験六郎", "", split=2)
    assert (sp.how, sp.surname, sp.given, sp.gap) == ("ai", "試験", "六郎", (2, 2))


def test_surname_hint_shows_the_text():
    """根拠の表記は、姓の前の開き括弧から、年と閉じ括弧まで（途中で切れない）。"""
    assert surname_hint("試験六郎", 2, "前の文。\nまた，試験（2020）は述べた。") == "試験（2020）"
    assert surname_hint("試験六郎", 2, "ここでは（試験，2020）が") == "（試験，2020）"
    assert surname_hint("試験六郎", 2, "試験ら (2019a)") == "試験ら (2019a)"
    assert surname_hint("試験六郎", 2, "試験・研究，2021") == "試験・研究，2021"
    assert surname_hint("試験六郎", 2, "試験（\n2020）") == ""          # 括弧の中が年で始まらない（段落をまたぐ）
    assert surname_hint("試験六郎", 2, "試験（12）と試験1，試験・，試験，") == ""
    assert surname_hint("試験六郎", 1, "試験（2020）") == ""


# ----------------------------------------------------------------------------- 変換
CASES = {
    # id: (和文の氏名, 本文, 姓と名, 分け方, 落とした空白の理由)
    "even-context": ("試\u3000験\u3000六\u3000郎", "試験（2024）にならい，著者名を確かめる。", ("試験", "六郎"), "context",
                     [NAME_INNER_REASON, NAME_GAP_REASONS["context"], NAME_INNER_REASON]),
    "even-count": ("試\u3000験\u3000六\u3000郎", "著者名を確かめる。", ("試験", "六郎"), "count",
                   [NAME_INNER_REASON, NAME_GAP_REASONS["count"], NAME_INNER_REASON]),
    "three-context": ("林\u3000太\u3000郎", "これは林（2019）による。", ("林", "太郎"), "context",
                      [NAME_GAP_REASONS["context"], NAME_INNER_REASON]),
    "longest": ("試\u3000験\u3000\u3000洋", "著者名を確かめる。", ("試験", "洋"), "longest",
                [NAME_INNER_REASON, NAME_GAP_REASONS["longest"]]),
    "single": ("試験\u3000六郎", "著者名を確かめる。", ("試験", "六郎"), "single", ["姓と名の間の空白"]),
    "edges": ("\u3000試験\u3000六郎\u3000", "著者名を確かめる。", ("試験", "六郎"), "single",
              [NAME_EDGE_REASON, "姓と名の間の空白", NAME_EDGE_REASON]),
    "unsplit": ("試験六郎", "著者名を確かめる。", ("試験六郎", None), "none", []),
    "latin": ("Taro\u3000Q\u3000SHIKEN", "著者名を確かめる。", ("Taro", "Q\u3000SHIKEN"), "latin", ["姓と名の間の空白"]),
}


@pytest.mark.parametrize("case", list(CASES))
def test_spaced_japanese_names(case, journal, meta, tmp_path):
    name, body, (sur, giv), how, reasons = CASES[case]
    path = names_doc(tmp_path / "n.docx", name, body)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    fid = res.fidelity
    assert fid.ok and fid.final_ok and res.dtd_valid, (fid.mismatches, fid.final_detail, res.dtd_errors[:3])
    assert eastern(res) == ([("surname", sur), ("given-names", giv)] if giv else [("surname", sur)])
    name_drops = [reason for s, _, reason in fid.drops if s == res.plan.authors[0].name_ja.src]
    assert name_drops == reasons
    keys = [a.key for a in actions(res)]
    report = res.report_path.read_text(encoding="utf-8")
    if how in ("single", "latin"):
        assert "name_split" not in keys
        return
    [act] = [a for a in actions(res) if a.key == "name_split"]
    assert act.level == TO_CHECK
    shown = name.strip("\u3000")
    for text in (act.top, act.checklist, act.box_detail, act.cli):
        assert f"「{shown}」" in text or text is act.checklist
    assert f"「{shown}」" in act.top and act.top in report
    if giv:
        assert f"{sur}／{giv}" in act.box_detail
        assert "出版版 PDF" in act.box_detail and "Word で" in act.box_detail
        assert {"context": "論文の中の表記", "count": "字数だけ", "longest": "いちばん長い"}[how] in act.box_detail
        # 4 章の記録にも、どう分けたか（推定かどうか）を書く
        assert any(d.category == "name" and f"姓「{sur}」・名「{giv}」" in d.message for d in res.build_notes)
    else:
        assert "分けられなかった" in act.box_detail and "空白を 1 つ" in act.box_detail
    for word in ("surname", "given-names", "drops", "split_ja", "split_eastern"):
        assert word not in act.box_detail and word not in act.top and word not in act.cli


def test_count_guess_is_worded_more_strongly(journal, meta, tmp_path):
    """字数だけの推定は、論文の中の表記からの推定より強い言い方で知らせる（誤りやすいため）。"""
    def detail(body, out):
        res = convert(names_doc(tmp_path / f"{out}.docx", "試\u3000験\u3000六\u3000郎", body), meta, journal,
                      Options(out_dir=tmp_path / out))
        return next(a for a in actions(res) if a.key == "name_split").box_detail
    weak, strong = detail("試験（2024）にならう。", "a"), detail("著者名を確かめる。", "b")
    assert "誤っていることがあります" in strong and "必ず" in strong
    assert "必ず" not in weak and "字数だけの推定は誤りやすい" not in weak


def test_estimates_are_marked_in_title_checklist_and_cli(journal, meta, tmp_path):
    """推定で分けた氏名があるときは、見出し・チェック項目・コマンドラインの文にも書く。字数だけの推定は、より強く書く。
    推定を含まない（いちばん長い空白で分けた・分けられなかった）ときは書かない。"""
    def action(name, body, out):
        res = convert(names_doc(tmp_path / f"{out}.docx", name, body), meta, journal,
                      Options(out_dir=tmp_path / out))
        return next(a for a in actions(res) if a.key == "name_split")
    ctx = action("試\u3000験\u3000六\u3000郎", "試験（2024）にならう。", "ctx")
    cnt = action("試\u3000験\u3000六\u3000郎", "著者名を確かめる。", "cnt")
    for a in (ctx, cnt):
        assert "（推定を含みます" in a.box_title and "推定で分けた氏名が 1 人" in a.checklist
        assert "推定で分けた氏名が 1 人" in a.cli and "誤っていることがあります" in a.top and "2 か所以上" in a.top
    assert "誤っていることがあります" in ctx.box_detail and "必ず" not in ctx.box_detail
    assert "誤りやすい" in cnt.box_detail and "必ず" in cnt.box_detail and "必ず" in cnt.checklist
    assert "必ず" not in ctx.checklist and "字数だけ" in cnt.cli
    assert "必ず確かめること" in cnt.cli and "必ず" not in ctx.cli
    for a in (ctx, cnt):
        for text in (a.top, a.box_detail, a.checklist, a.cli):
            assert text.count("誤っていることがあります") <= 1
            assert "字数だけ" not in text or a is cnt       # 字数だけの推定を含まないときは「字数だけ」と書かない
    assert "字数だけの推定は誤りやすい" in cnt.checklist and "字数だけの推定は誤りやすい" in cnt.cli
    for name, out in (("試\u3000験\u3000\u3000洋", "lg"), ("試験六郎", "un")):
        a = action(name, "著者名を確かめる。", out)
        for text in (a.box_title, a.checklist, a.cli, a.top):
            assert "推定" not in text


def test_same_docx_gives_same_xml(journal, meta, tmp_path):
    path = names_doc(tmp_path / "n.docx", "試\u3000験\u3000六\u3000郎", "試験（2024）にならう。")
    a = convert(path, meta, journal, Options(out_dir=tmp_path / "1"))
    b = convert(path, meta, journal, Options(out_dir=tmp_path / "2"))
    assert a.xml_path.read_bytes() == b.xml_path.read_bytes()


def test_name_context_leaves_out_author_names(journal, tmp_path):
    path = names_doc(tmp_path / "n.docx", "試\u3000験\u3000六\u3000郎", "本文。")
    _, plan, _ = _mechanical(path, journal)
    ctx = name_context(plan)
    assert "本文。" in ctx and REF in ctx and "試\u3000験" not in ctx and "SHIKEN" not in ctx


# ----------------------------------------------------------------------------- AI 補完
def _split(src, sur, giv):
    """姓と名の境目を指定する回答（tests/answers.py の names）。"""
    return answers.answer(names=[(src, sur, giv, "英文の著者名と照らした", "高")])


@pytest.mark.parametrize("sur, giv", [("試験", "六郎"), ("試\u3000験", "六\u3000郎"), ("試", "験六郎")])
def test_ai_split_name_accepts_spaced_name(sur, giv, journal, meta, tmp_path):
    """AI の split_name は、字間に空白のある氏名でも、空白を除いた文字で照合して受け付け、機械の推定より優先する。機械が推定で
    分けた氏名を AI が分けたときも、要確認 name_split に「AI が分けた」行として残し（確度つき）、4 章・7 章にも AI の指定と分かるように
    記録する。依頼文には推定で分けた氏名を載せる。"""
    path = names_doc(tmp_path / "n.docx", "試\u3000験\u3000六\u3000郎", "著者名を確かめる。")
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "m", ai_mode="manual"))
    src = res.plan.authors[0].name_ja.src
    lines = [ln for ln in res.prompt_path.read_text(encoding="utf-8").splitlines() if ln.startswith(f"- [{src}]")]
    assert len(lines) == 1 and "推定" in lines[0] and "「試\u3000験\u3000六\u3000郎」" in lines[0]
    assert "姓「試験」・名「六郎」" in lines[0] and "字数" in lines[0] and "2 か所以上" in lines[0]
    assert "name_split" in [a.key for a in actions(res)]
    resp = _split(src, sur, giv)
    res2 = convert(path, meta, journal, Options(out_dir=tmp_path / "m2", ai_mode="manual", ai_response=resp))
    fid = res2.fidelity
    assert fid.ok and fid.final_ok and res2.dtd_valid
    assert res2.ai.rejected == [] and len(res2.ai.accepted) == 1
    want_sur, want_giv = sur.replace("\u3000", ""), giv.replace("\u3000", "")
    assert eastern(res2) == [("surname", want_sur), ("given-names", want_giv)]
    [act] = [a for a in actions(res2) if a.key == "name_split"]
    assert act.level == TO_CHECK
    assert f"{want_sur}／{want_giv} に分けました。AI が境目を決めました（確度 高）。AI の指定がなければ、" in act.box_detail
    assert "字数だけから 試験／六郎 と推定していた" in act.box_detail           # AI の指定がなければ、機械はこう分けていた
    assert "推定を含みます" in act.box_title and "推定で分けた氏名が 1 人" in act.checklist and "推定で分けた氏名が 1 人" in act.cli
    for text in (act.top, act.box_detail, act.checklist, act.cli):
        assert "字数だけの推定は誤りやすい" not in text and text.count("誤っていることがあります") <= 1     # 字数だけの推定ではない
    assert any(d.category == "name" and "AI の指定" in d.message and f"姓「{want_sur}」・名「{want_giv}」" in d.message
               for d in res2.build_notes)
    assert NAME_GAP_REASONS["ai"] in [r for _, _, r in fid.drops]


def test_ai_split_name_on_unsplit_name_is_listed(journal, meta, tmp_path):
    """空白のない氏名を AI が分けたときも、「AI が分けた」行として残す（分けられなかった、という知らせは出ない）。"""
    path = names_doc(tmp_path / "n.docx", "試験六郎", "著者名を確かめる。")
    _, plan, _ = _mechanical(path, journal)
    src = plan.authors[0].name_ja.src
    resp = _split(src, "試験", "六郎")
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "m", ai_mode="manual", ai_response=resp))
    assert eastern(res) == [("surname", "試験"), ("given-names", "六郎")]
    [act] = [a for a in actions(res) if a.key == "name_split"]
    assert "AI が境目を決めました（確度 高）" in act.box_detail and "空白がなく分けられなかった" in act.box_detail
    assert "分けられなかったので" not in act.box_detail and "推定を含みます" in act.box_title


def test_ai_split_name_on_longest_gap(journal, meta, tmp_path):
    """いちばん長い空白が 1 つで機械が分けた氏名: AI が同じ位置を指定しただけなら、今までの「いちばん長い空白で分けた」の知らせのまま。
    違う位置を指定したら、「AI が分けた」行にする。"""
    path = names_doc(tmp_path / "n.docx", "試\u3000験\u3000\u3000洋", "著者名を確かめる。")
    _, plan, _ = _mechanical(path, journal)
    src = plan.authors[0].name_ja.src
    same = convert(path, meta, journal, Options(out_dir=tmp_path / "a", ai_mode="manual",
                                                ai_response=_split(src, "試験", "洋")))
    [act] = [a for a in actions(same) if a.key == "name_split"]
    assert "いちばん長い" in act.box_detail and "AI が境目を決めました" not in act.box_detail and "推定を含みます" not in act.box_title
    assert len(same.ai.accepted) == 1
    diff = convert(path, meta, journal, Options(out_dir=tmp_path / "b", ai_mode="manual",
                                                ai_response=_split(src, "試", "験洋")))
    [act] = [a for a in actions(diff) if a.key == "name_split"]
    assert eastern(diff) == [("surname", "試"), ("given-names", "験洋")]
    assert "試／験洋 に分けました。AI が境目を決めました" in act.box_detail and "いちばん長い空白で 試験／洋 に分けていた" in act.box_detail


def test_ai_split_name_on_single_space_name_is_unchanged(journal, meta, tmp_path):
    """空白が 1 か所の氏名への split_name の扱いは変えない（C043 は別に直す）: 空白を除いた照合はしない。"""
    path = names_doc(tmp_path / "n.docx", "試験\u3000六郎", "著者名を確かめる。")
    _, plan, _ = _mechanical(path, journal)
    src = plan.authors[0].name_ja.src
    resp = _split(src, "試験", "六郎")
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "m", ai_mode="manual", ai_response=resp))
    assert res.ai.accepted == [] and len(res.ai.rejected) == 1
    assert eastern(res) == [("surname", "試験"), ("given-names", "六郎")]


def test_ai_split_name_rejects_other_letters(journal, meta, tmp_path):
    path = names_doc(tmp_path / "n.docx", "試\u3000験\u3000六\u3000郎", "著者名を確かめる。")
    _, plan, _ = _mechanical(path, journal)
    src = plan.authors[0].name_ja.src
    resp = _split(src, "試験", "七郎")
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "m", ai_mode="manual", ai_response=resp))
    assert res.ai.accepted == [] and len(res.ai.rejected) == 1
    assert eastern(res) == [("surname", "試験"), ("given-names", "六郎")]       # 機械の推定のまま
    assert "name_split" in [a.key for a in actions(res)]


# ----------------------------------------------------------------------------- ルート2
def test_route2_keeps_name_shape(journal, meta, tmp_path, monkeypatch):
    """ルート2: 補った docx でも氏名の分け方（pdfdocx._name_shape）が変わらず、補完の確かめ（verify_supplement）が誤って
    不合格にしない。本文の「(2024)」を PDF の「（2024）」に直しても、推定の根拠（論文の中の表記）は同じに決まる。"""
    from jasme_jats.pdfdocx import _name_shape, _people
    path = names_doc(tmp_path / "n.docx", "試\u3000験\u3000六\u3000郎", "試験(2024)にならい，著者名を確かめる。")
    _, plan, _ = _mechanical(path, journal)
    texts = [p.plain() for p in plan.paras.values() if plan.region.get(p.src) or p.src == plan.authors[0].name_ja.src]
    pages = ["\n".join(t.replace("試験(2024)", "試験（2024）") for t in texts if t.strip())]
    monkeypatch.setattr(pdfmatch, "extract_pages", lambda p: pages)
    (tmp_path / "dummy.pdf").write_bytes(b"%PDF-1.4\n")
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "pdf", pdf_path=tmp_path / "dummy.pdf", route="pdf"))
    fid = res.fidelity
    assert fid.ok and fid.final_ok and res.dtd_valid
    assert res.supplement is not None and res.supplement.ok, res.supplement
    assert any(f.applied for f in res.docx_fix.fixes)
    assert eastern(res) == [("surname", "試験"), ("given-names", "六郎")]
    _, fixed, _ = _mechanical(res.docx_fix.path, journal)
    assert _people(plan)[2] == _people(fixed)[2]
    src = plan.authors[0].name_ja.src
    assert _name_shape(plan.paras[src].plain(), "eastern", None) == _people(plan)[2][src]


def test_spaces_around_english_name_are_dropped(journal, meta, tmp_path):
    """英文の氏名の前後の空白も姓・名に入れずに落とす（C072）。名の語の間の空白（Rokuro Taro）は残す。"""
    path = names_doc(tmp_path / "n.docx", "試験　六郎", "著者名を確かめる。", en_name=" Rokuro Taro SHIKEN　")
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    fid = res.fidelity
    assert fid.ok and fid.final_ok and res.dtd_valid
    [nm] = [n for n in load(res).iter("name") if n.get("name-style") == "western"]
    assert [(x.tag, x.text) for x in nm] == [("surname", "SHIKEN"), ("given-names", "Rokuro Taro")]
    src = res.plan.authors[0].name_en.src
    assert [r for s, _, r in fid.drops if s == src] == [NAME_EDGE_REASON, "姓と名の間の空白", NAME_EDGE_REASON]


def test_ai_request_tells_longest_from_estimate(journal, tmp_path):
    """AI の依頼文は、いちばん長い空白で決めた氏名を「推定した氏名」とは書かず、決め方を書き分ける。"""
    from jasme_jats.ai_assist import build_request
    from jasme_jats.builder import split_eastern
    _, plan, linker = _mechanical(names_doc(tmp_path / "r.docx", "試\u3000験\u3000六\u3000郎", "本文。"), journal)
    lg = split_eastern("試\u3000験\u3000\u3000洋")
    ct = split_eastern("試\u3000験\u3000六\u3000郎", "試験（2024）")
    req, _ = build_request(plan, linker, (), (), [("d11", lg), ("d12", ct)])
    [l1] = [x for x in req.splitlines() if x.startswith("- [d11]")]
    [l2] = [x for x in req.splitlines() if x.startswith("- [d12]")]
    assert "いちばん長い空白で決めた氏名" in l1 and "推定した氏名" not in l1
    assert "姓と名の境目を推定した氏名" in l2


def test_name_split_pending_has_no_ai_advice(journal, meta, tmp_path):
    """修正計画 W8 の手順 7: 手動モードで回答待ちのときも、著者名の知らせに「AI の回答を反映すると…」を書かない（AI を勧める文は
    推奨の手順 ai_finish の 1 か所）。文は AI を使わないときと同じ。"""
    path = names_doc(tmp_path / "n.docx", "試　験　六　郎", "著者名を確かめる。")
    acts = []
    for out, mode in (("none", "none"), ("pend", "manual")):
        res = convert(path, meta, journal, Options(out_dir=tmp_path / out, ai_mode=mode))
        acts.append(next(a for a in actions(res) if a.key == "name_split"))
    for a in acts:
        for t in (a.top, a.box_detail, a.cli, a.checklist):
            assert "AI" not in t, t
    assert (acts[0].top, acts[0].box_detail, acts[0].cli) == (acts[1].top, acts[1].box_detail, acts[1].cli)
