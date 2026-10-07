"""Value-pattern verification for classification (FR-M6) — pure functions.

Why this module exists
----------------------
Grading today is name-only heuristics: ``user_name`` is PII because the word
"name" appears. That over-fires (``product_name``) and under-fires (a column
called ``col_7`` holding phone numbers). Looking at actual values fixes both,
which is what OpenMetadata does with its value-pattern scan.

Design constraints
------------------
* **This module never reads the database.** It takes ``samples`` as an argument.
  That is deliberate, not an oversight: FR-M6.7 / QC1 forbid profiling-side
  grading from issuing new queries, so "no new data is fetched" is enforced by
  the signature rather than by a promise in a docstring.
* **Enum-like columns are skipped.** A status flag matches nothing and scanning
  a handful of repeated values buys nothing. Upstream applies the same guard
  (distinct/row under 1%). High-cardinality columns such as UUID primary keys
  need no guard — they simply match no pattern.
* **Every verdict carries evidence.** A grade without a reason cannot be
  reviewed, and unreviewable grades are how false positives reach production
  policy (QC4).

Provenance
----------
Scoring shape follows OpenMetadata ``pii/algorithms/classifiers.py``
(name hit adds a fixed bonus, value-pattern hit rate scales the score, a
confidence threshold gates publication). The regexes are local — bundled
rather than ported, because a Chinese-context deployment needs id-card and
mainland-mobile patterns that upstream's generic set does not emphasise.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

__all__ = [
    "VALUE_PATTERNS",
    "DEFAULT_CONFIDENCE_THRESHOLD",
    "ColumnVerdict",
    "evaluate_column",
    "is_low_cardinality",
]


@dataclass(frozen=True)
class ValuePattern:
    """One value-level signal."""

    code: str
    pattern: re.Pattern[str]
    #: Suggested grade when this pattern fires (1–5 ladder, see classification).
    grade: int
    #: How much a full match is worth before the hit-rate scales it.
    weight: float


#: Ordered most-specific first: a CN id card also looks like a long digit run,
#: so the narrower pattern must win.
VALUE_PATTERNS: tuple[ValuePattern, ...] = (
    ValuePattern("id_card_cn", re.compile(r"^\d{17}[\dXx]$"), 4, 0.95),
    ValuePattern("phone_cn", re.compile(r"^1[3-9]\d{9}$"), 3, 0.9),
    ValuePattern("email", re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$"), 3, 0.9),
    ValuePattern("bank_card", re.compile(r"^\d{16,19}$"), 4, 0.7),
)

#: Below this confidence a verdict is "needs review", not published (FR-M6.3).
DEFAULT_CONFIDENCE_THRESHOLD = 0.1

#: Distinct/row ratio under which a column is considered high-cardinality noise.
HIGH_CARDINALITY_RATIO = 0.01

#: Bonus added when the column *name* also matches (upstream uses +0.5).
NAME_HIT_BONUS = 0.5


@dataclass
class ColumnVerdict:
    """Outcome for one column."""

    grade: int
    confidence: float
    #: Why: ``name`` / ``value:<code>`` / both. Empty means "no signal at all".
    evidence: list[str] = field(default_factory=list)
    #: True when confidence is below threshold — route to review, do not publish.
    needs_review: bool = False
    #: True when the column was skipped rather than evaluated.
    skipped: bool = False
    skip_reason: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "grade": self.grade,
            "confidence": round(self.confidence, 4),
            "evidence": list(self.evidence),
            "needs_review": self.needs_review,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
        }


def is_low_cardinality(distinct_count: int | None, row_count: int) -> bool:
    """Whether a column is enum-like and therefore pointless to pattern-scan.

    A distinct/row ratio under 1% means a handful of values repeated across
    many rows (status flags, gender, type codes). Such columns are essentially
    never PII and scanning them is pure cost, so upstream skips them (FR-M6.4).

    ``None`` (unknown) is treated as *not* low-cardinality so a missing
    statistic never silently suppresses a real detection.
    """
    if distinct_count is None or row_count <= 0:
        return False
    return (distinct_count / row_count) < HIGH_CARDINALITY_RATIO


def _name_hits(column_name: str) -> bool:
    lowered = column_name.lower()
    tokens = re.split(r"[^a-z0-9]+", lowered)
    return bool(
        {"phone", "mobile", "tel", "email", "mail", "idcard", "id_card", "ssn",
         "bankcard", "card_no", "idno", "identity"} & set(tokens)
    )


def evaluate_column(
    column_name: str,
    samples: Sequence[str] | Iterable[str],
    *,
    distinct_count: int | None = None,
    row_count: int = 0,
    name_hit: bool | None = None,
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> ColumnVerdict:
    """Grade one column from its name plus a sample of its values.

    ``samples`` are values already collected elsewhere (profiling); nothing is
    fetched here.

    ``name_hit`` lets callers pass the result of the existing name heuristic;
    when omitted it is recomputed locally so this function stands alone.
    """
    values = [str(value) for value in samples if value is not None and str(value) != ""]
    hit_name = _name_hits(column_name) if name_hit is None else name_hit

    if is_low_cardinality(distinct_count, row_count):
        # Enum-like column: no PII signal, and scanning is pure cost (FR-M6.4).
        return ColumnVerdict(
            grade=1,
            confidence=0.0,
            evidence=["skipped: low cardinality"],
            skipped=True,
            skip_reason="low_cardinality",
        )

    if not values:
        return ColumnVerdict(
            grade=1,
            confidence=NAME_HIT_BONUS if hit_name else 0.0,
            evidence=["name"] if hit_name else [],
            needs_review=True,
        )

    best_pattern: ValuePattern | None = None
    best_rate = 0.0
    for pattern in VALUE_PATTERNS:
        matches = sum(1 for value in values if pattern.pattern.match(value))
        if matches == 0:
            continue
        rate = matches / len(values)
        if rate > best_rate:
            best_rate = rate
            best_pattern = pattern

    evidence: list[str] = []
    if hit_name:
        evidence.append("name")
    confidence = 0.0
    grade = 1

    if best_pattern is not None:
        # Hit rate scales the pattern's weight: one phone number among 100
        # values is weak evidence, 95 of 100 is strong.
        confidence = best_pattern.weight * best_rate
        grade = best_pattern.grade
        evidence.append(f"value:{best_pattern.code}")

    if hit_name:
        confidence += NAME_HIT_BONUS

    confidence = min(confidence, 1.0)
    if not evidence:
        return ColumnVerdict(grade=1, confidence=0.0, evidence=[], needs_review=False)

    return ColumnVerdict(
        grade=grade,
        confidence=confidence,
        evidence=evidence,
        needs_review=confidence < threshold,
    )
