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
    _migrate_columns()
    from specgraph.auth import ensure_roles, seed_admin

    s = SessionLocal()
    try:
        ensure_roles(s)
    finally:
        s.close()
    seed_admin()
    log.info("БД готова: %s", settings.database_url)


_AUTH_TABLES = {"users", "roles", "roles_users", "user_tokens"}


def _migrate_columns() -> None:
    """Старые SQLite-файлы: добавить uploaded_by_id без Alembic."""
    if not str(engine.url).startswith("sqlite"):
        return
    with engine.connect() as conn:
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(documents)"))}
        if cols and "uploaded_by_id" not in cols:
            conn.execute(text("ALTER TABLE documents ADD COLUMN uploaded_by_id INTEGER"))
        rcols = {r[1] for r in conn.execute(text("PRAGMA table_info(requirements)"))}
        if rcols and "created_at" not in rcols:
            conn.execute(text("ALTER TABLE requirements ADD COLUMN created_at DATETIME"))
        conn.commit()


def wipe_db() -> None:
    """Чистит граф (документы/требования/изделия). Пользователей и роли не трогает."""
    from specgraph import models  # noqa: F401

    keep = {n: Base.metadata.tables[n] for n in _AUTH_TABLES if n in Base.metadata.tables}
    drop = [t for n, t in Base.metadata.tables.items() if n not in _AUTH_TABLES]
    Base.metadata.drop_all(bind=engine, tables=drop)
    Base.metadata.create_all(bind=engine, tables=drop)
    log.warning("Граф очищен, RBAC сохранён: %s", settings.database_url)
