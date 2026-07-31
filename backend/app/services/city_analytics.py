"""Per-city datasets behind the executive views.

Denpasar shipped with a full benchmark study (968 candidates and 319 scored
Grab/Google pairs). Cities added later only have the workbook that was uploaded
for them, which carries no cross-provider match run. Both are shaped into the
same payload here, and every dataset states its `basis` so a view can say where
its numbers came from instead of implying the two are equivalent.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import City, CityCandidate, CityMatch, ValidationRecord

DATA_FILE = Path(__file__).parents[1] / "data" / "denpasar_customer_demo.json"

# The bundled study describes this city; any other city is workbook-only.
STUDY_CITY_SLUG = "denpasar"

BENCHMARK_STUDY = "BENCHMARK_STUDY"
CITY_WORKBOOK = "CITY_WORKBOOK"
PORTFOLIO = "PORTFOLIO"

BASIS_LABELS = {
    BENCHMARK_STUDY: "Controlled Grab-vs-Google benchmark study",
    CITY_WORKBOOK: "Uploaded city workbook",
    PORTFOLIO: "All cities combined",
}

TIER_BY_METHOD = {
    "PROBE": "TIER_1_DIRECT_PROBE",
    "AREA_COVERAGE": "TIER_2_AREA_SUPPORTED",
}


def _study_payload() -> dict[str, Any]:
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def _record_as_candidate(record: ValidationRecord) -> dict[str, Any]:
    # A benchmark import settles the role and tier, so take them as given - only
    # a plain workbook row needs a tier derived from its evidence method. A
    # Google-side probe row is not a direct-probe candidate.
    if record.role:
        role, tier = record.role, record.customer_tier
    else:
        tier = TIER_BY_METHOD.get(record.evidence_method or "")
        role = "INCREMENTAL" if tier else "WORKBOOK"
    return {
        "provider": record.provider,
        "provider_place_id": record.provider_place_id,
        "role": role,
        "business_name": record.business_name,
        "categories": record.categories,
        "address": record.address,
        "city": None,  # filled in by the caller with the city name
        "latitude": record.latitude,
        "longitude": record.longitude,
        "customer_tier": tier,
        "evidence_method": record.evidence_method,
        "evidence_strength": record.evidence_strength,
        "probe_query": record.probe_query,
        "result_count": record.result_count,
        "best_score": record.best_score,
        "evidence_reason": record.evidence_reason,
        "found_by_probe": record.found_by_probe,
        # Validation-layer evidence, so the executive views can reflect real progress.
        "identified_contact_number": record.identified_contact_number,
        "validation_status": record.validation_status,
    }


def _headline_from_records(records: list[ValidationRecord]) -> dict[str, Any]:
    def count(predicate) -> int:
        return sum(1 for r in records if predicate(r))

    total = len(records)
    contactable = count(lambda r: bool(r.identified_contact_number))
    return {
        "grab_inventory": count(lambda r: r.provider == "GRAB"),
        "google_inventory": count(lambda r: r.provider == "GOOGLE"),
        "sweep_matches": None,
        "probe_recovered_matches": None,
        # No cross-provider comparison has been run for an uploaded workbook.
        "total_matched_pairs": None,
        "tier1_direct_probe_candidates": count(lambda r: r.evidence_method == "PROBE"),
        "tier2_area_supported_leads": count(lambda r: r.evidence_method == "AREA_COVERAGE"),
        "grab_incremental_candidates": count(lambda r: r.evidence_method in ("PROBE", "AREA_COVERAGE")),
        "possible_pairings": None,
        "grab_unresolved": count(lambda r: r.evidence_method == "NOT_PROBED" and r.provider == "GRAB"),
        "google_unresolved": count(lambda r: r.evidence_method == "NOT_PROBED" and r.provider == "GOOGLE"),
        "contactability_pct": round(contactable / total * 100, 1) if total else 0.0,
        "customer_release_ready": 0,
        "records_total": total,
        "validation_completed": count(lambda r: r.validation_status == "COMPLETED"),
        "validation_in_progress": count(lambda r: r.validation_status == "IN_PROGRESS"),
        "scraped_records": count(lambda r: r.scrape_state == "DONE"),
    }


def _city_records(db: Session, city_id: int) -> list[ValidationRecord]:
    return list(
        db.scalars(
            select(ValidationRecord)
            .where(ValidationRecord.city_id == city_id)
            .order_by(ValidationRecord.source_row)
        )
    )


def _stored_matches(db: Session, city_id: int) -> list[dict[str, Any]]:
    return [
        {
            "kind": m.kind,
            "grab_id": m.grab_place_id,
            "google_id": m.google_place_id,
            "match_score": m.match_score,
            "distance_m": m.distance_m,
            "method": m.method,
            "signal_breakdown": m.signal_breakdown,
        }
        for m in db.scalars(
            select(CityMatch).where(CityMatch.city_id == city_id).order_by(CityMatch.match_score.desc())
        )
    ]


def _benchmark_candidate(candidate: CityCandidate, city_name: str) -> dict[str, Any]:
    return {
        "provider": candidate.provider,
        "provider_place_id": candidate.provider_place_id,
        "role": candidate.role,
        "business_name": candidate.business_name,
        "categories": candidate.categories,
        "address": candidate.address,
        "city": city_name,
        "latitude": candidate.latitude,
        "longitude": candidate.longitude,
        "customer_tier": candidate.customer_tier,
        "evidence_method": candidate.evidence_method,
        "evidence_strength": candidate.evidence_strength,
        "probe_query": candidate.probe_query,
        "result_count": candidate.result_count,
        "best_score": candidate.best_score,
        "evidence_reason": candidate.evidence_reason,
        "found_by_probe": candidate.found_by_probe,
        "identified_contact_number": None,
        "validation_status": None,
    }


def _workbook_dataset(db: Session, city: City) -> dict[str, Any]:
    # A benchmark import stores the authoritative headline, coverage and pairs,
    # and its own candidate set. Otherwise the city is described by the
    # validation workbook rows themselves.
    benchmarked = bool(city.headline)
    records = _city_records(db, city.id)

    if benchmarked:
        candidates = [
            _benchmark_candidate(c, city.name)
            for c in db.scalars(
                select(CityCandidate).where(CityCandidate.city_id == city.id).order_by(CityCandidate.id)
            )
        ]
        headline = dict(city.headline)
        headline["records_total"] = len(candidates)
        # Validation progress still comes from the validation workbook.
        derived = _headline_from_records(records)
        headline["validation_records"] = derived["records_total"]
        for key in ("validation_completed", "validation_in_progress", "scraped_records"):
            headline[key] = derived[key]
        matches = _stored_matches(db, city.id)
    else:
        candidates = []
        for record in records:
            candidate = _record_as_candidate(record)
            candidate["city"] = city.name
            candidates.append(candidate)
        headline = _headline_from_records(records)
        matches = []

    return {
        "basis": BENCHMARK_STUDY if benchmarked else CITY_WORKBOOK,
        "basis_label": BASIS_LABELS[BENCHMARK_STUDY if benchmarked else CITY_WORKBOOK],
        "study": {
            "title": f"{city.name} benchmark" if benchmarked else f"{city.name} workbook",
            "customer": "L'Oréal through Web Geo Services",
            "geography": ", ".join(filter(None, [city.name, city.region, city.country])),
            "source_workbook": (
                (city.coverage or {}).get("source_workbook")
                if benchmarked
                else ", ".join(city.source_files or [])
            ) or "—",
            "headline": headline,
            "coverage": city.coverage,
        },
        "candidates": candidates,
        "matches": matches,
        "comparison_available": benchmarked,
        "note": (
            ""
            if benchmarked
            else f"{city.name} was loaded from an uploaded workbook. No Grab-versus-Google "
            "comparison run exists for it yet, so matched pairs and possible pairings are not shown."
        ),
    }


def _study_dataset(city: City | None) -> dict[str, Any]:
    payload = _study_payload()
    study = dict(payload["study"])
    study["headline"] = {**study["headline"], "records_total": len(payload["candidates"])}
    if city:
        study["geography"] = ", ".join(filter(None, [city.name, city.region, city.country]))
    return {
        "basis": BENCHMARK_STUDY,
        "basis_label": BASIS_LABELS[BENCHMARK_STUDY],
        "study": study,
        "candidates": payload["candidates"],
        "matches": payload["matches"],
        "comparison_available": True,
        "note": "",
    }


def city_options(db: Session, project_id: int) -> list[dict[str, Any]]:
    """Cities available to filter by, with the basis each one reports on."""
    cities = list(db.scalars(select(City).where(City.project_id == project_id).order_by(City.name)))
    options = []
    for city in cities:
        # In an executive context a city is sized by the places it describes,
        # which for a benchmarked city is its candidate set, not its validation
        # queue. The validation views report their own counts separately.
        if city.headline:
            total = len(db.scalars(select(CityCandidate.id).where(CityCandidate.city_id == city.id)).all())
        else:
            total = len(db.scalars(select(ValidationRecord.id).where(ValidationRecord.city_id == city.id)).all())
        options.append(
            {
                "id": city.id,
                "name": city.name,
                "region": city.region,
                "records": total,
                "basis": BENCHMARK_STUDY
                if (city.slug == STUDY_CITY_SLUG or city.headline)
                else CITY_WORKBOOK,
            }
        )
    return options


def dataset(db: Session, project_id: int, city_id: int | None) -> dict[str, Any]:
    """The dataset the executive views should read for this filter."""
    if city_id:
        city = db.get(City, city_id)
        if not city or city.project_id != project_id:
            raise ValueError("City not found")
        # The bundled study only describes Denpasar; every other city carries its own.
        if city.slug == STUDY_CITY_SLUG and not city.headline and DATA_FILE.exists():
            data = _study_dataset(city)
        else:
            data = _workbook_dataset(db, city)
        data["city"] = {"id": city.id, "name": city.name, "region": city.region}
        data["cities"] = city_options(db, project_id)
        return data

    # No filter: combine every city so the portfolio can be read as a whole.
    cities = list(db.scalars(select(City).where(City.project_id == project_id).order_by(City.name)))
    parts = [
        _study_dataset(c)
        if (c.slug == STUDY_CITY_SLUG and not c.headline and DATA_FILE.exists())
        else _workbook_dataset(db, c)
        for c in cities
    ]
    if not parts:
        parts = [_study_dataset(None)]

    candidates: list[dict[str, Any]] = []
    matches: list[dict[str, Any]] = []
    for part in parts:
        candidates.extend(part["candidates"])
        matches.extend(part["matches"])

    def total(key: str) -> Any:
        values = [p["study"]["headline"].get(key) for p in parts]
        present = [v for v in values if isinstance(v, (int, float))]
        return sum(present) if present else None

    # Study and workbook headlines carry different keys, so union them.
    keys: list[str] = []
    for part in parts:
        for key in part["study"]["headline"]:
            if key not in keys:
                keys.append(key)
    headline = {key: total(key) for key in keys}
    if headline.get("records_total") is None:
        headline["records_total"] = sum(len(p["candidates"]) for p in parts)
    records_total = total("records_total") or 0
    if records_total:
        weighted = sum(
            (p["study"]["headline"].get("contactability_pct") or 0)
            * (p["study"]["headline"].get("records_total") or 0)
            for p in parts
        )
        headline["contactability_pct"] = round(weighted / records_total, 1)

    return {
        "basis": PORTFOLIO,
        "basis_label": BASIS_LABELS[PORTFOLIO],
        "city": None,
        "cities": city_options(db, project_id),
        "study": {
            "title": "All cities",
            "customer": "L'Oréal through Web Geo Services",
            "geography": ", ".join(c.name for c in cities) or "Denpasar, Bali",
            "source_workbook": f"{len(parts)} city dataset(s)",
            "headline": headline,
            "coverage": next((p["study"].get("coverage") for p in parts if p["study"].get("coverage")), None),
        },
        "candidates": candidates,
        "matches": matches,
        "comparison_available": any(p["comparison_available"] for p in parts),
        "note": (
            "Combined view. Matched pairs come only from cities with a completed "
            "Grab-versus-Google comparison run."
        ),
    }
