"""FastAPI server: dashboard del agente.

Sirve:
  GET  /          → SPA con chat de tareas + iframe a noVNC
  POST /task      → encola una tarea (409 si ya hay una corriendo)
  GET  /events    → SSE con todos los eventos del agente

Solo permite una tarea a la vez. Cada cliente SSE recibe los mismos eventos
(broadcast). Eventos viejos no se replay-ean a clientes que se conectan tarde.
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .agent import run_agent

VNC_PORT = int(os.environ.get("VNC_PORT", "5900"))
NOVNC_DIR = Path(os.environ.get("NOVNC_DIR", "/usr/share/novnc"))

app = FastAPI(title="Agente de navegador")

# Sirve los archivos estáticos de noVNC bajo /vnc/
if NOVNC_DIR.exists():
    app.mount("/vnc", StaticFiles(directory=str(NOVNC_DIR), html=True), name="vnc")


# ─── Estado global ───────────────────────────────────────────────────────────

_clients_lock = threading.Lock()
_clients: list[queue.Queue] = []
_state_lock = threading.Lock()
_state = {"busy": False, "task": None}


def _emit(event: dict[str, Any]) -> None:
    """Push a todos los clientes SSE conectados."""
    with _clients_lock:
        dead = []
        for q in _clients:
            try:
                q.put_nowait(event)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _clients.remove(q)


def _set_busy(busy: bool, task: str | None = None) -> None:
    with _state_lock:
        _state["busy"] = busy
        _state["task"] = task
    _emit({
        "type": "status",
        "busy": busy,
        "task": task,
        "message": "ejecutando…" if busy else "listo",
    })


# ─── HTML del dashboard ──────────────────────────────────────────────────────

INDEX_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <title>Agente de navegador</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; }
    html, body { margin: 0; padding: 0; height: 100%; }
    body {
      font-family: 'Segoe UI', -apple-system, sans-serif;
      background: #0d0d10;
      color: #e6e6e6;
      display: grid;
      grid-template-columns: minmax(360px, 1fr) 2fr;
      height: 100vh;
      overflow: hidden;
    }
    .panel { display: flex; flex-direction: column; min-width: 0; min-height: 0; border-right: 1px solid #2a2a32; }
    .panel:last-child { border-right: 0; }
    .panel header {
      padding: 10px 14px;
      background: #15151a;
      border-bottom: 1px solid #2a2a32;
      font-size: 13px;
      font-weight: 600;
      letter-spacing: 0.4px;
      text-transform: uppercase;
      color: #9aa0a6;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: #4caf50; }
    .dot.busy { background: #f4b400; animation: pulse 1s infinite; }
    @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }

    #log {
      flex: 1; min-height: 0;
      overflow-y: auto;
      padding: 14px;
      font-family: 'Consolas', 'Monaco', monospace;
      font-size: 13px;
      line-height: 1.5;
      white-space: pre-wrap;
      word-break: break-word;
    }
    #log .agent { color: #d8e3ff; }
    #log .user  { color: #50fa7b; font-weight: 600; }
    #log .action { color: #f1c40f; }
    #log .err   { color: #ff6b6b; }
    #log .sys   { color: #6c7086; font-style: italic; }
    #log .turn  { color: #888; border-top: 1px dashed #2a2a32; padding-top: 8px; margin-top: 8px; display: block; }
    #log .helper { color: #ff79c6; }
    #log .helper-block {
      display: block;
      background: #1d1424;
      border-left: 3px solid #ff79c6;
      padding: 6px 10px;
      margin: 6px 0;
      color: #f5d4ec;
      white-space: pre-wrap;
    }

    #input-row {
      display: flex;
      gap: 6px;
      padding: 10px;
      background: #15151a;
      border-top: 1px solid #2a2a32;
    }
    #task {
      flex: 1;
      background: #0a0a0c;
      color: #fff;
      border: 1px solid #2a2a32;
      border-radius: 6px;
      padding: 10px 12px;
      font-family: inherit;
      font-size: 14px;
      outline: none;
      resize: none;
      min-height: 40px;
      max-height: 120px;
    }
    #task:focus { border-color: #4a90e2; }
    #send {
      background: #4a90e2;
      color: white;
      border: 0;
      border-radius: 6px;
      padding: 0 18px;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.15s;
    }
    #send:hover:not(:disabled) { background: #3a7bc8; }
    #send:disabled { background: #2a2a32; color: #666; cursor: not-allowed; }

    iframe { flex: 1; border: 0; width: 100%; background: #000; }

    #status-bar {
      padding: 6px 14px;
      font-size: 11px;
      background: #15151a;
      border-top: 1px solid #2a2a32;
      color: #6c7086;
      display: flex;
      justify-content: space-between;
    }
  </style>
</head>
<body>
  <div class="panel">
    <header><span class="dot" id="dot"></span> <span id="status-label">listo</span></header>
    <div id="log"></div>
    <div id="status-bar">
      <span id="hint">escribe una tarea y dale Enter</span>
      <span id="conn">conectando…</span>
    </div>
    <div id="input-row">
      <textarea id="task" rows="1" placeholder="Ej: Busca el precio actual de Bitcoin en USD" autofocus></textarea>
      <button id="send">▶ enviar</button>
    </div>
  </div>
  <div class="panel">
    <header><span class="dot"></span> pantalla del navegador (noVNC)</header>
    <iframe src="/vnc/vnc.html?autoconnect=1&resize=scale&reconnect=1&path=websockify" id="vnc"></iframe>
  </div>

  <script>
    const log = document.getElementById('log');
    const taskInput = document.getElementById('task');
    const sendBtn = document.getElementById('send');
    const statusLabel = document.getElementById('status-label');
    const dot = document.getElementById('dot');
    const conn = document.getElementById('conn');

    function append(text, cls) {
      const span = document.createElement('span');
      if (cls) span.className = cls;
      span.textContent = text;
      log.appendChild(span);
      log.scrollTop = log.scrollHeight;
    }
    function appendBlock(text, cls) {
      append(text + '\\n', cls);
    }

    function setBusy(busy) {
      sendBtn.disabled = busy;
      taskInput.disabled = busy;
      statusLabel.textContent = busy ? 'ejecutando…' : 'listo';
      dot.classList.toggle('busy', busy);
      if (!busy) taskInput.focus();
    }

    let evt = null;
    function connectStream() {
      evt = new EventSource('/events');
      evt.onopen = () => { conn.textContent = 'conectado'; };
      evt.onerror = () => {
        conn.textContent = 'reconectando…';
        evt.close();
        setTimeout(connectStream, 1500);
      };
      evt.onmessage = (e) => {
        const m = JSON.parse(e.data);
        if (m.type === 'text') {
          append(m.text, 'agent');
        } else if (m.type === 'action') {
          appendBlock('▸ ' + m.action + ' ' + JSON.stringify(m.input), 'action');
        } else if (m.type === 'tool_result_error') {
          appendBlock('✗ ' + m.message, 'err');
        } else if (m.type === 'error') {
          appendBlock('[error] ' + m.message, 'err');
          setBusy(false);
        } else if (m.type === 'log') {
          appendBlock('· ' + m.message, 'sys');
        } else if (m.type === 'turn_end') {
          // separador entre turnos
          appendBlock('— turno (' + m.stop_reason + ') —', 'turn');
        } else if (m.type === 'done') {
          appendBlock('✓ ' + m.message, 'sys');
          setBusy(false);
        } else if (m.type === 'status') {
          setBusy(m.busy);
        } else if (m.type === 'task_started') {
          appendBlock('\\n>>> ' + m.task, 'user');
        } else if (m.type === 'helper_plan') {
          const div = document.createElement('div');
          div.className = 'helper-block';
          div.textContent = '🧠 Plan del ayudante:\\n' + m.plan;
          log.appendChild(div);
          log.scrollTop = log.scrollHeight;
        } else if (m.type === 'helper_answer') {
          const div = document.createElement('div');
          div.className = 'helper-block';
          div.textContent = '🧠 Consulta: ' + m.question + '\\n→ ' + m.answer;
          log.appendChild(div);
          log.scrollTop = log.scrollHeight;
        }
      };
    }
    connectStream();

    async function submitTask() {
      const task = taskInput.value.trim();
      if (!task) return;
      setBusy(true);
      try {
        const res = await fetch('/task', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ task })
        });
        if (!res.ok) {
          const txt = await res.text();
          appendBlock('[error] ' + txt, 'err');
          setBusy(false);
          return;
        }
        taskInput.value = '';
      } catch (e) {
        appendBlock('[error] ' + e.message, 'err');
        setBusy(false);
      }
    }
    sendBtn.onclick = submitTask;
    taskInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        submitTask();
      }
    });

    // Auto-resize del textarea
    taskInput.addEventListener('input', () => {
      taskInput.style.height = 'auto';
      taskInput.style.height = Math.min(120, taskInput.scrollHeight) + 'px';
    });
  </script>
</body>
</html>
"""


