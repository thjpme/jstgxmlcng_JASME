"""文字の不変性チェックそのものが、改変を確実に検出できることを確かめる（わざと壊して試す）。"""
import copy

import pytest
from lxml import etree

from conftest import FULL
from jasme_jats import pipeline
from jasme_jats.builder import build, finalize, serialize
from jasme_jats.docx_reader import read_docx
from jasme_jats.fidelity import DROP, final_check, source_texts, verify
from jasme_jats.linker import link
from jasme_jats.model import Exclusion
from jasme_jats.pipeline import Options, convert
from jasme_jats.structure import classify
from jasme_jats.tracking import SPAN


def tracked(journal, meta):
    doc = read_docx(FULL)
    plan = classify(doc, journal)
    link(plan)
    root, info = build(plan, meta, journal)
    return root, plan.exclusions + info.exclusions


def first_text_span(root):
    for sp in root.iter(SPAN):
        if sp.text and len(sp.text) > 5:
            return sp
    raise AssertionError


def remove_paragraph(root, src):
    """段落 src の目印（出力した文字と落とした空白）をすべて取り除く（その段落を出力しなかったことにする）。"""
    for el in [e for e in root.iter(SPAN, DROP) if e.get("src") == src]:
        el.getparent().remove(el)


def test_untouched_passes(journal, meta):
    root, excl = tracked(journal, meta)
    res = verify(FULL, root, excl)
    assert res.ok and res.conflicts == [] and res.bad_excluded == []


def test_changed_character_is_detected(journal, meta):
    root, excl = tracked(journal, meta)
    sp = first_text_span(root)
    sp.text = sp.text[:-1] + ("X" if sp.text[-1] != "X" else "Y")
    res = verify(FULL, root, excl)
    assert not res.ok and res.mismatches and res.mismatches[0].src == sp.get("src")


def test_removed_paragraph_is_detected(journal, meta):
    root, excl = tracked(journal, meta)
    sp = first_text_span(root)
    sp.getparent().remove(sp)
    res = verify(FULL, root, excl)
    assert not res.ok and any(s == sp.get("src") for s, _ in res.missing)


def test_added_text_is_detected(journal, meta):
    root, excl = tracked(journal, meta)
    p = root.find(".//body//p")
    p.append(etree.Element("bold"))
    p[-1].text = "追加"
    res = verify(FULL, root, excl)
    assert not res.ok and res.stray


def test_duplicated_paragraph_is_detected(journal, meta):
    root, excl = tracked(journal, meta)
    sp = first_text_span(root)
    sp.getparent().append(copy.deepcopy(sp))
    res = verify(FULL, root, excl)
    assert not res.ok and sp.get("src") in res.duplicates


def test_final_check_detects_serialization_change(journal, meta):
    root, excl = tracked(journal, meta)
    res = verify(FULL, root, excl)
    data = serialize(finalize(root))
    assert final_check(root, data, res)
    broken = data.replace("はじめに".encode(), "おわりに".encode(), 1)
    assert not final_check(root, broken, res)


def test_output_and_excluded_paragraph_is_detected(journal, meta):
    """出力した段落が、出力しなかった段落（除外）にも登録されていたら不合格（レポートの 6 章と食い違う）。"""
    root, excl = tracked(journal, meta)
    src = first_text_span(root).get("src")
    res = verify(FULL, root, excl + [Exclusion(src, "試験の除外", "x")])
    assert not res.ok and [(s, reason) for s, reason, _ in res.conflicts] == [(src, "試験の除外")]
    assert src not in [s for s, _, _ in res.excluded]


def test_blank_exclusion_with_text_is_detected(journal, meta):
    """空白だけの段落として除外したのに、docx では空白以外の文字がある段落は不合格。"""
    root, excl = tracked(journal, meta)
    src = first_text_span(root).get("src")
    remove_paragraph(root, src)
    text = source_texts(FULL)[src]
    res = verify(FULL, root, excl + [Exclusion(src, "空白のみの段落", "", blank=True)])
    assert not res.ok and res.bad_excluded == [(src, "空白のみの段落", text)]
    assert res.missing == []        # 除外には記録されている（出力漏れではない）


def test_second_blank_exclusion_of_a_paragraph_is_checked(journal, meta):
    """同じ段落に除外が 2 件あり、2 件目だけが blank の場合も、blank の除外の文字を確かめる（最初の 1 件だけを見ない）。"""
    root, excl = tracked(journal, meta)
    src = first_text_span(root).get("src")
    remove_paragraph(root, src)
    text = source_texts(FULL)[src]
    res = verify(FULL, root, excl + [Exclusion(src, "試験の除外", text), Exclusion(src, "空白のみの段落", "", blank=True)])
    assert not res.ok and res.bad_excluded == [(src, "空白のみの段落", text)]
    assert (src, "試験の除外", text) in res.excluded       # 6 章には 1 件目の理由で載る


