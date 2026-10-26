"""浮動配置の図表（テキストボックス・グループ図形）: 機械的な配置、AI による位置と組み合わせの指定、AI が必要なときの中止、
位置を決められない図表の仮の位置（アンカー段落の後ろ・本文の最後）、途中で切れた AI の回答の位置の指定の反映。"""
import json

import pytest
from lxml import etree

import make_fixtures as mf
from conftest import DATA, FLOAT, FLOAT_TEXT, META_EXAMPLE, PLACE
from jasme_jats.ai_assist import AIOutcome, build_request, float_placements
from jasme_jats.cli import main as cli_main
from jasme_jats.model import Atom, Float, Layout, Para
from jasme_jats.pipeline import AIRequiredError, Options, _mechanical, convert
from jasme_jats.structure import FigNode, PNode, Sec, TableNode

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


def node_sequence(nodes):
    """本文の要素の並び（段落は段落 ID、図はキャプションの段落 ID、表は表 ID）。"""
    out = []
    for n in nodes:
        if isinstance(n, Sec):
            out += ["sec"] + node_sequence(n.children)
        elif isinstance(n, FigNode):
            out.append(f"fig:{n.caption.src if n.caption else '-'}")
        elif isinstance(n, TableNode):
            out.append(f"table:{n.table.tid if n.table else '-'}")
        elif isinstance(n, PNode):
            out.append(n.para.src)
    return out


def test_mechanical_placement_and_request(journal):
    doc, plan, linker = _mechanical(FLOAT, journal)
    assert {fid: i.mode for fid, i in plan.floats.items()} == {"s1": "unplaced", "s2": "unplaced", "s3": "unplaced",
                                                              "s4": "mechanical"}
    # 位置を決められない図表は、AI の回答を反映するまで、アンカー段落のすぐ後ろに仮に置く（本文の冒頭には置かない）。
    # 中身は機械的に組めれば組む（s1: 表と図1、s2: 表のセルの画像とキャプションで図3・図4、s3: 画像と図2）
    assert isinstance(plan.body[0], Sec)
    seq = node_sequence(plan.body)
    assert after(seq, "d13") == ["fig:d16"] and after(seq, "d18", 2) == ["fig:d21", "fig:d22"]
    assert after(seq, "d23") == ["fig:d24"]
    assert {fid: (i.where, plan.float_place(fid)) for fid, i in plan.floats.items() if i.mode == "unplaced"} == {
        "s1": ("anchor", "段落「この段落に図1のテキストボックスが結び付」の後ろ"),
        "s2": ("anchor", "段落「この段落には図3と図4のテキストボックス」の後ろ"),
        "s3": ("anchor", "段落「図2は教科書の見開きページであり，グルー」の後ろ")}
    figs = {f.caption.src: f for f in plan.figures}
    assert [t.tid for t in figs["d16"].tables] == ["t2"] and [i.image_id for i in figs["d24"].extra_images] == ["img3"]
    assert [ip.src for ip in figs["d21"].image_paras] == ["d19"] and [ip.src for ip in figs["d22"].image_paras] == ["d20"]
    assert any("指定がなければ段落「この段落に図1のテキストボックスが結び付」の後ろに仮に置く" in d.message
               for d in plan.decisions)
    # s4: 図の左上がアンカー段落の左上にあるので、画像とキャプションを組にしてアンカー段落（d27）の前に置く
    assert after(seq, "fig:d29") == ["d27"]
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


def test_link_targets_follow_figures_after_rebuild(journal, meta, tmp_path):
    # AI は 1 回目の組み立ての ID（依頼文の ID。図2 は、仮に置いた図表の並びで F4）でリンク先を指定する。配置を反映して
    # 組み直すと図2 は F2 になるので、リンク先を組み直した後の ID に読み替える（読み替えないと F4 = 図4 にリンクしてしまう）
    _, first, _ = _mechanical(FLOAT, journal)
    before = next(f.fid for f in first.figures if f.caption is not None and f.caption.plain().startswith("図2"))
    data = json.loads(RESPONSE)
    data["operations"].append({"op": "link_figure", "src": "d23", "text": "教科書の見開きページ", "occurrence": 1,
                               "target": before, "role": "", "image": "", "mathml": "", "surname": "", "given": "",
                               "reason": "「教科書の見開きページ」は図2", "confidence": "中"})
    res = convert(FLOAT, meta, journal, Options(out_dir=tmp_path, ai_mode="manual", ai_response=json.dumps(data),
                                                convert_metafiles=False))
    assert res.fidelity.ok and res.dtd_valid
    root = load(res)
    x = next(x for x in root.iter("xref") if x.text == "教科書の見開きページ")
    assert before == "F4" and x.get("rid") == "F2"
    assert "".join(root.find(".//fig[@id='F2']/caption").itertext()).startswith("図2")


