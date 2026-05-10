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
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import bash_tool
from .agent import run_agent

VNC_PORT = int(os.environ.get("VNC_PORT", "5900"))
NOVNC_DIR = Path(os.environ.get("NOVNC_DIR", "/usr/share/novnc"))

# Token opcional para proteger los endpoints /api/*. Si se define, los clientes
# deben mandar `Authorization: Bearer <token>`. Si no se define, /api/* es abierto.
API_TOKEN = os.environ.get("API_TOKEN", "").strip()

@asynccontextmanager
async def lifespan(_app: "FastAPI"):
    """Arranca servicios opcionales (Telegram bot) al iniciar uvicorn."""
    try:
        from . import telegram_bot
        telegram_bot.start_bot()
    except Exception as e:  # noqa: BLE001
        print(f"[lifespan] error iniciando telegram_bot: {e!r}", flush=True)
    yield


app = FastAPI(title="Agente de navegador", lifespan=lifespan)

# CORS: permite llamadas a /api/* desde cualquier origen
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Sirve los archivos estáticos de noVNC bajo /vnc/
if NOVNC_DIR.exists():
    app.mount("/vnc", StaticFiles(directory=str(NOVNC_DIR), html=True), name="vnc")


def _check_api_auth(authorization: str | None) -> None:
    """Si API_TOKEN está definido, exige Authorization: Bearer <token>."""
    if not API_TOKEN:
        return  # auth desactivada
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="falta Authorization: Bearer <token>")
    token = authorization[len("Bearer "):].strip()
    if token != API_TOKEN:
        raise HTTPException(status_code=403, detail="token inválido")


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
    #log .bash-block {
      display: block;
      background: #050a05;
      border-left: 3px solid #50fa7b;
      padding: 8px 10px;
      margin: 6px 0;
      font-family: 'Consolas', 'Monaco', monospace;
      font-size: 12px;
      color: #c8d3e0;
      white-space: pre-wrap;
      word-break: break-word;
    }
    #log .bash-block .cmd { color: #50fa7b; font-weight: 600; }
    #log .bash-block .stderr { color: #ff79c6; }
    #log .bash-block .exit-ok { color: #6c7086; }
    #log .bash-block .exit-fail { color: #ff5555; }
    #log .bash-block .by-user { color: #4a90e2; font-size: 10px; text-transform: uppercase; }
    #shell-row {
      display: flex;
      gap: 6px;
      padding: 8px 10px;
      background: #0a0a0a;
      border-top: 1px solid #2a2a32;
      font-family: 'Consolas', 'Monaco', monospace;
    }
    #shell-row .prompt { color: #50fa7b; font-weight: bold; padding: 8px 0 0 6px; }
    #shell-input {
      flex: 1;
      background: #050a05;
      color: #c8d3e0;
      border: 1px solid #2a2a32;
      border-radius: 4px;
      padding: 8px 10px;
      font-family: inherit;
      font-size: 13px;
      outline: none;
    }
    #shell-input:focus { border-color: #50fa7b; }
    #shell-send {
      background: #2a2a32;
      color: #50fa7b;
      border: 0;
      border-radius: 4px;
      padding: 0 12px;
      font-family: inherit;
      cursor: pointer;
    }
    #shell-send:hover { background: #3a3a42; }

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
    <div id="shell-row">
      <span class="prompt">$</span>
      <input id="shell-input" placeholder="comando bash (ej: ls /app, df -h, curl ifconfig.me)" />
      <button id="shell-send">run</button>
    </div>
  </div>
  <div class="panel">
    <header><span class="dot"></span> pantalla del navegador (noVNC)</header>
    <iframe src="/vnc/vnc.html?autoconnect=1&resize=scale&reconnect=1&path=websockify&quality=8&compression=2&show_dot=0" id="vnc"></iframe>
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
        } else if (m.type === 'bash_output') {
          const div = document.createElement('div');
          div.className = 'bash-block';

          if (m.from_user) {
            const tag = document.createElement('div');
            tag.className = 'by-user';
            tag.textContent = '— ejecutado por ti —';
            div.appendChild(tag);
          }
          const cmd = document.createElement('div');
          cmd.className = 'cmd';
          cmd.textContent = '$ ' + m.command;
          div.appendChild(cmd);

          if (m.stdout) {
            const out = document.createElement('div');
            out.textContent = m.stdout;
            div.appendChild(out);
          }
          if (m.stderr) {
            const err = document.createElement('div');
            err.className = 'stderr';
            err.textContent = m.stderr;
            div.appendChild(err);
          }
          if (m.error) {
            const er = document.createElement('div');
            er.className = 'exit-fail';
            er.textContent = '⚠ ' + m.error;
            div.appendChild(er);
          } else {
            const e = document.createElement('div');
            e.className = m.exit_code === 0 ? 'exit-ok' : 'exit-fail';
            e.textContent = '[exit ' + m.exit_code + ']';
            div.appendChild(e);
          }
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

    // Terminal — el usuario también puede ejecutar comandos
    const shellInput = document.getElementById('shell-input');
    const shellSend = document.getElementById('shell-send');
    const shellHistory = [];
    let shellHistIdx = -1;

    async function runShell() {
      const cmd = shellInput.value.trim();
      if (!cmd) return;
      shellHistory.push(cmd);
      shellHistIdx = shellHistory.length;
      shellInput.value = '';
      shellSend.disabled = true;
      try {
        const res = await fetch('/shell', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ command: cmd, timeout: 30 })
        });
        if (!res.ok) {
          appendBlock('[shell error] ' + await res.text(), 'err');
        }
        // El resultado viene también por SSE (broadcast), no hace falta pintarlo aquí
      } catch (e) {
        appendBlock('[shell error] ' + e.message, 'err');
      } finally {
        shellSend.disabled = false;
        shellInput.focus();
      }
    }
    shellSend.onclick = runShell;
    shellInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); runShell(); }
      else if (e.key === 'ArrowUp' && shellHistIdx > 0) {
        shellHistIdx--;
        shellInput.value = shellHistory[shellHistIdx];
      } else if (e.key === 'ArrowDown') {
        if (shellHistIdx < shellHistory.length - 1) {
          shellHistIdx++;
          shellInput.value = shellHistory[shellHistIdx];
        } else {
          shellHistIdx = shellHistory.length;
          shellInput.value = '';
        }
      }
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


