"""Ops/platform ORM models: scans, snapshots, lineage, accounts, sampling, audit, RBAC."""
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
    Text,
    desc,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy import LargeBinary
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, SoftDeleteMixin, TimestampMixin


class ScanRun(Base):
    __tablename__ = "scan_run"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    datasource_id: Mapped[int | None] = mapped_column(ForeignKey("datasource.id"))
    job_type: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_type: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="pending", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    stats: Mapped[dict] = mapped_column(JSONB, server_default="'{}'::jsonb", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False)
    __table_args__ = (
        Index("idx_scanrun_ds", "datasource_id", desc(created_at)),
        Index("idx_scanrun_type_status", "job_type", "status", desc(created_at)),
    )


class TableSnapshot(Base):
    __tablename__ = "table_snapshot"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, primary_key=True)
    scan_run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    datasource_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    table_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fqn: Mapped[str] = mapped_column(Text, nullable=False)
    struct_hash: Mapped[str | None] = mapped_column(Text)
    snapshot_json: Mapped[dict] = mapped_column(JSONB, server_default="'{}'::jsonb", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False)
    __table_args__ = (
        Index("idx_tsnap_run", "scan_run_id"),
        Index("idx_tsnap_table", "table_id", desc(snapshot_date)),
        {"postgresql_partition_by": "RANGE (snapshot_date)"},
    )


class ColumnSnapshot(Base):
    __tablename__ = "column_snapshot"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, primary_key=True)
    scan_run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    datasource_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    table_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    column_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fqn: Mapped[str] = mapped_column(Text, nullable=False)
    ordinal_position: Mapped[int | None] = mapped_column(Integer)
    struct_hash: Mapped[str | None] = mapped_column(Text)
    snapshot_json: Mapped[dict] = mapped_column(JSONB, server_default="'{}'::jsonb", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False)
    __table_args__ = (
        Index("idx_csnap_run", "scan_run_id"),
        Index("idx_csnap_column", "column_id", desc(snapshot_date)),
        {"postgresql_partition_by": "RANGE (snapshot_date)"},
    )


class ChangeEvent(Base):
    __tablename__ = "change_event"
    # Composite PK (id, detected_at) on a partitioned table; ``id`` is a PG
    # IDENTITY column, so autoincrement must be declared explicitly for the ORM
    # to fetch the generated value back on INSERT ... RETURNING.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False, primary_key=True)
    scan_run_id: Mapped[int | None] = mapped_column(BigInteger)
    datasource_id: Mapped[int | None] = mapped_column(BigInteger)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[int | None] = mapped_column(BigInteger)
    entity_fqn: Mapped[str | None] = mapped_column(Text)
    change_type: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    before_json: Mapped[dict | None] = mapped_column(JSONB)
    after_json: Mapped[dict | None] = mapped_column(JSONB)
    notified: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    # T-204 change-confirmation closure (FR-7.9)
    ack_status: Mapped[str] = mapped_column(Text, server_default="pending", nullable=False)
    ack_action: Mapped[str | None] = mapped_column(Text)
    ack_by: Mapped[str | None] = mapped_column(Text)
    ack_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False)
    __table_args__ = (
        Index("idx_change_run", "scan_run_id"),
        Index("idx_change_sev", "severity", desc(detected_at)),
        Index("idx_change_entity", "entity_type", "entity_fqn", desc(detected_at)),
        Index("idx_change_ack", "ack_status", desc(detected_at)),
        CheckConstraint("change_type IN ('table_added','table_removed','table_renamed','column_added','column_removed','column_renamed','type_changed','nullable_changed','comment_changed')", name="ck_change_type"),
        CheckConstraint("severity IN ('breaking','structural','descriptive')", name="ck_change_sev"),
        CheckConstraint("ack_status IN ('pending','closed')", name="ck_change_ack"),
        {"postgresql_partition_by": "RANGE (detected_at)"},
    )


class LineageTableEdge(Base, SoftDeleteMixin):
    __tablename__ = "lineage_table_edge"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    src_fqn: Mapped[str] = mapped_column(Text, nullable=False)
    tgt_fqn: Mapped[str] = mapped_column(Text, nullable=False)
    src_table_id: Mapped[int | None] = mapped_column(BigInteger)
    tgt_table_id: Mapped[int | None] = mapped_column(BigInteger)
    edge_source: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), server_default="1.0", nullable=False)
    properties: Mapped[dict] = mapped_column(JSONB, server_default="'{}'::jsonb", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False)
    __table_args__ = (
        Index("uq_lte_edge", "src_fqn", "tgt_fqn", unique=True, postgresql_where="deleted_at IS NULL"),
        Index("idx_lte_src", "src_fqn", postgresql_where="deleted_at IS NULL"),
        Index("idx_lte_tgt", "tgt_fqn", postgresql_where="deleted_at IS NULL"),
    )


