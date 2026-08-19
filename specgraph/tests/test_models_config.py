from specgraph.config import Settings
from specgraph.llm import model_info


def test_three_model_slots(monkeypatch):
    monkeypatch.setenv("CHEAP_BASE_URL", "http://cheap.local/v1")
    monkeypatch.setenv("CHEAP_API_KEY", "ck")
    monkeypatch.setenv("CHEAP_MODEL", "small-1")
    monkeypatch.setenv("EXPENSIVE_BASE_URL", "http://dear.local/v1")
    monkeypatch.setenv("EXPENSIVE_API_KEY", "ek")
    monkeypatch.setenv("EXPENSIVE_MODEL", "big-1")
    monkeypatch.setenv("EMBED_BASE_URL", "http://emb.local/v1")
    monkeypatch.setenv("EMBED_API_KEY", "bk")
    monkeypatch.setenv("EMBED_MODEL", "emb-1")
    s = Settings()
    assert s.cheap() == ("http://cheap.local/v1", "ck", "small-1")
    assert s.expensive() == ("http://dear.local/v1", "ek", "big-1")
    assert s.embed() == ("http://emb.local/v1", "bk", "emb-1")
    monkeypatch.setenv("VLM_BASE_URL", "http://vlm.local/v1")
    monkeypatch.setenv("VLM_API_KEY", "vk")
    monkeypatch.setenv("VLM_MODEL", "vision-1")
    s2 = Settings()
    assert s2.vlm() == ("http://vlm.local/v1", "vk", "vision-1")
