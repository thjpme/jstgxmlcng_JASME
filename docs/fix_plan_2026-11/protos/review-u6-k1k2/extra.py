import sys
sys.path.insert(0, "/tmp/scratchpad/u6-k1k2")
import proto
from common import S, article, para, run, summary
from pathlib import Path
OUT = Path(__file__).resolve().parent / "out"; OUT.mkdir(exist_ok=True)
P = lambda st, t: para(S[st], t)
REF = P("ref", "試験六郎（2024）．「小さな論文」．『架空誌』，第5巻，pp.9-10．")
FN1 = P("body", "1) 注の本文である。")
CASES = {
 "blank_ref_head_right_after": dict(back=[P("ref_head", "引用文献"), P("ref_head", ""), REF]),
 "space_ref_head_right_after": dict(back=[P("ref_head", "引用文献"), P("ref_head", "　"), REF]),
 "fn_head_then_blank_fn_head": dict(body=[P("fn_head", "注"), P("fn_head", ""), FN1]),
 "ack_blank_head_with_body": dict(back=[P("ack_head", ""), P("body", "先の謝辞。"), P("ack_head", "謝辞"), P("body", "後の謝辞。"), P("ref_head", "引用文献"), REF]),
 "ack_head_then_blank_ack_head": dict(back=[P("ack_head", "謝辞"), P("body", "謝辞の本文。"), P("ack_head", ""), P("body", "続き。"), P("ref_head", "引用文献"), REF]),
 "table_aff_row_then_name_row": dict(ja_rows=(("第一大学", ""), ("", "試験　六郎"))),
 "loose_aff_author_dupaff_author": dict(ja_rows=(), loose=(P("aff_ja", "第一大学"), P("author_ja", "試験　六郎"), P("aff_ja", "第一大学"), P("author_ja", "架空　花子"))),
 "loose_aff_spaceaff_author": dict(ja_rows=(), loose=(P("aff_ja", "第一大学"), P("aff_ja", "　"), P("author_ja", "試験　六郎"))),
 "loose_aff_then_table": dict(ja_rows=(("第一大学", "試験　六郎"),), loose=()),
 "notes_inside_refs_text": dict(back=[P("ref_head", "引用文献"), REF, P("body", "付記"), P("body", "付記の本文。"), P("body", "付記"), P("body", "後の付記。")]),
}
for name, kw in CASES.items():
    path = article(OUT / f"{name}.docx", **kw)
    res = run("x_" + name, path)
    s = summary(res)
    cs = proto.conflicts(res.plan)
    print(name, "missing", s["missing"], "conf", [(c.kind, c.lost, c.by) for c in cs], "ok", s["ok"], "keys", s["keys"])
