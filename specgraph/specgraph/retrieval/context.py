"""Связки сущностей + семантика → пакет контекста для LLM.

Стратегия:
1. семантический поиск по запросу / коду изделия / id;
2. раскрытие графа (родители/дети изделия, требования, иллюстрации, refines);
3. упаковка в компактный JSON, который кладётся в state LangGraph.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session, joinedload

from specgraph.config import settings
from specgraph.models import (
    Attachment,
    DocumentChunk,
    Embedding,
    EntityRelation,
    EntityType,
    Illustration,
    Product,
    RelationType,
    Requirement,
)


def _product_dump(p: Product) -> dict[str, Any]:
    return {
        "id": p.id,
        "code": p.code,
        "name": p.name,
        "level": p.level,
        "parent_id": p.parent_id,
        "section_path": p.section_path,
        "description": p.description,
        "attributes": {a.key: a.value for a in p.attributes},
    }


def _req_dump(r: Requirement) -> dict[str, Any]:
    return {
        "id": r.id,
        "code": r.code,
        "kind": r.kind.value,
        "title": r.title,
        "text": r.text,
        "product_id": r.product_id,
        "parent_id": r.parent_id,
        "section_path": r.section_path,
        "created_at": r.created_at.isoformat() if getattr(r, "created_at", None) else None,
        "attributes": {a.key: a.value for a in r.attributes},
    }


def expand_product(db: Session, product_id: int, depth: int = 2) -> dict[str, Any]:
    prod = (
        db.query(Product)
        .options(joinedload(Product.attributes), joinedload(Product.children))
        .filter(Product.id == product_id)
        .first()
    )
    if not prod:
        return {}

    # предки
    ancestors: list[Product] = []
    cur = prod
    seen: set[int] = set()
    while cur.parent_id and cur.parent_id not in seen:
        seen.add(cur.parent_id)
        cur = db.get(Product, cur.parent_id)
        if not cur:
            break
        ancestors.append(cur)

    # потомки до depth
    descendants: list[Product] = []

    def walk(node: Product, d: int) -> None:
        if d <= 0:
            return
        kids = db.query(Product).options(joinedload(Product.attributes)).filter(Product.parent_id == node.id).all()
        for k in kids:
            descendants.append(k)
            walk(k, d - 1)

    walk(prod, depth)

    reqs = (
        db.query(Requirement)
        .options(joinedload(Requirement.attributes))
        .filter(
            Requirement.is_current.is_(True),
            Requirement.product_id.in_([prod.id] + [p.id for p in descendants] + [p.id for p in ancestors]),
        )
        .all()
    )
    ills = db.query(Illustration).filter(
        Illustration.product_id.in_([prod.id] + [p.id for p in descendants])
    ).all()

    return {
        "product": _product_dump(prod),
        "ancestors": [_product_dump(p) for p in ancestors],
        "descendants": [_product_dump(p) for p in descendants],
        "requirements": [_req_dump(r) for r in reqs],
        "illustrations": [
            {"id": i.id, "filename": i.filename, "caption": i.caption, "path": i.storage_path} for i in ills
        ],
    }


def expand_requirement(db: Session, requirement_id: int) -> dict[str, Any]:
    r = db.query(Requirement).options(joinedload(Requirement.attributes)).filter(Requirement.id == requirement_id).first()
    if not r:
        return {}
    out = _req_dump(r)
    rels = (
        db.query(EntityRelation)
        .filter(
            EntityRelation.src_type == EntityType.REQUIREMENT,
            EntityRelation.src_id == r.id,
            EntityRelation.rel_type.in_([RelationType.DERIVED_FROM, RelationType.REFINES]),
        )
        .all()
    )
    parents = []
    for rel in rels:
        p = db.get(Requirement, rel.dst_id)
        if p:
            parents.append(_req_dump(p) | {"stub": bool((p.extra or {}).get("stub"))})
    children = db.query(Requirement).filter(Requirement.parent_id == r.id).all()
    atts = db.query(Attachment).filter(Attachment.requirement_id == r.id).all()
    out["parents"] = parents
    out["children"] = [_req_dump(c) for c in children]
    out["attachments"] = [
        {"filename": a.filename, "code": a.code, "text": (a.text_content or "")[:4000]} for a in atts
    ]
    ills = db.query(Illustration).filter(Illustration.document_id == r.document_id).all()
    out["illustrations"] = [
        {
            "id": i.id,
            "filename": i.filename,
            "caption": i.caption,
            "url": f"/illustrations/{i.id}",
            "content_type": i.content_type,
        }
        for i in ills[:12]
    ]
    out["chunks"] = []
    return out


def _chunks_for_requirement(db: Session, r: Requirement, limit: int = 6) -> list[dict[str, Any]]:
    doc_ids: set[int] = set()
    if r.document_id:
        doc_ids.add(r.document_id)
    rels = (
        db.query(EntityRelation)
        .filter(
            EntityRelation.src_type == EntityType.REQUIREMENT,
            EntityRelation.src_id == r.id,
            EntityRelation.dst_type == EntityType.DOCUMENT,
        )
        .all()
    )
    for rel in rels:
        doc_ids.add(rel.dst_id)
    atts = db.query(Attachment).filter(Attachment.requirement_id == r.id).all()
    for a in atts:
        if a.document_id:
            doc_ids.add(a.document_id)
    if not doc_ids:
        return []
    rows = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id.in_(doc_ids))
        .order_by(DocumentChunk.document_id, DocumentChunk.seq)
        .limit(limit)
        .all()
    )
    return [
        {
            "id": c.id,
            "document_id": c.document_id,
            "seq": c.seq,
            "heading": c.heading,
            "text": c.text[:800],
        }
        for c in rows
    ]


def gather_context(
    db: Session,
    *,
    query: str | None = None,
    product_id: int | None = None,
    product_code: str | None = None,
    requirement_id: int | None = None,
    requirement_ids: list[int] | None = None,
    document_id: int | None = None,
    top_k: int = 8,
    hop: int = 2,
    mode: str = "graph",
    context_mode: str | None = None,
) -> dict[str, Any]:
    mode = (context_mode or mode or "graph").lower()
    if mode not in {"graph", "hybrid", "chunks"}:
        mode = "graph"
    bundle: dict[str, Any] = {
        "query": query,
        "mode": mode,
        "hits": [],
        "subgraphs": [],
        "relations": [],
        "requirements": [],
        "chunks": [],
    }

    if product_code and not product_id:
        p = db.query(Product).filter(Product.code == product_code).first()
        if p:
            product_id = p.id

    if product_id:
        bundle["subgraphs"].append(expand_product(db, product_id, depth=hop))

    if requirement_id:
        exp = expand_requirement(db, requirement_id)
        if exp:
            bundle["seed_requirement"] = exp
            r = db.get(Requirement, requirement_id)
            if r and r.product_id:
                bundle["subgraphs"].append(expand_product(db, r.product_id, depth=hop))
            if mode in {"hybrid", "chunks"} and r:
                bundle["chunks"] = _chunks_for_requirement(db, r)
                exp["chunks"] = bundle["chunks"]

    ids = list(requirement_ids or [])
    q = db.query(Requirement).options(joinedload(Requirement.attributes)).filter(Requirement.is_current.is_(True))
    if ids:
        q = q.filter(Requirement.id.in_(ids))
    elif document_id:
        q = q.filter(Requirement.document_id == document_id)
    elif requirement_id or product_id:
        q = None
    if q is not None and (ids or document_id):
        rows = [r for r in q.all() if not (r.extra or {}).get("stub") and not (r.extra or {}).get("appendix")]
        bundle["requirements"] = [_req_dump(r) for r in rows[:200]]
        for r in rows:
            if r.product_id:
                bundle["subgraphs"].append(expand_product(db, r.product_id, depth=1))

    if query:
        from specgraph.retrieval.embeddings import semantic_search

        hits = semantic_search(db, query, top_k=top_k)
        for emb, score in hits:
            bundle["hits"].append(
                {
                    "entity_type": emb.entity_type.value,
                    "entity_id": emb.entity_id,
                    "score": round(score, 4),
                    "text": emb.text,
                }
            )
            if emb.entity_type == EntityType.PRODUCT:
                bundle["subgraphs"].append(expand_product(db, emb.entity_id, depth=hop))
            elif emb.entity_type == EntityType.REQUIREMENT:
                r = db.get(Requirement, emb.entity_id)
                if r and r.product_id:
                    bundle["subgraphs"].append(expand_product(db, r.product_id, depth=1))
            elif emb.entity_type == EntityType.CHUNK and mode in {"hybrid", "chunks"}:
                ch = db.get(DocumentChunk, emb.entity_id)
                if ch:
                    bundle.setdefault("chunks", []).append(
                        {"id": ch.id, "document_id": ch.document_id, "seq": ch.seq, "text": ch.text[:800]}
                    )

    # уникализируем подграфы
    seen_p: set[int] = set()
    uniq = []
    for sg in bundle["subgraphs"]:
        pid = (sg.get("product") or {}).get("id")
        if pid and pid not in seen_p:
            seen_p.add(pid)
            uniq.append(sg)
    bundle["subgraphs"] = uniq

    if seen_p:
        rels = (
            db.query(EntityRelation)
            .filter(
                ((EntityRelation.src_type == EntityType.PRODUCT) & (EntityRelation.src_id.in_(seen_p)))
                | ((EntityRelation.dst_type == EntityType.PRODUCT) & (EntityRelation.dst_id.in_(seen_p)))
            )
            .all()
        )
        bundle["relations"] = [
            {
                "type": rel.rel_type.value,
                "src": f"{rel.src_type.value}:{rel.src_id}",
                "dst": f"{rel.dst_type.value}:{rel.dst_id}",
            }
            for rel in rels
        ]
    bundle["budget_chars"] = settings.context_budget_chars
    return pack_budget(bundle)


def pack_budget(bundle: dict[str, Any], budget: int | None = None) -> dict[str, Any]:
    """Слои: seed → родители → чанки упоминаний → подписи рисунков → остальные требования."""
    budget = budget or settings.context_budget_chars
    used = 0

    def take(s: str, cap: int) -> str:
        nonlocal used
        left = budget - used
        if left <= 0:
            return ""
        piece = (s or "")[: min(cap, left)]
        used += len(piece)
        return piece

    seed = bundle.get("seed_requirement") or {}
    if seed.get("text"):
        seed["text"] = take(seed["text"], 2000)
    for p in seed.get("parents") or []:
        p["text"] = take(p.get("text") or "", 400)
    for a in seed.get("attachments") or []:
        a["text"] = take(a.get("text") or "", 600)
    for c in seed.get("chunks") or []:
        c["text"] = take(c.get("text") or "", 600)
    for r in bundle.get("requirements") or []:
        r["text"] = take(r.get("text") or "", 400)
        attrs = r.get("attributes") or {}
        for k in list(attrs)[8:]:
            attrs.pop(k, None)
    for h in bundle.get("hits") or []:
        h["text"] = take(h.get("text") or "", 240)
    for c in bundle.get("chunks") or []:
        c["text"] = take(c.get("text") or "", 500)
    bundle["packed_chars"] = used
    return bundle


def context_as_prompt(bundle: dict[str, Any]) -> str:
    parts = [
        "Контекст спецификации уже в этом сообщении. Не проси данные ещё раз — анализируй список ниже.",
    ]
    if bundle.get("query"):
        parts.append(f"Запрос: {bundle['query']}")
    reqs = bundle.get("requirements") or []
    if reqs:
        parts.append(f"\n## Требования ({len(reqs)} шт.)")
        for r in reqs:
            attrs = r.get("attributes") or {}
            attr_s = "; ".join(f"{k}={str(v)[:120]}" for k, v in list(attrs.items())[:8])
            when = (r.get("created_at") or "")[:19]
            parts.append(f"- [{r.get('code')}] ({r.get('kind')}) загружено {when} {(r.get('text') or '')[:500]}")
            if attr_s:
                parts.append(f"  атрибуты: {attr_s}")
    seed = bundle.get("seed_requirement") or {}
    if seed.get("code"):
        parts.append(f"\n## Требование {seed['code']}")
        parts.append(seed.get("text") or "")
        for p in seed.get("parents") or []:
            mark = " [не загружено]" if p.get("stub") else ""
            parts.append(f"↑ источник{mark}: {p.get('code')} {(p.get('text') or '')[:400]}")
        for a in seed.get("attachments") or []:
            parts.append(f"файл {a.get('filename')}: {(a.get('text') or '')[:800]}")
        for c in seed.get("chunks") or []:
            parts.append(f"чанк {c.get('document_id')}/{c.get('seq')}: {(c.get('text') or '')[:500]}")
        for ill in seed.get("illustrations") or []:
            parts.append(f"рис. {ill.get('id')} {ill.get('caption') or ill.get('filename')} {ill.get('url')}")
        for k, v in (seed.get("attributes") or {}).items():
            parts.append(f"  {k}: {str(v)[:400]}")
    for sg in bundle.get("subgraphs", []):
        p = sg["product"]
        parts.append(f"\n## Изделие {p['code']} — {p['name']}")
        if p.get("attributes"):
            parts.append("Атрибуты: " + ", ".join(f"{k}={v}" for k, v in p["attributes"].items()))
        if sg.get("ancestors"):
            parts.append("Входит в: " + " > ".join(a["name"] for a in reversed(sg["ancestors"])))
        if sg.get("descendants"):
            parts.append("Состав: " + ", ".join(f"{d['code']} {d['name']}" for d in sg["descendants"]))
        for r in sg.get("requirements", []):
            parts.append(f"- [{r['code']}] ({r['kind']}) {r['text']}")
        for ill in sg.get("illustrations", []):
            parts.append(f"  рис.: {ill.get('caption') or ill['filename']}")
    if bundle.get("hits"):
        parts.append("\nСемантические попадания:")
        for h in bundle["hits"][:6]:
            parts.append(f"  ({h['score']}) {h['text'][:240]}")
    return "\n".join(parts)
