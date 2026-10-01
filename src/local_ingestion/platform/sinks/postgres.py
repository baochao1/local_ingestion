"""PostgresSink (T-105, MOD-02).

Persists scanned metadata (``schema.data`` ``Database``/``Table``/``Column``)
into the local governance database's ``catalog_*`` tables. It is a sibling of
the existing file sinks and inherits the L1 ``SinkConnector`` contract exactly —
it does **not** touch ``BaseFileSink`` (which is coupled to file configs).

Design notes (see ``doc/design/MOD-02-scan-persistence.md``):

* The pipeline hands over un-normalised source objects and never calls
  ``write_schema``; catalog schemas are derived from each table's FQN here.
* Source objects carry no ``tenant_id``/``datasource_id``; both are injected by
  :class:`PostgresSinkConfig`.
* Writes are buffered and flushed in dependency order
  (database → schema → table → column) within a single transaction, using
  PostgreSQL ``INSERT ... ON CONFLICT (fqn) WHERE deleted_at IS NULL DO UPDATE``
  so re-scans are idempotent. Only columns owned by MOD-02 are updated;
  ``grade_level``/``grade_code`` (owned by MOD-05) are deliberately excluded.
* Column ``data_type`` is normalised through the T-114 dialect when the source
  connector returned ``UNKNOWN`` but a display type is available.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import md5
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import create_engine, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from local_ingestion.core.connectors.base import SinkConnector
from local_ingestion.platform.config import get_database_url
from local_ingestion.platform.dialect import UnknownDialectError, get_dialect
from local_ingestion.platform.identity import (
    detect_orphans,
    resolve_columns,
    resolve_tables,
)
from local_ingestion.platform.storage.models_core import (
    CatalogColumn,
    CatalogDatabase,
    CatalogSchema,
    CatalogTable,
    EntityAlias,
)
from local_ingestion.schema.base import DataType
from local_ingestion.schema.data.database import Database as SourceDatabase
from local_ingestion.schema.data.table import Column as SourceColumn
from local_ingestion.schema.data.table import Table as SourceTable

logger = structlog.get_logger()


@dataclass
class PostgresSinkConfig:
    """Configuration for :class:`PostgresSink`.

    ``tenant_id``/``datasource_id`` are required because the source data objects
    (``schema.data``) do not carry them. ``datasource_id`` must point at an
    existing ``datasource`` row (FK-enforced).
    """

    datasource_id: int
    tenant_id: int = 0
    ds_type: str = "postgres"
    batch_size: int = 5000
    database_url: Optional[str] = None


def _child_to_json(child: SourceColumn) -> Dict[str, Any]:
    dt = child.dataType
    return {
        "name": child.name,
        "dataType": dt.value if isinstance(dt, DataType) else str(dt),
        "dataTypeDisplay": child.dataTypeDisplay or None,
    }


def _column_public(col: SourceColumn, config: PostgresSinkConfig) -> Dict[str, Any]:
    """Public, JSON-serialisable view of a column (also the persistence base)."""
    dt = col.dataType
    # Source Column uses use_enum_values=True, so dt may be a DataType enum or a
    # plain string ("UNKNOWN"); normalise the comparison for both.
    dt_is_unknown = dt == DataType.UNKNOWN or str(dt).upper() == "UNKNOWN"
    if dt_is_unknown and col.dataTypeDisplay:
        try:
            dt = get_dialect(config.ds_type).normalize_type(col.dataTypeDisplay)
        except UnknownDialectError:
            pass
    return {
        "name": col.name,
        "dataType": dt.value if isinstance(dt, DataType) else str(dt),
        "dataTypeDisplay": col.dataTypeDisplay or None,
        "dataLength": col.dataLength,
        "precision": col.precision,
        "scale": col.scale,
        "nullable": col.nullable,
        "ordinalPosition": col.ordinalPosition,
        "default": col.default,
        "description": col.description,
    }


def _struct_hash(columns: List[SourceColumn]) -> str:
    """Stable signature of a table's column structure (FR-2.1 incremental)."""
    parts = []
    for c in sorted(columns, key=lambda x: x.ordinalPosition or 0):
        dt = c.dataType
        type_str = dt.value if isinstance(dt, DataType) else str(dt)
        parts.append(f"{c.ordinalPosition}:{c.name}:{type_str}:{c.nullable}")
    return md5("|".join(parts).encode("utf-8")).hexdigest()


