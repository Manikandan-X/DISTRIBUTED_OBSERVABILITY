"""Create the per-service databases and apply their Alembic migrations.

    python -m app.db.migrate                      # every service
    MIGRATE_SERVICES=traces,logs python -m app.db.migrate

Runs as the one-shot ``migrate`` container in docker-compose. Safe to re-run
(CREATE DATABASE IF NOT EXISTS + ``alembic upgrade head``).
"""

import logging
import os
import re
import sys
import time
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.core.config import settings
from app.db.registry import DEFAULT_DATABASES, SERVICE_TABLES
from app.db.session import build_database_url, make_engine

logger = logging.getLogger("migrate")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_]+$")


def database_name(service: str) -> str:
    return os.getenv(f"DB_{service.upper()}", DEFAULT_DATABASES[service])


def wait_for_server(retries: int = 30, delay: float = 2.0) -> None:
    engine = make_engine(build_database_url(""))  # server-level connection
    for attempt in range(1, retries + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except Exception as exc:
            logger.warning("Database not ready (%s/%s): %s", attempt, retries, type(exc).__name__)
            time.sleep(delay)
    raise SystemExit("Database server did not become ready")


def create_databases(services: list[str]) -> None:
    if settings.database_url:  # SQLite (tests): nothing to create
        return
    engine = make_engine(build_database_url(""))
    with engine.begin() as conn:
        for service in services:
            name = database_name(service)
            if not _SAFE_NAME.match(name):
                raise SystemExit(f"Unsafe database name: {name!r}")
            conn.execute(text(f"CREATE DATABASE IF NOT EXISTS `{name}` CHARACTER SET utf8mb4"))
            logger.info("Database ready: %s", name)


def migrate(services: list[str] | None = None) -> None:
    services = services or list(SERVICE_TABLES)
    unknown = set(services) - set(SERVICE_TABLES)
    if unknown:
        raise SystemExit(f"Unknown service(s): {', '.join(sorted(unknown))}")
    if not settings.database_url:
        wait_for_server()
    create_databases(services)

    root = Path(__file__).resolve().parents[2]
    for service in services:
        cfg = Config(str(root / "alembic.ini"))
        cfg.set_main_option("script_location", str(root / "alembic"))
        cfg.attributes["service"] = service
        logger.info("Migrating %s -> %s", service, database_name(service))
        command.upgrade(cfg, f"{service}@head")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    selected = [s.strip() for s in os.getenv("MIGRATE_SERVICES", "").split(",") if s.strip()]
    migrate(selected or None)
    logger.info("All migrations applied")


if __name__ == "__main__":
    sys.exit(main())