def test_missing_placement_is_reported_after_ai(journal, meta, tmp_path, capsys):
    data = json.loads(RESPONSE)
    data["placements"] = [p for p in data["placements"] if p["float"] != "s2"]
    res = convert(FLOAT, meta, journal, Options(out_dir=tmp_path, ai_mode="manual", ai_response=json.dumps(data),
                                                convert_metafiles=False))
    assert res.fidelity.ok and res.dtd_valid and res.jstage_issues == []
    assert res.plan.unplaced_floats == ["s2"]
    assert any(u[0] == "float" and "手作業" in u[3] for u in res.unresolved_after)
    # AI による補完でも位置が決まらなかった図表は、アンカー段落のすぐ後ろに仮に置き（本文の冒頭には置かない）、手作業で直すよう
    # レポートに出す。中身は機械的に組む（表のセルの画像とキャプションで図3・図4）
    root = load(res)
    assert root.find("body")[0].tag == "sec"
    seq = body_sequence(root)
    assert after(seq, "この段落には図3と図", 2) == ["F2", "F3"]
    assert [c[:2] for c in ("".join(root.find(f".//fig[@id='{k}']/caption").itertext()) for k in ("F2", "F3"))] == ["図3", "図4"]
    place = "段落「この段落には図3と図4のテキストボックス」の後ろ"
    assert res.forced_floats == [f"「図3\u3000面積図」「図4\u3000樹形図」: XML の{place}にある F2・F3"]
    report = res.report_path.read_text(encoding="utf-8")
    assert "本文の冒頭" not in report
    assert "要対応: 位置を決められなかった図表が 1 件" in report and "手作業で正しい位置" in report
    assert "アンカー段落）のすぐ後ろ（箇条書き・引用の途中なら、その終わり）か、本文の最後に仮に置いています" in report
    assert "1 件（アンカー段落の後ろに仮に配置）" in report
    assert f"AI による補完でも位置を決められなかったため、{place}に仮に置いた" in report.split("## 3.")[1]
    assert "仮の位置（アンカー段落の後ろ・本文の最後）に置いた図表" in report.split("## 14.")[1]
    from jasme_jats.report import NEEDS_ACTION, actions
    assert [a.key for a in actions(res) if a.level == NEEDS_ACTION] == ["forced"] and res.needs_action
    path = tmp_path / "resp.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    capsys.readouterr()
    # 仮に置いた図表は要対応で 1（--meta を付けて、書誌情報がないことによる要対応〈EMSGM230E〉と分ける）
    assert cli_main([str(FLOAT), "--meta", str(META_EXAMPLE), "--out", str(tmp_path / "cli"), "--ai", "manual",
                     "--ai-response", str(path)]) == 1
    # コマンドラインでも、図表ごとに、キャプションと XML の中の位置・ID を 1 行ずつ示す（レポートの冒頭と同じ）
    err = capsys.readouterr().err
    assert "要対応: J-STAGE のアップロード時チェック" not in err
    assert "要対応: 位置を決められなかった図表 1 件を、仮の位置（アンカー段落の後ろ、または本文の最後）に置きました" in err
    assert f"\n  「図3\u3000面積図」「図4\u3000樹形図」: XML の{place}にある F2・F3" in err


def test_unplaced_simple_float_is_paired_after_anchor(journal, meta, tmp_path):
    data = json.loads(RESPONSE)
    data["placements"] = [p for p in data["placements"] if p["float"] != "s1"]
    res = convert(FLOAT, meta, journal, Options(out_dir=tmp_path, ai_mode="manual", ai_response=json.dumps(data),
                                                convert_metafiles=False))
    assert res.fidelity.ok and res.dtd_valid
    root = load(res)
    assert root.find("body")[0].tag == "sec"
    assert after(body_sequence(root), "この段落に図1のテキ") == ["F1"]          # アンカー段落のすぐ後ろ
    fig = root.find(".//fig[@id='F1']")
    assert fig.find("table-wrap/table") is not None and "".join(fig.find("caption").itertext()).startswith("図1")
    assert res.forced_floats == ["「図1\u3000表で組んだ問題」: XML の段落「この段落に図1のテキストボックスが結び付」の後ろにある F1"]


