"""Web-evidence providers for the bulk scraping layer.

Scope: Fresha, Instagram, Facebook and WhatsApp only.

Everything starts from Fresha. Its sitemap is published for crawlers, so venues
can be matched from a business name and address, and the matched venue page
(robots.txt only disallows /search) carries the venue's own phone number and any
social links the venue chose to publish. Instagram and Facebook are filled from
those published links - never from guessed handles - because:

  * facebook.com/robots.txt is "Disallow: /" for every crawler.
  * instagram.com serves a JavaScript shell to logged-out clients and returns
    HTTP 200 for handles that do not exist, so a guessed handle cannot be
    verified and would be a fabrication.

A column is only written when a provider actually proved a value. Otherwise it
stays empty and the reason is recorded against the row.
"""

from __future__ import annotations

import re
import time
import urllib.robotparser
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from rapidfuzz import fuzz

from ..config import get_settings

settings = get_settings()

USER_AGENT = "JSAN-GeoDiscover-Validator/5.0 (+https://jsanconsulting.com; contact admin@jsanconsulting.com)"
REQUEST_TIMEOUT = 25.0
POLITE_DELAY_S = 0.6
FRESHA_SITEMAP = "https://sitemaps.fresha.com/www/sitemap-salons.xml"

# Provider outcome codes surfaced in the UI.
OK = "OK"
NOT_FOUND = "NOT_FOUND"
BLOCKED = "BLOCKED_BY_SITE"
UNREACHABLE = "UNREACHABLE"
ROBOTS_DISALLOWED = "ROBOTS_DISALLOWED"
ERROR = "ERROR"

# Words that carry no identifying signal when matching a salon name.
GENERIC_TOKENS = {
    "salon", "spa", "beauty", "hair", "barbershop", "barber", "studio", "clinic",
    "kecantikan", "rambut", "cantik", "dan", "and", "the", "for", "nail", "nails",
    "make", "up", "muslimah", "keluarga", "family", "care", "house", "home",
}

# Address words common to nearly every Indonesian address, so no geographic signal.
ADDRESS_NOISE = {
    "jalan", "jln", "gang", "gg", "no", "kota", "kec", "kel", "kabupaten",
    "raya", "blok", "utara", "selatan", "timur", "barat", "indonesia", "bali",
}

# Fresha's own corporate accounts appear in the footer of every venue page and
# must never be recorded as a venue's social presence.
PLATFORM_HANDLES = {
    "fresha", "teamfresha", "freshaapp", "fresha_official", "shedul", "instagram",
    "facebook", "tiktok", "explore", "sharer", "profile.php", "pages", "home",
}


@dataclass
class ProviderResult:
    """What one provider concluded for one business."""

    status: str
    values: dict[str, Any] = field(default_factory=dict)
    note: str = ""
    source_url: str | None = None


def _tokens(text: str) -> list[str]:
    words = re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()).split()
    return [w for w in words if len(w) > 2 and w not in GENERIC_TOKENS]


def _location_tokens(address: str) -> list[str]:
    """Place words that tie a listing to this specific neighbourhood."""
    words = re.sub(r"[^a-z0-9 ]", " ", (address or "").lower()).split()
    return [w for w in words if len(w) > 3 and w not in ADDRESS_NOISE and not w.isdigit()]


def _handle_of(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1].lstrip("@").lower()


class RobotsCache:
    """robots.txt gate. A host is only fetched when it says we may."""

    def __init__(self, client: httpx.Client):
        self._client = client
        self._parsers: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._parsers:
            parser = urllib.robotparser.RobotFileParser()
            try:
                response = self._client.get(urljoin(origin, "/robots.txt"))
                if response.status_code >= 400:
                    parser = None  # No usable robots.txt - treat as permitted.
                else:
                    parser.parse(response.text.splitlines())
            except httpx.HTTPError:
                parser = None
            self._parsers[origin] = parser
        parser = self._parsers[origin]
        if parser is None:
            return True
        return parser.can_fetch(USER_AGENT, url)


