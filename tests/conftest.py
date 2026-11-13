from pathlib import Path

import pytest

from jasme_jats.config import ArticleMeta, JournalConfig

FIXTURES = Path(__file__).resolve().parent / "fixtures"
DATA = Path(__file__).resolve().parent / "data"
META_EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "meta_example.toml"   # コマンドラインの --meta の例
FULL = FIXTURES / "sample_full.docx"
EDGE = FIXTURES / "sample_edge.docx"
TEMPLATE = FIXTURES / "JASME_template_20261009.docx"
FLOAT = FIXTURES / "sample_float.docx"   # 位置を決めるのに AI 補完が必要（ALL_DOCS には入れない）
NOTES = FIXTURES / "sample_notes.docx"
PDFCHECK = FIXTURES / "sample_pdfcheck.docx"
PDFCHECK_PDF = FIXTURES / "sample_pdfcheck.pdf"   # 出版社が組版で直した想定の PDF（make_fixtures.py が LibreOffice で作る）
READER = FIXTURES / "sample_reader.docx"   # 読み取りの境界ケース（sample_edge に入れていないもの）
FLOAT_TEXT = FIXTURES / "sample_float_text.docx"   # 図形の中で画像と文字が同じ段落にある（ALL_DOCS には入れない）
STRUCTURE = FIXTURES / "sample_structure.docx"   # 論文の構造（領域の分け方など）の境界ケース
CELLS = FIXTURES / "sample_b3_cells.docx"   # 表のセルに画像とキャプションが並ぶ図形（AI なしで図に組める）
TABLEFIG = FIXTURES / "sample_b3_tablefig.docx"   # 画像のない図キャプションと、隣のキャプションのない表
PLACE = FIXTURES / "sample_b3_place.docx"   # 位置を決められない図表の仮の置き場所（AI 補完が必要。ALL_DOCS には入れない）
OUTSIDE = FIXTURES / "sample_outside.docx"   # 本文の外の段落に結び付いた図形（AI 補完が必要。ALL_DOCS には入れない）
LINKS = FIXTURES / "sample_links.docx"   # 注・図表へのリンクの規則（注番号が「1)」の書き方の論文。修正計画の D2・M5）
LINKS_BARE = FIXTURES / "sample_links_bare.docx"   # 同じ規則の、注番号が番号だけの上付きの論文
ALL_DOCS = [FULL, EDGE, TEMPLATE, NOTES, PDFCHECK, READER, STRUCTURE, CELLS, TABLEFIG, LINKS, LINKS_BARE]


@pytest.fixture(scope="session")
def journal():
    return JournalConfig.load()


@pytest.fixture
def meta():
    return ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12",
                                  "pub_date": "2026-03-31", "received": "2025-06-01", "accepted": "2025-11-20",
                                  "peer_review": "あり", "keywords": "proof; 論証; 数学的探究"})


def one_color_png(color=(200, 200, 200), size=(8, 6)) -> bytes:
    """1 色の PNG（図の画像の代わり。ツールは画像の中身を見ない）。"""
    import io

    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def key_png(k: int) -> bytes:
    """k 番目の置き場所の 1 色の PNG（k ごとに色が違う）。"""
    return one_color_png((200, (37 * k) % 256, k % 256))


def fill_images(res) -> list:
    """残っている画像の置き場所（状態 missing）すべてに 1 色の PNG を入れる（pipeline.add_images）。画像を入れる手順 images を
    済ませて、ほかの知らせ（要対応・要確認）を今までどおり確かめるときに使う。置き場所ごとに色を変える（同じ中身の画像を
    2 つの図に入れると要確認 image_same が出るため）。戻り値: 入れた幹の一覧。"""
    from jasme_jats.pipeline import add_images
    keys = [i.key for i in res.images if i.status == "missing"]
    need = {key: ("fill.png", key_png(k)) for k, key in enumerate(keys)}
    return add_images(res, need) if need else []


def image_folder(path, keys) -> Path:
    """幹ごとに 1 色の PNG（fig01.png など）を置いたフォルダ（コマンドラインの --images に渡す）。"""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    for k, key in enumerate(keys):
        (path / f"{key}.png").write_bytes(key_png(k))
    return path


def others(res) -> list:
    """図の画像を入れる手順（images）を除いた知らせ（report.actions）。手順のほかの知らせを今までどおり比べるときに使う。"""
    from jasme_jats.report import actions
    return [a for a in actions(res) if a.key != "images"]
