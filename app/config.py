from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://minimdm:minimdm@localhost:5432/minimdm"
    config_file: str = "config/minimdm.yaml"
    app_name: str = "miniMDM"
    app_version: str = "0.7.3"
    debug: bool = False

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
    # Set to True when serving over HTTPS to add the Secure flag to the session cookie
    secure_cookie: bool = False

    # Set to True when miniMDM runs behind a trusted reverse proxy that sets
    # X-Forwarded-For. When False (default), the direct TCP peer address is
    # used for audit log IP recording to prevent header spoofing.
    trusted_proxy: bool = False

    # "ignore" (not the pydantic-settings default "forbid") because .env is shared
    # with docker-compose.yml, which reads host-only values like APP_PORT and
    # POSTGRES_PORT that Settings has no field for and never needs to parse.
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
