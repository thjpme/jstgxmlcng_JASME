"""テストの AI の回答（手動モードで貼り付ける JSON の文字）を、意味で書いた項目から作る（修正計画 W8 の手順 9・10）。

テストは回答の JSON を手で組まず、answer() に「どの図形をどの段落の後ろに置くか」「どの文字をどこにリンクするか」などを
渡す。回答の形（依頼文が求める JSON の項目）を変えるときは、このファイルの写し方だけを直せば、テストはそのまま新しい形の
回答になる。回答の形そのもの（parse_response が読む形、壊れた回答）を試すテストは、ここを使わずに手で書く。

回答の形（手順 10 から。ai_assist.RESPONSE_SCHEMA）: {"request_id", "pdf", "placements", "boxes", "boundaries", "links",
"names", "style_fixes", "notes"}。pdf は「添付なし」、段落の先頭の文字（head・after_head）は ""（確かめずに使う）。

request_id（依頼の番号。ai_assist.check_answer が今の依頼の番号と比べる。手順 17）は、既定で THIS_REQUEST（目印の文字）にする。
tests/conftest.py の自動のフィクスチャが、変換のときに目印をその変換の依頼の番号に置き換える（テストの回答は、その docx の今の
依頼文への回答〈4.6 の (a)〉として扱われる）。本物の番号が要るときは answer(docx=…)（request_of で依頼文を作って番号を埋める）。
番号の確かめそのもの（番号のない回答・別の依頼文への回答）を試すテストは、request_id を直接書く。

- placements（図・表の位置）: (図形の ID, after) か (図形の ID, after, reason, confidence)。basis は「配置の情報」、page は 0。
- boxes（テキストボックスの種類）: (テキストボックスの ID, kind, after[, reason, confidence])。kind は "囲み" か "図の注記"。
  図の注記の after は ""。
- boundaries（注の区切り・資料の始まり）: (段落 ID, kind[, reason, confidence])。kind は ai_assist.BOUNDARY_KINDS の語
  （注の始まり・注の続き・資料の見出し・英文要旨の続き・資料の本文）。
- links（リンク）: (kind, 段落 ID, text, occurrence, target[, reason, confidence])。kind は ai_assist.LINK_KINDS の語
  （文献・図・表・注・式）。
- names（姓と名の境目）: (段落 ID, surname, given[, reason, confidence])。
- style_fixes（Word のスタイルで直す提案）: (段落 ID, role[, reason, confidence])。role は段落の役割の名前（sec1・quote・exclude
  など。ai_assist.ROLES）で、この誌のその役割のスタイル名（ai_assist.role_style）と Word での直し方（how）に写す（verdict は「直す」）。
- notes: 文字列の一覧。

reason・confidence を省いた項目は DEFAULT_REASON・DEFAULT_CONFIDENCE（placements・boxes は DEFAULT_PLACE_CONFIDENCE）。

to_new(old, plan) は、前の形の回答（{"placements": [...items つき], "operations": [...], "notes": [...]}。AI 役の回答と、
手順 9 までのテストの回答）を新しい形に写す（回帰で前の回答を使うため。製品のコードは前の形を読まない）。
"""
from __future__ import annotations

import json

from jasme_jats.ai_assist import (BOUNDARY_KINDS, BOX_KINDS, EXCLUDE_HOW, LINK_KINDS, ROLES, boundary_kind, head_of,
                                  role_style)

DEFAULT_REASON = "試験"
DEFAULT_CONFIDENCE = "高"
DEFAULT_PLACE_CONFIDENCE = "中"
DEFAULT_BASIS = "配置の情報"
# 前の形の操作の名前 → links の kind の語
OLD_LINK_KINDS = {v: k for k, v in LINK_KINDS.items()}
# 前の形の placements の items の kind → boxes の kind の語
OLD_BOX_KINDS = {v: k for k, v in BOX_KINDS.items()}
# 「この変換の依頼の番号」の目印（tests/conftest.py が置き換える。ai_assist.RE_STAMP の形ではないので、置き換えなければ断られる）
THIS_REQUEST = "試験:この依頼の番号"
KEYS = ("request_id", "pdf", "placements", "boxes", "boundaries", "links", "names", "style_fixes", "notes")


