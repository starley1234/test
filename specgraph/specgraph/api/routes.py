from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.orm import Session, joinedload

from specgraph.api.schemas import DocumentOut, IngestJsonRequest, PipelineRequest, ProductOut, RetrievalRequest
from specgraph.config import settings
from specgraph.db import get_db
from specgraph.ingest.ids import base_code
from specgraph.ingest.pipeline import ingest_file, ingest_many, ingest_parsed_json
from specgraph.models import Attachment, Document, EntityRelation, EntityType, Illustration, Product, RelationType, Requirement
from specgraph.retrieval.context import gather_context

router = APIRouter()
STATIC = Path(__file__).resolve().parent.parent / "static"


@router.get("/", response_class=HTMLResponse)
def ui():
    return (STATIC / "index.html").read_text(encoding="utf-8")


@router.post("/documents", response_model=DocumentOut)
async def upload_document(file: UploadFile = File(...), db: Session = Depends(get_db)):
    suffix = Path(file.filename or "upload.bin").name
    tmp = settings.upload_dir / f"tmp_{uuid4().hex}_{suffix}"
    tmp.write_bytes(await file.read())
    try:
        doc = ingest_file(db, tmp, suffix, index=False)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"ingest failed: {exc}") from exc
    return DocumentOut(id=doc.id, filename=doc.filename, kind=doc.kind.value, title=doc.title, status=doc.status)


@router.post("/documents/batch")
async def upload_batch(files: list[UploadFile] = File(...), db: Session = Depends(get_db)):
    packed: list[tuple[Path, str]] = []
    for file in files:
        name = Path(file.filename or "upload.bin").name
        tmp = settings.upload_dir / f"tmp_{uuid4().hex}_{name}"
        tmp.write_bytes(await file.read())
        packed.append((tmp, name))
    try:
        docs = ingest_many(db, packed, index=False)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"ingest failed: {exc}") from exc
    return {
        "documents": [
            DocumentOut(id=d.id, filename=d.filename, kind=d.kind.value, title=d.title, status=d.status).model_dump()
            for d in docs
        ]
    }


@router.post("/documents/json", response_model=DocumentOut)
def upload_parsed_json(body: IngestJsonRequest, db: Session = Depends(get_db)):
    doc = ingest_parsed_json(db, body.payload, body.filename, index=False)
    return DocumentOut(id=doc.id, filename=doc.filename, kind=doc.kind.value, title=doc.title, status=doc.status)


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(db: Session = Depends(get_db)):
    docs = db.query(Document).order_by(Document.id.desc()).all()
    return [DocumentOut(id=d.id, filename=d.filename, kind=d.kind.value, title=d.title, status=d.status) for d in docs]


@router.get("/documents/{doc_id}")
def get_document(doc_id: int, db: Session = Depends(get_db)):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(404)
    n_p = db.query(Product).filter(Product.document_id == doc_id).count()
    n_r = db.query(Requirement).filter(Requirement.document_id == doc_id).count()
    n_i = db.query(Illustration).filter(Illustration.document_id == doc_id).count()
    n_a = db.query(Attachment).filter(Attachment.document_id == doc_id).count()
    return {
        "id": d.id,
        "filename": d.filename,
        "title": d.title,
        "status": d.status,
        "parse_meta": d.parse_meta,
        "counts": {"products": n_p, "requirements": n_r, "illustrations": n_i, "attachments": n_a},
    }


@router.get("/products", response_model=list[ProductOut])
def list_products(document_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(Product).options(joinedload(Product.attributes))
    if document_id:
        q = q.filter(Product.document_id == document_id)
    out = []
    for p in q.all():
        out.append(
            ProductOut(
                id=p.id,
                code=p.code,
                name=p.name,
                parent_id=p.parent_id,
                level=p.level,
                attributes={a.key: a.value for a in p.attributes},
            )
        )
    return out


@router.get("/products/{product_id}")
def get_product(product_id: int, db: Session = Depends(get_db)):
    from specgraph.retrieval.context import expand_product

    sg = expand_product(db, product_id)
    if not sg:
        raise HTTPException(404)
    return sg


def _req_dump(r: Requirement) -> dict:
    return {
        "id": r.id,
        "code": r.code,
        "kind": r.kind.value,
        "text": r.text,
        "product_id": r.product_id,
        "parent_id": r.parent_id,
        "document_id": r.document_id,
        "section_path": r.section_path,
        "extra": r.extra or {},
        "attributes": {a.key: a.value for a in r.attributes},
    }


@router.get("/requirements")
def list_requirements(document_id: int | None = None, product_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(Requirement).options(joinedload(Requirement.attributes))
    if document_id:
        q = q.filter(Requirement.document_id == document_id)
    if product_id:
        q = q.filter(Requirement.product_id == product_id)
    return [_req_dump(r) for r in q.all()]


@router.get("/requirements/{req_id}")
def get_requirement(req_id: int, db: Session = Depends(get_db)):
    r = db.query(Requirement).options(joinedload(Requirement.attributes)).filter(Requirement.id == req_id).first()
    if not r:
        raise HTTPException(404)
    out = _req_dump(r)
    prod = db.get(Product, r.product_id) if r.product_id else None
    out["product_code"] = prod.code if prod else None
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
            parents.append(
                {
                    "id": p.id,
                    "code": p.code,
                    "text": p.text,
                    "stub": bool((p.extra or {}).get("stub")),
                }
            )
    if r.parent_id and not any(p["id"] == r.parent_id for p in parents):
        p = db.get(Requirement, r.parent_id)
        if p:
            parents.append({"id": p.id, "code": p.code, "text": p.text, "stub": bool((p.extra or {}).get("stub"))})
    out["parents"] = parents
    atts = db.query(Attachment).filter(
        (Attachment.requirement_id == r.id)
        | (Attachment.code.in_([base_code(r.code)] + [base_code(a.value) for a in r.attributes if a.key.startswith("приложение")]))
    ).all()
    out["attachments"] = [
        {"id": a.id, "filename": a.filename, "code": a.code, "text_content": (a.text_content or "")[:8000]}
        for a in atts
    ]
    return out


@router.post("/retrieval/context")
def retrieval_context(body: RetrievalRequest, db: Session = Depends(get_db)):
    return gather_context(db, **body.model_dump())


@router.post("/pipelines/validate-requirements")
def pipeline_validate(body: PipelineRequest, db: Session = Depends(get_db)):
    return validate_requirements(db, **body.model_dump())


@router.post("/pipelines/generate-tests")
def pipeline_tests(body: PipelineRequest, db: Session = Depends(get_db)):
    return generate_tests(db, **body.model_dump())
