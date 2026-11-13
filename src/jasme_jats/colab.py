"""Colab ノートブックで使う表示部品（HTML）。

ノートブックのセルを短く保ち、テストできるようにするため、表示用の HTML はここで作る。
Colab の出力欄は暗い配色のこともあるので、枠の中の文字色・背景色は明示し、枠は白地に暗い文字に固定する（`LIGHT_STYLE`。ダークモードでも読める）。

枠の色は 4 つ: 要対応は赤（error_box）、要確認は黄（check_box）、手順は青（step_box）、結果の要約は灰（summary_box）。変換の後は、要対応・要確認の
枠（result_boxes）→ 結果の要約（summary_box）→ レポート全文（report_details。畳んで出す）の順に出す。
"""
from __future__ import annotations

import html
import re
import unicodedata
import uuid

_COPY_JS = """
<script>
function jasmeCopy(id) {
  const ta = document.getElementById(id);
  const msg = document.getElementById(id + "-msg");
  const done = (ok) => {
    msg.textContent = ok ? "コピーしました。チャットに貼り付けてください。"
                         : "自動でコピーできませんでした。枠の中をクリックし、Ctrl+A（Mac は ⌘+A）→ Ctrl+C（⌘+C）でコピーしてください。";
  };
  const fallback = () => { ta.focus(); ta.select(); let ok = false; try { ok = document.execCommand("copy"); } catch (e) {} done(ok); };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(ta.value).then(() => done(true), fallback);
  } else {
    fallback();
  }
}
</script>
"""

_LIGHT_INK = "#1f2937"
_LIGHT_TAGS = ("div", "p", "span", "li", "ol", "ul", "table", "thead", "tbody", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6",
               "b", "strong", "em", "i", "u", "small", "code", "pre", "blockquote", "summary", "details", "label", "caption", "sup", "sub", "a", "kbd", "del", "ins", "s", "mark")


def _light_css() -> str:
    def sel(tags, prefix=".jasme-light"):
        return ",".join(f"{prefix} {t}" for t in tags)
    plain = tuple(t for t in _LIGHT_TAGS if t not in ("blockquote", "pre"))
    return ("<style>"
            f".jasme-light,{sel(_LIGHT_TAGS)}{{color:{_LIGHT_INK} !important}}"
            f".jasme-light{{color-scheme:light}}"
            f"{sel(plain)}{{background:transparent !important}}"
            f"{sel(('blockquote', 'pre'))}{{background:#f3f4f6 !important}}"
            ".jasme-light a{color:#1d4ed8 !important}"
            ".jasme-report table{border-collapse:collapse;margin:8px 0}"
            ".jasme-report th,.jasme-report td{border:1px solid #9ca3af;padding:3px 8px;vertical-align:top;text-align:left}"
            ".jasme-report blockquote{border-left:4px solid #9ca3af;margin:8px 0;padding:2px 12px}"
            ".jasme-report pre{padding:8px;overflow-x:auto}"
            ".jasme-report h1,.jasme-report h2,.jasme-report h3{margin-top:1em}"
            "</style>")


# 白地の枠に共通の <style>（クラス jasme-light）。Gradio のダークモードや暗い出力欄が、中の要素に明るい文字の色・暗い背景を当てても、
# 枠の中は白地に暗い文字で読めるように、文字の色と背景を !important で決める。枠ごとに独立に描かれるので、枠の HTML ごとに含める。
# 枠の見出しの色など、わざと色を付けるところはインラインの指定に !important を付ける（インラインの !important が勝つ）。
LIGHT_STYLE = _light_css()


# 手動モードの案内の枠（manual_guide・prompt_box）は推奨の手順なので、手順の枠（step_box）と同じ青にする（要確認の黄と分ける。
# 点検 review14 利用者向け 2）
_BOX = ("border:3px solid #2563eb;border-radius:8px;padding:12px 16px;margin:12px 0;background:#eff6ff !important;"
        "color:#1f2937 !important;font-size:14px;line-height:1.6")
_BUTTON = ("background:#2563eb !important;color:#ffffff !important;border:none;border-radius:6px;padding:8px 16px;font-size:15px;"
           "font-weight:bold;cursor:pointer")
