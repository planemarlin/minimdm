from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://minimdm:minimdm@localhost:5432/minimdm"
    config_file: str = "config/minimdm.yaml"
    app_name: str = "miniMDM"
    app_version: str = "0.1.0"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
