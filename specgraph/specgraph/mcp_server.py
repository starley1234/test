"""MCP (JSON-RPC 2.0) — внешние системы читают изделия и требования.

HTTP: POST /mcp
stdio: python -m specgraph.mcp_server
"""

from __future__ import annotations

from typing import Any

from specgraph.db import SessionLocal
from specgraph.models import Product, Requirement
from specgraph.retrieval.context import expand_product, gather_context

TOOLS = [
    {
        "name": "list_products",
        "description": "Список изделий (code, name, id).",
        "inputSchema": {"type": "object", "properties": {"document_id": {"type": "integer"}}},
    },
    {
        "name": "get_product",
        "description": "Изделие с предками, составом и требованиями.",
        "inputSchema": {"type": "object", "properties": {"product_id": {"type": "integer"}}, "required": ["product_id"]},
    },
    {
        "name": "search_requirements",
        "description": "Текущие требования. Фильтр: document_id, product_id, query.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "document_id": {"type": "integer"},
                "product_id": {"type": "integer"},
                "query": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
    },
    {
        "name": "gather_context",
        "description": "Пакет контекста для LLM: выбранные требования и подграф изделия.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "document_id": {"type": "integer"},
                "requirement_ids": {"type": "array", "items": {"type": "integer"}},
                "product_id": {"type": "integer"},
                "query": {"type": "string"},
            },
        },
    },
]


def _call(name: str, args: dict[str, Any]) -> Any:
    db = SessionLocal()
    try:
        if name == "list_products":
            q = db.query(Product)
            if args.get("document_id"):
                q = q.filter(Product.document_id == args["document_id"])
            return [{"id": p.id, "code": p.code, "name": p.name, "parent_id": p.parent_id} for p in q.limit(200).all()]
        if name == "get_product":
            return expand_product(db, int(args["product_id"]))
        if name == "search_requirements":
            q = db.query(Requirement).filter(Requirement.is_current.is_(True))
            if args.get("document_id"):
                q = q.filter(Requirement.document_id == args["document_id"])
            if args.get("product_id"):
                q = q.filter(Requirement.product_id == args["product_id"])
            rows = q.limit(int(args.get("limit") or 80)).all()
            key = (args.get("query") or "").lower()
            out = []
            for r in rows:
                if key and key not in (r.code or "").lower() and key not in (r.text or "").lower():
                    continue
                out.append(
                    {
                        "id": r.id,
                        "code": r.code,
                        "text": (r.text or "")[:800],
                        "document_id": r.document_id,
                        "product_id": r.product_id,
                        "created_at": r.created_at.isoformat() if getattr(r, "created_at", None) else None,
                    }
                )
            return out
        if name == "gather_context":
            return gather_context(
                db,
                document_id=args.get("document_id"),
                requirement_ids=args.get("requirement_ids"),
                product_id=args.get("product_id"),
                query=args.get("query"),
            )
        raise ValueError(f"unknown tool {name}")
    finally:
        db.close()


def handle_rpc(msg: dict[str, Any]) -> dict[str, Any]:
    mid = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") or {}
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": mid,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "specgraph", "version": "0.1.0"},
            },
        }
    if method == "notifications/initialized":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            data = _call(name, args)
        except Exception as exc:  # noqa: BLE001
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32000, "message": str(exc)}}
        import json

        return {
            "jsonrpc": "2.0",
            "id": mid,
            "result": {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, default=str)}]},
        }
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method {method}"}}


def main() -> None:
    import json
    import sys

    from specgraph.db import init_db

    init_db()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        out = handle_rpc(msg)
        sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
