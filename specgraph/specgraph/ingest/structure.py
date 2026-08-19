"""Эвристики: плоский текст/JSON Word-скрипта → изделия и требования.

Типичные маркеры в ТЗ/ТУ/спецификациях:
- заголовки «1.2 Изделие …», «Состав изделия», коды вида АБВГ.123456.001
- требования: «должен», «обеспечивать», «не менее», нумерация 4.1.2
- таблицы атрибутов: параметр | значение | единица
- подписи рисунков: «Рисунок 3 — …»
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from specgraph.ingest.extract import ExtractedDoc

DEC_CODE = re.compile(r"\b([A-ZА-Я]{2,6}\.\d{5,8}\.\d{2,4}(?:[-.]\d{2})?)\b")
REQ_CODE = re.compile(r"\b((?:REQ|ТР|Треб)[-–]?\d+(?:\.\d+)*)\b", re.I)
HEADING = re.compile(r"^(\d+(?:\.\d+){0,5})\s+(.+)$")
MUST = re.compile(r"(должен|должна|должно|должны|обеспечивать|предусмотреть|не менее|не более)", re.I)
FIGURE = re.compile(r"^(рисунок|рис\.|figure)\s*[\d.]+", re.I)
ATTR_LINE = re.compile(r"^([^:]{2,80}):\s*(.+)$")

KIND_HINTS = {
    "interface": ("интерфейс", "протокол", "разъём", "разъем", "шина"),
    "safety": ("безопасност", "защита", "запрещ"),
    "performance": ("производительн", "быстродейств", "точность", "погрешн"),
    "reliability": ("надёжн", "надежн", "наработк", "отказ"),
    "environment": ("климат", "температур", "влажност", "вибрац"),
    "regulatory": ("гост", "ост", "нжд", "норматив"),
    "functional": ("функц", "должен", "режим"),
}


@dataclass
class DraftProduct:
    code: str
    name: str
    parent_code: str | None = None
    level: int = 0
    section_path: str | None = None
    description: str = ""
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass
class DraftRequirement:
    code: str
    text: str
    title: str | None = None
    product_code: str | None = None
    parent_code: str | None = None
    kind: str = "unknown"
    section_path: str | None = None
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass
class DraftGraph:
    products: list[DraftProduct] = field(default_factory=list)
    requirements: list[DraftRequirement] = field(default_factory=list)
    figure_captions: list[str] = field(default_factory=list)


def infer_kind(text: str) -> str:
    low = text.lower()
    for kind, hints in KIND_HINTS.items():
        if any(h in low for h in hints):
            return kind
    return "unknown"


def from_extracted(doc: ExtractedDoc) -> DraftGraph:
    graph = DraftGraph()
    current_section = ""
    current_product: DraftProduct | None = None
    heading_stack: list[tuple[int, str]] = []
    req_seq = 0

    for para in doc.paragraphs:
        if FIGURE.match(para):
            graph.figure_captions.append(para)
            continue

        hm = HEADING.match(para)
        if hm:
            num, title = hm.group(1), hm.group(2).strip()
            current_section = f"{num} {title}"
            depth = num.count(".")
            heading_stack = [(d, t) for d, t in heading_stack if d < depth]
            heading_stack.append((depth, current_section))

            codes = DEC_CODE.findall(para)
            looks_product = bool(codes) or any(
                k in title.lower() for k in ("изделие", "блок", "модуль", "система", "устройство", "состав")
            )
            if looks_product:
                code = codes[0] if codes else f"P-{num}"
                parent = current_product.code if current_product and depth > (current_product.level) else None
                if heading_stack and depth > 0:
                    # родитель — предыдущий заголовок меньшего уровня, если он изделие
                    for p in reversed(graph.products):
                        if p.level < depth:
                            parent = p.code
                            break
                current_product = DraftProduct(
                    code=code,
                    name=title,
                    parent_code=parent,
                    level=depth,
                    section_path=current_section,
                    description=para,
                )
                graph.products.append(current_product)
            continue

        am = ATTR_LINE.match(para)
        if am and current_product and len(am.group(1)) < 60:
            current_product.attributes[am.group(1).strip()] = am.group(2).strip()
            continue

        is_req = bool(REQ_CODE.search(para) or MUST.search(para))
        if is_req:
            req_seq += 1
            codes = REQ_CODE.findall(para)
            code = codes[0] if codes else f"REQ-{req_seq:04d}"
            parent_req = None
            if "." in code:
                parent_req = code.rsplit(".", 1)[0]
            graph.requirements.append(
                DraftRequirement(
                    code=code,
                    text=para,
                    product_code=current_product.code if current_product else None,
                    parent_code=parent_req,
                    kind=infer_kind(para),
                    section_path=current_section,
                )
            )
        elif current_product:
            current_product.description = (current_product.description + "\n" + para).strip()

    # таблицы: первая строка — заголовки, дальше атрибуты или требования
    for table in doc.tables:
        _ingest_table(table, graph, current_product)

    if not graph.products:
        graph.products.append(DraftProduct(code="P-ROOT", name=doc.title or "Документ", description=doc.text[:2000]))

    return graph


def _ingest_table(table: list[list[str]], graph: DraftGraph, current: DraftProduct | None) -> None:
    if not table:
        return
    header = [c.lower() for c in table[0]]
    joined = " ".join(header)
    if any(k in joined for k in ("параметр", "наименован", "атрибут", "характерист")):
        name_i = next((i for i, h in enumerate(header) if any(k in h for k in ("наим", "парам", "атриб"))), 0)
        val_i = next((i for i, h in enumerate(header) if any(k in h for k in ("значен", "велич"))), 1 if len(header) > 1 else 0)
        unit_i = next((i for i, h in enumerate(header) if "единиц" in h), None)
        target = current or (graph.products[-1] if graph.products else None)
        if not target:
            return
        for row in table[1:]:
            if len(row) <= max(name_i, val_i):
                continue
            key, val = row[name_i], row[val_i]
            if unit_i is not None and unit_i < len(row) and row[unit_i]:
                val = f"{val} {row[unit_i]}"
            if key:
                target.attributes[key] = val
        return
    if any(k in joined for k in ("требован", "должен")):
        for i, row in enumerate(table[1:], start=1):
            text = " — ".join(c for c in row if c)
            if not text:
                continue
            graph.requirements.append(
                DraftRequirement(
                    code=f"REQ-T{len(graph.requirements)+1:04d}",
                    text=text,
                    product_code=current.code if current else None,
                    kind=infer_kind(text),
                )
            )


def from_parsed_json(payload: dict[str, Any]) -> DraftGraph:
    """Адаптер под типичный JSON скрипта обработки Word.

    Ожидаемые (гибкие) ключи:
    - products / items / изделия
    - requirements / требования
    - sections / paragraphs
    """
    graph = DraftGraph()

    products = payload.get("products") or payload.get("items") or payload.get("изделия") or []
    reqs = payload.get("requirements") or payload.get("требования") or []
    sections = payload.get("sections") or payload.get("paragraphs") or payload.get("blocks") or []

    if not products and not reqs and sections:
        # скрипт отдал линейную структуру — прогоняем как текст
        paras: list[str] = []
        for s in sections:
            if isinstance(s, str):
                paras.append(s)
            elif isinstance(s, dict):
                paras.append(s.get("text") or s.get("content") or s.get("title") or "")
        from specgraph.ingest.extract import ExtractedDoc

        return from_extracted(ExtractedDoc(title=payload.get("title"), paragraphs=[p for p in paras if p], tables=[]))

    for p in products:
        if not isinstance(p, dict):
            continue
        graph.products.append(
            DraftProduct(
                code=str(p.get("code") or p.get("id") or p.get("шифр") or f"P-{len(graph.products)+1}"),
                name=str(p.get("name") or p.get("title") or p.get("наименование") or "Изделие"),
                parent_code=(str(p["parent"]) if p.get("parent") else None) or p.get("parent_code"),
                level=int(p.get("level") or 0),
                section_path=p.get("section") or p.get("path"),
                description=str(p.get("description") or p.get("text") or ""),
                attributes={str(k): str(v) for k, v in (p.get("attributes") or p.get("attrs") or {}).items()},
            )
        )

    for r in reqs:
        if not isinstance(r, dict):
            continue
        text = str(r.get("text") or r.get("wording") or r.get("формулировка") or "")
        graph.requirements.append(
            DraftRequirement(
                code=str(r.get("code") or r.get("id") or f"REQ-{len(graph.requirements)+1:04d}"),
                text=text,
                title=r.get("title") or r.get("name"),
                product_code=r.get("product") or r.get("product_code") or r.get("изделие"),
                parent_code=r.get("parent") or r.get("parent_code"),
                kind=str(r.get("kind") or r.get("type") or infer_kind(text)),
                section_path=r.get("section"),
                attributes={str(k): str(v) for k, v in (r.get("attributes") or {}).items()},
            )
        )

    for fig in payload.get("figures") or payload.get("illustrations") or []:
        if isinstance(fig, str):
            graph.figure_captions.append(fig)
        elif isinstance(fig, dict):
            graph.figure_captions.append(str(fig.get("caption") or fig.get("title") or ""))

    if not graph.products:
        graph.products.append(DraftProduct(code="P-ROOT", name=str(payload.get("title") or "Документ")))
    return graph
