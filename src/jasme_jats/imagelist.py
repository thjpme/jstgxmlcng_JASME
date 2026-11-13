"""取り違えの確かめの一覧（図の確かめ.html）を作る（修正計画 W1 の 4.3）。

図・表の画像は作業する人が用意して入れるので、図番号・キャプションと入れた画像が合っているかを目で確かめる一覧を、出力フォルダ
（記事フォルダの外。アップロード用の ZIP に入らない）に別の HTML ファイル「{記事識別子}_図の確かめ.html」として書く。
行のデータは report.image_rows（9 章・画面・コマンドラインと同じ）を使い、ここでは見せ方だけを決める。docx 由来の文字は
すべて HTML のエスケープをする（レポート〈Markdown〉は生の HTML を使わない決まりなので、HTML は別のファイルにする）。
"""
from __future__ import annotations

import base64
import html
import io
from pathlib import Path

from .package import article_dir
from .report import (DECORATION_JA, OPTIONAL_CAPTION, IMAGE_STATUS_JA, LOST_IMAGES_HOW, LOST_IMAGES_WHY, image_rows, images_changed,
                     images_dropped, images_progress, lost_image_label)

OBJECT_MARK = "\ufffc"          # 数式などの図形の位置（Para.plain の代わりの文字）
OBJECT_SHOWN = "［数式など］"     # HTML の表示だけで、この文字の代わりに出す（XML の文字ではない）
THUMB_PX = 240                  # embed=True の縮小の幅（px）。表示用だけで、ZIP の画像は変えない

CSS = """
:root { --bg:#fff; --fg:#1d1d1f; --mute:#6b6b70; --line:#d5d5da; --head:#f0f0f4; --warn:#fff3cd; }
@media (prefers-color-scheme: dark) { :root { --bg:#1b1b1f; --fg:#ececf0; --mute:#a0a0a8; --line:#3a3a42; --head:#2a2a32; --warn:#4a4020; } }
body { background:var(--bg); color:var(--fg); font:14px/1.6 system-ui,"Hiragino Sans","Noto Sans JP",sans-serif; margin:0; padding:16px; }
h1 { font-size:20px; margin:0 0 4px; } h2 { font-size:16px; margin:28px 0 6px; }
p.lead { color:var(--mute); margin:0 0 16px; }
.wrap { overflow-x:auto; }
table { border-collapse:collapse; width:100%; min-width:760px; }
th, td { border:1px solid var(--line); padding:6px 8px; vertical-align:top; text-align:left; }
th { background:var(--head); white-space:nowrap; }
td.img { min-width:120px; } td.img img { max-width:240px; height:auto; display:block; border:1px solid var(--line); }
td.note { background:var(--warn); } td.note:empty { background:transparent; }
.mute { color:var(--mute); } .bad { font-weight:bold; }
"""


def _e(text) -> str:
    return html.escape(str(text or ""), quote=True)


def _shown(text) -> str:
    """docx の文字を HTML に出す文字列（エスケープ済み）。数式などの位置の文字は、表示だけ分かる言葉にする。"""
    return _e(str(text or "").replace(OBJECT_MARK, OBJECT_SHOWN))


def _thumb(path: Path, fmt: str) -> str:
    """表示用の縮小（data URI）。読めなければ ""。"""
    try:
        from PIL import Image
        with Image.open(path) as im:
            im.load()
            if im.width > THUMB_PX:
                im = im.resize((THUMB_PX, max(1, round(im.height * THUMB_PX / im.width))))
            buf = io.BytesIO()
            if fmt in ("jpg", "jpeg"):
                im.convert("RGB").save(buf, "JPEG", quality=80)
                mime = "image/jpeg"
            else:
                im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB").save(buf, "PNG")
                mime = "image/png"
        return f"data:{mime};base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:   # 表示用なので、読めないときは画像なしで出す
        return ""


def _image_cell(res, row, embed: bool) -> str:
    """入れた画像の列。入れていなければ状態の言葉、入れていれば画像（embed なら埋め込み、そうでなければ Graphics/ への相対リンク）。"""
    if row.status != "user":
        return f'<td class="img mute">{_e(IMAGE_STATUS_JA.get(row.status, row.status))}</td>'
    adir = article_dir(Path(""), res.journal, res.meta).as_posix()
    rel = f"{adir}/Graphics/{row.name}"
    if embed:
        src = _thumb(res.zip_path.parent / rel, row.image.format if row.image is not None else "")
        if src:
            return f'<td class="img"><img src="{src}" alt="{_e(row.name)}"><span class="mute">{_e(row.name)}</span></td>'
        return f'<td class="img">{_e(row.name)}<br><span class="mute">（画像を読めませんでした）</span></td>'
    return f'<td class="img"><img src="{_e(rel)}" alt="{_e(row.name)}" loading="lazy"><span class="mute">{_e(row.name)}</span></td>'


def _table(heads, rows) -> str:
    """見出しと行（セルは HTML の文字列。エスケープ済み）の表。"""
    out = ['<div class="wrap"><table>', "<tr>" + "".join(f"<th>{_e(h)}</th>" for h in heads) + "</tr>"]
    out += ["<tr>" + "".join(cells) + "</tr>" for cells in rows]
    out.append("</table></div>")
    return "\n".join(out)


