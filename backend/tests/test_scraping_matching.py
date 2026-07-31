"""A same-named business in another city must never be recorded as a match."""

from app.services.scraping import ProviderResult, _location_tokens, _tokens, fresha_provider


class FakeContext:
    """Stands in for ScrapeContext with a fixed Fresha index."""

    def __init__(self, index):
        self._index = index

    def fresha_index(self):
        return self._index


# Slug -> venue URL, in the shape the real sitemap produces.
INDEX = {
    "glo spa salon sanur bali sanur denpasar city jalan danau poso no 57": "https://fresha.test/glo-denpasar",
    "glo bar kenmore 1567 military rd": "https://fresha.test/glo-kenmore",
    "peni weni bali peni weni salon sanur denpasar city jalan sudamala": "https://fresha.test/peni-denpasar",
}


def test_generic_words_are_not_identifying():
    assert _tokens("Beauty Salon Spa") == []
    assert "moonlash" in _tokens("Moonlash Studio")


def test_address_noise_is_dropped():
    places = _location_tokens("Jl. Danau Poso No. 57, Sanur, Denpasar Utara, Bali")
    assert "sanur" in places and "denpasar" in places
    # "jalan"/"bali"/"utara" appear in nearly every address, so they carry no signal.
    for noise in ("jalan", "bali", "utara"):
        assert noise not in places


def test_match_requires_the_same_locality():
    ctx = FakeContext(INDEX)
    result = fresha_provider(ctx, "Glo Spa Salon", "Jalan Danau Poso No. 57, Sanur, Denpasar")
    assert result.status == "OK"
    # The Kenmore venue shares the word "glo" but is on the other side of the world.
    assert result.values["fresha_link"] == "https://fresha.test/glo-denpasar"


def test_no_locality_overlap_is_not_a_match():
    ctx = FakeContext({"glo bar kenmore 1567 military rd": "https://fresha.test/glo-kenmore"})
    result = fresha_provider(ctx, "Glo Spa Salon", "Jalan Danau Poso No. 57, Sanur, Denpasar")
    assert result.status == "NOT_FOUND"


def test_name_with_no_distinctive_words_is_refused():
    ctx = FakeContext(INDEX)
    result = fresha_provider(ctx, "Salon Spa", "Sanur, Denpasar")
    assert result.status == "NOT_FOUND"
    assert "distinctive" in result.note


def test_absent_business_is_not_invented():
    ctx = FakeContext(INDEX)
    assert fresha_provider(ctx, "Nowhere Salon Zzz", "Denpasar").status == "NOT_FOUND"


# --- WhatsApp derivation and social-link hygiene ---------------------------

from app.services.scraping import PROVIDER_LABELS, _indonesian_mobile, facebook_provider, instagram_provider, whatsapp_provider


def test_only_indonesian_mobiles_become_whatsapp_links():
    assert _indonesian_mobile("+62 813-5304-4498") == "6281353044498"
    assert _indonesian_mobile("0813 5304 4498") == "6281353044498"       # local 0 prefix
    assert _indonesian_mobile("+62 361 234567") is None                  # Bali landline, not mobile
    assert _indonesian_mobile("+1 415 555 0100") is None                 # not Indonesian
    assert _indonesian_mobile("") is None


def test_whatsapp_is_never_invented():
    assert whatsapp_provider(None, None, None).status == "NOT_FOUND"
    landline = whatsapp_provider(None, None, "+62 361 234567")
    assert landline.status == "NOT_FOUND" and "not an Indonesian mobile" in landline.note
    ok = whatsapp_provider(None, "https://wa.me/6281353044498", "+62 813-5304-4498")
    assert ok.status == "OK" and ok.values["whatsapp"] == "https://wa.me/6281353044498"


def test_instagram_is_only_recorded_when_published():
    # A guessed handle can never be verified, so nothing is written.
    blank = instagram_provider(None, None)
    assert blank.status == "NOT_FOUND" and blank.values == {}
    found = instagram_provider(None, "https://www.instagram.com/somesalon")
    assert found.status == "OK" and found.values["instagram"].endswith("somesalon")


class NoRobots:
    robots = type("R", (), {"allowed": staticmethod(lambda url: False)})()


def test_facebook_reports_that_crawling_is_disallowed():
    result = facebook_provider(NoRobots(), None)
    assert result.status == "ROBOTS_DISALLOWED" and result.values == {}


def test_removed_providers_are_gone():
    assert set(PROVIDER_LABELS) == {"fresha", "fresha_venue", "instagram", "facebook", "whatsapp"}
