from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select

from .auth import hash_password
from .config import get_settings
from .database import Base, SessionLocal, engine
from .models import (
    CallJob,
    CallOutcome,
    ComparisonBucket,
    ConnectorMode,
    EntityMatch,
    EvidenceItem,
    EvidenceType,
    GoogleCheck,
    GoogleStatus,
    PoiCandidate,
    Project,
    QaReview,
    QaStatus,
    ResearchTask,
    SourceConnector,
    TaskStatus,
    User,
    UserRole,
)
from .services.eligibility import recalculate_candidate
from .services.entity_resolution import score_pair
from .services.google_rules import MANDATORY_GOOGLE_CHECKS
from .services.normalization import normalize_text

settings = get_settings()
CITIES = ["Jakarta", "Surabaya", "Bandung", "Medan", "Denpasar"]
CITY_COORDS = {
    "Jakarta": (-6.2088, 106.8456),
    "Surabaya": (-7.2575, 112.7521),
    "Bandung": (-6.9175, 107.6191),
    "Medan": (3.5952, 98.6722),
    "Denpasar": (-8.6500, 115.2167),
}


def get_or_create_user(db, email: str, full_name: str, role: UserRole) -> User:
    user = db.scalar(select(User).where(User.email == email))
    if not user:
        user = User(email=email, full_name=full_name, password_hash=hash_password(settings.demo_admin_password), role=role)
        db.add(user)
        db.flush()
    return user


def demo_candidate(project: Project, idx: int, source_name: str, **overrides) -> PoiCandidate:
    city = overrides.pop("city", CITIES[(idx - 1) % len(CITIES)])
    lat, lon = CITY_COORDS[city]
    defaults = dict(
        project_id=project.id,
        poi_id=f"DEMO-ID-{idx:03d}",
        source_name=source_name,
        source_type="DEMO_SEED",
        source_record_id=f"DEMO-{source_name[:3].upper()}-{idx:03d}",
        business_name=f"Demo Salon {idx}",
        normalized_name=normalize_text(f"Demo Salon {idx}"),
        local_name=None,
        alternate_names=[],
        category="Hair Salon",
        subcategory="Beauty & Hair",
        business_verified=True,
        full_address=f"Jl. Contoh No. {idx}, {city}, Indonesia",
        locality="Central District",
        district="Demo Kecamatan",
        city=city,
        province="DKI Jakarta" if city == "Jakarta" else ("Bali" if city == "Denpasar" else "Indonesia"),
        postal_code=f"10{idx:03d}",
        latitude=lat + idx * 0.00025,
        longitude=lon + idx * 0.00025,
        coordinate_precision="ROOFTOP",
        phone=f"+62-812-0000-{idx:04d}",
        whatsapp=f"+62-812-0000-{idx:04d}",
        whatsapp_business=idx % 2 == 0,
        website=f"https://demo.example/salon-{idx}",
        booking_url=f"https://booking.example/salon-{idx}" if idx % 3 == 0 else None,
        instagram=f"https://instagram.com/demo_salon_{idx}" if idx % 2 == 1 else None,
        tiktok=f"https://tiktok.com/@demo_salon_{idx}" if idx % 4 == 0 else None,
        facebook=f"https://facebook.com/demo.salon.{idx}" if idx % 3 != 0 else None,
        primary_source_url=f"https://source.example/record/{idx}",
        evidence_reference=f"DEMO-EVIDENCE-{idx:03d}",
        extraction_date=date.today(),
        last_active_date=date.today() - timedelta(days=idx),
        activity_verified=True,
        google_status=GoogleStatus.GOOGLE_CHECK_PENDING,
        google_review_completed=False,
        google_reviewer=None,
        confidence_score=75,
        confidence_components={"identity": 18, "address": 17, "coordinates": 18, "contact": 13, "activity": 8, "corroboration": 7, "call_or_research": 4},
        reviewer_identity="demo-discovery-analyst",
        qa_status=QaStatus.NOT_SUBMITTED,
        comparison_bucket=ComparisonBucket.UNCLASSIFIED,
        is_demo=True,
    )
    defaults.update(overrides)
    item = PoiCandidate(**defaults)
    recalculate_candidate(item, project)
    return item


