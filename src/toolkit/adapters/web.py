"""Simple web tools — weather and exchange rates.

Not a general-purpose HTTP client. Two specific fetches, with
graceful failure. No API key required for either endpoint.
"""

from __future__ import annotations

import httpx

TIMEOUT = 10.0
UA = "Toolkit/1.0 (+https://github.com/yourname/toolkit)"


async def get_weather_async(city: str) -> dict:
    """Current weather for a city.

    Returns {"ok": True, "text": "..."} or {"ok": False, "why": "..."}.
    """
    city_clean = city.strip().replace(" ", "+")
    url = f"https://wttr.in/{city_clean}?format=j1"

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            res = await client.get(url, headers={"User-Agent": UA})
    except httpx.HTTPError as exc:
        return {"ok": False, "why": f"Could not reach weather service: {exc}"}

    if res.status_code != 200:
        return {"ok": False, "why": f"Weather service returned {res.status_code}."}

    try:
        data = res.json()
    except Exception:
        return {"ok": False, "why": "Weather service returned unreadable data."}

    current = data.get("current_condition", [{}])[0]
    if not current:
        return {"ok": False, "why": f"No weather data for {city}."}

    temp_c = current.get("temp_C", "?")
    feels = current.get("FeelsLikeC", "?")
    desc = current.get("weatherDesc", [{}])[0].get("value", "?")
    humidity = current.get("humidity", "?")
    wind_kmph = current.get("windspeedKmph", "?")

    text = (
        f"Weather in {city}:\n"
        f"  {desc}, {temp_c}°C (feels like {feels}°C)\n"
        f"  Humidity: {humidity}%\n"
        f"  Wind: {wind_kmph} km/h"
    )
    return {"ok": True, "text": text}


async def get_exchange_rate_async(base: str, target: str) -> dict:
    """Exchange rate between two currencies.

    Uses Frankfurter (ECB data, no key).
    """
    base_clean = base.strip().upper()[:3]
    target_clean = target.strip().upper()[:3]
    url = f"https://api.frankfurter.app/latest?from={base_clean}&to={target_clean}"

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            res = await client.get(url, headers={"User-Agent": UA})
    except httpx.HTTPError as exc:
        return {"ok": False, "why": f"Could not reach exchange service: {exc}"}

    if res.status_code != 200:
        return {"ok": False, "why": f"Exchange service returned {res.status_code}."}

    try:
        data = res.json()
    except Exception:
        return {"ok": False, "why": "Exchange service returned unreadable data."}

    rate = data.get("rates", {}).get(target_clean)
    if rate is None:
        return {"ok": False, "why": f"No rate for {base_clean}→{target_clean}."}

    date = data.get("date", "unknown")
    text = (
        f"1 {base_clean} = {rate:.4f} {target_clean}\n"
        f"  (source: ECB, date: {date})"
    )
    return {"ok": True, "text": text}


def get_weather(city: str) -> dict:
    from toolkit.brain.http import run_sync
    return run_sync(get_weather_async(city))


def get_exchange_rate(base: str, target: str) -> dict:
    from toolkit.brain.http import run_sync
    return run_sync(get_exchange_rate_async(base, target))
