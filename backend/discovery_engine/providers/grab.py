"""GrabMaps adapter via Amazon Location Service (geo-places), ap-southeast-1.

Two constraints from the AWS API reference drive this design:

1. GrabMaps supports SearchText, Suggest, ReverseGeocode and GetPlace only. There is
   NO SearchNearby, so category-radius discovery is impossible. Discovery is instead a
   keyword matrix: each tile is searched once per Indonesian salon search term, with a
   circle filter restricting results to the tile.

2. In ap-southeast-1 / ap-southeast-5, GrabMaps supports only the `TimeZone` value for
   AdditionalFeatures. `Contact` is unavailable, so GrabMaps returns NO phone numbers
   and NO websites. The matching engine therefore cannot use contact signals across
   providers, and Grab-only records arrive with no contact channel at all.

Coordinates are GeoJSON [lng, lat] on the wire and are converted at this boundary.
"""
from __future__ import annotations

import re
import time

from ..config import get_settings
from ..models import Provider
from ..services.geo import Tile
from .base import ProviderError, ProviderPlaceDTO, SweepResult

# Indonesian and English salon search terms. This matrix is what buys back the recall
# that the missing category-sweep costs; tune it against the gold set.
SALON_QUERY_TERMS = [
    "salon",
    "salon kecantikan",
    "salon rambut",
    "barbershop",
    "pangkas rambut",
    "nail art",
    "spa kecantikan",
    "hair studio",
]

# Grab category tokens that identify the salon vertical.
#
# These are matched as whole tokens, never as substrings. Substring matching put
# kindergartens into a live Denpasar run, because "spa" is inside "space" and Grab
# labels schools "academic space".
SALON_CATEGORY_TERMS = {
    "salon", "salons", "barber", "barbers", "barbershop", "spa", "spas", "nail", "nails",
    "kecantikan", "beauty", "hair", "grooming", "makeup", "manicure", "pedicure",
    "cukur", "rambut", "waxing", "lashes", "kuku",
}

# GrabMaps categories are hierarchical paths: "beauty services::spas",
# "education::academic spaces", "healthcare::pets::groomer". Classification keys off
# that hierarchy, not off loose token matching over the whole blob.
#
# The salon vertical is the "beauty services" subtree in its entirety — it contains
# other salons, spas, hair, nails, barbers, makeup, skin care, massage and reflexology.
SALON_CATEGORY_ROOT = "beauty services"

# Subtrees that are not this vertical even when a beauty tag is also present. Note
# that plain "healthcare" is deliberately NOT here: Grab files massage therapy under
# "healthcare::massage therapy", so excluding the whole healthcare root drops every
# salon that also offers massage — which it did, on a live Denpasar run.
VETO_CATEGORY_PATHS = (
    "healthcare::pets",        # pet grooming is a different business
    "healthcare::physicians",  # medical practice, e.g. plastic surgery
    "healthcare::hospital",
    "healthcare::dentist",
    "healthcare::pharmacy",
)

_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")

PLACE_TYPES_KEPT = {"PointOfInterest", "PointAddress", "Street", "Locality"}
MAX_RESULTS_PER_CALL = 100  # API ceiling for SearchText


