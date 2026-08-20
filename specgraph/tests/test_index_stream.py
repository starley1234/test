from specgraph.ingest.progress import file_role, iter_index
from specgraph.db import Base
from specgraph.ingest.pipeline import ingest_parsed_json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from pathlib import Path


def test_file_role():
    assert file_role("требования.docx") == "spec"
    assert file_role("MK-SSJ-NEW.HRDW.00001.docx") == "attachment"
    assert file_role("table.xlsx") == "attachment"


def test_iter_index_emits_entities(tmp_path, monkeypatch):
    from specgraph import config

    monkeypatch.setattr(config.settings, "upload_dir", tmp_path)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    p = tmp_path / "pack.json"
    p.write_text(
        '{"title":"t","products":[{"code":"P","name":"X"}],'
        '"requirements":[{"code":"R.1/A","text":"должен работать","product":"P"}]}',
        encoding="utf-8",
    )
    evs = list(iter_index(db, [(p, "pack.json")]))
    kinds = [e["event"] for e in evs]
    assert kinds[0] == "queued"
    assert "file_start" in kinds and "file_done" in kinds and kinds[-1] == "done"
    done = next(e for e in evs if e["event"] == "file_done")
    assert any(r["code"].startswith("R.1") for r in done["entities"]["requirements"])
