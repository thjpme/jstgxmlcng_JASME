"""文字の不変性チェック。

docx の各段落の文字列を ooxml.canonical_texts()（段落ごとの ooxml.canonical_text()）で独立に取り出し、変換後の XML の
<jx:span src=...> に書き出された文字列と 1 文字ずつ比較する。段落記号の削除でつないだ段落（ooxml.joined_paragraphs）と
隠し文字の判定（ooxml.HiddenRule）は、読み取り（docx_reader）と同じ規則を使う（規則そのものの誤りはここでは見つからない）。

  ・docx のすべての段落が、XML のどこかに過不足なく出力されているか
    （出力しない段落は Exclusion としてレポートに全文を載せる）
  ・XML に、docx にない文字が追加されていないか（追跡の目印の外に文字がないか）
  ・構造の区切りとして落とした文字は空白だけか
  ・出力した段落が、出力しなかった段落（除外）にも登録されていないか
  ・空白だけとして除外した段落（Exclusion.blank）の docx の文字は、本当に空白だけか

さらに final_check() で、目印を取り除いた最終出力の文字列が、検証済みの木と一致することを確かめる。

ルート2 では、verify_supplement()（補完の確かめ）で、出版版 PDF で補った docx が、元の docx から「組版の違い（(A)）」と
「13.1 に報告した校正の直し（(B)。pdfdocx.Fix の kind text）」以外に変わっていないことを確かめる。照合（pdfmatch）と
docx の書き込み（pdfdocx）の不具合も見つけられるように、照合・書き込みと共有するのは定数（pdfmatch の FW_FIRST・FW_LAST・
HYPHENS・DASHES・QUOTE_CLASSES・NUMBER_PAIRS、pdfdocx の AUTHOR・PARTS）だけにする。組版の違いの判定（_pair）と変更の単位の
取り出しはここで別に実装し（文字の取り出しは ooxml.canonical_text）、大文字・小文字を (A) とする段落と、Word が付ける番号の
元の文字は、補った docx から組み立てた plan から別に作る（supplement_targets。照合の case_paragraphs・PdfCheck.original は
使わない）。照合から受け取るのは、直した箇所の一覧（pdfdocx.Fix）と、番号を PDF に合わせたもの（plan.pdf_numbers）で、
どちらも確かめる側。
"""
from __future__ import annotations

import copy
import difflib
from collections import defaultdict
from dataclasses import dataclass, field

from lxml import etree

from .ooxml import (DocxPackage, HiddenRule, canonical_text, canonical_texts, is_ws, joined_paragraphs,
                    paragraph_ids, w)
from .omml import MML_NS, math_plain
from .pdfdocx import AUTHOR, PARTS
from .pdfmatch import DASHES, FW_FIRST, FW_LAST, HYPHENS, NUMBER_PAIRS, QUOTE_CLASSES
from .tracking import AI, GEN, JX_NS, SPAN

DROP = f"{{{JX_NS}}}drop"
MATH = f"{{{MML_NS}}}math"

# 利用者が入力した書誌情報や雑誌の設定から作る要素（docx の文字ではない）
META_ELEMENTS = {"journal-meta", "article-id", "article-categories", "pub-date", "volume", "issue", "fpage", "lpage",
                 "history", "permissions", "kwd-group", "self-uri", "related-article", "funding-group",
                 "conference", "supplementary-material"}


@dataclass
class Mismatch:
    src: str
    expected: str
    got: str
    detail: str


@dataclass
class FidelityResult:
    ok: bool = True
    units: int = 0                 # docx の段落数（空でないもの）
    mapped: int = 0
    excluded: list = field(default_factory=list)      # (src, reason, text)
    conflicts: list = field(default_factory=list)     # (src, reason, text) 出力したのに除外にも登録されている段落
    bad_excluded: list = field(default_factory=list)  # (src, reason, text) 空白だけとして除外したのに空白以外の文字がある
    mismatches: list = field(default_factory=list)    # Mismatch
    missing: list = field(default_factory=list)       # (src, text)
    duplicates: list = field(default_factory=list)    # src
    stray: list = field(default_factory=list)         # (要素, 文字)
    drops: list = field(default_factory=list)         # (src, text, reason)
    bad_drops: list = field(default_factory=list)     # (src, text, reason) 空白以外を落としたもの
    generated: list = field(default_factory=list)     # (kind, text)
    unknown: list = field(default_factory=list)       # docx に存在しない src
    ai_additions: list = field(default_factory=list)  # (decision, 文字) AI が明示的に追加したもの
    final_ok: bool = None
    final_detail: str = ""
    final_unreadable: bool = False  # 最終出力が XML として読めなかった・実体の宣言があった（final_check。読めないことが不合格の理由）
    final_differs: bool = False     # 最終出力の文字が、検証済みの木と違った（final_check。読めない・実体の宣言と同時のこともある）

    def summary(self) -> str:
        if self.ok and self.final_ok is not False:
            return "合格"
        return "不合格"


