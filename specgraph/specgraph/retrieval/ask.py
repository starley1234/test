"""Вопрос к рабочему пространству: сначала граф/мета, потом текст.

Не чанковый RAG. Каталог и счётчики — из таблиц. Поиск по коду — индекс.
Упоминание в тексте — LIKE + векторы, если эмбеддинги есть.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from specgraph.models import Document, DocumentChunk, Requirement


def _cards(db: Session, document_id: int | None = None) -> list[Requirement]:
    q = db.query(Requirement).filter(Requirement.is_current.is_(True))
    if document_id:
        q = q.filter(Requirement.document_id == document_id)
    rows = []
    for r in q.all():
        extra = r.extra or {}
        if extra.get("stub") or extra.get("appendix"):
            continue
        rows.append(r)
    return rows


def workspace(db: Session) -> dict[str, Any]:
    docs = db.query(Document).order_by(Document.id.asc()).all()
    out = []
    for i, d in enumerate(docs, 1):
        cards = _cards(db, d.id)
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
                "stubs": extra.get("stubs") or 0,
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
    if re.search(r"найди\s+(требован|карточка)|требование\s+[A-ZА-Я0-9._\-]+", question, re.I):
        return "lookup"
    if re.search(r"[A-Z]{2,}[-.][A-Z0-9.\-_/]+", question) and re.search(r"найд|покаж|код", q):
        return "lookup"
    return "rag"


def _answer_catalog(ws: dict[str, Any]) -> dict[str, Any]:
    docs = ws["documents"]
    if not docs:
        text = "В рабочем пространстве нет документов. Загрузите файлы слева."
    else:
        lines = [f"Загружено документов: {len(docs)} (карточек всего {ws['total_cards']})."]
        for d in docs:
            lines.append(f"{d['n']}. {d['filename']} — карточек {d['cards']} (id {d['id']})")
        text = "\n".join(lines)
    return {"route": "catalog", "answer": text, "sources": docs}


def _answer_count(q: str, ws: dict[str, Any], db: Session) -> dict[str, Any]:
    doc = _pick_doc(q, ws)
    if doc:
        n = doc["cards"]
        text = f"В документе {doc['n']} «{doc['filename']}» карточек требований: {n}."
        return {"route": "count", "answer": text, "sources": [doc]}
    n = ws["total_cards"]
    text = f"Во всём пространстве карточек требований: {n} (документов {len(ws['documents'])})."
    return {"route": "count", "answer": text, "sources": ws["documents"]}


def _answer_lookup(question: str, db: Session) -> dict[str, Any]:
    code = None
    m = re.search(r"([A-ZА-Я]{2,}[-.][A-ZА-Я0-9.\-_/]+)", question)
    if m:
        code = m.group(1).rstrip(".,;")
    needle = code or question
    needle = re.sub(r"^(найди|покажи|найдите)\s+(требование|карточку)?\s*", "", needle, flags=re.I).strip(" «»\"'")
    q = db.query(Requirement).filter(Requirement.is_current.is_(True))
    rows = []
    for r in q.all():
        extra = r.extra or {}
        if extra.get("stub") or extra.get("appendix"):
            continue
        blob = f"{r.code} {r.base_code} {r.title or ''} {r.text or ''}"
        if needle.lower() in blob.lower() or (code and code.lower() in (r.code or "").lower()):
            rows.append(r)
        if len(rows) >= 8:
            break
    if not rows:
        return {"route": "lookup", "answer": f"Требование «{needle}» в базе не найдено.", "sources": []}
    parts = []
    sources = []
    for r in rows:
        doc = db.get(Document, r.document_id)
        parts.append(f"{r.code}: {(r.text or '')[:280]}")
        sources.append({"requirement_id": r.id, "code": r.code, "document": doc.filename if doc else None})
    return {"route": "lookup", "answer": "\n\n".join(parts), "sources": sources}


def _keyword_hits(db: Session, query: str, limit: int = 8) -> list[dict[str, Any]]:
    words = [w for w in re.findall(r"[а-яёa-z0-9]{4,}", query.lower()) if w not in {"требование", "документ", "найди", "каком", "упоминание", "про"}]
    if not words:
        words = [query.lower().strip()]
    hits = []
    for r in _cards(db):
        blob = f"{r.code} {r.text or ''}".lower()
        score = sum(1 for w in words if w in blob)
        if score:
            hits.append((score, r))
    hits.sort(key=lambda x: -x[0])
    out = []
    for score, r in hits[:limit]:
        doc = db.get(Document, r.document_id)
        out.append(
            {
                "requirement_id": r.id,
                "code": r.code,
                "text": (r.text or "")[:400],
                "document": doc.filename if doc else None,
                "score": score,
                "via": "keyword",
            }
        )
    if len(out) < 3:
        for ch in db.query(DocumentChunk).all():
            blob = (ch.text or "").lower()
            score = sum(1 for w in words if w in blob)
            if not score:
                continue
            doc = db.get(Document, ch.document_id)
            out.append(
                {
                    "chunk_id": ch.id,
                    "document": doc.filename if doc else None,
                    "text": (ch.text or "")[:400],
                    "score": score,
                    "via": "chunk",
                }
            )
            if len(out) >= limit:
                break
    return out[:limit]


def _answer_rag(question: str, db: Session) -> dict[str, Any]:
    hits = _keyword_hits(db, question)
    try:
        from specgraph.retrieval.embeddings import semantic_search

        for emb, score in semantic_search(db, question, top_k=5):
            hits.append(
                {
                    "entity_type": emb.entity_type.value,
                    "entity_id": emb.entity_id,
                    "text": (emb.text or "")[:400],
                    "score": round(float(score), 3),
                    "via": "vector",
                }
            )
    except Exception:  # noqa: BLE001
        pass
    if not hits:
        return {
            "route": "rag",
            "answer": "По тексту ничего не нашёл. Попробуйте код требования или загрузите документ с карточками.",
            "sources": [],
        }
    lines = ["Нашёл по тексту (ключ + вектор, если есть):"]
    for h in hits[:6]:
        who = h.get("code") or h.get("document") or h.get("via")
        lines.append(f"— {who}: {(h.get('text') or '')[:220]}")
    return {"route": "rag", "answer": "\n".join(lines), "sources": hits[:6]}


def ask(db: Session, question: str) -> dict[str, Any]:
    q = (question or "").strip()
    ws = workspace(db)
    route = classify(q)
    if route == "catalog":
        out = _answer_catalog(ws)
    elif route == "count":
        out = _answer_count(q, ws, db)
    elif route == "lookup":
        out = _answer_lookup(q, db)
    else:
        out = _answer_rag(q, db)
    out["question"] = q
    out["workspace"] = {"documents": len(ws["documents"]), "cards": ws["total_cards"]}
    return out