class ShellBody(BaseModel):
    command: str
    timeout: float = 30.0


@app.post("/task")
def submit_task(body: TaskBody) -> dict[str, Any]:
    """Endpoint usado por el dashboard. Misma semántica que /api/task pero
    sin requisito de auth (ya está detrás del dashboard)."""
    task = (body.task or "").strip()
    if not task:
        raise HTTPException(status_code=400, detail="tarea vacía")
    with _state_lock:
        if _state["busy"]:
            raise HTTPException(status_code=409, detail="ya hay una tarea corriendo")
    _start_task(task)
    return {"ok": True}


@app.post("/shell")
def shell_exec(body: ShellBody) -> dict[str, Any]:
    """Ejecuta un comando bash directamente desde la UI (no a través del agente).

    El resultado se devuelve por HTTP y también se broadcastea por SSE para que
    aparezca en el chat junto al resto del log.
    """
    cmd = (body.command or "").strip()
    if not cmd:
        raise HTTPException(status_code=400, detail="comando vacío")

    result = bash_tool.execute_bash(cmd, timeout=body.timeout)
    _emit({
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
    """Bridge WebSocket → TCP a x11vnc:5900. Reemplaza al binario `websockify`.

    Negocia el subprotocol dinámicamente: si el cliente pide "binary" se lo
    devolvemos; si no, aceptamos sin subprotocol. Algunos proxies (Railway,
    Cloudflare) pueden stripear/transformar la cabecera Sec-WebSocket-Protocol.
    """
    requested = list(websocket.scope.get("subprotocols", []) or [])
    selected: str | None = None
    if "binary" in requested:
        selected = "binary"

    print(f"[ws] connect requested_protos={requested!r} selected={selected!r}", flush=True)

    try:
        await websocket.accept(subprotocol=selected)
    except Exception as e:
        print(f"[ws] accept failed: {e!r}", flush=True)
        return

    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", VNC_PORT)
    except OSError as e:
        print(f"[ws] tcp connect to 127.0.0.1:{VNC_PORT} failed: {e!r}", flush=True)
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
        return

    print(f"[ws] tcp connected to x11vnc:{VNC_PORT}, bridging…", flush=True)

    async def ws_to_tcp() -> None:
        try:
            while True:
                msg = await websocket.receive()
                msg_type = msg.get("type")
                if msg_type == "websocket.disconnect":
                    return
                # noVNC envía bytes; algunas versiones envían texto. Aceptamos ambos.
                data = msg.get("bytes")
                if data is None:
                    text = msg.get("text")
                    if text is None:
                        continue
                    data = text.encode("utf-8")
                writer.write(data)
                await writer.drain()
        except WebSocketDisconnect:
            pass
        except Exception as e:
            print(f"[ws] ws_to_tcp error: {e!r}", flush=True)

    async def tcp_to_ws() -> None:
        try:
            while True:
                data = await reader.read(16384)
                if not data:
                    return
                await websocket.send_bytes(data)
        except Exception as e:
            print(f"[ws] tcp_to_ws error: {e!r}", flush=True)

    try:
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
        print("[ws] bridge closed", flush=True)


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    with _state_lock:
        return {"ok": True, "busy": _state["busy"], "task": _state["task"]}


# ─── API pública (/api/*) ────────────────────────────────────────────────────

def _start_task(task: str) -> None:
    """Lanza el agente en un thread y broadcast el estado por SSE.

    Misma lógica que /task — extraída para reutilizar en /api/task.
    """

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


@app.get("/api")
@app.get("/api/")
def api_root() -> dict[str, Any]:
    """Pequeño descubrimiento del API."""
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
        },
    }


