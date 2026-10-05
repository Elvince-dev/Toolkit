"""Domain profiles — so the toolkit is not welded to one business.

The original Code.gs had hardcoded hints like "branch", "urgency",
"channel" — the vocabulary of one specific customer-complaints sheet.
This module replaces those with a configurable profile, loaded from
config/domain.json or a named preset.

The public API is one function: `domain()`. It returns a Domain
object. Code that used to say:

    if "region" in header.lower() or "branch" in header.lower():
        ...

now says:

    if domain().matches("group", header):
        ...

which means the same toolkit works on a Kenyan retail dataset, a
hospital dataset, or a research dataset — with only the config
changing.

Four presets ship:

    generic     — the safe default; works on anything
    business    — retail, sales, operations (the original tailoring)
    research    — lab data, cohorts, treatments
    financial   — market data, portfolios, prices

You can also write your own at config/domain.json, which overrides
the preset.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from toolkit.config import settings


# ── the Domain object ─────────────────────────────────────────────────

@dataclass(frozen=True)
class PhoneRules:
    """Country-specific phone handling."""

    default_country: str = ""      # e.g. "+254" for Kenya
    strip_leading_zero: bool = False


@dataclass(frozen=True)
class CurrencyRules:
    """Currency symbol and code, for messages and formatting."""

    symbol: str = ""
    code: str = ""


@dataclass(frozen=True)
class Domain:
    """A vocabulary for one kind of data."""

    name: str = "generic"
    vocabulary: dict[str, list[str]] = field(default_factory=dict)
    phone: PhoneRules = field(default_factory=PhoneRules)
    currency: CurrencyRules = field(default_factory=CurrencyRules)
    prompts: dict[str, str] = field(default_factory=dict)

    # Matching is intentionally permissive: a column header that
    # contains any of the words for a kind counts as that kind.
    def matches(self, kind: str, header: str) -> bool:
        """Does this column header look like `kind` in this domain?"""
        words = self.vocabulary.get(kind, [])
        if not words:
            return False
        low = str(header).lower()
        return any(w in low for w in words)

    def kind_of(self, header: str) -> str | None:
        """The first kind this header matches, or None.

        Priority order matters: identifier > date > measure > person >
        group. A column called "order_id" is an identifier, not a
        group, even though "order" might appear in the group list.
        """
        for kind in ("identifier", "date", "measure", "person", "group"):
            if self.matches(kind, header):
                return kind
        return None

    def words_for(self, kind: str) -> list[str]:
        return list(self.vocabulary.get(kind, []))


# ── loading ───────────────────────────────────────────────────────────

# Where presets live. Computed relative to the package root, which is
# src/toolkit/brain/domain.py → up 3 levels → project root → config/.
_HERE = Path(__file__).resolve()
_PROJECT_ROOT = _HERE.parent.parent.parent.parent
_PRESETS_DIR = _PROJECT_ROOT / "config" / "presets"


@lru_cache(maxsize=1)
def domain() -> Domain:
    """The active domain.

    Precedence:
        1. config/domain.json, if it exists (the user's own profile)
        2. config/presets/<settings.domain_preset>.json
        3. config/presets/generic.json
        4. a hardcoded fallback (so the toolkit still works if the
           config directory is missing entirely)
    """
    cfg = settings()

    # 1. Explicit file
    if cfg.domain_file and cfg.domain_file.exists():
        try:
            return _from_dict(json.loads(cfg.domain_file.read_text(encoding="utf-8")))
        except Exception:
            pass  # fall through to preset

    # 2. Project-wide override
    project_domain = _PROJECT_ROOT / "config" / "domain.json"
    if project_domain.exists():
        try:
            return _from_dict(json.loads(project_domain.read_text(encoding="utf-8")))
        except Exception:
            pass

    # 3. Named preset
    preset_path = _PRESETS_DIR / f"{cfg.domain_preset}.json"
    if preset_path.exists():
        try:
            return _from_dict(json.loads(preset_path.read_text(encoding="utf-8")))
        except Exception:
            pass

    # 4. Generic preset
    generic = _PRESETS_DIR / "generic.json"
    if generic.exists():
        try:
            return _from_dict(json.loads(generic.read_text(encoding="utf-8")))
        except Exception:
            pass

    # 5. Hardcoded fallback
    return _fallback()


def _from_dict(data: dict[str, Any]) -> Domain:
    """Build a Domain from a parsed JSON dict.

    Tolerates missing sections — a partial profile is still useful.
    """
    phone = data.get("phone") or {}
    currency = data.get("currency") or {}
    return Domain(
        name=str(data.get("name") or "custom"),
        vocabulary={
            k: [str(w).lower() for w in v]
            for k, v in (data.get("vocabulary") or {}).items()
            if isinstance(v, list)
        },
        phone=PhoneRules(
            default_country=str(phone.get("default_country") or ""),
            strip_leading_zero=bool(phone.get("strip_leading_zero")),
        ),
        currency=CurrencyRules(
            symbol=str(currency.get("symbol") or ""),
            code=str(currency.get("code") or ""),
        ),
        prompts={k: str(v) for k, v in (data.get("prompts") or {}).items()},
    )


def _fallback() -> Domain:
    """The absolute minimum, in case config/presets/ is missing.

    This is what a fresh install would fall back to if someone deleted
    the presets folder. It is deliberately small — just enough to be
    useful, not enough to be a substitute for the real presets.
    """
    return Domain(
        name="fallback",
        vocabulary={
            "identifier": ["id", "ref", "code"],
            "date": ["date", "when", "time"],
            "measure": ["amount", "count", "total", "value"],
            "person": ["name", "person", "user", "owner"],
            "group": ["type", "status", "category", "group"],
        },
    )


def reset() -> None:
    """Clear the cached domain. Tests call this when config changes."""
    domain.cache_clear()


# ── listing and setting ───────────────────────────────────────────────

def list_presets() -> list[str]:
    """Names of every preset that ships with the toolkit."""
    if not _PRESETS_DIR.exists():
        return []
    return sorted(p.stem for p in _PRESETS_DIR.glob("*.json"))


def load_preset(name: str) -> Domain:
    """Load a named preset without activating it. Useful for preview."""
    path = _PRESETS_DIR / f"{name}.json"
    if not path.exists():
        raise ValueError(
            f"No preset called {name!r}. Available: "
            f"{', '.join(list_presets())}"
        )
    return _from_dict(json.loads(path.read_text(encoding="utf-8")))


def describe(d: Domain | None = None) -> str:
    """One human paragraph about the active domain, for the CLI."""
    d = d or domain()
    bits = [f"Domain: {d.name}"]
    for kind in ("identifier", "date", "measure", "person", "group"):
        words = d.words_for(kind)
        if words:
            shown = ", ".join(words[:6])
            if len(words) > 6:
                shown += f", +{len(words) - 6} more"
            bits.append(f"  {kind}: {shown}")
    if d.phone.default_country:
        bits.append(f"  phone country: {d.phone.default_country}")
    if d.currency.symbol or d.currency.code:
        bits.append(f"  currency: {d.currency.symbol or d.currency.code}")
    return "\n".join(bits)