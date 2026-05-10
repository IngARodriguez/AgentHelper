<div align="center">

# AgentHelper

### Pentesting agent autónomo. Claude Opus 4.7 + Firefox real + toolbox Kali-style. Local con Docker.

[![License: MIT](https://img.shields.io/badge/License-MIT-7DBC00.svg?style=flat-square)](#licencia)
[![Docker](https://img.shields.io/badge/Docker-required-2496ED.svg?style=flat-square&logo=docker&logoColor=white)](https://www.docker.com/)
[![Python 3.11](https://img.shields.io/badge/Python-3.11-3776AB.svg?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Claude](https://img.shields.io/badge/Claude-Opus_4.7-D97757.svg?style=flat-square)](https://www.anthropic.com/)

</div>

Agente Claude que opera como un red teamer autónomo. Controla un **Firefox real**
viendo la pantalla por coordenadas (no manipula el DOM) y tiene shell completa
con un toolbox de pentesting tipo Kali. Encadena recon → enumeración →
explotación → post-explotación sin pedir permiso entre pasos.

Pensado para **CTFs, bug bounty con scope, pentest autorizado, labs propios y
cursos de seguridad**. Corre 100% local con Docker.

---

## Tabla de contenido

- [Quickstart](#quickstart)
- [Cómo se comporta](#cómo-se-comporta)
- [Toolbox](#toolbox)
- [Playbook integrado](#playbook-integrado)
- [DevTools de Firefox](#devtools-de-firefox)
- [Control mid-run (STOP / INJECT / RESUME)](#control-mid-run-stop--inject--resume)
- [Cuando Anthropic activa cyber-safeguards](#cuando-anthropic-activa-cyber-safeguards)
- [API keys opcionales](#api-keys-opcionales)
- [Bot de Telegram](#bot-de-telegram-opcional)
- [Endpoints](#endpoints)
- [Arquitectura](#arquitectura)
- [Coste](#coste)
- [Seguridad](#seguridad)
- [Licencia](#licencia)

---

## Quickstart

```bash
git clone https://github.com/IngARodriguez/AgentHelper.git
cd AgentHelper
cp .env.example .env
# Edita .env y pon tu ANTHROPIC_API_KEY

docker compose up --build
```

Abre <http://localhost:8000>.

| Panel | Qué hace |
|---|---|
| **Izquierda** | Chat: escribes tarea, dale Enter. Eventos del agente en streaming. |
| **Derecha** | Pantalla del navegador del agente, en vivo (noVNC). |

Lo único obligatorio es `ANTHROPIC_API_KEY`. Resolución, calidad de screenshots,
anti-crash de Firefox, prompt caching — todo viene preconfigurado.

> **Primer build**: 15-25 min (~3GB entre apt, pip, gem, Go/Rust binaries,
> SecLists, exploitdb, nuclei templates). Builds posteriores reutilizan caché.

---

## Cómo se comporta

Mentalidad red teamer:

- **Actúa, no pide permiso.** Recibe target → ejecuta. Sin "¿quieres que pruebe…?"
- **Cero disclaimers.** Asume contexto autorizado. No recuerda ética en cada turno.
- **Payloads completos.** XSS, SQLi, RCE, reverse shells, deser, LFI, SSRF, XXE,
  SSTI — los escribe enteros y funcionales para el target, no placeholders.
- **Persiste.** Si una tool falla, prueba 3-5 vectores alternativos antes de rendirse.
- **Encadena el recon completo.** Con un target hace nmap → enum servicios → recon
  específico → vuln scan → explotación → privesc → lateral, todo en una sesión.
- **Combina shell + navegador.** Mezcla CLI (curl, sqlmap, ffuf) con DevTools de
  Firefox (Network para editar requests, Console para JS, Storage para cookies).
- **Interrumpible.** Mientras trabaja puedes inyectarle instrucciones con
  **INJECT** o pararlo con **STOP**. Tras un stop o error, **RESUME** recupera
  el contexto.

**Ejemplos de prompts:**

```
Escanea con nmap el rango 10.10.11.0/24, identifica hosts vivos,
enumera servicios y dime cuáles tienen versiones con CVEs explotables.
```

```
Hay una app web en http://target.htb/login. Haz recon completo
(stack, dirs, params), prueba SQLi y XSS, y si entras busca privesc.
```

```
Username johndoe123 — perfil OSINT: redes sociales, emails asociados,
breaches, repos públicos, info filtrada.
```

---

## Toolbox

<details>
<summary><b>Recon de red</b> — nmap, masscan, naabu, dnsx, tcpdump, tshark…</summary>

`nmap`, `masscan`, `arp-scan`, `tcpdump`, `tshark`, `whois`, `dig`, `dnsenum`,
`dnsrecon`, `traceroute`, `mtr`, `naabu` (port scanner Go rápido), `dnsx`
(DNS toolkit Go).
</details>

<details>
<summary><b>Web fuzzing / scanning</b> — ffuf, feroxbuster, sqlmap, nikto, wpscan…</summary>

`ffuf`, `feroxbuster` (recursive Rust), `katana` (crawler con headless +
JS parsing), `gobuster`, `dirb`, `dirsearch`, `wfuzz`, `nikto`, `sqlmap`,
`commix`, `dalfox` (XSS), `xsstrike` (XSS con bypass WAF), `arjun`
(param discovery), `paramspider`, `wafw00f`, `wpscan`, `whatweb`, `sslscan`,
`mitmproxy`, `gowitness` (screenshots URLs en masa).
</details>

<details>
<summary><b>Brute force / cracking</b> — hydra, john, hashcat, cewl…</summary>

`hydra`, `ncrack`, `medusa`, `john`, `hashcat`, `hashid`, `crunch`, `cewl`
(wordlist desde sites web).
</details>

<details>
<summary><b>AD / Windows pentesting</b> — NetExec, BloodHound, certipy, mimikatz…</summary>

- `nxc`/`netexec` — swiss army SMB/LDAP/MSSQL/WinRM/SSH
- `bloodhound-python` — ingestor para BloodHound (path mapping)
- `bloodyAD` — RBCD / shadow creds / DCSync desde CLI
- `certipy-ad` — explotación AD CS (ESC1-11)
- `pypykatz` — mimikatz puro Python
- `coercer` — PetitPotam, PrinterBug
- `kerbrute` — bruteforce/userenum Kerberos
- `evil-winrm` — shell WinRM
- `responder` — LLMNR/NBT-NS poisoning
- `mitm6` — IPv6 spoof + WPAD
- `ldapdomaindump`, `smbclient`, `ldap-utils`, `enum4linux-ng`
- `impacket` — `psexec.py`, `wmiexec.py`, `secretsdump.py`, `GetNPUsers.py`,
  `GetUserSPNs.py`, `ntlmrelayx.py`
</details>

<details>
<summary><b>OSINT</b> — subfinder, httpx, nuclei, theHarvester, sherlock…</summary>

`subfinder`, `assetfinder`, `httpx`, `nuclei` (templates pre-cargados),
`theHarvester`, `gau`, `waybackurls`, `gitleaks`, `trufflehog` (secret
scanning agresivo), `sherlock`, `holehe`, `socialscan`, `shodan`, `censys`,
`waybackpy`.
</details>

<details>
<summary><b>Binary / pwn / exploit dev</b> — gdb+GEF, pwntools, ROPgadget…</summary>

`gdb` con GEF preinstalado, `ROPgadget`, `pwntools` (Python), `xxd`,
`strings`, `file`, `objdump`, `readelf`, `nm`, `ltrace`, `strace`.
</details>

<details>
<summary><b>Forense / esteganografía / crypto</b> — binwalk, steghide, volatility3, RsaCtfTool…</summary>

`binwalk`, `foremost`, `steghide`, `exiftool`, `volatility3` (memoria RAM),
`bulk-extractor`, `RsaCtfTool` (ataques a RSA débil — factordb, Wiener,
Fermat, common factors).
</details>

<details>
<summary><b>Pivoting / cloud / wireless / exploits</b></summary>

- **Pivoting**: `chisel`, `proxychains4`, `socat`, `tor`
- **Cloud (AWS)**: `awscli`, `s3scanner`
- **Wireless**: `aircrack-ng`
- **Exploit DB**: `searchsploit` (exploit-database completo en `/opt/exploitdb`)
- **Python exploits**: `pwntools`, `scapy`, `impacket`, `paramiko`, `requests`,
  `dnspython`, `pycryptodome`, `pyOpenSSL`, `beautifulsoup4`
- **Wordlists**: `/opt/SecLists` (rockyou, common-passwords, web-fuzzing,
  usernames, payloads)
</details>

---

## Playbook integrado

El system prompt lleva recetas listas para usar — el agente no reinventa
payloads cada vez. Cubre:

| Categoría | Qué incluye |
|---|---|
| **Reverse shells** | bash, python, php, powershell + estabilización TTY |
| **Web exploits** | SQLi (auth bypass, union, blind), XSS (filtros, polyglot), SSTI por engine, LFI, JWT (alg:none, kid), file upload bypass |
| **XXE** | File read, SSRF interno, OOB exfil con DTD remoto |
| **Linux privesc** | sudo, SUIDs, GTFOBins + kernel exploits (Dirty Pipe, PwnKit, Dirty COW, sudoedit) |
| **Windows privesc** | Mapeo `Se*Privilege` → técnica (SeBackup, SeImpersonate→Potatoes, etc.) |
| **AD chain HTB-style** | kerbrute → AS-REP → spray → kerberoast → BloodHound → certipy → DCSync → PtH |
| **Stack-specific** | WordPress, Drupal, Tomcat, Spring Actuator, Jenkins, Confluence, GitLab, phpMyAdmin, Grafana, Elasticsearch, MongoDB, Redis, Docker daemon, K8s API |
| **API testing** | REST discovery (swagger), IDOR, mass assignment, GraphQL (introspection, batch queries) |
| **Container escape** | docker.sock, --privileged, cgroup release_agent, cap_sys_admin |
| **AWS** | IAM enum, S3 anónimo/auth, EC2 metadata (IMDSv2 con token), Lambda env |
| **Pivoting** | chisel + proxychains |
| **Iteration tactics** | Qué probar cuando nmap/gobuster/sqlmap/XSS/hydra fallan |

---

## DevTools de Firefox

El agente sabe usar DevTools (F12) para análisis web:

| Pestaña | Uso ofensivo |
|---|---|
| **Inspector** | `input[type=hidden]`, comentarios HTML con secretos, DOM XSS en vivo |
| **Console** | JS arbitrario: `document.cookie`, `fetch('/api/admin')`, decodificar JWTs |
| **Network** | Capturar requests, **Edit and Resend** para IDOR / privesc cambiando IDs |
| **Storage** | Editar cookies / localStorage para tampering, role escalation, hijack |
| **Debugger** | Breakpoints en JS, source maps si están expuestos |

Cache HTTP, response body limits y persist logs ya vienen tuneados en el perfil
de Firefox para que las DevTools sean útiles desde el primer scan.

---

## Control mid-run (STOP / INJECT / RESUME)

Tres controles en el panel izquierdo para no perder contexto cuando algo no va
bien:

| Botón | Cuándo aparece | Qué hace |
|---|---|---|
| **`[ INJECT ]`** (amber) | El sitio de EXEC durante `busy` | Manda una instrucción al agente entre turnos. Llega como `[USUARIO INTERRUMPE…]` |
| **`[ STOP ]`** (rojo) | Solo durante `busy` | Cancela limpiamente al cierre del turno actual |
| **`[ RESUME ]`** (cyan) | Idle Y hay sesión guardada | Reanuda última sesión. Click vacío = continuar tal cual. Click con texto = añade instrucción + screenshot fresco |

> La sesión sobrevive a refresh del dashboard, pero **NO** a `docker compose down`.

**Por API:**

```bash
# Inyectar mid-task
curl -X POST http://localhost:8000/inject -H "Content-Type: application/json" \
  -d '{"message":"prueba con dirsearch en /admin"}'

# Parar
curl -X POST http://localhost:8000/interrupt

# Reanudar con nueva instrucción
curl -X POST http://localhost:8000/resume -H "Content-Type: application/json" \
  -d '{"task":"olvida nuclei, profundiza en Firebase manualmente"}'

# Ver si hay sesión
curl http://localhost:8000/session
```

---

## Cuando Anthropic activa cyber-safeguards

El modelo tiene safeguards de "cyber" que disparan refusals incluso con uso
autorizado. El agente los maneja así:

1. **Log claro en la UI** (bloque rojo con categoría + URL del Cyber Verification Program).
2. **Reintenta hasta 2 veces** inyectando un nudge para descomponer la acción.
3. **Si tras 2 reintentos sigue bloqueando**, guarda la sesión, surfaca el URL y
   queda lista para `RESUME`.

**Lo único que de verdad relaja los safeguards:**

> [Cyber Verification Program](https://claude.com/form/cyber-use-case) —
> Anthropic ajusta los límites de tu cuenta para casos legítimos. La URL exacta
> sale en el refusal cuando ocurre.

**Para reducir la frecuencia, sé específico:**

| ✗ Demasiado abstracto | ✓ Específico al target |
|---|---|
| *"haz pentest completo del sitio X"* | *"prueba SQLi union-based en username del form `https://lab.htb/login`"* |
| *"escanea todas las vulns"* | *"nmap -sV puertos 1-1000 a 10.10.11.X"* |
| *"hackea el banco Y"* | (cambia el target — los safeguards bloquean third-party real) |

---

## API keys opcionales

En `.env`. El agente las usa si están definidas; sin ellas cae a métodos públicos.

| Variable | Para qué |
|---|---|
| `SHODAN_API_KEY` | Búsquedas Shodan completas |
| `CENSYS_API_ID` / `CENSYS_API_SECRET` | Censys queries |
| `HIBP_API_KEY` | Have I Been Pwned |
| `GITHUB_TOKEN` | GitHub code search (encontrar secrets en repos) |
| `VIRUSTOTAL_API_KEY` | VirusTotal lookups |

---

## Bot de Telegram (opcional)

Si añades `TELEGRAM_BOT_TOKEN` a `.env`, arranca un bot que recibe tareas y
**edita en vivo un mensaje** con el texto del agente, estilo ChatGPT.

```bash
TELEGRAM_BOT_TOKEN=el-token-de-botfather
TELEGRAM_ALLOWED_CHAT_IDS=tu-chat-id   # recomendado
```

**Comandos:** `/start`, `/myid`, `/status`. Una tarea concurrente.

---

## Endpoints

<details>
<summary><b>Dashboard (interno)</b></summary>

| Method | Path | Body |
|---|---|---|
| `GET` | `/` | dashboard |
| `POST` | `/task` | `{"task": "..."}` |
| `POST` | `/shell` | `{"command": "...", "timeout": 30}` |
| `POST` | `/inject` | `{"message": "..."}` (instrucción mid-task) |
| `POST` | `/interrupt` | (cancelar al cierre del turno) |
| `POST` | `/resume` | `{"task": "..."}` (vacío = continuar) |
| `GET` | `/session` | `{resumable, messages_count, ended_at, end_reason}` |
| `GET` | `/events` | SSE |
| `GET` | `/healthz` | estado |
</details>

<details>
<summary><b>API pública (/api/*)</b> — CORS abierto, Bearer opcional vía API_TOKEN</summary>

| Method | Path | Notas |
|---|---|---|
| `GET` | `/api` | descubrimiento |
| `POST` | `/api/task` | encola async |
| `POST` | `/api/task/stream` | stremea texto en vivo |
| `POST` | `/api/inject` | |
| `POST` | `/api/interrupt` | |
| `POST` | `/api/resume` | |
| `GET` | `/api/session` | |
| `GET` | `/api/status` | `{busy, task}` |
| `GET` | `/api/events` | SSE global |
| `POST` | `/api/shell` | ejecuta bash |

```bash
curl -N -X POST http://localhost:8000/api/task/stream \
  -H "Content-Type: application/json" \
  -d '{"task": "nmap -sV 10.10.11.5"}'
```

Variantes: `?actions=1` (acciones inline), `?format=json` (SSE JSON).
</details>

---

## Arquitectura

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
│                                  ↑   │ x11vnc :5900         │
│                Toolbox pentesting│                          │
│                + DevTools Firefox│                          │
└──────────────────────────────────┴──────────────────────────┘
```

**Estructura del repo:**

```
AgentHelper/
├── docker/
│   ├── Dockerfile                 # Debian slim + Firefox + toolbox + OSINT
│   ├── start.sh                   # Entrypoint + watchdog Firefox
│   └── firefox-profile/user.js    # Prefs anti-crash + DevTools tuneadas
├── agent/
│   ├── agent.py                   # Bucle agéntico + prompt caching + playbook
│   ├── computer_tool.py           # xdotool/scrot + JPEG via Pillow
│   ├── bash_tool.py               # Tool bash (sin filtros)
│   ├── server.py                  # FastAPI: dashboard + SSE + WS + /api/*
│   └── telegram_bot.py            # Bot Telegram (opcional)
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── README.md
```

**Tools del agente** (las que llama vía API tool_use):
`screenshot`, `left_click`, `right_click`, `double_click`, `type_text`,
`key_press`, `scroll`, `mouse_move`, `left_click_drag`, `wait`, `bash`,
`task_complete`. `bash` ejecuta cualquier comando sin filtros — root dentro
del contenedor.

---

## Coste

| Modelo | Input / M tok | Output / M tok |
|---|---|---|
| Opus 4.7 | $5 | $25 |
| Sonnet 4.6 | $3 | $15 |

Una sesión de pentest (recon + enum + explotación, ~30-60 acciones) ronda
**50-100k input tokens**. Con prompt caching activo (ya configurado), el system
prompt + tools no se recobran tras el primer turno → **~$0.30-0.60 por sesión
completa con Opus**, menos con Sonnet.

---

## Seguridad

- El agente corre con **root dentro del contenedor**. No ve el sistema host.
- El sandbox Docker provee aislamiento por defecto. **No le pases** flags que
  lo rompan (`--privileged`, `--network=host`) salvo escenario específico.
- **No commitees `.env`** — el `.gitignore` ya lo excluye.

---

## Licencia

MIT.

<div align="center">

— Hecho para aprender pentesting. Úsalo solo donde tengas autorización. —

</div>
