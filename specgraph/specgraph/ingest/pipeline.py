from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from specgraph.config import settings
from specgraph.ingest.extract import detect_kind, extract_any, extract_parsed_json
from specgraph.ingest.structure import DraftGraph, from_extracted, from_parsed_json
from specgraph.models import (
    Document,
    DocumentKind,
    EntityRelation,
    EntityType,
    Illustration,
    Product,
    ProductAttribute,
    RelationType,
    Requirement,
    RequirementAttribute,
    RequirementKind,
)


def ingest_file(db: Session, src: Path, original_name: str, *, index: bool = True) -> Document:
    kind = detect_kind(original_name)
    dest = settings.upload_dir / f"{uuid4().hex}_{original_name}"
    dest.write_bytes(src.read_bytes())

    if kind == "parsed_json":
        payload = extract_parsed_json(dest)
        draft = from_parsed_json(payload)
        raw = dest.read_text(encoding="utf-8", errors="ignore")
        images: list = []
        title = payload.get("title") or original_name
        meta = {"source": "parsed_json"}
    else:
        extracted = extract_any(dest)
        draft = from_extracted(extracted)
        raw = extracted.text
        images = extracted.images
        title = extracted.title
        meta = extracted.meta

    kind_enum = kind if kind in {e.value for e in DocumentKind} else "other"
    doc = Document(
        filename=original_name,
        kind=DocumentKind(kind_enum),
        storage_path=str(dest),
        title=title,
        raw_text=raw,
        parse_meta=meta,
        status="parsed",
    )
    db.add(doc)
    db.flush()

    persist_graph(db, doc, draft)
    persist_images(db, doc, images, draft.figure_captions)
    db.commit()
    db.refresh(doc)
    if index:
        try:
            from specgraph.retrieval.embeddings import embed_and_store

            embed_and_store(db, doc.id)
            doc.status = "indexed"
        except Exception as exc:  # noqa: BLE001
            doc.status = "parsed"
            doc.parse_meta = {**(doc.parse_meta or {}), "embed_error": str(exc)}
        db.commit()
    return doc


def ingest_parsed_json(db: Session, payload: dict[str, Any], filename: str = "inline.json", *, index: bool = True) -> Document:
    import json

    dest = settings.upload_dir / f"{uuid4().hex}_{filename}"
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    draft = from_parsed_json(payload)
    doc = Document(
        filename=filename,
        kind=DocumentKind.PARSED_JSON,
        storage_path=str(dest),
        title=payload.get("title") or filename,
        raw_text=json.dumps(payload, ensure_ascii=False)[:50_000],
        parse_meta={"source": "api_json"},
        status="parsed",
    )
    db.add(doc)
    db.flush()
    doc.parse_meta = {
        **(doc.parse_meta or {}),
        "glossary": draft.glossary,
        "sources": draft.sources,
        "counts": {"products": len(draft.products), "requirements": len(draft.requirements)},
    }
    persist_graph(db, doc, draft)
    db.commit()
    if index:
        try:
            from specgraph.retrieval.embeddings import embed_and_store

            embed_and_store(db, doc.id)
            doc.status = "indexed"
        except Exception as exc:  # noqa: BLE001
            doc.parse_meta = {**(doc.parse_meta or {}), "embed_error": str(exc)}
        db.commit()
    return doc


