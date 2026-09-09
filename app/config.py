import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application configuration."""

    # Database
    DATABASE_URL: str = "postgresql://user:password@localhost/calendariodocenti"

    # API
    API_TITLE: str = "Calendario Docenti API"
    API_VERSION: str = "0.1.0"
    DEBUG: bool = True

    # Solver
    SOLVER_TIMEOUT_SECONDS: int = 60

    # LLM (Claude)
    ANTHROPIC_API_KEY: str = ""

    # Storage (optional S3)
    USE_S3: bool = False
    S3_BUCKET: str = ""

    # Temp files
    TEMP_DIR: str = "/tmp/calendariodocenti"

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
