from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_roles
from ..database import get_db
from ..models import (
    ComparisonBucket,
    DuplicateGroup,
    DuplicateMembership,
    EntityMatch,
    PoiCandidate,
    PoiEntity,
    User,
    UserRole,
)
from ..schemas import ComparisonRunRequest, ComparisonSummary, EntityMatchOut, MatchDecisionRequest
from ..services.audit import write_audit
from ..services.entity_resolution import score_pair

router = APIRouter(prefix="/entity-resolution", tags=["Entity Resolution"])


def _rows_for_source(db: Session, project_id: int, name: str, ids: list[int] | None) -> list[PoiCandidate]:
    query = select(PoiCandidate).where(PoiCandidate.project_id == project_id)
    if ids:
        query = query.where(PoiCandidate.id.in_(ids))
    else:
        query = query.where(PoiCandidate.source_name == name)
    return list(db.scalars(query).all())


@router.post("/compare", response_model=ComparisonSummary)
def compare_sources(
    payload: ComparisonRunRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(UserRole.PROGRAM_ADMIN, UserRole.PROJECT_MANAGER, UserRole.DISCOVERY_ANALYST, UserRole.QA_REVIEWER))],
):
    source_rows = _rows_for_source(db, payload.project_id, payload.source_name, payload.source_candidate_ids)
    baseline_rows = _rows_for_source(db, payload.project_id, payload.baseline_name, payload.baseline_candidate_ids)
    if not source_rows:
        raise HTTPException(422, f"No records found for source {payload.source_name}")
    if not baseline_rows:
        raise HTTPException(422, f"No records found for baseline {payload.baseline_name}")

    matched_baseline: set[int] = set()
    common = possible = source_only = matches_created = 0
    for candidate in source_rows:
        scored = [(baseline, score_pair(candidate, baseline)) for baseline in baseline_rows]
        best_baseline, best = max(scored, key=lambda item: item[1]["total_score"])
        existing = db.scalar(select(EntityMatch).where(
            EntityMatch.candidate_id == candidate.id,
            EntityMatch.comparison_candidate_id == best_baseline.id,
        ))
        match = existing or EntityMatch(
            project_id=payload.project_id,
            candidate_id=candidate.id,
            comparison_candidate_id=best_baseline.id,
        )
        for field in ["name_score", "coordinate_score", "phone_score", "address_score", "web_social_score", "total_score", "distance_m", "explanation"]:
            setattr(match, field, best[field])
        if best["total_score"] >= payload.common_threshold:
            match.decision = "PROBABLE_SAME_POI"
            candidate.comparison_bucket = ComparisonBucket.COMMON
            best_baseline.comparison_bucket = ComparisonBucket.COMMON
            matched_baseline.add(best_baseline.id)
            common += 1
        elif best["total_score"] >= payload.possible_threshold:
            match.decision = "MANUAL_REVIEW"
            candidate.comparison_bucket = ComparisonBucket.POSSIBLE_MATCH
            best_baseline.comparison_bucket = ComparisonBucket.POSSIBLE_MATCH
            matched_baseline.add(best_baseline.id)
            possible += 1
        else:
            match.decision = "SEPARATE_OR_UNRESOLVED"
            candidate.comparison_bucket = ComparisonBucket.SOURCE_ONLY
            source_only += 1
        if not existing:
            db.add(match)
            matches_created += 1

    baseline_only = 0
    for baseline in baseline_rows:
        if baseline.id not in matched_baseline and baseline.comparison_bucket not in {ComparisonBucket.COMMON, ComparisonBucket.POSSIBLE_MATCH}:
            baseline.comparison_bucket = ComparisonBucket.BASELINE_ONLY
            baseline_only += 1

    write_audit(db, user, "SOURCE_COMPARISON_RUN", "project", payload.project_id, {
        "source": payload.source_name,
        "baseline": payload.baseline_name,
        "source_count": len(source_rows),
        "baseline_count": len(baseline_rows),
        "common": common,
        "possible": possible,
        "source_only": source_only,
        "baseline_only": baseline_only,
    })
    db.commit()
    return ComparisonSummary(
        common=common,
        source_only=source_only,
        baseline_only=baseline_only,
        possible_match=possible,
        matches_created=matches_created,
        source_name=payload.source_name,
        baseline_name=payload.baseline_name,
    )


