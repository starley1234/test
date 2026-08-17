import os
import pytest
import torch
from fastapi.testclient import TestClient

from fractal_holonet_prod import ProductionFractalHoloNet, FractalHoloNetConfig
from pipeline import SimpleProductionTokenizer, FractalHoloNetInferencePipeline
from serve import app

@pytest.fixture
def test_checkpoint_dir(tmp_path):
    checkpoint_dir = str(tmp_path / "model_test")
    # Vocab size 300 to comfortably fit all 256 ASCII/byte values + special tokens
    config = FractalHoloNetConfig(vocab_size=300, d_model=64, n_layers=2, d_ff=128)
    model = ProductionFractalHoloNet(config)
    model.save_pretrained(checkpoint_dir)
    
    tokenizer = SimpleProductionTokenizer()
    tokenizer.save(os.path.join(checkpoint_dir, "tokenizer.json"))
    return checkpoint_dir

def test_model_forward_and_generate(test_checkpoint_dir):
    model = ProductionFractalHoloNet.from_pretrained(test_checkpoint_dir)
    model.eval()
    
    # 1. Sequence forward pass
    inp = torch.randint(0, 300, (2, 16))
    logits, states = model(inp)
    assert logits.shape == (2, 16, 300)
    assert len(states) == 2 # 2 layers
    
    # 2. Step forward pass (O(1) streaming)
    step_inp = torch.randint(0, 300, (2, 1))
    step_logits, next_states = model(step_inp, states=states, use_step=True)
    assert step_logits.shape == (2, 1, 300)
    
    # 3. Autoregressive generation
    gen = model.generate(torch.tensor([[10, 20]]), max_new_tokens=10)
    assert gen.size(0) == 1
    assert gen.size(1) >= 3

def test_pipeline_integration(test_checkpoint_dir):
    pipe = FractalHoloNetInferencePipeline(test_checkpoint_dir)
    out = pipe.generate("hello", max_new_tokens=10)
    assert "generated_text" in out
    assert "prompt_tokens" in out
    
    emb = pipe.get_embeddings("hello world")
    assert len(emb) == 64 # d_model

def test_fastapi_endpoints():
    client = TestClient(app)
    
    # Health
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"
    
    # Info
    r = client.get("/info")
    assert r.status_code == 200
    assert "architecture" in r.json()
    assert r.json()["status"] == "ready"
    
    # Generate
    r = client.post("/v1/generate", json={"prompt": "ABC", "max_tokens": 15})
    assert r.status_code == 200
    assert "generated_text" in r.json()
    assert "latency_ms" in r.json()
    
    # Embeddings
    r = client.post("/v1/embeddings", json={"text": "ABC"})
    assert r.status_code == 200
    assert "embedding" in r.json()
    assert r.json()["dimension"] == 128
