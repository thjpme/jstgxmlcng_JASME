"""実際の原稿 46 docx を両ルートで変換し直し、基準（0.31.1 の出力。runs/）と比べる。

  python regress.py <タグ>            … runs_<タグ>/ に出力して、基準との差を表示する（4 並列。数分かかる）
  python regress.py <タグ> --show N   … 差のある XML の差分を、ファイルごとに N 行まで表示する
  python regress.py <タグ> --base X   … 基準を runs_X/ にする（既定は runs/）
  python regress.py <タグ> --extra    … AI 役の回答のある docx を、ほかに AI なし（*_none）と手動・回答なし（*_m0）でも変換する
                                        （W8 の手順 0〜。基準に同じ組がなければ「基準なし」。*_none の XML は、同じ回の *_m0 と比べる）

比べるもの: XML（タグごとに改行して比べる）、要対応・要確認の key、不変性チェック・DTD・補完の確かめ、状態。
AI が要る docx は、基準と同じ AI 役の回答（manual/…/answer.json）を反映して変換する。
"""
import difflib, json, re, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

S = Path(__file__).resolve().parent.parent
D = Path("/home/user/jstgxmlcng_JASME/tests/private/drive")
tag = sys.argv[1]
show = int(sys.argv[sys.argv.index("--show") + 1]) if "--show" in sys.argv else 0
OUT = S / f"runs_{tag}"
BASE = S / (f"runs_{sys.argv[sys.argv.index('--base') + 1]}" if "--base" in sys.argv else "runs")
extra = "--extra" in sys.argv
jobs = []
for d in sorted(D.iterdir()):
    pdf = sorted(d.glob("*.pdf"))[0]
    for x in sorted(d.glob("*.docx")):
        ans = S / "manual" / d.name / x.stem / "prompt" / "answer.json"
        for route in ("docx", "pdf"):
            sub = route + ("_ai" if ans.exists() else "")
            base = BASE / d.name / x.stem / sub
            if (base / "summary.json").exists():
                jobs.append((x, pdf, route, ans if ans.exists() else None, OUT / d.name / x.stem / sub, base))
                if extra and ans.exists():
                    for ex, ai in (("_none", "none"), ("_m0", "manual")):
                        jobs.append((x, pdf, route, ai, OUT / d.name / x.stem / (route + ex), BASE / d.name / x.stem / (route + ex)))


def run(j):
    x, pdf, route, ans, out, base = j
    if not (out / "summary.json").exists():
        if isinstance(ans, str):        # --extra の組: 回答なし（ans は AI の方法）
            cmd = [sys.executable, str(S / "tools/one.py"), str(x), str(pdf), route, ans, str(out)]
        else:
            cmd = [sys.executable, str(S / "tools/one.py"), str(x), str(pdf), route, "manual" if ans else "none", str(out)] + ([str(ans)] if ans else [])
        subprocess.run(cmd, capture_output=True, timeout=1800)


with ThreadPoolExecutor(4) as ex:
    list(ex.map(run, jobs))


def lines(p):
    return re.sub(r">\s*<", ">\n<", p.read_text(encoding="utf-8")).split("\n")


def keys(s):
    return sorted(f"{a[0]}:{a[1]}" for a in s.get("actions", []))


same = diff = 0
for x, pdf, route, ans, out, base in jobs:
    name = f"{out.parent.parent.name}/{out.parent.name[:28]}/{out.name}"
    if not (base / "summary.json").exists() and (out / "summary.json").exists():
        b = json.load(open(out / "summary.json"))
        print("・", name, "| 基準なし:", b.get("status"), "知らせ", ",".join(keys(b)), "needs_action", b.get("needs_action"))
        diff += 1; continue
    try:
        a, b = json.load(open(base / "summary.json")), json.load(open(out / "summary.json"))
    except Exception as e:
        print("!!", name, "結果なし", e); diff += 1; continue
    notes = []
    for k in ("status", "fid_ok", "final_ok", "dtd", "supplement", "needs_action"):
        if a.get(k) != b.get(k): notes.append(f"{k}: {a.get(k)}→{b.get(k)}")
    if keys(a) != keys(b):
        notes.append("知らせ: -" + ",".join(sorted(set(keys(a)) - set(keys(b)))) + " +" + ",".join(sorted(set(keys(b)) - set(keys(a)))))
    if b.get("status") == "CRASH": notes.append("例外: " + b.get("message", "")[-300:])
    d = []
    if a.get("xml") and b.get("xml") and Path(a["xml"]).exists() and Path(b["xml"]).exists():
        d = [l for l in difflib.unified_diff(lines(Path(a["xml"])), lines(Path(b["xml"])), lineterm="", n=0) if l[:1] in "+-" and l[:3] not in ("+++", "---")]
        if d: notes.append(f"XML の差 {len(d)} 行")
    if notes:
        diff += 1; print("≠", name, "|", " / ".join(notes))
        for l in d[:show]: print("    ", l[:200])
    else:
        same += 1
print(f"同じ {same} 件、違う {diff} 件（計 {len(jobs)} 件）")
if extra:   # AI なし（*_none）の XML が、同じ回の手動・回答なし（*_m0）の XML と同じか
    ok = ng = 0
    for x, pdf, route, ans, out, base in jobs:
        if not out.name.endswith("_none"):
            continue
        m0 = out.parent / (route + "_m0")
        try:
            a, b = json.load(open(m0 / "summary.json")), json.load(open(out / "summary.json"))
        except Exception as e:
            print("!! none/m0", out, e); ng += 1; continue
        if b.get("status") != "done" or a.get("status") != "done":
            print("≠ none/m0", out.parent.parent.name, out.name, a.get("status"), b.get("status")); ng += 1; continue
        same_xml = Path(a["xml"]).read_bytes() == Path(b["xml"]).read_bytes()
        if same_xml: ok += 1
        else: ng += 1; print("≠ none/m0 XML", out.parent.parent.name, out.parent.name[:20], out.name)
    print(f"AI なしと手動・回答なしの XML: 同じ {ok} 件、違う {ng} 件")
