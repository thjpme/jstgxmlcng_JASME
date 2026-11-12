"""Word の自動番号の出力の確かめ（pipeline.lost_autonums・要対応 autonum_lost。修正計画 2026-11 の単位 u3-autonum）。

docx は make_fixtures の部品で作る（内容は架空）。番号は docx の文字ではなく生成文字（jx:gen kind autonum、src は段落の ID）なので、
文字の不変性チェックでは見つからない。ここでは、番号を出していない段落を見つけること、見つけてはいけないものを見つけないこと、
最後の組み立ての木を調べていることを確かめる。
"""
import json
import types
import zipfile

import make_fixtures as mf
import pytest
from conftest import ALL_DOCS, FULL, META_EXAMPLE
from lxml import etree

from jasme_jats import pipeline
from jasme_jats.builder import BuildInfo, Builder
from jasme_jats.cli import main as cli_main
from jasme_jats.model import LostImage, LostNumber
from jasme_jats.pipeline import Options, _mechanical, convert, lost_autonums
from jasme_jats.report import NEEDS_ACTION, actions
from jasme_jats.tracking import GEN, SPAN

S = mf.S
W = mf.W
NUM = 7        # テンプレートの numbering.xml の「1.」の番号


def li(style, *parts):
    return mf.list_item(style, *parts, num_id=NUM)


def add_num(docx, markers, num_id=NUM):
    """document.xml の、文字に markers のどれかを含む w:p に自動番号を付ける（題目・著者名・所属の段落に番号を付けるのに使う）。"""
    tmp = docx.with_suffix(".tmp.docx")
    with zipfile.ZipFile(docx) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                root = etree.fromstring(data)
                for p in root.iter(f"{{{W}}}p"):
                    text = "".join(x.text or "" for x in p.iter(f"{{{W}}}t"))
                    if any(m in text for m in markers):
                        ppr = p.find(f"{{{W}}}pPr")
                        if ppr is None:
                            ppr = etree.Element(f"{{{W}}}pPr")
                            p.insert(0, ppr)
                        num = etree.fromstring(f'<w:numPr xmlns:w="{W}"><w:ilvl w:val="0"/><w:numId w:val="{num_id}"/></w:numPr>')
                        st = ppr.find(f"{{{W}}}pStyle")
                        if st is not None:
                            st.addnext(num)
                        else:
                            ppr.insert(0, num)
                data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
            zout.writestr(item, data)
    tmp.replace(docx)


def convert_tracking(monkeypatch, path, journal, meta, out, **opts):
    """変換し、(結果, 最後に組み立てた木, その BuildInfo) を返す（pipeline.build を包んで最後の組み立てを取る）。"""
    built = []
    orig = pipeline.build

    def spy(*a, **k):
        root, info = orig(*a, **k)
        built.append((root, info))
        return root, info
    monkeypatch.setattr(pipeline, "build", spy)
    res = convert(path, meta, journal, Options(out_dir=out, convert_metafiles=False, **opts))
    return res, built[-1][0], built[-1][1]


def assert_autonum_gens(root, plan):
    """kind autonum の jx:gen の出し方を確かめる（番号の二重出力・置き場所の誤りを見逃さない）。
    src ごとに 1 つまで。親は、同じ src の最初の jx:span の親か、sec・fig・table-wrap・ref・list-item の子の label。src の段落の autonum は空でない。"""
    first_span = {}
    for sp in root.iter(SPAN):
        first_span.setdefault(sp.get("src"), sp)
    seen = set()
    for g in root.iter(GEN):
        if g.get("kind") != "autonum":
            continue
        src = g.get("src")
        assert src is not None and src not in seen, src
        seen.add(src)
        parent = g.getparent()
        label_ok = parent.tag == "label" and parent.getparent().tag in ("sec", "fig", "table-wrap", "ref", "list-item")
        sp = first_span.get(src)
        assert label_ok or (sp is not None and sp.getparent() is parent), (src, parent.tag)
        assert (plan.paras[src].autonum or "").strip(), src


