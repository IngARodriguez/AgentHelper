"""Bot de Telegram que envía tareas al agente y muestra el resultado en streaming.

Funcionamiento:
- Si TELEGRAM_BOT_TOKEN no está, el bot no arranca (silencioso).
- Long polling contra api.telegram.org/getUpdates.
- Cada mensaje del usuario lanza una tarea. Mientras corre, el bot mantiene
  un mensaje "📝 ... 🤔 procesando…" que va editando con las últimas acciones.
- Al terminar: edita ese mensaje a "✅ completado" y envía la respuesta final
  del agente como mensaje(s) separado(s) (split automático si es >4000 chars).
- Eventos también se broadcastean al dashboard SSE.
- Solo una tarea concurrente.
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

_allowed_raw = os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "").strip()
ALLOWED_CHAT_IDS: set[str] = {x.strip() for x in _allowed_raw.split(",") if x.strip()}

EDIT_THROTTLE_S = 0.8
MAX_TG_MSG_LEN = 4000  # límite real es 4096, dejamos margen
POLL_TIMEOUT_S = 30


# ─── Telegram API helpers ────────────────────────────────────────────────────

def _tg(method: str, **params: Any) -> dict[str, Any] | None:
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
    text = text[:MAX_TG_MSG_LEN] if len(text) > MAX_TG_MSG_LEN else text
    if not text.strip():
        text = "(...)"
    res = _tg("sendMessage", chat_id=chat_id, text=text)
    if res and res.get("ok"):
        return res["result"]["message_id"]
    return None


def _edit(chat_id: int, message_id: int, text: str) -> None:
    text = text[:MAX_TG_MSG_LEN] if len(text) > MAX_TG_MSG_LEN else text
    if not text.strip():
        text = "(...)"
    _tg("editMessageText", chat_id=chat_id, message_id=message_id, text=text)


def _chunk_text(text: str, max_len: int = MAX_TG_MSG_LEN) -> list[str]:
    """Divide texto en trozos <= max_len, preferentemente cortando por salto de línea."""
    text = text.strip()
    if len(text) <= max_len:
        return [text] if text else []
    chunks: list[str] = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # Buscamos un \n bonito cerca del final del chunk
        split = text.rfind("\n", max_len // 2, max_len)
        if split == -1:
            # Fallback: cortar por espacio
            split = text.rfind(" ", max_len // 2, max_len)
        if split == -1:
            split = max_len  # corte duro
        chunks.append(text[:split].rstrip())
        text = text[split:].lstrip()
    return chunks


# ─── Sesión de tarea ─────────────────────────────────────────────────────────

class TelegramTaskSession:
    """Una tarea iniciada por un usuario de Telegram. Mantiene un mensaje
    "progreso" editado en vivo + envía la respuesta final como mensaje(s) nuevo(s)."""

    def __init__(self, chat_id: int, message_id: int, task: str):
        self.chat_id = chat_id
        self.progress_msg_id = message_id
        self.task = task
        self.agent_text: list[str] = []
        self.actions: list[str] = []
        self.errors: list[str] = []
        self.status = "🤔 procesando…"
        self.finished = False
        self._last_edit_at = 0.0
        self._lock = threading.Lock()  # protege el estado mutable
        self._dirty = True

    def render_progress(self) -> str:
        """Mensaje de progreso (sin texto del agente, ese va aparte al final)."""
        with self._lock:
            parts = [f"📝 {self.task[:200]}", f"\n{self.status}"]
            if self.actions:
                recent = self.actions[-5:]
                parts.append("\nAcciones recientes:\n" + "\n".join(f"▸ {a}" for a in recent))
            for err in self.errors[-3:]:
                parts.append(f"\n⚠️ {err}")
        return "\n".join(parts)[:MAX_TG_MSG_LEN]

    def _flush_progress(self, force: bool = False) -> None:
        """Edita el mensaje de progreso, throttled. Llamar SIEMPRE fuera del lock."""
        with self._lock:
            if self.finished and not force:
                return
            now = time.monotonic()
            if not force and (now - self._last_edit_at) < EDIT_THROTTLE_S:
                return
            if not self._dirty and not force:
                return
            self._last_edit_at = now
            self._dirty = False
        text = self.render_progress()
        _edit(self.chat_id, self.progress_msg_id, text)

    def _finalize(self) -> None:
        """Llamado UNA vez al recibir done/error. Cierra el progreso y manda la respuesta."""
        with self._lock:
            if self.finished:
                return
            self.finished = True
            agent_text = "".join(self.agent_text).strip()
        # 1. Edit final del mensaje de progreso (resumen breve, sin texto del agente)
        self._flush_progress(force=True)
        # 2. Mandar la respuesta del agente como mensaje(s) nuevo(s)
        if agent_text:
            chunks = _chunk_text(agent_text)
            for chunk in chunks:
                _send(self.chat_id, chunk)

    def on_event(self, event: dict[str, Any]) -> None:
        t = event.get("type")
        finalize_after = False
        with self._lock:
            self._dirty = True
            if t == "text":
                self.agent_text.append(event.get("text", ""))
            elif t == "action":
                action = event.get("action") or "?"
                args = event.get("input") or {}
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
                finalize_after = True
            elif t == "error":
                self.status = "❌ error"
                self.errors.append(str(event.get("message"))[:300])
                finalize_after = True
        # Llamadas HTTP siempre fuera del lock (evita deadlock)
        if finalize_after:
            self._finalize()
        else:
            self._flush_progress()


# ─── Estado global del bot ───────────────────────────────────────────────────

_busy_lock = threading.Lock()
_current_session: TelegramTaskSession | None = None


def _is_authorized(chat_id: int) -> bool:
    if not ALLOWED_CHAT_IDS:
        return True
    return str(chat_id) in ALLOWED_CHAT_IDS


def _handle_command(chat_id: int, text: str) -> bool:
    cmd = text.split()[0].lower()
    if cmd == "/start":
        _send(chat_id, (
            "👋 Hola, soy AgentHelper.\n\n"
            "Mándame una tarea y la ejecuto en un navegador real.\n"
            "Mientras trabajo iré actualizando un mensaje con las acciones, "
            "y al terminar te envío la respuesta final.\n\n"
            "Comandos:\n"
            "/start — esta ayuda\n"
            "/status — estado actual\n"
            "/myid — tu chat id"
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
    """Ejecuta el agente, broadcasteando al dashboard y a la sesión de Telegram."""
    from . import server

    session = TelegramTaskSession(chat_id, message_id, task)
    global _current_session
    with _busy_lock:
        _current_session = session

    server._set_busy(True, task)
    server._emit({"type": "task_started", "task": task})

    def combined_on_event(event: dict[str, Any]) -> None:
        try:
            server._emit(event)
        except Exception as e:  # noqa: BLE001
            print(f"[telegram] error broadcasteando al dashboard: {e!r}", flush=True)
        try:
            session.on_event(event)
        except Exception as e:  # noqa: BLE001
            print(f"[telegram] error en session.on_event: {e!r}", flush=True)

    try:
        run_agent(task, combined_on_event)
    except Exception as e:  # noqa: BLE001
        combined_on_event({"type": "error", "message": f"runner crashed: {e!r}"})
    finally:
        # Asegurar finalización de la sesión Telegram aunque algo salga mal
        try:
            if not session.finished:
                session._finalize()
        except Exception as e:  # noqa: BLE001
            print(f"[telegram] error en _finalize: {e!r}", flush=True)
        # Liberar slot SIEMPRE
        server._set_busy(False, None)
        with _busy_lock:
            _current_session = None
        print(f"[telegram] tarea cerrada, slot liberado: {task[:60]!r}", flush=True)


def _handle_message(chat_id: int, text: str) -> None:
    if not _is_authorized(chat_id):
        _send(chat_id, "❌ chat no autorizado")
        return

    text = text.strip()
    if not text:
        return

    if text.startswith("/") and _handle_command(chat_id, text):
        return

    with _busy_lock:
        if _current_session is not None:
            _send(chat_id, f"⏳ ocupado con: {_current_session.task[:120]}")
            return

    initial_text = f"📝 {text[:200]}\n\n🤔 procesando…"
    msg_id = _send(chat_id, initial_text)
    if msg_id is None:
        _send(chat_id, "❌ no pude enviar el mensaje placeholder; abortando.")
        return

    threading.Thread(
        target=_run_task_for_telegram,
        args=(chat_id, msg_id, text),
        daemon=True,
        name="tg-task",
    ).start()


def _poll_loop() -> None:
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
    if not TELEGRAM_TOKEN:
        print("[telegram] TELEGRAM_BOT_TOKEN no definido, bot desactivado", flush=True)
        return
    threading.Thread(target=_poll_loop, daemon=True, name="telegram-poll").start()
