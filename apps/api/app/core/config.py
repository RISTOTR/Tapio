from functools import lru_cache

from pydantic import PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: PostgresDsn = PostgresDsn(
        "postgresql+psycopg://tapio:tapio_local@localhost:5433/tapio"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
