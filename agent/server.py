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

# Control mid-run del agente: el thread del agente lee de aquí entre turnos.
#   interrupt:  Event() → set para que termine al cerrar el turno actual.
#   injections: Queue() de strings → se inyectan como user message al modelo.
_control: dict[str, Any] = {
    "interrupt": threading.Event(),
    "injections": queue.Queue(maxsize=100),
}


def _reset_control() -> None:
    """Limpia interrupt + injections. Se llama al iniciar una tarea nueva."""
    _control["interrupt"].clear()
    while not _control["injections"].empty():
        try:
            _control["injections"].get_nowait()
        except queue.Empty:
            break


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
  <title>AGENTHELPER // pentest console</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after { box-sizing: border-box; }
    html, body { margin: 0; padding: 0; height: 100%; }
    :root {
      --bg: #050807;
      --bg-2: #0a0f0d;
      --bg-3: #101715;
      --border: #1a3a2a;
      --border-soft: #142822;
      --fg: #c8f0d4;
      --green: #00ff9c;
      --green-dim: #4ddb89;
      --green-glow: rgba(0,255,156,0.18);
      --cyan: #5cf3ff;
      --amber: #ffcc55;
      --red: #ff4757;
      --magenta: #ff5cad;
      --gray: #5e7b6e;
      --font-mono: 'JetBrains Mono', 'Fira Code', 'Consolas', 'Monaco', monospace;
    }
    body {
      font-family: var(--font-mono);
      background: var(--bg);
      color: var(--fg);
      display: grid;
      grid-template-columns: minmax(420px, 1fr) 1.6fr;
      height: 100vh;
      overflow: hidden;
      font-size: 13px;
      line-height: 1.55;
      /* Subtle scanline overlay */
      background-image:
        linear-gradient(rgba(0,255,156,0.015) 50%, transparent 50%);
      background-size: 100% 3px;
    }
    .panel {
      display: flex;
      flex-direction: column;
      min-width: 0;
      min-height: 0;
      border-right: 1px solid var(--border);
    }
    .panel:last-child { border-right: 0; }

    /* ─── Header con título estilo terminal ─── */
    .panel header {
      padding: 10px 14px;
      background: var(--bg-2);
      border-bottom: 1px solid var(--border);
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 1.5px;
      text-transform: uppercase;
      color: var(--green-dim);
      display: flex;
      align-items: center;
      gap: 10px;
      position: relative;
    }
    .panel header::before {
      content: '';
      position: absolute;
      top: 0; left: 0; right: 0;
      height: 1px;
      background: linear-gradient(90deg, transparent, var(--green) 50%, transparent);
      opacity: 0.4;
    }
    .panel header .label {
      color: var(--green);
      text-shadow: 0 0 6px var(--green-glow);
    }
    .panel header .meta {
      margin-left: auto;
      font-size: 10px;
      color: var(--gray);
      letter-spacing: 1px;
    }
    .dot {
      width: 7px; height: 7px;
      border-radius: 50%;
      background: var(--green);
      box-shadow: 0 0 8px var(--green);
    }
    .dot.busy {
      background: var(--amber);
      box-shadow: 0 0 8px var(--amber);
      animation: pulse 0.9s infinite;
    }
    @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.35} }

    /* ─── Log central ─── */
    #log {
      flex: 1;
      min-height: 0;
      overflow-y: auto;
      padding: 14px 14px 8px 14px;
      font-family: var(--font-mono);
      font-size: 12.5px;
      line-height: 1.55;
      white-space: pre-wrap;
      word-break: break-word;
      scrollbar-width: thin;
      scrollbar-color: var(--border) transparent;
    }
    #log::-webkit-scrollbar { width: 6px; }
    #log::-webkit-scrollbar-track { background: transparent; }
    #log::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }

    #log .agent  { color: var(--fg); }
    #log .user   { color: var(--green); font-weight: 700; text-shadow: 0 0 6px var(--green-glow); }
    #log .action { color: var(--amber); }
    #log .err    { color: var(--red); }
    #log .sys    { color: var(--gray); font-style: italic; }
    #log .turn   {
      color: var(--gray);
      border-top: 1px dashed var(--border);
      padding-top: 6px;
      margin-top: 8px;
      display: block;
      font-size: 10px;
      letter-spacing: 1.2px;
      text-transform: uppercase;
    }
    #log .helper-block {
      display: block;
      background: var(--bg-3);
      border-left: 2px solid var(--magenta);
      padding: 6px 10px;
      margin: 6px 0;
      color: var(--magenta);
      white-space: pre-wrap;
    }
    #log .bash-block {
      display: block;
      background: #030504;
      border: 1px solid var(--border-soft);
      border-left: 2px solid var(--green);
      padding: 8px 10px;
      margin: 6px 0;
      font-family: var(--font-mono);
      font-size: 12px;
      color: var(--fg);
      white-space: pre-wrap;
      word-break: break-word;
      box-shadow: 0 0 0 1px rgba(0,255,156,0.04);
    }
    #log .bash-block .cmd { color: var(--green); font-weight: 700; }
    #log .bash-block .cmd::before { content: '┌─ '; color: var(--gray); font-weight: 400; }
    #log .bash-block .stderr { color: var(--magenta); }
    #log .bash-block .exit-ok { color: var(--gray); font-size: 11px; }
    #log .bash-block .exit-fail { color: var(--red); font-size: 11px; }
    #log .bash-block .by-user {
      color: var(--cyan);
      font-size: 9px;
      text-transform: uppercase;
      letter-spacing: 1.5px;
      margin-bottom: 4px;
    }

    /* ─── Status bar ─── */
    #status-bar {
      padding: 5px 14px;
      font-size: 10px;
      background: var(--bg-2);
      border-top: 1px solid var(--border);
      color: var(--gray);
      display: flex;
      justify-content: space-between;
      letter-spacing: 1px;
      text-transform: uppercase;
    }
    #status-bar #conn.live { color: var(--green); }
    #status-bar #conn.reconnecting { color: var(--amber); }

    /* ─── Input ─── */
    #input-row {
      display: flex;
      gap: 0;
      padding: 8px;
      background: var(--bg-2);
      border-top: 1px solid var(--border);
      position: relative;
    }
    #input-row::before {
      content: '▶';
      position: absolute;
      left: 18px; top: 16px;
      color: var(--green);
      font-size: 11px;
      pointer-events: none;
      text-shadow: 0 0 6px var(--green-glow);
    }
    #task {
      flex: 1;
      background: var(--bg);
      color: var(--fg);
      border: 1px solid var(--border);
      border-radius: 0;
      padding: 10px 12px 10px 32px;
      font-family: var(--font-mono);
      font-size: 13px;
      outline: none;
      resize: none;
      min-height: 42px;
      max-height: 140px;
      caret-color: var(--green);
    }
    #task:focus {
      border-color: var(--green);
      box-shadow: 0 0 0 1px var(--green), 0 0 12px var(--green-glow);
    }
    #task:disabled { opacity: 0.45; }

    #send, #stop {
      background: transparent;
      color: var(--green);
      border: 1px solid var(--green);
      border-left: 0;
      border-radius: 0;
      padding: 0 18px;
      font-family: var(--font-mono);
      font-weight: 700;
      font-size: 12px;
      letter-spacing: 2px;
      cursor: pointer;
      transition: all 0.12s;
      text-shadow: 0 0 4px var(--green-glow);
    }
    #send:hover:not(:disabled) {
      background: var(--green);
      color: var(--bg);
      box-shadow: 0 0 12px var(--green-glow);
      text-shadow: none;
    }
    #send:disabled {
      color: var(--gray);
      border-color: var(--border);
      cursor: not-allowed;
      text-shadow: none;
    }
    /* INJECT mode (cuando busy): cambia a amber */
    #send.inject {
      color: var(--amber);
      border-color: var(--amber);
      text-shadow: 0 0 4px rgba(255,204,85,0.3);
    }
    #send.inject:hover:not(:disabled) {
      background: var(--amber);
      color: var(--bg);
      box-shadow: 0 0 12px rgba(255,204,85,0.4);
      text-shadow: none;
    }
    /* STOP button — solo visible durante busy */
    #stop {
      display: none;
      color: var(--red);
      border-color: var(--red);
      text-shadow: 0 0 4px rgba(255,71,87,0.3);
      padding: 0 14px;
    }
    #stop.visible { display: block; }
    #stop:hover {
      background: var(--red);
      color: var(--bg);
      box-shadow: 0 0 12px rgba(255,71,87,0.4);
      text-shadow: none;
    }
    #stop.armed {
      background: var(--red);
      color: var(--bg);
      animation: pulse-fast 0.6s steps(2) infinite;
      pointer-events: none;
    }
    @keyframes pulse-fast { 50% { opacity: 0.6; } }

    /* Inyección del usuario en el log */
    #log .inject-block {
      display: block;
      background: #1a1505;
      border-left: 2px solid var(--amber);
      padding: 6px 10px;
      margin: 6px 0;
      color: var(--amber);
      white-space: pre-wrap;
    }
    #log .inject-applied {
      color: var(--amber);
      font-size: 10px;
      letter-spacing: 1.5px;
      text-transform: uppercase;
      display: block;
      margin: 2px 0;
    }

    /* ─── noVNC iframe ─── */
    iframe {
      flex: 1;
      border: 0;
      width: 100%;
      background: #000;
    }

    /* ─── Cursor parpadeante decorativo en el log ─── */
    #cursor {
      display: inline-block;
      width: 8px;
      height: 14px;
      background: var(--green);
      vertical-align: text-bottom;
      animation: blink 1s steps(2) infinite;
      box-shadow: 0 0 6px var(--green-glow);
      margin-left: 2px;
    }
    @keyframes blink { 50% { opacity: 0; } }
  </style>
