from __future__ import annotations

from typing import Any

import httpx

from ..config import get_settings
from ..models import ConnectorMode, SourceConnector

settings = get_settings()


class ConnectorError(RuntimeError):
    pass


def _google_places(query: str, max_results: int, latitude: float | None, longitude: float | None, radius_m: int) -> list[dict[str, Any]]:
    if not settings.google_places_api_key:
        raise ConnectorError("GOOGLE_PLACES_API_KEY is not configured")
    body: dict[str, Any] = {"textQuery": query, "maxResultCount": min(max_results, 20), "languageCode": "id"}
    if latitude is not None and longitude is not None:
        body["locationBias"] = {"circle": {"center": {"latitude": latitude, "longitude": longitude}, "radius": float(radius_m)}}
    headers = {
        "X-Goog-Api-Key": settings.google_places_api_key,
        "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.location,places.primaryType,places.websiteUri,places.internationalPhoneNumber,places.googleMapsUri,places.businessStatus",
    }
    response = httpx.post("https://places.googleapis.com/v1/places:searchText", json=body, headers=headers, timeout=45)
    if response.status_code >= 400:
        raise ConnectorError(f"Google Places error {response.status_code}: {response.text[:500]}")
    records = []
    for place in response.json().get("places", []):
        records.append({
            "business_name": (place.get("displayName") or {}).get("text"),
            "category": place.get("primaryType") or "Hair Salon",
            "full_address": place.get("formattedAddress"),
            "latitude": (place.get("location") or {}).get("latitude"),
            "longitude": (place.get("location") or {}).get("longitude"),
            "phone": place.get("internationalPhoneNumber"),
            "website": place.get("websiteUri"),
            "primary_source_url": place.get("googleMapsUri"),
            "source_record_id": place.get("id"),
            "business_status": place.get("businessStatus"),
        })
    return records


def _grabmaps_aws(query: str, max_results: int, latitude: float | None, longitude: float | None) -> list[dict[str, Any]]:
    if not settings.aws_grab_place_index:
        raise ConnectorError("AWS_GRAB_PLACE_INDEX is not configured")
    try:
        import boto3
        client = boto3.client("location", region_name=settings.aws_region)
        kwargs: dict[str, Any] = {
            "IndexName": settings.aws_grab_place_index,
            "Text": query,
            "MaxResults": min(max_results, 50),
            "FilterCountries": ["IDN"],
        }
        if latitude is not None and longitude is not None:
            kwargs["BiasPosition"] = [longitude, latitude]
        response = client.search_place_index_for_text(**kwargs)
    except Exception as exc:  # provider exception text is retained in the connector run
        raise ConnectorError(f"GrabMaps/Amazon Location error: {exc}") from exc
    records = []
    for item in response.get("Results", []):
        place = item.get("Place", {})
        position = place.get("Geometry", {}).get("Point", [None, None])
        records.append({
            "business_name": place.get("Label") or place.get("Municipality") or "Unnamed candidate",
            "category": (place.get("Categories") or ["Hair Salon"])[0],
            "full_address": place.get("Label"),
            "city": place.get("Municipality"),
            "province": place.get("Region"),
            "postal_code": place.get("PostalCode"),
            "longitude": position[0] if len(position) > 0 else None,
            "latitude": position[1] if len(position) > 1 else None,
            "source_record_id": item.get("PlaceId"),
        })
    return records


def _apify(connector: SourceConnector, query: str, max_results: int, city: str | None) -> list[dict[str, Any]]:
    if not settings.apify_token:
        raise ConnectorError("APIFY_TOKEN is not configured")
    actor_id = connector.configuration.get("actor_id")
    if not actor_id:
        source = connector.source_type.upper()
        actor_id = {
            "INSTAGRAM": settings.apify_instagram_actor_id,
            "TIKTOK": settings.apify_tiktok_actor_id,
            "FACEBOOK": settings.apify_facebook_actor_id,
        }.get(source)
    if not actor_id:
        raise ConnectorError("No Apify actor_id is configured for this connector")
    actor_path = str(actor_id).replace("/", "~")
    input_template = connector.configuration.get("input_template") or {
        "search": f"{query} {city or ''}".strip(),
        "resultsLimit": max_results,
    }
    url = f"https://api.apify.com/v2/acts/{actor_path}/run-sync-get-dataset-items"
    response = httpx.post(url, params={"token": settings.apify_token}, json=input_template, timeout=300)
    if response.status_code >= 400:
        raise ConnectorError(f"Apify error {response.status_code}: {response.text[:500]}")
    data = response.json()
    return data if isinstance(data, list) else [data]


def run_connector(
    connector: SourceConnector,
    query: str,
    max_results: int,
    city: str | None,
    latitude: float | None,
    longitude: float | None,
    radius_m: int,
) -> list[dict[str, Any]]:
    if not connector.enabled:
        raise ConnectorError("Connector is disabled")
    if connector.mode == ConnectorMode.MOCK:
        return [{
            "business_name": f"MOCK {query} Example",
            "category": "Hair Salon",
            "full_address": f"Demonstration address, {city or 'Indonesia'}",
            "city": city or "Jakarta",
            "province": "Indonesia",
            "latitude": latitude or -6.2088,
            "longitude": longitude or 106.8456,
            "phone": "+62-000-MOCK",
            "primary_source_url": "https://example.invalid/mock-source",
            "source_record_id": "MOCK-ONLY",
            "_mock": True,
        }]
    source_type = connector.source_type.upper()
    if source_type in {"GOOGLE", "GOOGLE_PLACES"}:
        return _google_places(query, max_results, latitude, longitude, radius_m)
    if source_type in {"GRAB", "GRABMAPS", "AMAZON_LOCATION_GRAB"}:
        return _grabmaps_aws(query, max_results, latitude, longitude)
    if source_type in {"INSTAGRAM", "TIKTOK", "FACEBOOK", "APIFY"}:
        return _apify(connector, query, max_results, city)
    raise ConnectorError(f"No live adapter is implemented for source type {connector.source_type}; use FILE_UPLOAD mode")
