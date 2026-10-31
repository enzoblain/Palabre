"""Settings read from environment variables and, for secrets, from files (Docker secrets)."""

import os
from pathlib import Path
from urllib.parse import quote

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SECRETS_DIR = Path(os.environ.get("PALABRE_SECRETS_DIR", "/run/palabre-secrets"))

# Brute-force floor for the secrets that guard the API and the database
MIN_SECRET_LENGTH = 32


class Settings(BaseSettings):
    # Secrets (admin_token, github_token, claude_code_oauth_tokens, postgres_password) are
    # files here, not environment variables: the entrypoint copies them for the backend only
    # hide_input_in_errors: a model-level error would otherwise print every field, secrets included
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        secrets_dir=SECRETS_DIR if SECRETS_DIR.is_dir() else None,
        hide_input_in_errors=True,
    )

    database_url: str = "postgresql+asyncpg://palabre:palabre@localhost:5432/palabre"
    # With a password (the compose setup), the URL is built from these instead
    postgres_password: str | None = None
    postgres_user: str = "palabre"
    postgres_db: str = "palabre"
    postgres_host: str = "db"
    # Protects the REST API (Authorization: Bearer <ADMIN_TOKEN>)
    # Default + validate_default: Compose mounts no file for an empty secret, so an absent token
    # must hit the blank check too (an unvalidated "" default would leave the API open)
    admin_token: str = Field("", validate_default=True)
    # Failed API authentications from one IP within auth_fail_window_seconds before it is
    # answered 429 (and so even with a valid token) until the window has passed
    auth_max_failures: int = 10
    auth_fail_window_seconds: int = 300
    # Hosts whose X-Real-IP is believed (the web container's nginx); the server port is published, so never "*"
    trusted_proxy_hosts: list[str] = ["web"]
    # Origins allowed to call the API from a browser (the desktop app's dev server)
    cors_origins: list[str] = ["*"]
    # Used by the backend only (push, pull requests, merges). Never given to agents.
    github_token: str | None = None
    projects_dir: Path = Path("/data/projects")
    # Temporary files of runs (MCP configs), kept outside the repositories
    runtime_dir: Path = Path("/data/runtime")
    # System user the agents' `claude` runs as, through sudo (see "Security" in the README).
    # Empty = same user as the backend (desktop app, local dev without sudo).
    agent_user: str = ""
    # Number of per-run accounts `<agent_user>1..N` (0 = every run shares agent_user). A run takes
    # a free one for its whole life, so no two live runs share a uid (see "Security" in the README).
    agent_pool_size: int = 0
    # The backend's private store of Claude sessions, one directory per employee (default: CLAUDE_CONFIG_DIR)
    claude_store_dir: Path | None = None
    # Holds the MCP configs of runs when the agent user must read them (runtime_dir is the backend's only)
    agent_run_dir: Path = Path("/data/run")
    # Agents reach the Internet only through this local CONNECT proxy (the entrypoint's firewall
    # drops their other connections): the Anthropic API and the package registries of the toolchains
    egress_proxy_port: int = 3128
    egress_allowed_ports: list[int] = [443]
    # Concurrent tunnels the proxy serves: an agent cannot starve the server's event loop and file descriptors
    egress_max_tunnels: int = 64
    egress_allowed_hosts: list[str] = [
        "statsig.anthropic.com", "registry.npmjs.org", "pypi.org",
        "files.pythonhosted.org", "proxy.golang.org", "sum.golang.org",
    ]
    # Claude Code talks to this local reverse proxy (ANTHROPIC_BASE_URL), which holds the account token
    anthropic_proxy_url: str = "http://127.0.0.1:8000/anthropic"
    anthropic_api_url: str = "https://api.anthropic.com"
    # API paths the proxy forwards; server tools (type prefixes) a request may declare
    anthropic_allowed_paths: list[str] = ["v1/messages", "api/"]
    anthropic_allowed_server_tools: list[str] = ["web_search"]
    anthropic_max_body_bytes: int = 64 * 1024 * 1024
    anthropic_timeout_s: int = 600
    # Toolchains installed by the agents (install_toolchain), shared by the whole team
    toolchains_dir: Path = Path("/data/toolchains")

    # Agents (`claude -p`, billed on Claude subscriptions). One token per account,
    # separated by "|": the employees are spread over the accounts.
    claude_code_oauth_tokens: str = ""
    claude_bin: str = "claude"
    # Turns per run: a conversation turn is short, work on a task can take long
    claude_max_turns: int = 20
    claude_task_max_turns: int = 100
    agent_timeout_s: int = 1800
    # Seen from the `claude` processes, which run in the backend container
    mcp_url: str = "http://127.0.0.1:8000/mcp/"

    # Orchestrator
    orchestrator_enabled: bool = True
    poll_interval_s: float = 2.0
    # Per Claude account
    max_concurrent_agents: int = 3
    # Rounds of "changes requested" on a task before the lead has to step in
    max_review_rounds: int = 3
    # Tasks finished (merged or cancelled) by an employee before their next run starts on a blank
    # context, without resuming their Claude sessions; 0 = never
    context_reset_every_tasks: int = 5
    # Runs one Claude session (conversation or task) serves before the next one starts on a new session,
    # as a resumed session gets costlier at each run; 0 = never. The employee's other sessions are kept
    context_reset_every_runs: int = 5
    # Chatter runs per employee per hour (all conversations); past it, their wakeups wait for the window to free
    max_runs_per_conversation_hour: int = 20
    # Local time of the daily stand-up ("HH:MM"), empty to disable
    daily_time: str = "09:30"
    # Quiet minutes before the scribe is asked to update the room document
    idle_minutes: int = Field(30, ge=1)
    # New messages since the last scribe wakeup needed to ask it again
    idle_min_messages: int = Field(5, ge=1)

    # Minutes a mergeable task may wait before the lead is reminded (once)
    merge_reminder_minutes: int = 10
    # Minutes a task in progress or in review may stay still before the lead is alerted (once per head SHA)
    idle_task_minutes: int = 10
    # Minutes of calm on the team's branch, with no open task, before the lead is told changes wait for a release
    release_wait_minutes: int = 5
    # Seconds during which further changes of a task do not wake the lead again
    lead_debounce_seconds: int = 30
    # Minutes after a submission without any CI check before the PR goes back to its dev
    ci_missing_minutes: int = 10

    @field_validator("admin_token")
    @classmethod
    def _admin_token_strong(cls, v: str) -> str:
        # Never echo the value: only say what is wrong
        if not v.strip():
            raise ValueError("ADMIN_TOKEN is blank: set it in .env (e.g. openssl rand -hex 32)")
        if len(v) < MIN_SECRET_LENGTH:
            raise ValueError(f"ADMIN_TOKEN is too short (minimum {MIN_SECRET_LENGTH} characters): e.g. openssl rand -hex 32")
        return v

    @field_validator("postgres_password")
    @classmethod
    def _postgres_password_strong(cls, v: str | None) -> str | None:
        # An empty one is reported by the model validator below, with its own message
        if v and len(v) < MIN_SECRET_LENGTH:
            raise ValueError(f"POSTGRES_PASSWORD is too short (minimum {MIN_SECRET_LENGTH} characters): e.g. openssl rand -hex 32")
        return v

    @model_validator(mode="after")
    def _database_url_from_password(self):
        if "database_url" in self.model_fields_set:
            return self  # an explicit URL (external database) wins
        if not self.postgres_password and SECRETS_DIR.is_dir():
            raise ValueError("POSTGRES_PASSWORD is empty or missing: set it in .env")
        if self.postgres_password:
            user, pw = quote(self.postgres_user, safe=""), quote(self.postgres_password, safe="")
            self.database_url = f"postgresql+asyncpg://{user}:{pw}@{self.postgres_host}:5432/{self.postgres_db}"
        return self

    @property
    def claude_tokens(self) -> list[str]:
        return [t.strip() for t in self.claude_code_oauth_tokens.split("|") if t.strip()]


settings = Settings()


def removed_settings_present(env_file: Path = Path(".env")) -> list[str]:
    """Settings that no longer exist but are still set (environment or .env): they are ignored."""
    removed = ["MCP_SESSION_BINDING"]
    text = env_file.read_text(errors="ignore") if env_file.is_file() else ""
    in_file = {l.split("=", 1)[0].strip().removeprefix("export ").strip().upper() for l in text.splitlines() if "=" in l}
    return [name for name in removed if name in os.environ or name in in_file]
