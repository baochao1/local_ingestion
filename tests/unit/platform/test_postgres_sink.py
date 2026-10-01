"""T-105 PostgresSink tests.

Pure-unit tests (field mapping, struct_hash, FQN helpers) run anywhere.
Database-backed tests are skipped unless ``DATABASE_URL`` is reachable (e.g.
the local ``li-pg`` container running the migrated ``ddlbasis`` database).
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, delete, text
from sqlalchemy.orm import sessionmaker

from local_ingestion.platform.sinks.postgres import (
    PostgresSink,
    PostgresSinkConfig,
    _column_public,
    _parent_db,
    _parent_schema,
    _struct_hash,
)
from local_ingestion.platform.storage.models_core import (
    CatalogColumn,
    CatalogDatabase,
    CatalogTable,
    Datasource,
)
from local_ingestion.schema.base import DataType
from local_ingestion.schema.data.database import Database
from local_ingestion.schema.data.table import Column, Table


def _make_sink() -> PostgresSink:
    sink = PostgresSink()
    # config is needed by write_* for tenant/datasource ids and dialect.
    sink._config = PostgresSinkConfig(datasource_id=1, ds_type="postgres")
    return sink


def test_column_field_mapping_translates_names():
    sink = _make_sink()
    col = Column(
        name="amount",
        dataType=DataType.DECIMAL,
        dataTypeDisplay="numeric(12,4)",
        dataLength=None,
        precision=12,
        scale=4,
        nullable=False,
        ordinalPosition=3,
        default="0",
        description="金额",
    )
    public = _column_public(col, sink._config)
    assert public["name"] == "amount"
    assert public["dataType"] == "DECIMAL"
    assert public["dataTypeDisplay"] == "numeric(12,4)"
    assert public["dataLength"] is None
    assert public["precision"] == 12
    assert public["scale"] == 4
    assert public["nullable"] is False
    assert public["ordinalPosition"] == 3
    assert public["default"] == "0"
    assert public["description"] == "金额"


def test_column_type_fallback_via_dialect():
    sink = _make_sink()
    # Source connector returned UNKNOWN but left a display type.
    col = Column(name="c", dataType=DataType.UNKNOWN, dataTypeDisplay="varchar(255)")
    public = _column_public(col, sink._config)
    assert public["dataType"] == "STRING"  # resolved by PostgresDialect


def test_struct_hash_stable_and_sensitive():
    cols_a = [Column(name="a", dataType=DataType.INTEGER, ordinalPosition=1, nullable=True)]
    cols_b = [Column(name="a", dataType=DataType.INTEGER, ordinalPosition=1, nullable=True)]
    assert _struct_hash(cols_a) == _struct_hash(cols_b)
    cols_c = [Column(name="a", dataType=DataType.BIGINT, ordinalPosition=1, nullable=True)]
    assert _struct_hash(cols_a) != _struct_hash(cols_c)


def test_parent_helpers():
    assert _parent_db("db.schema.table") == "db"
    assert _parent_schema("db.schema.table") == "db.schema"
    assert _parent_schema("db.table") == "db"


# --------------------------------------------------------------------------
# DB-backed tests (skipped without a reachable DATABASE_URL)
# --------------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL")


def _db_available() -> bool:
    if not DATABASE_URL:
        return False
    try:
        eng = create_engine(DATABASE_URL)
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        eng.dispose()
        return True
    except Exception:  # noqa: BLE001
        return False


_DB_SKIP = pytest.mark.skipif(
    not _db_available(),
    reason="DATABASE_URL not reachable (start the li-pg container & set DATABASE_URL)",
)


@pytest.fixture()
def sink_session():
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()
    ds_id = 991001
    session.execute(
        delete(CatalogColumn).where(CatalogColumn.datasource_id == ds_id)
    )
    session.execute(delete(CatalogTable).where(CatalogTable.datasource_id == ds_id))
    session.execute(delete(CatalogDatabase).where(CatalogDatabase.datasource_id == ds_id))
    session.execute(delete(Datasource).where(Datasource.id == ds_id))
    session.commit()
    session.add(Datasource(id=ds_id, code="t105_ds", name="t105", ds_type="postgres"))
    session.commit()

    sink = PostgresSink()
    sink.connect(PostgresSinkConfig(datasource_id=ds_id, ds_type="postgres"))
    yield sink, session, ds_id

    session.rollback()
    session.execute(delete(CatalogColumn).where(CatalogColumn.datasource_id == ds_id))
    session.execute(delete(CatalogTable).where(CatalogTable.datasource_id == ds_id))
    session.execute(delete(CatalogDatabase).where(CatalogDatabase.datasource_id == ds_id))
    session.execute(delete(Datasource).where(Datasource.id == ds_id))
    session.commit()
    sink.close()
    engine.dispose()


@_DB_SKIP
def test_write_persists_catalog_rows(sink_session):
    sink, session, ds_id = sink_session
    db = Database(name="shop", fullyQualifiedName="shop", description="db desc")
    table = Table(
        name="orders",
        fullyQualifiedName="shop.public.orders",
        database="shop",
        databaseSchema="public",
        tableType="TABLE",
        description="orders table",
        columns=[
            Column(name="id", dataType=DataType.BIGINT, ordinalPosition=1, nullable=False),
            Column(name="amt", dataType=DataType.DECIMAL, dataTypeDisplay="numeric(10,2)",
                   precision=10, scale=2, ordinalPosition=2, nullable=True),
        ],
    )
    sink.write_database(db)
    sink.write_table(table)
    sink.flush()

    db_row = session.execute(
        text("SELECT fqn, name, description FROM catalog_database WHERE datasource_id=:d"),
        {"d": ds_id},
    ).fetchone()
    assert db_row is not None and db_row[0] == "shop"

    tbl_row = session.execute(
        text("SELECT fqn, table_type, column_count, struct_hash, grade_level "
             "FROM catalog_table WHERE datasource_id=:d"),
        {"d": ds_id},
    ).fetchone()
    assert tbl_row[0] == "shop.public.orders"
    assert tbl_row[1] == "TABLE"
    assert tbl_row[2] == 2
    assert tbl_row[3] is not None
    assert tbl_row[4] is None  # grade_level protected (MOD-05 owns it)

    col_rows = session.execute(
        text("SELECT fqn, data_type, numeric_precision, numeric_scale, nullable "
             "FROM catalog_column WHERE datasource_id=:d ORDER BY ordinal_position"),
        {"d": ds_id},
    ).fetchall()
    assert len(col_rows) == 2
    assert col_rows[0][0] == "shop.public.orders.id"
    assert col_rows[0][1] == "BIGINT"
    assert col_rows[1][1] == "DECIMAL" and col_rows[1][2] == 10 and col_rows[1][3] == 2


@_DB_SKIP
def test_flush_is_idempotent(sink_session):
    sink, session, ds_id = sink_session
    db = Database(name="shop2", fullyQualifiedName="shop2")
    table = Table(
        name="t",
        fullyQualifiedName="shop2.public.t",
        columns=[Column(name="id", dataType=DataType.INTEGER, ordinalPosition=1)],
    )
    sink.write_database(db)
    sink.write_table(table)
    sink.flush()
    first_count = session.execute(
        text("SELECT count(*) FROM catalog_table WHERE datasource_id=:d"), {"d": ds_id}
    ).scalar()

    # Re-run the same scan: should upsert, not duplicate.
    sink.write_database(db)
    sink.write_table(table)
    sink.flush()
    second_count = session.execute(
        text("SELECT count(*) FROM catalog_table WHERE datasource_id=:d"), {"d": ds_id}
    ).scalar()
    assert second_count == first_count == 1
