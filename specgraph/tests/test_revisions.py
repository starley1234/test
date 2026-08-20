from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from specgraph.db import Base
from specgraph.ingest.pipeline import ingest_parsed_json
from specgraph.models import Requirement, RequirementRevision


def test_new_revision_archives_old(tmp_path, monkeypatch):
    from specgraph import config

    monkeypatch.setattr(config.settings, "upload_dir", tmp_path)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    v1 = {
        "products": [{"code": "P", "name": "Изделие"}],
        "requirements": [{"code": "REQ.X.001/A", "text": "старый текст", "product": "P"}],
    }
    ingest_parsed_json(db, v1, "v1.json", index=False)
    v2 = {
        "products": [{"code": "P", "name": "Изделие"}],
        "requirements": [{"code": "REQ.X.001/B", "text": "новый текст", "product": "P"}],
    }
    ingest_parsed_json(db, v2, "v2.json", index=False)

    cur = db.query(Requirement).filter(Requirement.base_code == "REQ.X.001", Requirement.is_current.is_(True)).one()
    assert cur.revision == "B"
    assert cur.text == "новый текст"
    old = db.query(RequirementRevision).filter(RequirementRevision.requirement_id == cur.id).all()
    assert old
    assert any("старый" in (r.text or "") for r in old)
