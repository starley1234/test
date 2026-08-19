from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from sqlalchemy.orm import Session, joinedload

from specgraph.api.schemas import DocumentOut, IngestJsonRequest, PipelineRequest, ProductOut, RetrievalRequest
from specgraph.auth import can_run_pipeline, optional_user, require_admin
from specgraph.config import settings
from specgraph.db import get_db, wipe_db
from specgraph.models import User
from specgraph.ingest.ids import base_code
from specgraph.ingest.pipeline import ingest_file, ingest_many, ingest_parsed_json
from specgraph.models import Attachment, Document, EntityRelation, EntityType, Illustration, Product, RelationType, Requirement
from specgraph.retrieval.context import gather_context

router = APIRouter()
STATIC = Path(__file__).resolve().parent.parent / "static"


def _need_pipe(name: str, user: User | None) -> None:
    if not can_run_pipeline(user, name):
        raise HTTPException(403, f"нет роли для пайплайна {name}")


@router.get("/", response_class=HTMLResponse)
def ui():
    return (STATIC / "index.html").read_text(encoding="utf-8")


@router.post("/documents", response_model=DocumentOut)
async def upload_document(
    file: UploadFile = File(...), db: Session = Depends(get_db), user: User | None = Depends(optional_user)
):
    suffix = Path(file.filename or "upload.bin").name
    tmp = settings.upload_dir / f"tmp_{uuid4().hex}_{suffix}"
    tmp.write_bytes(await file.read())
    try:
        doc = ingest_file(db, tmp, suffix, index=False, uploaded_by_id=user.id if user else None)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"ingest failed: {exc}") from exc
    return DocumentOut(id=doc.id, filename=doc.filename, kind=doc.kind.value, title=doc.title, status=doc.status)


@router.get("/index/history")
def index_history(db: Session = Depends(get_db)):
    from specgraph.models import IndexBatch

    rows = db.query(IndexBatch).order_by(IndexBatch.id.desc()).limit(80).all()
    return [
        {
            "id": b.id,
            "created_at": b.created_at.isoformat() if b.created_at else None,
            "uploaded_by_id": b.uploaded_by_id,
            "files": b.files,
            "totals": b.totals,
            "document_ids": b.document_ids,
            "status": b.status,
        }
        for b in rows
    ]


@router.post("/db/wipe")
def wipe_database(_: User = Depends(require_admin)):
    wipe_db()
    return {"ok": True, "cleared": True}


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    from specgraph.ingest.progress import db_totals

    recent = (
        db.query(Requirement)
        .options(joinedload(Requirement.attributes))
        .filter(Requirement.is_current.is_(True))
        .order_by(Requirement.id.desc())
        .limit(30)
        .all()
    )
    return {
        "totals": db_totals(db),
        "recent_requirements": [_req_dump(r) for r in recent],
    }


@router.post("/index")
async def index_stream(
    files: list[UploadFile] = File(...), db: Session = Depends(get_db), user: User | None = Depends(optional_user)
):
    """Пакет файлов → поток NDJSON: файл за файлом и появившиеся сущности."""
    import json

    from specgraph.ingest.progress import iter_index

    packed: list[tuple[Path, str]] = []
    for file in files:
        name = Path(file.filename or "upload.bin").name
        tmp = settings.upload_dir / f"tmp_{uuid4().hex}_{name}"
        tmp.write_bytes(await file.read())
        packed.append((tmp, name))

    def gen():
        for ev in iter_index(db, packed, uploaded_by_id=user.id if user else None):
            yield json.dumps(ev, ensure_ascii=False) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


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
    return [
        DocumentOut(
            id=d.id,
            filename=d.filename,
            kind=d.kind.value,
            title=d.title,
            status=d.status,
            uploaded_by_id=d.uploaded_by_id,
        )
        for d in docs
    ]


