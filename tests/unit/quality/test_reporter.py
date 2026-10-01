"""Unit tests for quality reporter module"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List

import pytest

from local_ingestion.quality.rules import RuleResult
from local_ingestion.quality.validator import ValidationResult
from local_ingestion.quality.reporter import (
    QualityReport,
    ReportSummary,
    TrendDataPoint,
    QualityReporter,
)


class TestReportSummary:
    """Tests for ReportSummary class."""

    def test_summary_creation(self):
        summary = ReportSummary(
            total_tables=5,
            total_columns=20,
            total_rules=100,
            passed_rules=90,
            failed_rules=10,
            overall_pass_rate=90.0,
        )
        assert summary.total_tables == 5
        assert summary.total_columns == 20
        assert summary.overall_pass_rate == 90.0

    def test_summary_success_rate_property(self):
        summary = ReportSummary(overall_pass_rate=85.0)
        assert summary.success_rate == 85.0

    def test_summary_to_dict(self):
        summary = ReportSummary(
            total_tables=3,
            total_columns=10,
            total_rules=50,
            passed_rules=45,
            failed_rules=5,
            overall_pass_rate=90.0,
        )
        data = summary.to_dict()
        assert data["total_tables"] == 3
        assert data["total_columns"] == 10
        assert data["passed_rules"] == 45


class TestTrendDataPoint:
    """Tests for TrendDataPoint class."""

    def test_trend_data_point_creation(self):
        timestamp = datetime.now(timezone.utc)
        point = TrendDataPoint(
            timestamp=timestamp,
            metric_name="pass_rate",
            value=95.5,
            entity_name="users",
        )
        assert point.metric_name == "pass_rate"
        assert point.value == 95.5
        assert point.entity_name == "users"

    def test_trend_data_point_to_dict(self):
        point = TrendDataPoint(
            timestamp=datetime.now(timezone.utc),
            metric_name="pass_rate",
            value=90.0,
        )
        data = point.to_dict()
        assert data["metric_name"] == "pass_rate"
        assert data["value"] == 90.0
        assert "timestamp" in data


class TestQualityReport:
    """Tests for QualityReport class."""

    def test_report_creation(self):
        report = QualityReport(
            report_id="test-123",
            title="Test Quality Report",
        )
        assert report.report_id == "test-123"
        assert report.title == "Test Quality Report"
        assert report.generated_at is not None

    def test_report_to_dict(self):
        report = QualityReport(
            report_id="test-123",
            title="Test Report",
            summary=ReportSummary(
                total_tables=2,
                total_columns=10,
                total_rules=20,
                passed_rules=18,
                failed_rules=2,
                overall_pass_rate=90.0,
            ),
        )

        data = report.to_dict()
        assert data["report_id"] == "test-123"
        assert data["title"] == "Test Report"
        assert data["summary"]["total_tables"] == 2
        assert "generated_at" in data

    def test_report_to_json(self):
        report = QualityReport(
            report_id="test-123",
            title="Test Report",
        )

        json_str = report.to_json()
        data = json.loads(json_str)

        assert data["report_id"] == "test-123"
        assert data["title"] == "Test Report"

    def test_report_to_html(self):
        report = QualityReport(
            report_id="test-123",
            title="Test Report",
            summary=ReportSummary(
                total_tables=1,
                total_columns=5,
                total_rules=10,
                passed_rules=8,
                failed_rules=2,
                overall_pass_rate=80.0,
            ),
        )

        html = report.to_html()
        assert "Test Report" in html
        assert "Data Quality Report" in html
        assert "80.0%" in html or "80%" in html


class TestQualityReporter:
    """Tests for QualityReporter class."""

    def test_generate_report_empty(self):
        report = QualityReporter.generate_report("Empty Report")

        assert report.title == "Empty Report"
        assert report.summary.total_tables == 0
        assert report.summary.total_rules == 0
        assert report.summary.overall_pass_rate == 0.0

    def test_generate_report_with_table_results(self):
        table_result = ValidationResult(
            validator_name="TableValidator:users",
            overall_passed=True,
            total_rules=5,
            passed_rules=5,
            failed_rules=0,
        )

        report = QualityReporter.generate_report(
            title="Users Table Report",
            table_results={"users": table_result},
        )

        assert report.summary.total_tables == 1
        assert report.summary.total_rules == 5
        assert report.summary.passed_rules == 5

    def test_generate_report_with_column_results(self):
        col_result = ValidationResult(
            validator_name="ColumnValidator:users.email",
            overall_passed=False,
            total_rules=2,
            passed_rules=1,
            failed_rules=1,
        )

        report = QualityReporter.generate_report(
            title="Column Report",
            column_results={"users.email": col_result},
        )

        assert report.summary.total_columns == 1
        assert report.summary.failed_rules == 1

    def test_generate_html_report(self):
        table_result = ValidationResult(
            validator_name="TableValidator:users",
            overall_passed=True,
            total_rules=10,
            passed_rules=10,
            failed_rules=0,
        )

        report = QualityReporter.generate_report(
            title="Test HTML Report",
            table_results={"users": table_result},
        )

        html = QualityReporter.generate_html_report(report)

        assert "<!DOCTYPE html>" in html
        assert "Test HTML Report" in html
        assert "Tables Validated" in html
        assert "1" in html

    def test_generate_html_report_with_failures(self):
        table_result = ValidationResult(
            validator_name="TableValidator:users",
            overall_passed=False,
            total_rules=10,
            passed_rules=7,
            failed_rules=3,
        )

        report = QualityReporter.generate_report(
            title="Failed Report",
            table_results={"users": table_result},
        )

        html = QualityReporter.generate_html_report(report)

        assert "warning" in html.lower() or "Failed" in html

    def test_export_to_openmetadata_format(self):
        report = QualityReport(
            report_id="om-export-123",
            title="Export Test",
            summary=ReportSummary(
                total_tables=1,
                total_columns=2,
                total_rules=5,
                passed_rules=4,
                failed_rules=1,
                overall_pass_rate=80.0,
            ),
        )

        om_format = QualityReporter.export_to_openmetadata_format(report)

        assert om_format["entity"]["id"] == "om-export-123"
        assert om_format["entity"]["type"] == "dataQualityReport"
        assert om_format["eventType"] == "entityUpdated"
        assert "payload" in om_format

    def test_report_with_trends(self):
        trends = [
            TrendDataPoint(
                timestamp=datetime.now(timezone.utc),
                metric_name="pass_rate",
                value=95.0,
                entity_name="users",
            ),
            TrendDataPoint(
                timestamp=datetime.now(timezone.utc),
                metric_name="pass_rate",
                value=92.0,
                entity_name="users",
            ),
        ]

        report = QualityReporter.generate_report(
            title="Trend Report",
            trends=trends,
        )

        assert len(report.trends) == 2
        assert report.trends[0].metric_name == "pass_rate"

    def test_report_with_metadata(self):
        metadata = {
            "pipeline_id": "pipeline-123",
            "run_id": "run-456",
            "environment": "production",
        }

        report = QualityReporter.generate_report(
            title="Metadata Report",
            metadata=metadata,
        )

        assert report.metadata["pipeline_id"] == "pipeline-123"
        assert report.metadata["environment"] == "production"


class TestReporterIntegration:
    """Integration tests for reporter with real validation results."""

    def test_full_report_workflow(self):
        users_table_result = ValidationResult(
            validator_name="TableValidator:users",
            overall_passed=True,
            total_rules=5,
            passed_rules=5,
            failed_rules=0,
            execution_time_ms=50.0,
        )

        orders_table_result = ValidationResult(
            validator_name="TableValidator:orders",
            overall_passed=False,
            total_rules=4,
            passed_rules=2,
            failed_rules=2,
            execution_time_ms=30.0,
        )

        users_email_result = ValidationResult(
            validator_name="ColumnValidator:users.email",
            overall_passed=True,
            total_rules=2,
            passed_rules=2,
            failed_rules=0,
            execution_time_ms=10.0,
        )

        report = QualityReporter.generate_report(
            title="Daily Quality Report",
            table_results={
                "users": users_table_result,
                "orders": orders_table_result,
            },
            column_results={
                "users.email": users_email_result,
            },
            metadata={
                "date": "2024-01-15",
                "environment": "production",
            },
        )

        assert report.summary.total_tables == 2
        assert report.summary.total_columns == 1
        assert report.summary.total_rules == 11
        assert report.summary.passed_rules == 9
        assert report.summary.failed_rules == 2
        assert report.summary.overall_pass_rate > 0

        json_output = report.to_json()
        assert "Daily Quality Report" in json_output
        assert "users" in json_output
        assert "orders" in json_output

        html_output = report.to_html()
        assert "Daily Quality Report" in html_output
        assert "Pass Rate" in html_output

    def test_report_with_rule_results(self):
        rule_result = RuleResult(
            passed=False,
            failed_count=5,
            total_count=100,
            details={"null_count": 5, "null_rows": [{"row_index": 1, "value": None}]},
            message="Column 'email' has 5 null values",
        )

        table_result = ValidationResult(
            validator_name="TableValidator:users",
            overall_passed=False,
            total_rules=1,
            passed_rules=0,
            failed_rules=1,
        )
        table_result.rule_results["check_email_null"] = rule_result

        report = QualityReporter.generate_report(
            title="Failed Rule Report",
            table_results={"users": table_result},
        )

        assert report.summary.failed_rules == 1

        data = report.to_dict()
        users_result = data["table_results"]["users"]
        assert "check_email_null" in users_result["rule_results"]
        assert users_result["rule_results"]["check_email_null"]["failed_count"] == 5
