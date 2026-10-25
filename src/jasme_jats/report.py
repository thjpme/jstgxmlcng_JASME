"""変換レポート（Markdown）。

冒頭に結果の要約、続いて AI による補完（不確実性のある箇所）、機械処理で解決できなかった箇所、
機械的な推定、出力しなかった文字の全件、落とした空白の全件、生成文字、画像、書誌情報、DTD 検証と J-STAGE の登載時チェック、
出版版 PDF との照合、登載前のチェックリストの順に並べる。
"""
from __future__ import annotations

from collections import Counter

from pathlib import Path

from .ai_assist import PROVIDERS
from .linker import body_paragraphs, linked_ids
from .package import article_dir
from .pdfmatch import (DISPLACED_WHY, EDGE_WHY, FAR_WHY, FORMULA_MARK, HEAD_WHY, LINE_MARK, LONG_WHY, MATH_WHY, RE_PAGE_NO,
                       UNSURE_WHY, WHOLE_WHY)
from .structure import ENDNOTE_EXCLUDED, TEXTBOX_TEXT_EXCLUDED


def esc(s, n=None) -> str:
    s = "" if s is None else str(s)
    s = s.replace("|", "｜").replace("\n", "⏎").replace("\t", "⇥")
    if n and len(s) > n:
        s = s[:n] + "…"
    return s


def table(headers, rows) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(esc(c) for c in r) + " |")
    return "\n".join(out)


CAT_JA = {"style": "段落の役割（スタイル）", "citation": "引用文献へのリンク", "xref": "図表・注・数式へのリンク",
          "formula": "数式", "name": "著者名", "figure": "図", "table": "表", "url": "URL", "note": "注"}
UNRES_JA = {"bibr": "引用文献", "fig": "図の参照", "table": "表の参照", "fn": "注の参照", "float": "図表の位置"}


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
    """本文から参照されていない図・表と、キャプションのない表（PDF と照らして確認するためのもの）。"""
    out = []
    figs, tabs = linked_ids(plan, "fig"), linked_ids(plan, "table")
    nf = [f"{f.fid}（{esc(f.caption.plain()[:20])}）" for f in plan.figures
          if f.fid and f.caption is not None and f.fid not in figs]
    if nf:
        out.append("本文中のどこからも参照（リンク）されていない図: " + "、".join(nf))
    nt = [f"{t.tid}（{esc(t.caption.plain()[:20])}）" for t in plan.tables
          if t.tid and t.caption is not None and t.tid not in tabs]
    if nt:
        out.append("本文中のどこからも参照（リンク）されていない表: " + "、".join(nt))
    nc = []
    for t in plan.tables:
        if t.caption is None:
            first = next((p.plain().strip() for p in (t.table.paragraphs() if t.table else []) if p.plain().strip()), "")
            nc.append(f"{t.tid or '-'}（最初のセル「{esc(first[:15])}」）")
    if nc:
        out.append("キャプションのない表（表番号がないため本文からリンクできない。表として出力した）: " + "、".join(nc))
    return out


def images_to_prepare(r) -> list:
    """利用者が用意する必要のある画像（画像ファイルがない Word の図形、変換できなかった EMF など）。

    戻り値: [(出力ファイル名, 図のキャプション, 理由)]。レポートの冒頭・14 章、Colab の枠、コマンドラインの表示で使う。
    """
    caps = {}
    for f in r.plan.figures:
        cap = f.caption.plain().strip() if f.caption is not None else ""
        for img in [i for ip in f.image_paras for i in ip.images] + list(f.extra_images):
            caps.setdefault(img.image_id, cap)
    out = []
    for i in r.images:
        if i.status not in ("missing", "failed"):
            continue
        if i.status == "missing" and not i.source:
            why = "Word の図形・グラフで描かれていて、docx に画像ファイルがない"
        else:
            why = i.message
        out.append((i.name, caps.get(i.image_id, ""), why))
    return out


LOST_IMAGES_WHY = ("docx にあるのに、画像を出力できない場所（引用文献・題目・著者名・所属の段落など）や、XML に出力しなかった"
                   "段落の中にあるため、XML にも Graphics/ にも入っていません。このままでは、その画像は J-STAGE の画面に表示されません。")
LOST_IMAGES_ACTION = ("本文に必要な画像なら、Word でその画像（テキストボックスなどの図形に入っているときは図形ごと）を本文の段落に"
                      "移してから、変換し直してください。PDF にない装飾など、要らない画像なら、対応は要りません。")


def lost_image_label(li) -> str:
    """XML に入らなかった画像（pipeline.lost_images）1 件の見出し。例: img3（段落 d45「試験太郎（2020）」、引用文献 2件目）。

    レポートの冒頭・9 章・14 章、Colab の枠、コマンドラインの表示で使う。
    """
    where = []
    if li.src:
        where.append(f"段落 {li.src}" + (f"「{li.text}」" if li.text else ""))
    if li.location:
        where.append(li.location)
    return f"{li.image_id}（{'、'.join(where)}）" if where else li.image_id


def provisional_exclusions(r) -> list:
    """XML に出力しなかった、文字だけのテキストボックスの段落と Word の文末脚注の段落（要確認）。

    どちらも今の版では XML に出力できないので、レポートの 6 章に載るだけだと見落とされる。出力できるようになるまで、
    レポートの冒頭と 14 章で件数と対処を知らせる（暫定の知らせ）。
    戻り値: [(種類 "textbox" / "endnote", [(段落, 文字)])]。該当がなければ、その種類は入らない。
    """
    out = []
    for kind, reason in (("textbox", TEXTBOX_TEXT_EXCLUDED), ("endnote", ENDNOTE_EXCLUDED)):
        rows = [(src, text) for src, why, text in r.fidelity.excluded if why == reason]
        if rows:
            out.append((kind, rows))
    return out


