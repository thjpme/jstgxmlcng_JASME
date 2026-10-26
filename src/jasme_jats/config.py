"""雑誌の設定（config/*.toml）と記事ごとの書誌情報。"""
from __future__ import annotations

import datetime as _dt
import re
import sys
import unicodedata
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
    fn_mark: str = "{n})"
    fn_title: str = "注"
    fn_title_en: str = "Notes"
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


# 日付の書き方（NFKC にして空白を除いた後）: 20260331、2026-03-31・2026/3/31・2026.3.31・2026年3月31日。2 桁の年と和暦は読まない
RE_DATE8 = re.compile(r"([0-9]{4})([0-9]{2})([0-9]{2})")
RE_DATE = re.compile(r"([0-9]{4})[-/.年]([0-9]{1,2})[-/.月]([0-9]{1,2})日?")


def _date(v, label="日付") -> Optional[_dt.date]:
    """入力された日付を date にする。空なら None。読めなければ、欄の名前（label）を入れた ValueError。

    date.fromisoformat は使わない（Python の版で読める形が違う。3.11 以降は 2026-W13-2 なども読む）。
    """
    if v is None:
        return None
    if isinstance(v, _dt.datetime):          # datetime は date の派生なので先に判定する（TOML の引用符なしの日時）
        return v.date()
    if isinstance(v, _dt.date):
        return v
    s = re.sub(r"\s", "", unicodedata.normalize("NFKC", str(v)))
    if not s:
        return None
    m = RE_DATE8.fullmatch(s) or RE_DATE.fullmatch(s)
    if m:
        try:
            return _dt.date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            pass
    raise ValueError(f"{label}「{v}」を読めません（YYYY-MM-DD の形で入力してください。2026/3/31 のようにも書けます）")


# 書誌情報の日付の欄（ArticleMeta の項目 -> 欄の名前。Colab の手順 3 とレポートの 11 章の名前）
DATE_FIELDS = {"pub_date": "発行日", "epub_date": "J-STAGE 公開日", "received": "受付日", "revised": "再受付日",
               "accepted": "受理日", "approved": "最終査読日"}
# 巻・号・ページの欄。巻・号・開始ページは J-STAGE のフォルダ名・ファイル名（記事識別子）と DOI に使うので、半角の英数字だけにする
PAGE_FIELDS = {"volume": "巻", "issue": "号", "fpage": "最初のページ", "lpage": "最後のページ"}
ID_FIELDS = ("volume", "issue", "fpage")
RE_ALNUM = re.compile(r"[A-Za-z0-9]+")


def _shown_char(c: str) -> str:
    """知らせに出す使えない文字。空白は「空白」、幅のない文字・制御文字などの見えない文字は「見えない文字」と書く。"""
    if c.isspace():
        return "空白"
    if unicodedata.category(c) in ("Cf", "Cc", "Co", "Cn", "Zs", "Zl", "Zp"):
        return "見えない文字"
    return c


def _id_value(key: str, v, notes: list) -> str:
    """巻・号・ページの入力を NFKC で正規化する（全角の数字は半角にし、notes に知らせを足す）。

    巻・号・開始ページに半角の英数字以外が残れば、欄の名前と、その文字を入れた ValueError（決定事項 3）。
    """
    raw = str(v).strip()
    s = unicodedata.normalize("NFKC", raw).strip()
    label = PAGE_FIELDS[key]
    if key in ID_FIELDS and s and not RE_ALNUM.fullmatch(s):
        bad = list(dict.fromkeys(_shown_char(c) for c in s if not RE_ALNUM.fullmatch(c)))
        shown = "」「".join(bad)
        if any(len(c) == 1 and not c.isascii() for c in bad):
            why = "全角の文字（漢字・かな・記号など）は使えません"
        elif "見えない文字" in bad:
            why = "見えない文字は使えません。貼り付けたときに入ることがあるので、欄を空にして打ち直してください"
        else:
            why = "記号・空白は使えません"
        raise ValueError(f"{label}「{raw}」に、使えない文字「{shown}」があります。{label}は半角の英数字だけで入力してください"
                         f"（例: {'31' if key == 'volume' else '1'}。{why}。J-STAGE のフォルダ名・ファイル名に使うためです）")
    if s != raw:
        notes.append(f"{label}「{raw}」を「{s}」として読みました（全角の文字を半角にしました）")
    return s


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
    input_notes: list = field(default_factory=list)  # 入力値を直した知らせ（全角の数字を半角にしたなど。XML には出さない）

    @classmethod
    def from_dict(cls, d: dict) -> "ArticleMeta":
        d = dict(d or {})
        for k, label in DATE_FIELDS.items():
            d[k] = _date(d.get(k), label)
        d["peer_review"] = _peer_review(d.get("peer_review"))
        notes = []
        for k in PAGE_FIELDS:
            if k in d and d[k] is not None:
                d[k] = _id_value(k, d[k], notes)
        if d.get("doi") is not None:
            d["doi"] = str(d["doi"]).strip()
        d["input_notes"] = notes
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