_TEXTAREA = ("width:100%;box-sizing:border-box;font-family:monospace;font-size:12px;color:#111827 !important;background:#ffffff !important;"
             "border:1px solid #9ca3af;border-radius:4px;padding:6px;margin-top:8px")


COPY_STEP = {"notebook": "「依頼文をコピー」を押します。",
             "app": "「依頼文（新しいチャットに貼り付けて送る）」の欄の右上のコピーボタンで、依頼文をコピーします。",
             "cli": "AI依頼文.txt を開き、全文をコピーします。"}
NO_FLOATS_TITLE = "AI の回答を入れる（任意）"
NO_FLOATS_INTRO = ("この論文には、位置を決められない図・表はありません。AI は、リンクの取りこぼしやスタイルの誤りなど（論文によっては、"
                   "テキストボックスの種類・注の区切り・著者名の姓と名の区切りも）を確かめます。出版版 PDF を同じメッセージに添付すると、"
                   "AI が体裁を見て答えられます（任意）。このまま登載することもできます。")


def _wants_pdf(action) -> bool:
    """依頼文を渡すときに、出版版 PDF も同じメッセージに添付してもらう手順か（回答待ちの ai_finish の本文に目印 pdf_attach があるとき。
    位置を聞く図形か、2 段にまたがる機械的な図形がある場合）。"""
    from .report import STEP_MARK
    return action is not None and STEP_MARK + "step:pdf_attach" + STEP_MARK in action.box_detail


def _guide_inner(action, screen: str, pdf_name: str) -> str:
    """manual_guide の枠の中身（見出し・状況の説明・手順の番号つきの案内）。"""
    from .report import step
    # 見出し: 推奨の手順 ai_finish なら、手順の枠（step_box）と同じく「手順（推奨）: 」を前に付ける（失敗なら赤字）。
    # ないとき（NO_FLOATS_TITLE）は見出しに「（任意）」がある
    title = ("手順（推奨）: " + step_text(action.box_title, screen)) if action is not None else NO_FLOATS_TITLE
    color = "#b91c1c" if action is not None and action.failed else "#1d4ed8"
    intro = step_text(action.box_intro or action.box_detail, screen) if action is not None else NO_FLOATS_INTRO
    if _wants_pdf(action):
        which = f"変換に使った「{pdf_name}」と同じファイルです" if pdf_name else "この論文の出版版 PDF です"
        send = (f"新しいチャット（claude.ai など）に貼り付け、<b>{html.escape(STEP_WORDS[screen]['pdf_attach'])}</b>送信します"
                f"（強く推奨。出版版 PDF があると、図・表を出版版と同じ位置に置けます。PDF は、{html.escape(which)}）。")
    else:
        send = "新しいチャット（claude.ai など）に貼り付けて送信します。"
    steps = ("<ol style='margin:6px 0 10px 20px;padding:0'>"
             f"<li>{COPY_STEP[screen]}</li>"
             f"<li>{send}</li>"
             "<li>返ってきた回答（<code>json</code> と書かれたコードブロック）を、コードブロック右上のコピーボタンでコピーします。</li>"
             f"<li>{html.escape(step_text(step('paste'), screen))}します。</li>"
             "</ol>")
    after = "<div>このまま登載することもできます。</div>" if action is not None else ""      # 任意であること（ない場合の説明には書いてある）
    return (f"<div style='font-size:18px;font-weight:bold;margin-bottom:4px;color:{color} !important'>{html.escape(title)}</div>"
            f"<div style='white-space:pre-wrap'>{html.escape(intro)}</div>{steps}{after}")


def ai_finish_of(res):
    """結果（pipeline.Result）の推奨の手順 ai_finish（report.actions の中の key が ai_finish のもの。出す条件に当たらなければ None）。
    手動の案内（manual_guide・prompt_box）の action に渡す。"""
    from .report import actions
    return next((a for a in actions(res) if a.key == "ai_finish"), None)