def _journal():
    from jasme_jats.config import JournalConfig
    return JournalConfig.load(None)


def _tail(item, n, confidence=DEFAULT_CONFIDENCE):
    """項目の n 個目より後ろ（省いてよい reason・confidence）を補う。"""
    item = tuple(item)
    if not n <= len(item) <= n + 2:
        raise ValueError(f"項目の数が違う: {item!r}")
    rest = item[n:] + (DEFAULT_REASON, confidence)[len(item) - n:]
    return item[:n], rest[0], rest[1]


def placement(fid, after, reason=DEFAULT_REASON, confidence=DEFAULT_PLACE_CONFIDENCE, after_head="") -> dict:
    """図形 fid を段落 after の後ろに置く指定（placements の要素）。"""
    return {"float": fid, "after": after, "after_head": after_head, "page": 0, "column": "", "basis": DEFAULT_BASIS,
            "reason": reason, "confidence": confidence}


def box(xid, kind, after, reason=DEFAULT_REASON, confidence=DEFAULT_PLACE_CONFIDENCE, after_head="") -> dict:
    """テキストボックス xid の種類（囲み・図の注記）と位置の指定（boxes の要素）。"""
    if kind not in BOX_KINDS:
        raise ValueError(f"boxes の kind は {'・'.join(BOX_KINDS)} のどれか: {kind!r}")
    return {"box": xid, "kind": kind, "after": after, "after_head": after_head, "reason": reason, "confidence": confidence}


def boundary(src, kind, reason=DEFAULT_REASON, confidence=DEFAULT_CONFIDENCE, head="") -> dict:
    """注の区切り・資料の始まりの直し（boundaries の要素）。"""
    if kind not in BOUNDARY_KINDS:
        raise ValueError(f"boundaries の kind は {'・'.join(BOUNDARY_KINDS)} のどれか: {kind!r}")
    return {"src": src, "head": head, "kind": kind, "reason": reason, "confidence": confidence}


def link(kind, src, text, occurrence, target, reason=DEFAULT_REASON, confidence=DEFAULT_CONFIDENCE, head="") -> dict:
    """リンクの指定（links の要素）。"""
    if kind not in LINK_KINDS:
        raise ValueError(f"links の kind は {'・'.join(LINK_KINDS)} のどれか: {kind!r}")
    return {"kind": kind, "src": src, "head": head, "text": text, "occurrence": occurrence, "target": target,
            "reason": reason, "confidence": confidence}


def name(src, surname, given, reason=DEFAULT_REASON, confidence=DEFAULT_CONFIDENCE) -> dict:
    """姓と名の境目の指定（names の要素）。"""
    return {"src": src, "surname": surname, "given": given, "reason": reason, "confidence": confidence}


def style_fix(src, role, reason=DEFAULT_REASON, confidence=DEFAULT_CONFIDENCE, head="", journal=None) -> dict:
    """Word のスタイルで直す提案（style_fixes の要素）。role はその段落の正しい役割（ai_assist.ROLES の名前）。

    style はこの誌のその役割のスタイル名（ai_assist.role_style。除外は ""）、how は Word での直し方（除外は EXCLUDE_HOW、
    スタイル名がなければ「Word で段落を（役割の説明）のスタイルにする」）。"""
    if role not in ROLES:
        raise ValueError(f"style_fixes の役割は ai_assist.ROLES のどれか: {role!r}")
    style = "" if role == "exclude" else role_style(journal or _journal(), role)
    if role == "exclude":
        how = EXCLUDE_HOW
    elif style:
        how = f"Word で段落のスタイルを「{style}」にする"
    else:
        how = f"Word で段落を{ROLES[role]}のスタイルにする"
    return {"src": src, "head": head, "verdict": "直す", "style": style, "how": how, "reason": reason,
            "confidence": confidence}


def empty() -> dict:
    """何も指定しない回答（dict）。"""
    return {"request_id": THIS_REQUEST, "pdf": {"status": "添付なし", "pages": 0}, "placements": [], "boxes": [], "boundaries": [],
            "links": [], "names": [], "style_fixes": [], "notes": []}


