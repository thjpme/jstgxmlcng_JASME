"""Gradio の操作画面（app.py。1 画面版）: AppState の遷移と、build_app が画面を組めること。ブラウザは使わない。"""
import zipfile

import pytest

from conftest import FULL, TEMPLATE
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
    path, note = st.download()
    assert not st.needs_action and note == ""
    assert path.endswith("変換結果_" + res.xml_path.stem + ".zip")
    assert any(n.endswith(".xml") for n in zipfile.ZipFile(path).namelist())


def test_manual_mode_waits_for_answer(tmp_path):
    st = filled(tmp_path)
    st.set_inputs(ai_mode="manual")
    st.convert()
    assert st.waiting_for_answer and st.needs_action
    assert "AI の回答をまだ反映していません" not in st.result_html()    # 依頼文の欄があるので枠は出さない
    assert st.prompt_text()
    # 要対応が残っていると、そのままではダウンロードできない
    path, note = st.download()
    assert path is None and "AI の回答をまだ反映していません" in note
    path, note = st.download(accept_todo=True)
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


def test_missing_images_are_filled_per_figure(tmp_path, monkeypatch):
    import dataclasses
    import io
    from PIL import Image
    real = app.convert
    # EMF を変換しない設定にして、テンプレートの図の画像を用意できない状態にする（LibreOffice の有無に左右されない）
    monkeypatch.setattr(app, "convert", lambda d, m, j, o: real(d, m, j, dataclasses.replace(o, convert_metafiles=False)))
    st = filled(tmp_path, docx=TEMPLATE)
    st.convert()
    rows = st.missing_images()
    assert rows and "必要です" in st.images_markdown() and rows[0][0] in st.images_markdown()
    assert st.image_slots() == rows and st.needs_action
    assert st.slot_label("a.png", "図1 x") == "図1 x（a.png）" and st.slot_label("a.png", "") == "a.png"
    buf = io.BytesIO()
    Image.new("RGB", (60, 40), "white").save(buf, "PNG")
    pic = tmp_path / "z_any_name.png"                  # ファイル名は何でもよい。割り当ては名前の順ではなく、図ごとの指定
    pic.write_bytes(buf.getvalue())
    last = rows[0][0]                                  # テンプレートの足りない図は 1 つ（欄が複数のときも、選んだ欄だけを入れる）
    added = st.add_images({last: str(pic), "31_1_99.png": None})       # 選んでいない欄（None）は飛ばす
    assert added == [last] and last not in [r[0] for r in st.missing_images()]
    assert len(st.missing_images()) == len(rows) - 1 and st.user_images[last][0] == "z_any_name.png"
    with pytest.raises(InputError, match="選ばれていません"):
        st.add_images({})
    with pytest.raises(InputError, match="選ばれていません"):
        st.add_images({last: None})
    with pytest.raises(InputError, match="用意が必要な画像ではありません"):
        st.add_images({last: str(pic)})                # 入れた図はもう必要ない
    st.convert()                                       # 変換し直すと、前の画像は持ち越さない
    assert len(st.missing_images()) == len(rows)


def test_image_slots_in_view(tmp_path):
    """build_app の画面更新: 足りない図の数だけ欄を見せ、ラベルは「キャプション（出力ファイル名）」。上限を超えた分は見せない。"""
    import types
    import gradio as gr
    st = AppState(tmp_path / "work")
    st.res = types.SimpleNamespace(needs_action=True)      # 模擬の結果（AI は使わない設定なので回答待ちにならない）
    st.set_inputs(ai_mode="none")
    st.result_html = lambda: ""
    rows = [(f"31_1_{k:02d}.png", f"図{k} 架空の図" if k % 2 else "", "why") for k in range(1, app.MAX_IMAGE_SLOTS + 4)]
    assert len(rows) > app.MAX_IMAGE_SLOTS
    st.missing_images = lambda: rows
    assert len(st.image_slots()) == app.MAX_IMAGE_SLOTS
    assert f"{app.MAX_IMAGE_SLOTS} 件までです" in st.images_markdown()
    assert st.slot_label(*rows[0][:2]) == "図1 架空の図（31_1_01.png）" and st.slot_label(*rows[1][:2]) == "31_1_02.png"
    demo = app.build_app(st, app.IO())
    assert isinstance(demo, gr.Blocks)
    fns = {f.fn.__name__: f.fn for f in demo.fns.values()}
    out = fns["on_images"](*[None] * app.MAX_IMAGE_SLOTS)                 # 何も選ばないとエラー（画面の更新の数は変わらない）
    assert len(out) == 9 + app.MAX_IMAGE_SLOTS and "選ばれていません" in out[0]
    slots = out[9:]
    assert slots[0]["visible"] and slots[0]["label"] == "図1 架空の図（31_1_01.png）" and slots[0]["value"] is None
    assert slots[1]["label"] == "31_1_02.png" and all(u["visible"] for u in slots)
    st.missing_images = lambda: rows[:2]
    slots = fns["on_images"](*[None] * app.MAX_IMAGE_SLOTS)[9:]
    assert [u["visible"] for u in slots] == [True, True] + [False] * (app.MAX_IMAGE_SLOTS - 2)


