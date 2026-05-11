"""Helpers para construir/normalizar la lista `messages` que se envía al
modelo. Sin lógica de turnos — solo construcción de bloques.
"""

from __future__ import annotations

from typing import Any

from .. import computer_tool


def assistant_block_to_param(block: Any) -> dict[str, Any] | None:
    """Convierte un bloque del SDK (objeto Pydantic) al dict-form que la
    API espera al re-enviar el historial. Devuelve None si el tipo no es
    re-serializable (lo dropea silenciosamente — caso raro).
    """
    bt = block.type
    if bt == "text":
        return {"type": "text", "text": block.text}
    if bt == "tool_use":
        return {
            "type": "tool_use",
            "id": block.id,
            "name": block.name,
            "input": block.input,
        }
    if bt == "thinking":
        return {
            "type": "thinking",
            "thinking": getattr(block, "thinking", ""),
            "signature": getattr(block, "signature", ""),
        }
    if bt == "redacted_thinking":
        return {"type": "redacted_thinking", "data": getattr(block, "data", "")}
    return None


def initial_user_content(
    task: str, plan: str | None
) -> tuple[list[dict[str, Any]], str | None]:
    """Primer mensaje del usuario: tarea + plan opcional + screenshot.
    Devuelve (content, screenshot_b64).
    """
    initial = computer_tool.execute("screenshot")
    intro = f"Tarea: {task}"
    if plan:
        intro += f"\n\nPlan sugerido por el ayudante (úsalo como guía, ajústalo si es necesario):\n{plan}"
    intro += "\n\nEsta es la pantalla actual:"
    content: list[dict[str, Any]] = [{"type": "text", "text": intro}]
    screenshot_b64 = initial.get("image_b64")
    if screenshot_b64:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": initial.get("image_media") or "image/jpeg",
                "data": screenshot_b64,
            },
        })
    if initial.get("error"):
        content.append({"type": "text", "text": f"(captura inicial falló: {initial['error']})"})
    return content, screenshot_b64


def append_user_text_smart(
    messages: list[dict[str, Any]],
    text: str,
    image_b64: str | None = None,
    image_media: str | None = None,
) -> None:
    """Añade texto (y opcionalmente imagen) como contenido user.

    Si el último mensaje es user, fusiona los bloques en él (la API rechaza
    consecutive user messages). Si es assistant o no hay, crea uno nuevo.
    """
    blocks: list[dict[str, Any]] = [{"type": "text", "text": text}]
    if image_b64:
        blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": image_media or "image/jpeg",
                "data": image_b64,
            },
        })
    if messages and messages[-1].get("role") == "user":
        existing = messages[-1].get("content")
        if isinstance(existing, str):
            existing = [{"type": "text", "text": existing}]
        elif not isinstance(existing, list):
            existing = []
        messages[-1]["content"] = existing + blocks
    else:
        messages.append({"role": "user", "content": blocks})