def data(placements=(), boxes=(), boundaries=(), links=(), names=(), style_fixes=(), notes=(), base=None) -> dict:
    """answer() と同じ回答を、JSON にする前の dict で返す。base（新しい形の回答の dict か JSON の文字）があれば、その一覧の後ろに足す。"""
    if isinstance(base, str):
        base = json.loads(base)
    out = empty()
    for k, v in (base or {}).items():
        out[k] = list(v) if isinstance(v, list) else v
    journal = _journal() if style_fixes else None
    out["placements"] += [placement(*h, r, c) for h, r, c in (_tail(x, 2, DEFAULT_PLACE_CONFIDENCE) for x in placements)]
    out["boxes"] += [box(*h, r, c) for h, r, c in (_tail(x, 3, DEFAULT_PLACE_CONFIDENCE) for x in boxes)]
    out["boundaries"] += [boundary(*h, r, c) for h, r, c in (_tail(x, 2) for x in boundaries)]
    out["links"] += [link(*h, r, c) for h, r, c in (_tail(x, 5) for x in links)]
    out["names"] += [name(*h, r, c) for h, r, c in (_tail(x, 3) for x in names)]
    out["style_fixes"] += [style_fix(*h, r, c, journal=journal) for h, r, c in (_tail(x, 2) for x in style_fixes)]
    out["notes"] += list(notes)
    return out


def answer(placements=(), boxes=(), boundaries=(), links=(), names=(), style_fixes=(), notes=(), base=None,
           docx=None) -> str:
    """意味で書いた項目から、手動モードで貼り付ける回答の JSON の文字を作る（項目の書き方はモジュールの説明）。
    何も渡さなければ、何も指定しない回答（どの一覧も []）。docx（ルート1 で変換する docx のパス）があれば、request_id をその docx の
    依頼の番号にし、段落を指す項目の head・after_head が "" なら、その段落の先頭の文字（head_of）で埋める。"""
    out = data(placements, boxes, boundaries, links, names, style_fixes, notes, base)
    if docx is not None:
        req, plan = request_of(docx)
        out["request_id"] = req.stamp
        fill_heads(out, plan)
    return json.dumps(out, ensure_ascii=False)


def request_of(docx, journal=None, meta=None):
    """docx（ルート1 で変換する docx。ルート2 では補った docx）の依頼文（ai_assist.AIRequest）と 1 回目の組み立て（plan）。
    pipeline.convert と同じ手順（_mechanical → build → build_request）で作る。meta がなければ試験用の書誌。"""
    from jasme_jats.ai_assist import build_request
    from jasme_jats.builder import build
    from jasme_jats.config import ArticleMeta
    from jasme_jats.pipeline import _mechanical
    journal = journal or _journal()
    meta = meta or ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12", "pub_date": "2026-03-31",
                                         "received": "2025-06-01", "accepted": "2025-11-20", "peer_review": "あり"})
    _, plan, linker = _mechanical(docx, journal)
    _, info = build(plan, meta, journal, journal.split_labels)
    return build_request(plan, linker, info, journal=journal), plan


# 段落を指す項目（一覧, 段落の ID の項目, 先頭の文字の項目）。ai_assist.HEAD_CHECKED と同じ
HEADED = (("placements", "after", "after_head"), ("boxes", "after", "after_head"), ("boundaries", "src", "head"),
          ("links", "src", "head"), ("style_fixes", "src", "head"))


def fill_heads(out: dict, plan):
    """回答の dict の、段落を指す項目の head・after_head が "" なら、その段落の先頭の文字（head_of）で埋める。"""
    for key, ptr, hkey in HEADED:
        for it in out.get(key) or []:
            if isinstance(it, dict) and not it.get(hkey) and isinstance(it.get(ptr), str):
                it[hkey] = head_of(plan.paras.get(it[ptr]))


def _old_dict(old):
    """前の形の回答（dict か、```json のコードブロックを含む文字）を dict にする。"""
    if isinstance(old, dict):
        return old
    from jasme_jats.ai_assist import _json_text
    t, _ = _json_text(old)
    i, j = t.find("{"), t.rfind("}")
    return json.loads(t[i:j + 1])


