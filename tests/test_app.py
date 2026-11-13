"""Gradio の操作画面（app.py。1 画面版）: AppState の遷移と、build_app が画面を組めること。ブラウザは使わない。"""
import zipfile

import pytest

from conftest import FULL, TEMPLATE, fill_images
from jasme_jats import app
from jasme_jats.app import AppState, InputError, type_choices


def filled(tmp_path, docx=FULL, **extra):
    """必須項目をそろえた状態。"""
    st = AppState(tmp_path / "work")
    st.set_inputs(route="docx", docx=str(docx), volume="31", issue="1", fpage="1", lpage="12", peer_review="査読あり",
                  manuscript_type=type_choices()[0], ai_mode="none", **extra)
    return st


def test_missing_items_block_conversion(tmp_path):
    st = AppState(tmp_path / "work")
    assert not st.can_convert()
    assert st.missing() == ["docx", "PDF", "巻", "号", "最初のページ", "最後のページ", "査読の有無", "原稿種別"]
    with pytest.raises(InputError, match="足りません: docx"):
        st.convert()
    st.set_inputs(route="docx")
    assert "PDF" not in st.missing()               # docx から作るときは PDF が要らない
    st.set_inputs(manuscript_type=app.OTHER_TYPE)
    assert "原稿種別（日本語）" in st.missing() and "原稿種別（英語）" in st.missing()
    with pytest.raises(KeyError):
        st.set_inputs(unknown="x")


def test_input_errors_are_reported(tmp_path):
    st = filled(tmp_path, approved="2026-03-31")
    st.set_inputs(peer_review="査読なし")
    with pytest.raises(InputError, match="最終査読日を空欄"):
        st.convert()
    st.set_inputs(peer_review="査読あり", received="あした")
    with pytest.raises(InputError, match="入力を確認してください"):
        st.convert()
    st.set_inputs(received="", ai_mode="api")
    with pytest.raises(InputError, match="ANTHROPIC_API_KEY"):
        st.convert(app.IO())                       # 環境変数にキーがない（下のテストで読めることも確かめる）


def test_convert_shows_summary_and_download(tmp_path):
    st = filled(tmp_path)
    res = st.convert()
    assert res is st.res and not st.waiting_for_answer
    html = st.result_html()
    assert "結果の要約" in html and "AI による補完を「使わない」" in html      # AI を使わないときの注意も出る
    # 図の画像を入れるまでは、必須の手順が残るのでダウンロードを止める（修正計画 W1）
    assert st.needs_action and st.download()[0] is None and "図の画像を入れてください" in st.download()[1]
    fill_images(st.res)
    path, note = st.download()
    assert not st.needs_action and note == ""
    assert path.endswith("変換結果_" + res.xml_path.stem + ".zip")
    assert any(n.endswith(".xml") for n in zipfile.ZipFile(path).namelist())


def test_manual_mode_waits_for_answer(tmp_path):
    st = filled(tmp_path)
    st.set_inputs(ai_mode="manual")
    st.convert()
    assert st.waiting_for_answer
    fill_images(st.res)             # 図の画像の手順（必須）を済ませる
    assert not st.needs_action      # 回答待ちは推奨の手順なので、要対応に数えない
    assert "AI の回答をまだ反映していません" not in st.result_html()    # 依頼文の欄があるので枠は出さない
    assert st.prompt_text()
    # 回答待ちは推奨の手順なので、ダウンロードを止めない
    path, note = st.download()
    assert path and note == ""
    with pytest.raises(InputError, match="貼り付けられていません"):
        st.apply_answer("  ")
    st.apply_answer('{"operations": []}')
    assert not st.waiting_for_answer


def test_next_article_clears_only_per_article_items(tmp_path):
    st = filled(tmp_path, keywords_ja="証明", keywords_en="proof", received="2025-06-01", accepted="2025-11-20", doi="10.1/x",
                pub_date="2026-03-31", approved="2025-12-01", corresp="1")
    st.set_inputs(split_labels=True, model="自動（最新の Opus）")
    st.convert()
    st.reset()
    f = st.inputs
    for k in ("docx", "pdf", "fpage", "lpage", "keywords_ja", "keywords_en", "received", "accepted", "pub_date", "epub_date",
              "approved", "doi", "corresp"):
        assert not f[k], k
    assert (f["volume"], f["issue"], f["peer_review"], f["ai_mode"], f["split_labels"], f["model"]) == (
        "31", "1", "査読あり", "none", True, "自動（最新の Opus）")
    assert f["manuscript_type"] == type_choices()[0]
    assert st.res is None and st.result_html() == "" and not (st.work / "output").exists()


def png_file(path, k=0):
    from conftest import key_png
    path.write_bytes(key_png(k))
    return path


def test_missing_images_are_filled_per_figure(tmp_path):
    from jasme_jats.report import images_action
    # 図・表の画像は作業する人が入れる（修正計画 W1）: テンプレートの図の画像も、変換の直後はまだない
    st = filled(tmp_path, docx=TEMPLATE)
    st.convert()
    rows = st.missing_images()
    assert rows and st.image_slots() == st.image_rows() == rows and st.needs_action
    md = st.images_markdown()
    assert md.startswith("### 図の画像（" + images_action(st.res).progress + "）")        # 見出しの進み具合は手順 images の progress
    assert rows[0].key in md and "「図の画像」の欄" in md and "まとめて入れる" in md
    assert st.slot_label(rows[0]) == f"{rows[0].caption.strip()[:30]}（{rows[0].key}）— 未"
    pic = png_file(tmp_path / "z_any_name.png")        # ファイル名は何でもよい。割り当ては名前の順ではなく、図ごとの指定
    last = rows[0].key                                 # テンプレートの足りない図は 1 つ（欄が複数のときも、選んだ欄だけを入れる）
    added = st.add_images({last: str(pic), "fig99": None})       # 選んでいない欄（None）は飛ばす
    assert added == [last] and last not in [r.key for r in st.missing_images()]
    assert len(st.missing_images()) == len(rows) - 1 and next(i for i in st.res.images if i.key == last).source_name == "z_any_name.png"
    assert st.slot_label(st.image_rows()[0]).endswith("— 入れた: z_any_name.png")
    assert st.images_markdown().startswith("### 図の画像（1 枚をすべて入れました）")
    with pytest.raises(InputError, match="選ばれていません"):
        st.add_images({})
    with pytest.raises(InputError, match="選ばれていません"):
        st.add_images({last: None})
    with pytest.raises(InputError, match="画像を入れる場所ではありません"):
        st.add_images({"fig99": str(pic)})             # この論文にない置き場所
    st.convert()                                       # 変換し直すと、同じ図（番号もキャプションも同じ）には入れ直す
    assert len(st.missing_images()) == len(rows) - 1 and st.res.images_dropped == []


