"""Улучшенный извлекатель Word (замена input/pars.txt).

Отличия от исходного скрипта:
- сохраняет стиль / уровень заголовка (Heading 1–5);
- не теряет иллюстрации (word/media + rId);
- умные таблицы без дублей merged-ячеек;
- порядок body как в документе;
- Natasha NER опциональна (без неё остаются тех.регексы).
"""

from __future__ import annotations

import re
from io import BytesIO
from typing import Any

from specgraph.ingest.extract import extract_docx

TECH_PATTERNS = {
    "VOLTAGE": r"\b\d+\s*[VВ](?:т)?\b",
    "INTERFACE": r"\b(RS-?\d{3}|Ethernet|USB|HDMI|Wi-Fi|Bluetooth|ARINC-?\d+|CAN|I2C|UART|DMA)\b",
    "IP_CLASS": r"\bIP[0-9]{2}\b",
    "STANDARDS": r"\b(ГОСТ|ISO|IEC|КТ-178[CС]?|DO-178[BC]?)\b",
    "REQ_ID": r"\b[A-Z]{1,12}-\d{1,4}(?:\.[A-Z]{2,8}){1,6}\.\d{3}(?:/[A-Z](?:\.\d{2})?)?\b",
    "MCU": r"\b(MCU[12]|STM32F407\w*|1921ВК028)\b",
}


def _natasha_entities(text: str) -> list[dict[str, str]]:
    try:
        from natasha import Doc, NewsEmbedding, NewsNERTagger, Segmenter
    except ImportError:
        return []
    if not hasattr(_natasha_entities, "_tagger"):
        _natasha_entities._seg = Segmenter()
        emb = NewsEmbedding()
        _natasha_entities._tagger = NewsNERTagger(emb)
    doc = Doc(text)
    doc.segment(_natasha_entities._seg)
    doc.tag_ner(_natasha_entities._tagger)
    return [{"text": span.text, "label": span.type} for span in doc.spans]


def get_entities(text: str) -> list[dict[str, str]]:
    if not text or not text.strip():
        return []
    results = _natasha_entities(text)
    for label, pattern in TECH_PATTERNS.items():
        for m in re.finditer(pattern, text, re.IGNORECASE):
            results.append({"text": m.group(), "label": label})
    return results


def extract_structure_bytes(data: bytes, filename: str = "doc.docx") -> dict[str, Any]:
    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp.write(data)
        path = Path(tmp.name)
    try:
        extracted = extract_docx(path)
    finally:
        path.unlink(missing_ok=True)

    structure: list[dict[str, Any]] = []
    for b in extracted.blocks:
        if b.kind == "table":
            all_text = " ".join(c for row in b.rows for c in row if c)
            structure.append({"type": "table", "content": b.rows, "entities": get_entities(all_text)})
        elif b.kind == "image":
            structure.append(
                {
                    "type": "image",
                    "content": {"filename": b.image.filename if b.image else b.text, "caption": b.image.caption if b.image else None},
                    "entities": [],
                }
            )
        else:
            structure.append(
                {
                    "type": "heading" if b.kind == "heading" else "paragraph",
                    "content": b.text,
                    "heading_level": b.heading_level,
                    "style": b.style,
                    "entities": get_entities(b.text),
                }
            )
    return {"filename": filename, "title": extracted.title, "document_structure": structure}


def build_extractor_app():
    from fastapi import FastAPI, File, HTTPException, UploadFile

    app = FastAPI(title="SpecGraph Word extractor")

    @app.post("/extract")
    async def extract_api(file: UploadFile = File(...)):
        name = file.filename or "doc.docx"
        if not name.lower().endswith((".docm", ".docx")):
            raise HTTPException(status_code=400, detail="Use .docm or .docx")
        data = await file.read()
        try:
            return extract_structure_bytes(data, name)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return app
