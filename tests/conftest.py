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
ALL_DOCS = [FULL, EDGE, TEMPLATE, NOTES, PDFCHECK, READER, STRUCTURE, CELLS, TABLEFIG]


@pytest.fixture(scope="session")
def journal():
    return JournalConfig.load()


@pytest.fixture
def meta():
    return ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12",
                                  "pub_date": "2026-03-31", "received": "2025-06-01", "accepted": "2025-11-20",
                                  "peer_review": "あり", "keywords": "proof; 論証; 数学的探究"})
