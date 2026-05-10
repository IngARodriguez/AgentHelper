"""Runner del agente. Expone `run_agent(task, on_event)` — un bucle agéntico
síncrono que emite eventos vía callback.

Modo de operación: **custom tools**. Definimos nosotros las tools del agente
(left_click, type_text, key_press, scroll, etc.) y le mandamos screenshots
como imágenes en los mensajes. Esto funciona con cualquier endpoint compatible
con la Messages API + tool use, sin requerir el beta header `computer-use-...`
(que algunos proxies, como Skills Network, no propagan).

Si tienes un endpoint que sí soporte computer-use beta, ver el flag
USE_COMPUTER_USE_BETA al final del archivo (no implementado por defecto).
"""

from __future__ import annotations

import os
import time
import traceback
from typing import Any, Callable

import anthropic

from . import bash_tool, computer_tool

# ─── Config (env-driven) ─────────────────────────────────────────────────────

MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-4-7")
DISPLAY_WIDTH = int(os.environ.get("DISPLAY_WIDTH", "1280"))
DISPLAY_HEIGHT = int(os.environ.get("DISPLAY_HEIGHT", "800"))
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "8192"))
MAX_ITERATIONS = int(os.environ.get("MAX_ITERATIONS", "100"))

# Cuántos screenshots recientes conservar tal cual en el historial. Los más
# viejos se sustituyen por un placeholder de texto. 0 = sin truncar (manda
# todos al modelo, llena más contexto pero da continuidad visual completa).
# Default 10: continuidad visual amplia sin saturar contexto en tareas largas.
KEEP_RECENT_SCREENSHOTS = int(os.environ.get("KEEP_RECENT_SCREENSHOTS", "10"))

SYSTEM_PROMPT = """Eres un agente que controla un escritorio Linux con Firefox \
abierto, dentro de un sandbox Docker.

Resolución de la pantalla: {w}x{h} píxeles. Las coordenadas son [x, y] desde \
la esquina superior izquierda.

Tienes estas herramientas:
- screenshot()                       — captura la pantalla actual.
- left_click(x, y)                   — click izquierdo.
- right_click(x, y)                  — click derecho.
- double_click(x, y)                 — doble click.
- type_text(text)                    — escribe texto en el foco actual.
- key_press(key)                     — pulsa tecla o combo: 'Return', 'Tab',
                                       'Escape', 'ctrl+l', 'ctrl+t', 'ctrl+w',
                                       'ctrl+a', 'BackSpace', 'Page_Down', etc.
- scroll(x, y, direction, amount)    — desplaza la rueda en (x,y);
                                       direction: up/down/left/right; amount: clicks.
- mouse_move(x, y)                   — mueve el ratón sin clickar.
- left_click_drag(x1, y1, x2, y2)    — arrastra desde (x1,y1) a (x2,y2).
- wait(seconds)                      — espera segundos (max 30).
- bash(command, timeout=30)          — ejecuta un comando bash en el sandbox Debian.
                                       Pre-instalados: xterm, nano, curl, wget, jq,
                                       unzip, ping, dig, ss, netstat. Para abrir una
                                       terminal visual en el escritorio: `xterm &`.
                                       Devuelve stdout, stderr y exit_code. CWD: /app.
- task_complete(summary)             — llámala cuando hayas terminado la tarea
                                       y resume brevemente el resultado.

Reglas:
- Cada vez que ejecutes una acción visual (click, scroll, type, key_press, etc.) \
recibirás un screenshot actualizado en el resultado.
- Mira el screenshot atentamente antes de decidir la siguiente acción. \
Identifica visualmente botones, campos de texto, enlaces.
- Para enfocar la barra de direcciones de Firefox usa key_press('ctrl+l').
- Después de navegar a una URL nueva, usa wait(2) para que cargue.
- Si una acción no produjo el efecto esperado, captura primero (screenshot) y replantea.
- Cuando completes la tarea, llama a task_complete con un resumen claro.
- Tienes libertad total dentro del sandbox: navega a cualquier sitio.
""".format(w=DISPLAY_WIDTH, h=DISPLAY_HEIGHT)


