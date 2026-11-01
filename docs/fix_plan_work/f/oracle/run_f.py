"""単位 F の反例（gen_f.py の cases.json）を、指定した src で変換し、期待と比べる。

  python run_f.py --src <src> [--python <python>] [--label <名前>] [--base <基準の label>] [--only ID,...]
                  [--box-form items|items_body|top]

- ケースごとに、子のプロセス（PYTHONPATH=<src>）で jasme_jats.pipeline.convert を呼び（公開 API の convert・Options と、
  結果の Result の欄だけを使う）、さらに python -m jasme_jats（同じ docx・同じ指定）を実行して、標準エラー（要対応・要確認の
  知らせ）と終了コードを取る。結果は out/<label>/<ID>.json（facts）に残し、XML などの大きな出力は消す。
- 手動モードで回答を使うケース（resp あり）は、まず回答なしで変換して段落の ID（Result.plan.paras）と図形の ID
  （段落の textbox_id、なければ float_id）を調べ、回答の JSON を組み立ててから、回答つきで変換し直す。
- placements の kind box・label の書き方は FIX_PLAN に書かれていないので仮に決めた（--box-form。既定 items:
  {"float": 図形, "after": 段落, "items": [{"kind": "box"|"label", "caption": [], "body": []}]}。items_body は body に
  図形の中の段落の ID をすべて入れる。top は placement の最上位に "kind" を置き items を空にする）。
- same_as_base は --base の label の facts と、XML の並び（tokens）を比べる。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path("/home/user/jstgxmlcng_JASME")
META = REPO / "examples" / "meta_example.toml"
NOTICE_WORDS = ["テキストボックス", "囲み", "注記"]


# ============================================================================= 子のプロセス（指定した src で動く）
def text(el):
    return "".join(el.itertext())


def local(tag):
    return tag.split("}")[-1] if isinstance(tag, str) else ""


def tokens_of(root):
    """body・back の要素を文書の順に並べる: (種類, 文字, 場所)。boxed-text・fig・table-wrap は中身を 1 つにまとめる。"""
    out = []

    def walk(el, where):
        for ch in el:
            t = local(ch.tag)
            if t == "boxed-text":
                out.append(("box", text(ch), where))
            elif t == "fig":
                cap = ch.find("caption")
                out.append(("fig", text(cap) if cap is not None else "", where))
            elif t == "table-wrap":
                out.append(("table", text(ch), where))
            elif t == "p":
                if any(local(x.tag) in ("boxed-text", "fig", "table-wrap") for x in ch):
                    walk(ch, where)
                else:
                    out.append(("p", text(ch), where))
            elif t == "title":
                out.append(("title", text(ch), where))
            elif t in ("app", "fn-group", "ref-list", "ack", "notes"):
                walk(ch, t if where == "back" else where)
            else:
                walk(ch, where)
    for part, where in (("body", "body"), ("back", "back")):
        el = root.find(part)
        if el is not None:
            walk(el, where)
    return out


def ancestors_with(root, needle):
    """needle を含む最も内側の要素ごとに、祖先の要素名の一覧。"""
    res = []
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        own = (el.text or "")
        if needle in own or any(needle in (c.tail or "") for c in el):
            res.append([local(a.tag) for a in el.iterancestors()][::-1] + [local(el.tag)])
    if not res:     # 要素をまたいで書かれた文字（xref の中など）
        cands = [el for el in root.iter() if isinstance(el.tag, str) and needle in text(el)]
        inner = [el for el in cands if not any(needle in text(c) for c in el if isinstance(c.tag, str))]
        res = [[local(a.tag) for a in el.iterancestors()][::-1] + [local(el.tag)] for el in inner]
    return res


def inner(args):
    from lxml import etree
    from jasme_jats.config import ArticleMeta, JournalConfig
    from jasme_jats.pipeline import Options, convert
    try:
        from jasme_jats.pipeline import AIRequiredError
    except ImportError:          # 念のため
        AIRequiredError = Exception
    case = json.loads(Path(args.case_json).read_text(encoding="utf-8"))
    docx = Path(args.docx)
    work = Path(args.work)
    journal = JournalConfig.load()
    meta = ArticleMeta.load(META)
    facts = {"id": case["id"]}

    def one(out_dir, mode, response=None):
        return convert(docx, meta, journal, Options(out_dir=out_dir, ai_mode=mode, ai_response=response,
                                                    convert_metafiles=False))
    mode = case["mode"]
    response_text = None
    try:
        if case.get("resp"):
            pre = one(work / "pre", "manual")
            plan = pre.plan
            response = build_response(case["resp"], plan, args.box_form)
            facts["response"] = response
            response_text = json.dumps(response, ensure_ascii=False)
            res = one(work / "main", "manual", response_text)
        else:
            res = one(work / "main", mode)
    except AIRequiredError as e:
        facts["raised"] = f"{type(e).__name__}: {e}"
        res = None
    except Exception as e:       # 変換の失敗も記録する
        import traceback
        facts["error"] = traceback.format_exc()[-3000:]
        res = None
    if res is not None:
        raw = res.xml_path.read_bytes()
        root = etree.fromstring(raw.split(b"\n", 2)[2]) if raw.startswith(b"<?xml") else etree.fromstring(raw)
        facts["tokens"] = tokens_of(root)
        facts["xml_text"] = text(root)
        facts["excluded"] = [[s, r, t] for s, r, t in res.fidelity.excluded]
        facts["fidelity_ok"] = bool(res.fidelity.ok)
        facts["final_ok"] = bool(res.fidelity.final_ok)
        facts["dtd_valid"] = bool(res.dtd_valid)
        facts["dtd_errors"] = [str(x) for x in res.dtd_errors][:5]
        facts["jstage_issues"] = [list(map(str, x)) if isinstance(x, (list, tuple)) else str(x) for x in res.jstage_issues]
        facts["lost_images"] = [str(x) for x in res.lost_images]
        facts["needs_action"] = bool(res.needs_action)
        facts["warnings"] = [str(w) for w in res.warnings]
        facts["ai_accepted"] = [[op.get("op") if isinstance(op, dict) else str(op),
                                 op.get("src") if isinstance(op, dict) else "", getattr(d, "message", str(d))]
                                for op, d in res.ai.accepted]
        facts["ai_rejected"] = [[op.get("op") if isinstance(op, dict) else str(op),
                                 op.get("src") if isinstance(op, dict) else "", str(w)] for op, w in res.ai.rejected]
        facts["ai_error"] = res.ai.error
        # 図形・段落の ID（回答の組み立てと、拒否の照合のため）
        facts["para_ids"] = {}
        for src, p in res.plan.paras.items():
            facts["para_ids"][src] = {"text": p.plain()[:40], "textbox_id": getattr(p, "textbox_id", None),
                                      "float_id": getattr(p, "float_id", None)}
        facts["formulas"] = [{"id": f.get("id"), "label": f.find("label") is not None and bool(text(f.find("label"))),
                              "anc": [local(a.tag) for a in f.iterancestors()]} for f in root.iter("disp-formula")]
        facts["xrefs"] = [[text(x), x.get("rid"), x.get("ref-type")] for x in root.iter("xref")]
        facts["figs"] = [{"id": f.get("id"), "caption": text(f.find("caption")) if f.find("caption") is not None else "",
                          "graphic": f.find(".//graphic") is not None,
                          "anc": [local(a.tag) for a in f.iterancestors()]} for f in root.iter("fig")]
        facts["counts"] = {"sec": len(root.findall("body/sec")),
                           "trans_abstract_p": len(root.findall(".//trans-abstract//p")),
                           "fn_group": root.find(".//fn-group") is not None}
        facts["prompt"] = res.prompt_path.read_text(encoding="utf-8") if getattr(res, "prompt_path", None) else ""
        needles = {c.get("text") for c in case["checks"] if c.get("text")}
        facts["where"] = {n: ancestors_with(root, n) for n in needles}
    # コマンドライン（知らせと終了コード）
    cmd = [sys.executable, "-m", "jasme_jats", str(docx), "--meta", str(META), "--route", "docx",
           "--ai", "manual" if mode == "manual" else "none", "--out", str(work / "cli"), "--no-metafile-conversion"]
    if response_text is not None:
        rp = work / "response.json"
        rp.write_text(response_text, encoding="utf-8")
        cmd += ["--ai-response", str(rp)]
    cp = subprocess.run(cmd, capture_output=True, text=True, cwd="/tmp", env=os.environ.copy())
    facts["cli_rc"] = cp.returncode
    facts["cli_stderr"] = cp.stderr[-6000:]
    Path(args.facts).write_text(json.dumps(facts, ensure_ascii=False, indent=1), encoding="utf-8")


def find_src(plan, head):
    for src, p in plan.paras.items():
        if p.plain().startswith(head):
            return src, p
    for src, p in plan.paras.items():
        if head in p.plain():
            return src, p
    raise KeyError(f"段落が見つからない: {head}")


def shape_id(p):
    return getattr(p, "textbox_id", None) or getattr(p, "float_id", None)


def build_response(spec, plan, box_form):
    resp = {"placements": [], "operations": [], "notes": []}
    for pl in spec.get("placements", []):
        try:
            src, p = find_src(plan, pl["float_of"])
            after, _ = find_src(plan, pl["after_of"])
        except KeyError as e:        # 回答前の組み立てに段落がない（F の前の版の本文の外の図形など）
            resp["notes"].append(f"組み立てられなかった指定: {e}")
            continue
        fid = shape_id(p)
        kind = pl["kind"]
        if kind in ("box", "label"):
            members = [s for s, q in plan.paras.items() if shape_id(q) == fid]
            if box_form == "top":
                item = None
                one = {"float": fid, "after": after, "kind": kind, "items": []}
            else:
                item = {"kind": kind, "caption": [], "body": members if box_form == "items_body" else []}
                one = {"float": fid, "after": after, "items": [item]}
        else:
            cap, _ = find_src(plan, pl["caption_of"])
            body = [s for s, q in plan.paras.items()
                    if shape_id(q) == fid and any(getattr(a, "kind", "") == "image" for a in q.atoms)]
            one = {"float": fid, "after": after, "items": [{"kind": kind, "caption": [cap], "body": body}]}
        one.update(reason="試験の指定", confidence="中")
        resp["placements"].append(one)
    for sr in spec.get("set_role", []):
        src, _ = find_src(plan, sr["src_of"])
        resp["operations"].append({"op": "set_role", "src": src, "text": "", "occurrence": 1, "target": "",
                                   "role": sr["role"], "image": "", "mathml": "", "surname": "", "given": "",
                                   "reason": "試験の指定", "confidence": "高"})
    return resp


# ============================================================================= 親のプロセス（期待と比べる）
def box_tokens(f, needle):
    return [k for k, t in enumerate(f.get("tokens", [])) if t[0] == "box" and needle in t[1]]


def neighbor(f, k, step):
    toks = f["tokens"]
    j = k + step
    while 0 <= j < len(toks):
        if toks[j][1].strip():
            return toks[j]
        j += step
    return None


def excluded_with(f, needle):
    return [e for e in f.get("excluded", []) if needle in e[2]]


def notice_lines(f, keys):
    lines = [ln for ln in f.get("cli_stderr", "").splitlines() if ln.strip()]
    return [ln for ln in lines if any(k in ln for k in keys) or any(w in ln for w in NOTICE_WORDS)]


def in_body_p(f, needle, exact_text=False):
    return [t for t in f.get("tokens", []) if t[0] == "p" and (t[1].strip() == needle if exact_text else needle in t[1])]


def evaluate(case, f, base):
    """各 check を (OK/FAIL/NA, 説明) にする。"""
    out = []
    for c in case["checks"]:
        kind = c["check"]
        ok, why = None, ""
        raised = "raised" in f or "error" in f
        if kind == "raises_ai_required":
            ok = "raised" in f and "AIRequired" in f["raised"]
            why = f.get("raised", "") or f.get("error", "")[-300:] or f"止まらなかった（終了コード {f.get('cli_rc')}）"
        elif raised:
            ok, why = False, f"変換が止まった: {(f.get('raised') or f.get('error', ''))[-300:]}"
        elif kind == "no_raise":
            ok, why = True, ""
        elif kind == "box":
            ks = box_tokens(f, c["text"])
            if not ks:
                ok, why = False, "boxed-text がない" + _fate(f, c["text"])
            else:
                k = ks[0]
                if c["where"] == "before":
                    nb = neighbor(f, k, +1)
                    ok = nb is not None and nb[0] == "p" and c["ref"] in nb[1]
                    why = f"直後の要素: {nb[:2] if nb else None}"
                elif c["where"] == "after":
                    nb = neighbor(f, k, -1)
                    ok = nb is not None and nb[0] == "p" and c["ref"] in nb[1]
                    why = f"直前の要素: {nb[:2] if nb else None}"
                else:
                    ok = True
                if ok and len(ks) > 1:
                    ok, why = False, f"boxed-text が {len(ks)} 個"
        elif kind == "box_contains_all":
            ks = box_tokens(f, c["text"])
            ok = bool(ks) and all(any(part in f["tokens"][k][1] for k in ks) for part in c["parts"])
            why = "" if ok else "囲みの段落が揃っていない" + _fate(f, c["text"])
        elif kind == "same_box":
            ks = box_tokens(f, c["text"])
            ok = bool(ks) and any(c["other"] in f["tokens"][k][1] for k in ks)
            why = "" if ok else "内側の文字が同じ boxed-text にない" + _fate(f, c["other"])
        elif kind == "no_box":
            ks = box_tokens(f, c["text"])
            ok, why = not ks, (f"boxed-text がある: {f['tokens'][ks[0]][1][:30]}" if ks else "")
        elif kind == "no_box_any":
            ks = [t for t in f["tokens"] if t[0] == "box"]
            ok, why = not ks, (f"boxed-text がある: {ks[0][1][:30]}" if ks else "")
        elif kind == "excluded":
            ex = excluded_with(f, c["text"])
            ok = bool(ex) and (not c.get("reason_has") or any(c["reason_has"] in e[1] for e in ex))
            why = f"除外: {[e[1] for e in ex]}" if ex else "除外に記録がない" + _fate(f, c["text"])
        elif kind == "excluded_reason_not":
            ex = excluded_with(f, c["text"])
            ok = not any(c["reason_not"] in e[1] for e in ex)
            why = f"除外の理由: {[e[1] for e in ex]}"
        elif kind == "box_or_excluded":
            has_box = bool(box_tokens(f, c["text"]))
            ex = excluded_with(f, c["text"])
            got = "box" if has_box else ("excluded" if ex else "other")
            ok = got in c["alts"]
            why = f"結果: {got}" + (f"（理由 {[e[1] for e in ex]}）" if ex else "") + ("" if ok else _fate(f, c["text"]))
        elif kind == "not_in_body_p":
            hit = in_body_p(f, c["text"], c.get("exact_text"))
            ok, why = not hit, (f"本文の p にある: {hit[0][:2]}" if hit else "")
        elif kind == "notice":
            hit = notice_lines(f, c["keys"])
            got = bool(hit)
            if c["level"] == "either":
                ok = got in c["alts"]
            else:
                ok = got == c["present"]
            why = f"知らせ {'あり' if got else 'なし'}" + (f": {hit[0][:120]}" if hit else "")
        elif kind == "fig":
            figs = [g for g in f["figs"] if c["caption"] in g["caption"]]
            if not figs:
                ok, why = False, "図がない" + _fate(f, c["caption"])
            else:
                g = figs[0]
                ok, why = True, f"図 {g['id']} 祖先 {'/'.join(g['anc'][-3:])}"
                if c.get("graphic") and not g["graphic"]:
                    ok, why = False, why + "、graphic がない"
                wh = c.get("where")
                if wh == "body" and ("body" not in g["anc"]):
                    ok = False
                if wh == "app" and "app" not in g["anc"]:
                    ok = False
                if c.get("fid") and g["id"] != c["fid"]:
                    ok, why = False, why + f"、ID が {g['id']}"
                k = next((i for i, t in enumerate(f["tokens"]) if t[0] == "fig" and c["caption"] in t[1]), None)
                if c.get("before") and k is not None:
                    nb = neighbor(f, k, +1)
                    if not (nb and nb[0] == "p" and c["before"] in nb[1]):
                        ok, why = False, why + f"、直後 {nb[:2] if nb else None}"
                if c.get("after") and k is not None:
                    nb = neighbor(f, k, -1)
                    if not (nb and nb[0] == "p" and c["after"] in nb[1]):
                        ok, why = False, why + f"、直前 {nb[:2] if nb else None}"
                if c.get("body_end") and k is not None:
                    rest = [t for t in f["tokens"][k + 1:] if t[2] == "body" and t[1].strip()]
                    if rest:
                        ok, why = False, why + f"、後ろに本文の要素 {rest[0][:2]}"
        elif kind == "not_in_tags":
            places = f["where"].get(c["text"], [])
            bad = [pl for pl in places if any(t in pl for t in c["tags"])]
            ok = not bad
            why = f"場所: {['/'.join(p[-4:]) for p in places][:3]}" if places else "XML にない" + _fate(f, c["text"])
        elif kind == "lost_none":
            ok, why = not f["lost_images"], f"lost_images: {f['lost_images'][:2]}"
        elif kind == "lost_has":
            ok, why = bool(f["lost_images"]), f"lost_images: {f['lost_images'][:2]}"
        elif kind == "needs_action":
            ok, why = f["needs_action"] == c["value"], f"needs_action={f['needs_action']} 終了コード {f.get('cli_rc')}"
        elif kind == "ai_accepted":
            ids = _ids_for(f, c["src_of"])
            hit = [a for a in f["ai_accepted"] if a[0] == c["op"] and (a[1] in ids)]
            ok = bool(hit)
            why = f"採用: {[a[:2] for a in f['ai_accepted']]} 不採用: {[(r[1], r[2][:80]) for r in f['ai_rejected']]}"
        elif kind == "ai_rejected":
            ids = _ids_for(f, c["src_of"])
            hit = [r for r in f["ai_rejected"] if r[1] in ids]
            ok = bool(hit) and (not c.get("reason_has") or any(c["reason_has"] in r[2] for r in hit))
            why = f"不採用: {[(r[1], r[2][:100]) for r in f['ai_rejected']]} 採用: {[a[:2] for a in f['ai_accepted']]}"
        elif kind == "formula_in_box":
            fs = [x for x in f["formulas"] if x["id"] == c["fid"]]
            ok = bool(fs) and "boxed-text" in fs[0]["anc"] and (fs[0]["label"] or not c.get("label"))
            why = f"数式: {f['formulas']}"
        elif kind == "xref":
            ok = any(x[0] == c["text"] and x[1] == c["rid"] for x in f["xrefs"])
            why = f"リンク: {[x for x in f['xrefs'] if x[2] == 'disp-formula'] or '数式へのリンクなし'}"
        elif kind == "counts":
            got = f["counts"]
            want = {k: c[k] for k in ("sec", "trans_abstract_p", "fn_group")}
            ok, why = got == want, f"{got}"
        elif kind == "blank_excluded_only":
            bad = [e for e in f["excluded"] if not e[2].strip() and "空白" not in e[1]]
            ok = not bad
            why = f"空白なのに理由が空白でない除外: {[(e[0], e[1]) for e in bad][:4]}" if bad else ""
        elif kind == "box_parent":
            places = f["where"].get(c["text"], [])
            par = None
            for pl in places:
                if "boxed-text" in pl:
                    i = pl.index("boxed-text")
                    par = pl[i - 1] if i else None
                    break
            ok = (par in c["alts"]) if c["level"] == "either" else par == c["parent"]
            why = f"boxed-text の親: {par}"
        elif kind == "prompt":
            pr = f.get("prompt", "")
            miss = [m for m in c["must"] if m not in pr]
            ok, why = (bool(pr) and not miss), ("依頼文がない" if not pr else (f"依頼文にない: {miss}" if miss else ""))
        elif kind == "in_body_p":
            hit = in_body_p(f, c["text"])
            ok, why = bool(hit), (f"{hit[0][:2]}" if hit else "本文の p にない" + _fate(f, c["text"]))
        elif kind == "fig_graphic_in":
            figs = [g for g in f["figs"] if c["where"] in g["anc"] and g["graphic"]]
            ok, why = bool(figs), f"図: {[(g['id'], g['anc'][:2]) for g in f['figs']]}"
        elif kind == "in_region":
            places = f["where"].get(c["text"], [])
            ok = bool(places) and all(c["region"] in pl for pl in places)
            why = f"場所: {['/'.join(p[-4:]) for p in places][:3]}"
        elif kind == "same_as_base":
            if base is None:
                ok, why = None, "基準がない"
            elif "tokens" not in base:
                ok, why = None, "基準が止まった"
            else:
                ok = f["tokens"] == base["tokens"]
                why = "" if ok else _diff(base["tokens"], f["tokens"])
        else:
            ok, why = None, f"未知の check {kind}"
        out.append((c, ok, why))
    # どのケースにも: 不変性・最終・DTD・J-STAGE（止まらないとき）
    if "tokens" in f:
        for key in ("fidelity_ok", "final_ok", "dtd_valid"):
            out.append(({"check": key, "level": "exact"}, f[key], "" if f[key] else str(f.get("dtd_errors", ""))))
        out.append(({"check": "jstage_ok", "level": "exact"}, not f["jstage_issues"], str(f["jstage_issues"][:2])))
        if not any(c["check"] == "lost_has" for c in case["checks"]):
            out.append(({"check": "lost_none(全体)", "level": "exact"}, not f["lost_images"], str(f["lost_images"][:2])))
    return out


def _ids_for(f, head):
    ids = set()
    for src, p in f.get("para_ids", {}).items():
        if p["text"].startswith(head[:40]) or head[:20] in p["text"]:
            ids.add(src)
            for k in ("textbox_id", "float_id"):
                if p.get(k):
                    ids.add(p[k])
    return ids


def _fate(f, needle):
    ex = excluded_with(f, needle)
    places = f.get("where", {}).get(needle)
    s = ""
    if ex:
        s += f"（除外: {[e[1] for e in ex]}）"
    if places:
        s += f"（XML の場所: {['/'.join(p[-4:]) for p in places][:2]}）"
    if not ex and not places:
        s += "（XML にも除外にもない）" if needle not in f.get("xml_text", "") else ""
    return s


def _diff(a, b):
    import difflib
    sm = difflib.SequenceMatcher(a=[tuple(x) for x in a], b=[tuple(x) for x in b])
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op != "equal":
            return f"{op}: base {[x[:2] for x in a[i1:i2]][:2]} → {[x[:2] for x in b[j1:j2]][:2]}"
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path)
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--label", default="run")
    ap.add_argument("--base", default=None, help="same_as_base で比べる label")
    ap.add_argument("--only", default="")
    ap.add_argument("--box-form", default="items", choices=["items", "items_body", "top"])
    ap.add_argument("--keep", action="store_true", help="XML などの出力を残す")
    # 子のプロセス
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
    summary = []
    n_ok = n_fail = 0
    for case in cases:
        if only and case["id"] not in only:
            continue
        work = outdir / f"{case['id']}_work"
        if work.exists():
            shutil.rmtree(work)
        work.mkdir()
        cj = work / "case.json"
        cj.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
        facts_path = outdir / f"{case['id']}.json"
        cp = subprocess.run([a.python, str(Path(__file__).resolve()), "--inner", "--case-json", str(cj),
                             "--docx", str(HERE / "cases" / f"{case['id']}.docx"), "--work", str(work),
                             "--facts", str(facts_path), "--box-form", a.box_form],
                            capture_output=True, text=True, cwd="/tmp", env=env)
        if cp.returncode != 0 or not facts_path.exists():
            print(f"[ERROR] {case['id']}: 子のプロセスが失敗\n{cp.stderr[-2000:]}")
            summary.append({"id": case["id"], "error": cp.stderr[-2000:]})
            n_fail += 1
            continue
        if not a.keep:
            shutil.rmtree(work, ignore_errors=True)
        f = json.loads(facts_path.read_text(encoding="utf-8"))
        base = None
        if a.base:
            bp = HERE / "out" / a.base / f"{case['id']}.json"
            base = json.loads(bp.read_text(encoding="utf-8")) if bp.exists() else None
        res = evaluate(case, f, base)
        bad = [(c, why) for c, ok, why in res if ok is False]
        na = [(c, why) for c, ok, why in res if ok is None]
        status = "OK" if not bad else "FAIL"
        n_ok += status == "OK"
        n_fail += status == "FAIL"
        print(f"[{status}] {case['id']}  {case['title']}  (終了コード {f.get('cli_rc')})")
        for c, ok, why in res:
            mark = {True: "ok ", False: "NG ", None: "-- "}[ok]
            if ok is not True or c["check"] not in ("fidelity_ok", "final_ok", "dtd_valid", "jstage_ok", "lost_none(全体)"):
                print(f"    {mark}{c['level']:6} {c['check']}: {why}")
        summary.append({"id": case["id"], "status": status,
                        "fail": [{"check": c["check"], "level": c["level"], "why": why} for c, why in bad],
                        "na": [{"check": c["check"], "why": why} for c, why in na]})
    (outdir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n合計: OK {n_ok} / FAIL {n_fail}（{outdir / 'summary.json'}）")


if __name__ == "__main__":
    sys.exit(main())
