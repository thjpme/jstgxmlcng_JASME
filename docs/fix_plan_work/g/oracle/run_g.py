"""単位 G の反例（gen_g.py の cases.json）を、指定した src で変換し、期待と比べる。

  python run_g.py --src <src> [--python <python>] [--label <名前>] [--only ID,...] [--keep]

- ケースごとに、子のプロセス（PYTHONPATH=<src>）で jasme_jats.pipeline.convert を呼び（公開 API の convert・Options と、
  結果の Result の欄だけを使う）、さらに python -m jasme_jats（同じ docx・同じ指定）を実行して、標準エラー（要対応・要確認の
  知らせ）と終了コードを取る。ルート2 のケース（route=pdf）は tests/fixtures/sample_pdfcheck.pdf を使う。
- 結果は out/<label>/<ID>.json（facts）と out/<label>/summary.json に残し、XML などの大きな出力は消す（--keep で残す）。
- 期待の level: exact は FIX_PLAN の G から一つに決まるもの（違えば FAIL）。either は決めかねるもの（許される結果を alts に
  列挙し、外れたら FAIL。alts が [True, False] のものは記録だけ）。
- どのケースにも、不変性チェック・最終出力の再チェック・DTD 検証・J-STAGE のチェック・XML に入らなかった画像なし、を足す。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path("/home/user/jstgxmlcng_JASME")
META = REPO / "examples" / "meta_example.toml"
PDF = REPO / "tests" / "fixtures" / "sample_pdfcheck.pdf"
WNS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
TAGS = ("p", "title", "article-title", "mixed-citation", "td", "th", "label", "uri", "ext-link", "caption")


# ============================================================================= 子のプロセス（指定した src で動く）
def text(el):
    return "".join(el.itertext())


def local(tag):
    return tag.split("}")[-1] if isinstance(tag, str) else ""


def tokens_of(root):
    """body・back の要素を文書の順に並べる: (種類, 文字)。fig・table-wrap は中身を 1 つにまとめる。"""
    out = []

    def walk(el):
        for ch in el:
            t = local(ch.tag)
            if t in ("fig", "table-wrap"):
                out.append((t, text(ch)))
            elif t in ("p", "title"):
                if any(local(x.tag) in ("fig", "table-wrap", "list") for x in ch):
                    walk(ch)
                else:
                    out.append((t, text(ch)))
            else:
                walk(ch)
    for part in ("body", "back"):
        el = root.find(part)
        if el is not None:
            walk(el)
    return out


def docx_paragraphs(path):
    """docx の本文の w:p ごとに、(変更を承諾した文字, 段落記号が削除か)。この道具だけの簡単な読み方（隠し文字は見ない）。"""
    from lxml import etree
    root = etree.fromstring(zipfile.ZipFile(path).read("word/document.xml"))
    out = []
    for p in root.iter(f"{{{WNS}}}p"):
        s = []
        for t in p.iter(f"{{{WNS}}}t"):
            if any(local(a.tag) in ("del", "moveFrom") for a in t.iterancestors()):
                continue
            # 入れ子の段落（テキストボックス）の文字は数えない
            if next(t.iterancestors(f"{{{WNS}}}p")) is not p:
                continue
            s.append(t.text or "")
        ppr = p.find(f"{{{WNS}}}pPr/{{{WNS}}}rPr")
        marked = ppr is not None and (ppr.find(f"{{{WNS}}}del") is not None or ppr.find(f"{{{WNS}}}moveFrom") is not None)
        out.append(["".join(s), marked])
    return out


def inner(args):
    from lxml import etree
    from jasme_jats.config import ArticleMeta, JournalConfig
    from jasme_jats.pipeline import Options, convert
    case = json.loads(Path(args.case_json).read_text(encoding="utf-8"))
    docx = Path(args.docx)
    work = Path(args.work)
    journal = JournalConfig.load()
    meta = ArticleMeta.load(META)
    facts = {"id": case["id"]}
    route = case.get("route", "docx")
    try:
        opts = Options(out_dir=work / "main", ai_mode="none", convert_metafiles=False)
        if route == "pdf":
            opts = Options(out_dir=work / "main", ai_mode="none", convert_metafiles=False, route="pdf", pdf_path=PDF)
        res = convert(docx, meta, journal, opts)
    except Exception:
        import traceback
        facts["error"] = traceback.format_exc()[-3000:]
        res = None
    if res is not None:
        raw = res.xml_path.read_bytes()
        root = etree.fromstring(raw)
        facts["tokens"] = tokens_of(root)
        facts["xml_text"] = text(root)
        els = []
        for el in root.iter():
            t = local(el.tag)
            if t in TAGS:
                d = {"tag": t, "text": text(el), "anc": [local(a.tag) for a in el.iterancestors()][::-1],
                     "breaks": len([x for x in el.iter() if local(x.tag) == "break"])}
                if t in ("td", "th"):
                    d["xml"] = etree.tostring(el, encoding="unicode")
                els.append(d)
        facts["elements"] = els
        facts["tables"] = []
        for tw in root.iter("table-wrap"):
            cap = tw.find("caption")
            facts["tables"].append({"caption": text(cap) if cap is not None else "",
                                    "rows": [[text(c) for c in tr if local(c.tag) in ("td", "th")] for tr in tw.iter("tr")]})
        facts["figs"] = [text(f.find("caption")) if f.find("caption") is not None else "" for f in root.iter("fig")]
        facts["fns"] = [[text(p) for p in fn.iter("p")] for fn in root.iter("fn")]
        facts["list_items"] = [{"label": text(li.find("label")) if li.find("label") is not None else None,
                                "text": " ".join(text(p) for p in li.iter("p"))} for li in root.iter("list-item")]
        facts["fidelity_ok"] = bool(res.fidelity.ok)
        facts["final_ok"] = bool(res.fidelity.final_ok)
        facts["dtd_valid"] = bool(res.dtd_valid)
        facts["dtd_errors"] = [str(x) for x in res.dtd_errors][:5]
        facts["jstage_issues"] = [str(x) for x in res.jstage_issues]
        facts["lost_images"] = [str(x) for x in res.lost_images]
        facts["needs_action"] = bool(res.needs_action)
        facts["warnings"] = [str(w) for w in res.warnings]
        facts["hidden_text"] = [str(h) for h in res.hidden_text]
        facts["excluded"] = [[str(x) for x in e] for e in res.fidelity.excluded]
        facts["plan_paras"] = [[src, p.plain()] for src, p in res.plan.paras.items()]
        facts["report"] = res.report_path.read_text(encoding="utf-8") if res.report_path else ""
        if route == "pdf":
            fx = res.docx_fix
            facts["docx_fix"] = None
            if fx is not None and fx.path and Path(fx.path).exists():
                facts["docx_fix"] = {"fixed": docx_paragraphs(fx.path), "orig": docx_paragraphs(docx),
                                     "applied": len(fx.applied), "skipped": len(fx.skipped)}
    cmd = [sys.executable, "-m", "jasme_jats", str(docx), "--meta", str(META), "--ai", "none",
           "--out", str(work / "cli"), "--no-metafile-conversion"]
    cmd += ["--route", "pdf", "--pdf", str(PDF)] if route == "pdf" else ["--route", "docx"]
    cp = subprocess.run(cmd, capture_output=True, text=True, cwd="/tmp", env=os.environ.copy())
    facts["cli_rc"] = cp.returncode
    facts["cli_stderr"] = cp.stderr[-8000:]
    Path(args.facts).write_text(json.dumps(facts, ensure_ascii=False, indent=1), encoding="utf-8")


# ============================================================================= 期待との比べ方
def chapters(report):
    out, cur = {}, None
    for ln in report.splitlines():
        m = re.match(r"^## (\d+)\.", ln)
        if m:
            cur = int(m.group(1))
            out[cur] = []
        elif cur is not None:
            out[cur].append(ln)
    return out


def src_of(f, t):
    hits = [s for s, plain in f.get("plan_paras", []) if plain == t]
    return hits[0] if hits else None


def mentions(lines, f, t, keys):
    """keys のどれかと、段落（文字の先頭 8 字か段落の ID）を含む行。"""
    sid = src_of(f, t)
    if sid is None:
        cands = [s for s, plain in f.get("plan_paras", []) if plain.startswith(t[:8])]
        sid = cands[0] if cands else None
    head = t[:8]
    out = []
    for ln in lines:
        if not any(k in ln for k in keys):
            continue
        if head in ln or (sid and re.search(rf"(?<![A-Za-z0-9]){re.escape(sid)}(?![0-9])", ln)):
            out.append(ln)
    return out


def els(f, tags=None, pred=None):
    return [e for e in f.get("elements", []) if (tags is None or e["tag"] in tags) and (pred is None or pred(e))]


def evaluate(case, f, twin):
    out = []
    rep = chapters(f.get("report", ""))
    stderr_lines = [ln for ln in f.get("cli_stderr", "").splitlines() if ln.strip()]
    for c in case["checks"]:
        k = c["check"]
        ok, why = None, ""
        if "error" in f:
            out.append((c, False, "変換が止まった: " + f["error"][-300:]))
            continue
        t = c.get("text")
        if k == "p_exact":
            hit = els(f, ("p",), lambda e: e["text"] == t and "caption" not in e["anc"])
            ok = len(hit) == 1
            why = f"{len(hit)} 個" + ("" if ok else _fate(f, t))
        elif k == "p_exact_in":
            hit = els(f, ("p",), lambda e: t in e["text"])
            ok = bool(hit) and any(e["text"].endswith(t) for e in hit)
            why = f"{[e['text'][:40] for e in hit][:2]}" if hit else "ない" + _fate(f, t)
        elif k == "p_absent":
            hit = els(f, ("p", "td", "th", "title"), lambda e: e["text"] == t)
            ok, why = not hit, (f"ある: {[e['tag'] for e in hit]}" if hit else "")
        elif k == "p_one_of":
            hit = els(f, ("p",), lambda e: e["text"] in c["texts"])
            ok, why = len(hit) == 1, (f"{[e['text'] for e in hit]}" if hit else "ない" + _fate(f, c["texts"][0][:8]))
        elif k == "title_exact":
            hit = els(f, ("title",), lambda e: e["text"] == t)
            ok, why = len(hit) == 1, (f"{[e['anc'][-2:] for e in hit]}" if hit else "title にない" + _fate(f, t))
        elif k in ("not_title", "no_title"):
            hit = els(f, ("title",), lambda e: e["text"] == t)
            ok, why = not hit, ("title にある" if hit else "")
        elif k == "id_gap":
            a, b = src_of(f, t), src_of(f, c["next"])
            if a is None or b is None:
                ok, why = False, f"段落が見つからない（{t[:10]}: {a}, {c['next'][:10]}: {b}）"
            else:
                na, nb = int(re.sub(r"\D", "", a)), int(re.sub(r"\D", "", b))
                ok, why = nb - na == c["gap"], f"{a} → {b}"
        elif k == "decision":
            hit = mentions(rep.get(4, []), f, t, c["keys"])
            got = bool(hit)
            ok = (got in c["alts"]) if c["level"] == "either" else got
            why = f"4 章 {'あり' if got else 'なし'}" + (f": {hit[0][:100]}" if hit else "")
        elif k == "label":
            li = [x for x in f.get("list_items", []) if t in x["text"]]
            if li:
                ok, why = (li[0]["label"] or "").strip() == c["label"], f"label={li[0]['label']!r}"
            else:
                hit = els(f, ("p",), lambda e: t in e["text"])
                ok = bool(hit) and hit[0]["text"].startswith(c["label"])
                why = f"list-item なし。p={[e['text'][:20] for e in hit][:1]}"
        elif k == "no_ch10":
            hit = [ln for ln in rep.get(10, []) if any(x in ln for x in c["keys"])]
            ok, why = not hit, (hit[0][:100] if hit else "")
        elif k == "ch10":
            hit = mentions(rep.get(10, []), f, t, c["keys"])
            got = bool(hit)
            ok = (got in c["alts"]) if c["level"] == "either" else got
            why = f"10 章 {'あり' if got else 'なし'}" + (f": {hit[0][:120]}" if hit else "")
        elif k == "table_caption":
            hit = [x for x in f.get("tables", []) if x["caption"] == c["caption"]]
            ok, why = len(hit) == 1, f"表題: {[x['caption'] for x in f.get('tables', [])]}"
        elif k == "cell_exact":
            hit = els(f, ("td", "th"), lambda e: e["text"] == t)
            ok = len(hit) == 1 and hit[0]["breaks"] == c["breaks"]
            why = (f"break {hit[0]['breaks']} 個" if hit else "セルがない" + _cells(f, t))
        elif k == "fig_caption":
            ok, why = c["caption"] in f.get("figs", []), f"図: {f.get('figs')}"
        elif k == "fn_paras":
            fn = [x for x in f.get("fns", []) if any(t in p for p in x)]
            ok = len(fn) == 1 and len(fn[0]) == c["n"]
            why = f"{fn[0] if fn else '注がない'}" + ("" if fn else _fate(f, t))
        elif k == "text_absent":
            ok, why = t not in f.get("xml_text", ""), ("XML にある" + _where(f, t) if t in f.get("xml_text", "") else "")
        elif k == "hidden_listed":
            hit = [h for h in f.get("hidden_text", []) if t in h]
            ok, why = bool(hit), (hit[0][:80] if hit else f"hidden_text: {[h[:40] for h in f.get('hidden_text', [])]}")
        elif k == "hidden_has_br":
            hit = [h for h in f.get("hidden_text", []) if t in h]
            got = bool(hit) and any(x in hit[0] for x in ("\\n", "\n", "改行", "↵", "β", "‑"))
            ok = got in c["alts"]
            why = f"6 章の隠し文字: {hit[0][:80] if hit else 'なし'}"
        elif k == "same_as_twin":
            if twin is None or "tokens" not in twin:
                ok, why = None, "比べる相手がない"
            else:
                def strip(ts):
                    return [x for x in ts if not any(i in x[1] for i in c["ignore"])]
                a, b = strip(twin["tokens"]), strip(f["tokens"])
                ok = a == b
                why = "" if ok else _diff(a, b)
        elif k in ("cell_break", "cell_break_prefix"):
            if k == "cell_break":
                hit = els(f, ("td", "th"), lambda e: t in e["text"])
            else:
                hit = els(f, ("td", "th"), lambda e: e["text"].startswith(t))
            if not hit:
                ok, why = False, "セルがない" + _cells(f, t[:4])
            else:
                x = hit[0]["xml"]
                n = len(re.findall(r"<break/>(?:<[^/!>][^>]*>)*\n", x))
                ok = n >= t.count("\n")
                why = f"{hit[0]['tag']}: {re.sub(r' xmlns(:[a-z]+)?=\"[^\"]*\"', '', x)[:160]!r}"
        elif k == "link_no_break":
            hit = els(f, ("uri", "ext-link"), lambda e: e["text"] == t)
            ok = bool(hit) and all(e["breaks"] == 0 for e in hit)
            why = f"{[(e['tag'], e['breaks']) for e in hit]}" if hit else "リンクがない" + _cells(f, t[:4])
        elif k == "no_break_in":
            hit = els(f, (c["tag"],), lambda e: (t in e["text"]) if c.get("contains") else e["text"] == t)
            ok = len(hit) >= 1 and all(e["breaks"] == 0 for e in hit)
            why = f"{[(e['tag'], e['breaks']) for e in hit]}" if hit else f"{c['tag']} にない" + _fate(f, t[:5])
        elif k in ("action", "no_action"):
            hit = [ln for ln in stderr_lines if any(x in ln for x in c["keys"])]
            ok = bool(hit) if k == "action" else not hit
            why = f"終了コード {f.get('cli_rc')}" + (f"、標準エラー: {hit[0][:120]}" if hit else "、標準エラーに知らせなし")
        elif k == "table_rows":
            hit = [x for x in f.get("tables", []) if x["caption"] == c["caption"]]
            ok = bool(hit) and hit[0]["rows"] == c["rows"]
            why = f"{hit[0]['rows'] if hit else '表がない'}"
        elif k == "table_has":
            hit = [x for x in f.get("tables", []) if x["caption"] == c["caption"]]
            cells = [y for r in hit[0]["rows"] for y in r] if hit else []
            miss = [x for x in c["texts"] if x not in cells]
            ok, why = bool(hit) and not miss, (f"ない: {miss}" if miss else "")
        elif k == "celldel":
            hit = [x for x in f.get("tables", []) if x["caption"] == c["caption"]]
            row = next((r for r in hit[0]["rows"] if "残るセル" in r), None) if hit else None
            got = "removed" if row == ["残るセル"] else ("empty" if row == ["残るセル", ""] else f"other:{row}")
            ok, why = got in c["alts"], f"行: {row}（{got}）"
        elif k == "report_line":
            lines = f.get("report", "").splitlines()
            hit = [ln for ln in lines if any(all(x in ln for x in alt) for alt in c["any_of"])]
            ok, why = bool(hit), (hit[0][:120] if hit else "レポートに記録がない")
        elif k == "fixed_docx":
            fx = f.get("docx_fix")
            if not fx:
                ok, why = False, "直した docx がない"
            else:
                fixed, orig = fx["fixed"], fx["orig"]
                i = next((j for j, (s, m) in enumerate(fixed) if s.startswith(c["first_head"])), None)
                if i is None or i + 1 >= len(fixed):
                    ok, why = False, "段落がない"
                else:
                    joined = fixed[i][0] + fixed[i + 1][0]
                    ok = fixed[i][1] and len(fixed) == len(orig) and joined in c["joined"]
                    why = (f"w:p {len(orig)}→{len(fixed)}、段落記号の削除 {'あり' if fixed[i][1] else 'なし'}、"
                           f"つないだ文字 {joined!r}、直した {fx['applied']}・直さなかった {fx['skipped']}")
        else:
            ok, why = None, f"未知の check {k}"
        out.append((c, ok, why))
    if "tokens" in f:
        for key in ("fidelity_ok", "final_ok", "dtd_valid"):
            out.append(({"check": key, "level": "exact"}, f[key], "" if f[key] else str(f.get("dtd_errors", ""))))
        out.append(({"check": "jstage_ok", "level": "exact"}, not f["jstage_issues"], str(f["jstage_issues"][:2])))
        out.append(({"check": "lost_none", "level": "exact"}, not f["lost_images"], str(f["lost_images"][:2])))
    return out


def _fate(f, needle):
    s = ""
    hit = [e for e in f.get("elements", []) if needle in e["text"] and e["tag"] in ("p", "title", "td", "th")]
    if hit:
        s += f"（XML: {[(e['tag'], e['text'][:30]) for e in hit][:3]}）"
    ex = [e for e in f.get("excluded", []) if needle in e[-1]]
    if ex:
        s += f"（除外: {[e[:2] for e in ex][:2]}）"
    return s


def _where(f, needle):
    hit = [e for e in f.get("elements", []) if needle in e["text"] and e["tag"] in ("p", "title", "td", "th")]
    return f"（{[(e['tag'], e['text'][:30]) for e in hit][:2]}）"


def _cells(f, needle):
    hit = [e for e in f.get("elements", []) if needle in e["text"] and e["tag"] in ("td", "th", "uri", "ext-link", "p")]
    return f"（{[(e['tag'], e['text'][:30]) for e in hit][:3]}）"


def _diff(a, b):
    import difflib
    sm = difflib.SequenceMatcher(a=[tuple(x) for x in a], b=[tuple(x) for x in b])
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op != "equal":
            return f"{op}: 相手 {[x[1][:20] for x in a[i1:i2]][:2]} → {[x[1][:20] for x in b[j1:j2]][:2]}"
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path)
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--label", default="run")
    ap.add_argument("--only", default="")
    ap.add_argument("--keep", action="store_true", help="XML などの出力を残す")
    ap.add_argument("--inner", action="store_true")
    ap.add_argument("--case-json")
    ap.add_argument("--docx")
    ap.add_argument("--work")
    ap.add_argument("--facts")
    a = ap.parse_args()
    if a.inner:
        return inner(a)
    cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    only = set(filter(None, a.only.split(",")))
    outdir = HERE / "out" / a.label
    outdir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONPATH=str(a.src.resolve()), PYTHONDONTWRITEBYTECODE="1")
    summary, n_ok, n_fail = [], 0, 0
    for case in cases:
        if only and case["id"] not in only and case["id"] != next((c["twin"] for c in cases if c["id"] in only and c.get("twin")), None):
            continue
        work = outdir / f"{case['id']}_work"
        if work.exists():
            shutil.rmtree(work)
        work.mkdir()
        cj = work / "case.json"
        cj.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
        facts_path = outdir / f"{case['id']}.json"
        cp = subprocess.run([a.python, str(Path(__file__).resolve()), "--inner", "--case-json", str(cj),
                             "--docx", case["docx"], "--work", str(work), "--facts", str(facts_path)],
                            capture_output=True, text=True, cwd="/tmp", env=env)
        if cp.returncode != 0 or not facts_path.exists():
            print(f"[ERROR] {case['id']}: 子のプロセスが失敗\n{cp.stderr[-2000:]}")
            summary.append({"id": case["id"], "status": "ERROR", "error": cp.stderr[-2000:]})
            n_fail += 1
            continue
        if not a.keep:
            shutil.rmtree(work, ignore_errors=True)
        f = json.loads(facts_path.read_text(encoding="utf-8"))
        twin = None
        if case.get("twin"):
            tp = outdir / f"{case['twin']}.json"
            twin = json.loads(tp.read_text(encoding="utf-8")) if tp.exists() else None
        res = evaluate(case, f, twin)
        bad = [(c, why) for c, ok, why in res if ok is False]
        status = "OK" if not bad else "FAIL"
        n_ok += status == "OK"
        n_fail += status == "FAIL"
        print(f"[{status}] {case['id']}  {case['title']}  (終了コード {f.get('cli_rc')})")
        for c, ok, why in res:
            m = {True: "ok ", False: "NG ", None: "-- "}[ok]
            if ok is not True or c["check"] not in ("fidelity_ok", "final_ok", "dtd_valid", "jstage_ok", "lost_none"):
                print(f"    {m}{c['level']:6} {c['check']}{('(' + c['text'][:14] + ')') if c.get('text') else ''}: {why}")
        summary.append({"id": case["id"], "status": status, "cli_rc": f.get("cli_rc"),
                        "results": [{"check": c["check"], "level": c["level"], "text": c.get("text"), "ok": ok, "why": why}
                                    for c, ok, why in res]})
    (outdir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n合計: OK {n_ok} / FAIL {n_fail}（{outdir / 'summary.json'}）")


if __name__ == "__main__":
    sys.exit(main())
