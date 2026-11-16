"""変換レポート（Markdown）。

冒頭に、J-STAGE に登載する前にすることの一覧（旧 14 章）と結果の要約、続いて AI による仕上げ（不確実性のある箇所）、機械処理で解決できなかった箇所、
機械的な推定、出力しなかった文字の全件、落とした空白の全件、生成文字、画像、書誌情報、DTD 検証と J-STAGE の登載時チェック、
出版版 PDF との照合の順に並べる。

利用者に知らせること（要対応・要確認・手順）は actions() の 1 か所で決める。レポートの冒頭（することの一覧と囲み）、Colab の枠（要対応は赤、要確認は黄、手順は青）
（colab.result_boxes）、コマンドラインの標準エラーと終了コード（pipeline.Result.needs_action）は、どれもその結果を使う。
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .ai_assist import PROVIDERS
from .config import DATE_FIELDS, PAGE_FIELDS
from . import frontcheck
from .docx_reader import table_where
from .linker import body_paragraphs, linked_ids
from .model import note_key, note_label
from .ooxml import FIELD_DRAWN
from .package import article_dir
from .pdfbiblio import mismatches
from .pdfmatch import (CONTENT, DISPLACED_WHY, EDGE_WHY, FORMULA_MARK, HEAD_WHY, LINE_MARK, LONG_WHY, MATH_WHY,
                       TYPESET_KINDS, UNSURE_WHY, WHOLE_WHY, diff_parts, level_of, typeset_pair)
from .structure import BACK_KIND_JA, RE_FIGCAP, RE_TABCAP, nfkc
from .validate import group_errors
from .structure import (AUTHOR_TABLE_OTHER_EXCLUDED, BACK_OTHER_EXCLUDED, BACK_TABLE_EXCLUDED, EN_AUTHOR_TABLE_OTHER_EXCLUDED,
                        EN_OTHER_EXCLUDED, EN_TABLE_EXCLUDED, FRONT_OTHER_EXCLUDED, FRONT_TABLE_EXCLUDED, NO_LINK_KINDS,
                        TEXTBOX_TEXT_EXCLUDED, UNPLACED_EXCLUSIONS, abstract_missing_srcs, appendix_heading)


def esc(s, n=None) -> str:
    s = "" if s is None else str(s)
    s = s.replace("|", "｜").replace("\n", "⏎").replace("\t", "⇥")
    if n and len(s) > n:
        s = s[:n] + "…"
    return s


BLANK_NAMES = {" ": "半角の空白", "\u3000": "全角の空白", "\t": "タブ", "\u00a0": "改行しない空白"}


def esc_blank(s, n=None) -> str:
    """esc と同じ。ただし、空白の文字だけの文字列は、空欄に見えないよう「（半角の空白）」のような見える表記にする
    （13 章の表の docx・PDF の欄。レポートの表示だけで、XML や docx の文字には影響しない）。空の文字列はそのまま空欄。"""
    s = "" if s is None else str(s)
    if s and not s.strip():
        name = BLANK_NAMES.get(s[0], "空白") if len(set(s)) == 1 else "空白"
        return f"（{name}）" if len(s) == 1 else f"（{name} {len(s)} 文字）"
    return esc(s, n)


def table(headers, rows) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(esc(c) for c in r) + " |")
    return "\n".join(out)


CAT_JA = {"style": "段落の役割（スタイル）", "citation": "引用文献へのリンク", "xref": "図表・注・数式へのリンク",
          "formula": "数式", "name": "著者名", "figure": "図", "table": "表", "url": "URL", "note": "注",
          "box": "囲み・図の注記（テキストボックス）"}
UNRES_JA = {"bibr": "引用文献", "fig": "図の参照", "table": "表の参照", "fn": "注の参照", "float": "図表の位置",
            "box": "囲み・図の注記", "table_body": "表の本体",
            "table_parts": "表の組み立て"}


def style_unknown_rows(plan):
    """本文のスタイルでない（標準など）ために本文の段落として扱った段落を、スタイル名ごとに 1 行にまとめる。"""
    groups = {}
    for p in plan.paras.values():
        if p.note == "style_unknown":
            groups.setdefault(p.style_name or "（なし）", []).append(p)
    rows = []
    for name, ps in groups.items():
        sample = "、".join(f"{p.src}「{esc(p.plain(), 15)}」" for p in ps[:5]) + ("ほか" if len(ps) > 5 else "")
        loc = plan.locations.get(ps[0].src, ps[0].src) + ("ほか" if len(ps) > 1 else "")
        rows.append(("-", CAT_JA["style"], loc,
                     f"本文のスタイルでない段落（スタイル「{name}」）{len(ps)} 件を本文の段落として扱った: {sample}"))
    return rows


def float_notes(plan):
    """本文から参照されていない図・表と、キャプションのない表と、本文の図キャプションの図に含めた図形（PDF と照らして確認する
    ためのもの。3 章）。"""
    out = []
    figs, tabs = linked_ids(plan, "fig"), linked_ids(plan, "table")
    nf = [f"{f.fid}（{esc(shorten_shown(f.caption.plain(), 20))}）" for f in plan.figures
          if f.fid and f.caption is not None and f.fid not in figs]
    if nf:
        out.append("本文中のどこからも参照（リンク）されていない図: " + "、".join(nf))
    nt = [f"{t.tid}（{esc(shorten_shown(t.caption.plain(), 20))}）" for t in plan.tables
          if t.tid and t.caption is not None and t.tid not in tabs]
    if nt:
        out.append("本文中のどこからも参照（リンク）されていない表: " + "、".join(nt))
    nc = []
    for t in plan.tables:
        if t.caption is None:
            first = next((shown_text(p.plain()) for p in (t.table.paragraphs() if t.table else []) if shown_text(p.plain())), "")
            nc.append(f"{t.tid or '-'}（最初のセル「{esc(shorten_shown(first, 15))}」）")
    if nc:
        out.append("キャプションのない表（表番号がないため本文からリンクできない。表として出力した）: " + "、".join(nc))
    # 本文の図キャプションの図に含めた図形（修正計画 W1 の 2.3 の B6。図キャプションの位置に置いたので、位置を決められない図表に数えない）
    cap = []
    for fid, info in plan.floats.items():
        if info.mode != "caption":
            continue
        fig = next((f for f in plan.figures if f.caption is not None and f.caption.src == info.caption_src), None)
        what = f"{fig.fid}「{esc(shorten_shown(fig.caption.plain(), 20))}」" if fig is not None and fig.fid else info.caption_src
        cap.append(f"{fid}（{what}）")
    if cap:
        out.append("本文の図キャプションの図に含め、その位置に置いた図形（キャプションのないグループ図形。近くの段落に結び付いていた）: "
                   + "、".join(cap))
    return out


def float_places(plan) -> str:
    """位置を機械的に決められず、AI の指定もない図表を置いた位置の要約（1 章）。例: 結び付いた段落の後ろ /
    結び付いた段落の後ろ 2 件・本文の最後 1 件。"""
    n = {"anchor": 0, "end": 0}
    for fid in plan.unplaced_floats:
        n["end" if plan.floats[fid].where == "end" else "anchor"] += 1
    if n["anchor"] and n["end"]:
        return f"結び付いた段落の後ろ {n['anchor']} 件・本文の最後 {n['end']} 件"
    return "本文の最後" if n["end"] else "結び付いた段落の後ろ"


def _head(p, n=20) -> str:
    """段落の文字の先頭 n 字（長ければ「…」を付ける）。場所の文に使う（docx の文字のまま）。"""
    t = p.text_only().strip() if p is not None else ""
    return t[:n] + ("…" if len(t) > n else "")


def slot_where(r, slot) -> str:
    """画像の置き場所 slot（article.ImageSlot）の場所を人に示す文。場所の文を書く所（手順 images の行・図の画像の一覧の「場所」の列・
    コマンドラインの行など）は、すべてこれを使う（修正計画 W1 の 2.8）。

    キャプションのある置き場所（図・表・表のセルの図）は章の見出しだけ（「章「3．結果」」。場所はキャプションで分かる）。
    キャプションのない置き場所は、行内（place inline）なら「「{段落の先頭 20 字}」の段落の中」、場所を示す段落 slot.src 自身に文字が
    あれば「「…」の段落の後ろ」（段落に結び付いた画像の図）、なければ前の文字のある段落の「「…」の段落の後ろ」か、章の最初なら
    「章「{見出し}」の最初」（structure.text_before）。図形の中身から組んだキャプションのない図は、図を置いた位置の前の文字のある
    段落で書く。章の見出しが分かれば、後ろに「（章「…」）」を添える。
    """
    from .structure import text_before
    plan = r.plan
    heading, para = text_before(plan, slot.src, slot)
    chapter = f"章「{_head(heading)}」" if heading is not None else ""
    if slot.caption is not None:
        return chapter
    # 図形の中身から組んだ図（float_id のある <fig>）は、図を置いた位置の前の段落で書く（機械的な配置ではアンカー段落の前に
    # 置くので、アンカー段落の「後ろ」とは書かない）
    own = plan.paras.get(slot.src) if not (slot.float_id and slot.place == "fig") else None
    if own is not None and own.text_only().strip():
        para = own
    if para is None:
        return f"{chapter}の最初" if chapter else "本文の最初"
    if heading is not None and para is heading:
        chapter = ""
    where = "の段落の中" if slot.place == "inline" and para is own else "の段落の後ろ"
    return f"「{_head(para)}」{where}" + (f"（{chapter}）" if chapter else "")


def decoration_where(r, img, anchor_src: str = "") -> str:
    """飾りの図形 img（model.ImageRef。decoration のあるもの）の場所を人に示す文（9 章の飾りの一覧。pipeline.decorations）。

    浮動配置の図形の中（float_id があり、図形のアンカー段落 anchor_src が分かる）なら「図形 s3（「{アンカー段落の先頭 20 字}」の段落に
    結び付いている）」、そうでなければ画像の置き場所と同じ書き方（slot_where。文字のある段落の中なら「…の段落の中」、飾りだけの段落なら
    前の文字のある段落の「…の段落の後ろ」）。
    """
    from .article import ImageSlot
    plan = r.plan
    if img.float_id and anchor_src:
        head = _head(plan.paras.get(anchor_src))
        return f"図形 {img.float_id}（" + (f"「{head}」の段落に結び付いている" if head else f"段落 {anchor_src} に結び付いている") + "）"
    own = plan.paras.get(img.para_src)
    if own is not None and own.text_only().strip():
        return slot_where(r, ImageSlot(key="", kind="nocap", src=img.para_src, place="inline"))
    # 飾りだけの段落（空白だけの段落と同じく除外され、要素の木にない）は、docx の順で前の文字のある段落（図形・テキストボックスの
    # 中の段落を除く）の後ろと書く
    prev = None
    for src, p in plan.paras.items():
        if src == img.para_src:
            break
        if p.text_only().strip() and not p.float_id and not p.in_textbox:
            prev = p
    if prev is None:
        return slot_where(r, ImageSlot(key="", kind="nocap", src=img.para_src, place="fig"))
    return slot_where(r, ImageSlot(key="", kind="nocap", src=prev.src, place="fig"))


# 飾りの図形の種類（model.Decoration.kind）の言い方（9 章・図の画像の一覧の備考）
DECORATION_JA = {"frame": "枠", "mask": "白い四角", "line": "線や矢印", "textgroup": "文字の図形の集まり"}


# 画像の置き場所の状態（images.SlotImage.status）の言い方（図の画像の一覧の「入れた画像」の列と備考）
OPTIONAL_CAPTION = "（画像で補える文字の位置。任意）"      # 任意の置き場所（結果のないフィールドの位置）の行の、図・表とキャプションの列
IMAGE_STATUS_JA = {"missing": "未", "user": "入れた", "skipped": "入れない", "unused": "入れていない（任意）"}
OBJECT_MARK = "\ufffc"          # 数式などの図形の位置（Para.plain の代わりの文字）
OBJECT_SHOWN = "［数式など］"     # 画面・コマンドライン・レポート・HTML の表示だけで、この文字の代わりに出す（XML と docx の文字ではない）


def shown_text(text) -> str:
    """docx の文字（キャプション・場所など）を、人が読む表示にした文字列。数式などの位置の文字（U+FFFC）は「［数式など］」にし、
    先頭にあるものは除く（図番号の前の数式の位置は読む手がかりにならない）。表示だけで、XML と docx の文字は変えない。"""
    t = str(text or "").strip()
    while t.startswith(OBJECT_MARK):
        t = t[1:].lstrip()
    return t.replace(OBJECT_MARK, OBJECT_SHOWN)


_BRACKETS = {"（": "）", "「": "」", "『": "』", "(": ")", "［": "］"}


def shorten_shown(text, limit: int = 30) -> str:
    """表示用に limit 字までに切り詰める（表示用の文字にした後。切ったら「…」を付け、開いたままの括弧は閉じる）。"""
    t = shown_text(text)
    if len(t) <= limit:
        return t
    cut, stack = t[:limit], []
    for ch in cut:
        if ch in _BRACKETS:
            stack.append(ch)
        elif stack and ch == _BRACKETS[stack[-1]]:
            stack.pop()
    return cut.rstrip() + "…" + "".join(_BRACKETS[b] for b in reversed(stack))


def _key_ranges(keys) -> str:
    """幹の並びの言い方: fig01〜fig07、tab01、img3fa9c2（figNN・tabNN が 3 つ以上つながるときは「〜」でまとめる）。"""
    out, run = [], []

    def flush():
        if len(run) >= 3:
            out.append(f"{run[0][1]}〜{run[-1][1]}")
        else:
            out.extend(k for _, k, _n in run)
        run.clear()
    for k in keys:
        m = re.fullmatch(r"(fig|tab)(\d+)", k)
        if m and run and run[-1][0] == m.group(1) and int(m.group(2)) == run[-1][2] + 1:
            run.append((m.group(1), k, int(m.group(2))))
            continue
        flush()
        if m:
            run.append((m.group(1), k, int(m.group(2))))
        else:
            out.append(k)
    flush()
    return "、".join(out)


def _same_number_text(rows) -> str:
    """同じ番号の図・表が 2 つ以上ある論文の、名前の付け方の注意（なければ ""）。例: 図4 は 2 つあるので fig04・fig04_2 の名前にしてください。"""
    groups = {}
    for row in rows:
        if row.kind in ("fig", "table"):
            groups.setdefault(re.sub(r"_\d+$", "", row.key), []).append(row)
    parts = [f"{(g[0].label or base)} は {len(g)} 個あるので {'・'.join(x.key for x in g)} の名前に" for base, g in groups.items() if len(g) > 1]
    return ("同じ番号の図・表があります。" + "、".join(parts) + "してください。") if parts else ""


def unmatched_image_text(res, name: str, tail: str = "") -> str:
    """まとめて入れた画像のファイル名が、どの置き場所の名前にも合わなかったときの文（コマンドライン・1 画面版・ノートブックが共用）。

    今の記事識別子を使った例と、この論文の画像の名前の一覧を添える。同じ番号の図・表がある論文では、その名前の付け方も足す。
    tail は画面ごとの、直し方の言い方（「ファイル名を直すか、図ごとの行で選んでください。」など）。
    """
    rows = image_rows(res)
    aid = res.meta.article_id(res.journal)
    fig = next((row.key for row in rows if row.kind != "optional" and row.key), "fig03")
    text = (f"「{name}」に合う図がありません（この論文の画像の名前: {_key_ranges([row.key for row in rows if row.key])}。"
            f"fig03.png・図3.png・{aid}_{fig}.png のような名前にします。ほかの記事の識別子が付いた名前は入れません）。")
    return text + _same_number_text(rows) + tail


def clash_images_text(key: str, names) -> str:
    """同じ置き場所に合うファイルが複数あったときの文（どれも入れない。コマンドライン・1 画面版・ノートブックが共用）。"""
    return f"同じ図（{key}）に合うファイルが複数あるので、どれも入れていません: " + "、".join(names)


@dataclass
class ImageRow:
    """図の画像の一覧の 1 行（image_rows。9 章の表・画面の欄・コマンドラインの表・図の確かめの一覧が同じものを使う）。

    key は置き場所の幹、name は Graphics/ の中の名前、label は「図3」「表1」（キャプションのない画像は ""）、caption はキャプションの
    文字（docx の文字のまま。なければ ""）、where は場所（slot_where）、place は位置の決め方（structure.PLACE_JA の語）、status は
    images.SlotImage.status、detail は入れた画像の元のファイル名・形式・幅×高さ px・KB、note は備考（修正計画 W1 の 4.3 の順に「。」で
    つないだもの）、image は images.SlotImage、slot は article.ImageSlot。slot_note は置き場所の備考（ImageSlot.note。手順 images の行の
    括弧に添えるもの。図形で描いた図では「docx でこの図の画像を見つけられませんでした」の代わりに、図形で描いた図の備考）、drawn は
    図形で描いた図の図形の種類（「文字の図形の集まり」など。そうでなければ ""）。
    """
    key: str
    name: str
    kind: str
    label: str
    caption: str
    where: str
    place: str
    status: str
    detail: str
    note: str
    image: object = None
    slot: object = None
    slot_note: str = ""
    drawn: str = ""


def _image_detail(i) -> str:
    """入れた画像の元のファイル名・形式・幅×高さ px・KB（入れていなければ ""）。"""
    if i.status != "user":
        return ""
    parts = [i.source_name] if i.source_name else []
    parts.append((i.format or "").upper().replace("JPG", "JPEG"))
    if i.size:
        parts.append(f"{i.size[0]}×{i.size[1]} px")
    parts.append(f"{max(1, round(i.bytes / 1024))} KB")
    return "・".join(x for x in parts if x)


def _covers_note(slot) -> str:
    """1 枚にまとめる図の備考: 置き場所に docx の画像の位置が 2 つ以上あるとき（covers が 2 つ以上）。"""
    if len(slot.covers) < 2:
        return ""
    pics = sum(1 for i in slot.covers if not i.shape_only)
    shapes = len(slot.covers) - pics
    what = "と".join(x for x in ((f"画像 {pics} 枚" if pics else ""), (f"図形 {shapes} 個" if shapes else "")) if x)
    return f"docx ではこの図に{what}（1 枚にまとめた画像を入れてください）"


HOW_NOTES = {"near": "近くの段落に結び付いた画像をこの図に含めた", "same_para": "キャプションの段落の中の画像をこの図に含めた"}


def drawn_note(kinds: str) -> str:
    """図形で描いた図の備考（修正計画 W1 の 4.3 の備考の 4）。kinds は図形の種類の言い方（「文字の図形の集まり」など）。"""
    return f"Word の図形（{kinds}）で描いた図です。出版版 PDF から図の部分を切り取って入れてください"


def drawn_figures(r) -> dict:
    """図形で描いた図: {置き場所の幹: 図形の種類の言い方（「文字の図形の集まり」など。「・」でつなぐ）}（Result.decorations の figure のあるもの）。"""
    out = {}
    for d in getattr(r, "decorations", []):
        if d.figure:
            out.setdefault(d.figure, [])
            kind = DECORATION_JA.get(d.kind, d.kind)
            if kind not in out[d.figure]:
                out[d.figure].append(kind)
    return {k: "・".join(v) for k, v in out.items()}


def image_rows(r) -> list:
    """図の画像の一覧（ImageRow。XML の順〈structure.figure_rows〉）。手順 images の行・9 章の表・画面・コマンドラインが使う。

    行は、出力した画像の置き場所（Result.images）ごとに 1 つ（表で組んだ図など、置き場所のない図・表は入らない）。備考は、状態（未・
    入れない）、置き場所の備考（ImageSlot.note。表で組めなかった理由・表のセルで画像を決められなかった理由と候補・本文の最後に置いた
    理由。必ず出す）、1 枚にまとめる図、図形で描いた図（Result.decorations の figure）、含め方（近くの段落・キャプションの段落の中の
    画像を含めた）、キャプションが変わった持ち越し、同じ中身の画像が入っている図、の順。図形で描いた図は、置き場所の備考の
    「docx でこの図の画像を見つけられませんでした」（structure.NO_FIGURE_IMAGE）を出さない（画像がないのは図形で描いたため）。
    """
    from .structure import NO_FIGURE_IMAGE, PLACE_JA, figure_rows
    if r.plan is None:
        return []
    slots = {s.key: s for s in r.plan.slots}
    places = {}
    for row in figure_rows(r.plan):
        if row.key:
            places.setdefault(row.key, PLACE_JA.get(row.place, row.place))
    same = {}
    for i in r.images:
        if i.status == "user" and i.sha1:
            same.setdefault(i.sha1, []).append(i)
    changed_keys = {c.key for c in getattr(r, "images_changed", [])}
    drawn = drawn_figures(r)
    out = []
    for i in r.images:
        slot = slots.get(i.key)
        notes = []
        slot_note = i.note
        if i.key in drawn and slot_note.startswith(NO_FIGURE_IMAGE):
            slot_note = slot_note[len(NO_FIGURE_IMAGE):].lstrip("。")
        if slot_note:
            notes.append(slot_note)
        if slot is not None:
            notes.append(_covers_note(slot))
        if i.key in drawn:
            notes.append(drawn_note(drawn[i.key]))
            slot_note = "。".join(x for x in (drawn_note(drawn[i.key]), slot_note) if x)
        if slot is not None:
            notes += [HOW_NOTES[h] for h in (slot.how or "").split("+") if h in HOW_NOTES]
        if i.key in changed_keys and i.status == "user":
            notes.append("入れた後にキャプションが変わりました")
        others = [o for o in same.get(i.sha1, []) if o is not i] if i.status == "user" and i.sha1 else []
        if others:
            notes.append("同じ画像が" + "・".join(o.label or o.key for o in others) + " にも入っています")
        out.append(ImageRow(key=i.key, name=i.name, kind=i.kind, label=i.label, caption=i.caption, where=i.location,
                            place=places.get(i.key, ""), status=i.status, detail=_image_detail(i),
                            note="。".join(x for x in notes if x), image=i, slot=slot, slot_note=slot_note,
                            drawn=drawn.get(i.key, "")))
    return out


def images_progress(r) -> tuple:
    """手順 images の数: (残りの数, 全部の数)。全部は、任意の置き場所と「入れない」とした置き場所を除いた数（修正計画 W1 の 4.1）。"""
    need = [i for i in r.images if i.kind != "optional" and i.status in ("missing", "user")]
    return sum(1 for i in need if i.status == "missing"), len(need)


# PDF と照合しない番号の但し書き（8 章・13.2 で共用）
NUMBERS_NOT_MATCHED_BODY = ("表のセル・囲み・別行数式の段落と、付記・謝辞・注・引用文献・資料・英文要旨の見出しの番号は PDF と照合しないので、"
                            "Word の形のままです。")
NUMBERS_NOT_MATCHED = "（" + NUMBERS_NOT_MATCHED_BODY + "）"


# 画像を入れる場所を作れなかった画像（要対応 lost。修正計画 W1 の 4.2）の説明と直し方。APP_MOVE_HOW は、本文の外の資料を移す直し方の
# ただ 1 つの文で、lost・要確認 app_after_refs（・W8 の float_end）が共用する（手順 images の行・置き場所の備考には直し方を書かない）
LOST_IMAGES_WHY = ("引用文献・注の節や、題目・著者名・所属の段落の中にある画像には、XML に画像を入れる場所を作れません"
                   "（このままでは、その画像は J-STAGE に載りません）。")
APP_MOVE_HOW = "Word で資料（見出しと中身）を英文要旨の後ろ（論文の最後）に移して、変換し直してください。"
LOST_IMAGES_MORE = "題目・著者名・所属の段落の中の画像は、本文の段落に移します。要らない画像なら、Word で消してください。"
LOST_IMAGES_HOW = "資料の図なら、" + APP_MOVE_HOW + LOST_IMAGES_MORE


def lost_image_label(li) -> str:
    """画像を入れる場所を作れなかった画像（pipeline.lost_images）1 件の見出し。例: img3（段落 d45「試験太郎（2020）」、引用文献 2件目）。

    レポートの冒頭（することの一覧と囲み）・9 章、Colab の枠、コマンドラインの表示で使う。
    """
    where = []
    if li.src:
        where.append(f"段落 {li.src}" + (f"「{li.text}」" if li.text else ""))
    if li.location:
        where.append(li.location)
    return f"{li.image_id}（{'、'.join(where)}）" if where else li.image_id


def lost_autonum_label(ln) -> str:
    """XML に番号を出せなかった段落（pipeline.lost_autonums）1 件の見出し。例: d95（本文 > 3．方法 / 第4要素）「番号付きの質問」の番号「1.」（XML の td）。"""
    head = f"{ln.src}（{ln.location}）" if ln.location else ln.src
    return f"{head}{f'「{ln.text}」' if ln.text else ''}の番号「{ln.number}」（XML の {ln.where}）"


def textbox_summary(plan) -> str:
    """文字だけのテキストボックスの扱いの要約（1 章）。空白だけのものは数えない。該当がなければ ''。"""
    boxes = [b for b in plan.textboxes.values() if b.kind != "blank"]
    if not boxes:
        return ""
    n = {k: sum(1 for b in boxes if b.kind == k) for k in ("box", "label", "undecided")}
    est = sum(1 for b in boxes if b.kind == "box" and b.estimated)
    parts = []
    if n["box"]:
        parts.append(f"囲み {n['box']} 件（boxed-text" + (f"。うち位置を推定 {est} 件・要確認" if est else "") + "）")
    if n["label"]:
        parts.append(f"図の注記として除外 {n['label']} 件")
    if n["undecided"]:
        parts.append(f"決められずに除外 {n['undecided']} 件（要確認）")
    return "、".join(parts)


def textbox_chapters(plan) -> str:
    """1 章の「テキストボックスの文字」の行に示す章（中身があるところだけ）: 2 章（AI が囲み・図の注記を判断したもの）、3 章
    （決められないもの・位置を推定した囲み）、4 章（機械的な判断の一覧）、6 章（除外した文字）、10 章（図の注記の警告）。"""
    kinds = {b.kind for b in plan.textboxes.values()}
    stages = {d.stage for d in plan.decisions if d.category == "box"}
    out = ["2 章"] if "ai" in stages else []
    if plan.undecided_boxes or plan.estimated_boxes:
        out.append("3 章")
    if "mechanical" in stages:
        out.append("4 章")
    if kinds & {"label", "undecided"}:
        out.append("6 章")
    if "label" in kinds:
        out.append("10 章")
    return "・".join(out)


def _box_samples(plan, xids, n=5) -> str:
    """テキストボックスの例（例: x4（段落 d20「…」に結び付いた「（ヒント）」）、…）。"""
    out = []
    for x in xids[:n]:
        info = plan.textboxes[x]
        head = next((q.text_only().strip() for q in info.paras if not q.is_blank), "")
        anchor = plan.paras.get(info.box.anchor_src)
        at = anchor.text_only().strip() if anchor is not None else ""
        out.append(f"{x}（段落 {info.box.anchor_src}" + (f"「{esc(at, 15)}」" if at else "") + f"に結び付いた「{esc(head, 15)}」）")
    return "、".join(out) + ("ほか" if len(xids) > n else "")


def _para_samples(rows, n=5, width=15) -> str:
    """段落の例（例: d12「文字の冒頭」、d13「…」。先頭 width 文字）。文字のない段落（画像だけの段落など）は「d14（文字なし）」と書く。"""
    return ("、".join(f"{src}「{esc(text.strip(), width)}」" if text.strip() else f"{src}（文字なし）" for src, text in rows[:n])
            + ("ほか" if len(rows) > n else ""))


def image_summary(r) -> str:
    """1 章の要約の「画像」の行（修正計画 W1 の 4.4）。画像を入れる場所を作れなかった画像があるときは、それも書く。"""
    left, total = images_progress(r)
    if not total:
        line = "画像の要る図・表はありません"
    elif left:
        line = f"図の画像 {total - left}/{total} 枚を入れた（残り {left} 枚。9 章）"
    else:
        line = f"図の画像 {total} 枚をすべて入れた（9 章）"
    if r.lost_images:
        line += f"。ほかに、画像を入れる場所を作れなかった画像が {len(r.lost_images)} つあり、要対応（9 章）"
    return line


def article_folder(r) -> str:
    """ZIP の中の記事フォルダ（例: jasme/25/1/25_77/）。"""
    return article_dir(Path(""), r.journal, r.meta).as_posix() + "/"


def upload_issues(r) -> list:
    """J-STAGE のアップロード時チェックの結果: XML で判定したもの（jstage_issues）と、ZIP を読み直して見つけたもの（zip_issues）。

    レポートの 1 章・12 章、コマンドライン・Colab の表示で使う（Result では 2 つを分けて持つ）。
    """
    return list(r.jstage_issues) + list(r.zip_issues)


def not_zipped_note(r) -> str:
    """10 章の、記事フォルダにあるのにアップロード用の ZIP に入れなかったファイル（Result.not_zipped）の説明と対処。"""
    aid = r.meta.article_id(r.journal)
    names = r.not_zipped
    L = [f"記事フォルダ（`{article_folder(r)}`）にあるが、アップロード用の ZIP に入れなかったファイルが {len(names)} 件"
         "あります: " + "、".join(f"`{esc(n)}`" for n in names) + "。前の変換の残りか、手で置いたファイルです。ZIP には、今回の"
         "変換で作った XML と画像、今回指定した PDF だけを入れます。"]
    if f"{aid}.pdf" in names:
        L.append("PDF を ZIP に入れるときは、Colab では記事の PDF を選び直し（ノートブックは手順 2、1 画面版は「PDF」の欄）、"
                 "コマンドラインでは --pdf で PDF を指定して、"
                 "変換し直してください。")
    if any(n.startswith("Graphics/") for n in names):
        L.append("画像は、用意が必要な画像（9 章で要対応）なら、Colab では画像を入れ直し（ノートブックは手順 7、1 画面版は「画像を入れる」の"
                 "欄）、コマンドラインでは --images で入れ直してください"
                 "（それ以外の画像は、前の変換の残りなので、対応は要りません）。")
    if any(n != f"{aid}.pdf" and not n.startswith("Graphics/") for n in names):
        L.append("ほかのファイルは J-STAGE にアップロードしないので、対応は要りません。")
    return "".join(L)


def pdf_checklist_line(r) -> str:
    """することの一覧（冒頭）の PDF の行。PDF は J-STAGE で必須で、ZIP に入れるのは変換のときに指定した PDF だけ。"""
    pdf = f"{r.meta.article_id(r.journal)}.pdf"
    if r.has_pdf:
        return f"- [x] PDF（{pdf}）がアップロード用の ZIP に入っている（J-STAGE では PDF が必須）"
    return (f"- [ ] **PDF（{pdf}）がアップロード用の ZIP に入っていない**（J-STAGE では PDF が必須）: Colab では記事の PDF を選び直し"
            "（ノートブックは手順 2、1 画面版は「PDF」の欄）、コマンドラインでは --pdf で PDF を指定して、変換し直す")


# レポートの冒頭の「- 出版版 PDF:」の行の文（PDF の有無と、表記を PDF に合わせたか）
def pdf_use_ja(r) -> str:
    if not getattr(r, "pdf_name", ""):
        return "なし（表記は docx のまま）"
    if getattr(r, "route", "docx") == "pdf":
        return "あり（全角・半角・句読点などの表記を PDF に合わせた）"
    return "あり（照合だけ。表記は docx のまま。コマンドラインの `--route docx`）"


SECTION_UNSURE = "13.3"       # 照合できなかった箇所（記録）を載せる節


def pdf_summary(r) -> str:
    """出版版 PDF との照合の要約（レポートの 1 章、コマンドライン・Colab の表示）。

    PDF と違う箇所（要確認。13.1）・表記を PDF に合わせた箇所（route docx は「docx のまま」）・照合できなかった箇所と PDF に見つからない
    段落（13.3）の件数。"""
    pc, fx = r.pdf_check, r.docx_fix
    if pc is None:
        return "PDF なし（照合していない）"
    if not pc.ok:
        return f"照合できなかった（{pc.message}）"
    c = mismatch_check(r) or pc
    n = mismatch_count(r)
    parts = [f"PDF と違う箇所 {n} 件（要確認。{MISMATCH_AT}）" if n else "PDF と違う箇所 なし"]
    if fx is not None:
        from .pdfdocx import tracked_counts
        ins, dels = tracked_counts(fx.path)
        parts.append(f"表記を PDF に合わせた {len(fx.applied_typeset) + len(r.plan.pdf_numbers)} 箇所"
                     f"（変更履歴: 挿入 {ins}・削除 {dels}）")
    else:
        parts.append(f"PDF と表記が違う箇所 {c.typeset_count + c.drop_count + len(c.numbers)} 箇所（docx のまま）")
    unmatched = [s for s in c.unmatched if s not in set(c.found_elsewhere)]
    rec = len(c.unsure_diffs)
    if rec or unmatched:
        parts.append(f"照合できなかった箇所 {rec} 件・PDF に見つからない段落 {len(unmatched)} 件"
                     + ("（半分以上の段落が見つからない。PDF がこの論文の全体か確認）" if pdf_suspect(r) else "")
                     + f"（{SECTION_UNSURE}）")
    if r.supplement is not None and not r.supplement.ok:
        parts.append("補完の確かめ: 不合格（要対応）")
    return " / ".join(parts) + "（13 章）"


def ignored_lines(r) -> list:
    """組版で入る文字（誌名の行・柱・投稿受付日など）や図・表の中の文字とみなして、照合に使わなかった PDF の文字
    [(段落 ID, 行または投稿受付日の文字列)]。

    route pdf では、元の docx と PDF の照合（直す箇所を決めたもの）から。
    """
    fx = r.docx_fix
    pc = fx.check if fx is not None and fx.check is not None else r.pdf_check
    return list(pc.ignored_lines) if pc is not None and pc.ok else []


def _clean(t) -> str:
    return esc(t.replace(chr(0xFFFC), "〓"))


def _fix_typeset_kind(f) -> str:
    """route pdf: 組版の違いの直し f の種類（pdfmatch.TYPESET_KINDS の鍵）。glyph は文字の対から決める。"""
    if f.kind in ("width", "space"):
        return f.kind
    return typeset_pair(f.old, f.new, case=True) or "dash"


def typeset_counts(items) -> str:
    """組版の違い（(A)）の種類ごとの内訳の文: 「英数字・記号の全角・半角 3 箇所、ダッシュ・ハイフン 1 箇所」。

    items は pdfdocx.Fix（kind が width・space・glyph）か、種類の鍵（TYPESET_KINDS）の並び。route docx・route pdf で同じ文を使う。
    """
    cnt = Counter(x if isinstance(x, str) else _fix_typeset_kind(x) for x in items)
    return "、".join(f"{label} {cnt[k]} 箇所" for k, label in TYPESET_KINDS.items() if cnt[k])


def check_typeset_kinds(pc, plan) -> list:
    """route docx: 照合（pdfmatch.PdfCheck）の組版の違いの種類の並び（1 文字・1 区間ごと。typeset_counts の入力）。"""
    kinds = ["width"] * pc.width_count + ["space"] * pc.drop_count
    for d in pc.typeset_diffs:
        text = plan.paras[d.src].plain()
        kinds += [kind for a, b, new, kind in diff_parts(text, d, d.src in pc.case_srcs) if kind != "text"]
    return kinds


# 13 章の表（と Colab の枠）の「〓」の説明。docx の側（docx・前後の欄）では docx の数式・画像、PDF の側では PDF で文字として
# 読み取れない数式などの位置（同じ記号なので、表に「〓」があるときは、表の前に必ず添える）
FORMULA_NOTE = (f"表の「{FORMULA_MARK}」は、docx の欄と前後の欄では docx の数式・画像、PDF の欄では PDF で数式など文字として"
                "読み取れない部分です。")


def _formula_note(L, cells):
    """表の文字 cells のどれかに FORMULA_MARK があれば、表の前に FORMULA_NOTE を添える。"""
    if any(FORMULA_MARK in (c or "") for c in cells):
        L.append(FORMULA_NOTE)
        L.append("")


def word_note_refs(plan) -> int:
    """Word の脚注・文末脚注の参照のうち、注へのリンクとして出力されるものの数（1 章のリンクの数）。

    XML に出力しなかった段落（plan.exclusions）と、注の番号をリンクにしない段落（題目・副題・著者名・所属・引用文献。
    ArticlePlan.no_link_paras）の中の参照は、リンクにならないので数えない（FnNode.linked と同じ条件）。
    """
    ids = {fn.word_id for fn in plan.fns if fn.word_note}
    unlinked = {e.src for e in plan.exclusions} | set(plan.no_link_paras())
    return sum(1 for p in plan.paras.values() if p.src not in unlinked for a in p.atoms
               if a.kind == "fnref" and note_key(a.fn_kind, a.fn_id) in ids)


def has_endnotes(plan) -> bool:
    """Word の文末脚注から作った注があるか（1 章・8 章の表記を変える）。"""
    return any(fn.word_note and fn.word_kind == "endnote" for fn in plan.fns)


def word_note_rows(r) -> list:
    """Word の脚注・文末脚注と XML の注の対応（8 章の表）。文末脚注・本文からリンクのない注・記号を自分で付けた注のどれかが
    あるときだけ作る（脚注だけで、どれもなければ空。0.23.1 までと同じ表示）。本文からリンクのない注には、参照のある段落
    （XML に出力しなかった段落と、題目・引用文献など注の番号をリンクにしない段落。ArticlePlan.unlinked_places）を添える。
    「Word の注」の欄の番号は docx の中の注の ID で、Word の表示（文末脚注は「i」など）と違うことがあるので、Word で注を
    探せるよう、注の書き出し（文字のある最初の段落の docx の文字。15 文字まで）も載せる。"""
    plan = r.plan
    word = [fn for fn in plan.fns if fn.word_note]
    if not any(fn.word_kind == "endnote" or not fn.linked or fn.custom_mark for fn in word):
        return []
    rows = []
    nolink = plan.no_link_paras()
    for k, fn in enumerate(word, 1):
        mark = plan.pdf_numbers.get(("fnlist", fn.word_id)) or r.journal.fn_mark.format(n=fn.number or k)
        if not fn.linked:
            out, shown = plan.unlinked_places(fn.word_refs)
            if not shown:
                link = f"なし（参照は XML に出力しなかった段落 {'、'.join(out)} の中だけ）"
            else:
                before = f" XML に出力しなかった段落 {'、'.join(out)} と、" if out else ""
                names = "。著者名の中では番号も出力しない" if any(nolink.get(s) == "著者名" for s in fn.word_refs) else ""
                link = f"なし（参照は{before}{'、'.join(shown)} の中だけ。{NO_LINK_KINDS}の中の注の番号はリンクにしない{names}）"
        elif fn.custom_mark:
            # 本文の参照は中身のない <xref>（emit.Emitter.write_object）。記号はその後ろに docx の文字のまま出るので、リンクにならない
            link = "あり（中身のない参照。本文の記号はリンクの外で docx の文字のまま。J-STAGE のプレビューで確かめる）"
        else:
            link = "あり"
        head = next((t for t in (p.text_only().strip() for p in fn.paras) if t), "")
        rows.append((fn.fid, note_label(fn.word_id), mark, esc(head, 15) if head else "（文字なし）", link))
    return rows


def note_problems(plan):
    """手で書いた注（Word の脚注機能を使わずに書かれたもの）の読み取りの問題: (注の一覧, 本文で初めて参照された順の注の ID,
    番号を読み取れなかった注 unnum, 本文から参照されない注 unref)。3 章の文（note_notes）と要確認 note_unlinked が同じ判定を使う
    （件数がずれない）。AI の仕上げ（link_note）でリンクされた注は、plan の本文の参照に入っているので数えない。注がなければ空の組。"""
    fns = [fn for fn in plan.fns if not fn.word_note]
    if not fns:
        return [], [], [], []
    order = []   # 本文で初めて参照された順
    for p, where in body_paragraphs(plan):
        if where in ("ref", "fn"):
            continue
        for a in p.atoms:
            if a.link is not None and a.link.kind == "xref" and a.link.attrs.get("ref-type") == "fn":
                if a.link.attrs.get("rid") not in order:
                    order.append(a.link.attrs.get("rid"))
    unnum = [fn for fn in fns if fn.number is None]
    unref = [fn for fn in fns if fn.fid not in order]
    return fns, order, unnum, unref


def note_notes(plan):
    """注（Word の脚注機能を使わずに書かれたもの）の番号と、本文での参照の対応。PDF と照らして確認するためのもの。"""
    out = []
    fns, order, unnum, unref = note_problems(plan)
    if not fns:
        return out
    nums = [fn.number for fn in fns]
    if unnum:
        out.append("先頭に番号（「1)」「（注1）」など）を読み取れなかった注: " + "、".join(
            f"{fn.fid}（「{esc(fn.paras[0].plain()[:20])}」"
            + (f"。{len(fn.paras)} 段落を 1 件の注にまとめた" if len(fn.paras) > 1 else "") + "）" for fn in unnum)
            + "。番号の書き方が想定外のため、複数の注が 1 件にまとめられている可能性がある。PDF と照らして確認し、"
              "AI による仕上げ（注の区切りの指定）を使うか、docx の注の番号をテンプレートの形式（「1)」）にしてから変換し直す")
    elif nums != list(range(1, len(nums) + 1)):
        out.append("注の番号が 1 からの連番になっていない: " + "、".join(str(n) for n in nums))
    if unref:
        out.append("本文中のどこからも参照（リンク）されていない注: " + "、".join(
            f"{fn.fid}（{esc(fn.paras[0].plain()[:20])}）" for fn in unref))
    by_id = {fn.fid: fn.number for fn in fns}
    seq = [by_id[r] for r in order if by_id.get(r) is not None]
    if seq != sorted(seq):
        out.append("本文で注が番号順に参照されていない（本文での初出の順: " + " → ".join(f"注{n}" for n in seq) + "）")
    return out


# ---------------------------------------------------------------------------- 要対応・要確認の知らせ（1 か所にまとめる）
# 利用者に知らせることは、ここ（actions）に Action を 1 つ足す。レポートの冒頭（することの一覧と囲み）、Colab の枠（要対応は赤、要確認は黄）（colab.result_boxes）と
# 手順 8 の止め方、コマンドラインの標準エラーと終了コードは、どれも actions の結果だけで決まる（個別の表示を足さない）。
NEEDS_ACTION = "要対応"     # コマンドラインの終了コード 1、Colab の手順 8 で一度止める、赤い枠、レポートの冒頭（することの一覧と囲み）
TO_CHECK = "要確認"         # 黄色い枠、レポートの冒頭（することの一覧と囲み）だけ（終了コードは 0）
# 毎回の手順（Action.required: 必須か推奨か。Action.done: 済んだか）。青い枠とすることの一覧の行に出す（レポートの冒頭の囲みには出さない）。
# 残っている必須の手順は要対応と同じく終了コード 1・Colab の手順 8 で一度止める。推奨の手順は、残っていても失敗しても終了コード 0 で、止めない
# （止める知らせは blocking の 1 か所で決める）
STEP = "手順"


# box_detail（Colab の枠の本文）などの文の中の、画面の操作を指す目印。ノートブックの手順番号や 1 画面版の欄の名前は、ここには書かず、
# 目印 step() で書く。目印を画面ごとの語に置き換えるのは colab.step_text の 1 か所（colab.STEP_WORDS）。
# 目印の名前を足すときは、colab.STEP_WORDS のすべての画面に語を足す（足りなければ、置き換えのときに例外になる）。
# 目印は U+0000 で挟む。U+0000 は XML 1.0 の文字ではなく、docx の文字（w:t）・ファイル名・PDF の文字（pdfmatch が制御文字を除く）の
# どれにも入らないので、文の中の docx 由来の文字（段落の抜粋など）が目印と読まれることがない。
STEP_NAMES = ("docx", "pdf", "meta", "ai_choose", "prompt", "paste", "repaste", "convert_again",
              "answer_field", "apply_button", "images", "pdf_attach", "files")
STEP_MARK = "\x00"
STEP_MARK_PATTERN = STEP_MARK + "step:([^\x00]*)" + STEP_MARK


def step(name: str) -> str:
    """画面の操作を指す目印（box_detail などに書く。画面ごとの語への置き換えは colab.step_text）。"""
    if name not in STEP_NAMES:
        raise ValueError(f"知らない目印: {name}")
    return STEP_MARK + "step:" + name + STEP_MARK


# ---------------------------------------------------------------------------- 構造の衝突で変換を中止するときの文（K1・K2）
# report.actions の知らせではなく、pipeline.StructureConflictError の文（例外の表示）。画面の操作は目印 step() で書く。
# 抜粋・段落 ID・Word での直し方を、衝突（article.StructureConflict）ごとに 1 行で書く。直し方は Word のスタイル名（jasme.toml の名前）と
# Word での操作（段落を消す・移す、スタイルを変える、著者表の欄に並べる）で書き、変換ツールの内部の名前は書かない。
CONFLICT_HEADING_JA = {"ref_heading": "引用文献", "fn_heading": "注", "notes": "付記", "ack": "謝辞"}
CONFLICT_PARAS_JA = {"ref_heading": "文献", "fn_heading": "注", "notes": "付記の本文", "ack": "謝辞の本文"}  # 後ろの節の段落の言い方
# 所属の衝突の文の共通の部分（どの著者名に付くかの規則と、直し方）
AFF_LOOSE_RULE = "所属の段落は、その後ろの著者名（次の所属の段落の手前まで）に付けて出力するので"
AFF_TABLE_RULE = "著者表の所属は、同じ行と、次の所属の行の手前までの行の著者名に付けて出力するので"
AFF_LOOSE_FIX = ("ほかの著者の所属なら、その著者名の段落のすぐ前に移してください。1 人の著者に所属が 2 つ以上あるときは、テンプレートの"
                 "著者表を使い、その著者の行の所属の欄に段落を分けて並べてください。")


def _sample(plan, src) -> str:
    """段落 1 つの例（d12「文字の冒頭」。文字のない段落は d12（文字なし））。"""
    p = plan.paras.get(src)
    return _para_samples([(src, p.text_only() if p is not None else "")])


def _conflict_fix(c, prev: str) -> str:
    """見出し・節の衝突（ref_heading・fn_heading・notes・ack）の Word での直し方。prev: 前の節の言い方（「前の見出し d13 の節」など）。

    前の節と後ろの見出しの間に別の種類の後付けの節があるとき（c.between）は、後ろの見出しを消すだけでは、後ろの節の段落が間の節に
    入る（引用文献 → 注 → 参考文献で「参考文献」だけを消すと、後ろの文献が注の続きになる）ので、先に後ろの節の段落を前の節の最後に
    移してもらう。"""
    if not c.between:
        return f"後ろの見出し {c.by} の段落を消してください（その後ろの段落は、{prev}に続きます）。"
    return (f"後ろの見出し {c.by} の節の段落（{CONFLICT_PARAS_JA[c.kind]}）を{prev}の最後に移してから、後ろの見出し {c.by} の"
            "段落を消してください（間にほかの後付けの節があるので、見出しを消すだけでは、後ろの節の段落が間の節に入ってしまいます）。")


def _aff_line(plan, c, ids) -> str:
    """所属の衝突（aff）の 1 行。"""
    row = _para_samples([(s, plan.paras[s].text_only() if s in plan.paras else "") for s in c.lost])
    if c.where == "loose" and c.by:
        same = plan.paras[c.by].text_only().strip() == plan.paras[c.lost[-1]].text_only().strip()
        nxt = "同じ文字の" if same else "次の"
        fix = ("同じ所属を重ねて書いたのなら、どちらかの段落を消してください。" + AFF_LOOSE_FIX if same
               else AFF_LOOSE_FIX + "要らない所属なら消してください。")
        return (f"・所属の段落 {row}の後ろに、著者名がないまま{nxt}所属の段落 {_sample(plan, c.by)}が続いています。"
                f"{AFF_LOOSE_RULE}、{ids} が XML に入りません。{fix}")
    if c.where == "loose":
        return (f"・最後の所属の段落 {row}の後ろに著者名がありません。{AFF_LOOSE_RULE}、{ids} が XML に入りません。"
                f"{AFF_LOOSE_FIX}要らない所属なら消してください。")
    if c.by:
        return (f"・著者表の、所属 {row}の行に著者名がなく、次の所属の行 {_sample(plan, c.by)}が続いています。{AFF_TABLE_RULE}、"
                f"{ids} が XML に入りません。その所属が付く著者の行の所属の欄に移し、段落を分けて並べてください。"
                "要らなければ行を消してください。")
    return (f"・著者表の最後の所属の行 {row}に著者名がありません。{AFF_TABLE_RULE}、{ids} が XML に入りません。著者名が表の外に"
            "あるなら、その著者名をこの行の著者名の欄に移してください。ほかの著者の所属なら、その著者の行の所属の欄に移し、"
            "段落を分けて並べてください。要らなければ行を消してください。")


def _conflict_line(plan, c) -> str:
    """衝突 c の 1 行（「・」で始まる）。"""
    ids = "、".join(c.lost)
    first = c.lost[0]
    if c.kind == "aff":
        return _aff_line(plan, c, ids)
    before, after = _sample(plan, first), _sample(plan, c.by)
    if c.kind == "abstract_heading":
        return (f"・英文要旨の見出しが 2 つあります（前 {before}、後 {after}）。XML の英文要旨の見出しは 1 つだけなので、{first} が "
                "XML に入りません。要らない方の見出しの段落を消してください（見出しの後ろの段落は、英文要旨の段落として続きます）。"
                "見出しでない段落が英文要旨の見出しのスタイル（「英文要旨見出し」など）になっているなら、その段落のスタイルを"
                "「英文要旨」にしてください。")
    name = CONFLICT_HEADING_JA[c.kind]
    if c.kind in ("notes", "ack"):
        # lost は前の節の、空白だけの段落を除くすべて（先頭はふつう前の見出し）。表のセルの段落も含むので、段落の件数は書かず、
        # ID の範囲で示す（Word で見える段落・表の数と合わない件数を出さない）
        span = f"{c.lost[0]}〜{c.lost[-1]}" if len(c.lost) > 1 else c.lost[0]
        return (f"・{name}の節が 2 つあります（前の節 {before}から、後ろの見出し {after}）。XML の{name}は 1 つだけなので、"
                f"前の節の段落（{span}。節の中の表のセルの段落も含む）が XML に入りません。1 つの節にまとめてください。"
                + _conflict_fix(c, f"前の節（{span}）"))
    fix = _conflict_fix(c, f"前の見出し {first} の節")
    if c.kind == "fn_heading":
        kinds = ["本文などのスタイル。文字から注の見出しと推定" if t else "「注見出し」のスタイル" for t in c.by_text]
        return (f"・注の見出しが 2 つあります（前 {before}〈{kinds[0]}〉、後 {after}〈{kinds[1]}〉）。注の一覧の見出しは 1 つだけなので、"
                f"{first} が XML に入りません。注の節の見出しにする「注」1 つだけを「注見出し」スタイルにし、ほかの「注」（表の注の"
                "見出しなど）は「注本文」スタイルにしてください（本文・標準・章見出しのスタイルの「注」だけの段落は、文字から注の見出しと"
                f"推定されます）。注の一覧が 2 つに分かれているなら、{fix}")
    guessed = [src for src, t in ((first, c.by_text[0]), (c.by, c.by_text[1])) if t]
    guess = ""      # 文字から推定した引用文献の見出しなら、見出しでないときの直し方を添える
    if guessed:
        srcs = "・".join(guessed)
        guess = (f"{srcs} は「参考文献見出し」のスタイルではありませんが、文字から引用文献の見出しと推定しました。見出しでなければ、"
                 "スタイルを「参考文献」などにしてください。")
    return (f"・引用文献の見出しが 2 つあります（前 {before}、後 {after}）。XML の引用文献の見出しは 1 つだけなので、{first} が "
            f"XML に入りません。{fix}文献の順はそのままでかまいません。{guess}")


def structure_conflict_text(plan) -> str:
    """原稿の構造の衝突（plan.structure_conflicts）で変換を中止するときの文（pipeline.StructureConflictError の文）。

    衝突ごとに、段落 ID・抜粋・Word での直し方を 1 行で書く（すべて挙げる）。Markdown ではない。画面の操作は目印 step() で書く。
    """
    cs = plan.structure_conflicts
    docx = step("docx")
    head = (f"この原稿には、そのまま変換すると段落の文字が XML に入らなくなる箇所が {len(cs)} か所あるため、変換を中止しました"
            "（XML とレポートは作っていません）。docx の文字を 1 文字も変えずに XML にするため、どちらの段落を残すか・どこに"
            f"まとめるかを変換ツールは決めません。Word で次のように直して保存し、{docx}からやり直してください。")
    lines = [_conflict_line(plan, c) for c in cs]
    if any(c.kind == "fn_heading" for c in cs):
        used = {s for c in cs for s in c.lost + [c.by]}
        others = [(s, plan.paras[s].text_only()) for s in plan.fn_guess_notes if s in plan.paras and s not in used]
        if others:
            lines.append(f"・ほかに、文字から注の見出しと推定される「注」だけの段落 {_para_samples(others)}があります。すべての「注」の"
                         "扱いを一緒に決めてから変換し直してください。")
    return head + "\n" + "\n".join(lines)


def _verdict_title(plan):
    """別の論文かの判定（pdfmatch.paper_verdict）に使った題目の段落（和文、なければ英文）の文字。なければ ""。"""
    for p in (plan.title or plan.title_en):
        t = shown_text(p.plain().replace(OBJECT_MARK, ""))
        if len(t) >= 6:
            return t
    return ""


LINE_SHOWN = 60       # 別の論文で止める文に出す PDF の誌名の行の長さ（巻・号・ページの範囲まで見える長さ）


def wrong_paper_text(plan, pc, docx_name: str, pdf_name: str, line: str = "") -> str:
    """docx と PDF が別の論文か、大きく違う版のとき（pdfmatch の verdict が wrong）に変換を中止する文（pipeline.WrongPaperError の文）。

    題目が PDF の最初の 2 ページに見つからず、段落の半分を超えて見つからないことと、PDF の 1 ページ目の誌名の行（line。pdfbiblio.PdfBiblio.line。
    読めなければ最初の 2 行）を示し、docx と PDF を選び直してやり直すよう案内する。Markdown ではない。画面の操作は目印 step() で書く。docx の文字は shorten_shown を通す。
    """
    title = shorten_shown(_verdict_title(plan))
    last = "".join(f"「{shorten_shown(x, LINE_SHOWN)}」" for x in ([line] if line else pc.first_lines))
    label = "PDF の 1 ページ目の誌名の行" if line else "PDF の 1 ページ目"
    return (f"docx（{docx_name}）の題目「{title}」が PDF（{pdf_name}）の最初の 2 ページに見つからず、docx の段落 {pc.verdict_counted} 件のうち "
            f"{pc.verdict_missing} 件が PDF に見つかりませんでした（XML とレポートは作っていません）。docx と PDF が同じ論文のものか、"
            f"docx が校正後の版かを確かめ、{step('files')}やり直してください。"
            + (f"\n{label}: {last}" if last else ""))


@dataclass
class Action:
    """利用者に知らせる 1 件（要対応・要確認・手順）。文面の欄が空なら、そこには出さない。

    top: レポートの冒頭の囲み（Markdown。複数行でもよい）。checklist: することの一覧（冒頭）の行。box_title・box_detail: Colab の枠（要対応は赤、
    要確認は黄、手順は青）の見出しと本文（画面の操作は目印 step() で書き、colab が画面ごとの語に置き換える。top・checklist はレポートの
    文なので目印を使わず、ノートブックと 1 画面版の両方の言い方を書く）。cli: コマンドラインの標準エラーに出す文（Colab の手順の
    番号ではなく、コマンドラインの指定で書く）。

    required・done・failed・progress は手順（level が STEP）だけが使う。required: 必須（残っていれば終了コード 1 で止める）か、
    推奨（止めない）か。done: 済んだ（枠は出さない）。failed: やってみて失敗した（枠の見出しを赤字で出す。終了コードは変えない）。
    progress: 進み具合の短い文（「あと 4 枚／全部で 7 枚」「回答待ち」など）。
    box_intro: box_detail の前半（今の状況の説明。手動モードの回答待ちの ai_finish だけが持つ。依頼文の枠〈colab.prompt_box〉が、
    手順の番号つきの案内の前にこれを出す）。
    """
    level: str
    key: str
    top: str = ""
    checklist: str = ""
    box_title: str = ""
    box_detail: str = ""
    box_intro: str = ""
    cli: str = ""
    required: bool = True
    done: bool = False
    failed: bool = False
    progress: str = ""


def blocking(acts) -> list:
    """ダウンロードの歯止め・終了コード 1 になる知らせ: 要対応と、残っている必須の手順（推奨の手順と済んだ手順は含まない）。"""
    return [a for a in acts if a.level == NEEDS_ACTION or (a.level == STEP and a.required and not a.done)]


def _fidelity_action(r):
    fid = r.fidelity
    if fid.ok and fid.final_ok:
        return None
    unreadable = fid.final_unreadable
    differs = not fid.ok or fid.final_differs
    if unreadable and differs:          # 読めないことと、文字の差分の両方（どちらも、この XML は登載に使わない）
        return Action(
            NEEDS_ACTION, "fidelity",
            top=("> **注意: 出力された XML を XML として読めませんでした（実体参照などの不備）。さらに、文字の不変性チェックも不合格で、"
                 "出力された XML の本文が docx と一致していません。** この XML は登載に使わず、変換レポートを添えて開発者に知らせて"
                 "ください（変換ツールの不具合の可能性があります。読めなかった理由と文字の差分は 5 章）。"),
            checklist=("- [ ] **出力された XML を XML として読めず、文字の不変性チェックも不合格**（5 章）: この XML は登載に使わない"
                       "（変換レポートを添えて開発者に知らせる）"),
            box_title="出力された XML を読めず、文字の不変性チェックも不合格です（この XML は登載に使わないでください）",
            box_detail=("出力された XML を、XML として読めませんでした（実体参照などの不備）。さらに、出力された XML の本文が docx と"
                        "一致していません。この XML は登載に使わず、変換レポートを添えて開発者に知らせてください（変換ツールの不具合の"
                        "可能性があります。読めなかった理由と文字の差分はレポートの 5 章にあります）。"),
            cli=("要対応: 出力された XML を XML として読めず（実体参照などの不備）、文字の不変性チェックも不合格です。出力された XML の"
                 "本文が docx と一致していないので、この XML は登載に使わないこと（レポートの冒頭と 5 章。変換ツールの不具合の可能性がある）"))
    if unreadable:                      # 文字は合っているが、最終出力を XML として読めない（実体参照などの不備）
        return Action(
            NEEDS_ACTION, "fidelity",
            top=("> **注意: 出力された XML を XML として読めませんでした（実体参照などの不備）。** 本文が docx と一致しているかを"
                 "確かめられないので、この XML は登載に使わず、変換レポートを添えて開発者に知らせてください（変換ツールの不具合の"
                 "可能性があります。読めなかった理由は 5 章）。"),
            checklist=("- [ ] **出力された XML を XML として読めない**（5 章）: この XML は登載に使わない"
                       "（変換レポートを添えて開発者に知らせる）"),
            box_title="出力された XML を XML として読めません（この XML は登載に使わないでください）",
            box_detail=("出力された XML を、XML として読めませんでした（実体参照などの不備）。本文が docx と一致しているかを確かめられない"
                        "ため、この XML は登載に使わず、変換レポートを添えて開発者に知らせてください（変換ツールの不具合の可能性が"
                        "あります。読めなかった理由はレポートの 5 章にあります）。"),
            cli=("要対応: 出力された XML を XML として読めませんでした（実体参照などの不備）。この XML は登載に使わないこと"
                 "（レポートの冒頭と 5 章。変換ツールの不具合の可能性がある）"))
    return Action(
        NEEDS_ACTION, "fidelity",
        top=("> **注意: 文字の不変性チェックが不合格です。** 出力された XML の本文が docx と一致していません。"
             "下の 5 章の差分を確認し、この XML は登載に使わないでください（変換ツールの不具合の可能性があります）。"),
        checklist=("- [ ] **文字の不変性チェックが不合格**（5 章）: この XML は登載に使わない（変換ツールの不具合の可能性がある。"
                   "変換レポートを添えて開発者に知らせる）"),
        box_title="文字の不変性チェックが不合格です（この XML は登載に使わないでください）",
        box_detail=("出力された XML の本文が docx と一致していません。変換ツールの不具合の可能性があります。レポートの 5 章の"
                    "差分を確認し、変換レポートを添えて開発者に知らせてください。"),
        cli=("要対応: 文字の不変性チェックが不合格です。出力された XML の本文が docx と一致していないので、この XML は登載に"
             "使わないこと（レポートの冒頭と 5 章。変換ツールの不具合の可能性がある）"))


def _supplement_action(r):
    """route pdf の補完の確かめ（fidelity.verify_supplement）が不合格のとき（要対応。不変性チェックと同じ並び）。"""
    sup, fx = getattr(r, "supplement", None), r.docx_fix
    if sup is None or sup.ok:
        return None
    name = fx.path.name if fx is not None else "補った docx"
    n = len(sup.problems)
    shown = list(sup.problems[:DTD_SHOWN])
    items = "\n".join(f"・{src}: 「{esc(old, 30)}」→「{esc(new, 30)}」（{why}）" for src, old, new, why in shown) + \
        (f"\n…ほか {n - DTD_SHOWN} 件" if n > DTD_SHOWN else "")
    return Action(
        NEEDS_ACTION, "supplement",
        top=(f"> **要対応: 出版版 PDF による補完の確かめが不合格です（13.4）。** 補った docx（{esc(name)}）に、表記を合わせたもの以外の変更があります"
             "（変換ツールの不具合の可能性があります）。この XML は登載に使わず、"
             "「docx から作る」で変換し直すか、変換レポートを添えて開発者に知らせてください。"),
        checklist=("- [ ] **補完の確かめが不合格**（13.4）: この XML は登載に使わない"
                   "（「docx から作る」で変換し直すか、開発者に知らせる）"),
        box_title="出版版 PDF による補完の確かめが不合格です（この XML は登載に使わないでください）",
        box_detail=(f"補った docx（{name}）に、表記を合わせたもの以外の変更があります。変換ツールの不具合の可能性が"
                    "あります。レポートの 13.4 を確認し、変換レポートを添えて開発者に知らせてください。" + (f"\n{items}" if items else "")),
        cli=("要対応: 出版版 PDF による補完の確かめが不合格です。補った docx に、組版の違いでない変更が"
             "あるので、この XML は登載に使わないこと（レポートの冒頭と 13.4。変換ツールの不具合の可能性がある）"))


DTD_SHOWN = 5       # 赤い枠とコマンドラインに並べる DTD のエラーの数（全件はレポートの 12 章）


DTD_PLACES_SHOWN = 3  # 赤い枠とコマンドラインに、同じエラーの場所を並べる数（全件はレポートの 12 章）
APP_TITLE_TOP = "引用文献などの後ろに、資料の見出しと思われる段落があります"      # 要確認 app_after_refs の見出し（レポートの冒頭）
APP_TITLE_BOX = "引用文献などの後ろに資料があるかもしれません"                      # 同じ要確認の Colab・1 画面版の枠の見出し
APP_RUN_TITLE_TOP = "引用文献の後ろに、資料の中身と思われる段落があります"        # 同じ要確認の、資料の見出しがなく年の読めない段落が続くときの見出し


def dtd_app_hint(title: str) -> str:
    """DTD の不合格が、引用文献の後ろの資料が原因の可能性があるときの直し方。title: 同じ原因の要確認の見出し（画面ごとに違う）。"""
    return ("引用文献などの後ろに資料があり、その中の数式などが引用文献の中に入ったことが原因の可能性があります（要確認の"
            f"「{title}」と同じ原因）。Word で資料を英文要旨の後ろ（論文の最後）に移して、変換し直してください。")


DTD_APP_HINT_CLI = "引用文献などの後ろの資料が原因の可能性がある。docx で資料を英文要旨の後ろに移して変換し直すこと。"


def _dtd_group_line(g, shown=DTD_PLACES_SHOWN) -> str:
    """同じ DTD エラーのまとまり 1 つの 1 行: 文（2 件以上なら件数）と、原因の場所（引用文献 B129（段落 d123「…」）など）。"""
    text = g.message + (f"（{g.count} 件）" if g.count > 1 else "")
    if g.places:
        more = f" ほか {len(g.places) - shown} 件" if len(g.places) > shown else ""
        text += "。場所: " + "、".join(g.places[:shown]) + more
    return text


def _dtd_app_hint(r) -> bool:
    """DTD の不合格が、引用文献の後ろの資料（要確認 app_after_refs）が原因の可能性があるか。

    資料の見出しと思われる段落があり、エラーの場所が引用文献（または場所が分からない）のとき。エラーがすべて引用文献の外
    （表など）と分かっているときは勧めない。
    """
    if not r.plan.app_after_refs:
        return False
    return any(not g.kinds or "ref" in g.kinds for g in group_errors(r.dtd_errors))


def _dtd_action(r):
    if r.dtd_valid:
        return None
    n = len(r.dtd_errors)
    groups = group_errors(r.dtd_errors)
    lines = [_dtd_group_line(g) for g in groups[:DTD_SHOWN]]
    rest = sum(g.count for g in groups[DTD_SHOWN:])
    if rest:
        lines.append(f"…ほか {rest} 件")
    places = groups[0].places if groups else []
    where = (f"エラーの場所は、たとえば{places[0]}{'ほか' if len(places) > 1 else ''}です（全件は 12 章）。" if places else "")
    hint = _dtd_app_hint(r)
    top_tail = where + (dtd_app_hint(APP_TITLE_TOP) if hint else "12 章のエラーを確認してください（変換ツールの不具合の可能性があります）。")
    box_tail = (dtd_app_hint(APP_TITLE_BOX) if hint else "変換ツールの不具合の可能性があります。レポートの 12 章のエラーを確認し、変換レポートを添えて"
                "開発者に知らせてください。")
    cli_tail = "。" + DTD_APP_HINT_CLI if hint else "（変換ツールの不具合の可能性がある）。"
    check_tail = ("引用文献などの後ろの資料を英文要旨の後ろに移して変換し直す（12 章に場所）" if hint else
                  "12 章のエラーを確かめる（変換ツールの不具合の可能性がある）")
    return Action(
        NEEDS_ACTION, "dtd",
        top=(f"> **要対応: J-STAGE 指定の DTD による検証が不合格です（{n} 件、12 章）。** この XML は J-STAGE にアップロード"
             f"できません。{top_tail}"),
        checklist=(f"- [ ] **DTD 検証が不合格**（12 章、{n} 件）: この XML は J-STAGE にアップロードできない。{check_tail}"),
        box_title=f"J-STAGE 指定の DTD による検証が不合格です（{n} 件。要対応）",
        box_detail=(f"この XML は J-STAGE にアップロードできません。{box_tail}\n" + "\n".join(f"・{e}" for e in lines)),
        cli=(f"要対応: J-STAGE 指定の DTD による検証が不合格です（{n} 件。レポートの冒頭と 12 章）。この XML は J-STAGE に"
             f"アップロードできない{cli_tail}\n" + "\n".join(f"  {e}" for e in lines)))


TABLE_SHAPE_WHY = ("行ごとの列の数がそろわない・縦の結合が見出し行や本文の行の外にはみ出すなど、docx の表と違う形で出力しました"
                   "（変換ツールの不具合の可能性があります）。")


def _table_shape_action(r):
    """出力した XML の表の形の崩れ（pipeline.table_problems）。なければ None。"""
    probs = r.table_problems
    if not probs:
        return None
    n = len(probs)
    lines = [(p.name, "、".join(p.problems)) for p in probs]
    names = "、".join(esc(name) for name, _ in lines)
    shown = lines[:DTD_SHOWN]
    rest = [f"…ほか {n - DTD_SHOWN} 件"] if n > DTD_SHOWN else []
    return Action(
        NEEDS_ACTION, "table_shape",
        top="\n".join([f"> **要対応: 出力した XML の表 {n} 件の形が崩れています（12 章）。** {TABLE_SHAPE_WHY}"
                       "この XML は登載に使わず、変換レポートを添えて開発者に知らせてください。", ">"]
                      + [f"> - {esc(name)}: {esc(what)}" for name, what in lines]),
        checklist=(f"- [ ] **表の形が崩れている {n} 件**（12 章）: この XML は登載に使わない（変換レポートを添えて開発者に"
                   f"知らせる）: {names}"),
        box_title=f"出力した XML の表の形が崩れています（{n} 件。この XML は登載に使わないでください）",
        box_detail=("docx の表と違う形（行ごとの列の数・縦の結合の範囲など）で出力しました。変換ツールの不具合の可能性があります。"
                    "レポートの 12 章を確認し、変換レポートを添えて開発者に知らせてください。\n"
                    + "\n".join([f"・{name}: {what}" for name, what in shown] + rest)),
        cli=(f"要対応: 出力した XML の表 {n} 件の形が崩れている（行ごとの列の数がそろわないなど。レポートの冒頭と 12 章。"
             "変換ツールの不具合の可能性がある）。この XML は登載に使わないこと。\n"
             + "\n".join([f"  {name}: {what}" for name, what in shown] + rest)))


TABLE_BODY_WHY = ("キャプションだけの表として XML に出ていて、表として組めていません（中身は、本文の段落やキャプションのない表として、"
                  "別の所に出ていることがあります）。表ごとの直し方のとおりに Word で直して、変換し直してください。")
TABLE_BODY_IMAGE = "表の画像をキャプションのすぐ後ろの段落に貼ってもかまいません（変換し直した後、画像はレポートの 9 章の置き場所に入れます）。"
FLOAT_TABLE_HOW = "Word で表のプロパティの文字列の折り返しを「なし」にし、このキャプションのすぐ後ろに移してください。"


def table_body_name(b) -> str:
    """本体のない表（model.BodylessTable）の知らせの名前: 「T2「表2　…」」（表キャプションの冒頭 20 字）。"""
    return f"{b.tid or '表'}「{shorten_shown(b.head, 20)}」"


def _candidate(c) -> str:
    tid, first, _ = c
    return f"{tid}（最初のセル「{shorten_shown(first, 15)}」）"


def table_body_why(b) -> str:
    """本体のない表 1 つの理由と直し方の文（要対応 table_body の 1 表 1 行と、3 章の「表の本体」の行の理由）。"""
    floats = [c for c in b.candidates if c[2]]
    if b.why == "caption_style":
        return ("キャプションが「図」で始まるのに表キャプションのスタイルです。図なら Word でこの段落を図キャプションのスタイルにして"
                "変換し直してください（図・表のキャプションのスタイルの取り違えは、要確認「スタイルを確かめてください」にも、本体の有無に関係なくすべて挙げています）。")
    if b.why == "same_number":
        ref = f"{b.why_ref}「{shorten_shown(b.why_ref_head, 20)}」" if b.why_ref_head else b.why_ref
        return (f"直前の表キャプション（{ref}）と同じ番号です（英文のキャプションなど）。同じ表のキャプションなら、Word で 2 つの"
                "キャプションを 1 つの段落にして（間の段落記号を消し、Shift+Enter の改行にする）変換し直してください。")
    if b.why == "next_caption":
        ref = f"{b.why_ref}「{shorten_shown(b.why_ref_head, 20)}」" if b.why_ref_head else b.why_ref
        out = (f"すぐ後ろに別の表キャプション（{ref}）があり、その後ろの表はそちらの表にしました。この表の本体がほかの所にあれば、"
               "Word でこのキャプションのすぐ後ろに移してください。")
        if floats:
            out += (f"この docx には、文字列の折り返しを「する」にした（浮動配置の）表があり、キャプションのない表 "
                    f"{'・'.join(_candidate(c) for c in floats)}として出ています。それがこの表なら、{FLOAT_TABLE_HOW}")
        return out
    if b.why == "floating":
        return (f"この docx には、文字列の折り返しを「する」にした（浮動配置の）表があり、キャプションのない表 "
                f"{'・'.join(_candidate(c) for c in floats)}として出ています。それがこの表なら、{FLOAT_TABLE_HOW}")
    out = ("キャプションの後ろに Word の表がありません（本文の段落・タブ・テキストボックスで書いた表は、表として組めません）。"
           "Word の表に作り直して、キャプションのすぐ後ろに置いてください（間に本文の段落を入れない）。" + TABLE_BODY_IMAGE)
    if b.candidates:
        out += (f"キャプションのない表 {'・'.join(_candidate(c) for c in b.candidates)}"
                f"{'のどれか' if len(b.candidates) > 1 else ''}がこの表かもしれません。")
    return out


def _table_body_action(r):
    """本体（Word の表・画像で貼った表）のない表（pipeline.bodyless_tables。C003 の表の側・C027）。なければ None。"""
    found = getattr(r, "bodyless_tables", None) or []
    if not found:
        return None
    n = len(found)
    lines = [(table_body_name(b), table_body_why(b)) for b in found]
    names = "、".join(esc(name) for name, _ in lines)
    return Action(
        NEEDS_ACTION, "table_body",
        top="\n".join([f"> **要対応: 表の本体（Word の表）が見つからない表が {n} つあります（3 章）。** {TABLE_BODY_WHY}", ">"]
                      + [f"> - {esc(name)}: {esc(why)}" for name, why in lines]),
        checklist=(f"- [ ] **表の本体が見つからない表 {n} つ**（3 章）: 表ごとの直し方のとおりに Word で直して変換し直す: {names}"),
        box_title=f"表の本体が見つからない表が {n} つあります（要対応）",
        box_detail=(f"{TABLE_BODY_WHY}変換し直すときは、Word で直した docx を{step('docx')}でアップロードし直し、そこから"
                    "順にやり直してください（レポートの冒頭と 3 章）。\n"
                    + "\n".join(f"・{name}: {why}" for name, why in lines)),
        cli=(f"要対応: 表の本体（Word の表）が見つからない表が {n} つ（キャプションだけの表として出ている。レポートの冒頭と 3 章）。"
             "表ごとの直し方のとおりに docx を直して変換し直すこと。\n"
             + "\n".join(f"  {name}: {why}" for name, why in lines)))


TABLE_PARTS_SHOWN = 5      # 要確認 table_parts の冒頭・枠・コマンドラインに、種類ごとに並べる行の数（全件はレポートの 3 章）
TABLE_PART_KINDS = ("split", "cell_table_cap_first", "cell_table_cap_mid", "cell_fig_cap")


def _first_cell(node) -> str:
    return next((shown_text(p.plain()) for p in (node.table.paragraphs() if node.table is not None else [])
                 if shown_text(p.plain())), "")


def table_part_rows(plan) -> list:
    """表の組み立てを確かめてもらう所（plan.table_parts。要確認 table_parts）を、1 か所 1 行の
    [(種類, 段落 ID, 本文の表記, 理由と直し方の文), …] にする（分かれた表は、連なりの最初の表ごとに 1 行。3 章の行と Action の行）。"""
    rows, split = [], {}
    for part in getattr(plan, "table_parts", []):
        if part.kind == "split":
            split.setdefault(id(part.head), (part.head, []))[1].append(part.node)
    for head, nodes in split.values():
        cap = shorten_shown(head.caption.plain(), 20) if head.caption is not None else ""
        tids = "・".join(n.tid for n in nodes)
        src = next((p.src for p in nodes[0].table.paragraphs()), head.caption.src if head.caption is not None else "")
        rows.append(("split", src, f"{tids}（最初のセル「{shorten_shown(_first_cell(nodes[0]), 15)}」）",
                     f"表 {head.tid}「{cap}」のすぐ後ろに、キャプションのない表 {tids} が続いています。1 つの表が分かれているなら、"
                     "Word で間の空の段落を消して表をつなぎ、変換し直してください（別の表ならそのままでかまいません）。"))
    slots = {id(s.caption): s for s in getattr(plan, "slots", []) if s.caption is not None}
    for part in getattr(plan, "table_parts", []):
        if part.kind == "split":
            continue
        text = shorten_shown(part.para.plain(), 20)
        if part.kind == "cell_fig_cap":
            m = RE_FIGCAP.match(nfkc(shown_text(part.para.plain())))
            slot = slots.get(id(part.para))
            keep = f"（図の画像の置き場所 {slot.key} はそのまま使えます）" if slot is not None and slot.key else ""
            why = (f"表 {part.node.tid} のセルに図キャプション「{text}」があります。図が表として出て、本文の「図{m.group(1) if m else ''}」に"
                   f"リンクされません。Word で、画像と図キャプションを表の外の段落に出して変換し直してください{keep}。")
        else:
            m = RE_TABCAP.match(nfkc(shown_text(part.para.plain())))
            if part.kind == "cell_table_cap_first":
                why = (f"表 {part.node.tid} の 1 行目のセルに表キャプション「{text}」があります。XML では表のキャプションにならず、"
                       f"本文の「表{m.group(1) if m else ''}」にリンクされません。Word で、その行を表の外（表のすぐ前の段落）に出し、"
                       "表キャプションのスタイルにして変換し直してください。")
            else:
                why = (f"表 {part.node.tid} の {part.row} 行目のセルに表キャプション「{text}」があります。2 つの表が 1 つに"
                       "つながっています。Word で、その行の前で表を分割し、キャプションの行を表の外に出して変換し直してください。")
        rows.append((part.kind, part.para.src, text, why))
    order = {k: i for i, k in enumerate(TABLE_PART_KINDS)}
    return sorted(rows, key=lambda row: order.get(row[0], len(order)))


TABLE_PARTS_REFS = ("セルの中のキャプションを表の外に出すと、本文の参照の「対応する表（図）が見つからない」（3 章）の行も、"
                    "この直しで消えます。")


def _table_parts_action(r):
    """分かれた表と、表のセルの中の図・表キャプション（plan.table_parts。C027 の (d)・C031。XML は docx の表のまま）。なければ None。"""
    rows = table_part_rows(r.plan)
    if not rows:
        return None
    n = len(rows)
    shown, rest = [], 0
    for kind in TABLE_PART_KINDS:
        mine = [row for row in rows if row[0] == kind]
        shown += mine[:TABLE_PARTS_SHOWN]
        rest += max(0, len(mine) - TABLE_PARTS_SHOWN)
    more = [f"ほか {rest} 件（3 章）"] if rest else []
    refs = TABLE_PARTS_REFS if any(row[0] != "split" for row in rows) else ""
    lines = [why for _, _, _, why in shown] + more
    # 見出しの種類は、出ている行の種類から作る（分かれた表／セルの中のキャプション／両方）。一覧の行とコマンドラインで共有する
    kinds = {row[0] for row in rows}
    cell_kinds = {k for k in kinds if k != "split"}
    label = "・".join((["分かれた表"] if "split" in kinds else []) + (["セルの中のキャプション"] if cell_kinds else []))
    became = "・".join((["表のキャプション"] if cell_kinds - {"cell_fig_cap"} else []) + (["図"] if "cell_fig_cap" in cell_kinds else []))
    how = (f"Word で直すと、{became}になり、本文からリンクされる" if cell_kinds
           else "1 つの表なら、Word で間の空の段落を消して表をつなぐ")
    return Action(
        TO_CHECK, "table_parts",
        top="\n".join([f"> **要確認: 表の組み立てを確かめてください（{n} か所。3 章）。** XML は docx の表のまま出しています。"
                       f"{TABLE_PARTS_AS_IS}{refs}", ">"]
                      + [f"> - {esc(line)}" for line in lines]),
        checklist=f"- [ ] **表の組み立ての確認 {n} か所**（3 章）: {label}。{how}",
        box_title="表の組み立てを確かめてください（要確認）",
        box_detail=(f"XML は docx の表のまま出しています（{n} か所。レポートの冒頭と 3 章）。{TABLE_PARTS_AS_IS}{refs}直すときは、"
                    f"Word で直した docx を{step('docx')}でアップロードし直し、そこから順にやり直してください。\n"
                    + "\n".join(f"・{line}" for line in lines)),
        cli=(f"要確認: 表の組み立てを確かめること（{n} か所。{label}。XML は docx の表のまま。登載はこのままでもできる。"
             "レポートの冒頭と 3 章）。直すなら docx を直して変換し直すこと。\n" + "\n".join(f"  {line}" for line in lines)))


TABLE_PARTS_AS_IS = "登載はこのままでもできます。"


def _upload_action(r):
    issues = upload_issues(r)
    if not issues:
        return None
    n = len(issues)
    ids = "、".join(dict.fromkeys(mid for mid, _ in issues))
    # 冒頭部の確かめと同じ原因の問題には、そちらを直すと消えることを添える（直し方を 2 通りに書かない）
    title_missing = any(f.kind == frontcheck.TITLE_MISSING for f in front_findings(r))
    no_authors = frontcheck.authors_missing_applies(r.plan, _front_lang(r))
    notes = {"EMSGM097E": UPLOAD_TITLE_NOTE if title_missing else "", "EMSGM233E/250E": UPLOAD_AUTHOR_NOTE if no_authors else ""}
    issues = [(mid, msg + notes.get(mid, "")) for mid, msg in issues]
    docx_only = all(notes.get(mid) for mid, _ in upload_issues(r))
    how_top = ("冒頭部の確かめの直し方のとおりに docx を直し、変換し直してください。" if docx_only else
               "12 章の内容を見て、書誌情報（巻・号・ページ・日付など）か docx を直し、変換し直してください。")
    how_box = (f"冒頭部の確かめの直し方のとおりに docx を直して{step('docx')}から、やり直してください（レポートの 12 章）。" if docx_only else
               f"書誌情報（巻・号・ページ・日付など）が原因なら{step('meta')}から、docx が原因なら docx を直して{step('docx')}から、"
               "やり直してください（レポートの 12 章）。")
    return Action(
        NEEDS_ACTION, "upload",
        top=(f"> **要対応: J-STAGE のアップロード時チェックで問題が {n} 件見つかりました（12 章）。** このままでは、J-STAGE に"
             f"アップロードするときに弾かれます。{how_top}\n>\n" + "\n".join(f"> - {esc(mid)}: {esc(msg)}" for mid, msg in issues)),
        checklist=(f"- [ ] **J-STAGE のアップロード時チェックの問題 {n} 件**（12 章）を、"
                   + ("冒頭部の確かめのとおりに docx を直して変換し直す: " if docx_only else "書誌情報か docx を直して変換し直す: ")
                   + esc(ids)),
        box_title=f"J-STAGE のアップロード時チェックで問題が {n} 件あります（要対応）",
        box_detail=("このままでは、J-STAGE にアップロードするときに弾かれます。" + how_box + "\n"
                    + "\n".join(f"・{mid}: {msg}" for mid, msg in issues)),
        cli=(f"要対応: J-STAGE のアップロード時チェックで問題が {n} 件あります（レポートの冒頭と 12 章）。このままでは"
             "アップロードのときに弾かれるので、"
             + ("冒頭部の確かめの直し方のとおりに docx を直して変換し直すこと。\n" if docx_only else
                "書誌情報（--meta）か docx を直して変換し直すこと。\n")
             + "\n".join(f"  {mid}: {msg}" for mid, msg in issues)))


# アップロード時チェックの問題のうち、冒頭部の確かめと同じ原因のものに添える文（_upload_action）
UPLOAD_TITLE_NOTE = "（冒頭部の確かめ〈題目の段落がない〉を直すと消えます）"
UPLOAD_AUTHOR_NOTE = "（和文の著者名が見つからないこと〈要対応「和文の著者名が見つかりません」〉を直すと消えるかもしれません）"


FLOAT_NAMES_SHOWN = 4      # float_names に並べる図・表の名前の数（残りは「ほか N 個」）


def float_names(plan, fids) -> str:
    """図形 fids の中身の図・表の名前（「図2・図5・表3」）。図・表の順に番号順で並べ、FLOAT_NAMES_SHOWN を超える分は「ほか N 個」。
    キャプションのないものは数でまとめる（「キャプションのない図 2 個」）。推奨の手順 ai_finish の文に使う（修正計画 W8 の 4.3）。"""
    from .structure import figure_rows
    want = set(fids)
    named, nocap = [], {}
    for row in figure_rows(plan):
        if row.float_id in want and row.node is not None:
            if row.label:
                if row.label not in [x[1] for x in named]:
                    m = re.search(r"(\d+)", unicodedata.normalize("NFKC", row.label))
                    named.append(((0 if row.kind != "table" else 1, int(m.group(1)) if m else 0), row.label))
            else:
                what = "キャプションのない表" if row.kind == "table" else "キャプションのない図"
                nocap[what] = nocap.get(what, 0) + 1
    names = [name for _, name in sorted(named, key=lambda x: x[0])]
    shown = names[:FLOAT_NAMES_SHOWN]
    rest = len(names) - len(shown)
    parts = shown + ([f"ほか {rest} 個"] if rest else []) + [f"{what} {k} 個" for what, k in nocap.items()]
    return "・".join(parts) or "キャプションのない図"


def float_phrase(plan, fids) -> str:
    """図形 fids の言い方（「図形 3 個（図1・図3・図4・図6）」。図形の数と、中の図・表の名前を分ける）。"""
    return f"図形 {len(fids)} 個（{float_names(plan, fids)}）"


def _float_left(plan) -> list:
    """AI に位置を聞いた図形のうち、AI の答えを採用していないもの（plan.asked_floats − plan.answered_floats。docx の順）。"""
    done = set(plan.answered_floats)
    return [fid for fid in plan.asked_floats if fid not in done]


def _boxes_answered(plan) -> list:
    """AI の答えで種類（囲みか図の注記か）を決めた、文字だけのテキストボックスの ID（BoxInfo.mode が ai）。"""
    return [x for x, info in plan.textboxes.items() if info.mode == "ai"]


AI_STATES = ("未実行", "回答待ち", "済み", "一部", "失敗")      # AI による仕上げの状態（ai_state。修正計画 W8 の 4.3）


def ai_state(r) -> str:
    """AI による仕上げの状態（AI_STATES のどれか。修正計画 W8 の 4.3）。

    未実行: AI を使わない。回答待ち: 手動モードで、回答をまだ反映していない。失敗: API の呼び出しに失敗した・回答を読めなかった
    （回答を 1 件も反映していない）。一部: 回答が途中で切れていて位置の一部だけを読んだか、聞いた図形（plan.asked_floats）・
    囲みか図の注記か決められないテキストボックスに、答えがない・採用しなかったものが残る。済み: どれでもない（AI が PDF を見たかは ai_done・pdf_unseen）。
    """
    ai, plan = r.ai, r.plan
    if ai.mode == "none":
        return "未実行"
    if ai.mode == "manual" and not ai.raw and not ai.error:
        return "回答待ち"
    if ai.error or not ai.raw:
        return "失敗"
    if ai.partial or _float_left(plan) or plan.undecided_boxes:
        return "一部"
    return "済み"


def pdf_unseen(r) -> bool:
    """AI に位置を聞いた図形（plan.asked_floats）か、PDF を見たときだけ AI の位置を使う 2 段にまたがる機械的な図形（plan.wide_floats）
    があるのに、AI が出版版 PDF を見て答えた回答ではないか（AIOutcome.pdf_seen が「見た」「見た（確かめられない）」でない。回答に pdf が
    なければ「添付なし」と同じ扱い）。どちらの図形もなければ偽（PDF を見ていなくても、リンクなどは決められる。修正計画 W8 の 4.3・4.4。
    2 段の図形だけの論文で、PDF を見ていない回答を知らせずに使い回さないよう、2 段の図形も数える。点検 review14 原則 1）。"""
    from .ai_assist import PDF_SEEN_OK
    return bool(r.plan.asked_floats or r.plan.wide_floats) and r.ai.pdf_seen not in PDF_SEEN_OK


def ai_done(r) -> bool:
    """AI による仕上げが済んだか（ai_state が「済み」で、位置を聞いた図形か 2 段にまたがる機械的な図形があれば AI が出版版 PDF を見て
    答えたこと〈pdf_unseen が偽〉。
    1 画面版の手動の欄を閉じる条件。修正計画 W8 の 4.3・4.4・4.5）。"""
    return ai_state(r) == "済み" and not pdf_unseen(r)


def ai_pdf(r) -> str:
    """AI が出版版 PDF を見て答えたかの表示（2 章の概要の表・結果の要約）。回答に pdf がなければ ""。
    AIOutcome.pdf_seen の語に、合わないときは理由（pdf_seen_note）を添える。"""
    ai = r.ai
    if not ai.pdf_seen:
        return ""
    return ai.pdf_seen + (f"。{esc(ai.pdf_seen_note)}" if ai.pdf_seen_note else "")


AI_METHOD_JA = {"none": "使わない", "manual": "手動（チャットに貼り付け）"}      # API は ai_method で作る


def ai_method(r) -> str:
    """AI による仕上げの方法の表示（レポートの 2 章の表・結果の要約）。API は「API（Claude）」のように使った AI の名前を付ける。"""
    ai = r.ai
    if ai.mode == "api":
        return f"API（{PROVIDERS.get(ai.provider, ai.provider)}）"
    return AI_METHOD_JA.get(ai.mode, ai.mode)


def ai_summary(r) -> str:
    """結果の要約（colab.summary_box）の「AI による仕上げ」の行: 方法・モデルと状態（ai_state）、AI が出版版 PDF を見たか（pdf_seen）。"""
    ai = r.ai
    model = f"（モデル: {ai.model}）" if ai.mode == "api" and ai.model else ""
    seen = f"。PDF: {ai.pdf_seen}" if ai.pdf_seen else ""
    return f"{ai_method(r)}{model}。状態: {ai_state(r)}{seen}"


AI_FINISH_TITLE = "AI で図・表の位置を合わせる"
AI_BOX_TITLE = "AI にテキストボックスの種類を判断させる"      # 位置を聞く図形がなく、決められないテキストボックスだけのとき
AI_STYLE_TITLE = "AI にスタイルの直し方を提案させる"            # 図形もテキストボックスもなく、機械が挙げたスタイルを確かめる段落だけのとき
AI_ANSWER_TITLE = "AI の回答を反映する"                      # 図形もテキストボックスもなく、失敗か一部のとき
AI_FAILED_TITLE = "AI の回答を反映できませんでした"
AI_PDF_TITLE = "AI に出版版 PDF を見せて、図・表の位置を合わせ直す"     # 回答で位置は決まったが、AI が出版版 PDF を見ていないとき
AI_CHOOSE_HOW = "（ノートブックは手順 4〜6、1 画面版は「AI による仕上げの方法」の欄、コマンドラインは --ai manual か --ai api）"
CUT_ASK = "「回答が途中で切れました。同じ形式で最初から出し直してください」"     # 途中で切れた回答の、出し直しの頼み方


def _ai_finish_action(r):
    """推奨の手順 ai_finish（AI による仕上げ。修正計画 W8 の 4.3）。出す条件に当たらなければ None（レポートの 2 章に 1 行だけ書く）。

    出す条件: AI に位置を聞く図形がある（plan.asked_floats）／PDF を見たときだけ AI の位置を使う 2 段にまたがる機械的な図形がある
    （plan.wide_floats。点検 review14 利用者向け 5）／囲みか図の注記か決められないテキストボックスがあるか、AI の答えで
    決めた／機械が挙げた、スタイルを確かめる段落がある（plan.style_suspects。英文要旨が見つからない要対応の段落は除く）／状態
    （ai_state）が「失敗」か「一部」。状態ごとに文を変え、済みなら done、失敗なら failed（枠の見出しを赤字）。残っていても
    失敗しても、needs_action は偽（推奨の手順）。位置は決まったが AI が出版版 PDF を見ていないとき（pdf_unseen）は、済みにせず
    PDF を添付して依頼し直す文（_ai_pdf_unseen_action）。
    """
    plan, ai = r.plan, r.ai
    state = ai_state(r)
    asked, left, boxes = plan.asked_floats, _float_left(plan), plan.undecided_boxes
    # 2 段にまたがる図形: wide は機械的な位置のままのもの（PDF を見せると移せる）、moved は AI の位置に移したもの（6.5 の 4）
    wide = [f for f in plan.wide_floats if plan.floats[f].mode == "mechanical"]
    moved = [f for f in plan.wide_floats if plan.floats[f].mode == "ai"]
    skip = set(abstract_missing_srcs(plan)) | front_reported_srcs(r)
    m = len({x.src for x in plan.style_suspects if x.src not in skip and x.kind not in STYLE_NO_AI_KINDS})
    if not (asked or plan.wide_floats or boxes or _boxes_answered(plan) or m or state in ("失敗", "一部")):
        return None
    manual = ai.mode == "manual"
    n, k = len(left), len(boxes)
    names = float_phrase(plan, left) if left else ""
    ends = [f for f in left if plan.floats[f].where == "end"]
    if ends and len(ends) == len(left):
        where = "本文の最後（結び付いている段落が本文の外にあるため）"
    elif ends:
        where = (f"結び付いている段落のすぐ後ろ（うち{float_phrase(plan, ends)}は、結び付いている段落が本文の外にあるので、"
                 "本文の最後）")
    else:
        where = "結び付いている段落のすぐ後ろ"
    # 見出し: 残っている図形があれば位置、なければ残っているテキストボックス、どちらもなければ（途中で切れた回答など）回答の反映
    if left or (asked and state == "済み") or plan.wide_floats:
        base = AI_FINISH_TITLE
    elif boxes or (_boxes_answered(plan) and state == "済み"):
        base = AI_BOX_TITLE
    elif m:
        base = AI_STYLE_TITLE
    else:
        base = AI_ANSWER_TITLE
    # 見出しに「推奨」を書かない（青い枠は「手順（推奨）: 」を前に付け、一覧の行は checklist_line が「（推奨）」を付けるので、重ねない。点検 review13 利用者向け 10）
    # 残りの数は位置を聞いた図形だけの数（数え方は変えない）。2 段にまたがる機械的な図形は、数に入れず文で添える（点検 review14 の残り 5）
    title = (f"{base}（残り {n} 個" + (f"。ほかに 2 段にまたがる図形 {len(wide)} 個" if wide else "") + "）") if left else base
    progress = state + (f"・残り {n} 個" if left else "")
    prompt = r.prompt_path.name if r.prompt_path else "AI依頼文.txt"
    # 位置を聞く図形・テキストボックスの説明（未実行・回答待ち）
    floats = (f"Word のテキストボックスなどの{names}は、本文のどこに出すかを原稿から決められないため、"
              f"{where}に置いています（出版版 PDF の位置とは数段落ずれていることがあります。置いた位置はレポートの 3 章）。"
              "AI に出版版 PDF を見せると、PDF と同じ位置に置けます。" if left else "")
    # 2 段にまたがる機械的な図形（PDF を見た回答のときだけ AI の位置を使う。点検 review14 利用者向け 4・5）
    # 位置を聞く図形（floats）もあるときは、PDF を見せる 1 文を floats に任せて重ねない（点検 review14 の残り 4）
    wide_text = (f"2 段にまたがる{float_phrase(plan, wide)}も、Word の配置から機械的に決めた位置に置いています（組版で移されていることが"
                 "あります）。" if wide and left else
                 f"2 段にまたがる{float_phrase(plan, wide)}は、Word の配置から機械的に決めた位置に置いています（組版で移されていることが"
                 "あります）。AI に出版版 PDF を見せると、出版版と同じ位置に移せます。" if wide else "")
    box_text = f"囲みか図の注記か決められないテキストボックス {k} 個の文字は、XML に出していません。" if boxes else ""
    style_text = f"スタイルを確かめる段落 {m} か所について、AI が Word での直し方を提案します。" if m else ""
    what = "と".join(([("図・表の位置")] if left or wide else []) + (["テキストボックスの種類"] if boxes else []))
    does = f"AI が{what}を決めます" if what else ("AI がスタイルの直し方を提案します" if m else "AI がリンクなどを決めます")
    short = "、".join(([f"{esc(names)}を、{where}に置いている（3 章）"] if left else [])
                     + ([f"2 段にまたがる{esc(float_phrase(plan, wide))}を、機械的に決めた位置に置いている（3 章）"] if wide else [])
                     + ([f"囲みか図の注記か決められないテキストボックス {k} 個の文字を XML に出していない（3 章）"] if boxes else [])
                     + ([f"スタイルを確かめる段落が {m} か所ある（2 章）"] if m else []))
    cli_head = "".join(([f"{names}は{where}に置いています（レポートの 3 章）。"] if left else []) + ([wide_text] if wide else [])
                       + ([box_text] if boxes else []) + ([f"スタイルを確かめる段落が {m} か所あります（レポートの 2 章）。"] if m else []))
    if state == "済み" and pdf_unseen(r):
        return _ai_pdf_unseen_action(r)
    if state == "済み":
        # 2 段にまたがる図形を AI の位置に移したときは、その数も添える（数え方〈asked〉は変えない。点検 review14 利用者向け 4）
        # 機械的な位置のまま残った 2 段の図形（PDF の位置と違うとして使わなかったなど。2 章に理由）も言う（点検 review14 の残り 1）。括弧は 1 つにする
        more = ("。ほかに、" + "、".join(([f"2 段にまたがる{float_phrase(plan, moved)}を PDF の位置に移した"] if moved else [])
                                       + ([f"2 段にまたがる{float_phrase(plan, wide)}は機械的な位置のまま"] if wide else []))) if (moved or wide) else ""
        return Action(STEP, "ai_finish", required=False, done=True, progress=state,
                      checklist=(f"- [x] AI が出版版 PDF を見て、図・表 {len(asked)} 個の位置を決めた（2 章・3 章{more}）" if asked
                                 else f"- [x] AI の回答を反映した（2 章{more}）"),
                      box_title=title)
    if state == "失敗":
        reason = (ai.error or "AI の回答が空でした").rstrip("。")
        if manual:
            again = f"回答のコードブロックの中身だけを{step('repaste')}てください。"
            todo = "回答のコードブロックの中身だけを貼り付け直して、変換し直す"
            cli_again = "回答のコードブロックの中身だけをファイルに保存し、--ai manual --ai-response で指定し直して変換し直すこと。"
        else:
            again = f"{step('convert_again')}してください（また失敗するときは、手動に切り替えます）。"
            todo = "2 章の理由を確かめて、もう一度変換する（また失敗するときは「手動（チャットに貼り付け）」に切り替える）"
            cli_again = "--ai api でもう一度実行すること（また失敗するときは --ai manual に切り替える）。"
        return Action(
            STEP, "ai_finish", required=False, failed=True, progress=state,
            checklist=f"- [ ] **{AI_FAILED_TITLE}**（2 章）: {todo}",
            box_title=AI_FAILED_TITLE, box_detail=f"{reason}。変換の結果は、AI を使わないときと同じです。{again}",
            cli=f"手順（推奨）: {AI_FAILED_TITLE}。{reason}。変換の結果は、AI を使わないときと同じです。{cli_again}")
    if state == "未実行":
        detail = (floats + wide_text + (box_text + "AI が種類を判断します。" if boxes else "") + style_text
                  + f"{step('ai_choose')}変換し直してください。このまま登載することもできます。")
        cli = (f"手順（推奨）: {base}。{cli_head}--ai manual か --ai api を指定して変換し直すと、{does}（--ai manual では、"
               "書き出した AI依頼文.txt をチャット〈claude.ai など〉に渡し、回答を保存して --ai-response で指定します）。"
               "このまま登載することもできます。")
        todo = ("AI に出版版 PDF を見せると、PDF と同じ位置に置ける" if (left or wide) and not boxes else f"AI を使うと、{what}を決められる" if what
                else "AI を使うと、スタイルの直し方の提案を受けられる" if m else "AI を使うと、リンクなどを補える")
        checklist = f"- [ ] {base}: {short}。{todo}{AI_CHOOSE_HOW}"
    elif state == "回答待ち":
        intro = floats + wide_text + (box_text + "AI が種類を判断します。" if boxes else "") + style_text
        # 位置を聞く図形か、2 段にまたがる機械的な図形があるときは、出版版 PDF を同じメッセージに添付して送る
        send = step("pdf_attach") if left or wide else ""
        detail = (intro + f"{step('prompt')}を AI（claude.ai などのチャット）に{send}送信し、返ってきた回答を{step('paste')}してください。"
                  "このまま登載することもできます。")
        cli_pdf = "出版版 PDF と一緒に" if left or wide else ""
        cli = (f"手順（推奨）: {base}。{cli_head}手動モードで、AI の回答をまだ反映していません。{prompt} を、{cli_pdf}チャット（claude.ai など）に"
               "送信し、返ってきた回答をファイルに保存して --ai manual --ai-response 回答のファイル を指定し、変換し直すと、"
               f"{does}。このまま登載することもできます。")
        pdf_with = "を、出版版 PDF を同じメッセージに添付して" if left or wide else "を"
        checklist = (f"- [ ] {base}（AI の回答をまだ反映していない）: {short}。{esc(prompt)} {pdf_with} AI に渡し、返ってきた回答を"
                     "貼り戻して変換し直す（ノートブックは手順 6 に貼り付ける、1 画面版は回答の欄に貼り付けて「反映」、"
                     "コマンドラインは --ai manual --ai-response 回答のファイル）")
    else:       # 一部
        parts = []
        if left:
            parts.append(f"AI の回答で位置が決まったのは {len(asked)} 個のうち {len(asked) - n} 個です。残りの{names}は、{where}に"
                         "置いたままです（理由はレポートの 2 章・3 章）。")
        if boxes:
            parts.append(f"囲みか図の注記か決められないテキストボックス {k} 個は、AI の回答でも種類が決まらず、文字を XML に出していません（3 章）。")
        if ai.partial:
            parts.append("AI の回答が途中で切れていました。" + ai.partial)
        plain = "".join(parts)
        if ai.partial and manual:
            again = (f"チャットで{CUT_ASK}と頼み、新しい回答を最初から最後まで{step('repaste')}てください（続きだけを貼り付けても読めません）。")
            cli_again = (f"チャットで{CUT_ASK}と頼み、新しい回答を最初から最後までファイルに保存して --ai manual --ai-response で"
                         "指定し直し、変換し直すと、すべてを反映できます（続きだけを保存しても読めません）。")
        elif ai.partial:
            again = f"{step('convert_again')}してください（また途中で切れるときは、手動に切り替えます）。"
            cli_again = "--ai api でもう一度実行すると、AI が出し直します（また途中で切れるときは --ai manual に切り替える）。"
        elif manual:
            ask = "・".join((["「位置を決める図・表」の図形"] if left else [])
                           + (["「囲みか図の注記か決められなかったテキストボックス」"] if boxes else []))
            again = (f"AI に出し直してもらうときは、チャットで「{ask}をすべて回答に書いて、依頼文の『回答の形』のとおりに"
                     f"出し直してください」と頼んで{step('repaste')}てください。")
            cli_again = "AI に出し直してもらった回答で変換し直すと、残りも合わせられます。"
        else:
            again = f"AI に出し直してもらうときは、{step('convert_again')}してください。"
            cli_again = "--ai api でもう一度実行すると、AI が出し直します（毎回同じ結果になるとは限りません）。"
        detail = plain + again + "このまま登載することもできます。"
        cli = f"手順（推奨）: {base}" + (f"（残り {n} 個）" if left else "") + f"。{plain}{cli_again}このまま登載することもできます。"
        todo = []
        if left:
            todo.append(f"AI の回答で位置が決まったのは {len(asked)} 個のうち {len(asked) - n} 個。出し直してもらった回答で、残りの位置を合わせられる")
        if boxes:
            todo.append(f"囲みか図の注記か決められないテキストボックス {k} 個が残る")
        if ai.partial:
            todo.append("AI の回答が途中で切れていた（2 章）。AI に出し直してもらい、もう一度変換する")
        checklist = f"- [ ] {base}: " + "。".join(todo)
    return Action(STEP, "ai_finish", required=False, progress=progress, checklist=checklist,
                  box_title=title, box_detail=detail, box_intro=intro if state == "回答待ち" else "", cli=cli)


def _ai_pdf_unseen_action(r):
    """推奨の手順 ai_finish の、AI の回答で位置は決まったが、AI が出版版 PDF を見ていない（添付なし・別の論文・ツールの確かめが合わない。
    AIOutcome.pdf_seen）とき（修正計画 W8 の 4.3・4.4）。位置は AI の答えのまま使い、PDF を添付して依頼し直す手順を残す。
    2 段にまたがる機械的な図形（plan.wide_floats）は機械的な位置のままなので、その数も書く（2 段の図形だけの論文も。点検 review14 原則 1）。
    一覧の行の直し方は、枠・コマンドラインと同じ分け方にする（API で PDF を渡したか・渡せなかった理由。点検 review14 利用者向け 3）。"""
    ai, plan = r.ai, r.plan
    asked = plan.asked_floats
    wide = [f for f in plan.wide_floats if plan.floats[f].mode == "mechanical"]
    n, seen = len(asked), ai.pdf_seen
    manual = ai.mode == "manual"
    # 位置を決めた図形の数と、機械的な位置のままの 2 段にまたがる図形（文の頭）
    done = f"AI の回答で図・表 {n} 個の位置を決めましたが" if n else "AI の回答を反映しましたが"
    wide_text = (f"2 段にまたがる{float_phrase(plan, wide)}は、AI が出版版 PDF を見た回答のときだけ AI の位置を使うので、機械的に"
                 "決めた位置のままです。" if wide else "")
    guess = "（位置は Word の配置からの推定です）" if n else ""
    if seen.startswith("合わない"):
        why = (f"AI は出版版 PDF を見たと答えましたが、{ai.pdf_seen_note}。別の論文の PDF を添付していないか確かめ、この論文の PDF を"
               "添付して依頼し直してください。")
    elif seen == "別の論文":
        why = "AI は、添付された出版版 PDF が別の論文だと答えました。この論文の PDF を添付して依頼し直してください。"
    else:
        why = f"出版版 PDF を見ていない回答でした{guess}。PDF を添付して依頼し直すと、PDF と同じ位置に置けます。"
    plain = f"{done}、{why}{wide_text}"
    todo = "PDF を添付して AI に依頼し直す"
    if manual:
        again = f"チャットで、PDF を添付して依頼文を送り直し、返ってきた回答を{step('repaste')}てください。"
        cli_again = "チャットで、出版版 PDF を添付して AI依頼文.txt を送り直し、返ってきた回答を保存して --ai manual --ai-response で指定し、変換し直すこと。"
    elif ai.pdf_sent:
        # PDF を渡したのに見ていない回答は AI回答.json に写さない（pipeline.convert）ので、もう一度変換すると AI を呼び直す（点検 review13 利用者向け 1）
        if not (seen.startswith("合わない") or seen == "別の論文"):
            plain = f"{done}、出版版 PDF は AI に渡したのに、PDF を見ていない回答でした{guess}。{wide_text}"
        # 「…してください」に続ける（1 画面版の語は「押」で終わるので、「すると」に続けない。点検 review14 利用者向け 1）
        again = f"{step('convert_again')}してください。前の回答を使わずに AI を呼び直します（料金がかかります）。"
        cli_again = "--ai api でもう一度実行すると、前の回答を使わずに AI を呼び直す（料金がかかる）。"
        todo = "もう一度変換して、AI を呼び直す（前の回答は使わない。料金がかかる）"
    else:
        # PDF を渡せなかった: もう一度実行しても同じなので、渡せなかった理由に合わせて直し方を書く
        from .ai_assist import PDF_NONE_MSG, PDF_OFF_MSG
        plain = f"{done}、出版版 PDF を AI に渡せませんでした（{ai.pdf_note or '理由は 2 章'}）。{wide_text}"
        if ai.pdf_note == PDF_NONE_MSG:
            again = f"{step('pdf')}で出版版 PDF を指定して、{step('convert_again')}してください。"
            cli_again = "--pdf で出版版 PDF を指定して、--ai api でもう一度実行すること。"
            todo = "出版版 PDF を指定して、もう一度変換する"
        elif ai.pdf_note == PDF_OFF_MSG:
            again = f"出版版 PDF を渡す設定にして、{step('convert_again')}してください。"
            cli_again = "--ai-no-pdf を外して、--ai api でもう一度実行すること。"
            todo = "出版版 PDF を渡す設定にして、もう一度変換する"
        else:
            again = ("理由を確かめて PDF を直すか、手動（チャットに貼り付け）に切り替えて、依頼文と出版版 PDF をチャットに渡してください。")
            cli_again = "理由を確かめて PDF を直すか、--ai manual に切り替えて、AI依頼文.txt と出版版 PDF をチャットに渡すこと。"
            todo = "理由を確かめて PDF を直すか、手動（チャットに貼り付け）に切り替えて、依頼文と出版版 PDF をチャットに渡す"
    head = f"AI の回答で図・表 {n} 個の位置を決めたが" if n else "AI の回答を反映したが"
    also = f"。2 段にまたがる{esc(float_phrase(plan, wide))}は機械的な位置のまま" if wide else ""     # 括弧は 1 つにする（点検 review14 の残り 6）
    return Action(
        STEP, "ai_finish", required=False, progress=f"済み・PDF {seen or '添付なし'}",
        checklist=(f"- [ ] {AI_PDF_TITLE}: {head}、AI が出版版 PDF を見ていない"
                   f"（{seen or '添付なし'}。2 章{also}）。{todo}"),
        box_title=AI_PDF_TITLE, box_detail=plain + again + "このまま登載することもできます。",
        cli=f"手順（推奨）: {AI_PDF_TITLE}。{plain}{cli_again}このまま登載することもできます。")


def _float_end_action(r):
    """要確認 float_end: 結び付いた段落が本文の外なので、本文の最後に置いた図・表（修正計画 W8 の 4.3）。なければ None。

    結び付いた段落が本文の外の図形（end_why が anchor）と、AI が本文より後ろにあると答えた図形（end_why が ai。行に AI の答えを
    添える。W8 の手順 11）。引用文献などの後ろの資料の要確認（app_after_refs）が出る原稿では出さない（直し方が同じなので重ねない。
    図の位置は 3 章に出る）。
    """
    from .structure import OUTSIDE_JA, figure_rows
    plan = r.plan
    fids = [fid for fid in plan.unplaced_floats if plan.floats[fid].end_why in ("anchor", "ai")]
    if not fids or plan.app_after_refs:
        return None
    rows = figure_rows(plan)
    lines = []
    for fid in fids:
        info = plan.floats[fid]
        caps = [row for row in rows if row.float_id == fid and row.caption is not None]
        if caps:
            name = "・".join(f"「{esc(row.caption.plain().strip(), 20)}」" for row in caps)
        else:
            text = next((q.plain().strip() for q in info.paras if q.plain().strip()), "")
            name = f"キャプションのない図（「{esc(text, 20)}」）" if text else f"キャプションのない図（図形 {fid}）"
        if info.end_why == "ai":
            lines.append(f"{name} — AI の答え: {_float_end_answer(plan, info)}")
            continue
        region = OUTSIDE_JA.get(plan.region.get(info.float.anchor_src, ""), "本文の外")
        lines.append(f"{name} — {region}の段落に結び付いています")
    n = len(fids)
    how = ("Word で、引用文献・注などの本文の外の段落に結び付いている図・表は、XML では本文の最後に置いています。資料の図なら、"
           + APP_MOVE_HOW + "本文の図・表なら、Word でその図形を、図について述べている本文の段落の近くに移して、変換し直してください。")
    title = f"本文の最後に置いた図・表が {n} 個あります"
    return Action(
        TO_CHECK, "float_end",
        top=f"> **要確認: {title}（3 章）。** {how}" + "".join(f"\n>\n> - {esc(x)}" for x in lines),
        checklist=f"- [ ] **本文の最後に置いた図・表**（{n} 個。3 章）: 資料の図なら資料を英文要旨の後ろに、本文の図なら図形を本文の段落の近くに、Word で移して変換し直す",
        box_title=title + "（要確認）", box_detail=how + "".join("\n・" + x for x in lines),
        cli=f"要確認: {title}（レポートの冒頭と 3 章）。{how}" + "".join("\n  " + x for x in lines))


def _float_end_answer(plan, info) -> str:
    """要確認 float_end の行の「AI の答え」（AI が本文より後ろと答えた図形。end_why が ai）。after が "" なら根拠（reason）、本文の外の
    段落を指定したなら、その領域。"""
    from .structure import OUTSIDE_JA
    if info.end_after:
        return f"{OUTSIDE_JA.get(plan.region.get(info.end_after, ''), '本文の外')}の段落の後ろにあります"
    reason = ai_text(info.end_reason).strip().rstrip("。")
    return reason[:40] + ("…" if len(reason) > 40 else "") if reason else "本文より後ろにあります"


# 機械が挙げたスタイルを確かめる段落（article.StyleSuspect）の種類ごとの、決まった見立てと一般の直し方（AI を使っていないとき、
# AI の提案がないときに使う。要確認 style_check。修正計画 W8 の 4.3）
STYLE_SUSPECT_JA = {
    "heading_body": ("見出しのスタイルの段落に本文が続いています",
                     "見出しと本文の間で Enter を押して段落を分け（改行〈Shift+Enter〉があれば、それを消してから）、後ろを本文のスタイルにする"),
    "heading_level": ("見出しのスタイルの階層が、同じ番号の形の見出しと食い違っています",
                      "同じ番号の形の見出し（兄弟）と同じ階層の見出しのスタイルにする"),
    "quote_like": ("本文のスタイルですが、引用の形をしています", "引用なら、ブロック引用のスタイルにする"),
    "heading_guess": ("見出しのスタイルがなく、文字の形から見出しと推定しました",
                      "見出しなら見出しのスタイル（「章見出し」など）を、本文の番号つきの箇条なら「本文」のスタイルを付ける"),
    "ref_symbol": ("記号だけの段落が、引用文献の 1 件として XML に出ます", "文献でなければ、Word でこの段落を消す"),
    "back_heading": ("付記・謝辞・引用文献の見出しの形ですが、本文の段落として出力しています",
                     "付記・謝辞なら、見出しの段落を「付記見出し」「謝辞見出し」のスタイルにする（見出しと本文が 1 つの段落なら、"
                     "見出しの後ろで Enter を押して分け、後ろを本文のスタイルにする）"),
    "ref_cont": ("前の文献の続きの疑いがあります（年が読めず、別の文献として出力しています）",
                 "前の文献の続きなら、Word で前の段落の終わりの段落記号を消して 1 つの段落にする"),
    "caption_kind": ("図・表のキャプションのスタイルと、キャプションの番号の頭（図・表）が食い違っています",
                     "キャプションの番号の頭に合わせて、Word でこの段落を図キャプション（「図」「Figure」の頭）か表キャプション"
                     "（「表」「Table」の頭）のスタイルにする"),
    "en_in_body": ("本文の途中に、英文の部分のスタイルの段落があります。本文として出しました",
                   "本文なら Word で本文のスタイルに直す。英文要旨などなら、引用文献より後ろに移して（英文の部分は論文の最後）"),
}
# 機械が挙げても、AI の提案を待たずに直し方が決まっている種類（推奨の手順 ai_finish を出す条件に数えない）
# （heading_level・heading_guess は、どちらの階層・見出しかを出版版 PDF を見て決められるので、heading_body と同じく AI の提案を待つ種類。
#  C038・C077。直し方が機械的に決まる ref_symbol・back_heading・ref_cont・caption_kind だけが待たない。caption_kind は番号の頭の文字で
#  図か表かが決まり〈docx の文字は変えない〉、PDF を見ても直し方は変わらない。C034）
STYLE_NO_AI_KINDS = ("ref_symbol", "back_heading", "ref_cont", "caption_kind", "en_in_body")
STYLE_CHECK_SHOWN = 10      # 要確認 style_check に並べる段落の数（残りは「ほか N か所（2 章）」）
# AI の回答は段落の役割（謝辞・引用・見出しの階層など）を XML に反映しない（所有者の決定 5）ので、Word での直し方を具体的に書く（点検 review13 回帰 1）
STYLE_CHECK_HOW = ("見出しや引用・謝辞のスタイルが違うと、J-STAGE の全文で章立てや引用・謝辞の形が変わります。違っていれば、Word でその段落を選び、［ホーム］の"
                   "スタイルの一覧から正しいスタイル（「節見出し」「ブロック引用」「謝辞見出し」など。下の行の提案）を選んで保存し、"
                   "変換し直してください。行の直し方が段落をつなぐ・分けるものなら、その行の直し方のとおりに Word で直して保存し、"
                   "変換し直してください。")
# 行に AI の提案（AIOutcome.style_fixes）があるときだけ STYLE_CHECK_HOW の前に添える文（AI を使っていない変換では言わない。
# 点検 review19 の 3 回目の利用者向け 5）
STYLE_CHECK_AI_NOTE = "AI の提案は、XML には反映していません（AI の回答を入れても、この段落は今の形のまま出ます）。"
STYLE_KEEP = "このまま"      # StyleFix.verdict の「このままでよい」（もう 1 つは「直す」）
STYLE_SHOWN_CONFIDENCE = ("高", "中")     # AI だけが見つけた提案のうち、要確認 style_check に載せる確度（低は 2 章だけ）


def _style_fix_of(ai) -> dict:
    """AI のスタイルの提案（AIOutcome.style_fixes）を段落 ID ごとに 1 件（同じ段落の 2 件目は使わない。修正計画 W8 の 4.2）。"""
    out = {}
    for f in getattr(ai, "style_fixes", None) or []:
        out.setdefault(f.src, f)
    return out


def ai_text(s) -> str:
    """知らせに入れる AI の文（根拠など）: 画面の操作の目印の文字（STEP_MARK）を除き、改行・タブを esc と同じ見える印にする
    （AI の文が画面の案内や偽の行に化けないように。回答を読むときにも ai_assist.strip_controls が制御文字を除いている）。"""
    return esc(("" if s is None else str(s)).replace(STEP_MARK, ""))


def _ai_style_text(f) -> str:
    """AI のスタイルの提案 1 件の文（「AI の提案: …（確度 高。理由）」か「AI の見立て: このままでよい（理由）」）。"""
    reason = ai_text(f.reason).strip().rstrip("。")
    if f.verdict == STYLE_KEEP:
        return "AI の見立て: このままでよい" + (f"（{reason}）" if reason else "")
    note = "。".join(x for x in ((f"確度 {f.confidence}" if f.confidence else ""), reason) if x)
    return f"AI の提案: {f.how}" + (f"（{note}）" if note else "")


def _style_ref(plan, src) -> str:
    """要確認 style_check の行の段落の指し方: 段落の ID（場所）「文字の先頭」。文字は 2 章の表と同じ _head（画像・数式の位置の文字を含めない）。"""
    place = _place_short(plan.locations.get(src, ""))
    head = _head(plan.paras.get(src), 15)
    return f"{src}{'（' + esc(place) + '）' if place else ''}" + (f"「{esc(head)}」" if head else "")


def _place_short(place) -> str:
    """場所の見出しの文字のうち、改行（見出しの段落の中の Shift+Enter）から後ろを「…」にする（見出しと本文が 1 段落のとき、場所に本文の
    書き出しまで入らないように。heading_body）。表示だけで、plan.locations は変えない。"""
    out = []
    for seg in place.split(" > "):
        if "\n" in seg:
            tail = "（見出し）" if seg.endswith("（見出し）") else ""
            seg = seg.split("\n")[0].rstrip() + "…" + tail
        out.append(seg)
    return " > ".join(out)


def _loose_back_note(plan, src) -> str:
    """要確認 style_check の AI だけの提案の行に添える文: 機械が文字から後付けの見出しと推定した段落（plan.loose_back。C032）なら、
    XML ではもうそのように出力していること（AI の提案は「XML に反映していない」が、この段落は今の形のまま正しく出る）。"""
    kind = plan.loose_back.get(src)
    if not kind:
        return ""
    return (f"機械が文字から{BACK_KIND_JA[kind]}の見出しと推定し、XML ではそのように出力しています。"
            "Word のスタイルだけ直してください。")


def style_check_rows(r) -> tuple:
    """要確認 style_check の行（段落ごとに 1 行。段落の順）と、2 章だけに書く AI の提案（確度 低・機械が挙げていない段落の「このまま」）。

    行に載せるのは、機械が挙げた段落（plan.style_suspects。AI の提案があれば同じ行に添え、「このまま」でも行は消さない）と、AI だけが
    見つけた提案のうち確度が高・中の「直す」もの。英文要旨が見つからない要対応（abstract_missing）の対象の段落は載せない（同じことを
    2 つの知らせで言わない）。戻り値は (行の一覧〈(段落 ID, 文)〉, 2 章だけの提案〈StyleFix〉)。修正計画 W8 の 4.3。
    """
    plan = r.plan
    skip = set(abstract_missing_srcs(plan)) | front_reported_srcs(r)        # 要対応の側（authors_missing・front_check）で知らせる段落は載せない
    fixes = _style_fix_of(r.ai)
    order = {src: i for i, src in enumerate(plan.paras)}
    rows, seen = [], set()
    for sus in plan.style_suspects:
        if sus.src in skip or sus.src in seen:
            continue
        seen.add(sus.src)
        what, how = STYLE_SUSPECT_JA.get(sus.kind, ("スタイルを確かめてください", ""))
        how = sus.how or how            # 段落ごとの直し方（StyleSuspect.how）があれば、一般の直し方の代わりに使う
        if sus.kind == "back_heading":
            how = _back_heading_how(r, sus) or how
        f = fixes.get(sus.src)
        tail = _ai_style_text(f) if f is not None else (f"直し方: {how}" if how else "")
        rows.append((sus.src, f"{_style_ref(plan, sus.src)}: {sus.detail or what}。" + (tail + "。" if tail else "")))
    only = []
    for src, f in fixes.items():
        if src in seen or src in skip:
            continue
        if f.verdict != STYLE_KEEP and f.confidence in STYLE_SHOWN_CONFIDENCE:
            rows.append((src, f"{_style_ref(plan, src)}: {_ai_style_text(f)}。" + _loose_back_note(plan, src)))
        else:
            only.append(f)
    rows.sort(key=lambda x: order.get(x[0], len(order)))
    return rows, only


def _back_heading_how(r, sus) -> str:
    """要確認 style_check の back_heading の直し方を、見出しの種類（付記・謝辞・引用文献）で出し分ける。同じ種類の見出しの形の段落が
    ほかにも挙がっていれば（structure.Classifier.loose_back_headings の (g2) で受け入れなかった候補）、どちらか一方だけを見出しの
    スタイルにする、と添える。見出しと本文が 1 つの段落の形（back_heading_inline）と、種類が読めないときは ""（決まった文を使う）。"""
    from .structure import back_heading_inline, loose_back_heading
    plan = r.plan
    p = plan.paras.get(sus.src)
    if p is None:
        return ""
    text = p.text_only()
    if back_heading_inline(text):
        return ""
    kind = loose_back_heading(text)
    if kind is None:
        return ""
    name = BACK_KIND_JA[kind]
    style = _first_style(r.journal, kind, BACK_HEADING_STYLE_DEFAULT.get(kind, ""))
    twins = [x.src for x in plan.style_suspects if x.kind == "back_heading" and x.src != sus.src and x.src in plan.paras
             and not back_heading_inline(plan.paras[x.src].text_only())
             and loose_back_heading(plan.paras[x.src].text_only()) == kind]
    how = f"{name}の見出しなら、見出しの段落を「{style}」のスタイルにする"
    if twins:
        how += f"（{name}の見出しの形の段落 {'・'.join(dict.fromkeys(twins))} もあるので、どちらか一方だけを見出しのスタイルにする）"
    return how


# back_heading の直し方に書く、後付けの見出しのスタイルの名前（雑誌の設定にないときの既定）
BACK_HEADING_STYLE_DEFAULT = {"ref_heading": "参考文献見出し", "ack_heading": "謝辞見出し", "notes_heading": "付記見出し"}


def _style_check_action(r):
    """要確認 style_check: スタイルを確かめる段落（機械の検出〈plan.style_suspects〉と AI の提案〈AIOutcome.style_fixes〉を 1 つに。
    段落ごとに 1 行、先頭 STYLE_CHECK_SHOWN 行まで。残りは 2 章）。なければ None。XML は変えない（直すのは Word。修正計画 W8 の 4.3）。"""
    rows, _ = style_check_rows(r)
    if not rows:
        return None
    n = len(rows)
    machine = any(s.src in {src for src, _ in rows} for s in r.plan.style_suspects)
    title = (f"スタイルを確かめてください（{n} か所）" if machine
             else f"AI がスタイルの誤りを見つけました（{n} か所）。確かめてください")
    lines = [text for _, text in rows[:STYLE_CHECK_SHOWN]]
    more = f"ほか {n - STYLE_CHECK_SHOWN} か所（2 章）" if n > STYLE_CHECK_SHOWN else ""
    shown = {src for src, _ in rows}
    joins = "（段落のつなぎ・分けを含む）" if any(
        s.kind in ("ref_cont", "heading_body") and s.src in shown for s in r.plan.style_suspects) else ""
    with_ai = bool(shown & set(_style_fix_of(r.ai)))        # 行に AI の提案がある
    how = (STYLE_CHECK_AI_NOTE if with_ai else "") + STYLE_CHECK_HOW
    return Action(
        TO_CHECK, "style_check",
        top=(f"> **要確認: {title}（2 章）。** {how}" + "".join(f"\n>\n> - {esc(x)}" for x in lines)
             + (f"\n>\n> - {more}" if more else "")),
        checklist=f"- [ ] **スタイルを確かめる段落**（{n} か所。2 章）: 違っていれば Word でスタイル{joins}を直して変換し直す",
        box_title=title + "（要確認）",
        box_detail=how + "".join("\n・" + x for x in lines) + (f"\n・{more}" if more else ""),
        cli=(f"要確認: {title}（レポートの冒頭と 2 章）。違っていれば、docx でスタイル{joins}を直して変換し直すこと"
             + ("（AI の提案は XML に反映していない）" if with_ai else "") + "。"
             + "".join("\n  " + x for x in lines) + (f"\n  {more}" if more else "")))


NOTE_BOUNDARY_KINDS = ("注の始まり", "注の続き")      # ai_assist.BOUNDARY_KINDS のうち注の区切りの直し（ほかは資料の始まり）
BOUNDARY_LINE_JA = {
    "注の始まり": "注の一覧の{head}の段落を、新しい注の始まりにしました",
    "注の続き": "注の一覧の{head}の段落を、前の注の続きにしました",
    "資料の見出し": "英文の部分の{head}の段落から後ろを、資料にしました",
    "英文要旨の続き": "英文の部分の{head}の段落からの資料を取り消し、英文要旨の続きにしました",
    "資料の本文": "英文の部分の{head}の段落を、資料の見出しではなく、前の資料の続きにしました",
}
# 「資料の本文」にした段落の前に続ける資料がなく、見出しのない資料（XML の資料の見出しが空）になったときの文（点検 review13 原則 3）
APP_NO_TITLE_LINE = ("英文の部分の{head}の段落を、資料の見出しではなく資料の本文にしました。前に続ける資料がないので、"
                     "見出しのない資料になりました（XML の資料の見出しは空です）")
NOTE_BOUNDARY_HOW = ("注の数と、本文の注番号のリンク先を、出版版 PDF と見比べてください。違っていれば、Word で注の番号を「2)」の形に直して"
                     "保存し、AI の回答を入れずに変換し直してください（AI の回答を入れなければ、元の区切りに戻ります）。")
APP_BOUNDARY_HOW = ("英文要旨の終わりと資料の始まりを、出版版 PDF と見比べてください。違っていれば、Word で資料を英文要旨の後ろの"
                    "セクションに分けて保存し、変換し直してください。")


def boundary_text(plan, b) -> str:
    """AI の回答で反映した注の区切り・資料の始まりの直し（ai_assist.Boundary）1 件の、何を直したかの文（根拠と確度は付けない）。"""
    head = f"「{esc(_head(plan.paras.get(b.src), 15))}」"
    if b.kind == "資料の本文" and b.src in titleless_app_starts(plan):
        return APP_NO_TITLE_LINE.format(head=head)
    return BOUNDARY_LINE_JA.get(b.kind, "{head}の段落の区切りを直しました").format(head=head)


def titleless_app_starts(plan) -> set:
    """見出しのない資料（AppNode.title が None）の、最初の段落の ID の集合。"""
    from .structure import Classifier
    return {q.src for a in plan.apps if a.title is None and a.children
            for q in Classifier.node_paras(a.children[0])[:1]}


def boundary_line(plan, b) -> str:
    """boundary_text に AI の根拠と確度を添えた文（要確認 ai_boundary の行）。"""
    text = boundary_text(plan, b)
    reason = ai_text(b.reason).strip().rstrip("。")
    note = "。".join(x for x in ((f"AI の根拠: {reason}" if reason else ""), (f"確度 {ai_text(b.confidence)}" if b.confidence else ""))
                     if x)
    return text + (f"（{note}）" if note else "")


def _ai_boundary_action(r):
    """要確認 ai_boundary: AI の回答で注の区切り・資料の始まりを直した（AIOutcome.boundaries。直した段落ごとに 1 行）。なければ None。

    XML は AI の回答で変わっているので、出版版 PDF と見比べてもらう。直し方は、注は Word で注の番号を直す（AI の回答を入れなければ
    元の区切りに戻る）、資料は Word で資料を英文要旨の後ろのセクションに分ける（修正計画 W8 の 4.3）。
    """
    plan = r.plan
    bs = list(getattr(r.ai, "boundaries", None) or [])
    if not bs:
        return None
    n = len(bs)
    notes = any(b.kind in NOTE_BOUNDARY_KINDS for b in bs)
    apps = any(b.kind not in NOTE_BOUNDARY_KINDS for b in bs)
    what = "と".join((["注の区切り"] if notes else []) + (["資料の始まり"] if apps else []))
    title = f"AI の回答で、{what}を直しました（{n} か所）。確かめてください"
    how = (NOTE_BOUNDARY_HOW if notes else "") + (APP_BOUNDARY_HOW if apps else "")
    lines = [boundary_line(plan, b) for b in bs]
    return Action(
        TO_CHECK, "ai_boundary",
        top=f"> **要確認: {title}（2 章）。** {how}" + "".join(f"\n>\n> - {x}" for x in lines),
        checklist=f"- [ ] **AI の回答で直した{what}**（{n} か所。2 章）: 出版版 PDF と見比べ、違っていれば Word で直して変換し直す",
        box_title=title + "（要確認）",
        box_detail="".join(x + "\n" for x in ["・" + y for y in lines]) + how,
        cli=f"要確認: {title}（レポートの冒頭と 2 章）。{how}" + "".join("\n  " + x for x in lines))


CARRIED_HOW = ("Word で原稿を直した後の変換に、直す前の依頼文への回答を入れました。段落の先頭の文字で確かめられなかった指定は"
               "使っていません（2 章の「検証で採用しなかった提案」）。すべての指定を使うには、今の依頼文で AI に依頼し直してください。")


def _ai_carried_action(r):
    """要確認 ai_carried: 原稿を直す前の依頼文への回答を使った（AIOutcome.carried。ai_assist.check_answer の (b)）。なければ None。

    段落の先頭の文字で確かめられなかった指定（head のないものなど）は不採用になり、区切り・リンクが黙って減りうるので、2 章の文だけに
    せず知らせる（点検 review13 原則 6）。
    """
    carried = getattr(r.ai, "carried", "")
    if not carried:
        return None
    title = "原稿を直す前の AI の回答を使いました。確かめてください"
    return Action(
        TO_CHECK, "ai_carried",
        top=f"> **要確認: {title}（2 章）。** {esc(carried)}{CARRIED_HOW}",
        checklist="- [ ] **原稿を直す前の AI の回答**（2 章）: 使わなかった指定を確かめ、必要なら今の依頼文で AI に依頼し直す",
        box_title=title + "（要確認）", box_detail=carried + CARRIED_HOW,
        cli=f"要確認: {title}（レポートの冒頭と 2 章）。{carried}{CARRIED_HOW}")


def _with_reused(fin, r):
    """推奨の手順 ai_finish の枠とコマンドラインの文に、前の変換の回答（AI回答.json）を使って AI を呼ばなかったこと（AIOutcome.reused）を
    添える（済んだ手順は枠を出さないので添えない。点検 review13 原則 6）。"""
    reused = getattr(r.ai, "reused", "")
    if fin is None or fin.done or not reused:
        return fin
    fin.box_detail = (fin.box_detail + reused) if fin.box_detail else fin.box_detail
    fin.cli = (fin.cli + reused) if fin.cli else fin.cli
    return fin


def _textbox_undecided_action(r):
    """囲み（問題文・ヒントなど）か図の注記か決められず、文字を XML に出力しなかったテキストボックス（structure.Classifier.place_boxes）。
    なければ None。

    要確認にとどめる（文字はレポートの 6 章に全文があり、図の注記を本文に混ぜるほうが害が大きい。決定事項 9(2)）。Word での直し方だけを
    書く（AI に種類を判断させる案内は、推奨の手順 ai_finish の 1 か所。修正計画 W8 の 4.3）。
    """
    plan = r.plan
    xids = plan.undecided_boxes
    if not xids:
        return None
    n = len(xids)
    samples = _box_samples(plan, xids)
    how = "Word でそのテキストボックスを確かめ、本文に必要な囲みなら、文字をテキストボックスの外（本文の段落）に出してから変換し直してください。"
    box_how = ("Word でそのテキストボックスを確かめ、本文に必要な囲みなら、文字をテキストボックスの外（本文の段落）に出してから"
               "変換し直してください")
    cli_how = "docx でそのテキストボックスを確かめ、本文に必要な囲みなら、文字をテキストボックスの外に出して変換し直すこと"
    todo = "Word で確かめ、本文に必要な囲みならテキストボックスの外に出して変換し直す"
    return Action(
        TO_CHECK, "textbox_undecided",
        top=(f"> **要確認: 囲み（問題文・ヒントなど）か図の注記か決められなかったテキストボックスが {n} 件あり、その文字を XML に"
             f"出力していません（3 章・6 章）。** {how}対象: {samples}"),
        checklist=(f"- [ ] **囲みか図の注記か決められなかったテキストボックス {n} 件**（3 章。XML に出力していない）: " + todo),
        box_title=f"囲みか図の注記か決められなかったテキストボックスが {n} 件あります（要確認）",
        box_detail=f"その文字は XML に出力していません。{box_how}（レポートの冒頭・3 章・6 章）。\n対象: {samples}",
        cli=(f"要確認: 囲みか図の注記か決められなかったテキストボックス {n} 件の文字を XML に出力していません（レポートの冒頭と"
             f" 3 章）。{cli_how}。対象: {samples}"))


def _textbox_place_action(r):
    """位置を推定して置いた囲み（boxed-text）。なければ None（要確認）。"""
    plan = r.plan
    xids = plan.estimated_boxes
    if not xids:
        return None
    n = len(xids)

    def head(x):        # 囲みの最初の文字（XML の boxed-text には ID がないので、文字で探してもらう）
        return next((q.text_only().strip() for q in plan.textboxes[x].paras if not q.is_blank), "")
    where = "、".join(f"{x}「{esc(head(x), 15)}」（{plan.box_place(x)}）" for x in xids[:5]) + ("ほか" if n > 5 else "")
    detail = ("docx には Word で表示したときの位置が記録されていないため、アンカー段落のすぐ後ろ（本文の外に結び付いたものは"
              "本文の最後）に置きました。PDF と見比べ、違えば XML の中で囲み（boxed-text。最初の文字で探せます）を正しい位置に"
              "移してください")
    return Action(
        TO_CHECK, "textbox_place",
        top=f"> **要確認: 位置を推定して置いた囲み（boxed-text）が {n} 件あります（3 章）。** {detail}: {where}",
        checklist=f"- [ ] 位置を推定して置いた囲み {n} 件（3 章の「囲み・図の注記」）を PDF と見比べ、違えば XML の中で移す",
        box_title=f"位置を推定して置いた囲みが {n} 件あります（要確認）",
        box_detail=f"{detail}（レポートの冒頭と 3 章）。\n対象: {where}",
        cli=f"要確認: 位置を推定して置いた囲み {n} 件（レポートの冒頭と 3 章）。{detail}。対象: {where}")


def figure_text_exclusions(r) -> list:
    """図表の入ったテキストボックス・グループ図形の中の、キャプションでも図の本体でもない段落で、XML に出力しなかったもの
    （理由 structure.TEXTBOX_TEXT_EXCLUDED。図の画像に写るとみなした説明・出典など）: [(段落 ID, 文字)]。

    図形の中身の組み方は AI の指定の有無で変わらない（structure.Classifier.float_units）ので、手動モードで AI の回答を貼り戻す
    前の、位置を決められない図表の中身も数える（修正計画 W1 の 2.4）。
    """
    return [(src, text) for src, why, text in r.fidelity.excluded if why == TEXTBOX_TEXT_EXCLUDED]


# 図の画像に写るとみなして XML の本文に出さなかった、図形の中の文字の説明と直し方（要確認 textbox_figure_text。修正計画 W1 の 4.2）
FIGURE_TEXT_WHY = ("図・表の入った図形（テキストボックス・グループ図形）の中の、キャプションでない文字は、図の画像に写るものとして、"
                   "XML の本文には出していません（全文はレポートの 6 章）。入れる画像にその文字が写っているか確かめてください。")
FIGURE_TEXT_HOW = "本文として読ませたい文字なら、Word でその文字を図形の外（本文の段落）に出して、変換し直してください。"


def figure_text_groups(r) -> list:
    """図の画像に写るとみなして除外した段落（figure_text_exclusions）を、その段落を中身に持つ図形ごとにまとめたもの（docx の順）:
    [(図形の言い方, 字数〈空白を除く〉, 先頭の文字)]。修正計画 W1 の 4.2。

    図形は段落の float_id（浮動配置の図形）か、なければ textbox_id（行内のテキストボックス）で決める。図形の言い方は、その図形の
    中身から組んだ図・表の置き場所（FloatInfo.nodes の slot の label・key。docx の順）で「図2・図3（fig02・fig03）の図形」、
    キャプションのない画像なら「キャプションのない画像（img3fa9c2。{slot_where}）の図形」、本文の図キャプションに含めた図形（mode が
    caption）なら「本文の図キャプション「図5 …」の図（fig05）に含めた図形」、置き場所が 1 つもなければ「図形 s3（{場所}）」。
    nodes がない図形（行内のテキストボックス・キャプションだけの図形を figure_units が組んだ図）は、キャプションか含めた画像がその図形の
    中にある置き場所を使う。
    """
    plan = r.plan
    groups = {}
    for src, text in figure_text_exclusions(r):
        p = plan.paras.get(src)
        gid = (p.float_id or f"x:{p.textbox_id}") if p is not None else f"p:{src}"
        groups.setdefault(gid, []).append((p, text))
    out = []
    for gid, rows in groups.items():
        chars = sum(len("".join(t.split())) for _, t in rows)
        head = next((t.strip() for _, t in rows if t.strip()), "")
        head = head[:20] + ("…" if len(head) > 20 else "")
        out.append((_figure_text_owner(r, gid, rows), chars, head))
    return out


def _figure_text_owner(r, gid, rows) -> str:
    """figure_text_groups の図形の言い方。"""
    plan = r.plan
    fi = plan.floats.get(gid) if not gid.startswith(("x:", "p:")) else None
    if fi is not None and fi.mode == "caption":
        slot = next((s for s in plan.slots if s.caption is not None and s.caption.src == fi.caption_src), None)
        if slot is not None:
            cap = slot.caption.text_only().strip()
            cap = cap[:20] + ("…" if len(cap) > 20 else "")
            return f"本文の図キャプション「{cap}」の図（{slot.key}）に含めた図形"
    slots = []
    if fi is not None:
        slots = [n.slot for n in fi.nodes if getattr(n, "slot", None) is not None]
    if not slots:
        def inside(q):
            if q is None or gid.startswith("p:"):
                return False
            return f"x:{q.textbox_id}" == gid if gid.startswith("x:") else q.float_id == gid
        slots = [s for s in plan.slots if inside(s.caption) or any(inside(plan.paras.get(i.para_src)) for i in s.covers)]
    slots = list(dict.fromkeys(slots))
    if slots:
        named = [s for s in slots if s.label]
        parts = []
        if named:
            parts.append("・".join(s.label for s in named) + "（" + "・".join(s.key for s in named) + "）")
        parts += [f"キャプションのない画像（{s.key}。{slot_where(r, s)}）" if s.kind == "nocap" else s.key
                  for s in slots if not s.label]
        return "と".join(parts) + "の図形"
    if fi is not None:
        anchor = plan.paras.get(fi.float.anchor_src)
        head = _head(anchor)
        return f"図形 {gid}（" + (f"「{head}」の段落に結び付いている" if head else f"段落 {fi.float.anchor_src} に結び付いている") + "）"
    p = rows[0][0]
    if p is not None and p.float_id:
        return f"図形 {p.float_id}"
    return f"テキストボックス {p.textbox_id}" if p is not None and p.textbox_id else "図形"


def _textbox_figure_text_action(r):
    """要確認 textbox_figure_text: 図の画像に写るとみなして XML の本文に出さなかった、図形の中の文字（figure_text_exclusions）。
    いつも出す（決定 3）。1 つの知らせで、図形ごとに 1 行（図番号か幹と、字数と先頭の文字。figure_text_groups）。なければ None。

    図形の中身の組み方は AI の指定の有無で変わらない（structure.Classifier.float_units）ので、手動モードで AI の回答を貼り戻す前の、
    位置を決められない図表の中身も数える。文字はレポートの 6 章に全文がある。
    """
    groups = figure_text_groups(r)
    if not groups:
        return None
    n = len(groups)
    lines = [f"・{owner}: {chars} 字「{head}」" for owner, chars, head in groups]
    title = f"図の画像に写るものとして、XML の本文に出していない文字があります（図形 {n} つ"
    return Action(
        TO_CHECK, "textbox_figure_text",
        top="\n".join([f"> **要確認: {title}。6 章）。** {FIGURE_TEXT_WHY}{FIGURE_TEXT_HOW}", ">"]
                      + [f"> - {esc(x[1:])}" for x in lines]),
        checklist=(f"- [ ] **図の画像に写るものとして XML の本文に出していない文字（図形 {n} つ）**（6 章）: 入れる画像に写っているか"
                   "確かめ、本文として読ませたい文字なら Word で図形の外に出して変換し直す"),
        box_title=f"{title}。要確認）",
        box_detail=f"{FIGURE_TEXT_WHY}{FIGURE_TEXT_HOW}\n" + "\n".join(lines),
        cli=(f"要確認: {title}。レポートの冒頭と 6 章）。入れる画像に写っているか確かめ、本文として読ませたい文字なら docx で図形の外"
             "（本文の段落）に出して変換し直すこと。\n" + "\n".join("  " + x[1:] for x in lines)))


def unplaced_exclusions(r) -> list:
    """論文の中の位置を決められずに XML に出力しなかった段落（理由が structure.UNPLACED_EXCLUSIONS。文字のないものと、
    abstract_missing で知らせるものを除く）: [(段落 ID, 理由, 文字)]（docx の順）。"""
    miss = set(abstract_missing_srcs(r.plan)) | front_reported_srcs(r)      # 要対応 authors_missing・front_check で知らせる段落は重ねて挙げない
    return [(s, why, t) for s, why, t in r.fidelity.excluded if why in UNPLACED_EXCLUSIONS and t.strip() and s not in miss]


# 位置を決められない除外の理由ごとの名前と、Word での直し方（_unplaced_action）
UNPLACED_GUIDE = {
    FRONT_OTHER_EXCLUDED: ("冒頭部の段落", "題目・副題・著者名・所属なら、Word でその段落に「題目（日）」「著者名（日）」「所属（日）」などのスタイルを付ける（所属と氏名が 1 つの段落なら、Enter で 2 段落に分けてから付ける）。本文なら、最初の章見出しの後ろに移す"),
    FRONT_TABLE_EXCLUDED: ("冒頭部の表", "本文の表なら、Word で最初の章見出しの後ろに移す"),
    AUTHOR_TABLE_OTHER_EXCLUDED: ("著者表の中の段落", "著者名・所属なら、Word でその段落に「著者名（日）」「所属（日）」スタイルを付ける"),
    BACK_TABLE_EXCLUDED: ("後付けの表", "注・付記・謝辞の表なら、Word で表をその節の中（注なら注の本文の後ろ）に移す。本文の表なら、引用文献・注などの見出しより前に移す"),
    BACK_OTHER_EXCLUDED: ("本文と後付けの間の段落", "前にある見出しのスタイル（「注見出し」「付記見出し」「謝辞見出し」「参考文献見出し」）を確かめる"),
    EN_AUTHOR_TABLE_OTHER_EXCLUDED: ("英文著者表の中の段落", "英文の著者名・所属なら、Word でその段落に「著者名（英）」「所属（英）」スタイルを付ける"),
    EN_TABLE_EXCLUDED: ("英文の部分の表", "資料の表なら、Word で表の前に資料の見出し（「資料1」など）を付ける"),
    EN_OTHER_EXCLUDED: ("英文の部分の段落", "英文要旨の見出し（Abstract）なら「英文要旨見出し」、英文要旨の段落なら「英文要旨」スタイルを付ける。英文の著者名・所属なら「著者名（英）」「所属（英）」スタイルを付ける。資料なら、前に資料の見出し（「資料1」など）を付ける"),
}


def _unplaced_action(r):
    """論文の中の位置を決められず、XML に出力しなかった段落（unplaced_exclusions）。なければ None。

    要確認にとどめる（文字は 6 章に全文がある。装飾・重複する所属など、意図して除いた段落は数えない。
    英文要旨が 1 段落もないときの英文の部分の段落は、要対応 abstract_missing で知らせる）。
    """
    rows = unplaced_exclusions(r)
    if not rows:
        return None
    n = len(rows)
    lines = []
    for why in UNPLACED_EXCLUSIONS:
        sub = [(s, t) for s, w, t in rows if w == why]
        if sub:
            name, how = UNPLACED_GUIDE[why]
            lines.append(f"{name} {len(sub)} 件（{_para_samples(sub, 3)}）: {how}")
    bullet = "\n>\n> - "
    dot = "\n・"
    samples = _para_samples([(s, t) for s, _, t in rows])
    lead = f"論文の中の位置を決められず、XML に出力していない段落が {n} 件あります"
    return Action(
        TO_CHECK, "excluded_unsure",
        top=(f"> **要確認: {lead}（6 章）。** 本文などに必要な文字なら、下の直し方で Word を直して変換し直してください"
             "（XML に入れない文字なら、そのままでかまいません）。" + "".join(bullet + x for x in lines)),
        checklist=(f"- [ ] **位置を決められず XML に出力していない段落**（{n} 件。6 章）: 本文などに必要なら、Word でスタイル・位置を"
                   "直して変換し直す"),
        box_title=f"論文の中の位置を決められない段落 {n} 件を、XML に出力していません（要確認）",
        box_detail="本文などに必要な文字なら、Word で直してから変換し直してください（レポートの冒頭と 6 章）。" + dot + dot.join(lines),
        cli=(f"要確認: {lead}（レポートの冒頭と 6 章）。本文などに必要な文字なら、docx でスタイル・位置を直して変換し直すこと。"
             f"対象: {samples}"))


# 英文要旨がないため資料も落ちていることの説明（_abstract_missing_action）
ABSTRACT_MISSING_APP = ("英文要旨がないため、英文の部分の資料（「資料1」などの見出しの段落と表）も位置を決められず、出力していません。"
                        "英文要旨を直すと、資料も出力されます。")


def _refs_missing_action(r):
    """引用文献の一覧が 1 件もないのに、本文に「著者（年）」の形の引用があるとき（plan.refs_missing_cites。refparse.refs_missing_cites）。
    なければ None。要対応（引用文献の一覧のない XML は登載できない。引用文献の見出しの文字を後付けの見出しと見分けられなかった原稿など。
    C032 の守り）。番号の形式の引用（［1］）だけの原稿は対象の外。"""
    plan = r.plan
    n = plan.refs_missing_cites
    if plan.refs or not n:
        return None
    head_style = _first_style(r.journal, "ref_heading", "参考文献見出し")
    ref_style = _first_style(r.journal, "ref", "参考文献")
    how = (f"Word で、引用文献の見出しの段落を「{head_style}」のスタイルに、各文献の段落を「{ref_style}」のスタイルにして、"
           "変換し直してください。")
    why = f"本文に「著者（年）」の形の引用が少なくとも {n} か所ありますが、引用文献の見出しが見つからず、XML に引用文献の一覧"
    return Action(
        NEEDS_ACTION, "refs_missing",
        top=f"> **要対応: 引用文献の一覧が見つかりません（3 章）。** {why}（{md_tag('<ref-list>')}）がありません。{how}",
        checklist="- [ ] **引用文献の一覧がない**（3 章）: Word で引用文献の見出しと文献のスタイルを付けて変換し直す",
        box_title="引用文献の一覧が見つかりません（要対応）",
        box_detail=f"{why}がありません。{how}（レポートの冒頭と 3 章）",
        cli=(f"要対応: 引用文献の一覧が見つからない（本文に著者（年）の引用が少なくとも {n} か所ある）。docx で引用文献の見出し・"
             "文献のスタイルを付けて変換し直すこと"))


def _refs_unlinked_action(r):
    """要確認 refs_unlinked（C087）: 引用文献の一覧が「[1]」の番号つきで、本文は「山田（2020）」の著者・年の書き方で引用していて、本文から
    文献へのリンクが 1 件もないとき。なければ None。

    番号つきの一覧では、リンクするのは本文の「[1]」の形の引用だけ（refparse.link_numeric。リンクの規則は変えない）。著者・年の引用の
    数は plan.numeric_author_year_cites（refparse.refs_missing_cites と同じ数え方。引用がない短い原稿・文献のない原稿には出さない）。
    リンクが 1 件でもある原稿には出さない（一部の引用がリンクされない場合は、3 章の未解決の表と「どこからもリンクされていない文献」で見る）。
    XML は変えない（リンクを推定で足さない）。"""
    plan = r.plan
    n = plan.numeric_author_year_cites
    if plan.citation_mode != "numeric" or not plan.refs or not n or linked_ids(plan, "bibr"):
        return None
    refs = len(plan.refs)
    why = (f"引用文献の一覧が「[1]」のような番号つきですが、本文は「著者（年）」の形の引用（少なくとも {n} か所）で、本文から引用文献"
           f"（{refs} 件）へのリンクが 1 件もありません")
    how = ("Word で、引用文献の一覧の番号を外して「著者（年）」の形にそろえるか、本文の引用を番号の形（「[1]」）にそろえて、変換し直してください。"
           "このまま登載すると、J-STAGE の本文から引用文献へのリンクがありません")
    return Action(
        TO_CHECK, "refs_unlinked",
        top=f"> **要確認: 本文から引用文献へのリンクがありません（3 章）。** {why}。{how}。",
        checklist=f"- [ ] **本文から引用文献へのリンクがない**（引用文献 {refs} 件。3 章）: 文献の一覧と本文の引用の書き方（番号か著者・年）をそろえて変換し直す",
        box_title="本文から引用文献へのリンクがありません（要確認）",
        box_detail=f"{why}。{how}（直した docx を{step('docx')}でアップロードし直し、そこから順にやり直す）。",
        cli=f"要確認: 本文から引用文献へのリンクがない（{why}。レポートの冒頭と 3 章）。{how}")


def _first_style(journal, role, default):
    return next((name for name, v in journal.styles.items() if v == role), default)


def _abstract_missing_action(r):
    """英文要旨が 1 段落もなく、英文の部分の段落・表の文字を XML に出力しなかったとき（structure.abstract_missing_srcs）。なければ None。

    要対応（英文要旨は XML の必須の内容。段落のスタイルがないために落ちている可能性が高い）。Word でスタイルを付ける直し方を書き、
    AI が英文要旨の段落を提案していれば（AIOutcome.style_fixes の abstract。XML には反映しない）、AI の見立てを 1 行添える
    （対象の段落は要確認 style_check には載せない。修正計画 W8 の 4.3）。
    """
    plan = r.plan
    srcs = abstract_missing_srcs(plan)
    if not srcs:
        return None
    reason = {e.src: e.reason for e in plan.exclusions}
    k = sum(1 for s in srcs if reason[s] == EN_OTHER_EXCLUDED)
    c = sum(1 for s in srcs if reason[s] == EN_TABLE_EXCLUDED)
    count = f"段落 {k} 件" + (f"と表のセルの段落 {c} 件" if c else "")
    rows = [(s, plan.paras[s].text_only()) for s in srcs]
    samples = _para_samples(rows)
    names = list(dict.fromkeys(plan.paras[s].style_name or "（スタイルなし）" for s in srcs))[:3]
    styles = "・".join(f"「{x}」" for x in names)
    abs_style = _first_style(r.journal, "abstract", "英文要旨")
    head_style = _first_style(r.journal, "abstract_heading", "英文要旨見出し")
    app = (ABSTRACT_MISSING_APP
           if c or any(appendix_heading(plan.paras[s].text_only()) for s in srcs if reason[s] == EN_OTHER_EXCLUDED) else "")
    if plan.abstract_heading is None:
        why = f"英文要旨の段落に「{abs_style}」スタイルがなく、見出し（Abstract）にも「{head_style}」スタイルがないため、"
    else:
        why = f"「{head_style}」スタイルの見出しはありますが、その後ろに英文要旨の段落がないため、"
    body = (why +
            f"英文の題目・著者名・所属以外の段落の位置を決められませんでした（段落のスタイル: {styles}）。{app}"
            f"英文要旨なら、Word で要旨の段落に「{abs_style}」スタイルを（見出しがあれば見出しに「{head_style}」スタイルを）付けて、"
            "変換し直してください。")
    fixes = _style_fix_of(r.ai)
    guess = next((fixes[s] for s in srcs if s in fixes and fixes[s].role == "abstract" and fixes[s].verdict != STYLE_KEEP), None)
    conf = f"（確度 {guess.confidence}）" if guess is not None and guess.confidence else ""
    ai_line = (f"AI の見立て: 「{esc(_head(plan.paras.get(guess.src), 15))}」の段落から英文要旨{conf}。" if guess is not None else "")
    body += ai_line
    return Action(
        NEEDS_ACTION, "abstract_missing",
        top=(f"> **要対応: 英文要旨が見つかりません。英文の部分の{count}を XML に出力していません（6 章）。** {body}"
             f"対象の段落: {samples}"),
        checklist=(f"- [ ] **英文要旨が見つからない**（英文の部分の{count}を出力していない。6 章）: Word で英文要旨の段落に"
                   f"「{abs_style}」スタイルを付けて変換し直す"),
        box_title="英文要旨が見つかりません（要対応）",
        box_detail=body + "\n対象の段落: " + samples,
        cli=(f"要対応: 英文要旨が見つかりません。英文の部分の{count}を XML に出力していません（レポートの冒頭と 6 章）。{app}"
             f"docx で要旨の段落に「{abs_style}」スタイルを付けて変換し直すこと。"
             f"{ai_line}対象: {samples}"))


# ---------------------------------------------------------------------------- 冒頭部（題目・著者名・所属）の確かめ（単位 C。frontcheck.py）
def _front_lang(r) -> str:
    return frontcheck.article_lang(r.plan, getattr(r, "meta", None), getattr(r, "journal", None))


def _front_pdf(r) -> tuple:
    """出版版 PDF との照合でわかった冒頭部の項目（frontcheck.pdf_findings。pdfmatch.PdfCheck.front）と、題目のページにあった段落の ID。
    PDF がない・読めない・照合できないときは、どちらも空。"""
    pc = getattr(r, "pdf_check", None)
    if pc is None or not getattr(pc, "ok", False):
        return [], set()
    return list(getattr(pc, "front", ()) or ()), set(getattr(pc, "front_on_page", ()) or ())


def authors_missing_srcs(r) -> list:
    """要対応 authors_missing の対象にする（和文の著者名らしい）段落の ID。和文の著者名が 1 人もない記事のときだけ（なければ []）。
    ない記事でも authors_missing 自体は出るので、候補が空でも出る場合は authors_missing_applies で見る。"""
    plan = r.plan
    if not frontcheck.authors_missing_applies(plan, _front_lang(r)):
        return []
    skip = {s for f in frontcheck.plan_findings(plan, _front_lang(r)) if f.kind == frontcheck.TITLE_MISSING for s in f.srcs}
    return frontcheck.author_candidates(plan, skip)


def front_findings(r) -> list:
    """要対応・要確認 front_check の項目（frontcheck.FrontFinding。出版版 PDF の項目を含む）。"""
    pdf_front, _ = _front_pdf(r)
    return frontcheck.front_findings(r.plan, _front_lang(r), pdf_front)


def front_reported_srcs(r) -> set:
    """authors_missing・front_check で知らせる段落の ID。同じ段落を要確認 excluded_unsure・name_split・style_check で重ねて挙げない
    ために、それぞれの一覧から除く（authors_missing は、出ているときの候補だけ。出ないときの冒頭部の段落は、今までどおり
    excluded_unsure に出る）。"""
    return set(authors_missing_srcs(r)) | frontcheck.finding_srcs(front_findings(r))


def _front_samples(plan, srcs, n=4) -> str:
    return _para_samples([(s, frontcheck.text_of(plan, s)) for s in srcs], n)


def _authors_missing_action(r):
    """和文の著者名が 1 人もない（C009）。要対応 authors_missing。なければ None。

    著者表のセルにスタイルがない・所属と氏名が 1 つの段落になっている・著者表がない、などで、XML の書誌に和文の著者名・所属が入らなかったとき。
    文字も構造も変えず、Word でスタイルを付ける直し方を知らせる。著者名・所属らしい段落を添える（出版版 PDF の題目のページに
    あれば、そのことも書く）。"""
    plan = r.plan
    lang = _front_lang(r)
    if not frontcheck.authors_missing_applies(plan, lang):
        return None
    cands = authors_missing_srcs(r)
    _, on_page = _front_pdf(r)
    author_style = _first_style(r.journal, "author_ja", "著者名（日）")
    aff_style = _first_style(r.journal, "aff_ja", "所属（日）")
    in_table = {q.src for t in plan.tables if t.table is not None for q in t.table.paragraphs()}
    # 著者表のセルにもうスタイルが付いていて、題目の段落がないために冒頭部の著者表として読めていないときは、スタイルを付ける直し方を
    # 書かず、冒頭部の確かめ〈題目の段落がない〉を直すと消えると書く（upload の UPLOAD_TITLE_NOTE と同じ扱い。直し方を 2 通りに書かない）
    title_missing = any(f.kind == frontcheck.TITLE_MISSING for f in front_findings(r))
    styled = [s for s in cands if s in plan.paras and r.journal.styles.get(plan.paras[s].style_name) in ("author_ja", "aff_ja")]
    if title_missing and styled:
        how = AUTHORS_TITLE_NOTE
        short = "著者表のスタイルは付いています。冒頭部の確かめ〈題目の段落がない〉を直すと消える"
        cli_how = "著者表のスタイルは付いているので、冒頭部の確かめ〈題目の段落がない〉を直して変換し直すこと（直すと消える）。"
    else:
        # 表のセルの候補: 本文の表（plan.tables）か、冒頭部の表のセルとして除外した段落
        from .structure import AUTHOR_TABLE_OTHER_EXCLUDED, FRONT_TABLE_EXCLUDED
        cell_excluded = {e.src for e in plan.exclusions if e.reason in (FRONT_TABLE_EXCLUDED, AUTHOR_TABLE_OTHER_EXCLUDED)}
        if not cands or any(s in in_table or s in cell_excluded for s in cands):
            how = (f"Word で、著者表の氏名のセルに「{author_style}」、所属のセルに「{aff_style}」のスタイルを付けて（所属と氏名が 1 つの段落なら、"
                   "Enter で 2 段落に分けてから付けて）、変換し直してください。")
            short = f"著者表に「{author_style}」「{aff_style}」のスタイルを付けて変換し直す"
            cli_how = f"docx の著者表に「{author_style}」「{aff_style}」のスタイルを付けて変換し直すこと。"
        else:
            # 著者名・所属らしい段落が表の外だけ（著者表がない docx）: 表を作る必要はない（点検 review19 の 3 回目の利用者向け 3）
            how = (f"Word で、氏名の段落に「{author_style}」、所属の段落に「{aff_style}」のスタイルを付けて（所属と氏名が 1 つの段落なら、"
                   "Enter で所属と氏名の 2 段落に分けてから付けて）、変換し直してください。著者表を作る必要はありません。")
            short = f"氏名と所属の段落に「{author_style}」「{aff_style}」のスタイルを付けて変換し直す"
            cli_how = f"docx の氏名と所属の段落に「{author_style}」「{aff_style}」のスタイルを付けて変換し直すこと。"
        if styled:
            how += f"（{'・'.join(styled)} には、もうスタイルが付いています。題目の段落の後ろ・本文の最初の見出しの前にあるかも確かめてください）"
        elif title_missing:
            how += "（題目の段落がないことも原因かもしれません。冒頭部の確かめ〈題目の段落がない〉も直してください）"
    rows = []
    for s in cands:
        notes = (["本文の表として出力しています"] if s in in_table and plan.region.get(s) == "body" else []) + (
            ["PDF の題目のページにあります"] if s in on_page else [])
        rows.append(_para_samples([(s, frontcheck.text_of(plan, s))], 1) + ("（" + "、".join(notes) + "）" if notes else ""))
    cand = ("著者名・所属らしい段落: " + "、".join(rows) + "。") if rows else ""
    body = f"XML の書誌に和文の著者名・所属が入っていません（6 章）。{how}{cand}"
    return Action(
        NEEDS_ACTION, "authors_missing",
        top=f"> **要対応: 和文の著者名が 1 人も見つかりません。** {body}",
        checklist=f"- [ ] **和文の著者名・所属が見つからない**（6 章）: {short}",
        box_title="和文の著者名が見つかりません（要対応）",
        box_detail=body,
        cli=f"要対応: 和文の著者名が見つからない（XML に和文の著者名・所属が入っていない。レポートの冒頭と 6 章）。{cli_how}{cand}")


# 著者表にスタイルは付いているが、題目の段落がないために冒頭部の著者表として読めていないときの直し方（_authors_missing_action）
AUTHORS_TITLE_NOTE = ("著者表のスタイルは付いていますが、題目の段落がないため冒頭部の著者表として読めていません。"
                      "冒頭部の確かめ〈題目の段落がない〉を直すと消えます。")


FRONT_KIND_SHORT = {
    frontcheck.TEMPLATE: "テンプレートの見本の行", frontcheck.TITLE_MISSING: "題目の段落がない", frontcheck.TITLE_MULTI: "題目の段落が 2 つ以上",
    frontcheck.SWAP: "所属と氏名の入れ替わり", frontcheck.JA_MISSING: "和文の著者名の欠け", frontcheck.AFF_MISSING: "和文の所属の欠け",
    frontcheck.EN_MISSING: "英文の著者名がない", frontcheck.EN_COUNT: "和文と英文の著者数の違い",
    frontcheck.PDF_MISSING: "PDF に見つからない項目", frontcheck.PDF_NEAR: "PDF と少し違う項目", frontcheck.PDF_EN_MISSING: "PDF に見つからない英文の項目",
}
# 題目の段落が 2 つ以上のとき、2 つ目以降を直す「副題」のスタイルの役割
FRONT_SUBTITLE_ROLE = {"題目（日）": ("subtitle", "副題（日）"), "副題（日）": ("subtitle", "副題（日）"),
                       "題目（英）": ("subtitle_en", "副題（英）"), "副題（英）": ("subtitle_en", "副題（英）")}


FRONT_PDF_WIDTH = 120     # front_check の PDF と比べる項目（pdf_missing・pdf_near・pdf_en_missing）に出す段落の文字の数


def _front_item_text(r, f) -> str:
    """front_check の項目 1 つの文（何が・どの段落か・Word での直し方）。"""
    plan = r.plan
    ex = _front_samples(plan, f.srcs)
    k = f.kind
    if k == frontcheck.TEMPLATE:
        return (f"著者表に、テンプレートの見本の行（{ex}）が残っていて、XML に著者・所属として出ています。見本の行なら、Word で著者表のその行を"
                "消して（白字で見えないことがあります）変換し直してください。")
    if k == frontcheck.TITLE_MISSING:
        style = _first_style(r.journal, "title", "題目（日）")
        cand = f"題目らしい段落: {ex}。" if f.srcs else ""
        return (f"「{style}」のスタイルの段落がありません（XML に和文の題目がありません）。Word で題目の段落にそのスタイルを付けて"
                f"変換し直してください。{cand}")
    if k == frontcheck.TITLE_MULTI:
        role, sub = FRONT_SUBTITLE_ROLE.get(f.note, ("", "副題"))
        sub = _first_style(r.journal, role, sub) if role else sub
        dash = len(f.srcs) > 1 and frontcheck.starts_with_dash(frontcheck.text_of(plan, f.srcs[1]))
        guess = f"{f.srcs[1]} はダッシュで始まるので副題のようです。" if dash else ""
        return (f"{f.note}のスタイルの段落が {len(f.srcs)} つあり、XML では 1 つにつないでいます（{ex}）。{guess}副題なら Word でその段落を"
                f"「{sub}」のスタイルに、題目の続きなら 1 段落にまとめて（改行が要るなら Shift+Enter）、変換し直してください。")
    if k == frontcheck.SWAP:
        a, b = _first_style(r.journal, "author_ja", "著者名（日）"), _first_style(r.journal, "aff_ja", "所属（日）")
        # 例は、所属の語がある著者名（著者名のスタイルの段落）と、氏名らしい所属（所属のスタイルの段落）に分けて書く
        names = [s for s in f.srcs if frontcheck.label_of(plan, s) != "所属（日）"]
        affs = [s for s in f.srcs if frontcheck.label_of(plan, s) == "所属（日）"]
        aff_ex = f"。氏名らしい所属: {_front_samples(plan, affs)}" if affs else ""
        return (f"著者名に所属の語（「{f.note}」）があります（所属の語がある著者名: {_front_samples(plan, names)}{aff_ex}）。"
                f"著者表の所属と氏名のセルのスタイル（「{a}」「{b}」）が入れ替わって"
                "いないか確かめ、入れ替わっていれば Word でスタイルを付け直して変換し直してください。所属と氏名が 1 つの段落なら、"
                "Enter で 2 段落に分けてください。")
    if k == frontcheck.JA_MISSING:
        a = _first_style(r.journal, "author_ja", "著者名（日）")
        return (f"英文の著者名に対応する和文の著者名がありません（{ex}）。和文の氏名のセルに「{a}」のスタイルが付いているか確かめて、"
                "変換し直してください。")
    if k == frontcheck.AFF_MISSING:
        b = _first_style(r.journal, "aff_ja", "所属（日）")
        cand = f"所属らしい段落: {ex}。" if f.srcs else ""
        return f"和文の所属が 1 つもありません（XML の書誌に和文の所属が入っていません）。所属のセルに「{b}」のスタイルを付けて変換し直してください。{cand}"
    if k == frontcheck.EN_MISSING:
        a, b = _first_style(r.journal, "author_en", "著者名（英）"), _first_style(r.journal, "aff_en", "所属（英）")
        cand = f"英文の著者名・所属らしい段落: {ex}。" if f.srcs else ""
        return (f"英文の題目はありますが、英文の著者名がありません（XML に英文の氏名・所属が入っていません）。英文の著者名・所属の段落に"
                f"「{a}」「{b}」のスタイルを付けて、変換し直してください。{cand}")
    if k == frontcheck.EN_COUNT:
        return (f"和文の著者名のうち、対応する英文の著者名がない人がいます（{ex}）。英文の著者表の行が足りないか、スタイルが付いていないか"
                "確かめてください。")
    # PDF と比べる項目は、段落の文字をまるごと（FRONT_PDF_WIDTH 文字まで）出す（違う所が後ろにあっても PDF と見比べられるように。
    # 冒頭部の段落は短い。点検 review19 の 3 回目の利用者向け 1）
    labelled = "、".join(f"{frontcheck.label_of(plan, s) or '段落'} "
                        f"{_para_samples([(s, frontcheck.text_of(plan, s))], 1, FRONT_PDF_WIDTH)}" for s in f.srcs[:4])
    if k == frontcheck.PDF_MISSING:
        return (f"出版版 PDF の題目のページに見つからない和文の項目: {labelled}。著者表に余分な行がないか、docx が校正後の版かを確かめ、"
                "Word で直して変換し直してください。")
    if k == frontcheck.PDF_NEAR:
        return (f"出版版 PDF の題目のページの文字と少し違う和文の項目: {labelled}。異体字や校正の直しかもしれません。PDF と見比べて、"
                "違っていれば Word で直して変換し直してください。")
    return (f"出版版 PDF に見つからない英文の項目: {labelled}。校正で直ったのかもしれません。PDF が正しければ、Word で直して"
            "変換し直してください。")


def _front_check_action(r):
    """冒頭部（題目・著者名・所属）の確かめ（修正計画 W6）。要対応か要確認 front_check。なければ None。

    項目（frontcheck.FrontFinding）を 1 つにまとめる。要対応の項目が 1 つでもあれば要対応、なければ要確認（meta_pdf と同じ作り）。
    XML は変えない（直すのは Word。docx の文字も構造も変えない）。和文の著者名が 1 人もないときは別の要対応 authors_missing で知らせる。"""
    items = front_findings(r)
    if not items:
        return None
    n = len(items)
    heavy = any(f.level == frontcheck.MUST for f in items)
    lead = "要対応" if heavy else "要確認"
    level = NEEDS_ACTION if heavy else TO_CHECK
    # 要対応と要確認の項目が混ざるときは、要確認の項目に印を付ける（どれが止める理由か分かるように）
    mark = lambda f: "（要確認）" if heavy and f.level != frontcheck.MUST else ""
    lines = [mark(f) + _front_item_text(r, f) for f in items]
    names = "・".join(dict.fromkeys(FRONT_KIND_SHORT[f.kind] + mark(f) for f in items))
    bullet, dot = "\n>\n> - ", "\n・"
    what = "題目・著者名・所属を確かめてください"
    return Action(
        level, "front_check",
        top=f"> **{lead}: {what}（{n} 件。4 章・7 章）。** " + "".join(bullet + x for x in lines),
        checklist=f"- [ ] **題目・著者名・所属**（{n} 件。4 章・7 章）: 確かめて、Word で直して変換し直す（{names}）",
        box_title=f"題目・著者名・所属に確かめる所があります（{lead}）",
        box_detail="Word で直してから変換し直してください（レポートの 4 章・7 章）。" + dot + dot.join(lines),
        cli=(f"{lead}: 題目・著者名・所属に確かめる所がある（{names}。レポートの冒頭と 4 章・7 章）。docx を直して変換し直すこと。\n"
             + "\n".join("  ・" + x for x in lines)))


NOCAP_SKIP_HINT = "。出版版 PDF で見て、ほかの図に写っている・飾りだけ、のときは「入れない」を選びます"      # 手順 images の、キャプションのない行の末尾


def _image_line(row) -> str:
    """手順 images の残りの 1 行（box_detail。修正計画 W1 の 4.1）。括弧には置き場所の備考（ImageSlot.note）をそのまま添える。"""
    cap = shown_text(row.caption)
    head = f"「{cap[:30]}{'…' if len(cap) > 30 else ''}」" if cap else ""      # キャプションは番号から（docx の文字のまま。数式の位置は表示用の言葉に）
    notes = [row.slot_note] if row.slot_note else []
    if row.kind == "table":
        notes.insert(0, "表が画像で挿入されていると考えられます。表の部分を画像にして入れてください")
    if row.kind == "nocap" or not cap:
        head = "キャプションのない画像"
        notes = ([shown_text(row.where)] if row.where else []) + notes
    line = f"・{row.key}: {head}" + (f"（{'。'.join(notes)}）" if notes else "")
    if row.kind == "nocap" or not cap:
        line += NOCAP_SKIP_HINT
    return line


def _image_short(row) -> str:
    """一覧・コマンドラインの残りの 1 項目: fig04（図4 …）・img3fa9c2（キャプションなし）。"""
    if row.kind == "nocap" or not row.caption.strip():
        return f"{row.key}（キャプションなし）"
    cap = shown_text(row.caption)
    return f"{row.key}（{cap[:20]}{'…' if len(cap) > 20 else ''}）"


def _cap30(text: str) -> str:
    """キャプションの先頭 30 字（長ければ「…」を付ける）。docx の文字のまま。"""
    t = shown_text(text)
    return t[:30] + ("…" if len(t) > 30 else "")


def _image_cli(row) -> str:
    """コマンドラインの残りの 1 項目。キャプションのない画像は、入れないときの指定（--no-image）も添える。"""
    if row.kind == "nocap" or not row.caption.strip():
        return f"{row.key}（キャプションなし。{shown_text(row.where)}。入れないときは --no-image {row.key}）"
    return _image_short(row)


def images_dropped(r) -> list:
    """持ち越せず、まだ入れ直していない前の画像（Result.images_dropped の DroppedImage）。同じ論文のものだけ（別の論文のものは images_other_article）。

    今の図が示されているもの（suggest）は、その図にこの前の画像そのもの（中身の SHA-1 が同じ）が入っているか、変換の後に作業する人が
    その図に画像を入れた（Result.images_readded。切り取り直した別の画像でもよい）なら済んだとみなす（持ち越しでほかの前の画像が
    入っただけでは済みにしない）。示されていないものは、同じ幹の図に画像が入っていれば済んだとみなす。
    """
    now = {i.key: i for i in r.images}
    readded = getattr(r, "images_readded", set())
    out = []
    for d in getattr(r, "images_dropped", []):
        if d.other_article:
            continue
        if d.suggest:
            im = now.get(d.suggest)
            done = im is not None and im.status == "user" and (d.suggest in readded or (bool(d.sha1) and im.sha1 == d.sha1))
        else:
            im = now.get(d.key)
            done = im is not None and im.status == "user"
        if not done:
            out.append(d)
    return out


def images_other_article(r) -> list:
    """記事識別子が変わった（別の論文に替えて変換した）ので入れなかった前の画像（Result.images_dropped の DroppedImage）。"""
    return [d for d in getattr(r, "images_dropped", []) if d.other_article]


def images_changed(r) -> list:
    """キャプションが少し変わった図に入れ直した画像（Result.images_changed の ChangedImage）で、画像がまだ入っているもの。"""
    got = {i.key for i in r.images if i.status == "user"}
    return [c for c in getattr(r, "images_changed", []) if c.key in got]


def _dropped_lines(r, dropped) -> list:
    """持ち越せなかった画像の行（手順 images の本文・一覧・コマンドラインで共用）。"""
    caps = {i.key: i.caption for i in r.images}
    out = []
    for d in dropped:
        head = f"・前の {d.key}" + (f"「{_cap30(d.caption)}」" if d.caption.strip() else "（キャプションなし）") + f"の画像（{d.source_name or 'ファイル名なし'}）: "
        if d.suggest:
            head += f"今の {d.suggest}" + (f"「{_cap30(caps.get(d.suggest, ''))}」" if caps.get(d.suggest, "").strip() else "") + "の画像と思われます"
        else:
            head += d.why
        out.append(head)
    return out


def _changed_lines(changed) -> list:
    return [f"・{c.key}: 前「{_cap30(c.old_caption)}」→ 今「{_cap30(c.new_caption)}」（{c.source_name or 'ファイル名なし'}）" for c in changed]


def images_carry_text(r) -> str:
    """変換し直しで持ち越せなかった画像についての知らせ（修正計画 W1 の 4.1）。なければ ""。

    同じ論文で入れ直さなかった画像は 1 枚ずつ並べる。別の論文に替えて変換したときの前の画像は並べず、画像がまだ残っているうちだけ 1 行で
    知らせる（同じ論文で巻・ページを直したときのため）。キャプションが少し変わった図に入れた画像は、要確認 image_changed で知らせる。
    """
    dropped, other = images_dropped(r), images_other_article(r)
    parts = []
    if other and images_progress(r)[0]:
        ids = "・".join(dict.fromkeys(d.other_article for d in other))
        parts.append(f"前の論文（{ids}）で入れた画像 {len(other)} 枚は、記事の巻・ページが違うので入れていません。"
                     "同じ論文で巻・ページを直したのなら、入れ直してください。")
    if dropped:
        parts.append(f"前に入れた画像のうち {len(dropped)} 枚は、変換し直した原稿で図の番号かキャプション（キャプションのない画像は場所）が変わっていたので、"
                     "入れていません（別の図の画像を入れないためです）。入れ直してください。\n" + "\n".join(_dropped_lines(r, dropped)))
    return "\n".join(parts)


def images_action(r):
    """手順 images（必須）: 図・表の画像を入れる（修正計画 W1 の 4.1）。画像の置き場所（任意を除く）がなければ None。

    図・表の画像は、作業する人が出版版 PDF などから用意して入れる（docx の画像は使わない）。残っていれば必須の手順が残り
    （終了コード 1・ダウンロードの歯止め）、全部入れれば済み（done）。枠の本文には、残りの置き場所ごとに 1 行（image_rows）。
    変換し直しで持ち越せなかった画像があれば、本文に足す（済んでいても枠を出す。images_carry_text）。
    """
    left, total = images_progress(r)
    carry = images_carry_text(r)
    if not total and not carry:
        return None
    rows = [row for row in image_rows(r) if row.kind != "optional" and row.status in ("missing", "user")]
    rest = [row for row in rows if row.status == "missing"]
    dropped = images_dropped(r)
    if not left:
        title = (f"図の画像 {total} 枚をすべて入れました" if total else "図の画像を入れる必要はありません")
        if dropped:
            title += f"（前に入れた画像 {len(dropped)} 枚は入れていません）"
        note = ""
        if total and sum(1 for i in r.images if i.status == "skipped"):
            note = f"。キャプションのない画像 {sum(1 for i in r.images if i.status == 'skipped')} か所は入れないことにした"
        return Action(STEP, "images", required=True, done=True,
                      progress=(f"{total} 枚をすべて入れました" if total else "入れる画像はありません"),
                      checklist=((f"- [x] 図の画像 {total} 枚を入れた（9 章）{note}" if total else "- [x] 図の画像を入れる必要はない（9 章）")
                                 + ("".join("\n  " + esc(x) for x in carry.splitlines()) if carry else "")),
                      box_title=title if carry else "", box_detail=carry, cli=carry)
    progress = f"あと {left} 枚／全部で {total} 枚"
    detail = (f"この論文で画像が要る図・表は {total} 個です（Word の原稿の中の画像は使いません）。出版版 PDF を画面に大きく表示し、"
              "図ごとに図の部分だけを切り取って（スクリーンショット）、PNG か JPEG で保存し、"
              f"{step('images')}で入れてください。キャプション（「図1 …」の行）は写さないでください（XML に文字で入っています）。"
              "ファイル名を fig04.png・図4.png のようにしておくと、まとめて入れられます。\n残り:\n"
              + "\n".join(_image_line(row) for row in rest))
    return Action(
        STEP, "images", required=True, done=False, progress=progress,
        checklist=(f"- [ ] **図の画像を入れる（{progress}）**（9 章）: " + "、".join(esc(_image_short(row)) for row in rest)
                   + ("".join("\n  " + esc(x) for x in carry.splitlines()) if carry else "")),
        box_title=f"図の画像を入れてください（{progress}）",
        box_detail=detail + ("\n" + carry if carry else ""),
        cli=(f"手順: 図の画像があと {left} 枚要ります（全部で {total} 枚）。次の名前（拡張子は .png・.jpg・.gif）の画像を、この論文だけの"
             "フォルダに入れ、--images で指定して変換し直すこと: " + "、".join(_image_cli(row) for row in rest)
             + ("\n" + carry if carry else "")))


def lost_action(r):
    """画像を入れる場所（置き場所）を作れなかった docx の画像（pipeline.lost_images。修正計画 W1 の 4.2）。なければ None。"""
    lost = r.lost_images
    if not lost:
        return None
    n = len(lost)
    return Action(
        NEEDS_ACTION, "lost",
        top="\n".join([f"> **要対応: 画像を入れる場所を作れなかった画像が {n} つあります（9 章）。** {LOST_IMAGES_WHY}{LOST_IMAGES_HOW}", ">"]
                      + [f"> - {esc(lost_image_label(li))}: {esc(li.reason)}" for li in lost]),
        checklist=(f"- [ ] **画像を入れる場所を作れなかった画像 {n} つ**（9 章）: 資料の図なら Word で資料を英文要旨の後ろに移す。"
                   "要らなければ Word で消す: " + "、".join(esc(lost_image_label(li)) for li in lost)),
        box_title=f"画像を入れる場所を作れなかった画像が {n} つあります（要対応）",
        box_detail=(f"{LOST_IMAGES_WHY}{LOST_IMAGES_HOW}変換し直すときは、Word で直した docx を{step('docx')}でアップロードし直し、そこから"
                    "順にやり直してください（レポートの冒頭と 9 章）。\n"
                    + "\n".join(f"・{lost_image_label(li)}: {li.reason}" for li in lost)),
        cli=(f"要対応: 画像を入れる場所を作れなかった画像 {n} つ（引用文献・注の節や、題目・著者名・所属の段落の中にある。"
             "レポートの冒頭と 9 章）。資料の図なら docx で資料を英文要旨の後ろに移して変換し直すこと。\n"
             + "\n".join(f"  {lost_image_label(li)}: {li.reason}" for li in lost)))


def same_images(r) -> list:
    """同じ中身（SHA-1）の画像が入っている置き場所の組（images.SlotImage の一覧の一覧。2 つ以上のものだけ。XML の順）。"""
    groups = {}
    for i in r.images:
        if i.status == "user" and i.sha1:
            groups.setdefault(i.sha1, []).append(i)
    return [g for g in groups.values() if len(g) > 1]


def _slot_label(i) -> str:
    """置き場所の言い方: 図2（fig02）・キャプションのない画像（img3fa9c2）。"""
    return f"{i.label}（{i.key}）" if i.label else f"キャプションのない画像（{i.key}）"


def _image_same_action(r):
    """要確認 image_same: 入れた画像のうち、中身が同じものが 2 つ以上の置き場所にある（修正計画 W1 の 4.2）。なければ None。"""
    groups = same_images(r)
    if not groups:
        return None
    lines = ["と".join(_slot_label(i) for i in g) + "に、同じ中身の画像が入っています。" for g in groups]
    keys = "・".join(i.key for g in groups for i in g)
    how = f"取り違えていないか、「{r.meta.article_id(r.journal)}_図の確かめ.html」で確かめてください。"
    return Action(
        TO_CHECK, "image_same",
        top="> **要確認: 同じ画像が 2 つ以上の図に入っています（9 章）。** " + esc("".join(lines)) + how,
        checklist=f"- [ ] **同じ画像が入っている図**（{keys}）を、「{r.meta.article_id(r.journal)}_図の確かめ.html」で確かめる",
        box_title="同じ画像が 2 つ以上の図に入っています（要確認）",
        box_detail="".join(lines) + how,
        cli=f"要確認: 同じ画像が 2 つ以上の図に入っています（{keys}。レポートの冒頭と 9 章）。" + "".join(lines) + "取り違えていないか確かめること。")


def _image_changed_action(r):
    """要確認 image_changed: 変換し直しで、キャプションの本体が少し変わった図（割合 0.8 以上 1.0 未満）に前の画像を入れ直した
    （修正計画 W1 の 2.6。pipeline.reapply_images）。手順 images は済みのまま、図と画像が合っているかを確かめてもらう。その図に画像を
    入れ直すと消える。なければ None。"""
    changed = images_changed(r)
    if not changed:
        return None
    keys = "・".join(c.key for c in changed)
    check = f"「{r.meta.article_id(r.journal)}_図の確かめ.html」"
    lines = _changed_lines(changed)
    why = "変換し直す前に入れた画像を、キャプションが少し変わった図に入れ直しました。"
    return Action(
        TO_CHECK, "image_changed",
        top="\n".join([f"> **要確認: キャプションが変わった図に、前の画像を入れ直しました（9 章）。** {why}図と画像が合っているか、"
                       f"{esc(check)}で確かめてください。違っていれば、正しい画像を入れ直してください。", ">"]
                      + [f"> - {esc(x[1:])}" for x in lines]),
        checklist=f"- [ ] **キャプションが変わった図に入れ直した画像**（{keys}）を、{esc(check)}で確かめる",
        box_title="キャプションが変わった図に、前の画像を入れ直しました（要確認）",
        box_detail=(f"{why}図と画像が合っているか、{check}で確かめてください。違っていれば、{step('images')}で正しい画像を入れ直してください。\n"
                    + "\n".join(lines)),
        cli=(f"要確認: キャプションが変わった図に、前の画像を入れ直しました（{keys}。レポートの冒頭と 9 章）。図と画像が合っているか確かめること。\n"
             + "\n".join("  " + x[1:] for x in lines)))


IMAGE_NAMES_HOW = "この XML は登載に使わず、変換レポートを添えて開発者に知らせてください。"


def _image_names_action(r):
    """要対応 image_names: 最終の XML の画像の名前が、画像を入れる場所の一覧と合わない（pipeline.image_problems。変換ツールの不具合の
    守りで、ふつうは出ない。修正計画 W1 の 4.2）。なければ None。"""
    issues = getattr(r, "image_problems", [])
    if not issues:
        return None
    what = "。".join(issues)
    return Action(
        NEEDS_ACTION, "image_names",
        top=f"> **要対応: XML の画像の名前に不具合があります（変換ツールの不具合の可能性。9 章）。** XML の中の画像の名前が、画像を入れる場所の一覧と合いません（{esc(what)}）。{IMAGE_NAMES_HOW}",
        checklist=f"- [ ] **XML の画像の名前の不具合**（9 章）: この XML は登載に使わず、変換レポートを添えて開発者に知らせる",
        box_title="XML の画像の名前に不具合があります（要対応。変換ツールの不具合の可能性）",
        box_detail=f"XML の中の画像の名前が、画像を入れる場所の一覧と合いません（{what}）。{IMAGE_NAMES_HOW}",
        cli=f"要対応: XML の画像の名前に不具合があります（変換ツールの不具合の可能性。レポートの冒頭と 9 章）: {what}。この XML は登載に使わないこと。")


LOST_AUTONUM_WHY = ("Word では段落の先頭に番号が表示されますが、XML のその段落には番号がありません（変換ツールの不具合の可能性があります）。"
                    "番号は docx の文字ではないため、文字の不変性チェックでは見つかりません。")


def lost_autonum_action(r):
    """Word の自動番号があるのに XML に番号を出さなかった段落（pipeline.lost_autonums）。なければ None。"""
    lost = getattr(r, "lost_autonums", None) or []
    if not lost:
        return None
    n = len(lost)
    return Action(
        NEEDS_ACTION, "autonum_lost",
        top="\n".join([f"> **要対応: Word の自動番号が XML に出ていない段落が {n} 件あります（8 章）。** {LOST_AUTONUM_WHY}"
                        "変換レポートを添えて開発者に知らせてください。", ">"]
                      + [f"> - {esc(lost_autonum_label(ln))}" for ln in lost]),
        checklist=(f"- [ ] **XML に出ていない Word の自動番号 {n} 件**（8 章）: 変換レポートを添えて開発者に知らせる"
                   "（変換ツールの不具合の可能性がある）: " + "、".join(esc(ln.src) for ln in lost)),
        box_title=f"Word の自動番号が XML に出ていない段落が {n} 件あります（要対応）",
        box_detail=(f"{LOST_AUTONUM_WHY}変換レポートを添えて開発者に知らせてください（レポートの冒頭と 8 章）。\n"
                    + "\n".join(f"・{lost_autonum_label(ln)}" for ln in lost)),
        cli=(f"要対応: Word の自動番号が XML に出ていない段落 {n} 件（変換ツールの不具合の可能性がある。レポートの冒頭と 8 章）。"
             "変換レポートを添えて開発者に知らせること。\n"
             + "\n".join(f"  {ln.src}: 「{ln.number}」…" for ln in lost)))


SYMBOL_KIND_JA = {"bullet": "箇条書きの記号", "sym": "本文の記号", "text": "本文の記号"}
SYMBOL_SAMPLES = 5      # 記号の置き換えの要確認に並べる段落の数（全件はレポートの 8 章）
SYMBOL_CONTEXT = 10     # 本文の記号の抜粋の、記号の前後の文字数

# 箇条書きの記号は、Word の箇条書きの設定が付ける記号で、本文の文字ではないので、打ち直せない（設定で選び直す）
BULLET_HOW = ("Word で、その箇条書きを選び、［ホーム］の箇条書きの▼にある［新しい行頭文字の定義］で、普通の記号に選び直してください")
BODY_HOW = "Word でその記号を普通の文字（［挿入］の［記号と特殊文字］から Unicode の記号）に打ち直してください"


def _para_ref(plan, src, mark: str = "") -> str:
    """要確認・要対応に並べる段落の指し方: 段落の ID（場所）「文字の抜粋」。場所は plan.locations（ほかの知らせと同じ）。
    mark があれば、段落の文字の中のその文字の前後の抜粋（なければ冒頭）。"""
    place = plan.locations.get(src, "") if plan is not None and getattr(plan, "locations", None) else ""
    para = plan.paras.get(src) if plan is not None and getattr(plan, "paras", None) else None
    text = para.plain() if para is not None else ""
    if text.strip():
        i = text.find(mark) if mark else -1
        if i >= 0:
            n = SYMBOL_CONTEXT
            text = ("…" if i > n else "") + text[max(0, i - n):i + len(mark) + n] + ("…" if len(text) > i + len(mark) + n else "")
        else:
            text = esc(text.strip(), 15)
    return f"{src}{'（' + esc(place) + '）' if place else ''}" + (f"「{esc(text)}」" if text.strip() else "")


def symbol_groups(r) -> list:
    """記号フォントの記号の置き換え（Result.symbols_replaced）のうち、要確認で知らせるもの（SymbolReplaced.known でない。0.31.1 までは
    置き換えていなかったもの）を、種類（箇条書きの記号・本文の記号）・フォント・置き換えた文字ごとにまとめたもの
    [(種類, フォント, 置き換えた文字, 個数, [段落の ID])]（文書の順。段落の ID は重ねない）。"""
    groups = {}
    for s in getattr(r, "symbols_replaced", None) or []:
        if s.known:
            continue
        kind = SYMBOL_KIND_JA[s.kind]
        g = groups.setdefault((kind, s.font, s.to), [0, []])
        g[0] += 1
        if s.src not in g[1]:
            g[1].append(s.src)
    return [(k, f, to, n, srcs) for (k, f, to), (n, srcs) in groups.items()]


def _symbol_line(g, plan=None, with_paras=True) -> str:
    kind, font, to, n, srcs = g
    paras = ""
    if with_paras and kind != SYMBOL_KIND_JA["bullet"]:
        paras = "。段落 " + "・".join(_para_ref(plan, x, to) for x in srcs[:SYMBOL_SAMPLES]) + ("ほか" if len(srcs) > SYMBOL_SAMPLES else "")
    return f"{kind}（{font}）を「{to}」に置き換えました（{n} か所{paras}）"


def _symbol_action(r):
    """記号フォント（Symbol・Wingdings 系）の私用領域の符号を、対応する普通の Unicode の文字に置き換えたもの（pipeline.symbols_replaced）。
    なければ None。置き換えた記号が正しいかは機械では確かめられないので、要確認として 1 件にまとめて知らせる（PDF を指定した変換では
    出版版 PDF の記号と、指定していない変換では Word の表示と、同じか確かめてもらう）。"""
    groups = symbol_groups(r)
    if not groups:
        return None
    n = sum(g[3] for g in groups)
    plan = getattr(r, "plan", None)
    ref = "出版版 PDF の記号" if getattr(r, "has_pdf", False) else "Word の表示"
    fixes = []
    if any(g[0] == SYMBOL_KIND_JA["bullet"] for g in groups):
        fixes.append(f"箇条書きの記号なら、{BULLET_HOW}")
    if any(g[0] != SYMBOL_KIND_JA["bullet"] for g in groups):
        fixes.append(f"本文の記号なら、{BODY_HOW}")
    how = f"置き換えた記号が、{ref}と同じか確かめてください。違っていれば、" + "。".join(fixes) + "。そのうえで変換し直してください"
    lines = [_symbol_line(g, plan) for g in groups]
    return Action(
        TO_CHECK, "symbol_replaced",
        top="\n".join([f"> **要確認: 記号フォント（Wingdings・Symbol など）の記号を、対応する普通の文字に置き換えました（{n} か所。8 章）。** "
                        f"{how}。", ">"] + [f"> - {esc(x)}" for x in lines]),
        checklist=f"- [ ] **記号フォントの記号を普通の文字に置き換えたもの {n} か所**（8 章）: {ref}と同じか確かめる",
        box_title=f"記号フォントの記号を普通の文字に置き換えました（{n} か所。要確認）",
        box_detail=(f"{how}（Word で直した docx を{step('docx')}でアップロードし直し、そこから順にやり直す。"
                    "レポートの冒頭と 8 章）。\n" + "\n".join(f"・{x}" for x in lines)),
        cli=(f"要確認: 記号フォントの記号を普通の文字に置き換えた（{n} か所。レポートの冒頭と 8 章）。{how}。\n"
             + "\n".join(f"  {x}" for x in lines)))


PUA_KIND_JA = {True: "箇条書きの記号", False: "本文の文字"}
PUA_SAMPLES = 5         # 読めない文字の要対応に並べる段落の数（全件はレポートの 8 章）


def pua_groups(r) -> list:
    """XML に残った私用領域の文字（Result.pua_chars）を、種類（箇条書きの記号か本文の文字か）・フォント・符号ごとにまとめたもの
    [(箇条書きの記号か, フォント, 符号, 個数, [PuaChar])]（文書の順）。"""
    groups = {}
    for pc in getattr(r, "pua_chars", None) or []:
        g = groups.setdefault((bool(pc.generated), pc.font or "", pc.code), [0, []])
        g[0] += pc.count
        g[1].append(pc)
    return [(k[0], k[1], k[2], v[0], v[1]) for k, v in groups.items()]


def pua_label(g, plan=None) -> str:
    """XML に残った私用領域の文字 1 グループ（pua_groups）の 1 行。例: 箇条書きの記号（Wingdings の U+F0B1）が 12 か所残っています。
    段落 d95（本文 > 3．方法）「番号付きの質問」・…ほか"""
    gen, font, code, n, pcs = g
    kind = PUA_KIND_JA[gen]
    head = f"{kind}（{font or 'フォント不明'}の U+{code:04X}）が {n} か所残っています"
    refs, seen = [], set()
    for pc in pcs:
        if pc.src and pc.src not in seen:
            seen.add(pc.src)
            refs.append(pc)
    if not refs:
        return head + "（段落に結び付かない文字）"
    shown = "・".join(_pua_ref(pc) for pc in refs[:PUA_SAMPLES])
    return f"{head}。段落 {shown}" + (f"ほか {len(refs) - PUA_SAMPLES} 段落" if len(refs) > PUA_SAMPLES else "")


def _pua_ref(pc) -> str:
    place = f"（{esc(pc.location)}）" if pc.location else ""
    return f"{pc.src}{place}" + (f"「{esc(pc.text)}」" if pc.text else "")


PUA_WHY = ("私用領域の文字は J-STAGE の画面では読めない文字（豆腐）になります。Word の記号フォント（Wingdings など）で打たれた記号が、"
           "この変換ツールの対応表にない記号のままです。")


def pua_how(r) -> str:
    """読めない文字（要対応 pua_left）の直し方。箇条書きの記号は Word の設定で選び直し、本文の文字は打ち直す。"""
    kinds = {g[0] for g in pua_groups(r)}
    fixes = ([f"箇条書きの記号は、{BULLET_HOW}"] if True in kinds else []) + ([f"本文の文字は、{BODY_HOW}"] if False in kinds else [])
    return "。".join(fixes) + "。そのうえで変換し直してください"


def _pua_left_action(r):
    """最終の XML に残った私用領域の文字（pipeline.pua_chars）。なければ None。種類・フォント・符号ごとの件数でまとめる。"""
    groups = pua_groups(r)
    if not groups:
        return None
    n = sum(g[3] for g in groups)
    plan = getattr(r, "plan", None)
    how = pua_how(r)
    lines = [pua_label(g, plan) for g in groups]
    return Action(
        NEEDS_ACTION, "pua_left",
        top="\n".join([f"> **要対応: XML に、J-STAGE の画面で読めない文字（私用領域の文字）が {n} 個残っています（8 章）。** {PUA_WHY}"
                        f"{how}。", ">"] + [f"> - {esc(x)}" for x in lines]),
        checklist=f"- [ ] **XML に残った読めない文字（私用領域の文字）{n} 個**（8 章）: {how}",
        box_title=f"XML に、読めない文字（私用領域の文字）が {n} 個残っています（要対応）",
        box_detail=(f"{PUA_WHY}{how}（Word で直した docx を{step('docx')}でアップロードし直し、そこから順にやり直す。"
                    "レポートの冒頭と 8 章）。\n" + "\n".join(f"・{x}" for x in lines)),
        cli=(f"要対応: XML に読めない文字（私用領域の文字）が {n} 個残っている（レポートの冒頭と 8 章）。{how}。\n"
             + "\n".join(f"  {x}" for x in lines)))


STYLE_HIDDEN_SAMPLES = 5     # スタイルの隠し文字の要確認に並べる段落の数（全件はレポートの 6 章）


def _style_hidden_paras(r) -> list:
    """スタイル・既定の書式の設定で隠した文字（Result.style_hidden）を段落ごとにまとめたもの [(段落 ID, 隠した文字)]（文書の順）。"""
    per = {}
    for src, text in r.style_hidden:
        per[src] = per.get(src, "") + text
    return list(per.items())


def _style_hidden_action(r):
    """スタイル（段落スタイル・文字スタイル）や既定の書式の設定で隠し文字になっていて、XML に出力しなかった文字・画像
    （docx_reader が記録する。ooxml.HiddenRule.run_hidden_by が "style"）。空白だけの文字なら数えない。なければ None。

    ランに直接付けた隠し文字（w:vanish・w:specVanish）は Word と同じに隠せるが、スタイル・既定の書式の w:vanish の規則は暫定で
    （修正計画の G。Word では確かめていない）、不変性チェックも同じ規則で docx の文字を取り出すので、規則が Word と違っても
    検出できない（Word で見える文字が XML から消えても合格する）。隠した文字が利用者の目に入るように、要確認として知らせる
    （終了コードは 0）。直接の指定だけで隠した文字は、0.25.0 までと同じく 6 章に載せるだけ。
    """
    paras = [(s, t) for s, t in _style_hidden_paras(r) if t.strip()]
    imgs = r.style_hidden_images
    if not paras and not imgs:
        return None
    what = "、".join(x for x in (f"文字が {len(paras)} 段落" if paras else "", f"画像が {len(imgs)} 件" if imgs else "") if x)
    samples = "、".join([f"{s}「{esc(t.strip(), 15)}」" for s, t in paras[:STYLE_HIDDEN_SAMPLES]]
                       + (["ほか"] if len(paras) > STYLE_HIDDEN_SAMPLES else [])
                       + ([f"画像 {'・'.join(imgs)}"] if imgs else []))
    how = ("この判定は暫定で、Word の表示と違うことがあります。Word で開き（［ホーム］の［編集記号の表示/非表示］はオフにして）、"
           "これらが表示されないことを確かめてください。表示されるものがあれば、XML に出力されていないので、変換レポートを添えて"
           "開発者に知らせてください。")
    head = f"Word のスタイル（段落スタイル・文字スタイル）や既定の書式の設定で隠し文字になっている{what}あり、XML に出力していません"
    return Action(
        TO_CHECK, "style_hidden",
        top=f"> **要確認: {head}（6 章）。** {how}対象: {samples}",
        checklist=(f"- [ ] **スタイルの設定で隠し文字になっているもの**（{what}。6 章）: Word で表示されないことを確かめる"
                   "（表示されるなら開発者に知らせる）"),
        box_title="スタイルの設定で隠し文字になっている文字を出力していません（要確認）",
        box_detail=f"{head}。{how}（レポートの冒頭と 6 章）\n対象: {samples}",
        cli=(f"要確認: {head}（レポートの冒頭と 6 章）。Word で表示されないことを確かめ、表示されるものがあれば"
             "開発者に知らせること"))


RESULTLESS_MARK = "［ここ］"     # 段落の文字の抜粋で、結果のないフィールドがある位置の印（レポートの表示だけ。XML には入れない）
RESULTLESS_SEGMENTS = 3         # 要確認に並べる抜粋の数（1 段落あたり。全件はレポートの 6 章）
RESULTLESS_LINES = 5            # 要確認に並べる段落の数（ほかは「ほか N 段落」。全件はレポートの 6 章）
RESULTLESS_CONTEXT = 12         # 抜粋の、印の前後の文字数


def _resultless_by_para(r) -> list:
    """結果を持たないフィールドで Word では表示のあるもの（Result.resultless_fields）を段落ごとにまとめたもの [(段落 ID, [ResultlessField])]
    （文書の順）。"""
    per = {}
    for f in getattr(r, "resultless_fields", None) or []:
        per.setdefault(f.src, []).append(f)
    return list(per.items())


def _resultless_excerpt(f) -> str:
    """段落の文字の抜粋。フィールドのある位置に印（RESULTLESS_MARK）を入れる（どこが抜けているかが分かるように）。"""
    n = RESULTLESS_CONTEXT
    head = f.text[max(0, f.pos - n):f.pos]
    tail = f.text[f.pos:f.pos + n]
    return esc(("…" if f.pos > n else "") + head + RESULTLESS_MARK + tail + ("…" if len(f.text) > f.pos + n else ""))


def _resultless_keys(r) -> dict:
    """段落の ID -> その段落の、画像で補える位置（任意の置き場所。XML に出した <inline-graphic> の位置）の幹の一覧（修正計画 W1 の手順 15）。"""
    plan = getattr(r, "plan", None)
    if plan is None:
        return {}
    shown = {i.key for i in getattr(r, "images", None) or [] if i.kind == "optional"}
    out = {}
    for slot in plan.slots:
        if slot.kind == "optional" and slot.key in shown:
            out.setdefault(slot.src, []).append(slot.key)
    return out


def _resultless_line(src, fs, plan=None, keys=()) -> str:
    """1 段落ぶんの 1 行: 段落の ID（と場所）、種類、個数、抜粋。画像で補える位置があれば、その幹（任意の置き場所）も添える。"""
    place = plan.locations.get(src, "") if plan is not None and getattr(plan, "locations", None) else ""
    kinds = []
    for f in fs:
        label = FIELD_DRAWN[f.kind] if f.kind in FIELD_DRAWN else f.kind
        if label not in kinds:
            kinds.append(label)
    excerpts = " ／ ".join(_resultless_excerpt(f) for f in fs[:RESULTLESS_SEGMENTS]) + (" ／ ほか" if len(fs) > RESULTLESS_SEGMENTS else "")
    spare = f"（画像の幹: {'・'.join(keys)}）" if keys else ""
    return f"{src}{'（' + esc(place) + '）' if place else ''}: {'・'.join(kinds)} {len(fs)} か所「{excerpts}」{spare}"


def _resultless_field_action(r):
    """結果を持たないまま終わるフィールドのうち、Word では表示のあるもの（EQ の囲い文字・分数・ルビ、SYMBOL、フォームのチェックボックスなど。
    docx_reader が記録する）。なければ None。

    表示は Word がフィールドコードから描くもので docx の文字ではないので、XML には出ない（読み取りも検証も同じに捨てるため、不変性チェック
    は合格する）。囲い文字を合成して文字を作ることはしない（docx にない文字を作らない）。元の論文が特殊な作り方をしているときなので、要確認として
    1 件にまとめて知らせ、取れる行動は「Word で普通の文字か数式に打ち直して変換し直す」と、画像で補う（任意の置き場所。入れなくてもよい。
    手順 15）の 2 つにする。"""
    paras = _resultless_by_para(r)
    if not paras:
        return None
    n = sum(len(fs) for _, fs in paras)
    plan = getattr(r, "plan", None)
    keyed = _resultless_keys(r)
    lines = [_resultless_line(src, fs, plan, keyed.get(src, ())) for src, fs in paras[:RESULTLESS_LINES]]
    if len(paras) > RESULTLESS_LINES:
        lines.append(f"ほか {len(paras) - RESULTLESS_LINES} 段落（全件はレポートの 6 章）")
    what = "Word では表示されるのに、XML に出せていないかもしれない文字（囲い文字など）があります"
    why = ("Word のフィールドというしくみ（囲い文字・分数・根号・ルビなど）で描いている文字は、docx に文字として入っていないため、"
           "XML には出ません。")
    if getattr(r, "route", "docx") == "pdf":
        why += "出版版 PDF で補った docx では、PDF から別の文字として補われていることがあります。"
    how = ("XML のその位置に文字があるかを確かめ、なければ、Word で、その部分を普通の文字（③ など）か Word の数式に打ち直して、"
           "変換し直してください。直さなければ、その文字は XML で抜けたままになります")
    if keyed:
        how += ("。画像で補うこともできます（各行の「画像の幹」の画像を、図の画像と同じ所で入れます。"
                "入れた画像は、その文字の位置に画像として入ります。入れなくてもかまいません。手順には数えません）")
    mark = f"対象（{RESULTLESS_MARK}は、文字のある位置の印です。レポートの表示だけで、XML には入りません）:"
    return Action(
        TO_CHECK, "resultless_field",
        top="\n".join([f"> **要確認: {what}（{n} か所。6 章）。** {why}{how}。", ">", f"> {mark}"] + [f"> - {x}" for x in lines]),
        checklist=f"- [ ] **Word では表示されるのに XML に出せていないかもしれない文字（囲い文字など）{n} か所**（6 章）: XML に文字があるか確かめ、なければ Word で普通の文字か数式に打ち直す",
        box_title=f"Word では表示されるのに、XML に出せていないかもしれない文字があります（{n} か所。要確認）",
        box_detail=(f"{why}{how}（Word で直した docx を{step('docx')}でアップロードし直し、そこから順にやり直す。"
                    f"レポートの冒頭と 6 章）。\n{mark}\n" + "\n".join(f"・{x}" for x in lines)),
        cli=(f"要確認: {what}（{n} か所。レポートの冒頭と 6 章）。{how}。\n{mark}\n" + "\n".join(f"  {x}" for x in lines)))


EMPHASIS_SAMPLES = 5     # 傍点の要確認に並べる段落の数


def _emphasis_action(r):
    """傍点（圏点。w:em）のかかった文字がある段落（docx_reader が記録する。Result.emphasis）。なければ None。

    JATS に傍点に対応する要素がないので、XML は変えず（文字だけを出力する）、傍点が消えることを知らせるだけ（終了コードは 0）。
    空白だけの傍点は数えない。
    """
    per = {}
    for src, text in r.emphasis:
        per[src] = per.get(src, "") + text
    paras = [(s, t) for s, t in per.items() if t.strip()]
    if not paras:
        return None
    n = len(paras)
    samples = _para_samples(paras, EMPHASIS_SAMPLES)
    how = ("XML には傍点を出せないので、文字だけが出力されています（傍点は消えます）。出版版 PDF と見比べて、"
           "傍点がなくても意味が通るかを確かめてください（docx の文字は変えないでください）")
    head = f"傍点（圏点）のかかった文字が {n} 段落にあります"
    return Action(
        TO_CHECK, "emphasis_mark",
        top=f"> **要確認: {head}。** {how}。対象: {samples}",
        checklist=f"- [ ] **傍点（圏点）のかかった文字**（{n} 段落）: XML では傍点が消えることを確かめる",
        box_title="傍点（圏点）を XML に出力していません（要確認）",
        box_detail=f"{head}。{how}。\n対象: {samples}",
        cli=f"要確認: {head}。XML には傍点を出せず、文字だけが出力されています。対象: {samples}")


def _abstract_ja_action(r):
    """英文要旨の中の、かな・漢字が 3 割以上の段落（structure.Classifier.check_abstract_ja。自動では移さない）。なければ None。"""
    plan = r.plan
    if not plan.abstract_ja:
        return None
    n = len(plan.abstract_ja)
    samples = _para_samples([(s, plan.paras[s].text_only()) for s in plan.abstract_ja])
    return Action(
        TO_CHECK, "abstract_ja",
        top=(f"> **要確認: 英文要旨に、和文と思われる段落が {n} 件あります（10 章）。** 資料・付録などの和文が英文要旨に入っている"
             "かもしれません。資料なら、Word で資料の見出しの段落に章・節・項見出しのスタイルを付けて（見出しがなければ、資料の前に"
             f"「資料1」「資料（授業プリント）」などの見出しを付けて）、変換し直してください。対象の段落: {samples}"),
        checklist=(f"- [ ] **英文要旨の中の和文の段落**（{n} 件。10 章）: 資料などの和文なら、Word で資料の見出しに見出しのスタイルを"
                   "付けて（見出しがなければ見出しを付けて）変換し直す"),
        box_title="英文要旨に和文の段落があります（要確認）",
        box_detail=(f"英文要旨に、かな・漢字が 3 割以上の段落が {n} 件あります。資料・付録などの和文が英文要旨に入っているかもしれません。"
                    "資料なら、Word で資料の見出しの段落に章・節・項見出しのスタイルを付けて（見出しがなければ、資料の前に「資料1」"
                    f"などの見出しを付けて）から、変換し直してください（レポートの冒頭と 10 章）。\n対象の段落: {samples}"),
        cli=(f"要確認: 英文要旨に和文と思われる段落が {n} 件あります（レポートの冒頭と 10 章）。資料なら、docx で資料の見出しに見出しの"
             "スタイルを付けて（見出しがなければ見出しを付けて）変換し直すこと"))


def _app_after_refs_action(r):
    """引用文献・注・付記・謝辞の中の、資料の見出しと思われる段落（structure.Classifier.build_back）。なければ None。

    暫定の判断で、引用文献などの後ろの資料は資料（app-group）にせず、知らせるだけにしている（決定事項 8(b) は利用者に未確認）。
    """
    plan = r.plan
    runs = [s for s in plan.ref_yearless_runs if s not in plan.app_after_refs]
    if not plan.app_after_refs and not runs:
        return None
    n = len(plan.app_after_refs) + len(runs)
    samples = _para_samples([(s, plan.paras[s].text_only()) for s in plan.app_after_refs])
    run_samples = _para_samples([(s, plan.paras[s].text_only()) for s in runs])
    # 資料の見出しは見つからないが、引用文献の中に年の読めない段落が続く所（refparse.ref_continuations。資料の中身の疑い。C001）
    from .refparse import REF_CONT_RUN
    run_line = (f"引用文献の中に、年の読めない段落が {REF_CONT_RUN} 件以上続く所があります（資料の中身かもしれません）: {run_samples}"
                if runs else "")
    title = APP_TITLE_TOP if plan.app_after_refs else APP_RUN_TITLE_TOP
    # することの一覧の見出しも、見つけたもの（資料の見出し・年の読めない段落の並び）で変える（点検 review19 の 3 回目の利用者向け 4）
    label = "資料の見出しか中身" if plan.app_after_refs and runs else ("資料の見出し" if plan.app_after_refs else "資料の中身")
    found = "、".join(x for x in (f"対象の段落: {samples}" if plan.app_after_refs else "", run_line) if x)
    return Action(
        TO_CHECK, "app_after_refs",
        top=(f"> **要確認: {title}（10 章）。** 今の版では、引用文献などの後ろの"
             f"資料は資料（付録）として扱わず、引用文献などの段落のまま出力しています。資料なら、{APP_MOVE_HOW}{found}"),
        checklist=(f"- [ ] **引用文献などの後ろの{label}**（{n} 件。10 章）: 資料なら、Word で英文要旨の後ろに移して"
                   "変換し直す"),
        box_title=APP_TITLE_BOX + "（要確認）",
        box_detail=("引用文献・注・付記・謝辞の中に、資料の見出しと思われる段落か、資料の中身と思われる段落があります。今の版では資料として扱わず、引用文献などの"
                    f"段落のまま出力しています。資料なら、{APP_MOVE_HOW}（レポートの冒頭と 10 章）\n{found}"),
        cli=("要確認: 引用文献などの後ろに、資料の見出しか中身と思われる段落があります（レポートの冒頭と 10 章）。資料なら、docx で英文要旨の"
             "後ろに移して変換し直すこと"))


def _note_overlap_action(r):
    """手で書いた注と Word の脚注・文末脚注の番号が重なる（structure.Classifier.attach_word_notes の plan.note_overlap）。なければ None。

    Word の注の番号は 1 から付けるので、「注」の節に手で書いた「1)」と同じ番号の別の注が注の一覧に並ぶ。番号を手で書いた注の
    後ろから続けるかは利用者に確かめていないので、番号は変えずに知らせるだけにしている。
    """
    plan = r.plan
    if not plan.note_overlap:
        return None
    marks = "、".join(r.journal.fn_mark.format(n=k) for k in plan.note_overlap)
    return Action(
        TO_CHECK, "note_overlap",
        top=(f"> **要確認: 手で書いた注と Word の脚注・文末脚注が両方あり、注の番号 {marks} が重なっています（10 章）。** 注の一覧に、"
             "同じ番号の別の注が並びます（本文からリンクしている注は、それぞれ正しい注を指します）。Word で、どちらかの書き方（本文に上付きの"
             "「1)」を書いて「注」の節にまとめる、または Word の脚注・文末脚注の機能）にそろえてから、変換し直してください。"),
        checklist=(f"- [ ] **注の番号の重なり**（{marks}。10 章）: 手で書いた注と Word の脚注・文末脚注のどちらかの書き方に"
                   "そろえて変換し直す"),
        box_title="注の番号が重なっています（要確認）",
        box_detail=(f"手で書いた注と Word の脚注・文末脚注が両方あり、注の一覧に同じ番号（{marks}）の別の注が並びます。Word で"
                    "どちらかの書き方にそろえてから、変換し直してください（レポートの冒頭と 10 章）。"),
        cli=(f"要確認: 手で書いた注と Word の脚注・文末脚注が両方あり、注の番号 {marks} が重なっています（レポートの冒頭と 10 章）。"
             "docx でどちらかの書き方にそろえて変換し直すこと"))


NOTE_UNLINKED_SHOWN = 5      # 要確認 note_unlinked に並べる注の数（残りは「ほか N 件」。全部は 3 章）
NOTE_MARK_SHOWN = 3          # 要確認 note_unlinked に添える、本文の注番号の候補の段落の数
# 本文の注番号の候補（読むだけで、リンクはしない）: Unicode の上付き文字の「¹⁾」と「[1]」の形（_note_unlinked_action の手がかり）
# （形の名前・正規表現・Word の［検索］で探す文字）
RE_NOTE_MARK_FORMS = (("Unicode の上付き文字の「¹⁾」", re.compile("[⁰¹²³⁴-⁹]+⁾"), "⁾"), ("「[1]」", re.compile(r"\[[0-9０-９]{1,3}\]"), "["))


def _note_mark_hint(plan) -> str:
    """本文（注・引用文献の一覧を除く）にある注番号の候補の形と段落 ID（先頭 NOTE_MARK_SHOWN 段落）の文。なければ ""。
    利用者が Word で本文の注番号の場所を探す手がかり（読むだけ。リンクも XML も変えない。点検 review20 利用者向け 9）。"""
    out, keys = [], []
    for label, rx, key in RE_NOTE_MARK_FORMS:
        srcs = list(dict.fromkeys(q.src for q, where in body_paragraphs(plan) if where not in ("ref", "fn") and rx.search(q.text_only())))
        if srcs:
            # 段落 ID（英字）の後ろは空白、「段落」の後ろは空白なし
            more = f" ほか {len(srcs) - NOTE_MARK_SHOWN} 段落に" if len(srcs) > NOTE_MARK_SHOWN else " に"
            out.append(f"{label}の形の文字が本文の {'・'.join(srcs[:NOTE_MARK_SHOWN])}{more}あります")
            keys.append(f"「{key}」")
    if not out:
        return ""
    return "本文の注番号の候補: " + "。".join(out) + f"（Word の［検索］で{'や'.join(keys)}を探すと見つかります）"


def _note_unlinked_action(r):
    """要確認 note_unlinked（C067）: 手で書いた注で、番号が読み取れなかった注（複数の注が 1 件にまとまっていることがある）か、本文から
    参照（リンク）されていない注があるとき。なければ None。

    判定は 3 章の文（note_notes）と同じ report.note_problems（新しい判定を作らない。件数がずれない）。件数は注の数で数え、各行に当たる
    印（番号を読み取れない・本文から参照されていない）を全部書く。本文の注番号が Unicode の上付き文字（「¹⁾」）や「[1]」の形だと、注が
    リンクされず、番号が読めない注は 1 件にまとまる（本文の候補の段落を添える。_note_mark_hint）。AI による仕上げ（link_note・注の区切りの
    指定）でリンクされた注は数えない。AI の回答が入っているときは「AI でも直せる」と言わず、ai_boundary と同じ Word での直し方にそろえる
    （点検 review20 利用者向け 4）。XML は変えない（注の読み取りは変えない）。
    """
    plan = r.plan
    fns, order, unnum, unref = note_problems(plan)
    if not unnum and not unref:
        return None
    bad_num, bad_ref = {fn.fid for fn in unnum}, {fn.fid for fn in unref}
    hit = [fn for fn in fns if fn.fid in bad_num or fn.fid in bad_ref]

    def marks(fn):
        return "・".join(x for x, on in (("番号を読み取れない", fn.fid in bad_num), ("本文から参照されていない", fn.fid in bad_ref)) if on)

    def line(fn):
        place = _place_short(plan.locations.get(fn.paras[0].src, ""))
        head = esc(fn.paras[0].plain().strip(), 15)
        return (f"{fn.fid}（{fn.paras[0].src}" + (f"。{esc(place)}" if place else "") + (f"。「{head}」" if head else "")
                + (f"。{len(fn.paras)} 段落を 1 件の注にまとめています" if len(fn.paras) > 1 and fn.number is None else "")
                + f"）: {marks(fn)}")

    rows = [line(fn) for fn in hit]
    more = len(rows) - NOTE_UNLINKED_SHOWN
    shown = rows[:NOTE_UNLINKED_SHOWN] + ([f"ほか {more} 件（3 章）"] if more > 0 else [])
    hint = _note_mark_hint(plan) if unref else ""
    if hint:
        shown.append(hint)
    parts = "・".join(x for x, on in (("番号を読み取れない", unnum), ("本文から参照されていない", unref)) if on)
    title = f"注 {len(hit)} 件が正しく読み取れていない可能性があります（{parts}）"
    word = ("本文の注番号は上付き文字の「1)」（Word の［ホーム］の上付き）、注の一覧の各段落の先頭は「1)」の形にし、注 1 件を 1 つの段落にして")
    ai = getattr(r, "ai", None)
    ai_in = ai is not None and ai_state(r) in ("済み", "一部")
    # 文は印（番号を読み取れない unnum・本文から参照されていない unref）で分ける（番号を読み取れないだけの注に「リンクされていない」と
    # 言わない。AI の回答が入っているときは、区切りの点〈複数の注が 1 件〉を結果の文に書かない。点検 review20 利用者向けの 2 回目）
    if unnum and unref:
        state = "本文からリンクされていないか、番号を読み取れていません"
    elif unref:
        state = "本文からリンクされていません"
    else:
        state = "番号を読み取れていません"
    if ai_in:
        fixed = any(b.kind in NOTE_BOUNDARY_KINDS for b in getattr(ai, "boundaries", None) or [])
        how = (("AI の回答で注の区切りは直しましたが（2 章）、" if fixed else "AI の回答も入れましたが、") + f"下に挙げた注は{state}。"
               f"Word で{word}保存し、AI の回答を入れずに変換し直すと、区切りとリンクの両方が直ります（本文の注番号が Unicode の上付き文字や"
               "「[1]」の形だと、注にリンクされず、注が 1 件にまとまることがあります）")
    else:
        how = (f"Word で{word}、変換し直してください（本文の注番号が Unicode の上付き文字や「[1]」の形だと、注にリンクされず、"
               "注が 1 件にまとまることがあります）。AI による仕上げ（注のリンク・注の区切りの指定）でも直せます")
    if unref and unnum and not ai_in:
        result = "本文から注へのリンクがなく、複数の注が 1 件の注にまとまっていることがあります"
    elif unref:
        result = "本文から注へのリンクがありません"
    elif not ai_in:
        result = "番号を読み取れなかった注には、複数の注が 1 件にまとまっていることがあります"
    else:
        result = ""
    note3 = "3 章の注の確認と同じ注です。ここでは注の場所と Word での直し方を挙げます"
    how += f"。このまま登載すると、{result}（{note3}）" if result else f"。{note3}"
    return Action(
        TO_CHECK, "note_unlinked",
        top=f"> **要確認: {title}（3 章）。** {how}。" + "".join(f"\n>\n> - {x}" for x in shown),
        checklist=f"- [ ] **注の読み取り**（注 {len(hit)} 件: {parts}。3 章）: 本文の注番号と注の一覧の番号を「1)」の形にそろえて変換し直す",
        box_title=title + "（要確認）",
        box_detail=(f"{how}（直した docx を{step('docx')}でアップロードし直し、そこから順にやり直す）。" + "".join("\n・" + x for x in shown)),
        cli=f"要確認: {title}（レポートの冒頭と 3 章）。{how}。" + "".join("\n  " + x for x in shown))


LINK_IRI_SHOWN = 5       # 要確認 link_iri に並べるリンクの数（残りは「ほか N 件」）
LINK_IRI_JA = {"iri": "リンク先に日本語などの文字がある", "scheme": "http・https・mailto・ftp 以外のリンク先"}


def _link_iri_action(r):
    """要確認 link_iri（C089・C090）: XML に出す外部リンクのリンク先（xlink:href）に非 ASCII の文字（日本語など）が入っているか、
    リンク先が http・https・mailto・ftp 以外（Word のハイパーリンクの file:・javascript:・パソコンの中のパスなど）のとき。なければ None。

    判定は linker.href_problems。URL の直後に空白なしで続く文字のうち、閉じていないかっこ・「参照」「閲覧」などの語はリンクの範囲に
    入れない（linker._trim）が、それ以外は推定で切らない（パーセント符号化していない IRI を途中で切ると、別のページを指す正しく見える
    リンクになるため）。リンク先の値は書き換えず、リンクも外さない（XML は変えない）。"""
    from .linker import href_problems
    plan = r.plan
    probs = href_problems(plan)
    if not probs:
        return None

    def line(x):
        place = _place_short(plan.locations.get(x.src, ""))
        return (f"{x.src}（" + (f"{esc(place)}。" if place else "") + f"リンクの文字「{esc(x.text, 40)}」。リンク先「{esc(x.href, 80)}」。"
                + "・".join(LINK_IRI_JA[k] for k in x.kinds) + "）")
    rows = [line(x) for x in probs[:LINK_IRI_SHOWN]] + ([f"ほか {len(probs) - LINK_IRI_SHOWN} 件"] if len(probs) > LINK_IRI_SHOWN else [])
    n = len(probs)
    kinds = {k for x in probs for k in x.kinds}
    hows = []
    if "iri" in kinds:
        hows.append("リンク先に日本語などの文字があるもの: URL の直後に空白なしで文字が続くと、その文字までリンク先に入ることがあります"
                    "（閉じていないかっこと、「参照」「閲覧」などで終わる部分はリンクに入れていませんが、それ以外は推定で切っていません）。"
                    "リンク先が正しければ（日本語のページ名の URL など）そのままでかまいません。違っていれば、Word で URL の文字だけを選び、"
                    "［挿入］の［リンク］で正しいアドレスを入れて保存し、変換し直してください（文字は変わらず、Word のリンクの範囲とリンク先が"
                    " XML のリンクになります）")
    if "scheme" in kinds:
        hows.append("http・https・mailto・ftp 以外のリンク先（パソコンの中のファイル〈file:〉・javascript: など）: J-STAGE の読者は開けません。"
                    "Word でそのハイパーリンクを右クリックし、［リンクの編集］で正しい URL にするか、［リンクの削除］をして、変換し直して"
                    "ください（変換ツールはリンク先の値を変えていません）")
    how = "。".join(hows)
    title = f"リンク先（URL）の形を確かめてください（{n} 件）"
    return Action(
        TO_CHECK, "link_iri",
        top=f"> **要確認: {title}。** {how}。" + "".join(f"\n>\n> - {x}" for x in rows),
        checklist=f"- [ ] **リンク先（URL）の形**（{n} 件）: リンク先が正しいかを確かめ、違っていれば Word でリンクを直して変換し直す",
        box_title=title + "（要確認）",
        box_detail=f"{how}（Word で直したときは、直した docx を{step('docx')}でアップロードし直し、そこから順にやり直す）。" + "".join("\n・" + x for x in rows),
        cli=f"要確認: {title}（レポートの冒頭）。{how}。" + "".join("\n  " + x for x in rows))


XREF_TAG = '<xref ref-type="fig" rid="図の id">'
FIG_ID_TAG, TABLE_ID_TAG = '<fig id="…">', '<table-wrap id="…">'


# タグの形: <名前>・<名前/>・<名前 属性="値" …>（属性は 名前="値" の形だけ）。名前が JATS の要素名のときだけ、md_tag が囲む
RE_MD_TAG = re.compile(r'(?<!`)<([A-Za-z][\w:.-]*)(?:\s+[\w:.-]+="[^"<>\n]*")*\s*/?>(?!`)')


def md_tag(text: str) -> str:
    """文の中の XML のタグ（<xref …>・<label> など）を、Markdown のコード（バッククォート）で囲む。

    レポート（Markdown）の文に生のタグを書くと、Markdown を HTML にしたときに HTML のタグとして扱われて消えるため
    （Colab の「変換レポートの全文を見る」）。囲むのは、名前が JATS の要素名（validate.jats_element_names）のタグの形だけ。
    docx の文字を引用した文（10 章の警告に引用した段落の抜粋など）の「x<y かつ z>w」のような < > は、タグの形でも要素名でもないので
    変えない（文字を書き換えない）。画面の枠（HTML をエスケープして出す）やコマンドラインの文には使わない。
    """
    from .validate import jats_element_names
    names = jats_element_names()
    return RE_MD_TAG.sub(lambda m: f"`{m.group(0)}`" if m.group(1) in names else m.group(0), text)


def float_ref_manual() -> str:
    """リンクしなかった図・表の参照に、利用者が手でリンクを付ける方法の文（_float_ref_action。AI の状態によらない。AI を勧める文は
    推奨の手順 ai_finish の 1 か所。修正計画 W8 の 4.3）。"""
    return (f'{XREF_TAG}（表への参照は ref-type="table"、rid は表の id）を手で足してください。図の id は XML の {FIG_ID_TAG}'
            f'（表は {TABLE_ID_TAG}）にあります。')


def float_ref_how(r, screen: str = "report") -> str:
    """リンクしなかった図・表の参照に、利用者がリンクを付ける方法の文（_float_ref_action）。レポートの文（screen が "report"）は
    タグを Markdown のコードで囲む。"""
    text = float_ref_manual()
    return md_tag(text) if screen == "report" else text


FLOAT_REF_SHOWN = 6     # 図・表の参照の要確認に並べる参照の数（全件は 4 章の判断の一覧）


def _float_ref_action(r):
    """番号から図・表を決められず、リンクしなかった図・表の参照（plan.float_unlinked。linker.Linker.float_refs）。なければ None。

    同じ種類のキャプションの番号が重なる（図1・図1）か、キャプションに枝番がある（図1-1・図1-2、図2.1）ときの、その番号の参照。
    どの図・表への参照か決められないので、誤ったリンクを出さず、リンクしないで知らせる（手で確かめ、必要なら手でリンクを付ける）。
    """
    plan = r.plan
    if not plan.float_unlinked:
        return None
    counts = {}
    for u in plan.float_unlinked:
        counts[u.text] = counts.get(u.text, 0) + 1
    items = list(counts.items())
    shown = "、".join(f"「{esc(t)}」" + (f"（{c} か所）" if c > 1 else "") for t, c in items[:FLOAT_REF_SHOWN]) \
        + ("ほか" if len(items) > FLOAT_REF_SHOWN else "")
    n = len(plan.float_unlinked)
    return Action(
        TO_CHECK, "float_ref",
        top=("> **要確認: 図・表の番号が重なる、または枝番がある（図1-1・図1-2 など）ため、どの図・表か決められず、リンクしなかった"
             f"参照があります（{n} か所。4 章）。** 参照: {shown}。誤ったリンクを出さないよう、これらの参照には図・表へのリンクを"
             "付けていません。リンクがなくても J-STAGE には登載できるので、そのままでもかまいません。付けるときは、PDF と照らして"
             "どの図・表への参照かを確かめ、XML の該当箇所に" + float_ref_how(r)),
        checklist=(f"- [ ] **リンクしなかった図・表の参照**（{n} か所。4 章）: 番号が重なる・枝番があるため。リンクがなくても登載できる。"
                   "付けるなら、PDF と照らして XML に " + md_tag("<xref>") + " を足す"),
        box_title="図・表の参照のリンクを付けていない箇所があります（要確認）",
        box_detail=("図・表の番号が重なる、または枝番がある（図1-1・図1-2 など）ため、どの図・表か決められない参照には、リンクを付けて"
                    f"いません（誤ったリンクを出さないため）。\n対象の参照（{n} か所）: {shown}\n"
                    "リンクがなくても J-STAGE には登載できるので、そのままでもかまいません。付けるときは、PDF と照らしてどの図・表への参照かを"
                    "確かめ（場所はレポートの 4 章にあります）、XML の該当箇所に" + float_ref_how(r, "box")),
        cli=(f"要確認: 図・表の番号が重なる、または枝番があるため、リンクしなかった図・表の参照が {n} か所あります"
             f"（{shown}。レポートの冒頭と 4 章）。リンクがなくても登載できる。付けるなら、PDF と照らしてどの図・表かを確かめ、"
             "XML に <xref ref-type=\"fig\" rid=\"図の id\">（表は ref-type=\"table\"）を手で足すこと"
             "（図の id は XML の <fig id=\"…\">、表は <table-wrap id=\"…\"> にある）。"))


FN_GUESS_SHOWN = 5      # 注の扱いの要確認に並べる件数（全件は 4 章の判断の一覧）


def _fn_guess_span_text(r, checks) -> str:
    """「注」の段落を「注見出し」スタイルにしたとき、注の節に入る段落の説明（要確認 fn_guess の助言に添える。plan.fn_guess_span）。

    「注」ごとに、その後ろの最初と最後の段落（ID と文字の抜粋）と件数。次の後付けの見出しまで（後ろの章見出しとその本文も含む）。
    注の節に入る段落がない（記録がない）ときは空文字。
    """
    plan = r.plan
    rows = []
    for head, _, _ in checks[:FN_GUESS_SHOWN]:
        srcs = [s for s in plan.fn_guess_span.get(head, ()) if s in plan.paras]
        if not srcs:
            continue
        first, last = (_para_samples([(s, plan.paras[s].text_only())]) for s in (srcs[0], srcs[-1]))
        rows.append(f"{head} の後ろの {first}の 1 段落" if len(srcs) == 1
                    else f"{head} の後ろの {first}から {last}までの {len(srcs)} 段落")
    return "、".join(rows) + ("ほか" if len(checks) > FN_GUESS_SHOWN and rows else "")


def _fn_guess_span_clause(r, checks) -> str:
    """助言「注見出し」に添える、注の節に入る範囲の注意（top・checklist・box_detail・cli で同じ）。"""
    span = _fn_guess_span_text(r, checks)
    return ("「注見出し」にすると、その「注」の段落から次の後付けの見出し（引用文献・謝辞など）または文書の終わりまでの段落が、"
            "後ろの章見出しとその本文も含めてすべて注の節に入ります" + (f"（今回の範囲: {span}）" if span else "")
            + "。注の一覧が論文の最後にあるときの方法です。")


def _fn_guess_multi_clause(r) -> str:
    """文字から注の見出しと推定される「注」の段落が 2 つ以上あるときの助言の注意（要確認 fn_guess の助言に添える。plan.fn_guess_notes）。

    「注見出し」の段落は 1 つしか持てず、ほかの「注」が文字から推定されると先の見出しが出力されない（変換が中止される。
    StructureConflictError。docs/REVIEW_2026-11.md の K1）ので、「注」を 1 つだけ直して変換し直さずに、すべての「注」の扱いを決めて
    から変換し直してもらう。「注」が 1 つ以下なら空文字。
    """
    plan = r.plan
    notes = [s for s in plan.fn_guess_notes if s in plan.paras]
    if len(notes) < 2:
        return ""
    listed = _para_samples([(s, plan.paras[s].text_only()) for s in notes])
    return (f"文字から注の見出しと推定される「注」だけの段落が {len(notes)} 件あります（4 章の件数のほか、その範囲の中の「注」も"
            f"数えています。{listed}）。「注見出し」にするのは注の節の「注」"
            "1 つだけにし、ほかの「注」（表の注の見出しなど）は「注本文」スタイルにするなど、すべての「注」の扱いを決めてから"
            "変換し直してください（「注」を 1 つずつ直しては変換し直すと、「注見出し」の「注」が 2 つ以上になったり、文字から注の見出しと"
            "推定される「注」が残ったりして、変換が中止されることがあります（注の見出しが 2 つになるため））。")


def _fn_guess_action(r):
    """文字から推定した注の見出し（本文スタイルの「注」だけの段落。表の注の見出しなど）の扱い（plan.fn_guess_checks。
    structure.Classifier.split_regions）。なければ None。

    注の節として扱ったか、本文に戻したかを、段落ごとに知らせる。どちらも文字から推定したもので、Word の段落のスタイルが
    「注」の見出しにふさわしいかを利用者が確かめる。
    """
    checks = r.plan.fn_guess_checks
    if not checks:
        return None
    paras = r.plan.paras
    n = len(checks)
    samples = _para_samples([(src, paras[src].text_only()) for src, _, _ in checks if src in paras])
    detail = "\n".join(f"・{src}: {how}" for src, kind, how in checks[:FN_GUESS_SHOWN]) + ("\n・ほか" if n > FN_GUESS_SHOWN else "")
    kept = any(kind == "kept" for _, kind, _ in checks)
    returned = any(kind == "returned" for _, kind, _ in checks)
    what = ("「注」だけの段落を、文字から注の見出しと推定しました。"
            + ("注の一覧に見えない段落（注の番号で始まらない段落、または見出しのスタイルの段落）が続いたまま後付けの見出し"
               "（または文書の終わり）に着いたため、その範囲を注の節として扱いました。" if kept else "")
            + ("後ろに見出しのスタイルの段落（資料の見出しではないもの）が続くため、注の節ではなく本文の続きとみなして"
               "本文に戻しました。" if returned else ""))
    # 戻した範囲に注の番号で始まる段落があったとき（本当の注の一覧かもしれない。H7）は、件数と抜粋、注の節にする手段を添える
    numbered = [src for head, kind, _ in checks if kind == "returned" for src in r.plan.fn_guess_numbered.get(head, ())]
    if numbered:
        listed = _para_samples([(src, paras[src].text_only()) for src in numbered if src in paras])
        what += f"戻した範囲に、注の番号で始まる段落が {len(numbered)} 件ありました（{listed}）。本当の注の一覧かもしれません。"
    # 「注」の段落は、本文・標準・章見出しのスタイルだと文字から注の見出しと推定される（structure.back_heading_by_text が見る役割は
    # sec1・normal・p）。Word で実際に取れる手段は、注の節なら「注見出し」スタイル（役割 fn_heading）、本文の続きなら「注本文」スタイル
    # （役割 fn。本文では本文の段落として出て、文字からは推定されない。tests/test_structure.py の test_fn_guess_advice_is_executable）。
    # 表の注・図表のキャプション・ブロック引用のスタイルは、別の要素（表・図・引用）になるので勧めない
    clause = _fn_guess_span_clause(r, checks)
    multi = _fn_guess_multi_clause(r)
    how = ("注の節なら、Word で「注」の段落のスタイルを「注見出し」にして変換し直してください。" + clause
           + "表の注の見出しなど本文の続きなら、"
           "Word で「注」の段落のスタイルを「注本文」にして変換し直してください（本文・標準・章見出しのスタイルのままでは、"
           "「注」だけの段落は文字から注の見出しと推定されます）。" + multi)
    return Action(
        TO_CHECK, "fn_guess",
        top=f"> **要確認: 「注」だけの段落の扱いを、文字から推定しました（{n} 件。4 章）。** {what}{how}対象の段落: {samples}",
        checklist=(f"- [ ] **文字から推定した「注」の扱い**（{n} 件。4 章）: 注の節か本文の続きかを確かめ、違えば Word で「注」の段落の"
                   "スタイルを「注見出し」（注の節）か「注本文」（本文の続き）にして変換し直す。" + clause + multi),
        box_title="「注」の段落の扱いを推定しました（要確認）",
        box_detail=f"{what}{how}（レポートの冒頭と 4 章）\n対象の段落: {samples}\n{detail}",
        cli=(f"要確認: 「注」だけの段落を文字から注の見出しと推定して扱いました（{n} 件。レポートの冒頭と 4 章）。"
             + (f"戻した範囲に注の番号で始まる段落が {len(numbered)} 件あります。" if numbered else "")
             + "注の節か本文の続きかを確かめ、docx で「注」の段落のスタイルを、注の節なら「注見出し」、本文の続きなら「注本文」にして"
             "変換し直すこと。" + clause + multi))


NEWLINE_SAMPLES = 5     # 改行の要確認に並べる段落の数（全件はレポートの 10 章）
JOINED_SHOWN = 10       # 6 章の、つないだ段落・読み飛ばした表の行の一覧に並べる数（それより多ければ「ほか」）


def _deleted_row_where(r):
    """読み飛ばした削除行（model.DeletedRow）の表を、利用者が Word で探す手がかりにする関数（docx_reader.table_where）。
    表に文字が残っていない（すべての行を読み飛ばした）表は、表のキャプションの冒頭（キャプションがあれば）。"""
    caps = {t.table.tid: t.caption for t in r.plan.tables if t.table is not None and t.caption is not None}

    def where(d):
        return table_where(d.head, caps[d.tid].text_only() if not d.head and d.tid in caps else "")
    return where


NAME_SPLIT_SAMPLES = 5  # 著者名の要確認に並べる氏名の数（全件はレポートの 4 章）


def name_split_items(r) -> list:
    """要確認 name_split に挙げる和文の著者名 [(段落 ID, builder.EasternSplit)]: 字の間の空白のいちばん長い所で分けたもの・
    境目を推定して分けたもの・AI が分けたもの・空白がなく分けられなかったもの（C010・C064）。空白が 1 か所の氏名と、AI が機械の
    分け方（空白が 1 か所・いちばん長い空白が 1 か所）と同じ位置を指定しただけの氏名は入らない（BuildInfo.name_splits に入れない）。"""
    dup = {s for f in front_findings(r) if f.kind in (frontcheck.TEMPLATE, frontcheck.SWAP) for s in f.srcs}      # 見本の行・入れ替わりは front_check で知らせる
    return [(s, sp) for s, sp in getattr(r, "name_splits", ()) if sp.how in ("longest", "context", "count", "ai", "none") and s not in dup]


def _ai_name_confidence(r, src) -> str:
    """段落 src の氏名を AI が分けた判断（2 章）の確度。なければ ""。"""
    for d in getattr(getattr(r, "plan", None), "decisions", ()):
        if d.stage == "ai" and d.category == "name" and d.src == src:
            return d.confidence
    return ""


def _name_split_line(sp, confidence="") -> str:
    """氏名 1 人の分け方の文（「試　験　六　郎」を 試験／六郎 に分けました〈…〉）。末尾の「。」は付けない。4 章の記録は builder.name_split_note。
    「誤っていることがあります」は、ここには書かず、知らせ全体で 1 回（_name_split_action の check）。"""
    if sp.how == "none":
        return f"「{_clean(sp.name)}」は姓と名の間に空白がなく、分けられなかったので、全体を姓として出力しました"
    if sp.how == "longest":
        why = "字の間の空白がいちばん長い所を、姓と名の境目にしました"
    elif sp.how == "context":
        why = (f"推定。いちばん長い空白が 2 か所以上あって境目を決められないので、論文の中の表記「{_clean(sp.hint)}」から境目を"
               "決めました。その表記が、この著者の引用でないこともあります")
    elif sp.how == "count":
        why = ("推定。いちばん長い空白が 2 か所以上あって境目を決められないので、字数だけから境目を決め、"
               f"姓を {len(sp.surname)} 字としました")
    else:
        # 「誤っていることがあります」は、知らせ全体で 1 回（_name_split_action の check）。機械の推定は別の文に書く
        conf = f"（確度 {_clean(confidence)}）" if confidence else ""
        before = f"。AI の指定がなければ、{_clean(sp.machine.describe())}" if sp.machine is not None else ""
        return (f"「{_clean(sp.name)}」を {_clean(sp.surname)}／{_clean(sp.given)} に分けました。AI が境目を決めました{conf}{before}")
    return f"「{_clean(sp.name)}」を {_clean(sp.surname)}／{_clean(sp.given)} に分けました（{why}）"


def _name_split_action(r):
    """和文の著者名の分け方を確かめてもらう（要確認。C010・C064）。なければ None。

    字の間に空白を入れて揃えた氏名は、空白のいちばん長い所か、推定した境目で分け、字の間の空白は落としている（builder.split_eastern）。
    空白のない氏名は全体を姓として出力している（J-STAGE に名のない著者として出る）。AI が境目を指定した氏名も、推定なので挙げる。
    どれも、出版版 PDF の氏名と見比べてもらい、違えば Word で姓と名の間に空白を 1 つだけ置いて変換し直してもらう。
    推定を含むときは、見出し・一覧・コマンドラインの文にも書く。字数だけの推定は誤りやすいので強く書く。"""
    items = name_split_items(r)
    if not items:
        return None
    split = [sp for _, sp in items if sp.how != "none"]
    unsplit = [sp for _, sp in items if sp.how == "none"]
    guessed = [sp for sp in split if sp.how in ("context", "count", "ai")]
    by_count = [sp for sp in split if sp.how == "count"]
    lines = [_name_split_line(sp, _ai_name_confidence(r, src) if sp.how == "ai" else "") for src, sp in items[:NAME_SPLIT_SAMPLES]]
    if len(items) > NAME_SPLIT_SAMPLES:
        lines.append(f"ほか {len(items) - NAME_SPLIT_SAMPLES} 人（4 章）")
    names = "、".join(f"「{_clean(sp.name)}」" for _, sp in items[:NAME_SPLIT_SAMPLES]) + ("、ほか" if len(items) > NAME_SPLIT_SAMPLES
                                                                                       else "")
    what = "著者名の姓と名の分け方を確かめてください"
    refs = ("推定を含みます。" if guessed else "") + "4 章・7 章"
    check = ("出版版 PDF の氏名と、姓と名の境目が合っているか確かめてください（英文の著者名の姓も手がかりになります）。"
             if split else "")
    if guessed:
        check += "推定で境目を決めた氏名は、誤っていることがあります。"
    if by_count:
        check += "字数だけで境目を推定した氏名は、誤りやすいので、必ず確かめてください。"
    how = ""
    if split:
        how += ("違っていたら、Word でその氏名の姓と名の間の空白を 1 つだけ残し、字の間の空白を消して保存してから、変換し直して"
                "ください。")
    if unsplit:
        how += ("分けられなかった氏名に名もあるなら、Word で姓と名の間に空白を 1 つ入れて保存してから、変換し直してください"
                "（名のない著者として J-STAGE に出ます）。")
    # 「字数だけの推定は誤りやすい」は、字数だけの推定（how が count）の氏名を含むときだけ書く
    guess_check = (f" 推定で分けた氏名が {len(guessed)} 人あります（誤っていることがあります"
                   + ("。字数だけの推定は誤りやすいので、必ず確かめる" if by_count else "") + "）。") if guessed else ""
    guess_cli = (f"推定で分けた氏名が {len(guessed)} 人あります（誤っていることがあります）。"
                 + ("字数だけの推定は誤りやすいので、必ず確かめること。" if by_count else "") if guessed else "")
    listed = "。".join(lines) + "。"
    return Action(
        TO_CHECK, "name_split",
        top=f"> **要確認: {what}（{refs}）。** {listed}{check}{how}",
        checklist=(f"- [ ] **著者名の姓と名**（{len(items)} 人。4 章・7 章）: 出版版 PDF の氏名と、姓と名の境目が合っているか"
                   "確かめる。違えば Word で姓と名の間に空白を 1 つだけ置いて変換し直す。" + guess_check.strip()),
        box_title="著者名の姓と名の分け方を確かめてください（" + ("推定を含みます。" if guessed else "") + "要確認）",
        box_detail=f"{listed}\n{check}{how}（レポートの冒頭・4 章・7 章）",
        cli=(f"要確認: 著者名の姓と名の分け方を確かめること（{names}。レポートの冒頭・4 章・7 章）。{guess_cli}出版版 PDF の氏名と境目が"
             "違えば、docx で姓と名の間に空白を 1 つだけ置いて変換し直すこと"))


def _newline_action(r):
    """題目・副題・著者名・所属・引用文献の段落の中の改行（Word の Shift+Enter。builder の BuildInfo.newlines の label）。なければ None。

    これらの文脈には <break/> を置けないので（題目・副題は、同梱の DTD では置けるが J-STAGE の修飾タグ許容一覧で ×。著者名・所属・
    引用文献は DTD でも置けない）、XML では改行の文字のまま出力している。
    決定事項 13(2) のとおり要確認として知らせる（終了コードは 0）。本文・見出し・表のセルの改行は 10 章の警告だけ。
    """
    rows = [x for x in r.newlines if x.label and not x.cell]
    if not rows:
        return None
    n = sum(x.count for x in rows)
    paras = r.plan.paras
    samples = ("、".join(f"{x.src}「{esc(paras[x.src].text_only().strip(), 15)}」（{x.label}）" if x.src in paras
                        else f"{x.src}（{x.label}）" for x in rows[:NEWLINE_SAMPLES])
               + ("、ほか" if len(rows) > NEWLINE_SAMPLES else ""))
    what = f"題目・著者・所属・引用文献の段落の中に、改行（Shift+Enter）が {n} か所あります"
    shown = ("XML では改行の文字のまま出力しています。J-STAGE の画面では、改行の位置が空白になるか、前後の文字が詰まって"
             "表示されることがあります。")
    how = "改行が要らなければ、Word でその改行を消して（英文なら空白に置き換えて）、変換し直してください。"
    return Action(
        TO_CHECK, "newline",
        top=f"> **要確認: {what}（10 章）。** {shown}{how}対象の段落: {samples}",
        checklist=f"- [ ] **題目・著者・所属・引用文献の中の改行**（{n} か所。10 章）: 要らなければ Word で改行を消して変換し直す",
        box_title="題目・著者・所属・引用文献の中に改行があります（要確認）",
        box_detail=f"{what}。{shown}{how}（レポートの冒頭と 10 章）\n対象の段落: {samples}",
        cli=f"要確認: {what}（レポートの冒頭と 10 章）。要らなければ docx で改行を消して変換し直すこと")


def pdf_fallback(r) -> bool:
    """route pdf で出版版 PDF の文字を読めず、docx を補わずに変換した（pipeline.Result.pdf_fallback と同じ。M4）。"""
    return r.route == "pdf" and r.docx_fix is None and r.pdf_check is not None


def pdf_not_zipped(r) -> bool:
    """指定した PDF が PDF として開けず、ZIP に入れなかった（pipeline が has_pdf を立てなかった。C098）。

    pypdfium2 が入っていないときは開けるかを確かめず、ZIP に入れるので、当てはまらない。
    """
    pc = r.pdf_check
    return pc is not None and not pc.ok and not r.has_pdf


NOT_ZIPPED_PDF = ("この PDF は PDF として開けないので、アップロード用の ZIP に入れていません"
                  "（J-STAGE では PDF が必須です。PDF を選び直して変換し直してください）。")
NOT_ZIPPED_PDF_CLI = "。この PDF は PDF として開けないので、ZIP に入れていない"


def pdf_suspect(r) -> bool:
    """docx の段落の半分以上が PDF に見つからないが、題目は PDF にある（別の版の疑い。要確認。pdfmatch の verdict が suspect）。
    題目が PDF にないときは変換を中止する（pipeline.WrongPaperError）ので、ここには来ない。"""
    pc = r.pdf_check
    return pc is not None and pc.ok and pc.verdict == "suspect"


def _pdf_fallback_action(r):
    pc = r.pdf_check
    if pc is None or pc.ok or not pdf_fallback(r):
        return None
    msg = pc.message
    zip_note = NOT_ZIPPED_PDF if pdf_not_zipped(r) else ""
    return Action(
        NEEDS_ACTION, "pdf_fallback",
        top=(f"> **要対応: 出版版 PDF を読めませんでした（13 章）。** PDF の文字を読めなかったため（{esc(msg)}）、表記を PDF に"
             "合わせず、PDF との照合もしていません。XML は docx の文字のままです。文字を読める出版版 PDF を選んで変換し直してください"
             f"（画像だけの PDF〈スキャンした PDF など〉では、文字を読めません）。{zip_note}"),
        checklist=("- [ ] **出版版 PDF を読めなかった**（13 章）: 文字を読める出版版 PDF を選んで変換し直す"
                   "（このままなら、表記を PDF に合わせず、照合もしていない。XML は docx の文字のまま）"),
        box_title="出版版 PDF を読めませんでした（要対応）",
        box_detail=(f"PDF の文字を読めなかったため（{msg}）、表記を PDF に合わせず、PDF との照合もしていません。XML は docx の文字の"
                    f"ままです。文字を読める出版版 PDF を{step('pdf')}で選び直して変換し直してください（画像だけの PDF〈スキャンした PDF "
                    f"など〉では、文字を読めません。レポートの冒頭と 13 章）。{zip_note}"),
        cli=(f"要対応: 出版版 PDF を読めませんでした。PDF の文字を読めなかったため（{msg}）、表記を PDF に合わせず、照合もしていない"
             "（XML は docx の文字のまま。レポートの冒頭と 13 章）。文字を読める出版版 PDF を --pdf で指定して変換し直すこと" + (NOT_ZIPPED_PDF_CLI if zip_note else "")))


def _pdf_unread_action(r):
    pc = r.pdf_check
    if pc is None or pc.ok or pdf_fallback(r):
        return None
    msg = pc.message
    zip_note = NOT_ZIPPED_PDF if pdf_not_zipped(r) else ""
    return Action(
        TO_CHECK, "pdf_unread",
        top=(f"> **要確認: 出版版 PDF と照合できませんでした（13 章）。** {esc(msg)}。XML は docx の文字のままです。"
             f"画像だけの PDF（スキャンした PDF など）では、文字を読めません。PDF がこの記事の出版版 PDF かを確かめてください。{zip_note}"),
        checklist="- [ ] 出版版 PDF と照合できなかった（13 章）: PDF がこの記事の出版版 PDF か（画像だけの PDF でないか）を確かめる",
        box_title="出版版 PDF と照合できませんでした（要確認）",
        box_detail=(f"{msg}。XML は docx の文字のままです（レポートの 13 章）。画像だけの PDF（スキャンした PDF など）では、"
                    f"文字を読めません。{step('pdf')}で選んだ PDF が、この記事の出版版 PDF かを確かめてください。{zip_note}"),
        cli=(f"要確認: 出版版 PDF と照合できませんでした（{msg}。レポートの 13 章）。XML は docx の文字のまま"
             + (NOT_ZIPPED_PDF_CLI if zip_note else "")))


MISMATCH_SHOWN = 10       # 要確認 pdf_mismatch の一覧（冒頭・枠）に並べる件数（全件はレポートの 13.1）
MISMATCH_MANY = 5         # 語句・番号の違いがこの件数以上なら、受け取った docx が校正後の版でない可能性を添える
MISMATCH_SIDE = 10        # 違いの前後に添える docx の文字の数
MISMATCH_AT = "13.1"      # 違いの全件を載せる節（手順 7 で 13 章を作り直すときに、この節に揃える）
MISMATCH_RANK = {"word": 0, "number": 0, "case": 1, "punct": 2}     # 並べる順（語句・番号 → 大文字・小文字 → 約物だけ）


def mismatch_check(r):
    """要確認 pdf_mismatch のもとにする照合（PdfCheck。照合できていなければ None）。補った docx を作ったときは元の docx と PDF の照合
    （fx.check）、作らなかったときは pdf_check（docx の欄に、Word で検索できる元の docx の文字を出すため。ignored_lines と同じ決め方）。"""
    fx = r.docx_fix
    pc = fx.check if fx is not None and fx.check is not None else r.pdf_check
    return pc if pc is not None and pc.ok else None


def mismatch_diffs(r) -> list:
    """PDF と文字が違う箇所（内容の違い。区分 CONTENT の違い）。並びは、語句・番号 → 大文字・小文字 → 約物だけの順で、同じ種類の中は docx の順。"""
    pc = mismatch_check(r)
    if pc is None:
        return []
    diffs = [d for d in pc.diffs if level_of(d) == CONTENT]
    return sorted(diffs, key=lambda d: MISMATCH_RANK.get(d.label or "word", 0))


def mismatch_cells(r) -> list:
    """表のセル・囲みの行で、PDF に見つからないもの [(段落 ID, 行の文字)]（pdfmatch.cell_misses。docx の順）。"""
    pc = mismatch_check(r)
    return list(pc.cell_misses) if pc is not None else []


def mismatch_count(r) -> int:
    """要確認 pdf_mismatch の件数（文字の違い＋表のセルの見つからない行）。"""
    return len(mismatch_diffs(r)) + len(mismatch_cells(r))


def mismatch_many(diffs) -> bool:
    """語句・番号の違い（大文字・小文字・約物だけは数えない）が MISMATCH_MANY 件以上か。"""
    return sum(1 for d in diffs if MISMATCH_RANK.get(d.label or "word", 0) == 0) >= MISMATCH_MANY


def _mismatch_texts(r):
    """違いの場所と docx の段落の文字を引く関数 (場所, 文字)。補った docx を作ったときは元の docx の控え（DocxFix.texts・locations）、
    作らなかったときは plan から。"""
    fx = r.docx_fix
    if fx is not None and fx.check is not None:
        return (lambda s: fx.locations.get(s) or r.plan.locations.get(s, "")), (lambda s: fx.texts.get(s))
    return (lambda s: r.plan.locations.get(s, "")), (lambda s: r.plan.paras[s].plain() if s in r.plan.paras else None)


MISMATCH_KIND_JA = {"word": "語句", "number": "番号", "case": "大文字・小文字", "punct": "約物だけ"}


def mismatch_parts(d, text):
    """違い 1 件の (docx の側の文字, PDF の側の文字, 形)（設計 W2 の 3.1）。形は replace（置き換え）・docx_only（docx にだけある）・
    pdf_only（PDF にだけある）・number（Word の番号）。docx の側は、前後 MISMATCH_SIDE 文字つきで、［］が違う部分（Word の番号は
    番号の文字）。docx の文字は shown_text を通す（数式などの位置の U+FFFC は「［数式など］」）。text は docx の段落の文字（引けなければ None）。"""
    pdf = esc_blank(d.pdf, 40)
    body = text[d.start:d.end] if text is not None else d.docx
    if d.number and not body.strip():       # Word が付ける番号だけにかかる違い
        return esc_blank(shown_text(d.number), 30), pdf, "number"
    if text is None:    # 段落の文字を引けない（手で作った照合の結果など）: docx の前後つきの文字をそのまま使う
        excerpt = d.context
    else:
        a, b = d.start, d.end
        excerpt = ("…" if a > MISMATCH_SIDE else "") + text[max(0, a - MISMATCH_SIDE):a] + "［" + text[a:b][:30] + \
            ("…" if b - a > 30 else "") + "］" + text[b:b + MISMATCH_SIDE] + ("…" if len(text) > b + MISMATCH_SIDE else "")
    shown = esc(shown_text(excerpt))
    if d.number:        # 番号と、続く本文の文字にかかる違い: 番号は docx の文字ではないので、断って前に置く
        shown = f"（Word の番号「{esc(shown_text(d.number))}」）" + shown
    if not d.pdf.strip():
        return shown, "PDF にはない", "docx_only"
    return shown, pdf, "pdf_only" if d.start == d.end else "replace"


def mismatch_line(d, where, text) -> str:
    """違い 1 件の行（設計 W2 の 3.1。場所は where、docx の段落の文字は text）。"""
    head = f"{where or d.src}（{d.src}）: "
    docx, pdf, form = mismatch_parts(d, text)
    if form == "number":
        return head + f"docx の番号「{docx}」→ PDF「{pdf}」"
    if form == "docx_only":
        return head + f"docx「{docx}」→ PDF にはない"
    return head + f"docx「{docx}」→ PDF「{pdf}」" + ("（docx にはない）" if form == "pdf_only" else "")


def mismatch_cell_line(src, text, where) -> str:
    """表のセルの行 1 件の行（設計 W2 の 3.1）。"""
    return f"{where or '表の中'}（{src}）: 「{esc_blank(shown_text(text), 60)}」と同じ文字が PDF に見つからない"


def mismatch_lines(r, diffs=None, cells=None) -> list:
    """要確認 pdf_mismatch の行（diffs・cells は省略すると mismatch_diffs・mismatch_cells。全件）。文字の違いの後ろに表のセルの行を並べる。"""
    where, text_of = _mismatch_texts(r)
    out = [mismatch_line(d, where(d.src), text_of(d.src)) for d in (mismatch_diffs(r) if diffs is None else diffs)]
    return out + [mismatch_cell_line(s, t, where(s)) for s, t in (mismatch_cells(r) if cells is None else cells)]


MISMATCH_MARK_NOTE = "各行の docx の［ ］は、PDF と違う部分です。"
MISMATCH_MANY_NOTE = ("**語句の違いが多いので、受け取った docx が校正後の版でない可能性があります。"
                      "1 か所ずつ直す前に、著者に校正後の docx を確かめてください。**")
MISMATCH_MANY_SHORT = "語句の違いが多いので、docx が校正後の版かを先に著者に確かめること（校正前の版なら 1 か所ずつ直さない）"


def _pdf_mismatch_action(r):
    diffs, cells = mismatch_diffs(r), mismatch_cells(r)
    if not diffs and not cells:
        return None
    n = len(diffs) + len(cells)
    fx = r.docx_fix
    kept = ("XML は docx の文字のままです（PDF に合わせて直したのは、全角・半角や句読点などの表記だけです）。" if fx is not None
            else "XML は docx の文字のままです（表記も PDF に合わせていません）。")
    many = mismatch_many(diffs)
    lines = mismatch_lines(r, diffs[:MISMATCH_SHOWN], cells[:max(0, MISMATCH_SHOWN - len(diffs))])
    more = n - MISMATCH_SHOWN
    top = [f"> **要確認: 出版版 PDF と文字が違う箇所が {n} 件あります（{MISMATCH_AT}）。** "
           + (MISMATCH_MANY_NOTE + " " if many else "") + kept
           + "PDF が正しければ、Word で docx を直して変換し直してください。docx が正しければ（PDF の誤植など）、そのままでかまいません。"
           + MISMATCH_MARK_NOTE, ">"]
    top += [md_tag("> - " + x) for x in lines]
    if more > 0:
        top.append(f"> - …ほか {more} 件（{MISMATCH_AT}）")
    return Action(
        TO_CHECK, "pdf_mismatch",
        top="\n".join(top),
        checklist=(f"- [ ] **出版版 PDF と文字が違う箇所**（{n} 件。{MISMATCH_AT}）を確かめる: "
                   + (MISMATCH_MANY_SHORT + "。その上で、" if many else "")
                   + "PDF が正しければ Word で docx を直して変換し直す。docx が正しければそのまま"),
        box_title=f"出版版 PDF と文字が違う箇所が {n} 件あります（要確認）",
        box_detail=((MISMATCH_MANY_NOTE.replace("**", "") if many else "") + kept + "PDF が正しければ、Word で docx を直して" + step("docx")
                    + f"からやり直してください。docx が正しければ（PDF の誤植など）、そのままでかまいません（全件はレポートの {MISMATCH_AT}）。"
                    + MISMATCH_MARK_NOTE + "\n"
                    + "\n".join(f"・{x}" for x in lines) + (f"\n…ほか {more} 件" if more > 0 else "")),
        cli=(f"要確認: 出版版 PDF と文字が違う箇所 {n} 件（レポートの冒頭と {MISMATCH_AT}）。"
             + (MISMATCH_MANY_SHORT + "。その上で、" if many else "")
             + "PDF が正しければ docx を直して変換し直すこと。docx が正しければそのままでよい"))


def _pdf_suspect_action(r):
    if not pdf_suspect(r):
        return None
    pc = r.pdf_check
    what = f"照合した段落 {pc.verdict_counted} 件のうち {pc.verdict_missing} 件"
    if pc.has_title:
        known = "題目は PDF にあります。"
        known_short = "題目は PDF にあります"
    else:
        known = "docx の題目を読み取れなかったので、別の論文かどうかは確かめられませんでした。"
        known_short = "docx の題目を読み取れなかったので、別の論文かどうかは確かめられませんでした"
    return Action(
        TO_CHECK, "pdf_suspect",
        top=(f"> **要確認: docx の段落の半分以上が、出版版 PDF に見つかりません（13.3）。** {what}。{known}PDF がこの論文の全体か"
             "（抜粋・別の版でないか）、docx が別の版でないかを確かめてください。"),
        checklist=("- [ ] **PDF がこの論文の全体か**を確かめる（docx の段落の半分以上が PDF に見つからない。13.3）。違っていたら、"
                   "正しい PDF（または docx）で変換し直す"),
        box_title="docx の段落の半分以上が、出版版 PDF に見つかりません（要確認）",
        box_detail=(f"{what}が、出版版 PDF に見つかりませんでした。{known}{step('pdf')}で選んだ PDF がこの論文の全体か（抜粋・別の版で"
                    f"ないか）、{step('docx')}で選んだ docx が別の版でないかを確かめてください。違っていたら、選び直してやり直して"
                    "ください（レポートの 13.3）。"),
        cli=f"要確認: docx の段落の半分以上が出版版 PDF に見つかりません（{what}。{known_short}。レポートの 13.3）。--pdf の PDF と docx が"
            "同じ論文のものか確かめること")


REQUIRED_DATES = ("pub_date", "received", "accepted")      # 入力で必須の日付（再受付日・J-STAGE 公開日・最終査読日は必須にしない）


def missing_dates(meta) -> list:
    """入力が空の必須の日付の欄の名前（発行日・受付日・受理日の順）。日付は年月日がそろった値か空のどちらか（config._date が一部だけの日付を
    弾く）ので、「空」は None。発行日は pub_date だけを見る（J-STAGE 公開日 epub_date があっても、ppub の <pub-date> は空になる）。"""
    return [DATE_FIELDS[k] for k in REQUIRED_DATES if not getattr(meta, k, None)]


def _meta_dates_action(r):
    """発行日・受付日・受理日のどれかが空のまま変換した（所有者の決定: 3 つとも入力で必須）。要対応。変換は止めず、XML は今までどおり作る
    （発行日が空なら <pub-date> の年が空、受付日・受理日が空ならその <date> がない）。受付日・受理日は PDF から先に入るので、空のまま
    残るのは PDF を入れなかったか、PDF から読めなかったとき。"""
    meta = getattr(r, "meta", None)
    if meta is None:
        return None
    miss = missing_dates(meta)
    if not miss:
        return None
    names = "・".join(miss)
    pdf_note = "受付日・受理日は、出版版 PDF の 1 ページ目（投稿受付・採用決定の日付）を見て入力します。"
    return Action(
        NEEDS_ACTION, "meta_dates",
        top=(f"> **要対応: {names}が空です（11 章）。** 発行日・受付日・受理日は入力が必須です。このままでは J-STAGE に登載する書誌情報が"
             f"そろいません。{pdf_note}入力して変換し直してください。"),
        checklist=f"- [ ] **{names}が空**（11 章）: 入力して変換し直す。{pdf_note}",
        box_title=f"{names}が空です（要対応）",
        box_detail=(f"発行日・受付日・受理日は入力が必須です。{pdf_note}{step('meta')}に入力して、やり直してください"
                    "（日付は 2026-03-31 の形。レポートの 11 章）。"),
        cli=(f"要対応: {names}が空です（レポートの 11 章）。発行日・受付日・受理日は必須なので、--meta の [article] に pub_date・"
             "received・accepted を 2026-03-31 の形で書いて変換し直すこと（受付日・受理日は --pdf の PDF から読めればそれが入る）"))


AUTHORS_SHOWN = 10       # 要確認 meta_corresp に並べる著者の数（残りは「ほか N 人」）


def author_names(plan) -> list:
    """著者の氏名（plan.authors の順。和文の氏名、なければ英文の氏名。どちらもなければ ""）の一覧。番号は 1 から（XML の contrib の順）。"""
    out = []
    for a in plan.authors:
        p = a.name_ja if a.name_ja is not None else a.name_en
        out.append(p.plain().strip() if p is not None else "")
    return out


def corresp_cell(meta, plan) -> str:
    """11 章の表の「責任著者」の値: 入力の番号と、印（corresp="yes"）を付けた著者の氏名。範囲外の番号はそうと書く（点検 review20 の 2 回目）。"""
    nums = list(dict.fromkeys(getattr(meta, "corresp", None) or []))
    if not nums:
        return "（未入力）"
    names = author_names(plan)
    n = len(names)
    return "、".join(f"{k}（{esc(names[k - 1], 20) or '氏名なし'}）" if k <= n else f"{k}（範囲外。著者は {n} 人。印を付けていません）"
                    for k in nums)


def _meta_corresp_action(r):
    """要確認 meta_corresp（C095）: 入力した責任著者の番号に、著者の人数の範囲外のものがある（1 つでも）。なければ None。

    範囲外の番号は XML の責任著者の印（corresp="yes"）にならず、範囲内の番号だけが印になる。最後の著者に付けるなどの推定はしない。
    番号が 1 以上の整数かは config.ArticleMeta.from_dict が確かめる。著者が 1 人もいない原稿は、要対応 authors_missing で知らせる。"""
    meta, plan = getattr(r, "meta", None), r.plan
    n = len(plan.authors)
    out = [k for k in dict.fromkeys(getattr(meta, "corresp", None) or []) if k > n]
    if not out or not n:
        return None
    nums = "・".join(str(k) for k in out)
    rng = "1" if n == 1 else f"1〜{n}"
    names = author_names(plan)
    order = "、".join(f"{i}: {esc(x, 20) or '氏名なし'}" for i, x in enumerate(names[:AUTHORS_SHOWN], 1)) \
        + (f"、ほか {n - AUTHORS_SHOWN} 人" if n > AUTHORS_SHOWN else "")
    title = f"責任著者の番号 {nums} が、著者の人数（{n} 人）の範囲外です"
    how = (f"XML の責任著者の印は、範囲内の番号の著者だけに付きます（範囲外の番号は、どの著者にも付けません）。入力の責任著者の番号を、"
           + ("1 " if n == 1 else f"何番目の著者か（{rng}）") + "に直して変換し直してください"
           f"（著者の順は docx の和文の著者名の順で、{order}。入力した番号はレポートの 11 章）")
    return Action(
        TO_CHECK, "meta_corresp",
        top=f"> **要確認: {title}。** {how}。",
        checklist=f"- [ ] **責任著者の番号**（{nums}。著者は {n} 人。11 章）: 何番目の著者かを直して変換し直す",
        box_title=title + "（要確認）", box_detail=(f"範囲外の番号（{nums}）には責任著者の印を付けていません。{step('meta')}の責任著者の番号を、{rng} の番号に直して、"
                    f"やり直してください（著者の順は {order}。レポートの 11 章）。"),
        cli=f"要確認: {title}（レポートの 11 章）。--meta の [article] の corresp を、{rng} の番号に直して変換し直すこと（著者の順は {order}）")


META_ID_LABELS = tuple(PAGE_FIELDS.values())      # 巻・号・ページ（違えば記事 ID・DOI・ファイル名が変わるので要対応）


def _meta_pdf_action(r):
    """入力した書誌情報が出版版 PDF の 1 ページ目と違う（設計 W5 の 3.7）。巻・号・ページが違えば要対応、日付・年・ページ数だけなら要確認。
    PDF から読めなかった項目と、入力が空の項目は比べない。XML に出すのはいつも入力の値で、この知らせは値を変えない。"""
    b, meta = getattr(r, "pdf_biblio", None), getattr(r, "meta", None)
    if b is None or meta is None:
        return None
    mm = mismatches(meta, b)
    if not mm:
        return None
    heavy = any(label in META_ID_LABELS for label, _, _ in mm)
    pages = [x for x in mm if x[0] == "ページ数"]
    rest = [x for x in mm if x[0] != "ページ数"]
    parts = [f"{label}: 入力 {mine}／PDF {pdf}" for label, mine, pdf in rest]
    page_note = ""
    if pages:
        _, mine, pdf = pages[0]
        page_note = (f"PDF のページ数（{pdf}）が、ページの範囲 {mine}と合いません。号全体の PDF や、別の論文の PDF ではないか確かめてください。")
    what = "、".join(parts)
    shown = "、".join(parts[:3]) + ("…" if len(parts) > 3 else "")
    look = "PDF の 1 ページ目（誌名の行と、投稿受付・採用決定の日付）と見比べ、入力が誤っていれば直して変換し直してください。"
    level = NEEDS_ACTION if heavy else TO_CHECK
    lead = "要対応" if heavy else "要確認"
    label_list = "、".join(dict.fromkeys(x[0] for x in mm))
    return Action(
        level, "meta_pdf",
        top=f"> **{lead}: 入力した書誌情報が、出版版 PDF と違います（11 章）。** " + (what + "。" if what else "") + page_note + look,
        checklist=(f"- [ ] **書誌情報が出版版 PDF と違う**（{label_list}。11 章）: PDF の 1 ページ目と見比べ、入力が誤っていれば直して変換し直す"),
        box_title=f"入力した書誌情報が、出版版 PDF と違います（{lead}）",
        box_detail=((what + "。" if what else "") + page_note + "PDF の 1 ページ目（誌名の行と、投稿受付・採用決定の日付）と見比べ、"
                    + step("meta") + "の入力が誤っていれば直して、やり直してください（レポートの 11 章）。"),
        cli=f"{lead}: 書誌情報が出版版 PDF と違う（{shown or label_list}。レポートの 11 章）。--meta の値を確かめること")


def pdf_actions(r) -> list:
    """出版版 PDF との照合の知らせ（actions の一部）。r は pdf_check・docx_fix・route があればよい（Colab の result_boxes は report.actions を通して使う）。"""
    makers = (_pdf_fallback_action, _pdf_unread_action, _pdf_mismatch_action, _pdf_suspect_action, _meta_pdf_action)
    return [a for a in (f(r) for f in makers) if a is not None]


PDF_KEYS = ("pdf_fallback", "pdf_unread", "pdf_mismatch", "pdf_suspect", "meta_pdf")


def actions(r) -> list:
    """利用者に知らせること（要対応・要確認）の一覧。並びはレポートの冒頭の順（推奨の手順 ai_finish は、要対応と必須の手順の後ろ）。

    PDF の知らせは pdf_actions（PDF を読めない・照合できない・PDF と文字が違う〈pdf_mismatch〉・PDF がこの論文の全体か〈pdf_suspect〉・入力した書誌情報が PDF と違う〈meta_pdf〉）。
    PDF に合わせた表記の件数や、照合に使わなかった PDF の文字は知らせにせず、レポートの 13 章に載せるだけ。
    記事フォルダにあるのに ZIP に入れなかったファイル（Result.not_zipped）は 10 章の警告のまま。
    """
    head = [f(r) for f in (_fidelity_action, _supplement_action, _dtd_action, _table_shape_action, _table_body_action,
                           _table_parts_action, _image_names_action,
                           _upload_action, _meta_dates_action, _meta_corresp_action, _textbox_undecided_action,
                           _textbox_place_action, _textbox_figure_text_action, _authors_missing_action, _unplaced_action, _front_check_action, images_action,
                           lost_action, _image_same_action, _image_changed_action, lost_autonum_action, _pua_left_action, _abstract_missing_action, _refs_missing_action, _refs_unlinked_action, _style_hidden_action, _emphasis_action, _resultless_field_action, _symbol_action, _abstract_ja_action, _app_after_refs_action, _float_end_action, _style_check_action, _ai_boundary_action, _ai_carried_action, _note_overlap_action, _note_unlinked_action, _float_ref_action, _link_iri_action,
                           _fn_guess_action, _name_split_action, _newline_action)]
    acts = [a for a in head if a is not None] + pdf_actions(r)
    fin = _with_reused(_ai_finish_action(r), r)
    if fin is not None:
        # 推奨の手順 ai_finish は、要対応と必須の手順の後ろ（することの一覧の checklist_order と同じく、先に済ませることを上に出す）
        last = max((i for i, a in enumerate(acts) if a.level == NEEDS_ACTION or (a.level == STEP and a.required)), default=-1)
        acts.insert(last + 1, fin)
    return acts


def checklist_order(acts) -> list:
    """することの一覧に並べる知らせの順: 手順（必須 → 推奨）→ 要対応 → 要確認。それぞれの中は、PDF の項目（PDF_KEYS）を先に、残りを actions の順に。"""
    ordered = [a for a in acts if a.key in PDF_KEYS] + [a for a in acts if a.key not in PDF_KEYS]
    steps = [a for a in ordered if a.level == STEP]
    return ([a for a in steps if a.required] + [a for a in steps if not a.required]
            + [a for a in ordered if a.level == NEEDS_ACTION] + [a for a in ordered if a.level == TO_CHECK])


def checklist_line(a) -> str:
    """することの一覧の 1 行（Action.checklist）。まだ済んでいない行（「- [ ] 」）の頭に、種類の印を 1 か所で付ける:
    必須の手順は（必須）、推奨の手順は（推奨）、要対応は（要対応）、要確認は（要確認）（Action の level と required で決める）。"""
    head = "- [ ] "
    if not a.checklist.startswith(head):
        return a.checklist
    mark = (("（必須）" if a.required else "（推奨）") if a.level == STEP else
            "（要対応）" if a.level == NEEDS_ACTION else "（要確認）" if a.level == TO_CHECK else "")
    return head + mark + a.checklist[len(head):]


def todo_list(r, acts=None) -> list:
    """レポートの冒頭の「することの一覧」の行（Markdown。J-STAGE に登載する前にすること）。

    並びは checklist_order（手順〈必須 → 推奨〉→ 要対応 → 要確認）の行で、手順 images の行の直後に図の確かめ.html の行
    （画像を 1 枚でも入れたとき）を置き、その後ろに PDF の行・2 章と 3 章の確認（AI の採用・不採用か未解決があるときだけ）と
    固定の 3 行（11 章の書誌情報、J-STAGE で巻・号を作る、アップロードして確かめる）を置く。acts は actions(r)（省略すると作る）。"""
    if acts is None:
        acts = actions(r)
    ai, m = r.ai, r.meta
    L = []
    # 図の画像を全部入れたときは、手順 images の済んだ行（[x]）が出る
    check_line = ((f"- [ ] 「{esc(m.article_id(r.journal))}_図の確かめ.html」で、図番号・キャプションと入れた画像が合っているかを確認する")
                  if any(i.status == "user" for i in r.images) else "")        # 画像を 1 枚でも入れたら、手順 images の行の直後に足す
    for a in checklist_order(acts):
        if a.checklist:
            L.append(checklist_line(a))
        if a.key == "images" and check_line:
            L.append(check_line)
            check_line = ""
    if check_line:
        L.append(check_line)
    L.append(pdf_checklist_line(r))
    if ai.accepted or ai.rejected or r.unresolved_after:       # AI の採用・不採用か、機械で解決できなかった箇所があるときだけ
        L.append("- [ ] 2 章（AI による仕上げ）と 3 章（未解決）を PDF と照らして確認する")
    L.append("- [ ] 11 章の書誌情報（巻・号・頁・日付・DOI）を確認する")
    L.append(f"- [ ] J-STAGE 編集登載システムで、巻（{esc(m.volume or '?')}）・号（{esc(m.issue or '?')}）と、その号のセクション"
             "（目次の見出し。例: 論文）を作成しておく（ないとアップロード時に EMSGM181E「巻号が学会誌別巻号の設定に存在しません」・"
             "EMSGM182E「学会誌別セクションが存在しません」になる）")
    L.append("- [ ] J-STAGE 編集登載システムにアップロードし、記事を正しいセクションに振り分け（記事移動）、"
             "プレビューで本文・図表・引用文献リンクを確認する")
    return L


def pdfium_version() -> str:
    """入っている pypdfium2 の版（importlib.metadata。入っていない・読めなければ ""。レポートの冒頭の記録だけで、知らせにしない。C057）。"""
    try:
        from importlib.metadata import version
        return version("pypdfium2")
    except Exception:  # noqa: BLE001  入っていない・版を読めない: 書かない
        return ""


def render(r) -> str:
    plan, fid = r.plan, r.fidelity
    L = []
    L.append(f"# 変換レポート: {r.docx_name}")
    L.append("")
    L.append(f"- 作成日時: {r.created}")
    L.append(f"- ツール: jasme-jats {r.tool_version}")
    pdfium = pdfium_version()
    if pdfium:       # PDF の文字の読み方（描かれない文字の除去など）は版で変わりうるので、後から原因を突き止められるよう記録する（C057。知らせにはしない）
        L.append(f"- PDF を読むライブラリ: pypdfium2 {pdfium}")
    L.append(f"- 図表番号の扱い: {'`<label>` とタイトルに分ける（間の空白のみ落とす）' if r.split_labels else '番号もタイトルと一緒に 1 つの要素に入れる（文字を落とさない）'}")
    ai = r.ai
    api = f"API（{PROVIDERS.get(ai.provider, ai.provider)}: {ai.model}）"
    ai_mode = {"none": "使用しない", "api": api, "manual": "手動（チャットに貼り付け）"}.get(ai.mode, ai.mode)
    L.append(f"- AI による仕上げ: {ai_mode}")
    L.append(f"- 出版版 PDF: {pdf_use_ja(r)}"
             + ("（PDF の文字を読めなかったので、docx を補わずに変換した）" if pdf_fallback(r) else ""))
    L.append("")

    # ------------------------------------------------------------------ することの一覧（旧 14 章。1 章の前）
    acts = actions(r)
    L.append("## することの一覧")
    L.append("")
    L.extend(todo_list(r, acts))
    L.append("")

    # ------------------------------------------------------------------ 1. 要約
    L.append("## 1. 結果の要約")
    L.append("")
    fid_line = (f"{fid.summary()}（docx の段落 {fid.units} 件: XML に出力 {fid.mapped} 件、出力しなかった {len(fid.excluded)} 件"
                f"［6 章に全文］）")
    if r.docx_fix is not None:
        fid_line += f"。照合の相手は、表記を PDF に合わせた docx（{r.docx_fix.path.name}）"
    final_line = "合格" if fid.final_ok else ("不合格: " + fid.final_detail if fid.final_ok is False else "未実施")
    c = r.link_counts
    wn = word_note_refs(plan)
    which = "Word の脚注・文末脚注" if has_endnotes(plan) else "Word の脚注"
    fn_links = f"{c.get('fn', 0) + wn}" + (f"（うち {which} {wn}）" if wn else "")
    links = (f"引用文献 {c.get('bibr', 0)} / 図 {c.get('fig', 0)} / 表 {c.get('table', 0)} / 注 {fn_links} / "
             f"数式 {c.get('disp-formula', 0)} / URL {c.get('url', 0) + c.get('word', 0)} / DOI {c.get('doi', 0)}")
    ai_acc = [d for _, d in ai.accepted]
    rows = [
        ("本文の文字の不変性チェック（AI による仕上げの後に実施）", fid_line),
        ("最終出力（目印を取り除いた XML）の再チェック", final_line),
        ("J-STAGE 指定 DTD（JATS 1.1）による検証", "合格" if r.dtd_valid else f"不合格（{len(r.dtd_errors)} 件、12 章）"),
        ("J-STAGE のアップロード時チェック（XML と ZIP で判定できるもの）",
         "問題なし" if not upload_issues(r) else f"要対応 {len(upload_issues(r))} 件（12 章）"),
        ("機械的に付けたリンク", links),
        ("AI が付けたリンク・判断（2 章）", f"採用 {len(ai_acc)} 件 / 不採用 {len(ai.rejected)} 件" if ai.mode != "none" else "AI による仕上げなし"),
        ("機械処理で解決できなかった箇所（3 章）", f"{len(r.unresolved_after)} 件"),
        ("画像", image_summary(r)),
        ("警告", f"{len(r.warnings)} 件（10 章）"
                 + (f"。ほかに、ZIP に入れなかったファイル {len(r.not_zipped)} 件（10 章）" if r.not_zipped else "")),
        ("出版版 PDF との照合", pdf_summary(r)),
    ]
    if plan.unplaced_floats:
        rows.insert(7, ("結び付いた段落の後ろに置いた図表（3 章）", f"{len(plan.unplaced_floats)} 件（{float_places(plan)}）"))
    if textbox_summary(plan):
        rows.insert(8 if plan.unplaced_floats else 7,
                    (f"テキストボックスの文字（{textbox_chapters(plan)}）", textbox_summary(plan)))
    if r.supplement is not None:
        sup = r.supplement
        rows.insert(1, ("出版版 PDF による補完の確かめ",
                        f"合格（元の docx から変わった箇所は、すべて表記を合わせたもの {sup.typeset} 文字）"
                        if sup.ok else "不合格（13 章の 13.4）"))
    L.append(table(["項目", "結果"], rows))
    L.append("")
    # 要対応・要確認の囲み（actions）。PDF の知らせは、ほかの知らせの後ろ
    late = [a for a in acts if a.key in PDF_KEYS]
    for a in [a for a in acts if a not in late]:
        if a.top:
            L.append(a.top)
            L.append("")
    pc, fx = r.pdf_check, r.docx_fix
    for a in late:
        if a.top:
            L.append(a.top)
            L.append("")

    # ------------------------------------------------------------------ 2. AI
    L.append("## 2. AI による仕上げ")
    L.append("")
    state = ai_state(r)
    left = _float_left(plan)
    L.append(table(["項目", "内容"], [
        ("方法", ai_method(r)),
        ("モデル", ai.model if ai.mode == "api" and ai.model else "—"),
        ("状態", state + (f"（位置を聞いた図・表 {len(plan.asked_floats)} 個のうち、残り {len(left)} 個）" if plan.asked_floats else "")),
        ("利用量", f"入力 {ai.usage.get('input_tokens')} トークン / 出力 {ai.usage.get('output_tokens')} トークン" if ai.usage else "—"),
    ] + ([("出版版 PDF", ai_pdf_sent(ai))] if ai.mode == "api" else [])
      + ([("PDF を見たか（ツールの確かめ）", ai_pdf(r))] if ai.pdf_seen else [])))
    L.append("")
    if ai.mode == "none":
        L.append("AI による仕上げは行っていません。")
    elif state == "回答待ち":
        # 位置を聞く図形などがなければ、推奨の手順 ai_finish は出さず、ここに 1 行だけ書く（修正計画 W8 の 4.3）
        # 位置を聞く図形があれば、出版版 PDF の添付と図・表の位置から書く（ai_finish の本文と同じ。点検 review13 利用者向け 7・8）
        name = esc(r.prompt_path.name if r.prompt_path else "AI依頼文.txt")
        if left:
            L.append(f"AI の回答をまだ反映していません（手動モード）。{name} を、出版版 PDF を同じメッセージに添付して"
                     "チャット（claude.ai など）に渡し、返ってきた回答を貼り戻して変換し直すと、AI が出版版 PDF を見て図・表の位置を合わせ、"
                     "リンクの取りこぼしなども確かめます。この出力は AI による仕上げの前の状態です。")
        else:
            L.append(f"AI の回答をまだ反映していません（手動モード）。{name} をチャット（claude.ai など）に渡し（出版版 PDF を添付すると、"
                     "AI が体裁を見て答えられます）、返ってきた回答を貼り戻して変換し直すと、AI の判断（リンクの取りこぼしなど）が"
                     "反映されます。この出力は AI による仕上げの前の状態です。")
    elif state == "失敗":
        L.append(f"AI による仕上げは行えませんでした: {ai.error or 'AI の回答が空でした'}")
    else:
        # 文字だけのテキストボックスがある論文では、その判断（boxes の kind「囲み」「図の注記」）も AI が変えられる
        boxes = ("、文字だけのテキストボックスの囲み・図の注記の判断と囲みの位置"
                 if any(b.kind != "blank" for b in r.plan.textboxes.values()) else "")
        L.append("AI の判断には誤りの可能性があります。特に確度「低」「中」の項目は、PDF と照らして確認してください。"
                 "AI の回答で変わるのはリンク・姓名の区切り・注の区切りと資料の始まりと、テキストボックス・"
                 f"グループ図形に入った図表の位置{boxes}だけで、本文の文字は変更していません。見出し・引用など、Word のスタイルで"
                 "直せる段落の役割は、AI の提案を下の「スタイルの提案」に載せるだけで、XML には反映していません。")
        L.append("")
        if ai.partial:
            L.append(f"**AI の回答が途中で切れていました。** {esc(ai.partial)}")
            L.append("")
        for line in ai_check_lines(ai):
            L += [line, ""]
        if ai_acc:
            order = {"低": 0, "中": 1, "高": 2}
            rows = []
            for d in sorted(ai_acc, key=lambda d: (order.get(d.confidence, 3), d.did)):
                rows.append((d.did, d.confidence, CAT_JA.get(d.category, d.category), d.location or r.plan.locations.get(d.src, d.src), d.message))
            L.append(table(["番号", "確度", "種類", "場所", "内容と根拠"], rows))
        else:
            L.append("採用された提案はありません。")
        L.append("")
        if ai.rejected:
            L.append("### AI の提案のうち、検証で採用しなかったもの")
            L.append("")
            rows = [(op.get("op"), op.get("src"), op.get("text") or op.get("role") or op.get("image"), op.get("target"),
                     md_tag(why), op.get("reason")) for op, why in ai.rejected]
            L.append(table(["操作", "段落", "対象", "リンク先", "不採用の理由", "AI の根拠"], rows))
            L.append("")
        if ai.notes:
            L.append("### AI からの気づき（操作にはしていない）")
            L.append("")
            for n in ai.notes:
                L.append(f"- {esc(n)}")
            L.append("")
        if ai.model_note:
            L.append(f"（使用したモデル: {ai.model}。{ai.model_note}）")
    L += ai_style_section(r)
    L.append("")

    # ------------------------------------------------------------------ 3. 未解決
    L.append("## 3. 機械処理（と AI）で解決できなかった箇所")
    L.append("")
    if r.unresolved_after:
        rows = [(UNRES_JA.get(u[0], u[0]), plan.locations.get(u[1], u[1]), u[2], u[3]) for u in r.unresolved_after]
        L.append(table(["種類", "場所", "本文の表記", "理由"], rows))
    else:
        L.append("ありません。")
    unc = plan.uncited_refs
    if unc:
        L.append("")
        conts = set(plan.ref_conts)        # 前の文献の続きの疑い（refparse.ref_continuations。C026）
        L.append("本文中のどこからもリンクされていない文献: " + "、".join(
            f"{x.rid}（{esc(x.para.plain()[:30])}）" + ("（前の文献の続きの疑い）" if x.para.src in conts else "")
            for x in plan.refs if x.rid in unc))
    if not plan.refs and plan.refs_missing_cites:
        L.append("")
        L.append(f"引用文献の一覧が見つからないので、本文の「著者（年）」の形の引用（少なくとも {plan.refs_missing_cites} か所）を"
                 "リンクしていません（要対応。レポートの冒頭）。")
    for line in float_notes(plan) + note_notes(plan):
        L.append("")
        L.append(line)
    L.append("")

    # ------------------------------------------------------------------ 4. 機械的な推定
    L.append("## 4. 機械処理による推定（生成 AI は使っていない）")
    L.append("")
    mech = [d for d in plan.decisions if d.stage == "mechanical"] + r.build_notes
    rows = [(d.did, CAT_JA.get(d.category, d.category), d.location or r.plan.locations.get(d.src, d.src), d.message) for d in mech]
    rows += style_unknown_rows(plan)
    if rows:
        L.append(table(["番号", "種類", "場所", "内容"], rows))
    else:
        L.append("ありません（想定外のスタイルの段落も、番号の形式などから推定した箇所もありませんでした）。")
    L.append("")

    # ------------------------------------------------------------------ 5. 不変性チェックの詳細
    L.append("## 5. 文字の不変性チェックの詳細")
    L.append("")
    L.append("docx の各段落から文字を独立に取り出し、XML に出力された文字と 1 文字ずつ比較しました。")
    L.append("")
    if fid.mismatches:
        L.append(table(["段落", "場所", "差分"], [(m.src, plan.locations.get(m.src, ""), m.detail) for m in fid.mismatches]))
        L.append("")
    if fid.missing:
        L.append("XML に出力されていない段落（変換ツールの不具合）:")
        L.append("")
        L.append(table(["段落", "文字"], [(s, esc(t, 80)) for s, t in fid.missing]))
        L.append("")
    if fid.stray:
        L.append("docx にない文字が XML に入っている箇所（変換ツールの不具合）:")
        L.append("")
        L.append(table(["要素", "文字"], [(p, esc(t, 40)) for p, t in fid.stray[:50]]))
        L.append("")
    if fid.conflicts:
        L.append("XML に出力したのに、出力しない段落としても記録されている段落（変換ツールの不具合）:")
        L.append("")
        L.append(table(["段落", "除外の理由", "文字"], [(s, reason, esc(t, 80)) for s, reason, t in fid.conflicts]))
        L.append("")
    if fid.bad_excluded:
        L.append("空白だけの段落として出力しなかったのに、docx では空白以外の文字がある段落（変換ツールの不具合）:")
        L.append("")
        L.append(table(["段落", "除外の理由", "docx の文字"], [(s, reason, esc(t, 80)) for s, reason, t in fid.bad_excluded]))
        L.append("")
    if fid.duplicates or fid.unknown or fid.bad_drops:
        L.append(f"重複出力: {fid.duplicates} / 不明な段落: {fid.unknown} / 空白以外を落とした箇所: {fid.bad_drops}")
        L.append("")
    if fid.ok:
        L.append("すべての段落で一致しました。")
        L.append("")

    # ------------------------------------------------------------------ 6. 出力しなかった文字
    L.append("## 6. XML に出力しなかった docx の文字（全件）")
    L.append("")
    if fid.excluded:
        ff = front_findings(r)
        miss = set(abstract_missing_srcs(plan)) | set(authors_missing_srcs(r)) | {s for f in ff if f.level == frontcheck.MUST for s in f.srcs}
        sure = {s for s, _, _ in unplaced_exclusions(r)} | {s for f in ff if f.level != frontcheck.MUST for s in f.srcs}
        # 理由の列の印: 英文要旨が見つからない（要対応）、位置を決められない（要確認）。docx の文字の列は変えない
        mark = lambda s, reason: reason + ("（要対応）" if s in miss else "（要確認）" if s in sure else "")
        L.append(table(["段落", "理由", "文字"], [(s, mark(s, reason), esc(t, 100)) for s, reason, t in fid.excluded]))
    else:
        L.append("ありません。")
    other = []
    if r.hidden_text:
        other.append("隠し文字（Word で非表示に設定された文字）: " + "、".join(f"［{s}］{esc(t, 40)}" for s, t in r.hidden_text))
    if r.hidden_images:
        other.append(f"隠し文字の中の画像 {len(r.hidden_images)} 件（{'、'.join(r.hidden_images)}）: Word で表示されないので、"
                     "出力していません。")
    if r.style_hidden or r.style_hidden_images:
        items = ([f"［{s}］{esc(t, 40)}" for s, t in _style_hidden_paras(r)]
                 + ([f"画像 {'・'.join(r.style_hidden_images)}"] if r.style_hidden_images else []))
        other.append("上の隠し文字のうち、文字に直接付けた隠し文字ではなく、スタイル（段落スタイル・文字スタイル）や既定の書式の設定で"
                     "隠し文字になっているもの（Word の表示と同じかの判定は暫定。要確認）: " + "、".join(items))
    if getattr(r, "resultless_fields", None):
        items = [f"［{f.src}］{FIELD_DRAWN.get(f.kind, f.kind)}（Word のフィールドの中身: `{f.code.replace('`', '')[:40]}`）{_resultless_excerpt(f)}"
                 for f in r.resultless_fields]
        other.append("Word では表示されるが、XML に出せない文字（囲い文字・分数・ルビなど。Word が、フィールドというしくみで描いている文字で、"
                     "docx に文字としては入っていません。出版版 PDF で補った docx では、PDF から別の文字として補われていることもあります。要確認。"
                     f"段落の文字の抜粋の{RESULTLESS_MARK}が、その文字のある位置です）: " + "、".join(items))
    if r.tracked_changes:
        other.append(f"変更履歴が {r.tracked_changes} 箇所あります。挿入は反映し、削除は出力していません（Word で表示される最終版と同じ）。")
    if r.joined:
        def joined(first, srcs):
            # つないだ段落を Word で探せるように、つないだ後の段落の文字の冒頭を添える
            head = plan.paras[first].text_only().strip() if first in plan.paras else ""
            return "＋".join(srcs) + (f"「{esc(head, 15)}」" if head else "（文字なし）")
        shown = "、".join(joined(first, srcs) for first, srcs in r.joined[:JOINED_SHOWN])
        more = f"、ほか {len(r.joined) - JOINED_SHOWN} か所" if len(r.joined) > JOINED_SHOWN else ""
        other.append(f"変更履歴で段落記号（段落の区切り）が削除された段落を、次の段落とつないで 1 段落として出力しました"
                     f"（{len(r.joined)} か所: {shown}{more}。Word で変更をすべて承諾した状態に合わせています）。")
    if r.deleted_rows:
        where = _deleted_row_where(r)
        rows = "、".join(f"{where(d)}の {d.row} 行目" for d in r.deleted_rows[:JOINED_SHOWN])
        more = f"、ほか {len(r.deleted_rows) - JOINED_SHOWN} 行" if len(r.deleted_rows) > JOINED_SHOWN else ""
        other.append(f"変更履歴で削除された表の行 {len(r.deleted_rows)} 行は、行に Word で表示される文字・画像などが残っていなかった"
                     f"ので、Word で変更を承諾した状態と同じく出力していません: {esc(rows)}{more}")
    if r.comments:
        other.append(f"コメントが {r.comments} 件ありました（コメントは本文ではないため出力していません）。")
    other.append("ヘッダー・フッター（柱・ページ番号）は対象外です。")
    L.append("")
    for o in other:
        L.append(f"- {o}")
    L.append("")

    # ------------------------------------------------------------------ 7. 落とした空白
    L.append("## 7. XML の構造に合わせて落とした空白（全件）")
    L.append("")
    L.append("姓と名、図表番号とタイトルのように、JATS で別々の要素に分ける箇所の区切りの空白と、著者名の前後の空白・和文の著者名の"
             "字の間の空白だけを落としています（J-STAGE の表示では区切りが補われます）。空白以外の文字は落としていません。"
             "姓と名の間の空白の理由に「推定」とあるものは、いちばん長い空白が 2 か所以上あって姓と名の境目を決められない氏名で、"
             "境目を推定したもの、「AI の指定」とあるものは、AI が境目を指定したものです（どちらもレポートの冒頭の要確認）。")
    L.append("")
    if fid.drops:
        L.append(table(["段落", "場所", "落とした文字", "理由"],
                       [(s, plan.locations.get(s, ""), repr(t), reason) for s, t, reason in fid.drops]))
    else:
        L.append("ありません。")
    L.append("")

    # ------------------------------------------------------------------ 8. 生成文字
    L.append("## 8. Word が自動生成していた文字・補った文字")
    L.append("")
    if has_endnotes(plan):
        word_marks = ("（Word の脚注・文末脚注機能で書かれた注の番号だけは、Word の表示〈脚注は「1」、文末脚注は「i」など〉ではなく、"
                      "本文で最初に参照される順の通し番号を本誌の形式〈設定 fn_mark〉で付けています。対応は下の表）")
    else:
        word_marks = "（Word の脚注機能で書かれた注の番号だけは、Word の表示「1」ではなく本誌の形式（設定 fn_mark）にしています）"
    unshown = "（題目・副題・著者名・所属の段落の番号は出していません。10 章）" if getattr(r, "unshown_numbers", None) else ""
    L.append("Word の自動段落番号や脚注番号は docx の文字ではなく Word が表示時に作るものです。表示どおりの文字を XML に出力しました"
             f"{word_marks}{unshown}。"
             "表記を PDF に合わせたときは、章・節・項の見出し・本文・キャプション・注・付記・謝辞・引用文献・英文要旨の段落の"
             "自動番号と脚注番号の全角・半角と字形を PDF に合わせています（" + NUMBERS_NOT_MATCHED_BODY + "13 章）。"
             "docx に注の見出しがない場合（Word の脚注機能で書かれた注など）は、見出し（設定 fn_title）を補いました。")
    L.append("")
    if fid.generated:
        cnt = Counter(k for k, _ in fid.generated)
        names = {"autonum": "自動番号", "footnote-mark": "脚注番号", "fn-title": "補った注の見出し"}
        L.append("、".join(f"{names.get(k, k)} {n} 件" for k, n in cnt.items())
                 + "（例: " + "、".join(esc(t) for _, t in fid.generated[:8]) + "）")
    else:
        L.append("ありません。")
    L.append("")
    lost_nums = getattr(r, "lost_autonums", None) or []
    if lost_nums:
        L.append("XML に番号を出せなかった段落（要対応。変換ツールの不具合の可能性）:")
        L.append("")
        L.append(table(["段落", "場所", "Word の番号", "XML の要素", "段落の書き出し"],
                       [(ln.src, ln.location, ln.number, ln.where, ln.text) for ln in lost_nums]))
        L.append("")
    pua_left = getattr(r, "pua_chars", None) or []
    if pua_left:
        L.append("XML に残った私用領域（U+E000–U+F8FF）の文字（要対応。J-STAGE の画面で読めない文字になります）:")
        L.append("")
        L.append(table(["段落", "場所", "符号", "フォント", "種類", "XML の要素", "個数", "段落の書き出し"],
                       [(pc.src or "（段落なし）", pc.location, f"U+{pc.code:04X}", pc.font or "不明",
                         PUA_KIND_JA[bool(pc.generated)], pc.where, pc.count, pc.text)
                        for pc in pua_left]))
        L.append("")
    sym_done = getattr(r, "symbols_replaced", None) or []
    if sym_done:
        L.append("記号フォント（Symbol・Wingdings 系）の私用領域の符号を、対応する普通の文字に置き換えた記号（全件）。置き換えは表に載っている"
                 "確かな対応だけです。箇条書きの記号は Word の箇条書きの設定が付ける記号、本文の記号は本文に入れた記号です。「要確認」のものは、"
                 "出版版 PDF（なければ Word の表示）の記号と同じか確かめてください。「従来どおり」は、よく使う記号（Wingdings の●・➢・▪・✓・❖、Symbol の箇条書きの記号と矢印・ギリシャ文字などの記号。Symbol の数字・€・®・©・™ は含みません）で、"
                 "以前の版から同じ文字にしていて実際の原稿で確かめ済みなので、冒頭では知らせません:")
        L.append("")
        L.append(table(["段落", "場所", "種類", "フォント", "元の符号", "置き換えた文字", "知らせ"],
                       [(sy.src, plan.locations.get(sy.src, ""), SYMBOL_KIND_JA[sy.kind], sy.font or "不明", f"U+{sy.code:04X}", sy.to,
                         "従来どおり" if sy.known else "要確認") for sy in sym_done]))
        L.append("")
    note_rows = word_note_rows(r)
    if note_rows:
        L.append(f"{'Word の脚注・文末脚注' if has_endnotes(plan) else 'Word の脚注'}と、XML の注の対応（「Word の注」の番号は docx の"
                 "中の番号で、Word の画面に出る番号〈文末脚注の「i」など〉と違うことがあります。Word で注を探すときは、注の書き出しを"
                 "手がかりにしてください）:")
        L.append("")
        L.append(table(["XML の注", "Word の注", "番号", "注の書き出し", "本文からのリンク"], note_rows))
        L.append("")

    # ------------------------------------------------------------------ 9. 画像
    L.append("## 9. 図の画像")
    L.append("")
    lost = r.lost_images
    rows = image_rows(r)
    if rows:
        L.append("図・表の画像は、作業する人が出版版 PDF などから用意して入れます（Word の原稿の中の画像は使いません）。"
                 f"入れた画像との対応は「{esc(r.meta.article_id(r.journal))}_図の確かめ.html」でも確かめられます。")
        L.append("")
        L.append(table(["名前", "図・表とキャプション", "場所", "位置の決め方", "入れた画像", "元のファイル名・形式・大きさ", "備考"],
                       [(row.key, shown_text(row.caption) or (OPTIONAL_CAPTION if row.kind == "optional" else "（キャプションなし）"),
                         shown_text(row.where), row.place, row.name if row.status == "user" else IMAGE_STATUS_JA.get(row.status, row.status),
                         row.detail, shown_text(row.note)) for row in rows]))
    elif lost or r.hidden_images:
        L.append("XML に画像を入れる場所はありません。")
    else:
        L.append("画像の要る図・表はありません。")
    L.append("")
    dropped, changed = images_dropped(r), images_changed(r)
    if dropped:
        L.append("### 入れ直しが要る前の画像")
        L.append("")
        L.append(f"変換し直す前に入れた画像のうち {len(dropped)} 枚は、図の番号かキャプション（キャプションのない画像は場所）が変わっていたので、"
                 "入れていません（別の図の画像を入れないためです）。")
        L.append("")
        L.append(table(["前の名前", "前のキャプション", "元のファイル名", "今の図・理由"],
                       [(d.key, shown_text(d.caption) or "（キャプションなし）", d.source_name,
                         (f"今の {d.suggest} の画像と思われます" if d.suggest else d.why)) for d in dropped]))
        L.append("")
    if changed:
        L.append("### キャプションが変わった図に入れ直した画像")
        L.append("")
        L.append("前に入れた画像を、キャプションが少し変わった図に入れ直しました。図と画像が合っているか確かめてください。")
        L.append("")
        L.append(table(["名前", "前のキャプション", "今のキャプション", "元のファイル名"],
                       [(c.key, shown_text(c.old_caption), shown_text(c.new_caption), c.source_name) for c in changed]))
        L.append("")
    decos = getattr(r, "decorations", [])
    drawn = [d for d in decos if d.figure]
    if drawn:
        labels = {i.key: i.label for i in r.images}
        L.append("### 図形で描いた図（図の本体）")
        L.append("")
        L.append("次の図は、Word の図形（文字の図形の集まりなど）で描かれていて、docx に画像がありません。図の置き場所に、出版版 PDF から"
                 "切り取った画像を 1 枚入れます。")
        L.append("")
        for d in drawn:
            label = labels.get(d.figure, "") or d.figure
            L.append(f"- {esc(label)}（{d.figure}）: {DECORATION_JA.get(d.kind, d.kind)}（{d.image.image_id}。{esc(d.where)}）。"
                     f"画像の場所には数えず、{esc(label)} の置き場所に 1 枚入れる")
        L.append("")
    plain = [d for d in decos if not d.figure]
    if plain:
        L.append("### 画像の場所に数えなかった図形（飾り）")
        L.append("")
        L.append("次の図形は、枠・白い四角・線・矢印・文字の図形だけの集まりなので、画像の場所に数えていません（XML には出ません）。")
        L.append("")
        L.append(table(["図形", "種類", "場所"], [(d.image.image_id, DECORATION_JA.get(d.kind, d.kind), d.where) for d in plain]))
        L.append("")
    if lost:
        L.append("### 画像を入れる場所を作れなかった画像（要対応）")
        L.append("")
        L.append(f"{LOST_IMAGES_WHY}{LOST_IMAGES_HOW}")
        L.append("")
        L.append(table(["画像", "docx 内のファイル", "段落", "場所", "段落の文字", "場所を作れなかった理由（推定）"],
                       [(li.image_id, li.source or "（Word の図形）", li.src or "-", li.location, li.text, li.reason)
                        for li in lost]))
        L.append("")
    if getattr(r, "image_problems", []):
        L.append("### XML の画像の名前の不具合（要対応）")
        L.append("")
        L.append(f"XML の中の画像の名前が、画像を入れる場所の一覧と合いません（変換ツールの不具合の可能性があります）。{IMAGE_NAMES_HOW}")
        L.append("")
        for x in r.image_problems:
            L.append(f"- {esc(x)}")
        L.append("")
    if r.hidden_images:
        L.append(f"隠し文字（Word で非表示に設定された文字）の中の画像 {len(r.hidden_images)} 件（{'、'.join(r.hidden_images)}）は、"
                 "Word で表示されないので出力していません（6 章）。")
        L.append("")

    # ------------------------------------------------------------------ 10. 警告
    L.append("## 10. 警告")
    L.append("")
    if r.warnings:
        for w in r.warnings:
            L.append(f"- {md_tag(esc(w))}")
    if r.not_zipped:
        L.append(f"- {not_zipped_note(r)}")
    if not r.warnings and not r.not_zipped:
        L.append("ありません。")
    L.append("")

    # ------------------------------------------------------------------ 11. 書誌情報
    L.append("## 11. 書誌情報（入力値）")
    L.append("")
    m, j = r.meta, r.journal
    rows = [("資料コード", j.journal_id), ("巻", m.volume or "（未入力）"), ("号", m.issue or "（未入力）"),
            ("開始ページ", m.fpage or "（未入力）"), ("終了ページ", m.lpage or "（未入力）"),
            ("DOI", m.doi_value(j) or "（未入力）"), ("記事識別子", m.article_id(j)),
            ("発行日", m.pub_date or "（未入力）"), ("J-STAGE 公開日", m.epub_date or "（未入力）"),
            ("受付日", m.received or "（未入力）"), ("受理日", m.accepted or "（未入力）"),
            ("査読の有無", {"yes": "査読あり", "no": "査読なし"}.get(m.peer_review,
                                                                "（未入力。J-STAGE の資料の設定が引き継がれる）")),
            ("最終査読日", m.approved or ("（未入力）" if m.peer_review == "yes" else "―")),
            ("原稿種別（日）", j.subjects(m)[0]), ("原稿種別（英）", j.subjects(m)[1] or "（不明）"),
            ("記事種別（article-type）", m.article_type or j.article_type),
            ("責任著者", corresp_cell(m, r.plan)),
            ("キーワード（日）", "；".join(m.keywords_ja) or "（なし）"),
            ("キーワード（英）", "; ".join(m.keywords_en) or "（なし）"),
            ("抄録の二次利用（specific-use）",
             f"{j.abstract_specific_use}（英文の論文で英文要旨を `<abstract>` に入れるときだけ使う。学会の方針を確認すること）")]
    b = getattr(r, "pdf_biblio", None)
    if b is not None:
        # PDF から読んだ値の列（入力の値は XML に使う値。PDF の値と違えば要確認 meta_pdf。読めなかった項目は「（読めません）」、比べない項目は空）
        from_pdf = {"巻": b.volume, "号": b.issue, "開始ページ": b.fpage, "終了ページ": b.lpage, "受付日": b.received, "受理日": b.accepted,
                    "発行日": f"{b.year} 年" if b.year else ""}
        rows = [(k, v, (from_pdf[k] or "（読めません）") if k in from_pdf else "") for k, v in rows]
        L.append(table(["項目", "入力の値（XML に使う値）", "PDF から読んだ値"], rows))
        if b.pages:
            L.append("")
            L.append(f"PDF のページ数: {b.pages}")
    else:
        L.append(table(["項目", "値"], rows))
    L.append("")
    for note in m.input_notes:
        L.append(f"- {esc(note)}")
    if m.input_notes:
        L.append("")

    # ------------------------------------------------------------------ 12. DTD・J-STAGE のチェック
    L.append("## 12. DTD 検証と J-STAGE のアップロード時チェックの詳細")
    L.append("")
    L.append("### DTD 検証")
    L.append("")
    if r.dtd_valid:
        L.append("J-STAGE 指定の DTD（https://www.jstage.jst.go.jp/dtds/1.1/JATS-journalpublishing1.dtd と同一の同梱版）で検証し、エラーはありませんでした。")
    else:
        if _dtd_app_hint(r):
            L.append(dtd_app_hint(APP_TITLE_TOP))
            L.append("")
        room = 100          # 場所の行の数の上限（全体。超えた分は件数で知らせる）
        for g in group_errors(r.dtd_errors):
            L.append(f"- {esc(g.message)}" + (f"（{g.count} 件）" if g.count > 1 else ""))
            for place in g.places[:room]:
                L.append(f"  - {esc(place)}")
            if len(g.places) > room:
                L.append(f"  - …ほか {len(g.places) - room} 件")
            room = max(0, room - len(g.places))
    L.append("")
    L.append("### J-STAGE のアップロード時チェック")
    L.append("")
    L.append("DTD に合っていても J-STAGE のアップロードで弾かれる条件（題目と抄録の言語の対応、日付の前後、所属番号など）のうち、"
             "XML だけで判定できるものと、アップロード用の ZIP を読み直して分かるもの（ファイル名・フォルダ名の文字、記事フォルダの"
             "外の項目や想定外のファイル、0 バイトのファイル、記事の XML が入っているか）を『記事アップロードメッセージ一覧』に沿って確かめた結果です。")
    L.append("")
    if upload_issues(r):
        L.append(table(["メッセージ ID", "内容"], upload_issues(r)))
    else:
        L.append("該当するエラーはありませんでした（J-STAGE 側でしか判定できない項目は、アップロード時に確認してください）。")
    L.append("")
    L.append("### 表の形の確かめ")
    L.append("")
    if r.table_problems:
        L.append(f"出力した表 {r.tables_checked} 件のうち {len(r.table_problems)} 件の形が、docx の表と違います（変換ツールの"
                 "不具合の可能性があります。この XML は登載に使わず、変換レポートを添えて開発者に知らせてください）。")
        L.append("")
        L.append(table(["表", "Word で探す手がかり", "見つかった問題"],
                       [(p.name, p.where, "、".join(p.problems)) for p in r.table_problems]))
    elif r.tables_checked:
        L.append(f"出力した表 {r.tables_checked} 件について、行ごとの列の数（縦に結合したセルが覆う列を含む）が docx の表と同じか、"
                 "セルが重なっていないか、縦の結合が見出し行・本文の行の外にはみ出していないか、セルのない行がないかを確かめ、"
                 "問題はありませんでした（変更履歴ですべての行が削除された表は数えていません）。")
    else:
        L.append("形を確かめた表はありません（表がないか、変更履歴ですべての行が削除された表だけです）。")
    L.append("")

    # ------------------------------------------------------------------ 13. 出版版 PDF との照合
    L.append("## 13. 出版版 PDF との照合")
    L.append("")
    if pc is None:
        L.append("記事の PDF がないため、照合していません。")
    elif not pc.ok:
        L.append(f"照合できませんでした: {esc(pc.message)}")
    else:
        render_pdf(L, r, pc, fx)
    L.append("")

    return "\n".join(L)


# 直せない違い（why のあるもの）の PDF の文字に添える文（レポートの表と Colab の枠）
WHY_MARKS = {HEAD_WHY: f"（PDF の側は照合に使わなかった文字だけ。{LINE_MARK} は PDF の行の変わり目）",
             LONG_WHY: f"（PDF にだけある 20 文字以上の文字。図や表の中の文字かもしれない。{LINE_MARK} は PDF の行の変わり目）",
             EDGE_WHY: f"（段落の最初・最後の、どこまでが段落の文字か決められない PDF の文字。{LINE_MARK} は PDF の行の変わり目）",
             UNSURE_WHY: f"（PDF のこの位置には、どの段落とも一致しない文字が続く。{LINE_MARK} は PDF の行の変わり目）",
             WHOLE_WHY: f"（段落の途中の、どの段落とも一致しない行まるごと。図や表の中の文字かもしれない。{LINE_MARK} は PDF の"
                        "行の変わり目）",
             DISPLACED_WHY: f"（分断された段落の、図や表の中の文字に挟まれた部分か、キャプションのすぐ隣の部分。{LINE_MARK} は"
                            " PDF の行の変わり目）",
             MATH_WHY: f"（PDF の文字の {FORMULA_MARK} は、PDF で数式など文字として読み取れない部分。{LINE_MARK} は PDF の"
                       "行の変わり目）"}
WHY_MARK = WHY_MARKS[HEAD_WHY]
PDF_COLUMN = f"PDF（{LINE_MARK} は行の変わり目）"     # 直せない違いのある表の、PDF の列の見出し


def why_mark(why) -> str:
    """直せない違いの理由 why に添える文（why がなければ空）。"""
    return WHY_MARKS.get(why, "（直せない違い）") if why else ""


def _mismatch_section(L, r):
    """13.1「PDF と違う箇所（要確認）」: 要確認 pdf_mismatch の全件（docx の順。表の「種類」の並びは pdf_mismatch と同じ）。
    others: 照合できなかった違い（区分が内容の違いでないもの。記録）も続けて載せる（手順 7 で 13.3 に移す）。"""
    plan = r.plan
    L.append(f"### {MISMATCH_AT} PDF と違う箇所（要確認）")
    L.append("")
    diffs, cells = mismatch_diffs(r), mismatch_cells(r)
    if diffs or cells:
        L.append("docx と出版版 PDF で文字が違う箇所です（全角・半角や句読点などの表記の違いは含みません）。XML は docx の文字のままです。"
                 "PDF が正しければ、Word で docx を直して変換し直してください。docx が正しければ（PDF の誤植など）、そのままでかまいません。")
        L.append("")
        where, text_of = _mismatch_texts(r)
        rows = []
        for d in diffs:
            docx, pdf, form = mismatch_parts(d, text_of(d.src))
            rows.append((d.src, where(d.src), docx, pdf, MISMATCH_KIND_JA.get(d.label or "word", "語句")))
        for src, text in cells:       # 表のセル・囲み: 行の文字が PDF に見つからない（簡易な確かめ。13.3）
            rows.append((src, where(src), esc_blank(shown_text(text), 60), "PDF に見つからない", "表のセル"))
        L.append(table(["段落", "場所", "docx（［］が違う部分）", "PDF", "種類"], rows))
    else:
        L.append("ありません。")


# 13.2 で、合わせなかった（直さず知らせない）表記の違い（TextDiff.label）の名前。なければ「そのほか」。unfixable は直せない位置にあるもの
SILENT_KIND_JA = {"script": "上付き・下付きの文字", "glyph": "字形だけの違い", "bullet": "箇条書きの記号・番号の形",
                  "numform": "箇条書きの記号・番号の形", "noteform": "注番号の形", "titlecolon": "英文題目の末尾の「:」"}
SILENT_UNFIXABLE = "直せない位置にあるもの（リンクの中・ルビのある段落・直さない違いの隣など）"
SILENT_OTHER = "そのほか"
SILENT_NOSPACE = "英文の文と文の間の全角の「，」「．」（PDF ではすぐ後ろに空白があり docx にはないので、半角にすると文の間が空かなくなるもの）"
# 13.3 で、照合できなかった違い（区分 UNSURE の TextDiff.label）の理由の名前
UNSURE_KIND_JA = {"head": "段落の端", "edge": "段落の端", "long": "PDF にだけある長い文字", "unsure": "どの段落とも一致しない文字が続く",
                  "whole": "どの段落とも一致しない行がまるごとある", "displaced": "図や表の中の文字に挟まれた位置",
                  "math": "数式の隣", "bullet_word": "箇条書きの記号と語句", "unreadable": "PDF の読めない文字",
                  "object": "数式・画像・注の参照にかかる", "elsewhere": "ほかの位置に同じ文字がある",
                  "punct_near": "直さない違いのすぐ隣の句読点"}
UNSURE_ROWS = 30         # 13.3 の表に並べる行の数の上限（それを超えた分は件数だけ。レポートを長くしない）


def silent_counts(diffs, unfixable_too) -> list:
    """13.2 の「合わせなかった」表記の内訳 [(名前, 件数)]。diffs は区分 SILENT の違い。unfixable_too が偽のとき、直せない位置にあるもの
    （label が unfixable）は数えない（route pdf では fx.skipped_typeset が別に数える）。"""
    cnt = Counter()
    for d in diffs:
        lab = (d.label or "").split("+")[0]
        if lab == "unfixable":
            if unfixable_too:
                cnt[SILENT_UNFIXABLE] += 1
            continue
        cnt[SILENT_KIND_JA.get(lab, SILENT_OTHER)] += 1
    return list(cnt.items())


def _unsure_table(L, plan, diffs, where):
    """13.3 の、照合できなかった違いの表（段落・場所・docx〈［］が違う部分。前後つき〉・PDF・わけ）。UNSURE_ROWS 行まで。"""
    shown = diffs[:UNSURE_ROWS]
    _formula_note(L, [x for d in shown for x in (d.docx, d.pdf, d.context)])
    L.append("表の docx の欄の［ ］は、PDF と違う部分（足す位置なら［］）です。")
    L.append("")
    L.append(table(["段落", "場所", "docx", PDF_COLUMN if any(d.why for d in shown) else "PDF", "わけ"],
                   [(d.src, where(d.src), esc_blank(d.context or d.docx, 60),
                     esc_blank(d.pdf, 80) if d.why else esc_blank(d.pdf, 40),
                     UNSURE_KIND_JA.get(d.label, "決められない") + (why_mark(d.why) if d.why else ""))
                    for d in shown]))
    if len(diffs) > UNSURE_ROWS:
        L.append("")
        L.append(f"…ほか {len(diffs) - UNSURE_ROWS} 件（表は {UNSURE_ROWS} 行まで）。")


def _unmatched_table(L, srcs, text_of, loc_of):
    L.append("PDF の中で対応する箇所を見つけられなかった段落です（PDF にない段落か、大きく書き換えられた段落の可能性があります）。"
             "これらの段落は照合していません。")
    L.append("")
    shown = srcs[:UNSURE_ROWS]
    L.append(table(["段落", "場所", "文字の先頭"], [(s, loc_of(s), esc(text_of(s) or "", 50)) for s in shown]))
    if len(srcs) > UNSURE_ROWS:
        L.append("")
        L.append(f"…ほか {len(srcs) - UNSURE_ROWS} 件（表は {UNSURE_ROWS} 行まで）。")


def render_pdf(L, r, pc, fx):
    """13 章（出版版 PDF との照合）。route pdf は fx（補った docx）あり、route docx は fx が None（--route docx。表記も PDF に合わせない）。

    13.1 PDF と違う箇所（要確認）/ 13.2 PDF に合わせた表記（件数だけ。route docx は PDF と表記が違う箇所〈docx のまま〉）/
    13.3 照合できなかった箇所（記録）/ 13.4 補完の確かめ（route pdf だけ）。件数は、補った docx を作ったときは元の docx と PDF の照合
    （mismatch_check）から数える（route pdf の pc は補った docx との照合で、残りの違いだけ）。"""
    plan = r.plan
    c = mismatch_check(r) or pc
    where, text_of = _mismatch_texts(r)
    if fx is not None:
        L.append(f"docx の段落の文字を、出版版 PDF（著者校正を経た最終版）の文字と段落ごとに照合しました（照合した段落 {c.checked} 件。"
                 "表のセル・別行の数式・資料の見出しと、4 文字未満の段落は除く）。全角・半角や句読点などの表記は PDF に合わせ"
                 f"（補った docx「{esc(fx.path.name)}」。Word の変更履歴つき）、それを変換しています。XML は補った docx の文字と"
                 f" 1 文字も違いません。語句などの内容は、PDF と違っていても docx のままです（{MISMATCH_AT}）。")
    else:
        L.append(f"docx の段落の文字を、出版版 PDF（著者校正を経た最終版）の文字と段落ごとに照合しました（照合した段落 {c.checked} 件。"
                 "表のセル・別行の数式・資料の見出しと、4 文字未満の段落は除く）。**XML は docx の文字のままで、表記も PDF に合わせていません**"
                 f"（コマンドラインの `--route docx`）。照合の結果をレポートに載せているだけです（{MISMATCH_AT}）。")
    L.append("")
    _mismatch_section(L, r)
    L.append("")
    # ---------------------------------------------------------------- 13.2
    if fx is not None:
        L.append("### 13.2 PDF に合わせた表記（確認は要りません）")
        L.append("")
        nums = len(plan.pdf_numbers)
        done = [x for x in (typeset_counts(fx.applied_typeset), f"Word が付ける番号 {nums} 件" if nums else "") if x]
        L.append(("合わせた表記: " + "、".join(done) + "。変更の全件は、補った docx の変更履歴にあります。") if done
                 else "PDF に合わせた表記はありません。")
        left = silent_counts(c.silent_diffs, False)
        from .pdfdocx import NOSPACE_REASON
        nospace = [f for f in fx.skipped_typeset if f.reason == NOSPACE_REASON]
        if len(fx.skipped_typeset) > len(nospace):
            left.append((SILENT_UNFIXABLE, len(fx.skipped_typeset) - len(nospace)))
        if nospace:         # 英文の文の間の全角の「，」「．」（全角のまま残す。C111）
            left.append((SILENT_NOSPACE, len(nospace)))
    else:
        L.append("### 13.2 PDF と表記が違う箇所（docx のまま）")
        L.append("")
        kinds = check_typeset_kinds(pc, plan)
        done = [x for x in (typeset_counts(kinds), f"Word が付ける番号 {len(pc.numbers)} 件" if pc.numbers else "") if x]
        L.append(("全角・半角や句読点などの表記だけが違う箇所: " + "、".join(done) + "。XML は docx のままです。") if done
                 else "全角・半角や句読点などの表記だけが違う箇所はありません。")
        left = silent_counts(c.silent_diffs, True)
    if left:
        L.append("")
        L.append("合わせなかった表記の違い（docx のまま。確認は要りません）: " + "、".join(f"{k} {n}" for k, n in left) + "。")
    L.append("")
    L.append(NUMBERS_NOT_MATCHED)
    L.append("")
    # ---------------------------------------------------------------- 13.3
    L.append(f"### {SECTION_UNSURE} 照合できなかった箇所（記録。PDF と見比べたいときに使う）")
    L.append("")
    L.append("照合で位置や中身を決められなかった箇所です。知らせにはしていませんが、本物の違い（校正で足された文など）が入っていることがあります。")
    L.append("")
    uns = c.unsure_diffs
    elsewhere = set(c.found_elsewhere)
    unmatched = [s for s in c.unmatched if s not in elsewhere]
    if uns:
        why = Counter(UNSURE_KIND_JA.get(d.label, "決められない") for d in uns)
        L.append(f"- 決められなかった違い {len(uns)} 件（" + "、".join(f"{k} {n}" for k, n in why.most_common()) + "）")
        L.append("")
        _unsure_table(L, plan, uns, where)
        L.append("")
    else:
        L.append("- 決められなかった違いはありません。")
        L.append("")
    if unmatched:
        L.append(f"- PDF に見つからなかった段落 {len(unmatched)} 件")
        L.append("")
        _unmatched_table(L, unmatched, text_of, where)
        L.append("")
    else:
        L.append("- PDF に見つからなかった段落はありません。")
        L.append("")
    if elsewhere:
        L.append(f"- ほかに、段落の位置は決められなかったが、同じ文字が PDF のどこかにある段落 {len(elsewhere)} 件（違いとしては数えていません）")
        L.append("")
    ign = ignored_lines(r)
    if ign:
        L.append(f"- 照合に使わなかった PDF の文字 {len(ign)} 行（誌名の行・柱・投稿受付日・表や図の中の文字とみなしたもの。一覧は出しません）")
        L.append("")
    if c.hidden_chars:
        L.append(f"- 出版版 PDF の、描かれない文字（図の枠の外に隠れた文字など）{c.hidden_chars:,} 字は、照合に使っていません。")
        L.append("")
    front_error = getattr(r.pdf_check, "front_error", "")      # 冒頭部の確かめは r.pdf_check の照合で行う（_front_pdf）
    if front_error:
        L.append(f"- 冒頭部（題目・著者名・所属）の、出版版 PDF との確かめはできませんでした（{esc(front_error)}）。"
                 "冒頭部の確かめのうち、PDF と比べる項目は出していません（照合の結果には影響しません）。")
        L.append("")
    L.append("- 表のセル・囲み・別行の数式・図の中の文字と、4 文字未満の段落は、段落ごとの照合をしていません"
             "（表のセル・囲みは、8 文字以上の行が PDF のどこかにあるかだけ確かめ、見つからない行は 13.1 に載せています。"
             "短い行と、直した後の文字が PDF のほかの場所にたまたまある行は見つけられません）。")
    # ---------------------------------------------------------------- 13.4
    if fx is not None:
        sup = r.supplement
        L.append("")
        L.append("### 13.4 補完の確かめ")
        L.append("")
        if sup is None:
            L.append("実施していません。")
        elif sup.ok:
            L.append(f"合格（表記を合わせた箇所 {sup.typeset} 文字）。補った docx は、元の docx から、13.2 の表記以外に変わっていません"
                     "（照合・直しとは別の実装で、変更履歴を取り除いた文字と図形の並びを元の docx と比べて確かめています）。")
        else:
            L.append("**不合格**です。補った docx に、表記を合わせたもの以外の変更があります（変換ツールの不具合の"
                     "可能性があります）。この XML は登載に使わないでください。")
            L.append("")
            L.append(table(["段落", "場所", "元の docx", "補った docx", "理由"],
                           [(src, fx.locations.get(src, "") or plan.locations.get(src, ""), esc(old, 40), esc(new, 40), why)
                            for src, old, new, why in sup.problems]))


def ai_style_section(r) -> list:
    """2 章の「注の区切り・資料の始まり（AI の回答で直した）」と「スタイルの提案（XML には反映していない）」の表（Markdown の行の一覧）。

    スタイルの表には、機械が挙げた段落（plan.style_suspects）と AI の提案（AIOutcome.style_fixes。確度 低と「このまま」も）をすべて載せる
    （要確認 style_check に載らなかった行の置き場所。AI を使っていなくても、機械が挙げた段落があれば出す）。修正計画 W8 の 4.3。
    """
    plan, ai = r.plan, r.ai
    L = []
    bs = list(getattr(ai, "boundaries", None) or [])
    if bs:
        L += ["", "### 注の区切り・資料の始まり（AI の回答で直した）", ""]
        L.append(table(["段落", "場所", "直したこと", "AI の根拠", "確度"],
                       [(b.src, plan.locations.get(b.src, ""), boundary_text(plan, b),
                         esc(b.reason), b.confidence) for b in bs]))
    fixes = _style_fix_of(ai)
    sus = {}
    for x in plan.style_suspects:
        sus.setdefault(x.src, x)
    srcs = list(dict.fromkeys(list(sus) + list(fixes)))
    if srcs:
        order = {src: i for i, src in enumerate(plan.paras)}
        srcs.sort(key=lambda s: order.get(s, len(order)))
        miss = set(abstract_missing_srcs(plan))
        front = front_reported_srcs(r)
        am = set(authors_missing_srcs(r))
        ff = front_findings(r)
        fc = frontcheck.finding_srcs(ff)
        fc_lead = "要対応" if any(f.level == frontcheck.MUST for f in ff) else "要確認"

        def front_note(src):        # 載せた知らせの名前（重さは知らせのとおり）
            got = (["要対応「和文の著者名が見つかりません」"] if src in am else []) + (
                [f"{fc_lead}「題目・著者名・所属」"] if src in fc else [])
            return "（冒頭部の確かめ〈" + "・".join(got) + "〉に載せた）"
        rows = []
        for src in srcs:
            x, f = sus.get(src), fixes.get(src)
            machine = (x.detail or STYLE_SUSPECT_JA.get(x.kind, ("",))[0]) if x is not None else "—"
            if f is None:
                proposal, conf, reason = "—", "—", "—"
            else:
                proposal = "このままでよい" if f.verdict == STYLE_KEEP else f.how
                conf, reason = f.confidence or "—", f.reason or "—"
            if src in miss:
                proposal += "（要対応「英文要旨が見つかりません」に載せた）"
            elif src in front:
                proposal += front_note(src)
            rows.append((src, plan.locations.get(src, ""), esc(_head(plan.paras.get(src), 20)), esc(machine), esc(proposal), conf,
                         md_tag(esc(reason))))
        L += ["", "### スタイルの提案（XML には反映していない）", ""]
        L.append("Word のスタイルで直せる誤りの見立てです。違っていれば Word でスタイルを直して変換し直してください（確度「高」「中」の"
                 "AI の提案と、機械が挙げた段落は、要確認「スタイルを確かめてください」にも載せています）。")
        L.append("")
        L.append(table(["段落", "場所", "文字", "機械の見立て", "AI の提案", "確度", "AI の根拠"], rows))
    return L


REREAD_SHOWN = 5        # 段落の ID を読み替えた指定を、2 章に例として挙げる数


def ai_pdf_sent(ai) -> str:
    """2 章の概要の「出版版 PDF」（API モード）: AI に渡したか。渡していなければ理由（AIOutcome.pdf_note）。"""
    if ai.reused:
        return "前の変換の回答を使ったため、呼び出していない" + ("（その回答は PDF を付けて得たもの）" if ai.pdf_sent else "")
    if ai.pdf_sent == "pages":
        return "ページの画像にして渡した（依頼のデータの前に付けて送信）" + (f"。{esc(ai.pdf_note)}" if ai.pdf_note else "")
    if ai.pdf_sent:
        return "渡した（依頼のデータの前に付けて送信）" + (f"。{esc(ai.pdf_note)}" if ai.pdf_note else "")
    return "渡していない" + (f"（{esc(ai.pdf_note)}）" if ai.pdf_note else "")


def ai_check_lines(ai) -> list:
    """依頼の番号と段落の先頭の文字での確かめ（ai_assist.check_answer）の結果の行（2 章と AI の判断一覧）: 前の変換の回答
    （AI回答.json）を使い、API を呼ばなかったこと（AIOutcome.reused）、原稿を直す前の回答を使ったこと（AIOutcome.carried）と、
    段落の ID を先頭の文字で読み替えた指定（AIOutcome.reread）、括弧・引用符の違いだけで先頭の文字と合わなかった指定（loose_heads）。"""
    out = []
    if ai.reused:
        out.append(esc(ai.reused))
    if ai.carried:
        out.append(f"**原稿を直す前の回答です。** {esc(ai.carried)}")
    if ai.reread:
        ex = "、".join(f"{a} → {b}" for _, a, b in ai.reread[:REREAD_SHOWN]) + ("など" if len(ai.reread) > REREAD_SHOWN else "")
        out.append(f"段落の ID が段落の先頭の文字と合わなかった指定 {len(ai.reread)} 件を、同じ先頭の文字の段落に読み替えました"
                   f"（{ex}）。")
    loose = list(getattr(ai, "loose_heads", None) or [])
    if loose:
        ex = "、".join(src for _, src in loose[:REREAD_SHOWN]) + ("など" if len(loose) > REREAD_SHOWN else "")
        out.append(f"段落の先頭の文字（head）が括弧・引用符の違いだけで合わなかった指定 {len(loose)} 件を、ほかに紛れる段落がないので、"
                   f"その段落への指定とみなしました（{ex}）。")
    return out


def render_ai_only(r) -> str:
    """AI による判断だけをまとめた別ファイル（不確実性のある箇所の一覧）。"""
    ai = r.ai
    L = [f"# AI による仕上げの判断一覧: {r.docx_name}", "",
         "AI（生成 AI）が判断した箇所の一覧です。AI は本文の文字を変更していません（AI の回答で変わるのは、図・表の位置、"
         "文字だけのテキストボックスの種類と位置、リンク、姓名の区切り、注の区切りと資料の始まりのみ。Word のスタイルで直せる"
         "段落の役割は提案だけで、XML には反映していません）。"
         "確度の低いものから順に並べています。PDF と照らして確認してください。", ""]
    acc = [d for _, d in ai.accepted]
    if ai.partial:
        L += [f"**AI の回答が途中で切れていました。** {esc(ai.partial)}", ""]
    for line in ai_check_lines(ai):
        L += [line, ""]
    if ai.error:
        L.append(f"AI による仕上げは行えませんでした: {ai.error}")
    elif not acc and not ai.rejected:
        L.append("AI の判断はありません。")
    order = {"低": 0, "中": 1, "高": 2}
    for d in sorted(acc, key=lambda d: (order.get(d.confidence, 3), d.did)):
        L.append(f"- **{d.did}（確度 {d.confidence}）** {d.location or r.plan.locations.get(d.src, d.src)}: {esc(d.message)}")
    if ai.rejected:
        L += ["", "## 検証で採用しなかった提案", ""]
        for op, why in ai.rejected:
            L.append(f"- {op.get('op')} [{op.get('src')}] 「{esc(op.get('text') or op.get('role') or op.get('image'))}」: {md_tag(why)}")
    if ai.notes:
        L += ["", "## AI からの気づき", ""]
        L += [f"- {esc(n)}" for n in ai.notes]
    L += [x.replace("### ", "## ", 1) if x.startswith("### ") else x for x in ai_style_section(r)]
    return "\n".join(L) + "\n"
