"""Validation layer: workbook import and the field specification shared by the API and UI.

The misseddata workbook carries two row shapes. Rows that were probed follow the
header exactly; rows that were never probed in the opposite provider are shifted
one column left from "Categories" onward (address sits under Categories, the
coordinates under City/Province, and the evidence reason under Latitude).
Both shapes are normalised here so the validation layer sees one clean schema.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import City, ValidationRecord

WORKBOOK_DIR = Path(__file__).parents[2] / "misseddata"

# The workbook that shipped with the demo describes Denpasar.
DEFAULT_CITY = {"name": "Denpasar", "region": "Bali", "country": "Indonesia"}

# Placeholder the workbook uses to mark "this column is answered Yes or No".
TEMPLATE_MARKER = "yes/no"

# Validators fill "no" across a whole row, including the discovery columns that
# describe how a place was found. "no" is not an evidence method or a score, so
# these are read as "not stated" rather than stored as literal values.
PLACEHOLDERS = {"yes", "no", "n/a", "na", "none", "-", "--", TEMPLATE_MARKER}


def _is_placeholder(value: Any) -> bool:
    return str(value or "").strip().lower() in PLACEHOLDERS

# Presence checks: a YES/NO dropdown that requires a supporting link when YES.
CHECK_FIELDS: list[dict[str, str]] = [
    {"key": "google_maps", "label": "Google Maps", "link_key": "google_maps_link", "column": "Google maps"},
    {"key": "google_street_view", "label": "Google Street View", "link_key": "gsv_link", "column": "Google strret view "},
    {"key": "yellow_pages_indonesia", "label": "Yellow Pages Indonesia", "link_key": "yellow_pages_indonesia_link", "column": "Yellow Pages Indonesia"},
    {"key": "search_yellow_directory", "label": "Search Yellow Directory", "link_key": "search_yellow_directory_link", "column": "Search Yellow Directory"},
    {"key": "indonesia_yp", "label": "IndonesiaYP", "link_key": "indonesia_yp_link", "column": "IndonesiaYP (Indonesia Business Directory)"},
    {"key": "fresha", "label": "Fresha", "link_key": "fresha_link", "column": "Fresha"},
]

# Free links captured during validation - no YES/NO gate in the workbook.
LINK_FIELDS: list[dict[str, str]] = [
    {"key": "website_link", "label": "Website", "column": "Website"},
    {"key": "services", "label": "Services", "column": "services"},
    {"key": "facebook", "label": "Facebook", "column": "FB"},
    {"key": "instagram", "label": "Instagram", "column": "Insta"},
    {"key": "tiktok", "label": "TikTok", "column": "TikTok"},
    {"key": "whatsapp", "label": "WhatsApp", "column": "whats app"},
]

TEXT_FIELDS: list[dict[str, Any]] = [
    {"key": "identified_contact_number", "label": "Identified Contact Number", "column": "Identified Contact Number"},
    {"key": "identified_source", "label": "Identified Source", "column": "Identified Source"},
    {"key": "validation_notes", "label": "Validator notes", "column": None, "multiline": True},
]

# Discovery evidence shown read-only.
SOURCE_FIELDS: list[dict[str, str]] = [
    {"key": "provider", "label": "Provider"},
    {"key": "provider_place_id", "label": "Provider Place ID"},
    {"key": "business_name", "label": "Business Name"},
    {"key": "categories", "label": "Categories"},
    {"key": "address", "label": "Address"},
    {"key": "city", "label": "City"},
    {"key": "province", "label": "Province"},
    {"key": "latitude", "label": "Latitude"},
    {"key": "longitude", "label": "Longitude"},
    {"key": "phone", "label": "Phone"},
    {"key": "website", "label": "Website (source)"},
    {"key": "business_status", "label": "Business Status"},
    {"key": "evidence_method", "label": "Evidence Method"},
    {"key": "evidence_strength", "label": "Evidence Strength"},
    {"key": "probe_query", "label": "Probe Query"},
    {"key": "result_count", "label": "Result Count"},
    {"key": "best_score", "label": "Best Score"},
    {"key": "evidence_timestamp", "label": "Evidence Timestamp"},
    {"key": "evidence_reason", "label": "Evidence Reason"},
    {"key": "found_by_probe", "label": "Found By Probe"},
]

CHECK_KEYS = [f["key"] for f in CHECK_FIELDS]
LINK_KEYS_BY_CHECK = {f["key"]: f["link_key"] for f in CHECK_FIELDS}
EDITABLE_KEYS = (
    CHECK_KEYS
    + list(LINK_KEYS_BY_CHECK.values())
    + [f["key"] for f in LINK_FIELDS]
    + [f["key"] for f in TEXT_FIELDS]
)


def field_schema() -> dict[str, Any]:
    """Field specification the frontend renders against."""
    return {
        "source_fields": SOURCE_FIELDS,
        "check_fields": CHECK_FIELDS,
        "link_fields": LINK_FIELDS,
        "text_fields": TEXT_FIELDS,
        "check_options": ["YES", "NO"],
        "statuses": ["PENDING", "IN_PROGRESS", "COMPLETED"],
    }


def normalise_check(value: Any) -> str | None:
    """Map a workbook or API value onto YES / NO / unanswered."""
    text = str(value or "").strip().lower()
    if not text or text == TEMPLATE_MARKER:
        return None
    if text in {"yes", "y", "true", "1"}:
        return "YES"
    if text in {"no", "n", "false", "0"}:
        return "NO"
    return None


def normalise_link(value: Any) -> str | None:
    """Accept a bare domain and give it a scheme; keep everything else verbatim.

    A validator may write "no" to mean nothing was found, or "yes" to record a
    presence without pasting the address. Neither is a link: "no" reads as empty
    and "yes" is kept as plain text.
    """
    text = str(value or "").strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered in {"yes"}:
        return "Yes"
    if lowered in PLACEHOLDERS:
        return None
    if "://" not in text and "." in text and " " not in text:
        text = "https://" + text.lstrip("/")
    return text


def compute_status(record: ValidationRecord) -> str:
    answered = sum(1 for key in CHECK_KEYS if getattr(record, key) in {"YES", "NO"})
    if answered == 0:
        return "PENDING"
    return "COMPLETED" if answered == len(CHECK_KEYS) else "IN_PROGRESS"


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == TEMPLATE_MARKER:
        return None
    return text


def _number(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _norm(header: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(header or "").strip().lower()).strip("_")


# The layout of the workbook that shipped with the demo. Used when a caller
# supplies rows without their header row.
CANONICAL_HEADER: tuple[str, ...] = (
    "Provider", "Provider Place ID", "Business Name", "Categories", "Address", "City",
    "Province", "Latitude", "Longitude", "Phone", "Website", "Business Status",
    "Evidence Method", "Evidence Strength", "Probe Query", "Result Count", "Best Score",
    "Evidence Timestamp", "Evidence Reason", "Found By Probe", "Google maps",
    "Google strret view", "GSV link", "Website", "services", "FB", "Insta", "TikTok",
    "whats app", "Yellow Pages Indonesia", "Search Yellow Directory",
    "IndonesiaYP (Indonesia Business Directory)", "Fresha",
    "Identified Contact Number", "Identified Source",
)


class Columns:
    """Read a row by column name.

    Validation workbooks are not identical between cities - the Jakarta and
    Surabaya files omit the source Website column, which shifts every later
    column. Looking columns up by header keeps the import correct whatever the
    layout, and a missing column simply reads as None. With no header supplied
    the canonical layout is assumed.
    """

    def __init__(self, header: tuple[Any, ...] = ()):
        header = tuple(header) or CANONICAL_HEADER
        self._index: dict[str, int] = {}
        for position, name in enumerate(header):
            key = _norm(name)
            # A duplicated header (the canonical layout has two "Website"
            # columns) keeps its first position; the later one is reached by
            # its ordinal via nth().
            if key and key not in self._index:
                self._index[key] = position
        self._header = list(header)

    def has(self, *names: str) -> bool:
        return any(_norm(n) in self._index for n in names)

    def index(self, *names: str) -> int | None:
        for name in names:
            position = self._index.get(_norm(name))
            if position is not None:
                return position
        return None

    def nth(self, name: str, occurrence: int) -> int | None:
        """Position of the Nth column with this header, for duplicated names."""
        key = _norm(name)
        seen = 0
        for position, header in enumerate(self._header):
            if _norm(header) == key:
                seen += 1
                if seen == occurrence:
                    return position
        return None

    def get(self, row: tuple[Any, ...], *names: str) -> Any:
        position = self.index(*names)
        return row[position] if position is not None and position < len(row) else None

    def get_at(self, row: tuple[Any, ...], position: int | None) -> Any:
        return row[position] if position is not None and position < len(row) else None


def parse_row(row: tuple[Any, ...], columns: Columns | None = None) -> dict[str, Any] | None:
    """Normalise one workbook row into validation-record fields.

    Columns are matched by header name when one is supplied. Rows that were
    never probed are shifted left in the source file and are read positionally,
    because the header does not describe their layout.
    """
    columns = columns or Columns()

    def cell(index: int) -> Any:
        return row[index] if index < len(row) else None

    if not _text(cell(0)) and not _text(cell(2)):
        return None

    # Probed rows carry a real latitude in the Latitude column; unprobed rows
    # carry the evidence reason there because their columns are shifted left.
    latitude_at = columns.index("Latitude")
    latitude_at = 7 if latitude_at is None else latitude_at
    aligned = _number(cell(latitude_at)) is not None

    if aligned:
        # Discovery columns describe how a place was found, so a "yes"/"no"
        # placeholder in them is read as "not stated".
        def evidence(*names: str) -> Any:
            value = columns.get(row, *names)
            return None if _is_placeholder(value) else value

        parsed = {
            "categories": _text(evidence("Categories")),
            "address": _text(evidence("Address")),
            "city": _text(evidence("City")),
            "province": _text(evidence("Province")),
            "latitude": _number(evidence("Latitude")),
            "longitude": _number(evidence("Longitude")),
            # Left unstated here; the caller keeps any method already known and
            # otherwise settles on NOT_PROBED.
            "evidence_method": _text(evidence("Evidence Method")),
            "evidence_strength": _text(evidence("Evidence Strength")),
            "probe_query": _text(evidence("Probe Query")),
            "result_count": _int(evidence("Result Count")),
            "best_score": _number(evidence("Best Score")),
            "evidence_timestamp": _text(evidence("Evidence Timestamp")),
            "evidence_reason": _text(evidence("Evidence Reason")),
            "found_by_probe": _text(evidence("Found By Probe")),
            # Phone and status are recorded by the validator, where "no" means
            # none was found.
            "phone": _text(evidence("Phone")),
            "website": _text(evidence("Website")),
            "business_status": _text(evidence("Business Status")),
        }
    else:
        parsed = {
            "categories": None,
            "address": _text(cell(3)),
            "city": _text(cell(4)),
            "province": None,
            "latitude": _number(cell(5)),
            "longitude": _number(cell(6)),
            "evidence_method": "NOT_PROBED",
            "evidence_strength": None,
            "probe_query": None,
            "result_count": None,
            "best_score": None,
            "evidence_timestamp": None,
            "evidence_reason": _text(cell(7)),
            "found_by_probe": None,
            "phone": _text(cell(9)),
            "website": _text(cell(10)),
            "business_status": _text(cell(11)),
        }

    # The validation columns sit after the discovery block. "Website" appears
    # twice in some workbooks - the second one is the validation-layer link.
    website_link_at = columns.nth("Website", 2)
    parsed.update(
        {
            "provider": _text(cell(0)),
            "provider_place_id": _text(cell(1)),
            "business_name": _text(cell(2)),
            # Validation layer values already present in the workbook.
            "google_maps": normalise_check(columns.get(row, "Google maps")),
            "google_street_view": normalise_check(columns.get(row, "Google strret view", "Google street view")),
            "gsv_link": normalise_link(columns.get(row, "GSV link")),
            "website_link": normalise_link(columns.get_at(row, website_link_at)),
            "services": None if _is_placeholder(columns.get(row, "services")) else _text(columns.get(row, "services")),
            "facebook": normalise_link(columns.get(row, "FB", "Facebook")),
            "instagram": normalise_link(columns.get(row, "Insta", "Instagram")),
            "tiktok": normalise_link(columns.get(row, "TikTok")),
            "whatsapp": normalise_link(columns.get(row, "whats app", "whatsapp")),
            "yellow_pages_indonesia": normalise_check(columns.get(row, "Yellow Pages Indonesia")),
            "search_yellow_directory": normalise_check(columns.get(row, "Search Yellow Directory")),
            "indonesia_yp": normalise_check(
                columns.get(row, "IndonesiaYP (Indonesia Business Directory)", "IndonesiaYP")
            ),
            "fresha": normalise_check(columns.get(row, "Fresha")),
            "identified_contact_number": (
                None
                if _is_placeholder(columns.get(row, "Identified Contact Number"))
                else _text(columns.get(row, "Identified Contact Number"))
            ),
            "identified_source": (
                None
                if _is_placeholder(columns.get(row, "Identified Source"))
                else _text(columns.get(row, "Identified Source"))
            ),
        }
    )
    return parsed


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")


def get_or_create_city(
    db: Session,
    project_id: int,
    name: str,
    region: str | None = None,
    country: str = "Indonesia",
    created_by: str | None = None,
) -> City:
    slug = slugify(name)
    if not slug:
        raise ValueError("City name is required")
    city = db.scalar(select(City).where(City.project_id == project_id, City.slug == slug))
    if city is None:
        city = City(
            project_id=project_id,
            name=name.strip(),
            slug=slug,
            region=(region or "").strip() or None,
            country=country or "Indonesia",
            source_files=[],
            created_by_email=created_by,
        )
        db.add(city)
        db.flush()
    elif region and not city.region:
        city.region = region.strip()
    return city


def _dedupe_key(record_fields: dict[str, Any]) -> tuple[str, str]:
    """Identify a business within a city so re-uploads append instead of duplicating."""
    place_id = (record_fields.get("provider_place_id") or "").strip().lower()
    if place_id:
        return ("place", place_id)
    name = (record_fields.get("business_name") or "").strip().lower()
    address = (record_fields.get("address") or "").strip().lower()
    return ("name", f"{name}|{address}")


def append_rows(
    db: Session,
    project_id: int,
    city: City,
    rows: list[tuple[Any, ...]],
    file_name: str,
    columns: Columns | None = None,
) -> dict[str, int]:
    """Append workbook rows to a city, skipping businesses already loaded.

    Discovery columns on an existing business are refreshed; validation answers
    already saved through the UI are never overwritten.
    """
    existing = list(
        db.scalars(
            select(ValidationRecord).where(
                ValidationRecord.project_id == project_id, ValidationRecord.city_id == city.id
            )
        )
    )
    by_key = {_dedupe_key({f["key"]: getattr(r, f["key"]) for f in SOURCE_FIELDS}): r for r in existing}
    next_row = max((r.source_row for r in existing), default=1)

    added = refreshed = skipped = 0
    for row in rows:
        parsed = parse_row(row, columns)
        if parsed is None:
            skipped += 1
            continue
        key = _dedupe_key(parsed)
        record = by_key.get(key)
        if record is None:
            next_row += 1
            record = ValidationRecord(
                project_id=project_id, city_id=city.id, source_row=next_row, source_file=file_name
            )
            for field, value in parsed.items():
                setattr(record, field, value)
            record.evidence_method = record.evidence_method or "NOT_PROBED"
            record.validation_status = compute_status(record)
            db.add(record)
            by_key[key] = record
            added += 1
        else:
            for field in SOURCE_FIELDS:
                name = field["key"]
                value = parsed[name]
                # Never erase known discovery data with an unstated cell.
                if value in (None, "") and getattr(record, name) not in (None, ""):
                    continue
                setattr(record, name, value)
            record.evidence_method = record.evidence_method or "NOT_PROBED"
            record.source_file = file_name
            refreshed += 1

    files = list(city.source_files or [])
    if file_name not in files:
        city.source_files = files + [file_name]
    db.flush()
    return {"added": added, "refreshed": refreshed, "skipped": skipped}


# The workbook that shipped with the demo has no city in its name.
BUNDLED_WORKBOOK = "Ssample-2.xlsx"


def find_workbooks() -> list[Path]:
    if not WORKBOOK_DIR.is_dir():
        return []
    return sorted(p for p in WORKBOOK_DIR.glob("*.xlsx") if not p.name.startswith("~$"))


def find_workbook() -> Path | None:
    """The bundled Denpasar workbook, if it is present."""
    for path in find_workbooks():
        if path.name == BUNDLED_WORKBOOK:
            return path
    return None


def city_for_workbook(path: Path) -> tuple[str, str | None]:
    """Which city a validation workbook belongs to, from its file name.

    "Jakarta_data.xlsx" -> Jakarta. The bundled demo file and its revisions
    ("Ssample-2_8992.xlsx") have no city in the name and describe Denpasar.
    """
    if path.stem.lower().startswith("ssample"):
        return DEFAULT_CITY["name"], DEFAULT_CITY["region"]
    stem = re.split(r"[_\-]", path.stem)[0].strip()
    return (stem or DEFAULT_CITY["name"]), None


def replace_rows(
    db: Session,
    project_id: int,
    city: City,
    rows: list[tuple[Any, ...]],
    file_name: str,
    columns: Columns | None = None,
) -> dict[str, Any]:
    """Make a city's validation rows match one workbook exactly.

    Businesses missing from the workbook are dropped. Discovery columns the
    workbook leaves unstated keep the value already held, so a placeholder in
    the source does not erase how a place was found.
    """
    existing = list(
        db.scalars(
            select(ValidationRecord).where(
                ValidationRecord.project_id == project_id, ValidationRecord.city_id == city.id
            )
        )
    )
    by_key = {_dedupe_key({f["key"]: getattr(r, f["key"]) for f in SOURCE_FIELDS}): r for r in existing}

    seen: set[tuple[str, str]] = set()
    added = refreshed = skipped = kept_evidence = 0
    # Existing rows keep their source_row; renumbering them would collide with
    # the (project, city, source_row) constraint part way through the flush.
    next_row = max((r.source_row for r in existing), default=1)

    for row in rows:
        parsed = parse_row(row, columns)
        if parsed is None:
            skipped += 1
            continue
        key = _dedupe_key(parsed)
        if key in seen:
            skipped += 1
            continue
        seen.add(key)

        record = by_key.get(key)
        if record is None:
            next_row += 1
            record = ValidationRecord(project_id=project_id, city_id=city.id, source_row=next_row)
            db.add(record)
            added += 1
        else:
            refreshed += 1
        record.source_file = file_name

        for field in SOURCE_FIELDS:
            name = field["key"]
            value = parsed[name]
            if value in (None, "") and getattr(record, name) not in (None, ""):
                kept_evidence += 1   # workbook is silent here; keep what we know
                continue
            setattr(record, name, value)
        for name in EDITABLE_KEYS:
            if name in parsed:
                setattr(record, name, parsed[name])
        if not record.evidence_method:
            record.evidence_method = "NOT_PROBED"
        record.validation_status = compute_status(record)

    removed = 0
    for key, record in by_key.items():
        if key not in seen:
            db.delete(record)
            removed += 1

    city.source_files = [file_name]
    db.flush()
    return {
        "added": added,
        "refreshed": refreshed,
        "removed": removed,
        "skipped": skipped,
        "kept_evidence": kept_evidence,
    }


def import_validation_folder(db: Session, project_id: int) -> list[dict[str, Any]]:
    """Load the validation workbooks in backend/misseddata, one city each.

    When a city has several workbooks the most recently modified one wins and
    replaces that city's rows, so dropping in a revised file updates the city
    rather than merging two versions of it.
    """
    by_city: dict[str, list[Path]] = {}
    for path in find_workbooks():
        by_city.setdefault(city_for_workbook(path)[0], []).append(path)

    results = []
    for name, paths in by_city.items():
        # Oldest first so a revision lands on top of the context it inherits,
        # then the newest file decides the final row set and answers.
        ordered = sorted(paths, key=lambda p: p.stat().st_mtime)
        chosen = ordered[-1]
        region = city_for_workbook(chosen)[1]
        city = get_or_create_city(db, project_id, name, region, DEFAULT_CITY["country"])

        for earlier in ordered[:-1]:
            columns, rows = read_rows(earlier)
            append_rows(db, project_id, city, rows, earlier.name, columns)
        columns, rows = read_rows(chosen)
        result = replace_rows(db, project_id, city, rows, chosen.name, columns)
        db.commit()
        results.append(
            {
                **result,
                "workbook": chosen.name,
                "superseded": [p.name for p in ordered[:-1]],
                "city": city.name,
                "city_id": city.id,
            }
        )
    return results


def read_rows(source: Any) -> tuple[Columns, list[tuple[Any, ...]]]:
    """Header map and data rows of the first sheet of a workbook."""
    import openpyxl

    book = openpyxl.load_workbook(source, data_only=True, read_only=True)
    sheet = book[book.sheetnames[0]]
    rows = list(sheet.iter_rows(values_only=True))
    book.close()
    if not rows:
        return Columns(), []
    return Columns(rows[0]), [r for r in rows[1:] if any(c is not None for c in r)]


def import_workbook(db: Session, project_id: int, workbook: Path | None = None) -> dict[str, Any]:
    """Load the bundled misseddata workbook as the default Denpasar city."""
    path = workbook or find_workbook()
    if path is None:
        return {"added": 0, "refreshed": 0, "workbook": None, "city": None}

    city = get_or_create_city(db, project_id, DEFAULT_CITY["name"], DEFAULT_CITY["region"], DEFAULT_CITY["country"])
    columns, rows = read_rows(path)
    result = append_rows(db, project_id, city, rows, path.name, columns)
    db.commit()
    return {**result, "workbook": path.name, "city": city.name, "city_id": city.id}
