"""Validation layer: workbook import and the field specification shared by the API and UI.

The misseddata workbooks are hand-finished by validators, so no two are laid out
identically. Three deviations are normalised here so the validation layer always
sees one clean schema:

* Rows that were never probed in the opposite provider can be shifted one column
  left from "Categories" onward (address under Categories, the coordinates under
  City/Province, the evidence reason under Latitude).
* Some exports carry a blank column in front of the evidence block, shifting
  Evidence Method through Evidence Reason one column right and pushing
  "Found By Probe" off the end.
* The source "Website" column is absent from most city files, so the single
  "Website" column they do have is the link the validator captured, not the
  discovery source's own site.
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


def _as_link(value: Any) -> str | None:
    """The value only if it is unmistakably a web address.

    Used on the Yes/No columns, where anything else - "no", a service list, a
    phone number - is not a link and must not be read as one.
    """
    text = str(value or "").strip()
    if text.lower().startswith(("http://", "https://", "www.")):
        return normalise_link(text)
    return None


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


def _reads_as_note(text: str) -> bool:
    """A sentence in a short-value column, such as a reason written under Province."""
    return len(text.split()) >= 5


# The first of the presence checks. Anything to the right of it was filled in by
# a validator rather than by discovery.
CHECK_BLOCK_START = ("Google maps", "Google strret view", "Google street view", "GSV link")

# How the discovery engine describes the way a place was found. Used to locate
# the evidence block in a file that carries a spare column in front of it.
EVIDENCE_METHODS = {"PROBE", "AREA_COVERAGE", "AREA_SWEEP", "COMPARISON", "NOT_PROBED"}


def _evidence_offset(row: tuple[Any, ...], columns: Columns) -> int:
    """How far the evidence block sits from where the header says it does.

    The Medan workbook carries a blank column before Evidence Method, so every
    value from there to Evidence Reason reads one column late. Finding the
    method token keeps the whole block readable whichever layout a file uses.
    Only a later position is considered: a block that appears to sit earlier
    means the header does not describe this row at all, which is the shifted
    row shape and is handled separately.
    """
    base = columns.index("Evidence Method")
    if base is None:
        return 0
    for offset in (0, 1):
        position = base + offset
        value = row[position] if position < len(row) else None
        if str(value or "").strip().upper() in EVIDENCE_METHODS:
            return offset
    return 0


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

    def positions(self, name: str) -> list[int]:
        """Every position carrying this header, for duplicated names."""
        key = _norm(name)
        return [position for position, header in enumerate(self._header) if _norm(header) == key]

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
    # A spreadsheet error such as #VALUE! is a broken coordinate on an otherwise
    # well-formed row, so it must not be read as the shifted layout.
    latitude_at = columns.index("Latitude")
    latitude_at = 7 if latitude_at is None else latitude_at
    raw_latitude = cell(latitude_at)
    aligned = _number(raw_latitude) is not None or str(raw_latitude or "").startswith("#")

    # A workbook with no source Website column still has the validator's own
    # Website link, sitting after the presence checks begin.
    checks_at = columns.index(*CHECK_BLOCK_START)
    website_columns = columns.positions("Website")
    source_website_at = next(
        (p for p in website_columns if checks_at is None or p < checks_at), None
    )
    website_link_at = next(
        (p for p in website_columns if checks_at is not None and p > checks_at), None
    )

    if aligned:
        offset = _evidence_offset(row, columns)

        # Discovery columns describe how a place was found, so a "yes"/"no"
        # placeholder in them is read as "not stated".
        def evidence(*names: str) -> Any:
            value = columns.get(row, *names)
            return None if _is_placeholder(value) else value

        def probe(name: str) -> Any:
            """An evidence column, honouring a blank column inserted before it."""
            position = columns.index(name)
            if position is None:
                return None
            if offset and name == "Found By Probe":
                # The inserted column pushes the block right and this last value
                # off the end of it; the next cell belongs to the checks.
                return None
            value = columns.get_at(row, position + offset)
            return None if _is_placeholder(value) else value

        province = _text(evidence("Province"))
        reason = _text(probe("Evidence Reason"))
        if province and _reads_as_note(province):
            # Unprobed rows in some files carry the evidence note under Province.
            province, reason = None, reason or province

        parsed = {
            "categories": _text(evidence("Categories")),
            "address": _text(evidence("Address")),
            "city": _text(evidence("City")),
            "province": province,
            "latitude": _number(evidence("Latitude")),
            "longitude": _number(evidence("Longitude")),
            # Left unstated here; the caller keeps any method already known and
            # otherwise settles on NOT_PROBED.
            "evidence_method": _text(probe("Evidence Method")),
            "evidence_strength": _text(probe("Evidence Strength")),
            "probe_query": _text(probe("Probe Query")),
            "result_count": _int(probe("Result Count")),
            "best_score": _number(probe("Best Score")),
            "evidence_timestamp": _text(probe("Evidence Timestamp")),
            "evidence_reason": reason,
            "found_by_probe": _text(probe("Found By Probe")),
            # Phone and status are recorded by the validator, where "no" means
            # none was found.
            "phone": _text(evidence("Phone")),
            "website": _text(
                None if _is_placeholder(columns.get_at(row, source_website_at))
                else columns.get_at(row, source_website_at)
            ),
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

    # Presence checks, and the link a validator sometimes pastes into the
    # Yes/No column instead of answering it. A link is an answer of Yes.
    for field in CHECK_FIELDS:
        raw = columns.get(row, field["column"], field["label"])
        link = _as_link(raw)
        parsed[field["key"]] = "YES" if link else normalise_check(raw)
        parsed[field["link_key"]] = link

    # Street View has a link column of its own, which wins over the check cell.
    gsv = normalise_link(columns.get(row, "GSV link"))
    if gsv:
        parsed["gsv_link"] = gsv
        parsed["google_street_view"] = parsed["google_street_view"] or ("YES" if gsv != "Yes" else None)

    parsed.update(
        {
            "provider": _text(cell(0)),
            "provider_place_id": _text(cell(1)),
            "business_name": _text(cell(2)),
            # Validation layer values already present in the workbook.
            "website_link": normalise_link(columns.get_at(row, website_link_at)),
            "services": None if _is_placeholder(columns.get(row, "services")) else _text(columns.get(row, "services")),
            "facebook": normalise_link(columns.get(row, "FB", "Facebook")),
            "instagram": normalise_link(columns.get(row, "Insta", "Instagram")),
            "tiktok": normalise_link(columns.get(row, "TikTok")),
            "whatsapp": normalise_link(columns.get(row, "whats app", "whatsapp")),
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

# Trailing words in a file name that describe the file, not the city.
FILE_DESCRIPTOR_WORDS = {
    "final", "finals", "data", "dataset", "validation", "validated", "missed",
    "misseddata", "missing", "layer", "sheet", "workbook", "export", "updated",
    "update", "new", "latest", "copy", "core", "v1", "v2", "v3", "v4",
}

# The provinces of the cities in the programme, so a city is complete from its
# validation workbook alone. A benchmark export states its own province and
# takes precedence when one is loaded.
KNOWN_REGIONS = {
    "denpasar": "Bali",
    "jakarta": "DKI Jakarta",
    "surabaya": "Jawa Timur",
    "bandung": "Jawa Barat",
    "medan": "Sumatera Utara",
}


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

    "Jakarta_data.xlsx", "Medan Final.xlsx" and "BANDUNG Final.xlsx" all name
    their city first and then describe the file, so the trailing words and any
    date or version number are dropped and the name is cased for display. The
    bundled demo file and its revisions ("Ssample-2_8992.xlsx") have no city in
    the name and describe Denpasar.
    """
    if path.stem.lower().startswith("ssample"):
        return DEFAULT_CITY["name"], DEFAULT_CITY["region"]

    tokens = [token for token in re.split(r"[\s_\-]+", path.stem) if token]
    while len(tokens) > 1 and (tokens[-1].lower() in FILE_DESCRIPTOR_WORDS or tokens[-1].isdigit()):
        tokens.pop()
    name = " ".join(tokens).strip() or DEFAULT_CITY["name"]
    # "BANDUNG" and "surabaya" are the same city as "Bandung"; present one name.
    if name.isupper() or name.islower():
        name = name.title()
    return name, KNOWN_REGIONS.get(slugify(name))


def replace_rows(
    db: Session,
    project_id: int,
    city: City,
    rows: list[tuple[Any, ...]],
    file_name: str,
    columns: Columns | None = None,
) -> dict[str, Any]:
    """Append and refresh a city's validation rows from one workbook.

    This is not a destructive replace: records already in the database that
    are absent from the current workbook are left untouched, so a workbook
    change (or a bundled-file rename) never deletes data. Rows present in the
    workbook are added when new or refreshed when they already exist.
    Discovery columns the workbook leaves unstated keep the value already
    held, so a placeholder in the source does not erase how a place was
    found.
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

    # Note: records not present in the workbook are intentionally left
    # untouched here. replace_rows() no longer deletes anything -- it only
    # appends new rows and refreshes existing ones.

    city.source_files = [file_name]
    db.flush()
    return {
        "added": added,
        "refreshed": refreshed,
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
