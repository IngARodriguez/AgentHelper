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
    # SMB / AD / Windows-side (enum4linux-ng via pip más abajo)
    smbclient samba-common-bin ldap-utils \
    # SNMP / SSL / DNS extra
    snmp snmp-mibs-downloader \
    sslscan \
    dnsenum dnsrecon \
    # Forense / esteganografía / binarios. Para reversing básico tenemos
    # xxd/strings/objdump/readelf via binutils (ya en build-essential).
    binwalk steghide foremost libimage-exiftool-perl \
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
# theHarvester ya no está empaquetado en Debian bookworm — lo instalamos vía
# pip junto con el resto de OSINT Python. El resto (subfinder/httpx/nuclei/etc.)
# son binarios Go pre-built que descargamos de GitHub Releases más abajo.
RUN pip3 install --break-system-packages --no-cache-dir \
    theHarvester \
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
# Cada extracción usa su propio dir para evitar colisiones (LICENSE.md, README.md
# repiten entre proyectos y unzip pediría confirmación interactiva).
RUN set -eux; \
    workdir=$(mktemp -d); cd "$workdir"; \
    fetch_zip() { \
        curl -sSL "$2" -o pkg.zip; \
        rm -rf extract && mkdir extract; \
        unzip -qo pkg.zip -d extract; \
        mv "extract/$1" /usr/local/bin/; \
        chmod +x "/usr/local/bin/$1"; \
        rm -rf pkg.zip extract; \
    }; \
    fetch_tgz() { \
        curl -sSL "$2" -o pkg.tgz; \
        rm -rf extract && mkdir extract; \
        tar -xzf pkg.tgz -C extract; \
        mv "extract/$1" /usr/local/bin/; \
        chmod +x "/usr/local/bin/$1"; \
        rm -rf pkg.tgz extract; \
    }; \
    fetch_zip subfinder    "https://github.com/projectdiscovery/subfinder/releases/download/v${SUBFINDER_VER}/subfinder_${SUBFINDER_VER}_linux_amd64.zip"; \
    fetch_zip httpx        "https://github.com/projectdiscovery/httpx/releases/download/v${HTTPX_VER}/httpx_${HTTPX_VER}_linux_amd64.zip"; \
    fetch_zip nuclei       "https://github.com/projectdiscovery/nuclei/releases/download/v${NUCLEI_VER}/nuclei_${NUCLEI_VER}_linux_amd64.zip"; \
    fetch_tgz assetfinder  "https://github.com/tomnomnom/assetfinder/releases/download/v0.1.1/assetfinder-linux-amd64-0.1.1.tgz"; \
    fetch_tgz waybackurls  "https://github.com/tomnomnom/waybackurls/releases/download/v0.1.0/waybackurls-linux-amd64-0.1.0.tgz"; \
    fetch_tgz gau          "https://github.com/lc/gau/releases/download/v${GAU_VER}/gau_${GAU_VER}_linux_amd64.tar.gz"; \
    fetch_tgz gitleaks     "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VER}/gitleaks_${GITLEAKS_VER}_linux_x64.tar.gz"; \
    cd / && rm -rf "$workdir"

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
# enum4linux-ng = rewrite Python de enum4linux (el Perl original fue removido
# de Debian bookworm).
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
    enum4linux-ng \
    && rm -rf /root/.cache /tmp/* /var/tmp/*

COPY agent /app/agent
COPY docker/firefox-profile /app/firefox-profile
COPY docker/start.sh /app/start.sh
# Eliminar CR en caso de checkout en Windows con CRLF
RUN sed -i 's/\r$//' /app/start.sh && chmod +x /app/start.sh

ENV PORT=8000
EXPOSE 8000

ENTRYPOINT ["/app/start.sh"]
