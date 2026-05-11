"""Routes del dashboard (sin auth): UI, /task, /events, /shell, /interrupt,
/inject, /session, /resume, /healthz. Los `/api/*` reutilizan estos
handlers vía `api.py`.
"""

from __future__ import annotations

import json
import queue
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse

from ... import bash_tool
from .. import state
from ..models import InjectBody, ResumeBody, ShellBody, TaskBody
from ..runner import start_task

router = APIRouter()

# Cargar HTML una vez al import (no en cada request).
_UI_DIR = Path(__file__).resolve().parent.parent / "ui"
_INDEX_HTML = (_UI_DIR / "index.html").read_text(encoding="utf-8")


@router.get("/", response_class=HTMLResponse)
def index() -> str:
    return _INDEX_HTML


@router.post("/task")
def submit_task(body: TaskBody) -> dict[str, Any]:
    """Encola una tarea. 409 si ya hay una corriendo."""
    task = (body.task or "").strip()
    if not task:
        raise HTTPException(status_code=400, detail="tarea vacía")
    if state.is_busy():
        raise HTTPException(status_code=409, detail="ya hay una tarea corriendo")
    start_task(task)
    return {"ok": True}


@router.post("/shell")
def shell_exec(body: ShellBody) -> dict[str, Any]:
    """Ejecuta un comando bash directo (no a través del agente).

    El resultado se devuelve por HTTP y se broadcastea por SSE para que
    aparezca en el chat junto al resto del log.
    """
    cmd = (body.command or "").strip()
    if not cmd:
        raise HTTPException(status_code=400, detail="comando vacío")

    result = bash_tool.execute_bash(cmd, timeout=body.timeout)
    state.emit({
        "type": "bash_output",
        "command": cmd,
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "exit_code": result["exit_code"],
        "error": result.get("error"),
        "from_user": True,
    })
    return {
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "exit_code": result["exit_code"],
        "error": result.get("error"),
    }


@router.get("/events")
def events() -> StreamingResponse:
    client_q: queue.Queue = queue.Queue(maxsize=1000)
    state.register_sse_client(client_q)

    def gen():
        try:
            snapshot = state.get_state_snapshot()
            yield "data: " + json.dumps({
                "type": "status",
                "busy": snapshot["busy"],
                "task": snapshot["task"],
                "message": "ejecutando…" if snapshot["busy"] else "listo",
            }) + "\n\n"

            while True:
                try:
                    event = client_q.get(timeout=15)
                    yield "data: " + json.dumps(event) + "\n\n"
                except queue.Empty:
                    yield ": heartbeat\n\n"
        finally:
            state.unregister_sse_client(client_q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/healthz")
def healthz() -> dict[str, Any]:
    snap = state.get_state_snapshot()
    return {"ok": True, "busy": snap["busy"], "task": snap["task"]}


@router.post("/interrupt")
def interrupt() -> dict[str, Any]:
    """Marca la tarea actual para que termine limpiamente al final del turno."""
    if not state.is_busy():
        return {"ok": False, "reason": "no hay tarea en curso"}
    state.get_control()["interrupt"].set()
    state.emit({"type": "log", "message": "interrupción solicitada — terminando al final del turno"})
    return {"ok": True}


@router.get("/session")
def session_state() -> dict[str, Any]:
    """Indica si hay contexto resumable disponible (para que la UI muestre RESUME)."""
    snap = state.get_session_snapshot()
    msgs = snap.get("messages")
    return {
        "resumable": bool(msgs),
        "messages_count": len(msgs) if msgs else 0,
        "ended_at": snap.get("ended_at"),
        "end_reason": snap.get("end_reason"),
    }


@router.post("/resume")
def resume(body: ResumeBody) -> dict[str, Any]:
    """Reanuda la última sesión, opcionalmente con una instrucción nueva.

    Si no hay sesión previa, devuelve 400. La sesión persiste en memoria
    hasta que el usuario inicie una tarea fresca con /task o reinicie el
    contenedor.
    """
    if state.is_busy():
        raise HTTPException(status_code=409, detail="ya hay una tarea corriendo")
    snap = state.get_session_snapshot()
    if not snap.get("messages"):
        raise HTTPException(status_code=400, detail="no hay sesión previa para reanudar")
    follow_up = (body.task or "").strip()
    start_task(follow_up, resume=True)
    return {"ok": True, "resumed": True, "follow_up": follow_up}


@router.post("/inject")
def inject(body: InjectBody) -> dict[str, Any]:
    """Encola un mensaje del usuario para inyectar entre turnos del agente.

    Se inserta como mensaje user con prefijo claro de "USUARIO INTERRUMPE…"
    para que el agente entienda que es input mid-task del operador.
    """
    msg = (body.message or "").strip()
    if not msg:
        raise HTTPException(status_code=400, detail="mensaje vacío")
    if not state.is_busy():
        raise HTTPException(status_code=409, detail="no hay tarea en curso")
    try:
        state.get_control()["injections"].put_nowait(msg)
    except queue.Full:
        raise HTTPException(status_code=503, detail="cola de inyecciones llena")
    state.emit({"type": "user_inject_queued", "message": msg})
    return {"ok": True}
