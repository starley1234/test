"""Нарезка сырого текста. Сам файл в documents.raw_text не меняем."""

from __future__ import annotations

from specgraph.config import settings


def split_text(text: str, *, size: int | None = None, overlap: int | None = None) -> list[tuple[int, int, str]]:
    body = text or ""
    size = size or settings.chunk_chars
    overlap = overlap or settings.chunk_overlap
    if not body.strip():
        return []
    if len(body) <= size:
        return [(0, len(body), body)]
    out: list[tuple[int, int, str]] = []
    i = 0
    n = len(body)
    while i < n:
        end = min(n, i + size)
        if end < n:
            cut = body.rfind("\n", i + size // 2, end)
            if cut > i:
                end = cut + 1
        piece = body[i:end].strip()
        if piece:
            out.append((i, end, piece))
        if end >= n:
            break
        i = max(end - overlap, i + 1)
    return out