def test_conflicts_and_bad_exclusions_are_reported(journal, meta, tmp_path, monkeypatch):
    """出力と除外の重なりと、文字のある blank の除外は、レポートの 5 章に「変換ツールの不具合」として出る。"""
    orig = pipeline.verify

    def broken(docx_path, root, exclusions):
        spans = [e.get("src") for e in root.iter(SPAN) if e.text and len(e.text) > 5]
        out, blank = spans[0], spans[-1]
        remove_paragraph(root, blank)
        return orig(docx_path, root, list(exclusions) + [Exclusion(out, "試験の除外", "x"),
                                                         Exclusion(blank, "空白のみの段落", "", blank=True)])
    monkeypatch.setattr(pipeline, "verify", broken)
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path))
    assert not res.fidelity.ok and res.fidelity.conflicts and res.fidelity.bad_excluded
    sec5 = res.report_path.read_text(encoding="utf-8").split("## 5.")[1].split("## 6.")[0]
    assert "XML に出力したのに、出力しない段落としても記録されている段落（変換ツールの不具合）" in sec5
    assert "空白だけの段落として出力しなかったのに、docx では空白以外の文字がある段落（変換ツールの不具合）" in sec5
    assert "すべての段落で一致しました" not in sec5


def _tracked_reader(journal, meta):
    from conftest import READER
    doc = read_docx(READER)
    plan = classify(doc, journal)
    link(plan)
    root, info = build(plan, meta, journal)
    return READER, doc, root, plan.exclusions + info.exclusions


def test_joined_and_hidden_text_follow_the_same_policy(journal, meta):
    """検証の docx 側の文字（source_texts）も、読み取りと同じく段落記号の削除でつなぎ（後ろの段落の ID は欠番）、スタイルの
    隠し文字を隠す（修正計画の G）。欠番の ID の文字を出力したり、隠した文字を出力したりすると不合格になる。"""
    path, doc, root, excl = _tracked_reader(journal, meta)
    src = source_texts(path)
    first, srcs = doc.joined[0]
    assert srcs[1] not in src and src[first].endswith("次の段落の後半の文がつながる。")
    assert not any("〔" in t for t in src.values())
    assert verify(path, root, excl).ok
    # 欠番の ID の目印は、docx にない段落（unknown）として不合格
    bad = copy.deepcopy(root)
    sp = next(e for e in bad.iter(SPAN) if e.get("src") == first)
    extra = copy.deepcopy(sp)
    extra.set("src", srcs[1])
    sp.addnext(extra)
    res = verify(path, bad, excl)
    assert not res.ok and srcs[1] in res.unknown
    # スタイルで隠した文字を出力すると、文字の不一致
    bad = copy.deepcopy(root)
    sp = next(e for e in bad.iter(SPAN) if (e.text or "").startswith("文字スタイルで"))
    sp.text = sp.text.replace("文字スタイルで", "文字スタイルで〔文字スタイルで隠す〕")
    res = verify(path, bad, excl)
    assert not res.ok and [m.src for m in res.mismatches] == [sp.get("src")]


def test_textbox_in_deleted_run_is_not_counted(journal, meta, tmp_path):
    """削除の変更履歴のランの中のテキストボックスは、中の段落の文字が w:t のままでも、Word で承諾すると図形ごと消える。
    読み取りは図形を読まないので、検証（source_texts）も、その段落を欠番にする（読み取り・検証・ルート2 の 3 か所が同じ）。
    欠番にしないと「欠けた段落」の偽の不合格（要対応）になる。"""
    import zipfile

    import make_fixtures as mf
    from jasme_jats.ooxml import HiddenRule, in_deleted_run, paragraph_ids, parse_xml, preprocess
    from jasme_jats.pdfdocx import _chains, paragraph_units, raw_paragraph_ids
    S = mf.S
    box = mf.vml_textbox(mf.para(S["body"], "削除された囲みの中の文字"))     # 中は w:t のまま
    wrapped = ('<w:del w:id="9101" w:author="試験" w:date="2026-01-01T00:00:00Z">' + box + "</w:del>")

    def parts(b):
        return [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "前の文。", wrapped, "後ろの文。")]
    path = tmp_path / "delbox.docx"
    mf.make_article(path, "削除された囲みの検証用文書", parts)
    doc = read_docx(path)
    read = {p.src: p.plain() for p in doc.all_paragraphs()}
    assert "削除された囲みの中の文字" not in "".join(read.values())
    src = source_texts(path)
    assert "削除された囲みの中の文字" not in "".join(src.values())
    with zipfile.ZipFile(path) as z:
        root = parse_xml(z.read("word/document.xml"))
        rule = HiddenRule(preprocess(parse_xml(z.read("word/styles.xml"))))
    ids = paragraph_ids(preprocess(parse_xml(zipfile.ZipFile(path).read("word/document.xml"))), "d")
    inner = [pid for p, pid in ids.items() if in_deleted_run(p)]
    assert len(inner) == 1 and inner[0] not in src and inner[0] not in read
    # ルート2 の段落の文字も、外側の段落を読み取りと同じに組み立てる（削除された図形で _Complex にしない）
    raw, chains = raw_paragraph_ids(root, "d"), _chains(root, "d")
    outer = next(s for s, t in read.items() if t.startswith("前の文。"))
    assert "".join(c for c, _, _ in paragraph_units(raw[outer], rule)) == read[outer] == src[outer] == "前の文。後ろの文。"
    # 変換全体も不合格にならない
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    assert res.fidelity.ok and res.fidelity.final_ok