class LineageColumnEdge(Base, SoftDeleteMixin):
    __tablename__ = "lineage_column_edge"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    src_fqn: Mapped[str] = mapped_column(Text, nullable=False)
    tgt_fqn: Mapped[str] = mapped_column(Text, nullable=False)
    src_column_id: Mapped[int | None] = mapped_column(BigInteger)
    tgt_column_id: Mapped[int | None] = mapped_column(BigInteger)
    edge_source: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), server_default="1.0", nullable=False)
    transform_expr: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False)
    __table_args__ = (
        Index("uq_lce_edge", "src_fqn", "tgt_fqn", unique=True, postgresql_where="deleted_at IS NULL"),
        Index("idx_lce_src", "src_fqn", postgresql_where="deleted_at IS NULL"),
        Index("idx_lce_tgt", "tgt_fqn", postgresql_where="deleted_at IS NULL"),
    )


class LineageClosure(Base):
    __tablename__ = "lineage_closure"
    ancestor_fqn: Mapped[str] = mapped_column(Text, primary_key=True)
    descendant_fqn: Mapped[str] = mapped_column(Text, primary_key=True)
    depth: Mapped[int] = mapped_column(Integer, nullable=False)
    edge_count: Mapped[int] = mapped_column(Integer, server_default="1", nullable=False)
    rebuilt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False)
    __table_args__ = (
        Index("idx_lclos_anc", "ancestor_fqn", "depth"),
        Index("idx_lclos_desc", "descendant_fqn", "depth"),
    )


class Account(Base, SoftDeleteMixin):
    __tablename__ = "account"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    datasource_id: Mapped[int] = mapped_column(ForeignKey("datasource.id"), nullable=False)
    account_name: Mapped[str] = mapped_column(Text, nullable=False)
    account_type: Mapped[str | None] = mapped_column(Text)
    host_pattern: Mapped[str | None] = mapped_column(Text)
    is_super: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    is_locked: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    properties: Mapped[dict] = mapped_column(JSONB, server_default="'{}'::jsonb", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False)
    __table_args__ = (
        Index("uq_account", "datasource_id", "account_name", "host_pattern", unique=True, postgresql_where="deleted_at IS NULL"),
    )


class AccountGrant(Base, SoftDeleteMixin):
    __tablename__ = "account_grant"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    datasource_id: Mapped[int] = mapped_column(ForeignKey("datasource.id"), nullable=False)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("account.id"))
    privilege: Mapped[str] = mapped_column(Text, nullable=False)
    object_type: Mapped[str] = mapped_column(Text, nullable=False)
    object_fqn: Mapped[str] = mapped_column(Text, nullable=False)
    grantable: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False)
    __table_args__ = (
        Index("idx_grant_account", "account_id", postgresql_where="deleted_at IS NULL"),
        Index("idx_grant_object", "object_fqn", postgresql_where="deleted_at IS NULL"),
        Index("idx_grant_ds", "datasource_id", "privilege", postgresql_where="deleted_at IS NULL"),
    )


class SampleValue(Base):
    __tablename__ = "sample_value"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sampled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False, primary_key=True)
    column_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    value_masked: Mapped[str | None] = mapped_column(Text)
    value_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    value_hash: Mapped[str | None] = mapped_column(Text)
    sampled_by: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        Index("idx_sample_column", "column_id", desc(sampled_at)),
        Index("idx_sample_expire", "expires_at"),
        {"postgresql_partition_by": "RANGE (sampled_at)"},
    )


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    actor: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str | None] = mapped_column(Text)
    entity_fqn: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict] = mapped_column(JSONB, server_default="'{}'::jsonb", nullable=False)
    client_ip: Mapped[str | None] = mapped_column(INET)
    result: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        Index("idx_audit_action", "action", desc(occurred_at)),
        Index("idx_audit_entity", "entity_type", "entity_fqn", desc(occurred_at)),
        {"postgresql_partition_by": "RANGE (occurred_at)"},
    )


class NotificationSubscription(Base):
    __tablename__ = "notification_subscription"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    subscriber: Mapped[str] = mapped_column(Text, nullable=False)
    scope_type: Mapped[str] = mapped_column(Text, nullable=False)
    scope_fqn: Mapped[str | None] = mapped_column(Text)
    # 订阅可限定到数据源（领域模型 SubscriptionView.datasource_id）
    datasource_id: Mapped[int | None] = mapped_column(BigInteger)
    min_severity: Mapped[str] = mapped_column(Text, server_default="structural", nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    channel_conf: Mapped[dict] = mapped_column(JSONB, server_default="'{}'::jsonb", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False)
    __table_args__ = (
        Index("idx_notisub_scope", "scope_type", "scope_fqn", postgresql_where="enabled"),
    )


class NotificationLog(Base):
    __tablename__ = "notification_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    change_id: Mapped[int | None] = mapped_column(BigInteger)
    subscription_id: Mapped[int | None] = mapped_column(BigInteger)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False)
    __table_args__ = (Index("idx_notilog_change", "change_id"),)


