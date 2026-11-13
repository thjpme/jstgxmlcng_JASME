"""AI への依頼文のデータの部分 3: 位置を決める図・表とテキストボックスの節（修正計画 W8 の手順 16。実際の API は呼ばない）。

「# 位置を決める図・表」は、位置を聞く図形ごとに、中身（図・表の ID とキャプションの段落の全文・本文として出す段落）・仮の位置・
docx の配置（値は日本語）・推定（同じ段で、結び付いた段落を基準にした位置のときだけ。「## 本文」にない段落は前の段落に読み替える）。
位置が決まっている図形は ID を 1 行に並べ、中身は「# 位置が決まっている図・表と囲みの中身」に書く（ai_assist.float_section・
textbox_section・fixed_section）。内容はすべて架空。
"""
import re

import answers
import make_fixtures as mf
from conftest import CELLS, EDGE, FLOAT, FULL, NOTES, OUTSIDE, PLACE, STRUCTURE
from jasme_jats import ai_assist
from jasme_jats.ai_assist import (FIXED_HEADING, FLOATS_HEADING, LABELS_HEADING, UNDECIDED_HEADING, after_ids, build_request,
                                  listed_before)
from jasme_jats.floats import describe
from jasme_jats.model import Float, Layout
from jasme_jats.pipeline import Options, _mechanical, convert
from jasme_jats.structure import figure_rows


def _req(path, journal):
    _, plan, linker = _mechanical(path, journal)
    return plan, build_request(plan, linker, journal=journal)


def _section(data, heading) -> str:
    """データの節 heading（見出しの行）の中身（次の空行まで）。なければ ""。"""
    if "\n" + heading + "\n" not in data:
        return ""
    return data.split("\n" + heading + "\n", 1)[1].split("\n\n", 1)[0]


def _blocks(sec) -> dict:
    """節の中の、[s1] などで始まる図形・テキストボックスごとの行（ID → 行の文字）。"""
    out = {}
    for block in ("\n" + sec).split("\n[")[1:]:
        out[block.split("]", 1)[0]] = "[" + block
    return out


def test_contents_follow_xml_order(journal):
    # 図・表が 2 つ入った図形（s2）の「中身」は、変換ツールが組んだ図・表の順（figure_rows。XML の順）
    plan, req = _req(FLOAT, journal)
    sec = _section(req.data, FLOATS_HEADING)
    blocks = _blocks(sec)
    assert set(blocks) == set(plan.asked_floats) == {"s1", "s2", "s3"}
    for fid, block in blocks.items():
        shown = re.findall(r"(?:図|表) (F\d+|T\d+) = ", block.split("\n  仮の位置", 1)[0])
        assert shown == [r.fid for r in figure_rows(plan) if r.float_id == fid and r.caption is not None]
    assert blocks["s2"].startswith("[s2] 中身: 図 F2 = [d21]〔図キャプション〕図3　面積図\n      図 F3 = [d22]")
    # 1 つの図形の行の並び: 中身・仮の位置・docx の配置・推定
    lines = [ln.split(":", 1)[0].strip() for ln in blocks["s1"].splitlines() if not ln.startswith(" " * 6)]
    assert lines == ["[s1] 中身", "仮の位置", "docx の配置", "推定"]


def test_fixed_floats_are_listed_by_id(journal):
    # 位置が決まっている図形（mechanical・caption）は「# 位置を決める図・表」に ID を 1 行に並べるだけで、中身は答えない節に書く
    plan, req = _req(FLOAT, journal)
    sec = _section(req.data, FLOATS_HEADING)
    assert plan.floats["s4"].mode == "mechanical" and "[s4]" not in sec
    assert sec.splitlines()[-1] == "位置が決まっている図形（答えません）: s4"
    assert _section(req.data, FIXED_HEADING).startswith("[s4] 中身: 図 F5 = [d29]")
    assert "s4" not in req.asked["floats"]
    # 位置を聞く図形がなければ「# 位置を決める図・表」を出さない（表のセルで組んだ図は、中身だけを答えない節に書く）
    # 2 段にまたがる機械的な図形（s1・s3）は「# PDF を見たときだけ答える図・表」に中身を書き、ほかは答えない節に書く（W8 の 6.5 の 4）
    plan, req = _req(CELLS, journal)
    assert not plan.asked_floats and FLOATS_HEADING not in req.data and plan.wide_floats == ["s1", "s3"]
    wide = _section(req.data, ai_assist.WIDE_HEADING)
    assert all(f"[{fid}] 中身: " in wide for fid in plan.wide_floats)
    assert wide.splitlines()[-1] == "位置が決まっている図形（答えません）: s2"
    assert all(f"[{fid}] 中身: " in _section(req.data, FIXED_HEADING) for fid in plan.floats if fid not in plan.wide_floats)
    assert not any(f"[{fid}] 中身: " in _section(req.data, FIXED_HEADING) for fid in plan.wide_floats)


