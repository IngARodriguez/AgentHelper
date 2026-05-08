# AgentHelper

Agente Claude que controla un navegador Firefox **como un humano** — viendo
la pantalla y moviendo ratón/teclado por coordenadas, no manipulando el DOM.
Dashboard web con chat de tareas y vista en vivo del escritorio (noVNC),
todo en un solo puerto. Listo para deploy en Railway.

Incluye un **agente ayudante** (Claude Haiku 4.5) que escribe el plan al
recibir la tarea y resuelve consultas durante la ejecución, para que el
agente principal (Claude Opus 4.7) tenga que pensar menos por turno.

```
┌─────────────────────────────────────────────────────────────┐
│  Browser ←→ FastAPI :PORT                                    │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  /             dashboard SPA                          │   │
│  │  /events       SSE — eventos del agente              │   │
│  │  /task         POST — encolar tarea                   │   │
│  │  /vnc/         estáticos noVNC                        │   │
│  │  /websockify   WS bridge → x11vnc:5900                │   │
│  └──────────────────────────────────────────────────────┘   │
│                  │                    │                     │
│                  │ run_agent()        │ proxy WS            │
│                  ▼                    ▼                     │
│            ┌──────────┐         ┌──────────┐               │
│            │ Opus 4.7 │ ──tools→│ xdotool  │               │
│            │  agent   │  scrot  │  scrot   │               │
│            └────┬─────┘         └────┬─────┘               │
│                 │ consult              │                    │
│                 ▼                      ▼                    │
│            ┌──────────┐          Xvfb :1                    │
│            │ Haiku 4.5│       ←─ fluxbox                    │
│            │  helper  │       ←─ firefox-esr                │
│            └──────────┘          ↑                          │
│                                  │ x11vnc :5900             │
└──────────────────────────────────┴──────────────────────────┘
```

## Quickstart local

```bash
git clone https://github.com/IngARodriguez/AgentHelper.git
cd AgentHelper
cp .env.example .env
# Edita .env con tu ANTHROPIC_API_KEY (y opcionalmente ANTHROPIC_BASE_URL)

docker compose up --build
```

Abre <http://localhost:8000>. Verás dos paneles:
- **Izquierda**: chat. Escribe la tarea, dale Enter. Texto del modelo en streaming, acciones, mensajes del helper en rosa.
- **Derecha**: pantalla del navegador del agente, en vivo.

## Deploy en Railway (free / hobby)

### Opción A — desde GitHub (recomendada)

1. **Hacer fork** o tener este repo en tu cuenta de GitHub.
2. Entrar en <https://railway.app> → **New Project** → **Deploy from GitHub repo** → seleccionar `AgentHelper`.
3. Railway detecta el `railway.json` y el `Dockerfile`. Empieza a construir.
4. En **Variables** del servicio, añadir como mínimo:
   - `ANTHROPIC_API_KEY` = tu API key
   - (opcional) `ANTHROPIC_BASE_URL` = si usas un proxy
   - (opcional) `CLAUDE_MODEL`, `HELPER_MODEL`, `HELPER_ENABLED`
5. En **Settings → Networking** → **Generate Domain** para obtener una URL pública.
6. Cuando el deploy termine, abrir esa URL.

### Opción B — desde imagen Docker en GHCR

GitHub Actions construye y publica la imagen automáticamente en cada push a
`main`. La encuentras en `ghcr.io/IngARodriguez/agenthelper:latest`.

1. Hacer la imagen pública: <https://github.com/users/IngARodriguez/packages/container/agenthelper/settings> → *Change visibility* → Public.
2. Railway → **New Project** → **Deploy from Docker image** → pegar `ghcr.io/ingarodriguez/agenthelper:latest`.
3. Mismas variables que en Opción A.

### Notas para el plan free

- **Memoria**: Railway Trial da ~512MB. Con Firefox + Xvfb + Python eso es muy
  justo, puede OOM-killear. Si te pasa, sube a Hobby ($5/mes) que da 8GB. La
  imagen está optimizada para correr en 800MB-1GB.
- **Sleep tras inactividad**: Railway duerme servicios sin tráfico. El primer
  acceso tras dormir tarda ~10-15s (arranca Xvfb, fluxbox, Firefox y uvicorn
  en orden). Es normal.
- **Resolución bajada a 1024x768** por defecto: menos RAM y menos tokens por
  screenshot. Súbela en `DISPLAY_WIDTH`/`DISPLAY_HEIGHT` si necesitas más espacio.
- **Un solo puerto público**: noVNC va integrado en FastAPI vía `/vnc/` + WS
  `/websockify`, no hace falta exponer el 6080 ni el 5900.

## Variables de entorno

Todas opcionales menos `ANTHROPIC_API_KEY`.

| Variable | Default | Descripción |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | **Obligatorio.** API key de Anthropic. |
| `ANTHROPIC_BASE_URL` | `api.anthropic.com` | Para usar un proxy compatible. |
| `CLAUDE_MODEL` | `claude-opus-4-7` | Modelo principal. `claude-sonnet-4-6` para más velocidad. |
| `HELPER_MODEL` | `claude-haiku-4-5` | Modelo del ayudante (rápido y barato). |
| `HELPER_ENABLED` | `1` | `0` para desactivar el ayudante. |
| `DISPLAY_WIDTH` | `1024` | Ancho del display Xvfb. |
| `DISPLAY_HEIGHT` | `768` | Alto del display Xvfb. |
| `MAX_TOKENS` | `8192` | Tokens máx por turno del agente. |
| `MAX_ITERATIONS` | `100` | Tope de iteraciones del bucle agéntico. |
| `ACTION_DELAY_S` | `0.6` | Pausa tras cada acción antes del screenshot. |
| `PORT` | `8000` | Railway lo pisa automáticamente. |

