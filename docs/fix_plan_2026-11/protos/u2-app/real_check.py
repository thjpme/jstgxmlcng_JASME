"""u2-app: 実際の原稿（tests/private のテストデータ）2 件で、1 画面版の入力の混ざり方を数える。本文の文字は出さない。"""
import dataclasses, json, shutil, sys
from pathlib import Path
REPO = Path("/home/user/jstgxmlcng_JASME")
from lxml import etree
from jasme_jats import app
from jasme_jats.app import AppState, type_choices
real = app.convert
app.convert = lambda d, m, j, o: real(d, m, j, dataclasses.replace(o, convert_metafiles=False))
HERE = Path(__file__).resolve().parent
W = HERE / "w_real"; shutil.rmtree(W, ignore_errors=True); W.mkdir()
docs = sorted(p for d in sorted((REPO / "tests/private").glob("テストデータ*")) for p in d.glob("*.docx"))
print("docx:", len(docs), [p.parent.name for p in docs])
def body_ids(res):
    return [pid for pid, r in res.plan.region.items() if r == "body"] if hasattr(res.plan, "region") else []
pairs = [(docs[0], docs[2]), (docs[2], docs[0])] if len(docs) > 2 else []
for a, b in pairs:
    st = AppState(W / f"work_{a.parent.name}_{b.parent.name}")
    st.set_inputs(route="docx", docx=str(a), volume="31", issue="1", fpage="1", lpage="12", peer_review="査読あり",
                  manuscript_type=type_choices()[0], ai_mode="manual")
    ra = st.convert()
    ids_a = body_ids(ra)
    ops = [{"op": "set_role", "src": pid, "text": "", "occurrence": 1, "target": "", "role": "exclude", "image": "",
            "confidence": "高", "reason": "試験"} for pid in ids_a[5:8]]
    st.set_inputs(docx=str(b), fpage="77", lpage="90")
    rb = st.apply_answer(json.dumps({"operations": ops, "placements": [], "notes": []}))
    root = etree.fromstring(rb.xml_path.read_bytes().split(b"\n", 2)[2])
    ids_b = set(body_ids(rb))
    print(f"{a.parent.name} → {b.parent.name}: xml={rb.xml_path.name} fpage={next(root.iter('fpage')).text} "
          f"本文の段落 ID の重なり={len(set(ids_a) & ids_b)}/{len(ids_a)} 採用={len(rb.ai.accepted)} 不採用={len(rb.ai.rejected)} "
          f"検証={rb.fidelity.ok and rb.fidelity.final_ok} DTD={rb.dtd_valid} 要対応={rb.needs_action} "
          f"AI の除外={sum(1 for e in rb.plan.exclusions if 'AI' in str(getattr(e, 'reason', '')))}")
