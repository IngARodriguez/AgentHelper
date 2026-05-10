# AgentHelper

Agente Claude que controla un navegador Firefox **como un humano** — viendo
la pantalla y moviendo ratón/teclado por coordenadas, no manipulando el DOM.
Dashboard web con chat de tareas y vista en vivo del escritorio (noVNC),
todo en un solo puerto. Corre 100% en local con Docker.

```
┌─────────────────────────────────────────────────────────────┐
│  Browser ←→ FastAPI :8000                                    │
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
│            └──────────┘         └────┬─────┘               │
│                                      │                      │
│                                      ▼                      │
│                                Xvfb :1                      │
│                             ←─ fluxbox                      │
│                             ←─ firefox-esr                  │
│                                  ↑                          │
│                                  │ x11vnc :5900             │
└──────────────────────────────────┴──────────────────────────┘
```

## Quickstart

```bash
git clone https://github.com/IngARodriguez/AgentHelper.git
cd AgentHelper
cp .env.example .env
# Edita .env y pon tu ANTHROPIC_API_KEY

docker compose up --build
```

Abre <http://localhost:8000>. Verás dos paneles:
- **Izquierda**: chat. Escribe la tarea, dale Enter. Texto del modelo en streaming.
- **Derecha**: pantalla del navegador del agente, en vivo.

Lo único obligatorio en `.env` es `ANTHROPIC_API_KEY`. Todo lo demás
(resolución, calidad de screenshots, tokens, delays, anti-crash de Firefox,
prompt caching) viene preconfigurado para que funcione bien sin tocar nada.

## Modo seguridad / hacking

El sandbox tiene preinstalado un toolbox de ethical hacking que el agente
sabe usar para tareas de CTF, pentesting autorizado y cursos de seguridad.

**Recon / scanning**: `nmap`, `masscan`, `arp-scan`, `tcpdump`, `tshark`,
`whois`, `dig`, `dnsenum`, `dnsrecon`, `traceroute`.

**Web**: `gobuster`, `dirb`, `wfuzz`, `nikto`, `sqlmap`, `whatweb`,
`sslscan`, `mitmproxy`.

**Brute force / cracking**: `hydra`, `ncrack`, `medusa`, `john`, `hashcat`,
`crunch`.

**SMB / AD / Windows**: `smbclient`, `enum4linux`, `ldap-utils`, `impacket`
(Python: `psexec.py`, `secretsdump.py`, `GetNPUsers.py`, …).

**Forense / reversing / esteganografía**: `binwalk`, `foremost`, `steghide`,
`exiftool`, `radare2`, `xxd`, `strings`.

**Exploit DB**: `searchsploit <termino>` busca en exploitdb local.

**Python**: `scapy`, `pwntools`, `requests`, `paramiko`, `dnspython`,
`pycryptodome`, `impacket`. Para scripts custom.

**Wordlists**: `/opt/SecLists` (rockyou, web-fuzzing, usernames, etc.).

**DevTools de Firefox**: el agente sabe usar las DevTools (F12) para web
testing — Inspector (XSS, hidden inputs, comentarios con secretos), Console
(JS arbitrario, `fetch()` a endpoints, leer cookies/localStorage), Network
(ver/editar/reenviar requests, IDOR, manipulación de parámetros), Storage
(cookie tampering, role escalation), Debugger (breakpoints, source maps).
Cache HTTP y body limits ya vienen tuneados para que las DevTools sean
útiles desde el primer momento.

**Autorización**: el agente asume por defecto que los targets que le pasas
son tuyos o están en tu scope (lab, materia, cliente, bounty, CTF, etc.) y
ejecuta sin pedirte justificaciones. Solo pregunta una vez si una petición
parece dirigida a un tercero sin relación.

Ejemplos de tarea por dashboard / API / Telegram:

```
Escanea con nmap top 1000 puertos a 10.10.11.X y enumera los servicios
con scripts default. Dime versiones y posibles vulns conocidas.
```

