"""Bot de Telegram que envía tareas al agente y muestra el resultado en streaming.

UX (estilo ChatGPT/Claude):
- Un único mensaje del bot que se va EDITANDO con todo lo que el agente dice.
- Cuando se acerca al límite (4000 chars), lo cierra con "[continúa…]" y abre
  un mensaje NUEVO que pasa a ser el activo. Así la respuesta puede crecer
  indefinidamente.
- Acciones (clicks/teclas/bash) se muestran pequeñas al final del mensaje activo.
- Throttle de ~800ms entre edits (Telegram limita ~1 edit/sec por chat).
- Solo una tarea concurrente.
"""

from __future__ import annotations

import os
import threading
import time
import traceback
from typing import Any

import httpx

from .agent import run_agent

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

_allowed_raw = os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "").strip()
ALLOWED_CHAT_IDS: set[str] = {x.strip() for x in _allowed_raw.split(",") if x.strip()}

EDIT_THROTTLE_S = 0.8
TG_HARD_LIMIT = 4096
TG_SOFT_LIMIT = 3700  # cuando el contenido pase de aquí, abrimos mensaje nuevo
POLL_TIMEOUT_S = 30


# ─── Telegram API helpers ────────────────────────────────────────────────────

_tg_client = httpx.Client(timeout=30.0)  # reutilizable para todas las llamadas


def _tg(method: str, **params: Any) -> dict[str, Any] | None:
    if not TELEGRAM_TOKEN:
        return None
    try:
        r = _tg_client.post(f"{TELEGRAM_API}/{method}", json=params)
        try:
            data = r.json()
        except Exception:
            print(f"[telegram] {method} non-json {r.status_code}: {r.text[:200]}", flush=True)
            return None
        if not data.get("ok"):
            # No es fatal — Telegram devuelve "message is not modified" cuando
            # editamos con el mismo contenido, eso lo silenciamos
            desc = data.get("description", "")
            if "not modified" not in desc:
                print(f"[telegram] {method} not-ok: {desc}", flush=True)
        return data
    except Exception as e:  # noqa: BLE001
        print(f"[telegram] {method} EXC: {e!r}", flush=True)
        return None


def _send_message(chat_id: int, text: str) -> int | None:
    if not text or not text.strip():
        text = "(...)"
    if len(text) > TG_HARD_LIMIT:
        text = text[:TG_HARD_LIMIT - 4] + "\n…"
    res = _tg("sendMessage", chat_id=chat_id, text=text)
    if res and res.get("ok"):
        mid = res["result"]["message_id"]
        return mid
    return None


def _edit_message(chat_id: int, message_id: int, text: str) -> bool:
    if not text or not text.strip():
        text = "(...)"
    if len(text) > TG_HARD_LIMIT:
        text = text[:TG_HARD_LIMIT - 4] + "\n…"
    res = _tg("editMessageText", chat_id=chat_id, message_id=message_id, text=text)
    return bool(res and res.get("ok"))


# ─── Sesión de tarea ─────────────────────────────────────────────────────────

