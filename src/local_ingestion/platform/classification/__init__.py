"""MOD-05 sensitivity / importance grading.

Fills the gap left by the scan: catalog rows landed with ``grade_level`` NULL and
no sensitivity markers, which made the overview's sensitive-asset ratio and the
change-impact grading permanently empty. See :mod:`.rules` for the ladder.
"""
from .rules import (
    GRADE_CODES,
    HIGH_GRADE,
    PII_GRADE,
    Verdict,
    classify_column,
    classify_table,
)
from .service import ClassificationResult, ClassificationService

__all__ = [
    "GRADE_CODES",
    "HIGH_GRADE",
    "PII_GRADE",
    "Verdict",
    "classify_column",
    "classify_table",
    "ClassificationResult",
    "ClassificationService",
]
