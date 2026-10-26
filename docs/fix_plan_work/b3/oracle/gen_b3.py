"""B3（N15〜N19）の反例: 架空の文字の docx・模擬の AI 回答・期待を作る（実装を見ずに FIX_PLAN の B3 と決定事項 21・22 から）。

  python gen_b3.py [リポジトリ]      # 既定 /home/user/jstgxmlcng_JASME

cases/<ID>/doc.docx と cases/<ID>/case.json、cases.json（一覧）を作る。docx は tests/make_fixtures.py の部品で作る
（make_fixtures.py 自体は変えない）。回答の段落 ID は、run_b3.py が依頼文（AI依頼文.txt）から読み替える
（"@p:<段落の冒頭>" は段落 ID、"@img:<図形 ID>" はその図形の中の画像だけの段落 ID）。
"""
import json
import shutil
import sys

sys.dont_write_bytecode = True
from pathlib import Path

REPO = Path(sys.argv[1] if len(sys.argv) > 1 else "/home/user/jstgxmlcng_JASME")
sys.path.insert(0, str(REPO / "tests"))
from make_fixtures import (
    Builder,
    S,
    cell,
    drawing,
    front_en,
    front_ja,
    group,
    para,
    png_bytes,
    table,
    tail,
    textbox,
)

HERE = Path(__file__).resolve().parent
CASES = HERE / "cases"
CM = 360000

# ----------------------------------------------------------------------------- 架空の文字
SEC1 = "１．架空の観測の背景"
SEC2 = "２．架空の考察"
P_A = "架空の観測では，雲の形を三種類に分けて記録した。"
P_B = "この段落に観測図の図形が結び付いている。図は段落から下に離れて置かれている。"
P_C = "観測の記録は，朝と夕方の二回に分けて整理した。"
P_D = "図1に示したように，雲の形は時刻によって変わる。"
P_E = "以上の観測から，記録の方法を見直す必要がある。"
P_F = "今後は，記録用紙の書式をそろえて観測を続ける。"
N_1 = "1) この観測は架空の学校で行ったものとする。"
N_2 = "2) 記録用紙は架空の様式である。"
REF = "試験九郎（2023）．「架空の観測記録」．『架空誌』，第7巻，pp.13-14．"
CAP1 = "図1　雲の形の分類"
CAP2 = "図2　観測の時刻と雲"


class Doc:
    """1 件の原稿。parts は (種類, 中身) の一覧で、anchor_runs は {段落の記号: [図形の XML]}。"""

    def __init__(self):
        self.b = Builder()
        self.pid = 400

    def next_pid(self, n=3):
        self.pid += n
        return self.pid

    def img(self, name, label, size=(300, 200)):
        return self.b.add_image(name, png_bytes(label, size=size))

    def img_para(self, rid, style="body"):
        return para(S[style], drawing(rid, 1800000, 1200000, self.next_pid()))

    def tb_fig(self, rid, cap, down_cm, extra=""):
        """画像の段落とキャプションの段落のテキストボックス。down_cm だけアンカー段落から下にずらす（0 なら機械的に決まる）。"""
        inner = self.img_para(rid) + para(S["fig_cap"], cap) + extra
        return textbox(inner, self.next_pid(), cx=8 * CM, cy=5 * CM, v=("paragraph", int(down_cm * CM)),
                       wrap="wrapTopAndBottom")

    def tb(self, inner, down_cm, cx=16, cy=7):
        return textbox(inner, self.next_pid(), cx=cx * CM, cy=cy * CM, v=("paragraph", int(down_cm * CM)),
                       wrap="wrapTopAndBottom")

    def save(self, path, sections, notes=True, front_runs=None, last_front_runs=None, note_runs=None, ref_runs=None):
        b = self.b
        body = front_ja(b, "架空の雲の観測に関する検証用文書", "―図表の置き場所の確かめ―", [("架空大学", "試験　九郎")])
        if front_runs:      # 副題の段落に図形を結び付ける
            _append_runs(b, body[3], front_runs)
        if last_front_runs:  # 和文の冒頭の最後の段落（セクション区切り）に図形を結び付ける
            _append_runs(b, body[-1], last_front_runs)
        for heading, paras in sections:
            body.append(para(S["sec1"], heading))
            body += paras
        if notes:
            body.append(para(S["fn_head"], "注"))
            body.append(para(S["body"], N_1, *(note_runs or [])))
            body.append(para(S["body"], N_2))
        body.append(para(S["ref_head"], "引用および参考文献"))
        body.append(para(S["ref"], REF, *(ref_runs or [])))
        body += front_en(b, "Observing Fictional Clouds", "Where to Put Figures",
                         [("Kuro SHIKEN", "Fictional University")], ["Fictional cloud abstract."])
        body += tail(b)
        b.save(path, body)


