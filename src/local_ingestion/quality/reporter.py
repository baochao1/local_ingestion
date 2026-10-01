"""Quality Report Generation Module

This module provides functionality for generating data quality reports
in various formats (HTML, JSON) with statistical summaries and trend analysis.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from local_ingestion.quality.validator import ValidationResult


@dataclass
class ReportSummary:
    """Summary statistics for a quality report.
    
    Attributes:
        total_tables: Total number of tables validated.
        total_columns: Total number of columns validated.
        total_rules: Total number of rules executed.
        passed_rules: Number of rules that passed.
        failed_rules: Number of rules that failed.
        overall_pass_rate: Overall pass rate percentage.
        critical_failures: Number of critical severity failures.
        warning_failures: Number of warning severity failures.
    """
    total_tables: int = 0
    total_columns: int = 0
    total_rules: int = 0
    passed_rules: int = 0
    failed_rules: int = 0
    overall_pass_rate: float = 0.0
    critical_failures: int = 0
    warning_failures: int = 0
    
    @property
    def success_rate(self) -> float:
        """Alias for overall_pass_rate."""
        return self.overall_pass_rate
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert the summary to a dictionary."""
        return {
            "total_tables": self.total_tables,
            "total_columns": self.total_columns,
            "total_rules": self.total_rules,
            "passed_rules": self.passed_rules,
            "failed_rules": self.failed_rules,
            "overall_pass_rate": self.overall_pass_rate,
            "critical_failures": self.critical_failures,
            "warning_failures": self.warning_failures,
        }


@dataclass
class TrendDataPoint:
    """A single data point in a trend analysis.
    
    Attributes:
        timestamp: When the data point was recorded.
        metric_name: Name of the metric being tracked.
        value: Value of the metric.
        entity_name: Name of the entity (table/column) being tracked.
    """
    timestamp: datetime
    metric_name: str
    value: float
    entity_name: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert the data point to a dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "metric_name": self.metric_name,
            "value": self.value,
            "entity_name": self.entity_name,
        }


@dataclass
class QualityReport:
    """Data quality report containing validation results.
    
    Attributes:
        report_id: Unique identifier for the report.
        title: Title of the report.
        generated_at: Timestamp when the report was generated.
        summary: Statistical summary of the validation results.
        table_results: Validation results per table.
        column_results: Validation results per column.
        trends: Trend analysis data if historical data is available.
        metadata: Additional metadata about the report.
    """
    report_id: str
    title: str
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    summary: ReportSummary = field(default_factory=ReportSummary)
    table_results: Dict[str, "ValidationResult"] = field(default_factory=dict)
    column_results: Dict[str, "ValidationResult"] = field(default_factory=dict)
    trends: List[TrendDataPoint] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert the report to a dictionary."""
        return {
            "report_id": self.report_id,
            "title": self.title,
            "generated_at": self.generated_at.isoformat(),
            "summary": self.summary.to_dict(),
            "table_results": {
                name: result.to_dict() for name, result in self.table_results.items()
            },
            "column_results": {
                name: result.to_dict() for name, result in self.column_results.items()
            },
            "trends": [t.to_dict() for t in self.trends],
            "metadata": self.metadata,
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Convert the report to a JSON string.
        
        Args:
            indent: Indentation level for pretty printing.
            
        Returns:
            JSON string representation of the report.
        """
        return json.dumps(self.to_dict(), indent=indent, default=str)
    
    def to_html(self) -> str:
        """Convert the report to an HTML string.
        
        Returns:
            HTML string representation of the report.
        """
        return QualityReporter.generate_html_report(self)


