from urllib.parse import parse_qs, urlparse

from src.scraper import build_search_url


def test_build_search_url_has_no_price_filter():
    # Maks pris skal kun brukes til å avgjøre om noe er verdt å varsle om --
    # selve søket skal alltid hente hele prisspennet til statistikken.
    url = build_search_url("Skoda", "Enyaq", filters={"max_price": 230000})
    query = parse_qs(urlparse(url).query)

    assert "price_to" not in query


def test_build_search_url_still_applies_year_and_mileage_filters():
    url = build_search_url("Skoda", "Enyaq", filters={"min_year": 2020, "max_year": 2023, "max_km": 50000})
    query = parse_qs(urlparse(url).query)

    assert query["year_from"] == ["2020"]
    assert query["year_to"] == ["2023"]
    assert query["mileage_to"] == ["50000"]


def test_build_search_url_query_combines_brand_and_model():
    url = build_search_url("Skoda", "Enyaq")
    query = parse_qs(urlparse(url).query)

    assert query["q"] == ["Skoda Enyaq"]
