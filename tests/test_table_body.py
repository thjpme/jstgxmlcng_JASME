"""表の本体の組み立て（修正計画の単位 B。C003 の表の側・C027・C031）: 浮動配置の表の印（Table.floating）、表キャプションの後ろの
表の探し方（続きを飛ばす・番号つきの別のキャプションを飛び越えない）、本体のない表の要対応 table_body、分かれた表・セルの中の
キャプションの要確認 table_parts。

docx は make_fixtures の部品で作る（内容は架空）。"""
import make_fixtures as mf
from lxml import etree

from jasme_jats.docx_reader import read_docx
from jasme_jats.model import Table
from jasme_jats.pipeline import Options, convert
from jasme_jats.report import TO_CHECK, actions, table_body_why

S = mf.S


def tb(rows=2, first="項目"):
    """2 列の小さな表（1 行目の最初のセルは first）。"""
    return mf.table([[mf.cell(first), mf.cell("値")]] + [[mf.cell(f"甲{i}"), mf.cell(f"{i}")] for i in range(1, rows)])


def head():
    return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "表1 と表2 を見る。試験（2024）による。")]


def build(tmp_path, parts, name="t"):
    """parts(b) の本文の段落の小さな論文を作り、その docx の道を返す。"""
    path = tmp_path / f"{name}.docx"
    mf.make_article(path, "架空の表の題目", lambda b: head() + parts(b))
    return path


def run(tmp_path, journal, meta, parts, name="t"):
    """変換し、4 つの確かめ（不変性・最終・DTD）を通ることを確かめて (res, root) を返す。"""
    path = build(tmp_path, parts, name)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / f"out_{name}", ai_mode="none"))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid, (res.fidelity.missing, res.dtd_errors[:3])
    return res, etree.fromstring(res.xml_base)


def wraps(root):
    """出力の <table-wrap> を [(id, 本体があるか, キャプションの先頭 4 字), …] にする。"""
    out = []
    for t in root.iter("table-wrap"):
        cap = t.find("caption")
        body = any(ch.tag in ("table", "graphic", "alternatives") for ch in t)
        out.append((t.get("id"), body, "".join(cap.itertext())[:4] if cap is not None else None))
    return out


def keys(res):
    return [a.key for a in actions(res)]


# ---------------------------------------------------------------------------- B1. 浮動配置の表の印
def test_floating_table_is_marked_and_text_unchanged(tmp_path):
    """w:tblPr/w:tblpPr のある表は Table.floating が真、ない表は偽。文字と段落 ID は印の有無で変わらない。"""
    def parts(float_it):
        def f(b):
            t2 = tb(first="架空の項目")
            return [mf.para(S["tab_cap"], "表1　架空の表"), tb(), mf.para(S["body"], "間の本文。"),
                    mf.floating_table(t2) if float_it else t2]
        return f
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    doc = read_docx(build(tmp_path / "a", parts(True)))
    plain = read_docx(build(tmp_path / "b", parts(False)))
    # 題目・著者の表（make_article の雛形）を除いた、本文の表
    tables = lambda d: [b.floating for b in d.blocks if isinstance(b, Table)
                         and any(p.text_only() == "値" for p in b.paragraphs())]
    assert tables(doc) == [False, True]
    assert tables(plain) == [False, False]
    assert [(p.src, p.text_only()) for p in doc.all_paragraphs()] == [(p.src, p.text_only()) for p in plain.all_paragraphs()]


# ---------------------------------------------------------------------------- B2. 表キャプションの後ろの表の探し方
def cap(text):
    return mf.para(S["tab_cap"], text)


def test_caption_with_two_or_three_continuations_gets_its_table(tmp_path, journal, meta):
    """番号で始まらない続きが 2 段落・3 段落の表キャプションも、続きの直後の表を組む（C027 の (a)。0.34.0 はキャプションだけの表と
    キャプションのない表に分かれた）。続きは caption_more に入る。"""
    for n in (1, 2, 3):
        more = [cap("（試験，2024，p.3"), cap("を基に"), cap("作成）")][:n]
        res, root = run(tmp_path, journal, meta, lambda b, more=more: [cap("表1　架空の分類")] + more
                        + [tb(), mf.para(S["body"], "後ろの本文。")], name=f"more{n}")
        assert wraps(root) == [("T1", True, "表1　架")], n
        assert len(root.find(".//table-wrap/caption").findall("p")) >= 1
        assert "table_body" not in keys(res)


