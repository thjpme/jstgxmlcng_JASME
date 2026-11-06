"""出力の <table> の形の確かめ（試作）。"""
def table_shape(tbl):
    """戻り値: (各行の占有列数の一覧〈節ごとに区切らず表全体〉, 問題の一覧)"""
    widths, problems = [], []
    for sec in tbl:
        if not isinstance(sec.tag, str):
            continue
        name = sec.tag.split("}")[-1]
        if name not in ("thead", "tbody", "tfoot"):
            continue
        carry = {}    # 列 -> 残りの行数
        trs = [tr for tr in sec if isinstance(tr.tag, str) and tr.tag.split("}")[-1] == "tr"]
        for i, tr in enumerate(trs):
            cells = [c for c in tr if isinstance(c.tag, str) and c.tag.split("}")[-1] in ("td", "th")]
            if not cells:
                problems.append(f"{name} の {i+1} 行目が空の tr")
            occ = {c for c, n in carry.items() if n > 0}
            col = 0
            newcarry = {c: n - 1 for c, n in carry.items() if n - 1 > 0}
            for c in cells:
                while col in occ:
                    col += 1
                cs = int(c.get("colspan", "1")); rs = int(c.get("rowspan", "1"))
                for k in range(col, col + cs):
                    if k in occ:
                        problems.append(f"{name} の {i+1} 行目でセルが重なる（列 {k}）")
                    occ.add(k)
                    if rs > 1:
                        newcarry[k] = rs - 1
                col += cs
            widths.append(len(occ) if occ else 0)
            width_max = max(occ) + 1 if occ else 0
            if width_max != len(occ):
                problems.append(f"{name} の {i+1} 行目に空いた列")
            carry = newcarry
        if carry:
            problems.append(f"{name} の外に rowspan がはみ出す（{sorted(carry.items())}）")
    if len(set(widths)) > 1:
        problems.append(f"行ごとの占有列数が違う: {widths}")
    return widths, problems