@app.post("/api/task")
def api_submit_task(
    body: TaskBody,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Encola una tarea. Misma semántica que el botón del dashboard.

    Devuelve `409` si ya hay una tarea corriendo (con info de cuál).
    El progreso aparece automáticamente en el dashboard (mismo SSE).
    """
    _check_api_auth(authorization)

    task = (body.task or "").strip()
    if not task:
        raise HTTPException(status_code=400, detail="campo `task` vacío o ausente")

    with _state_lock:
        if _state["busy"]:
            raise HTTPException(
                status_code=409,
                detail={"error": "agente ocupado", "current_task": _state["task"]},
            )

    _start_task(task)
    return {"ok": True, "status": "started", "task": task}


@app.get("/api/status")
def api_status(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _check_api_auth(authorization)
    with _state_lock:
        return {"busy": _state["busy"], "task": _state["task"]}


@app.get("/api/events")
def api_events(authorization: str | None = Header(default=None)) -> StreamingResponse:
    """Mismo stream SSE que /events, pero bajo el namespace /api/."""
    _check_api_auth(authorization)
    return events()


@app.post("/api/shell")
def api_shell(
    body: ShellBody,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _check_api_auth(authorization)
    return shell_exec(body)


@app.post("/api/task/stream")
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
    - `format=json`: SSE con cada evento serializado (texto, acciones, errores, fin).

    Además, los eventos también se broadcastean al dashboard, por lo que la tarea
    aparece en el panel del navegador exactamente como si la hubieras escrito ahí.

    Si el agente está ocupado devuelve 409.
    """
    _check_api_auth(authorization)
    task = (body.task or "").strip()
    if not task:
        raise HTTPException(status_code=400, detail="campo `task` vacío o ausente")
    with _state_lock:
        if _state["busy"]:
            raise HTTPException(
                status_code=409,
                detail={"error": "agente ocupado", "current_task": _state["task"]},
            )

    # Cola exclusiva de este request — el dashboard sigue recibiendo todo via _emit
    client_q: queue.Queue = queue.Queue(maxsize=10000)
    SENTINEL = object()

    def per_request_emit(event: dict[str, Any]) -> None:
        # Broadcast al dashboard (bus global)
        _emit(event)
        # Y a este cliente concreto
        try:
            client_q.put_nowait(event)
        except queue.Full:
            pass  # cliente lento — dropeamos eventos pero el agente sigue

    def runner() -> None:
        _set_busy(True, task)
        per_request_emit({"type": "task_started", "task": task})
        try:
            run_agent(task, per_request_emit)
        except Exception as e:  # noqa: BLE001
            per_request_emit({"type": "error", "message": f"runner crashed: {e!r}"})
        finally:
            _set_busy(False, None)
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
        return None  # eventos que no se incluyen en text mode

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


@app.get("/debug/services")
def debug_services() -> dict[str, Any]:
    """Lista procesos clave + intenta conectar a x11vnc:5900 para diagnosticar."""
    import socket
    import subprocess

    def pgrep(name: str) -> str:
        try:
            r = subprocess.run(
                ["pgrep", "-a", name], capture_output=True, text=True, timeout=2,
            )
            return r.stdout.strip() or "(no procs)"
        except Exception as e:  # noqa: BLE001
            return f"err: {e}"

    def tail(path: str, n: int = 30) -> str:
        try:
            with open(path) as f:
                lines = f.readlines()
            return "".join(lines[-n:])
        except Exception as e:  # noqa: BLE001
            return f"(no se puede leer: {e})"

    def can_connect(host: str, port: int) -> str:
        try:
            with socket.create_connection((host, port), timeout=2):
                return "ok"
        except Exception as e:  # noqa: BLE001
            return f"falla: {e}"

    return {
        "procs": {
            "Xvfb": pgrep("Xvfb"),
            "fluxbox": pgrep("fluxbox"),
            "x11vnc": pgrep("x11vnc"),
            "firefox": pgrep("firefox"),
        },
        "tcp": {
            "x11vnc:5900": can_connect("127.0.0.1", 5900),
        },
        "logs": {
            "xvfb.log": tail("/tmp/xvfb.log"),
            "x11vnc.log": tail("/tmp/x11vnc.log"),
            "fluxbox.log": tail("/tmp/fluxbox.log"),
            "firefox.log": tail("/tmp/firefox.log"),
        },
    }


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
