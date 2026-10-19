"""handoff_pkg: 確かめの道具が読むファイルを、道具の中身（パスの文字・シェルの変数・Path の式・import）からたどって一覧にする。

  python -I trace.py [--show-dirs] [--outdirs] [--why]      # 一覧（S からの相対パス）を標準出力に。外したものは stderr に理由付きで
SEEDS（手で決めた出発点）から始め、*.py・*.sh の中の参照を、見つからなくなるまでたどる。束に入れるかどうかの規則は EXCLUDE。
"""
from __future__ import annotations

import glob
import os
import re
import sys
from pathlib import Path

S = Path("/tmp/claude-0/-home-user-jstgxmlcng-JASME/fb4d86bb-6ffb-5369-990a-10fe830c8789/scratchpad")
REPO = Path("/home/user/jstgxmlcng_JASME")
SP = str(S)

# 出発点（S からの相対。glob 可）
SEEDS = [
    "fixB2r4/tools/*.py", "fixB2r4/tools/*.sh", "fixB2r4/tools/pt/*.py", "fixB2r4/gen.sh", "fixB2r4/snap.sh",
    "n10/judge/tools/*.py", "n10/judge/tools/*.sh", "n10/judge/tools/pt/*.py",
    "n10/judge/realpdf/check.py", "n10/pytest_src.sh",
    "b2_review/r5p/run_gen.sh", "b2_review/r4p/h2.py",
    "b2_review/r3p/exp/gen_*.py", "b2_review/r4p/exp/gen_*.py", "b2_review/r4reg/exp/gen_*.py",
    "b2_review/r5p/exp/gen_*.py", "b2_review/r5reg/exp/gen_*.py", "fixB2r4/exp/gen_*.py",
    "oracle/runner.py", "oracle/run_all.py", "oracle/cases_*.py",
    "golden/golden.py",
    "fixB/fixB_all.py", "rvB2/rvB2_mkdocx.py",
    "rvB4_regress/fuzz/gen*.py", "rvB4_regress/fuzz/judge*.py", "rvB4_regress/fuzz/run*.py",
    "rvB8_regress/fuzz8/gen*.py", "rvB8_regress/fuzz8/judge*.py", "rvB8_regress/fuzz8/run*.py",
    "rvB8_regress/fuzz8/run*.sh", "rvB8_regress/fuzz8/sum8.sh",
    "realpdf_B/check.py",
    # 単位 B2.1（作業中のワークフローの道具。束を作った時点の写し）
    "b21/*/tools/*.py", "b21/*/tools/*.sh", "b21/*/tools/pt/*.py", "b21/*/cases*.py", "b21/*/cases/*.py",
    "b21/*/exp/*.py", "b21/*/exp/gens/*.py",
    # 文書
    "n10/DESIGN_N10.md", "b21/DESIGN_B21.md", "session_notes.md", "handoff/*.md",
]
DOCS = {"n10/DESIGN_N10.md", "b21/DESIGN_B21.md", "session_notes.md"}
# 道具が読む入力の json（結果ではないもの）。名前の形で決める
INPUT_JSON = [re.compile(r"^rvB2p/fz\d+\.json$"), re.compile(r"^rvB9p/bound\d+\.json$")]
BAD_PARTS = {"logs", "v", "out", "_work", "__pycache__", "venv310", "docx", "gen", "dump", "tmp", "td", "realpdf_out_prev",
             "out_saved_before_final", "lo_profile", "nb", "dbg", "dbg_work", "oracle_results", "suite", "run"}
BAD_SUFFIX = {".docx", ".pdf", ".xml", ".zip", ".png", ".jpg", ".jpeg", ".log", ".pyc", ".patch", ".diff", ".txt", ".out"}


# restore.sh が作り直すもの（束に入れない）
RESTORED = {
    "rvB_regress_mut/": "tests/ の写し（restore.sh が git archive 1fe3bc7 から作る）",
    "b21/isolate/realpdf/check.py": "n10/judge/realpdf/check.py と同じ（restore.sh が写す）",
    "fixB2r4/realpdf/check.py": "n10/judge/realpdf/check.py と同じ（restore.sh が写す）",
}


def exclude(rel: str) -> str | None:
    parts = rel.split("/")
    for k, why in RESTORED.items():
        if rel == k or (k.endswith("/") and rel.startswith(k)):
            return why
    if rel in DOCS or (parts[0] == "handoff" and rel.endswith(".md")):
        return None
    for p in parts[:-1]:
        if p in BAD_PARTS:
            return f"出力のフォルダ（{p}）"
        if p.endswith("_src") or p == "src" or p.startswith("wt_") or p.endswith("_snapshot"):
            return f"コードの写し（{p}）"
    name = parts[-1]
    suf = Path(name).suffix.lower()
    if suf in BAD_SUFFIX:
        return f"{suf} は入れない"
    if name == "cases.json":
        return "fuzz の cases.json（regen_fuzz.sh で作り直す）"
    if suf == ".md":
        return "文書以外の .md（変換のレポートなど）"
    if suf == ".json":
        if any(r.match(rel) for r in INPUT_JSON):
            return None
        return "結果の json"
    if suf not in (".py", ".sh"):
        return f"{suf or '拡張子なし'} は入れない"
    if suf == ".py" and _first_line(S / rel) in SRC_HEADS:
        return "コードの写し（jasme_jats のモジュールと同じ書き出し）"
    return None


