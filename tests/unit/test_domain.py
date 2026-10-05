"""The domain profiles."""

from __future__ import annotations

from pathlib import Path

import pytest

from toolkit.brain.domain import (
    Domain,
    PhoneRules,
    describe,
    domain,
    list_presets,
    load_preset,
    reset,
)


@pytest.fixture(autouse=True)
def clean_domain_cache():
    """Clear the domain cache before and after every test."""
    reset()
    yield
    reset()


# ── the Domain object itself ──────────────────────────────────────────

def test_matches_is_case_insensitive():
    d = Domain(
        name="test",
        vocabulary={"group": ["region", "branch"]},
    )
    assert d.matches("group", "Region")
    assert d.matches("group", "BRANCH")
    assert d.matches("group", "Sales Region")
    assert not d.matches("group", "Amount")


def test_matches_returns_false_for_unknown_kind():
    d = Domain(name="test", vocabulary={"group": ["x"]})
    assert not d.matches("nonsense", "x")


def test_kind_of_priority_order():
    """identifier wins over group when both match."""
    d = Domain(
        name="test",
        vocabulary={
            "identifier": ["id"],
            "group": ["id", "category"],
        },
    )
    assert d.kind_of("order_id") == "identifier"
    assert d.kind_of("category") == "group"
    assert d.kind_of("something_else") is None


# ── loading ───────────────────────────────────────────────────────────

def test_presets_exist():
    """All four presets must ship."""
    names = list_presets()
    assert "generic" in names
    assert "business" in names
    assert "research" in names
    assert "financial" in names


def test_load_preset_business():
    d = load_preset("business")
    assert d.name == "business"
    assert d.matches("group", "Branch")
    assert d.matches("group", "Channel")
    assert d.matches("measure", "Revenue")
    assert d.phone.default_country == "+254"
    assert d.currency.code == "KES"


def test_load_preset_research():
    d = load_preset("research")
    assert d.matches("group", "Treatment")
    assert d.matches("group", "Cohort")
    assert d.matches("measure", "Concentration")
    assert d.matches("date", "Collected")


def test_load_preset_financial():
    d = load_preset("financial")
    assert d.matches("group", "Sector")
    assert d.matches("group", "Asset Class")
    assert d.matches("measure", "Yield")
    assert d.matches("identifier", "Ticker")


def test_load_unknown_preset_raises():
    with pytest.raises(ValueError, match="No preset"):
        load_preset("nonsense")


# ── the active domain ─────────────────────────────────────────────────

def test_domain_returns_something():
    d = domain()
    assert isinstance(d, Domain)
    assert d.name


def test_domain_falls_back_when_no_presets(monkeypatch, tmp_path):
    """If the presets directory is missing, we get the fallback."""
    from toolkit.brain import domain as domain_mod

    monkeypatch.setattr(
        domain_mod, "_PRESETS_DIR", tmp_path / "nonexistent"
    )
    monkeypatch.setattr(
        domain_mod, "_PROJECT_ROOT", tmp_path
    )
    reset()
    d = domain()
    assert d.name == "fallback"
    assert d.matches("group", "category")


# ── describe ──────────────────────────────────────────────────────────

def test_describe_shows_the_vocabulary():
    d = load_preset("business")
    text = describe(d)
    assert "business" in text
    assert "group" in text
    assert "branch" in text.lower()