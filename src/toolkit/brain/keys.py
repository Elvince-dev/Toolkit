"""API keys: storage, rotation, model discovery, self-healing.

Ported from Code.gs. What changed:

  * Storage moved from PropertiesService (9KB ceiling, sharded) to
    SQLite. The sharding logic, the size checks, and the "over the
    limit" errors that Code.gs works around are all gone.
  * Keys are stored in plaintext in data/keys.db. Protect that file
    with filesystem permissions. If you need encryption, wrap the
    file in SQLCipher or an encrypted volume — do not roll your own.
  * The public API is the same shape. load_keys, add_key, remove_key,
    toggle_key, set_key_model, heal_all_keys all exist and mean what
    they meant.

What stays exactly the same:

  * Prefix detection (delegates to providers.detect_provider).
  * Model scoring (which model to prefer when a provider offers many).
  * Self-healing when a saved model goes stale.
  * Room-for-another-per-company (7 keys maximum).
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator

from toolkit.brain.providers import (
    BOOK,
    Provider,
    detect_provider,
    split_account_key,
)
from toolkit.config import settings


# ── the data shape ────────────────────────────────────────────────────

@dataclass
class Key:
    """One API key, and what we know about it.

    This is the Python equivalent of the objects Code.gs stored in
    its AI_KEYS_V1 property, with the same fields. Field names are
    snake_case (Python convention); the original's camelCase names
    are noted in comments where they matter.
    """

    id: str
    provider: str
    key: str
    model: str = ""
    models: list[str] = field(default_factory=list)
    account: str = ""
    nickname: str = ""
    enabled: bool = True
    wins: int = 0
    fails: int = 0
    created_at: float = field(default_factory=time.time)
    resting_until: float = 0.0
    bad_models: list[str] = field(default_factory=list)

    @property
    def resting(self) -> bool:
        return self.resting_until > time.time()

    @property
    def label(self) -> str:
        """What to call this key in a message."""
        if self.nickname:
            return self.nickname
        provider = BOOK.get(self.provider)
        return provider.label if provider else self.provider


# ── storage ───────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS keys (
    id              TEXT PRIMARY KEY,
    provider        TEXT NOT NULL,
    key             TEXT NOT NULL UNIQUE,
    model           TEXT NOT NULL DEFAULT '',
    models          TEXT NOT NULL DEFAULT '[]',
    account         TEXT NOT NULL DEFAULT '',
    nickname        TEXT NOT NULL DEFAULT '',
    enabled         INTEGER NOT NULL DEFAULT 1,
    wins            INTEGER NOT NULL DEFAULT 0,
    fails           INTEGER NOT NULL DEFAULT 0,
    created_at      REAL NOT NULL,
    resting_until   REAL NOT NULL DEFAULT 0,
    bad_models      TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_keys_provider ON keys(provider);
"""


@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    """One connection per call. SQLite is fast enough that pooling
    is premature optimization here."""
    path = settings().data_dir / "keys.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _row_to_key(row: sqlite3.Row) -> Key:
    return Key(
        id=row["id"],
        provider=row["provider"],
        key=row["key"],
        model=row["model"],
        models=json.loads(row["models"] or "[]"),
        account=row["account"],
        nickname=row["nickname"],
        enabled=bool(row["enabled"]),
        wins=row["wins"],
        fails=row["fails"],
        created_at=row["created_at"],
        resting_until=row["resting_until"],
        bad_models=json.loads(row["bad_models"] or "[]"),
    )


def _key_to_row(k: Key) -> tuple:
    return (
        k.id, k.provider, k.key, k.model,
        json.dumps(k.models), k.account, k.nickname,
        1 if k.enabled else 0, k.wins, k.fails,
        k.created_at, k.resting_until,
        json.dumps(k.bad_models),
    )


# ── public API ────────────────────────────────────────────────────────

