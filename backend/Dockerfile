FROM python:3.12-slim-bookworm

# Extra system packages the agents need to build and test your projects
# (e.g. "nodejs npm" or "golang"). git and Python are always there.
ARG EXTRA_APT_PACKAGES=""
# Claude Code version: "stable", "latest" or an exact version
ARG CLAUDE_CODE_VERSION=stable

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git sudo tzdata ${EXTRA_APT_PACKAGES} \
    && rm -rf /var/lib/apt/lists/*

# Two users: palabre runs the backend (database, GitHub token, Claude tokens), agent runs the
# agents' `claude` processes. They share the group "work" for the files agents work in.
RUN groupadd --gid 1002 work \
    && useradd --create-home --uid 1000 --groups work palabre \
    && useradd --create-home --uid 1001 --groups work agent \
    && chmod 711 /home/palabre \
    && mkdir -p /data /srv \
    && chown palabre:palabre /data /srv

# The only thing palabre may do as agent: run the claude binary, nothing else.
# The umask makes the agents' files writable by the backend.
RUN printf '%s\n' \
      'Defaults:palabre !requiretty, umask=0002, umask_override' \
      'palabre ALL=(agent) NOPASSWD:SETENV: /home/palabre/.local/bin/claude' \
      > /etc/sudoers.d/palabre-agent \
    && chmod 440 /etc/sudoers.d/palabre-agent \
    && visudo -cf /etc/sudoers.d/palabre-agent

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
# The agent runs the binary but cannot change it
RUN chmod -R go+rX /home/palabre/.local

COPY --chown=palabre:palabre app ./app
COPY --chmod=755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# Root only for the entrypoint, which fixes /data's permissions and then drops to palabre.
# The toolchains directory is never in the backend's PATH (only in the agents').
USER root

VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"

# A single worker: the orchestrator runs inside the process
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
