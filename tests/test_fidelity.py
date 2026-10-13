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


def _wrap_char(root, pred, make):
    """span の直下の文字のうち、pred に合う最初の 1 文字を make(文字) が返す目印の要素に入れる。"""
    for sp in root.iter(SPAN):
        t = sp.text or ""
        i = next((k for k, c in enumerate(t) if pred(c)), None)
        if i is None:
            continue
        el = make(t[i])
        el.tail = t[i + 1:]
        sp.text = t[:i]
        sp.insert(0, el)
        return sp.get("src")
    raise AssertionError("該当する文字がない")


def _marker(tag, text, orig=None):
    el = etree.Element(tag)
    if orig is not None:
        el.set("o", orig)
    el.text = text
    return el


def test_pdf_width_change_is_verified(journal, meta):
    from jasme_jats.tracking import WIDTH
    root, excl = tracked(journal, meta)
    # 半角の英数字を全角にした（出版版 PDF に合わせた）ものは、元の文字として照合して合格
    src = _wrap_char(root, lambda c: c.isascii() and c.isalnum(), lambda c: _marker(WIDTH, chr(ord(c) + 0xFEE0), c))
    res = verify(FULL, root, excl)
    assert res.ok and len(res.pdf_width) == 1 and res.pdf_width[0][0] == src
    data = serialize(finalize(root))
    assert final_check(root, data, res)
    # 全角・半角の違いでない変更は、元の文字を正しく書いていても不合格
    root, excl = tracked(journal, meta)
    _wrap_char(root, lambda c: c == "の", lambda c: _marker(WIDTH, "が", c))
    res = verify(FULL, root, excl)
    assert not res.ok and res.bad_pdf and "全角・半角の違いではない" in res.bad_pdf[0][1]


def test_pdf_drop_must_be_whitespace(journal, meta):
    from jasme_jats.tracking import PDFDROP
    root, excl = tracked(journal, meta)
    _wrap_char(root, lambda c: c == " ", lambda c: _marker(PDFDROP, c))
    res = verify(FULL, root, excl)
    assert res.ok and len(res.pdf_drops) == 1
    data = serialize(finalize(root))
    assert final_check(root, data, res)
    # 空白でない文字を落とそうとしたら不合格
    root, excl = tracked(journal, meta)
    _wrap_char(root, lambda c: c == "の", lambda c: _marker(PDFDROP, c))
    res = verify(FULL, root, excl)
    assert not res.ok and "空白でない文字" in res.bad_pdf[0][1]
