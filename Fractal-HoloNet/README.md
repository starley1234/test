# Fractal-HoloNet: Production-Grade AI Inference & Deployment

**Fractal-HoloNet** (*Fractal Gated Holographic Resonance Network*) — современная архитектура искусственного интеллекта нового поколения с линейной вычислительной сложностью $\mathcal{O}(N)$ и константной памятью инференса $\mathcal{O}(1)$.

Репозиторий полностью подготовлен к промышленной эксплуатации (Production-ready): включает модульный движок модели, streaming-генерацию, REST API на FastAPI, экспорт в ONNX / TensorRT, Docker контейнеризацию и интеграционные тесты.

---

## 🚀 1. Структура продакшен-стека

| Файл / Каталог | Назначение |
| :--- | :--- |
| `train.py` | Модуль обучения и дообучения (Fine-tuning / Pre-training) на текстовых корпусах (`FractalHoloNetTrainer`). |
| `fractal_holonet_prod.py` | Продакшен-реализация архитектуры: `ProductionFractalHoloNet`, `FractalHoloNetConfig`, streaming inference $\mathcal{O}(1)$, checkpoints I/O. |
| `pipeline.py` | Высокоуровневый Inference Pipeline (`FractalHoloNetInferencePipeline`) и токенизатор. |
| `serve.py` | Высокопроизводительный REST API сервер на **FastAPI / Uvicorn** с эндпоинтами генерации, эмбеддингов и health-check. |
| `export_onnx.py` | Экспорт модели в **ONNX** с валидацией графа и проверкой исполнения через **ONNX Runtime**. |
| `test_production.py` | Модульные и сквозные интеграционные тесты (**PyTest** + `TestClient`). |
| `Dockerfile` & `docker-compose.yml` | Продакшен-контейнеризация с multi-worker Uvicorn и healthcheck. |
| `requirements.txt` | Зафиксированные зависимости для продакшен-окружения. |

---

## ⚡ 2. Быстрый запуск API сервера

### Локально:
```bash
# Установка зависимостей
pip install -r requirements.txt

# Запуск сервера на порту 8000
uvicorn serve:app --host 0.0.0.0 --port 8000 --workers 2
```

### В Docker / Docker Compose:
```bash
docker-compose up -d --build
```

---

## 📡 3. REST API Эндпоинты

### 1. Проверка работоспособности (Healthcheck)
`GET /health`
```json
{
  "status": "healthy",
  "service": "Fractal-HoloNet Inference Service",
  "timestamp": 1723937320.12
}
```

### 2. Информация об архитектуре
`GET /info`
```json
{
  "architecture": "Fractal Gated Holographic Resonance Network (Fractal-HoloNet)",
  "config": {
    "vocab_size": 300,
    "d_model": 128,
    "n_layers": 4,
    "d_ff": 384
  },
  "device": "cpu",
  "status": "ready"
}
```

### 3. Авторегрессионная генерация текста
`POST /v1/generate`
```json
{
  "prompt": "Neural architecture search",
  "max_tokens": 64,
  "temperature": 0.8,
  "top_k": 40,
  "top_p": 0.9
}
```
**Ответ:**
```json
{
  "prompt": "Neural architecture search",
  "generated_text": "...",
  "full_text": "...",
  "prompt_tokens": 27,
  "generated_tokens": 64,
  "latency_ms": 14.82
}
```

### 4. Извлечение векторных эмбеддингов
`POST /v1/embeddings`
```json
{
  "text": "Fractal resonance state"
}
```
**Ответ:**
```json
{
  "embedding": [0.0142, -0.0512, 0.0891, "..."],
  "dimension": 128
}
```

---

## 📦 4. Экспорт и запуск в ONNX Runtime

Для аппаратного ускорения на серверах и edge-устройствах модель экспортируется в ONNX:
```bash
python3 export_onnx.py
```
Файл модели сохраняется в `exports/fractal_holonet.onnx` и верифицируется через `onnx.checker` и `onnxruntime`.

---

## 🧪 5. Тестирование

Запуск полного набора модульных и интеграционных тестов:
```bash
python3 -m pytest test_production.py -v
```
Все тесты (проход прямого распространения, потоковая генерация, pipeline и все HTTP эндпоинты API) успешно проходят.
