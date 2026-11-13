"""取り違えの確かめの一覧（imagelist。図の確かめ.html。修正計画 W1 の手順 12・4.3）。

出力フォルダ（記事フォルダの外）に別の HTML として書き、行は report.image_rows と同じ。docx 由来の文字は HTML のエスケープをする。
画像は embed なしで Graphics/ への相対リンク、embed ありで縮小した画像を埋め込む。fixture は make_where・make_figs・make_float_figs（内容は架空）。
"""
import re
import zipfile

import pytest

import make_fixtures as mf
from conftest import fill_images
from jasme_jats.imagelist import check_html, check_name
from jasme_jats.package import article_dir
from jasme_jats.pipeline import Options, add_images, convert
from jasme_jats.report import image_rows


@pytest.fixture
def where(tmp_path, journal, meta):
    path = tmp_path / "where.docx"
    mf.make_where(path)
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    assert res.fidelity.ok and res.fidelity.final_ok and res.dtd_valid
    return res


def body_rows(html_text):
    """最初の表（図の画像の一覧）のデータ行のセル（タグを除いた文字）の一覧。"""
    table = html_text.split("<table>")[1].split("</table>")[0]
    rows = re.findall(r"<tr>(.*?)</tr>", table, re.S)[1:]
    return [re.findall(r"<td[^>]*>(.*?)</td>", r, re.S) for r in rows]


def test_rows_are_the_same_as_image_rows(where):
    """行の数と並びは report.image_rows と同じ（名前の列で比べる）。画像の場所の列は slot_where、備考の列は ImageRow.note。"""
    rows = image_rows(where)
    got = body_rows(check_html(where))
    assert [c[0] for c in got] == [r.key for r in rows] and len(rows) == 7
    assert [c[2] for c in got] == [r.where.replace("&", "&amp;") for r in rows]
    # 画像だけの段落のキャプションなしの置き場所の「場所」は、前の文字のある段落（章の最初なら章）
    assert got[0][2] == "章「１．場所の確かめ」の最初"
    assert got[1][2].startswith("「試験（2024）にならい，画像の場所を確…」の段落の後ろ")


def test_heading_and_file_outside_the_article_folder(where, journal, meta):
    """見出しは入れた画像の数。ファイルは出力フォルダ（記事フォルダの外）にあり、アップロード用の ZIP に入らない。"""
    assert "<h1>図の確かめ（" in check_html(where) and "入れた画像 0/7 枚</h1>" in check_html(where)
    path = where.check_path
    assert path.name == check_name(where) == f"{meta.article_id(journal)}_図の確かめ.html"
    assert path.parent == where.zip_path.parent and article_dir(path.parent, journal, meta) not in path.parents
    assert path.read_text(encoding="utf-8") == check_html(where)
    with zipfile.ZipFile(where.zip_path) as z:
        assert not [n for n in z.namelist() if n.endswith(".html")]
    assert path.name not in where.not_zipped


def test_caption_and_note_are_escaped(where):
    """キャプション・場所・備考の docx の文字は HTML のエスケープをする。数式などの位置の文字は表示だけ言葉にする。"""
    cap = next(i for i in where.images if i.kind == "fig")
    cap.caption = "図1　<b>x</b> & \"y\" ￼"
    cap.note = "備考 <script>alert(1)</script>"
    html_text = check_html(where)
    assert "<b>x</b>" not in html_text and "<script>alert" not in html_text
    assert "&lt;b&gt;x&lt;/b&gt; &amp; &quot;y&quot; ［数式など］" in html_text
    assert "備考 &lt;script&gt;alert(1)&lt;/script&gt;" in html_text


def test_embed_and_links_and_rebuild_on_add(where, journal, meta):
    """画像を入れると一覧が作り直される。embed なしは Graphics/ への相対リンク、embed ありは縮小した画像の埋め込み。"""
    before = where.check_path.read_text(encoding="utf-8")
    keys = fill_images(where)
    assert keys and where.check_path.read_text(encoding="utf-8") != before
    plain = where.check_path.read_text(encoding="utf-8")
    adir = article_dir(__import__("pathlib").Path(""), journal, meta).as_posix()
    for i in where.images:
        if i.status == "user":
            assert f'src="{adir}/Graphics/{i.name}"' in plain
            assert (where.zip_path.parent / adir / "Graphics" / i.name).is_file()
    assert "data:image" not in plain and f"入れた画像 {len(keys)}/{len(keys)} 枚" in plain
    emb = check_html(where, embed=True)
    assert 'src="data:image/png;base64,' in emb and "/Graphics/" not in emb


def test_two_images_figure_note(journal, meta, tmp_path):
    """docx で画像 2 枚の図には、備考に「1 枚にまとめた画像を入れてください」。置き場所の note も備考に必ず出る。"""
    path = tmp_path / "run_frame.docx"
    mf.make_figs(path, "run_frame")
    res = convert(path, meta, journal, Options(out_dir=tmp_path / "out"))
    html_text = check_html(res)
    assert "docx ではこの図に画像 2 枚（1 枚にまとめた画像を入れてください）" in html_text
    assert body_rows(html_text)[0][6].startswith("未。")


def test_drawn_figures_and_decorations_are_separated(journal, meta, tmp_path):
    """末尾: 図キャプションのある図形の中の文字の図形だけのグループは「図形で描いた図」、キャプションのない同じ形は「飾り」。
    図形で描いた図の備考に「Word の図形で描いた図です」が出る。"""
    outs = {}
    for variant in ("drawn", "drawn_free"):
        path = tmp_path / f"{variant}.docx"
        mf.make_float_figs(path, variant)
        outs[variant] = convert(path, meta, journal, Options(out_dir=tmp_path / variant, ai_mode="manual"))
    drawn = check_html(outs["drawn"])
    assert "<h2>図形で描いた図（図の本体）</h2>" in drawn and "<h2>画像の場所に数えなかった図形（飾り）</h2>" not in drawn
    assert "Word の図形（文字の図形の集まり）で描いた図です" in drawn
    free = check_html(outs["drawn_free"])
    assert "<h2>画像の場所に数えなかった図形（飾り）</h2>" in free and "<h2>図形で描いた図" not in free
    assert "画像の要る図・表はありません" in free


def test_heading_follows_added_images(where):
    """画像を入れるたびに、一覧は新しい状態になる（入れた画像の数が見出しに出る）。"""
    keys = [i.key for i in where.images][:2]
    add_images(where, {k: ("a%d.png" % n, __import__("conftest").key_png(n)) for n, k in enumerate(keys)})
    assert "入れた画像 2/7 枚" in where.check_path.read_text(encoding="utf-8")


def test_report_points_to_the_html(where, journal, meta):
    """レポートの 9 章の冒頭と 14 章、要確認 image_same の文は、図の確かめ.html を案内する。"""
    from jasme_jats.images import SlotImage  # noqa: F401
    from jasme_jats.report import actions
    name = check_name(where)
    text = where.report_path.read_text(encoding="utf-8")
    assert name in text.split("## 9.")[1].split("## 10.")[0] and name in text.split("## 14.")[1]
    same = ("a1.png", __import__("conftest").key_png(1))
    add_images(where, {i.key: same for i in where.images[:2]})
    [a] = [a for a in actions(where) if a.key == "image_same"]
    assert f"「{name}」で確かめてください" in a.box_detail
