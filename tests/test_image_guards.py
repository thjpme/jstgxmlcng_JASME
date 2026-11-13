"""画像の守りと知らせ（修正計画 W1 の手順 11。2.9・4.2〜4.4）。

- 要対応 lost: 画像を入れる場所（置き場所）を作れなかった画像。置き場所をすべて書いた XML（Result.xml_base）で調べるので、「入れない」とした
  置き場所は置き場所ありとみなす（pipeline.lost_images）。
- 要対応 image_names: XML の画像の名前が置き場所の一覧と合わない（pipeline.image_problems。変換ツールの不具合の守り）。
- ZIP の確かめ（package.zip_problems）: 置き場所にない名前の画像と、入れたのに ZIP にない画像だけを見る（まだ入れていない画像は数えない）。
- 要確認 textbox_figure_text: 図の画像に写るとみなした図形の中の文字を、図形ごとに 1 行（図番号・幹）で知らせる。
- 要確認 image_same: 同じ中身の画像が 2 つ以上の置き場所に入っている。
- 飾りの図形（Result.decorations）は 9 章に記録するだけで、知らせない。図キャプションのある図形の中の文字の図形だけのグループは、
  「図形で描いた図（図の本体）」として分ける。
fixture は make_fixtures.make_float_figs・make_figs（内容は架空）。
"""
import json
import shutil
import zipfile

from lxml import etree

import make_fixtures as mf
from conftest import fill_images, key_png
from jasme_jats.builder import build, finalize, serialize
from jasme_jats.package import apply_images, zip_problems
from jasme_jats.pipeline import (Options, _mechanical, add_images, convert, image_problems, kept_images, lost_images,
                                 reapply_images, rebuild_outputs)
from jasme_jats.report import NEEDS_ACTION, TO_CHECK, actions, image_rows

XLINK = "{http://www.w3.org/1999/xlink}href"


def run(tmp_path, meta, journal, variant, placements=None, name="out"):
    path = tmp_path / f"{variant}.docx"
    if not path.exists():
        mf.make_float_figs(path, variant)
    resp = None if placements is None else json.dumps({"placements": placements, "operations": [], "notes": []},
                                                      ensure_ascii=False)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / name, ai_mode="manual", ai_response=resp))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    assert res.lost_images == [] and res.image_problems == []
    return res


def acts(res):
    return {a.key: a for a in actions(res)}


def chapter9(res):
    return res.report_path.read_text(encoding="utf-8").split("## 9.")[1].split("## 10.")[0]


def figure_text_lines(res):
    a = acts(res)["textbox_figure_text"]
    assert a.level == TO_CHECK
    return a.box_detail.split("\n")[1:]


# ---------------------------------------------------------------------------- 要対応 lost（置き場所をすべて書いた XML で調べる）
def test_lost_images_looks_at_the_xml_with_all_slots(journal, meta, tmp_path):
    """lost_images は、置き場所をすべて書いた XML（xml_base）に置き場所の名前が出ているかで調べる。「入れない」で要素を取り除いた
    最終の XML で調べると、その画像は置き場所がないことになる（だから xml_base で調べる）。名前が XML にない置き場所の画像は lost。"""
    path = tmp_path / "nocap.docx"
    mf.make_float_figs(path, "nocap_group")
    doc, plan, _ = _mechanical(path, journal)
    root, info = build(plan, meta, journal, journal.split_labels)
    base = serialize(finalize(root))
    exclusions = plan.exclusions + info.exclusions
    [slot] = info.slots
    assert slot.kind == "nocap" and lost_images(doc, plan, root, info, exclusions, base) == ([], [])
    from jasme_jats.images import SlotImage
    final = apply_images(base, [SlotImage(slot.key, info.slot_names[slot.key], kind="nocap", status="skipped")])
    assert final != base and b"<graphic" not in final
    lost, _ = lost_images(doc, plan, root, info, exclusions, final)
    assert [li.image_id for li in lost] == [i.image_id for i in slot.covers]
    assert lost[0].reason.startswith("段落は XML に出力したが、画像を入れる場所を XML に書いていない")


def test_skipped_slot_is_not_lost_after_converting_again(journal, meta, tmp_path):
    """「入れない」としたキャプションのない画像は、変換し直して持ち越しても、要対応 lost にならない（監督の決定 3）。"""
    res = run(tmp_path, meta, journal, "nocap_group")
    [im] = res.images
    add_images(res, {}, skip=[im.key])
    assert res.images[0].status == "skipped" and res.lost_images == [] and "lost" not in acts(res)
    kept = kept_images(res)
    again = run(tmp_path, meta, journal, "nocap_group", name="again")
    reapply_images(again, kept)
    assert again.images[0].status == "skipped" and again.lost_images == [] and not again.needs_action
    assert again.image_problems == [] and again.zip_issues == []
    assert not list(etree.fromstring(again.xml_path.read_bytes()).iter("graphic"))


