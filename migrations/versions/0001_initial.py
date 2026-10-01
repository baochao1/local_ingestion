"""initial schema

Replays the reviewed DDL in ``doc/design/02-schema-ddl.sql`` so the database
matches the ORM models exactly. This is the only hand-written migration; all
later schema changes are produced by ``alembic revision --autogenerate``.

Revision ID: 0001
Revises:
Create Date: 2026-09-30
"""
from alembic import op
from sqlalchemy import text

import os

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_DDL_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "doc", "design", "02-schema-ddl.sql"
)


def upgrade() -> None:
    with open(_DDL_PATH, "r", encoding="utf-8") as fh:
        sql = fh.read()
    # The DDL is wrapped in BEGIN/COMMIT; Alembic already runs inside a
    # transaction, so strip those markers. Use exec_driver_sql (not
    # op.execute(text(...))) because the DDL is full of PostgreSQL "::type"
    # casts that text() would misinterpret as bound parameters.
    sql = sql.replace("BEGIN;", "").replace("COMMIT;", "")
    op.get_bind().exec_driver_sql(sql)


def downgrade() -> None:
    tables = [
        "account_user_mapping", "data_policy", "user_role", "role_permission",
        "permission", "role", "app_user", "notification_log",
        "notification_subscription", "audit_log", "sample_value", "account_grant",
        "account", "lineage_closure", "lineage_column_edge", "lineage_table_edge",
        "change_event", "column_snapshot", "table_snapshot", "scan_run",
        "business_metadata", "business_term", "table_profile_history",
        "entity_tag", "classification_rule", "classification_tag", "quality_result",
        "quality_rule", "table_profile", "entity_alias", "catalog_column",
        "catalog_table", "catalog_schema", "catalog_database",
        "datasource_credential", "datasource", "tenant",
    ]
    for t in tables:
        op.execute(text(f'DROP TABLE IF EXISTS "{t}" CASCADE'))
