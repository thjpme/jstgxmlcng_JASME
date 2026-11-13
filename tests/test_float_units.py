"""浮動配置の図形の中身の組み方（structure.Classifier.float_units。修正計画 W1 の 2.3 の B1〜B5・B7・B8 と 2.4）と、
AI の位置の指定を after だけ読むこと（2.7）。fixture は make_fixtures.make_float_figs（内容は架空）。"""

import pytest
from lxml import etree

import answers
import make_fixtures as mf
from jasme_jats.pipeline import Options, _mechanical, convert
from jasme_jats.report import TO_CHECK, actions
from jasme_jats.structure import TEXTBOX_TEXT_EXCLUDED

XLINK = "{http://www.w3.org/1999/xlink}href"


def load(res):
    return etree.fromstring(res.xml_path.read_bytes().split(b"\n", 2)[2])


def run(tmp_path, meta, journal, variant, placements=None, name="out"):
    path = tmp_path / f"{variant}.docx"
    if not path.exists():
        mf.make_float_figs(path, variant)
    resp = None if placements is None else answers.answer(placements=placements)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / name, ai_mode="manual", ai_response=resp))
    fid = res.fidelity
    assert fid.ok and fid.final_ok and res.dtd_valid and res.jstage_issues == [], (fid.missing, fid.conflicts)
    assert res.lost_images == []
    return res


def seq(root):
    """本文の要素の並び: 段落は文字の冒頭 8 字、図・表は「ID:キャプションの冒頭 2 字（なければ -）:中身（g は画像、t は表）」。"""
    out = []
    for el in root.find("body").iter("p", "fig", "table-wrap"):
        if el.tag in ("fig", "table-wrap"):
            if el.getparent().tag == "fig":
                continue
            cap = el.find("caption")
            inner = "g" * len(el.findall("graphic")) + "t" * len(el.findall(".//table"))
            out.append(f"{el.get('id') or '-'}:{''.join(cap.itertext())[:2] if cap is not None else '-'}:{inner}")
        elif el.getparent().tag in ("sec", "body"):
            out.append("".join(el.itertext())[:8])
    return out


def excluded(res):
    return [(t, w) for _, w, t in res.fidelity.excluded if w == TEXTBOX_TEXT_EXCLUDED]


def src_of(plan, head):
    return next(src for src, p in plan.paras.items() if p.plain().startswith(head))


def test_group_shape_with_images_line_mask_and_text(journal, meta, tmp_path):
    """グループ図形（画像 2 枚・線・白い四角・文字・中のキャプション。C002・C004）: 図 1 つ・置き場所 1 つ（画像 2 枚とも含める）。
    中の文字は図の画像に写るとみなして除外し、要確認 textbox_figure_text に載せる。線と白い四角は飾りなので数えない。"""
    res = run(tmp_path, meta, journal, "group")
    assert res.plan.floats["s1"].mode == "mechanical"
    assert seq(load(res))[1:3] == ["F1:図1:g", "この段落に図形が"]
    [slot] = res.plan.slots
    assert (slot.key, slot.kind, slot.how, len(slot.covers)) == ("fig01", "fig", "float", 2)
    assert excluded(res) == [("点Ａと点Ｂを結ぶ。", TEXTBOX_TEXT_EXCLUDED)]
    assert [a.key for a in actions(res) if a.level == TO_CHECK] == ["textbox_figure_text"]


def test_group_shape_exclusions_are_the_same_with_and_without_ai(journal, meta, tmp_path):
    """位置を決められないグループ図形でも、中身の組み方と除外は AI の位置の指定の前後で同じ（AI の指定は位置だけ）。"""
    before = run(tmp_path, meta, journal, "group_down", name="before")
    assert before.plan.unplaced_floats == ["s1"]
    after = run(tmp_path, meta, journal, "group_down", name="after",
                placements=[("s1", src_of(before.plan, "この段落に図形が"))])
    assert after.plan.floats["s1"].mode == "ai" and after.ai.rejected == []
    assert excluded(before) == excluded(after) == [("点Ａと点Ｂを結ぶ。", TEXTBOX_TEXT_EXCLUDED)]
    assert [(s.key, len(s.covers)) for s in before.plan.slots] == [(s.key, len(s.covers)) for s in after.plan.slots] == [
        ("fig01", 2)]


