"""Рабочее пространство в БД. Cookie гостя / user_id. Не localStorage."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from specgraph.models import User, WorkSpace

COOKIE = "specgraph_ws"


def get_or_create(db: Session, *, guest_key: str | None, user: User | None) -> WorkSpace:
    row = None
    if user:
        row = db.query(WorkSpace).filter(WorkSpace.user_id == user.id).order_by(WorkSpace.created_at.desc()).first()
    if not row and guest_key:
        row = db.query(WorkSpace).filter(WorkSpace.guest_key == guest_key).first()
    if row:
        if user and not row.user_id:
            row.user_id = user.id
            db.commit()
        return row
    row = WorkSpace(
        id=uuid4().hex[:16],
        user_id=user.id if user else None,
        guest_key=guest_key or uuid4().hex,
        include_graph=False,
        document_ids=[],
        events=[],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def attach_documents(db: Session, ws: WorkSpace, ids: list[int]) -> WorkSpace:
    have = list(ws.document_ids or [])
    for i in ids:
        if i not in have:
            have.append(i)
    ws.document_ids = have
    db.commit()
    return ws


def log_event(db: Session, ws: WorkSpace, kind: str, payload: dict[str, Any]) -> None:
    ev = list(ws.events or [])
    ev.append({"kind": kind, **payload})
    ws.events = ev[-40:]
    db.commit()


def set_include(db: Session, ws: WorkSpace, include_graph: bool) -> WorkSpace:
    ws.include_graph = bool(include_graph)
    db.commit()
    return ws
