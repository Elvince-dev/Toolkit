"""Hallucination guards.

Ported from Code.gs. These are the functions that stop the model from
inventing figures. They are not optional — they are the difference
between an AI assistant and a random number generator.

The pattern throughout:

    the agent runs some tools, gets some results
    the agent writes an answer from those results
    these functions check that answer against the raw material
    if a figure cannot be traced, the answer is marked "shaky"
    the agent loop may then ask the model to answer again
    keep_the_first decides which version wins

Everything here is pure. No I/O, no model calls, no state. A function
takes strings and dicts, and returns dataclasses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# ── Claims ─────────────────────────────────────────────────────────────

@dataclass
class ClaimCheck:
    """What could be traced, and what could not.

    checked:      how many figures and names the answer contained
    supported:    how many appeared verbatim in the source
    derived:      how many could be worked out from the source
                  (row counts, totals, lengths)
    unsupported:  figures that cannot be traced — the red flag
    unknown_names: capitalised words that are not in the source
    """

    checked: int = 0
    supported: int = 0
    derived: int = 0
    unsupported_numbers: list[str] = field(default_factory=list)
    unknown_names: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.unsupported_numbers and not self.unknown_names

    @property
    def confidence(self) -> str:
        if self.checked == 0:
            return "nothing to check"
        if self.clean:
            return "every figure checks out"
        n = len(self.unsupported_numbers) + len(self.unknown_names)
        if n == 1:
            return "one thing I could not find"
        return f"{n} things I could not find"


# Words that look like proper nouns but are not entities. Ported
# verbatim from Code.gs — every word in this list was added because
# it appeared in a real answer and was flagged as a false positive.
_COMMON_WORDS = frozenset(
    "the this that there these those it if in on at for and but so we you "
    "yes no both all most some none each every however overall based looking "
    "across given with from only one two three four five six seven eight nine "
    "ten monday tuesday wednesday thursday friday saturday sunday "
    "january february march april may june july august september october "
    "november december not nothing they their them your our its his her "
    "about after before during since here when what which who why how also "
    "then than more less best worst first last branch branches row rows "
    "column columns total average count data sheet tab summary answer note "
    "key keys model models value values result results time times day days "
    "week weeks month months year years customer customers order orders "
    "please thank thanks ok okay sure fine good great perfect note notes "
    "theirs ours yours mine hers his its their".split()
)


def check_claims(answer: str, source: str) -> ClaimCheck:
    """Find figures in the answer that do not appear in the source.

    "Source" here means whatever the model was shown — the table, the
    tool results, the pasted text. If a number in the answer cannot be
    found in the source, or derived from it, it is suspect.

    The three ways a figure can be legitimate:

      1. It appears verbatim: "4200" in the answer, "4200" in the source
      2. It equals the number of rows (or rows-1, for header handling)
      3. It equals the sum of the numbers in the source (the model
         correctly added them up)

    Anything else is unsupported. The threshold is deliberately strict:
    a false alarm shows a real message the user can act on; a missed
    failure claims work that never happened.
    """
    numbers = _numbers_in(answer)
    names = _proper_nouns(answer)

    flat = source.replace(",", "")
    src_numbers: list[float] = []
    for m in re.finditer(r"\b\d+(?:\.\d+)?\b", flat):
        try:
            src_numbers.append(float(m.group(0)))
        except ValueError:
            continue
    total = sum(src_numbers)
    line_count = len([line for line in source.splitlines() if line.strip()])

    unsupported: list[str] = []
    supported = 0
    derived = 0

    for raw, value in numbers:
        # 1. Verbatim
        if str(value) in flat or str(int(value)) in flat:
            supported += 1
            continue
        # 2. Row count
        if value == line_count or value == line_count - 1:
            derived += 1
            continue
        # 3. Count of items in the source
        if value == len(src_numbers):
            derived += 1
            continue
        # 4. Sum of the source numbers (allow 1% tolerance for rounding)
        if total and abs(value - total) < max(1.0, total * 0.01):
            derived += 1
            continue
        # 5. Small round numbers can be structural ("3 ways", "2 things")
        if value <= line_count and value == int(value) and value < 100:
            derived += 1
            continue
        unsupported.append(raw)

    lower = source.lower()
    unknown = [n for n in names if n.lower() not in lower]

    return ClaimCheck(
        checked=len(numbers) + len(names),
        supported=supported,
        derived=derived,
        unsupported_numbers=unsupported[:6],
        unknown_names=unknown[:6],
    )


def _numbers_in(text: str) -> list[tuple[str, float]]:
    """Every number in the answer, as (raw_text, float_value)."""
    out: list[tuple[str, float]] = []
    for m in re.finditer(r"\b\d[\d,]*(?:\.\d+)?\b", text):
        raw = m.group(0)
        try:
            out.append((raw, float(raw.replace(",", ""))))
        except ValueError:
            continue
    return out


def _proper_nouns(text: str) -> list[str]:
    """Capitalised words that are not common English words.

    The heuristic is deliberately narrow — only words that look like
    "Proper Noun" (initial cap, at least three letters, rest lowercase).
    All-caps like "URGENT" and CamelCase like "GetTotal" are ignored.
    """
    seen: list[str] = []
    for match in re.finditer(r"\b([A-Z][a-z]{2,})\b", text):
        w = match.group(1)
        if w.lower() in _COMMON_WORDS:
            continue
        if w not in seen:
            seen.append(w)
    return seen[:12]


# ── Invented entities ──────────────────────────────────────────────────

# Every phrase in this list was added because the model used it to
# explain a gap — and every one of them was made up. Do not remove
# entries without a very good reason; they are load-bearing.
_INVENTED_PHRASES = (
    r"pipeline",
    r"database",
    r"back\.?end",
    r"api call",
    r"webhook",
    r"etl",
    r"ingestion pipeline",
    r"enrichment pipeline",
    r"microservice",
    r"cron job",
    r"lookup table",
    r"join table",
    r"foreign key",
    r"schema mismatch",
    r"migration",
    r"version control",
    r"repository",
    r"deployment",
    r"environment variable",
    r"fill rate",
    r"data extraction",
    r"audit trail",
    r"change log",
    r"user attribution",
    r"source system",
    r"data collection script",
    r"logging error",
    r"upstream system",
)


@dataclass
class InventedReport:
    words: list[str]
    say: str


def invented_something(
    answer: str, trail: list[dict[str, Any]] | None = None
) -> InventedReport | None:
    """Did the answer describe a system that does not exist?

    The failure mode this catches: the model cannot find a real
    explanation in the data, so it invents an IT reason. "The
    pipeline probably dropped those rows" — when there is no pipeline.

    Returns None when the answer contains no invented phrases, or
    when the phrase appears in the trail (meaning a tool actually
    mentioned it, so the model was quoting reality).
    """
    text = str(answer or "")
    if not text.strip():
        return None

    # Build a corpus of everything the tools actually said.
    real = " "
    for step in trail or []:
        if not isinstance(step, dict):
            continue
        for key in ("tool", "result", "says", "saw", "table", "note"):
            value = step.get(key)
            if value:
                real += " " + str(value)[:400]
    real = real.lower()

    made: list[str] = []
    for phrase in _INVENTED_PHRASES:
        if not re.search(r"\b" + phrase + r"\b", text, re.I):
            continue
        # If the phrase is also in the trail, the model is quoting.
        cleaned = phrase.replace(r"\.?", "").replace("\\", "")
        if cleaned.lower() in real:
            continue
        made.append(cleaned)

    if not made:
        return None

    # De-duplicate while preserving order.
    seen: list[str] = []
    for w in made:
        if w not in seen:
            seen.append(w)

    head = " and a ".join(seen[:2])
    return InventedReport(
        words=seen,
        say=(
            f"\u26a0 I described a {head} just now. Your sheet has "
            f"none of those \u2014 I invented them to explain a gap. "
            f"Ignore that part: the honest answer is that the "
            f"information is not in your sheet, and I do not know why."
        ),
    )


# ── Critique ───────────────────────────────────────────────────────────

@dataclass
class CritiqueReport:
    ok: bool
    problems: list[str]
    verdict: str


def critique(
    question: str, answer: str, source: str = ""
) -> CritiqueReport:
    """Did the answer actually answer the question?

    This is not check_claims. check_claims asks "is this figure real?"
    critique asks "did you address what was asked?" — a question can be
    answered with entirely real numbers and still not be answered.

    Examples that this catches:

      "How many rows?" → "The data contains several categories..." — no number
      "Which branch is worst?" → "There are differences between branches"
                                  — no branch named
      "Why did sales drop?" → "Sales have dropped significantly" — no reason
      "Is X in the data?" → three paragraphs — no yes or no
    """
    problems: list[str] = []

    q = str(question or "")
    a = str(answer or "")

    # Figure asked for, no figure given
    if re.search(r"\bhow many\b|\bhow much\b|\bwhat (is|was) the "
                 r"(total|number|count|average)\b", q, re.I):
        if not re.search(r"\d", a):
            problems.append("asked for a figure and got none")

    # Named answer asked for, no name given
    if re.search(r"\bwhich\b|\bwho\b|\bwhat is the "
                 r"(worst|best|biggest|most|largest)\b", q, re.I):
        names = _proper_nouns(a)
        if not names and "not in the data" not in a.lower():
            problems.append("asked which one and did not name it")

    # Reason asked for, no reason given
    if re.search(r"\bwhy\b", q, re.I):
        if not re.search(r"because|due to|driven by|since|the reason|caused",
                         a, re.I) and "not in the data" not in a.lower():
            problems.append("asked why and gave no reason")

    # Yes/no asked for, essay given
    if re.search(r"\byes or no\b|^(is|are|does|do|did|can|will|should)\b",
                 q.strip(), re.I):
        if not re.match(r"^(yes|no)\b", a.strip(), re.I) and len(a) > 200:
            problems.append("a yes-or-no question got a lecture")

    # Trailing hedges so heavy the answer says nothing
    hedges = len(re.findall(
        r"\b(may|might|could|possibly|perhaps|it depends|potentially|likely)\b",
        a, re.I))
    if hedges >= 4 and len(a) < 600:
        problems.append("hedged so much it says nothing definite")

    # Optional: compare to a source for unsupported claims
    if source:
        check = check_claims(a, source)
        if check.unsupported_numbers:
            problems.append(
                "these figures are not in the data: "
                + ", ".join(check.unsupported_numbers))
        if check.unknown_names:
            problems.append(
                "these names are not in the data: "
                + ", ".join(check.unknown_names))

    if not problems:
        verdict = "answers the question"
    elif len(problems) == 1:
        verdict = "one thing off"
    else:
        verdict = f"{len(problems)} things off"

    return CritiqueReport(ok=not problems, problems=problems, verdict=verdict)


# ── Choosing between two answers ───────────────────────────────────────

def keep_the_first(first: str, second: str) -> bool:
    """When a second answer is produced, should we keep the first?

    This is a subtle heuristic and it exists because the obvious rule
    ("keep the second, it was a correction") is wrong about half the
    time. The model, asked to correct itself, often:

      * responds with "NOT IN THE DATA" when the first answer was fine
      * passes the buck with "please provide the data" instead of trying
      * gives fewer concrete figures than the first attempt

    In all those cases, the first answer was better and the second is
    a regression. This function detects them.

    Returns True to keep the first, False to accept the second.
    """
    a = str(first or "").strip()
    b = str(second or "").strip()

    if not a:
        return False   # nothing to keep
    if not b:
        return True    # second is empty, keep first

    # If the second refuses where the first was concrete, keep the first.
    refuses = len(re.findall(
        r"NOT IN THE DATA|not in the data|cannot be determined|no data available",
        b, re.I))
    if refuses:
        first_has_meat = (
            bool(re.search(r"\d", a))
            or bool(re.search(
                r"\b(column|tab|row|would need|does not contain|"
                r"shall (i|we)|would you like)\b", a, re.I))
        )
        if first_has_meat and len(a) > 60:
            return True

    # If the second passes the buck and the first does not, keep the first.
    passes_buck = (
        bool(re.search(r"\b(please )?(provide|paste|supply|share|upload|"
                       r"give me)\b", b, re.I))
        and not re.search(r"\b(provide|paste|supply|share|upload|give me)\b",
                          a, re.I)
    )
    if passes_buck:
        return True

    # If the second has more figures, it is probably a real improvement.
    a_figures = len(re.findall(r"\d[\d,.]*", a))
    b_figures = len(re.findall(r"\d[\d,.]*", b))
    if not refuses and b_figures > a_figures:
        return False

    # Default: keep the first. The second only wins when it is clearly
    # better, not merely when it exists.
    return True


# ── The one-line summary ───────────────────────────────────────────────

def say_how_sure(check: ClaimCheck) -> str:
    """Turn a ClaimCheck into a sentence, or "" if it is confident.

    "solid" answers say nothing — they do not need a caveat.
    "unchecked" and "thin" answers get a warning.
    "shaky" answers get a warning plus the specific figures that
    could not be traced.
    """
    # An empty check (nothing to trace) does not warrant a caveat.
    if check.checked == 0:
        return ""

    if check.clean:
        return ""

    if check.unsupported_numbers:
        listed = ", ".join(check.unsupported_numbers[:3])
        return (
            f"\u26a0 I could not trace {listed} back to anything I "
            f"read. Treat them as my reasoning, not a reading of your "
            f"sheet."
        )

    if check.unknown_names:
        listed = ", ".join(check.unknown_names[:3])
        return (
            f"\u26a0 {listed} do not appear in anything I read. If "
            f"they are real, they came from outside your sheet."
        )

    return ""