def load_keys() -> list[Key]:
    """Every stored key, in insertion order."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM keys ORDER BY created_at ASC"
        ).fetchall()
    return [_row_to_key(r) for r in rows]


def save_key(k: Key) -> None:
    """Insert or update one key."""
    with _db() as conn:
        conn.execute(
            """
            INSERT INTO keys (id, provider, key, model, models, account,
                              nickname, enabled, wins, fails, created_at,
                              resting_until, bad_models)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                provider=excluded.provider,
                key=excluded.key,
                model=excluded.model,
                models=excluded.models,
                account=excluded.account,
                nickname=excluded.nickname,
                enabled=excluded.enabled,
                wins=excluded.wins,
                fails=excluded.fails,
                resting_until=excluded.resting_until,
                bad_models=excluded.bad_models
            """,
            _key_to_row(k),
        )


def new_key_id() -> str:
    return "k" + uuid.uuid4().hex[:12]


# ── adding ────────────────────────────────────────────────────────────

@dataclass
class AddResult:
    ok: bool
    why: str = ""
    nickname: str = ""
    provider: str = ""
    company: str = ""
    model: str = ""
    for_company: int = 0
    room_left: int = 0
    count: int = 0
    at_cap: bool = False


def add_key(
    nickname: str,
    raw_key: str,
    provider_id: str = "",
) -> AddResult:
    """Add one key.

    Detects the provider from the prefix if not given. Validates the
    key by asking the provider for its model list — a key that
    cannot list models cannot be used, and it is better to fail here
    than three calls later.

    Enforces the per-company limit (7). This is a soft rule, chosen
    because beyond seven keys the rotation stops helping and starts
    hiding which one is broken.
    """
    raw = str(raw_key or "").strip()
    if not raw:
        return AddResult(ok=False, why="That was empty — paste the key itself.")

    # Cloudflare is the only provider that needs account:key
    must_split = bool(
        provider_id
        and provider_id in BOOK
        and BOOK[provider_id].needs_account
    )
    account, clean = ("", raw)
    if must_split:
        account, clean = split_account_key(raw, force=True)
        if not account or not clean:
            return AddResult(
                ok=False,
                why=(
                    f"{BOOK[provider_id].label} needs your account id too. "
                    f"Paste it as  accountid:token"
                ),
            )
    else:
        maybe_account, maybe_clean = split_account_key(raw, force=False)
        if maybe_account and not detect_provider(raw):
            account, clean = maybe_account, maybe_clean

    pid = provider_id or detect_provider(clean)
    if not pid:
        return AddResult(
            ok=False,
            why=(
                "I do not recognise that key from its prefix. "
                "Pick the company from the list, or add one from "
                "aistudio.google.com, console.groq.com, or "
                "cloud.cerebras.ai — those three cover most needs."
            ),
        )
    if pid not in BOOK:
        return AddResult(ok=False, why=f"I do not know a company called {pid!r}.")

    provider = BOOK[pid]

    if provider.needs_account and not account:
        return AddResult(
            ok=False,
            why=(
                f"{provider.label} needs your account id too. "
                f"Paste it as  accountid:token"
            ),
        )

    # Duplicate?
    existing = load_keys()
    for k in existing:
        if k.key == clean:
            return AddResult(
                ok=False,
                why=f"You already added that key ({k.label}).",
            )

    # Room for another?
    same_company = [k for k in existing if k.provider == pid]
    if len(same_company) >= KEYS_PER_COMPANY:
        return AddResult(
            ok=False,
            why=(
                f"You already have {len(same_company)} keys for "
                f"{provider.label}, which is the most I will juggle. "
                f"Beyond {KEYS_PER_COMPANY} the rotation stops helping "
                f"and starts hiding which one is actually broken. "
                f"Remove one first, or add a key from a different company."
            ),
            at_cap=True,
        )

    k = Key(
        id=new_key_id(),
        provider=pid,
        key=clean,
        account=account,
        nickname=nickname.strip() or f"{provider.label} {len(same_company) + 1}",
    )

    # Validate: ask the provider for its model list.
    models, model, why = discover_model_for_key(k)
    if not model:
        return AddResult(
            ok=False,
            why=why or f"{provider.label} offered no usable chat model.",
        )
    k.model = model
    k.models = models[:MODELS_KEPT]

    save_key(k)
    return AddResult(
        ok=True,
        nickname=k.nickname,
        provider=pid,
        company=provider.label,
        model=model,
        for_company=len(same_company) + 1,
        room_left=KEYS_PER_COMPANY - len(same_company) - 1,
        count=len(existing) + 1,
    )


def add_many(pasted: str) -> AddResult:
    """Add several keys from one paste.

    Splits on whitespace and newlines. Skips anything that does not
    look like a key (too short, has spaces, is obviously a URL).
    Adds each one and reports how many landed.
    """
    import re

    text = str(pasted or "")
    if not text.strip():
        return AddResult(ok=False, why="Paste something first.")

    candidates: list[str] = []
    seen: set[str] = set()
    for chunk in re.split(r"[\s,;]+", text):
        token = chunk.strip().strip("\"'<>")
        if len(token) < 16:
            continue
        if token.startswith(("http://", "https://")):
            continue
        if "@" in token and ":" not in token:
            continue
        if token in seen:
            continue
        seen.add(token)
        candidates.append(token)

    if not candidates:
        return AddResult(
            ok=False,
            why=(
                "I could not see anything key-shaped in that. "
                "Keys are long strings with no spaces."
            ),
        )

    added: list[str] = []
    failed: list[str] = []
    for token in candidates[:25]:
        result = add_key("", token, "")
        if result.ok:
            added.append(result.nickname)
        elif "already" in result.why.lower():
            continue
        else:
            failed.append(f"{token[:8]}… — {result.why}")

    if not added:
        return AddResult(
            ok=False,
            why="Nothing could be added.\n" + "\n".join(failed[:5]),
        )
    return AddResult(
        ok=True,
        nickname=f"{len(added)} added",
        count=len(load_keys()),
        why=(
            f"Added {len(added)}."
            + (f" Could not add {len(failed)}." if failed else "")
        ),
    )


# ── removal / toggling ────────────────────────────────────────────────

def remove_key(key_id: str) -> Key | None:
    """Remove one key. Returns the removed Key, or None.

    The caller is expected to have kept a copy for the bin.
    """
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM keys WHERE id = ?", (key_id,)
        ).fetchone()
        if not row:
            return None
        removed = _row_to_key(row)
        conn.execute("DELETE FROM keys WHERE id = ?", (key_id,))
    return removed


def toggle_key(key_id: str) -> bool:
    """Flip the enabled flag. Returns the new state, or False if missing."""
    with _db() as conn:
        row = conn.execute(
            "SELECT enabled FROM keys WHERE id = ?", (key_id,)
        ).fetchone()
        if not row:
            return False
        new_state = 0 if row["enabled"] else 1
        conn.execute(
            "UPDATE keys SET enabled = ? WHERE id = ?",
            (new_state, key_id),
        )
    return bool(new_state)


def set_key_model(key_id: str, model: str) -> bool:
    with _db() as conn:
        cur = conn.execute(
            "UPDATE keys SET model = ? WHERE id = ?",
            (str(model).strip(), key_id),
        )
    return cur.rowcount > 0


def key_by_id(key_id: str) -> Key | None:
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM keys WHERE id = ?", (key_id,)
        ).fetchone()
    return _row_to_key(row) if row else None


# ── rotation and resting ──────────────────────────────────────────────

KEYS_PER_COMPANY = 7
MODELS_KEPT = 12
REST_SECONDS_DEFAULT = 65
REST_SECONDS_TEMPORARY = 60


def is_resting(key_id: str) -> bool:
    with _db() as conn:
        row = conn.execute(
            "SELECT resting_until FROM keys WHERE id = ?", (key_id,)
        ).fetchone()
    return bool(row and row["resting_until"] > time.time())


def rest_key(key_id: str, seconds: int = REST_SECONDS_DEFAULT) -> None:
    until = time.time() + max(1, int(seconds))
    with _db() as conn:
        conn.execute(
            "UPDATE keys SET resting_until = ? WHERE id = ?",
            (until, key_id),
        )


def keys_for(provider_id: str) -> list[Key]:
    """Every enabled key for one provider, resting ones last.

    Rotation is round-robin across the non-resting ones, so the load
    spreads. This is the same behaviour as the original's `keysFor`.
    """
    keys = [
        k for k in load_keys()
        if k.provider == provider_id and k.enabled
    ]
    if not keys:
        return []
    rested = [k for k in keys if not k.resting]
    resting = [k for k in keys if k.resting]
    if len(rested) > 1:
        # Rotate by shuffling — cheap and good enough for evenness.
        import random
        random.shuffle(rested)
    return rested + resting


# ── model discovery ───────────────────────────────────────────────────

# Words that appear in model names we can definitely use.
_GOOD_HINTS = (
    "instruct", "chat", "versatile", "flash", "turbo", "oss",
    "small", "mini",
)

# Words that mean the model does something else.
_BAD_WORDS = (
    "whisper", "embed", "tts", "audio", "rerank", "guard",
    "moderation", "image", "vision", "video", "dall", "stable",
    "flux", "safety", "bge", "clip", "ocr", "transcribe",
)

NEVER = -1000


def score_model(model_id: str, meta: dict[str, Any] | None = None) -> int:
    """Rank a model. Higher is better. NEVER means unusable.

    Ported from Code.gs scoreModel. The scoring weights are the same
    because they were tuned against real model lists.
    """
    m = model_id.lower()
    s = 0
    for word in _BAD_WORDS:
        if word in m:
            return NEVER
    if meta:
        if meta.get("free") is True:
            s += 60
        if meta.get("free") is False:
            s -= 45
        if meta.get("declared") is True:
            s += 25
    if ":free" in m:
        s += 40
    if "free" in m:
        s += 20
    for hint in _GOOD_HINTS:
        if hint in m:
            s += 6
    if "llama" in m:
        s += 12
    if "gpt-oss" in m:
        s += 12
    if "qwen" in m:
        s += 8
    if "mistral" in m:
        s += 8
    if "gemma" in m:
        s += 6
    if "flash-lite" in m:
        s += 14
    if "2.5" in m:
        s += 6
    if "3.3" in m:
        s += 6
    if "preview" in m:
        s -= 8
    if len(m) > 60:
        s -= 5
    return s


def pick_best_model(
    ids: list[str],
    exclude: list[str] | None = None,
    meta: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Pick the best model from a list, skipping excluded ones."""
    skip = set(exclude or [])
    best = ""
    best_score = NEVER
    for model_id in ids:
        if model_id in skip:
            continue
        s = score_model(model_id, (meta or {}).get(model_id))
        if s <= NEVER:
            continue
        if s > best_score:
            best_score = s
            best = model_id
    return best


