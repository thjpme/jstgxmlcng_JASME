"""反例集（観点: layout = PDF の配置と読み順）。文字はすべて架空。

確かめること（1 つの反例で 1 つ）:
  - 段落がページの区切り（ページ番号の行）で分かれる位置: 最初の行の後・最後の行の前（途中は cases_seed.py の
    seed_pagebreak_mid）。区切りのすぐ近くに直す違い（全角・半角）を 1 つ置き、ページ番号を足さずに直せるかを見る
  - 段落の途中（段の区切り）に入る文字の種類と長さ: 表（キャプション＋数字のセル）10・60・200・500 文字、
    表（語句のセル）12 文字、図の中の文字 200 文字、図のキャプションだけ、別の段落（読み順のずれ）約 200 文字
  - 同じ表（60 文字）の区切りに、直す違いがかかるもの
  - 段落の後ろ・前が分断されるもの（N10）: 最後の行の前に表 300 文字・別の段落、最初の行の後に別の段落
  - 短い段落（表のキャプション・見出し）のすぐ隣に表のセルの文字があるもの
  - 長い段落（約 900 文字。ページをまたぐ）の終わり近くの違い
  - 引用文献の行分け: 「pp.11-」の後の「16」がページの最初（ページ番号の次）の行になるもの、URL の途中の改行で
    数字だけの行（「2019」）になるもの
  - 英文要旨の行末のハイフン（PDFium は、行末のハイフンを U+FFFE にして 2 行を 1 行につなげて取り出す。
    tests/private/pdf の 5 本で、組版のハイフン（argu|ments など）も、複合語の本物のハイフン（self|explanation など）も、
    この形で出ることを確かめた）

PDF の形は tests/private/pdf の 5 本で確かめたもの（2 段組み・1 行およそ 24 文字・段落の最初の行は全角の空白で
始まる・行頭の句読点は前の行にぶら下げる・ページ番号は各ページの最初の行の「（25）」・表のセルは 1 セル 1 行か、
1 行に空白区切りで並ぶ・英文要旨は 1 段で 1 行およそ 100 文字）。受付日・柱は入れない（観点 artifact が確かめる）。

期待（truth・expect）は原則だけで決めた。docx と PDF の本文が同じ段落は truth を書かない（変わってはいけない）。
"""
from __future__ import annotations

import random
import unicodedata

from runner import BREAK, DEFAULTS, Raw, flow, journal_line  # noqa: F401

# ============================================================================ この観点の補助
KINSOKU = "，。、．）」』！？"     # 行頭に来ない文字（前の行にぶら下げる）


def _w(c: str) -> float:
    return 1.0 if unicodedata.east_asian_width(c) in ("F", "W", "A") else 0.5


def jwrap(text: str, width: float = 24) -> list:
    """和文の行分け（runner.wrap と同じ数え方に、行頭の句読点のぶら下げを加えたもの）。"""
    lines, cur, n = [], "", 0.0
    for c in text:
        if cur and n + _w(c) > width and c not in KINSOKU:
            lines.append(cur)
            cur, n = "", 0.0
        cur += c
        n += _w(c)
    if cur:
        lines.append(cur)
    return lines


def body(text: str) -> list:
    """本文の段落の PDF の行（最初の行は全角の空白で字下げする）。"""
    return jwrap("　" + text)


def ewrap(text: str, n: int = 100) -> list:
    """英文の行分け（単語の境目で、1 行 n 文字まで）。"""
    lines, cur = [], ""
    for word in text.split(" "):
        if cur and len(cur) + 1 + len(word) > n:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}" if cur else word
    if cur:
        lines.append(cur)
    return lines


def num_cells(total: int, cols: int = 5, seed: int = 1):
    """数字のセルの表。人数（整数）と平均・標準偏差（小数）を混ぜ、セルの文字数の合計がおよそ total になるまで
    行（cols 個のセル）を足す。戻り値: (docx の表の行, PDF の行（1 セル 1 行）, セルの文字数の合計)。"""
    rnd = random.Random(seed)
    rows, n = [], 0
    while n < total:
        row = []
        for k in range(cols):
            if k in (0, cols - 1):
                s = str(rnd.randint(1, 40))
            else:
                s = f"{rnd.randint(0, 4)}.{rnd.randint(10, 99)}"
            row.append(s)
            n += len(s)
        rows.append(row)
    return rows, [c for r in rows for c in r], n


