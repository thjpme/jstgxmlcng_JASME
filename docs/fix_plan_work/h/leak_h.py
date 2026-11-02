"""作業ツリーの変更（git diff の追加行・未追跡ファイル・fixture の docx）に、tests/private の文字と 12 文字以上一致する窓がないか。
HEAD のリポジトリの文字にもある窓は除く。出力は端末だけ。"""
import re, subprocess, sys, zipfile, unicodedata
from pathlib import Path
REPO=Path('/home/user/jstgxmlcng_JASME'); N=12
WS=re.compile(r"[\s　﻿​­￾￼]+")
def norm(s): return WS.sub('',s)
def docx_text(p):
    out=[]
    with zipfile.ZipFile(p) as z:
        for n in z.namelist():
            if n.endswith('.xml'): out+=re.findall(r'<w:t[^>]*>([^<]*)</w:t>', z.read(n).decode('utf-8','replace'))
    return ''.join(out)
def pdf_text(p):
    import pypdfium2 as pdfium
    d=pdfium.PdfDocument(str(p)); return ''.join(pg.get_textpage().get_text_range() for pg in d)
priv=''
for p in sorted((REPO/'tests/private').rglob('*')):
    if p.suffix=='.docx': priv+=docx_text(p)
    elif p.suffix=='.pdf':
        try: priv+=pdf_text(p)
        except Exception as e: print('pdf skip',p.name,e)
def windows(s):
    s=norm(s); return {s[i:i+N] for i in range(len(s)-N+1)}
pw=windows(priv)|windows(unicodedata.normalize('NFKC',priv))
print('private windows',len(pw))
# HEAD text
head=''
for f in subprocess.run(['git','ls-files'],cwd=REPO,capture_output=True,text=True).stdout.split():
    if f.endswith('.docx'):
        head+=docx_text(REPO/f) if (REPO/f).exists() else ''
        continue
    b=subprocess.run(['git','show',f'56d5b59:{f}'],cwd=REPO,capture_output=True).stdout
    try: head+=b.decode('utf-8')
    except UnicodeDecodeError: pass
hw=windows(head)
# changed text
diff=subprocess.run(['git','diff','--unified=0','--no-color','56d5b59','HEAD'],cwd=REPO,capture_output=True,text=True).stdout
added='\n'.join(l[1:] for l in diff.splitlines() if l.startswith('+') and not l.startswith('+++'))
unt=subprocess.run(['git','ls-files','--others','--exclude-standard'],cwd=REPO,capture_output=True,text=True).stdout.split()
for f in unt:
    p=REPO/f
    added+= docx_text(p) if p.suffix=='.docx' else p.read_text('utf-8','replace')
# fixtures docx changed
for f in subprocess.run(['git','diff','--name-only','56d5b59','HEAD'],cwd=REPO,capture_output=True,text=True).stdout.split():
    if f.endswith('.docx'): added+=docx_text(REPO/f)
aw=windows(added)|windows(unicodedata.normalize('NFKC',added))
hit=aw&pw; new=hit-hw
print('hits',len(hit),'not in HEAD',len(new))
for w in sorted(new)[:40]: print(' ',w)
