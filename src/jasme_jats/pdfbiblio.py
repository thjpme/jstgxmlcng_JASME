"""出版版 PDF の 1 ページ目から書誌情報（巻・号・年・ページ・投稿受付日など）を読む（W5）。

読んだ値は、入力欄に先に入れる手助けと、入力との食い違いの知らせ（`meta_pdf`）にだけ使う。XML に出すのはいつも入力の値で、PDF の値で黙って置き換えない。
誌ごとの形（誌名の行・日付のラベル）はコードに書かず、設定（`JournalConfig.pdf_issue_line`・`pdf_date_labels`。data/jasme.toml の `[pdf_biblio]`）に置く。
読めない項目は空にし、例外にしない（PDF が読めない・誌名の行がない・設定がない、のどれでも変換を止めない）。
"""
from __future__ import annotations

import datetime as _dt
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

from .config import DATE_FIELDS, PAGE_FIELDS

# 入力欄に入れる項目（ArticleMeta の欄の名前）。再投稿受付は読むだけで入力欄には使わない
INPUT_KEYS = ("volume", "issue", "fpage", "lpage", "received", "accepted")
# 欄の名前（知らせ・表示用）
LABELS = {**PAGE_FIELDS, **DATE_FIELDS}


@dataclass
class PdfBiblio:
    """PDF から読んだ書誌情報。読めなかった項目は空（日付は ISO 形式 "2029-06-01" の文字列）。"""
    volume: str = ""
    issue: str = ""
    year: str = ""
    fpage: str = ""
    lpage: str = ""
    received: str = ""
    revised: str = ""        # 読むだけ。入力欄にも比べる項目にも使わない
    accepted: str = ""
    pages: int = 0           # PDF のページ数（0 は不明）
    line: str = ""           # 読んだ誌名の行（空白をそろえたもの）
    ambiguous: tuple = ()    # 違う日付が 2 つ以上あって採らなかった日付のラベル（received・revised・accepted。入力があれば unread_dates が受付日・受理日を知らせる）

    def any(self) -> bool:
        return any((self.volume, self.issue, self.fpage, self.lpage, self.received, self.accepted))


def _nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


def _issue_line(first: str, journal) -> tuple:
    """誌名の行の (グループの辞書, 読んだ文字)。読めなければ ({}, "")。設定の正規表現が壊れていても例外にしない。"""
    pat = getattr(journal, "pdf_issue_line", "") or ""
    if not pat:
        return {}, ""
    try:
        m = re.search(pat, first)
    except re.error:
        return {}, ""
    if not m:
        return {}, ""
    g = {k: (v or "") for k, v in m.groupdict().items()}
    return g, re.sub(r"\s+", " ", m.group(0)).strip()


def _date_hits(first: str, journal) -> dict:
    """1 ページ目の日付の一致をラベルごとにすべて集める（{ラベルの種類: 出てきた順の ISO 形式の一覧〈同じ値も重ねる〉}）。
    読むのは組版の形の日付だけ: 「日付＋ラベル」が区切り（「，」など）でつながった 2 つ以上の並び
    （「2029年６月１日投稿受付，2029年11月20日採用決定」。照合の `pdfmatch.RE_RECEIVED` と同じ形で、日付とラベルの間・数字の間の
    空白や改行、本文の行の前後へのつながりは許す）。本文の文の中の日付（「…2020年1月1日採用決定と記されている」）は、
    1 つだけで並びにならないので読まない。読めなかった日付は、利用者が入力する。"""
    labels = {k: v for k, v in (getattr(journal, "pdf_date_labels", None) or {}).items() if v}
    if not labels:
        return {}
    from .pdfmatch import _RECEIVED, _RECEIVED_SEP      # 照合と同じ日付＋ラベルの形（RE_RECEIVED の部品）
    run = re.compile(rf"{_RECEIVED}(?:{_RECEIVED_SEP}{_RECEIVED})+")
    # 「投稿受付」は「再投稿受付」の一部なので、長いラベルから当てる
    alt = "|".join(re.escape(v) for v in sorted(labels.values(), key=len, reverse=True))
    out: dict = {}
    by_label = {v: k for k, v in labels.items()}
    for m in run.finditer(first):
        text = re.sub(r"\s", "", m.group(0))
        for y, mo, d, lab in re.findall(r"(\d{4})年(\d{1,2})月(\d{1,2})日(" + alt + ")", text):
            try:
                iso = _dt.date(int(y), int(mo), int(d)).isoformat()
            except ValueError:
                continue
            out.setdefault(by_label[lab], []).append(iso)
    return out


