"""浮動配置の図形（テキストボックス・グループ図形）の位置の扱い。

docx には、Word で表示したときの位置（どの行が図の左上に来るか）は記録されていない。記録されているのは、
図形が結び付いている段落（アンカー段落）と、そこからの距離などである。
ここでは、その記録から機械的に確実に言えること（図の左上がアンカー段落の左上の位置にある）の判定と、
AI に位置を判断させるための説明・行数の推定を作る。

図を置く位置の規則: Word で表示したときに、図の左上の直上にある本文の文章を含む段落の直後。

文字だけのテキストボックス（画像・表・図表キャプションを含まないもの）が、囲み（問題文・ヒントなど。本文の <boxed-text>）か、
図に重ねた注記（矢印・点・辺の名前など。本文に出さない）かも、ここで機械的に判定する（textbox_kind。決められないものは
除外して要確認にし、AI か人に任せる）。しきい値は、手元の実際の論文 3 本（テストデータ1〜3）で確かめた（判定の対象になった
実例は図の注記だけで、囲みの側は架空の境界の例でしか確かめていない。docs/DESIGN.md の 6.2）。
"""
from __future__ import annotations

import math
import unicodedata
from typing import Optional

from .model import Float, Layout, Para

FROM_JA = {"column": "アンカー段落の段", "margin": "本文の領域", "page": "ページ", "paragraph": "アンカー段落",
           "line": "アンカーのある行", "character": "アンカーの文字", "leftMargin": "左余白", "rightMargin": "右余白",
           "topMargin": "上余白", "bottomMargin": "下余白", "insideMargin": "内側の余白", "outsideMargin": "外側の余白"}
WRAP_JA = {"wrapTopAndBottom": "上下", "wrapSquare": "四角", "wrapTight": "外周", "wrapThrough": "内部", "wrapNone": "なし（前面・背面）"}
# 配置（wp:align）の値。横は left・center・right・inside・outside、縦は top・center・bottom・inside・outside
ALIGN_JA = {"left": "左端", "center": "中央", "right": "右端", "inside": "内側", "outside": "外側", "top": "上端", "bottom": "下端"}
UNKNOWN_FROM = "基準の分からない位置"     # FROM_JA にない基準（AI 依頼文に英語の値を出さない。修正計画 W8 の 4.1）


# 文字だけのテキストボックスの判定（textbox_kind）のしきい値。文字数は空白を除いた文字の数（数式・脚注の参照は 1 字）、幅は
# 1 段の幅に対する割合（幅を読めないとき〈VML の pt 以外の単位など〉は、囲みの規則では幅の条件を使わず、注記の規則は当てはめない）
BOX_CHARS = 20        # 囲みとみなす文字数の下限
BOX_WIDTH = 0.6       # 囲みとみなす幅の下限
LABEL_CHARS = 15      # 図に重ねた注記とみなす文字数の上限
LABEL_WIDTH = 0.4     # 図に重ねた注記とみなす幅の上限（グループ図形の中では使わない）
NEAR_PARAS = 2        # 「画像の近く」: アンカー段落の前後 2 段落以内（図形の外の段落・表で数える。structure.Classifier.near_image）


def pitch(layout: Optional[Layout]) -> float:
    return layout.line_pitch_cm if layout and layout.line_pitch_cm else 0.55


def at_anchor(fl: Float, layout: Optional[Layout]) -> bool:
    """図の左上がアンカー段落の左上の位置にあるか（機械的に位置を決められる条件）。

    縦はアンカー段落の上端からのずれが 1 行未満、横はアンカー段落の段の左端から 1 cm 未満。
    このとき、図の左上の直上にある本文はアンカー段落の直前の段落の終わりなので、図はアンカー段落の前に置く。
    """
    if fl.v_from != "paragraph" or fl.v_offset_cm is None or abs(fl.v_offset_cm) >= pitch(layout):
        return False
    if fl.h_from != "column":
        return False
    return fl.h_align == "left" or (fl.h_offset_cm is not None and abs(fl.h_offset_cm) < 1.0)


def why_not_at_anchor(fl: Float, layout: Optional[Layout]) -> str:
    if fl.v_from != "paragraph":
        return f"縦の位置が{FROM_JA.get(fl.v_from, fl.v_from)}を基準にしている"
    if fl.v_offset_cm is None:
        return "縦の位置が配置（上・中央など）で指定されている"
    if abs(fl.v_offset_cm) >= pitch(layout):
        return f"図の上端がアンカー段落の上端から {fl.v_offset_cm:.1f} cm 離れている"
    return "横の位置がアンカー段落の段の左端ではない"