# 暫定の知らせ: 種類 -> (何を, 冒頭の説明と対処, 14 章の対処)
PROVISIONAL = {
    "textbox": ("テキストボックスの中の文字 {n} 段落",
                "今の版では、図・表を含まないテキストボックス（囲み）の文字は、図の一部とみなして本文から除いています。"
                "問題文などの囲みで本文に必要な文字なら、Word でその文字をテキストボックスの外（本文の段落）に出してから、"
                "変換し直してください。",
                "本文に必要か確かめ、問題文などの囲みなら Word でテキストボックスの外（本文の段落）に出して変換し直す"),
    "endnote": ("Word の文末脚注 {n} 段落",
                "今の版では、Word の文末脚注を XML に出力できません。注の内容を、本文の注（テンプレートの書き方: 本文に上付きの"
                "「1)」を書き、注は「注」の節にまとめる）に移してから、変換し直してください。",
                "本文の注（テンプレートの書き方: 本文に上付きの「1)」、注は「注」の節）に移して変換し直す"),
}


def _para_samples(rows, n=5) -> str:
    """段落の例（例: d12「文字の冒頭」、d13「…」）。文字のない段落（画像だけの段落など）は「d14（文字なし）」と書く。"""
    return ("、".join(f"{src}「{esc(text.strip(), 15)}」" if text.strip() else f"{src}（文字なし）" for src, text in rows[:n])
            + ("ほか" if len(rows) > n else ""))


def image_summary(r) -> str:
    """1 章の要約の「画像」の行。XML に入らなかった画像があるときは、XML に出力した画像と分けて書く。"""
    need = sum(1 for i in r.images if i.status in ("failed", "missing"))
    if not r.lost_images:
        return f"{len(r.images)} 件（要対応 {need} 件、9 章）"
    return (f"XML に出力 {len(r.images)} 件（うち要対応 {need} 件）。ほかに XML に入らなかった画像が {len(r.lost_images)} 件あり、"
            "要対応（9 章）")


def graphics_dir(r) -> str:
    """ZIP の中の Graphics フォルダ（例: jasme/25/1/25_77/Graphics/）。"""
    return (article_dir(Path(""), r.journal, r.meta) / "Graphics").as_posix() + "/"


ROUTE_JA = {"docx": "docx から作る（ルート1。docx の文字は 1 文字も変えない）",
            "pdf": "出版版 PDF に合わせてから作る（ルート2。PDF に合わせて直した docx を変換）"}
NUMBER_KINDS = {"auto": "自動段落番号", "fnref": "本文の脚注番号", "fnlist": "注の一覧の脚注番号"}


def pdf_summary(r) -> str:
    """出版版 PDF との照合の要約（レポートの 1 章、コマンドライン・Colab の表示）。"""
    pc, fx = r.pdf_check, r.docx_fix
    if pc is None:
        return "PDF なし（照合していない）"
    if not pc.ok:
        return f"照合できなかった（{pc.message}）"
    unmatched = fx.unmatched if fx is not None else pc.unmatched
    if fx is not None:
        from .pdfdocx import tracked_counts
        ins, dels = tracked_counts(fx.path)
        parts = [f"PDF に合わせて docx を直した {len(fx.applied)} 箇所（変更履歴: 挿入 {ins}・削除 {dels}）"]
        if fx.skipped:
            parts.append(f"直せなかった {len(fx.skipped)} 箇所（要確認）")
        if ignored_lines(r):
            parts.append(ignored_summary(r))
        if pc.number_edits:
            parts.append(f"Word が付けた番号を PDF に合わせた {len(pc.number_edits)} 件")
        if pc.diffs or pc.width_count:
            parts.append(f"直した後も残る違い {len(pc.diffs) + pc.width_count} 件")
    else:
        parts = [f"文字の違い {len(pc.diffs)} 件" + ("（要確認）" if pc.diffs else "")]
        if pc.width_count:
            parts.append(f"全角・半角の違い {pc.width_count} 文字（docx のまま）")
        if ignored_lines(r):
            parts.append(ignored_summary(r))
    if unmatched:
        parts.append(f"PDF に見つからない段落 {len(unmatched)} 件"
                     + ("（半分以上の段落が見つからない。別の記事の PDF ではないか確認）" if len(unmatched) * 2 > pc.checked else ""))
    return " / ".join(parts) + "（13 章）"


def ignored_lines(r) -> list:
    """組版で入る文字（誌名の行・柱・投稿受付日など）や図・表の中の文字とみなして、照合に使わなかった PDF の文字
    [(段落 ID, 行または投稿受付日の文字列)]。

    ルート2 では、元の docx と PDF の照合（直す箇所を決めたもの）から。
    """
    fx = r.docx_fix
    pc = fx.check if fx is not None and fx.check is not None else r.pdf_check
    return list(pc.ignored_lines) if pc is not None and pc.ok else []


IGNORED_TITLE = "照合に使わなかった PDF の文字（誌名の行・投稿受付日・表や図の中の文字など）"
IGNORED_NOTE = ("段落の途中にあった PDF の文字のうち、組版で入る文字（誌名の行・柱・投稿受付日など）や、docx にない図・表の中の"
                "文字（表のセルの数字、図の中の語句など）とみなして、照合に使わなかったものです（ページの端の行・ページの途中の"
                "数字だけの行・短い行などで、docx のどの段落の文字とも一致しなかったもの）。表・図の中の文字や、docx のほかの段落に"
                "すでにある文字なら、対応は要りません。PDF では本文なのに docx にない文字（校正で足された一文など）があったときだけ、"
                "docx を手で直してから変換し直してください。")
# ルート2 で添える文。照合に使わなかった文字が docx のほかの段落にある文字なら、照合がその段落の文字を取り違えて、元の段落から
# 消していないか（隣り合う段落に同じ文がくり返す形など。docs/DESIGN.md の 4.4 の「限界」）も 13.1 で確かめてもらう
IGNORED_NOTE_ROUTE2 = ("これらの文字は、PDF に合わせて直した docx にも入れていません。docx のほかの段落にある文字のときは、その文字を"
                       " 13.1 で元の段落から消していないかも確かめてください（消していれば、直した docx を Word で開いてその変更を"
                       "却下し、却下して保存した docx を「docx から作る」で変換し直します）。")
IGNORED_NUMBERS = 8      # 数字だけの行を一覧に並べる数（それより多ければ「…」）


def ignored_summary(r) -> str:
    """1 章の要約（とコマンドライン・Colab の表示）の、照合に使わなかった PDF の文字の件数。"""
    rows = ignored_lines(r)
    return (f"照合に使わなかった PDF の文字 {len(rows)} 件（{len({s for s, _ in rows})} 段落。誌名の行・投稿受付日・表や図の"
            "中の文字などとみなしたもの。本文が混じっていないか確認）")


