"""反例集を、指定したコードで実行する。

  python run_all.py <src のフォルダ> [反例のファイル ...] [--name 名前] [-v]

- <src のフォルダ> を PYTHONPATH の先頭に入れた別のプロセスで実行する（どのコードを読んだかを jasme_jats.__file__ と版で表示する）。
- 反例のファイルを省くと、このフォルダの cases_*.py をすべて実行する。
- 結果を表で出し、JSON を results_<名前>.json に保存する。名前を省くと、src のフォルダの親の名前（.../wt_head/src なら wt_head）。
- 各反例の作業ファイル（docx・直した docx・XML・レポート）は _work/<名前>/<反例の名前>/ に残す。
- -v を付けると、OK でない段落の元の文字・直した後の文字・truth も出す。
書式と判定は runner.py の docstring。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_cases(files) -> list:
    cases = []
    for f in files:
        spec = importlib.util.spec_from_file_location(Path(f).stem, f)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for c in mod.CASES:
            c = dict(c)
            c["_file"] = Path(f).name
            cases.append(c)
    names = [c["name"] for c in cases]
    dup = {n for n in names if names.count(n) > 1}
    if dup:
        raise SystemExit(f"反例の名前が重なっている: {sorted(dup)}")
    return cases


def worker(name, files, out_json):
    """子のプロセス: 反例を実行して JSON に書く。"""
    sys.path.insert(0, str(HERE))
    import jasme_jats
    from runner import run_case
    info = {"jasme_jats": jasme_jats.__file__, "version": getattr(jasme_jats, "__version__", "?"), "cases": []}
    print(f"読んだコード: {info['jasme_jats']}（版 {info['version']}）", flush=True)
    for c in load_cases(files):
        r = run_case(c, HERE / "_work" / name / c["name"])
        r["file"] = c["_file"]
        info["cases"].append(r)
        print(f"  {r['verdict']:8} {c['name']}", flush=True)
    Path(out_json).write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")


def show(info, verbose=False):
    print()
    print(f"コード: {info['jasme_jats']}（版 {info['version']}）")
    rows = [("判定", "反例", "item", "angle", "expect", "OK でない段落")]
    for r in info["cases"]:
        bad = [p for p in r["paras"] if p["verdict"] != "OK"]
        detail = "; ".join(f"{p['label']}({p['src']}) {p['verdict']}: {p['reason']}" for p in bad)
        if r["error"]:
            detail = (f"[{r['error'].strip().splitlines()[-1][:200]}] " + detail).strip()
        exp = r["expect"] if isinstance(r["expect"], str) else json.dumps(r["expect"], ensure_ascii=False)
        rows.append((r["verdict"], r["name"], str(r["item"]), str(r["angle"]), exp, detail or "-"))
    w = [max(len(x[k]) for x in rows) for k in range(5)]
    for x in rows:
        print("  ".join(x[k].ljust(w[k]) for k in range(5)) + "  " + x[5])
    n = {v: sum(1 for r in info["cases"] if r["verdict"] == v) for v in ("OK", "REPORTED", "FAIL")}
    print(f"\n合計 {len(info['cases'])} 件: OK {n['OK']}・REPORTED {n['REPORTED']}・FAIL {n['FAIL']}")
    if verbose:
        for r in info["cases"]:
            for p in r["paras"]:
                if p["verdict"] == "OK":
                    continue
                print(f"\n[{r['name']}] {p['label']}({p['src']}) {p['verdict']}")
                print(f"  元の docx : {p['original']}")
                print(f"  直した後  : {p['fixed']}")
                print(f"  truth     : {p['truth']}")
                print(f"  理由      : {p['reason']}")
            if r["error"]:
                print(f"\n[{r['name']}] エラー: {r['error']}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="反例集を指定したコードで実行する")
    ap.add_argument("src", help="jasme_jats を含む src のフォルダ")
    ap.add_argument("files", nargs="*", help="反例のファイル（省くと cases_*.py をすべて）")
    ap.add_argument("--name", help="結果の名前（results_<名前>.json）")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--worker", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    src = Path(a.src).resolve()
    files = [str(Path(f).resolve()) for f in a.files] or [str(p) for p in sorted(HERE.glob("cases_*.py"))]
    name = a.name or (src.parent.name if src.name == "src" else src.name)
    if a.worker:
        worker(name, files, a.worker)
        return 0
    if not (src / "jasme_jats" / "__init__.py").exists():
        raise SystemExit(f"{src} に jasme_jats がない")
    out_json = HERE / f"results_{name}.json"
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(src), str(HERE)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    env.pop("PYTHONHOME", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"     # 指定したコードのフォルダに __pycache__ を作らない
    cmd = [sys.executable, str(Path(__file__).resolve()), str(src), *files, "--name", name, "--worker", str(out_json)]
    proc = subprocess.run(cmd, env=env, cwd=str(HERE))
    if proc.returncode != 0:
        raise SystemExit(f"子のプロセスが止まった（終了コード {proc.returncode}）")
    info = json.loads(out_json.read_text(encoding="utf-8"))
    if not Path(info["jasme_jats"]).resolve().is_relative_to(src):
        print(f"警告: 指定したコード（{src}）ではなく {info['jasme_jats']} を読んだ", file=sys.stderr)
    show(info, a.verbose)
    print(f"\n結果: {out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