def check_ok(res, root):
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    assert res.lost_autonums == []
    assert_autonum_gens(root, res.plan)


def cell_article(path):
    def parts(b):
        return [mf.para(S["sec1"], "１．表の検証"), mf.para(S["tab_cap"], "表1　検証用の表"),
                mf.table([[mf.cell(li(S["body"], "番号付きの質問")), mf.cell("回答")]]), mf.para(S["body"], "以上で終わる。")]
    mf.make_article(path, "番号の検証用文書", parts)


# ---------------------------------------------------------------------------- 守りが番号の出し忘れを見つける
def test_guard_reports_missing_number(journal, meta, tmp_path, monkeypatch, capsys):
    """表のセルの番号を出さない（Builder.autonum_mark を、セルの段落だけ何もしない関数に替えた）と、守りが見つけて要対応にする。"""
    path = tmp_path / "cell.docx"
    cell_article(path)
    orig = Builder.autonum_mark

    def skip_cells(self, parent, p):
        if parent.tag != "td":
            orig(self, parent, p)
    monkeypatch.setattr(Builder, "autonum_mark", skip_cells)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    src = next(s for s, p in res.plan.paras.items() if p.plain() == "番号付きの質問")
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid       # 文字の検査は通る（番号は docx の文字ではない）
    assert res.lost_autonums == [LostNumber(src, "1.", res.lost_autonums[0].location, "td", "番号付きの質問")]
    acts = [a for a in actions(res) if a.key == "autonum_lost"]
    assert len(acts) == 1 and acts[0].level == NEEDS_ACTION and res.needs_action
    assert src in acts[0].top and "番号付きの質問" in acts[0].top
    report = res.report_path.read_text(encoding="utf-8")
    ch8 = report.split("## 8.")[1].split("## 9.")[0]
    assert "XML に番号を出せなかった段落" in ch8 and src in ch8
    assert cli_main([str(path), "--meta", str(META_EXAMPLE), "--out", str(tmp_path / "cli"), "--no-metafile-conversion"]) == 1
    err = capsys.readouterr().err
    assert "自動番号" in err and src in err


def test_actions_order_puts_autonum_lost_right_after_lost(journal, meta, tmp_path, monkeypatch):
    path = tmp_path / "cell.docx"
    cell_article(path)
    orig = Builder.autonum_mark
    monkeypatch.setattr(Builder, "autonum_mark", lambda self, parent, p: None if parent.tag == "td" else orig(self, parent, p))
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    assert [a.key for a in actions(res)][0] == "autonum_lost"      # 画像が失われていなければ先頭
    # XML に入らなかった画像もあるときは、その直後（actions() の head の並び: lost、autonum_lost）
    res.lost_images = [LostImage("img1", "", "引用文献 1件目", "試験用")]
    keys = [a.key for a in actions(res)]
    assert keys.index("autonum_lost") == keys.index("lost") + 1


