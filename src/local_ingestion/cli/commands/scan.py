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