def persist_graph(db: Session, doc: Document, draft: DraftGraph) -> None:
    products: dict[str, Product] = {}
    ordered = sorted(draft.products, key=lambda p: p.level)
    for dp in ordered:
        prod = Product(
            document_id=doc.id,
            parent_id=products[dp.parent_code].id if dp.parent_code and dp.parent_code in products else None,
            code=dp.code,
            name=dp.name,
            level=dp.level,
            section_path=dp.section_path,
            description=dp.description,
            extra=dp.extra or {},
        )
        db.add(prod)
        db.flush()
        products[dp.code] = prod
        for k, v in dp.attributes.items():
            db.add(ProductAttribute(product_id=prod.id, key=k, value=v))
        if prod.parent_id:
            db.add(
                EntityRelation(
                    rel_type=RelationType.COMPOSED_OF,
                    src_type=EntityType.PRODUCT,
                    src_id=prod.parent_id,
                    dst_type=EntityType.PRODUCT,
                    dst_id=prod.id,
                )
            )

    reqs: dict[str, Requirement] = {}
    for dr in draft.requirements:
        kind = dr.kind if dr.kind in {e.value for e in RequirementKind} else "unknown"
        req = Requirement(
            document_id=doc.id,
            product_id=products[dr.product_code].id if dr.product_code and dr.product_code in products else None,
            parent_id=None,
            code=dr.code,
            title=dr.title,
            text=dr.text,
            kind=RequirementKind(kind),
            section_path=dr.section_path,
        )
        db.add(req)
        db.flush()
        reqs[dr.code] = req
        for k, v in dr.attributes.items():
            db.add(RequirementAttribute(requirement_id=req.id, key=k, value=v))
        if req.product_id:
            db.add(
                EntityRelation(
                    rel_type=RelationType.APPLIES_TO,
                    src_type=EntityType.REQUIREMENT,
                    src_id=req.id,
                    dst_type=EntityType.PRODUCT,
                    dst_id=req.product_id,
                )
            )

    for dr in draft.requirements:
        if dr.parent_code and dr.parent_code in reqs and dr.code in reqs:
            child = reqs[dr.code]
            child.parent_id = reqs[dr.parent_code].id
            db.add(
                EntityRelation(
                    rel_type=RelationType.REFINES,
                    src_type=EntityType.REQUIREMENT,
                    src_id=child.id,
                    dst_type=EntityType.REQUIREMENT,
                    dst_id=reqs[dr.parent_code].id,
                )
            )

    type_map = {
        "applies_to": RelationType.APPLIES_TO,
        "composed_of": RelationType.COMPOSED_OF,
        "refines": RelationType.REFINES,
        "depends_on": RelationType.DEPENDS_ON,
        "conflicts_with": RelationType.CONFLICTS_WITH,
        "illustrated_by": RelationType.ILLUSTRATED_BY,
        "derived_from": RelationType.DERIVED_FROM,
        "verified_by": RelationType.VERIFIED_BY,
        "implements": RelationType.IMPLEMENTS,
    }
    kind_map = {"product": (EntityType.PRODUCT, products), "requirement": (EntityType.REQUIREMENT, reqs)}
    for rel in draft.relations:
        rt = type_map.get(rel.rel_type)
        if not rt:
            continue
        sk, smap = kind_map.get(rel.src_kind, (None, {}))
        dk, dmap = kind_map.get(rel.dst_kind, (None, {}))
        if not sk or rel.src_code not in smap or rel.dst_code not in dmap:
            continue
        db.add(
            EntityRelation(
                rel_type=rt,
                src_type=sk,
                src_id=smap[rel.src_code].id,
                dst_type=dk,
                dst_id=dmap[rel.dst_code].id,
            )
        )


def persist_images(db: Session, doc: Document, images, captions: list[str]) -> None:
    for i, img in enumerate(images):
        path = settings.media_dir / f"{doc.id}_{img.filename}"
        path.write_bytes(img.content)
        caption = img.caption or (captions[i] if i < len(captions) else None)
        ill = Illustration(
            document_id=doc.id,
            filename=img.filename,
            storage_path=str(path),
            caption=caption,
            content_type=img.content_type,
            blob=img.content if len(img.content) < 2_000_000 else None,
        )
        db.add(ill)
        db.flush()
        db.add(
            EntityRelation(
                rel_type=RelationType.ILLUSTRATED_BY,
                src_type=EntityType.DOCUMENT,
                src_id=doc.id,
                dst_type=EntityType.ILLUSTRATION,
                dst_id=ill.id,
            )
        )
        if caption:
            for prod in db.query(Product).filter(Product.document_id == doc.id).all():
                if prod.code in caption or (prod.name and prod.name.lower() in caption.lower()):
                    ill.product_id = prod.id
                    db.add(
                        EntityRelation(
                            rel_type=RelationType.ILLUSTRATED_BY,
                            src_type=EntityType.PRODUCT,
                            src_id=prod.id,
                            dst_type=EntityType.ILLUSTRATION,
                            dst_id=ill.id,
                        )
                    )
                    break