def test_bulk_images_match_by_name(tmp_path):
    """「まとめて入れる」: 名前（fig01.png・図1.png・記事識別子つき）で図に合わせる。合わないファイル・別の記事の名前・重なりは挙げる。"""
    st = filled(tmp_path, docx=TEMPLATE)
    st.convert()
    key = st.missing_images()[0].key
    num = int(key[3:])
    aid = st.res.meta.article_id(st.res.journal)
    d = tmp_path / "pics"
    d.mkdir()
    ok = png_file(d / f"図{num}.png")
    other = png_file(d / "x_cover.png", 1)
    foreign = png_file(d / f"99_99_{key}.png", 2)             # 別の記事の識別子つき
    matched, unmatched, clashes = st.match_images([str(ok), str(other), str(foreign)])
    assert matched == {key: ok} and sorted(unmatched) == ["99_99_" + key + ".png", "x_cover.png"] and clashes == []
    both = png_file(d / f"{aid}_{key}.png", 3)                 # 同じ図に合うファイルが 2 つ: どちらも入れない
    matched, unmatched, clashes = st.match_images([str(ok), str(both)])
    assert matched == {} and unmatched == [] and clashes[0][0] == key and sorted(clashes[0][1]) == sorted([ok.name, both.name])
    assert st.match_images([]) == ({}, [], [])
    assert st.add_images(matched or {key: ok}) == [key]
    assert st.missing_images() == []


def test_skip_nocap_image_and_checkbox(tmp_path):
    """キャプションのない画像の「入れない」: 手順の「全部で」から除かれ、行のラベルは「入れない」。"""
    import test_image_carry as tic
    from conftest import fill_images
    docx = tmp_path / "nocap.docx"
    tic.make(docx, ["三角形ABC"], nocaps=[("前の文章である。", "red")])
    st = filled(tmp_path, docx=docx)
    st.convert()
    nocap = [r for r in st.image_rows() if r.kind == "nocap"]
    assert len(nocap) == 1
    key = nocap[0].key
    assert st.slot_label(nocap[0]).startswith("キャプションのない画像（") and st.slot_label(nocap[0]).endswith(f"（{key}）— 未")
    st.add_images({}, skip=[key])
    assert st.slot_label(next(r for r in st.image_rows() if r.key == key)).endswith("— 入れない")
    assert key not in [r.key for r in st.missing_images()]
    assert st.images_markdown().startswith("### 図の画像（あと 1 枚／全部で 1 枚）")      # 「全部で」から除かれる（図 1 つ）
    fill_images(st.res)
    assert not st.needs_action and st.images_markdown().startswith("### 図の画像（1 枚をすべて入れました）")
    # 画面のチェック: 入れない行は、チェックの入った状態で出る。図の行のチェックは見せない
    demo = app.build_app(st, app.IO())
    fns = {f.fn.__name__: f.fn for f in demo.fns.values()}
    n = app.MAX_IMAGE_SLOTS
    out = fns["on_images"](None, *[None] * n, *[False] * n)
    checks = out[app.FIXED_VIEWS + n:]
    rows = st.image_slots()
    assert [c["visible"] for c in checks[:len(rows)]] == [r.kind == "nocap" for r in rows]
    assert [c["value"] for c in checks[:len(rows)]] == [r.status == "skipped" for r in rows]


def test_image_slots_in_view(tmp_path):
    """build_app の画面更新: 置き場所の数だけ行を見せる。ラベルは行（report.ImageRow）から作る。上限を超えた分は見せない。"""
    import types
    import gradio as gr
    from jasme_jats.report import ImageRow
    st = AppState(tmp_path / "work")
    st.res = types.SimpleNamespace(needs_action=True)      # 模擬の結果（AI は使わない設定なので回答待ちにならない）
    st.set_inputs(ai_mode="none")
    st.result_html = lambda: ""
    st.check_html = lambda: "<i>check</i>"

    def row(k):
        return ImageRow(key=f"fig{k:02d}" if k % 2 else f"img{k:06x}", name=f"x_fig{k:02d}.png", kind="fig" if k % 2 else "nocap",
                        label=f"図{k}" if k % 2 else "", caption=f"図{k} 架空の図" if k % 2 else "", where="章1", place="", status="missing",
                        detail="", note="")
    rows = [row(k) for k in range(1, app.MAX_IMAGE_SLOTS + 4)]
    assert len(rows) > app.MAX_IMAGE_SLOTS
    st.image_rows = lambda: rows
    st.images_visible = lambda: True
    assert len(st.image_slots()) == app.MAX_IMAGE_SLOTS
    st.images_markdown = lambda: "md"
    assert st.slot_label(rows[0]) == "図1 架空の図（fig01）— 未"
    assert st.slot_label(rows[1]) == "キャプションのない画像（章1）（img000002）— 未"
    demo = app.build_app(st, app.IO())
    assert isinstance(demo, gr.Blocks)
    fns = {f.fn.__name__: f.fn for f in demo.fns.values()}
    n = app.MAX_IMAGE_SLOTS
    out = fns["on_images"](None, *[None] * n, *[False] * n)               # 何も選ばないとエラー（画面の更新の数は変わらない）
    assert len(out) == app.FIXED_VIEWS + 2 * n and "選ばれていません" in out[0] and out[9] == "<i>check</i>"
    files = out[app.FIXED_VIEWS:app.FIXED_VIEWS + n]
    checks = out[app.FIXED_VIEWS + n:]
    assert files[0]["visible"] and files[0]["label"] == "図1 架空の図（fig01）— 未" and files[0]["value"] is None and all(u["visible"] for u in files)
    assert [c["visible"] for c in checks[:3]] == [False, True, False]      # 「入れない」はキャプションのない画像の行だけ
    st.image_rows = lambda: rows[:2]
    out = fns["on_images"](None, *[None] * n, *[False] * n)
    files = out[app.FIXED_VIEWS:app.FIXED_VIEWS + n]
    assert [u["visible"] for u in files] == [True, True] + [False] * (n - 2)


