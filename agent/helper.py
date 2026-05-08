"""Agente ayudante. Modelo rápido y barato (Haiku 4.5 por defecto) que:

  1. Escribe un plan al recibir la tarea (planner).
  2. Responde consultas concretas del agente principal durante la ejecución
     (consult_helper tool).

No toca el navegador. Su trabajo es razonar y planificar para que el agente
principal (que sí controla el navegador) tenga que pensar menos por turno.
"""

from __future__ import annotations

import os
from typing import Any

import anthropic

HELPER_MODEL = os.environ.get("HELPER_MODEL", "claude-haiku-4-5-20251001")


PLANNER_SYSTEM = """Eres un planificador para un agente que controla un \
navegador Firefox en un escritorio Linux (1280x800).

El agente tiene estas herramientas: screenshot, left_click(x,y), right_click, \
double_click, type_text, key_press (acepta 'Return', 'Tab', 'ctrl+l', 'ctrl+t', \
'BackSpace', etc.), scroll, mouse_move, left_click_drag, wait, task_complete.

Te dan una tarea. Devuelve un PLAN CONCISO en pasos numerados. Cada paso debe \
ser una acción concreta o un grupo pequeño de acciones. **Máximo 8 pasos.** \
No describas la salida esperada, solo qué hacer.

Reglas para el plan:
- Asume que Firefox está abierto en duckduckgo.com.
- Para ir a una URL: paso "key_press ctrl+l, type_text URL, key_press Return, wait 2".
- Para buscar en Google: ir a google.com primero (o usar la búsqueda actual de DuckDuckGo).
- Si la tarea requiere leer información de una página, incluye un paso "leer la \
pantalla y extraer X".
- Termina siempre con "task_complete con resumen de Y".

Formato de salida: solo la lista numerada, sin preamble, sin markdown extra."""


CONSULTOR_SYSTEM = """Eres un consultor para un agente que está ejecutando una \
tarea en un navegador. El agente te hace una pregunta concreta. Respondes \
breve y directo, máximo 3-4 líneas.

Si te dan un screenshot, úsalo. Si te preguntan dónde está un elemento en \
pantalla, da coordenadas aproximadas (x, y). Si te preguntan estrategia, da \
los siguientes 1-3 pasos concretos."""


def plan_task(task: str, client: anthropic.Anthropic) -> str | None:
    """Pide al helper un plan de pasos. Devuelve el texto del plan, o None si falla."""
    try:
        # Usamos streaming para evitar el 429 de proxies que limitan no-streaming.
        with client.messages.stream(
            model=HELPER_MODEL,
            max_tokens=1024,
            system=PLANNER_SYSTEM,
            messages=[{"role": "user", "content": f"Tarea: {task}\n\nDame el plan."}],
        ) as stream:
            final = stream.get_final_message()
        for blk in final.content:
            if blk.type == "text":
                return blk.text.strip()
    except Exception as e:  # noqa: BLE001
        return f"(no pude generar plan: {type(e).__name__}: {e})"
    return None


def consult_helper(
    question: str,
    client: anthropic.Anthropic,
    screenshot_b64: str | None = None,
) -> str:
    """Pregunta concreta al ayudante. Opcionalmente con screenshot adjunto."""
    content: list[dict[str, Any]] = [{"type": "text", "text": question}]
    if screenshot_b64:
        content.insert(0, {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": screenshot_b64,
            },
        })
    try:
        with client.messages.stream(
            model=HELPER_MODEL,
            max_tokens=512,
            system=CONSULTOR_SYSTEM,
            messages=[{"role": "user", "content": content}],
        ) as stream:
            final = stream.get_final_message()
        for blk in final.content:
            if blk.type == "text":
                return blk.text.strip()
    except Exception as e:  # noqa: BLE001
        return f"(consulta falló: {type(e).__name__}: {e})"
    return "(sin respuesta)"
