"""Quality Rules Module

This module provides data quality checking functionality including:
- Rule definitions (not_null, unique, range_check, pattern_match, etc.)
- Data validation engine
- Quality report generation
"""

from local_ingestion.quality.rules import (
    RuleType,
    Severity,
    RuleResult,
    QualityRule,
    NotNullRule,
    UniqueRule,
    RangeCheckRule,
    PatternMatchRule,
    ReferentialIntegrityRule,
    CustomSQLRule,
    RuleFactory,
)
from local_ingestion.quality.validator import (
    ValidationResult,
    TableValidator,
    ColumnValidator,
    BatchValidator,
)
from local_ingestion.quality.reporter import (
    QualityReport,
    ReportSummary,
    TrendDataPoint,
    QualityReporter,
)

__all__ = [
    # Rules
    "RuleType",
    "Severity",
    "RuleResult",
    "QualityRule",
    "NotNullRule",
    "UniqueRule",
    "RangeCheckRule",
    "PatternMatchRule",
    "ReferentialIntegrityRule",
    "CustomSQLRule",
    "RuleFactory",
    # Validator
    "ValidationResult",
    "TableValidator",
    "ColumnValidator",
    "BatchValidator",
    # Reporter
    "QualityReport",
    "ReportSummary",
    "TrendDataPoint",
    "QualityReporter",
]
