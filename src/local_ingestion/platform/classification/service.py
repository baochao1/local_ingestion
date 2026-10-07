"""Apply MOD-05 grading to catalog rows produced by a scan.

Writes three things per column, because the downstream consumers read different
places:

* ``grade_level`` / ``grade_code`` — used by the overview's sensitive ratio
  (``grade_level >= 2``) and by change impact grading as ``importance``.
* ``tags`` (``PII`` / ``HIGH``) and ``properties`` (``pii`` /
  ``high_sensitivity``) — these are what ``build_catalog_state`` reads to decide
  whether a change touches sensitive data. Setting only ``grade_level`` would
  leave every change looking non-sensitive.

Tags are merged, never replaced, and stale ``PII``/``HIGH`` marks are cleared on
re-classification so a downgraded column does not keep its old flag.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional

import structlog

from .rules import GRADE_CODES, HIGH_GRADE, PII_GRADE, classify_column

logger = structlog.get_logger()

#: Tags owned by grading; anything else on the row is preserved.
OWNED_TAGS = ("PII", "HIGH")


def merge_value_verdict(
    name_verdict, value_verdict
) -> tuple:
    """Combine name/type grading with value-pattern evidence (FR-M6).

    Returns ``(verdict, extra_properties)``.

    * No value evidence (or the column was skipped by the value scanner) → the
      name-only verdict stands and no extra properties are added.
    * Strong value evidence (a pattern matched at or above the confidence
      threshold) *upgrades* the grade when it is higher than the name verdict, so
      ``col_7`` holding email addresses becomes PII even with a non-PII name.
    * Weak value evidence (``needs_review``) never upgrades — it is recorded as
      ``value_pii_review`` so the review queue can see it, but a low-confidence
      hit must not be published as fact (QC4).
    """
    if value_verdict is None or value_verdict.skipped or not value_verdict.evidence:
        return name_verdict, {}

    props = {"value_pii_evidence": value_verdict.evidence}
    if value_verdict.needs_review:
        # Pattern matched, but not confidently enough to publish — route to review.
        props["value_pii_review"] = True
        return name_verdict, props

    if value_verdict.grade > name_verdict.grade_level:
        upgraded = type(name_verdict)(
            grade_level=value_verdict.grade,
            grade_code=GRADE_CODES[value_verdict.grade],
            is_pii=value_verdict.grade >= PII_GRADE,
            high_sensitivity=value_verdict.grade >= HIGH_GRADE,
            reason=f"{name_verdict.reason};value:{','.join(value_verdict.evidence)}",
        )
        return upgraded, props
    return name_verdict, props

#: Imported lazily inside the merge helper to avoid a hard import edge at module
#: load (classification is imported by many call sites; the value-PII path is
#: only needed when samples are actually present).
def _evaluate_values(column_name: str, samples, **kwargs):
    from ..profile.pii import evaluate_column

    return evaluate_column(column_name, samples, **kwargs)


@dataclass
class ClassificationResult:
    """What one grading pass changed."""

    datasource_id: int
    tables_graded: int = 0
    columns_graded: int = 0
    pii_columns: int = 0
    sensitive_columns: int = 0
    skipped: int = 0
    #: 因存在人工标注而跳过的实体数（FR-9.5：人工结论不被自动引擎覆盖）。
    manual_preserved: int = 0
    grade_distribution: Dict[str, int] = dc_field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "datasource_id": self.datasource_id,
            "tables_graded": self.tables_graded,
            "columns_graded": self.columns_graded,
            "pii_columns": self.pii_columns,
            "sensitive_columns": self.sensitive_columns,
            "skipped": self.skipped,
            "manual_preserved": self.manual_preserved,
            "grade_distribution": self.grade_distribution,
        }


class ClassificationService:
    """Grade every catalog row of a datasource."""

    def __init__(self, session_factory) -> None:
        self._sf = session_factory

    def classify_datasource(
        self, datasource_id: int, *, only_ungraded: bool = True
    ) -> ClassificationResult:
        """Grade all non-deleted tables/columns of ``datasource_id``.

        Args:
            only_ungraded: Skip rows that already carry a ``grade_level``, so a
                manual grading decision is never overwritten by a re-scan. Turn
                it off to re-derive everything from the current rules.
        """
        from ..storage.models_core import CatalogColumn, CatalogTable

        result = ClassificationResult(datasource_id=datasource_id)
        dist: Dict[str, int] = {}

        with self._sf() as s:
            tables = (
                s.query(CatalogTable)
                .filter(
                    CatalogTable.datasource_id == datasource_id,
                    CatalogTable.deleted_at.is_(None),
                )
                .all()
            )
            columns = (
                s.query(CatalogColumn)
                .filter(
                    CatalogColumn.datasource_id == datasource_id,
                    CatalogColumn.deleted_at.is_(None),
                )
                .all()
            )
            by_table: Dict[int, List[Any]] = {}
            for c in columns:
                by_table.setdefault(c.table_id, []).append(c)

            # FR-9.5：人工标注过的实体，自动引擎不得覆盖——**全量重跑也不例外**。
            manual_cols = _manual_ids(s, "column")
            manual_tables = _manual_ids(s, "table")

            for t in tables:
                t_cols = by_table.get(t.id, [])
                max_grade = 1
                for c in t_cols:
                    if c.id in manual_cols:
                        result.skipped += 1
                        result.manual_preserved += 1
                        max_grade = max(max_grade, int(c.grade_level or 1))
                        continue
                    if only_ungraded and c.grade_level is not None:
                        result.skipped += 1
                        max_grade = max(max_grade, int(c.grade_level))
                        continue
                    verdict = classify_column(
                        c.name, getattr(c, "data_type", None),
                        getattr(c, "description", None),
                    )
                    _apply_column(c, verdict)
                    result.columns_graded += 1
                    result.pii_columns += 1 if verdict.is_pii else 0
                    if verdict.grade_level >= 2:
                        result.sensitive_columns += 1
                    dist[str(verdict.grade_level)] = dist.get(str(verdict.grade_level), 0) + 1
                    max_grade = max(max_grade, verdict.grade_level)

                if t.id in manual_tables:
                    result.manual_preserved += 1
                    continue
                if only_ungraded and t.grade_level is not None:
                    result.skipped += 1
                    continue
                t.grade_level = max_grade
                t.grade_code = GRADE_CODES[max_grade]
                result.tables_graded += 1

            s.commit()

        result.grade_distribution = dist
        logger.info("classification_finished", **result.as_dict())
        return result


def _manual_ids(session: Any, entity_type: str) -> set:
    """已被人工标注的实体 ID（FR-9.5）。

    引擎据此跳过这些实体——否则人工改正的误判会在下一次全量重跑时被改回去。
    """
    from ..storage.models_governance import EntityTag

    return {
        row[0]
        for row in session.query(EntityTag.entity_id)
        .filter(
            EntityTag.entity_type == entity_type,
            EntityTag.source == "manual",
            EntityTag.deleted_at.is_(None),
        )
        .all()
    }


def _apply_column(col: Any, verdict) -> None:
    """Write grade + sensitivity markers onto a ``CatalogColumn`` row."""
    col.grade_level = verdict.grade_level
    col.grade_code = verdict.grade_code

    tags = [t for t in (col.tags or []) if t not in OWNED_TAGS]
    tags.extend(verdict.tags)
    col.tags = tags

    props = dict(col.properties or {})
    # False (not absent) on purpose: a column that is no longer PII must lose
    # the flag, and `bool(props.get(...))` treats both the same.
    props["pii"] = verdict.is_pii
    props["high_sensitivity"] = verdict.high_sensitivity
    props["grade_reason"] = verdict.reason
    col.properties = props


__all__ = [
    "ClassificationResult",
    "ClassificationService",
    "HIGH_GRADE",
    "PII_GRADE",
]
