"""Capa HTTP del agente: FastAPI app + estado compartido + routes.

`create_app()` ensambla todo y devuelve la instancia de FastAPI lista para
servir. El entry point real para uvicorn lo expone `agent/server.py` (shim
de retrocompat) como `agent.server:app`.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from ..config import NOVNC_DIR
from .routes import register_routes


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """Arranca servicios opcionales (Telegram bot) al iniciar uvicorn."""
    try:
        from .. import telegram_bot
        telegram_bot.start_bot()
    except Exception as e:  # noqa: BLE001
        print(f"[lifespan] error iniciando telegram_bot: {e!r}", flush=True)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Agente de navegador", lifespan=_lifespan)

    # CORS: permite llamadas a /api/* desde cualquier origen
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    # Static UI assets (HTML/CSS/JS extraídos del antiguo INDEX_HTML)
    ui_dir = Path(__file__).parent / "ui"
    if ui_dir.exists():
        app.mount("/ui", StaticFiles(directory=str(ui_dir)), name="ui")

    # noVNC bajo /vnc/
    if NOVNC_DIR.exists():
        app.mount("/vnc", StaticFiles(directory=str(NOVNC_DIR), html=True), name="vnc")

    register_routes(app)
    return app