def test_caption_mode_float_is_id_only(journal, tmp_path):
    # 本文の図キャプションの図に含めた図形（mode caption）は、位置を聞かず、図の画像に写るとみなして除いた文字も中身に書かない
    path = tmp_path / "near.docx"
    mf.make_float_figs(path, "near_group3")
    plan, req = _req(path, journal)
    assert plan.floats["s1"].mode == "caption" and FLOATS_HEADING not in req.data
    excluded = {e.src for e in plan.exclusions}
    fixed = _section(req.data, FIXED_HEADING)
    assert not any(f"[{src}]" in fixed for src in excluded)


def test_body_paras_are_listed_and_cannot_be_after(journal, meta, tmp_path):
    # 本文として出す段落（FloatInfo.body_paras）は「中身」に「本文として出す段落」で載せ、「## 本文」には載せない（after に書けない）
    path = tmp_path / "note.docx"
    mf.make_float_figs(path, "table_fig_note_down")
    plan, req = _req(path, journal)
    info = plan.floats["s1"]
    [q] = info.body_paras
    block = _blocks(_section(req.data, FLOATS_HEADING))["s1"]
    assert f"      本文として出す段落 = [{q.src}]注：架空の注である。" in block
    body = req.data.split("\n## 本文（", 1)[1].split("\n\n", 1)[0]
    assert f"[{q.src}]" not in body and q.src not in req.asked["after"]
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", ai_mode="manual",
                                               ai_response=answers.answer(placements=[("s1", q.src)])))
    assert res.fidelity.ok and res.plan.unplaced_floats == ["s1"]
    assert [op["src"] for op, _ in res.ai.rejected if op["op"] == "place_float"] == ["s1"]


def test_asked_after_is_the_body_section(journal):
    # AIRequest.asked の after は、「## 本文」の [d…] で始まる行の段落 ID と同じ
    for path in (FULL, EDGE, FLOAT, NOTES, STRUCTURE, PLACE, OUTSIDE):
        plan, req = _req(path, journal)
        body = req.data.split("\n## 本文（", 1)[1].split("\n\n", 1)[0].splitlines()
        ids = [m.group(1) for m in (re.match(r"\[(d\d+)\]", ln) for ln in body) if m]
        assert req.asked["after"] == set(ids) == set(after_ids(plan)), path.name


def test_other_column_has_no_estimate(journal):
    # 図形が結び付いた段落の右隣の段にある（横の位置が段の幅の 0.8 倍より右）ときは、推定を出さない
    plan, linker = _mechanical(FLOAT, journal)[1:]
    fl = plan.floats["s1"].float
    before = _blocks(_section(build_request(plan, linker).data, FLOATS_HEADING))["s1"]
    assert "  推定: [d17]" in before
    fl.h_offset_cm = plan.layout.column_width_cm + 0.5
    after = _blocks(_section(build_request(plan, linker).data, FLOATS_HEADING))["s1"]
    assert "  推定: なし" in after and "（アンカー段落の段の右隣の段）" in after


