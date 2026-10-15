"""ルート2（出版版 PDF に合わせてから作る）の反例集を動かす仕組み。

実装の内部（照合の窓の決め方・違いの分類の規則など）とは独立に、原則だけから期待を決めた反例を、指定したコードで
変換して確かめる。実行は run_all.py から（このファイルを直接 import して run_case() を呼んでもよい）。

  python run_all.py <src のフォルダ> [cases_xxx.py ...]

======================================================================== 原則（期待はこれだけで決める）
- XML の本文は、出版版 PDF の本文と 1 文字も違ってはいけない。直した docx の段落の文字は XML の本文と同じ。
- PDF にある組版の文字（ページ番号・誌名の行・柱・投稿受付日）、docx にない図・表の中の文字、ほかの段落の文字を、
  docx の段落に足してはいけない。
- 出版版 PDF の本文にある docx の文字を消してはいけない。
- 直せない違い・決められない違いは、黙って落とさず、レポートの 13 章に出す。

======================================================================== 反例の書式
反例のファイルは cases_<名前>.py。モジュールの変数 CASES（dict のリスト）に反例を並べる。補助はこのファイルから
  from runner import *
で使う（run_all.py は、このフォルダを PYTHONPATH に入れて実行する）。

1 つの反例は dict:
  name   : 反例の名前（ファイルをまたいで一意。英数字と _ が無難）
  angle  : "layout"（PDF の形・読み順）/ "artifact"（組版の文字・図表の文字）/ "edit"（docx と PDF の文字の違い）
  item   : 既知の不具合の番号（"U7"・"N9"・"N10" など）。分からなければ "new"
  paras  : docx の段落の並び。(役割, 文字) のリスト。番号（0 から）は truth のキーになる。
           役割（docx の中の順序は、役割ごとに決まる。下の「docx の組み立て」）:
             冒頭  : 題目 / 副題 / 著者（"所属\t氏名"。所属を省くと「架空大学」）
             本文  : 本文 / 見出し（=見出し1）/ 見出し2 / 見出し3 / 引用 / 図キャプション / 表キャプション /
                     付記見出し / 付記 / 謝辞見出し / 謝辞 / 注見出し / 注 / 引用文献見出し / 引用文献 / スタイルなし
                     表   : 文字の代わりに行のリスト [["セル", "セル"], ...]（Word の表。セルの段落は照合されない）
                     画像 : 文字は画像に描く文字（図の画像だけの段落。段落の文字は U+FFFC 1 文字）
             英文  : 英文題目 / 英文副題 / 英文著者（"Name\tAffiliation"）/ 英文要旨
             後付け: 資料（英文要旨の後ろの、資料の段落）
           冒頭・英文の役割を省くと、既定の文字の段落が入る（ラベル「既定:題目」など。truth はないので、変われば FAIL）。
           テンプレートから入る段落（誌名「全国数学教育学会誌　数学教育学研究」の行・装飾の行・空の段落など）も
           「既定:…」として確かめる（変わってはいけない）。
  truth  : 出版版での段落の文字 {paras の番号: 文字}。書かない段落は docx と同じ（変わってはいけない）。
           著者・英文著者は "所属\t氏名" / "Name\tAffiliation" の形で書く。表・画像には書けない。
  pages  : pdfmatch.extract_pages の代わりに返す各ページの文字（str のリスト。行は "\n"）。下の補助で作る。
  expect : "exact"（直した後の段落が truth と一致すること）/
           "reported"（一致しなくてもよいが、一致しない段落の違いが 13 章に出ること）。
           段落ごとに変えるなら {"default": "exact", 3: "reported"} の形。
  note   : 説明（何を確かめるか、なぜその期待か）

======================================================================== 判定（段落ごと）
  OK       : 直した docx の段落の文字（直した docx を読み直したもの）が truth（書いていなければ元の docx の文字）と一致する。
  REPORTED : 一致しないが、expect が reported で、次をすべて満たす。
             - その段落の違いが 13 章に出ている（照合の違いの fixable=False / 直さなかった箇所 / 残っている違い /
               PDF の中に見つからない段落 / 照合に使わなかった PDF の文字（ignored_lines。不足・余分の文字と重なるもの））。
               構造の記録（PdfCheck・DocxFix）にあり、かつレポートの 13 章の文字に段落 ID が出ていること
             - 元の docx より truth から遠ざかっていない（編集距離が増えず、truth と共通の文字が減らない）
             - 足していない（docx にも truth にもない文字をツールが入れていない）・消していない（truth にある docx の文字を
               ツールが除いていない）
  FAIL     : それ以外。理由に「足した「…」」「消した「…」」「直していない…」を書く。truth を書いていない段落が変わった、
             XML に直した段落の文字がない、不変性チェック（fidelity）が不合格、変換が止まった（例外）も FAIL。
反例全体の判定は、段落の判定の最も悪いもの（FAIL > REPORTED > OK）。

======================================================================== PDF の文字を作る補助
  wrap(text, width=24)            : 本誌の 1 行の長さで行に分ける（全角 1・半角 0.5 で数える）。行のリスト
  page(no, lines, style="paren", where="top", heads=())
                                  : 1 ページの文字。先頭に「（no）」の行（style="dash" なら「－ no －」、"plain" なら「no」、
                                    None ならページ番号なし。where="bottom" ならページの最後）。heads は柱の行（先頭に入る）
  journal_line(vol=24, no=1, year=2018, fp=25, lp=36)
                                  : 「全国数学教育学会誌　数学教育学研究　第24巻　第１号　2018　pp.25～36」の行
  received_line(sub="2025年８月31日", acc="2025年11月24日", resub=None)
                                  : 「2025年８月31日投稿受付，2025年11月24日採用決定」（resub があれば「，…再投稿受付」を挟む）
  received_old(date="2017.11.30") : 「（2017.11.30受理）」
  zen(s)                          : 半角の英数字・記号を全角にする（「8」→「８」）
  insert_lines(lines, at, *extra) : 行のリストの at 番目の前に extra の行を差し込んだ新しいリスト
                                    （at は行の番号、または文字列。文字列ならそれを含む最初の行の後に差し込む）
  join_line(lines, at, s)         : at 番目の行（または文字列を含む最初の行）の後ろに s をつなげた新しいリスト
  split_text(text, *at)           : 段落の文字を、at（文字の位置か、その文字列が始まる位置）で分けたリスト
  flow(blocks, first=1, per_page=None, width=24, style="paren", where="top", heads=())
                                  : 段落の文字を行に分けてページに流し込む。blocks の要素は
                                      str          → wrap() して流す
                                      Raw(*lines)  → そのままの行（表の数字・図の文字・別の段落・誌名の行など）
                                      Join(s)      → 直前の行の後ろにつなげる（受付日が本文の行につながる形）
                                      BREAK        → ページの区切り
                                    per_page を与えると、その行数でページを分ける（ページ番号の行は数えない）。
                                    first は最初のページ番号。戻り値は pages（str のリスト）
  pub(text)                       : truth を書くときの補助（何もしない。読みやすさのため）

======================================================================== 実行
  run_case(case, workdir=None) -> dict
      {"name", "angle", "item", "expect", "note", "verdict", "error", "fidelity_ok", "report13",
       "paras": [{"label", "index", "role", "src", "original", "fixed", "truth", "verdict", "reason"}]}
  pipeline.convert を route="pdf" で、pdfmatch.extract_pages を差し替えて実行する（PDF のファイルは空のダミー）。
  docx は tests/make_fixtures.py（実行するコードの tests/ にあればそれ、なければ wt_head の tests/）の部品で作る。
"""
from __future__ import annotations

