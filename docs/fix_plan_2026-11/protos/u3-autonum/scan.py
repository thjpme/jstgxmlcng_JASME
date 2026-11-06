"""tests/fixtures と tests/private のすべての docx を変換し、自動番号のある段落のうち
(a) XML に文字を出した（jx:span がある）のに番号を出さなかった（Builder.autonum を呼ばなかった）もの
(b) 番号を出したもの
(c) 文字を出さなかった（除外・空・画像だけ）もの
を、段落 ID と XML の要素の道筋で数える（本文の文字は出さない）。ルート2 は PDF のある 3 件で。

python3 scan.py
"""
import sys
import traceback
from collections import Counter
from pathlib import Path

REPO = Path("/home/user/jstgxmlcng_JASME")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "tests"))

from jasme_jats import builder as B  # noqa: E402
import jasme_jats.pipeline as P  # noqa: E402
from jasme_jats.config import ArticleMeta, JournalConfig  # noqa: E402
from jasme_jats.pipeline import Options, convert, AIRequiredError  # noqa: E402
from jasme_jats.tracking import GEN, SPAN  # noqa: E402

called = set()
trees = []
orig_autonum = B.Builder.autonum
orig_build = B.build


def spy(self, p):
    called.add(p.src)
    return orig_autonum(self, p)


def build_spy(*a, **k):
    called.clear()
    root, info = orig_build(*a, **k)
    trees.append((root, set(called)))
    return root, info


B.Builder.autonum = spy
P.build = build_spy

journal = JournalConfig.load()
meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12", "pub_date": "2026-03-31",
                              "received": "2025-06-01", "accepted": "2025-11-20", "peer_review": "あり",
                              "keywords": "proof; 論証"})


def path_of(sp):
    tags = [a.tag for a in sp.iterancestors() if isinstance(a.tag, str)]
    tags = [t for t in tags if not t.startswith("{")]
    return "/".join(reversed(tags[:3]))


def scan(docx, label, pdf=None):
    trees.clear()
    out = HERE / "scan_out" / label
    res = None
    try:
        res = convert(docx, meta, journal, Options(out_dir=out, convert_metafiles=False,
                                                   pdf_path=pdf, route="pdf" if pdf else "docx"))
    except AIRequiredError:
        trees.clear()
        res = convert(docx, meta, journal, Options(out_dir=out, convert_metafiles=False, ai_mode="manual",
                                                   pdf_path=pdf, route="pdf" if pdf else "docx"))
    except Exception as e:  # noqa: BLE001
        return label, "error " + type(e).__name__ + ": " + str(e)[:80], None
    root, emitted = trees[-1]
    plan = res.plan
    spans = {}
    for sp in root.iter(SPAN):
        spans.setdefault(sp.get("src"), path_of(sp))
    lost, ok, silent = [], 0, Counter()
    excl = {e.src for e in plan.exclusions} | {e.src for e in []}
    for p in plan.paras.values():
        if not (p.autonum or "").strip():
            continue
        if p.src in spans:
            if p.src in emitted:
                ok += 1
            else:
                lost.append((p.src, spans[p.src], p.role))
        else:
            silent["excluded" if p.src in excl else ("empty" if not p.plain().strip() else "no-span")] += 1
    gens = Counter(g.get("kind") for g in root.iter(GEN))
    summary = dict(fid=res.fidelity.ok, dtd=res.dtd_valid, emitted=ok, lost=len(lost), silent=dict(silent), gens=dict(gens),
                   needs_action=res.needs_action)
    return label, summary, lost


def main():
    docs = sorted((REPO / "tests" / "fixtures").glob("*.docx")) + sorted((REPO / "tests" / "private").glob("テスト*/*.docx")) \
        + sorted((REPO / "tests" / "private" / "テンプレート").glob("*.docx"))
    runs = [(d, d.parent.name + "/" + d.stem[:12] if "private" in str(d) else d.stem, None) for d in docs]
    for folder in ("テストデータ1", "テストデータ2", "テストデータ3"):
        f = REPO / "tests" / "private" / folder
        pdf = next(f.glob("*.pdf"))
        for d in sorted(f.glob("*.docx")):
            runs.append((d, folder + "/" + d.stem[-8:] + "/route2", pdf))
    paths = Counter()
    for d, label, pdf in runs:
        label, summary, lost = scan(d, label.replace("/", "_"), pdf)
        print(label, summary)
        for src, where, role in lost or []:
            print("    lost", src, where, role)
            paths[where] += 1
    print("paths:", dict(paths))


if __name__ == "__main__":
    main()
