"""浮動配置の図表（テキストボックス・グループ図形）: 機械的な配置、AI による位置と組み合わせの指定、AI が必要なときの中止。"""
import json

import pytest
from lxml import etree

from conftest import DATA, FLOAT
from jasme_jats.ai_assist import AIOutcome, build_request, float_placements
from jasme_jats.cli import main as cli_main
from jasme_jats.model import Atom, Float, Layout, Para
from jasme_jats.pipeline import AIRequiredError, Options, _mechanical, convert
from jasme_jats.structure import FigNode, Sec

RESPONSE = (DATA / "ai_response_sample_float.json").read_text(encoding="utf-8")
XLINK = "http://www.w3.org/1999/xlink"


def load(res):
    return etree.fromstring(res.xml_path.read_bytes().split(b"\n", 2)[2])


def body_sequence(root):
    """本文の要素の並び（段落は文字の冒頭 10 字、図・表は ID）。"""
    out = []
    for el in root.find("body").iter("p", "fig", "table-wrap"):
        if el.tag in ("fig", "table-wrap"):
            if el.get("id"):
                out.append(el.get("id"))
        elif el.getparent().tag in ("sec", "body"):
            out.append("".join(el.itertext())[:10])
    return out


def after(seq, head, n=1):
    i = next(k for k, x in enumerate(seq) if x.startswith(head))
    return seq[i + 1:i + 1 + n]


