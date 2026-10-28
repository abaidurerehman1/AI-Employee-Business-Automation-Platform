from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    app_name: str = "AI Employee Platform API"
    app_env: Literal["development", "test", "staging", "production"] = "development"
    api_v1_prefix: str = "/api/v1"
    database_url: str = Field(
        default="postgresql+asyncpg://ai_employee:change_me@localhost:55432/ai_employee", repr=False
    )
    redis_url: str = Field(default="redis://localhost:6379/0", repr=False)
    cors_origins: list[str] = ["http://localhost:5173"]
    frontend_url: str = "http://localhost:5173"
    session_cookie_name: str = "ai_employee_session"
    session_days: int = 7
    secure_cookies: bool = False
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = Field(default="", repr=False)
    smtp_from_email: str = ""
    emails_enabled: bool = False
    openai_api_key: str = Field(default="", repr=False)
    openai_default_model: str = "gpt-4.1-mini"
    embedding_model: str = "text-embedding-3-small"
    max_document_bytes: int = 10 * 1024 * 1024
    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "ai-employee-workflows"
    temporal_tls: bool = False
    temporal_api_key: str = Field(default="", repr=False)
    agent_max_output_tokens: int = 1024
    agent_max_tool_calls: int = 3
    agent_max_input_characters: int = 100000
    resend_api_key: str = Field(default="", repr=False)
    resend_from_email: str = ""
    resend_reply_to: str = ""
    resend_webhook_secret: str = Field(default="", repr=False)
    twilio_account_sid: str = ""
    twilio_auth_token: str = Field(default="", repr=False)
    twilio_from_number: str = ""
    messaging_public_base_url: str = ""
    messaging_unsubscribe_secret: str = Field(default="", repr=False)
    messaging_hourly_limit: int = 100
    google_client_id: str = ""
    google_client_secret: str = Field(default="", repr=False)
    google_redirect_uri: str = "http://localhost:8000/api/v1/messaging/gmail/callback"
    oauth_encryption_key: str = Field(default="", repr=False)
    campaign_max_recipients: int = 1000
    campaign_email_interval_seconds: float = Field(default=2.0, ge=0)
    campaign_sms_interval_seconds: float = Field(default=1.0, ge=0)
    campaign_allowed_sms_prefixes: list[str] = []
    campaign_allow_local_gmail_self_test: bool = False
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "testserver", "test", "backend"]
    health_timeout_seconds: float = Field(default=2.0, gt=0, le=10)
    database_pool_size: int = Field(default=5, ge=1, le=100)
    database_max_overflow: int = Field(default=10, ge=0, le=100)
    database_pool_timeout: float = Field(default=10, gt=0, le=60)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    run_migrations_on_start: bool = True
    auth_requests_per_minute: int = Field(default=10, ge=1, le=1000)

    @model_validator(mode="after")
    def validate_configuration(self):
        if self.database_url.split(":", 1)[0] not in {"postgresql+asyncpg", "sqlite+aiosqlite"}:
            raise ValueError("DATABASE_URL must use an asynchronous supported database driver")
        if urlparse(self.redis_url).scheme not in {"redis", "rediss"}:
            raise ValueError("REDIS_URL must use redis or rediss")
        frontend = urlparse(self.frontend_url)
        if frontend.scheme not in {"http", "https"} or not frontend.hostname or frontend.username:
            raise ValueError("FRONTEND_URL must be a valid HTTP application URL")
        for origin in self.cors_origins:
            url = urlparse(origin)
            if (
                url.scheme not in {"http", "https"}
                or not url.netloc
                or url.path not in {"", "/"}
                or url.query
                or url.fragment
                or url.username
            ):
                raise ValueError("CORS_ORIGINS must contain explicit HTTP origins")
        if not self.allowed_hosts or any(
            "/" in host or "://" in host for host in self.allowed_hosts
        ):
            raise ValueError("ALLOWED_HOSTS must contain host names")
        if (
            self.session_days < 1
            or self.messaging_hourly_limit < 1
            or self.campaign_max_recipients < 1
        ):
            raise ValueError("Session duration and message/recipient limits must be positive")
        if self.oauth_encryption_key:
            from cryptography.fernet import Fernet

            try:
                Fernet(self.oauth_encryption_key.encode())
            except (ValueError, TypeError) as exc:
                raise ValueError("OAUTH_ENCRYPTION_KEY must be a valid Fernet key") from exc
        if self.app_env in {"production", "staging"}:
            db = make_url(self.database_url)
            if (
                db.drivername != "postgresql+asyncpg"
                or not db.password
                or db.password in {"change_me", "local_development_only", "postgres"}
            ):
                raise ValueError("Production requires PostgreSQL with a non-default password")
            if not self.secure_cookies or urlparse(self.frontend_url).scheme != "https":
                raise ValueError(
                    "Production requires SECURE_COOKIES=true and an HTTPS FRONTEND_URL"
                )
            if not self.cors_origins or any(
                urlparse(origin).scheme != "https" for origin in self.cors_origins
            ):
                raise ValueError("Production requires explicit HTTPS CORS origins")
            if "allowed_hosts" not in self.model_fields_set or "*" in self.allowed_hosts:
                raise ValueError("Production requires explicit ALLOWED_HOSTS")
            if self.campaign_allow_local_gmail_self_test:
                raise ValueError("Local Gmail self-testing must be disabled in production")
            if (
                self.messaging_public_base_url
                and urlparse(self.messaging_public_base_url).scheme != "https"
            ):
                raise ValueError("Production messaging requires an HTTPS public URL")
            if self.messaging_unsubscribe_secret and len(self.messaging_unsubscribe_secret) < 32:
                raise ValueError(
                    "Production unsubscribe signing secret must have at least 32 characters"
                )
            if self.google_client_id and urlparse(self.google_redirect_uri).scheme != "https":
                raise ValueError("Production Gmail requires an HTTPS Google redirect URI")
        return self

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
