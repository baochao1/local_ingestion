"""数据库预检：分区覆盖 / CHECK 约束与代码枚举一致性 / 表与模型漂移。

本次 6 张分区表 0 分区导致注册 500，若有此脚本可一次发现。

用法：
    python db_preflight.py
退出码非 0 表示存在问题。
"""
from __future__ import annotations

import io
import sys
from datetime import date

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import os  # noqa: E402
from pathlib import Path  # noqa: E402

import psycopg2  # noqa: E402

DSN = os.getenv(
    "LOCAL_INGESTION_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/local_ingestion",
)

# 代码侧枚举：与 platform/datasource/service.py::ALLOWED_DS_TYPES 对齐
ALLOWED_DS_TYPES = {
    "mysql", "postgres", "postgresql", "snowflake", "sqlserver", "bigquery", "other",
}


def parse_check_values(checkdef: str) -> set[str]:
    """从 `CHECK ((ds_type = ANY (ARRAY['mysql'::text, ...])))` 中抠出取值。"""
    import re

    return set(re.findall(r"'([^']+)'::text", checkdef)) or set(
        re.findall(r"'([^']+)'", checkdef)
    )


def main() -> int:
    conn = psycopg2.connect(DSN, connect_timeout=8)
    cur = conn.cursor()
    problems: list[str] = []

    # 1) 分区覆盖：每张分区表是否包含"当前月"分区
    cur.execute(
        """
        select c.relname from pg_partitioned_table pt join pg_class c on c.oid = pt.partrelid
        """
    )
    part_tables = [r[0] for r in cur.fetchall()]
    print(f"分区表 {len(part_tables)} 张：{', '.join(part_tables) or '（无）'}")
    for t in part_tables:
        cur.execute(
            """
            select c.relname, pg_get_expr(c.relpartbound, c.oid)
            from pg_inherits i join pg_class c on c.oid = i.inhrelid
            where i.inhparent = %s::regclass
            """,
            (t,),
        )
        parts = cur.fetchall()
        if not parts:
            problems.append(f"[分区] {t} 没有任何分区 → 任何写入都会报 no partition found")
            print(f"    ✗ {t}: 0 个分区")
            continue
        today = date.today()
        cur_month = f"{today.year}{today.month:02d}"
        covered = any(f"_{cur_month}" in p[0] for p in parts)
        if not covered:
            problems.append(f"[分区] {t} 缺少当前月分区 {cur_month}")
            print(f"    ✗ {t}: {len(parts)} 个分区，缺当前月 {cur_month}")
        else:
            print(f"    ✓ {t}: {len(parts)} 个分区")

    # 2) CHECK 约束 vs 代码枚举
    # 只校验 datasource.ds_type 的约束：其它 ck_*_type 是不同列的约束，
    # 且分区子表会继承同名约束，必须限定 conrelid 否则会重复/误报。
    cur.execute(
        """
        select conname, pg_get_constraintdef(oid)
        from pg_constraint
        where conrelid = 'datasource'::regclass and conname = 'ck_datasource_type'
        """
    )
    for name, cdef in cur.fetchall():
        vals = parse_check_values(cdef)
        missing = ALLOWED_DS_TYPES - vals
        extra = vals - ALLOWED_DS_TYPES
        if missing:
            problems.append(
                f"[约束] {name} 缺少代码允许的类型 {sorted(missing)}"
                f"（后端 ALLOWED_DS_TYPES 允许但插入会被拒）"
            )
            print(f"    ✗ {name}: 缺 {sorted(missing)}")
        else:
            print(f"    ✓ {name}: 与代码枚举一致（多余项 {sorted(extra) or '无'}）")

    # 3) 关键表是否有数据（空数据会让页面只渲染空态，掩盖真实逻辑）
    for t in ("datasource", "catalog_table", "catalog_column",
              "change_event", "scan_run", "approval_request", "governance_ticket"):
        try:
            cur.execute(f"select count(*) from {t}")
            n = cur.fetchone()[0]
            print(f"    {'✓' if n else '·'} {t}: {n} 行" + ("（空 → 页面仅渲染空态）" if n == 0 else ""))
        except psycopg2.Error as e:
            conn.rollback()
            print(f"    ! {t}: 查询失败 {e}")

    conn.close()

    print("\n=== 结论 ===")
    if problems:
        for p_ in problems:
            print("✗", p_)
        return 1
    print("✓ 未发现分区/约束问题")
    return 0


if __name__ == "__main__":
    sys.exit(main())