def _first_line(p: Path) -> str:
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            return f.readline().strip()
    except OSError:
        return ""


SRC_HEADS = {h for h in (_first_line(q) for q in (REPO / "src" / "jasme_jats").glob("*.py")) if len(h) > 12}


def under_s(p: str) -> str | None:
    p = os.path.normpath(p)
    if p == SP or not p.startswith(SP + "/"):
        return None
    return p[len(SP) + 1:]


def expand(pattern: str) -> list[str]:
    pattern = re.sub(r"\*+", "*", pattern)
    if "*" in pattern or "?" in pattern or "[" in pattern:
        if pattern.count("*") > 6:
            return []
        try:
            return sorted(glob.glob(pattern))
        except re.error:
            return []
    return [pattern] if os.path.exists(pattern) else []


# ---------------------------------------------------------------- シェル
SH_ASSIGN = re.compile(r"(?:^|[\s;(&|])([A-Za-z_]\w*)=(\"[^\"]*\"|'[^']*'|[^\s;)&|]*)")
SH_FOR = re.compile(r"\bfor\s+([A-Za-z_]\w*)\s+in\s+([^;\n]+)")
SH_TOKEN = re.compile(r"(?:\$\{?[A-Za-z_]\w*\}?|" + re.escape(SP) + r")(?:/[^\s\"'`;|&<>()]*)?")


def sh_vars(text: str) -> dict[str, set[str]]:
    v: dict[str, set[str]] = {"S": {SP}}
    for name, val in SH_ASSIGN.findall(text):
        val = val.strip("\"'")
        m = re.match(r"\$\{\*:-\"?([^}\"]*)\"?\}", val)
        if m:
            continue
        v.setdefault(name, set()).add(val)
    for name, words in SH_FOR.findall(text):
        for w in words.split():
            w = w.strip("\"'")
            if w.startswith("$"):
                continue
            v.setdefault(name, set()).add(w)
    v["S"] = {SP}
    return v


def sh_subst(s: str, v: dict[str, set[str]], depth=0) -> set[str]:
    m = re.search(r"\$\{?([A-Za-z_]\w*)(?:[%#:][^}]*)?\}?", s)
    if not m or depth > 6:
        return {s}
    name = m.group(1)
    vals = v.get(name) or {"*"}
    if len(vals) > 40:
        vals = {"*"}
    out = set()
    for val in vals:
        if "$" + name in val or "${" + name in val:
            val = "*"
        out |= sh_subst(s[:m.start()] + val + s[m.end():], v, depth + 1)
    return out


def refs_sh(path: Path, text: str) -> set[str]:
    v = sh_vars(text)
    out = set()
    for tok in SH_TOKEN.findall(text):
        for s in sh_subst(tok, v):
            s = re.sub(r"\$\{?[^/]*", "*", s)
            if s.startswith("/"):
                out.add(s)
    # 同じフォルダの .sh を . で読む・sh で動かす（相対）
    for m in re.finditer(r"(?:^|[\s;])(?:\.|sh|python3?(?: -I)?)\s+([\w./-]+\.(?:sh|py))", text):
        p = m.group(1)
        if not p.startswith("/") and not p.startswith("$"):
            out.add(str(path.parent / p))
    return out


# ---------------------------------------------------------------- Python
STR = r"(?:[fr]?\"[^\"\n]*\"|[fr]?'[^'\n]*')"
PY_EXPR = re.compile(r"\b([A-Za-z_]\w*(?:\.parent|\.parents\[\d\])*)((?:\s*/\s*(?:" + STR + r"|[A-Za-z_]\w*))+)")
PY_ASSIGN = re.compile(r"^\s*([A-Za-z_]\w*)\s*=\s*(.+?)\s*(?:#.*)?$", re.M)
ABS = re.compile(re.escape(SP) + r"[^\s\"'`)\]};,:]*")


def py_str(tok: str) -> str:
    tok = tok.strip()
    if tok[:1] in "fr":
        f = tok[0] == "f"
        tok = tok[1:]
    else:
        f = False
    s = tok[1:-1]
    if f:
        s = re.sub(r"\{[^}]*\}", "*", s)
    return s


