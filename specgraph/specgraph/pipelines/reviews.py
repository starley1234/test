"""Оценки и черновики формулировок на карточках требований."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from specgraph.models import Requirement, RequirementReview


def save_review(db: Session, req: Requirement, row: dict[str, Any], *, run_id: str | None = None) -> None:
    rec = RequirementReview(
        requirement_id=req.id,
        run_id=run_id,
        passed=bool(row.get("pass")),
        note=row.get("note"),
        marks=row.get("marks") or {},
        mode=row.get("mode"),
    )
    db.add(rec)
    extra = dict(req.extra or {})
    extra["review"] = {
        "pass": row.get("pass"),
        "note": row.get("note"),
        "marks": row.get("marks") or {},
        "mode": row.get("mode"),
        "at": datetime.utcnow().isoformat(timespec="seconds"),
        "run_id": run_id,
    }
    req.extra = extra


def set_draft(db: Session, req: Requirement, text: str) -> None:
    extra = dict(req.extra or {})
    extra["draft_text"] = text
    extra["draft_at"] = datetime.utcnow().isoformat(timespec="seconds")
    req.extra = extra


def apply_draft(db: Session, req: Requirement) -> str:
    extra = dict(req.extra or {})
    draft = (extra.get("draft_text") or "").strip()
    if not draft:
        raise ValueError("нет черновика")
    from specgraph.ingest.resolve import apply_new_revision

    extra.pop("draft_text", None)
    extra["draft_applied"] = True
    apply_new_revision(db, req, code=req.code, text=draft, extra=extra, document_id=req.document_id)
    req.text = draft
    db.commit()
    return draft


def store_drafts_from_text(db: Session, text: str, requirement_ids: list[int] | None) -> list[dict]:
    """Пытаемся вытащить JSON [{id|code, suggested}] и записать draft_text."""
    out: list[dict] = []
    m = re.search(r"\[.*\]", text or "", re.S)
    items = []
    if m:
        try:
            items = json.loads(m.group(0))
        except json.JSONDecodeError:
            items = []
    if not isinstance(items, list):
        return out
    q = db.query(Requirement).filter(Requirement.is_current.is_(True))
    if requirement_ids:
        q = q.filter(Requirement.id.in_(requirement_ids))
    by_id = {r.id: r for r in q.all()}
    by_code = {r.code: r for r in by_id.values()}
    for it in items:
        if not isinstance(it, dict):
            continue
        suggested = str(it.get("suggested") or it.get("стало") or it.get("text") or "").strip()
        if not suggested:
            continue
        req = None
        if it.get("id") and int(it["id"]) in by_id:
            req = by_id[int(it["id"])]
        elif it.get("code") and it["code"] in by_code:
            req = by_code[it["code"]]
        if not req:
            continue
        set_draft(db, req, suggested)
        out.append({"id": req.id, "code": req.code, "suggested": suggested})
    if out:
        db.commit()
    return out
