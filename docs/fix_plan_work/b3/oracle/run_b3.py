"""B3 の反例（gen_b3.py が作った cases/）を、指定した src で変換し、期待と実際を比べる。

  python run_b3.py --src /home/user/jstgxmlcng_JASME/src --out <出力先> [--only P01,T02] [--keep]

ケースごとに OK / FAIL と理由を出し、<出力先>/results.json に実際の値（終了コード・本文の要素の並び・図の組み方・
要対応の行・途中で切れた案内の有無）と判定を書く。実行するのは python -m jasme_jats だけ。
--keep を付けなければ、大きな出力（docx・xml・zip・画像）を消し、レポート・依頼文・回答・標準出力は残す。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from lxml import etree

HERE = Path(__file__).resolve().parent
META = "/home/user/jstgxmlcng_JASME/examples/meta_example.toml"
PASS_LINES = ["文字の不変性チェック: 合格", "最終出力の再チェック: 合格", "DTD 検証: 合格", "J-STAGE のアップロード時チェック: 問題なし"]


def convert(src, docx, out, ai, response=None):
    cmd = [sys.executable, "-m", "jasme_jats", str(docx), "--meta", META, "--route", "docx", "--ai", ai, "--out", str(out)]
    if response:
        cmd += ["--ai-response", str(response)]
    env = dict(os.environ, PYTHONPATH=str(src), PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run(cmd, cwd="/tmp", env=env, capture_output=True, text=True, timeout=600)
    (out / "stdout.txt").write_text(p.stdout + "\n--- stderr ---\n" + p.stderr, encoding="utf-8")
    return p.returncode, p.stdout + p.stderr


# ----------------------------------------------------------------------------- 回答の段落 ID の読み替え
def id_map(request_text):
    paras = []
    for line in request_text.splitlines():
        mm = re.match(r"^\[(d\d+)\]（([^）]*)）(.*)$", line)
        if mm:
            paras.append((mm.group(1), mm.group(2), mm.group(3)))
    return paras


def resolver(paras):
    def plain(t):
        return re.sub(r"«([^→»]*)→[^»]*»", r"\1", t)

    def one(kind, arg):
        if kind == "p":
            hits = [i for i, _, t in paras if plain(t).startswith(arg)]
        else:   # img: その図形の中の、画像だけの段落
            hits = [i for i, info, t in paras if f"図形 {arg} の中" in info and re.fullmatch(r"\s*(⟦画像 [^⟧]*⟧\s*)+", t)]
        if not hits:
            raise KeyError(f"@{kind}:{arg} が依頼文の段落一覧にない")
        return hits[0]

    def sub(s):
        return re.sub(r"@(p|img):([^\"]*)", lambda mm: one(mm.group(1), mm.group(2)), s)
    return sub


def resolve(obj, sub):
    if isinstance(obj, str):
        return sub(obj)
    if isinstance(obj, list):
        return [resolve(x, sub) for x in obj]
    if isinstance(obj, dict):
        return {k: resolve(v, sub) for k, v in obj.items()}
    return obj


# ----------------------------------------------------------------------------- 実際の値
def cap_head(el):
    c = el.find("caption")
    if c is None:
        return "-"
    t = "".join(c.itertext()).strip()
    return re.split(r"[　 ]", t, 1)[0] if t else "-"


def inside_fig(el):
    p = el.getparent()
    while p is not None:
        if p.tag == "fig":
            return True
        p = p.getparent()
    return False


def body_sequence(root):
    seq = []
    for el in root.find("body").iter("p", "fig", "table-wrap"):
        if el.tag == "fig":
            seq.append(("fig", "fig:" + cap_head(el)))
        elif el.tag == "table-wrap":
            if not inside_fig(el):
                seq.append(("tw", "tw:" + cap_head(el)))
        elif el.getparent().tag in ("sec", "body"):
            seq.append(("p", "".join(el.itertext())))
    return seq


def figs(root):
    out = []
    for f in root.find("body").iter("fig"):
        out.append({"cap": cap_head(f), "graphic": f.find(".//graphic") is not None,
                    "table": f.find(".//table-wrap") is not None})
    return out


def sections(report):
    secs, cur, buf = {}, "head", []
    for line in report.splitlines():
        mm = re.match(r"^## (\d+)\.", line)
        if mm:
            secs[cur] = "\n".join(buf)
            cur, buf = mm.group(1), []
        buf.append(line)
    secs[cur] = "\n".join(buf)
    secs["1"] = secs.get("head", "") + "\n" + secs.get("1", "")
    return secs


def notices(sec1, topic):
    lines = [x for x in sec1.splitlines() if "要対応" in x and "要対応 0" not in x and not x.startswith("|")]
    if topic == "float":
        lines = [x for x in lines if re.search(r"図表|図形|位置", x) and "XML に入らなかった画像" not in x]
    return lines


def label(item):
    return item[1] if item[0] != "p" else "p:" + item[1][:12]


def match_items(got, want):
    if len(got) != len(want):
        return False
    for g, w in zip(got, want):
        if w.startswith("p:"):
            if not (g[0] == "p" and g[1].startswith(w[2:])):
                return False
        elif label(g) != w:
            return False
    return True


# ----------------------------------------------------------------------------- 判定
def check(c, act):
    """1 つの期待を確かめる。(合否, 理由)。"""
    t = c["t"]
    seq = act.get("seq")
    if t == "exit":
        return act["exit"] in c["in"], f"終了コード {act['exit']}（期待 {c['in']}）"
    if t == "any":
        rs = []
        for alt in c["alts"]:
            sub = [check(x, act) for x in alt]
            if all(ok for ok, _ in sub):
                return True, "どちらか: " + " / ".join(r for _, r in sub)
            rs.append(" & ".join(r for ok, r in sub if not ok))
        return False, "どれにも当たらない: " + " | ".join(rs)
    if t == "hint":
        ok = "途中で切れ" in act["stdout"] or "途中で切れ" in act.get("report", "")
        return ok, "途中で切れている可能性の案内" + ("あり" if ok else "がない")
    if seq is None:
        return False, "XML がない（変換が止まった）"
    if t in ("seq_after", "seq_before"):
        idx = [k for k, x in enumerate(seq) if x[0] == "p" and x[1].startswith(c["anchor"])]
        if not idx:
            return False, f"段落「{c['anchor']}」が本文にない"
        k, n = idx[0], len(c["items"])
        got = seq[k + 1:k + 1 + n] if t == "seq_after" else seq[max(0, k - n):k]
        ok = match_items(got, c["items"])
        return ok, f"「{c['anchor'][:8]}」の{'後' if t == 'seq_after' else '前'}: {[label(x) for x in got]}（期待 {c['items']}）"
    if t in ("seq_last", "seq_first"):
        n = len(c["items"])
        got = seq[-n:] if t == "seq_last" else seq[:n]
        ok = match_items(got, c["items"])
        return ok, f"本文の{'最後' if t == 'seq_last' else '最初'}: {[label(x) for x in got]}（期待 {c['items']}）"
    if t == "fig":
        fs = [f for f in act["figs"] if f["cap"] == c["cap"]]
        if not fs:
            return False, f"キャプション {c['cap']} の図がない"
        f = fs[0]
        bad = [k for k in ("graphic", "table") if k in c and f[k] != c[k]]
        return not bad, f"{c['cap']}: graphic={f['graphic']} table-wrap={f['table']}" + (f"（期待と違う: {bad}）" if bad else "")
    if t == "no_top_tw":
        tws = [label(x) for x in seq if x[0] == "tw"]
        return not tws, f"本文の表: {tws}"
    if t == "top_tw":
        tws = [label(x) for x in seq if x[0] == "tw"]
        return f"tw:{c['cap']}" in tws, f"本文の表: {tws}（期待 tw:{c['cap']}）"
    if t == "no_fig_cap":
        bad = [f["cap"] for f in act["figs"] if f["cap"].startswith(c["prefix"])]
        return not bad, f"キャプションが「{c['prefix']}」の図: {bad}"
    if t in ("notice_float", "notice_any"):
        lines = notices(act["secs"].get("1", ""), "float" if t == "notice_float" else "any")
        if c["present"] != bool(lines):
            return False, f"要対応の行 {len(lines)} 件（期待 {'あり' if c['present'] else 'なし'}）" + (
                f": {lines[0][:120]}" if lines else "")
        if c.get("words_any") and lines and not any(w in x for x in lines for w in c["words_any"]):
            return False, f"要対応の文言に {c['words_any']} のどれもない: {lines[0][:160]}"
        return True, f"要対応の行 {len(lines)} 件"
    if t == "no_words":
        where = {"stdout": act["stdout"], "sec1": act["secs"].get("1", ""), "sec3": act["secs"].get("3", ""),
                 "sec14": act["secs"].get("14", ""), "note": act["secs"].get("1", "")}
        hits = [(w, word) for w in c["where"] for word in c["words"] if word in where[w]]
        return not hits, ("文言が残る: " + ", ".join(f"{w} に「{word}」" for w, word in sorted(set(hits)))) if hits else "文言 OK"
    return False, f"知らない期待 {t}"


def run_case(src, cdir, out, keep):
    c = json.loads((cdir / "case.json").read_text(encoding="utf-8"))
    out.mkdir(parents=True, exist_ok=True)
    resp_path = None
    if c["response"] is not None:
        pre = out / "pre"
        pre.mkdir(exist_ok=True)
        convert(src, cdir / "doc.docx", pre, "manual")
        sub = resolver(id_map((pre / "AI依頼文.txt").read_text(encoding="utf-8")))
        text = json.dumps(resolve(c["response"], sub), ensure_ascii=False, indent=None)
        if c.get("cut"):
            marker = sub(c["cut"]["after"])
            k = text.index(marker)
            text = text[:k + len(marker)]
        resp_path = out / "response.json"
        resp_path.write_text(text, encoding="utf-8")
    run = out / "run"
    if run.exists():
        shutil.rmtree(run)
    run.mkdir()
    code, stdout = convert(src, cdir / "doc.docx", run, c["ai"], resp_path)
    act = {"exit": code, "stdout": stdout}
    xmls = sorted(run.glob("*.xml"))
    reps = sorted(run.glob("*変換レポート.md"))
    act["report"] = reps[0].read_text(encoding="utf-8") if reps else ""
    act["secs"] = sections(act["report"])
    if xmls and code != 2:
        root = etree.fromstring(xmls[0].read_bytes().split(b"\n", 2)[2])
        act["seq"] = body_sequence(root)
        act["figs"] = figs(root)
    results = []
    expect = list(c["expect"])
    may_stop = any(x["t"] == "exit" and x["in"] == [2] for x in expect)
    if code != 2:
        miss = [x for x in PASS_LINES if x not in stdout]
        results.append((not miss, "チェック: " + ("すべて合格" if not miss else f"合格でない {miss}"), "原則"))
        lost = "XML に入らなかった画像" in stdout
        results.append((not lost, "XML に入らなかった画像" + ("がある" if lost else "なし"), "原則"))
    elif not may_stop and not any(x["t"] == "any" for x in expect):
        results.append((False, "変換が止まった（終了コード 2）", "原則"))
    for x in expect:
        ok, why = check(x, act)
        results.append((ok, why, x.get("why", "")))
    if not keep:
        for p in out.rglob("*"):
            if p.is_file() and p.suffix.lower() in (".docx", ".xml", ".zip", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".emf"):
                p.unlink()
    summary = {"exit": code, "seq": [label(x) for x in act.get("seq", [])], "figs": act.get("figs"),
               "float_notices": [x[:200] for x in notices(act["secs"].get("1", ""), "float")],
               "notices": [x[:200] for x in notices(act["secs"].get("1", ""), "any")],
               "hint": "途中で切れ" in stdout or "途中で切れ" in act["report"],
               "stdout_tail": [x for x in stdout.splitlines() if "仮に" in x or "要対応" in x or "AI" in x][:6]}
    return c, results, summary


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cases", default=str(HERE / "cases"))
    ap.add_argument("--only", default="")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args(argv)
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    only = set(filter(None, a.only.split(",")))
    allres, n_ok = [], 0
    for cdir in sorted(Path(a.cases).iterdir()):
        if not (cdir / "case.json").exists() or (only and cdir.name not in only):
            continue
        c, results, summary = run_case(Path(a.src).resolve(), cdir, out / cdir.name, a.keep)
        ok = all(r[0] for r in results)
        n_ok += ok
        print(f"{'OK  ' if ok else 'FAIL'} {c['id']} [{c['grade']}] {c['title']}")
        for r in results:
            if not r[0]:
                print(f"     - {r[1]}" + (f"  〔{r[2]}〕" if r[2] else ""))
        allres.append({"id": c["id"], "title": c["title"], "grade": c["grade"], "ok": ok,
                       "checks": [{"ok": r[0], "got": r[1], "why": r[2]} for r in results], "actual": summary})
    (out / "results.json").write_text(json.dumps(allres, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{n_ok}/{len(allres)} 件が期待どおり（結果: {out / 'results.json'}）")
    return 0 if n_ok == len(allres) else 1


if __name__ == "__main__":
    sys.exit(main())
