import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))

from holonet import FractalHoloNetInferencePipeline

prompts = [
    "Искусственный интеллект — это",
    "Архитектура Fractal-HoloNet построена на",
    "Мороз и солнце; день чудесный!",
    "У лукоморья дуб зеленый;"
]

def run_ru_inference():
    pipe = FractalHoloNetInferencePipeline("./checkpoints/fractal_holonet_base")
    results = []
    print("=" * 70)
    print("  🇷🇺 ТЕСТИРОВАНИЕ РУССКОЯЗЫЧНОЙ ГЕНЕРАЦИИ FRACTAL-HOLONET")
    print("=" * 70)

    for p in prompts:
        res = pipe.generate(p, max_new_tokens=120, temperature=0.4, top_k=20, top_p=0.85)
        print(f"\n[ПРОМПТ]: {p}")
        print(f"[ПРОДОЛЖЕНИЕ]: {res['generated_text']}")
        print(f"[ИТОГОВЫЙ ТЕКСТ]:\n{res['full_text']}")
        print("-" * 70)
        results.append(res)
    return results

def test_russian_inference_output():
    results = run_ru_inference()
    assert len(results) == len(prompts)
    for res in results:
        assert len(res["generated_text"]) > 0

if __name__ == "__main__":
    run_ru_inference()
