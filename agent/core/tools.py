"""Schema de tools que ofrecemos al modelo + dispatch al backend real
(`computer_tool` para acciones de escritorio; `bash` se ejecuta en
`core/loop.py` porque también emite eventos al stream).
"""

from __future__ import annotations

from typing import Any

from .. import computer_tool

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


def dispatch_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Traduce una llamada de tool custom al action dict que entiende
    `computer_tool`. No maneja `bash` ni `task_complete` — esos son casos
    especiales del bucle (emiten eventos / terminan el run).
    """
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