def test_continuations_then_body_paragraph_do_not_take_a_later_table(tmp_path, journal, meta):
    """続き 2 段落の後ろが本文の段落なら、その後ろの表は取らない（続きの直後の 1 要素だけを見る）。"""
    res, root = run(tmp_path, journal, meta, lambda b: [cap("表1　架空の分類"), cap("（試験，2024"), cap("を基に作成）"),
                                                         mf.para(S["body"], "間の本文。"), tb()])
    assert wraps(root) == [("T1", False, "表1　架"), ("T2", True, None)]


def test_numbered_caption_is_not_skipped(tmp_path, journal, meta):
    """番号つきの表キャプションが 2 つ続き、その後ろに表が 1 つ: 表は隣の後ろのキャプションに付き、前のキャプションは本体なし
    （C027 の (b)。0.34.0 は前のキャプションが後ろのキャプションを飛び越えて表を取った）。"""
    res, root = run(tmp_path, journal, meta, lambda b: [cap("表1　架空の甲"), cap("表2　架空の乙"), tb(),
                                                         mf.para(S["body"], "後ろの本文。")])
    assert wraps(root) == [("T1", False, "表1　架"), ("T2", True, "表2　架")]


def test_same_number_english_caption_is_skipped_as_before(tmp_path, journal, meta):
    """和文の「表1」の後ろに同じ番号の英文の「Table 1」があるときは、今までどおり和文のキャプションが表を取る（英文の側は本体なし）。"""
    res, root = run(tmp_path, journal, meta, lambda b: [cap("表1　架空の甲"), cap("Table 1　Fictional"), tb(),
                                                         mf.para(S["body"], "後ろの本文。")])
    assert wraps(root) == [("T1", True, "表1　架"), ("T2", False, "Tabl")]


def test_normal_and_one_continuation_tables_unchanged(tmp_path, journal, meta):
    """続きのない表キャプション・空の段落をはさんだ表は、今までどおり組む。"""
    res, root = run(tmp_path, journal, meta, lambda b: [cap("表1　架空の正常な表"), tb(), mf.para(S["body"], "間。"),
                                                         cap("表2　架空の表"), mf.para(S["body"], ""), tb()])
    assert wraps(root) == [("T1", True, "表1　架"), ("T2", True, "表2　架")]


# ---------------------------------------------------------------------------- B3. 続きのある画像で貼った表
def test_caption_continuations_then_image_is_image_table(tmp_path, journal, meta):
    """続き 2 段落の表キャプションの直後の画像だけの段落は、画像で貼った表にする（0.34.0 は続きの直後で探すのをやめ、
    キャプションだけの表とキャプションのない図に分かれた）。"""
    def parts(b):
        im = b.add_image("tbimg.png", mf.png_bytes("Tab", size=(300, 200)))
        return [cap("表1　架空の画像の表"), cap("（試験，2024"), cap("を基に作成）"),
                mf.para(S["body"], mf.drawing(im, 1440000, 960000, 1001)), mf.para(S["body"], "後ろの本文。")]
    res, root = run(tmp_path, journal, meta, parts)
    assert wraps(root) == [("T1", True, "表1　架")]
    assert root.find(".//table-wrap/graphic") is not None
    assert not list(root.iter("fig"))


# ---------------------------------------------------------------------------- B4. 本体のない表の理由
def nodes(res):
    return {t.tid: t for t in res.plan.tables}


