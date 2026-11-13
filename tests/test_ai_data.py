"""AI への依頼文のデータの部分 1: 段落の行・注・文献・図表式の一覧（修正計画 W8 の手順 14。実際の API は呼ばない）。

データの部分は「# 論文（ここから下はデータ）」から下。段落は 1 行に 1 つ（[段落 ID]〔スタイル名〕文字。本文のスタイルは〔 〕を書かない）、
節は「## スタイルの一覧」「## 冒頭」「## 本文」「## 付記・謝辞・後付けの見出し」「## 注」「## 引用文献」「## 英文の部分」と
「# 図・表・式の一覧」。docx の画像の印は書かない。表のセルは参照らしい文字のあるものだけを載せる（ai_assist.paper_sections）。
"""
import pytest

import make_fixtures as mf
from conftest import EDGE, FLOAT, FULL, NOTES, OUTSIDE, PDFCHECK, PLACE, READER, STRUCTURE
from jasme_jats import ai_assist
from jasme_jats.ai_assist import (BODY_HEADING, CELL_STYLE, DATA_HEADING, NO_FORMULA_TEXT, STYLES_HEADING, WORD_DEFAULT_STYLES,
                                  build_request, cell_has_ref, para_line)
from jasme_jats.builder import build
from jasme_jats.model import Atom, LinkSpec, Para
from jasme_jats.pipeline import _mechanical
from jasme_jats.structure import figure_rows
from make_fixtures import S

DOCS = [FULL, EDGE, FLOAT, NOTES, PDFCHECK, STRUCTURE, PLACE, OUTSIDE, READER]


def _data(path, journal, meta=None):
    _, plan, linker = _mechanical(path, journal)
    info = build(plan, meta, journal, None)[1] if meta is not None else None
    return plan, info, build_request(plan, linker, info, journal=journal).data


def _section(data, heading) -> list:
    """データの節 heading（「## 本文」など。見出しの行の先頭）の行（見出しの行を除き、次の空行まで）。なければ []。"""
    lines = data.splitlines()
    k = next((i for i, ln in enumerate(lines) if ln.startswith(heading)), None)
    if k is None:
        return []
    out = []
    for ln in lines[k + 1:]:
        if not ln.strip():
            break
        out.append(ln)
    return out


def _ids(lines) -> list:
    """行頭の [段落 ID]（字下げした行と〔 〕の行を除く）。"""
    return [ln[1:].split("]", 1)[0] for ln in lines if ln.startswith("[d") or ln.startswith("[f") or ln.startswith("[e")]


def _article(tmp_path):
    """本文に番号つき・記号つきの箇条書き、参照のあるセルとないセルの表、キャプションのない表のある小さな論文（架空）。"""
    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "授業の流れを表1に示す（試験，2024）。"),
                mf.list_item(S["body"], "番号の付いた項目である。", num_id=7),
                mf.list_item(S["body"], "記号の付いた項目である。"),
                mf.para(S["tab_cap"], "表1　授業の流れ"),
                mf.table([[mf.cell("段階"), mf.cell("活動")], [mf.cell("導入"), mf.cell("図1を見る")],
                          [mf.cell("展開"), mf.cell("試験（2024）の問題を解く")], [mf.cell("まとめ"), mf.cell("")]]),
                mf.para(S["body"], "次の表に型を示す。"),
                mf.table([[mf.cell("型"), mf.cell("人数")], [mf.cell("A"), mf.cell("3")]]),
                mf.para(S["body"], "以上である。")]
    path = tmp_path / "data_rows.docx"
    mf.make_article(path, "依頼文のデータの検証用文書", parts)
    return path


def _src(plan, head):
    return next(s for s, p in plan.paras.items() if p.plain().startswith(head))


