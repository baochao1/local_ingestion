"""Entity identity resolution (FR-13, MOD-02 §4.4).

The catalog uses a surrogate ``id`` as the stable internal identity while ``fqn``
is merely the *current* fully-qualified name. When a table/column is renamed the
FQN changes but the entity must keep its ``id`` so that lineage, tags and history
survive. This module detects renames by structural similarity (field-set overlap
/ ``struct_hash`` + name similarity) and produces the ``entity_alias`` records
that preserve former names (FR-13.6).

The functions here are pure and duck-typed: ``existing_*`` accept any object
exposing the catalog attributes (``id``, ``fqn``, ``name``, ``struct_hash``,
``columns_json`` for tables; ``id``, ``fqn``, ``name``, ``ordinal_position``,
``data_type``, ``nullable`` for columns). The PostgresSink wires the results into
its single upsert transaction; see ``platform/sinks/postgres.py``.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass
from hashlib import md5
from typing import Any, Dict, List, Optional

# Thresholds (MOD-02 §4.4). A rename is adopted only when *both* the structural
# overlap and the name similarity clear their minima.
TABLE_FIELD_OVERLAP_MIN = 0.8
TABLE_NAME_SIM_MIN = 0.6
TABLE_HIGH_CONF_OVERLAP = 1.0
TABLE_HIGH_CONF_NAME_SIM = 0.8
COLUMN_NAME_SIM_MIN = 0.6
COLUMN_POS_WINDOW = 2  # consider columns within N ordinal positions
COLUMN_HIGH_CONF = 0.85


@dataclass
class TableResolution:
    fqn: str
    action: str  # "matched" | "renamed" | "new"
    entity_id: Optional[int] = None
    old_fqn: Optional[str] = None
    confidence: float = 0.0
    pending: bool = False  # low confidence -> needs human confirmation
    entity_type: str = "table"
    alias_fqn: Optional[str] = None  # former FQN to record in entity_alias


@dataclass
class ColumnResolution:
    fqn: str  # always the *new* fully-qualified name
    action: str  # "matched" | "renamed" | "new"
    entity_id: Optional[int] = None
    old_fqn: Optional[str] = None
    confidence: float = 0.0
    pending: bool = False
    entity_type: str = "column"
    alias_fqn: Optional[str] = None


def name_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _schema_of(fqn: str) -> str:
    parts = fqn.split(".")
    return ".".join(parts[:-1]) if len(parts) > 1 else ""


def table_struct_hash(col_names: List[str], col_types: List[Any]) -> str:
    """Replica of ``PostgresSink._struct_hash`` over primitive inputs."""
    parts = []
    for name, dtype in sorted(
        zip(col_names, col_types), key=lambda x: x[0]
    ):
        parts.append(f"{name}:{dtype}")
    return md5("|".join(parts).encode("utf-8")).hexdigest()


def _table_field_overlap(existing: Any, cur_col_names: List[str],
                         cur_struct_hash: str) -> float:
    """1.0 when struct_hash matches; else Jaccard over column names."""
    if existing.struct_hash and existing.struct_hash == cur_struct_hash:
        return 1.0
    existing_names = {c.get("name") for c in (existing.columns_json or [])}
    existing_names.discard(None)
    if not existing_names and not cur_col_names:
        return 1.0
    if not existing_names or not cur_col_names:
        return 0.0
    inter = len(existing_names & set(cur_col_names))
    union = len(existing_names | set(cur_col_names))
    return inter / union


def resolve_tables(
    datasource_id: int,
    current_tables: List[Dict[str, Any]],
    existing_tables: List[Any],
) -> List[TableResolution]:
    """Resolve each current table to an existing entity, a rename, or a new one.

    ``current_tables`` items: ``{"fqn", "name", "struct_hash", "col_names"}``.
    ``existing_tables``: duck-typed catalog rows (see module docstring).
    """
    existing_by_fqn = {t.fqn: t for t in existing_tables}
    existing_by_schema: Dict[str, List[Any]] = {}
    for t in existing_tables:
        existing_by_schema.setdefault(_schema_of(t.fqn), []).append(t)

    out: List[TableResolution] = []
    for cur in current_tables:
        fqn = cur["fqn"]
        if fqn in existing_by_fqn:
            out.append(TableResolution(
                fqn=fqn, action="matched",
                entity_id=existing_by_fqn[fqn].id, confidence=1.0,
            ))
            continue

        best = None  # (cand, overlap, nsim)
        for cand in existing_by_schema.get(_schema_of(fqn), []):
            overlap = _table_field_overlap(cand, cur["col_names"], cur["struct_hash"])
            nsim = name_similarity(cur["name"], cand.name)
            if overlap >= TABLE_FIELD_OVERLAP_MIN and nsim >= TABLE_NAME_SIM_MIN:
                score = 0.6 * overlap + 0.4 * nsim
                if best is None or score > best[1]:
                    best = (cand, overlap, nsim)

        if best is not None:
            cand, overlap, nsim = best
            high = (
                overlap >= TABLE_HIGH_CONF_OVERLAP
                and nsim >= TABLE_HIGH_CONF_NAME_SIM
            )
            out.append(TableResolution(
                fqn=fqn, action="renamed", entity_id=cand.id, old_fqn=cand.fqn,
                confidence=round(0.6 * overlap + 0.4 * nsim, 3),
                pending=not high, entity_type="table", alias_fqn=cand.fqn,
            ))
        else:
            out.append(TableResolution(fqn=fqn, action="new"))
    return out


def resolve_columns(
    datasource_id: int,
    current_columns: List[Dict[str, Any]],
    existing_columns: List[Any],
    table_old_fqn: str,
    table_new_fqn: str,
) -> List[ColumnResolution]:
    """Resolve columns of one table (matched or renamed) to existing entities.

    ``current_columns`` items: ``{"fqn", "name", "ordinal_position",
    "data_type", "nullable"}``. ``existing_columns``: duck-typed catalog rows.
    Every returned ``fqn`` is the *new* qualified name so the caller can rewrite
    the existing row's FQN and keep its ``id``.
    """
    existing_by_fqn = {c.fqn: c for c in existing_columns}
    existing_by_name = {c.name: c for c in existing_columns}

    out: List[ColumnResolution] = []
    for cur in current_columns:
        new_fqn = f"{table_new_fqn}.{cur['name']}"
        if cur["fqn"] in existing_by_fqn or cur["name"] in existing_by_name:
            eid = (
                existing_by_fqn[cur["fqn"]].id
                if cur["fqn"] in existing_by_fqn
                else existing_by_name[cur["name"]].id
            )
            out.append(ColumnResolution(
                fqn=new_fqn, action="matched", entity_id=eid, confidence=1.0,
            ))
            continue

        best = None  # (cand, score)
        for cand in existing_columns:
            if cand.data_type != cur["data_type"]:
                continue
            pos_diff = abs(
                (cand.ordinal_position or 0) - (cur["ordinal_position"] or 0)
            )
            if pos_diff > COLUMN_POS_WINDOW:
                continue
            nsim = name_similarity(cur["name"], cand.name)
            if nsim >= COLUMN_NAME_SIM_MIN:
                score = 0.5 * nsim + 0.5 * (1 - pos_diff / (COLUMN_POS_WINDOW + 1))
                if best is None or score > best[1]:
                    best = (cand, score)

        if best is not None:
            cand, score = best
            high = score >= COLUMN_HIGH_CONF
            out.append(ColumnResolution(
                fqn=new_fqn, action="renamed", entity_id=cand.id,
                old_fqn=cand.fqn,
                confidence=round(score, 3), pending=not high,
                entity_type="column", alias_fqn=cand.fqn,
            ))
        else:
            out.append(ColumnResolution(fqn=new_fqn, action="new"))
    return out


def detect_orphans(existing_tables: List[Any], current_fqns: set) -> List[Any]:
    """FR-13.5: entities present in the catalog but absent from this scan.

    The caller decides what to do with them (mark pending / retain history).
    """
    return [t for t in existing_tables if t.fqn not in current_fqns]