def chars(lines) -> int:
    """空白を除いた文字数。"""
    return sum(1 for ln in lines for c in ln if not c.isspace())


def front(fp: int = 25) -> Raw:
    """1 ページ目の冒頭（ページ番号の後ろ）: 誌名の行・題目・副題・所属・著者名。"""
    return Raw(journal_line(fp=fp, lp=fp + 11), DEFAULTS["題目"], DEFAULTS["副題"], "架空大学", "試験　五郎")


def en_block(*abstract_lines) -> Raw:
    """最後のページの英文の部分（題目・副題・著者・所属・Abstract・要旨）。docx の既定の英文と同じ文字。"""
    return Raw(DEFAULTS["英文題目"], DEFAULTS["英文副題"], "Goro SHIKEN", "Fictional University", "Abstract",
               *abstract_lines)


# ============================================================================ 架空の論文の段落
H1 = "１．はじめに"
H2 = "２．研究の方法"
H3 = "３．結果と考察"
H4 = "４．おわりに"
RH = "引用および参考文献"

P_INTRO = ("本研究の目的は，架空の中学校で行った比例の授業において，生徒が二つの量の関係をどのように捉えたかを，"
           "ノートの記述と授業中の発話から明らかにすることである。これまでの架空の研究では，比例の式を立てる"
           "手続きに重点が置かれ，生徒が関係そのものをどう見ているかは十分に調べられてこなかった。")
P_METHOD = ("調査は，架空の市立中学校の第１学年の二つの学級で行った。授業は各学級で５時間ずつ行い，すべての時間を"
            "録画した。生徒のノートは授業の終わりに回収し，写しを取ってから返した。分析では，発話と記述を時間の"
            "順に並べ，量の関係についての言及を取り出して分類した。")
P_METHOD_DOCX = P_METHOD.replace("第１学年", "第1学年")          # docx は半角（A1 の直す違い）
P_FRAME = ("分類の観点として，架空の先行研究が示した三つの見方を用いた。一つ目は値を一つずつ見る見方，二つ目は"
           "変化の様子を見る見方，三つ目は対応の規則を見る見方である。本研究では，これらの見方のどれが，どの課題の"
           "場面で現れたのかに注目した。")
P_COMPARE = ("二つの学級の記述を比べると，矢印を用いた学級では，変化の様子に触れる記述が早い時期から見られた。"
             "もう一方の学級では，表の値を読み取る記述が長く続き，変化に触れる記述が初めて現れたのは第４時であった。")
P_COMPARE_DOCX = P_COMPARE.replace("第４時", "第4時")             # docx は半角（A2 の直す違い）
P_RESULT = ("第一時と第二時では，表の値を一つずつ読み取る記述が多く見られた。第三時に，伴って変わる二つの量の変化を"
            "矢印で表す活動を取り入れたところ，変化の様子に触れる記述が増えた。第四時以降は，一方が２倍，３倍に"
            "なると他方も同じように変わることを言葉で説明する生徒が現れ，対応の規則に注目する見方が学級の中に"
            "広がっていった。")
P_RESULT_DOCX = P_RESULT.replace("２倍，３倍", "2倍，3倍")        # docx は半角（B9 の直す違い）
P_DISC = ("このような変容が起きた理由として，矢印で表す活動によって，表の横の関係に生徒の目が向いたことが考えられる。"
          "ただし，対応の規則を言葉で述べられても，それを式に表すことに困難を感じる生徒も多かった。言葉による説明と"
          "式による表現を結び付ける手立てについては，さらに検討する必要がある。")
