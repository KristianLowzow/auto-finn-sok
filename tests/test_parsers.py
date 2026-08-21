import os

import pytest

from src import parsers

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _read(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()


def test_parse_search_results_extracts_listings():
    html = _read("search_page_sample.html")
    results = parsers.parse_search_results(html)

    assert len(results) > 0
    first = results[0]
    assert first["finn_id"].isdigit()
    assert first["merke"]
    assert first["modell"]
    assert first["pris"] > 0
    assert first["url"].startswith("https://www.finn.no/mobility/item/")


def test_parse_search_results_raises_on_missing_block():
    with pytest.raises(parsers.SchemaDriftError):
        parsers.parse_search_results("<html><body>ingen data her</body></html>")


def test_parse_total_results():
    html = _read("search_page_sample.html")
    total = parsers.parse_total_results(html)
    assert total is not None
    assert total > 0


def test_parse_ad_detail_extracts_key_facts():
    html = _read("ad_page_sample.html")
    detail = parsers.parse_ad_detail(html)

    assert detail["finn_id"].isdigit()
    assert detail["merke"]
    assert detail["modell"]
    assert detail["pris"] > 0
    assert detail["aarsmodell"] is not None
    assert detail["kilometerstand"] is not None
    assert detail["girkasse"]
    assert detail["drivstoff"]


def test_parse_ad_detail_raises_when_price_missing():
    html = "<html><body><script type=\"application/ld+json\">{}</script></body></html>"
    with pytest.raises(parsers.SchemaDriftError):
        parsers.parse_ad_detail(html, finn_id="123", url="https://www.finn.no/mobility/item/123")


def test_finn_id_from_url():
    assert parsers.finn_id_from_url("https://www.finn.no/mobility/item/474152630") == "474152630"
    assert parsers.finn_id_from_url("https://www.finn.no/other/path") is None
