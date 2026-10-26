"""変換レポート（Markdown）。

冒頭に結果の要約、続いて AI による補完（不確実性のある箇所）、機械処理で解決できなかった箇所、
機械的な推定、出力しなかった文字の全件、落とした空白の全件、生成文字、画像、書誌情報、DTD 検証と J-STAGE の登載時チェック、
出版版 PDF との照合、登載前のチェックリストの順に並べる。

利用者に知らせること（要対応・要確認）は actions() の 1 か所で決める。レポートの冒頭・14 章、Colab の赤い枠
（colab.result_boxes）、コマンドラインの標準エラーと終了コード（pipeline.Result.needs_action）は、どれもその結果を使う。
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .ai_assist import PROVIDERS
from .linker import body_paragraphs, linked_ids
from .model import note_key, note_label
from .package import article_dir
from .pdfmatch import (DISPLACED_WHY, EDGE_WHY, FORMULA_MARK, HEAD_WHY, LINE_MARK, LONG_WHY, MATH_WHY, RE_PAGE_NO, UNSURE_WHY,
                       WHOLE_WHY)
from .structure import NO_LINK_KINDS, TEXTBOX_TEXT_EXCLUDED


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
UNRES_JA = {"bibr": "引用文献", "fig": "図の参照", "table": "表の参照", "fn": "注の参照", "float": "図表の位置",
            "figbody": "図の本体"}


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


def float_places(plan) -> str:
    """位置を決められなかった図表を仮に置いた位置の要約（1 章）。例: アンカー段落の後ろ / アンカー段落の後ろ 2 件・本文の最後 1 件。"""
    n = {"anchor": 0, "end": 0}
    for fid in plan.unplaced_floats:
        n["end" if plan.floats[fid].where == "end" else "anchor"] += 1
    if n["anchor"] and n["end"]:
        return f"アンカー段落の後ろ {n['anchor']} 件・本文の最後 {n['end']} 件"
    return "本文の最後" if n["end"] else "アンカー段落の後ろ"


# 図の本体（画像・表）が見つからない図（structure.Classifier.table_for_figure）の対処。レポートの冒頭、Colab の枠、CLI で使う
# （図ごとの対処は 3 章。figure_body_detail）
FIGURE_BODY_ACTION = ("XML では、キャプションだけの図になっています。docx でこの図の本体（画像・表）を確かめてください。"
                      "近くの表が図の本体なら、表を図キャプションのすぐ上（図キャプションを図の上に置く原稿では、すぐ下）に、"
                      "間にほかの段落を挟まずに置いてから、変換し直してください。その表に表キャプションが付いているときは、"
                      "表キャプションと図キャプションのどちらが正しいかを著者に確かめてください。図の本体が画像なら、"
                      "Word でその画像が図キャプションのすぐ隣にあるかを確かめてください（3 章に図ごとの対処があります）。")


def figure_body_detail(why: str) -> str:
    """図の本体が見つからない図の、3 章の理由の欄（理由 why ごとの対処。structure.Classifier.table_for_figure の理由）。

    近くの表に表キャプションが付いている（理由に「表キャプション」がある）ときは、その表は表として出しているので、表を動かす
    のではなく、図の本体（画像）があるか、表キャプションと図キャプションのどちらが正しいかを確かめる。そのほか（間にほかの段落が
    ある・逆の向きにある）は、表を図キャプションの隣に置き直す。
    """
    head = (f"図キャプションに対応する画像が見つからず、近くの表も図の本体にできなかった（{why}）。"
            "XML ではキャプションだけの図になる。")
    if "表キャプション" in why:
        return head + ("近くの表は、表キャプションの表として出している。その表が表として正しいなら、docx でこの図の本体（画像）を"
                       "確かめ、Word でその画像が図キャプションのすぐ隣にあるかを確かめること（画像がなければ用意する）。その表が"
                       "この図の本体なら、表キャプションと図キャプションのどちらが正しいかを著者に確かめてから docx を直し、"
                       "変換し直すこと")
    return head + ("docx でこの図の本体（画像・表）を確かめ、表が図の本体なら、表を図キャプションのすぐ上（図キャプションを"
                   "図の上に置く原稿では、すぐ下）に、間にほかの段落を挟まずに置いてから、変換し直すこと。図の本体が画像なら、"
                   "Word でその画像が図キャプションのすぐ隣にあるかを確かめること")


def figure_issue_labels(plan) -> list:
    """図の本体が見つからない図の一覧（例: 「図2　間に段落がある問題」（理由））。レポートの冒頭、Colab の枠、CLI で使う。"""
    out = []
    for src, why in plan.figure_issues:
        p = plan.paras.get(src)
        out.append(f"「{esc(p.plain().strip(), 20) if p is not None else src}」（{esc(why)}）")
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
    """XML に出力しなかった、文字だけのテキストボックスの段落（要確認）。

    今の版では XML に出力できないので、レポートの 6 章に載るだけだと見落とされる。出力できるようになるまで（修正計画の F）、
    レポートの冒頭と 14 章で件数と対処を知らせる（暫定の知らせ。Word の文末脚注は 0.24.0 で注として出力するようにした）。
    戻り値: [(種類 "textbox", [(段落, 文字)])]。該当がなければ、その種類は入らない。
    """
    out = []
    for kind, reason in (("textbox", TEXTBOX_TEXT_EXCLUDED),):
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


def article_folder(r) -> str:
    """ZIP の中の記事フォルダ（例: jasme/25/1/25_77/）。"""
    return article_dir(Path(""), r.journal, r.meta).as_posix() + "/"


def graphics_dir(r) -> str:
    """ZIP の中の Graphics フォルダ（例: jasme/25/1/25_77/Graphics/）。"""
    return article_folder(r) + "Graphics/"


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
        L.append("PDF を ZIP に入れるときは、Colab では手順 2 で記事の PDF を選び、コマンドラインでは --pdf で PDF を指定して、"
                 "変換し直してください。")
    if any(n.startswith("Graphics/") for n in names):
        L.append("画像は、用意が必要な画像（9 章で要対応）なら、Colab では手順 7、コマンドラインでは --images で入れ直してください"
                 "（それ以外の画像は、前の変換の残りなので、対応は要りません）。")
    if any(n != f"{aid}.pdf" and not n.startswith("Graphics/") for n in names):
        L.append("ほかのファイルは J-STAGE にアップロードしないので、対応は要りません。")
    return "".join(L)


def pdf_checklist_line(r) -> str:
    """14 章のチェックリストの PDF の行。PDF は J-STAGE で必須で、ZIP に入れるのは変換のときに指定した PDF だけ。"""
    pdf = f"{r.meta.article_id(r.journal)}.pdf"
    if r.has_pdf:
        return f"- [x] PDF（{pdf}）がアップロード用の ZIP に入っている（J-STAGE では PDF が必須）"
    return (f"- [ ] **PDF（{pdf}）がアップロード用の ZIP に入っていない**（J-STAGE では PDF が必須）: Colab では手順 2 で記事の PDF を"
            "選び、コマンドラインでは --pdf で PDF を指定して、変換し直す")


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
                     + ("（半分以上の段落が見つからない。別の記事の PDF ではないか確認）" if pdf_suspect(r) else ""))
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
    文字。f.start == f.end）は、docx の段落の文字 text の、その位置の前後 n 文字（「…確率［］が…」）。"""
    if f.start != f.end or not text:
        return esc(f.old.replace(chr(0xFFFC), "〓"), 30)
    q = f.start
    return _clean(("…" if q > n else "") + text[max(0, q - n):q] + INSERT_AT + text[q:q + n]
                  + ("…" if q + n < len(text) else ""))


