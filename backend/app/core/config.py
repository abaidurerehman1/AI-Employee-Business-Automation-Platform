from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AI Employee Platform API"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "postgresql+asyncpg://ai_employee:change_me@localhost:55432/ai_employee"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: list[str] = ["http://localhost:5173"]
    frontend_url: str = "http://localhost:5173"
    session_cookie_name: str = "ai_employee_session"
    session_days: int = 7
    secure_cookies: bool = False
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    emails_enabled: bool = False
    openai_api_key: str = ""
    openai_default_model: str = "gpt-4.1-mini"
    embedding_model: str = "text-embedding-3-small"
    max_document_bytes: int = 10 * 1024 * 1024
    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "ai-employee-workflows"
    agent_max_output_tokens: int = 1024
    agent_max_tool_calls: int = 3
    agent_max_input_characters: int = 100000

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
