"""「手順」の型（report.STEP。必須と推奨の別・済んだか・失敗したか）。要対応・要確認とは別の区分で、出す場所を決める仕組みは
report.actions() の 1 か所のまま。止める知らせは report.blocking() が決める。"""
import re

import answers
from conftest import FULL, META_EXAMPLE

from jasme_jats import colab, report
from jasme_jats.pipeline import Options, convert
from jasme_jats.report import NEEDS_ACTION, STEP, TO_CHECK, Action, blocking, checklist_order


def make(level, key, **kw):
    return Action(level, key, box_title=kw.pop("box_title", key), **kw)


def test_action_defaults():
    a = Action(STEP, "x")
    assert (a.required, a.done, a.failed, a.progress) == (True, False, False, "")
    assert a.top == "" and a.checklist == "" and a.cli == ""
    assert STEP == "手順" and STEP not in (NEEDS_ACTION, TO_CHECK)


def test_blocking_is_needs_action_and_remaining_required_steps():
    acts = [make(NEEDS_ACTION, "n"), make(TO_CHECK, "c"),
            make(STEP, "req"), make(STEP, "done", done=True),
            make(STEP, "rec", required=False), make(STEP, "failed", required=False, failed=True)]
    assert [a.key for a in blocking(acts)] == ["n", "req"]
    assert blocking([make(STEP, "rec", required=False)]) == []
    assert blocking([]) == []


def test_recommended_step_alone_is_exit_code_0(journal, meta, tmp_path, capsys):
    """手動モードで回答を入れていない変換（推奨の手順だけが残る）は、needs_action が偽・終了コード 0。ダウンロードも止めない。"""
    from jasme_jats.cli import main
    from conftest import fill_images, one_color_png
    from conftest import FLOAT
    res = convert(FLOAT, meta, journal, Options(out_dir=tmp_path / "a", ai_mode="manual"))
    keys = fill_images(res)                     # 図の画像の手順（必須）を済ませる
    acts = report.actions(res)
    ai = next(a for a in acts if a.key == "ai_finish")
    assert ai.level == STEP and ai.required is False and ai.progress.startswith("回答待ち・残り ")
    assert ai.top == "" and "AI の回答をまだ反映していない" in ai.checklist
    assert not any(a.level == NEEDS_ACTION for a in acts) and blocking(acts) == [] and not res.needs_action
    pics = tmp_path / "pics"
    pics.mkdir()
    for key in keys:
        (pics / f"{key}.png").write_bytes(one_color_png())
    assert main([str(FLOAT), "--meta", str(META_EXAMPLE), "--out", str(tmp_path / "b"), "--ai", "manual",
                 "--images", str(pics)]) == 0
    assert capsys.readouterr().err.count("手順（推奨）: ") == 1


def test_step_box_is_blue_and_failed_is_red_heading():
    ok = colab.step_box("題", "本文")
    assert "手順: 題" in ok and "#2563eb" in ok and "#eff6ff" in ok
    failed = colab.step_box("題", "本文", failed=True)
    assert "#b91c1c" in failed and "#b91c1c" not in ok
    rec = colab.step_box("題", "本文", required=False)
    assert "手順（推奨）: 題" in rec
    for red in ("#dc2626", "#d97706"):         # 要対応の赤・要確認の黄は使わない
        assert red not in ok


def test_box_shows_step_blue_and_hides_done_step():
    pending = Action(STEP, "s", box_title="題", box_detail="本文")
    assert "#2563eb" in colab._box(pending)
    assert colab._box(Action(STEP, "s", box_title="題", done=True)) == ""             # 済んだ手順は、本文がなければ枠を出さない
    assert "#2563eb" in colab._box(Action(STEP, "s", box_title="題", box_detail="本文", done=True))   # 本文があれば出す（持ち越しの確かめ）
    assert "#dc2626" in colab._box(Action(NEEDS_ACTION, "n", box_title="題"))
    assert "#d97706" in colab._box(Action(TO_CHECK, "c", box_title="題"))


def test_checklist_order_steps_then_needs_action_then_to_check():
    acts = [make(TO_CHECK, "c1"), make(NEEDS_ACTION, "n1"), make(STEP, "rec", required=False),
            make(TO_CHECK, "c2"), make(STEP, "req"), make(NEEDS_ACTION, "n2")]
    assert [a.key for a in checklist_order(acts)] == ["req", "rec", "n1", "n2", "c1", "c2"]
    # PDF の項目は、それぞれの区分の中で先
    acts = [make(TO_CHECK, "c1"), make(TO_CHECK, "pdf_diff")]
    assert [a.key for a in checklist_order(acts)] == ["pdf_diff", "c1"]


