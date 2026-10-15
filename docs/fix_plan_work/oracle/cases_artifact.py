"""反例集（観点: artifact）。組版の文字（ページ番号・誌名の行・柱・投稿受付日）、行末のハイフン・制御文字、本文の中の日付。

期待は runner.py の原則だけで決める（0.19.0 の結果には合わせない）。
- 組版の文字（ページ番号・誌名の行・柱・投稿受付日）は docx の段落に足してはいけない。
  → その文字が段落の途中に入る形の PDF でも、段落は docx のまま（truth を書かない。変われば FAIL）。
- 出版版 PDF の本文にある docx の文字は消してはいけない（数字だけの行・誌名に似た本文・繰り返す行・本当のハイフン）。
- 本当の違いは直す（exact）。組版の文字のすぐ隣の本当の違いは、直すか、直せなければ 13 章に出す（reported）。

どの反例にも、組版の文字から離れた段落に 1 つだけ確かめ用の違い（docx「3回」→ PDF「３回」）を置く（CTRL）。
照合が働いていること（PDF を読めずに何も直さず OK になるのではないこと）を確かめるためで、反例が確かめることとは別の段落にある。

PDF の形は、本誌の出版版 PDF 5 本（tests/private/pdf/）で確かめた形と、その少し先の形（ほかの雑誌のページ番号・柱など）。
- 1 ページ目: 1 行目にページ番号「（25）」、2 行目に誌名の行、題目・副題・「所属　氏名」の行。段落の 1 行目は全角の空白で字下げ。
- 投稿受付日: 本文の行と同じ行に「本文の行 + 空白 + 受付日」または「受付日 + 空白 + 本文の行」の形でつながる。2 行にわたる
  （再投稿受付のある形）。ページの最後の行。古い号は「（2017.11.30受理）」が著者の行の次に 1 行で出る。
- pdfium は、英単語の途中の行末のハイフンを U+FFFE にし、次の行と改行なしでつなげる（本当のハイフン「self-explanation」
  でも同じ）。タブ・番号の後ろに \\x07 が出る。
本文の文字はすべて架空のもの（実際の論文の文字を書き写していない）。
"""
from runner import DEFAULTS, journal_line, received_line, received_old, wrap  # noqa: F401

# ============================================================================ 補助（このファイルだけで使う）


def pg(lines, top=None, bottom=None, heads=()):
    """1 ページの文字。ページ番号の行の文字を top（ページの最初）・bottom（ページの最後）にそのまま書く。
    heads は柱の行（ページ番号の行の次）。runner.page() にない形（「- 25 -」など）を書くため。"""
    out = ([top] if top is not None else []) + list(heads) + list(lines) + ([bottom] if bottom is not None else [])
    return "\n".join(out) + "\n"


def para_lines(text, indent=True):
    """本文の段落の行（1 行目は全角の空白で字下げ。本誌の PDF の形）。"""
    return wrap(("　" if indent else "") + text)


def front_lines(vol=31, no=1, year=2025, fp=25, lp=36):
    """1 ページ目の冒頭（ページ番号の次）: 誌名の行・題目・副題・「所属　氏名」の行。"""
    return [journal_line(vol, no, year, fp, lp), DEFAULTS["題目"], DEFAULTS["副題"], "架空大学　試験　五郎"]


def english_lines(abstract=None):
    """最後のページの英文（題目・副題・著者・Abstract・要旨）。"""
    abs_ = abstract if abstract is not None else DEFAULTS["英文要旨"]
    return ([DEFAULTS["英文題目"], DEFAULTS["英文副題"], "Goro SHIKEN", "Fictional University", "Abstract"]
            + wrap(abs_))


def _check(cond, msg):
    if not cond:
        raise ValueError("反例の組み立ての誤り: " + msg)


# ============================================================================ 架空の論文の段落
H1 = "１．はじめに"
A = ("本研究の目的は，架空の中学校で行われた比例の授業において，生徒が二つの量の変化をどのように関係づけたかを，"
     "授業中の発話と記述の分析によって明らかにすることである。そのために，架空の枠組みを用いて発話を分類し，"
     "授業の展開に沿って生徒の捉え方の変容を追う。")
