from datetime import date, timedelta
from sqlalchemy import select

from .auth import hash_password
from .config import get_settings
from .database import Base, SessionLocal, engine
from .models import GoogleStatus, PoiCandidate, Project, User, UserRole
from .services.eligibility import recalculate_candidate
from .services.normalization import normalize_text

settings = get_settings()
CITIES = ["Jakarta", "Surabaya", "Bandung", "Medan", "Denpasar"]


def candidate(project: Project, idx: int, **overrides):
    city = overrides.pop("city", CITIES[(idx - 1) % len(CITIES)])
    defaults = dict(
        project_id=project.id,
        poi_id=f"DEMO-ID-{idx:03d}",
        source_name="Demo Source",
        source_type="DEMO_SEED",
        source_record_id=f"DEMO-{idx:03d}",
        business_name=f"Demo Salon {idx}",
        normalized_name=normalize_text(f"Demo Salon {idx}"),
        category="Hair Salon",
        business_verified=True,
        full_address=f"Jl. Contoh No. {idx}, {city}",
        locality="Central District",
        city=city,
        province="DKI Jakarta" if city == "Jakarta" else ("Bali" if city == "Denpasar" else "Indonesia"),
        postal_code=f"10{idx:03d}",
        latitude={"Jakarta": -6.2088, "Surabaya": -7.2575, "Bandung": -6.9175, "Medan": 3.5952, "Denpasar": -8.65}[city] + idx * 0.001,
        longitude={"Jakarta": 106.8456, "Surabaya": 112.7521, "Bandung": 107.6191, "Medan": 98.6722, "Denpasar": 115.2167}[city] + idx * 0.001,
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
        reviewer_identity="demo-seed-process",
        is_demo=True,
    )
    defaults.update(overrides)
    item = PoiCandidate(**defaults)
    recalculate_candidate(item, project)
    return item


def run_seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == settings.demo_admin_email.lower()))
        if not user:
            user = User(
                email=settings.demo_admin_email.lower(),
                full_name="JSAN GeoDiscover Administrator",
                password_hash=hash_password(settings.demo_admin_password),
                role=UserRole.SUPER_ADMIN,
            )
            db.add(user)
            db.flush()

        project = db.scalar(select(Project).where(Project.name == "Indonesia Salon Discovery — Leadership Demo"))
        if not project:
            project = Project(
                name="Indonesia Salon Discovery — Leadership Demo",
                customer="Demonstration Customer",
                country="Indonesia",
                cities=CITIES,
                categories=["Hair Salon", "Beauty Salon", "Salon Kecantikan"],
                target_volume=100,
                confidence_threshold=70,
                gold_threshold=85,
                created_by=user.id,
            )
            db.add(project)
            db.flush()

        if not db.scalar(select(PoiCandidate.id).where(PoiCandidate.project_id == project.id).limit(1)):
            rows = [
                candidate(project, 1, business_name="Salon Gita Pattern Demo", normalized_name="salon gita pattern demo", source_name="Instagram Demo", google_status=GoogleStatus.GOOGLE_ABSENT_VERIFIED, google_review_completed=True, google_reviewer="demo-validator", confidence_score=94),
                candidate(project, 2, business_name="Nusa Hair Studio Demo", normalized_name="nusa hair studio demo", source_name="Directory Demo", google_status=GoogleStatus.GOOGLE_ABSENT_VERIFIED, google_review_completed=True, google_reviewer="demo-validator", confidence_score=82),
                candidate(project, 3, business_name="Mawar Beauty Demo", normalized_name="mawar beauty demo", source_name="Booking Demo", google_status=GoogleStatus.GOOGLE_PRESENT_CONFIRMED, google_review_completed=True, google_reviewer="demo-validator", confidence_score=91),
                candidate(project, 4, business_name="Cantik Hub Demo", normalized_name="cantik hub demo", source_name="Grab Feed Demo", google_status=GoogleStatus.GOOGLE_POSSIBLE_MATCH, google_review_completed=True, google_reviewer="demo-validator", confidence_score=73),
                candidate(project, 5, business_name="Bali Glow Demo", normalized_name="bali glow demo", source_name="Facebook Demo", google_status=GoogleStatus.GOOGLE_CHECK_INCONCLUSIVE, google_review_completed=False, confidence_score=68),
                candidate(project, 6, business_name="Rambut Indah Demo", normalized_name="rambut indah demo", source_name="Instagram Demo", google_status=GoogleStatus.GOOGLE_CHECK_PENDING, google_review_completed=False, confidence_score=61),
                candidate(project, 7, business_name="Medan Style Demo", normalized_name="medan style demo", source_name="TikTok Demo", google_status=GoogleStatus.GOOGLE_ABSENT_VERIFIED, google_review_completed=True, google_reviewer="demo-validator", confidence_score=87, full_address=None),
                candidate(project, 8, business_name="Surabaya Hair Lab Demo", normalized_name="surabaya hair lab demo", source_name="Web Search Demo", google_status=GoogleStatus.GOOGLE_ABSENT_VERIFIED, google_review_completed=True, google_reviewer="demo-validator", confidence_score=88, phone=None, whatsapp=None, website=None, booking_url=None, instagram=None, tiktok=None, facebook=None),
                candidate(project, 9, business_name="Bandung Salon House Demo", normalized_name="bandung salon house demo", source_name="Directory Demo", google_status=GoogleStatus.GOOGLE_PRESENT_CONFIRMED, google_review_completed=True, google_reviewer="demo-validator", confidence_score=90),
                candidate(project, 10, business_name="Denpasar Beauty Point Demo", normalized_name="denpasar beauty point demo", source_name="Booking Demo", google_status=GoogleStatus.GOOGLE_ABSENT_VERIFIED, google_review_completed=True, google_reviewer="demo-validator", confidence_score=79),
                candidate(project, 11, business_name="Jakarta Social Salon Demo", normalized_name="jakarta social salon demo", source_name="Instagram Demo", google_status=GoogleStatus.GOOGLE_CHECK_PENDING, google_review_completed=False, confidence_score=72),
                candidate(project, 12, business_name="Medan Booking Salon Demo", normalized_name="medan booking salon demo", source_name="Booking Demo", google_status=GoogleStatus.GOOGLE_PRESENT_CONFIRMED, google_review_completed=True, google_reviewer="demo-validator", confidence_score=86),
                candidate(project, 13, business_name="Surabaya Directory Salon Demo", normalized_name="surabaya directory salon demo", source_name="Directory Demo", google_status=GoogleStatus.GOOGLE_ABSENT_VERIFIED, google_review_completed=True, google_reviewer="demo-validator", confidence_score=92),
                candidate(project, 14, business_name="Bandung Possible Branch Demo", normalized_name="bandung possible branch demo", source_name="Grab Feed Demo", google_status=GoogleStatus.GOOGLE_POSSIBLE_MATCH, google_review_completed=True, google_reviewer="demo-validator", confidence_score=80),
                candidate(project, 15, business_name="Denpasar Pending Salon Demo", normalized_name="denpasar pending salon demo", source_name="Web Search Demo", google_status=GoogleStatus.GOOGLE_CHECK_PENDING, google_review_completed=False, confidence_score=58),
            ]
            db.add_all(rows)
        db.commit()
        print(f"Seed complete. Administrator: {settings.demo_admin_email}")
    finally:
        db.close()


if __name__ == "__main__":
    run_seed()
