"""Подключение к БД. Если Postgres в .env не запущен — сами переходим на SQLite."""

from __future__ import annotations

import logging
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from specgraph.config import settings

log = logging.getLogger("specgraph.db")

SQLITE_FALLBACK = "sqlite:///./specgraph.db"


class Base(DeclarativeBase):
    pass


def _make_engine(url: str):
    args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, echo=False, connect_args=args)


engine = _make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _switch_sqlite() -> None:
    global engine, SessionLocal
    log.warning(
        "Не удалось подключиться к %s — используем %s. "
        "Чтобы Postgres: docker compose up -d db  и верный DATABASE_URL в .env",
        settings.database_url,
        SQLITE_FALLBACK,
    )
    settings.database_url = SQLITE_FALLBACK
    engine = _make_engine(SQLITE_FALLBACK)
    SessionLocal.configure(bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from specgraph import models  # noqa: F401
    from sqlalchemy.exc import OperationalError

    global engine
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError:
        if settings.database_url.startswith("sqlite"):
            raise
        if not settings.sqlite_fallback:
            raise
        _switch_sqlite()

    Base.metadata.create_all(bind=engine)
    log.info("БД готова: %s", settings.database_url)
