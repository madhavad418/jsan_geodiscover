from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_roles
from ..config import get_settings
from ..database import get_db
from ..models import (
    CallJob,
    EvidenceItem,
    EvidenceType,
    GoogleCheck,
    PoiCandidate,
    QaReview,
    RawSourceRecord,
    ResearchTask,
    User,
    UserRole,
)
from ..schemas import EvidenceCreate, EvidenceOut
from ..services.audit import write_audit

router = APIRouter(prefix="/evidence", tags=["Evidence"])
settings = get_settings()


def _candidate_or_404(db: Session, candidate_id: int) -> PoiCandidate:
    candidate = db.get(PoiCandidate, candidate_id)
    if not candidate:
        raise HTTPException(404, "Candidate not found")
    return candidate


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).name)[:180] or "evidence.bin"


@router.get("/{candidate_id}", response_model=list[EvidenceOut])
def list_evidence(
    candidate_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    _candidate_or_404(db, candidate_id)
    return db.scalars(select(EvidenceItem).where(EvidenceItem.poi_candidate_id == candidate_id).order_by(EvidenceItem.created_at.desc())).all()


@router.post("/{candidate_id}", response_model=EvidenceOut, status_code=201)
def create_url_evidence(
    candidate_id: int,
    payload: EvidenceCreate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(UserRole.PROGRAM_ADMIN, UserRole.PROJECT_MANAGER, UserRole.DISCOVERY_ANALYST, UserRole.GOOGLE_VALIDATOR, UserRole.LOCAL_RESEARCHER, UserRole.CALL_VALIDATOR, UserRole.QA_REVIEWER))],
):
    candidate = _candidate_or_404(db, candidate_id)
    item = EvidenceItem(
        project_id=candidate.project_id,
        poi_candidate_id=candidate.id,
        evidence_type=payload.evidence_type,
        title=payload.title,
        source_url=payload.source_url,
        payload=payload.payload,
        notes=payload.notes,
        created_by=user.id,
    )
    db.add(item)
    db.flush()
    write_audit(db, user, "EVIDENCE_ADDED", "evidence_item", item.id, {"candidate_id": candidate_id, "type": payload.evidence_type.value})
    db.commit()
    db.refresh(item)
    return item


@router.post("/{candidate_id}/upload", response_model=EvidenceOut, status_code=201)
async def upload_evidence(
    candidate_id: int,
    evidence_type: Annotated[EvidenceType, Form()],
    title: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    notes: Annotated[str | None, Form()] = None,
    source_url: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.PROGRAM_ADMIN, UserRole.PROJECT_MANAGER, UserRole.DISCOVERY_ANALYST, UserRole.GOOGLE_VALIDATOR, UserRole.LOCAL_RESEARCHER, UserRole.CALL_VALIDATOR, UserRole.QA_REVIEWER)),
):
    candidate = _candidate_or_404(db, candidate_id)
    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(413, "Evidence files are limited to 20 MB in the POC")
    digest = hashlib.sha256(content).hexdigest()
    candidate_dir = settings.evidence_path / str(candidate.project_id) / candidate.poi_id
    candidate_dir.mkdir(parents=True, exist_ok=True)
    safe = _safe_name(file.filename or "evidence.bin")
    stored_name = f"{digest[:12]}_{safe}"
    path = candidate_dir / stored_name
    path.write_bytes(content)
    item = EvidenceItem(
        project_id=candidate.project_id,
        poi_candidate_id=candidate.id,
        evidence_type=evidence_type,
        title=title,
        source_url=source_url,
        file_name=safe,
        storage_path=str(path),
        sha256=digest,
        mime_type=file.content_type,
        notes=notes,
        created_by=user.id,
    )
    db.add(item)
    db.flush()
    write_audit(db, user, "EVIDENCE_FILE_UPLOADED", "evidence_item", item.id, {"candidate_id": candidate_id, "sha256": digest, "file_name": safe})
    db.commit()
    db.refresh(item)
    return item


