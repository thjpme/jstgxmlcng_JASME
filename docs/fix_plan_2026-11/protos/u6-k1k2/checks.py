import sys, tempfile
from pathlib import Path
from common import OUT, ROOT, journal, meta
sys.path.insert(0, str(ROOT/"tests"))
import test_structure as ts
from jasme_jats.pipeline import Options, convert
tmp = Path(tempfile.mkdtemp(dir=OUT))
for case, tokens in ts.FN_SPAN_CASES.items():
    res = convert(ts.fn_span_article(tmp, tokens, case), meta, journal, Options(out_dir=tmp/("o"+case), convert_metafiles=False))
    print(case, "checks", [(c[0], c[1]) for c in res.plan.fn_guess_checks], "notes", res.plan.fn_guess_notes, "span", {k: len(v) for k,v in res.plan.fn_guess_span.items()})
