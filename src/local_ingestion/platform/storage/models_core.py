"""Core catalog ORM models: tenant, datasource, catalog entities, aliases.

Field names, types and constraints mirror ``doc/design/02-schema-ddl.sql``.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    desc,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import LargeBinary
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, SoftDeleteMixin, TimestampMixin


class Tenant(Base):
    __tablename__ = "tenant"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False)
    __table_args__ = (Index("uq_tenant_code", "code", unique=True),)


class Datasource(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "datasource"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    ds_type: Mapped[str] = mapped_column(Text, nullable=False)
    host: Mapped[str | None] = mapped_column(Text)
    port: Mapped[int | None] = mapped_column(Integer)
    environment: Mapped[str | None] = mapped_column(Text)
    group_name: Mapped[str | None] = mapped_column(Text)
    owner_business: Mapped[str | None] = mapped_column(Text)
    owner_technical: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    scan_enabled: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    sampling_enabled: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    scan_config: Mapped[dict] = mapped_column(JSONB, server_default="'{}'::jsonb", nullable=False, comment="采集策略：黑白名单、并发、调度")
    sampling_config: Mapped[dict] = mapped_column(JSONB, server_default="'{}'::jsonb", nullable=False, comment="采样策略：采样率、上限、超时、大表熔断阈值、敏感列黑名单")
    supports_sampling: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False, comment="MySQL 无 TABLESAMPLE，需由方言层置位并走替代策略")
    supports_lineage: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    supports_profiling: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_scan_status: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        Index("uq_datasource_code", "code", unique=True, postgresql_where="deleted_at IS NULL"),
        Index("idx_datasource_tenant", "tenant_id", postgresql_where="deleted_at IS NULL"),
        CheckConstraint(
            "ds_type IN ('mysql','mariadb','postgres','postgresql',"
            "'snowflake','sqlserver','bigquery','other')",
            name="ck_datasource_type",
        ),
    )


class DatasourceCredential(Base):
    __tablename__ = "datasource_credential"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    datasource_id: Mapped[int] = mapped_column(ForeignKey("datasource.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, server_default="1", nullable=False)
    username: Mapped[str | None] = mapped_column(Text)
    credential_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    enc_algo: Mapped[str] = mapped_column(Text, server_default="AES-256-GCM", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False)
    __table_args__ = (
        Index("uq_dscred_active", "datasource_id", unique=True, postgresql_where="is_active"),
        Index("idx_dscred_ds", "datasource_id", desc(version)),
    )


class CatalogDatabase(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "catalog_database"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    datasource_id: Mapped[int] = mapped_column(ForeignKey("datasource.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    fqn: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    owner: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSONB, server_default="'[]'::jsonb", nullable=False)
    properties: Mapped[dict] = mapped_column(JSONB, server_default="'{}'::jsonb", nullable=False)
    __table_args__ = (
        Index("uq_catdb_fqn", "fqn", unique=True, postgresql_where="deleted_at IS NULL"),
        Index("idx_catdb_ds", "datasource_id", postgresql_where="deleted_at IS NULL"),
    )


class CatalogSchema(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "catalog_schema"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    datasource_id: Mapped[int] = mapped_column(ForeignKey("datasource.id"), nullable=False)
    database_id: Mapped[int] = mapped_column(ForeignKey("catalog_database.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    fqn: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    owner: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSONB, server_default="'[]'::jsonb", nullable=False)
    properties: Mapped[dict] = mapped_column(JSONB, server_default="'{}'::jsonb", nullable=False)
    __table_args__ = (
        Index("uq_catsch_fqn", "fqn", unique=True, postgresql_where="deleted_at IS NULL"),
        Index("idx_catsch_db", "database_id", postgresql_where="deleted_at IS NULL"),
        Index("idx_catsch_ds", "datasource_id", postgresql_where="deleted_at IS NULL"),
    )


class CatalogTable(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "catalog_table"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    datasource_id: Mapped[int] = mapped_column(ForeignKey("datasource.id"), nullable=False)
    schema_id: Mapped[int] = mapped_column(ForeignKey("catalog_schema.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    fqn: Mapped[str] = mapped_column(Text, nullable=False)
    table_type: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    owner: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSONB, server_default="'[]'::jsonb", nullable=False)
    properties: Mapped[dict] = mapped_column(JSONB, server_default="'{}'::jsonb", nullable=False)
    columns_json: Mapped[list] = mapped_column(JSONB, server_default="'[]'::jsonb", nullable=False, comment="字段冗余缓存，以 catalog_column 为准，可由重建任务按 table_id 重刷")
    column_count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    struct_hash: Mapped[str | None] = mapped_column(Text, comment="md5(按 ordinal 拼接的字段签名)，用于增量判定与 Diff 前置过滤")
    grade_level: Mapped[int | None] = mapped_column(SmallInteger)
    grade_code: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        Index("uq_cattab_fqn", "fqn", unique=True, postgresql_where="deleted_at IS NULL"),
        Index("idx_cattab_keyset", "fqn", "id", postgresql_where="deleted_at IS NULL"),
        Index("idx_cattab_ds_keyset", "datasource_id", "fqn", "id", postgresql_where="deleted_at IS NULL"),
        Index("idx_cattab_schema", "schema_id", "name", postgresql_where="deleted_at IS NULL"),
        Index("idx_cattab_grade", "grade_level", postgresql_where="deleted_at IS NULL"),
        Index("idx_cattab_name_trgm", "name", postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}),
        Index("idx_cattab_tags", "tags", postgresql_using="gin", postgresql_ops={"tags": "jsonb_path_ops"}),
        CheckConstraint("grade_level IS NULL OR grade_level BETWEEN 1 AND 9", name="ck_table_grade"),
    )


class CatalogColumn(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "catalog_column"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    datasource_id: Mapped[int] = mapped_column(ForeignKey("datasource.id"), nullable=False)
    table_id: Mapped[int] = mapped_column(ForeignKey("catalog_table.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    fqn: Mapped[str] = mapped_column(Text, nullable=False)
    ordinal_position: Mapped[int | None] = mapped_column(Integer)
    data_type: Mapped[str | None] = mapped_column(Text)
    data_type_display: Mapped[str | None] = mapped_column(Text)
    data_length: Mapped[int | None] = mapped_column(Integer)
    numeric_precision: Mapped[int | None] = mapped_column(Integer)
    numeric_scale: Mapped[int | None] = mapped_column(Integer)
    nullable: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    default_value: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    children: Mapped[list] = mapped_column(JSONB, server_default="'[]'::jsonb", nullable=False)
    tags: Mapped[list] = mapped_column(JSONB, server_default="'[]'::jsonb", nullable=False)
    properties: Mapped[dict] = mapped_column(JSONB, server_default="'{}'::jsonb", nullable=False)
    struct_hash: Mapped[str | None] = mapped_column(Text)
    grade_level: Mapped[int | None] = mapped_column(SmallInteger)
    grade_code: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        Index("uq_catcol_fqn", "fqn", unique=True, postgresql_where="deleted_at IS NULL"),
        Index("idx_catcol_keyset", "fqn", "id", postgresql_where="deleted_at IS NULL"),
        Index("idx_catcol_ds_keyset", "datasource_id", "fqn", "id", postgresql_where="deleted_at IS NULL"),
        Index("idx_catcol_table", "table_id", "ordinal_position", postgresql_where="deleted_at IS NULL"),
        Index("idx_catcol_grade", "grade_level", postgresql_where="deleted_at IS NULL"),
        Index("idx_catcol_datatype", "data_type", postgresql_where="deleted_at IS NULL"),
        Index("idx_catcol_name_trgm", "name", postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}),
        Index("idx_catcol_tags", "tags", postgresql_using="gin", postgresql_ops={"tags": "jsonb_path_ops"}),
        CheckConstraint("grade_level IS NULL OR grade_level BETWEEN 1 AND 9", name="ck_column_grade"),
    )


class EntityAlias(Base):
    __tablename__ = "entity_alias"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    alias_fqn: Mapped[str] = mapped_column(Text, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False)
    __table_args__ = (
        Index("uq_alias", "entity_type", "alias_fqn", unique=True),
        Index("idx_alias_entity", "entity_type", "entity_id"),
    )


__all__ = [
    "Tenant", "Datasource", "DatasourceCredential", "CatalogDatabase",
    "CatalogSchema", "CatalogTable", "CatalogColumn", "EntityAlias",
]
