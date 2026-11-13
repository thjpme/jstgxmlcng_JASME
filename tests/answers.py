"""テストの AI の回答（手動モードで貼り付ける JSON の文字）を、意味で書いた項目から作る（修正計画 W8 の手順 9）。

テストは回答の JSON を手で組まず、answer() に「どの図形をどの段落の後ろに置くか」「どの文字をどこにリンクするか」などを
渡す。回答の形（依頼文が求める JSON の項目）を変えるときは、このファイルの写し方だけを直せば、テストはそのまま新しい形の
回答になる（手順 10）。回答の形そのもの（parse_response・split_ops が読む形、壊れた回答）を試すテストは、ここを使わずに
手で書く。

今の形（手順 9 の時点）: {"placements": [...], "operations": [...], "notes": [...]}。

- placements（図・表の位置）: (図形の ID, after) か (図形の ID, after, reason, confidence)。items は空の一覧 [] で書く
  （組み合わせは変換ツールが決める。修正計画 W1 の 2.7）。
- boxes（テキストボックスの種類）: (テキストボックスの ID, kind, after[, reason, confidence])。kind は "囲み" か "図の注記"
  （今の形では placements の items の kind box・label）。図の注記の after は ""。
- boundaries（注の区切り・資料の始まり）: (段落 ID, kind[, reason, confidence])。kind は ai_assist.BOUNDARY_KINDS の語
  （注の始まり・注の続き・資料の見出し・英文要旨の続き・資料の本文）。今の形では set_role（fn_start・p・app_heading・abstract）。
- links（リンク）: (kind, 段落 ID, text, occurrence, target[, reason, confidence])。kind は LINK_KINDS の語
  （文献・図・表・注・式。今の形では link_citation など）。
- names（姓と名の境目）: (段落 ID, surname, given[, reason, confidence])。今の形では split_name。
- style_fixes（Word のスタイルで直す提案）: (段落 ID, role[, reason, confidence])。role は今の set_role の役割名
  （sec1・quote・exclude など。新しい形では、その役割のスタイル名と直し方に写す）。今の形では set_role。
- notes: 文字列の一覧。

operations の並びは links・names・boundaries・style_fixes の順（それぞれの中は渡した順）。reason・confidence を省いた項目は
DEFAULT_REASON・DEFAULT_CONFIDENCE（placements・boxes は DEFAULT_PLACE_CONFIDENCE）。
"""
from __future__ import annotations

import json

from jasme_jats.ai_assist import BOUNDARY_KINDS

DEFAULT_REASON = "試験"
DEFAULT_CONFIDENCE = "高"
DEFAULT_PLACE_CONFIDENCE = "中"
# links の kind の語 → 今の操作の名前
LINK_KINDS = {"文献": "link_citation", "図": "link_figure", "表": "link_table", "注": "link_note", "式": "link_formula"}
# boxes の kind の語 → 今の placements の items の kind
BOX_KINDS = {"囲み": "box", "図の注記": "label"}


def _tail(item, n, confidence=DEFAULT_CONFIDENCE):
    """項目の n 個目より後ろ（省いてよい reason・confidence）を補う。"""
    item = tuple(item)
    if not n <= len(item) <= n + 2:
        raise ValueError(f"項目の数が違う: {item!r}")
    rest = item[n:] + (DEFAULT_REASON, confidence)[len(item) - n:]
    return item[:n], rest[0], rest[1]


def _op(op, src, reason, confidence, text="", occurrence=1, target="", role="", surname="", given=""):
    return {"op": op, "src": src, "text": text, "occurrence": occurrence, "target": target, "role": role, "image": "",
            "mathml": "", "surname": surname, "given": given, "reason": reason, "confidence": confidence}


def placement(fid, after, reason=DEFAULT_REASON, confidence=DEFAULT_PLACE_CONFIDENCE) -> dict:
    """図形 fid を段落 after の後ろに置く指定（今の形の placements の要素）。"""
    return {"float": fid, "after": after, "items": [], "reason": reason, "confidence": confidence}