def test_bodyless_reason_next_caption_and_other(tmp_path, journal, meta):
    """すぐ後ろが番号つきの別の表キャプションなら理由は next_caption（why_ref にその段落 ID）、後ろが本文の段落ならその他（空）。"""
    res, root = run(tmp_path, journal, meta, lambda b: [cap("表1　架空の甲"), cap("表2　架空の乙"), tb(),
                                                         cap("表3　架空の丙"), mf.para(S["body"], "①甲の段落")])
    t = nodes(res)
    assert (t["T1"].why, t["T1"].why_ref) == ("next_caption", t["T2"].caption.src)
    assert (t["T2"].why, t["T3"].why, t["T3"].why_ref) == ("", "", "")


# ---------------------------------------------------------------------------- B5・B6. 本体のない表（要対応 table_body）
def text_body(b):
    """表キャプションの後ろが本文の段落（表を段落で書いた。data28 の形）。"""
    return [cap("表1　架空の一覧"), mf.para(S["body"], "①甲の段落"), mf.para(S["body"], "②乙の段落")]


def test_text_body_table_is_needs_action(tmp_path, journal, meta, capsys):
    """表キャプションの後ろに Word の表がない表は、要対応 table_body（理由はその他）。冒頭・することの一覧・3 章・Colab の枠・
    コマンドラインに出て、終了コードは 1。XML は今までどおりキャプションだけの表。"""
    from conftest import META_EXAMPLE

    from jasme_jats import colab
    from jasme_jats.cli import main as cli_main
    res, root = run(tmp_path, journal, meta, text_body)
    assert wraps(root) == [("T1", False, "表1　架")]
    assert [(b.tid, b.why, b.candidates) for b in res.bodyless_tables] == [("T1", "", [])]
    assert "table_body" in keys(res) and res.needs_action
    report = res.report_path.read_text(encoding="utf-8")
    top = report.split("## 1.")[1].split("## 2.")[0]
    assert "表の本体（Word の表）が見つからない表が 1 つあります" in top
    assert "（要対応）**表の本体が見つからない表 1 つ**" in report.split("## することの一覧")[1].split("## 1.")[0]
    ch3 = report.split("## 3.")[1].split("## 4.")[0]
    assert "| 表の本体 |" in ch3 and "キャプションの後ろに Word の表がありません" in ch3
    box = colab.result_boxes(res)
    assert "表の本体が見つからない表が 1 つあります（要対応）" in box and "\x00" not in box
    act = next(a for a in actions(res) if a.key == "table_body")
    assert "\x00" in act.box_detail          # 画面の操作は目印で書く
    path = tmp_path / "t.docx"
    assert cli_main([str(path), "--meta", str(META_EXAMPLE), "--out", str(tmp_path / "cli")]) == 1
    err = capsys.readouterr().err
    assert "表の本体（Word の表）が見つからない表が 1 つ" in err and "T1「表1　架空の一覧」" in err


def test_bodyless_next_caption_names_the_next_caption(tmp_path, journal, meta):
    """連続キャプションで本体のなくなった前の表は、理由 next_caption で、すぐ後ろのキャプションを添えて知らせる。"""
    res, root = run(tmp_path, journal, meta, lambda b: [cap("表1　架空の甲"), cap("表2　架空の乙"), tb()])
    act = next(a for a in actions(res) if a.key == "table_body")
    assert [(b.tid, b.why) for b in res.bodyless_tables] == [("T1", "next_caption")]
    assert "すぐ後ろに別の表キャプション" in act.top and "「表2　架空の乙」" in act.top
    assert "折り返し" not in act.top


def test_floating_table_is_candidate(tmp_path, journal, meta):
    """表キャプションの後ろが本文で、離れた所にキャプションのない浮動配置の表があれば、理由は floating で、その表を候補に添える
    （data21 の形）。XML は組み直さない。"""
    def parts(b):
        return [cap("表1　架空の浮動表"), mf.para(S["body"], "間の本文。"), mf.para(S["sec2"], "（１）次の節"),
                mf.floating_table(tb(first="架空の項目")), mf.para(S["body"], "後ろの本文。")]
    res, root = run(tmp_path, journal, meta, parts)
    assert wraps(root) == [("T1", False, "表1　架"), ("T2", True, None)]
    (b,) = res.bodyless_tables
    assert (b.tid, b.why, b.candidates) == ("T1", "floating", [("T2", "架空の項目", True)])
    act = next(a for a in actions(res) if a.key == "table_body")
    assert "折り返しを「なし」" in act.top and "T2（最初のセル「架空の項目」）" in act.top


