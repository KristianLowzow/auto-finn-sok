"""Bygger Finn-søk fra merke/modell/filtre og henter resultater.

Bruker fritekstsøk (?q=merke+modell) fordi Finns egne merke/modell-filtre
krever interne, ugjennomsiktige numeriske koder vi ikke kan utlede fra et
merkenavn brukeren skriver inn. Fritekstsøket er bredere enn de interne
filtrene, så resultatene filtreres etterpå mot de strukturerte
merke/modell-feltene fra JSON-LD (parsers.parse_search_results) for å unngå
falske treff.
"""

import logging
from urllib.parse import urlencode

from src import config
from src.parsers import parse_search_results, parse_total_results

logger = logging.getLogger(__name__)

SEARCH_BASE_URL = "https://www.finn.no/mobility/search/car"

_RESULTS_PER_PAGE = 46  # observert på faktiske søkesider, brukes kun til logging


def build_search_url(brand, model, filters=None, page=1):
    filters = filters or {}
    query = " ".join(part for part in (brand, model) if part).strip()
    params = {"q": query, "page": page}
    if filters.get("min_year"):
        params["year_from"] = filters["min_year"]
    if filters.get("max_year"):
        params["year_to"] = filters["max_year"]
    if filters.get("max_price"):
        params["price_to"] = filters["max_price"]
    if filters.get("max_km"):
        params["mileage_to"] = filters["max_km"]
    return f"{SEARCH_BASE_URL}?{urlencode(params)}"


def _matches(entry, brand, model):
    """Filtrerer bort fritekst-treff som ikke faktisk er riktig merke/modell."""
    brand_ok = not brand or brand.strip().lower() in (entry.get("merke") or "").lower()
    model_ok = not model or model.strip().lower() in (entry.get("modell") or "").lower()
    return brand_ok and model_ok


def search_listings(client, brand, model, filters=None):
    """Henter alle (filtrerte) søketreff for ett merke/modell, side for side.

    Returnerer liste av lette dict (finn_id, url, merke, modell, variant, pris, bilde).
    Full detaljhenting skjer separat, kun for nye annonser.
    """
    filters = filters or {}
    all_results = []
    seen_ids = set()

    for page in range(1, config.MAX_SEARCH_PAGES_PER_QUERY + 1):
        url = build_search_url(brand, model, filters, page=page)
        response = client.get(url)
        page_results = parse_search_results(response.text)

        if page == 1:
            total = parse_total_results(response.text)
            logger.info("Søk %s %s: %s totale treff (fritekst, ufiltrert)", brand, model, total)

        if not page_results:
            break

        new_on_page = 0
        for entry in page_results:
            if entry["finn_id"] in seen_ids:
                continue
            seen_ids.add(entry["finn_id"])
            if _matches(entry, brand, model):
                all_results.append(entry)
                new_on_page += 1

        if len(page_results) < _RESULTS_PER_PAGE:
            break  # siste side

    logger.info("Søk %s %s: %d treff etter merke/modell-filtrering", brand, model, len(all_results))
    return all_results


def fetch_detail(client, finn_id, url):
    from src.parsers import parse_ad_detail

    response = client.get(url)
    return parse_ad_detail(response.text, finn_id=finn_id, url=url)
