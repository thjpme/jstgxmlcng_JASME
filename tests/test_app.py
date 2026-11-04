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
    assert "想定外のエラーで止まりました" in out[0] and out[8] == ""
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
    assert "入れた画像と変換の結果は、この画面に残っています" in html and "押すと、入れた画像が消えます" in html
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
    out = fns["on_download"](False)
    assert out[8] == "" and "想定外のエラーで止まりました" in out[0]
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
    assert not st.needs_action and out[2]["visible"] is False and out[3] == ""
    # 手動でなければ欄は出ない
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
    """回答の反映が、前の結果を捨てる前に想定外の例外で止まったとき（入力ファイルを作業用の場所に写せないなど）は、手動の欄も結果も
    画面に残っている。案内も「欄は隠れている」ではなく、残っていることを言う。"""
    st = filled(tmp_path)
    st.set_inputs(ai_mode="manual")
    demo = app.build_app(st, app.IO())
    fns = {f.fn.__name__: f.fn for f in demo.fns.values()}
    assert fns["on_convert"](*[st.inputs[n] for n in app.INPUT_NAMES])[2]["visible"] is True

    def boom(*args, **kwargs):
        raise OSError("写せません")
    monkeypatch.setattr(app.shutil, "copyfile", boom)
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
    choices = {"手動（チャットに貼り付け）", "API（Claude）", "docx から作り、出版版 PDF で補う", "次の図の画像が必要です"}
    assert quoted - choices <= labels, quoted - choices - labels
    assert "AI の回答" not in quoted
    # CRASH_ADVICE は語の表から組み立てている: 実際のラベルが入り、略した名前・直接書いた名前はない
    texts = list(app.AppState.CRASH_ADVICE.values()) + [app.AppState.CRASH_ADVICE_APPLY_KEPT, app.AppState.CRASH_ADVICE_FOLDER_GONE]
    for t in texts:
        assert "\x00" not in t and "「AI の回答」" not in t and "手順" not in t
    assert f"「{colab.ANSWER_LABEL}」の欄" in app.AppState.CRASH_ADVICE["apply"]
    assert f"「{colab.CONVERT_LABEL}」をもう一度押" in app.AppState.CRASH_ADVICE["convert"]
    assert words["docx"] in app.AppState.CRASH_ADVICE["convert"] and words["meta"] in app.AppState.CRASH_ADVICE["convert"]
