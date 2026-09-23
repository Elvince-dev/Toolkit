
"""Shared fixtures for all tests.

Every test that touches the disk uses tmp_path from pytest — the
fixtures here just make that ergonomic.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def csv_dir(tmp_path: Path) -> Path:
    """A throwaway folder to hold CSV 'tabs' for the tests."""
    p = tmp_path / "csv"
    p.mkdir()
    return p


@pytest.fixture
def sales_tab(csv_dir: Path) -> Path:
    """A small, well-behaved sales sheet."""
    (csv_dir / "Sales.csv").write_text(
        "Region,Amount,Date,Rep\n"
        "Thika,4200,2026-01-15,Ann\n"
        "Ruaka,3100,2026-01-16,Bob\n"
        "Thika,5100,2026-01-17,Ann\n"
        "Nairobi,2800,2026-01-18,Carol\n"
        "Ruaka,9100,2026-01-19,Bob\n"
        "Thika,4700,2026-01-20,Ann\n"
        "Nairobi,3300,2026-01-21,Carol\n"
        "Ruaka,2500,2026-01-22,Bob\n",
        encoding="utf-8",
    )
    return csv_dir