def _append_runs(b, el, runs):
    for xml in runs:
        p = b.frag(f"<w:p>{xml}</w:p>")[0]
        for r in list(p):
            el.append(r)


def body_paras(*texts, runs=None):
    runs = runs or {}
    return [para(S["body"], t, *runs.get(t, [])) for t in texts]


def std_sections(runs=None, extra1=None):
    """位置の反例の本文: 1 章に A〜D、2 章に E・F。runs は {段落の文字: [図形の XML]}。"""
    s1 = body_paras(P_A, P_B, P_C, P_D, runs=runs)
    if extra1:
        s1 += extra1
    return [(SEC1, s1), (SEC2, body_paras(P_E, P_F, runs=runs))]


# ----------------------------------------------------------------------------- 模擬の AI 回答
def placement(fid, after, cap_prefix, reason="図の上端はアンカー段落から離れている。推定では直上の本文はこの段落", conf="中"):
    return {"float": fid, "after": after, "items": [{"kind": "fig", "caption": [f"@p:{cap_prefix}"], "body": [f"@img:{fid}"]}],
            "reason": reason, "confidence": conf}


def response(placements, order=("placements", "operations", "notes"), ops=None, notes=None):
    d = {"placements": placements, "operations": ops or [], "notes": notes or []}
    return {k: d[k] for k in order}


LINK_OP = {"op": "link_figure", "src": f"@p:{P_D[:12]}", "text": "図1", "occurrence": 1, "target": "F1", "role": "",
           "image": "", "mathml": "", "surname": "", "given": "",
           "reason": "本文の「図1」は観測図のキャプション「図1　雲の形の分類」を指す。前後の文脈からも観測図と判断できる",
           "confidence": "高"}

# ----------------------------------------------------------------------------- 期待の部品
NO_TOP = {"t": "no_words", "where": ["stdout", "sec1", "sec3", "sec14", "note"], "words": ["本文の冒頭"],
          "why": "N17: 置いた位置に合わせて「本文の冒頭に仮に置いた」の文言を直す（CLI・レポートの冒頭・3 章・14 章・手動モードの案内）"}


def notice(present=True, words_any=None, why=""):
    c = {"t": "notice_float", "present": present, "why": why}
    if words_any:
        c["words_any"] = words_any
    return c


END_WORDS = ["最後", "末尾", "終わり"]


def exit_in(*codes, why=""):
    return {"t": "exit", "in": list(codes), "why": why}


def after(anchor, items, why=""):
    return {"t": "seq_after", "anchor": anchor[:10], "items": items, "why": why}


def before(anchor, items, why=""):
    return {"t": "seq_before", "anchor": anchor[:10], "items": items, "why": why}


def last(items, why=""):
    return {"t": "seq_last", "items": items, "why": why}


def first(items, why=""):
    return {"t": "seq_first", "items": items, "why": why}


def fig(cap, graphic=None, table=None, why=""):
    c = {"t": "fig", "cap": cap, "why": why}
    if graphic is not None:
        c["graphic"] = graphic
    if table is not None:
        c["table"] = table
    return c


def anyof(*alts, why=""):
    return {"t": "any", "alts": [list(a) for a in alts], "why": why}


# ----------------------------------------------------------------------------- ケース
CASE_LIST = []


def case(cid, title, build, ai, expect, resp=None, cut=None, grade="exact", note=""):
    CASE_LIST.append(dict(id=cid, title=title, build=build, ai=ai, expect=expect, response=resp, cut=cut,
                          grade=grade, note=note))


def build_pos(path):
    d = Doc()
    r = d.img("pos_1.png", "Cloud types")
    d.save(path, std_sections({P_B: [d.tb_fig(r, CAP1, 2.5)]}))


