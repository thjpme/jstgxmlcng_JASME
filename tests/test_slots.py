"""画像の置き場所（article.ImageSlot）と名前（W1 の手順 3）。

図 1 つに <graphic> 1 つで、名前は図番号から決める（fig01・fig02-1・fig04_2・figx01）。キャプションのない画像は、docx の画像の位置
（ImageRef.draw_id）ごとに置き場所 1 つで、名前は画像の中身の要約値（ImageRef.digest）の先頭 6 桁から決める（img3fa9c2。同じ中身が
2 か所なら _2）。名前は XML に 2 回出ず、AI の位置の指定の前後・ルート2（出版版 PDF で補った docx）でも変わらない。
テスト用の docx の内容は架空のもの。
"""
import hashlib
import zipfile

import make_fixtures as mf
import pytest
from conftest import ALL_DOCS, DATA, FLOAT
from lxml import etree

from jasme_jats import pdfmatch
from jasme_jats.docx_reader import read_docx
from jasme_jats.model import OBJ
from jasme_jats.pipeline import Options, convert

XLINK = "http://www.w3.org/1999/xlink"
HREF = f"{{{XLINK}}}href"


def load(res):
    return etree.parse(str(res.xml_path)).getroot()


def hrefs(root):
    return [g.get(HREF) for g in root.iter("graphic", "inline-graphic")]


def fig_names(root):
    """キャプションの先頭（「図1」など）→ その <fig> の <graphic> の名前の一覧。"""
    out = {}
    for f in root.iter("fig"):
        cap = f.find("caption")
        head = "".join(cap.itertext()).split("　")[0] if cap is not None else "-"
        out.setdefault(head, []).append([g.get(HREF) for g in f.findall("graphic")])
    return out


