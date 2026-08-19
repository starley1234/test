from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session, joinedload

from specgraph.api.schemas import DocumentOut, IngestJsonRequest, PipelineRequest, ProductOut, RetrievalRequest
from specgraph.config import settings
from specgraph.db import get_db
from specgraph.ingest.pipeline import ingest_file, ingest_parsed_json
from specgraph.models import Document, Illustration, Product, Requirement
from specgraph.pipelines.graphs import generate_tests, validate_requirements
from specgraph.retrieval.context import gather_context

router = APIRouter()


@router.post("/documents", response_model=DocumentOut)
async def upload_document(file: UploadFile = File(...), db: Session = Depends(get_db)):
    suffix = Path(file.filename or "upload.bin").name
    tmp = settings.upload_dir / f"tmp_{uuid4().hex}_{suffix}"
    tmp.write_bytes(await file.read())
    try:
        doc = ingest_file(db, tmp, suffix)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"ingest failed: {exc}") from exc
    return DocumentOut(id=doc.id, filename=doc.filename, kind=doc.kind.value, title=doc.title, status=doc.status)


@router.post("/documents/json", response_model=DocumentOut)
def upload_parsed_json(body: IngestJsonRequest, db: Session = Depends(get_db)):
    doc = ingest_parsed_json(db, body.payload, body.filename)
    return DocumentOut(id=doc.id, filename=doc.filename, kind=doc.kind.value, title=doc.title, status=doc.status)


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(db: Session = Depends(get_db)):
    docs = db.query(Document).order_by(Document.id.desc()).all()
    return [DocumentOut(id=d.id, filename=d.filename, kind=d.kind.value, title=d.title, status=d.status) for d in docs]


@router.get("/documents/{doc_id}")
def get_document(doc_id: int, db: Session = Depends(get_db)):
    d = db.query(Document).get(doc_id)
    if not d:
        raise HTTPException(404)
    n_p = db.query(Product).filter(Product.document_id == doc_id).count()
    n_r = db.query(Requirement).filter(Requirement.document_id == doc_id).count()
    n_i = db.query(Illustration).filter(Illustration.document_id == doc_id).count()
    return {
        "id": d.id,
        "filename": d.filename,
        "title": d.title,
        "status": d.status,
        "counts": {"products": n_p, "requirements": n_r, "illustrations": n_i},
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


@router.get("/requirements")
def list_requirements(document_id: int | None = None, product_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(Requirement).options(joinedload(Requirement.attributes))
    if document_id:
        q = q.filter(Requirement.document_id == document_id)
    if product_id:
        q = q.filter(Requirement.product_id == product_id)
    return [
        {
            "id": r.id,
            "code": r.code,
            "kind": r.kind.value,
            "text": r.text,
            "product_id": r.product_id,
            "parent_id": r.parent_id,
            "attributes": {a.key: a.value for a in r.attributes},
        }
        for r in q.all()
    ]


@router.post("/retrieval/context")
def retrieval_context(body: RetrievalRequest, db: Session = Depends(get_db)):
    return gather_context(db, **body.model_dump())


@router.post("/pipelines/validate-requirements")
def pipeline_validate(body: PipelineRequest, db: Session = Depends(get_db)):
    return validate_requirements(db, **body.model_dump())


@router.post("/pipelines/generate-tests")
def pipeline_tests(body: PipelineRequest, db: Session = Depends(get_db)):
    return generate_tests(db, **body.model_dump())
