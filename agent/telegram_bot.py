"""Bot de Telegram que envía tareas al agente y muestra el resultado en streaming.

Funcionamiento:
- Si TELEGRAM_BOT_TOKEN no está, el bot no arranca (silencioso).
- Long polling contra api.telegram.org/getUpdates.
- Cada mensaje del usuario lanza una tarea: el bot responde con un mensaje
  "🤔 procesando…" y va EDITANDO ese mismo mensaje conforme el agente escribe,
  estilo ChatGPT/Claude.
- Throttle de ~800ms entre edits (Telegram limita ~1 edit/sec por chat).
- Eventos también se broadcastean al dashboard SSE.
- Solo una tarea concurrente — si llega otra mientras hay una corriendo,
  responde "ocupado".
- ALLOWED_CHAT_IDS opcional para limitar quién puede usarlo.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

import httpx

from .agent import run_agent

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Lista CSV opcional de chat IDs permitidos. Si está vacía, abierto a cualquiera
# que descubra el bot. Si pones IDs, solo ellos pueden mandar tareas.
_allowed_raw = os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "").strip()
ALLOWED_CHAT_IDS: set[str] = {x.strip() for x in _allowed_raw.split(",") if x.strip()}

EDIT_THROTTLE_S = 0.8
MAX_TG_MSG_LEN = 4000  # límite real es 4096, dejamos margen
POLL_TIMEOUT_S = 30


def _tg(method: str, **params: Any) -> dict[str, Any] | None:
    """Llama a un método del Bot API. Sync, errores se loguean y se devuelve None."""
    if not TELEGRAM_TOKEN:
        return None
    try:
        with httpx.Client(timeout=30.0) as h:
            r = h.post(f"{TELEGRAM_API}/{method}", json=params)
        data = r.json()
        if not data.get("ok"):
            print(f"[telegram] {method} no-ok: {data}", flush=True)
        return data
    except Exception as e:  # noqa: BLE001
        print(f"[telegram] {method} error: {e!r}", flush=True)
        return None


def _send(chat_id: int, text: str) -> int | None:
    """sendMessage simple (texto plano), devuelve message_id o None."""
    res = _tg("sendMessage", chat_id=chat_id, text=text[:MAX_TG_MSG_LEN])
    if res and res.get("ok"):
        return res["result"]["message_id"]
    return None


def _edit(chat_id: int, message_id: int, text: str) -> None:
    """editMessageText — silencioso si no hay cambios respecto al mensaje actual."""
    text = text[:MAX_TG_MSG_LEN]
    if not text.strip():
        text = "(...)"
    _tg("editMessageText", chat_id=chat_id, message_id=message_id, text=text)


class TelegramTaskSession:
    """Una tarea enviada por un usuario de Telegram. Editamos en bucle el mensaje
    del bot conforme llega texto/acciones del agente."""

    def __init__(self, chat_id: int, message_id: int, task: str):
        self.chat_id = chat_id
        self.message_id = message_id
        self.task = task
        self.agent_text: list[str] = []
        self.actions: list[str] = []  # últimas acciones, sólo mostramos las recientes
        self.errors: list[str] = []
        self.status = "🤔 procesando…"
        self._last_edit_at = 0.0
        self._lock = threading.Lock()
        self._dirty = True

    def render(self) -> str:
        parts: list[str] = []
        parts.append(f"📝 {self.task[:120]}")
        parts.append(f"\n{self.status}\n")
        if self.actions:
            recent = self.actions[-4:]
            parts.append("Acciones recientes:\n" + "\n".join(f"▸ {a}" for a in recent))
        body = "".join(self.agent_text).strip()
        if body:
            parts.append("\n" + body)
        for err in self.errors[-3:]:
            parts.append(f"\n⚠️ {err}")
        text = "\n".join(parts)
        if len(text) > MAX_TG_MSG_LEN:
            head = text[:300]
            tail = text[-(MAX_TG_MSG_LEN - 320):]
            text = head + "\n\n[…]\n\n" + tail
        return text

    def maybe_flush(self, force: bool = False) -> None:
        with self._lock:
            if not self._dirty and not force:
                return
            now = time.monotonic()
            if not force and (now - self._last_edit_at) < EDIT_THROTTLE_S:
                return
            self._last_edit_at = now
            self._dirty = False
            text = self.render()
        # Llamada HTTP fuera del lock
        _edit(self.chat_id, self.message_id, text)

    def on_event(self, event: dict[str, Any]) -> None:
        t = event.get("type")
        with self._lock:
            self._dirty = True
            if t == "text":
                self.agent_text.append(event.get("text", ""))
            elif t == "action":
                action = event.get("action") or "?"
                args = event.get("input") or {}
                # Resumen de args sin spam
                args_brief = ", ".join(f"{k}={v}" for k, v in list(args.items())[:3])
                if len(args_brief) > 80:
                    args_brief = args_brief[:77] + "…"
                self.actions.append(f"{action} {args_brief}".strip())
            elif t == "tool_result_error":
                self.errors.append(str(event.get("message"))[:200])
            elif t == "bash_output":
                cmd = event.get("command", "")
                ec = event.get("exit_code")
                self.actions.append(f"bash $ {cmd[:60]} → exit {ec}")
            elif t == "done":
                self.status = "✅ " + (event.get("message") or "completado")
                self.maybe_flush(force=True)
                return
            elif t == "error":
                self.status = "❌ error"
                self.errors.append(str(event.get("message"))[:300])
                self.maybe_flush(force=True)
                return
        self.maybe_flush()


# ─── Estado global del bot ───────────────────────────────────────────────────

_busy_lock = threading.Lock()
_current_session: TelegramTaskSession | None = None


def _is_authorized(chat_id: int) -> bool:
    if not ALLOWED_CHAT_IDS:
        return True
    return str(chat_id) in ALLOWED_CHAT_IDS


def _handle_command(chat_id: int, text: str) -> bool:
    """Devuelve True si era un comando y lo manejamos."""
    cmd = text.split()[0].lower()
    if cmd == "/start":
        _send(chat_id, (
            "👋 Hola, soy el agente AgentHelper.\n\n"
            "Mándame una tarea por mensaje y la ejecuto en un navegador real, "
            "soltando el resultado aquí mismo en streaming.\n\n"
            "Comandos:\n"
            "/start — esta ayuda\n"
            "/status — estado actual\n"
            "/myid — tu chat id (útil para TELEGRAM_ALLOWED_CHAT_IDS)\n"
        ))
        return True
    if cmd == "/myid":
        _send(chat_id, f"Tu chat id: {chat_id}")
        return True
    if cmd == "/status":
        with _busy_lock:
            sess = _current_session
        if sess is None:
            _send(chat_id, "📭 sin tarea activa")
        else:
            _send(chat_id, f"⏳ tarea en curso: {sess.task[:200]}")
        return True
    return False


def _run_task_for_telegram(chat_id: int, message_id: int, task: str) -> None:
    """Ejecuta el agente dentro del thread del bot, broadcasteando al dashboard."""
    # Import diferido para evitar circular imports
    from . import server

    session = TelegramTaskSession(chat_id, message_id, task)
    global _current_session
    with _busy_lock:
        _current_session = session

    server._set_busy(True, task)
    server._emit({"type": "task_started", "task": task})

    def combined_on_event(event: dict[str, Any]) -> None:
        # 1. Broadcast al dashboard SSE
        server._emit(event)
        # 2. Update del mensaje de Telegram
        session.on_event(event)

    try:
        run_agent(task, combined_on_event)
    except Exception as e:  # noqa: BLE001
        combined_on_event({"type": "error", "message": f"runner crashed: {e!r}"})
    finally:
        server._set_busy(False, None)
        with _busy_lock:
            _current_session = None
        # Asegurar último edit
        session.maybe_flush(force=True)


def _handle_message(chat_id: int, text: str) -> None:
    if not _is_authorized(chat_id):
        _send(chat_id, "❌ chat no autorizado")
        return

    text = text.strip()
    if not text:
        return

    if text.startswith("/") and _handle_command(chat_id, text):
        return

    # Si está ocupado, rechaza
    with _busy_lock:
        if _current_session is not None:
            _send(chat_id, f"⏳ ocupado con: {_current_session.task[:120]}")
            return

    # Crea el mensaje placeholder y arranca la tarea
    initial_text = f"📝 {text[:120]}\n\n🤔 procesando…"
    msg_id = _send(chat_id, initial_text)
    if msg_id is None:
        return

    threading.Thread(
        target=_run_task_for_telegram,
        args=(chat_id, msg_id, text),
        daemon=True,
        name="tg-task",
    ).start()


def _poll_loop() -> None:
    """Long polling de getUpdates. Se lanza en un thread daemon."""
    print(f"[telegram] bot iniciado. allowed_chat_ids={ALLOWED_CHAT_IDS or 'todos'}", flush=True)
    offset = 0
    backoff = 1.0
    while True:
        try:
            with httpx.Client(timeout=POLL_TIMEOUT_S + 10) as h:
                r = h.get(
                    f"{TELEGRAM_API}/getUpdates",
                    params={"offset": offset, "timeout": POLL_TIMEOUT_S},
                )
            if r.status_code != 200:
                print(f"[telegram] getUpdates {r.status_code}: {r.text[:200]}", flush=True)
                time.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
                continue
            backoff = 1.0
            data = r.json()
            if not data.get("ok"):
                print(f"[telegram] getUpdates not-ok: {data}", flush=True)
                time.sleep(3)
                continue

            for upd in data.get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message")
                if not msg:
                    continue
                chat = msg.get("chat", {})
                chat_id = chat.get("id")
                text = msg.get("text") or ""
                if chat_id is None or not text:
                    continue
                # Manejar el mensaje en otro thread para no bloquear el polling
                threading.Thread(
                    target=_handle_message,
                    args=(chat_id, text),
                    daemon=True,
                    name="tg-msg",
                ).start()
        except httpx.TimeoutException:
            continue
        except Exception as e:  # noqa: BLE001
            print(f"[telegram] poll error: {e!r}", flush=True)
            time.sleep(backoff)
            backoff = min(backoff * 2, 30.0)


def start_bot() -> None:
    """Llamado desde el lifespan del FastAPI. Si no hay token, no hace nada."""
    if not TELEGRAM_TOKEN:
        print("[telegram] TELEGRAM_BOT_TOKEN no definido, bot desactivado", flush=True)
        return
    threading.Thread(target=_poll_loop, daemon=True, name="telegram-poll").start()
