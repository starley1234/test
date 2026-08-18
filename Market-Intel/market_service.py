"""Backward-compatible ASGI entry point.

Allows: uvicorn market_service:app --host 0.0.0.0 --port 8080
"""
from app import app
