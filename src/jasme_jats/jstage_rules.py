"""J-STAGE の登載時チェックの再現。

J-STAGE『記事アップロードメッセージ一覧』（UM-01-004 別紙3）のエラーのうち、XML だけで判定できるものを
変換時に確かめる。DTD に適合していても J-STAGE のアップロードで弾かれる条件（題目と抄録の言語の対応など）を、
登載前に見つけるためのもの。
出典: https://www.jstage.jst.go.jp/static/files/ja/UM-01-004_sousa(henshu)_append3.pdf
"""
from __future__ import annotations

import datetime as _dt
import re

XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def _lang(el, default):
    cur = el
    while cur is not None:
        v = cur.get(XML_LANG)
        if v:
            return v
        cur = cur.getparent()
    return default


def _text(el) -> str:
    return "".join(el.itertext()).strip() if el is not None else ""


def _date(el):
    if el is None:
        return None
    try:
        y = int(_text(el.find("year")))
        m = int(_text(el.find("month")) or 1)
        d = int(_text(el.find("day")) or 1)
        return _dt.date(y, m, d)
    except (TypeError, ValueError):
        return None


def check(root, article_id: str = "", image_names=()):
    """最終出力の XML（目印を取り除いたもの）を調べる。戻り値: [(メッセージ ID, 内容)]"""
    out = []
    art_lang = root.get(XML_LANG) or "ja"
    am = root.find("front/article-meta")
    if am is None:
        return [("-", "article-meta がない")]
    tg = am.find("title-group")
    titles, subtitles, ttitles, tsubtitles = set(), set(), set(), set()
    if tg is not None:
        for el in tg.findall("article-title"):
            if _text(el):
                titles.add(_lang(el, art_lang))
        for el in tg.findall("subtitle"):
            if _text(el):
                subtitles.add(_lang(el, art_lang))
        for g in tg.findall("trans-title-group"):
            glang = g.get(XML_LANG)
            for el in g.findall("trans-title"):
                if _text(el):
                    ttitles.add(el.get(XML_LANG) or glang or art_lang)
            for el in g.findall("trans-subtitle"):
                if _text(el):
                    tsubtitles.add(el.get(XML_LANG) or glang or art_lang)
    ja_en = {"ja": "日", "en": "英"}
    if not titles & {"ja", "en"}:
        out.append(("EMSGM097E", "タイトル(英)とタイトル(日)の両方が未設定"))
    for lg in subtitles - titles:
        out.append(("EMSGM098E/099E", f"サブタイトル({ja_en.get(lg, lg)})があるがタイトル({ja_en.get(lg, lg)})がない"))
    for lg in tsubtitles - ttitles:
        out.append(("EMSGM100E/101E", f"翻訳サブタイトル({ja_en.get(lg, lg)})があるが翻訳タイトル({ja_en.get(lg, lg)})がない"))
    for el in am.findall("abstract"):
        lg = _lang(el, art_lang)
        if lg not in titles:
            out.append(("EMSGM102E/103E", f"抄録({ja_en.get(lg, lg)})があるがタイトル({ja_en.get(lg, lg)})がない"))
        n = sum(len(_text(p)) for p in el.findall("p"))
        if n > 4000:
            out.append(("-", f"抄録が {n} 文字（上限 4000）"))
    for el in am.findall("trans-abstract"):
        lg = el.get(XML_LANG) or art_lang
        if lg not in ttitles:
            out.append(("EMSGM104E/105E", f"翻訳抄録({ja_en.get(lg, lg)})があるが翻訳タイトル({ja_en.get(lg, lg)})がない"))
        n = sum(len(_text(p)) for p in el.findall("p"))
        if n > 4000:
            out.append(("-", f"翻訳抄録が {n} 文字（上限 4000）"))
    if len(am.findall("abstract")) > 1 or len(am.findall("trans-abstract")) > 1:
        out.append(("-", "抄録・翻訳抄録はそれぞれ 1 つまで（ガイドライン 3.1.23）"))

    # 日付の前後関係
    hist = {d.get("date-type"): _date(d) for d in am.findall("history/date")}
    for d in am.findall("history/date"):
        filled = [bool(_text(d.find(x))) for x in ("day", "month", "year")]
        if any(filled) and not all(filled):
            out.append(("-", f"日付（{d.get('date-type')}）の年・月・日の一部だけが入っている（すべて入れるか、すべて空にする）"))
    if "approved" in hist and "accepted as received" in hist:
        out.append(("-", "最終査読日（査読あり）と査読なし受付日（査読なし）の両方がある"))
    pub = next((_date(p) for p in am.findall("pub-date") if p.get("pub-type") == "ppub"), None)
    rec, acc = hist.get("received"), hist.get("accepted")
    if rec and acc and rec > acc:
        out.append(("EMSGM106E", "受付日が掲載決定日（受理日）より後"))
    if rec and pub and rec > pub:
        out.append(("EMSGM107E", "受付日が発行日より後"))
    if acc and pub and acc > pub:
        out.append(("EMSGM108E", "掲載決定日（受理日）が発行日より後"))

    # 著作権表記は日英両方か、どちらもないか
    for tag, name in (("copyright-statement", "コピーライト"), ("copyright-holder", "著作権保持者")):
        langs = {_lang(el, art_lang) for el in am.findall(f"permissions/{tag}")}
        if langs and langs != {"ja", "en"}:
            out.append(("EMSGM111E/112E", f"{name}(日)・(英)の片方しかない"))

    # 著者と所属
    cg = am.find("contrib-group")
    if cg is not None:
        ids = [a.get("id") for a in cg.findall("aff")] + [a.get("id") for a in cg.findall("aff-alternatives")]
        for c in cg.findall("contrib"):
            for x in c.findall("xref"):
                if x.get("ref-type") == "aff" and x.get("rid") not in ids:
                    out.append(("EMSGM115E", f"著者所属対応番号 {x.get('rid')} の所属がない"))
            if not any(_text(s) for s in c.iter("surname")) and not any(_text(s) for s in c.iter("collab")):
                out.append(("EMSGM233E/250E", "著者名・姓（日・英）がない著者がいる"))
        expect = [f"aff{i}" for i in range(1, len(ids) + 1)]
        if ids and sorted(ids, key=lambda s: int(re.sub(r"\D", "", s) or 0)) != expect:
            out.append(("EMSGM116E", f"所属番号が連番ではない（{', '.join(ids)}）"))
        for a in list(cg.iter("aff")):
            if not _text(a):
                out.append(("EMSGM117E", "所属(英)と所属(日)の両方が未設定の所属がある"))

    kgs = am.findall("kwd-group")
    kwds = [_text(k) for kg in kgs for k in kg.findall("kwd")]
    if kgs and not any(kwds):
        out.append(("EMSGM234E", "キーワード(英)とキーワード(日)の両方が未設定（kwd-group だけがある）"))
    if len(kwds) > 100:
        out.append(("EMSGM149E", f"キーワードが {len(kwds)} 個ある（上限 100 個）"))
    for k in kwds:
        if len(k) > 1000:
            out.append(("-", f"キーワード「{k[:20]}…」が 1000 文字を超える"))

    if not _text(am.find("fpage")) and not _text(am.find("elocation-id")):
        out.append(("EMSGM230E", "開始ページと論文番号の両方が未設定"))
    if _text(am.find("lpage")) and not _text(am.find("fpage")):
        out.append(("EMSGM232E", "終了ページがあるが開始ページがない"))

    doi = next((_text(a) for a in am.findall("article-id") if a.get("pub-id-type") == "doi"), "")
    if doi and not re.fullmatch(r"[A-Za-z0-9().\-/;_]+", doi):
        out.append(("EMSGM256E", f"DOI に使えない文字がある（{doi}）"))

    # 引用文献。記述言語は ref → ref-list → article の xml:lang の順に決まる（ガイドライン別紙 2）
    for ref in root.iter("ref"):
        if not _lang(ref, ""):
            out.append(("EMSGM247E", f"引用文献 {ref.get('id')} の記述言語（xml:lang）がない"))
        for mc in ref.findall("mixed-citation"):
            if len(_text(mc)) > 4000:
                out.append(("-", f"引用文献 {ref.get('id')} が 4000 文字を超える"))

    # 画像のファイル名
    for name in image_names:
        if article_id and name.startswith(article_id + "."):
            out.append(("EMSGM248E", f"画像ファイル名が「記事識別子.」で始まっている（{name}）"))
        if not re.fullmatch(r"[A-Za-z0-9._\-]+", name):
            out.append(("EMSGM034E", f"画像ファイル名に英数字以外が含まれている（{name}）"))
    return out