SPAN_WIDTH = 1.3      # 2 段にまたがる図形とみなす幅の下限（1 段の幅に対する割合。spans_columns）


def spans_columns(fl: Float, layout: Optional[Layout]) -> bool:
    """図形 fl が 2 段にまたがるか: 段組みが 2 段以上で、図形の幅が 1 段の幅の SPAN_WIDTH 倍より広い（describe の「2 段にまたがる」。
    機械的に置いた図形のうち、AI が出版版 PDF を見たときだけ位置を採るものを決める。修正計画 W8 の 6.5 の 4）。"""
    lay = layout or Layout()
    return lay.columns > 1 and fl.width_cm > lay.column_width_cm * SPAN_WIDTH


def describe(fl: Float, layout: Optional[Layout]) -> str:
    """AI に渡す、docx に記録された位置の説明（AI 依頼文の「docx の配置」）。値は日本語で書く（基準・配置・折り返しの英語の値を
    出さない。知らない値は「基準の分からない位置」「指定の位置」「不明」。修正計画 W8 の 4.1）。"""
    lay = layout or Layout()
    if spans_columns(fl, lay):
        size = f"幅 {fl.width_cm:.1f} cm・高さ {fl.height_cm:.1f} cm（2 段にまたがる）"
    else:
        size = f"幅 {fl.width_cm:.1f} cm・高さ {fl.height_cm:.1f} cm（1 段の幅）"
    if fl.h_offset_cm is not None:
        h = f"{FROM_JA.get(fl.h_from, UNKNOWN_FROM)}の左端から {fl.h_offset_cm:.1f} cm"
        if fl.h_from == "column" and lay.columns > 1 and fl.h_offset_cm > lay.column_width_cm * 0.8:
            h += "（アンカー段落の段の右隣の段）"
    else:
        h = f"{FROM_JA.get(fl.h_from, UNKNOWN_FROM)}の{ALIGN_JA.get(fl.h_align, '指定の位置')}"
    if fl.v_offset_cm is not None:
        v = f"{FROM_JA.get(fl.v_from, UNKNOWN_FROM)}の上端から {fl.v_offset_cm:.1f} cm 下（約 {fl.v_offset_cm / pitch(layout):.1f} 行）"
    else:
        v = f"{FROM_JA.get(fl.v_from, UNKNOWN_FROM)}の{ALIGN_JA.get(fl.v_align, '指定の位置')}"
    wrap = WRAP_JA.get(fl.wrap, "不明")
    return f"{size}。横: {h}。縦: {v}。文字列の折り返し: {wrap}"


def para_lines(p: Para, layout: Optional[Layout]) -> int:
    """段落が 1 段の中で占める行数の推定（全角 1 文字 = 1、半角 = 0.5、字下げ 1 文字として、1 行の文字数で割る）。"""
    cpl = layout.chars_per_line if layout and layout.chars_per_line else 24.0
    width = 1.0
    for a in p.atoms:
        if a.kind == "text":
            width += sum(0.5 if unicodedata.east_asian_width(ch) in ("Na", "H") else 1.0 for ch in a.text)
        elif a.kind == "image" and a.image is not None and a.image.inline:
            return max(1, math.ceil(a.image.height_cm / pitch(layout)))
        else:
            width += 2.0
    return max(1, math.ceil(width / cpl))


def column_cm(layout: Layout | None) -> float | None:
    """1 段の幅（cm）。段組みの設定がなければ本文の幅、それもなければ None（幅の割合を求めない。textbox_kind）。"""
    if layout and layout.column_width_cm:
        return layout.column_width_cm
    if layout and layout.text_width_cm:
        return layout.text_width_cm
    return None


def box_lines(paras, width_cm: float | None, layout: Layout | None) -> int:
    """テキストボックス（囲み）の中の行数の推定。

    幅が分かれば、1 行の字数（幅 / 1 字の幅〈1 段の幅 / 1 行の字数〉）で、文字のある段落ごとに割って足す（para_lines と同じく
    全角 1・半角 0.5）。幅か 1 段の幅が分からなければ、文字のある段落の数。
    """
    texts = [p for p in paras if p.plain().strip()]
    col = column_cm(layout)
    if width_cm is None or not col:
        return len(texts)
    cpl = layout.chars_per_line if layout and layout.chars_per_line else 24.0
    per = max(1.0, width_cm / (col / cpl))
    lines = 0
    for p in texts:
        n = sum(0.5 if unicodedata.east_asian_width(ch) in ("Na", "H") else 1.0 for ch in p.plain())
        lines += max(1, math.ceil(n / per))
    return lines


