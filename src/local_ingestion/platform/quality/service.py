"""Quality case execution with persisted results (FR-M5).

Why this module exists
----------------------
``quality/rules.py`` already defines seven rule types, but running them produces
results only in memory: ``quality_result`` exists as a table and nothing ever
writes it. So quality had no history, no trend, and no way to answer "was this
column already clean last week?" — which is the whole point of FR-M5.3/5.5.

Design
------
* **Push down first.** Every rule compiles to one ``SELECT`` against the source
  and runs in the database. Only ``custom_sql`` falls back to evaluating a
  caller-supplied statement, and only rules that cannot be expressed as SQL
  would need in-memory evaluation (none today) — see FR-M5.2.
* **A failed rule is not an error.** "3 rows are null" is a quality result, not
  an exception. Only an unrunnable rule (bad SQL, missing column) becomes
  ``passed=False`` with an ``error`` in the detail payload.
* **Never writes to the business database.** Statements are read-only, matching
  the profiling constraint.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select, text

from ..storage.models_governance import QualityResult, QualityRule

__all__ = ["CaseResult", "QualityService", "SUPPORTED_RULE_TYPES"]

#: Rule types this service can compile to SQL.
SUPPORTED_RULE_TYPES = (
    "not_null",
    "unique",
    "range",
    "pattern",
    "row_count",
    "custom_sql",
)


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


@dataclass
class CaseResult:
    """Outcome of one rule against one table/column."""

    rule_code: str
    passed: bool
    metric_value: float | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    column: str | None = None
    duration_ms: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule_code": self.rule_code,
            "passed": self.passed,
            "metric_value": self.metric_value,
            "detail": self.detail,
            "column": self.column,
            "duration_ms": self.duration_ms,
        }


def compile_rule(rule_type: str, definition: dict[str, Any], relation: str) -> str:
    """Compile one rule into a single read-only SELECT.

    The statement returns one scalar: the number of offending rows. Zero means
    the rule passed. Returning a count (rather than a boolean) is what makes
    ``metric_value`` meaningful for trend reporting.
    """
    column = definition.get("column")
    quoted = _quote(column) if column else None

    if rule_type == "not_null":
        if not quoted:
            raise ValueError("not_null requires definition.column")
        return f"SELECT COUNT(*) FROM {relation} WHERE {quoted} IS NULL"

    if rule_type == "unique":
        if not quoted:
            raise ValueError("unique requires definition.column")
        return (
            f"SELECT COUNT(*) FROM ("
            f"SELECT {quoted} FROM {relation} WHERE {quoted} IS NOT NULL "
            f"GROUP BY {quoted} HAVING COUNT(*) > 1"
            f") AS _dups"
        )

    if rule_type == "range":
        if not quoted:
            raise ValueError("range requires definition.column")
        low = definition.get("min")
        high = definition.get("max")
        clauses = []
        if low is not None:
            clauses.append(f"{quoted} < {float(low)}")
        if high is not None:
            clauses.append(f"{quoted} > {float(high)}")
        if not clauses:
            raise ValueError("range requires definition.min and/or definition.max")
        return f"SELECT COUNT(*) FROM {relation} WHERE {' OR '.join(clauses)}"

    if rule_type == "pattern":
        if not quoted:
            raise ValueError("pattern requires definition.column")
        pattern = str(definition.get("pattern", "")).replace("'", "''")
        if not pattern:
            raise ValueError("pattern requires definition.pattern")
        # must_match=True → count rows that FAIL to match; False → the inverse.
        negate = "" if definition.get("must_match", True) else "NOT "
        return (
            f"SELECT COUNT(*) FROM {relation} "
            f"WHERE {quoted} IS NOT NULL AND {negate}({quoted}::text ~ '{pattern}')"
        )

    if rule_type == "row_count":
        low = definition.get("min")
        high = definition.get("max")
        if low is None and high is None:
            raise ValueError("row_count requires definition.min and/or definition.max")
        # Count how many times the *table-level* predicate fails (0 or 1 rows).
        clauses = []
        if low is not None:
            clauses.append(f"_n < {int(low)}")
        if high is not None:
            clauses.append(f"_n > {int(high)}")
        return (
            f"SELECT COUNT(*) FROM ("
            f"SELECT COUNT(*) AS _n FROM {relation}"
            f") AS _t WHERE {' OR '.join(clauses)}"
        )

    if rule_type == "custom_sql":
        sql = str(definition.get("sql", "")).strip()
        if not sql:
            raise ValueError("custom_sql requires definition.sql")
        if not sql.lstrip().lower().startswith("select"):
            # Read-only guarantee: refuse anything that is not a SELECT.
            raise ValueError("custom_sql must be a SELECT statement")
        return sql

    raise ValueError(f"unsupported rule_type: {rule_type!r}")


class QualityService:
    """Runs quality rules and persists results."""

    def __init__(self, session_factory) -> None:
        self._sf = session_factory

    def list_rules(self, *, enabled_only: bool = True) -> list[QualityRule]:
        with self._sf() as session:
            stmt = select(QualityRule)
            if enabled_only:
                stmt = stmt.where(QualityRule.enabled.is_(True))
            return list(session.execute(stmt).scalars().all())

    def run(
        self,
        *,
        engine,
        relation: str,
        table_id: int,
        column_ids: dict[str, int] | None = None,
        rules: Sequence[QualityRule] | None = None,
        persist: bool = True,
    ) -> list[CaseResult]:
        """Execute rules against ``relation`` and optionally persist results."""
        from time import monotonic

        column_ids = column_ids or {}
        targets = list(rules) if rules is not None else self.list_rules()
        results: list[CaseResult] = []

        for rule in targets:
            started = monotonic()
            definition = dict(rule.definition or {})
            try:
                sql = compile_rule(rule.rule_type, definition, relation)
                with engine.connect() as conn:
                    value = conn.execute(text(sql)).scalar()
                offending = int(value or 0)
                threshold = int(definition.get("max_failures", 0))
                results.append(
                    CaseResult(
                        rule_code=rule.code,
                        passed=offending <= threshold,
                        metric_value=float(offending),
                        detail={"offending_rows": offending, "threshold": threshold},
                        column=definition.get("column"),
                        duration_ms=int((monotonic() - started) * 1000),
                    )
                )
            except Exception as exc:  # noqa: BLE001 - unrunnable rule is a result
                results.append(
                    CaseResult(
                        rule_code=rule.code,
                        passed=False,
                        detail={"error": str(exc)[:300]},
                        column=definition.get("column"),
                        duration_ms=int((monotonic() - started) * 1000),
                    )
                )

        if persist:
            self._persist(table_id, column_ids, results)
        return results

    def _persist(
        self, table_id: int, column_ids: dict[str, int], results: list[CaseResult]
    ) -> None:
        with self._sf() as session:
            rule_codes = [result.rule_code for result in results]
            codes = {
                row.code: row.id
                for row in session.execute(
                    select(QualityRule.code, QualityRule.id).where(
                        QualityRule.code.in_(rule_codes)
                    )
                ).all()
            }
            for result in results:
                rule_id = codes.get(result.rule_code)
                if rule_id is None:
                    continue
                session.add(
                    QualityResult(
                        table_id=table_id,
                        column_id=column_ids.get(result.column or ""),
                        rule_id=rule_id,
                        passed=result.passed,
                        metric_value=result.metric_value,
                        detail=result.detail,
                    )
                )
            session.commit()

    def history(self, table_id: int, *, limit: int = 50) -> list[QualityResult]:
        """Most recent results for one table."""
        with self._sf() as session:
            rows = session.execute(
                select(QualityResult)
                .where(QualityResult.table_id == table_id)
                .order_by(QualityResult.id.desc())
                .limit(limit)
            ).scalars()
            return list(rows)

    def success_rate(self, table_id: int) -> float | None:
        """Passed / total for the latest snapshot of each rule on one table."""
        rows = self.history(table_id)
        if not rows:
            return None
        passed = sum(1 for row in rows if row.passed)
        return passed / len(rows)


def now() -> datetime:
    return datetime.now()
