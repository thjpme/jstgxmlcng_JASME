import sys
sys.path.insert(0, "/tmp/claude-0/-home-user-jstgxmlcng-JASME/d6c16a4c-c8c0-592a-be84-ec12faff29b8/scratchpad/h/oracle")
import gen_h as g
from pathlib import Path
from jasme_jats.config import ArticleMeta, JournalConfig
from jasme_jats.pipeline import Options, convert
c = {"id": "x", "kind": "strong", "desc": "", "paras": [g.P("a", ["架空の調査を行った。"])], "case_checks": [],
     "authors_ja": [("架空大学", "架空四郎　"), ("架空大学", "　架空五郎")], "authors_en": [("Shiro KAKU", "F U"), ("Goro KAKU", "F U")]}
g.build(c, Path("p2.docx"))
res = convert(Path("p2.docx"), ArticleMeta.load(Path("/home/user/jstgxmlcng_JASME/examples/meta_example.toml")), JournalConfig.load(), Options(out_dir=Path("o2"), ai_mode="manual", convert_metafiles=False))
print([l for l in res.prompt_path.read_text().splitlines() if "区切り" in l and l.startswith("- [")])
print([l for l in res.report_path.read_text().splitlines() if "区切り" in l][:4])
import re
x = res.xml_path.read_text(); print(re.findall(r"<name[^>]*>.*?</name>", x)[:4])