def ignored_rows(rows, loc_of) -> list:
    """照合に使わなかった PDF の文字を、段落ごとに 1 行にする: [(段落, 場所, 行数, PDF の文字)]。

    PDF の文字は、数字だけの行（表のセルの数字など）以外の行を先に LINE_MARK（行の変わり目の記号）でつなぎ、数字だけの行は
    件数と最初のいくつかにまとめる（表が段落の途中に入ると、セルの数字が何十行も並ぶため）。
    """
    by_src = {}
    for s, t in rows:
        by_src.setdefault(s, []).append(t)
    out = []
    for s, ts in by_src.items():
        nums = [t for t in ts if RE_PAGE_NO.match(t)]
        parts = [esc(t, 60) for t in ts if not RE_PAGE_NO.match(t)]
        if nums:
            parts.append(f"数字だけの行 {len(nums)} 件: " + "、".join(esc(t) for t in nums[:IGNORED_NUMBERS])
                         + ("…" if len(nums) > IGNORED_NUMBERS else ""))
        out.append((s, loc_of(s), str(len(ts)), LINE_MARK.join(parts)))
    return out


def _ignored_section(L, r, number, loc_of):
    """13 章の、照合に使わなかった PDF の文字の一覧（段落ごとに 1 行）。"""
    rows = ignored_lines(r)
    L.append(f"### 13.{number} {IGNORED_TITLE}")
    L.append("")
    if not rows:
        L.append("ありません。")
        return
    L.append(IGNORED_NOTE + (IGNORED_NOTE_ROUTE2 if r.docx_fix is not None else ""))
    L.append("")
    L.append(table(["段落", "場所", "行数", f"PDF の文字（{LINE_MARK} は行の変わり目）"], ignored_rows(rows, loc_of)))


def _clean(t) -> str:
    return esc(t.replace(chr(0xFFFC), "〓"))


def _snippets(text, edits) -> list:
    """段落の中の変更 [(開始, 終了, 新しい文字)] を、近いものどうしまとめて「変更前」→「変更後」の形にする。"""
    clusters = []
    for e in sorted(edits):
        if clusters and e[0] - clusters[-1][-1][1] <= 3:
            clusters[-1].append(e)
        else:
            clusters.append([e])
    out = []
    for cl in clusters:
        a, b = cl[0][0], cl[-1][1]
        s0, s1 = max(0, a - 4), min(len(text), b + 4)
        after, pos = [], s0
        for st, en, new in cl:
            after += [text[pos:st], new]
            pos = en
        after.append(text[pos:s1])
        out.append(f"「{_clean(text[s0:s1])}」→「{_clean(''.join(after))}」")
    return out


def width_rows(r) -> list:
    """ルート1: 全角・半角だけの違い（docx のまま）を段落ごとに: [(段落, 場所, 文字数, 「docx」→「PDF」…)]。"""
    pc = r.pdf_check
    rows = []
    for src, p in r.plan.paras.items():
        subs, drops = pc.width.get(src, {}), pc.drops.get(src, set())
        if not subs and not drops:
            continue
        edits = [(q, q + 1, c) for q, c in subs.items()] + [(q, q + 1, "") for q in drops]
        n = f"{len(subs)}" + (f"（空白 {len(drops)}）" if drops else "")
        rows.append((src, r.plan.locations.get(src, ""), n, "、".join(_snippets(p.plain(), edits))))
    return rows


def fix_rows(fx) -> list:
    """ルート2: PDF に合わせて直した箇所を段落ごとに: [(段落, 場所, 箇所数, 「変更前」→「変更後」…)]。"""
    by_src = {}
    for f in fx.applied:
        by_src.setdefault(f.src, []).append(f)
    return [(src, fx.locations.get(src, ""), str(len(fs)), "、".join(_snippets(fx.texts[src], [(f.start, f.end, f.new)
                                                                                         for f in fs])))
            for src, fs in by_src.items()]


INSERT_AT = "［］"      # ルート2 の 13.2 の docx の欄で、PDF にだけある文字の位置を示す記号
# 13.2 の docx の欄で、違う部分を前後の docx の文字とともに出す（「［…］」で囲む）、直さなかった理由（分断された段落の、本体から
# 離れた部分・図や表の中の文字に挟まれた部分。隣の文字との 1〜2 文字の偶然の一致で違いが短く区切られることがあり〈「12点」の
# 「2」→「13」〉、表のとおりに置き換えると docx にも PDF にもない文字になる）
CONTEXT_WHYS = (FAR_WHY, DISPLACED_WHY)
# 13 章の表（と Colab の枠）の「〓」の説明。docx の側（docx・前後の欄）では docx の数式・画像、PDF の側では PDF で文字として
# 読み取れない数式などの位置（同じ記号なので、表に「〓」があるときは、表の前に必ず添える）
FORMULA_NOTE = (f"表の「{FORMULA_MARK}」は、docx の欄と前後の欄では docx の数式・画像、PDF の欄では PDF で数式など文字として"
                "読み取れない部分です。")


def _formula_note(L, cells):
    """表の文字 cells のどれかに FORMULA_MARK があれば、表の前に FORMULA_NOTE を添える。"""
    if any(FORMULA_MARK in (c or "") for c in cells):
        L.append(FORMULA_NOTE)
        L.append("")


def _skipped_docx(f, text, n=8) -> str:
    """ルート2 の 13.2 の docx の欄: 直さなかった箇所の docx の文字（数式・画像は 〓）。docx の側に文字がない箇所（PDF にだけある
    文字。f.start == f.end）は、docx の段落の文字 text の、その位置の前後 n 文字（「…確率［］が…」）。分断された段落の部分の
    違い（CONTEXT_WHYS）も、違う部分を「［…］」で囲んで前後 n 文字とともに出す（「…平均は１［2］点であり…」）。"""
    if not text or (f.start != f.end and f.reason not in CONTEXT_WHYS):
        return esc(f.old.replace(chr(0xFFFC), "〓"), 30)
    a, b = f.start, f.end
    return esc(_clean(("…" if a > n else "") + text[max(0, a - n):a] + "［" + text[a:b] + "］" + text[b:b + n]
                      + ("…" if b + n < len(text) else "")), 60)


