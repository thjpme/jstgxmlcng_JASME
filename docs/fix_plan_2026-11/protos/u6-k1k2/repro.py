"""K1・K2 の再現（不変性チェックの missing の段落 ID を確かめる）。"""
import json
from common import OUT, S, article, para, run, summary

P = lambda st, t: para(S[st], t)  # noqa: E731
REF = P("ref", "試験六郎（2024）．「小さな論文」．『架空誌』，第5巻，pp.9-10．")
FN1 = P("body", "1) 注の本文である。")

CASES = {
    # --- K1
    "K1_ref_ref": dict(back=[P("ref_head", "引用文献"), REF, P("ref_head", "参考文献"), P("ref", "架空花子（2020）．『本』．架空社．")]),
    "K1_ref_reftext": dict(back=[P("ref_head", "引用文献"), REF, P("body", "参考文献"), P("ref", "架空花子（2020）．『本』．架空社．")]),
    "K1_ack_ack_style": dict(back=[P("ack_head", "謝辞"), P("body", "先の謝辞の本文。"), P("ack_head", "謝辞"), P("body", "後の謝辞の本文。"),
                                    P("ref_head", "引用文献"), REF]),
    "K1_ack_ack_text": dict(body=[P("body", "謝辞"), P("body", "先の謝辞の本文。"), P("body", "謝辞"), P("body", "後の謝辞の本文。")]),
    "K1_notes_notes": dict(back=[P("notes_head", "付記"), P("body", "先の付記。"), P("ref_head", "引用文献"), REF,
                                  P("notes_head", "付記"), P("body", "後の付記。")]),
    "K1_fn_style2": dict(body=[P("fn_head", "注"), FN1, P("fn_head", "注"), P("body", "2) 二つ目の注。")]),
    "K1_fn_style_text": dict(body=[P("fn_head", "注"), FN1, P("body", "注"), P("body", "2) 二つ目の注。")]),
    "K1_fn_text2_kept": dict(body=[P("body", "注"), FN1, P("body", "注"), P("body", "2) 二つ目の注。")]),
    "K1_fn_text2_K5_returned": dict(body=[P("body", "注"), P("body", "表の下の説明。"), P("sec1", "２．続き"), P("body", "本文。"),
                                          P("body", "注"), FN1]),
    "K1_fn_text2_first_returned_second_kept_body": dict(body=[P("body", "注"), P("body", "表の下の説明。"), P("sec1", "２．続き"),
                                                              P("body", "注"), P("body", "表の下の説明2。")]),
    "K1_fn_after_refs_then_ref_again": dict(back=[P("ref_head", "引用文献"), REF, P("fn_head", "注"), FN1, P("ref_head", "参考文献"),
                                                  P("ref", "架空花子（2020）．『本』．架空社．")]),
    "K1_blank_ref_head_first": dict(back=[P("ref_head", ""), P("ref_head", "引用文献"), REF]),
    "K1_space_ref_head_first": dict(back=[P("ref_head", "　"), P("ref_head", "引用文献"), REF]),
    "K1_blank_ref_head_last": dict(back=[P("ref_head", "引用文献"), REF, P("ref_head", "")]),
    # 英文側: Abstract 見出しが 2 つ（K1 の一覧の外）
    "X_abstract_heading2": dict(en_after=[P("abs_head", "Abstract"), P("abs", "Second abstract.")]),
    # --- K2
    "K2_loose_aff_aff_author": dict(ja_rows=(), loose=(P("aff_ja", "第一大学"), P("aff_ja", "第二大学"), P("author_ja", "試験　六郎"))),
    "K2_loose_trailing_aff": dict(ja_rows=(), loose=(P("aff_ja", "第一大学"), P("author_ja", "試験　六郎"), P("aff_ja", "第二大学"))),
    "K2_loose_aff_author_author": dict(ja_rows=(), loose=(P("aff_ja", "第一大学"), P("author_ja", "試験　六郎"), P("author_ja", "架空　花子"))),
    "K2_loose_aff_blank_aff_author": dict(ja_rows=(), loose=(P("aff_ja", "第一大学"), P("aff_ja", ""), P("author_ja", "試験　六郎"))),
    "K2_loose_dup_aff": dict(ja_rows=(), loose=(P("aff_ja", "第一大学"), P("author_ja", "試験　六郎"), P("aff_ja", "第一大学"),
                                                P("aff_ja", "第一大学"), P("author_ja", "架空　花子"))),
    "K2_table_affonly_row_first": dict(ja_rows=(("第一大学", ""), ("第二大学", "試験　六郎"))),
    "K2_table_affonly_row_last": dict(ja_rows=(("第一大学", "試験　六郎"), ("第二大学", ""))),
    "K2_table_nameonly_row": dict(ja_rows=(("第一大学", "試験　六郎"), ("", "架空　花子"))),
    "K2_table_then_loose_author": dict(ja_rows=(("第一大学", ""),), loose=(P("author_ja", "試験　六郎"),)),
    # 英文側
    "EN_aff_before_name": dict(en_rows=(("aff", "Fictional University"), ("name", "Rokuro SHIKEN"))),
    "EN_aff_aff_name": dict(en_rows=(("aff", "First University"), ("aff", "Second University"), ("name", "Rokuro SHIKEN"))),
    "EN_name_aff_aff": dict(en_rows=(("name", "Rokuro SHIKEN"), ("aff", "First University"), ("aff", "Second University"))),
    "EN_trailing_aff": dict(en_rows=(("name", "Rokuro SHIKEN"), ("aff", "Fictional University"), ("aff", "Other University"))),
}


def main():
    rows = {}
    for name, kw in CASES.items():
        path = article(OUT / f"{name}.docx", **kw)
        res = run(name, path)
        s = summary(res)
        plan = res.plan
        s["fn_heading"] = plan.fn_heading.src if plan.fn_heading else None
        s["ref_heading"] = plan.ref_heading.src if plan.ref_heading else None
        s["fn_guess_notes"] = plan.fn_guess_notes
        s["fn_guess_checks"] = [c[:2] for c in plan.fn_guess_checks]
        s["affs"] = [(a.ja.src if a.ja else None, a.en.src if a.en else None) for a in plan.affs]
        s["authors"] = [(a.name_ja.src if a.name_ja else None, [x.ja.src if x.ja else x.en.src for x in a.affs]) for a in plan.authors]
        rows[name] = s
        print(name, json.dumps(s, ensure_ascii=False))
    (OUT / "repro.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