def number_rows(r) -> list:
    pc = r.pdf_check
    rows = []
    for (kind, ident), chg in pc.numbers.items():
        old = pc.original[(kind, ident)]
        new = "".join(chg.get(i, c) for i, c in enumerate(old))
        where = r.plan.locations.get(ident, ident) if kind == "auto" else note_label(ident)
        rows.append((NUMBER_KINDS[kind], where, f"「{esc(old.strip())}」→「{esc(new.strip())}」"))
    return rows


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


# ---------------------------------------------------------------------------- 要対応・要確認の知らせ（1 か所にまとめる）
# 利用者に知らせることは、ここ（actions）に Action を 1 つ足す。レポートの冒頭・14 章、Colab の赤い枠（colab.result_boxes）と
# 手順 8 の止め方、コマンドラインの標準エラーと終了コードは、どれも actions の結果だけで決まる（個別の表示を足さない）。
NEEDS_ACTION = "要対応"     # コマンドラインの終了コード 1、Colab の手順 8 で一度止める、赤い枠、レポートの冒頭・14 章
TO_CHECK = "要確認"         # 赤い枠、レポートの冒頭・14 章だけ（終了コードは 0）


@dataclass
class Action:
    """利用者に知らせる 1 件（要対応か要確認）。文面の欄が空なら、そこには出さない。

    top: レポートの冒頭の囲み（Markdown。複数行でもよい）。checklist: 14 章の行。box_title・box_detail: Colab の赤い枠の
    見出しと本文。cli: コマンドラインの標準エラーに出す文（Colab の手順の番号ではなく、コマンドラインの指定で書く）。
    """
    level: str
    key: str
    top: str = ""
    checklist: str = ""
    box_title: str = ""
    box_detail: str = ""
    cli: str = ""


def _fidelity_action(r):
    fid = r.fidelity
    if fid.ok and fid.final_ok:
        return None
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


DTD_SHOWN = 5       # 赤い枠とコマンドラインに並べる DTD のエラーの数（全件はレポートの 12 章）


def _dtd_action(r):
    if r.dtd_valid:
        return None
    n = len(r.dtd_errors)
    errs = list(r.dtd_errors[:DTD_SHOWN]) + ([f"…ほか {n - DTD_SHOWN} 件"] if n > DTD_SHOWN else [])
    return Action(
        NEEDS_ACTION, "dtd",
        top=(f"> **要対応: J-STAGE 指定の DTD による検証が不合格です（{n} 件、12 章）。** この XML は J-STAGE にアップロード"
             "できません。12 章のエラーを確認してください（変換ツールの不具合の可能性があります）。"),
        checklist=(f"- [ ] **DTD 検証が不合格**（12 章、{n} 件）: この XML は J-STAGE にアップロードできない。12 章のエラーを"
                   "確かめる（変換ツールの不具合の可能性がある）"),
        box_title=f"J-STAGE 指定の DTD による検証が不合格です（{n} 件。要対応）",
        box_detail=("この XML は J-STAGE にアップロードできません。変換ツールの不具合の可能性があります。レポートの 12 章の"
                    "エラーを確認し、変換レポートを添えて開発者に知らせてください。\n" + "\n".join(f"・{e}" for e in errs)),
        cli=(f"要対応: J-STAGE 指定の DTD による検証が不合格です（{n} 件。レポートの冒頭と 12 章）。この XML は J-STAGE に"
             "アップロードできない（変換ツールの不具合の可能性がある）。\n" + "\n".join(f"  {e}" for e in errs)))


def _upload_action(r):
    issues = upload_issues(r)
    if not issues:
        return None
    n = len(issues)
    ids = "、".join(dict.fromkeys(mid for mid, _ in issues))
    return Action(
        NEEDS_ACTION, "upload",
        top=(f"> **要対応: J-STAGE のアップロード時チェックで問題が {n} 件見つかりました（12 章）。** このままでは、J-STAGE に"
             "アップロードするときに弾かれます。12 章の内容を見て、書誌情報（巻・号・ページ・日付など）か docx を直し、"
             "変換し直してください。\n>\n" + "\n".join(f"> - {esc(mid)}: {esc(msg)}" for mid, msg in issues)),
        checklist=(f"- [ ] **J-STAGE のアップロード時チェックの問題 {n} 件**（12 章）を、書誌情報か docx を直して変換し直す: "
                   + esc(ids)),
        box_title=f"J-STAGE のアップロード時チェックで問題が {n} 件あります（要対応）",
        box_detail=("このままでは、J-STAGE にアップロードするときに弾かれます。書誌情報（巻・号・ページ・日付など）が原因なら"
                    "手順 3 から、docx が原因なら docx を直して手順 2 から、やり直してください（レポートの 12 章）。\n"
                    + "\n".join(f"・{mid}: {msg}" for mid, msg in issues)),
        cli=(f"要対応: J-STAGE のアップロード時チェックで問題が {n} 件あります（レポートの冒頭と 12 章）。このままでは"
             "アップロードのときに弾かれるので、書誌情報（--meta）か docx を直して変換し直すこと。\n"
             + "\n".join(f"  {mid}: {msg}" for mid, msg in issues)))


