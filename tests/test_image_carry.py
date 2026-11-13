"""変換し直したときの画像の持ち越しと、キャプションのない画像の「入れない」（修正計画 W1 の 2.6。手順 10）。

pipeline.kept_images（変換し直す前に入れた画像を覚える）・reapply_images（変換し直した後に、同じ図だと確かめられた画像だけ入れ直す）・
add_images の skip（入れない）と、手順 images の本文・9 章・コマンドラインへの知らせ。内容は架空。
"""
import zipfile

import pytest

import make_fixtures as mf
from conftest import one_color_png
from jasme_jats.config import ArticleMeta
from jasme_jats.pipeline import Options, add_images, convert, kept_images, reapply_images
from jasme_jats.report import actions, image_rows, images_action

S = mf.S
XLINK = "{http://www.w3.org/1999/xlink}href"


def png(color) -> bytes:
    return one_color_png(color=color)


def make(path, figs, text="本文の段落である。", nocaps=(), title="持ち越しの検証用文書"):
    """図 figs（キャプションの文字の一覧。番号は「図N」を前から付ける）と、キャプションのない画像 nocaps（前の文字の一覧。
    画像の中身は前の文字ごとに違う）を並べた小さな論文を作る。"""
    def parts(b):
        out = [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], text)]
        for n, cap in enumerate(figs, 1):
            rid = b.add_image(f"c{n}.png", mf.png_bytes(f"fig {cap}"))
            out += [mf.para(S["body"], mf.drawing(rid, 1440000, 960000, 900 + n)), mf.para(S["fig_cap"], f"図{n}　{cap}")]
        for n, (before, color) in enumerate(nocaps, 1):
            rid = b.add_image(f"n{n}.png", mf.png_bytes(f"nocap {color}"))
            out += [mf.para(S["body"], before), mf.para(S["body"], mf.drawing(rid, 1440000, 960000, 950 + n))]
        return out
    mf.make_article(path, title, parts)
    return path


def conv(tmp, docx, journal, fpage="1"):
    meta = ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": fpage, "lpage": "12", "pub_date": "2026-03-31",
                                  "peer_review": "あり"})
    return convert(docx, meta, journal, Options(out_dir=tmp / "out"))


def fill(res, colors=None):
    """全部の置き場所に、置き場所ごとに色の違う PNG を入れる。"""
    need = {i.key: (f"{i.key}.png", png((n * 20 % 256, 50, 100))) for n, i in enumerate(res.images, 1) if i.status == "missing"}
    add_images(res, need)
    return need


def user(res):
    return {i.key: i for i in res.images if i.status == "user"}


def graphics(res):
    from jasme_jats.pipeline import graphics_path
    return graphics_path(res)


def again(tmp, docx, journal, res, fpage="1"):
    kept = kept_images(res)
    new = conv(tmp, docx, journal, fpage)
    return new, kept, reapply_images(new, kept)


# ---------------------------------------------------------------------------- 図・表
def test_text_edit_keeps_images_on_same_figures(tmp_path, journal):
    a = make(tmp_path / "a.docx", ["児童Aの記述", "児童Bの記述"])
    res = conv(tmp_path, a, journal)
    sent = fill(res)
    b = make(tmp_path / "b.docx", ["児童Aの記述", "児童Bの記述"], text="直した本文の段落である。")
    new, kept, put = again(tmp_path, b, journal, res)
    assert sorted(put) == ["fig01", "fig02"] and new.images_dropped == [] and new.images_changed == []
    for key, (_, data) in sent.items():                                   # 同じ図に、同じバイト列
        assert (graphics(new) / user(new)[key].name).read_bytes() == data
    assert not [a for a in actions(new) if a.key == "images" and not a.done] and not new.needs_action


