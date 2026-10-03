# Toolkit Project Notes

## Overview
This project is a Python toolkit for working with spreadsheet data, running structured analysis, and connecting to AI providers through a thin tool layer. The design is intentionally split between pure reasoning code and I/O-heavy adapters.

---

## 1) Project Skeleton

| File | Purpose |
| --- | --- |
| `pyproject.toml` | Single source of truth for dependencies, packaging, and the CLI entry point. |
| `pytest.ini` | Test discovery, async setup, and custom markers such as `live` and `slow`. |
| `ruff.toml` | Linting and formatting configuration with a 100-character line length and modern Python defaults. |
| `.gitignore` | Excludes caches, virtual environments, local env files, and generated DB artifacts. |
| `.python-version` | Pins Python 3.12.10 for pyenv users. |
| `.env.example` / `.env` | Environment template and the actual local config (gitignored). |
| `.vscode/settings.json` | Strict type checking, Ruff on save, and `src/` added to Python path resolution. |
| `.vscode/launch.json` | Debug configs for pytest, CLI usage, and future server work. |
| `.vscode/tasks.json` | Convenience tasks for test, lint, and dev flows. |
| `.vscode/extensions.json` | Recommended editor extensions for Python, linting, and DB tooling. |

---

## 2) The Brain

The brain is the reasoning layer. It operates on normalized data structures and does not perform direct file, HTTP, or Google I/O.

| File | Summary |
| --- | --- |
| `src/toolkit/brain/parsing.py` | Extracts numbers and dates from messy spreadsheet values such as `KSh 2,000`, `(45)`, `1.5k`, and ambiguous day-first/month-first dates while preserving the quirks from the original logic. |
| `src/toolkit/brain/analysis.py` | Pure statistical logic for IQR outliers, grouping, trend direction, concentration checks, and recent-shift detection on `TabData`. |
| `src/toolkit/brain/verify.py` | Hallucination protection: checks invented numbers/figures, spots fabricated entities, rejects non-answers, and chooses the most defensible response when multiple outputs are possible. |
| `src/toolkit/brain/providers.py` | Registry of 28 AI providers with URLs, prefixes, request formats, and provider-specific request/reply handling. |
| `src/toolkit/brain/keys.py` | SQLite-backed key storage with rotation, self-healing, model discovery, and per-company limits. |
| `src/toolkit/brain/http.py` | Shared HTTP utilities for model listing, key probing, and AI calls with graceful fallback between providers. |
| `src/toolkit/brain/agent.py` | Main 8-step reasoning loop: direct matchers, structured model call, tool execution, feedback loop, and final verification before returning a result. |

---

## 3) Adapters

Adapters isolate external systems from the brain. The brain stays ignorant of where data comes from.

| File | Summary |
| --- | --- |
| `src/toolkit/adapters/base.py` | Core interfaces for `TabData`, selection objects, and adapter protocols such as `SheetAdapter`, `MailAdapter`, and `CalendarAdapter`. |
| `src/toolkit/adapters/registry.py` | Chooses the active adapter, caches it, and supports test resets. |
| `src/toolkit/adapters/sheets/csv_folder.py` | Reference adapter for a folder of CSV files. Handles atomic writes, safe tab naming, and normalization of null cells to empty strings. |

---

## 4) Tools

The tool layer provides direct operations that can be triggered by regex matching or by the model when needed.

| File | Summary |
| --- | --- |
| `src/toolkit/tools/registry.py` | Defines the `Tool` dataclass, loads tools, runs direct matchers, and detects when a tool has refused to answer. |
| `src/toolkit/tools/data.py` | First set of tools: `describe_sheet`, `count_rows`, `count_rows_in`, `compare_groups`, `find_outliers`, and `trend_over`. |

---

## 5) Config and CLI

| File | Summary |
| --- | --- |
| `src/toolkit/config.py` | Pydantic-based settings loaded from environment and `.env` with sensible defaults. |
| `src/toolkit/__main__.py` | CLI entry point covering `toolkit ask`, `toolkit keys {list,add,pool,remove,toggle}`, `toolkit tools {list,run}`, `toolkit version`, and a placeholder server command. |