def check_html(res, embed: bool = False) -> str:
    """取り違えの確かめの一覧の HTML（文字列）。embed が偽なら画像は記事フォルダの Graphics/ への相対リンク（出力フォルダに置いて開く）、
    真なら縮小した画像を埋め込む（画面に表示する用）。行は report.image_rows と同じ数・同じ並び。"""
    aid = res.meta.article_id(res.journal)
    left, total = images_progress(res)
    rows = image_rows(res)
    P = [f'<!doctype html>\n<html lang="ja"><head><meta charset="utf-8">'
         f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>図の確かめ</title><style>{CSS}</style></head><body>',
         f"<h1>図の確かめ（{_e(aid)}）— 入れた画像 {total - left}/{total} 枚</h1>",
         '<p class="lead">図番号・キャプションと、入れた画像が合っているかを確かめてください。画像は、J-STAGE に登載する ZIP に入るものです。</p>']
    if rows:
        body = []
        for row in rows:
            cap = (f"{_shown(row.label)}　" if row.label else "") + (_shown(row.caption.strip()) or ('<span class="mute">' + (OPTIONAL_CAPTION if row.kind == "optional" else "（キャプションなし）") + '</span>' if not row.label else ""))
            detail = _e(row.detail)
            body.append([f"<td>{_e(row.key)}</td>", f"<td>{cap}</td>", f"<td>{_shown(row.where)}</td>", f"<td>{_e(row.place)}</td>",
                         _image_cell(res, row, embed), f"<td>{detail}</td>", f'<td class="note">{_shown(row.note)}</td>'])
        P.append(_table(["名前", "図・表とキャプション", "場所", "位置の決め方", "入れた画像", "元のファイル名・形式・大きさ", "備考"], body))
    else:
        P.append("<p>画像の要る図・表はありません。</p>")
    dropped, changed = images_dropped(res), images_changed(res)
    if dropped:
        P.append("<h2>入れ直しが要る前の画像</h2>")
        P.append(_table(["前の名前", "前のキャプション", "元のファイル名", "今の図・理由"],
                        [[f"<td>{_e(d.key)}</td>", f"<td>{_shown(d.caption.strip() or '（キャプションなし）')}</td>", f"<td>{_e(d.source_name)}</td>",
                          f"<td>{_e(f'今の {d.suggest} の画像と思われます' if d.suggest else d.why)}</td>"] for d in dropped]))
    if changed:
        P.append("<h2>キャプションが変わった図に入れ直した画像</h2>")
        P.append(_table(["名前", "前のキャプション", "今のキャプション", "元のファイル名"],
                        [[f"<td>{_e(c.key)}</td>", f"<td>{_shown(c.old_caption.strip())}</td>", f"<td>{_shown(c.new_caption.strip())}</td>",
                          f"<td>{_e(c.source_name)}</td>"] for c in changed]))
    decos = getattr(res, "decorations", [])
    drawn = [d for d in decos if d.figure]
    if drawn:
        labels = {i.key: i.label for i in res.images}
        P.append("<h2>図形で描いた図（図の本体）</h2>")
        P.append("<p>次の図は、Word の図形（文字の図形の集まりなど）で描かれていて、docx に画像がありません。図の置き場所に、出版版 PDF から"
                 "切り取った画像を 1 枚入れます。</p><ul>")
        for d in drawn:
            label = labels.get(d.figure, "") or d.figure
            P.append(f"<li>{_e(label)}（{_e(d.figure)}）: {_e(DECORATION_JA.get(d.kind, d.kind))}（{_e(d.image.image_id)}。{_shown(d.where)}）。"
                     f"画像の場所には数えず、{_e(label)} の置き場所に 1 枚入れる</li>")
        P.append("</ul>")
    plain = [d for d in decos if not d.figure]
    if plain:
        P.append("<h2>画像の場所に数えなかった図形（飾り）</h2>")
        P.append("<p>次の図形は、枠・白い四角・線・矢印・文字の図形だけの集まりなので、画像の場所に数えていません（XML には出ません）。</p>")
        P.append(_table(["図形", "種類", "場所"],
                        [[f"<td>{_e(d.image.image_id)}</td>", f"<td>{_e(DECORATION_JA.get(d.kind, d.kind))}</td>", f"<td>{_shown(d.where)}</td>"]
                         for d in plain]))
    if res.lost_images:
        P.append('<h2>画像を入れる場所を作れなかった画像（要対応）</h2>')
        P.append(f'<p class="bad">{_e(LOST_IMAGES_WHY + LOST_IMAGES_HOW)}</p><ul>')
        P += [f"<li>{_shown(lost_image_label(li))}: {_e(li.reason)}</li>" for li in res.lost_images]
        P.append("</ul>")
    P.append("</body></html>")
    return "\n".join(P)


FRAME_MAX_PX = 760     # check_frame の高さの上限（px）。超える分は枠の中でスクロールする


def check_frame(res) -> str:
    """画面（1 画面版・ノートブック）に出す、図の確かめの一覧。check_html(res, embed=True) を iframe（srcdoc）に入れたもの。

    一覧は 1 つの HTML の文書（body・table などの CSS を持つ）なので、画面の他の部分の見た目を変えないよう iframe で分ける。
    画像は縮小して埋め込む（表示用だけで、ZIP の画像は変えない）。画像の要る図・表も、入れた画像もなければ空文字。
    """
    if not image_rows(res):
        return ""
    height = min(FRAME_MAX_PX, 260 + 150 * len(image_rows(res)))
    return (f'<iframe srcdoc="{_e(check_html(res, embed=True))}" title="図の確かめ" '
            f'style="width:100%;height:{height}px;border:1px solid #d5d5da;border-radius:6px"></iframe>')


def check_name(res) -> str:
    """図の確かめの一覧のファイル名（出力フォルダの中）。"""
    return f"{res.meta.article_id(res.journal)}_図の確かめ.html"


def write_check(res) -> Path:
    """図の確かめの一覧を出力フォルダ（記事フォルダの外）に書く。変換のたびと、画像を入れるたびに作り直す。res.check_path に持つ。"""
    path = res.zip_path.parent / check_name(res)
    path.write_text(check_html(res), encoding="utf-8")
    res.check_path = path
    return path
