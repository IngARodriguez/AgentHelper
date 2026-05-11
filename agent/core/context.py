"""Gestión de contexto: prune de screenshots viejos + estimación de tokens
+ compactación progresiva. Diseñado para preservar TODO el texto del
asistente (findings, razonamiento) y solo adelgazar datos brutos viejos
(outputs de bash, inputs largos, screenshots). Sin esto, sesiones largas
saturan el contexto del proxy ngrok (cierra stream sin eventos).
"""

from __future__ import annotations

import json as _json
from typing import Any, Callable

from ..config import (
    CONTEXT_BASH_OUTPUT_TRIM,
    CONTEXT_KEEP_RECENT_TURNS,
    CONTEXT_TOOL_INPUT_TRIM,
)

EventCallback = Callable[[dict[str, Any]], None]


def prune_old_screenshots(messages: list[dict[str, Any]], keep: int) -> None:
    """Sustituye in-place las imágenes viejas del historial por un placeholder.

    Mantiene tal cual los `keep` screenshots más recientes y reemplaza el resto
    con un bloque de texto. `keep <= 0` desactiva el pruning (se mandan todas
    las imágenes al modelo). Reduce input tokens en tareas largas (cada
    JPEG ~1000 tokens; tras 30 acciones sin pruning serían ~30k tokens por
    turno solo en imágenes).
    """
    if keep <= 0:
        return
    image_locations: list[tuple[int, ...]] = []
    for mi, msg in enumerate(messages):
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for ci, blk in enumerate(content):
            if isinstance(blk, dict) and blk.get("type") == "image":
                image_locations.append((mi, ci))
            elif isinstance(blk, dict) and blk.get("type") == "tool_result":
                inner = blk.get("content")
                if isinstance(inner, list):
                    for ii, sub in enumerate(inner):
                        if isinstance(sub, dict) and sub.get("type") == "image":
                            image_locations.append((mi, ci, ii))
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


def estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """Heurística rápida de tokens del historial. Aproxima:
    - texto: len/4
    - imagen: ~1500 tokens (JPEG q=90 a 1280x800)
    - tool_use input: len(json)/4
    - tool_result content (string o lista de bloques): igual que texto/imagen
    No es exacto pero permite decidir si compactar; el coste real lo calcula
    la API a posteriori.
    """
    total = 0
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            total += len(content) // 4
            continue
        if not isinstance(content, list):
            continue
        for blk in content:
            if not isinstance(blk, dict):
                continue
            t = blk.get("type")
            if t == "text":
                total += len(blk.get("text", "")) // 4
            elif t == "image":
                total += 1500
            elif t == "tool_use":
                try:
                    total += len(_json.dumps(blk.get("input") or {})) // 4
                except Exception:
                    total += 50
            elif t == "tool_result":
                inner = blk.get("content")
                if isinstance(inner, str):
                    total += len(inner) // 4
                elif isinstance(inner, list):
                    for sub in inner:
                        if not isinstance(sub, dict):
                            continue
                        st = sub.get("type")
                        if st == "text":
                            total += len(sub.get("text", "")) // 4
                        elif st == "image":
                            total += 1500
    return total


