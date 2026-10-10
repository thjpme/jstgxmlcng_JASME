from pathlib import Path

import pytest

from jasme_jats.config import ArticleMeta, JournalConfig

FIXTURES = Path(__file__).resolve().parent / "fixtures"
DATA = Path(__file__).resolve().parent / "data"
FULL = FIXTURES / "sample_full.docx"
EDGE = FIXTURES / "sample_edge.docx"
TEMPLATE = FIXTURES / "JASME_template_20261009.docx"
ALL_DOCS = [FULL, EDGE, TEMPLATE]


@pytest.fixture(scope="session")
def journal():
    return JournalConfig.load()


@pytest.fixture
def meta():
    return ArticleMeta.from_dict({"volume": "31", "issue": "1", "fpage": "1", "lpage": "12",
                                  "pub_date": "2026-03-31", "received": "2025-06-01", "accepted": "2025-11-20"})
