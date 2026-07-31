from __future__ import annotations

import enum
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Enum, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserRole(str, enum.Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    PROGRAM_ADMIN = "PROGRAM_ADMIN"
    PROJECT_MANAGER = "PROJECT_MANAGER"
    DISCOVERY_ANALYST = "DISCOVERY_ANALYST"
    GOOGLE_VALIDATOR = "GOOGLE_VALIDATOR"
    LOCAL_RESEARCHER = "LOCAL_RESEARCHER"
    CALL_VALIDATOR = "CALL_VALIDATOR"
    QA_REVIEWER = "QA_REVIEWER"
    CUSTOMER_VIEWER = "CUSTOMER_VIEWER"
    AUDITOR = "AUDITOR"


class GoogleStatus(str, enum.Enum):
    GOOGLE_CHECK_PENDING = "GOOGLE_CHECK_PENDING"
    GOOGLE_PRESENT_CONFIRMED = "GOOGLE_PRESENT_CONFIRMED"
    GOOGLE_POSSIBLE_MATCH = "GOOGLE_POSSIBLE_MATCH"
    GOOGLE_ABSENT_VERIFIED = "GOOGLE_ABSENT_VERIFIED"
    GOOGLE_CHECK_INCONCLUSIVE = "GOOGLE_CHECK_INCONCLUSIVE"


class CandidateStatus(str, enum.Enum):
    RAW_DISCOVERED = "RAW_DISCOVERED"
    NORMALISED = "NORMALISED"
    DUPLICATE_REVIEW = "DUPLICATE_REVIEW"
    ENTITY_RESOLVED = "ENTITY_RESOLVED"
    GOOGLE_CHECK_PENDING = "GOOGLE_CHECK_PENDING"
    GOOGLE_PRESENT_CONFIRMED = "GOOGLE_PRESENT_CONFIRMED"
    GOOGLE_POSSIBLE_MATCH = "GOOGLE_POSSIBLE_MATCH"
    GOOGLE_ABSENT_VERIFIED = "GOOGLE_ABSENT_VERIFIED"
    GOOGLE_CHECK_INCONCLUSIVE = "GOOGLE_CHECK_INCONCLUSIVE"
    ENRICHMENT_PENDING = "ENRICHMENT_PENDING"
    CALL_VALIDATION_PENDING = "CALL_VALIDATION_PENDING"
    LOCAL_RESEARCH_PENDING = "LOCAL_RESEARCH_PENDING"
    QA_PENDING = "QA_PENDING"
    QA_REWORK = "QA_REWORK"
    ACCEPTED_GOLD = "ACCEPTED_GOLD"
    ACCEPTED_SILVER = "ACCEPTED_SILVER"
    REJECTED = "REJECTED"
    RELEASED = "RELEASED"
    ARCHIVED = "ARCHIVED"


class QualityTier(str, enum.Enum):
    GOLD = "GOLD"
    SILVER = "SILVER"
    RESEARCH = "RESEARCH"
    REJECTED = "REJECTED"


class QaStatus(str, enum.Enum):
    NOT_SUBMITTED = "NOT_SUBMITTED"
    PENDING = "PENDING"
    PASSED = "PASSED"
    REWORK = "REWORK"
    REJECTED = "REJECTED"


class ComparisonBucket(str, enum.Enum):
    UNCLASSIFIED = "UNCLASSIFIED"
    COMMON = "COMMON"
    SOURCE_ONLY = "SOURCE_ONLY"
    BASELINE_ONLY = "BASELINE_ONLY"
    POSSIBLE_MATCH = "POSSIBLE_MATCH"
    VERIFIED_NON_GOOGLE = "VERIFIED_NON_GOOGLE"


class ConnectorMode(str, enum.Enum):
    LIVE = "LIVE"
    MOCK = "MOCK"
    FILE_UPLOAD = "FILE_UPLOAD"
    MANUAL = "MANUAL"


class ConnectorRunStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class EvidenceType(str, enum.Enum):
    SOURCE_URL = "SOURCE_URL"
    SCREENSHOT = "SCREENSHOT"
    PHOTO = "PHOTO"
    RAW_PAYLOAD = "RAW_PAYLOAD"
    GOOGLE_COMPARISON = "GOOGLE_COMPARISON"
    CALL = "CALL"
    LOCAL_RESEARCH = "LOCAL_RESEARCH"
    QA = "QA"


class TaskStatus(str, enum.Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CallOutcome(str, enum.Enum):
    CONFIRMED_ACTIVE = "CONFIRMED_ACTIVE"
    ACTIVE_INFORMATION_CORRECTED = "ACTIVE_INFORMATION_CORRECTED"
    TEMPORARILY_CLOSED = "TEMPORARILY_CLOSED"
    PERMANENTLY_CLOSED = "PERMANENTLY_CLOSED"
    WRONG_NUMBER = "WRONG_NUMBER"
    NO_RESPONSE = "NO_RESPONSE"
    REFUSED = "REFUSED"
    LANGUAGE_ESCALATION_REQUIRED = "LANGUAGE_ESCALATION_REQUIRED"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255), default="JSAN Administrator")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.SUPER_ADMIN)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    customer: Mapped[str] = mapped_column(String(255))
    country: Mapped[str] = mapped_column(String(100))
    cities: Mapped[list[str]] = mapped_column(JSON, default=list)
    categories: Mapped[list[str]] = mapped_column(JSON, default=list)
    target_volume: Mapped[int] = mapped_column(Integer, default=100)
    confidence_threshold: Mapped[int] = mapped_column(Integer, default=70)
    gold_threshold: Mapped[int] = mapped_column(Integer, default=85)
    require_qa_for_release: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(50), default="ACTIVE")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    candidates: Mapped[list["PoiCandidate"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class SourceConnector(Base):
    __tablename__ = "source_connectors"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_connector_project_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(150))
    source_type: Mapped[str] = mapped_column(String(100))
    mode: Mapped[ConnectorMode] = mapped_column(Enum(ConnectorMode), default=ConnectorMode.FILE_UPLOAD)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    credentials_status: Mapped[str] = mapped_column(String(50), default="NOT_REQUIRED")
    compliance_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ConnectorRun(Base):
    __tablename__ = "connector_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connector_id: Mapped[int] = mapped_column(ForeignKey("source_connectors.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    status: Mapped[ConnectorRunStatus] = mapped_column(Enum(ConnectorRunStatus), default=ConnectorRunStatus.QUEUED)
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    geography: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    records_discovered: Mapped[int] = mapped_column(Integer, default=0)
    records_imported: Mapped[int] = mapped_column(Integer, default=0)
    raw_response: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RawSourceRecord(Base):
    __tablename__ = "raw_source_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    connector_run_id: Mapped[int | None] = mapped_column(ForeignKey("connector_runs.id"), nullable=True)
    source_name: Mapped[str] = mapped_column(String(100))
    source_record_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    imported_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PoiEntity(Base):
    __tablename__ = "poi_entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    entity_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    canonical_name: Mapped[str] = mapped_column(String(255))
    canonical_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class PoiCandidate(Base):
    __tablename__ = "poi_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    entity_id: Mapped[int | None] = mapped_column(ForeignKey("poi_entities.id"), nullable=True, index=True)
    raw_source_record_id: Mapped[int | None] = mapped_column(ForeignKey("raw_source_records.id"), nullable=True)
    poi_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    source_name: Mapped[str] = mapped_column(String(100), index=True)
    source_type: Mapped[str] = mapped_column(String(100), default="FILE_UPLOAD")
    source_record_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    business_name: Mapped[str] = mapped_column(String(255), index=True)
    normalized_name: Mapped[str] = mapped_column(String(255), index=True)
    local_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    alternate_names: Mapped[list[str]] = mapped_column(JSON, default=list)
    category: Mapped[str] = mapped_column(String(150), index=True)
    subcategory: Mapped[str | None] = mapped_column(String(150), nullable=True)
    branch_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    business_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    full_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    locality: Mapped[str | None] = mapped_column(String(150), nullable=True)
    district: Mapped[str | None] = mapped_column(String(150), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), index=True, nullable=True)
    province: Mapped[str | None] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    coordinate_precision: Mapped[str | None] = mapped_column(String(50), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(80), nullable=True)
    whatsapp: Mapped[str | None] = mapped_column(String(80), nullable=True)
    whatsapp_business: Mapped[bool] = mapped_column(Boolean, default=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    website: Mapped[str | None] = mapped_column(Text, nullable=True)
    booking_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    instagram: Mapped[str | None] = mapped_column(Text, nullable=True)
    tiktok: Mapped[str | None] = mapped_column(Text, nullable=True)
    facebook: Mapped[str | None] = mapped_column(Text, nullable=True)
    opening_hours: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    services: Mapped[list[str]] = mapped_column(JSON, default=list)
    primary_source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_active_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    activity_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    google_status: Mapped[GoogleStatus] = mapped_column(Enum(GoogleStatus), default=GoogleStatus.GOOGLE_CHECK_PENDING, index=True)
    google_review_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    google_reviewer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    confidence_score: Mapped[int] = mapped_column(Integer, default=0)
    confidence_components: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    quality_tier: Mapped[QualityTier] = mapped_column(Enum(QualityTier), default=QualityTier.RESEARCH, index=True)
    usability_eligible: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    usability_failures: Mapped[list[str]] = mapped_column(JSON, default=list)
    qa_status: Mapped[QaStatus] = mapped_column(Enum(QaStatus), default=QaStatus.NOT_SUBMITTED, index=True)
    qa_reviewer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    qa_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    release_approved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    comparison_bucket: Mapped[ComparisonBucket] = mapped_column(Enum(ComparisonBucket), default=ComparisonBucket.UNCLASSIFIED, index=True)
    status: Mapped[CandidateStatus] = mapped_column(Enum(CandidateStatus), default=CandidateStatus.GOOGLE_CHECK_PENDING)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewer_identity: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    project: Mapped[Project] = relationship(back_populates="candidates")


class GoogleCheck(Base):
    __tablename__ = "google_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    poi_candidate_id: Mapped[int] = mapped_column(ForeignKey("poi_candidates.id"), index=True)
    decision: Mapped[GoogleStatus] = mapped_column(Enum(GoogleStatus))
    checklist: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    queries: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    candidate_place_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    nearby_search_radius_m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reviewer: Mapped[str] = mapped_column(String(255))
    reason: Mapped[str] = mapped_column(Text)
    evidence_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    mandatory_checks_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EntityMatch(Base):
    __tablename__ = "entity_match_scores"
    __table_args__ = (UniqueConstraint("candidate_id", "comparison_candidate_id", name="uq_entity_match_pair"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("poi_candidates.id"), index=True)
    comparison_candidate_id: Mapped[int] = mapped_column(ForeignKey("poi_candidates.id"), index=True)
    name_score: Mapped[float] = mapped_column(Float, default=0)
    coordinate_score: Mapped[float] = mapped_column(Float, default=0)
    phone_score: Mapped[float] = mapped_column(Float, default=0)
    address_score: Mapped[float] = mapped_column(Float, default=0)
    web_social_score: Mapped[float] = mapped_column(Float, default=0)
    total_score: Mapped[float] = mapped_column(Float, default=0, index=True)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    decision: Mapped[str] = mapped_column(String(50), default="UNRESOLVED")
    explanation: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DuplicateGroup(Base):
    __tablename__ = "duplicate_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(50), default="OPEN")
    canonical_candidate_id: Mapped[int | None] = mapped_column(ForeignKey("poi_candidates.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DuplicateMembership(Base):
    __tablename__ = "duplicate_memberships"
    __table_args__ = (UniqueConstraint("group_id", "candidate_id", name="uq_duplicate_group_candidate"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("duplicate_groups.id"), index=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("poi_candidates.id"), index=True)
    is_canonical: Mapped[bool] = mapped_column(Boolean, default=False)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EvidenceItem(Base):
    __tablename__ = "evidence_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    poi_candidate_id: Mapped[int] = mapped_column(ForeignKey("poi_candidates.id"), index=True)
    evidence_type: Mapped[EvidenceType] = mapped_column(Enum(EvidenceType))
    title: Mapped[str] = mapped_column(String(255))
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    storage_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_immutable: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QaReview(Base):
    __tablename__ = "qa_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    poi_candidate_id: Mapped[int] = mapped_column(ForeignKey("poi_candidates.id"), index=True)
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewer_email: Mapped[str] = mapped_column(String(255))
    decision: Mapped[QaStatus] = mapped_column(Enum(QaStatus))
    checklist: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    defects: Mapped[list[str]] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text)
    independent_review: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CallJob(Base):
    __tablename__ = "call_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    poi_candidate_id: Mapped[int] = mapped_column(ForeignKey("poi_candidates.id"), index=True)
    provider: Mapped[str] = mapped_column(String(100), default="MOCK")
    provider_mode: Mapped[str] = mapped_column(String(30), default="MOCK")
    language: Mapped[str] = mapped_column(String(30), default="id-ID")
    script_version: Mapped[str] = mapped_column(String(50), default="ID-SALON-V1")
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.OPEN)
    outcome: Mapped[CallOutcome | None] = mapped_column(Enum(CallOutcome), nullable=True)
    structured_answers: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    transcript_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    consent_status: Mapped[str] = mapped_column(String(50), default="NOT_RECORDED")
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ResearchTask(Base):
    __tablename__ = "research_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    poi_candidate_id: Mapped[int] = mapped_column(ForeignKey("poi_candidates.id"), index=True)
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.OPEN)
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    corrected_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    corrected_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    operating_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    storefront_evidence_id: Mapped[int | None] = mapped_column(ForeignKey("evidence_items.id"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StatusHistory(Base):
    __tablename__ = "status_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    poi_candidate_id: Mapped[int] = mapped_column(ForeignKey("poi_candidates.id"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    to_status: Mapped[str] = mapped_column(String(80))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExportRecord(Base):
    __tablename__ = "exports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    file_name: Mapped[str] = mapped_column(String(255))
    record_count: Mapped[int] = mapped_column(Integer)
    validation_summary: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class City(Base):
    """A city whose workbook has been loaded into the validation layer."""

    __tablename__ = "cities"
    __table_args__ = (UniqueConstraint("project_id", "slug", name="uq_city_project_slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    slug: Mapped[str] = mapped_column(String(120), index=True)
    region: Mapped[str | None] = mapped_column(String(120), nullable=True)
    country: Mapped[str] = mapped_column(String(80), default="Indonesia")
    source_files: Mapped[list[str]] = mapped_column(JSON, default=list)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Set when the city was loaded from a full Grab-vs-Google benchmark export.
    headline: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    coverage: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_by_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, onupdate=utcnow)


class CityCandidate(Base):
    """A place from a city's benchmark export.

    These feed the executive views only. The validation layer and scraping work
    from ValidationRecord, which is loaded from a separate validation workbook.
    """

    __tablename__ = "city_candidates"
    __table_args__ = (
        UniqueConstraint("city_id", "provider", "provider_place_id", name="uq_city_candidate_place"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"), index=True)
    provider: Mapped[str | None] = mapped_column(String(50), index=True, nullable=True)
    provider_place_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    business_name: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    categories: Mapped[str | None] = mapped_column(Text, nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    city_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    province: Mapped[str | None] = mapped_column(String(120), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(120), nullable=True)
    website: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_status: Mapped[str | None] = mapped_column(String(120), nullable=True)
    evidence_method: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    evidence_strength: Mapped[str | None] = mapped_column(Text, nullable=True)
    probe_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    best_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_timestamp: Mapped[str | None] = mapped_column(String(80), nullable=True)
    evidence_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    found_by_probe: Mapped[str | None] = mapped_column(String(20), nullable=True)
    role: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    customer_tier: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CityMatch(Base):
    """A scored Grab/Google pair from a city's comparison run."""

    __tablename__ = "city_matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)  # MATCHED or POSSIBLE
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    method: Mapped[str | None] = mapped_column(String(60), nullable=True)
    signal_breakdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    grab_place_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    grab_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    grab_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    grab_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    grab_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    google_place_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    google_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    google_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    google_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    google_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ScrapeJobStatus(str, enum.Enum):
    UPLOADED = "UPLOADED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ScrapeJob(Base):
    """One uploaded workbook processed through the web-evidence providers."""

    __tablename__ = "scrape_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    city_id: Mapped[int | None] = mapped_column(ForeignKey("cities.id"), nullable=True, index=True)
    file_name: Mapped[str] = mapped_column(String(255))
    status: Mapped[ScrapeJobStatus] = mapped_column(Enum(ScrapeJobStatus), default=ScrapeJobStatus.UPLOADED, index=True)
    total_records: Mapped[int] = mapped_column(Integer, default=0)
    processed_records: Mapped[int] = mapped_column(Integer, default=0)
    fields_filled: Mapped[int] = mapped_column(Integer, default=0)
    records_with_findings: Mapped[int] = mapped_column(Integer, default=0)
    current_business: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_report: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ValidationRecord(Base):
    """One workbook row for one city, plus the editable validation layer.

    Every record belongs to a city. Uploading a city workbook appends rows here;
    scraping enriches those same rows in place rather than duplicating them.
    """

    __tablename__ = "validation_records"
    __table_args__ = (UniqueConstraint("project_id", "city_id", "source_row", name="uq_validation_project_row"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    city_id: Mapped[int | None] = mapped_column(ForeignKey("cities.id"), nullable=True, index=True)
    last_job_id: Mapped[int | None] = mapped_column(ForeignKey("scrape_jobs.id"), nullable=True, index=True)
    source_row: Mapped[int] = mapped_column(Integer, index=True)
    source_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scrape_state: Mapped[str | None] = mapped_column(String(30), nullable=True)
    scrape_findings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # Discovery evidence carried over from the workbook - read-only in the UI.
    provider: Mapped[str | None] = mapped_column(String(50), index=True, nullable=True)
    provider_place_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    business_name: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    categories: Mapped[str | None] = mapped_column(Text, nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    province: Mapped[str | None] = mapped_column(String(120), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(120), nullable=True)
    website: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_status: Mapped[str | None] = mapped_column(String(120), nullable=True)
    evidence_method: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    evidence_strength: Mapped[str | None] = mapped_column(Text, nullable=True)
    probe_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    best_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_timestamp: Mapped[str | None] = mapped_column(String(80), nullable=True)
    evidence_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    found_by_probe: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Set by a benchmark import; otherwise derived from the evidence method.
    role: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    customer_tier: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)

    # Validation layer - YES/NO presence checks, each with a supporting link.
    google_maps: Mapped[str | None] = mapped_column(String(3), nullable=True)
    google_maps_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    google_street_view: Mapped[str | None] = mapped_column(String(3), nullable=True)
    gsv_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    yellow_pages_indonesia: Mapped[str | None] = mapped_column(String(3), nullable=True)
    yellow_pages_indonesia_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    search_yellow_directory: Mapped[str | None] = mapped_column(String(3), nullable=True)
    search_yellow_directory_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    indonesia_yp: Mapped[str | None] = mapped_column(String(3), nullable=True)
    indonesia_yp_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    fresha: Mapped[str | None] = mapped_column(String(3), nullable=True)
    fresha_link: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Validation layer - free links and contact evidence.
    website_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    services: Mapped[str | None] = mapped_column(Text, nullable=True)
    facebook: Mapped[str | None] = mapped_column(Text, nullable=True)
    instagram: Mapped[str | None] = mapped_column(Text, nullable=True)
    tiktok: Mapped[str | None] = mapped_column(Text, nullable=True)
    whatsapp: Mapped[str | None] = mapped_column(Text, nullable=True)
    identified_contact_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    identified_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    validation_status: Mapped[str] = mapped_column(String(30), default="PENDING", index=True)
    updated_by_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, onupdate=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    actor_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