def textbox_kind(chars: int, width_cm: float | None, lines: int, near_image: bool, group: bool,
                 layout: Layout | None) -> tuple:
    """文字だけのテキストボックスを、囲み（box）・図に重ねた注記（label）・決められない（undecided）・空白だけ（blank）に分ける。

    chars: 空白を除いた文字の数（数式・脚注の参照は 1 字）。width_cm: 幅（読めなければ None）。lines: 行数の推定（box_lines）。
    near_image: 画像の近く（structure.Classifier.near_image）。group: グループ図形・描画キャンバスの中。
    戻り値: (種類, 根拠の説明)。根拠は判断の一覧・レポートの 3 章・AI 依頼文に出す。規則（上から順に）:
      1. 文字がない（空白だけ）→ blank
      2. グループ図形の中: 15 字以下なら label（図そのものの中の文字）、それより長ければ undecided（幅は使わない）
      3. 15 字以下・画像の近く・幅が 1 段の 0.4 以下 → label（幅か 1 段の幅を読めなければ当てはめない。黙って除外する label に
         倒さず、undecided にして知らせる。修正計画の付録の D1「VML の width が pt 以外のとき、label に倒れない」）
      4. 20 字以上・幅が 1 段の 0.6 以上（幅を読めなければ問わない）で、画像から離れているか推定 2 行以上 → box
      5. それ以外 → undecided（迷ったら、図の注記を本文に混ぜないよう除外して知らせる）
    """
    if chars <= 0:
        return "blank", "空白だけ"
    col = column_cm(layout)
    ratio = width_cm / col if (width_cm is not None and col) else None
    if width_cm is None:
        size = "幅は読めない"
    elif ratio is None:
        size = f"幅 {width_cm:.1f} cm"
    else:
        size = f"幅 {width_cm:.1f} cm（1 段の {ratio:.2f} 倍）"
    where = "グループ図形の中" if group else ("画像の近く" if near_image else "画像から離れている")
    why = f"文字 {chars} 字・{size}・{where}・推定 {lines} 行"
    if group:
        return ("label" if chars <= LABEL_CHARS else "undecided"), why
    if chars <= LABEL_CHARS and near_image and ratio is not None and ratio <= LABEL_WIDTH:
        return "label", why
    if chars >= BOX_CHARS and (ratio is None or ratio >= BOX_WIDTH) and (not near_image or lines >= 2):
        return "box", why
    return "undecided", why


def estimate_top_left(fl: Float, layout: Optional[Layout], seq: list, prev_src: str = "") -> Optional[tuple]:
    """図の左上の直上にある本文の段落の推定（アンカー段落と同じ段で、上から行数を数える）。

    seq: アンカー段落から後の本文の段落（浮動配置の図形の中の段落を除く）。prev_src: アンカー段落の直前の段落。
    戻り値: (段落 ID, 説明) または None（縦の位置がアンカー段落基準でない・別の段にある、など推定できないとき）
    """
    if fl.v_from != "paragraph" or fl.v_offset_cm is None or not seq:
        return None
    lay = layout or Layout()
    if fl.h_from == "column" and lay.columns > 1 and (fl.h_offset_cm or 0) > lay.column_width_cm * 0.8:
        return None
    target = fl.v_offset_cm / pitch(layout)
    acc = 0
    counts = []
    answer = None
    for k, p in enumerate(seq):
        n = para_lines(p, layout)
        counts.append(f"[{p.src}] {n} 行（{acc}〜{acc + n} 行目）")
        if answer is None:
            if target < acc + 0.5:
                answer = seq[k - 1].src if k > 0 else prev_src
            elif target < acc + n:
                answer = p.src
        acc += n
        if answer is not None and acc > target + 3:
            break
    if answer is None:
        return None
    detail = (f"図の上端はアンカー段落の上端から約 {target:.1f} 行下。アンカー段落から後の段落の推定行数: "
              + "、".join(counts))
    return answer, detail
