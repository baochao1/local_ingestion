"""Governance ORM models: profiling, quality, classification, business metadata."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    desc,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class TableProfile(Base, TimestampMixin):
    __tablename__ = "table_profile"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    datasource_id: Mapped[int] = mapped_column(ForeignKey("datasource.id"), nullable=False)
    table_id: Mapped[int] = mapped_column(ForeignKey("catalog_table.id"), nullable=False)
    row_count: Mapped[int | None] = mapped_column(BigInteger)
    column_count: Mapped[int | None] = mapped_column(Integer)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    stats: Mapped[dict] = mapped_column(JSONB, server_default="'{}'::jsonb", nullable=False)
    sample_rate: Mapped[float | None] = mapped_column(Numeric(6, 4))
    sampled_rows: Mapped[int | None] = mapped_column(BigInteger)
    profiled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, server_default="pending", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        Index("uq_profile_table", "table_id", unique=True),
        Index("idx_profile_ds", "datasource_id", desc(profiled_at)),
        CheckConstraint(
            "status IN ('pending','running','success','failed','skipped')",
            name="ck_profile_status",
        ),
    )


class QualityRule(Base, TimestampMixin):
    __tablename__ = "quality_rule"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    rule_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    definition: Mapped[dict] = mapped_column(JSONB, server_default="'{}'::jsonb", nullable=False)
    severity: Mapped[str] = mapped_column(Text, server_default="warning", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    __table_args__ = (Index("uq_qrule_code", "code", unique=True),)


class QualityResult(Base):
    __tablename__ = "quality_result"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    scan_run_id: Mapped[int | None] = mapped_column(BigInteger)
    table_id: Mapped[int] = mapped_column(ForeignKey("catalog_table.id"), nullable=False)
    column_id: Mapped[int | None] = mapped_column(ForeignKey("catalog_column.id"))
    rule_id: Mapped[int] = mapped_column(ForeignKey("quality_rule.id"), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    metric_value: Mapped[float | None] = mapped_column(Numeric)
    detail: Mapped[dict] = mapped_column(JSONB, server_default="'{}'::jsonb", nullable=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False)
    __table_args__ = (
        Index("idx_qresult_table", "table_id", desc(executed_at)),
        Index("idx_qresult_rule", "rule_id", desc(executed_at)),
    )


class ClassificationTag(Base):
    __tablename__ = "classification_tag"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    tag_key: Mapped[str] = mapped_column(Text, nullable=False)
    tag_name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(Text)
    grade_level: Mapped[int | None] = mapped_column(SmallInteger)
    grade_code: Mapped[str | None] = mapped_column(Text)
    color: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False)
    __table_args__ = (
        Index("uq_clstag_key", "tag_key", unique=True),
        Index("idx_clstag_grade", "grade_level"),
        CheckConstraint("grade_level IS NULL OR grade_level BETWEEN 1 AND 9", name="ck_clstag_grade"),
    )


class ClassificationRule(Base):
    __tablename__ = "classification_rule"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    tag_key: Mapped[str] = mapped_column(Text, nullable=False)
    rule_kind: Mapped[str] = mapped_column(Text, nullable=False)
    pattern: Mapped[str | None] = mapped_column(Text)
    options: Mapped[dict] = mapped_column(JSONB, server_default="'{}'::jsonb", nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), server_default="0.8", nullable=False)
    priority: Mapped[int] = mapped_column(Integer, server_default="100", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False)
    __table_args__ = (Index("idx_clsrule_tag", "tag_key", "enabled"),)


class EntityTag(Base):
    __tablename__ = "entity_tag"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    entity_fqn: Mapped[str | None] = mapped_column(Text)
    tag_key: Mapped[str] = mapped_column(Text, nullable=False)
    grade_level: Mapped[int | None] = mapped_column(SmallInteger)
    source: Mapped[str] = mapped_column(Text, nullable=False, comment="manual 来源的标签，自动引擎不得覆盖（FR-9.5）")
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    applied_by: Mapped[str | None] = mapped_column(Text)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        Index("uq_etag_entity_tag", "entity_type", "entity_id", "tag_key", unique=True, postgresql_where="deleted_at IS NULL"),
        Index("idx_etag_entity", "entity_type", "entity_id", postgresql_where="deleted_at IS NULL"),
        Index("idx_etag_key", "tag_key", postgresql_where="deleted_at IS NULL"),
        Index("idx_etag_grade", "grade_level", postgresql_where="deleted_at IS NULL"),
        CheckConstraint("entity_type IN ('database','schema','table','column')", name="ck_etag_type"),
        CheckConstraint("source IN ('rule','sample','manual')", name="ck_etag_source"),
    )


class TableProfileHistory(Base):
    __tablename__ = "table_profile_history"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    profiled_date: Mapped[date] = mapped_column(Date, primary_key=True)
    table_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    datasource_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    row_count: Mapped[int | None] = mapped_column(BigInteger)
    stats: Mapped[dict] = mapped_column(JSONB, server_default="'{}'::jsonb", nullable=False)
    quality_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    profiled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False)
    __table_args__ = (
        Index("idx_prof_hist_table", "table_id", desc(profiled_date)),
        {"postgresql_partition_by": "RANGE (profiled_date)"},
    )


class BusinessTerm(Base, TimestampMixin):
    __tablename__ = "business_term"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    term_code: Mapped[str] = mapped_column(Text, nullable=False)
    term_name: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str | None] = mapped_column(Text)
    definition: Mapped[str | None] = mapped_column(Text)
    owner: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="active", nullable=False)
    __table_args__ = (Index("uq_bterm_code", "term_code", unique=True),)


class BusinessMetadata(Base, TimestampMixin):
    __tablename__ = "business_metadata"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    alias: Mapped[str | None] = mapped_column(Text)
    business_desc: Mapped[str | None] = mapped_column(Text)
    domain: Mapped[str | None] = mapped_column(Text)
    owner_business: Mapped[str | None] = mapped_column(Text)
    term_codes: Mapped[list] = mapped_column(JSONB, server_default="'[]'::jsonb", nullable=False)
    tags: Mapped[dict] = mapped_column(JSONB, server_default="'{}'::jsonb", nullable=False)
    __table_args__ = (
        Index("uq_bmeta_entity", "entity_type", "entity_id", unique=True),
        Index("idx_bmeta_domain", "domain"),
        Index("idx_bmeta_alias", "alias", postgresql_using="gin", postgresql_ops={"alias": "gin_trgm_ops"}),
        Index("idx_bmeta_tags", "tags", postgresql_using="gin", postgresql_ops={"tags": "jsonb_path_ops"}),
    )


__all__ = [
    "TableProfile", "QualityRule", "QualityResult", "ClassificationTag",
    "ClassificationRule", "EntityTag", "TableProfileHistory", "BusinessTerm",
    "BusinessMetadata",
]
