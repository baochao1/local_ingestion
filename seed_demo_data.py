"""演示数据播种：为仍为空的业务表各插入少量最小可行行。

目的：没有数据时，列表页渲染 EmptyState、详情页渲染 ErrorState，
真实逻辑（字段映射 / 分页 / 渲染分支）完全不会被触达，测试形同虚设。

特性：
* 幂等——只处理当前 0 行的表；
* 安全——自动读取 CHECK 约束允许的取值、外键取被引用表现有 id；
* 可容忍失败——单表失败不中断，失败原因会列出（本身也是有价值的信息）。

用法：
    python seed_demo_data.py            # 播种（默认每表 2 行）
    python seed_demo_data.py --rows 3
"""
from __future__ import annotations

import io
import re
import sys
from typing import Any

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import os  # noqa: E402

import psycopg2  # noqa: E402
from psycopg2 import sql  # noqa: E402

DSN = os.getenv(
    "LOCAL_INGESTION_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/local_ingestion",
)

# 按外键依赖顺序：被引用的表排在前面
TARGET_TABLES = [
    "tenant",
    "datasource",
    "catalog_database",
    "catalog_schema",
    "catalog_table",
    "catalog_column",
    "change_event",
    "scan_run",
    "column_snapshot",
    "table_snapshot",
    "table_profile",
    "quality_rule",
    "quality_result",
    "classification_tag",
    "classification_rule",
    "lineage_table_edge",
    "business_term",
    "entity_tag",
    "approval_request",
    "governance_ticket",
    "notification_subscription",
]


def table_columns(cur, table: str) -> list[dict]:
    cur.execute(
        """
        select column_name, data_type, is_nullable, column_default,
               is_generated, identity_generation
        from information_schema.columns
        where table_schema='public' and table_name=%s
        order by ordinal_position
        """,
        (table,),
    )
    cols = []
    for name, dtype, nullable, default, generated, ident in cur.fetchall():
        cols.append({
            "name": name, "data_type": dtype,
            "notnull": nullable == "NO",
            "has_default": default is not None or ident is not None,
            "generated": generated and generated != "NEVER",
        })
    return cols


def check_allowed_values(cur, table: str) -> dict[str, list[str]]:
    """提取 CHECK 约束中每个列允许的字面量取值。"""
    cur.execute(
        """
        select pg_get_constraintdef(oid)
        from pg_constraint
        where conrelid = %s::regclass and contype = 'c'
        """,
        (table,),
    )
    out: dict[str, list[str]] = {}
    for (cdef,) in cur.fetchall():
        lits = re.findall(r"'((?:[^']|'')*)'", cdef)
        if not lits:
            continue
        # 只在约束体里提到单个列名时才归属（避免多列约束误判）
        mentioned = [c for c in re.findall(r"\b([a-z_][a-z0-9_]*)\b", cdef)
                     if c in {x[0] for x in _all_columns(cur, table)}]
        uniq = set(mentioned)
        if len(uniq) == 1:
            out.setdefault(uniq.pop(), []).extend(lits)
    return out


def _all_columns(cur, table: str) -> list[tuple[str, ...]]:
    cur.execute(
        "select column_name from information_schema.columns "
        "where table_schema='public' and table_name=%s",
        (table,),
    )
    return cur.fetchall()


def foreign_keys(cur, table: str) -> dict[str, str]:
    """列 -> 被引用表名（取该表主键/首列）。"""
    cur.execute(
        """
        select kcu.column_name, ccu.table_name, ccu.column_name
        from information_schema.table_constraints tc
        join information_schema.key_column_usage kcu
          on tc.constraint_name=kcu.constraint_name and tc.table_schema=kcu.table_schema
        join information_schema.constraint_column_usage ccu
          on ccu.constraint_name=tc.constraint_name and ccu.table_schema=tc.table_schema
        where tc.constraint_type='FOREIGN KEY' and tc.table_name=%s
        """,
        (table,),
    )
    return {r[0]: (r[1], r[2]) for r in cur.fetchall()}


