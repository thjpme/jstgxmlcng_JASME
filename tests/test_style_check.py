"""要確認 style_check（スタイルを確かめる段落）と ai_boundary（AI の回答で直した注の区切り・資料の始まり）。修正計画 W8 の手順 8。

機械の検出（plan.style_suspects。検出そのものは修正計画の単位 D が足す）は、ここでは変換の後の plan に手で入れて確かめる。
AI の提案（AIOutcome.style_fixes）は、今の形の回答の set_role（区切りの 5 つ以外）から作られる（W8 の手順 5）。実際の API は呼ばない。
"""
import answers
import make_fixtures as mf
from conftest import NOTES
from jasme_jats import report
from jasme_jats.ai_assist import StyleFix
from jasme_jats.article import StyleSuspect
from jasme_jats.pipeline import Options, _mechanical, convert
from jasme_jats.report import STEP, TO_CHECK, actions, blocking

S = mf.S


def _manual(path, resp, meta, journal, out):
    """回答 resp（tests/answers.py で作った JSON の文字）を手動モードで貼り戻して変換する。"""
    return convert(path, meta, journal, Options(out_dir=out, ai_mode="manual", ai_response=resp))


def _docx(tmp_path, n=3):
    """図形のない小さな原稿（本文の段落 n 個。位置を聞く図形もテキストボックスもない）。"""
    path = tmp_path / "style.docx"
    mf.make_article(path, "スタイルの確かめの検証用文書",
                    lambda b: [mf.para(S["sec1"], "１．はじめに")]
                    + [mf.para(S["body"], f"架空の本文の段落 {i} である。") for i in range(1, n + 1)])
    return path


def _src(res, text):
    return next(s for s, p in res.plan.paras.items() if p.plain() == text)


def _act(res, key):
    return next((a for a in actions(res) if a.key == key), None)


def test_style_check_from_machine_suspects_without_ai(journal, meta, tmp_path):
    """AI を使っていなくても、機械が挙げた段落（style_suspects）で要確認 style_check が出る。行は機械の見立てと、種類ごとの一般の
    直し方だけ。推奨の手順 ai_finish も（出す条件 3 で）出て、AI がスタイルの直し方を提案すると書く。どちらも終了コード 0。"""
    res = convert(_docx(tmp_path), meta, journal, Options(out_dir=tmp_path / "out"))
    assert _act(res, "style_check") is None and _act(res, "ai_finish") is None       # 検出がなければ出さない
    s1, s2 = _src(res, "架空の本文の段落 1 である。"), _src(res, "架空の本文の段落 2 である。")
    res.plan.style_suspects = [StyleSuspect("quote_like", s2), StyleSuspect("heading_level", s1, "項見出しのスタイルですが、番号の形は節です")]
    act = _act(res, "style_check")
    assert act.level == TO_CHECK and act.box_title == "スタイルを確かめてください（2 か所）（要確認）"
    lines = act.box_detail.split("\n")[1:]
    assert [line.split("（")[0] for line in lines] == [f"・{s1}", f"・{s2}"]          # 段落の順
    assert lines[0].endswith("項見出しのスタイルですが、番号の形は節です。直し方: 番号の形に合う階層の見出しのスタイルにする。")
    assert lines[1].endswith("本文のスタイルですが、引用の形をしています。直し方: 引用なら、ブロック引用のスタイルにする。")
    assert "AI の提案:" not in act.box_detail and "XML には反映していません" in act.box_detail
    assert s1 in act.top and s1 in act.cli and "2 か所" in act.checklist
    fin = _act(res, "ai_finish")
    assert fin.level == STEP and not fin.required and fin.box_title == "AI にスタイルの直し方を提案させる（推奨）"
    assert "スタイルを確かめる段落 2 か所について、AI が Word での直し方を提案します。" in fin.box_detail
    assert "AI がスタイルの直し方を提案します" in fin.cli and "スタイルを確かめる段落が 2 か所ある（2 章）" in fin.checklist
    assert blocking(actions(res)) == [] and not res.needs_action
    # 2 章の表にも載る（AI を使っていなくても）
    ch2 = report.render(res).split("## 2.")[1].split("## 3.")[0]
    assert "### スタイルの提案（XML には反映していない）" in ch2 and f"| {s1} |" in ch2


