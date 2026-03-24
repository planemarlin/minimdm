from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://minimdm:minimdm@localhost:5432/minimdm"
    config_file: str = "config/minimdm.yaml"
    app_name: str = "miniMDM"
    app_version: str = "0.1.0"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000

    # Rate limiting (set to False in test environments)
    rate_limit_enabled: bool = True

    # Authentication
    secret_key: str = "change-me-in-production-use-a-long-random-string"
    token_expire_hours: int = 8
    # Set these to auto-create the first admin on startup when no users exist
    admin_username: str = ""
    admin_password: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
