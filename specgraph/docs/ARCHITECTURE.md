# Архитектура SpecGraph

Кратко для программиста, который открыл репозиторий впервые.

## Зачем сервис

1. Разобрать Word/Excel/JSON спецификацию в **граф** (изделия + требования + связи).
2. Отдать этот граф **пайплайнам** (проверка, тесты, резюме) и **внешним системам** (HTTP, MCP).

Граф — изделия + требования + связи. Сырые файлы без карточек — чанки `document_chunks` (двойник `documents.raw_text` не режем). Картинки — `illustrations` + `GET /illustrations/{id}`.

Маленькое окно модели: `gather_context` → `pack_budget` (`CONTEXT_BUDGET_CHARS`, по умолчанию 10k символов). Слои: seed-требование → родители/stub → чанки упомянутых файлов → подписи схем → остальные требования. VLM читает байты схемы отдельно, текст окна не раздуваем.

## Слои (модульный монолит)

```
UI  /  и /app          FastAPI routes          pipelines / ingest
     │                      │                         │
     └──────── HTTP ────────┴──── SQLAlchemy ─────────┴── SQLite/Postgres
                                      │
                                 retrieval + LLM
```

| Каталог | Роль |
|---|---|
| `specgraph/main.py` | FastAPI app, lifespan → `init_db()` |
| `specgraph/api/` | HTTP: индекс, сущности, прогоны, auth, MCP |
| `specgraph/ingest/` | Word/Tika → черновик → строки БД |
| `specgraph/models.py` | Таблицы: documents, products, requirements, RBAC, index_batches |
| `specgraph/pipelines/` | Каталог JSON + LangGraph / матрица / xlsx / схема |
| `specgraph/retrieval/` | Контекст для LLM + эмбеддинги |
| `specgraph/auth.py` | Koseven: users / roles / roles_users / user_tokens |
| `specgraph/mcp_server.py` | JSON-RPC для внешних агентов |
| `specgraph/static/` | `index.html` — полный UI; `app.html` — конструктор |

Код пайплайна **не** обязателен для нового сценария: чаще достаточно `pipelines/catalog.json`.

## Поток данных

```
файлы → POST /index (NDJSON)
      → ingest_file → persist_graph → IndexBatch
      → requirements / products / attachments

кнопка пайплайна → POST /pipelines/runs/{name}
      → jobs.start_job (поток + таблица pipeline_runs)
      → gather_context(document_id, requirement_ids)  # лимит MAX_REQS_PER_RUN
      → LLM или честная эвристика (поле mode)
      → оценки на карточке (requirement_reviews) / черновик формулировки
      → exports (json, md, xlsx, docx)
```

Гость может индексировать и смотреть. Wipe — только роль `admin`.
Залогиненный без роли `pipeline` не запускает пайплайны; гость — может.

## Два UI

| URL | Для кого |
|---|---|
| `/` и `/app` | Конструктор |
| `/dev` | Полный UI для разработчика |

Черновики правок — таблица `requirement_drafts`. Текст из файла не меняем.

Оба ходят в те же API. Ломать `/` нельзя.

## Внешним системам

- `POST /retrieval/context` — JSON подграфа
- `POST /mcp` — MCP tools: `gather_context`, `search_requirements`, `list_products`, `get_product`
- stdio: `python -m specgraph.mcp_server`

## Где править без Python

- Поля карточки Word: `specgraph/profiles/default.json`
- Новый текстовый пайплайн: `specgraph/pipelines/catalog.json`
- Модели: `.env` (`CHEAP_*`, `EXPENSIVE_*`, `EMBED_*`, `VLM_*`)