def manual_guide(action=None, screen: str = "notebook", pdf_name: str = "") -> str:
    """手動モードの案内の枠（見出し・状況の説明・手順の番号つきの案内。依頼文の枠〈prompt_box〉の上の部分。1 画面版は結果の枠の並びに出す）。

    action は回答待ちの推奨の手順 ai_finish（report.actions の key が ai_finish のもの）。見出しは box_title に、手順の枠（step_box）と
    同じ「手順（推奨）: 」を前に付け、最初の説明は box_intro をそのまま使う（同じ文を 2 か所に書かない。修正計画 W8 の 4.5）。枠の色は
    手順の青（点検 review14 利用者向け 2）。None のとき（位置を聞く図形・2 段にまたがる機械的な図形などがなく、AI の知らせがないとき）は
    見出しを「AI の回答を入れる（任意）」にする。pdf_name はツールに渡された出版版 PDF のファイル名（なければ「この論文の出版版 PDF」）。
    画面の操作は目印（report.step）で書き、screen（"notebook"・"app"・"cli"）の語に置き換える。
    """
    return f"{LIGHT_STYLE}<div class='jasme-light' style=\"{_BOX}\">{_guide_inner(action, screen, pdf_name)}</div>"


def prompt_box(prompt: str, action=None, screen: str = "notebook", pdf_name: str = "") -> str:
    """手動モードの依頼文を、案内（manual_guide）とコピーボタン付きの目立つ枠で表示する HTML（ノートブックで、結果の枠の後ろに出す。
    この枠を出すときは ai_finish の枠を重ねて出さない）。docx の画像は AI に渡さない（修正計画 W1）ので、添付する画像はない。
    action・screen・pdf_name は manual_guide と同じ。"""
    tid = "jasme-prompt-" + uuid.uuid4().hex[:8]
    return (f"{LIGHT_STYLE}{_COPY_JS}<div class='jasme-light' style=\"{_BOX}\">{_guide_inner(action, screen, pdf_name)}"
            f"<button style=\"{_BUTTON}\" onclick=\"jasmeCopy('{tid}')\">依頼文をコピー</button>"
            f"<span id='{tid}-msg' style='margin-left:12px;font-weight:bold;color:#1f2937 !important'></span>"
            f"<textarea id='{tid}' readonly style=\"{_TEXTAREA};height:220px\">{html.escape(prompt)}</textarea>"
            "</div>")


def _notice(title: str, detail: str, border: str, background: str, heading: str) -> str:
    return (f"{LIGHT_STYLE}<div class='jasme-light' style='border:3px solid {border};border-radius:8px;padding:12px 16px;"
            f"margin:12px 0;background:{background} !important;color:#1f2937 !important;font-size:14px;line-height:1.6'>"
            f"<div style='font-size:17px;font-weight:bold;color:{heading} !important'>{html.escape(title)}</div>"
            f"<div style='white-space:pre-wrap'>{html.escape(detail)}</div></div>")


def error_box(title: str, detail: str) -> str:
    """要対応（登載の前に直すもの）と、読み込めなかった AI の回答などの見落とされると困るエラーを赤い枠で表示する HTML。"""
    return _notice(title, detail, "#dc2626", "#fef2f2", "#b91c1c")


def check_box(title: str, detail: str) -> str:
    """要確認（確かめて、必要なら直すもの）を黄色い枠で表示する HTML。"""
    return _notice(title, detail, "#d97706", "#fffbeb", "#b45309")


def step_box(title: str, detail: str, failed: bool = False, required: bool = True) -> str:
    """手順（report.STEP。毎回行うこと）を青い枠で表示する HTML。見出しの前に「手順」（推奨の手順は「手順（推奨）」）を付ける。
    failed（やってみて失敗した）なら見出しを赤字にする。"""
    head = ("手順" if required else "手順（推奨）") + ": " + title
    return _notice(head, detail, "#2563eb", "#eff6ff", "#b91c1c" if failed else "#1d4ed8")


_SUMMARY = ("border:2px solid #9ca3af;border-radius:8px;padding:10px 16px;margin:12px 0;background:#f9fafb !important;"
            "color:#1f2937 !important;font-size:14px;line-height:1.7")


