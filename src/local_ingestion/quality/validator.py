"""Data Validation Engine Module

This module provides validators for executing quality rules against
tables, columns, and batch operations.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Union

from local_ingestion.quality.rules import (
    QualityRule,
    RuleResult,
    RuleFactory,
    RuleType,
)


@dataclass
class ValidationResult:
    """Result of a validation operation.
    
    Attributes:
        validator_name: Name of the validator that produced this result.
        overall_passed: Whether all validations passed.
        total_rules: Total number of rules executed.
        passed_rules: Number of rules that passed.
        failed_rules: Number of rules that failed.
        rule_results: Dictionary mapping rule names to their results.
        execution_time_ms: Total execution time in milliseconds.
        timestamp: When the validation was performed.
    """
    validator_name: str
    overall_passed: bool
    total_rules: int
    passed_rules: int
    failed_rules: int
    rule_results: Dict[str, RuleResult] = field(default_factory=dict)
    execution_time_ms: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    @property
    def pass_rate(self) -> float:
        """Calculate the pass rate percentage."""
        if self.total_rules == 0:
            return 100.0
        return (self.passed_rules / self.total_rules) * 100
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert the result to a dictionary."""
        return {
            "validator_name": self.validator_name,
            "overall_passed": self.overall_passed,
            "total_rules": self.total_rules,
            "passed_rules": self.passed_rules,
            "failed_rules": self.failed_rules,
            "pass_rate": self.pass_rate,
            "rule_results": {name: result.to_dict() for name, result in self.rule_results.items()},
            "execution_time_ms": self.execution_time_ms,
            "timestamp": self.timestamp.isoformat(),
        }


class BaseValidator:
    """Abstract base class for validators."""
    
    def __init__(self, name: str):
        """Initialize the validator.
        
        Args:
            name: Name of the validator.
        """
        self.name = name
        self._rules: List[QualityRule] = []
    
    def add_rule(self, rule: QualityRule) -> None:
        """Add a rule to the validator.
        
        Args:
            rule: QualityRule to add.
        """
        self._rules.append(rule)
    
    def add_rules(self, rules: List[QualityRule]) -> None:
        """Add multiple rules to the validator.
        
        Args:
            rules: List of QualityRules to add.
        """
        self._rules.extend(rules)
    
    def clear_rules(self) -> None:
        """Remove all rules from the validator."""
        self._rules.clear()
    
    def _execute_rules(
        self,
        data: List[Dict[str, Any]],
        rules: Optional[List[QualityRule]] = None,
    ) -> Dict[str, RuleResult]:
        """Execute rules against data.
        
        Args:
            data: Data to validate.
            rules: Optional list of rules to execute. If None, uses all rules.
            
        Returns:
            Dictionary mapping rule names to results.
        """
        rules_to_execute = rules if rules is not None else self._rules
        results: Dict[str, RuleResult] = {}
        
        for rule in rules_to_execute:
            if rule.enabled:
                results[rule.name] = rule.execute(data)
        
        return results


