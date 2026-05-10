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

# enum4linux-ng — rewrite Python del enum4linux clásico (el Perl original
# fue removido de Debian bookworm). El paquete `enum4linux-ng` de PyPI es un
# squatter, lo clonamos del repo oficial.
RUN git clone --depth 1 https://github.com/cddmp/enum4linux-ng.git /opt/enum4linux-ng \
    && ln -sf /opt/enum4linux-ng/enum4linux-ng.py /usr/local/bin/enum4linux-ng \
    && chmod +x /opt/enum4linux-ng/enum4linux-ng.py \
    && rm -rf /opt/enum4linux-ng/.git

# ─── Apt extras: pentesting + debugging + QoL ────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    aircrack-ng \
    gdb \
    ltrace strace \
    ruby ruby-dev make pkg-config \
    libcurl4-openssl-dev libxml2-dev libxslt1-dev zlib1g-dev \
    bat fzf httpie ripgrep \
    && apt-get clean && rm -rf /var/lib/apt/lists/* /var/cache/apt/* /tmp/*

# Responder no está en repos Debian, lo clonamos del repo oficial.
RUN git clone --depth 1 https://github.com/lgandx/Responder.git /opt/Responder \
    && ln -sf /opt/Responder/Responder.py /usr/local/bin/responder \
    && chmod +x /opt/Responder/Responder.py \
    && rm -rf /opt/Responder/.git

# ─── Gems: WPScan + Evil-WinRM ───────────────────────────────────────────────
RUN gem install --no-document wpscan evil-winrm \
    && rm -rf /tmp/* /var/tmp/* /usr/lib/ruby/gems/*/cache

