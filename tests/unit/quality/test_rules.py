"""Unit tests for quality rules module"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

import pytest

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


class TestRuleResult:
    """Tests for RuleResult class."""

    def test_rule_result_creation(self):
        result = RuleResult(
            passed=True,
            failed_count=0,
            total_count=100,
            message="All checks passed",
        )
        assert result.passed is True
        assert result.failed_count == 0
        assert result.total_count == 100
        assert result.success_rate == 100.0

    def test_rule_result_failure(self):
        result = RuleResult(
            passed=False,
            failed_count=10,
            total_count=100,
            message="10 values failed validation",
        )
        assert result.passed is False
        assert result.failed_count == 10
        assert result.success_rate == 90.0

    def test_rule_result_zero_total(self):
        result = RuleResult(
            passed=True,
            failed_count=0,
            total_count=0,
        )
        assert result.success_rate == 100.0

    def test_rule_result_to_dict(self):
        result = RuleResult(
            passed=True,
            failed_count=5,
            total_count=100,
            details={"key": "value"},
        )
        data = result.to_dict()
        assert data["passed"] is True
        assert data["failed_count"] == 5
        assert data["total_count"] == 100
        assert data["details"]["key"] == "value"
        assert "timestamp" in data


class TestNotNullRule:
    """Tests for NotNullRule class."""

    def test_not_null_rule_creation(self):
        rule = NotNullRule(name="check_null", column="email")
        assert rule.name == "check_null"
        assert rule.column == "email"
        assert rule.rule_type == RuleType.NOT_NULL
        assert rule.severity == Severity.WARNING

    def test_not_null_all_valid(self):
        rule = NotNullRule(name="check_null", column="email")
        data = [
            {"email": "a@example.com"},
            {"email": "b@example.com"},
            {"email": "c@example.com"},
        ]
        result = rule.execute(data)
        assert result.passed is True
        assert result.failed_count == 0
        assert result.total_count == 3

    def test_not_null_with_nulls(self):
        rule = NotNullRule(name="check_null", column="email")
        data = [
            {"email": "a@example.com"},
            {"email": None},
            {"email": "c@example.com"},
            {"email": ""},
        ]
        result = rule.execute(data)
        assert result.passed is False
        assert result.failed_count == 2
        assert result.total_count == 4

    def test_not_null_missing_column(self):
        rule = NotNullRule(name="check_null", column="nonexistent")
        data = [{"email": "test@example.com"}]
        result = rule.execute(data)
        assert result.passed is False
        assert result.failed_count == 1


class TestUniqueRule:
    """Tests for UniqueRule class."""

    def test_unique_rule_creation(self):
        rule = UniqueRule(name="check_unique", column="user_id")
        assert rule.name == "check_unique"
        assert rule.column == "user_id"
        assert rule.rule_type == RuleType.UNIQUE

    def test_unique_all_unique(self):
        rule = UniqueRule(name="check_unique", column="user_id")
        data = [
            {"user_id": 1},
            {"user_id": 2},
            {"user_id": 3},
        ]
        result = rule.execute(data)
        assert result.passed is True
        assert result.failed_count == 0

    def test_unique_with_duplicates(self):
        rule = UniqueRule(name="check_unique", column="user_id")
        data = [
            {"user_id": 1},
            {"user_id": 2},
            {"user_id": 1},
            {"user_id": 2},
            {"user_id": 3},
        ]
        result = rule.execute(data)
        assert result.passed is False
        assert result.failed_count == 2
        assert "1" in result.details["duplicate_values"]

    def test_unique_with_nulls(self):
        rule = UniqueRule(name="check_unique", column="user_id")
        data = [
            {"user_id": 1},
            {"user_id": None},
            {"user_id": None},
            {"user_id": 2},
        ]
        result = rule.execute(data)
        assert result.passed is True


class TestRangeCheckRule:
    """Tests for RangeCheckRule class."""

    def test_range_check_creation(self):
        rule = RangeCheckRule(
            name="check_age",
            column="age",
            min_value=0,
            max_value=120,
        )
        assert rule.name == "check_age"
        assert rule.min_value == 0
        assert rule.max_value == 120

    def test_range_check_all_valid(self):
        rule = RangeCheckRule(
            name="check_age",
            column="age",
            min_value=0,
            max_value=120,
        )
        data = [
            {"age": 25},
            {"age": 50},
            {"age": 75},
        ]
        result = rule.execute(data)
        assert result.passed is True
        assert result.failed_count == 0

    def test_range_check_below_min(self):
        rule = RangeCheckRule(
            name="check_age",
            column="age",
            min_value=0,
            max_value=120,
        )
        data = [
            {"age": -5},
            {"age": 50},
        ]
        result = rule.execute(data)
        assert result.passed is False
        assert result.failed_count == 1
        assert result.details["out_of_range_rows"][0]["reason"] == "below_min"

    def test_range_check_above_max(self):
        rule = RangeCheckRule(
            name="check_age",
            column="age",
            min_value=0,
            max_value=120,
        )
        data = [
            {"age": 150},
            {"age": 50},
        ]
        result = rule.execute(data)
        assert result.passed is False
        assert result.failed_count == 1
        assert result.details["out_of_range_rows"][0]["reason"] == "above_max"

    def test_range_check_non_numeric(self):
        rule = RangeCheckRule(
            name="check_age",
            column="age",
            min_value=0,
            max_value=120,
        )
        data = [
            {"age": "not a number"},
            {"age": 50},
        ]
        result = rule.execute(data)
        assert result.passed is False
        assert result.failed_count == 1
        assert result.details["out_of_range_rows"][0]["reason"] == "non_numeric"


class TestPatternMatchRule:
    """Tests for PatternMatchRule class."""

    def test_pattern_match_creation(self):
        rule = PatternMatchRule(
            name="check_email",
            column="email",
            pattern=r"^[\w\.-]+@[\w\.-]+\.\w+$",
        )
        assert rule.name == "check_email"
        assert rule.pattern == r"^[\w\.-]+@[\w\.-]+\.\w+$"

    def test_pattern_match_valid(self):
        rule = PatternMatchRule(
            name="check_email",
            column="email",
            pattern=r"^[\w\.-]+@[\w\.-]+\.\w+$",
        )
        data = [
            {"email": "test@example.com"},
            {"email": "user.name@domain.org"},
        ]
        result = rule.execute(data)
        assert result.passed is True
        assert result.failed_count == 0

    def test_pattern_match_invalid(self):
        rule = PatternMatchRule(
            name="check_email",
            column="email",
            pattern=r"^[\w\.-]+@[\w\.-]+\.\w+$",
        )
        data = [
            {"email": "invalid-email"},
            {"email": "test@example.com"},
        ]
        result = rule.execute(data)
        assert result.passed is False
        assert result.failed_count == 1

    def test_pattern_match_null_value(self):
        rule = PatternMatchRule(
            name="check_email",
            column="email",
            pattern=r"^[\w\.-]+@[\w\.-]+\.\w+$",
        )
        data = [
            {"email": None},
            {"email": "valid@email.com"},
        ]
        result = rule.execute(data)
        assert result.passed is True


class TestReferentialIntegrityRule:
    """Tests for ReferentialIntegrityRule class."""

    def test_referential_integrity_creation(self):
        rule = ReferentialIntegrityRule(
            name="check_status",
            column="status",
            reference_values=["active", "inactive", "pending"],
        )
        assert rule.name == "check_status"
        assert "active" in rule.reference_values

    def test_referential_integrity_valid(self):
        rule = ReferentialIntegrityRule(
            name="check_status",
            column="status",
            reference_values=["active", "inactive", "pending"],
        )
        data = [
            {"status": "active"},
            {"status": "pending"},
            {"status": "inactive"},
        ]
        result = rule.execute(data)
        assert result.passed is True
        assert result.failed_count == 0

    def test_referential_integrity_invalid(self):
        rule = ReferentialIntegrityRule(
            name="check_status",
            column="status",
            reference_values=["active", "inactive", "pending"],
        )
        data = [
            {"status": "active"},
            {"status": "deleted"},
            {"status": "inactive"},
        ]
        result = rule.execute(data)
        assert result.passed is False
        assert result.failed_count == 1
        assert result.details["invalid_rows"][0]["value"] == "deleted"


class TestCustomSQLRule:
    """Tests for CustomSQLRule class."""

    def test_custom_sql_rule_creation(self):
        def validator(data: List[Dict[str, Any]]) -> RuleResult:
            return RuleResult(
                passed=True,
                failed_count=0,
                total_count=len(data),
            )

        rule = CustomSQLRule(
            name="custom_check",
            validator_func=validator,
        )
        assert rule.name == "custom_check"
        assert rule.rule_type == RuleType.CUSTOM_SQL

    def test_custom_sql_rule_execution(self):
        def validator(data: List[Dict[str, Any]]) -> RuleResult:
            return RuleResult(
                passed=True,
                failed_count=0,
                total_count=len(data),
            )

        rule = CustomSQLRule(
            name="custom_check",
            validator_func=validator,
        )
        data = [{"id": 1}, {"id": 2}]
        result = rule.execute(data)
        assert result.passed is True

    def test_custom_sql_rule_exception(self):
        def failing_validator(data: List[Dict[str, Any]]) -> RuleResult:
            raise ValueError("Custom validation error")

        rule = CustomSQLRule(
            name="failing_check",
            validator_func=failing_validator,
        )
        data = [{"id": 1}]
        result = rule.execute(data)
        assert result.passed is False
        assert "Custom validation error" in result.message


class TestRuleFactory:
    """Tests for RuleFactory class."""

    def test_from_dict_not_null(self):
        config = {
            "name": "not_null_email",
            "ruleType": "not_null",
            "column": "email",
        }
        rule = RuleFactory.from_dict(config)
        assert isinstance(rule, NotNullRule)
        assert rule.name == "not_null_email"
        assert rule.column == "email"

    def test_from_dict_unique(self):
        config = {
            "name": "unique_user_id",
            "ruleType": "unique",
            "column": "user_id",
        }
        rule = RuleFactory.from_dict(config)
        assert isinstance(rule, UniqueRule)
        assert rule.column == "user_id"

    def test_from_dict_range_check(self):
        config = {
            "name": "age_range",
            "ruleType": "range_check",
            "column": "age",
            "config": {"minValue": 0, "maxValue": 120},
        }
        rule = RuleFactory.from_dict(config)
        assert isinstance(rule, RangeCheckRule)
        assert rule.min_value == 0
        assert rule.max_value == 120

    def test_from_dict_pattern_match(self):
        config = {
            "name": "email_pattern",
            "ruleType": "pattern_match",
            "column": "email",
            "config": {"pattern": r"^[\w\.-]+@[\w\.-]+\.\w+$"},
        }
        rule = RuleFactory.from_dict(config)
        assert isinstance(rule, PatternMatchRule)
        assert rule.pattern == r"^[\w\.-]+@[\w\.-]+\.\w+$"

    def test_from_dict_referential_integrity(self):
        config = {
            "name": "valid_status",
            "ruleType": "referential_integrity",
            "column": "status",
            "config": {"referenceValues": ["active", "inactive"]},
        }
        rule = RuleFactory.from_dict(config)
        assert isinstance(rule, ReferentialIntegrityRule)
        assert "active" in rule.reference_values

    def test_from_dict_missing_name(self):
        config = {"ruleType": "not_null", "column": "email"}
        with pytest.raises(ValueError, match="must include 'name'"):
            RuleFactory.from_dict(config)

    def test_from_dict_invalid_rule_type(self):
        config = {"name": "test", "ruleType": "invalid_type"}
        with pytest.raises(ValueError, match="invalid ruleType"):
            RuleFactory.from_dict(config)

    def test_from_dict_missing_column(self):
        config = {"name": "test", "ruleType": "not_null"}
        with pytest.raises(ValueError, match="requires 'column'"):
            RuleFactory.from_dict(config)

    def test_from_json_schema(self):
        schema = {
            "rules": [
                {
                    "name": "not_null_email",
                    "ruleType": "not_null",
                    "column": "email",
                },
                {
                    "name": "unique_id",
                    "ruleType": "unique",
                    "column": "id",
                },
            ]
        }
        rules = RuleFactory.from_json_schema(schema)
        assert len(rules) == 2
        assert all(isinstance(r, QualityRule) for r in rules)

    def test_from_json_schema_disabled_rule(self):
        schema = {
            "rules": [
                {"name": "enabled", "ruleType": "not_null", "column": "email", "enabled": True},
                {"name": "disabled", "ruleType": "not_null", "column": "name", "enabled": False},
            ]
        }
        rules = RuleFactory.from_json_schema(schema)
        assert len(rules) == 1
        assert rules[0].name == "enabled"


class TestRuleSeverity:
    """Tests for severity levels in rules."""

    def test_not_null_with_critical_severity(self):
        rule = NotNullRule(
            name="critical_check",
            column="id",
            severity=Severity.CRITICAL,
        )
        assert rule.severity == Severity.CRITICAL

    def test_not_null_with_info_severity(self):
        rule = NotNullRule(
            name="info_check",
            column="id",
            severity=Severity.INFO,
        )
        assert rule.severity == Severity.INFO
