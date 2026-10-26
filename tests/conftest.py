from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.ingest.xlsx import ParseResult, load_config, parse_workbook, pivot_wide

FIXTURES = Path(__file__).parent / "fixtures"
XLSX = FIXTURES / "Social_Media_fixture.xlsx"
os.environ["SOCIAL_XLSX"] = str(XLSX)  # tests never read a real workbook dropped into data/


@pytest.fixture(scope="session")
def parsed() -> ParseResult:
    return parse_workbook(XLSX, load_config())


@pytest.fixture(scope="session")
def weekly_wide(parsed):  # noqa: ANN001, ANN201
    return pivot_wide(parsed.weekly)


@pytest.fixture(scope="session")
def monthly_wide(parsed):  # noqa: ANN001, ANN201
    return pivot_wide(parsed.monthly)
