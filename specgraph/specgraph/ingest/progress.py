"""Пошаговая индексация пакета: события для UI."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from sqlalchemy.orm import Session

from specgraph.ingest.pipeline import bind_attachment_to_requirements, ingest_file
from specgraph.ingest.resolve import resolve_pending
from specgraph.models import Attachment, Document, Illustration, Product, Requirement


def file_role(name: str) -> str:
    lower = name.lower()
    if lower.endswith((".xlsx", ".xlsm")):
        return "attachment"
    if Path(name).stem.count(".") >= 2:
        return "attachment"
    return "spec"


def _snap_doc(db: Session, doc_id: int) -> dict[str, Any]:
    reqs = db.query(Requirement).filter(Requirement.document_id == doc_id).all()
    prods = db.query(Product).filter(Product.document_id == doc_id).all()
    atts = db.query(Attachment).filter(Attachment.document_id == doc_id).all()
    ills = db.query(Illustration).filter(Illustration.document_id == doc_id).all()
    return {
        "requirements": [
            {
                "id": r.id,
                "code": r.code,
                "revision": r.revision,
                "stub": bool((r.extra or {}).get("stub")),
                "appendix": bool((r.extra or {}).get("appendix")),
                "text": (r.text or "")[:160],
            }
            for r in reqs
        ],
        "products": [{"id": p.id, "code": p.code, "name": p.name} for p in prods],
        "attachments": [{"id": a.id, "filename": a.filename, "code": a.code} for a in atts],
        "illustrations": len(ills),
        "counts": {
            "requirements": len(reqs),
            "products": len(prods),
            "attachments": len(atts),
            "stubs": sum(1 for r in reqs if (r.extra or {}).get("stub")),
        },
    }


def db_totals(db: Session) -> dict[str, int]:
    return {
        "documents": db.query(Document).count(),
        "requirements": db.query(Requirement).filter(Requirement.is_current.is_(True)).count(),
        "products": db.query(Product).count(),
        "attachments": db.query(Attachment).count(),
    }


def iter_index(
    db: Session, files: list[tuple[Path, str]], *, uploaded_by_id: int | None = None
) -> Iterator[dict[str, Any]]:
    planned = [{"filename": n, "role": file_role(n)} for _, n in files]
    yield {"event": "queued", "files": planned, "totals": db_totals(db)}

    def rank(item: tuple[Path, str]) -> int:
        return 2 if file_role(item[1]) == "attachment" else 1

    ordered = sorted(files, key=rank)
    docs = []
    for i, (path, name) in enumerate(ordered, 1):
        role = file_role(name)
        yield {
            "event": "file_start",
            "index": i,
            "total": len(ordered),
            "filename": name,
            "role": role,
            "step": "читаем файл и ищем карточки" if role == "spec" else "читаем вложение",
        }
        try:
            doc = ingest_file(db, path, name, index=False)
            docs.append(doc)
            snap = _snap_doc(db, doc.id)
            yield {
                "event": "file_done",
                "index": i,
                "total": len(ordered),
                "filename": name,
                "role": role,
                "document_id": doc.id,
                "title": doc.title,
                "status": doc.status,
                "entities": snap,
            }
        except Exception as exc:  # noqa: BLE001
            yield {
                "event": "file_error",
                "index": i,
                "total": len(ordered),
                "filename": name,
                "role": role,
                "error": str(exc),
            }

    yield {"event": "linking", "step": "связываем приложения с требованиями"}
    for att in db.query(Attachment).all():
        bind_attachment_to_requirements(db, att)
    resolve_pending(db)
    db.commit()
    yield {
        "event": "done",
        "documents": [{"id": d.id, "filename": d.filename, "title": d.title} for d in docs],
        "totals": {
            "documents": db.query(Document).count(),
            "requirements": db.query(Requirement).filter(Requirement.is_current.is_(True)).count(),
            "products": db.query(Product).count(),
            "attachments": db.query(Attachment).count(),
        },
    }
