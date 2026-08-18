import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))

import time
import torch
from holonet import FractalHoloNetInferencePipeline, MultimodalFractalHoloNet

test_cases = [
    {
        "category": "Классическая драматургия / Диалог",
        "prompt": "First Citizen:\nWe are accounted poor citizens, the patricians good.\nWhat authority surfeits on would",
        "max_tokens": 100,
        "temperature": 0.6,
        "top_k": 30,
        "top_p": 0.9
    },
    {
        "category": "Эмоциональный монолог",
        "prompt": "KING RICHARD:\nGive me another horse: bind up my wounds.\nHave mercy,",
        "max_tokens": 80,
        "temperature": 0.7,
        "top_k": 40,
        "top_p": 0.95
    },
    {
        "category": "Поэтический контекст",
        "prompt": "ROMEO:\nO, speak again, bright angel! for thou art\nAs glorious to",
        "max_tokens": 80,
        "temperature": 0.5,
        "top_k": 20,
        "top_p": 0.85
    },
    {
        "category": "Короткий зачин",
        "prompt": "HAMLET:\nTo be, or not to be, that is the",
        "max_tokens": 60,
        "temperature": 0.6,
        "top_k": 25,
        "top_p": 0.9
    }
]

def test_language_model_responses():
    print("=" * 75)
    print("  🎭 ТЕСТИРОВАНИЕ ОТВЕТОВ ЯЗЫКОВОЙ МОДЕЛИ FRACTAL-HOLONET")
    print("=" * 75)
    
    pipe = FractalHoloNetInferencePipeline("./checkpoints/fractal_holonet_base")
    
    for i, tc in enumerate(test_cases, 1):
        print(f"\n[{i}/{len(test_cases)}] Категория: {tc['category']}")
        print(f"--- Промпт ---:\n{tc['prompt']}")
        
        t0 = time.perf_counter()
        res = pipe.generate(
            prompt=tc["prompt"],
            max_new_tokens=tc["max_tokens"],
            temperature=tc["temperature"],
            top_k=tc["top_k"],
            top_p=tc["top_p"]
        )
        gen_time = time.perf_counter() - t0
        tok_per_sec = res["generated_tokens"] / max(gen_time, 1e-6)
        
        print(f"--- Ответ модели ---:\n{res['generated_text']}")
        print(f"⚡ Токенов сгенерировано: {res['generated_tokens']} за {gen_time*1000:.2f} ms ({tok_per_sec:.1f} tok/s)")
        print("-" * 75)
        assert len(res["generated_text"]) > 0

def test_multimodal_signal_responses():
    print("\n" + "=" * 75)
    print("  🌊 ТЕСТИРОВАНИЕ ОТВЕТОВ МУЛЬТИМОДАЛЬНОЙ МОДЕЛИ (НЕПРЕРЫВНЫЕ СИГНАЛЫ)")
    print("=" * 75)
    
    ckpt_path = "./checkpoints/fractal_holonet_multimodal"
    model = MultimodalFractalHoloNet.from_pretrained(ckpt_path)
    model.eval()
    
    # 1. Тест прогноза непрерывной синусоиды
    t = torch.linspace(0, 4 * 3.14159, 64)
    normal_signal = (torch.sin(t) + 0.3 * torch.sin(2.5 * t)).unsqueeze(0).unsqueeze(-1)
    
    t0 = time.perf_counter()
    forecast = model.forecast_stream(normal_signal, forecast_steps=32)
    lat_forecast = (time.perf_counter() - t0) * 1000.0
    
    print(f"✅ Непрерывный авторегрессионный прогноз 32 шагов выполнен за {lat_forecast:.2f} ms")
    print(f"   Форма выхода: {forecast.shape}")
    assert forecast.shape == (1, 32, 1)
    
    # 2. Тест детекции аномалий
    anomalous_signal = normal_signal.clone()
    anomalous_signal[0, 40:48, 0] += 3.5
    
    _, anom_scores, _ = model.forward_continuous(anomalous_signal)
    max_anom = anom_scores[0, 40:48, 0].max().item()
    base_anom = anom_scores[0, :30, 0].mean().item()
    
    print(f"✅ Детекция аномалий:")
    print(f"   Фоновый скор аномальности (норма): {base_anom:.6f}")
    print(f"   Пиковый скор аномальности (всплеск): {max_anom:.6f}")
    print(f"   Коэффициент обнаружения: x{max_anom / max(base_anom, 1e-6):.1f}")
    print("=" * 75)
    assert max_anom > base_anom

if __name__ == "__main__":
    test_language_model_responses()
    test_multimodal_signal_responses()
