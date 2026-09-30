from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str = "sqlite:///./globalinfra.db"
    redis_url: str = "redis://localhost:6379/0"
    llm_mode: str = "mock"
    openai_compat_base_url: str = "https://api.openai.com/v1"
    openai_compat_api_key: str = ""
    openai_compat_model: str = "gpt-5.6-mini"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