import difflib
import re
import shutil
import sys
import tempfile
import traceback
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
OBJ = "￼"

__all__ = ["wrap", "page", "journal_line", "received_line", "received_old", "zen", "insert_lines", "join_line",
           "split_text", "flow", "Raw", "Join", "BREAK", "pub", "run_case", "JOURNAL_NAME", "DEFAULTS"]

JOURNAL_NAME = "全国数学教育学会誌　数学教育学研究"


# ============================================================================ PDF の文字を作る補助
def _w(c: str) -> float:
    return 1.0 if unicodedata.east_asian_width(c) in ("F", "W", "A") else 0.5


def wrap(text: str, width: float = 24) -> list:
    """本誌の 1 行の長さ（全角 width 文字。半角は 0.5 と数える）で行に分ける。"""
    lines, cur, n = [], "", 0.0
    for c in text:
        if cur and n + _w(c) > width:
            lines.append(cur)
            cur, n = "", 0.0
        cur += c
        n += _w(c)
    if cur:
        lines.append(cur)
    return lines


def zen(s) -> str:
    """半角の英数字・記号を全角にする。"""
    return "".join(chr(ord(c) + 0xFEE0) if 0x21 <= ord(c) <= 0x7E else c for c in str(s))


def _page_no(no, style) -> str:
    if style == "paren":
        return f"（{no}）"
    if style == "dash":
        return f"－ {no} －"
    if style == "plain":
        return f"{no}"
    raise ValueError(style)