---

## 6) Tests

| File | Tests | What it verifies |
| --- | ---: | --- |
| `tests/unit/test_parsing.py` | 32 | Edge cases in number and date parsing from messy spreadsheet values. |
| `tests/unit/test_analysis.py` | 15 | Outliers, groups, trends, concentration, and shift detection. |
| `tests/unit/test_verify.py` | 23 | Hallucination guard behavior, including false claims and fabricated entities. |
| `tests/unit/test_csv_adapter.py` | 20 | CSV contract: atomic writes, empty-string normalization, and path traversal rejection. |
| `tests/unit/test_tools.py` | 18 | Tool execution, direct matcher behavior, and refusal detection. |
| `tests/unit/test_keys.py` | 27 | Provider detection, request building, key storage, model scoring, and reply parsing. |

---

## 7) What Works Right Now

### Commands
```powershell
# Describe the data (no model, no key needed)
python -m toolkit ask "what can you see in my sheet?"

# Count and group (still no model)
python -m toolkit ask "how many rows are there?"
python -m toolkit ask "count the rows by Region"

# Manage keys
python -m toolkit keys list
python -m toolkit keys add gsk_...
python -m toolkit keys pool

# Run any tool directly
python -m toolkit tools list
python -m toolkit tools run compare_groups -a tab=Sales -a column=Region
```

### Verified
- Describe-sheet flow
- Row counting and grouping
- Key storage and key rotation logic
- Model discovery and provider prefix detection
- Honest failure handling
- Direct matchers that bypass the model entirely

### Known issue this session
The async/sync mismatch in `call_ai` is the main bug identified in this pass. The fix is linked to an `nest_asyncio.apply()` issue and related dependency setup inside the CLI layer; once corrected, model calls should work consistently.

---

## 8) Commit History

```text
980b34b  brain: keys.py + http.py — key store, rotation, model discovery
53cff29  brain: providers.py — 28 AI companies, detect, build_request, read_reply
80b856c  tools: describe_sheet reads the whole tab for an exact count
51650eb  adapters: csv_folder normalises null cells to empty strings
0584129  brain: verify.py — the hallucination guards
b7bb9d6  brain: analysis.py (outliers, groups, trends) + adapters/base.py
47a0f35  brain: parsing.py ported, canary green (32 passed)
```

A CLI-focused commit is still pending.

---

## 9) What Is Still Missing

| Area | Remaining work |
| --- | --- |
| Other sheet adapters | SQLite, Postgres, Excel, and Google Sheets implementations as variants of the CSV adapter pattern. |
| Mail adapter | Gmail integration and a fake adapter for tests. |
| Calendar adapter | Google Calendar support and a fake implementation. |
| Telegram | Polling loop and message interface once adapters exist. |
| HTTP server | FastAPI endpoints matching `google.script.run` behavior, plus WebSocket graph updates. |
| The Drawer | HTML/CSS/JS port, shim layer, and RPC wiring. |
| More tools | Remaining tool groups from the original app, likely one file per logical group such as `clean.py`, `think.py`, `make.py`, `mail.py`, `calendar.py`, `contacts.py`, `media.py`, `keys_tools.py`, and `admin.py`. |
| Domain profiles | `config/domain.json` and preset dictionaries to replace hardcoded branch/urgency/channel vocabulary. |

None of these are hard. Each is a small, isolated addition, and the pattern has already been established.

---

## 10) Core Design Rules

### Rule 1: The brain stays pure
Nothing in `brain/` performs file reads, makes HTTP calls, or talks to Google. Anything that does I/O belongs in `adapters/` or `tools/`.

### Rule 2: The adapter normalizes, the brain reasons
- Empty cells are normalized to `""`, never `None`.
- Dates remain strings until `read_date` interprets them.
- Numbers remain strings until `read_number` interprets them.

This normalization discipline keeps the reasoning layer stable and makes future adapters easier to plug in safely.

---

## 11) Summary

The project already has a solid foundation: a clean separation between reasoning logic, adapters, and tool execution; strong unit coverage; and a clear path toward adding more integrations and features without disturbing the brain layer.
