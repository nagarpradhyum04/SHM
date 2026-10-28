"""Database engine/session management.

SQLite is used for local development; the models only use portable column
types so the same schema migrates to PostgreSQL by changing ``SS_DATABASE_URL``.
"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

from sqlalchemy import DateTime, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from app.config import get_settings
from app.timeutil import ensure_utc


class UTCDateTime(TypeDecorator):
    """Stores naive UTC, always returns timezone-aware UTC datetimes."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        return ensure_utc(value).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect):
        return ensure_utc(value)


class Base(DeclarativeBase):
    pass


def make_engine(url: str) -> Engine:
    kwargs: dict = {"future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()

    return engine


class Database:
    def __init__(self, url: str):
        self.url = url
        self.engine = make_engine(url)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)

    def session(self) -> Session:
        return self.SessionLocal()

    def dispose(self) -> None:
        self.engine.dispose()


_db: Database | None = None


def get_database() -> Database:
    global _db
    if _db is None:
        _db = Database(get_settings().database_url)
    return _db


def set_database(db: Database | None) -> None:
    global _db
    _db = db


def get_session() -> Iterator[Session]:
    session = get_database().session()
    try:
        yield session
    finally:
        session.close()
