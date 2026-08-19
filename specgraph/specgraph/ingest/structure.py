"""Word / JSON генератора → изделия и требования.

Требование = таблица-карточка с подписями в первой колонке
(Идентификатор, Содержание, Обоснование, Источник требования, …).
Код берётся из ячейки, не из маски. Родители — строки поля «Источник требования».
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from specgraph.ingest.extract import Block, ExtractedDoc
from specgraph.ingest.ids import kind_from_code
from specgraph.ingest.profile import card_fields, card_must_have, empty_source, kind_in_code

DEC_CODE = re.compile(r"\b([A-ZА-Я]{2,6}\.\d{5,8}\.\d{2,4}(?:[-.]\d{2})?)\b")
MUST = re.compile(r"(должен|должна|должно|должны|обеспечивать|предусмотреть|не менее|не более|shall)", re.I)
FIGURE = re.compile(r"^(рисунок|рис\.|figure|схема)\s*[\d.IVX]*", re.I)
NUM_HEADING = re.compile(r"^(\d+(?:\.\d+){0,5})\s+(.+)$")
ATTR_LINE = re.compile(r"^([^:]{2,80}):\s*(.+)$")
GLOSS = re.compile(r"^(.{1,80}?)\s+[–—\-]\s+(.{3,})$")
SOURCE = re.compile(r"^\[(\d+)\]\s+(.+)$")
TABLE_CAPTION = re.compile(r"^таблица\s+[\d.]+\s*[–—-]?\s*(.*)$", re.I)
QUOTED = re.compile(r"[«\"“]([^»\"”]{3,240})[»\"”]")

KIND_BY_TOKEN = kind_in_code() or {
    "FNCT": "functional",
    "INTF": "interface",
    "TIME": "performance",
    "DATA": "design",
    "HWRQ": "design",
    "FCTR": "performance",
}

KIND_HINTS = {
    "interface": ("интерфейс", "протокол", "разъём", "разъем", "шина", "arinc", "can", "rs-485"),
    "safety": ("безопасност", "защита", "запрещ"),
    "performance": ("производительн", "быстродейств", "точность", "погрешн", "кГц", "частот"),
    "reliability": ("надёжн", "надежн", "наработк", "отказ"),
    "environment": ("климат", "температур", "влажност", "вибрац"),
    "regulatory": ("гост", "кт-178", "do-178", "норматив"),
    "functional": ("функц", "должен", "режим"),
}

CARD_LABELS = card_fields()


@dataclass
class DraftProduct:
    code: str
    name: str
    parent_code: str | None = None
    level: int = 0
    section_path: str | None = None
    description: str = ""
    attributes: dict[str, str] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


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
    extra: dict[str, Any] = field(default_factory=dict)
    stub: bool = False
    parent_codes: list[str] = field(default_factory=list)
    attachment_refs: list[str] = field(default_factory=list)


@dataclass
class DraftRelation:
    rel_type: str
    src_kind: str
    src_code: str
    dst_kind: str
    dst_code: str


@dataclass
class DraftGraph:
    products: list[DraftProduct] = field(default_factory=list)
    requirements: list[DraftRequirement] = field(default_factory=list)
    relations: list[DraftRelation] = field(default_factory=list)
    figure_captions: list[str] = field(default_factory=list)
    glossary: dict[str, str] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)
    title: str | None = None
    attachment_codes: list[str] = field(default_factory=list)


def _uniq(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for x in items:
        if x and x not in seen and x not in "-–—":
            seen.add(x)
            out.append(x)
    return out


def base_ne(a: str, b: str) -> bool:
    return a.split("/", 1)[0] != b.split("/", 1)[0]


def infer_kind(text: str, code: str = "") -> str:
    if code:
        k = kind_from_code(code)
        if k != "unknown":
            return k
    up = code.upper()
    for token, kind in KIND_BY_TOKEN.items():
        if f".{token}." in up:
            return kind
    low = text.lower()
    for kind, hints in KIND_HINTS.items():
        if any(h in low for h in hints):
            return kind
    return "unknown"


def _revision(code: str) -> str | None:
    return code.split("/", 1)[1] if "/" in code else None


def _looks_id_heading(text: str) -> bool:
    """Генератор ставит код требования заголовком: один токен без пробелов, с точками."""
    t = text.strip()
    return bool(t) and len(t) <= 160 and " " not in t and "." in t


def split_source_refs(text: str) -> list[str]:
    """Поле «Источник требования»: по строкам, как пишет генератор."""
    if not text:
        return []
    out: list[str] = []
    for line in re.split(r"[\n\r;]+", text):
        line = line.strip().strip("«»\"'“”")
        if not line or line.lower() in empty_source() or line in "-–—":
            continue
        out.append(line.split()[0])
    return _uniq(out)


def quoted_refs(text: str) -> list[str]:
    if not text:
        return []
    refs = []
    for m in QUOTED.finditer(text):
        val = m.group(1).strip()
        # приложение генератора: «КОД/ревизия-название», не обычные кавычки в тексте
        if "." in val or "/" in val:
            refs.append(val)
    return _uniq(refs)


class _Builder:
    def __init__(self) -> None:
        self.g = DraftGraph()
        self._products: dict[str, DraftProduct] = {}
        self._reqs: dict[str, DraftRequirement] = {}
        self.section: list[str] = []
        self.current_product: str | None = None
        self.pending_req: str | None = None
        self.last_table_caption: str | None = None
        self.has_cards: bool = False

    def section_path(self) -> str:
        return " / ".join(self.section[-4:])

    def ensure_product(self, code: str, name: str, *, parent: str | None = None, level: int = 0, **kw) -> DraftProduct:
        if code in self._products:
            p = self._products[code]
            if name and len(name) > len(p.name):
                p.name = name
            p.attributes.update(kw.pop("attributes", {}) or {})
            if kw.get("description"):
                p.description = (p.description + "\n" + kw["description"]).strip()
            return p
        p = DraftProduct(code=code, name=name, parent_code=parent, level=level, section_path=self.section_path(), **kw)
        self._products[code] = p
        self.g.products.append(p)
        return p

    def add_req(self, dr: DraftRequirement) -> DraftRequirement:
        if dr.code in self._reqs:
            old = self._reqs[dr.code]
            if dr.text and (not old.text or (not dr.stub and old.stub)):
                old.text = dr.text
                old.stub = False
            old.attributes.update(dr.attributes)
            if dr.product_code and not old.product_code:
                old.product_code = dr.product_code
            old.parent_codes = _uniq(old.parent_codes + dr.parent_codes)
            old.attachment_refs = _uniq(old.attachment_refs + dr.attachment_refs)
            return old
        if not dr.kind or dr.kind == "unknown":
            dr.kind = infer_kind(dr.text, dr.code)
        if not dr.section_path:
            dr.section_path = self.section_path()
        rev = _revision(dr.code)
        if rev:
            dr.attributes.setdefault("ревизия", rev)
            dr.attributes.setdefault("базовый_код", dr.code.split("/", 1)[0])
        self._reqs[dr.code] = dr
        self.g.requirements.append(dr)
        return dr

    def rel(self, rel_type: str, src_kind: str, src: str, dst_kind: str, dst: str) -> None:
        self.g.relations.append(DraftRelation(rel_type, src_kind, src, dst_kind, dst))


def _push_heading(b: _Builder, text: str, level: int) -> None:
    while len(b.section) >= level:
        b.section.pop()
    while len(b.section) < level - 1:
        b.section.append("")
    b.section.append(text)

    if _looks_id_heading(text):
        b.pending_req = text.strip()
        return

    decs = DEC_CODE.findall(text)
    looks_hw = bool(decs) or any(k in text.lower() for k in ("изделие", "блок", "система", "устройство", "состав"))
    if looks_hw and "требован" not in text.lower() and "архитектур" not in text.lower():
        code = decs[0] if decs else f"P-{level}-{re.sub(r'[^0-9A-Za-zА-Яа-я]+', '', text)[:16]}"
        b.ensure_product(code, text.strip(), parent=b.current_product, level=level)
        b.current_product = code

    low = text.lower()
    if "микроконтроллер №1" in low or "1921вк028" in low:
        b.ensure_product("MCU1", "Микроконтроллер №1 (1921ВК028)", parent=b.current_product, level=2)
        b.current_product = "MCU1"
    elif "микроконтроллер №2" in low or "stm32f407" in low:
        b.ensure_product("MCU2", "Микроконтроллер №2 (STM32F407)", parent=b.current_product, level=2)
        b.current_product = "MCU2"
    elif "модул" in low:
        name = re.sub(r"^требования к\s+", "", text, flags=re.I).strip()
        code = _module_code(name)
        b.ensure_product(code, name, parent=b.current_product, level=3)
        b.current_product = code


def _module_code(name: str) -> str:
    file_hint = re.search(r"([a-zA-Z][a-zA-Z0-9_]+)\.(c|h)\b", name)
    if file_hint:
        return f"MOD-{file_hint.group(1)}"
    slug = re.sub(r"[^a-zA-Zа-яА-Я0-9]+", "-", name.lower()).strip("-")
    slug = slug.replace("требования-к-", "").replace("модулю-", "mod-").replace("модуль-", "mod-")
    return ("MOD-" + slug)[:80]


def _looks_req_card(rows: list[list[str]]) -> bool:
    if not rows:
        return False
    labels = [r[0].strip().lower() for r in rows if r and r[0]]
    return "идентификатор" in labels and "содержание" in labels


def _parse_req_card(rows: list[list[str]]) -> dict[str, str]:
    card: dict[str, str] = {}
    extras_row: list[str] = []
    for row in rows:
        if not row:
            continue
        raw_label = (row[0] or "").strip()
        label = CARD_LABELS.get(raw_label.lower())
        values = [c.strip() for c in row[1:] if c and c.strip()]
        if label == "id" and values:
            card["id"] = values[0]
        elif label == "assumption":
            extras_row = [c.strip() for c in row[1:] if c and c.strip()]
            if extras_row:
                card["assumption"] = " ".join(extras_row)
        elif label:
            card[label] = "\n".join(values)
        elif raw_label:
            card[raw_label] = "\n".join(values)
    joined = " ".join(extras_row)
    if re.search(r"производн", joined, re.I):
        card["производное"] = "да" if re.search(r"\bда\b", joined, re.I) else joined
    if re.search(r"функц", joined, re.I):
        card["класс"] = "функция"
    return card


def _parse_module_table(b: _Builder, rows: list[list[str]], parent: str | None) -> None:
    if len(rows) < 2:
        return
    header = [c.lower() for c in rows[0]]
    name_i = 0
    desc_i = 1 if len(header) > 1 else 0
    files_i = next((i for i, h in enumerate(header) if "файл" in h), 2 if len(header) > 2 else None)
    parent = parent or b.current_product
    for row in rows[1:]:
        if not row or not row[0].strip():
            continue
        name = row[name_i].replace("\n", " ").strip()
        desc = row[desc_i].strip() if desc_i < len(row) else ""
        files = row[files_i].replace("\n", ", ").strip() if files_i is not None and files_i < len(row) else ""
        code = _module_code(files.split(",")[0] if files else name)
        attrs = {}
        if files:
            attrs["файлы"] = files
        b.ensure_product(code, name, parent=parent, level=3, description=desc, attributes=attrs)


def _parse_alloc_table(b: _Builder, rows: list[list[str]], parent: str | None) -> None:
    if len(rows) < 2:
        return
    parent = parent or b.current_product
    for row in rows[1:]:
        if len(row) < 2 or not row[0].strip():
            continue
        name = row[0].replace("\n", " ").strip()
        codes = [ln.strip() for ln in (row[1] or "").splitlines() if ln.strip() and ln.strip() not in "-–—"]
        mod = _module_code(name)
        b.ensure_product(mod, name, parent=parent, level=3)
        for code in codes:
            token = code.split()[0]
            b.add_req(
                DraftRequirement(
                    code=token,
                    text=f"Вышестоящее требование {token} (трассировка).",
                    product_code=mod,
                    stub=True,
                )
            )
            b.rel("implements", "product", mod, "requirement", token)


def _parse_generic_attr_table(b: _Builder, rows: list[list[str]]) -> None:
    if len(rows) < 2:
        return
    header = [c.lower() for c in rows[0]]
    if not any(k in " ".join(header) for k in ("параметр", "наименован", "атрибут", "характерист")):
        return
    target = b._products.get(b.current_product) if b.current_product else None
    if not target:
        return
    name_i = next((i for i, h in enumerate(header) if any(k in h for k in ("наим", "парам", "атриб"))), 0)
    val_i = next((i for i, h in enumerate(header) if any(k in h for k in ("значен", "велич"))), 1 if len(header) > 1 else 0)
    for row in rows[1:]:
        if len(row) <= max(name_i, val_i):
            continue
        if row[name_i]:
            target.attributes[row[name_i]] = row[val_i]


def _handle_table(b: _Builder, rows: list[list[str]]) -> None:
    if _looks_req_card(rows):
        card = _parse_req_card(rows)
        code = (card.get("id") or b.pending_req or "").strip()
        if not code:
            return
        text = card.get("text") or ""
        attrs = {k: v for k, v in card.items() if k not in {"id", "text"} and v}
        product = b.current_product
        blob = "\n".join([text, card.get("rationale", ""), card.get("note", ""), card.get("source", "")])
        if re.search(r"MCU2|МК2|микроконтроллера №2", blob, re.I):
            product = "MCU2"
        elif re.search(r"MCU1|МК1|микроконтроллера №1", blob, re.I):
            product = "MCU1"
        parents = [c for c in split_source_refs(card.get("source") or "") if base_ne(c, code)]
        attachments = quoted_refs(blob)
        b.add_req(
            DraftRequirement(
                code=code,
                text=text or f"Требование {code}",
                product_code=product,
                parent_code=parents[0] if parents else None,
                parent_codes=parents,
                attachment_refs=attachments,
                kind=infer_kind(text, code),
                attributes=attrs,
                extra={"card": True},
            )
        )
        if product:
            b.rel("applies_to", "requirement", code, "product", product)
        for pcode in parents:
            b.rel("derived_from", "requirement", code, "requirement", pcode)
        b.has_cards = True
        b.pending_req = None
        return

    header = " ".join(rows[0]).lower() if rows else ""
    cap = (b.last_table_caption or "").lower()
    if "модул" in header or "модул" in cap:
        if "требован" in header or "которые реализуются" in header:
            _parse_alloc_table(b, rows, b.current_product)
        else:
            _parse_module_table(b, rows, b.current_product)
        return
    if "кт-178" in header or "настоящий документ" in header:
        return
    _parse_generic_attr_table(b, rows)


def _handle_paragraph(b: _Builder, text: str) -> None:
    hm = NUM_HEADING.match(text)
    if hm and len(text) < 200:
        _push_heading(b, text, hm.group(1).count(".") + 1)
        return
    if FIGURE.match(text):
        b.g.figure_captions.append(text)
        return
    if TABLE_CAPTION.match(text):
        b.last_table_caption = text
        return
    sm = SOURCE.match(text)
    if sm:
        b.g.sources[sm.group(1)] = sm.group(2).strip()
        return
    if _looks_id_heading(text):
        b.pending_req = text.strip()
        return
    gm = GLOSS.match(text)
    if gm and "термин" in b.section_path().lower():
        b.g.glossary[gm.group(1).strip()] = gm.group(2).strip()
        return
    if gm and len(gm.group(1)) <= 40 and "должен" not in text.lower():
        left = gm.group(1).strip()
        if re.match(r"^[A-ZА-Я0-9][A-ZА-Я0-9/ \-]{0,30}$", left):
            b.g.glossary[left] = gm.group(2).strip()
            return
    am = ATTR_LINE.match(text)
    if am and b.current_product and len(am.group(1)) < 60 and not MUST.search(text):
        target = b._products.get(b.current_product)
        if target:
            target.attributes[am.group(1).strip()] = am.group(2).strip()
            return
    if b.has_cards:
        return
    if MUST.search(text):
        b.add_req(
            DraftRequirement(
                code=f"REQ-{len(b.g.requirements)+1:04d}",
                text=text,
                product_code=b.current_product,
                kind=infer_kind(text),
            )
        )


def from_extracted(doc: ExtractedDoc) -> DraftGraph:
    b = _Builder()
    b.g.title = doc.title
    if doc.title:
        b.ensure_product("DOC", doc.title, level=0)
        b.current_product = "DOC"

    blocks = doc.blocks
    if not blocks:
        blocks = [Block(kind="paragraph", text=p) for p in doc.paragraphs]
        for t in doc.tables:
            blocks.append(Block(kind="table", rows=t))

    for block in blocks:
        if block.kind == "heading" and block.text:
            _push_heading(b, block.text, block.heading_level or 1)
            continue
        if block.kind == "table":
            _handle_table(b, block.rows)
            continue
        if block.kind == "image":
            if block.text:
                b.g.figure_captions.append(block.text)
            continue
        if block.text:
            if block.heading_level and len(block.text) < 90:
                _push_heading(b, block.text, block.heading_level)
            else:
                _handle_paragraph(b, block.text)

    if not b.has_cards and (doc.title or ""):
        code = (doc.title or "").split()[0][:256]
        tables_txt = "\n".join(" | ".join(row) for t in doc.tables for row in t[:30])
        b.add_req(
            DraftRequirement(
                code=code,
                text=((doc.text or "") + "\n" + tables_txt)[:20000],
                product_code=b.current_product,
                extra={"appendix": True},
                attributes={"тип": "приложение"},
            )
        )
        b.g.attachment_codes.append(code)

    if not b.g.products:
        b.ensure_product("P-ROOT", doc.title or "Документ", description=(doc.text or "")[:2000])
    return b.g


def extracted_from_generic_json(payload: dict[str, Any]) -> ExtractedDoc:
    paras: list[str] = []
    for key in ("sections", "paragraphs", "blocks"):
        for s in payload.get(key) or []:
            if isinstance(s, str):
                paras.append(s)
            elif isinstance(s, dict):
                paras.append(str(s.get("text") or s.get("content") or s.get("title") or ""))
    paras = [p for p in paras if p]
    return ExtractedDoc(
        title=payload.get("title"),
        paragraphs=paras,
        tables=[],
        blocks=[Block(kind="paragraph", text=p) for p in paras],
    )


def from_parsed_json(payload: dict[str, Any]) -> DraftGraph:
    if payload.get("document_structure"):
        from specgraph.ingest.extract import extracted_from_script_json

        return from_extracted(extracted_from_script_json(payload))

    products = payload.get("products") or payload.get("items") or payload.get("изделия") or []
    reqs = payload.get("requirements") or payload.get("требования") or []
    if not products and not reqs:
        return from_extracted(extracted_from_generic_json(payload))

    b = _Builder()
    b.g.title = payload.get("title")
    for p in products:
        if not isinstance(p, dict):
            continue
        b.ensure_product(
            str(p.get("code") or p.get("id") or p.get("шифр") or f"P-{len(b.g.products)+1}"),
            str(p.get("name") or p.get("title") or p.get("наименование") or "Изделие"),
            parent=(str(p["parent"]) if p.get("parent") else None) or p.get("parent_code"),
            level=int(p.get("level") or 0),
            description=str(p.get("description") or p.get("text") or ""),
            attributes={str(k): str(v) for k, v in (p.get("attributes") or p.get("attrs") or {}).items()},
        )
    for r in reqs:
        if not isinstance(r, dict):
            continue
        text = str(r.get("text") or r.get("wording") or r.get("формулировка") or "")
        b.add_req(
            DraftRequirement(
                code=str(r.get("code") or r.get("id") or f"REQ-{len(b.g.requirements)+1:04d}"),
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
            b.g.figure_captions.append(fig)
        elif isinstance(fig, dict):
            b.g.figure_captions.append(str(fig.get("caption") or fig.get("title") or ""))
    return b.g