def test_ai_proposal_joins_machine_line_and_keep_does_not_remove_it(journal, meta, tmp_path):
    """AI の提案は機械が挙げた段落の同じ行に添う。AI の「このまま」でも、機械が挙げた行は消さず、見立てを添える。"""
    res = convert(_docx(tmp_path), meta, journal, Options(out_dir=tmp_path / "out"))
    s1, s2 = _src(res, "架空の本文の段落 1 である。"), _src(res, "架空の本文の段落 2 である。")
    res.plan.style_suspects = [StyleSuspect("quote_like", s1), StyleSuspect("heading_guess", s2)]
    res.ai.style_fixes = [StyleFix(s1, "quote", "ブロック引用", "Word で段落のスタイルを「ブロック引用」にする", "末尾にページがある", "中"),
                          StyleFix(s2, "sec2", "", "", "本文の文の形", "高", verdict="このまま")]
    act = _act(res, "style_check")
    lines = act.box_detail.split("\n")[1:]
    assert len(lines) == 2
    assert lines[0].endswith("AI の提案: Word で段落のスタイルを「ブロック引用」にする（確度 中。末尾にページがある）。")
    assert "直し方:" not in lines[0]
    assert lines[1].endswith("AI の見立て: このままでよい（本文の文の形）。")
    assert act.box_title.startswith("スタイルを確かめてください（2 か所）")


def test_ai_only_proposals_show_high_and_middle_only(journal, meta, tmp_path):
    """AI だけが見つけた提案（今の形の回答の set_role）は、確度 高・中だけが style_check に載り、低は 2 章だけ。XML は変えない。"""
    path = _docx(tmp_path)
    _, plan, _ = _mechanical(path, journal)
    by_text = {p.plain(): s for s, p in plan.paras.items()}
    s1, s2, s3 = (by_text[f"架空の本文の段落 {i} である。"] for i in (1, 2, 3))
    none = convert(path, meta, journal, Options(out_dir=tmp_path / "none"))
    res = _manual(path, answers.answer(style_fixes=[(s1, "sec2", "番号の形", "高"), (s2, "quote", "試験", "中"),
                                                    (s3, "sec3", "試験", "低")]), meta, journal, tmp_path / "out")
    assert res.xml_path.read_bytes() == none.xml_path.read_bytes()
    act = _act(res, "style_check")
    assert act.level == TO_CHECK and act.box_title == "AI がスタイルの誤りを見つけました（2 か所）。確かめてください（要確認）"
    lines = act.box_detail.split("\n")[1:]
    assert len(lines) == 2 and s1 in lines[0] and s2 in lines[1] and s3 not in act.box_detail
    assert lines[0].endswith("AI の提案: Word で段落のスタイルを「節見出し」にする（確度 高。番号の形）。")
    # 確度 低の提案は 2 章の表だけ
    ch2 = res.report_path.read_text(encoding="utf-8").split("## 2.")[1].split("## 3.")[0]
    table = ch2.split("### スタイルの提案（XML には反映していない）")[1]
    assert f"| {s3} |" in table and "| 低 |" in table
    assert "Word のスタイルで直せる段落の役割は、AI の提案を下の「スタイルの提案」に載せるだけで、XML には反映していません" in ch2.replace("見出し・引用など、", "")
    assert not res.needs_action
    # AI の判断一覧の別ファイルにも載る
    assert "## スタイルの提案（XML には反映していない）" in report.render_ai_only(res)


def test_style_check_shows_ten_lines(journal, meta, tmp_path):
    """11 か所あるときは 10 行と「ほか 1 か所（2 章）」。"""
    res = convert(_docx(tmp_path, n=11), meta, journal, Options(out_dir=tmp_path / "out"))
    srcs = [_src(res, f"架空の本文の段落 {i} である。") for i in range(1, 12)]
    res.plan.style_suspects = [StyleSuspect("quote_like", s) for s in srcs]
    act = _act(res, "style_check")
    lines = act.box_detail.split("\n")[1:]
    assert len(lines) == 11 and lines[-1] == "・ほか 1 か所（2 章）"
    assert srcs[9] in lines[9] and srcs[10] not in act.box_detail
    assert act.top.endswith("> - ほか 1 か所（2 章）") and "（11 か所）" in act.box_title