def page(no, lines, style="paren", where="top", heads=()) -> str:
    """1 ページの文字。style=None ならページ番号の行を入れない。"""
    out = list(heads)
    if style is not None and where == "top":
        out = [_page_no(no, style)] + out
    out += list(lines)
    if style is not None and where == "bottom":
        out.append(_page_no(no, style))
    return "\n".join(out) + "\n"


def journal_line(vol=24, no=1, year=2018, fp=25, lp=36) -> str:
    return f"{JOURNAL_NAME}　第{vol}巻　第{zen(no)}号　{year}　pp.{fp}～{lp}"


def received_line(sub="2025年８月31日", acc="2025年11月24日", resub=None) -> str:
    mid = f"，{resub}再投稿受付" if resub else ""
    return f"{sub}投稿受付{mid}，{acc}採用決定"


def received_old(date="2017.11.30") -> str:
    return f"（{date}受理）"


def _find(lines, at):
    if isinstance(at, int):
        return at
    for k, ln in enumerate(lines):
        if at in ln:
            return k
    raise ValueError(f"「{at}」を含む行がない")


def insert_lines(lines, at, *extra) -> list:
    """at 番目の行の前（at が文字列なら、それを含む最初の行の後）に extra の行を差し込む。"""
    lines = list(lines)
    k = at if isinstance(at, int) else _find(lines, at) + 1
    return lines[:k] + list(extra) + lines[k:]


def join_line(lines, at, s) -> list:
    """at 番目の行（at が文字列なら、それを含む最初の行）の後ろに s をつなげる。"""
    lines = list(lines)
    k = _find(lines, at)
    lines[k] = lines[k] + s
    return lines


def split_text(text, *at) -> list:
    """段落の文字を at（文字の位置か、その文字列が始まる位置）で分ける。"""
    cuts = []
    for a in at:
        if isinstance(a, int):
            cuts.append(a)
        else:
            k = text.find(a)
            if k < 0:
                raise ValueError(f"「{a}」が段落にない")
            cuts.append(k)
    cuts = sorted(set(cuts))
    out, prev = [], 0
    for c in cuts:
        out.append(text[prev:c])
        prev = c
    out.append(text[prev:])
    return [x for x in out if x]


class Raw:
    """そのまま入れる行。"""

    def __init__(self, *lines):
        self.lines = list(lines)


class Join:
    """直前の行の後ろにつなげる文字。"""

    def __init__(self, s):
        self.s = s


BREAK = object()


def flow(blocks, first=1, per_page=None, width=24, style="paren", where="top", heads=()) -> list:
    """段落の文字を行に分けてページに流し込む（各ページの文字のリスト）。"""
    pages_lines = [[]]
    for b in blocks:
        cur = pages_lines[-1]
        if b is BREAK:
            pages_lines.append([])
            continue
        if isinstance(b, Join):
            if not cur:
                raise ValueError("Join の前に行がない")
            cur[-1] += b.s
            continue
        new = b.lines if isinstance(b, Raw) else wrap(b, width)
        for ln in new:
            if per_page and len(pages_lines[-1]) >= per_page:
                pages_lines.append([])
            pages_lines[-1].append(ln)
    return [page(first + k, ls, style=style, where=where, heads=heads) for k, ls in enumerate(pages_lines)]


def pub(text: str) -> str:
    return text