def number_rows(r) -> list:
    pc = r.pdf_check
    rows = []
    for (kind, ident), chg in pc.numbers.items():
        old = pc.original[(kind, ident)]
        new = "".join(chg.get(i, c) for i, c in enumerate(old))
        where = r.plan.locations.get(ident, ident) if kind == "auto" else f"Word の脚注 {ident}"
        rows.append((NUMBER_KINDS[kind], where, f"「{esc(old.strip())}」→「{esc(new.strip())}」"))
    return rows


def word_note_refs(plan) -> int:
    """本文中の Word の脚注参照（注へのリンクとして出力されるもの）の数。"""
    ids = {fn.word_id for fn in plan.fns if fn.word_note}
    return sum(1 for p in plan.paras.values() for a in p.atoms
               if a.kind == "fnref" and a.fn_kind.startswith("footnote") and a.fn_id in ids)


def note_notes(plan):
    """注（Word の脚注機能を使わずに書かれたもの）の番号と、本文での参照の対応。PDF と照らして確認するためのもの。"""
    out = []
    fns = [fn for fn in plan.fns if not fn.word_note]
    if not fns:
        return out
    order = []   # 本文で初めて参照された順
    for p, where in body_paragraphs(plan):
        if where in ("ref", "fn"):
            continue
        for a in p.atoms:
            if a.link is not None and a.link.kind == "xref" and a.link.attrs.get("ref-type") == "fn":
                if a.link.attrs.get("rid") not in order:
                    order.append(a.link.attrs.get("rid"))
    nums = [fn.number for fn in fns]
    unnum = [fn for fn in fns if fn.number is None]
    if unnum:
        out.append("先頭に番号（「1)」「（注1）」など）を読み取れなかった注: " + "、".join(
            f"{fn.fid}（「{esc(fn.paras[0].plain()[:20])}」"
            + (f"。{len(fn.paras)} 段落を 1 件の注にまとめた" if len(fn.paras) > 1 else "") + "）" for fn in unnum)
            + "。番号の書き方が想定外のため、複数の注が 1 件にまとめられている可能性がある。PDF と照らして確認し、"
              "AI 補完（注の区切りの指定）を使うか、docx の注の番号をテンプレートの形式（「1)」）にしてから変換し直す")
    elif nums != list(range(1, len(nums) + 1)):
        out.append("注の番号が 1 からの連番になっていない: " + "、".join(str(n) for n in nums))
    unref = [f"{fn.fid}（{esc(fn.paras[0].plain()[:20])}）" for fn in fns if fn.fid not in order]
    if unref:
        out.append("本文中のどこからも参照（リンク）されていない注: " + "、".join(unref))
    by_id = {fn.fid: fn.number for fn in fns}
    seq = [by_id[r] for r in order if by_id.get(r) is not None]
    if seq != sorted(seq):
        out.append("本文で注が番号順に参照されていない（本文での初出の順: " + " → ".join(f"注{n}" for n in seq) + "）")
    return out


