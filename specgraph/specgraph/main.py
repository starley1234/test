from contextlib import asynccontextmanager

from fastapi import FastAPI

from fastapi.staticfiles import StaticFiles

from specgraph.api.routes import STATIC, router
from specgraph.db import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="SpecGraph",
    description="Загрузка Word/JSON спецификаций → граф изделий и требований → контекст для LLM-пайплайнов",
    lifespan=lifespan,
)
app.include_router(router)
if STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.get("/health")
def health():
    return {"ok": True}