def build_pos2(path):
    d = Doc()
    r1, r2 = d.img("pos2_1.png", "Cloud types"), d.img("pos2_2.png", "Time and cloud")
    d.save(path, std_sections({P_B: [d.tb_fig(r1, CAP1, 2.5)], P_E: [d.tb_fig(r2, CAP2, 3.0)]}))


def build_note(path):
    d = Doc()
    r = d.img("note_1.png", "Cloud types")
    d.save(path, std_sections(), note_runs=[d.tb_fig(r, CAP1, 2.5)])


def build_ref(path):
    d = Doc()
    r = d.img("ref_1.png", "Cloud types")
    d.save(path, std_sections(), ref_runs=[d.tb_fig(r, CAP1, 2.5)])


def build_front_sub(path):
    d = Doc()
    r = d.img("front_1.png", "Cloud types")
    d.save(path, std_sections(), front_runs=[d.tb_fig(r, CAP1, 2.5)])


def build_front_last(path):
    d = Doc()
    r = d.img("frontl_1.png", "Cloud types")
    d.save(path, std_sections(), last_front_runs=[d.tb_fig(r, CAP1, 2.5)])


def build_same(path, reverse=False):
    d = Doc()
    r1, r2 = d.img("same_1.png", "Cloud types"), d.img("same_2.png", "Time and cloud")
    t1, t2 = d.tb_fig(r1, CAP1, 2.5), d.tb_fig(r2, CAP2, 6.0)
    d.save(path, std_sections({P_B: [t2, t1] if reverse else [t1, t2]}))


def build_group(path):
    d = Doc()
    r = d.img("grp_1.png", "Cloud page", size=(480, 240))
    g = group(r, 6 * CM, 3 * CM, para(S["fig_cap"], CAP1), d.next_pid(), cx=16 * CM, cy=5 * CM, v=("page", 10 * CM),
              wrap="wrapTopAndBottom")
    d.next_pid()
    d.save(path, std_sections({P_B: [g]}))


# --- N18: 表のセルに画像とキャプションが並ぶ図形
TB_ANCHOR = "この段落に雲の写真の図形が結び付いている。図形の中の表に写真と説明を並べた。"
TB_SEC = "１．架空の写真の整理"
TB_PRE = "雲の写真を二枚選び，形の違いを比べた。"
TB_POST = "写真の撮影時刻は，すべて架空のものである。"
PCAP1 = "図1　積雲の架空の写真"
PCAP2 = "図2　層雲の架空の写真"


def _cells_doc(path, rows_fn, down_cm=0):
    d = Doc()
    r1, r2 = d.img(f"{Path(path).parent.name}_1.png", "Cumulus"), d.img(f"{Path(path).parent.name}_2.png", "Stratus")
    rows = rows_fn(d, r1, r2)
    tb = d.tb(table(rows), down_cm)
    secs = [(TB_SEC, [para(S["body"], TB_PRE), para(S["body"], TB_ANCHOR, tb), para(S["body"], TB_POST)]),
            (SEC2, body_paras(P_E, P_F))]
    d.save(path, secs)


def build_cell1(path):
    _cells_doc(path, lambda d, r1, r2: [[cell([d.img_para(r1), para(S["fig_cap"], PCAP1)])]])


def build_cell2h(path):
    _cells_doc(path, lambda d, r1, r2: [[cell([d.img_para(r1), para(S["fig_cap"], PCAP1)]),
                                         cell([d.img_para(r2), para(S["fig_cap"], PCAP2)])]])


def build_cellrows(path, down_cm=0):
    _cells_doc(path, lambda d, r1, r2: [[cell(d.img_para(r1)), cell(d.img_para(r2))],
                                        [cell(para(S["fig_cap"], PCAP1)), cell(para(S["fig_cap"], PCAP2))]], down_cm)


def build_cellmixed(path):
    _cells_doc(path, lambda d, r1, r2: [[cell(d.img_para(r1)), cell(d.img_para(r2))],
                                        [cell(para(S["fig_cap"], PCAP1)),
                                         cell(para(S["tab_cap"], "表1　層雲の架空の観測回数"))]])