class TelegramTaskSession:
    """Tarea iniciada por Telegram. Editamos un mensaje activo en vivo, y si
    rebasa el límite abrimos otro mensaje y continuamos en ese."""

    def __init__(self, chat_id: int, first_message_id: int, task: str):
        self.chat_id = chat_id
        self.task = task
        # Mensaje activo (el que estamos editando ahora mismo)
        self.active_msg_id: int = first_message_id
        # Texto que ya está "fijado" en mensajes anteriores (no se edita más)
        self.frozen_msgs_count = 0
        # Buffer del mensaje activo: lo que se está acumulando
        self.active_text_buf: list[str] = []  # texto del agente desde que empezó este mensaje
        self.actions: list[str] = []
        self.errors: list[str] = []
        self.status = "🤔 procesando…"
        self.finished = False
        # RLock — la misma rama puede entrar al lock varias veces sin deadlockear
        self._lock = threading.RLock()
        self._last_edit_at = 0.0
        self._dirty = True

    # ─── Render ──────────────────────────────────────────────────────────────

    def _render_active(self) -> str:
        """Render del mensaje activo: header + status + texto acumulado + acciones."""
        with self._lock:
            parts: list[str] = []
            if self.frozen_msgs_count == 0:
                # Solo en el primer mensaje incluimos el header completo
                parts.append(f"📝 {self.task[:200]}")
                parts.append(self.status)
            else:
                # Mensajes posteriores son continuación
                parts.append(f"…(continuación, parte {self.frozen_msgs_count + 1})")
                parts.append(self.status)
            body = "".join(self.active_text_buf).strip()
            if body:
                parts.append("")
                parts.append(body)
            recent_actions = self.actions[-4:] if self.actions else []
            if recent_actions:
                parts.append("")
                parts.append("⚙️ " + " · ".join(recent_actions))
            for err in self.errors[-2:]:
                parts.append(f"\n⚠️ {err}")
            return "\n".join(parts)

    # ─── Roll-over a mensaje nuevo ───────────────────────────────────────────

    def _maybe_rollover(self) -> bool:
        """Si el mensaje activo se va a pasar del límite, lo cierra y abre uno nuevo.

        Devuelve True si se hizo rollover (en cuyo caso ya se editó/envió todo).
        """
        with self._lock:
            text = self._render_active()
            if len(text) <= TG_SOFT_LIMIT:
                return False
            # Rollover: cerrar el mensaje actual con un sufijo "[continúa…]"
            # y abrir uno nuevo continuando desde donde estamos
            closing = text + "\n\n[continúa…]"
            if len(closing) > TG_HARD_LIMIT:
                closing = closing[:TG_HARD_LIMIT - 20] + "\n\n[continúa…]"
            old_id = self.active_msg_id
            # Limpiar buffer activo PERO conservar last actions/status/errors
            self.active_text_buf = []
            self.frozen_msgs_count += 1
            # Liberar lock antes de hacer las llamadas HTTP
        _edit_message(self.chat_id, old_id, closing)
        new_id = _send_message(self.chat_id, "(continuando…)")
        with self._lock:
            if new_id:
                self.active_msg_id = new_id
                self._dirty = True
            else:
                # Si no pudimos crear el mensaje nuevo, dejamos el viejo y reintentaremos
                self.frozen_msgs_count -= 1
        # Forzar un edit del nuevo mensaje con el contenido actual
        if new_id:
            _edit_message(self.chat_id, new_id, self._render_active())
        return True

    # ─── Flush ───────────────────────────────────────────────────────────────

    def _flush(self, force: bool = False) -> None:
        """Edita el mensaje activo, throttled. Hace rollover si rebasa límite."""
        with self._lock:
            now = time.monotonic()
            if not force and (now - self._last_edit_at) < EDIT_THROTTLE_S:
                return
            if not self._dirty and not force:
                return
            self._last_edit_at = now
            self._dirty = False

        # Comprobar si necesitamos rollover (esto ya hace el edit por sí mismo)
        if self._maybe_rollover():
            return

        with self._lock:
            text = self._render_active()
            msg_id = self.active_msg_id
        _edit_message(self.chat_id, msg_id, text)

    # ─── Eventos ─────────────────────────────────────────────────────────────

    def on_event(self, event: dict[str, Any]) -> None:
        t = event.get("type")
        try:
            with self._lock:
                self._dirty = True
                if t == "text":
                    self.active_text_buf.append(event.get("text", ""))
                elif t == "action":
                    action = event.get("action") or "?"
                    args = event.get("input") or {}
                    args_brief = ", ".join(
                        f"{k}={v}" for k, v in list(args.items())[:2]
                    )
                    if len(args_brief) > 60:
                        args_brief = args_brief[:57] + "…"
                    self.actions.append(f"{action}({args_brief})")
                elif t == "tool_result_error":
                    self.errors.append(str(event.get("message"))[:200])
                elif t == "bash_output":
                    cmd = event.get("command", "")
                    ec = event.get("exit_code")
                    self.actions.append(f"bash:{cmd[:40]}→{ec}")
                elif t == "done":
                    self.status = "✅ " + (event.get("message") or "completado")
                    self.finished = True
                elif t == "error":
                    self.status = "❌ error"
                    self.errors.append(str(event.get("message"))[:300])
                    self.finished = True
                # Resto de tipos los ignoramos
            self._flush(force=(t in ("done", "error")))
        except Exception as e:  # noqa: BLE001
            print(f"[telegram] on_event({t}) EXC: {e!r}\n{traceback.format_exc()}", flush=True)


