# G2 Agent Container
# Runs Claude Agent SDK in isolated Linux VM with browser automation

FROM python:3.12-slim

# Install system dependencies for Chromium + Node (for claude-code CLI)
RUN apt-get update && apt-get install -y \
    chromium \
    fonts-liberation \
    fonts-noto-color-emoji \
    libgbm1 \
    libnss3 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libasound2 \
    libpangocairo-1.0-0 \
    libcups2 \
    libdrm2 \
    libxshmfence1 \
    curl \
    git \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Default timezone — overridden at runtime by host's TZ via -e flag.
ENV TZ=UTC

# Set Chromium path for agent-browser
ENV AGENT_BROWSER_EXECUTABLE_PATH=/usr/bin/chromium
ENV PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium

# Install claude-code CLI globally (Node-based)
RUN npm install -g @anthropic-ai/claude-code agent-browser

# Create app directory
WORKDIR /app

# Copy agent runner
COPY agent-runner/src/main.py ./main.py

# Create workspace directories
RUN mkdir -p /workspace/group /workspace/global /workspace/extra /workspace/ipc/messages /workspace/ipc/tasks /workspace/ipc/input

# Create entrypoint script
# Secrets are passed via stdin JSON — temp file is deleted immediately after Python reads it
# Follow-up messages arrive via IPC files in /workspace/ipc/input/
RUN printf '#!/bin/bash\nset -e\ncat > /tmp/input.json\npython3 /app/main.py < /tmp/input.json\nrm -f /tmp/input.json\n' > /app/entrypoint.sh && chmod +x /app/entrypoint.sh

# Create non-root user
RUN useradd -m -u 1000 agent
RUN chown -R agent:agent /workspace && chmod 777 /home/agent

# Switch to non-root user
USER agent

# Set working directory to group workspace
WORKDIR /workspace/group

# Entry point reads JSON from stdin, outputs JSON to stdout
ENTRYPOINT ["/app/entrypoint.sh"]
