import glob, os, sys, zipfile, re, shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent)); sys.path.insert(0, "/home/user/jstgxmlcng_JASME/tests")
import sanitize_proto as sp
from jasme_jats.fidelity import source_texts
from jasme_jats.config import ArticleMeta, JournalConfig
from jasme_jats.pipeline import Options, convert
from jasme_jats.docx_reader import read_docx
journal = JournalConfig.load()
meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12", "pub_date": "2026-03-31",
    "received": "2025-06-01", "accepted": "2025-11-20", "peer_review": "あり", "keywords": "proof"})
out = Path(__file__).parent / "san"; shutil.rmtree(out, ignore_errors=True); out.mkdir()
files = sorted(f for f in glob.glob("/home/user/jstgxmlcng_JASME/tests/private/**/*.docx", recursive=True) if "review-repros" not in f)
files += sorted(glob.glob("/home/user/jstgxmlcng_JASME/tests/fixtures/*.docx"))
for k, f in enumerate(files):
    d = out / f"{k}.docx"
    sp.sanitize(f, d)
    z = zipfile.ZipFile(d)
    leftovers = {
        "author": sum(len(re.findall(rb'w:author="(?!\xe4\xbd\x9c\xe6\x88\x90\xe8\x80\x85)', z.read(n))) for n in z.namelist() if n.endswith(".xml")),
        "users_path": sum(z.read(n).count(b"Users") for n in z.namelist() if n.endswith(".rels")),
        "customXml": sum(1 for n in z.namelist() if n.startswith("customXml/")),
        "comments": sum(1 for n in z.namelist() if "comment" in n or "people" in n),
        "commentRef": z.read("word/document.xml").count(b"commentRe"),
    }
    same_text = source_texts(f) == source_texts(d)
    ra, rb = read_docx(f), read_docx(d)
    same_reader = [(p.src, p.plain(), p.autonum) for p in ra.all_paragraphs()] == [(p.src, p.plain(), p.autonum) for p in rb.all_paragraphs()]
    xml_same = None
    if "--convert" in sys.argv:
        try:
            r1 = convert(f, meta, journal, Options(out_dir=out / f"o{k}a", convert_metafiles=False, ai_mode="manual"))
            r2 = convert(d, meta, journal, Options(out_dir=out / f"o{k}b", convert_metafiles=False, ai_mode="manual"))
            xml_same = r1.xml_path.read_bytes() == r2.xml_path.read_bytes()
        except Exception as e:
            xml_same = type(e).__name__
    label = os.path.basename(os.path.dirname(f)) if "private" in f else os.path.basename(f)
    print(label, "size", os.path.getsize(f), "->", os.path.getsize(d), leftovers, "source_texts same", same_text, "reader same", same_reader, "xml same", xml_same)