def trim_old_tool_outputs(
    messages: list[dict[str, Any]],
    keep_recent: int,
    max_chars: int,
) -> int:
    """Trunca outputs grandes en tool_results más viejos que los últimos
    `keep_recent` mensajes. Preserva pairing tool_use↔tool_result (solo
    sustituye el contenido interno, no quita bloques). Devuelve bytes
    aproximados ahorrados.
    """
    if len(messages) <= keep_recent:
        return 0
    saved = 0
    cutoff = len(messages) - keep_recent
    for m in messages[:cutoff]:
        content = m.get("content")
        if not isinstance(content, list):
            continue
        for blk in content:
            if not isinstance(blk, dict) or blk.get("type") != "tool_result":
                continue
            inner = blk.get("content")
            if isinstance(inner, str):
                if len(inner) > max_chars:
                    saved += len(inner) - max_chars
                    blk["content"] = (
                        inner[: max_chars // 2]
                        + f"\n…[output anterior truncado — {len(inner) - max_chars} chars omitidos]…\n"
                        + inner[-(max_chars // 2):]
                    )
            elif isinstance(inner, list):
                for i, sub in enumerate(inner):
                    if not isinstance(sub, dict) or sub.get("type") != "text":
                        continue
                    txt = sub.get("text", "")
                    if len(txt) > max_chars:
                        saved += len(txt) - max_chars
                        inner[i] = {
                            "type": "text",
                            "text": (
                                txt[: max_chars // 2]
                                + f"\n…[output anterior truncado — {len(txt) - max_chars} chars omitidos]…\n"
                                + txt[-(max_chars // 2):]
                            ),
                        }
    return saved


def trim_old_tool_inputs(
    messages: list[dict[str, Any]],
    keep_recent: int,
    max_chars: int,
) -> int:
    """Trunca inputs string largos en tool_use viejos (ej: `command` de bash
    con un payload masivo, `text` de type_text con un blob). Preserva la
    estructura del bloque tool_use, solo recorta valores string > max_chars.
    """
    if len(messages) <= keep_recent:
        return 0
    saved = 0
    cutoff = len(messages) - keep_recent
    for m in messages[:cutoff]:
        content = m.get("content")
        if not isinstance(content, list):
            continue
        for blk in content:
            if not isinstance(blk, dict) or blk.get("type") != "tool_use":
                continue
            inp = blk.get("input")
            if not isinstance(inp, dict):
                continue
            for k, v in list(inp.items()):
                if isinstance(v, str) and len(v) > max_chars:
                    saved += len(v) - max_chars
                    inp[k] = (
                        v[: max_chars // 2]
                        + f"…[+{len(v) - max_chars} chars omitidos]…"
                        + v[-(max_chars // 2):]
                    )
    return saved


def compact_to_budget(
    messages: list[dict[str, Any]],
    target_tokens: int,
    on_event: EventCallback,
    *,
    aggressive: bool = False,
) -> None:
    """Compacta progresivamente hasta caber en target_tokens. Estrategias en
    orden de menor a mayor pérdida de detalle:
      1. Trim tool_results viejos a CONTEXT_BASH_OUTPUT_TRIM chars
      2. Trim inputs string viejos de tool_use a CONTEXT_TOOL_INPUT_TRIM
      3. Reducir screenshots recientes a 5 (vs default 10)
      4. (aggressive) trim tool_results más fuerte (500 chars) y screenshots a 2
    En ningún paso se eliminan bloques — solo se sustituye contenido pesado
    por placeholders. Esto preserva pairing tool_use↔tool_result y mantiene
    todo el texto del asistente (findings, razonamiento) intacto.
    """
    before = estimate_tokens(messages)
    if before <= target_tokens:
        return

    initial = before
    steps: list[str] = []

    saved = trim_old_tool_outputs(
        messages, CONTEXT_KEEP_RECENT_TURNS, CONTEXT_BASH_OUTPUT_TRIM
    )
    if saved:
        steps.append(f"outputs(-{saved // 4} tok)")

    if estimate_tokens(messages) <= target_tokens:
        on_event({
            "type": "log",
            "message": (
                f"contexto compactado: {initial} → {estimate_tokens(messages)} "
                f"tokens [{', '.join(steps)}]"
            ),
        })
        return

    saved = trim_old_tool_inputs(
        messages, CONTEXT_KEEP_RECENT_TURNS, CONTEXT_TOOL_INPUT_TRIM
    )
    if saved:
        steps.append(f"inputs(-{saved // 4} tok)")

    if estimate_tokens(messages) <= target_tokens:
        on_event({
            "type": "log",
            "message": (
                f"contexto compactado: {initial} → {estimate_tokens(messages)} "
                f"tokens [{', '.join(steps)}]"
            ),
        })
        return

    prune_old_screenshots(messages, keep=5)
    steps.append("screenshots(keep=5)")

    if estimate_tokens(messages) <= target_tokens or not aggressive:
        on_event({
            "type": "log",
            "message": (
                f"contexto compactado: {initial} → {estimate_tokens(messages)} "
                f"tokens [{', '.join(steps)}]"
            ),
        })
        return

    trim_old_tool_outputs(messages, CONTEXT_KEEP_RECENT_TURNS, 500)
    trim_old_tool_inputs(messages, CONTEXT_KEEP_RECENT_TURNS, 150)
    prune_old_screenshots(messages, keep=2)
    steps.append("aggressive(outputs=500,inputs=150,shots=2)")

    on_event({
        "type": "log",
        "message": (
            f"contexto compactado: {initial} → {estimate_tokens(messages)} "
            f"tokens [{', '.join(steps)}]"
        ),
    })
