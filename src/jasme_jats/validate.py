"""J-STAGE 指定の DTD（JATS 1.1 Journal Publishing）による妥当性検証。

J-STAGE が公開している DTD 一式（https://www.jstage.jst.go.jp/dtds/1.1/）を dtd/ に同梱している。
同梱版は NLM が公開している JATS 1.1 の DTD と同一であることを確認済み（2026-10）。
ネットワークに接続せずに検証できる。

注意: validate() は実体を解決しない（resolve_entities=False。外部実体を読まないための安全な設定）ので、未定義の実体参照
（`&foo;` など）や DOCTYPE の内部サブセットで定義した実体は、DTD 検証では見つからず「妥当」になる。補いとして、AI の MathML は
parse_mathml が実体参照・コメント・処理命令・DOCTYPE を不採用にし、最終出力は fidelity.final_check が、実体の宣言（<!ENTITY）が
あれば解決せずに不合格にし、なければ実体を解決する設定でも読めること（未定義の実体参照がないこと）を確かめる。
"""
from __future__ import annotations

import re
from pathlib import Path

from lxml import etree

DTD_PATH = Path(__file__).resolve().parent / "dtd" / "JATS-journalpublishing1.dtd"
_DTD = None
_NAMES = None


def load_dtd():
    global _DTD
    if _DTD is None:
        _DTD = etree.DTD(str(DTD_PATH))
    return _DTD


def jats_element_names() -> frozenset:
    """JATS（同梱の DTD）の要素名の集合（このツールが出力する要素名は、DTD に合うので、すべてここに入る）。
    変換レポートの文の中の「タグの形」が、ツールの書いたタグか、docx の文字（x<y かつ z>w など）かを見分けるのに使う（report.md_tag）。"""
    global _NAMES
    if _NAMES is None:
        _NAMES = frozenset(e.name for e in load_dtd().iterelements())
    return _NAMES


# DTD のエラーの場所に使う、id を持つ要素の呼び方
PLACE_KINDS = {"ref": "引用文献", "table-wrap": "表", "fig": "図", "fn": "注", "disp-formula": "数式", "app": "資料",
               "aff": "所属", "sec": "節"}
EXCERPT = 15


# lxml の英語の文のうち、よく出る形の日本語の説明（先頭から照合する）。知らせの文は「日本語の説明（英語の文）」の形にする
JA_MESSAGES = (
    (r"Element (\S+) is not declared in (\S+) list of possible children", "要素 {1} は、{2} の中に置けません"),
    (r"Element (\S+) was declared #PCDATA but contains non text nodes", "要素 {1} は文字だけの要素ですが、ほかの要素が入っています"),
    (r"Element (\S+) content does not follow the DTD", "要素 {1} の中身が、DTD の決まり（要素の並び・数）に合いません"),
    (r"Element (\S+) does not carry attribute (\S+)", "要素 {1} に、必要な属性 {2} がありません"),
    (r"No declaration for attribute (\S+) of element (\S+)", "要素 {2} に、DTD にない属性 {1} があります"),
    (r"No declaration for element (\S+)", "要素 {1} は DTD にありません"),
    (r"Value \"([^\"]*)\" for attribute (\S+) of (\S+) is not among the enumerated set", "要素 {3} の属性 {2} の値「{1}」は、DTD が認める値ではありません"),
    (r"ID (\S+) already defined", "id {1} が重複しています"),
    (r"IDREF attribute (\S+) references an unknown ID \"([^\"]*)\"", "属性 {1} の参照先 id「{2}」がありません"),
)


def ja_message(message: str) -> str:
    """lxml の英語の文を「日本語の説明（英語の文）」にする。よく出る形（JA_MESSAGES）だけで、ほかは英語の文のまま。"""
    for pattern, ja in JA_MESSAGES:
        m = re.match(pattern, message)
        if m:
            return ja.format("", *m.groups()) + f"（{message}）"
    return message


class DtdGroup:
    """同じエラーの文（lxml の英語の文）でまとめたもの。message: 日本語の説明（英語の文）、count: 件数、places: 場所（重複なし・出現順）、
    kinds: 場所の要素名。"""

    def __init__(self, message: str):
        self.message = ja_message(message)
        self.count = 0
        self.places = []
        self.kinds = set()


def group_errors(errors) -> list:
    """validate() のエラーの一覧を、同じ文ごとにまとめる（出現順）。場所のない文字列は、文そのものを同じ文として扱う。"""
    groups = {}
    for e in errors:
        raw = getattr(e, "message", str(e))
        g = groups.get(raw)
        if g is None:
            g = groups[raw] = DtdGroup(raw)
        g.count += 1
        place = getattr(e, "place", "")
        if place and place not in g.places:
            g.places.append(place)
        if getattr(e, "kind", ""):
            g.kinds.add(e.kind)
    return list(groups.values())


