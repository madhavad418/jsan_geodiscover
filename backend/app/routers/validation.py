from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import City, Project, User, ValidationRecord
from ..schemas import ValidationRecordUpdate
from ..services.audit import write_audit
from ..services.validation_layer import (
    CHECK_FIELDS,
    CHECK_KEYS,
    EDITABLE_KEYS,
    LINK_FIELDS,
    LINK_KEYS_BY_CHECK,
    SOURCE_FIELDS,
    compute_status,
    field_schema,
    import_validation_folder,
    normalise_check,
    normalise_link,
)

router = APIRouter(prefix="/validation", tags=["Validation Layer"])

LINK_KEYS = set(LINK_KEYS_BY_CHECK.values()) | {field["key"] for field in LINK_FIELDS}
CHECK_LABELS = {field["key"]: field["label"] for field in CHECK_FIELDS}


def _require_project(project_id: int, db: Session) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


def _serialise(record: ValidationRecord) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": record.id,
        "source_row": record.source_row,
        "source_file": record.source_file,
        "validation_status": record.validation_status,
        "updated_by_email": record.updated_by_email,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }
    for field in SOURCE_FIELDS:
        payload[field["key"]] = getattr(record, field["key"])
    for key in EDITABLE_KEYS:
        payload[key] = getattr(record, key)
    return payload


@router.get("/schema")
def validation_schema(user: Annotated[User, Depends(get_current_user)]) -> dict[str, Any]:
    return field_schema()


@router.get("/{project_id}/records")
def list_records(
    project_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    search: str | None = Query(None),
    provider: str | None = Query(None),
    status: str | None = Query(None),
    city_id: int | None = Query(None, description="Restrict to one city; omit for every city"),
) -> dict[str, Any]:
    _require_project(project_id, db)

    # First open of the tab on a database seeded before this feature existed.
    scope = ValidationRecord.project_id == project_id
    if not db.scalar(select(func.count(ValidationRecord.id)).where(scope)):
        import_validation_folder(db, project_id)
    if city_id:
        scope = scope & (ValidationRecord.city_id == city_id)

    query = select(ValidationRecord).where(scope)
    if provider:
        query = query.where(ValidationRecord.provider == provider.upper())
    if status:
        query = query.where(ValidationRecord.validation_status == status.upper())
    if search:
        term = f"%{search.strip()}%"
        query = query.where(
            ValidationRecord.business_name.ilike(term) | ValidationRecord.address.ilike(term)
        )

    records = list(db.scalars(query.order_by(ValidationRecord.city_id, ValidationRecord.source_row)))
    all_records = list(db.scalars(select(ValidationRecord).where(scope)))
    counts = {"PENDING": 0, "IN_PROGRESS": 0, "COMPLETED": 0}
    for record in all_records:
        counts[record.validation_status] = counts.get(record.validation_status, 0) + 1

    cities = list(db.scalars(select(City).where(City.project_id == project_id).order_by(City.name)))
    city_names = {city.id: city.name for city in cities}
    city_counts = dict(
        db.execute(
            select(ValidationRecord.city_id, func.count())
            .where(ValidationRecord.project_id == project_id)
            .group_by(ValidationRecord.city_id)
        ).all()
    )

    return {
        "project_id": project_id,
        "city_id": city_id,
        "cities": [
            {"id": c.id, "name": c.name, "region": c.region, "records": city_counts.get(c.id, 0)}
            for c in cities
        ],
        "total": len(all_records),
        "returned": len(records),
        "summary": counts,
        "providers": sorted({r.provider for r in all_records if r.provider}),
        "source_file": next((r.source_file for r in all_records if r.source_file), None),
        "records": [{**_serialise(r), "city": city_names.get(r.city_id)} for r in records],
    }


@router.put("/records/{record_id}")
def save_record(
    record_id: int,
    payload: ValidationRecordUpdate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    record = db.get(ValidationRecord, record_id)
    if not record:
        raise HTTPException(404, "Validation record not found")

    submitted = payload.model_dump()

    # Normalise the YES/NO answers first so the link rules can rely on them.
    answers: dict[str, str | None] = {}
    for key in CHECK_KEYS:
        raw = submitted.get(key)
        answer = normalise_check(raw)
        if raw not in (None, "") and answer is None:
            raise HTTPException(422, f"{CHECK_LABELS[key]} must be answered Yes or No")
        answers[key] = answer

    values: dict[str, Any] = {}
    for key in EDITABLE_KEYS:
        if key in CHECK_KEYS:
            values[key] = answers[key]
        elif key in LINK_KEYS:
            values[key] = normalise_link(submitted.get(key))
        else:
            text = str(submitted.get(key) or "").strip()
            values[key] = text or None

    # A YES answer has to be backed by a link; a NO answer never carries one.
    for key in CHECK_KEYS:
        link_key = LINK_KEYS_BY_CHECK[key]
        if answers[key] == "YES" and not values[link_key]:
            raise HTTPException(422, f"{CHECK_LABELS[key]} is marked Yes - add the supporting link")
        if answers[key] != "YES":
            values[link_key] = None

    before = {key: getattr(record, key) for key in EDITABLE_KEYS}
    for key, value in values.items():
        setattr(record, key, value)
    record.validation_status = compute_status(record)
    record.updated_by_email = user.email

    changed = {key: {"from": before[key], "to": values[key]} for key in EDITABLE_KEYS if before[key] != values[key]}
    write_audit(
        db,
        user,
        "VALIDATION_RECORD_SAVED",
        "ValidationRecord",
        record.id,
        {"business_name": record.business_name, "status": record.validation_status, "changed": changed},
    )
    db.commit()
    db.refresh(record)
    return _serialise(record)


@router.post("/{project_id}/reimport")
def reimport(
    project_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    """Refresh the discovery columns from every workbook. Saved answers are kept."""
    _require_project(project_id, db)
    results = import_validation_folder(db, project_id)
    if not results:
        raise HTTPException(404, "No .xlsx workbook found in backend/misseddata")
    write_audit(db, user, "VALIDATION_WORKBOOK_IMPORTED", "Project", project_id, {"results": results})
    db.commit()
    return {"imported": results}
