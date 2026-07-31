from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_roles
from ..database import get_db
from ..models import CandidateStatus, PoiCandidate, QaReview, QaStatus, StatusHistory, User, UserRole
from ..schemas import QaReviewOut, QaReviewRequest
from ..services.audit import write_audit
from ..services.eligibility import recalculate_candidate

router = APIRouter(prefix="/qa", tags=["Quality Assurance"])

REQUIRED_QA_CHECKS = {
    "identity_verified",
    "salon_category_verified",
    "address_verified",
    "coordinates_verified",
    "contact_verified",
    "activity_verified",
    "google_exclusion_verified",
    "evidence_complete",
    "duplicate_check_complete",
}


@router.get("/queue")
def qa_queue(
    project_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    rows = db.scalars(
        select(PoiCandidate)
        .where(PoiCandidate.project_id == project_id, PoiCandidate.qa_status.in_([QaStatus.NOT_SUBMITTED, QaStatus.PENDING, QaStatus.REWORK]))
        .order_by(PoiCandidate.updated_at.desc())
    ).all()
    return rows


@router.post("/{candidate_id}/submit")
def submit_to_qa(
    candidate_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(UserRole.PROGRAM_ADMIN, UserRole.PROJECT_MANAGER, UserRole.DISCOVERY_ANALYST, UserRole.GOOGLE_VALIDATOR, UserRole.LOCAL_RESEARCHER, UserRole.CALL_VALIDATOR))],
):
    candidate = db.get(PoiCandidate, candidate_id)
    if not candidate:
        raise HTTPException(404, "Candidate not found")
    if not candidate.usability_eligible:
        raise HTTPException(422, {"message": "Candidate is not eligible for QA", "failures": candidate.usability_failures})
    old_status = candidate.status.value
    candidate.qa_status = QaStatus.PENDING
    candidate.status = CandidateStatus.QA_PENDING
    candidate.release_approved = False
    db.add(StatusHistory(poi_candidate_id=candidate.id, from_status=old_status, to_status=CandidateStatus.QA_PENDING.value, reason="Submitted for independent QA", actor_email=user.email))
    write_audit(db, user, "QA_SUBMITTED", "poi_candidate", candidate.id, {})
    db.commit()
    return {"status": "QA_PENDING", "candidate_id": candidate.id}


@router.post("/{candidate_id}/review", response_model=QaReviewOut)
def review_candidate(
    candidate_id: int,
    payload: QaReviewRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(UserRole.PROGRAM_ADMIN, UserRole.QA_REVIEWER))],
):
    candidate = db.get(PoiCandidate, candidate_id)
    if not candidate:
        raise HTTPException(404, "Candidate not found")
    if candidate.qa_status != QaStatus.PENDING and payload.decision == QaStatus.PASSED:
        raise HTTPException(422, "Candidate must be submitted to QA before it can pass")
    if payload.independent_review and user.email in {candidate.google_reviewer, candidate.reviewer_identity}:
        raise HTTPException(422, "Independent QA must be completed by a different reviewer")
    missing_checks = sorted(REQUIRED_QA_CHECKS - set(payload.checklist))
    failed_checks = sorted(key for key in REQUIRED_QA_CHECKS if not bool(payload.checklist.get(key)))
    if payload.decision == QaStatus.PASSED:
        if missing_checks:
            raise HTTPException(422, "Missing QA checks: " + ", ".join(missing_checks))
        if failed_checks:
            raise HTTPException(422, "Failed QA checks: " + ", ".join(failed_checks))
        if payload.defects:
            raise HTTPException(422, "A passed QA review cannot contain unresolved defects")
        if not candidate.usability_eligible:
            raise HTTPException(422, {"message": "Candidate no longer meets D eligibility", "failures": candidate.usability_failures})

    review = QaReview(
        poi_candidate_id=candidate.id,
        reviewer_id=user.id,
        reviewer_email=user.email,
        decision=payload.decision,
        checklist=payload.checklist,
        defects=payload.defects,
        notes=payload.notes,
        independent_review=payload.independent_review,
    )
    db.add(review)
    old_status = candidate.status.value
    candidate.qa_status = payload.decision
    candidate.qa_reviewer = user.email
    candidate.qa_completed_at = datetime.now(timezone.utc)
    if payload.decision == QaStatus.REWORK:
        candidate.status = CandidateStatus.QA_REWORK
        candidate.release_approved = False
    elif payload.decision == QaStatus.REJECTED:
        candidate.status = CandidateStatus.REJECTED
        candidate.release_approved = False
        candidate.rejection_reason = payload.notes
    else:
        recalculate_candidate(candidate, candidate.project)
    db.add(StatusHistory(poi_candidate_id=candidate.id, from_status=old_status, to_status=candidate.status.value, reason=payload.notes, actor_email=user.email))
    write_audit(db, user, "QA_REVIEW_COMPLETED", "poi_candidate", candidate.id, {
        "decision": payload.decision.value,
        "defects": payload.defects,
        "release_approved": candidate.release_approved,
    })
    db.commit()
    db.refresh(review)
    return review


@router.get("/{candidate_id}/history", response_model=list[QaReviewOut])
def qa_history(candidate_id: int, db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]):
    if not db.get(PoiCandidate, candidate_id):
        raise HTTPException(404, "Candidate not found")
    return db.scalars(select(QaReview).where(QaReview.poi_candidate_id == candidate_id).order_by(QaReview.created_at.desc())).all()

@router.get("/scorecard/{project_id}")
def qa_scorecard(
    project_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    candidate_ids = list(db.scalars(select(PoiCandidate.id).where(PoiCandidate.project_id == project_id)).all())
    reviews = list(db.scalars(select(QaReview).where(QaReview.poi_candidate_id.in_(candidate_ids))).all()) if candidate_ids else []
    by_reviewer: dict[str, dict] = {}
    by_candidate: dict[int, list[QaReview]] = {}
    for review in reviews:
        row = by_reviewer.setdefault(review.reviewer_email, {"reviewer": review.reviewer_email, "reviews": 0, "passed": 0, "rework": 0, "rejected": 0, "defects": 0})
        row["reviews"] += 1
        row[review.decision.value.lower()] = row.get(review.decision.value.lower(), 0) + 1
        row["defects"] += len(review.defects or [])
        by_candidate.setdefault(review.poi_candidate_id, []).append(review)
    agreements = 0
    comparable = 0
    for candidate_reviews in by_candidate.values():
        if len(candidate_reviews) > 1:
            comparable += 1
            agreements += int(len({r.decision for r in candidate_reviews}) == 1)
    reviewer_rows = []
    for row in by_reviewer.values():
        row["pass_rate"] = round(row["passed"] / row["reviews"] * 100, 2) if row["reviews"] else 0
        reviewer_rows.append(row)
    return {
        "total_reviews": len(reviews),
        "reviewers": sorted(reviewer_rows, key=lambda x: (-x["reviews"], x["reviewer"])),
        "inter_reviewer_agreement": round(agreements / comparable * 100, 2) if comparable else None,
        "comparable_candidates": comparable,
    }
