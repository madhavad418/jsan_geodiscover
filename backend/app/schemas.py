from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from .models import (
    CallOutcome,
    ComparisonBucket,
    ConnectorMode,
    EvidenceType,
    GoogleStatus,
    QaStatus,
    QualityTier,
    TaskStatus,
    UserRole,
)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserOut(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    role: UserRole
    model_config = ConfigDict(from_attributes=True)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=3, max_length=255)
    customer: str
    country: str = "Indonesia"
    cities: list[str] = []
    categories: list[str] = ["Hair Salon"]
    target_volume: int = Field(default=100, ge=1)
    confidence_threshold: int = Field(default=70, ge=0, le=100)
    gold_threshold: int = Field(default=85, ge=0, le=100)
    require_qa_for_release: bool = True


class ProjectOut(ProjectCreate):
    id: int
    status: str
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class CandidateOut(BaseModel):
    id: int
    poi_id: str
    project_id: int
    entity_id: int | None
    source_name: str
    source_type: str
    source_record_id: str | None
    business_name: str
    normalized_name: str
    local_name: str | None
    alternate_names: list[str]
    category: str
    subcategory: str | None
    branch_name: str | None
    business_verified: bool
    full_address: str | None
    locality: str | None
    district: str | None
    city: str | None
    province: str | None
    postal_code: str | None
    latitude: float | None
    longitude: float | None
    coordinate_precision: str | None
    phone: str | None
    whatsapp: str | None
    whatsapp_business: bool
    email: str | None
    website: str | None
    booking_url: str | None
    instagram: str | None
    tiktok: str | None
    facebook: str | None
    opening_hours: dict[str, Any]
    services: list[str]
    primary_source_url: str | None
    evidence_reference: str | None
    extraction_date: date | None
    last_active_date: date | None
    activity_verified: bool
    google_status: GoogleStatus
    google_review_completed: bool
    google_reviewer: str | None
    confidence_score: int
    confidence_components: dict[str, Any]
    quality_tier: QualityTier
    usability_eligible: bool
    usability_failures: list[str]
    qa_status: QaStatus
    qa_reviewer: str | None
    qa_completed_at: datetime | None
    release_approved: bool
    comparison_bucket: ComparisonBucket
    status: str
    rejection_reason: str | None
    is_demo: bool
    reviewer_identity: str | None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class CandidateUpdate(BaseModel):
    business_name: str | None = None
    local_name: str | None = None
    alternate_names: list[str] | None = None
    category: str | None = None
    subcategory: str | None = None
    branch_name: str | None = None
    business_verified: bool | None = None
    full_address: str | None = None
    locality: str | None = None
    district: str | None = None
    city: str | None = None
    province: str | None = None
    postal_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    coordinate_precision: str | None = None
    phone: str | None = None
    whatsapp: str | None = None
    whatsapp_business: bool | None = None
    email: str | None = None
    website: str | None = None
    booking_url: str | None = None
    instagram: str | None = None
    tiktok: str | None = None
    facebook: str | None = None
    opening_hours: dict[str, Any] | None = None
    services: list[str] | None = None
    primary_source_url: str | None = None
    evidence_reference: str | None = None
    extraction_date: date | None = None
    last_active_date: date | None = None
    activity_verified: bool | None = None
    confidence_score: int | None = Field(default=None, ge=0, le=100)
    confidence_components: dict[str, Any] | None = None
    reviewer_identity: str | None = None


class GoogleChecklistItem(BaseModel):
    check_type: str
    query: str
    completed: bool = False
    result: str = "NOT_RUN"
    candidate_place_ids: list[str] = []
    match_score: float | None = None
    search_radius_m: int | None = None
    evidence_reference: str | None = None
    notes: str | None = None


class GoogleReviewRequest(BaseModel):
    decision: GoogleStatus
    completed: bool
    reason: str = Field(min_length=5)
    evidence_reference: str | None = None
    checklist: list[GoogleChecklistItem] = []
    queries: list[dict[str, Any]] = []
    candidate_place_ids: list[str] = []
    nearby_search_radius_m: int | None = None


class ImportResult(BaseModel):
    imported: int
    rejected_rows: int
    candidate_ids: list[int]


class ComparisonRunRequest(BaseModel):
    project_id: int
    source_name: str = "Grab"
    baseline_name: str = "Google"
    source_candidate_ids: list[int] | None = None
    baseline_candidate_ids: list[int] | None = None
    common_threshold: float = Field(default=80, ge=0, le=100)
    possible_threshold: float = Field(default=60, ge=0, le=100)


class EntityMatchOut(BaseModel):
    id: int
    candidate_id: int
    comparison_candidate_id: int
    name_score: float
    coordinate_score: float
    phone_score: float
    address_score: float
    web_social_score: float
    total_score: float
    distance_m: float | None
    decision: str
    explanation: dict[str, Any]
    model_config = ConfigDict(from_attributes=True)


class ComparisonSummary(BaseModel):
    common: int
    source_only: int
    baseline_only: int
    possible_match: int
    matches_created: int
    source_name: str
    baseline_name: str


class MatchDecisionRequest(BaseModel):
    decision: str = Field(pattern="^(SAME_POI|SEPARATE|UNRESOLVED)$")
    reason: str = Field(min_length=5)
    canonical_candidate_id: int | None = None


