import pytest
from pydantic import ValidationError

from app.core.config import Settings


def production(**overrides):
    values = dict(
        app_env="production",
        database_url="postgresql+asyncpg://app:synthetic-strong-password@db/app",
        frontend_url="https://app.example.com",
        cors_origins=["https://app.example.com"],
        secure_cookies=True,
        allowed_hosts=["api.example.com", "localhost"],
    )
    return Settings(_env_file=None, **{**values, **overrides})


def test_explicit_production_configuration_is_supported():
    assert production().app_env == "production"


@pytest.mark.parametrize(
    "overrides",
    [
        {"secure_cookies": False},
        {"frontend_url": "http://localhost:5173"},
        {"cors_origins": ["*"]},
        {"allowed_hosts": ["*"]},
        {"database_url": "postgresql+asyncpg://app:change_me@db/app"},
        {"campaign_allow_local_gmail_self_test": True},
        {"messaging_public_base_url": "http://localhost:8000"},
        {"messaging_unsubscribe_secret": "short"},
    ],
)
def test_production_rejects_unsafe_defaults(overrides):
    with pytest.raises(ValidationError):
        production(**overrides)


def test_invalid_configuration_errors_do_not_expose_inputs():
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, redis_url="bad://private-credential")
    assert "private-credential" not in str(error.value)
    settings = Settings(_env_file=None, openai_api_key="private-api-key")
    assert "private-api-key" not in repr(settings)