def test_on_images_bulk_skip_and_notes(tmp_path):
    """画面の「画像を入れる」: まとめて入れる（名前で合わせる）・図ごとの行・「入れない」のチェック。合わないファイルは知らせる。"""
    st = filled(tmp_path, docx=TEMPLATE)
    demo = app.build_app(st, app.IO())
    fns = {f.fn.__name__: f.fn for f in demo.fns.values()}
    values = [st.inputs[k] for k in app.INPUT_NAMES]
    out = fns["on_convert"](*values)
    n = app.MAX_IMAGE_SLOTS
    F = app.FIXED_VIEWS
    key = st.missing_images()[0].key
    assert out[4]["visible"] and out[5].startswith("### 図の画像（あと 1 枚") and "図の画像" in out[1] and "図の画像を入れてください" not in out[1]
    pic = png_file(tmp_path / f"{key}.png")
    stray = png_file(tmp_path / "stray.png", 1)
    out = fns["on_images"]([str(pic), str(stray)], *[None] * n, *[False] * n)
    assert st.missing_images() == [] and out[5].startswith("### 図の画像（1 枚をすべて入れました）")
    assert "「stray.png」に合う図がありません（この論文の画像の名前: " in out[0] and "<iframe" in out[9]
    assert out[F]["label"].endswith("— 入れた: " + pic.name) and out[8] is None
    # 行で選んだ画像と、まとめて入れた画像が同じ図に合うときは、行の画像を使い、まとめての方は入れなかったと知らせる
    row_pic = png_file(tmp_path / "row.png", 2)
    out = fns["on_images"]([str(pic)], row_pic.as_posix(), *[None] * (n - 1), *[False] * n)
    assert next(i for i in st.res.images if i.key == key).source_name == "row.png"
    assert f"「{pic.name}」は、図ごとの行で画像を選んだ図（{key}）に合ったので、入れていません" in out[0]


def test_on_images_unchecking_skip_returns_to_missing(tmp_path):
    """「入れない」のチェックを外して「画像を入れる」を押すと、「入れない」をやめて未に戻る（点検 9）。"""
    from test_image_carry import make
    d = make(tmp_path / "n.docx", [], nocaps=[("画像の前の本文である。", "red")])
    st = filled(tmp_path, docx=d)
    demo = app.build_app(st, app.IO())
    fns = {f.fn.__name__: f.fn for f in demo.fns.values()}
    fns["on_convert"](*[st.inputs[k] for k in app.INPUT_NAMES])
    n = app.MAX_IMAGE_SLOTS
    F = app.FIXED_VIEWS
    (row,) = st.image_slots()
    assert row.kind == "nocap"
    out = fns["on_images"](None, *[None] * n, True, *[False] * (n - 1))
    assert st.image_slots()[0].status == "skipped" and out[F + n]["value"] is True
    out = fns["on_images"](None, *[None] * n, *[False] * n)                 # チェックを外す
    assert st.image_slots()[0].status == "missing" and out[F + n]["value"] is False and "選ばれていません" not in out[0]
    assert "チェックを外して" in st.images_markdown()
    # 「入れない」にチェックが付いた画像に、まとめて入れた画像が合ったときは入れず、知らせる
    pic = png_file(tmp_path / f"{row.key}.png")
    out = fns["on_images"]([str(pic)], *[None] * n, True, *[False] * (n - 1))
    assert st.image_slots()[0].status == "skipped" and "「入れない」にチェックが付いた画像" in out[0]


def test_images_stay_through_rebuild_and_reset(tmp_path):
    """変換し直し・回答の反映の後も入れた画像が残る（同じ図）。「次の論文」で捨てる。残っているとダウンロードが止まり、チェックで通る。"""
    st = filled(tmp_path, docx=TEMPLATE)
    st.set_inputs(ai_mode="manual")
    st.convert()
    key = st.missing_images()[0].key
    path, note = st.download()
    assert path is None and "図の画像を入れてください" in note and "このままダウンロード" in note      # 歯止め
    zpath, note = st.download(accept_todo=True)
    assert zpath and note == ""                                                                      # チェックで通る
    st.add_images({key: str(png_file(tmp_path / "a.png"))})
    st.apply_answer(EMPTY_ANSWER)                                                                   # 回答の反映（変換し直し）
    assert st.missing_images() == [] and next(i for i in st.res.images if i.key == key).status == "user"
    st.convert()                                                                                    # 変換し直し
    assert st.missing_images() == [] and st.images_markdown().startswith("### 図の画像（1 枚をすべて入れました）")
    st.reset()
    assert st.kept == {} and st.res is None and st.images_markdown() == "" and not st.images_visible()
    assert st.image_slots() == [] and st.check_html() == ""


def test_more_than_max_slots_points_to_bulk(tmp_path):
    """行は MAX_IMAGE_SLOTS 個まで。31 個目からは「まとめて入れる」の案内を出し、まとめて入れれば全部入る。"""
    import test_image_carry as tic
    docx = tmp_path / "many.docx"
    n = app.MAX_IMAGE_SLOTS + 2
    tic.make(docx, [f"図の{k}" for k in range(1, n + 1)])
    st = filled(tmp_path, docx=docx)
    st.convert()
    assert len(st.image_rows()) == n and len(st.image_slots()) == app.MAX_IMAGE_SLOTS
    assert f"図ごとの行は {app.MAX_IMAGE_SLOTS} 個までです" in st.images_markdown() and "「まとめて入れる」で入れてください" in st.images_markdown()
    d = tmp_path / "pics"
    d.mkdir()
    paths = [str(png_file(d / f"図{k}.png", k)) for k in range(1, n + 1)]
    matched, unmatched, clashes = st.match_images(paths)
    assert len(matched) == n and unmatched == [] and clashes == []
    assert len(st.add_images(matched)) == n and st.missing_images() == []
    assert "図ごとの行は" in st.images_markdown()                        # 行の数は変わらない（入れた行も残る）


