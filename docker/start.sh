#!/bin/bash
# Entrypoint del contenedor: arranca Xvfb, fluxbox, x11vnc, Firefox y uvicorn.
# Single-port: FastAPI sirve dashboard + noVNC + bridge WebSocket en $PORT.
#
# Configurado para uso local con recursos abundantes (no hay límites de RAM/CPU):
#   - x11vnc con polling rápido (-threads -defer 1 -wait 5).
#   - Firefox con perfil dedicado (user.js sin telemetry/prompts, sin GPU
#     porque Xvfb no la tiene, sandboxes desactivados porque Docker no puede
#     usarlos sin user namespaces).
#   - Watchdog que relanza Firefox si muere (raro con la config actual).
set -u

cleanup() {
    pkill -P $$ || true
}
trap cleanup EXIT INT TERM

PORT=${PORT:-8000}
WIDTH=${DISPLAY_WIDTH:-1280}
HEIGHT=${DISPLAY_HEIGHT:-800}
DEPTH=${DISPLAY_DEPTH:-24}

echo "[start] Xvfb :1 ${WIDTH}x${HEIGHT}x${DEPTH}"
Xvfb :1 -screen 0 "${WIDTH}x${HEIGHT}x${DEPTH}" \
    -ac +extension RANDR +extension DAMAGE -nolisten tcp \
    -dpi 96 \
    >/tmp/xvfb.log 2>&1 &
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
# Desactivar sandboxes que fallan dentro de containers (no hay user namespaces).
# Sin esto Firefox crashea al arrancar en muchos hosts Docker.
export MOZ_DISABLE_CONTENT_SANDBOX=1
export MOZ_DISABLE_RDD_SANDBOX=1
export MOZ_DISABLE_GMP_SANDBOX=1
export MOZ_DISABLE_SOCKET_PROCESS=1
# Sin diálogos de crash report (el agente no puede contestarlos)
export MOZ_CRASHREPORTER_DISABLE=1
export MOZ_DISABLE_AUTO_SAFE_MODE=1

echo "[start] fluxbox"
fluxbox >/tmp/fluxbox.log 2>&1 &

# x11vnc tuning para uso local con recursos abundantes:
#   -threads: encoding paralelo (aprovecha CPU multicore).
#   -defer 1 -wait 5: 200Hz de polling, batching de 1ms → muy fluido.
#   -noxdamage: en Firefox+Xvfb XDAMAGE a veces pierde updates → polling es más fiable.
#   -cursor most: cursor del cliente.
echo "[start] x11vnc :5900 (interno)"
x11vnc -display :1 -forever -shared -rfbport 5900 -nopw \
       -localhost -threads -defer 1 -wait 5 \
       -noxdamage -cursor most \
       -o /tmp/x11vnc.log >/tmp/x11vnc.stdout.log 2>&1 &
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

# Perfil dedicado: ya viene con user.js bakeado en /app/firefox-profile.
# Lo copiamos a un dir escribible para que Firefox pueda escribir su estado.
FF_PROFILE_SRC=/app/firefox-profile
FF_PROFILE_DIR=/tmp/ff-profile
if [ ! -d "$FF_PROFILE_DIR" ]; then
    mkdir -p "$FF_PROFILE_DIR"
    cp -r "$FF_PROFILE_SRC"/* "$FF_PROFILE_DIR"/ 2>/dev/null || true
fi

start_firefox() {
    # Borrar lock files de runs anteriores (tras crash quedan colgados y bloquean el arranque)
    rm -f "$FF_PROFILE_DIR/lock" "$FF_PROFILE_DIR/.parentlock" 2>/dev/null || true
    # --no-remote para no hablar con instancias previas. --new-instance + --profile fija el perfil.
    firefox-esr \
        --no-remote --new-instance \
        --profile "$FF_PROFILE_DIR" \
        --new-window "https://duckduckgo.com" \
        >>/tmp/firefox.log 2>&1 &
    FIREFOX_PID=$!
    echo "[firefox] arrancado pid=$FIREFOX_PID"
}

# Watchdog: si Firefox muere (OOM, crash), lo relanzamos hasta MAX_RESPAWNS.
# Incrementa el delay entre respawns para no entrar en loop si crashea inmediatamente.
firefox_watchdog() {
    local MAX_RESPAWNS=20
    local respawns=0
    local delay=2
    while true; do
        if ! kill -0 "$FIREFOX_PID" 2>/dev/null; then
            if [ $respawns -ge $MAX_RESPAWNS ]; then
                echo "[firefox] watchdog: alcanzados $MAX_RESPAWNS respawns, dejo de relanzar"
                return
            fi
            echo "[firefox] watchdog: pid=$FIREFOX_PID muerto, relanzando en ${delay}s (respawn #$((respawns+1)))"
            sleep $delay
            start_firefox
            respawns=$((respawns + 1))
            # Backoff suave: 2s, 2s, 4s, 4s, 8s, 8s, max 30s
            if [ $((respawns % 2)) -eq 0 ] && [ $delay -lt 30 ]; then
                delay=$((delay * 2))
                [ $delay -gt 30 ] && delay=30
            fi
        else
            sleep 5
        fi
    done
}

if [ "${SKIP_FIREFOX:-0}" = "1" ]; then
    echo "[start] firefox SKIP (SKIP_FIREFOX=1)"
else
    echo "[start] firefox-esr (con perfil $FF_PROFILE_DIR)"
    start_firefox
    firefox_watchdog &
fi

# Otro respiro para que la ventana de Firefox se renderice
sleep 2

echo "[start] uvicorn en :${PORT}"
cd /app
exec python3 -u -m uvicorn agent.server:app \
     --host 0.0.0.0 --port "${PORT}" --log-level info \
     --proxy-headers --forwarded-allow-ips '*'
