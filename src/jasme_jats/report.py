"""変換レポート（Markdown）。

冒頭に結果の要約、続いて AI による補完（不確実性のある箇所）、機械処理で解決できなかった箇所、
機械的な推定、出力しなかった文字の全件、落とした空白の全件、生成文字、画像、書誌情報、DTD 検証の順に並べる。
"""
from __future__ import annotations

from collections import Counter


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
                rows.append((d.did, d.confidence, CAT_JA.get(d.category, d.category), d.location or d.src, d.message))
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
    unc = getattr(plan, "uncited_refs", [])
    if unc:
        L.append("")
        L.append("本文中のどこからもリンクされていない文献: " + "、".join(
            f"{rid}（{esc(next((x.para.plain()[:30] for x in plan.refs if x.rid == rid), ''))}）" for rid in unc))
    L.append("")

    # ------------------------------------------------------------------ 4. 機械的な推定
    L.append("## 4. 機械処理による推定（生成 AI は使っていない）")
    L.append("")
    mech = [d for d in plan.decisions if d.stage == "mechanical"] + r.build_notes
    if mech:
        rows = [(d.did, CAT_JA.get(d.category, d.category), d.location or d.src, d.message) for d in mech]
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
            ("原稿種別", m.subject_ja or j.subject_ja), ("論文種別（article-type）", m.article_type or j.article_type),
            ("抄録の二次利用（specific-use）", f"{j.abstract_specific_use}（学会の方針を確認すること）")]
    L.append(table(["項目", "値"], rows))
    L.append("")

    # ------------------------------------------------------------------ 12. DTD
    L.append("## 12. DTD 検証の詳細")
    L.append("")
    if r.dtd_valid:
        L.append("J-STAGE 指定の DTD（https://www.jstage.jst.go.jp/dtds/1.1/JATS-journalpublishing1.dtd と同一の同梱版）で検証し、エラーはありませんでした。")
    else:
        for e in r.dtd_errors[:100]:
            L.append(f"- {esc(e)}")
    L.append("")

    # ------------------------------------------------------------------ 13. チェックリスト
    L.append("## 13. J-STAGE に登載する前に")
    L.append("")
    L.append(f"- [{'x' if r.has_pdf else ' '}] PDF（{m.article_id(j)}.pdf）を記事フォルダに入れる（J-STAGE では PDF が必須）")
    L.append("- [ ] 2 章（AI による補完）と 3 章（未解決）を PDF と照らして確認する")
    L.append("- [ ] 9 章で「要対応」の画像があれば用意して Graphics/ に入れる")
    L.append("- [ ] 11 章の書誌情報（巻・号・頁・日付・DOI）を確認する")
    L.append("- [ ] J-STAGE 編集登載システムにアップロードし、プレビューで本文・図表・引用文献リンクを確認する")
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
        L.append(f"- **{d.did}（確度 {d.confidence}）** {d.location or d.src}: {esc(d.message)}")
    if ai.rejected:
        L += ["", "## 検証で採用しなかった提案", ""]
        for op, why in ai.rejected:
            L.append(f"- {op.get('op')} [{op.get('src')}] 「{esc(op.get('text') or op.get('role') or op.get('image'))}」: {why}")
    if ai.notes:
        L += ["", "## AI からの気づき", ""]
        L += [f"- {esc(n)}" for n in ai.notes]
    return "\n".join(L) + "\n"