TOOLS: list[dict[str, Any]] = [
    {
        "name": "screenshot",
        "description": "Captura la pantalla actual. Úsalo cuando necesites ver el estado antes de actuar.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "left_click",
        "description": "Click izquierdo en la coordenada (x, y).",
        "input_schema": {
            "type": "object",
            "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}},
            "required": ["x", "y"],
        },
    },
    {
        "name": "right_click",
        "description": "Click derecho en (x, y).",
        "input_schema": {
            "type": "object",
            "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}},
            "required": ["x", "y"],
        },
    },
    {
        "name": "double_click",
        "description": "Doble click izquierdo en (x, y).",
        "input_schema": {
            "type": "object",
            "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}},
            "required": ["x", "y"],
        },
    },
    {
        "name": "type_text",
        "description": "Escribe texto en el elemento que tenga el foco. Asegúrate antes de hacer click en el campo.",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "key_press",
        "description": (
            "Pulsa una tecla o combinación (sintaxis xdotool). "
            "Ejemplos: 'Return', 'Tab', 'Escape', 'BackSpace', 'Page_Down', "
            "'ctrl+l' (barra direcciones), 'ctrl+t' (nueva pestaña), "
            "'ctrl+w' (cerrar pestaña), 'ctrl+a' (seleccionar todo)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
    },
    {
        "name": "scroll",
        "description": "Desplaza la rueda del ratón en (x, y).",
        "input_schema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
                "amount": {"type": "integer", "description": "Número de clicks de rueda", "default": 3},
            },
            "required": ["x", "y", "direction"],
        },
    },
    {
        "name": "mouse_move",
        "description": "Mueve el ratón a (x, y) sin clickar.",
        "input_schema": {
            "type": "object",
            "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}},
            "required": ["x", "y"],
        },
    },
    {
        "name": "left_click_drag",
        "description": "Arrastra desde (x1, y1) hasta (x2, y2) con el botón izquierdo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "x1": {"type": "integer"},
                "y1": {"type": "integer"},
                "x2": {"type": "integer"},
                "y2": {"type": "integer"},
            },
            "required": ["x1", "y1", "x2", "y2"],
        },
    },
    {
        "name": "wait",
        "description": "Espera N segundos antes de seguir. Útil tras navegar a una URL para que cargue.",
        "input_schema": {
            "type": "object",
            "properties": {"seconds": {"type": "number"}},
            "required": ["seconds"],
        },
    },
    {
        "name": "bash",
        "description": (
            "Ejecuta un comando en bash dentro del sandbox Debian. Devuelve "
            "stdout, stderr y exit_code. Timeout por defecto 30s (max 120s). "
            "Usa esto para tareas que no requieren ver el navegador: descargar "
            "(curl/wget), procesar texto (grep/awk/sed/jq), explorar el "
            "filesystem (ls/find), instalar paquetes (apt-get install -y), "
            "verificar conectividad (ping/dig), etc. CWD inicial: /app. "
            "Para encadenar: usa '&&' o ';'. Para cambiar de dir usa 'cd /path && cmd'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Comando bash a ejecutar"},
                "timeout": {
                    "type": "number",
                    "description": "Timeout en segundos (default 30, max 120)",
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "task_complete",
        "description": "Marca la tarea como completada con un resumen del resultado. Llámala al final.",
        "input_schema": {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        },
    },
]


# ─── Mapeo a computer_tool ───────────────────────────────────────────────────