def biblio_from_pages(pages: list, journal) -> PdfBiblio:
    """PDF の各ページの文字（`pdfmatch.extract_pages` の結果）から書誌情報を読む。1 ページ目だけを見る。"""
    b = PdfBiblio(pages=len(pages))
    if not pages:
        return b
    first = _nfkc(pages[0])
    # 行の中の空白の揺れ（連続・全角・タブ）は 1 つの空白にそろえる。改行は \s* が許す
    first = re.sub(r"[ \t　]+", " ", first)
    g, line = _issue_line(first, journal)
    b.volume, b.issue, b.year = g.get("volume", ""), g.get("issue", ""), g.get("year", "")
    b.fpage, b.lpage = g.get("fpage", ""), g.get("lpage", "")
    b.line = line
    hits = _date_hits(first, journal)
    d = {k: v[0] for k, v in hits.items() if len(set(v)) == 1}
    b.ambiguous = tuple(k for k, v in hits.items() if len(set(v)) > 1)
    b.received, b.revised, b.accepted = d.get("received", ""), d.get("revised", ""), d.get("accepted", "")
    return b


def read_biblio(pdf_path, journal) -> PdfBiblio:
    """PDF の 1 ページ目から書誌情報を読む。PDF を開けない・読めない項目は空で、例外にしない。"""
    try:
        from .pdfmatch import extract_pages
        pages = extract_pages(pdf_path)
    except Exception:    # PDF の読み取りの失敗は、書誌情報を読めなかったことにするだけ（照合の側が別に知らせる）
        return PdfBiblio()
    try:
        return biblio_from_pages(pages, journal)
    except Exception:
        return PdfBiblio(pages=len(pages))


def biblio_inputs(b: PdfBiblio) -> dict:
    """入力欄に入れる文字列（読めた項目だけ。キーは ArticleMeta の欄の名前）。"""
    return {k: getattr(b, k) for k in INPUT_KEYS if getattr(b, k)}


def fill_missing(meta_input: dict, b: PdfBiblio) -> tuple:
    """入力（ArticleMeta.from_dict に渡す辞書）の空の欄だけを PDF の値で埋める。(新しい辞書, 埋めた欄の名前の一覧) を返す。

    入力済みの欄は変えない（違いは変換の後の知らせ meta_pdf に任せる）。元の辞書は変えない。
    """
    out = dict(meta_input or {})
    filled = []
    for k, v in biblio_inputs(b).items():
        cur = out.get(k)
        if cur is None or (isinstance(cur, str) and not cur.strip()):
            out[k] = v
            filled.append(LABELS[k])
    return out, filled


def _same_id(a: str, b: str) -> bool:
    a, b = _nfkc(str(a)).strip(), _nfkc(str(b)).strip()
    if a.isdigit() and b.isdigit():
        return int(a) == int(b)
    return a == b


def _int(v) -> Optional[int]:
    s = _nfkc(str(v or "")).strip()
    return int(s) if s.isdigit() else None


def page_count_ok(fpage, lpage, pages: int) -> bool:
    """PDF のページ数が「最後 − 最初 ＋ 1」か「＋ 2」（最終ページの次に奥付などが続く形）なら True。比べられなければ True。"""
    f, l = _int(fpage), _int(lpage)
    if f is None or l is None or l < f or not pages:
        return True
    n = l - f + 1
    return pages in (n, n + 1)


def unread_dates(meta, b: PdfBiblio) -> list:
    """入力があるのに、PDF に違う日付が複数あって読めなかった（採らなかった）受付日・受理日の欄の名前の一覧。
    違いではないので `mismatches` には入れない（比べていないだけ。PDF を見て確かめてもらう）。入力が空なら言わない。"""
    return [LABELS[k] for k in ("received", "accepted") if getattr(meta, k, None) and k in b.ambiguous]


def mismatches(meta, b: PdfBiblio) -> list:
    """入力（ArticleMeta）が PDF から読んだ値と違う項目の一覧 [(欄の名前, 入力, PDF)]。

    PDF から読めなかった項目（違う日付が複数あって採らなかった受付日・受理日を含む。それは `unread_dates`）と、入力が空の項目は比べない。比べるのは、巻・号・最初と最後のページ・受付日・受理日、
    発行日を入れていればその年、PDF のページ数（ページの範囲から数えた数と合うか）。再受付日は比べない。
    """
    out = []
    for k in ("volume", "issue", "fpage", "lpage"):
        mine, pdf = getattr(meta, k, "") or "", getattr(b, k)
        if mine and pdf and not _same_id(mine, pdf):
            out.append((LABELS[k], str(mine), pdf))
    for k in ("received", "accepted"):
        mine, pdf = getattr(meta, k, None), getattr(b, k)
        if mine and pdf and mine.isoformat() != pdf:
            out.append((LABELS[k], mine.isoformat(), pdf))
    pub = getattr(meta, "pub_date", None)
    if pub and b.year and str(pub.year) != b.year:
        out.append(("発行日の年", str(pub.year), b.year))
    f, l = getattr(meta, "fpage", ""), getattr(meta, "lpage", "")
    if not page_count_ok(f, l, b.pages):
        n = _int(l) - _int(f) + 1
        out.append(("ページ数", f"{f}〜{l}（{n} ページ）", f"{b.pages} ページ"))
    return out