def test_removed_figure_drops_only_its_image(tmp_path, journal):
    res = conv(tmp_path, make(tmp_path / "a.docx", ["児童Aが三角形を作図した場面", "平行四辺形の性質を調べた活動", "円周角の定理を見いだした場面"]), journal)
    sent = fill(res)
    # 図2（B）を消すと、図3（C）が図2 になる: B の画像は入らず、C の画像も（番号がずれた）図2 には入らない
    new, kept, put = again(tmp_path, make(tmp_path / "b.docx", ["児童Aが三角形を作図した場面", "円周角の定理を見いだした場面"]), journal, res)
    assert put == ["fig01"]
    assert [d.key for d in new.images_dropped] == ["fig02", "fig03"]
    by = {d.key: d for d in new.images_dropped}
    assert by["fig03"].suggest == "fig02" and by["fig02"].suggest == ""
    assert [i.key for i in new.images if i.status == "missing"] == ["fig02"]
    action = images_action(new)
    assert not action.done and "前に入れた画像のうち 2 枚は" in action.box_detail
    assert "前の fig03「図3\u3000円周角の定理を見いだした場面」の画像" in action.box_detail and "今の fig02「図2\u3000円周角の定理を見いだした場面」の画像と思われます" in action.box_detail
    assert "同じキャプションの図が見つかりません" in action.box_detail
    assert "入れ直しが要る前の画像" in new.report_path.read_text(encoding="utf-8")
    # 別の図の画像が入っていない
    assert (graphics(new) / user(new)["fig01"].name).read_bytes() == sent["fig01"][1]


def test_added_figure_does_not_put_old_image_on_shifted_figure(tmp_path, journal):
    res = conv(tmp_path, make(tmp_path / "a.docx", ["児童Aの記述", "児童Bの記述"]), journal)
    fill(res)
    # 先頭に図を足す: 図1 は新しい図、図2（A）・図3（B）になる
    new, kept, put = again(tmp_path, make(tmp_path / "b.docx", ["新しい図の記述", "児童Aの記述", "児童Bの記述"]), journal, res)
    assert put == []
    assert user(new) == {}
    assert {d.key: d.suggest for d in new.images_dropped} == {"fig01": "fig02", "fig02": "fig03"}
    assert "今の fig02「図2\u3000児童Aの記述」の画像と思われます" in images_action(new).box_detail


def test_swapped_figures_get_no_images(tmp_path, journal):
    res = conv(tmp_path, make(tmp_path / "a.docx", ["児童Aの記述", "全く別の事例の説明"]), journal)
    fill(res)
    new, kept, put = again(tmp_path, make(tmp_path / "b.docx", ["全く別の事例の説明", "児童Aの記述"]), journal, res)
    assert put == [] and sorted(d.key for d in new.images_dropped) == ["fig01", "fig02"]
    assert {d.key: d.suggest for d in new.images_dropped} == {"fig01": "fig02", "fig02": "fig01"}


def test_short_one_character_difference_does_not_attach_to_other_figure(tmp_path, journal):
    """「図3 児童Aの記述」「図4 児童Bの記述」の原稿に新しい図 3 を足し、新しい fig04 が「図4 児童Aの記述」になる形（点検 2 の指摘 4）。"""
    res = conv(tmp_path, make(tmp_path / "a.docx", ["X", "X", "児童Aの記述", "児童Bの記述"]), journal)
    fill(res)
    new, kept, put = again(tmp_path, make(tmp_path / "b.docx", ["X", "X", "新図", "児童Aの記述", "児童Bの記述"]), journal, res)
    assert sorted(put) == ["fig01", "fig02"]
    by = {d.key: d for d in new.images_dropped}
    assert by["fig04"].suggest == "fig05"                    # 前の fig04（B）の画像は、今の fig04（A）ではなく fig05 と思われる
    assert "fig04" not in user(new) and "fig05" not in user(new)
    assert "今の fig05「図5\u3000児童Bの記述」の画像と思われます" in images_action(new).box_detail


def test_slightly_changed_caption_carries_with_note_and_step_stays_done(tmp_path, journal):
    res = conv(tmp_path, make(tmp_path / "a.docx", ["三角形ABCの辺の長さを調べた児童の記述"]), journal)
    fill(res)
    new, kept, put = again(tmp_path, make(tmp_path / "b.docx", ["三角形ABCの辺の長さを調べた児童の記述を"]), journal, res)
    assert put == ["fig01"] and new.images_dropped == []
    assert [c.key for c in new.images_changed] == ["fig01"]
    rows = image_rows(new)
    assert "入れた後にキャプションが変わりました" in rows[0].note
    action = images_action(new)
    assert action.done and action.box_title == "図の画像 1 枚をすべて入れました（キャプションが変わった図 1 つを確かめてください）"
    assert "前「図1\u3000三角形ABCの辺の長さを調べた児童の記述」→ 今「図1\u3000三角形ABCの辺の長さを調べた児童の記述を」" in action.box_detail
    assert action.cli == action.box_detail and "fig01" in action.checklist
    assert not new.needs_action                                        # 手順は済み: 終了コード 0
    from jasme_jats import colab
    assert "児童の記述を" in colab.result_boxes(new)                    # 済んだ手順でも青い枠を出す
    assert "キャプションが変わった図に入れ直した画像" in new.report_path.read_text(encoding="utf-8")