def _dispatch_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Traduce una llamada de tool custom al action dict que entiende computer_tool."""
    if name == "screenshot":
        return computer_tool.execute("screenshot")
    if name == "left_click":
        return computer_tool.execute("left_click", coordinate=[args["x"], args["y"]])
    if name == "right_click":
        return computer_tool.execute("right_click", coordinate=[args["x"], args["y"]])
    if name == "double_click":
        return computer_tool.execute("double_click", coordinate=[args["x"], args["y"]])
    if name == "type_text":
        return computer_tool.execute("type", text=args["text"])
    if name == "key_press":
        return computer_tool.execute("key", text=args["key"])
    if name == "scroll":
        return computer_tool.execute(
            "scroll",
            coordinate=[args["x"], args["y"]],
            scroll_direction=args["direction"],
            scroll_amount=int(args.get("amount", 3)),
        )
    if name == "mouse_move":
        return computer_tool.execute("mouse_move", coordinate=[args["x"], args["y"]])
    if name == "left_click_drag":
        return computer_tool.execute(
            "left_click_drag",
            start_coordinate=[args["x1"], args["y1"]],
            coordinate=[args["x2"], args["y2"]],
        )
    if name == "wait":
        return computer_tool.execute("wait", duration=float(args["seconds"]))
    return {"error": f"tool desconocida: {name}", "image_b64": None, "text": None}


# ─── Helpers ─────────────────────────────────────────────────────────────────

EventCallback = Callable[[dict[str, Any]], None]


def _assistant_block_to_param(block: Any) -> dict[str, Any] | None:
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


def _initial_user_content(task: str, plan: str | None) -> tuple[list[dict[str, Any]], str | None]:
    """Mensaje inicial: tarea + plan opcional + screenshot. Devuelve (content, screenshot_b64)."""
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


def _prune_old_screenshots(messages: list[dict[str, Any]], keep: int) -> None:
    """Sustituye in-place las imágenes viejas del historial por un placeholder.

    Mantiene tal cual los `keep` screenshots más recientes y reemplaza el resto
    con un bloque de texto. `keep <= 0` desactiva el pruning (se mandan todas
    las imágenes al modelo). Reduce input tokens en tareas largas (cada
    JPEG ~1000 tokens; tras 30 acciones sin pruning serían ~30k tokens por
    turno solo en imágenes).
    """
    if keep <= 0:
        return
    # Recoge índices de imágenes en orden (msg_idx, content_idx)
    image_locations: list[tuple[int, int]] = []
    for mi, msg in enumerate(messages):
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for ci, blk in enumerate(content):
            if isinstance(blk, dict) and blk.get("type") == "image":
                image_locations.append((mi, ci))
            elif isinstance(blk, dict) and blk.get("type") == "tool_result":
                # tool_result.content puede ser una lista con imágenes dentro
                inner = blk.get("content")
                if isinstance(inner, list):
                    for ii, sub in enumerate(inner):
                        if isinstance(sub, dict) and sub.get("type") == "image":
                            image_locations.append((mi, ci, ii))  # tipo más largo
    # Las últimas `keep` se conservan.
    if len(image_locations) <= keep:
        return
    to_prune = image_locations[: len(image_locations) - keep]
    placeholder = {
        "type": "text",
        "text": "[screenshot anterior omitido para ahorrar contexto]",
    }
    for loc in to_prune:
        if len(loc) == 2:
            mi, ci = loc
            messages[mi]["content"][ci] = placeholder
        else:
            mi, ci, ii = loc
            inner = messages[mi]["content"][ci].get("content")
            if isinstance(inner, list) and 0 <= ii < len(inner):
                inner[ii] = placeholder


def _build_cached_system() -> list[dict[str, Any]]:
    """System prompt con cache_control para que la API lo cachee entre turnos."""
    return [{
        "type": "text",
        "text": SYSTEM_PROMPT,
        "cache_control": {"type": "ephemeral"},
    }]


def _build_cached_tools() -> list[dict[str, Any]]:
    """Tools list marcando la última con cache_control. Cachea TODA la lista."""
    if not TOOLS:
        return TOOLS
    cached = [dict(t) for t in TOOLS]
    cached[-1] = {**cached[-1], "cache_control": {"type": "ephemeral"}}
    return cached


_CACHED_SYSTEM = _build_cached_system()
_CACHED_TOOLS = _build_cached_tools()


def _stream_one_turn(
    client: anthropic.Anthropic,
    messages: list[dict[str, Any]],
    on_event: EventCallback,
) -> Any:
    """Hace un turno con streaming. Devuelve el final_message."""
    # Limpiar imágenes viejas antes de mandar — reduce tokens y latencia.
    _prune_old_screenshots(messages, keep=KEEP_RECENT_SCREENSHOTS)

    backoff = 2.0
    for attempt in range(5):
        try:
            event_count = 0
            with client.messages.stream(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=_CACHED_SYSTEM,
                tools=_CACHED_TOOLS,
                messages=messages,
            ) as stream:
                for ev in stream:
                    event_count += 1
                    if ev.type == "content_block_delta":
                        delta = ev.delta
                        if delta.type == "text_delta":
                            on_event({"type": "text", "text": delta.text})
                if event_count == 0:
                    raise RuntimeError(
                        "el stream cerró sin eventos. El proxy/API devolvió "
                        "una respuesta vacía. Verifica /debug/simple-stream."
                    )
                return stream.get_final_message()
        except anthropic.RateLimitError as e:
            on_event({"type": "log", "message": f"rate-limit, reintentando en {backoff:.1f}s"})
            time.sleep(backoff)
            backoff *= 2
        except anthropic.APIStatusError as e:
            if 500 <= e.status_code < 600 and attempt < 4:
                on_event({"type": "log", "message": f"server {e.status_code}, reintentando en {backoff:.1f}s"})
                time.sleep(backoff)
                backoff *= 2
                continue
            raise
    raise RuntimeError("agotados los reintentos contra la API")


# ─── Entry point ─────────────────────────────────────────────────────────────

def run_agent(task: str, on_event: EventCallback) -> None:
    """Ejecuta una tarea de principio a fin. Bloquea hasta terminar o fallar."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        on_event({"type": "error", "message": "falta ANTHROPIC_API_KEY"})
        return

    client = anthropic.Anthropic(api_key=api_key)

    initial_content, last_screenshot = _initial_user_content(task, plan=None)
    messages: list[dict[str, Any]] = [{"role": "user", "content": initial_content}]

    try:
        for iteration in range(MAX_ITERATIONS):
            final = _stream_one_turn(client, messages, on_event)

            assistant_blocks = [
                b for b in (_assistant_block_to_param(blk) for blk in final.content)
                if b is not None
            ]
            messages.append({"role": "assistant", "content": assistant_blocks})

            on_event({"type": "turn_end", "stop_reason": final.stop_reason})

            if final.stop_reason == "end_turn":
                # Terminó sin llamar tools — probablemente acabó o dio respuesta final.
                on_event({"type": "done", "message": "tarea finalizada (end_turn)"})
                return

            if final.stop_reason == "tool_use":
                tool_results = []
                for blk in final.content:
                    if blk.type != "tool_use":
                        continue
                    name = blk.name
                    args = blk.input or {}

                    # task_complete: termina el bucle
                    if name == "task_complete":
                        summary = args.get("summary", "")
                        on_event({"type": "action", "action": "task_complete", "input": {"summary": summary}})
                        on_event({"type": "done", "message": f"tarea completada: {summary}"})
                        return

                    # log de la acción al cliente (truncando textos largos)
                    display_args = {
                        k: (v[:77] + "…" if isinstance(v, str) and len(v) > 80 else v)
                        for k, v in args.items()
                    }
                    on_event({"type": "action", "action": name, "input": display_args})

                    # bash: ejecuta comando shell
                    if name == "bash":
                        cmd = args.get("command", "")
                        timeout_arg = float(args.get("timeout", bash_tool.DEFAULT_TIMEOUT_S))
                        bash_result = bash_tool.execute_bash(cmd, timeout=timeout_arg)
                        on_event({
                            "type": "bash_output",
                            "command": cmd,
                            "stdout": bash_result["stdout"],
                            "stderr": bash_result["stderr"],
                            "exit_code": bash_result["exit_code"],
                            "error": bash_result.get("error"),
                        })
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": blk.id,
                            "content": bash_tool.to_tool_result_content(bash_result),
                            "is_error": bool(bash_result.get("error")) or bash_result["exit_code"] != 0,
                        })
                        continue

                    # Acciones del navegador
                    result = _dispatch_tool(name, args)
                    if result.get("error"):
                        on_event({"type": "tool_result_error", "message": result["error"]})
                    if result.get("image_b64"):
                        last_screenshot = result["image_b64"]

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": blk.id,
                        "content": computer_tool.to_tool_result_content(result),
                        "is_error": bool(result.get("error")),
                    })
                messages.append({"role": "user", "content": tool_results})
                continue

            if final.stop_reason == "max_tokens":
                on_event({"type": "log", "message": "max_tokens, pidiendo continuación"})
                messages.append({"role": "user", "content": "Continúa."})
                continue

            if final.stop_reason == "refusal":
                details = getattr(final, "stop_details", None)
                on_event({"type": "error", "message": f"el modelo rechazó: {details}"})
                return

            on_event({"type": "error", "message": f"stop_reason inesperado: {final.stop_reason}"})
            return

        on_event({"type": "error", "message": f"alcanzado MAX_ITERATIONS={MAX_ITERATIONS}"})

    except Exception as e:  # noqa: BLE001
        tb = traceback.format_exc()
        print("\n[agent.run_agent] EXCEPTION:\n" + tb, flush=True)
        on_event({
            "type": "error",
            "message": f"{type(e).__name__}: {e}\n\n{tb}",
        })