class ScrapeContext:
    """Shared HTTP client, robots gate and caches for one job."""

    def __init__(self) -> None:
        self.client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "id,en;q=0.8"},
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
        )
        self.robots = RobotsCache(self.client)
        self._fresha_index: dict[str, str] | None = None
        self._last_request = 0.0

    def close(self) -> None:
        self.client.close()

    def pace(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < POLITE_DELAY_S:
            time.sleep(POLITE_DELAY_S - elapsed)
        self._last_request = time.monotonic()

    def fetch(self, url: str) -> httpx.Response | None:
        """Robots-checked GET. Returns None when disallowed or unreachable."""
        if not self.robots.allowed(url):
            return None
        self.pace()
        try:
            return self.client.get(url)
        except httpx.HTTPError:
            return None

    def fresha_index(self) -> dict[str, str]:
        """Slug -> venue URL, built once per job from Fresha's published sitemap."""
        if self._fresha_index is not None:
            return self._fresha_index
        index: dict[str, str] = {}
        try:
            root = self.client.get(FRESHA_SITEMAP, timeout=60)
            for child in re.findall(r"<loc>(.*?)</loc>", root.text):
                page = self.client.get(child, timeout=60)
                for url in re.findall(r"<loc>(.*?)</loc>", page.text):
                    slug = url.rsplit("/a/", 1)[-1]
                    index[slug.rsplit("-", 1)[0].replace("-", " ")] = url
        except httpx.HTTPError:
            pass
        self._fresha_index = index
        return index


# --------------------------------------------------------------------------
# Providers
# --------------------------------------------------------------------------

def fresha_provider(ctx: ScrapeContext, name: str, address: str) -> ProviderResult:
    """Match the business against Fresha's published salon sitemap."""
    index = ctx.fresha_index()
    if not index:
        return ProviderResult(UNREACHABLE, note="Fresha sitemap could not be read")
    wanted = _tokens(name)
    if not wanted:
        return ProviderResult(NOT_FOUND, note="Business name has no distinctive words to match on")
    places = _location_tokens(address)
    best_url, best_score = None, 0.0
    for slug, url in index.items():
        words = set(slug.split())
        # Every distinctive name word must appear as a whole word, and the venue
        # must sit in the same neighbourhood - otherwise a same-named salon on
        # the other side of the world would be recorded as a match.
        if not all(token in words for token in wanted):
            continue
        if places and not any(place in words for place in places):
            continue
        score = fuzz.token_set_ratio(" ".join(wanted), slug)
        if score > best_score:
            best_url, best_score = url, score
    if best_url and best_score >= 60:
        return ProviderResult(
            OK, {"fresha": "YES", "fresha_link": best_url},
            f"Sitemap match at {best_score:.0f}% in the same locality", best_url,
        )
    return ProviderResult(NOT_FOUND, note=f"Not listed among {len(index)} Fresha venues")


def _indonesian_mobile(digits: str) -> str | None:
    """Normalise an Indonesian mobile number to its wa.me form, or reject it."""
    digits = re.sub(r"\D", "", digits)
    if digits.startswith("0"):
        digits = "62" + digits[1:]
    if not digits.startswith("62") or not 10 <= len(digits) <= 15:
        return None
    # Indonesian mobile numbers - and therefore WhatsApp accounts - start 62 8xx.
    return digits if digits[2] == "8" else None


def fresha_venue_provider(ctx: ScrapeContext, venue_url: str | None) -> ProviderResult:
    """Read the matched Fresha venue page for the venue's own contact and socials."""
    if not venue_url:
        return ProviderResult(NOT_FOUND, note="No Fresha venue matched, so there is no page to read")
    if not ctx.robots.allowed(venue_url):
        return ProviderResult(ROBOTS_DISALLOWED, note="Fresha robots.txt disallows this page")
    response = ctx.fetch(venue_url)
    if response is None:
        return ProviderResult(UNREACHABLE, note="Fresha venue page did not respond")
    if response.status_code >= 400:
        return ProviderResult(ERROR, note=f"Fresha venue page returned {response.status_code}")

    body = response.text
    values: dict[str, Any] = {}

    # The venue's own number is embedded as "telephone" / "contactNumber".
    phone_match = re.search(r'"(?:telephone|contactNumber)"\s*:\s*"([^"]{6,30})"', body)
    if phone_match:
        phone = phone_match.group(1).strip()
        values["identified_contact_number"] = phone
        values["identified_source"] = "Fresha venue page"
        mobile = _indonesian_mobile(phone)
        if mobile:
            values["whatsapp"] = f"https://wa.me/{mobile}"

    # Social links the venue published - Fresha's own accounts are excluded.
    for key, pattern in (
        ("instagram", r"https?://(?:www\.)?instagram\.com/([A-Za-z0-9._]+)"),
        ("facebook", r"https?://(?:www\.|m\.)?facebook\.com/([A-Za-z0-9._]+)"),
        ("tiktok", r"https?://(?:www\.)?tiktok\.com/@([A-Za-z0-9._]+)"),
    ):
        for handle in re.findall(pattern, body):
            if handle.lower() in PLATFORM_HANDLES:
                continue
            host = {"instagram": "instagram.com", "facebook": "facebook.com", "tiktok": "tiktok.com/@"}[key]
            values[key] = f"https://www.{host}{'' if key == 'tiktok' else '/'}{handle}"
            break

    if not values:
        return ProviderResult(NOT_FOUND, note="Venue page published no contact number or social links")
    return ProviderResult(OK, values, f"Read {len(values)} detail(s) from the Fresha venue page", venue_url)


def instagram_provider(ctx: ScrapeContext, discovered: str | None) -> ProviderResult:
    """Instagram is only recorded when the venue itself published the link.

    A logged-out request to instagram.com returns a JavaScript shell and answers
    HTTP 200 even for handles that do not exist, so a guessed handle cannot be
    confirmed and is never written.
    """
    if discovered:
        return ProviderResult(OK, {"instagram": discovered}, "Handle published on the venue's Fresha page", discovered)
    return ProviderResult(
        NOT_FOUND,
        note="No Instagram link published for this business. Instagram serves a "
             "logged-out shell that returns 200 for any handle, so a guessed one cannot be verified.",
    )


def facebook_provider(ctx: ScrapeContext, discovered: str | None) -> ProviderResult:
    """Facebook forbids crawling outright, so only published links are recorded."""
    if discovered:
        return ProviderResult(OK, {"facebook": discovered}, "Page link published on the venue's Fresha page", discovered)
    if not ctx.robots.allowed("https://www.facebook.com/"):
        return ProviderResult(
            ROBOTS_DISALLOWED,
            note="facebook.com/robots.txt is 'Disallow: /' for all crawlers, so Facebook is never searched directly.",
        )
    return ProviderResult(NOT_FOUND, note="No Facebook link published for this business")


def whatsapp_provider(ctx: ScrapeContext, whatsapp: str | None, phone: str | None) -> ProviderResult:
    """WhatsApp is derived from a discovered Indonesian mobile number."""
    if whatsapp:
        return ProviderResult(OK, {"whatsapp": whatsapp}, f"Derived from the venue's number {phone or ''}".strip(), whatsapp)
    if phone:
        return ProviderResult(NOT_FOUND, note=f"Number {phone} is not an Indonesian mobile (62 8xx), so it is not a WhatsApp account")
    return ProviderResult(NOT_FOUND, note="No contact number discovered to derive a WhatsApp link from")


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

PROVIDER_LABELS = {
    "fresha": "Fresha listing",
    "fresha_venue": "Fresha venue page (contact & socials)",
    "instagram": "Instagram",
    "facebook": "Facebook",
    "whatsapp": "WhatsApp",
}


def probe_sources() -> dict[str, Any]:
    """What each provider can do right now, before any job is started."""
    ctx = ScrapeContext()
    report: dict[str, Any] = {}
    try:
        index = ctx.fresha_index()
        if index:
            report["fresha"] = {"status": OK, "note": f"{len(index)} venues indexed from the published sitemap"}
            report["fresha_venue"] = {"status": OK, "note": "Venue pages are readable; robots.txt only disallows /search"}
        else:
            report["fresha"] = {"status": UNREACHABLE, "note": "Fresha sitemap could not be read"}
            report["fresha_venue"] = {"status": UNREACHABLE, "note": "Depends on the Fresha sitemap"}
        report["instagram"] = {
            "status": OK,
            "note": "Filled from links the venue publishes. Direct lookup is not possible: logged-out "
                    "instagram.com returns 200 for any handle, so a guess cannot be verified.",
        }
        report["facebook"] = {
            "status": ROBOTS_DISALLOWED if not ctx.robots.allowed("https://www.facebook.com/") else OK,
            "note": "facebook.com/robots.txt is 'Disallow: /' for all crawlers. Only links published by the venue are recorded.",
        }
        report["whatsapp"] = {"status": OK, "note": "Derived from an Indonesian mobile number (62 8xx) found for the business"}
    finally:
        ctx.close()
    for key, entry in report.items():
        entry["label"] = PROVIDER_LABELS[key]
    return report


def scrape_business(ctx: ScrapeContext, name: str, address: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run every provider for one business.

    Returns the values to write and a per-provider findings report. Only keys a
    provider actually proved appear in the values dict.
    """
    findings: dict[str, Any] = {}
    values: dict[str, Any] = {}

    def record(key: str, result: ProviderResult) -> None:
        findings[key] = {
            "label": PROVIDER_LABELS[key],
            "status": result.status,
            "note": result.note,
            "source_url": result.source_url,
        }
        if result.status == OK:
            for field_key, value in result.values.items():
                if value not in (None, "") and field_key not in values:
                    values[field_key] = value

    record("fresha", fresha_provider(ctx, name, address))
    record("fresha_venue", fresha_venue_provider(ctx, values.get("fresha_link")))
    # Instagram, Facebook and WhatsApp report on what the venue page yielded.
    record("instagram", instagram_provider(ctx, values.get("instagram")))
    record("facebook", facebook_provider(ctx, values.get("facebook")))
    record("whatsapp", whatsapp_provider(ctx, values.get("whatsapp"), values.get("identified_contact_number")))

    # A YES answer is only kept when its supporting link came with it.
    if values.get("fresha") == "YES" and not values.get("fresha_link"):
        values.pop("fresha", None)
    return values, findings
