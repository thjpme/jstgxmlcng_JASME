"""作業する人が入れる図・表の画像の受け取り（修正計画 W1）。

ツールは docx の中の画像を書き出さない（変換・切り取りもしない）。画像は作業する人が出版版 PDF などから用意して入れる。
ここは、入れられた画像の中身の確かめ（`check_user_image`）、入れた画像・持ち越しの記録の型（`SlotImage` など）、
アップロードされたファイル名と画像の置き場所の照合（`match_names`）だけを持つ。
"""
from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------- 作業する人が入れる画像（修正計画 W1 の 2.6）
# 図・表の画像は、作業する人が出版版 PDF などから用意して入れる。ツールは docx の中の画像を書き出さず、入れた画像は中身を
# 確かめるだけで、バイト列をそのまま Graphics/ に入れる（向き・圧縮・透過を変えない。C085）。J-STAGE が受け付けるのは jpg・gif・png。
@dataclass(eq=False)
class SlotImage:
    """画像の置き場所 1 つと、そこに入れた画像（pipeline.Result.images の要素。XML の順）。

    key は置き場所の幹（article.ImageSlot.key）、name は Graphics/ の中の名前（「{記事識別子}_{幹}.{拡張子}」。拡張子は入れた画像の
    形式で、入れる前は .png）、kind・label は置き場所の種類と「図3」「表1」、caption はキャプションの文字（なければ ""）、location は
    場所の文（report.slot_where）。status: missing（未）/ user（入れた）/ skipped（入れない。キャプションのない画像だけ）/
    unused（任意の置き場所で、入れていない）。source_name は入れた画像の元のファイル名、format は png・jpg・gif、size は (幅, 高さ)
    （読めなければ None）、bytes は大きさ（バイト）、sha1 は中身の SHA-1、note は置き場所の備考（article.ImageSlot.note）。
    """
    key: str
    name: str
    kind: str = "fig"
    label: str = ""
    caption: str = ""
    location: str = ""
    status: str = "missing"
    source_name: str = ""
    format: str = ""
    size: tuple | None = None
    bytes: int = 0
    sha1: str = ""
    note: str = ""


@dataclass(eq=False)
class KeptImage:
    """変換し直す前に覚えておく、入れた画像（pipeline.kept_images）。変換し直した後に pipeline.reapply_images が、同じ図かを確かめて入れ直す。

    key は置き場所の幹、kind は fig・table・nocap・optional、source_name は元のファイル名、data は中身（バイト列のまま）、
    caption は入れたときのキャプションの文字、body はその本体（structure.caption_body。番号を除いた文字）、where は入れたときの
    場所の段落の先頭 20 字（キャプションのない画像の照合に使う）、skipped は「入れない」とした置き場所か、article_id は記事識別子
    （巻と最初のページ）、layout は入れたときの置き場所の並び全体（pipeline._slot_layout。幹・種類・本体・場所・docx の画像の中身。どの KeptImage も同じ）。
    """
    key: str
    kind: str
    source_name: str
    data: bytes
    caption: str
    body: str
    where: str
    skipped: bool
    article_id: str
    layout: tuple = ()


@dataclass(eq=False)
class DroppedImage:
    """持ち越せなかった前の画像（pipeline.Result.images_dropped）。別の図の画像を入れないために入れなかったもの。

    key は前の置き場所の幹、source_name は元のファイル名、caption は前のキャプションの文字、why は入れなかった理由の言い方、
    suggest は、前のキャプションの本体と本体が同じ図が今ちょうど 1 つあるときのその幹か、本体が少し変わり番号もずれた図で、互いにただ 1 つの
    いちばん近い組（割合 0.8 以上）の今の図の幹（なければ ""。示すだけで入れない）、sha1 は前の画像の中身の SHA-1
    （report.images_dropped が、suggest の置き場所にこの画像そのものが入ったかを見る。作業する人がその置き場所に画像を入れ直したときも
    済みにする）、other_article は、記事識別子が変わった
    （別の論文の）ときの前の記事識別子（同じ論文なら ""。手順 images では行を並べず 1 行で知らせる）。
    """
    key: str
    source_name: str
    caption: str
    why: str
    suggest: str = ""
    sha1: str = ""
    other_article: str = ""


@dataclass(eq=False)
class ChangedImage:
    """キャプションが少し変わった図に入れ直した画像（pipeline.Result.images_changed。図と画像が合っているかを確かめてもらう）。"""
    key: str
    source_name: str
    old_caption: str
    new_caption: str


# 中身の先頭のバイト → 形式（受け付けるもの）と、断るときの形式の名前
_ACCEPTED = ((b"\x89PNG\r\n\x1a\n", "png"), (b"\xff\xd8\xff", "jpg"), (b"GIF87a", "gif"), (b"GIF89a", "gif"))
_REFUSED = ((b"%PDF-", "PDF"), (b"II*\x00", "TIFF"), (b"MM\x00*", "TIFF"), (b"BM", "BMP"))