P_LATER = ("また，授業の後に行った質問紙調査では，表に矢印をかき込む活動が考えるのに役立ったと答えた生徒が，二つの"
           "学級を合わせて八割を超えた。自由記述には，矢印をかくと増え方が見えるようになった，横に見るだけでなく"
           "縦に見てもよいことに気付いた，といった内容が多く見られた。こうした記述からは，生徒が活動の意味を"
           "自分なりに捉え，表の見方を広げていたことがうかがえる。")
P_END = ("本研究では，比例の授業における生徒の見方の変容を，記述と発話の分析によって明らかにした。今後は，ほかの"
         "学年や単元でも同じような変容が見られるかを確かめるとともに，教師の発問が見方の変容に果たす役割を"
         "詳しく調べていきたい。")
P_LONG = ("第三時の授業の展開を詳しく見ると，次のような流れがあった。授業の始めに，教師は前時に扱った表を黒板に"
          "掲げ，水を入れる時間と水の深さの関係を振り返らせた。続いて，表の横の隣り合う値の間に矢印をかき，深さが"
          "どれだけ増えたかを矢印の上に書き込む活動を示した。生徒は自分のノートの表にも矢印をかき，増え方がいつも"
          "同じであることを確かめていった。その後，教師は時間が１分から３分になったときの深さの変わり方を問い，"
          "生徒どうしで説明し合う時間を取った。ある生徒は，時間が３倍になると深さも３倍になると述べ，別の生徒は，"
          "１分ごとに同じだけ増えるから，と理由を付け加えた。教師はこの二つの説明を並べて板書し，両者の違いと"
          "共通点を学級全体で話し合わせた。話し合いの中で，増え方に注目する説明は表の横の関係を見ており，何倍に"
          "なるかに注目する説明は二つの量の対応を見ていることが確かめられた。さらに教師は，表の数を一つだけ"
          "隠して，隠れた数をどのように求めるかを問うた。多くの生徒は横に矢印をたどって求めたが，縦に見て深さを"
          "時間の何倍かで求める生徒も現れ，その方法の良さが学級で共有された。授業の終わりの振り返りでは，多くの"
          "生徒が矢印をかくとよく分かったと書いていたが，二つの見方の違いに触れた生徒は一部にとどまった。この"
          "ことから，矢印は変化に目を向けさせるのには役立つが，対応の規則に目を向けさせるには，さらに別の手立てが"
          "必要であると考えられる。実際に，次の時間に行った第５時の授業では，表を縦に見る活動を加えたことで，"
          "対応の規則に触れる記述が大きく増えた。")
P_LONG_DOCX = P_LONG.replace("第５時", "第5時")                   # docx は半角（E1 の直す違い）

REF_A = "架空一郎（2019）．「比例の学習における関係の見方」．『架空数学教育研究』，第29号，pp.11-16"
REF_A_LINES = ["架空一郎（2019）．「比例の学習における関係の", "見方」．『架空数学教育研究』，第29号，pp.11-", "16"]
REF_B = "仮名花子・試験次郎（2021）．「表と式を結ぶ授業の工夫」．『架空の算数と数学』，第12巻，第3号，pp.45-58"
REF_URL = ("架空教育研究所（2019）．『比例の授業に関する架空の調査報告』．"
           "https://www.kakuu-kenkyujo.example.jp/houkoku/2019")
REF_URL_LINES = ["架空教育研究所（2019）．『比例の授業に関する", "架空の調査報告』．",
                 "https://www.kakuu-kenkyujo.example.jp/houkoku/", "2019"]
assert "".join(REF_A_LINES) == REF_A and "".join(REF_URL_LINES) == REF_URL

# 表・図
TAB_CAP = "表１　架空の学級別の記述の数"
TAB_CAP_DOCX = "表1　架空の学級別の記述の数"                     # docx は半角（D2 の直す違い）
TAB2_CAP = "表２　架空の観点の一覧"
FIG_CAP = "図１　架空の授業の流れ"
FIG_PHOTO_CAP = "図１　架空の授業の板書"
H3_DOCX = "3．結果と考察"                                         # docx は半角（D1 の直す違い）