def source_texts(docx_path) -> dict:
    """docx の段落 ID → 文字（本文・Word の脚注・文末脚注）。段落記号の削除でつないだ段落の後ろの段落の ID は入らない（欠番）。"""
    pkg = DocxPackage(docx_path)
    rule = HiddenRule(pkg.xml("word/styles.xml"))
    out = {}
    for part, prefix in (("word/document.xml", "d"), ("word/footnotes.xml", "f"), ("word/endnotes.xml", "e")):
        root = pkg.xml(part)
        if root is None:
            continue
        out.update(canonical_texts(root, prefix, rule))
    return out


def piece_text(el, nested_errors=None) -> str:
    """<jx:span> の中の文字（生成文字を除き、数式は docx 上の順序で）を取り出す。"""
    out = [el.text or ""]
    for ch in el:
        if not isinstance(ch.tag, str):
            out.append(ch.tail or "")
            continue
        if ch.tag == GEN:
            pass
        elif ch.tag == MATH:
            out.append(math_plain(ch))
        elif ch.tag in (SPAN, DROP):
            if nested_errors is not None:
                nested_errors.append(ch.get("src"))
            out.append(piece_text(ch))
        else:
            out.append(piece_text(ch, nested_errors))
        out.append(ch.tail or "")
    return "".join(out)


def _diff(expected: str, got: str) -> str:
    sm = difflib.SequenceMatcher(None, expected, got, autojunk=False)
    parts = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        ctx = expected[max(0, i1 - 10):i1]
        parts.append(f"{op}: …{ctx}［docx: {expected[i1:i2]!r} → XML: {got[j1:j2]!r}］")
        if len(parts) >= 3:
            break
    return " / ".join(parts)


def verify(docx_path, tracked_root, exclusions) -> FidelityResult:
    res = FidelityResult()
    src = source_texts(docx_path)
    exclusions = list(exclusions)
    excl = {}
    for e in exclusions:
        excl.setdefault(e.src, e)

    pieces = defaultdict(list)
    nested = []
    for el in tracked_root.iter(SPAN, DROP):
        s = el.get("src")
        seq = int(el.get("seq", "0"))
        if el.tag == SPAN:
            pieces[s].append((seq, "span", piece_text(el, nested), ""))
        else:
            pieces[s].append((seq, "drop", el.text or "", el.get("reason", "")))
    for el in tracked_root.iter(GEN):
        res.generated.append((el.get("kind", ""), el.text or ""))
    for el in tracked_root.iter(AI):
        res.ai_additions.append((el.get("decision", ""), "".join(el.itertext())))

    for s, text in src.items():
        if text != "":
            res.units += 1
        if s in pieces:
            items = sorted(pieces[s], key=lambda x: x[0])
            seqs = [x[0] for x in items]
            if len(seqs) != len(set(seqs)):
                res.duplicates.append(s)
            got = "".join(x[2] for x in items)
            for seq, kind, t, reason in items:
                if kind == "drop":
                    res.drops.append((s, t, reason))
                    if not is_ws(t):
                        res.bad_drops.append((s, t, reason))
            if got != text:
                res.mismatches.append(Mismatch(s, text, got, _diff(text, got)))
            else:
                res.mapped += 1
            if s in excl:
                # 出力したのに除外にも登録されている（レポートの「出力しなかった文字」と食い違う。変換処理の誤り）
                reasons = "／".join(dict.fromkeys(e.reason for e in exclusions if e.src == s))
                res.conflicts.append((s, reasons, text))
        elif s in excl:
            e = excl[s]
            res.excluded.append((s, e.reason, text))
        elif text == "":
            continue
        else:
            res.missing.append((s, text))
    for s in pieces:
        if s not in src:
            res.unknown.append(s)
    # 空白だけとして除外したもの（blank）は、docx の文字が本当に空白だけかを確かめる。
    # 同じ段落に除外が 2 件以上あることもあるので、最初の 1 件だけでなく、すべての除外を確かめる
    for e in exclusions:
        if e.blank and not is_ws(src.get(e.src, "")):
            res.bad_excluded.append((e.src, e.reason, src.get(e.src, "")))

    res.stray = stray_text(tracked_root)
    res.ok = not (res.mismatches or res.missing or res.duplicates or res.stray or res.bad_drops or res.unknown
                  or res.conflicts or res.bad_excluded or nested)
    if nested:
        res.mismatches.append(Mismatch(",".join(nested), "", "", "追跡用の目印が入れ子になっている（変換処理の誤り）"))
    return res


