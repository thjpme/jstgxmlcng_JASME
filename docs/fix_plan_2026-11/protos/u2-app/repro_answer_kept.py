"""u2-app: 「変換する」で論文B に切り替えても、回答の欄（views にない）は論文A の回答のまま。押すと論文B の段落に当たる。
split_labels の基準値も測る。"""
import json, shutil, sys
from pathlib import Path
REPO = Path("/home/user/jstgxmlcng_JASME")
sys.path.insert(0, str(REPO / "tests"))
import make_fixtures as mf
from conftest import FULL
from lxml import etree
from jasme_jats import app
from jasme_jats.app import AppState, type_choices
HERE = Path(__file__).resolve().parent
W = HERE / "w_kept"; shutil.rmtree(W, ignore_errors=True); W.mkdir()
S = mf.S
def parts(word):
    return lambda b: [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], f"{word}の本文。試験（2024）を引く。"),
                      mf.para(S["body"], f"{word}の二つ目の段落。")]
A, B = W / "A.docx", W / "B.docx"
mf.make_article(A, "論文Aの題目", parts("論文A")); mf.make_article(B, "論文Bの題目", parts("論文B"))
st = AppState(W / "work")
st.set_inputs(route="docx", docx=str(A), volume="31", issue="1", fpage="1", lpage="12", peer_review="査読あり",
              manuscript_type=type_choices()[0], ai_mode="manual")
demo = app.build_app(st, app.IO())
fns = {f.fn.__name__: f.fn for f in demo.fns.values()}
deps = {f.fn.__name__: f for f in demo.fns.values()}
print("on_convert の出力の数:", len(deps["on_convert"].outputs), "| answer の欄を含むか:",
      any(getattr(o, "label", "") == app.ANSWER_LABEL for o in deps["on_convert"].outputs))
fns["on_convert"](*[st.inputs[n] for n in app.INPUT_NAMES])
src = [pid for pid, p in st.res.plan.paras.items() if "二つ目" in str(p)][0]
ans_A = json.dumps({"operations": [{"op": "set_role", "src": src, "text": "", "occurrence": 1, "target": "", "role": "exclude",
                                    "image": "", "confidence": "高", "reason": "試験"}], "placements": [], "notes": []})
st.set_inputs(docx=str(B), fpage="77", lpage="88")
fns["on_convert"](*[st.inputs[n] for n in app.INPUT_NAMES])      # 論文B を変換（回答の欄は論文A の回答のまま）
out = fns["on_apply"](ans_A)
root = etree.fromstring(st.res.xml_path.read_bytes().split(b"\n", 2)[2])
print("xml:", st.res.xml_path.name, "| fpage:", next(root.iter("fpage")).text, "| accepted:", [(o["op"], o["src"]) for o, _ in st.res.ai.accepted],
      "| B の二つ目の段落が XML にある:", "論文Bの二つ目の段落。" in etree.tostring(root, encoding="unicode"),
      "| needs_action:", st.res.needs_action, "| ok:", st.res.fidelity.ok and st.res.fidelity.final_ok)

# split_labels の基準
for flag in (False, True):
    s2 = AppState(W / f"work_sl{flag}")
    s2.set_inputs(route="docx", docx=str(FULL), volume="31", issue="1", fpage="1", lpage="12", peer_review="査読あり",
                  manuscript_type=type_choices()[0], ai_mode="none", split_labels=flag)
    r = s2.convert()
    root = etree.fromstring(r.xml_path.read_bytes().split(b"\n", 2)[2])
    print("split_labels", flag, "→ fig/table-wrap の label:", sum(1 for e in root.iter("label") if e.getparent().tag in ("fig", "table-wrap")))