# 表のセル
NUM10 = [["27", "3.5"], ["16", "2.8"]]                            # 10 文字（本誌の「27」「16」の形に小数を混ぜた）
NUM60, _, NUM60_N = num_cells(60, seed=60)
NUM200, _, NUM200_N = num_cells(200, seed=200)
NUM300, _, NUM300_N = num_cells(300, seed=300)
NUM500, _, NUM500_N = num_cells(500, seed=500)
WORD12 = [["区分", "職名"], ["初任", "教諭"], ["中堅", "主任"]]        # 12 文字（1 セル 1 行の短い行）
TAB2 = [["観点", "内容"], ["値", "一つずつ見る"], ["変化", "増え方を見る"], ["対応", "規則を見る"]]
TAB_ROWS = [["学級", "第一時", "第二時", "第三時"], ["Ａ組", "12", "9", "4"], ["Ｂ組", "10", "11", "6"]]

# 図の中の文字（docx では画像なので、docx のどの段落にもない）。約 200 文字
FIG_TEXT = ["授業の流れ", "導入（５分）", "前時の表を振り返る", "↓", "課題の提示（５分）", "水を入れる時間と深さの表",
            "↓", "個人で考える（15分）", "表に矢印をかき込む", "増え方を矢印の上に書く", "↓",
            "学級で話し合う（20分）", "増え方に注目する説明", "何倍かに注目する説明", "二つの説明を比べる", "↓",
            "まとめ（５分）", "分かったことをノートに書く", "振り返りを書く", "第三時", "第四時", "第五時",
            "教師の発問", "生徒の説明", "板書", "ノート", "記述の分類", "値・変化・対応", "矢印の活動",
            "縦に見る活動", "対応の規則", "隠れた数を求める"]


def cells_lines(rows) -> list:
    """表のセルを 1 セル 1 行で並べた PDF の行。"""
    return [c for r in rows for c in r]


def rows_lines(rows) -> list:
    """表の行を、セルを空白で区切って 1 行に並べた PDF の行。"""
    return [" ".join(r) for r in rows]


def split_at(lines, k):
    return Raw(*lines[:k]), Raw(*lines[k:])


R_LINES = body(P_RESULT)            # 7 行。最後の行は短い（N10 の形に使う）
MID = 4                             # 段落の途中で分けるときの位置（最初の 4 行の後）


def article(*result, after=None, before_h3=(), refs=(REF_A, REF_B), fp=25, extra_tail=()):
    """PDF の本文の流れ（1 ページ目の冒頭から引用文献まで）。result は見出し H3 の後に入る PDF のブロック、
    after はその後ろ（既定は P_DISC）、before_h3 は H3 の前に入るブロック。"""
    after = [Raw(*body(P_DISC))] if after is None else list(after)
    return [front(fp), H1, Raw(*body(P_INTRO)), H2, Raw(*body(P_METHOD)), Raw(*body(P_FRAME)), *before_h3, H3,
            *result, *after, H4, Raw(*body(P_END)), RH, *refs, *extra_tail]


def docx_paras(*result, after=(("本文", P_DISC),), before_h3=(), refs=(REF_A, REF_B), method=P_METHOD, h3=H3,
               extra=()):
    """docx の段落の並び（役割, 文字）。result は見出し H3 の後に入る段落、after はその後ろ（既定は P_DISC）。"""
    return ([("見出し", H1), ("本文", P_INTRO), ("見出し", H2), ("本文", method), ("本文", P_FRAME), *before_h3,
             ("見出し", h3), *result, *after, ("見出し", H4), ("本文", P_END), ("引用文献見出し", RH)]
            + [("引用文献", r) for r in refs] + list(extra))


def idx(paras, text):
    """paras の中で text の段落の番号（truth のキー）。"""
    found = [i for i, (_, t) in enumerate(paras) if t == text]
    assert len(found) == 1, (text[:20], found)
    return found[0]


# ============================================================================ 反例
CASES = []


def case(name, item, paras, pages, note, truth=None, expect="exact"):
    CASES.append({"name": name, "angle": "layout", "item": item, "paras": paras, "truth": truth or {},
                  "pages": pages, "expect": expect, "note": note})