def stray_text(root):
    """docx の文字の外（目印の外）にある文字を探す。書誌情報の要素は対象外。"""
    out = []

    def walk(el, path, inside):
        tag = el.tag if isinstance(el.tag, str) else ""
        local = etree.QName(tag).localname if tag else ""
        here_inside = inside or tag in (SPAN, DROP, GEN, AI) or local in META_ELEMENTS
        if el.text and not here_inside and tag:
            out.append(("/".join(path + [local]), el.text))
        for ch in el:
            if not isinstance(ch.tag, str):
                continue
            walk(ch, path + [local], here_inside)
            if ch.tail and not here_inside:
                out.append(("/".join(path + [local]), ch.tail))
    walk(root, [], False)
    return out


def final_check(tracked_root, final_bytes: bytes, res: FidelityResult):
    """目印を取り除いた最終出力の文字列が、検証済みの木（落とした空白を除く）と一致するかを確かめる。"""
    import copy
    t = copy.deepcopy(tracked_root)
    etree.strip_elements(t, DROP, with_tail=False)
    expected = "".join(t.itertext())
    parser = etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False, huge_tree=True)
    try:
        final = etree.fromstring(final_bytes, parser)
    except etree.XMLSyntaxError as e:
        res.final_ok, res.final_detail = False, f"最終出力が XML として読めない: {e}"
        res.final_unreadable = True
        return False
    # 実体参照のノードは文字として数えない（未定義の実体参照 &foo; は、itertext に "&foo;" が入って文字の違いに見えるが、
    # 文字の違いではなく「読めない」側の不備。下の、実体を解決する読み直しで不合格にする）
    for ent in list(final.iter(etree.Entity)):
        parent = ent.getparent()
        if ent.tail:
            prev = ent.getprevious()
            if prev is not None:
                prev.tail = (prev.tail or "") + ent.tail
            else:
                parent.text = (parent.text or "") + ent.tail
        parent.remove(ent)
    got = "".join(final.itertext())
    res.final_ok = expected == got
    res.final_differs = not res.final_ok
    res.final_detail = "" if res.final_ok else _diff(expected, got)
    # 実体宣言（<!ENTITY）を含む出力は、それだけで不合格にする。このツールは実体を宣言しない（DOCTYPE は公開 ID だけ）ので、
    # あれば入り込んだもの。解決すると外部実体（file://）を読んでしまうが、内部実体だけ解決する設定（resolve_entities='internal'）は
    # lxml 5.0 以降でしか使えず、下限（pyproject.toml の lxml>=4.9）では使えないため、宣言を見つけたら解決せずに止める
    if b"<!ENTITY" in final_bytes:
        res.final_ok = False
        res.final_unreadable = True         # 文字の違いではなく、読めない・実体の宣言がある側の知らせ（report._fidelity_action）にする
        res.final_detail = ("最終出力に実体の宣言（<!ENTITY）がある。このツールは出力しないので、外部の実体を読まないよう解決せずに不合格とした"
                            + (f"。{res.final_detail}" if res.final_detail else ""))
        return False
    # 実体を宣言していなければ、実体を解決する通常のパーサでも読めること（未定義の実体参照などは、上の resolve_entities=False では
    # 実体参照のまま通り、文字としては数えられない）。宣言がないので外部実体は読まない（ネットワークも読まない）。読めなければ
    # 最終出力の不合格として、要対応に乗せる
    try:
        etree.fromstring(final_bytes, etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=True, huge_tree=True))
    except etree.XMLSyntaxError as e:
        res.final_ok = False
        res.final_unreadable = True
        res.final_detail = f"最終出力が XML として読めない（実体参照などの不備）: {e}" + (f"。{res.final_detail}" if res.final_detail else "")
    return res.final_ok