# ─── Endpoints ───────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return INDEX_HTML


class TaskBody(BaseModel):
    task: str


@app.post("/task")
def submit_task(body: TaskBody) -> dict[str, Any]:
    task = (body.task or "").strip()
    if not task:
        raise HTTPException(status_code=400, detail="tarea vacía")

    with _state_lock:
        if _state["busy"]:
            raise HTTPException(status_code=409, detail="ya hay una tarea corriendo")

    def runner() -> None:
        _set_busy(True, task)
        _emit({"type": "task_started", "task": task})
        try:
            run_agent(task, _emit)
        except Exception as e:  # noqa: BLE001
            _emit({"type": "error", "message": f"runner crashed: {e!r}"})
        finally:
            _set_busy(False, None)

    threading.Thread(target=runner, daemon=True, name="agent-runner").start()
    return {"ok": True}


@app.get("/events")
def events() -> StreamingResponse:
    client_q: queue.Queue = queue.Queue(maxsize=1000)
    with _clients_lock:
        _clients.append(client_q)

    def gen():
        try:
            # Estado inicial al conectar
            with _state_lock:
                snapshot = dict(_state)
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
            with _clients_lock:
                if client_q in _clients:
                    _clients.remove(client_q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.websocket("/websockify")
async def websockify_bridge(websocket: WebSocket) -> None:
    """Bridge WebSocket → TCP a x11vnc:5900.

    Reemplaza al binario `websockify`. noVNC envía frames binarios sobre WS;
    nosotros los pipe-amos a un socket TCP de x11vnc en localhost.
    """
    await websocket.accept(subprotocol="binary")
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", VNC_PORT)
    except OSError:
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
        return

    async def ws_to_tcp() -> None:
        try:
            while True:
                data = await websocket.receive_bytes()
                writer.write(data)
                await writer.drain()
        except WebSocketDisconnect:
            pass
        except Exception:
            pass

    async def tcp_to_ws() -> None:
        try:
            while True:
                data = await reader.read(8192)
                if not data:
                    return
                await websocket.send_bytes(data)
        except Exception:
            pass

    try:
        # Cualquiera que termine cierra el otro
        done, pending = await asyncio.wait(
            [asyncio.create_task(ws_to_tcp()), asyncio.create_task(tcp_to_ws())],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        try:
            await websocket.close()
        except Exception:
            pass


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    with _state_lock:
        return {"ok": True, "busy": _state["busy"], "task": _state["task"]}


@app.get("/debug/computer-use")
def debug_computer_use() -> dict[str, Any]:
    """Diagnóstico: stream raw con la combinación tools+beta del agente.

    Recoge los primeros eventos SSE y los devuelve como texto plano para que
    veas qué responde el proxy con esa request exacta.
    """
    import httpx

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
    url = f"{base_url}/v1/messages"

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "computer-use-2025-01-24",
        "content-type": "application/json",
    }
    body = {
        "model": os.environ.get("CLAUDE_MODEL", "claude-opus-4-7"),
        "max_tokens": 512,
        "stream": True,
        "tools": [{
            "type": "computer_20250124",
            "name": "computer",
            "display_width_px": 1280,
            "display_height_px": 800,
            "display_number": 1,
        }],
        "messages": [{"role": "user", "content": "di hola en una palabra"}],
    }

    try:
        with httpx.Client(timeout=30.0) as h:
            with h.stream("POST", url, headers=headers, json=body) as r:
                response_headers = dict(r.headers)
                status = r.status_code
                # Recolecta primeros 8000 chars del body en streaming
                buf = []
                total = 0
                for chunk in r.iter_text():
                    buf.append(chunk)
                    total += len(chunk)
                    if total > 8000:
                        buf.append("\n…[truncado]")
                        break
                body_text = "".join(buf)
        return {
            "url": url,
            "request_headers_sent": list(headers.keys()),
            "status": status,
            "response_headers": response_headers,
            "response_body": body_text,
        }
    except Exception as e:  # noqa: BLE001
        return {"url": url, "error": f"{type(e).__name__}: {e}"}


@app.get("/debug/simple-stream")
def debug_simple_stream() -> dict[str, Any]:
    """Diagnóstico mínimo: stream sin tools ni beta. Para verificar el proxy base."""
    import httpx

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
    url = f"{base_url}/v1/messages"

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": os.environ.get("CLAUDE_MODEL", "claude-opus-4-7"),
        "max_tokens": 256,
        "stream": True,
        "messages": [{"role": "user", "content": "Hola"}],
    }

    try:
        with httpx.Client(timeout=30.0) as h:
            with h.stream("POST", url, headers=headers, json=body) as r:
                status = r.status_code
                response_headers = dict(r.headers)
                buf = []
                total = 0
                for chunk in r.iter_text():
                    buf.append(chunk)
                    total += len(chunk)
                    if total > 4000:
                        buf.append("\n…[truncado]")
                        break
        return {
            "url": url,
            "status": status,
            "response_headers": response_headers,
            "response_body": "".join(buf),
        }
    except Exception as e:  # noqa: BLE001
        return {"url": url, "error": f"{type(e).__name__}: {e}"}
