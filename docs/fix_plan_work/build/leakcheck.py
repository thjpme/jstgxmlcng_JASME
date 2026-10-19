"""handoff_pkg: 束に入れるファイルに、実際の論文（tests/private/ の PDF・docx）の文字と 12 文字以上一致する部分がないかを確かめる。

  python -I leakcheck.py FILELIST [--show] [--min 12]
FILELIST は S からの相対パスの一覧（1 行 1 つ。タブの後ろは無視）。
- 実際の論文の文字: tests/private/pdf/*.pdf と tests/private/colab/td*/td?.pdf（pypdfium2）、tests/private/colab/td*/td?.docx
  （docx の中の XML のすべての段落 w:p の w:t をつないだもの。本文・表・脚注・テキストボックス）。
- 比べ方: 両方から空白（全角空白・改行を含む）を除き、12 文字の窓がひとつでも一致すれば「一致」。NFKC で寄せた形でも比べる。
  束のファイルは、そのままの文字のほか、.py は文字列リテラル（隣り合うものをつないだもの）とコメント、.json はすべての文字列も見る。
- リポジトリに入っている文字（git ls-files のテキストと、tests/fixtures の docx・PDF の文字）にもある窓は「リポジトリにもある」
  として分ける（誌名の行など、論文の文字ではないもの）。
出力は端末だけ（一致した文字は --show のときだけ出す。実際の論文の文字なので、ファイルには書かない）。
"""
from __future__ import annotations

import ast
import io
import json
import re
import subprocess
import sys
import tokenize
import unicodedata
import zipfile
from pathlib import Path

S = Path("/tmp/claude-0/-home-user-jstgxmlcng-JASME/fb4d86bb-6ffb-5369-990a-10fe830c8789/scratchpad")
REPO = Path("/home/user/jstgxmlcng_JASME")
WS = re.compile(r"[\s　﻿​­￾￼]+")


def norm(t: str) -> str:
    return WS.sub("", t)


def pdf_text(p: Path) -> str:
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(p))
    try:
        return "\n".join(doc[i].get_textpage().get_text_range() for i in range(len(doc)))
    finally:
        doc.close()


def docx_paras(p: Path) -> list[str]:
    from lxml import etree
    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    out = []
    with zipfile.ZipFile(p) as z:
        for n in z.namelist():
            if not (n.startswith("word/") and n.endswith(".xml")):
                continue
            try:
                root = etree.fromstring(z.read(n))
            except etree.XMLSyntaxError:
                continue
            for para in root.iter(W + "p"):
                t = "".join(x.text or "" for x in para.iter(W + "t"))
                if t.strip():
                    out.append(t)
    return out


def grams(t: str, k: int) -> set[str]:
    return {t[i:i + k] for i in range(len(t) - k + 1)}


def py_strings(text: str) -> list[str]:
    """文字列リテラル（隣り合うものはつなぐ）とコメント。"""
    out, cur = [], []
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return []
    for tok in toks:
        if tok.type == tokenize.STRING:
            try:
                v = ast.literal_eval(tok.string)
                cur.append(v if isinstance(v, str) else v.decode("utf-8", "replace"))
            except Exception:  # noqa: BLE001  f 文字列など
                cur.append(re.sub(r"^[a-zA-Z]*['\"]{1,3}|['\"]{1,3}$", "", tok.string))
            continue
        if tok.type in (tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT) or tok.string in ("(", ")", "+"):
            continue
        if cur:
            out.append("".join(cur))
            cur = []
        if tok.type == tokenize.COMMENT:
            out.append(tok.string)
    if cur:
        out.append("".join(cur))
    return out


def json_strings(x) -> list[str]:
    if isinstance(x, str):
        return [x]
    if isinstance(x, dict):
        return [s for k, v in x.items() for s in [k] + json_strings(v)]
    if isinstance(x, list):
        return [s for v in x for s in json_strings(v)]
    return []


def views(p: Path) -> list[str]:
    raw = p.read_text(encoding="utf-8", errors="replace")
    vs = [raw, re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), raw)]
    if p.suffix == ".py":
        vs += py_strings(raw)
    elif p.suffix == ".json":
        try:
            vs += json_strings(json.loads(raw))
        except ValueError:
            pass
    return vs


