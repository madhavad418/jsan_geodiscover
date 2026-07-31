from __future__ import annotations

import math
import re
from urllib.parse import urlparse

from rapidfuzz import fuzz

from ..models import PoiCandidate
from .normalization import normalize_text


def haversine_m(lat1: float | None, lon1: float | None, lat2: float | None, lon2: float | None) -> float | None:
    if None in (lat1, lon1, lat2, lon2):
        return None
    radius = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def coordinate_similarity(distance_m: float | None) -> float:
    if distance_m is None:
        return 0.0
    if distance_m <= 25:
        return 100.0
    if distance_m <= 75:
        return 95.0
    if distance_m <= 150:
        return 85.0
    if distance_m <= 300:
        return 70.0
    if distance_m <= 750:
        return 45.0
    if distance_m <= 1500:
        return 20.0
    return 0.0


def normalize_phone(value: str | None) -> str:
    digits = re.sub(r"\D", "", value or "")
    if digits.startswith("0"):
        digits = "62" + digits[1:]
    return digits


def domain(value: str | None) -> str:
    if not value:
        return ""
    parsed = urlparse(value if "://" in value else "https://" + value)
    return parsed.netloc.lower().removeprefix("www.")


def social_handles(candidate: PoiCandidate) -> set[str]:
    values = [candidate.instagram, candidate.facebook, candidate.tiktok]
    result: set[str] = set()
    for value in values:
        if value:
            result.add(normalize_text(value).replace(" ", ""))
    return result


def score_pair(left: PoiCandidate, right: PoiCandidate) -> dict:
    left_names = [left.normalized_name or normalize_text(left.business_name)] + [normalize_text(x) for x in (left.alternate_names or [])]
    right_names = [right.normalized_name or normalize_text(right.business_name)] + [normalize_text(x) for x in (right.alternate_names or [])]
    if left.branch_name:
        left_names.append(normalize_text(f"{left.business_name} {left.branch_name}"))
    if right.branch_name:
        right_names.append(normalize_text(f"{right.business_name} {right.branch_name}"))
    name_score = max(float(fuzz.token_set_ratio(a, b)) for a in left_names for b in right_names)
    left_address = normalize_text(" ".join(filter(None, [left.full_address, left.locality, left.district, left.city])))
    right_address = normalize_text(" ".join(filter(None, [right.full_address, right.locality, right.district, right.city])))
    address_score = float(fuzz.token_set_ratio(left_address, right_address)) if left_address and right_address else 0.0
    distance = haversine_m(left.latitude, left.longitude, right.latitude, right.longitude)
    coordinate_score = coordinate_similarity(distance)

    left_phones = {normalize_phone(left.phone), normalize_phone(left.whatsapp)} - {""}
    right_phones = {normalize_phone(right.phone), normalize_phone(right.whatsapp)} - {""}
    phone_score = 100.0 if left_phones & right_phones else 0.0

    left_domains = {domain(left.website), domain(left.booking_url)} - {""}
    right_domains = {domain(right.website), domain(right.booking_url)} - {""}
    web_match = bool(left_domains & right_domains)
    social_match = bool(social_handles(left) & social_handles(right))
    web_social_score = 100.0 if web_match or social_match else 0.0

    source_record_id_match = bool(left.source_record_id and right.source_record_id and left.source_record_id == right.source_record_id)
    total = round(
        name_score * 0.30
        + coordinate_score * 0.25
        + phone_score * 0.20
        + address_score * 0.15
        + web_social_score * 0.10,
        2,
    )
    if source_record_id_match:
        total = 100.0
    return {
        "name_score": round(name_score, 2),
        "coordinate_score": round(coordinate_score, 2),
        "phone_score": phone_score,
        "address_score": round(address_score, 2),
        "web_social_score": web_social_score,
        "total_score": total,
        "distance_m": round(distance, 2) if distance is not None else None,
        "explanation": {
            "weights": {"name": 30, "coordinates": 25, "phone_whatsapp": 20, "address": 15, "web_social": 10},
            "phone_match": bool(left_phones & right_phones),
            "domain_match": web_match,
            "social_match": social_match,
            "source_record_id_match": source_record_id_match,
            "left_source_record_id": left.source_record_id,
            "right_source_record_id": right.source_record_id,
            "branch_names": [left.branch_name, right.branch_name],
        },
    }
