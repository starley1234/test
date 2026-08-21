"""
Продвинутый гибридный RAG для конструктора.

Проблема классического чанкового RAG:
- "Какие документы загружены?" — в топ-3 чанков этого нет.
- "Сколько требований в Документе X" — чанки не знают мета.
- "Найди требование REQ-123" — чанки разбивают код.

Наш подход:
1. Intent Router — определяем тип вопроса
2. Meta Layer — точные ответы из БД (документы, счётчики, поиск по коду)
3. Lexical Layer — LIKE поиск по требованиям/чанкам
4. Vector Layer — семантика по embeddings (requirements)
5. Fusion — склейка с объяснением почему сработало

Workspace = все документы = отправная точка.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, asdict
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from specgraph.models import Document, DocumentChunk, Requirement, Product, Embedding, EntityType


STOPWORDS = {
    "и","в","во","не","что","он","на","я","с","со","как","а","то","все","она","так","его","но","да","ты","к","у","же","вы","за","бы","по","только",
    "ее","мне","было","вот","от","меня","еще","нет","о","из","ему","теперь","когда","даже","ну","вдруг","ли","если","уже","или","ни","быть",
    "был","него","до","вас","нибудь","опять","уж","вам","ведь","там","потом","себя","ничего","ей","может","они","тут","где","есть","надо",
    "ней","для","мы","тебя","их","чем","была","сам","чтоб","без","будто","чего","раз","тоже","себе","под","будет","ж","тогда","кто","этот",
    "того","потому","этого","какой","совсем","ним","здесь","этом","один","почти","мой","тем","чтобы","нее","сейчас","были","куда","зачем",
    "сказать","ка","всех","никогда","сегодня","можно","при","наконец","два","об","другой","хоть","после","над","больше","тот","через","эти",
    "нас","про","всего","них","какая","много","разве","три","эту","моя","впрочем","хорошо","свою","этой","перед","иногда","лучше","чуть",
    "том","нельзя","такой","им","более","всегда","конечно","всю","между","какие","какой","какая","какое"
}

def tokenize(q: str) -> list[str]:
    q = q.lower()
    tokens = re.findall(r"[a-zа-яё0-9]+", q)
    return [t for t in tokens if t not in STOPWORDS and len(t) > 1]

def extract_requirement_code(text: str) -> list[str]:
    patterns = [
        r"\b[A-ZА-Я]{1,10}[-_]\d+[\w\.\-]*\b",
        r"\b[A-Z]{2,}\d+\b",
        r"\b\d+(?:\.\d+){1,5}\b",
        r"\bREQ\b[^\s]*\d+\b",
        r"\bТ\d+[\.\-]\d*\b",
    ]
    found = []
    up = text.upper()
    for pat in patterns:
        for m in re.finditer(pat, up):
            found.append(m.group(0).strip())
    for m in re.finditer(r'"([^"]+)"', text):
        s = m.group(1).strip()
        if len(s) >= 2 and len(s) <= 120:
            found.append(s)
    for m in re.finditer(r"[«»]([^«»]+)[«»]", text):
        s = m.group(1).strip()
        if len(s) >= 2 and len(s) <= 120:
            found.append(s)
    seen = set()
    uniq = []
    for f in found:
        if f not in seen and len(f) >= 2:
            seen.add(f)
            uniq.append(f)
    return uniq[:5]

def resolve_doc_reference(query: str, docs: list[Document]) -> Document | None:
    q_low = query.lower()
    m = re.search(r"документ[аеу]?\s+(\d+)", q_low)
    if m:
        try:
            did = int(m.group(1))
            for d in docs:
                if d.id == did:
                    return d
        except:
            pass
    m2 = re.search(r"(?:в\s+)?документ[ае]?\s+([^\s\?\,\.]+)", q_low)
    if m2:
        needle = m2.group(1).strip().strip('"«»')
        if needle:
            for d in docs:
                if needle in d.filename.lower() or (d.title and needle in d.title.lower()):
                    return d
            for d in docs:
                if needle.isdigit() and needle in d.filename:
                    return d
    for d in docs:
        fn = d.filename.lower()
        base = fn.rsplit(".",1)[0]
        if base and len(base) >= 3 and base in q_low:
            return d
    if len(docs) == 1:
        return docs[0]
    return None


@dataclass
class RetrievedRequirement:
    id: int
    code: str
    title: str | None
    text: str
    kind: str
    document_id: int
    document_filename: str
    section_path: str | None
    score: float
    match_type: str
    highlight: str = ""

@dataclass
class RetrievedChunk:
    id: int
    document_id: int
    document_filename: str
    seq: int
    text: str
    score: float
    match_type: str

@dataclass
class RetrievedDoc:
    id: int
    filename: str
    title: str | None
    requirements_count: int
    chunks_count: int
    status: str


def get_workspace_overview(db: Session) -> dict[str, Any]:
    docs = db.query(Document).order_by(Document.id.desc()).all()
    overview = []
    for d in docs:
        rc = db.query(Requirement).filter(Requirement.document_id == d.id, Requirement.is_current.is_(True)).count()
        cc = db.query(DocumentChunk).filter(DocumentChunk.document_id == d.id).count()
        overview.append(
            RetrievedDoc(
                id=d.id,
                filename=d.filename,
                title=d.title,
                requirements_count=rc,
                chunks_count=cc,
                status=d.status,
            )
        )
    total_reqs = db.query(Requirement).filter(Requirement.is_current.is_(True)).count()
    total_chunks = db.query(DocumentChunk).count()
    total_prods = db.query(Product).count()
    total_emb = db.query(Embedding).count()
    return {
        "documents": [asdict(x) for x in overview],
        "totals": {
            "documents": len(docs),
            "requirements": total_reqs,
            "chunks": total_chunks,
            "products": total_prods,
            "embeddings": total_emb,
        },
        "raw_docs": docs,
    }


def classify_intent(query: str) -> tuple[str, float, str]:
    q = query.lower().strip()
    list_triggers = [
        "какие документы", "список документов", "какие файлы", "что загружено",
        "какие есть документы", "перечисли документы", "покажи документы",
        "какие документы загружены", "какие документы в", "что в воркспейсе",
        "что в рабочем", "workspace", "сколько документов"
    ]
    if any(t in q for t in list_triggers):
        return "list_docs", 0.95, "Ключевые слова про список документов — классический RAG этого не знает, т.к. в топ-3 чанка не попадает полный список"

    count_triggers = [
        "сколько требований", "количество требований", "число требований",
        "сколько всего требований", "кол-во требований"
    ]
    if any(t in q for t in count_triggers):
        return "count_requirements", 0.9, "Требуется мета-информация из БД — COUNT(*) по документу, а не поиск по чанкам"

    find_triggers = [
        "найди требование", "найти требование", "покажи требование", "где требование",
        "найди такое", "найди документ", "найти по коду", "требование с кодом",
        "требование с названием", "отыщи требование"
    ]
    codes = extract_requirement_code(query)
    if any(t in q for t in find_triggers) or codes:
        if codes:
            return "find_requirement", 0.85, f"Запрос содержит код/название {codes} — ищем точным совпадением по code/title БД"
        return "find_requirement", 0.6, "Похоже на поиск конкретного требования по названию"

    semantic_triggers = ["в каком требовании", "где упомина", "про надёжность", "про надежность", "про безопасность", "какие требования про", "требования связанные"]
    if any(t in q for t in semantic_triggers):
        return "semantic", 0.75, "Вопрос про содержание — подходит классический RAG + векторный поиск"

    return "semantic", 0.5, "Общий вопрос — используем гибрид: вектора + лексика + мета"


def lexical_score(text: str, query_tokens: list[str]) -> float:
    if not text or not query_tokens:
        return 0.0
    low = text.lower()
    hit = 0
    for tok in query_tokens:
        if tok in low:
            hit += 1
    return hit / len(query_tokens) if query_tokens else 0.0


def semantic_search_requirements(db: Session, query: str, top_k: int = 20) -> list[tuple[Requirement, float, str]]:
    try:
        from specgraph.retrieval.embeddings import encode
        qv = encode([query])[0]
    except Exception:
        qv = None

    hits: list[tuple[Requirement, float, str]] = []

    if qv is not None:
        embs = db.query(Embedding).filter(Embedding.entity_type == EntityType.REQUIREMENT).all()
        if embs:
            import numpy as np
            q_arr = np.asarray(qv, dtype=float)
            q_norm = float(np.linalg.norm(q_arr)) or 1.0
            scored = []
            for emb in embs:
                try:
                    v = np.asarray(emb.vector, dtype=float)
                    denom = (float(np.linalg.norm(v)) or 1.0) * q_norm
                    score = float(np.dot(v, q_arr) / denom) if denom else 0.0
                except Exception:
                    score = 0.0
                scored.append((emb, score))
            scored.sort(key=lambda x: x[1], reverse=True)
            for emb, sc in scored[:top_k*2]:
                req = db.get(Requirement, emb.entity_id)
                if req and req.is_current:
                    if (req.extra or {}).get("stub"):
                        continue
                    hits.append((req, sc, emb.text[:500]))
            best = {}
            for req, sc, txt in hits:
                if req.id not in best or best[req.id][1] < sc:
                    best[req.id] = (req, sc, txt)
            hits = list(best.values())
            hits.sort(key=lambda x: x[1], reverse=True)
            return hits[:top_k]
    return []


def search_requirements_hybrid(db: Session, query: str, docs: list[Document], top_k: int = 10, mode: str = "hybrid") -> list[RetrievedRequirement]:
    tokens = tokenize(query)
    codes = extract_requirement_code(query)

    exact_matches: list[RetrievedRequirement] = []
    if codes:
        for code in codes:
            q = db.query(Requirement).options(joinedload(Requirement.document)).filter(
                Requirement.is_current.is_(True),
                or_(
                    func.lower(Requirement.code) == code.lower(),
                    func.lower(Requirement.code).like(f"%{code.lower()}%"),
                    func.lower(Requirement.title).like(f"%{code.lower()}%") if Requirement.title else False,
                )
            ).limit(10).all()
            for r in q:
                if (r.extra or {}).get("stub"):
                    continue
                doc_fn = ""
                for d in docs:
                    if d.id == r.document_id:
                        doc_fn = d.filename
                        break
                exact_matches.append(RetrievedRequirement(
                    id=r.id, code=r.code, title=r.title, text=r.text[:1000],
                    kind=r.kind.value if r.kind else "unknown",
                    document_id=r.document_id, document_filename=doc_fn,
                    section_path=r.section_path,
                    score=1.0, match_type="exact_code",
                    highlight=code
                ))
    if exact_matches:
        seen = set()
        uniq = []
        for m in exact_matches:
            if m.id not in seen:
                seen.add(m.id)
                uniq.append(m)
        return uniq[:top_k]

    all_reqs = db.query(Requirement).options(joinedload(Requirement.attributes)).filter(
        Requirement.is_current.is_(True)
    ).limit(2000).all()
    all_reqs = [r for r in all_reqs if not (r.extra or {}).get("stub")]

    doc_map = {d.id: d.filename for d in docs}

    sem_map: dict[int, float] = {}
    if mode in ("hybrid", "semantic"):
        sem_hits = semantic_search_requirements(db, query, top_k=top_k*2)
        for req, sc, txt in sem_hits:
            sem_map[req.id] = sc

    scored: list[RetrievedRequirement] = []
    for r in all_reqs:
        lex = lexical_score(f"{r.code} {r.title or ''} {r.text}", tokens)
        sem = sem_map.get(r.id, 0.0)
        if mode == "hybrid":
            combined = sem*0.7 + lex*0.3 if sem > 0 else lex
        elif mode == "semantic":
            combined = sem if sem>0 else lex*0.5
        else:
            combined = lex

        if combined < 0.05 and mode != "chunks_only":
            if not (sem > 0.2):
                continue

        hl = ""
        for tok in tokens:
            if tok in (r.text or "").lower():
                hl = tok
                break

        match_type = "combined" if (lex>0 and sem>0) else ("semantic" if sem>lex else "lexical")
        scored.append(RetrievedRequirement(
            id=r.id, code=r.code, title=r.title, text=(r.text or "")[:1000],
            kind=r.kind.value if hasattr(r.kind,'value') else str(r.kind),
            document_id=r.document_id, document_filename=doc_map.get(r.document_id, ""),
            section_path=r.section_path,
            score=round(float(combined), 4),
            match_type=match_type,
            highlight=hl
        ))

    scored.sort(key=lambda x: x.score, reverse=True)
    return scored[:top_k]


def search_chunks(db: Session, query: str, docs: list[Document], top_k: int = 6, mode: str = "hybrid") -> list[RetrievedChunk]:
    tokens = tokenize(query)
    if not tokens:
        tokens = [query.lower()][:1]

    all_chunks = db.query(DocumentChunk).limit(5000).all()
    doc_map = {d.id: d.filename for d in docs}

    scored = []
    for ch in all_chunks:
        txt_low = (ch.text or "").lower()
        lex = lexical_score(txt_low, tokens)
        if lex < 0.01 and mode == "hybrid":
            continue
        if mode == "chunks_only" and lex == 0:
            if query.lower()[:4] not in txt_low:
                continue
        scored.append(RetrievedChunk(
            id=ch.id,
            document_id=ch.document_id,
            document_filename=doc_map.get(ch.document_id, f"doc {ch.document_id}"),
            seq=ch.seq,
            text=(ch.text or "")[:800],
            score=round(float(lex), 4),
            match_type="lexical"
        ))
    scored.sort(key=lambda x: x.score, reverse=True)
    k = 3 if mode == "chunks_only" else top_k
    return scored[:k]


def truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    # пробуем обрезать по предложению
    cut = text[:max_chars]
    last_dot = max(cut.rfind("."), cut.rfind("\n"))
    if last_dot > max_chars * 0.5:
        return cut[: last_dot + 1] + "…"
    return cut + "…"


def pack_with_budget(
    reqs: list[RetrievedRequirement],
    chunks: list[RetrievedChunk],
    budget: int,
    req_share: float = 0.7,
    chunk_share: float = 0.2,
) -> tuple[list[RetrievedRequirement], list[RetrievedChunk], dict]:
    """Упаковка под бюджет: приоритизируем по score, усекаем тексты."""
    from specgraph.config import settings as cfg

    req_budget = int(budget * req_share)
    chunk_budget = int(budget * chunk_share)
    # meta 10% не используется тут, но учитывается в breakdown

    packed_reqs: list[RetrievedRequirement] = []
    used_req = 0
    per_req_avg = max(120, req_budget // max(1, len(reqs)) if reqs else 120)

    for r in sorted(reqs, key=lambda x: x.score, reverse=True):
        # сколько можем отдать этому требованию
        remaining = req_budget - used_req
        if remaining < 50:
            break
        # даём минимум 120, максимум per_req_avg*1.5 но не больше remaining
        alloc = min(remaining, max(120, min(per_req_avg * 2, 500)))
        # усекаем текст
        orig_len = len(r.text)
        truncated = truncate_text(r.text, max(80, alloc - 30))  # 30 на мета
        r_packed = RetrievedRequirement(
            id=r.id,
            code=r.code,
            title=r.title,
            text=truncated,
            kind=r.kind,
            document_id=r.document_id,
            document_filename=r.document_filename,
            section_path=r.section_path,
            score=r.score,
            match_type=r.match_type,
            highlight=r.highlight,
        )
        packed_reqs.append(r_packed)
        used_req += len(truncated) + len(r.code) + 20

    packed_chunks: list[RetrievedChunk] = []
    used_chunk = 0
    for c in sorted(chunks, key=lambda x: x.score, reverse=True):
        remaining = chunk_budget - used_chunk
        if remaining < 50:
            break
        alloc = min(remaining, 300)
        truncated = truncate_text(c.text, max(50, alloc - 20))
        c_packed = RetrievedChunk(
            id=c.id,
            document_id=c.document_id,
            document_filename=c.document_filename,
            seq=c.seq,
            text=truncated,
            score=c.score,
            match_type=c.match_type,
        )
        packed_chunks.append(c_packed)
        used_chunk += len(truncated) + 20

    used_total = used_req + used_chunk
    breakdown = {
        "budget_chars": budget,
        "requirements_chars": used_req,
        "chunks_chars": used_chunk,
        "used_chars": used_total,
        "remaining_chars": max(0, budget - used_total),
        "requirements_count": len(packed_reqs),
        "chunks_count": len(packed_chunks),
        "estimated_tokens": int(used_total / (cfg.rag_token_ratio or 3.5)),
        "budget_tokens": int(budget / (cfg.rag_token_ratio or 3.5)),
    }
    return packed_reqs, packed_chunks, breakdown


def answer_query(db: Session, query: str, mode: str = "hybrid", top_k: int = 10, budget_chars: int | None = None) -> dict[str, Any]:
    t0 = time.time()
    ws = get_workspace_overview(db)
    docs_raw: list[Document] = ws["raw_docs"]
    docs_meta = ws["documents"]
    totals = ws["totals"]

    # бюджет контекста
    from specgraph.config import settings
    budget = budget_chars or settings.rag_max_context_chars or settings.context_budget_chars
    # ограничим разумными пределами
    budget = max(500, min(budget, 50000))

    intent, conf, explanation = classify_intent(query)

    answer_text = ""
    retrieved_reqs: list[RetrievedRequirement] = []
    retrieved_chunks: list[RetrievedChunk] = []
    reasoning = ""
    docs_used: list[dict] = []

    if not docs_raw:
        return {
            "intent": "empty_workspace",
            "confidence": 1.0,
            "explanation": "Воркспейс пуст — загрузите документы",
            "answer": "Воркспейсе пока нет документов. Загрузите .docx/.pdf в левую панель.",
            "documents": [],
            "totals": totals,
            "requirements": [],
            "chunks": [],
            "reasoning": "Нет данных для RAG — сначала индексация",
            "timing_ms": int((time.time()-t0)*1000),
            "mode": mode,
        }

    if intent == "list_docs":
        if mode == "chunks_only":
            retrieved_chunks = search_chunks(db, query, docs_raw, top_k=3, mode="chunks_only")
            if retrieved_chunks:
                answer_text = f"[CLASSIC RAG FAIL] В топ-3 чанках нашлось только {len(retrieved_chunks)} упоминания, но полный список документов восстановить нельзя:\n" + "\n".join([f"• {c.document_filename} chunk {c.seq}: {c.text[:120]}..." for c in retrieved_chunks])
            else:
                answer_text = "[CLASSIC RAG FAIL] В режиме 'только чанки' (top_k=3) нет информации о полном списке документов. Чанки не содержат мета. Нужен мета-слой."
            docs_used = []
            reasoning = "Классический RAG: берёт 3 чанка и не может ответить сколько всего документов, потому что мета не в чанках."
        else:
            lines = [f"Загружено {len(docs_raw)} документ(ов):"]
            for d in docs_meta:
                lines.append(f"• {d['filename']} — {d['requirements_count']} требований, {d['chunks_count']} чанков, id={d['id']}")
            answer_text = "\n".join(lines)
            docs_used = docs_meta
            reasoning = (
                "Классический чанковый RAG отвечает только по топ-3 чанкам, поэтому не может перечислить все 20 документов. "
                "Мы отвечаем напрямую из таблицы documents (мета-слой), а чанки даже не трогаем."
            )

    elif intent == "count_requirements":
        if mode == "chunks_only":
            retrieved_chunks = search_chunks(db, query, docs_raw, top_k=3, mode="chunks_only")
            answer_text = "[CLASSIC RAG FAIL] COUNT(*) по требованиям нельзя получить из 3 чанков. Даже если в документе 100 требований, чанки видят 3 окна по 1200 символов."
            if retrieved_chunks:
                answer_text += "\nЧанки: " + "; ".join([f"{c.document_filename}#{c.seq}" for c in retrieved_chunks])
            docs_used = []
            reasoning = "COUNT требует мета-информации из БД, а не векторного поиска."
        else:
            target_doc = resolve_doc_reference(query, docs_raw)
            if target_doc:
                cnt = db.query(Requirement).filter(
                    Requirement.document_id == target_doc.id,
                    Requirement.is_current.is_(True)
                ).count()
                cnt_real_q = db.query(Requirement).filter(
                    Requirement.document_id == target_doc.id,
                    Requirement.is_current.is_(True)
                ).all()
                cnt_real = len([r for r in cnt_real_q if not (r.extra or {}).get("stub")])
                answer_text = f"В документе «{target_doc.filename}» (id={target_doc.id}) найдено {cnt_real} требования. Всего записей в БД по этому документу (включая stub): {cnt}."
                examples = db.query(Requirement).filter(
                    Requirement.document_id == target_doc.id,
                    Requirement.is_current.is_(True)
                ).limit(5).all()
                retrieved_reqs = [
                    RetrievedRequirement(
                        id=r.id, code=r.code, title=r.title, text=(r.text or "")[:500],
                        kind=r.kind.value if hasattr(r.kind,'value') else str(r.kind),
                        document_id=r.document_id, document_filename=target_doc.filename,
                        section_path=r.section_path, score=1.0, match_type="meta"
                    ) for r in examples if not (r.extra or {}).get("stub")
                ]
                docs_used = [d for d in docs_meta if d['id']==target_doc.id]
                reasoning = (
                    "COUNT(*) из таблицы requirements, а не поиск по векторам. "
                    "Даже если документ большой (100+ требований) и чанков 3 — мета-ответ точен. "
                    "Классический RAG тут угадывает или говорит 'не знаю'."
                )
            else:
                lines = [f"Всего в воркспейсе {totals['requirements']} требований в {totals['documents']} документах:"]
                for d in docs_meta:
                    lines.append(f"• {d['filename']}: {d['requirements_count']} требований")
                answer_text = "\n".join(lines)
                docs_used = docs_meta
                reasoning = "Документ не распознался — отдали статистику по всему воркспейсу. Уточните имя файла или ID для точного ответа."

    elif intent == "find_requirement":
        retrieved_reqs = search_requirements_hybrid(db, query, docs_raw, top_k=top_k, mode=mode)
        if mode == "chunks_only":
            retrieved_chunks = search_chunks(db, query, docs_raw, top_k=10, mode=mode)
            if not retrieved_reqs and not retrieved_chunks:
                answer_text = "В режиме 'только чанки' по этому запросу ничего не нашлось. Чанки разбивают код требования и не хранят мета."
            elif retrieved_reqs:
                answer_text = f"[CLASSIC RAG PARTIAL] Найдено {len(retrieved_reqs)} требований (но без точного кода, только лекс):\n" + "\n".join([f"• [{r.code}] {r.text[:120]}..." for r in retrieved_reqs])
            else:
                answer_text = f"[CLASSIC RAG FAIL] Требований не нашлось, но есть чанки:\n" + "\n".join([f"• doc {c.document_filename} seq {c.seq}: {c.text[:100]}..." for c in retrieved_chunks])
            reasoning = "Чанковый RAG по коду проваливается, т.к. код может быть разрезан между чанками или в таблице."
        else:
            retrieved_chunks = search_chunks(db, query, docs_raw, top_k=3, mode=mode)
            if retrieved_reqs:
                answer_text = f"Нашёл {len(retrieved_reqs)} подходящих требования:\n" + "\n".join(
                    [f"• [{r.code}] ({r.kind}) — {r.text[:160]}... (doc: {r.document_filename}, score={r.score}, {r.match_type})" for r in retrieved_reqs[:5]]
                )
            else:
                answer_text = "Не нашёл требований по такому коду/названию. Попробуйте другие ключевые слова или проверьте список документов."
            reasoning = (
                "Сначала ищем точное совпадение по code/title (БД), потом — гибрид: вектора (семантика кода) + лексика (LIKE). "
                "Чанковый RAG часто не находит код, потому что код разрезан на чанки или встречается отдельно от текста."
            )
        docs_used = docs_meta

    else:  # semantic
        if mode == "chunks_only":
            retrieved_chunks = search_chunks(db, query, docs_raw, top_k=3, mode=mode)
            retrieved_reqs = []
            if retrieved_chunks:
                answer_text = f"Классический RAG нашёл {len(retrieved_chunks)} чанка:\n" + "\n".join(
                    [f"• {c.document_filename} [chunk {c.seq}] score={c.score}: {c.text[:200]}..." for c in retrieved_chunks]
                )
            else:
                answer_text = "В режиме 'только чанки' ничего не нашлось по этому запросу"
            reasoning = "Только чанки (top-3). Теряется информация о том, в каком именно требовании встречается термин, особенно если термин в атрибутах, а не в теле чанка."
            docs_used = docs_meta
        else:
            retrieved_reqs = search_requirements_hybrid(db, query, docs_raw, top_k=top_k, mode="hybrid")
            retrieved_chunks = search_chunks(db, query, docs_raw, top_k=5, mode="hybrid")
            if retrieved_reqs:
                answer_text = (
                    f"Нашёл упоминания в {len(retrieved_reqs)} требованиях (гибрид вектора+лексика):\n"
                    + "\n".join([f"• [{r.code}] {r.document_filename} score={r.score} {r.match_type}: {r.text[:200]}..." for r in retrieved_reqs[:7]])
                )
                if retrieved_chunks:
                    answer_text += "\n\nДополнительно чанки:\n" + "\n".join(
                        [f"• {c.document_filename} chunk {c.seq}: {c.text[:120]}..." for c in retrieved_chunks[:3]]
                    )
            else:
                if retrieved_chunks:
                    answer_text = f"Требований не нашёл, но есть чанки:\n" + "\n".join([f"• {c.document_filename} {c.seq}: {c.text[:200]}..." for c in retrieved_chunks])
                else:
                    answer_text = "По запросу ничего не нашлось ни в требованиях, ни в чанках. Попробуйте переформулировать или проверьте что документы загружены."
            reasoning = (
                "Гибрид: 1) вектора по embeddings (находит 'надёжность' даже если написано 'MTBF'), "
                "2) лексика по БД (LIKE по тексту, не по чанкам), "
                "3) чанки как дополнительный контекст. "
                "В отличие от чистого чанкового RAG, мы возвращаем код требования и документ-источник."
            )
            docs_used = docs_meta

    # применяем бюджетную упаковку (если не meta-ответы)
    breakdown = None
    try:
        from specgraph.config import settings as cfg2
        if retrieved_reqs or retrieved_chunks:
            # для list_docs/count — не пакуем, там ответ meta
            if intent not in ("list_docs", "count_requirements") or mode == "chunks_only":
                packed_reqs, packed_chunks, breakdown = pack_with_budget(
                    retrieved_reqs, retrieved_chunks, budget,
                    req_share=cfg2.rag_requirements_share,
                    chunk_share=cfg2.rag_chunks_share,
                )
                # перестраиваем ответ для semantic/find, если было много
                if intent in ("find_requirement", "semantic") and mode != "chunks_only":
                    # если упаковка отбросила часть — покажем сколько влезло
                    if breakdown and breakdown["requirements_count"] < len(retrieved_reqs):
                        answer_text += f"\n\n[БЮДЖЕТ] Показано {breakdown['requirements_count']} из {len(retrieved_reqs)} требований, {breakdown['chunks_count']} из {len(retrieved_chunks)} чанков в лимите {budget} симв. (~{breakdown['budget_tokens']} ток). Использовано {breakdown['used_chars']} симв. (~{breakdown['estimated_tokens']} ток)."
                retrieved_reqs, retrieved_chunks = packed_reqs, packed_chunks
            else:
                # для meta — считаем breakdown нулевым
                breakdown = {
                    "budget_chars": budget,
                    "requirements_chars": 0,
                    "chunks_chars": 0,
                    "used_chars": 0,
                    "remaining_chars": budget,
                    "requirements_count": 0,
                    "chunks_count": 0,
                    "estimated_tokens": 0,
                    "budget_tokens": int(budget / (cfg2.rag_token_ratio or 3.5)),
                }
    except Exception as e:
        # не ломаем основной ответ из-за бюджета
        print(f"[budget pack] failed {e}")
        breakdown = {
            "budget_chars": budget,
            "used_chars": 0,
            "error": str(e),
        }

    elapsed = int((time.time() - t0) * 1000)

    return {
        "intent": intent,
        "confidence": conf,
        "explanation": explanation,
        "answer": answer_text,
        "documents": docs_meta,
        "totals": totals,
        "requirements": [asdict(r) for r in retrieved_reqs],
        "chunks": [asdict(c) for c in retrieved_chunks],
        "reasoning": reasoning,
        "timing_ms": elapsed,
        "mode": mode,
        "query": query,
        "docs_used": docs_used,
        "budget": breakdown,
        "budget_chars": budget,
    }