@router.get("/matches", response_model=list[EntityMatchOut])
def list_matches(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    project_id: int,
    decision: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
):
    query = select(EntityMatch).where(EntityMatch.project_id == project_id)
    if decision:
        query = query.where(EntityMatch.decision == decision)
    return db.scalars(query.order_by(EntityMatch.total_score.desc()).limit(limit)).all()


@router.get("/matches/{match_id}")
def get_match(match_id: int, db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]):
    match = db.get(EntityMatch, match_id)
    if not match:
        raise HTTPException(404, "Match not found")
    left = db.get(PoiCandidate, match.candidate_id)
    right = db.get(PoiCandidate, match.comparison_candidate_id)
    return {"match": EntityMatchOut.model_validate(match), "candidate": left, "comparison_candidate": right}


@router.post("/matches/{match_id}/decision")
def decide_match(
    match_id: int,
    payload: MatchDecisionRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(UserRole.PROGRAM_ADMIN, UserRole.PROJECT_MANAGER, UserRole.QA_REVIEWER))],
):
    match = db.get(EntityMatch, match_id)
    if not match:
        raise HTTPException(404, "Match not found")
    left = db.get(PoiCandidate, match.candidate_id)
    right = db.get(PoiCandidate, match.comparison_candidate_id)
    if not left or not right:
        raise HTTPException(404, "Match candidates not found")

    match.decision = payload.decision
    match.reviewed_by = user.email
    match.explanation = {**(match.explanation or {}), "manual_reason": payload.reason}
    group_id = None
    entity_id = None
    if payload.decision == "SAME_POI":
        canonical = db.get(PoiCandidate, payload.canonical_candidate_id) if payload.canonical_candidate_id else left
        if not canonical or canonical.id not in {left.id, right.id}:
            raise HTTPException(422, "Canonical candidate must belong to the match")
        entity = db.get(PoiEntity, canonical.entity_id) if canonical.entity_id else None
        if not entity:
            entity = PoiEntity(
                project_id=left.project_id,
                entity_key=f"ENT-{uuid.uuid4().hex[:12].upper()}",
                canonical_name=canonical.business_name,
                canonical_address=canonical.full_address,
                latitude=canonical.latitude,
                longitude=canonical.longitude,
            )
            db.add(entity)
            db.flush()
        left.entity_id = right.entity_id = entity.id
        entity_id = entity.id
        group = DuplicateGroup(
            project_id=left.project_id,
            name=f"{canonical.business_name} duplicate review",
            status="RESOLVED_MERGED",
            canonical_candidate_id=canonical.id,
        )
        db.add(group)
        db.flush()
        db.add_all([
            DuplicateMembership(group_id=group.id, candidate_id=left.id, is_canonical=left.id == canonical.id),
            DuplicateMembership(group_id=group.id, candidate_id=right.id, is_canonical=right.id == canonical.id),
        ])
        group_id = group.id
    elif payload.decision == "SEPARATE":
        left.entity_id = None
        right.entity_id = None

    write_audit(db, user, "ENTITY_MATCH_DECIDED", "entity_match", match.id, {
        "decision": payload.decision,
        "reason": payload.reason,
        "entity_id": entity_id,
        "duplicate_group_id": group_id,
    })
    db.commit()
    return {"status": "ok", "decision": payload.decision, "entity_id": entity_id, "duplicate_group_id": group_id}


@router.post("/candidates/{candidate_id}/unmerge")
def unmerge_candidate(
    candidate_id: int,
    reason: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(UserRole.PROGRAM_ADMIN, UserRole.PROJECT_MANAGER, UserRole.QA_REVIEWER))],
):
    candidate = db.get(PoiCandidate, candidate_id)
    if not candidate:
        raise HTTPException(404, "Candidate not found")
    previous_entity = candidate.entity_id
    candidate.entity_id = None
    memberships = db.scalars(select(DuplicateMembership).where(DuplicateMembership.candidate_id == candidate_id)).all()
    for membership in memberships:
        db.delete(membership)
    matches = db.scalars(select(EntityMatch).where(or_(EntityMatch.candidate_id == candidate_id, EntityMatch.comparison_candidate_id == candidate_id))).all()
    for match in matches:
        if match.decision == "SAME_POI":
            match.decision = "UNRESOLVED"
    write_audit(db, user, "ENTITY_UNMERGED", "poi_candidate", candidate_id, {"previous_entity_id": previous_entity, "reason": reason})
    db.commit()
    return {"status": "unmerged", "candidate_id": candidate_id, "previous_entity_id": previous_entity}
