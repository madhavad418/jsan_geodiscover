from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import PoiCandidate, Project, User

router = APIRouter(prefix="/maps", tags=["Map Intelligence"])


@router.get("/{project_id}/geojson")
def project_geojson(
    project_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    city: str | None = None,
    source: str | None = None,
    status: str | None = None,
):
    if not db.get(Project, project_id):
        raise HTTPException(404, "Project not found")
    query = select(PoiCandidate).where(PoiCandidate.project_id == project_id, PoiCandidate.latitude.is_not(None), PoiCandidate.longitude.is_not(None))
    if city:
        query = query.where(PoiCandidate.city == city)
    if source:
        query = query.where(PoiCandidate.source_name == source)
    rows = db.scalars(query).all()
    if status:
        rows = [row for row in rows if row.google_status.value == status or row.comparison_bucket.value == status or row.qa_status.value == status]
    features = [{
        "type": "Feature",
        "id": row.id,
        "geometry": {"type": "Point", "coordinates": [row.longitude, row.latitude]},
        "properties": {
            "candidate_id": row.id,
            "poi_id": row.poi_id,
            "business_name": row.business_name,
            "city": row.city,
            "source": row.source_name,
            "google_status": row.google_status.value,
            "comparison_bucket": row.comparison_bucket.value,
            "quality_tier": row.quality_tier.value,
            "qa_status": row.qa_status.value,
            "usable": row.usability_eligible,
            "release_approved": row.release_approved,
            "confidence": row.confidence_score,
            "is_demo": row.is_demo,
        },
    } for row in rows]
    return {"type": "FeatureCollection", "features": features}
