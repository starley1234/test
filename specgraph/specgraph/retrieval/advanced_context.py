"""
Advanced context builder for pipelines — использует гибридный RAG с бюджетом.

Идея: pipelines раньше звали gather_context который тянул всё подряд.
Теперь зовём гибридный поиск + pack_with_budget, чтобы не жечь токены.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from specgraph.config import settings
from specgraph.retrieval.advanced_rag import (
    get_workspace_overview,
    search_requirements_hybrid,
    search_chunks,
    pack_with_budget,
    resolve_doc_reference,
    tokenize,
)
from specgraph.models import Document, Requirement
from specgraph.retrieval.context import expand_requirement, expand_product


def estimate_tokens(chars: int) -> int:
    ratio = settings.rag_token_ratio or 3.5
    return int(chars / ratio)


def gather_advanced_rag_context(
    db: Session,
    *,
    query: str | None = None,
    product_id: int | None = None,
    product_code: str | None = None,
    requirement_id: int | None = None,
    requirement_ids: list[int] | None = None,
    document_id: int | None = None,
    top_k: int | None = None,
    budget_chars: int | None = None,
    mode: str = "hybrid",
) -> dict[str, Any]:
    """
    Собирает контекст для пайплайна с учётом бюджета.
    Возвращает структуру совместимую со старой gather_context + дополнительные поля.
    """
    budget = budget_chars or settings.rag_max_context_chars or settings.context_budget_chars
    budget = max(500, min(budget, 50000))
    top_k = top_k or settings.rag_default_top_k or 10

    ws = get_workspace_overview(db)
    docs_raw: list[Document] = ws["raw_docs"]
    docs_meta = ws["documents"]
    totals = ws["totals"]

    bundle: dict[str, Any] = {
        "query": query,
        "mode": mode,
        "budget_chars": budget,
        "budget_tokens": estimate_tokens(budget),
        "hits": [],
        "subgraphs": [],
        "requirements": [],
        "chunks": [],
        "documents": docs_meta,
        "totals": totals,
    }

    # 1. если указан конкретный requirement_id — берём его + родителей + связанные
    if requirement_id:
        exp = expand_requirement(db, requirement_id)
        if exp:
            bundle["seed_requirement"] = exp
            # добавляем в requirements для пайплайна
            bundle["requirements"].append({
                "id": exp.get("id"),
                "code": exp.get("code"),
                "text": exp.get("text","")[:1000],
                "kind": exp.get("kind"),
                "section_path": exp.get("section_path"),
            })
            # расширяем продукт если есть
            prod_id = exp.get("product_id")
            if prod_id:
                try:
                    sg = expand_product(db, prod_id, depth=1)
                    if sg:
                        bundle["subgraphs"].append(sg)
                except Exception:
                    pass
        # также добавим чанки упоминаний если нужны
        # (для бюджета — урежем позже)

    # 2. если указан document_id — берём требования этого документа через RAG
    if document_id and not requirement_ids:
        # находим документ
        target_doc = next((d for d in docs_raw if d.id == document_id), None)
        if target_doc:
            # если есть query — используем гибрид, иначе — просто топ из документа
            if query:
                reqs = search_requirements_hybrid(db, query, docs_raw, top_k=top_k, mode="hybrid")
                # фильтруем по документу
                reqs = [r for r in reqs if r.document_id == document_id] or reqs
            else:
                # fallback: первые N из документа
                from specgraph.models import Requirement as ReqModel
                q = db.query(ReqModel).filter(ReqModel.document_id == document_id, ReqModel.is_current.is_(True)).limit(top_k*2).all()
                from specgraph.retrieval.advanced_rag import RetrievedRequirement
                reqs = []
                for r in q:
                    if (r.extra or {}).get("stub"):
                        continue
                    reqs.append(RetrievedRequirement(
                        id=r.id, code=r.code, title=r.title, text=r.text[:800],
                        kind=r.kind.value if hasattr(r.kind,'value') else str(r.kind),
                        document_id=r.document_id, document_filename=target_doc.filename,
                        section_path=r.section_path, score=0.5, match_type="doc_filter"
                    ))
            bundle["retrieved_reqs_raw"] = reqs

    # 3. если есть requirement_ids — берём их напрямую + расширим соседями
    if requirement_ids:
        from specgraph.models import Requirement as ReqModel
        rows = db.query(ReqModel).filter(ReqModel.id.in_(requirement_ids), ReqModel.is_current.is_(True)).all()
        from specgraph.retrieval.advanced_rag import RetrievedRequirement
        reqs = []
        for r in rows:
            fn = next((d.filename for d in docs_raw if d.id == r.document_id), "")
            reqs.append(RetrievedRequirement(
                id=r.id, code=r.code, title=r.title, text=r.text[:1000],
                kind=r.kind.value if hasattr(r.kind,'value') else str(r.kind),
                document_id=r.document_id, document_filename=fn,
                section_path=r.section_path, score=1.0, match_type="direct"
            ))
        bundle["retrieved_reqs_raw"] = reqs

    # 4. если есть query и нет конкретных ids — гибридный поиск
    if query and not requirement_ids and not requirement_id:
        reqs = search_requirements_hybrid(db, query, docs_raw, top_k=top_k, mode="hybrid")
        bundle["retrieved_reqs_raw"] = reqs
        # чанки тоже
        chunks = search_chunks(db, query, docs_raw, top_k=5, mode="hybrid")
        bundle["retrieved_chunks_raw"] = chunks

    # 5. упаковка под бюджет
    raw_reqs = bundle.pop("retrieved_reqs_raw", [])
    raw_chunks = bundle.pop("retrieved_chunks_raw", [])

    # если до сих пор ничего — пробуем взять из seed или по документу
    if not raw_reqs and bundle.get("requirements"):
        # уже есть seed
        pass
    elif raw_reqs:
        packed_reqs, packed_chunks, breakdown = pack_with_budget(
            raw_reqs, raw_chunks, budget,
            req_share=settings.rag_requirements_share,
            chunk_share=settings.rag_chunks_share,
        )
        bundle["requirements"] = [
            {"id": r.id, "code": r.code, "title": r.title, "text": r.text, "kind": r.kind, "section_path": r.section_path, "document_filename": r.document_filename, "score": r.score, "match_type": r.match_type}
            for r in packed_reqs
        ]
        bundle["chunks"] = [
            {"id": c.id, "document_id": c.document_id, "document_filename": c.document_filename, "seq": c.seq, "text": c.text, "score": c.score}
            for c in packed_chunks
        ]
        bundle["budget_breakdown"] = breakdown
        bundle["packed_chars"] = breakdown["used_chars"]
        bundle["budget_chars"] = breakdown["budget_chars"]
    else:
        # ничего не нашли — пустой бюджет
        bundle["requirements"] = bundle.get("requirements", [])
        bundle["chunks"] = []
        bundle["packed_chars"] = 0
        bundle["budget_breakdown"] = {
            "budget_chars": budget,
            "used_chars": 0,
            "requirements_count": len(bundle["requirements"]),
            "chunks_count": 0,
            "estimated_tokens": 0,
            "budget_tokens": estimate_tokens(budget),
        }

    # для совместимости со старым context_as_prompt — генерируем prompt внутри
    from specgraph.retrieval.context import context_as_prompt as old_prompt
    # соберём минимальную структуру которую понимает old_prompt, но с нашими данными
    compat_bundle = {
        "query": bundle.get("query"),
        "requirements": bundle.get("requirements", []),
        "hits": bundle.get("hits", []),
        "subgraphs": bundle.get("subgraphs", []),
        "chunks": bundle.get("chunks", []),
    }
    # если есть chunks — добавим в seed для отладки
    bundle["prompt_preview"] = old_prompt(compat_bundle)[:budget] if bundle["requirements"] else ""

    return bundle


def context_as_prompt_advanced(bundle: dict[str, Any]) -> str:
    """Генерация промпта с учётом бюджета — компактнее чем старый."""
    parts = []
    if bundle.get("query"):
        parts.append(f"Запрос: {bundle['query']}")
    budget = bundle.get("budget_chars", 8000)
    breakdown = bundle.get("budget_breakdown", {})
    parts.append(f"\n[БЮДЖЕТ КОНТЕКСТА: {breakdown.get('used_chars',0)}/{budget} симв. ~{breakdown.get('estimated_tokens',0)}/{breakdown.get('budget_tokens',0)} токенов]")

    reqs = bundle.get("requirements") or []
    if reqs:
        parts.append(f"\n## Требования ({len(reqs)} шт. — упаковано под бюджет)")
        for r in reqs[:20]:
            txt = (r.get("text") or "")[:400]
            parts.append(f"- [{r.get('code')}] ({r.get('kind')}) {txt}")
            if r.get("section_path"):
                parts.append(f"  раздел: {r['section_path']} doc: {r.get('document_filename')}")
    # seed
    seed = bundle.get("seed_requirement")
    if seed:
        parts.append(f"\n## Фокус-требование {seed.get('code')}")
        parts.append((seed.get("text") or "")[:800])
        for p in seed.get("parents") or []:
            parts.append(f"↑ {p.get('code')}: {(p.get('text') or '')[:200]}")

    chunks = bundle.get("chunks") or []
    if chunks:
        parts.append(f"\n## Чанки ({len(chunks)} шт.)")
        for c in chunks[:3]:
            parts.append(f"[{c.get('document_filename')} #{c.get('seq')}] {c.get('text')[:300]}")

    return "\n".join(parts)[:budget]