# ---------------------------------------------------------------- A. ページの区切りの位置（ページ番号の行）
_m = body(P_METHOD)
_paras = docx_paras(("本文", P_RESULT), method=P_METHOD_DOCX)
case("lay_pb_after_first_line", "new", _paras,
     flow([front(), H1, Raw(*body(P_INTRO)), H2, Raw(_m[0]), BREAK, Raw(*_m[1:]), Raw(*body(P_FRAME)), H3,
           Raw(*R_LINES), Raw(*body(P_DISC)), H4, Raw(*body(P_END)), RH, REF_A, REF_B], first=25),
     truth={I_METHOD: P_METHOD},
     note="段落の最初の行の後でページが変わる（次のページの最初の行が「（26）」）。最初の行の終わり（区切りの 6 文字前）"
          "に docx の「第1学年」と PDF の「第１学年」の違いがある。全角にするだけで、ページ番号を足さない。")

_c = body(P_COMPARE)
_paras = docx_paras(("本文", P_RESULT), ("本文", P_COMPARE_DOCX))
case("lay_pb_before_last_line", "new", _paras,
     flow([front(), H1, Raw(*body(P_INTRO)), H2, Raw(*body(P_METHOD)), Raw(*body(P_FRAME)), H3, Raw(*R_LINES),
           Raw(*_c[:-1]), BREAK, Raw(_c[-1]), Raw(*body(P_DISC)), H4, Raw(*body(P_END)), RH, REF_A, REF_B],
          first=25),
     truth={_idx(_paras, P_COMPARE_DOCX): P_COMPARE},
     note="段落の最後の行の前でページが変わり、最後の行だけが次のページ（「（26）」の次の行）にある。その最後の行に"
          "docx の「第4時」と PDF の「第４時」の違いがある。全角にするだけで、ページ番号を足さない。")

# ---------------------------------------------------------------- B. 段落の途中に入る文字（種類と長さ）
_head, _tail = split_at(R_LINES, MID)


def _table_mid(rows, cap=TAB_CAP, lines_of=cells_lines):
    """段落 P_RESULT の途中（4 行目の後）に表（キャプション＋セル）が入る PDF と、表が段落の後ろにある docx。"""
    paras = docx_paras(("本文", P_RESULT), ("表キャプション", cap), ("表", rows))
    pages = flow(article(_head, Raw(cap, *lines_of(rows)), _tail), first=25)
    return paras, pages


_paras, _pages = _table_mid(NUM10)
case("lay_tab_num10_mid", "N9", _paras, _pages,
     note=f"段落の途中（段の区切り）に表のキャプションと数字のセル {chars(cells_lines(NUM10))} 文字（「27」「3.5」「16」"
          "「2.8」の 1 セル 1 行）が入る。docx では表は段落の後ろの Word の表。どの段落も docx と PDF の本文は同じなので、"
          "何も変えない（セルの文字・キャプションを段落に足さない）。")

_paras, _pages = _table_mid(NUM60)
case("lay_tab_num60_mid", "new", _paras, _pages,
     note=f"段落の途中に表のキャプションと数字のセル {NUM60_N} 文字（整数と小数、1 セル 1 行）が入る。何も変えない。")

_paras, _pages = _table_mid(NUM200)
case("lay_tab_num200_mid", "new", _paras, _pages,
     note=f"段落の途中に表のキャプションと数字のセル {NUM200_N} 文字（1 セル 1 行）が入る。何も変えない。")

_paras, _pages = _table_mid(NUM500)
case("lay_tab_num500_mid", "N10", _paras, _pages,
     note=f"段落の途中に長い表（キャプションと数字のセル {NUM500_N} 文字、1 セル 1 行）が入る（段落の 3 倍より長い）。"
          "何も変えない（段落の後ろの 3 行を消したり、セルの文字に置き換えたりしない）。")

