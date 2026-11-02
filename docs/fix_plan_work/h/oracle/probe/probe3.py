import sys, json
sys.path.insert(0, "/tmp/claude-0/-home-user-jstgxmlcng-JASME/d6c16a4c-c8c0-592a-be84-ec12faff29b8/scratchpad/h/oracle")
import run_h
from pathlib import Path
docx = Path("/tmp/claude-0/-home-user-jstgxmlcng-JASME/d6c16a4c-c8c0-592a-be84-ec12faff29b8/scratchpad/h/oracle/cases/S08.docx")
f = run_h.run_once(docx, Path("p3a"))
src = [s for s, t in f["plan_paras"] if t == "架空の補足がある5)。"][0]
ops = [{"op": "link_note", "src": src, "text": "5)", "occurrence": 1, "target": "fn3", "role": "", "image": "", "mathml": "", "surname": "", "given": "", "reason": "x", "confidence": "高"}]
Path("r.json").write_text(json.dumps({"placements": [], "operations": ops, "notes": ""}))
g = run_h.run_once(docx, Path("p3b"), response=Path("r.json").read_text())
print([x for x in g["paras"] if x["text"].startswith("架空の補足")])
print([l for l in g["ai_report"].splitlines() if "link_note" in l][:3])
print(g["stripped"] == f["stripped"])
