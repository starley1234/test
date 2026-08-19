"""Связи с вышестоящими требованиями, даже если их ещё нет в БД.

Заглушка (stub) создаётся сразу; при загрузке настоящего документа
текст/атрибуты вливаются в ту же запись (по базовому коду).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from specgraph.ingest.ids import base_code
from specgraph.models import (
    EntityRelation,
    EntityType,
    RelationType,
    Requirement,
    RequirementAttribute,
    RequirementKind,
)


def find_by_code(db: Session, code: str) -> Requirement | None:
    if not code:
        return None
    exact = db.query(Requirement).filter(Requirement.code == code).first()
    if exact:
        return exact
    base = base_code(code)
    return (
        db.query(Requirement)
        .filter((Requirement.code == base) | (Requirement.code.startswith(base + "/")))
        .order_by(Requirement.id.asc())
        .first()
    )


def ensure_stub(
    db: Session,
    code: str,
    *,
    document_id: int,
    kind: str = "unknown",
    note: str = "",
) -> Requirement:
    existing = find_by_code(db, code)
    if existing:
        return existing
    k = kind if kind in {e.value for e in RequirementKind} else "unknown"
    req = Requirement(
        document_id=document_id,
        code=code,
        text=note or f"Вышестоящее требование {code} (ещё не загружено).",
        kind=RequirementKind(k),
        extra={"stub": True},
    )
    db.add(req)
    db.flush()
    db.add(RequirementAttribute(requirement_id=req.id, key="stub", value="true"))
    return req


def merge_if_stub(existing: Requirement, incoming: Requirement) -> None:
    if not (existing.extra or {}).get("stub"):
        return
    if incoming.text and not incoming.text.startswith("Вышестоящее"):
        existing.text = incoming.text
    if incoming.kind and incoming.kind != RequirementKind.UNKNOWN:
        existing.kind = incoming.kind
    extra = dict(existing.extra or {})
    extra.pop("stub", None)
    extra.update({k: v for k, v in (incoming.extra or {}).items() if k != "stub"})
    existing.extra = extra
    if incoming.section_path:
        existing.section_path = incoming.section_path
    if incoming.product_id and not existing.product_id:
        existing.product_id = incoming.product_id


def link_derived(db: Session, child: Requirement, parent: Requirement) -> None:
    exists = (
        db.query(EntityRelation)
        .filter(
            EntityRelation.rel_type == RelationType.DERIVED_FROM,
            EntityRelation.src_type == EntityType.REQUIREMENT,
            EntityRelation.src_id == child.id,
            EntityRelation.dst_type == EntityType.REQUIREMENT,
            EntityRelation.dst_id == parent.id,
        )
        .first()
    )
    if exists:
        return
    db.add(
        EntityRelation(
            rel_type=RelationType.DERIVED_FROM,
            src_type=EntityType.REQUIREMENT,
            src_id=child.id,
            dst_type=EntityType.REQUIREMENT,
            dst_id=parent.id,
        )
    )
    if not child.parent_id:
        child.parent_id = parent.id


def resolve_pending(db: Session) -> int:
    """Повторно связать висячие derived_from по коду (после догрузки пакета)."""
    n = 0
    stubs = db.query(Requirement).all()
    by_base: dict[str, list[Requirement]] = {}
    for r in stubs:
        by_base.setdefault(base_code(r.code), []).append(r)
    for base, group in by_base.items():
        real = next((r for r in group if not (r.extra or {}).get("stub")), None)
        if not real:
            continue
        for r in group:
            if r.id == real.id:
                continue
            if (r.extra or {}).get("stub"):
                merge_if_stub(r, real)
                n += 1
    return n
