Схема создаётся `Base.metadata.create_all` при старте.
Индекс «один текущий base_code» ставит `db._ensure_indexes()`.
Alembic можно подключить позже: `alembic revision --autogenerate`.