# ---------------------------------------------------------------------------- 補完の確かめ（ルート2）
# 補った docx のこのツールの変更履歴の中の文字を、canonical_texts の文字の中で見分けるための目印（Unicode の非文字。docx の文字には
# 出ない）。挿入（w:ins）のランの中の文字を I_OPEN〜I_CLOSE で、削除（w:del）のランの中の文字を D_OPEN〜D_CLOSE で挟む
I_OPEN, I_CLOSE, D_OPEN, D_CLOSE = "﷐", "﷑", "﷒", "﷓"
# Word の脚注・文末脚注の参照（本文の番号）と、注の段落の番号（w:footnoteRef・w:endnoteRef）の位置の目印。番号は canonical_text
# に出ないので、この位置を変更の単位の境目にし、すぐ隣の空白の削除を照合の drops と同じく (A) と認める（却下した文字・承諾した
# 文字には入れない）
EDGE = "﷔"
MARKS = I_OPEN + I_CLOSE + D_OPEN + D_CLOSE + EDGE
NOTE_MARKS = {w("footnoteReference"), w("endnoteReference"), w("footnoteRef"), w("endnoteRef")}
SUP_WINDOW = 16          # 1 つの変更の単位に当てる校正の直し（Fix）を探す数（段落の中で、まだ当てていない最初の直しから）
SUP_CONTEXT = 10         # 問題の箇所の前後に添える文字の数
# 補完の確かめの不合格の理由
UNTRACKED_WHY = "変更履歴でない書き換えがある（このツールの変更履歴を却下した文字が、元の docx の文字と違う）"
PARA_SET_WHY = "段落が増えたか消えた（補った docx と元の docx で、段落の並びが違う）"
PARA_MARK_WHY = "このツールの変更履歴が、段落記号か書式にかかっている"
READ_WHY = "補った docx の変更履歴を読み取れない（承諾した文字が、補った docx の文字と合わない）"
UNIT_WHY = "組版の違い（(A) の対・空白の削除）でも、13.1 の補った箇所でもない変更"
UNWRITTEN_WHY = "13.1 に報告したのに、補った docx に書き込まれていない"
NUMBER_WHY = "Word が付ける番号を、組版の違い（全角・半角と、番号の字形の対）でない文字にしている"
NUMBER_SRC_WHY = "Word が付ける番号の元の文字が分からない"


@dataclass
class SupplementResult:
    """補完の確かめ（verify_supplement）の結果。"""
    ok: bool = True
    typeset: int = 0          # (A) と当たった文字の数（全角・半角などの対と、消した空白。Fix の width・space・glyph の数に当たる）
    supplied: int = 0         # (B)（13.1 の Fix。kind text）と当たった数
    problems: list = field(default_factory=list)   # [(段落 ID, 元の docx の文字, 補った docx の文字, 理由)]


def _fold(c: str) -> str:
    """全角の英数字・記号 → 半角（pdfmatch.fold と同じ規則を、定数から別に書く）。"""
    o = ord(c)
    return chr(o - 0xFEE0) if FW_FIRST <= o <= FW_LAST else c


def _quote_class(c: str) -> int:
    return next((n for n, cls in enumerate(QUOTE_CLASSES) if c in cls), -1)


def _width(a: str, b: str) -> bool:
    """a と b が全角・半角の対か（_fold が同じで 0x21〜0x7E。同じ文字は偽）。"""
    if a == b:
        return False
    fa = _fold(a)
    return fa == _fold(b) and 0x21 <= ord(fa) <= 0x7E


def _pair(a: str, b: str, case: bool = False, number: bool = False) -> bool:
    """docx の 1 文字 a と、補った docx の 1 文字 b が組版の違い（(A)）の対か（同じ文字は偽）。pdfmatch.typeset_pair と同じ規則を、
    定数だけを共有して別に書いたもの（tests/test_supplement.py で、すべての対で答えが同じことを確かめる）。

    全角・半角（_fold が同じで 0x21〜0x7E）、HYPHENS ＋ DASHES の中どうし（向きを問わない）、QUOTE_CLASSES の同じ類の中どうし
    （全角は _fold の後。向きを問わない）、number なら NUMBER_PAIRS の対（向きがある）、case なら英字の大文字・小文字
    （「ａ」と「A」のように全角・半角と重なるものも。両方が _fold の後に ASCII の英字のときだけ）。
    """
    if a == b:
        return False
    if _width(a, b):
        return True
    fa, fb = _fold(a), _fold(b)
    dash = HYPHENS + DASHES
    if a in dash and b in dash:
        return True
    qa = _quote_class(fa)
    if qa >= 0 and qa == _quote_class(fb):
        return True
    if number and (a, b) in NUMBER_PAIRS:
        return True
    return case and fa.isascii() and fb.isascii() and fa.isalpha() and fa.lower() == fb.lower()


