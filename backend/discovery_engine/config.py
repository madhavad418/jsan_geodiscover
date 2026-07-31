from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

# Sweep field mask stays inside the Essentials + Pro SKU tiers. Adding any of
# nationalPhoneNumber / internationalPhoneNumber / websiteUri / rating / userRatingCount
# promotes EVERY tile call to the Enterprise SKU, so contact fields are fetched only
# during enrichment of surviving records. See MVP_GRAB_VS_GOOGLE.md section 7.
# addressComponents is Essentials tier, the same as formattedAddress, so adding it
# gives city and province at no SKU cost. Without it every Google record lands with
# an unknown city and the city filter is useless on half the dataset.
GOOGLE_SWEEP_FIELD_MASK = (
    "places.id,places.location,places.formattedAddress,places.addressComponents,"
    "places.types,places.displayName,places.primaryType,places.businessStatus"
)
GOOGLE_DETAIL_FIELD_MASK = (
    "id,location,formattedAddress,addressComponents,types,displayName,primaryType,"
    "businessStatus,googleMapsUri,nationalPhoneNumber,internationalPhoneNumber,websiteUri"
)


class Settings(BaseSettings):
    engine_database_url: str = "sqlite:///./discovery_engine.db"
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 480
    demo_admin_email: str = "admin@example.com"
    demo_admin_password: str
    cors_origins: str = "http://localhost:5173"

    # --- Google Places API (New) ---
    google_maps_api_key: str = ""
    google_sweep_field_mask: str = GOOGLE_SWEEP_FIELD_MASK
    google_detail_field_mask: str = GOOGLE_DETAIL_FIELD_MASK
    google_language_code: str = "id"
    google_region_code: str = "ID"

    # --- GrabMaps via Amazon Location Service (geo-places) ---
    # GrabMaps data is served from ap-southeast-1 (Singapore) and ap-southeast-5 (Malaysia).
    # Two auth modes are supported; the API key takes precedence when both are present.
    #  1. Amazon Location API key — a PASETO token beginning "v1.public.". Sent as the
    #     Key request parameter with the request otherwise unsigned.
    #  2. SigV4 IAM credentials — an access key ID + secret pair.
    aws_region: str = "ap-southeast-1"
    aws_location_api_key: str = ""
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_session_token: str = ""
    # Amazon Location's Label/Core/Advanced buckets all state that results "can't be
    # stored permanently". This application persists every result into provider_places,
    # so Storage is the correct and required setting. It bills at a higher rate.
    grab_intended_use: str = "Storage"
    grab_language: str = "id"
    grab_country: str = "IDN"

    # --- Cost guardrails: a run aborts rather than overrunning these ---
    google_max_calls_per_run: int = 2000
    grab_max_calls_per_run: int = 2000
    # Optional USD ceiling per run. 0 disables it and leaves the call cap as the only
    # bound. A run stops as soon as the next call would cross the ceiling.
    google_max_spend_per_run_usd: float = 0.0
    grab_max_spend_per_run_usd: float = 0.0

    # --- API rates, USD per 1,000 requests ---
    # A negative value means "not configured": cost is then reported as unknown rather
    # than as zero, so a missing rate cannot masquerade as a free call.
    # Verify these against your own billing console before trusting any estimate.
    # Google Places (New) bills at the highest SKU tier the field mask touches; the
    # sweep mask is Pro, enrichment is Enterprise. The defaults below use the highest
    # rate observed, so estimates are an upper bound rather than a surprise.
    rate_google_nearby_per_1k: float = 32.0
    rate_google_text_per_1k: float = 32.0
    rate_google_details_per_1k: float = 20.0
    # Amazon Location Places buckets are Label / Core / Advanced / Stored. Persisting
    # results, which this application does, requires the Stored bucket. Left
    # unconfigured by default because the rate depends on your agreement.
    rate_grab_search_text_per_1k: float = -1.0
    provider_request_timeout: float = 20.0
    provider_max_retries: int = 3

    # --- Matching thresholds (project rows may override) ---
    match_auto_threshold: int = 85
    match_possible_threshold: int = 60
    match_max_distance_m: float = 300.0

    # Retention window for cached third-party place payloads, in days.
    provider_payload_ttl_days: int = 30

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_maps_api_key)

    @property
    def grab_uses_api_key(self) -> bool:
        return bool(self.aws_location_api_key)

    @property
    def grab_enabled(self) -> bool:
        return self.grab_uses_api_key or bool(self.aws_access_key_id and self.aws_secret_access_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
