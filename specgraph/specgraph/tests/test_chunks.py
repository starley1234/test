from specgraph.retrieval.chunks import split_text
from specgraph.retrieval.context import pack_budget


def test_split_text_overlap():
    body = ("абзац один.\n" * 80) + ("абзац два.\n" * 80)
    parts = split_text(body, size=200, overlap=20)
    assert len(parts) > 1
    assert all(p[2] for p in parts)


def test_pack_budget():
    bundle = {
        "seed_requirement": {"text": "x" * 5000, "parents": [{"text": "y" * 2000}]},
        "requirements": [{"text": "z" * 3000, "attributes": {}}],
        "hits": [],
        "chunks": [{"text": "c" * 1000}],
    }
    out = pack_budget(bundle, budget=1500)
    assert out["packed_chars"] <= 1500
    assert len(out["seed_requirement"]["text"]) > 0
