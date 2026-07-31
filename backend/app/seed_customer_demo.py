from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path

from sqlalchemy import delete, select

from .auth import hash_password
from .config import get_settings
from .database import Base, SessionLocal, engine
from .models import (
    AuditLog,
    CandidateStatus,
    ComparisonBucket,
    ConnectorMode,
    ConnectorRun,
    ConnectorRunStatus,
    EntityMatch,
    EvidenceItem,
    EvidenceType,
    GoogleCheck,
    GoogleStatus,
    PoiCandidate,
    Project,
    QualityTier,
    RawSourceRecord,
    SourceConnector,
    User,
    UserRole,
)
from .services.eligibility import recalculate_candidate
from .services.google_rules import MANDATORY_GOOGLE_CHECKS
from .services.normalization import normalize_text

settings = get_settings()
DATA_FILE = Path(__file__).parent / "data" / "denpasar_customer_demo.json"
PROJECT_NAME = "L'Oréal / Web Geo Services — Denpasar CORE Capability Demo"


def get_or_create_user(db, email: str, full_name: str, role: UserRole, password: str | None = None) -> User:
    user = db.scalar(select(User).where(User.email == email.lower()))
    if not user:
        user = User(
            email=email.lower(),
            full_name=full_name,
            password_hash=hash_password(password or settings.demo_admin_password),
            role=role,
        )
        db.add(user)
        db.flush()
    return user


def split_signal_breakdown(text: str | None) -> dict[str, float]:
    values: dict[str, float] = {}
    for key, value in re.findall(r"([a-z_]+)=([0-9.]+)", text or ""):
        values[key] = round(float(value) * 100, 2)
    return values


def partial_google_checklist(record: dict) -> list[dict]:
    method = record.get("evidence_method")
    completed = set()
    if method == "PROBE":
        completed = {"EXACT_NAME", "FULL_ADDRESS", "COORDINATE_SEARCH"}
    elif method == "AREA_COVERAGE":
        completed = {"COORDINATE_SEARCH", "NEARBY_SALON_SEARCH"}

    name = record.get("business_name") or ""
    address = record.get("address") or ""
    lat = record.get("latitude")
    lon = record.get("longitude")
    query_map = {
        "EXACT_NAME": name,
        "NAME_PLUS_CITY": f"{name} Denpasar",
        "NAME_PLUS_LOCALITY": f"{name} Denpasar Bali",
        "FULL_ADDRESS": f"{name} {address}",
        "ALTERNATE_SPELLING": name,
        "NORMALIZED_NAME": normalize_text(name),
        "PHONE_NUMBER": "Not available in source extract",
        "WHATSAPP_NUMBER": "Not available in source extract",
        "WEBSITE_DOMAIN": "Not available in source extract",
        "COORDINATE_SEARCH": f"{lat},{lon}",
        "NEARBY_SALON_SEARCH": f"hair salon near {lat},{lon}",
        "BRANCH_CHECK": f"branch review: {name}",
        "RENAMED_BUSINESS_CHECK": f"renamed business review: {name}",
        "MOVED_LOCATION_CHECK": f"moved location review: {name}",
        "CLOSED_BUSINESS_CHECK": f"closed business review: {name}",
        "DUPLICATE_MERGED_LISTING_CHECK": f"duplicate or merged listing review: {name}",
    }
    return [
        {
            "check_type": check,
            "query": query_map[check],
            "completed": check in completed,
            "result": "NOT_FOUND" if check in completed else "NOT_RUN",
            "candidate_place_ids": [],
            "search_radius_m": 300 if check == "NEARBY_SALON_SEARCH" else None,
            "evidence_reference": record.get("provider_place_id") if check in completed else None,
            "notes": (
                f"Imported from workbook {method} evidence; this is not the complete 16-step Google exclusion workflow."
                if check in completed
                else "Pending customer-grade verification."
            ),
        }
        for check in MANDATORY_GOOGLE_CHECKS
    ]


