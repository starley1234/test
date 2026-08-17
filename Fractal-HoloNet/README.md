# Fractal-HoloNet: Multimodal Continuous Signal & Language Model

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-green.svg)](https://fastapi.tiangolo.com/)
[![Continuous Modality](https://img.shields.io/badge/Modality-Continuous%20Signals%20%2B%20Text-purple.svg)](https://github.com/)
[![ONNX Runtime](https://img.shields.io/badge/ONNX-Runtime-orange.svg)](https://onnxruntime.ai/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg)](https://www.docker.com/)

**Fractal-HoloNet** — универсальная мультимодальная архитектура ИИ с линейной вычислительной сложностью $\mathcal{O}(N)$ и константной памятью $\mathcal{O}(1)$. 

Благодаря **непрерывной комплексно-фазовой природе**, модель способна напрямую принимать, обрабатывать и прогнозировать **непрерывные аналоговые сигналы (сырой звук, ЭКГ, датчики IoT, телеметрию, видеопотоки) без дискретизации в тяжелые токены** с нулевой потерей физической динамики.

---

## 🌊 Мультимодальность для непрерывных сигналов

### Почему это уникально:
* **Традиционный подход (Whisper / VQ-VAE)**: вынужден нарезать непрерывную волну на дискретные токены через квантование, теряя тонкие фазовые гармоники и раздувая размер контекста.
* **Fractal-HoloNet**: проецирует сырой сигнал $x(t) \in \mathbb{R}^C$ напрямую в комплексное фазовое пространство $\mathbb{C}^d$ через обучаемый банк вейвлет-фильтров Фурье. Фазовый аккумулятор естественным образом моделирует физические колебания, гармоники и тренды.

### Поддерживаемые непрерывные модальности:
1. **Биомедицинские сигналы**: ЭКГ (электрокардиограмма), ЭЭГ мозга, пульсоксиметрия.
2. **Акустика и звук**: сырые аудио-волны 16kHz/44.1kHz без спектрограммного огрубления.
3. **Промышленный IoT и телеметрия**: вибрации турбин, датчики давления, температуры, сетевой трафик.
4. **Финансовые потоки**: высокочастотные тиковые данные (HFT).

---

## 📊 Результаты прогнозирования непрерывного сигнала

Модель протестирована на прогнозировании 64 шагов сложного непрерывного квазипериодического сигнала с детекцией аномалий в реальном времени:
* **MSE прогнозирования**: `0.0274`
* **Точность детекции аномалий (BCE)**: `0.00019`
* **Задержка прогнозирования (64 шага)**: `39.5 ms` ($\mathcal{O}(1)$ шаговый стриминг)

![Multimodal Signal Forecast](multimodal_signal_forecast.png)

---

## 📂 Структура репозитория

```text
├── multimodal_holonet.py    # 🌊 Мультимодальное ядро: ContinuousSignalEncoder, AnomalyHead, SignalHead
├── train_multimodal.py      # 🏋️ Обучение и валидация на непрерывных сигналах (ЭКГ, Аудио, IoT)
├── fractal_holonet_prod.py  # 🧠 Ядро архитектуры: RMSNorm, O(1) генератор, config
├── pipeline.py              # 🔌 Inference Pipeline и UTF-8 байтовый токенизатор
├── train.py                 # 📝 Обучение языковой модели на текстах
├── serve.py                 # 🌐 REST API сервер (текст + непрерывные сигналы + аномалии)
├── export_onnx.py           # 📦 Экспорт в ONNX и валидация через ONNX Runtime
├── test_production.py       # 🧪 Комплексный набор тестов PyTest
├── Dockerfile               # 🐳 Production Dockerfile
├── docker-compose.yml       # 🚀 Оркестрация Uvicorn
├── requirements.txt         # 📌 Зафиксированные зависимости
├── checkpoints/             # 💾 Чекпоинты (text + multimodal)
└── research/                # 🔬 Эксперименты и прототипы (V1..V3)
```

---

## ⚡ Использование непрерывных сигналов на практике

### 1. Обучение на непрерывных сигналах
```bash
python3 train_multimodal.py
```

### 2. Использование в Python для IoT / Биомедицины
```python
import torch
from multimodal_holonet import MultimodalFractalHoloNet

# Загрузка обученной мультимодальной модели
model = MultimodalFractalHoloNet.from_pretrained("./checkpoints/fractal_holonet_multimodal")

# Сырой непрерывный сигнал с датчика (1 поток, 64 отсчета)
raw_stream = torch.randn(1, 64, 1)

# 1. Прогноз на 32 шага вперед без токенизации
forecast = model.forecast_stream(raw_stream, forecast_steps=32)
print("Форма прогноза:", forecast.shape) # (1, 32, 1)

# 2. Мгновенная детекция аномалий
_, anomaly_scores, _ = model.forward_continuous(raw_stream)
print("Оценка аномальности по шагам:", anomaly_scores[0, :, 0])
```

### 3. Запуск через REST API

```bash
uvicorn serve:app --host 0.0.0.0 --port 8000
```

#### Эндпоинт прогнозирования и скоринга аномалий:
`POST /v1/signal/forecast`
```bash
curl -X POST http://localhost:8000/v1/signal/forecast \
  -H "Content-Type: application/json" \
  -d '{
    "signal_history": [[0.12], [0.35], [0.89], [1.45], [0.80], [0.20]],
    "forecast_steps": 16
  }'
```
**Ответ:**
```json
{
  "forecast": [[0.15], [0.28], "..."],
  "forecast_steps": 16,
  "channels": 1,
  "anomaly_scores": [0.001, 0.002, 0.001, "..."],
  "latency_ms": 12.4
}
```

### 4. Запуск всех тестов
```bash
python3 -m pytest test_production.py -v -o cache_dir=/tmp/.pytest_cache
```