class GrabMapsAdapter:
    provider = Provider.GRAB

    def __init__(self, client=None):
        settings = get_settings()
        self.settings = settings
        self._api_key = settings.aws_location_api_key or None
        if client is not None:
            self._client = client
            return
        if not settings.grab_enabled:
            raise ProviderError(
                "GrabMaps is not configured: set AWS_LOCATION_API_KEY, or "
                "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY"
            )
        try:
            import boto3  # imported lazily so the rest of the app runs without boto3
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise ProviderError("boto3 is required for the GrabMaps adapter: pip install boto3") from exc

        if self._api_key:
            # An Amazon Location API key authenticates the request on its own, so the
            # request must go out unsigned — botocore would otherwise refuse to build
            # it without IAM credentials present.
            from botocore import UNSIGNED
            from botocore.config import Config

            self._client = boto3.client(
                "geo-places", region_name=settings.aws_region, config=Config(signature_version=UNSIGNED)
            )
            return

        kwargs = {
            "region_name": settings.aws_region,
            "aws_access_key_id": settings.aws_access_key_id,
            "aws_secret_access_key": settings.aws_secret_access_key,
        }
        if settings.aws_session_token:
            kwargs["aws_session_token"] = settings.aws_session_token
        self._client = boto3.client("geo-places", **kwargs)

    # --- mapping -----------------------------------------------------------

    @staticmethod
    def _category_names(item: dict) -> list[str]:
        names: list[str] = []
        for category in item.get("Categories") or []:
            for key in ("Name", "LocalizedName", "Id"):
                value = category.get(key)
                if value:
                    names.append(str(value))
        return names

    def _to_dto(self, item: dict) -> ProviderPlaceDTO:
        address = item.get("Address") or {}
        position = item.get("Position") or []
        # Position is GeoJSON order: [longitude, latitude].
        lng = position[0] if len(position) >= 2 else None
        lat = position[1] if len(position) >= 2 else None
        region = address.get("Region") or {}
        return ProviderPlaceDTO(
            provider=Provider.GRAB,
            provider_place_id=item.get("PlaceId") or "",
            name=item.get("Title") or "",
            categories=self._category_names(item),
            address=address.get("Label"),
            city=address.get("Locality") or address.get("District"),
            province=region.get("Name") or region.get("Code"),
            postal_code=address.get("PostalCode"),
            lat=lat,
            lng=lng,
            # GrabMaps cannot return Contacts in ap-southeast-1/5, so these stay None.
            phone=None,
            website=None,
            business_status=None,
            raw=item,
        )

    # --- transport ---------------------------------------------------------

    @staticmethod
    def _pricing_bucket(payload: dict) -> str | None:
        """Amazon Location reports the bucket it charged in a response header."""
        headers = (payload.get("ResponseMetadata") or {}).get("HTTPHeaders") or {}
        return headers.get("x-amz-geo-pricing-bucket")

    def _search_text(self, query: str, lat: float, lng: float, radius_m: float, max_results: int) -> tuple[list[dict], int, dict[str, int]]:
        """One paginated SearchText query. Returns (items, api_calls_made, buckets)."""
        items: list[dict] = []
        calls = 0
        buckets: dict[str, int] = {}
        next_token: str | None = None
        while True:
            request = {
                "QueryText": query[:200],
                "Filter": {
                    # Radius must be an integer: botocore rejects a float outright,
                    # client-side, before any request is sent.
                    "Circle": {"Center": [float(lng), float(lat)], "Radius": int(round(radius_m))},
                    "IncludeCountries": [self.settings.grab_country],
                },
                "MaxResults": int(min(max_results, MAX_RESULTS_PER_CALL)),
                "Language": self.settings.grab_language,
                "IntendedUse": self.settings.grab_intended_use,
            }
            if next_token:
                request["NextToken"] = next_token
            if self._api_key:
                request["Key"] = self._api_key
            last_error: Exception | None = None
            payload = None
            for attempt in range(self.settings.provider_max_retries):
                try:
                    payload = self._client.search_text(**request)
                    calls += 1
                    break
                except Exception as exc:  # botocore raises ClientError subclasses
                    last_error = exc
                    if _is_throttle(exc) and attempt < self.settings.provider_max_retries - 1:
                        time.sleep(2**attempt)
                        continue
                    raise ProviderError(f"GrabMaps SearchText failed: {exc}") from exc
            if payload is None:  # pragma: no cover - defensive
                raise ProviderError(f"GrabMaps SearchText failed: {last_error}")

            bucket = self._pricing_bucket(payload)
            if bucket:
                buckets[bucket] = buckets.get(bucket, 0) + 1

            items.extend(payload.get("ResultItems") or [])
            next_token = payload.get("NextToken")
            if not next_token or len(items) >= max_results:
                break
        return items, calls, buckets

    # --- operations --------------------------------------------------------

    def sweep(self, tile: Tile) -> SweepResult:
        """Keyword matrix over one tile, deduplicated by PlaceId."""
        by_id: dict[str, ProviderPlaceDTO] = {}
        total_calls = 0
        saturated = False
        all_buckets: dict[str, int] = {}
        for term in SALON_QUERY_TERMS:
            items, calls, buckets = self._search_text(term, tile.lat, tile.lng, tile.radius_m, MAX_RESULTS_PER_CALL)
            total_calls += calls
            for name, count in buckets.items():
                all_buckets[name] = all_buckets.get(name, 0) + count
            if len(items) >= MAX_RESULTS_PER_CALL:
                saturated = True
            for item in items:
                if item.get("PlaceType") and item["PlaceType"] not in PLACE_TYPES_KEPT:
                    continue
                dto = self._to_dto(item)
                if dto.provider_place_id:
                    by_id.setdefault(dto.provider_place_id, dto)
        return SweepResult(
            places=list(by_id.values()),
            api_calls=total_calls,
            saturated=saturated,
            pricing_buckets=all_buckets,
        )

    def probe(self, name: str, lat: float, lng: float, address: str | None) -> SweepResult:
        query = " ".join(part for part in [name, address] if part).strip()
        items, calls, buckets = self._search_text(query, lat, lng, 500.0, 10)
        return SweepResult(
            places=[self._to_dto(i) for i in items], api_calls=calls, pricing_buckets=buckets
        )


