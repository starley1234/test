"""Читает profiles/default.json — подписи карточки без правки кода."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

PROFILE_PATH = Path(__file__).resolve().parent.parent / "profiles" / "default.json"


@lru_cache(maxsize=1)
def load_profile() -> dict[str, Any]:
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def card_fields() -> dict[str, str]:
    return {k.lower(): v for k, v in (load_profile().get("card_fields") or {}).items() if not k.startswith("_")}


def card_must_have() -> list[str]:
    return [x.lower() for x in load_profile().get("card_must_have") or ["идентификатор", "содержание"]]


def empty_source() -> set[str]:
    return set(load_profile().get("empty_source") or ["-"])


def kind_in_code() -> dict[str, str]:
    return load_profile().get("kind_in_code") or {}