def build_celltext(path):
    _cells_doc(path, lambda d, r1, r2: [[cell(d.img_para(r1)), cell(d.img_para(r2))],
                                        [cell(para(S["fig_cap"], PCAP1)),
                                         cell(para(S["body"], "右の写真は夕方に撮った架空のものである。"))]])


# --- N19: 画像のない図キャプションと直前の表（本文の流れ）
TS = "１．架空の記録表"
T_PRE = "観測した雲の高さを，次のような表にまとめた。"
T_POST = "記録表の数値は，すべて架空の値である。"
T_MID = "この表は，午前の観測だけをまとめたものである。"
TCAP = "図1　雲の高さの記録表"
TCAP2 = "図2　雲の厚さの記録表"


def data_table(kind="高さ"):
    return table([[cell("雲の種類"), cell(f"{kind}（架空）")], [cell("積雲"), cell("12")], [cell("層雲"), cell("5")]])


def _tbl_doc(path, middle, extra_img=False):
    d = Doc()
    if extra_img:
        r = d.img("imgafter_1.png", "Cloud chart")
        middle = [x if x != "IMG" else d.img_para(r) for x in middle]
    secs = [(TS, [para(S["body"], T_PRE)] + middle + [para(S["body"], T_POST)]), (SEC2, body_paras(P_E, P_F))]
    d.save(path, secs)


def build_tblcap(path):
    _tbl_doc(path, [data_table(), para(S["fig_cap"], TCAP)])


def build_capabove(path):
    _tbl_doc(path, [para(S["fig_cap"], TCAP), data_table()])


def build_between(path):
    _tbl_doc(path, [data_table(), para(S["body"], T_MID), para(S["fig_cap"], TCAP)])


def build_tabcap(path):
    _tbl_doc(path, [para(S["tab_cap"], "表1　雲の高さの集計"), data_table(), para(S["fig_cap"], TCAP)])


def build_imgafter(path):
    _tbl_doc(path, [data_table(), "IMG", para(S["fig_cap"], TCAP)], extra_img=True)


def build_control(path):
    """要対応が出ないはずの対照: 表キャプションの付いた表と、画像の付いた図キャプション。"""
    d = Doc()
    r = d.img("control_1.png", "Cloud chart")
    secs = [(TS, [para(S["body"], T_PRE), para(S["tab_cap"], "表1　雲の高さの集計"), data_table(),
                  d.img_para(r),
                  para(S["fig_cap"], TCAP), para(S["body"], T_POST)]),
            (SEC2, body_paras(P_E, P_F))]
    d.save(path, secs)


def build_tbfloat(path):
    """表と画像のない図キャプションのテキストボックス（図の左上がアンカー段落の左上。機械的に決まる）。"""
    d = Doc()
    tb = d.tb(data_table() + para(S["fig_cap"], TCAP), 0)
    secs = [(TS, [para(S["body"], T_PRE), para(S["body"], TB_ANCHOR, tb), para(S["body"], T_POST)]),
            (SEC2, body_paras(P_E, P_F))]
    d.save(path, secs)


# ----------------------------------------------------------------------------- ケースの一覧
F1, F2 = "fig:図1", "fig:図2"
S_B, S_D, S_E, S_F = P_B[:12], P_D[:12], P_E[:12], P_F[:12]

# N16・N17: 位置を決められない図表の置き場所
case("P01", "本文の段落に結び付いた図形・手動モードで回答を貼る前", build_pos, "manual",
     [after(P_B, [F1], "N17: 手動モードで回答を貼り戻す前の出力も、アンカー段落のすぐ後ろ"), NO_TOP,
      notice(False, why="回答を反映する前は「手作業で直す」の要対応ではない（今までどおり）"), exit_in(0)])
case("P02", "本文の段落に結び付いた図形・位置を答えない回答（placements が空）", build_pos, "manual",
     [after(P_B, [F1], "N17: AI でも決められない図表はアンカー段落のすぐ後ろ"), NO_TOP,
      notice(True, why="N17: 要対応として知らせる"), exit_in(1)],
     resp=response([]))
case("P03", "本文の段落に結び付いた図形・本文の段落を正しく答える回答", build_pos, "manual",
     [after(P_D, [F1], "答えた段落の直後"), fig("図1", graphic=True), notice(False), exit_in(0)],
     resp=response([placement("s1", f"@p:{S_D}", CAP1[:3])]))