def test_two_figure_captions_in_one_float(journal, meta, tmp_path):
    """図キャプション 2 つの図形: 図 2 つ・置き場所 2 つ（画像はその後ろの最初の図キャプションの図）。"""
    res = run(tmp_path, meta, journal, "two_figs")
    assert seq(load(res))[1:4] == ["F1:図1:g", "F2:図2:g", "この段落に図形が"]
    assert [(s.key, len(s.covers)) for s in res.plan.slots] == [("fig01", 1), ("fig02", 1)]
    assert excluded(res) == []


def test_two_table_captions_above_and_below(journal, meta, tmp_path):
    """表キャプション 2 つと表 2 つ（表1 は表の上、表2 は表の下のキャプション）: 表 2 つに組む（B2）。"""
    res = run(tmp_path, meta, journal, "two_tables")
    root = load(res)
    assert seq(root)[1:4] == ["T1:表1:t", "T2:表2:t", "この段落に図形が"]
    cells = ["".join(t.find(".//td").itertext()) for t in root.iter("table-wrap")]
    assert cells == ["上の表の中身", "下の表の中身"] and res.plan.slots == []


def test_table_figure_with_note_text(journal, meta, tmp_path):
    """図キャプション・キャプションのない表・注の文字の図形: 表で組んだ図（置き場所なし。決定 2）と、その直後の本文の段落
    （画像に写らないので除外しない。FloatInfo.body_paras。2.4）。"""
    res = run(tmp_path, meta, journal, "table_fig_note")
    assert seq(load(res))[1:4] == ["F1:図1:t", "注：架空の注であ", "この段落に図形が"]
    assert excluded(res) == [] and res.plan.slots == []
    info = res.plan.floats["s1"]
    assert info.built == "units" and [q.plain() for q in info.body_paras] == ["注：架空の注である。"]
    assert src_of(res.plan, "注：架空の注") not in res.plan.body_seq          # AI が位置に書ける段落には入れない


def test_unplaced_table_figure_notice_lists_its_body_paragraph(journal, meta, tmp_path):
    """位置を決められない図形の中から本文の段落として出した段落は、図形の中身の図表の ID（structure.float_targets）に、図の ID と
    並べて示す。"""
    from jasme_jats.structure import float_targets
    res = run(tmp_path, meta, journal, "table_fig_note_down", placements=[])
    assert res.plan.unplaced_floats == ["s1"]
    assert float_targets(res.plan, res.plan.floats["s1"]) == "F1 と段落「注：架空の注である。」"
    [row] = [u[3] for u in res.unresolved_after if u[0] == "float"]
    assert row.startswith("結び付いた段落の後ろ（段落「この段落に図形が結び付いている。本文の段」の後ろ）に置いた")


def test_ambiguous_table_captions_keep_the_contents(journal, meta, tmp_path):
    """表・表1・表・表2 の図形（キャプションのない表と本体のない表キャプションが残る）: 組めないので中身を docx の順に
    そのまま出し（B5）、判断の一覧に記録する。位置は機械的に決まる。"""
    res = run(tmp_path, meta, journal, "ambiguous")
    info = res.plan.floats["s1"]
    assert info.mode == "mechanical" and info.built == "raw"
    assert seq(load(res))[1:5] == ["T1:-:t", "T2:表1:t", "T3:表2:", "この段落に図形が"]
    assert any(d.message == "図形 s1 の表とキャプションの組み方を決められないので、中身を docx の順に出した"
               for d in res.plan.decisions)


def test_group_without_caption_is_a_figure_without_caption(journal, meta, tmp_path):
    """キャプションのないグループ図形（画像を直接持つ）: <fig><graphic/></fig>（id なし）。中の文字は図の画像に写るとみなして
    除外する（B4・2.4）。"""
    res = run(tmp_path, meta, journal, "nocap_group")
    root = load(res)
    [fig] = list(root.iter("fig"))
    assert fig.get("id") is None and fig.find("caption") is None and len(fig.findall("graphic")) == 1
    [slot] = res.plan.slots
    assert slot.kind == "nocap" and slot.how == "float" and fig.find("graphic").get(XLINK) == f"31_1_{slot.key}.png"
    assert excluded(res) == [("点Ｐ", TEXTBOX_TEXT_EXCLUDED)]