def checklist_for(candidate: PoiCandidate) -> list[dict]:
    query_map = {
        "EXACT_NAME": candidate.business_name,
        "NAME_PLUS_CITY": f"{candidate.business_name} {candidate.city}",
        "NAME_PLUS_LOCALITY": f"{candidate.business_name} {candidate.locality}",
        "FULL_ADDRESS": f"{candidate.business_name} {candidate.full_address}",
        "ALTERNATE_SPELLING": f"{candidate.business_name.replace('Salon', 'Saloon')}",
        "NORMALIZED_NAME": candidate.normalized_name,
        "PHONE_NUMBER": candidate.phone or "reviewed-no-phone",
        "WHATSAPP_NUMBER": candidate.whatsapp or "reviewed-no-whatsapp",
        "WEBSITE_DOMAIN": candidate.website or "reviewed-no-domain",
        "COORDINATE_SEARCH": f"{candidate.latitude},{candidate.longitude}",
        "NEARBY_SALON_SEARCH": f"hair salon near {candidate.latitude},{candidate.longitude}",
        "BRANCH_CHECK": f"branch review: {candidate.business_name}",
        "RENAMED_BUSINESS_CHECK": f"renamed business review: {candidate.business_name}",
        "MOVED_LOCATION_CHECK": f"moved location review: {candidate.business_name}",
        "CLOSED_BUSINESS_CHECK": f"closed business review: {candidate.business_name}",
        "DUPLICATE_MERGED_LISTING_CHECK": f"duplicate merged listing review: {candidate.business_name}",
    }
    return [{
        "check_type": check,
        "query": query_map[check],
        "completed": True,
        "result": "NOT_FOUND",
        "candidate_place_ids": [],
        "search_radius_m": 250 if check == "NEARBY_SALON_SEARCH" else None,
        "evidence_reference": f"DEMO-GOOGLE-{candidate.poi_id}-{check}",
        "notes": "Demonstration checklist entry; not a live Google search.",
    } for check in MANDATORY_GOOGLE_CHECKS]


