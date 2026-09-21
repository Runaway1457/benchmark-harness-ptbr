"""Configuração por variável de ambiente, com prefixo PTBR_BENCHMARK_."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PTBR_BENCHMARK_", env_file=".env", extra="ignore")

    cache_path: Path = Path(".ptbr-benchmark-cache.sqlite")
    max_concurrency: int = Field(default=4, ge=1, le=32)
    log_level: str = "INFO"
    tasks_dir: Path = Path("tasks")
    results_dir: Path = Path("results")
    docs_dir: Path = Path("docs")
    site_dir: Path = Path("site")
    request_timeout_seconds: float = Field(default=60.0, gt=0)
