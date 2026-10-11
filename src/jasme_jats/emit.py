"""段落の中身（アトム列）を JATS の要素として書き出す。

段落の文字は必ず <jx:span src=... seq=...> の中に書き出す（tracking.py 参照）。
書式（太字など）やリンクは、文字を包む要素として付け加えるだけで、文字そのものは変えない。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from lxml import etree

from .model import LinkSpec, Para
from .omml import OmmlConverter
from .tracking import GEN, JX, SPAN

XLINK = "http://www.w3.org/1999/xlink"
DROP = JX + "drop"

FMT_ORDER = ("bold", "italic", "underline", "strike", "sc", "sup", "sub")
ALL_FMT = frozenset(FMT_ORDER)
BASIC_FMT = frozenset({"bold", "italic", "sup", "sub"})


@dataclass
class Ctx:
    """書き出し先の文脈。J-STAGE の『修飾タグ処理仕様』と JATS の DTD に合わせて、使える要素を制限する。"""
    fmt: frozenset = ALL_FMT
    link: Optional[str] = "uri"       # URL の書き方: "uri" / "ext-link" / "ref"（文献内）/ None
    xref: bool = True
    math: str = "inline"              # "inline" / "display" / "none"
    images: bool = True
    label: bool = False               # LinkSpec(kind="label") を <label> にするか（別行数式）
    ref_tags: bool = False            # year / article-title / source / pub-id を使えるか（文献内）


BODY = Ctx()
SECTITLE = Ctx(link=None)
TITLE = Ctx(fmt=BASIC_FMT, link=None, xref=False, images=False)
NAME = Ctx(fmt=frozenset(), link=None, xref=False, math="none", images=False)
AFF = Ctx(fmt=frozenset({"sup", "sub"}), link=None, xref=False, math="none", images=False)
ABSTRACT = Ctx(link="uri")
REF = Ctx(fmt=BASIC_FMT, link="ref", xref=False, images=False, ref_tags=True)
BACKP = Ctx(link="ext-link")
CELL = Ctx()
CAPTION = Ctx()
DISPF = Ctx(link=None, xref=False, math="display", label=True)
LABEL = Ctx(link=None, xref=False, math="none", images=False)


def xl(name):
    return f"{{{XLINK}}}{name}"


class Emitter:
    def __init__(self, image_namer, fn_numbers=None, skip_images=()):
        self.image_namer = image_namer          # ImageRef -> ファイル名
        self.fn_numbers = fn_numbers or {}      # Word 脚注 id -> (fid, 表示番号)
        self.skip_images = set(skip_images)     # 図に移したため段落の中では出力しない画像の ID
        self.math_warnings = []

    # ------------------------------------------------------------------ 範囲の切り出し
    @staticmethod
    def slice_atoms(para: Para, start: int, end: int):
        """para.plain() 上の [start, end) にあたるアトム（文字は必要に応じて切った写し）を返す。"""
        out = []
        pos = 0
        for a in para.atoms:
            n = len(a.text) if a.kind == "text" else 1
            a0, a1 = pos, pos + n
            pos = a1
            if a1 <= start or a0 >= end:
                if not (n == 0 and start <= a0 < end):
                    continue
            if a.kind == "text":
                s, e = max(start, a0) - a0, min(end, a1) - a0
                if s == 0 and e == n:
                    out.append(a)
                elif e > s:
                    b = _copy_atom(a)
                    b.text = a.text[s:e]
                    out.append(b)
            else:
                out.append(a)
        return out

    # ------------------------------------------------------------------ 公開関数
    def span(self, parent, para: Para, ctx: Ctx, start: int = 0, end: Optional[int] = None, seq: int = 0,
             skip_gen: bool = True):
        if end is None:
            end = len(para.plain())
        sp = etree.SubElement(parent, SPAN)
        sp.set("src", para.src)
        sp.set("seq", str(seq))
        atoms = self.slice_atoms(para, start, end)
        if skip_gen:
            atoms = [a for a in atoms if a.kind != "gen"]
        self.write_atoms(sp, atoms, ctx)
        return sp

    def drop(self, parent, para: Para, start: int, end: int, seq: int, reason: str):
        """docx の文字のうち、構造の区切りとして出力しない空白（検証用に記録してから取り除く）。"""
        el = etree.SubElement(parent, DROP)
        el.set("src", para.src)
        el.set("seq", str(seq))
        el.set("reason", reason)
        el.text = "".join(a.text for a in self.slice_atoms(para, start, end) if a.kind == "text")
        return el

    @staticmethod
    def gen(parent, text, kind):
        el = etree.SubElement(parent, GEN)
        el.set("kind", kind)
        el.text = text
        return el

    # ------------------------------------------------------------------ 中身
    def write_atoms(self, parent, atoms, ctx: Ctx):
        groups = []
        for a in atoms:
            key = a.link if a.link is not None else (("href", a.href) if a.href and ctx.link else None)
            if groups and _same_key(groups[-1][0], key):
                groups[-1][1].append(a)
            else:
                groups.append((key, [a]))
        for key, items in groups:
            target, pcdata = self.link_element(parent, key, ctx, items)
            if pcdata:
                # PCDATA のみの要素（uri, pub-id, year）: 書式を付けずに文字だけ入れる
                txt = "".join(a.text for a in items if a.kind == "text")
                _append_text(target, txt)
                for a in items:
                    if a.kind != "text":
                        self.write_object(parent, a, ctx)
                continue
            self.write_inline(target, items, ctx)

    def link_element(self, parent, key, ctx: Ctx, items):
        """リンク要素を作る。戻り値: (中身を入れる要素, PCDATA のみか)"""
        if key is None:
            return parent, False
        if isinstance(key, tuple):   # docx のハイパーリンク
            spec = LinkSpec(kind="uri", attrs={"href": key[1]}, origin="word")
        else:
            spec = key
        only_text = all(a.kind == "text" for a in items)
        k = spec.kind
        if k == "xref":
            if not ctx.xref:
                return parent, False
            el = etree.SubElement(parent, "xref")
            el.set("ref-type", spec.attrs["ref-type"])
            el.set("rid", spec.attrs["rid"])
            return el, False
        if k in ("uri", "ext-link", "pub-id"):
            href = spec.attrs.get("href", "")
            mode = ctx.link
            if mode is None:
                return parent, False
            if k == "pub-id" and ctx.ref_tags and only_text:
                # J-STAGE の引用文献では DOI を pub-id で書く（mixed-citation の子に ext-link は使えない）。
                # リンク先も xlink:href に入れておく（DTD 上 pub-id に付けられる）
                el = etree.SubElement(parent, "pub-id")
                el.set("pub-id-type", spec.attrs.get("pub-id-type", "doi"))
                if href:
                    el.set(xl("href"), href)
                return el, True
            if mode in ("uri", "ref") and only_text:
                el = etree.SubElement(parent, "uri")
                if href:
                    el.set(xl("href"), href)
                return el, True
            if mode == "ext-link":
                el = etree.SubElement(parent, "ext-link")
                el.set("ext-link-type", "uri")
                if href:
                    el.set(xl("href"), href)
                return el, False
            return parent, False
        if k in ("year", "article-title", "source") and ctx.ref_tags:
            el = etree.SubElement(parent, k)
            return el, k == "year"
        if k == "label" and ctx.label and only_text:
            el = etree.SubElement(parent, "label")
            return el, False
        return parent, False

    def write_inline(self, parent, items, ctx: Ctx):
        run = []   # 同じ書式が続く文字をまとめる

        def flush():
            if not run:
                return
            fmt = run[0].fmt & ctx.fmt
            target = parent
            for f in FMT_ORDER:
                if f in fmt:
                    target = etree.SubElement(target, f)
            _append_text(target, "".join(a.text for a in run))
            run.clear()

        for a in items:
            if a.kind == "text":
                if run and (run[0].fmt & ctx.fmt) != (a.fmt & ctx.fmt):
                    flush()
                run.append(a)
            else:
                flush()
                self.write_object(parent, a, ctx)
        flush()

    def write_object(self, parent, a, ctx: Ctx):
        if a.kind == "math":
            conv = OmmlConverter()
            if ctx.math == "display" and a.display:
                mml = conv.convert(a.math, display=True)
                parent.append(mml)
            elif ctx.math == "none":
                # 数式を置けない場所（著者名など）。文字だけを出す
                mml = conv.convert(a.math, display=False)
                from .omml import math_plain
                _append_text(parent, math_plain(mml))
            elif a.display:
                df = etree.SubElement(parent, "disp-formula")
                df.append(conv.convert(a.math, display=True))
            else:
                inf = etree.SubElement(parent, "inline-formula")
                inf.append(conv.convert(a.math, display=False))
            self.math_warnings.extend(conv.warnings)
        elif a.kind == "image":
            if ctx.images and a.image.image_id not in self.skip_images:
                g = etree.SubElement(parent, "inline-graphic")
                g.set(xl("href"), self.image_namer(a.image))
        elif a.kind == "fnref":
            fid, number = self.fn_numbers.get(a.fn_id, (None, None))
            if fid and ctx.xref:
                x = etree.SubElement(parent, "xref")
                x.set("ref-type", "fn")
                x.set("rid", fid)
                if not a.fn_kind.endswith("-custom"):
                    sup = etree.SubElement(x, "sup")
                    self.gen(sup, str(number), "footnote-mark")
            elif not a.fn_kind.endswith("-custom") and number is not None:
                sup = etree.SubElement(parent, "sup")
                self.gen(sup, str(number), "footnote-mark")


def _same_key(k1, k2) -> bool:
    if isinstance(k1, tuple) or isinstance(k2, tuple):
        return k1 == k2
    return k1 is k2


def _copy_atom(a):
    from copy import copy
    b = copy(a)
    return b


def _append_text(el, text):
    if not text:
        return
    if len(el):
        last = el[-1]
        last.tail = (last.tail or "") + text
    else:
        el.text = (el.text or "") + text
