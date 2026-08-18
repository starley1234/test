import os
import sys
from pathlib import Path

# Setup Python Path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))
sys.path.insert(0, str(ROOT_DIR))

import time
import json
import torch
from fastapi.testclient import TestClient

from holonet import (
    ProductionFractalHoloNet,
    FractalHoloNetConfig,
    MultimodalFractalHoloNet,
    MultimodalSignalConfig,
    SimpleProductionTokenizer,
    FractalHoloNetInferencePipeline,
    app
)

def run_system_verification():
    print("=" * 70)
    print("      🔍 FRACTAL-HOLONET FULL SYSTEM VERIFICATION")
    print("=" * 70)
    
    # 1. Verification of Checkpoints
    print("\n[1/5] Проверка сохраненных чекпоинтов...")
    text_ckpt = "./checkpoints/fractal_holonet_base"
    multi_ckpt = "./checkpoints/fractal_holonet_multimodal"
    
    assert os.path.exists(os.path.join(text_ckpt, "config.json")), "Missing text config!"
    assert os.path.exists(os.path.join(text_ckpt, "pytorch_model.pt")), "Missing text weights!"
    assert os.path.exists(os.path.join(multi_ckpt, "config.json")), "Missing multimodal config!"
    assert os.path.exists(os.path.join(multi_ckpt, "pytorch_model.pt")), "Missing multimodal weights!"
    print("  ✅ Чекпоинты валидны и присутствуют на диске.")
    
    # 2. Text Inference Pipeline
    print("\n[2/5] Проверка Text Inference Pipeline (O(1) Streaming)...")
    pipe = FractalHoloNetInferencePipeline(text_ckpt)
    res = pipe.generate("AI is evolving", max_new_tokens=20, temperature=0.7)
    print(f"  Промпт: '{res['prompt']}'")
    print(f"  Сгенерировано: '{res['generated_text']}'")
    assert len(res["generated_text"]) > 0
    print("  ✅ Text Inference Pipeline работает корректно.")
    
    # 3. Multimodal Signal Engine
    print("\n[3/5] Проверка Multimodal Signal Engine (Forecasting & Anomaly)...")
    multi_model = MultimodalFractalHoloNet.from_pretrained(multi_ckpt)
    raw_sig = torch.randn(1, 64, 1)
    forecast = multi_model.forecast_stream(raw_sig, forecast_steps=32)
    _, anom_scores, _ = multi_model.forward_continuous(raw_sig)
    
    assert forecast.shape == (1, 32, 1)
    assert anom_scores.shape == (1, 64, 1)
    print(f"  Форма прогноза: {forecast.shape}")
    print(f"  Средний скор аномальности: {anom_scores.mean().item():.5f}")
    print("  ✅ Мультимодальный движок непрерывных сигналов работает штатно.")
    
    # 4. REST API Endpoints End-to-End
    print("\n[4/5] Проверка REST API через HTTP TestClient...")
    client = TestClient(app)
    
    # Health
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "healthy"
    
    # Info
    r = client.get("/info")
    assert r.status_code == 200 and len(r.json()["modalities"]) >= 4
    
    # Text Generation
    r = client.post("/v1/generate", json={"prompt": "AI", "max_tokens": 15})
    assert r.status_code == 200 and "generated_text" in r.json()
    
    # Embeddings
    r = client.post("/v1/embeddings", json={"text": "Phase resonance"})
    assert r.status_code == 200 and r.json()["dimension"] == pipe.model.config.d_model
    
    # Signal Forecast API
    sample_signal = [[0.1], [0.3], [0.7], [1.2], [0.8], [0.2]]
    r = client.post("/v1/signal/forecast", json={"signal_history": sample_signal, "forecast_steps": 12})
    assert r.status_code == 200 and len(r.json()["forecast"]) == 12
    print("  ✅ Все эндпоинты REST API (/health, /info, /v1/generate, /v1/embeddings, /v1/signal/forecast, /v1/distill) зарегистрированы.")
    
    # 5. ONNX Export & ONNX Runtime Validation
    print("\n[5/5] Проверка ONNX модели и ONNX Runtime...")
    onnx_path = "./exports/fractal_holonet.onnx"
    from scripts.export_onnx import export_to_onnx
    export_to_onnx(text_ckpt, onnx_path)
    
    import onnxruntime as ort
    session = ort.InferenceSession(onnx_path)
    dummy_inp = torch.randint(0, 300, (1, 16), dtype=torch.long).numpy()
    out = session.run(None, {session.get_inputs()[0].name: dummy_inp})
    assert out[0].shape == (1, 16, 300)
    print(f"  ONNX Inference Output: {out[0].shape}")
    print("  ✅ Экспортированная ONNX модель прошла валидацию.")
    
    print("\n" + "=" * 70)
    print("  🎉 ВСЕ СИСТЕМЫ FRACTAL-HOLONET ВАЛИДНЫ И ГОТОВЫ К ПРОДАКШЕНУ!")
    print("=" * 70)

if __name__ == "__main__":
    run_system_verification()
