from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from specgraph.db import Base
from specgraph.ingest.pipeline import ingest_file, ingest_many
from specgraph.ingest.structure import split_source_refs
from specgraph.models import Attachment, EntityRelation, RelationType, Requirement
from specgraph.retrieval.context import expand_requirement

SDKV = Path(__file__).resolve().parents[1] / "input" / "sdkv"
TA1 = next(SDKV.glob("*ТА1.docx"))


def _db(tmp_path, monkeypatch):
    from specgraph import config

    monkeypatch.setattr(config.settings, "upload_dir", tmp_path)
    monkeypatch.setattr(config.settings, "media_dir", tmp_path)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_source_field_split_by_structure_not_mask():
    raw = "FOO.BAR.ANYTHING.999/Z\n-\nXYZ.PARENT.1\n"
    refs = split_source_refs(raw)
    assert refs == ["FOO.BAR.ANYTHING.999/Z", "XYZ.PARENT.1"]


def test_ta1_cards_and_parent_stubs(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    doc = ingest_file(db, TA1, TA1.name, index=False)
    reqs = db.query(Requirement).all()
    real = [r for r in reqs if not (r.extra or {}).get("stub")]
    assert len(real) >= 80
    assert any(r.attributes for r in real)
    stubs = [r for r in reqs if (r.extra or {}).get("stub")]
    assert stubs
    derived = db.query(EntityRelation).filter(EntityRelation.rel_type == RelationType.DERIVED_FROM).count()
    assert derived >= 1
    sample = next(r for r in real if r.text and len(r.text) > 40)
    ctx = expand_requirement(db, sample.id)
    assert ctx["code"] == sample.code
    assert doc.id


def test_batch_binds_appendix_file(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    files = [(p, p.name) for p in SDKV.iterdir() if p.is_file()]
    docs = ingest_many(db, files, index=False)
    assert len(docs) >= 5
    atts = db.query(Attachment).all()
    assert atts
    hit = False
    for r in db.query(Requirement).all():
        for a in r.attributes:
            if a.key.startswith("файл:") and len(a.value or "") > 20:
                hit = True
    assert hit or any(a.text_content for a in atts)
