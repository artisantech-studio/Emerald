from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Database — required, no defaults. App refuses to start without these.
    DATABASE_URL: str

    # Cryptographic salt for Merkle ledger token signing.
    # Must be at least 64 hex characters (32 bytes entropy) in production.
    LEDGER_SECRET: str

    # WhatsApp Cloud API webhook registration verify token.
    WHATSAPP_VERIFY_TOKEN: str

    # Meta App Secret for HMAC-SHA256 webhook signature validation.
    WHATSAPP_APP_SECRET: str

    # WhatsApp API Bearer Token (for outbound API calls).
    WHATSAPP_API_TOKEN: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
