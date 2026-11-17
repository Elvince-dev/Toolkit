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

import asyncio
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

def run_sync(coro):
    """Run an async coroutine from sync code, whether or not a loop
    is already running.

    The naive `asyncio.run(coro)` raises RuntimeError if a loop is
    already running. That happens when sync code (keys.add_key,
    keys.heal_all_keys, the CLI) is called from inside async code
    (a future OAuth callback, a notebook, a test runner that uses
    pytest-asyncio). nest_asyncio patches the running loop so the
    inner coroutine can be awaited; on a clean thread it does
    nothing and asyncio.run works normally.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No loop running. The simple path.
        return asyncio.run(coro)

    # A loop is already running. nest_asyncio lets us re-enter it.
    import nest_asyncio
    nest_asyncio.apply(loop)
    return loop.run_until_complete(coro)

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
    return run_sync(fetch_model_list_async(key))


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
    return run_sync(probe_key_async(key))


# ── the chat call the agent uses ──────────────────────────────────────

async def call_ai_async(
    prompt: str,
    *,
    system: str | None = None,
    turns: list[dict[str, str]] | None = None,
    only_key_id: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    """Send a prompt to whichever key answers first.

    This is the core function. Everything the agent does goes through
    here.

    Behaviour, in order:

      1. Load every enabled key.
      2. Sort them by reliability (wins / (wins + fails)).
      3. Try each in turn:
           - post the request
           - on 200: return the text
           - on 429: rest the key for 65s and try the next
           - on 4xx that means "bad model": mark the model bad and
             try the next-best model on the same key
           - on 5xx or network error: try the next key
      4. If every key fails, return a sentence explaining what went
         wrong. Never raises.

    The response is always a string, on purpose — the agent loop
    treats "here is the answer" and "here is why I could not answer"
    as the same thing, because both are worth saying to the user.
    """
    from toolkit.brain.keys import (
        bad_models_for,
        is_resting,
        load_keys,
        mark_bad_model,
        pick_best_model,
        rest_key,
        set_key_model,
        clear_bad_models,
    )

    keys = [k for k in load_keys() if k.enabled]
    if not keys:
        return (
            "NO KEYS YET — add one from aistudio.google.com or "
            "console.groq.com, then try again."
        )
    if only_key_id:
        keys = [k for k in keys if k.id == only_key_id]
        if not keys:
            return "That key is gone."

    # Sort by reliability, most reliable first. Ties broken randomly
    # so we do not always hammer the same key.
    import random
    random.shuffle(keys)
    keys.sort(
        key=lambda k: (k.wins + 1) / (k.wins + k.fails + 2),
        reverse=True,
    )

    resting_count = 0
    errors: list[str] = []

    for k in keys:
        if is_resting(k.id):
            resting_count += 1
            continue

        result = await _try_one(
            k,
            prompt,
            system=system,
            turns=turns,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if result["ok"]:
            _bump_wins(k.id)
            return result["text"]

        # Failure modes
        if result.get("billing"):
            errors.append(f"{k.label}: no credit left")
            continue
        if result.get("rest"):
            rest_key(k.id, 65)
            errors.append(f"{k.label}: rate limited")
            continue
        if result.get("model_bad") and result.get("tried"):
            errors.append(
                f"{k.label}: models tried {result['tried']}"
            )
            continue
        errors.append(f"{k.label}: {result.get('why', 'unknown')[:120]}")

    if resting_count and resting_count == len(keys):
        return (
            "ALL KEYS ARE RESTING — wait about a minute, or add "
            "another key."
        )
    if errors:
        return (
            "I could not get an answer. What each key said:\n"
            + "\n".join(f"  · {e}" for e in errors[:5])
        )
    return "NO KEY AVAILABLE — every key is off."


async def _try_one(
    key: Any,
    prompt: str,
    *,
    system: str | None,
    turns: list[dict[str, str]] | None,
    temperature: float | None,
    max_tokens: int | None,
) -> dict[str, Any]:
    """One key. Try the current model; on model errors, heal and retry.

    Returns a dict with at minimum {"ok": bool}. On success, "text".
    On failure, "why" and possibly "rest", "billing", "model_bad".
    """
    from toolkit.brain.keys import (
        bad_models_for,
        clear_bad_models,
        discover_model_for_key,
        mark_bad_model,
        pick_best_model,
        set_key_model,
    )

    provider = BOOK.get(key.provider)
    if provider is None:
        return {"ok": False, "why": f"Unknown company: {key.provider}"}

    # If the key has no model, discover one.
    if not key.model:
        models, model, why = discover_model_for_key(key)
        if not model:
            return {"ok": False, "why": why or "no usable model"}
        key.model = model
        key.models = models
        set_key_model(key.id, model)

    # Try the current model first.
    result = await _post_completion(
        key, prompt,
        system=system, turns=turns,
        temperature=temperature, max_tokens=max_tokens,
    )
    if result["ok"]:
        return result

    # If it looks like a model problem, try healing up to 4 more times.
    if result.get("model_bad"):
        tried = [key.model]
        last_why = result.get("why", "")
        for _ in range(4):
            mark_bad_model(key.id, key.model)
            models, model, why = discover_model_for_key(key)
            if not model:
                return {"ok": False, "why": why, "model_bad": True,
                        "tried": ", ".join(tried)}
            key.model = model
            key.models = models
            set_key_model(key.id, model)
            tried.append(model)

            result = await _post_completion(
                key, prompt,
                system=system, turns=turns,
                temperature=temperature, max_tokens=max_tokens,
            )
            if result["ok"]:
                return result
            if not result.get("model_bad"):
                # Not a model problem anymore, give up on this key.
                return result
            last_why = result.get("why", "")

        return {"ok": False, "why": last_why, "model_bad": True,
                "tried": ", ".join(tried[:4])}

    return result


async def _post_completion(
    key: Any,
    prompt: str,
    *,
    system: str | None,
    turns: list[dict[str, str]] | None,
    temperature: float | None,
    max_tokens: int | None,
) -> dict[str, Any]:
    """One POST. Diagnose the response into a structured result."""
    from toolkit.brain.providers import build_request

    provider = BOOK.get(key.provider)
    if provider is None:
        return {"ok": False, "why": f"Unknown company: {key.provider}"}

    req = build_request(
        provider, key.model, key.key, prompt,
        account=key.account,
        system=system, turns=turns,
        temperature=temperature, max_tokens=max_tokens,
    )

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            res = await client.post(
                req["url"], headers=req["headers"], json=req["json"],
            )
    except httpx.HTTPError as exc:
        return {"ok": False, "why": f"network error: {exc}"}

    if res.status_code == 200:
        try:
            text = _read_text(provider.shape, res.text)
            return {"ok": True, "text": text}
        except ValueError as exc:
            return {"ok": False, "why": str(exc)}

    why = error_message(res.text) or f"HTTP {res.status_code}"

    # 429: rate limit OR busy model — distinguish by the body
    if res.status_code == 429:
        if any(
            marker in why.lower()
            for marker in ("provider returned error", "upstream",
                           "no available provider", "overloaded", "capacity")
        ):
            return {"ok": False, "why": why, "model_bad": True}
        return {"ok": False, "why": why, "rest": True}

    # 5xx: retry-able but not the key's fault
    if res.status_code >= 500:
        return {"ok": False, "why": why}

    # Billing
    low = why.lower()
    if any(marker in low for marker in (
        "payment required", "insufficient", "no credits",
        "out of credit", "credit balance", "quota exceeded",
        "exceeded your current quota", "billing", "top up",
        "add credits", "purchase", "upgrade your plan",
    )):
        return {"ok": False, "why": why, "billing": True}

    # 401/403: key rejected — not our problem to fix
    if res.status_code in (401, 403):
        return {"ok": False, "why": why, "permanent": True}

    # 404: model gone
    if res.status_code == 404:
        return {"ok": False, "why": why, "model_bad": True}

    # 400 with "model" wording: model rejected
    if res.status_code == 400 and any(
        marker in low
        for marker in ("model", "not found", "unsupported",
                       "deprecat", "does not exist", "no such")
    ):
        return {"ok": False, "why": why, "model_bad": True}

    return {"ok": False, "why": why}


def _bump_wins(key_id: str) -> None:
    """Increase the win counter for a key, non-fatally."""
    try:
        from toolkit.brain import keys as km
        with km._db() as conn:  # noqa: SLF001 — internal use by design
            conn.execute(
                "UPDATE keys SET wins = wins + 1 WHERE id = ?",
                (key_id,),
            )
    except Exception:
        pass

def call_ai(
    prompt: str,
    *,
    system: str | None = None,
    turns: list[dict[str, str]] | None = None,
    only_key_id: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    """Blocking wrapper around call_ai_async. Used by the CLI."""
    return run_sync(call_ai_async(
        prompt,
        system=system, turns=turns,
        only_key_id=only_key_id,
        temperature=temperature, max_tokens=max_tokens,
    ))