def value_for(col: dict, idx: int, allowed: list[str] | None, fk_ref: tuple[str, str] | None,
              cur) -> Any:
    name, dtype = col["name"], col["data_type"]

    if fk_ref:
        ref_table, ref_col = fk_ref
        try:
            # 按行号取不同的被引用行：否则多行会复用同一个 id，
            # 撞上 (table_id) 这类唯一约束。
            cur.execute(
                sql.SQL("select {} from {} order by {} limit 1 offset %s").format(
                    sql.Identifier(ref_col), sql.Identifier(ref_table),
                    sql.Identifier(ref_col)),
                (idx - 1,),
            )
            row = cur.fetchone()
            if row:
                return row[0]
            cur.execute(sql.SQL("select {} from {} limit 1").format(
                sql.Identifier(ref_col), sql.Identifier(ref_table)))
            row = cur.fetchone()
            if row:
                return row[0]
        except psycopg2.Error:
            cur.connection.rollback()
        return None

    if allowed:
        return allowed[idx % len(allowed)]

    low = name.lower()
    if dtype in ("text", "character varying", "character", "name"):
        if "fqn" in low:
            return f"seed.schema.tbl{idx}"
        if low.endswith("code") or "code" in low:
            return f"seed_code_{idx}"
        if "name" in low:
            return f"seed_name_{idx}"
        if "email" in low:
            return f"seed{idx}@example.com"
        return f"seed_{low}_{idx}"
    if dtype in ("timestamp with time zone", "timestamp without time zone", "date"):
        return "now()"
    if dtype == "boolean":
        return True
    if dtype in ("json", "jsonb"):
        return "{}"
    if dtype.startswith("numeric") or dtype in ("real", "double precision"):
        return idx
    if dtype in ("integer", "bigint", "smallint"):
        return idx
    return f"seed_{idx}"


def seed_table(cur, conn, table: str, rows: int) -> tuple[int, str | None]:
    cur.execute(f"select count(*) from {table}")
    if cur.fetchone()[0] > 0:
        return 0, None  # 已有数据，跳过

    cols = table_columns(cur, table)
    fks = foreign_keys(cur, table)
    allowed_map = check_allowed_values(cur, table)

    # 主键/生成列/有默认值的列不填
    fillable = [c for c in cols if not c["generated"] and not c["has_default"]]

    # 可空列一律不填：否则会把 deleted_at 之类填成 now()，
    # 导致行被判为"已删除"、查询（deleted_at IS NULL）永远查不到。
    fillable = [c for c in fillable if c["notnull"] and c["name"].lower() not in
                {"deleted_at", "deleted", "is_deleted"}]

    inserted = 0
    for i in range(1, rows + 1):
        names, vals, placeholders = [], [], []
        for c in fillable:
            nm = c["name"]
            if nm in fks:
                v = value_for(c, i, None, fks[nm], cur)
                if v is None and c["notnull"]:
                    return inserted, f"外键列 {nm} 无可用被引用行"
            else:
                v = value_for(c, i, allowed_map.get(nm), None, cur)
            if v is None and not c["notnull"]:
                continue
            if isinstance(v, str) and v == "now()":
                placeholders.append("now()")
            else:
                placeholders.append("%s")
                vals.append(v)
            names.append(nm)

        if not names:
            continue
        stmt = sql.SQL("insert into {} ({}) values ({})").format(
            sql.Identifier(table),
            sql.SQL(", ").join(sql.Identifier(n) for n in names),
            sql.SQL(", ").join(sql.SQL(p) for p in placeholders),
        )
        try:
            cur.execute(stmt, vals)
            conn.commit()
            inserted += 1
        except psycopg2.Error as e:
            conn.rollback()
            return inserted, f"{type(e).__name__}: {str(e).strip()[:180]}"
    return inserted, None


# 已有真实数据、不参与 --reset 的表
PROTECTED = {"datasource", "classification_tag", "classification_rule"}


def main() -> int:
    rows = 2
    if "--rows" in sys.argv:
        rows = int(sys.argv[sys.argv.index("--rows") + 1])
    do_reset = "--reset" in sys.argv

    conn = psycopg2.connect(DSN, connect_timeout=8)
    cur = conn.cursor()

    if do_reset:
        # 清掉上一次误填的播种行（这些表在播种前都是空的）
        cleared = []
        for t in TARGET_TABLES:
            if t in PROTECTED:
                continue
            try:
                cur.execute(f"truncate table {t}")
                conn.commit()
                cleared.append(t)
            except psycopg2.Error as e:
                conn.rollback()
                print(f"  ! {t}: 清空失败 {str(e).strip()[:80]}")
        print(f"已清空 {len(cleared)} 张表：{', '.join(cleared)}\n")

    print(f"播种目标 {len(TARGET_TABLES)} 张表（每表 {rows} 行，仅处理空表）\n")

    ok_tables, skipped, failed = [], [], []
    for t in TARGET_TABLES:
        try:
            cur.execute(f"select count(*) from {t}")
        except psycopg2.Error as e:
            conn.rollback()
            skipped.append((t, f"表不存在：{str(e).strip()[:80]}"))
            print(f"  - {t}: 表不存在，跳过")
            continue
        n, err = seed_table(cur, conn, t, rows)
        if err:
            failed.append((t, err))
            print(f"  ✗ {t}: 插入 {n} 行后失败 → {err}")
        elif n == 0:
            print(f"  · {t}: 已有数据，跳过")
        else:
            ok_tables.append(t)
            print(f"  ✓ {t}: +{n} 行")

    conn.close()
    print(f"\n成功 {len(ok_tables)} 张 / 失败 {len(failed)} 张 / 跳过 {len(skipped)} 张")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
