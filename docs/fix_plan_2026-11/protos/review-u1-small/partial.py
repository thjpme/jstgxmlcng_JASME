import sys
sys.path.insert(0, "/tmp/claude-0/-home-user-jstgxmlcng-JASME/72d6c468-bb77-50d1-8396-803f4558807a/scratchpad/u1-small")
from lxml import etree
from numfix import FixedNumbering
from jasme_jats.numbering import Numbering
W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
x=f'''<w:numbering xmlns:w="{W}"><w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="(%1)"/></w:lvl></w:abstractNum>
<w:num w:numId="1"><w:abstractNumId w:val="0"/><w:lvlOverride w:ilvl="0"><w:lvl w:ilvl="0"><w:start w:val="4"/></w:lvl></w:lvlOverride></w:num>
<w:num w:numId="2"><w:abstractNumId w:val="0"/><w:lvlOverride w:ilvl="0"><w:lvl w:ilvl="0"><w:numFmt w:val="upperLetter"/></w:lvl></w:lvlOverride></w:num></w:numbering>'''
r=etree.fromstring(x)
for cls in (Numbering, FixedNumbering):
    n=cls(r); print(cls.__name__, [n.label("1",0), n.label("1",0), n.label("2",0)])
