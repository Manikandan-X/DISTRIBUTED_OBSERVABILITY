"""Alembic environment: one migration branch + one database per service."""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import MetaData

import app.db.base  # noqa: F401  (registers every model)
from app.db.registry import DEFAULT_DATABASES, SERVICE_TABLES
from app.db.session import Base, build_database_url, make_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

service = config.attributes.get("service") or os.getenv("ALEMBIC_SERVICE")
if service not in SERVICE_TABLES:
    raise SystemExit(f"Set ALEMBIC_SERVICE to one of: {', '.join(SERVICE_TABLES)}")

# Only this service's tables are visible to autogenerate / comparison.
target_metadata = MetaData()
for name in SERVICE_TABLES[service]:
    Base.metadata.tables[name].to_metadata(target_metadata)


def _database_name() -> str:
    return os.getenv(f"DB_{service.upper()}", DEFAULT_DATABASES[service])


def run_migrations_offline() -> None:
    context.configure(url=str(build_database_url(_database_name())), target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = config.attributes.get("connectable") or make_engine(build_database_url(_database_name()))
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
