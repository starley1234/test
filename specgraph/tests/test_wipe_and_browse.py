from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from specgraph.db import Base, wipe_db
from specgraph.ingest.pipeline import ingest_parsed_json
from specgraph.models import Document, Product, Requirement


def test_wipe_clears_rows(tmp_path, monkeypatch):
    from specgraph import config, db as dbmod

    monkeypatch.setattr(config.settings, "upload_dir", tmp_path)
    monkeypatch.setattr(config.settings, "media_dir", tmp_path)

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    monkeypatch.setattr(dbmod, "engine", engine)
    monkeypatch.setattr(dbmod, "SessionLocal", Session)

    ingest_parsed_json(
        db,
        {
            "title": "demo",
            "products": [{"code": "P1", "name": "Блок"}],
            "requirements": [{"code": "R1", "text": "должен", "product": "P1"}],
        },
        index=False,
    )
    assert db.query(Document).count() == 1
    wipe_db()
    db2 = Session()
    assert db2.query(Document).count() == 0
    assert db2.query(Product).count() == 0
    assert db2.query(Requirement).count() == 0
