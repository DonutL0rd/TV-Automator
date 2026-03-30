# ── TV-Automator Docker Image ────────────────────────────────────
# Lightweight Ubuntu base with Google Chrome, Python, Playwright,
# and a minimal window manager for HDMI kiosk output.
# ─────────────────────────────────────────────────────────────────

FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=en_US.UTF-8
ENV TZ=America/New_York

# ── System packages ─────────────────────────────────────────────

RUN apt-get update && apt-get install -y --no-install-recommends \
    # Core
    ca-certificates curl gnupg wget \
    # Python
    python3.11 python3.11-venv python3-pip \
    # Display / Window manager
    xdg-utils openbox xdotool x11-utils \
    # SSH server (for TUI access)
    openssh-server \
    # Audio (for game audio via HDMI)
    pulseaudio alsa-utils \
    # Fonts
    fonts-liberation fonts-noto \
    # Misc
    locales dbus-x11 \
    && rm -rf /var/lib/apt/lists/*

# Set locale
RUN locale-gen en_US.UTF-8

# ── Google Chrome (for Widevine DRM support) ────────────────────

RUN curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
    | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] \
    http://dl.google.com/linux/chrome/deb/ stable main" \
    > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# ── Python setup ────────────────────────────────────────────────

# Make python3.11 the default
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1

# Create a venv for the app
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python deps
COPY pyproject.toml /app/
WORKDIR /app
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir . 2>/dev/null || true

# Install Playwright browsers (chromium — used as fallback only)
# Chrome itself is already installed system-wide
RUN pip install --no-cache-dir playwright \
    && playwright install --with-deps chromium

# ── Copy application code ──────────────────────────────────────

COPY src/ /app/src/
COPY config/ /app/config/

# Install the app itself
RUN pip install --no-cache-dir -e .

# ── SSH configuration ──────────────────────────────────────────

RUN mkdir -p /run/sshd \
    && echo "PermitRootLogin yes" >> /etc/ssh/sshd_config \
    && echo "PasswordAuthentication yes" >> /etc/ssh/sshd_config \
    && echo "root:tvautomator" | chpasswd

EXPOSE 22

# ── Openbox configuration ─────────────────────────────────────

RUN mkdir -p /root/.config/openbox
COPY docker/openbox-config/rc.xml /root/.config/openbox/rc.xml

# ── Data volume ────────────────────────────────────────────────

VOLUME /data
ENV DATA_DIR=/data

# ── Entrypoint ─────────────────────────────────────────────────

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