def image_format(data: bytes) -> str:
    """画像の中身（先頭のバイト）から決めた形式: png・jpg・gif（受け付けない形式なら ""）。拡張子は見ない（C076）。"""
    return next((fmt for magic, fmt in _ACCEPTED if data.startswith(magic)), "")


def check_user_image(data: bytes, name: str = "") -> tuple:
    """作業する人が入れる画像の確かめ。戻り値: (形式〈png・jpg・gif〉, (幅, 高さ)〈読めなければ None〉)。

    形式は中身の先頭のバイトで決める（拡張子が違っていてもよい）。PNG・JPEG・GIF でないもの・0 バイトは、理由を言って ValueError
    （文は修正計画 W1 の 4.2。name は文に出すファイル名）。幅と高さは Pillow で読むだけで、保存し直さない（中身は変えない）。
    """
    label = name or "選んだファイル"
    if not data:
        raise ValueError(f"「{label}」は中身が空（0 バイト）です。")
    fmt = image_format(data)
    if not fmt:
        what = next((w for magic, w in _REFUSED if data.startswith(magic)), "")
        if not what and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            what = "WebP"
        raise ValueError(f"「{label}」は PNG・JPEG・GIF の画像ではありません（中身は {what or '分からない形式'} です）。"
                         "図の部分を PNG か JPEG の画像にして入れてください。")
    size = None
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            size = tuple(im.size)
    except Exception:  # noqa: BLE001
        size = None
    return fmt, size


RE_ARTICLE_PREFIX = re.compile(r"^([0-9a-z]+_[0-9a-z]+)_(.+)$")        # 記事識別子の付いた名前（29_55_fig03・31_e5_fig03。巻と最初のページは英数字）
RE_FIG_ALIAS = re.compile(r"^(?:figure|fig|図)[\s_\-]*0*(\d+)(?:[\-‐–](\d+))?$")
RE_TAB_ALIAS = re.compile(r"^(?:table|tab|表)[\s_\-]*0*(\d+)(?:[\-‐–](\d+))?$")


def _stem(name: str) -> str:
    """ファイル名の拡張子を除き、NFKC にして小文字にしたもの（名前の照らし合わせ用）。"""
    base = unicodedata.normalize("NFKC", Path(name).name).strip()
    if "." in base:
        base = base.rsplit(".", 1)[0]
    return base.strip().lower()


def match_names(names, slots, article_id: str) -> tuple:
    """まとめて入れた画像のファイル名を、画像の置き場所（key・kind を持つもの。ImageSlot か SlotImage）の幹に合わせる。

    受け付ける名前（拡張子は問わない。NFKC にし、大文字・小文字を区別しない）: 幹そのもの（fig03・tab01・img3fa9c2・fig04_2）、
    記事識別子の付いた名前（29_55_fig03）、図・表の番号からの別名（fig3・図3・Figure3・fig1-2・表1・tab1・table1）。番号からの別名は、
    その番号の置き場所が 1 つだけのとき（fig04_2 がなければ）に受け付ける。記事識別子の形（{英数字}_{英数字}_。31_e5_ など）で始まり、
    この記事の識別子 article_id と違う名前は受け付けない（別の論文のフォルダの使い回しで、別の論文の画像が黙って入らないように）。
    戻り値: ({幹: ファイル名}, 合わなかった名前の一覧, 重なった名前 [(幹, [ファイル名, …])])。同じ幹に 2 つ以上合ったファイルは、
    どれも {幹: ファイル名} に入れない（黙って 1 つを選ばない）。
    """
    keys = {s.key.lower(): s.key for s in slots if s.key}
    found, unmatched = {}, []
    for name in names:
        stem = _stem(name)
        own = str(article_id).lower() + "_"
        m = RE_ARTICLE_PREFIX.match(stem)
        if stem.startswith(own) and len(stem) > len(own):
            stem = stem[len(own):]
        elif m:
            unmatched.append(name)
            continue
        key = keys.get(stem)
        if key is None:
            for regex, prefix in ((RE_FIG_ALIAS, "fig"), (RE_TAB_ALIAS, "tab")):
                a = regex.match(stem)
                if a:
                    cand = f"{prefix}{int(a.group(1)):02d}" + (f"-{int(a.group(2))}" if a.group(2) else "")
                    if cand in keys and f"{cand}_2" not in keys:
                        key = keys[cand]
                    break
        if key is None:
            unmatched.append(name)
            continue
        found.setdefault(key, []).append(name)
    matched = {k: v[0] for k, v in found.items() if len(v) == 1}
    clashes = [(k, v) for k, v in found.items() if len(v) > 1]
    return matched, unmatched, clashes