def test_manual_mode_before_response_places_floats_after_anchor(journal, meta, tmp_path):
    res = convert(FLOAT, meta, journal, Options(out_dir=tmp_path, ai_mode="manual", convert_metafiles=False))
    assert res.fidelity.ok and res.dtd_valid
    assert res.forced_floats == []                          # AI の回答を反映する前は「手作業で直す」ではない
    assert "AI の回答を反映するまで、図が結び付いている段落（アンカー段落）のすぐ後ろ" in res.output_note
    assert all("AI の回答を反映すると配置される" in u[3] for u in res.unresolved_after if u[0] == "float")
    detail = {u[1]: u[3] for u in res.unresolved_after if u[0] == "float"}
    assert "（今は段落「この段落に図1のテキストボックスが結び付」の後ろに仮に置いている）" in detail["d13"]
    seq = body_sequence(load(res))
    assert after(seq, "この段落に図1のテキ") == ["F1"] and after(seq, "この段落には図3と図", 2) == ["F2", "F3"]
    assert after(seq, "図2は教科書の") == ["F4"]
    report = res.report_path.read_text(encoding="utf-8")
    assert "本文の冒頭" not in report and "3 件（アンカー段落の後ろに仮に配置）" in report


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


def test_image_and_text_in_one_paragraph_of_a_float(journal, meta, tmp_path):
    """図形の中で画像と文字が同じ段落にある図: 画像は図の <graphic> に入れ、段落の文字は図の直後の <p> に出す。
    AI を使わない設定でも止まらない。キャプションのない図形は、これまでどおり画像も文字も 1 つの <p> に出す。"""
    res = convert(FLOAT_TEXT, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    fid = res.fidelity
    assert fid.ok and fid.final_ok and res.dtd_valid and res.jstage_issues == [], (fid.missing, fid.conflicts)
    assert res.plan.unplaced_floats == [] and not any("説明文" in t for _, _, t in fid.excluded)
    root = load(res)
    mixed = next(p for p in res.plan.paras.values() if p.text_only().startswith("説明文：図1"))
    fig = root.find(".//fig[@id='F1']")
    assert [g.get(f"{{{XLINK}}}href") for g in fig.findall("graphic")] == [mixed.images[0].export_name]
    assert "説明文" not in "".join(fig.itertext())
    nxt = fig.getnext()
    assert nxt.tag == "p" and "".join(nxt.itertext()) == "説明文：図1の画像と同じ段落にある文字。"
    assert nxt.find("inline-graphic") is None                            # 画像は図に移した（段落の中に二重に出さない）
    assert after(body_sequence(root), "試験（2024）", 3) == ["F1", "説明文：図1の画像と", "この段落に図1のテキ"]
    assert any("画像と文字が同じ段落にある" in d.message and d.src == mixed.src for d in res.plan.decisions)
    # キャプションのない図形: これまでどおり（画像も文字も 1 つの <p>。図にはしない）
    p = next(p for p in root.iter("p") if "キャプションのない図形の文字" in "".join(p.itertext()))
    assert p.find("inline-graphic") is not None and len(list(root.iter("fig"))) == 1
    assert len(res.images) == 2


def test_text_in_figure_image_paragraph_is_not_excluded(journal, meta):
    """図の画像の段落に空白以外の文字があっても（構造の組み立ての誤り）、書き出しでは除外にせず、警告に記録する。
    その文字は XML に出ないので、不変性チェックで出力漏れとして不合格になる（黙って落ちない）。"""
    from jasme_jats.builder import build
    from jasme_jats.fidelity import verify
    from jasme_jats.structure import PNode
    _, plan, _ = _mechanical(FLOAT_TEXT, journal)
    mixed = next(p for p in plan.paras.values() if p.text_only().startswith("説明文：図1"))
    # 0.18.1 の組み方を模す: 画像と文字が同じ段落を図 F1 の画像の段落にし、図の直後の段落からは外す
    [fig] = [f for f in plan.figures if f.fid == "F1"]
    fig.image_paras.append(mixed)
    sec = next(s for s in plan.body if fig in s.children)
    sec.children = [n for n in sec.children if not (isinstance(n, PNode) and n.para is mixed)]
    root, info = build(plan, meta, journal)
    assert not any(e.src == mixed.src for e in info.exclusions)
    assert any(f"画像の段落 {mixed.src} に画像以外の文字がある" in w and "変換ツールの不具合" in w for w in info.warnings)
    res = verify(FLOAT_TEXT, root, plan.exclusions + info.exclusions)
    assert not res.ok and mixed.src in [s for s, _ in res.missing]


@pytest.mark.parametrize("by", ["image", "paragraph"])
def test_ai_placement_of_image_and_text_in_one_paragraph(journal, meta, tmp_path, by):
    """位置を決められない図形で、画像と文字が同じ段落の画像（またはその段落）を AI が図の本体に指定した場合も、
    画像は図に入れ、段落の文字は図の直後の <p> に出す。"""
    path = tmp_path / "float_text_down.docx"
    mf.make_float_text(path, down_cm=2)          # 図1 のテキストボックスをアンカー段落から 2 cm 下にずらす
    with pytest.raises(AIRequiredError):
        convert(path, meta, journal, Options(out_dir=tmp_path / "none", convert_metafiles=False))
    doc, plan, _ = _mechanical(path, journal)
    paras = list(plan.paras.values())
    mixed = next(p for p in paras if p.text_only().startswith("説明文：図1"))
    cap = next(p for p in paras if p.text_only().startswith("図1\u3000"))
    anchor = next(p for p in paras if p.text_only().startswith("この段落に図1"))
    body = [mixed.images[0].image_id] if by == "image" else [mixed.src]
    resp = {"operations": [], "notes": [], "placements": [{"float": mixed.float_id, "after": anchor.src, "items": [
        {"kind": "fig", "caption": [cap.src], "body": body}], "reason": "試験", "confidence": "中"}]}
    res = convert(path, meta, journal, Options(out_dir=tmp_path / by, ai_mode="manual",
                                               ai_response=json.dumps(resp, ensure_ascii=False), convert_metafiles=False))
    assert res.ai.rejected == [] and res.plan.unplaced_floats == []
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    root = load(res)
    assert after(body_sequence(root), "この段落に図1", 2) == ["F1", "説明文：図1の画像と"]
    fig = root.find(".//fig[@id='F1']")
    assert len(fig.findall("graphic")) == 1 and fig.getnext().find("inline-graphic") is None
    assert any(f"画像と文字が同じ段落 {mixed.src}" in d.message for _, d in res.ai.accepted)


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


# ---------------------------------------------------------------------------- 位置を決められない図表の仮の置き場所（決定事項 21）
# sample_b3_place: s1（図1）・s2（図3）・s3（図2）・s4（図4。空の段落に結び付いている）は、どれも位置を決められない
def src_of(plan, head):
    """文字が head で始まる段落の ID。"""
    return next(src for src, p in plan.paras.items() if p.plain().startswith(head))


def captions_sequence(root):
    """本文の要素の並び（図はキャプションの番号「図1」など）。"""
    caps = {f.get("id"): "".join(f.find("caption").itertext())[:2] for f in root.iter("fig") if f.get("id")}
    return [caps.get(x, x) for x in body_sequence(root)]


def place_response(journal, after_head, extra=()):
    """sample_b3_place の s1 の位置を、文字が after_head（と extra）で始まる段落の後ろと答える回答（ほかの図形は答えない）。"""
    _, plan, _ = _mechanical(PLACE, journal)
    cap = src_of(plan, "図1\u3000一つ目")
    body = [q.src for q in plan.floats["s1"].paras if q.images]
    pls = [{"float": "s1", "after": src_of(plan, h), "items": [{"kind": "fig", "caption": [cap], "body": body}],
            "reason": "試験の回答", "confidence": "低"} for h in [after_head, *extra]]
    return json.dumps({"placements": pls, "operations": [], "notes": []}, ensure_ascii=False), plan


def test_unplaced_floats_go_after_anchor_in_number_order(journal, meta, tmp_path):
    """手動モードで AI の回答を貼り戻す前: 位置を決められない図表はアンカー段落のすぐ後ろ。同じ段落に結び付いた図表は
    キャプションの番号順（docx の順は図3・図2）。空の段落に結び付いた図表は、前の文字のある段落の名前で示す。"""
    res = convert(PLACE, meta, journal, Options(out_dir=tmp_path, ai_mode="manual", convert_metafiles=False))
    fid = res.fidelity
    assert fid.ok and fid.final_ok and res.dtd_valid and res.jstage_issues == [] and res.lost_images == []
    plan = res.plan
    assert plan.unplaced_floats == ["s1", "s2", "s3", "s4"]
    assert {f: plan.floats[f].where for f in plan.unplaced_floats} == dict.fromkeys(plan.unplaced_floats, "anchor")
    root = load(res)
    assert root.find("body")[0].tag == "sec"                         # 本文の冒頭には置かない
    seq = captions_sequence(root)
    assert after(seq, "この段落に図1のテキ") == ["図1"]
    assert after(seq, "この段落に図3と図2", 3) == ["図2", "図3", "図4"]   # 図4 は、その後ろの空の段落に結び付いている
    assert plan.float_place("s4") == "段落「この段落に図3と図2のテキストボックスが」の後ろ"
    assert res.forced_floats == []
    report = res.report_path.read_text(encoding="utf-8")
    assert "本文の冒頭" not in report and "4 件（アンカー段落の後ろに仮に配置）" in report


FIRST = "この項目に図1のテキストボックスが結び付いている。"


@pytest.mark.parametrize("variant, items, last, groups", [
    ("list", ["箇条書きの一つ目の項目である。", FIRST, "箇条書きの三つ目の項目である。"], "箇条書きの三つ目の項目である。", 1),
    ("quote", ["引用の一つ目の段落である。", "この引用の段落に図1のテキストボックスが結び付いている。", "引用の三つ目の段落である。"],
     "引用の三つ目の段落である。", 1),
    ("blank_list", ["箇条書きの一つ目の項目である。", "箇条書きの二つ目の項目である。"], "箇条書きの二つ目の項目である。", 1),
    ("quote_blank", ["引用の一つ目の段落である。", "この引用の段落に図1のテキストボックスが結び付いている。",
                     "引用の三つ目の段落である。"], "引用の三つ目の段落である。", 1),
    ("two_lists", [FIRST, "一つ目の箇条書きの二つ目の項目である。"], "一つ目の箇条書きの二つ目の項目である。", 2),
    ("list_heading", [FIRST, "箇条書きの二つ目の項目である。"], "箇条書きの二つ目の項目である。", 1),
    ("list_image", [FIRST, "二つ目の項目には画像と文字がある。", "箇条書きの三つ目の項目である。"], "箇条書きの三つ目の項目である。", 1),
    ("list_math", [FIRST, "箇条書きの二つ目の項目である。"], "箇条書きの二つ目の項目である。", 2),
    ("list_textbox", [FIRST, "箇条書きの二つ目の項目である。"], "箇条書きの二つ目の項目である。", 1),
    ("other_list", ["箇条書きの一つ目の項目である。", FIRST], FIRST, 2)])
def test_unplaced_float_does_not_split_list_or_quote(journal, meta, tmp_path, variant, items, last, groups):
    """アンカー段落が、続いた箇条書きの項目・引用の段落の途中にあるときは、その箇条書き・引用の最後の段落の後ろに仮に置く
    （箇条書き・引用を 2 つに分けない。分けると、図表を手作業で移しても分かれたまま残る）。空のアンカー段落が箇条書きの
    項目の間にあるときも同じ。間の空の段落は飛ばし（quote_blank）、別の番号の定義の箇条書き（other_list）、箇条書き・引用で
    ない段落（two_lists の本文の段落）、見出しと推定する段落（list_heading）、画像だけの項目（list_image。図になる）、
    別行数式だけの項目（list_math。数式になる）、浮動配置でないテキストボックスの中の段落（list_textbox。XML に出さない）の
    前で止める。画像と文字が同じ段落の項目は、箇条書きの項目として数える。AI が指定した位置はずらさない。"""
    path = tmp_path / f"place_{variant}.docx"
    mf.make_b3_place(path, variant=variant)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", ai_mode="manual", convert_metafiles=False))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and res.lost_images == []
    assert res.plan.unplaced_floats == ["s1", "s2", "s3", "s4"] and res.plan.floats["s1"].where == "anchor"
    body = load(res).find("body")
    tag = "disp-quote" if variant.startswith("quote") else "list"
    found = list(body.iter(tag))
    assert len(found) == groups
    group = found[0]
    assert ["".join(p.itertext()) for p in group.iter("p")] == items           # 1 つの箇条書き・引用のまま
    nxt = group.getnext()
    assert nxt.tag == "fig" and "".join(nxt.find("caption").itertext()).startswith("図1")
    assert res.plan.float_place("s1") == f"段落「{last[:20]}」の後ろ"
    detail = next(u[3] for u in res.unresolved_after if u[0] == "float" and "図1" in u[2])
    assert f"今は段落「{last[:20]}」の後ろに仮に置いている" in detail
    # AI が箇条書き・引用の途中の段落の後ろを指定したときは、指定どおり（ずらさない）
    _, first, _ = _mechanical(path, journal)
    anchor = first.floats["s1"].float.anchor_src
    cap = next(q.src for q in first.floats["s1"].paras if q.plain().startswith("図1"))
    imgs = [q.src for q in first.floats["s1"].paras if q.images]
    resp = json.dumps({"placements": [{"float": "s1", "after": anchor, "items": [{"kind": "fig", "caption": [cap], "body": imgs}],
                                       "reason": "試験の回答", "confidence": "低"}], "operations": [], "notes": []})
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "ai", ai_mode="manual", ai_response=resp,
                                               convert_metafiles=False))
    assert res.plan.floats["s1"].mode == "ai" and res.fidelity.ok and res.dtd_valid
    if variant != "blank_list":
        # 指定された段落の直後に置くので、アンカー段落が箇条書き・引用の途中なら 2 つに分かれる（今までどおり。other_list の
        # アンカー段落は、箇条書きの最後の項目）
        assert len(list(load(res).find("body").iter(tag))) == groups + (variant != "other_list")