def _mark_runs(el, open_mark: str, close_mark: str):
    """変更履歴の要素 el の中のランの文字を目印で挟み、削除の文字（w:delText）はふつうの文字（w:t）にする。"""
    for r in list(el.iter(w("r"))):
        if r.tag != w("r"):
            continue
        for t in r.iter(w("delText")):
            t.tag = w("t")
        for t in r.iter(w("delInstrText")):
            t.tag = w("instrText")
        start = etree.Element(w("t"))
        start.text = open_mark
        end = etree.Element(w("t"))
        end.text = close_mark
        rpr = r.find(w("rPr"))
        r.insert(r.index(rpr) + 1 if rpr is not None else 0, start)
        r.append(end)


def _unwrap(el):
    """要素 el を取り除き、中身を親の同じ位置に戻す。"""
    parent = el.getparent()
    idx = parent.index(el)
    kids = list(el)
    prev = el.getprevious()
    if el.text:
        if prev is not None:
            prev.tail = (prev.tail or "") + el.text
        else:
            parent.text = (parent.text or "") + el.text
    for k, ch in enumerate(kids):
        parent.insert(idx + k, ch)
    if el.tail:
        if kids:
            kids[-1].tail = (kids[-1].tail or "") + el.tail
        else:
            before = parent[idx - 1] if idx > 0 else None
            if before is not None:
                before.tail = (before.tail or "") + el.tail
            else:
                parent.text = (parent.text or "") + el.tail
    parent.remove(el)


def _ours(el, old_ids) -> bool:
    """el がこのツールが今回書き込んだ変更履歴か（作成者が AUTHOR で、元の docx にあった同じ作成者の変更履歴〈w:id〉でない）。"""
    return el.get(w("author")) == AUTHOR and el.get(w("id")) not in old_ids


def _marked_text(chain, rule, old_ids, problems, src) -> str:
    """段落の連鎖 chain（w:p の並び）の目印付きの文字（canonical_text。このツールの変更履歴の中の文字を目印で挟む）。

    w:p を写し、このツールの変更履歴（_ours）を、中のランの文字を目印で挟んで外し（削除の文字は w:t にする）、canonical_text で
    読む。目印の外の文字が変わっていない文字、I_OPEN〜I_CLOSE が足した文字、D_OPEN〜D_CLOSE が消した文字。このツールの変更履歴が
    段落記号・書式（w:rPr の中）にかかっていれば、problems に足す。Word の注の番号（参照と、注の段落の番号。削除されたものを
    除く）の位置には、境目の目印 EDGE を入れる。
    """
    out = []
    for q in chain:
        q = copy.deepcopy(q)
        for ref in list(q.iter(*NOTE_MARKS)):
            r = ref.getparent()
            if r is None or r.tag != w("r") or any(True for _ in ref.iterancestors(w("del"), w("moveFrom"))):
                continue
            edge = etree.Element(w("t"))
            edge.text = EDGE
            r.insert(r.index(ref), edge)
        for el in list(q.iter(w("ins"), w("del"))):
            parent = el.getparent()
            if parent is None or not _ours(el, old_ids):
                continue
            if parent.tag == w("rPr"):
                problems.append((src, "", "", PARA_MARK_WHY))
                parent.remove(el)
                continue
            if el.tag == w("ins"):
                _mark_runs(el, I_OPEN, I_CLOSE)
            else:
                _mark_runs(el, D_OPEN, D_CLOSE)
            _unwrap(el)
        out.append(canonical_text(q, rule))
    return "".join(out)


def _chains(root, prefix) -> dict:
    """部品の段落 ID → 段落の連鎖 [w:p, …]（canonical_texts と同じ並び。段落記号の削除でつないだ後ろの段落の ID は入らない）。"""
    if root is None:
        return {}
    joined = joined_paragraphs(root)
    later = {q for c in joined.values() for q in c[1:]}
    return {pid: joined.get(p, [p]) for p, pid in paragraph_ids(root, prefix).items() if p not in later}


def _split_marked(text: str):
    """目印付きの文字から (却下した文字, 承諾した文字, 単位の一覧)。単位は (却下した文字の上の位置, 承諾した文字の上の位置,
    消した文字 D, 足した文字 I, 前が境目か, 後ろが境目か)。変わっていない文字をはさまずに続く挿入・削除を 1 つの単位にする。
    境目は Word の注の番号の目印 EDGE（単位はそこで切る）。目印の並びがおかしければ None。"""
    rej, acc, units = [], [], []
    state = ""            # "" / "i" / "d"
    cur = None            # 作っている単位 [rej の位置, acc の位置, D, I, 前が境目か, 後ろが境目か]
    edge = False          # 直前が境目の目印
    for c in text:
        if c in MARKS:
            if c == EDGE and state == "":
                if cur is not None:
                    cur[5] = True
                    units.append(tuple(cur))
                    cur = None
                edge = True
            elif c == I_OPEN and state == "":
                state = "i"
            elif c == D_OPEN and state == "":
                state = "d"
            elif (c == I_CLOSE and state == "i") or (c == D_CLOSE and state == "d"):
                state = ""
            else:
                return None
            continue
        if state == "":
            if cur is not None:
                units.append(tuple(cur))
                cur = None
            edge = False
            rej.append(c)
            acc.append(c)
            continue
        if cur is None:
            cur = [len(rej), len(acc), "", "", edge, False]
        if state == "d":
            cur[2] += c
            rej.append(c)
        else:
            cur[3] += c
            acc.append(c)
    if state:
        return None
    if cur is not None:
        units.append(tuple(cur))
    return "".join(rej), "".join(acc), units


