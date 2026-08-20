from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session, joinedload

from specgraph.config import settings
from specgraph.ingest.extract import detect_kind, extract_any, extract_parsed_json
from specgraph.ingest.ids import base_code
from specgraph.ingest.resolve import (
    apply_new_revision,
    ensure_stub,
    find_by_code,
    link_derived,
    merge_if_stub,
    resolve_pending,
)
from specgraph.ingest.structure import DraftGraph, from_extracted, from_parsed_json
from specgraph.models import (
    Attachment,
    Document,
    DocumentChunk,
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


def make_ingest_report(db: Session, doc: Document, draft: DraftGraph | None = None) -> dict[str, Any]:
    reqs = db.query(Requirement).filter(Requirement.document_id == doc.id).all()
    return {
        "filename": doc.filename,
        "has_cards": bool(draft.has_cards) if draft else any((r.extra or {}).get("card") for r in reqs),
        "cards": sum(1 for r in reqs if (r.extra or {}).get("card")),
        "stubs": sum(1 for r in reqs if (r.extra or {}).get("stub")),
        "appendix": sum(1 for r in reqs if (r.extra or {}).get("appendix")),
        "requirements": len(reqs),
        "products": db.query(Product).filter(Product.document_id == doc.id).count(),
        "images": db.query(Illustration).filter(Illustration.document_id == doc.id).count(),
    }


def ingest_file(
    db: Session,
    src: Path,
    original_name: str,
    *,
    index: bool = True,
    uploaded_by_id: int | None = None,
    commit: bool = True,
) -> Document:
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
        uploaded_by_id=uploaded_by_id,
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
    persist_images(db, doc, images, draft.figure_captions)
    if not draft.has_cards:
        persist_chunks(db, doc)
    persist_self_attachment(db, doc, draft)
    link_mentions(db, doc)
    doc.parse_meta = {**(doc.parse_meta or {}), "ingest_report": make_ingest_report(db, doc, draft)}
    if commit:
        db.commit()
        db.refresh(doc)
        resolve_pending(db)
        db.commit()
    if index and commit:
        try:
            from specgraph.retrieval.embeddings import embed_and_store

            embed_and_store(db, doc.id)
            doc.status = "indexed"
        except Exception as exc:  # noqa: BLE001
            doc.status = "parsed"
            doc.parse_meta = {**(doc.parse_meta or {}), "embed_error": str(exc)}
        db.commit()
    return doc


def ingest_parsed_json(
    db: Session,
    payload: dict[str, Any],
    filename: str = "inline.json",
    *,
    index: bool = True,
    uploaded_by_id: int | None = None,
) -> Document:
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
        uploaded_by_id=uploaded_by_id,
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
    if not draft.has_cards:
        persist_chunks(db, doc)
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

    def _put(code: str, req: Requirement) -> None:
        reqs[code] = req
        reqs[base_code(code)] = req

    for dr in draft.requirements:
        kind = dr.kind if dr.kind in {e.value for e in RequirementKind} else "unknown"
        extra = dict(dr.extra or {})
        if dr.stub:
            extra["stub"] = True
        with db.no_autoflush:
            existing = find_by_code(db, dr.code)
        if existing and (existing.extra or {}).get("stub"):
            merge_if_stub(
                existing,
                Requirement(
                    document_id=doc.id,
                    code=dr.code,
                    text=dr.text,
                    kind=RequirementKind(kind),
                    extra=extra,
                    section_path=dr.section_path,
                ),
            )
            existing.document_id = doc.id
            existing.base_code = base_code(dr.code)
            existing.revision = dr.code.split("/", 1)[1] if "/" in dr.code else None
            existing.is_current = True
            req = existing
        elif existing and not dr.stub:
            apply_new_revision(db, existing, code=dr.code, text=dr.text, extra=extra, document_id=doc.id)
            if dr.title:
                existing.title = dr.title
            existing.kind = RequirementKind(kind)
            existing.section_path = dr.section_path
            req = existing
        else:
            req = Requirement(
                document_id=doc.id,
                product_id=products[dr.product_code].id if dr.product_code and dr.product_code in products else None,
                parent_id=None,
                code=dr.code,
                title=dr.title,
                text=dr.text,
                kind=RequirementKind(kind),
                section_path=dr.section_path,
                extra=extra,
                base_code=base_code(dr.code),
                revision=dr.code.split("/", 1)[1] if "/" in dr.code else None,
                is_current=True,
            )
            db.add(req)
            db.flush()
        _put(dr.code, req)
        have = {a.key for a in req.attributes} if req.attributes else set()
        for k, v in dr.attributes.items():
            if k in have:
                continue
            db.add(RequirementAttribute(requirement_id=req.id, key=k, value=v))
            have.add(k)
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
        parents = list(dr.parent_codes or [])
        if dr.parent_code:
            parents.append(dr.parent_code)
        for pcode in dict.fromkeys(parents):
            parent = reqs.get(pcode) or reqs.get(base_code(pcode)) or ensure_stub(db, pcode, document_id=doc.id)
            _put(pcode, parent)
            link_derived(db, req, parent)
        for acode in dr.attachment_refs or []:
            key = f"приложение:{base_code(acode)[:80]}"
            if key in have:
                continue
            db.add(RequirementAttribute(requirement_id=req.id, key=key, value=acode))
            have.add(key)

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
            blob=None,
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


def persist_chunks(db: Session, doc: Document) -> int:
    from specgraph.retrieval.chunks import split_text

    pieces = split_text(doc.raw_text or "")
    n = 0
    for seq, (a, b, piece) in enumerate(pieces):
        db.add(
            DocumentChunk(
                document_id=doc.id,
                seq=seq,
                heading=(doc.title or doc.filename)[:512],
                text=piece,
                char_start=a,
                char_end=b,
            )
        )
        n += 1
    return n


def link_mentions(db: Session, doc: Document) -> int:
    needles = [x for x in (doc.filename, Path(doc.filename).stem) if x and len(x) >= 4]
    if not needles:
        return 0
    n = 0
    with db.no_autoflush:
        reqs = db.query(Requirement).options(joinedload(Requirement.attributes)).all()
    for req in reqs:
        blob = " ".join([req.text or "", req.code or "", " ".join(a.value for a in req.attributes)])
        if not any(nd in blob for nd in needles):
            continue
        exists = (
            db.query(EntityRelation)
            .filter(
                EntityRelation.rel_type == RelationType.DEPENDS_ON,
                EntityRelation.src_type == EntityType.REQUIREMENT,
                EntityRelation.src_id == req.id,
                EntityRelation.dst_type == EntityType.DOCUMENT,
                EntityRelation.dst_id == doc.id,
            )
            .first()
        )
        if exists:
            continue
        db.add(
            EntityRelation(
                rel_type=RelationType.DEPENDS_ON,
                src_type=EntityType.REQUIREMENT,
                src_id=req.id,
                dst_type=EntityType.DOCUMENT,
                dst_id=doc.id,
                extra={"kind": "mention", "filename": doc.filename},
            )
        )
        n += 1
    return n


def persist_self_attachment(db: Session, doc: Document, draft: DraftGraph) -> None:
    codes = list(draft.attachment_codes or [])
    stem = Path(doc.filename).stem
    only_app = bool(draft.requirements) and all((r.extra or {}).get("appendix") for r in draft.requirements)
    if only_app or not draft.requirements:
        codes.append(stem)
    codes = list(dict.fromkeys(c for c in codes if c))
    if not codes:
        return
    text_body = (doc.raw_text or "")[:50000]
    for code in codes:
        att = Attachment(
            document_id=doc.id,
            requirement_id=None,
            code=base_code(code),
            filename=doc.filename,
            storage_path=doc.storage_path,
            text_content=text_body,
            extra={"role": "appendix"},
        )
        db.add(att)
        db.flush()
        bind_attachment_to_requirements(db, att)


def bind_attachment_to_requirements(db: Session, att: Attachment) -> int:
    n = 0
    stem = Path(att.filename).stem
    needles = [x for x in (att.code, stem, base_code(stem)) if x]
    pending = {
        (obj.requirement_id, obj.key)
        for obj in db.new
        if isinstance(obj, RequirementAttribute)
    }
    with db.no_autoflush:
        reqs = db.query(Requirement).options(joinedload(Requirement.attributes)).all()
    for req in reqs:
        blob = " ".join(
            [
                req.text or "",
                req.code or "",
                " ".join(f"{a.key}={a.value}" for a in req.attributes),
            ]
        )
        if not any(nd and nd in blob for nd in needles):
            continue
        if not att.requirement_id:
            att.requirement_id = req.id
        key = f"файл:{att.filename}"[:128]
        if key in {a.key for a in req.attributes} or (req.id, key) in pending:
            continue
        exists = (
            db.query(RequirementAttribute)
            .filter(RequirementAttribute.requirement_id == req.id, RequirementAttribute.key == key)
            .first()
        )
        if exists:
            continue
        db.add(
            RequirementAttribute(
                requirement_id=req.id,
                key=key,
                value=f"document:{att.document_id}:{att.filename}",
            )
        )
        pending.add((req.id, key))
        n += 1
    return n


def ingest_many(db: Session, files: list[tuple[Path, str]], *, index: bool = False) -> list[Document]:
    def rank(name: str) -> int:
        if name.lower().endswith((".xlsx", ".xlsm")):
            return 2
        if Path(name).stem.count(".") >= 2:
            return 2
        return 1

    ordered = sorted(files, key=lambda x: rank(x[1]))
    docs: list[Document] = []
    for path, name in ordered:
        docs.append(ingest_file(db, path, name, index=index, commit=False))
    for att in db.query(Attachment).all():
        bind_attachment_to_requirements(db, att)
    for d in docs:
        link_mentions(db, d)
    resolve_pending(db)
    db.commit()
    return docs
