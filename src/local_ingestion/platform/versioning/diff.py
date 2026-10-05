"""Schema diff engine (MOD-06 / T-201).

Compares two :class:`CatalogState` snapshots (baseline vs current) and produces a
:class:`DiffResult`. Table/column rename detection reuses ``identity.resolve_*``
so renames are identified by structural + name similarity exactly as during
ingestion (FR-13.4), preventing false "drop + recreate" diffs.
"""
from __future__ import annotations

from types import SimpleNamespace

from ..identity import resolve_columns, resolve_tables, table_struct_hash
from .models import CatalogState, Change, ColumnSpec, DiffResult, TableSpec


def _compute_table_hash(table: TableSpec) -> str:
    return table_struct_hash(
        [c.name for c in table.columns],
        [c.data_type for c in table.columns],
    )


class SchemaDiffer:
    def diff(
        self,
        baseline: CatalogState,
        current: CatalogState,
        *,
        datasource_id: int,
        baseline_snapshot_id: int | None = None,
        current_snapshot_id: int | None = None,
    ) -> DiffResult:
        self._datasource_id = datasource_id
        base_by_fqn = {t.fqn: t for t in baseline.tables}

        # 1) Resolve current tables against baseline (matched / renamed / new).
        current_descs = [
            {
                "fqn": t.fqn,
                "name": t.name,
                "struct_hash": t.struct_hash or _compute_table_hash(t),
                "col_names": [c.name for c in t.columns],
            }
            for t in current.tables
        ]
        base_objs = [
            SimpleNamespace(
                id=i,
                fqn=t.fqn,
                name=t.name,
                struct_hash=t.struct_hash or _compute_table_hash(t),
                columns_json=[{"name": c.name} for c in t.columns],
            )
            for i, t in enumerate(baseline.tables)
        ]

        resolutions = resolve_tables(datasource_id, current_descs, base_objs)

        result = DiffResult(
            datasource_id=datasource_id,
            baseline_snapshot_id=baseline_snapshot_id,
            current_snapshot_id=current_snapshot_id,
        )
        resolved_baseline_fqns: set[str] = set()

        for res in resolutions:
            cur_tbl = next(t for t in current.tables if t.fqn == res.fqn)
            if res.action == "matched":
                resolved_baseline_fqns.add(res.fqn)
                self._diff_columns(base_by_fqn[res.fqn], cur_tbl, result)
            elif res.action == "renamed":
                resolved_baseline_fqns.add(res.old_fqn)
                result.tables_renamed.append((res.fqn, res.old_fqn))
                result.table_changes.append(
                    Change(
                        "table_renamed", res.fqn,
                        old_fqn=res.old_fqn,
                        detail={"confidence": res.confidence, "pending": res.pending},
                    )
                )
                # Diff the renamed table's columns too (it may also have edits).
                self._diff_columns(base_by_fqn[res.old_fqn], cur_tbl, result)
            else:  # new
                resolved_baseline_fqns.add(res.fqn)
                result.tables_added.append(res.fqn)
                result.table_changes.append(Change("table_added", res.fqn))

        # 2) Tables present in baseline but not resolved -> removed.
        for bt in baseline.tables:
            if bt.fqn not in resolved_baseline_fqns:
                result.tables_removed.append(bt.fqn)
                result.table_changes.append(Change("table_removed", bt.fqn))

        # Stamp datasource id on every emitted change for downstream routing.
        for ch in (*result.table_changes, *result.column_changes):
            ch.datasource_id = self._datasource_id
        return result

    # ------------------------------------------------------------- column diff
    def _diff_columns(self, base_tbl: TableSpec, cur_tbl: TableSpec, result: DiffResult) -> None:
        cur_cols_by_fqn = {f"{cur_tbl.fqn}.{c.name}": c for c in cur_tbl.columns}
        base_objs = [
            SimpleNamespace(
                id=i,
                fqn=f"{base_tbl.fqn}.{c.name}",
                name=c.name,
                ordinal_position=i,
                data_type=c.data_type,
            )
            for i, c in enumerate(base_tbl.columns)
        ]
        cur_descs = [
            {
                "fqn": f"{cur_tbl.fqn}.{c.name}",
                "name": c.name,
                "ordinal_position": i,
                "data_type": c.data_type,
            }
            for i, c in enumerate(cur_tbl.columns)
        ]
        col_res = resolve_columns(
            result.datasource_id, cur_descs, base_objs, base_tbl.fqn, cur_tbl.fqn
        )

        matched_ids: set[int] = set()
        changed = False
        for cr in col_res:
            new_name = cr.fqn.split(".")[-1]
            if cr.action == "matched":
                base_c = base_tbl.columns[cr.entity_id]
                cur_c = cur_cols_by_fqn[cr.fqn]
                matched_ids.add(cr.entity_id)
                if self._compare_column(base_tbl.fqn, base_c, cur_c, result):
                    changed = True
            elif cr.action == "renamed":
                base_c = base_tbl.columns[cr.entity_id]
                matched_ids.add(cr.entity_id)
                result.column_changes.append(
                    Change(
                        "column_renamed", cur_tbl.fqn,
                        column=new_name, old_column=base_c.name,
                        sensitive=base_c.is_pii or base_c.high_sensitivity,
                        importance=base_c.importance,
                        detail={"confidence": cr.confidence, "pending": cr.pending},
                    )
                )
                changed = True
            else:  # new
                cur_c = cur_cols_by_fqn[cr.fqn]
                result.column_changes.append(
                    Change(
                        "column_added", cur_tbl.fqn,
                        column=new_name,
                        sensitive=cur_c.is_pii or cur_c.high_sensitivity,
                        importance=cur_c.importance,
                    )
                )
                changed = True

        # Columns in baseline not matched -> removed.
        for i, bc in enumerate(base_tbl.columns):
            if i not in matched_ids:
                result.column_changes.append(
                    Change(
                        "column_removed", cur_tbl.fqn,
                        column=bc.name,
                        sensitive=bc.is_pii or bc.high_sensitivity,
                        importance=bc.importance,
                    )
                )
                changed = True

        if changed:
            result.tables_changed.append(cur_tbl.fqn)

    @staticmethod
    def _compare_column(table_fqn: str, base_c: ColumnSpec, cur_c: ColumnSpec, result: DiffResult) -> bool:
        touched = False
        if base_c.data_type != cur_c.data_type:
            result.column_changes.append(
                Change(
                    "type_changed", table_fqn, column=cur_c.name,
                    detail={"from": base_c.data_type, "to": cur_c.data_type},
                    sensitive=cur_c.is_pii or cur_c.high_sensitivity,
                    importance=cur_c.importance,
                )
            )
            touched = True
        if base_c.nullable != cur_c.nullable:
            result.column_changes.append(
                Change(
                    "nullable_changed", table_fqn, column=cur_c.name,
                    detail={"from": base_c.nullable, "to": cur_c.nullable},
                    sensitive=cur_c.is_pii or cur_c.high_sensitivity,
                    importance=cur_c.importance,
                )
            )
            touched = True
        if (base_c.comment or "").strip() != (cur_c.comment or "").strip():
            result.column_changes.append(
                Change(
                    "comment_changed", table_fqn, column=cur_c.name,
                    detail={"from": base_c.comment, "to": cur_c.comment},
                    sensitive=cur_c.is_pii or cur_c.high_sensitivity,
                    importance=cur_c.importance,
                )
            )
            touched = True
        return touched