def test_checklist_in_report_puts_step_before_others(journal, meta, tmp_path):
    from conftest import OUTSIDE
    res = convert(OUTSIDE, meta, journal, Options(out_dir=tmp_path, ai_mode="manual"))
    chapter14 = res.report_path.read_text(encoding="utf-8").split("## 14.")[1]
    ai = next(a for a in report.actions(res) if a.key == "ai_finish")
    other = next(a for a in report.actions(res) if a.key == "float_end")        # 要確認
    assert chapter14.index(ai.checklist) < chapter14.index(other.checklist)
    # 冒頭の囲みには手順を出さない
    assert "AI の回答をまだ反映していない" not in report_head(res)


def report_head(res):
    return res.report_path.read_text(encoding="utf-8").split("## 2.")[0]


def test_step_marks_are_replaced_on_three_screens(journal, meta, tmp_path):
    from conftest import FLOAT
    res = convert(FLOAT, meta, journal, Options(out_dir=tmp_path, ai_mode="manual"))
    ai = next(a for a in report.actions(res) if a.key == "ai_finish")
    assert "\x00" in ai.box_detail                       # 目印を使っている
    note = colab.step_text(ai.box_detail, "notebook")
    page = colab.step_text(ai.box_detail, "app")
    cli = colab.step_text(ai.box_detail, "cli")
    assert re.search(r"手順 ?\d", note) and not re.search(r"手順 ?\d", page + cli)
    assert "\x00" not in note + page + cli
    assert note != page != cli


def test_result_boxes_blocking_only(journal, meta, tmp_path):
    from conftest import FLOAT, fill_images
    res = convert(FLOAT, meta, journal, Options(out_dir=tmp_path, ai_mode="manual"))
    assert "図の画像を入れてください" in colab.result_boxes(res, blocking=True)     # 必須の手順は止める
    fill_images(res)
    assert colab.result_boxes(res, blocking=True) == ""                           # 推奨の手順（ai_finish）は止めない
    assert "AI で図・表の位置を合わせる（強く推奨。残り " in colab.result_boxes(res)
    keys = {a.key for a in report.actions(res)} - {"ai_finish", "images"}
    assert colab.result_boxes(res, skip=("ai_finish", "images") + tuple(keys)) == ""


# ---------------------------------------------------------------------------- AI の仕上げ（推奨の手順 ai_finish）と float_end（修正計画 W8 の手順 1）
def test_ai_finish_is_recommended_and_does_not_block(journal, meta, tmp_path):
    """AI を使わずに位置を決められない図形のある原稿（sample_float）を変換すると、推奨の手順 ai_finish（未実行）が出る。図の画像を
    入れれば needs_action は偽（推奨の手順は止めない）。レポートの冒頭の囲みには出さず、14 章に「（推奨）」の行が出る。"""
    from conftest import FLOAT, fill_images
    res = convert(FLOAT, meta, journal, Options(out_dir=tmp_path))
    fill_images(res)
    fin = next(a for a in report.actions(res) if a.key == "ai_finish")
    assert (fin.level, fin.required, fin.done, fin.failed) == (STEP, False, False, False)
    assert not res.needs_action and blocking(report.actions(res)) == []
    text = res.report_path.read_text(encoding="utf-8")
    head, ch14 = text.split("## 1.")[0] + text.split("## 1.")[1].split("## 2.")[0], text.split("## 14.")[1]
    assert "AI で図・表の位置を合わせる" not in head
    assert "- [ ] （推奨）AI で図・表の位置を合わせる: " in ch14 and "ノートブックは手順 4〜6" in ch14


def test_no_ai_finish_without_floats_to_ask(journal, meta, tmp_path):
    """位置を聞く図形のない原稿（sample_full）では、AI を使わなくても、手動の回答待ちでも、ai_finish は出ない（W8 の手順 1。
    回答待ちは今の ai_pending のまま）。"""
    for mode in ("none", "manual"):
        res = convert(FULL, meta, journal, Options(out_dir=tmp_path / mode, ai_mode=mode))
        assert res.plan.asked_floats == []
        assert "ai_finish" not in [a.key for a in report.actions(res)]