## Estructura

```
AgentHelper/
├── .github/workflows/docker.yml   # CI: build + push a GHCR
├── docker/
│   ├── Dockerfile                 # Debian slim + Firefox + Xvfb + xdotool
│   └── start.sh                   # Entrypoint: orquesta procesos
├── agent/
│   ├── __init__.py
│   ├── agent.py                   # Bucle agéntico (Opus 4.7) con custom tools
│   ├── helper.py                  # Planner + consultor (Haiku 4.5)
│   ├── computer_tool.py           # xdotool/scrot wrappers
│   └── server.py                  # FastAPI: dashboard + SSE + WS bridge
├── docker-compose.yml
├── requirements.txt
├── railway.json                   # Config para Railway
├── .env.example
└── README.md
```

## Endpoints

### Dashboard (uso interno)
- `GET  /` — dashboard (HTML SPA)
- `POST /task` — `{"task": "..."}` — encola una tarea (409 si hay otra activa)
- `POST /shell` — `{"command": "...", "timeout": 30}` — ejecuta bash
- `GET  /events` — SSE con eventos del agente (multi-cliente, broadcast)
- `GET  /vnc/...` — estáticos de noVNC
- `WS   /websockify` — bridge a x11vnc:5900
- `GET  /healthz` — JSON de estado
- `GET  /debug/services` — estado de procesos + logs internos
- `GET  /debug/simple-stream` — diagnóstico API streaming

### API pública (`/api/*`)

CORS abierto (`*`). Auth Bearer opcional via env var `API_TOKEN`.

- `GET  /api` — descubrimiento (lista de endpoints)
- `POST /api/task` — encola tarea async (respuesta inmediata)
- `POST /api/task/stream` — **encola y mantiene la conexión soltando el texto del agente en tiempo real**
- `GET  /api/status` — `{busy, task}`
- `GET  /api/events` — SSE global (broadcast del dashboard)
- `POST /api/shell` — ejecuta comando bash

**Ejemplo curl** (sin token):

```bash
curl -X POST https://agenthelper-production.up.railway.app/api/task \
  -H "Content-Type: application/json" \
  -d '{"task": "Ve a wikipedia.org y dime el artículo del día"}'
```

**Con token (recomendado)**: define `API_TOKEN=algo-secreto` en Railway Variables y manda:

```bash
curl -X POST https://agenthelper-production.up.railway.app/api/task \
  -H "Authorization: Bearer algo-secreto" \
  -H "Content-Type: application/json" \
  -d '{"task": "..."}'
```

Respuesta: `{"ok": true, "status": "started", "task": "..."}`. La tarea
aparece en el dashboard en tiempo real (mismo stream SSE).

**Streaming en tiempo real (recomendado)** — POST que mantiene la conexión y va devolviendo el texto del agente conforme lo genera:

```bash
curl -N -X POST https://agenthelper-production.up.railway.app/api/task/stream \
  -H "Content-Type: application/json" \
  -d '{"task": "Ve a wikipedia y dime el artículo del día"}'
```

Salida (texto plano, va apareciendo conforme el agente lo dice):
```
Voy a navegar a wikipedia.org para ver el artículo del día.
Ya puedo ver el artículo destacado del día. Voy a desplazarme un poco...
Ya tengo toda la información sobre el artículo destacado de hoy.

[done] tarea completada: ...
```

Variantes:
- `?actions=1` — incluye líneas `[action: key_press {"key":"ctrl+l"}]` inline
- `?format=json` — SSE con cada evento como JSON (`data: {"type": "text", ...}`)

**Escuchar eventos sueltos (sin disparar tarea)** — útil si ya enviaste la tarea por otro canal:

```bash
curl -N https://agenthelper-production.up.railway.app/api/events
```

Devuelve eventos SSE con `data: {"type": "text|action|bash_output|done|...", ...}`.

**Códigos de error**:
- `401` — falta `Authorization: Bearer`
- `403` — token incorrecto
- `409` — agente ocupado (cuerpo incluye `current_task`)
- `400` — body inválido

## Tools disponibles para el agente

Tools propias (no usan el beta `computer_20250124`, así funciona con cualquier
proxy compatible con Messages API):

`screenshot`, `left_click`, `right_click`, `double_click`, `type_text`,
`key_press`, `scroll`, `mouse_move`, `left_click_drag`, `wait`,
`consult_helper`, `task_complete`.

## Coste

| Modelo | Input/M tok | Output/M tok |
|---|---|---|
| Opus 4.7 (principal) | $5 | $25 |
| Haiku 4.5 (ayudante) | $1 | $5 |

Una tarea típica de 15-25 acciones ronda 30-50k tokens input. ~$0.15-0.25 por
tarea con Opus, mucho menos con Sonnet 4.6 como principal.

## Seguridad

- El agente tiene libertad **dentro del contenedor**. No ve el sistema host.
- En Railway no se exponen puertos extra (5900/6080) — todo va por `$PORT`.
- **No commitees `.env`** — el `.gitignore` ya lo excluye.
- En producción considera meter una capa de auth básica delante del dashboard
  (no incluida — añádela según tu caso).

## Licencia

MIT.
