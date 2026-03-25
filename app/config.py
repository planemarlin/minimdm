from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://minimdm:minimdm@localhost:5432/minimdm"
    config_file: str = "config/minimdm.yaml"
    app_name: str = "miniMDM"
    app_version: str = "0.2.0"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000

    # Logging: "json" for structured output (production), "text" for human-readable (development)
    log_format: str = "text"

    # Rate limiting (set to False in test environments)
    rate_limit_enabled: bool = True

    # Maximum file upload size in bytes (default 10 MB)
    max_upload_size: int = 10 * 1024 * 1024

    # Authentication
    secret_key: str = "change-me-in-production-use-a-long-random-string"
    token_expire_hours: int = 8
    # Set these to auto-create the first admin on startup when no users exist
    admin_username: str = ""
    admin_password: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