# ---------------------------------------------------------------------------- 見つけてはいけないもの
def test_guard_ignores_intentional_paths(journal, meta, tmp_path, monkeypatch):
    """番号を出すものと、番号を出さないと決めたものは、守りが報告しない: 自動番号の章見出し・本文と付記と資料の箇条・引用文献・
    番号だけの空の段落・番号付きの画像だけの段落・AI の set_role exclude で除外した段落・題目の番号（10 章の警告）。"""
    def parts(b):
        rid = b.add_image("a.png", mf.png_bytes("A"))
        return [li(S["sec1"], "番号付きの章見出し"), li(S["body"], "本文の箇条"), mf.para(S["body"], "本文の文である。"),
                mf.list_item(S["body"], mf.drawing(rid, 1800000, 1100000, 50), num_id=NUM),
                mf.para(S["fig_cap"], "図1　番号付きの画像の段落"),
                li(S["body"], ""), li(S["body"], "除外する箇条"), mf.para(S["body"], "本文の文である。"),
                li(S["notes_head"], "付記の見出し"), li(S["body"], "付記の箇条"),
                li(S["ack_head"], "謝辞の見出し"), mf.para(S["body"], "謝辞の文である。")]
    path = tmp_path / "ignored.docx"
    mf.make_article(path, "題目の番号の検証用文書", parts, refs=lambda b: [li(S["ref"], "試験七郎（2022）．「番号付きの文献」．『架空誌』，第2巻，pp.1-2．")],
                    appendix=[li(S["sec1"], "資料　番号付きの資料の見出し"), li(S["body"], "資料の箇条")])
    add_num(path, ["題目の番号の検証用文書"])
    _, plan, _ = _mechanical(path, journal)
    src = next(s for s, p in plan.paras.items() if p.plain() == "除外する箇条")
    op = {"op": "set_role", "src": src, "text": "", "occurrence": 1, "target": "", "role": "exclude", "image": "",
          "confidence": "高", "reason": "試験"}
    resp = json.dumps({"operations": [op], "placements": [], "notes": []}, ensure_ascii=False)
    res, root, info = convert_tracking(monkeypatch, path, journal, meta, tmp_path / "out", ai_mode="manual", ai_response=resp)
    assert res.ai.rejected == [] and src in {e.src for e in res.plan.exclusions}
    check_ok(res, root)
    assert [u[2] for u in res.unshown_numbers] == ["題目"]
    assert not any(sp.get("src") == src for sp in root.iter(SPAN))
    assert "autonum_lost" not in [a.key for a in actions(res)]


def _node(autonum, text="本文"):
    return types.SimpleNamespace(autonum=autonum, text_only=lambda: text)


def test_lost_autonums_unit():
    """pipeline.lost_autonums を小さな木で直接確かめる。"""
    def tree(gen_src="d1", with_gen=True):
        root = etree.Element("article")
        td = etree.SubElement(root, "td")
        if with_gen:
            g = etree.SubElement(td, GEN, kind="autonum")
            if gen_src is not None:
                g.set("src", gen_src)
            g.text = "1. "
        etree.SubElement(td, SPAN, src="d1", seq="0").text = "本文"
        return root

    def plan(autonum="1."):
        return types.SimpleNamespace(paras={"d1": _node(autonum)}, pdf_numbers={}, locations={"d1": "本文 > 方法"},
                                     region={})
    info = BuildInfo()
    assert lost_autonums(plan(), tree(), info) == []
    assert lost_autonums(plan(), tree(gen_src=None), info) == [LostNumber("d1", "1.", "本文 > 方法", "td", "本文")]
    assert lost_autonums(plan(" "), tree(with_gen=False), info) == []
    assert lost_autonums(plan(None), tree(with_gen=False), info) == []
    skipped = BuildInfo()
    skipped.unshown_numbers.append(("d1", "1.", "題目", "本文"))
    assert lost_autonums(plan(), tree(with_gen=False), skipped) == []
    p = plan()
    p.pdf_numbers[("auto", "d1")] = "１．"
    assert lost_autonums(p, tree(with_gen=False), info)[0].number == "１．"
    # 文字を出していない段落（jx:span がない）は調べない
    root = tree(with_gen=False)
    root.find("td").remove(root.find("td/{*}span"))
    assert lost_autonums(plan(), root, info) == []
    # 同じ段落を複数の要素に分けて出しても 1 件
    root = tree(with_gen=False)
    etree.SubElement(root.find("td"), SPAN, src="d1", seq="1").text = "続き"
    assert len(lost_autonums(plan(), root, info)) == 1


