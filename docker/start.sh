#!/bin/bash
# Entrypoint del contenedor: arranca Xvfb, fluxbox, x11vnc, Firefox y uvicorn.
# Single-port: FastAPI sirve dashboard + noVNC + bridge WebSocket en $PORT.
set -u

cleanup() {
    pkill -P $$ || true
}
trap cleanup EXIT INT TERM

PORT=${PORT:-8000}
WIDTH=${DISPLAY_WIDTH:-1024}
HEIGHT=${DISPLAY_HEIGHT:-768}

echo "[start] Xvfb :1 ${WIDTH}x${HEIGHT}"
Xvfb :1 -screen 0 "${WIDTH}x${HEIGHT}x24" -ac +extension RANDR -nolisten tcp >/tmp/xvfb.log 2>&1 &
XVFB_PID=$!

# Esperar hasta 15s a que el display esté listo
for i in $(seq 1 75); do
    if xdpyinfo -display :1 >/dev/null 2>&1; then
        echo "[start] Xvfb listo tras ${i} intentos"
        break
    fi
    if ! kill -0 "$XVFB_PID" 2>/dev/null; then
        echo "[start] ERROR: Xvfb murió. Log:"
        cat /tmp/xvfb.log || true
        exit 1
    fi
    sleep 0.2
done

if ! xdpyinfo -display :1 >/dev/null 2>&1; then
    echo "[start] ERROR: Xvfb no responde tras 15s"
    cat /tmp/xvfb.log || true
    exit 1
fi

export DISPLAY=:1
export MOZ_DISABLE_RDD_SANDBOX=1
export MOZ_DISABLE_GMP_SANDBOX=1

echo "[start] fluxbox"
fluxbox >/tmp/fluxbox.log 2>&1 &

# x11vnc en foreground-background (proceso normal en bg, no daemonizado).
# Sin -bg: si falla, vemos el error. Con --logfile además lo persistimos.
echo "[start] x11vnc :5900 (interno)"
x11vnc -display :1 -forever -shared -rfbport 5900 -nopw \
       -localhost -o /tmp/x11vnc.log >/tmp/x11vnc.stdout.log 2>&1 &
X11VNC_PID=$!

# Confirmar que x11vnc está bind-eando en 5900 (hasta 5s)
for i in $(seq 1 25); do
    if ss -lnt 2>/dev/null | grep -q ":5900 " || \
       netstat -lnt 2>/dev/null | grep -q ":5900 "; then
        echo "[start] x11vnc bind ok"
        break
    fi
    if ! kill -0 "$X11VNC_PID" 2>/dev/null; then
        echo "[start] ERROR: x11vnc murió. Log:"
        cat /tmp/x11vnc.stdout.log /tmp/x11vnc.log 2>/dev/null || true
        # No salimos — uvicorn sigue arriba para que /debug/services funcione
        break
    fi
    sleep 0.2
done

# Pequeña pausa antes de abrir Firefox
sleep 1

if [ "${SKIP_FIREFOX:-0}" = "1" ]; then
    echo "[start] firefox SKIP (SKIP_FIREFOX=1)"
else
    echo "[start] firefox-esr"
    firefox-esr --new-window "https://duckduckgo.com" >/tmp/firefox.log 2>&1 &
fi

# Otro respiro para que la ventana de Firefox se renderice
sleep 2

echo "[start] uvicorn en :${PORT}"
cd /app
exec python3 -u -m uvicorn agent.server:app \
     --host 0.0.0.0 --port "${PORT}" --log-level info \
     --proxy-headers --forwarded-allow-ips '*'
