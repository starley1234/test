"""Извлечение текста и иллюстраций из Word.

Два канала:
- python-docx — структура, параграфы, картинки в document.xml / media
- Apache Tika — .doc/.docm, встроенные объекты, OCR-метаданные
"""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from specgraph.config import settings


@dataclass
class ExtractedImage:
    filename: str
    content: bytes
    content_type: str
    caption: str | None = None


@dataclass
class ExtractedDoc:
    title: str | None
    paragraphs: list[str]
    tables: list[list[list[str]]]
    images: list[ExtractedImage] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n".join(self.paragraphs)


def detect_kind(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".docm"):
        return "macro_doc"
    if lower.endswith(".docx"):
        return "docx"
    if lower.endswith(".doc"):
        return "doc"
    if lower.endswith(".json"):
        return "parsed_json"
    return "other"


def extract_docx(path: Path) -> ExtractedDoc:
    from docx import Document as Docx

    doc = Docx(str(path))
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
    tables: list[list[list[str]]] = []
    for table in doc.tables:
        rows = []
        for row in table.rows:
            rows.append([cell.text.strip() for cell in row.cells])
        tables.append(rows)

    images: list[ExtractedImage] = []
    # media из пакета OOXML — картинки, которые теряются при «голом» тексте
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                if name.startswith("word/media/"):
                    data = zf.read(name)
                    ext = Path(name).suffix.lower()
                    ctype = {
                        ".png": "image/png",
                        ".jpg": "image/jpeg",
                        ".jpeg": "image/jpeg",
                        ".emf": "image/x-emf",
                        ".wmf": "image/x-wmf",
                        ".gif": "image/gif",
                    }.get(ext, "application/octet-stream")
                    images.append(ExtractedImage(filename=Path(name).name, content=data, content_type=ctype))

    title = doc.core_properties.title or (paragraphs[0] if paragraphs else path.stem)
    return ExtractedDoc(title=title, paragraphs=paragraphs, tables=tables, images=images)


def extract_tika(path: Path) -> ExtractedDoc:
    """Fallback / дополнение: Tika поднимает .doc, макросы, вложения."""
    import httpx

    url = settings.tika_server_url.rstrip("/")
    data = path.read_bytes()
    headers = {"Accept": "application/json"}
    try:
        r = httpx.put(f"{url}/tika", content=data, headers={"Accept": "text/plain"}, timeout=60)
        r.raise_for_status()
        text = r.text
        meta_r = httpx.put(f"{url}/meta", content=data, headers=headers, timeout=60)
        meta = meta_r.json() if meta_r.status_code == 200 else {}
    except Exception as exc:  # noqa: BLE001
        return ExtractedDoc(title=path.stem, paragraphs=[], tables=[], meta={"tika_error": str(exc)})

    paragraphs = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return ExtractedDoc(title=meta.get("title") or path.stem, paragraphs=paragraphs, tables=[], meta=meta)


def extract_parsed_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def extract_any(path: Path) -> ExtractedDoc:
    kind = detect_kind(path.name)
    if kind in {"docx", "macro_doc"}:
        extracted = extract_docx(path)
        # макросы/OLE — добираем текстом через Tika, картинки уже из zip
        if kind == "macro_doc":
            extra = extract_tika(path)
            if extra.paragraphs and len(extra.paragraphs) > len(extracted.paragraphs):
                extracted.paragraphs = extra.paragraphs
                extracted.meta.update(extra.meta)
        return extracted
    if kind == "doc":
        return extract_tika(path)
    # неизвестное — пробуем tika, иначе как текст
    tika = extract_tika(path)
    if tika.paragraphs:
        return tika
    text = path.read_text(encoding="utf-8", errors="ignore")
    return ExtractedDoc(title=path.stem, paragraphs=[ln.strip() for ln in text.splitlines() if ln.strip()], tables=[])
