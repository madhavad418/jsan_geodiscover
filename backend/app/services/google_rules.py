from __future__ import annotations

from typing import Any

MANDATORY_GOOGLE_CHECKS = [
    "EXACT_NAME",
    "NAME_PLUS_CITY",
    "NAME_PLUS_LOCALITY",
    "FULL_ADDRESS",
    "ALTERNATE_SPELLING",
    "NORMALIZED_NAME",
    "PHONE_NUMBER",
    "WHATSAPP_NUMBER",
    "WEBSITE_DOMAIN",
    "COORDINATE_SEARCH",
    "NEARBY_SALON_SEARCH",
    "BRANCH_CHECK",
    "RENAMED_BUSINESS_CHECK",
    "MOVED_LOCATION_CHECK",
    "CLOSED_BUSINESS_CHECK",
    "DUPLICATE_MERGED_LISTING_CHECK",
]

MATCH_RESULTS = {"MATCH_FOUND", "POSSIBLE_MATCH"}


def validate_absence_checklist(checklist: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    failures: list[str] = []
    by_type = {str(item.get("check_type", "")).upper(): item for item in checklist}
    missing = [check for check in MANDATORY_GOOGLE_CHECKS if check not in by_type]
    if missing:
        failures.append("Missing checks: " + ", ".join(missing))
    incomplete = [
        check for check in MANDATORY_GOOGLE_CHECKS
        if check in by_type and not bool(by_type[check].get("completed"))
    ]
    if incomplete:
        failures.append("Incomplete checks: " + ", ".join(incomplete))
    matches = [
        check for check in MANDATORY_GOOGLE_CHECKS
        if check in by_type and str(by_type[check].get("result", "")).upper() in MATCH_RESULTS
    ]
    if matches:
        failures.append("Potential Google matches remain: " + ", ".join(matches))
    no_query = [
        check for check in MANDATORY_GOOGLE_CHECKS
        if check in by_type and check not in {"BRANCH_CHECK", "RENAMED_BUSINESS_CHECK", "MOVED_LOCATION_CHECK", "CLOSED_BUSINESS_CHECK", "DUPLICATE_MERGED_LISTING_CHECK"}
        and not str(by_type[check].get("query", "")).strip()
    ]
    if no_query:
        failures.append("Search query missing for: " + ", ".join(no_query))
    return not failures, failures