def test_other_article_gets_no_images(tmp_path, journal):
    d = make(tmp_path / "a.docx", ["児童Aの記述"])
    res = conv(tmp_path, d, journal)
    fill(res)
    new, kept, put = again(tmp_path, d, journal, res, fpage="13")
    assert put == [] and [x.key for x in new.images_dropped] == ["fig01"]
    assert "巻・ページが変わった" in new.images_dropped[0].why and [i.status for i in new.images] == ["missing"]


def test_tracks_table_kind(tmp_path, journal):
    """幹の種類が違えば入れない（図1 が表1 に変わったなど）ため、種類も照らす。"""
    res = conv(tmp_path, make(tmp_path / "a.docx", ["児童Aの記述"]), journal)
    fill(res)
    kept = kept_images(res)
    kept["fig01"].kind = "table"
    new = conv(tmp_path, make(tmp_path / "b.docx", ["児童Aの記述"]), journal)
    assert reapply_images(new, kept) == [] and [d.key for d in new.images_dropped] == ["fig01"]


# ---------------------------------------------------------------------------- キャプションのない画像
def nocap_keys(res):
    return [i.key for i in res.images if i.kind == "nocap"]


def test_nocap_image_carries_only_with_same_place(tmp_path, journal):
    nocaps = [("一つ目の画像の前の本文である。", "red"), ("二つ目の画像の前の本文である。", "blue")]
    res = conv(tmp_path, make(tmp_path / "a.docx", [], nocaps=nocaps), journal)
    assert len(nocap_keys(res)) == 2
    fill(res)
    # 場所の文字を直した: その画像だけ入れ直さない
    edited = [("一つ目の画像の前の本文を直した。", "red"), ("二つ目の画像の前の本文である。", "blue")]
    new, kept, put = again(tmp_path, make(tmp_path / "b.docx", [], nocaps=edited), journal, res)
    assert len(put) == 1 and len(new.images_dropped) == 1
    assert "前の文章が変わっています" in new.images_dropped[0].why
    assert "キャプションなし" in images_action(new).box_detail


def test_identical_nocap_images_do_not_swap_places(tmp_path, journal):
    """同じ中身の画像が 2 か所（img…・img…_2）ある原稿で 1 つ目を消す: 2 つ目の場所に 1 つ目の画像を入れない（点検 2 の指摘 17）。"""
    same = [("最初の場所の本文である。", "same"), ("次の場所の本文である。", "same")]
    res = conv(tmp_path, make(tmp_path / "a.docx", [], nocaps=same), journal)
    keys = nocap_keys(res)
    assert len(keys) == 2 and keys[1] == keys[0] + "_2"
    add_images(res, {keys[0]: ("a.png", png((255, 0, 0))), keys[1]: ("b.png", png((0, 0, 255)))})
    new, kept, put = again(tmp_path, make(tmp_path / "b.docx", [], nocaps=[("次の場所の本文である。", "same")]), journal, res)
    assert nocap_keys(new) == [keys[0]]                                    # 残った 1 つの幹は img…（_2 でない）
    assert put == [] and [d.key for d in new.images_dropped][:1] == [keys[0]]
    assert user(new) == {}                                                 # 次の場所に 1 つ目（赤）の画像は入らない


# ---------------------------------------------------------------------------- 入れない
def test_skip_removes_element_and_excludes_from_total(tmp_path, journal):
    nocaps = [("一つ目の画像の前の本文である。", "red"), ("二つ目の画像の前の本文である。", "blue")]
    res = conv(tmp_path, make(tmp_path / "a.docx", ["児童Aの記述"], nocaps=nocaps), journal)
    k1, k2 = nocap_keys(res)
    before = res.xml_path.read_bytes()
    assert before.count(b"<graphic") == 3
    add_images(res, {}, skip=[k1])
    after = res.xml_path.read_bytes()
    assert after.count(b"<graphic") == 2 and k1.encode() not in after and k2.encode() in after   # <fig> ごと消える
    assert res.fidelity.final_ok and res.dtd_valid and res.lost_images == [] and not [a for a in actions(res) if a.key == "lost"]
    row = next(r for r in image_rows(res) if r.key == k1)
    assert row.status == "skipped" and "入れない" in row.note
    assert images_action(res).progress == "あと 2 枚／全部で 2 枚"          # 全部で 3 枚から 2 枚に
    fill(res)
    assert images_action(res).done and "入れないことにした" in images_action(res).checklist
    assert not res.needs_action
    assert not [n for n in zipfile.ZipFile(res.zip_path).namelist() if k1 in n]