def test_float_row_location_for_empty_anchor(journal, meta, tmp_path):
    """3 章の「図表の位置」の場所の欄: アンカー段落が空の段落（出力しないので場所がない）なら、その前の段落の場所を示す
    （段落の ID をそのまま出さない）。"""
    res = convert(PLACE, meta, journal, Options(out_dir=tmp_path, ai_mode="manual", convert_metafiles=False))
    plan = res.plan
    anchor = plan.floats["s4"].float.anchor_src
    assert not plan.locations.get(anchor)
    [row] = [u for u in res.unresolved_after if u[0] == "float" and "図4" in u[2]]
    assert row[1] != anchor and plan.locations.get(row[1])
    assert plan.paras[row[1]].plain().startswith("この段落に図3と図2のテキストボックスが")
    chapter3 = res.report_path.read_text(encoding="utf-8").split("## 3.")[1].split("## 4.")[0]
    assert f"| {anchor} |" not in chapter3 and f"| {plan.locations[row[1]]} |" in chapter3


def test_provisional_target_and_place():
    """仮に置く位置の決め方（structure.Classifier.provisional_target）と、その説明（ArticlePlan.float_place）。"""
    from jasme_jats.structure import BODY_END, ArticlePlan, Classifier, FloatInfo
    fl = Float(fid="s1", anchor_src="d5")
    assert Classifier.provisional_target(fl, None, {"d5": 3}, {"d5"}) == ("anchor", "", "", 4)       # アンカー段落の後ろ
    # アンカー段落が本文の段落でない（修正計画の F で、本文の外に結び付いた図形を扱うとき）・AI が本文の外を指定した: 本文の最後
    assert Classifier.provisional_target(fl, None, {"d5": 3}, set()) == ("end", "anchor", "", BODY_END)
    assert Classifier.provisional_target(fl, {"where": "end", "after": "d30"}, {"d5": 3}, {"d5"}) == (
        "end", "ai", "d30", BODY_END)
    plan = ArticlePlan(body_seq=["d4", "d5"], paras={"d4": Para(src="d4", atoms=[Atom(kind="text", text="前の段落")]),
                                                    "d5": Para(src="d5", atoms=[Atom(kind="text", text="\u3000")])})
    plan.floats["s1"] = FloatInfo(float=fl, where="anchor")
    assert plan.float_place("s1") == "段落「前の段落」の後ろ"            # 空白だけのアンカー段落は、前の段落で示す
    plan.floats["s1"].where = "end"
    assert plan.float_place("s1") == "本文の最後"