def render(r) -> str:
    plan, fid = r.plan, r.fidelity
    L = []
    L.append(f"# 変換レポート: {r.docx_name}")
    L.append("")
    L.append(f"- 作成日時: {r.created}")
    L.append(f"- ツール: jasme-jats {r.tool_version}")
    L.append(f"- 図表番号の扱い: {'<label> とタイトルに分ける（間の空白のみ落とす）' if r.split_labels else '番号もタイトルと一緒に 1 つの要素に入れる（文字を落とさない）'}")
    ai = r.ai
    api = f"API（{PROVIDERS.get(ai.provider, ai.provider)}: {ai.model}）"
    ai_mode = {"none": "使用しない", "api": api, "manual": "手動（チャットに貼り付け）"}.get(ai.mode, ai.mode)
    L.append(f"- AI による補完: {ai_mode}")
    L.append(f"- 作り方: {ROUTE_JA.get(r.route, r.route)}"
             + ("（PDF の文字を読めなかったので、docx を直さずに変換した）" if r.route == "pdf" and r.docx_fix is None else ""))
    L.append("")

    # ------------------------------------------------------------------ 1. 要約
    L.append("## 1. 結果の要約")
    L.append("")
    fid_line = (f"{fid.summary()}（docx の段落 {fid.units} 件: XML に出力 {fid.mapped} 件、出力しなかった {len(fid.excluded)} 件"
                f"［6 章に全文］）")
    if r.docx_fix is not None:
        fid_line += f"。照合の相手は、出版版 PDF に合わせて直した docx（{r.docx_fix.path.name}）"
    final_line = "合格" if fid.final_ok else ("不合格: " + fid.final_detail if fid.final_ok is False else "未実施")
    c = r.link_counts
    wn = word_note_refs(plan)
    fn_links = f"{c.get('fn', 0) + wn}" + (f"（うち Word の脚注 {wn}）" if wn else "")
    links = (f"引用文献 {c.get('bibr', 0)} / 図 {c.get('fig', 0)} / 表 {c.get('table', 0)} / 注 {fn_links} / "
             f"数式 {c.get('disp-formula', 0)} / URL {c.get('url', 0) + c.get('word', 0)} / DOI {c.get('doi', 0)}")
    ai_acc = [d for _, d in ai.accepted]
    rows = [
        ("本文の文字の不変性チェック（AI 補完の後に実施）", fid_line),
        ("最終出力（目印を取り除いた XML）の再チェック", final_line),
        ("J-STAGE 指定 DTD（JATS 1.1）による検証", "合格" if r.dtd_valid else f"不合格（{len(r.dtd_errors)} 件、12 章）"),
        ("J-STAGE のアップロード時チェック（XML で判定できるもの）",
         "問題なし" if not r.jstage_issues else f"要対応 {len(r.jstage_issues)} 件（12 章）"),
        ("機械的に付けたリンク", links),
        ("AI が付けたリンク・判断（2 章）", f"採用 {len(ai_acc)} 件 / 不採用 {len(ai.rejected)} 件" if ai.mode != "none" else "AI 補完なし"),
        ("機械処理で解決できなかった箇所（3 章）", f"{len(r.unresolved_after)} 件"),
        ("画像", image_summary(r)),
        ("警告", f"{len(r.warnings)} 件（10 章）"),
        ("出版版 PDF との照合", pdf_summary(r)),
    ]
    if plan.unplaced_floats:
        rows.insert(7, ("位置を決められなかった図表（3 章）", f"{len(plan.unplaced_floats)} 件（本文の冒頭に仮に配置）"))
    L.append(table(["項目", "結果"], rows))
    L.append("")
    if not fid.ok or fid.final_ok is False:
        L.append("> **注意: 文字の不変性チェックが不合格です。** 出力された XML の本文が docx と一致していません。"
                 "下の 5 章の差分を確認し、この XML は登載に使わないでください（変換ツールの不具合の可能性があります）。")
        L.append("")
    if r.forced_floats:
        L.append(f"> **要対応: 位置を決められなかった図表が {len(r.forced_floats)} 件あります（AI による補完でも決まりませんでした）。** "
                 "本文の冒頭に仮に置いています。登載の前に、XML の中でこれらの図表を手作業で正しい位置（Word で表示したときに、図の左上の"
                 "直上にある本文の段落の後）に移してください（3 章）: " + "、".join(esc(x) for x in r.forced_floats))
        L.append("")
    need = images_to_prepare(r)
    if need:
        zname = r.zip_path.name if r.zip_path else "アップロード用の ZIP"
        L.append(f"> **要対応: 画像ファイルを用意できなかった図が {len(need)} 件あります（9 章）。** 次の名前の画像（PNG）を"
                 f"作り、{esc(zname)} の中の `{graphics_dir(r)}` に入れてください。画像がないままでは、その図が J-STAGE の"
                 "画面に表示されません。")
        L.append(">")
        for name, cap, why in need:
            L.append(f"> - `{name}`: {esc(cap, 40) or '（キャプションなし）'}（{esc(why)}）")
        L.append("")
    lost = r.lost_images
    if lost:
        L.append(f"> **要対応: XML に入らなかった画像が {len(lost)} 件あります（9 章）。** {LOST_IMAGES_WHY}{LOST_IMAGES_ACTION}")
        L.append(">")
        for li in lost:
            L.append(f"> - {esc(lost_image_label(li))}: {esc(li.reason)}")
        L.append("")
    pc, fx = r.pdf_check, r.docx_fix
    if fx is not None:
        L.append(f"> **出版版 PDF に合わせて docx を直してから変換しました（13 章）。** 直した docx（{esc(fx.path.name)}）は "
                 "Word の変更履歴つきです。Word で開いて変更を確認し、却下したい変更があれば、却下して保存した docx を"
                 "「docx から作る」で変換し直してください。"
                 + (f"**直せなかった箇所が {len(fx.skipped)} 件あります。**" if fx.skipped else ""))
        L.append("")
    elif pc is not None and pc.ok and (pc.diffs or pc.width_count):
        L.append(f"> **要確認: 出版版 PDF と文字が違う箇所が {len(pc.diffs)} 件、全角・半角の違いが {pc.width_count} 文字あります"
                 "（13 章）。** 受け取った docx が、著者校正を経た最終版ではない可能性があります。XML は docx の文字のままです。"
                 "PDF に合わせるときは、「出版版 PDF に合わせてから作る」で変換し直すか、docx を直して変換し直してください。")
        L.append("")
    provisional = provisional_exclusions(r)
    for kind, prow in provisional:
        title, detail, _ = PROVISIONAL[kind]
        L.append(f"> **要確認: {title.format(n=len(prow))}を、XML に出力していません（6 章）。** {detail}"
                 f"対象の段落: {_para_samples(prow)}")
        L.append("")
    if r.output_note:
        L.append(r.output_note)
        L.append("")

    # ------------------------------------------------------------------ 2. AI
    L.append("## 2. AI による補完（要確認）")
    L.append("")
    if ai.mode == "none":
        L.append("AI による補完は行っていません。")
    elif ai.error:
        L.append(f"AI による補完は行えませんでした: {ai.error}")
    else:
        L.append("AI の判断には誤りの可能性があります。特に確度「低」「中」の項目は、PDF と照らして確認してください。"
                 "AI が変更できるのはリンク・段落の役割・姓名の区切り・数式画像への MathML の併記と、テキストボックス・"
                 "グループ図形に入った図表の位置と組み合わせだけで、本文の文字は変更していません。")
        L.append("")
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
                     why, op.get("reason")) for op, why in ai.rejected]
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
        if ai.usage:
            L.append(f"（API 使用量: 入力 {ai.usage.get('input_tokens')} トークン / 出力 {ai.usage.get('output_tokens')} トークン）")
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
        L.append("本文中のどこからもリンクされていない文献: " + "、".join(
            f"{rid}（{esc(next((x.para.plain()[:30] for x in plan.refs if x.rid == rid), ''))}）" for rid in unc))
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
        L.append(table(["段落", "理由", "文字"], [(s, reason, esc(t, 100)) for s, reason, t in fid.excluded]))
    else:
        L.append("ありません。")
    other = []
    if r.hidden_text:
        other.append("隠し文字（Word で非表示に設定された文字）: " + "、".join(f"［{s}］{esc(t, 40)}" for s, t in r.hidden_text))
    if r.hidden_images:
        other.append(f"隠し文字の中の画像 {len(r.hidden_images)} 件（{'、'.join(r.hidden_images)}）: Word で表示されないので、"
                     "出力していません。")
    if r.tracked_changes:
        other.append(f"変更履歴が {r.tracked_changes} 箇所あります。挿入は反映し、削除は出力していません（Word で表示される最終版と同じ）。")
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
    L.append("姓と名、図表番号とタイトルのように、JATS で別々の要素に分ける箇所の区切りの空白だけを落としています"
             "（J-STAGE の表示では区切りが補われます）。空白以外の文字は落としていません。")
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
    L.append("Word の自動段落番号や脚注番号は docx の文字ではなく Word が表示時に作るものです。表示どおりの文字を XML に出力しました"
             "（Word の脚注機能で書かれた注の番号だけは、Word の表示「1」ではなく本誌の形式（設定 fn_mark）にしています）。"
             "出版版 PDF があれば、自動番号・脚注番号の全角・半角を PDF に合わせています（13 章）。"
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

    if fid.ai_additions:
        L.append("### AI が画像から読み取って併記した数式（docx の文字ではない）")
        L.append("")
        L.append("数式が画像で貼られていた箇所に、AI が読み取った MathML を元の画像と並べて（<alternatives>）出力しました。"
                 "本文の文字ではありませんが、読み取りに誤りがないか確認してください。")
        L.append("")
        L.append(table(["判断の番号", "読み取った数式（MathML の文字）"], fid.ai_additions))
        L.append("")

    # ------------------------------------------------------------------ 9. 画像
    L.append("## 9. 画像")
    L.append("")
    if r.images:
        st = {"ok": "そのまま出力", "converted": "変換して出力", "failed": "要対応", "missing": "要対応（画像なし）",
              "user": "利用者が用意"}
        L.append(table(["画像", "出力ファイル（Graphics/）", "docx 内のファイル", "状態", "備考"],
                       [(i.image_id, i.name, i.source, st.get(i.status, i.status), i.message) for i in r.images]))
    elif lost or r.hidden_images:
        L.append("XML に出力した画像はありません。")
    else:
        L.append("画像はありません。")
    L.append("")
    if lost:
        L.append("### XML に入らなかった画像（要対応）")
        L.append("")
        L.append(f"{LOST_IMAGES_WHY}{LOST_IMAGES_ACTION}")
        L.append("")
        L.append(table(["画像", "docx 内のファイル", "段落", "場所", "段落の文字", "出力しなかった理由（推定）"],
                       [(li.image_id, li.source or "（Word の図形）", li.src or "-", li.location, li.text, li.reason)
                        for li in lost]))
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
            L.append(f"- {esc(w)}")
    else:
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
            ("キーワード（日）", "；".join(m.keywords_ja) or "（なし）"),
            ("キーワード（英）", "; ".join(m.keywords_en) or "（なし）"),
            ("抄録の二次利用（specific-use）",
             f"{j.abstract_specific_use}（英文の論文で英文要旨を <abstract> に入れるときだけ使う。学会の方針を確認すること）")]
    L.append(table(["項目", "値"], rows))
    L.append("")

    # ------------------------------------------------------------------ 12. DTD・J-STAGE のチェック
    L.append("## 12. DTD 検証と J-STAGE のアップロード時チェックの詳細")
    L.append("")
    L.append("### DTD 検証")
    L.append("")
    if r.dtd_valid:
        L.append("J-STAGE 指定の DTD（https://www.jstage.jst.go.jp/dtds/1.1/JATS-journalpublishing1.dtd と同一の同梱版）で検証し、エラーはありませんでした。")
    else:
        for e in r.dtd_errors[:100]:
            L.append(f"- {esc(e)}")
    L.append("")
    L.append("### J-STAGE のアップロード時チェック")
    L.append("")
    L.append("DTD に合っていても J-STAGE のアップロードで弾かれる条件（題目と抄録の言語の対応、日付の前後、所属番号など）のうち、"
             "XML だけで判定できるものを『記事アップロードメッセージ一覧』に沿って確かめた結果です。")
    L.append("")
    if r.jstage_issues:
        L.append(table(["メッセージ ID", "内容"], r.jstage_issues))
    else:
        L.append("該当するエラーはありませんでした（J-STAGE 側でしか判定できない項目は、アップロード時に確認してください）。")
    L.append("")

    # ------------------------------------------------------------------ 13. 出版版 PDF との照合
    L.append("## 13. 出版版 PDF との照合")
    L.append("")
    if pc is None:
        L.append("記事の PDF がないため、照合していません。")
    elif not pc.ok:
        L.append(f"照合できませんでした: {esc(pc.message)}")
    elif fx is not None:
        render_route2(L, r, pc, fx)
    else:
        render_route1(L, r, pc)
    L.append("")

    # ------------------------------------------------------------------ 14. チェックリスト
    L.append("## 14. J-STAGE に登載する前に")
    L.append("")
    L.append(f"- [{'x' if r.has_pdf else ' '}] PDF（{m.article_id(j)}.pdf）を記事フォルダに入れる（J-STAGE では PDF が必須）")
    L.append("- [ ] 2 章（AI による補完）と 3 章（未解決）を PDF と照らして確認する")
    if fx is not None:
        L.append(f"- [ ] **PDF に合わせて直した docx（{esc(fx.path.name)}）を Word で開き、変更履歴を確認する**"
                 "（却下したい変更があれば、却下して保存した docx を「docx から作る」で変換し直す）")
        if fx.skipped:
            L.append(f"- [ ] 13 章の、PDF に合わせて直せなかった箇所（{len(fx.skipped)} 件）を確認する")
    elif pc is not None and pc.ok and (pc.diffs or pc.width_count):
        L.append(f"- [ ] **13 章の、出版版 PDF との違い**（文字の違い {len(pc.diffs)} 件・全角・半角の違い {pc.width_count} 文字）を"
                 "確認する（docx が最終版でなければ、docx を直すか「出版版 PDF に合わせてから作る」で変換し直す）")
    if ignored_lines(r):
        L.append(f"- [ ] 13 章の最後の「照合に使わなかった PDF の文字」（{len(ignored_lines(r))} 件）に、docx にない本文"
                 "（校正で足された一文など）が混じっていないか確かめる（表・図の中の文字や、docx のほかの段落にすでにある文字なら"
                 "対応は要らない。本文が足りなければ docx を手で直して変換し直す）")
    if r.forced_floats:
        L.append("- [ ] 本文の冒頭に仮に置いた図表（3 章の「図表の位置」）を、XML の中で手作業で正しい位置に移す")
    if need:
        L.append(f"- [ ] **画像ファイルを用意できなかった図 {len(need)} 件**の画像を作り、ZIP の中の `{graphics_dir(r)}` に入れる: "
                 + "、".join(f"`{name}`（{esc(cap, 20) or 'キャプションなし'}）" for name, cap, _ in need))
    elif r.images and not lost:
        L.append(f"- [x] 画像 {len(r.images)} 件はすべて Graphics/ に入っている（9 章）")
    if lost:
        L.append(f"- [ ] **XML に入らなかった画像 {len(lost)} 件**（9 章）が本文に必要か確かめ、必要なら Word でその画像を本文の段落に"
                 "移して変換し直す: " + "、".join(esc(lost_image_label(li)) for li in lost))
    for kind, prow in provisional:
        title, _, todo = PROVISIONAL[kind]
        L.append(f"- [ ] **{title.format(n=len(prow))}**（6 章。XML に出力していない）: {todo}")
    L.append("- [ ] 11 章の書誌情報（巻・号・頁・日付・DOI）を確認する")
    L.append(f"- [ ] J-STAGE 編集登載システムで、巻（{esc(m.volume or '?')}）・号（{esc(m.issue or '?')}）と、その号のセクション"
             "（目次の見出し。例: 論文）を作成しておく（ないとアップロード時に EMSGM181E「巻号が学会誌別巻号の設定に存在しません」・"
             "EMSGM182E「学会誌別セクションが存在しません」になる）")
    L.append("- [ ] J-STAGE 編集登載システムにアップロードし、記事を正しいセクションに振り分け（記事移動）、"
             "プレビューで本文・図表・引用文献リンクを確認する")
    L.append("")
    return "\n".join(L)