CTRL_DOCX = "分析の対象は，第２学年の一つの学級で3回行った授業の記録である。授業者は架空の教諭である。"
CTRL_PUB = "分析の対象は，第２学年の一つの学級で３回行った授業の記録である。授業者は架空の教諭である。"
H2 = "２．研究の方法"
C = ("授業の記録は，教室の前後に置いた二台の架空の録画機器によって得た。発話はすべて文字に起こし，"
     "発話者と発話の順番を付けた。記述は授業の終わりに集めた架空のワークシートから得た。"
     "分類は二人の架空の研究者が別々に行い，一致しなかったものは協議して決めた。")
D = ("その結果，生徒の捉え方は，量を別々に見る段階，一方の量の変化に着目する段階，二つの量の変化を対応させる段階の"
     "三つに分けられた。架空の授業の後半では，多くの生徒が対応を表す言葉を用いるようになった。")
RH = "引用および参考文献"
REF1 = "架空一郎（2019）．「架空の数の研究」．『架空数学研究』，第29号，pp.11-16"
REF2 = "架空二郎（2021）．「架空の比の研究」．『架空教育研究』，第12巻，pp.45-58"
# 引用文献の PDF の行（本誌の形: 2 行目以降も字下げなし）。ふつうは「pp.11-16」が 1 行に入る（REF1_LINES）。
# 数字だけの行の反例（N9）だけ、「pp.11-」の後で改行して「16」だけの行になる形（REF1_SPLIT）を使う
REF1_LINES = ["架空一郎（2019）．「架空の数の研究」．『架空", "数学研究』，第29号，pp.11-16"]
REF1_SPLIT = ["架空一郎（2019）．「架空の数の研究」．『架空", "数学研究』，第29号，pp.11-", "16"]
REF2_LINES = ["架空二郎（2021）．「架空の比の研究」．『架空", "教育研究』，第12巻，pp.45-58"]

# 標準の docx の段落（番号は truth のキー）: 0 見出し / 1 A / 2 CTRL / 3 見出し / 4 C / 5 D / 6 文献見出し / 7 REF1 / 8 REF2
BASE = [("見出し", H1), ("本文", A), ("本文", CTRL_DOCX), ("見出し", H2), ("本文", C), ("本文", D),
        ("引用文献見出し", RH), ("引用文献", REF1), ("引用文献", REF2)]
TRUTH = {2: CTRL_PUB}

LA, LCTRL, LC, LD = para_lines(A), para_lines(CTRL_PUB), para_lines(C), para_lines(D)
_check(len(LA) == 6 and len(LC) == 6 and len(LD) == 5, f"行数 A{len(LA)} C{len(LC)} D{len(LD)}")
_check(["".join(REF1_LINES), "".join(REF1_SPLIT), "".join(REF2_LINES)] == [REF1, REF1, REF2], "引用文献の行")


def body_after_a():
    """段落 A の後ろ（確かめ用の段落・方法・結果・引用文献）の行。"""
    return LCTRL + [H2] + LC + LD + [RH] + REF1_LINES + REF2_LINES


# ---------------------------------------------------------------------------- 受付日の形
RECV = received_line()                                                     # 2025年８月31日投稿受付，2025年11月24日採用決定
RECV_RESUB = received_line("2025年２月27日", "2025年10月10日", resub="2025年７月30日")
RECV_RESUB_1, RECV_RESUB_2 = RECV_RESUB.split("，2025年10月10日")[0] + "，", "2025年10月10日採用決定"
_check(RECV_RESUB_1 + RECV_RESUB_2 == RECV_RESUB, "再投稿受付の分け方")
RECV_1, RECV_2 = "2025年８月31日投稿受付，", "2025年11月24日採用決定"
_check(RECV_1 + RECV_2 == RECV, "受付日の分け方")


# ---------------------------------------------------------------------------- 柱の反例の 4 ページの論文
def four_pages(heads_of, top=True):
    """4 ページの論文（ページ 25〜28）。段落 A・C・D の途中でページが変わる。heads_of(ページ番号) は柱の行。"""
    chunks = [
        front_lines() + [H1] + LA[:3],
        LA[3:] + LCTRL + [H2] + LC[:3],
        LC[3:] + LD[:3],
        LD[3:] + [RH] + REF1_LINES + REF2_LINES,
    ]
    return [pg(ls, top=f"（{25 + k}）" if top else None, heads=heads_of(25 + k)) for k, ls in enumerate(chunks)]