def test_io_reads_secrets_and_waits_for_libreoffice(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    io = app.IO()
    assert io.read_secret(("ANTHROPIC_API_KEY",)) is None
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key")
    assert io.read_secret(("ANTHROPIC_API_KEY",)) == "key"
    import __main__

    class Proc:
        waited = False

        def poll(self):
            return None

        def wait(self):
            Proc.waited = True
    monkeypatch.setattr(__main__, "LO_PROC", Proc(), raising=False)
    app.ColabIO().libreoffice_ready()
    assert Proc.waited


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



def test_images_box_uses_app_words(tmp_path, monkeypatch):
    """足りない画像の知らせは、1 画面版では手順の番号ではなく欄の名前で書く（O2）。ノートブックの枠（既定）は手順 7 のまま。"""
    import dataclasses
    from jasme_jats.colab import missing_images_box, result_boxes
    real = app.convert
    monkeypatch.setattr(app, "convert", lambda d, m, j, o: real(d, m, j, dataclasses.replace(o, convert_metafiles=False)))
    st = filled(tmp_path, docx=TEMPLATE)
    st.convert()
    html = st.result_html()
    assert "「次の図の画像が必要です」の下に並ぶ、図ごとの欄（欄の名前は図のキャプションと出力ファイル名）で、図ごとにその図の画像を" in html
    assert "\x00" not in html and "足りない図の画像" not in html
    assert "手順" not in result_boxes(st.res, screen="app")       # レポート全文（畳んだ部分）には「ノートブックは手順 N」と両方の言い方がある
    assert "手順 7「足りない画像をアップロード」で" in missing_images_box(st.res)
    assert "次の図の画像が必要です" in st.images_markdown()          # 語の指す見出しが、実際の画面の欄の並びの見出しにある


def test_unexpected_error_is_shown_and_old_result_dropped(tmp_path, monkeypatch):
    """変換が想定外の例外で止まったとき、前の結果を捨てる（消えた出力フォルダを指さない）。画面には例外の種類と文を赤い枠で出す（O1）。"""
    import types
    st = filled(tmp_path)
    st.convert()
    zip_before, _ = st.download()
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
    assert "もう一度「変換する」を押してください" in out[0] and "入力（docx・PDF・書誌情報の欄）が正しいかを確かめ" in out[0]
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
    assert "想定外のエラーで止まりました" in out[0] and out[8] == ""
    assert "もう一度ダウンロードの操作をしてかまいません" in out[0] and "もう一度「変換する」" not in out[0]     # 結果は残っている


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
    assert "貼り付けた回答は、「変換する」を押し直すと使えなくなる" in out[0] and "もう一度「変換する」を押してください" not in out[0]
    # レポートが残っているときも、サーバー側のパスは書かない（利用者は取り出せない）。この画面の変換レポートの全文を案内する
    st.res = types.SimpleNamespace(report_path=report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("x", encoding="utf-8")
    html = st.crash(RuntimeError("y"), "images").html
    assert str(report) not in html and "変換レポートの全文を見る" in html
    assert "入れた画像と変換の結果は、この画面に残っています" in html and "押すと、入れた画像が消えます" in html
    assert "もう一度「変換する」を押してください" not in html
    with pytest.raises(ValueError):
        st.crash(RuntimeError("y"), "other")