def summary_box(res) -> str:
    """変換の結果の要約（文字の不変性チェック・DTD 検証・J-STAGE のアップロード時チェック・出版版 PDF との照合・AI による仕上げ）を灰色の枠で
    表示する HTML。手順 5・6 で、要対応・要確認の枠の後、レポート全文の前に出す。不合格・要対応の行は赤い文字にする。"""
    from .report import ai_summary, pdf_summary, upload_issues
    fid = res.fidelity
    issues = upload_issues(res)
    rows = [("文字の不変性チェック", f"{fid.summary()}（段落 {fid.units} 件中 {fid.mapped} 件を出力、{len(fid.excluded)} 件は除外）",
             fid.ok),
            ("最終出力の再チェック", "合格" if fid.final_ok else "不合格", fid.final_ok),
            ("DTD 検証", "合格" if res.dtd_valid else "不合格", res.dtd_valid),
            ("J-STAGE のアップロード時チェック",
             "問題なし" if not issues else f"要対応 {len(issues)} 件\n" + "\n".join(f"　{mid} {msg}" for mid, msg in issues),
             not issues),
            ("出版版 PDF との照合", pdf_summary(res), True),
            ("AI による仕上げ", ai_summary(res), True)]      # 推奨の手順なので、失敗でも赤くしない（修正計画 W8 の 4.8）
    sup = getattr(res, "supplement", None)
    if sup is not None:             # ルート2 で補完の確かめを行ったときだけ
        rows.insert(4, ("出版版 PDF による補完の確かめ", "合格" if sup.ok else "不合格（この XML は登載に使わないでください）", sup.ok))
    if res.docx_fix is not None:
        rows.append(("PDF で補った docx", f"{res.docx_fix.path.name}（変更履歴つき。ダウンロードする ZIP に入ります）", True))
    elif res.pdf_fallback:
        rows.append(("PDF で補った docx", "作れませんでした（PDF の文字を読めなかったため、docx を補わずに変換しました）", False))
    lines = "".join(f"<div style='white-space:pre-wrap{'' if ok else ';color:#b91c1c !important;font-weight:bold'}'>"
                    f"{html.escape(label)}: {html.escape(value)}</div>" for label, value, ok in rows)
    return f"{LIGHT_STYLE}<div class='jasme-light' style=\"{_SUMMARY}\"><div style='font-weight:bold;margin-bottom:2px'>結果の要約</div>{lines}</div>"


_REPORT_CSS = ("color:#1f2937 !important;background:#ffffff !important;padding:8px 16px;border:1px solid #d1d5db;"
               "border-radius:8px;font-size:14px;line-height:1.6")


def markdown_text_only(markdown_text: str) -> str:
    """変換レポート（Markdown）を HTML にする。生の HTML は使わず、書かれた文字をそのまま文字として見せる。

    レポートは docx の文字を引用する（10 章の警告・冒頭の「対象の段落」など）。引用に「x<y>z」「<y かつ z>」「a&amp;b」のような
    タグ・実体参照に見える並びがあっても、HTML のタグ・実体として読まれて文字が消えない（または別の文字に変わらない）ように、
    Markdown の生の HTML（ブロック・インライン）と自動リンクの `<…>` を無効にし、`&` は先に別の文字に置き換えて、HTML にした後で
    `&amp;` に戻す（markdown ライブラリは `&amp;` のような実体の形をそのまま通すため）。コードの書式（バッククォート・``` で囲んだ
    範囲）の中は、もともと文字として出る。レポート自身は生の HTML・実体を使わない（`report.md_tag` はタグをコードで囲む。
    tests/test_colab.py の test_report_details_shows_angle_brackets が全 fixture のレポートで確かめる）。
    """
    import markdown
    from markdown.extensions import Extension

    class TextOnly(Extension):
        def extendMarkdown(self, md):
            md.preprocessors.deregister("html_block", strict=False)
            for name in ("html", "autolink", "automail"):
                md.inlinePatterns.deregister(name, strict=False)
    amp = next(c for c in map(chr, range(0xE000, 0xF8FF)) if c not in markdown_text)       # 文章にない私用領域の文字
    body = markdown.markdown(markdown_text.replace("&", amp), extensions=["tables", "fenced_code", TextOnly()])
    return body.replace(amp, "&amp;")