def test_floating_reason_goes_to_one_table_only(tmp_path, journal, meta):
    """浮動配置の表 1 つには、docx の順でその表に最も近い前の、本体のない表 1 つだけを floating にする（ほかはその他＋候補）。"""
    def parts(b):
        return [cap("表1　架空の甲"), mf.para(S["body"], "間の本文。"), cap("表2　架空の乙"), mf.para(S["body"], "間の本文。"),
                mf.para(S["sec2"], "（１）次の節"), mf.floating_table(tb(first="架空の項目")), mf.para(S["body"], "後ろの本文。")]
    res, root = run(tmp_path, journal, meta, parts)
    assert [(b.tid, b.why) for b in res.bodyless_tables] == [("T1", ""), ("T2", "floating")]
    other = table_body_why(res.bodyless_tables[0])
    assert "Word の表に作り直して" in other and "T3（最初のセル「架空の項目」）がこの表かもしれません" in other


def test_next_caption_with_far_floating_table_adds_float_advice(tmp_path, journal, meta):
    """連続キャプションで本体のなくなった表も、離れた所に浮動配置の表があれば、浮動配置の案内と候補を添える（data27 の形）。"""
    def parts(b):
        return [mf.floating_table(tb(first="架空の項目")), mf.para(S["body"], "間の本文。"),
                cap("表1　架空の甲"), cap("表2　架空の乙"), tb(), mf.para(S["body"], "後ろの本文。")]
    res, root = run(tmp_path, journal, meta, parts)
    (b,) = res.bodyless_tables
    assert (b.tid, b.why) == ("T2", "next_caption")
    why = table_body_why(b)
    assert "すぐ後ろに別の表キャプション" in why and "折り返しを「なし」" in why and "T1（最初のセル「架空の項目」）" in why


def test_figure_caption_with_table_caption_style(tmp_path, journal, meta):
    """「図1 …」に表キャプションのスタイルを付けた段落は、理由 caption_style で、スタイルを直す文にする（表を作り直す文・候補は添えない）。"""
    def parts(b):
        return [cap("図1　架空の図"), mf.para(S["body"], "間の本文。"), mf.para(S["sec2"], "（１）次の節"), tb(first="架空の項目"),
                mf.para(S["body"], "後ろの本文。")]
    res, root = run(tmp_path, journal, meta, parts)
    (b,) = res.bodyless_tables
    assert (b.tid, b.why, b.candidates) == ("T1", "caption_style", [])
    act = next(a for a in actions(res) if a.key == "table_body")
    assert "キャプションが「図」で始まるのに表キャプションのスタイルです" in act.top
    assert "Word の表に作り直して" not in act.top and "折り返し" not in act.top
    assert "Word で表をキャプションのすぐ後ろに置いて" not in act.checklist and "表ごとの直し方のとおりに" in act.checklist


def test_same_number_english_caption_reason(tmp_path, journal, meta):
    """和文の「表1」の後ろの同じ番号の英文の「Table 1」（本体なし）は、理由 same_number で、直前のキャプションを添えて 1 つの段落に
    まとめる文にする。"""
    res, root = run(tmp_path, journal, meta, lambda b: [cap("表1　架空の甲"), cap("Table 1　Fictional"), tb(),
                                                         mf.para(S["body"], "後ろの本文。")])
    (b,) = res.bodyless_tables
    t = nodes(res)
    assert (b.tid, b.why, b.why_ref, b.candidates) == ("T2", "same_number", t["T1"].caption.src, [])
    why = table_body_why(b)
    assert "直前の表キャプション（" in why and "「表1　架空の甲」" in why and "Shift+Enter" in why
    assert "Word の表に作り直して" not in why


