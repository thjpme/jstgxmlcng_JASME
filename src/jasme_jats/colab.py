"""Colab ノートブックで使う表示部品（HTML）。

ノートブックのセルを短く保ち、テストできるようにするため、表示用の HTML はここで作る。
Colab の出力欄は暗い配色のこともあるので、枠の中の文字色・背景色は明示する。
"""
from __future__ import annotations

import html
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
    """巻と最初のページが前の論文と同じ（出力のファイル名と DOI が前の論文と同じになる）か。"""
    return all(str(current.get(k, "")).strip() and current.get(k) == previous.get(k) for k in ("volume", "fpage"))


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


def missing_images_box(res) -> str:
    """画像ファイルを用意できなかった図（Word の図形で描かれた図など）があるときの表示（赤い枠）。なければ空文字。"""
    from .report import graphics_dir, images_to_prepare
    need = images_to_prepare(res)
    if not need:
        return ""
    items = "\n".join(f"・{name}: {cap or '（キャプションなし）'}（{why}）" for name, cap, why in need)
    return error_box(
        f"画像ファイルを用意できなかった図が {len(need)} 件あります",
        "Word の図形で描かれた図などは、docx に画像ファイルがないので、変換で画像を作れません。画像がないままでは、その図が "
        "J-STAGE の画面に表示されません。手順 7「足りない画像をアップロード」で、図ごとにその図の画像を選んでください"
        f"（ファイル名は何でもかまいません）。手元で入れるときは、次の名前の画像を {res.zip_path.name} の中の "
        f"{graphics_dir(res)} に入れます（レポートの冒頭と 9 章）。\n{items}")


def pdf_diff_box(res) -> str:
    """出版版 PDF と文字が違う箇所があるときの表示（赤い枠）。なければ空文字。"""
    pc = res.pdf_check
    if pc is None or not pc.ok or not pc.diffs:
        return ""
    items = "\n".join(f"・{d.context}（docx「{d.docx}」/ PDF「{d.pdf}」）" for d in pc.diffs[:10])
    more = f"\n…ほか {len(pc.diffs) - 10} 件" if len(pc.diffs) > 10 else ""
    return error_box(
        f"出版版 PDF と文字が違う箇所が {len(pc.diffs)} 件あります（要確認）",
        "受け取った docx が、著者校正を経た最終版ではない可能性があります。XML は docx の文字のままです。PDF と照らして確認し、"
        "PDF が正しければ docx を直して、手順 2 からやり直してください（レポートの 13 章。英数字・記号の全角・半角の違いだけは"
        + ("PDF に合わせました）。" if pc.apply else "、設定により PDF に合わせていません）。") + f"\n{items}{more}")


def unplaced_box(plan) -> str:
    """AI の回答を反映した後も、位置を決められない図表が残っているときの表示。なければ空文字。"""
    if not plan.unplaced_floats:
        return ""
    return error_box(
        "位置を決められなかった図表があります（本文の冒頭に仮に置いています。手作業で直してください）",
        f"AI の回答に、次の図表の位置（placements）の指定がないか、指定が検証で採用されませんでした: "
        f"{', '.join(plan.unplaced_floats)}（レポートの 2 章・3 章）。これらは本文の冒頭に仮に置いているので、登載の前に、"
        "XML の中で手作業で正しい位置（Word で表示したときに、図の左上の直上にある本文の段落の後）に移してください。"
        "AI に出し直してもらう場合は、手動モードではチャットで「位置を決められなかった図表をすべて placements に書いて、"
        "回答の書き方に従って出し直してください」と頼んで手順 6 で貼り付け直し、API モードでは手順 5 をもう一度実行してください。")