# AI の回答を反映できなかったときの見出し（手動モードは貼り付けた回答、API モードは API の呼び出しか回答）
AI_ERROR_TITLE = {"manual": "貼り付けた回答を読み込めませんでした（AI による補完は反映されていません）",
                  "api": "AI による補完ができませんでした"}


def _ai_error_action(r):
    ai = r.ai
    if ai.mode == "none" or not ai.error:
        return None
    manual = ai.mode == "manual"
    title = AI_ERROR_TITLE["manual" if manual else "api"]
    todo = ("回答のコードブロックの中身だけを貼り付け直して、変換し直す" if manual
            else "2 章の理由を確かめて、もう一度変換する（また失敗するときは「手動（チャットに貼り付け）」に切り替える）")
    return Action(
        NEEDS_ACTION, "ai_error",
        top=(f"> **要対応: {'貼り付けた回答を読み込めませんでした（AI による補完は反映されていません。2 章）' if manual else 'AI による補完ができませんでした（2 章）'}。** "
             f"{esc(ai.error)}"),
        checklist=f"- [ ] **{'貼り付けた AI の回答を読み込めなかった' if manual else 'AI による補完ができなかった'}**（2 章）: {todo}",
        box_title=title, box_detail=ai.error,
        cli=f"要対応: {title}。{ai.error}")


def ai_pending(r) -> bool:
    """手動モードで、AI の回答をまだ貼り戻していない（この出力は AI による補完の前の状態。決定事項 5(c)）。"""
    return r.ai.mode == "manual" and not r.ai.raw and not r.ai.error


def _ai_pending_action(r):
    if not ai_pending(r):
        return None
    floats = ("位置を決められない図表は、AI の回答を反映するまで仮の位置に置いています（3 章）。" if r.plan.unplaced_floats
              else "")
    prompt = r.prompt_path.name if r.prompt_path else "AI依頼文.txt"
    # 冒頭には、変換のときに書いた手動モードの説明（Result.output_note）が出るので、ここでは冒頭に出さない
    return Action(
        NEEDS_ACTION, "ai_pending",
        checklist=(f"- [ ] **AI の回答をまだ反映していない**（手動モード）: {esc(prompt)} を AI に渡し、返ってきた回答を貼り戻して"
                   "変換し直す（Colab では手順 6、コマンドラインでは --ai-response）"),
        box_title="AI の回答をまだ反映していません（手動モード）",
        box_detail=("この結果は、AI による補完の前の状態です。手順 5 の依頼文を AI（claude.ai などのチャット）に渡し、"
                    "返ってきた回答を手順 6 に貼り付けて ▶ を押してください。" + floats),
        cli=(f"要対応: 手動モードで、AI の回答をまだ反映していません（この出力は AI による補完の前の状態）。{prompt} を"
             "チャット（claude.ai など）に貼り付け、返ってきた回答をファイルに保存して --ai-response で指定し、変換し直すこと。"
             + floats))


PARTIAL_TITLE = "AI の回答が途中で切れていました（図表の位置の一部だけを反映しました）"


def _partial_action(r):
    if not r.ai.partial:
        return None
    return Action(
        NEEDS_ACTION, "partial",
        top=f"> **要対応: AI の回答が途中で切れていました（2 章）。** {esc(r.ai.partial)}",
        checklist="- [ ] **AI の回答が途中で切れていた**（2 章）: AI に出し直してもらい、もう一度変換する",
        box_title=PARTIAL_TITLE, box_detail=r.ai.partial,
        cli=f"要対応: AI の回答が途中で切れていました。{r.ai.partial}")


def unplaced_text(plan, partial="") -> tuple:
    """AI の回答を反映した後も、位置を決められない図表が残っているときの赤い枠の (見出し, 本文)。なければ None。

    図表ごとに、キャプション、XML の中の図表の ID（と、図形の中身から出した本文の段落など。structure.float_targets）、
    仮に置いた位置（structure.ArticlePlan.float_place。アンカー段落の後ろか本文の最後）を示す。partial（AIOutcome.partial。
    AI の回答が途中で切れていた）があれば、出し直しの頼み方は、途中で切れた回答の枠（PARTIAL_MSG）と同じものを示す
    （別の頼み方を並べない）。
    """
    from .structure import float_caption, float_targets
    if not plan.unplaced_floats:
        return None
    why = {"ai": "（AI が注などの本文の外の段落の後ろを指定したため）",
           "anchor": "（図が結び付いている段落が本文の段落でないため）"}
    rows = []
    for fid in plan.unplaced_floats:
        info = plan.floats[fid]
        ids = float_targets(plan, info)
        xml = f"、XML の{' ' if ids[:1].isascii() else ''}{ids}" if ids else ""
        rows.append(f"・{fid}（{float_caption(info)}{xml}）: {plan.float_place(fid)}"
                    f"{why.get(info.end_why, '')}")
    if partial:
        intro = ("AI の回答が途中で切れていて、次の図表の位置（placements）の指定を読み取れなかったか、指定が検証で採用されません"
                 "でした（レポートの 2 章・3 章）。")
        again = ("AI に出し直してもらう方法は、上の「AI の回答が途中で切れていました」の枠のとおりです（最初から出し直してもらうと、"
                 "これらの図表の位置も反映されます）。")
    else:
        intro = "AI の回答に、次の図表の位置（placements）の指定がないか、指定が検証で採用されませんでした（レポートの 2 章・3 章）。"
        again = ("AI に出し直してもらう場合は、手動モードではチャットで「位置を決められなかった図表をすべて placements に書いて、"
                 "回答の書き方に従って出し直してください」と頼んで手順 6 で貼り付け直し、API モードでは手順 5 をもう一度実行してください。")
    return ("位置を決められなかった図表があります（仮の位置に置いています。手作業で直してください）",
            intro + "これらは仮の位置に置いているので、登載の前に、XML の中で手作業で正しい位置（Word で表示したときに、図の左上の"
            "直上にある本文の段落の後）に移してください。\n" + "\n".join(rows) + "\n" + again)


