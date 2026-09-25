"""The two HTTP calls the key layer needs.

Not a general-purpose HTTP client. `brain/http.py` exists so that
`brain/keys.py` can validate a key without importing httpx itself,
and so tests can monkeypatch a single module.

The two functions:

    fetch_model_list(key)  →  ask a provider which models this key can see
    probe_key(key)         →  send one "say OK" and see what comes back

Everything here is async. The key layer calls these from an event
loop; if it is called from sync code, wrap in asyncio.run().
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from toolkit.brain.providers import (
    BOOK,
    chat_url,
    error_message,
    models_url,
)
from toolkit.brain.keys import Key


TIMEOUT = 30.0


# ── model list ────────────────────────────────────────────────────────

async def fetch_model_list_async(key: Key) -> dict[str, Any]:
    """Ask a provider which models this key can reach.

    Returns:
        {"ok": True, "models": [...], "meta": {...}}
        {"ok": False, "why": "..."}

    The meta dict maps model id → {"free": bool, "declared": bool}.
    Meta is best-effort: if the provider does not tell us, it is
    absent, and the scorer treats absent as neutral.
    """
    provider = BOOK.get(key.provider)
    if provider is None:
        return {"ok": False, "why": f"Unknown company: {key.provider}"}

    url = models_url(provider, key.key, key.account)
    headers: dict[str, str] = {}
    if provider.shape != "google":
        headers["Authorization"] = f"Bearer {key.key}"

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            res = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        return {"ok": False, "why": f"Could not reach {provider.label}: {exc}"}

    if res.status_code != 200:
        return {
            "ok": False,
            "why": (
                f"{provider.label} would not list its models "
                f"({res.status_code}). Usually a bad key. "
                f"{error_message(res.text)[:120]}"
            ),
        }

    try:
        data = res.json()
    except json.JSONDecodeError:
        return {"ok": False, "why": "Its model list was unreadable."}

    if provider.shape == "google":
        return _parse_google_models(data)

    return _parse_openai_models(data, provider)


def _parse_google_models(data: dict[str, Any]) -> dict[str, Any]:
    """Google's model list has a 'supportedGenerationMethods' array."""
    arr = data.get("models") or []
    ids: list[str] = []
    meta: dict[str, dict[str, Any]] = {}
    for entry in arr:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").replace("models/", "")
        if not name:
            continue
        methods = (
            entry.get("supportedGenerationMethods")
            or entry.get("supportedActions")
            or []
        )
        # Google states what each model does. Keep only chat ones.
        if methods:
            if "generateContent" not in methods:
                continue
        elif not name.startswith(("gemini", "gemma")):
            continue
        ids.append(name)
        meta[name] = {"free": True, "chat": True, "declared": True}
    if not ids:
        return {"ok": False, "why": "Google returned no chat models."}
    return {"ok": True, "models": ids, "meta": meta}


def _parse_openai_models(
    data: dict[str, Any], provider: Any
) -> dict[str, Any]:
    """OpenAI-shape model lists vary in detail. Be conservative."""
    raw: list[Any] = []
    if isinstance(data, list):
        raw = data
    elif isinstance(data, dict):
        raw = data.get("data") or data.get("models") or []

    ids: list[str] = []
    meta: dict[str, dict[str, Any]] = {}

    for entry in raw:
        if isinstance(entry, str):
            model_id = entry
            entry = {}
        elif isinstance(entry, dict):
            model_id = str(entry.get("id") or entry.get("name") or "")
        else:
            continue
        if not model_id:
            continue

        # Skip obvious non-chat models if the provider names their type
        entry_type = str(entry.get("type") or "").lower()
        if entry_type and any(
            word in entry_type
            for word in ("embed", "image", "audio", "video",
                         "moderation", "rerank", "speech", "vision",
                         "code_completion")
        ):
            continue

        # OpenRouter declares modality
        arch = entry.get("architecture") or {}
        modality = str(arch.get("modality") or "")
        if modality and "->text" not in modality:
            continue

        # OpenRouter also declares pricing
        free: bool | None = None
        pricing = entry.get("pricing") or {}
        if ":free" in model_id:
            free = True
        elif pricing.get("prompt") is not None:
            try:
                free = float(pricing["prompt"]) == 0
            except (TypeError, ValueError):
                free = None

        capabilities = entry.get("capabilities") or {}
        declared = capabilities.get("completion_chat") is True

        ids.append(model_id)
        meta[model_id] = {"free": free, "chat": True, "declared": declared}

    if not ids:
        return {
            "ok": False,
            "why": f"{provider.label} returned no chat models on this key.",
        }
    return {"ok": True, "models": ids, "meta": meta}


def fetch_model_list(key: Key) -> dict[str, Any]:
    """Blocking wrapper. Used by the synchronous key layer."""
    import asyncio

    return asyncio.run(fetch_model_list_async(key))


# ── probe ─────────────────────────────────────────────────────────────

async def probe_key_async(key: Key, prompt: str = "Reply with the single word: OK") -> dict[str, Any]:
    """Send one small request to prove the key and model work.

    Returns:
        {"ok": True, "model": "...", "text": "OK"}
        {"ok": False, "why": "...", "rest": bool}

    "rest" means the provider told us to back off (429). The key
    layer uses that to put the key on cooldown.
    """
    provider = BOOK.get(key.provider)
    if provider is None:
        return {"ok": False, "why": f"Unknown company: {key.provider}"}

    if not key.model:
        return {"ok": False, "why": "No model chosen for this key."}

    url = chat_url(provider, key.model, key.key, key.account)
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if provider.shape != "google":
        headers["Authorization"] = f"Bearer {key.key}"

    if provider.shape == "google":
        body = {"contents": [{"parts": [{"text": prompt}]}]}
    else:
        body = {
            "model": key.model,
            "messages": [{"role": "user", "content": prompt}],
        }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            res = await client.post(url, headers=headers, json=body)
    except httpx.HTTPError as exc:
        return {"ok": False, "why": f"Could not reach {provider.label}: {exc}"}

    if res.status_code == 200:
        try:
            text = _read_text(provider.shape, res.text)
        except ValueError as exc:
            return {"ok": False, "why": str(exc)}
        return {"ok": True, "model": key.model, "text": text}

    why = error_message(res.text) or f"HTTP {res.status_code}"
    rest = res.status_code == 429
    return {"ok": False, "why": why[:200], "rest": rest}


def _read_text(shape: str, body: str) -> str:
    """Extract the assistant's reply from a completion body."""
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Unreadable reply ({exc.msg})") from exc

    if shape == "google":
        candidates = data.get("candidates") or []
        if candidates:
            parts = (candidates[0].get("content") or {}).get("parts") or []
            for part in parts:
                if part.get("text"):
                    return str(part["text"]).strip()
    else:
        choices = data.get("choices") or []
        if choices:
            msg = choices[0].get("message") or {}
            if msg.get("content"):
                return str(msg["content"]).strip()

    err = data.get("error")
    if isinstance(err, dict) and err.get("message"):
        raise ValueError(str(err["message"])[:200])
    raise ValueError("The reply had no text in it.")


def probe_key(key: Key) -> dict[str, Any]:
    """Blocking wrapper."""
    import asyncio

    return asyncio.run(probe_key_async(key))