"""図・表のキャプションのスタイルの取り違え（C034。要確認 style_check の caption_kind）。

番号の頭（図・Figure・Fig. か、表・Table）と段落のスタイル（図キャプション・表キャプション）の食い違いを、本体の有無に関係なく挙げる。
XML・組み立ては変えない（知らせるだけ。直すのは Word のスタイル）。docx は make_fixtures の部品で作る（内容は架空）。
"""
import make_fixtures as mf

from jasme_jats import report
from jasme_jats.pipeline import Options, convert
from jasme_jats.report import actions

S = mf.S


def _tb(first="架空の項目"):
    return mf.table([[mf.cell(first), mf.cell("値")], [mf.cell("甲"), mf.cell("1")]])


def _run(tmp_path, journal, meta, parts, name="k"):
    path = tmp_path / f"{name}.docx"
    head = [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "架空の本文である。試験（2024）による。")]
    mf.make_article(path, "架空の題目", lambda b: head + parts(b))
    res = convert(path, meta, journal, Options(out_dir=tmp_path / f"out_{name}", ai_mode="none"))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid, (res.fidelity.missing, res.dtd_errors[:3])
    return res


def _kinds(res):
    return [(x.kind, res.plan.paras[x.src].plain()) for x in res.plan.style_suspects if x.kind == "caption_kind"]


def _act(res, key):
    return next((a for a in actions(res) if a.key == key), None)


def test_table_caption_with_figure_caption_style(tmp_path, journal, meta):
    """「表1 …」に図キャプションのスタイルを付けた段落（本体は表）は caption_kind で挙げる。XML の図・表の組は今のまま。"""
    res = _run(tmp_path, journal, meta,
               lambda b: [mf.para(S["fig_cap"], "表1　架空の表"), _tb(), mf.para(S["body"], "後ろの本文。")])
    assert _kinds(res) == [("caption_kind", "表1　架空の表")]
    act = _act(res, "style_check")
    assert act is not None and "番号の頭が「表」です" in act.box_detail and "表キャプションのスタイルにする" in act.box_detail
    assert _act(res, "ai_finish") is None                  # 直し方が決まっているので、AI の提案を待たない
    assert "caption_kind" in report.STYLE_NO_AI_KINDS


def test_figure_caption_with_table_caption_style_has_body(tmp_path, journal, meta):
    """本体のある表に「図1 …」で始まる表キャプションのスタイルを付けた形も挙げる。"""
    res = _run(tmp_path, journal, meta,
               lambda b: [mf.para(S["tab_cap"], "図1　架空の図"), _tb(), mf.para(S["body"], "後ろの本文。")])
    assert _kinds(res) == [("caption_kind", "図1　架空の図")]
    assert not res.bodyless_tables
    assert "番号の頭が「図」です" in _act(res, "style_check").box_detail


def test_english_heads_and_bodyless_caption_style(tmp_path, journal, meta):
    """Table・Fig. の頭も同じ。本体のない形（caption_style）は両方の知らせが出て、table_body の行は style_check を指す。"""
    res = _run(tmp_path, journal, meta,
               lambda b: [mf.para(S["fig_cap"], "Table 1  A fictional table"), _tb(), mf.para(S["body"], "本文。"),
                          mf.para(S["tab_cap"], "Fig. 2  A fictional figure"), mf.para(S["body"], "間の本文。"),
                          mf.para(S["sec2"], "（１）次の節"), _tb("別の項目"), mf.para(S["body"], "後ろの本文。")])
    assert [t for _, t in _kinds(res)] == ["Table 1  A fictional table", "Fig. 2  A fictional figure"]
    (bl,) = res.bodyless_tables
    assert bl.why == "caption_style"
    assert "スタイルを確かめてください" in report.table_body_why(bl)


def test_correct_styles_and_confusing_heads_do_not_report(tmp_path, journal, meta):
    """正しい原稿では出ない。「図表1」のような紛らわしい頭・番号のない「表現」は、取り違えとしない。"""
    res = _run(tmp_path, journal, meta,
               lambda b: [mf.para(S["tab_cap"], "表1　架空の表"), _tb(), mf.para(S["body"], "本文。"),
                          mf.para(S["tab_cap"], "図表2　架空の表"), _tb("別の項目"), mf.para(S["body"], "後ろの本文。"),
                          mf.para(S["tab_cap"], "表現の一覧"), _tb("さらに別の項目"), mf.para(S["body"], "最後の本文。")])
    assert _kinds(res) == []
