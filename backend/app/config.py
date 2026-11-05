from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_db_url(url: str) -> str:
    # Render hands out postgres:// ; SQLAlchemy + psycopg3 needs postgresql+psycopg://
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://paycord_user:password@localhost:5432/paycord"
    paypal_env: str = "sandbox"
    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    paypal_webhook_id: str = ""
    openai_api_key: str = ""
    openai_model: str = "gpt-5.4-mini"
    frontend_public_url: str = "http://localhost:5173"
    cors_origins: str = "http://localhost:5173"

    @field_validator("database_url")
    @classmethod
    def _normalize(cls, v: str) -> str:
        return normalize_db_url(v)

    @property
    def paypal_base_url(self) -> str:
        if self.paypal_env == "live":
            return "https://api-m.paypal.com"
        return "https://api-m.sandbox.paypal.com"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