case("P04", "本文の段落に結び付いた図形・注の段落の後ろと答える回答", build_pos, "manual",
     [last([F1], "N16: 本文の外の段落の後ろと答えた図表は本文の最後"), NO_TOP,
      notice(True, END_WORDS, "N16: 要対応として知らせる。文言は置いた位置（本文の最後）に合わせる"), exit_in(1)],
     resp=response([placement("s1", f"@p:{N_1[:10]}", CAP1[:3], reason="図の直上は注の 1 番目の段落")]))
case("P05", "本文の段落に結び付いた図形・引用文献の段落の後ろと答える回答", build_pos, "manual",
     [last([F1], "N16: 本文の最後"), NO_TOP, notice(True, END_WORDS, "N16"), exit_in(1)],
     resp=response([placement("s1", f"@p:{REF[:10]}", CAP1[:3], reason="図の直上は引用文献の段落")]))
case("P06", "注の段落に結び付いた図形・手動モードで回答を貼る前", build_note, "manual",
     [last([F1], "決定事項 21: アンカー段落が本文でなければ本文の最後"), NO_TOP, exit_in(0)])
case("P07", "注の段落に結び付いた図形・位置を答えない回答", build_note, "manual",
     [last([F1], "決定事項 21: 本文の最後"), NO_TOP, notice(True, END_WORDS, "N17: 要対応。文言は本文の最後"), exit_in(1)],
     resp=response([]))
case("P08", "引用文献の段落に結び付いた図形・位置を答えない回答", build_ref, "manual",
     [last([F1], "決定事項 21: 本文の最後"), NO_TOP, notice(True, END_WORDS, "N17"), exit_in(1)],
     resp=response([]))
case("P09", "和文の冒頭（副題）の段落に結び付いた図形・位置を答えない回答", build_front_sub, "manual",
     [last([F1], "決定事項 21: アンカー段落が本文でなければ本文の最後"), fig("図1", graphic=True), NO_TOP,
      notice(True, END_WORDS, "N17"), exit_in(1)],
     resp=response([]),
     note="和文の冒頭の段落の中身の領域（6.1）は冒頭になる。図が XML に入ること（画像を失わない）も確かめる")
case("P10", "和文の冒頭の最後の段落（セクション区切り）に結び付いた図形・位置を答えない回答", build_front_last, "manual",
     [anyof([first([F1])], [last([F1])], why="6.1 では中身は本文に入るので、本文の最初（アンカー段落の直後に当たる）か、"
            "アンカー段落が本文でないとして本文の最後か、どちらか"), fig("図1", graphic=True), NO_TOP, exit_in(0, 1)],
     resp=response([]), grade="either")
case("P11", "同じ段落に 2 つの図形（docx の順も番号順）・位置を答えない回答", build_same, "manual",
     [after(P_B, [F1, F2], "N17: アンカー段落のすぐ後ろに番号順"), NO_TOP, notice(True), exit_in(1)],
     resp=response([]))
case("P12", "同じ段落に 2 つの図形（docx では図2 の図形が先）・位置を答えない回答",
     lambda p: build_same(p, reverse=True), "manual",
     [anyof([after(P_B, ["fig:図1", "fig:図2"])], [after(P_B, ["fig:図2", "fig:図1"])],
            why="番号順か docx の順か、FIX_PLAN からは決められない（どちらもアンカー段落のすぐ後ろ）"),
      NO_TOP, notice(True), exit_in(1)],
     resp=response([]), grade="either")
case("P13", "途中で切れた回答: placements が先頭、閉じた要素 1 つ（s1）と切れた要素（s2）", build_pos2, "manual",
     [{"t": "hint", "why": "N15: 途中で切れている可能性の案内"},
      anyof([after(P_D, [F1])], [after(P_B, [F1])], why="閉じた s1 を読み取れれば答えた段落 D の後、読み取らなければアンカー段落の後"),
      after(P_E, [F2], "切れた s2 はアンカー段落 E のすぐ後ろ（N17）"), NO_TOP],
     resp=response([placement("s1", f"@p:{S_D}", CAP1[:3]), placement("s2", f"@p:{S_F}", CAP2[:3])]),
     cut={"after": '"float": "s2", "after": "@p:' + S_F + '", "items": [{"kind": "fig", "caption": ['},
     grade="either")
