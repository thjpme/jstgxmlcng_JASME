"""u2-app: 従来のノートブック。手順 5 まで済ませた後に手順 2・3 が途中で止まると、DONE が戻らず、手順 6 が混ざった入力で動く。"""
import json, sys, types
from pathlib import Path
REPO = Path("/home/user/jstgxmlcng_JASME")
sys.path.insert(0, str(REPO / "tools"))
import make_notebook as mk
HERE = Path(__file__).resolve().parent
W = HERE / "w_nb"; W.mkdir(exist_ok=True)

def cell(prefix):
    c = next(c for c in json.loads(mk.render())["cells"] if "".join(c["source"]).startswith(prefix))
    return "".join(c["source"])

uploads = []
files = types.SimpleNamespace(upload=lambda: uploads.pop(0), download=lambda p: None)
colab = types.ModuleType("google.colab"); colab.files = files
google = types.ModuleType("google"); google.colab = colab
sys.modules["google"] = google; sys.modules["google.colab"] = colab

# 手順 2: 作り方は「PDF で補う」。論文B の docx は選んだが、PDF を選び損ねた（キャンセル）
src2 = cell("#@title 2.").replace('Path("/content/jasme_work")', repr(str(W)) and f'Path({str(W)!r})')
ns = {"DONE": {1, 2, 3, 4, 5}, "docx_path": Path("A.docx"), "meta_input": {"fpage": "1"}, "USER_IMAGES": {"31_1_01.png": ("a.png", b"")}}
uploads[:] = [{"B.docx": b"PK"}, {}]
try:
    exec(src2, ns)
except SystemExit as e:
    print("step2 stopped:", str(e)[:30], "…")
print("DONE after failed step 2:", ns["DONE"], "| docx_path:", ns["docx_path"].name, "| pdf_path:", ns["pdf_path"],
      "| USER_IMAGES:", ns["USER_IMAGES"])
g6 = mk.guard(1, 2, 3, 4, 5)
try:
    exec(g6, dict(ns)); print("step 6 guard: passes (論文B の docx・論文A の meta で convert が走る)")
except SystemExit as e:
    print("step 6 guard refuses:", e)

# 手順 3: 最初のページを 77 にしたが、受付日の書き方が誤り
src3 = cell("#@title 3.").replace('peer_review = "（選んでください）"  #@param', 'peer_review = "査読あり"  #@param')
src3 = src3.replace('first_page = ""  #@param', 'first_page = "77"  #@param', 1).replace('received = ""  #@param', 'received = "あした"  #@param', 1)
ns3 = {"DONE": {1, 2, 3, 4, 5}, "docx_path": Path("A.docx"), "meta_input": {"fpage": "1"}}
try:
    exec(src3, ns3)
except SystemExit as e:
    print("step3 stopped:", str(e)[:20], "…")
print("DONE after failed step 3:", ns3["DONE"], "| meta_input.fpage:", ns3["meta_input"]["fpage"])