def test_other_reason_mentions_table_image(tmp_path, journal, meta):
    """理由がその他の文には、表の画像を貼ってもよいことを添える。共通の文は「表の題だけが表示されます」と言い切らない。"""
    res, root = run(tmp_path, journal, meta, text_body)
    act = next(a for a in actions(res) if a.key == "table_body")
    assert "表の画像をキャプションのすぐ後ろの段落に貼ってもかまいません" in act.top
    assert "表の題だけが表示されます" not in act.top and "別の所に出ていることがあります" in act.top


def test_no_table_body_for_normal_and_image_tables(tmp_path, journal, meta):
    """正常な表・画像で貼った表（画像をまだ入れていなくても、置き場所をすべて書いた XML に <graphic> がある）・表で組んだ図には出ない。"""
    from conftest import TABLEFIG

    res, root = run(tmp_path, journal, meta, lambda b: [cap("表1　架空の正常な表"), tb()], name="normal")
    assert res.bodyless_tables == [] and "table_body" not in keys(res)
    (tmp_path / "img").mkdir()
    path = tmp_path / "img" / "tab.docx"
    mf.make_table_images(path, "tab_next")
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "img" / "out"))
    assert res.bodyless_tables == [] and "table_body" not in keys(res)
    res = convert(TABLEFIG, meta, journal, Options(out_dir=tmp_path / "tf"))
    assert res.bodyless_tables == []


# ---------------------------------------------------------------------------- B7a. 分かれた表
def parts_of(res):
    return [(p.kind, p.node.tid, p.head.tid if p.head is not None else None) for p in res.plan.table_parts]


def test_split_tables_after_captioned_table(tmp_path, journal, meta):
    """キャプション付きの表のすぐ後ろ（間は空の段落）に続くキャプションのない表は、split として記録する（XML はつながない）。"""
    res, root = run(tmp_path, journal, meta, lambda b: [cap("表1　架空の分かれた表"), tb(3), mf.para(S["body"], ""), tb(3),
                                                         mf.para(S["body"], ""), tb(3), mf.para(S["body"], "後ろの本文。")])
    assert wraps(root) == [("T1", True, "表1　架"), ("T2", True, None), ("T3", True, None)]
    assert parts_of(res) == [("split", "T2", "T1"), ("split", "T3", "T1")]


def test_split_not_recorded_without_caption_at_head(tmp_path, journal, meta):
    """連なりの最初の表にキャプションがないとき（キャプションのない表が 2 つ続く・1 行目のセルにキャプションがある表に続く表）は
    記録しない。本文の段落をはさむ表も記録しない。"""
    res, root = run(tmp_path, journal, meta, lambda b: [
        tb(), tb(),
        mf.table([[mf.cell(mf.para(S["tab_cap"], "表1　セルの中の架空の表"), span=2)], [mf.cell("甲"), mf.cell("1")]]), tb(),
        cap("表2　架空の表"), tb(), mf.para(S["body"], "間の本文。"), tb()], name="nohead")
    assert [p for p in parts_of(res) if p[0] == "split"] == []


# ---------------------------------------------------------------------------- B7b. 表のセルの中のキャプション
def test_cell_captions_are_recorded(tmp_path, journal, meta):
    """表の 1 行目のセルの表キャプション・途中の行の表キャプション・セルの図キャプションを記録する（XML は表のまま）。"""
    def parts(b):
        im = b.add_image("g1.png", mf.png_bytes("fig"))
        return [
            mf.table([[mf.cell(cap("表1　セルの中の架空の表"), span=2)], [mf.cell("項目"), mf.cell("値")], [mf.cell("甲"), mf.cell("1")]]),
            mf.para(S["body"], "間の本文。"),
            mf.table([[mf.cell(cap("表2　架空の甲"), span=2)], [mf.cell("甲"), mf.cell("1")],
                      [mf.cell(cap("表3　架空の乙"), span=2)], [mf.cell("乙"), mf.cell("2")]]),
            mf.para(S["body"], "間の本文。"),
            mf.table([[mf.cell(mf.para(S["body"], mf.drawing(im, 1800000, 1200000, 601)))],
                      [mf.cell(mf.para(S["fig_cap"], "図1　セルの中の架空の図"))]]),
            mf.para(S["body"], "図1 を見る。")]
    res, root = run(tmp_path, journal, meta, parts)
    assert [w[1:] for w in wraps(root)] == [(True, None)] * 3
    got = [(p.kind, p.node.tid, p.row, _text(p.para)[:3]) for p in res.plan.table_parts]
    assert got == [("cell_table_cap_first", "T1", 1, "表1　"), ("cell_table_cap_first", "T2", 1, "表2　"),
                   ("cell_table_cap_mid", "T2", 3, "表3　"), ("cell_fig_cap", "T3", 2, "図1　")]
    assert not list(root.iter("fig"))


