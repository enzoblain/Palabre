from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://palabre:palabre@localhost:5432/palabre"
    # Protects the REST API (Authorization: Bearer <ADMIN_TOKEN>)
    admin_token: str
    # Origins allowed to call the API from a browser (the desktop app's dev server)
    cors_origins: list[str] = ["*"]
    # Used by the backend only (push, pull requests, merges). Never given to agents.
    github_token: str | None = None
    projects_dir: Path = Path("/data/projects")
    # Temporary files of runs (MCP configs), kept outside the repositories
    runtime_dir: Path = Path("/data/runtime")
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

    # Orchestrator
    orchestrator_enabled: bool = True
    poll_interval_s: float = 2.0
    # Per Claude account
    max_concurrent_agents: int = 3
    # Rounds of "changes requested" on a task before the lead has to step in
    max_review_rounds: int = 3
    # Agent runs per conversation per hour before the boss is asked to step in
    max_runs_per_conversation_hour: int = 40
    # Local time of the daily stand-up ("HH:MM"), empty to disable
    daily_time: str = "09:30"
    # Quiet minutes before the scribe is asked to update the room document
    idle_minutes: int = 10

    @property
    def claude_tokens(self) -> list[str]:
        return [t.strip() for t in self.claude_code_oauth_tokens.split("|") if t.strip()]


settings = Settings()
