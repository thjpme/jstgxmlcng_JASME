"""docx の読み取り: 中間表現の文字列が、独立に取り出した docx の文字列と一致すること。"""
import pytest

from conftest import ALL_DOCS, EDGE, FLOAT, FULL
from jasme_jats.docx_reader import read_docx
from jasme_jats.omml import math_plain, omml_to_mathml
from jasme_jats.ooxml import DocxPackage, canonical_text, paragraph_ids


def atoms_text(p):
    out = []
    for a in p.atoms:
        if a.kind == "text":
            out.append(a.text)
        elif a.kind == "math":
            out.append(math_plain(omml_to_mathml(a.math, a.display)[0]))
    return "".join(out)


@pytest.mark.parametrize("path", ALL_DOCS + [FLOAT], ids=lambda p: p.name)
def test_reader_matches_canonical(path):
    doc = read_docx(path)
    root = DocxPackage(path).xml("word/document.xml")
    canon = {pid: canonical_text(p) for p, pid in paragraph_ids(root, "d").items()}
    paras = list(doc.all_paragraphs())
    assert paras
    for p in paras:
        assert atoms_text(p) == canon[p.src], p.src


def test_edge_cases():
    doc = read_docx(EDGE)
    texts = {p.src: p.text_only() for p in doc.all_paragraphs()}
    joined = "\n".join(texts.values())
    # 隠し文字と削除された変更履歴は出力しない。挿入は出力する
    assert "（隠し文字）" not in joined
    assert "削除済み" not in joined
    assert "挿入済み" in joined
    assert doc.hidden_text and doc.hidden_text[0][1] == "（隠し文字）"
    assert doc.tracked_changes == 2
    # 記号フォントの α、改行
    assert "記号α" in joined
    assert "改行\nの後" in joined
    # テキストボックスの中身は 1 回だけ読む（mc:Fallback を二重に数えない）
    tb = [p.text_only() for p in doc.all_paragraphs() if p.in_textbox]
    assert tb.count("図1　テキストボックス内のキャプション") == 1
    # テキストボックスの中の表も読む
    assert "問1　架空の問題文である。" in joined and "根拠を示す" in joined
    # テキストボックスの中の画像は、テキストボックスの段落の画像として 1 回だけ読む（外側の図形の画像にしない）
    tbimg = [p.in_textbox for p in doc.all_paragraphs() for a in p.atoms
             if a.kind == "image" and a.image.target == "word/media/tbfig.png"]
    assert tbimg == [True]
    assert [i.target for i in doc.images].count("word/media/tbfig.png") == 1
    # フィールドのハイパーリンク
    hrefs = {a.href for p in doc.all_paragraphs() for a in p.atoms if a.kind == "text" and a.href}
    assert "https://example.net/field" in hrefs
    assert "https://example.com/a?b=1&c=2" in hrefs
    # Word の脚注
    assert "5" in doc.footnotes


def test_images_and_math_detected():
    doc = read_docx(FULL)
    assert [i.target for i in doc.images] == ["word/media/fig1.png", "word/media/fig2.png", "word/media/eq1.png"]
    displays = [a for p in doc.all_paragraphs() for a in p.atoms if a.kind == "math" and a.display]
    assert len(displays) == 1
