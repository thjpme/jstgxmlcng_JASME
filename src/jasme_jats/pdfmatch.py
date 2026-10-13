"""出版版 PDF との照合（docx の段落の文字と、記事の PDF の文字を段落ごとに突き合わせる）。

PDF は著者校正を経た最終版なので、XML の本文が PDF と違えば、J-STAGE には同じ記事の 2 つの版が並ぶことになる。
受け取った docx が校正後の最終版とは限らない（組版で印刷所がかっこ・句読点を全角にそろえる、校正の直しが docx に
戻されていない、など）ため、変換の後に PDF の文字と比べて、

  ・英数字・記号の全角・半角だけの違い: PDF に合わせる（設定でやめられる）。その文字のすぐ前後の空白で、PDF にない
    ものは落とす（「理論 (ATD) に」→「理論（ATD）に」）。空白を足すことはしない
  ・それ以外の文字の違い（「資料」と「付録」など）: レポートに載せるだけ（docx を直して変換し直すかは人が決める）
  ・PDF の中に見つからない段落: レポートに載せる

PDF から XML を作るのではない（構造はすべて docx のスタイルから決める）。PDF の文字は、照合にだけ使う。
変えた文字は、XML の作業用の目印（jx:w / jx:d）に docx の元の文字を残し、文字の不変性チェックで、全角・半角の
違いと空白のほかは docx と 1 文字ずつ一致することを確かめる（fidelity.py）。

PDF から取り出した文字には組版の都合（両端そろえの空白、行末のハイフン、図の中の文字、数式、柱）が混じるため、
空白は照合に使わず、段落ごとに PDF の中の対応する箇所を探してから比べる。
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
RE_PAGE_NO = re.compile(r"^[\s　]*[(（]?[0-9０-９]{1,4}[)）]?[\s　]*$")
RE_ALNUM = re.compile(r"[0-9A-Za-z]")


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
    pdf: str         # PDF の文字（違う部分）
    context: str     # docx の前後の文字


@dataclass
class PdfCheck:
    ok: bool = True                 # PDF の文字を読めたか
    message: str = ""               # 読めなかった理由など
    apply: bool = True              # 全角・半角を PDF に合わせる設定か
    checked: int = 0                # 照合した段落の数
    unmatched: list = field(default_factory=list)   # PDF の中に見つからなかった段落の src
    width: dict = field(default_factory=dict)       # src -> {plain 上の位置: PDF の文字}
    drops: dict = field(default_factory=dict)       # src -> {plain 上の位置（落とす空白）}
    diffs: list = field(default_factory=list)       # TextDiff

    @property
    def edits(self) -> dict:
        """XML に反映する変更: src -> (置き換え {位置: 文字}, 落とす空白 {位置})。設定で無効なら空。"""
        if not self.apply:
            return {}
        return {s: (self.width.get(s, {}), self.drops.get(s, set())) for s in set(self.width) | set(self.drops)}

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
    """PDF の本文の文字の列（空白を除いたもの）と、各文字の前の空白・改行。"""
    chars: list = field(default_factory=list)
    space_before: list = field(default_factory=list)    # 前に空白（改行以外）がある
    newline_before: list = field(default_factory=list)  # 前に改行がある
    soft: list = field(default_factory=list)            # 行末のハイフン（照合で無視してよい文字）

    @property
    def keys(self) -> str:
        return "".join(key(c) for c in self.chars)


def pdf_stream(pages) -> PdfStream:
    lines = []
    page_lines = [re.split(r"\r\n|\r|\n", p) for p in pages]
    # 柱: ページ番号だけの行と、3 ページ以上に同じ文字列で現れる 8 文字以上の行
    cnt = Counter(s for ls in page_lines for s in {x.strip() for x in ls} if len(s) >= 8)
    heads = {s for s, n in cnt.items() if n >= 3}
    for ls in page_lines:
        for ln in ls:
            if RE_PAGE_NO.match(ln) or ln.strip() in heads:
                continue
            lines.append(ln)
    st = PdfStream()
    sp = nl = False
    text = "\n".join(lines)
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
        sp = nl = False
    return st


# ---------------------------------------------------------------------------- 照合
def _para_seq(p):
    """段落の照合用の文字の列 [(文字, plain 上の位置)]。空白は除く。数式・画像・脚注番号・自動番号は SKIP。"""
    seq = [(SKIP, -1) for _ in (p.autonum or "").strip()]
    for i, ch in enumerate(p.plain()):
        if ch.isspace():
            continue
        seq.append((SKIP if ch == OBJ else ch, i))
    return seq


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


def compare(plan, pages, apply: bool = True) -> PdfCheck:
    """docx の段落と PDF の文字を照合する。pages は PDF の各ページの文字（extract_pages）。"""
    res = PdfCheck(apply=apply)
    st = pdf_stream(pages)
    pf = st.keys
    if not pf:
        res.ok = False
        res.message = "PDF から文字を取り出せなかった（画像だけの PDF の可能性がある）"
        return res
    targets = {p.src for p in target_paragraphs(plan)}
    # 位置合わせには、照合しない段落（図の中の文字・表のセル・資料など）も docx の順で使う。PDF の文字のうち、
    # ほかの段落に当たった文字を「PDF にだけある文字」と数えないため
    paras = [(p, _para_seq(p)) for p in plan.paras.values()]
    paras = [(p, q) for p, q in paras if sum(1 for c, _ in q if c != SKIP) >= MIN_CHARS]
    # 1. 全体の照合で、段落ごとの PDF の中のおおよその位置を決める
    whole, spans = [], []
    for p, seq in paras:
        start = len(whole)
        whole.extend(key(c) for c, _ in seq)
        spans.append((start, len(whole)))
        whole.append(SEP)
    d2p = [-1] * len(whole)
    sm = difflib.SequenceMatcher(None, "".join(whole), pf, autojunk=False)
    for a, b, n in sm.get_matching_blocks():
        for k in range(n):
            d2p[a + k] = b + k
    # 2. 段落ごとに、PDF の中の窓と照合する
    aligned = {}
    owner = {}                 # PDF の文字の位置 -> その文字に当たった段落
    for (p, seq), (s, e) in zip(paras, spans):
        window = _window(seq, d2p[s:e], pf)
        ops = _align(seq, st, window) if window else None
        if ops is None:
            continue
        aligned[p.src] = (p, seq, window[0], ops)
        for tag, i1, i2, j1, j2 in ops:
            if tag == "equal":
                for k in range(j2 - j1):
                    owner.setdefault(window[0] + j1 + k, p.src)
    # 3. 照合する段落の違いを分類する
    for p, seq in paras:
        if p.src not in targets:
            continue
        res.checked += 1
        if p.src not in aligned:
            res.unmatched.append(p.src)
            continue
        _classify(*aligned[p.src], st, owner, res)
    return res


def _window(seq, mapped, pf):
    """段落を照合する PDF の範囲 (lo, hi)。見つからなければ None。"""
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
    """段落と PDF の窓の照合（difflib の opcodes）。一致した文字が少なければ None。"""
    lo, hi = window
    d = "".join(key(c) for c, _ in seq)
    w = "".join(key(c) for c in st.chars[lo:hi])
    ops = difflib.SequenceMatcher(None, d, w, autojunk=False).get_opcodes()
    real = sum(1 for c, _ in seq if c != SKIP)
    same = sum(i2 - i1 for t, i1, i2, _, _ in ops if t == "equal")
    return ops if same >= MIN_COVERAGE * real else None


def _classify(p, seq, lo, ops, st: PdfStream, owner, res: PdfCheck):
    text = p.plain()
    locked = _locked_positions(p)
    d2w = {}          # seq の位置 -> PDF の文字の位置
    width = {}        # seq の位置 -> PDF の文字（全角・半角だけの違い）
    regions = []      # 違う部分 (i1, i2, j1, j2)（seq と窓の中の位置）

    def mine(j):      # PDF の文字が、ほかの段落に当たっていない（この段落の違いとして扱ってよい）か
        return owner.get(lo + j, p.src) == p.src and not st.soft[lo + j]

    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            for k in range(i2 - i1):
                dc = seq[i1 + k][0]
                pc = st.chars[lo + j1 + k]
                d2w[i1 + k] = lo + j1 + k
                if dc == pc:
                    continue
                if is_width_pair(dc, pc):
                    if seq[i1 + k][1] not in locked:
                        width[i1 + k] = pc
                else:
                    regions.append((i1 + k, i1 + k + 1, j1 + k, j1 + k + 1))   # 大文字・小文字の違い
            continue
        if tag == "insert" and (i1 == 0 or i1 == len(seq)):
            continue                     # 段落の前後の PDF の文字（別の段落など）
        js = [j for j in range(j1, j2) if mine(j)]
        if not any(c != SKIP for c, _ in seq[i1:i2]):
            # docx の側に文字がない（数式・脚注番号は PDF では文字になっている）。PDF にだけある文字は、
            # 図の中の文字などの可能性が高い長いものは除く
            if tag != "insert" or not js or len(js) >= 20:
                continue
        regions.append((i1, i2, js[0] if js else j1, js[-1] + 1 if js else j1))
    _report_regions(p, seq, st, lo, regions, mine, res)
    if not width:
        return
    res.width[p.src] = {seq[i][1]: c for i, c in width.items()}
    drops = set()
    for i in width:
        for j, k in ((i - 1, i), (i, i + 1)):          # 前の文字との間・後ろの文字との間
            if j < 0 or k >= len(seq) or j not in d2w or k not in d2w or d2w[k] != d2w[j] + 1:
                continue
            gap = range(seq[j][1] + 1, seq[k][1])
            if not gap or not all(text[x].isspace() for x in gap):
                continue
            pk = d2w[k]
            if not _pdf_space(st, pk):
                drops.update(x for x in gap if x not in locked)
    if drops:
        res.drops[p.src] = drops


def _pdf_space(st: PdfStream, k: int) -> bool:
    """PDF の k 番目の文字の前に、本物の空白があるか。

    和文の文字（全角の記号を含む）の隣に PDF で見える空白は、両端そろえや字間の調整による見かけのものなので、空白とみなさない。
    前後がどちらも半角の英数字・記号のとき（英文の単語の間）だけ、空白（行の折り返しを含む）とみなす。
    """
    if k <= 0 or not (st.space_before[k] or st.newline_before[k]):
        return False
    return ord(st.chars[k - 1]) < 0x80 and ord(st.chars[k]) < 0x80


def _report_regions(p, seq, st: PdfStream, lo, regions, mine, res: PdfCheck, near=12):
    """違う部分を、近いものどうしまとめて TextDiff にする。"""
    merged = []
    for r in sorted(regions):
        if merged and r[0] - merged[-1][1] <= near and r[2] - merged[-1][3] <= near:
            m = merged[-1]
            merged[-1] = (m[0], max(m[1], r[1]), m[2], max(m[3], r[3]))
        else:
            merged.append(r)
    text = p.plain()
    for i1, i2, j1, j2 in merged:
        pos = [q for _, q in seq[i1:i2] if q >= 0]
        if pos:
            a, b = pos[0], pos[-1] + 1
        else:                                   # docx の側に文字がない（PDF にだけある）
            a = b = (seq[i1 - 1][1] + 1) if i1 > 0 and seq[i1 - 1][1] >= 0 else 0
        dtext = text[a:b].replace(OBJ, "")
        ptext = ""
        for j in range(j1, j2):
            if not mine(j):
                continue
            g = lo + j
            if ptext and _pdf_space(st, g):
                ptext += " "          # 表示のために単語の間の空白を戻す（照合では空白を使わない）
            ptext += st.chars[g]
        if fold_str(re.sub(r"\s", "", dtext)) == fold_str(re.sub(r"\s", "", ptext)):
            continue
        ctx = (text[max(0, a - 12):a] + "［" + text[a:b] + "］" + text[b:b + 12]).replace(OBJ, "")
        res.diffs.append(TextDiff(p.src, dtext, ptext, ctx))


def fold_str(s: str) -> str:
    return "".join(fold(c) for c in s)


def check_pdf(plan, pdf_path, apply: bool = True) -> PdfCheck:
    """記事の PDF を読み、docx の段落と照合する。PDF を読めなければ ok=False（変換は続ける）。"""
    try:
        pages = extract_pages(pdf_path)
    except ImportError:
        return PdfCheck(ok=False, apply=apply, message="PDF の文字を読むための pypdfium2 が入っていない（pip install pypdfium2）")
    except Exception as e:  # noqa: BLE001
        return PdfCheck(ok=False, apply=apply, message=f"PDF を読めなかった: {e}")
    return compare(plan, pages, apply)
