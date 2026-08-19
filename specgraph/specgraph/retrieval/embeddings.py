from __future__ import annotations

from functools import lru_cache

import numpy as np
from sqlalchemy.orm import Session

from specgraph.config import settings
from specgraph.models import Embedding, EntityType, Illustration, Product, Requirement


@lru_cache(maxsize=1)
def _model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(settings.embedding_model)


def encode(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    vecs = _model().encode(texts, normalize_embeddings=True)
    return [v.tolist() for v in np.asarray(vecs)]


def cosine(a: list[float], b: list[float]) -> float:
    va, vb = np.asarray(a), np.asarray(b)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb)) or 1.0
    return float(np.dot(va, vb) / denom)


def product_text(p: Product) -> str:
    attrs = "; ".join(f"{a.key}={a.value}" for a in p.attributes)
    return f"Изделие {p.code} {p.name}. {p.description or ''}. Атрибуты: {attrs}"


def requirement_text(r: Requirement) -> str:
    attrs = "; ".join(f"{a.key}={a.value}" for a in r.attributes)
    return f"Требование {r.code} [{r.kind.value}]: {r.text}. {attrs}"


def embed_and_store(db: Session, document_id: int) -> int:
    texts: list[tuple[EntityType, int, str]] = []
    for p in db.query(Product).filter(Product.document_id == document_id).all():
        texts.append((EntityType.PRODUCT, p.id, product_text(p)))
    for r in db.query(Requirement).filter(Requirement.document_id == document_id).all():
        texts.append((EntityType.REQUIREMENT, r.id, requirement_text(r)))
    for ill in db.query(Illustration).filter(Illustration.document_id == document_id).all():
        if ill.caption:
            texts.append((EntityType.ILLUSTRATION, ill.id, ill.caption))
    if not texts:
        return 0
    vectors = encode([t[2] for t in texts])
    n = 0
    for (etype, eid, text), vec in zip(texts, vectors, strict=True):
        db.add(Embedding(entity_type=etype, entity_id=eid, text=text, vector=vec))
        n += 1
    db.commit()
    return n


def semantic_search(
    db: Session,
    query: str,
    *,
    top_k: int = 8,
    entity_types: list[EntityType] | None = None,
    document_id: int | None = None,
) -> list[tuple[Embedding, float]]:
    qv = encode([query])[0]
    q = db.query(Embedding)
    if entity_types:
        q = q.filter(Embedding.entity_type.in_(entity_types))
    rows = q.all()
    scored = [(row, cosine(qv, row.vector)) for row in rows]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]
