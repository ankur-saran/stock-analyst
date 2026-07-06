from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── PostgreSQL ────────────────────────────────────────────────────────────
    postgres_user: str = "stockanalyst"
    postgres_password: SecretStr = SecretStr("changeme")
    postgres_db: str = "stockanalyst"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── Qdrant ────────────────────────────────────────────────────────────────
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333

    # ── MinIO ─────────────────────────────────────────────────────────────────
    minio_root_user: str = "minioadmin"
    minio_root_password: SecretStr = SecretStr("changeme")
    minio_endpoint: str = "http://localhost:9000"

    # ── Keycloak ──────────────────────────────────────────────────────────────
    keycloak_url: str = "http://localhost:8080"
    keycloak_realm: str = "stockanalyst"
    keycloak_client_id: str = "stockanalyst-api"
    keycloak_client_secret: SecretStr = SecretStr("changeme")
    keycloak_admin: str = "admin"
    keycloak_admin_password: SecretStr = SecretStr("changeme")

    # ── LLM providers ─────────────────────────────────────────────────────────
    anthropic_api_key: SecretStr = SecretStr("sk-ant-...")
    openai_api_key: SecretStr = SecretStr("sk-...")

    # ── LiteLLM proxy ─────────────────────────────────────────────────────────
    litellm_url: str = "http://localhost:4000"

    # ── Ollama ────────────────────────────────────────────────────────────────
    ollama_base_url: str = "http://localhost:11434"

    # ── LangSmith ────────────────────────────────────────────────────────────
    langsmith_api_key: SecretStr = SecretStr("ls__...")
    langsmith_project: str = "stock-analyst-dev"

    # ── Tavily ────────────────────────────────────────────────────────────────
    tavily_api_key: SecretStr = SecretStr("tvly-...")

    # ── FastAPI application ───────────────────────────────────────────────────
    secret_key: SecretStr = SecretStr("changeme-generate-a-real-secret")
    environment: str = "development"

    # ── Helpers ───────────────────────────────────────────────────────────────

    def get_db_url(self) -> str:
        """Async SQLAlchemy connection string for asyncpg."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}"
            f":{self.postgres_password.get_secret_value()}"
            f"@{self.postgres_host}:{self.postgres_port}"
            f"/{self.postgres_db}"
        )

    def get_sync_db_url(self) -> str:
        """Sync psycopg2 connection string — useful for Alembic offline mode."""
        return (
            f"postgresql+psycopg2://{self.postgres_user}"
            f":{self.postgres_password.get_secret_value()}"
            f"@{self.postgres_host}:{self.postgres_port}"
            f"/{self.postgres_db}"
        )
