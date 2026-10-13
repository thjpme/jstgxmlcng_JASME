"""文字の不変性チェックそのものが、改変を確実に検出できることを確かめる（わざと壊して試す）。"""
import copy

from lxml import etree

from conftest import FULL
from jasme_jats.builder import build, finalize, serialize
from jasme_jats.docx_reader import read_docx
from jasme_jats.fidelity import final_check, verify
from jasme_jats.linker import link
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


def test_untouched_passes(journal, meta):
    root, excl = tracked(journal, meta)
    res = verify(FULL, root, excl)
    assert res.ok


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
