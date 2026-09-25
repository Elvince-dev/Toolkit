"""The provider book: who they are, where they live, how to talk to them.

Ported from Code.gs BOOK. The data is identical — same URLs, same
prefixes, same free/paid flags. Only the shape changed:

    before:  var BOOK = { gemini: { label:'...', shape:'google', ... }, ... }
    after:   BOOK: dict[str, Provider] = { "gemini": Provider(...), ... }

Two shapes:
    "openai"  — /chat/completions, Authorization: Bearer
    "google"  — /models/{model}:generateContent, ?key=

Nothing else in the toolkit needs to know which shape a provider is.
build_request() and read_reply() handle the difference.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

Shape = Literal["openai", "google"]


@dataclass(frozen=True)
class Provider:
    """One AI company, and how to talk to it."""

    id: str
    label: str
    shape: Shape
    base: str
    prefix: str = ""
    free: bool = True
    get: str = ""
    needs_account: bool = False


# ── the book ──────────────────────────────────────────────────────────
# Every entry here has been verified to work at least once. If you add
# one, verify it before committing.

BOOK: dict[str, Provider] = {
    "gemini": Provider(
        id="gemini", label="Google Gemini", shape="google",
        prefix="AIza", free=True,
        base="https://generativelanguage.googleapis.com/v1beta",
        get="aistudio.google.com/apikey",
    ),
    "groq": Provider(
        id="groq", label="Groq", shape="openai",
        prefix="gsk_", free=True,
        base="https://api.groq.com/openai/v1",
        get="console.groq.com/keys",
    ),
    "openrouter": Provider(
        id="openrouter", label="OpenRouter", shape="openai",
        prefix="sk-or-", free=True,
        base="https://openrouter.ai/api/v1",
        get="openrouter.ai/keys",
    ),
    "cerebras": Provider(
        id="cerebras", label="Cerebras", shape="openai",
        prefix="csk-", free=True,
        base="https://api.cerebras.ai/v1",
        get="cloud.cerebras.ai",
    ),
    "nvidia": Provider(
        id="nvidia", label="NVIDIA NIM", shape="openai",
        prefix="nvapi-", free=True,
        base="https://integrate.api.nvidia.com/v1",
        get="build.nvidia.com",
    ),
    "together": Provider(
        id="together", label="Together AI", shape="openai",
        prefix="tgp_", free=True,
        base="https://api.together.xyz/v1",
        get="api.together.ai",
    ),
    "huggingface": Provider(
        id="huggingface", label="Hugging Face", shape="openai",
        prefix="hf_", free=True,
        base="https://router.huggingface.co/v1",
        get="huggingface.co/settings/tokens",
    ),
    "mistral": Provider(
        id="mistral", label="Mistral", shape="openai",
        prefix="", free=True,
        base="https://api.mistral.ai/v1",
        get="console.mistral.ai",
    ),
    "deepseek": Provider(
        id="deepseek", label="DeepSeek", shape="openai",
        prefix="sk-", free=False,
        base="https://api.deepseek.com/v1",
        get="platform.deepseek.com",
    ),
    "openai": Provider(
        id="openai", label="OpenAI", shape="openai",
        prefix="sk-proj-", free=False,
        base="https://api.openai.com/v1",
        get="platform.openai.com",
    ),
    "fireworks": Provider(
        id="fireworks", label="Fireworks AI", shape="openai",
        prefix="fw_", free=True,
        base="https://api.fireworks.ai/inference/v1",
        get="fireworks.ai/account/api-keys",
    ),
    "chutes": Provider(
        id="chutes", label="Chutes AI", shape="openai",
        prefix="cpk_", free=True,
        base="https://llm.chutes.ai/v1",
        get="chutes.ai",
    ),
    "sambanova": Provider(
        id="sambanova", label="SambaNova", shape="openai",
        prefix="", free=True,
        base="https://api.sambanova.ai/v1",
        get="cloud.sambanova.ai",
    ),
    "nebius": Provider(
        id="nebius", label="Nebius AI Studio", shape="openai",
        prefix="", free=True,
        base="https://api.studio.nebius.com/v1",
        get="studio.nebius.com",
    ),
    "deepinfra": Provider(
        id="deepinfra", label="DeepInfra", shape="openai",
        prefix="", free=True,
        base="https://api.deepinfra.com/v1/openai",
        get="deepinfra.com/dash/api_keys",
    ),
    "hyperbolic": Provider(
        id="hyperbolic", label="Hyperbolic", shape="openai",
        prefix="", free=True,
        base="https://api.hyperbolic.xyz/v1",
        get="app.hyperbolic.xyz",
    ),
    "scaleway": Provider(
        id="scaleway", label="Scaleway", shape="openai",
        prefix="", free=True,
        base="https://api.scaleway.ai/v1",
        get="console.scaleway.com",
    ),
    "cohere": Provider(
        id="cohere", label="Cohere", shape="openai",
        prefix="", free=True,
        base="https://api.cohere.ai/compatibility/v1",
        get="dashboard.cohere.com/api-keys",
    ),
    "ai21": Provider(
        id="ai21", label="AI21 Labs", shape="openai",
        prefix="", free=True,
        base="https://api.ai21.com/studio/v1",
        get="studio.ai21.com",
    ),
    "ollama": Provider(
        id="ollama", label="Ollama Cloud", shape="openai",
        prefix="", free=True,
        base="https://ollama.com/v1",
        get="ollama.com",
    ),
    "cloudflare": Provider(
        id="cloudflare", label="Cloudflare Workers AI", shape="openai",
        prefix="", free=True,
        base="https://api.cloudflare.com/client/v4/accounts/{account}/ai/v1",
        needs_account=True,
        get="dash.cloudflare.com/profile/api-tokens",
    ),
    "ovh": Provider(
        id="ovh", label="OVH AI Endpoints", shape="openai",
        prefix="", free=True,
        base="https://oai.endpoints.kepler.ai.cloud.ovh.net/v1",
        get="endpoints.ai.cloud.ovh.net",
    ),
    "github": Provider(
        id="github", label="GitHub Models", shape="openai",
        prefix="github_pat_", free=True,
        base="https://models.github.ai/inference",
        get="github.com/settings/tokens",
    ),
    "nscale": Provider(
        id="nscale", label="Nscale", shape="openai",
        prefix="", free=True,
        base="https://inference.api.nscale.com/v1",
        get="console.nscale.com",
    ),
    "siliconflow": Provider(
        id="siliconflow", label="SiliconFlow", shape="openai",
        prefix="", free=True,
        base="https://api.siliconflow.com/v1",
        get="siliconflow.com",
    ),
    "zai": Provider(
        id="zai", label="Z.AI (Zhipu)", shape="openai",
        prefix="", free=True,
        base="https://api.z.ai/api/paas/v4",
        get="z.ai",
    ),
    "modelscope": Provider(
        id="modelscope", label="ModelScope", shape="openai",
        prefix="", free=True,
        base="https://api-inference.modelscope.cn/v1",
        get="modelscope.cn",
    ),
    "llm7": Provider(
        id="llm7", label="LLM7 (no key needed)", shape="openai",
        prefix="", free=True,
        base="https://api.llm7.io/v1",
        get="llm7.io",
    ),
}


# ── detection ─────────────────────────────────────────────────────────

def detect_provider(key: str) -> str:
    """Find the provider id by key prefix.

    Returns "" if the prefix matches nothing. The caller then falls
    back to trying providers one by one.
    """
    k = key.strip()
    best = ""
    best_len = -1
    for pid, provider in BOOK.items():
        if provider.prefix and k.startswith(provider.prefix):
            if len(provider.prefix) > best_len:
                best = pid
                best_len = len(provider.prefix)
    return best


def split_account_key(raw: str, force: bool = False) -> tuple[str, str]:
    """Split 'account:key' into its parts.

    Cloudflare is the only provider that needs this. The rule: if
    there is no colon, or the colon is at position 0, there is no
    account. If there is a colon before position 8 and force is
    False, treat the whole thing as a key (it is probably a prefix
    that happens to contain a colon).
    """
    s = str(raw or "").strip()
    i = s.find(":")
    if i < 1:
        return "", s
    if not force and i < 8:
        return "", s
    return s[:i].strip(), s[i + 1:].strip()


# ── URL building ──────────────────────────────────────────────────────

def _with_account(base: str, account: str) -> str:
    return base.replace("{account}", account or "")


def _base_for(provider: Provider, account: str = "") -> str:
    if provider.needs_account:
        return _with_account(provider.base, account)
    return provider.base


def chat_url(
    provider: Provider, model: str, key: str, account: str = ""
) -> str:
    """The URL to POST to for a chat completion."""
    if provider.shape == "google":
        return (
            f"{provider.base}/models/{model}:generateContent"
            f"?key={key}"
        )
    return f"{_base_for(provider, account)}/chat/completions"


def models_url(provider: Provider, key: str, account: str = "") -> str:
    """The URL to GET for the model list."""
    if provider.shape == "google":
        return f"{provider.base}/models?key={key}"
    return f"{_base_for(provider, account)}/models"


# ── request building ──────────────────────────────────────────────────

def build_request(
    provider: Provider,
    model: str,
    key: str,
    prompt: str,
    *,
    account: str = "",
    system: str | None = None,
    turns: list[dict[str, str]] | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Build a chat-completion request.

    Returns {"url": ..., "method": "post", "headers": {...}, "json": {...}}
    — plain data the caller passes to httpx. No I/O here.
    """
    url = chat_url(provider, model, key, account)

    if provider.shape == "google":
        # Google uses "contents", a list of {role, parts}. System
        # messages go in "system_instruction", not as a turn.
        contents: list[dict[str, Any]] = []
        for turn in turns or []:
            role = "user" if turn.get("role") == "user" else "model"
            text = str(turn.get("text") or "")
            if text:
                contents.append({"role": role, "parts": [{"text": text}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        body: dict[str, Any] = {"contents": contents}
        if system:
            body["system_instruction"] = {"parts": [{"text": system}]}
        if temperature is not None or max_tokens is not None:
            gen: dict[str, Any] = {}
            if temperature is not None:
                gen["temperature"] = temperature
            if max_tokens is not None:
                gen["maxOutputTokens"] = max_tokens
            body["generationConfig"] = gen

        return {
            "url": url,
            "method": "post",
            "headers": {"Content-Type": "application/json"},
            "json": body,
        }

    # OpenAI shape
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    for turn in turns or []:
        role = turn.get("role") or "user"
        if role not in ("user", "assistant", "system"):
            role = "user"
        text = str(turn.get("text") or "")
        if text:
            messages.append({"role": role, "content": text})
    messages.append({"role": "user", "content": prompt})

    body = {"model": model, "messages": messages}
    if temperature is not None:
        body["temperature"] = temperature
    if max_tokens is not None:
        body["max_tokens"] = max_tokens

    return {
        "url": url,
        "method": "post",
        "headers": {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        "json": body,
    }


def read_reply(provider: Provider, body: str | bytes) -> str:
    """Pull the assistant's text out of a completion response.

    Raises ValueError with a readable message if there is no text.
    The agent loop catches this and diagnoses further.
    """
    text = body.decode("utf-8") if isinstance(body, bytes) else str(body)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"The reply was not readable JSON ({exc.msg}). "
            f"First 200 characters: {text[:200]}"
        ) from exc

    if provider.shape == "google":
        candidates = data.get("candidates") or []
        if candidates:
            parts = (candidates[0].get("content") or {}).get("parts") or []
            for part in parts:
                t = part.get("text")
                if t:
                    return str(t).strip()
    else:
        choices = data.get("choices") or []
        if choices:
            message = choices[0].get("message") or {}
            content = message.get("content")
            if content:
                return str(content).strip()

    # No text — try to say why
    err = data.get("error")
    if isinstance(err, dict) and err.get("message"):
        raise ValueError(str(err["message"])[:200])
    if isinstance(err, str):
        raise ValueError(err[:200])
    raise ValueError("The reply had no text in it.")


def error_message(body: str | bytes) -> str:
    """Extract a short human-readable error from an error response.

    Tries, in order: JSON error objects, JSON error strings, JSON
    message fields, then the raw text, then "".
    """
    raw = body.decode("utf-8") if isinstance(body, bytes) else str(body)
    if not raw.strip():
        return ""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return " ".join(raw.split())[:200]

    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, str):
            return err[:200]
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])[:200]
        if err and err.get("code"):
            return str(err["code"])[:200]
        for key in ("message", "detail"):
            if data.get(key):
                v = data[key]
                if isinstance(v, str):
                    return v[:200]
                return json.dumps(v)[:200]
        errors = data.get("errors")
        if isinstance(errors, list) and errors:
            first = errors[0]
            if isinstance(first, dict) and first.get("message"):
                return str(first["message"])[:200]
    return ""