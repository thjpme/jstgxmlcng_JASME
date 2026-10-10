"""引用文献リストの解析と、本文中の著者・年方式の引用の抽出・照合。

正規表現と照合規則は、先行ツール「文献チェック」（refcheck.py, Google ドライブの
「Claude生成物/文献チェック/.claude/skills/refcheck/scripts/」）で磨いたものをそのまま移植している。
本ツールでは、抽出した引用の「年」の位置を元の文字列上で特定し、そこだけをリンクにする
（例: Claude (2025) → 2025 のみがリンク）。

元の文字列は全角括弧などを含むため、照合は NFKC 正規化した文字列で行い、
文字ごとの対応表で元の位置に戻す。
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

from .model import LinkSpec

# ---------------------------------------------------------------------------- refcheck.py から移植
CJK = "㐀-鿿豈-﫿々〆ヵヶ"
KATA = "ァ-ヺー"
HIRA = "぀-ゟ"
NAME_CH = CJK + KATA
YR = r"(?:1[5-9]|20)\d{2}[a-z]?"
Y = rf"{YR}(?:/{YR})?|n\.\s?d\.|印刷中|in press|forthcoming"
DASH = r"[-−–—―‐\u2011~〜ー]"
LATIN_NAME = r"[A-ZÀ-ÖØ-Þ][\w'’\-]+"
INITIAL = r"[A-ZÀ-ÖØ-Þ]"
LATIN_PARTICLE = (r"(?:of|the|for|and the|de|du|da|del|van|von|der|den|la|le"
                  r"|school|university|institute|department|ministry|association|society|council|committee|center|centre)")
RE_YEAR_PAREN = re.compile(rf"\(\s*({Y})\s*\)", re.I)
RE_NUM_START = re.compile(r"^\s*(?:\[(\d{1,3})\]|(\d{1,3})[.)])\s*\S")
RE_DOI = re.compile(r"(?:https?://(?:dx\.)?doi\.org/|doi:\s*)?(10\.\d{4,9}/[^\s\"<>]+)", re.I)
RE_URL = re.compile(r"https?://[^\s<>\"]+")
RE_ACCESS = re.compile(r"最終確認|最終閲覧|閲覧日|閲覧|アクセス日|accessed|Retrieved\s+[A-Z][a-z]+\s+\d", re.I)
RE_THESIS = re.compile(r"博士(?:学位)?論文|修士(?:学位)?論文|卒業論文|学位論文|[Dd]issertation|[Tt]hesis")
RE_PROC = re.compile(r"発表集録|論文集|研究報告|予稿集|要旨集|発表論文|大会|Proceedings|Proc\.|Conference|Symposium|Meeting")
RE_ETAL_TAIL = re.compile(r"(?:(?:ほか|他)\s*\d+\s*名|ら|ほか|他|et\.?\s*al\.?)$")
RE_PREFIX = re.compile(r"^\s*(?:(?:e\.\s?g\.|cf\.|i\.\s?e\.|see(?:\s+also)?|for example|例えば|参照|詳しくは)\s*[,:]?\s*)+", re.I)
JOURNAL_WORDS = r"Journal|Review|Quarterly|Magazine|Bulletin|Letters|Transactions|Annals|for the [Ll]earning of|Teacher"
PUBLISHER_WORDS = (r"Press|Publish\w*|Publications|Verlag|Books|Kluwer|Springer|Wiley|Routledge|Dover|Reidel|Sense|Erlbaum"
                   r"|Elsevier|Éditions|Editions|Vrin|PUF|Gedisa|Prometheus|Norton|Shambhala|Bloomsbury|Palgrave|Sage|Guilford"
                   r"|Information Age|NCTM|Meijitosho|Pearson|Taylor & Francis|Brill|Benjamins|Heinemann")

ITAIJI = str.maketrans({v: k for k, vs in {
    "斉": "齋齊斎", "辺": "邊邉", "沢": "澤", "浜": "濱濵", "崎": "﨑碕嵜", "島": "嶋嶌", "高": "髙", "吉": "𠮷",
    "竜": "龍", "桜": "櫻", "弥": "彌", "国": "國", "恵": "惠", "広": "廣", "徳": "德", "真": "眞", "実": "實",
    "栄": "榮", "寿": "壽", "万": "萬", "条": "條", "来": "來", "礼": "禮", "将": "將", "富": "冨", "槙": "槇",
    "柳": "栁", "黒": "黑", "瀬": "瀨", "関": "關", "滝": "瀧", "渕": "淵", "曽": "曾", "蔵": "藏", "円": "圓",
    "渋": "澁", "学": "學", "会": "會", "県": "縣", "館": "舘", "慎": "愼", "増": "增", "戸": "戶", "静": "靜",
    "浅": "淺"}.items() for v in vs})


def nfkc(s):
    return unicodedata.normalize("NFKC", s)


def itaiji(s):
    """人名の異体字を代表字にそろえる（斉藤/齋藤、浜中/濵中 など）。"""
    return (s or "").translate(ITAIJI)


def norm_name(s):
    return re.sub(r"[\s,.・·]", "", nfkc(s)).lower()


def name_match(cname, rname, latin):
    if not cname or not rname:
        return False
    return cname == rname if latin else rname.startswith(cname)


def bracket_groups(s):
    pairs = {"「": "」", "『": "』"}
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c in pairs:
            depth, j = 0, i
            while j < len(s):
                if s[j] == c:
                    depth += 1
                elif s[j] == pairs[c]:
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            out.append({"type": c, "text": s[i + 1:j], "start": i, "end": j})
            i = j + 1
        else:
            i += 1
    return out


def parse_authors(auth):
    a = auth.strip().rstrip(".,")
    editor = bool(re.search(r"(?:編著?|監修|監訳|編集|\((?:編|編著|Eds?\.?)\)|\bEds?\.)", a))
    a = re.sub(r"\s*\([^()]{0,20}\)", " ", a)
    a = re.sub(r"\s*(?:編著?|監修|監訳|編集|\bEds?\.)$", "", a.strip()).strip().rstrip(".,")
    etal_n = 0
    m = re.search(r"(?:ほか|他)\s*(\d+)\s*名$", a)
    if m:
        etal_n = int(m.group(1))
        a = a[:m.start()].strip()
    elif RE_ETAL_TAIL.search(a):
        etal_n = 1
        a = RE_ETAL_TAIL.sub("", a).strip().rstrip(",")
    initials = re.compile(rf"(?:{INITIAL}\.?\s*-?)+")
    if re.search(f"[{NAME_CH}]", a):
        chunks = [x.strip() for x in re.split(r"[・、,，/&＆]|\band\b", a) if x.strip()]
        chunks = [re.sub(r"^(?:[A-Z]\.\s*)+", "", c) for c in chunks if not initials.fullmatch(c)]
        names = [norm_name(c) for c in chunks if c]
        latin = False
    else:
        names = re.findall(rf"({LATIN_NAME}(?:\s(?:[a-z]+\s)?{LATIN_NAME})?)\s*,\s*{INITIAL}\.?(?:\s?-?{INITIAL}\.?)*(?=\s*(?:,|&|and\b|$))", a)
        names = [n.lower() for n in names]
        if not names:
            chunks = [c.strip() for c in re.split(r"&|\band\b|,", a) if c.strip() and not initials.fullmatch(c.strip())]
            names = [re.sub(r"[.\s]", "", (c.split()[0] if re.fullmatch(rf"{INITIAL}{{1,2}}\.?", c.split()[-1]) else c.split()[-1])).lower()
                     for c in chunks] or [norm_name(a)]
        latin = True
    return {"names": names, "n_authors": len(names) + etal_n, "etal_count": etal_n, "editor": editor, "latin": latin}


def parse_entry(raw, numeric=False):
    """文献 1 件を解析する（refcheck.parse_entry の簡略版。リンク付けに必要な項目のみ）。"""
    t = nfkc(raw)
    d = {"raw": raw}
    if numeric:
        m = RE_NUM_START.match(t)
        d["number"] = int(m.group(1) or m.group(2)) if m else None
        t = RE_NUM_START.sub(lambda mm: mm.group(0)[-1], t, count=1)
    m = RE_YEAR_PAREN.search(t)
    if m:
        d["year"] = m.group(1)
        d["year_span_nfkc"] = (m.start(1), m.end(1))
        auth, rest = t[:m.start()], t[m.end():]
    else:
        d["year"] = None
        d["year_span_nfkc"] = None
        mm = re.search(r"[「『]", t)
        auth, rest = (t[:mm.start()], t[mm.start():]) if mm else (t.split(".")[0], t[len(t.split(".")[0]):])
    d.update(parse_authors(auth))
    d["authors_str"] = auth.strip().rstrip(",")
    md = RE_DOI.search(rest)
    d["doi"] = md.group(1).rstrip(".,;)") if md else None
    mu = RE_URL.search(rest)
    d["url"] = mu.group(0).rstrip(".,;)") if mu and "doi.org" not in mu.group(0) else None
    groups = bracket_groups(rest)
    container = None
    publisher_hint = False
    if groups:
        if groups[0]["type"] == "「" and len(groups) > 1:
            container = groups[1]["text"]
    if re.search(rf",\s*\d+\s*(?:\(\s*\d+(?:\s*{DASH}\s*\d+)?\s*\))?\s*,\s*(?:pp?\.\s*)?\d+\s*[–{DASH[1:-1]}]\s*\d+", rest) \
            or re.search(r"第\s*\d+\s*巻", rest):
        container = container or True
    if not groups:
        if re.search(rf"\d+\s*\(\s*\d+(?:\s*{DASH}\s*\d+)?\s*\)|\b[Vv]ol\.?\s*\d", rest) or re.search(JOURNAL_WORDS, rest):
            container = True
        if re.search(PUBLISHER_WORDS, rest):
            publisher_hint = True
    in_book = bool(re.search(r"\bIn:?\s+.*\((?:Eds?|eds?)\.?\)", rest)) or ("編" in rest and groups and groups[0]["type"] == "「"
                                                                             and len(groups) > 1 and groups[1]["type"] == "『")
    if RE_THESIS.search(rest):
        typ = "thesis"
    elif in_book:
        typ = "chapter"
    elif container and RE_PROC.search(rest):
        typ = "proceedings"
    elif container:
        typ = "journal"
    elif groups and groups[0]["type"] == "『":
        typ = "book"
    elif d["url"] and not publisher_hint:
        typ = "web"
    else:
        typ = "book"
    d["type"] = typ
    d["publication_type"] = {"journal": "journal", "book": "book", "chapter": "book", "proceedings": "confproc",
                             "thesis": "thesis", "web": "website"}[typ]
    return d


def resolve_cjk(run, known):
    for i in range(len(run)):
        s = run[i:]
        if len(s) == 1 and len(run) > 1:
            break
        if any(itaiji(k).startswith(itaiji(s)) for k in known):
            return s, True
    return run, False


def split_names(names_str, known):
    s = RE_PREFIX.sub("", names_str.strip())
    etal = bool(RE_ETAL_TAIL.search(s))
    s = RE_ETAL_TAIL.sub("", s).strip().rstrip(",")
    seps = re.findall(r"・|,|、|&|\band\b", s)
    chunks = [c.strip() for c in re.split(r"・|,|、|&|\band\b", s)
              if c.strip() and not re.fullmatch(rf"(?:{INITIAL}\.\s*-?)+", c.strip())]
    out = []
    for c in chunks:
        if re.search(f"[{NAME_CH}]", c):
            m = re.search(f"[{NAME_CH}・]+$", c)
            c = m.group(0) if m else c
            r, ok = resolve_cjk(norm_name(c), known)
        else:
            c = re.sub(r"^(?:and|&)\s+", "", c)
            r = norm_name(c.split()[-1]) if c.split() else norm_name(c)
            ok = r in known
        out.append((r, ok))
    if len(out) > 1 and not all(ok for _, ok in out) and not set(seps) & {"・", "&", "and"}:
        k = next((i for i in range(len(out)) if all(ok for _, ok in out[i:])), None)
        out = out[k:] if k is not None else out[-1:]
    return [r for r, _ in out], etal, seps


def parse_years_spans(inner):
    """括弧の中が「年（, 年）*（, 頁）?」だけなら、年とその位置の一覧を返す。"""
    years, loc = [], None
    pos = 0
    for tok in inner.split(","):
        raw = tok
        t = tok.strip()
        lead = len(tok) - len(tok.lstrip())
        if re.fullmatch(Y, t, re.I):
            years.append((t, pos + lead, pos + lead + len(t)))
        elif re.match(r"(?:pp?\.|頁|ページ|chap\.|ch\.|第)", t, re.I):
            loc = inner[pos:].strip()
            break
        else:
            return None, None
        pos += len(raw) + 1
    return (years or None), loc


# ---------------------------------------------------------------------------- 位置の対応表
class Mapped:
    """元の文字列 s と、その文字ごとの NFKC 正規化 n、n の位置 → s の位置の表。"""

    def __init__(self, s: str):
        self.s = s
        parts, mp = [], []
        for i, ch in enumerate(s):
            c = nfkc(ch)
            parts.append(c)
            mp.extend([i] * len(c))
        self.n = "".join(parts)
        self.map = mp

    def orig(self, ns: int, ne: int):
        if ne <= ns:
            return None
        return self.map[ns], self.map[ne - 1] + 1


# ---------------------------------------------------------------------------- 引用の抽出
def extract_citations(text_nfkc, known):
    """NFKC 済みの段落文字列から引用を抽出する。年ごとに位置（NFKC 上）を持つ。"""
    cites = []
    for m in re.finditer(r"\(([^()]{1,400})\)", text_nfkc):
        inner = m.group(1)
        if not re.search(r"(?:1[5-9]|20)\d{2}|n\.\s?d\.|印刷中|in press", inner, re.I):
            continue
        base_inner = m.start(1)
        years, loc = parse_years_spans(inner)
        if years:   # 叙述型: 著者名（年）
            base = max(0, m.start() - 120)
            pre = text_nfkc[base:m.start()].rstrip().rstrip(",").rstrip()
            etal = bool(RE_ETAL_TAIL.search(pre))
            pre2 = re.sub(r"[’']s$", "", RE_ETAL_TAIL.sub("", pre).rstrip())
            mm = re.search(rf"([{NAME_CH}]+(?:(?:\s*[・,、]\s*(?:&\s*)?|\s*&\s*|\s+and\s+)[{NAME_CH}]+)*)$", pre2) \
                or re.search(rf"({LATIN_NAME}(?:\s+(?:{LATIN_PARTICLE}\s+)*{LATIN_NAME})*"
                             rf"(?:(?:\s*,\s*(?:and\s+|&\s*)?|\s+and\s+|\s*&\s*){LATIN_NAME}(?:\s+(?:{LATIN_PARTICLE}\s+)*{LATIN_NAME})*)*)$", pre2)
            if not mm:
                for y, s, e in years:
                    cites.append({"names": [], "etal": False, "year": y, "span": (base_inner + s, base_inner + e),
                                  "form": "unresolved", "raw": m.group(0), "loc": loc})
                continue
            names, e2, seps = split_names(mm.group(1) + ("ら" if etal else ""), known)
            for y, s, e in years:
                cites.append({"names": names, "etal": etal or e2, "year": y, "span": (base_inner + s, base_inner + e),
                              "form": "narrative", "raw": text_nfkc[base + mm.start():m.end()], "loc": loc})
            continue
        pos = 0
        for part in inner.split(";"):
            pm = re.match(rf"^\s*(?P<names>(?!\d)[^;]*?[A-Za-z{NAME_CH}][^;]*?)\s*,?\s*"
                          rf"(?P<years>(?:{Y})(?:\s*,\s*(?:{Y}))*)(?P<loc>\s*,\s*(?:pp?\.|頁|ページ|chap\.|ch\.|第)[^;]*)?\s*$",
                          part, re.I)
            if pm:
                nm = pm.group("names")
                ci = re.search(r"\b(?:as\s+)?(?:cited|quoted)\s+in\s+", nm, re.I)
                if ci:
                    nm = nm[ci.end():]
                names, etal, seps = split_names(nm, known)
                ys = pm.start("years")
                for t in re.finditer(Y, pm.group("years"), re.I):
                    s = base_inner + pos + ys + t.start()
                    cites.append({"names": names, "etal": etal, "year": t.group(0), "span": (s, s + len(t.group(0))),
                                  "form": "parenthetical", "raw": m.group(0), "loc": pm.group("loc")})
            pos += len(part) + 1
    cites.sort(key=lambda c: c["span"][0])
    return cites


def match_citation(c, refs):
    """引用 1 件を文献と照合する。戻り値: (文献 または None, 種別, 説明)"""
    if c["form"] == "unresolved" or not c["names"]:
        cand = [r for r in refs if (r.parsed.get("year") or "").lower() == c["year"].lower()]
        return None, "unparsed", "年だけの括弧で、著者名を機械的に特定できない" + (
            "（同じ年の文献: " + "、".join(f"{r.rid} {r.parsed.get('authors_str', '')}" for r in cand[:4]) + "）" if cand else "")
    first = c["names"][0]
    by_name = [r for r in refs if r.parsed.get("names") and name_match(first, r.parsed["names"][0], r.parsed["latin"])]
    exact = [r for r in by_name if (r.parsed.get("year") or "").lower() == c["year"].lower()]
    if exact:
        def fit(r):
            rn = r.parsed["names"]
            co = len(c["names"]) > 1 and len(rn) > 1 and all(name_match(a, b, r.parsed["latin"]) for a, b in zip(c["names"][1:], rn[1:]))
            n_ok = r.parsed["n_authors"] == len(c["names"]) or (c["etal"] and r.parsed["n_authors"] >= 2)
            return (co, n_ok)
        r = max(exact, key=fit)
        if len(exact) > 1 and fit(exact[0]) == fit(exact[-1]):
            return None, "ambiguous", "同じ著者・同じ年の文献が複数あり、どれか特定できない: " + "、".join(x.rid for x in exact)
        return r, "exact", ""
    same_year = [r for r in refs if r.parsed.get("names") and (r.parsed.get("year") or "").lower() == c["year"].lower()]
    variant = [r for r in same_year if not r.parsed["latin"] and itaiji(r.parsed["names"][0]).startswith(itaiji(first))]
    if len(variant) == 1:
        return variant[0], "variant", f"第一著者名の表記が文献リストと異なる（異体字として照合: 本文 {first} / 文献 {variant[0].parsed['authors_str']}）"
    other = [r for r in same_year if any(name_match(first, nm, r.parsed["latin"]) for nm in r.parsed["names"][1:])]
    if other:
        return None, "author_order", f"第一著者が文献リストと異なる（候補: {other[0].rid} {other[0].parsed['authors_str']}）"
    if by_name:
        years = sorted({r.parsed.get('year') or '年なし' for r in by_name})
        return None, "year_mismatch", f"著者は一致するが年が一致しない（本文 {c['year']} / 文献の同著者の年: {', '.join(years)}）"
    return None, "missing", "文献リストに該当する文献が見つからない"


def link_citations(plan, linker, paras):
    """文献リストを解析し、本文の引用の年をリンクにする。"""
    refs = plan.refs
    if not refs:
        return
    texts = [r.para.plain() for r in refs]
    numeric = sum(1 for t in texts if RE_NUM_START.match(nfkc(t))) >= max(2, len(texts) * 0.5)
    known = set()
    for r, t in zip(refs, texts):
        r.parsed = parse_entry(t, numeric)
        known.update(r.parsed.get("names") or [])
        tag_reference(r)
    plan.citation_mode = "numeric" if numeric else "author-year"
    if numeric:
        link_numeric(plan, linker, paras)
        return
    cited = defaultdict(list)
    for p, where in paras:
        if where in ("ref", "formula"):
            continue
        mp = Mapped(p.plain())
        for c in extract_citations(mp.n, known):
            r, kind, detail = match_citation(c, refs)
            span = mp.orig(*c["span"])
            if r is None:
                linker.unresolved.append(("bibr", p.src, c["raw"], detail, kind, c["year"]))
                continue
            spec = LinkSpec(kind="xref", attrs={"ref-type": "bibr", "rid": r.rid})
            if span and mp.s[span[0]:span[1]] and _apply(p, span, spec):
                linker.count["bibr"] += 1
                cited[r.rid].append(p.src)
                if kind == "variant":
                    plan.decide("mechanical", "citation", p.src, f"「{c['raw']}」の {c['year']} を {r.rid} にリンク。{detail}")
    plan.uncited_refs = [r.rid for r in refs if r.rid not in cited]


def _apply(p, span, spec):
    from .linker import apply_span
    return apply_span(p, span[0], span[1], spec)


def tag_reference(r):
    """文献の中の年・論文名・誌名・書名にタグを付ける（J-STAGE の引用文献リンク用。文字列は変えない）。"""
    p = r.para
    plain = p.plain()
    mp = Mapped(plain)
    ys = r.parsed.get("year_span_nfkc")
    if ys:
        span = mp.orig(*ys)
        if span:
            _apply(p, span, LinkSpec(kind="year"))
    # 和文の「論文名」『誌名・書名』: 年の直後に「 や 『 が来る書き方のときだけタグを付ける
    groups = bracket_groups(plain)
    if not groups or not ys:
        return
    year_end = span[1] if span else 0
    g0 = groups[0]
    between = plain[year_end:g0["start"]]
    if not re.fullmatch(r"[\s\u3000)）.．,，:：]*", between) or g0["end"] >= len(plain):
        return
    if g0["type"] == "「":
        _apply(p, (g0["start"] + 1, g0["end"]), LinkSpec(kind="article-title"))
        if len(groups) > 1 and groups[1]["type"] == "『" and groups[1]["end"] < len(plain):
            mid = plain[g0["end"] + 1:groups[1]["start"]]
            if len(mid) <= 20 and not re.search(r"\d", mid):
                _apply(p, (groups[1]["start"] + 1, groups[1]["end"]), LinkSpec(kind="source"))
    else:
        _apply(p, (g0["start"] + 1, g0["end"]), LinkSpec(kind="source"))


def link_numeric(plan, linker, paras):
    nums = {r.parsed.get("number"): r.rid for r in plan.refs if r.parsed.get("number") is not None}
    for p, where in paras:
        if where in ("ref", "formula"):
            continue
        plain = p.plain()
        for m in re.finditer(r"\[(\d{1,3}(?:\s*[-–,]\s*\d{1,3})*)\]", plain):
            base = m.start(1)
            for t in re.finditer(r"\d{1,3}", m.group(1)):
                rid = nums.get(int(t.group(0)))
                if rid is None:
                    linker.unresolved.append(("bibr", p.src, m.group(0), f"番号 {t.group(0)} の文献がない", "missing", t.group(0)))
                    continue
                if _apply(p, (base + t.start(), base + t.end()), LinkSpec(kind="xref", attrs={"ref-type": "bibr", "rid": rid})):
                    linker.count["bibr"] += 1
