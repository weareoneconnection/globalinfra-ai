from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str = "sqlite:///./globalinfra.db"
    redis_url: str = "redis://localhost:6379/0"
    llm_mode: str = "mock"
    openai_compat_base_url: str = "https://api.openai.com/v1"
    openai_compat_api_key: str = ""
    openai_compat_model: str = "gpt-5.6-mini"
    local_llm_base_url: str = "http://host.docker.internal:11434/v1"
    local_llm_api_key: str = ""
    local_llm_model: str = "qwen3:8b"
    llm_preferred_provider: str = "local"
    llm_cloud_fallback_enabled: bool = True
    # Pilot-stage auth gate (see app.security): a single shared-secret API
    # key, *not* a replacement for enterprise SSO/OIDC. Off by default so
    # the V1.0 competition/demo flow is unaffected; a pilot deployment can
    # turn it on without any code change.
    require_api_key: bool = False
    api_key: str = ""
    cors_origins: str = "http://localhost:3000"
    max_upload_bytes: int = 10 * 1024 * 1024
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def allowed_origins(self) -> list[str]:
        """Return an explicit CORS allowlist; wildcard origins are rejected."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip() and origin.strip() != "*"]

settings = Settings()