def test_caption_like_paragraph_in_group_without_caption_is_its_caption(journal, meta, tmp_path):
    """キャプションのないグループ図形の中の「資料：…」（80 字以内で「。」で終わらない、キャプションの形の段落）は、図の画像に写る
    文字として除外せず、その図の <caption> にする。続く出典の注記はキャプションの続き（引用のリンクも XML に残る。data24 の形）。
    ほかの文字は今までどおり除外する。"""
    res = run(tmp_path, meta, journal, "nocap_source")
    root = load(res)
    [fig] = list(root.iter("fig"))
    caps = ["".join(p.itertext()) for p in fig.find("caption").iter("p")]
    assert caps == ["資料：　架空の授業プリントの問い", "※試験（2024）を基に筆者作成"]
    assert [x.get("ref-type") for x in fig.find("caption").iter("xref")] == ["bibr"]
    assert fig.get("id") == "F1" and len(fig.findall("graphic")) == 1
    [slot] = res.plan.slots
    assert (slot.kind, slot.key, slot.how) == ("fig", "figx01", "float")
    assert excluded(res) == [("点Ｐ", TEXTBOX_TEXT_EXCLUDED)]
    assert any("キャプションの形" in d.message for d in res.plan.decisions)


def test_caption_more_stops_at_another_textbox(journal, meta, tmp_path):
    """キャプションの形の段落が図形の先頭にあり、後ろに別のテキストボックスのラベルの文字が続く形: ラベルの文字は
    キャプションの続きに取り込まず、図の画像に写る文字として除外する（要確認に出る）。"""
    res = run(tmp_path, meta, journal, "nocap_label")
    [fig] = list(load(res).iter("fig"))
    assert ["".join(p.itertext()) for p in fig.find("caption").iter("p")] == ["資料：　架空の授業プリントの問い"]
    assert [t for t, _ in excluded(res)] == ["点Ａ", "ラベルの文字：" + "あ" * 40, "いろいろ" * 30]
    assert "textbox_figure_text" in [a.key for a in actions(res) if a.level == TO_CHECK]


def test_figure_captions_above_images_in_one_float(journal, meta, tmp_path):
    """図形の中で図キャプションが画像の上にある形（図1・画像・図2・画像）: 画像はその前の最後の図キャプションの図に含める
    （図 2 つ・置き場所 2 つで、どちらにも画像が 1 枚ずつ）。"""
    res = run(tmp_path, meta, journal, "two_figs_above")
    assert seq(load(res))[1:4] == ["F1:図1:g", "F2:図2:g", "この段落に図形が"]
    assert [(s.key, [i.image_id for i in s.covers]) for s in res.plan.slots] == [("fig01", ["img1"]), ("fig02", ["img2"])]
    assert excluded(res) == []


def test_textbox_without_caption_or_direct_image_is_body_elements(journal, meta, tmp_path):
    """キャプションもグループの画像もないテキストボックス（文字の段落・表・画像だけの段落）: 図にせず、中身を docx の順に本文の
    要素として出す（文字は段落、表は表、画像だけの段落はキャプションなしの図。B4）。文字は除外しない。"""
    res = run(tmp_path, meta, journal, "nocap_textbox")
    assert seq(load(res))[1:5] == ["図形の中の説明の", "T1:-:t", "-:-:g", "この段落に図形が"]
    assert excluded(res) == [] and [s.kind for s in res.plan.slots] == ["nocap"]
    assert [q.plain() for q in res.plan.floats["s1"].body_paras] == ["図形の中の説明の文である。"]


@pytest.mark.parametrize("ai", [False, True])
@pytest.mark.parametrize("variant, want", [
    ("anchor_tabcap_down", ["T1:表1:t", "F1:図5:g", "以上で終わる。"]),
    ("anchor_figcap_down", ["F1:図1:g", "F2:図5:g", "以上で終わる。"]),
    ("anchor_image_down", ["F1:図5:g", "F2:図1:g", "以上で終わる。"]),
])
def test_anchor_on_caption_or_image_paragraph(journal, meta, tmp_path, variant, want, ai):
    """アンカー段落（AI の指定した段落）が、本文の表キャプション（後ろに表）・図キャプション（前に画像）・画像だけの段落
    （後ろに図キャプション）でも、本文のキャプションと本体は組まれ、図形の図はその後ろに出る（図はキャプションの位置に組むので、
    画像だけの段落なら、図形の図・本文の図の順）。組み立て済みの図表を前後の要素に数えない（B8。data22・data24 の形）。"""
    first = run(tmp_path, meta, journal, variant, name="first")
    assert first.plan.unplaced_floats == ["s1"]
    pls = None
    if ai:
        pls = [("s1", first.plan.floats["s1"].float.anchor_src)]
    res = run(tmp_path, meta, journal, variant, placements=pls)
    assert res.plan.floats["s1"].mode == ("ai" if ai else "unplaced")
    assert seq(load(res))[1:4] == want


