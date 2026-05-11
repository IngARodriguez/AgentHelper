"""Shim de retrocompatibilidad. `docker/start.sh` apunta a
`agent.server:app`, así que mantenemos ese símbolo aquí. El código real
está modularizado en `agent.web.*`.
"""

from __future__ import annotations

from .web import create_app

app = create_app()

__all__ = ["app"]