class EvidenceCreate(BaseModel):
    evidence_type: EvidenceType
    title: str
    source_url: str | None = None
    payload: dict[str, Any] = {}
    notes: str | None = None


class EvidenceOut(BaseModel):
    id: int
    project_id: int
    poi_candidate_id: int
    evidence_type: EvidenceType
    title: str
    source_url: str | None
    file_name: str | None
    storage_path: str | None
    sha256: str | None
    mime_type: str | None
    payload: dict[str, Any]
    notes: str | None
    is_immutable: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class QaReviewRequest(BaseModel):
    decision: QaStatus
    checklist: dict[str, Any]
    defects: list[str] = []
    notes: str = Field(min_length=5)
    independent_review: bool = True


class QaReviewOut(BaseModel):
    id: int
    poi_candidate_id: int
    reviewer_email: str
    decision: QaStatus
    checklist: dict[str, Any]
    defects: list[str]
    notes: str
    independent_review: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class CallJobCreate(BaseModel):
    provider: str = "MOCK"
    provider_mode: str = "MOCK"
    language: str = "id-ID"
    script_version: str = "ID-SALON-V1"


class CallJobComplete(BaseModel):
    outcome: CallOutcome
    structured_answers: dict[str, Any]
    transcript_reference: str | None = None
    consent_status: str = "NOT_RECORDED"
    confidence: int = Field(ge=0, le=100)


class CallJobOut(BaseModel):
    id: int
    poi_candidate_id: int
    provider: str
    provider_mode: str
    language: str
    script_version: str
    status: TaskStatus
    outcome: CallOutcome | None
    structured_answers: dict[str, Any]
    transcript_reference: str | None
    consent_status: str
    confidence: int | None
    created_at: datetime
    completed_at: datetime | None
    model_config = ConfigDict(from_attributes=True)


class ResearchTaskCreate(BaseModel):
    assigned_to: int | None = None


class ResearchTaskSubmit(BaseModel):
    corrected_address: str | None = None
    corrected_latitude: float | None = None
    corrected_longitude: float | None = None
    operating_status: str
    notes: str = Field(min_length=3)


class ResearchTaskOut(BaseModel):
    id: int
    poi_candidate_id: int
    status: TaskStatus
    assigned_to: int | None
    corrected_address: str | None
    corrected_latitude: float | None
    corrected_longitude: float | None
    operating_status: str | None
    storefront_evidence_id: int | None
    notes: str | None
    created_at: datetime
    submitted_at: datetime | None
    model_config = ConfigDict(from_attributes=True)


class ConnectorCreate(BaseModel):
    project_id: int
    name: str
    source_type: str
    mode: ConnectorMode
    enabled: bool = True
    configuration: dict[str, Any] = {}
    credentials_status: str = "NOT_REQUIRED"
    compliance_notes: str | None = None


class ConnectorOut(ConnectorCreate):
    id: int
    last_run_at: datetime | None
    last_error: str | None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ConnectorRunRequest(BaseModel):
    query: str
    city: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    radius_m: int = Field(default=15000, ge=100, le=50000)
    max_results: int = Field(default=20, ge=1, le=100)


class DashboardKpi(BaseModel):
    A_total: int
    B_google_present: int
    C_google_absent_verified: int
    D_usable_non_google: int
    E_instagram_on_D: int
    F_tiktok_on_D: int
    G_facebook_on_D: int
    H_whatsapp_on_D: int
    I_inconclusive_or_pending: int
    incremental_usable_ratio: float
    google_coverage_ratio: float
    verified_gap_ratio: float
    usability_rate_of_gaps: float
    gold_quality_ratio: float
    coordinate_precision_coverage: float
    contactability_coverage: float
    qa_pass_rate: float
    release_ready_count: int
    comparison_common: int
    comparison_source_only: int
    comparison_baseline_only: int
    comparison_possible: int
    invariant_a_equals_b_plus_c_plus_i: bool
    invariant_d_subset_c: bool
    invariant_release_requires_qa: bool
    by_city: list[dict[str, Any]]
    by_source: list[dict[str, Any]]
    by_google_status: list[dict[str, Any]]
    by_quality_tier: list[dict[str, Any]]
    by_qa_status: list[dict[str, Any]]
    by_comparison_bucket: list[dict[str, Any]]


class AuditOut(BaseModel):
    id: int
    actor_email: str | None
    action: str
    entity_type: str
    entity_id: str | None
    details: dict[str, Any]
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ValidationRecordUpdate(BaseModel):
    """Validation-layer edits. Only the editable columns are accepted."""

    google_maps: str | None = None
    google_maps_link: str | None = None
    google_street_view: str | None = None
    gsv_link: str | None = None
    yellow_pages_indonesia: str | None = None
    yellow_pages_indonesia_link: str | None = None
    search_yellow_directory: str | None = None
    search_yellow_directory_link: str | None = None
    indonesia_yp: str | None = None
    indonesia_yp_link: str | None = None
    fresha: str | None = None
    fresha_link: str | None = None
    website_link: str | None = None
    services: str | None = None
    facebook: str | None = None
    instagram: str | None = None
    tiktok: str | None = None
    whatsapp: str | None = None
    identified_contact_number: str | None = None
    identified_source: str | None = None
    validation_notes: str | None = None