@pytest.mark.parametrize("path", DOCS, ids=lambda p: p.stem)
def test_body_section_lists_body_seq(path, journal, meta):
    """「## 本文」の段落 ID の集合は、plan.body_seq の文字のある段落（出力から除いた段落を除く）と同じ（after に書ける段落）。
    図形の中の段落（浮動配置の図形・テキストボックス）は、どの段落の節にも載せない。画像の印は書かない。"""
    plan, info, data = _data(path, journal, meta)
    assert data.startswith(DATA_HEADING + "\n")
    excluded = {e.src for e in plan.exclusions} | {e.src for e in info.exclusions}
    body = _section(data, "## 本文")
    expected = [s for s in plan.body_seq if s not in excluded and ai_assist.para_view(plan.paras[s]).strip()]
    assert _ids(body) == expected
    paper = data.split("\n# 図・表・式の一覧", 1)[0]
    inside = [s for s, p in plan.paras.items() if p.float_id or p.textbox_id]
    assert all(f"[{s}]" not in paper for s in inside)
    assert "⟦画像" not in data and "画像: " not in data
    # 役割・位置の欄（前の形の「（役割 / 位置 / スタイル）」）は書かない
    assert not any(" / " in ln.split("〕", 1)[0] for ln in body if "〔" in ln)


@pytest.mark.parametrize("path", DOCS, ids=lambda p: p.stem)
def test_refs_and_notes_once(path, journal):
    """文献は「## 引用文献」に 1 回だけ（段落 ID は書かない）、注は「## 注」に 1 回だけ（注の ID は注の最初の段落の行頭）。"""
    plan, _, data = _data(path, journal)
    for r in plan.refs:
        assert data.count(f"\n[{r.rid}] ") == 1
        assert f"[{r.para.src}]" not in data.split("\n# 図・表・式の一覧", 1)[0]
    notes = _section(data, "## 注")
    for fn in plan.fns:
        assert sum(ln.startswith(f"[{fn.fid}]") for ln in notes) == 1
        assert data.split("\n# 図・表・式の一覧", 1)[0].count(f"[{fn.fid}]") == 1
        shown = [q.src for q in fn.paras if ai_assist.para_view(q).strip()]
        assert all(sum(f"[{s}]" in ln for ln in notes) == 1 for s in shown)


def test_rows_marks_and_tables(journal, tmp_path):
    """Word の番号・箇条書きの記号は ⟦番号: …⟧、本文のスタイルは〔 〕を書かない。表のセルは参照らしい文字のあるものだけを字下げして
    〔表のセル〕で載せ、省いた数を表の行に書く。キャプションのない表は「図・表・式の一覧」に最初のセルと場所で出る。"""
    path = _article(tmp_path)
    plan, _, data = _data(path, journal)
    body = _section(data, "## 本文")
    numbered, bullet = plan.paras[_src(plan, "番号の付いた")], plan.paras[_src(plan, "記号の付いた")]
    assert numbered.autonum.strip() and bullet.autonum.strip()
    assert f"[{numbered.src}]⟦番号: {numbered.autonum.strip()}⟧番号の付いた項目である。" in body
    assert f"[{bullet.src}]⟦番号: {bullet.autonum.strip()}⟧記号の付いた項目である。" in body
    assert f"[{_src(plan, '以上である。')}]以上である。" in body          # 本文のスタイル（Body Text）は〔 〕を書かない
    assert f"[{_src(plan, '表1　授業')}]〔表キャプション〕表1　授業の流れ" in body
    k = body.index("〔表 T1: セル 7 個のうち、参照らしい文字のない 5 個は省略〕")
    assert body[k + 1] == f"  [{_src(plan, '図1を見る')}]〔{CELL_STYLE}〕図1を見る"
    assert body[k + 2] == f"  [{_src(plan, '試験（2024）の')}]〔{CELL_STYLE}〕試験（«2024→B1»）の問題を解く"
    assert not body[k + 3].startswith(" ")         # 文字のないセル・参照のないセルは載せない
    assert "〔表 T2: セル 4 個のうち、参照らしい文字のない 4 個は省略〕" in body
    assert all(f"[{_src(plan, t)}]" not in data for t in ("段階", "導入", "まとめ", "人数"))
    figs = _section(data, "# 図・表・式の一覧")
    assert figs == [f"[T1] 表1　授業の流れ（[{_src(plan, '表1　授業')}]）",
                    f"[T2]（キャプションのない表。最初のセル「型」。[{_src(plan, '次の表に')}] の後ろ）", NO_FORMULA_TEXT]


