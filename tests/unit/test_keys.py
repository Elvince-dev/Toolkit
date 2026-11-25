"""The provider book, the key store, and the model scorer."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from toolkit.adapters import registry as adapter_registry
from toolkit.brain import http as http_mod
from toolkit.brain import keys as keys_mod
from toolkit.brain.providers import (
    BOOK,
    build_request,
    detect_provider,
    read_reply,
    split_account_key,
)
from toolkit.config import settings


@pytest.fixture(autouse=True)
def clean_db(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TOOLKIT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TOOLKIT_AI_PROVIDER", "")
    monkeypatch.setenv("TOOLKIT_AI_API_KEY", "")
    settings.cache_clear()
    adapter_registry.reset()
    keys_mod.load_keys.cache_clear() if hasattr(keys_mod.load_keys, "cache_clear") else None
    yield
    settings.cache_clear()
    adapter_registry.reset()


# ── the book ──────────────────────────────────────────────────────────

def test_book_has_the_expected_companies():
    for pid in ("gemini", "groq", "openrouter", "cerebras", "openai"):
        assert pid in BOOK


def test_every_provider_has_a_base_url():
    for pid, p in BOOK.items():
        assert p.base.startswith("https://"), f"{pid} has no base URL"


def test_detect_provider_by_prefix():
    assert detect_provider("gsk_abc123") == "groq"
    assert detect_provider("AIzaSyTest") == "gemini"
    assert detect_provider("sk-or-abc") == "openrouter"
    assert detect_provider("csk-abc") == "cerebras"


def test_detect_provider_longest_prefix_wins():
    # sk- matches deepseek, sk-or- matches openrouter. Longer wins.
    assert detect_provider("sk-or-abc") == "openrouter"
    assert detect_provider("sk-abc") == "deepseek"


def test_detect_provider_returns_empty_for_unknown():
    assert detect_provider("nonsense") == ""


def test_split_account_key():
    # No colon
    assert split_account_key("abc") == ("", "abc")
    # Colon at start
    assert split_account_key(":abc") == ("", ":abc")
    # Short account — treated as part of the key unless forced
    assert split_account_key("a:bcd") == ("", "a:bcd")
    assert split_account_key("a:bcd", force=True) == ("a", "bcd")
    # Normal split
    assert split_account_key("account123:token456") == (
        "account123", "token456"
    )


# ── request building ──────────────────────────────────────────────────

def test_build_request_openai_shape():
    provider = BOOK["groq"]
    req = build_request(provider, "llama-3.1-8b", "gsk_x", "hi")
    assert req["url"].endswith("/chat/completions")
    assert req["headers"]["Authorization"] == "Bearer gsk_x"
    assert req["json"]["model"] == "llama-3.1-8b"
    assert req["json"]["messages"][-1]["content"] == "hi"


def test_build_request_google_shape():
    provider = BOOK["gemini"]
    req = build_request(provider, "gemini-2.5-flash", "AIza", "hi")
    assert "generateContent" in req["url"]
    assert "key=AIza" in req["url"]
    assert "Authorization" not in req["headers"]
    assert req["json"]["contents"][-1]["parts"][0]["text"] == "hi"


def test_build_request_google_with_system():
    provider = BOOK["gemini"]
    req = build_request(provider, "gemini-2.5-flash", "AIza", "hi", system="be brief")
    assert req["json"]["system_instruction"]["parts"][0]["text"] == "be brief"


def test_build_request_with_turns():
    provider = BOOK["groq"]
    req = build_request(
        provider, "llama-3.1-8b", "gsk_x", "and now?",
        turns=[
            {"role": "user", "text": "hello"},
            {"role": "assistant", "text": "hi"},
        ],
    )
    roles = [m["role"] for m in req["json"]["messages"]]
    assert roles == ["user", "assistant", "user"]


# ── reply reading ─────────────────────────────────────────────────────

def test_read_reply_openai():
    body = '{"choices":[{"message":{"content":"hi there"}}]}'
    assert read_reply(BOOK["groq"], body) == "hi there"


def test_read_reply_google():
    body = ('{"candidates":[{"content":{"parts":[{"text":"hi there"}]}}]}')
    assert read_reply(BOOK["gemini"], body) == "hi there"


def test_read_reply_raises_on_error():
    body = '{"error":{"message":"bad key"}}'
    with pytest.raises(ValueError, match="bad key"):
        read_reply(BOOK["groq"], body)


def test_read_reply_raises_on_empty():
    with pytest.raises(ValueError):
        read_reply(BOOK["groq"], '{"choices":[]}')


# ── model scoring ─────────────────────────────────────────────────────

def test_score_model_rejects_embeddings():
    assert keys_mod.score_model("text-embedding-004") == keys_mod.NEVER
    assert keys_mod.score_model("whisper-large") == keys_mod.NEVER
    assert keys_mod.score_model("stable-diffusion-xl") == keys_mod.NEVER


def test_score_model_prefers_free():
    paid = keys_mod.score_model("gpt-4o", {"free": False})
    free = keys_mod.score_model("llama-3.3-70b", {"free": True})
    assert free > paid


def test_pick_best_model_returns_best():
    ids = ["text-embedding-004", "llama-3.3-70b-versatile", "gpt-4o"]
    meta = {
        "llama-3.3-70b-versatile": {"free": True},
        "gpt-4o": {"free": False},
    }
    best = keys_mod.pick_best_model(ids, [], meta)
    assert best == "llama-3.3-70b-versatile"


def test_pick_best_model_skips_excluded():
    ids = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
    best = keys_mod.pick_best_model(ids, exclude=["llama-3.3-70b-versatile"])
    assert best == "llama-3.1-8b-instant"


# ── key store ─────────────────────────────────────────────────────────

def test_load_keys_starts_empty():
    assert keys_mod.load_keys() == []


def test_load_keys_includes_server_managed_environment_key(monkeypatch):
    monkeypatch.setenv("TOOLKIT_AI_PROVIDER", "gemini")
    monkeypatch.setenv("TOOLKIT_AI_API_KEY", "AIzaTestKey")
    settings.cache_clear()

    keys = keys_mod.load_keys()

    assert len(keys) == 1
    assert keys[0].provider == "gemini"
    assert keys[0].key == "AIzaTestKey"
    assert keys[0].nickname == "Google Gemini (environment)"
    assert keys_mod.key_by_id(keys[0].id) is None


def test_load_keys_requires_provider_and_key_together(monkeypatch):
    monkeypatch.setenv("TOOLKIT_AI_API_KEY", "test-key")
    settings.cache_clear()

    with pytest.raises(ValueError, match="TOOLKIT_AI_PROVIDER"):
        keys_mod.load_keys()


def test_chat_does_not_ask_end_users_to_supply_provider_keys():
    with pytest.raises(
        http_mod.AIProviderError,
        match="contact the Toolkit administrator",
    ):
        asyncio.run(http_mod.call_ai_async("hello"))


def test_chat_stops_when_provider_model_discovery_fails(monkeypatch):
    monkeypatch.setenv("TOOLKIT_AI_PROVIDER", "gemini")
    monkeypatch.setenv("TOOLKIT_AI_API_KEY", "AIzaTestKey")
    settings.cache_clear()

    async def fail_discovery(key):
        return [], "", "Google Gemini: invalid API key"

    monkeypatch.setattr(keys_mod, "discover_model_for_key_async", fail_discovery)

    with pytest.raises(http_mod.AIProviderError, match="invalid API key"):
        asyncio.run(http_mod.call_ai_async("question"))


def test_async_chat_uses_async_model_discovery(monkeypatch):
    monkeypatch.setenv("TOOLKIT_AI_PROVIDER", "gemini")
    monkeypatch.setenv("TOOLKIT_AI_API_KEY", "AIzaTestKey")
    settings.cache_clear()

    async def discover(key):
        assert key.provider == "gemini"
        return ["test-model"], "test-model", ""

    async def complete(key, prompt, **kwargs):
        assert key.model == "test-model"
        return {"ok": True, "text": "answer"}

    monkeypatch.setattr(keys_mod, "discover_model_for_key_async", discover)
    monkeypatch.setattr(
        keys_mod,
        "discover_model_for_key",
        lambda key: pytest.fail("sync model discovery used in async chat"),
    )
    monkeypatch.setattr(http_mod, "_post_completion", complete)

    answer = asyncio.run(http_mod.call_ai_async("question"))

    assert answer == "answer"


def test_async_chat_retries_each_model_once_and_surfaces_reason(monkeypatch):
    monkeypatch.setenv("TOOLKIT_AI_PROVIDER", "gemini")
    monkeypatch.setenv("TOOLKIT_AI_API_KEY", "AIzaTestKey")
    settings.cache_clear()
    tried_models: list[str] = []
    available_models = ["gemini-2.5-flash-lite", "gemini-2.5-flash"]

    async def discover(key, *, exclude=None):
        next_model = next(
            (model for model in available_models if model not in (exclude or [])),
            "",
        )
        return available_models, next_model, "No untried model" if not next_model else ""

    async def reject_model(key, prompt, **kwargs):
        tried_models.append(key.model)
        return {
            "ok": False,
            "why": f"{key.model} rejected the request",
            "model_bad": True,
        }

    monkeypatch.setattr(keys_mod, "discover_model_for_key_async", discover)
    monkeypatch.setattr(http_mod, "_post_completion", reject_model)

    with pytest.raises(http_mod.AIProviderError) as exc_info:
        asyncio.run(http_mod.call_ai_async("question"))

    assert tried_models == available_models
    assert "gemini-2.5-flash rejected the request" in str(exc_info.value)
    assert "models tried: " + ", ".join(available_models) in str(exc_info.value)


def test_save_and_load_key():
    k = keys_mod.Key(
        id="k1", provider="groq", key="gsk_test",
        nickname="test groq", model="llama-3.1-8b",
    )
    keys_mod.save_key(k)
    loaded = keys_mod.load_keys()
    assert len(loaded) == 1
    assert loaded[0].nickname == "test groq"
    assert loaded[0].model == "llama-3.1-8b"


def test_toggle_key():
    k = keys_mod.Key(id="k1", provider="groq", key="gsk_test")
    keys_mod.save_key(k)
    assert keys_mod.toggle_key("k1") is False
    assert keys_mod.toggle_key("k1") is True


def test_remove_key():
    k = keys_mod.Key(id="k1", provider="groq", key="gsk_test")
    keys_mod.save_key(k)
    removed = keys_mod.remove_key("k1")
    assert removed is not None
    assert keys_mod.load_keys() == []


def test_rest_key():
    k = keys_mod.Key(id="k1", provider="groq", key="gsk_test")
    keys_mod.save_key(k)
    assert not keys_mod.is_resting("k1")
    keys_mod.rest_key("k1", seconds=1)
    assert keys_mod.is_resting("k1")


def test_mark_bad_model():
    k = keys_mod.Key(id="k1", provider="groq", key="gsk_test")
    keys_mod.save_key(k)
    keys_mod.mark_bad_model("k1", "gpt-4o")
    assert "gpt-4o" in keys_mod.bad_models_for("k1")
    keys_mod.clear_bad_models("k1")
    assert keys_mod.bad_models_for("k1") == []


def test_add_key_rejects_empty():
    result = keys_mod.add_key("", "", "")
    assert not result.ok
    assert "empty" in result.why.lower()


def test_add_key_rejects_unknown_prefix(monkeypatch):
    # Monkeypatch fetch_model_list so add_key does not go over the wire
    from toolkit.brain import http
    monkeypatch.setattr(
        http, "fetch_model_list",
        lambda k: {"ok": False, "why": "test"},
    )
    result = keys_mod.add_key("", "nonsense-key-with-no-prefix", "")
    assert not result.ok


def test_key_pool_when_empty():
    text = keys_mod.key_pool()
    assert "no keys" in text.lower()