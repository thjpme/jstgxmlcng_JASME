"""AI への依頼文のデータの部分 2: 未解決の一覧・スタイルを確かめる段落・除外・氏名（修正計画 W8 の手順 15。実際の API は呼ばない）。

「# 機械がリンクできなかった箇所」は、段落にあるとおりの表記（全角・半角を変えない）と、段落の中で何回目か（linker.occurrence_at。
回答の links の occurrence と同じ数え方）を書く。そのために linker.unresolved の項目は linker.Unresolved（先頭の 6 つは前の組と同じ
並び）で、段落の中の範囲を持つ。機械の判断でリンクしなかった参照（linker.held）も同じ形で載せる。
"""
import types

import answers
import make_fixtures as mf
from conftest import FULL, STRUCTURE
from jasme_jats import ai_assist
from jasme_jats.ai_assist import (EXCLUDED_HEADING, NAMES_HEADING, SUSPECTS_HEADING, UNPLACED_TEXT_NOTE, UNRESOLVED_HEADING,
                                  build_request, unresolved_line, unresolved_section)
from jasme_jats.article import StyleSuspect
from jasme_jats.linker import Unresolved
from jasme_jats.model import Atom, Para
from jasme_jats.pipeline import Options, _mechanical, convert
from make_fixtures import S


def _section(data, heading) -> list:
    """データの節 heading の行（見出しの行を除き、次の空行まで）。なければ []。"""
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


def _src(plan, prefix):
    [src] = [s for s, p in plan.paras.items() if p.plain().startswith(prefix)]
    return src


def _article(path, *texts):
    mf.make_article(path, "未解決の一覧の検証用文書", lambda b: [mf.para(S["sec1"], "１．はじめに")]
                    + [mf.para(S["body"], t) for t in texts])
    return path


def test_second_occurrence_matches_links_occurrence(journal, meta, tmp_path):
    # 同じ「2024」が同じ段落に 2 回あり、1 回目はリンク済み（試験（2024））、2 回目は文献リストにない（別人（2024））。依頼文には
    # 「（2 回目）」と書き、その数え方で答えた links が、2 回目の「2024」にリンクを付ける
    path = _article(tmp_path / "occ.docx", "試験（2024）にならい，別人（2024）の考えも見る。")
    _, plan, linker = _mechanical(path, journal)
    src = _src(plan, "試験（2024）にならい")
    lines = _section(build_request(plan, linker).data, UNRESOLVED_HEADING)
    [line] = [ln for ln in lines if ln.startswith(f"- [{src}]")]
    assert line.startswith(f"- [{src}] 文献:「2024」（2 回目）… 「別人（2024）」の中。")
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", ai_mode="manual",
                                               ai_response=answers.answer(links=[("文献", src, "2024", 2, "B1")])))
    assert res.ai.rejected == [] and len(res.ai.accepted) == 1
    p = res.plan.paras[src]
    linked = [(a.text, a.link.attrs["rid"]) for a in p.atoms if a.link is not None and a.link.attrs.get("ref-type") == "bibr"]
    assert linked == [("2024", "B1"), ("2024", "B1")]
    # レポートの 3 章の項目は前の組と同じ（先頭の 4 つと 5・6 番目の添字。文献は NFKC の引用の文字）
    [u] = linker.unresolved
    assert (u[0], u[1], u[2], u[4], u[5]) == ("bibr", src, "別人(2024)", "missing", "2024")
    assert u[3] == u.detail and p.plain()[u.start:u.end] == "2024" and u.context == "別人（2024）"


def test_fullwidth_and_halfwidth_kept_as_in_paragraph(journal, tmp_path):
    # 全角の「（」と半角の「(」、全角の数字は、段落にあるとおりに書く（前の形は NFKC の文字を書いていた）
    path = _article(tmp_path / "width.docx", "架空(2030)と別人（２０３１）を比べる。")
    _, plan, linker = _mechanical(path, journal)
    src = _src(plan, "架空(2030)")
    lines = [ln for ln in _section(build_request(plan, linker).data, UNRESOLVED_HEADING) if ln.startswith(f"- [{src}]")]
    assert lines[0].startswith(f"- [{src}] 文献:「2030」（1 回目）… 「架空(2030)」の中。")
    assert lines[1].startswith(f"- [{src}] 文献:「２０３１」（1 回目）… 「別人（２０３１）」の中。")
    # レポートの 3 章の文字は前と同じ（NFKC の引用の文字）
    assert [u.text for u in linker.unresolved] == ["架空(2030)", "別人(2031)"]


def test_figure_list_number_in_context(journal, tmp_path):
    # 「図1、3」の 3（図3 がない）は「3」（リンクにする文字）を、その参照の並びの表記の中として書く
    path = _article(tmp_path / "fig.docx", "図1、3を見る。")
    _, plan, linker = _mechanical(path, journal)
    src = _src(plan, "図1、3")
    lines = [ln for ln in _section(build_request(plan, linker).data, UNRESOLVED_HEADING) if ln.startswith(f"- [{src}]")]
    assert f"- [{src}] 図:「図1」（1 回目）… 「図1、3」の中。図1 に対応する図が見つからない" in lines
    assert f"- [{src}] 図:「3」（1 回目）… 「図1、3」の中。図3 に対応する図が見つからない" in lines


