from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from specgraph.db import Base
from specgraph.ingest.pipeline import ingest_parsed_json, make_ingest_report
from specgraph.models import Requirement
from specgraph.pipelines.reviews import apply_draft, set_draft


def test_ingest_report_and_apply_draft(tmp_path, monkeypatch):
    from specgraph import config

    monkeypatch.setattr(config.settings, "upload_dir", tmp_path)
    monkeypatch.setattr(config.settings, "media_dir", tmp_path)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    doc = ingest_parsed_json(
        db,
        {
            "title": "t",
            "products": [{"code": "P", "name": "Блок"}],
            "requirements": [{"code": "R1", "text": "должен быть", "product": "P"}],
        },
        index=False,
    )
    rep = make_ingest_report(db, doc)
    assert rep["requirements"] >= 1
    r = db.query(Requirement).filter_by(code="R1").one()
    set_draft(db, r, "Блок должен выдавать 27 В.")
    db.commit()
    apply_draft(db, r)
    db.refresh(r)
    assert "27" in r.text
    assert not (r.extra or {}).get("draft_text")