def _unit_ends(d: str, i: str, queue: list, p: int, case: bool, at_start: bool = False, at_end: bool = False) -> dict:
    """変更の単位（消した文字 d, 足した文字 i）を、組版の違いと、校正の直しの並び queue の p 番目からのいくつか（どれも 1 回ずつ。
    単位の中の順は問わない）で説明できる、当て終わった後の queue の位置 → (A) の文字の数（最も少ないもの）。

    d と i を前から 1 文字ずつ、同じ文字か _pair の対として並べるか、d の空白を消す（(A)）か、まだ当てていない直し f の
    (f.old, f.new) を d・i のその位置に当てて進め、d・i を使い切ったときに、当てた直しが queue[p:p+k] のちょうど k 個の
    ものだけを答えにする（位置は使わない。数式の後ろでは、Fix の位置と canonical_text の位置が合わないため）。

    空白の削除を (A) とするのは、照合の drops と同じく、半角の空白（U+0020）で、d の中のすぐ前かすぐ後ろ（空白が続けば、その
    並びの前か後ろ）が、全角・半角の対（_width）として並べた文字か、Word が付ける番号のときだけ。番号は canonical_text に
    出ないので、呼び出し側が単位の端で知らせる: at_start は単位の前が番号（自動番号のある段落の先頭か、Word の注の番号の目印
    EDGE のすぐ後ろ）、at_end は単位の後ろが番号（EDGE のすぐ前）。全角の空白・タブ・改行の削除は (A) にしない。

    限界: 探す直しは、まだ当てていない最初の直しから SUP_WINDOW 個まで。1 つの単位（変わっていない文字をはさまずに続く変更）に
    校正の直しが SUP_WINDOW を超えてかかると、正しい書き込みでも説明できず、不合格になる（安全側）。
    """
    window = queue[p:p + SUP_WINDOW]
    full = (1 << len(window)) - 1
    best = {}
    seen = {}
    # 直前の d の文字の扱い: 0 ふつう / 1 全角・半角の対（か、その後ろで消した空白）/ 2 隣が決まっていない、消した空白 /
    # 3 番号のすぐ後ろで消した空白（at_start のとき、d の最初から）
    stack = [(0, 0, 0, 3 if at_start else 0, 0)]   # (d の位置, i の位置, 当てた直しの集合〈window の中のビット〉, 直前, (A) の数)
    while stack:
        a, b, used, last, n = stack.pop()
        key = (a, b, used, last)
        if key in seen and seen[key] <= n:
            continue
        seen[key] = n
        if a == len(d) and b == len(i) and (last != 2 or at_end):
            k = 0
            while k < len(window) and used >> k & 1:
                k += 1
            if used == (1 << k) - 1:
                best[p + k] = min(best.get(p + k, n), n)
        if a < len(d) and b < len(i) and (d[a] == i[b] or _pair(d[a], i[b], case)):
            width = _width(d[a], i[b])
            if width or last != 2:
                stack.append((a + 1, b + 1, used, 1 if width else 0, n + (d[a] != i[b])))
        if a < len(d) and d[a] == " ":
            stack.append((a + 1, b, used, last if last in (1, 3) else 2, n + 1))
        if used != full:
            for k, f in enumerate(window):
                if used >> k & 1:
                    continue
                if d.startswith(f.old, a) and i.startswith(f.new, b) and (f.old or f.new):
                    if f.old and last == 2:
                        continue
                    stack.append((a + len(f.old), b + len(f.new), used | 1 << k, last if not f.old else 0, n))
    return best