# ---------------------------------------------------------------------------- 要対応 image_names（名前の不具合の守り）
def test_image_problems_finds_broken_names(journal, meta, tmp_path):
    """最終の XML の xlink:href に、置き場所にない名前・同じ名前の重なり・出ていない置き場所があれば image_problems が挙げる。"""
    res = run(tmp_path, meta, journal, "two_figs")
    n1, n2 = (i.name for i in res.images)
    assert image_problems(res.xml_base, res.images) == []
    broken = res.xml_base.replace(n2.encode(), n1.encode())        # fig02 の <graphic> が fig01 の名前を指す
    got = image_problems(broken, res.images)
    assert got == [f"XML に {n1} が 2 回出ています（同じ画像を 2 つ以上の図が指しています）",
                   f"fig02（{n2}）が XML に出ていません"]
    other = res.xml_base.replace(n2.encode(), b"31_1_fig99.png")
    assert image_problems(other, res.images)[0] == "XML の 31_1_fig99.png は、画像を入れる場所の一覧にない名前です"
    # 作り直しのたびに確かめ、要対応 image_names で知らせる（終了コード 1）
    res.xml_base = broken
    rebuild_outputs(res)
    a = acts(res)["image_names"]
    assert a.level == NEEDS_ACTION and res.needs_action and "変換ツールの不具合の可能性" in a.box_title
    assert "この XML は登載に使わず、変換レポートを添えて開発者に知らせてください" in a.box_detail
    assert "### XML の画像の名前の不具合（要対応）" in chapter9(res)


# ---------------------------------------------------------------------------- ZIP の確かめ（画像の 2 つ）
def test_zip_problems_do_not_count_images_not_yet_supplied(journal, meta, tmp_path):
    """画像を入れる前の ZIP では、置き場所の名前の画像がなくても要対応 upload を出さない（手順 images が伝える。監督の決定 2）。"""
    res = run(tmp_path, meta, journal, "two_figs")
    assert [i.status for i in res.images] == ["missing", "missing"] and res.zip_issues == []
    assert "upload" not in acts(res)
    fill_images(res)
    assert res.zip_issues == [] and "upload" not in acts(res)


def test_zip_problems_find_unknown_and_missing_images(journal, meta, tmp_path):
    """ZIP の Graphics/ に置き場所にない名前の画像がある・入れた画像が ZIP にない、を zip_problems が挙げる。"""
    res = run(tmp_path, meta, journal, "two_figs")
    fill_images(res)
    adir = "jasme/31/1/31_1"
    stray = tmp_path / "stray.zip"
    shutil.copyfile(res.zip_path, stray)
    with zipfile.ZipFile(stray, "a") as z:
        z.writestr(f"{adir}/Graphics/31_1_fig09.png", key_png(9))
    assert zip_problems(stray, journal, meta, res.images) == [
        ("-", "ZIP の Graphics/ に、画像を入れる場所にない名前の画像がある（31_1_fig09.png）")]
    assert zip_problems(stray, journal, meta) == []          # images を渡さなければ画像の名前は見ない（今までの確かめ）
    missing = tmp_path / "missing.zip"
    with zipfile.ZipFile(res.zip_path) as src, zipfile.ZipFile(missing, "w") as dst:
        for info in src.infolist():
            if not info.filename.endswith("31_1_fig02.png"):
                dst.writestr(info, src.read(info))
    assert zip_problems(missing, journal, meta, res.images) == [
        ("-", "入れた画像 31_1_fig02.png が、アップロード用の ZIP に入っていない（画像を入れ直してください）")]


# ---------------------------------------------------------------------------- 要確認 textbox_figure_text（図形ごとに 1 行）
def test_figure_text_lines_name_the_figure(journal, meta, tmp_path):
    """図形の中の文字の要確認は 1 つで、図形ごとに 1 行。行に図番号と幹（キャプションのない画像は幹と場所）が出る。4 つの形:
    図キャプションの図形・図キャプション 2 つの図形・本文の図キャプションに含めた図形（B6）・キャプションのないグループ図形。"""
    assert figure_text_lines(run(tmp_path, meta, journal, "group")) == ["・図1（fig01）の図形: 9 字「点Ａと点Ｂを結ぶ。」"]
    assert figure_text_lines(run(tmp_path, meta, journal, "two_figs_text")) == [
        "・図1・図2（fig01・fig02）の図形: 7 字「線分ＡＢの長さ」"]
    assert figure_text_lines(run(tmp_path, meta, journal, "near_group3")) == [
        "・本文の図キャプション「図1　近くの段落の図形の図」の図（fig01）に含めた図形: 2 字「点Ｐ」"]
    res = run(tmp_path, meta, journal, "nocap_group")
    [slot] = res.plan.slots
    assert figure_text_lines(res) == [f"・キャプションのない画像（{slot.key}。「試験（2024）にならい，図形の中身の組…」の段落の後ろ"
                                      "（章「１．図形の中身」））の図形: 2 字「点Ｐ」"]
    a = acts(res)["textbox_figure_text"]
    assert a.box_title == "図の画像に写るものとして、XML の本文に出していない文字があります（図形 1 つ。要確認）"
    assert "> **要確認: 図の画像に写るものとして、XML の本文に出していない文字があります（図形 1 つ。6 章）。**" in a.top
    assert f"> - キャプションのない画像（{slot.key}。" in a.top and f"  キャプションのない画像（{slot.key}。" in a.cli
    assert a.checklist.startswith("- [ ] **図の画像に写るものとして XML の本文に出していない文字（図形 1 つ）**（6 章）")


