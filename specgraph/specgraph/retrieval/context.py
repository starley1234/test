"""Связки сущностей + семантика → пакет контекста для LLM.

Стратегия:
1. семантический поиск по запросу / коду изделия / id;
2. раскрытие графа (родители/дети изделия, требования, иллюстрации, refines);
3. упаковка в компактный JSON, который кладётся в state LangGraph.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session, joinedload

from specgraph.models import (
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
        .filter(Requirement.product_id.in_([prod.id] + [p.id for p in descendants] + [p.id for p in ancestors]))
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


def gather_context(
    db: Session,
    *,
    query: str | None = None,
    product_id: int | None = None,
    product_code: str | None = None,
    requirement_id: int | None = None,
    document_id: int | None = None,
    top_k: int = 8,
    hop: int = 2,
) -> dict[str, Any]:
    bundle: dict[str, Any] = {"query": query, "hits": [], "subgraphs": [], "relations": []}

    if product_code and not product_id:
        p = db.query(Product).filter(Product.code == product_code).first()
        if p:
            product_id = p.id

    if product_id:
        bundle["subgraphs"].append(expand_product(db, product_id, depth=hop))

    if requirement_id:
        r = db.query(Requirement).options(joinedload(Requirement.attributes)).get(requirement_id)
        if r:
            bundle["seed_requirement"] = _req_dump(r)
            if r.product_id:
                bundle["subgraphs"].append(expand_product(db, r.product_id, depth=hop))

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
                r = db.query(Requirement).get(emb.entity_id)
                if r and r.product_id:
                    bundle["subgraphs"].append(expand_product(db, r.product_id, depth=1))

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
    return bundle


def context_as_prompt(bundle: dict[str, Any]) -> str:
    parts = ["Контекст спецификации (связанные сущности):"]
    if bundle.get("query"):
        parts.append(f"Запрос: {bundle['query']}")
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
