"""gen_h.py に書いた架空の文字（文字列の定数）が、tests/private の実際の論文（docx・PDF）の文字と 12 文字以上一致しないかを数える。
一致した文字は表示しない（件数と、どの定数かの番号だけ）。"""
import ast
import re
import subprocess
import sys
import unicodedata
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRIV = Path("/home/user/jstgxmlcng_JASME/tests/private")
N = 12


def norm(s):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s))


lits = [n.value for n in ast.walk(ast.parse((HERE / "gen_h.py").read_text(encoding="utf-8")))
        if isinstance(n, ast.Constant) and isinstance(n.value, str)]
import json

lits += [p["plain"] for c in json.loads((HERE / "cases.json").read_text(encoding="utf-8")) for p in c["paras"]]
lits = [x for x in lits if len(norm(x)) >= N]
corpus = []
for p in sorted(PRIV.rglob("*.docx")):
    z = zipfile.ZipFile(p)
    for name in z.namelist():
        if name.startswith("word/") and name.endswith(".xml"):
            xml = z.read(name).decode("utf-8", "ignore")
            corpus.append(norm("".join(re.findall(r"<w:t(?: [^>]*)?>([^<]*)</w:t>", xml))))
for p in sorted(PRIV.rglob("*.pdf")):
    cp = subprocess.run(["pdftotext", str(p), "-"], capture_output=True, text=True)
    corpus.append(norm(cp.stdout))
big = "\n".join(corpus)
hits = 0
for k, s in enumerate(lits):
    t = norm(s)
    if any(t[i:i + N] in big for i in range(len(t) - N + 1)):
        hits += 1
        print(f"一致あり: 定数 {k}（{len(t)} 字）")
print(f"文字列の定数と段落の文字 {len(lits)} 件（{N} 字以上）、実際の論文の docx・PDF {len(corpus)} 件と比べて、{N} 字以上の一致 {hits} 件")
sys.exit(1 if hits else 0)
