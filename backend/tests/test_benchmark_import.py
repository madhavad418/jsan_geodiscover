"""Benchmark exports vary in layout, so columns are read by header name."""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import CityCandidate, CityMatch, Project, ValidationRecord
from app.services.benchmark_import import (
    Columns,
    ROLE_PRECEDENCE,
    find_workbooks,
    import_benchmark,
)
from app.services.city_analytics import dataset


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(Project(id=1, name="T", customer="C", country="ID"))
    session.commit()
    yield session
    session.close()


def test_columns_are_found_by_name_not_position():
    full = Columns(("Provider", "Provider Place ID", "Business Status", "Evidence Method"))
    # Surabaya's Grab sheet omits Business Status, shifting everything after it.
    short = Columns(("Provider", "Provider Place ID", "Evidence Method"))
    row_full = ("GRAB", "P1", "OPERATIONAL", "PROBE")
    row_short = ("GRAB", "P1", "PROBE")
    assert full.get(row_full, "Evidence Method") == "PROBE"
    assert short.get(row_short, "Evidence Method") == "PROBE"
    assert short.get(row_short, "Business Status") is None


def test_missing_column_returns_none_not_an_error():
    columns = Columns(("Provider", "Business Name"))
    assert columns.get(("GRAB",), "Business Name") is None   # row shorter than header
    assert columns.get(("GRAB", "X"), "Nonexistent") is None


def test_verified_outranks_possible():
    # A place can be proposed as a possible pair and still be verified unique.
    assert ROLE_PRECEDENCE["MATCHED"] < ROLE_PRECEDENCE["INCREMENTAL"]
    assert ROLE_PRECEDENCE["INCREMENTAL"] < ROLE_PRECEDENCE["POSSIBLE"]
    assert ROLE_PRECEDENCE["POSSIBLE"] < ROLE_PRECEDENCE["UNRESOLVED"]


@pytest.mark.skipif(not find_workbooks(), reason="no benchmark workbooks present")
def test_real_exports_reconcile_with_their_summary(db):
    """Tier counts must equal the export's own GU_grab_only_*_verified metrics."""
    for path in find_workbooks():
        result = import_benchmark(db, 1, path, path.name)
        data = dataset(db, 1, result["city_id"])
        headline = data["study"]["headline"]

        tier1 = sum(1 for c in data["candidates"] if c["customer_tier"] == "TIER_1_DIRECT_PROBE")
        tier2 = sum(1 for c in data["candidates"] if c["customer_tier"] == "TIER_2_AREA_SUPPORTED")
        assert tier1 == headline["tier1_direct_probe_candidates"], f"{result['city']} tier 1"
        assert tier2 == headline["tier2_area_supported_leads"], f"{result['city']} tier 2"

        # Only Grab-side rows are direct-probe candidates.
        assert all(
            c["provider"] == "GRAB"
            for c in data["candidates"]
            if c["customer_tier"] == "TIER_1_DIRECT_PROBE"
        ), f"{result['city']} has a non-Grab tier 1 candidate"

        assert data["comparison_available"] is True
        assert data["matches"], f"{result['city']} has no scored pairs"


@pytest.mark.skipif(not find_workbooks(), reason="no benchmark workbooks present")
def test_reimport_does_not_duplicate(db):
    path = find_workbooks()[0]
    first = import_benchmark(db, 1, path, path.name)
    second = import_benchmark(db, 1, path, path.name)
    assert second["added"] == 0
    assert second["refreshed"] == first["added"]
    assert len(list(db.scalars(select(CityCandidate)))) == first["candidates"]
    # Pairs are replaced wholesale rather than appended twice.
    pairs = len(list(db.scalars(select(CityMatch))))
    assert pairs == first["matched_pairs"] + first["possible_pairs"]


@pytest.mark.skipif(not find_workbooks(), reason="no benchmark workbooks present")
def test_benchmark_rows_stay_out_of_the_validation_queue(db):
    """The validation layer and scraping read only a city's validation workbook."""
    for path in find_workbooks():
        import_benchmark(db, 1, path, path.name)
    assert list(db.scalars(select(CityCandidate)))          # candidates were loaded
    assert not list(db.scalars(select(ValidationRecord)))   # validation queue untouched
