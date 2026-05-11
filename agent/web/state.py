"""Estado global del proceso web: clientes SSE, busy/task, control mid-run
del agente (interrupt + injections) y la última sesión persistida (para
RESUME). También el helper `_emit` que hace broadcast a los SSE.
"""

from __future__ import annotations

import datetime
import queue
import threading
from typing import Any

# ─── Clientes SSE (cada GET /events añade su Queue aquí) ─────────────────────

_clients_lock = threading.Lock()
_clients: list[queue.Queue] = []

# ─── Estado de tarea actual ──────────────────────────────────────────────────

_state_lock = threading.Lock()
_state: dict[str, Any] = {"busy": False, "task": None}

# ─── Control mid-run del agente ──────────────────────────────────────────────
# El thread del agente lee de aquí entre turnos.
#   interrupt:  Event() → set para que termine al cerrar el turno actual.
#   injections: Queue() de strings → se inyectan como user message al modelo.
_control: dict[str, Any] = {
    "interrupt": threading.Event(),
    "injections": queue.Queue(maxsize=100),
}

# ─── Contexto persistido entre runs para reanudar (RESUME) ───────────────────
# Se sobrescribe al final de cada run con la lista `messages` resultante.
# Se limpia solo cuando el usuario inicia una tarea fresca con /task.
_session_lock = threading.Lock()
_session: dict[str, Any] = {
    "messages": None,        # list[dict] | None
    "last_task": None,       # str | None
    "ended_at": None,        # timestamp ISO
    "end_reason": None,      # str — done / error / interrupt / refusal
}


# ─── API pública ─────────────────────────────────────────────────────────────

def emit(event: dict[str, Any]) -> None:
    """Broadcast a todos los SSE conectados. Cliente lento → cae."""
    with _clients_lock:
        dead = []
        for q in _clients:
            try:
                q.put_nowait(event)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _clients.remove(q)


def register_sse_client(q: queue.Queue) -> None:
    with _clients_lock:
        _clients.append(q)


def unregister_sse_client(q: queue.Queue) -> None:
    with _clients_lock:
        if q in _clients:
            _clients.remove(q)


def get_state_snapshot() -> dict[str, Any]:
    with _state_lock:
        return dict(_state)


def is_busy() -> bool:
    with _state_lock:
        return _state["busy"]


def set_busy(busy: bool, task: str | None = None) -> None:
    with _state_lock:
        _state["busy"] = busy
        _state["task"] = task
    emit({
        "type": "status",
        "busy": busy,
        "task": task,
        "message": "ejecutando…" if busy else "listo",
    })


def reset_control() -> None:
    """Limpia interrupt + injections. Se llama al iniciar una tarea nueva."""
    _control["interrupt"].clear()
    while not _control["injections"].empty():
        try:
            _control["injections"].get_nowait()
        except queue.Empty:
            break


def get_control() -> dict[str, Any]:
    return _control


def save_session(messages: list[dict[str, Any]] | None, end_reason: str) -> None:
    if not messages:
        return
    ended_at = datetime.datetime.utcnow().isoformat() + "Z"
    with _session_lock:
        _session["messages"] = messages
        _session["ended_at"] = ended_at
        _session["end_reason"] = end_reason
    emit({
        "type": "session_resumable",
        "messages_count": len(messages),
        "ended_at": ended_at,
    })


def clear_session() -> None:
    with _session_lock:
        _session["messages"] = None
        _session["last_task"] = None
        _session["ended_at"] = None
        _session["end_reason"] = None


def get_session_snapshot() -> dict[str, Any]:
    """Snapshot copy del state de sesión — incluye `messages` (por referencia)."""
    with _session_lock:
        msgs = _session["messages"]
        return {
            "messages": msgs,
            "ended_at": _session["ended_at"],
            "end_reason": _session["end_reason"],
            "last_task": _session["last_task"],
        }
