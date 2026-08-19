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


def vlm_chat(images: list[tuple[str, bytes]], prompt: str) -> str | None:
    """OpenAI-совместимый vision. images = [(mime, bytes), ...]. None — нет ключа."""
    import base64

    import httpx

    base, key, model = settings.vlm()
    if not key:
        return None
    content: list[dict] = [{"type": "text", "text": prompt}]
    for mime, raw in images[:4]:
        b64 = base64.b64encode(raw).decode("ascii")
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
    url = base.rstrip("/") + "/chat/completions"
    r = httpx.post(
        url,
        headers={"Authorization": f"Bearer {key}"},
        json={"model": model, "temperature": 0.1, "messages": [{"role": "user", "content": content}]},
        timeout=180,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def model_info() -> dict:
    c_base, c_key, c_model = settings.cheap()
    e_base, e_key, e_model = settings.expensive()
    b_base, b_key, b_model = settings.embed()
    v_base, v_key, v_model = settings.vlm()
    return {
        "cheap": {"base_url": c_base, "model": c_model, "configured": bool(c_key)},
        "expensive": {"base_url": e_base, "model": e_model, "configured": bool(e_key)},
        "embed": {"base_url": b_base or "(local sentence-transformers)", "model": b_model, "configured": bool(b_base or True)},
        "vlm": {"base_url": v_base, "model": v_model, "configured": bool(v_key)},
    }
