from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from specgraph.db import Base
from specgraph.ingest.pipeline import ingest_parsed_json, make_ingest_report
from specgraph.models import Requirement, RequirementDraft
from specgraph.pipelines.reviews import export_drafts, heuristic_drafts, set_draft


def test_ingest_report_and_draft_does_not_mutate_twin(tmp_path, monkeypatch):
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
            "requirements": [{"code": "R1", "text": "питание 27 В", "product": "P"}],
        },
        index=False,
    )
    assert make_ingest_report(db, doc)["requirements"] >= 1
    r = db.query(Requirement).filter_by(code="R1").one()
    original = r.text
    set_draft(db, r, "Должен: питание 27 В", reason="модальность", source="heuristic")
    db.commit()
    db.refresh(r)
    assert r.text == original
    assert db.query(RequirementDraft).count() == 1
    heuristic_drafts(db, [r.id])
    db.refresh(r)
    assert r.text == original
    rep = export_drafts(db, doc.id)
    assert rep["count"] >= 1
    assert "xlsx" in (rep.get("downloads") or {}) or "md" in (rep.get("downloads") or {})
