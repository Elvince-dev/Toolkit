import pytest
from toolkit.tools import web as web_tools
from toolkit.tools import registry


def test_weather_returns_text(monkeypatch):
    monkeypatch.setattr(
        web_tools.web,
        "get_weather",
        lambda city: {"ok": True, "text": f"Weather in {city}: sunny, 22°C"},
    )
    result = web_tools._weather({"city": "Nairobi"})
    assert "sunny" in result
    assert "Nairobi" in result


def test_weather_failure(monkeypatch):
    monkeypatch.setattr(
        web_tools.web,
        "get_weather",
        lambda city: {"ok": False, "why": "network down"},
    )
    result = web_tools._weather({"city": "Nairobi"})
    assert "could not" in result.lower()
    assert "network down" in result


def test_weather_missing_city():
    result = web_tools._weather({})
    assert "which city" in result.lower()


def test_exchange_returns_text(monkeypatch):
    monkeypatch.setattr(
        web_tools.web,
        "get_exchange_rate",
        lambda b, t: {"ok": True, "text": f"1 {b} = 130.0 {t}"},
    )
    result = web_tools._exchange({"base": "USD", "target": "KES"})
    assert "USD" in result
    assert "KES" in result
    assert "130" in result


def test_matcher_weather(monkeypatch):
    monkeypatch.setattr(
        web_tools.web,
        "get_weather",
        lambda city: {"ok": True, "text": f"Weather in {city}: sunny"},
    )
    res = registry.run_direct("what's the weather in Nairobi?")
    assert res is not None
    assert res.tool == "weather"


def test_matcher_exchange(monkeypatch):
    monkeypatch.setattr(
        web_tools.web,
        "get_exchange_rate",
        lambda base, target: {
            "ok": True,
            "text": f"1 {base} = 130.0 {target}",
        },
    )
    res = registry.run_direct("what is the USD to KES exchange rate?")
    assert res is not None
    assert res.tool == "exchange_rate"
