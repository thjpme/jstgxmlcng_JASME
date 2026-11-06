"""u3-autonum の監査: Word の自動番号（Para.autonum）のある段落を、XML のいろいろな場所に置いて変換し、
番号が XML に出るか（Builder.autonum が呼ばれたか、と XML の文字）を表にする。

python3 audit.py
"""
import re
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path("/home/user/jstgxmlcng_JASME")
sys.path.insert(0, str(REPO / "tests"))

import make_fixtures as mf  # noqa: E402
from lxml import etree  # noqa: E402

from jasme_jats import builder as B  # noqa: E402
from jasme_jats.config import ArticleMeta, JournalConfig  # noqa: E402
from jasme_jats.pipeline import Options, convert  # noqa: E402
from jasme_jats.tracking import GEN, SPAN  # noqa: E402

S = mf.S
W = mf.W
NUM = 7


def li(style, text):
    return mf.list_item(style, text, num_id=NUM)


def body_parts(b):
    rid = b.add_image("a.png", mf.png_bytes("A"))
    formula = mf.list_item(S["body"], mf.omathpara(mf.mr("S=") + mf.mfrac(mf.mr("1"), mf.mr("2"))), mf.tab(), "(1)",
                           num_id=NUM)
    return [
        li(S["sec1"], "検査見出し一"),
        li(S["body"], "検査本文箇条"),
        mf.para(S["body"], "本文の文である。"),
        li(S["quote"], "検査引用"),
        formula,
        mf.para(S["body"], "本文の文である。"),
        mf.para(S["body"], mf.drawing(rid, 1800000, 1100000, 50)),
        li(S["fig_cap"], "図1　検査図キャプション"),
        li(S["fig_cap"], "検査図キャプション続き"),
        li(S["tab_cap"], "表1　検査表キャプション"),
        mf.table([[mf.cell(li(S["body"], "検査セル一")), mf.cell("回答")],
                  [mf.cell(li(S["body"], "検査セル二")), mf.cell("回答")]]),
        mf.para(S["body"], "本文の文である。"),
        mf.para(S["body"], "囲みの前の段落。",
                mf.textbox(mf.para(S["body"], "問1　架空の囲みの問題文である。") + li(S["body"], "検査囲み一")
                           + li(S["body"], "検査囲み二"), 60, cx=12 * 360000, cy=3 * 360000, wrap="wrapTopAndBottom")),
        mf.para(S["body"], "囲みの後の段落である。"),
        mf.para(S["body"], "本文の文である。"),
        mf.list_item(S["body"], mf.drawing(b.add_image("b.png", mf.png_bytes("B")), 1800000, 1100000, 51), num_id=NUM),
        mf.para(S["fig_cap"], "図2　画像の段落に番号"),
        mf.para(S["body"], "本文の文である。"),
        li(S["body"], ""),
        mf.para(S["body"], "番号だけの段落の後ろ。"),
        mf.para(S["fig_cap"], "図3　表で組んだ図"),
        mf.table([[mf.cell(li(S["body"], "検査図の表のセル"))]]),
        mf.para(S["body"], "本文の文である。"),
        mf.para(S["body"], "本文の文である。" + "", mf.footnote_ref(5)),
        li(S["notes_head"], "検査付記見出し"),
        li(S["body"], "検査付記箇条"),
        li(S["ack_head"], "検査謝辞見出し"),
        mf.para(S["body"], "謝辞の文。"),
        li(S["fn_head"], "検査注見出し"),
        li(S["fn_body"], "検査注一の一段落目"),
        mf.list_item(S["fn_body"], "検査注一の二段落目（箇条の記号）", num_id=6),
        li(S["fn_body"], "検査注二"),
    ]


def footnotes():
    # Word の脚注の 2 段落目に自動番号
    return [mf.footnote(5, "脚注の一段落目。", li("a8", "検査脚注二段落目"))]


