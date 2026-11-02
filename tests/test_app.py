"""Gradio の操作画面（app.py。試作）: AppState の遷移と、build_app が画面を組めること。ブラウザは使わない。"""
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


def test_missing_images_are_filled_in_filename_order(tmp_path, monkeypatch):
    import dataclasses
    import io
    from PIL import Image
    real = app.convert
    # EMF を変換しない設定にして、テンプレートの図 1 の画像を用意できない状態にする（LibreOffice の有無に左右されない）
    monkeypatch.setattr(app, "convert", lambda d, m, j, o: real(d, m, j, dataclasses.replace(o, convert_metafiles=False)))
    st = filled(tmp_path, docx=TEMPLATE)
    st.convert()
    rows = st.missing_images()
    assert rows and "必要です" in st.images_markdown() and rows[0][0] in st.images_markdown()
    assert st.needs_action
    buf = io.BytesIO()
    Image.new("RGB", (60, 40), "white").save(buf, "PNG")
    pics = []
    for name in ("b.png", "a.png"):
        p = tmp_path / name
        p.write_bytes(buf.getvalue())
        pics.append(p)
    added = st.add_images(pics)                    # 足りない図が 1 つなら、名前の順で先頭の a.png だけを使う
    assert added == [rows[0][0]] and len(st.missing_images()) == len(rows) - 1
    assert list(st.user_images.values())[0][0] == "a.png"
    with pytest.raises(InputError, match="選ばれていません"):
        st.add_images([])
    st.convert()                                   # 変換し直すと、前の画像は持ち越さない
    assert len(st.missing_images()) == len(rows)


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