def test_io_reads_secrets(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    io = app.IO()
    assert io.read_secret(("ANTHROPIC_API_KEY",)) is None
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key")
    assert io.read_secret(("ANTHROPIC_API_KEY",)) == "key"
    assert not hasattr(app.IO, "libreoffice_ready") and not hasattr(app.ColabIO, "libreoffice_ready")      # LibreOffice は使わない


def test_build_app_and_launch_never_share(tmp_path, monkeypatch):
    import gradio as gr
    demo = app.build_app(AppState(tmp_path / "work"), app.IO())
    assert isinstance(demo, gr.Blocks)
    seen = {}
    monkeypatch.setattr(gr.Blocks, "launch", lambda self, **kw: seen.update(kw))
    monkeypatch.setattr(app, "_in_colab", lambda: False)
    app.launch(inline=False)                       # Colab の外: ローカルのサーバーをブラウザで開く
    assert seen["share"] is False and seen["inline"] is False
    # Colab では、中継の URL を root_path にして（ダウンロードのリンクが中継を通る）、出力欄に大きく埋め込む
    monkeypatch.setattr(app, "_in_colab", lambda: True)
    monkeypatch.setattr(app, "colab_proxy_url", lambda port: f"https://x-{port}-colab.googleusercontent.com/?authuser=0")
    embedded = []
    monkeypatch.setattr(app, "colab_embed", lambda port, height: embedded.append((port, height)))
    seen.clear()
    app.launch()
    assert seen["share"] is False and seen["inline"] is False and seen["prevent_thread_lock"] is True
    assert seen["root_path"] == f"https://x-{seen['server_port']}-colab.googleusercontent.com"
    assert embedded == [(seen["server_port"], 1400)]


def test_download_button_fetches_in_page():
    """「ZIP を保存」は、Gradio のファイルの経路を画面の中の fetch で取ってから保存する（Colab の中継はリンク先への移動では開けない）。"""
    html = app.download_button_html("/content/jasme_work/変換結果_31_1.zip")
    assert "fetch('gradio_api/file=/content/jasme_work/%E5%A4%89%E6%8F%9B%E7%B5%90%E6%9E%9C_31_1.zip')" in html
    # onclick の中の引用符は HTML の実体にする（属性の中なので、JavaScript になる前に戻る）。リンク（<a href>）は出さない
    assert "window.URL.createObjectURL" in html and "=URL.createObjectURL" not in html
    assert "a.download=&#x27;変換結果_31_1.zip&#x27;" in html and "ZIP を保存（変換結果_31_1.zip）" in html and "<a " not in html



def test_images_box_uses_app_words(tmp_path):
    """図の画像の手順の枠は、1 画面版では手順の番号ではなく欄の名前で書く（O2）。ノートブックの枠（既定）は手順 7 のまま。"""
    import re
    from jasme_jats.colab import missing_images_box, result_boxes
    st = filled(tmp_path, docx=TEMPLATE)
    st.convert()
    md = st.images_markdown()
    assert "「図の画像」の欄で入れてください" in md and "\x00" not in md and md.startswith("### 図の画像")     # 語の指す見出しが、実際の欄の見出し
    assert "図の画像を入れてください" not in st.result_html()           # 手順 images は「図の画像」の欄に出し、結果の枠では重ねない
    # レポート全文（畳んだ部分）には「ノートブックは手順 N」と両方の言い方がある。枠の見出しの前の「手順」は手順の区分の印
    assert not re.search(r"手順 ?[0-9]", result_boxes(st.res, screen="app"))
    assert "手順 7「図の画像を入れる」で入れてください" in missing_images_box(st.res)
    assert "図の画像を入れてください" in result_boxes(st.res, screen="app")      # 結果の枠そのものは、手順 images も含む（app は skip する）


def test_unexpected_error_is_shown_and_old_result_dropped(tmp_path, monkeypatch):
    """変換が想定外の例外で止まったとき、前の結果を捨てる（消えた出力フォルダを指さない）。画面には例外の種類と文を赤い枠で出す（O1）。"""
    import types
    st = filled(tmp_path)
    st.convert()
    zip_before, _ = st.download(accept_todo=True)
    assert st.res is not None and zip_before
    st.set_inputs(ai_mode="manual")

    def boom(*args, **kwargs):
        raise RuntimeError("こわれた")
    monkeypatch.setattr(app, "convert", boom)
    demo = app.build_app(st, app.IO())
    fns = {f.fn.__name__: f.fn for f in demo.fns.values()}
    values = [st.inputs[n] for n in app.INPUT_NAMES]
    st.inputs["ai_mode"] = "manual"
    out = fns["on_convert"](*values)                   # 例外を画面の外へ出さない
    assert st.res is None and not st.waiting_for_answer and not st.needs_action
    assert "想定外のエラーで止まりました" in out[0] and "RuntimeError: こわれた" in out[0] and "開発者に知らせてください" in out[0]
    assert "変換レポートは作られていません" in out[0] and out[1] == ""
    # 変換で落ちたときは入力を確かめて変換し直す案内（F15）
    assert "「変換する」をもう一度押してください" in out[0]
    assert "入力（「docx（論文の Word ファイル）」の欄・「PDF（J-STAGE に登載する PDF）」の欄・巻・号・ページなどの入力欄）が正しいかを確かめ" in out[0]
    # 回答の反映（_run を直接呼ぶ）でも、前の結果を残さない
    st.res = types.SimpleNamespace(report_path=tmp_path / "ない.md", needs_action=True)
    with pytest.raises(RuntimeError):
        st._run("manual", "{}")
    assert st.res is None
    st.res = None
    out = fns["on_download"](False)
    assert "先に変換してください" in out[0]
    # 結果があるのに ZIP を作れない（出力フォルダが消えている）ときも、例外を出さずに枠で知らせる
    st.res = types.SimpleNamespace(report_path=tmp_path / "ない.md", needs_action=False,
                                   xml_path=tmp_path / "a" / "x.xml")
    out = fns["on_download"](False)
    assert "想定外のエラーで止まりました" in out[0] and out[7] == ""
    # 結果は画面に残っているが、出力フォルダ（変換レポートのファイル）がない: 「作られていません」と「画面に残っている」を並べず、
    # 画面の全文を添えて知らせ、同じ操作をもう一度しても止まることを案内する
    assert "変換レポートは作られていません" not in out[0] and "この画面の「変換レポートの全文を見る」の内容" in out[0]
    assert "出力フォルダが見つからず" in out[0] and "同じ例外で止まります" in out[0]
    assert "もう一度ダウンロードの操作をしてかまいません" not in out[0] and "結果はこの画面に残っています" not in out[0]


def test_unexpected_error_in_apply_answer(tmp_path, monkeypatch):
    """回答の反映での想定外の例外も、枠に出す。変換レポートがあれば、この画面の全文を案内する（場所のパスは書かない）。"""
    import types
    st = filled(tmp_path)
    st.set_inputs(ai_mode="manual")
    st.convert()
    report = st.res.report_path
    demo = app.build_app(st, app.IO())
    fns = {f.fn.__name__: f.fn for f in demo.fns.values()}

    def boom(*args, **kwargs):
        raise OSError("書けません")
    monkeypatch.setattr(app, "convert", boom)
    out = fns["on_apply"]('{"operations": []}')
    assert st.res is None and "OSError: 書けません" in out[0]
    assert "変換レポートは作られていません" in out[0] and str(report) not in out[0]     # 出力フォルダを消したので、前のレポートはない
    # 反映で落ちたときは、回答や入力を消す「変換する」の押し直しを勧めない。別に保存することと、開発者に知らせることを案内する（F15）
    # 前の結果を捨てたので手動の欄は隠れる。貼り付けた文字は欄に残る（views に answer がない）ので、そのとおりに案内する
    assert out[2]["visible"] is False and "手動の欄" in out[0] and "隠れています" in out[0] and "欄に残っています" in out[0]
    # H5: 欄が隠れている間は保存できないので、「別の場所にも保存」は、欄が戻る「変換する」の案内の後に言う
    assert out[0].index("隠れています") < out[0].index("「変換する」をもう一度押すと") < out[0].index("欄が戻ったら") < out[0].index("別の場所")
    assert "欄に残っているはず" not in out[0] and "隠れています。貼り付けた回答" not in out[0]
    assert "「変換する」をもう一度押してください" not in out[0] and "使えなくなる" not in out[0]
    # レポートが残っているときも、サーバー側のパスは書かない（利用者は取り出せない）。この画面の変換レポートの全文を案内する
    st.res = types.SimpleNamespace(report_path=report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("x", encoding="utf-8")
    html = st.crash(RuntimeError("y"), "images").html
    assert str(report) not in html and "変換レポートの全文を見る" in html
    assert "入れた画像と変換の結果は、この画面に残っています" in html and "入れた画像が消えます" not in html
    assert "「変換する」をもう一度押してください" not in html
    with pytest.raises(ValueError):
        st.crash(RuntimeError("y"), "other")


def test_download_crash_with_output_folder_gone(tmp_path):
    """結果が画面に残っているのに出力フォルダが消えていてダウンロードできないとき（実際に変換してから消す）、
    「変換レポートは作られていません」と「結果はこの画面に残っています」を並べず、状況に合う 1 つの案内にする。"""
    import shutil
    st = filled(tmp_path)
    st.convert()
    shutil.rmtree(st.out_dir)
    demo = app.build_app(st, app.IO())
    fns = {f.fn.__name__: f.fn for f in demo.fns.values()}
    out = fns["on_download"](True)        # 残っている手順（図の画像）があっても、このままダウンロードする
    assert out[7] == "" and "想定外のエラーで止まりました" in out[0]
    assert "変換レポートは作られていません" not in out[0] and "結果はこの画面に残っています" not in out[0]
    assert "この画面の「変換レポートの全文を見る」" in out[0] and "同じ例外で止まります" in out[0]
    assert "「変換する」をもう一度押してください" in out[0]


def test_manual_fields_stay_for_repaste(tmp_path):
    """手動モードで回答を反映した後、回答を貼り直す必要がある枠（回答を読めない・途中で切れた・図表の位置が決まらない）が出ているときは、
    枠の「「AI の回答」の欄に貼り付け直して「反映」を押し」のとおりに、手動の欄（依頼文・「AI の回答」・「反映」）を見せたままにする。
    貼り直す必要がなくなったら隠す。画面の更新（on_apply の戻り）で確かめる。"""
    import json
    from conftest import FLOAT
    from test_ai import FLOAT_RESPONSE, cut_cases
    from jasme_jats.colab import result_boxes
    from jasme_jats.report import actions
    st = AppState(tmp_path / "work")
    st.set_inputs(route="docx", docx=str(FLOAT), volume="31", issue="1", fpage="1", lpage="12", peer_review="査読あり",
                  manuscript_type=type_choices()[0], ai_mode="manual")
    demo = app.build_app(st, app.IO())
    fns = {f.fn.__name__: f.fn for f in demo.fns.values()}
    out = fns["on_convert"](*[st.inputs[n] for n in app.INPUT_NAMES])
    assert out[2]["visible"] is True and out[3]                       # 回答待ち: 依頼文が出る
    cases = {"ai_error": "これは JSON ではない", "forced": '{"placements": [], "operations": [], "notes": []}',
             "partial": cut_cases()["c"]}
    for key, text in cases.items():
        out = fns["on_apply"](text)
        assert key in [a.key for a in actions(st.res)], key
        assert not st.waiting_for_answer
        assert out[2]["visible"] is True, key                         # 手動の欄を見せたまま
        assert out[3] == st.prompt_text() and out[3], key               # 依頼文も出る
        boxes = result_boxes(st.res, screen="app")
        # 枠が回答の貼り直しを案内している（途中で切れた回答の枠は「新しい回答を最初から最後まで貼り付けて変換し直します」）
        assert ("新しい回答を最初から最後まで貼り付けて" if key == "partial" else "貼り付け直して「反映」を押し") in boxes, key
    out = fns["on_apply"](json.dumps(FLOAT_RESPONSE, ensure_ascii=False))     # 貼り直した回答で決まれば、欄を隠す
    fill_images(st.res)                                                       # 図の画像の手順（必須）を済ませる
    assert not st.needs_action and out[2]["visible"] is False and out[3] == ""
    # 変換の後に「AI による補完の方法」の欄を変えても判定は変わらない（O3）。この時点では貼り直す枠がないので欄は出ない
    st.set_inputs(ai_mode="none")
    assert not st.answer_box_open


def test_apply_crash_hides_manual_fields_as_advised(tmp_path, monkeypatch):
    """回答の反映の想定外の例外（前の結果を捨てる）のあとの画面は、案内のとおり: 手動の欄は隠れ、「変換する」を押すと欄が戻る。"""
    st = filled(tmp_path)
    st.set_inputs(ai_mode="manual")
    demo = app.build_app(st, app.IO())
    fns = {f.fn.__name__: f.fn for f in demo.fns.values()}
    values = [st.inputs[n] for n in app.INPUT_NAMES]
    assert fns["on_convert"](*values)[2]["visible"] is True
    real = app.convert

    def boom(*args, **kwargs):
        raise OSError("書けません")
    monkeypatch.setattr(app, "convert", boom)
    out = fns["on_apply"]('{"operations": []}')
    assert out[2]["visible"] is False and "隠れています" in out[0] and "「変換する」をもう一度押すと" in out[0]
    monkeypatch.setattr(app, "convert", real)
    assert fns["on_convert"](*values)[2]["visible"] is True            # 案内のとおり、欄が戻る


def test_apply_crash_before_result_dropped_keeps_manual_fields(tmp_path, monkeypatch):
    """回答の反映が、前の結果を捨てる前に想定外の例外で止まったとき（変換の設定を作れないなど）は、手動の欄も結果も
    画面に残っている。案内も「欄は隠れている」ではなく、残っていることを言う。"""
    st = filled(tmp_path)
    st.set_inputs(ai_mode="manual")
    demo = app.build_app(st, app.IO())
    fns = {f.fn.__name__: f.fn for f in demo.fns.values()}
    assert fns["on_convert"](*[st.inputs[n] for n in app.INPUT_NAMES])[2]["visible"] is True

    def boom(*args, **kwargs):
        raise OSError("写せません")
    monkeypatch.setattr(app, "Options", boom)
    out = fns["on_apply"]('{"operations": []}')
    assert st.res is not None and out[2]["visible"] is True
    assert "OSError: 写せません" in out[0] and "そのまま残っています" in out[0] and "隠れています" not in out[0]
    assert "変換レポートは作られていません" not in out[0]


def test_app_words_match_the_real_labels(tmp_path):
    """0.29.0 の最後の点検の (e)(f): colab.STEP_WORDS の 1 画面版の語が、画面の実際のラベル（欄・ボタン）で探せる。
    app.CRASH_ADVICE の案内は STEP_WORDS の語で組み立てる（「AI の回答」だけのような、実際のラベルと違う語を直接書かない）。"""
    import re

    from jasme_jats import colab
    from jasme_jats.report import STEP_NAMES
    st = AppState(tmp_path / "work")
    demo = app.build_app(st, app.IO())
    labels = {getattr(b, "label", None) for b in demo.blocks.values()} | {getattr(b, "value", None) for b in demo.blocks.values()}
    for label in (colab.ANSWER_LABEL, colab.APPLY_LABEL, colab.CONVERT_LABEL, "作り方", "AI による補完の方法",
                  "docx（論文の Word ファイル）", "PDF（J-STAGE に登載する PDF）"):
        assert label in labels, label
    words = colab.STEP_WORDS["app"]
    assert set(words) == set(STEP_NAMES)
    # 語の中の「…」で囲んだ名前は、画面のラベルにある（選択肢の名前を除く）。「AI の回答」だけの略は書かない
    quoted = {q for w in words.values() for q in re.findall(r"「([^」]+)」", w)}
    choices = {"手動（チャットに貼り付け）", "API（Claude）", "docx から作り、出版版 PDF で補う", "図の画像"}
        # 「図の画像」は結果の下の欄の見出し（AppState.images_markdown の "### 図の画像"。test_images_box_uses_app_words で確かめる）
    assert quoted - choices <= labels, quoted - choices - labels
    assert "AI の回答" not in quoted
    # CRASH_ADVICE は語の表から組み立てている: 実際のラベルが入り、略した名前・直接書いた名前はない
    texts = list(app.AppState.CRASH_ADVICE.values()) + [app.AppState.CRASH_ADVICE_APPLY_KEPT, app.AppState.CRASH_ADVICE_FOLDER_GONE]
    for t in texts:
        assert "\x00" not in t and "「AI の回答」" not in t and "手順" not in t
    assert f"「{colab.ANSWER_LABEL}」の欄" in app.AppState.CRASH_ADVICE["apply"]
    assert f"「{colab.CONVERT_LABEL}」をもう一度押" in app.AppState.CRASH_ADVICE["convert"]
    assert words["docx"] in app.AppState.CRASH_ADVICE["convert"] and words["meta"] in app.AppState.CRASH_ADVICE["convert"]


# ---------------------------------------------------------------------------- 入力の写し（0.30.0。u2-app）
def make_pair(tmp_path):
    """本文の段落の形が同じで、題目と本文の文字だけ違う架空の論文 A・B。"""
    import make_fixtures as mf
    S = mf.S

    def parts(word):
        return lambda b: [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], f"{word}の本文。試験（2024）を引く。"),
                          mf.para(S["body"], f"{word}の二つ目の段落。")]
    a, b = tmp_path / "A.docx", tmp_path / "B.docx"
    mf.make_article(a, "論文Aの題目", parts("論文A"))
    mf.make_article(b, "論文Bの題目", parts("論文B"))
    return a, b