def test_skip_is_carried_over_a_reconvert_and_figures_refuse_skip(tmp_path, journal):
    nocaps = [("画像の前の本文である。", "red")]
    d = make(tmp_path / "a.docx", ["児童Aの記述"], nocaps=nocaps)
    res = conv(tmp_path, d, journal)
    (key,) = nocap_keys(res)
    with pytest.raises(ValueError, match="fig01 は図・表の画像なので、「入れない」にはできません"):
        add_images(res, {}, skip=["fig01"])
    with pytest.raises(ValueError, match="この論文の画像を入れる場所ではありません"):
        add_images(res, {}, skip=["img0000"])
    with pytest.raises(ValueError, match="同時に指定できません"):
        add_images(res, {key: png((1, 2, 3))}, skip=[key])
    assert user(res) == {} and all(i.status == "missing" for i in res.images)       # 1 枚も変えていない
    add_images(res, {}, skip=[key])
    new, kept, put = again(tmp_path, d, journal, res)
    assert put == [] and next(i for i in new.images if i.key == key).status == "skipped" and new.images_dropped == []
    assert new.xml_path.read_bytes().count(b"<graphic") == 1
    # 画像を入れれば「入れない」でなくなる
    add_images(new, {key: png((9, 9, 9))})
    assert next(i for i in new.images if i.key == key).status == "user"


def test_skip_of_place_that_changed_returns_to_missing(tmp_path, journal):
    res = conv(tmp_path, make(tmp_path / "a.docx", [], nocaps=[("画像の前の本文である。", "red")]), journal)
    (key,) = nocap_keys(res)
    add_images(res, {}, skip=[key])
    new, kept, put = again(tmp_path, make(tmp_path / "b.docx", [], nocaps=[("画像の前の本文を直した。", "red")]), journal, res)
    assert next(i for i in new.images if i.key == key).status == "missing"


# ---------------------------------------------------------------------------- コマンドライン
def test_cli_no_image_and_exit_code(tmp_path, capsys):
    from conftest import META_EXAMPLE
    from jasme_jats.cli import main
    d = make(tmp_path / "a.docx", [], nocaps=[("画像の前の本文である。", "red")])
    out = tmp_path / "cli"
    assert main([str(d), "--meta", str(META_EXAMPLE), "--out", str(out)]) == 1
    err = capsys.readouterr().err
    assert "入れないときは --no-image" in err
    key = err.split("入れないときは --no-image ")[1].split("）")[0]
    assert main([str(d), "--meta", str(META_EXAMPLE), "--out", str(out), "--no-image", key]) == 0
    assert main([str(d), "--meta", str(META_EXAMPLE), "--out", str(out), "--no-image", "fig01"]) == 2
    assert "この論文の画像を入れる場所ではありません" in capsys.readouterr().err


# ---------------------------------------------------------------------------- 画面とノートブック
def test_app_reconvert_carries_images_and_drops_changed(tmp_path):
    from test_app import filled
    d1 = make(tmp_path / "A.docx", ["児童Aの記述", "児童Bの記述"])
    st = filled(tmp_path, docx=d1)
    st.convert()
    rows = st.missing_images()
    pics = {}
    for n, row in enumerate(rows):
        p = tmp_path / f"p{n}.png"
        p.write_bytes(png((n * 40, 10, 10)))
        pics[row.key] = str(p)
    st.add_images(pics)
    assert st.missing_images() == []
    st.set_inputs(docx=str(make(tmp_path / "B.docx", ["新しい図", "児童Aの記述", "児童Bの記述"])))
    st.convert()
    assert st.missing_images() and [i.status for i in st.res.images] == ["missing"] * 3      # 番号がずれたので 1 枚も入れない
    assert len(st.res.images_dropped) == 2
    st.set_inputs(docx=str(d1))
    st.convert()                                                       # 元の原稿に戻すと、覚えていた画像は消えている（1 つ前の結果が元）
    assert len(st.res.images) == 2
