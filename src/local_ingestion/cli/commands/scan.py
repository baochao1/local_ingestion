"""数据库扫描命令"""

from __future__ import annotations

import argparse
import logging
from typing import Optional

from local_ingestion.cli.base import BaseCommand
from local_ingestion.schema.service.connection import MySQLConnection, PostgresConnection, SnowflakeConnection

logger = logging.getLogger(__name__)


class ScanMySQLCommand(BaseCommand):
    """扫描 MySQL 数据库命令"""
    
    name = "scan mysql"
    help = "扫描 MySQL 数据库并提取元数据"
    
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--host", required=True, help="MySQL 主机地址")
        parser.add_argument("--port", type=int, default=3306, help="MySQL 端口 (默认: 3306)")
        parser.add_argument("--username", required=True, help="用户名")
        parser.add_argument("--password", required=True, help="密码")
        parser.add_argument("--database", default="mysql", help="数据库名 (默认: mysql)")
        parser.add_argument("--schema", default="information_schema", help="Schema 名 (默认: information_schema)")
        parser.add_argument("--include-columns", action="store_true", help="包含列信息")
        parser.add_argument("--output", help="输出文件路径 (JSON)")
    
    def execute(self, args: list) -> int:
        parser = argparse.ArgumentParser(prog="scan mysql")
        self.add_arguments(parser)
        
        try:
            parsed_args = parser.parse_args(args)
        except SystemExit:
            return 1
        
        from local_ingestion.core.connectors.mysql import MySQLSourceConnector
        
        self.print_info(f"正在连接 MySQL: {parsed_args.host}:{parsed_args.port}")
        
        config = MySQLConnection(
            hostPort=f"{parsed_args.host}:{parsed_args.port}",
            username=parsed_args.username,
            password=parsed_args.password,
            database=parsed_args.database,
        )
        
        connector = MySQLSourceConnector()
        
        try:
            connector.connect(config)
            self.print_success("连接成功!")
            
            # 获取数据库
            databases = connector.fetch_databases()
            self.print_info(f"发现 {len(databases)} 个数据库")
            
            # 获取表
            tables = connector.fetch_tables(parsed_args.database, parsed_args.schema)
            self.print_info(f"发现 {len(tables)} 个表")
            
            # 输出表信息
            print("\n" + "=" * 60)
            print(f"数据库: {parsed_args.database}")
            print(f"Schema: {parsed_args.schema}")
            print("=" * 60)
            
            for table in tables:
                print(f"\n表: {table.name}")
                print(f"  类型: {table.tableType}")
                print(f"  描述: {table.description or 'N/A'}")
                print(f"  完全限定名: {table.fullyQualifiedName}")
                
                if parsed_args.include_columns:
                    columns = connector.fetch_columns(table)
                    print(f"  列数: {len(columns)}")
                    for col in columns[:5]:  # 只显示前5列
                        nullable = "NULL" if col.nullable else "NOT NULL"
                        print(f"    - {col.name}: {col.dataType} ({nullable})")
                    if len(columns) > 5:
                        print(f"    ... 还有 {len(columns) - 5} 列")
            
            print("\n" + "=" * 60)
            
            # 保存到文件
            if parsed_args.output:
                import json
                result = {
                    "database": parsed_args.database,
                    "schema": parsed_args.schema,
                    "tables": [
                        {
                            "name": t.name,
                            "type": t.tableType,
                            "description": t.description,
                            "fullyQualifiedName": t.fullyQualifiedName,
                        }
                        for t in tables
                    ]
                }
                with open(parsed_args.output, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
                self.print_success(f"结果已保存到: {parsed_args.output}")
            
            return 0
            
        except Exception as e:
            self.print_error(f"扫描失败: {e}")
            return 1
        finally:
            connector.disconnect()


def _resolve_datasource(ref: str):
    """按 code 或 id 解析数据源 id（忽略已软删的）。"""
    from local_ingestion.platform.storage.models_core import Datasource
    from local_ingestion.platform.storage.session import session_scope

    with session_scope() as s:
        ds = (
            s.query(Datasource)
            .filter(Datasource.code == ref, Datasource.deleted_at.is_(None))
            .first()
        )
        if ds is None and ref.isdigit():
            ds = s.get(Datasource, int(ref))
            if ds is not None and ds.deleted_at is not None:
                ds = None
        return ds.id if ds is not None else None


class ScanRunCommand(BaseCommand):
    """对已注册数据源执行一次真实摄取，写入 ``catalog_*``。

    与 ``scan mysql`` / ``scan postgres`` 不同——那两个只是连通性预览，结果只
    打印到 stdout，不落库（目录行的归属必须挂在某个 ``datasource_id`` 上，而
    裸连接参数没有数据源身份）。本命令走 ScanService 的完整链路：
    只读校验 -> 连接器 -> DatabasePipeline -> PostgresSink。
    """

    name = "run"
    help = "摄取已注册数据源的元数据并写入目录"

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--datasource", required=True, help="数据源 code 或 id")
        parser.add_argument("--database", help="覆盖 scan_config.database")
        parser.add_argument("--schemas", nargs="*", help="仅扫描指定 schema（可多个）")
        parser.add_argument("--allow-write", action="store_true", help="放宽只读校验（非生产用途）")
        parser.add_argument("--keep-deleted", action="store_true", help="本次不标记删除（保留历史实体）")
        parser.add_argument("--skip-classify", action="store_true", help="跳过 MOD-05 分级（不写 grade_level/PII 标记）")

    def execute(self, args: list) -> int:
        parser = argparse.ArgumentParser(prog="scan run")
        self.add_arguments(parser)

        try:
            parsed_args = parser.parse_args(args)
        except SystemExit:
            return 1

        # 延迟导入：platform 包在导入时会读取环境变量化的配置（如加密密钥）。
        from local_ingestion.platform.scan import (
            ScanError,
            ScanService,
        )
        from local_ingestion.platform.storage.session import session_scope

        ds_id = _resolve_datasource(parsed_args.datasource)
        if ds_id is None:
            self.print_error(f"未找到数据源：{parsed_args.datasource}")
            return 1

        service = ScanService(session_scope)
        try:
            result = service.run_scan(
                ds_id,
                database=parsed_args.database,
                schemas=parsed_args.schemas or None,
                allow_write=parsed_args.allow_write,
                mark_deleted=not parsed_args.keep_deleted,
                classify=not parsed_args.skip_classify,
            )
        except ScanError as e:
            self.print_error(f"扫描失败: {e}")
            return 1

        self.print_success(
            f"扫描完成 {result.datasource_code} / {result.database}："
            f"表 {result.tables_processed}（失败 {result.tables_failed}）、"
            f"schema {result.schemas_processed}、只读={result.readonly}"
        )
        if result.classification:
            c = result.classification
            self.print_info(
                f"分级：表 {c['tables_graded']}、列 {c['columns_graded']}"
                f"（PII {c['pii_columns']}、敏感 {c['sensitive_columns']}）"
            )
        for err in result.errors:
            self.print_error(f"  - {err}")
        return 0 if result.ok else 1

class ScanClassifyCommand(BaseCommand):
    """对目录里已有的数据补做 MOD-05 分级（无需重新扫描）。

    扫描默认已带分级，此命令用于：规则更新后重算、或对历史数据补分级。
    """

    name = "classify"
    help = "对目录数据执行敏感度分级"

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--datasource", required=True, help="数据源 code 或 id")
        parser.add_argument("--all", action="store_true",
                            help="连同已分级的行一起重算（默认跳过，保留人工分级）")

    def execute(self, args: list) -> int:
        parser = argparse.ArgumentParser(prog="scan classify")
        self.add_arguments(parser)

        try:
            parsed_args = parser.parse_args(args)
        except SystemExit:
            return 1

        from local_ingestion.platform.classification import ClassificationService
        from local_ingestion.platform.storage.session import session_scope

        ds_id = _resolve_datasource(parsed_args.datasource)
        if ds_id is None:
            self.print_error(f"未找到数据源：{parsed_args.datasource}")
            return 1

        outcome = ClassificationService(session_scope).classify_datasource(
            ds_id, only_ungraded=not parsed_args.all
        )
        self.print_success(
            f"分级完成：表 {outcome.tables_graded}、列 {outcome.columns_graded}"
            f"（PII {outcome.pii_columns}、敏感 {outcome.sensitive_columns}、跳过 {outcome.skipped}）"
        )
        return 0


class ScanPostgresCommand(BaseCommand):
    """扫描 PostgreSQL 数据库命令"""
    
    name = "scan postgres"
    help = "扫描 PostgreSQL 数据库并提取元数据"
    
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--host", required=True, help="PostgreSQL 主机地址")
        parser.add_argument("--port", type=int, default=5432, help="PostgreSQL 端口 (默认: 5432)")
        parser.add_argument("--username", required=True, help="用户名")
        parser.add_argument("--password", required=True, help="密码")
        parser.add_argument("--database", required=True, help="数据库名")
        parser.add_argument("--schema", default="public", help="Schema 名 (默认: public)")
        parser.add_argument("--include-columns", action="store_true", help="包含列信息")
        parser.add_argument("--output", help="输出文件路径 (JSON)")
    
    def execute(self, args: list) -> int:
        parser = argparse.ArgumentParser(prog="scan postgres")
        self.add_arguments(parser)
        
        try:
            parsed_args = parser.parse_args(args)
        except SystemExit:
            return 1
        
        from local_ingestion.core.connectors.postgres import PostgresSourceConnector
        
        self.print_info(f"正在连接 PostgreSQL: {parsed_args.host}:{parsed_args.port}")
        
        config = PostgresConnection(
            hostPort=f"{parsed_args.host}:{parsed_args.port}",
            username=parsed_args.username,
            password=parsed_args.password,
            database=parsed_args.database,
        )
        
        connector = PostgresSourceConnector()
        
        try:
            connector.connect(config)
            self.print_success("连接成功!")
            
            schemas = connector.fetch_schemas(parsed_args.database)
            self.print_info(f"发现 {len(schemas)} 个 schemas")
            
            tables = connector.fetch_tables(parsed_args.database, parsed_args.schema)
            self.print_info(f"发现 {len(tables)} 个表")
            
            print("\n" + "=" * 60)
            print(f"数据库: {parsed_args.database}")
            print(f"Schema: {parsed_args.schema}")
            print("=" * 60)
            
            for table in tables:
                print(f"\n表: {table.name}")
                print(f"  描述: {table.description or 'N/A'}")
                print(f"  完全限定名: {table.fullyQualifiedName}")
                
                if parsed_args.include_columns:
                    columns = connector.fetch_columns(table)
                    print(f"  列数: {len(columns)}")
                    for col in columns[:5]:
                        nullable = "NULL" if col.nullable else "NOT NULL"
                        print(f"    - {col.name}: {col.dataType} ({nullable})")
            
            return 0
            
        except Exception as e:
            self.print_error(f"扫描失败: {e}")
            return 1
        finally:
            connector.disconnect()
