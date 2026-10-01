"""Unit tests for validation engine module"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from local_ingestion.quality.rules import (
    NotNullRule,
    UniqueRule,
    RangeCheckRule,
    PatternMatchRule,
    RuleResult,
)
from local_ingestion.quality.validator import (
    ValidationResult,
    BaseValidator,
    TableValidator,
    ColumnValidator,
    BatchValidator,
)


class TestValidationResult:
    """Tests for ValidationResult class."""

    def test_validation_result_creation(self):
        result = ValidationResult(
            validator_name="test_validator",
            overall_passed=True,
            total_rules=5,
            passed_rules=5,
            failed_rules=0,
        )
        assert result.validator_name == "test_validator"
        assert result.overall_passed is True
        assert result.pass_rate == 100.0

    def test_validation_result_with_failures(self):
        result = ValidationResult(
            validator_name="test_validator",
            overall_passed=False,
            total_rules=10,
            passed_rules=7,
            failed_rules=3,
        )
        assert result.overall_passed is False
        assert result.pass_rate == 70.0

    def test_validation_result_zero_rules(self):
        result = ValidationResult(
            validator_name="empty_validator",
            overall_passed=True,
            total_rules=0,
            passed_rules=0,
            failed_rules=0,
        )
        assert result.pass_rate == 100.0

    def test_validation_result_to_dict(self):
        result = ValidationResult(
            validator_name="test_validator",
            overall_passed=True,
            total_rules=5,
            passed_rules=5,
            failed_rules=0,
        )
        data = result.to_dict()
        assert data["validator_name"] == "test_validator"
        assert data["overall_passed"] is True
        assert data["total_rules"] == 5
        assert "timestamp" in data


class TestTableValidator:
    """Tests for TableValidator class."""

    def test_table_validator_creation(self):
        validator = TableValidator("users")
        assert validator.table_name == "users"
        assert validator.name == "TableValidator:users"

    def test_add_rule(self):
        validator = TableValidator("users")
        rule = NotNullRule(name="check_email", column="email")
        validator.add_rule(rule)
        assert len(validator._rules) == 1

    def test_validate_all_passed(self):
        validator = TableValidator("users")
        validator.add_rule(NotNullRule(name="check_name", column="name"))
        validator.add_rule(NotNullRule(name="check_email", column="email"))

        data = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob", "email": "bob@example.com"},
        ]

        result = validator.validate(data)
        assert result.overall_passed is True
        assert result.total_rules == 2
        assert result.passed_rules == 2

    def test_validate_with_failures(self):
        validator = TableValidator("users")
        validator.add_rule(NotNullRule(name="check_email", column="email"))

        data = [
            {"email": "alice@example.com"},
            {"email": None},
            {"email": "charlie@example.com"},
        ]

        result = validator.validate(data)
        assert result.overall_passed is False
        assert result.failed_rules == 1

    def test_validate_column(self):
        validator = TableValidator("users")
        validator.add_rule(NotNullRule(name="check_email", column="email"))
        validator.add_rule(NotNullRule(name="check_name", column="name"))

        data = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob", "email": None},
        ]

        result = validator.validate_column(data, "email")
        assert result.validator_name == "TableValidator:users:email"
        assert result.overall_passed is False

    def test_validate_column_no_rules(self):
        validator = TableValidator("users")
        data = [{"name": "Alice", "email": "alice@example.com"}]

        result = validator.validate_column(data, "nonexistent")
        assert result.overall_passed is True
        assert result.total_rules == 0

    def test_pre_execute_hook(self):
        hook_called = []

        def pre_hook(table_name: str) -> None:
            hook_called.append(table_name)

        validator = TableValidator("users")
        validator.set_pre_execute_hook(pre_hook)

        data = [{"name": "Alice"}]
        validator.validate(data)

        assert hook_called == ["users"]

    def test_post_execute_hook(self):
        hook_results = []

        def post_hook(table_name: str, result: ValidationResult) -> None:
            hook_results.append((table_name, result.overall_passed))

        validator = TableValidator("users")
        validator.add_rule(NotNullRule(name="check_name", column="name"))
        validator.set_post_execute_hook(post_hook)

        data = [{"name": "Alice"}]
        validator.validate(data)

        assert hook_results == [("users", True)]

    def test_from_schema(self):
        schema = {
            "rules": [
                {"name": "check_name", "ruleType": "not_null", "column": "name"},
                {"name": "check_email", "ruleType": "unique", "column": "email"},
            ]
        }

        validator = TableValidator.from_schema("users", schema)
        assert len(validator._rules) == 2


class TestColumnValidator:
    """Tests for ColumnValidator class."""

    def test_column_validator_creation(self):
        validator = ColumnValidator("users", "email")
        assert validator.table_name == "users"
        assert validator.column_name == "email"
        assert validator.name == "ColumnValidator:users.email"

    def test_validate_passed(self):
        validator = ColumnValidator("users", "email")
        validator.add_rule(PatternMatchRule(
            name="check_format",
            column="email",
            pattern=r"^[\w\.-]+@[\w\.-]+\.\w+$",
        ))

        data = [
            {"email": "alice@example.com"},
            {"email": "bob@example.com"},
        ]

        result = validator.validate(data)
        assert result.overall_passed is True

    def test_validate_failed(self):
        validator = ColumnValidator("users", "email")
        validator.add_rule(PatternMatchRule(
            name="check_format",
            column="email",
            pattern=r"^[\w\.-]+@[\w\.-]+\.\w+$",
        ))

        data = [
            {"email": "invalid-email"},
            {"email": "bob@example.com"},
        ]

        result = validator.validate(data)
        assert result.overall_passed is False
        assert result.failed_rules == 1

    def test_from_schema(self):
        schema = {
            "rules": [
                {"name": "check_pattern", "ruleType": "pattern_match", "column": "any", "config": {"pattern": r"^\w+$"}},
            ]
        }

        validator = ColumnValidator.from_schema("users", "email", schema)
        assert validator.column_name == "email"
        assert len(validator._rules) == 1
        assert validator._rules[0].column == "email"


class TestBatchValidator:
    """Tests for BatchValidator class."""

    def test_batch_validator_creation(self):
        validator = BatchValidator()
        assert validator.name == "BatchValidator"
        assert len(validator._table_validators) == 0
        assert len(validator._column_validators) == 0

    def test_add_table_validator(self):
        batch = BatchValidator()
        table_validator = TableValidator("users")
        batch.add_table_validator(table_validator)

        assert "users" in batch._table_validators
        assert batch._table_validators["users"] is table_validator

    def test_add_column_validator(self):
        batch = BatchValidator()
        col_validator = ColumnValidator("users", "email")
        batch.add_column_validator(col_validator)

        key = "users.email"
        assert key in batch._column_validators

    def test_remove_table_validator(self):
        batch = BatchValidator()
        table_validator = TableValidator("users")
        batch.add_table_validator(table_validator)
        batch.remove_table_validator("users")

        assert "users" not in batch._table_validators

    def test_remove_column_validator(self):
        batch = BatchValidator()
        col_validator = ColumnValidator("users", "email")
        batch.add_column_validator(col_validator)
        batch.remove_column_validator("users", "email")

        assert "users.email" not in batch._column_validators

    def test_validate_all_sequential(self):
        batch = BatchValidator()

        table_validator = TableValidator("users")
        table_validator.add_rule(NotNullRule(name="check_name", column="name"))
        batch.add_table_validator(table_validator)

        table_data = {
            "users": [
                {"name": "Alice"},
                {"name": None},
            ]
        }

        results = batch.validate_all(table_data)

        assert "users" in results
        assert results["users"].overall_passed is False

    def test_validate_all_parallel(self):
        batch = BatchValidator()
        batch.set_parallel_execution(enabled=True, max_workers=2)

        table_validator = TableValidator("users")
        table_validator.add_rule(NotNullRule(name="check_name", column="name"))
        batch.add_table_validator(table_validator)

        table_data = {
            "users": [
                {"name": "Alice"},
                {"name": "Bob"},
            ]
        }

        results = batch.validate_all(table_data)
        assert "users" in results
        assert results["users"].overall_passed is True

    def test_get_aggregate_result(self):
        batch = BatchValidator()

        result1 = ValidationResult(
            validator_name="table1",
            overall_passed=True,
            total_rules=5,
            passed_rules=5,
            failed_rules=0,
            execution_time_ms=100.0,
        )

        result2 = ValidationResult(
            validator_name="table2",
            overall_passed=False,
            total_rules=5,
            passed_rules=3,
            failed_rules=2,
            execution_time_ms=50.0,
        )

        aggregate = batch.get_aggregate_result({"table1": result1, "table2": result2})

        assert aggregate.total_rules == 10
        assert aggregate.passed_rules == 8
        assert aggregate.failed_rules == 2
        assert aggregate.overall_passed is False
        assert aggregate.execution_time_ms == 150.0


class TestValidatorIntegration:
    """Integration tests for validators with real rules."""

    def test_complete_validation_workflow(self):
        validator = TableValidator("customers")

        validator.add_rule(NotNullRule(name="check_id", column="customer_id"))
        validator.add_rule(NotNullRule(name="check_name", column="name"))
        validator.add_rule(NotNullRule(name="check_email", column="email"))
        validator.add_rule(UniqueRule(name="unique_email", column="email"))
        validator.add_rule(RangeCheckRule(
            name="check_age",
            column="age",
            min_value=0,
            max_value=150,
        ))

        data = [
            {"customer_id": 1, "name": "Alice", "email": "alice@example.com", "age": 30},
            {"customer_id": 2, "name": "Bob", "email": "bob@example.com", "age": 25},
            {"customer_id": 3, "name": None, "email": "charlie@example.com", "age": 35},
            {"customer_id": 4, "name": "David", "email": "alice@example.com", "age": 200},
        ]

        result = validator.validate(data)

        assert result.overall_passed is False
        assert result.failed_rules == 3
        assert result.rule_results["check_name"].failed_count == 1
        assert result.rule_results["unique_email"].failed_count == 1
        assert result.rule_results["check_age"].failed_count == 1

    def test_batch_validation_multiple_tables(self):
        batch = BatchValidator()

        users_validator = TableValidator("users")
        users_validator.add_rule(NotNullRule(name="check_id", column="id"))
        batch.add_table_validator(users_validator)

        orders_validator = TableValidator("orders")
        orders_validator.add_rule(NotNullRule(name="check_user_id", column="user_id"))
        batch.add_table_validator(orders_validator)

        table_data = {
            "users": [
                {"id": 1},
                {"id": 2},
            ],
            "orders": [
                {"user_id": 1},
                {"user_id": None},
            ],
        }

        results = batch.validate_all(table_data)

        assert len(results) == 2
        assert results["users"].overall_passed is True
        assert results["orders"].overall_passed is False
