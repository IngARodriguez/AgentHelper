FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DISPLAY=:1 \
    MOZ_DISABLE_CONTENT_SANDBOX=1

# Lista mínima: lo justo para Xvfb + Firefox + xdotool + scrot + noVNC + Python
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    xvfb \
    x11vnc \
    x11-utils \
    xdotool \
    scrot \
    fluxbox \
    xfonts-base \
    xauth \
    xterm \
    novnc \
    firefox-esr \
    ca-certificates \
    curl \
    wget \
    jq \
    nano \
    unzip \
    procps \
    net-tools \
    iputils-ping \
    dnsutils \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/* /tmp/*

# Symlink novnc landing para que /vnc/ funcione
RUN ln -sf /usr/share/novnc/vnc.html /usr/share/novnc/index.html

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip3 install --break-system-packages --no-cache-dir -r /app/requirements.txt \
    && rm -rf /root/.cache /tmp/* /var/tmp/*

COPY agent /app/agent
COPY docker/firefox-profile /app/firefox-profile
COPY docker/start.sh /app/start.sh
# Eliminar CR en caso de checkout en Windows con CRLF
RUN sed -i 's/\r$//' /app/start.sh && chmod +x /app/start.sh

# Railway pisará PORT; en local default 8000
ENV PORT=8000
EXPOSE 8000

ENTRYPOINT ["/app/start.sh"]
