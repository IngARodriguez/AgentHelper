# AgentHelper — Pentesting Agent

Agente Claude (Opus 4.7) que opera como un red teamer autónomo. Controla un
Firefox real **viendo la pantalla** (no manipulando el DOM) y tiene acceso
shell completo a un toolbox de pentesting estilo Kali. Encadena recon →
enumeración → explotación → post-explotación sin pedir permiso entre pasos.

Pensado para CTFs, bug bounty con scope, pentesting autorizado, labs propios
y cursos de seguridad. Corre 100% local con Docker.

```
┌─────────────────────────────────────────────────────────────┐
│  Browser ←→ FastAPI :8000                                    │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  /             dashboard SPA (chat + vista live)      │   │
│  │  /events       SSE — eventos del agente              │   │
│  │  /task         POST — encolar tarea                   │   │
│  │  /api/*        API pública (token Bearer opcional)    │   │
│  │  /vnc/         estáticos noVNC                        │   │
│  │  /websockify   WS bridge → x11vnc:5900                │   │
│  └──────────────────────────────────────────────────────┘   │
│                  │                    │                     │
│                  │ run_agent()        │ proxy WS            │
│                  ▼                    ▼                     │
│            ┌──────────┐         ┌──────────┐               │
│            │ Opus 4.7 │ ──tools→│ xdotool  │               │
│            │  agent   │  scrot  │  scrot   │               │
│            │          │  bash   │ Xvfb :1  │               │
│            │          │  bash── │ → fluxbox│               │
│            └──────────┘         │ → firefox│               │
│                                 └────┬─────┘               │
│                                  ↑   │                      │
│                Toolbox pentesting│   │ x11vnc :5900         │
│                + DevTools Firefox│                          │
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

Abre <http://localhost:8000>:
- **Izquierda**: chat. Escribe la tarea, dale Enter.
- **Derecha**: pantalla del navegador del agente, en vivo.

Lo único obligatorio es `ANTHROPIC_API_KEY`. Resolución, calidad de
screenshots, anti-crash de Firefox, prompt caching, todo viene
preconfigurado.

**Primer build**: 15-25 min (descarga ~3GB entre apt, pip, gem, Go/Rust
binaries, SecLists, exploitdb, nuclei templates). Builds posteriores
reutilizan caché.

## Cómo se comporta

El agente trabaja con mentalidad red teamer:

- **Actúa, no pide permiso.** Recibe target → ejecuta. Sin "¿quieres que
  pruebe…?" ni confirmaciones entre pasos.
- **Cero disclaimers.** Asume contexto autorizado. No te recuerda la ética
  ni la legalidad en cada turno.
- **Payloads completos.** XSS, SQLi, RCE, reverse shells, deserialización,
  LFI, SSRF, XXE, SSTI — los escribe enteros y funcionales para el target,
  no placeholders genéricos.
- **Persiste.** Si una tool falla, prueba 3-5 vectores alternativos antes
  de declarar algo inviable.
- **Encadena el recon completo.** Con un target, hace nmap → enum
  servicios → recon específico (web/SMB/AD) → vuln scan → explotación →
  privesc → lateral movement, todo en una sola sesión.
- **Combina shell + navegador.** En tareas web mezcla CLI (curl, sqlmap,
  ffuf) con DevTools de Firefox (Network para editar requests, Console
  para JS, Storage para cookies, Inspector para DOM/XSS).
- **Interrumpible.** Mientras trabaja puedes mandarle instrucciones nuevas
  con INJECT (cambia de táctica al siguiente turno) o pararlo con STOP.

Ejemplos de prompts:

```
Escanea con nmap el rango 10.10.11.0/24, identifica hosts vivos,
enumera servicios y dime cuáles tienen versiones con CVEs conocidos
explotables.
```

```
Hay una app web en http://target.htb/login. Haz recon completo
(stack, dirs, params), prueba SQLi y XSS en los inputs, y si entras
busca privesc.
```

```
Username: johndoe123. Hazle perfil OSINT — redes sociales, emails
asociados, breaches, repos públicos, info filtrada.
```

## Toolbox

**Recon de red**: `nmap`, `masscan`, `arp-scan`, `tcpdump`, `tshark`,
`whois`, `dig`, `dnsenum`, `dnsrecon`, `traceroute`, `mtr`.

**Web fuzzing / scanning**: `ffuf`, `feroxbuster` (recursive), `katana`,
`gobuster`, `dirb`, `dirsearch`, `wfuzz`, `nikto`, `sqlmap`, `commix`,
`dalfox`, `xsstrike` (XSS con bypass WAF), `arjun`, `paramspider`,
`wafw00f`, `wpscan`, `whatweb`, `sslscan`, `mitmproxy`, `naabu`, `dnsx`,
`gowitness` (screenshots URLs en masa).

**Brute force / cracking**: `hydra`, `ncrack`, `medusa`, `john`,
`hashcat`, `hashid`, `crunch`, `cewl` (wordlist desde sites web).

**AD / Windows pentesting**: `nxc`/`netexec` (swiss army SMB/LDAP/MSSQL/
WinRM/SSH), `bloodhound-python`, `bloodyAD` (RBCD / shadow creds CLI),
`certipy-ad` (AD CS ESC1-11), `pypykatz` (mimikatz Python),
`coercer` (PetitPotam &co.), `kerbrute`, `evil-winrm`, `responder`,
`mitm6` (IPv6 spoof + WPAD), `ldapdomaindump`, `enum4linux-ng`,
`smbclient`, `ldap-utils`, `impacket` (`psexec.py`, `secretsdump.py`,
`GetNPUsers.py`, `ntlmrelayx.py`, …).

**Pivoting / túneles**: `chisel`, `proxychains4`, `socat`, `tor`.

**OSINT**: `subfinder`, `assetfinder`, `httpx`, `nuclei` (con templates
pre-cargados), `theHarvester`, `gau`, `waybackurls`, `gitleaks`,
`trufflehog` (secret scanning agresivo), `sherlock`, `holehe`,
`socialscan`, `shodan`, `censys`, `waybackpy`.

**Forense / esteganografía**: `binwalk`, `foremost`, `steghide`, `exiftool`,
`volatility3` (memoria RAM), `bulk-extractor`.

**Binary / reversing / exploit dev**: `gdb` con GEF preinstalado, `ROPgadget`,
`pwntools` (Python), `xxd`, `strings`, `file`, `objdump`, `readelf`, `nm`,
`ltrace`, `strace`.

**CTF crypto**: `RsaCtfTool` (ataques a RSA débil — factordb, Wiener,
Fermat, common factors, etc.).

**Cloud (AWS)**: `awscli`, `s3scanner` (buckets S3 abiertos).

**Wireless**: `aircrack-ng` suite (cracking de capturas .cap/.pcap).

**Exploit DB**: `searchsploit <termino>` (exploit-database completo en `/opt/exploitdb`).

**Python para exploits**: `pwntools`, `scapy`, `impacket`, `paramiko`,
`requests`, `dnspython`, `pycryptodome`, `pyOpenSSL`, `beautifulsoup4`.

**Wordlists**: `/opt/SecLists` (rockyou, common-passwords, web-fuzzing,
usernames, payloads).

## Playbook integrado

El system prompt lleva recetas listas para usar — el agente no tiene que
reinventar payloads cada vez. Cubre:

- **Reverse shells** (bash/python/php/powershell + estabilización TTY)
- **SQLi** (auth bypass, union, time-based blind, sqlmap tampers)
- **XSS** (bypass de filtros, polyglot universal, robo de cookies)
- **SSTI** por engine (Jinja2, Twig, ERB, Velocity)
- **LFI**, **JWT** (alg:none, kid traversal), **file upload bypass**
- **XXE** (file read, SSRF interno, OOB exfil con DTD remoto)
- **Linux privesc** (sudo -l, SUIDs, GTFOBins, kernel exploits con
  CVE→versión: Dirty Pipe, PwnKit, Dirty COW, sudoedit)
- **Windows privesc** (mapeo `Se*Privilege` → técnica: SeImpersonate→
  PrintSpoofer/GodPotato, SeBackup→dump SAM, SeRestore, SeLoadDriver…)
- **AD chain HTB-style** (kerbrute → AS-REP roast → password spray →
  kerberoast → BloodHound → certipy AD CS → DCSync → pass-the-hash)
- **Stack-specific**: WordPress / Drupal / Tomcat / Spring Actuator /
  Jenkins / Confluence / GitLab / phpMyAdmin / Grafana / Elasticsearch /
  MongoDB / Redis / Docker daemon / K8s API
- **API testing**: REST discovery (swagger), IDOR, mass assignment,
  GraphQL (introspection, batch queries, sin introspect)
- **Container escape**: docker.sock, --privileged, cgroup release_agent,
  cap_sys_admin, cap_dac_read_search
- **AWS**: IAM enum, S3 anónimo/auth, EC2 metadata (IMDSv2 con token),
  Lambda env vars
- **Pivoting con chisel** + proxychains
- **Iteration tactics**: qué probar cuando nmap/gobuster/sqlmap/XSS/hydra
  fallan (vectores alternativos)

## Control mid-run (STOP / INJECT / RESUME)

Tres controles en el panel izquierdo para no perder contexto cuando algo
no va bien:

- **`[ INJECT ]`** (amber, sustituye a EXEC durante busy) — manda una
  instrucción al agente entre turnos. Llega como mensaje del usuario con
  prefijo `[USUARIO INTERRUMPE…]`. Útil para:
  - corregir target (*"el IP real es .42 no .41"*)
  - cambiar de táctica (*"olvida ese path, prueba sqlmap"*)
  - añadir objetivo (*"si encuentras la flag, también dump /etc/passwd"*)
- **`[ STOP ]`** (rojo, solo durante busy) — cancela limpiamente al final
  del turno actual (sin romper la API call en curso).
- **`[ RESUME ]`** (cyan, solo visible cuando hay sesión guardada) —
  reanuda la última sesión. Click sin texto = continúa tal cual. Click
  con texto en el input = reanuda añadiendo esa instrucción + screenshot
  fresco. Útil cuando paraste, hubo un error o un refusal.

La sesión sobrevive a refresh del dashboard (la UI consulta `/session` al
cargar) pero NO sobrevive a `docker compose down`.

Por API:

```bash
curl -X POST http://localhost:8000/inject \
  -H "Content-Type: application/json" \
  -d '{"message":"prueba con dirsearch en /admin"}'