def _forced_action(r):
    if not r.forced_floats:
        return None
    title, detail = unplaced_text(r.plan, r.ai.partial)
    return Action(
        NEEDS_ACTION, "forced",
        top=(f"> **要対応: 位置を決められなかった図表が {len(r.forced_floats)} 件あります（AI による補完でも決まりませんでした）。** "
             "図が結び付いている段落（アンカー段落）のすぐ後ろ（箇条書き・引用の途中なら、その終わり）か、本文の最後に仮に"
             "置いています。登載の前に、XML の中でこれらの"
             "図表を手作業で正しい位置（Word で表示したときに、図の左上の直上にある本文の段落の後）に移してください（3 章）: "
             + "、".join(esc(x) for x in r.forced_floats)),
        checklist=("- [ ] 仮の位置（アンカー段落の後ろ・本文の最後）に置いた図表（3 章の「図表の位置」）を、XML の中で手作業で"
                   "正しい位置に移す"),
        box_title=title, box_detail=detail,
        # 図表ごとに、キャプションと、XML の中の位置・ID（レポートの冒頭と同じ。pipeline の forced_floats）
        cli=(f"要対応: 位置を決められなかった図表 {len(r.forced_floats)} 件を、仮の位置（アンカー段落の後ろ、または"
             "本文の最後）に置きました。XML の中で手作業で正しい位置（Word で表示したときに、図の左上の直上にある本文の段落の後）"
             "に移してください（レポートの冒頭と 3 章）。\n" + "\n".join(f"  {x}" for x in r.forced_floats)))


def figure_body_action(r):
    """図の本体（画像・表）が見つからない図（structure.Classifier.table_for_figure）。なければ None。"""
    plan = r.plan
    if not plan.figure_issues:
        return None
    labels = figure_issue_labels(plan)
    n = len(plan.figure_issues)
    return Action(
        NEEDS_ACTION, "figbody",
        top=(f"> **要対応: 図の本体（画像・表）が見つからない図が {n} 件あります（3 章）。** "
             f"{FIGURE_BODY_ACTION}対象の図: " + "、".join(labels)),
        checklist=(f"- [ ] 図の本体が見つからない図 {n} 件（3 章の「図の本体」）を docx で確かめ、表が図の本体なら "
                   "docx を直して変換し直す"),
        box_title=f"図の本体（画像・表）が見つからない図が {len(labels)} 件あります（要対応）",
        box_detail=f"{FIGURE_BODY_ACTION}（レポートの冒頭と 3 章）\n" + "\n".join(f"・{x}" for x in labels),
        cli=(f"要対応: 図の本体（画像・表）が見つからない図 {len(labels)} 件（レポートの冒頭と 3 章）。{FIGURE_BODY_ACTION}\n"
             + "\n".join(f"  {x}" for x in labels)))


def images_action(r):
    """画像ファイルを用意できなかった図（Word の図形で描かれた図など。images_to_prepare）。なければ None。"""
    need = images_to_prepare(r)
    if not need:
        return None
    zname = r.zip_path.name if r.zip_path else "アップロード用の ZIP"
    items = "\n".join(f"・{name}: {cap or '（キャプションなし）'}（{why}）" for name, cap, why in need)
    return Action(
        NEEDS_ACTION, "images",
        top="\n".join([(f"> **要対応: 画像ファイルを用意できなかった図が {len(need)} 件あります（9 章）。** 次の名前の画像（PNG）を"
                        f"作り、{esc(zname)} の中の `{graphics_dir(r)}` に入れてください。画像がないままでは、その図が J-STAGE の"
                        "画面に表示されません。"), ">"]
                      + [f"> - `{name}`: {esc(cap, 40) or '（キャプションなし）'}（{esc(why)}）" for name, cap, why in need]),
        checklist=(f"- [ ] **画像ファイルを用意できなかった図 {len(need)} 件**の画像を作り、ZIP の中の `{graphics_dir(r)}` に入れる: "
                   + "、".join(f"`{name}`（{esc(cap, 20) or 'キャプションなし'}）" for name, cap, _ in need)),
        box_title=f"画像ファイルを用意できなかった図が {len(need)} 件あります",
        box_detail=("Word の図形で描かれた図などは、docx に画像ファイルがないので、変換で画像を作れません。画像がないままでは、"
                    "その図が J-STAGE の画面に表示されません。手順 7「足りない画像をアップロード」で、図ごとにその図の画像を"
                    f"選んでください（ファイル名は何でもかまいません）。手元で入れるときは、次の名前の画像を {zname} の中の "
                    f"{graphics_dir(r)} に入れます（レポートの冒頭と 9 章）。\n{items}"),
        cli=(f"要対応: 画像ファイルを用意できなかった図 {len(need)} 件。画像を作り、同じ名前でフォルダに入れて --images で"
             f"指定するか、ZIP の中の {graphics_dir(r)} に入れること（レポートの冒頭と 9 章）: "
             + ", ".join(f"{name}（{(cap[:20] + '…' if len(cap) > 20 else cap) or 'キャプションなし'}）"
                         for name, cap, _ in need)))


def lost_action(r):
    """docx にあるのに XML に入らなかった画像（pipeline.lost_images）。なければ None。"""
    lost = r.lost_images
    if not lost:
        return None
    return Action(
        NEEDS_ACTION, "lost",
        top="\n".join([(f"> **要対応: XML に入らなかった画像が {len(lost)} 件あります（9 章）。** {LOST_IMAGES_WHY}"
                        f"{LOST_IMAGES_ACTION}"), ">"]
                      + [f"> - {esc(lost_image_label(li))}: {esc(li.reason)}" for li in lost]),
        checklist=(f"- [ ] **XML に入らなかった画像 {len(lost)} 件**（9 章）が本文に必要か確かめ、必要なら Word でその画像を本文の段落に"
                   "移して変換し直す: " + "、".join(esc(lost_image_label(li)) for li in lost)),
        box_title=f"XML に入らなかった画像が {len(lost)} 件あります（要対応）",
        box_detail=(f"{LOST_IMAGES_WHY}{LOST_IMAGES_ACTION}変換し直すときは、Word で直した docx を手順 2 でアップロードし直し、そこから"
                    "順にやり直してください（レポートの冒頭と 9 章）。\n"
                    + "\n".join(f"・{lost_image_label(li)}: {li.reason}" for li in lost)),
        cli=(f"要対応: XML に入らなかった画像 {len(lost)} 件（画像を出力できない引用文献・題目・著者名・所属の段落や、"
             f"出力しなかった段落の中にある。レポートの冒頭と 9 章）。{LOST_IMAGES_ACTION}\n"
             + "\n".join(f"  {lost_image_label(li)}: {li.reason}" for li in lost)))


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
             "かもしれません。資料なら、Word でその段落の前に資料の見出し（「資料1」「資料（授業プリント）」など）を付けて、変換し直して"
             f"ください。対象の段落: {samples}"),
        checklist=f"- [ ] **英文要旨の中の和文の段落**（{n} 件。10 章）: 資料などの和文なら、Word で資料の見出しを付けて変換し直す",
        box_title="英文要旨に和文の段落があります（要確認）",
        box_detail=(f"英文要旨に、かな・漢字が 3 割以上の段落が {n} 件あります。資料・付録などの和文が英文要旨に入っているかもしれません。"
                    "資料なら、Word でその段落の前に資料の見出し（「資料1」など）を付けてから、変換し直してください（レポートの冒頭と"
                    f" 10 章）。\n対象の段落: {samples}"),
        cli=(f"要確認: 英文要旨に和文と思われる段落が {n} 件あります（レポートの冒頭と 10 章）。資料なら、docx に資料の見出しを付けて"
             "変換し直すこと"))