def test_all_fixtures_have_no_lost_autonums(journal, meta, tmp_path, monkeypatch):
    for k, docx in enumerate(ALL_DOCS):
        res, root, _ = convert_tracking(monkeypatch, docx, journal, meta, tmp_path / f"o{k}")
        assert res.lost_autonums == [], docx.name
        assert_autonum_gens(root, res.plan)
        monkeypatch.undo()


# ---------------------------------------------------------------------------- 最後の組み立ての木を調べる
def _record_guards(monkeypatch):
    seen = {"autonums": [], "tables": []}
    orig_a, orig_t = pipeline.lost_autonums, pipeline.table_problems

    def spy_a(plan, root, info):
        seen["autonums"].append((root, info))
        return orig_a(plan, root, info)

    def spy_t(root, info):
        seen["tables"].append((root, info))
        return orig_t(root, info)
    monkeypatch.setattr(pipeline, "lost_autonums", spy_a)
    monkeypatch.setattr(pipeline, "table_problems", spy_t)
    return seen


def _rows_in_tree(root, info):
    return sum(1 for tbl, t, _ in info.tables if t.rows and any(a is root for a in tbl.iterancestors()))


def test_guard_uses_final_tree_after_dtd_retraction(journal, meta, tmp_path, monkeypatch):
    """DTD 不合格の数式の取り消しで組み立てをやり直した後は、lost_autonums も table_problems も、やり直した後の木と BuildInfo を見る。"""
    from test_ai import RESPONSE
    seen = _record_guards(monkeypatch)
    built = []
    orig_build = pipeline.build

    def spy_build(*a, **k):
        root, info = orig_build(*a, **k)
        built.append((root, info))
        return root, info
    monkeypatch.setattr(pipeline, "build", spy_build)
    orig_validate, calls = pipeline.validate, []

    def validate(xml, where=None):
        calls.append(1)
        return (False, ["強制的な不適合"]) if len(calls) == 1 else orig_validate(xml, where)
    monkeypatch.setattr(pipeline, "validate", validate)
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, ai_mode="manual", ai_response=RESPONSE, convert_metafiles=False))
    assert len(built) >= 2 and len(calls) == 2           # 取り消して組み立てをやり直した
    root, info = built[-1]
    assert [r is root and i is info for r, i in seen["autonums"]] == [True] and [r is root and i is info for r, i in seen["tables"]] == [True]
    assert res.tables_checked == _rows_in_tree(root, info) and res.tables_checked > 0
    assert res.lost_autonums == []


def test_guard_uses_final_tree_after_route2_numbers(journal, meta, tmp_path, monkeypatch):
    """ルート2 で pdf_numbers を付けて組み立て直した後も、最後の木と BuildInfo を見る（番号は PDF の形で出る）。"""
    from test_pdfmatch import (N10_TAIL, SMALL_FRONT, TALK, BULLETS, body_lines, bullet_article, convert_with_pages, n10_pages)
    bullet_article(tmp_path, journal)
    pages = n10_pages([*SMALL_FRONT, *body_lines(TALK), *[f"・{t}" for t in BULLETS], *N10_TAIL])
    seen = _record_guards(monkeypatch)
    built = []
    orig_build = pipeline.build

    def spy_build(*a, **k):
        root, info = orig_build(*a, **k)
        built.append((root, info))
        return root, info
    monkeypatch.setattr(pipeline, "build", spy_build)
    res = convert_with_pages(tmp_path, monkeypatch, journal, meta, pages, "pdf", docx=tmp_path / "n10.docx")
    assert len(built) == 2 and res.plan.pdf_numbers           # pdf_numbers で組み立て直した
    root, info = built[-1]
    assert [r is root and i is info for r, i in seen["autonums"]] == [True] and [r is root and i is info for r, i in seen["tables"]] == [True]
    assert res.tables_checked == _rows_in_tree(root, info)
    assert res.lost_autonums == []
    assert_autonum_gens(root, res.plan)
    assert [g.text.strip() for g in root.iter(GEN) if g.get("kind") == "autonum"] == ["・", "・"]

