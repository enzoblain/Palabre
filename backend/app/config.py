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


settings = Settings()