def test_ai_is_required_when_a_float_cannot_be_placed(journal, meta, tmp_path):
    with pytest.raises(AIRequiredError) as e:
        convert(FLOAT, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    assert [f.float.fid for f in e.value.floats] == ["s1", "s2", "s3"]      # s4 は機械的に配置できる
    assert "AI による補完を「使わない」設定では変換できません" in str(e.value)
    assert not (tmp_path / "jasme.zip").exists()
    # コマンドラインは終了コード 2 で止まる
    assert cli_main([str(FLOAT), "--out", str(tmp_path / "cli")]) == 2


def test_mechanical_placement_and_request(journal):
    doc, plan, linker = _mechanical(FLOAT, journal)
    assert {fid: i.mode for fid, i in plan.floats.items()} == {"s1": "unplaced", "s2": "unplaced", "s3": "unplaced",
                                                              "s4": "mechanical"}
    # 位置を決められない図表は本文の冒頭（最初の章の前）に仮に置く。中身が単純なら組にする（s1: 表と図1、s3: 画像と図2）、
    # 単純でなければ中身をそのまま（s2: 画像とキャプションが並んだ表）
    k = next(i for i, n in enumerate(plan.body) if isinstance(n, Sec))
    head = plan.body[:k]
    assert [(type(n).__name__, n.caption.src if n.caption else None) for n in head] == [
        ("FigNode", "d16"), ("FigNode", "d24"), ("TableNode", None)]
    assert [t.tid for t in head[0].tables] == ["t2"] and [i.image_id for i in head[1].extra_images] == ["img3"]
    assert head[2].table.tid == "t3"
    # s4: 図の左上がアンカー段落の左上にあるので、画像とキャプションを組にしてアンカー段落（d27）の前に置く
    sec = plan.body[k]
    kinds = [type(n).__name__ if not isinstance(n, FigNode) else f"Fig:{n.caption.src}" for n in sec.children]
    i = kinds.index("Fig:d29")
    assert sec.children[i + 1].para.src == "d27"
    text, images = build_request(plan, linker)
    unplaced = text.split("# 位置を決められなかった図表", 1)[1].split("# 位置を機械的に決めた図表", 1)
    assert all(f"[{fid}]" in unplaced[0] for fid in ("s1", "s2", "s3")) and "[s4]" not in unplaced[0]
    assert "[s4]" in unplaced[1] and "変更不可" in text
    assert "行数による推定: 図の左上の直上の本文は段落 [d17]" in unplaced[0]       # d13 も d17 も 2 行、図は 3.6 行目
    assert "表 t3" in unplaced[0] and "[d19]⟦画像 img1" in unplaced[0]
    assert {"img1", "img2", "img3"} <= {i.image_id for i in images}      # 図形の中の画像を AI に見せる


def test_ai_placements_are_validated_and_applied(journal, meta, tmp_path):
    res = convert(FLOAT, meta, journal, Options(out_dir=tmp_path, ai_mode="manual", ai_response=RESPONSE,
                                                convert_metafiles=False))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and res.jstage_issues == []
    assert res.plan.unplaced_floats == []
    root = load(res)
    figs = {f.get("id"): f for f in root.iter("fig") if f.get("id")}
    cap = {k: "".join(f.find("caption").itertext()) for k, f in figs.items()}
    assert cap == {"F1": "図1　表で組んだ問題", "F2": "図2　グループ図形の図（出典：架空の教科書）",
                   "F3": "図3　面積図", "F4": "図4　樹形図", "F5": "図5　位置が決まる図"}
    assert figs["F1"].find("table-wrap/table") is not None                # 表で組んだ図
    assert [len(figs[k].findall("graphic")) for k in ("F2", "F3", "F4", "F5")] == [1, 1, 1, 1]
    assert root.find(".//inline-graphic") is None                         # グループ図形の画像を段落に残さない
    # 指定した段落の直後に置く（s4 は機械的にアンカー段落の前）
    seq = body_sequence(root)
    assert after(seq, "図3と図4は") == ["F1"]
    assert after(seq, "図2は教科書の") == ["F2"]
    assert after(seq, "以上のように", 3) == ["F3", "F4", "F5"]
    assert after(seq, "F5") == ["図5は位置が機械的に"]
    # 機械的に配置した図形の変更と、図形の中の段落への set_role は採用しない
    why = {op["src"]: reason for op, reason in res.ai.rejected}
    assert "機械的に決めた" in why["s4"] and "placements" in why["d16"]
    acc = [d.message for _, d in res.ai.accepted]
    assert sum("テキストボックス・グループ図形" in m for m in acc) == 3
    report = res.report_path.read_text(encoding="utf-8")
    assert "図表の位置と組み合わせ" in report


def test_missing_placement_is_reported_after_ai(journal, meta, tmp_path):
    data = json.loads(RESPONSE)
    data["placements"] = [p for p in data["placements"] if p["float"] != "s2"]
    res = convert(FLOAT, meta, journal, Options(out_dir=tmp_path, ai_mode="manual", ai_response=json.dumps(data),
                                                convert_metafiles=False))
    assert res.fidelity.ok and res.dtd_valid and res.jstage_issues == []
    assert res.plan.unplaced_floats == ["s2"]
    assert any(u[0] == "float" and "手作業" in u[3] for u in res.unresolved_after)
    # AI による補完でも位置が決まらなかった図表は本文の冒頭に置き、手作業で直すようレポートに出す
    first = load(res).find("body")[0]
    assert first.tag == "table-wrap" and "図3" in "".join(first.itertext())
    report = res.report_path.read_text(encoding="utf-8")
    assert "要対応: 位置を決められなかった図表が 1 件" in report and "手作業で正しい位置" in report
    assert "本文の冒頭に仮に置いた図表" in report.split("## 13.")[1]
    path = tmp_path / "resp.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert cli_main([str(FLOAT), "--out", str(tmp_path / "cli"), "--ai", "manual", "--ai-response", str(path)]) == 1


def test_unplaced_simple_float_is_paired_at_body_start(journal, meta, tmp_path):
    data = json.loads(RESPONSE)
    data["placements"] = [p for p in data["placements"] if p["float"] != "s1"]
    res = convert(FLOAT, meta, journal, Options(out_dir=tmp_path, ai_mode="manual", ai_response=json.dumps(data),
                                                convert_metafiles=False))
    assert res.fidelity.ok and res.dtd_valid
    first = load(res).find("body")[0]
    assert first.tag == "fig" and first.get("id") == "F1" and first.find("table-wrap/table") is not None
    assert "F1" in res.forced_floats[0] and "図1" in res.forced_floats[0]


def test_manual_mode_before_response_places_floats_at_body_start(journal, meta, tmp_path):
    res = convert(FLOAT, meta, journal, Options(out_dir=tmp_path, ai_mode="manual", convert_metafiles=False))
    assert res.fidelity.ok and res.dtd_valid
    assert res.forced_floats == []                          # AI の回答を反映する前は「手作業で直す」ではない
    assert "本文の冒頭に仮に置いています" in res.output_note
    assert all("AI の回答を反映すると配置される" in u[3] for u in res.unresolved_after if u[0] == "float")


@pytest.mark.parametrize("bad, why", [
    ({"float": "s1", "after": "d16", "items": [{"kind": "fig", "caption": ["d16"], "body": ["t2"]}]}, "本文の段落ではない"),
    ({"float": "s1", "after": "d13", "items": [{"kind": "table", "caption": ["d16"], "body": ["d14"]}]}, "表 1 つ"),
    ({"float": "s1", "after": "d13", "items": [{"kind": "fig", "caption": ["d16"], "body": ["d14"]}]}, "画像以外の文字"),
    ({"float": "s1", "after": "d13", "items": [{"kind": "fig", "caption": ["d24"], "body": ["t2"]}]}, "図形 s1 の中にない"),
    ({"float": "s2", "after": "d18", "items": [{"kind": "fig", "caption": ["d21"], "body": ["img1", "d19"]}]}, "2 回"),
    ({"float": "s2", "after": "d18", "items": [{"kind": "fig", "caption": ["d21"], "body": ["t3"]}]}, "両方"),
    ({"float": "s9", "after": "d13", "items": [{"kind": "fig", "caption": [], "body": ["t2"]}]}, "ない"),
])
def test_invalid_placements_are_rejected(journal, bad, why):
    doc, plan, linker = _mechanical(FLOAT, journal)
    out = AIOutcome(mode="manual")
    assert float_placements({"placements": [dict(bad, reason="", confidence="低")]}, plan, out) == {}
    assert why in out.rejected[0][1]


def test_estimate_top_left_counts_lines():
    from jasme_jats.floats import at_anchor, estimate_top_left
    lay = Layout(columns=2, column_width_cm=8.7, line_pitch_cm=0.5, chars_per_line=20)
    seq = [Para(src=f"d{k}", atoms=[Atom(kind="text", text="あ" * 39)]) for k in (1, 2, 3)]   # 各 2 行
    fl = Float(fid="s1", anchor_src="d1", h_from="column", h_offset_cm=0.0, v_from="paragraph", v_offset_cm=0.75)
    assert estimate_top_left(fl, lay, seq, "d0")[0] == "d1"        # 1.5 行目（d1 の途中）→ 直上の本文は d1
    fl.v_offset_cm = 1.0
    assert estimate_top_left(fl, lay, seq, "d0")[0] == "d1"        # 2 行目 = d2 の先頭 → 直上は d1 の最後の行
    fl.v_offset_cm = 1.5
    assert estimate_top_left(fl, lay, seq, "d0")[0] == "d2"        # 3 行目（d2 の 2 行目）→ 直上は d2
    fl.v_offset_cm = 0.1
    assert estimate_top_left(fl, lay, seq, "d0")[0] == "d0" and at_anchor(fl, lay)
    fl.h_offset_cm = 9.0                                           # 右隣の段: 推定しない
    assert estimate_top_left(fl, lay, seq, "d0") is None and not at_anchor(fl, lay)
