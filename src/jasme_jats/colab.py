"""Colab ノートブックで使う表示部品（HTML）。

ノートブックのセルを短く保ち、テストできるようにするため、表示用の HTML はここで作る。
Colab の出力欄は暗い配色のこともあるので、枠の中の文字色・背景色は明示する。
"""
from __future__ import annotations

import html
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


def prompt_box(prompt: str, image_names=(), compact: bool = False) -> str:
    """手動モードの依頼文を、コピーボタン付きの目立つ枠で表示する HTML。

    compact=True はレポートの後ろに出す短い版（同じ依頼文をコピーできる）。
    """
    tid = "jasme-prompt-" + uuid.uuid4().hex[:8]
    imgs = ""
    if image_names:
        names = "、".join(html.escape(n) for n in image_names)
        imgs = (f"<li>画像 {len(image_names)} 枚（{names}）も同じメッセージに添付します。"
                "画像はブラウザのダウンロードフォルダに保存されています。</li>")
    if compact:
        head = "↑ 上は AI 補完の前のレポートです。手動モードの依頼文は、ここからもコピーできます"
        steps = ""
        height = 90
    else:
        head = "手動モード: 次の依頼文を AI（claude.ai などのチャット）に渡してください"
        steps = ("<ol style='margin:6px 0 10px 20px;padding:0'>"
                 "<li>「依頼文をコピー」を押し、<b>新しいチャット</b>に貼り付けて送信します。</li>"
                 f"{imgs}"
                 "<li>返ってきた回答（<code>json</code> と書かれたコードブロック）を、コードブロック右上のコピーボタンでコピーします。</li>"
                 "<li>この下の<b>手順 6</b> のセルに貼り付けて ▶ を押します。</li>"
                 "</ol>")
        height = 220
    return (f"{_COPY_JS}<div style=\"{_BOX}\">"
            f"<div style='font-size:18px;font-weight:bold;margin-bottom:4px'>{html.escape(head)}</div>"
            f"{steps}"
            f"<button style=\"{_BUTTON}\" onclick=\"jasmeCopy('{tid}')\">依頼文をコピー</button>"
            f"<span id='{tid}-msg' style='margin-left:12px;font-weight:bold'></span>"
            f"<textarea id='{tid}' readonly style=\"{_TEXTAREA};height:{height}px\">{html.escape(prompt)}</textarea>"
            "</div>")


NO_AI_TITLE = "AI による補完を「使わない」設定です（推奨しません）"
NO_AI_DETAIL = ("機械的な変換だけでは、テンプレートのスタイルが正しく設定されていない段落、決まった形でない引用（著者名と年が離れている、"
                "括弧がないなど）、画像で貼られた数式などを取りこぼすことがあります。"
                "API キーがなくても使える「手動（チャットに貼り付け）」を選ぶことをお勧めします。")


def no_ai_box() -> str:
    """AI による補完を使わないときに出す注意（赤い枠）。"""
    return error_box(NO_AI_TITLE, NO_AI_DETAIL)


def error_box(title: str, detail: str) -> str:
    """読み込めなかった AI の回答など、見落とされると困るエラーを赤い枠で表示する HTML。"""
    return ("<div style='border:3px solid #dc2626;border-radius:8px;padding:12px 16px;margin:12px 0;background:#fef2f2;"
            "color:#1f2937;font-size:14px;line-height:1.6'>"
            f"<div style='font-size:17px;font-weight:bold;color:#b91c1c'>{html.escape(title)}</div>"
            f"<div style='white-space:pre-wrap'>{html.escape(detail)}</div></div>")


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


def ai_required_box(message: str) -> str:
    """AI による補完を使わない設定で、位置を決められない図表があったときの表示（変換は中止）。"""
    return error_box("AI による補完が必要です（変換を中止しました）", message)


def _box(action) -> str:
    """report.Action を赤い枠にする（枠の見出しがなければ空文字）。"""
    return error_box(action.box_title, action.box_detail) if action is not None and action.box_title else ""


def result_boxes(res, level=None, skip=()) -> str:
    """変換の結果の、要対応・要確認の赤い枠（report.actions の順。なければ空文字）。手順 5・6・8 で使う。

    level を "要対応" にすると要対応だけ（手順 8 で一度止めるとき）。skip は出さない知らせの key（手順 5 の手動モードでは、
    依頼文の枠を出すので ai_pending を出さない）。
    """
    from .report import actions
    return "".join(_box(a) for a in actions(res) if (level is None or a.level == level) and a.key not in skip)


def missing_images_box(res) -> str:
    """画像ファイルを用意できなかった図（Word の図形で描かれた図など）があるときの表示（赤い枠）。なければ空文字。"""
    from .report import images_action
    return _box(images_action(res))


def lost_images_box(res) -> str:
    """docx にあるのに XML に入らなかった画像（引用文献の段落の中の画像など）があるときの表示（赤い枠）。なければ空文字。"""
    from .report import lost_action
    return _box(lost_action(res))


def pdf_diff_box(res) -> str:
    """出版版 PDF との照合で確認が必要なことがあるときの表示（赤い枠。report.pdf_actions）。なければ空文字。

    ルート1（docx から作る）: docx と PDF で文字が違う箇所。PDF の文字を読めなければ「照合できませんでした」（要確認）。
    ルート2（出版版 PDF に合わせてから作る）: 直せなかった箇所と、直した後も残る違い（直した docx は変換結果の ZIP に入る）。
    PDF の文字を読めなければ「出版版 PDF に合わせられませんでした」（要対応）。どちらでも、docx の段落の半分以上が PDF に
    見つからなければ「別の記事の PDF かもしれません」、照合に使わなかった PDF の文字があればその枠も出す。
    """
    from .report import pdf_actions
    return "".join(_box(a) for a in pdf_actions(res))


def unplaced_box(plan, partial="") -> str:
    """AI の回答を反映した後も、位置を決められない図表が残っているときの表示（report.unplaced_text）。なければ空文字。"""
    from .report import unplaced_text
    text = unplaced_text(plan, partial)
    return error_box(*text) if text else ""


def figure_body_box(res) -> str:
    """図の本体（画像・表）が見つからない図があるときの表示（赤い枠）。なければ空文字。"""
    from .report import figure_body_action
    return _box(figure_body_action(res))