# ============================================================================ docx の組み立て
FRONT = ("題目", "副題", "著者")
ENGLISH = ("英文題目", "英文副題", "英文著者", "英文要旨")
BACK = ("資料",)
BODY_STYLE = {"本文": "body", "見出し": "sec1", "見出し1": "sec1", "見出し2": "sec2", "見出し3": "sec3",
              "引用": "quote", "図キャプション": "fig_cap", "表キャプション": "tab_cap", "付記見出し": "notes_head",
              "付記": "body", "謝辞見出し": "ack_head", "謝辞": "body", "注見出し": "fn_head", "注": "body",
              "引用文献見出し": "ref_head", "引用文献": "ref", "スタイルなし": "normal"}
DEFAULTS = {"題目": "架空の題目による照合の検証用の論文", "副題": "―反例集の既定の副題―", "著者": "架空大学\t試験　五郎",
            "英文題目": "A Fictional Article for Checking", "英文副題": "Default Subtitle",
            "英文著者": "Goro SHIKEN\tFictional University", "英文要旨": "This is a fictional abstract for checking."}


def _fixtures(code_root: Path):
    """実行するコードの tests/make_fixtures.py（なければ wt_head のもの）を import する。"""
    for tests in (code_root / "tests", HERE / "wt_head" / "tests"):
        if (tests / "make_fixtures.py").exists():
            if str(tests) not in sys.path:
                sys.path.insert(0, str(tests))
            import make_fixtures
            return make_fixtures
    raise RuntimeError("tests/make_fixtures.py が見つからない")


def build_docx(case, path, mf):
    """case["paras"] から docx を作る。戻り値: docx の順の期待する段落 [(ラベル, 番号, 役割, 文字)]。"""
    paras = case["paras"]
    for i, (role, _) in enumerate(paras):
        if role not in FRONT + ENGLISH + BACK + ("表", "画像") and role not in BODY_STYLE:
            raise ValueError(f"段落 {i}: 役割「{role}」は使えない")
    pick = lambda roles: [(i, r, t) for i, (r, t) in enumerate(paras) if r in roles]   # noqa: E731

    def one(role):
        got = pick((role,))
        return got if got else [(f"既定:{role}", role, DEFAULTS[role])]

    b = mf.Builder()
    S = mf.S
    order = []          # (ラベル, 番号, 役割, 文字)。テンプレートの段落は後で「既定:テンプレート」として扱う
    title, subtitle, authors = one("題目")[0], one("副題")[0], one("著者")
    au = []
    for i, r, t in authors:
        aff, name = t.split("\t", 1) if "\t" in t else ("架空大学", t)
        au.append((aff, name))
    body = mf.front_ja(b, title[2], subtitle[2], au)
    order += [(_label(title), title[0], "題目", title[2]), (_label(subtitle), subtitle[0], "副題", subtitle[2])]
    for (i, r, t), (aff, name) in zip(authors, au):
        order += [(_label((i, r, t)) + ":所属", i, "著者:所属", aff), (_label((i, r, t)) + ":氏名", i, "著者:氏名", name)]
    pid = 300
    for i, (role, text) in enumerate(paras):
        if role in FRONT + ENGLISH + BACK:
            continue
        if role == "表":
            rows = [[mf.cell(c) for c in row] for row in text]
            body.append(mf.table(rows))
            for r_, row in enumerate(text):
                for c_, c in enumerate(row):
                    order.append((f"{i}:表[{r_}][{c_}]", i, "表", c))
            continue
        if role == "画像":
            pid += 1
            rid = b.add_image(f"img{i}.png", mf.png_bytes(str(text)))
            body.append(mf.para(S["body"], mf.drawing(rid, 2880000, 1800000, pid), jc="center"))
            order.append((f"{i}:画像", i, "画像", OBJ))
            continue
        body.append(mf.para(S[BODY_STYLE[role]], text) if text else mf.para(S[BODY_STYLE[role]]))
        order.append((str(i), i, role, text))
    t_en, st_en, au_en, abstracts = one("英文題目")[0], one("英文副題")[0], one("英文著者"), one("英文要旨")
    au2 = [tuple(t.split("\t", 1)) if "\t" in t else (t, "Fictional University") for _, _, t in au_en]
    body += mf.front_en(b, t_en[2], st_en[2], au2, [t for _, _, t in abstracts])
    order += [(_label(t_en), t_en[0], "英文題目", t_en[2]), (_label(st_en), st_en[0], "英文副題", st_en[2])]
    for x, (name, aff) in zip(au_en, au2):
        order += [(_label(x) + ":氏名", x[0], "英文著者:氏名", name), (_label(x) + ":所属", x[0], "英文著者:所属", aff)]
    order += [(_label(x), x[0], "英文要旨", x[2]) for x in abstracts]
    back = [mf.para(S["abs"], t) for _, _, t in pick(BACK)]
    order += [(str(i), i, r, t) for i, r, t in pick(BACK)]
    body += mf.tail(b, appendix=back or None)
    b.save(path, body)
    return order