def xml_root(res):
    from lxml import etree
    return etree.fromstring(res.xml_path.read_bytes().split(b"\n", 2)[2])


def xml_text(res):
    return "".join(xml_root(res).itertext())


def exclude_answer(res, word):
    """本文の「二つ目の段落」を除外する AI の回答（src は res の段落 ID）。"""
    import json
    cand = [pid for pid, p in res.plan.paras.items() if word in str(getattr(p, "text", "") or getattr(p, "plain", "") or p)]
    assert cand, "段落が見つからない"
    return json.dumps({"placements": [], "operations": [{"op": "set_role", "src": cand[0], "text": "", "occurrence": 1,
                                                         "target": "", "role": "exclude", "image": "", "confidence": "高",
                                                         "reason": "試験"}], "notes": []}, ensure_ascii=False)


EMPTY_ANSWER = '{"placements": [], "operations": [], "notes": []}'


def check_text(t):
    assert "\x00" not in t and "手順" not in t


def test_inputs_changed_after_convert_are_refused(tmp_path):
    a, b = make_pair(tmp_path)
    st = filled(tmp_path, docx=a)
    st.set_inputs(ai_mode="manual")
    res = st.convert()
    st.set_inputs(docx=str(b), fpage="77")
    assert st.changed_inputs() == ["docx", "最初のページ"]
    with pytest.raises(InputError) as ei:
        st.apply_answer(EMPTY_ANSWER)
    msg = str(ei.value)
    check_text(msg)
    assert "入力が前回の変換から変わっています" in msg and "「変換する」をもう一度押してください" in msg and "新しい依頼文が出る" in msg
    assert st.res is res and "<fpage>1</fpage>" in res.xml_path.read_text(encoding="utf-8")
    assert st.download() == (None, msg) and st.download(accept_todo=True) == (None, msg)
    assert "入力が前回の変換から変わっています" in st.ready_text() and "入力が前回の変換から変わっています" not in st.result_html()
    st.set_inputs(docx=str(a), fpage=" １ ")
    assert st.changed_inputs() == []
    st.apply_answer(EMPTY_ANSWER)
    assert "論文Aの題目" in xml_text(st.res)
    # ページだけを変えたときは、欄の回答でもう一度反映する案内
    st.set_inputs(fpage="2")
    text = st.stale_text(st.changed_inputs())
    assert "貼り付けた回答は欄に残る" in text and "もう一度「反映」を押します" in text and "新しい依頼文が出る" not in text
    check_text(text)


