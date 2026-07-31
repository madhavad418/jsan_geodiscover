from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import SessionLocal, get_db
from ..models import City, Project, ScrapeJob, ScrapeJobStatus, User, ValidationRecord
from ..services.audit import write_audit
from ..services.scraping import ScrapeContext, probe_sources, scrape_business
from ..services.validation_layer import EDITABLE_KEYS, SOURCE_FIELDS, compute_status

router = APIRouter(prefix="/scraping", tags=["Bulk Scraping"])

# One worker thread per job id, so a job cannot be started twice.
_running: dict[int, threading.Thread] = {}


def _require_project(project_id: int, db: Session) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


def _job_payload(job: ScrapeJob, city: City | None = None) -> dict[str, Any]:
    return {
        "id": job.id,
        "project_id": job.project_id,
        "city_id": job.city_id,
        "city": city.name if city else None,
        "file_name": job.file_name,
        "status": job.status.value,
        "total_records": job.total_records,
        "processed_records": job.processed_records,
        "fields_filled": job.fields_filled,
        "records_with_findings": job.records_with_findings,
        "current_business": job.current_business,
        "source_report": job.source_report or {},
        "error": job.error,
        "created_by_email": job.created_by_email,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "percent": round(job.processed_records / job.total_records * 100) if job.total_records else 0,
    }


@router.get("/sources")
def sources(user: Annotated[User, Depends(get_current_user)]) -> dict[str, Any]:
    """What each provider can actually do right now, before any job is started."""
    return {"sources": probe_sources()}


@router.post("/{project_id}/jobs")
def create_job(
    project_id: int,
    city_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    only_unscraped: bool = False,
) -> dict[str, Any]:
    """Queue a scrape over a city's records. Workbooks are uploaded under Cities."""
    _require_project(project_id, db)
    city = db.get(City, city_id)
    if not city or city.project_id != project_id:
        raise HTTPException(404, "City not found")

    query = select(func.count(ValidationRecord.id)).where(ValidationRecord.city_id == city_id)
    if only_unscraped:
        query = query.where(ValidationRecord.scrape_state.is_(None))
    total = db.scalar(query) or 0
    if not total:
        raise HTTPException(400, f"{city.name} has no records to process")

    job = ScrapeJob(
        project_id=project_id,
        city_id=city_id,
        file_name=", ".join(city.source_files or []) or city.name,
        status=ScrapeJobStatus.UPLOADED,
        total_records=total,
        created_by_email=user.email,
    )
    db.add(job)
    write_audit(db, user, "SCRAPE_JOB_CREATED", "ScrapeJob", None, {"city": city.name, "records": total})
    db.commit()
    db.refresh(job)
    return _job_payload(job, city)


def _run_job(job_id: int) -> None:
    """Worker body. Owns its own session because it runs off the request thread."""
    db = SessionLocal()
    ctx: ScrapeContext | None = None
    try:
        job = db.get(ScrapeJob, job_id)
        if job is None:
            return
        job.status = ScrapeJobStatus.RUNNING
        job.started_at = datetime.now(timezone.utc)
        job.error = None
        db.commit()

        ctx = ScrapeContext()
        job.source_report = probe_sources()
        db.commit()

        records = list(
            db.scalars(
                select(ValidationRecord)
                .where(ValidationRecord.city_id == job.city_id)
                .order_by(ValidationRecord.source_row)
            )
        )
        job.total_records = len(records)
        db.commit()
        filled = with_findings = 0
        for index, record in enumerate(records, start=1):
            db.refresh(job)
            if job.status == ScrapeJobStatus.CANCELLED:
                break
            job.current_business = record.business_name
            db.commit()

            record.scrape_state = "PROCESSING"
            db.commit()
            try:
                values, findings = scrape_business(ctx, record.business_name or "", record.address or "")
            except Exception as exc:  # never let one bad row kill the run
                record.scrape_state = "FAILED"
                record.scrape_findings = {"error": {"label": "Scrape", "status": "ERROR", "note": str(exc)[:400]}}
                db.commit()
                job.processed_records = index
                db.commit()
                continue

            # Only write columns the providers actually proved.
            written = 0
            for key, value in values.items():
                if key in EDITABLE_KEYS and value not in (None, ""):
                    setattr(record, key, value)
                    written += 1
            record.scrape_findings = findings
            record.scrape_state = "DONE"
            record.last_job_id = job_id
            record.validation_status = compute_status(record)
            filled += written
            if written:
                with_findings += 1

            job.processed_records = index
            job.fields_filled = filled
            job.records_with_findings = with_findings
            db.commit()

        db.refresh(job)
        if job.status != ScrapeJobStatus.CANCELLED:
            job.status = ScrapeJobStatus.COMPLETED
        job.current_business = None
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:
        db.rollback()
        job = db.get(ScrapeJob, job_id)
        if job:
            job.status = ScrapeJobStatus.FAILED
            job.error = str(exc)[:900]
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        if ctx:
            ctx.close()
        db.close()
        _running.pop(job_id, None)