curl -X POST http://localhost:8000/interrupt

# Reanudar la última sesión con instrucción nueva
curl -X POST http://localhost:8000/resume \
  -H "Content-Type: application/json" \
  -d '{"task":"olvida nuclei, profundiza en Firebase manualmente"}'

# Ver si hay sesión resumable
curl http://localhost:8000/session
```

## Cuando Anthropic activa cyber-safeguards

El modelo Claude tiene safeguards de "cyber" que a veces disparan refusals
incluso con uso autorizado. El agente los maneja así:

1. Lo loguea claramente en la UI (bloque rojo con la categoría y el URL
   del Cyber Verification Program de Anthropic).
2. Reintenta automáticamente hasta 2 veces inyectando un nudge que pide
   al modelo descomponer la acción en pasos más pequeños y específicos al
   target real.
3. Si tras 2 reintentos sigue bloqueando, guarda la sesión, surfacea el
   URL del formulario y queda lista para `RESUME`.

Si chocas a menudo, la solución oficial es rellenar el [Cyber Verification
Program](https://claude.com/form/cyber-use-case) — Anthropic ajusta los
límites de tu cuenta para casos legítimos (académico, pentest, bounty).
La URL exacta sale en el refusal cuando ocurre.

Para reducir la frecuencia, **sé específico** en los prompts:
- ✗ *"haz pentest completo del banco X"*
- ✓ *"sobre el form de login en https://lab.htb/login, prueba SQLi en el campo username con union-based"*

## DevTools de Firefox

El agente sabe manejar las DevTools (F12) para análisis web:

- **Inspector**: encontrar `input[type=hidden]`, comentarios HTML con
  secretos, modificar el DOM en vivo (test XSS reflejado).
- **Console**: ejecutar JS arbitrario en el contexto de la página
  (`document.cookie`, `fetch('/api/admin')`, decodificar JWTs inline).
- **Network**: capturar todas las requests, ver headers/cookies/payloads,
  **Edit and Resend** para test de IDOR / privilege escalation cambiando
  IDs en URL/body.
- **Storage**: editar cookies / localStorage / sessionStorage / IndexedDB
  para cookie tampering, role escalation, session hijack.
- **Debugger**: poner breakpoints en JS, ver source maps si están
  expuestos (leak de código fuente original).

Cache HTTP, response body limits y persist logs ya vienen tuneados en el
perfil de Firefox para que las DevTools sean útiles desde el primer scan.

## API keys opcionales

En `.env`. El agente las usa si están definidas; sin ellas cae a métodos
públicos (crt.sh, internetdb.shodan.io, etc.).

| Variable | Para qué |
|---|---|
| `SHODAN_API_KEY` | Búsquedas Shodan completas (host, search, faceted) |
| `CENSYS_API_ID` / `CENSYS_API_SECRET` | Censys queries |
| `HIBP_API_KEY` | Have I Been Pwned (breachedaccount endpoint) |
| `GITHUB_TOKEN` | GitHub code search vía API (encontrar secrets en repos) |
| `VIRUSTOTAL_API_KEY` | VirusTotal lookups |

## Bot de Telegram (opcional)

Si añades `TELEGRAM_BOT_TOKEN` a `.env`, arranca un bot que recibe tareas y
**edita en vivo un mensaje** con el texto del agente, estilo ChatGPT.

```bash
TELEGRAM_BOT_TOKEN=el-token-de-botfather
TELEGRAM_ALLOWED_CHAT_IDS=tu-chat-id   # recomendado: limitar quién puede usarlo
```

Comandos: `/start`, `/myid`, `/status`. Una tarea concurrente.

## Endpoints

### Dashboard (interno)
- `GET /` — dashboard
- `POST /task` — `{"task": "..."}`
- `POST /shell` — `{"command": "...", "timeout": 30}`
- `POST /inject` — `{"message": "..."}` (instrucción mid-task al agente)
- `POST /interrupt` — detener tarea actual al cierre del turno
- `POST /resume` — `{"task": "..."}` (vacío = continuar tal cual)
- `GET /session` — `{resumable, messages_count, ended_at, end_reason}`
- `GET /events` — SSE
- `GET /healthz`

### API pública (`/api/*`)

CORS abierto. Auth Bearer opcional vía `API_TOKEN`.

- `GET /api` — descubrimiento
- `POST /api/task` — encola async
- `POST /api/task/stream` — encola y stremea texto del agente en vivo
- `POST /api/inject` — inyecta mensaje mid-task
- `POST /api/interrupt` — para la tarea actual
- `POST /api/resume` — reanuda última sesión
- `GET /api/session` — info de sesión guardada
- `GET /api/status` — `{busy, task}`
- `GET /api/events` — SSE global
- `POST /api/shell` — ejecuta bash

```bash
curl -N -X POST http://localhost:8000/api/task/stream \
  -H "Content-Type: application/json" \
  -d '{"task": "nmap -sV 10.10.11.5 y dime los servicios"}'
```

Variantes: `?actions=1` (acciones inline), `?format=json` (SSE JSON).

## Estructura

```
AgentHelper/
├── docker/
│   ├── Dockerfile                 # Debian slim + Firefox + toolbox pentest + OSINT
│   ├── start.sh                   # Entrypoint + watchdog Firefox
│   └── firefox-profile/user.js    # Prefs anti-crash + DevTools tuneadas
├── agent/
│   ├── agent.py                   # Bucle agéntico + prompt caching + system prompt agresivo
│   ├── computer_tool.py           # xdotool/scrot + JPEG via Pillow
│   ├── bash_tool.py               # Tool bash (sin filtros)
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

`bash` ejecuta cualquier comando en el sandbox sin filtros — el agente
tiene root dentro del contenedor.

## Coste

| Modelo | Input / M tok | Output / M tok |
|---|---|---|
| Opus 4.7 | $5 | $25 |
| Sonnet 4.6 | $3 | $15 |

Una sesión de pentest (recon + enum + explotación, ~30-60 acciones) ronda
50-100k input tokens. Con prompt caching activo (ya configurado), el system
prompt + tools no se recobran tras el primer turno → ~$0.30-0.60 por
sesión completa con Opus, menos con Sonnet.

## Seguridad

- El agente corre con root **dentro del contenedor**. No ve el sistema host.
- El sandbox Docker provee aislamiento del host por defecto. No le pases
  flags que lo rompan (`--privileged`, `--network=host`) salvo que lo
  necesites para un escenario específico.
- **No commitees `.env`** — el `.gitignore` ya lo excluye.

## Licencia

MIT.