def test_same_file_reselected_is_not_a_change(tmp_path, monkeypatch):
    a, b = make_pair(tmp_path)
    st = filled(tmp_path, docx=a)
    st.set_inputs(ai_mode="manual")
    st.convert()
    copy = tmp_path / "gradio" / "A.docx"
    copy.parent.mkdir()
    copy.write_bytes(a.read_bytes())
    st.set_inputs(docx=str(copy))
    assert st.changed_inputs() == []
    copy.write_bytes(a.read_bytes() + b"\0")
    assert st.changed_inputs() == ["docx"]
    demo = app.build_app(st, app.IO())
    fns = {f.fn.__name__: f.fn for f in demo.fns.values()}
    st.set_inputs(docx=None)
    assert st.changed_inputs() == ["docx"]
    out = fns["on_apply"](EMPTY_ANSWER)
    assert "入力が前回の変換から変わっています" in out[0] and "想定外のエラー" not in out[0]
    # ファイルを読めないとき: 例外を外に出さない。変換は「読めませんでした」で断り、前の結果と写しを残す
    st.set_inputs(docx=str(a))
    res, run = st.res, st.run

    def bad(path):
        raise OSError("読めません")
    monkeypatch.setattr(app, "file_digest", bad)
    values = [st.inputs[n] for n in app.INPUT_NAMES]
    fns["on_change"](*values)
    out = fns["on_apply"](EMPTY_ANSWER)
    assert "入力が前回の変換から変わっています" in out[0] and "想定外のエラー" not in out[0]
    with pytest.raises(InputError, match="のファイルを読めませんでした") as ei:
        st.convert()
    check_text(str(ei.value))
    assert st.res is res and st.run is run