@router.post("/jobs/{job_id}/start")
def start_job(
    job_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    job = db.get(ScrapeJob, job_id)
    if not job:
        raise HTTPException(404, "Scrape job not found")
    if job_id in _running or job.status == ScrapeJobStatus.RUNNING:
        raise HTTPException(409, "This job is already processing")

    job.status = ScrapeJobStatus.UPLOADED
    job.processed_records = 0
    job.fields_filled = 0
    job.records_with_findings = 0
    job.completed_at = None
    write_audit(db, user, "SCRAPE_JOB_STARTED", "ScrapeJob", job.id, {"file": job.file_name, "rows": job.total_records})
    db.commit()

    thread = threading.Thread(target=_run_job, args=(job_id,), daemon=True, name=f"scrape-job-{job_id}")
    _running[job_id] = thread
    thread.start()
    db.refresh(job)
    return _job_payload(job)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(
    job_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    job = db.get(ScrapeJob, job_id)
    if not job:
        raise HTTPException(404, "Scrape job not found")
    if job.status == ScrapeJobStatus.RUNNING:
        job.status = ScrapeJobStatus.CANCELLED
        db.commit()
    db.refresh(job)
    return _job_payload(job)


@router.get("/{project_id}/jobs")
def list_jobs(
    project_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    _require_project(project_id, db)
    jobs = list(db.scalars(select(ScrapeJob).where(ScrapeJob.project_id == project_id).order_by(ScrapeJob.id.desc())))
    cities = {c.id: c for c in db.scalars(select(City).where(City.project_id == project_id))}
    return {"jobs": [_job_payload(job, cities.get(job.city_id)) for job in jobs]}


@router.get("/jobs/{job_id}")
def get_job(
    job_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    job = db.get(ScrapeJob, job_id)
    if not job:
        raise HTTPException(404, "Scrape job not found")
    return _job_payload(job, db.get(City, job.city_id) if job.city_id else None)


@router.get("/jobs/{job_id}/records")
def job_records(
    job_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    """Same shape as the validation layer, so the grid and editor are shared."""
    job = db.get(ScrapeJob, job_id)
    if not job:
        raise HTTPException(404, "Scrape job not found")
    city = db.get(City, job.city_id) if job.city_id else None
    records = list(
        db.scalars(
            select(ValidationRecord)
            .where(ValidationRecord.city_id == job.city_id)
            .order_by(ValidationRecord.source_row)
        )
    )
    counts = {"PENDING": 0, "IN_PROGRESS": 0, "COMPLETED": 0}
    for record in records:
        counts[record.validation_status] = counts.get(record.validation_status, 0) + 1

    payload = []
    for record in records:
        item: dict[str, Any] = {
            "id": record.id,
            "source_row": record.source_row,
            "source_file": record.source_file,
            "validation_status": record.validation_status,
            "updated_by_email": record.updated_by_email,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
            "scrape_state": record.scrape_state,
            "scrape_findings": record.scrape_findings or {},
            "city": city.name if city else None,
        }
        for field in SOURCE_FIELDS:
            item[field["key"]] = getattr(record, field["key"])
        for key in EDITABLE_KEYS:
            item[key] = getattr(record, key)
        payload.append(item)

    return {
        "job": _job_payload(job, city),
        "project_id": job.project_id,
        "city_id": job.city_id,
        "city": city.name if city else None,
        "total": len(records),
        "returned": len(records),
        "summary": counts,
        "providers": sorted({r.provider for r in records if r.provider}),
        "source_file": job.file_name,
        "records": payload,
    }


@router.delete("/jobs/{job_id}")
def delete_job(
    job_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, str]:
    job = db.get(ScrapeJob, job_id)
    if not job:
        raise HTTPException(404, "Scrape job not found")
    if job.status == ScrapeJobStatus.RUNNING:
        raise HTTPException(409, "Cancel the job before deleting it")
    # The records belong to the city, not the job - only the run history goes.
    for record in db.scalars(select(ValidationRecord).where(ValidationRecord.last_job_id == job_id)):
        record.last_job_id = None
    write_audit(db, user, "SCRAPE_JOB_DELETED", "ScrapeJob", job_id, {"file": job.file_name, "city_id": job.city_id})
    db.delete(job)
    db.commit()
    return {"status": "deleted"}
