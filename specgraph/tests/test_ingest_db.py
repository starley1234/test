from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from specgraph.db import Base
from specgraph.ingest.pipeline import ingest_parsed_json
from specgraph.models import Product, Requirement
from specgraph.retrieval.context import context_as_prompt, expand_product, gather_context


def test_json_ingest_and_expand(tmp_path, monkeypatch):
    from specgraph import config

    monkeypatch.setattr(config.settings, "upload_dir", tmp_path)
    monkeypatch.setattr(config.settings, "media_dir", tmp_path)

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    payload = {
        "title": "demo",
        "products": [
            {"code": "ROOT", "name": "Система"},
            {"code": "CH", "name": "Блок", "parent": "ROOT", "level": 1, "attributes": {"масса": "1"}},
        ],
        "requirements": [{"code": "ТР-1", "text": "Блок должен быть", "product": "CH"}],
    }
    doc = ingest_parsed_json(db, payload, index=False)
    assert db.query(Product).count() >= 2
    child = db.query(Product).filter(Product.code == "CH").one()
    assert child.parent_id is not None
    assert db.query(Requirement).filter(Requirement.product_id == child.id).count() == 1
    sg = expand_product(db, child.id)
    assert sg["product"]["code"] == "CH"
    assert sg["ancestors"][0]["code"] == "ROOT"
    assert sg["requirements"]
    assert doc.id
    ctx = gather_context(db, document_id=doc.id)
    assert ctx["requirements"]
    prompt = context_as_prompt(ctx)
    assert "ТР-1" in prompt
