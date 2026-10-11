"""浮動配置の図形（テキストボックス・グループ図形）の位置の扱い。

docx には、Word で表示したときの位置（どの行が図の左上に来るか）は記録されていない。記録されているのは、
図形が結び付いている段落（アンカー段落）と、そこからの距離などである。
ここでは、その記録から機械的に確実に言えること（図の左上がアンカー段落の左上の位置にある）の判定と、
AI に位置を判断させるための説明・行数の推定を作る。

図を置く位置の規則: Word で表示したときに、図の左上の直上にある本文の文章を含む段落の直後。
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


def describe(fl: Float, layout: Optional[Layout]) -> str:
    """AI に渡す、docx に記録された位置の説明。"""
    lay = layout or Layout()
    if lay.columns > 1 and fl.width_cm > lay.column_width_cm * 1.3:
        size = f"幅 {fl.width_cm:.1f} cm・高さ {fl.height_cm:.1f} cm（2 段にまたがる）"
    else:
        size = f"幅 {fl.width_cm:.1f} cm・高さ {fl.height_cm:.1f} cm（1 段の幅）"
    if fl.h_offset_cm is not None:
        h = f"{FROM_JA.get(fl.h_from, fl.h_from)}の左端から {fl.h_offset_cm:.1f} cm"
        if fl.h_from == "column" and lay.columns > 1 and fl.h_offset_cm > lay.column_width_cm * 0.8:
            h += "（アンカー段落の段の右隣の段）"
    else:
        h = f"{FROM_JA.get(fl.h_from, fl.h_from)}の{fl.h_align or '?'}"
    if fl.v_offset_cm is not None:
        v = f"{FROM_JA.get(fl.v_from, fl.v_from)}の上端から {fl.v_offset_cm:.1f} cm 下（約 {fl.v_offset_cm / pitch(layout):.1f} 行）"
    else:
        v = f"{FROM_JA.get(fl.v_from, fl.v_from)}の{fl.v_align or '?'}"
    wrap = WRAP_JA.get(fl.wrap, fl.wrap or "不明")
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