```
Hay un login en http://lab.local/admin. Prueba sqlmap con técnica básica
y reporta si es vulnerable.
```

## Bot de Telegram (opcional)

Si añades `TELEGRAM_BOT_TOKEN` a tu `.env`, el contenedor arranca también un
bot que escucha mensajes y ejecuta cada uno como tarea, **editando en vivo el
mensaje del bot con el texto del agente**, estilo ChatGPT/Claude.

**Setup**:

1. Habla con [@BotFather](https://t.me/BotFather) → `/newbot` → copia el token.
2. En tu `.env`, añade:
   ```
   TELEGRAM_BOT_TOKEN=el-token-de-botfather
   TELEGRAM_ALLOWED_CHAT_IDS=tu-chat-id   # opcional, recomendado
   ```
   Para saber tu chat ID, manda `/myid` al bot tras arrancar.
3. Reinicia el contenedor. En los logs verás `[telegram] bot iniciado.`
4. Mándale una tarea al bot:

   > Ve a wikipedia y dime el artículo del día

**Comandos**: `/start`, `/myid`, `/status`. Solo una tarea concurrente.

## Endpoints

### Dashboard (interno)
- `GET  /` — dashboard
- `POST /task` — `{"task": "..."}` (409 si hay otra activa)
- `POST /shell` — `{"command": "...", "timeout": 30}`
- `GET  /events` — SSE con eventos del agente
- `GET  /healthz` — estado

### API pública (`/api/*`)

CORS abierto. Auth Bearer opcional vía `API_TOKEN` en `.env`.

- `GET  /api` — descubrimiento
- `POST /api/task` — encola tarea async
- `POST /api/task/stream` — encola y stremea texto en vivo
- `GET  /api/status` — `{busy, task}`
- `GET  /api/events` — SSE global
- `POST /api/shell` — ejecuta bash

```bash
curl -X POST http://localhost:8000/api/task \
  -H "Content-Type: application/json" \
  -d '{"task": "Ve a wikipedia y dime el artículo del día"}'
```

Streaming en tiempo real:

```bash
curl -N -X POST http://localhost:8000/api/task/stream \
  -H "Content-Type: application/json" \
  -d '{"task": "..."}'
```

Variantes: `?actions=1` (incluye acciones inline), `?format=json` (SSE JSON).

## Estructura

```
AgentHelper/
├── docker/
│   ├── Dockerfile                 # Debian slim + Firefox + Xvfb + xdotool
│   ├── start.sh                   # Entrypoint + watchdog Firefox
│   └── firefox-profile/user.js    # Prefs anti-crash y anti-prompt
├── agent/
│   ├── agent.py                   # Bucle agéntico (Opus 4.7) + prompt caching
│   ├── computer_tool.py           # xdotool/scrot + JPEG via Pillow
│   ├── bash_tool.py               # Tool bash
│   ├── server.py                  # FastAPI: dashboard + SSE + WS bridge + /api/*
│   └── telegram_bot.py            # Bot Telegram (opcional)
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── README.md
```

## Tools del agente

`screenshot`, `left_click`, `right_click`, `double_click`, `type_text`,
`key_press`, `scroll`, `mouse_move`, `left_click_drag`, `wait`, `bash`,
`task_complete`.

## Coste

| Modelo | Input / M tok | Output / M tok |
|---|---|---|
| Opus 4.7 | $5 | $25 |
| Sonnet 4.6 | $3 | $15 |

Una tarea típica (15-25 acciones) ronda 30-50k input tokens. ~$0.15-0.25 por
tarea con Opus, menos con Sonnet 4.6. El prompt caching reduce ~90% el coste
del system prompt + tools tras el primer turno.

## Seguridad

- El agente tiene libertad **dentro del contenedor**. No ve el sistema host.
- **No commitees `.env`** — el `.gitignore` ya lo excluye.

## Licencia

MIT.