@router.get("/documents/{doc_id}")
def get_document(doc_id: int, db: Session = Depends(get_db)):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(404)
    n_p = db.query(Product).filter(Product.document_id == doc_id).count()
    n_r = db.query(Requirement).filter(Requirement.document_id == doc_id).count()
    n_i = db.query(Illustration).filter(Illustration.document_id == doc_id).count()
    n_a = db.query(Attachment).filter(Attachment.document_id == doc_id).count()
    products = (
        db.query(Product).filter(Product.document_id == doc_id).order_by(Product.level, Product.id).all()
    )
    return {
        "id": d.id,
        "filename": d.filename,
        "kind": d.kind.value if d.kind else None,
        "title": d.title,
        "status": d.status,
        "uploaded_by_id": d.uploaded_by_id,
        "parse_meta": d.parse_meta,
        "counts": {"products": n_p, "requirements": n_r, "illustrations": n_i, "attachments": n_a},
        "products": [
            {"id": p.id, "code": p.code, "name": p.name, "level": p.level, "parent_id": p.parent_id} for p in products
        ],
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
    p = db.get(Product, product_id)
    if p:
        sg["document_id"] = p.document_id
        doc = db.get(Document, p.document_id)
        if doc:
            sg["document"] = {"id": doc.id, "filename": doc.filename, "title": doc.title, "status": doc.status}
    return sg


@router.get("/products/{product_id}/documents")
def product_documents(product_id: int, db: Session = Depends(get_db)):
    """Документы, связанные с изделием: свой документ + документы требований этого изделия / того же кода."""
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(404)
    ids: set[int] = set()
    if p.document_id:
        ids.add(p.document_id)
    same = db.query(Product).filter(Product.code == p.code).all()
    for s in same:
        if s.document_id:
            ids.add(s.document_id)
    reqs = db.query(Requirement).filter(
        Requirement.is_current.is_(True),
        (Requirement.product_id == product_id) | (Requirement.product_id.in_([s.id for s in same])),
    ).all()
    for r in reqs:
        if r.document_id:
            ids.add(r.document_id)
    docs = db.query(Document).filter(Document.id.in_(ids)).order_by(Document.id.desc()).all() if ids else []
    out = []
    for d in docs:
        n_r = db.query(Requirement).filter(Requirement.document_id == d.id, Requirement.is_current.is_(True)).count()
        n_p = db.query(Product).filter(Product.document_id == d.id).count()
        out.append(
            {
                "id": d.id,
                "filename": d.filename,
                "title": d.title,
                "status": d.status,
                "kind": d.kind.value if d.kind else None,
                "counts": {"requirements": n_r, "products": n_p},
                "own": d.id == p.document_id,
            }
        )
    return {"product": {"id": p.id, "code": p.code, "name": p.name}, "documents": out}


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
        "base_code": r.base_code,
        "revision": r.revision,
        "is_current": r.is_current,
        "created_at": r.created_at.isoformat() if getattr(r, "created_at", None) else None,
        "attributes": {a.key: a.value for a in r.attributes},
    }


