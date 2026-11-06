import sys
sys.path.insert(0, ".")
import audit
from pathlib import Path
from jasme_jats.pipeline import _mechanical
from jasme_jats.config import JournalConfig
p = Path("audit_out/audit.docx")
doc, plan, linker = _mechanical(p, JournalConfig.load())[:3]
for fn in plan.fns:
    print(fn.fid, fn.word_note, [(q.src, q.autonum) for q in fn.paras])
print(plan.ack and [type(c).__name__ for c in plan.ack.children])
print([w for w in plan.warnings][:5])
