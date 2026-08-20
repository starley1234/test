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
    RequirementRevision,
)


def find_by_code(db: Session, code: str) -> Requirement | None:
    if not code:
        return None
    base = base_code(code)
    current = (
        db.query(Requirement)
        .filter(Requirement.base_code == base, Requirement.is_current.is_(True))
        .first()
    )
    if current:
        return current
    exact = db.query(Requirement).filter(Requirement.code == code).first()
    if exact:
        return exact
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
        base_code=base_code(code),
        revision=code.split("/", 1)[1] if "/" in code else None,
        is_current=True,
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


def archive_revision(db: Session, req: Requirement) -> None:
    db.add(
        RequirementRevision(
            requirement_id=req.id,
            document_id=req.document_id,
            code=req.code,
            revision=req.revision,
            text=req.text,
            attributes={a.key: a.value for a in req.attributes},
        )
    )


def apply_new_revision(db: Session, req: Requirement, *, code: str, text: str, extra: dict, document_id: int) -> bool:
    """Если пришла другая ревизия или другой текст — сохранить старое, обновить текущее."""
    new_base = base_code(code)
    new_rev = code.split("/", 1)[1] if "/" in code else None
    same_rev = (req.revision or "") == (new_rev or "") and req.code == code
    same_text = (req.text or "") == (text or "")
    if same_rev and same_text:
        return False
    if not (req.extra or {}).get("stub"):
        archive_revision(db, req)
    req.code = code
    req.base_code = new_base
    req.revision = new_rev
    req.text = text
    req.document_id = document_id
    extra = dict(extra or {})
    extra.pop("stub", None)
    req.extra = extra
    req.is_current = True
    return True


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