class TableValidator(BaseValidator):
    """Validator for table-level data quality checks.
    
    This validator executes quality rules against an entire table,
    checking data across all columns.
    """
    
    def __init__(self, table_name: str):
        """Initialize the table validator.
        
        Args:
            table_name: Name of the table being validated.
        """
        super().__init__(f"TableValidator:{table_name}")
        self.table_name = table_name
        self._pre_execute_hook: Optional[Callable[[str], None]] = None
        self._post_execute_hook: Optional[Callable[[str, ValidationResult], None]] = None
    
    def set_pre_execute_hook(self, hook: Callable[[str], None]) -> None:
        """Set a hook to be called before validation.
        
        Args:
            hook: Callable that takes table_name as argument.
        """
        self._pre_execute_hook = hook
    
    def set_post_execute_hook(self, hook: Callable[[str, ValidationResult], None]) -> None:
        """Set a hook to be called after validation.
        
        Args:
            hook: Callable that takes table_name and ValidationResult as arguments.
        """
        self._post_execute_hook = hook
    
    def validate(self, data: List[Dict[str, Any]]) -> ValidationResult:
        """Validate table data against all rules.
        
        Args:
            data: Table data as a list of row dictionaries.
            
        Returns:
            ValidationResult containing all rule execution results.
        """
        start_time = time.perf_counter()
        
        if self._pre_execute_hook:
            self._pre_execute_hook(self.table_name)
        
        rule_results = self._execute_rules(data)
        
        passed_count = sum(1 for result in rule_results.values() if result.passed)
        failed_count = len(rule_results) - passed_count
        
        result = ValidationResult(
            validator_name=self.name,
            overall_passed=failed_count == 0,
            total_rules=len(rule_results),
            passed_rules=passed_count,
            failed_rules=failed_count,
            rule_results=rule_results,
            execution_time_ms=(time.perf_counter() - start_time) * 1000,
        )
        
        if self._post_execute_hook:
            self._post_execute_hook(self.table_name, result)
        
        return result
    
    def validate_column(self, data: List[Dict[str, Any]], column: str) -> ValidationResult:
        """Validate a specific column in the table data.
        
        Args:
            data: Table data as a list of row dictionaries.
            column: Name of the column to validate.
            
        Returns:
            ValidationResult for the column validation.
        """
        column_rules = [rule for rule in self._rules if rule.column == column]
        
        if not column_rules:
            return ValidationResult(
                validator_name=f"{self.name}:{column}",
                overall_passed=True,
                total_rules=0,
                passed_rules=0,
                failed_rules=0,
            )
        
        start_time = time.perf_counter()
        rule_results = self._execute_rules(data, column_rules)
        
        passed_count = sum(1 for result in rule_results.values() if result.passed)
        failed_count = len(rule_results) - passed_count
        
        return ValidationResult(
            validator_name=f"{self.name}:{column}",
            overall_passed=failed_count == 0,
            total_rules=len(rule_results),
            passed_rules=passed_count,
            failed_rules=failed_count,
            rule_results=rule_results,
            execution_time_ms=(time.perf_counter() - start_time) * 1000,
        )
    
    @classmethod
    def from_schema(cls, table_name: str, schema: Dict[str, Any]) -> TableValidator:
        """Create a TableValidator from a JSON Schema definition.
        
        Args:
            table_name: Name of the table.
            schema: JSON Schema containing rule definitions.
            
        Returns:
            Configured TableValidator instance.
        """
        validator = cls(table_name)
        rules = RuleFactory.from_json_schema(schema)
        validator.add_rules(rules)
        return validator


class ColumnValidator(BaseValidator):
    """Validator for column-level data quality checks.
    
    This validator focuses on validating a single column against
    a set of column-specific rules.
    """
    
    def __init__(self, table_name: str, column_name: str):
        """Initialize the column validator.
        
        Args:
            table_name: Name of the table containing the column.
            column_name: Name of the column being validated.
        """
        super().__init__(f"ColumnValidator:{table_name}.{column_name}")
        self.table_name = table_name
        self.column_name = column_name
    
    def validate(self, data: List[Dict[str, Any]]) -> ValidationResult:
        """Validate column data against all rules.
        
        Args:
            data: Table data as a list of row dictionaries.
            
        Returns:
            ValidationResult containing all rule execution results.
        """
        start_time = time.perf_counter()
        
        column_data = [row.get(self.column_name) for row in data]
        
        rule_results = self._execute_rules(data)
        
        passed_count = sum(1 for result in rule_results.values() if result.passed)
        failed_count = len(rule_results) - passed_count
        
        return ValidationResult(
            validator_name=self.name,
            overall_passed=failed_count == 0,
            total_rules=len(rule_results),
            passed_rules=passed_count,
            failed_rules=failed_count,
            rule_results=rule_results,
            execution_time_ms=(time.perf_counter() - start_time) * 1000,
        )
    
    @classmethod
    def from_schema(
        cls,
        table_name: str,
        column_name: str,
        schema: Dict[str, Any],
    ) -> ColumnValidator:
        """Create a ColumnValidator from a JSON Schema definition.
        
        Args:
            table_name: Name of the table containing the column.
            column_name: Name of the column.
            schema: JSON Schema containing rule definitions.
            
        Returns:
            Configured ColumnValidator instance.
        """
        validator = cls(table_name, column_name)
        rules = RuleFactory.from_json_schema(schema)
        for rule in rules:
            rule.column = column_name
        validator.add_rules(rules)
        return validator