def candidate_status(record: dict) -> tuple[GoogleStatus, ComparisonBucket, str, int]:
    provider = record["provider"]
    role = record["role"]
    if provider == "GOOGLE":
        bucket = {
            "MATCHED": ComparisonBucket.COMMON,
            "POSSIBLE": ComparisonBucket.POSSIBLE_MATCH,
            "GOOGLE_ONLY": ComparisonBucket.BASELINE_ONLY,
            "UNRESOLVED": ComparisonBucket.UNCLASSIFIED,
        }.get(role, ComparisonBucket.BASELINE_ONLY)
        return GoogleStatus.GOOGLE_PRESENT_CONFIRMED, bucket, "GOOGLE_PRESENT_CONFIRMED", 88 if role == "MATCHED" else 78
    if role == "MATCHED":
        return GoogleStatus.GOOGLE_PRESENT_CONFIRMED, ComparisonBucket.COMMON, "GOOGLE_PRESENT_CONFIRMED", 92
    if role == "POSSIBLE":
        return GoogleStatus.GOOGLE_POSSIBLE_MATCH, ComparisonBucket.POSSIBLE_MATCH, "GOOGLE_POSSIBLE_MATCH", 68
    if role == "INCREMENTAL":
        confidence = 68 if record.get("customer_tier") == "TIER_1_DIRECT_PROBE" else 60
        return GoogleStatus.GOOGLE_CHECK_INCONCLUSIVE, ComparisonBucket.SOURCE_ONLY, "ENRICHMENT_PENDING", confidence
    return GoogleStatus.GOOGLE_CHECK_PENDING, ComparisonBucket.UNCLASSIFIED, "GOOGLE_CHECK_PENDING", 50


def reset_customer_demo(db) -> None:
    project = db.scalar(select(Project).where(Project.name == PROJECT_NAME))
    if project:
        db.delete(project)
        db.flush()
    # The demo project owns candidates via cascade; these tables do not all cascade in SQLite.
    # A full database reset through RESET_DEMO_WINDOWS.bat remains the recommended clean path.