def report_details(markdown_text: str, title: str = "変換レポートの全文を見る（クリックで開きます）") -> str:
    """変換レポート（Markdown）を、畳んだ状態（HTML の details）で表示する HTML。

    Markdown → HTML の変換には markdown ライブラリ（pyproject の colab の extra）を使う。入っていなければ、そのままの文字で出す。
    """
    try:
        body = markdown_text_only(markdown_text)
    except ImportError:
        body = f"<pre style='white-space:pre-wrap'>{html.escape(markdown_text)}</pre>"
    # 「全文を見る」の行も暗い背景の上に出ないよう、details ごと白地の枠にする
    return (f"{LIGHT_STYLE}<details class='jasme-light' style=\"margin:12px 0;{_REPORT_CSS}\">"
            f"<summary style='cursor:pointer;font-weight:bold;font-size:15px'>"
            f"{html.escape(title)}</summary><div class='jasme-report'>{body}</div></details>")


# ---------------------------------------------------------------------------- 続けて他の論文を変換するとき（手順 9 の後）
# 論文ごとに違うはずの項目。手順 3 で、前の論文の値が残ったままになっていないかを確かめる。
PER_ARTICLE_FIELDS = {"fpage": "最初のページ", "lpage": "最後のページ", "keywords_ja": "キーワード（日本語）",
                      "keywords_en": "キーワード（英語）", "approved": "最終査読日", "received": "受付日",
                      "accepted": "受理日", "doi": "DOI"}


def same_first_page(previous: dict, current: dict) -> bool:
    """巻と最初のページが前の論文と同じ（出力のファイル名と DOI が前の論文と同じになる）か。

    ArticleMeta.from_dict と同じく NFKC にしてから比べる（「３１」と「31」は同じフォルダ名・ファイル名になる）。
    """
    def norm(d, k):
        return unicodedata.normalize("NFKC", str(d.get(k, "") or "")).strip()
    return all(norm(current, k) and norm(current, k) == norm(previous, k) for k in ("volume", "fpage"))


def carried_over(previous: dict, current: dict) -> list:
    """前の論文と同じ値のままの項目の名前（空欄の項目は除く）。"""
    return [label for key, label in PER_ARTICLE_FIELDS.items()
            if str(current.get(key, "")).strip() and current.get(key) == previous.get(key)]


def next_article_box(previous_docx: str = "") -> str:
    """手順 9 で出す注意（赤い枠）: 入力欄には前の論文の値が残っている。"""
    prev = f"前の論文（{previous_docx}）" if previous_docx else "前の論文"
    return error_box(
        f"手順 3 などの入力欄には、{prev}の値が残っています",
        "手順 2 から順に実行し、手順 3 の巻・号・ページ・査読の有無・キーワード・日付・責任著者などを、"
        "今回の論文のものに書き換えてから ▶ を押してください。手順 4（AI による仕上げの方法・モデル名）と、"
        "手順 6（AI の回答）の欄も前の論文のときのままです。\n"
        "書き換え漏れが心配なときは、ノートブックを開き直して（README の「Open in Colab」のボタンなどから）、"
        "手順 1 からやり直すほうが確実です。GitHub のノートブックを開き直すと、入力欄は初期の値に戻ります。")


def structure_conflict_box(message: str, screen: str = "notebook") -> str:
    """原稿の構造（同じ種類の後付けの見出しが 2 つ・著者名の付かない所属。K1・K2）で変換を中止したときの表示。

    message は pipeline.StructureConflictError の文（画面の操作の目印つき）。screen は目印の置き換え先（step_text）。
    """
    return error_box("原稿の構造を直す必要があります（変換を中止しました）", step_text(message, screen))


