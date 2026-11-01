"""gen_g.py の文字（文字列リテラル）が tests/private の docx の文字と 12 文字以上一致しないかを調べる（一致した件数と長さだけを出す）。"""
import ast, re, sys, zipfile
from pathlib import Path
from lxml import etree
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
N = 12
priv = []
for p in Path("/home/user/jstgxmlcng_JASME/tests/private").rglob("*.docx"):
    z = zipfile.ZipFile(p)
    for name in z.namelist():
        if name.startswith("word/") and name.endswith(".xml"):
            try:
                root = etree.fromstring(z.read(name))
            except Exception:
                continue
            for para in root.iter(W + "p"):
                priv.append("".join(t.text or "" for t in para.iter(W + "t")))
grams = set()
for s in priv:
    for i in range(len(s) - N + 1):
        grams.add(s[i:i + N])
lits = [n.value for n in ast.walk(ast.parse(Path("gen_g.py").read_text(encoding="utf-8")))
        if isinstance(n, ast.Constant) and isinstance(n.value, str)]
hits = 0
for s in lits:
    for i in range(len(s) - N + 1):
        if s[i:i + N] in grams:
            hits += 1
            print("一致: 文字列リテラルの", i, "文字目から（長さ", len(s), "）。ASCII だけか:", s[i:i+N].isascii())
            break
print("docx の数", len(list(Path('/home/user/jstgxmlcng_JASME/tests/private').rglob('*.docx'))), "段落", len(priv), "リテラル", len(lits), "一致", hits)

# 生成した docx の段落（テンプレート由来の段落も含む）でも確かめる
tmpl = set()
for name in ("word/document.xml",):
    root = etree.fromstring(zipfile.ZipFile("/home/user/jstgxmlcng_JASME/tests/fixtures/JASME_template_20261009.docx").read(name))
    for para in root.iter(W + "p"):
        tmpl.add("".join(t.text or "" for t in para.iter(W + "t")))
dh = 0
for p in sorted(Path("cases").glob("*.docx")):
    root = etree.fromstring(zipfile.ZipFile(p).read("word/document.xml"))
    for para in root.iter(W + "p"):
        s = "".join(t.text or "" for t in para.iter(W + "t"))
        if s in tmpl:
            continue
        if any(s[i:i + N] in grams for i in range(len(s) - N + 1)):
            dh += 1
            print("docx の段落で一致:", p.name, "長さ", len(s))
print("生成した docx の段落の一致", dh)