def test_cell_captions_not_recorded_for_table_figures_and_float_cells(tmp_path, journal, meta):
    """表で組んだ図の本体の表（セルに「図1」の段落があっても）と、浮動配置の図形の中のセルの図（図に組むもの）は記録しない。
    キャプションの形でないセルの「表1 の…。」の本文も記録しない。"""
    from conftest import CELLS, TABLEFIG
    for name, path in (("cells", CELLS), ("tablefig", TABLEFIG)):
        res = convert(path, meta, journal, Options(out_dir=tmp_path / name))
        assert [p for p in res.plan.table_parts if p.kind.startswith("cell_")] == [], name
    res, root = run(tmp_path, journal, meta, lambda b: [
        mf.table([[mf.cell(mf.para(S["fig_cap"], "図1　セルの架空の図")), mf.cell("値")], [mf.cell("甲"), mf.cell("1")]]),
        mf.para(S["fig_cap"], "図1　架空の表で組んだ図"),
        mf.para(S["body"], "間の本文。"), cap("表1　架空の表"), mf.table([[mf.cell("表1 の値は架空の値である。"), mf.cell("値")]])], name="fig")
    assert root.find(".//fig/table-wrap") is not None or root.find(".//fig//table") is not None
    assert [p for p in res.plan.table_parts if p.kind.startswith("cell_")] == []


def _text(p):
    from jasme_jats.article import _para_text
    return _para_text(p)


# ---------------------------------------------------------------------------- B8. 要確認 table_parts
def test_table_parts_is_to_check_with_rows_in_chapter3(tmp_path, journal, meta, capsys):
    """分かれた表とセルの中のキャプションは、1 つの要確認 table_parts にまとめる（終了コードは変えない）。3 章に 1 か所 1 行。"""
    from conftest import META_EXAMPLE

    from jasme_jats import colab
    from jasme_jats.cli import main as cli_main

    def parts(b):
        im = b.add_image("g1.png", mf.png_bytes("fig"))
        return [cap("表1　架空の分かれた表"), tb(3), mf.para(S["body"], ""), tb(3), mf.para(S["body"], ""), tb(3),
                mf.para(S["body"], "間の本文。"),
                mf.table([[mf.cell(cap("表2　セルの中の架空の表"), span=2)], [mf.cell("甲"), mf.cell("1")],
                          [mf.cell(cap("表3　架空の乙"), span=2)], [mf.cell("乙"), mf.cell("2")]]),
                mf.para(S["body"], "間の本文。"),
                mf.table([[mf.cell(mf.para(S["body"], mf.drawing(im, 1800000, 1200000, 601)))],
                          [mf.cell(mf.para(S["fig_cap"], "図1　セルの中の架空の図"))]])]
    res, root = run(tmp_path, journal, meta, parts)
    act = next(a for a in actions(res) if a.key == "table_parts")
    assert act.level == TO_CHECK
    assert "表の組み立てを確かめてください（4 か所。3 章）" in act.top
    assert "表 T1「表1　架空の分かれた表」のすぐ後ろに、キャプションのない表 T2・T3 が続いています" in act.top
    assert "表 T4 の 1 行目のセルに表キャプション「表2　セルの中の架空の表」" in act.top and "本文の「表2」" in act.top
    assert "表 T4 の 3 行目のセルに表キャプション「表3　架空の乙」" in act.top
    assert "表 T5 のセルに図キャプション「図1　セルの中の架空の図」" in act.top and "置き場所 fig01" in act.top
    assert "対応する表（図）が見つからない" in act.top
    assert "table_body" not in keys(res)
    report = res.report_path.read_text(encoding="utf-8")
    ch3 = report.split("## 3.")[1].split("## 4.")[0]
    assert ch3.count("| 表の組み立て |") == 4
    assert "（要確認）**表の組み立ての確認 4 か所**" in report.split("## することの一覧")[1].split("## 1.")[0]
    assert "表の組み立てを確かめてください（要確認）" in colab.result_boxes(res)
    code = cli_main([str(tmp_path / "t.docx"), "--meta", str(META_EXAMPLE), "--out", str(tmp_path / "cli")])
    err = capsys.readouterr().err
    assert "要確認: 表の組み立てを確かめること（4 か所" in err
    assert code == (1 if res.needs_action else 0)


