from src.models import Listing
from src.tracker import diff_listings

NOW = "2026-08-21T10:00:00+00:00"


def _listing(finn_id, pris=100000, mangler_siden=""):
    return Listing(finn_id=finn_id, url=f"https://finn.no/{finn_id}", merke="Toyota", modell="Corolla", pris=pris, mangler_siden=mangler_siden)


def test_new_listing_is_returned_as_new_id():
    previous = []
    current = [{"finn_id": "1", "pris": 100000}]

    new_ids, still_active, to_archive = diff_listings(previous, current, NOW)

    assert new_ids == {"1"}
    assert still_active == []
    assert to_archive == []


def test_still_present_listing_updates_price_and_last_seen():
    previous = [_listing("1", pris=100000)]
    current = [{"finn_id": "1", "pris": 95000}]

    new_ids, still_active, to_archive = diff_listings(previous, current, NOW)

    assert new_ids == set()
    assert len(still_active) == 1
    assert still_active[0].pris == 95000
    assert still_active[0].sist_sett == NOW
    assert still_active[0].mangler_siden == ""
    assert to_archive == []


def test_first_miss_is_flagged_but_kept_active():
    previous = [_listing("1")]
    current = []  # forsvunnet fra søket

    new_ids, still_active, to_archive = diff_listings(previous, current, NOW)

    assert new_ids == set()
    assert to_archive == []
    assert len(still_active) == 1
    assert still_active[0].mangler_siden == NOW


def test_second_consecutive_miss_is_archived():
    previous = [_listing("1", mangler_siden="2026-08-21T09:00:00+00:00")]
    current = []  # borte igjen, andre gang på rad

    new_ids, still_active, to_archive = diff_listings(previous, current, NOW)

    assert still_active == []
    assert len(to_archive) == 1
    assert to_archive[0].finn_id == "1"


def test_reappearing_listing_clears_missing_marker():
    previous = [_listing("1", mangler_siden="2026-08-21T09:00:00+00:00")]
    current = [{"finn_id": "1", "pris": 100000}]  # tilbake igjen før arkivering

    new_ids, still_active, to_archive = diff_listings(previous, current, NOW)

    assert to_archive == []
    assert len(still_active) == 1
    assert still_active[0].mangler_siden == ""