# ─── Estado global del bot ───────────────────────────────────────────────────

_busy_lock = threading.Lock()
_current_session: TelegramTaskSession | None = None


def _is_authorized(chat_id: int) -> bool:
    return not ALLOWED_CHAT_IDS or str(chat_id) in ALLOWED_CHAT_IDS


def _handle_command(chat_id: int, text: str) -> bool:
    cmd = text.split()[0].lower()
    if cmd == "/start":
        _send_message(chat_id, (
            "👋 Hola, soy AgentHelper.\n\n"
            "Mándame una tarea y la ejecuto en un navegador real, mostrándote "
            "lo que voy haciendo en tiempo real.\n\n"
            "/start — esta ayuda\n"
            "/status — estado actual\n"
            "/myid — tu chat id"
        ))
        return True
    if cmd == "/myid":
        _send_message(chat_id, f"Tu chat id: {chat_id}")
        return True
    if cmd == "/status":
        with _busy_lock:
            sess = _current_session
        if sess is None:
            _send_message(chat_id, "📭 sin tarea activa")
        else:
            _send_message(chat_id, f"⏳ tarea en curso: {sess.task[:200]}")
        return True
    return False


def _run_task_for_telegram(chat_id: int, message_id: int, task: str) -> None:
    """Ejecuta el agente, broadcasteando al dashboard y a la sesión Telegram."""
    from . import server

    print(f"[telegram] start task chat={chat_id} msg={message_id} task={task[:80]!r}", flush=True)
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
            print(f"[telegram] dashboard emit error: {e!r}", flush=True)
        try:
            session.on_event(event)
        except Exception as e:  # noqa: BLE001
            print(f"[telegram] session.on_event error: {e!r}", flush=True)

    final_messages = None
    try:
        final_messages = run_agent(task, combined_on_event)
    except Exception as e:  # noqa: BLE001
        print(f"[telegram] run_agent crashed: {e!r}\n{traceback.format_exc()}", flush=True)
        combined_on_event({"type": "error", "message": f"runner crashed: {e!r}"})
    finally:
        # Forzar último flush y liberar slot SIEMPRE
        try:
            session._flush(force=True)
        except Exception as e:  # noqa: BLE001
            print(f"[telegram] final flush error: {e!r}", flush=True)
        # Guardar sesión en server para que /resume funcione desde dashboard
        try:
            server._save_session(final_messages, end_reason="done")
        except Exception:
            pass
        server._set_busy(False, None)
        with _busy_lock:
            _current_session = None
        print(f"[telegram] task finished, slot libre: {task[:60]!r}", flush=True)


def _handle_message(chat_id: int, text: str) -> None:
    if not _is_authorized(chat_id):
        _send_message(chat_id, "❌ chat no autorizado")
        return
    text = text.strip()
    if not text:
        return
    if text.startswith("/") and _handle_command(chat_id, text):
        return
    with _busy_lock:
        if _current_session is not None:
            _send_message(chat_id, f"⏳ ocupado con: {_current_session.task[:120]}")
            return
    initial = f"📝 {text[:200]}\n🤔 procesando…"
    msg_id = _send_message(chat_id, initial)
    if msg_id is None:
        print("[telegram] no pude enviar el mensaje placeholder, abortando", flush=True)
        return
    threading.Thread(
        target=_run_task_for_telegram,
        args=(chat_id, msg_id, text),
        daemon=True,
        name="tg-task",
    ).start()


def _poll_loop() -> None:
    print(
        f"[telegram] bot iniciado. allowed_chat_ids={ALLOWED_CHAT_IDS or 'todos'}",
        flush=True,
    )
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