class DtdError(str):
    """DTD 検証のエラー 1 件。文字列としては「場所: 日本語の説明（lxml の英語の文）」（場所が分からなければ文だけ。ja_message）。

    message: lxml の英語の文、place: 原因の場所（例: 引用文献 129件目（B129）「冒頭」。where になければ「引用文献 B129「冒頭」」）、
    kind: 場所の要素名（ref・table-wrap など）。
    """

    def __new__(cls, message: str, place: str = "", kind: str = ""):
        shown = ja_message(message)
        s = super().__new__(cls, f"{place}: {shown}" if place else shown)
        s.message, s.place, s.kind = message, place, kind
        return s


def _qname(el) -> str:
    q = etree.QName(el)
    return f"{el.prefix}:{q.localname}" if el.prefix else q.localname


def _place_of(el, where) -> tuple:
    """要素 el の場所 (文, 要素名)。id を持つ最も近い祖先（where にその id の場所があればそれ、なければ「引用文献 B129「冒頭」」）。
    id を持つ祖先がなければ、題名（title）を持つ最も近い祖先（本文の id のない節など）の題名。どちらもなければ ("", "")。"""
    anc, titled = el, None
    while anc is not None and anc.get("id") is None:
        if titled is None and isinstance(anc.tag, str) and anc.tag != "body" and anc.find("title") is not None:
            titled = anc
        anc = anc.getparent()
    if anc is not None:
        kind = anc.tag if isinstance(anc.tag, str) else ""
        if anc.get("id") in where:
            return where[anc.get("id")], kind
        detail = "".join("".join(anc.itertext()).split())[:EXCERPT]
        return f"{PLACE_KINDS.get(kind, kind)} {anc.get('id')}" + (f"「{detail}」" if detail else ""), kind
    if titled is not None:
        title = "".join("".join(titled.find("title").itertext()).split())[:EXCERPT]
        if title:
            return f"{PLACE_KINDS.get(titled.tag, titled.tag)}「{title}」の中", ""
    return "", ""


def _locate(root, errors, where) -> list:
    """エラーごとの (場所, 要素名) を返す（できなければ空の一覧）。

    検証した XML は 1 行なので、lxml のエラーの行からは要素が引けない。そこで、検証用に pretty_print した写しを作って検証し直し、
    エラーの行にある要素から、id を持つ祖先（ref の B 番号など）を辿る。写しは場所を引くためだけに使い、出力の XML は変えない。
    写しのエラーの数が合わなければ（空白の扱いの違いなど）、場所は付けない。
    """
    copy = etree.fromstring(etree.tostring(root, pretty_print=True),
                            etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False, huge_tree=True))
    dtd = load_dtd()
    dtd.validate(copy)
    found = list(dtd.error_log.filter_from_errors())
    if len(found) != len(errors):
        return []
    by_line = {}
    for el in copy.iter():
        if isinstance(el.tag, str):
            by_line.setdefault(el.sourceline, []).append(el)
    out = []
    for e in found:
        m = re.match(r"Element (\S+) is not declared in (\S+) list of possible children", e.message)
        names = [x for x in by_line.get(e.line, [])]
        if m:       # 行は、宣言のない子ではなく、その親の行
            cands = [x for x in names if _qname(x) == m.group(2)]
            cands = [x for x in cands if any(isinstance(c.tag, str) and _qname(c) == m.group(1) for c in x)] or cands
        else:
            m = re.match(r"Element (\S+) ", e.message)
            cands = [x for x in names if m and _qname(x) == m.group(1)]
        el = cands[0] if cands else None
        out.append(_place_of(el, where))
    return out


def validate(xml_bytes: bytes, where=None):
    """XML（DOCTYPE 付きでもよい）を DTD で検証する。戻り値: (妥当か, エラーの一覧)

    エラーは文字列（DtdError）で、原因の場所（id を持つ祖先。例: 引用文献 B129。id がなければ題名を持つ祖先の題名）が分かるときは
    「場所: 日本語の説明（lxml の英語の文）」。where は {要素の id: 場所の文（例: 引用文献 129件目（B129）「冒頭」）}（省略できる。
    引用文献・表などの id から、docx の段落を示すのに使う）。
    """
    where = where or {}
    parser = etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False, huge_tree=True)
    root = etree.fromstring(xml_bytes, parser)
    dtd = load_dtd()
    ok = dtd.validate(root)
    errors = []
    if not ok:
        msgs = [e.message for e in dtd.error_log.filter_from_errors()]
        try:
            places = _locate(root, msgs, where)
        except etree.LxmlError:
            places = []
        for i, msg in enumerate(msgs):
            place, kind = places[i] if places else ("", "")
            errors.append(DtdError(msg, place, kind))
    return ok, errors
