"""Quality Rules Module

This module defines the data quality rule engine for validating data against
various quality checks.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union


class RuleType(Enum):
    """Supported quality rule types."""
    NOT_NULL = "not_null"
    UNIQUE = "unique"
    RANGE_CHECK = "range_check"
    PATTERN_MATCH = "pattern_match"
    REFERENTIAL_INTEGRITY = "referential_integrity"
    CUSTOM_SQL = "custom_sql"


class Severity(Enum):
    """Severity levels for rule violations."""
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


@dataclass
class RuleResult:
    """Result of a quality rule execution.
    
    Attributes:
        passed: Whether the rule passed validation.
        failed_count: Number of records that failed the rule.
        total_count: Total number of records checked.
        details: Additional details about the rule execution.
        message: Human-readable message describing the result.
        timestamp: When the rule was executed.
        execution_time_ms: Time taken to execute the rule in milliseconds.
    """
    passed: bool
    failed_count: int
    total_count: int
    details: Dict[str, Any] = field(default_factory=dict)
    message: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    execution_time_ms: float = 0.0
    
    @property
    def success_rate(self) -> float:
        """Calculate the success rate percentage."""
        if self.total_count == 0:
            return 100.0
        return ((self.total_count - self.failed_count) / self.total_count) * 100
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert the result to a dictionary."""
        return {
            "passed": self.passed,
            "failed_count": self.failed_count,
            "total_count": self.total_count,
            "success_rate": self.success_rate,
            "details": self.details,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "execution_time_ms": self.execution_time_ms,
        }


