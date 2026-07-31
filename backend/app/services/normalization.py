import re
import unicodedata
from typing import Any

SALON_TERMS = {
    "hair salon", "beauty salon", "salon kecantikan", "salon rambut", "penata rambut",
    "hair studio", "beauty studio", "salon wanita", "salon muslimah", "barbershop",
    "makeup artist", "nail salon", "spa kecantikan", "perawatan rambut", "salon",
}

ALIASES = {
    "name": ["business_name", "name", "poi_name", "salon_name", "title", "display_name", "username", "full_name"],
    "local_name": ["local_name", "local_language_name", "name_local"],
    "category": ["category", "type", "business_category", "subcategory", "primarytype", "primary_type"],
    "address": ["full_address", "address", "formatted_address", "street_address", "locationname", "location_name"],
    "locality": ["locality", "neighbourhood", "neighborhood", "village"],
    "district": ["district", "subdistrict", "kecamatan"],
    "city": ["city", "municipality", "kabupaten", "kota"],
    "province": ["province", "state", "administrative_area", "region"],
    "postal_code": ["postal_code", "postcode", "zip", "zip_code"],
    "lat": ["latitude", "lat", "y"],
    "lon": ["longitude", "lon", "lng", "x"],
    "phone": ["phone", "telephone", "contact_number", "internationalphonenumber"],
    "whatsapp": ["whatsapp", "wa", "whatsapp_number"],
    "email": ["email", "business_email"],
    "website": ["website", "url", "official_website", "websiteuri"],
    "booking_url": ["booking_url", "booking", "fresha_url"],
    "instagram": ["instagram", "instagram_url", "ig", "instagramurl"],
    "tiktok": ["tiktok", "tiktok_url"],
    "facebook": ["facebook", "facebook_url", "fb"],
    "source_url": ["primary_source_url", "source_url", "evidence_url", "googlemapsuri", "inputurl"],
    "source_record_id": ["source_record_id", "record_id", "id", "place_id", "placeid"],
}


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9]+", " ", value.lower()).strip()
    return re.sub(r"\s+", " ", value)


def pick(row: dict[str, Any], aliases: list[str]) -> Any:
    lowered = {str(k).strip().lower().replace(" ", "_"): v for k, v in row.items()}
    for key in aliases:
        value = lowered.get(key.lower().replace(" ", "_"))
        if value not in (None, ""):
            return value
    return None


def parse_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def is_salon_category(category: str | None, name: str | None = None) -> bool:
    combined = normalize_text(f"{category or ''} {name or ''}")
    return any(normalize_text(term) in combined for term in SALON_TERMS)


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    name = pick(row, ALIASES["name"])
    category = pick(row, ALIASES["category"]) or "Unclassified"
    return {
        "business_name": str(name).strip() if name else "Unnamed candidate",
        "normalized_name": normalize_text(str(name) if name else "Unnamed candidate"),
        "local_name": pick(row, ALIASES["local_name"]),
        "category": str(category).strip(),
        "business_verified": is_salon_category(str(category), str(name or "")),
        "full_address": pick(row, ALIASES["address"]),
        "locality": pick(row, ALIASES["locality"]),
        "district": pick(row, ALIASES["district"]),
        "city": pick(row, ALIASES["city"]),
        "province": pick(row, ALIASES["province"]),
        "postal_code": pick(row, ALIASES["postal_code"]),
        "latitude": parse_float(pick(row, ALIASES["lat"])),
        "longitude": parse_float(pick(row, ALIASES["lon"])),
        "phone": pick(row, ALIASES["phone"]),
        "whatsapp": pick(row, ALIASES["whatsapp"]),
        "email": pick(row, ALIASES["email"]),
        "website": pick(row, ALIASES["website"]),
        "booking_url": pick(row, ALIASES["booking_url"]),
        "instagram": pick(row, ALIASES["instagram"]),
        "tiktok": pick(row, ALIASES["tiktok"]),
        "facebook": pick(row, ALIASES["facebook"]),
        "primary_source_url": pick(row, ALIASES["source_url"]),
        "source_record_id": pick(row, ALIASES["source_record_id"]),
    }
