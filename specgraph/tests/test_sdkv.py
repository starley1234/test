from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from specgraph.db import Base
from specgraph.ingest.ids import find_appendix_ids, find_ids
from specgraph.ingest.pipeline import ingest_file, ingest_many
from specgraph.models import Attachment, EntityRelation, RelationType, Requirement

SDKV = Path(__file__).resolve().parents[1] / "input" / "sdkv"
TA1 = next(SDKV.glob("*ТА1.docx"))


def _db(tmp_path, monkeypatch):
    from specgraph import config

    monkeypatch.setattr(config.settings, "upload_dir", tmp_path)
    monkeypatch.setattr(config.settings, "media_dir", tmp_path)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_ssj_id_parser():
    assert find_ids("MK-SSJ-NEW.HRDW.FNCT.4-20_PSU-1d2V.001/A.03")[0].endswith("001/A.03")
    assert find_appendix_ids("согласно приложению «MK-SSJ-NEW.HRDW.00001/A-Уровни»")


def test_ta1_cards_and_parent_stubs(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    doc = ingest_file(db, TA1, TA1.name, index=False)
    reqs = db.query(Requirement).all()
    codes = {r.code for r in reqs}
    assert any("HRDW.FNCT" in c for c in codes)
    assert any(".SSTM." in c for c in codes)
    stubs = [r for r in reqs if (r.extra or {}).get("stub")]
    assert stubs
    derived = db.query(EntityRelation).filter(EntityRelation.rel_type == RelationType.DERIVED_FROM).count()
    assert derived >= 1
    # приложение упоминается в атрибутах
    attrs = []
    for r in reqs:
        attrs.extend(r.attributes)
    assert any("HRDW.0000" in (a.value or "") or a.key.startswith("приложение") or a.key.startswith("файл") for a in attrs)
    assert doc.id


def test_batch_binds_appendix_file(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    files = [(p, p.name) for p in SDKV.iterdir() if p.is_file()]
    docs = ingest_many(db, files, index=False)
    assert len(docs) >= 5
    atts = db.query(Attachment).all()
    assert atts
    # содержимое xlsx/записки попало в атрибут какого-то требования
    hit = False
    for r in db.query(Requirement).all():
        for a in r.attributes:
            if a.key.startswith("файл:") and len(a.value or "") > 20:
                hit = True
    assert hit or any(a.text_content for a in atts)