def add_num(docx, markers):
    """document.xml の、文字に markers のどれかを含む w:p に自動番号（numId=NUM）を付ける。"""
    tmp = docx.with_suffix(".tmp.docx")
    with zipfile.ZipFile(docx) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                root = etree.fromstring(data)
                for p in root.iter(f"{{{W}}}p"):
                    t = "".join(x.text or "" for x in p.iter(f"{{{W}}}t"))
                    if any(m in t for m in markers):
                        ppr = p.find(f"{{{W}}}pPr")
                        if ppr is None:
                            ppr = etree.SubElement(p, f"{{{W}}}pPr")
                            p.insert(0, ppr)
                        num = etree.fromstring(f'<w:numPr xmlns:w="{W}"><w:ilvl w:val="0"/><w:numId w:val="{NUM}"/></w:numPr>')
                        st = ppr.find(f"{{{W}}}pStyle")
                        if st is not None:
                            st.addnext(num)
                        else:
                            ppr.insert(0, num)
                data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
            zout.writestr(item, data)
    tmp.replace(docx)


def make(path):
    b = mf.Builder()
    b.footnotes_extra.extend(footnotes())
    body = []
    body += mf.front_ja(b, "検査題目", "―検査副題―", [("検査所属", "試験　六郎")])
    body += body_parts(b)
    body.append(li(S["ref_head"], "検査文献見出し"))
    body.append(li(S["ref"], "試験六郎（2024）．「検査文献」．『架空誌』，第5巻，pp.9-10．"))
    body += mf.front_en(b, "Kensa Title", "Kensa Subtitle", [("Rokuro SHIKEN", "Kensa Univ")], [])
    # 英文要旨の段落を番号付きに
    body.append(li(S["abs"], "Kensa abstract numbered."))
    body.append(mf.para(S["abs"], "Kensa abstract plain."))
    appendix = [li(S["sec1"], "資料　検査資料見出し"), li(S["body"], "検査資料箇条"),
                mf.table([[mf.cell(li(S["body"], "検査資料セル"))]])]
    body += mf.tail(b, appendix=appendix)
    b.save(path, body)
    add_num(path, ["検査題目", "検査副題", "検査所属", "Kensa Title", "Kensa Subtitle", "Kensa Univ", "Rokuro SHIKEN",
                   "試験　六郎", "Abstract"])


def main():
    out = HERE / "audit_out"
    out.mkdir(exist_ok=True)
    path = out / "audit.docx"
    make(path)
    called = set()
    orig = B.Builder.autonum

    def spy(self, p):
        called.add(p.src)
        return orig(self, p)
    B.Builder.autonum = spy
    trees = []
    orig_build = B.build

    def build_spy(*a, **k):
        root, info = orig_build(*a, **k)
        trees.append(root)
        return root, info
    import jasme_jats.pipeline as P
    P.build = build_spy
    journal = JournalConfig.load()
    meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12", "pub_date": "2026-03-31",
                                  "received": "2025-06-01", "accepted": "2025-11-20", "peer_review": "あり",
                                  "keywords": "proof; 論証"})
    res = convert(path, meta, journal, Options(out_dir=out / "o", convert_metafiles=False))
    plan = res.plan
    root = trees[-1]
    span_srcs = {sp.get("src") for sp in root.iter(SPAN)}
    excl = {e.src: e.reason for e in plan.exclusions}
    print("fidelity", res.fidelity.ok, res.fidelity.final_ok, "dtd", res.dtd_valid, res.dtd_errors[:3])
    rows = []
    for p in plan.paras.values():
        if not p.autonum:
            continue
        where = []
        sp = next((s for s in root.iter(SPAN) if s.get("src") == p.src), None)
        if sp is not None:
            where = [a.tag for a in sp.iterancestors()][:4]
        rows.append((p.src, p.autonum, p.role, p.text_only()[:16], p.src in span_srcs, p.src in called,
                     excl.get(p.src, ""), "/".join(reversed([w for w in where if isinstance(w, str)]))))
    for r in rows:
        print("\t".join(str(x) for x in r))
    print("gen:", [(g.get("kind"), g.text) for g in root.iter(GEN)])


if __name__ == "__main__":
    main()
