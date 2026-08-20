from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from specgraph.db import Base
from specgraph.ingest.pipeline import ingest_parsed_json
from specgraph.pipelines.schematic import cover, load_pages, run_schematic_coverage


def test_cover_matches_node_to_requirement(tmp_path, monkeypatch):
    from specgraph import config
    from specgraph.pipelines import schematic as sch

    monkeypatch.setattr(config.settings, "upload_dir", tmp_path)
    monkeypatch.setattr(sch, "EXPORTS", tmp_path)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    ingest_parsed_json(
        db,
        {
            "products": [{"code": "PSU-3V3", "name": "Преобразователь 3.3 В"}],
            "requirements": [
                {
                    "code": "X.HRDW.FNCT.PSU-3V3.001/A",
                    "text": "Узел преобразователя 3.3 В должен выдавать 3.3±0.3 В.",
                    "product": "PSU-3V3",
                }
            ],
        },
        index=False,
    )
    scheme = {
        "title": "тест",
        "nodes": [{"id": "PSU-3V3", "name": "преобразователь 3.3 В", "kind": "psu"}],
        "edges": [],
        "mode": "heuristic",
    }
    cov = cover(scheme, db, None)
    assert cov["nodes_covered"] == 1
    assert cov["pass"] is True

    png = tmp_path / "s.png"
    png.write_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
        )
    )
    assert load_pages(png)[0][0] == "image/png"
    out = run_schematic_coverage(db, png, "s.png")
    assert "coverage" in out
    assert Path(out["output_file"]).is_file()
