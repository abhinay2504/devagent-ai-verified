from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    devagent_workspace_root: str = "../workspace"
    devagent_database_path: str = "./devagent.sqlite3"
    devagent_max_file_bytes: int = 200_000
    devagent_max_patch_bytes: int = 150_000
    devagent_max_test_seconds: int = 90
    devagent_max_repair_attempts: int = 3
    devagent_enable_local_test_runner: bool = False
    devagent_docker_image: str = "devagent-ai-test-runner:latest"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5-coder:3b"
    ollama_timeout_seconds: int = 180

    @property
    def workspace_root(self) -> Path:
        path = Path(self.devagent_workspace_root).expanduser()
        if not path.is_absolute():
            path = (Path(__file__).resolve().parents[1] / path).resolve()
        return path.resolve()

    @property
    def database_path(self) -> Path:
        path = Path(self.devagent_database_path).expanduser()
        if not path.is_absolute():
            path = (Path(__file__).resolve().parents[1] / path).resolve()
        return path.resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
