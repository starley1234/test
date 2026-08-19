# SpecGraph

Модульный монолит для загрузки Word-спецификаций (обычный `.docx` и документы со скриптами/макросами), извлечения связанных сущностей и выдачи контекста LLM-пайплайнам.

## Зачем

Типовой выход парсера Word — плоский текст/JSON без картинок и без явной модели «изделие ↔ требование».  
SpecGraph:

1. принимает документ;
2. извлекает текст и иллюстрации (Apache Tika + python-docx);
3. строит иерархию **изделий** и **требований**;
4. кладёт связи в реляционную БД + векторный индекс;
5. отдаёт пайплайнам связку сущностей + семантический поиск.

Пайплайны (LangGraph) живут рядом с сущностями: проверка корректности требований, генерация тестов по изделию и т.д.

## Сущности

| Сущность | Смысл |
|---|---|
| `Document` | Исходный Word / извлечённый JSON |
| `Product` | Изделие / сборочная единица / деталь. Дерево `parent_id` |
| `ProductAttribute` | Код, масса, интерфейс, материал, версия… |
| `Requirement` | Требование (функциональное, интерфейсное, НТД…). Дерево `parent_id` |
| `RequirementAttribute` | Приоритет, верификация, статус, источник… |
| `Illustration` | Рисунок из документа (байты + подпись + эмбеддинг подписи) |
| `EntityRelation` | Типизированные рёбра: `applies_to`, `composed_of`, `refines`, `depends_on`, `illustrated_by` |

## Стек

- FastAPI, SQLAlchemy 2, Alembic-совместимые модели
- PostgreSQL + pgvector (в dev — SQLite + локальный векторный индекс)
- LangChain, LangGraph
- Apache Tika (контейнер) + python-docx
- sentence-transformers для эмбеддингов

## Запуск

```bash
cd specgraph
docker compose up -d db tika
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
uvicorn specgraph.main:app --reload --host 0.0.0.0 --port 8000
```

API: `http://localhost:8000/docs`

## Пайплайны

- `POST /pipelines/validate-requirements` — проверка полноты/противоречий
- `POST /pipelines/generate-tests` — тесты по требованиям и атрибутам изделия
- `POST /retrieval/context` — граф + семантика для произвольного вопроса
