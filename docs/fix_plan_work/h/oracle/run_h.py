"""単位 H の反例（gen_h.py の cases.json）を、指定した src で変換し、期待と比べる。

  python run_h.py --src <src> [--python <python>] [--label <名前>] [--ref <比べる相手の label>] [--only ID,...] [--keep]

  例: python run_h.py --src <作業ツリー>/src --label h --ref base0260   （out/base0260 は 0.26.0 の src の写しで流した結果）
  cases/*.docx がなければ、先に gen_h.py で作り直す。

- ケースごとに、子のプロセス（PYTHONPATH=<src>）で公開 API の jasme_jats.pipeline.convert（Options の ai_mode="manual"）を呼び、
  XML の xref（段落ごとの種類・rid・文字・位置）、plan.decisions、レポートの 4 章、AI 依頼文、不変性・最終・DTD・J-STAGE の
  チェック、XML に入らなかった画像、report.actions の key を取る。貼り戻しの期待（paste）があれば、記録の文面から link_note の
  text と occurrence を読み取り、回答の JSON を作って ai_response で変換し直す。
- 結果は out/<label>/<ID>.json と out/<label>/summary.json に残し、XML などの大きな出力は消す（--keep で残す）。
- --ref を付けると、out/<ref>/ の結果と比べる期待（same_ref）と、どのケースにも足す「xref を外した body・back の XML と
  XML の文字が相手と同じ」（リンクの違いが xref の有無だけに現れること）を確かめる。--ref がなければ、それらは N/A。
- 判定: OK / FAIL / UNSURE（記録の文面から text と occurrence を読み取れないなど、道具の側で決めかねたもの）/ N/A。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path("/home/user/jstgxmlcng_JASME")
META = REPO / "examples" / "meta_example.toml"
LINKCATS = {"note", "figure", "table", "xref"}
NAME_LINE = re.compile(r"^- \[([A-Za-z0-9_-]+)\] 姓と名の区切りがない氏名: 「(.*)」\s*$")


# ============================================================================= 子のプロセス（指定した src で動く）
def local(tag):
    return tag.split("}")[-1] if isinstance(tag, str) else ""


def text(el):
    return "".join(el.itertext())


def para_facts(root):
    """body・back の <p>（入れ子でないもの）ごとに: 文字、xref の (種類, rid, 文字, 位置)、囲み（boxed-text）の中か。"""
    from lxml import etree
    out = []
    for p in root.iter("p"):
        if any(local(a.tag) == "p" for a in p.iterancestors()):
            continue
        acc, refs = [], []
        for ev, el in etree.iterwalk(p, events=("start", "end")):
            if ev == "start":
                if el is not p and local(el.tag) == "xref":
                    refs.append({"type": el.get("ref-type"), "rid": el.get("rid"), "text": text(el),
                                 "offset": len("".join(acc))})
                acc.append(el.text or "")
            else:
                if el is not p:
                    acc.append(el.tail or "")
        anc = [local(a.tag) for a in p.iterancestors()]
        out.append({"text": "".join(acc), "xrefs": refs, "boxed": "boxed-text" in anc,
                    "where": "/".join(reversed(anc[:4]))})
    return out


def stripped(root):
    """xref を外した（中の文字は残す）body と back の XML。"""
    import copy

    from lxml import etree
    r = copy.deepcopy(root)
    etree.strip_tags(r, "xref")
    return "".join(etree.tostring(r.find(x), encoding="unicode") for x in ("body", "back") if r.find(x) is not None)


def run_once(docx, work, response=None):
    from jasme_jats import report as rp
    from jasme_jats.config import ArticleMeta, JournalConfig
    from jasme_jats.pipeline import Options, convert
    from lxml import etree
    journal = JournalConfig.load()
    meta = ArticleMeta.load(META)
    opts = Options(out_dir=work, ai_mode="manual", convert_metafiles=False, ai_response=response)
    res = convert(docx, meta, journal, opts)
    root = etree.fromstring(res.xml_path.read_bytes())
    f = {}
    f["paras"] = para_facts(root)
    f["stripped"] = stripped(root)
    f["xml_text"] = text(root)
    f["plan_paras"] = [[src, p.plain()] for src, p in res.plan.paras.items()]
    f["decisions"] = [{"did": d.did, "category": d.category, "src": d.src, "message": d.message, "applied": d.applied,
                       "location": d.location} for d in res.plan.decisions]
    f["fidelity_ok"] = bool(res.fidelity.ok)
    f["final_ok"] = bool(res.fidelity.final_ok)
    f["dtd_valid"] = bool(res.dtd_valid)
    f["dtd_errors"] = [str(x) for x in res.dtd_errors][:5]
    f["jstage_issues"] = [str(x) for x in res.jstage_issues]
    f["lost_images"] = [str(x) for x in res.lost_images]
    f["warnings"] = [str(w) for w in res.warnings]
    try:
        f["actions"] = sorted({a.key for a in rp.actions(res)})
    except Exception as e:      # noqa: BLE001
        f["actions"] = [f"(actions を取れない: {e})"]
    f["report"] = res.report_path.read_text(encoding="utf-8") if res.report_path else ""
    f["prompt"] = res.prompt_path.read_text(encoding="utf-8") if res.prompt_path and Path(res.prompt_path).exists() else ""
    f["ai_report"] = (res.ai_report_path.read_text(encoding="utf-8")
                      if res.ai_report_path and Path(res.ai_report_path).exists() else "")
    return f


def parse_record(msg):
    """記録の文面から link_note の text と occurrence を読み取る（読めなければ None）。"""
    t = re.search(r"text[\"'」:：=\s]*[「\"']?([^\s「」\"',，、]+)", msg) or re.search(r"「(\s*[0-9０-９]+\s*)」", msg) \
        or re.search(r"「([^「」]+)」", msg)
    o = (re.search(r"occurrence[\"'」:：=\s]*(\d+)", msg) or re.search(r"(\d+)\s*(?:回目|番目|つ目|個目)", msg)
         or re.search(r"第\s*(\d+)", msg))
    if not t or not o:
        return None
    return t.group(1), int(o.group(1))


def inner(args):
    case = json.loads(Path(args.case_json).read_text(encoding="utf-8"))
    work = Path(args.work)
    facts = {"id": case["id"]}
    try:
        facts.update(run_once(Path(case["docx"]), work / "main"))
    except Exception:
        import traceback
        facts["error"] = traceback.format_exc()[-3000:]
    # 貼り戻し
    pastes = []
    if "error" not in facts:
        srcs = {plain: src for src, plain in facts["plan_paras"]}
        for p in case["paras"]:
            for c in p["checks"]:
                if c["check"] != "paste":
                    continue
                src = srcs.get(p["plain"])
                recs = [d for d in facts["decisions"] if d["src"] == src and d["category"] in LINKCATS]
                item = {"key": p["key"], "src": src, "records": [d["message"] for d in recs]}
                parsed = [parse_record(d["message"]) for d in recs]
                parsed = [x for x in parsed if x]
                item["parsed"] = parsed
                if src and parsed:
                    ops = [{"op": "link_note", "src": src, "text": t, "occurrence": o, "target": c["target"], "role": "",
                            "image": "", "mathml": "", "surname": "", "given": "", "reason": "記録の貼り戻しの試験",
                            "confidence": "高"} for t, o in parsed]
                    rj = work / f"resp_{p['key']}.json"
                    rj.write_text(json.dumps({"placements": [], "operations": ops, "notes": ""}, ensure_ascii=False),
                                  encoding="utf-8")
                    try:
                        g = run_once(Path(case["docx"]), work / f"paste_{p['key']}", response=rj.read_text(encoding="utf-8"))
                        item["paras"] = [x for x in g["paras"] if x["text"] == p["plain"]]
                        item["ai_report_lines"] = [ln for ln in g["ai_report"].splitlines() if "link_note" in ln][:6]
                        item["stripped_same"] = g["stripped"] == facts["stripped"]
                    except Exception:
                        import traceback
                        item["error"] = traceback.format_exc()[-1500:]
                pastes.append(item)
    facts["pastes"] = pastes
    Path(args.facts).write_text(json.dumps(facts, ensure_ascii=False, indent=1), encoding="utf-8")


# ============================================================================= 期待との比べ方
def chapter(report, n):
    out, cur = [], None
    for ln in report.splitlines():
        m = re.match(r"^## (\d+)\.", ln)
        if m:
            cur = int(m.group(1))
        elif cur == n:
            out.append(ln)
    return out


def rid_list(ps, types):
    return [x["rid"] for x in ps["xrefs"] if x["type"] in types]


def evaluate(case, f, ref, control):
    out = []                                # (段落, 期待の名前, 判定, 理由)
    if "error" in f:
        return [("-", "convert", "FAIL", "変換が止まった: " + f["error"][-400:])]
    srcs = {}
    for src, plain in f["plan_paras"]:
        srcs.setdefault(plain, src)
    ch4 = chapter(f["report"], 4)
    prompt_lines = f["prompt"].splitlines()
    for p in case["paras"]:
        hits = [x for x in f["paras"] if x["text"] == p["plain"]]
        rhits = [x for x in ref["paras"] if x["text"] == p["plain"]] if ref else None
        src = srcs.get(p["plain"])
        for c in p["checks"]:
            k, name = c["check"], f"{p['key']}:{c['check']}"
            if not hits and k not in ("dec", "paste"):
                out.append((p["key"], name, "FAIL", f"XML に段落「{p['plain'][:20]}」がない（または文字が違う）"))
                continue
            ps = hits[0] if hits else None
            if k == "xref":
                got = rid_list(ps, c["types"])
                if c["level"] == "exact":
                    ok = got == c["rids"]
                    out.append((p["key"], name, "OK" if ok else "FAIL", f"{c['types']} の rid: {got}（期待 {c['rids']}）"
                                + (f"。xref: {[(x['text'], x['rid']) for x in ps['xrefs'] if x['type'] in c['types']]}" if not ok else "")))
                else:
                    ok = got in c["alts"]
                    out.append((p["key"], name, "OK" if ok else "FAIL", f"{c['types']} の rid: {got}（許す {c['alts']}）"))
            elif k == "offsets":
                got = [x["offset"] for x in ps["xrefs"] if x["type"] in c["types"]]
                ok = got == c["offsets"]
                out.append((p["key"], name, "OK" if ok else "FAIL",
                            f"位置: {got}（期待 {c['offsets']}）" + ("" if ok else f" xref: {[(x['text'], x['offset']) for x in ps['xrefs']]}")))
            elif k == "boxed":
                out.append((p["key"], name, "OK" if ps["boxed"] else "FAIL", f"置き場所: {ps['where']}"))
            elif k == "same_ref":
                if ref is None:
                    out.append((p["key"], name, "N/A", "--ref がない"))
                    continue
                if not rhits:
                    out.append((p["key"], name, "FAIL", "比べる相手に段落がない"))
                    continue
                a = [(x["type"], x["rid"], x["text"], x["offset"]) for x in ps["xrefs"] if x["type"] in c["types"]]
                b = [(x["type"], x["rid"], x["text"], x["offset"]) for x in rhits[0]["xrefs"] if x["type"] in c["types"]]
                out.append((p["key"], name, "OK" if a == b else "FAIL", f"今 {a} / 相手 {b}"))
            elif k == "dec":
                recs = [d for d in f["decisions"] if d["src"] == src and d["category"] in LINKCATS] if src else []
                n = len(recs)
                if c["level"] == "either":
                    st, why = "OK", f"記録 {n} 件（件数は問わない）"
                else:
                    lo, hi = c.get("min"), c.get("max")
                    ok = (lo is None or n >= lo) and (hi is None or n <= hi)
                    st, why = ("OK" if ok else "FAIL"), f"記録 {n} 件（期待 {lo if lo is not None else 0}〜{hi if hi is not None else '∞'}）"
                if src is None:
                    st, why = "FAIL", "plan に段落がない"
                if recs:
                    why += "。" + " / ".join(f"[{d['category']}] {d['message'][:70]}" for d in recs[:3])
                    # 記録はレポートの 4 章と AI 依頼文にも出る（D の方針）
                    miss4 = [d for d in recs if not any(d["message"][:25] in ln for ln in ch4)]
                    missp = [d for d in recs if not any(f"[{src}]" in ln and d["message"][:25] in ln for ln in prompt_lines)]
                    if miss4 or missp:
                        st = "FAIL" if st == "OK" else st
                        why += f"。4 章にない {len(miss4)} 件・AI 依頼文にない {len(missp)} 件"
                out.append((p["key"], name, st, why))
            elif k == "paste":
                item = next((x for x in f.get("pastes", []) if x["key"] == p["key"]), None)
                if item is None or not item.get("records"):
                    out.append((p["key"], name, "FAIL", "記録がないので貼り戻せない"))
                elif not item.get("parsed"):
                    out.append((p["key"], name, "UNSURE", f"記録の文面から text と occurrence を読み取れない: {item['records'][0][:90]}"))
                elif "error" in item:
                    out.append((p["key"], name, "FAIL", "貼り戻しの変換が止まった: " + item["error"][-200:]))
                else:
                    want = p["offsets"][c["seg"]]
                    gp = item.get("paras") or []
                    got = [(x["rid"], x["offset"]) for x in (gp[0]["xrefs"] if gp else []) if x["type"] == "fn"]
                    ok = (c["target"], want) in got
                    exp = (c.get("text"), c.get("occurrence"))
                    match = any(tuple(x) == exp for x in item["parsed"])
                    out.append((p["key"], name, "OK" if ok else ("FAIL" if match else "UNSURE"),
                                f"期待の text・occurrence {exp}（{'読み取りと一致' if match else '読み取りと違う'}）。"
                                f"空白: {'なし' if not any(re.search(r'\\s', str(x[0])) for x in item['parsed']) else 'あり'}。"
                                f"読み取り {item['parsed']} → 注の xref {got}（期待 {(c['target'], want)} を含む）。"
                                f"AI 反映: {item.get('ai_report_lines', [])[:2]}"))
    # ---- ケース全体
    for c in case["case_checks"]:
        k = c["check"]
        lines = [m.groups() for m in (NAME_LINE.match(ln) for ln in prompt_lines) if m]
        if k == "prompt_name":
            got = any(nm == c["name"] for _, nm in lines)
            if c["level"] == "exact":
                ok = got == c["present"]
            else:
                ok = got in c["alts"]
            out.append(("-", f"prompt_name:{c['name']}", "OK" if ok else "FAIL",
                        f"依頼文の行 {'あり' if got else 'なし'}（{'期待 ' + ('あり' if c.get('present') else 'なし') if c['level'] == 'exact' else 'どちらでもよい'}）。行: {lines}"))
        elif k == "prompt_name_count":
            out.append(("-", "prompt_name_count", "OK" if len(lines) == c["n"] else "FAIL", f"{len(lines)} 行（期待 {c['n']}）: {lines}"))
        elif k == "report_name":
            hit = [ln for ln in f["report"].splitlines() if c["name"] in ln and "区切り" in ln]
            out.append(("-", f"report_name:{c['name']}", "OK" if hit else "FAIL", hit[0][:110] if hit else "レポートに記録がない"))
    # ---- どのケースにも
    inv = [("fidelity", f["fidelity_ok"]), ("final", f["final_ok"]), ("dtd", f["dtd_valid"]),
           ("jstage", f["jstage_issues"] == []), ("lost_images", f["lost_images"] == [])]
    for nm, ok in inv:
        out.append(("-", f"inv:{nm}", "OK" if ok else "FAIL",
                    "" if ok else str({"dtd": f["dtd_errors"], "jstage": f["jstage_issues"], "lost_images": f["lost_images"]}.get(nm, ""))[:200]))
    if control is not None and case["id"] != "C00":
        ok = f["actions"] == control["actions"]
        out.append(("-", "actions", "OK" if ok else "FAIL", f"{f['actions']}（対照 C00: {control['actions']}）"))
    if ref is None:
        out.append(("-", "ref:xref以外同じ", "N/A", "--ref がない"))
    else:
        ok1 = f["stripped"] == ref["stripped"]
        ok2 = f["xml_text"] == ref["xml_text"]
        out.append(("-", "ref:xref以外同じ", "OK" if ok1 and ok2 else "FAIL",
                    f"xref を外した body・back {'同じ' if ok1 else '違う'}、XML の文字 {'同じ' if ok2 else '違う'}"))
    for item in f.get("pastes", []):
        if "stripped_same" in item:
            out.append(("-", f"paste:{item['key']}:xref以外同じ", "OK" if item["stripped_same"] else "FAIL",
                        "貼り戻しの前後で xref を外した body・back が同じ" if item["stripped_same"] else "貼り戻しで xref 以外も変わった"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src")
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--label", default="run")
    ap.add_argument("--ref")
    ap.add_argument("--only")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--inner", action="store_true")
    ap.add_argument("--case-json")
    ap.add_argument("--work")
    ap.add_argument("--facts")
    args = ap.parse_args()
    if args.inner:
        return inner(args)
    cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    if any(not Path(c["docx"]).exists() for c in cases):       # docx は消してあることがある（gen_h.py で作り直す）
        subprocess.run([sys.executable, str(HERE / "gen_h.py")], check=True, cwd=str(HERE),
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    if args.only:
        want = set(args.only.split(","))
        cases = [c for c in cases if c["id"] in want]
    outdir = HERE / "out" / args.label
    outdir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONPATH=str(Path(args.src).resolve()), PYTHONDONTWRITEBYTECODE="1")
    facts = {}
    for c in cases:
        cj = outdir / f"{c['id']}.case.json"
        cj.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
        work = outdir / f"work_{c['id']}"
        shutil.rmtree(work, ignore_errors=True)
        fj = outdir / f"{c['id']}.json"
        cp = subprocess.run([args.python, str(Path(__file__).resolve()), "--inner", "--case-json", str(cj),
                             "--work", str(work), "--facts", str(fj)], env=env, cwd="/tmp", capture_output=True, text=True)
        if cp.returncode != 0 or not fj.exists():
            facts[c["id"]] = {"error": cp.stderr[-2000:]}
        else:
            facts[c["id"]] = json.loads(fj.read_text(encoding="utf-8"))
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)
        cj.unlink()
    control = facts.get("C00")
    if control is None and (outdir / "C00.json").exists():
        control = json.loads((outdir / "C00.json").read_text(encoding="utf-8"))
    summary, nfail = [], 0
    for c in cases:
        ref = None
        if args.ref:
            rp = HERE / "out" / args.ref / f"{c['id']}.json"
            ref = json.loads(rp.read_text(encoding="utf-8")) if rp.exists() else None
            if ref is not None and "error" in ref:
                ref = None
        res = evaluate(c, facts[c["id"]], ref, control if control and "error" not in control else None)
        bad = [r for r in res if r[2] == "FAIL"]
        uns = [r for r in res if r[2] == "UNSURE"]
        nfail += bool(bad)
        st = "FAIL" if bad else ("UNSURE" if uns else "OK")
        print(f"[{st}] {c['id']}: {c['desc']}")
        for r in res:
            if r[2] in ("FAIL", "UNSURE") or os.environ.get("RUN_H_VERBOSE"):
                print(f"    {r[2]:6} {r[1]}: {r[3][:300]}")
        summary.append({"id": c["id"], "status": st, "desc": c["desc"], "results": res})
    (outdir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"--- {len(cases)} 件中 FAIL {nfail} 件（{args.label}）")


if __name__ == "__main__":
    sys.exit(main())
