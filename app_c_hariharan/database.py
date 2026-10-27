"""Database connection and session management (SQLAlchemy 2.x).

Works with SQLite (local development) and PostgreSQL (production).
Money values always use Decimal fixed-precision types.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

connect_args = {}
pool_kwargs: dict = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False
    if ":memory:" in settings.DATABASE_URL:
        # Share one connection across the pool so in-memory data persists.
        from sqlalchemy.pool import StaticPool

        pool_kwargs["poolclass"] = StaticPool

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
    echo=False,
    **pool_kwargs,
)

if settings.DATABASE_URL.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):  # noqa
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    """Create all tables (used for local dev and tests; production uses migrations)."""
    # Import models so they are registered on Base.metadata.
    import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    logger.info("Database initialised.")


@contextmanager
def get_db_transaction() -> Generator[Session, None, None]:
    """Session context manager with commit/rollback transaction handling."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