def test_figure_text_lines_are_the_same_with_and_without_ai(journal, meta, tmp_path):
    """位置を決められない図形でも、AI の位置の指定の前後で、図形ごとの行は同じ（図形の中身の組み方は AI の指定で変わらない）。"""
    before = run(tmp_path, meta, journal, "group_down", name="before")
    anchor = next(s for s, p in before.plan.paras.items() if p.plain().startswith("この段落に図形が"))
    after = run(tmp_path, meta, journal, "group_down", name="after", placements=[
        {"float": "s1", "after": anchor, "items": [], "reason": "試験", "confidence": "中"}])
    assert figure_text_lines(before) == figure_text_lines(after) == ["・図1（fig01）の図形: 9 字「点Ａと点Ｂを結ぶ。」"]


# ---------------------------------------------------------------------------- 要確認 image_same
def test_same_image_in_two_slots_is_noticed(journal, meta, tmp_path):
    """同じ中身の画像を 2 つの図に入れると要確認 image_same（取り違えの確かめ）。備考にも出る。違う画像なら出ない。"""
    res = run(tmp_path, meta, journal, "two_figs")
    png = key_png(1)
    add_images(res, {"fig01": ("a.png", png), "fig02": ("b.png", png)})
    a = acts(res)["image_same"]
    assert a.level == TO_CHECK and not res.needs_action
    assert a.box_title == "同じ画像が 2 つ以上の図に入っています（要確認）"
    assert a.box_detail.startswith("図1（fig01）と図2（fig02）に、同じ中身の画像が入っています。")
    assert "fig01・fig02" in a.checklist and "fig01・fig02" in a.cli
    notes = {row.key: row.note for row in image_rows(res)}
    assert notes == {"fig01": "同じ画像が図2 にも入っています", "fig02": "同じ画像が図1 にも入っています"}
    add_images(res, {"fig02": ("b.png", key_png(2))})
    assert "image_same" not in acts(res)


# ---------------------------------------------------------------------------- 飾りと、図形で描いた図
def test_decorations_are_recorded_not_noticed(journal, meta, tmp_path):
    """図形の外の枠・白い四角は、9 章の「画像の場所に数えなかった図形（飾り）」に場所と種類を出すだけで、知らせない。"""
    path = tmp_path / "deco.docx"
    mf.make_figs(path, "deco")
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    assert res.fidelity.ok and res.lost_images == [] and res.images == []
    assert sorted(d.kind for d in res.decorations) == ["frame", "mask"] and all(not d.figure for d in res.decorations)
    assert actions(res) == [] and not res.needs_action
    ch9 = chapter9(res)
    assert "### 画像の場所に数えなかった図形（飾り）" in ch9 and "| 枠 |" in ch9 and "| 白い四角 |" in ch9
    assert "### 図形で描いた図" not in ch9


def test_text_shapes_group_with_figure_caption_is_a_drawn_figure(journal, meta, tmp_path):
    """図キャプションのある図形の中の、文字の図形だけのグループ（Word の図形で描いた図。data10・data25 の形）は、飾りの一覧に入れず、
    「図形で描いた図（図1 の本体）」に分ける。その図の備考と手順 images の行に「Word の図形で描いた図です」が出て、「docx でこの図の
    画像を見つけられませんでした」は出ない。図キャプションのない同じ形のグループは、飾りの一覧に入る。"""
    res = run(tmp_path, meta, journal, "drawn")
    [deco] = res.decorations
    assert (deco.kind, deco.figure) == ("textgroup", "fig01") and deco.where.startswith("図形 s1（「この段落に図形が")
    [row] = image_rows(res)
    assert row.drawn == "文字の図形の集まり" and "見つけられませんでした" not in row.note
    assert row.note == "Word の図形（文字の図形の集まり）で描いた図です。出版版 PDF から図の部分を切り取って入れてください"
    step = acts(res)["images"]
    assert "・fig01: 「図1　図形で描いた図」（Word の図形（文字の図形の集まり）で描いた図です。" in step.box_detail
    ch9 = chapter9(res)
    assert "### 図形で描いた図（図の本体）" in ch9 and "- 図1（fig01）: 文字の図形の集まり（img1。" in ch9
    assert "### 画像の場所に数えなかった図形（飾り）" not in ch9
    assert set(acts(res)) == {"ai_pending", "textbox_figure_text", "images"}
    free = run(tmp_path, meta, journal, "drawn_free", name="free")
    [deco] = free.decorations
    assert (deco.kind, deco.figure) == ("textgroup", "") and free.images == []
    ch9 = chapter9(free)
    assert "### 画像の場所に数えなかった図形（飾り）" in ch9 and "| img1 | 文字の図形の集まり | 図形 s1（" in ch9
    assert "### 図形で描いた図" not in ch9
