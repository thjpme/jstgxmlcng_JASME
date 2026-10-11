"""変換レポート（Markdown）。

冒頭に結果の要約、続いて AI による補完（不確実性のある箇所）、機械処理で解決できなかった箇所、
機械的な推定、出力しなかった文字の全件、落とした空白の全件、生成文字、画像、書誌情報、DTD 検証と J-STAGE の登載時チェックの順に並べる。
"""
from __future__ import annotations

from collections import Counter

from .linker import body_paragraphs, linked_ids


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
UNRES_JA = {"bibr": "引用文献", "fig": "図の参照", "table": "表の参照", "fn": "注の参照"}


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
    if nums != list(range(1, len(nums) + 1)):
        out.append("注の番号が 1 からの連番になっていない: " + "、".join("（番号なし）" if n is None else str(n) for n in nums))
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
    ai_mode = {"none": "使用しない", "api": f"API（{ai.model}）", "manual": "手動（チャットに貼り付け）"}.get(ai.mode, ai.mode)
    L.append(f"- AI による補完: {ai_mode}")
    L.append("")

    # ------------------------------------------------------------------ 1. 要約
    L.append("## 1. 結果の要約")
    L.append("")
    fid_line = (f"{fid.summary()}（docx の段落 {fid.units} 件: XML に出力 {fid.mapped} 件、出力しなかった {len(fid.excluded)} 件"
                f"［6 章に全文］）")
    final_line = "合格" if fid.final_ok else ("不合格: " + fid.final_detail if fid.final_ok is False else "未実施")
    c = r.link_counts
    links = (f"引用文献 {c.get('bibr', 0)} / 図 {c.get('fig', 0)} / 表 {c.get('table', 0)} / 注 {c.get('fn', 0)} / "
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
        ("画像", f"{len(r.images)} 件（要対応 {sum(1 for i in r.images if i.status in ('failed', 'missing'))} 件、9 章）"),
        ("警告", f"{len(r.warnings)} 件（10 章）"),
    ]
    L.append(table(["項目", "結果"], rows))
    L.append("")
    if not fid.ok or fid.final_ok is False:
        L.append("> **注意: 文字の不変性チェックが不合格です。** 出力された XML の本文が docx と一致していません。"
                 "下の 5 章の差分を確認し、この XML は登載に使わないでください（変換ツールの不具合の可能性があります）。")
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
                 "AI が変更できるのはリンク・段落の役割・姓名の区切り・数式画像への MathML の併記だけで、本文の文字は変更していません。")
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
    if mech:
        rows = [(d.did, CAT_JA.get(d.category, d.category), d.location or r.plan.locations.get(d.src, d.src), d.message) for d in mech]
        L.append(table(["番号", "種類", "場所", "内容"], rows))
    else:
        L.append("ありません（すべての段落にテンプレートのスタイルが正しく設定されていました）。")
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
    L.append("## 8. Word が自動生成していた文字")
    L.append("")
    L.append("Word の自動段落番号や脚注番号は docx の文字ではなく Word が表示時に作るものです。表示どおりの文字を XML に出力しました。")
    L.append("")
    if fid.generated:
        cnt = Counter(k for k, _ in fid.generated)
        L.append("、".join(f"{ {'autonum': '自動番号', 'footnote-mark': '脚注番号'}.get(k, k)} {n} 件" for k, n in cnt.items())
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
        st = {"ok": "そのまま出力", "converted": "変換して出力", "failed": "要対応", "missing": "要対応（画像なし）"}
        L.append(table(["画像", "出力ファイル（Graphics/）", "docx 内のファイル", "状態", "備考"],
                       [(i.image_id, i.name, i.source, st.get(i.status, i.status), i.message) for i in r.images]))
    else:
        L.append("画像はありません。")
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

    # ------------------------------------------------------------------ 13. チェックリスト
    L.append("## 13. J-STAGE に登載する前に")
    L.append("")
    L.append(f"- [{'x' if r.has_pdf else ' '}] PDF（{m.article_id(j)}.pdf）を記事フォルダに入れる（J-STAGE では PDF が必須）")
    L.append("- [ ] 2 章（AI による補完）と 3 章（未解決）を PDF と照らして確認する")
    L.append("- [ ] 9 章で「要対応」の画像があれば用意して Graphics/ に入れる")
    L.append("- [ ] 11 章の書誌情報（巻・号・頁・日付・DOI）を確認する")
    L.append(f"- [ ] J-STAGE 編集登載システムで、巻（{esc(m.volume or '?')}）・号（{esc(m.issue or '?')}）と、その号のセクション"
             "（目次の見出し。例: 論文）を作成しておく（ないとアップロード時に EMSGM181E「巻号が学会誌別巻号の設定に存在しません」・"
             "EMSGM182E「学会誌別セクションが存在しません」になる）")
    L.append("- [ ] J-STAGE 編集登載システムにアップロードし、記事を正しいセクションに振り分け（記事移動）、"
             "プレビューで本文・図表・引用文献リンクを確認する")
    L.append("")
    return "\n".join(L)


def render_ai_only(r) -> str:
    """AI による判断だけをまとめた別ファイル（不確実性のある箇所の一覧）。"""
    ai = r.ai
    L = [f"# AI による補完の判断一覧: {r.docx_name}", "",
         "AI（生成 AI）が判断した箇所の一覧です。AI は本文の文字を変更していません（リンク・段落の役割・姓名の区切り・"
         "数式画像への MathML の併記のみ）。確度の低いものから順に並べています。PDF と照らして確認してください。", ""]
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
