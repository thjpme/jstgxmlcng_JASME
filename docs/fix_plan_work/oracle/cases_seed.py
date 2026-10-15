"""種の反例（仕組みが正しく動くかを確かめるためのもの）。文字はすべて架空。"""
from runner import (BREAK, DEFAULTS, Join, Raw, flow, journal_line, received_old, wrap)  # noqa: F401

# 小さな論文の共通の段落（架空）
H1 = "１．はじめに"
P1 = ("本研究の目的は，架空の教室で行われた比の授業において，生徒が二つの量の関係をどのように捉えたかを，"
      "発話の記録と記述の分析によって明らかにすることである。そのために，架空の枠組みを用いて発話を分類し，"
      "授業の展開に沿って変容を追う。")
P2_DOCX = "分析の対象は，第２学年の一つの学級で2回行った授業の記録である。授業者は架空の教諭である。"
P2_PUB = "分析の対象は，第２学年の一つの学級で２回行った授業の記録である。授業者は架空の教諭である。"
RH = "引用および参考文献"
REF = "架空一郎（2019）．「架空の数の研究」．『架空数学研究』，第29号，pp.11-16"


def front(first_page=25):
    """1 ページ目の冒頭（ページ番号の後ろ）: 誌名の行・題目・副題・著者名。"""
    return Raw(journal_line(fp=first_page, lp=first_page + 11), DEFAULTS["題目"], DEFAULTS["副題"], "試験　五郎")


CASES = [
    {
        "name": "seed_pagebreak_mid",
        "angle": "layout",
        "item": "new",
        "paras": [("見出し", H1), ("本文", P1), ("本文", P2_DOCX), ("引用文献見出し", RH), ("引用文献", REF)],
        "truth": {2: P2_PUB},
        # 段落 1 の途中でページが変わり、次のページの最初の行が「（26）」
        "pages": flow([front(), H1, Raw(*wrap(P1)[:3]), BREAK, Raw(*wrap(P1)[3:]),
                       P2_PUB, RH, REF], first=25),
        "expect": "exact",
        "note": "段落の途中のページの区切りにページ番号「（26）」があるだけ。段落 2 の「2回」→「２回」だけを直し、"
                "ほかは変えない（OK になるはず）。",
    },
    {
        "name": "seed_received_joined",
        "angle": "artifact",
        "item": "U7",
        "paras": [("見出し", H1), ("本文", P1), ("本文", P2_DOCX), ("引用文献見出し", RH), ("引用文献", REF)],
        "truth": {2: P2_PUB},
        # 1 ページ目で、古い号の受理日「（2017.11.30受理）」が段落 1 の途中の行（3 行目）の後ろにつながって取り出される
        "pages": flow([front(), H1, Raw(*wrap(P1)[:3]), Join(received_old()), Raw(*wrap(P1)[3:]),
                       P2_PUB, RH, REF], first=25),
        "expect": "exact",
        "note": "受理日は組版の文字なので docx に足してはいけない。段落 1 は docx のまま（0.19.0 では足して FAIL のはず）。"
                "新しい形の「…投稿受付，…採用決定」（20 文字以上）を同じ位置につなげると、0.19.0 では足さない（OK）。",
    },
    {
        "name": "seed_ref_pp_digits",
        "angle": "artifact",
        "item": "N9",
        "paras": [("見出し", H1), ("本文", P1), ("本文", P2_DOCX), ("引用文献見出し", RH), ("引用文献", REF)],
        "truth": {2: P2_PUB},
        # 引用文献の「pp.11-」の後の改行で、「16」だけの行になる
        "pages": flow([front(), H1, P1, P2_PUB, RH,
                       Raw("架空一郎（2019）．「架空の数の研究」．『架空", "数学研究』，第29号，pp.11-", "16")], first=25),
        "expect": "exact",
        "note": "「16」は引用文献の本文の文字でページ番号ではない。消してはいけない（0.19.0 では消して FAIL のはず）。",
    },
]
