from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    db_host: str
    db_port: int = 5432
    db_name: str
    db_user: str
    db_password: str
    db_pool_size: int = 20
    db_max_overflow: int = 30

    # Ollama
    ollama_base_url: str
    ollama_api_key: str
    ollama_model: str = "gpt-oss:20b"
    ollama_request_timeout: float = 120.0

    # Embeddings
    embedding_model_name: str = "BAAI/bge-small-en-v1.5"

    # JWT (mesmo secret do nexusgov-api, base64-encoded)
    jwt_secret: str
    jwt_algorithms: str = "HS384"

    # Sessions
    session_backend: str = "memory"
    session_max_size: int = 1000
    session_ttl_minutes: int = 60
    redis_url: str = "redis://localhost:6379/0"

    # CORS — CSV; vazio bloqueia tudo
    cors_origins: str = ""

    # Rate limit
    rate_limit_per_minute: int = 20

    # Chat — tool calling
    chat_tool_calling_enabled: bool = True

    # Logging
    sql_echo: bool = False

    # App
    app_port: int = 8000
    app_host: str = "0.0.0.0"
    app_reload: bool = False

    @property
    def database_url(self) -> str:
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def jwt_algorithms_list(self) -> list[str]:
        return [a.strip() for a in self.jwt_algorithms.split(",") if a.strip()]

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