def test_unreadable_final_output_gets_its_own_notice(journal, meta, tmp_path, monkeypatch):
    """最終出力が XML として読めないとき（実体参照の不備など）の要対応は、「本文が docx と一致していません」ではなく、
    読めないこと・この XML は登載に使わないこと・開発者に知らせることを言う（F14）。文字の違いで不合格のときは従来の文。"""
    from jasme_jats import pipeline
    from jasme_jats.pipeline import Options, convert
    from jasme_jats.report import NEEDS_ACTION, actions
    real = pipeline.serialize
    monkeypatch.setattr(pipeline, "serialize", lambda root: real(root).replace(b"</p>", b"&foo;</p>", 1))
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path / "bad"))
    assert res.fidelity.final_ok is False and res.fidelity.final_unreadable and res.needs_action
    [act] = [a for a in actions(res) if a.key == "fidelity"]
    assert act.level == NEEDS_ACTION
    for text in (act.top, act.box_detail, act.cli):
        assert "読めません" in text and "登載に使わ" in text and "一致していません" not in text and "差分" not in text, text
    assert "読めなかった理由" in act.box_detail and "開発者" in act.box_detail
    monkeypatch.setattr(pipeline, "serialize", lambda root: real(root).replace("はじめに".encode(), "おわりに".encode(), 1))
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path / "diff"))
    [act] = [a for a in actions(res) if a.key == "fidelity"]
    assert not res.fidelity.final_unreadable and "一致していません" in act.box_detail and "5 章" in act.top


def test_entity_declaration_in_final_output_is_unreadable_notice(journal, meta, tmp_path, monkeypatch):
    """最終出力に実体の宣言（<!ENTITY）があるとき（F6 で不合格）も、「出力された XML の本文が docx と一致していません」ではなく、
    読めない・登載に使わない・開発者に知らせる側の要対応（F14）を出す。文字は変わっていないので、差分の案内は誤りになる。"""
    from jasme_jats import pipeline
    from jasme_jats.pipeline import Options, convert
    from jasme_jats.report import NEEDS_ACTION, actions
    real = pipeline.serialize
    monkeypatch.setattr(pipeline, "serialize", lambda root: real(root).replace(b'.dtd">', b'.dtd" [<!ENTITY foo "abc">]>', 1))
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path / "ent"))
    assert res.fidelity.ok and res.fidelity.final_ok is False and res.fidelity.final_unreadable
    assert "<!ENTITY" in res.fidelity.final_detail and res.needs_action
    [act] = [a for a in actions(res) if a.key == "fidelity"]
    assert act.level == NEEDS_ACTION
    for text in (act.top, act.box_detail, act.cli):
        assert "読めません" in text and "登載に使わ" in text and "一致していません" not in text and "差分" not in text, text


@pytest.mark.parametrize("unreadable", [b'.dtd">|.dtd" [<!ENTITY foo "abc">]>', b"</p>|&foo;</p>"], ids=["entity-declaration", "undefined-entity"])
def test_h6_unreadable_and_different_text_both_reported(unreadable, journal, meta, tmp_path, monkeypatch):
    """H6: 最終出力が読めない（実体の宣言・未定義の実体参照）うえに、本文の文字も違うときは、読めないことと文字の差分の両方を
    要対応の文に出す（以前は、読めない側の文だけで、差分があることが消えた）。どちらも、この XML は登載に使わない。
    読めないだけのとき・文字の差分だけのときの文は変えない。"""
    from jasme_jats import pipeline
    from jasme_jats.pipeline import Options, convert
    from jasme_jats.report import NEEDS_ACTION, actions
    real = pipeline.serialize
    a, b = unreadable.split(b"|")

    def broken(root):
        return real(root).replace(a, b, 1).replace("はじめに".encode(), "おわりに".encode(), 1)
    monkeypatch.setattr(pipeline, "serialize", broken)
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path / "both"))
    fid = res.fidelity
    assert fid.final_ok is False and fid.final_unreadable and fid.final_differs and res.needs_action
    [act] = [x for x in actions(res) if x.key == "fidelity"]
    assert act.level == NEEDS_ACTION
    for text in (act.top, act.checklist, act.box_title, act.box_detail, act.cli):
        assert "読め" in text, text
    for text in (act.top, act.box_detail, act.cli):
        assert "XML として読めません" in text or "XML として読めず" in text
        assert "docx と一致していません" in text or "docx と一致していないので" in text, text
        assert "登載に使わ" in text and "5 章" in text, text
    assert fid.final_detail
    # 読めないだけのときは、差分の文を出さない
    monkeypatch.setattr(pipeline, "serialize", lambda root: real(root).replace(a, b, 1))
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path / "only"))
    assert res.fidelity.final_unreadable and not res.fidelity.final_differs
    [act] = [x for x in actions(res) if x.key == "fidelity"]
    assert "一致していません" not in act.top + act.box_detail and "一致していないので" not in act.cli
