"""Agrupa todos los routers en `register_routes(app)`."""

from __future__ import annotations

from fastapi import FastAPI

from . import api, dashboard, debug, vnc


def register_routes(app: FastAPI) -> None:
    """Monta todos los routers / handlers en la app. Orden no importa
    (cada router incluye sus propios paths)."""
    app.include_router(dashboard.router)
    app.include_router(api.router)
    app.include_router(debug.router)
    vnc.register(app)  # WebSocket + el mount de /vnc lo hace create_app()
