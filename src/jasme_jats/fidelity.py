"""文字の不変性チェック。

docx の各段落の文字列を ooxml.canonical_text() で独立に取り出し、変換後の XML の
<jx:span src=...> に書き出された文字列と 1 文字ずつ比較する。

  ・docx のすべての段落が、XML のどこかに過不足なく出力されているか
    （出力しない段落は Exclusion としてレポートに全文を載せる）
  ・XML に、docx にない文字が追加されていないか（追跡の目印の外に文字がないか）
  ・構造の区切りとして落とした文字は空白だけか

さらに final_check() で、目印を取り除いた最終出力の文字列が、検証済みの木と一致することを確かめる。
"""
from __future__ import annotations

import difflib
from collections import defaultdict
from dataclasses import dataclass, field

from lxml import etree

from .ooxml import DocxPackage, canonical_text, is_ws, paragraph_ids
from .omml import MML_NS, math_plain
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

    def summary(self) -> str:
        if self.ok and self.final_ok is not False:
            return "合格"
        return "不合格"


def source_texts(docx_path) -> dict:
    pkg = DocxPackage(docx_path)
    out = {}
    for part, prefix in (("word/document.xml", "d"), ("word/footnotes.xml", "f"), ("word/endnotes.xml", "e")):
        root = pkg.xml(part)
        if root is None:
            continue
        for p, pid in paragraph_ids(root, prefix).items():
            out[pid] = canonical_text(p)
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
            if s in excl and text.strip():
                # 出力したのに除外にも登録されている（図の段落の空白などは除外の対象外）
                pass
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

    res.stray = stray_text(tracked_root)
    res.ok = not (res.mismatches or res.missing or res.duplicates or res.stray or res.bad_drops or res.unknown
                  or nested)
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
    final = etree.fromstring(final_bytes, parser)
    got = "".join(final.itertext())
    res.final_ok = expected == got
    res.final_detail = "" if res.final_ok else _diff(expected, got)
    return res.final_ok
