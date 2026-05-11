"""Lanzador del thread del agente. Encapsula `_start_task` que conecta
los endpoints HTTP con `core.loop.run_agent`.
"""

from __future__ import annotations

import threading
from typing import Any

from ..core.loop import run_agent
from . import state


def start_task(task: str, resume: bool = False) -> None:
    """Lanza el agente en un thread y broadcast el estado por SSE.

    `resume=True` reanuda con la sesión guardada como contexto previo y
    `task` (si no vacío) se añade como instrucción nueva. Si False, arranca
    fresco y limpia el contexto previo.
    """
    state.reset_control()
    prior: list[dict[str, Any]] | None = None
    if resume:
        snap = state.get_session_snapshot()
        msgs = snap.get("messages")
        prior = list(msgs) if msgs else None
        if not prior:
            state.emit({
                "type": "log",
                "message": "no hay sesión previa para reanudar — arrancando fresco",
            })
    else:
        state.clear_session()

    display_task = task if task else "(reanudando sin instrucción nueva)"

    def runner() -> None:
        state.set_busy(True, display_task)
        state.emit({"type": "task_started", "task": display_task})
        final_messages: list[dict[str, Any]] | None = None
        try:
            final_messages = run_agent(
                task,
                state.emit,
                control=state.get_control(),
                prior_messages=prior,
            )
        except Exception as e:  # noqa: BLE001
            state.emit({"type": "error", "message": f"runner crashed: {e!r}"})
        finally:
            state.save_session(final_messages, end_reason="done")
            state.set_busy(False, None)

    threading.Thread(target=runner, daemon=True, name="agent-runner").start()