def _label(x) -> str:
    return str(x[0])


def read_paragraphs(path) -> list:
    """docx を本ツールで読み取った段落 [(src, 文字)]（本文の順、Word の脚注は後ろ）。"""
    from jasme_jats.docx_reader import read_docx
    doc = read_docx(path)
    out = [(p.src, p.plain()) for p in doc.all_paragraphs()]
    for notes in getattr(doc, "footnotes", {}).values():
        out += [(p.src, p.plain()) for p in notes]
    return out


def map_paragraphs(order, got) -> dict:
    """期待する段落の並び（order）を、読み取った段落（got）に順に当てはめる。src -> (ラベル, 番号, 役割)。"""
    out, k = {}, 0
    for label, idx, role, text in order:
        j = k
        while j < len(got) and got[j][1] != text:
            j += 1
        if j >= len(got):
            raise RuntimeError(f"反例の段落 {label}「{text[:20]}」を docx の中に見つけられない（仕組みの不具合）")
        out[got[j][0]] = (label, idx, role)
        k = j + 1
    return out


# ============================================================================ 判定
def levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def lcs(a: str, b: str) -> int:
    prev = [0] * (len(b) + 1)
    for ca in a:
        cur = [0]
        for j, cb in enumerate(b, 1):
            cur.append(prev[j - 1] + 1 if ca == cb else max(prev[j], cur[j - 1]))
        prev = cur
    return prev[-1]


def _matched(a: str, b: str):
    """a と b の照合で一致した位置の集合 (a の位置, b の位置)。"""
    ma, mb = set(), set()
    for i, j, n in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        ma.update(range(i, i + n))
        mb.update(range(j, j + n))
    return ma, mb


def _runs(positions, text):
    """位置の集合を連続した部分にまとめた文字列のリスト。"""
    out, cur, last = [], "", None
    for k in sorted(positions):
        if last is not None and k != last + 1:
            out.append(cur)
            cur = ""
        cur += text[k]
        last = k
    if cur:
        out.append(cur)
    return out


def describe(orig: str, fixed: str, truth: str) -> dict:
    """直した後の文字と truth の違いを、ツールが足した・消した・直していないに分ける。"""
    f_in_t, t_in_f = _matched(fixed, truth)
    o_in_f, f_from_o = _matched(orig, fixed)
    o_in_t, t_from_o = _matched(orig, truth)
    extra = set(range(len(fixed))) - f_in_t          # truth にない、直した後の文字
    missing = set(range(len(truth))) - t_in_f        # 直した後にない、truth の文字
    added = {k for k in extra if k not in f_from_o}            # ツールが入れた
    left = extra - added                                       # docx のまま残った
    deleted = {k for k in missing if k in t_from_o}            # docx にあったのに消えた
    not_added = missing - deleted                              # docx になく、足していない
    return {"added": _runs(added, fixed), "left": _runs(left, fixed),
            "deleted": _runs(deleted, truth), "not_added": _runs(not_added, truth)}


def _q(xs) -> str:
    return "・".join(f"「{x}」" for x in xs)


def _strip(s: str) -> str:
    return re.sub(r"\s", "", s.replace(OBJ, ""))


def _src_in(text: str, src: str) -> bool:
    return re.search(rf"(?<![0-9A-Za-z_]){re.escape(src)}(?![0-9])", text) is not None


