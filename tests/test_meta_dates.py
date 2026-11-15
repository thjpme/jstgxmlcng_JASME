"""発行日・受付日・受理日は入力で必須（所有者の決定）。どれかが空のまま変換したら、要対応 meta_dates で知らせる（変換は止めない）。
3 つの画面（コマンドライン・ノートブック・1 画面版）と、PDF から受付日・受理日が入る場合を確かめる。内容はすべて架空。"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from conftest import FULL, PDFCHECK
from jasme_jats import app
from jasme_jats.app import AppState, type_choices
from jasme_jats.cli import main
from jasme_jats.config import ArticleMeta
from jasme_jats.pipeline import Options, convert
from jasme_jats.report import NEEDS_ACTION, actions, blocking, missing_dates

from test_app import pdf_biblio_pages
from test_meta_pdf import pages_with

BASE = {"volume": "31", "issue": "1", "fpage": "1", "lpage": "12", "peer_review": "あり"}
DATES = {"pub_date": "2026-03-31", "received": "2025-06-01", "accepted": "2025-11-20"}
NAMES = {"pub_date": "発行日", "received": "受付日", "accepted": "受理日"}


def dates_act(res):
    return {a.key: a for a in actions(res)}.get("meta_dates")


def run(tmp_path, journal, **dates):
    meta = ArticleMeta.from_dict({**BASE, **dates})
    return convert(FULL, meta, journal, Options(out_dir=tmp_path / "out"))


@pytest.mark.parametrize("empty", ["pub_date", "received", "accepted"])
def test_each_empty_date_is_needs_action(tmp_path, journal, empty):
    res = run(tmp_path, journal, **{k: v for k, v in DATES.items() if k != empty})
    a = dates_act(res)
    assert a is not None and a.level == NEEDS_ACTION and a in blocking(actions(res)) and res.needs_action
    assert NAMES[empty] + "が空です" in a.top
    assert all(NAMES[k] not in a.box_title for k in DATES if k != empty)           # 空でない日付は挙げない
    assert "11 章" in a.top and "11 章" in a.checklist and a.cli.startswith("要対応") and "--meta" in a.cli
    assert res.xml_path.exists() and res.report_path.exists()                      # 変換は止めない


def test_all_three_empty_names_all(tmp_path, journal):
    res = run(tmp_path, journal)
    a = dates_act(res)
    assert "発行日・受付日・受理日が空です" in a.top
    assert missing_dates(res.meta) == ["発行日", "受付日", "受理日"]


def test_all_filled_gives_no_notice(tmp_path, journal):
    res = run(tmp_path, journal, **DATES)
    assert dates_act(res) is None


def test_optional_dates_are_not_required(tmp_path, journal):
    # 再受付日・J-STAGE 公開日・最終査読日は必須にしない。J-STAGE 公開日だけでは発行日の代わりにならない
    res = run(tmp_path, journal, received="2025-06-01", accepted="2025-11-20", epub_date="2026-04-24")
    assert "発行日が空です" in dates_act(res).top
    res = run(tmp_path, journal, **DATES)
    assert missing_dates(res.meta) == [] and dates_act(res) is None


def test_bad_date_form_still_stops_on_input_check():
    # 日付の形が不正（一部だけの日付）なら、今までどおり日付の検査で止まる（meta_dates の「空」には入らない）
    with pytest.raises(ValueError, match="発行日"):
        ArticleMeta.from_dict({**BASE, **DATES, "pub_date": "2026-03"})


def test_empty_dates_keep_existing_xml(tmp_path, journal):
    res = run(tmp_path, journal)
    xml = res.xml_path.read_text(encoding="utf-8")
    assert '<pub-date pub-type="ppub">' in xml and '<date date-type="received">' not in xml


# ---- コマンドライン
def write_meta(path, **dates):
    lines = ['[article]', 'volume = "31"', 'issue = "1"', 'fpage = "1"', 'lpage = "12"', 'peer_review = "あり"']
    lines += [f'{k} = "{v}"' for k, v in dates.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_cli_exit_code_follows_dates(tmp_path, capsys):
    out = tmp_path / "out"
    main([str(FULL), "--meta", str(write_meta(tmp_path / "a.toml", **DATES)), "--out", str(out / "a")])
    assert "が空です（レポートの 11 章）" not in capsys.readouterr().err
    for empty in DATES:
        d = {k: v for k, v in DATES.items() if k != empty}
        code = main([str(FULL), "--meta", str(write_meta(tmp_path / f"{empty}.toml", **d)), "--out", str(out / empty)])
        err = capsys.readouterr().err
        assert code == 1 and f"要対応: {NAMES[empty]}が空です（レポートの 11 章）" in err


def test_cli_dates_from_pdf(tmp_path, capsys, monkeypatch):
    from jasme_jats import pdfmatch
    monkeypatch.setattr(pdfmatch, "extract_pages", lambda path: pages_with())
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4\n")
    main([str(PDFCHECK), "--meta", str(write_meta(tmp_path / "m.toml", pub_date="2026-03-31")), "--pdf", str(tmp_path / "a.pdf"),
          "--out", str(tmp_path / "out")])
    assert (tmp_path / "out").exists() and "が空です（レポートの 11 章）" not in capsys.readouterr().err            # 受付日・受理日は PDF から入る
    # PDF から日付を読めなければ空のまま残り、要対応
    monkeypatch.setattr(pdfmatch, "extract_pages", lambda path: pages_with(dates=""))
    main([str(PDFCHECK), "--meta", str(write_meta(tmp_path / "m2.toml", pub_date="2026-03-31")), "--pdf", str(tmp_path / "a.pdf"),
          "--out", str(tmp_path / "out2")])
    assert "要対応: 受付日・受理日が空です" in capsys.readouterr().err


# ---- 1 画面版
def filled(tmp_path, **extra):
    st = AppState(tmp_path / "work")
    st.set_inputs(docx=str(FULL), volume="31", issue="1", fpage="1", lpage="12", peer_review="査読あり",
                  manuscript_type=type_choices()[0], ai_mode="none", **extra)
    return st


def test_app_convert_button_stays_enabled_without_dates(tmp_path):
    st = filled(tmp_path)
    assert st.can_convert() and st.missing() == []                  # 日付が空でも「変換する」は押せる（巻・号・ページとは違う）
    assert not any(n in "".join(st.missing()) for n in NAMES.values())


@pytest.mark.parametrize("empty", ["pub_date", "received", "accepted"])
def test_app_each_empty_date_is_needs_action(tmp_path, empty):
    st = filled(tmp_path, **{k: v for k, v in DATES.items() if k != empty})
    st.convert()
    a = dates_act(st.res)
    assert a is not None and NAMES[empty] + "が空です" in a.top and st.needs_action
    html = st.result_html()
    assert "#dc2626" in html and NAMES[empty] + "が空です（要対応）" in html          # ほかの要対応と同じ赤い枠
    assert "「発行日」" not in a.box_detail and "手順" not in a.box_detail            # 画面ごとの語に置き換わる
    assert any(NAMES[empty] + "が空です" in t for t in st.todo_titles())          # ダウンロードの扱いは既存の要対応と同じ仕組み


def test_app_all_filled_and_pdf_filled(tmp_path, monkeypatch):
    from jasme_jats import pdfmatch
    st = filled(tmp_path, **DATES)
    st.convert()
    assert dates_act(st.res) is None
    monkeypatch.setattr(pdfmatch, "extract_pages", lambda path: pdf_biblio_pages())
    st = filled(tmp_path, pub_date="2026-03-31")
    st.pdf_selected(str(tmp_path / "a.pdf"))
    assert st.inputs["received"] == "2029-06-01" and st.inputs["accepted"] == "2029-11-20"
    st.convert()
    assert dates_act(st.res) is None                                # PDF から入った受付日・受理日は空ではない


def test_app_screen_has_required_date_boxes():
    import inspect
    src = inspect.getsource(app.build_app)
    assert 'gr.Textbox(label="発行日", info=' in src and "必須" in src.split('label="発行日"')[1][:120]
    assert src.index('label="受理日"') < src.index('with gr.Accordion("任意の項目"')        # 任意の項目の外（必須の欄の並び）


# ---- ノートブック
def cell_source(title_prefix):
    import make_notebook as mk
    cell = next(c for c in json.loads(mk.render())["cells"] if "".join(c["source"]).startswith(title_prefix))
    return "".join(cell["source"])


def test_notebook_step3_marks_dates_required(monkeypatch, tmp_path):
    src = cell_source("#@title 3.")
    assert "発行日・受付日・受理日は必須です" in src and "（必須）" in src and "J-STAGE 公開日（jstage_release_date）**（任意）" in src
    s = src.replace('peer_review = "（選んでください）"  #@param', 'peer_review = "査読あり"  #@param')
    ns = {"DONE": {1, 2}, "docx_path": Path("a.docx")}
    exec(s, ns)                                                     # 日付が空でも手順 3 は止まらない
    assert ns["meta_input"]["pub_date"] == "" and ns["meta_input"]["received"] == ""


def test_notebook_step3_dates_from_pdf(monkeypatch, tmp_path):
    from jasme_jats import pdfmatch
    monkeypatch.setattr(pdfmatch, "extract_pages", lambda path: pdf_biblio_pages())
    s = cell_source("#@title 3.").replace('peer_review = "（選んでください）"  #@param', 'peer_review = "査読あり"  #@param')
    ns = {"DONE": {1, 2}, "docx_path": Path("a.docx"), "pdf_path": tmp_path / "a.pdf"}
    exec(s, ns)
    assert ns["meta_input"]["received"] == "2029-06-01" and ns["meta_input"]["accepted"] == "2029-11-20"
    res = convert(FULL, ArticleMeta.from_dict({**ns["meta_input"], "pub_date": "2026-03-31"}), __import__("jasme_jats.config", fromlist=["x"]).JournalConfig.load(),
                  Options(out_dir=tmp_path / "out"))
    assert dates_act(res) is None
