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

# Habilitar contrib + non-free para que apt vea nikto/enum4linux/snmp-mibs-downloader.
# Soporta tanto el formato legacy sources.list como el nuevo deb822
# /etc/apt/sources.list.d/debian.sources (Debian 12 lo usa).
RUN if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i 's/^Components: main$/Components: main contrib non-free non-free-firmware/' /etc/apt/sources.list.d/debian.sources; \
    fi; \
    if [ -f /etc/apt/sources.list ]; then \
        sed -i 's/ main$/ main contrib non-free non-free-firmware/' /etc/apt/sources.list || true; \
    fi

# ─── Toolbox de seguridad / pentesting ───────────────────────────────────────
# Cubre recon de red, scanning, web testing, brute force, SMB/AD, forense.
# Solo herramientas en repos oficiales Debian (main + contrib + non-free).
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
    # Forense / esteganografía / binarios (rizin = fork mantenido de radare2)
    binwalk steghide foremost libimage-exiftool-perl rizin \
    # Web proxies / interceptación
    mitmproxy \
    # Misc útiles
    proxychains4 tor stunnel4 socat openssl gnupg \
    && apt-get clean && rm -rf /var/lib/apt/lists/* /var/cache/apt/* /tmp/*

# Exploit-DB no está en repos Debian. Lo clonamos shallow y enlazamos
# searchsploit en /usr/local/bin/.
RUN git clone --depth 1 https://gitlab.com/exploit-database/exploitdb.git /opt/exploitdb \
    && ln -sf /opt/exploitdb/searchsploit /usr/local/bin/searchsploit \
    && rm -rf /opt/exploitdb/.git

# Diccionarios SecLists (muy comunes en CTF / web fuzzing). Lo clonamos
# shallow para mantener tamaño razonable. Ruta: /opt/SecLists.
RUN git clone --depth 1 https://github.com/danielmiessler/SecLists.git /opt/SecLists \
    && rm -rf /opt/SecLists/.git

# ─── Toolbox OSINT ───────────────────────────────────────────────────────────
# theHarvester (apt) recolecta emails, subdominios, IPs e info de fuentes
# públicas. El resto (subfinder/httpx/nuclei/etc.) son binarios Go pre-built
# que descargamos de GitHub Releases — más rápidos y portables que apt.
RUN apt-get update && apt-get install -y --no-install-recommends \
    theharvester \
    && apt-get clean && rm -rf /var/lib/apt/lists/* /var/cache/apt/* /tmp/*

# Python OSINT
RUN pip3 install --break-system-packages --no-cache-dir \
    sherlock-project \
    holehe \
    socialscan \
    shodan \
    censys \
    waybackpy \
    && rm -rf /root/.cache /tmp/* /var/tmp/*

# Go binaries (proyectos de ProjectDiscovery + tomnomnom + gitleaks).
# Versiones pinneadas para builds reproducibles. Si quieres actualizar,
# busca la última release en cada repo.
ARG SUBFINDER_VER=2.6.7
ARG HTTPX_VER=1.6.10
ARG NUCLEI_VER=3.3.10
ARG GITLEAKS_VER=8.21.2
ARG GAU_VER=2.2.4
RUN set -eux; \
    cd /tmp; \
    curl -sSL "https://github.com/projectdiscovery/subfinder/releases/download/v${SUBFINDER_VER}/subfinder_${SUBFINDER_VER}_linux_amd64.zip" -o subfinder.zip; \
    unzip -q subfinder.zip && mv subfinder /usr/local/bin/ && rm subfinder.zip; \
    curl -sSL "https://github.com/projectdiscovery/httpx/releases/download/v${HTTPX_VER}/httpx_${HTTPX_VER}_linux_amd64.zip" -o httpx.zip; \
    unzip -q httpx.zip && mv httpx /usr/local/bin/ && rm httpx.zip; \
    curl -sSL "https://github.com/projectdiscovery/nuclei/releases/download/v${NUCLEI_VER}/nuclei_${NUCLEI_VER}_linux_amd64.zip" -o nuclei.zip; \
    unzip -q nuclei.zip && mv nuclei /usr/local/bin/ && rm nuclei.zip; \
    curl -sSL "https://github.com/tomnomnom/assetfinder/releases/download/v0.1.1/assetfinder-linux-amd64-0.1.1.tgz" -o assetfinder.tgz; \
    tar -xzf assetfinder.tgz && mv assetfinder /usr/local/bin/ && rm assetfinder.tgz; \
    curl -sSL "https://github.com/tomnomnom/waybackurls/releases/download/v0.1.0/waybackurls-linux-amd64-0.1.0.tgz" -o wayback.tgz; \
    tar -xzf wayback.tgz && mv waybackurls /usr/local/bin/ && rm wayback.tgz; \
    curl -sSL "https://github.com/lc/gau/releases/download/v${GAU_VER}/gau_${GAU_VER}_linux_amd64.tar.gz" -o gau.tgz; \
    tar -xzf gau.tgz gau && mv gau /usr/local/bin/ && rm gau.tgz; \
    curl -sSL "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VER}/gitleaks_${GITLEAKS_VER}_linux_x64.tar.gz" -o gitleaks.tgz; \
    tar -xzf gitleaks.tgz gitleaks && mv gitleaks /usr/local/bin/ && rm gitleaks.tgz; \
    chmod +x /usr/local/bin/subfinder /usr/local/bin/httpx /usr/local/bin/nuclei \
             /usr/local/bin/assetfinder /usr/local/bin/waybackurls /usr/local/bin/gau \
             /usr/local/bin/gitleaks

# Pre-actualizar templates de nuclei (~50MB) — primer scan no espera la descarga
RUN nuclei -update-templates -silent || true

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