# Columns updated on conflict — module-owned only. grade_level / grade_code
# (MOD-05) and created_at / deleted_at / fqn / id are intentionally excluded;
# updated_at is refreshed via func.now() (TimestampMixin has no onupdate).
_DATABASE_UPDATE = ["name", "description", "owner", "tags", "properties",
                    "tenant_id", "datasource_id"]
_SCHEMA_UPDATE = ["name", "description", "owner", "tags", "properties",
                  "tenant_id", "datasource_id", "database_id"]
_TABLE_UPDATE = ["name", "table_type", "description", "owner", "tags",
                 "properties", "columns_json", "column_count", "struct_hash",
                 "tenant_id", "datasource_id", "schema_id"]
_COLUMN_UPDATE = ["name", "ordinal_position", "data_type", "data_type_display",
                  "data_length", "numeric_precision", "numeric_scale",
                  "nullable", "default_value", "description", "children",
                  "tags", "properties", "struct_hash", "tenant_id",
                  "datasource_id", "table_id"]


class PostgresSink(SinkConnector):
    """Batch-upsert scanned metadata into the catalog_* tables."""

    def __init__(self) -> None:
        super().__init__()
        self._config: Optional[PostgresSinkConfig] = None
        self._engine: Optional[Engine] = None
        self._session_factory: Optional[sessionmaker] = None
        self._session: Optional[Session] = None
        self._databases: Dict[str, Dict[str, Any]] = {}
        self._schemas: Dict[str, Dict[str, Any]] = {}
        self._tables: Dict[str, Dict[str, Any]] = {}
        self._columns: Dict[str, Dict[str, Any]] = {}
        self._column_table_fqn: Dict[str, str] = {}

    # -- SinkConnector contract -----------------------------------------
    def connect(self, config: PostgresSinkConfig) -> None:
        self._config = config
        url = config.database_url or get_database_url()
        self._engine = create_engine(url, pool_pre_ping=True)
        self._session_factory = sessionmaker(bind=self._engine)
        self._session = self._session_factory()
        self._connected = True
        logger.info("postgres_sink_connected", url_masked=_mask(url))

    def disconnect(self) -> None:
        if self._session:
            try:
                self._session.close()
            finally:
                self._session = None
        if self._engine:
            self._engine.dispose()
            self._engine = None
        self._connected = False
        logger.info("postgres_sink_disconnected")

    def write_database(self, database: SourceDatabase) -> None:
        fqn = database.fullyQualifiedName
        self._databases[fqn] = {
            "tenant_id": self._config.tenant_id,
            "datasource_id": self._config.datasource_id,
            "fqn": fqn,
            "name": database.name,
            "description": database.description,
            "owner": getattr(database.owner, "name", None),
            "tags": list(database.tags or []),
            "properties": {},
        }

    def write_table(self, table: SourceTable) -> None:
        parts = table.fullyQualifiedName.split(".")
        db_fqn = parts[0]
        schema_fqn = ".".join(parts[:2]) if len(parts) >= 2 else db_fqn
        schema_name = parts[1] if len(parts) >= 2 else (table.databaseSchema or db_fqn)

        # Schema is derived (pipeline never calls write_schema).
        self._schemas[schema_fqn] = {
            "tenant_id": self._config.tenant_id,
            "datasource_id": self._config.datasource_id,
            "fqn": schema_fqn,
            "name": schema_name,
            "description": None,
            "owner": None,
            "tags": [],
            "properties": {},
        }

        columns = list(table.columns or [])
        for col in columns:
            public = _column_public(col, self._config)
            col_fqn = f"{table.fullyQualifiedName}.{col.name}"
            row = {
                "tenant_id": self._config.tenant_id,
                "datasource_id": self._config.datasource_id,
                "fqn": col_fqn,
                "name": public["name"],
                "ordinal_position": public["ordinalPosition"],
                "data_type": public["dataType"],
                "data_type_display": public["dataTypeDisplay"],
                "data_length": public["dataLength"],
                "numeric_precision": public["precision"],
                "numeric_scale": public["scale"],
                "nullable": public["nullable"],
                "default_value": public["default"],
                "description": public["description"],
                "children": [_child_to_json(ch) for ch in (col.children or [])],
                "tags": list(col.tags or []),
                "properties": {},
                "struct_hash": None,
            }
            self._columns[col_fqn] = row
            self._column_table_fqn[col_fqn] = table.fullyQualifiedName

        self._tables[table.fullyQualifiedName] = {
            "tenant_id": self._config.tenant_id,
            "datasource_id": self._config.datasource_id,
            "fqn": table.fullyQualifiedName,
            "name": table.name,
            "table_type": table.tableType,
            "description": table.description,
            "owner": getattr(table.owner, "name", None),
            "tags": list(table.tags or []),
            "properties": {},
            "columns_json": [public for public in (
                _column_public(c, self._config) for c in columns
            )],
            "column_count": len(columns),
            "struct_hash": _struct_hash(columns),
        }

    def flush(self) -> None:
        if self._session is None:
            return
        if not (self._databases or self._schemas or self._tables or self._columns):
            return
        try:
            self._resolve_identities()
            db_ids = self._upsert(CatalogDatabase, list(self._databases.values()),
                                  _DATABASE_UPDATE, key_fqn=True)
            for schema in self._schemas.values():
                schema["database_id"] = db_ids[_parent_db(schema["fqn"])]
            schema_ids = self._upsert(CatalogSchema, list(self._schemas.values()),
                                      _SCHEMA_UPDATE, key_fqn=True)
            for table in self._tables.values():
                table["schema_id"] = schema_ids[_parent_schema(table["fqn"])]
            table_ids = self._upsert(CatalogTable, list(self._tables.values()),
                                     _TABLE_UPDATE, key_fqn=True)
            for col_fqn, row in self._columns.items():
                row["table_id"] = table_ids[self._column_table_fqn[col_fqn]]
            self._upsert(CatalogColumn, list(self._columns.values()),
                         _COLUMN_UPDATE, key_fqn=False)
            self._session.commit()
            logger.info(
                "postgres_sink_flushed",
                databases=len(self._databases),
                schemas=len(self._schemas),
                tables=len(self._tables),
                columns=len(self._columns),
            )
        except Exception as exc:  # noqa: BLE001
            self._session.rollback()
            self._log_write_error(exc, "catalog_batch")
            raise
        finally:
            self._reset_buffers()

    def _resolve_identities(self) -> None:
        """FR-13 identity resolution, run inside the flush transaction.

        For tables/columns whose FQN changed but structure is preserved, rewrite
        the *existing* row's FQN to the new one (keeping its stable ``id``) and
        record the former name in ``entity_alias``. The subsequent
        ``ON CONFLICT (fqn)`` upsert then hits the same row, so a rename is never
        reported as delete + add (which would break lineage and lose tags/history).
        """
        if self._session is None or not self._tables:
            return
        ds = self._config.datasource_id
        existing_tables = (
            self._session.query(CatalogTable)
            .filter_by(datasource_id=ds, deleted_at=None)
            .all()
        )
        if not existing_tables:
            return

        current_table_dicts = [
            {
                "fqn": t["fqn"],
                "name": t["name"],
                "struct_hash": t["struct_hash"],
                "col_names": [c["name"] for c in (t.get("columns_json") or [])],
            }
            for t in self._tables.values()
        ]
        resolutions = resolve_tables(ds, current_table_dicts, existing_tables)

        aliases: List[EntityAlias] = []
        table_map: Dict[str, tuple] = {}  # new_fqn -> (old_id, old_fqn)
        for r in resolutions:
            if r.action == "renamed":
                self._session.query(CatalogTable).filter_by(id=r.entity_id).update(
                    {CatalogTable.fqn: r.fqn}, synchronize_session=False
                )
                aliases.append(EntityAlias(
                    entity_type="table", entity_id=r.entity_id, alias_fqn=r.alias_fqn,
                ))
            table_map[r.fqn] = (r.entity_id, r.old_fqn)

        orphans = detect_orphans(existing_tables, set(self._tables.keys()))
        if orphans:
            logger.info(
                "orphan_tables_detected",
                count=len(orphans), fqns=[o.fqn for o in orphans][:50],
            )

        table_ids = [t.id for t in existing_tables]
        existing_columns = (
            self._session.query(CatalogColumn)
            .filter(CatalogColumn.table_id.in_(table_ids),
                    CatalogColumn.deleted_at.is_(None))
            .all()
            if table_ids else []
        )
        existing_cols_by_table: Dict[int, list] = {}
        for c in existing_columns:
            existing_cols_by_table.setdefault(c.table_id, []).append(c)

        cur_cols_by_table: Dict[str, list] = {}
        for col_fqn, row in self._columns.items():
            cur_cols_by_table.setdefault(
                self._column_table_fqn[col_fqn], []
            ).append(row)

        for tfqn, cur_cols in cur_cols_by_table.items():
            old_id, old_fqn = table_map.get(tfqn, (None, None))
            if old_id is None or old_fqn is None:
                continue  # new table -> columns are new
            for cr in resolve_columns(
                ds, cur_cols, existing_cols_by_table.get(old_id, []),
                old_fqn, tfqn,
            ):
                if cr.entity_id is None:
                    continue
                self._session.query(CatalogColumn).filter_by(id=cr.entity_id).update(
                    {CatalogColumn.fqn: cr.fqn}, synchronize_session=False
                )
                if cr.alias_fqn and cr.alias_fqn != cr.fqn:
                    aliases.append(EntityAlias(
                        entity_type="column", entity_id=cr.entity_id,
                        alias_fqn=cr.alias_fqn,
                    ))

        for a in aliases:
            self._session.add(a)

    def close(self) -> None:
        try:
            self.flush()
        finally:
            self.disconnect()

    # -- internals ------------------------------------------------------
    def _reset_buffers(self) -> None:
        self._databases = {}
        self._schemas = {}
        self._tables = {}
        self._columns = {}
        self._column_table_fqn = {}

    def _upsert(
        self,
        model: Any,
        rows: List[Dict[str, Any]],
        update_cols: List[str],
        *,
        key_fqn: bool,
    ) -> Dict[str, int]:
        """Batch INSERT ... ON CONFLICT (fqn) WHERE deleted_at IS NULL DO UPDATE.

        Returns ``{fqn: id}`` for every row (inserted or updated). ``key_fqn``
        selects the returned key (catalog_database/schema/table return their FQN
        so children can resolve parent ids; columns do not).
        """
        if not rows:
            return {}
        stmt = pg_insert(model).values(rows)
        set_ = {col: stmt.excluded[col] for col in update_cols}
        set_["updated_at"] = func.now()
        stmt = stmt.on_conflict_do_update(
            index_elements=["fqn"],
            # index_where matches the partial unique index predicate
            # (WHERE deleted_at IS NULL) so the conflict target is recognised.
            index_where=model.deleted_at.is_(None),
            set_=set_,
        )
        result = self._session.execute(stmt.returning(model.id, model.fqn)).all()
        if key_fqn:
            return {fqn: row_id for row_id, fqn in result}
        return {}


def _parent_db(schema_fqn: str) -> str:
    return schema_fqn.split(".")[0]


def _parent_schema(table_fqn: str) -> str:
    parts = table_fqn.split(".")
    return ".".join(parts[:-1]) if len(parts) > 1 else parts[0]


def _mask(url: str) -> str:
    # Best-effort mask: keep scheme/host, drop password.
    try:
        from sqlalchemy.engine.url import make_url

        u = make_url(url)
        return u.render_as_string()
    except Exception:  # noqa: BLE001
        return url
