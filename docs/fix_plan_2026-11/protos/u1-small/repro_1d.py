import sys, zipfile
from pathlib import Path
sys.path.insert(0, "/home/user/jstgxmlcng_JASME/tests")
import make_fixtures as mf
from jasme_jats.docx_reader import read_docx
from jasme_jats.config import ArticleMeta, JournalConfig
from jasme_jats.pipeline import Options, convert
HERE = Path(__file__).parent
S = mf.S
def parts(b):
    return [mf.para(S["sec1"], "１．はじめに"),
            mf.list_item(S["body"], "一つ目の項目", num_id=92), mf.list_item(S["body"], "二つ目の項目", num_id=92),
            mf.list_item(S["body"], "三つ目の項目", num_id=93), mf.para(S["body"], "最後の文。")]
base = HERE / "lvl_base.docx"
mf.make_article(base, "段の書式の上書きの検証用文書", parts)
dst = HERE / "lvl_override.docx"
NUMS = ('<w:num w:numId="92"><w:abstractNumId w:val="0"/><w:lvlOverride w:ilvl="0">'
        '<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="upperLetter"/><w:lvlText w:val="(%1)"/></w:lvl></w:lvlOverride></w:num>'
        '<w:num w:numId="93"><w:abstractNumId w:val="0"/><w:lvlOverride w:ilvl="0"><w:startOverride w:val="5"/>'
        '<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="lowerRoman"/><w:lvlText w:val="%1)"/></w:lvl></w:lvlOverride></w:num>')
with zipfile.ZipFile(base) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
    for it in zin.infolist():
        d = zin.read(it.filename)
        if it.filename == "word/numbering.xml":
            d = d.decode().replace("</w:numbering>", NUMS + "</w:numbering>").encode()
        zout.writestr(it, d)
doc = read_docx(dst)
print("abstract 0 lvl0 (numId 7):", [p.autonum for p in read_docx(base).all_paragraphs() if p.numbering])
print("autonum:", [p.autonum for p in doc.all_paragraphs() if p.numbering])
from jasme_jats.numbering import Numbering
