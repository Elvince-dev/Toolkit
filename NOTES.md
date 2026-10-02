# Toolkit — Executive Summary

## Status at a Glance

| Area | Status | Notes |
| --- | --- | --- |
| Core reasoning engine | ✅ Strong foundation | Data parsing, analysis, verification, provider abstraction, and tool routing are in place. |
| Spreadsheet operations | ✅ Working | CSV-based adapter and direct tools cover core data inspection and aggregation. |
| AI provider integration | ✅ Functional | Multi-provider key handling and request parsing are implemented. |
| Test coverage | ✅ Good coverage | Unit tests cover parsing, analysis, verification, CSV behavior, tools, and keys. |
| Production expansion | ⚠️ In progress | Mail, calendar, server, UI, and more tool groups remain to be added. |
| Execution blocker | ⚠️ One key issue | Async/sync mismatch in the AI call path still needs cleanup. |

---

## Executive Overview
This project is a Python-based toolkit for spreadsheet analysis and AI-assisted operations. It is designed around a clean separation of concerns: the reasoning layer is kept pure and deterministic, while external systems such as CSV files, keys, and AI providers are isolated behind adapters and tools.

The architecture already demonstrates the core pattern needed for a broader platform: normalize the data, reason over it, verify the result, and then expose it through structured tools or CLI entry points.

---

## What We Have Built

### 1. Core Intelligence Layer
The brain is responsible for analysis and decision-making without talking directly to files or external services.

| Module | Role |
| --- | --- |
| `src/toolkit/brain/parsing.py` | Reads messy spreadsheet values like currencies, negatives, abbreviations, and date variants. |
| `src/toolkit/brain/analysis.py` | Handles outliers, group counts, trend direction, concentration, and recent shifts. |
| `src/toolkit/brain/verify.py` | Blocks hallucinations, invented numbers, and unsupported claims before returning an answer. |
| `src/toolkit/brain/providers.py` | Encodes provider metadata for nearly 30 AI services and standardizes request/response handling. |
| `src/toolkit/brain/keys.py` | Manages provider keys with rotation, discovery, and storage logic. |
| `src/toolkit/brain/http.py` | Centralizes model-list fetches, key probing, and provider calls. |
| `src/toolkit/brain/agent.py` | Runs the decision loop that checks for direct tools before escalating to model-driven execution. |

### 2. Data Access Layer
Adapters hide the external source of data from the reasoning layer.

| Module | Role |
| --- | --- |
| `src/toolkit/adapters/base.py` | Defines core data contracts and abstraction boundaries. |
| `src/toolkit/adapters/registry.py` | Selects and caches the active adapter. |
| `src/toolkit/adapters/sheets/csv_folder.py` | Reference implementation for spreadsheet data in a folder of CSV files. |

### 3. Tooling Layer
The project exposes a structured tool interface for common actions.

| Module | Role |
| --- | --- |
| `src/toolkit/tools/registry.py` | Loads tools and resolves direct-match execution routes. |
| `src/toolkit/tools/data.py` | Contains the first set of operational tools such as counting, grouping, describing, and trend analysis. |

---

## Business Readiness

### Working today
- Spreadsheet inspection and description
- Counting rows and grouping by columns
- Simple trend and outlier analysis
- Key management and provider detection
- Direct tool execution without model dependency
- Hallucination checks and answer validation

### Not yet complete
- Mail and calendar integrations
- More adapters for databases and external sheets
- Telegram and web server integration
- Drawer/UI layer and API surface
- Expansion into the larger tool library from the original app

---

## Current Risk Profile

### Low-risk areas
- Core reasoning layer
- Parsing and analysis functions
- Adapter normalization conventions
- Tool packaging patterns

### Medium-risk / active issue
- AI request flow is still affected by an async/sync mismatch in `call_ai`
- This is a single known execution blocker and appears localized to the CLI/runtime integration layer

### Strategic note
The project is not “half-built”; it is already built around the right operating model. The remaining work is expansion and integration rather than re-architecting the core.

---

## Delivery Priorities

1. Fix the async call path so all AI-backed flows work reliably.
2. Finish the adapter expansion beyond CSV.
3. Add the remaining tool sets and domain-specific profiles.
4. Expose a server/UI layer for richer workflows.
5. Keep the brain pure and the adapters thin as the system scales.

---

## Key Design Principles

### Principle 1: Pure reasoning
The brain should not read files, fetch HTTP, or call Google APIs directly.

### Principle 2: Normalized inputs
- Empty cells become `""`
- Dates remain strings until parsed
- Numbers stay strings until parsed

### Principle 3: Verifiable output
The system is designed to catch invented values, unsupported claims, and weak reasoning before returning a result.

---

## Verified Command Examples

```powershell
# Describe the data
python -m toolkit ask "what can you see in my sheet?"

# Count and group
python -m toolkit ask "how many rows are there?"
python -m toolkit ask "count the rows by Region"

# Manage keys
python -m toolkit keys list
python -m toolkit keys add gsk_...
python -m toolkit keys pool

# Run tools directly
python -m toolkit tools list
python -m toolkit tools run compare_groups -a tab=Sales -a column=Region
```

---

## Commit Momentum

```text
980b34b  brain: keys.py + http.py — key store, rotation, model discovery
53cff29  brain: providers.py — 28 AI companies, detect, build_request, read_reply
80b856c  tools: describe_sheet reads the whole tab for an exact count
51650eb  adapters: csv_folder normalises null cells to empty strings
0584129  brain: verify.py — the hallucination guards
b7bb9d6  brain: analysis.py (outliers, groups, trends) + adapters/base.py
47a0f35  brain: parsing.py ported, canary green (32 passed)
```

This shows a strong pattern of incremental delivery: each step adds a concrete capability without destabilizing the architecture.

---

## Final Takeaway
The project has already reached a meaningful alpha-state: the core reasoning engine is robust, the tool layer is working, and the architecture is coherent enough to scale. The remaining work is mostly additive rather than foundational, which makes the path to a broader product much more manageable.