_paras = docx_paras(("本文", P_RESULT_DOCX), ("表キャプション", TAB_CAP), ("表", NUM60))
case("lay_tab_num60_probe", "new", _paras,
     flow(article(_head, Raw(TAB_CAP, *cells_lines(NUM60)), _tail), first=25),
     truth={I_RES: P_RESULT},
     note="lay_tab_num60_mid と同じ PDF で、docx の段落だけが「2倍，3倍」（PDF は「２倍，３倍」）。PDF では表が"
          "「一方が２」と「倍，３倍」の間（直す違いのちょうど区切り）に入る。2 文字を全角にするだけで、表の文字を足さない。")

_paras, _pages = _table_mid(WORD12, cap=TAB2_CAP)
case("lay_tab_word12_mid", "new", _paras, _pages,
     note=f"段落の途中に表のキャプションと語句のセル {chars(cells_lines(WORD12))} 文字（「区分」「職名」「初任」…の"
          "1 セル 1 行の短い行）が入る。何も変えない（語句のセルを段落に足さない）。")

_paras = docx_paras(("本文", P_RESULT), ("画像", "授業の流れ"), ("図キャプション", FIG_CAP))
case("lay_fig_text200_mid", "new", _paras,
     flow(article(_head, Raw(*FIG_TEXT, FIG_CAP), _tail), first=25),
     note=f"段落の途中に図の中の文字 {chars(FIG_TEXT)} 文字（流れ図の語句と矢印。docx では画像なので、docx のどの段落にも"
          "ない）と図のキャプションが入る。何も変えない（図の中の文字を段落に足さない）。")

_paras = docx_paras(("本文", P_RESULT), ("画像", "板書の写真"), ("図キャプション", FIG_PHOTO_CAP))
case("lay_fig_caption_mid", "new", _paras,
     flow(article(_head, Raw(FIG_PHOTO_CAP), _tail), first=25),
     note="段落の途中に図のキャプションの行（11 文字）だけが入る（図は写真で文字がない）。docx ではキャプションは段落の"
          "後ろの別の段落。何も変えない（キャプションを段落に足さない。キャプションの段落も変えない）。")

_paras = docx_paras(("本文", P_RESULT), ("本文", P_DISC), ("本文", P_LATER))
_paras = [p for k, p in enumerate(_paras) if not (p == ("本文", P_DISC) and k > I_RES + 1)]   # P_DISC を 1 つにする
case("lay_para200_mid", "new", _paras,
     flow([front(), H1, Raw(*body(P_INTRO)), H2, Raw(*body(P_METHOD)), Raw(*body(P_FRAME)), H3, _head,
           Raw(*body(P_LATER)), _tail, Raw(*body(P_DISC)), H4, Raw(*body(P_END)), RH, REF_A, REF_B], first=25),
     note=f"2 段組みの読み順のずれ: 段落の途中に、docx では 2 つ後ろの段落（{len(P_LATER)} 文字）が丸ごと入る"
          "（ページの中ほどに段をまたぐ図があり、左の段の上・右の段の上・左の段の下の順に取り出される形）。"
          "どちらの段落も何も変えない。")

# ---------------------------------------------------------------- C. 段落の後ろ・前が分断される（N10）
_paras = docx_paras(("本文", P_RESULT), ("表キャプション", TAB_CAP), ("表", NUM300))
case("lay_n10_tail_table300", "N10", _paras,
     flow(article(Raw(*R_LINES[:-1]), Raw(TAB_CAP, *cells_lines(NUM300)), Raw(R_LINES[-1])), first=25),
     note=f"段落の最後の行（「{R_LINES[-1]}」）の前に、表のキャプションと数字のセル {NUM300_N} 文字が入る（表が右の段の"
          "上にあり、段落の最後の行だけが表の下に回った形）。何も変えない（段落の最後の行を消したり、セルの文字に"
          "置き換えたりしない）。")

_paras = [p for p in docx_paras(("本文", P_RESULT), ("本文", P_DISC), ("本文", P_LATER))]
_paras = [p for k, p in enumerate(_paras) if not (p == ("本文", P_DISC) and k > I_RES + 1)]
case("lay_n10_tail_para", "N10", _paras,
     flow([front(), H1, Raw(*body(P_INTRO)), H2, Raw(*body(P_METHOD)), Raw(*body(P_FRAME)), H3,
           Raw(*R_LINES[:-1]), Raw(*body(P_LATER)), Raw(R_LINES[-1]), Raw(*body(P_DISC)), H4, Raw(*body(P_END)),
           RH, REF_A, REF_B], first=25),
     note="読み順のずれで、段落の最後の行（13 文字）の前に、docx では 2 つ後ろの段落が丸ごと入る。どちらの段落も"
          "何も変えない（最後の行を消さない。入ってきた段落の文字を足さない）。")

