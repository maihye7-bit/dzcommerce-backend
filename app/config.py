"""
Central application configuration.

Everything environment-specific (DB connection, secrets, token lifetime)
lives here and is read from environment variables / .env file.
No other module should read os.environ directly.
"""

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ENV: str = "development"

    # Database
    DATABASE_URL: str = (
        "postgresql+psycopg2://dzcommerce:dzcommerce_dev_password@db:5432/dzcommerce"
    )

    # Auth
    JWT_SECRET_KEY: str = Field(
        default="",
        validation_alias=AliasChoices("JWT_SECRET_KEY", "SECRET_KEY"),
    )
    JWT_ALGORITHM: str = Field(
        default="HS256",
        validation_alias=AliasChoices("JWT_ALGORITHM", "ALGORITHM"),
    )
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Product image storage. Railway volumes expose their mount path through
    # RAILWAY_VOLUME_MOUNT_PATH; local development defaults to ./var/product-images.
    PRODUCT_IMAGE_STORAGE_DIR: str | None = None
    RAILWAY_VOLUME_MOUNT_PATH: str | None = None
    RAILWAY_ENVIRONMENT: str | None = None
    RAILWAY_PUBLIC_DOMAIN: str | None = None
    META_APP_ID: str = ""
    META_APP_SECRET: str = ""
    SOCIAL_TOKEN_ENCRYPTION_KEY: str = ""

    @model_validator(mode="after")
    def require_secure_production_secret(self):
        if self.ENV.lower() in {"production", "prod"} and (
            self.JWT_SECRET_KEY == "insecure-dev-secret-change-me"
            or len(self.JWT_SECRET_KEY) < 32
            or self.JWT_SECRET_KEY.lower().startswith(
                ("replace-with-", "your-", "change_this")
            )
        ):
            raise ValueError(
                "JWT_SECRET_KEY must be configured with at least 32 characters in production"
            )
        return self


settings = Settings()