def _is_throttle(exc: Exception) -> bool:
    code = getattr(exc, "response", {}).get("Error", {}).get("Code", "") if hasattr(exc, "response") else ""
    return code in {"ThrottlingException", "TooManyRequestsException", "InternalServerException"}


def category_tokens(categories: list[str]) -> set[str]:
    return {t for t in _TOKEN_SPLIT.split(" ".join(categories).lower()) if t}


def _hierarchy_paths(categories: list[str]) -> list[str]:
    """Category entries that carry taxonomy position, i.e. contain a '::' separator."""
    return [c.lower().strip() for c in categories if "::" in c]


def _has_salon_path(categories: list[str]) -> bool:
    """True when any category sits in the beauty services tree.

    A category can be positioned at the root itself, in which case Grab emits the bare
    group name with no '::'. "Kanaya Salon & Butik" is tagged exactly that way — flat
    "beauty services" alongside general merchandise::fashion leaves — so requiring a
    '::' here would drop a business with "Salon" in its name.
    """
    root = SALON_CATEGORY_ROOT
    return any(
        c.lower().strip() == root or c.lower().strip().startswith(root + "::")
        for c in categories
    )


def is_excluded_grab_category(categories: list[str]) -> bool:
    """Authoritative veto, which also overrides any name-based fallback.

    Two ways to be vetoed: sitting in a disqualifying subtree, or carrying a full
    category hierarchy that contains nothing under beauty services at all. The second
    is what keeps a school called "Taman Pendidikan ... Salon" out of a salon dataset:
    the provider's own taxonomy says education, so the name does not get a vote.
    """
    paths = _hierarchy_paths(categories)
    if any(path.startswith(veto) for path in paths for veto in VETO_CATEGORY_PATHS):
        return True
    return bool(paths) and not _has_salon_path(categories)


def is_salon_grab_category(categories: list[str]) -> bool:
    """True when GrabMaps files this place under the beauty services vertical."""
    if is_excluded_grab_category(categories):
        return False
    if _has_salon_path(categories):
        return True
    if _hierarchy_paths(categories):
        return False
    # No hierarchy supplied: fall back to whole-token matching. Tokens, never
    # substrings — "spa" is inside "space", and Grab labels schools "academic space".
    return bool(category_tokens(categories) & SALON_CATEGORY_TERMS)
