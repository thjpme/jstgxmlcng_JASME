"""本誌の実際の出版版 PDF（tests/private/pdf。J-STAGE で公開済み。コミットしない）で、ルート2 が PDF のページ番号・
誌名の行・柱・投稿受付日・表の数字の行を docx に挿入せず、本文の文字（引用文献の「pp.11-」の後の「16」など）を消さない
ことを確かめる（単位 B〈0.20.0〉の確認用。scratchpad にだけ置く）。

使い方（リポジトリの外のこのフォルダで。-I は PYTHONPATH と作業フォルダを読まないため）:

  python -I check.py                       # 確かめ用 docx を作り、変更前（HEAD を git worktree で取り出したもの）と
                                           # 変更後（作業ツリー）のコードでルート2 の変換をして、前後を比べる
  python -I check.py --only 27_1_27_47     # 1 本だけ（stem をいくつでも）
  python -I check.py --keep                # 変更前の worktree（../wt_before_B）を消さずに残す（次の実行はそれを使い、消さない。
                                           # 消すときは git -C /home/user/jstgxmlcng_JASME worktree remove --force ../wt_before_B）
  python -I check.py --before-src DIR      # 変更前のコードの src を指定する（worktree を作らない）
  python -I check.py --route1              # 変更後のコードで、ルート1 の 13.4 の一覧も確かめる
  変更前は HEAD（0.19.0）のコード、変更後は作業ツリーの src のコード。1 回に 2 分ほどかかる。

関連（このフォルダ）: dbg_blocks.py（確かめ用 docx の段落の並びを出す）、dbg_align.py（段落の照合の窓と opcodes を出す）、
exp_tail.py（段落の後ろが照合の窓の外に出ると、ほかの段落の文字で直してしまう不具合の、架空の文字での再現。単位 B の外）、
realpdf_B_dump.py（PDF の行を dump/ に書き出す）。

出力（このフォルダの out/ の下。どれもコミットしない）:
  docx/<stem>_<variant>.docx   確かめ用 docx（著者が渡す組版前の docx の想定。下の「作り方」）
  run_before/・run_after/      変換の出力（PDF に合わせて直した docx・XML・レポート）
  results_before.json・results_after.json   直した箇所・違い・照合に使わなかった文字など（ワーカーの出力）
  summary.txt                  前後の比較（端末にも出す）

確かめ用 docx の作り方（SPECS）:
  ・PDF の各ページの空でない行から、ページ番号（ページの最初の行の「（25）」）・1 ページ目の誌名の行・投稿受付日の文字を除く
    （著者が渡す docx は組版の前のものなので、これらは入っていない、という想定）。
  ・図の中の文字（skip）は docx に入れない（docx では図は画像）。図・表のキャプション（caption）は別の段落にし、表（table）は
    Word の表にする（variant "table"）。variant "text" では、表を本文の段落にする（表をタブなどで本文に書いた原稿の想定。
    表の数字の行の扱いを確かめるため）。
  ・行をつないで段落にする。段落の始まりは、全角空白で始まる行・見出し・注の番号・引用文献の始まり・SPECS の start。
    段落の終わりは、「。」で終わる短い行。ページ番号などのほかは、PDF の文字をそのまま使う（docx の文字の順は、PDF から
    取り出した文字の順。29 巻 79 の 1 ページ目だけ読む順に並べ直す〈order〉）。
  ・題目・副題・著者・英文（題目・著者・Abstract）は make_fixtures の front_ja・front_en で作る。
  ・わざと入れた違い（diffs。docx を PDF と違う文字にする）:
      M1  ページの途中の行の語を変える                    → 変更後も直る（docx が PDF の文字になる）はず
      E1  ページの端の行（ほかの文字は段落に当たる）の語を変える → 変更後も直るはず（その行は段落に当たるので照合に使う）
      E2  ページの端の行の文字を、PDF にない文字（甲乙丙…）に差し替える
                                                          → 変更後は直さず、fixable=False（HEAD_WHY）と ignored_lines に出るはず
      E3  ページの端の行を docx から除く（校正で足した一文の想定） → 変更後は足さず、ignored_lines に出るはず
          （本誌の本文の行は 24 文字ほどなので、段落の途中の行をまるごと除くと 20 文字以上になり、変更前も足さない）

まとめ（summary.txt）の見方: 「組版の文字による挿入・削除」は、直した箇所のうち、PDF のページ番号・誌名の行・受付日・数字だけの
行（表のセル・引用文献の「16」）・表の文字によるもの。「それ以外の想定外」は、わざと入れた違いにかからない、ほかの直した箇所
（確かめ用 docx は PDF の文字から作ったので、本来は 0）。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import traceback
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path("/home/user/jstgxmlcng_JASME")
PDF_DIR = REPO / "tests" / "private" / "pdf"
OUT = HERE / "out"
WT = HERE.parent / "wt_before_B"

# ---------------------------------------------------------------------------- PDF の文字（照合のコードに頼らず、ここで読む）
# ページ番号の行と投稿受付日（pdfmatch.RE_PAGE_NO・RE_RECEIVED と同じ形。docx から除くために使う）
RE_PAGE_NO = re.compile(r"^[\s　]*(?:[(（]?[0-9０-９]{1,4}[)）]?|[-－‐−–—―][\s　]*[0-9０-９]{1,4}[\s　]*[-－‐−–—―])[\s　]*$")
_D = "[0-9０-９]"
_KIND = "(?:再投稿受付|投稿受付|採用決定|受付|受理)"
_JA = rf"{_D}{{4}}\s*年\s*{_D}{{1,2}}\s*月\s*{_D}{{1,2}}\s*日\s*{_KIND}"
_DOT = rf"{_D}{{4}}\s*[.．]\s*{_D}{{1,2}}\s*[.．]\s*{_D}{{1,2}}\s*{_KIND}"
_SEP = r"\s*[，,、]?\s*"
RE_DATE = re.compile(rf"{_JA}(?:{_SEP}{_JA})*|[（(]\s*{_DOT}(?:{_SEP}{_DOT})*\s*[）)]")
SWAP = "甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉"      # E2 で差し替える文字（PDF にない文字）


def visible(line: str) -> bool:
    return any(not c.isspace() and unicodedata.category(c) not in ("Cc", "Cf", "Cn") for c in line)


def clean(s: str) -> str:
    """docx に入れる文字: 制御文字・PDF の目に見えない文字（行末のハイフンの U+FFFE など）を除き、タブを空白にする。"""
    s = s.replace("\t", " ")
    return "".join(c for c in s if unicodedata.category(c) not in ("Cc", "Cf", "Cn"))


def read_pdf(pdf: Path) -> list:
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(pdf))
    try:
        pages = [doc[i].get_textpage().get_text_range() for i in range(len(doc))]
    finally:
        doc.close()
    return [re.split(r"\r\n|\r|\n", p) for p in pages]


# ---------------------------------------------------------------------------- 確かめ用 docx の作り方
# 行は (ページ, 行の番号)。行の番号は、ページの文字を改行で分けたときの位置（空の行も数える。dump/ の番号と同じ）。
# skip・caption・table は (ページ, 最初の行, 最後の行)。en の authors は ((氏名の行), (所属の行))。
# diffs は (名前, ページ, 行, 種類, 変える前, 変えた後)。種類 replace（docx の文字を変える）/ swap（行を SWAP の文字に）/
# drop（行を docx から除く）。
SPECS = {
    "24_1_24_25": dict(
        pages=[1, 2, 3, 11, 12],
        title=[(1, 2), (1, 3)], subtitle=[], authors=[(1, 4)],
        skip=[(1, 72, 75), (2, 86, 95), (3, 84, 88)],
        caption=[(1, 71, 71), (2, 50, 50), (3, 62, 63)],
        en=dict(title=[(12, 19), (12, 20)], subtitle=[], authors=[((12, 21), (12, 22))], abstract=[(12, 24, 36)]),
        diffs=[("M1", 2, 40, "replace", "最後", "最終"),
               ("E1", 3, 1, "replace", "視点", "観点"),
               ("E2", 12, 2, "swap", "", "")],
    ),
    "25_1_25_77": dict(
        pages=[1, 2, 9, 10, 11],
        title=[(1, 2), (1, 3)], subtitle=[(1, 4)], authors=[(1, 5)],
        start=[(2, 1), (2, 4), (2, 35), (2, 36), (2, 37), (2, 39), (2, 58), (2, 60), (2, 62), (2, 65)],
        en=dict(title=[(11, 1), (11, 2)], subtitle=[(11, 3)], authors=[((11, 4), (11, 5))], abstract=[(11, 7, 24)]),
        diffs=[("M1", 1, 40, "replace", "今後", "以後"),
               ("E1", 1, 76, "replace", "まとめれば", "まとめると"),
               ("E3", 2, 2, "drop", "", "")],
    ),
    "27_1_27_47": dict(
        pages=[1, 2, 3, 4, 21, 22],
        title=[(1, 2)], subtitle=[(1, 3)], authors=[(1, 4)],
        table=[(3, 82, 103), (4, 77, 98)],
        caption=[(3, 104, 104), (4, 99, 99)],
        en=dict(title=[(22, 27)], subtitle=[(22, 28)], authors=[((22, 29), (22, 30))], abstract=[(22, 32, 43)]),
        diffs=[("M1", 2, 50, "replace", "背景も", "背景をも"),
               ("E1", 1, 76, "replace", "研究が少ない", "研究は少ない"),
               ("E2", 4, 1, "swap", "", "")],
    ),
    "29_2_29_79": dict(
        pages=[1, 2, 12, 13],
        # 1 ページ目は、取り出した文字の順が読む順と違う（左の段の下の部分が、右の段と図の後に出る）ので並べ直す
        order={1: [(0, 16), (129, 139), (17, 56), (57, 128)]},
        title=[(1, 1)], subtitle=[(1, 2)], authors=[(1, 3), (1, 4)],
        # 図１・図２の中に、投稿時の原稿のページの文字が重なって入っている（図の中の文字として除く）
        skip=[(1, 57, 128), (2, 84, 167)],
        caption=[(1, 55, 56), (2, 82, 83)],
        start=[(2, 80)],
        en=dict(title=[(13, 1)], subtitle=[(13, 2)], authors=[((13, 3), (13, 4)), ((13, 5), (13, 6))],
                abstract=[(13, 8, 35)]),
        diffs=[("M1", 2, 30, "replace", "典型的", "代表的"),
               ("E1", 2, 2, "replace", "構造指向", "構造志向"),
               ("E2", 12, 82, "swap", "", "")],
    ),
    "30_2_30_59": dict(
        pages=[1, 2, 11, 12, 13, 16, 17],
        title=[(1, 2)], subtitle=[(1, 3)], authors=[(1, 4), (1, 5)],
        caption=[(11, 48, 48), (11, 49, 49), (11, 50, 50), (12, 83, 84), (13, 52, 52), (13, 53, 53)],
        table=[(11, 51, 70), (11, 71, 90), (11, 91, 110), (13, 54, 73)],
        en=dict(title=[(19, 13)], subtitle=[(19, 14)], authors=[((19, 15), (19, 16)), ((19, 17), (19, 18))],
                abstract=[(19, 20, 33)]),
        diffs=[("M1", 1, 30, "replace", "仕事", "役割"),
               ("E1", 1, 78, "replace", "本稿の目的", "本研究の目的"),
               ("E2", 2, 1, "swap", "", "")],
    ),
}
VARIANTS = {"24_1_24_25": ["table"], "25_1_25_77": ["table"], "27_1_27_47": ["table", "text"],
            "29_2_29_79": ["table"], "30_2_30_59": ["table", "text"]}
EXPECT_AFTER = {"M1": "直る", "E1": "直る", "E2": "直さない（HEAD_WHY）", "E3": "足さない（ignored_lines）"}

RE_HEAD1 = re.compile(r"^[０-９0-9]{1,2}．\S")                       # １．はじめに
RE_HEAD2 = re.compile(r"^(?:[0-9０-９]{1,2}\.\s*[0-9０-９]{1,2}．|[（(][0-9０-９]{1,2}[）)])\s*\S")   # 2. 1．… /（1）…
RE_HEAD3 = re.compile(r"^(?:[①-⑳]|視点[①-⑳])")
RE_NOTE = re.compile(r"^[０-９0-9]{1,2}）(?![。，、）])")               # 注の番号（１）…。「31）。」は除く）
RE_REF_JA = re.compile(r"^(?:[^\x00-\x7f（(「『][^（(「『]{0,39}?[（(][0-9０-９]{4}[a-z]?[）)]|[ァ-ヶー・]+，)")
RE_REF_EN = re.compile(r"^[A-ZÀ-Ý][A-Za-zÀ-ÿ'’\-]+(?:\.|,|，)\s*[A-Z]")
REF_HEADS = ("引用および参考文献", "引用・参考文献")
NOTE_HEADS = ("註", "注")


def dwidth(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "FW" else 1 for c in s)


def in_ranges(rngs, p, i):
    return any(p == a and lo <= i <= hi for a, lo, hi in rngs)


class Article:
    """1 本の PDF から作る確かめ用 docx の中身と、PDF の行の分類。"""

    def __init__(self, stem, spec, variant):
        self.stem, self.spec, self.variant = stem, spec, variant
        self.pages = read_pdf(PDF_DIR / f"{stem}.pdf")
        self.cat = {}            # (ページ, 行) -> 行の分類
        self.dates = []          # 投稿受付日の文字列（空白を除いたもの）
        self.date_mask = {}      # (ページ, 行) -> その行の中の投稿受付日の文字の位置
        self.page_numbers = []   # ページ番号の文字列
        self.journal = ""        # 誌名の行（空白を除いたもの）
        self.blocks = []         # docx の本文の並び: ("p", 様式, [(ページ, 行, 文字)]) / ("table", [文字]) / ("image",)
        self.diffs = []          # わざと入れた違い（evaluate で使う）
        self._prepare()
        self._build()

    # -- PDF の行の分類 -------------------------------------------------------------------------------------------
    def _prepare(self):
        sp = self.spec
        en_lines = set()
        en = sp.get("en") or {}
        for p, i in en.get("title", []) + en.get("subtitle", []):
            en_lines.add((p, i))
        for a, b in en.get("authors", []):
            en_lines |= {a, b}
        for p, lo, hi in en.get("abstract", []):
            en_lines |= {(p, i) for i in range(lo, hi + 1)}
        front = set(sp.get("title", [])) | set(sp.get("subtitle", [])) | set(sp.get("authors", []))
        en_pages = {p for p, _ in en_lines}
        for pn, ls in enumerate(self.pages, 1):
            if pn in en_pages:      # 英文要旨の見出し（make_fixtures.front_en が入れる）
                en_lines |= {(pn, i) for i, x in enumerate(ls) if x.strip() == "Abstract"}
            shown = [i for i, x in enumerate(ls) if visible(x)]
            if shown and RE_PAGE_NO.match(ls[shown[0]]):
                self.cat[(pn, shown[0])] = "ページ番号"
                self.page_numbers.append(ls[shown[0]].strip())
            # 投稿受付日（行をまたぐので、ページの文字をつないで探す）
            text = "\n".join(ls)
            starts, pos = [], 0
            for x in ls:
                starts.append(pos)
                pos += len(x) + 1
            for m in RE_DATE.finditer(text):
                self.dates.append(re.sub(r"\s+", "", m.group()))
                for k in range(m.start(), m.end()):
                    li = max(i for i, s in enumerate(starts) if s <= k)
                    self.date_mask.setdefault((pn, li), set()).add(k - starts[li])
            for i in shown:
                key = (pn, i)
                if key in self.cat:
                    continue
                x = ls[i]
                if in_ranges(sp.get("skip", []), pn, i):
                    self.cat[key] = "図の中の文字"
                elif pn == 1 and x.strip().startswith("全国数学教育学会誌"):
                    self.cat[key] = "誌名の行"
                    self.journal = re.sub(r"\s+", "", x)
                elif key in self.date_mask and not clean("".join(c for k, c in enumerate(x)
                                                                 if k not in self.date_mask[key])).strip():
                    self.cat[key] = "受付日"
                elif key in front:
                    self.cat[key] = "題目・著者"
                elif key in en_lines:
                    self.cat[key] = "英文"
                elif in_ranges(sp.get("table", []), pn, i):
                    self.cat[key] = "表の文字"
                elif in_ranges(sp.get("caption", []), pn, i):
                    self.cat[key] = "キャプション"
                elif pn not in sp["pages"]:
                    self.cat[key] = "docx に入れなかったページ"
                else:
                    self.cat[key] = "本文"
        self.digit_lines = {(p, i): self.pages[p - 1][i].strip() for (p, i), c in self.cat.items()
                            if c in ("本文", "表の文字") and RE_PAGE_NO.match(self.pages[p - 1][i])}

    def line_text(self, p, i) -> str:
        """docx に入れる行の文字（投稿受付日の文字を除いたもの）。"""
        x = self.pages[p - 1][i]
        mask = self.date_mask.get((p, i), set())
        return clean("".join(c for k, c in enumerate(x) if k not in mask)).strip()

    # -- docx の段落 ----------------------------------------------------------------------------------------------
    def _order(self, pn):
        ls = self.pages[pn - 1]
        segs = self.spec.get("order", {}).get(pn)
        if not segs:
            return list(range(len(ls)))
        out = [i for a, b in segs for i in range(a, b + 1)]
        return out + [i for i in range(len(ls)) if i not in out]

    def _build(self):
        sp = self.spec
        diffs = {(p, i): (name, kind, old, new) for name, p, i, kind, old, new in sp.get("diffs", [])}
        starts = set(sp.get("start", []))
        cur = None                       # 作っている段落: [様式, [(p, i, 文字)], 閉じたか]
        pending = []                     # 段落の後に置くキャプション・表
        tables = {}                      # 表の範囲 -> 行の文字
        in_refs = False
        prev_page = None

        def close():
            nonlocal cur
            if cur is not None and cur[1]:
                self.blocks.append(("p", cur[0], cur[1]))
            cur = None
            for b in pending:
                self.blocks.append(b)
            pending.clear()

        for pn in sp["pages"]:
            if prev_page is not None and pn != prev_page + 1:
                close()                  # 入れなかったページをはさむ: 段落を切る
            prev_page = pn
            for i in self._order(pn):
                c = self.cat.get((pn, i))
                if c is None or c in ("ページ番号", "誌名の行", "受付日", "図の中の文字", "題目・著者", "英文"):
                    continue
                if c == "キャプション":
                    rng = next(r for r in sp["caption"] if r[0] == pn and r[1] <= i <= r[2])
                    if i == rng[1]:
                        cap = [(pn, k, self.line_text(pn, k)) for k in range(rng[1], rng[2] + 1)]
                        style = "fig_cap" if cap[0][2].startswith("図") else "tab_cap"
                        if style == "fig_cap":
                            pending.append(("image",))
                        pending.append(("p", style, cap))
                        if cur is None:
                            close()
                    continue
                if c == "表の文字":
                    rng = next(r for r in sp["table"] if r[0] == pn and r[1] <= i <= r[2])
                    tables.setdefault(rng, []).append((pn, i, self.line_text(pn, i)))
                    if i == rng[2]:
                        if self.variant == "table":
                            pending.append(("table", tables[rng]))
                        else:
                            pending.append(("p", "body", tables[rng]))
                        if cur is None:
                            close()
                    continue
                t = self.line_text(pn, i)
                if not t:
                    continue
                if (pn, i) in diffs:
                    name, kind, old, new = diffs[(pn, i)]
                    pdf_t = t
                    if kind == "replace":
                        assert old in t, (self.stem, pn, i, old, t)
                        t = t.replace(old, new, 1)
                    elif kind == "swap":
                        n = len(re.sub(r"\s", "", pdf_t))
                        t = "".join(SWAP[k % len(SWAP)] for k in range(min(n, 12)))
                    elif kind == "drop":
                        t = ""
                    self.diffs.append(dict(name=name, page=pn, line=i, kind=kind, pdf=pdf_t, docx=t,
                                           expect=EXPECT_AFTER[name]))
                raw = self.pages[pn - 1][i]
                strip = t.lstrip("　 ")
                heading = None
                if t in REF_HEADS:
                    heading, in_refs = "ref_head", True
                elif t in NOTE_HEADS:
                    heading = "fn_head"
                elif not in_refs and not t.endswith("。") and len(t) <= 30 and (
                        RE_HEAD1.match(strip) or RE_HEAD2.match(strip) or RE_HEAD3.match(strip)) \
                        and not raw.startswith("　") and (cur is None or cur[1][-1][2].endswith("。")):
                    heading = "sec1" if RE_HEAD1.match(strip) else "sec2" if RE_HEAD2.match(strip) else "sec3"
                if heading:
                    close()
                    self.blocks.append(("p", heading, [(pn, i, t)]))
                    continue
                new_para = (raw.startswith("　") or (pn, i) in starts or RE_NOTE.match(strip)
                            or (in_refs and (RE_REF_JA.match(strip) or RE_REF_EN.match(strip))))
                if cur is None or new_para:
                    close()
                    cur = ["ref" if in_refs else "body", [], False]
                if t:
                    cur[1].append((pn, i, t))
                elif kind == "drop":
                    cur[1].append((pn, i, ""))
                if t.endswith("。") and dwidth(raw.strip()) <= 44 and not in_refs:
                    close()
        close()

    # -- 段落の文字 -----------------------------------------------------------------------------------------------
    @staticmethod
    def join(pieces) -> str:
        out = ""
        for _, _, t in pieces:
            if not t:
                continue
            if out and ord(out[-1]) < 0x250 and ord(t[0]) < 0x250 and not out[-1].isspace() and out[-1] != "-":
                out += " "
            out += t
        return out

    def front(self):
        sp = self.spec

        def txt(keys):
            return "".join(self.line_text(p, i) for p, i in keys)

        authors = []
        for p, i in sp["authors"]:
            x = clean(self.pages[p - 1][i]).strip()
            aff, _, name = x.partition("　")
            authors.append((re.sub(r"\s", "", aff), re.sub(r"\s", "", name)))
        return txt(sp["title"]), txt(sp.get("subtitle", [])), authors

    def front_en(self):
        en = self.spec.get("en")
        if not en:
            return "A Checking Article", "", [("Taro SHIKEN", "Fictional University")], ["Abstract for checking."]

        def txt(keys):
            return self.join([(p, i, self.line_text(p, i)) for p, i in keys])

        authors = [(self.line_text(*a), self.line_text(*b)) for a, b in en["authors"]]
        paras, cur = [], []
        for p, lo, hi in en["abstract"]:
            for i in range(lo, hi + 1):
                raw = self.pages[p - 1][i]
                if not visible(raw):
                    continue
                if raw.startswith("　") and cur:
                    paras.append(self.join(cur))
                    cur = []
                cur.append((p, i, self.line_text(p, i)))
        if cur:
            paras.append(self.join(cur))
        return txt(en["title"]), txt(en.get("subtitle", [])), authors, paras

    def write_docx(self, path: Path):
        sys.path.insert(0, str(REPO / "tests"))
        import make_fixtures as mf
        b = mf.Builder()
        title, subtitle, authors = self.front()
        body = mf.front_ja(b, title, subtitle, authors)
        img = None
        self.paragraphs = []         # docx の本文の段落の文字（evaluate で段落を探すため）
        for blk in self.blocks:
            if blk[0] == "image":
                if img is None:
                    img = b.add_image("fig.png", mf.png_bytes("Figure"))
                body.append(mf.para(mf.S["body"], mf.drawing(img, 1440000, 900000, 100 + len(body)), jc="center"))
            elif blk[0] == "table":
                body.append(mf.table([[mf.cell(t)] for _, _, t in blk[1] if t]))
            else:
                text = self.join(blk[2])
                if not text:
                    continue
                body.append(mf.para(mf.S[blk[1]], text))
                self.paragraphs.append(dict(style=blk[1], text=text, lines=[(p, i) for p, i, _ in blk[2]]))
        et, es, ea, eabs = self.front_en()
        body += mf.front_en(b, et, es, ea, eabs)
        body += mf.tail(b)
        b.save(path, body)
        # わざと入れた違いの、docx の段落の中の位置
        for d in self.diffs:
            for k, para in enumerate(self.paragraphs):
                if (d["page"], d["line"]) in para["lines"]:
                    d["para"] = k
                    d["text"] = para["text"]
                    # 段落の中の位置: その行より前の行の文字をつないだ長さ
                    before = self.join([(p, i, t) for p, i, t in self._pieces(k)
                                        if (p, i) != (d["page"], d["line"]) and para["lines"].index((p, i))
                                        < para["lines"].index((d["page"], d["line"]))])
                    if d["kind"] == "replace":
                        old, new = next((o, n) for nm, p, i, kd, o, n in self.spec["diffs"] if nm == d["name"])
                        at = para["text"].find(new, max(0, len(before) - 2))
                        d["pos"] = [at, at + len(new)]
                        d["pdf_seg"], d["docx_seg"] = old, new
                    elif d["kind"] == "swap":
                        at = para["text"].find(d["docx"])
                        d["pos"] = [at, at + len(d["docx"])]
                        d["pdf_seg"], d["docx_seg"] = d["pdf"], d["docx"]
                    else:
                        at = len(before) + (1 if before and ord(before[-1]) < 0x250 else 0)
                        d["pos"] = [at, at]
                        d["pdf_seg"], d["docx_seg"] = d["pdf"], ""
                    break
        return path

    def _pieces(self, k):
        n = -1
        for blk in self.blocks:
            if blk[0] == "p" and self.join(blk[2]):
                n += 1
                if n == k:
                    return blk[2]
        return []

    def meta(self) -> dict:
        """evaluate で使う、PDF の行の分類など。"""
        lines = {}
        for (p, i), c in self.cat.items():
            lines.setdefault(re.sub(r"\s+", "", clean(self.pages[p - 1][i])), set()).add(c)
        return dict(stem=self.stem, variant=self.variant, dates=self.dates, page_numbers=self.page_numbers,
                    journal=self.journal, digit_lines=sorted(set(self.digit_lines.values())),
                    lines={k: sorted(v) for k, v in lines.items()}, diffs=self.diffs,
                    paragraphs=[p["text"] for p in self.paragraphs],
                    figure_text="".join(re.sub(r"\s+", "", clean(self.pages[p - 1][i]))
                                        for (p, i), c in self.cat.items() if c == "図の中の文字"),
                    table_text="".join(re.sub(r"\s+", "", clean(self.pages[p - 1][i]))
                                       for (p, i), c in self.cat.items() if c == "表の文字"))


# ---------------------------------------------------------------------------- 変換（変更前・後のコードで別のプロセスで）
def worker(src_root: str, jobs_path: str, out_path: str):
    sys.path.insert(0, src_root)
    import jasme_jats
    from lxml import etree
    from jasme_jats.config import ArticleMeta, JournalConfig
    from jasme_jats.docx_reader import read_docx
    from jasme_jats.pdfdocx import tracked_counts
    from jasme_jats.pipeline import Options, convert
    assert Path(jasme_jats.__file__).resolve().is_relative_to(Path(src_root).resolve()), jasme_jats.__file__
    jobs = json.loads(Path(jobs_path).read_text(encoding="utf-8"))
    j = JournalConfig.load()
    out = {"version": jasme_jats.__version__, "file": jasme_jats.__file__, "jobs": {}}
    for job in jobs:
        name = job["name"]
        try:
            meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12",
                                          "pub_date": "2026-03-31", "received": "2025-06-01",
                                          "accepted": "2025-11-20", "peer_review": "あり", "keywords": "確認"})
            od = Path(job["out_dir"])
            od.mkdir(parents=True, exist_ok=True)
            res = convert(job["docx"], meta, j, Options(out_dir=od, route=job["route"], pdf_path=Path(job["pdf"]),
                                                        convert_metafiles=False))
            fx = res.docx_fix
            pc = fx.check if fx is not None else res.pdf_check
            texts = dict(getattr(fx, "texts", {}) or {}) if fx is not None else {}

            def text_of(src):
                if src in texts:
                    return texts[src]
                p = res.plan.paras.get(src)
                return p.plain() if p is not None else ""

            r = {"ok": [res.fidelity.ok, res.fidelity.final_ok, res.dtd_valid, len(res.jstage_issues)],
                 "pdf_ok": pc.ok if pc is not None else None, "checked": pc.checked if pc else 0,
                 "width": pc.width_count if pc else 0, "drops": pc.drop_count if pc else 0,
                 "fixes": [], "diffs": [], "unmatched": [], "ignored": [], "tracked": None}
            if fx is not None:
                r["fixes"] = [dict(src=f.src, start=f.start, end=f.end, old=f.old, new=f.new, kind=f.kind,
                                   applied=f.applied, reason=f.reason, para=text_of(f.src)) for f in fx.fixes]
                r["tracked"] = list(tracked_counts(fx.path)) if Path(fx.path).exists() else None
            if pc is not None:
                r["diffs"] = [dict(src=d.src, start=d.start, end=d.end, docx=d.docx, pdf=d.pdf, fixable=d.fixable,
                                   why=getattr(d, "why", ""), para=text_of(d.src)) for d in pc.diffs]
                r["unmatched"] = [[s, text_of(s)] for s in pc.unmatched]
                r["ignored"] = [[s, t, text_of(s)] for s, t in getattr(pc, "ignored_lines", [])]
            rep = res.report_path.read_text(encoding="utf-8")
            m = re.search(r"^## 13\..*?(?=^## 14\.|\Z)", rep, re.S | re.M)
            r["report13"] = m.group() if m else ""
            # XML と元の docx の文字（PDF の組版の文字が XML に入ったかを見るため）
            xml_text = "".join(etree.fromstring(res.xml_path.read_bytes()).itertext())
            doc = read_docx(job["docx"])
            src_text = "".join(p.plain() for p in doc.all_paragraphs())
            r["xml_text"] = re.sub(r"\s+", "", xml_text)
            r["docx_text"] = re.sub(r"\s+", "", src_text)
            out["jobs"][name] = r
        except Exception:  # noqa: BLE001
            out["jobs"][name] = {"error": traceback.format_exc()}
    Path(out_path).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------------------- 結果の分け方
def nospace(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def artifact_kind(s: str, meta) -> str:
    """PDF の文字 s（足す・差し替える文字）が、組版で入る文字のどれか。"""
    t = nospace(s)
    if not t:
        return ""
    if RE_DATE.search(t) or any(t in d or d in t for d in meta["dates"] if len(t) >= 4):
        return "受付日"
    if any(nospace(n) == t or nospace(n) in t for n in meta["page_numbers"]):
        return "ページ番号"
    if meta["journal"] and len(t) >= 3 and (t in meta["journal"] or "学会誌" in t and "巻" in t):
        return "誌名の行"
    if t in meta["digit_lines"]:
        return "数字だけの行（表・N9）"
    if meta["table_text"] and len(t) >= 2 and t in meta["table_text"]:
        return "表の文字"
    if meta["figure_text"] and len(t) >= 2 and t in meta["figure_text"]:
        return "図の中の文字"
    return ""


def ignored_kind(t: str, meta) -> str:
    u = nospace(clean(t))
    if any(u == d for d in meta["dates"]):
        return "受付日"
    cats = meta["lines"].get(u)
    if cats:
        return "・".join(cats)
    return "（行が見つからない）"


def apply_fixes(text, fixes):
    out, pos = [], 0
    for f in sorted(fixes, key=lambda f: (f["start"], f["end"])):
        out.append(text[pos:f["start"]])
        out.append(f["new"])
        pos = f["end"]
    out.append(text[pos:])
    return "".join(out)


def evaluate(meta, r) -> dict:
    """1 つの変換の結果を、わざと入れた違いと、それ以外（組版の文字によるものなど）に分ける。"""
    if "error" in r:
        return {"error": r["error"]}
    paras = meta["paragraphs"]
    intended = []
    for d in meta["diffs"]:
        if "para" not in d:
            intended.append(dict(d, result="（段落を作れなかった）"))
            continue
        ptext = paras[d["para"]]
        a, b = d["pos"]
        fixes = [f for f in r["fixes"] if f["para"] == ptext]
        near = [f for f in fixes if f["start"] < max(b, a + 1) + 2 and a - 2 < max(f["end"], f["start"] + 1)]
        applied = [f for f in near if f["applied"]]
        diffs = [x for x in r["diffs"] if x["para"] == ptext and x["start"] < max(b, a + 1) + 2
                 and a - 2 < max(x["end"], x["start"] + 1)]
        ign = [t for s, t, pt in r["ignored"] if pt == ptext and nospace(clean(t)) == nospace(d["pdf"])]
        # 直った: わざと入れた違いの近くの直しを当てはめた段落が、PDF の文字（違いを入れる前の段落）と同じになった
        fixed_near = apply_fixes(ptext, applied)
        truth = ptext[:a] + d["pdf_seg"] + ptext[b:]
        ok_fixed = nospace(fixed_near) == nospace(truth)
        if any(pt == ptext for _, pt in r["unmatched"]):
            res = "見つからない段落"
        elif ok_fixed:
            res = "直った"
        elif applied:
            res = f"誤（PDF の別の文字で直した: {[(f['old'][:12], f['new'][:40]) for f in applied]}）"
        elif any(not x["fixable"] and x.get("why") for x in diffs):
            res = "直さない（fixable=False・why）"
        elif diffs:
            res = "直さない（" + "／".join((f["reason"] or "理由なし")[:24] for f in near if not f["applied"]) + "）"
        elif not near:
            res = "違いにならない"
        else:
            res = "直さない"
        if ign:
            res += "＋ignored_lines"
        intended.append(dict(name=d["name"], page=d["page"], line=d["line"], kind=d["kind"], expect=d["expect"],
                             result=res))
    # わざと入れた違いにかからない、直した箇所・違い
    def is_intended(x, ptext):
        for d in meta["diffs"]:
            if "para" in d and paras[d["para"]] == ptext:
                a, b = d["pos"]
                if x["start"] < max(b, a + 1) + 2 and a - 2 < max(x["end"], x["start"] + 1):
                    return True
        return False

    other_fixes, artifact = [], {}
    for f in r["fixes"]:
        if not f["applied"]:
            continue
        if is_intended(f, f["para"]):
            # わざと入れた違いの直しに、受付日・ページ番号・誌名の行が混じったもの（変更前のコードで、受付日の隣の違いを直すと
            # 受付日も docx に入った）も数える
            kind = artifact_kind(f["new"], meta)
            if kind in ("受付日", "ページ番号", "誌名の行"):
                artifact.setdefault(kind, []).append(f)
            continue
        kind = artifact_kind(f["new"], meta) if f["new"] else ""
        old = nospace(f["old"])
        if not f["new"] and old.isdigit() and any(old in x for x in meta["digit_lines"]):
            kind = "数字だけの行（表・N9）"       # 「16」の「6」だけを消すこともある
        if not kind and not f["new"] and meta["table_text"] and len(nospace(f["old"])) >= 4 \
                and nospace(f["old"]) in meta["table_text"]:
            kind = "表の文字"
        if kind:
            artifact.setdefault(kind, []).append(f)
        other_fixes.append(dict(f, artifact=kind))
    other_diffs = [dict(x, artifact=artifact_kind(x["pdf"], meta)) for x in r["diffs"] if not is_intended(x, x["para"])]
    ign = [(s, t, ignored_kind(t, meta)) for s, t, _ in r["ignored"]]
    # XML に入った組版の文字（元の docx になく、XML にあるもの）
    leaked = []
    for s in meta["dates"] + [n for n in meta["page_numbers"]]:
        u = nospace(s)
        if r["xml_text"].count(u) > r["docx_text"].count(u):
            leaked.append(u)
    return dict(intended=intended, artifact={k: len(v) for k, v in artifact.items()},
                artifact_fixes={k: [(f["src"], f["old"], f["new"]) for f in v] for k, v in artifact.items()},
                other_fixes=other_fixes, other_diffs=other_diffs, ignored=ign, unmatched=len(r["unmatched"]),
                applied=sum(1 for f in r["fixes"] if f["applied"]), tracked=r["tracked"], ok=r["ok"],
                checked=r["checked"], leaked=leaked, report13=r.get("report13", ""))


# ---------------------------------------------------------------------------- まとめ
def summarize(metas, before, after, route1=None) -> str:
    L = []
    w = L.append
    w(f"変更前: {before.get('version')}（{before.get('file')}）")
    w(f"変更後: {after.get('version')}（{after.get('file')}）")
    w("")
    w("| PDF | docx | 段落 | 照合 | 見つからない段落（前→後） | 直した箇所（前→後） | うち組版の文字による挿入・削除（前→後） | "
      "うちそれ以外の想定外（前→後） | わざと入れた違い（前／後） | 照合に使わなかった文字（後） | XML に入った受付日・ページ番号（前→後） |")
    w("|---|---|---|---|---|---|---|---|---|---|---|")
    evs = {}
    for name, meta in metas.items():
        eb = evaluate(meta, before["jobs"][name]) if name in before["jobs"] else {"error": "なし"}
        ea = evaluate(meta, after["jobs"][name]) if name in after["jobs"] else {"error": "なし"}
        evs[name] = (eb, ea)
        if "error" in eb or "error" in ea:
            w(f"| {meta['stem']} | {meta['variant']} | エラー | | | | | | |")
            continue

        def art(e):
            return sum(e["artifact"].values())

        def art_detail(e):
            return "・".join(f"{k}{v}" for k, v in e["artifact"].items()) or "0"

        cats = {}
        for _, _, k in ea["ignored"]:
            cats[k] = cats.get(k, 0) + 1
        def short(res):
            if res.startswith("見つからない段落"):
                return "見つからない段落"
            if res.startswith("誤"):
                return "誤"
            if res.startswith("直った"):
                return "直"
            if "why" in res:
                return "why"
            if "ignored" in res:
                return "ign"
            return "なし" if res.startswith("違いにならない") else "不"

        intended = "・".join(f"{x['name']} {short(x['result'])}／{short(y['result'])}"
                            for x, y in zip(eb["intended"], ea["intended"]))
        w(f"| {meta['stem']} | {meta['variant']} | {len(meta['paragraphs'])} | {ea['checked']} | "
          f"{eb['unmatched']}→{ea['unmatched']} | {eb['applied']}→{ea['applied']} | "
          f"{art(eb)}（{art_detail(eb)}）→{art(ea)}（{art_detail(ea)}） | "
          f"{sum(1 for f in eb['other_fixes'] if not f['artifact'])}→{sum(1 for f in ea['other_fixes'] if not f['artifact'])} | "
          f"{intended} | "
          f"{len(ea['ignored'])}（{'・'.join(f'{k}{v}' for k, v in cats.items()) or 'なし'}） | "
          f"{len(eb['leaked'])}→{len(ea['leaked'])} |")
    w("")
    w("わざと入れた違い: 直＝直った / why＝直さず、fixable=False（HEAD_WHY）で 13.2 に出た / ign＝足さず、照合に使わなかった文字"
      "（13.6）に出た / なし＝違いにならなかった（足さず、どこにも出ない） / 見つからない段落＝段落が PDF の中に見つからず照合"
      "されなかった（13.5 に出る） / 誤＝PDF の別の文字で直した / 不＝直さなかった")
    w("")
    for name, meta in metas.items():
        eb, ea = evs[name]
        w(f"## {meta['stem']}（{meta['variant']}）")
        if "error" in eb or "error" in ea:
            w("前: " + eb.get("error", "")[-800:])
            w("後: " + ea.get("error", "")[-800:])
            continue
        w(f"- 不変性・最終・DTD・J-STAGE: 前 {eb['ok']} / 後 {ea['ok']}。変更履歴（挿入, 削除）: 前 {eb['tracked']} / 後 {ea['tracked']}")
        w("- わざと入れた違い（期待は変更後のもの）:")
        for x, y in zip(eb["intended"], ea["intended"]):
            w(f"  - {y['name']} p{y['page']}:{y['line']} {y['kind']}: 前 {x['result']} / 後 {y['result']}"
              f"（期待: {y['expect']}）")
        for tag, e in (("前", eb), ("後", ea)):
            if e["artifact_fixes"]:
                w(f"- 組版の文字による挿入・削除（{tag}）:")
                for k, v in e["artifact_fixes"].items():
                    for src, old, new in v:
                        w(f"  - {k}: {src} 「{old[:30]}」→「{new[:50]}」")
            others = [f for f in e["other_fixes"] if not f["artifact"]]
            if others:
                w(f"- それ以外の直した箇所（{tag}）: {len(others)}")
                for f in others[:12]:
                    w(f"  - {f['src']} {f['kind']} 「{f['old'][:30]}」→「{f['new'][:40]}」")
            nf = [x for x in e["other_diffs"] if not x["fixable"]]
            if nf:
                w(f"- 直さない違い（{tag}。わざと入れたものを除く）: {len(nf)}")
                for x in nf[:8]:
                    w(f"  - {x['src']} 「{x['docx'][:24]}」/「{x['pdf'][:40]}」 why={x.get('why', '')[:12]}"
                      f" {x['artifact']}")
            if e["leaked"]:
                w(f"- XML に入った組版の文字（{tag}）: {e['leaked']}")
        w(f"- 照合に使わなかった PDF の文字（後）: {len(ea['ignored'])}")
        for s, t, k in ea["ignored"]:
            w(f"  - {s} [{k}] 「{t[:50]}」")
        if route1 and name in route1:
            r1 = route1[name]
            w(f"- ルート1 の照合に使わなかった文字（後）: {len(r1['ignored'])}"
              f"（ルート2 と同じ: {sorted((t for _, t, _ in r1['ignored'])) == sorted((t for _, t, _ in ea['ignored']))}）")
        sec = [ln for ln in ea["report13"].splitlines() if ln.startswith("### 13.")]
        w(f"- レポート 13 章の節（後）: {sec}")
        w("")
    return "\n".join(L)


def run_worker(src_root, jobs, out_json):
    jp = OUT / f"jobs_{out_json.stem}.json"
    jp.write_text(json.dumps(jobs, ensure_ascii=False, indent=1), encoding="utf-8")
    subprocess.run([sys.executable, "-I", str(Path(__file__).resolve()), "--worker", str(src_root), str(jp),
                    str(out_json)], check=True)
    return json.loads(out_json.read_text(encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--worker", nargs=3)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--before-src")
    ap.add_argument("--route1", action="store_true")
    a = ap.parse_args()
    if a.worker:
        worker(*a.worker)
        return
    OUT.mkdir(exist_ok=True)
    (OUT / "docx").mkdir(exist_ok=True)
    metas, jobs = {}, {"before": [], "after": [], "route1": []}
    for stem, spec in SPECS.items():
        if a.only and stem not in a.only:
            continue
        for variant in VARIANTS[stem]:
            art = Article(stem, spec, variant)
            name = f"{stem}_{variant}"
            path = art.write_docx(OUT / "docx" / f"{name}.docx")
            metas[name] = art.meta()
            for tag in ("before", "after"):
                jobs[tag].append(dict(name=name, docx=str(path), pdf=str(PDF_DIR / f"{stem}.pdf"), route="pdf",
                                      out_dir=str(OUT / f"run_{tag}" / name)))
            jobs["route1"].append(dict(name=name, docx=str(path), pdf=str(PDF_DIR / f"{stem}.pdf"), route="docx",
                                       out_dir=str(OUT / "run_route1" / name)))
    (OUT / "meta.json").write_text(json.dumps(metas, ensure_ascii=False, indent=1), encoding="utf-8")
    made = False
    before_src = a.before_src
    if not before_src:
        if not WT.exists():
            subprocess.run(["git", "-C", str(REPO), "worktree", "add", "--detach", str(WT), "HEAD"], check=True,
                           capture_output=True)
            made = True
        before_src = str(WT / "src")
    try:
        before = run_worker(before_src, jobs["before"], OUT / "results_before.json")
    finally:
        if made and not a.keep:
            subprocess.run(["git", "-C", str(REPO), "worktree", "remove", "--force", str(WT)], check=True)
    after = run_worker(str(REPO / "src"), jobs["after"], OUT / "results_after.json")
    route1 = None
    if a.route1:
        r1 = run_worker(str(REPO / "src"), jobs["route1"], OUT / "results_route1.json")
        route1 = {n: evaluate(metas[n], r) for n, r in r1["jobs"].items()}
    text = summarize(metas, before, after, route1)
    (OUT / "summary.txt").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
