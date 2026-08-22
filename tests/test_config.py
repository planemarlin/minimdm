from app.config import Settings


class TestSettingsExtraEnv:
    def test_ignores_docker_compose_only_env_vars(self, tmp_path, monkeypatch):
        """docker-compose.yml bind-mounts the repo into the app container, so
        Settings(env_file=".env") parses the same .env file docker-compose.yml uses
        for host-port variable substitution. APP_PORT and POSTGRES_PORT aren't app
        config and must not crash startup (regression test for issue #49 — v0.7.2
        shipped with extra="forbid", which crashed on these keys).

        Unknown keys must come from an actual .env file, not os.environ: pydantic-settings'
        EnvSettingsSource looks up env vars per declared field, so a stray os.environ key is
        invisible to it either way; DotEnvSettingsSource parses the whole file into a dict,
        which is where unknown keys actually reach model validation."""
        env_file = tmp_path / ".env"
        env_file.write_text("APP_PORT=18000\nPOSTGRES_PORT=15432\n")
        monkeypatch.chdir(tmp_path)
        Settings()
