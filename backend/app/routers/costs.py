from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import City, User, ValidationRecord
from ..services.city_analytics import STUDY_CITY_SLUG, city_options

router = APIRouter(prefix="/costs", tags=["costs"])

# Effort observed on the Denpasar benchmark, per record, used to scale a plan
# for a city that has not been run yet.
RESEARCH_HOURS_PER_RECORD = 0.5
QA_HOURS_PER_RECORD = 0.167
TEXT_CALLS_PER_RECORD = 6
DETAIL_CALLS_PER_RECORD = 1


def _plan(records: int) -> dict[str, Any]:
    text_calls = records * TEXT_CALLS_PER_RECORD
    detail_calls = records * DETAIL_CALLS_PER_RECORD
    return {
        "google_text_search_calls": text_calls,
        "google_place_detail_calls": detail_calls,
        "global_list_cost": round(text_calls * 32.0 / 1000 + detail_calls * 20.0 / 1000, 2),
        "india_eligible_list_cost": round(text_calls * 9.60 / 1000 + detail_calls * 6.0 / 1000, 2),
        "research_hours": round(records * RESEARCH_HOURS_PER_RECORD, 2),
        "qa_hours": round(records * QA_HOURS_PER_RECORD, 2),
        "human_cost_status": "ENTER_JSAN_INTERNAL_HOURLY_RATES",
        "note": (
            "API spend is only one part of the pilot. Category review, enrichment, evidence "
            "capture and independent QA are the main delivery effort. Use narrow field masks "
            "to control SKU and response cost."
        ),
    }


@router.get("/denpasar")
def project_costs(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    project_id: int = Query(1),
    city_id: int | None = Query(None, description="Restrict to one city; omit for every city"),
) -> dict[str, Any]:
    """Cost view for one city, or for the whole programme when no city is given."""
    city = None
    if city_id:
        city = db.get(City, city_id)
        if not city or city.project_id != project_id:
            raise HTTPException(404, "City not found")

    scope = select(func.count(ValidationRecord.id)).where(ValidationRecord.project_id == project_id)
    if city_id:
        scope = scope.where(ValidationRecord.city_id == city_id)
    records = db.scalar(scope) or 0

    # Use the city's own recorded discovery run when its benchmark export has one.
    coverage = city.coverage if city and city.coverage else None
    if coverage:
        benchmarked = True
        google_calls = coverage.get("google_api_calls") or 0
        grab_calls = coverage.get("grab_api_calls") or 0
    else:
        benchmarked = city is None or city.slug == STUDY_CITY_SLUG
        google_calls = 72 if benchmarked else 0
        grab_calls = 200 if benchmarked else 0

    return {
        "currency": "USD",
        "pricing_date": "2026-07-30",
        "city": {"id": city.id, "name": city.name} if city else None,
        "cities": city_options(db, project_id),
        "records_in_scope": records,
        "actual_run_available": benchmarked,
        "research_note": (
            "Rates checked against official Google Maps Platform global and India pricing pages. "
            "Field masks determine the billed Places SKU."
        ),
        "actual_run": {
            "google_nearby_calls": google_calls,
            "google_global_list_cost": round(google_calls * 32.0 / 1000, 2),
            "google_india_eligible_list_cost": round(google_calls * 9.60 / 1000, 2),
            "grab_stored_calls": grab_calls,
            "grab_cost_status": "RATE_REQUIRED_FROM_AWS_ACCOUNT",
            "global_free_usage_cap": 5000,
            "india_free_usage_cap": 35000,
            "note": (
                "Gross list estimates before eligible monthly free usage and account aggregation. "
                "Grab results are persisted, so the applicable Amazon Places stored-use terms and "
                "account rate must be confirmed."
                + (
                    f" Google run status: {coverage.get('google_status')} after "
                    f"{coverage.get('google_tiles_done')}/{coverage.get('google_tiles_planned')} tiles."
                    if coverage
                    else ""
                )
                if benchmarked
                else f"No discovery run has been recorded for {city.name}. The plan below is scaled "
                     f"from the {records} records loaded for this city."
            ),
        },
        "strong_25_plan": _plan(25 if benchmarked else min(records, 25) or 25),
        "full_city_plan": _plan(records),
        "sources": [
            {"name": "Google Maps Platform pricing", "url": "https://developers.google.com/maps/billing-and-pricing/pricing"},
            {"name": "Google India pricing", "url": "https://developers.google.com/maps/billing-and-pricing/pricing-india"},
            {"name": "Amazon Location Places pricing", "url": "https://aws.amazon.com/location/pricing/"},
        ],
        "commercial_guardrail": (
            "Do not treat estimated API consumption as the customer selling price. Customer pricing "
            "must include discovery operations, enrichment, QA, project management, evidence "
            "packaging and contingency."
        ),
    }
