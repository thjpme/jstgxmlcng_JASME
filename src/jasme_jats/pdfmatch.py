"""出版版 PDF との照合（docx の段落の文字と、記事の PDF の文字を段落ごとに突き合わせる）。

PDF は著者校正を経た最終版なので、XML の本文が PDF と違えば、J-STAGE には同じ記事の 2 つの版が並ぶことになる。
受け取った docx が校正後の最終版とは限らない（組版で印刷所がかっこ・句読点を全角にそろえる、校正の直しが docx に
戻されていない、など）ため、docx の段落ごとに PDF の中の対応する箇所を探して比べ、違いを次のように分ける。

  ・英数字・記号の全角・半角だけの違い（width）と、その文字のすぐ前後の空白で PDF にないもの（drops）
  ・それ以外の文字の違い（diffs。「資料」と「付録」など）
  ・PDF の中に見つからない段落（unmatched）
  ・Word が付ける番号（自動段落番号・脚注番号）の全角・半角の違い（numbers）

ルート1（docx から作る）では、照合の結果をレポートに載せるだけで、文字は変えない。
ルート2（出版版 PDF に合わせてから作る）では、この結果から、PDF に合わせて直した docx（Word の変更履歴つき）を作り
（pdfdocx.py）、それをルート1 と同じ処理で XML にする。Word が付ける番号は docx の文字ではないので、変換のときに
全角・半角を PDF に合わせる（plan.pdf_numbers）。

PDF から XML を作るのではない（構造はすべて docx のスタイルから決める）。PDF から取り出した文字には組版の都合
（両端そろえの空白、行末のハイフン、図の中の文字、数式、柱）が混じるため、空白は照合に使わず、段落ごとに PDF の中の
対応する箇所を探してから比べる。

PDF には、組版で入る docx にない文字（ページ番号・誌名の行・柱・投稿受付日など）や、docx では画像・Word の表になっている
図・表の中の文字もある。段落の途中にあると、PDF にだけある文字として違いになり、ルート2 では docx に足されてしまうので、
次のように扱う（pdf_stream）。

  ・ページ番号（各ページの最初か最後の行の数字だけの行で、ページの順に番号が続いているもの。1 ページに 1 つ）と、ページの
    端の行にある、3 ページ以上に同じ文字列で現れる 8 文字以上の行（柱）は、列から除く
  ・ページの端の行（ページ番号を除いた後の、各ページの最初の 2 行と最後の 2 行）、ページの途中の数字だけの行・何ページにも
    出る行、短い行（MIN_CHARS 文字未満）は「柱の候補の行」とし、その行のどの文字もどの段落にも当たらなければ、その行の
    文字は照合に使わない
  ・ページの途中の数字だけの行（表のセルなど。引用文献の「pp.11-」の改行の後の「16」のような、前の行の続きを除く）と
    何ページにも出る行は、全体の照合と照合の窓の大きさには数えず、段落の照合では行全体でしか docx の文字と一致させない
    （PdfStream.line_only。表の数字が docx の数字と偶然 1 文字だけ一致して、その行の文字が docx に入らないように）
  ・投稿受付日などの文字（RE_RECEIVED）は、ページのどこにあっても、どの段落にも当たらなければ照合に使わない（文字ごと）

照合に使わなかった文字のうち、段落の違いの範囲の中にあったものを記録する（ignored_lines。レポートの 13 章）。PDF の側に
照合に使わない文字しかない位置の docx の文字は、直さない（TextDiff.why）。照合に使わない文字を除いた残りが、どの段落の文字とも
一致しない行の文字（docx にない図・表の中の文字など）だけのときも同じで、その文字で docx を直さず、docx に足さない。
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from .model import OBJ

FW_FIRST, FW_LAST = 0xFF01, 0xFF5E   # 全角の英数字・記号（！〜～）。半角の 0x21〜0x7E と 1 対 1 に対応する
SKIP = ""        # docx の数式・画像・脚注番号・自動番号（docx の文字ではない、または PDF と文字で比べられないもの）
SEP = ""         # 段落の区切り
SOFT = {"￾", "­", "\x02"}   # PDF の行末のハイフン（ソフトハイフン）
MIN_CHARS = 4          # これより短い段落は照合しない（短すぎて PDF の中の位置を決められない）
MIN_COVERAGE = 0.85    # 段落の文字のうち PDF と一致した割合がこれ以上なら「照合できた」とする
# ページ番号の行（数字だけ、かっこ付きの「（25）」、ダッシュで挟んだ「－ 1 －」「- 1 -」）。ページの最初か最後の行にあるときだけ
# ページ番号として除く（ページの途中の数字だけの行は、引用文献の「pp.11-」の後の「16」や表のセルのことがある。pdf_stream）
RE_PAGE_NO = re.compile(r"^[\s　]*(?:[(（]?[0-9０-９]{1,4}[)）]?|[-－‐−–—―][\s　]*[0-9０-９]{1,4}[\s　]*[-－‐−–—―])[\s　]*$")
# 数字だけの行を、前の行の続き（引用文献の「pp.11-」の改行の後の「16」、「第29号，」の後の「2018」など）とみなす、前の行の
# 最後の文字。続きの行は、ページの途中でも普通の行と同じに照合する（表のセルの数字とは扱いを分ける）
CONTINUED_AFTER = tuple("-－‐−–—―~～〜,，、")
RE_ALNUM = re.compile(r"[0-9A-Za-z]")
# 投稿受付・採用決定などの日付。本誌（全国数学教育学会誌『数学教育学研究』）の出版版 PDF では 1 ページ目に組版で入り、docx には
# 普通ない。本文の行の後ろにつながったり、ページの途中で 2 行にわたったりする。形は「2025年８月31日投稿受付，2025年11月24日
# 採用決定」「2025年２月27日投稿受付，2025年７月30日再投稿受付，」（改行）「2025年10月10日採用決定」（数字は全角・半角）と、
# 古い号のかっこ付きの「（2025.11.30受理）」（日付は例）。かっこのない「受付」「受理」は、本文の日付（「…日受付分」など）にも
# 当たるので、かっこ付きの形でだけ認める
_DIGIT = "[0-9０-９]"
_DATE_JA = rf"{_DIGIT}{{4}}\s*年\s*{_DIGIT}{{1,2}}\s*月\s*{_DIGIT}{{1,2}}\s*日"
_DATE_DOT = rf"{_DIGIT}{{4}}\s*[.．]\s*{_DIGIT}{{1,2}}\s*[.．]\s*{_DIGIT}{{1,2}}"
_RECEIVED = rf"{_DATE_JA}\s*(?:再投稿受付|投稿受付|採用決定)"                               # 本誌の 1 ページ目の形
_RECEIVED_OLD = rf"(?:{_DATE_JA}|{_DATE_DOT})\s*(?:再投稿受付|投稿受付|採用決定|受付|受理)"   # かっこの中の形
_RECEIVED_SEP = r"\s*[，,、]?\s*"          # 日付と日付の間（読点と、空白・改行）
RE_RECEIVED = re.compile(rf"{_RECEIVED}(?:{_RECEIVED_SEP}{_RECEIVED})*"
                         rf"|[（(]\s*{_RECEIVED_OLD}(?:{_RECEIVED_SEP}{_RECEIVED_OLD})*\s*[）)]")
# ルート2 で直さない理由（PDF の側に、照合に使わなかった文字〈柱・投稿受付日など。どの段落とも一致しない行の文字を含む〉しか
# ない位置の docx の文字）
HEAD_WHY = ("PDF のこの位置には、照合に使わなかった文字（誌名の行・柱・投稿受付日・表や図の中の文字など。13 章の最後の一覧）"
            "しかなく、どう直すか決められない。PDF のその位置の本文と見比べ、docx が違っていれば手で直してから変換し直す")


def fold(c: str) -> str:
    """全角の英数字・記号を半角にする（それ以外の文字はそのまま。文字数は変わらない）。"""
    o = ord(c)
    return chr(o - 0xFEE0) if FW_FIRST <= o <= FW_LAST else c


def key(c: str) -> str:
    """照合（位置合わせ）に使う文字: 全角・半角と大文字・小文字の違いを無視する（違いの判定は元の文字で行う）。"""
    return fold(c).lower()


def is_width_pair(a: str, b: str) -> bool:
    """a と b が、英数字・記号の全角と半角の違いだけか。"""
    return len(a) == len(b) == 1 and a != b and fold(a) == fold(b) and 0x21 <= ord(fold(a)) <= 0x7E


@dataclass
class TextDiff:
    src: str
    docx: str        # docx の文字（違う部分）
    pdf: str         # PDF の文字（違う部分。単語の間の空白は戻してある。直せない理由 why のあるものは、行の変わり目に「／」）
    context: str     # docx の前後の文字
    start: int = 0   # docx の段落（plain）の中の範囲 [start, end)。PDF にだけある文字なら start == end（その位置に足す）
    end: int = 0
    fixable: bool = True   # ルート2 で docx を直せるか（数式・Word が付ける番号・リンクの文字にかかるものは直さない）
    why: str = ""    # 直せない理由（ルート2 のレポートに出す）。空なら pdfdocx.plan_fixes の決まった文言


@dataclass
class PdfCheck:
    ok: bool = True                 # PDF の文字を読めたか
    message: str = ""               # 読めなかった理由など
    checked: int = 0                # 照合した段落の数
    unmatched: list = field(default_factory=list)   # PDF の中に見つからなかった段落の src
    width: dict = field(default_factory=dict)       # src -> {plain 上の位置: PDF の文字}
    drops: dict = field(default_factory=dict)       # src -> {plain 上の位置（落とす空白）}
    diffs: list = field(default_factory=list)       # TextDiff
    numbers: dict = field(default_factory=dict)     # Word が付ける番号: (種類, 段落 ID または脚注 ID) -> {番号の中の位置: PDF の文字}
    original: dict = field(default_factory=dict)    # Word が付ける番号の元の文字列: (種類, ID) -> 文字列
    # 種類: auto（段落の自動番号。ID は段落）/ fnref（本文の脚注番号）/ fnlist（注の一覧の脚注番号。ID は Word の脚注 ID）
    # 組版で入る文字（誌名の行・柱・投稿受付日など）や図・表の中の文字とみなして照合に使わなかった PDF の文字:
    # [(段落 ID, 行または投稿受付日の文字列)]。
    # 段落の違いの範囲（段落の途中の、PDF にだけある文字と、docx の文字と違う PDF の文字）から実際に除いたものだけ（重複なし）。
    # 段落の切れ目（段落の前後）や数式などの位置にあるものは、もともと違いにならないので載せない
    ignored_lines: list = field(default_factory=list)

    @property
    def number_edits(self) -> dict:
        """Word が付ける番号を PDF に合わせたもの: (種類, ID) -> 出力する文字列（ルート2 で使う）。"""
        return {k: "".join(m.get(i, c) for i, c in enumerate(self.original[k])) for k, m in self.numbers.items()}

    @property
    def width_count(self) -> int:
        return sum(len(v) for v in self.width.values())

    @property
    def drop_count(self) -> int:
        return sum(len(v) for v in self.drops.values())


# ---------------------------------------------------------------------------- PDF の文字
def extract_pages(pdf_path) -> list:
    """PDF の各ページの文字（pypdfium2）。"""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        return [doc[i].get_textpage().get_text_range() for i in range(len(doc))]
    finally:
        doc.close()


@dataclass
class PdfStream:
    """PDF の本文の文字の列（空白を除いたもの）と、各文字の前の空白・改行、各文字の行。

    ページ番号（各ページの最初か最後の行の数字だけの行で、ページの順に番号が続いているもの。1 ページに 1 つ）と、
    ページの端の行にある、3 ページ以上に同じ文字列で現れる 8 文字以上の行（柱）は、列に入れない（pdf_stream）。
    柱の候補の行（head）と投稿受付日などの文字（date）は列に入れたまま印を付け、どの段落にも当たらなければ照合に使わない
    （ignored）。ページの途中の数字だけの行（前の行の続きを除く）と何ページにも出る行（line_only。0.19.0 では列から
    除いていた行）は、全体の照合と照合の窓の大きさに数えず、段落の照合では行全体でしか docx の文字と一致させない（compare）。
    """
    chars: list = field(default_factory=list)
    space_before: list = field(default_factory=list)    # 前に空白（改行以外）がある
    newline_before: list = field(default_factory=list)  # 前に改行がある
    soft: list = field(default_factory=list)            # 行末のハイフン（照合で無視してよい文字）
    line: list = field(default_factory=list)            # 各文字の行の番号（lines の位置。列に入れた行だけを数える）
    lines: list = field(default_factory=list)           # 行の文字列（目に見えない文字と前後の空白を除いたもの。レポートに出す）
    edge: list = field(default_factory=list)            # 各文字の行が、ページの端の行（ページ番号を除いた後の、空でない
    #                                                     最初の 2 行と最後の 2 行）か
    head: list = field(default_factory=list)            # 各文字の行が、柱の候補の行（ページの端の行、ページの途中の数字だけの
    #                                                     行、3 ページ以上に同じ文字列で現れる 8 文字以上の行、短い行）か
    line_only: list = field(default_factory=list)       # 各文字の行が、行全体でしか docx の文字と一致させない行（ページの途中の
    #                                                     数字だけの行〈前の行の続きを除く〉、何ページにも出る行）か
    date: list = field(default_factory=list)            # 各文字が投稿受付日などの文字（RE_RECEIVED）なら dates の位置、違えば -1
    dates: list = field(default_factory=list)           # 投稿受付日などの文字列（空白・改行を除いたもの）

    @property
    def keys(self) -> str:
        return "".join(key(c) for c in self.chars)

    def ignored(self, k: int, owner, owned_lines) -> str:
        """k 番目の文字を、組版で入る文字（誌名の行・柱・投稿受付日など）や図・表の中の文字とみなして照合に使わないなら、
        その行（投稿受付日などの文字なら、その日付）の文字列。照合に使うなら空文字。

        owner: どれかの段落に当たった文字の位置（compare）。owned_lines: どれかの段落に当たった文字のある行の番号。
        投稿受付日などの文字は文字ごとに、柱の候補の行は行ごとに、どの段落にも当たらないものを照合に使わない
        （docx に同じ文字の段落があれば、その段落に当たるので普通に照合される）。
        """
        if k in owner:
            return ""
        if self.date[k] >= 0:
            return self.dates[self.date[k]]
        if self.head[k] and self.line[k] not in owned_lines:
            return self.lines[self.line[k]]
        return ""


def _visible(line: str) -> bool:
    """行に、列に入る文字（空白・制御文字以外）があるか。"""
    return any(not c.isspace() and (unicodedata.category(c) not in ("Cc", "Cf", "Cn") or c in SOFT) for c in line)


def _shown(line: str) -> str:
    """行の目に見える文字（制御文字・行末のハイフンの印〈U+FFFE など〉を除き、前後の空白を除いたもの。レポートに出す）。"""
    return "".join(c for c in line.replace("\t", " ") if unicodedata.category(c) not in ("Cc", "Cf", "Cn")).strip()


def _page_numbers(page_lines) -> list:
    """各ページのページ番号の行の位置（なければ None）。

    候補は、ページの空でない最初の行と最後の行のうち、数字だけの行（RE_PAGE_NO）。その数とページの順番（何ページ目か）の
    差が、ほかのページの候補と同じもの（ページの順に番号が続いているもの）を選ぶ（ページの最後か最初にある、引用文献の
    「pp.11-」の後の「16」や表の数字を、ページ番号と取り違えないため。本誌の PDF では、すべてのページの最初の行の「（25）」）。
    番号が続いている候補がどのページにもない（1 ページだけの PDF など）ときは、最初の行、それがなければ最後の行の候補を選ぶ。
    """
    cands = []           # ページごとの [(行の位置, 番号とページの順番の差)]
    for n, ls in enumerate(page_lines):
        shown = [i for i, x in enumerate(ls) if _visible(x)]
        cands.append([(i, int(re.sub(r"[^0-9]", "", unicodedata.normalize("NFKC", ls[i]))) - n)
                      for i in dict.fromkeys(shown[:1] + shown[-1:]) if RE_PAGE_NO.match(ls[i])])
    votes = Counter(d for c in cands for d in {d for _, d in c})
    if not any(v >= 2 for v in votes.values()):
        return [c[0][0] if c else None for c in cands]
    out = []
    for c in cands:
        good = [(votes[d], -k, i) for k, (i, d) in enumerate(c) if votes[d] >= 2]
        out.append(max(good)[2] if good else None)
    return out


def _visible_count(line: str) -> int:
    """行の目に見える文字の数（空白・制御文字・行末のハイフンの印を除く）。"""
    return sum(1 for c in line if not c.isspace() and unicodedata.category(c) not in ("Cc", "Cf", "Cn"))


def pdf_stream(pages) -> PdfStream:
    """PDF の各ページの文字（extract_pages）から、照合に使う文字の列を作る（PdfStream）。"""
    page_lines = [re.split(r"\r\n|\r|\n", p) for p in pages]
    # 柱: 3 ページ以上に同じ文字列で現れる 8 文字以上の行
    cnt = Counter(s for ls in page_lines for s in {x.strip() for x in ls} if len(s) >= 8)
    heads = {s for s, n in cnt.items() if n >= 3}
    kept = []          # 列に入れる行: (行の文字列, ページの端の行か, 柱の候補の行か, 行全体でしか一致させない行か)
    prev = ""          # 直前に列に入れた、空でない行の目に見える文字（数字だけの行が前の行の続きかを見る）
    for ls, page_no in zip(page_lines, _page_numbers(page_lines)):
        shown = [i for i, x in enumerate(ls) if _visible(x)]
        rest = [i for i in shown if i != page_no]
        edge = set(rest[:2] + rest[-2:])
        for i, ln in enumerate(ls):
            if i == page_no or (i in edge and ln.strip() in heads):
                continue           # ページ番号と、ページの端の柱
            # ページの途中の数字だけの行・何ページにも出る行は、引用文献や表の文字のことがあるので、除かずに柱の候補にする。
            # 短い行（図の中の点の名前・軸のラベル、表の短いセルなど）も柱の候補にする（本文の短い行は段落の最後にしかなく、
            # 段落に当たる）
            digits = bool(RE_PAGE_NO.match(ln))
            repeated = ln.strip() in heads
            head = i in edge or digits or repeated or 0 < _visible_count(ln) < MIN_CHARS
            # 前の行の続きでない数字だけの行と、何ページにも出る行（0.19.0 では列から除いていた行）は、行全体でしか一致させない
            kept.append((ln, i in edge, head, (digits and not prev.endswith(CONTINUED_AFTER)) or repeated))
            if _visible(ln):
                prev = _shown(ln)
    text = "\n".join(ln for ln, *_ in kept)
    line_of = [n for n, (ln, *_) in enumerate(kept) for _ in range(len(ln) + 1)]     # text の各文字の行（+1 は改行）
    st = PdfStream(lines=[_shown(ln) for ln, *_ in kept])
    date_of = [-1] * len(text)
    for m in RE_RECEIVED.finditer(text):
        st.dates.append(re.sub(r"\s+", "", m.group()))
        date_of[m.start():m.end()] = [len(st.dates) - 1] * (m.end() - m.start())
    sp = nl = False
    for k, c in enumerate(text):
        if c == "\n":
            nl = True
            continue
        if c.isspace():
            sp = True
            continue
        if unicodedata.category(c) in ("Cc", "Cf", "Cn") and c not in SOFT:
            continue             # 制御文字など（PDF の目に見えない文字）
        soft = c in SOFT
        if c in "-‐" and k + 1 < len(text) and text[k + 1] == "\n" and st.chars and RE_ALNUM.match(st.chars[-1]):
            soft = True          # 英単語の途中の改行のハイフン
        st.chars.append(c)
        st.space_before.append(sp)
        st.newline_before.append(nl)
        st.soft.append(soft)
        n = line_of[k]
        st.line.append(n)
        st.edge.append(kept[n][1])
        st.head.append(kept[n][2])
        st.line_only.append(kept[n][3])
        st.date.append(date_of[k])
        sp = nl = False
    return st


# ---------------------------------------------------------------------------- 照合
def _para_seq(p, fn_marks=None, list_marks=None):
    """段落の照合用の文字の列 [(文字, plain 上の位置)] と、Word が付ける番号の文字
    {列の位置: (種類, ID, 番号の中の位置, 番号のアトムの plain 上の位置（段落の自動番号は -1）)}。

    空白は除く。数式・画像は SKIP。Word が付ける番号（段落の自動番号、本文の脚注番号、注の一覧の脚注番号）は、
    出力する文字を列に入れ、plain 上の位置は -1 とする。fn_marks: Word の脚注 ID -> 本文・注の一覧に出力する番号。
    list_marks: 注の一覧の最初の段落 ID -> Word の脚注 ID。
    """
    fn_marks, list_marks = fn_marks or {}, list_marks or {}
    seq, gens = [], {}

    def number(kind, ident, text, apos):
        for k, c in enumerate(text):
            if not c.isspace():
                gens[len(seq)] = (kind, ident, k, apos)
                seq.append((c, -1))

    number("auto", p.src, p.autonum or "", -1)
    pos = 0
    for a in p.atoms:
        if a.kind == "text":
            for k, ch in enumerate(a.text):
                if not ch.isspace():
                    seq.append((ch, pos + k))
            pos += len(a.text)
            continue
        if a.kind == "fnref" and a.fn_kind == "footnote" and a.fn_id in fn_marks:
            number("fnref", a.fn_id, fn_marks[a.fn_id], pos)
        elif a.kind == "gen" and a.fn_kind == "mark" and p.src in list_marks and list_marks[p.src] in fn_marks:
            number("fnlist", list_marks[p.src], fn_marks[list_marks[p.src]], pos)
        elif a.kind != "gen":
            seq.append((SKIP, pos))
        pos += 1
    return seq, gens


def _locked_positions(p) -> set:
    """全角・半角を変えない位置（URL・DOI などのリンクの文字。表示とリンク先がずれないように）。"""
    out = set()
    pos = 0
    for a in p.atoms:
        n = len(a.text) if a.kind == "text" else 1
        if a.href or (a.link is not None and a.link.kind in ("uri", "ext-link", "pub-id")):
            out.update(range(pos, pos + n))
        pos += n
    return out


def target_paragraphs(plan) -> list:
    """照合する段落: 題目・本文・見出し・キャプション・注・付記・謝辞・引用文献・英文要旨（表のセル・別行数式・資料は除く）。"""
    from .linker import body_paragraphs
    out = []
    for p in list(plan.title) + list(plan.subtitle) + list(plan.title_en) + list(plan.subtitle_en):
        out.append(p)
    for p, where in body_paragraphs(plan):
        if where not in ("cell", "formula"):
            out.append(p)
    seen = set()
    return [p for p in out if not (p.src in seen or seen.add(p.src))]


def compare(plan, pages, fn_marks=None) -> PdfCheck:
    """docx の段落と PDF の文字を照合する。pages は PDF の各ページの文字（extract_pages）。

    fn_marks: Word の脚注 ID -> 出力する脚注番号（builder.word_note_marks）。Word の脚注番号も PDF と照合する。
    段落の途中にある柱・投稿受付日・図や表の中の文字など（どの段落にも当たらない、ページの端の行など）は照合に使わず、
    res.ignored_lines に記録する（ページ番号は列から除く。pdf_stream）。
    """
    res = PdfCheck()
    fn_marks = fn_marks or {}
    list_marks = {fn.paras[0].src: fn.word_id for fn in plan.fns if fn.word_note and fn.paras}
    st = pdf_stream(pages)
    pf = st.keys
    if not pf:
        res.ok = False
        res.message = "PDF から文字を取り出せなかった（画像だけの PDF の可能性がある）"
        return res
    targets = {p.src for p in target_paragraphs(plan)}
    # 位置合わせには、照合しない段落（図の中の文字・表のセル・資料など）も docx の順で使う。PDF の文字のうち、
    # ほかの段落に当たった文字を「PDF にだけある文字」と数えないため
    paras = [(p, *_para_seq(p, fn_marks, list_marks)) for p in plan.paras.values()]
    paras = [(p, q, g) for p, q, g in paras if sum(1 for c, _ in q if c != SKIP) >= MIN_CHARS]
    # 1. 全体の照合で、段落ごとの PDF の中のおおよその位置を決める。行全体でしか一致させない行（ページの途中の数字だけの行・
    # 何ページにも出る行。0.19.0 では列から除いていた行）の文字は、全体の照合にも窓の大きさにも数えない（表の数字の行が
    # 段落を分断しても、窓が 0.19.0 より短くならないように。窓は core の上で決めてから、列の上の位置に戻す）
    core = [k for k in range(len(st.chars)) if not st.line_only[k]]
    pf_core = "".join(pf[k] for k in core)
    whole, spans = [], []
    for p, seq, _ in paras:
        start = len(whole)
        whole.extend(key(c) for c, _ in seq)
        spans.append((start, len(whole)))
        whole.append(SEP)
    d2p = [-1] * len(whole)
    sm = difflib.SequenceMatcher(None, "".join(whole), pf_core, autojunk=False)
    for a, b, n in sm.get_matching_blocks():
        for k in range(n):
            d2p[a + k] = b + k
    # 2. 段落ごとに、PDF の中の窓と照合する
    aligned = {}
    owner = {}                 # PDF の文字の位置 -> その文字に当たった段落
    for (p, seq, gens), (s, e) in zip(paras, spans):
        window = _window(seq, d2p[s:e], pf_core)
        if window:
            window = tuple(core[x] if x < len(core) else len(st.chars) for x in window)
        ops = _align(seq, st, window) if window else None
        if ops is None:
            continue
        aligned[p.src] = (p, seq, gens, window[0], ops)
        for tag, i1, i2, j1, j2 in ops:
            if tag == "equal":
                for k in range(j2 - j1):
                    owner.setdefault(window[0] + j1 + k, p.src)
    # どれかの段落に当たった文字のある行（柱の候補の行のうち、これに入らない行の文字は照合に使わない）
    owned_lines = {st.line[g] for g in owner}
    # 3. 照合する段落の違いを分類する
    for p, seq, gens in paras:
        for (kind, ident, k, _) in gens.values():
            res.original.setdefault((kind, ident), (p.autonum or "") if kind == "auto" else fn_marks[ident])
        if p.src not in targets:
            continue
        res.checked += 1
        if p.src not in aligned:
            res.unmatched.append(p.src)
            continue
        _classify(*aligned[p.src], st, owner, owned_lines, res)
    return res


def _window(seq, mapped, pf):
    """段落を照合する PDF の範囲 (lo, hi)。見つからなければ None。

    mapped は段落の各文字の pf の上の位置（全体の照合で見つからなければ -1）。compare では、pf に行全体でしか一致させない
    行の文字を除いたもの（pf_core）を渡す。
    """
    n = len(seq)
    hits = [(i, j) for i, j in enumerate(mapped) if j >= 0]
    real = sum(1 for c, _ in seq if c != SKIP)
    if len(hits) >= 0.5 * real:
        (i0, j0), (i1, j1) = hits[0], hits[-1]
        if j1 - j0 <= 3 * n + 80:     # 段落がまとまって見つかっている
            return max(0, j0 - i0 - 6), min(len(pf), j1 + (n - i1) + 60)
    # 全体の照合で見つからない（段落の順序が PDF と違うなど）: 段落の一部の文字列を PDF の中で探す
    text = "".join(key(c) for c, _ in seq)
    for k in (24, 16, 10, len(text)):       # 短い段落（見出しなど）は全体で探す
        if len(text) < k or k < MIN_CHARS:
            continue
        for off in (0, max(0, len(text) // 2 - k // 2), len(text) - k):
            piece = text[off:off + k]
            if SKIP in piece:
                continue
            at = pf.find(piece)
            if at >= 0 and pf.find(piece, at + 1) < 0:
                start = at - off
                return max(0, start - 6), min(len(pf), start + n + 60)
    return None


def _align(seq, st: PdfStream, window):
    """段落と PDF の窓の照合（difflib の opcodes）。一致した文字が少なければ None。

    行全体でしか一致させない行（PdfStream.line_only。表のセルの数字の行など）の文字は、docx のどの文字とも一致しないものと
    して照合し、docx の文字がその行の文字とまったく同じに続くときだけ、行全体で一致させる（_whole_lines）。表のセルの「31」
    「27」の「1」「2」が docx の「12」と偶然一致して、その行の残りの文字が docx に入らないように。
    """
    lo, hi = window
    d = "".join(key(c) for c, _ in seq)
    keys = [key(c) for c in st.chars[lo:hi]]
    w = [None if st.line_only[lo + j] else c for j, c in enumerate(keys)]     # None はどの文字とも一致しない
    ops = _whole_lines(_opcodes(d, w), d, w, keys, st, lo)
    real = sum(1 for c, _ in seq if c != SKIP)
    same = sum(i2 - i1 for t, i1, i2, _, _ in ops if t == "equal")
    return ops if same >= MIN_COVERAGE * real else None


def _opcodes(d, w, i0=0, j0=0) -> list:
    """d[i0:] と w[j0:] の照合（difflib の opcodes。位置は d・w の上の位置に直したもの）。"""
    return [(t, i1 + i0, i2 + i0, j1 + j0, j2 + j0)
            for t, i1, i2, j1, j2 in difflib.SequenceMatcher(None, d[i0:], w[j0:], autojunk=False).get_opcodes()]


def _whole_lines(ops, d, w, keys, st: PdfStream, lo) -> list:
    """行全体でしか一致させない行（窓の中の w が None の文字。続いた行はまとめる）を、docx の文字がその行の文字とまったく
    同じに続くときだけ、行全体で一致（equal）にする。

    その行の直前の PDF の文字まで一致していて、docx の続きの文字がその行の文字とまったく同じで、さらに docx の段落がそこで
    終わるか、次の docx の文字がその行の次の PDF の文字と同じなら、その行を一致にして、後ろを照合し直す（引用文献の「p.」の
    改行の後の「16」、docx の表を本文に書いた段落の数字、引用文献の中の何ページにも出る行など）。その行のすぐ後ろから一致して
    いて、その前の docx の文字がその行の文字とまったく同じで、docx の段落がそこで始まるか、その前の docx の文字がその行の前の
    PDF の文字と同じときも同じ（前を照合し直す。段落の最初の行が、何ページにも出る表の見出しの行のときなど）。表のセルの「1」が、
    出版版で直された docx の「1回」（PDF では「２回」）の「1」と同じ文字でも、前後の文字が続かないので一致にしない。
    """
    runs = []
    j = 0
    while j < len(w):
        if w[j] is not None:
            j += 1
            continue
        k = j
        while k < len(w) and w[k] is None:
            k += 1
        a, b = lo + j, lo + k
        if (a == 0 or st.line[a - 1] != st.line[a]) and (b == len(st.chars) or st.line[b] != st.line[b - 1]):
            runs.append((j, k))           # 行の途中で窓が切れていないものだけ
        j = k
    done = 0                              # ops[:done] は決まったもの（それより前は照合し直さない）
    for a, b in runs:
        n, text = b - a, "".join(keys[a:b])
        i0, j0 = (ops[done - 1][2], ops[done - 1][4]) if done else (0, 0)
        if a < j0:
            continue
        at = next((x for x in range(done, len(ops)) if ops[x][0] == "equal" and ops[x][4] == a), None)
        if at is not None:                # 一致した文字に続く行
            i = ops[at][2]
            if d[i:i + n] == text and (i + n == len(d) or (b < len(w) and w[b] is not None and d[i + n] == w[b])):
                ops = ops[:at + 1] + [("equal", i, i + n, a, b)] + _opcodes(d, w, i + n, b)
                done = at + 2
                continue
        at = next((x for x in range(done, len(ops)) if ops[x][0] == "equal" and ops[x][3] == b), None)
        if at is not None:                # 一致した文字の前の行
            i = ops[at][1]
            if i - n >= i0 and d[i - n:i] == text and (i - n == 0 or (a > j0 and w[a - 1] is not None and d[i - n - 1] == w[a - 1])):
                mid = [(t, i1 + i0, i2 + i0, j1 + j0, j2 + j0) for t, i1, i2, j1, j2
                       in difflib.SequenceMatcher(None, d[i0:i - n], w[j0:a], autojunk=False).get_opcodes()]
                ops = ops[:done] + mid + [("equal", i - n, i, a, b)] + ops[at:]
                done += len(mid) + 1
    out = []
    for tag, i1, i2, j1, j2 in ops:       # 続いた一致はまとめる
        if tag == "equal" and out and out[-1][0] == "equal" and out[-1][2] == i1 and out[-1][4] == j1:
            _, i1, _, j1, _ = out.pop()
        out.append((tag, i1, i2, j1, j2))
    return out


def _classify(p, seq, gens, lo, ops, st: PdfStream, owner, owned_lines, res: PdfCheck):
    text = p.plain()
    locked = _locked_positions(p)
    d2w = {}          # seq の位置 -> PDF の文字の位置
    width = {}        # seq の位置 -> PDF の文字（全角・半角だけの違い）
    numbers = set()   # PDF に合わせた Word の番号の文字の seq の位置
    regions = []      # 違う部分 (i1, i2, j1, j2, 直せない理由)（seq と窓の中の位置）

    eq = [(j1, j2) for tag, _, _, j1, j2 in ops if tag == "equal"]
    first_eq, last_eq = eq[0][0], eq[-1][1] - 1      # 窓の中で最初・最後に一致した PDF の文字

    def mine(j):      # PDF の文字が、ほかの段落に当たっていない（この段落の違いとして扱ってよい）か
        return owner.get(lo + j, p.src) == p.src and not st.soft[lo + j]

    def used(j):      # mine で、照合に使わない文字（どの段落にも当たらない柱の候補の行・投稿受付日など）でもないか
        return mine(j) and not st.ignored(lo + j, owner, owned_lines)

    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            for k in range(i2 - i1):
                dc = seq[i1 + k][0]
                pc = st.chars[lo + j1 + k]
                d2w[i1 + k] = lo + j1 + k
                if dc == pc:
                    continue
                if is_width_pair(dc, pc):
                    if i1 + k in gens:          # Word が付ける番号
                        kind, ident, at, _ = gens[i1 + k]
                        res.numbers.setdefault((kind, ident), {})[at] = pc
                        numbers.add(i1 + k)
                    elif seq[i1 + k][1] not in locked:
                        width[i1 + k] = pc
                else:
                    regions.append((i1 + k, i1 + k + 1, j1 + k, j1 + k + 1, ""))   # 大文字・小文字の違い
            continue
        if tag == "insert" and (i1 == 0 or i1 == len(seq)):
            continue                     # 段落の前後の PDF の文字（別の段落など）
        js_all = [j for j in range(j1, j2) if mine(j)]
        # 段落の先頭・末尾の違いでは、最初・最後に一致した文字と同じ行の PDF の文字だけを使う
        # （前・後の行の文字は、照合しない短い段落（見出しの「註」など）や別の段落の文字の可能性が高い）
        if i1 == 0:
            js_all = [j for j in js_all if not any(st.newline_before[lo + x] for x in range(j + 1, first_eq + 1))]
        if i2 == len(seq):
            js_all = [j for j in js_all if not any(st.newline_before[lo + x] for x in range(last_eq + 1, j + 1))]
        # 照合に使わない文字（どの段落にも当たらない、ページの端の行・数字だけの行などと、投稿受付日など）を除く
        dropped = [st.ignored(lo + j, owner, owned_lines) for j in js_all]
        js = [j for j, d in zip(js_all, dropped) if not d]
        if any(dropped) and all(st.line[lo + j] not in owned_lines for j in js):
            # 残りが、どの段落の文字とも一致しない行の文字（docx にない図・表の中の文字や、照合に使わない短いセルの文字）だけ:
            # その文字で docx を直さない（ページの端の行を除いた残りの表の文字で、docx の文字を置き換えないように）
            js = []
        if not any(c != SKIP for c, _ in seq[i1:i2]):
            # docx の側に文字がない（数式・脚注番号は PDF では文字になっている）。PDF にだけある文字は、
            # 図の中の文字などの可能性が高い長いものは除く。長さは、照合に使わない文字を除く前の文字で数える（図の中の文字の
            # 行がページの端にかかって除かれても、残りを足さないように）。数字だけの行・何ページにも出る行は、行全体でしか
            # 一致させないので（_align）、表の数字が docx の文字と偶然一致して、その行の文字を足すこともない
            if tag != "insert":
                continue
            _ignore(res, p.src, dropped)
            if not js or len(js_all) >= 20:
                continue
        else:
            _ignore(res, p.src, dropped)
            if js_all and not js:
                # PDF のこの位置には、照合に使わない文字（と、どの段落とも一致しない行の文字）しかない:
                # docx の文字を消す（直す）ことにはしない
                regions.append((i1, i2, js_all[0], js_all[-1] + 1, HEAD_WHY))
                continue
        regions.append((i1, i2, js[0] if js else j1, js[-1] + 1 if js else j1, ""))
    _report_regions(p, seq, gens, st, lo, regions, mine, used, locked, res)
    if width:
        res.width[p.src] = {seq[i][1]: c for i, c in width.items()}
    drops = set()
    for i in set(width) | numbers:
        for j, k in ((i - 1, i), (i, i + 1)):          # 前の文字との間・後ろの文字との間
            if j < 0 or k >= len(seq) or j not in d2w or k not in d2w or d2w[k] != d2w[j] + 1:
                continue
            if j in gens and k in gens:
                continue
            # Word が付ける番号との間なら、番号のアトムの位置から（段落の自動番号は段落の先頭から）
            start = gens[j][3] + 1 if j in gens else seq[j][1] + 1
            end = gens[k][3] if k in gens else seq[k][1]
            gap = range(start, end)
            if not gap or not all(text[x].isspace() for x in gap):
                continue
            pk = d2w[k]
            if not _pdf_space(st, pk):
                drops.update(x for x in gap if x not in locked)
    if drops:
        res.drops[p.src] = drops


def _ignore(res: PdfCheck, src, dropped):
    """照合に使わなかった PDF の文字（柱の候補の行・投稿受付日など。PdfStream.ignored の文字列）を、段落ごとに重複なしで記録する。"""
    for d in dropped:
        if d and (src, d) not in res.ignored_lines:
            res.ignored_lines.append((src, d))


def _pdf_space(st: PdfStream, k: int, prev: int = None) -> bool:
    """PDF の k 番目の文字の前に、本物の空白があるか。

    和文の文字（全角の記号を含む）の隣に PDF で見える空白は、両端そろえや字間の調整による見かけのものなので、空白とみなさない。
    前後がどちらも英文の文字（半角の英数字・記号、アクセント付きの文字、’ “ ” – などの記号）のとき（英文の単語の間）だけ、
    空白（行の折り返しを含む）とみなす。prev: 前の文字の位置（k - 1 の文字を飛ばしたとき〈照合に使わない行の文字など〉に、
    表示する前の文字を渡す）。
    """
    prev = k - 1 if prev is None else prev
    if prev < 0 or not (st.space_before[k] or st.newline_before[k]):
        return False
    return _latin(st.chars[prev]) and _latin(st.chars[k])


def _latin(c: str) -> bool:
    o = ord(c)
    return o < 0x250 or 0x2010 <= o <= 0x2027


def _report_regions(p, seq, gens, st: PdfStream, lo, regions, mine, used, locked, res: PdfCheck, near=12):
    """違う部分を、近いものどうしまとめて TextDiff にする。

    mine: PDF の文字が、ほかの段落に当たっていないか。used: さらに、照合に使わない文字（柱の候補の行・投稿受付日など）でも
    ないか。PDF の文字は used の文字だけを使う。ただし、PDF の側に照合に使わない文字しかない部分（直せない理由 why の
    あるもの）は、直さない（fixable=False）ので、表示のために mine の文字をすべて載せ、行の変わり目に「／」を入れる
    （受付日の後ろに続く本文の行を見分けられるように）。直せない理由のある部分は、ほかの部分とまとめない（近くの直せる
    違いまで直さないことにならないように）。
    """
    merged = []
    for r in sorted(regions):
        if merged and r[4] == merged[-1][4] and r[0] - merged[-1][1] <= near and r[2] - merged[-1][3] <= near:
            m = merged[-1]
            merged[-1] = (m[0], max(m[1], r[1]), m[2], max(m[3], r[3]), m[4])
        else:
            merged.append(r)
    text = p.plain()
    for i1, i2, j1, j2, why in merged:
        pos = [q for _, q in seq[i1:i2] if q >= 0]
        anchor_ok = True
        if pos:
            a, b = pos[0], pos[-1] + 1
        else:                                   # docx の側に文字がない（PDF にだけある）: 直前の docx の文字の後に足す
            prev = seq[i1 - 1] if i1 > 0 else None
            anchor_ok = prev is not None and prev[1] >= 0 and prev[0] != SKIP and (i1 - 1) not in gens
            a = b = (prev[1] + 1) if anchor_ok else max([q + 1 for _, q in seq[:i1] if q >= 0] or [0])
        dtext = text[a:b].replace(OBJ, "")
        num = "".join(seq[i][0] for i in range(i1, i2) if i in gens)
        if num:
            dtext = f"（Word が付けた番号「{num}」）" + dtext
        ptext = shown = ""    # PDF の文字（比べるもの）と、表示するもの
        last = None
        for j in range(j1, j2):
            if not (mine(j) if why else used(j)):
                continue
            g = lo + j
            if why and last is not None and st.line[g] != st.line[last]:
                shown += "／"           # 直せない部分は、行の変わり目を示す
            elif ptext and _pdf_space(st, g, last):
                ptext += " "          # 表示のために単語の間の空白を戻す（照合では空白を使わない）
                shown += " "
            ptext += st.chars[g]
            shown += st.chars[g]
            last = g
        if fold_str(re.sub(r"\s", "", (num + text[a:b].replace(OBJ, "")))) == fold_str(re.sub(r"\s", "", ptext)):
            continue
        ctx = (text[max(0, a - 12):a] + "［" + text[a:b] + "］" + text[b:b + 12]).replace(OBJ, "")
        fixable = not why and anchor_ok and not num and OBJ not in text[a:b] \
            and not any(SKIP == seq[i][0] for i in range(i1, i2)) and not any(x in locked for x in range(a, max(b, a + 1)))
        res.diffs.append(TextDiff(p.src, dtext, shown, ctx, a, b, fixable, why))


def fold_str(s: str) -> str:
    return "".join(fold(c) for c in s)


def check_pdf(plan, pdf_path, fn_marks=None) -> PdfCheck:
    """記事の PDF を読み、docx の段落と照合する。PDF を読めなければ ok=False（変換は続ける）。"""
    try:
        pages = extract_pages(pdf_path)
    except ImportError:
        return PdfCheck(ok=False, message="PDF の文字を読むための pypdfium2 が入っていない（pip install pypdfium2）")
    except Exception as e:  # noqa: BLE001
        return PdfCheck(ok=False, message=f"PDF を読めなかった: {e}")
    return compare(plan, pages, fn_marks)
