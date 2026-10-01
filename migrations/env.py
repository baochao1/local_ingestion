"""Alembic migration environment.

Loads ORM metadata from ``local_ingestion.platform.storage.Base`` so that
``alembic revision --autogenerate`` stays in sync with the models, and reads
the database URL from ``METADATA_DB_URL`` (overriding alembic.ini).
"""
import os
import sys
from logging.config import fileConfig

from alembic import context

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from local_ingestion.platform.storage import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

url = os.getenv("METADATA_DB_URL")
if url:
    config.set_main_option("sqlalchemy.url", url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_comments=False,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    from sqlalchemy import engine_from_config, pool

    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_comments=False,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
