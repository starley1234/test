from typing import Any

from pydantic import BaseModel, Field


class IngestJsonRequest(BaseModel):
    filename: str = "inline.json"
    payload: dict[str, Any]


class RetrievalRequest(BaseModel):
    query: str | None = None
    product_id: int | None = None
    product_code: str | None = None
    requirement_id: int | None = None
    document_id: int | None = None
    top_k: int = 8
    hop: int = 2


class PipelineRequest(RetrievalRequest):
    query: str | None = Field(default=None)
    source_code: str | None = Field(default=None, description="Исходник модуля (если есть). Без него прогон не выполняется.")
    requirement_ids: list[int] | None = Field(default=None, description="Галочки: только эти требования")


class DocumentOut(BaseModel):
    id: int
    filename: str
    kind: str
    title: str | None
    status: str

    model_config = {"from_attributes": True}


class ProductOut(BaseModel):
    id: int
    code: str
    name: str
    parent_id: int | None
    level: int
    attributes: dict[str, str] = {}

    model_config = {"from_attributes": True}