@pytest.mark.parametrize("head, region", [("1) 架空の注", "注"), ("試験六郎（2024）", "引用文献"),
                                          ("Small article abstract", "英文の部分")])
def test_ai_placement_after_back_matter_goes_to_body_end(journal, meta, tmp_path, head, region):
    """AI が本文の外（注・引用文献・英文の部分）の段落の後ろを指定した図表: 指定は今までどおり採用しないが、図表は
    本文の冒頭ではなく本文の最後（最後の章の最後）に仮に置き、要対応として知らせる。"""
    resp, first = place_response(journal, head)
    res = convert(PLACE, meta, journal, Options(out_dir=tmp_path, ai_mode="manual", ai_response=resp,
                                                convert_metafiles=False))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and res.lost_images == []
    fi, after_src = res.plan.floats["s1"], src_of(first, head)
    assert fi.mode == "unplaced" and (fi.where, fi.end_why, fi.end_after) == ("end", "ai", after_src)
    [why] = [w for op, w in res.ai.rejected if op["src"] == "s1"]
    assert "本文の段落ではない" in why and "図表は本文の最後に仮に置いた" in why
    root = load(res)
    last = root.find("body")[-1]
    assert last.tag == "sec" and last[-1].tag == "fig" and "".join(last[-1].find("caption").itertext()).startswith("図1")
    assert captions_sequence(root)[-1] == "図1"
    detail = next(u[3] for u in res.unresolved_after if u[0] == "float" and u[1] == fi.float.anchor_src)
    assert f"AI が本文の外（{region}）の段落 {after_src} の後ろを指定したが" in detail and "本文の最後に仮に置いた" in detail
    assert res.forced_floats[0] == f"「図1\u3000一つ目の図」: XML の本文の最後にある {last[-1].get('id')}"
    report = res.report_path.read_text(encoding="utf-8")
    assert "4 件（アンカー段落の後ろ 3 件・本文の最後 1 件に仮に配置）" in report and "本文の冒頭" not in report


