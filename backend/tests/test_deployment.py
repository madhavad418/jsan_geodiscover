"""Settings and wiring the hosted deployment depends on."""

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from app.config import ENGINE_SCHEMA, Settings, normalise_database_url

REPO = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "given, expected",
    [
        # Railway and Heroku hand out these two shapes.
        ("postgres://u:p@host:5432/db", "postgresql+psycopg://u:p@host:5432/db"),
        ("postgresql://u:p@host:5432/db", "postgresql+psycopg://u:p@host:5432/db"),
        # Already explicit, or not Postgres at all - left alone.
        ("postgresql+psycopg://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
        ("sqlite:///./customer_demo.db", "sqlite:///./customer_demo.db"),
    ],
)
def test_hosted_database_urls_get_a_driver(given, expected):
    assert normalise_database_url(given) == expected


def test_normalised_url_is_loadable_by_sqlalchemy():
    """Catches a missing driver at test time rather than on first boot."""
    url = normalise_database_url("postgres://u:p@host:5432/db")
    engine = create_engine(url)  # resolves the dialect without connecting
    assert engine.dialect.name == "postgresql"
    assert engine.dialect.driver == "psycopg"


def _settings(**overrides) -> Settings:
    """Settings built in isolation - a developer's local .env must not leak in."""
    base = {"jwt_secret": "x" * 32, "demo_admin_password": "admin-pass"}
    return Settings(_env_file=None, **{**base, **overrides})


def test_extra_users_fall_back_to_the_admin_password():
    settings = _settings()
    assert settings.manager_password == "admin-pass"
    assert settings.analyst_password == "admin-pass"


def test_extra_users_can_have_their_own_passwords():
    settings = _settings(demo_manager_password="mgr-pass", demo_analyst_password="ana-pass")
    assert settings.manager_password == "mgr-pass"
    assert settings.analyst_password == "ana-pass"
    assert settings.demo_admin_password == "admin-pass"


def test_railway_domain_is_allowed_without_being_hard_coded(monkeypatch):
    monkeypatch.setenv("RAILWAY_PUBLIC_DOMAIN", "geodiscover-production.up.railway.app")
    origins = _settings(cors_origins="http://localhost:8000").cors_origin_list
    assert "https://geodiscover-production.up.railway.app" in origins
    assert "http://localhost:8000" in origins


def test_railway_domain_is_not_duplicated(monkeypatch):
    monkeypatch.setenv("RAILWAY_PUBLIC_DOMAIN", "https://demo.up.railway.app")
    origins = _settings(cors_origins="https://demo.up.railway.app").cors_origin_list
    assert origins.count("https://demo.up.railway.app") == 1


def test_postgres_is_detected_from_either_url_shape():
    assert _settings(database_url="postgres://u:p@h/db").is_postgres
    assert not _settings(database_url="sqlite:///./x.db").is_postgres


def test_engine_is_confined_to_its_own_schema():
    """The engine reuses table names, so it must not share the public schema."""
    from app import models as customer_models
    from discovery_engine import models as engine_models

    shared = {t.name for t in customer_models.Base.metadata.tables.values()} & {
        t.name for t in engine_models.Base.metadata.tables.values()
    }
    assert shared, "expected overlapping table names; the isolation below guards them"
    assert ENGINE_SCHEMA and ENGINE_SCHEMA != "public"


def test_deployment_files_are_present_and_consistent():
    dockerfile = (REPO / "Dockerfile").read_text(encoding="utf-8")
    railway = (REPO / "railway.json").read_text(encoding="utf-8")
    assert "release.py" in dockerfile and "release.py" in railway
    assert "/integrated-health" in railway
    # Everything the image copies has to exist in the repository.
    for source in ("backend/requirements.txt", "backend/alembic.ini", "backend/app",
                   "backend/discovery_engine", "backend/misseddata", "backend/other_cities",
                   "backend/release.py", "sample_output"):
        assert (REPO / source).exists(), f"Dockerfile copies missing path: {source}"
        assert source in dockerfile


def test_secrets_are_not_baked_into_the_image():
    ignored = (REPO / ".dockerignore").read_text(encoding="utf-8")
    assert "backend/.env" in ignored
    assert "backend/*.db" in ignored
