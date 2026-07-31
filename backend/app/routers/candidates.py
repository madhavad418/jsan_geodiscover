from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_roles
from ..database import get_db
from ..models import (
    ComparisonBucket,
    GoogleCheck,
    GoogleStatus,
    PoiCandidate,
    Project,
    QaStatus,
    StatusHistory,
    User,
    UserRole,
)
from ..schemas import CandidateOut, CandidateUpdate, GoogleReviewRequest
from ..services.audit import write_audit
from ..services.eligibility import recalculate_candidate
from ..services.google_rules import validate_absence_checklist
from ..services.normalization import normalize_text

router = APIRouter(prefix="/candidates", tags=["POI Candidates"])


@router.get("")
def list_candidates(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    project_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=2000),
    search: str | None = None,
    city: str | None = None,
    source: str | None = None,
    google_status: GoogleStatus | None = None,
    qa_status: QaStatus | None = None,
    comparison_bucket: ComparisonBucket | None = None,
    usable_only: bool = False,
    release_ready_only: bool = False,
):
    filters = [PoiCandidate.project_id == project_id]
    if search:
        filters.append(func.lower(PoiCandidate.business_name).contains(search.lower()))
    if city:
        filters.append(PoiCandidate.city == city)
    if source:
        filters.append(PoiCandidate.source_name == source)
    if google_status:
        filters.append(PoiCandidate.google_status == google_status)
    if qa_status:
        filters.append(PoiCandidate.qa_status == qa_status)
    if comparison_bucket:
        filters.append(PoiCandidate.comparison_bucket == comparison_bucket)
    if usable_only:
        filters.append(PoiCandidate.usability_eligible.is_(True))
    if release_ready_only:
        filters.append(PoiCandidate.release_approved.is_(True))
    total = db.scalar(select(func.count()).select_from(PoiCandidate).where(*filters)) or 0
    rows = db.scalars(
        select(PoiCandidate).where(*filters).order_by(PoiCandidate.updated_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {"items": [CandidateOut.model_validate(r) for r in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/{candidate_id}", response_model=CandidateOut)
def get_candidate(candidate_id: int, db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]):
    candidate = db.get(PoiCandidate, candidate_id)
    if not candidate:
        raise HTTPException(404, "Candidate not found")
    return candidate


@router.patch("/{candidate_id}", response_model=CandidateOut)
def update_candidate(
    candidate_id: int,
    payload: CandidateUpdate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(UserRole.PROGRAM_ADMIN, UserRole.PROJECT_MANAGER, UserRole.DISCOVERY_ANALYST, UserRole.GOOGLE_VALIDATOR, UserRole.LOCAL_RESEARCHER, UserRole.QA_REVIEWER))],
):
    candidate = db.get(PoiCandidate, candidate_id)
    if not candidate:
        raise HTTPException(404, "Candidate not found")
    project = db.get(Project, candidate.project_id)
    changes = payload.model_dump(exclude_unset=True)
    old_status = candidate.status.value
    for key, value in changes.items():
        setattr(candidate, key, value)
    if "business_name" in changes:
        candidate.normalized_name = normalize_text(candidate.business_name)
    candidate.updated_by = user.id
    recalculate_candidate(candidate, project)
    if old_status != candidate.status.value:
        db.add(StatusHistory(poi_candidate_id=candidate.id, from_status=old_status, to_status=candidate.status.value, reason="Candidate fields updated", actor_email=user.email))
    write_audit(db, user, "CANDIDATE_UPDATED", "poi_candidate", candidate.id, {"fields": list(changes)})
    db.commit()
    db.refresh(candidate)
    return candidate


@router.post("/{candidate_id}/google-review", response_model=CandidateOut)
def google_review(
    candidate_id: int,
    payload: GoogleReviewRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(UserRole.PROGRAM_ADMIN, UserRole.PROJECT_MANAGER, UserRole.GOOGLE_VALIDATOR, UserRole.QA_REVIEWER))],
):
    candidate = db.get(PoiCandidate, candidate_id)
    if not candidate:
        raise HTTPException(404, "Candidate not found")
    checklist = [item.model_dump() for item in payload.checklist]
    mandatory_complete = False
    if payload.decision == GoogleStatus.GOOGLE_ABSENT_VERIFIED:
        if not payload.completed:
            raise HTTPException(422, "Verified Google absence requires a completed review")
        mandatory_complete, failures = validate_absence_checklist(checklist)
        if not mandatory_complete:
            raise HTTPException(422, "; ".join(failures))
        if not payload.evidence_reference:
            raise HTTPException(422, "Verified Google absence requires an evidence reference")
    elif payload.completed and checklist:
        mandatory_complete, _ = validate_absence_checklist(checklist)

    check = GoogleCheck(
        poi_candidate_id=candidate.id,
        decision=payload.decision,
        checklist=checklist,
        queries=payload.queries or [{"check_type": item["check_type"], "query": item["query"], "result": item["result"]} for item in checklist],
        candidate_place_ids=payload.candidate_place_ids,
        nearby_search_radius_m=payload.nearby_search_radius_m,
        reviewer=user.email,
        reason=payload.reason,
        evidence_reference=payload.evidence_reference,
        mandatory_checks_complete=mandatory_complete,
        completed=payload.completed,
    )
    db.add(check)
    old_status = candidate.status.value
    candidate.google_status = payload.decision
    candidate.google_review_completed = payload.completed
    candidate.google_reviewer = user.email
    candidate.reviewer_identity = user.email
    if payload.decision == GoogleStatus.GOOGLE_PRESENT_CONFIRMED:
        candidate.comparison_bucket = ComparisonBucket.COMMON
    elif payload.decision == GoogleStatus.GOOGLE_POSSIBLE_MATCH:
        candidate.comparison_bucket = ComparisonBucket.POSSIBLE_MATCH
    if payload.evidence_reference:
        candidate.evidence_reference = payload.evidence_reference
    recalculate_candidate(candidate, candidate.project)
    db.add(StatusHistory(poi_candidate_id=candidate.id, from_status=old_status, to_status=candidate.status.value, reason=payload.reason, actor_email=user.email))
    write_audit(db, user, "GOOGLE_REVIEW_COMPLETED", "poi_candidate", candidate.id, {
        "decision": payload.decision.value,
        "completed": payload.completed,
        "mandatory_checks_complete": mandatory_complete,
        "check_count": len(checklist),
        "reason": payload.reason,
    })
    db.commit()
    db.refresh(candidate)
    return candidate


@router.get("/{candidate_id}/google-history")
def google_history(candidate_id: int, db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]):
    if not db.get(PoiCandidate, candidate_id):
        raise HTTPException(404, "Candidate not found")
    checks = db.scalars(select(GoogleCheck).where(GoogleCheck.poi_candidate_id == candidate_id).order_by(GoogleCheck.created_at.desc())).all()
    return [{
        "id": c.id,
        "decision": c.decision.value,
        "checklist": c.checklist,
        "candidate_place_ids": c.candidate_place_ids,
        "reviewer": c.reviewer,
        "reason": c.reason,
        "evidence_reference": c.evidence_reference,
        "mandatory_checks_complete": c.mandatory_checks_complete,
        "completed": c.completed,
        "created_at": c.created_at,
    } for c in checks]