def test_table_parts_alone_does_not_block(tmp_path, journal, meta):
    """要確認 table_parts だけなら、終了コードに数えない（needs_action は偽）。"""
    from jasme_jats.report import NEEDS_ACTION, blocking
    res, root = run(tmp_path, journal, meta, lambda b: [cap("表1　架空の分かれた表"), tb(3), mf.para(S["body"], ""), tb(3)])
    act = next(a for a in actions(res) if a.key == "table_parts")
    assert act.level != NEEDS_ACTION and act not in blocking(actions(res))
    assert not res.needs_action, [a.key for a in blocking(actions(res))]
    # 分かれた表だけのときは、一覧の行に「本文からリンクされる」と書かない（囲みの TABLE_PARTS_REFS と同じ条件）
    assert "リンク" not in act.checklist and "間の空の段落を消して表をつなぐ" in act.checklist
    # 見出しの種類は出ている行の種類だけ（一覧の行とコマンドライン）。枠と冒頭には、登載はこのままでもできると書く
    assert "セルの中のキャプション" not in act.checklist and "セルの中のキャプション" not in act.cli
    assert "（1 か所。分かれた表。XML は docx の表のまま" in act.cli
    from jasme_jats.report import TABLE_PARTS_AS_IS
    assert TABLE_PARTS_AS_IS in act.top and TABLE_PARTS_AS_IS in act.box_detail


def test_cell_figure_caption_after_image_mark_keeps_number(tmp_path, journal, meta):
    """セルの図キャプションの段落の先頭が画像（［画像］図3：…）でも、行の「本文の「図N」」に番号が入る。"""
    from jasme_jats.report import table_part_rows

    def parts(b):
        im = b.add_image("g3.png", mf.png_bytes("fig"))
        return [mf.table([[mf.cell(mf.para(S["fig_cap"], mf.drawing(im, 1800000, 1200000, 603), "図3：架空のセルの図"))],
                          [mf.cell("甲")]]),
                mf.para(S["body"], "図3 を見る。")]
    res, root = run(tmp_path, journal, meta, parts)
    rows = [row for row in table_part_rows(res.plan) if row[0] == "cell_fig_cap"]
    assert len(rows) == 1 and "本文の「図3」にリンクされません" in rows[0][3], rows
    act = next(a for a in actions(res) if a.key == "table_parts")      # セルの中の図キャプションだけ: 分かれた表・表のキャプションと書かない
    assert "セルの中のキャプション。Word で直すと、図になり、本文からリンクされる" in act.checklist
    assert "分かれた表" not in act.checklist and "分かれた表" not in act.cli


def test_no_table_parts_for_normal_tables(tmp_path, journal, meta):
    res, root = run(tmp_path, journal, meta, lambda b: [cap("表1　架空の正常な表"), tb(), mf.para(S["body"], "間。"),
                                                         cap("表2　架空の表"), tb()])
    assert "table_parts" not in keys(res) and res.plan.table_parts == []
