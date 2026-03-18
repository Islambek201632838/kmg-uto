from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Локальная БД (Docker с mock_uto_backup.sql)
    DB_HOST: str = "localhost"
    DB_PORT: int = 5434
    DB_NAME: str = "mock_uto"
    DB_USER: str = "kmg_user"
    DB_PASSWORD: str = "kmg_password"

    # Удалённая БД (хакатон)
    REMOTE_DB_HOST: str = ""
    REMOTE_DB_PORT: int = 5432
    REMOTE_DB_NAME: str = "mock_uto"
    REMOTE_DB_USER: str = "readonly_user"
    REMOTE_DB_PASSWORD: str = ""

    # Какую БД использовать: "local" или "remote"
    USE_DB: str = "local"

    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8003

    # LLM (Gemini)
    GEMINI_API_KEY: str = ""

    @property
    def database_url(self) -> str:
        if self.USE_DB == "remote":
            return (
                f"postgresql+asyncpg://{self.REMOTE_DB_USER}:{self.REMOTE_DB_PASSWORD}"
                f"@{self.REMOTE_DB_HOST}:{self.REMOTE_DB_PORT}/{self.REMOTE_DB_NAME}"
            )
        return (
            f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    @property
    def sync_database_url(self) -> str:
        """Синхронный URL для начальной загрузки данных при старте."""
        if self.USE_DB == "remote":
            return (
                f"postgresql+psycopg2://{self.REMOTE_DB_USER}:{self.REMOTE_DB_PASSWORD}"
                f"@{self.REMOTE_DB_HOST}:{self.REMOTE_DB_PORT}/{self.REMOTE_DB_NAME}"
            )
        return (
            f"postgresql+psycopg2://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "env_ignore_empty": True,
        "extra": "ignore",
    }


settings = Settings()