def _app_after_refs_action(r):
    """引用文献・注・付記・謝辞の中の、資料の見出しと思われる段落（structure.Classifier.build_back）。なければ None。

    暫定の判断で、引用文献などの後ろの資料は資料（app-group）にせず、知らせるだけにしている（決定事項 8(b) は利用者に未確認）。
    """
    plan = r.plan
    if not plan.app_after_refs:
        return None
    n = len(plan.app_after_refs)
    samples = _para_samples([(s, plan.paras[s].text_only()) for s in plan.app_after_refs])
    return Action(
        TO_CHECK, "app_after_refs",
        top=("> **要確認: 引用文献などの後ろに、資料の見出しと思われる段落があります（10 章）。** 今の版では、引用文献などの後ろの"
             "資料は資料（付録）として扱わず、引用文献などの段落のまま出力しています。資料なら、Word で英文要旨の後ろ（論文の最後）に"
             f"移して、変換し直してください。対象の段落: {samples}"),
        checklist=(f"- [ ] **引用文献などの後ろの資料の見出し**（{n} 件。10 章）: 資料なら、Word で英文要旨の後ろに移して"
                   "変換し直す"),
        box_title="引用文献などの後ろに資料があるかもしれません（要確認）",
        box_detail=("引用文献・注・付記・謝辞の中に、資料の見出しと思われる段落があります。今の版では資料として扱わず、引用文献などの"
                    "段落のまま出力しています。資料なら、Word でその見出しと中身を英文要旨の後ろ（論文の最後）に移してから、変換し直して"
                    f"ください（レポートの冒頭と 10 章）。\n対象の段落: {samples}"),
        cli=("要確認: 引用文献などの後ろに、資料の見出しと思われる段落があります（レポートの冒頭と 10 章）。資料なら、docx で英文要旨の"
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
             "同じ番号の別の注が並びます（本文からのリンクは、それぞれ正しい注を指します）。Word で、どちらかの書き方（本文に上付きの"
             "「1)」を書いて「注」の節にまとめる、または Word の脚注・文末脚注の機能）にそろえてから、変換し直してください。"),
        checklist=(f"- [ ] **注の番号の重なり**（{marks}。10 章）: 手で書いた注と Word の脚注・文末脚注のどちらかの書き方に"
                   "そろえて変換し直す"),
        box_title="注の番号が重なっています（要確認）",
        box_detail=(f"手で書いた注と Word の脚注・文末脚注が両方あり、注の一覧に同じ番号（{marks}）の別の注が並びます。Word で"
                    "どちらかの書き方にそろえてから、変換し直してください（レポートの冒頭と 10 章）。"),
        cli=(f"要確認: 手で書いた注と Word の脚注・文末脚注が両方あり、注の番号 {marks} が重なっています（レポートの冒頭と 10 章）。"
             "docx でどちらかの書き方にそろえて変換し直すこと"))


def pdf_fallback(r) -> bool:
    """ルート2 で出版版 PDF の文字を読めず、docx を直さずに変換した（pipeline.Result.pdf_fallback と同じ。M4）。"""
    return r.route == "pdf" and r.docx_fix is None and r.pdf_check is not None


def pdf_suspect(r) -> bool:
    """docx の段落の半分以上が PDF に見つからない（別の記事の PDF の疑い。要確認）。"""
    pc, fx = r.pdf_check, r.docx_fix
    if pc is None or not pc.ok:
        return False
    unmatched = fx.unmatched if fx is not None else pc.unmatched
    return len(unmatched) * 2 > pc.checked


def _marks_note(docx_texts, pdf_texts, insert=False) -> str:
    """赤い枠の一覧の前に添える、記号の説明（一覧に「〓」〈と、insert なら「［］」〉があるときだけ。レポートの 13 章の表と同じ
    意味。docx の側と PDF の側で「〓」の意味が違う）。"""
    in_docx = any(FORMULA_MARK in (t or "") for t in docx_texts)
    in_pdf = any(FORMULA_MARK in (t or "") for t in pdf_texts)
    notes = []
    if in_docx or in_pdf:
        parts = ([f"docx の側の「{FORMULA_MARK}」は docx の数式・画像"] if in_docx else []) + \
            ([f"PDF の側の「{FORMULA_MARK}」は PDF で数式など文字として読み取れない部分"] if in_pdf else [])
        notes.append("、".join(parts) + "です。")
    if insert and any(INSERT_AT in (t or "") for t in docx_texts):
        notes.append(f"docx の側の「{INSERT_AT}」は、docx に文字がなく PDF にだけ文字がある位置です（前後は docx の文字）。")
    return "".join(n + "\n" for n in notes)


