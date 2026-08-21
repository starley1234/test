from __future__ import annotations

from functools import lru_cache

import numpy as np
from sqlalchemy.orm import Session

from specgraph.config import settings
from specgraph.models import DocumentChunk, Embedding, EntityType, Illustration, Product, Requirement


@lru_cache(maxsize=1)
def _local_model():
    from sentence_transformers import SentenceTransformer

    _, _, model = settings.embed()
    try:
        return SentenceTransformer(model)
    except Exception as e:
        # offline fallback — will use hash embed
        print(f"[embed] local model load failed ({e}), using hash fallback")
        return None


def _hash_embed(texts: list[str], dim: int) -> list[list[float]]:
    """Детерминированный offline эмбеддинг без скачивания модели.
    Токенизация по словам, хэш в бакеты, L2 нормализация."""
    import hashlib
    import re

    out = []
    for txt in texts:
        vec = [0.0] * dim
        tokens = re.findall(r"[a-zа-яё0-9]{2,}", (txt or "").lower())
        for tok in tokens:
            # хэш токена -> индекс
            h = int(hashlib.md5(tok.encode()).hexdigest()[:8], 16)
            idx = h % dim
            # второй хэш для знака / веса
            h2 = int(hashlib.md5((tok + "_2").encode()).hexdigest()[:8], 16)
            sign = 1 if (h2 % 2 == 0) else -1
            vec[idx] += sign * (1.0 + len(tok) * 0.05)
            # биграммы тоже
        # L2 norm
        import math
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        vec = [x / norm for x in vec]
        out.append(vec)
    return out


def _encode_remote(texts: list[str], base_url: str, api_key: str, model: str) -> list[list[float]]:
    import httpx

    url = base_url.rstrip("/") + "/embeddings"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    r = httpx.post(url, json={"model": model, "input": texts}, headers=headers, timeout=120)
    r.raise_for_status()
    data = sorted(r.json()["data"], key=lambda x: x.get("index", 0))
    out = []
    for row in data:
        a = np.asarray(row["embedding"], dtype=float)
        n = float(np.linalg.norm(a)) or 1.0
        out.append((a / n).tolist())
    return out


def _fit_dim(vec: list[float]) -> list[float]:
    dim = int(settings.embedding_dim or 0) or len(vec)
    if len(vec) == dim:
        return vec
    if len(vec) > dim:
        return vec[:dim]
    return vec + [0.0] * (dim - len(vec))


def encode(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    base, key, model = settings.embed()
    dim = int(settings.embedding_dim or 384)
    if base:
        try:
            raw = _encode_remote(texts, base, key, model)
            return [_fit_dim(v) for v in raw]
        except Exception as e:
            print(f"[embed] remote failed ({e}), fallback to local/hash")
    m = _local_model()
    if m is not None:
        try:
            vecs = m.encode(texts, normalize_embeddings=True)
            raw = [v.tolist() for v in np.asarray(vecs)]
            return [_fit_dim(v) for v in raw]
        except Exception as e:
            print(f"[embed] local encode failed ({e}), fallback to hash")
    # hash fallback
    raw = _hash_embed(texts, dim)
    return [_fit_dim(v) for v in raw]


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
