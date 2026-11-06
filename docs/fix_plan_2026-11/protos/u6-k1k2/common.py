"""u6-k1k2 の再現・試作の共通部品（リポジトリは変えない）。"""
import copy
import sys
from pathlib import Path

ROOT = Path("/home/user/jstgxmlcng_JASME")
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
import make_fixtures as mf  # noqa: E402
from make_fixtures import S, W, para  # noqa: E402
from jasme_jats.config import ArticleMeta, JournalConfig  # noqa: E402
from jasme_jats.pipeline import Options, convert  # noqa: E402
from jasme_jats.report import actions  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)
journal = JournalConfig.load()
meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12",
                              "pub_date": "2026-03-31", "received": "2025-06-01", "accepted": "2025-11-20",
                              "peer_review": "あり", "keywords": "proof; 論証; 数学的探究"})


def front_ja_rows(b, title, rows, loose=()):
    """make_fixtures.front_ja と同じだが、著者表の行を [(所属, 著者)] で自由に（空文字は空のセル）、表の後ろに loose の段落を足す。"""
    k = b.kids
    out = [copy.deepcopy(k[0]), copy.deepcopy(k[1])]
    t = copy.deepcopy(k[2]); b.set_text(t, title); out.append(t)
    st = copy.deepcopy(k[3]); b.set_text(st, "―検証用―"); out.append(st)
    out.append(copy.deepcopy(k[4]))
    tbl = copy.deepcopy(k[5])
    trs = tbl.findall(f"{{{W}}}tr")
    proto = trs[0]
    for r in trs:
        tbl.remove(r)
    for aff, name in rows:
        r = copy.deepcopy(proto)
        cells = r.findall(f"{{{W}}}tc")
        b.set_text(cells[0].find(f".//{{{W}}}p"), aff)
        b.set_text(cells[1].find(f".//{{{W}}}p"), name)
        tbl.append(r)
    if rows:
        out.append(tbl)
    out.extend(b.frag("".join(loose)) if loose else [])
    out.extend(copy.deepcopy(x) for x in k[6:9])
    return out


def front_en_rows(b, rows, abstract=("Small article abstract.",)):
    """英文の著者表の行を [("name"|"aff", 文字)] で自由に並べる。"""
    k = b.kids
    i2 = [i for i, el in enumerate(k) if el.find(f".//{{{W}}}sectPr") is not None][1]
    out = [copy.deepcopy(k[i2]), copy.deepcopy(k[i2 + 1])]
    t = copy.deepcopy(k[i2 + 2]); b.set_text(t, "A Small Article"); out.append(t)
    st = copy.deepcopy(k[i2 + 3]); b.set_text(st, "For Checking"); out.append(st)
    tbl = copy.deepcopy(k[i2 + 4])
    trs = tbl.findall(f"{{{W}}}tr")
    pn, pa = trs[0], trs[1]
    for r in trs:
        tbl.remove(r)
    for kind, text in rows:
        r = copy.deepcopy(pn if kind == "name" else pa)
        b.set_text(r.find(f".//{{{W}}}p"), text)
        tbl.append(r)
    out.append(tbl)
    out.append(copy.deepcopy(k[i2 + 5]))
    for text in abstract:
        out.append(para(S["abs"], text))
    return out


def article(path, body=None, back=None, ja_rows=(("架空大学", "試験　六郎"),), loose=(),
            en_rows=(("name", "Rokuro SHIKEN"), ("aff", "Fictional University")), en_after=None):
    """題目・著者・本文・引用文献・英文。back は引用文献の見出し・1 件の後ろに足す段落の XML。"""
    b = mf.Builder()
    parts = front_ja_rows(b, "検証用の論文", list(ja_rows), loose)
    parts += [para(S["sec1"], "１．はじめに"), para(S["body"], "架空の主張である（試験，2024）。")]
    parts += list(body or [])
    if back is None:
        parts.append(para(S["ref_head"], "引用文献"))
        parts.append(para(S["ref"], "試験六郎（2024）．「小さな論文」．『架空誌』，第5巻，pp.9-10．"))
    else:
        parts += list(back)
    parts += front_en_rows(b, list(en_rows))
    parts += list(en_after or [])
    parts.append(copy.deepcopy(b.kids[-1]))
    b.save(path, parts)
    return path


def run(name, path, **opt):
    res = convert(path, meta, journal, Options(out_dir=OUT / name, convert_metafiles=False, **opt))
    return res


def summary(res):
    f = res.fidelity
    return dict(ok=f.ok, missing=[s for s, _ in f.missing], needs_action=res.needs_action,
                keys=[a.key for a in actions(res)])
