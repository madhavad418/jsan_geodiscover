import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# The discovery engine reuses seven table names from the customer schema
# (users, projects, poi_candidates, ...). On one Postgres database they would
# overwrite each other, so the engine is given its own schema.
ENGINE_SCHEMA = "engine"


def normalise_database_url(url: str) -> str:
    """Make a hosted Postgres URL usable by SQLAlchemy 2 with psycopg 3.

    Railway and Heroku hand out "postgres://" or "postgresql://" URLs, but
    SQLAlchemy needs an explicit driver or it reaches for psycopg2, which is
    not installed here.
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


class Settings(BaseSettings):
    database_url: str = "sqlite:///./customer_demo.db"
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 480
    demo_admin_email: str = "admin@example.com"
    demo_admin_password: str
    # Two further sign-ins for the demo team. Each falls back to the admin
    # password only when its own is left unset, so a deployment can give them
    # separate credentials.
    demo_manager_email: str = "manager@jsanconsulting.com"
    demo_manager_password: str | None = None
    demo_analyst_email: str = "analyst@jsanconsulting.com"
    demo_analyst_password: str | None = None
    cors_origins: str = "http://localhost:5173,http://localhost:8000"
    evidence_storage_path: str = "./evidence_storage_customer"
    redis_url: str = "redis://localhost:6379/0"

    google_places_api_key: str | None = None
    google_maps_api_key: str | None = None
    google_language_code: str = "id"
    google_region_code: str = "ID"
    google_max_calls_per_run: int = 2000
    aws_region: str = "ap-southeast-1"
    aws_grab_place_index: str | None = None
    aws_location_api_key: str | None = None
    apify_token: str | None = None
    apify_instagram_actor_id: str = "apify/instagram-scraper"
    apify_tiktok_actor_id: str = "clockworks/tiktok-scraper"
    apify_facebook_actor_id: str | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def sqlalchemy_url(self) -> str:
        return normalise_database_url(self.database_url)

    @property
    def is_postgres(self) -> bool:
        return self.sqlalchemy_url.startswith("postgresql")

    @property
    def manager_password(self) -> str:
        return self.demo_manager_password or self.demo_admin_password

    @property
    def analyst_password(self) -> str:
        return self.demo_analyst_password or self.demo_admin_password

    @property
    def cors_origin_list(self) -> list[str]:
        origins = [item.strip() for item in self.cors_origins.split(",") if item.strip()]
        # Railway publishes the deployment's own host; allow it without having
        # to hard-code the generated domain at build time.
        for variable in ("RAILWAY_PUBLIC_DOMAIN", "RAILWAY_STATIC_URL"):
            host = os.getenv(variable, "").strip()
            if not host:
                continue
            origin = host if host.startswith("http") else f"https://{host}"
            if origin not in origins:
                origins.append(origin)
        return origins

    @property
    def evidence_path(self) -> Path:
        path = Path(self.evidence_storage_path)
        path.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache
def get_settings() -> Settings:
    return Settings()
