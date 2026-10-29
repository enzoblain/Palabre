"""Settings read from environment variables and, for secrets, from files (Docker secrets)."""

import os
from typing import Literal
from pathlib import Path
from urllib.parse import quote

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SECRETS_DIR = Path(os.environ.get("PALABRE_SECRETS_DIR", "/run/palabre-secrets"))


class Settings(BaseSettings):
    # Secrets (admin_token, github_token, claude_code_oauth_tokens, postgres_password) are
    # files here, not environment variables: the entrypoint copies them for the backend only
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", secrets_dir=SECRETS_DIR if SECRETS_DIR.is_dir() else None
    )

    database_url: str = "postgresql+asyncpg://palabre:palabre@localhost:5432/palabre"
    # With a password (the compose setup), the URL is built from these instead
    postgres_password: str | None = None
    postgres_user: str = "palabre"
    postgres_db: str = "palabre"
    postgres_host: str = "db"
    # Protects the REST API (Authorization: Bearer <ADMIN_TOKEN>)
    admin_token: str = Field(min_length=1)
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
    # Holds the MCP configs of runs when the agent user must read them (runtime_dir is the backend's only)
    agent_run_dir: Path = Path("/data/run")
    # Toolchains installed by the agents (install_toolchain), shared by the whole team
    toolchains_dir: Path = Path("/data/toolchains")

    # Agents (`claude -p`, billed on Claude subscriptions). One token per account,
    # separated by "|": the employees are spread over the accounts.
    claude_code_oauth_tokens: str = ""
    claude_bin: str = "claude"
    # Turns per run: a conversation turn is short, work on a task can take long
    claude_max_turns: int = 30
    claude_task_max_turns: int = 100
    agent_timeout_s: int = 1800
    # Seen from the `claude` processes, which run in the backend container
    mcp_url: str = "http://127.0.0.1:8000/mcp/"
    # "warn": a second MCP session on a run's token is logged and the lead alerted once, nothing is revoked.
    # "enforce": the token is revoked (fail closed). Not checked yet on a real `claude -p` run.
    mcp_session_binding: Literal["warn", "enforce"] = "warn"

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
    # Agent runs per conversation per hour before the boss is asked to step in
    max_runs_per_conversation_hour: int = 40
    # Local time of the daily stand-up ("HH:MM"), empty to disable
    daily_time: str = "09:30"
    # Quiet minutes before the scribe is asked to update the room document
    idle_minutes: int = 10

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
    def _admin_token_not_blank(cls, v: str) -> str:
        # Never echo the value: only say what is wrong
        if not v.strip():
            raise ValueError("ADMIN_TOKEN is blank: set it in .env (e.g. openssl rand -hex 32)")
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