_paras = [p for p in docx_paras(("本文", P_RESULT), ("本文", P_DISC), ("本文", P_LATER))]
_paras = [p for k, p in enumerate(_paras) if not (p == ("本文", P_DISC) and k > I_RES + 1)]
case("lay_n10_head_para", "N10", _paras,
     flow([front(), H1, Raw(*body(P_INTRO)), H2, Raw(*body(P_METHOD)), Raw(*body(P_FRAME)), H3,
           Raw(R_LINES[0]), Raw(*body(P_LATER)), Raw(*R_LINES[1:]), Raw(*body(P_DISC)), H4, Raw(*body(P_END)),
           RH, REF_A, REF_B], first=25),
     note="読み順のずれで、段落の最初の行（左の段の一番下）の後に、docx では 2 つ後ろの段落が丸ごと入り、その後に"
          "段落の残りが続く。どちらの段落も何も変えない（最初の行を消さない。入ってきた段落の文字を足さない）。")

# ---------------------------------------------------------------- D. 短い段落（キャプション・見出し）のすぐ隣のセル
_paras = docx_paras(("本文", P_RESULT), ("表キャプション", TAB_CAP_DOCX), ("表", TAB_ROWS))
case("lay_short_caption_cells", "new", _paras,
     flow(article(Raw(*R_LINES), Raw(TAB_CAP, *rows_lines(TAB_ROWS))), first=25),
     truth={_idx(_paras, TAB_CAP_DOCX): TAB_CAP},
     note="表のキャプション（14 文字）のすぐ後ろに表のセルの行（「学級 第一時 第二時 第三時」「Ａ組 12 9 4」…。"
          "1 行に空白区切り）が続く。キャプションは docx が「表1」、PDF が「表１」。全角にするだけで、セルの文字を"
          "キャプションに足さない。")

_paras = docx_paras(("表キャプション", TAB2_CAP), ("表", TAB2), ("本文", P_RESULT), h3=H3_DOCX)
# docx では表は見出しの前（P_FRAME の後ろ）に置く: 並べ替える
_paras = [p for p in _paras if p[0] not in ("表キャプション", "表")]
_k = _idx(_paras, H3_DOCX)
_paras = _paras[:_k] + [("表キャプション", TAB2_CAP), ("表", TAB2)] + _paras[_k:]
case("lay_short_heading_after_cells", "new", _paras,
     flow([front(), H1, Raw(*body(P_INTRO)), H2, Raw(*body(P_METHOD)), Raw(*body(P_FRAME)),
           Raw(TAB2_CAP, *cells_lines(TAB2)), H3, Raw(*R_LINES), Raw(*body(P_DISC)), H4, Raw(*body(P_END)), RH,
           REF_A, REF_B], first=25),
     truth={_idx(_paras, H3_DOCX): H3},
     note="見出し（7 文字）のすぐ前に、表のセルの短い行（「観点」「内容」「値」「一つずつ見る」…、1 セル 1 行）がある"
          "（表が左の段の一番下、見出しが右の段の一番上）。見出しは docx が「3．結果と考察」、PDF が「３．結果と考察」。"
          "全角にするだけで、セルの文字を見出しに足さない。")

# ---------------------------------------------------------------- E. 長い段落
_l = body(P_LONG)
_paras = docx_paras(("本文", P_LONG_DOCX), ("本文", P_RESULT))
case("lay_long_para", "new", _paras,
     flow([front(), H1, Raw(*body(P_INTRO)), H2, Raw(*body(P_METHOD)), Raw(*body(P_FRAME)), H3,
           Raw(*_l[:20]), BREAK, Raw(*_l[20:]), Raw(*R_LINES), Raw(*body(P_DISC)), H4, Raw(*body(P_END)), RH,
           REF_A, REF_B], first=25),
     truth={I_RES: P_LONG},
     note=f"長い段落（{len(P_LONG)} 文字、{len(_l)} 行。21 行目からは次のページ）。終わりから 2 行目に docx の「第5時」と"
          "PDF の「第５時」の違いがある。全角にするだけで、ほかは変えない。")

