"""ArticlePlan から J-STAGE 全文 XML（JATS 1.1 Journal Publishing, FULL-J）の要素木を作る。

ここで作る木には追跡用の目印（tracking.py）が入っている。文字の不変性チェックの後、
finalize() で目印を取り除いてから出力する。
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field

from lxml import etree

from . import emit as E
from .config import ArticleMeta, JournalConfig, keyword_problem
from .model import Exclusion, Para
from .ooxml import is_ws
from .structure import (ArticlePlan, BackSec, FigNode, FnNode, FormulaNode, ListNode, PNode, QuoteNode,
                        RefNode, Sec, TableNode, _para_text)
from .tracking import AI, GEN, IMPLICIT, JX_NS, ORDER, SPAN

MML_NS = "http://www.w3.org/1998/Math/MathML"
XLINK = "http://www.w3.org/1999/xlink"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
ALI = "http://www.niso.org/schemas/ali/1.0/"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
DOCTYPE = ('<!DOCTYPE article PUBLIC "-//NLM//DTD JATS (Z39.96) Journal Publishing DTD v1.1 20151215//EN" '
           '"https://www.jstage.jst.go.jp/dtds/1.1/JATS-journalpublishing1.dtd">')

RE_JA_CHARS = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff々]")
RE_LABEL_SPLIT = re.compile(r"^([\s\u3000]*)((?:図|表|Figure|Fig\.?|Table)[\s\u3000]*[0-9０-９]+(?:[.．\-－][0-9０-９]+)?)"
                            r"([\s\u3000:：.．]*)")
RE_HEAD_SPLIT = re.compile(r"^([\s\u3000]*)([0-9０-９]{1,2}[．.]|[(（][0-9０-９]{1,2}[)）]|[①-⑳])([\s\u3000]*)(?=\S)")


@dataclass
class BuildInfo:
    images: list = field(default_factory=list)       # 出力した ImageRef（出現順）
    warnings: list = field(default_factory=list)
    drops: list = field(default_factory=list)        # (src, text, reason)
    exclusions: list = field(default_factory=list)   # Exclusion（書き出しの段階で出力しないと決めたもの）
    notes: list = field(default_factory=list)        # (category, src, message) 機械的な判断の記録


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
        self._img_n = 0
        fn_numbers = {}
        k = 0
        for fn in plan.fns:
            if fn.word_note:
                k += 1
                fn_numbers[fn.word_id] = (fn.fid, k)
                fn.number = fn.number or k
        self.em = E.Emitter(self.name_image, fn_numbers)

    # ------------------------------------------------------------------ 画像
    def name_image(self, img) -> str:
        if not img.export_name:
            self._img_n += 1
            ext = (img.target.rsplit(".", 1)[-1].lower() if "." in img.target else "png")
            ext = {"jpeg": "jpg", "jpg": "jpg", "png": "png", "gif": "gif"}.get(ext, "png")
            base = self.j.image_name_pattern.format(article_id=self.article_id, n=self._img_n)
            img.export_name = f"{base}.{ext}"
            self.info.images.append(img)
        return img.export_name

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
        return root

    def em_warnings(self):
        for w in sorted(set(self.em.math_warnings)):
            self.info.warnings.append(f"数式: {w}")

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
                t = _sub(ab, "title")
                self.em.span(t, plan.abstract_heading, E.SECTITLE)
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
        self.multi(at, main, E.TITLE)
        if not main:
            self.info.warnings.append("題目（スタイル「題目（日）」）が見つからない")
        self.check_length(at, 2000, "題目")
        if main_sub:
            st = _lang(_sub(tg, "subtitle"), lang)
            self.multi(st, main_sub, E.TITLE)
        if other:
            ttg = _lang(_sub(tg, "trans-title-group"), other_lang)
            tt = _sub(ttg, "trans-title")
            self.multi(tt, other, E.TITLE)
            self.check_length(tt, 2000, "翻訳題目")
            if other_sub:
                ts = _sub(ttg, "trans-subtitle")
                self.multi(ts, other_sub, E.TITLE)
        elif other_sub:
            self.info.warnings.append("副題（翻訳）があるが題目（翻訳）がない（J-STAGE ではエラーになる）")

    def check_length(self, el, limit, what):
        n = len("".join(el.itertext()))
        if n > limit:
            self.info.warnings.append(f"{what}が {n} 文字あり、J-STAGE の上限（{limit} 文字）を超えている")

    def multi(self, parent, paras, ctx):
        for p in paras:
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
                    self.em.span(inst, p, E.AFF)
            else:
                p = aff.ja if aff.ja is not None else aff.en
                af = _lang(_sub(cg, "aff", id=aff.aid), "ja" if aff.ja is not None else "en")
                inst = _sub(af, "institution")
                self.em.span(inst, p, E.AFF)

    def person_name(self, parent, p: Para, style, lang, split):
        """氏名を姓と名に分ける。分ける位置の空白だけを落とす（検証のため記録する）。"""
        nm = _lang(_sub(parent, "name", name_style=style), lang)
        text = p.plain()
        n = len(text)
        lead = len(text) - len(text.lstrip(" \u3000\t"))
        trail = n - len(text.rstrip(" \u3000\t"))
        core_s, core_e = lead, n - trail
        pieces = None   # [(kind, s, e)]
        if split is not None and core_s < split < core_e:
            pieces = [("surname", 0, split), ("given", split, n)] if style == "eastern" else None
            if style == "western":
                pieces = [("given", 0, split), ("surname", split, n)]
        else:
            core = text[core_s:core_e]
            ws = [m for m in re.finditer(r"[ \u3000\t]+", core)]
            if style == "eastern" and len(ws) >= 1:
                m = ws[0]
                pieces = [("surname", 0, core_s + m.start()), ("drop", core_s + m.start(), core_s + m.end()),
                          ("given", core_s + m.end(), n)]
            elif style == "western" and len(ws) >= 1:
                toks = [(t.start() + core_s, t.end() + core_s) for t in re.finditer(r"[^ \u3000\t]+", core)]
                caps = [k for k, (s, e) in enumerate(toks) if re.fullmatch(r"[A-ZÀ-Ý][A-ZÀ-Ý'’\-]+", text[s:e])]
                if len(caps) == 1 and caps[0] in (0, len(toks) - 1):
                    k = caps[0]
                else:
                    k = len(toks) - 1
                if k == len(toks) - 1:
                    s_sur = toks[k][0]
                    gap_s = toks[k - 1][1]
                    pieces = [("given", 0, gap_s), ("drop", gap_s, s_sur), ("surname", s_sur, n)]
                else:  # 姓が先頭（SUGAKU Taro）
                    e_sur = toks[0][1]
                    g_s = toks[1][0]
                    pieces = [("surname", 0, e_sur), ("drop", e_sur, g_s), ("given", g_s, n)]
        if pieces is None:
            sn = _sub(nm, "surname")
            self.em.span(sn, p, E.NAME)
            self.info.notes.append(("name", p.src,
                                    f"氏名「{text.strip()}」に姓と名の区切り（空白）がないため、全体を姓（surname）として出力"))
            return
        order = {"surname": 0, "given": 1}
        holders = {}
        for kind in sorted({k for k, _, _ in pieces if k != "drop"}, key=order.get):
            holders[kind] = _sub(nm, "surname" if kind == "surname" else "given-names")
        for seq, (kind, s, e) in enumerate(pieces):
            if kind == "drop":
                self.em.drop(holders.get("surname", nm), p, s, e, seq, "姓と名の間の空白")
                self.info.drops.append((p.src, text[s:e], "姓と名の間の空白"))
            else:
                self.em.span(holders[kind], p, E.NAME, start=s, end=e, seq=seq)

    # ------------------------------------------------------------------ 本文
    def nodes(self, parent, nodes, top=False):
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
                    self.em.span(pe, p, E.BODY)
            elif isinstance(node, FigNode):
                self.fig(parent, node)
            elif isinstance(node, TableNode):
                self.table_wrap(parent, node)
            elif isinstance(node, FormulaNode):
                self.formula(parent, node)

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
                self.em.gen(lab, h.autonum, "autonum")
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
        pe = _sub(parent, "p")
        self.em.span(pe, p, ctx)

    def list_node(self, parent, node: ListNode):
        lst = _sub(parent, "list", list_type="order" if node.ordered else "bullet")
        for p in node.items:
            li = _sub(lst, "list-item")
            if p.autonum:
                lab = _sub(li, "label")
                self.em.gen(lab, p.autonum, "autonum")
            pe = _sub(li, "p")
            self.em.span(pe, p, E.BODY)

    def fig(self, parent, node: FigNode):
        f = _sub(parent, "fig")
        if node.fid:
            f.set("id", node.fid)
        if node.caption is not None:
            cap_parent = f
            m = RE_LABEL_SPLIT.match(node.caption.plain()) if self.split else None
            if m and m.group(2):
                self.labelled(f, node.caption, RE_LABEL_SPLIT, E.CAPTION, title_tag="caption", wrap_p=True)
            else:
                cap = _sub(cap_parent, "caption")
                pe = _sub(cap, "p")
                self.em.span(pe, node.caption, E.CAPTION)
            self.caption_more(f, node.caption_more)
        graphics = 0
        for ip in node.image_paras:
            ws = [a for a in ip.atoms if a.kind == "text" and a.text]
            if ws:
                self.info.exclusions.append(Exclusion(ip.src, "図の画像だけの段落にある空白", _para_text(ip)))
            for img in ip.images:
                if node.formula is not None:
                    continue
                g = _sub(f, "graphic")
                g.set(f"{{{XLINK}}}href", self.name_image(img))
                graphics += 1
                if img.shape_only:
                    self.info.warnings.append(
                        f"{img.image_id}: Word の図形（画像ファイルなし）のため画像化できない。"
                        f"{img.export_name} を手作業で用意すること")
        if node.formula is not None:
            parent.remove(f)
            self.formula_image(parent, node)
            return
        if graphics == 0 and node.caption is not None:
            self.info.warnings.append(f"{node.fid or '図'}: 画像が見つからないため <graphic> なしで出力")

    def caption_more(self, holder, paras):
        if not paras:
            return
        cap = holder.find("caption")
        if cap is None:
            cap = _sub(holder, "caption")
        for p in paras:
            pe = _sub(cap, "p")
            self.em.span(pe, p, E.CAPTION)

    def formula_image(self, parent, node: FigNode):
        """AI が数式画像と判断した図: 元の画像を残したまま、AI が読み取った MathML を併記する。"""
        df = _sub(parent, "disp-formula")
        alt = _sub(df, "alternatives")
        for ip in node.image_paras:
            for img in ip.images:
                g = _sub(alt, "graphic")
                g.set(f"{{{XLINK}}}href", self.name_image(img))
        holder = etree.SubElement(alt, AI)
        holder.set("decision", getattr(node, "formula_decision", "") or "")
        holder.append(copy.deepcopy(node.formula))

    def table_wrap(self, parent, node: TableNode):
        tw = _sub(parent, "table-wrap")
        if node.tid:
            tw.set("id", node.tid)
        if node.caption is not None:
            m = RE_LABEL_SPLIT.match(node.caption.plain()) if self.split else None
            if m and m.group(2):
                self.labelled(tw, node.caption, RE_LABEL_SPLIT, E.CAPTION, title_tag="caption", wrap_p=True)
            else:
                cap = _sub(tw, "caption")
                pe = _sub(cap, "p")
                self.em.span(pe, node.caption, E.CAPTION)
            self.caption_more(tw, node.caption_more)
        if node.table is not None:
            self.table(tw, node.table)

    def table(self, parent, t):
        # 縦の結合（vMerge）を rowspan に変換する（中間表現は書き換えない）
        rowspan, merged, extra = {}, set(), {}
        owner = {}
        for row in t.rows:
            col = 0
            for c in row.cells:
                if c.vmerge == "continue" and col in owner:
                    top = owner[col]
                    rowspan[id(top)] = rowspan.get(id(top), 1) + 1
                    # 結合された側のセルに文字があれば、結合元のセルに続けて出す（文字を落とさないため）
                    extra.setdefault(id(top), []).extend(c.blocks)
                    merged.add(id(c))
                elif c.vmerge == "restart":
                    owner[col] = c
                else:
                    owner.pop(col, None)
                col += c.gridspan
        tbl = _sub(parent, "table")
        n_head = 0
        for row in t.rows:
            if row.header:
                n_head += 1
            else:
                break
        sections = []
        if n_head:
            sections.append(("thead", t.rows[:n_head]))
        sections.append(("tbody", t.rows[n_head:] or []))
        for tag, rows in sections:
            if not rows:
                continue
            sec = _sub(tbl, tag)
            for row in rows:
                tr = _sub(sec, "tr")
                for c in row.cells:
                    if id(c) in merged:
                        continue
                    td = _sub(tr, "th" if tag == "thead" else "td")
                    if c.gridspan > 1:
                        td.set("colspan", str(c.gridspan))
                    if rowspan.get(id(c), 1) > 1:
                        td.set("rowspan", str(rowspan[id(c)]))
                    self.cell_content(td, c.blocks + extra.get(id(c), []))
                if not len(tr):
                    sec.remove(tr)
            if not len(sec):
                tbl.remove(sec)
        if not len(tbl):
            tr = _sub(_sub(tbl, "tbody"), "tr")
            _sub(tr, "td")

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
                t = _sub(rl, "title")
                self.em.span(t, plan.ref_heading, E.SECTITLE)
            for r in plan.refs:
                self.ref(rl, r)
        if plan.apps:
            ag = _sub(back, "app-group")
            for app in plan.apps:
                ap = _sub(ag, "app")
                t = _sub(ap, "title")
                if app.title is not None:
                    self.em.span(t, app.title, E.SECTITLE)
                self.app_children(ap, app.children)
        if plan.fns:
            fg = _sub(back, "fn-group")
            if plan.fn_heading is not None:
                t = _sub(fg, "title")
                self.em.span(t, plan.fn_heading, E.SECTITLE)
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
            t = _sub(el, "title")
            self.em.span(t, sec.heading, E.SECTITLE)
        for node in sec.children:
            if isinstance(node, PNode):
                self.paragraph_or_formula(el, node.para, ctx)
            elif isinstance(node, FormulaNode):
                self.formula(el, node)
            elif isinstance(node, TableNode):
                self.table_wrap(el, node)

    def app_children(self, ap, children):
        for node in children:
            if isinstance(node, PNode):
                self.paragraph_or_formula(ap, node.para, E.BACKP)
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
            self.em.gen(lab, r.para.autonum, "autonum")
            ref.insert(0, lab)
        self.em.span(mc, r.para, E.REF)
        self.check_length(mc, 4000, f"引用文献 {r.rid}")

    def fn(self, fg, fn: FnNode):
        """注。J-STAGE の注（fn）には label を書けない（書いても表示されない）ため、番号は本文（p）の先頭に入れる。

        - Word の自動番号・脚注番号: 生成した番号と空白を p の先頭に（jx:gen。docx の文字ではない）
        - 手で打たれた番号「1)」: docx の文字なので、そのまま p の中に残す（label に分けない）
        """
        el = _sub(fg, "fn", id=fn.fid)
        mark = ""
        if fn.word_note:
            mark = f"{fn.number})"
        elif fn.paras and fn.paras[0].autonum:
            mark = fn.paras[0].autonum.strip()
        for i, p in enumerate(fn.paras):
            pe = _sub(el, "p")
            if i == 0 and mark:
                sep = "" if p.plain()[:1].isspace() else " "
                self.em.gen(pe, mark + sep, "footnote-mark" if fn.word_note else "autonum")
            self.em.span(pe, p, E.BACKP)


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