def evidence(res, src, segs, report13) -> list:
    """段落 src の違いが 13 章に出ている証拠の一覧（構造の記録にあり、かつ 13 章の文字に段落 ID が出ているもの）。"""
    fx = getattr(res, "docx_fix", None)
    checks = [c for c in ((fx.check if fx is not None else None), getattr(res, "pdf_check", None)) if c is not None]
    kinds = []
    if (fx is not None and src in (fx.unmatched or [])) or any(src in (c.unmatched or []) for c in checks):
        kinds.append("PDF の中に見つからない段落")
    if fx is not None and any(f.src == src and not f.applied for f in fx.fixes):
        kinds.append("直さなかった箇所")
    if fx is not None and fx.check is not None and any(d.src == src and not getattr(d, "fixable", True)
                                                        for d in fx.check.diffs):
        kinds.append("照合の違い（fixable=False）")
    pc = getattr(res, "pdf_check", None)
    if pc is not None and any(d.src == src for d in pc.diffs):
        kinds.append("残っている違い")
    segs = [_strip(s) for s in segs if _strip(s)]
    for c in checks:
        for item in getattr(c, "ignored_lines", None) or []:
            s, t = (item[0], item[1]) if isinstance(item, (tuple, list)) else (getattr(item, "src", ""), str(item))
            t = _strip(str(t))
            if s == src and t and any(x in t or t in x for x in segs):
                kinds.append("照合に使わなかった PDF の文字")
                break
    if not _src_in(report13, src):
        return []
    return list(dict.fromkeys(kinds))


def judge(orig, fixed, truth, has_truth, expect, ev_fn):
    """段落 1 つの判定 (判定, 理由)。"""
    if fixed == truth:
        return "OK", ""
    d = describe(orig, fixed, truth)
    parts = []
    if d["added"]:
        parts.append(f"足した{_q(d['added'])}（docx にも truth にもない）")
    if d["deleted"]:
        parts.append(f"消した{_q(d['deleted'])}（truth にある docx の文字）")
    if d["left"]:
        parts.append(f"直していない: truth にない docx の文字{_q(d['left'])}が残る")
    if d["not_added"]:
        parts.append(f"直していない: truth の文字{_q(d['not_added'])}がない")
    reason = "。".join(parts) or "違いがある"
    if not has_truth:
        return "FAIL", "truth を書いていない段落が変わった: " + reason
    if expect != "reported":
        return "FAIL", reason
    if d["added"] or d["deleted"]:
        return "FAIL", reason
    if levenshtein(fixed, truth) > levenshtein(orig, truth) or lcs(fixed, truth) < lcs(orig, truth):
        return "FAIL", "元の docx より truth から遠ざかった: " + reason
    ev = ev_fn(d["left"] + d["not_added"] + d["added"] + d["deleted"])
    if not ev:
        return "FAIL", "違いが 13 章に出ていない: " + reason
    return "REPORTED", reason + "（13 章: " + "・".join(ev) + "）"


def _expect_of(case, idx):
    e = case.get("expect", "exact")
    if isinstance(e, dict):
        return e.get(idx, e.get(str(idx), e.get("default", "exact")))
    return e


def _truth_of(case, idx, role, original):
    t = case.get("truth", {})
    if idx is None or not isinstance(idx, int):
        return original, False
    if idx in t or str(idx) in t:
        v = t[idx] if idx in t else t[str(idx)]
        if role.startswith("著者:") or role.startswith("英文著者:"):
            a, n = v.split("\t", 1) if "\t" in v else (("架空大学", v) if role.startswith("著者") else (v, ""))
            if role.startswith("著者:"):
                return (a if role.endswith("所属") else n), True
            return (a if role.endswith("氏名") else n), True     # 英文著者は "Name\tAffiliation"
        if role in ("表", "画像"):
            raise ValueError(f"段落 {idx}: 表・画像には truth を書けない")
        return v, True
    return original, False


def _report13(text: str) -> str:
    m = re.search(r"^## 13\..*?(?=^## 14\.|\Z)", text, re.S | re.M)
    return m.group(0) if m else ""


def _xml_text(path) -> str:
    """XML のすべての文字（空白を除く）。"""
    from lxml import etree
    parser = etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False)
    root = etree.fromstring(Path(path).read_bytes(), parser)
    return _strip("".join(root.itertext()))