def mark_bad_model(key_id: str, model: str) -> None:
    """Remember that a model does not work on this key."""
    if not model:
        return
    with _db() as conn:
        row = conn.execute(
            "SELECT bad_models FROM keys WHERE id = ?", (key_id,)
        ).fetchone()
        if not row:
            return
        bad = json.loads(row["bad_models"] or "[]")
        if model not in bad:
            bad.append(model)
        bad = bad[-25:]
        conn.execute(
            "UPDATE keys SET bad_models = ? WHERE id = ?",
            (json.dumps(bad), key_id),
        )


def bad_models_for(key_id: str) -> list[str]:
    with _db() as conn:
        row = conn.execute(
            "SELECT bad_models FROM keys WHERE id = ?", (key_id,)
        ).fetchone()
    return json.loads(row["bad_models"] or "[]") if row else []


def clear_bad_models(key_id: str) -> None:
    with _db() as conn:
        conn.execute(
            "UPDATE keys SET bad_models = '[]' WHERE id = ?", (key_id,)
        )


def discover_model_for_key(key: Key) -> tuple[list[str], str, str]:
    """Ask the provider which models this key can reach.

    Returns (all_models, best_model, why_if_failed).

    Called at add time to validate the key, and after a stale model
    is detected to pick a new one.
    """
    # Local import to avoid a circular dependency: http module will
    # eventually need keys for retry logic.
    from toolkit.brain.http import fetch_model_list

    result = fetch_model_list(key)
    if not result.get("ok"):
        return [], "", result.get("why") or "The provider would not list models."

    ids = result.get("models") or []
    meta = result.get("meta") or {}
    if not ids:
        return [], "", "The provider listed no chat models for that key."

    excluded = bad_models_for(key.id)
    best = pick_best_model(ids, excluded, meta)
    if not best:
        return ids, "", "The provider listed models but none looked usable."
    return ids, best, ""


