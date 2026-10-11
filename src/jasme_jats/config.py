"""雑誌の設定（config/*.toml）と記事ごとの書誌情報。"""
from __future__ import annotations

import datetime as _dt
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = PACKAGE_DIR / "data" / "jasme.toml"


@dataclass
class JournalConfig:
    journal_id: str
    title_ja: str
    title_en: str
    abbrev: str
    issn_print: str
    issn_online: str
    publisher_ja: str
    publisher_en: str
    doi_pattern: str
    article_id_pattern: str
    image_name_pattern: str
    article_type: str = "other"
    subject_ja: str = "論文"
    subject_en: str = "Article"
    lang: str = "ja"
    abstract_specific_use: str = "secondary-disallow"
    split_labels: bool = False
    ref_doi: str = "pub-id"
    styles: dict = field(default_factory=dict)
    manuscript_types: dict = field(default_factory=dict)   # 原稿種別の選択肢（日本語 → 英語）

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "JournalConfig":
        path = Path(path) if path else DEFAULT_CONFIG
        with open(path, "rb") as f:
            data = tomllib.load(f)
        j = data.get("journal", {})
        d = data.get("defaults", {})
        return cls(styles=data.get("styles", {}), manuscript_types=data.get("manuscript_types", {}), **j, **d)

    def subjects(self, meta) -> tuple:
        """原稿種別（日本語, 英語）。英語が入力されていなければ、選択肢の対応表から決める。"""
        ja = meta.subject_ja or self.subject_ja
        en = meta.subject_en or self.manuscript_types.get(ja) or (self.subject_en if ja == self.subject_ja else "")
        return ja, en


def _date(v) -> Optional[_dt.date]:
    if v in (None, ""):
        return None
    if isinstance(v, _dt.date):
        return v
    s = str(v).strip().replace("/", "-").replace(".", "-")
    if not s:
        return None
    if len(s) == 8 and s.isdigit():
        s = f"{s[:4]}-{s[4:6]}-{s[6:]}"
    try:
        return _dt.date.fromisoformat(s)
    except ValueError:
        raise ValueError(f"日付「{v}」を読めません（YYYY-MM-DD の形で入力してください）") from None


RE_JA_CHARS = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uf900-\uff65々]")
KEYWORDS_MAX = 100


def split_keywords(v) -> tuple:
    """「;」「；」区切りのキーワードを (日本語, 英語) に分ける。リストで渡されたらその要素ごと。"""
    items = v if isinstance(v, (list, tuple)) else re.split(r"[;；]", str(v))
    ja, en = [], []
    for k in items:
        k = str(k).strip()
        if k:
            (ja if RE_JA_CHARS.search(k) else en).append(k)
    return ja, en


def keyword_problem(meta) -> str:
    """キーワードが J-STAGE の上限（日・英あわせて 100 個）を超えていれば理由を返す。キーワードは任意。"""
    n = len(meta.keywords_ja) + len(meta.keywords_en)
    if n > KEYWORDS_MAX:
        return f"キーワードが日・英あわせて {n} 個ある（J-STAGE の上限は {KEYWORDS_MAX} 個）"
    return ""


def keyword_language_mismatch(meta) -> list:
    """日本語の欄に英語だけのキーワード、英語の欄にかな・漢字を含むキーワードがあれば、その一覧（入力欄の取り違えの確認用）。"""
    return ([k for k in meta.keywords_ja if not RE_JA_CHARS.search(k)]
            + [k for k in meta.keywords_en if RE_JA_CHARS.search(k)])


_PEER_REVIEW = {"yes": "yes", "true": "yes", "あり": "yes", "査読あり": "yes", "有": "yes", "有り": "yes",
                "no": "no", "false": "no", "なし": "no", "査読なし": "no", "無": "no", "無し": "no"}


def _peer_review(v) -> str:
    """査読の有無を "yes" / "no" / ""（未入力）にそろえる。"""
    if isinstance(v, bool):
        return "yes" if v else "no"
    s = str(v or "").strip()
    if s in ("", "（選んでください）"):
        return ""
    if s.lower() in _PEER_REVIEW:
        return _PEER_REVIEW[s.lower()]
    raise ValueError(f"査読の有無「{v}」を読めません（「あり」か「なし」で指定してください）")


@dataclass
class ArticleMeta:
    """記事ごとに利用者が入力する書誌情報（docx には書かれていないもの）。"""
    volume: str = ""
    issue: str = ""
    fpage: str = ""
    lpage: str = ""
    pub_date: Optional[_dt.date] = None        # 発行日（pub-type="ppub"）
    epub_date: Optional[_dt.date] = None       # J-STAGE 公開日（pub-type="epub"）
    received: Optional[_dt.date] = None
    revised: Optional[_dt.date] = None
    accepted: Optional[_dt.date] = None
    peer_review: str = ""                       # 査読の有無: "yes" / "no" / ""（未入力）
    approved: Optional[_dt.date] = None        # 最終査読日（査読ありのとき。分からなければ空）
    doi: str = ""                               # 空なら doi_pattern から作る
    article_type: str = ""
    subject_ja: str = ""
    subject_en: str = ""
    lang: str = ""
    keywords_en: list = field(default_factory=list)
    keywords_ja: list = field(default_factory=list)
    corresp: list = field(default_factory=list)  # 責任著者の番号（1 始まり）

    @classmethod
    def from_dict(cls, d: dict) -> "ArticleMeta":
        d = dict(d or {})
        for k in ("pub_date", "epub_date", "received", "revised", "accepted", "approved"):
            d[k] = _date(d.get(k))
        d["peer_review"] = _peer_review(d.get("peer_review"))
        for k in ("volume", "issue", "fpage", "lpage", "doi"):
            if k in d and d[k] is not None:
                d[k] = str(d[k]).strip()
        for k in ("keywords_en", "keywords_ja"):
            v = d.get(k)
            if isinstance(v, str):
                d[k] = [x.strip() for x in re.split(r"[;；]", v) if x.strip()]
        # キーワードを 1 つの欄で受け取る場合（「;」「；」区切り）。かな・漢字を含むものは日本語、それ以外は英語のキーワード
        if d.get("keywords"):
            ja, en = split_keywords(d["keywords"])
            d["keywords_ja"] = list(d.get("keywords_ja") or []) + ja
            d["keywords_en"] = list(d.get("keywords_en") or []) + en
        if isinstance(d.get("corresp"), (int, str)):
            d["corresp"] = [int(x) for x in str(d["corresp"]).replace("，", ",").split(",") if str(x).strip()]
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    @classmethod
    def load(cls, path) -> "ArticleMeta":
        with open(path, "rb") as f:
            return cls.from_dict(tomllib.load(f).get("article", {}))

    def article_id(self, j: JournalConfig) -> str:
        if not (self.volume and self.fpage):
            return "article"
        return j.article_id_pattern.format(volume=self.volume, issue=self.issue or "0", fpage=self.fpage)

    def doi_value(self, j: JournalConfig) -> str:
        if self.doi:
            return self.doi
        if self.volume and self.fpage and j.doi_pattern:
            return j.doi_pattern.format(volume=self.volume, issue=self.issue or "0", fpage=self.fpage)
        return ""
