"""u5-exclusions の再現: (a) 注の節の表（K7）、(b) 見出しのない標準スタイルの英文要旨（K12）。"""
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path("/home/user/jstgxmlcng_JASME")
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
from lxml import etree

import make_fixtures as mf
from jasme_jats.config import ArticleMeta, JournalConfig
from jasme_jats.pipeline import Options, convert
from jasme_jats.report import actions

WORK = Path(__file__).resolve().parent / "work"
WORK.mkdir(exist_ok=True)
journal = JournalConfig.load()
meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12"})
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def out(label, **v):
    print(label, json.dumps(v, ensure_ascii=False, default=str))


def run(label, path):
    res = convert(path, meta, journal, Options(out_dir=WORK / label, convert_metafiles=False))
    root = etree.fromstring(res.xml_path.read_bytes())
    acts = [(a.level, a.key) for a in actions(res)]
    ex = [(e.src, e.reason) for e in res.plan.exclusions + getattr(res, "_info_ex", []) if not e.blank]
    return res, root, acts, ex


def simple(b):
    return [mf.para(mf.S["sec1"], "１．検証"), mf.para(mf.S["body"], "これは検証用の本文です。")]


def rewrite(src, dst, change):
    with zipfile.ZipFile(src) as zi, zipfile.ZipFile(dst, "w") as zo:
        for e in zi.infolist():
            d = zi.read(e.filename)
            if e.filename == "word/document.xml":
                d = change(d)
            zo.writestr(e, d)


# (a) 注の節の表: 注の項目の後ろ / 注の見出しの直後 / 表のキャプション付き
variants = {
    "a1_after_item": lambda b: simple(b) + [mf.para(mf.S["fn_head"], "注"), mf.para(mf.S["fn_body"], "1) 注の本文。"),
                                             mf.table([[mf.cell("注の表A"), mf.cell("123")]])],
    "a2_first": lambda b: simple(b) + [mf.para(mf.S["fn_head"], "注"),
                                        mf.table([[mf.cell("注の表B"), mf.cell("456")]]),
                                        mf.para(mf.S["fn_body"], "1) 注の本文。")],
    "a3_caption": lambda b: simple(b) + [mf.para(mf.S["fn_head"], "注"), mf.para(mf.S["fn_body"], "1) 注の本文。"),
                                          mf.para(mf.S["tab_cap"], "表1　注の表のキャプション"),
                                          mf.table([[mf.cell("注の表C"), mf.cell("789")]])],
    "a4_body_style": lambda b: simple(b) + [mf.para(mf.S["fn_head"], "注"), mf.para(mf.S["body"], "1) 注の本文。"),
                                             mf.table([[mf.cell("注の表D"), mf.cell("0")]])],
}
for name, body in variants.items():
    p = WORK / f"{name}.docx"
    mf.make_article(p, "注の表の検証", body)
    res, root, acts, ex = run(name, p)
    fn = root.findall(".//fn-group/fn")
    out(name, ok=res.ok, needs_action=res.needs_action, actions=acts, exclusions=ex,
        fn_count=len(fn), tables_in_xml=len(root.findall(".//table-wrap")),
        fid_excluded=[(s, r) for s, r, t in res.fidelity.excluded if r != "空白のみの段落"])

# (b) 見出しのない標準スタイルの英文要旨
orig = WORK / "b_orig.docx"
mf.make_article(orig, "要旨の検証", simple, abstract=("This abstract contains important results.", "Second para."))


def strip_abs(remove_heading=True, plain=True):
    def change(data):
        root = etree.fromstring(data)
        for p in list(root.iter(W + "p")):
            text = "".join(p.itertext())
            if remove_heading and text.strip() == "Abstract":
                p.getparent().remove(p)
            elif plain and ("important results" in text or text == "Second para."):
                pr = p.find(W + "pPr")
                if pr is not None:
                    p.remove(pr)
        return etree.tostring(root)
    return change


for name, kw in {"b1_noheading_plain": dict(remove_heading=True, plain=True),
                 "b2_heading_plain": dict(remove_heading=False, plain=True),
                 "b3_noheading_styled": dict(remove_heading=True, plain=False)}.items():
    p = WORK / f"{name}.docx"
    rewrite(orig, p, strip_abs(**kw))
    res, root, acts, ex = run(name, p)
    out(name, ok=res.ok, needs_action=res.needs_action, actions=acts, exclusions=ex,
        abstract_en=len(root.findall(".//trans-abstract")) + len([a for a in root.findall(".//abstract")]),
        plan_abstract=len(res.plan.abstract), lang=res.plan.lang)
