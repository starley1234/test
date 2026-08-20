"""Вопрос к пространству: граф/мета, потом точечный текст.

Ответ для человека и pack для LLM — короткие строки (код + зачем + 80 символов).
Полный текст карточки — только lookup одной сущности.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from specgraph.models import Document, DocumentChunk, EntityRelation, EntityType, RelationType, Requirement

VOLT = re.compile(r"вольт|\bvdc\b|\bvac\b|\b\d+[.,]?\d*\s*v\b|\b\d+\s*в\b", re.I)


def _is_stub(r: Requirement) -> bool:
    return bool((r.extra or {}).get("stub") or (r.extra or {}).get("appendix"))


def _scope_ids(document_ids: list[int] | None) -> list[int] | None:
    return list(document_ids) if document_ids else None


def _reqs(db: Session, document_ids: list[int] | None, *, stubs: bool | None = False) -> list[Requirement]:
    if document_ids is not None and not document_ids:
        return []
    q = db.query(Requirement).filter(Requirement.is_current.is_(True))
    if document_ids is not None:
        q = q.filter(Requirement.document_id.in_(document_ids))
    out = []
    for r in q.all():
        st = _is_stub(r)
        if stubs is False and st:
            continue
        if stubs is True and not st:
            continue
        out.append(r)
    return out


def workspace(db: Session, document_ids: list[int] | None = None) -> dict[str, Any]:
    if document_ids is not None and not document_ids:
        return {"documents": [], "total_cards": 0}
    q = db.query(Document).order_by(Document.id.asc())
    if document_ids is not None:
        q = q.filter(Document.id.in_(document_ids))
    docs = q.all()
    if document_ids:
        order = {i: n for n, i in enumerate(document_ids)}
        docs = sorted(docs, key=lambda d: order.get(d.id, 999))
    out = []
    for i, d in enumerate(docs, 1):
        cards = _reqs(db, [d.id], stubs=False)
        extra = (d.parse_meta or {}).get("ingest_report") or {}
        out.append(
            {
                "n": i,
                "id": d.id,
                "filename": d.filename,
                "title": d.title,
                "kind": d.kind.value if d.kind else None,
                "status": d.status,
                "cards": len(cards),
                "stubs": extra.get("stubs") or sum(1 for r in _reqs(db, [d.id], stubs=None) if _is_stub(r)),
                "images": extra.get("images") or 0,
            }
        )
    return {"documents": out, "total_cards": sum(x["cards"] for x in out)}


def _pick_doc(q: str, ws: dict[str, Any]) -> dict[str, Any] | None:
    docs = ws["documents"]
    m = re.search(r"документ(?:е|а|у)?\s*[№#]?\s*(\d+)", q, re.I)
    if m:
        n = int(m.group(1))
        for d in docs:
            if d["n"] == n or d["id"] == n:
                return d
    low = q.lower()
    for d in docs:
        name = (d["filename"] or "").lower()
        if name and name in low:
            return d
        stem = name.rsplit(".", 1)[0]
        if stem and len(stem) > 4 and stem in low:
            return d
    return None


def classify(question: str) -> str:
    q = question.lower().strip()
    if re.search(r"какие\s+документ|что\s+загруж|список\s+файл|что\s+в\s+(базе|пространств)", q):
        return "catalog"
    if re.search(r"сколько\s+(требован|карточек|сущност)", q) or re.search(r"число\s+требован", q):
        return "count"
    if re.search(r"не\s+подгруз|заглуш|\bstub\b|источник\s+не|информация\s+о\s+которых\s+не", q):
        return "stubs"
    if re.search(r"зависим|потомк|дочерн|derived|refines|ссылает", q):
        return "dependents"
    if re.search(r"найди\s+требование\s+[A-ZА-Я0-9._\-]", question, re.I):
        return "lookup"
    if re.search(r"[A-Z]{2,}[-.][A-Z0-9.\-_/]+", question) and re.search(r"найд|покаж|код", q):
        return "lookup"
    return "rag"


def pack(lines: list[str], budget: int = 1800) -> str:
    out, n = [], 0
    for ln in lines:
        if n + len(ln) + 1 > budget:
            out.append(f"… ещё {len(lines) - len(out)} строк не влезло")
            break
        out.append(ln)
        n += len(ln) + 1
    return "\n".join(out)


def _line(r: Requirement, why: str) -> str:
    return f"{r.code} [{why}] {(r.text or '')[:80]}"


def _answer_catalog(ws: dict[str, Any]) -> dict[str, Any]:
    docs = ws["documents"]
    if not docs:
        text = "В этом пространстве документов нет. Закиньте файлы слева."
    else:
        lines = [f"В пространстве документов: {len(docs)}, карточек: {ws['total_cards']}."]
        for d in docs:
            lines.append(f"{d['n']}. {d['filename']} — карточек {d['cards']}, stub {d['stubs']}")
        text = pack(lines)
    return {"route": "catalog", "answer": text, "sources": docs, "pack": text}


def _answer_count(q: str, ws: dict[str, Any]) -> dict[str, Any]:
    doc = _pick_doc(q, ws)
    if doc:
        text = f"Документ {doc['n']} «{doc['filename']}»: карточек {doc['cards']}, stub {doc['stubs']}."
        return {"route": "count", "answer": text, "sources": [doc], "pack": text}
    text = f"Пространство: карточек {ws['total_cards']}, документов {len(ws['documents'])}."
    return {"route": "count", "answer": text, "sources": ws["documents"], "pack": text}


def _answer_stubs(db: Session, document_ids: list[int] | None, include_graph: bool) -> dict[str, Any]:
    """Карточки-заглушки и родители, которых нет в загруженных файлах."""
    local = _reqs(db, document_ids, stubs=None)
    stubs = [r for r in local if _is_stub(r)]
    missing_parents = []
    if include_graph:
        ids = {r.id for r in local}
        rels = (
            db.query(EntityRelation)
            .filter(
                EntityRelation.src_type == EntityType.REQUIREMENT,
                EntityRelation.src_id.in_(ids) if ids else False,
                EntityRelation.rel_type.in_([RelationType.DERIVED_FROM, RelationType.REFINES]),
                EntityRelation.dst_type == EntityType.REQUIREMENT,
            )
            .all()
            if ids
            else []
        )
        seen = set()
        for rel in rels:
            p = db.get(Requirement, rel.dst_id)
            if p and _is_stub(p) and p.id not in seen:
                seen.add(p.id)
                missing_parents.append(p)
    rows = stubs + [p for p in missing_parents if p.id not in {s.id for s in stubs}]
    if not rows:
        text = "Все источники в пространстве загружены (stub нет)."
        return {"route": "stubs", "answer": text, "sources": [], "pack": text}
    lines = [f"Не подгружено / stub: {len(rows)}"]
    src = []
    for r in rows[:40]:
        lines.append(_line(r, "stub"))
        src.append({"id": r.id, "code": r.code, "stub": True})
    text = pack(lines)
    return {"route": "stubs", "answer": text, "sources": src, "pack": text}


def _answer_dependents(db: Session, document_ids: list[int] | None, include_graph: bool) -> dict[str, Any]:
    """Требования, которые ссылаются на карточки пространства (дети / derived_from)."""
    roots = _reqs(db, document_ids, stubs=False)
    root_ids = {r.id for r in roots}
    if not root_ids:
        return {"route": "dependents", "answer": "В пространстве нет карточек.", "sources": [], "pack": ""}
    q = db.query(EntityRelation).filter(
        EntityRelation.dst_type == EntityType.REQUIREMENT,
        EntityRelation.dst_id.in_(root_ids),
        EntityRelation.src_type == EntityType.REQUIREMENT,
        EntityRelation.rel_type.in_([RelationType.DERIVED_FROM, RelationType.REFINES, RelationType.DEPENDS_ON]),
    )
    rels = q.all()
    kids_by_parent: dict[int, list[Requirement]] = {}
    for rel in rels:
        child = db.get(Requirement, rel.src_id)
        if not child:
            continue
        if not include_graph and document_ids and child.document_id not in document_ids:
            continue
        kids_by_parent.setdefault(rel.dst_id, []).append(child)
    for r in roots:
        if r.parent_id:
            continue
        for c in db.query(Requirement).filter(Requirement.parent_id == r.id).all():
            if not include_graph and document_ids and c.document_id not in document_ids:
                continue
            kids_by_parent.setdefault(r.id, []).append(c)
    if not kids_by_parent:
        text = "Зависимых (derived_from / дети) в выбранном контуре нет."
        return {"route": "dependents", "answer": text, "sources": [], "pack": text}
    by_id = {r.id: r for r in roots}
    lines = [f"Зависимые связи: {sum(len(v) for v in kids_by_parent.values())}"]
    src = []
    for pid, kids in list(kids_by_parent.items())[:30]:
        p = by_id.get(pid) or db.get(Requirement, pid)
        pname = p.code if p else str(pid)
        for c in kids[:8]:
            extra = "" if (not document_ids or c.document_id in document_ids) else " вне пространства"
            lines.append(f"{c.code} → {pname}{extra} {(c.text or '')[:60]}")
            src.append({"id": c.id, "code": c.code, "parent": pname})
    text = pack(lines)
    return {"route": "dependents", "answer": text, "sources": src, "pack": text}


def _answer_lookup(question: str, db: Session, document_ids: list[int] | None) -> dict[str, Any]:
    code = None
    m = re.search(r"([A-ZА-Я]{2,}[-.][A-ZА-Я0-9.\-_/]+)", question)
    if m:
        code = m.group(1).rstrip(".,;")
    needle = code or question
    needle = re.sub(r"^(найди|покажи|найдите)\s+(требование|карточку)?\s*", "", needle, flags=re.I).strip(" «»\"'")
    rows = []
    for r in _reqs(db, document_ids, stubs=None):
        blob = f"{r.code} {r.base_code} {r.title or ''} {r.text or ''}"
        if needle.lower() in blob.lower() or (code and code.lower() in (r.code or "").lower()):
            rows.append(r)
        if len(rows) >= 5:
            break
    if not rows:
        return {"route": "lookup", "answer": f"«{needle}» в пространстве нет.", "sources": [], "pack": ""}
    parts = []
    sources = []
    for r in rows:
        doc = db.get(Document, r.document_id)
        parts.append(f"{r.code} ({'stub' if _is_stub(r) else 'карточка'}, {doc.filename if doc else '?'}):\n{(r.text or '')[:500]}")
        sources.append({"requirement_id": r.id, "code": r.code, "document": doc.filename if doc else None})
    text = pack(parts, 2500)
    return {"route": "lookup", "answer": text, "sources": sources, "pack": text}


def _mention_needles(question: str) -> list[str]:
    q = question.lower()
    extra = []
    if VOLT.search(q) or "вольт" in q:
        extra.extend(["вольт", "vdc", "vac", " в ", "v "])
    words = [w for w in re.findall(r"[а-яёa-z0-9]{3,}", q) if w not in {"требование", "документ", "найди", "каком", "упоминание", "про", "которых", "есть"}]
    return extra + words


def _answer_rag(question: str, db: Session, document_ids: list[int] | None) -> dict[str, Any]:
    needles = _mention_needles(question)
    hits: list[tuple[int, Requirement, str]] = []
    for r in _reqs(db, document_ids, stubs=False):
        blob = f"{r.code} {r.text or ''}".lower()
        score = sum(1 for w in needles if w in blob)
        if VOLT.search(question) and VOLT.search(blob):
            score += 3
        if score:
            hits.append((score, r, "card"))
    if document_ids:
        chq = db.query(DocumentChunk).filter(DocumentChunk.document_id.in_(document_ids))
    else:
        chq = db.query(DocumentChunk)
    chunk_hits = []
    for ch in chq.all():
        blob = (ch.text or "").lower()
        score = sum(1 for w in needles if w in blob)
        if VOLT.search(question) and VOLT.search(blob):
            score += 2
        if score:
            chunk_hits.append((score, ch))
    hits.sort(key=lambda x: -x[0])
    chunk_hits.sort(key=lambda x: -x[0])
    if not hits and not chunk_hits:
        return {
            "route": "rag",
            "answer": "Упоминаний в карточках пространства нет.",
            "sources": [],
            "pack": "",
        }
    lines = [f"Упоминания в карточках: {len(hits)}"]
    src = []
    for score, r, _ in hits[:12]:
        lines.append(_line(r, f"hit {score}"))
        src.append({"id": r.id, "code": r.code, "via": "card"})
    if not hits and chunk_hits:
        lines = ["В карточках пусто, есть сырые чанки:"]
        for score, ch in chunk_hits[:4]:
            doc = db.get(Document, ch.document_id)
            lines.append(f"чанк {doc.filename if doc else ch.document_id}: {(ch.text or '')[:120]}")
    text = pack(lines)
    return {"route": "rag", "answer": text, "sources": src, "pack": text}


def ask(
    db: Session,
    question: str,
    *,
    document_ids: list[int] | None = None,
    include_graph: bool = False,
) -> dict[str, Any]:
    q = (question or "").strip()
    ids = _scope_ids(document_ids)
    ws = workspace(db, ids)
    route = classify(q)
    if route == "catalog":
        out = _answer_catalog(ws)
    elif route == "count":
        out = _answer_count(q, ws)
    elif route == "stubs":
        out = _answer_stubs(db, ids, include_graph)
    elif route == "dependents":
        out = _answer_dependents(db, ids, include_graph)
    elif route == "lookup":
        out = _answer_lookup(q, db, ids)
    else:
        out = _answer_rag(q, db, ids)
    out["question"] = q
    out["include_graph"] = include_graph
    out["workspace"] = {"documents": len(ws["documents"]), "cards": ws["total_cards"]}
    return out
