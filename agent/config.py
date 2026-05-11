"""Constantes env-driven del agente. Centralizadas para que cualquier
módulo pueda importarlas sin tocar lógica.

Las leemos al import. Si necesitas cambiar valores en runtime, vuelve a
arrancar el proceso (es el comportamiento esperado en Docker).
"""

from __future__ import annotations

import os
from pathlib import Path

# ─── Modelo + límites de generación ──────────────────────────────────────────

MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-4-7")
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "8192"))
MAX_ITERATIONS = int(os.environ.get("MAX_ITERATIONS", "100"))

# ─── Display / pantalla del agente ───────────────────────────────────────────

DISPLAY_WIDTH = int(os.environ.get("DISPLAY_WIDTH", "1280"))
DISPLAY_HEIGHT = int(os.environ.get("DISPLAY_HEIGHT", "800"))

# ─── Gestión de contexto / compactación ──────────────────────────────────────

# Cuántos screenshots recientes se mandan tal cual; los más viejos se
# reemplazan por un placeholder de texto. 0 = sin truncar.
KEEP_RECENT_SCREENSHOTS = int(os.environ.get("KEEP_RECENT_SCREENSHOTS", "10"))

# Auto-compactación del historial. Preserva texto del asistente; solo
# adelgaza tool_results, tool_use inputs y screenshots viejos.
CONTEXT_TARGET_TOKENS = int(os.environ.get("CONTEXT_TARGET_TOKENS", "300000"))
CONTEXT_KEEP_RECENT_TURNS = int(os.environ.get("CONTEXT_KEEP_RECENT_TURNS", "20"))
CONTEXT_BASH_OUTPUT_TRIM = int(os.environ.get("CONTEXT_BASH_OUTPUT_TRIM", "1500"))
CONTEXT_TOOL_INPUT_TRIM = int(os.environ.get("CONTEXT_TOOL_INPUT_TRIM", "400"))

# ─── Web (FastAPI + noVNC + auth opcional) ───────────────────────────────────

VNC_PORT = int(os.environ.get("VNC_PORT", "5900"))
NOVNC_DIR = Path(os.environ.get("NOVNC_DIR", "/usr/share/novnc"))

# Token opcional para /api/*. Si está vacío, /api/* es público.
API_TOKEN = os.environ.get("API_TOKEN", "").strip()
