from collections import Counter
from typing import Iterable

from ..models import ComparisonBucket, GoogleStatus, PoiCandidate, QaStatus, QualityTier


def pct(numerator: int, denominator: int) -> float:
    return round((numerator / denominator * 100), 2) if denominator else 0.0


def calculate_kpis(candidates: Iterable[PoiCandidate]) -> dict:
    rows = list(candidates)
    b_rows = [r for r in rows if r.google_status == GoogleStatus.GOOGLE_PRESENT_CONFIRMED]
    c_rows = [r for r in rows if r.google_status == GoogleStatus.GOOGLE_ABSENT_VERIFIED]
    i_rows = [r for r in rows if r.google_status in {
        GoogleStatus.GOOGLE_CHECK_PENDING,
        GoogleStatus.GOOGLE_POSSIBLE_MATCH,
        GoogleStatus.GOOGLE_CHECK_INCONCLUSIVE,
    }]
    a = len(b_rows) + len(c_rows) + len(i_rows)
    d_rows = [r for r in c_rows if r.usability_eligible]
    qa_reviewed = [r for r in rows if r.qa_status in {QaStatus.PASSED, QaStatus.REWORK, QaStatus.REJECTED}]

    def grouped(field: str):
        counter = Counter((getattr(r, field) or "Unknown") for r in rows)
        return [{"name": getattr(k, "value", str(k)), "count": v} for k, v in sorted(counter.items(), key=lambda x: (-x[1], str(x[0])))]

    release_ready = [r for r in rows if r.release_approved]
    result = {
        "A_total": a,
        "B_google_present": len(b_rows),
        "C_google_absent_verified": len(c_rows),
        "D_usable_non_google": len(d_rows),
        "E_instagram_on_D": sum(bool(r.instagram) for r in d_rows),
        "F_tiktok_on_D": sum(bool(r.tiktok) for r in d_rows),
        "G_facebook_on_D": sum(bool(r.facebook) for r in d_rows),
        "H_whatsapp_on_D": sum(bool(r.whatsapp or r.whatsapp_business) for r in d_rows),
        "I_inconclusive_or_pending": len(i_rows),
        "incremental_usable_ratio": pct(len(d_rows), a),
        "google_coverage_ratio": pct(len(b_rows), a),
        "verified_gap_ratio": pct(len(c_rows), a),
        "usability_rate_of_gaps": pct(len(d_rows), len(c_rows)),
        "gold_quality_ratio": pct(sum(r.quality_tier == QualityTier.GOLD for r in d_rows), len(d_rows)),
        "coordinate_precision_coverage": pct(sum(r.latitude is not None and r.longitude is not None and (r.coordinate_precision or "").upper() not in {"", "UNKNOWN", "CITY_CENTROID", "NEIGHBOURHOOD_CENTROID"} for r in rows), a),
        "contactability_coverage": pct(sum(any([r.phone, r.whatsapp, r.website, r.booking_url, r.instagram, r.facebook, r.tiktok]) for r in rows), a),
        "qa_pass_rate": pct(sum(r.qa_status == QaStatus.PASSED for r in qa_reviewed), len(qa_reviewed)),
        "release_ready_count": len(release_ready),
        "comparison_common": sum(r.comparison_bucket == ComparisonBucket.COMMON for r in rows),
        "comparison_source_only": sum(r.comparison_bucket in {ComparisonBucket.SOURCE_ONLY, ComparisonBucket.VERIFIED_NON_GOOGLE} for r in rows),
        "comparison_baseline_only": sum(r.comparison_bucket == ComparisonBucket.BASELINE_ONLY for r in rows),
        "comparison_possible": sum(r.comparison_bucket == ComparisonBucket.POSSIBLE_MATCH for r in rows),
        "invariant_a_equals_b_plus_c_plus_i": a == len(b_rows) + len(c_rows) + len(i_rows),
        "invariant_d_subset_c": all(r.google_status == GoogleStatus.GOOGLE_ABSENT_VERIFIED for r in d_rows),
        "invariant_release_requires_qa": all(r.qa_status == QaStatus.PASSED and r.usability_eligible and not r.is_demo for r in release_ready),
        "by_city": grouped("city"),
        "by_source": grouped("source_name"),
        "by_google_status": grouped("google_status"),
        "by_quality_tier": grouped("quality_tier"),
        "by_qa_status": grouped("qa_status"),
        "by_comparison_bucket": grouped("comparison_bucket"),
    }
    return result
