"""Клиенты трёх моделей из .env (OpenAI-совместимый API)."""

from __future__ import annotations

from typing import Literal

from specgraph.config import settings

Slot = Literal["cheap", "expensive"]


def chat_llm(slot: Slot = "cheap"):
    """LangChain ChatOpenAI или None, если нет ключа."""
    if slot == "expensive":
        base, key, model = settings.expensive()
    else:
        base, key, model = settings.cheap()
    if not key:
        return None
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model,
        api_key=key,
        base_url=base or None,
        temperature=0.1,
    )


def model_info() -> dict:
    c_base, c_key, c_model = settings.cheap()
    e_base, e_key, e_model = settings.expensive()
    b_base, b_key, b_model = settings.embed()
    return {
        "cheap": {"base_url": c_base, "model": c_model, "configured": bool(c_key)},
        "expensive": {"base_url": e_base, "model": e_model, "configured": bool(e_key)},
        "embed": {"base_url": b_base or "(local sentence-transformers)", "model": b_model, "configured": bool(b_base or True)},
    }
