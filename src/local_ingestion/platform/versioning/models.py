"""Versioning / change-analysis domain models (MOD-06 / T-201, T-202).

The Diff engine is deliberately storage-agnostic: it consumes a normalized
:class:`CatalogState` (built either from the catalog ORM or from a snapshot) and
emits a :class:`DiffResult` of discrete :class:`Change` items. Impact grading
(T-202) then attaches a :class:`GradedChange` level to each.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ColumnSpec:
    name: str
    data_type: str
    nullable: bool
    comment: Optional[str] = None
    is_pii: bool = False
    high_sensitivity: bool = False
    importance: int = 0  # business importance 1-9 (catalog grade_level)


@dataclass
class TableSpec:
    fqn: str
    name: str
    schema: Optional[str] = None
    columns: List[ColumnSpec] = field(default_factory=list)
    struct_hash: Optional[str] = None
    importance: int = 0


@dataclass
class CatalogState:
    tables: List[TableSpec] = field(default_factory=list)


@dataclass
class Change:
    change_type: str  # table_added|table_removed|table_renamed|column_added|
    # column_removed|column_renamed|type_changed|nullable_changed|comment_changed
    fqn: str
    old_fqn: Optional[str] = None
    table_fqn: Optional[str] = None
    column: Optional[str] = None
    old_column: Optional[str] = None
    detail: Dict[str, Any] = field(default_factory=dict)
    sensitive: bool = False
    importance: int = 0
    datasource_id: int = 0


@dataclass
class DiffResult:
    datasource_id: int
    baseline_snapshot_id: Optional[int] = None
    current_snapshot_id: Optional[int] = None
    tables_added: List[str] = field(default_factory=list)
    tables_removed: List[str] = field(default_factory=list)
    tables_renamed: List[tuple] = field(default_factory=list)
    tables_changed: List[str] = field(default_factory=list)
    table_changes: List[Change] = field(default_factory=list)
    column_changes: List[Change] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.tables_added or self.tables_removed or self.tables_renamed
                    or self.tables_changed or self.column_changes)

    def all_changes(self) -> List[Change]:
        return self.table_changes + self.column_changes


@dataclass
class GradedChange:
    change_type: str
    fqn: str
    level: str  # P0 | P1 | P2 | P3
    column: Optional[str] = None
    old_fqn: Optional[str] = None
    old_column: Optional[str] = None
    detail: Dict[str, Any] = field(default_factory=dict)
    sensitive: bool = False
    importance: int = 0
    datasource_id: int = 0
