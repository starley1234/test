"""Принципиальная схема (картинка/PDF) → узлы ФС → покрытие требованиями."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from specgraph.config import settings
from specgraph.llm import vlm_chat
from specgraph.models import Product, Requirement

EXPORTS = Path(settings.upload_dir).resolve().parent / "exports"
PROMPT = Path(__file__).with_name("schematic_prompt.txt")


def load_pages(path: Path) -> list[tuple[str, bytes]]:
    suf = path.suffix.lower()
    data = path.read_bytes()
    if suf in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        mime = "image/jpeg" if suf in {".jpg", ".jpeg"} else f"image/{suf.lstrip('.')}"
        return [(mime, data)]
    if suf == ".pdf":
        return _pdf_pages(path, data)
    raise ValueError(f"нужна картинка или PDF, а не {suf or 'без расширения'}")


def _pdf_pages(path: Path, data: bytes) -> list[tuple[str, bytes]]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValueError("для PDF нужен пакет pypdf") from exc
    reader = PdfReader(path)
    out: list[tuple[str, bytes]] = []
    for page in reader.pages[:6]:
        if getattr(page, "images", None):
            for img in page.images:
                raw = img.data
                name = (img.name or "x.png").lower()
                mime = "image/jpeg" if name.endswith((".jpg", ".jpeg")) else "image/png"
                out.append((mime, raw))
    if out:
        return out[:4]
    raise ValueError("в PDF нет встроенных картинок — сохраните страницу как PNG")


def _parse_json(raw: str) -> dict[str, Any]:
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return {}
    return json.loads(m.group(0))


def _heuristic_scheme(db: Session, document_id: int | None) -> dict[str, Any]:
    q = db.query(Product)
    if document_id:
        q = q.filter(Product.document_id == document_id)
    prods = q.all()
    nodes = []
    for p in prods:
        if p.code in {"DOC", "P-ROOT"}:
            continue
        nodes.append({"id": p.code, "name": p.name, "kind": "block", "from": "product"})
    return {"title": "Функциональная схема (по изделиям в БД — VLM не настроен)", "nodes": nodes, "edges": [], "mode": "heuristic"}


def analyze_scheme(images: list[tuple[str, bytes]], db: Session, document_id: int | None) -> dict[str, Any]:
    prompt = PROMPT.read_text(encoding="utf-8") if PROMPT.exists() else "Верни JSON узлов схемы."
    raw = None
    try:
        raw = vlm_chat(images, prompt)
    except Exception as exc:  # noqa: BLE001
        raw = None
        err = str(exc)
    else:
        err = None
    if raw:
        data = _parse_json(raw)
        nodes = data.get("nodes") or []
        if nodes:
            data["mode"] = "vlm"
            data.setdefault("edges", [])
            return data
    scheme = _heuristic_scheme(db, document_id)
    if err:
        scheme["vlm_error"] = err
    return scheme


def _req_blob(r: Requirement) -> str:
    attrs = " ".join(f"{a.key} {a.value}" for a in r.attributes)
    return f"{r.code} {r.title or ''} {r.text or ''} {attrs}".lower()


def cover(
    scheme: dict[str, Any],
    db: Session,
    document_id: int | None,
    requirement_ids: list[int] | None = None,
) -> dict[str, Any]:
    q = db.query(Requirement).filter(Requirement.is_current.is_(True))
    if document_id:
        q = q.filter(Requirement.document_id == document_id)
    if requirement_ids:
        q = q.filter(Requirement.id.in_(requirement_ids))
    reqs = [r for r in q.all() if not (r.extra or {}).get("stub") and not (r.extra or {}).get("appendix")]
    blobs = [(r, _req_blob(r)) for r in reqs]
    rows = []
    for node in scheme.get("nodes") or []:
        keys = [str(node.get("id") or ""), str(node.get("name") or "")]
        keys = [k for k in keys if k]
        hits = []
        for r, blob in blobs:
            if any(k.lower() in blob for k in keys if len(k) >= 3):
                hits.append({"id": r.id, "code": r.code, "text": (r.text or "")[:180]})
        rows.append(
            {
                "node_id": node.get("id"),
                "name": node.get("name"),
                "kind": node.get("kind"),
                "covered": bool(hits),
                "requirements": hits[:8],
            }
        )
    covered = sum(1 for x in rows if x["covered"])
    missing = [x for x in rows if not x["covered"]]
    return {
        "nodes_total": len(rows),
        "nodes_covered": covered,
        "coverage": round(100 * covered / len(rows), 1) if rows else 0.0,
        "missing": missing,
        "rows": rows,
        "pass": not missing,
    }


def write_report(scheme: dict, cov: dict, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Покрытие функциональной схемы требованиями",
        f"",
        f"Схема: {scheme.get('title') or '—'}",
        f"Режим: {scheme.get('mode')}",
        f"Узлов: {cov['nodes_total']}, покрыто: {cov['nodes_covered']} ({cov['coverage']}%)",
        f"Итог: {'покрыто' if cov['pass'] else 'есть непокрытые узлы'}",
        "",
        "## Узлы",
    ]
    for row in cov["rows"]:
        mark = "да" if row["covered"] else "НЕТ"
        codes = ", ".join(h["code"] for h in row["requirements"]) or "—"
        lines.append(f"- [{mark}] {row['node_id']} — {row['name']} → {codes}")
    if scheme.get("edges"):
        lines.append("")
        lines.append("## Связи ФС")
        for e in scheme["edges"]:
            lines.append(f"- {e.get('from')} → {e.get('to')} ({e.get('signal') or ''})")
    dest.write_text("\n".join(lines), encoding="utf-8")
    return dest


def run_schematic_coverage(
    db: Session,
    path: Path,
    filename: str,
    *,
    document_id: int | None = None,
    requirement_ids: list[int] | None = None,
    on_progress: Any = None,
    **_: Any,
) -> dict[str, Any]:
    if on_progress:
        on_progress({"event": "read", "step": f"чтение {filename}"})
    pages = load_pages(path)
    if on_progress:
        on_progress({"event": "vlm", "step": "VLM: разбор схемы"})
    scheme = analyze_scheme(pages, db, document_id)
    usage = getattr(vlm_chat, "last_usage", None) or {}
    if on_progress:
        on_progress({"event": "vlm_done", "step": f"режим {scheme.get('mode')}", "tokens": usage})
    if on_progress:
        on_progress({"event": "cover", "step": "сопоставление с требованиями"})
    cov = cover(scheme, db, document_id, requirement_ids=requirement_ids)
    EXPORTS.mkdir(parents=True, exist_ok=True)
    out = EXPORTS / f"scheme_coverage_{uuid4().hex[:6]}.md"
    write_report(scheme, cov, out)
    return {
        "pipeline": "schematic-coverage",
        "source": filename,
        "pages": len(pages),
        "scheme": scheme,
        "coverage": cov,
        "output_file": str(out),
        "download": f"/exports/{out.name}",
        "tokens": usage,
    }
