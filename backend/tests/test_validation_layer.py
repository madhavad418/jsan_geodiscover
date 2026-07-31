"""The misseddata workbook carries two row shapes; both must normalise the same way."""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Project, ValidationRecord
from app.services.validation_layer import (
    append_rows,
    get_or_create_city,
    normalise_check,
    normalise_link,
    parse_row,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(Project(id=1, name="T", customer="C", country="ID"))
    session.commit()
    yield session
    session.close()

ALIGNED = (
    "GRAB", "AQAAAC0Aexample", "AS Beauty Salon", "day spa, beauty services",
    "Jl. Nangka Selatan, Gg. Garuda No. 26", "Bali", None, "-8.638366416", "115.223491",
    None, None, None, "AREA_COVERAGE", "MODERATE - swept area", None, "14", "48.23",
    "2026-07-30T07:53:23.813661", "GOOGLE returned 14 other salons within 300 m", "NO",
    "Yes/No", "Yes/No", None, None, None, None, None, None, None,
    "Yes/No", "Yes/No", "Yes/No", "Yes/No", None, None,
)

# Never probed: every column from "Categories" onward is shifted one to the left.
SHIFTED = (
    "GOOGLE", "ChIJ3TnBT0tB0i0R", "82 BarbershopBALI",
    "Jl. Teuku Umar Barat No.3a, Pemecutan Klod", None,
    "-8.682241099999999", "115.1928226", "Not yet probed in the opposite provider",
)


def test_aligned_row_maps_to_its_header():
    row = parse_row(ALIGNED)
    assert row["categories"].startswith("day spa")
    assert row["address"].startswith("Jl. Nangka Selatan")
    assert row["city"] == "Bali"
    assert row["latitude"] == -8.638366416
    assert row["longitude"] == 115.223491
    assert row["evidence_method"] == "AREA_COVERAGE"
    assert row["result_count"] == 14
    assert row["best_score"] == 48.23


def test_shifted_row_is_realigned():
    row = parse_row(SHIFTED)
    assert row["categories"] is None
    assert row["address"].startswith("Jl. Teuku Umar Barat")
    assert row["latitude"] == -8.682241099999999
    assert row["longitude"] == 115.1928226
    assert row["evidence_method"] == "NOT_PROBED"
    assert row["evidence_reason"] == "Not yet probed in the opposite provider"


def test_workbook_yes_no_placeholder_is_not_an_answer():
    assert parse_row(ALIGNED)["google_maps"] is None
    assert normalise_check("Yes/No") is None
    assert normalise_check("yes") == "YES"
    assert normalise_check(" No ") == "NO"
    assert normalise_check("maybe") is None


def test_bare_domain_gets_a_scheme():
    assert normalise_link("fresha.com/a/demo") == "https://fresha.com/a/demo"
    assert normalise_link("https://maps.google.com/x") == "https://maps.google.com/x"
    assert normalise_link("  ") is None
    assert normalise_link("Yes/No") is None


def test_blank_row_is_skipped():
    assert parse_row((None,) * 35) is None


# --- Workbook layouts differ between cities --------------------------------

from app.services.validation_layer import Columns

JAKARTA_HEADER = (
    "Provider", "Provider Place ID", "Business Name", "Categories", "Address", "City",
    "Province", "Latitude", "Longitude", "Phone", "Business Status", "Evidence Method",
    "Evidence Strength", "Probe Query", "Result Count", "Best Score", "Evidence Timestamp",
    "Evidence Reason", "Found By Probe", "Google maps", "Google strret view ", "GSV link",
    "Website", "services", "FB", "Insta", "TikTok", "whats app", "Yellow Pages Indonesia",
    "Search Yellow Directory", "IndonesiaYP (Indonesia Business Directory)", "Fresha",
)

# Same business, in a workbook that omits the source Website column.
JAKARTA_ROW = (
    "GRAB", "AQ1", "La Disty Salon & Spa", "massages, pijat", "Ruko Graha Mas Pemuda",
    "DKI Jakarta", None, "-6.2061037", "106.833648", None, None, "AREA_COVERAGE",
    "MODERATE - swept area", None, "3", "53.37", "2026-07-31T07:03:54", "GOOGLE returned 3",
    "NO", None, None, None, None, None, None, None, None, None, None, None, None, None,
)


def test_narrower_workbook_still_maps_to_the_right_fields():
    row = parse_row(JAKARTA_ROW, Columns(JAKARTA_HEADER))
    assert row["evidence_method"] == "AREA_COVERAGE"
    assert row["evidence_strength"].startswith("MODERATE")
    assert row["result_count"] == 3
    assert row["best_score"] == 53.37
    assert row["business_status"] is None       # the column is absent
    assert row["latitude"] == -6.2061037


def test_reading_that_row_positionally_would_be_wrong():
    """Guards the bug this replaced: fixed offsets misread the narrower file."""
    wrong = parse_row(JAKARTA_ROW)              # canonical layout assumed
    assert wrong["evidence_method"] != "AREA_COVERAGE"


def test_unstated_evidence_method_is_left_for_the_loader_to_settle():
    """parse_row must not assert NOT_PROBED, or it would erase a known method."""
    header = ("Provider", "Provider Place ID", "Business Name", "Address", "Latitude", "Longitude")
    row = ("GOOGLE", "ChIJ1", "EverGreen Salon", "Jl. Tebet Utara I", "-6.228672", "106.8527803")
    assert parse_row(row, Columns(header))["evidence_method"] is None


def test_no_written_across_the_discovery_block_is_not_data():
    """A validator filling "no" down a row must not become an evidence method."""
    header = (
        "Provider", "Provider Place ID", "Business Name", "Categories", "Address", "City",
        "Province", "Latitude", "Longitude", "Phone", "Business Status", "Evidence Method",
        "Evidence Strength", "Probe Query", "Result Count", "Best Score",
    )
    row = (
        "GRAB", "AQ9", "Andrean Salon", "hair salon", "Jl. Untung", "Bali", None,
        "-8.65", "115.21", "No", "No", "No", "No", "No", "No", "No",
    )
    parsed = parse_row(row, Columns(header))
    assert parsed["evidence_method"] is None
    assert parsed["evidence_strength"] is None
    assert parsed["result_count"] is None
    assert parsed["best_score"] is None
    assert parsed["phone"] is None
    # The business itself still reads correctly.
    assert parsed["business_name"] == "Andrean Salon"
    assert parsed["latitude"] == -8.65


def test_presence_without_a_link_is_kept_as_text():
    assert normalise_link("yes") == "Yes"
    assert normalise_link("No") is None
    assert normalise_link("n/a") is None
    assert normalise_link("https://www.google.com/maps/place/x") == "https://www.google.com/maps/place/x"


def test_a_revision_replaces_a_city_but_keeps_known_evidence(db):
    """Dropping in a revised workbook updates the city instead of merging."""
    from app.services.validation_layer import replace_rows

    city = get_or_create_city(db, 1, "Denpasar")
    header = (
        "Provider", "Provider Place ID", "Business Name", "Categories", "Address", "City",
        "Province", "Latitude", "Longitude", "Phone", "Website", "Business Status",
        "Evidence Method", "Evidence Strength", "Probe Query", "Result Count", "Best Score",
        "Evidence Timestamp", "Evidence Reason", "Found By Probe", "Google maps",
    )
    original = [
        ("GRAB", "P1", "Andrean Salon", "hair", "Jl. Untung", "Bali", None, "-8.65", "115.21",
         None, None, None, "AREA_COVERAGE", "MODERATE", None, "18", "34.49", None, "reason", "NO", None),
        ("GRAB", "P2", "Dropped Salon", "hair", "Jl. Gone", "Bali", None, "-8.66", "115.22",
         None, None, None, "PROBE", "STRONG", None, "5", "41.5", None, "reason", "NO", None),
    ]
    append_rows(db, 1, city, original, "v1.xlsx", Columns(header))
    db.commit()

    # The revision answers Google maps but writes "No" over the evidence block,
    # and no longer lists the second business.
    revision = [
        ("GRAB", "P1", "Andrean Salon", "hair", "Jl. Untung", "Bali", None, "-8.65", "115.21",
         "No", None, "No", "No", "No", "No", "No", "No", "No", "No", "No", "yes"),
    ]
    result = replace_rows(db, 1, city, revision, "v2.xlsx", Columns(header))
    db.commit()

    rows = list(db.scalars(select(ValidationRecord)))
    assert result["removed"] == 1 and len(rows) == 1
    kept = rows[0]
    assert kept.business_name == "Andrean Salon"
    assert kept.google_maps == "YES"              # taken from the revision
    assert kept.evidence_method == "AREA_COVERAGE"  # not erased by "No"
    assert kept.best_score == 34.49
    assert city.source_files == ["v2.xlsx"]
