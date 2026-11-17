# Toolkit — Resume Notes

*Last updated: 2026-11-17. State: 233 tests passing, Path C complete.*

## What this is

A portable AI assistant for tabular data, mail, and calendar. Originally
a Google Apps Script toolkit (Code.gs + Drawer.html, ~10,000 lines); now
a Python port with a pure brain, pluggable adapters, and a CLI.

The guiding principle: **the brain stays pure. Every I/O concern lives
in an adapter. Every adapter is proved against the same tests.**

Current working commands:

    toolkit ask "how many orders do we have"           # sheets, direct matcher
    toolkit ask "what's in my inbox"                   # mail, direct matcher
    toolkit ask "what's in my calendar for tomorrow"   # calendar, direct matcher
    toolkit ask "book a meeting called Sync for tomorrow at 3pm for 2 hours"
    toolkit ask "search my emails for invoice"
    toolkit ask "archive email <thread-id>"
    toolkit ask "among my unread emails, which should I prioritize"  # falls to LLM

## Architecture

    src/toolkit/
    ├── brain/                  Pure logic. No I/O. Fully tested.
    │   ├── parsing.py          Numbers, dates, string comparison
    │   ├── analysis.py         Outliers, groups, trends, shifts
    │   ├── verify.py           Hallucination guards
    │   ├── providers.py        28 AI companies, prefix detection, URL building
    │   ├── keys.py             SQLite key store, rotation, healing
    │   ├── http.py             call_ai + run_sync helper
    │   ├── auth.py             Google OAuth (load, refresh, consent)
    │   ├── results.py          AuthResult
    │   ├── agent.py            The 8-step JSON-only tool loop
    │   ├── domain.py           Configurable vocabulary profiles
    │   └── presentation.py     Human-readable output for tool results
    │
    ├── adapters/
    │   ├── base.py             SheetAdapter / MailAdapter / CalendarAdapter protocols
    │   ├── registry.py         Picks the adapter from settings; @lru_cache'd
    │   ├── sheets/
    │   │   ├── csv_folder.py   Reference adapter
    │   │   └── sqlite.py       Proves portability
    │   ├── mail/
    │   │   ├── fake.py         In-memory, proves the protocol
    │   │   └── gmail.py        Real Gmail API (google-api-python-client)
    │   └── calendar/
    │       ├── fake.py         In-memory
    │       └── google.py       Real Google Calendar API + Meet links
    │
    ├── tools/
    │   ├── registry.py         Tool dataclass, MATCHERS, run_direct, ToolResult
    │   ├── data.py             10 reading tools
    │   ├── write.py            7 writing tools
    │   ├── mail.py             4 mail tools
    │   └── calendar.py         2 calendar tools
    │
    ├── config.py               Pydantic settings
    └── __main__.py             The CLI (typer + rich)

## The five patterns that make this work

### 1. Direct matchers first, model second

Every question hits `registry.run_direct()` before the model. A regex
match means sub-second, no API key, deterministic answer. The model is
a fallback for phrasing the matchers don't anticipate.

Rules for matchers:
- **Order matters.** Specific before general. "Book a meeting" beats
  "add". Mail matchers beat data matchers, because "what's in my inbox"
  looks like "what is in [sheet]".
- **Conservative.** A wrong match is worse than no match. Use
  `soft=True` when the matcher is guessing at args; it falls through to
  the model rather than refusing.
- **Validate on first use.** `_validate_matchers()` catches typos in
  tool names at startup, not three steps later.

### 2. `ToolResult` for action tools

Read-only tools return a plain string. Prose. `tool_said_no()` classifies
it by opening words — "I could not…", "There is no…" — and that works
because a read tool's refusal *is* a failure.

Action tools (send, draft, archive, book) return `ToolResult(ok, prose)`.
Why: `send_email` can return "Sent to Ann. I could not write the cc
header." — honest prose that `tool_said_no()` reads as failure. Without
`ToolResult`, the agent loop retries and sends a duplicate. With it, the
loop believes the tool. **This is the single most important pattern in
the port.** Do not add action tools that return bare strings.

### 3. `run_sync` for calling async from sync

`keys.add_key()` is sync. `fetch_model_list()` is async. The chain
`add_key → discover_model_for_key → fetch_model_list → asyncio.run()`
breaks if you call it from inside a running loop (Jupyter, future async
OAuth callbacks, pytest-asyncio).

`http.run_sync(coro)` handles both cases: `asyncio.run()` if no loop is
running, `nest_asyncio.apply(loop)` + `loop.run_until_complete()` if one
is. **Use it everywhere you need to call async from sync.** Do not
reintroduce `asyncio.run()` outside `http.py`.

### 4. Local timezone for user-facing times

`datetime.now(timezone.utc)` is correct for logs and API tokens. It is
*wrong* for "book a meeting at 3pm" — the user means 3pm where they are.

Rule: **user-facing times use `tzlocal()`**. Google Calendar will
convert to display timezone; the API will accept an offset. But the
*parsing* of "tomorrow at 3pm" must be in local time.

Also: strip `minute`, `second`, `microsecond` from `now` before passing
it to `dateutil.parser.parse(default=now)`. Otherwise "6pm" becomes
"18:04" because the minutes come from the current clock. This bug bit
us once; it will bite again if you forget.

### 5. Cache invalidation: `@lru_cache` + `reset()`

Adapters are built via `@lru_cache(maxsize=1)` functions in
`registry.py`. Tests call `registry.reset()` to clear them between
runs. If you add a new adapter, add it to `reset()` or the test suite
will leak state across tests.