def main():
    argv = sys.argv[1:]
    k = 12
    if "--min" in argv:
        i = argv.index("--min")
        k = int(argv[i + 1])
        del argv[i:i + 2]
    args = [a for a in argv if not a.startswith("--")]
    show = "--show" in argv
    files = [ln.split("\t")[0].strip() for ln in open(args[0], encoding="utf-8") if ln.strip()]
    # 実際の論文の文字
    srcs = {}
    for p in sorted((REPO / "tests" / "private" / "pdf").glob("*.pdf")):
        srcs[f"pdf/{p.name}"] = pdf_text(p)
    for d in sorted((REPO / "tests" / "private" / "colab").glob("td*")):
        for p in sorted(d.glob("td?.pdf")):
            srcs[f"colab/{d.name}/{p.name}"] = pdf_text(p)
        for p in sorted(d.glob("td?.docx")):
            srcs[f"colab/{d.name}/{p.name}"] = "\n".join(docx_paras(p))
    real = {}          # 窓 -> 出どころの名前の集合
    for mode in ("raw", "nfkc"):
        for name, t in srcs.items():
            t = norm(unicodedata.normalize("NFKC", t) if mode == "nfkc" else t)
            for g in grams(t, k):
                real.setdefault((mode, g), set()).add(name)
    # リポジトリに入っている文字
    repo_text = []
    for f in subprocess.run(["git", "-C", str(REPO), "ls-files"], capture_output=True, text=True, check=True).stdout.split("\n"):
        p = REPO / f
        if not f or not p.is_file():
            continue
        if p.suffix == ".docx":
            repo_text += docx_paras(p)
        elif p.suffix == ".pdf":
            repo_text.append(pdf_text(p))
        elif p.suffix in (".py", ".md", ".toml", ".json", ".yaml", ".yml", ".txt", ".ipynb", ".cfg", ".csv", ".xml", ".dtd",
                          ".html", ".js", ".css", ".sh", ".ini", ""):
            try:
                repo_text.append(p.read_text(encoding="utf-8"))
            except (UnicodeDecodeError, OSError):
                pass
    repo = set()
    for t in repo_text:
        repo |= grams(norm(t), k)
        repo |= grams(norm(unicodedata.normalize("NFKC", t)), k)
    print(f"実際の論文の文字: {len(srcs)} 個（{', '.join(srcs)}）、窓 {len(real)}、リポジトリの窓 {len(repo)}")
    total_hit, files_hit = 0, {}
    for rel in files:
        p = S / rel
        if not p.is_file():
            continue
        hits = {}       # 一致した文字（空白を除いた形） -> (出どころ, リポジトリにもあるか)
        for v in views(p):
            for mode in ("raw", "nfkc"):
                t = norm(unicodedata.normalize("NFKC", v) if mode == "nfkc" else v)
                i, n = 0, len(t)
                while i + k <= n:
                    g = t[i:i + k]
                    if (mode, g) in real:
                        j = i + k
                        while j < n and (mode, t[j - k + 1:j + 1]) in real:
                            j += 1
                        span = t[i:j]
                        names = set().union(*((real.get((mode, span[a:a + k])) or set()) for a in range(len(span) - k + 1)))
                        in_repo = all(span[a:a + k] in repo for a in range(len(span) - k + 1))
                        key = span
                        if key not in hits:
                            hits[key] = (sorted(names), in_repo, mode)
                        i = j
                    else:
                        i += 1
        # 短い一致が長い一致に含まれるなら、長いほうだけ
        keys = sorted(hits, key=len, reverse=True)
        kept = []
        for s in keys:
            if not any(s in t for t in kept):
                kept.append(s)
        if kept:
            files_hit[rel] = [(s, *hits[s]) for s in kept]
            total_hit += len(kept)
    print(f"調べたファイル {len(files)}、一致のあるファイル {len(files_hit)}、一致 {total_hit}")
    for rel, hs in sorted(files_hit.items()):
        only_repo = all(h[2] for h in hs)
        print(f"\n## {rel}  一致 {len(hs)}{'（すべてリポジトリにもある）' if only_repo else ''}")
        for s, names, in_repo, mode in sorted(hs, key=lambda h: (h[2], -len(h[0]))):
            txt = s if show else f"{s[:2]}…（{len(s)} 文字）"
            print(f"   {'[repo] ' if in_repo else ''}{mode} {len(s)} 文字 {', '.join(names)}: {txt}")


if __name__ == "__main__":
    main()
