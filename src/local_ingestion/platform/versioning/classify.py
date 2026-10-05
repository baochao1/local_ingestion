"""Impact grading of schema changes (MOD-06 / T-202).

Maps each :class:`Change` to a severity level (P0 highest .. P3 lowest) using
the change type, the sensitivity of the affected column (PII / high-sensitivity)
and the business importance of the entity (catalog grade_level). The rules:

* P0 — destructive or high-blast-radius: table drop, column drop, type change or
  rename of a sensitive column, table rename (breaks lineage).
* P1 — structural edits on normal columns, nullable flip, or sensitive column add.
* P2 — additive / low-risk structural edits.
* P3 — cosmetic (comment changes).
* An entity with importance >= 7 is promoted one level.
"""
from __future__ import annotations

from .models import Change, DiffResult, GradedChange

_LEVEL_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
_BOOST = {"P3": "P2", "P2": "P1", "P1": "P0", "P0": "P0"}


class ImpactClassifier:
    def classify(self, diff: DiffResult) -> list[GradedChange]:
        out: list[GradedChange] = []
        for ch in diff.table_changes:
            out.append(self._grade_table(ch))
        for ch in diff.column_changes:
            out.append(self._grade_column(ch))
        out.sort(key=lambda g: _LEVEL_RANK.get(g.level, 9))
        return out

    @staticmethod
    def _boost(level: str, importance: int) -> str:
        if importance >= 7:
            return _BOOST.get(level, level)
        return level

    def _grade_table(self, ch: Change) -> GradedChange:
        level = {
            "table_removed": "P0",
            "table_renamed": "P1",
            "table_added": "P2",
        }.get(ch.change_type, "P2")
        return GradedChange(
            ch.change_type, ch.fqn, level,
            old_fqn=ch.old_fqn, detail=ch.detail,
            datasource_id=ch.datasource_id,
        )

    def _grade_column(self, ch: Change) -> GradedChange:
        t = ch.change_type
        if t == "column_removed":
            level = "P0" if ch.sensitive else "P1"
        elif t in ("type_changed", "column_renamed"):
            level = "P0" if ch.sensitive else "P1"
        elif t == "nullable_changed":
            level = "P1" if ch.sensitive else "P2"
        elif t == "column_added":
            level = "P1" if ch.sensitive else "P2"
        elif t == "comment_changed":
            level = "P3"
        else:
            level = "P2"
        level = self._boost(level, ch.importance)
        return GradedChange(
            t, ch.fqn, level,
            column=ch.column, old_column=ch.old_column,
            detail=ch.detail, sensitive=ch.sensitive, importance=ch.importance,
            datasource_id=ch.datasource_id,
        )
