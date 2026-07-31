from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_roles
from ..database import get_db
from ..models import (
    CandidateStatus,
    ConnectorMode,
    ConnectorRun,
    ConnectorRunStatus,
    GoogleStatus,
    PoiCandidate,
    Project,
    RawSourceRecord,
    SourceConnector,
    User,
    UserRole,
)
from ..schemas import ConnectorCreate, ConnectorOut, ConnectorRunRequest
from ..services.audit import write_audit
from ..services.connectors import ConnectorError, run_connector
from ..services.eligibility import recalculate_candidate
from ..services.normalization import normalize_row

router = APIRouter(prefix="/sources", tags=["Source Connectors"])


@router.get("", response_model=list[ConnectorOut])
def list_connectors(project_id: int, db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]):
    return db.scalars(select(SourceConnector).where(SourceConnector.project_id == project_id).order_by(SourceConnector.name)).all()


@router.post("", response_model=ConnectorOut, status_code=201)
def create_connector(
    payload: ConnectorCreate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(UserRole.PROGRAM_ADMIN, UserRole.PROJECT_MANAGER))],
):
    if not db.get(Project, payload.project_id):
        raise HTTPException(404, "Project not found")
    existing = db.scalar(select(SourceConnector).where(SourceConnector.project_id == payload.project_id, SourceConnector.name == payload.name))
    if existing:
        raise HTTPException(409, "A connector with this name already exists in the project")
    connector = SourceConnector(**payload.model_dump())
    db.add(connector)
    db.flush()
    write_audit(db, user, "SOURCE_CONNECTOR_CREATED", "source_connector", connector.id, {"name": connector.name, "mode": connector.mode.value})
    db.commit()
    db.refresh(connector)
    return connector


@router.post("/{connector_id}/run")
def execute_connector(
    connector_id: int,
    payload: ConnectorRunRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(UserRole.PROGRAM_ADMIN, UserRole.PROJECT_MANAGER, UserRole.DISCOVERY_ANALYST))],
):
    connector = db.get(SourceConnector, connector_id)
    if not connector:
        raise HTTPException(404, "Connector not found")
    if connector.mode in {ConnectorMode.FILE_UPLOAD, ConnectorMode.MANUAL}:
        raise HTTPException(422, "This connector uses file/manual mode and cannot be executed as a live job")
    project = db.get(Project, connector.project_id)
    run = ConnectorRun(
        connector_id=connector.id,
        project_id=connector.project_id,
        status=ConnectorRunStatus.RUNNING,
        query=payload.query,
        geography={"city": payload.city, "latitude": payload.latitude, "longitude": payload.longitude, "radius_m": payload.radius_m},
    )
    db.add(run)
    db.flush()
    try:
        records = run_connector(
            connector,
            query=payload.query,
            max_results=payload.max_results,
            city=payload.city,
            latitude=payload.latitude,
            longitude=payload.longitude,
            radius_m=payload.radius_m,
        )
        run.records_discovered = len(records)
        run.raw_response = records[:100]
        imported_ids: list[int] = []
        for record in records:
            normalized = normalize_row(record)
            if normalized["business_name"] == "Unnamed candidate":
                continue
            raw_json = json.dumps(record, sort_keys=True, default=str).encode("utf-8")
            raw = RawSourceRecord(
                project_id=project.id,
                connector_run_id=run.id,
                source_name=connector.name,
                source_record_id=str(normalized.get("source_record_id") or "") or None,
                raw_payload=record,
                payload_sha256=hashlib.sha256(raw_json).hexdigest(),
                imported_by=user.id,
            )
            db.add(raw)
            db.flush()
            is_google = connector.source_type.upper() in {"GOOGLE", "GOOGLE_PLACES"}
            is_mock = bool(record.get("_mock")) or connector.mode == ConnectorMode.MOCK
            candidate = PoiCandidate(
                project_id=project.id,
                raw_source_record_id=raw.id,
                poi_id=f"POI-{uuid.uuid4().hex[:12].upper()}",
                source_name=connector.name,
                source_type=connector.source_type,
                source_record_id=normalized.pop("source_record_id", None),
                coordinate_precision="PROVIDER_POINT" if normalized.get("latitude") is not None and normalized.get("longitude") is not None else "UNKNOWN",
                extraction_date=date.today(),
                reviewer_identity=f"connector:{connector.id}",
                created_by=user.id,
                updated_by=user.id,
                confidence_score=70 if not is_mock else 60,
                google_status=GoogleStatus.GOOGLE_PRESENT_CONFIRMED if is_google else GoogleStatus.GOOGLE_CHECK_PENDING,
                google_review_completed=is_google,
                google_reviewer=f"connector:{connector.id}" if is_google else None,
                status=CandidateStatus.GOOGLE_PRESENT_CONFIRMED if is_google else CandidateStatus.GOOGLE_CHECK_PENDING,
                is_demo=is_mock,
                city=normalized.pop("city", None) or payload.city,
                province=normalized.pop("province", None) or ("Indonesia" if payload.city else None),
                **normalized,
            )
            recalculate_candidate(candidate, project)
            db.add(candidate)
            db.flush()
            imported_ids.append(candidate.id)
        run.records_imported = len(imported_ids)
        run.status = ConnectorRunStatus.COMPLETED
        run.completed_at = datetime.now(timezone.utc)
        connector.last_run_at = run.completed_at
        connector.last_error = None
        write_audit(db, user, "SOURCE_CONNECTOR_RUN", "connector_run", run.id, {"connector": connector.name, "discovered": len(records), "imported": len(imported_ids), "mode": connector.mode.value})
        db.commit()
        return {"run_id": run.id, "status": run.status.value, "records_discovered": len(records), "records_imported": len(imported_ids), "candidate_ids": imported_ids, "mock": connector.mode == ConnectorMode.MOCK}
    except ConnectorError as exc:
        run.status = ConnectorRunStatus.FAILED
        run.error = str(exc)
        run.completed_at = datetime.now(timezone.utc)
        connector.last_error = str(exc)
        db.commit()
        raise HTTPException(422, str(exc)) from exc


@router.get("/{connector_id}/runs")
def connector_runs(connector_id: int, db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]):
    return db.scalars(select(ConnectorRun).where(ConnectorRun.connector_id == connector_id).order_by(ConnectorRun.started_at.desc()).limit(100)).all()
