"""Each city's workbook is appended to the shared tables without colliding."""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Project, ValidationRecord
from app.services.validation_layer import append_rows, get_or_create_city, slugify


def _row(place_id, name, address):
    """A workbook row in the aligned (probed) shape."""
    return (
        "GRAB", place_id, name, "hair salon", address, "Bali", None, "-8.65", "115.21",
        None, None, None, "PROBE", "STRONG", None, "5", "41.5", None, "reason", "NO",
    ) + (None,) * 15


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(Project(id=1, name="T", customer="C", country="ID"))
    session.commit()
    yield session
    session.close()


def test_slugify_folds_case_and_punctuation():
    assert slugify("Denpasar") == "denpasar"
    assert slugify("  Kuta Utara ") == "kuta-utara"
    assert slugify("Nusa Dua!") == "nusa-dua"


def test_same_city_name_is_never_created_twice(db):
    first = get_or_create_city(db, 1, "Ubud", "Bali")
    again = get_or_create_city(db, 1, "  ubud  ")
    assert first.id == again.id


def test_two_cities_keep_their_own_records(db):
    ubud = get_or_create_city(db, 1, "Ubud")
    sanur = get_or_create_city(db, 1, "Sanur")
    append_rows(db, 1, ubud, [_row("U1", "Milk Salon", "Jl. Raya Ubud")], "ubud.xlsx")
    append_rows(db, 1, sanur, [_row("S1", "Peni Weni", "Jl. Sudamala")], "sanur.xlsx")
    db.commit()
    assert db.scalar(select(ValidationRecord).where(ValidationRecord.city_id == ubud.id)).business_name == "Milk Salon"
    assert len(list(db.scalars(select(ValidationRecord)))) == 2


def test_reupload_refreshes_instead_of_duplicating(db):
    city = get_or_create_city(db, 1, "Ubud")
    rows = [_row("U1", "Milk Salon", "Jl. Raya Ubud"), _row("U2", "Bloom", "Jl. Monkey Forest")]
    first = append_rows(db, 1, city, rows, "ubud.xlsx")
    second = append_rows(db, 1, city, rows, "ubud-v2.xlsx")
    db.commit()
    assert (first["added"], second["added"]) == (2, 0)
    assert second["refreshed"] == 2
    assert len(list(db.scalars(select(ValidationRecord)))) == 2
    assert city.source_files == ["ubud.xlsx", "ubud-v2.xlsx"]


def test_reupload_keeps_saved_validation_answers(db):
    city = get_or_create_city(db, 1, "Ubud")
    append_rows(db, 1, city, [_row("U1", "Milk Salon", "Jl. Raya Ubud")], "ubud.xlsx")
    db.commit()
    record = db.scalar(select(ValidationRecord))
    record.fresha = "YES"
    record.fresha_link = "https://www.fresha.com/a/milk"
    record.validation_status = "IN_PROGRESS"
    db.commit()

    append_rows(db, 1, city, [_row("U1", "Milk Salon Renamed", "Jl. Raya Ubud 2")], "ubud.xlsx")
    db.commit()
    db.refresh(record)
    assert record.business_name == "Milk Salon Renamed"   # discovery columns refresh
    assert record.fresha == "YES"                          # saved answers survive
    assert record.fresha_link == "https://www.fresha.com/a/milk"


def test_rows_without_a_place_id_dedupe_on_name_and_address(db):
    city = get_or_create_city(db, 1, "Ubud")
    row = _row(None, "Milk Salon", "Jl. Raya Ubud")
    append_rows(db, 1, city, [row], "a.xlsx")
    second = append_rows(db, 1, city, [row], "b.xlsx")
    db.commit()
    assert second["added"] == 0
    assert len(list(db.scalars(select(ValidationRecord)))) == 1
