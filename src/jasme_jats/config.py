"""雑誌の設定（config/*.toml）と記事ごとの書誌情報。"""
from __future__ import annotations

import datetime as _dt
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
    article_type: str = "research-article"
    subject_ja: str = "論文"
    lang: str = "ja"
    abstract_specific_use: str = "secondary-disallow"
    split_labels: bool = False
    styles: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "JournalConfig":
        path = Path(path) if path else DEFAULT_CONFIG
        with open(path, "rb") as f:
            data = tomllib.load(f)
        j = data.get("journal", {})
        d = data.get("defaults", {})
        return cls(styles=data.get("styles", {}), **j, **d)


def _date(v) -> Optional[_dt.date]:
    if v in (None, ""):
        return None
    if isinstance(v, _dt.date):
        return v
    s = str(v).strip().replace("/", "-").replace(".", "-")
    if len(s) == 8 and s.isdigit():
        s = f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return _dt.date.fromisoformat(s)


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
    doi: str = ""                               # 空なら doi_pattern から作る
    article_type: str = ""
    subject_ja: str = ""
    lang: str = ""
    keywords_en: list = field(default_factory=list)
    keywords_ja: list = field(default_factory=list)
    corresp: list = field(default_factory=list)  # 責任著者の番号（1 始まり）

    @classmethod
    def from_dict(cls, d: dict) -> "ArticleMeta":
        d = dict(d or {})
        for k in ("pub_date", "epub_date", "received", "revised", "accepted"):
            d[k] = _date(d.get(k))
        for k in ("volume", "issue", "fpage", "lpage", "doi"):
            if k in d and d[k] is not None:
                d[k] = str(d[k]).strip()
        for k in ("keywords_en", "keywords_ja"):
            v = d.get(k)
            if isinstance(v, str):
                d[k] = [x.strip() for x in v.replace("，", ",").replace("、", ",").split(",") if x.strip()]
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