def test_images_not_carried_to_changed_input(tmp_path, monkeypatch):
    import dataclasses
    import io
    from PIL import Image
    a, b = make_pair(tmp_path)
    real = app.convert
    monkeypatch.setattr(app, "convert", lambda d, m, j, o: real(d, m, j, dataclasses.replace(o)))
    st = filled(tmp_path, docx=TEMPLATE)
    st.set_inputs(ai_mode="manual")
    st.convert()
    rows = st.missing_images()
    pic = png_file(tmp_path / "pic.png")
    st.add_images({rows[0].key: str(pic)})
    st.set_inputs(docx=str(b))
    for call in (lambda: st.add_images({rows[0].key: str(pic)}), lambda: st.apply_answer(EMPTY_ANSWER)):
        with pytest.raises(InputError, match="入力が前回の変換から変わっています"):
            call()
    st.convert()
    # 別の原稿には、前の画像を入れない（図がないので記録に残る）
    assert "論文Bの題目" in xml_text(st.res) and [d.key for d in st.res.images_dropped] == [rows[0].key]


def test_ai_mode_change_after_convert_keeps_screen(tmp_path):
    """O3: 変換の後に「AI による補完の方法」の欄を変えても、手動の欄・結果の枠は変わらない。"""
    st = filled(tmp_path)
    st.set_inputs(ai_mode="manual")
    st.convert()
    for mode in ("api", "none"):
        st.set_inputs(ai_mode=mode)
        assert st.waiting_for_answer and st.answer_box_open
        html = st.result_html()
        assert "AI の回答をまだ反映していません" not in html and "AI による補完を「使わない」" not in html
        assert st.changed_inputs() == [] and "次に変換するときに使われます" in st.ready_text()
        check_text(st.settings_note())
    st.apply_answer(EMPTY_ANSWER)
    st2 = filled(tmp_path / "x")
    st2.convert()                                   # ai_mode="none"
    st2.set_inputs(ai_mode="manual")
    assert not st2.answer_box_open
    with pytest.raises(InputError, match="手動モードで変換してから"):
        st2.apply_answer(EMPTY_ANSWER)


def test_failed_convert_keeps_previous_run(tmp_path, monkeypatch):
    st = filled(tmp_path)
    res = st.convert()
    run = st.run
    st.set_inputs(fpage="77", ai_mode="api")
    monkeypatch.delenv(app.API_KEY_NAMES["claude"][0], raising=False)
    for name in app.API_KEY_NAMES["claude"]:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(InputError, match="API キー"):
        st.convert(app.IO())
    assert st.run is run and st.run.meta.fpage == "1" and st.res is res
    assert st.changed_inputs() == ["最初のページ"]
    path, note = st.download()
    assert path is None and "入力が前回の変換から変わっています" in note


def test_new_paper_clears_answer_field(tmp_path):
    a, b = make_pair(tmp_path)
    st = filled(tmp_path, docx=a)
    st.set_inputs(ai_mode="manual")
    demo = app.build_app(st, app.IO())
    fns = {f.fn.__name__: f.fn for f in demo.fns.values()}
    n_views = app.FIXED_VIEWS + 2 * app.MAX_IMAGE_SLOTS

    def values(**kw):
        st.set_inputs(**kw)
        return [st.inputs[n] for n in app.INPUT_NAMES]
    out = fns["on_convert"](*values())
    assert len(out) == n_views + 2 and "value" not in out[-2]
    out = fns["on_convert"](*values(docx=str(b)))
    assert out[-2].get("value") == ""
    out = fns["on_convert"](*values(docx=str(a)))
    assert out[-2].get("value") == ""                 # b -> a: また別の論文
    out = fns["on_convert"](*values())
    assert "value" not in out[-2]                     # 同じ docx の変換し直しでは残す
    out = fns["on_convert"](*values(docx=str(b)))
    out = fns["on_convert"](*values(received="あした"))
    assert "入力を確認してください" in out[0] and "value" not in out[-2]
    # ready: 入力を変えると文が出て、変換に成功すると空になる
    out = fns["on_change"](*values(received="", fpage="9"))
    assert "入力が前回の変換から変わっています" in out[1]
    out = fns["on_convert"](*values())
    assert out[-1] == ""


