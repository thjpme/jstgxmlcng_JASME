"""Colab ノートブックで使う表示部品（HTML）。

ノートブックのセルを短く保ち、テストできるようにするため、表示用の HTML はここで作る。
Colab の出力欄は暗い配色のこともあるので、枠の中の文字色・背景色は明示する。

枠の色は 3 つ: 要対応は赤（error_box）、要確認は黄（check_box）、結果の要約は灰（summary_box）。変換の後は、要対応・要確認の
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

_BOX = ("border:3px solid #d97706;border-radius:8px;padding:12px 16px;margin:12px 0;background:#fffbeb;"
        "color:#1f2937;font-size:14px;line-height:1.6")
_BUTTON = ("background:#d97706;color:#ffffff;border:none;border-radius:6px;padding:8px 16px;font-size:15px;"
           "font-weight:bold;cursor:pointer")
_TEXTAREA = ("width:100%;box-sizing:border-box;font-family:monospace;font-size:12px;color:#111827;background:#ffffff;"
             "border:1px solid #9ca3af;border-radius:4px;padding:6px;margin-top:8px")


def prompt_box(prompt: str, image_names=()) -> str:
    """手動モードの依頼文を、コピーボタン付きの目立つ枠で表示する HTML（手順 5 で、結果の枠の前に出す）。"""
    tid = "jasme-prompt-" + uuid.uuid4().hex[:8]
    imgs = ""
    if image_names:
        names = "、".join(html.escape(n) for n in image_names)
        imgs = (f"<li>画像 {len(image_names)} 枚（{names}）も同じメッセージに添付します。"
                "画像はブラウザのダウンロードフォルダに保存されています。</li>")
    head = "手動モード: 次の依頼文を AI（claude.ai などのチャット）に渡してください"
    steps = ("<ol style='margin:6px 0 10px 20px;padding:0'>"
             "<li>「依頼文をコピー」を押し、<b>新しいチャット</b>に貼り付けて送信します。</li>"
             f"{imgs}"
             "<li>返ってきた回答（<code>json</code> と書かれたコードブロック）を、コードブロック右上のコピーボタンでコピーします。</li>"
             "<li>この下の<b>手順 6</b> のセルに貼り付けて ▶ を押します。</li>"
             "</ol>")
    return (f"{_COPY_JS}<div style=\"{_BOX}\">"
            f"<div style='font-size:18px;font-weight:bold;margin-bottom:4px'>{html.escape(head)}</div>"
            f"{steps}"
            f"<button style=\"{_BUTTON}\" onclick=\"jasmeCopy('{tid}')\">依頼文をコピー</button>"
            f"<span id='{tid}-msg' style='margin-left:12px;font-weight:bold'></span>"
            f"<textarea id='{tid}' readonly style=\"{_TEXTAREA};height:220px\">{html.escape(prompt)}</textarea>"
            "</div>")


NO_AI_TITLE = "AI による補完を「使わない」設定です（推奨しません）"
NO_AI_DETAIL = ("機械的な変換だけでは、テンプレートのスタイルが正しく設定されていない段落、決まった形でない引用（著者名と年が離れている、"
                "括弧がないなど）、画像で貼られた数式などを取りこぼすことがあります。"
                "API キーがなくても使える「手動（チャットに貼り付け）」を選ぶことをお勧めします。")


def no_ai_box(screen: str = "notebook") -> str:
    """AI による補完を使わないときに出す注意（赤い枠）。screen は目印の置き換え先（step_text）。"""
    return error_box(step_text(NO_AI_TITLE, screen), step_text(NO_AI_DETAIL, screen))


def _notice(title: str, detail: str, border: str, background: str, heading: str) -> str:
    return (f"<div style='border:3px solid {border};border-radius:8px;padding:12px 16px;margin:12px 0;background:{background};"
            "color:#1f2937;font-size:14px;line-height:1.6'>"
            f"<div style='font-size:17px;font-weight:bold;color:{heading}'>{html.escape(title)}</div>"
            f"<div style='white-space:pre-wrap'>{html.escape(detail)}</div></div>")


def error_box(title: str, detail: str) -> str:
    """要対応（登載の前に直すもの）と、読み込めなかった AI の回答などの見落とされると困るエラーを赤い枠で表示する HTML。"""
    return _notice(title, detail, "#dc2626", "#fef2f2", "#b91c1c")


def check_box(title: str, detail: str) -> str:
    """要確認（確かめて、必要なら直すもの）を黄色い枠で表示する HTML。"""
    return _notice(title, detail, "#d97706", "#fffbeb", "#b45309")


_SUMMARY = ("border:2px solid #9ca3af;border-radius:8px;padding:10px 16px;margin:12px 0;background:#f9fafb;"
            "color:#1f2937;font-size:14px;line-height:1.7")


def summary_box(res) -> str:
    """変換の結果の要約（文字の不変性チェック・DTD 検証・J-STAGE のアップロード時チェック・出版版 PDF との照合）を灰色の枠で
    表示する HTML。手順 5・6 で、要対応・要確認の枠の後、レポート全文の前に出す。不合格・要対応の行は赤い文字にする。"""
    from .report import pdf_summary, upload_issues
    fid = res.fidelity
    issues = upload_issues(res)
    rows = [("文字の不変性チェック", f"{fid.summary()}（段落 {fid.units} 件中 {fid.mapped} 件を出力、{len(fid.excluded)} 件は除外）",
             fid.ok),
            ("最終出力の再チェック", "合格" if fid.final_ok else "不合格", fid.final_ok),
            ("DTD 検証", "合格" if res.dtd_valid else "不合格", res.dtd_valid),
            ("J-STAGE のアップロード時チェック",
             "問題なし" if not issues else f"要対応 {len(issues)} 件\n" + "\n".join(f"　{mid} {msg}" for mid, msg in issues),
             not issues),
            ("出版版 PDF との照合", pdf_summary(res), True)]
    sup = getattr(res, "supplement", None)
    if sup is not None:             # ルート2 で補完の確かめを行ったときだけ
        rows.insert(4, ("出版版 PDF による補完の確かめ", "合格" if sup.ok else "不合格（この XML は登載に使わないでください）", sup.ok))
    if res.docx_fix is not None:
        rows.append(("PDF で補った docx", f"{res.docx_fix.path.name}（変更履歴つき。ダウンロードする ZIP に入ります）", True))
    elif res.pdf_fallback:
        rows.append(("PDF で補った docx", "作れませんでした（PDF の文字を読めなかったため、docx を補わずに変換しました）", False))
    lines = "".join(f"<div style='white-space:pre-wrap{'' if ok else ';color:#b91c1c;font-weight:bold'}'>"
                    f"{html.escape(label)}: {html.escape(value)}</div>" for label, value, ok in rows)
    return f"<div style=\"{_SUMMARY}\"><div style='font-weight:bold;margin-bottom:2px'>結果の要約</div>{lines}</div>"


_REPORT_CSS = ("color:#1f2937;background:#ffffff;padding:8px 16px;border:1px solid #d1d5db;border-radius:8px;font-size:14px;"
               "line-height:1.6")
_REPORT_STYLE = """<style>
.jasme-report table{border-collapse:collapse;margin:8px 0}
.jasme-report th,.jasme-report td{border:1px solid #9ca3af;padding:3px 8px;vertical-align:top;text-align:left}
.jasme-report blockquote{border-left:4px solid #9ca3af;margin:8px 0;padding:2px 12px;background:#f3f4f6}
.jasme-report pre{background:#f3f4f6;padding:8px;overflow-x:auto}
.jasme-report h1,.jasme-report h2,.jasme-report h3{margin-top:1em}
</style>"""


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
    return (f"{_REPORT_STYLE}<details style='margin:12px 0'><summary style='cursor:pointer;font-weight:bold;font-size:15px'>"
            f"{html.escape(title)}</summary><div class='jasme-report' style=\"{_REPORT_CSS}\">{body}</div></details>")


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
        "今回の論文のものに書き換えてから ▶ を押してください。手順 4（AI による補完の方法・モデル名）と、"
        "手順 6（AI の回答）の欄も前の論文のときのままです。\n"
        "書き換え漏れが心配なときは、ノートブックを開き直して（README の「Open in Colab」のボタンなどから）、"
        "手順 1 からやり直すほうが確実です。GitHub のノートブックを開き直すと、入力欄は初期の値に戻ります。")


def ai_required_box(message: str, screen: str = "notebook") -> str:
    """AI による補完を使わない設定で、位置を決められない図表があったときの表示（変換は中止）。

    message は pipeline.AIRequiredError の文（画面の操作の目印つき）。screen は目印の置き換え先（step_text）。
    """
    return error_box("AI による補完が必要です（変換を中止しました）", step_text(message, screen))


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
# 1ffed92 までの文と同じになる形。ただし answer_apply〈以前の answer_paste。「▶ を押す」を足した〉とコマンドラインの語は、0.29.0 の最後の点検で直した。「手順 2」のように数字で終わる語の後ろの助詞の前の空白は step_text が補う）。
# 1 画面版の語は app.py の部品のラベルに合わせる（ラベルは下の定数。app.py もこれを使う）。語の形は、前後の文が決める:
#   paste・repaste・convert_again: 「…してください」に続く（語は「押」「指定し直し」などの語幹で終わる）。
#   answer_apply: 「…と、AI が…」に続く（「押す」「変換し直す」の終止形で終わる。「反映」を押した後にさらに「変換する」を押す
#   操作に読めないよう、1 画面版は「反映」を押すだけで変換し直されることが分かる形にする）。
#   answer_field・apply_button: 欄・ボタンの名前（app.CRASH_ADVICE が使う）。
ANSWER_LABEL = "AI の回答（json のコードブロック）を貼り付ける"      # 1 画面版の回答の欄のラベル（app.py の gr.Textbox）
APPLY_LABEL = "反映"                                             # 回答を反映するボタン
CONVERT_LABEL = "変換する"                                       # 変換するボタン（回答なしで作り直す）
STEP_WORDS = {
    "notebook": {
        "docx": "手順 2", "pdf": "手順 2", "route": "手順 2", "meta": "手順 3",
        "ai_choose": "手順 4 で AI による補完の方法を「API で自動実行」か「手動（チャットに貼り付け）」にして ▶ を押し、手順 5 から",
        "ai_modes": "「API で自動実行」か「手動（チャットに貼り付け）」を選んで",
        "prompt": "手順 5 の依頼文", "paste": "手順 6 に貼り付けて ▶ を押", "repaste": "手順 6 で貼り付け直し",
        "answer_apply": "手順 6 で AI の回答を貼り付けて ▶ を押す", "convert_again": "手順 5 をもう一度実行",
        "answer_field": "手順 6 の貼り付けの欄", "apply_button": "手順 6 の ▶",
        "images": "手順 7「足りない画像をアップロード」"},
    "app": {
        "docx": "「docx（論文の Word ファイル）」の欄", "pdf": "「PDF（J-STAGE に登載する PDF）」の欄", "route": "「作り方」の欄",
        "meta": "巻・号・ページなどの入力欄",
        "ai_choose": f"「AI による補完の方法」の欄を「手動（チャットに貼り付け）」か「API（Claude）」にして「{CONVERT_LABEL}」を押し、",
        "ai_modes": "「AI による補完の方法」の欄で「手動（チャットに貼り付け）」か「API（Claude）」を選んで",
        "prompt": "依頼文", "paste": f"「{ANSWER_LABEL}」の欄に貼り付けて「{APPLY_LABEL}」を押",
        "repaste": f"「{ANSWER_LABEL}」の欄に貼り付け直して「{APPLY_LABEL}」を押し",
        "answer_apply": f"AI の回答を「{ANSWER_LABEL}」の欄に貼り付けて「{APPLY_LABEL}」を押す",
        "convert_again": f"「{CONVERT_LABEL}」をもう一度押",
        "answer_field": f"「{ANSWER_LABEL}」の欄", "apply_button": f"「{APPLY_LABEL}」",
        # 欄の並びの見出し（AppState.images_markdown の「次の図の画像が必要です」）の下に、図ごとの欄が並ぶ。欄の名前は図のキャプション
        # （出力ファイル名）（AppState.slot_label）
        "images": "「次の図の画像が必要です」の下に並ぶ、図ごとの欄（欄の名前は図のキャプションと出力ファイル名）"},
    "cli": {
        "docx": "docx の指定", "pdf": "--pdf の指定", "route": "--route の指定", "meta": "--meta の指定",
        "ai_choose": "--ai manual か --ai api を指定して",
        "ai_modes": "--ai manual か --ai api を指定して",
        "prompt": "AI依頼文.txt", "paste": "ファイルに保存して --ai manual --ai-response 回答のファイル を指定",
        "repaste": "ファイルに保存して --ai manual --ai-response 回答のファイル を指定し直し",
        "answer_apply": "AI の回答をファイルに保存し、--ai manual --ai-response 回答のファイル を指定して変換し直す",
        "convert_again": "--ai api でもう一度実行",
        "answer_field": "--ai-response で指定する回答のファイル", "apply_button": "--ai-response の指定",
        "images": "--images の指定"},
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
    """report.Action を枠にする（要対応は赤、要確認は黄。枠の見出しがなければ空文字）。screen は目印の置き換え先（step_text）。"""
    from .report import NEEDS_ACTION
    if action is None or not action.box_title:
        return ""
    make = error_box if action.level == NEEDS_ACTION else check_box
    return make(step_text(action.box_title, screen), step_text(action.box_detail, screen))


def result_boxes(res, level=None, skip=(), screen: str = "notebook") -> str:
    """変換の結果の、要対応（赤）・要確認（黄）の枠（report.actions の順。なければ空文字）。手順 5・6・8 で使う。

    level を "要対応" にすると要対応だけ（手順 8 で一度止めるとき）。skip は出さない知らせの key（手順 5 の手動モードでは、
    依頼文の枠を出すので ai_pending を出さない）。screen は "notebook"（既定。手順の番号）か "app"（1 画面版。欄の名前）。
    """
    from .report import actions
    return "".join(_box(a, screen) for a in actions(res) if (level is None or a.level == level) and a.key not in skip)


def missing_images_box(res, screen: str = "notebook") -> str:
    """画像ファイルを用意できなかった図（Word の図形で描かれた図など）があるときの表示（赤い枠）。なければ空文字。"""
    from .report import images_action
    return _box(images_action(res), screen)


def lost_images_box(res, screen: str = "notebook") -> str:
    """docx にあるのに XML に入らなかった画像（引用文献の段落の中の画像など）があるときの表示（赤い枠）。なければ空文字。"""
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


def unplaced_box(plan, partial="", screen: str = "notebook") -> str:
    """AI の回答を反映した後も、位置を決められない図表が残っているときの表示（report.unplaced_text）。なければ空文字。"""
    from .report import unplaced_text
    text = unplaced_text(plan, partial)
    return error_box(*(step_text(t, screen) for t in text)) if text else ""


def figure_body_box(res, screen: str = "notebook") -> str:
    """図の本体（画像・表）が見つからない図があるときの表示（赤い枠）。なければ空文字。"""
    from .report import figure_body_action
    return _box(figure_body_action(res), screen)
