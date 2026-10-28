from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings


def build_database_url(database: str | None = None) -> URL | str:
    """Build the DB URL. Credentials are escaped by SQLAlchemy's URL object."""
    if settings.database_url:
        return settings.database_url
    return URL.create(
        "mysql+pymysql",
        username=settings.mysql_user,
        password=settings.mysql_root_password,
        host=settings.mysql_host,
        port=settings.mysql_port,
        # None -> the configured database; "" -> server-level connection (no database selected)
        database=settings.mysql_database if database is None else (database or None),
    )


def make_engine(url=None):
    url = url if url is not None else build_database_url()
    if str(url).startswith("sqlite"):
        return create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    return create_engine(url, pool_pre_ping=True, pool_recycle=1800)


engine = make_engine()

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
