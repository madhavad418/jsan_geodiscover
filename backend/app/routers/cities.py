from __future__ import annotations

import io
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import City, CityMatch, Project, ScrapeJob, User, ValidationRecord
from ..services.audit import write_audit
from ..services.benchmark_import import find_workbooks, import_benchmark
from ..services.validation_layer import append_rows, get_or_create_city, read_rows

router = APIRouter(prefix="/cities", tags=["Cities"])


def _require_project(project_id: int, db: Session) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


def _city_payload(db: Session, city: City) -> dict[str, Any]:
    rows = db.execute(
        select(ValidationRecord.validation_status, func.count())
        .where(ValidationRecord.city_id == city.id)
        .group_by(ValidationRecord.validation_status)
    ).all()
    counts = {"PENDING": 0, "IN_PROGRESS": 0, "COMPLETED": 0}
    for status, total in rows:
        counts[status] = counts.get(status, 0) + total
    total_records = sum(counts.values())
    scraped = db.scalar(
        select(func.count(ValidationRecord.id)).where(
            ValidationRecord.city_id == city.id, ValidationRecord.scrape_state == "DONE"
        )
    ) or 0
    last_job = db.scalar(
        select(ScrapeJob).where(ScrapeJob.city_id == city.id).order_by(ScrapeJob.id.desc()).limit(1)
    )
    return {
        "id": city.id,
        "name": city.name,
        "slug": city.slug,
        "region": city.region,
        "country": city.country,
        "source_files": city.source_files or [],
        "notes": city.notes,
        "total_records": total_records,
        "summary": counts,
        "scraped_records": scraped,
        "created_at": city.created_at.isoformat() if city.created_at else None,
        "last_job": (
            {
                "id": last_job.id,
                "status": last_job.status.value,
                "processed_records": last_job.processed_records,
                "total_records": last_job.total_records,
                "fields_filled": last_job.fields_filled,
                "completed_at": last_job.completed_at.isoformat() if last_job.completed_at else None,
            }
            if last_job
            else None
        ),
    }


@router.get("/{project_id}")
def list_cities(
    project_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    _require_project(project_id, db)
    cities = list(db.scalars(select(City).where(City.project_id == project_id).order_by(City.name)))
    payload = [_city_payload(db, city) for city in cities]
    return {
        "cities": payload,
        "total_records": sum(c["total_records"] for c in payload),
        "totals": {
            key: sum(c["summary"].get(key, 0) for c in payload)
            for key in ("PENDING", "IN_PROGRESS", "COMPLETED")
        },
    }


@router.post("/{project_id}/upload")
async def upload_city_workbook(
    project_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    city: Annotated[str, Form()],
    region: Annotated[str | None, Form()] = None,
    country: Annotated[str, Form()] = "Indonesia",
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Append a city's workbook into the validation tables.

    Re-uploading a city is safe: businesses already loaded are refreshed rather
    than duplicated, and saved validation answers are preserved.
    """
    _require_project(project_id, db)
    if not city.strip():
        raise HTTPException(400, "Enter the city this workbook covers")
    if not (file.filename or "").lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(400, "Upload an .xlsx workbook in the same format as the validation layer")

    payload = await file.read()
    try:
        columns, rows = read_rows(io.BytesIO(payload))
    except Exception as exc:  # openpyxl raises a variety of parse errors
        raise HTTPException(400, f"Could not read the workbook: {exc}")

    record = get_or_create_city(db, project_id, city, region, country, user.email)
    result = append_rows(db, project_id, record, rows, file.filename or "upload.xlsx", columns)
    if not result["added"] and not result["refreshed"]:
        db.rollback()
        raise HTTPException(400, "No usable rows found in the workbook")

    write_audit(
        db, user, "CITY_WORKBOOK_APPENDED", "City", record.id,
        {"city": record.name, "file": file.filename, **result},
    )
    db.commit()
    return {"city": _city_payload(db, record), **result, "file_name": file.filename}


@router.post("/{project_id}/import-benchmarks")
def import_benchmarks(
    project_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    """Load every Grab-vs-Google benchmark workbook in backend/other_cities."""
    _require_project(project_id, db)
    if not find_workbooks():
        raise HTTPException(404, "No .xlsx workbook found in backend/other_cities")
    results = []
    for path in find_workbooks():
        try:
            results.append(import_benchmark(db, project_id, path, path.name, created_by=user.email))
        except ValueError as exc:
            results.append({"workbook": path.name, "error": str(exc)})
    write_audit(db, user, "CITY_BENCHMARKS_IMPORTED", "Project", project_id, {"results": results})
    db.commit()
    return {"imported": results}


@router.post("/{project_id}/upload-benchmark")
async def upload_benchmark(
    project_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    city: Annotated[str | None, Form()] = None,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Upload one benchmark export. The city name is read from the workbook."""
    _require_project(project_id, db)
    if not (file.filename or "").lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(400, "Upload an .xlsx benchmark export")
    payload = await file.read()
    try:
        result = import_benchmark(
            db, project_id, io.BytesIO(payload), file.filename or "benchmark.xlsx", city, user.email
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    write_audit(db, user, "CITY_BENCHMARK_UPLOADED", "City", result["city_id"], result)
    db.commit()
    return result


@router.delete("/{project_id}/{city_id}")
def delete_city(
    project_id: int,
    city_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    city = db.get(City, city_id)
    if not city or city.project_id != project_id:
        raise HTTPException(404, "City not found")
    running = db.scalar(
        select(func.count(ScrapeJob.id)).where(ScrapeJob.city_id == city_id, ScrapeJob.status == "RUNNING")
    )
    if running:
        raise HTTPException(409, "A scrape is running for this city - cancel it first")

    removed = db.scalar(select(func.count(ValidationRecord.id)).where(ValidationRecord.city_id == city_id)) or 0
    for match in db.scalars(select(CityMatch).where(CityMatch.city_id == city_id)):
        db.delete(match)
    for job in db.scalars(select(ScrapeJob).where(ScrapeJob.city_id == city_id)):
        db.delete(job)
    for record in db.scalars(select(ValidationRecord).where(ValidationRecord.city_id == city_id)):
        db.delete(record)
    write_audit(db, user, "CITY_DELETED", "City", city_id, {"city": city.name, "records": removed})
    db.delete(city)
    db.commit()
    return {"status": "deleted", "records_removed": removed}