case("P14", "途中で切れた回答: placements が末尾（operations・notes の後）で、s1 の途中で切れた", build_pos2, "manual",
     [{"t": "hint", "why": "N15"}, after(P_B, [F1], "N17"), after(P_E, [F2], "N17"), NO_TOP],
     resp=response([placement("s1", f"@p:{S_D}", CAP1[:3]), placement("s2", f"@p:{S_F}", CAP2[:3])],
                   order=("operations", "notes", "placements"), ops=[LINK_OP],
                   notes=["本文の「図1」と図形の中のキャプションの番号は合っている"]),
     cut={"after": '"placements": [{"float": "s1", "after": "@p:' + S_D + '"'})
case("P15", "途中で切れた回答: s1 の reason の文字列の途中で切れた（Unterminated string）", build_pos2, "manual",
     [{"t": "hint", "why": "N15: Unterminated string のときも案内を出す"}, after(P_B, [F1], "N17"), after(P_E, [F2], "N17"),
      NO_TOP],
     resp=response([placement("s1", f"@p:{S_D}", CAP1[:3]), placement("s2", f"@p:{S_F}", CAP2[:3])]),
     cut={"after": '"reason": "図の上端はアンカー段落から'})
case("P16", "途中で切れた回答: placements は先頭で閉じ、後ろの operations の文字列の途中で切れた", build_pos2, "manual",
     [{"t": "hint", "why": "N15"},
      anyof([after(P_D, [F1]), after(P_F, [F2])], [after(P_B, [F1]), after(P_E, [F2])],
            why="閉じた placements を読み取れば答えた位置、読み取らなければアンカー段落の後（どちらか）"), NO_TOP],
     resp=response([placement("s1", f"@p:{S_D}", CAP1[:3]), placement("s2", f"@p:{S_F}", CAP2[:3])], ops=[LINK_OP]),
     cut={"after": '"reason": "本文の「図1」は観測図の'}, grade="either")
case("P17", "グループ図形（縦の位置がページ基準）・位置を答えない回答", build_group, "manual",
     [after(P_B, [F1], "N17: アンカー段落のすぐ後ろ"), fig("図1", graphic=True), NO_TOP, notice(True), exit_in(1)],
     resp=response([]))

# N18: 表のセルに画像とキャプションが並ぶ図形（図の左上はアンカー段落の左上なので、位置は機械的に決まる）
T_OK = [{"t": "no_top_tw", "why": "表の枠は図に組んだので、表として残さない"}]
case("T01", "1 つのセルに画像とキャプション（AI なし）", build_cell1, "none",
     [exit_in(0, why="N18: AI なしでも図に組む（止まらない）"), before(TB_ANCHOR, [F1], "at_anchor: アンカー段落の前"),
      fig("図1", graphic=True, table=False), *T_OK])
case("T02", "2 つのセルが横に並び、それぞれに画像とキャプション（AI なし）", build_cell2h, "none",
     [exit_in(0, why="N18"), before(TB_ANCHOR, [F1, F2], "アンカー段落の前に図1・図2"),
      fig("図1", graphic=True, table=False), fig("図2", graphic=True, table=False), *T_OK])
case("T03", "画像のセルの行とキャプションのセルの行が別（2 列。AI なし）", build_cellrows, "none",
     [exit_in(0, why="N18: 列ごとに組む"), before(TB_ANCHOR, [F1, F2]),
      fig("図1", graphic=True, table=False), fig("図2", graphic=True, table=False), *T_OK])
case("T04", "画像の行とキャプションの行（2 列）で、表キャプションが混ざる（AI なし）", build_cellmixed, "none",
     [anyof([exit_in(2, why="組み方が一つに決まらないので AI に任せる（AI なしでは止まる）")],
            [exit_in(0), {"t": "top_tw", "cap": "-"}, {"t": "no_fig_cap", "prefix": "表"}],
            [exit_in(0, 1), fig("図1", graphic=True), {"t": "no_fig_cap", "prefix": "表"},
             notice(True, why="組み切れなかったものを知らせる")],
            why="一つに決まらないときは機械的に組まない（AI に任せるか、今までどおり表のまま）。"
                "決まる部分だけ組むなら、残りを要対応として知らせる。表キャプションを図のキャプションにはしない"),
      ], grade="either",
     note="図の左上がアンカー段落の左上にあるので、0.21.0 では AI に送らず表のまま出す（今までどおりの範囲）")