def to_new(old, plan, journal=None, stamp=THIS_REQUEST) -> dict:
    """前の形の回答 old（placements〈items つき〉・operations・notes）を、新しい形の回答の dict に写す（修正計画 W8 の手順 10）。

    plan は回答を当てる原稿の 1 回目の組み立て（pipeline._mechanical）。写し方:
    - placements: 文字だけのテキストボックス（plan.textboxes）への指定は boxes（items の kind box → 囲み、label → 図の注記）、
      ほかは placements（items は捨てる。basis は「配置の情報」）。after_head は after の段落の先頭の文字（head_of）。
    - operations: link_* は links、split_name は names。set_role は、その段落への区切りの直し（ai_assist.boundary_kind）に
      当たれば boundaries（kind はその語）、当たらなければ style_fixes（style_fix と同じ写し方）。formula_image と知らない操作は捨てる
      （新しい形に入れ物がない）。head は src の段落の先頭の文字。
    - notes はそのまま。request_id は stamp（既定は THIS_REQUEST。回帰では、変換する docx の依頼の番号〈request_of〉）、
      pdf は「添付なし」。
    """
    old = _old_dict(old)
    journal = journal or _journal()
    out = empty()
    out["request_id"] = stamp
    out["notes"] = list(old.get("notes") or []) if isinstance(old.get("notes"), list) else old.get("notes", [])
    paras = plan.paras
    for pl in old.get("placements") or []:
        if not isinstance(pl, dict):
            out["placements"].append(pl)
            continue
        fid, after = pl.get("float"), pl.get("after")
        head = head_of(paras.get(after)) if isinstance(after, str) else ""
        reason, conf = pl.get("reason", ""), pl.get("confidence", "")
        if isinstance(fid, str) and fid in plan.textboxes:
            items = pl.get("items") if isinstance(pl.get("items"), list) else []
            kind = items[0].get("kind") if len(items) == 1 and isinstance(items[0], dict) else ""
            out["boxes"].append({"box": fid, "kind": OLD_BOX_KINDS.get(kind, str(kind)), "after": after if after else "",
                                 "after_head": head, "reason": reason, "confidence": conf})
            continue
        out["placements"].append({"float": fid, "after": after, "after_head": head, "page": 0, "column": "",
                                  "basis": DEFAULT_BASIS, "reason": reason, "confidence": conf})
    for op in old.get("operations") or []:
        if not isinstance(op, dict):
            continue
        kind, src = op.get("op"), op.get("src")
        p = paras.get(src) if isinstance(src, str) else None
        head = head_of(p)
        reason, conf = op.get("reason", ""), op.get("confidence", "")
        if kind in OLD_LINK_KINDS:
            out["links"].append({"kind": OLD_LINK_KINDS[kind], "src": src, "head": head, "text": op.get("text", ""),
                                 "occurrence": op.get("occurrence", 1), "target": op.get("target", ""),
                                 "reason": reason, "confidence": conf})
        elif kind == "split_name":
            out["names"].append({"src": src, "surname": op.get("surname", ""), "given": op.get("given", ""),
                                 "reason": reason, "confidence": conf})
        elif kind == "set_role":
            role = op.get("role", "")
            bkind = boundary_kind(p, plan, role) if p is not None else ""
            if bkind:
                out["boundaries"].append({"src": src, "head": head, "kind": bkind, "reason": reason, "confidence": conf})
            elif role in ROLES:
                fix = style_fix(src, role, reason, conf, head=head, journal=journal)
                out["style_fixes"].append(fix)
    return out


def force_boundaries(monkeypatch, roles):
    """守りのテスト用: pipeline の区切りの検証（ai_assist.boundary_overrides）を差し替え、roles（{段落 ID: 中の役割}）をそのまま
    上書き表にする（区切りの 5 つ以外の役割も反映する形。構造の衝突・組み直した後の不採用の守りを、回答の形に依らずに確かめる）。
    回答の boundaries は読まない。"""
    from jasme_jats import ai_assist, pipeline

    def fake(data, plan, outcome):
        ops = [{"op": "boundary", "src": src, "text": "試験の区切り", "occurrence": 1, "target": "", "role": role,
                "reason": DEFAULT_REASON, "confidence": "低"} for src, role in roles.items()]
        for op in ops:
            outcome.boundaries.append(ai_assist.Boundary(op["src"], op["text"], op["role"], op["reason"], op["confidence"]))
        return dict(roles), ops
    monkeypatch.setattr(pipeline, "boundary_overrides", fake)
