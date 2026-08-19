from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from specgraph.db import Base
from specgraph.ingest.extract import extract_docx, extracted_from_script_json
from specgraph.ingest.pipeline import ingest_file, ingest_parsed_json
from specgraph.ingest.structure import from_extracted, from_parsed_json
from specgraph.models import EntityRelation, Product, RelationType, Requirement
from specgraph.retrieval.context import expand_product, gather_context

INPUT = Path(__file__).resolve().parents[1] / "input"
JSON = INPUT / "response_1787127382719.json"
DOCX = INPUT / "требования_урезан.docx"


def test_docx_keeps_headings_and_images():
    ext = extract_docx(DOCX)
    assert any(b.kind == "heading" and b.heading_level == 1 for b in ext.blocks)
    assert any(b.kind == "heading" and "MK-114.OPPO.DATA.001" in b.text for b in ext.blocks)
    assert len(ext.images) >= 6
    assert any(b.kind == "table" for b in ext.blocks)


def test_script_json_yields_req_cards_and_modules():
    import json

    payload = json.loads(JSON.read_text(encoding="utf-8"))
    g = from_parsed_json(payload)
    codes = {r.code for r in g.requirements}
    assert "MK-114.OPPO.DATA.001/B" in codes
    assert "MK-114.OPPO.HWRQ.064/C" in codes
    assert any(".TPO.FNCT." in c for c in codes)
    assert any(p.code.startswith("MOD-") or "rms" in p.code for p in g.products)
    assert g.glossary
    assert any(rel.rel_type == "implements" for rel in g.relations)
    data001 = next(r for r in g.requirements if r.code == "MK-114.OPPO.DATA.001/B")
    assert "структур" in data001.text.lower() or "удобства кодирования" in data001.text.lower()
    assert data001.attributes.get("производное") == "да"


def test_ingest_json_and_expand(tmp_path, monkeypatch):
    import json

    from specgraph import config

    monkeypatch.setattr(config.settings, "upload_dir", tmp_path)
    monkeypatch.setattr(config.settings, "media_dir", tmp_path)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    payload = json.loads(JSON.read_text(encoding="utf-8"))
    doc = ingest_parsed_json(db, payload, index=False)
    assert db.query(Requirement).filter(Requirement.document_id == doc.id).count() >= 6
    impl = (
        db.query(EntityRelation)
        .filter(EntityRelation.rel_type == RelationType.IMPLEMENTS)
        .count()
    )
    assert impl >= 1
    mcu = db.query(Product).filter(Product.code == "MCU2").first()
    assert mcu is not None
    ctx = gather_context(db, product_id=mcu.id, hop=2)
    assert ctx["subgraphs"]
    names = " ".join(r["code"] for sg in ctx["subgraphs"] for r in sg["requirements"])
    assert "OPPO" in names or "HWRQ" in names or "DATA" in names


def test_ingest_docx_images(tmp_path, monkeypatch):
    from specgraph import config

    monkeypatch.setattr(config.settings, "upload_dir", tmp_path)
    monkeypatch.setattr(config.settings, "media_dir", tmp_path)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    doc = ingest_file(db, DOCX, DOCX.name, index=False)
    from specgraph.models import Illustration

    assert db.query(Illustration).filter(Illustration.document_id == doc.id).count() >= 6
    assert db.query(Requirement).filter(Requirement.document_id == doc.id).count() >= 4