# 直せない違い（why のあるもの）の PDF の文字に添える文（レポートの表と Colab の枠）
WHY_MARKS = {HEAD_WHY: f"（PDF の側は照合に使わなかった文字だけ。13 章の最後の一覧。{LINE_MARK} は PDF の行の変わり目）",
             LONG_WHY: f"（PDF にだけある 20 文字以上の文字。図や表の中の文字かもしれない。{LINE_MARK} は PDF の行の変わり目）",
             EDGE_WHY: f"（段落の最初・最後の、どこまでが段落の文字か決められない PDF の文字。{LINE_MARK} は PDF の行の変わり目）",
             UNSURE_WHY: f"（PDF のこの位置には、どの段落とも一致しない文字が続く。{LINE_MARK} は PDF の行の変わり目）",
             WHOLE_WHY: f"（段落の途中の、どの段落とも一致しない行まるごと。図や表の中の文字かもしれない。{LINE_MARK} は PDF の"
                        "行の変わり目）",
             DISPLACED_WHY: f"（分断された段落の、図や表の中の文字に挟まれた部分か、キャプションのすぐ隣の部分。{LINE_MARK} は"
                            " PDF の行の変わり目）",
             FAR_WHY: f"（分断された段落の、本体から離れた最初・最後の部分。{LINE_MARK} は PDF の行の変わり目）",
             MATH_WHY: f"（PDF の文字の {FORMULA_MARK} は、PDF で数式など文字として読み取れない部分。{LINE_MARK} は PDF の"
                       "行の変わり目）"}
