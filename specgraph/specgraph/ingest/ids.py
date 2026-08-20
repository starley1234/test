"""Универсальные идентификаторы требований / приложений.

Покрывает:
  MK-114.OPPO.DATA.001/B
  MK-SSJ-NEW.HRDW.FNCT.4-20_PSU-1d2V.001/A.03
  MK-SSJ-NEW.SSTM.FNCT.MK-SSJ-NEW.035/A
  MK-SSJ-NEW.HRDW.00001/A   (приложение-файл)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

REQ_ID = re.compile(
    r"(?<![A-Za-z0-9])([A-Z][A-Za-z0-9-]+(?:\.[A-Za-z0-9][A-Za-z0-9_-]*)+(?:/[A-Z](?:\.\d{1,3})?)?)(?![A-Za-z0-9_/])"
)

APPENDIX_ID = re.compile(
    r"""
    (?<![A-Z0-9])
    (
        [A-Z]{1,16}(?:-[A-Z0-9]{1,16}){0,4}
        \.(?:HRDW|SOFT|SSTM|OPPO|TPO|APDX|APP)
        \.\d{3,6}
        (?:/[A-Z](?:\.\d{1,3})?)?
    )
    (?![A-Za-z0-9_/])
    """,
    re.VERBOSE,
)

LAYER_TOKENS = {"HRDW", "SOFT", "SSTM", "OPPO", "TPO", "APDX", "APP", "SYS"}
KIND_TOKENS = {
    "FNCT": "functional",
    "INTF": "interface",
    "FCTR": "performance",
    "TIME": "performance",
    "DATA": "design",
    "HWRQ": "design",
    "SAFE": "safety",
    "REL": "reliability",
}


@dataclass(frozen=True)
class ParsedId:
    raw: str
    base: str
    revision: str | None
    system: str
    layer: str | None
    kind: str | None
    node: str | None


def base_code(code: str) -> str:
    return code.split("/", 1)[0]


def revision_of(code: str) -> str | None:
    return code.split("/", 1)[1] if "/" in code else None


def find_ids(text: str) -> list[str]:
    if not text:
        return []
    found = REQ_ID.findall(text)
    # уникальные, порядок сохранения
    out: list[str] = []
    seen: set[str] = set()
    for c in found:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def find_appendix_ids(text: str) -> list[str]:
    if not text:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for c in APPENDIX_ID.findall(text) + find_ids(text):
        b = base_code(c)
        if re.search(r"\.\d{3,6}$", b) and b not in seen:
            # приложение вида *.HRDW.00001, не FNCT.001 внутри узла
            tail = b.rsplit(".", 1)[-1]
            head = b.rsplit(".", 1)[0]
            if tail.isdigit() and any(f".{tok}" in head for tok in LAYER_TOKENS):
                # отсекаем FNCT.4-20_xxx.001 — tail 001 but previous token has underscore/hyphen mix
                prev = head.rsplit(".", 1)[-1]
                if prev in LAYER_TOKENS:
                    seen.add(b)
                    out.append(c)
    return out


def parse_id(code: str) -> ParsedId:
    rev = revision_of(code)
    base = base_code(code)
    parts = base.split(".")
    system = parts[0] if parts else base
    layer = next((p for p in parts[1:] if p in LAYER_TOKENS), None)
    kind = next((p for p in parts[1:] if p in KIND_TOKENS), None)
    node = None
    if kind:
        try:
            i = parts.index(kind)
            rest = parts[i + 1 :]
            if rest:
                node = rest[0] if not rest[0].isdigit() else (rest[0] if len(rest) == 1 else rest[0])
                # 4-20_PSU-1d2V
                if len(rest) >= 1 and not rest[0].isdigit():
                    node = rest[0]
        except ValueError:
            node = None
    return ParsedId(raw=code, base=base, revision=rev, system=system, layer=layer, kind=kind, node=node)


def kind_from_code(code: str) -> str:
    p = parse_id(code)
    if p.kind and p.kind in KIND_TOKENS:
        return KIND_TOKENS[p.kind]
    return "unknown"


def filename_matches_code(filename: str, code: str) -> bool:
    stem = filename.rsplit(".", 1)[0]
    b = base_code(code)
    return stem.startswith(b) or b in stem or base_code(stem) == b
