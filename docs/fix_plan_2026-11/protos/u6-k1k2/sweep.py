"""試作の検出（proto.py）で、検出 ⇔ 不変性チェックの missing（落ちた段落）がちょうど一致するかを、多くの原稿で確かめる。

出力には原稿の文字を書かない（件数・段落 ID・フォルダ名だけ）。
"""
import json
import sys
from pathlib import Path

import proto  # noqa: F401  （先に読み込んで monkeypatch する）
from common import OUT, ROOT, S, article, journal, meta, para
from jasme_jats.pipeline import AIRequiredError, Options, convert

sys.path.insert(0, str(ROOT / "tests"))
import conftest  # noqa: E402
import test_structure as ts  # noqa: E402
import repro  # noqa: E402

rows = []


def check(label, path, **opt):
    o = dict(out_dir=OUT / "sweep" / label, convert_metafiles=False)
    o.update(opt)
    try:
        res = convert(path, meta, journal, Options(**o))
    except AIRequiredError:
        o["ai_mode"] = "manual"
        res = convert(path, meta, journal, Options(**o))
    cs = proto.conflicts(res.plan)
    lost = sorted({s for c in cs for s in c.lost})
    missing = sorted(s for s, _ in res.fidelity.missing)
    agree = lost == missing
    rows.append(dict(label=label, detected=bool(cs), kinds=[c.kind for c in cs], lost=lost, missing=missing, agree=agree,
                     fid_ok=res.fidelity.ok))
    flag = "" if agree else "  <-- 不一致"
    print(f"{label}: detected={bool(cs)} kinds={[c.kind for c in cs]} lost={lost} missing={missing}{flag}")


# 1. 再現の原稿
for name, kw in repro.CASES.items():
    check("repro_" + name, article(OUT / f"{name}.docx", **kw))

# 2. FN_SPAN_CASES（「注」が 1〜3 つ）と、「注」ごとに注見出しにしたもの、助言どおりのもの
import tempfile  # noqa: E402
tmp = Path(tempfile.mkdtemp(dir=OUT))
for case, tokens in ts.FN_SPAN_CASES.items():
    check(f"span_{case}", ts.fn_span_article(tmp, tokens, case))
    n = tokens.count("注")
    for k in range(n):
        check(f"span_{case}_head{k}", ts.fn_span_article(tmp, tokens, f"{case}_{k}", k))
    if n >= 2:
        check(f"span_{case}_advice", ts.fn_styled_article(tmp, tokens, case + "_adv", ["fn_head"] + ["fn_body"] * (n - 1)))
        check(f"span_{case}_first", ts.fn_styled_article(tmp, tokens, case + "_first", ["fn_head"]))

# 3. tests/fixtures のすべて
for p in sorted((ROOT / "tests" / "fixtures").glob("*.docx")):
    check("fixture_" + p.stem, p)
    pdf = p.with_suffix(".pdf")
    if pdf.exists():
        check("fixture_route2_" + p.stem, p, pdf_path=pdf, route="pdf")

# 4. tests/private（実際の原稿）。ラベルはフォルダ名と連番だけ
priv = ROOT / "tests" / "private"
for d in sorted(x for x in priv.iterdir() if x.is_dir() and x.name != "review-repros"):
    pdfs = sorted(d.glob("*.pdf"))
    for i, p in enumerate(sorted(d.glob("*.docx")), 1):
        check(f"private_{d.name}_{i}", p)
        if pdfs:
            check(f"private_{d.name}_{i}_route2", p, pdf_path=pdfs[0], route="pdf")

(OUT / "sweep.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
bad = [r["label"] for r in rows if not r["agree"]]
print("total", len(rows), "detected", sum(r["detected"] for r in rows), "disagree", bad)