class QualityReporter:
    """Generator for data quality reports."""
    
    @staticmethod
    def generate_report(
        title: str,
        table_results: Optional[Dict[str, "ValidationResult"]] = None,
        column_results: Optional[Dict[str, "ValidationResult"]] = None,
        trends: Optional[List[TrendDataPoint]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> QualityReport:
        """Generate a quality report from validation results.
        
        Args:
            title: Title for the report.
            table_results: Dictionary of table validation results.
            column_results: Dictionary of column validation results.
            trends: List of trend data points.
            metadata: Additional metadata to include.
            
        Returns:
            QualityReport instance.
        """
        import uuid
        
        table_results = table_results or {}
        column_results = column_results or {}
        trends = trends or []
        metadata = metadata or {}
        
        summary = QualityReporter._calculate_summary(
            table_results, column_results
        )
        
        return QualityReport(
            report_id=str(uuid.uuid4()),
            title=title,
            summary=summary,
            table_results=table_results,
            column_results=column_results,
            trends=trends,
            metadata=metadata,
        )
    
    @staticmethod
    def _calculate_summary(
        table_results: Dict[str, "ValidationResult"],
        column_results: Dict[str, "ValidationResult"],
    ) -> ReportSummary:
        """Calculate summary statistics from validation results.
        
        Args:
            table_results: Table validation results.
            column_results: Column validation results.
            
        Returns:
            ReportSummary with calculated statistics.
        """
        total_tables = len(table_results)
        total_columns = len(column_results)
        
        total_rules = 0
        passed_rules = 0
        failed_rules = 0
        critical_failures = 0
        warning_failures = 0
        
        for result in list(table_results.values()) + list(column_results.values()):
            total_rules += result.total_rules
            passed_rules += result.passed_rules
            failed_rules += result.failed_rules
        
        overall_pass_rate = 0.0
        if total_rules > 0:
            overall_pass_rate = (passed_rules / total_rules) * 100
        
        return ReportSummary(
            total_tables=total_tables,
            total_columns=total_columns,
            total_rules=total_rules,
            passed_rules=passed_rules,
            failed_rules=failed_rules,
            overall_pass_rate=overall_pass_rate,
            critical_failures=critical_failures,
            warning_failures=warning_failures,
        )
    
    @staticmethod
    def generate_html_report(report: QualityReport) -> str:
        """Generate an HTML report from a QualityReport.
        
        Args:
            report: QualityReport to convert to HTML.
            
        Returns:
            HTML string representation.
        """
        summary = report.summary
        passed_class = "success" if summary.overall_pass_rate >= 90 else "warning" if summary.overall_pass_rate >= 70 else "danger"
        
        html_parts = [
            "<!DOCTYPE html>",
            "<html lang='en'>",
            "<head>",
            "    <meta charset='UTF-8'>",
            "    <meta name='viewport' content='width=device-width, initial-scale=1.0'>",
            f"    <title>{report.title} - Data Quality Report</title>",
            "    <style>",
            "        * { margin: 0; padding: 0; box-sizing: border-box; }",
            "        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; padding: 20px; }",
            "        .container { max-width: 1200px; margin: 0 auto; }",
            "        .header { background: white; padding: 24px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }",
            "        .header h1 { color: #333; margin-bottom: 8px; }",
            "        .header .meta { color: #666; font-size: 14px; }",
            "        .card { background: white; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }",
            "        .card-header { padding: 16px 24px; border-bottom: 1px solid #eee; }",
            "        .card-header h2 { color: #333; font-size: 18px; }",
            "        .card-body { padding: 24px; }",
            "        .summary-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; }",
            "        .stat-card { background: #f8f9fa; padding: 16px; border-radius: 6px; }",
            "        .stat-value { font-size: 28px; font-weight: bold; color: #333; }",
            "        .stat-label { color: #666; font-size: 14px; margin-top: 4px; }",
            "        .stat-card.success .stat-value { color: #28a745; }",
            "        .stat-card.warning .stat-value { color: #ffc107; }",
            "        .stat-card.danger .stat-value { color: #dc3545; }",
            "        table { width: 100%; border-collapse: collapse; }",
            "        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #eee; }",
            "        th { background: #f8f9fa; font-weight: 600; color: #333; }",
            "        .badge { display: inline-block; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 500; }",
            "        .badge.success { background: #d4edda; color: #155724; }",
            "        .badge.warning { background: #fff3cd; color: #856404; }",
            "        .badge.danger { background: #f8d7da; color: #721c24; }",
            "        .progress-bar { height: 8px; background: #e9ecef; border-radius: 4px; overflow: hidden; margin-top: 8px; }",
            "        .progress-fill { height: 100%; transition: width 0.3s ease; }",
            "        .progress-fill.success { background: #28a745; }",
            "        .progress-fill.warning { background: #ffc107; }",
            "        .progress-fill.danger { background: #dc3545; }",
            "        .detail-row { display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px solid #eee; }",
            "        .detail-row:last-child { border-bottom: none; }",
            "    </style>",
            "</head>",
            "<body>",
            "    <div class='container'>",
            "        <div class='header'>",
            f"            <h1>{report.title}</h1>",
            f"            <div class='meta'>Generated: {report.generated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}</div>",
            "        </div>",
        ]
        
        html_parts.extend([
            "        <div class='card'>",
            "            <div class='card-header'>",
            "                <h2>Summary</h2>",
            "            </div>",
            "            <div class='card-body'>",
            "                <div class='summary-grid'>",
            "                    <div class='stat-card'>",
            f"                        <div class='stat-value'>{summary.total_tables}</div>",
            "                        <div class='stat-label'>Tables Validated</div>",
            "                    </div>",
            "                    <div class='stat-card'>",
            f"                        <div class='stat-value'>{summary.total_columns}</div>",
            "                        <div class='stat-label'>Columns Validated</div>",
            "                    </div>",
            "                    <div class='stat-card'>",
            f"                        <div class='stat-value'>{summary.total_rules}</div>",
            "                        <div class='stat-label'>Total Rules</div>",
            "                    </div>",
            f"                    <div class='stat-card {passed_class}'>",
            f"                        <div class='stat-value'>{summary.overall_pass_rate:.1f}%</div>",
            "                        <div class='stat-label'>Pass Rate</div>",
            "                        <div class='progress-bar'>",
            f"                            <div class='progress-fill {passed_class}' style='width: {summary.overall_pass_rate}%'></div>",
            "                        </div>",
            "                    </div>",
            "                </div>",
            "            </div>",
            "        </div>",
        ])
        
        if report.table_results:
            html_parts.extend([
                "        <div class='card'>",
                "            <div class='card-header'>",
                "                <h2>Table Results</h2>",
                "            </div>",
                "            <div class='card-body'>",
                "                <table>",
                "                    <thead>",
                "                        <tr>",
                "                            <th>Table</th>",
                "                            <th>Status</th>",
                "                            <th>Rules Passed</th>",
                "                            <th>Rules Failed</th>",
                "                            <th>Pass Rate</th>",
                "                            <th>Execution Time (ms)</th>",
                "                        </tr>",
                "                    </thead>",
                "                    <tbody>",
            ])
            
            for table_name, result in report.table_results.items():
                status_class = "success" if result.overall_passed else "danger"
                status_text = "Passed" if result.overall_passed else "Failed"
                pass_rate = result.pass_rate
                
                html_parts.extend([
                    "                        <tr>",
                    f"                            <td>{table_name}</td>",
                    f"                            <td><span class='badge {status_class}'>{status_text}</span></td>",
                    f"                            <td>{result.passed_rules}</td>",
                    f"                            <td>{result.failed_rules}</td>",
                    f"                            <td>{pass_rate:.1f}%</td>",
                    f"                            <td>{result.execution_time_ms:.2f}</td>",
                    "                        </tr>",
                ])
            
            html_parts.extend([
                "                    </tbody>",
                "                </table>",
                "            </div>",
                "        </div>",
            ])
        
        if report.column_results:
            html_parts.extend([
                "        <div class='card'>",
                "            <div class='card-header'>",
                "                <h2>Column Results</h2>",
                "            </div>",
                "            <div class='card-body'>",
                "                <table>",
                "                    <thead>",
                "                        <tr>",
                "                            <th>Column</th>",
                "                            <th>Status</th>",
                "                            <th>Rules Passed</th>",
                "                            <th>Rules Failed</th>",
                "                            <th>Pass Rate</th>",
                "                        </tr>",
                "                    </thead>",
                "                    <tbody>",
            ])
            
            for column_name, result in report.column_results.items():
                status_class = "success" if result.overall_passed else "danger"
                status_text = "Passed" if result.overall_passed else "Failed"
                
                html_parts.extend([
                    "                        <tr>",
                    f"                            <td>{column_name}</td>",
                    f"                            <td><span class='badge {status_class}'>{status_text}</span></td>",
                    f"                            <td>{result.passed_rules}</td>",
                    f"                            <td>{result.failed_rules}</td>",
                    f"                            <td>{result.pass_rate:.1f}%</td>",
                    "                        </tr>",
                ])
            
            html_parts.extend([
                "                    </tbody>",
                "                </table>",
            ])
        
        if report.trends:
            html_parts.extend([
                "        <div class='card'>",
                "            <div class='card-header'>",
                "                <h2>Trend Analysis</h2>",
                "            </div>",
                "            <div class='card-body'>",
                "                <p>Trend data visualization would be rendered here.</p>",
                "            </div>",
                "        </div>",
            ])
        
        html_parts.extend([
            "    </div>",
            "</body>",
            "</html>",
        ])
        
        return "\n".join(html_parts)
    
    @staticmethod
    def export_to_openmetadata_format(report: QualityReport) -> Dict[str, Any]:
        """Export report in OpenMetadata-compatible format.
        
        Args:
            report: QualityReport to export.
            
        Returns:
            Dictionary in OpenMetadata event format.
        """
        return {
            "entity": {
                "id": report.report_id,
                "type": "dataQualityReport",
            },
            "eventType": "entityUpdated",
            "timestamp": report.generated_at.isoformat(),
            "payload": report.to_dict(),
        }
