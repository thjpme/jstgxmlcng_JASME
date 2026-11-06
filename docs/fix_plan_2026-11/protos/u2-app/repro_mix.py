"""u2-app: 1 画面版で、変換の後に docx・ページを変えて「反映」を押すと、前回の meta と今の docx が混ざる。"""
import json, sys, shutil
from pathlib import Path
REPO = Path("/home/user/jstgxmlcng_JASME")
sys.path.insert(0, str(REPO / "tests"))
import make_fixtures as mf
from lxml import etree
from jasme_jats.app import AppState, type_choices
from jasme_jats.report import actions

HERE = Path(__file__).resolve().parent
W = HERE / "w_mix"
shutil.rmtree(W, ignore_errors=True); W.mkdir()
S = mf.S

def parts(b, word):
    return [mf.para(S["sec1"], "１．はじめに"),
            mf.para(S["body"], f"{word}の本文。試験（2024）を引く。"),
            mf.para(S["body"], f"{word}の二つ目の段落。")]

A = W / "ronbun_A.docx"; B = W / "ronbun_B.docx"
mf.make_article(A, "論文Aの題目", lambda b: parts(b, "論文A"))
mf.make_article(B, "論文Bの題目", lambda b: parts(b, "論文B"))

st = AppState(W / "work")
st.set_inputs(route="docx", docx=str(A), volume="31", issue="1", fpage="1", lpage="12", peer_review="査読あり",
              manuscript_type=type_choices()[0], ai_mode="manual")
res = st.convert()
print("1st:", res.xml_path.name, "waiting:", st.waiting_for_answer)
req = st.prompt_text()
# 論文A の段落一覧から、本文の 2 段落目の ID を探す
plan_ids = [(p_id, p) for p_id, p in res.plan.paras.items()]
srcA = [pid for pid, p in plan_ids if "二つ目" in "".join(getattr(p, "text", "") or "")] if plan_ids else []
print("srcA candidates:", srcA[:3])

def text_of(p):
    for name in ("text", "plain"):
        v = getattr(p, name, None)
        if isinstance(v, str):
            return v
    return str(p)

# 回答: 論文A の「二つ目の段落」を除外にする（AI に set_role exclude を出させた想定）
cand = [pid for pid, p in res.plan.paras.items() if "二つ目" in text_of(p)]
print("cand:", cand)
ans = json.dumps({"operations": [{"op": "set_role", "src": cand[0], "text": "", "occurrence": 1, "target": "",
                                  "role": "exclude", "image": "", "confidence": "高", "reason": "試験"}],
                  "placements": [], "notes": []}, ensure_ascii=False)

# 入力を変える: docx を B に、最初のページを 77 に
st.set_inputs(docx=str(B), fpage="77", lpage="88")
res2 = st.apply_answer(ans)
root = etree.fromstring(res2.xml_path.read_bytes().split(b"\n", 2)[2])
def first(tag):
    el = next(root.iter(tag), None)
    return None if el is None else "".join(el.itertext())
print("2nd xml:", res2.xml_path.name)
print("fpage:", first("fpage"), "lpage:", first("lpage"))
print("title:", first("article-title"))
print("doi:", [x.text for x in root.iter("article-id")])
print("fidelity ok:", res2.fidelity.ok, res2.fidelity.final_ok, "dtd:", res2.dtd_valid)
print("ai accepted:", [(op["op"], op["src"], op["role"]) for op, d in res2.ai.accepted])
print("ai rejected:", [(op["op"], op["src"], why) for op, why in res2.ai.rejected])
ex = [(e.src if hasattr(e, "src") else e) for e in getattr(res2.plan, "exclusions", [])]
print("exclusions:", [(getattr(e, 'src', None), getattr(e, 'reason', None)) for e in res2.plan.exclusions][:5])
print("B の『二つ目の段落』は XML にあるか:", "論文Bの二つ目の段落。" in etree.tostring(root, encoding="unicode"))
print("needs_action:", res2.needs_action, [a.key for a in actions(res2)])