# ---------------------------------------------------------------------------- 画面の操作の言い方（画面ごと）
# report.Action.box_detail などの文は、画面の操作を目印（report.step）で書く。ノートブックの手順番号・1 画面版（app.py）の欄の名前・
# コマンドラインの指定の違いは、ここ 1 か所の表だけで決める。目印の名前は report.STEP_NAMES と同じ（食い違いはテストで見つける）。
# 目印は U+0000 で区切る（report.step）。U+0000 は XML 1.0 の文字ではなく、docx の文字（w:t）・ファイル名・PDF の文字
# （pdfmatch が制御文字を除く）のどれにも入らないので、docx 由来の文字（段落の抜粋など）に {{step:x}} のような並びがあっても
# 目印とは読まれない。語は、前後の文に合わせて「〜から」「〜で」「〜してください」に続けて読める形にする（ノートブックの語は
# 1ffed92 までの文と同じになる形。ただしコマンドラインの語は、0.29.0 の最後の点検で直した。「手順 2」のように数字で終わる語の後ろの助詞の前の空白は step_text が補う。
# 回答を反映すると AI が…と続けた目印 answer_apply は、AI を勧める文を推奨の手順 ai_finish に一本化して使わなくなったのでなくした。修正計画 W8 の手順 7）。
# 1 画面版の語は app.py の部品のラベルに合わせる（ラベルは下の定数。app.py もこれを使う）。語の形は、前後の文が決める:
#   paste・repaste・convert_again: 「…してください」に続く（語は「押」「指定し直し」などの語幹で終わる）。
#   answer_field・apply_button: 欄・ボタンの名前（app.CRASH_ADVICE が使う）。
ANSWER_LABEL = "AI の回答（json のコードブロック）を貼り付ける"      # 1 画面版の回答の欄のラベル（app.py の gr.Textbox）
APPLY_LABEL = "反映"                                             # 回答を反映するボタン
CONVERT_LABEL = "変換する"                                       # 変換するボタン（回答なしで作り直す）
STEP_WORDS = {
    "notebook": {
        "docx": "手順 2", "pdf": "手順 2", "route": "手順 2", "meta": "手順 3",
        "ai_choose": "手順 4 で AI による仕上げの方法を「API で自動実行」か「手動（チャットに貼り付け）」にして ▶ を押し、手順 5 から",
        "prompt": "手順 5 の依頼文", "paste": "手順 6 に貼り付けて ▶ を押", "repaste": "手順 6 で貼り付け直し",
        "convert_again": "手順 5 をもう一度実行",
        "answer_field": "手順 6 の貼り付けの欄", "apply_button": "手順 6 の ▶",
        "images": "手順 7「図の画像を入れる」", "pdf_attach": "出版版 PDF を同じメッセージに添付して"},
    "app": {
        "docx": "「docx（論文の Word ファイル）」の欄", "pdf": "「PDF（J-STAGE に登載する PDF）」の欄", "route": "「作り方」の欄",
        "meta": "巻・号・ページなどの入力欄",
        "ai_choose": f"「AI による仕上げの方法」の欄を「手動（チャットに貼り付け）」か「API（Claude）」にして「{CONVERT_LABEL}」を押し、",
        "prompt": "依頼文", "paste": f"「{ANSWER_LABEL}」の欄に貼り付けて「{APPLY_LABEL}」を押",
        "repaste": f"「{ANSWER_LABEL}」の欄に貼り付け直して「{APPLY_LABEL}」を押し",
        "convert_again": f"「{CONVERT_LABEL}」をもう一度押",
        "answer_field": f"「{ANSWER_LABEL}」の欄", "apply_button": f"「{APPLY_LABEL}」",
        # 結果の下の「図の画像」の欄（AppState.images_markdown の見出し。まとめて入れる欄・図ごとの行・「画像を入れる」が並ぶ）
        "images": "「図の画像」の欄", "pdf_attach": "出版版 PDF を同じメッセージに添付して"},
    "cli": {
        "docx": "docx の指定", "pdf": "--pdf の指定", "route": "--route の指定", "meta": "--meta の指定",
        "ai_choose": "--ai manual か --ai api を指定して",
        "prompt": "AI依頼文.txt", "paste": "ファイルに保存して --ai manual --ai-response 回答のファイル を指定",
        "repaste": "ファイルに保存して --ai manual --ai-response 回答のファイル を指定し直し",
        "convert_again": "--ai api でもう一度実行",
        "answer_field": "--ai-response で指定する回答のファイル", "apply_button": "--ai-response の指定",
        "images": "--images の指定", "pdf_attach": "出版版 PDF を一緒に渡して"},
}
_HIRAGANA = re.compile("[\u3041-\u309f]")