def run_seed(reset: bool = False):
    Base.metadata.create_all(bind=engine)
    payload = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    study = payload["study"]
    db = SessionLocal()
    try:
        admin = get_or_create_user(db, settings.demo_admin_email, "JSAN GeoDiscover Demo Administrator", UserRole.SUPER_ADMIN)
        validator = get_or_create_user(db, "validator.demo@jsanconsulting.com", "Google Validation Analyst", UserRole.GOOGLE_VALIDATOR)
        get_or_create_user(db, "qa.demo@jsanconsulting.com", "Independent QA Reviewer", UserRole.QA_REVIEWER)
        get_or_create_user(db, "research.demo@jsanconsulting.com", "Local Researcher", UserRole.LOCAL_RESEARCHER)
        # Two further sign-ins with their own credentials, for a deployment
        # where the admin password should not be shared around.
        get_or_create_user(
            db,
            settings.demo_manager_email,
            "JSAN Project Manager",
            UserRole.PROJECT_MANAGER,
            settings.manager_password,
        )
        get_or_create_user(
            db,
            settings.demo_analyst_email,
            "JSAN Discovery Analyst",
            UserRole.DISCOVERY_ANALYST,
            settings.analyst_password,
        )
        if reset:
            reset_customer_demo(db)

        project = db.scalar(select(Project).where(Project.name == PROJECT_NAME))
        if not project:
            project = Project(
                name=PROJECT_NAME,
                customer="L'Oréal through Web Geo Services — Customer Capability Demonstration",
                country="Indonesia",
                cities=["Denpasar"],
                categories=["Hair Salon", "Beauty Salon", "Barbershop", "Beauty Services Candidate"],
                target_volume=100,
                confidence_threshold=70,
                gold_threshold=85,
                require_qa_for_release=True,
                created_by=admin.id,
            )
            db.add(project)
            db.flush()

        if db.scalar(select(PoiCandidate.id).where(PoiCandidate.project_id == project.id).limit(1)):
            # Commit before returning, or the users created above are rolled
            # back and a newly added account never reaches the database.
            db.commit()
            print(f"Customer demo already loaded for project {project.id}. Delete customer_demo.db or run RESET_DEMO_WINDOWS.bat for a clean reload.")
            return

        grab_connector = SourceConnector(
            project_id=project.id,
            name="GrabMaps — Authorised Denpasar Extract",
            source_type="GRABMAPS",
            mode=ConnectorMode.FILE_UPLOAD,
            enabled=True,
            credentials_status="AUTHORISED_EXTRACT_LOADED",
            compliance_notes="Workbook-sourced capability demonstration. No live result is fabricated.",
            configuration={"inventory_count": study["headline"]["grab_inventory"], "run_status": study["coverage"]["grab_status"]},
        )
        google_connector = SourceConnector(
            project_id=project.id,
            name="Google Places — Authorised Comparison Baseline",
            source_type="GOOGLE_PLACES",
            mode=ConnectorMode.FILE_UPLOAD,
            enabled=True,
            credentials_status="AUTHORISED_EXTRACT_LOADED",
            compliance_notes="Comparison evidence only; redistribution remains subject to customer/partner licence terms.",
            configuration={"inventory_count": study["headline"]["google_inventory"], "run_status": study["coverage"]["google_status"]},
        )
        db.add_all([grab_connector, google_connector])
        db.flush()
        db.add_all([
            ConnectorRun(
                connector_id=grab_connector.id,
                project_id=project.id,
                status=ConnectorRunStatus.COMPLETED,
                query="Denpasar salon taxonomy sweep — CORE 1.2 km",
                geography={"city": "Denpasar", "radius_m": 1200},
                records_discovered=study["headline"]["grab_inventory"],
                records_imported=study["detail_inventory"]["unique_grab_records_loaded"],
                raw_response={"study": study, "source_workbook": study["source_workbook"]},
            ),
            ConnectorRun(
                connector_id=google_connector.id,
                project_id=project.id,
                status=ConnectorRunStatus.COMPLETED,
                query="Google Places salon nearby sweep and reciprocal probes",
                geography={"city": "Denpasar", "radius_m": 1200},
                records_discovered=study["headline"]["google_inventory"],
                records_imported=study["detail_inventory"]["unique_google_evidence_records_loaded"],
                raw_response={"coverage": study["coverage"], "note": "Budget-limited baseline inventory plus retained probe-result evidence."},
            ),
        ])

        candidate_ids: dict[str, int] = {}
        for index, record in enumerate(payload["candidates"], start=1):
            google_status, comparison_bucket, status_value, confidence = candidate_status(record)
            provider = record["provider"]
            source_name = "GrabMaps Denpasar CORE" if provider == "GRAB" else "Google Places Denpasar CORE"
            raw_payload = dict(record)
            sha = hashlib.sha256(json.dumps(raw_payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
            raw = RawSourceRecord(
                project_id=project.id,
                source_name=source_name,
                source_record_id=record["provider_place_id"],
                raw_payload=raw_payload,
                file_name=study["source_workbook"],
                payload_sha256=sha,
                imported_by=admin.id,
            )
            db.add(raw)
            db.flush()

            role = record.get("role")
            tier = record.get("customer_tier")
            category = (record.get("categories") or "Salon / Beauty Candidate").split(",")[0].strip()[:150]
            evidence_ref = f"DENPASAR-{provider}-{hashlib.sha1(record['provider_place_id'].encode()).hexdigest()[:12].upper()}"
            components = {
                "customer_classification": record.get("customer_classification"),
                "customer_tier": tier,
                "evidence_method": record.get("evidence_method"),
                "evidence_strength": record.get("evidence_strength"),
                "workbook_best_score": record.get("best_score"),
                "workbook_role": role,
                "release_message": "Research candidate only — not customer-release ready.",
            }
            candidate = PoiCandidate(
                project_id=project.id,
                raw_source_record_id=raw.id,
                poi_id=f"IDN-DPS-{provider[:1]}-{index:04d}",
                source_name=source_name,
                source_type="AUTHORISED_WORKBOOK_EXTRACT",
                source_record_id=record["provider_place_id"],
                business_name=(record.get("business_name") or "Unnamed candidate")[:255],
                normalized_name=normalize_text(record.get("business_name") or "Unnamed candidate"),
                alternate_names=[],
                category=category or "Salon / Beauty Candidate",
                subcategory="Customer comparison evidence",
                business_verified=role == "MATCHED",
                full_address=record.get("address"),
                city="Denpasar",
                province="Bali",
                latitude=record.get("latitude"),
                longitude=record.get("longitude"),
                coordinate_precision="SOURCE_COORDINATE",
                phone=record.get("phone"),
                website=record.get("website"),
                primary_source_url=None,
                evidence_reference=evidence_ref,
                extraction_date=date(2026, 7, 30),
                activity_verified=False,
                google_status=google_status,
                google_review_completed=provider == "GOOGLE" or role == "MATCHED",
                google_reviewer="source-comparison-engine" if provider == "GOOGLE" or role == "MATCHED" else None,
                confidence_score=confidence,
                confidence_components=components,
                quality_tier=QualityTier.RESEARCH,
                comparison_bucket=comparison_bucket,
                status=CandidateStatus(status_value),
                is_demo=True,
                reviewer_identity="source-comparison-engine",
                created_by=admin.id,
                updated_by=admin.id,
            )
            recalculate_candidate(candidate, project)
            db.add(candidate)
            db.flush()
            candidate_ids[f"{provider}:{record['provider_place_id']}"] = candidate.id

            if role == "INCREMENTAL":
                checklist = partial_google_checklist(record)
                db.add(GoogleCheck(
                    poi_candidate_id=candidate.id,
                    decision=GoogleStatus.GOOGLE_CHECK_INCONCLUSIVE,
                    checklist=checklist,
                    queries=[{"query": record.get("probe_query"), "method": record.get("evidence_method"), "best_score": record.get("best_score")}],
                    candidate_place_ids=[],
                    nearby_search_radius_m=300 if record.get("evidence_method") == "AREA_COVERAGE" else None,
                    reviewer=validator.email,
                    reason=record.get("evidence_reason") or "Imported source-comparison evidence; full Google exclusion remains incomplete.",
                    evidence_reference=evidence_ref,
                    mandatory_checks_complete=False,
                    completed=False,
                ))
                db.add(EvidenceItem(
                    project_id=project.id,
                    poi_candidate_id=candidate.id,
                    evidence_type=EvidenceType.GOOGLE_COMPARISON,
                    title=f"{record.get('customer_tier', 'Incremental')} workbook evidence",
                    payload={
                        "method": record.get("evidence_method"),
                        "strength": record.get("evidence_strength"),
                        "probe_query": record.get("probe_query"),
                        "result_count": record.get("result_count"),
                        "best_score": record.get("best_score"),
                        "timestamp": record.get("evidence_timestamp"),
                        "reason": record.get("evidence_reason"),
                    },
                    notes="Immutable evidence imported from the authorised Denpasar workbook. It does not by itself satisfy the complete 16-step Google absence standard.",
                    created_by=admin.id,
                ))

        for row in payload["matches"]:
            left_id = candidate_ids.get(f"GRAB:{row['grab_id']}")
            right_id = candidate_ids.get(f"GOOGLE:{row['google_id']}")
            if not left_id or not right_id:
                continue
            signals = split_signal_breakdown(row.get("signal_breakdown"))
            score = float(row.get("match_score") or 0)
            db.add(EntityMatch(
                project_id=project.id,
                candidate_id=left_id,
                comparison_candidate_id=right_id,
                name_score=signals.get("name", 0),
                coordinate_score=signals.get("geo", max(0, 100 - float(row.get("distance_m") or 100))),
                phone_score=0,
                address_score=signals.get("addr", 0),
                web_social_score=0,
                total_score=score,
                distance_m=row.get("distance_m"),
                decision="PROBABLE_SAME_POI" if row["kind"] == "MATCHED" else "MANUAL_REVIEW",
                explanation={
                    "workbook_classification": row["kind"],
                    "method": row.get("method"),
                    "signal_breakdown": row.get("signal_breakdown"),
                    "customer_note": "Matched pairs demonstrate cross-provider overlap; possible pairs remain excluded from gap claims.",
                },
                reviewed_by=row.get("reviewer"),
            ))

        db.add(AuditLog(
            actor_id=admin.id,
            actor_email=admin.email,
            action="CUSTOMER_DEMO_DATASET_LOADED",
            entity_type="project",
            entity_id=str(project.id),
            details={
                "source_workbook": study["source_workbook"],
                "study_headline": study["headline"],
                "strict_customer_release_count": 0,
                "claim_guardrail": study["controls"]["claim"],
            },
        ))
        db.commit()
        print(f"Customer demo seed complete. Project ID: {project.id}")
        print(f"Login: {settings.demo_admin_email}")
        print("All records are marked demonstration-only; strict customer release remains zero.")
    finally:
        db.close()


if __name__ == "__main__":
    run_seed()