class BatchValidator:
    """Validator for batch validation of multiple tables or columns.
    
    This validator manages multiple TableValidators and ColumnValidators,
    executing them in batch and aggregating results.
    """
    
    def __init__(self, name: str = "BatchValidator"):
        """Initialize the batch validator.
        
        Args:
            name: Name of the batch validator.
        """
        self.name = name
        self._table_validators: Dict[str, TableValidator] = {}
        self._column_validators: Dict[str, ColumnValidator] = {}
        self._parallel_execution: bool = False
        self._max_workers: int = 4
    
    def add_table_validator(self, validator: TableValidator) -> None:
        """Add a table validator to the batch.
        
        Args:
            validator: TableValidator to add.
        """
        self._table_validators[validator.table_name] = validator
    
    def add_column_validator(self, validator: ColumnValidator) -> None:
        """Add a column validator to the batch.
        
        Args:
            validator: ColumnValidator to add.
        """
        key = f"{validator.table_name}.{validator.column_name}"
        self._column_validators[key] = validator
    
    def remove_table_validator(self, table_name: str) -> None:
        """Remove a table validator from the batch.
        
        Args:
            table_name: Name of the table validator to remove.
        """
        self._table_validators.pop(table_name, None)
    
    def remove_column_validator(self, table_name: str, column_name: str) -> None:
        """Remove a column validator from the batch.
        
        Args:
            table_name: Name of the table.
            column_name: Name of the column.
        """
        key = f"{table_name}.{column_name}"
        self._column_validators.pop(key, None)
    
    def set_parallel_execution(self, enabled: bool, max_workers: int = 4) -> None:
        """Configure parallel execution settings.
        
        Args:
            enabled: Whether to enable parallel execution.
            max_workers: Maximum number of worker threads.
        """
        self._parallel_execution = enabled
        self._max_workers = max_workers
    
    def validate_all(
        self,
        table_data: Dict[str, List[Dict[str, Any]]],
    ) -> Dict[str, ValidationResult]:
        """Validate all tables and columns in the batch.
        
        Args:
            table_data: Dictionary mapping table names to their data.
            
        Returns:
            Dictionary mapping validator names to their results.
        """
        results: Dict[str, ValidationResult] = {}
        
        if self._parallel_execution:
            results.update(self._validate_parallel(table_data))
        else:
            results.update(self._validate_sequential(table_data))
        
        return results
    
    def _validate_sequential(
        self,
        table_data: Dict[str, List[Dict[str, Any]]],
    ) -> Dict[str, ValidationResult]:
        """Execute validations sequentially.
        
        Args:
            table_data: Dictionary mapping table names to their data.
            
        Returns:
            Dictionary mapping validator names to their results.
        """
        results: Dict[str, ValidationResult] = {}
        
        for table_name, data in table_data.items():
            if table_name in self._table_validators:
                results[table_name] = self._table_validators[table_name].validate(data)
            
            for key, validator in self._column_validators.items():
                if validator.table_name == table_name:
                    results[key] = validator.validate(data)
        
        return results
    
    def _validate_parallel(
        self,
        table_data: Dict[str, List[Dict[str, Any]]],
    ) -> Dict[str, ValidationResult]:
        """Execute validations in parallel.
        
        Args:
            table_data: Dictionary mapping table names to their data.
            
        Returns:
            Dictionary mapping validator names to their results.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        results: Dict[str, ValidationResult] = {}
        
        def validate_table(table_name: str, data: List[Dict[str, Any]]) -> tuple:
            table_results = {}
            if table_name in self._table_validators:
                table_results[table_name] = self._table_validators[table_name].validate(data)
            
            for key, validator in self._column_validators.items():
                if validator.table_name == table_name:
                    table_results[key] = validator.validate(data)
            
            return table_results
        
        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            futures = {
                executor.submit(validate_table, table_name, data): table_name
                for table_name, data in table_data.items()
            }
            
            for future in as_completed(futures):
                try:
                    table_results = future.result()
                    results.update(table_results)
                except Exception as e:
                    table_name = futures[future]
                    results[table_name] = ValidationResult(
                        validator_name=table_name,
                        overall_passed=False,
                        total_rules=0,
                        passed_rules=0,
                        failed_rules=0,
                    )
        
        return results
    
    def get_aggregate_result(self, results: Dict[str, ValidationResult]) -> ValidationResult:
        """Get aggregate validation result across all validators.
        
        Args:
            results: Dictionary of validation results.
            
        Returns:
            Aggregated ValidationResult.
        """
        total_rules = sum(r.total_rules for r in results.values())
        passed_rules = sum(r.passed_rules for r in results.values())
        failed_rules = sum(r.failed_rules for r in results.values())
        execution_time = sum(r.execution_time_ms for r in results.values())
        
        all_passed = all(r.overall_passed for r in results.values())
        
        return ValidationResult(
            validator_name=self.name,
            overall_passed=all_passed,
            total_rules=total_rules,
            passed_rules=passed_rules,
            failed_rules=failed_rules,
            execution_time_ms=execution_time,
        )