# ── self-healing ──────────────────────────────────────────────────────

@dataclass
class HealReport:
    nickname: str
    ok: bool
    note: str


def heal_all_keys() -> list[HealReport]:
    """Clear bad models, re-discover, and test every key.

    This is the "Repair my models" button. It gives every key a fresh
    chance — useful after a provider adds models, or after a service
    outage has polluted the bad_models lists.
    """
    reports: list[HealReport] = []
    keys = load_keys()

    for k in keys:
        clear_bad_models(k.id)
        if k.provider not in BOOK:
            reports.append(HealReport(
                nickname=k.label, ok=False,
                note=f"Unknown company: {k.provider}",
            ))
            continue

        models, model, why = discover_model_for_key(k)
        if not model:
            reports.append(HealReport(
                nickname=k.label, ok=False,
                note=why or "No usable model.",
            ))
            continue

        k.model = model
        k.models = models[:MODELS_KEPT]
        save_key(k)

        # Probe — do not just trust the model list.
        from toolkit.brain.http import probe_key
        probe = probe_key(k)
        if probe["ok"]:
            reports.append(HealReport(
                nickname=k.label, ok=True,
                note=(
                    f"working on {probe.get('model') or model} "
                    f"({len(models)} available)"
                ),
            ))
        else:
            reports.append(HealReport(
                nickname=k.label, ok=False,
                note=probe.get("why", "unknown error"),
            ))

    return reports


