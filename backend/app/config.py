from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://palabre:palabre@localhost:5432/palabre"
    # Name of the person using Palabre (the CEO), set by the user.
    boss_name: str = ""
    # Used by the backend only (push, pull requests, merges). Never given to agents.
    github_token: str | None = None
    projects_dir: Path = Path("/data/projects")
    # Temporary files of runs (MCP configs), kept outside the repositories
    runtime_dir: Path = Path("/data/runtime")

    # Agents (`claude -p`, billed on the subscription through CLAUDE_CODE_OAUTH_TOKEN)
    claude_bin: str = "claude"
    claude_max_turns: int = 30
    agent_timeout_s: int = 1800
    # Seen from the `claude` processes, which run in the backend container
    mcp_url: str = "http://127.0.0.1:8000/mcp/"

    # Orchestrator
    orchestrator_enabled: bool = True
    poll_interval_s: float = 2.0
    max_concurrent_agents: int = 3
    # Rounds of "changes requested" on a task before the lead has to step in
    max_review_rounds: int = 3
    # Agent runs per conversation per hour before the boss is asked to step in
    max_runs_per_conversation_hour: int = 40
    # Local time of the daily stand-up ("HH:MM"), empty to disable
    daily_time: str = "09:30"
    # Quiet minutes before the scribe is asked to update the room document
    idle_minutes: int = 10


settings = Settings()
