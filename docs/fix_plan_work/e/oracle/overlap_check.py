"""gen_e.py・run_e.py の架空の文字が、tests/private の実際の論文の文字と 12 文字以上一致しないかを確かめる（実際の文字は出さない）。"""
import ast
import re
import sys
import zipfile
from pathlib import Path

PRIV = Path("/home/user/jstgxmlcng_JASME/tests/private")
TEMPLATE = Path("/home/user/jstgxmlcng_JASME/tests/fixtures/JASME_template_20261009.docx")
N = 12


def docx_text(p):
    out = []
    with zipfile.ZipFile(p) as z:
        for n in z.namelist():
            if n.startswith("word/") and n.endswith(".xml"):
                x = z.read(n).decode("utf-8", "replace")
                out.append("".join(re.findall(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>", x)))
    return "\n".join(out)


def literals(path):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


priv = {p.name: docx_text(p) for p in PRIV.rglob("*.docx")}
tmpl = docx_text(TEMPLATE)
grams = {}
for name, t in priv.items():
    t = t.replace("\n", "")
    for i in range(len(t) - N + 1):
        grams.setdefault(t[i:i + N], set()).add(name)
hits = []
for f in sys.argv[1:]:
    for s in literals(f):
        for i in range(len(s) - N + 1):
            g = s[i:i + N]
            if g in grams and g not in tmpl:
                hits.append((f, i, sorted(grams[g])))
print(f"private docx: {len(priv)} 本, 調べた文字列のファイル: {sys.argv[1:]}")
print(f"{N} 文字以上一致: {len(hits)} 件" + ("" if not hits else f"（位置のみ: {hits[:5]}）"))
# 文末脚注の有無（件数だけ）
for name in sorted(priv):
    pass
for p in sorted(PRIV.rglob("*.docx")):
    with zipfile.ZipFile(p) as z:
        en = z.read("word/endnotes.xml").decode("utf-8", "replace") if "word/endnotes.xml" in z.namelist() else ""
        fnx = z.read("word/footnotes.xml").decode("utf-8", "replace") if "word/footnotes.xml" in z.namelist() else ""
        doc = z.read("word/document.xml").decode("utf-8", "replace")
    print(p.relative_to(PRIV), "endnotes:", len(re.findall(r"<w:endnote [^>]*w:id=\"[1-9]", en)),
          "endnoteReference:", doc.count("<w:endnoteReference"), "footnotes:", len(re.findall(r"<w:footnote [^>]*w:id=\"[1-9]", fnx)),
          "footnoteReference:", doc.count("<w:footnoteReference"))