@pytest.mark.parametrize("head", ["仮の置き場所の検証用文書", "図3\u3000三つ目の図"])
def test_ai_placement_after_title_or_shape_stays_after_anchor(journal, meta, tmp_path, head):
    """AI が題目（和文の冒頭）や図形の中の段落の後ろを指定した図表は、本文の最後ではなく、アンカー段落の後ろに仮に置く。"""
    resp, _ = place_response(journal, head)
    res = convert(PLACE, meta, journal, Options(out_dir=tmp_path, ai_mode="manual", ai_response=resp,
                                                convert_metafiles=False))
    assert res.fidelity.ok and res.dtd_valid
    fi = res.plan.floats["s1"]
    assert fi.mode == "unplaced" and fi.where == "anchor" and fi.end_why == ""
    [why] = [w for op, w in res.ai.rejected if op["src"] == "s1"]
    assert "本文の段落ではない" in why and "本文の最後" not in why
    assert after(captions_sequence(load(res)), "この段落に図1のテキ") == ["図1"]


def test_correct_placement_after_back_matter_one_is_used(journal, meta, tmp_path):
    """同じ図形に、注の段落の後ろの指定と、正しい指定が続くときは、正しい指定を採用する（本文の最後には置かない）。"""
    resp, _ = place_response(journal, "1) 架空の注", extra=["図2と図3は同じ段落"])
    res = convert(PLACE, meta, journal, Options(out_dir=tmp_path, ai_mode="manual", ai_response=resp,
                                                convert_metafiles=False))
    assert res.plan.floats["s1"].mode == "ai" and "s1" not in res.plan.unplaced_floats
    [why] = [w for op, w in res.ai.rejected if op["src"] == "s1"]
    assert "本文の段落ではない" in why and "本文の最後" not in why
    assert after(captions_sequence(load(res)), "図2と図3は同じ段落") == ["図1"]


