import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
from jasme_jats.config import ArticleMeta, JournalConfig
from jasme_jats.pipeline import convert, Options
journal = JournalConfig.load()
meta = ArticleMeta.from_dict({'volume':'31','issue':'1','fpage':'1','lpage':'12'})
for n in ["head_to_body", "head_all_to_body", "span_mismatch_wide_top", "span_mismatch_narrow_top", "owner_not_cleared", "both_cont"]:
    res = convert(HERE / "docx" / f"{n}.docx", meta, journal, Options(out_dir=HERE / "out_w" / n, convert_metafiles=False))
    print(n, [w for w in res.warnings if "結合" in w])
