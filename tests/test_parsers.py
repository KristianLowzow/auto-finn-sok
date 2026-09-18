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


def test_parse_ad_detail_extracts_wltp_range_for_electric_car():
    # Rekkevidde-feltet har en skjult forklaringstekst limt rett inn i <dt>-teksten
    # uten mellomrom ("Rekkevidde (WLTP)WLTP er et måltall...") -- må matches på prefiks.
    html = _read("ad_page_ev_sample.html")
    detail = parsers.parse_ad_detail(html)

    assert detail["drivstoff"] == "El"
    assert detail["rekkevidde_wltp"] == 468


def test_parse_ad_detail_range_is_none_when_field_absent():
    # Denne annonsen (en varebil) har ikke Rekkevidde i nøkkelinfo-listen sin.
    html = _read("ad_page_sample.html")
    detail = parsers.parse_ad_detail(html)

    assert detail["rekkevidde_wltp"] is None


def test_parse_ad_detail_extracts_equipment_features_and_wheel_drive():
    html = _read("ad_page_ev_sample.html")
    detail = parsers.parse_ad_detail(html)

    assert detail["hjuldrift"] == "Firehjulsdrift"
    assert "Varmepumpe" in detail["utstyrspakke"]
    assert detail["varmepumpe"] == "Ja"
    assert detail["head_up_display"] == "Ja"
    assert detail["oppvarmet_ratt"] == "Ja"
    assert detail["oppvarmede_seter_foran"] == "Ja"
    assert detail["oppvarmede_seter_bak"] == "Nei"  # kun foran er utstyrt på denne bilen
    assert detail["tradlos_mobillading"] == "Nei"


def test_parse_ad_detail_feature_flags_unknown_without_equipment_data():
    # Denne annonsen har en tom utstyrsliste i data-props -- vi skal da si
    # "Ukjent" i stedet for å anta at funksjonene mangler.
    html = _read("ad_page_sample.html")
    detail = parsers.parse_ad_detail(html)

    assert detail["hjuldrift"] == "Forhjulsdrift"
    assert detail["utstyrspakke"] == ""
    assert detail["varmepumpe"] == "Ukjent"
    assert detail["head_up_display"] == "Ukjent"
    assert detail["batteri_kapasitet_kwh"] is None


def test_parse_battery_kwh_extracted_from_key_facts_text():
    html = """
    <html><body>
    <script type="application/ld+json">
    {"@type": "Product", "name": "Test EV", "brand": {"name": "TestMerke"}, "model": "TestModell",
     "url": "https://www.finn.no/mobility/item/123456", "offers": {"price": 250000}}
    </script>
    <dl><dt>Batterikapasitet</dt><dd>77 kWh</dd></dl>
    </body></html>
    """
    detail = parsers.parse_ad_detail(html, finn_id="123456", url="https://www.finn.no/mobility/item/123456")

    assert detail["batteri_kapasitet_kwh"] == 77.0
