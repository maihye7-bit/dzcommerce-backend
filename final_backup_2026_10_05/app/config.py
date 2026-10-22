"""
Central application configuration.

Everything environment-specific (DB connection, secrets, token lifetime)
lives here and is read from environment variables / .env file.
No other module should read os.environ directly.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ENV: str = "development"

    # Database
    DATABASE_URL: str = (
        "postgresql+psycopg2://dzcommerce:dzcommerce_dev_password@db:5432/dzcommerce"
    )

    # Auth
    JWT_SECRET_KEY: str = "insecure-dev-secret-change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60


settings = Settings()
