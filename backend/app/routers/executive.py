from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import City, Project, User
from ..services.city_analytics import STUDY_CITY_SLUG, dataset as city_dataset
from ..services.customer_pack import build_customer_pack

router = APIRouter(prefix="/executive", tags=["Executive Customer Demo"])
DATA_FILE = Path(__file__).parents[1] / "data" / "denpasar_customer_demo.json"


def _find_sample_output() -> Path:
    """Locate sample_output, which sits at the repo root but beside the app in
    the deployment image."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "sample_output"
        if candidate.is_dir():
            return parent
    return Path(__file__).parents[3]


ROOT_DIR = _find_sample_output()

EXCLUDE_TERMS = {
    "tattoo", "pijat", "massage", "reflexology", "toko", "shop", "store",
    "es cantik", "make up artist", "makeup artist", "warung", "pet shop",
}
PREFERRED_TERMS = {
    "hair salon", "salon rambut", "beauty salon", "salon kecantikan",
    "salon wanita", "hair studio", "beauty studio", "salon muslimah",
}


def _payload() -> dict:
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def _bundled_pack_path() -> Path:
    return ROOT_DIR / "sample_output" / "GeoDiscover_Executive_Customer_Sample_v5.xlsx"


def _has_bundled_pack(db: Session, city_id: int | None) -> bool:
    """Only the signed-off Denpasar city ships with a pre-built customer pack."""
    if not city_id:
        return False
    city = db.get(City, city_id)
    return bool(city and city.slug == STUDY_CITY_SLUG and not city.headline and _bundled_pack_path().exists())


def _data(db: Session, project_id: int, city_id: int | None) -> dict:
    try:
        return city_dataset(db, project_id, city_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


def _require_project(project_id: int, db: Session) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


def _candidate_strength(row: dict) -> float:
    name = str(row.get("business_name") or "").lower()
    categories = str(row.get("categories") or "").lower()
    text = f"{name} {categories}"
    score = 0.0
    if row.get("customer_tier") == "TIER_1_DIRECT_PROBE":
        score += 40
    if any(term in text for term in PREFERRED_TERMS):
        score += 25
    if "salon" in name:
        score += 10
    if row.get("result_count") in (0, None):
        score += 10
    if row.get("address") and len(str(row["address"])) >= 25:
        score += 5
    if row.get("latitude") is not None and row.get("longitude") is not None:
        score += 5
    best_score = row.get("best_score")
    if isinstance(best_score, (int, float)):
        score += max(0, 5 - min(5, best_score / 20))
    if any(term in text for term in EXCLUDE_TERMS):
        score -= 100
    return round(score, 2)


def _sample_record(row: dict, rank: int) -> dict:
    return {
        "rank": rank,
        "provider_place_id": row.get("provider_place_id"),
        "business_name": row.get("business_name"),
        "categories": row.get("categories"),
        "address": row.get("address"),
        "city": row.get("city"),
        "latitude": row.get("latitude"),
        "longitude": row.get("longitude"),
        "evidence_method": row.get("evidence_method"),
        "evidence_strength": row.get("evidence_strength"),
        "probe_query": row.get("probe_query"),
        "result_count": row.get("result_count"),
        "best_score": row.get("best_score"),
        "evidence_reason": row.get("evidence_reason"),
        "strength_score": _candidate_strength(row),
        "current_status": "PRIORITY VALIDATION CANDIDATE",
        "customer_ready": False,
        "next_actions": [
            "Confirm customer-approved salon category",
            "Enrich phone, WhatsApp, website or active social profile",
            "Complete all 16 Google-exclusion checks",
            "Confirm recent business activity",
            "Complete independent QA",
        ],
    }


@router.get("/{project_id}/summary")
def executive_summary(
    project_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    city_id: int | None = Query(None, description="Restrict to one city; omit for every city"),
):
    project = _require_project(project_id, db)
    data = _data(db, project_id, city_id)
    study = data["study"]
    headline = study["headline"]
    where = study["geography"]
    matched = headline.get("total_matched_pairs")

    if matched is None:
        message = (
            f"JSAN loaded {headline.get('records_total') or 0} businesses for {where} and prioritised "
            f"{headline['tier1_direct_probe_candidates']} direct-probe candidates for enrichment, complete "
            "Google exclusion and independent QA. No Grab-versus-Google comparison run exists for this city yet."
        )
    else:
        message = (
            f"JSAN compared {headline['grab_inventory']} Grab POIs with {headline['google_inventory']} Google POIs "
            f"across {where}, identified {matched} matched pairs, and created a priority queue of "
            f"{headline['tier1_direct_probe_candidates']} direct-probe candidates for enrichment, complete "
            "Google exclusion and independent QA."
        )

    scope = [
        "Compare authorised Grab and Google POI extracts",
        "Explain matched, possible, incremental and unresolved outcomes",
        f"Prioritise {headline['tier1_direct_probe_candidates']} direct-probe candidates for deeper validation",
        "Show real coordinates, evidence reasons and cost controls",
        "Block customer release until enrichment and independent QA are complete",
    ]
    if not data["comparison_available"]:
        scope = [line for line in scope if "Compare authorised" not in line and "Explain matched" not in line]
        scope.insert(0, f"Load and validate the {where} workbook business by business")

    return {
        "project": {"id": project.id, "name": project.name, "customer": project.customer},
        "study": study,
        "basis": data["basis"],
        "basis_label": data["basis_label"],
        "city": data["city"],
        "cities": data["cities"],
        "comparison_available": data["comparison_available"],
        "bundled_pack": _has_bundled_pack(db, city_id),
        "note": data["note"],
        "story": {
            "current_scope": scope,
            "not_claimed_today": [
                "Confirmed active salons absent from Google",
                f"Complete coverage of {where}",
                "Production-scale automated social discovery",
            ],
            "customer_message": message,
        },
        "demo_only": True,
    }


@router.get("/{project_id}/sample")
def priority_sample(
    project_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    limit: int = Query(10, ge=1, le=25),
    city_id: int | None = Query(None, description="Restrict to one city; omit for every city"),
):
    _require_project(project_id, db)
    data = _data(db, project_id, city_id)
    tier1 = [row for row in data["candidates"] if row.get("customer_tier") == "TIER_1_DIRECT_PROBE"]
    ranked = sorted(tier1, key=lambda row: (-_candidate_strength(row), str(row.get("business_name") or "")))
    selected = ranked[:limit]
    return {
        "count": len(selected),
        "available_tier1": len(tier1),
        "city": data["city"],
        "cities": data["cities"],
        "basis": data["basis"],
        "records": [_sample_record(row, idx + 1) for idx, row in enumerate(selected)],
        "guardrail": "These are priority validation candidates, not customer-released POIs.",
    }


@router.get("/{project_id}/comparison-proof")
def comparison_proof(
    project_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    limit: int = Query(8, ge=1, le=20),
    city_id: int | None = Query(None, description="Restrict to one city; omit for every city"),
):
    _require_project(project_id, db)
    data = _data(db, project_id, city_id)
    lookup = {(r.get("provider"), r.get("provider_place_id")): r for r in data["candidates"]}
    rows = []
    for match in sorted(data["matches"], key=lambda x: float(x.get("match_score") or 0), reverse=True):
        grab = lookup.get(("GRAB", match.get("grab_id")))
        google = lookup.get(("GOOGLE", match.get("google_id")))
        if not grab or not google:
            continue
        rows.append({
            "kind": match.get("kind"),
            "grab": {
                "id": grab.get("provider_place_id"),
                "name": grab.get("business_name"),
                "address": grab.get("address"),
                "latitude": grab.get("latitude"),
                "longitude": grab.get("longitude"),
            },
            "google": {
                "id": google.get("provider_place_id"),
                "name": google.get("business_name"),
                "address": google.get("address"),
                "latitude": google.get("latitude"),
                "longitude": google.get("longitude"),
            },
            "match_score": match.get("match_score"),
            "distance_m": match.get("distance_m"),
            "method": match.get("method"),
            "signal_breakdown": match.get("signal_breakdown"),
        })
        if len(rows) >= limit:
            break
    return {
        "rows": rows,
        "count": len(rows),
        "city": data["city"],
        "cities": data["cities"],
        "basis": data["basis"],
        "comparison_available": data["comparison_available"],
        "note": data["note"],
    }


@router.get("/{project_id}/map.geojson")
def executive_map(
    project_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    layer: str = Query("current", pattern="^(current|tier1|tier2|matched)$"),
    city_id: int | None = Query(None, description="Restrict to one city; omit for every city"),
):
    _require_project(project_id, db)
    data = _data(db, project_id, city_id)
    features = []
    seen = set()
    for row in data["candidates"]:
        role = row.get("role")
        tier = row.get("customer_tier")
        include = False
        map_layer = None
        if tier == "TIER_1_DIRECT_PROBE":
            map_layer = "TIER 1 · DIRECT PROBE"
            include = layer in {"current", "tier1"}
        elif tier == "TIER_2_AREA_SUPPORTED":
            map_layer = "TIER 2 · AREA SUPPORTED"
            include = layer in {"current", "tier2"}
        elif role == "MATCHED" and row.get("provider") == "GRAB":
            map_layer = "MATCHED"
            include = layer in {"current", "matched"}
        elif role == "WORKBOOK":
            # Uploaded rows with no probe yet still have real coordinates. The
            # benchmark study's own unresolved rows stay off the map as before.
            map_layer = "NOT PROBED"
            include = layer == "current"
        if not include or row.get("latitude") is None or row.get("longitude") is None:
            continue
        key = (row.get("provider"), row.get("provider_place_id"), row.get("business_name"))
        if key in seen:
            continue
        seen.add(key)
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [row["longitude"], row["latitude"]]},
            "properties": {
                "id": row.get("provider_place_id"),
                "business_name": row.get("business_name"),
                "address": row.get("address"),
                "city": row.get("city"),
                "layer": map_layer,
                "evidence_method": row.get("evidence_method"),
                "customer_ready": False,
            },
        })
    return {
        "type": "FeatureCollection",
        "features": features,
        "city": data["city"],
        "cities": data["cities"],
        "basis": data["basis"],
    }


@router.get("/{project_id}/future-modules")
def future_modules(
    project_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    _require_project(project_id, db)
    return {
        "current_demo": [
            "Grab-versus-Google comparison",
            "Explainable matching and evidence tiers",
            "Priority sample queue",
            "Real-coordinate map",
            "Cost and scale view",
            "Controlled customer workbook",
        ],
        "phase_2_after_customer_alignment": [
            "Complete Strong 10/25 contact and social enrichment",
            "All 16 Google-exclusion checks per selected POI",
            "Independent QA and evidence ZIP",
            "Customer-approved release workbook",
        ],
        "future_scale": [
            "Live multi-city scheduled discovery",
            "Instagram, TikTok, Facebook and booking-platform enrichment",
            "AI calling and local-research queues",
            "PostGIS, background workers, object storage and enterprise SSO",
            "National coverage and customer API delivery",
        ],
    }


@router.get("/{project_id}/download/customer-pack")
def download_customer_pack(
    project_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    city_id: int | None = Query(None, description="Restrict to one city; omit for every city"),
):
    _require_project(project_id, db)
    data = _data(db, project_id, city_id)

    # The bundled pack is the signed-off artefact for Denpasar only; every other
    # city gets a pack generated from its own data.
    if _has_bundled_pack(db, city_id):
        path = _bundled_pack_path()
        return FileResponse(
            path,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=path.name,
        )

    stream, filename = build_customer_pack(data)
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