</head>
<body>
  <div class="panel">
    <header>
      <span class="dot" id="dot"></span>
      <span class="label">[ AGENTHELPER ]</span>
      <span id="status-label">idle</span>
      <span class="meta" id="header-meta">opus-4.7 // session live</span>
    </header>
    <div id="log"><span id="cursor"></span></div>
    <div id="status-bar">
      <span id="hint">enter task // shift+enter for newline</span>
      <span id="conn" class="reconnecting">linking…</span>
    </div>
    <div id="input-row">
      <textarea id="task" rows="1" placeholder="target / task..." autofocus></textarea>
      <button id="send">EXEC</button>
      <button id="stop" title="Detener tarea actual al final del turno">STOP</button>
    </div>
  </div>
  <div class="panel">
    <header>
      <span class="dot"></span>
      <span class="label">[ TARGET DISPLAY ]</span>
      <span class="meta">novnc :: x11vnc → xvfb :1</span>
    </header>
    <iframe src="/vnc/vnc.html?autoconnect=1&resize=scale&reconnect=1&path=websockify&quality=8&compression=2&show_dot=0" id="vnc"></iframe>
  </div>

  <script>
    const log = document.getElementById('log');
    const cursor = document.getElementById('cursor');
    const taskInput = document.getElementById('task');
    const sendBtn = document.getElementById('send');
    const stopBtn = document.getElementById('stop');
    const statusLabel = document.getElementById('status-label');
    const dot = document.getElementById('dot');
    const conn = document.getElementById('conn');
    let isBusy = false;

    function appendNode(node) {
      // Insertar antes del cursor para que siempre quede al final
      log.insertBefore(node, cursor);
      log.scrollTop = log.scrollHeight;
    }
    function append(text, cls) {
      const span = document.createElement('span');
      if (cls) span.className = cls;
      span.textContent = text;
      appendNode(span);
    }
    function appendBlock(text, cls) {
      append(text + '\\n', cls);
    }

    function setBusy(busy) {
      isBusy = busy;
      // Input siempre habilitado: cuando busy → modo INJECT
      taskInput.disabled = false;
      sendBtn.disabled = false;
      sendBtn.textContent = busy ? 'INJECT' : 'EXEC';
      sendBtn.classList.toggle('inject', busy);
      stopBtn.classList.toggle('visible', busy);
      stopBtn.classList.remove('armed');
      taskInput.placeholder = busy
        ? 'inject instruction (will reach agent at next turn)…'
        : 'target / task...';
      statusLabel.textContent = busy ? 'executing' : 'idle';
      dot.classList.toggle('busy', busy);
      if (!busy) taskInput.focus();
    }

    let evt = null;
    function connectStream() {
      evt = new EventSource('/events');
      evt.onopen = () => {
        conn.textContent = 'linked';
        conn.className = 'live';
      };
      evt.onerror = () => {
        conn.textContent = 'reconnecting…';
        conn.className = 'reconnecting';
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
          appendBlock('[err] ' + m.message, 'err');
          setBusy(false);
        } else if (m.type === 'log') {
          appendBlock('· ' + m.message, 'sys');
        } else if (m.type === 'turn_end') {
          appendBlock('── turn end :: ' + m.stop_reason + ' ──', 'turn');
        } else if (m.type === 'done') {
          appendBlock('✓ ' + m.message, 'sys');
          setBusy(false);
        } else if (m.type === 'status') {
          setBusy(m.busy);
        } else if (m.type === 'task_started') {
          appendBlock('\\n>>> ' + m.task, 'user');
        } else if (m.type === 'user_inject_queued') {
          const div = document.createElement('div');
          div.className = 'inject-block';
          div.textContent = '>> [inject queued] ' + m.message;
          appendNode(div);
        } else if (m.type === 'user_inject_applied') {
          appendBlock('   ↳ inject delivered to agent', 'inject-applied');
        } else if (m.type === 'helper_plan') {
          const div = document.createElement('div');
          div.className = 'helper-block';
          div.textContent = '[plan]\\n' + m.plan;
          appendNode(div);
        } else if (m.type === 'helper_answer') {
          const div = document.createElement('div');
          div.className = 'helper-block';
          div.textContent = '[?] ' + m.question + '\\n→ ' + m.answer;
          appendNode(div);
        } else if (m.type === 'bash_output') {
          const div = document.createElement('div');
          div.className = 'bash-block';

          if (m.from_user) {
            const tag = document.createElement('div');
            tag.className = 'by-user';
            tag.textContent = '── manual ──';
            div.appendChild(tag);
          }
          const cmd = document.createElement('div');
          cmd.className = 'cmd';
          cmd.textContent = m.command;
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
            er.textContent = '└─ ✗ ' + m.error;
            div.appendChild(er);
          } else {
            const e = document.createElement('div');
            e.className = m.exit_code === 0 ? 'exit-ok' : 'exit-fail';
            e.textContent = '└─ exit ' + m.exit_code;
            div.appendChild(e);
          }
          appendNode(div);
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
          appendBlock('[err] ' + txt, 'err');
          setBusy(false);
          return;
        }
        taskInput.value = '';
        taskInput.style.height = 'auto';
      } catch (e) {
        appendBlock('[err] ' + e.message, 'err');
        setBusy(false);
      }
    }

    async function injectMessage() {
      const message = taskInput.value.trim();
      if (!message) return;
      try {
        const res = await fetch('/inject', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message })
        });
        if (!res.ok) {
          const txt = await res.text();
          appendBlock('[inject err] ' + txt, 'err');
          return;
        }
        taskInput.value = '';
        taskInput.style.height = 'auto';
      } catch (e) {
        appendBlock('[inject err] ' + e.message, 'err');
      }
    }

    async function stopTask() {
      if (!isBusy) return;
      stopBtn.classList.add('armed');
      try {
        const res = await fetch('/interrupt', { method: 'POST' });
        if (!res.ok) {
          appendBlock('[stop err] ' + await res.text(), 'err');
          stopBtn.classList.remove('armed');
        }
      } catch (e) {
        appendBlock('[stop err] ' + e.message, 'err');
        stopBtn.classList.remove('armed');
      }
    }

    function dispatchSubmit() {
      if (isBusy) injectMessage();
      else submitTask();
    }

    sendBtn.onclick = dispatchSubmit;
    stopBtn.onclick = stopTask;
    taskInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        dispatchSubmit();
      }
    });

    // Auto-resize del textarea
    taskInput.addEventListener('input', () => {
      taskInput.style.height = 'auto';
      taskInput.style.height = Math.min(140, taskInput.scrollHeight) + 'px';
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


class InjectBody(BaseModel):
    message: str


@app.post("/interrupt")
def interrupt() -> dict[str, Any]:
    """Marca la tarea actual para que termine limpiamente al final del turno."""
    with _state_lock:
        if not _state["busy"]:
            return {"ok": False, "reason": "no hay tarea en curso"}
    _control["interrupt"].set()
    _emit({"type": "log", "message": "interrupción solicitada — terminando al final del turno"})
    return {"ok": True}


@app.post("/inject")
def inject(body: InjectBody) -> dict[str, Any]:
    """Encola un mensaje del usuario para inyectar entre turnos del agente.

    Se inserta como mensaje user con prefijo claro de "USUARIO INTERRUMPE…"
    para que el agente entienda que es input mid-task del operador.
    """
    msg = (body.message or "").strip()
    if not msg:
        raise HTTPException(status_code=400, detail="mensaje vacío")
    with _state_lock:
        if not _state["busy"]:
            raise HTTPException(status_code=409, detail="no hay tarea en curso")
    try:
        _control["injections"].put_nowait(msg)
    except queue.Full:
        raise HTTPException(status_code=503, detail="cola de inyecciones llena")
    _emit({"type": "user_inject_queued", "message": msg})
    return {"ok": True}


# ─── API pública (/api/*) ────────────────────────────────────────────────────

def _start_task(task: str) -> None:
    """Lanza el agente en un thread y broadcast el estado por SSE.

    Misma lógica que /task — extraída para reutilizar en /api/task.
    """
    _reset_control()

    def runner() -> None:
        _set_busy(True, task)
        _emit({"type": "task_started", "task": task})
        try:
            run_agent(task, _emit, control=_control)
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
            "POST /api/interrupt":    "detiene la tarea actual al final del turno en curso",
            "POST /api/inject":       "inyecta un mensaje al agente entre turnos — body {message}",
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


@app.post("/api/interrupt")
def api_interrupt(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _check_api_auth(authorization)
    return interrupt()


@app.post("/api/inject")
def api_inject(
    body: InjectBody,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _check_api_auth(authorization)
    return inject(body)


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

    _reset_control()

    def runner() -> None:
        _set_busy(True, task)
        per_request_emit({"type": "task_started", "task": task})
        try:
            run_agent(task, per_request_emit, control=_control)
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