# ─── Pip: AD pentesting + web exploitation + binary + forensics + cloud ──────
# bloodhound = ingestor Python para BloodHound (mapeo de ataque AD)
# certipy-ad = explotación de AD CS (ESC1-ESC11 y derivados)
# pypykatz = mimikatz puro Python (extracción credenciales offline)
# coercer = forzar autenticación SMB de víctimas (PetitPotam, PrinterBug...)
# arjun = HTTP parameter discovery
# commix = command injection scanner
# dirsearch = brute force de paths (alternativa moderna a dirb)
# ROPgadget = búsqueda de gadgets ROP en binarios
# hashid = identificación de tipo de hash
# volatility3 = análisis forense de memoria (RAM dumps)
# awscli = AWS CLI (cloud pentesting)
RUN pip3 install --break-system-packages --no-cache-dir \
    bloodhound \
    certipy-ad \
    pypykatz \
    coercer \
    arjun \
    commix \
    dirsearch \
    ROPgadget \
    hashid \
    volatility3 \
    awscli \
    && rm -rf /root/.cache /tmp/* /var/tmp/*

# NetExec (rebrand de crackmapexec, swiss army de AD) — solo se instala
# desde git según los docs oficiales. Capa propia para no invalidar la de
# arriba si NetExec falla por alguna dep.
RUN pip3 install --break-system-packages --no-cache-dir \
    git+https://github.com/Pennyw0rth/NetExec.git \
    && rm -rf /root/.cache /tmp/* /var/tmp/*

# ─── GEF: extensión moderna para gdb (CTF binary pwn) ────────────────────────
RUN curl -sSL https://gef.blah.cat/py -o /opt/gef.py \
    && echo "source /opt/gef.py" > /root/.gdbinit

# ─── Go binaries: web fuzzing avanzado, crawler, scanners, AD, pivoting ──────
ARG FFUF_VER=2.1.0
ARG KATANA_VER=1.1.2
ARG NAABU_VER=2.3.4
ARG DNSX_VER=1.2.2
ARG DALFOX_VER=2.10.0
ARG KERBRUTE_VER=1.0.3
ARG CHISEL_VER=1.10.1
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
    fetch_tgz ffuf      "https://github.com/ffuf/ffuf/releases/download/v${FFUF_VER}/ffuf_${FFUF_VER}_linux_amd64.tar.gz"; \
    fetch_zip katana    "https://github.com/projectdiscovery/katana/releases/download/v${KATANA_VER}/katana_${KATANA_VER}_linux_amd64.zip"; \
    fetch_zip naabu     "https://github.com/projectdiscovery/naabu/releases/download/v${NAABU_VER}/naabu_${NAABU_VER}_linux_amd64.zip"; \
    fetch_zip dnsx      "https://github.com/projectdiscovery/dnsx/releases/download/v${DNSX_VER}/dnsx_${DNSX_VER}_linux_amd64.zip"; \
    fetch_tgz dalfox    "https://github.com/hahwul/dalfox/releases/download/v${DALFOX_VER}/dalfox_${DALFOX_VER}_linux_amd64.tar.gz"; \
    cd / && rm -rf "$workdir"; \
    # kerbrute: binario directo, no archive
    curl -sSL "https://github.com/ropnop/kerbrute/releases/download/v${KERBRUTE_VER}/kerbrute_linux_amd64" -o /usr/local/bin/kerbrute; \
    chmod +x /usr/local/bin/kerbrute; \
    # chisel: gz comprimido con un solo binario
    curl -sSL "https://github.com/jpillora/chisel/releases/download/v${CHISEL_VER}/chisel_${CHISEL_VER}_linux_amd64.gz" -o /tmp/chisel.gz; \
    gzip -d /tmp/chisel.gz; \
    mv /tmp/chisel /usr/local/bin/chisel; \
    chmod +x /usr/local/bin/chisel

# ─── Apt extras 2: cewl (wordlist generator) + libpcap headers ───────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    cewl \
    libpcap-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/* /var/cache/apt/* /tmp/*

# ─── Pip OSINT/web/AD adicionales ────────────────────────────────────────────
# mitm6: spoofing IPv6 + WPAD para AD
# ldapdomaindump: dump completo info LDAP (users, computers, GPO, ACLs)
# bloodyAD: alternativa a bloodhound-python con ataques offensive built-in
# wafw00f: detección de WAF (whatwaf no está en PyPI, wafw00f es el estándar)
# s3scanner: enum buckets S3 abiertos
RUN pip3 install --break-system-packages --no-cache-dir \
    mitm6 \
    ldapdomaindump \
    bloodyAD \
    wafw00f \
    s3scanner \
    && rm -rf /root/.cache /tmp/* /var/tmp/*

# paramspider no está en PyPI con ese nombre — install desde git oficial.
# Capa propia para que un fallo aquí no invalide la de arriba.
RUN pip3 install --break-system-packages --no-cache-dir \
    git+https://github.com/devanshbatham/ParamSpider.git \
    && rm -rf /root/.cache /tmp/* /var/tmp/*

# ─── XSStrike: XSS scanner avanzado con bypass de WAF ────────────────────────
RUN git clone --depth 1 https://github.com/s0md3v/XSStrike.git /opt/XSStrike \
    && pip3 install --break-system-packages --no-cache-dir -r /opt/XSStrike/requirements.txt \
    && printf '#!/bin/bash\ncd /opt/XSStrike && python3 xsstrike.py "$@"\n' > /usr/local/bin/xsstrike \
    && chmod +x /usr/local/bin/xsstrike \
    && rm -rf /opt/XSStrike/.git

# ─── RsaCtfTool: ataques automáticos a RSA débil (CTF crypto) ────────────────
RUN git clone --depth 1 https://github.com/RsaCtfTool/RsaCtfTool.git /opt/RsaCtfTool \
    && pip3 install --break-system-packages --no-cache-dir -r /opt/RsaCtfTool/requirements.txt 2>/dev/null || true \
    && printf '#!/bin/bash\ncd /opt/RsaCtfTool && python3 RsaCtfTool.py "$@"\n' > /usr/local/bin/rsactftool \
    && chmod +x /usr/local/bin/rsactftool \
    && rm -rf /opt/RsaCtfTool/.git

# ─── Más Go/Rust binarios: feroxbuster, gowitness, subzy, trufflehog ─────────
ARG FEROX_VER=2.11.0
ARG GOWITNESS_VER=3.0.5
ARG SUBZY_VER=2.2.6
ARG TRUFFLEHOG_VER=3.83.7
RUN set -eux; \
    workdir=$(mktemp -d); cd "$workdir"; \
    fetch_zip() { \
        curl -sSL "$2" -o pkg.zip; \
        rm -rf extract && mkdir extract; \
        unzip -qo pkg.zip -d extract; \
        # Algunos paquetes meten el binario en subdir o con sufijo
        if [ -f "extract/$1" ]; then mv "extract/$1" /usr/local/bin/; \
        else find extract -type f -name "$1*" -executable -exec mv {} /usr/local/bin/$1 \; ; fi; \
        chmod +x "/usr/local/bin/$1"; \
        rm -rf pkg.zip extract; \
    }; \
    fetch_tgz() { \
        curl -sSL "$2" -o pkg.tgz; \
        rm -rf extract && mkdir extract; \
        tar -xzf pkg.tgz -C extract; \
        if [ -f "extract/$1" ]; then mv "extract/$1" /usr/local/bin/; \
        else find extract -type f -name "$1*" -executable -exec mv {} /usr/local/bin/$1 \; ; fi; \
        chmod +x "/usr/local/bin/$1"; \
        rm -rf pkg.tgz extract; \
    }; \
    # feroxbuster — Rust, recursive content discovery
    fetch_zip feroxbuster "https://github.com/epi052/feroxbuster/releases/download/v${FEROX_VER}/x86_64-linux-feroxbuster.zip"; \
    # subzy — subdomain takeover scanner
    fetch_tgz subzy       "https://github.com/PentestPad/subzy/releases/download/v${SUBZY_VER}/subzy_${SUBZY_VER}_linux_amd64.tgz"; \
    # trufflehog — secret scanner agresivo (más completo que gitleaks)
    fetch_tgz trufflehog  "https://github.com/trufflesecurity/trufflehog/releases/download/v${TRUFFLEHOG_VER}/trufflehog_${TRUFFLEHOG_VER}_linux_amd64.tar.gz"; \
    # gowitness — screenshot URLs at scale (recon visual)
    curl -sSL "https://github.com/sensepost/gowitness/releases/download/${GOWITNESS_VER}/gowitness-${GOWITNESS_VER}-linux-amd64" -o /usr/local/bin/gowitness; \
    chmod +x /usr/local/bin/gowitness; \
    cd / && rm -rf "$workdir"

COPY agent /app/agent
COPY docker/firefox-profile /app/firefox-profile
COPY docker/start.sh /app/start.sh
# Eliminar CR en caso de checkout en Windows con CRLF
RUN sed -i 's/\r$//' /app/start.sh && chmod +x /app/start.sh

ENV PORT=8000
EXPOSE 8000

ENTRYPOINT ["/app/start.sh"]
