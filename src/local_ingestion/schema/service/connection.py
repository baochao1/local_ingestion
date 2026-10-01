"""Service connection configurations"""
from __future__ import annotations

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

from local_ingestion.schema.base import ServiceType


class ServiceConnectionBase(BaseModel):
    """Base class for all service connections"""
    type: ServiceType = ServiceType.DATABASE
    supportsMetadataExtraction: bool = True
    supportsProfileExtraction: bool = True
    supportsLineageExtraction: bool = True

    model_config = {"use_enum_values": True, "extra": "allow"}


class DatabaseConnection(ServiceConnectionBase):
    """Database connection base class"""
    type: ServiceType = ServiceType.DATABASE
    hostPort: str = "localhost"
    username: Optional[str] = None
    password: Optional[str] = None
    database: Optional[str] = None
    sslMode: Optional[str] = "preferred"
    connectionOptions: Optional[Dict[str, str]] = None

    def get_connection_string(self) -> str:
        """Template method for connection string - override in subclasses"""
        raise NotImplementedError


class MySQLConnection(DatabaseConnection):
    """MySQL connection configuration"""
    type: ServiceType = ServiceType.DATABASE

    def get_connection_string(self) -> str:
        parts = self.hostPort.split(":")
        host = parts[0]
        port = parts[1] if len(parts) > 1 else "3306"

        auth = ""
        if self.username:
            auth = f"{self.username}:{self.password or ''}@"

        db = f"/{self.database}" if self.database else ""

        return f"mysql+pymysql://{auth}{host}:{port}{db}?charset=utf8mb4"


class PostgresConnection(DatabaseConnection):
    """PostgreSQL connection configuration"""
    type: ServiceType = ServiceType.DATABASE
    sslMode: str = "prefer"

    def get_connection_string(self) -> str:
        parts = self.hostPort.split(":")
        host = parts[0]
        port = parts[1] if len(parts) > 1 else "5432"

        auth = ""
        if self.username:
            auth = f"{self.username}:{self.password or ''}@"

        db = f"/{self.database}" if self.database else ""

        return f"postgresql://{auth}{host}:{port}{db}"


class SqlServerConnection(DatabaseConnection):
    """SQL Server connection configuration"""
    driver: str = "ODBC Driver 17 for SQL Server"

    def get_connection_string(self) -> str:
        parts = self.hostPort.split(":")
        host = parts[0]
        port = parts[1] if len(parts) > 1 else "1433"

        auth = ""
        if self.username and self.password:
            auth = f"{self.username}:{self.password}@"

        return f"mssql+pyodbc://{auth}{host}:{port}/{self.database}?driver={self.driver.replace(' ', '+')}"


class BigQueryConnection(DatabaseConnection):
    """BigQuery connection configuration"""
    type: ServiceType = ServiceType.DATABASE
    projectId: str = ""
    credentials: Optional[str] = None

    def get_connection_string(self) -> str:
        return f"bigquery://{self.projectId}"


class SnowflakeConnection(DatabaseConnection):
    """Snowflake connection configuration"""
    type: ServiceType = ServiceType.DATABASE
    account: str = ""
    warehouse: Optional[str] = None
    role: Optional[str] = None
    privateKey: Optional[str] = None

    def get_connection_string(self) -> str:
        parts = [f"snowflake://{self.account}"]

        if self.username:
            parts.append("/")
            parts.append(self.username)
            if self.password:
                parts.append(f":{self.password}")
            parts.append("@")

        if self.warehouse:
            parts.append(f"{self.warehouse}")

        parts.append(f"/{self.database}")

        if self.role:
            parts.append(f"?role={self.role}")

        return "".join(parts)
