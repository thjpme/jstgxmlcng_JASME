exec(open("proto_base.py").read())
W = Path("/tmp/claude-0/-home-user-jstgxmlcng-JASME/72d6c468-bb77-50d1-8396-803f4558807a/scratchpad/review-u5-exclusions/work")
import sys
name = sys.argv[1]
p = W / f"e_{name}.docx"
res = convert(p, meta, j, Options(out_dir=W / f"e2_{name}", convert_metafiles=False))
f = res.fidelity
print(f.missing, f.conflicts, f.mismatches[:2], f.duplicates, f.bad_excluded)
