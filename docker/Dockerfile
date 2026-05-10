FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DISPLAY=:1 \
    MOZ_DISABLE_CONTENT_SANDBOX=1

# ─── Stack base: Xvfb + Firefox + noVNC + Python + utilidades shell ──────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    xvfb x11vnc x11-utils xdotool scrot \
    fluxbox xfonts-base xauth xterm \
    novnc \
    firefox-esr \
    ca-certificates curl wget jq nano vim less unzip zip xxd file \
    procps net-tools iputils-ping dnsutils traceroute mtr-tiny whois \
    git build-essential \
    && apt-get clean && rm -rf /var/lib/apt/lists/* /var/cache/apt/* /tmp/*

# ─── Toolbox de seguridad / pentesting ───────────────────────────────────────
# Instalado en una capa separada para que cambios al stack base no rebuilden
# todo el toolbox. Cubre las categorías típicas de un curso de ethical hacking:
# recon de red, scanning, web testing, brute force, SMB/AD, forense, crypto,
# wireless. Solo herramientas en repos oficiales Debian.
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Recon / scanning de red
    nmap masscan arp-scan netcat-openbsd tcpdump tshark \
    # Web: directory busting, fuzzing, sqli, vuln scanners
    gobuster dirb wfuzz nikto sqlmap whatweb \
    # Brute force / cracking de contraseñas y hashes
    hydra john hashcat crunch ncrack medusa \
    # SMB / AD / Windows-side
    smbclient samba-common-bin enum4linux ldap-utils \
    # SNMP / SSL / DNS extra
    snmp snmp-mibs-downloader \
    sslscan \
    dnsenum dnsrecon \
    # Exploit DB (provee `searchsploit`)
    exploitdb \
    # Forense / esteganografía / binarios
    binwalk steghide foremost libimage-exiftool-perl radare2 \
    # Web proxies / interceptación
    mitmproxy \
    # Misc útiles
    proxychains4 tor stunnel4 socat openssl gnupg \
    && apt-get clean && rm -rf /var/lib/apt/lists/* /var/cache/apt/* /tmp/*

# Diccionarios SecLists (muy comunes en CTF / web fuzzing). Lo clonamos
# shallow para mantener tamaño razonable. Ruta: /opt/SecLists.
RUN git clone --depth 1 https://github.com/danielmiessler/SecLists.git /opt/SecLists \
    && rm -rf /opt/SecLists/.git

# Symlink novnc landing para que /vnc/ funcione
RUN ln -sf /usr/share/novnc/vnc.html /usr/share/novnc/index.html

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip3 install --break-system-packages --no-cache-dir -r /app/requirements.txt \
    && rm -rf /root/.cache /tmp/* /var/tmp/*

# Librerías Python comunes para scripting de seguridad / CTF.
# Una capa separada para no invalidar cache cuando solo cambia el código.
RUN pip3 install --break-system-packages --no-cache-dir \
    impacket \
    pwntools \
    scapy \
    requests \
    beautifulsoup4 \
    lxml \
    dnspython \
    paramiko \
    pycryptodome \
    pyOpenSSL \
    && rm -rf /root/.cache /tmp/* /var/tmp/*

COPY agent /app/agent
COPY docker/firefox-profile /app/firefox-profile
COPY docker/start.sh /app/start.sh
# Eliminar CR en caso de checkout en Windows con CRLF
RUN sed -i 's/\r$//' /app/start.sh && chmod +x /app/start.sh

ENV PORT=8000
EXPOSE 8000

ENTRYPOINT ["/app/start.sh"]
