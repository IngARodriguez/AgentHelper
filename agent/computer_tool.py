"""Capa de ejecución para la tool `computer_20250124`.

Recibe una acción tal como la emite el modelo y la ejecuta en el display Xvfb
del contenedor usando xdotool/scrot. Devuelve el resultado en el formato que
la API espera como `tool_result` (texto, imagen base64, o ambos).
"""

from __future__ import annotations

import base64
import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any

DISPLAY = os.environ.get("DISPLAY", ":1")
SCREENSHOT_PATH = Path("/tmp/agent_screenshot.png")

# Pausa después de cada acción para que la UI se asiente antes del siguiente screenshot.
# Ajustable vía env var por si una página concreta necesita más.
ACTION_DELAY_S = float(os.environ.get("ACTION_DELAY_S", "0.6"))

# Acciones que devuelven una imagen al modelo. Las que no aparecen aquí solo
# devuelven texto (cursor_position) o nada relevante.
ACTIONS_THAT_SCREENSHOT = {
    "screenshot",
    "left_click",
    "right_click",
    "middle_click",
    "double_click",
    "triple_click",
    "left_click_drag",
    "mouse_move",
    "type",
    "key",
    "scroll",
    "wait",
    "hold_key",
    "left_mouse_down",
    "left_mouse_up",
}


class ToolError(Exception):
    """Error ejecutando una acción — se devuelve al modelo como is_error=True."""


def _run(cmd: list[str], timeout: float = 10.0) -> str:
    env = {**os.environ, "DISPLAY": DISPLAY}
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise ToolError(f"Timeout: {' '.join(shlex.quote(c) for c in cmd)}") from e
    if result.returncode != 0:
        raise ToolError(
            f"{cmd[0]} rc={result.returncode} stderr={result.stderr.strip()!r}"
        )
    return result.stdout


def _xdotool(*args: str) -> str:
    return _run(["xdotool", *args])


def _coord(c: Any) -> tuple[int, int]:
    if not isinstance(c, (list, tuple)) or len(c) != 2:
        raise ToolError(f"coordenada inválida: {c!r}")
    return int(c[0]), int(c[1])


def _take_screenshot() -> str:
    """Captura el display actual y devuelve la imagen como base64 PNG."""
    if SCREENSHOT_PATH.exists():
        SCREENSHOT_PATH.unlink()
    # scrot a veces falla la primera vez tras un click rápido; reintentamos una vez.
    last_err: Exception | None = None
    for _ in range(2):
        try:
            _run(["scrot", "-o", str(SCREENSHOT_PATH)], timeout=5.0)
            data = SCREENSHOT_PATH.read_bytes()
            return base64.b64encode(data).decode("ascii")
        except (ToolError, FileNotFoundError) as e:
            last_err = e
            time.sleep(0.2)
    raise ToolError(f"no pude capturar pantalla: {last_err}")