def test_float_end_lists_floats_at_body_end(journal, meta, tmp_path):
    """sample_outside: 引用文献・注の段落に結び付いた図形 2 つは本文の最後に置き、要確認 float_end 1 つに、図形ごとに 1 行で出す
    （資料の図なら APP_MOVE_HOW。本文の図なら図形を本文の段落の近くに移す）。AI の仕上げ ai_finish にも数える（PDF で本文の段落を
    答えれば、そこに置ける）。"""
    from conftest import OUTSIDE
    res = convert(OUTSIDE, meta, journal, Options(out_dir=tmp_path))
    acts = [a for a in report.actions(res) if a.key == "float_end"]
    assert len(acts) == 1 and acts[0].level == TO_CHECK
    a = acts[0]
    assert a.box_title == "本文の最後に置いた図・表が 2 個あります（要確認）"
    assert "資料の図なら、" + report.APP_MOVE_HOW in a.box_detail
    lines = [x for x in a.box_detail.split("\n") if x.startswith("・")]
    assert len(lines) == 2 and lines[0].endswith("— 引用文献の段落に結び付いています") and lines[1].endswith("— 注の段落に結び付いています")
    assert a.cli.startswith("要確認: 本文の最後に置いた図・表が 2 個あります（レポートの冒頭と 3 章）。")
    assert a.top.startswith("> **要確認: 本文の最後に置いた図・表が 2 個あります（3 章）。**")
    assert next(x for x in report.actions(res) if x.key == "ai_finish").progress == "未実行・残り 2 個"
    # 引用文献などの後ろの資料の要確認（app_after_refs）が出る原稿では出さない（直し方が同じなので重ねない）
    res.plan.app_after_refs = [res.plan.refs[0].para.src]
    keys = [x.key for x in report.actions(res)]
    assert "app_after_refs" in keys and "float_end" not in keys


# ---------------------------------------------------------------------------- AI による仕上げの 5 つの状態（修正計画 W8 の手順 3）
def _finish(res):
    return next((a for a in report.actions(res) if a.key == "ai_finish"), None)


def test_ai_finish_has_five_states(journal, meta, tmp_path):
    """推奨の手順 ai_finish は、状態（report.ai_state）ごとに見出し・本文・done・failed・progress を変える（4.3 の表）。
    要対応の ai_error・partial と、手順 ai_pending はなくした（ai_finish にまとめた）。"""
    import json
    from conftest import FLOAT
    from test_ai import FLOAT_RESPONSE, cut_cases
    runs = {
        "未実行": Options(out_dir=tmp_path / "n"),
        "回答待ち": Options(out_dir=tmp_path / "w", ai_mode="manual"),
        "済み": Options(out_dir=tmp_path / "d", ai_mode="manual", ai_response=json.dumps(FLOAT_RESPONSE, ensure_ascii=False)),
        "一部": Options(out_dir=tmp_path / "p", ai_mode="manual", ai_response=answers.answer()),
        "失敗": Options(out_dir=tmp_path / "f", ai_mode="manual", ai_response="これは JSON ではない"),
        "途中": Options(out_dir=tmp_path / "c", ai_mode="manual", ai_response=cut_cases()["c"]),
    }
    got = {}
    for name, opts in runs.items():
        res = convert(FLOAT, meta, journal, opts)
        keys = {a.key for a in report.actions(res)}
        assert not keys & {"ai_error", "partial", "ai_pending", "forced"}, name
        got[name] = (res, _finish(res))
        assert got[name][1].level == STEP and got[name][1].required is False and got[name][1].top == "", name
    res, fin = got["未実行"]
    assert report.ai_state(res) == "未実行" and (fin.done, fin.failed, fin.progress) == (False, False, "未実行・残り 3 個")
    assert fin.box_title == "AI で図・表の位置を合わせる（強く推奨。残り 3 個）"
    assert "AI を使うと、図・表の位置を合わせられます。" in fin.box_detail and report.step("ai_choose") in fin.box_detail
    res, fin = got["回答待ち"]
    assert report.ai_state(res) == "回答待ち" and (fin.done, fin.failed, fin.progress) == (False, False, "回答待ち・残り 3 個")
    assert report.step("prompt") in fin.box_detail and report.step("paste") in fin.box_detail
    assert "このまま登載することもできます。" in fin.box_detail and "--ai manual --ai-response 回答のファイル" in fin.cli
    res, fin = got["済み"]
    assert report.ai_state(res) == "済み" and report.ai_done(res)
    assert (fin.done, fin.failed, fin.progress, fin.cli) == (True, False, "済み", "")
    assert fin.checklist.startswith("- [x] AI の回答で図・表 ") and colab._box(fin) == ""       # 済んだ手順は枠を出さない
    assert "- [x] AI の回答で図・表 " in res.report_path.read_text(encoding="utf-8").split("## 14.")[1]
    res, fin = got["一部"]
    assert report.ai_state(res) == "一部" and (fin.done, fin.failed, fin.progress) == (False, False, "一部・残り 3 個")
    assert "AI の回答で位置が決まったのは 3 個のうち 0 個です。" in fin.box_detail and report.step("repaste") in fin.box_detail
    res, fin = got["失敗"]
    assert report.ai_state(res) == "失敗" and (fin.done, fin.failed, fin.progress) == (False, True, "失敗")
    assert fin.box_title == "AI の回答を反映できませんでした"
    assert fin.box_detail.startswith("貼り付けられた回答を JSON として読めませんでした: ")
    assert "変換の結果は、AI を使わないときと同じです。回答のコードブロックの中身だけを" in fin.box_detail
    assert "#b91c1c" in colab._box(fin)                         # 見出しが赤字
    res, fin = got["途中"]
    assert report.ai_state(res) == "一部" and fin.progress == "一部・残り 2 個"
    assert "最後まで書かれていた 1 件だけを読み取って反映しました" in fin.box_detail and "続きだけを貼り付けても読めません" in fin.box_detail
    for name in ("未実行", "回答待ち", "一部", "失敗", "途中"):
        res = got[name][0]
        ch2 = res.report_path.read_text(encoding="utf-8").split("## 2.")[1].split("## 3.")[0]
        assert f"| 状態 | {report.ai_state(res)}（位置を聞いた図・表 3 個のうち、残り " in ch2, name


