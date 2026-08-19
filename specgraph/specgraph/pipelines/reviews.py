"""Черновики правок отдельно от цифрового двойника (текст из файла не трогаем)."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from specgraph.models import Requirement, RequirementDraft, RequirementReview
from specgraph.pipelines.exports import write_text_bundle


def save_review(db: Session, req: Requirement, row: dict[str, Any], *, run_id: str | None = None) -> None:
    db.add(
        RequirementReview(
            requirement_id=req.id,
            run_id=run_id,
            passed=bool(row.get("pass")),
            note=row.get("note"),
            marks=row.get("marks") or {},
            mode=row.get("mode"),
        )
    )
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


def set_draft(db: Session, req: Requirement, proposed: str, *, reason: str = "", source: str = "llm") -> RequirementDraft:
    d = RequirementDraft(requirement_id=req.id, proposed=proposed, reason=reason or None, source=source)
    db.add(d)
    return d


def latest_draft(db: Session, req_id: int) -> RequirementDraft | None:
    return (
        db.query(RequirementDraft)
        .filter(RequirementDraft.requirement_id == req_id)
        .order_by(RequirementDraft.id.desc())
        .first()
    )


def heuristic_drafts(db: Session, requirement_ids: list[int] | None) -> list[dict]:
    """Без LLM: черновик для отчёта, текст двойника не меняем."""
    q = db.query(Requirement).filter(Requirement.is_current.is_(True))
    if requirement_ids:
        q = q.filter(Requirement.id.in_(requirement_ids))
    out = []
    for req in q.all():
        if (req.extra or {}).get("stub") or (req.extra or {}).get("appendix"):
            continue
        text = req.text or ""
        notes = []
        proposed = text.strip()
        if not re.search(r"должен|должна|должно|shall", proposed, re.I):
            proposed = "Должен: " + proposed
            notes.append("добавить модальность должен/shall")
        if not re.search(r"\d", proposed):
            notes.append("указать численный критерий (если он есть в источнике)")
        if not notes:
            continue
        set_draft(db, req, proposed, reason="; ".join(notes), source="heuristic")
        out.append({"id": req.id, "code": req.code, "proposed": proposed, "reason": "; ".join(notes)})
    if out:
        db.commit()
    return out


def store_drafts_from_text(db: Session, text: str, requirement_ids: list[int] | None) -> list[dict]:
    out: list[dict] = []
    m = re.search(r"\[.*\]", text or "", re.S)
    items = []
    if m:
        try:
            items = json.loads(m.group(0))
        except json.JSONDecodeError:
            items = []
    if not isinstance(items, list) or not items:
        return heuristic_drafts(db, requirement_ids)
    q = db.query(Requirement).filter(Requirement.is_current.is_(True))
    if requirement_ids:
        q = q.filter(Requirement.id.in_(requirement_ids))
    by_id = {r.id: r for r in q.all()}
    by_code = {r.code: r for r in by_id.values()}
    for it in items:
        if not isinstance(it, dict):
            continue
        proposed = str(it.get("suggested") or it.get("стало") or it.get("text") or "").strip()
        if not proposed:
            continue
        req = None
        if it.get("id") and int(it["id"]) in by_id:
            req = by_id[int(it["id"])]
        elif it.get("code") and it["code"] in by_code:
            req = by_code[it["code"]]
        if not req:
            continue
        set_draft(db, req, proposed, reason=str(it.get("reason") or ""), source="llm")
        out.append({"id": req.id, "code": req.code, "proposed": proposed})
    if out:
        db.commit()
        return out
    return heuristic_drafts(db, requirement_ids)


def export_drafts(db: Session, document_id: int | None) -> dict[str, Any]:
    """Отчёт сотруднику: как в файле vs предложение. Двойник не меняется."""
    q = db.query(Requirement).filter(Requirement.is_current.is_(True))
    if document_id:
        q = q.filter(Requirement.document_id == document_id)
    lines = ["# Черновики правок (двойник не изменён)", ""]
    rows = []
    for req in q.all():
        d = latest_draft(db, req.id)
        if not d:
            continue
        lines.append(f"## {req.code}")
        lines.append(f"Как в файле: {req.text}")
        lines.append(f"Предложение ({d.source}): {d.proposed}")
        if d.reason:
            lines.append(f"Зачем: {d.reason}")
        lines.append("")
        rows.append({"code": req.code, "as_loaded": req.text, "proposed": d.proposed, "reason": d.reason, "source": d.source})
    if not rows:
        lines.append("Черновиков нет.")
    downloads = write_text_bundle("drafts", {"output": "\n".join(lines), "rows": rows}, title="Черновики правок")
    return {"count": len(rows), "rows": rows, "downloads": downloads}
