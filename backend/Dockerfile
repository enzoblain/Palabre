# Base image pinned by digest (tag kept for readers); bump both together
FROM python:3.12-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337

# Extra system packages the agents need to build and test your projects
# (e.g. "nodejs npm" or "golang"). git and Python are always there.
ARG EXTRA_APT_PACKAGES=""
# Claude Code: an exact version and the SHA-256 of its binary for each architecture, from
# https://downloads.claude.ai/claude-code-releases/<version>/manifest.json. To bump: change the
# three values together (a version without matching checksums fails the build).
ARG CLAUDE_CODE_VERSION=2.1.308
ARG CLAUDE_CODE_SHA256_X64=356733f185fa988e6bf3aa9a555269fdd167982a2e2a80d3c8a78037bb92ad58
ARG CLAUDE_CODE_SHA256_ARM64=fdd22e6cbb734d580f5664c48df4294eeec850218ff07f186f9af30426396ee1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git procps sudo tzdata ${EXTRA_APT_PACKAGES} \
    && rm -rf /var/lib/apt/lists/*

# Two users: palabre runs the backend (database, GitHub token, Claude tokens), agent runs the
# agents' `claude` processes. They share the group "work" for the files agents work in.
RUN groupadd --gid 1002 work \
    && useradd --create-home --uid 1000 --groups work palabre \
    && useradd --create-home --uid 1001 --groups work agent \
    && chmod 711 /home/palabre \
    && mkdir -p /data /srv \
    && chown palabre:palabre /data /srv

# The only things palabre may do as agent: run the claude binary, kill a process group
# of the agent's own, and delete a clone (a root-owned sudo cannot be signalled by palabre). Nothing else.
# !use_pty keeps claude in sudo's process group, so the group kill reaches it.
# !secure_path: the agent's PATH (with the toolchains) is set by the backend.
# The umask makes the agents' files writable by the backend.
# rm-clone deletes a desk or task clone (files the agent made outside the group): root-owned
# script that only accepts a clone path, so the rule is not a general rm.
COPY --chmod=755 scripts/rm-clone.sh /usr/local/bin/palabre-rm-clone
RUN printf '%s\n' \
      'Defaults:palabre !requiretty, !use_pty, !secure_path, umask=0002, umask_override' \
      'palabre ALL=(agent) NOPASSWD:SETENV: /home/palabre/.local/bin/claude' \
      'palabre ALL=(agent) NOPASSWD: /usr/bin/kill -KILL -- -[0-9]*' \
      'palabre ALL=(agent) NOPASSWD: /usr/local/bin/palabre-rm-clone /data/projects/*' \
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
    AGENT_USER=agent \
    PYTHONUNBUFFERED=1

# Native binary (no Node.js needed), downloaded from the official bucket and checked against the
# pinned checksum before it runs; install.sh is not used because it follows "latest"
RUN set -eu; \
    case "$(uname -m)" in \
      x86_64) platform=linux-x64; sha=${CLAUDE_CODE_SHA256_X64} ;; \
      aarch64) platform=linux-arm64; sha=${CLAUDE_CODE_SHA256_ARM64} ;; \
      *) echo "Unsupported architecture: $(uname -m)" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /tmp/claude "https://downloads.claude.ai/claude-code-releases/${CLAUDE_CODE_VERSION}/${platform}/claude"; \
    echo "${sha}  /tmp/claude" | sha256sum -c -; \
    chmod +x /tmp/claude; \
    /tmp/claude install "${CLAUDE_CODE_VERSION}"; \
    rm -f /tmp/claude; \
    installed=$(sha256sum "$(readlink -f "$(command -v claude)")" | cut -d" " -f1); \
    [ "$installed" = "${sha}" ] || { echo "The installed claude is not the checked binary" >&2; exit 1; }; \
    claude --version
# The agent runs the binary but cannot change it
RUN chmod -R go+rX /home/palabre/.local

COPY --chown=palabre:palabre app ./app
COPY --chmod=755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY --chmod=755 scripts ./scripts

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
