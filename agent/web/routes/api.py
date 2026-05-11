"""Espejo /api/* del dashboard, con auth opcional. Reutiliza handlers de
`dashboard` excepto los streaming, donde tenemos uno propio (`/api/task/stream`)
con cola exclusiva del request.
"""

from __future__ import annotations

import json
import queue
import threading
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import StreamingResponse

from ...config import API_TOKEN
from ...core.loop import run_agent
from .. import state
from ..auth import check_api_auth
from ..models import InjectBody, ResumeBody, ShellBody, TaskBody
from . import dashboard

router = APIRouter(prefix="/api")


@router.get("")
@router.get("/")
def api_root() -> dict[str, Any]:
    return {
        "name": "AgentHelper API",
        "version": "1",
        "auth": "Bearer (opcional)" if API_TOKEN else "abierta",
        "endpoints": {
            "POST /api/task":         "encola una tarea async — body {task}; respuesta inmediata",
            "POST /api/task/stream":  "encola una tarea y stremea texto en vivo (text/plain). ?actions=1 para acciones inline. ?format=json para SSE completo",
            "GET  /api/status":       "estado actual {busy, task}",
            "GET  /api/events":       "stream SSE global (broadcast del dashboard)",
            "POST /api/shell":        "ejecuta un comando bash — body {command, timeout?}",
            "POST /api/interrupt":    "detiene la tarea actual al final del turno en curso",
            "POST /api/inject":       "inyecta un mensaje al agente entre turnos — body {message}",
            "GET  /api/session":      "info de la última sesión (si es resumable)",
            "POST /api/resume":       "reanuda la última sesión — body {task} opcional con nueva instrucción",
        },
    }


@router.post("/task")
def api_submit_task(
    body: TaskBody,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    check_api_auth(authorization)
    task = (body.task or "").strip()
    if not task:
        raise HTTPException(status_code=400, detail="campo `task` vacío o ausente")
    if state.is_busy():
        snap = state.get_state_snapshot()
        raise HTTPException(
            status_code=409,
            detail={"error": "agente ocupado", "current_task": snap["task"]},
        )
    from ..runner import start_task
    start_task(task)
    return {"ok": True, "status": "started", "task": task}


@router.get("/status")
def api_status(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    check_api_auth(authorization)
    snap = state.get_state_snapshot()
    return {"busy": snap["busy"], "task": snap["task"]}


@router.get("/events")
def api_events(authorization: str | None = Header(default=None)) -> StreamingResponse:
    """Mismo stream SSE que /events, pero bajo /api/."""
    check_api_auth(authorization)
    return dashboard.events()


@router.post("/shell")
def api_shell(
    body: ShellBody,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    check_api_auth(authorization)
    return dashboard.shell_exec(body)


@router.post("/interrupt")
def api_interrupt(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    check_api_auth(authorization)
    return dashboard.interrupt()


@router.post("/inject")
def api_inject(
    body: InjectBody,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    check_api_auth(authorization)
    return dashboard.inject(body)


@router.get("/session")
def api_session(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    check_api_auth(authorization)
    return dashboard.session_state()


@router.post("/resume")
def api_resume(
    body: ResumeBody,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    check_api_auth(authorization)
    return dashboard.resume(body)


@router.post("/task/stream")
def api_task_stream(
    body: TaskBody,
    actions: bool = Query(default=False, description="incluir líneas de acción inline"),
    format: str = Query(default="text", description="text | json"),
    authorization: str | None = Header(default=None),
) -> StreamingResponse:
    """Encola una tarea y mantiene la conexión abierta streameando lo que va
    diciendo el agente en tiempo real.

    - `format=text` (default): plain text, solo el texto del agente.
    - `format=text&actions=1`: como text pero con líneas `[action: ...]`.
    - `format=json`: SSE con cada evento serializado.

    Además, los eventos también se broadcastean al dashboard, por lo que la
    tarea aparece en el panel del navegador exactamente como si la hubieras
    escrito ahí.
    """
    check_api_auth(authorization)
    task = (body.task or "").strip()
    if not task:
        raise HTTPException(status_code=400, detail="campo `task` vacío o ausente")
    if state.is_busy():
        snap = state.get_state_snapshot()
        raise HTTPException(
            status_code=409,
            detail={"error": "agente ocupado", "current_task": snap["task"]},
        )

    client_q: queue.Queue = queue.Queue(maxsize=10000)
    SENTINEL = object()

    def per_request_emit(event: dict[str, Any]) -> None:
        state.emit(event)
        try:
            client_q.put_nowait(event)
        except queue.Full:
            pass  # cliente lento — dropeamos eventos, el agente sigue

    state.reset_control()
    state.clear_session()

    def runner() -> None:
        state.set_busy(True, task)
        per_request_emit({"type": "task_started", "task": task})
        final_messages: list[dict[str, Any]] | None = None
        try:
            final_messages = run_agent(task, per_request_emit, control=state.get_control())
        except Exception as e:  # noqa: BLE001
            per_request_emit({"type": "error", "message": f"runner crashed: {e!r}"})
        finally:
            state.save_session(final_messages, end_reason="done")
            state.set_busy(False, None)
            try:
                client_q.put_nowait({"_sentinel_": SENTINEL})
            except queue.Full:
                pass

    threading.Thread(target=runner, daemon=True, name="agent-runner-stream").start()

    fmt = (format or "text").lower()
    media_type = "text/event-stream" if fmt == "json" else "text/plain; charset=utf-8"

    def render_text(event: dict[str, Any]) -> str | None:
        t = event.get("type")
        if t == "text":
            return event.get("text", "")
        if t == "action" and actions:
            args = event.get("input") or {}
            args_str = json.dumps(args, ensure_ascii=False)
            return f"\n[action: {event.get('action')} {args_str}]\n"
        if t == "tool_result_error":
            return f"\n[error tool: {event.get('message')}]\n"
        if t == "bash_output" and actions:
            cmd = event.get("command", "")
            ec = event.get("exit_code")
            return f"\n[bash $ {cmd} → exit {ec}]\n"
        if t == "error":
            return f"\n\n[error] {event.get('message')}\n"
        if t == "done":
            return f"\n\n[done] {event.get('message', '')}\n"
        return None

    def gen():
        while True:
            try:
                event = client_q.get(timeout=20)
            except queue.Empty:
                if fmt == "json":
                    yield ": heartbeat\n\n"
                continue

            if event.get("_sentinel_") is SENTINEL:
                return

            if fmt == "json":
                yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
            else:
                chunk = render_text(event)
                if chunk:
                    yield chunk

    return StreamingResponse(
        gen(),
        media_type=media_type,
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
