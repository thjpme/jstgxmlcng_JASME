"""「手順」の型（report.STEP。必須と推奨の別・済んだか・失敗したか）。要対応・要確認とは別の区分で、出す場所を決める仕組みは
report.actions() の 1 か所のまま。止める知らせは report.blocking() が決める。"""
import re

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
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path / "a", ai_mode="manual"))
    keys = fill_images(res)                     # 図の画像の手順（必須）を済ませる
    acts = report.actions(res)
    ai = next(a for a in acts if a.key == "ai_pending")
    assert ai.level == STEP and ai.required is False and ai.progress == "回答待ち"
    assert ai.top == "" and "AI の回答をまだ反映していない" in ai.checklist
    assert not any(a.level == NEEDS_ACTION for a in acts) and blocking(acts) == [] and not res.needs_action
    pics = tmp_path / "pics"
    pics.mkdir()
    for key in keys:
        (pics / f"{key}.png").write_bytes(one_color_png())
    assert main([str(FULL), "--meta", str(META_EXAMPLE), "--out", str(tmp_path / "b"), "--ai", "manual",
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
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, ai_mode="manual"))
    chapter14 = res.report_path.read_text(encoding="utf-8").split("## 14.")[1]
    ai = next(a for a in report.actions(res) if a.key == "ai_pending")
    other = next(a for a in report.actions(res) if a.key == "name_split")        # 要確認
    assert chapter14.index(ai.checklist) < chapter14.index(other.checklist)
    # 冒頭の囲みには手順を出さない
    assert "AI の回答をまだ反映していない" not in report_head(res)


def report_head(res):
    return res.report_path.read_text(encoding="utf-8").split("## 2.")[0]


def test_step_marks_are_replaced_on_three_screens(journal, meta, tmp_path):
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, ai_mode="manual"))
    ai = next(a for a in report.actions(res) if a.key == "ai_pending")
    assert "\x00" in ai.box_detail                       # 目印を使っている
    note = colab.step_text(ai.box_detail, "notebook")
    page = colab.step_text(ai.box_detail, "app")
    cli = colab.step_text(ai.box_detail, "cli")
    assert re.search(r"手順 ?\d", note) and not re.search(r"手順 ?\d", page + cli)
    assert "\x00" not in note + page + cli
    assert note != page != cli


def test_result_boxes_blocking_only(journal, meta, tmp_path):
    from conftest import fill_images
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, ai_mode="manual"))
    assert "図の画像を入れてください" in colab.result_boxes(res, blocking=True)     # 必須の手順は止める
    fill_images(res)
    assert colab.result_boxes(res, blocking=True) == ""
    assert "AI の回答をまだ反映していません" in colab.result_boxes(res)
    assert colab.result_boxes(res, skip=("ai_pending", "name_split")) == ""
