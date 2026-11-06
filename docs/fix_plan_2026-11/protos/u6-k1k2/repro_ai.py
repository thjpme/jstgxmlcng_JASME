"""AI 補完（set_role で組み直す）の後に K1・K2 の形ができるか。"""
import json
from common import OUT, S, article, para, run, summary

P = lambda st, t: para(S[st], t)  # noqa: E731


def manual(ops):
    return json.dumps({"operations": [dict(op="set_role", text="", occurrence=1, target="", image="", confidence="高",
                                           reason="試験", **o) for o in ops], "placements": [], "notes": []}, ensure_ascii=False)


def by_text(plan, t):
    return [s for s, p in plan.paras.items() if p.plain() == t]


# K1: 引用文献の 2 件目の段落を AI が ref_heading にする
path = article(OUT / "ai_k1.docx", back=[P("ref_head", "引用文献"), P("ref", "試験六郎（2024）．『本』．架空社．"),
                                        P("ref", "参考文献"), P("ref", "架空花子（2020）．『本』．架空社．")])
res0 = run("ai_k1_0", path)
src = by_text(res0.plan, "参考文献")[0]
print("K1 before AI", summary(res0), "region", res0.plan.region.get(src))
res = run("ai_k1", path, ai_mode="manual", ai_response=manual([dict(src=src, role="ref_heading")]))
print("K1 after AI", summary(res), "accepted", len(res.ai.accepted), "rejected", [w for _, w in res.ai.rejected])

# K1: 本文の段落を AI が ack_heading にする（謝辞が 2 つになる）
path = article(OUT / "ai_k1b.docx", body=[P("body", "謝辞"), P("body", "先の謝辞の本文。"), P("body", "お礼"), P("body", "後の謝辞の本文。")])
res0 = run("ai_k1b_0", path)
src = by_text(res0.plan, "お礼")[0]
print("K1b before AI", summary(res0), "region", res0.plan.region.get(src))
res = run("ai_k1b", path, ai_mode="manual", ai_response=manual([dict(src=src, role="ack_heading")]))
print("K1b after AI", summary(res), "rejected", [w for _, w in res.ai.rejected])

# K1: 本文の「注」に AI が p を指定 → 推定されなくなり上書きが消える（AI が直す方向）
path = article(OUT / "ai_k1c.docx", body=[P("body", "注"), P("body", "1) 注。"), P("body", "注"), P("body", "2) 注。")])
res0 = run("ai_k1c_0", path)
srcs = by_text(res0.plan, "注")
print("K1c before AI", summary(res0))
res = run("ai_k1c", path, ai_mode="manual", ai_response=manual([dict(src=srcs[1], role="p")]))
print("K1c after AI (2つ目を p)", summary(res), "rejected", [w for _, w in res.ai.rejected])

# K2: 所属・著者・所属・著者 の著者 1 を AI が exclude / title にする
for role in ("exclude", "title", "subtitle"):
    path = article(OUT / f"ai_k2_{role}.docx", ja_rows=(), loose=(P("aff_ja", "第一大学"), P("author_ja", "試験　六郎"),
                                                                 P("aff_ja", "第二大学"), P("author_ja", "架空　花子")))
    res0 = run(f"ai_k2_{role}_0", path)
    src = by_text(res0.plan, "試験　六郎")[0]
    print("K2 before AI", summary(res0), "region", res0.plan.region.get(src))
    res = run(f"ai_k2_{role}", path, ai_mode="manual", ai_response=manual([dict(src=src, role=role)]))
    print(f"K2 after AI ({role})", summary(res), "rejected", [w for _, w in res.ai.rejected])
