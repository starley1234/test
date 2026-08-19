"""LangGraph-пайплайны вокруг сущностей.

Каждый граф:
  retrieve → reason → (опционально) critique → pack

LLM опциональна: без ключа работает детерминированный fallback,
чтобы сервис был полезен и офлайн.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from specgraph.llm import invoke_chat
from specgraph.retrieval.context import context_as_prompt, gather_context

_CB: Any = None
_FILTER: dict[str, Any] = {}


class PipelineState(TypedDict, total=False):
    query: str
    product_id: int | None
    product_code: str | None
    document_id: int | None
    requirement_id: int | None
    requirement_ids: list[int] | None
    context: dict[str, Any]
    prompt: str
    draft: str
    result: dict[str, Any]
    tokens: dict[str, int]


def _notify(_state: PipelineState, ev: dict[str, Any]) -> None:
    if _CB:
        _CB(ev)


def _retrieve(state: PipelineState, db: Session) -> PipelineState:
    _notify(state, {"event": "retrieve", "step": "чтение графа / контекста"})
    filt = _FILTER or {}
    ids = state.get("requirement_ids") or filt.get("requirement_ids")
    ctx = gather_context(
        db,
        query=state.get("query") or filt.get("query"),
        product_id=state.get("product_id") or filt.get("product_id"),
        product_code=state.get("product_code") or filt.get("product_code"),
        document_id=state.get("document_id") or filt.get("document_id"),
        requirement_id=state.get("requirement_id") or filt.get("requirement_id"),
        requirement_ids=ids,
    )
    return {**state, "context": ctx, "prompt": context_as_prompt(ctx)}


def _reason(system: str, state: PipelineState, *, slot: str = "expensive") -> PipelineState:
    _notify(state, {"event": "llm", "step": f"запрос модели ({slot})"})
    text, usage = invoke_chat(slot if slot in ("cheap", "expensive") else "expensive", system, state.get("prompt") or "")
    if usage.get("offline") or not text:
        draft = _offline_draft(system, state)
        _notify(state, {"event": "llm_done", "step": "офлайн-эвристика", "tokens": usage, "mode": "heuristic"})
        return {**state, "draft": draft, "tokens": usage}
    _notify(state, {"event": "llm_done", "step": "ответ модели", "tokens": usage, "mode": "llm"})
    return {**state, "draft": text, "tokens": usage}


def _offline_draft(system: str, state: PipelineState) -> str:
    ctx = state.get("context") or {}
    reqs = list(ctx.get("requirements") or [])
    for sg in ctx.get("subgraphs", []):
        reqs.extend(sg.get("requirements", []))
    if "тест" in system.lower() or "test" in system.lower():
        lines = ["# Тесты (эвристика без LLM)"]
        for r in reqs:
            lines.append(f"- TC-{r['code']}: проверить «{r['text'][:180]}»")
            attrs = r.get("attributes") or {}
            if attrs:
                lines.append(f"  данные: {attrs}")
        if not reqs:
            lines.append("Требования не найдены — уточните изделие или запрос.")
        return "\n".join(lines)
    # validation
    issues = []
    for r in reqs:
        text = r["text"]
        if len(text) < 20:
            issues.append(f"{r['code']}: слишком короткое требование")
        if not any(w in text.lower() for w in ("должен", "shall", "обеспеч", "не менее", "не более")):
            issues.append(f"{r['code']}: нет модальности (должен/shall)")
        if r["kind"] == "unknown":
            issues.append(f"{r['code']}: не классифицирован тип")
    ok = "проблем не найдено" if not issues else "\n".join(f"- {i}" for i in issues)
    return f"# Проверка требований\nНайдено требований: {len(reqs)}\n{ok}"


def _pack(state: PipelineState) -> PipelineState:
    return {
        **state,
        "result": {
            "output": state.get("draft"),
            "context_summary": {
                "subgraphs": len((state.get("context") or {}).get("subgraphs") or []),
                "hits": len((state.get("context") or {}).get("hits") or []),
            },
        },
    }


def _compile(system: str, db: Session, *, slot: str = "expensive"):
    g = StateGraph(PipelineState)

    def retrieve(s: PipelineState) -> PipelineState:
        return _retrieve(s, db)

    def reason(s: PipelineState) -> PipelineState:
        return _reason(system, s, slot=slot)

    g.add_node("retrieve", retrieve)
    g.add_node("reason", reason)
    g.add_node("pack", _pack)
    g.add_edge(START, "retrieve")
    g.add_edge("retrieve", "reason")
    g.add_edge("reason", "pack")
    g.add_edge("pack", END)
    return g.compile()


def _catalog() -> dict:
    import json
    from pathlib import Path

    path = Path(__file__).with_name("catalog.json")
    return json.loads(path.read_text(encoding="utf-8"))


def run_pipeline(name: str, db: Session, **kwargs) -> dict[str, Any]:
    entry = _catalog().get(name)
    if not entry or name.startswith("_"):
        raise KeyError(name)
    if entry.get("kind") == "matrix" or name == "review-correctness":
        from specgraph.pipelines.correctness import run_correctness_matrix

        return run_correctness_matrix(db, **kwargs)
    if entry.get("kind") == "unit-xlsx" or name == "unit-tests":
        from specgraph.pipelines.unit_tests import run_unit_tests

        return run_unit_tests(db, **kwargs)
    if entry.get("kind") == "schematic" or name == "schematic-coverage":
        from specgraph.pipelines.schematic import run_schematic_coverage

        return run_schematic_coverage(db, **kwargs)
    if name == "review-one":
        from specgraph.pipelines.correctness import run_correctness_matrix

        ids = list(kwargs.get("requirement_ids") or [])
        if kwargs.get("requirement_id"):
            ids = [kwargs["requirement_id"]]
        if not ids:
            raise ValueError("выберите одно требование")
        return run_correctness_matrix(
            db,
            document_id=kwargs.get("document_id"),
            requirement_ids=ids[:1],
            on_progress=kwargs.get("on_progress"),
        )
    app = _compile(entry["system"], db, slot=entry.get("slot") or "expensive")
    global _CB, _FILTER
    payload = {k: v for k, v in kwargs.items() if k != "on_progress"}
    _CB = kwargs.get("on_progress")
    _FILTER = {
        "document_id": payload.get("document_id"),
        "requirement_ids": payload.get("requirement_ids"),
        "requirement_id": payload.get("requirement_id"),
        "product_id": payload.get("product_id"),
        "query": payload.get("query"),
    }
    try:
        out = app.invoke({"query": kwargs.get("query") or entry.get("title") or name, **payload})
    finally:
        _CB = None
        _FILTER = {}
    result = out["result"]
    result["pipeline"] = name
    result["slot"] = entry.get("slot")
    from specgraph.pipelines.exports import write_text_bundle

    result["downloads"] = write_text_bundle(name, result, title=entry.get("title") or name)
    return result


def validate_requirements(db: Session, **kwargs) -> dict[str, Any]:
    return run_pipeline("validate-requirements", db, **kwargs)


def generate_tests(db: Session, **kwargs) -> dict[str, Any]:
    return run_pipeline("generate-tests", db, **kwargs)


def summarize_context(db: Session, **kwargs) -> dict[str, Any]:
    return run_pipeline("summarize", db, **kwargs)