@router.get("/items/{evidence_id}/download")
def download_evidence(
    evidence_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    item = db.get(EvidenceItem, evidence_id)
    if not item or not item.storage_path:
        raise HTTPException(404, "Evidence file not found")
    path = Path(item.storage_path)
    if not path.exists():
        raise HTTPException(404, "Evidence file is missing from storage")
    return Response(
        content=path.read_bytes(),
        media_type=item.mime_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{_safe_name(item.file_name or path.name)}"'},
    )


@router.get("/{candidate_id}/timeline")
def evidence_timeline(
    candidate_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    candidate = _candidate_or_404(db, candidate_id)
    timeline: list[dict] = [{
        "timestamp": candidate.created_at,
        "stage": "DISCOVERY",
        "title": f"Candidate discovered from {candidate.source_name}",
        "details": {"source_record_id": candidate.source_record_id, "source_url": candidate.primary_source_url},
    }]
    raw = db.get(RawSourceRecord, candidate.raw_source_record_id) if candidate.raw_source_record_id else None
    if raw:
        timeline.append({"timestamp": raw.created_at, "stage": "RAW_SOURCE", "title": "Immutable raw source record retained", "details": {"raw_record_id": raw.id, "sha256": raw.payload_sha256}})
    for item in db.scalars(select(EvidenceItem).where(EvidenceItem.poi_candidate_id == candidate_id)).all():
        timeline.append({"timestamp": item.created_at, "stage": item.evidence_type.value, "title": item.title, "details": {"evidence_id": item.id, "source_url": item.source_url, "file_name": item.file_name, "sha256": item.sha256}})
    for check in db.scalars(select(GoogleCheck).where(GoogleCheck.poi_candidate_id == candidate_id)).all():
        timeline.append({"timestamp": check.created_at, "stage": "GOOGLE_EXCLUSION", "title": check.decision.value, "details": {"reviewer": check.reviewer, "mandatory_checks_complete": check.mandatory_checks_complete, "check_count": len(check.checklist)}})
    for call in db.scalars(select(CallJob).where(CallJob.poi_candidate_id == candidate_id)).all():
        timeline.append({"timestamp": call.completed_at or call.created_at, "stage": "CALL_VALIDATION", "title": call.outcome.value if call.outcome else call.status.value, "details": {"provider": call.provider, "mode": call.provider_mode, "confidence": call.confidence}})
    for task in db.scalars(select(ResearchTask).where(ResearchTask.poi_candidate_id == candidate_id)).all():
        timeline.append({"timestamp": task.submitted_at or task.created_at, "stage": "LOCAL_RESEARCH", "title": task.status.value, "details": {"operating_status": task.operating_status, "notes": task.notes}})
    for qa in db.scalars(select(QaReview).where(QaReview.poi_candidate_id == candidate_id)).all():
        timeline.append({"timestamp": qa.created_at, "stage": "QA", "title": qa.decision.value, "details": {"reviewer": qa.reviewer_email, "defects": qa.defects, "independent": qa.independent_review}})
    return sorted(timeline, key=lambda x: x["timestamp"])


@router.get("/{candidate_id}/package.zip")
def evidence_package(
    candidate_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    candidate = _candidate_or_404(db, candidate_id)
    items = db.scalars(select(EvidenceItem).where(EvidenceItem.poi_candidate_id == candidate_id).order_by(EvidenceItem.created_at)).all()
    checks = db.scalars(select(GoogleCheck).where(GoogleCheck.poi_candidate_id == candidate_id).order_by(GoogleCheck.created_at)).all()
    raw = db.get(RawSourceRecord, candidate.raw_source_record_id) if candidate.raw_source_record_id else None
    manifest = {
        "poi_id": candidate.poi_id,
        "business_name": candidate.business_name,
        "google_status": candidate.google_status.value,
        "quality_tier": candidate.quality_tier.value,
        "qa_status": candidate.qa_status.value,
        "release_approved": candidate.release_approved,
        "raw_source_record": ({"id": raw.id, "source_name": raw.source_name, "source_record_id": raw.source_record_id, "payload_sha256": raw.payload_sha256, "raw_payload": raw.raw_payload, "created_at": raw.created_at.isoformat()} if raw else None),
        "evidence": [{
            "id": item.id,
            "type": item.evidence_type.value,
            "title": item.title,
            "source_url": item.source_url,
            "file_name": item.file_name,
            "sha256": item.sha256,
            "created_at": item.created_at.isoformat(),
        } for item in items],
        "google_checks": [{
            "decision": check.decision.value,
            "checklist": check.checklist,
            "candidate_place_ids": check.candidate_place_ids,
            "reviewer": check.reviewer,
            "reason": check.reason,
            "evidence_reference": check.evidence_reference,
            "created_at": check.created_at.isoformat(),
        } for check in checks],
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, indent=2, default=str))
        for item in items:
            if item.storage_path and Path(item.storage_path).exists():
                archive.write(item.storage_path, arcname=f"files/{item.id}_{_safe_name(item.file_name or 'evidence.bin')}")
    return Response(
        content=output.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="Evidence_{candidate.poi_id}.zip"'},
    )
