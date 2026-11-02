"""単位 H（D2・M5・U4）の反例の原稿（docx）と期待（cases.json）を作る。実装（linker.py の fn_marks・float_refs・_link_num、
ai_assist.build_request、pipeline.py、DESIGN_H.md）は見ずに、docs/FIX_PLAN.md の H の節と付録 D2・M5・U4・U5、DESIGN.md から決めた。

  PYTHONDONTWRITEBYTECODE=1 python gen_h.py      # cases/*.docx と cases.json を作る

- docx は tests/make_fixtures.py の部品（Builder・para・run・front_ja・front_en・tail・table・cell・drawing・textbox・omathpara）
  を import して作る（make_fixtures.py は変えない）。文字はすべて架空。
- 段落は「部品」の列で書く: 文字列はふつうのラン、("s", 文字) は上付きのラン。段落の文字（plain）は部品の文字をつないだもの。
- 論文の種類（kind）: strong は本文に「1)」の形の上付きの注番号があり、注の一覧は「1) …」〜「3) …」。bare は本文の注番号が
  数字だけの上付きで、注の一覧も上付きの数字（¹〜³）。none は注の一覧がない。
- 期待の level: exact は FIX_PLAN の H から一つに決まるもの。either は決めかねるもの（alts に許される結果を列挙）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path("/home/user/jstgxmlcng_JASME")
sys.path.insert(0, str(REPO / "tests"))
import make_fixtures as mf

S = mf.S
CM = 360000
LINKCATS = ["note", "figure", "table", "xref"]      # リンクしなかった箇所の記録（Decision）の category として認めるもの
FN, FIG, TAB, FML = ["fn"], ["fig"], ["table"], ["disp-formula"]
FT = ["fig", "table"]


def plain(segs):
    return "".join(s if isinstance(s, str) else s[1] for s in segs)


def offset_of(segs, k):
    """k 番目の部品の、段落の中の開始位置。"""
    return len(plain(segs[:k]))


def runs(segs):
    out = []
    for s in segs:
        if isinstance(s, str):
            out.append(mf.run(s))
        else:
            out.append(mf.run(s[1], sup=True))
    return out


# ============================================================================= 期待の書き方
def xr(types, rids, level="exact", alts=None, why=""):
    """段落の中の、types の xref の rid の並び（文書の順。rid が複数なら空白で分けて並べる）。"""
    d = {"check": "xref", "types": types, "level": level, "why": why}
    if level == "exact":
        d["rids"] = rids
    else:
        d["alts"] = alts
    return d


def xoff(types, offsets, why=""):
    """段落の中の、types の xref の開始位置（段落の文字の何文字目か）の並び。"""
    return {"check": "offsets", "types": types, "offsets": offsets, "level": "exact", "why": why}


def dec(minimum=None, maximum=None, level="exact", alts=None, why=""):
    """段落の、リンクしなかった箇所の記録（plan.decisions の category が LINKCATS で src がその段落のもの）の件数。
    記録があるときは、レポートの 4 章と AI 依頼文にも出ること（D の方針）も確かめる。"""
    return {"check": "dec", "min": minimum, "max": maximum, "level": level, "alts": alts, "why": why}


def same_ref(types, why=""):
    """段落の中の types の xref（種類・rid・文字・位置）が、比べる相手（0.26.0）と同じ。"""
    return {"check": "same_ref", "types": types, "level": "exact", "why": why}


def boxed(why=""):
    return {"check": "boxed", "level": "exact", "why": why}


def paste(seg_index, target, text, occurrence, why=""):
    """記録の文面から link_note の text と occurrence を読み取り、手動モードの回答として貼り戻すと、seg_index の部品の位置に
    target への注のリンクができる（FIX_PLAN 付録 D2 の (4)）。"""
    return {"check": "paste", "seg": seg_index, "target": target, "text": text, "occurrence": occurrence, "level": "exact",
            "why": why}


# ============================================================================= 論文の組み立て
def notes_list(b, kind, n=3):
    out = [mf.para(S["fn_head"], "注")]
    texts = ["一つ目の架空の補足である。", "二つ目の架空の補足である。", "三つ目の架空の補足である。"]
    for k in range(n):
        if kind == "strong":
            out.append(mf.para(S["body"], f"{k + 1}) {texts[k]}"))
        else:
            out.append(mf.para(S["body"], mf.run(str(k + 1), sup=True), "　" + texts[k]))
    return out


def float_block(b):
    """図1・図2（画像）、表1（本体あり）、別行数式 (1)。本文の最後に置く（囲みから 3 段落以上離すため）。"""
    f1 = b.add_image("h_fig1.png", mf.png_bytes("Fictional shape A"))
    f2 = b.add_image("h_fig2.png", mf.png_bytes("Fictional shape B", size=(480, 260)))
    return [
        mf.para(S["body"], "以下に架空の図と表と式をまとめて置く。"),
        mf.para(S["body"], mf.omathpara(mf.mr("S=") + mf.mfrac(mf.mr("1"), mf.mr("2")) + mf.mr("ah")), mf.tab(), "(1)",
                jc="center"),
        mf.para(S["body"], mf.drawing(f1, 2880000, 1800000, 801), jc="center"),
        mf.para(S["fig_cap"], "図1　架空の図形の甲"),
        mf.para(S["body"], mf.drawing(f2, 2880000, 1560000, 802), jc="center"),
        mf.para(S["fig_cap"], "図2　架空の図形の乙"),
        mf.para(S["tab_cap"], "表1　架空の集計"),
        mf.table([[mf.cell(mf.run("区分", b=True)), mf.cell(mf.run("値", b=True))],
                  [mf.cell("甲"), mf.cell("七")]], header_rows=1),
        mf.para(S["body"], ""),
    ]


def build(case, path):
    b = mf.Builder()
    kind = case["kind"]
    body = mf.front_ja(b, "架空の検証論文の題目", "―リンクの規則を試す―",
                       case.get("authors_ja", [("架空大学", "試験　太郎")]))
    body.append(mf.para(S["sec1"], "１．はじめに"))
    anchor = case.get("anchor", "default")
    if anchor == "default":
        if kind == "strong":
            body.append(mf.para(S["body"], "前置きの段落である", mf.run("1)", sup=True), "。"))
        elif kind == "bare":
            body.append(mf.para(S["body"], "前置きの段落である", mf.run("1", sup=True), "。"))
        else:
            body.append(mf.para(S["body"], "前置きの段落である。"))
    elif anchor:
        body.append(mf.para(S["body"], *runs(anchor)))
    for p in case["paras"]:
        if p.get("box"):
            continue
        body.append(mf.para(S["body"], *runs(p["segs"])))
    box = [p for p in case["paras"] if p.get("box")]
    if box:
        inner = "".join(mf.para(S["body"], *runs(p["segs"])) for p in box)
        body.append(mf.para(S["body"], "次の囲みを読む。",
                            mf.textbox(inner, 811, cx=12 * CM, cy=3 * CM, wrap="wrapTopAndBottom")))
        body.append(mf.para(S["body"], "囲みの後の一つ目の段落である。"))
        body.append(mf.para(S["body"], "囲みの後の二つ目の段落である。"))
        body.append(mf.para(S["body"], "囲みの後の三つ目の段落である。"))
    if case.get("floats", True):
        body += float_block(b)
    if kind != "none":
        body += notes_list(b, kind)
    body.append(mf.para(S["ref_head"], "引用および参考文献"))
    body.append(mf.para(S["ref"], "試験太郎（2020）．「架空の論考」．『架空誌』，第1巻，pp.1-2．"))
    body += mf.front_en(b, "A Fictional Paper for Link Rules", "Checking Links",
                        case.get("authors_en", [("Taro SHIKEN", "Fictional University")]), ["Fictional abstract."])
    body += mf.tail(b)
    b.save(path, body)


def P(key, segs, *checks, box=False):
    return {"key": key, "segs": segs, "checks": list(checks), "box": box}


# ============================================================================= ケース
CASES = []


def case(cid, kind, desc, paras, **kw):
    c = {"id": cid, "kind": kind, "desc": desc, "paras": paras, "case_checks": kw.pop("case_checks", [])}
    c.update(kw)
    CASES.append(c)


case("C00", "strong", "対照: 注・図・表・式の参照がふつうの形だけ（リンクは 0.26.0 と同じ、記録なし）", [
    P("a", ["架空の調査を行った", ("s", "2)"), "。図1と表1と式(1)を参照する。"],
      xr(FN, ["fn2"]), xr(FT, ["F1", "T1"]), xr(FML, ["FD1"]), dec(maximum=0)),
])

# ----------------------------------------------------------------------------- D2: 「1)」の書き方の論文
case("S01", "strong", "番号の形がはっきりした注番号（上付きの「1)」、上付きの外の閉じ括弧で補う形）はリンクする", [
    P("a", ["架空の調査を行った", ("s", "1)"), "。"], xr(FN, ["fn1"])),
    P("b", ["架空の結果である", ("s", "2"), ")。"], xr(FN, ["fn2"], why="付録 D2 の点検: 本文「である」＋上付き「1」＋本文「)」→ fn1")),
    P("c", ["別の結果である", ("s", "3"), "）。"], xr(FN, ["fn3"], why="全角の閉じ括弧でも同じ")),
])
case("S02", "strong", "単位・変数の後ろの上付きの数字（cm²・x²+y²）と符号で始まる上付き（s⁻¹・m s⁻²）は注にリンクしない", [
    P("a", ["底面積は 3 cm", ("s", "2"), " である。"], xr(FN, []), dec(minimum=1)),
    P("b", ["架空の式 x", ("s", "2"), "+y", ("s", "2"), " を考える。"], xr(FN, []),
      dec(minimum=1, why="件数（1 件か 2 件か）は利用者の決定事項 15（段落ごとに 1 行）と H の節（数字ごと）で食い違うので問わない")),
    P("c", ["面積は 5 cm² である。"], xr(FN, [], why="上付きの書式ではない Unicode の ² はもともと対象外")),
    P("d", ["速さの単位は m s", ("s", "−1"), " とする。"], xr(FN, []),
      dec(level="either", alts=["any"], why="符号で始まる続きを記録するかは H から一つに決まらない")),
    P("e", ["加速度は m s", ("s", "-2"), " である。"], xr(FN, []), dec(level="either", alts=["any"])),
])
case("S04", "strong", "数字と区切りの続きに閉じ括弧（1,2)・1-3)）はリンクする", [
    P("a", ["二つの調査がある", ("s", "1,2)"), "。"], xr(FN, ["fn1", "fn2"], why="付録 D2 (1)「1,2)」の 1 にもリンク")),
    P("b", ["三つの資料もある", ("s", "1-3)"), "。"], xr(FN, None, level="either", alts=[["fn1", "fn3"], ["fn1 fn2 fn3"], ["fn1 fn3"]],
                                              why="1 と 3 にリンク（範囲を 1 つの xref にまとめる形も許す）")),
])
case("S05", "strong", "「注」「註」の字（上付きの中・外）や括弧の付いた上付きはリンクする", [
    P("a", ["この点は注", ("s", "3"), "で補う。"], xr(FN, ["fn3"], why="続きの直前が「注」")),
    P("b", ["別の点は", ("s", "註1"), "に記す。"], xr(FN, ["fn1"], why="付録 D2 の点検: 上付き「註1」→ fn1")),
    P("c", ["第三の点は", ("s", "（2）"), "に記す。"], xr(FN, ["fn2"], why="RE_SUP_FN の括弧つき")),
    P("d", ["第四の点は", ("s", "注3"), "である。"], xr(FN, ["fn3"])),
])
case("S06", "strong", "関数の括弧の中の指数（f(x²)）: 閉じ括弧が続いても指数ならリンクしない。記録が残る", [
    P("a", ["関数 f(x", ("s", "2"), ") の値を求める。"], xr(FN, []), dec(minimum=1, why="付録 D2 の点検: リンクなし（記録あり）")),
])
case("S07", "strong", "数字の後ろの上付き（10³・10^{2,3}・x^{1-3}）は続き全体で指数と判定してリンクしない", [
    P("a", ["個数は 10", ("s", "3"), " 個である。"], xr(FN, []), dec(minimum=1)),
    P("b", ["組は 10", ("s", "2,3"), " である。"], xr(FN, []), dec(minimum=1)),
    P("c", ["項は x", ("s", "1-3"), " である。"], xr(FN, []), dec(minimum=1)),
])
case("S08", "strong", "注の一覧にない番号の上付き（5)）はリンクしない。英字の後ろでも「2)」はリンクする", [
    P("a", ["架空の補足がある", ("s", "5)"), "。"], xr(FN, []), dec(level="either", alts=["any"])),
    P("b", ["Shiken", ("s", "2)"), " の議論を参照する。"],
      xr(FN, ["fn2"], why="閉じ括弧で終わる上付きは番号の形がはっきりした注番号（指数の判定は数字だけの一致にかける）")),
])
case("S09", "strong", "「1)」の書き方の論文では、かなの後ろの数字だけの上付き（²・1, 2）もリンクしない。記録が残る", [
    P("a", ["架空の主張である", ("s", "2"), "。"], xr(FN, []), dec(minimum=1, why="決定事項 15: 「1)」が 1 つでもあれば数字だけの上付きは注番号にしない")),
    P("b", ["並べた番号もある", ("s", "1, 2"), "。"], xr(FN, []), dec(minimum=1)),
])
case("S10", "strong", "記録の文面（text と occurrence）で link_note を貼り戻すと、その上付きにリンクできる", [
    P("a", ["架空の 2022 年版の面積は 2 m", ("s", "2"), " である。"], xr(FN, []), dec(minimum=1),
      paste(1, "fn2", "2", 4, why="「2」は段落の中で 4 回目（2022 の 2 つの 2 と「2 m」の 2 の後）。付録 D2 (4)")),
])

# ----------------------------------------------------------------------------- D2: 同じ本文を、2 つの書き方の論文で
TWIN = ["架空の見解である", ("s", "2"), "。広さは 4 m", ("s", "2"), " である。"]
case("TWS", "strong", "同じ本文（かなの後ろの ²、m²）を「1)」の書き方の論文で: どちらもリンクしない", [
    P("a", TWIN, xr(FN, []), dec(minimum=1)),
])
case("TWB", "bare", "同じ本文を数字だけの書き方の論文で: かなの後ろの ² は fn2、m² はリンクしない", [
    P("a", TWIN, xr(FN, ["fn2"]), xoff(FN, [offset_of(TWIN, 1)]), dec(minimum=1)),
])

# ----------------------------------------------------------------------------- D2: 数字だけの書き方の論文
B01 = ["架空の主張である", ("s", "1"), "。（試験, 2020）", ("s", "2"), "。面積は 4 m", ("s", "2"), "。"]
case("B01", "bare", "数字だけの論文: かな・閉じ括弧の後ろの ¹ ² はリンク、m² はしない（付録 D2 (2)）。貼り戻し", [
    P("a", B01, xr(FN, ["fn1", "fn2"]), xoff(FN, [offset_of(B01, 1), offset_of(B01, 3)]), dec(minimum=1),
      paste(5, "fn2", "2", 4, why="「2」は 4 回目（2020 の 2 つの 2、「）²」の後）")),
])
case("B02", "bare", "数字だけの論文: 数字と区切りの続き（1-3、1, 2）は続き全体の前後で判定してリンクする", [
    P("a", ["三つの例がある", ("s", "1-3"), "。"],
      xr(FN, None, level="either", alts=[["fn1", "fn3"], ["fn1 fn2 fn3"], ["fn1 fn3"]], why="付録 D2 の点検: 1 と 3 がリンク")),
    P("b", ["二つの例がある", ("s", "1, 2"), "。"], xr(FN, ["fn1", "fn2"])),
])
case("B03", "bare", "数字だけの論文: 指数（x²・2³・10³・cm³）と符号で始まる上付き（毎時⁻¹）はリンクしない", [
    P("a", ["x", ("s", "2"), " と 2", ("s", "3"), " と 10", ("s", "3"), " と 3 cm", ("s", "3"), " を比べる。"], xr(FN, []), dec(minimum=1)),
    P("b", ["減り方は毎時", ("s", "−1"), "である。"], xr(FN, []), dec(level="either", alts=["any"]),),
])
case("B04", "bare", "数字だけの論文: 「注」の後ろの上付きはリンク、注の一覧にない番号はリンクしない", [
    P("a", ["詳しくは注", ("s", "3"), "を見よ。"], xr(FN, ["fn3"])),
    P("b", ["架空の補足がある", ("s", "7"), "。"], xr(FN, []), dec(level="either", alts=["any"])),
])
case("B05", "bare", "本文の「注」＋上付き「1」だけの論文は、書き方の判定に使わないので数字だけの論文のまま（² もリンク）", [
    P("a", ["架空の見解である", ("s", "2"), "。"], xr(FN, ["fn2"], why="続きの直前が「注」の一致は書き方の判定に使わない")),
], anchor=["これは注", ("s", "1"), "で述べる。"])
case("B06", "bare", "上付き「1」＋本文「）」がはっきりした注番号になる論文の、かなの後ろの ²（判定に使うかは決めかねる）", [
    P("a", ["架空の主張である", ("s", "2"), "。"], xr(FN, None, level="either", alts=[["fn2"], []])),
], anchor=["前置きの段落である", ("s", "1"), "）。"])

# ----------------------------------------------------------------------------- D2: 注のない論文
case("N01", "none", "注の一覧のない論文: 上付きの「1)」も cm² も注にリンクしない（DTD に合う）", [
    P("a", ["架空の調査である", ("s", "1)"), "。面積は 3 cm", ("s", "2"), "。"], xr(FN, []), dec(level="either", alts=["any"])),
])

# ----------------------------------------------------------------------------- D2・M5: 囲み（テキストボックス）の中
case("BOX", "strong", "囲みの中も同じ規則: 地図1 はリンクせず 図1 はリンク、cm² はリンクせず「2)」はリンク", [
    P("a", ["囲みの問い　架空の地図1を見て、図1の面積を求めよ。"], xr(FT, ["F1"]), xoff(FT, [len("囲みの問い　架空の地図1を見て、")]),
      boxed(why="F の規則（20 字以上・幅が 1 段の 0.6 以上・画像から離れている）"), dec(minimum=1), box=True),
    P("b", ["底面は 3 cm", ("s", "2"), "、条件は資料による", ("s", "2)"), "。"], xr(FN, ["fn2"]),
      xoff(FN, [len("底面は 3 cm2、条件は資料による")]), dec(minimum=1), box=True),
])

# ----------------------------------------------------------------------------- M5: 語の中の「図1」「表1」
case("M01", "strong", "語の外の参照はリンクする（文の先頭の図1・括弧の中の（図1）・「この図1」・表1のとおり）。「各表1」はしない", [
    P("a", ["図1に示す架空の形である。"], xr(FT, ["F1"])),
    P("b", ["架空の形を示した（図1）。"], xr(FT, ["F1"])),
    P("c", ["この形は表1のとおりである。"], xr(FT, ["T1"])),
    P("d", ["この図1と各表1を比べる。"], xr(FT, ["F1"]), dec(minimum=1, why="各 は漢字で 掲至及 にない")),
])
case("M02", "strong", "地図1・概念図1・代表1名・本図1はリンクしない（図1・表1 があるので記録あり）", [
    P("a", ["架空の地図1を配った。"], xr(FT, []), dec(minimum=1)),
    P("b", ["概念図1を描いた。"], xr(FT, []), dec(minimum=1)),
    P("c", ["代表1名が答えた。"], xr(FT, []), dec(minimum=1)),
    P("d", ["本図1を見る。"], xr(FT, []), dec(minimum=1, why="決定事項 16: 掲・至・及 のまま（本 は語の一部とみなす）")),
])
case("M03", "strong", "図表1・発表1回目はリンクしない（表1 があるので記録あり）", [
    P("a", ["図表1を見る。"], xr(FT, []), dec(minimum=1)),
    P("b", ["発表1回目の記録である。"], xr(FT, []), dec(minimum=1, why="付録 M5: 発表1回目（表1 あり）にも Decision")),
])
case("M04", "strong", "付表1 はリンクせず記録あり、前掲表1・前掲図1 はリンクする", [
    P("a", ["付表1に示す。"], xr(FT, []), dec(minimum=1)),
    P("b", ["前掲表1に示す。"], xr(FT, ["T1"])),
    P("c", ["前掲図1を見る。"], xr(FT, ["F1"])),
])
case("M05", "strong", "語の中の一致の後ろから探し直す（図表1と表1・地図1、図2）、続きの番号ごと語の一部（地図1、2）", [
    P("a", ["図表1と表1を比べる。"], xr(FT, ["T1"]), xoff(FT, [len("図表1と")]), dec(minimum=1)),
    P("b", ["地図1、図2の順に見る。"], xr(FT, ["F2"]), xoff(FT, [len("地図1、")]), dec(minimum=1)),
    P("c", ["地図1、2を見る。"], xr(FT, []), dec(minimum=1, maximum=1, why="付録 M5 の点検: どちらもリンクされない（記録は 1 件）")),
])
case("M06", "strong", "前に来てよい漢字（掲・至・及）: 図1乃至図2・図1及図2 は両方リンクする", [
    P("a", ["図1乃至図2を見る。"], xr(FT, None, level="either", alts=[["F1", "F2"], ["F1 F2"]])),
    P("b", ["図1及図2を見る。"], xr(FT, None, level="either", alts=[["F1", "F2"], ["F1 F2"]])),
])
case("M07", "strong", "番号の図・表がないとき: 地図3 は記録しない。図3 もリンクしない", [
    P("a", ["地図3を配った。"], xr(FT, []), dec(maximum=0, why="記録は先頭の番号の図・表があるときだけ")),
    P("b", ["図3を見る。"], xr(FT, []), dec(level="either", alts=["any"])),
])
case("M08", "strong", "H で変えない参照（図1、2・Fig. 1・Table 1・図 1・式(1)・数式(1)・第1表）は 0.26.0 と同じ", [
    P("a", ["図1、2を見る。"], xr(FT, ["F1", "F2"]), same_ref(FT)),
    P("b", ["Fig. 1 と Table 1 を見る。"], same_ref(FT)),
    P("c", ["図 1 を見る。"], same_ref(FT)),
    P("d", ["式(1)より求める。"], xr(FML, ["FD1"]), same_ref(FML)),
    P("e", ["数式(1)を使う。"], same_ref(FML, why="H は float_refs だけを変える（式の参照は変えない）")),
    P("f", ["第1表を見る。"], xr(FT, []), same_ref(FT)),
])

# ----------------------------------------------------------------------------- U4: AI 依頼文の「姓と名の区切りがない氏名」
case("U01", "strong", "和文の氏名: 区切りのない「研究次郎」と前後に空白のある「架空四郎　」「　架空五郎」は依頼文に出る（前後の空白は除く）。間に全角・半角の空白のある氏名は出ない", [
    P("a", ["架空の調査を行った。"]),
], authors_ja=[("架空大学", "試験\u3000太郎"), ("架空大学", "研究次郎"), ("架空大学", "試験 三郎"),
                ("架空大学", "架空四郎\u3000"), ("架空大学", "\u3000架空五郎")],
    authors_en=[("Taro SHIKEN", "Fictional University"), ("Jiro KENKYU", "Fictional University"),
                ("Saburo SHIKEN", "Fictional University"), ("Shiro KAKU", "Fictional University"),
                ("Goro KAKU", "Fictional University")],
    case_checks=[{"check": "prompt_name", "name": "研究次郎", "level": "exact", "present": True},
                 {"check": "prompt_name", "name": "試験　太郎", "level": "exact", "present": False},
                 {"check": "prompt_name", "name": "試験 三郎", "level": "exact", "present": False},
                 {"check": "prompt_name", "name": "架空四郎", "level": "exact", "present": True,
                  "why": "U4: (段落ID, text.strip(' 　\\t'), lang)。依頼文の「」の中に前後の空白を入れない"},
                 {"check": "prompt_name", "name": "架空五郎", "level": "exact", "present": True},
                 {"check": "prompt_name_count", "level": "exact", "n": 3},
                 {"check": "report_name", "name": "研究次郎", "level": "exact"}])
case("U02", "strong", "英文の 1 語の氏名「KENKYU」: レポートには残る。依頼文に出すかは H の節と決定事項 17 で食い違う", [
    P("a", ["架空の調査を行った。"]),
], authors_ja=[("架空大学", "研究　次郎")], authors_en=[("KENKYU", "Fictional University")],
    case_checks=[{"check": "prompt_name", "name": "KENKYU", "level": "either", "alts": [True, False],
                  "why": "H の節・付録 U4・まとめ役の指示は「出さない」。FIX_PLAN の決定事項 17 は「今までどおり載せる」"},
                 {"check": "prompt_name", "name": "研究　次郎", "level": "exact", "present": False},
                 {"check": "report_name", "name": "KENKYU", "level": "exact"}])


def main():
    out = HERE / "cases"
    out.mkdir(exist_ok=True)
    meta = []
    for c in CASES:
        path = out / f"{c['id']}.docx"
        build(c, path)
        paras = [{"key": p["key"], "plain": plain(p["segs"]), "segs": p["segs"],
                  "offsets": [offset_of(p["segs"], k) for k in range(len(p["segs"]))],
                  "checks": p["checks"], "box": p["box"]} for p in c["paras"]]
        meta.append({"id": c["id"], "kind": c["kind"], "desc": c["desc"], "docx": str(path), "paras": paras,
                     "case_checks": c["case_checks"]})
    (HERE / "cases.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(len(meta), "件")


if __name__ == "__main__":
    main()