def _pdf_fallback_action(r):
    pc = r.pdf_check
    if pc is None or pc.ok or not pdf_fallback(r):
        return None
    msg = pc.message
    return Action(
        NEEDS_ACTION, "pdf_fallback",
        top=(f"> **要対応: 出版版 PDF に合わせられませんでした（13 章）。** PDF の文字を読めなかったため（{esc(msg)}）、docx を"
             "直さずに、docx の文字のまま変換しました（「docx から作る」と同じ結果です）。PDF に合わせるときは、文字を読める"
             "出版版 PDF を選んで変換し直すか、docx を手で直して変換し直してください。"),
        checklist=("- [ ] **docx を PDF に合わせていない**（PDF の文字を読めなかった。13 章）: 文字を読める出版版 PDF で変換し直すか、"
                   "docx を手で直して変換し直す（このままなら XML は docx の文字のまま）"),
        box_title="出版版 PDF に合わせられませんでした（要対応）",
        box_detail=(f"PDF の文字を読めなかったため（{msg}）、docx を直さずに、docx の文字のまま変換しました（「docx から作る」と"
                    "同じ結果です。PDF に合わせて直した docx は作っていません）。画像だけの PDF（スキャンした PDF など）では、"
                    "文字を読めません。PDF に合わせるときは、文字を読める出版版 PDF を手順 2 で選び直して変換し直すか、docx を手で"
                    "直して手順 2 からやり直してください（レポートの冒頭と 13 章）。"),
        cli=(f"要対応: 出版版 PDF に合わせられませんでした。PDF の文字を読めなかったため（{msg}）、docx を直さずに変換した"
             "（「docx から作る」と同じ結果。レポートの冒頭と 13 章）。文字を読める出版版 PDF を --pdf で指定して変換し直すか、"
             "docx を手で直して変換し直すこと"))


def _pdf_unread_action(r):
    pc = r.pdf_check
    if pc is None or pc.ok or pdf_fallback(r):
        return None
    msg = pc.message
    return Action(
        TO_CHECK, "pdf_unread",
        top=(f"> **要確認: 出版版 PDF と照合できませんでした（13 章）。** {esc(msg)}。XML は docx の文字のままです。"
             "画像だけの PDF（スキャンした PDF など）では、文字を読めません。PDF がこの記事の出版版 PDF かを確かめてください。"),
        checklist="- [ ] 出版版 PDF と照合できなかった（13 章）: PDF がこの記事の出版版 PDF か（画像だけの PDF でないか）を確かめる",
        box_title="出版版 PDF と照合できませんでした（要確認）",
        box_detail=(f"{msg}。XML は docx の文字のままです（レポートの 13 章）。画像だけの PDF（スキャンした PDF など）では、"
                    "文字を読めません。手順 2 で選んだ PDF が、この記事の出版版 PDF かを確かめてください。"),
        cli=f"要確認: 出版版 PDF と照合できませんでした（{msg}。レポートの 13 章）。XML は docx の文字のまま")


def _pdf_diff_action(r):
    pc, fx = r.pdf_check, r.docx_fix
    if pc is None or not pc.ok or fx is not None or (not pc.diffs and not pc.width_count):
        return None
    items = _marks_note([x for d in pc.diffs[:10] for x in (d.context, d.docx)], [d.pdf for d in pc.diffs[:10]]) + \
        "\n".join(f"・{d.context}（docx「{d.docx}」/ PDF「{d.pdf}」{why_mark(d.why)}）" for d in pc.diffs[:10])
    more = f"\n…ほか {len(pc.diffs) - 10} 件" if len(pc.diffs) > 10 else ""
    width = f"、全角・半角の違いが {pc.width_count} 文字" if pc.width_count else ""
    return Action(
        TO_CHECK, "pdf_diff",
        top=(f"> **要確認: 出版版 PDF と文字が違う箇所が {len(pc.diffs)} 件、全角・半角の違いが {pc.width_count} 文字あります"
             "（13 章）。** 受け取った docx が、著者校正を経た最終版ではない可能性があります。XML は docx の文字のままです。"
             "PDF に合わせるときは、「出版版 PDF に合わせてから作る」で変換し直すか、docx を直して変換し直してください。"),
        checklist=(f"- [ ] **13 章の、出版版 PDF との違い**（文字の違い {len(pc.diffs)} 件・全角・半角の違い {pc.width_count} 文字）を"
                   "確認する（docx が最終版でなければ、docx を直すか「出版版 PDF に合わせてから作る」で変換し直す）"),
        box_title=f"出版版 PDF と文字が違う箇所が {len(pc.diffs)} 件{width}あります（要確認）",
        box_detail=("受け取った docx が、著者校正を経た最終版ではない可能性があります。XML は docx の文字のままです（レポートの 13 章）。"
                    "PDF に合わせるときは、手順 2 で「出版版 PDF に合わせてから作る」を選んで変換し直すか、docx を直して"
                    "手順 2 からやり直してください。" + (f"\n{items}{more}" if items else "")),
        cli=(f"要確認: 出版版 PDF と文字が違う箇所が {len(pc.diffs)} 件{width}あります（レポートの冒頭と 13 章）。XML は docx の"
             "文字のまま。docx が最終版でなければ、docx を直すか --route pdf で変換し直すこと"))


def _pdf_unfixed_action(r):
    pc, fx = r.pdf_check, r.docx_fix
    if pc is None or not pc.ok or fx is None:
        return None
    rest = len(pc.diffs) + pc.width_count
    if not fx.skipped and not rest:
        return None

    def line_note(f):       # 直せない理由のある箇所の PDF の文字は、行の変わり目に LINE_MARK が入る
        return f"。{LINE_MARK} は PDF の行の変わり目" if LINE_MARK in f.new else ""
    # docx の文字はレポートの 13.2 と同じ形（数式・画像は FORMULA_MARK、PDF にだけある文字は INSERT_AT と前後の文字）
    shown = [(f, _skipped_docx(f, fx.texts.get(f.src, ""))) for f in fx.skipped[:10]]
    items = _marks_note([d for _, d in shown], [f.new for f, _ in shown], insert=True) + \
        "\n".join(f"・{f.src}: 「{d}」→「{f.new}」（{f.reason}{line_note(f)}）" for f, d in shown)
    more = f"\n…ほか {len(fx.skipped) - 10} 件" if len(fx.skipped) > 10 else ""
    head = []
    if fx.skipped:
        head.append(f"直せなかった箇所 {len(fx.skipped)} 件")
    if rest:
        head.append(f"直した後も PDF と違う箇所 {rest} 件")
    # 冒頭（固定の「docx を直してから変換しました」の案内）と 14 章（固定の行）には、今までどおり render が出す
    return Action(
        TO_CHECK, "pdf_unfixed",
        box_title="出版版 PDF に合わせきれなかった箇所があります（要確認）: " + "、".join(head),
        box_detail=(f"PDF に合わせて直した docx（{fx.path.name}、変換結果の ZIP に入っています）を Word で開き、レポートの 13 章と"
                    "照らして確認してください。XML は直した docx の文字のままです。" + (f"\n{items}{more}" if items else "")),
        cli=(f"要確認: 出版版 PDF に合わせきれなかった箇所があります: {'、'.join(head)}（レポートの 13 章）。PDF に合わせて"
             f"直した docx（{fx.path.name}）を Word で開き、13 章と照らして確認すること"))