# ---------------------------------------------------------------------------- 3 ページで繰り返す段落の最後の行
H3_RESULT = "３．結果"
REPEAT = "ことが明らかになった。"
E1 = ("一つ目の場面では，生徒は表の横の並びに着目し，架空の量が一定の割合で増えることを言葉で述べた。この発言から，"
      "横の見方が対応の見方よりも先に出る") + REPEAT
E2 = ("二つ目の場面では，生徒は二つの量の値の組を順に書き出し，架空の比が変わらないことを確かめた。このことから，"
      "値の組を書く活動で比の一定に気が付く") + REPEAT
E3 = ("三つ目の場面では，生徒はグラフの傾きに着目し，架空の二つの量の関係を式で表そうとした。全体の分析から，"
      "式による表現は対応の見方の定着後に現れる") + REPEAT
LE = [para_lines(e) for e in (E1, E2, E3)]
_check(all(ls[-1] == REPEAT for ls in LE), "E1〜E3 の最後の行が「" + REPEAT + "」だけにならない: "
       + str([ls[-1] for ls in LE]))

# ---------------------------------------------------------------------------- 誌名に似た本文の行
AJ = ("本研究では，比例の指導の研究の動向を探るために，全国数学教育学会誌『数学教育学研究』第24巻から第30巻までに"
      "掲載された架空の論文を対象に，比例の指導に関する記述を整理する。")
# 行末の句読点はぶら下げ（1 行目は字下げ + 23 文字 +「，」）。2 行目が誌名で始まる
LAJ = ["\u3000本研究では，比例の指導の研究の動向を探るために，", "全国数学教育学会誌『数学教育学研究』第24巻から",
       "第30巻までに掲載された架空の論文を対象に，比例の", "指導に関する記述を整理する。"]
_check("".join(LAJ).lstrip("\u3000") == AJ, "AJ の行")

# ---------------------------------------------------------------------------- 本文の中の日付
AD_DOCX = ("参加者は，架空の市の教育委員会を通して募集した。2020年8月30日に受付を始め，2020年9月15日に締め切った。"
           "応募した架空の教員のうち，条件を満たした12名を分析の対象とした。")
AD_PUB = ("参加者は，架空の市の教育委員会を通して募集した。2020年８月30日に受付を始め，2020年９月15日に締め切った。"
          "応募した架空の教員のうち，条件を満たした12名を分析の対象とした。")
# 2 行目が日付で始まる（1 行目の「。」はぶら下げ）。この 2 行目を 1 ページ目の最後の行（受付日の行がよく出る場所）に置く
LAD = ["\u3000参加者は，架空の市の教育委員会を通して募集した。", "2020年８月30日に受付を始め，2020年９月15日に締め",
       "切った。応募した架空の教員のうち，条件を満たした", "12名を分析の対象とした。"]
_check("".join(LAD).lstrip("\u3000") == AD_PUB, "AD の行")

# ---------------------------------------------------------------------------- 受付日の隣の本当の違い
A_FIX_DOCX = A.replace("架空の枠組みを用いて", "架空の枠組みを使って")
_check(A_FIX_DOCX != A and LA[3].endswith("架空の枠組みを用") and LA[4].startswith("いて"), "A_FIX_DOCX")
# 出版版（truth）は A。PDF の 4 行目「…架空の枠組みを用」の後ろに空白と受付日がつながり、5 行目が「いて発話を…」で始まる。
# docx の「使って」と出版版の「用いて」の違いが、受付日をはさんだ 2 行にまたがる

# ---------------------------------------------------------------------------- 英文要旨の本当のハイフン
EN_ABS = ("This study examines how lower secondary school students use self-explanation when they compare two "
          "quantities in a fictional classroom. The analysis of utterances shows three stages of reasoning about "
          "proportional relationships.")
# 出版版 PDF の行: 「self-」で改行。pdfium は行末のハイフンを U+FFFE にし、次の行と改行なしでつなげる
EN_LINES_PUB = ["This study examines how lower secondary school",
                "students use self￾explanation when they compare two quantities",
                "in a fictional classroom. The analysis of utterances",
                "shows three stages of reasoning about proportional",
                "relationships."]
_check(" ".join(EN_LINES_PUB).replace("￾", "-") == EN_ABS, "英文要旨の行")