def box(xid, kind, after, reason=DEFAULT_REASON, confidence=DEFAULT_PLACE_CONFIDENCE) -> dict:
    """テキストボックス xid の種類（囲み・図の注記）と位置の指定（今の形の placements の要素）。"""
    if kind not in BOX_KINDS:
        raise ValueError(f"boxes の kind は {'・'.join(BOX_KINDS)} のどれか: {kind!r}")
    return {"float": xid, "after": after, "items": [{"kind": BOX_KINDS[kind], "caption": [], "body": []}],
            "reason": reason, "confidence": confidence}


def boundary(src, kind, reason=DEFAULT_REASON, confidence=DEFAULT_CONFIDENCE) -> dict:
    """注の区切り・資料の始まりの直し（今の形の set_role の操作）。"""
    if kind not in BOUNDARY_KINDS:
        raise ValueError(f"boundaries の kind は {'・'.join(BOUNDARY_KINDS)} のどれか: {kind!r}")
    return _op("set_role", src, reason, confidence, role=BOUNDARY_KINDS[kind])


def link(kind, src, text, occurrence, target, reason=DEFAULT_REASON, confidence=DEFAULT_CONFIDENCE) -> dict:
    """リンクの指定（今の形の link_citation などの操作）。"""
    if kind not in LINK_KINDS:
        raise ValueError(f"links の kind は {'・'.join(LINK_KINDS)} のどれか: {kind!r}")
    return _op(LINK_KINDS[kind], src, reason, confidence, text=text, occurrence=occurrence, target=target)


def name(src, surname, given, reason=DEFAULT_REASON, confidence=DEFAULT_CONFIDENCE) -> dict:
    """姓と名の境目の指定（今の形の split_name の操作）。"""
    return _op("split_name", src, reason, confidence, surname=surname, given=given)


def style_fix(src, role, reason=DEFAULT_REASON, confidence=DEFAULT_CONFIDENCE) -> dict:
    """Word のスタイルで直す提案（今の形の set_role の操作。区切りの 5 つ以外の役割）。"""
    return _op("set_role", src, reason, confidence, role=role)


def data(placements=(), boxes=(), boundaries=(), links=(), names=(), style_fixes=(), notes=(), base=None) -> dict:
    """answer() と同じ回答を、JSON にする前の dict で返す。base（回答の dict か JSON の文字）があれば、その一覧の後ろに足す。"""
    if isinstance(base, str):
        base = json.loads(base)
    base = base or {}
    pls = [placement(*h, r, c) for h, r, c in (_tail(x, 2, DEFAULT_PLACE_CONFIDENCE) for x in placements)]
    pls += [box(*h, r, c) for h, r, c in (_tail(x, 3, DEFAULT_PLACE_CONFIDENCE) for x in boxes)]
    ops = [link(*h, r, c) for h, r, c in (_tail(x, 5) for x in links)]
    ops += [name(*h, r, c) for h, r, c in (_tail(x, 3) for x in names)]
    ops += [boundary(*h, r, c) for h, r, c in (_tail(x, 2) for x in boundaries)]
    ops += [style_fix(*h, r, c) for h, r, c in (_tail(x, 2) for x in style_fixes)]
    return {"placements": list(base.get("placements", [])) + pls, "operations": list(base.get("operations", [])) + ops,
            "notes": list(base.get("notes", [])) + list(notes)}


def answer(placements=(), boxes=(), boundaries=(), links=(), names=(), style_fixes=(), notes=(), base=None) -> str:
    """意味で書いた項目から、手動モードで貼り付ける回答の JSON の文字を作る（項目の書き方はモジュールの説明）。
    何も渡さなければ、何も指定しない回答（{"placements": [], "operations": [], "notes": []}）。"""
    return json.dumps(data(placements, boxes, boundaries, links, names, style_fixes, notes, base), ensure_ascii=False)