def test_float_anchored_outside_body_is_kept_as_before(journal, meta, tmp_path):
    """本文の外（注）の段落に結び付いた図形は、今までどおり、その領域の段落として扱う（位置を決められない図表にはしない）。
    本文の外に結び付いた図形を位置を決められない図表にするのは、修正計画の F（N7）。"""
    path = tmp_path / "outside.docx"
    mf.make_b3_place(path, outside=True)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", ai_mode="manual", convert_metafiles=False))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    assert res.plan.unplaced_floats == ["s1", "s2", "s3", "s4"] and "s5" not in res.plan.floats
    assert "図5\u3000注に結び付いた図" in "".join(load(res).find(".//fn-group").itertext())


def cut_float_response(at):
    """sample_float の模擬回答を placements を先頭にして書き、at（文字列の位置を返す関数）で切った回答。"""
    data = json.loads(RESPONSE)
    text = json.dumps({"placements": data["placements"], "operations": data["operations"], "notes": ["気づき"]},
                      ensure_ascii=False, indent=1)
    return text[:at(text)]


def test_cut_response_applies_only_finished_placements(journal, meta, tmp_path):
    """途中で切れた回答（2 つ目の placements の要素の途中）: 最後まで書かれた s1 の指定だけを読んで反映し、ほかの図表は
    アンカー段落の後ろに仮に置いて、要対応として知らせる。operations と notes は使わない。出し直しの案内は、最初から
    出し直してもらい、続きだけを貼り付けない（貼り付けても読めない）こと。"""
    resp = cut_float_response(lambda t: t.index('"float": "s2"') + 30)
    res = convert(FLOAT, meta, journal, Options(out_dir=tmp_path, ai_mode="manual", ai_response=resp,
                                                convert_metafiles=False))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid and res.lost_images == []
    assert res.ai.error == "" and "最後まで書かれていた 1 件だけを読み取って反映しました" in res.ai.partial
    assert "同じ形式で最初から出し直してください" in res.ai.partial and "続きだけを貼り付けても読めません" in res.ai.partial
    assert res.plan.floats["s1"].mode == "ai" and res.plan.unplaced_floats == ["s2", "s3"]
    assert res.ai.notes == [] and not any(op["op"] == "set_role" for op, _ in res.ai.rejected)   # operations は使わない
    seq = body_sequence(load(res))
    assert after(seq, "図3と図4は，1つの") == ["F1"]                                  # s1 は AI の指定どおり
    assert after(seq, "この段落には図3と図", 2) == ["F2", "F3"] and after(seq, "図2は教科書の") == ["F4"]
    detail = {u[1]: u[3] for u in res.unresolved_after if u[0] == "float"}
    assert "AI の回答が途中で切れていて、この図表の位置の指定を読み取れなかったため" in detail["d18"]
    report = res.report_path.read_text(encoding="utf-8")
    head, ch2, ch14 = report.split("## 2.")[0], report.split("## 2.")[1].split("## 3.")[0], report.split("## 14.")[1]
    assert "要対応: AI の回答が途中で切れていました（2 章）" in head and "AI の回答が途中で切れていました。" in ch2
    assert "AI の回答が途中で切れていた" in ch14 and "要対応: 位置を決められなかった図表が 2 件" in head
    from jasme_jats.report import NEEDS_ACTION, actions
    assert [a.key for a in actions(res) if a.level == NEEDS_ACTION] == ["partial", "forced"] and res.needs_action
    path = tmp_path / "cut.json"
    path.write_text(resp, encoding="utf-8")
    assert cli_main([str(FLOAT), "--meta", str(META_EXAMPLE), "--out", str(tmp_path / "cli"), "--ai", "manual",
                     "--ai-response", str(path)]) == 1


