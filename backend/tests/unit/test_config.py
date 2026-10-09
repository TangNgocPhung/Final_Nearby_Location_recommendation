import pytest
from pydantic import ValidationError

from app.config import Settings


def test_development_settings_parse_cors_origins() -> None:
    settings = Settings(
        app_env="development",
        allowed_origins="http://localhost:3000, http://localhost:8081",
    )

    assert settings.cors_origins == ["http://localhost:3000", "http://localhost:8081"]


def test_production_rejects_development_database_credentials() -> None:
    with pytest.raises(ValidationError, match="development/test credentials"):
        Settings(
            app_env="production",
            database_url="postgresql://nearby:nearby@database:5432/nearby",
            allowed_origins="https://nearby.example.com",
        )


def test_production_rejects_wildcard_cors() -> None:
    with pytest.raises(ValidationError, match="explicit trusted origins"):
        Settings(
            app_env="production",
            database_url="postgresql://app:strong-secret@database:5432/nearby",
            allowed_origins="*",
        )


def test_production_requires_auth_secret() -> None:
    with pytest.raises(ValidationError, match="AUTH_SECRET"):
        Settings(
            app_env="production",
            database_url="postgresql://app:strong-secret@database:5432/nearby",
            allowed_origins="https://nearby.example.com",
            auth_secret="short",
        )


def test_production_rejects_development_admin_password() -> None:
    with pytest.raises(ValidationError, match="ADMIN_PASSWORD"):
        Settings(
            app_env="production",
            database_url="postgresql://app:strong-secret@database:5432/nearby",
            allowed_origins="https://nearby.example.com",
            auth_secret="x" * 40,
            admin_password="nearby_admin_dev",
        )


def test_production_accepts_strong_auth_settings() -> None:
    settings = Settings(
        app_env="production",
        database_url="postgresql://app:strong-secret@database:5432/nearby",
        allowed_origins="https://nearby.example.com",
        auth_secret="x" * 40,
        admin_password="Correct-Horse-Battery-9",
    )
    assert settings.auth_signing_key == b"x" * 40