def _excerpt(text: str, pos: int, inner: str) -> str:
    """text の pos からの inner の前後 SUP_CONTEXT 文字を添えた抜き出し（「…前［inner］後…」）。"""
    head = text[max(0, pos - SUP_CONTEXT):pos]
    tail = text[pos + len(inner):pos + len(inner) + SUP_CONTEXT]
    return f"{'…' if pos > SUP_CONTEXT else ''}{head}［{inner}］{tail}{'…' if pos + len(inner) + SUP_CONTEXT < len(text) else ''}"


def _diff_excerpt(a: str, b: str):
    """2 つの文字の最初の違う部分を、前後の文字を添えて抜き出す (a の抜き出し, b の抜き出し)。"""
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op != "equal":
            return _excerpt(a, i1, a[i1:i2]), _excerpt(b, j1, b[j1:j2])
    return a, b


def supplement_targets(plan, note_marks) -> tuple:
    """補完の確かめに渡す (大文字・小文字を (A) とする段落の ID, Word が付ける番号の元の文字)。照合（pdfmatch の case_paragraphs・
    PdfCheck.original）を通さず、補った docx から組み立てた plan から別に作る。

    大文字・小文字: 英文の題目・副題・著者名・所属の段落（plan.title_en・subtitle_en・authors[].name_en・affs[].en）。
    番号: 自動番号 ("auto", 段落 ID) -> Para.autonum と、Word の注の番号 ("fnref", 注の鍵)・("fnlist", 注の鍵) -> note_marks の
    文字（builder.word_note_marks の出力する文字列。注の鍵 -> 文字）。plan.pdf_numbers と同じ鍵。
    """
    case = {p.src for p in [*plan.title_en, *plan.subtitle_en]}
    case |= {a.name_en.src for a in plan.authors if a.name_en is not None}
    case |= {f.en.src for f in plan.affs if f.en is not None}
    numbers = {("auto", p.src): p.autonum for p in plan.paras.values() if p.autonum}
    for wid, mark in note_marks.items():
        numbers[("fnref", wid)] = mark
        numbers[("fnlist", wid)] = mark
    return case, numbers