def test_estimate_outside_the_list_is_read_as_the_previous_paragraph(journal, monkeypatch):
    # 推定が「## 本文」に載せない段落（空の段落・出力から除いた段落など）を指すときは、その前の、載せた段落に読み替える（C059）
    plan, linker = _mechanical(PLACE, journal)[1:]
    listed = set(after_ids(plan))
    seq = plan.body_seq
    k = next(i for i, src in enumerate(seq) if src not in listed and i > 0 and seq[i - 1] in listed)
    hidden, prev = seq[k], seq[k - 1]
    assert listed_before(plan, hidden, listed) == prev and listed_before(plan, prev, listed) == prev
    monkeypatch.setattr(ai_assist, "estimate_top_left", lambda *a, **k: (hidden, ""))
    data = build_request(plan, linker).data
    sec = _section(data, FLOATS_HEADING)
    assert f"  推定: [{prev}]" in sec and f"[{hidden}]" not in sec
    # 段落が 1 つも前にないときは「なし」
    first = next(src for src in seq if src not in listed) if seq[0] not in listed else None
    if first is not None:
        monkeypatch.setattr(ai_assist, "estimate_top_left", lambda *a, **k: (seq[0], ""))
        assert "  推定: なし" in _section(build_request(plan, linker).data, FLOATS_HEADING)


def test_layout_values_are_japanese(journal):
    # docx の配置の値（基準・配置・折り返し）に英語の語を出さない。知らない値も日本語で書く
    lay = Layout(columns=2, column_width_cm=8.7, text_width_cm=18.1, line_pitch_cm=0.56, chars_per_line=24)
    words = re.compile(r"[A-Za-z]+")
    for kw in (dict(h_from="column", h_offset_cm=9.0, v_from="paragraph", v_offset_cm=1.0, wrap="wrapSquare"),
               dict(h_from="page", h_align="center", v_from="margin", v_align="bottom", wrap="wrapNone"),
               dict(h_from="insideMargin", h_align="inside", v_from="topMargin", v_align="top", wrap="wrapTight"),
               dict(h_from="somethingNew", h_align="oddAlign", v_from="", v_align="", wrap="wrapUnknown")):
        fl = Float(fid="s1", anchor_src="d1", width_cm=8.0, height_cm=4.0, **kw)
        text = describe(fl, lay)
        assert set(words.findall(text)) <= {"cm"}, text
    for path in (FLOAT, OUTSIDE, PLACE, STRUCTURE):
        data = _req(path, journal)[1].data
        for heading in (FLOATS_HEADING, UNDECIDED_HEADING):
            for ln in _section(data, heading).splitlines():
                if "docx の配置:" in ln:
                    assert set(words.findall(ln.split("docx の配置:", 1)[1])) <= {"cm"}, ln


def test_textbox_sections(journal):
    # テキストボックスの 3 つの節の見出しは、指示の部分が指す名前と同じ。決められないものは 1 つ残らず中身・仮の位置・大きさ・理由で示す
    plan, req = _req(STRUCTURE, journal)
    for heading in (UNDECIDED_HEADING, ai_assist.ESTIMATED_HEADING, LABELS_HEADING):
        name = heading.split("（", 1)[0][2:]
        assert f"「# {name}」" in req.instructions and heading in req.data
    blocks = _blocks(_section(req.data, UNDECIDED_HEADING))
    assert set(blocks) == set(plan.undecided_boxes) == set(req.asked["boxes"])
    for x, block in blocks.items():
        lines = [ln.split(":", 1)[0].strip() for ln in block.splitlines() if not ln.startswith(" " * 6)]
        assert lines[0] == f"[{x}] 中身" and lines[1:3] == ["仮の位置", "docx の配置"] and lines[-1] == "決められなかった理由"


def test_outside_anchor_place_says_why(journal):
    # 結び付いた段落が本文の外なら、仮の位置は「本文の最後（…ため）」で、推定は「なし」
    plan, req = _req(OUTSIDE, journal)
    blocks = _blocks(_section(req.data, FLOATS_HEADING))
    assert "  仮の位置: 本文の最後（図形が本文の外（引用文献）の段落に結び付いているため）" in blocks["s1"]
    assert "  推定: なし" in blocks["s1"]


def test_request_does_not_say_use_ai(journal):
    # 依頼文（AI に読ませる文）に、人向けの「AI を使うと」「AI による補完」の文と前の形の操作の名前を書かない（点検 review12 の
    # 利用者向け minor）
    for path in (FLOAT, OUTSIDE, PLACE, STRUCTURE, FULL):
        text = _req(path, journal)[1].manual_text()
        for word in ("AI を使うと", "AI による補完", "items", "kind box", "set_role", "変更不可"):
            assert word not in text, (path.name, word)