def py_eval(expr: str, env: dict[str, str], here: Path) -> str | None:
    expr = expr.strip()
    expr = re.sub(r"^str\((.*)\)$", r"\1", expr)
    m = re.match(r"^Path\((" + STR + r")\)(.*)$", expr)
    if m:
        base, rest = py_str(m.group(1)), m.group(2)
    else:
        m = re.match(r"^Path\(__file__\)(?:\.resolve\(\))?(.*)$", expr)
        if m:
            base, rest = str(here / "__FILE__"), m.group(1)
        else:
            m = re.match(r"^([A-Za-z_]\w*)(.*)$", expr)
            if not m or m.group(1) not in env:
                return None
            base, rest = env[m.group(1)], m.group(2)
    p = base
    while rest.strip():
        rest = rest.strip()
        m = re.match(r"^\.parent\b(.*)$", rest)
        if m:
            p, rest = str(Path(p).parent), m.group(1)
            continue
        m = re.match(r"^\.parents\[(\d)\](.*)$", rest)
        if m:
            p, rest = str(Path(p).parents[int(m.group(1))]), m.group(2)
            continue
        m = re.match(r"^\.resolve\(\)(.*)$", rest)
        if m:
            rest = m.group(1)
            continue
        m = re.match(r"^/\s*(" + STR + r")(.*)$", rest)
        if m:
            p, rest = p + "/" + py_str(m.group(1)), m.group(2)
            continue
        m = re.match(r"^/\s*([A-Za-z_]\w*)(.*)$", rest)
        if m:
            p, rest = p + "/*", m.group(2)
            continue
        return None
    return p


def refs_py(path: Path, text: str) -> tuple[set[str], set[str]]:
    env: dict[str, str] = {"S": SP}
    here = path.parent
    for name, rhs in PY_ASSIGN.findall(text):
        r = py_eval(rhs, env, here)
        if r is not None:
            env[name] = r
    out = set()
    for m in ABS.finditer(text):
        out.add(re.sub(r"\{[^}]*\}", "*", m.group(0)))
    for m in PY_EXPR.finditer(text):
        r = py_eval(m.group(0), env, here)
        if r is not None and r.startswith("/"):
            out.add(r)
    # sys.path に入れるフォルダ
    dirs = {str(here)}
    for m in re.finditer(r"sys\.path\.(?:insert\(\s*\d+\s*,|append\()\s*(.+?)\)\s*(?:#.*)?$", text, re.M):
        r = py_eval(m.group(1), env, here)
        if r is None:
            try:
                r = py_str(m.group(1))
            except Exception:  # noqa: BLE001
                r = None
        if r and r.startswith("/"):
            dirs.add(r)
    mods = set()
    for m in re.finditer(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w., ]+))", text, re.M):
        for x in (m.group(1) or m.group(2)).split(","):
            x = x.strip().split(" as ")[0].strip().split(".")[0]
            if x:
                mods.add(x)
    for d in dirs:
        for x in mods:
            q = Path(d) / f"{x}.py"
            if q.exists():
                out.add(str(q))
    return out, dirs


def main():
    files: dict[str, str] = {}
    excluded: dict[str, tuple[str, str]] = {}
    dirs_seen: dict[str, str] = {}
    queue = []
    for pat in SEEDS:
        for p in expand(str(S / pat)):
            rel = under_s(p)
            if rel and os.path.isfile(p):
                queue.append((rel, "SEED"))
    while queue:
        rel, by = queue.pop(0)
        if rel in files or rel in excluded:
            continue
        why = exclude(rel)
        if why:
            excluded[rel] = (why, by)
            continue
        files[rel] = by
        p = S / rel
        if p.suffix not in (".py", ".sh"):
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        refs = refs_sh(p, text) if p.suffix == ".sh" else refs_py(p, text)[0]
        for r in refs:
            for q in expand(r):
                qr = under_s(os.path.realpath(q)) or under_s(q)
                if not qr:
                    continue
                if os.path.isdir(q):
                    dirs_seen.setdefault(qr, rel)
                    continue
                if qr not in files and qr not in excluded:
                    queue.append((qr, rel))
    for rel in sorted(files):
        print(rel + ("\t<- " + files[rel] if "--why" in sys.argv else ""))
    for rel, (why, by) in sorted(excluded.items()):
        print(f"EXCLUDED\t{rel}\t{why}\t<- {by}", file=sys.stderr)
    if "--outdirs" in sys.argv:
        # 道具が書く出力のフォルダ（束には空のフォルダとして入れる。中身は入れない）
        outs = set()
        for rel, (why, by) in excluded.items():
            if why.startswith("出力のフォルダ"):
                parts = rel.split("/")
                for i, p in enumerate(parts[:-1]):
                    if p in BAD_PARTS:
                        if p != "__pycache__" and not any(q.endswith("_src") or q == "src" or q.startswith("wt_") for q in parts[:i]):
                            outs.add("/".join(parts[:i + 1]))
                        break
        for d in sorted(outs):
            print(f"OUTDIR\t{d}", file=sys.stderr)
    if "--show-dirs" in sys.argv:
        for d, by in sorted(dirs_seen.items()):
            print(f"DIR\t{d}\t<- {by}", file=sys.stderr)


if __name__ == "__main__":
    main()