def test_previous_paper_answer_refused(tmp_path):
    import zipfile as zf
    import make_fixtures as mf
    a, b = make_pair(tmp_path)
    st = filled(tmp_path, docx=a)
    st.set_inputs(ai_mode="manual")
    res_a = st.convert()
    ans_a = exclude_answer(res_a, "二つ目")
    st.apply_answer(ans_a)

    def switch(path):
        st.set_inputs(docx=str(path))
        st.convert()
    switch(b)
    with pytest.raises(InputError, match="前に別の依頼文（A.docx のとき）に対して反映した AI の回答です") as ei:
        st.apply_answer(ans_a)
    check_text(str(ei.value))
    assert "論文Bの二つ目の段落" in xml_text(st.res)
    st.reset()
    st.set_inputs(docx=str(b), volume="31", issue="1", fpage="1", lpage="12", peer_review="査読あり",
                  manuscript_type=type_choices()[0], ai_mode="manual", route="docx")
    st.convert()
    with pytest.raises(InputError, match="前に別の依頼文"):
        st.apply_answer(ans_a)
    st.apply_answer(EMPTY_ANSWER)                      # 違う回答は通る
    # A と同じ中身（別のパス）・依頼文の変わらない同名の直した版では、ans_A が通る
    same = tmp_path / "copy" / "A.docx"
    same.parent.mkdir()
    same.write_bytes(a.read_bytes())
    switch(same)
    st.apply_answer(ans_a)
    fixed = tmp_path / "fixed" / "A.docx"
    fixed.parent.mkdir()
    with zf.ZipFile(a) as src, zf.ZipFile(fixed, "w", zf.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "docProps/core.xml":        # 更新日だけを書き換える（本文は変えない）
                data = data.replace(b"</cp:coreProperties>", b"<dcterms:modified xmlns:dcterms='http://purl.org/dc/terms/'>2030-01-01</dcterms:modified></cp:coreProperties>")
                assert data != src.read(item.filename)
            dst.writestr(item, data)
    switch(b)
    st.apply_answer(EMPTY_ANSWER)
    switch(fixed)
    st.apply_answer(ans_a)
    # 依頼文が変わる（本文の段落を足した A）なら断る
    longer = tmp_path / "longer" / "A.docx"
    longer.parent.mkdir()
    S = mf.S
    mf.make_article(longer, "論文Aの題目", lambda b_: [mf.para(S["sec1"], "１．はじめに"), mf.para(S["body"], "論文Aの本文。試験（2024）を引く。"),
                                                       mf.para(S["body"], "論文Aの二つ目の段落。"), mf.para(S["body"], "足した段落。")])
    switch(longer)
    with pytest.raises(InputError, match="前に別の依頼文"):
        st.apply_answer(ans_a)


def test_stopped_convert_leaves_no_stale_text(tmp_path):
    from conftest import FLOAT
    st = filled(tmp_path)
    st.convert()
    st.set_inputs(docx=str(FLOAT))
    with pytest.raises(InputError):
        st.convert()                                   # 図の位置を AI が決める必要がある（AI なし）
    assert st.res is None and st.run is not None
    st.set_inputs(fpage="77")
    assert st.changed_inputs() == [] and "今の結果は" not in st.ready_text() and not st.answer_box_open


def test_subject_other_ignored_unless_other_type(tmp_path):
    st = filled(tmp_path)
    st.convert()
    st.set_inputs(subject_other="何か", subject_other_en="x")
    assert st.changed_inputs() == []
    st = filled(tmp_path / "o")
    st.set_inputs(manuscript_type=app.OTHER_TYPE, subject_other="資料", subject_other_en="Material")
    st.convert()
    st.set_inputs(subject_other="報告")
    assert st.changed_inputs() == ["原稿種別（日本語）"]


def test_stale_texts_use_real_labels(tmp_path):
    a, _b = make_pair(tmp_path)
    st = filled(tmp_path, docx=a)
    st.convert()
    st.set_inputs(fpage="3", ai_mode="manual")
    demo = app.build_app(st, app.IO())
    labels = {getattr(b, "label", None) for b in demo.blocks.values()} | {getattr(b, "value", None) for b in demo.blocks.values()}
    texts = [st.stale_text(["docx"]), st.stale_text(["最初のページ"]), st.settings_note()]
    st.set_inputs(docx=str(tmp_path / "none.docx"))
    with pytest.raises(InputError) as ei:
        st.convert()
    texts.append(str(ei.value))
    import re
    for t in texts:
        check_text(t)
        for q in re.findall(r"「([^」]+)」", t):
            assert q in labels, q
    assert "のファイルを読めませんでした" in texts[-1]


def test_manual_fields_stay_open_for_missing_abstract(tmp_path):
    """手動モードで回答を反映した後も、英文要旨が見つからない（abstract_missing）枠が出ているあいだは、AI の set_role の abstract を
    貼り直せるように、手動の欄を見せたままにする。"""
    import json
    from test_structure import _no_abstract_style_docx
    from jasme_jats.report import actions
    st = AppState(tmp_path / "work")
    st.set_inputs(route="docx", docx=str(_no_abstract_style_docx(tmp_path)), volume="31", issue="1", fpage="1", lpage="12",
                  peer_review="査読あり", manuscript_type=type_choices()[0], ai_mode="manual")
    demo = app.build_app(st, app.IO())
    fns = {f.fn.__name__: f.fn for f in demo.fns.values()}
    fns["on_convert"](*[st.inputs[n] for n in app.INPUT_NAMES])
    assert st.waiting_for_answer
    out = fns["on_apply"](json.dumps({"placements": [], "operations": [], "notes": []}))
    assert "abstract_missing" in [a.key for a in actions(st.res)] and not st.waiting_for_answer
    assert "abstract_missing" in AppState.REPASTE_KEYS and st.answer_box_open
    assert out[2]["visible"] is True and out[3] == st.prompt_text() and out[3]
    # 回答を反映した後の枠は、貼り直しの案内（目印 repaste）で書く
    from jasme_jats.report import step
    box = next(a for a in actions(st.res) if a.key == "abstract_missing").box_detail
    assert step("repaste") in box and "出し直してもらい" in box



def test_structure_conflict_shows_box(tmp_path):
    """原稿の構造の衝突（K1・K2）で変換が中止されたとき: InputError で、文（args[0]）と赤い枠（html）に画面の操作が 1 画面版の語
    （「docx（論文の Word ファイル）」の欄）で出る（目印が残らない）。結果は残らず、入力の写しは残る（入力を直して変換し直せる）。
    手動の欄は閉じたまま。AIRequiredError と同じ扱い。"""
    from test_structure import conflict_doc
    st = filled(tmp_path, docx=conflict_doc(tmp_path, "K1_ref_ref"))
    with pytest.raises(InputError) as ei:
        st.convert()
    msg = ei.value.args[0]
    for t in (msg, ei.value.html):
        assert "「docx（論文の Word ファイル）」の欄から" in t and "\x00" not in t and "step:" not in t
    assert "変換を中止しました" in msg and "原稿の構造を直す必要があります（変換を中止しました）" in ei.value.html
    assert st.res is None and st.run is not None
    assert st.changed_inputs() == [] and st.settings_note() == "" and not st.answer_box_open
    # 直した docx に差し替えて変換し直すと、続けられる
    st.set_inputs(docx=str(FULL))
    st.convert()
    assert st.res is not None and st.res.fidelity.ok


def test_structure_conflict_view_keeps_pending_screen(tmp_path):
    """画面の更新（on_convert の戻り）も、中止の経路で例外にならず、枠に文を出す。"""
    from test_structure import conflict_doc
    st = filled(tmp_path, docx=conflict_doc(tmp_path, "K2_loose_trailing_aff"))
    demo = app.build_app(st, app.IO())
    fns = {f.fn.__name__: f.fn for f in demo.fns.values()}
    out = fns["on_convert"](*[st.inputs[n] for n in app.INPUT_NAMES])
    assert any(isinstance(x, str) and "最後の所属の段落" in x for x in out)
    assert st.res is None