def test_cut_response_placements_are_validated(journal, meta, tmp_path, capsys):
    """途中で切れた回答（operations の文字列の途中）から読んだ placements も、ふつうの回答と同じく検証する
    （機械的に配置した s4 の指定は採用しない）。位置を決められない図表が残らなくても、途中で切れた回答は要対応
    （operations と notes を使っていない）で、コマンドラインは 1 を返す（0.23.0 では 0。修正計画 D）。"""
    from jasme_jats.report import NEEDS_ACTION, actions
    resp = cut_float_response(lambda t: t.index('"reason"', t.index('"operations"')) + 15)
    res = convert(FLOAT, meta, journal, Options(out_dir=tmp_path, ai_mode="manual", ai_response=resp,
                                                convert_metafiles=False))
    assert res.fidelity.ok and res.dtd_valid and res.ai.error == ""
    assert "最後まで書かれていた 4 件だけ" in res.ai.partial and res.plan.unplaced_floats == []
    assert [op["src"] for op, _ in res.ai.rejected] == ["s4"] and "機械的に決めた" in res.ai.rejected[0][1]
    assert [a.key for a in actions(res) if a.level == NEEDS_ACTION] == ["partial"] and res.needs_action
    path = tmp_path / "cut.json"
    path.write_text(resp, encoding="utf-8")
    capsys.readouterr()
    assert cli_main([str(FLOAT), "--meta", str(META_EXAMPLE), "--out", str(tmp_path / "cli"), "--ai", "manual",
                     "--ai-response", str(path)]) == 1
    assert "要対応: AI の回答が途中で切れていました。" in capsys.readouterr().err


def test_unreadable_cut_response_is_reported(journal, meta, tmp_path):
    """最初の placements の要素の途中（文字列の途中）で切れた回答: 読める指定がないので反映せず、「途中で切れている可能性」を
    案内する。位置を決められない図表は、アンカー段落の後ろに仮に置き、AI の回答を反映できなかったことを 3 章に書く。"""
    resp = cut_float_response(lambda t: t.index('"reason"') + 15)
    res = convert(FLOAT, meta, journal, Options(out_dir=tmp_path, ai_mode="manual", ai_response=resp,
                                                convert_metafiles=False))
    assert res.fidelity.ok and res.dtd_valid and res.ai.partial == ""
    assert "Unterminated string" in res.ai.error and "回答が途中で切れている可能性があります" in res.ai.error
    assert res.plan.unplaced_floats == ["s1", "s2", "s3"]
    assert after(body_sequence(load(res)), "この段落に図1のテキ") == ["F1"]
    detail = {u[1]: u[3] for u in res.unresolved_after if u[0] == "float"}
    assert all("AI の回答を反映できなかったため（2 章）" in d for d in detail.values())