# ---------------------------------------------------------------- F. 引用文献の行分け
_paras = docx_paras(("本文", P_RESULT))
case("lay_ref_pp_digits_pagetop", "N9", _paras,
     flow([front(), H1, Raw(*body(P_INTRO)), H2, Raw(*body(P_METHOD)), Raw(*body(P_FRAME)), H3, Raw(*R_LINES),
           Raw(*body(P_DISC)), H4, Raw(*body(P_END)), RH, Raw(*REF_A_LINES[:2]), BREAK, Raw(REF_A_LINES[2]), REF_B],
          first=25),
     note="引用文献の「…第29号，pp.11-」でページが変わり、次のページの「（26）」の次の行が「16」だけになる。「16」は"
          "引用文献の文字（ページ番号はその前の「（26）」）。引用文献を変えない（「16」を消さない）。")

_paras = docx_paras(("本文", P_RESULT), refs=(REF_A, REF_URL, REF_B))
case("lay_ref_url_digits", "N9", _paras,
     flow(article(Raw(*R_LINES), refs=(REF_A, Raw(*REF_URL_LINES), REF_B)), first=25),
     note="引用文献の URL が「…/houkoku/」の後で改行し、次の行が「2019」だけになる（ページの途中）。URL の一部なので、"
          "引用文献を変えない（「2019」を消さない）。")

# ---------------------------------------------------------------- G. 英文の段落の行末のハイフン
EN1 = ("This study examined how lower secondary school students understood the relationship between two "
       "quantities in fictional lessons on proportion. The notes and utterances of the students in five lessons "
       "were analysed using a framework of three views: looking at single values, looking at changes, and "
       "looking at correspondence rules.")
EN2 = ("The results showed that an activity of drawing arrows on tables helped the students to attend to changes, "
       "and that problem-solving discussions in the whole class supported the shift towards the view of "
       "correspondence rules. Implications for designing lessons that connect verbal explanations with algebraic "
       "expressions are discussed.")


def _soft(lines, word, at):
    """lines の中の word を word[:at] と word[at:] に分け、その間で行が変わる形にしてから、PDFium と同じく
    U+FFFE を挟んで 2 行を 1 行につなげる（組版のハイフンも、複合語の本物のハイフンも、この形で取り出される）。
    word に「-」があれば、それを U+FFFE に置き換える（本物のハイフンで行が変わった形）。"""
    text = "\n".join(lines)
    k = text.index(word)
    left, right = word[:at], word[at:]
    if right.startswith("-"):
        right = right[1:]
    return (text[:k] + left + "￾" + right + text[k + len(word):]).split("\n")


EN1_LINES = _soft(ewrap(EN1), "relationship", 8)        # relation|ship（組版のハイフン。docx にハイフンはない）
EN2_LINES = _soft(ewrap(EN2), "problem-solving", 7)     # problem-|solving（複合語の本物のハイフン。docx にある）
_paras = docx_paras(("本文", P_RESULT), extra=(("英文要旨", EN1), ("英文要旨", EN2)))
case("lay_en_eol_hyphen", "new", _paras,
     flow(article(Raw(*R_LINES), extra_tail=(BREAK, en_block(*EN1_LINES, *EN2_LINES))), first=25),
     note="英文要旨の行末のハイフンが U+FFFE になり、2 行が 1 行につながって取り出される（PDFium の形）。1 段落目は"
          "組版のハイフン（relation|ship。docx にハイフンはない）、2 段落目は複合語の本物のハイフン（problem-|solving。"
          "docx に「-」がある）。どちらも変えない（ハイフンを足さない。docx の「-」を消さない）。段落ごとの判定で切り分ける。")
