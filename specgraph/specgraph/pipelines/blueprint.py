"""Статическая схема пайплайна для UI-диаграммы."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from specgraph.pipelines.graphs import _catalog


def blueprint(name: str) -> dict[str, Any]:
    cat = _catalog()
    entry = cat.get(name)
    if not entry or name.startswith("_"):
        raise KeyError(name)
    kind = entry.get("kind") or "graph"
    system = entry.get("system") or ""
    if kind in {"matrix", "matrix-one"}:
        steps = [
            {"id": "in", "title": "Выборка", "detail": "document_id + requirement_ids (галочки)"},
            {"id": "card", "title": "Карточка требования", "detail": "текст, атрибуты, источник, дата загрузки"},
            {"id": "llm", "title": "Оценка А.3", "detail": system, "slot": entry.get("slot")},
            {"id": "out", "title": "Матрица", "detail": "docx / json / md / xlsx"},
        ]
        mermaid = "flowchart LR\n  A[галочки] --> B[карточка] --> C[LLM expensive] --> D[matrix.docx]"
    elif kind == "unit-xlsx":
        steps = [
            {"id": "in", "title": "Требования", "detail": "выбранные id"},
            {"id": "llm", "title": "Кейсы", "detail": Path(__file__).with_name("unit_tests_prompt.txt").read_text(encoding="utf-8")[:2500]},
            {"id": "sim", "title": "Simulation", "detail": "без кода — blocked"},
            {"id": "out", "title": "Excel", "detail": "Info / InputData / OutputData / Comments"},
        ]
        mermaid = "flowchart LR\n  A[требования] --> B[LLM] --> C[xlsx] --> D[Simulation]"
    elif kind == "schematic":
        steps = [
            {"id": "img", "title": "Картинка/PDF", "detail": "VLM читает узлы"},
            {"id": "cover", "title": "Покрытие", "detail": "узлы ↔ текст требований"},
            {"id": "out", "title": "Отчёт md", "detail": "покрыто / нет"},
        ]
        mermaid = "flowchart LR\n  A[схема] --> B[VLM] --> C[узлы] --> D[требования] --> E[md]"
    else:
        steps = [
            {"id": "ret", "title": "retrieve", "detail": "gather_context: документ + галочки → текст для модели"},
            {"id": "llm", "title": "reason", "detail": system, "slot": entry.get("slot")},
            {"id": "pack", "title": "pack", "detail": "output + json/md/xlsx/docx"},
        ]
        mermaid = "flowchart LR\n  A[БД] --> B[retrieve] --> C[reason] --> D[pack]"
    return {
        "name": name,
        "title": entry.get("title") or name,
        "slot": entry.get("slot"),
        "kind": kind,
        "system": system,
        "steps": steps,
        "mermaid": mermaid,
    }
