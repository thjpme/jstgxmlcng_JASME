"""文字の不変性チェックそのものが、改変を確実に検出できることを確かめる（わざと壊して試す）。"""
import copy

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
    res = convert(FULL, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    assert not res.fidelity.ok and res.fidelity.conflicts and res.fidelity.bad_excluded
    sec5 = res.report_path.read_text(encoding="utf-8").split("## 5.")[1].split("## 6.")[0]
    assert "XML に出力したのに、出力しない段落としても記録されている段落（変換ツールの不具合）" in sec5
    assert "空白だけの段落として出力しなかったのに、docx では空白以外の文字がある段落（変換ツールの不具合）" in sec5
    assert "すべての段落で一致しました" not in sec5