def _pdf_suspect_action(r):
    if not pdf_suspect(r):
        return None
    pc, fx = r.pdf_check, r.docx_fix
    n = len(fx.unmatched if fx is not None else pc.unmatched)
    what = f"docx の段落 {pc.checked} 件のうち {n} 件が、出版版 PDF に見つかりませんでした"
    return Action(
        TO_CHECK, "pdf_suspect",
        top=(f"> **要確認: 別の記事の PDF かもしれません（13 章）。** {what}。PDF がこの記事の出版版 PDF かを"
             "確かめてください。"),
        checklist=("- [ ] **PDF がこの記事のものか**を確かめる（docx の段落の半分以上が PDF に見つからない。13 章）。違っていたら、"
                   "正しい PDF で変換し直す"),
        box_title="別の記事の PDF かもしれません（要確認）",
        box_detail=(f"{what}。手順 2 で選んだ PDF が、この記事の出版版 PDF かを確かめてください。違っていたら、正しい PDF を"
                    "選んで手順 2 からやり直してください（レポートの 13 章）。"),
        cli=f"要確認: 別の記事の PDF かもしれません。{what}（レポートの 13 章）。--pdf の PDF がこの記事のものか確かめること")


IGNORED_SHOWN = 10      # 赤い枠に並べる、照合に使わなかった PDF の文字の段落の数（全件はレポートの 13 章の最後）


def _pdf_ignored_action(r):
    rows = ignored_lines(r)
    if not rows:
        return None
    n = len(rows)
    shown = ignored_rows(rows, lambda s: "")
    items = "\n".join(f"・{s}: {t}" for s, _, _, t in shown[:IGNORED_SHOWN]) + \
        (f"\n…ほか {len(shown) - IGNORED_SHOWN} 段落" if len(shown) > IGNORED_SHOWN else "")
    return Action(
        TO_CHECK, "pdf_ignored",
        top=(f"> **要確認: 照合に使わなかった PDF の文字が {n} 件あります（13 章の最後）。** 組版で入る文字（誌名の行・投稿受付日"
             "など）や、図・表の中の文字とみなしたものです。docx にない本文（校正で足された一文など）が混じっていないか"
             "確かめてください。"),
        checklist=(f"- [ ] 13 章の最後の「照合に使わなかった PDF の文字」（{n} 件）に、docx にない本文"
                   "（校正で足された一文など）が混じっていないか確かめる（表・図の中の文字や、docx のほかの段落にすでにある文字なら"
                   "対応は要らない。本文が足りなければ docx を手で直して変換し直す）"),
        box_title=f"照合に使わなかった PDF の文字が {n} 件あります（要確認）",
        box_detail=("組版で入る文字（誌名の行・投稿受付日など）や、図・表の中の文字とみなして、照合に使わなかった PDF の文字です"
                    f"（{LINE_MARK} は PDF の行の変わり目）。docx にない本文（校正で足された一文など）が混じっていないか、レポートの"
                    " 13 章の最後の一覧で確かめてください。表・図の中の文字や、docx のほかの段落にすでにある文字なら、対応は要りません。"
                    "本文が足りなければ、docx を手で直して手順 2 からやり直してください。\n" + items),
        cli=(f"要確認: 照合に使わなかった PDF の文字 {n} 件（レポートの冒頭と 13 章の最後）。docx にない本文（校正で足された"
             "一文など）が混じっていないか確かめること"))


def _provisional_actions(r) -> list:
    out = []
    for kind, prow in provisional_exclusions(r):
        title, detail, todo = PROVISIONAL[kind]
        what = title.format(n=len(prow))
        out.append(Action(
            TO_CHECK, kind,
            top=f"> **要確認: {what}を、XML に出力していません（6 章）。** {detail}対象の段落: {_para_samples(prow)}",
            checklist=f"- [ ] **{what}**（6 章。XML に出力していない）: {todo}",
            box_title=f"{what}を、XML に出力していません（要確認）",
            box_detail=f"{detail}（レポートの冒頭と 6 章）\n対象の段落: {_para_samples(prow)}",
            cli=f"要確認: {what}を、XML に出力していません（レポートの冒頭と 6 章）。{detail}"))
    return out


def pdf_actions(r) -> list:
    """出版版 PDF との照合の知らせ（actions の一部）。r は pdf_check・docx_fix・route があればよい（Colab の pdf_diff_box）。"""
    makers = (_pdf_fallback_action, _pdf_unread_action, _pdf_diff_action, _pdf_unfixed_action, _pdf_suspect_action,
              _pdf_ignored_action)
    return [a for a in (f(r) for f in makers) if a is not None]


PDF_KEYS = ("pdf_fallback", "pdf_unread", "pdf_diff", "pdf_unfixed", "pdf_suspect", "pdf_ignored")