@router.get("/requirements")
def list_requirements(document_id: int | None = None, product_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(Requirement).options(joinedload(Requirement.attributes)).filter(Requirement.is_current.is_(True))
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
def pipeline_validate(
    body: PipelineRequest, db: Session = Depends(get_db), user: User | None = Depends(optional_user)
):
    _need_pipe("validate-requirements", user)
    from specgraph.pipelines.graphs import validate_requirements

    return validate_requirements(db, **body.model_dump())


@router.post("/pipelines/generate-tests")
def pipeline_tests(body: PipelineRequest, db: Session = Depends(get_db), user: User | None = Depends(optional_user)):
    _need_pipe("generate-tests", user)
    from specgraph.pipelines.graphs import generate_tests

    return generate_tests(db, **body.model_dump())


@router.post("/pipelines/summarize")
def pipeline_summarize(
    body: PipelineRequest, db: Session = Depends(get_db), user: User | None = Depends(optional_user)
):
    _need_pipe("summarize", user)
    from specgraph.pipelines.graphs import summarize_context

    return summarize_context(db, **body.model_dump())


@router.get("/tree")
def product_tree(db: Session = Depends(get_db)):
    prods = db.query(Product).order_by(Product.level, Product.id).all()
    reqs = db.query(Requirement).filter(Requirement.is_current.is_(True)).all()
    by_parent: dict[int | None, list] = {}
    for p in prods:
        by_parent.setdefault(p.parent_id, []).append(p)
    req_by_p: dict[int | None, list] = {}
    for r in reqs:
        req_by_p.setdefault(r.product_id, []).append(r)

    def node(p: Product) -> dict:
        kids = [node(c) for c in by_parent.get(p.id, [])]
        mine = [
            {
                "id": r.id,
                "code": r.code,
                "text": (r.text or "")[:160],
                "kind": r.kind.value,
                "created_at": r.created_at.isoformat() if getattr(r, "created_at", None) else None,
            }
            for r in req_by_p.get(p.id, [])
            if not (r.extra or {}).get("stub")
        ]
        return {
            "id": p.id,
            "code": p.code,
            "name": p.name,
            "level": p.level,
            "requirements": mine,
            "children": kids,
        }

    roots = [node(p) for p in by_parent.get(None, [])]
    orphan_reqs = [
        {
            "id": r.id,
            "code": r.code,
            "text": (r.text or "")[:160],
            "kind": r.kind.value,
            "created_at": r.created_at.isoformat() if getattr(r, "created_at", None) else None,
        }
        for r in req_by_p.get(None, [])
        if not (r.extra or {}).get("stub")
    ]
    return {"roots": roots, "orphan_requirements": orphan_reqs}


@router.get("/pipelines/{name}/blueprint")
def pipeline_blueprint(name: str):
    from specgraph.pipelines.blueprint import blueprint

    try:
        return blueprint(name)
    except KeyError:
        raise HTTPException(404, name) from None


@router.post("/mcp")
def mcp_rpc(body: dict = None):
    from specgraph.mcp_server import handle_rpc

    return handle_rpc(body)


@router.get("/mcp/tools")
def mcp_tools():
    from specgraph.mcp_server import TOOLS

    return {"tools": TOOLS}


@router.get("/pipelines")
def list_pipelines():
    from specgraph.pipelines.graphs import _catalog

    cat = _catalog()
    out = []
    for name, e in cat.items():
        if name.startswith("_"):
            continue
        out.append({"name": name, "title": e.get("title") or name, "slot": e.get("slot"), "kind": e.get("kind")})
    return out


@router.post("/pipelines/runs/schematic-coverage")
async def start_schematic_run(
    file: UploadFile = File(...),
    document_id: int | None = None,
    requirement_ids: str | None = None,
    user: User | None = Depends(optional_user),
):
    _need_pipe("schematic-coverage", user)
    from specgraph.pipelines.jobs import start_job

    fname = Path(file.filename or "scheme.bin").name
    tmp = settings.upload_dir / f"scheme_{uuid4().hex}_{fname}"
    tmp.write_bytes(await file.read())
    ids = None
    if requirement_ids:
        import json

        ids = json.loads(requirement_ids)
    job = start_job(
        "schematic-coverage",
        {"document_id": document_id, "requirement_ids": ids},
        scheme_path=tmp,
        scheme_name=fname,
        user_id=user.id if user else None,
    )
    return {"run_id": job.id, "name": "schematic-coverage"}


@router.post("/pipelines/runs/{name}")
def start_named_run(name: str, body: PipelineRequest, user: User | None = Depends(optional_user)):
    from specgraph.pipelines.graphs import _catalog
    from specgraph.pipelines.jobs import start_job

    if name.startswith("_") or name not in _catalog():
        raise HTTPException(404, f"unknown pipeline: {name}")
    _need_pipe(name, user)
    job = start_job(name, body.model_dump(exclude_none=True), user_id=user.id if user else None)
    return {"run_id": job.id, "name": name}


@router.get("/pipelines/runs/{run_id}")
def get_run(run_id: str):
    from specgraph.pipelines.jobs import get_job

    job = get_job(run_id)
    if not job:
        raise HTTPException(404)
    return job.snapshot()


@router.get("/pipelines/runs/{run_id}/stream")
def stream_run(run_id: str):
    from specgraph.pipelines.jobs import get_job, ndjson

    job = get_job(run_id)
    if not job:
        raise HTTPException(404)
    return StreamingResponse(ndjson(job), media_type="application/x-ndjson")


@router.post("/pipelines/review-correctness")
def pipeline_correctness(
    body: PipelineRequest, db: Session = Depends(get_db), user: User | None = Depends(optional_user)
):
    _need_pipe("review-correctness", user)
    from specgraph.pipelines.correctness import run_correctness_matrix

    return run_correctness_matrix(
        db,
        document_id=body.document_id,
        product_id=body.product_id,
        requirement_ids=body.requirement_ids,
    )


@router.post("/pipelines/unit-tests")
def pipeline_unit_tests(
    body: PipelineRequest, db: Session = Depends(get_db), user: User | None = Depends(optional_user)
):
    _need_pipe("unit-tests", user)
    from specgraph.pipelines.unit_tests import run_unit_tests

    return run_unit_tests(
        db,
        document_id=body.document_id,
        requirement_id=body.requirement_id,
        requirement_ids=body.requirement_ids,
        query=body.query,
        source_code=body.source_code,
    )


@router.post("/pipelines/schematic-coverage")
async def pipeline_schematic(
    file: UploadFile = File(...),
    document_id: int | None = None,
    db: Session = Depends(get_db),
    user: User | None = Depends(optional_user),
):
    _need_pipe("schematic-coverage", user)
    from specgraph.pipelines.schematic import run_schematic_coverage

    name = Path(file.filename or "scheme.bin").name
    tmp = settings.upload_dir / f"scheme_{uuid4().hex}_{name}"
    tmp.write_bytes(await file.read())
    try:
        return run_schematic_coverage(db, tmp, name, document_id=document_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/pipelines/{name}")
def run_named_pipeline(
    name: str, body: PipelineRequest, db: Session = Depends(get_db), user: User | None = Depends(optional_user)
):
    from specgraph.pipelines.graphs import run_pipeline

    _need_pipe(name, user)
    try:
        return run_pipeline(name, db, **body.model_dump())
    except KeyError:
        raise HTTPException(404, f"unknown pipeline: {name}") from None


@router.get("/exports/{filename}")
def download_export(filename: str):
    from specgraph.pipelines.correctness import EXPORTS as C_EX
    from specgraph.pipelines.schematic import EXPORTS as S_EX
    from specgraph.pipelines.unit_tests import EXPORTS as U_EX

    name = Path(filename).name
    path = next((p for p in (C_EX / name, S_EX / name, U_EX / name) if p.is_file()), None)
    if not path:
        raise HTTPException(404, "file not found")
    return FileResponse(path, filename=path.name)


@router.get("/requirements/{req_id}/revisions")
def list_revisions(req_id: int, db: Session = Depends(get_db)):
    from specgraph.models import RequirementRevision

    rows = (
        db.query(RequirementRevision)
        .filter(RequirementRevision.requirement_id == req_id)
        .order_by(RequirementRevision.id.desc())
        .all()
    )
    return [
        {
            "id": x.id,
            "code": x.code,
            "revision": x.revision,
            "text": x.text,
            "attributes": x.attributes,
            "superseded_at": x.superseded_at.isoformat() if x.superseded_at else None,
        }
        for x in rows
    ]
