"""Endpoints de diagnóstico para verificar Xvfb/x11vnc/firefox y el
streaming de la API. Sin auth — son seguros (read-only)."""

from __future__ import annotations

import os
import socket
import subprocess
from typing import Any

import httpx
from fastapi import APIRouter

router = APIRouter(prefix="/debug")


def _pgrep(name: str) -> str:
    try:
        r = subprocess.run(
            ["pgrep", "-a", name], capture_output=True, text=True, timeout=2,
        )
        return r.stdout.strip() or "(no procs)"
    except Exception as e:  # noqa: BLE001
        return f"err: {e}"


def _tail(path: str, n: int = 30) -> str:
    try:
        with open(path) as f:
            lines = f.readlines()
        return "".join(lines[-n:])
    except Exception as e:  # noqa: BLE001
        return f"(no se puede leer: {e})"


def _can_connect(host: str, port: int) -> str:
    try:
        with socket.create_connection((host, port), timeout=2):
            return "ok"
    except Exception as e:  # noqa: BLE001
        return f"falla: {e}"


@router.get("/services")
def debug_services() -> dict[str, Any]:
    """Lista procesos clave + intenta conectar a x11vnc:5900."""
    return {
        "procs": {
            "Xvfb": _pgrep("Xvfb"),
            "fluxbox": _pgrep("fluxbox"),
            "x11vnc": _pgrep("x11vnc"),
            "firefox": _pgrep("firefox"),
        },
        "tcp": {
            "x11vnc:5900": _can_connect("127.0.0.1", 5900),
        },
        "logs": {
            "xvfb.log": _tail("/tmp/xvfb.log"),
            "x11vnc.log": _tail("/tmp/x11vnc.log"),
            "fluxbox.log": _tail("/tmp/fluxbox.log"),
            "firefox.log": _tail("/tmp/firefox.log"),
        },
    }


@router.get("/computer-use")
def debug_computer_use() -> dict[str, Any]:
    """Diagnóstico: stream raw con tools+beta del agente."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
    url = f"{base_url}/v1/messages"

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "computer-use-2025-01-24",
        "content-type": "application/json",
    }
    body = {
        "model": os.environ.get("CLAUDE_MODEL", "claude-opus-4-7"),
        "max_tokens": 512,
        "stream": True,
        "tools": [{
            "type": "computer_20250124",
            "name": "computer",
            "display_width_px": 1280,
            "display_height_px": 800,
            "display_number": 1,
        }],
        "messages": [{"role": "user", "content": "di hola en una palabra"}],
    }

    try:
        with httpx.Client(timeout=30.0) as h:
            with h.stream("POST", url, headers=headers, json=body) as r:
                response_headers = dict(r.headers)
                status = r.status_code
                buf = []
                total = 0
                for chunk in r.iter_text():
                    buf.append(chunk)
                    total += len(chunk)
                    if total > 8000:
                        buf.append("\n…[truncado]")
                        break
                body_text = "".join(buf)
        return {
            "url": url,
            "request_headers_sent": list(headers.keys()),
            "status": status,
            "response_headers": response_headers,
            "response_body": body_text,
        }
    except Exception as e:  # noqa: BLE001
        return {"url": url, "error": f"{type(e).__name__}: {e}"}


@router.get("/simple-stream")
def debug_simple_stream() -> dict[str, Any]:
    """Diagnóstico mínimo: stream sin tools ni beta."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
    url = f"{base_url}/v1/messages"

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": os.environ.get("CLAUDE_MODEL", "claude-opus-4-7"),
        "max_tokens": 256,
        "stream": True,
        "messages": [{"role": "user", "content": "Hola"}],
    }

    try:
        with httpx.Client(timeout=30.0) as h:
            with h.stream("POST", url, headers=headers, json=body) as r:
                status = r.status_code
                response_headers = dict(r.headers)
                buf = []
                total = 0
                for chunk in r.iter_text():
                    buf.append(chunk)
                    total += len(chunk)
                    if total > 4000:
                        buf.append("\n…[truncado]")
                        break
        return {
            "url": url,
            "status": status,
            "response_headers": response_headers,
            "response_body": "".join(buf),
        }
    except Exception as e:  # noqa: BLE001
        return {"url": url, "error": f"{type(e).__name__}: {e}"}