def step_text(text: str, screen: str = "notebook") -> str:
    """文の中の目印（report.step）を、画面（"notebook"・"app"・"cli"）の語に置き換える。知らない画面・目印は ValueError。

    「手順 2」のように数字で終わる語の直後にひらがな（「から」「で」など）が続くときは、間に半角の空白を入れる（「手順 2 から」）。
    """
    from .report import STEP_MARK_PATTERN
    if screen not in STEP_WORDS:
        raise ValueError(f"知らない画面: {screen}")
    words = STEP_WORDS[screen]

    def word(m):
        if m.group(1) not in words:
            raise ValueError(f"知らない目印: {m.group(1)}")
        w = words[m.group(1)]
        return w + " " if w[-1:].isdigit() and _HIRAGANA.match(m.string, m.end()) else w
    return re.sub(STEP_MARK_PATTERN, word, text)


def _box(action, screen: str = "notebook") -> str:
    """report.Action を枠にする（要対応は赤、要確認は黄、手順は青。枠の見出しがなければ空文字。済んだ手順の枠は、本文〈box_detail〉が
    あるときだけ出す。例: 画像を持ち越したときの、確かめてほしいこと）。screen は目印の置き換え先（step_text）。"""
    from .report import NEEDS_ACTION, STEP
    if action is None or not action.box_title:
        return ""
    title, detail = step_text(action.box_title, screen), step_text(action.box_detail, screen)
    if action.level == STEP:
        return "" if action.done and not action.box_detail else step_box(title, detail, failed=action.failed, required=action.required)
    return (error_box if action.level == NEEDS_ACTION else check_box)(title, detail)


def result_boxes(res, level=None, skip=(), screen: str = "notebook", blocking: bool = False) -> str:
    """変換の結果の、要対応（赤）・要確認（黄）・手順（青）の枠（report.actions の順。なければ空文字）。手順 5・6・8 で使う。

    level を "要対応" にすると要対応だけ。blocking を真にすると、止める知らせ（report.blocking。要対応と、残っている必須の手順）だけ
    （手順 8 で一度止めるとき）。skip は出さない知らせの key（手順 5 の手動モードでは、依頼文の枠を出すので AI による仕上げ〈ai_finish。回答待ち〉を出さない）。
    screen は "notebook"（既定。手順の番号）か "app"（1 画面版。欄の名前）。
    """
    from . import report
    acts = report.actions(res)
    if blocking:
        acts = report.blocking(acts)
    return "".join(_box(a, screen) for a in acts if (level is None or a.level == level) and a.key not in skip)


def missing_images_box(res, screen: str = "notebook") -> str:
    """図の画像がまだ残っているときの表示（手順 images の青い枠。report.images_action）。残っていなければ空文字。"""
    from .report import images_action
    return _box(images_action(res), screen)


def lost_images_box(res, screen: str = "notebook") -> str:
    """画像を入れる場所を作れなかった画像（引用文献の段落の中の画像など。report.lost_action）があるときの表示（赤い枠）。なければ空文字。"""
    from .report import lost_action
    return _box(lost_action(res), screen)


def pdf_diff_box(res, screen: str = "notebook") -> str:
    """出版版 PDF との照合で確認が必要なことがあるときの表示（要対応は赤、要確認は黄の枠。report.pdf_actions）。なければ空文字。

    ルート1（docx から作る）: docx と PDF で文字が違う箇所。PDF の文字を読めなければ「照合できませんでした」（要確認）。
    ルート2（docx から作り、出版版 PDF で補う）: 直さなかった箇所と、補った後も残る違い（組版の違いは数えない。補った docx は
    変換結果の ZIP に入る）。PDF の文字を読めなければ「出版版 PDF で補えませんでした」（要対応）。補完の確かめの不合格の枠は
    ここではなく result_boxes()（report.actions の全部）に出る。どちらでも、docx の段落の半分以上が PDF に
    見つからなければ「別の記事の PDF かもしれません」、照合に使わなかった PDF の文字があればその枠も出す。
    """
    from .report import pdf_actions
    return "".join(_box(a, screen) for a in pdf_actions(res))
