"""冒頭部（題目・著者名・所属）の確かめ（修正計画 W6 と、C009・C015・C016・C035・C036）。

plan（ArticlePlan）を読むだけで、docx の文字も XML の構造も変えない。知らせは report.actions() の Action
（要対応 `authors_missing`・要対応か要確認 `front_check`）だけで、この module は「どの段落に何があるか」を返す。

- 和文の著者名が 1 人もない（`authors_missing`。`authors_missing_applies`・`author_candidates`）。
- 冒頭部の項目（`FrontFinding`。`plan_findings`）: テンプレートの見本の行（template）・題目の段落が 2 つ以上（title_multi）・題目の段落がない
  （title_missing）・翻訳の題目がなく副題だけがある（subtitle_orphan）・所属と氏名の入れ替わり（swap）・和文の著者の欠け（ja_missing・aff_missing）・英文の著者の欠け（en_missing・en_count）。
- 出版版 PDF との確かめ（pdf_missing・pdf_near・pdf_en_missing。`pdf_findings`）。ページの文字を受け取って判定するだけで、
  PDF の文字を docx に足さない・直さない。docx → XML の処理は PDF の有無で変わらない（結果は知らせにだけ使う）。

和文の著者名が 1 人もないとき（authors_missing）は、和文の所属・英文の著者数の食い違い（ja_missing・aff_missing・en_count）を出さない
（同じ原因を 2 つの要対応で言わない）。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from .pdfmatch import OBJ, TITLE_MIN, TITLE_RATIO, _title_ratio, core
from .structure import (AUTHOR_TABLE_OTHER_EXCLUDED, EN_AUTHOR_TABLE_OTHER_EXCLUDED, EN_OTHER_EXCLUDED, FRONT_OTHER_EXCLUDED,
                        FRONT_TABLE_EXCLUDED, HEADING_LEVEL, abstract_missing_srcs)

MUST = "must"
CHECK = "check"

# 項目の種類
TEMPLATE = "template"
TITLE_MULTI = "title_multi"
TITLE_MISSING = "title_missing"
SUB_ORPHAN = "subtitle_orphan"
SWAP = "swap"
JA_MISSING = "ja_missing"
AFF_MISSING = "aff_missing"
EN_MISSING = "en_missing"
EN_COUNT = "en_count"
PDF_MISSING = "pdf_missing"
PDF_NEAR = "pdf_near"
PDF_EN_MISSING = "pdf_en_missing"

# 項目の並び（知らせの文の順）と重さ。PDF の項目は、出版版 PDF との違いなので要確認にとどめる（CLAUDE.md の PDF の区分: 内容の違いは
# 要確認。要対応にするのは、形から確かな template・swap の一部・著者名の欠けだけ）
KIND_ORDER = (TEMPLATE, TITLE_MISSING, SUB_ORPHAN, JA_MISSING, AFF_MISSING, SWAP, TITLE_MULTI, EN_MISSING, EN_COUNT,
              PDF_MISSING, PDF_NEAR, PDF_EN_MISSING)
KIND_LEVEL = {TEMPLATE: MUST, TITLE_MISSING: MUST, SUB_ORPHAN: MUST, JA_MISSING: MUST, AFF_MISSING: MUST, SWAP: CHECK, TITLE_MULTI: CHECK,
              EN_MISSING: CHECK, EN_COUNT: CHECK, PDF_MISSING: CHECK, PDF_NEAR: CHECK, PDF_EN_MISSING: CHECK}

CANDIDATE_REASONS = (FRONT_OTHER_EXCLUDED, FRONT_TABLE_EXCLUDED, AUTHOR_TABLE_OTHER_EXCLUDED)
EN_CANDIDATE_REASONS = (EN_AUTHOR_TABLE_OTHER_EXCLUDED, EN_OTHER_EXCLUDED)
MAX_CANDIDATES = 6          # 候補の段落の数の上限（知らせの文に並べる数。本文の段落が長く続いても増やさない）
CANDIDATE_MAX_LEN = 80      # 本文の段落を候補にする長さの上限（著者名・所属・題目らしい短い段落）


@dataclass
class FrontFinding:
    """冒頭部の確かめの項目 1 つ。kind: 項目の種類。level: MUST（要対応）か CHECK（要確認）。srcs: 段落 ID（docx の順）。
    note: 文に添える短い材料（所属の語・場所など。原稿の文字の抜粋は添えない）。"""
    kind: str
    level: str
    srcs: list = field(default_factory=list)
    note: str = ""


def finding(kind, srcs, note="") -> FrontFinding:
    return FrontFinding(kind, KIND_LEVEL[kind], list(srcs), note)


def nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "")


def article_lang(plan, meta, journal) -> str:
    """記事の言語（builder.Builder.article_lang と同じ規則）。"""
    return getattr(meta, "lang", "") or plan.lang or getattr(journal, "lang", "")


def text_of(plan, src) -> str:
    p = plan.paras.get(src)
    return p.text_only() if p is not None else ""


def _order(plan) -> dict:
    return {src: i for i, src in enumerate(plan.paras)}


def _srcs_in_order(plan, srcs) -> list:
    order = _order(plan)
    return sorted(dict.fromkeys(srcs), key=lambda s: order.get(s, len(order)))


def starts_with_dash(text) -> bool:
    """段落の文字がダッシュ・波ダッシュなどで始まるか（題目の 2 段落目が副題のようかの目安）。"""
    return text.strip()[:1] in tuple("―－—–〜~-")


def label_of(plan, src) -> str:
    """段落 src の項目の名前（題目・副題・著者名・所属。和文・英文の別つき。なければ ""）。"""
    for names, paras in (("題目（日）", plan.title), ("副題（日）", plan.subtitle), ("題目（英）", plan.title_en),
                         ("副題（英）", plan.subtitle_en)):
        if any(p.src == src for p in paras):
            return names
    for a in plan.authors:
        if a.name_ja is not None and a.name_ja.src == src:
            return "著者名（日）"
        if a.name_en is not None and a.name_en.src == src:
            return "著者名（英）"
    for x in plan.affs:
        if x.ja is not None and x.ja.src == src:
            return "所属（日）"
        if x.en is not None and x.en.src == src:
            return "所属（英）"
    return ""


def _paras(items) -> list:
    return [p for p in items if p is not None and p.text_only().strip()]


# ---------------------------------------------------------------------------- 和文の著者名が 1 人もない（C009）
def authors_missing_applies(plan, lang) -> bool:
    """記事が和文なのに、和文の著者名が 1 人もない（要対応 authors_missing）。英文の記事では見ない。"""
    return lang != "en" and not any(a.name_ja is not None and a.name_ja.text_only().strip() for a in plan.authors)


def _title_end(plan) -> int:
    """題目の段落（和文）の最後の位置（plan.paras の順。なければ -1）。"""
    order = _order(plan)
    return max((order[p.src] for p in plan.title if p.src in order), default=-1)


def _first_heading(plan) -> int:
    """本文の最初の章・節・項の見出し（空白だけの段落を除く）の位置（plan.paras の順。なければ無限大）。"""
    for i, (src, p) in enumerate(plan.paras.items()):
        if plan.region.get(src) == "body" and p.role in HEADING_LEVEL and not p.is_blank:
            return i
    return float("inf")


def author_candidates(plan, skip=()) -> list:
    """和文の著者名・所属らしい段落の ID（docx の順。最大 MAX_CANDIDATES 個）。題目より後ろで、
    (a) 位置を決められずに除外した冒頭部の段落（FRONT_OTHER_EXCLUDED・FRONT_TABLE_EXCLUDED・AUTHOR_TABLE_OTHER_EXCLUDED）、
    (b) 本文の領域で、最初の章・節・項の見出しより前の短い段落（スタイルがなく本文になった著者表のセルなど）。空白だけの段落は除く。
    「らしい」段落を挙げるだけで、要対応の理由（和文の著者名が 1 人もない）は候補の当たり外れで変えない。"""
    reason = {e.src: e.reason for e in plan.exclusions if not e.blank}
    t_end, head = _title_end(plan), _first_heading(plan)
    out = []
    for i, (src, p) in enumerate(plan.paras.items()):
        if i <= t_end or src in skip or p.is_blank or src.startswith("f"):
            continue
        text = p.text_only().strip()
        if not text:
            continue
        if reason.get(src) in CANDIDATE_REASONS:
            out.append(src)
        elif (plan.region.get(src) == "body" and i < head and len(text) <= CANDIDATE_MAX_LEN
              and p.role not in ("fig_caption", "table_caption", "fn")):
            out.append(src)
    return out[:MAX_CANDIDATES]


def title_candidates(plan) -> list:
    """和文の題目らしい段落（題目の段落がないとき）: 本文の領域の、最初の章・節・項の見出しより前の最初の段落（表のセルを除く）。"""
    head = _first_heading(plan)
    for i, (src, p) in enumerate(plan.paras.items()):
        if i >= head:
            break
        if plan.region.get(src) == "body" and src not in plan.cell_paras and not p.is_blank and not src.startswith("f") \
                and p.role not in ("fig_caption", "table_caption", "fn") and len(p.text_only().strip()) <= CANDIDATE_MAX_LEN:
            return [src]
    return []


# ---------------------------------------------------------------------------- テンプレートの見本の行（C015）
PLACEHOLDER_WORD = re.compile(r"^(氏名|所属|著者名?|name|affiliation|author)[0-9]*(\(.*\))?$", re.I)
PLACEHOLDER_FONT = re.compile(r"\([^()]*(明朝|ゴシック|century|times|arial|メイリオ|meiryo)[^()]*\d+(\.\d+)?pt[^()]*\)\s*$", re.I)


def template_placeholder(text) -> bool:
    """テンプレートの見本の文字か（「氏名２(MS明朝，11pt)」「Name2 (Century, 11pt)」など）。NFKC にして空白を除いた文字が、
    見本の語（氏名・所属・著者名・Name・Affiliation・Author）＋番号＋かっこ、か、末尾にフォント名と「NNpt」の書式見本のかっこがある形。
    番号つきの語と書式見本のかっこに限り、実名と取り違えない。白字かどうかは見ない（黒字の残りも拾う）。"""
    t = re.sub(r"\s+", "", nfkc(text))
    if not t:
        return False
    return bool(PLACEHOLDER_WORD.match(t) or PLACEHOLDER_FONT.search(t))


def _template_srcs(plan) -> list:
    paras = [a.name_ja for a in plan.authors] + [a.name_en for a in plan.authors]
    paras += [x.ja for x in plan.affs] + [x.en for x in plan.affs]
    return [p.src for p in _paras(paras) if template_placeholder(p.text_only())]


# ---------------------------------------------------------------------------- 所属と氏名の入れ替わり（C036）
AFF_WORDS = ("大学", "学校", "高校", "高専", "学園", "学院", "研究科", "研究所", "研究院", "学部", "学科", "センター", "教育委員会",
             "機構", "附属", "付属", "University", "School", "College", "Institute", "Graduate", "Faculty", "Department")
NAME_SHAPE = re.compile(r"^\S{1,5}[\s　]+\S{1,5}$")


def aff_word(text) -> str:
    """所属の語（少なめの一覧。AFF_WORDS）が文字にあれば、その語。なければ ""。"""
    t = nfkc(text)
    low = t.lower()
    return next((w for w in AFF_WORDS if (w in t if not w.isascii() else w.lower() in low)), "")


def name_shaped(text) -> bool:
    """氏名の形か（空白で区切った 1〜5 字の 2 語で、所属の語を含まない）。"""
    t = nfkc(text).strip()
    return bool(NAME_SHAPE.match(t)) and not aff_word(t)


def orphan_subtitle(plan, lang) -> tuple:
    """翻訳の題目（builder.title_group の other）がなく、翻訳の副題（other_sub）だけがあるときの (副題の名前, 副題の段落の列)。なければ ("", [])。
    本文の言語の選び方は builder.title_group と同じ（英文の記事で題目（英）があれば翻訳は和文、それ以外は翻訳が英文）。"""
    if lang == "en" and plan.title_en:
        title, sub, label = plan.title, plan.subtitle, "副題（日）"
    else:
        title, sub, label = plan.title_en, plan.subtitle_en, "副題（英）"
    if _paras(title) or not sub:
        return "", []
    return label, list(sub)


def _swap(plan) -> FrontFinding | None:
    srcs, words = [], []
    for a in plan.authors:
        if a.name_ja is None:
            continue
        w = aff_word(a.name_ja.text_only())
        if not w:
            continue
        srcs.append(a.name_ja.src)
        words.append(w)
        for x in a.affs:
            if x.ja is not None and name_shaped(x.ja.text_only()):
                srcs.append(x.ja.src)
    if not srcs:
        return None
    return finding(SWAP, _srcs_in_order(plan, srcs), "、".join(dict.fromkeys(words)))


# ---------------------------------------------------------------------------- 項目の判定
def plan_findings(plan, lang) -> list:
    """PDF の要らない項目（FrontFinding）の一覧（KIND_ORDER の順）。plan を読むだけ。"""
    out = []
    tmpl = _template_srcs(plan)
    if tmpl:
        out.append(finding(TEMPLATE, _srcs_in_order(plan, tmpl)))
    ja = lang != "en"
    if ja and not _paras(plan.title):
        out.append(finding(TITLE_MISSING, title_candidates(plan)))
    label, sub = orphan_subtitle(plan, lang)
    if _paras(sub):
        out.append(finding(SUB_ORPHAN, [p.src for p in _paras(sub)], label))
    for kind, label, paras in (("ja", "題目（日）", plan.title), ("ja", "副題（日）", plan.subtitle),
                               ("en", "題目（英）", plan.title_en), ("en", "副題（英）", plan.subtitle_en)):
        ps = _paras(paras)
        if len(ps) >= 2:
            out.append(finding(TITLE_MULTI, [p.src for p in ps], label))
    missing = authors_missing_applies(plan, lang)
    if ja and not missing:
        sw = _swap(plan)
        if sw is not None:
            out.append(sw)
        only_en = [a for a in plan.authors if a.name_en is not None and a.name_en.text_only().strip() and not (
            a.name_ja is not None and a.name_ja.text_only().strip())]
        if only_en:
            out.append(finding(JA_MISSING, [a.name_en.src for a in only_en]))
        if not any(x.ja is not None and x.ja.text_only().strip() for x in plan.affs):
            reason = {e.src: e.reason for e in plan.exclusions if not e.blank}
            out.append(finding(AFF_MISSING, [s for s in plan.paras if reason.get(s) == AUTHOR_TABLE_OTHER_EXCLUDED][:MAX_CANDIDATES]))
    if _paras(plan.title_en) and not any(a.name_en is not None and a.name_en.text_only().strip() for a in plan.authors):
        out.append(finding(EN_MISSING, en_candidates(plan)))
    elif ja and not missing:
        has_en = any(a.name_en is not None and a.name_en.text_only().strip() for a in plan.authors)
        only_ja = [a.name_ja.src for a in plan.authors if a.name_ja is not None and a.name_ja.text_only().strip()
                   and not (a.name_en is not None and a.name_en.text_only().strip())]
        covered = set(tmpl) | {s for f in out if f.kind == SWAP for s in f.srcs}
        if has_en and only_ja and not set(only_ja) <= covered:
            out.append(finding(EN_COUNT, only_ja))
    rank = {k: i for i, k in enumerate(KIND_ORDER)}
    out.sort(key=lambda f: rank[f.kind])
    return out


def en_candidates(plan) -> list:
    """英文の著者名・所属らしい段落（英文の題目の後ろ・英文要旨の見出しの前に除外した、スタイルのない段落）。"""
    reason = {e.src: e.reason for e in plan.exclusions if not e.blank}
    order = _order(plan)
    start = max((order[p.src] for p in plan.title_en + plan.subtitle_en if p.src in order), default=-1)
    stop = order.get(plan.abstract_heading.src, float("inf")) if plan.abstract_heading is not None else float("inf")
    skip = set(abstract_missing_srcs(plan))
    out = [s for s in plan.paras if reason.get(s) in EN_CANDIDATE_REASONS and start < order[s] < stop
           and s not in skip and text_of(plan, s).strip()]
    return out[:MAX_CANDIDATES]


def front_findings(plan, lang, pdf_front=()) -> list:
    """report が使う: plan_findings ＋ 出版版 PDF の項目（pdf_front。pdf_findings の結果）。同じ段落が template・swap などと PDF の項目の
    両方に挙がるときは PDF の項目の側から外す（1 つの段落を 2 回言わない）。PDF の項目だけで段落が残らなければ捨てる。"""
    base = plan_findings(plan, lang)
    seen = {s for f in base for s in f.srcs}
    extra = []
    for f in pdf_front:
        left = [s for s in f.srcs if s not in seen]
        if left:
            extra.append(FrontFinding(f.kind, f.level, left, f.note))
    return sorted(base + extra, key=lambda f: KIND_ORDER.index(f.kind))


def finding_srcs(findings) -> set:
    """項目に挙がった段落の ID（要確認 name_split・style_check・excluded_unsure などで、同じ段落を重ねて挙げないために使う）。"""
    return {s for f in findings for s in f.srcs}


# ---------------------------------------------------------------------------- 出版版 PDF との確かめ（W6）
NAME_NEAR = 0.6         # 和文の項目が題目のページの文字と「少し違う」とみなす一致の割合（推測。46 docx で、見つからない 2 件が 0.27・0.36、
#                         あるべきものはすべてそのままある。実物の次の号で測り直す）
ITEM_MIN = 2            # 見る和文の項目の長さの下限（core の文字数。これより短い項目は偶然の一致と区別できない）


def _core_of(para) -> str:
    return core(para.plain().replace(OBJ, ""))


def title_page(plan, pages) -> int:
    """和文の題目のあるページの番号（0 から）。題目（core。TITLE_MIN 字以上）がそのままある最初のページ。なければ、題目との一致の割合
    （pdfmatch._title_ratio）が TITLE_RATIO 以上でいちばん高いページ。どちらもなければ（題目がない・短い）0。
    号全体の PDF（題目が後ろのページ）でも、題目のあるページから探して、誤って知らせない。"""
    title = "".join(_core_of(p) for p in plan.title)
    if len(title) < TITLE_MIN:
        return 0
    cores = [core(x) for x in pages]
    for i, c in enumerate(cores):
        if title in c:
            return i
    best, at = 0.0, 0
    for i, x in enumerate(pages):
        r = _title_ratio(title, [x])
        if r > best:
            best, at = r, i
    return at if best >= TITLE_RATIO else 0


def _window_ratio(item: str, text: str) -> float:
    """item（core）と text（core）の、同じ長さの窓の一致の割合のいちばん高いもの（pdfmatch._title_ratio と同じ作りで、
    ページではなく文字列に対して）。"""
    return _title_ratio(item, [text])


def name_words(text) -> set:
    """英文の氏名の語の集合（NFKC にした文字の、文字だけのつながり。数字・記号〈所属の印の「*1」など〉は除く）。姓と名の順は見ない。"""
    return set(re.findall(r"[^\W\d_]+", nfkc(text)))


def pdf_findings(plan, pages, res) -> tuple:
    """出版版 PDF（pages: 各ページの文字。res: pdfmatch.compare の結果）と照らした冒頭部の項目 [FrontFinding] と、題目のページ（と次の
    ページ）に文字がそのままある和文の候補の段落 ID の集合（authors_missing・title_missing の添え書きに使う）。

    PDF は読むだけで、docx の文字も構造も変えない。照合できなかったとき（res.ok が偽・別の論文・文字化け）は何も返さない。
    和文の項目（題目の段落・和文の著者名・和文の所属。1 段落ごと）: core が題目のページとその次のページの core の中にそのままあれば何もしない。
    なければ、同じ窓の一致の割合が NAME_NEAR 以上なら pdf_near（題目の段落は出さない。題目の違いは要確認 pdf_mismatch に載るため）、
    未満なら pdf_missing。英文の項目（題目・副題・著者名・所属）は、照合で見つからなかった段落（res.unmatched。PDF の別の位置にある
    res.found_elsewhere を除く）だけを pdf_en_missing にする（照合できて違いのあるものは pdf_mismatch に載るので足さない。
    英文はこの誌の PDF では論文の最後のページにあるので、題目のページでは探さない）。英文の著者名は、語の集合（name_words）が PDF の
    どこかの 1 つの行の語にすべてあれば、姓と名の順だけの違いとして見つかったとみなす（XML では姓と名の要素に分けるので、直す理由が薄い）。
    どれも要確認にとどめる。
    """
    if not getattr(res, "ok", False) or getattr(res, "verdict", "") in ("wrong", "garbled") or not pages:
        return [], set()
    at = title_page(plan, pages)
    window = core("".join(pages[at:at + 2]))
    on_page = {s for s in author_candidates(plan) + title_candidates(plan) if len(_core_of(plan.paras[s])) >= ITEM_MIN
               and _core_of(plan.paras[s]) in window}
    items = [(p, True) for p in _paras(plan.title)]
    items += [(a.name_ja, False) for a in plan.authors if a.name_ja is not None]
    items += [(x.ja, False) for x in plan.affs if x.ja is not None]
    missing, near = [], []
    seen = set()
    for p, is_title in items:
        if p is None or p.src in seen:
            continue
        seen.add(p.src)
        c = _core_of(p)
        if len(c) < ITEM_MIN or c in window:
            continue
        r = _window_ratio(c, window)
        if r >= NAME_NEAR:
            if not is_title:
                near.append(p.src)
        else:
            missing.append(p.src)
    out = []
    if missing:
        out.append(finding(PDF_MISSING, _srcs_in_order(plan, missing)))
    if near:
        out.append(finding(PDF_NEAR, _srcs_in_order(plan, near)))
    gone = set(res.unmatched) - set(res.found_elsewhere)
    en = [p.src for p in _paras(plan.title_en + plan.subtitle_en) if p.src in gone]
    lines = [name_words(line) for x in pages for line in str(x).splitlines()]

    def reordered(p):       # 姓と名の順だけが違う（語がすべて PDF の 1 つの行にある）
        words = name_words(p.plain())
        return len(words) >= 2 and any(words <= w for w in lines)
    en += [a.name_en.src for a in plan.authors if a.name_en is not None and a.name_en.src in gone and not reordered(a.name_en)]
    en += [x.en.src for x in plan.affs if x.en is not None and x.en.src in gone]
    en = [s for s in dict.fromkeys(en) if text_of(plan, s).strip()]
    if en:
        out.append(finding(PDF_EN_MISSING, _srcs_in_order(plan, en)))
    return out, on_page
