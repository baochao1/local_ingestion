"""MOD-08 T3: risk detection engine."""
from datetime import datetime, timedelta, timezone

from local_ingestion.platform.permission.risk import evaluate_risks

NOW = datetime.now(timezone.utc)


def test_super_account_flagged():
    risks = evaluate_risks(
        [{"name": "root", "is_super": True, "is_locked": False, "last_login_at": None}],
        [], grade_lookup={},
    )
    assert any(r["type"] == "super" for r in risks)


def test_excessive_delete_on_table():
    risks = evaluate_risks(
        [{"name": "app", "is_super": False, "is_locked": False, "last_login_at": NOW}],
        [{"account": "app", "privilege": "DELETE", "object_type": "table", "object_fqn": "db.s.orders"}],
        grade_lookup={},
    )
    assert any(r["type"] == "excessive" for r in risks)


def test_high_sensitivity_grant_flagged():
    risks = evaluate_risks(
        [{"name": "analyst", "is_super": False, "is_locked": False, "last_login_at": NOW}],
        [{"account": "analyst", "privilege": "SELECT", "object_type": "table", "object_fqn": "db.s.pii_users"}],
        grade_lookup={"db.s.pii_users": 4},
    )
    assert any(r["type"] == "high_sensitivity" for r in risks)


def test_dormant_and_orphan():
    old = NOW - timedelta(days=400)
    risks = evaluate_risks(
        [{"name": "ghost", "is_super": False, "is_locked": False, "last_login_at": old}],
        [], grade_lookup={}, orphan_check=lambda n: False,
    )
    types = {r["type"] for r in risks}
    assert "dormant" in types and "orphan" in types


def test_select_only_not_excessive():
    risks = evaluate_risks(
        [{"name": "reader", "is_super": False, "is_locked": False, "last_login_at": NOW}],
        [{"account": "reader", "privilege": "SELECT", "object_type": "table", "object_fqn": "db.s.t1"}],
        grade_lookup={},
    )
    assert not any(r["type"] == "excessive" for r in risks)
