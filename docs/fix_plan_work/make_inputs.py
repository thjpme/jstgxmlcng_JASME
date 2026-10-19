"""handoff_pkg: 道具が読む入力の docx のうち、束に入れずに作り直すもの（どれも架空の文字。tests/make_fixtures.py で作る）。

  python -I make_inputs.py [DEST]        # DEST の既定は S。あるファイルは作らない（何度実行してもよい）
- rvB2/docx/win1.docx・num1.docx: rvB2_cases_win1.py・rvB2_cases_num1.py が読む（rvB2_mkdocx.py と同じ作り方: 本文の段落 B1・B2。
  ほかの rvB2/docx の docx は、ケースのファイルを読み込むときに rvB2_mk.build で作られる）。
- rvB_regress_exp_out/<実験名>.docx: rvB_regress_exp.py の EXPS（8 個）。fixB/fixB_all.py の worker が読む。
"""
import importlib.util
import sys
from pathlib import Path

S = Path("/tmp/claude-0/-home-user-jstgxmlcng-JASME/fb4d86bb-6ffb-5369-990a-10fe830c8789/scratchpad")
REPO = Path("/home/user/jstgxmlcng_JASME")
DEST = Path(sys.argv[1]) if len(sys.argv) > 1 else S
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(1, str(REPO / "tests"))
import make_fixtures as mf  # noqa: E402


def consts(path, *names):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return [getattr(m, n) for n in names]


made = []
(DEST / "rvB2" / "docx").mkdir(parents=True, exist_ok=True)
for n in ("win1", "num1"):
    out = DEST / "rvB2" / "docx" / f"{n}.docx"
    if out.exists():
        continue
    b1, b2 = consts(DEST / "rvB2" / f"rvB2_cases_{n}.py", "B1", "B2")
    mf.make_article(out, "照合の窓の検証用文書",
                    lambda b, body=(b1, b2): [mf.para(mf.S["sec1"], "１．はじめに")] + [mf.para(mf.S["body"], t) for t in body])
    made.append(str(out))

sys.path.insert(0, str(DEST))
import rvB_regress_exp as rx  # noqa: E402  HERE = DEST（WORK = DEST/rvB_regress_exp_out）

rx.WORK.mkdir(exist_ok=True)
for name, f in rx.EXPS.items():
    out = rx.WORK / f"{name}.docx"
    if out.exists():
        continue
    body, _ = f()
    rx.exp_docx(name, body)
    made.append(str(out))
print("作った docx:", len(made))
for m in made:
    print("  ", m)
