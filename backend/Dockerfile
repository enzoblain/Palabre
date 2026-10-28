FROM python:3.12-slim-bookworm

# Extra system packages the agents need to build and test your projects
# (e.g. "nodejs npm" or "golang"). git and Python are always there.
ARG EXTRA_APT_PACKAGES=""
# Claude Code version: "stable", "latest" or an exact version
ARG CLAUDE_CODE_VERSION=stable

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git tzdata ${EXTRA_APT_PACKAGES} \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 palabre \
    && mkdir -p /data /srv \
    && chown palabre:palabre /data /srv

WORKDIR /srv
COPY requirements.txt .
# Frozen, hash-checked dependencies (see "Dependencies" in the README)
RUN pip install --no-cache-dir --require-hashes -r requirements.txt

USER palabre
# Claude sessions (needed for --resume) live in the /data volume
ENV HOME=/home/palabre \
    PATH=/home/palabre/.local/bin:$PATH \
    CLAUDE_CONFIG_DIR=/data/claude \
    DISABLE_AUTOUPDATER=1 \
    PYTHONUNBUFFERED=1

# Native installer: no Node.js needed
RUN curl -fsSL https://claude.ai/install.sh | bash -s -- ${CLAUDE_CODE_VERSION} \
    && claude --version

COPY --chown=palabre:palabre app ./app

VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"

# A single worker: the orchestrator runs inside the process
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