case("T05", "画像の行とキャプションの行（2 列）で、キャプションのないセルの文字がある（AI なし）", build_celltext, "none",
     [anyof([exit_in(2, why="AI に任せる（AI なしでは止まる）")],
            [exit_in(0), {"t": "top_tw", "cap": "-", "why": "今までどおり表のまま"}],
            why="組めない（画像 2 つにキャプション 1 つと文字）ので機械的には組まない")], grade="either")
case("T06", "画像の行とキャプションの行（2 列）・アンカー段落から離れている・手動モードで回答を貼る前",
     lambda p: build_cellrows(p, down_cm=2.5), "manual",
     [anyof([after(TB_ANCHOR, [F1, F2]), fig("図1", graphic=True, table=False)],
            [after(TB_ANCHOR, ["tw:-"])],
            why="位置は AI が決める。組み方を機械的に済ませれば図1・図2、済ませなければ表のまま。どちらもアンカー段落の後ろ"),
      NO_TOP, exit_in(0)], grade="either")

# N19: 画像のない図キャプションの直前にある、キャプションのない表
case("U00", "対照: 表キャプションの付いた表と、画像の付いた図（AI なし）", build_control, "none",
     [exit_in(0), after(T_PRE, ["tw:表1", F1, "p:" + T_POST[:10]]), fig("図1", graphic=True, table=False),
      {"t": "notice_any", "present": False, "why": "要対応は出ない"}])
case("U01", "表の直後に画像のない図キャプション（AI なし）", build_tblcap, "none",
     [exit_in(0), after(T_PRE, [F1, "p:" + T_POST[:10]], "N19: 表を図の本体にする"),
      fig("図1", graphic=False, table=True, why="決定事項 22: fig の中の table-wrap"),
      {"t": "no_top_tw", "why": "表を表として残さない"}, {"t": "notice_any", "present": False}])
case("U02", "画像のない図キャプションの直後に表（キャプションが表の上。AI なし）", build_capabove, "none",
     [anyof([fig("図1", table=True), {"t": "no_top_tw"}],
            [fig("図1", table=False), {"t": "notice_any", "present": True}],
            why="N19 は「直前の表」。上のキャプションで組むか、組まずに要対応として知らせるか")], grade="either")
case("U03", "表と画像のない図キャプションの間に本文の段落（AI なし）", build_between, "none",
     [fig("図1", table=False, why="組めない"), {"t": "top_tw", "cap": "-", "why": "表は表のまま"},
      {"t": "notice_any", "present": True, "why": "N19: 組めないときは要対応として知らせる"}])
case("U04", "表キャプションの付いた表の直後に画像のない図キャプション（AI なし）", build_tabcap, "none",
     [fig("図1", table=False, why="組めない（表にほかのキャプション）"), {"t": "top_tw", "cap": "表1"},
      {"t": "notice_any", "present": True, "why": "N19: 要対応として知らせる"}])
case("U05", "表・画像の段落・図キャプションの順（AI なし）", build_imgafter, "none",
     [exit_in(0), fig("図1", graphic=True, table=False, why="キャプションには画像があるので、N19 は当てはまらない"),
      {"t": "top_tw", "cap": "-", "why": "表は表のまま"}])
case("U06", "テキストボックスの中の表と画像のない図キャプション（機械的に決まる位置。AI なし）", build_tbfloat, "none",
     [exit_in(0), before(TB_ANCHOR, [F1]), fig("図1", graphic=False, table=True), {"t": "no_top_tw"}])


def main():
    if CASES.exists():
        shutil.rmtree(CASES)
    CASES.mkdir()
    index = []
    for c in CASE_LIST:
        d = CASES / c["id"]
        d.mkdir()
        c["build"](d / "doc.docx")
        meta = {k: v for k, v in c.items() if k != "build"}
        (d / "case.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        index.append({"id": c["id"], "title": c["title"], "grade": c["grade"]})
    (HERE / "cases.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    print(len(index), "件:", " ".join(i["id"] for i in index))


if __name__ == "__main__":
    main()
