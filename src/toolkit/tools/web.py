"""Web tools — weather and exchange rates."""

from __future__ import annotations

from typing import Any

from toolkit.adapters import web
from toolkit.tools.registry import Tool

TOOLS: dict[str, Tool] = {}


def register(tool: Tool) -> None:
    TOOLS[tool.name] = tool


def _weather(args: dict[str, Any]) -> str:
    city = str(args.get("city") or "").strip()
    if not city:
        return "Which city? Give me a place name."

    result = web.get_weather(city)
    if not result.get("ok"):
        return f"I could not get the weather: {result.get('why', 'unknown error')}"
    return result["text"]


def _exchange(args: dict[str, Any]) -> str:
    base = str(args.get("base") or "").strip().upper()
    target = str(args.get("target") or "").strip().upper()

    if not base or not target:
        return "Which currencies? Say 'USD to KES' for example."

    result = web.get_exchange_rate(base, target)
    if not result.get("ok"):
        return f"I could not get the rate: {result.get('why', 'unknown error')}"
    return result["text"]


register(Tool(
    name="weather",
    what="get the current weather for a city",
    need=("city",),
    run=_weather,
))

register(Tool(
    name="exchange_rate",
    what="get the exchange rate between two currencies",
    need=("base", "target"),
    run=_exchange,
))
