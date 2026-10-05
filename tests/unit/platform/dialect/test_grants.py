"""MOD-08 T1: dialect accounts/grants SQL (uniform 5-column contract)."""
import pytest

from local_ingestion.platform.dialect import get_dialect

CONTRACT_COLS = ("grantee", "object_type", "object_fqn", "privilege", "grantable")


def test_accounts_sql_has_super_and_lock():
    sql = get_dialect("postgres").list_accounts_sql()
    assert "pg_roles" in sql and "rolsuper" in sql and "rolcanlogin" in sql


def test_accounts_sql_uniform_contract():
    # Uniform contract (name, host, is_super, is_locked) across dialects.
    pg = get_dialect("postgres").list_accounts_sql().lower()
    assert "pg_roles" in pg and "rolsuper" in pg and "host" in pg and "is_locked" in pg
    my = get_dialect("mysql").list_accounts_sql().lower()
    # mysql.user has NO is_super column — the real flag is Super_priv.
    assert "mysql.user" in my and "super_priv" in my and "account_locked" in my


def test_grants_sql_uniform_contract():
    # PostgreSQL + MySQL both emit the (grantee, object_type, object_fqn,
    # privilege, grantable) contract and include column-level grants.
    for ds in ("postgres", "mysql"):
        sql = get_dialect(ds).list_grants_sql().lower()
        for col in CONTRACT_COLS:
            assert col in sql, f"{ds} missing {col}"
        assert "column" in sql  # column-level grants must be present