WHY_MARK = WHY_MARKS[HEAD_WHY]
PDF_COLUMN = f"PDF（{LINE_MARK} は行の変わり目）"     # 直せない違いのある表の、PDF の列の見出し


def why_mark(why) -> str:
    """直せない違いの理由 why に添える文（why がなければ空）。"""
    return WHY_MARKS.get(why, "（直せない違い）") if why else ""


def _diff_table(L, plan, diffs):
    """文字の違いの表。直せない理由のある違い（PDF の側に照合に使わなかった文字しかないもの、PDF にだけある長い文字）は、
    PDF の文字を長めに出し（行の変わり目は LINE_MARK）、その旨を添える。表に FORMULA_MARK があれば、表の前に説明を添える。"""
    _formula_note(L, [x for d in diffs for x in (d.docx, d.pdf, d.context)])
    L.append(table(["段落", "場所", "docx", PDF_COLUMN if any(d.why for d in diffs) else "PDF", "docx の前後（［］が違う部分）"],
                   [(d.src, plan.locations.get(d.src, ""), esc(d.docx, 40),
                     esc(d.pdf, 80) + why_mark(d.why) if d.why else esc(d.pdf, 40), esc(d.context, 60))
                    for d in diffs]))


def _unmatched_table(L, srcs, text_of, loc_of):
    L.append("PDF の中で対応する箇所を見つけられなかった段落です（PDF にない段落か、大きく書き換えられた段落の可能性があります）。"
             "これらの段落は照合していません。")
    L.append("")
    L.append(table(["段落", "場所", "文字"], [(s, loc_of(s), esc(text_of(s), 50)) for s in srcs]))


def render_route1(L, r, pc):
    plan = r.plan
    L.append("docx の段落の文字を、記事の PDF（著者校正を経た最終版）の文字と段落ごとに照合しました"
             f"（照合した段落 {pc.checked} 件。表のセル・別行の数式・資料と、4 文字未満の段落は除く）。"
             "**XML は docx の文字のままで、照合の結果を載せているだけです。** PDF に合わせるときは、"
             "「出版版 PDF に合わせてから作る」で変換し直すか、docx を直して変換し直してください。")
    L.append("")
    L.append("### 13.1 文字の違い（要確認）")
    L.append("")
    L.append("PDF と違う箇所です。docx が最終版でない（校正の直しが反映されていない、組版で直された）可能性があります。"
             "大文字・小文字の違いや、引用符（' と ’）の違いも載せています。図の中の文字と思われる PDF の文字は除いています。")
    L.append("")
    if pc.diffs:
        _diff_table(L, plan, pc.diffs)
    else:
        L.append("ありません。")
    L.append("")
    L.append("### 13.2 英数字・記号の全角・半角の違い")
    L.append("")
    if pc.width_count:
        cnt = Counter(f"{plan.paras[s].plain()[q]}→{c}" for s, m in pc.width.items() for q, c in m.items())
        L.append("docx と PDF の違いが英数字・記号の全角・半角だけの文字です（「→」の右が PDF）。その文字のすぐ前後の空白で PDF に"
                 "ないものも含めています。")
        L.append("")
        L.append("内訳: " + "、".join(f"「{k}」{n} 件" for k, n in cnt.most_common())
                 + (f"。PDF にない空白 {pc.drop_count} 文字" if pc.drop_count else ""))
        L.append("")
        L.append(table(["段落", "場所", "文字数", "docx → PDF"], width_rows(r)))
    else:
        L.append("ありません。")
    if pc.numbers:
        L.append("")
        L.append("Word が付ける番号（自動段落番号・脚注番号）の全角・半角の違い（XML は Word の表示・設定の形のまま）:")
        L.append("")
        L.append(table(["番号", "場所", "XML → PDF"], number_rows(r)))
    L.append("")
    L.append("### 13.3 PDF の中に見つからなかった段落")
    L.append("")
    if pc.unmatched:
        _unmatched_table(L, pc.unmatched, lambda s: plan.paras[s].plain(), lambda s: plan.locations.get(s, ""))
    else:
        L.append("ありません。")
    L.append("")
    _ignored_section(L, r, 4, lambda s: plan.locations.get(s, ""))


