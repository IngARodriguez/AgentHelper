#!/bin/bash
# Entrypoint del contenedor: arranca Xvfb, fluxbox, x11vnc, Firefox y uvicorn.
# Single-port: FastAPI sirve dashboard + noVNC + bridge WebSocket en $PORT.
set -eu

cleanup() {
    pkill -P $$ || true
}
trap cleanup EXIT INT TERM

PORT=${PORT:-8000}
WIDTH=${DISPLAY_WIDTH:-1024}
HEIGHT=${DISPLAY_HEIGHT:-768}

echo "[start] Xvfb :1 ${WIDTH}x${HEIGHT}"
Xvfb :1 -screen 0 "${WIDTH}x${HEIGHT}x24" -ac +extension RANDR -nolisten tcp >/tmp/xvfb.log 2>&1 &

# Esperar a que el display esté listo
for i in $(seq 1 30); do
    if xdpyinfo -display :1 >/dev/null 2>&1; then
        break
    fi
    sleep 0.2
done

export DISPLAY=:1
export MOZ_DISABLE_RDD_SANDBOX=1
export MOZ_DISABLE_GMP_SANDBOX=1

echo "[start] fluxbox"
fluxbox >/tmp/fluxbox.log 2>&1 &

echo "[start] x11vnc :5900 (interno)"
x11vnc -display :1 -forever -shared -rfbport 5900 -nopw -quiet -bg \
       -localhost -o /tmp/x11vnc.log

# Pequeña pausa para que el WM se asiente antes de abrir Firefox
sleep 1

echo "[start] firefox-esr"
firefox-esr --new-window "https://duckduckgo.com" >/tmp/firefox.log 2>&1 &

# Otro respiro para que la ventana se renderice antes de la primera captura
sleep 2

echo "[start] uvicorn en :${PORT}"
cd /app
exec python3 -u -m uvicorn agent.server:app \
     --host 0.0.0.0 --port "${PORT}" --log-level info \
     --proxy-headers --forwarded-allow-ips '*'
