"""Saneador de sesiones persistidas. Cuando reanudamos una sesión guardada
en disco, su estructura puede ser inválida según la API (tool_use sin
tool_result, último mensaje assistant text-only sin nudge user). Esto la
arregla in-place antes de la primera llamada a `client.messages.stream`.
"""

from __future__ import annotations

from typing import Any, Callable

EventCallback = Callable[[dict[str, Any]], None]


def sanitize_resumed_messages(
    messages: list[dict[str, Any]],
    on_event: EventCallback,
) -> None:
    """Recupera sesiones cargadas que tengan estructura inválida para la API.

    Casos manejados:
    1) Último assistant contiene tool_use blocks que NO tienen tool_result en
       el mensaje siguiente. La API rechaza este historial. Cerramos cada
       tool_use con un tool_result sintético en un nuevo mensaje user.
       (Caso típico: sesión guardada tras task_complete antes del fix.)
    2) Después de (1), si el último mensaje sigue siendo assistant (caso raro:
       assistant text-only sin tool_use), añadimos un nudge user para que la
       API tenga algo a lo que responder.

    Modifica messages in-place y emite eventos `log` con lo que reparó.
    """
    if not messages:
        return

    last = messages[-1]
    if last.get("role") == "assistant":
        content = last.get("content") or []
        if not isinstance(content, list):
            content = []
        pending = [
            b for b in content
            if isinstance(b, dict) and b.get("type") == "tool_use"
        ]
        if pending:
            tool_results: list[dict[str, Any]] = []
            for tu in pending:
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.get("id"),
                    "content": (
                        f"[sesión reanudada — tool_use '{tu.get('name')}' "
                        "cerrado sintéticamente por el saneador]"
                    ),
                })
            messages.append({"role": "user", "content": tool_results})
            on_event({
                "type": "log",
                "message": (
                    f"saneador: cerrados {len(tool_results)} tool_use pendientes "
                    f"del último assistant ({', '.join(tu.get('name') or '?' for tu in pending)})"
                ),
            })

    if messages and messages[-1].get("role") == "assistant":
        messages.append({
            "role": "user",
            "content": "[reanudación] continúa o espera nueva instrucción del usuario.",
        })
        on_event({
            "type": "log",
            "message": "saneador: añadido nudge user para reanudar (historial terminaba en assistant)",
        })