class AppUser(Base):
    __tablename__ = "app_user"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    username: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    credential_hash: Mapped[str | None] = mapped_column(Text)
    auth_source: Mapped[str] = mapped_column(Text, server_default="local", nullable=False)
    external_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="active", nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False)
    __table_args__ = (Index("uq_appuser_name", "tenant_id", "username", unique=True),)


class Role(Base):
    __tablename__ = "role"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    role_code: Mapped[str] = mapped_column(Text, nullable=False)
    role_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False)
    __table_args__ = (Index("uq_role_code", "tenant_id", "role_code", unique=True),)


class Permission(Base):
    __tablename__ = "permission"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    perm_code: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (Index("uq_perm_code", "perm_code", unique=True),)


class RolePermission(Base):
    __tablename__ = "role_permission"
    role_id: Mapped[int] = mapped_column(ForeignKey("role.id"), primary_key=True)
    permission_id: Mapped[int] = mapped_column(ForeignKey("permission.id"), primary_key=True)


class UserRole(Base):
    __tablename__ = "user_role"
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("role.id"), primary_key=True)


class DataPolicy(Base):
    __tablename__ = "data_policy"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    subject_type: Mapped[str] = mapped_column(Text, nullable=False)
    subject_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    scope_type: Mapped[str] = mapped_column(Text, nullable=False)
    scope_fqn: Mapped[str] = mapped_column(Text, nullable=False)
    effect: Mapped[str] = mapped_column(Text, server_default="allow", nullable=False)
    actions: Mapped[list] = mapped_column(JSONB, server_default="'[\"read\"]'::jsonb", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False)
    __table_args__ = (
        Index("idx_dpolicy_subject", "subject_type", "subject_id"),
        Index("idx_dpolicy_scope", "scope_type", "scope_fqn"),
    )


class AccountUserMapping(Base):
    __tablename__ = "account_user_mapping"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False)
    __table_args__ = (Index("uq_acctuser", "account_id", "user_id", unique=True),)


# ---------------------------------------------------------------------------
# MOD-12 governance process: approvals + tickets (collaborative workflow)
# ---------------------------------------------------------------------------
class ApprovalRequest(Base):
    __tablename__ = "approval_request"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    resource_type: Mapped[str] = mapped_column(Text, nullable=False)
    resource_fqn: Mapped[str] = mapped_column(Text, nullable=False)
    action_type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    requested_by: Mapped[str] = mapped_column(Text, nullable=False)
    approver: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="pending", nullable=False)
    priority: Mapped[str] = mapped_column(Text, server_default="P2", nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[str | None] = mapped_column(Text)
    decided_comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False)
    __table_args__ = (
        Index("idx_approval_status", "status", desc(created_at)),
        Index("idx_approval_resource", "resource_type", "resource_fqn"),
        Index("idx_approval_approver", "approver"),
        CheckConstraint(
            "status IN ('pending','approved','rejected')", name="ck_approval_status"),
        CheckConstraint(
            "action_type IN ('publish','classify','sensitive_tag','delete')",
            name="ck_approval_action"),
    )


class GovernanceTicket(Base):
    __tablename__ = "governance_ticket"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    ticket_type: Mapped[str] = mapped_column(Text, server_default="data_issue", nullable=False)
    priority: Mapped[str] = mapped_column(Text, server_default="P2", nullable=False)
    status: Mapped[str] = mapped_column(Text, server_default="open", nullable=False)
    reporter: Mapped[str] = mapped_column(Text, nullable=False)
    assignee: Mapped[str | None] = mapped_column(Text)
    related_fqn: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, server_default="manual", nullable=False)
    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False)
    __table_args__ = (
        Index("idx_ticket_status", "status", desc(created_at)),
        Index("idx_ticket_type", "ticket_type"),
        Index("idx_ticket_assignee", "assignee"),
        Index("idx_ticket_related", "related_fqn"),
        CheckConstraint(
            "status IN ('open','in_progress','resolved','closed')", name="ck_ticket_status"),
        CheckConstraint(
            "ticket_type IN ('data_issue','access_request','change_auto','other')",
            name="ck_ticket_type"),
    )


class GovernanceComment(Base):
    __tablename__ = "governance_comment"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    target_type: Mapped[str] = mapped_column(Text, nullable=False)  # approval | ticket
    target_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    author: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False)
    __table_args__ = (
        Index("idx_gcomment_target", "target_type", "target_id", desc(created_at)),
        CheckConstraint("target_type IN ('approval','ticket')", name="ck_gcomment_target"),
    )


__all__ = [
    "ScanRun", "TableSnapshot", "ColumnSnapshot", "ChangeEvent", "LineageTableEdge",
    "LineageColumnEdge", "LineageClosure", "Account", "AccountGrant", "SampleValue",
    "AuditLog", "NotificationSubscription", "NotificationLog", "AppUser", "Role",
    "Permission", "RolePermission", "UserRole", "DataPolicy", "AccountUserMapping",
    "ApprovalRequest", "GovernanceTicket", "GovernanceComment",
]