def render_route2(L, r, pc, fx):
    plan = r.plan
    L.append(f"「出版版 PDF に合わせてから作る」で変換しました。元の docx（{esc(r.docx_name)}）の段落の文字を、記事の PDF"
             "（著者校正を経た最終版）と段落ごとに照合し、違う文字を PDF に合わせて直した docx"
             f"（{esc(fx.path.name)}。Word の変更履歴つき）を作り、それを変換しています。XML は直した docx の文字と"
             " 1 文字も違いません（文字の不変性チェック）。表のセル・別行の数式・図の中の文字・資料と、4 文字未満の段落は照合せず、"
             "docx のままです。")
    L.append("")
    L.append("### 13.1 PDF に合わせて直した箇所（変更履歴）")
    L.append("")
    if fx.applied:
        cnt = Counter({"width": "英数字・記号の全角・半角", "space": "その前後の PDF にない空白の削除",
                       "text": "文字の違い"}[f.kind] for f in fx.applied)
        L.append("内訳: " + "、".join(f"{k} {n} 箇所" for k, n in cnt.items()) + "。PDF の空白は信頼できないので、"
                 "空白だけの違いは直していません。")
        L.append("")
        L.append(table(["段落", "場所", "箇所数", "変更前 → 変更後"], fix_rows(fx)))
    else:
        L.append("ありません。")
    L.append("")
    L.append("### 13.2 PDF と違うが直さなかった箇所（要確認）")
    L.append("")
    if fx.skipped:
        # PDF の側に照合に使わなかった文字しかない箇所と、PDF にだけある長い文字は、PDF のその位置の本文の行が見えるように、
        # PDF の文字を長めに出す（行の変わり目は LINE_MARK）。docx の側に文字がない箇所（PDF にだけある文字）は、docx の欄に
        # 足す位置の前後の文字を出す（同じ段落の同じ PDF の文字の行を見分けられるように）
        long = any(f.reason in WHY_MARKS for f in fx.skipped)
        if any(f.start == f.end for f in fx.skipped):
            L.append(f"docx の欄の「{INSERT_AT}」は、docx に文字がなく PDF にだけ文字がある位置です（前後は docx の文字）。")
            L.append("")
        if any(f.start != f.end and f.reason in CONTEXT_WHYS for f in fx.skipped):
            L.append("docx の欄の「［…］」で囲んだ文字は、docx の違う部分です（前後は docx の文字）。分断された段落の部分の違いは、"
                     "隣の文字との偶然の一致で短く区切られることがあるので、表のとおりに置き換えず、PDF の本文と見比べてください。")
            L.append("")
        rows = [(f.src, fx.locations.get(f.src, ""), _skipped_docx(f, fx.texts.get(f.src, "")),
                 esc(f.new, 80 if f.reason in WHY_MARKS else 30), f.reason) for f in fx.skipped]
        _formula_note(L, [x for row in rows for x in row[2:4]])
        L.append(table(["段落", "場所", "docx", PDF_COLUMN if long else "PDF", "直さなかった理由"], rows))
    else:
        L.append("ありません。")
    L.append("")
    L.append("### 13.3 Word が付ける番号")
    L.append("")
    if pc.numbers:
        L.append("Word が付ける番号（自動段落番号・脚注番号）は docx の文字ではないので、変換のときに全角・半角を PDF に合わせました。")
        L.append("")
        L.append(table(["番号", "場所", "変更前 → 変更後"], number_rows(r)))
    else:
        L.append("PDF と全角・半角が違う番号（自動段落番号・脚注番号）はありません。")
    L.append("")
    L.append("### 13.4 直した docx と PDF の照合（残っている違い）")
    L.append("")
    if pc.diffs or pc.width_count:
        L.append("直した docx をもう一度 PDF と照合して、まだ残っている違いです（13.2 の直さなかった箇所など）。")
        L.append("")
        if pc.diffs:
            _diff_table(L, plan, pc.diffs)
        if pc.width_count:
            L.append("")
            L.append(table(["段落", "場所", "文字数", "docx → PDF"], width_rows(r)))
    else:
        L.append("ありません（照合した段落は、PDF と同じ文字になりました）。")
    L.append("")
    L.append("### 13.5 PDF の中に見つからなかった段落")
    L.append("")
    if fx.unmatched:
        _unmatched_table(L, fx.unmatched, lambda s: fx.texts.get(s, ""), lambda s: fx.locations.get(s, ""))
    else:
        L.append("ありません。")
    L.append("")
    _ignored_section(L, r, 6, lambda s: fx.locations.get(s, ""))


def render_ai_only(r) -> str:
    """AI による判断だけをまとめた別ファイル（不確実性のある箇所の一覧）。"""
    ai = r.ai
    L = [f"# AI による補完の判断一覧: {r.docx_name}", "",
         "AI（生成 AI）が判断した箇所の一覧です。AI は本文の文字を変更していません（リンク・段落の役割・姓名の区切り・"
         "数式画像への MathML の併記、テキストボックス・グループ図形に入った図表の位置と組み合わせのみ）。"
         "確度の低いものから順に並べています。PDF と照らして確認してください。", ""]
    acc = [d for _, d in ai.accepted]
    if ai.error:
        L.append(f"AI による補完は行えませんでした: {ai.error}")
    elif not acc and not ai.rejected:
        L.append("AI の判断はありません。")
    order = {"低": 0, "中": 1, "高": 2}
    for d in sorted(acc, key=lambda d: (order.get(d.confidence, 3), d.did)):
        L.append(f"- **{d.did}（確度 {d.confidence}）** {d.location or r.plan.locations.get(d.src, d.src)}: {esc(d.message)}")
    if ai.rejected:
        L += ["", "## 検証で採用しなかった提案", ""]
        for op, why in ai.rejected:
            L.append(f"- {op.get('op')} [{op.get('src')}] 「{esc(op.get('text') or op.get('role') or op.get('image'))}」: {why}")
    if ai.notes:
        L += ["", "## AI からの気づき", ""]
        L += [f"- {esc(n)}" for n in ai.notes]
    return "\n".join(L) + "\n"
