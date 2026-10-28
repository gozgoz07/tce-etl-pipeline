"""Settings and configuration management for TCE."""

from pathlib import Path
from typing import Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    DATABASE_URL: Optional[str] = None
    DB_HOST: Optional[str] = None
    DB_PORT: Optional[int] = 26149
    DB_NAME: Optional[str] = "defaultdb"
    DB_USER: Optional[str] = "tce_backend"
    DB_PWD: Optional[str] = None

    # Test database (optional, used for integration tests)
    TEST_DATABASE_URL: Optional[str] = None

    # HTTP client
    USER_AGENT: str = "TCE-Collector/0.1.0 (+https://github.com/tce; contact@example.com)"
    HTTP_TIMEOUT_SECONDS: float = 20.0
    HTTP_MAX_RETRIES: int = 3

    # Logging
    LOG_LEVEL: str = "INFO"

    # Topics matching threshold
    MATCH_SCORE_THRESHOLD: float = 0.5

    # Base paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    CONFIG_DIR: Path = Path(__file__).resolve().parent.parent.parent / "config"
    SQL_DIR: Path = Path(__file__).resolve().parent.parent.parent / "sql"

    @model_validator(mode="after")
    def assemble_database_url(self) -> "Settings":
        """Assemble DATABASE_URL from individual components if not directly provided."""
        if not self.DATABASE_URL:
            if self.DB_HOST and self.DB_USER and self.DB_PWD:
                port = self.DB_PORT or 26149
                name = self.DB_NAME or "defaultdb"
                self.DATABASE_URL = (
                    f"postgresql://{self.DB_USER}:{self.DB_PWD}@{self.DB_HOST}:{port}/{name}"
                    "?sslmode=require"
                )
        return self

    def get_database_url(self) -> str:
        """Return the effective database URL or raise ValueError."""
        if not self.DATABASE_URL:
            raise ValueError(
                "DATABASE_URL is not set. Please provide DATABASE_URL or DB_* variables."
            )
        return self.DATABASE_URL

    def __repr__(self) -> str:
        """Prevent secrets from leaking in representation."""
        return (
            f"Settings(LOG_LEVEL={self.LOG_LEVEL!r}, "
            f"USER_AGENT={self.USER_AGENT!r}, "
            f"MATCH_SCORE_THRESHOLD={self.MATCH_SCORE_THRESHOLD}, "
            f"DATABASE_CONFIGURED={bool(self.DATABASE_URL)})"
        )


settings = Settings()
