from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_roles
from ..database import get_db
from ..models import (
    CallJob,
    CandidateStatus,
    EvidenceItem,
    EvidenceType,
    PoiCandidate,
    ResearchTask,
    TaskStatus,
    User,
    UserRole,
)
from ..schemas import (
    CallJobComplete,
    CallJobCreate,
    CallJobOut,
    ResearchTaskCreate,
    ResearchTaskOut,
    ResearchTaskSubmit,
)
from ..services.audit import write_audit
from ..services.eligibility import recalculate_candidate

router = APIRouter(tags=["Call and Local Research"])


@router.post("/calls/{candidate_id}", response_model=CallJobOut, status_code=201)
def create_call_job(
    candidate_id: int,
    payload: CallJobCreate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(UserRole.PROGRAM_ADMIN, UserRole.PROJECT_MANAGER, UserRole.CALL_VALIDATOR))],
):
    candidate = db.get(PoiCandidate, candidate_id)
    if not candidate:
        raise HTTPException(404, "Candidate not found")
    if payload.provider_mode.upper() == "LIVE" and payload.provider.upper() == "MOCK":
        raise HTTPException(422, "A mock provider cannot be marked as live")
    job = CallJob(
        poi_candidate_id=candidate.id,
        provider=payload.provider,
        provider_mode=payload.provider_mode.upper(),
        language=payload.language,
        script_version=payload.script_version,
        assigned_to=user.id,
    )
    candidate.status = CandidateStatus.CALL_VALIDATION_PENDING
    db.add(job)
    db.flush()
    write_audit(db, user, "CALL_JOB_CREATED", "call_job", job.id, {"candidate_id": candidate.id, "provider": job.provider, "mode": job.provider_mode})
    db.commit()
    db.refresh(job)
    return job


@router.post("/calls/jobs/{job_id}/complete", response_model=CallJobOut)
def complete_call_job(
    job_id: int,
    payload: CallJobComplete,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(UserRole.PROGRAM_ADMIN, UserRole.CALL_VALIDATOR))],
):
    job = db.get(CallJob, job_id)
    if not job:
        raise HTTPException(404, "Call job not found")
    candidate = db.get(PoiCandidate, job.poi_candidate_id)
    job.status = TaskStatus.COMPLETED
    job.outcome = payload.outcome
    job.structured_answers = payload.structured_answers
    job.transcript_reference = payload.transcript_reference
    job.consent_status = payload.consent_status
    job.confidence = payload.confidence
    job.completed_at = datetime.now(timezone.utc)
    if payload.outcome.value in {"CONFIRMED_ACTIVE", "ACTIVE_INFORMATION_CORRECTED"}:
        candidate.activity_verified = True
        candidate.reviewer_identity = user.email
        corrected = payload.structured_answers
        candidate.full_address = corrected.get("address", candidate.full_address)
        candidate.phone = corrected.get("phone", candidate.phone)
        candidate.whatsapp = corrected.get("whatsapp", candidate.whatsapp)
    recalculate_candidate(candidate, candidate.project)
    db.add(EvidenceItem(
        project_id=candidate.project_id,
        poi_candidate_id=candidate.id,
        evidence_type=EvidenceType.CALL,
        title=f"Call validation: {payload.outcome.value}",
        source_url=payload.transcript_reference,
        payload={"provider": job.provider, "mode": job.provider_mode, "answers": payload.structured_answers, "confidence": payload.confidence, "consent_status": payload.consent_status},
        notes="Mock mode" if job.provider_mode == "MOCK" else "Live provider result",
        created_by=user.id,
    ))
    write_audit(db, user, "CALL_JOB_COMPLETED", "call_job", job.id, {"outcome": payload.outcome.value, "mode": job.provider_mode})
    db.commit()
    db.refresh(job)
    return job


@router.get("/calls", response_model=list[CallJobOut])
def list_calls(project_id: int, db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]):
    candidate_ids = select(PoiCandidate.id).where(PoiCandidate.project_id == project_id)
    return db.scalars(select(CallJob).where(CallJob.poi_candidate_id.in_(candidate_ids)).order_by(CallJob.created_at.desc())).all()


@router.post("/research/{candidate_id}", response_model=ResearchTaskOut, status_code=201)
def create_research_task(
    candidate_id: int,
    payload: ResearchTaskCreate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(UserRole.PROGRAM_ADMIN, UserRole.PROJECT_MANAGER, UserRole.LOCAL_RESEARCHER))],
):
    candidate = db.get(PoiCandidate, candidate_id)
    if not candidate:
        raise HTTPException(404, "Candidate not found")
    task = ResearchTask(poi_candidate_id=candidate.id, assigned_to=payload.assigned_to or user.id)
    candidate.status = CandidateStatus.LOCAL_RESEARCH_PENDING
    db.add(task)
    db.flush()
    write_audit(db, user, "RESEARCH_TASK_CREATED", "research_task", task.id, {"candidate_id": candidate.id})
    db.commit()
    db.refresh(task)
    return task


@router.post("/research/tasks/{task_id}/submit", response_model=ResearchTaskOut)
def submit_research_task(
    task_id: int,
    payload: ResearchTaskSubmit,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(UserRole.PROGRAM_ADMIN, UserRole.LOCAL_RESEARCHER))],
):
    task = db.get(ResearchTask, task_id)
    if not task:
        raise HTTPException(404, "Research task not found")
    candidate = db.get(PoiCandidate, task.poi_candidate_id)
    task.corrected_address = payload.corrected_address
    task.corrected_latitude = payload.corrected_latitude
    task.corrected_longitude = payload.corrected_longitude
    task.operating_status = payload.operating_status
    task.notes = payload.notes
    task.status = TaskStatus.SUBMITTED
    task.submitted_at = datetime.now(timezone.utc)
    if payload.corrected_address:
        candidate.full_address = payload.corrected_address
    if payload.corrected_latitude is not None and payload.corrected_longitude is not None:
        candidate.latitude = payload.corrected_latitude
        candidate.longitude = payload.corrected_longitude
        candidate.coordinate_precision = "FIELD_VERIFIED"
    if payload.operating_status.upper() == "CONFIRMED_ACTIVE":
        candidate.activity_verified = True
    candidate.reviewer_identity = user.email
    recalculate_candidate(candidate, candidate.project)
    db.add(EvidenceItem(
        project_id=candidate.project_id,
        poi_candidate_id=candidate.id,
        evidence_type=EvidenceType.LOCAL_RESEARCH,
        title=f"Local research: {payload.operating_status}",
        payload=payload.model_dump(),
        notes=payload.notes,
        created_by=user.id,
    ))
    write_audit(db, user, "RESEARCH_TASK_SUBMITTED", "research_task", task.id, {"operating_status": payload.operating_status})
    db.commit()
    db.refresh(task)
    return task


@router.get("/research", response_model=list[ResearchTaskOut])
def list_research(project_id: int, db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]):
    candidate_ids = select(PoiCandidate.id).where(PoiCandidate.project_id == project_id)
    return db.scalars(select(ResearchTask).where(ResearchTask.poi_candidate_id.in_(candidate_ids)).order_by(ResearchTask.created_at.desc())).all()
