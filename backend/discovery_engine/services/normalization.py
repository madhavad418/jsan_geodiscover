import re
import unicodedata
from typing import Any

SALON_TERMS = {
    "hair salon", "beauty salon", "salon kecantikan", "salon rambut", "penata rambut",
    "hair studio", "beauty studio", "salon wanita", "salon muslimah", "barbershop",
    "makeup artist", "nail salon", "spa kecantikan", "perawatan rambut", "salon"
}

ALIASES = {
    "name": ["business_name", "name", "poi_name", "salon_name", "title"],
    "category": ["category", "type", "business_category", "subcategory"],
    "address": ["full_address", "address", "formatted_address", "street_address"],
    "city": ["city", "municipality", "kabupaten", "kota"],
    "province": ["province", "state", "administrative_area", "region"],
    "lat": ["latitude", "lat", "y"],
    "lon": ["longitude", "lon", "lng", "x"],
    "phone": ["phone", "telephone", "contact_number"],
    "whatsapp": ["whatsapp", "wa", "whatsapp_number"],
    "website": ["website", "url", "official_website"],
    "booking_url": ["booking_url", "booking", "fresha_url"],
    "instagram": ["instagram", "instagram_url", "ig"],
    "tiktok": ["tiktok", "tiktok_url"],
    "facebook": ["facebook", "facebook_url", "fb"],
    "source_url": ["primary_source_url", "source_url", "evidence_url"],
    "source_record_id": ["source_record_id", "record_id", "id", "place_id"],
}


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9]+", " ", value.lower()).strip()
    return re.sub(r"\s+", " ", value)


def pick(row: dict[str, Any], aliases: list[str]) -> Any:
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for key in aliases:
        value = lowered.get(key)
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


# Trade words that carry no identifying information in this vertical. Two salons on the
# same street can both normalise to "salon kecantikan", so a name made only of these
# tokens must never be treated as evidence that two records are the same business.
GENERIC_NAME_TOKENS = {
    "salon", "salons", "beauty", "hair", "haircut", "barber", "barbershop", "barbers",
    "studio", "spa", "nail", "nails", "kecantikan", "rambut", "potong", "cukur",
    "make", "up", "makeup", "the", "dan", "and", "of", "by", "di", "de", "cabang",
    "pusat", "toko", "jasa", "perawatan", "klinik", "care", "shop", "house", "center",
    "centre", "id", "indonesia",
}


def match_name(value: str | None) -> str:
    """Normalised name with generic trade tokens removed, used for match scoring.

    Returns an empty string when nothing distinguishing survives, which the matcher
    treats as "no name evidence" rather than "names agree".
    """
    tokens = [t for t in normalize_text(value).split() if t and t not in GENERIC_NAME_TOKENS]
    return " ".join(tokens)


def normalize_phone_id(value: str | None) -> str | None:
    """Best-effort E.164 for Indonesian numbers. Returns None when unusable."""
    if not value:
        return None
    digits = re.sub(r"[^\d+]", "", str(value))
    if not digits:
        return None
    if digits.startswith("+"):
        digits = "+" + re.sub(r"\D", "", digits[1:])
        return digits if len(digits) >= 9 else None
    digits = re.sub(r"\D", "", digits)
    if digits.startswith("62"):
        candidate = "+" + digits
    elif digits.startswith("0"):
        candidate = "+62" + digits[1:]
    else:
        candidate = "+62" + digits
    return candidate if len(candidate) >= 10 else None


def website_domain(value: str | None) -> str | None:
    """Registrable-ish domain for comparing websites across providers."""
    if not value:
        return None
    text = str(value).strip().lower()
    text = re.sub(r"^[a-z][a-z0-9+.-]*://", "", text)
    text = text.split("/")[0].split("?")[0].split("#")[0]
    text = text.split("@")[-1]
    if text.startswith("www."):
        text = text[4:]
    text = text.split(":")[0]
    return text or None


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    name = pick(row, ALIASES["name"])
    category = pick(row, ALIASES["category"]) or "Unclassified"
    return {
        "business_name": str(name).strip() if name else "Unnamed candidate",
        "normalized_name": normalize_text(str(name) if name else "Unnamed candidate"),
        "category": str(category).strip(),
        "business_verified": is_salon_category(str(category), str(name or "")),
        "full_address": pick(row, ALIASES["address"]),
        "city": pick(row, ALIASES["city"]),
        "province": pick(row, ALIASES["province"]),
        "latitude": parse_float(pick(row, ALIASES["lat"])),
        "longitude": parse_float(pick(row, ALIASES["lon"])),
        "phone": pick(row, ALIASES["phone"]),
        "whatsapp": pick(row, ALIASES["whatsapp"]),
        "website": pick(row, ALIASES["website"]),
        "booking_url": pick(row, ALIASES["booking_url"]),
        "instagram": pick(row, ALIASES["instagram"]),
        "tiktok": pick(row, ALIASES["tiktok"]),
        "facebook": pick(row, ALIASES["facebook"]),
        "primary_source_url": pick(row, ALIASES["source_url"]),
        "source_record_id": pick(row, ALIASES["source_record_id"]),
    }