@dataclass
class QualityRule(ABC):
    """Abstract base class for quality rules.
    
    Attributes:
        name: Unique name for the rule.
        rule_type: Type of the quality rule.
        severity: Severity level of rule violations.
        column: Column name to apply the rule to (if applicable).
        enabled: Whether the rule is enabled.
        description: Description of what the rule checks.
    """
    name: str
    rule_type: RuleType
    severity: Severity = Severity.WARNING
    column: Optional[str] = None
    enabled: bool = True
    description: str = ""
    
    @abstractmethod
    def execute(self, data: List[Dict[str, Any]]) -> RuleResult:
        """Execute the rule against the provided data.
        
        Args:
            data: List of records to validate.
            
        Returns:
            RuleResult containing the validation outcome.
        """
        pass
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert the rule to a dictionary."""
        return {
            "name": self.name,
            "rule_type": self.rule_type.value,
            "severity": self.severity.value,
            "column": self.column,
            "enabled": self.enabled,
            "description": self.description,
        }


class NotNullRule(QualityRule):
    """Rule to check for null values in specified columns."""
    
    def __init__(
        self,
        name: str,
        column: str,
        severity: Severity = Severity.WARNING,
        description: str = "",
    ):
        super().__init__(
            name=name,
            rule_type=RuleType.NOT_NULL,
            column=column,
            severity=severity,
            description=description or f"Check that column '{column}' is not null",
        )
    
    def execute(self, data: List[Dict[str, Any]]) -> RuleResult:
        """Execute the not null check."""
        import time
        start_time = time.perf_counter()
        
        if not self.column:
            return RuleResult(
                passed=False,
                failed_count=0,
                total_count=len(data),
                message="Column not specified for not_null rule",
            )
        
        null_count = 0
        null_rows = []
        
        for idx, row in enumerate(data):
            value = row.get(self.column)
            if value is None or (isinstance(value, str) and value.strip() == ""):
                null_count += 1
                null_rows.append({"row_index": idx, "value": value})
        
        execution_time = (time.perf_counter() - start_time) * 1000
        failed_count = null_count
        passed = failed_count == 0
        
        return RuleResult(
            passed=passed,
            failed_count=failed_count,
            total_count=len(data),
            details={"null_count": null_count, "null_rows": null_rows[:100]},
            message=f"Column '{self.column}' has {null_count} null values out of {len(data)} records",
            execution_time_ms=execution_time,
        )


class UniqueRule(QualityRule):
    """Rule to check for unique values in specified columns."""
    
    def __init__(
        self,
        name: str,
        column: str,
        severity: Severity = Severity.CRITICAL,
        description: str = "",
    ):
        super().__init__(
            name=name,
            rule_type=RuleType.UNIQUE,
            column=column,
            severity=severity,
            description=description or f"Check that column '{column}' has unique values",
        )
    
    def execute(self, data: List[Dict[str, Any]]) -> RuleResult:
        """Execute the unique check."""
        import time
        start_time = time.perf_counter()
        
        if not self.column:
            return RuleResult(
                passed=False,
                failed_count=0,
                total_count=len(data),
                message="Column not specified for unique rule",
            )
        
        seen_values: Dict[Any, List[int]] = {}
        
        for idx, row in enumerate(data):
            value = row.get(self.column)
            if value is not None:
                if value not in seen_values:
                    seen_values[value] = []
                seen_values[value].append(idx)
        
        duplicate_values = {v: rows for v, rows in seen_values.items() if len(rows) > 1}
        duplicate_count = sum(len(rows) - 1 for rows in duplicate_values.values())
        
        execution_time = (time.perf_counter() - start_time) * 1000
        
        return RuleResult(
            passed=duplicate_count == 0,
            failed_count=duplicate_count,
            total_count=len(data),
            details={
                "unique_count": len(seen_values),
                "duplicate_values": {
                    str(k): v for k, v in list(duplicate_values.items())[:100]
                },
            },
            message=f"Found {duplicate_count} duplicate values in column '{self.column}'",
            execution_time_ms=execution_time,
        )


class RangeCheckRule(QualityRule):
    """Rule to check if values are within a specified range."""
    
    def __init__(
        self,
        name: str,
        column: str,
        min_value: Optional[Union[int, float]] = None,
        max_value: Optional[Union[int, float]] = None,
        severity: Severity = Severity.WARNING,
        description: str = "",
    ):
        super().__init__(
            name=name,
            rule_type=RuleType.RANGE_CHECK,
            column=column,
            severity=severity,
            description=description
            or f"Check that column '{column}' values are within range [{min_value}, {max_value}]",
        )
        self.min_value = min_value
        self.max_value = max_value
    
    def execute(self, data: List[Dict[str, Any]]) -> RuleResult:
        """Execute the range check."""
        import time
        start_time = time.perf_counter()
        
        if not self.column:
            return RuleResult(
                passed=False,
                failed_count=0,
                total_count=len(data),
                message="Column not specified for range_check rule",
            )
        
        out_of_range_count = 0
        out_of_range_rows = []
        
        for idx, row in enumerate(data):
            value = row.get(self.column)
            if value is not None:
                try:
                    num_value = float(value)
                    if self.min_value is not None and num_value < self.min_value:
                        out_of_range_count += 1
                        out_of_range_rows.append(
                            {"row_index": idx, "value": value, "reason": "below_min"}
                        )
                    elif self.max_value is not None and num_value > self.max_value:
                        out_of_range_count += 1
                        out_of_range_rows.append(
                            {"row_index": idx, "value": value, "reason": "above_max"}
                        )
                except (ValueError, TypeError):
                    out_of_range_count += 1
                    out_of_range_rows.append(
                        {"row_index": idx, "value": value, "reason": "non_numeric"}
                    )
        
        execution_time = (time.perf_counter() - start_time) * 1000
        
        return RuleResult(
            passed=out_of_range_count == 0,
            failed_count=out_of_range_count,
            total_count=len(data),
            details={
                "min_value": self.min_value,
                "max_value": self.max_value,
                "out_of_range_rows": out_of_range_rows[:100],
            },
            message=f"Found {out_of_range_count} values out of range in column '{self.column}'",
            execution_time_ms=execution_time,
        )


class PatternMatchRule(QualityRule):
    """Rule to check if values match a specified regex pattern."""
    
    def __init__(
        self,
        name: str,
        column: str,
        pattern: str,
        severity: Severity = Severity.WARNING,
        description: str = "",
    ):
        super().__init__(
            name=name,
            rule_type=RuleType.PATTERN_MATCH,
            column=column,
            severity=severity,
            description=description
            or f"Check that column '{column}' values match pattern '{pattern}'",
        )
        self.pattern = pattern
        self._compiled_pattern = re.compile(pattern)
    
    def execute(self, data: List[Dict[str, Any]]) -> RuleResult:
        """Execute the pattern match check."""
        import time
        start_time = time.perf_counter()
        
        if not self.column:
            return RuleResult(
                passed=False,
                failed_count=0,
                total_count=len(data),
                message="Column not specified for pattern_match rule",
            )
        
        non_matching_count = 0
        non_matching_rows = []
        
        for idx, row in enumerate(data):
            value = row.get(self.column)
            if value is not None:
                value_str = str(value)
                if not self._compiled_pattern.match(value_str):
                    non_matching_count += 1
                    non_matching_rows.append({"row_index": idx, "value": value_str})
        
        execution_time = (time.perf_counter() - start_time) * 1000
        
        return RuleResult(
            passed=non_matching_count == 0,
            failed_count=non_matching_count,
            total_count=len(data),
            details={
                "pattern": self.pattern,
                "non_matching_rows": non_matching_rows[:100],
            },
            message=f"Found {non_matching_count} non-matching values in column '{self.column}'",
            execution_time_ms=execution_time,
        )


class ReferentialIntegrityRule(QualityRule):
    """Rule to check referential integrity against a reference dataset."""
    
    def __init__(
        self,
        name: str,
        column: str,
        reference_values: List[Any],
        severity: Severity = Severity.CRITICAL,
        description: str = "",
    ):
        super().__init__(
            name=name,
            rule_type=RuleType.REFERENTIAL_INTEGRITY,
            column=column,
            severity=severity,
            description=description
            or f"Check that column '{column}' values exist in reference dataset",
        )
        self.reference_values = set(reference_values)
    
    def execute(self, data: List[Dict[str, Any]]) -> RuleResult:
        """Execute the referential integrity check."""
        import time
        start_time = time.perf_counter()
        
        if not self.column:
            return RuleResult(
                passed=False,
                failed_count=0,
                total_count=len(data),
                message="Column not specified for referential_integrity rule",
            )
        
        invalid_count = 0
        invalid_rows = []
        
        for idx, row in enumerate(data):
            value = row.get(self.column)
            if value is not None and value not in self.reference_values:
                invalid_count += 1
                invalid_rows.append({"row_index": idx, "value": value})
        
        execution_time = (time.perf_counter() - start_time) * 1000
        
        return RuleResult(
            passed=invalid_count == 0,
            failed_count=invalid_count,
            total_count=len(data),
            details={
                "reference_count": len(self.reference_values),
                "invalid_rows": invalid_rows[:100],
            },
            message=f"Found {invalid_count} invalid references in column '{self.column}'",
            execution_time_ms=execution_time,
        )


class CustomSQLRule(QualityRule):
    """Rule to execute custom SQL-like validation logic."""
    
    def __init__(
        self,
        name: str,
        validator_func: Callable[[List[Dict[str, Any]]], RuleResult],
        description: str = "",
    ):
        super().__init__(
            name=name,
            rule_type=RuleType.CUSTOM_SQL,
            description=description or f"Custom validation rule: {name}",
        )
        self.validator_func = validator_func
    
    def execute(self, data: List[Dict[str, Any]]) -> RuleResult:
        """Execute the custom validation function."""
        import time
        start_time = time.perf_counter()
        
        try:
            result = self.validator_func(data)
            result.execution_time_ms = (time.perf_counter() - start_time) * 1000
            return result
        except Exception as e:
            return RuleResult(
                passed=False,
                failed_count=0,
                total_count=len(data),
                message=f"Custom rule '{self.name}' failed with error: {str(e)}",
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
            )


class RuleFactory:
    """Factory class for creating quality rules from JSON Schema definitions."""
    
    @staticmethod
    def from_dict(rule_config: Dict[str, Any]) -> QualityRule:
        """Create a QualityRule from a dictionary configuration.
        
        Args:
            rule_config: Dictionary containing rule configuration.
                Required fields:
                    - name: str - Unique rule name
                    - ruleType: str - Type of rule (from RuleType enum)
                Optional fields:
                    - column: str - Column to apply rule to
                    - severity: str - Severity level
                    - description: str - Rule description
                    - config: dict - Rule-specific configuration
                    
        Returns:
            QualityRule instance.
            
        Raises:
            ValueError: If rule configuration is invalid.
        """
        name = rule_config.get("name")
        if not name:
            raise ValueError("Rule configuration must include 'name'")
        
        rule_type_str = rule_config.get("ruleType")
        if not rule_type_str:
            raise ValueError(f"Rule '{name}' must include 'ruleType'")
        
        try:
            rule_type = RuleType(rule_type_str)
        except ValueError:
            valid_types = [rt.value for rt in RuleType]
            raise ValueError(
                f"Rule '{name}' has invalid ruleType '{rule_type_str}'. "
                f"Valid types are: {valid_types}"
            )
        
        severity_str = rule_config.get("severity", "warning")
        try:
            severity = Severity(severity_str)
        except ValueError:
            valid_severities = [s.value for s in Severity]
            severity = Severity.WARNING
        
        description = rule_config.get("description", "")
        column = rule_config.get("column")
        config = rule_config.get("config", {})
        
        if rule_type == RuleType.NOT_NULL:
            if not column:
                raise ValueError(f"Rule '{name}' of type 'not_null' requires 'column'")
            return NotNullRule(
                name=name,
                column=column,
                severity=severity,
                description=description,
            )
        
        elif rule_type == RuleType.UNIQUE:
            if not column:
                raise ValueError(f"Rule '{name}' of type 'unique' requires 'column'")
            return UniqueRule(
                name=name,
                column=column,
                severity=severity,
                description=description,
            )
        
        elif rule_type == RuleType.RANGE_CHECK:
            if not column:
                raise ValueError(f"Rule '{name}' of type 'range_check' requires 'column'")
            return RangeCheckRule(
                name=name,
                column=column,
                min_value=config.get("minValue"),
                max_value=config.get("maxValue"),
                severity=severity,
                description=description,
            )
        
        elif rule_type == RuleType.PATTERN_MATCH:
            if not column:
                raise ValueError(f"Rule '{name}' of type 'pattern_match' requires 'column'")
            pattern = config.get("pattern")
            if not pattern:
                raise ValueError(f"Rule '{name}' of type 'pattern_match' requires 'pattern' in config")
            return PatternMatchRule(
                name=name,
                column=column,
                pattern=pattern,
                severity=severity,
                description=description,
            )
        
        elif rule_type == RuleType.REFERENTIAL_INTEGRITY:
            if not column:
                raise ValueError(f"Rule '{name}' of type 'referential_integrity' requires 'column'")
            reference_values = config.get("referenceValues", [])
            return ReferentialIntegrityRule(
                name=name,
                column=column,
                reference_values=reference_values,
                severity=severity,
                description=description,
            )
        
        elif rule_type == RuleType.CUSTOM_SQL:
            raise ValueError(
                f"Rule '{name}' of type 'custom_sql' cannot be created from dict. "
                f"Use CustomSQLRule directly with a validator function."
            )
        
        raise ValueError(f"Unknown rule type: {rule_type}")
    
    @staticmethod
    def from_json_schema(schema: Dict[str, Any]) -> List[QualityRule]:
        """Create a list of QualityRules from a JSON Schema definition.
        
        Args:
            schema: JSON Schema containing rule definitions in 'rules' property.
            
        Returns:
            List of QualityRule instances.
        """
        rules = []
        rules_config = schema.get("rules", [])
        
        for rule_config in rules_config:
            try:
                rule = RuleFactory.from_dict(rule_config)
                if rule_config.get("enabled", True):
                    rules.append(rule)
            except ValueError as e:
                raise ValueError(f"Failed to create rule from config: {e}")
        
        return rules