def test_mechanical_float_placement_is_rejected(journal, meta, tmp_path):
    """位置を機械的に決めた図形への指定は、今までどおり「機械的に配置した図形は変更させない」で不採用に記録する。"""
    path = tmp_path / "group.docx"
    mf.make_float_figs(path, "group")
    _, plan, _ = _mechanical(path, journal)
    res = run(tmp_path, meta, journal, "group", placements=[("s1", src_of(plan, "試験（2024）"))])
    [(op, why)] = res.ai.rejected
    assert op["src"] == "s1" and "機械的に決めた" in why and res.plan.floats["s1"].mode == "mechanical"


def test_placement_after_paragraph_that_is_no_longer_body_is_rejected(journal, meta, tmp_path, monkeypatch):
    """同じ回答の set_role で、置く位置の段落が本文の段落でなくなった指定は、黙って捨てずに不採用として 2 章に記録する
    （図形は位置を決められない図表のまま）。本文の段落への ack_heading は、今は Word のスタイルで直す提案で XML に反映しない
    （所有者の決定 5。W8 の手順 5）ので、位置の指定を採用する。守りは、区切り以外の役割も反映する形に差し替えて確かめる。"""
    import jasme_jats.ai_assist as ai_assist
    path = tmp_path / "group_down.docx"
    mf.make_float_figs(path, "group_down")
    _, plan, _ = _mechanical(path, journal)
    after = src_of(plan, "以上で終わる。")
    resp = answers.answer(placements=[("s1", after)], style_fixes=[(after, "ack_heading", "試験", "低")])
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "prop", ai_mode="manual", ai_response=resp))
    assert [w for _, w in res.ai.rejected] == [ai_assist.STYLE_ONLY_WHY]
    assert after in res.plan.body_seq and res.plan.unplaced_floats == [] and res.fidelity.ok
    monkeypatch.setattr(ai_assist, "boundary_kind", lambda p, plan, role: "試験の区切り")
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", ai_mode="manual", ai_response=resp))
    assert res.fidelity.ok and res.fidelity.final_ok
    assert after not in res.plan.body_seq and res.plan.unplaced_floats == ["s1"]
    [why] = [w for op_, w in res.ai.rejected if op_["op"] == "place_float"]
    assert "組み直した後に本文の段落でなくなった" in why


# ----------------------------------------------------------------------------- 本文の図キャプションに組む図形（2.3 の B6。W1 の手順 6）
@pytest.mark.parametrize("variant", ["near_group3", "near_group3_down", "near_group_empty_down"])
def test_group_near_figure_caption_goes_into_the_figure(journal, meta, tmp_path, variant):
    """キャプションのないグループ図形を結び付けた段落の 3 要素後ろに、画像のない本文の図キャプション（C029）: グループ図形ごと
    その図に含め（図 1 つ・置き場所 1 つ）、図形は図キャプションの位置に置いたもの（mode caption）として、位置を決められない
    図形に入れない（AI がなくても変換できる）。グループの中の文字は図の画像に写るとみなして除外する。グループ図形だけの空の
    段落も、キャプションなしの図を別に作らない。"""
    res = convert(_make(tmp_path, variant), meta, journal,
                  Options(out_dir=tmp_path / "none"))
    fid = res.fidelity
    assert fid.ok and fid.final_ok and res.dtd_valid and res.jstage_issues == [] and res.lost_images == []
    plan = res.plan
    info = plan.floats["s1"]
    assert info.mode == "caption" and plan.unplaced_floats == [] and info.reason == ""
    cap = src_of(plan, "図1　近くの段落の図形の図")
    assert info.caption_src == cap and [n.fid for n in info.nodes] == ["F1"]
    [slot] = plan.slots
    assert (slot.key, slot.kind, slot.how, [i.float_id for i in slot.covers]) == ("fig01", "fig", "near", ["s1"])
    root = load(res)
    [fig] = list(root.iter("fig"))
    assert fig.get("id") == "F1" and fig.find("graphic").get(XLINK) == "31_1_fig01.png"
    assert excluded(res) == [("点Ｐ", TEXTBOX_TEXT_EXCLUDED)]
    # 位置の判断は、図キャプションの図に含めたことの記録に書き直す（位置を決められないとは書かない）
    msgs = [d.message for d in plan.decisions if "s1" in d.message]
    assert len(msgs) == 1 and "本文の図キャプション「図1　近くの段落の図形の図」の図に含めた" in msgs[0]
    assert "決められない" not in msgs[0]
    # 図・表の一覧: 図形 s1 の図は、図キャプションの位置
    assert [(r.fid, r.kind, r.label, r.key, r.float_id, r.place) for r in plan_rows(plan)] == [
        ("F1", "fig", "図1", "fig01", "s1", "caption")]
    # 3 章に、図キャプションの図に含めた図形を挙げる
    assert "その位置に置いた図形" in res.report_path.read_text(encoding="utf-8")


