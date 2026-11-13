"""ArticlePlan から J-STAGE 全文 XML（JATS 1.1 Journal Publishing, FULL-J）の要素木を作る。

ここで作る木には追跡用の目印（tracking.py）が入っている。文字の不変性チェックの後、
finalize() で目印を取り除いてから出力する。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from lxml import etree

from . import emit as E
from .article import (ArticlePlan, BackSec, BoxNode, FigNode, FnNode, FormulaNode, ListNode, PNode, QuoteNode, RefNode,
                      Sec, TableNode, _para_text)
from .config import ArticleMeta, JournalConfig, keyword_problem
from .docx_reader import table_head, table_where
from .model import OBJ, Exclusion, Newline, Para
from .ooxml import is_ws
from .structure import CAP_BRANCH_NUM, CAP_BRANCH_SEP
from .tracking import AI, GEN, IMPLICIT, JX_NS, ORDER, SPAN

MML_NS = "http://www.w3.org/1998/Math/MathML"
XLINK = "http://www.w3.org/1999/xlink"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
ALI = "http://www.niso.org/schemas/ali/1.0/"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
DOCTYPE = ('<!DOCTYPE article PUBLIC "-//NLM//DTD JATS (Z39.96) Journal Publishing DTD v1.1 20151215//EN" '
           '"https://www.jstage.jst.go.jp/dtds/1.1/JATS-journalpublishing1.dtd">')

RE_JA_CHARS = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff々]")
# 図・表のキャプションの「番号 + 枝番」（枝番の区切りは structure.CAP_BRANCH_SEP。枝番とみなすキャプションの番号〈RE_CAP_BRANCH〉と同じ。枝番の数字は CAP_BRANCH_NUM）
RE_LABEL_SPLIT = re.compile(rf"^([\s\u3000]*)((?:図|表|Figure|Fig\.?|Table)[\s\u3000]*[0-9０-９]+(?:[{CAP_BRANCH_SEP}]{CAP_BRANCH_NUM})?)"
                            r"([\s\u3000:：.．]*)")
RE_HEAD_SPLIT = re.compile(r"^([\s\u3000]*)([0-9０-９]{1,2}[．.]|[(（][0-9０-９]{1,2}[)）]|[①-⑳])([\s\u3000]*)(?=\S)")
NEWLINE_SHOWN = 10      # レポートの 10 章の改行の一覧に並べる段落の数（それより多ければ「ほか N 段落」）
# 変更履歴ですべての行が削除された表（docx_reader が行をすべて読み飛ばした表。修正計画の N8）の 10 章の警告
ALL_ROWS_DELETED_MSG = ("{where}: 変更履歴で表のすべての行が削除されています（Word で変更をすべて承諾すると、表が消えます）。XML には"
                        "{what}を出力しました。Word で確かめ、表が要らなければ、{how}保存してから変換し直してください。")
# 表の縦の結合を XML の表の形に合わせて変えたときの 10 章の警告（文字は落とさない。Action にはしない）
TABLE_HEAD_SPAN_MSG = ("{where}: 見出し行から本文の行へ続く縦の結合を、見出し行の終わりで止めました（本文の行の側は別のセルとして"
                       "出力しました。文字は落としていません）。")
TABLE_SPAN_MISMATCH_MSG = ("{where}の {row} 行目: 縦に結合したセルの幅（横に結合した列の数）が上の行のセルと違うため、結合せずに"
                           "別のセルとして出力しました。Word で表の結合を確かめてください。")
# 題目・副題・著者名・所属の段落に Word の自動番号があるときの 10 章の警告（番号は XML に出さない。J-STAGE の書誌に入らないように）
UNSHOWN_NUMBERS_MSG = ("題目・副題・著者名・所属の段落に、Word の自動番号があります（{items}）。J-STAGE の書誌に番号が入らないよう、XML には番号を"
                       "出していません（Word の表示と違います）。番号が題目・副題・著者名・所属の一部なら、Word で番号を文字として打ち込んでから"
                       "変換し直してください。番号が要らなければ、このままでかまいません。")


@dataclass
class BuildInfo:
    slots: list = field(default_factory=list)        # 出力した画像の置き場所（article.ImageSlot。XML の出現順。重なりなし）
    slot_names: dict = field(default_factory=dict)   # 出力した置き場所の幹（ImageSlot.key）-> 名前（Builder.slot_name）
    warnings: list = field(default_factory=list)
    drops: list = field(default_factory=list)        # (src, text, reason)
    exclusions: list = field(default_factory=list)   # Exclusion（書き出しの段階で出力しないと決めたもの）
    notes: list = field(default_factory=list)        # (category, src, message) 機械的な判断の記録
    newlines: list = field(default_factory=list)     # 段落の中の改行（model.Newline。段落ごとにまとめたもの。10 章と要確認）
    # 姓と名を分けられなかった氏名 [(段落の ID, 氏名〈前後の空白・タブを除く〉, 言語 ja / en)]。AI 依頼文の「姓と名の区切りがない
    # 氏名」に使う（ai_assist.build_request。notes の文言から氏名を切り出さない）
    unsplit_names: list = field(default_factory=list)
    # 出力した表 [(<table> の要素, model.Table, Word で探す手がかり)]。pipeline.table_problems が出力した表の形を確かめるのに使う
    tables: list = field(default_factory=list)
    # 番号を XML に出さなかった題目・副題・著者名・所属の段落 [(段落 ID, 番号, 場所の名前, 段落の文字の冒頭 20 字)]
    # （10 章の警告。pipeline.lost_autonums は飛ばす）
    unshown_numbers: list = field(default_factory=list)
    # 利用者に確かめてもらう和文の著者名の分け方 [(段落 ID, EasternSplit)]: 字の間の空白のいちばん長い所で分けたもの・境目を
    # 推定して分けたもの・AI が分けたもの・分けられなかったもの（how が longest / context / count / ai / none。要確認 name_split。
    # AI 依頼文）
    name_splits: list = field(default_factory=list)


# ---------------------------------------------------------------------------- 和文の著者名の姓と名（C010・C064・C072）
NAME_WS = " \u3000\t"                           # 氏名の空白（AI の split_name の検証〈ai_assist.apply_ops〉と同じ）
RE_NAME_WS = re.compile(r"[ \u3000\t]+")
# 推定 a の手がかり（姓の候補の後ろに続く、引用の形）。年: 4 桁の数字（「2020a」も可。直後が数字なら年でない。直後が「年」なら日付なので除く）か
# 「印刷中」「in press」。姓の後ろには、氏名らしい「・共著者」（漢字・かな・カナで 1〜4 字か、英字の姓。その後ろが年の括弧・コンマと年・
# さらに「・共著者」・「ら」「他」「ほか」のどれかで続く）と、「ら」「他」「ほか」をはさんでよい。形は 2 つ: 「姓（2015）」「姓 (2015)」
# （括弧の中が年で始まる。姓との間に空白があってもよい）と、「姓，2015」「姓, 2015」（コンマと年）。年でない数字（「中1」）や、ただの
# 「・」「，」は手がかりにしない。閉じ括弧までの表記は surname_hint が足す
_CITE_YEAR = r"(?:[0-9０-９]{4}(?![0-9０-９])[a-zａ-ｚ]?(?!年)|印刷中|[Ii]n press)"
_CITE_YEAR_COMMA = r"[0-9０-９]{4}(?![0-9０-９年])[a-zａ-ｚ]?(?!年)"
_CO_AUTHOR = r"(?:[ぁ-ゖァ-ヺーヽヾ㐀-䶿一-鿿豈-﫿々〆ヵヶー]{1,4}|[A-Za-zÀ-ÖØ-öø-ÿ]+)"
RE_CITE_AFTER = re.compile(
    r"(?:・" + _CO_AUTHOR + r")*(?:ら|他|ほか)?"
    r"(?:[ \u3000]*[（(][ \u3000]*" + _CITE_YEAR + r"|[ \u3000]*[，,][ \u3000]*" + _CITE_YEAR_COMMA + r")")
# 姓の候補の直後が「・」で、その後ろの語が学校種・学年などの一般の語（「小・中学校（2019）」「高・大接続（2019）」）なら、手がかりにしない。
# 1 字の語（小・中・高・大・幼）は、語として終わっているとき（後ろが氏名の字でない）だけ。学校・学年を表す語で始まるもの、
# 「学校」「接続」「連携」「一貫」を含むもの（「・」から次の区切りまで）も一般の語
_GENERAL_ONE = "小中高大幼"
RE_GENERAL_AFTER_DOT = re.compile(
    r"(?:[" + _GENERAL_ONE + r"](?![ぁ-ゖァ-ヺーヽヾ㐀-䶿一-鿿豈-﫿々〆ヵヶA-Za-z])"
    r"|学校|学年|年生|中学|高校|高等|大学|小学|幼稚|幼児)"
    r"|[^\s（()）,，、。・\n]*(?:学校|接続|連携|一貫)")
# 姓の候補の前にあれば、別の語の一部（「小林（2019）」の「林」）とみなす文字
CLOSE_REACH = 20      # 引用の表記を閉じ括弧まで示すときに、年の後ろを見る字数
RE_NAME_BEFORE = re.compile(r"[㐀-䶿一-鿿豈-﫿々〆ヵヶ]")
RE_LATIN = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]")   # ローマ字（全角の英字は和文の字として扱う）
# 落とした空白の理由（7 章）。姓と名の間の空白は、どう分けたかが分かるように書く
NAME_GAP_REASONS = {"single": "姓と名の間の空白", "longest": "姓と名の間の空白（いちばん長い空白）",
                    "context": "姓と名の間の空白（推定: いちばん長い空白が複数あるので、論文の中の表記から）",
                    "count": "姓と名の間の空白（推定: いちばん長い空白が複数あるので、字数から）",
                    "ai": "姓と名の間の空白（AI の指定）", "latin": "姓と名の間の空白", "western": "姓と名の間の空白"}
NAME_INNER_REASON = "氏名の字間の空白"
NAME_EDGE_REASON = "氏名の前後の空白"


@dataclass
class EasternSplit:
    """和文の氏名の姓と名の分け方（split_eastern の結果）。

    how: none（分けない。空白がない）・single（空白が 1 か所）・latin（ローマ字の氏名で空白が 2 か所以上。最初の空白で分け、ほかの
    空白は残す）・longest（字の間に空白が 2 か所以上あり、いちばん長い空白が 1 か所で、そこで分けた）・
    context（いちばん長い空白が 2 か所以上あって境目を決められず、論文の中の表記から推定した）・count（同じく、字数だけから推定した）・
    ai（AI の指定。機械の分け方と同じ位置の指定は ai にせず、機械の how のままにする）。
    name は前後の空白を除いた氏名（Word の表示の文字。字の間の空白も含む）、surname・given は字の間の空白を除いた姓・名、
    gap は姓と名の間の空白の範囲（氏名の段落の文字の上。AI の指定で空白のない位置なら開始 = 終了。分けないなら None）、
    hint は推定 context の根拠にした論文の中の表記（引用の括弧と年まで）、
    machine は how が ai のとき、AI の指定がなければ機械がどう分けたか（EasternSplit）。"""
    how: str
    name: str = ""
    surname: str = ""
    given: str = ""
    gap: tuple = None
    hint: str = ""
    machine: "EasternSplit" = None

    @property
    def guessed(self) -> bool:
        return self.how in ("context", "count")

    def describe(self) -> str:
        """機械の分け方（how が ai 以外）の文。AI が分けたときに、AI の指定がなければどう分けていたかを書くのに使う（4 章の記録と
        要確認 name_split の文）。"""
        to = f"{self.surname}／{self.given}"
        return {"none": "空白がなく分けられなかった",
                "single": f"空白の位置で {to} に分けていた",
                "latin": f"最初の空白で {to} に分けていた",
                "longest": f"いちばん長い空白で {to} に分けていた",
                "context": f"論文の中の表記「{self.hint}」から {to} と推定していた",
                "count": f"字数だけから {to} と推定していた"}[self.how]


def _no_ws(s: str) -> str:
    return RE_NAME_WS.sub("", s)


def name_context(plan) -> str:
    """推定 a（論文の中の表記）で見る文字: 著者名の段落を除くすべての段落（本文・注・引用文献など）の文字を、改行でつないだもの。"""
    own = {p.src for a in plan.authors for p in (a.name_ja, a.name_en) if p is not None}
    return "\n".join(p.text_only() for src, p in plan.paras.items() if src not in own)


def surname_hint(chars: str, k: int, context: str) -> str:
    """氏名（空白を除いた文字 chars）の先頭 k 文字が、論文の中に引用の形で「姓だけ」現れれば、その表記（例「（試験，2020）」）。なければ ""。

    引用の形（RE_CITE_AFTER）: 姓の直後（「ら」「他」「ほか」「・共著者」をはさんでよい）が、「（」「(」（前に空白があってもよい）と年、
    または「，」「,」と年。直前が漢字でないもの（「小林（2019）」の「林」は数えない）。同じ氏名の全体（空白なし）の一部として現れる
    ものは数えない。年でない数字（「中1」）や、ただの「・」「，」は手がかりにしない。表記は、姓の前の開き括弧から、閉じ括弧まで（括弧の形で、閉じ括弧が近く〈CLOSE_REACH 字以内〉になければ年まで）。
    姓の直後が「・」で、その後ろの語が学校種・学年などの一般の語（RE_GENERAL_AFTER_DOT）のとき、直前が「小・中」のような一般の語の
    並びのときは、手がかりにしない。"""
    sur = chars[:k]
    for m in re.finditer(re.escape(sur), context):
        i, j = m.start(), m.end()
        if i and RE_NAME_BEFORE.match(context[i - 1]):
            continue
        if context.startswith(chars, i):
            continue
        if context.startswith("・", j) and RE_GENERAL_AFTER_DOT.match(context, j + 1):
            continue                    # 「小・中学校（2019）」の「小」
        if sur in _GENERAL_ONE and i >= 2 and context[i - 1] == "・" and context[i - 2] in _GENERAL_ONE:
            continue                    # 「中・高（2019）」の「高」
        cite = RE_CITE_AFTER.match(context, j)
        if cite is None:
            continue
        start = i - 1 if i and context[i - 1] in "（(" else i
        end = cite.end()
        if context[start] in "（(" or re.search(r"[（(]", context[j:end]):
            tail = context[end:end + CLOSE_REACH]       # 閉じ括弧が近くにあれば、そこまで（「（林，2019, p.3）」）
            for n, ch in enumerate(tail):
                if ch in "）)":
                    end += n + 1
                    break
                if ch in "（(\n":
                    break
        return context[start:end]
    return ""


def _gap_width(text: str, s: int, e: int) -> int:
    """空白の連なり text[s:e] の見た目の長さ: 全角の空白を半角 2 つ分、ほかの空白（半角・タブ）を 1 として数える。"""
    return sum(2 if ch == "\u3000" else 1 for ch in text[s:e])


def split_eastern(text: str, context: str = "", split=None) -> EasternSplit:
    """和文の氏名（段落の文字 text）を姓と名に分ける規則（builder.Builder.person_name。pdfdocx._name_shape も同じ規則を使う）。

    split は AI の指定の位置（article.Author.split_ja。前後の空白の内側にあるときだけ使い、機械の推定より優先する）。
    AI の指定が機械の分け方と同じ位置で、機械の分け方が single・latin・longest なら、機械の結果をそのまま返す（AI は確かめただけ）。
    それ以外の AI の指定は how が ai で、machine に機械の分け方を添える。
    指定がなければ、氏名の中の空白の連なり（前後の空白と、氏名の後ろの注の参照とその前の空白を除く）で決める:
    1 つなら、そこで分ける（single）。2 つ以上（字の間に空白を入れて揃えた氏名）で、いちばん長い連なりが 1 つだけなら、そこで
    分ける（longest。長さは全角の空白を半角 2 つ分と数える）。いちばん長い連なりが 2 つ以上なら、その連なりのどれかを境目と推定する:
    (a) 境目の前の文字（姓の候補）が、論文の中（context。name_context）に引用の形で「姓だけ」現れ（surname_hint）、そうなる候補が
    ちょうど 1 つなら、そこ（context）。(b) 決まらなければ、字数から（空白を除いて 2 字なら 1 字目の後ろ、3 字以上なら姓を 2 字とする。
    その位置に連なりがなければ、いちばん近い連なり。count）。空白がなければ分けない（none）。
    同じ text・context・split なら、いつも同じ結果になる。"""
    mech = _split_by_rule(text, context)
    n = len(text)
    core_s, core_e = n - len(text.lstrip(NAME_WS)), len(text.rstrip(NAME_WS))
    if split is None or not core_s < split < core_e:
        return mech
    s = e = split
    for m in RE_NAME_WS.finditer(text, core_s, core_e):
        if m.start() <= split <= m.end():       # 指定の位置に接する空白は、姓と名の間の空白
            s, e = m.start(), m.end()
            break
    name = text[core_s:core_e]
    if mech.gap == (s, e) and mech.how in ("single", "latin", "longest"):
        return mech
    return EasternSplit("ai", name, _no_ws(text[core_s:s]), _no_ws(text[e:core_e]), (s, e), machine=mech)


def _split_by_rule(text: str, context: str) -> EasternSplit:
    """split_eastern の、AI の指定がないときの機械の分け方。"""
    n = len(text)
    core_s, core_e = n - len(text.lstrip(NAME_WS)), len(text.rstrip(NAME_WS))
    if core_s >= core_e:
        return EasternSplit("none")
    name = text[core_s:core_e]
    # 氏名の後ろの注の参照（OBJ）とその前の空白は、氏名の空白の数に数えない
    end = max(len(text[:core_e].rstrip(NAME_WS + OBJ)), core_s)
    runs = [(m.start(), m.end()) for m in RE_NAME_WS.finditer(text, core_s, end)]

    def at(s, e, how, hint=""):
        return EasternSplit(how, name, _no_ws(text[core_s:s]), _no_ws(text[e:core_e]), (s, e), hint)

    if not runs:
        return EasternSplit("none", name, name)
    if len(runs) == 1:
        return at(*runs[0], "single")
    if RE_LATIN.search(name):
        # ローマ字の氏名（和文の著者名の欄の「Taro Q SHIKEN」など）: 語の間の空白は字の間の空白ではないので、これまでどおり最初の空白で分け、
        # ほかの空白は残す（latin。知らせない）
        return at(*runs[0], "latin")
    longest = max(_gap_width(text, s, e) for s, e in runs)
    top = [(s, e) for s, e in runs if _gap_width(text, s, e) == longest]
    if len(top) == 1:
        return at(*top[0], "longest")
    chars = _no_ws(name)
    # 姓・名のどちらかが注の参照など（文字でないもの）だけになる境目は、候補にしない（すべてそうなら、すべてを候補にする）
    real = [(s, e) for s, e in top if _no_ws(text[core_s:s]).strip(OBJ) and _no_ws(text[e:core_e]).strip(OBJ)]
    cands = {len(_no_ws(text[core_s:s])): (s, e) for s, e in (real or top)}      # 姓の字数 -> 境目の空白
    found = {k: h for k in sorted(cands) for h in [surname_hint(chars, k, context)] if h}
    if len(found) == 1:
        [(k, hint)] = found.items()
        return at(*cands[k], "context", hint)
    want = 1 if len(chars) <= 2 else 2
    k = min(cands, key=lambda c: (abs(c - want), c))
    return at(*cands[k], "count")


def name_split_note(sp: EasternSplit) -> str:
    """4 章の記録（機械的な判断）の文。how が longest / context / count / ai のもの（要確認 name_split の文は report._name_split_line）。"""
    why = {"longest": "字の間の空白がいちばん長い所を境目とした",
           "context": f"いちばん長い空白が 2 か所以上あって境目を決められないので、論文の中の表記「{sp.hint}」から推定した",
           "count": f"いちばん長い空白が 2 か所以上あって境目を決められないので、字数だけから推定した（姓を {len(sp.surname)} 字とした）",
           "ai": f"AI の指定。AI の指定がなければ、{sp.machine.describe()}" if sp.machine is not None else "AI の指定"}[sp.how]
    return f"氏名「{sp.name}」を姓「{sp.surname}」・名「{sp.given}」に分けた（{why}）。字の間の空白は XML から落とした（7 章）"


def _overlaps(owner, col, span) -> bool:
    """列の範囲 [col, col+span) が、結合元（owner: 開始列 -> (セル, 幅)）のどれかの範囲と重なるか。"""
    return any(s < col + span and col < s + w for s, (_, w) in owner.items())


def _sub(parent, tag, text=None, **attrs):
    el = etree.SubElement(parent, tag)
    for k, v in attrs.items():
        if v is not None:
            el.set(k.replace("__", ":").replace("_", "-") if not k.startswith("{") else k, str(v))
    if text is not None:
        el.text = str(text)
    return el


def _lang(el, lang):
    el.set(XML_LANG, lang)
    return el


class Builder:
    def __init__(self, plan: ArticlePlan, meta: ArticleMeta, journal: JournalConfig, split_labels=None):
        self.plan = plan
        self.meta = meta
        self.j = journal
        self.split = journal.split_labels if split_labels is None else split_labels
        self.info = BuildInfo()
        self.article_id = meta.article_id(journal)
        self._named = set()
        # 表のセルの図キャプションで、docx に画像の見つからない図の置き場所: キャプションの段落の ID -> 置き場所（cell_content が
        # キャプションの段落の先頭に <inline-graphic> を書く。structure.Classifier.cell_figures_in）
        self.cell_empty = {s.caption.src: s for s in plan.slots
                           if s.place == "inline" and s.kind == "fig" and not s.covers and s.caption is not None}
        marks = word_note_marks(plan, journal)
        fn_numbers = {}
        for fn in plan.fns:
            if fn.word_note:
                fn.number = fn.number or marks[fn.word_id][0]
                fn_numbers[fn.word_id] = (fn.fid, plan.pdf_numbers.get(("fnref", fn.word_id), marks[fn.word_id][1]))
        self.marks = marks
        self._name_ctx = None
        # 任意の置き場所（結果のないフィールドの位置。修正計画 W1 の手順 15）: 段落の ID -> [(段落の文字の中の位置, 置き場所)]
        self.optional_slots = {}
        for s in plan.slots:
            if s.kind == "optional":
                self.optional_slots.setdefault(s.src, []).append((s.pos, s))
        self.em = E.Emitter(self.name_image, fn_numbers, plan.moved_images,
                            optional_fields=self.optional_slots.get, optional_namer=self.slot_name)

    def autonum(self, p) -> str:
        """段落の Word の自動番号（ルート2 では、全角・半角と字形を出版版 PDF に合わせたもの）。"""
        return self.plan.pdf_numbers.get(("auto", p.src), p.autonum)

    def autonum_mark(self, parent, p) -> None:
        """段落 p の Word の自動番号を、生成した文字（jx:gen kind autonum、src は p.src）として parent の今の末尾に補う
        （段落の jx:span の直前に呼ぶ）。番号と本文の区切りは、docx の文字が空白で始まるか、番号が全角の文字で終われば補わず、
        そうでなければ半角の空白 1 つ。"""
        if not p.autonum:
            return
        mark = self.autonum(p).strip()
        if mark:
            sep = "" if _starts_with_space(p) or unicodedata.east_asian_width(mark[-1]) in ("F", "W") else " "
            self.em.gen(parent, mark + sep, "autonum", p.src)

    def heading_title(self, parent, p):
        """後付け（付記・謝辞・注・引用文献・資料）と英文要旨の見出しの <title>。自動番号は <title> の先頭に生成文字で補う。"""
        t = _sub(parent, "title")
        self.autonum_mark(t, p)
        self.em.span(t, p, E.SECTITLE)
        return t

    def unshown_number(self, p, what) -> None:
        """題目・副題・著者名・所属の段落の自動番号は XML に出さず、記録する（10 章の警告。守り lost_autonums は飛ばす）。"""
        if (p.autonum or "").strip():
            self.info.unshown_numbers.append((p.src, self.autonum(p).strip(), what, p.text_only().strip()[:20]))

    # ------------------------------------------------------------------ 画像
    def name_image(self, img):
        """段落の中の画像（emit の image_namer）: その画像の置き場所の名前。置き場所の最初の画像でなければ None（何も書かない。
        同じ置き場所の 2 つ目以降の画像と、置き場所のない画像）。"""
        slot = self.plan.slot_of.get(img.image_id)
        if slot is None or not slot.covers or slot.covers[0] is not img:
            return None
        return self.slot_name(slot)

    def slot_name(self, slot) -> str:
        """画像の置き場所の名前（Graphics/ の中のファイル名）: 「{記事識別子}_{幹}.{拡張子}」（雑誌の設定 image_name_pattern）。
        この組み立てで出力する置き場所として info.slots に加える（同じ置き場所は 1 度だけ）。

        拡張子はいつも png（置き場所をすべて書いた XML〈pipeline.Result.xml_base〉の名前。入れた画像の形式に合わせるのは
        package.apply_images）。docx の画像は書き出さない（修正計画 W1）。
        """
        name = f"{self.j.image_name_pattern.format(article_id=self.article_id, key=slot.key)}.png"
        if id(slot) not in self._named:
            self._named.add(id(slot))
            self.info.slots.append(slot)
            self.info.slot_names[slot.key] = name
        return name

    # ------------------------------------------------------------------ 全体
    def build(self):
        nsmap = {"xsi": XSI, "mml": MML_NS, "xlink": XLINK, "ali": ALI, "jx": JX_NS}
        root = etree.Element("article", nsmap=nsmap)
        root.set("article-type", self.meta.article_type or self.j.article_type)
        root.set("dtd-version", "1.1")
        _lang(root, self.meta.lang or self.plan.lang or self.j.lang)
        front = _sub(root, "front")
        self.journal_meta(front)
        self.article_meta(front)
        body = _sub(root, "body")
        self.nodes(body, self.plan.body, top=True)
        if not len(body):
            root.remove(body)
        back = etree.Element("back")
        self.back(back)
        if len(back):
            root.append(back)
        self.em_warnings()
        self.newline_warnings()
        self.unshown_warnings()
        return root

    def unshown_warnings(self):
        """番号を出さなかった題目・副題・著者名・所属の段落があれば、10 章の警告を 1 行足す。"""
        if not self.info.unshown_numbers:
            return
        items = "、".join(f"{src}「{head}」（{what}）の「{num}」" for src, num, what, head in self.info.unshown_numbers)
        self.info.warnings.append(UNSHOWN_NUMBERS_MSG.format(items=items))

    def em_warnings(self):
        for w in sorted(set(self.em.math_warnings)):
            self.info.warnings.append(f"数式: {w}")

    def newline_warnings(self):
        """段落の中の改行（Word の Shift+Enter。emit の Newline）を段落ごとにまとめて info.newlines に入れ、レポートの 10 章の
        警告を、表のセル（<break/> を入れたもの）・知らせる文脈（題目・著者・所属・引用文献。要確認は report._newline_action）・
        そのほか（本文・見出し・要旨・キャプションなど。文字のまま）の組ごとに 1 行足す。"""
        per = {}
        for nl in self.em.newlines:
            got = per.get(nl.src)
            if got is None:
                per[nl.src] = Newline(nl.src, nl.count, nl.breaks, nl.cell, nl.label)
            else:
                got.count += nl.count
                got.breaks += nl.breaks
                got.cell = got.cell or nl.cell
                got.label = got.label or nl.label
        self.info.newlines = list(per.values())
        cells = [x for x in per.values() if x.cell]
        noted = [x for x in per.values() if not x.cell and x.label]
        other = [x for x in per.values() if not x.cell and not x.label]
        if cells:
            n, b = sum(x.count for x in cells), sum(x.breaks for x in cells)
            link = f"（リンクの中の {n - b} か所は、改行の文字のまま）" if b < n else ""
            self.info.warnings.append(
                f"表のセルの中に、改行（Shift+Enter）が {n} か所あります。Word と同じ位置で改行して表示されるように、XML では"
                f"その位置に改行の印（`<break/>`）を入れました{link}。J-STAGE のプレビューで、表のセルの中の改行の位置を"
                f"確かめてください: {self._newline_paras(cells)}")
        if noted:
            self.info.warnings.append(
                f"題目・著者・所属・引用文献の段落の中に、改行（Shift+Enter）が {sum(x.count for x in noted)} か所あります。"
                "XML では改行の文字のまま出力しました（J-STAGE の画面では、改行の位置が空白になるか、前後の文字が詰まって"
                "表示されることがあります。改行が要らなければ、Word で消して変換し直してください）: "
                f"{self._newline_paras(noted, label=True)}")
        if other:
            self.info.warnings.append(
                f"本文などの段落の中の改行（Shift+Enter）{sum(x.count for x in other)} か所は、XML では改行の文字のまま出力しました"
                "（J-STAGE の画面では、空白になるか、前後の文字が詰まって表示されることがあります。改行が要らなければ、Word で消して"
                f"変換し直してください）: {self._newline_paras(other)}")

    def _newline_paras(self, rows, label=False) -> str:
        """改行のある段落の一覧（d12・d13（場所）、…。場所が同じ段落はまとめる）。表のセルの段落の場所は、その表を Word で探す
        手がかり（キャプションの冒頭か、表の最初の文字。docx_reader.table_where。資料などの表のセルには本文の場所がないため）。
        label なら、場所の代わりに段落の文字の冒頭と文脈の名前（d3「…」（題目・副題）。題目・著者・所属には場所がないため）。"""
        if label:
            out = []
            for x in rows[:NEWLINE_SHOWN]:
                p = self.plan.paras.get(x.src)
                head = p.text_only().strip()[:20] if p is not None else ""
                out.append(f"{x.src}「{head}」（{x.label}）" if head else f"{x.src}（{x.label}）")
            rest = len(rows) - NEWLINE_SHOWN
            return "、".join(out) + (f"、ほか {rest} 段落" if rest > 0 else "")
        tables = self._cell_tables() if any(x.cell for x in rows) else {}
        groups = {}
        for x in rows[:NEWLINE_SHOWN]:
            groups.setdefault(tables.get(x.src) or self.plan.locations.get(x.src, ""), []).append(x.src)
        out = [f"{'・'.join(srcs)}（{where}）" if where else "・".join(srcs) for where, srcs in groups.items()]
        rest = len(rows) - NEWLINE_SHOWN
        return "、".join(out) + (f"、ほか {rest} 段落" if rest > 0 else "")

    def _cell_tables(self) -> dict:
        """表のセルの段落 ID -> その表を Word で探す手がかり（キャプションの冒頭か、表の最初の文字。docx_reader.table_where）。
        表で組んだ図の表は、図のキャプション。"""
        out = {}
        pairs = ([(t.table, t.caption) for t in self.plan.tables if t.table is not None]
                 + [(tb, f.caption) for f in self.plan.figures for tb in f.tables])
        for t, cap in pairs:
            where = table_where(table_head(t), cap.text_only() if cap is not None else "")
            for p in t.paragraphs():
                out.setdefault(p.src, where)
        return out

    # ------------------------------------------------------------------ journal-meta
    def journal_meta(self, front):
        j = self.j
        jm = _sub(front, "journal-meta")
        _sub(jm, "journal-id", j.journal_id, journal_id_type="j-stage")
        tg = _sub(jm, "journal-title-group")
        _lang(_sub(tg, "journal-title", j.title_ja), "ja")
        if j.title_en:
            ttg = _lang(_sub(tg, "trans-title-group"), "en")
            _sub(ttg, "trans-title", j.title_en)
        if j.abbrev:
            _sub(tg, "abbrev-journal-title", j.abbrev)
        if j.issn_print:
            _sub(jm, "issn", j.issn_print, pub_type="ppub")
        if j.issn_online:
            _sub(jm, "issn", j.issn_online, pub_type="epub")
        pub = _sub(jm, "publisher")
        _lang(_sub(pub, "publisher-name", j.publisher_ja), "ja")
        if j.publisher_en:
            _lang(_sub(pub, "publisher-name", j.publisher_en), "en")

    # ------------------------------------------------------------------ article-meta
    def article_meta(self, front):
        plan, meta, j = self.plan, self.meta, self.j
        am = _sub(front, "article-meta")
        doi = meta.doi_value(j)
        if doi:
            _sub(am, "article-id", doi, pub_id_type="doi")
        subj_ja, subj_en = j.subjects(meta)
        if subj_ja and not subj_en:
            self.info.warnings.append(f"原稿種別（英）が分からない（原稿種別（日）は「{subj_ja}」）")
        subjects = [("ja", subj_ja), ("en", subj_en)]
        if any(s for _, s in subjects):
            cats = _sub(am, "article-categories")
            for lang, subject in subjects:
                if subject:
                    sg = _lang(_sub(cats, "subj-group", subj_group_type="article"), lang)
                    _sub(sg, "subject", subject)
        self.title_group(am)
        self.contrib_group(am)
        dates = [("ppub", meta.pub_date), ("epub", meta.epub_date)]
        if not any(d for _, d in dates):
            pd = _sub(am, "pub-date", pub_type="ppub")
            _sub(pd, "year", "")
            self.info.warnings.append("発行日が未入力（<pub-date> の年を空にした）")
        for typ, d in dates:
            if d:
                pd = _sub(am, "pub-date", pub_type=typ)
                _sub(pd, "day", f"{d.day:02d}")
                _sub(pd, "month", f"{d.month:02d}")
                _sub(pd, "year", str(d.year))
        _sub(am, "volume", meta.volume or "")
        _sub(am, "issue", meta.issue or "")
        if not meta.volume or not meta.issue:
            self.info.warnings.append("巻・号が未入力")
        if not meta.fpage:
            self.info.warnings.append("開始ページが未入力（J-STAGE の通常公開記事では開始ページか論文番号が必須）")
        if meta.fpage:
            _sub(am, "fpage", meta.fpage)
            if meta.lpage:
                _sub(am, "lpage", meta.lpage)
        # 諸日付と査読の有無（ガイドライン 3.1.30）。査読ありは最終査読日 approved（日付が分からなければ年月日を空に）、
        # 査読なしは査読なし受付日 accepted as received（年月日を空に）。どちらもなければ資料の設定が引き継がれる
        hist = [("received", meta.received), ("rev-recd", meta.revised), ("accepted", meta.accepted)]
        if meta.peer_review == "yes":
            hist.append(("approved", meta.approved or "empty"))
        elif meta.peer_review == "no":
            hist.append(("accepted as received", "empty"))
            if meta.approved:
                self.info.warnings.append("査読なしなのに最終査読日が入力されている（最終査読日は出力しない）")
        else:
            self.info.warnings.append("査読の有無が未入力（J-STAGE では資料の査読あり/なしの設定が引き継がれる）")
        if any(d for _, d in hist):
            h = _sub(am, "history")
            for typ, d in hist:
                if d == "empty":
                    dt = _sub(h, "date", date_type=typ)
                    for part in ("day", "month", "year"):
                        _sub(dt, part, "")
                elif d:
                    dt = _sub(h, "date", date_type=typ)
                    _sub(dt, "day", f"{d.day:02d}")
                    _sub(dt, "month", f"{d.month:02d}")
                    _sub(dt, "year", str(d.year))
        if plan.abstract or plan.abstract_heading:
            # 英文要旨。J-STAGE では「抄録(英)」には「タイトル(英)」（article-title）、「翻訳抄録(英)」には
            # 「翻訳タイトル(英)」（trans-title）が対応していなければならない（記事アップロードメッセージ EMSGM102E/104E）。
            # 和文の論文では英語の題目が trans-title なので、英文要旨は trans-abstract にする。
            lang_abs = "en"
            if self.article_lang() == lang_abs:
                ab = _lang(_sub(am, "abstract"), lang_abs)
                if j.abstract_specific_use:
                    ab.set("specific-use", j.abstract_specific_use)
            else:
                ab = _lang(_sub(am, "trans-abstract"), lang_abs)
            if plan.abstract_heading:
                self.heading_title(ab, plan.abstract_heading)
            for p in plan.abstract:
                self.paragraph_or_formula(ab, p, E.ABSTRACT)
            n = sum(len("".join(pe.itertext())) for pe in ab.findall("p"))
            if n > 4000:
                self.info.warnings.append(f"英文要旨が {n} 文字あり、J-STAGE の上限（4000 文字）を超えている")
        for lang, kws in (("ja", meta.keywords_ja), ("en", meta.keywords_en)):
            if kws:
                kg = _lang(_sub(am, "kwd-group", kwd_group_type="author"), lang)
                for k in kws:
                    _sub(kg, "kwd", k)
        problem = keyword_problem(meta)
        if problem:
            self.info.warnings.append(problem)

    def article_lang(self) -> str:
        return self.meta.lang or self.plan.lang or self.j.lang

    def title_group(self, am):
        """題目。本文の言語の題目を article-title、もう一方の言語の題目を trans-title にする。

        J-STAGE では article-title が「タイトル（本文の言語）」、trans-title が「翻訳タイトル」として登録される。
        """
        plan = self.plan
        lang = self.article_lang()
        if lang == "en" and plan.title_en:
            main, main_sub, other, other_sub, other_lang = plan.title_en, plan.subtitle_en, plan.title, plan.subtitle, "ja"
        else:
            main, main_sub, other, other_sub, other_lang = plan.title, plan.subtitle, plan.title_en, plan.subtitle_en, "en"
        tg = _sub(am, "title-group")
        at = _lang(_sub(tg, "article-title"), lang)
        self.multi(at, main, E.TITLE, "題目")
        if not main:
            self.info.warnings.append("題目（スタイル「題目（日）」）が見つからない")
        self.check_length(at, 2000, "題目")
        if main_sub:
            st = _lang(_sub(tg, "subtitle"), lang)
            self.multi(st, main_sub, E.TITLE, "副題")
        if other:
            ttg = _lang(_sub(tg, "trans-title-group"), other_lang)
            tt = _sub(ttg, "trans-title")
            self.multi(tt, other, E.TITLE, "翻訳題目")
            self.check_length(tt, 2000, "翻訳題目")
            if other_sub:
                ts = _sub(ttg, "trans-subtitle")
                self.multi(ts, other_sub, E.TITLE, "翻訳副題")
        elif other_sub:
            self.info.warnings.append("副題（翻訳）があるが題目（翻訳）がない（J-STAGE ではエラーになる）")

    def check_length(self, el, limit, what):
        n = len("".join(el.itertext()))
        if n > limit:
            self.info.warnings.append(f"{what}が {n} 文字あり、J-STAGE の上限（{limit} 文字）を超えている")

    def multi(self, parent, paras, ctx, what):
        for p in paras:
            self.unshown_number(p, what)
            self.em.span(parent, p, ctx)

    def contrib_group(self, am):
        plan = self.plan
        if not plan.authors:
            self.info.warnings.append("著者（スタイル「著者名（日）」）が見つからない")
            return
        cg = _sub(am, "contrib-group")
        for i, a in enumerate(plan.authors, 1):
            c = _sub(cg, "contrib", contrib_type="author")
            if i in (self.meta.corresp or []):
                c.set("corresp", "yes")
            names = []
            if a.name_ja is not None:
                names.append(("eastern", "ja", a.name_ja, a.split_ja))
            if a.name_en is not None:
                names.append(("western", "en", a.name_en, a.split_en))
            holder = _sub(c, "name-alternatives") if len(names) > 1 else c
            for style, lang, p, split in names:
                self.person_name(holder, p, style, lang, split)
            for aff in a.affs:
                _sub(c, "xref", ref_type="aff", rid=aff.aid)
        for aff in plan.affs:
            if aff.ja is not None and aff.en is not None:
                alt = _sub(cg, "aff-alternatives", id=aff.aid)
                for lang, p in (("ja", aff.ja), ("en", aff.en)):
                    af = _lang(_sub(alt, "aff"), lang)
                    inst = _sub(af, "institution")
                    self.unshown_number(p, "所属")
                    self.em.span(inst, p, E.AFF)
            else:
                p = aff.ja if aff.ja is not None else aff.en
                af = _lang(_sub(cg, "aff", id=aff.aid), "ja" if aff.ja is not None else "en")
                inst = _sub(af, "institution")
                self.unshown_number(p, "所属")
                self.em.span(inst, p, E.AFF)

    def names_context(self) -> str:
        """推定 a で見る論文の文字（name_context。1 回の組み立てで 1 度だけ作る）。"""
        if self._name_ctx is None:
            self._name_ctx = name_context(self.plan)
        return self._name_ctx

    def person_name(self, parent, p: Para, style, lang, split):
        """氏名を姓と名に分ける。落とすのは空白だけ（姓と名の間の空白、和文の氏名の字の間の空白、氏名の前後の空白。検証のため記録する）。

        和文の氏名の分け方は split_eastern。字の間の空白のいちばん長い所で分けたもの・境目を推定したもの・AI が分けたもの
        〈機械の分け方と同じ位置の指定を除く〉・分けられなかったものは BuildInfo.name_splits に入れ（要確認 name_split）、4 章にも
        記録する。"""
        self.unshown_number(p, "著者名")
        nm = _lang(_sub(parent, "name", name_style=style), lang)
        text = p.plain()
        n = len(text)
        core_s, core_e = n - len(text.lstrip(NAME_WS)), len(text.rstrip(NAME_WS))
        core = text[core_s:core_e]
        if core_s >= core_e:            # 空白だけの氏名（ここには来ない）: 今までどおり全体を姓に入れる
            self.em.span(_sub(nm, "surname"), p, E.NAME)
            return
        gap, first, how = None, "surname", "western"
        if style == "eastern":
            sp = split_eastern(text, self.names_context(), split)
            gap, how = sp.gap, sp.how
            if how in ("longest", "context", "count", "ai"):
                self.info.name_splits.append((p.src, sp))
                self.info.notes.append(("name", p.src, name_split_note(sp)))
            elif how == "none":
                self.info.name_splits.append((p.src, sp))
        elif split is not None and core_s < split < core_e:
            gap, first = (split, split), "given"
        else:
            toks = [(t.start(), t.end()) for t in re.finditer(r"[^ \u3000\t]+", text[:core_e])]
            if len(toks) >= 2:
                caps = [k for k, (s, e) in enumerate(toks) if re.fullmatch(r"[A-ZÀ-Ý][A-ZÀ-Ý'’\-]+", text[s:e])]
                if len(caps) == 1 and caps[0] in (0, len(toks) - 1):
                    k = caps[0]
                else:
                    k = len(toks) - 1
                if k == len(toks) - 1:
                    gap, first = (toks[k - 1][1], toks[k][0]), "given"
                else:  # 姓が先頭（SUGAKU Taro）
                    gap = (toks[0][1], toks[1][0])
        if gap is None:
            self.info.notes.append(("name", p.src,
                                    f"氏名「{core}」に姓と名の区切り（空白）がないため、全体を姓として出力"))
            self.info.unsplit_names.append((p.src, core, lang))     # AI の split_name の検証（ai_assist.apply_ops）と同じ空白の扱い
            if lang == "en":
                # 英文の氏名は AI の split_name でも分けられない（和文の氏名だけ）ので、利用者に知らせる（10 章。決定事項 17）
                self.info.warnings.append(
                    f"英文の著者名「{core}」（段落 {p.src}）に姓と名の区切り（空白）がないため、全体を姓として"
                    "出力しました。名もある氏名なら、Word で姓と名の間に空白を入れて保存してから変換し直してください"
                    "（AI による補完では、英文の著者名は分けられません）。")
            parts = [("surname", core_s, core_e)]
        else:
            second = "given" if first == "surname" else "surname"
            parts = [(first, core_s, gap[0]), ("gap", gap[0], gap[1]), (second, gap[1], core_e)]
        holders = {kind: _sub(nm, "surname" if kind == "surname" else "given-names")
                   for kind in ("surname", "given") if any(k == kind for k, _, _ in parts)}
        # 書き出す順（docx の順）: (書き込む要素, 開始, 終了, 落とす理由〈空なら文字を書く〉)
        pieces = [(holders[parts[0][0]], 0, core_s, NAME_EDGE_REASON)]
        for kind, s, e in parts:
            if kind == "gap":
                pieces.append((holders["surname"], s, e, NAME_GAP_REASONS[how]))
                continue
            pos = s
            if style == "eastern" and how != "latin":   # 和文の氏名の字の間の空白は落とす（ローマ字の名の語の間の空白〈Taro Jiro〉は残す）
                for m in RE_NAME_WS.finditer(text, s, e):
                    pieces += [(holders[kind], pos, m.start(), ""), (holders[kind], m.start(), m.end(), NAME_INNER_REASON)]
                    pos = m.end()
            pieces.append((holders[kind], pos, e, ""))
        pieces.append((holders[parts[-1][0]], core_e, n, NAME_EDGE_REASON))
        seq = 0
        for holder, s, e, reason in pieces:
            if s >= e:
                continue
            if reason:
                self.em.drop(holder, p, s, e, seq, reason)
                self.info.drops.append((p.src, text[s:e], reason))
            else:
                self.em.span(holder, p, E.NAME, start=s, end=e, seq=seq)
            seq += 1

    # ------------------------------------------------------------------ 本文
    def nodes(self, parent, nodes, top=False):
        """本文の要素を書き出す。top は本文の最上位（最初の章見出しの前。<body> の直下）か。"""
        for node in nodes:
            if isinstance(node, Sec):
                self.sec(parent, node)
            elif isinstance(node, PNode):
                self.paragraph_or_formula(parent, node.para, E.BODY)
            elif isinstance(node, ListNode):
                self.list_node(parent, node)
            elif isinstance(node, QuoteNode):
                dq = _sub(parent, "disp-quote")
                for p in node.paras:
                    pe = _sub(dq, "p")
                    self.autonum_mark(pe, p)
                    self.em.span(pe, p, E.BODY)
            elif isinstance(node, FigNode):
                self.fig(parent, node)
            elif isinstance(node, TableNode):
                self.table_wrap(parent, node)
            elif isinstance(node, FormulaNode):
                self.formula(parent, node)
            elif isinstance(node, BoxNode):
                # J-STAGE の <body> の子は <p> と <sec> だけで、<boxed-text> は <sec>・<p> の子に置く（全文 XML 作成マニュアル
                # 3.5.4。docs/JSTAGE_NOTES.md）。本文の最上位（最初の章見出しの前）では <p> で包む
                self.boxed_text(_sub(parent, "p") if top else parent, node)

    def boxed_text(self, parent, node: BoxNode):
        """囲み（文字だけのテキストボックス）の <boxed-text>。中身は本文と同じ要素（<p>・<list>・<disp-quote>・<disp-formula>）。"""
        self.nodes(_sub(parent, "boxed-text"), node.children)

    def sec(self, parent, node: Sec):
        s = _sub(parent, "sec")
        if node.sid:
            s.set("id", node.sid)
        h = node.heading
        if h is None:
            _sub(s, "title")
        else:
            if h.autonum:
                lab = _sub(s, "label")
                self.em.gen(lab, self.autonum(h), "autonum", h.src)
            self.labelled(s, h, RE_HEAD_SPLIT, E.SECTITLE, title_tag="title", allow_label=not h.autonum)
        self.nodes(s, node.children)

    def labelled(self, parent, p: Para, regex, ctx, title_tag="title", allow_label=True, wrap_p=False):
        """「図1（全角空白）タイトル」型の段落を書き出す。split_labels のときは <label> と本体に分ける。"""
        text = p.plain()
        m = regex.match(text) if (self.split and allow_label) else None
        if not m or not m.group(2):
            holder = _sub(parent, title_tag)
            if wrap_p:
                holder = _sub(holder, "p")
            self.em.span(holder, p, ctx)
            return
        seq = 0
        lab = _sub(parent, "label")
        if m.group(1):
            self.em.drop(lab, p, 0, m.end(1), seq, "番号の前の空白")
            self.info.drops.append((p.src, m.group(1), "番号の前の空白"))
            seq += 1
        self.em.span(lab, p, E.LABEL, start=m.start(2), end=m.end(2), seq=seq)
        seq += 1
        sep_s, sep_e = m.start(3), m.end(3)
        holder = _sub(parent, title_tag)
        if wrap_p:
            holder = _sub(holder, "p")
        if sep_e > sep_s:
            if is_ws(text[sep_s:sep_e]):
                self.em.drop(holder, p, sep_s, sep_e, seq, "番号と本文の間の空白")
                self.info.drops.append((p.src, text[sep_s:sep_e], "番号と本文の間の空白"))
                seq += 1
            else:
                sep_e = sep_s   # 空白以外（「：」など）は本体側に残す
        self.em.span(holder, p, ctx, start=sep_e, seq=seq)

    def paragraph_or_formula(self, parent, p: Para, ctx):
        """段落 p を <p> に書く。自動番号のある段落の番号は、生成した文字（jx:gen。docx の文字ではない）として <p> の先頭に補う。

        自動番号のある段落が <p> になるのは、箇条（ListNode）にしない段落だけ: 後付け（付記・謝辞・資料）の中の見出しの役割の段落
        （structure.add_back_para）と、英文要旨の段落など。<p> に <label> は置けないので、番号は注と同じく生成した文字で補う。
        """
        pe = _sub(parent, "p")
        self.autonum_mark(pe, p)
        self.em.span(pe, p, ctx)

    def list_node(self, parent, node: ListNode, ctx=E.BODY):
        """箇条書き。各項目の段落の文脈 ctx は、置く場所の段落と同じにする（本文は E.BODY。付記・謝辞・資料は、その節の
        番号のない段落と同じ文脈。URL を <uri> にするか <ext-link> にするかなどが、番号のある段落と同じになる）。"""
        lst = _sub(parent, "list", list_type="order" if node.ordered else "bullet")
        for p in node.items:
            li = _sub(lst, "list-item")
            if p.autonum:
                lab = _sub(li, "label")
                self.em.gen(lab, self.autonum(p), "autonum", p.src)
            pe = _sub(li, "p")
            self.em.span(pe, p, ctx)

    def fig(self, parent, node: FigNode):
        f = _sub(parent, "fig")
        if node.fid:
            f.set("id", node.fid)
        if node.caption is not None:
            self.caption(f, node.caption)
            self.caption_more(f, node.caption_more)
        self.image_para_blanks(node, node.fid or "図")
        if node.slot is not None:
            self.graphic(f, node.slot)      # 図 1 つに <graphic> 1 つ（置き場所の名前。docx の画像が何枚でも、画像がなくても）
        for t in node.tables:
            # 表で組んだ図（問題文など）: 図の中に表を入れる（JATS の fig は table-wrap を含められる）
            self.table(_sub(f, "table-wrap"), t, node.caption)

    def image_para_blanks(self, node, what: str):
        """図・画像で貼った表に含めた、画像だけの段落（node.image_paras）の空白を、空白の除外として記録する。"""
        for ip in node.image_paras:
            text = _para_text(ip)
            if text and is_ws(text):
                self.info.exclusions.append(Exclusion(ip.src, "図の画像だけの段落にある空白", text, blank=True))
            elif text:
                # 図の画像の段落は画像だけの段落に限る（structure）。万一ほかの文字があっても除外にはしない
                # （不変性チェックで出力漏れとして不合格になる）
                self.info.warnings.append(f"{what}: 画像の段落 {ip.src} に画像以外の文字がある。"
                                          "XML に出力していない（変換ツールの不具合）")

    def graphic(self, parent, slot):
        """画像の置き場所 slot の <graphic>（図の <fig>・画像で貼った表の <table-wrap> の中）。"""
        name = self.slot_name(slot)
        _sub(parent, "graphic").set(f"{{{XLINK}}}href", name)
        first = slot.covers[0] if slot.covers else None
        if first is not None and first.shape_only:
            self.info.warnings.append(
                f"{first.image_id}: Word の図形（画像ファイルなし）のため画像化できない。{name} を手作業で用意すること")

    def caption(self, holder, cap):
        """図・表のキャプション。自動番号があれば、章見出しと同じく番号を <label> に出し、キャプションの文字は分けない
        （split_labels にかかわらず）。なければ今までどおり（split_labels のとき「図1」を <label> に分ける）。"""
        if cap.autonum and self.autonum(cap).strip():
            self.em.gen(_sub(holder, "label"), self.autonum(cap), "autonum", cap.src)
            self.labelled(holder, cap, RE_LABEL_SPLIT, E.CAPTION, title_tag="caption", allow_label=False, wrap_p=True)
            return
        m = RE_LABEL_SPLIT.match(cap.plain()) if self.split else None
        if m and m.group(2):
            self.labelled(holder, cap, RE_LABEL_SPLIT, E.CAPTION, title_tag="caption", wrap_p=True)
        else:
            pe = _sub(_sub(holder, "caption"), "p")
            self.em.span(pe, cap, E.CAPTION)

    def caption_more(self, holder, paras):
        if not paras:
            return
        cap = holder.find("caption")
        if cap is None:
            cap = _sub(holder, "caption")
        for p in paras:
            pe = _sub(cap, "p")
            self.autonum_mark(pe, p)
            self.em.span(pe, p, E.CAPTION)

    def table_wrap(self, parent, node: TableNode):
        tw = _sub(parent, "table-wrap")
        if node.tid:
            tw.set("id", node.tid)
        if node.caption is not None:
            self.caption(tw, node.caption)
            self.caption_more(tw, node.caption_more)
        self.image_para_blanks(node, node.tid or "表")
        if node.slot is not None:
            self.graphic(tw, node.slot)         # 画像で貼った表: <caption> の後ろに <graphic> 1 つ
        if node.table is not None:
            if node.table.skipped_rows and not node.table.rows:
                self.all_rows_deleted(node)
            self.table(tw, node.table, node.caption)

    def all_rows_deleted(self, node: TableNode):
        """変更履歴ですべての行が削除された表を、10 章の警告にする（キャプションは docx の文字なので出力し、表は今までどおり
        空の表〈空の td を 1 つ〉にする）。"""
        cap = node.caption.text_only().strip() if node.caption is not None else ""
        name = f"表 {node.tid}" if node.tid else "表"
        where = f"{name}（キャプション「{cap[:20]}{'…' if len(cap) > 20 else ''}」）" if cap else f"{name}（キャプションなし）"
        self.info.warnings.append(ALL_ROWS_DELETED_MSG.format(
            where=where, what="キャプションと空の表" if cap else "空の表",
            how="変更をすべて承諾し、キャプションも消して" if cap else "変更をすべて承諾して"))

    def table(self, parent, t, caption=None):
        """表を <table> にする。縦の結合（vMerge）は rowspan にする（中間表現は書き換えない）。

        結合元は「開始列 -> (セル, 幅)」で覚え、行ごとに作り直す（その行に合う継続か restart があった列だけ結合が続く。
        横に広いセル・飛ばしたグリッド・セルのない列で切れる）。継続は、開始列と幅が結合元と同じときだけ結合し、幅が違えば
        別のセル（新しい結合元）にする（10 章の警告）。HTML の表では rowspan を行グループ（thead/tbody）の外に延ばせないので、
        本文の 1 行目で結合を止める（10 章の警告）。結合元のない継続（表・本文の 1 行目、削除された結合元の下）は新しい結合元に
        する。すべてのセルが結合した継続の行は出力せず（セルの文字は結合元のセルに続けて出す）、rowspan は出力する行だけで数える。
        行の前後で飛ばしたグリッド（gridBefore・gridAfter）は空のセルで埋める。
        """
        rows = t.rows
        n_head = 0
        for row in rows:
            if row.header:
                n_head += 1
            else:
                break
        if n_head == len(rows):
            n_head = 0      # すべての行が見出し行なら <thead> は作らない（DTD は thead? の後に tbody+ が必要）
        top_of, conts, extra = {}, {}, {}   # id(継続) -> 結合元、id(結合元) -> 継続の行の番号、id(結合元) -> 継続の blocks
        owner = {}                          # 開始列 -> (結合元のセル, 幅)
        crossed, mismatch = False, []
        for r, row in enumerate(rows):
            col = row.grid_before
            if n_head and r == n_head:
                # 本文の 1 行目: 見出し行の結合の範囲に重なる継続があれば、止めたことを警告する（幅は比べない）
                c0 = col
                for c in row.cells:
                    if c.vmerge == "continue" and _overlaps(owner, c0, c.gridspan):
                        crossed = True
                    c0 += c.gridspan
                owner = {}
            new = {}
            for c in row.cells:
                span = c.gridspan
                if c.vmerge == "continue":
                    o = owner.get(col)
                    if o is not None and o[1] == span:
                        top = o[0]
                        top_of[id(c)] = top
                        conts.setdefault(id(top), []).append(r)
                        # 結合された側のセルに文字があれば、結合元のセルに続けて出す（文字を落とさないため）
                        extra.setdefault(id(top), []).extend(c.blocks)
                        new[col] = o
                    else:
                        if _overlaps(owner, col, span):
                            mismatch.append(row.number or r + 1)
                        new[col] = (c, span)
                elif c.vmerge == "restart":
                    new[col] = (c, span)
                col += span
            owner = new
        # 出力しない行: すべてのセルが結合した継続の行（セルのない行も。今と同じ）
        dropped = {r for r, row in enumerate(rows) if all(id(c) in top_of for c in row.cells)}
        rowspan = {k: 1 + sum(1 for r in rs if r not in dropped) for k, rs in conts.items()}
        where = table_where(table_head(t), caption.text_only() if caption is not None else "")
        if crossed:
            self.info.warnings.append(TABLE_HEAD_SPAN_MSG.format(where=where))
        for k in dict.fromkeys(mismatch):
            self.info.warnings.append(TABLE_SPAN_MISMATCH_MSG.format(where=where, row=k))
        tbl = _sub(parent, "table")
        for tag, lo, hi in (("thead", 0, n_head), ("tbody", n_head, len(rows))):
            if lo >= hi:
                continue
            sec = _sub(tbl, tag)
            cell_tag = "th" if tag == "thead" else "td"
            for r in range(lo, hi):
                if r in dropped:
                    continue
                row = rows[r]
                tr = _sub(sec, "tr")
                self._grid_cell(tr, cell_tag, row.grid_before)
                for c in row.cells:
                    if id(c) in top_of:
                        continue
                    td = _sub(tr, cell_tag)
                    if c.gridspan > 1:
                        td.set("colspan", str(c.gridspan))
                    if rowspan.get(id(c), 1) > 1:
                        td.set("rowspan", str(rowspan[id(c)]))
                    self.cell_content(td, c.blocks + extra.get(id(c), []))
                self._grid_cell(tr, cell_tag, row.grid_after)
            if not len(sec):
                tbl.remove(sec)
        if not len(tbl):
            tr = _sub(_sub(tbl, "tbody"), "tr")
            _sub(tr, "td")
        self.info.tables.append((tbl, t, where))

    @staticmethod
    def _grid_cell(tr, tag, n):
        """飛ばしたグリッド n 列ぶんの空のセル（n が 0 なら何もしない。2 以上なら colspan）。文字がないので不変性チェックに関係しない。"""
        if n > 0:
            el = _sub(tr, tag)
            if n > 1:
                el.set("colspan", str(n))

    def cell_content(self, td, blocks):
        paras = []
        for b in blocks:
            if isinstance(b, Para):
                paras.append(b)
            else:
                paras.extend(b.paragraphs())
                self.info.warnings.append("表の中の表（入れ子）は、内側の表の文字を順に並べて出力した")
        first = True
        aligns = set()
        for p in paras:
            if p.is_blank and not p.plain():
                continue
            if not first:
                _sub(td, "break")
            slot = self.cell_empty.get(p.src)
            if slot is not None:
                # docx に画像の見つからない表のセルの図: キャプションの段落の先頭に置き場所を書く
                _sub(td, "inline-graphic").set(f"{{{XLINK}}}href", self.slot_name(slot))
            self.autonum_mark(td, p)
            self.em.span(td, p, E.CELL)
            first = False
            if p.align:
                aligns.add(p.align)
        if len(aligns) == 1:
            a = aligns.pop()
            a = {"center": "center", "left": "left", "start": "left", "right": "right", "end": "right"}.get(a)
            if a:
                td.set("align", a)

    def formula(self, parent, node: FormulaNode):
        df = _sub(parent, "disp-formula")
        if node.fid:
            df.set("id", node.fid)
        p = node.para
        self.autonum_mark(df, p)
        self.em.span(df, p, E.DISPF)

    # ------------------------------------------------------------------ 後付け
    def back(self, back):
        plan = self.plan
        if plan.ack is not None:
            ack = _sub(back, "ack")
            self.backsec(ack, plan.ack, E.BODY)
        if plan.refs or plan.ref_heading is not None:
            rl = _sub(back, "ref-list")
            if plan.ref_heading is not None:
                self.heading_title(rl, plan.ref_heading)
            for r in plan.refs:
                self.ref(rl, r)
        if plan.apps:
            ag = _sub(back, "app-group")
            for app in plan.apps:
                ap = _sub(ag, "app")
                if app.title is not None:
                    self.heading_title(ap, app.title)
                else:
                    _sub(ap, "title")
                self.app_children(ap, app.children)
        if plan.fns:
            fg = _sub(back, "fn-group")
            if plan.fn_heading is not None:
                self.heading_title(fg, plan.fn_heading)
            else:
                # docx に注の見出しがない（Word の脚注機能で書かれた注など）。設定の見出しを生成した文字として補う
                title = self.j.fn_title_en if self.article_lang() == "en" else self.j.fn_title
                if title:
                    self.em.gen(_sub(fg, "title"), title, "fn-title")
            for fn in plan.fns:
                self.fn(fg, fn)
        elif plan.fn_heading is not None:
            self.info.exclusions.append(Exclusion(plan.fn_heading.src, "注の見出しはあるが注の本文がない（JATS では見出しだけ置けない）",
                                                  _para_text(plan.fn_heading)))
        if plan.notes is not None:
            nt = _sub(back, "notes")
            self.backsec(nt, plan.notes, E.BACKP)

    def backsec(self, el, sec: BackSec, ctx):
        if sec.heading is not None:
            self.heading_title(el, sec.heading)
        # <ack> の内容は <p> と <sec> だけ（別行数式・表・リストは <p> で包む）。<notes> は本文と同じ要素を直接置ける
        wrap = el.tag == "ack"
        for node in sec.children:
            if isinstance(node, PNode):
                self.paragraph_or_formula(el, node.para, ctx)
            elif isinstance(node, (FormulaNode, TableNode, ListNode)):
                holder = _sub(el, "p") if wrap else el
                if isinstance(node, FormulaNode):
                    self.formula(holder, node)
                elif isinstance(node, TableNode):
                    self.table_wrap(holder, node)
                else:
                    self.list_node(holder, node, ctx)

    def app_children(self, ap, children):
        for node in children:
            if isinstance(node, PNode):
                self.paragraph_or_formula(ap, node.para, E.BACKP)
            elif isinstance(node, ListNode):
                self.list_node(ap, node, E.BACKP)
            elif isinstance(node, FormulaNode):
                self.formula(ap, node)
            elif isinstance(node, TableNode):
                self.table_wrap(ap, node)
            elif isinstance(node, FigNode):
                self.fig(ap, node)

    def ref(self, rl, r: RefNode):
        ref = _sub(rl, "ref", id=r.rid)
        # 引用文献の記述言語（J-STAGE の「引用文献（記述言語）」）。かな・漢字を含む文献は ja、それ以外は en
        _lang(ref, "ja" if RE_JA_CHARS.search(r.para.plain()) else "en")
        mc = _sub(ref, "mixed-citation")
        typ = (r.parsed or {}).get("publication_type")
        if typ:
            mc.set("publication-type", typ)
        if r.para.autonum:
            lab = etree.Element("label")
            self.em.gen(lab, self.autonum(r.para), "autonum", r.para.src)
            ref.insert(0, lab)
        self.em.span(mc, r.para, E.REF)
        self.check_length(mc, 4000, f"引用文献 {r.rid}")

    def fn(self, fg, fn: FnNode):
        """注。J-STAGE の注（fn）には label を書けない（書いても表示されない）ため、番号は本文（p）の先頭に入れる。

        - Word の自動番号・脚注番号: 生成した番号と空白を p の先頭に（jx:gen。docx の文字ではない）
        - 手で打たれた番号「1)」: docx の文字なので、そのまま p の中に残す（label に分けない）
        - 2 段落目以降の自動番号も、生成した文字として各 p の先頭に補う
        - 注の節の中の表（FnNode.tables）は <p> で包む（fn の内容は label?, p+。付記・謝辞の <p> の表と同じ）。表は k 段落目の後ろに
          置き、必ず table_wrap を通す（表の形の確かめ・キャプションとセルの自動番号が本文の表と同じに効く）
        """
        el = _sub(fg, "fn", id=fn.fid)
        mark = ""
        if fn.word_note:
            mark = self.plan.pdf_numbers.get(("fnlist", fn.word_id), self.marks[fn.word_id][1])
        elif fn.paras and fn.paras[0].autonum:
            mark = self.autonum(fn.paras[0]).strip()
        tables = list(fn.tables)
        for i, p in enumerate(fn.paras):
            while tables and tables[0][0] <= i:
                self.table_wrap(_sub(el, "p"), tables.pop(0)[1])
            pe = _sub(el, "p")
            if i == 0 and mark:
                wide = unicodedata.east_asian_width(mark[-1]) in ("F", "W")
                if fn.word_note:
                    numbered = bool(p.autonum and self.autonum(p).strip())
                    # 1 段落目に自動番号があれば、脚注番号の後ろには必ず空白を補う（「1)1. …」にしない）
                    sep = "" if wide or (_starts_with_space(p) and not numbered) else " "
                    self.em.gen(pe, mark + sep, "footnote-mark")
                    self.autonum_mark(pe, p)       # 1 段落目の自動番号（区切りは docx の文字で決める）
                else:
                    # 番号の後の空白は、docx の文字が空白で始まっていなければ補う。番号が全角の文字で終わる
                    # （出版版 PDF に合わせた「１）」など）ときは補わない
                    sep = "" if _starts_with_space(p) or wide else " "
                    self.em.gen(pe, mark + sep, "autonum", p.src)   # 自動番号を注の番号にした（2 回出さない）
            else:
                self.autonum_mark(pe, p)
            self.em.span(pe, p, E.BACKP)
        for _, node in tables:
            self.table_wrap(_sub(el, "p"), node)


def word_note_marks(plan, journal) -> dict:
    """Word の脚注機能・文末脚注機能で書かれた注の番号: 注の鍵（model.note_key。FnNode.word_id）-> (番号, 出力する文字列
    （設定 fn_mark。本誌は「1)」）)。

    番号は plan.fns の中の Word の注の順（structure.Classifier.attach_word_notes が、脚注と文末脚注をまとめて本文で最初に
    参照される順に並べる）の通し番号。本文の脚注番号と注の一覧の先頭の両方に使う。ルート2（docx から作り、出版版 PDF で補う）では、
    全角・半角と字形を PDF に合わせたもの（plan.pdf_numbers）で置き換えて出力する。
    """
    out = {}
    k = 0
    for fn in plan.fns:
        if fn.word_note:
            k += 1
            n = fn.number or k
            out[fn.word_id] = (n, journal.fn_mark.format(n=n))
    return out


def _starts_with_space(p) -> bool:
    """段落の docx の文字（脚注記号などの生成文字を除く）が空白で始まるか。"""
    for a in p.atoms:
        if a.kind == "gen" or (a.kind == "text" and not a.text):
            continue
        return a.kind == "text" and a.text[:1].isspace()
    return False


# ---------------------------------------------------------------------------- 仕上げ
def finalize(root):
    """追跡用の目印をすべて取り除いた写しを返す（文字列は変わらない）。"""
    import copy
    out = copy.deepcopy(root)
    etree.strip_elements(out, f"{{{JX_NS}}}drop", with_tail=False)
    etree.strip_tags(out, SPAN, GEN, AI)
    for el in out.iter():
        if not isinstance(el.tag, str):
            continue
        for a in (IMPLICIT, ORDER):
            if a in el.attrib:
                del el.attrib[a]
    etree.cleanup_namespaces(out, top_nsmap={"xsi": XSI, "mml": MML_NS, "xlink": XLINK, "ali": ALI},
                             keep_ns_prefixes=["xsi", "mml", "xlink", "ali"])
    return out


def serialize(root) -> bytes:
    body = etree.tostring(root, encoding="unicode")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n' + DOCTYPE + "\n" + body + "\n").encode("utf-8")


def build(plan, meta, journal, split_labels=None):
    b = Builder(plan, meta, journal, split_labels)
    root = b.build()
    return root, b.info