**When patching an adapter in a test, patch the *name the tool uses*,
not the registry.** If `mail_tools.py` does `from toolkit.adapters.registry
import mail`, then `monkeypatch.setattr(mail_tools, "mail", lambda: fake)`
is correct. Patching `registry.mail` does nothing.

## Adding a new adapter (the pattern)

Do it in this order, always:

1. **The fake.** `adapters/<kind>/fake.py`. In-memory, satisfies the
   protocol from `base.py`. Proves the interface before the real one.
2. **The fake's tests.** Every method has a test. The fake is the
   reference behaviour.
3. **The real adapter.** `adapters/<kind>/<backend>.py`. Uses whatever
   auth and client library the backend needs. Maps its JSON into the
   dataclasses from `base.py`.
4. **Register it.** Add a `@lru_cache` function to `registry.py`. Add
   it to `reset()`.
5. **The tools.** `tools/<kind>.py`. Read tools return strings. Action
   tools return `ToolResult`.
6. **The matchers.** Add to `MATCHERS` with `soft=True` if the args
   are guessed. **Order them above the data matchers.**
7. **Matcher tests.** Every matcher has one. Assert both the tool
   chosen and the args extracted.

Do not skip step 1. The fake is what lets you write Session 3's tools
in an afternoon without ever calling the real API.

## Adding a new tool

1. Write the test first. Watch it fail with `ModuleNotFoundError`.
2. Write the function. Return a string (read) or `ToolResult` (action).
3. `register(Tool(name=..., what=..., need=..., run=...))`.
4. If it needs a matcher, add to `MATCHERS` with a test.
5. Run `pytest tests/unit -v`. Watch the count go up by 1 or 2.
6. Commit. One coherent increment.

## Known technical debt

From the original handoff document, still accurate:

| Item | Effort | Notes |
|---|---|---|
| `_find_tab` over-greedy on "in January based on Q1 Dataset" | 30m | Add `based`, `across`, `within` to the stop list in the fallback regex |
| No `average_by` compositional tool | 1h | `compare_groups` with a value and a how |
| No `sample_rows` tool | 30m | "show me the first few rows" falls to model |
| Outliers run on identifier columns | 1h | `_guess_numeric_column` picks `Order ID` on Q1 Dataset |
| No web tools (weather, exchange, news) | 2h | Separate scope, lower value |
| `-v` mushes multiline tool output | 30m | Cosmetic; `presentation.py` line-wrapping |

New since the port:

| Item | Effort | Notes |
|---|---|---|
| Conversation turns not wired | 2–3h | `call_ai_async(turns=...)` works; `run_agent` never passes |
| `book_meeting` matcher still over-eager on complex phrasing | 30m | Duration detection is regex-based; LLM fallback works but is slow |
| No `calendar.invite` tool | 30m | The adapter method exists; no tool wraps it |

## What NOT to do yet

- **Do not build the presentation layer** (FastAPI/React equivalent of
  Drawer.html) until the CLI has been used for a week. The CLI is the
  proving ground. Note what you reach for that isn't there; build the
  panel that provides exactly that.
- **Do not fix the technical debt table above before the conversation
  loop.** The conversation loop is the feature the original had that
  the port lacks. Everything else is polish.
- **Do not add tools that return bare strings if they mutate state.**
  See pattern 2.

## Commit log milestones

    (older — pre-port, Paths A through E)
    5ff2fe0  presentation layer, CLI --verbose, tab/column resolution
    ...
    22       run_sync — kills the asyncio.run loop landmine
    23       count_distinct / count_orders_like soft=True
    24       ToolResult — action tools say ok/not-ok
    25       auth.py — Google OAuth handshake and token storage
    26       fake mail adapter proves the interface
    27       real Gmail adapter — search, read, send, draft
    28       mail tools (read, search, send, archive)
    30       mail matchers, describe/archive fixes
    32       calendar adapters, tools, matchers
    33       calendar: natural language time parsing
    34       calendar: parse durations in matcher
    35       calendar: local timezone, strip seconds

## Environment

- Path: `C:\Users\HP\Desktop\Toolkit`
- Python: 3.12.10, venv at `.venv`
- OS: Windows (PowerShell 5.1)
- Deps: `httpx`, `pydantic`, `pydantic-settings`, `structlog`, `typer`,
  `rich`, `polars`, `nest-asyncio`, `google-api-python-client`,
  `google-auth-oauthlib`, `google-auth-httplib2`, `python-dateutil`
- Keys: `data/keys.db` (SQLite). Active: Google Gemini.
- Google auth: `data/credentials.json` (OAuth client, gitignored) and
  `data/token.json` (user token, gitignored, expires weekly in Testing
  mode — re-run `python -c "from toolkit.brain.auth import get_credentials;
  get_credentials()"` to refresh)
- Sample data: `data/csv/Q1 Dataset.csv` (9,800 rows, 18 columns, Kenyan
  retail/sales dataset)

## Commands to resume

    cd C:\Users\HP\Desktop\Toolkit
    .\.venv\Scripts\Activate.ps1
    pytest tests/unit -v          # should show 233 passed
    toolkit ask "how many orders do we have"
    toolkit ask "what's in my inbox"

## The meta-lesson

Twenty-plus sessions. Every one green. Every one committed. Every one
coherent. The pattern that made this work:

1. Write the test.
2. Watch it fail with a specific error.
3. Write the minimum code to pass.
4. Run the full suite.
5. Commit.
6. Move on.

Do not batch. Do not "fix everything then commit once." Do not skip the
test-first step because you are sure the code is right.

The original was nineteen months of organic growth. The port is
deliberate construction. The difference is visible in the git log.