# ---------------------------------------------------------------------------- 番号・記号の後ろの \x07
H3_TAB = "（1）\t架空の協議における発言の特徴"
NOTE_TAB = "※\t架空の教材の例を参考にして作った。"


# ============================================================================ 反例
CASES = [
    # ------------------------------------------------------------------ ページ番号の形と位置
    {
        "name": "art_pageno_dash_top",
        "angle": "artifact",
        "item": "U7",
        "paras": BASE,
        "truth": TRUTH,
        "pages": [pg(front_lines() + [H1] + LA[:3], top="－ 25 －"),
                  pg(LA[3:] + body_after_a(), top="－ 26 －")],
        "expect": "exact",
        "note": "ほかの雑誌の形: ページ番号が各ページの最初の行の「－ 26 －」（全角のハイフンと空白）。段落 1（A）の途中で"
                "ページが変わり、ページ番号の行が段落の途中に入る。ページ番号は組版の文字なので段落 1 は docx のまま。",
    },
    {
        "name": "art_pageno_ascii_dash_bottom",
        "angle": "artifact",
        "item": "U7",
        "paras": BASE,
        "truth": TRUTH,
        "pages": [pg(front_lines() + [H1] + LA[:3], bottom="- 25 -"),
                  pg(LA[3:] + body_after_a(), bottom="- 26 -")],
        "expect": "exact",
        "note": "ほかの雑誌の形: ページ番号が各ページの最後の行の「- 25 -」（半角のハイフン）。段落 1 の途中でページが変わる。"
                "ページ番号は組版の文字なので段落 1 は docx のまま。",
    },
    {
        "name": "art_pageno_plain_bottom",
        "angle": "artifact",
        "item": "new",
        "paras": BASE,
        "truth": TRUTH,
        "pages": [pg(front_lines() + [H1] + LA[:3], bottom="25"),
                  pg(LA[3:] + body_after_a(), bottom="26")],
        "expect": "exact",
        "note": "ほかの雑誌の形: ページ番号が各ページの最後の行の数字だけ（「25」）。本誌の形（最初の行の「（25）」）だけを"
                "ページ番号とみなすと、段落の途中に「25」が入る。段落 1 は docx のまま。",
    },
    # ------------------------------------------------------------------ 数字だけの本文の行
    {
        "name": "art_digits_after_top_pageno",
        "angle": "artifact",
        "item": "N9",
        "paras": BASE,
        "truth": TRUTH,
        "pages": [pg(front_lines() + [H1] + LA + LCTRL + [H2] + LC + LD + [RH] + REF1_SPLIT[:2], top="（25）"),
                  pg(REF1_SPLIT[2:] + REF2_LINES, top="（26）")],
        "expect": "exact",
        "note": "引用文献 1（段落 7）が「…pp.11-」で 1 ページ目が終わり、2 ページ目のページ番号「（26）」の次の行（本文の"
                "最初の行）が「16」だけになる。ページ番号は「（26）」の行で、「16」は引用文献の本文の文字。消してはいけない"
                "（段落 7 は docx のまま）。",
    },
    {
        "name": "art_digits_last_line_of_page",
        "angle": "artifact",
        "item": "N9",
        "paras": BASE,
        "truth": TRUTH,
        "pages": [pg(front_lines() + [H1] + LA + LCTRL + [H2] + LC + LD + [RH] + REF1_SPLIT, top="（25）"),
                  pg(REF2_LINES + english_lines(), top="（26）")],
        "expect": "exact",
        "note": "ページ番号は本誌の形（各ページの最初の行の「（25）」）。引用文献 1 の「16」だけの行が 1 ページ目の最後の行に"
                "なる。ページの最後の行の数字をページ番号とみなすと「16」を消す。段落 7 は docx のまま。",
    },
    # ------------------------------------------------------------------ 誌名の行
    {
        "name": "art_journal_name_in_body",
        "angle": "artifact",
        "item": "new",
        "paras": [("見出し", H1), ("本文", AJ), ("本文", CTRL_DOCX), ("見出し", H2), ("本文", C), ("本文", D),
                  ("引用文献見出し", RH), ("引用文献", REF1), ("引用文献", REF2)],
        "truth": TRUTH,
        "pages": [pg(front_lines() + [H1] + LAJ + LCTRL + [H2] + LC[:3], top="（25）"),
                  pg(LC[3:] + LD + [RH] + REF1_LINES + REF2_LINES, top="（26）")],
        "expect": "exact",
        "note": "1 ページ目の本文（段落 1）の行が「全国数学教育学会誌『数学教育学研究』第24巻から」で始まる（本誌の論文を"
                "対象にする研究でよくある書き方）。誌名の行（2 行目）に似ているが本文の文字なので、消してはいけない"
                "（段落 1 は docx のまま）。",
    },
    # ------------------------------------------------------------------ 柱
    {
        "name": "art_head_author_short",
        "angle": "artifact",
        "item": "U7",
        "paras": BASE,
        "truth": TRUTH,
        "pages": four_pages(lambda no: () if no == 25 else ("試験五郎",)),
        "expect": "exact",
        "note": "ほかの雑誌の形: 2 ページ目以降の最初（ページ番号の次）に著者名の柱「試験五郎」（4 文字）。4 ページの論文で、"
                "段落 1・4・5 の途中でページが変わり、柱が段落の途中に入る。柱は組版の文字なので、段落 1・4・5 は docx のまま。",
    },
    {
        "name": "art_head_title_two_pages",
        "angle": "artifact",
        "item": "U7",
        "paras": BASE,
        "truth": TRUTH,
        "pages": [pg(front_lines() + [H1] + LA[:3], top="（25）"),
                  pg(LA[3:] + body_after_a(), top="（26）", heads=("架空の比例の授業の分析",))],
        "expect": "exact",
        "note": "ほかの雑誌の形: 2 ページの記事で、2 ページ目の最初（ページ番号の次）に題目を縮めた柱「架空の比例の授業の分析」"
                "（11 文字）。柱は 1 回しか出ない。段落 1 の途中でページが変わる。段落 1 は docx のまま。",
    },
    {
        "name": "art_head_title_three_pages",
        "angle": "artifact",
        "item": "U7",
        "paras": BASE,
        "truth": TRUTH,
        "pages": four_pages(lambda no: () if no == 25 else ("架空の比例の授業の分析",)),
        "expect": "exact",
        "note": "ほかの雑誌の形: 4 ページの論文で、2〜4 ページ目の最初に題目の柱「架空の比例の授業の分析」（3 ページに同じ行）。"
                "段落 1・4・5 の途中でページが変わる。段落 1・4・5 は docx のまま（柱の扱いの基本の形の確かめ）。",
    },
    {
        "name": "art_head_repeated_body_line",
        "angle": "artifact",
        "item": "new",
        "paras": [("見出し", H1), ("本文", A), ("本文", CTRL_DOCX), ("見出し", H2), ("本文", C), ("見出し", H3_RESULT),
                  ("本文", E1), ("本文", D), ("本文", E2), ("本文", E3), ("引用文献見出し", RH), ("引用文献", REF1),
                  ("引用文献", REF2)],
        "truth": TRUTH,
        # ページは段落の切れ目で変わる（段落の途中のページの区切りは入れない）
        "pages": [pg(front_lines() + [H1] + LA + LCTRL + [H2] + LC, top="（25）"),
                  pg([H3_RESULT] + LE[0] + LD, top="（26）"),
                  pg(LE[1], top="（27）"),
                  pg(LE[2] + [RH] + REF1_LINES + REF2_LINES, top="（28）")],
        "expect": "exact",
        "note": "柱はないが、本文の 3 つの段落（6・8・9。26〜28 ページに 1 つずつ）の最後の行が、どれも「ことが明らかになった。」"
                "（11 文字）だけになる。3 ページに同じ文字列の行があっても本文の文字なので、柱とみなして消してはいけない"
                "（段落 6・8・9 は docx のまま）。",
    },
    # ------------------------------------------------------------------ 投稿受付日
    {
        "name": "art_received_old_own_line",
        "angle": "artifact",
        "item": "U7",
        "paras": BASE,
        "truth": TRUTH,
        "pages": [pg([journal_line(24, 1, 2018, 25, 36), DEFAULTS["題目"], DEFAULTS["副題"], "架空大学　試験　五郎",
                      received_old("2017.11.30"), H1] + LA + LCTRL + [H2] + LC[:3], top="（25）"),
                  pg(LC[3:] + LD + [RH] + REF1_LINES + REF2_LINES, top="（26）")],
        "expect": "exact",
        "note": "本誌の古い号の形: 「（2017.11.30受理）」が著者の行の次、見出し「１．はじめに」の前に 1 行で出る。"
                "どの段落にも足してはいけない（見出し 0・題目・著者は docx のまま）。",
    },
    {
        "name": "art_received_last_line_page1",
        "angle": "artifact",
        "item": "U7",
        "paras": BASE,
        "truth": TRUTH,
        "pages": [pg(front_lines() + [H1] + LA[:4] + [RECV], top="（25）"),
                  pg(LA[4:] + body_after_a(), top="（26）")],
        "expect": "exact",
        "note": "本誌の形: 「2025年８月31日投稿受付，2025年11月24日採用決定」が 1 ページ目の最後の行。段落 1 は 2 ページ目に続く"
                "（受付日が段落の途中に入る）。段落 1 は docx のまま。",
    },
    {
        "name": "art_received_prefix_body_line",
        "angle": "artifact",
        "item": "U7",
        "paras": BASE,
        "truth": TRUTH,
        "pages": [pg(front_lines() + [H1] + LA[:3] + [RECV + " " + LA[3]], top="（25）"),
                  pg(LA[4:] + body_after_a(), top="（26）")],
        "expect": "exact",
        "note": "本誌の形: 1 ページ目の最後の行が「受付日 + 空白 + 段落 1 の 4 行目」（受付日が本文の行と同じ行に、本文の前に"
                "つながる）。段落 1 は 2 ページ目に続く。段落 1 は docx のまま。",
    },
    {
        "name": "art_received_two_lines_mid",
        "angle": "artifact",
        "item": "U7",
        "paras": BASE,
        "truth": TRUTH,
        "pages": [pg(front_lines() + [H1] + LA[:2] + [LA[2] + " " + RECV_RESUB_1, RECV_RESUB_2] + LA[3:]
                     + LCTRL + [H2] + LC[:3], top="（25）"),
                  pg(LC[3:] + LD + [RH] + REF1_LINES + REF2_LINES, top="（26）")],
        "expect": "exact",
        "note": "本誌の形（再投稿受付のある号）: ページの途中で、段落 1 の 3 行目の後ろに空白と「2025年２月27日投稿受付，"
                "2025年７月30日再投稿受付，」がつながり、次の行が「2025年10月10日採用決定」だけ、その次から段落 1 が続く。"
                "段落 1 は docx のまま。",
    },
    {
        "name": "art_received_two_lines_page_end",
        "angle": "artifact",
        "item": "U7",
        "paras": BASE,
        "truth": TRUTH,
        "pages": [pg(front_lines() + [H1] + LA[:3] + [LA[3] + " " + RECV_RESUB_1, RECV_RESUB_2], top="（25）"),
                  pg(LA[4:] + body_after_a(), top="（26）")],
        "expect": "exact",
        "note": "本誌の形（再投稿受付のある号）: 段落 1 の 4 行目の後ろに空白と受付日の前半がつながり、1 ページ目の最後の行が"
                "「2025年10月10日採用決定」だけ。段落 1 は 2 ページ目の「（26）」の次に続く。段落 1 は docx のまま。",
    },
    {
        "name": "art_received_both_lines_joined",
        "angle": "artifact",
        "item": "U7",
        "paras": BASE,
        "truth": TRUTH,
        "pages": [pg(front_lines() + [H1] + LA[:2] + [LA[2] + " " + RECV_1, LA[3] + " " + RECV_2] + LA[4:]
                     + LCTRL + [H2] + LC[:3], top="（25）"),
                  pg(LC[3:] + LD + [RH] + REF1_LINES + REF2_LINES, top="（26）")],
        "expect": "exact",
        "note": "本誌の形の少し先: 2 行の受付日の両方の行が、それぞれ同じ高さの本文の行の後ろにつながる（「段落 1 の 3 行目 + "
                "2025年８月31日投稿受付，」「段落 1 の 4 行目 + 2025年11月24日採用決定」）。受付日が短い 2 つに分かれて段落の"
                "途中に入る。段落 1 は docx のまま。",
    },
    {
        "name": "art_received_near_text_fix",
        "angle": "artifact",
        "item": "U7",
        "paras": [("見出し", H1), ("本文", A_FIX_DOCX)] + BASE[2:],
        "truth": {1: A, 2: CTRL_PUB},
        "pages": [pg(front_lines() + [H1] + LA[:3] + [LA[3] + " " + RECV] + LA[4:] + LCTRL + [H2] + LC[:3], top="（25）"),
                  pg(LC[3:] + LD + [RH] + REF1_LINES + REF2_LINES, top="（26）")],
        "expect": {"default": "exact", 1: "reported"},
        "note": "段落 1 の docx「架空の枠組みを使って」が出版版では「架空の枠組みを用いて」（著者校正の直し）。PDF では「…を用」"
                "で行が終わり、その行の後ろに空白と受付日がつながる（本誌の形）。次の行が「いて発話を…」。直すのは「使っ」→"
                "「用い」だけで、受付日を足してはいけない。直せなければ直さずに 13 章に出す（reported）。",
    },
    # ------------------------------------------------------------------ 本文の中の日付
    {
        "name": "art_date_in_body",
        "angle": "artifact",
        "item": "new",
        "paras": [("見出し", H1), ("本文", A), ("本文", CTRL_DOCX), ("見出し", H2), ("本文", AD_DOCX), ("本文", D),
                  ("引用文献見出し", RH), ("引用文献", REF1), ("引用文献", REF2)],
        "truth": {2: CTRL_PUB, 4: AD_PUB},
        "pages": [pg(front_lines() + [H1] + LA + LCTRL + [H2] + LAD[:2], top="（25）"),
                  pg(LAD[2:] + LD + [RH] + REF1_LINES + REF2_LINES, top="（26）")],
        "expect": "exact",
        "note": "本文（段落 4）の「2020年8月30日に受付を始め，2020年9月15日に締め切った」が、出版版では全角の「８」「９」。"
                "PDF ではその行が 1 ページ目の最後の行（受付日の行がよく出る場所）で、日付で始まる。本文の日付なので照合に"
                "使い、全角・半角を直す（exact）。受付日とみなして除くと、直せないか、日付を消す。",
    },
    # ------------------------------------------------------------------ 行末のハイフン・制御文字
    {
        "name": "art_hyphen_real_as_fffe",
        "angle": "artifact",
        "item": "new",
        "paras": BASE + [("英文要旨", EN_ABS)],
        "truth": TRUTH,
        "pages": [pg(front_lines() + [H1] + LA + LCTRL + [H2] + LC[:3], top="（25）"),
                  pg(LC[3:] + LD + [RH] + REF1_LINES + REF2_LINES
                     + [DEFAULTS["英文題目"], DEFAULTS["英文副題"], "Goro SHIKEN", "Fictional University", "Abstract"]
                     + EN_LINES_PUB, top="（26）")],
        "expect": "exact",
        "note": "英文要旨（段落 9）の本当のハイフン「self-explanation」が出版版 PDF で行末に来て、pdfium が U+FFFE にして次の行と"
                "改行なしでつなげた（「self\\ufffeexplanation」。本誌の 29 巻の引用文献で実際に出る形）。U+FFFE は行末の"
                "ハイフンの印で、出版版の本文にはハイフンがある。docx のハイフンを消してはいけない（段落 9 は docx のまま）。",
    },
    {
        "name": "art_bell_after_label",
        "angle": "artifact",
        "item": "new",
        "paras": [("見出し", H1), ("本文", A), ("本文", CTRL_DOCX), ("見出し", H2), ("見出し3", H3_TAB), ("本文", C),
                  ("本文", NOTE_TAB), ("本文", D), ("引用文献見出し", RH), ("引用文献", REF1), ("引用文献", REF2)],
        "truth": TRUTH,
        "pages": [pg(front_lines() + [H1] + LA + LCTRL + [H2], top="（25）"),
                  pg([H3_TAB.replace("\t", "\x07")] + LC + ["　" + NOTE_TAB.replace("\t", "\x07")] + LD
                     + [RH] + REF1_LINES + REF2_LINES, top="（26）")],
        "expect": "exact",
        "note": "本誌の形: 番号「（1）」・記号「※」の後ろのタブが、PDF では制御文字 \\x07 になる（「（1）\\x07架空の…」）。"
                "\\x07 は目に見えない文字なので、見出し（段落 4）と段落 6 は docx のまま（何も足さない・タブを消さない）。",
    },
]