def actions(r) -> list:
    """利用者に知らせること（要対応・要確認）の一覧。並びはレポートの冒頭の順。

    ルート2 の「出版版 PDF に合わせて docx を直してから変換しました」の案内と、14 章の「Word で開き、変更履歴を確認する」は、
    すべて直せたときにも出すものなので、ここには入れない（render の固定の部分。直せなかった箇所は pdf_unfixed の枠）。
    記事フォルダにあるのに ZIP に入れなかったファイル（Result.not_zipped）は 10 章の警告のまま。
    """
    head = [f(r) for f in (_fidelity_action, _dtd_action, _upload_action, _ai_error_action, _ai_pending_action,
                           _partial_action, _forced_action, figure_body_action, images_action, lost_action,
                           _abstract_ja_action, _app_after_refs_action, _note_overlap_action)]
    return [a for a in head if a is not None] + pdf_actions(r) + _provisional_actions(r)


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
             + ("（PDF の文字を読めなかったので、docx を直さずに変換した）" if pdf_fallback(r) else ""))
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
    which = "Word の脚注・文末脚注" if has_endnotes(plan) else "Word の脚注"
    fn_links = f"{c.get('fn', 0) + wn}" + (f"（うち {which} {wn}）" if wn else "")
    links = (f"引用文献 {c.get('bibr', 0)} / 図 {c.get('fig', 0)} / 表 {c.get('table', 0)} / 注 {fn_links} / "
             f"数式 {c.get('disp-formula', 0)} / URL {c.get('url', 0) + c.get('word', 0)} / DOI {c.get('doi', 0)}")
    ai_acc = [d for _, d in ai.accepted]
    rows = [
        ("本文の文字の不変性チェック（AI 補完の後に実施）", fid_line),
        ("最終出力（目印を取り除いた XML）の再チェック", final_line),
        ("J-STAGE 指定 DTD（JATS 1.1）による検証", "合格" if r.dtd_valid else f"不合格（{len(r.dtd_errors)} 件、12 章）"),
        ("J-STAGE のアップロード時チェック（XML と ZIP で判定できるもの）",
         "問題なし" if not upload_issues(r) else f"要対応 {len(upload_issues(r))} 件（12 章）"),
        ("機械的に付けたリンク", links),
        ("AI が付けたリンク・判断（2 章）", f"採用 {len(ai_acc)} 件 / 不採用 {len(ai.rejected)} 件" if ai.mode != "none" else "AI 補完なし"),
        ("機械処理で解決できなかった箇所（3 章）", f"{len(r.unresolved_after)} 件"),
        ("画像", image_summary(r)),
        ("警告", f"{len(r.warnings)} 件（10 章）"
                 + (f"。ほかに、ZIP に入れなかったファイル {len(r.not_zipped)} 件（10 章）" if r.not_zipped else "")),
        ("出版版 PDF との照合", pdf_summary(r)),
    ]
    if plan.unplaced_floats:
        rows.insert(7, ("位置を決められなかった図表（3 章）", f"{len(plan.unplaced_floats)} 件（{float_places(plan)}に仮に配置）"))
    L.append(table(["項目", "結果"], rows))
    L.append("")
    # 要対応・要確認（actions）。ルート2 の「docx を直してから変換しました」の案内は、PDF の知らせの前に固定で出す
    acts = actions(r)
    late = [a for a in acts if a.key in PDF_KEYS or a.key in PROVISIONAL]
    for a in [a for a in acts if a not in late]:
        if a.top:
            L.append(a.top)
            L.append("")
    pc, fx = r.pdf_check, r.docx_fix
    if fx is not None:
        L.append(f"> **出版版 PDF に合わせて docx を直してから変換しました（13 章）。** 直した docx（{esc(fx.path.name)}）は "
                 "Word の変更履歴つきです。Word で開いて変更を確認し、却下したい変更があれば、却下して保存した docx を"
                 "「docx から作る」で変換し直してください。"
                 + (f"**直せなかった箇所が {len(fx.skipped)} 件あります。**" if fx.skipped else ""))
        L.append("")
    for a in late:
        if a.top:
            L.append(a.top)
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
        if ai.partial:
            L.append(f"**AI の回答が途中で切れていました。** {esc(ai.partial)}")
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
    if has_endnotes(plan):
        word_marks = ("（Word の脚注・文末脚注機能で書かれた注の番号だけは、Word の表示〈脚注は「1」、文末脚注は「i」など〉ではなく、"
                      "本文で最初に参照される順の通し番号を本誌の形式〈設定 fn_mark〉で付けています。対応は下の表）")
    else:
        word_marks = "（Word の脚注機能で書かれた注の番号だけは、Word の表示「1」ではなく本誌の形式（設定 fn_mark）にしています）"
    L.append("Word の自動段落番号や脚注番号は docx の文字ではなく Word が表示時に作るものです。表示どおりの文字を XML に出力しました"
             f"{word_marks}。"
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
    note_rows = word_note_rows(r)
    if note_rows:
        L.append(f"{'Word の脚注・文末脚注' if has_endnotes(plan) else 'Word の脚注'}と、XML の注の対応（「Word の注」の番号は docx の"
                 "中の番号で、Word の画面に出る番号〈文末脚注の「i」など〉と違うことがあります。Word で注を探すときは、注の書き出しを"
                 "手がかりにしてください）:")
        L.append("")
        L.append(table(["XML の注", "Word の注", "番号", "注の書き出し", "本文からのリンク"], note_rows))
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
    lost = r.lost_images
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
            ("キーワード（日）", "；".join(m.keywords_ja) or "（なし）"),
            ("キーワード（英）", "; ".join(m.keywords_en) or "（なし）"),
            ("抄録の二次利用（specific-use）",
             f"{j.abstract_specific_use}（英文の論文で英文要旨を <abstract> に入れるときだけ使う。学会の方針を確認すること）")]
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
        for e in r.dtd_errors[:100]:
            L.append(f"- {esc(e)}")
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
    L.append(pdf_checklist_line(r))
    L.append("- [ ] 2 章（AI による補完）と 3 章（未解決）を PDF と照らして確認する")
    if fx is not None:
        L.append(f"- [ ] **PDF に合わせて直した docx（{esc(fx.path.name)}）を Word で開き、変更履歴を確認する**"
                 "（却下したい変更があれば、却下して保存した docx を「docx から作る」で変換し直す）")
        if fx.skipped:
            L.append(f"- [ ] 13 章の、PDF に合わせて直せなかった箇所（{len(fx.skipped)} 件）を確認する")
    # 要対応・要確認（actions）。PDF の項目を先に、残りを actions の順に。「画像はすべて Graphics/ に入っている」は、XML に
    # 入らなかった画像・暫定の知らせの前に出す
    checks = [a for a in acts if a.key in PDF_KEYS] + [a for a in acts if a.key not in PDF_KEYS]
    all_images = bool(r.images) and not images_to_prepare(r) and not lost
    for a in checks:
        if all_images and (a.key == "lost" or a.key in PROVISIONAL):
            L.append(f"- [x] 画像 {len(r.images)} 件はすべて Graphics/ に入っている（9 章）")
            all_images = False
        if a.checklist:
            L.append(a.checklist)
    if all_images:
        L.append(f"- [x] 画像 {len(r.images)} 件はすべて Graphics/ に入っている（9 章）")
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
             f"（照合した段落 {pc.checked} 件。表のセル・別行の数式・資料の見出しと、4 文字未満の段落は除く）。"
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
             " 1 文字も違いません（文字の不変性チェック）。表のセル・別行の数式・図の中の文字・資料の見出しと、4 文字未満の段落は照合せず、"
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
    if ai.partial:
        L += [f"**AI の回答が途中で切れていました。** {esc(ai.partial)}", ""]
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