# ── reporting ─────────────────────────────────────────────────────────

def key_pool() -> str:
    """A company-by-company breakdown, for the Setup panel."""
    keys = load_keys()
    if not keys:
        return "You have no keys yet."

    by: dict[str, list[Key]] = {}
    for k in keys:
        by.setdefault(k.provider, []).append(k)

    lines = []
    for pid, group in sorted(by.items(), key=lambda x: -len(x[1])):
        provider = BOOK.get(pid)
        label = provider.label if provider else pid
        ready = sum(1 for k in group if not k.resting and k.enabled)
        resting = sum(1 for k in group if k.resting)
        off = sum(1 for k in group if not k.enabled)
        bits = [f"{len(group)} key{'s' if len(group) != 1 else ''}"]
        if ready:
            bits.append(f"{ready} ready")
        if resting:
            bits.append(f"{resting} resting")
        if off:
            bits.append(f"{off} off")
        full = " (full)" if len(group) >= KEYS_PER_COMPANY else ""
        lines.append(f"{label} — {', '.join(bits)}{full}")

    # The Gemini advice from the original, still true.
    gemini = by.get("gemini", [])
    if not gemini:
        lines.append("")
        lines.append(
            "You have no Google Gemini key. That is the only one that "
            "draws pictures, reads voice notes and searches by meaning "
            "— and it is free from aistudio.google.com."
        )
    elif len(gemini) < 3:
        lines.append("")
        lines.append(
            f"You have {len(gemini)} Gemini key"
            f"{'s' if len(gemini) != 1 else ''}. Gemini does the "
            f"picture, voice and meaning work, so it hits its limit "
            f"first — another one from a different Google account "
            f"would spread that. Up to {KEYS_PER_COMPANY} each."
        )

    return "\n".join(lines)


def key_report() -> dict[str, Any]:
    """A verdict-shaped summary of every key."""
    keys = load_keys()
    working, broken, no_credit, off = [], [], [], []

    for k in keys:
        if not k.enabled:
            off.append(k.label)
        elif k.wins and not k.fails:
            working.append(k.label)
        elif k.fails and not k.wins:
            broken.append(k.label)
        elif k.wins:
            working.append(k.label)
        else:
            working.append(k.label)  # never used — assume fine

    if not keys:
        verdict = "No keys yet. Add one."
    elif len(working) >= 2:
        verdict = f"You are in good shape — {len(working)} keys working."
    elif len(working) == 1:
        verdict = (
            "One key working. That is enough, but add a second so it "
            "can fail over."
        )
    else:
        verdict = "Nothing is working. Add a free Gemini or Groq key."

    return {
        "ok": True,
        "verdict": verdict,
        "working": len(working),
        "broken": len(broken),
        "nocredit": len(no_credit),
        "off": len(off),
        "notes": [
            n for n in (
                f"{len(no_credit)} out of credit: {', '.join(no_credit)}"
                if no_credit else "",
                f"{len(broken)} with a real problem: {', '.join(broken)}"
                if broken else "",
                f"{len(off)} switched off."
                if off else "",
            ) if n
        ],
    }