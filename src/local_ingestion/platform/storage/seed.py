"""T-113 data-generation: populate ``catalog_*`` at a configurable scale.

Writes a full hierarchy ``datasource -> catalog_database -> catalog_schema ->
catalog_table -> catalog_column`` so the seeded rows satisfy every foreign key and
unique constraint. Used by the ``seed`` CLI command and the PG integration tests.
"""
from __future__ import annotations

import random
from typing import Optional

from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from .models_core import (
    CatalogColumn,
    CatalogDatabase,
    CatalogSchema,
    CatalogTable,
    Datasource,
)

# Scale presets (tables, total_columns) per doc/plan/02-decisions.md D2.
SCALES = {
    "smoke": (1_000, 20_000),
    "dev": (50_000, 1_000_000),
    "perf": (300_000, 10_000_000),
}

_DATA_TYPES = [
    "integer", "bigint", "varchar(64)", "text", "boolean",
    "timestamp", "numeric(18,2)", "jsonb", "uuid", "date",
]


def seed_catalog(
    engine: Engine,
    *,
    tables: int,
    columns_per_table: int,
    datasource_code: str = "seed_ds",
    database: str = "seed_db",
    schema: str = "public",
    batch: int = 5_000,
    seed: int = 0,
    grade: bool = True,
) -> dict:
    """Insert the catalog hierarchy. Returns a small summary dict.

    ``columns_per_table`` columns are created per table; total rows scale with
    ``tables * columns_per_table``. Useful for performance validation.
    """
    rnd = random.Random(seed)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    db_fqn = database
    sch_fqn = f"{database}.{schema}"

    with Session() as s:
        ds = (
            s.query(Datasource).filter(Datasource.code == datasource_code).first()
        )
        if ds is None:
            ds = Datasource(
                tenant_id=0,
                code=datasource_code,
                name="Seed Datasource",
                ds_type="postgres",
                host="localhost",
                port=5432,
                scan_enabled=False,
            )
            s.add(ds)
            s.flush()

        cdb = (
            s.query(CatalogDatabase)
            .filter(CatalogDatabase.fqn == db_fqn, CatalogDatabase.datasource_id == ds.id)
            .first()
        )
        if cdb is None:
            cdb = CatalogDatabase(
                tenant_id=0, datasource_id=ds.id, name=database, fqn=db_fqn
            )
            s.add(cdb)
            s.flush()

        csch = (
            s.query(CatalogSchema)
            .filter(CatalogSchema.fqn == sch_fqn, CatalogSchema.datasource_id == ds.id)
            .first()
        )
        if csch is None:
            csch = CatalogSchema(
                tenant_id=0, datasource_id=ds.id, database_id=cdb.id,
                name=schema, fqn=sch_fqn,
            )
            s.add(csch)
            s.flush()

        # --- tables (flush in batches to bound memory) ---
        table_objs: list = []
        for i in range(tables):
            tfqn = f"{sch_fqn}.table_{i}"
            t = CatalogTable(
                tenant_id=0, datasource_id=ds.id, schema_id=csch.id,
                name=f"table_{i}", fqn=tfqn, table_type="table",
                column_count=columns_per_table, struct_hash=None,
                grade_level=rnd.randint(1, 9) if grade else None,
            )
            s.add(t)
            table_objs.append(t)
            if (i + 1) % batch == 0:
                s.flush()
        s.flush()

        # --- columns (bulk-saved in batches) ---
        col_objs: list = []
        written = 0
        for t in table_objs:
            for j in range(columns_per_table):
                cfqn = f"{t.fqn}.col_{j}"
                col_objs.append(
                    CatalogColumn(
                        tenant_id=0, datasource_id=ds.id, table_id=t.id,
                        name=f"col_{j}", fqn=cfqn, ordinal_position=j + 1,
                        data_type=rnd.choice(_DATA_TYPES),
                        nullable=(rnd.randint(0, 1) == 0),
                        grade_level=rnd.randint(1, 9) if grade else None,
                    )
                )
                written += 1
                if written % batch == 0:
                    s.bulk_save_objects(col_objs)
                    s.flush()
                    col_objs = []
        if col_objs:
            s.bulk_save_objects(col_objs)
            s.flush()
        s.commit()

    return {
        "datasource_id": ds.id,
        "database_id": cdb.id,
        "schema_id": csch.id,
        "tables": tables,
        "columns": tables * columns_per_table,
    }