def test_cell_has_ref():
    """セルを載せる条件: リンク済みの箇所があるか、参照らしい文字（年・「図 N」「表 N」・式・注・URL。全角も）がある。"""
    def p(text, link=None):
        return Para(src="d1", atoms=[Atom(kind="text", text=text, link=link)])
    assert all(cell_has_ref(p(t)) for t in ("2019 年", "図３", "表 2", "（2）式", "注1", "https://example.org"))
    assert not any(cell_has_ref(p(t)) for t in ("導入", "10 分", "第2時", "A"))
    assert cell_has_ref(p("導入", LinkSpec(kind="xref", attrs={"rid": "B1"})))


def test_formulas_and_figures(journal):
    """番号つきの式は [FD1] と段落、なければ「式の番号（FD）はありません。」。図形の中の図・表は「（図形 s1 の中）」、ほかは
    キャプションの段落 ID。キャプションのない画像の置き場所（ID のない行）は載せない。"""
    plan, _, data = _data(FULL, journal)
    figs = _section(data, "# 図・表・式の一覧")
    fd = plan.formulas[0]
    assert f"[FD1] 式の番号「{fd.label}」（[{fd.para.src}]）" in figs and NO_FORMULA_TEXT not in figs
    rows = [r for r in figure_rows(plan) if r.fid]
    assert [ln.split("]")[0] + "]" for ln in figs if not ln.startswith("[FD")] == [f"[{r.fid}]" for r in rows]
    assert all(ln.endswith(f"（[{r.caption.src}]）") for ln, r in zip(figs, rows))
    _, _, data = _data(NOTES, journal)
    assert _section(data, "# 図・表・式の一覧") == [NO_FORMULA_TEXT]
    plan, _, data = _data(FLOAT, journal)
    figs = _section(data, "# 図・表・式の一覧")
    assert "[F1] 図1　表で組んだ問題（図形 s1 の中）" in figs


def test_styles_and_sections(journal):
    """「## スタイルの一覧」は雑誌の設定の順で、Word の既定の英語の名前を除き、Body Text と別名（英文要約 など）を載せる。和文の
    著者名・所属は「## 冒頭」、英文の著者名・所属は「## 英文の部分」、注見出しは「## 注」、参考文献見出しは「## 付記・謝辞・
    後付けの見出し」。"""
    plan, _, data = _data(FULL, journal)
    styles = _section(data, STYLES_HEADING)[0].split(" / ")
    assert styles == [k for k in journal.styles if k not in WORD_DEFAULT_STYLES]
    assert "Body Text" in styles and "英文要約" in styles and not set(styles) & WORD_DEFAULT_STYLES
    front, en = _ids(_section(data, "## 冒頭")), _ids(_section(data, "## 英文の部分"))
    for a in plan.authors:
        assert a.name_ja is None or a.name_ja.src in front
        assert a.name_en is None or a.name_en.src in en
    assert plan.fn_heading.src in _ids(_section(data, "## 注"))
    assert plan.ref_heading.src in _ids(_section(data, "## 付記・謝辞・後付けの見出し"))
    assert plan.abstract[0].src in en and BODY_HEADING in data


def test_para_line():
    """段落の行: スタイル名は本文のスタイル以外だけ〔 〕で書き、改行は ⏎、Word の脚注・文末脚注の参照は ⟦脚注⟧・⟦文末脚注⟧。"""
    p = Para(src="d9", style_name="章見出し", atoms=[Atom(kind="text", text="１．はじめに\n本文"),
                                                  Atom(kind="fnref", fn_kind="footnote", fn_id="2"),
                                                  Atom(kind="fnref", fn_kind="endnote", fn_id="3")])
    assert para_line(p, "Body Text") == "[d9]〔章見出し〕１．はじめに⏎本文⟦脚注⟧⟦文末脚注⟧"
    assert para_line(p, "章見出し") == "[d9]１．はじめに⏎本文⟦脚注⟧⟦文末脚注⟧"
