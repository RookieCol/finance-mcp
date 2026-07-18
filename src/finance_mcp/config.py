"""Environment-driven settings, shared by the MCP server, web UI, and scheduler.

Fails fast at startup (via pydantic-settings validation) rather than
surfacing a missing DATABASE_URL as a confusing error deep inside a
request handler.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
    log_level: str = "INFO"

    # 0.0.0.0 is required so the UI is reachable from outside its Docker
    # container (Stage 10); it is not exposed publicly (README: no-auth v1,
    # local/private network only). nosec: intentional, not an oversight.
    ui_host: str = "0.0.0.0"  # nosec B104
    ui_port: int = 8000

    otel_exporter_otlp_endpoint: str | None = None


def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values sourced from env/`.env`