def test_api_failure_is_recommended_step_and_exit_code_0(journal, meta, tmp_path, monkeypatch, capsys):
    """API の呼び出しの失敗（偽の呼び出し）は、推奨の手順 ai_finish の「失敗」: needs_action は偽・終了コード 0・failed は真。
    位置を聞く図形のない原稿（sample_full）でも、失敗は知らせる（回答待ちは知らせない）。"""
    from jasme_jats import pipeline
    from jasme_jats.ai_assist import AIOutcome
    from jasme_jats.cli import main
    from conftest import fill_images, one_color_png
    monkeypatch.setattr(pipeline, "call_provider",
                        lambda *a, **k: AIOutcome(mode="api", model="claude-test", error="AI の呼び出しに失敗しました: 試験"))
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path / "a", ai_mode="api", ai_api_key="k"))
    keys = fill_images(res)
    fin = _finish(res)
    assert fin is not None and fin.failed and not fin.done and not res.needs_action and blocking(report.actions(res)) == []
    assert fin.box_title == "AI の回答を反映できませんでした" and report.step("convert_again") in fin.box_detail
    assert "（また失敗するときは、手動に切り替えます）" in fin.box_detail
    assert _finish(convert(FULL, meta, journal, Options(out_dir=tmp_path / "w", ai_mode="manual"))) is None
    pics = tmp_path / "pics"
    pics.mkdir()
    for key in keys:
        (pics / f"{key}.png").write_bytes(one_color_png())
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    capsys.readouterr()
    assert main([str(FULL), "--meta", str(META_EXAMPLE), "--out", str(tmp_path / "b"), "--ai", "api",
                 "--images", str(pics)]) == 0
    err = capsys.readouterr().err
    assert "手順（推奨）: AI の回答を反映できませんでした。AI の呼び出しに失敗しました: 試験。" in err
    assert "--ai api でもう一度実行すること" in err


def test_textbox_only_original_titles_ai_finish_for_boxes(journal, meta, tmp_path):
    """位置を聞く図形がなく、囲みか図の注記か決められないテキストボックスだけの原稿（sample_structure）では、ai_finish の見出しを
    「AI にテキストボックスの種類を判断させる（推奨）」にし、テキストボックスの文を書く。"""
    from conftest import STRUCTURE
    res = convert(STRUCTURE, meta, journal, Options(out_dir=tmp_path))
    assert not res.plan.asked_floats and res.plan.undecided_boxes
    fin = _finish(res)
    assert fin.box_title == "AI にテキストボックスの種類を判断させる（推奨）" and fin.progress == "未実行"
    assert "囲みか図の注記か決められないテキストボックス 3 個の文字は、XML に出していません。AI が種類を判断します。" in fin.box_detail
    assert "AI がテキストボックスの種類を決めます" in fin.cli
