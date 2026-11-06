import sys, glob, shutil, subprocess, zipfile
sys.path.insert(0, "/tmp/scratchpad/u1-small")
from pathlib import Path
from sanitize_proto import sanitize
out = Path(__file__).parent / "lo"; out.mkdir(exist_ok=True)
fs = ["/home/user/jstgxmlcng_JASME/tests/fixtures/JASME_template_20261009.docx", "/home/user/jstgxmlcng_JASME/tests/fixtures/sample_full.docx"]
fs += [f for f in sorted(glob.glob("/home/user/jstgxmlcng_JASME/tests/private/**/*.docx", recursive=True)) if "review-repros" not in f][-1:]
for i, f in enumerate(fs):
    d = out / f"s{i}.docx"
    sanitize(f, d)
    r = subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(out), str(d)], capture_output=True, timeout=180)
    print(i, "lo rc", r.returncode, (out / f"s{i}.pdf").exists())
    z = zipfile.ZipFile(d)
    names = set(z.namelist())
    import re
    missing = []
    for n in names:
        if n.endswith(".rels"):
            s = z.read(n).decode()
            base = n.replace("_rels/", "").rsplit("/", 1)[0] if "/" in n.replace("_rels/", "") else ""
    print(i, "parts", len(names))