def execute(action: str, **kwargs: Any) -> dict[str, Any]:
    """Ejecuta una acción y devuelve un dict con el formato del tool_result content.

    Returns: dict con keys:
        - "image_b64": str | None  (base64 PNG si la acción produce screenshot)
        - "text": str | None       (texto, p.ej. cursor_position devuelve "X,Y")
        - "error": str | None      (si algo falló)
    """
    out: dict[str, Any] = {"image_b64": None, "text": None, "error": None}

    try:
        if action == "screenshot":
            pass  # solo capturamos abajo

        elif action == "left_click":
            x, y = _coord(kwargs.get("coordinate"))
            _xdotool("mousemove", "--sync", str(x), str(y), "click", "1")

        elif action == "right_click":
            x, y = _coord(kwargs.get("coordinate"))
            _xdotool("mousemove", "--sync", str(x), str(y), "click", "3")

        elif action == "middle_click":
            x, y = _coord(kwargs.get("coordinate"))
            _xdotool("mousemove", "--sync", str(x), str(y), "click", "2")

        elif action == "double_click":
            x, y = _coord(kwargs.get("coordinate"))
            _xdotool(
                "mousemove", "--sync", str(x), str(y),
                "click", "--repeat", "2", "--delay", "100", "1",
            )

        elif action == "triple_click":
            x, y = _coord(kwargs.get("coordinate"))
            _xdotool(
                "mousemove", "--sync", str(x), str(y),
                "click", "--repeat", "3", "--delay", "100", "1",
            )

        elif action == "mouse_move":
            x, y = _coord(kwargs.get("coordinate"))
            _xdotool("mousemove", "--sync", str(x), str(y))

        elif action == "left_click_drag":
            sx, sy = _coord(kwargs.get("start_coordinate"))
            ex, ey = _coord(kwargs.get("coordinate"))
            _xdotool(
                "mousemove", "--sync", str(sx), str(sy),
                "mousedown", "1",
                "mousemove", "--sync", str(ex), str(ey),
                "mouseup", "1",
            )

        elif action == "type":
            text = kwargs.get("text", "")
            if not isinstance(text, str):
                raise ToolError(f"text debe ser str, fue {type(text).__name__}")
            # --clearmodifiers evita que un modifier residual cambie el texto.
            _xdotool("type", "--delay", "12", "--clearmodifiers", "--", text)

        elif action == "key":
            text = kwargs.get("text", "")
            if not isinstance(text, str):
                raise ToolError(f"key text debe ser str, fue {type(text).__name__}")
            _xdotool("key", "--clearmodifiers", text)

        elif action == "scroll":
            coord = kwargs.get("coordinate")
            direction = kwargs.get("scroll_direction", "down")
            amount = int(kwargs.get("scroll_amount", 3))
            if coord is not None:
                x, y = _coord(coord)
                _xdotool("mousemove", "--sync", str(x), str(y))
            button_map = {"up": "4", "down": "5", "left": "6", "right": "7"}
            button = button_map.get(direction)
            if button is None:
                raise ToolError(f"scroll_direction inválida: {direction!r}")
            for _ in range(max(1, amount)):
                _xdotool("click", button)

        elif action == "wait":
            duration = float(kwargs.get("duration", 1.0))
            duration = max(0.0, min(duration, 30.0))  # cap defensivo
            time.sleep(duration)

        elif action == "cursor_position":
            raw = _xdotool("getmouselocation", "--shell")
            x = y = None
            for line in raw.splitlines():
                if line.startswith("X="):
                    x = line.split("=", 1)[1]
                elif line.startswith("Y="):
                    y = line.split("=", 1)[1]
            out["text"] = f"{x},{y}"
            return out  # no necesita screenshot

        elif action == "hold_key":
            text = kwargs.get("text", "")
            duration = float(kwargs.get("duration", 1.0))
            duration = max(0.0, min(duration, 10.0))
            _xdotool("keydown", text)
            time.sleep(duration)
            _xdotool("keyup", text)

        elif action == "left_mouse_down":
            coord = kwargs.get("coordinate")
            if coord is not None:
                x, y = _coord(coord)
                _xdotool("mousemove", "--sync", str(x), str(y))
            _xdotool("mousedown", "1")

        elif action == "left_mouse_up":
            coord = kwargs.get("coordinate")
            if coord is not None:
                x, y = _coord(coord)
                _xdotool("mousemove", "--sync", str(x), str(y))
            _xdotool("mouseup", "1")

        else:
            raise ToolError(f"acción desconocida: {action!r}")

        # Pequeña pausa para que la UI reaccione antes de capturar.
        time.sleep(ACTION_DELAY_S)
        if action in ACTIONS_THAT_SCREENSHOT:
            out["image_b64"] = _take_screenshot()

    except ToolError as e:
        out["error"] = str(e)
    except Exception as e:  # noqa: BLE001 — el modelo verá el mensaje y reaccionará
        out["error"] = f"error inesperado: {e!r}"

    return out


def to_tool_result_content(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Convierte el dict de execute() al formato `content` de un tool_result."""
    blocks: list[dict[str, Any]] = []
    if result.get("error"):
        blocks.append({"type": "text", "text": result["error"]})
        return blocks
    if result.get("text"):
        blocks.append({"type": "text", "text": result["text"]})
    if result.get("image_b64"):
        blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": result["image_b64"],
            },
        })
    if not blocks:
        blocks.append({"type": "text", "text": "ok"})
    return blocks
