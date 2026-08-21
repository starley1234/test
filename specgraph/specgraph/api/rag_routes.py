from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from specgraph.db import get_db
from specgraph.retrieval.advanced_rag import get_workspace_overview, answer_query, resolve_doc_reference
from specgraph.models import Document, Requirement
from specgraph.config import settings

router = APIRouter(prefix="/rag")


@router.get("/workspace")
def workspace(db: Session = Depends(get_db)):
    ws = get_workspace_overview(db)
    # убираем raw_docs
    return {
        "documents": ws["documents"],
        "totals": ws["totals"],
    }


class QueryRequest(BaseModel):
    query: str
    mode: str = "hybrid"  # hybrid | chunks_only
    top_k: int = 10
    budget_chars: int | None = None


@router.post("/query")
def rag_query(body: QueryRequest, db: Session = Depends(get_db)):
    mode = body.mode if body.mode in ("hybrid", "chunks_only") else "hybrid"
    result = answer_query(db, body.query, mode=mode, top_k=body.top_k, budget_chars=body.budget_chars)
    return result


class DocDetailRequest(BaseModel):
    doc_id: int


@router.get("/document/{doc_id}")
def rag_doc_detail(doc_id: int, db: Session = Depends(get_db)):
    doc = db.get(Document, doc_id)
    if not doc:
        return {"error": "not found"}
    reqs = db.query(Requirement).filter(Requirement.document_id == doc_id, Requirement.is_current.is_(True)).limit(200).all()
    reqs = [r for r in reqs if not (r.extra or {}).get("stub")]
    return {
        "id": doc.id,
        "filename": doc.filename,
        "title": doc.title,
        "status": doc.status,
        "raw_text_preview": (doc.raw_text or "")[:2000],
        "requirements": [
            {"id": r.id, "code": r.code, "title": r.title, "text": r.text[:600], "kind": r.kind.value, "section_path": r.section_path}
            for r in reqs[:100]
        ],
        "requirements_count": len(reqs),
    }


@router.get("/examples")
def examples():
    return [
        {"q": "Какие документы загружены?", "desc": "Мета-вопрос — классический RAG не ответит"},
        {"q": "Сколько требований в документе?", "desc": "COUNT(*) из БД"},
        {"q": "Найди требование с надёжностью", "desc": "Поиск по названию/тексту"},
        {"q": "В каком требовании упоминание про надёжность", "desc": "Семантика — должна найти даже синонимы"},
        {"q": "Найди требование REQ-001", "desc": "Точный поиск по коду"},
        {"q": "Какие требования про безопасность?", "desc": "Гибридный поиск"},
    ]
