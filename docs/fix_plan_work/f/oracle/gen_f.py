"""単位 F（D1・N7）の、実装を見ない反例の原稿（docx）と期待を作る。

  python gen_f.py            # cases/*.docx と cases.json を作る

docx は tests/make_fixtures.py の部品（Builder・para・textbox・group・drawing・anchored・make_article）で作る。
make_fixtures.py にない部品（wp:inline のテキストボックス、VML の position:absolute と大きさ、画像とテキストボックス 2 つの
グループ図形）は、ここに書く。文字はすべて架空のもの。

期待は docs/FIX_PLAN.md の F の節・D1・N7・決定事項 9・10・付録の D1 だけから決めた（実装は見ていない）。
各ケースの checks は、方針から一つに決まるものを level "exact"、しきい値などに依存して決めかねるものを level "either"
（alts に許される結果を列挙）にする。checks の種類と意味は run_f.py の evaluate() を見る。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path("/home/user/jstgxmlcng_JASME")
sys.dont_write_bytecode = True      # tests/__pycache__ を作らない
sys.path.insert(0, str(REPO / "tests"))
import make_fixtures as mf  # noqa: E402

S = mf.S
CM = 360000
HERE = Path(__file__).resolve().parent
OUT = HERE / "cases"


# ----------------------------------------------------------------------------- 足りない部品
def wps_graphic(inner):
    return ('<a:graphic><a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">'
            f'<wps:wsp><wps:txbx><w:txbxContent>{inner}</w:txbxContent></wps:txbx><wps:bodyPr/></wps:wsp>'
            '</a:graphicData></a:graphic>')


def inline_textbox(inner, pid, cx=8 * CM, cy=4 * CM):
    """行内（wp:inline）のテキストボックス。Word と同じく VML の代替も付ける。"""
    fallback = f'<w:pict><v:shape><v:textbox><w:txbxContent>{inner}</w:txbxContent></v:textbox></v:shape></w:pict>'
    return ('<w:r><mc:AlternateContent><mc:Choice Requires="wps"><w:drawing>'
            f'<wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/>'
            f'<wp:docPr id="{pid}" name="テキスト ボックス {pid}"/>{wps_graphic(inner)}</wp:inline></w:drawing>'
            f'</mc:Choice><mc:Fallback>{fallback}</mc:Fallback></mc:AlternateContent></w:r>')


def vml_textbox(inner, pid, absolute=True, top="30pt", left="0", width="240pt", height="150pt"):
    """VML だけのテキストボックス（DrawingML の代替なし）。absolute なら position:absolute（浮動配置）。"""
    style = (f"position:absolute;margin-left:{left};margin-top:{top};" if absolute else "") + \
        f"width:{width};height:{height};z-index:{pid}"
    return (f'<w:r><w:pict><v:shape id="_x0000_s{pid}" type="#_x0000_t202" style="{style}">'
            f'<v:textbox><w:txbxContent>{inner}</w:txbxContent></v:textbox></v:shape></w:pict></w:r>')


def group_with_label(rid, inner_cap, inner_label, pid, cx, cy, **pos):
    """画像・キャプションのテキストボックス・注記のテキストボックスをまとめたグループ図形。"""
    pic = (f'<pic:pic><pic:nvPicPr><pic:cNvPr id="{pid + 1}" name="図"/><pic:cNvPicPr/></pic:nvPicPr>'
           f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
           f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy - CM}"/></a:xfrm>'
           '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>')
    tb = ''.join(f'<wps:wsp><wps:txbx><w:txbxContent>{x}</w:txbxContent></wps:txbx><wps:bodyPr/></wps:wsp>'
                 for x in (inner_label, inner_cap))
    graphic = ('<a:graphic><a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup">'
               f'<wpg:wgp><wpg:cNvGrpSpPr/><wpg:grpSpPr/>{pic}{tb}</wpg:wgp></a:graphicData></a:graphic>')
    fb_tb = ''.join(f'<v:shape><v:textbox><w:txbxContent>{x}</w:txbxContent></v:textbox></v:shape>'
                    for x in (inner_label, inner_cap))
    fallback = f'<w:pict><v:group>{fb_tb}</v:group></w:pict>'
    return mf.anchored(graphic, fallback, pid, cx, cy, **pos)


def img(b, name, label, size=(300, 200)):
    return b.add_image(name, mf.png_bytes(label, size=size))


def P(*parts, style="body"):
    return mf.para(S[style] if style in S else style, *parts)


# ----------------------------------------------------------------------------- 架空の文字
# 囲み（200〜400 文字）。どれも架空の問題文。
BOX1 = [
    "問題Ｋ　ある架空の島には，灯台が五つ並んでいる。となり合う灯台の間の距離は，北から順に三百二十メートル，"
    "四百八十メートル，二百六十メートル，五百十メートルである。島の観光係は，灯台のどれか一つに案内所を置き，"
    "すべての灯台から案内所までの距離の合計をできるだけ小さくしたいと考えている。",
    "（１）案内所を北から二つ目の灯台に置いたときの，距離の合計を求めなさい。",
    "（２）距離の合計が最も小さくなる灯台はどれか。そう考えた理由を，数直線を使って説明しなさい。",
    "手がかり　案内所を一つ南の灯台へ動かすと，北側にある灯台の数と南側にある灯台の数によって，合計がどう変わるかを調べるとよい。",
]
BOX2 = [
    "課題Ｍ　架空の文具店では，鉛筆を三本ずつの袋と五本ずつの袋に分けて売っている。店主は，ちょうど何本の鉛筆なら"
    "袋を組み合わせて用意できるかを表にまとめることにした。一本から二十本までのそれぞれについて，用意できるかどうかを"
    "調べ，用意できない本数をすべて書き出しなさい。",
    "さらに，八本以上ならどの本数でも用意できることを，一本ずつ増やすときの袋の入れ替え方に注目して説明しなさい。"
    "説明の中では，三本の袋を五本の袋に取り替えると二本増えることを使ってよい。",
    "補足　袋の種類を四本と七本に変えたとき，用意できない最も大きい本数がいくつになるかも，同じ方法で予想してみよう。",
]
BOX3 = [
    "演習Ｒ　架空の学級で，一週間の通学時間を記録した。月曜日から金曜日までの平均は十八分で，月曜日だけが二十六分，"
    "ほかの四日はすべて同じ時間であった。ほかの四日の通学時間はそれぞれ何分か。式を一つ立てて求めなさい。",
    "次に，土曜日の補習に出かけた日の通学時間を加えると，六日間の平均がちょうど十九分になった。土曜日の通学時間を"
    "求め，平均が一分増えた理由を，合計の増え方から説明しなさい。答えだけでなく，途中の考えも書くこと。",
    "注意　平均を求めるときは，合計を日数でわることを確かめてから計算を始めよう。",
]
LONG_VML = [
    "練習Ｔ　架空の水そうに，毎分四リットルの割合で水を入れる。はじめに十二リットルの水が入っていたとき，"
    "水を入れ始めてから x 分後の水の量を y リットルとして，x と y の関係を式に表しなさい。また，水そうが"
    "六十リットルでいっぱいになるのは，水を入れ始めてから何分後かを求めなさい。",
    "続けて，途中で毎分二リットルの割合で水を抜き始めたとする。水を抜き始めた時刻によって，いっぱいになるまでの"
    "時間がどう変わるかを表とグラフで調べ，気づいたことを文章にまとめなさい。グラフには，水を抜き始めた時刻を"
    "はっきり書き入れること。",
]
FORMULA_BOX_TEXT = ("例題Ｑ　架空の長方形の花だんで，縦の長さを a メートル，横の長さを b メートルとする。"
                    "花だんの周りに幅一メートルの通路を作るとき，通路の面積は次の式で表される。")
FORMULA_BOX_TEXT2 = ("この式を使って，縦が六メートル，横が九メートルのときの通路の面積を求め，通路の面積が花だんの"
                     "周の長さとどのような関係にあるかを調べなさい。通路の幅を二メートルにしたときに，同じ関係が"
                     "成り立つかどうかも，式を変形して確かめなさい。")
HINT = "（ヒント）"
LABEL_A = "Ａ点"
LABEL_GROUP = "Ｐ点"


def box_paras(texts, style="body"):
    return "".join(P(t, style=style) for t in texts)


def chars(texts):
    return sum(len(t) for t in texts)


# ----------------------------------------------------------------------------- 原稿
def article(name, title, body, refs=None, appendix=None):
    """body(b) → 本文の段落の一覧（章見出しから）。refs(b) → 引用文献 1 件の後ろの段落。"""
    path = OUT / f"{name}.docx"
    b = mf.Builder()        # make_article と同じ形。資料の部品も同じ Builder で作る（画像を同じ docx に入れるため）
    parts = []
    parts += mf.front_ja(b, title, "―検証用の小さな論文―", [("架空大学", "試験\u3000六郎")])
    parts += body(b)
    parts.append(mf.para(S["ref_head"], "引用および参考文献"))
    parts.append(mf.para(S["ref"], "試験六郎（2024）．「小さな論文」．『架空誌』，第5巻，pp.9-10．"))
    if refs is not None:
        parts += refs(b)
    parts += mf.front_en(b, "A Small Article", "For Checking", [("Rokuro SHIKEN", "Fictional University")],
                         ["Small article abstract."])
    parts += mf.tail(b, appendix=appendix(b) if appendix is not None else None)
    b.save(path, parts)
    return path


CASES = []


def case(cid, title, docx_body, checks, mode="none", resp=None, refs=None, appendix=None, note=""):
    CASES.append({"id": cid, "title": title, "mode": mode, "resp": resp, "checks": checks, "note": note,
                  "_build": (docx_body, refs, appendix)})


def E(check, level="exact", **kw):
    return dict(check=check, level=level, **kw)


def head(t="１．はじめに"):
    return P(t, style="sec1")


# --- B01 幅の広い囲み（図の左上がアンカー段落の左上） → アンカー段落の前の boxed-text
def b01(b):
    return [head(), P("試験（2024）にならい，囲みの問題を扱う。"),
            P("この段落に問題Ｋの囲みが結び付いている。", mf.textbox(box_paras(BOX1), 1101, cx=int(8.6 * CM), cy=9 * CM,
                                                           wrap="wrapTopAndBottom")),
            P("以上が問題Ｋである。"), head("２．おわりに"), P("囲みの文字も本文に出す。")]


case("B01_box_at_anchor", f"幅の広い囲み（{chars(BOX1)} 文字。左上がアンカー段落の左上）", b01, [
    E("box", text="問題Ｋ　ある架空の島", where="before", ref="この段落に問題Ｋの囲み"),
    E("box_contains_all", text="問題Ｋ　ある架空の島", parts=[t[:12] for t in BOX1]),
    E("notice", present=False, keys=["問題Ｋ"],
      why="機械的に位置が決まる囲み。決められないもの・位置を推定したものだけが要確認（F の節）"),
])


# --- B02 段落の末尾の inline の囲み → アンカー段落の後
def b02(b):
    return [head(), P("試験（2024）にならい，囲みの課題を扱う。"),
            P("次の課題Ｍを考える。", inline_textbox(box_paras(BOX2), 1201, cx=int(8.6 * CM), cy=int(7 * CM))),
            P("以上が課題Ｍである。"), head("２．おわりに"), P("行内の囲みも本文に出す。")]


case("B02_box_inline_end", f"段落の末尾の inline の囲み（{chars(BOX2)} 文字）", b02, [
    E("box", text="課題Ｍ　架空の文具店", where="after", ref="次の課題Ｍを考える。"),
    E("box_contains_all", text="課題Ｍ　架空の文具店", parts=[t[:12] for t in BOX2]),
    E("notice", level="either", keys=["課題Ｍ"], alts=[True, False], why="行内なので位置は決まる。知らせるかは実装しだい"),
])


# --- B03 画像の段落・図キャプションの次の段落に付けた、v が負の小さな注記「Ａ点」（全角空白だけの段落つき）
def b03(b):
    r = img(b, "b03.png", "Map")
    return [head(), P("試験（2024）にならい，地図を使う。"),
            P(mf.drawing(r, 1800000, 1200000, 1301)), P("図1　架空の地図", style="fig_cap"),
            P("この段落に注記が結び付いている。", mf.textbox(P(LABEL_A) + P("　"), 1302, cx=int(0.9 * CM), cy=int(0.5 * CM),
                                                      h=("column", 2 * CM), v=("paragraph", -3 * CM))),
            P("図1のＡ点に注目する。"), head("２．おわりに"), P("注記は本文に入れない。")]


case("B03_label_near_image", "画像の近くの v が負の小さな注記（Ａ点。全角空白の段落つき）", b03, [
    E("not_in_body_p", text=LABEL_A, exact_text=True, why="注記は本文に混ぜない（決定事項 9 の推奨の理由）"),
    E("no_box", text=LABEL_A),
    E("excluded", text=LABEL_A, reason_has="注記", why="付録 D1 (b): 理由が「図に重ねた注記」"),
    E("fig", caption="図1　架空の地図", graphic=True, where="body"),
    E("notice", level="either", keys=["Ａ点", "注記"], alts=[True, False], why="(b) は「警告が出る」。要確認の Action かは書かれていない"),
])


# --- B04 幅が広く短い「（ヒント）」（決められない）。AI なし → 除外して要確認（止めない）
def b04(b):
    return [head(), P("試験（2024）にならい，ヒントの札を使う。"),
            P("この段落にヒントの札が結び付いている。", mf.textbox(P(HINT) + P("　"), 1401, cx=int(8.6 * CM), cy=int(0.8 * CM),
                                                          v=("paragraph", int(1.5 * CM)), wrap="wrapTopAndBottom")),
            P("札の後の本文である。"), head("２．おわりに"), P("決められない囲みは知らせる。")]


case("B04_hint_undecided", "幅が広く短い「（ヒント）」（決められない。全角空白の段落つき）", b04, [
    E("no_raise", why="決定事項 9(2): 除外して要確認にする（AI を必須にしない）"),
    E("no_box", text=HINT),
    E("excluded", text=HINT),
    E("notice", present=True, keys=["ヒント"], why="付録 D1 (d): 冒頭とチェックリストに要確認"),
])


# --- B05 VML だけの囲み（position:absolute） → アンカー段落の後、要確認
def b05(b):
    return [head(), P("試験（2024）にならい，練習Ｔを扱う。"),
            P("この段落に練習Ｔの囲みが結び付いている。", vml_textbox(box_paras(LONG_VML), 1501, width="240pt", height="200pt")),
            P("以上が練習Ｔである。"), head("２．おわりに"), P("VML の囲みも本文に出す。")]


case("B05_vml_abs_box", f"VML だけの囲み（position:absolute。{chars(LONG_VML)} 文字）", b05, [
    E("box", text="練習Ｔ　架空の水そう", where="after", ref="この段落に練習Ｔの囲み", why="付録 D1 (e)"),
    E("notice", present=True, keys=["練習Ｔ"], why="付録 D1 (e): 3 章に要確認（位置を推定）"),
])


# --- B06 VML の幅が cm（pt 以外）の短い「（ヒント）」 → label に倒れない
def b06(b):
    return [head(), P("試験（2024）にならい，VML の札を使う。"),
            P("この段落に VML の札が結び付いている。", vml_textbox(P(HINT), 1601, width="14cm", height="1cm")),
            P("札の後の本文である。"), head("２．おわりに"), P("幅を読めない札も知らせる。")]


case("B06_vml_cm_width_short", "VML の width が cm の短い「（ヒント）」（幅を読めない）", b06, [
    E("excluded_reason_not", text=HINT, reason_not="注記", why="付録 D1: VML の width が pt 以外のとき、label に倒れない"),
    E("box_or_excluded", level="either", text=HINT, alts=["box", "excluded"],
      why="幅の条件を使わないので、文字数などで囲みか決められないかのどちらか"),
    E("notice", present=True, keys=["ヒント"], why="囲みなら位置を推定（position:absolute）、決められないなら要確認。どちらでも知らせる"),
])


# --- B07 VML の幅が % の長い囲み
def b07(b):
    return [head(), P("試験（2024）にならい，演習Ｒを扱う。"),
            P("この段落に演習Ｒの囲みが結び付いている。", vml_textbox(box_paras(BOX3), 1701, width="60%", height="180pt")),
            P("以上が演習Ｒである。"), head("２．おわりに"), P("幅を読めない囲みも本文に出す。")]


case("B07_vml_pct_width_long", f"VML の width が % の長い囲み（{chars(BOX3)} 文字）", b07, [
    E("box_or_excluded", level="either", text="演習Ｒ　架空の学級", alts=["box", "excluded"],
      why="幅を読めないので幅の条件を使わない。文字数だけで囲みにするか、決められないにするかはしきい値しだい"),
    E("excluded_reason_not", text="演習Ｒ　架空の学級", reason_not="注記", why="幅を読めないことで label に倒れない"),
    E("notice", present=True, keys=["演習Ｒ"], why="どちらでも位置の推定か決められないかで要確認"),
])


# --- B08 画像と図キャプションを含むテキストボックス（今の扱い）
def b08(b):
    r = img(b, "b08.png", "Graph")
    return [head(), P("試験（2024）にならい，グラフを示す。"),
            P("この段落に図1のテキストボックスが結び付いている。", mf.textbox(
                P(mf.drawing(r, 1800000, 1080000, 1802)) + P("図1　架空のグラフ", style="fig_cap"), 1801,
                cx=8 * CM, cy=4 * CM, wrap="wrapTopAndBottom")),
            P("以上が図1である。"), head("２．おわりに"), P("図のテキストボックスは今までどおり。")]


case("B08_caption_textbox_image", "画像と図キャプションを含むテキストボックス（今の扱いのまま）", b08, [
    E("fig", caption="図1　架空のグラフ", graphic=True, where="body", before="この段落に図1のテキストボックス"),
    E("no_box_any"),
])


# --- B09 図キャプションだけのテキストボックス（本文の画像の下）
def b09(b):
    r = img(b, "b09.png", "Chart")
    return [head(), P("試験（2024）にならい，棒グラフを示す。"),
            P(mf.drawing(r, 1800000, 1080000, 1901)),
            P("この段落にキャプションのテキストボックスが結び付いている。", mf.textbox(
                P("図1　架空の棒グラフ", style="fig_cap"), 1902, cx=8 * CM, cy=int(0.7 * CM), wrap="wrapTopAndBottom")),
            P("以上が図1である。"), head("２．おわりに"), P("キャプションの図形は今までどおり。")]


case("B09_caption_only_textbox", "図キャプションだけのテキストボックス（今の扱いのまま）", b09, [
    E("fig", caption="図1　架空の棒グラフ", where="body"),
    E("no_box_any"),
    E("same_as_base", why="F の前と同じ扱い（付録 D1 (f)）。base の結果を基準にする"),
])


# --- B10 空白だけのテキストボックス
def b10(b):
    return [head(), P("試験（2024）にならい，空の囲みを置く。"),
            P("この段落に空の囲みが結び付いている。", mf.textbox(P("　") + P("") + P("  "), 2001, cx=int(8.6 * CM), cy=3 * CM,
                                                         v=("paragraph", 2 * CM), wrap="wrapTopAndBottom")),
            P("空の囲みの後の本文である。"), head("２．おわりに"), P("空の囲みは何も出さない。")]


case("B10_blank_textbox", "空白だけのテキストボックス", b10, [
    E("no_box_any", why="(5) 中身が空白だけのテキストボックスは囲みにも要確認にもしない"),
    E("notice", present=False, keys=["空の囲み", "テキストボックス", "囲み"], why="(5)"),
    E("blank_excluded_only", why="(5) 空白だけの段落は exclude_blank（理由「空白のみの段落」）"),
])


# --- B11 囲みの中の別行数式「(1)」と本文の「式(1)」
def b11(b):
    formula = mf.para(S["body"], mf.omathpara(mf.mr("S=2") + mf.mr("(a+b)") + mf.mr("+4")), mf.tab(), "(1)", jc="center")
    inner = P(FORMULA_BOX_TEXT) + formula + P(FORMULA_BOX_TEXT2)
    return [head(), P("試験（2024）にならい，例題Ｑを扱う。"),
            P("この段落に例題Ｑの囲みが結び付いている。", mf.textbox(inner, 2101, cx=int(8.6 * CM), cy=8 * CM,
                                                           wrap="wrapTopAndBottom")),
            P("式(1)より，通路の面積は周の長さに四を足したものである。"), head("２．おわりに"), P("囲みの数式にも番号を付ける。")]


case("B11_box_formula", "囲みの中の別行数式「(1)」と本文の「式(1)」", b11, [
    E("box", text="例題Ｑ　架空の長方形", where="before", ref="この段落に例題Ｑの囲み"),
    E("formula_in_box", fid="FD1", label=True, why="付録 D1 点検: disp-formula に id FD1 と label"),
    E("xref", text="式(1)", rid="FD1", why="本文の「式(1)」がリンクになる"),
])


# --- B12 囲みの中に全角空白だけの段落
def b12(b):
    inner = P(BOX3[0]) + P("　") + P(BOX3[1]) + P("　　") + P(BOX3[2])
    return [head(), P("試験（2024）にならい，演習Ｒを扱う。"),
            P("この段落に演習Ｒの囲みが結び付いている。", mf.textbox(inner, 2201, cx=int(8.6 * CM), cy=9 * CM,
                                                           wrap="wrapTopAndBottom")),
            P("以上が演習Ｒである。"), head("２．おわりに"), P("全角空白の段落も扱える。")]


case("B12_box_blank_para", "囲みの中に全角空白だけの段落", b12, [
    E("box", text="演習Ｒ　架空の学級", where="before", ref="この段落に演習Ｒの囲み"),
    E("box_contains_all", text="演習Ｒ　架空の学級", parts=[t[:12] for t in BOX3]),
])


# --- B13 入れ子のテキストボックス（外側が囲み、内側に短い文字）
def b13(b):
    inner_tb = mf.textbox(P("内側の札：答えは一つとは限らない。"), 2302, cx=4 * CM, cy=int(0.8 * CM), v=("paragraph", 0))
    outer = P(BOX2[0]) + P(BOX2[1], inner_tb) + P(BOX2[2])
    return [head(), P("試験（2024）にならい，課題Ｍを扱う。"),
            P("この段落に入れ子の囲みが結び付いている。", mf.textbox(outer, 2301, cx=int(8.6 * CM), cy=9 * CM,
                                                           wrap="wrapTopAndBottom")),
            P("以上が課題Ｍである。"), head("２．おわりに"), P("入れ子の内側は外側の囲みに入る。")]


case("B13_nested_textbox", "入れ子のテキストボックス（内側は外側の囲みを継ぐ）", b13, [
    E("box", text="課題Ｍ　架空の文具店", where="before", ref="この段落に入れ子の囲み"),
    E("same_box", text="課題Ｍ　架空の文具店", other="内側の札：答えは", why="入れ子の内側は外側の textbox_id を継ぐ"),
])


# --- B14 グループ図形の中の注記（範囲外。今の扱い）
def b14(b):
    r = img(b, "b14.png", "Figure", size=(400, 260))
    return [head(), P("試験（2024）にならい，グループ図形を使う。"),
            P("この段落にグループ図形が結び付いている。", group_with_label(
                r, P("図1　架空のグループ図形", style="fig_cap"), P(LABEL_GROUP), 2401, cx=8 * CM, cy=5 * CM,
                wrap="wrapTopAndBottom")),
            P("以上が図1である。"), head("２．おわりに"), P("グループ図形の注記は今までどおり。")]


case("B14_group_label", "グループ図形の中の注記「Ｐ点」（範囲外。手動モードで回答前）", b14, [
    E("no_box_any", why="(9) グループ図形の中の注記は今の扱い（図の後に p）のまま"),
    E("same_as_base", why="(9) F の前と同じ扱い"),
], mode="manual", note="AI なしでは、グループ図形の中身（キャプション・注記・画像）の組み合わせを決められず、今も止まる")


# --- B17 行内のグループ図形（画像なし。図形とテキストボックスの注記だけ。td3 の形）
def inline_group_labels(labels, pid, cx=int(6.7 * CM), cy=int(3.2 * CM)):
    tbs = "".join(f'<wps:wsp><wps:spPr><a:xfrm><a:off x="{k * 400000}" y="0"/><a:ext cx="300000" cy="200000"/></a:xfrm></wps:spPr>'
                  f'<wps:txbx><w:txbxContent>{P(t)}</w:txbxContent></wps:txbx><wps:bodyPr/></wps:wsp>'
                  for k, t in enumerate(labels))
    shape = '<wps:wsp><wps:spPr><a:prstGeom prst="ellipse"><a:avLst/></a:prstGeom></wps:spPr><wps:bodyPr/></wps:wsp>'
    graphic = ('<a:graphic><a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup">'
               f'<wpg:wgp><wpg:cNvGrpSpPr/><wpg:grpSpPr/>{shape}{tbs}</wpg:wgp></a:graphicData></a:graphic>')
    fb = "".join(f'<v:shape><v:textbox><w:txbxContent>{P(t)}</w:txbxContent></v:textbox></v:shape>' for t in labels)
    return ('<w:r><mc:AlternateContent><mc:Choice Requires="wpg"><w:drawing>'
            f'<wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/>'
            f'<wp:docPr id="{pid}" name="グループ化 {pid}"/>{graphic}</wp:inline></w:drawing></mc:Choice>'
            f'<mc:Fallback><w:pict><v:group>{fb}</v:group></w:pict></mc:Fallback></mc:AlternateContent></w:r>')


def b17(b):
    return [head(), P("試験（2024）にならい，図形で描いた図を示す。"),
            P(inline_group_labels(["Ｑ点", "Ｒ", "\u3000", "ｘ軸"], 2601)),
            P("図1\u3000架空の図形で描いた図", style="fig_cap"),
            P("以上が図1である。"), head("２．おわりに"), P("行内のグループ図形の注記は今までどおり。")]


case("B17_inline_group_labels", "行内のグループ図形（画像なし）の中の短い注記（td3 の形。範囲外）", b17, [
    E("no_box_any", why="(9) グループ図形の中の注記は範囲外"),
    E("same_as_base", why="(9) F の前と同じ扱い"),
])


# --- B15 囲みの中に「英文要旨」スタイルの段落と「注」だけの段落
def b15(b):
    inner = P(BOX1[0]) + P("Area of the island", style="abs") + P("注") + P(BOX1[1])
    return [head(), P("試験（2024）にならい，問題Ｋを扱う。"),
            P("この段落に問題Ｋの囲みが結び付いている。", mf.textbox(inner, 2501, cx=int(8.6 * CM), cy=9 * CM,
                                                           wrap="wrapTopAndBottom")),
            P("1) 番号で始まる本文の段落である。"), head("２．おわりに"), P("囲みの段落で構造は変わらない。")]


case("B15_box_region_styles", "囲みの中の「英文要旨」スタイルの段落と「注」だけの段落", b15, [
    E("box", text="問題Ｋ　ある架空の島", where="before", ref="この段落に問題Ｋの囲み"),
    E("counts", sec=2, trans_abstract_p=1, fn_group=False, why="付録 D1 点検: sec の数、trans-abstract の段落数、fn-group の有無が変わらない"),
])


# --- B18 本文の冒頭（最初の章見出しの前）の囲み → boxed-text を p で包む（DTD に合う）
def b18(b):
    return [P("この段落に本文の冒頭の囲みが結び付いている。", mf.textbox(box_paras(BOX2), 2701, cx=int(8.6 * CM), cy=9 * CM,
                                                             wrap="wrapTopAndBottom")),
            head(), P("試験（2024）にならい，冒頭の囲みを扱う。"), head("２．おわりに"), P("冒頭の囲みも本文に出す。")]


case("B18_box_body_start", "本文の冒頭（最初の章見出しの前）の囲み", b18, [
    E("box", text="課題Ｍ　架空の文具店", where="before", ref="この段落に本文の冒頭の囲み"),
    E("box_parent", text="課題Ｍ　架空の文具店", parent="p", why="本文の冒頭では <p> で包む（DTD は全体の dtd_valid で見る）",
      level="either", alts=["p", "sec", "body"]),
])


# --- B16 決められないもの（全角空白つき）、手動モードで回答前
case("B16_undecided_manual_noresp", "決められない「（ヒント）」、手動モードで回答を貼る前", b04, [
    E("no_box", text=HINT),
    E("excluded", text=HINT),
    E("notice", present=True, keys=["ヒント"]),
    E("prompt", must=['box', 'label', HINT], why="(8) FIELD_GUIDE と manual_prompt に box・label。決められない囲みを依頼文に載せる"),
], mode="manual")


# --- A01〜A03 AI の placements（kind box / label）
def a0x(b):
    return [head(), P("試験（2024）にならい，ヒントの札と問題Ｋを扱う。"),
            P("この段落にヒントの札が結び付いている。", mf.textbox(P(HINT), 3001, cx=int(8.6 * CM), cy=int(0.8 * CM),
                                                          v=("paragraph", int(1.5 * CM)), wrap="wrapTopAndBottom")),
            P("札を置くべき位置はこの段落の後である。"),
            P("この段落に問題Ｋの囲みが結び付いている。", mf.textbox(box_paras(BOX1), 3002, cx=int(8.6 * CM), cy=9 * CM,
                                                           wrap="wrapTopAndBottom")),
            P("以上が問題Ｋである。"), head("２．おわりに"), P("AI の指定で囲みを置く。")]


case("A01_ai_box", "決められない「（ヒント）」に kind box を指定", a0x, [
    E("box", text=HINT, where="after", ref="札を置くべき位置はこの段落の後", why="指定の段落の後の boxed-text"),
    E("ai_accepted", op="place_float", src_of=HINT, why="ai.accepted に place_float として載る"),
    E("notice", present=False, keys=["ヒント"], why="AI が位置を指定したので要確認は残らない（はず）", level="either", alts=[False, True]),
], mode="manual", resp={"placements": [{"float_of": HINT, "after_of": "札を置くべき位置はこの段落の後", "kind": "box"}]})

case("A02_ai_label", "決められない「（ヒント）」に kind label を指定", a0x, [
    E("no_box", text=HINT),
    E("excluded", text=HINT),
    E("ai_accepted", op="place_float", src_of=HINT),
], mode="manual", resp={"placements": [{"float_of": HINT, "after_of": "この段落にヒントの札", "kind": "label"}]})

case("A03_ai_after_in_shape", "kind box の after に図形（囲み）の中の段落を指定 → 不採用", a0x, [
    E("ai_rejected", src_of=HINT, why="after が図形の中の段落は不採用"),
    E("no_box", text=HINT),
    E("excluded", text=HINT),
    E("notice", present=True, keys=["ヒント"], why="指定なしに戻るので要確認が残る"),
], mode="manual", resp={"placements": [{"float_of": HINT, "after_of": "（１）案内所を北から", "kind": "box"}]})


# --- A04・A05 VML のキャプションへの set_role
def a04(b):
    r = img(b, "a04.png", "Figure")
    return [head(), P("試験（2024）にならい，図を示す。"),
            P(mf.drawing(r, 1800000, 1080000, 3101)),
            P(vml_textbox(P("図1　架空の図形の説明である。"), 3102, absolute=False, width="200pt", height="20pt")),
            P("以上が図1である。"), head("２．おわりに"), P("VML のキャプションも扱える。")]


case("A04_vml_caption_set_role_fig_caption", "VML の「図1　…。」に set_role fig_caption → 採用", a04, [
    E("ai_accepted", op="set_role", src_of="図1　架空の図形の説明"),
    E("fig", caption="図1　架空の図形の説明", graphic=True, where="body", fid="F1"),
], mode="manual", resp={"set_role": [{"src_of": "図1　架空の図形の説明", "role": "fig_caption"}]})

case("A05_vml_caption_set_role_p", "同じ段落に set_role p → placements を案内して拒否", a04, [
    E("ai_rejected", src_of="図1　架空の図形の説明", reason_has="placements"),
], mode="manual", resp={"set_role": [{"src_of": "図1　架空の図形の説明", "role": "p"}]})

case("A06_textbox_set_role_p", "文字だけのテキストボックスの段落に set_role p → 拒否", a0x, [
    E("ai_rejected", src_of=HINT, reason_has="placements", why="(1) float_id のない段落では fig_caption・table_caption・exclude だけ"),
    E("no_box", text=HINT),
], mode="manual", resp={"set_role": [{"src_of": HINT, "role": "p"}]})

case("A07_textbox_set_role_exclude", "文字だけのテキストボックスの段落に set_role exclude → 採用", a0x, [
    E("ai_accepted", op="set_role", src_of=HINT, why="(1) exclude は受け付ける"),
    E("excluded", text=HINT),
    E("no_box", text=HINT),
], mode="manual", resp={"set_role": [{"src_of": HINT, "role": "exclude"}]})


# --- N01〜N03 引用文献の段落に結び付いた、画像とキャプションを含む図形
def n_body(b):
    return [head(), P("試験（2024）にならい，最後の図を示す。"), P("図を置くべき位置はこの段落の後である。"),
            head("２．おわりに"), P("本文の外に結び付いた図も本文に置く。")]


def n_refs_fig(b):
    r = img(b, "n_refs.png", "Last figure")
    return [P("試験次郎（2023）．「最後の図」．『架空誌』，第4巻，pp.7-8．", mf.textbox(
        P(mf.drawing(r, 1440000, 960000, 4002)) + P("　") + P("図1　引用文献に結び付いた図", style="fig_cap"), 4001,
        cx=8 * CM, cy=4 * CM, v=("paragraph", 2 * CM), wrap="wrapTopAndBottom"), style="ref")]


case("N01_refs_fig_none", "引用文献の段落に結び付いた画像とキャプション（AI なし）", n_body, [
    E("raises_ai_required", why="決定事項 10: AI を使わない設定では止める"),
], refs=n_refs_fig)

case("N02_refs_fig_manual", "引用文献の段落に結び付いた画像とキャプション（手動モード、回答前）", n_body, [
    E("fig", caption="図1　引用文献に結び付いた図", graphic=True, where="body", body_end=True,
      why="決定事項 21: アンカー段落が本文でなければ本文の最後に仮に置く"),
    E("not_in_tags", text="図1　引用文献に結び付いた図", tags=["ref-list", "mixed-citation", "back"]),
    E("lost_none"),
    E("needs_action", value=True, why="位置を決められない図表の仮置きは要対応"),
], mode="manual", refs=n_refs_fig)

case("N03_refs_fig_ai_place", "引用文献の段落に結び付いた図形に placements で位置を指定", n_body, [
    E("fig", caption="図1　引用文献に結び付いた図", graphic=True, where="body", after="図を置くべき位置はこの段落の後"),
    E("ai_accepted", op="place_float", src_of="図1　引用文献に結び付いた図"),
    E("lost_none"),
], mode="manual", resp={"placements": [{"float_of": "図1　引用文献に結び付いた図", "after_of": "図を置くべき位置はこの段落の後",
                                        "kind": "fig", "caption_of": "図1　引用文献に結び付いた図", "body_image": True}]}, refs=n_refs_fig)


# --- N04 注の段落に結び付いた文字だけの図形
def n_notes_text(b):
    return [P("注", style="fn_head"), P("1) 架空の注の本文である。", mf.textbox(
        box_paras(BOX3), 4101, cx=int(8.6 * CM), cy=8 * CM, v=("paragraph", CM), wrap="wrapTopAndBottom"))]


case("N04_notes_text_shape", "注の段落に結び付いた文字だけの図形", n_body, [
    E("not_in_tags", text="演習Ｒ　架空の学級", tags=["fn", "fn-group", "ref-list"], why="N7: その領域の段落として扱わない"),
    E("box_or_excluded", level="either", text="演習Ｒ　架空の学級", alts=["box", "excluded"],
      why="D1 の place_boxes で判定。置き場所が本文でないので決められないとして除外もありうる"),
    E("notice", present=True, keys=["演習Ｒ"], why="本文の外に結び付いた囲みは位置を決められない（要確認）"),
], refs=n_notes_text)


# --- N05 引用文献の段落に結び付いた文字だけの図形
def n_refs_text(b):
    return [P("試験三郎（2022）．「囲みの文献」．『架空誌』，第3巻，pp.5-6．", mf.textbox(
        box_paras(LONG_VML), 4201, cx=int(8.6 * CM), cy=8 * CM, v=("paragraph", CM), wrap="wrapTopAndBottom"), style="ref")]


case("N05_refs_text_shape", "引用文献の段落に結び付いた文字だけの図形", n_body, [
    E("not_in_tags", text="練習Ｔ　架空の水そう", tags=["mixed-citation", "ref-list", "ref"]),
    E("box_or_excluded", level="either", text="練習Ｔ　架空の水そう", alts=["box", "excluded"]),
    E("notice", present=True, keys=["練習Ｔ"]),
], refs=n_refs_text)


# --- N06 資料の中の図形（今の扱い: 資料の中に出す）
def n_app(b):
    r = img(b, "n_app.png", "Worksheet")
    return [P("資料（授業プリント）", style="abs"),
            P("この段落に資料の図が結び付いている。", mf.textbox(
                P(mf.drawing(r, 1440000, 960000, 4302)) + P("図2　資料の図", style="fig_cap"), 4301,
                cx=8 * CM, cy=4 * CM, wrap="wrapTopAndBottom"), style="abs"),
            P("資料の最後の段落である。", style="abs")]


case("N06_app_fig", "資料（app）の中の図形（今の扱いのまま）", n_body, [
    E("fig_graphic_in", where="app", why="資料の中の図形は資料の中に出す"),
    E("in_region", text="図2\u3000資料の図", region="app"),
    E("same_as_base", why="今の扱いを保つ"),
], appendix=n_app)


# --- N07 引用文献の段落そのものにある画像（lost_images のまま）
def n_refs_img(b):
    r = img(b, "n_refimg.png", "Logo", size=(120, 60))
    return [P("試験四郎（2021）．「画像のある文献」．『架空誌』，第2巻，pp.1-2．", mf.drawing(r, 600000, 300000, 4401), style="ref")]


case("N07_refs_inline_image", "引用文献の段落そのものにある画像", n_body, [
    E("lost_has", why="A の N1 で要対応として知らせ続ける"),
    E("needs_action", value=True),
], refs=n_refs_img)


# ----------------------------------------------------------------------------- 書き出し
def main():
    OUT.mkdir(exist_ok=True)
    out = []
    for c in CASES:
        body, refs, appendix = c.pop("_build")
        article(c["id"], f"{c['id']} の検証用文書", body, refs=refs, appendix=appendix)
        out.append(c)
    (HERE / "cases.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(len(out), "cases written to", OUT)


if __name__ == "__main__":
    main()
