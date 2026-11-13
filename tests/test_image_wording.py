"""図の画像まわりの表示と文（数式の位置の表示・合う図がない文・「入れない」の目安・括弧の切り詰め・差し替え）。内容は架空。"""
from conftest import key_png
from jasme_jats import report as rp
from jasme_jats.app import AppState
from jasme_jats.imagelist import _shown
from jasme_jats.report import ImageRow
from test_image_carry import conv, make

OBJ = "￼"


def row(**kw):
    base = dict(key="fig06", name="31_1_fig06.png", kind="fig", label="図6", caption="", where="", place="", status="missing",
                detail="", note="")
    base.update(kw)
    return ImageRow(**base)


def test_object_mark_is_shown_as_words_everywhere():
    """数式などの位置の文字は、画面・コマンドライン・レポート・HTML で同じ「［数式など］」にし、先頭のものは除く。"""
    assert rp.shown_text(f"{OBJ}図3：{OBJ}∥{OBJ}の間") == "図3：［数式など］∥［数式など］の間"
    assert rp.shown_text("  ") == "" and rp.shown_text(None) == ""
    r = row(caption=f"{OBJ}図6：{OBJ}∥{OBJ}の間の折れ線を増やす問題②", where=f"「{OBJ}試験」の段落の後ろ")
    for text in (rp._image_line(r), rp._image_short(r), rp._cap30(r.caption), AppState.slot_label(r), _shown(r.caption)):
        assert OBJ not in text and "［数式など］" in text
    assert rp._image_short(r).startswith("fig06（図6：")
    assert _shown(r.caption) == "図6：［数式など］∥［数式など］の間の折れ線を増やす問題②"


def test_nocap_line_has_skip_hint():
    """手順 images の枠のキャプションのない行に、「入れない」の目安を添える。図の行には添えない。"""
    line = rp._image_line(row(key="img3fa9c2", kind="nocap", label="", where="「本文」の段落の後ろ"))
    assert line == "・img3fa9c2: キャプションのない画像（「本文」の段落の後ろ）。出版版 PDF で見て、ほかの図に写っている・飾りだけ、のときは「入れない」を選びます"
    assert "入れない" not in rp._image_line(row(caption="図6　折れ線"))


def test_shorten_closes_brackets():
    """場所の切り詰めで、括弧が壊れない（開いたままの括弧は閉じる）。"""
    where = "「ある短い段落」の後ろ（章「註」の中の長い長い長い長い長い節の名前）"
    short = rp.shorten_shown(where, 30)
    assert short.endswith("…）") and "（）" not in short
    assert short.count("（") == short.count("）") and short.count("「") == short.count("」")
    assert rp.shorten_shown("短い", 30) == "短い"


def test_unmatched_text_names_the_article_and_same_numbers(tmp_path, journal):
    """合う図がありません: 今の記事識別子の例と、この論文の名前の一覧を添える。"""
    res = conv(tmp_path, make(tmp_path / "a.docx", ["三角形", "四角形", "五角形"]), journal)
    text = rp.unmatched_image_text(res, "x.png", "ファイル名を直してください。")
    assert text.startswith("「x.png」に合う図がありません（この論文の画像の名前: fig01〜fig03。") and "31_1_fig01.png" in text
    assert text.endswith("ファイル名を直してください。")
    assert rp._key_ranges(["fig01", "fig02", "tab01", "img3fa9c2", "fig04", "fig04_2"]) == "fig01、fig02、tab01、img3fa9c2、fig04、fig04_2"
    rows = [row(key="fig04", label="図4"), row(key="fig04_2", label="図4")]
    assert "図4 は 2 個あるので fig04・fig04_2 の名前に" in rp._same_number_text(rows)
    assert rp._same_number_text(rows[:1]) == ""


def test_add_images_returns_keys_in_xml_order(tmp_path, journal):
    from jasme_jats.pipeline import add_images
    res = conv(tmp_path, make(tmp_path / "a.docx", ["三角形", "四角形"]), journal)
    got = add_images(res, {"fig02": ("b.png", key_png(2)), "fig01": ("a.png", key_png(1))})
    assert got == ["fig01", "fig02"]