def short(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()[:6]


def slots_doc(tmp_path, wide=False):
    """幹の規則を確かめる原稿: 図1、枝番の図（図2-1・図2-2）、同じ番号の図 2 つ（図4）、番号を読めない図キャプション、
    キャプションのない画像だけの段落 2 つ（同じ中身）、文の中の行内の画像、文の中のグループ図形（画像 2 枚）。
    wide なら図番号を全角の数字で書く（ルート2 で半角に直る）。戻り値: (パス, 画像の中身の一覧)。"""
    data = [mf.png_bytes(f"Slot {k}", size=(240, 160)) for k in range(9)]
    num = (lambda s: s.translate(str.maketrans("0123456789-", "０１２３４５６７８９－"))) if wide else (lambda s: s)

    def body(b):
        rid = [b.add_image(f"slot{k}.png", d) for k, d in enumerate(data)]
        rid.append(b.add_image("slot_same.png", data[6]))         # 同じ中身の別のファイル（rid[9]）

        def img(k, pid):
            return mf.para(mf.S["body"], mf.drawing(rid[k], 1800000, 1200000, pid))

        def text(s):
            return mf.para(mf.S["body"], s + "本文の段落としての長さを持たせるための、架空の説明の文である。")

        return [mf.para(mf.S["sec1"], "１．はじめに"),
                text("試験（2024）にならい，画像の置き場所を確かめる。"),
                img(0, 701), mf.para(mf.S["fig_cap"], num("図1") + "　架空の図"),
                text("図1の後ろの段落。"),
                img(1, 702), mf.para(mf.S["fig_cap"], num("図2-1") + "　枝番の図"),
                text("図2-1の後ろの段落。"),
                img(2, 703), mf.para(mf.S["fig_cap"], num("図2-2") + "　二つ目の枝番の図"),
                text("図2-2の後ろの段落。"),
                img(3, 704), mf.para(mf.S["fig_cap"], num("図4") + "　同じ番号の図"),
                text("一つ目の図4の後ろの段落。"),
                img(4, 705), mf.para(mf.S["fig_cap"], num("図4") + "　同じ番号の二つ目の図"),
                text("二つ目の図4の後ろの段落。"),
                img(5, 706), mf.para(mf.S["fig_cap"], "写真　番号のないキャプション"),
                text("写真の後ろの段落。"),
                img(6, 707),
                text("キャプションのない画像の後ろの段落。"),
                img(9, 708),
                text("同じ中身の画像の後ろの段落。"),
                mf.para(mf.S["body"], "文の中に", mf.drawing(rid[7], 360000, 240000, 709), "行内の画像がある架空の段落である。"),
                mf.para(mf.S["body"], "文の中に", mf.pic_group([(rid[8], 900000, 600000), (rid[0], 900000, 600000)], 710),
                        "グループ図形がある架空の段落である。"),
                text("以上で終わる。")]

    path = tmp_path / ("slots_wide.docx" if wide else "slots.docx")
    mf.make_article(path, "画像の置き場所の検証用文書", body)
    return path, data


def checks_pass(res):
    fid = res.fidelity
    assert fid.ok and fid.final_ok and res.dtd_valid and res.jstage_issues == [], (fid.missing, fid.conflicts)
    assert res.lost_images == []


def test_slot_keys(journal, meta, tmp_path):
    path, data = slots_doc(tmp_path)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    checks_pass(res)
    got = [(s.key, s.kind, s.place, s.label) for s in res.plan.slots]
    assert got == [("fig01", "fig", "fig", "図1"), ("fig02-1", "fig", "fig", "図2-1"), ("fig02-2", "fig", "fig", "図2-2"),
                   ("fig04", "fig", "fig", "図4"), ("fig04_2", "fig", "fig", "図4"), ("figx01", "fig", "fig", ""),
                   (f"img{short(data[6])}", "nocap", "fig", ""), (f"img{short(data[6])}_2", "nocap", "fig", ""),
                   (f"img{short(data[7])}", "nocap", "inline", ""), (f"img{short(data[8])}", "nocap", "inline", "")]
    # グループ図形の 2 枚の画像は、docx の画像の位置 1 つなので置き場所 1 つ（covers に 2 枚）
    group = res.plan.slots[-1]
    assert len(group.covers) == 2 and len({i.draw_id for i in group.covers}) == 1
    assert {i.image_id: s.key for s in res.plan.slots for i in s.covers} == {
        i.image_id: res.plan.slot_of[i.image_id].key for i in read_docx(path).images}
    root = load(res)
    names = hrefs(root)
    assert names == [f"31_1_{s.key}.png" for s in res.plan.slots]           # XML の順・重なりなし
    assert len(set(names)) == len(names) == len(res.images) and [i.name for i in res.images] == names
    assert all(len(f.findall("graphic")) == 1 for f in root.iter("fig"))     # 図 1 つに <graphic> 1 つ
    assert fig_names(root)["図4"] == [["31_1_fig04.png"], ["31_1_fig04_2.png"]]
    # 行内の画像は今までどおり段落の中の <inline-graphic>（グループ図形の 2 枚目は書かない）
    inline = [g.get(HREF) for g in root.iter("inline-graphic")]
    assert inline == [f"31_1_img{short(data[7])}.png", f"31_1_img{short(data[8])}.png"]


def test_one_graphic_for_a_figure_with_two_images(journal, meta, tmp_path):
    """図キャプションの図に docx の画像が 2 枚あっても（グループ図形の画像だけの段落）、<graphic> は 1 つで、名前は図番号から。
    ほかの画像は XML に入らなかった画像として知らせない（同じ 1 枚に写るとみなす）。"""
    def body(b):
        r1 = b.add_image("two_a.png", mf.png_bytes("Two A"))
        r2 = b.add_image("two_b.png", mf.png_bytes("Two B"))
        return [mf.para(mf.S["sec1"], "１．はじめに"),
                mf.para(mf.S["body"], "試験（2024）にならい，二つの画像のある図を確かめる。本文の段落としての長さを持たせる。"),
                mf.para(mf.S["body"], mf.pic_group([(r1, 900000, 600000), (r2, 900000, 600000)], 720)),
                mf.para(mf.S["fig_cap"], "図3　二つの画像の図"),
                mf.para(mf.S["body"], "以上で終わる。本文の段落としての長さを持たせるための、架空の説明の文である。")]
    path = tmp_path / "two.docx"
    mf.make_article(path, "二つの画像の図の検証用文書", body)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    checks_pass(res)
    [slot] = res.plan.slots
    assert slot.key == "fig03" and len(slot.covers) == 2 and res.plan.figures[0].slot is slot
    assert fig_names(load(res)) == {"図3": [["31_1_fig03.png"]]}
    assert [i.name for i in res.images] == ["31_1_fig03.png"]


@pytest.mark.parametrize("path", ALL_DOCS, ids=lambda p: p.stem)
def test_names_are_unique_in_fixtures(journal, meta, tmp_path, path):
    """どの fixture でも、XML の画像の名前は 2 回出ず、図 1 つに <graphic> は 1 つまで。名前は「記事識別子_幹」で、出力した
    置き場所と同じ。"""
    res = convert(path, meta, journal, Options(out_dir=tmp_path, convert_metafiles=False))
    root = load(res)
    names = hrefs(root)
    assert len(set(names)) == len(names)
    assert all(len(f.findall("graphic")) <= 1 for f in root.iter("fig"))
    assert sorted(names) == sorted(i.name for i in res.images)
    keys = {s.key for s in res.plan.slots}
    assert all(n.startswith("31_1_") and n[len("31_1_"):].rsplit(".", 1)[0] in keys for n in names)


def test_names_do_not_change_with_ai_placement(journal, meta, tmp_path):
    """AI の位置の指定で図の位置と XML の順が変わっても、図ごとの名前は変わらない（名前は図番号から決める）。"""
    before = convert(FLOAT, meta, journal, Options(out_dir=tmp_path / "a", ai_mode="manual", convert_metafiles=False))
    after = convert(FLOAT, meta, journal, Options(out_dir=tmp_path / "b", ai_mode="manual", convert_metafiles=False,
                                                  ai_response=(DATA / "ai_response_sample_float.json").read_text(encoding="utf-8")))
    assert before.plan.unplaced_floats and not after.plan.unplaced_floats
    a, b = fig_names(load(before)), fig_names(load(after))
    # 図1 は表で組んだ図（置き場所なし）。ほかの図は図番号の名前
    assert a == b and a.pop("図1") == [[]] and len(a) >= 3
    assert all(names == [[f"31_1_fig0{head[1]}.png"]] for head, names in a.items())
    assert sorted(i.name for i in before.images) == sorted(i.name for i in after.images)


def test_names_are_the_same_in_route2(journal, meta, tmp_path, monkeypatch):
    """ルート2（出版版 PDF で補った docx）でも、置き場所と名前はルート1 と同じ（全角の図番号を半角に直しても同じ幹。画像の中身の
    要約値も同じ）。"""
    path, _ = slots_doc(tmp_path, wide=True)
    r1 = convert(path, meta, journal, Options(out_dir=tmp_path / "r1", convert_metafiles=False))
    texts = [p.plain().replace(OBJ, "").strip() for p in read_docx(path).all_paragraphs()]
    table = str.maketrans("０１２３４５６７８９－", "0123456789-")
    pub = [t.translate(table) if t.startswith("図") else t for t in texts if t]
    monkeypatch.setattr(pdfmatch, "extract_pages", lambda p: ["\n".join(pub)])
    (tmp_path / "dummy.pdf").write_bytes(b"%PDF-1.4\n")
    r2 = convert(path, meta, journal, Options(out_dir=tmp_path / "r2", pdf_path=tmp_path / "dummy.pdf", route="pdf",
                                              convert_metafiles=False))
    checks_pass(r1)
    checks_pass(r2)
    assert r2.docx_fix is not None and any(f.src for f in r2.docx_fix.fixes)     # 図番号を半角に直した docx から変換した
    assert "".join(load(r2).find(".//fig/caption").itertext()).startswith("図1")
    k1 = [(s.key, s.kind, s.place) for s in r1.plan.slots]
    assert k1 == [(s.key, s.kind, s.place) for s in r2.plan.slots]
    assert k1[:5] == [("fig01", "fig", "fig"), ("fig02-1", "fig", "fig"), ("fig02-2", "fig", "fig"), ("fig04", "fig", "fig"),
                      ("fig04_2", "fig", "fig")]
    assert hrefs(load(r1)) == hrefs(load(r2))


def test_each_slot_is_written_under_its_own_name(journal, meta, tmp_path):
    """同じ docx の画像が 2 つの置き場所の最初の画像になる形（グループ図形を文字のない段落に結び付けた図。C007 の形）でも、
    XML の名前は 2 回出ず、XML のどの名前の画像も ZIP に入る（置き場所ごとの名前で書き出す。W1 の途中の姿）。"""
    def body(b):
        rid = b.add_image("grp.png", mf.png_bytes("Group"))
        cap = mf.para(mf.S["fig_cap"], "図1　グループ図形の図")
        return [mf.para(mf.S["sec1"], "１．はじめに"),
                mf.para(mf.S["body"], "試験（2024）にならい，グループ図形の図を確かめる。本文の段落としての長さを持たせる。"),
                mf.para(mf.S["body"], mf.group(rid, 1800000, 1200000, cap, 730, 1800000, 1600000, wrap="wrapTopAndBottom")),
                mf.para(mf.S["body"], "以上で終わる。本文の段落としての長さを持たせるための、架空の説明の文である。")]
    path = tmp_path / "group.docx"
    mf.make_article(path, "グループ図形の検証用文書", body)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out", convert_metafiles=False))
    checks_pass(res)
    names = hrefs(load(res))
    assert len(set(names)) == len(names) and "31_1_fig01.png" in names
    zipped = {n.rsplit("/", 1)[-1] for n in zipfile.ZipFile(res.zip_path).namelist() if "/Graphics/" in n}
    assert set(names) == zipped == {i.name for i in res.images if i.status == "ok"}
