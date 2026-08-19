"""LangGraph-пайплайны вокруг сущностей.

Каждый граф:
  retrieve → reason → (опционально) critique → pack

LLM опциональна: без ключа работает детерминированный fallback,
чтобы сервис был полезен и офлайн.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from specgraph.llm import chat_llm
from specgraph.retrieval.context import context_as_prompt, gather_context


class PipelineState(TypedDict, total=False):
    query: str
    product_id: int | None
    product_code: str | None
    document_id: int | None
    context: dict[str, Any]
    prompt: str
    draft: str
    result: dict[str, Any]


def _llm(slot: str = "expensive"):
    return chat_llm("expensive" if slot == "expensive" else "cheap")


def _retrieve(state: PipelineState, db: Session) -> PipelineState:
    ctx = gather_context(
        db,
        query=state.get("query"),
        product_id=state.get("product_id"),
        product_code=state.get("product_code"),
        document_id=state.get("document_id"),
    )
    return {**state, "context": ctx, "prompt": context_as_prompt(ctx)}


def _reason(system: str, state: PipelineState, *, slot: str = "expensive") -> PipelineState:
    llm = _llm(slot)
    if llm is None:
        return {**state, "draft": _offline_draft(system, state)}
    msg = llm.invoke([SystemMessage(content=system), HumanMessage(content=state.get("prompt") or "")])
    return {**state, "draft": msg.content}


def _offline_draft(system: str, state: PipelineState) -> str:
    ctx = state.get("context") or {}
    reqs = []
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
    app = _compile(entry["system"], db, slot=entry.get("slot") or "expensive")
    out = app.invoke({"query": kwargs.get("query") or entry.get("title") or name, **kwargs})
    result = out["result"]
    result["pipeline"] = name
    result["slot"] = entry.get("slot")
    return result


def validate_requirements(db: Session, **kwargs) -> dict[str, Any]:
    return run_pipeline("validate-requirements", db, **kwargs)


def generate_tests(db: Session, **kwargs) -> dict[str, Any]:
    return run_pipeline("generate-tests", db, **kwargs)


def summarize_context(db: Session, **kwargs) -> dict[str, Any]:
    return run_pipeline("summarize", db, **kwargs)