def verify_supplement(original_docx, fixed_docx, fixes, case_srcs, numbers_original, pdf_numbers,
                      autonum_srcs=None) -> SupplementResult:
    """補完の確かめ: ルート2 の補った docx（fixed_docx）が、元の docx（original_docx）から、組版の違い（(A)）と 13.1 に報告した
    校正の直し（fixes のうち applied で kind text のもの）以外に変わっていないか。照合（pdfmatch）・書き込み（pdfdocx）とは別の
    実装（設計: 定数だけを共有する）。

      1. 補った docx のこのツールの変更履歴（_ours）を却下した文字が、元の docx の文字（canonical_text。fidelity.source_texts と
         同じ並び）と、すべての段落で同じか（報告しない変更・変更履歴でない書き換え・段落の増減がないこと）。承諾した文字が
         補った docx の文字と同じかも確かめる（変更履歴の読み取りの確かめ）。速さのため、書式（styles.xml）が同じで、段落の
         XML が元の docx と同じ段落は読まない（同じ XML なら同じ文字）
      2. 段落ごと（段落記号の削除でつないだ段落は 1 つ）に、変わっていない文字をはさまずに続く挿入・削除を 1 つの単位にし、
         単位ごとに（消した文字, 足した文字）を作る（位置は変更履歴で決まるので、文字列を並べ直したときのずれは起きない）
      3. 単位を、1 文字ずつの (A) の対（_pair。大文字・小文字は case_srcs の段落だけ）・空白の削除（全角・半角の対と、Word が
         付ける番号〈自動番号のある段落の先頭と、Word の注の番号の目印 EDGE〉のすぐ隣の半角の空白だけ。_unit_ends）と、その段落の
         校正の直しの
         並びの次のいくつか（old・new が文字列として一致するもの）で説明できるか（_unit_ends）。説明できない単位と、どの単位にも
         当たらずに残った直しは不合格
      4. Word が付ける番号（pdf_numbers。docx の文字ではない）が、元の文字（numbers_original）と同じ長さで、1 文字ずつ同じか
         _pair（number）の対か

    case_srcs: 大文字・小文字の違いを (A) とする段落の ID。numbers_original: Word が付ける番号の元の文字。どちらも照合を通さず
    plan から作ったもの（supplement_targets）。pdf_numbers: 番号を PDF に合わせたもの（plan.pdf_numbers）。番号の鍵は
    (種類, ID) -> 文字列。autonum_srcs: 自動番号のある段落の ID（段落の先頭の空白の削除を (A) とする段落。省略すれば
    numbers_original の ("auto", 段落 ID) の鍵から作る）。
    """
    res = SupplementResult()
    problems = res.problems
    case_srcs = set(case_srcs or ())
    if autonum_srcs is None:
        autonum_srcs = {k[1] for k in (numbers_original or {}) if isinstance(k, tuple) and k[:1] == ("auto",)}
    autonum_srcs = set(autonum_srcs)
    opkg, fpkg = DocxPackage(original_docx), DocxPackage(fixed_docx)
    ostyles, fstyles = opkg.xml("word/styles.xml"), fpkg.xml("word/styles.xml")
    orule, frule = HiddenRule(ostyles), HiddenRule(fstyles)
    # 書式（styles.xml）が同じなら、XML が同じ段落は文字も同じなので読まない（速さのため。違う段落だけを canonical_text で読む）
    same_styles = (ostyles is None and fstyles is None) or (
        ostyles is not None and fstyles is not None and etree.tostring(ostyles) == etree.tostring(fstyles))

    def xml_of(chain):
        return [etree.tostring(q, with_tail=False) for q in chain]

    # 1. 却下した文字が元の docx と同じか（段落の並びも）
    split = {}
    for part, prefix in PARTS.items():
        oroot, froot = opkg.xml(part), fpkg.xml(part)
        old_ids = {el.get(w("id")) for el in (oroot.iter(w("ins"), w("del")) if oroot is not None else ())
                   if el.get(w("author")) == AUTHOR}
        ochains, fchains = _chains(oroot, prefix), _chains(froot, prefix)
        if set(ochains) != set(fchains):
            extra = sorted(set(ochains) ^ set(fchains))
            problems.append((",".join(extra[:5]) + ("…" if len(extra) > 5 else ""), "", "", PARA_SET_WHY))
        oids = paragraph_ids(oroot, prefix) if oroot is not None else {}
        fids = paragraph_ids(froot, prefix) if froot is not None else {}
        for src, fchain in fchains.items():
            ochain = ochains.get(src)
            if ochain is None:
                continue
            if (same_styles and [oids[q] for q in ochain] == [fids[q] for q in fchain]
                    and xml_of(ochain) == xml_of(fchain)):
                continue
            parts = _split_marked(_marked_text(fchain, frule, old_ids, problems, src))
            accepted = "".join(canonical_text(q, frule) for q in fchain)
            if parts is None or parts[1] != accepted:
                problems.append((src, "", accepted, READ_WHY))
                continue
            split[src] = parts
            original = "".join(canonical_text(q, orule) for q in ochain)
            if parts[0] != original:
                old, new = _diff_excerpt(original, parts[0])
                problems.append((src, old, new, UNTRACKED_WHY))

    # 2.・3. 変更の単位を (A) と (B) に当てる
    queues = defaultdict(list)
    for f in fixes or ():
        if f.applied and f.kind == "text":
            queues[f.src].append(f)
    for src in queues:
        queues[src].sort(key=lambda f: (f.start, f.end))
    for src, (rej, acc, units) in split.items():
        queue = queues.get(src, [])
        case = src in case_srcs
        reach = {0: (0, 0)}            # 当て終わった queue の位置 → ((A) の文字の数, (B) の数)
        for rpos, apos, d, i, left, right in units:
            at_start = left or (rpos == 0 and src in autonum_srcs)
            nxt = {}
            for p, (na, nb) in reach.items():
                for q, n in _unit_ends(d, i, queue, p, case, at_start, right).items():
                    cand = (na + n, nb + q - p)
                    if q not in nxt or cand < nxt[q]:
                        nxt[q] = cand
            if nxt:
                reach = nxt
            else:
                problems.append((src, _excerpt(rej, rpos, d), _excerpt(acc, apos, i), UNIT_WHY))
        end = len(queue)
        if end in reach:
            na, nb = reach[end]
        else:
            p = max(reach)
            na, nb = reach[p]
            for f in queue[p:]:
                problems.append((src, f.old, f.new, UNWRITTEN_WHY))
        res.typeset += na
        res.supplied += nb
    for src, queue in queues.items():
        if src not in split:
            for f in queue:
                problems.append((src, f.old, f.new, UNWRITTEN_WHY))

    # 4. Word が付ける番号
    for key, new in (pdf_numbers or {}).items():
        ident = f"{key[0]}:{key[1]}" if isinstance(key, tuple) and len(key) == 2 else str(key)
        old = (numbers_original or {}).get(key)
        if old is None:
            problems.append((ident, "", new, NUMBER_SRC_WHY))
        elif len(old) != len(new) or any(a != b and not _pair(a, b, number=True) for a, b in zip(old, new)):
            problems.append((ident, old, new, NUMBER_WHY))
    res.ok = not problems
    return res