def test_same_line_once_and_positionless_items():
    # 同じ行は 1 回だけ。位置を持たない項目（段落の範囲が段落の文字と合わないものも）は、項目の文字に「表記は…」を付ける
    p = Para(src="d1", atoms=[Atom(kind="text", text="図9と図9を見る。")])
    plan = types.SimpleNamespace(paras={"d1": p}, fns=[], refs=[], uncited_refs=[])
    u = Unresolved("fig", "d1", "図9", "図9 に対応する図が見つからない", start=0, end=2)
    v = Unresolved("fig", "d1", "図9", "図9 に対応する図が見つからない", start=3, end=5)
    linker = types.SimpleNamespace(unresolved=[u, u, v], held=[])
    assert unresolved_section(plan, linker) == [UNRESOLVED_HEADING, "- [d1] 図:「図9」（1 回目）… 図9 に対応する図が見つからない",
                                                "- [d1] 図:「図9」（2 回目）… 図9 に対応する図が見つからない"]
    w = Unresolved("bibr", "d1", "架空(2001)", "文献リストに該当する文献が見つからない", "missing", "2001")
    assert unresolved_line(plan, w) == f"- [d1] 文献:「架空(2001)」{UNPLACED_TEXT_NOTE}… 文献リストに該当する文献が見つからない"
    bad = u._replace(end=99)
    assert UNPLACED_TEXT_NOTE in unresolved_line(plan, bad)
    # 何もなければ「- なし」。文献があるときは、本文でリンクされていない文献の行（なければ「なし」）
    assert unresolved_section(plan, types.SimpleNamespace(unresolved=[], held=[])) == [UNRESOLVED_HEADING, "- なし"]
    plan.refs, plan.uncited_refs = ["B1"], []
    assert unresolved_section(plan, types.SimpleNamespace(unresolved=[], held=[]))[-1] == "- 本文でリンクされていない文献: なし"


def test_report_chapter3_unchanged(journal, meta, tmp_path):
    # レポートの 3 章は、前の組の 4 つ（種類・段落・文字・理由）のまま（Unresolved にしても変わらない）
    path = _article(tmp_path / "rep.docx", "図5を見る。別人（2031）による。")
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    sec3 = res.report_path.read_text(encoding="utf-8").split("\n## 3.")[1].split("\n## 4.")[0]
    assert "図5 に対応する図が見つからない" in sec3 and "別人(2031)" in sec3
    assert {u[0] for u in res.unresolved_after} == {"fig", "bibr"}


def test_style_suspects_and_names_sections(journal):
    # スタイルを確かめる段落は、段落 ID・スタイル名（本文のスタイルなら書かない）・先頭の文字・機械の見立て。和文の氏名だけを
    # 「# 姓と名の区切りを確かめる氏名」に載せる。どちらも、なければ節を出さない
    _, plan, linker = _mechanical(FULL, journal)
    assert SUSPECTS_HEADING not in build_request(plan, linker).data
    head = next(s for s, p in plan.paras.items() if p.role == "sec1")
    body = next(s for s in plan.body_seq if plan.paras[s].role == "p" and plan.paras[s].plain().strip())
    plan.style_suspects = [StyleSuspect("heading_level", head, "章見出しのスタイルですが、番号の形は節です"),
                           StyleSuspect("quote_like", body)]
    req = build_request(plan, linker, types.SimpleNamespace(exclusions=[], unsplit_names=[("d11", "研究次郎", "ja"),
                                                                                         ("d12", "KENKYU", "en")],
                                                             name_splits=[]))
    lines = _section(req.data, SUSPECTS_HEADING)
    hp, bp = plan.paras[head], plan.paras[body]
    assert lines[0].startswith(f"- [{head}]〔{hp.style_name}〕「{hp.text_only().strip()[:15]}")
    assert lines[0].endswith(": 章見出しのスタイルですが、番号の形は節です")
    assert lines[1].startswith(f"- [{body}]「") and lines[1].endswith(": 本文のスタイルですが、引用の形をしています")
    assert _section(req.data, NAMES_HEADING) == ["- [d11]「研究次郎」: 姓と名の間に空白がない"]
    assert {s.key for s in req.sections} >= {"names", "style_fixes"}
    assert "suspects" in next(s for s in req.sections if s.key == "style_fixes").parts


def test_exclusion_section_has_no_operation_names(journal):
    # 除外の一覧は、除いた理由と文字の先頭だけ（操作の名前を書かない）。決められないテキストボックス・図の注記とみなしたテキスト
    # ボックスの段落は、テキストボックスの節に載せるので、ここには載せない
    _, plan, linker = _mechanical(STRUCTURE, journal)
    data = build_request(plan, linker).data
    lines = _section(data, EXCLUDED_HEADING)
    assert lines and all(ln.startswith("- [") and "set_role" not in ln and "placements" not in ln for ln in lines)
    boxed = {q.src for b in plan.textboxes.values() if b.kind in ("undecided", "label") for q in b.paras}
    assert not any(ln.split("]")[0][3:] in boxed for ln in lines)
    # 節を出す条件は request_sections の parts（excluded）と同じ
    assert "excluded" in next(s for s in build_request(plan, linker).sections if s.key == "style_fixes").parts
    assert ai_assist._request_exclusions(plan, None)
