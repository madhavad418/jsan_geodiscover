"""Import a full Grab-vs-Google benchmark export for a city.

These workbooks are a different shape from the misseddata file: one sheet per
comparison outcome, plus an Executive Summary of authoritative metrics.

    Executive Summary      metric/value pairs and the discovery run table
    Grab Only (verified)   Grab places verified as absent from Google
    Google Only (verified) Google places verified as absent from Grab
    Matched                scored pairs accepted as the same business
    Possible Matches       scored pairs held for manual review
    Unresolved             places with no probe evidence either way

Candidate rows land in validation_records so the same city feeds the executive
views, the validation layer and scraping. Scored pairs land in city_matches.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import City, CityCandidate, CityMatch
from .validation_layer import get_or_create_city

WORKBOOK_DIR = Path(__file__).parents[2] / "other_cities"

SHEET_SUMMARY = "Executive Summary"
SHEET_GRAB_ONLY = "Grab Only (verified)"
SHEET_GOOGLE_ONLY = "Google Only (verified)"
SHEET_MATCHED = "Matched"
SHEET_POSSIBLE = "Possible Matches"
SHEET_UNRESOLVED = "Unresolved"

REQUIRED_SHEETS = {SHEET_SUMMARY, SHEET_GRAB_ONLY, SHEET_GOOGLE_ONLY, SHEET_MATCHED}

# A place can appear in several sheets, so the strongest outcome wins. The
# "verified" sheets are settled conclusions and outrank Possible Matches, which
# is a list of candidate pairings - a place can be proposed as a possible pair
# and still be verified afterwards as unique to its provider.
ROLE_PRECEDENCE = {"MATCHED": 0, "INCREMENTAL": 1, "GOOGLE_ONLY": 1, "POSSIBLE": 2, "UNRESOLVED": 3}

TIER_BY_METHOD = {"PROBE": "TIER_1_DIRECT_PROBE", "AREA_COVERAGE": "TIER_2_AREA_SUPPORTED"}


def cell(row: tuple[Any, ...], index: int) -> Any:
    """Sheets vary in width between exports, so index defensively."""
    return row[index] if index < len(row) else None


def _norm(header: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(header or "").strip().lower()).strip("_")


class Columns:
    """Read a row by column name.

    Exports are not identical: Surabaya's "Grab Only" sheet omits Business
    Status, which shifts every later column. Looking columns up by header keeps
    the import correct whatever the layout.
    """

    def __init__(self, header: tuple[Any, ...]):
        self._index = {_norm(name): position for position, name in enumerate(header) if name is not None}

    def has(self, *names: str) -> bool:
        return any(_norm(n) in self._index for n in names)

    def get(self, row: tuple[Any, ...], *names: str) -> Any:
        for name in names:
            position = self._index.get(_norm(name))
            if position is not None:
                return cell(row, position)
        return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _number(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def is_benchmark_workbook(book: Any) -> bool:
    return REQUIRED_SHEETS.issubset(set(book.sheetnames))


def _read_summary(sheet: Any) -> dict[str, Any]:
    """Metric/value pairs plus the discovery run rows."""
    metrics: dict[str, Any] = {}
    runs: list[dict[str, Any]] = []
    in_runs = False
    for row in sheet.iter_rows(values_only=True):
        cells = [c for c in row if c is not None]
        if not cells:
            continue
        first = str(cells[0]).strip()
        if first == "Discovery runs":
            in_runs = True
            continue
        if in_runs:
            if first == "Run" or len(cells) < 8:
                continue
            runs.append(
                {
                    "provider": _text(cells[1]),
                    "status": _text(cells[2]),
                    "tiles_planned": _int(cells[3]),
                    "tiles_done": _int(cells[4]),
                    "saturated_tiles": _int(cells[5]),
                    "api_calls": _int(cells[6]),
                    "places_kept": _int(cells[7]),
                }
            )
            continue
        if len(cells) >= 2:
            metrics[first] = cells[1]
    return {"metrics": metrics, "runs": runs}


def _candidate_from_row(columns: Columns, row: tuple[Any, ...], role: str) -> dict[str, Any] | None:
    """A row from the Grab Only / Google Only sheets."""
    get = columns.get
    if not _text(get(row, "Provider Place ID")) and not _text(get(row, "Business Name")):
        return None
    method = _text(get(row, "Evidence Method"))
    return {
        "provider": _text(get(row, "Provider")),
        "provider_place_id": _text(get(row, "Provider Place ID")),
        "business_name": _text(get(row, "Business Name")),
        "categories": _text(get(row, "Categories")),
        "address": _text(get(row, "Address")),
        "city": _text(get(row, "City")),
        "province": _text(get(row, "Province")),
        "latitude": _number(get(row, "Latitude")),
        "longitude": _number(get(row, "Longitude")),
        "phone": _text(get(row, "Phone")),
        "website": _text(get(row, "Website")),
        "business_status": _text(get(row, "Business Status")),
        "evidence_method": method,
        "evidence_strength": _text(get(row, "Evidence Strength")),
        "probe_query": _text(get(row, "Probe Query")),
        "result_count": _int(get(row, "Result Count")),
        "best_score": _number(get(row, "Best Score")),
        "evidence_timestamp": _text(get(row, "Evidence Timestamp")),
        "evidence_reason": _text(get(row, "Evidence Reason")),
        "found_by_probe": _text(get(row, "Found By Probe")),
        "role": role,
        # Only Grab-side incremental rows carry a customer tier, matching how the
        # benchmark counts GU_grab_only_probe_verified / _area_verified.
        "customer_tier": TIER_BY_METHOD.get(method or "") if role == "INCREMENTAL" else None,
    }


def _unresolved_candidate(columns: Columns, row: tuple[Any, ...]) -> dict[str, Any] | None:
    get = columns.get
    if not _text(get(row, "Provider Place ID")) and not _text(get(row, "Business Name")):
        return None
    return {
        "provider": _text(get(row, "Provider")),
        "provider_place_id": _text(get(row, "Provider Place ID")),
        "business_name": _text(get(row, "Business Name")),
        "categories": None,
        "address": _text(get(row, "Address")),
        "city": _text(get(row, "City")),
        "province": None,
        "latitude": _number(get(row, "Latitude")),
        "longitude": _number(get(row, "Longitude")),
        "phone": None,
        "website": None,
        "business_status": None,
        "evidence_method": "NOT_PROBED",
        "evidence_strength": None,
        "probe_query": None,
        "result_count": None,
        "best_score": None,
        "evidence_timestamp": None,
        "evidence_reason": _text(get(row, "Why unresolved")),
        "found_by_probe": None,
        "role": "UNRESOLVED",
        "customer_tier": None,
    }


def _pair_candidates(columns: Columns, row: tuple[Any, ...], role: str) -> list[dict[str, Any]]:
    """Both sides of a Matched / Possible Matches row."""
    get = columns.get
    common = {
        "categories": None,
        "province": None,
        "phone": None,
        "business_status": None,
        "evidence_method": "COMPARISON",
        "evidence_strength": _text(get(row, "Method")),
        "probe_query": None,
        "result_count": None,
        "best_score": _number(get(row, "Match Score")),
        "evidence_timestamp": None,
        "evidence_reason": _text(get(row, "Signal Breakdown")),
        "found_by_probe": None,
        "role": role,
        "customer_tier": None,
    }
    out = []
    if _text(get(row, "Grab Place ID")):
        out.append({
            **common,
            "provider": "GRAB",
            "provider_place_id": _text(get(row, "Grab Place ID")),
            "business_name": _text(get(row, "Grab Name")),
            "address": _text(get(row, "Grab Address")),
            "city": _text(get(row, "Grab City")),
            "latitude": _number(get(row, "Grab Lat")),
            "longitude": _number(get(row, "Grab Lng")),
            "website": None,
        })
    if _text(get(row, "Google Place ID")):
        out.append({
            **common,
            "provider": "GOOGLE",
            "provider_place_id": _text(get(row, "Google Place ID")),
            "business_name": _text(get(row, "Google Name")),
            "address": _text(get(row, "Google Address")),
            "city": _text(get(row, "Google City")),
            "latitude": _number(get(row, "Google Lat")),
            "longitude": _number(get(row, "Google Lng")),
            "website": _text(get(row, "Google Website")),
        })
    return out


def _match_record(columns: Columns, row: tuple[Any, ...], kind: str) -> dict[str, Any]:
    get = columns.get
    return {
        "kind": kind,
        "match_score": _number(get(row, "Match Score")),
        "distance_m": _number(get(row, "Distance (m)")),
        "method": _text(get(row, "Method")),
        "grab_place_id": _text(get(row, "Grab Place ID")),
        "grab_name": _text(get(row, "Grab Name")),
        "grab_address": _text(get(row, "Grab Address")),
        "grab_latitude": _number(get(row, "Grab Lat")),
        "grab_longitude": _number(get(row, "Grab Lng")),
        "google_place_id": _text(get(row, "Google Place ID")),
        "google_name": _text(get(row, "Google Name")),
        "google_address": _text(get(row, "Google Address")),
        "google_latitude": _number(get(row, "Google Lat")),
        "google_longitude": _number(get(row, "Google Lng")),
        "signal_breakdown": _text(get(row, "Signal Breakdown")),
    }


def _headline(metrics: dict[str, Any], matched_rows: list, possible_rows: list) -> dict[str, Any]:
    def value(key: str, default: Any = None) -> Any:
        raw = metrics.get(key, default)
        number = _number(raw)
        return number if number is not None else raw

    sweep = sum(1 for r in matched_rows if (_text(r[2]) or "").upper() == "AUTO_SWEEP")
    probe = sum(1 for r in matched_rows if (_text(r[2]) or "").upper() == "PROBE")
    grab_only = value("GU_grab_only_verified", 0) or 0
    return {
        "grab_inventory": value("G_grab_total", 0),
        "google_inventory": value("K_google_total", 0),
        "sweep_matches": sweep,
        "probe_recovered_matches": probe,
        # The export's own figure; the sheet can list more scored pairs than this.
        "total_matched_pairs": value("M_matched", len(matched_rows)),
        "scored_matched_pairs": len(matched_rows),
        "scored_possible_pairs": len(possible_rows),
        "tier1_direct_probe_candidates": value("GU_grab_only_probe_verified", 0),
        "tier2_area_supported_leads": value("GU_grab_only_area_verified", 0),
        "grab_incremental_candidates": grab_only,
        "possible_pairings": len(possible_rows),
        "possible_grab_unique": value("P_grab_possible", 0),
        "possible_google_unique": value("P_google_possible", 0),
        "grab_unresolved": value("U_grab_unresolved", 0),
        "google_unresolved": value("U_google_unresolved", 0),
        "contactability_pct": value("grab_contactability_pct", 0.0),
        "customer_release_ready": 0,
        "google_coverage_gap_pct": value("google_coverage_gap_pct"),
        "grab_coverage_gap_pct": value("grab_coverage_gap_pct"),
        "overlap_jaccard_pct": value("overlap_jaccard_pct"),
        "median_coordinate_delta_m": value("median_coordinate_delta_m"),
        "places_recovered_by_probe": value("places_recovered_by_probe"),
    }


def _coverage(runs: list[dict[str, Any]], metrics: dict[str, Any]) -> dict[str, Any]:
    grab = next((r for r in runs if r["provider"] == "GRAB"), {})
    google = next((r for r in runs if r["provider"] == "GOOGLE"), {})
    statement = (
        f"Controlled {metrics.get('Coverage', 'CORE')} benchmark. Grab completed "
        f"{grab.get('tiles_done', 0)}/{grab.get('tiles_planned', 0)} tiles; Google "
        f"{google.get('status', 'UNKNOWN').replace('_', ' ').lower()} after "
        f"{google.get('tiles_done', 0)}/{google.get('tiles_planned', 0)} tiles. "
        "Counts describe this benchmark window only, not complete city coverage."
    )
    return {
        "grab_status": grab.get("status"),
        "grab_tiles_planned": grab.get("tiles_planned"),
        "grab_tiles_done": grab.get("tiles_done"),
        "grab_api_calls": grab.get("api_calls"),
        "google_status": google.get("status"),
        "google_tiles_planned": google.get("tiles_planned"),
        "google_tiles_done": google.get("tiles_done"),
        "google_saturated_tiles": google.get("saturated_tiles"),
        "google_api_calls": google.get("api_calls"),
        "coverage_statement": statement,
    }


def import_benchmark(
    db: Session,
    project_id: int,
    source: Any,
    file_name: str,
    city_name: str | None = None,
    created_by: str | None = None,
) -> dict[str, Any]:
    """Load one benchmark workbook into a city. Re-running refreshes it in place."""
    import openpyxl

    book = openpyxl.load_workbook(source, data_only=True, read_only=True)
    if not is_benchmark_workbook(book):
        book.close()
        raise ValueError(
            "This workbook is not a Grab-vs-Google benchmark export. Expected sheets: "
            + ", ".join(sorted(REQUIRED_SHEETS))
        )

    summary = _read_summary(book[SHEET_SUMMARY])
    metrics = summary["metrics"]
    name = city_name or _text(metrics.get("City")) or Path(file_name).stem
    region = _text(metrics.get("Province"))

    def sheet(name: str) -> tuple[Columns, list[tuple[Any, ...]]]:
        """Header map plus data rows, so columns are read by name not position."""
        if name not in book.sheetnames:
            return Columns(()), []
        rows = list(book[name].iter_rows(values_only=True))
        if not rows:
            return Columns(()), []
        return Columns(rows[0]), [r for r in rows[1:] if any(c is not None for c in r)]

    grab_cols, grab_only = sheet(SHEET_GRAB_ONLY)
    google_cols, google_only = sheet(SHEET_GOOGLE_ONLY)
    matched_cols, matched = sheet(SHEET_MATCHED)
    possible_cols, possible = sheet(SHEET_POSSIBLE)
    unresolved_cols, unresolved = sheet(SHEET_UNRESOLVED)
    book.close()

    # Collect candidates, keeping the strongest role when a place repeats.
    collected: dict[tuple[str, str], dict[str, Any]] = {}

    def offer(candidate: dict[str, Any] | None) -> None:
        if not candidate or not candidate.get("provider_place_id"):
            return
        key = (candidate["provider"] or "", candidate["provider_place_id"])
        current = collected.get(key)
        if current is None or ROLE_PRECEDENCE[candidate["role"]] < ROLE_PRECEDENCE[current["role"]]:
            collected[key] = candidate

    for row in matched:
        for candidate in _pair_candidates(matched_cols, row, "MATCHED"):
            offer(candidate)
    for row in possible:
        for candidate in _pair_candidates(possible_cols, row, "POSSIBLE"):
            offer(candidate)
    for row in grab_only:
        offer(_candidate_from_row(grab_cols, row, "INCREMENTAL"))
    for row in google_only:
        offer(_candidate_from_row(google_cols, row, "GOOGLE_ONLY"))
    for row in unresolved:
        offer(_unresolved_candidate(unresolved_cols, row))

    city = get_or_create_city(db, project_id, name, region, "Indonesia", created_by)
    city.headline = _headline(metrics, matched, possible)
    # source_files lists the city's validation workbooks, which the validation
    # and scraping views report on. The benchmark export is recorded separately.
    city.coverage = {**_coverage(summary["runs"], metrics), "source_workbook": file_name}
    city.source_files = [f for f in (city.source_files or []) if f != file_name]

    # Benchmark candidates feed the executive views only. The validation layer
    # and scraping read ValidationRecord, loaded from a separate workbook.
    existing = {
        (r.provider or "", r.provider_place_id or ""): r
        for r in db.scalars(select(CityCandidate).where(CityCandidate.city_id == city.id))
    }

    added = refreshed = 0
    for key, candidate in collected.items():
        record = existing.get(key)
        if record is None:
            record = CityCandidate(city_id=city.id)
            db.add(record)
            added += 1
        else:
            refreshed += 1
        for field, value in candidate.items():
            # The model calls the place's own city "city_name" to avoid clashing
            # with the city_id relationship.
            setattr(record, "city_name" if field == "city" else field, value)

    # Comparison pairs are replaced wholesale so a re-import cannot double them.
    for stale in db.scalars(select(CityMatch).where(CityMatch.city_id == city.id)):
        db.delete(stale)
    db.flush()
    for row in matched:
        db.add(CityMatch(city_id=city.id, **_match_record(matched_cols, row, "MATCHED")))
    for row in possible:
        db.add(CityMatch(city_id=city.id, **_match_record(possible_cols, row, "POSSIBLE")))

    # Compare the export's stated metrics against what its sheets actually hold,
    # so a discrepancy is reported rather than silently absorbed.
    roles: dict[str, int] = {}
    for candidate in collected.values():
        roles[candidate["role"]] = roles.get(candidate["role"], 0) + 1
    warnings = []
    for label, stated, actual in (
        ("Grab-only verified", _int(metrics.get("GU_grab_only_verified")), roles.get("INCREMENTAL", 0)),
        ("Google-only verified", _int(metrics.get("KU_google_only_verified")), roles.get("GOOGLE_ONLY", 0)),
        ("matched pairs", _int(metrics.get("M_matched")), len(matched)),
        (
            "unresolved",
            (_int(metrics.get("U_grab_unresolved")) or 0) + (_int(metrics.get("U_google_unresolved")) or 0),
            roles.get("UNRESOLVED", 0),
        ),
    ):
        if stated is not None and stated != actual:
            warnings.append(f"{label}: summary states {stated}, sheets resolve to {actual}")

    db.commit()
    return {
        "city": city.name,
        "city_id": city.id,
        "region": city.region,
        "workbook": file_name,
        "added": added,
        "refreshed": refreshed,
        "candidates": len(collected),
        "matched_pairs": len(matched),
        "possible_pairs": len(possible),
        "roles": roles,
        "warnings": warnings,
    }


def find_workbooks() -> list[Path]:
    if not WORKBOOK_DIR.is_dir():
        return []
    return sorted(p for p in WORKBOOK_DIR.glob("*.xlsx") if not p.name.startswith("~$"))


def import_folder(db: Session, project_id: int, created_by: str | None = None) -> list[dict[str, Any]]:
    """Load every benchmark workbook sitting in backend/other_cities."""
    results = []
    for path in find_workbooks():
        results.append(import_benchmark(db, project_id, path, path.name, created_by=created_by))
    return results
