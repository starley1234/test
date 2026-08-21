"""Точка входа FastAPI.

UI: GET / — полный интерфейс, GET /app — конструктор.
БД поднимается в lifespan → init_db().
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from specgraph.api.auth_routes import router as auth_router
from specgraph.api.routes import STATIC, router
from specgraph.api.rag_routes import router as rag_router
from specgraph.db import init_db

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="SpecGraph",
    description="Загрузка Word/JSON → граф изделий и требований. MCP: POST /mcp",
    lifespan=lifespan,
)
app.include_router(auth_router)
app.include_router(router)
app.include_router(rag_router)
if STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.get("/health")
def health():
    from specgraph.llm import model_info

    return {"ok": True, "models": model_info()}