def run_case(case, workdir=None) -> dict:
    """反例 1 つを実行して判定する。"""
    import jasme_jats
    from jasme_jats import pdfmatch
    from jasme_jats.config import ArticleMeta, JournalConfig
    from jasme_jats.pipeline import Options, convert

    out = {k: case.get(k) for k in ("name", "angle", "item", "expect", "note")}
    out.update(verdict="FAIL", error="", fidelity_ok=None, report13="", paras=[])
    code_root = Path(jasme_jats.__file__).resolve().parents[2]
    mf = _fixtures(code_root)
    tmp = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="oracle_"))
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    src_docx = tmp / "case.docx"
    try:
        order = build_docx(case, src_docx, mf)
        original = read_paragraphs(src_docx)
        mapping = map_paragraphs(order, original)
    except Exception as e:  # noqa: BLE001
        out["error"] = "反例の docx を作れなかった（仕組みか反例の不具合）: " + "".join(
            traceback.format_exception_only(type(e), e)).strip()
        return out
    pdf = tmp / "dummy.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    pages = list(case["pages"])
    saved = pdfmatch.extract_pages
    pdfmatch.extract_pages = lambda path: pages
    journal = JournalConfig.load()
    meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12",
                                  "pub_date": "2026-03-31", "received": "2025-06-01", "accepted": "2025-11-20",
                                  "peer_review": "あり", "keywords": "proof; 論証; 数学的探究"})
    try:
        res = convert(src_docx, meta, journal, Options(out_dir=tmp / "out", pdf_path=pdf, route="pdf",
                                                       convert_metafiles=False))
    except Exception as e:  # noqa: BLE001
        out["error"] = "変換が止まった: " + "".join(traceback.format_exception(type(e), e, e.__traceback__))[-1500:]
        return out
    finally:
        pdfmatch.extract_pages = saved
    fx = res.docx_fix
    fixed_path = fx.path if fx is not None else src_docx
    fixed = dict(read_paragraphs(fixed_path))
    report = res.report_path.read_text(encoding="utf-8")
    r13 = _report13(report)
    out["report13"] = r13
    out["fidelity_ok"] = bool(res.fidelity.ok and res.fidelity.final_ok)
    try:
        xml_all = _xml_text(res.xml_path)
    except Exception as e:  # noqa: BLE001
        xml_all = None
        out["error"] = f"XML を読めなかった: {e}"
    rank = {"OK": 0, "REPORTED": 1, "FAIL": 2}
    worst = "OK"
    for src, otext in original:
        label, idx, role = mapping.get(src, (f"既定:テンプレート({src})", None, "テンプレート"))
        ftext = fixed.get(src)
        row = {"label": label, "index": idx, "role": role, "src": src, "original": otext, "fixed": ftext}
        if ftext is None:
            row.update(truth=None, verdict="FAIL", reason="直した docx にこの段落がない")
        else:
            try:
                truth, has = _truth_of(case, idx, role, otext)
            except ValueError as e:
                out["error"] = str(e)
                return out
            row["truth"] = truth if has else None
            v, why = judge(otext, ftext, truth, has, _expect_of(case, idx),
                           lambda segs, s=src: evidence(res, s, segs, r13))
            # XML の本文に、直した docx の段落の文字があるか（反例の段落だけ。空・画像・表は除く）
            if (xml_all is not None and isinstance(idx, int) and role not in ("表", "画像") and _strip(ftext)
                    and _strip(ftext) not in xml_all):
                v = "FAIL"
                why = (why + "。" if why else "") + "XML の本文に直した docx の段落の文字が見つからない"
            row.update(verdict=v, reason=why)
        out["paras"].append(row)
        worst = max(worst, row["verdict"], key=rank.get)
    extra = set(fixed) - {s for s, _ in original}
    if extra:
        worst = "FAIL"
        out["error"] = f"直した docx に元の docx にない段落がある: {sorted(extra)}"
    if not out["fidelity_ok"]:
        worst = "FAIL"
        out["error"] = (out["error"] + "。" if out["error"] else "") + "不変性チェック（fidelity）が不合格"
    out["verdict"] = worst
    return out