def run_seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        admin = get_or_create_user(db, settings.demo_admin_email.lower(), "JSAN GeoDiscover Administrator", UserRole.SUPER_ADMIN)
        validator = get_or_create_user(db, "validator.demo@jsanconsulting.com", "Demo Google Validator", UserRole.GOOGLE_VALIDATOR)
        qa_user = get_or_create_user(db, "qa.demo@jsanconsulting.com", "Demo Independent QA Reviewer", UserRole.QA_REVIEWER)
        researcher = get_or_create_user(db, "research.demo@jsanconsulting.com", "Demo Local Researcher", UserRole.LOCAL_RESEARCHER)
        caller = get_or_create_user(db, "call.demo@jsanconsulting.com", "Demo Call Validator", UserRole.CALL_VALIDATOR)

        project = db.scalar(select(Project).where(Project.name == "Indonesia Salon Intelligence — Customer Capability Demo"))
        if not project:
            project = Project(
                name="Indonesia Salon Intelligence — Customer Capability Demo",
                customer="L'Oréal / Web Geo Services — Demonstration Only",
                country="Indonesia",
                cities=CITIES,
                categories=["Hair Salon", "Beauty Salon", "Salon Kecantikan"],
                target_volume=100,
                confidence_threshold=70,
                gold_threshold=85,
                require_qa_for_release=True,
                created_by=admin.id,
            )
            db.add(project)
            db.flush()

        if not db.scalar(select(SourceConnector.id).where(SourceConnector.project_id == project.id).limit(1)):
            db.add_all([
                SourceConnector(project_id=project.id, name="Google Places Live", source_type="GOOGLE_PLACES", mode=ConnectorMode.LIVE, enabled=False, credentials_status="API_KEY_REQUIRED", compliance_notes="Use customer/partner-authorised Google Places credentials."),
                SourceConnector(project_id=project.id, name="GrabMaps via Amazon Location", source_type="GRABMAPS", mode=ConnectorMode.LIVE, enabled=False, credentials_status="AWS_PLACE_INDEX_REQUIRED", compliance_notes="Use an authorised Amazon Location place index configured for GrabMaps."),
                SourceConnector(project_id=project.id, name="Instagram via Apify", source_type="INSTAGRAM", mode=ConnectorMode.LIVE, enabled=False, credentials_status="APIFY_TOKEN_REQUIRED", compliance_notes="Actor configuration and platform terms must be approved."),
                SourceConnector(project_id=project.id, name="TikTok via Apify", source_type="TIKTOK", mode=ConnectorMode.LIVE, enabled=False, credentials_status="APIFY_TOKEN_REQUIRED", compliance_notes="Actor configuration and platform terms must be approved."),
                SourceConnector(project_id=project.id, name="Facebook via Apify", source_type="FACEBOOK", mode=ConnectorMode.LIVE, enabled=False, credentials_status="APIFY_TOKEN_REQUIRED", compliance_notes="Actor ID and platform terms must be approved."),
                SourceConnector(project_id=project.id, name="Directory / Booking Upload", source_type="DIRECTORY_BOOKING", mode=ConnectorMode.FILE_UPLOAD, enabled=True, credentials_status="NOT_REQUIRED", compliance_notes="Use authorised CSV/XLSX extracts from Fresha, Yellow Pages Indonesia, IndonesiaYP or official directories."),
                SourceConnector(project_id=project.id, name="Leadership Demo Mock", source_type="MOCK", mode=ConnectorMode.MOCK, enabled=True, credentials_status="NOT_REQUIRED", compliance_notes="Clearly labelled mock connector. Never use output as customer finding."),
            ])

        if not db.scalar(select(PoiCandidate.id).where(PoiCandidate.project_id == project.id).limit(1)):
            grab_gita = demo_candidate(project, 1, "GrabMaps Demo", business_name="Salon Gita Benchmark Demo", normalized_name="salon gita benchmark demo", city="Denpasar", google_status=GoogleStatus.GOOGLE_ABSENT_VERIFIED, google_review_completed=True, google_reviewer=validator.email, confidence_score=94, comparison_bucket=ComparisonBucket.SOURCE_ONLY)
            grab_common = demo_candidate(project, 2, "GrabMaps Demo", business_name="Mawar Beauty Studio Demo", normalized_name="mawar beauty studio demo", city="Jakarta", google_status=GoogleStatus.GOOGLE_PRESENT_CONFIRMED, google_review_completed=True, google_reviewer=validator.email, confidence_score=91, comparison_bucket=ComparisonBucket.COMMON)
            grab_possible = demo_candidate(project, 3, "GrabMaps Demo", business_name="Cantik Hair House Demo", normalized_name="cantik hair house demo", city="Bandung", google_status=GoogleStatus.GOOGLE_POSSIBLE_MATCH, google_review_completed=True, google_reviewer=validator.email, confidence_score=76, comparison_bucket=ComparisonBucket.POSSIBLE_MATCH)
            grab_only = demo_candidate(project, 4, "GrabMaps Demo", business_name="Nusa Hair Studio Demo", normalized_name="nusa hair studio demo", city="Surabaya", google_status=GoogleStatus.GOOGLE_ABSENT_VERIFIED, google_review_completed=True, google_reviewer=validator.email, confidence_score=87, comparison_bucket=ComparisonBucket.SOURCE_ONLY)
            google_common = demo_candidate(project, 5, "Google Places Demo", business_name="Mawar Beauty Studio", normalized_name="mawar beauty studio", city="Jakarta", google_status=GoogleStatus.GOOGLE_PRESENT_CONFIRMED, google_review_completed=True, google_reviewer="google-baseline-adapter", confidence_score=95, comparison_bucket=ComparisonBucket.COMMON, latitude=grab_common.latitude + 0.00003, longitude=grab_common.longitude + 0.00003, phone=grab_common.phone, whatsapp=grab_common.whatsapp, full_address=grab_common.full_address, source_record_id="GOOGLE-PLACE-DEMO-001")
            google_possible = demo_candidate(project, 6, "Google Places Demo", business_name="Cantik House Salon Demo", normalized_name="cantik house salon demo", city="Bandung", google_status=GoogleStatus.GOOGLE_PRESENT_CONFIRMED, google_review_completed=True, google_reviewer="google-baseline-adapter", confidence_score=90, comparison_bucket=ComparisonBucket.POSSIBLE_MATCH, latitude=grab_possible.latitude + 0.001, longitude=grab_possible.longitude + 0.001, source_record_id="GOOGLE-PLACE-DEMO-002")
            google_only = demo_candidate(project, 7, "Google Places Demo", business_name="Google Listed Salon Demo", normalized_name="google listed salon demo", city="Medan", google_status=GoogleStatus.GOOGLE_PRESENT_CONFIRMED, google_review_completed=True, google_reviewer="google-baseline-adapter", confidence_score=92, comparison_bucket=ComparisonBucket.BASELINE_ONLY, source_record_id="GOOGLE-PLACE-DEMO-003")
            instagram_gold = demo_candidate(project, 8, "Instagram Demo", business_name="Bali Social Salon Demo", normalized_name="bali social salon demo", city="Denpasar", google_status=GoogleStatus.GOOGLE_ABSENT_VERIFIED, google_review_completed=True, google_reviewer=validator.email, confidence_score=90, comparison_bucket=ComparisonBucket.SOURCE_ONLY)
            booking_silver = demo_candidate(project, 9, "Fresha Demo", business_name="Surabaya Booking Salon Demo", normalized_name="surabaya booking salon demo", city="Surabaya", google_status=GoogleStatus.GOOGLE_ABSENT_VERIFIED, google_review_completed=True, google_reviewer=validator.email, confidence_score=80, comparison_bucket=ComparisonBucket.SOURCE_ONLY)
            directory_research = demo_candidate(project, 10, "IndonesiaYP Demo", business_name="Medan Directory Candidate Demo", normalized_name="medan directory candidate demo", city="Medan", google_status=GoogleStatus.GOOGLE_CHECK_INCONCLUSIVE, google_review_completed=False, confidence_score=64)
            missing_address = demo_candidate(project, 11, "TikTok Demo", business_name="TikTok Salon Missing Location Demo", normalized_name="tiktok salon missing location demo", city="Jakarta", google_status=GoogleStatus.GOOGLE_ABSENT_VERIFIED, google_review_completed=True, google_reviewer=validator.email, confidence_score=86, full_address=None)
            pending = demo_candidate(project, 12, "Web Search Demo", business_name="Pending Web Discovery Demo", normalized_name="pending web discovery demo", city="Bandung", google_status=GoogleStatus.GOOGLE_CHECK_PENDING, confidence_score=60)
            rows = [grab_gita, grab_common, grab_possible, grab_only, google_common, google_possible, google_only, instagram_gold, booking_silver, directory_research, missing_address, pending]
            db.add_all(rows)
            db.flush()

            for candidate in [grab_gita, grab_only, instagram_gold, booking_silver, missing_address]:
                check = GoogleCheck(
                    poi_candidate_id=candidate.id,
                    decision=GoogleStatus.GOOGLE_ABSENT_VERIFIED,
                    checklist=checklist_for(candidate),
                    queries=[],
                    candidate_place_ids=[],
                    nearby_search_radius_m=250,
                    reviewer=validator.email,
                    reason="Demonstration of complete 16-step Google-exclusion control.",
                    evidence_reference=candidate.evidence_reference,
                    mandatory_checks_complete=True,
                    completed=True,
                )
                db.add(check)
                db.add(EvidenceItem(project_id=project.id, poi_candidate_id=candidate.id, evidence_type=EvidenceType.SOURCE_URL, title="Primary discovery evidence (demo)", source_url=candidate.primary_source_url, payload={"demo": True, "source": candidate.source_name}, notes="Demonstration evidence only; not a live customer finding.", created_by=admin.id))
                db.add(EvidenceItem(project_id=project.id, poi_candidate_id=candidate.id, evidence_type=EvidenceType.GOOGLE_COMPARISON, title="Google exclusion evidence manifest (demo)", source_url=None, payload={"check_count": 16, "all_complete": True, "demo": True}, notes="Demonstration evidence only.", created_by=validator.id))

            for candidate in [grab_gita, grab_only, instagram_gold, booking_silver]:
                candidate.qa_status = QaStatus.PASSED
                candidate.qa_reviewer = qa_user.email
                db.add(QaReview(
                    poi_candidate_id=candidate.id,
                    reviewer_id=qa_user.id,
                    reviewer_email=qa_user.email,
                    decision=QaStatus.PASSED,
                    checklist={
                        "identity_verified": True,
                        "salon_category_verified": True,
                        "address_verified": True,
                        "coordinates_verified": True,
                        "contact_verified": True,
                        "activity_verified": True,
                        "google_exclusion_verified": True,
                        "evidence_complete": True,
                        "duplicate_check_complete": True,
                    },
                    defects=[],
                    notes="Demonstration independent QA pass. Record remains excluded from customer release because it is demo data.",
                    independent_review=True,
                ))
                recalculate_candidate(candidate, project)

            call = CallJob(
                poi_candidate_id=grab_gita.id,
                provider="MOCK",
                provider_mode="MOCK",
                language="id-ID",
                script_version="ID-SALON-V1",
                status=TaskStatus.COMPLETED,
                outcome=CallOutcome.CONFIRMED_ACTIVE,
                structured_answers={"business_name_confirmed": True, "active": True, "services": ["hair salon", "makeup"], "address_confirmed": True},
                transcript_reference=None,
                consent_status="NOT_RECORDED",
                confidence=92,
                assigned_to=caller.id,
            )
            db.add(call)
            db.add(ResearchTask(
                poi_candidate_id=instagram_gold.id,
                status=TaskStatus.SUBMITTED,
                assigned_to=researcher.id,
                corrected_address=instagram_gold.full_address,
                corrected_latitude=instagram_gold.latitude,
                corrected_longitude=instagram_gold.longitude,
                operating_status="CONFIRMED_ACTIVE",
                notes="Demonstration local-research correction and storefront confirmation workflow.",
            ))

            for left, right in [(grab_common, google_common), (grab_possible, google_possible)]:
                scored = score_pair(left, right)
                db.add(EntityMatch(
                    project_id=project.id,
                    candidate_id=left.id,
                    comparison_candidate_id=right.id,
                    decision="PROBABLE_SAME_POI" if left is grab_common else "MANUAL_REVIEW",
                    **scored,
                ))

        db.commit()
        print(f"Seed complete. Administrator: {settings.demo_admin_email}")
        print("All demo users use the DEMO_ADMIN_PASSWORD configured in .env")
    finally:
        db.close()


if __name__ == "__main__":
    run_seed()