def test_abstract_missing_paragraphs_are_not_in_style_check(journal, meta, tmp_path):
    """英文要旨が見つからない要対応（abstract_missing）の対象の段落は style_check に載せず、AI の英文要旨の提案は abstract_missing に
    AI の見立ての 1 行として添える。"""
    from test_structure import _convert_no_abstract
    res = _convert_no_abstract(journal, meta, tmp_path)
    act = _act(res, "abstract_missing")
    assert act is not None and "AI" not in act.box_detail
    src = report.abstract_missing_srcs(res.plan)[0]
    res.plan.style_suspects = [StyleSuspect("heading_guess", src)]
    res.ai.style_fixes = [StyleFix(src, "abstract", "英文要旨", "Word で段落のスタイルを「英文要旨」にする", "英文の段落", "高")]
    assert _act(res, "style_check") is None
    act = _act(res, "abstract_missing")
    head = report._head(res.plan.paras[src], 15)
    line = f"AI の見立て: 「{head}」の段落から英文要旨（確度 高）。"
    assert line in act.box_detail and line in act.top and line in act.cli


def test_ai_boundary_for_notes(journal, meta, tmp_path):
    """AI の回答で注の区切りを直すと、要確認 ai_boundary が出て、直した段落が 1 行ずつ載る（終了コード 0）。2 章に表がある。"""
    _, plan, _ = _mechanical(NOTES, journal)
    start = next(s for s, p in plan.paras.items() if p.plain().startswith("※4"))
    res = _manual(NOTES, answers.answer(boundaries=[(start, "注の始まり", "番号で始まる", "中")]), meta, journal, tmp_path / "out")
    assert [(b.src, b.kind) for b in res.ai.boundaries] == [(start, "注の始まり")]
    act = _act(res, "ai_boundary")
    assert act.level == TO_CHECK and act.box_title == "AI の回答で、注の区切りを直しました（1 か所）。確かめてください（要確認）"
    head = report._head(res.plan.paras[start], 15)
    line = f"注の一覧の「{head}」の段落を、新しい注の始まりにしました（AI の根拠: 番号で始まる。確度 中）"
    assert act.box_detail.startswith("・" + line + "\n") and line in act.top and line in act.cli
    assert "AI の回答を入れずに変換し直してください" in act.box_detail and "資料" not in act.box_title
    assert not res.needs_action and _act(res, "style_check") is None
    ch2 = res.report_path.read_text(encoding="utf-8").split("## 2.")[1].split("## 3.")[0]
    assert "### 注の区切り・資料の始まり（AI の回答で直した）" in ch2 and f"| {start} |" in ch2
    # 直していなければ出さない
    none = _manual(NOTES, answers.answer(), meta, journal, tmp_path / "none")
    assert _act(none, "ai_boundary") is None


def test_ai_boundary_for_appendix(journal, meta, tmp_path):
    """資料の始まりを直したときは、見出しと行と確かめる文を資料のものにする。"""
    path = tmp_path / "app.docx"
    mf.make_article(path, "資料の見出しの検証用文書", lambda b: [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "本文。")],
                    abstract=["Small article abstract.", "架空の授業の記録", "架空の記録の本文である。"])
    _, plan, _ = _mechanical(path, journal)
    src = next(s for s, p in plan.paras.items() if p.plain() == "架空の授業の記録")
    res = _manual(path, answers.answer(boundaries=[(src, "資料の見出し")]), meta, journal, tmp_path / "out")
    act = _act(res, "ai_boundary")
    assert act.box_title == "AI の回答で、資料の始まりを直しました（1 か所）。確かめてください（要確認）"
    assert "英文の部分の「架空の授業の記録」の段落から後ろを、資料にしました（AI の根拠: 試験。確度 高）" in act.box_detail
    assert "英文要旨の終わりと資料の始まりを、出版版 PDF と見比べてください。" in act.box_detail
    assert "注の" not in act.box_detail and not res.needs_action
