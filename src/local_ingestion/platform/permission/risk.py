"""Risk rules for account/grant analysis (MOD-08, FR-6.3). Pure & testable.

Mirrors Atlas/Collibra/Alation permission-governance capabilities: super-account
detection, excessive privileges, zombie (dormant) accounts, orphan accounts (no
owner mapping), and high-sensitivity asset authorization (GB/T 43697 + 等保).
"""
from __future__ import annotations

from datetime import datetime, timezone

EXCESSIVE_PRIVILEGES = {"INSERT", "UPDATE", "DELETE", "TRUNCATE", "CREATE", "DROP", "ALTER", "ALL"}
HIGH_GRADE_THRESHOLD = 3  # grade_level >= 3 == 重要/核心 (GB/T 43697 mapping)


def evaluate_risks(
    accounts: list[dict],
    grants: list[dict],
    grade_lookup: dict[str, int] | None = None,
    *,
    dormant_days: int = 180,
    orphan_check=None,
) -> list[dict]:
    """Return a list of risk items.

    ``accounts``: [{name, is_super, is_locked, last_login_at}].
    ``grants``:  [{account, privilege, object_type, object_fqn}].
    ``grade_lookup``: object_fqn -> grade_level (from MOD-05 classification).
    ``orphan_check``: optional callable(name) -> bool (True if mapped to an owner).
    """
    grade_lookup = grade_lookup or {}
    risks: list[dict] = []
    acct_names = {a["name"] for a in accounts}

    for a in accounts:
        name = a["name"]
        if a.get("is_super"):
            risks.append({"type": "super", "account": name, "severity": "high",
                          "detail": "具备实例级超级权限（ALL PRIVILEGES / 超级角色）"})
        if a.get("is_locked"):
            risks.append({"type": "locked", "account": name, "severity": "info",
                          "detail": "账号已锁定"})
        last = a.get("last_login_at")
        if last is None:
            risks.append({"type": "dormant", "account": name, "severity": "medium",
                          "detail": "无登录记录（PG 原生不记录 last_login）"})
        elif isinstance(last, datetime) and (datetime.now(timezone.utc) - last).days > dormant_days:
            risks.append({"type": "dormant", "account": name, "severity": "medium",
                          "detail": f"超过 {dormant_days} 天未登录"})
        if orphan_check is not None and not orphan_check(name):
            risks.append({"type": "orphan", "account": name, "severity": "medium",
                          "detail": "未关联责任人 / 平台用户（无主账号）"})

    by_acct: dict[str, list] = {}
    for g in grants:
        by_acct.setdefault(g.get("account") or _owner_of(g), []).append(g)

    for acct, gs in by_acct.items():
        if acct not in acct_names:
            continue
        for g in gs:
            priv = (g.get("privilege") or "").upper()
            if priv in EXCESSIVE_PRIVILEGES and priv != "SELECT":
                risks.append({
                    "type": "excessive", "account": acct,
                    "object_fqn": g["object_fqn"], "privilege": priv,
                    "severity": "high",
                    "detail": f"{acct} 对 {g['object_fqn']} 具备 {priv}（过度授权）",
                })
            grade = grade_lookup.get(g["object_fqn"])
            if grade is not None and grade >= HIGH_GRADE_THRESHOLD:
                risks.append({
                    "type": "high_sensitivity", "account": acct,
                    "object_fqn": g["object_fqn"], "privilege": priv,
                    "severity": "high",
                    "detail": f"{acct} 可访问高敏对象 {g['object_fqn']} (L{grade})",
                })
    return risks


def _owner_of(grant: dict) -> str:
    return grant.get("account") or "unknown"