def test_placement_of_float_in_body_figure_is_rejected(journal, meta, tmp_path):
    """本文の図キャプションの図に含めた図形（mode caption）への位置の指定は、「本文の図キャプション [dN] の図に含めて配置した
    図形なので、位置を変更できない」で不採用に記録する（図形はキャプションの位置のまま）。"""
    path = _make(tmp_path, "near_group3")
    _, plan, _ = _mechanical(path, journal)
    res = run(tmp_path, meta, journal, "near_group3", placements=[("s1", src_of(plan, "試験（2024）"))])
    info = res.plan.floats["s1"]
    [(op, why)] = res.ai.rejected
    assert info.mode == "caption" and op["src"] == "s1"
    assert why == f"図形 s1 は本文の図キャプション [{info.caption_src}] の図に含めて配置した図形なので、位置を変更できない"


def test_group_four_elements_before_caption_stays_unplaced(journal, meta, tmp_path):
    """4 要素前の段落に結び付いたグループ図形は含めない: 図 1 つ（画像の見つからない図）＋キャプションなしの図 1 つで、図形は
    位置を決められないまま。"""
    path = _make(tmp_path, "near_group4_down")
    none = convert(path, meta, journal, Options(out_dir=tmp_path / "none"))      # AI なしでも中止しない（W8 の決定 4）
    assert none.plan.unplaced_floats == ["s1"]
    res = run(tmp_path, meta, journal, "near_group4_down")
    plan = res.plan
    assert plan.floats["s1"].mode == "unplaced" and plan.unplaced_floats == ["s1"]
    assert [(s.kind, s.how) for s in plan.slots] == [("nocap", "float"), ("fig", "")]
    assert [(r.fid, r.kind, r.float_id, r.place) for r in plan_rows(plan)] == [
        ("", "nocap", "s1", "anchor"), ("F1", "fig", "", "word")]


def test_figure_rows_of_raw_float_are_in_docx_order(journal, meta, tmp_path):
    """図・表の一覧（figure_rows）は、図形ごとの図・表を docx の順に返す（中身をそのまま出した図形でも）。FloatInfo.nodes も同じ。"""
    res = run(tmp_path, meta, journal, "ambiguous")
    plan = res.plan
    rows = [(r.fid, r.kind, r.label, r.float_id, r.place) for r in plan_rows(plan)]
    assert rows == [("T1", "table", "", "s1", "mechanical"), ("T2", "table", "表1", "s1", "mechanical"),
                    ("T3", "table", "表2", "s1", "mechanical")]
    assert [n.tid for n in plan.floats["s1"].nodes] == ["T1", "T2", "T3"]
    res = run(tmp_path, meta, journal, "two_figs", name="two")
    assert [(r.fid, r.label, r.key, r.float_id) for r in plan_rows(res.plan)] == [
        ("F1", "図1", "fig01", "s1"), ("F2", "図2", "fig02", "s1")]
    assert [n.fid for n in res.plan.floats["s1"].nodes] == ["F1", "F2"]


def _make(tmp_path, variant):
    path = tmp_path / f"{variant}.docx"
    if not path.exists():
        mf.make_float_figs(path, variant)
    return path


def plan_rows(plan):
    from jasme_jats.structure import figure_rows
    return figure_rows(plan)
